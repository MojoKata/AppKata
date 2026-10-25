"""Windows specifics (requirement 15): elevation, who an app is for, installers and their Uninstall
entries, shortcuts, junctions, command links, permissions, Authenticode, Mark of the Web, and
registering with Windows. The decisions are pure functions, tested on any OS; the calls into
Windows (ctypes, winreg, PowerShell) are made only on Windows."""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import tempfile
import time

log = logging.getLogger("appkata.windows")

IS_WINDOWS = os.name == "nt"
CREATE_NO_WINDOW = 0x08000000
DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200
UNINSTALL = r"Software\Microsoft\Windows\CurrentVersion\Uninstall"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
APPKATA_UNINSTALL_KEY = "{8E3B9C51-6A2D-4F7E-B1C4-3D5A7E9F0B12}_is1"     # AppKata's own setup (packaging/windows/appkata.iss)
SHIM_MARK = "@rem made by AppKata"

# well-known SIDs, so nothing depends on the language Windows runs in
ADMINS, SYSTEM, USERS, AUTH_USERS, CREATOR_OWNER, TRUSTED_INSTALLER = (
    "S-1-5-32-544", "S-1-5-18", "S-1-5-32-545", "S-1-5-11", "S-1-3-0",
    "S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464")


# ---------------------------------------------------------------- folders (requirement 15.4)
def local_appdata() -> str:
    return os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Local")


def programs_for_me() -> str:
    return os.path.join(local_appdata(), "Programs")


def programs_for_everyone() -> str:
    return (os.environ.get("SystemDrive") or "C:") + "\\Programs"


def command_dir_default() -> str:
    return os.path.join(local_appdata(), "AppKata", "bin")


def start_menu(scope: str) -> str:
    """The Start menu's Programs folder: the user's, or all users' (requirement 15.5)."""
    if scope == "everyone":
        base = os.environ.get("ProgramData") or "C:\\ProgramData"
    else:
        base = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Roaming")
    return os.path.join(base, "Microsoft", "Windows", "Start Menu", "Programs")


# ---------------------------------------------------------------- names and paths (requirement 15.16)
RESERVED = re.compile(r"^(con|prn|aux|nul|com[1-9]|lpt[1-9])(\..*)?$", re.I)


def safe_name(name: str) -> str:
    """A file or folder name Windows accepts: no reserved device names, no trailing dot or space."""
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", name or "") or "_"
    if RESERVED.match(name):
        name = "_" + name
    if name[-1] in ". ":
        name = name.rstrip(". ") + "_"
    return name


def long_path(path: str) -> str:
    """Prefix a long path with \\\\?\\ so it works without Windows' long-path setting."""
    if not IS_WINDOWS or path.startswith("\\\\?\\") or len(path) < 240:
        return path
    p = os.path.abspath(path)
    return "\\\\?\\UNC\\" + p[2:] if p.startswith("\\\\") else "\\\\?\\" + p


# ---------------------------------------------------------------- installers (requirement 15.7)
SILENT = {"inno": "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART", "nsis": "/S", "electron": "/S",
          "wix": "/quiet /norestart", "installshield": "/s", "squirrel": "--silent"}
SCOPE_ARGS = {      # exe kind → (just me, everyone); "" where the installer decides
    "inno": ("/CURRENTUSER", "/ALLUSERS"),
    "electron": ("/currentuser", "/allusers"),
}
ONLY_FOR_ME = {"squirrel", "msix"}


def scopes(kind: str, exe_kind: str = "") -> list[str]:
    """Which of "me" and "everyone" an installer can be asked for; [] when it decides itself."""
    if kind in ("zip",) or (kind == "exe" and exe_kind == "portable"):
        return ["me", "everyone"]
    if kind == "msi" or (kind == "exe" and exe_kind in SCOPE_ARGS):
        return ["me", "everyone"]
    if kind == "msix" or exe_kind in ONLY_FOR_ME:
        return ["me"]
    return []


def installer_command(kind: str, exe_kind: str, file: str, scope: str, log_file: str = "") -> tuple[str, str, bool]:
    """(program, arguments, elevate) to run an installer silently for a scope (requirement 15.7.2).
    An installer AppKata doesn't recognize runs interactively and decides for itself."""
    if kind == "msi":
        args = f'/i "{file}" /qn /norestart' + (f' /l*v "{log_file}"' if log_file else "")
        if scope == "everyone":
            return "msiexec.exe", args + " ALLUSERS=1", True
        return "msiexec.exe", args + " ALLUSERS=2 MSIINSTALLPERUSER=1", False
    silent = SILENT.get(exe_kind, "")
    if not silent:
        return file, "", False
    me, everyone = SCOPE_ARGS.get(exe_kind, ("", ""))
    extra = everyone if scope == "everyone" else me
    return file, (silent + " " + extra).strip(), bool(scope == "everyone" and everyone)


def exe_kind_from_release(asset_names: list[str]) -> str:
    """Installers that announce themselves through the release's other files: electron-builder
    publishes latest.yml, Squirrel.Windows a RELEASES file and .nupkg packages."""
    names = {n.lower() for n in asset_names}
    if "releases" in names or any(n.endswith("-full.nupkg") for n in names):
        return "squirrel"
    if "latest.yml" in names:
        return "electron"
    return ""


EXIT = {0: "ok", 3010: "restart", 1641: "restart", 1602: "cancelled", 1223: "cancelled", 1618: "busy",
        1638: "ok"}          # 1638: a newer version is already installed


def exit_meaning(code: int) -> str:
    """ok, restart (done, Windows must restart), cancelled, busy (another install runs) or failed."""
    return EXIT.get(code, "failed")


# ---------------------------------------------------------------- Uninstall entries (requirement 15.8)
def uninstall_entries() -> dict[str, dict]:
    """Every Uninstall registry entry: HKCU, and HKLM in its 64-bit and 32-bit views."""
    if not IS_WINDOWS:
        return {}
    import winreg
    out: dict[str, dict] = {}
    for hive, hname, views in ((winreg.HKEY_CURRENT_USER, "HKCU", [0]),
                               (winreg.HKEY_LOCAL_MACHINE, "HKLM", [winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY])):
        for view in views:
            try:
                root = winreg.OpenKey(hive, UNINSTALL, 0, winreg.KEY_READ | view)
            except OSError:
                continue
            with root:
                i = 0
                while True:
                    try:
                        sub = winreg.EnumKey(root, i)
                    except OSError:
                        break
                    i += 1
                    try:
                        with winreg.OpenKey(root, sub) as k:
                            e = {"hive": hname, "key": sub, "wow32": view == winreg.KEY_WOW64_32KEY}
                            for v in ("DisplayName", "DisplayVersion", "UninstallString", "QuietUninstallString",
                                      "InstallLocation", "DisplayIcon", "Publisher", "WindowsInstaller", "SystemComponent"):
                                try:
                                    e[v] = winreg.QueryValueEx(k, v)[0]
                                except OSError:
                                    pass
                    except OSError:
                        continue
                    out[entry_id(e)] = e
    return out


def entry_id(e: dict) -> str:
    return f"{e['hive']}{'32' if e.get('wow32') else ''}\\{e['key']}"


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def changed_entry(before: dict[str, dict], after: dict[str, dict], names: list[str]) -> dict | None:
    """The Uninstall entry an installer made or changed: new, or with a new version; the one whose
    name matches the app when there are several."""
    changes = [e for k, e in after.items() if k not in before or before[k].get("DisplayVersion") != e.get("DisplayVersion")]
    changes = [e for e in changes if not e.get("SystemComponent")] or changes
    if not changes:
        return None
    wants = [_norm(n) for n in names if _norm(n)]
    for e in changes:
        dn = _norm(e.get("DisplayName", ""))
        if dn and any(w in dn or dn in w for w in wants):
            return e
    return changes[0] if len(changes) == 1 else None


def find_entry(entries: dict[str, dict], names: list[str]) -> dict | None:
    """An existing entry for an app, by its display name (used to find AppKata's own and foreign installs)."""
    wants = [_norm(n) for n in names if _norm(n)]
    for e in entries.values():
        if _norm(e.get("DisplayName", "")) in wants:
            return e
    return None


def split_command(cmd: str) -> tuple[str, str]:
    """A command line from the registry, as (program, arguments)."""
    cmd = (cmd or "").strip()
    if cmd.startswith('"'):
        end = cmd.find('"', 1)
        return (cmd[1:end], cmd[end + 1:].strip()) if end > 0 else (cmd.strip('"'), "")
    m = re.match(r"(.+?\.exe)(\s.*)?$", cmd, re.I)
    if m:
        return m.group(1), (m.group(2) or "").strip()
    parts = cmd.split(" ", 1)
    return parts[0], parts[1] if len(parts) > 1 else ""


def uninstall_command(entry: dict, exe_kind: str = "") -> tuple[str, str, bool]:
    """(program, arguments, elevate) that removes what an entry describes (requirement 15.8.2)."""
    elevate = entry.get("hive") == "HKLM"
    if entry.get("QuietUninstallString"):
        prog, args = split_command(entry["QuietUninstallString"])
        return prog, args, elevate
    if entry.get("WindowsInstaller") == 1 or re.match(r"^\{[0-9A-F-]{36}\}$", entry.get("key", ""), re.I) and \
            "msiexec" in (entry.get("UninstallString") or "").lower():
        return "msiexec.exe", f"/x {entry['key']} /qn /norestart", elevate
    prog, args = split_command(entry.get("UninstallString", ""))
    if not prog:
        return "", "", elevate
    low = args.lower()
    if exe_kind == "squirrel" or os.path.basename(prog).lower() == "update.exe":
        extra = "" if "-s" in low.split() else "-s"
    elif exe_kind == "inno" or re.match(r"unins\d+\.exe$", os.path.basename(prog), re.I):
        extra = "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART"
    elif exe_kind == "wix" or "/uninstall" in low:
        extra = "" if "/quiet" in low else "/quiet /norestart"
    elif exe_kind in ("nsis", "electron"):
        extra = "" if "/s" in low.split() else "/S"
    else:
        extra = ""
    return prog, (args + " " + extra).strip(), elevate


# ---------------------------------------------------------------- running programs (requirement 15.2)
def shell_execute(program: str, args: str = "", elevate: bool = False, wait: bool = True, cwd: str = "",
                  show: int = 1, timeout: float = 3600) -> int:
    """Start a program through the shell, as Explorer does: Windows asks for administrator rights
    (UAC) when `elevate` or when the program's manifest needs them, and SmartScreen checks files
    with the Mark of the Web. Returns the exit code (1223 when the UAC prompt was declined)."""
    import ctypes
    from ctypes import wintypes

    class SHELLEXECUTEINFOW(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("fMask", wintypes.ULONG), ("hwnd", wintypes.HWND),
                    ("lpVerb", wintypes.LPCWSTR), ("lpFile", wintypes.LPCWSTR), ("lpParameters", wintypes.LPCWSTR),
                    ("lpDirectory", wintypes.LPCWSTR), ("nShow", ctypes.c_int), ("hInstApp", wintypes.HINSTANCE),
                    ("lpIDList", ctypes.c_void_p), ("lpClass", wintypes.LPCWSTR), ("hkeyClass", wintypes.HKEY),
                    ("dwHotKey", wintypes.DWORD), ("hIconOrMonitor", wintypes.HANDLE), ("hProcess", wintypes.HANDLE)]

    SEE_MASK_NOCLOSEPROCESS, SEE_MASK_NOASYNC, SEE_MASK_FLAG_NO_UI = 0x40, 0x100, 0x400
    info = SHELLEXECUTEINFOW()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = SEE_MASK_NOCLOSEPROCESS | SEE_MASK_NOASYNC | SEE_MASK_FLAG_NO_UI
    info.lpVerb = "runas" if elevate else "open"
    info.lpFile = program
    info.lpParameters = args or None
    info.lpDirectory = cwd or None
    info.nShow = show
    shell32, kernel32 = ctypes.windll.shell32, ctypes.windll.kernel32
    shell32.ShellExecuteExW.argtypes = [ctypes.POINTER(SHELLEXECUTEINFOW)]
    log.info("run%s: %s %s", " (elevated)" if elevate else "", program, args)
    if not shell32.ShellExecuteExW(ctypes.byref(info)):
        err = ctypes.GetLastError()
        if err == 1223:
            return 1223
        raise OSError(err, ctypes.FormatError(err).strip(), program)
    if not info.hProcess:
        return 0
    try:
        if not wait:
            return 0
        kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        end = time.monotonic() + timeout
        while kernel32.WaitForSingleObject(info.hProcess, 500) == 0x102:        # WAIT_TIMEOUT
            if time.monotonic() > end:
                raise TimeoutError(f"{os.path.basename(program)} didn't finish")
        code = wintypes.DWORD()
        kernel32.GetExitCodeProcess(info.hProcess, ctypes.byref(code))
        log.info("exit code %d: %s", code.value, os.path.basename(program))
        return code.value
    finally:
        kernel32.CloseHandle(info.hProcess)


def run_hidden(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, creationflags=CREATE_NO_WINDOW if IS_WINDOWS else 0, **kw)


def powershell(script: str, env: dict | None = None, timeout: float = 120) -> str:
    """Run a PowerShell script (values passed in environment variables, never pasted into it)."""
    p = run_hidden(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
                   env={**os.environ, **(env or {})}, timeout=timeout)
    if p.returncode:
        raise OSError(p.returncode, (p.stderr or p.stdout).strip().splitlines()[-1] if (p.stderr or p.stdout).strip() else "PowerShell failed")
    return p.stdout


def launch(program: str, args: list[str] | None = None, through_shell: bool = False) -> None:
    """Start an app detached from AppKata, so it keeps running when AppKata quits (requirement 15.16)."""
    if through_shell:           # Mark of the Web: let SmartScreen look at it (requirement 15.11.1)
        shell_execute(program, subprocess.list2cmdline(args or []), wait=False, cwd=os.path.dirname(program))
        return
    subprocess.Popen([program, *(args or [])], cwd=os.path.dirname(program) or None, close_fds=True,
                     creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def processes_in(folder: str) -> list[str]:
    """Programs running from a folder (requirement 15.9): their paths."""
    if not IS_WINDOWS:
        return []
    import ctypes
    from ctypes import wintypes
    psapi, kernel32 = ctypes.windll.psapi, ctypes.windll.kernel32
    arr = (wintypes.DWORD * 4096)()
    needed = wintypes.DWORD()
    if not psapi.EnumProcesses(arr, ctypes.sizeof(arr), ctypes.byref(needed)):
        return []
    kernel32.OpenProcess.restype = wintypes.HANDLE
    root = os.path.normcase(os.path.realpath(folder)) + os.sep
    out = []
    for pid in arr[:needed.value // ctypes.sizeof(wintypes.DWORD)]:
        h = kernel32.OpenProcess(0x1000, False, pid)            # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            continue
        try:
            buf = ctypes.create_unicode_buffer(1024)
            size = wintypes.DWORD(1024)
            if kernel32.QueryFullProcessImageNameW(wintypes.HANDLE(h), 0, buf, ctypes.byref(size)):
                if os.path.normcase(buf.value).startswith(root):
                    out.append(buf.value)
        finally:
            kernel32.CloseHandle(wintypes.HANDLE(h))
    return out


# ---------------------------------------------------------------- junctions, shortcuts, command links (15.5, 15.6)
def is_junction(path: str) -> bool:
    if hasattr(os.path, "isjunction"):
        return os.path.isjunction(path)
    try:
        import stat
        return bool(os.lstat(path).st_reparse_tag == stat.IO_REPARSE_TAG_MOUNT_POINT)   # type: ignore[attr-defined]
    except (OSError, AttributeError):
        return False


def make_junction(target: str, link: str) -> None:
    """A directory junction: like a symbolic link to a folder, but needs no extra rights."""
    if is_junction(link):
        os.rmdir(link)
    elif os.path.lexists(link):
        raise FileExistsError(f"{link} exists and isn't a junction AppKata made")
    import _winapi
    _winapi.CreateJunction(os.path.abspath(target), os.path.abspath(link))


def remove_link(path: str) -> None:
    """Remove a junction, symbolic link or AppKata file, never what it points at."""
    if is_junction(path):
        os.rmdir(path)
    elif os.path.islink(path) or os.path.isfile(path):
        os.remove(path)


def make_shortcut(lnk: str, target: str, elevate: bool = False, description: str = "") -> None:
    """A Start-menu .lnk with the program's own icon and folder (requirement 15.5). For the
    all-users Start menu, it's made in a temporary folder and copied there with administrator rights."""
    dest = lnk
    if elevate:
        lnk = os.path.join(tempfile.mkdtemp(prefix="appkata-lnk-"), os.path.basename(dest))
    else:
        os.makedirs(os.path.dirname(lnk), exist_ok=True)
    powershell("$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:AK_LNK); $s.TargetPath=$env:AK_T;"
               "$s.WorkingDirectory=$env:AK_W; $s.IconLocation=$env:AK_T + ',0'; $s.Description=$env:AK_D; $s.Save()",
               {"AK_LNK": lnk, "AK_T": target, "AK_W": os.path.dirname(target), "AK_D": description[:250]})
    if elevate:
        folder = os.path.dirname(dest)
        code = shell_execute("cmd.exe", f'/c (if not exist "{folder}" mkdir "{folder}") & copy /y "{lnk}" "{dest}"', elevate=True, show=0)
        if code:
            raise OSError(code, "couldn't add the shortcut to the all-users Start menu" if code != 1223 else "cancelled")


def remove_shortcut(lnk: str, elevate: bool = False) -> None:
    if not os.path.exists(lnk):
        return
    if elevate:
        shell_execute("cmd.exe", f'/c del /f /q "{lnk}"', elevate=True, show=0)
    else:
        os.remove(lnk)


def shim_text(program: str) -> str:
    """A command link (requirement 15.6): a .cmd file that runs the program with its arguments."""
    return f'{SHIM_MARK}\r\n@"{program}" %*\r\n'


def write_shim(folder: str, name: str, program: str) -> str:
    path = os.path.join(folder, name + ".cmd")
    if os.path.exists(path):
        with open(path, encoding="utf-8", errors="replace") as f:
            if not f.read().startswith(SHIM_MARK):
                raise FileExistsError(f"{path} exists and isn't a command link AppKata made; not replacing it")
    os.makedirs(folder, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(shim_text(program))
    if IS_WINDOWS:
        add_to_user_path(folder)
    return path


def remove_shim(path: str) -> None:
    if not os.path.exists(path):
        return
    os.remove(path)
    folder = os.path.dirname(path)
    if IS_WINDOWS and not any(f.lower().endswith(".cmd") for f in os.listdir(folder)):
        remove_from_user_path(folder)


def path_with(path_value: str, folder: str) -> str:
    parts = [p for p in (path_value or "").split(";") if p]
    if any(os.path.normcase(p.rstrip("\\")) == os.path.normcase(folder.rstrip("\\")) for p in parts):
        return path_value
    return ";".join(parts + [folder])


def path_without(path_value: str, folder: str) -> str:
    return ";".join(p for p in (path_value or "").split(";") if p and
                    os.path.normcase(p.rstrip("\\")) != os.path.normcase(folder.rstrip("\\")))


def _user_path(update) -> None:
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_READ | winreg.KEY_WRITE) as k:
        try:
            cur, kind = winreg.QueryValueEx(k, "Path")
        except OSError:
            cur, kind = "", winreg.REG_EXPAND_SZ
        new = update(cur)
        if new == cur:
            return
        winreg.SetValueEx(k, "Path", 0, kind, new)
    _broadcast_environment()


def add_to_user_path(folder: str) -> None:
    _user_path(lambda cur: path_with(cur, folder))


def remove_from_user_path(folder: str) -> None:
    _user_path(lambda cur: path_without(cur, folder))


def _broadcast_environment() -> None:
    import ctypes
    from ctypes import wintypes
    result = wintypes.DWORD()
    ctypes.windll.user32.SendMessageTimeoutW(0xFFFF, 0x001A, 0, "Environment", 0x0002, 5000, ctypes.byref(result))


# ---------------------------------------------------------------- permissions (requirement 15.4.3)
WRITE_BITS = (0x2 | 0x4 | 0x10 | 0x40 | 0x100 | 0x10000 | 0x40000 | 0x80000 | 0x40000000 | 0x10000000)
APPEND_DATA = 0x4           # "create folders" on a folder


def acl_problem(acl: dict, me: str, root: bool) -> str:
    """Why a folder isn't protected, or "" (requirement 15.4.3). `acl` is what read_acl() returns:
    {owner, protected, rules: [{sid, rights, type, inh, prop}]}. Only you, Administrators, SYSTEM
    and (for subfolders) CREATOR OWNER may change it; on the Programs folder itself, Users may only
    create folders."""
    owners = {me, ADMINS, SYSTEM, TRUSTED_INSTALLER}
    if acl.get("owner") not in owners:
        return "it belongs to another account"
    if not acl.get("protected"):
        return "it inherits permissions that let other accounts change it"
    for r in acl.get("rules", []):
        if r.get("type") != "Allow" or r.get("sid") in owners:
            continue
        rights = int(r.get("rights") or 0)
        if r.get("sid") == CREATOR_OWNER and root and r.get("prop", 0) & 2:      # inherit-only: subfolders' creators
            continue
        if root and r.get("sid") == USERS and not r.get("inh") and rights & WRITE_BITS == APPEND_DATA:
            continue
        if rights & WRITE_BITS:
            return f"another account ({r.get('sid')}) can change it"
    return ""


def read_acl(path: str) -> tuple[dict, str]:
    """(acl, my SID) of a folder, read with PowerShell."""
    out = powershell(
        "$a=Get-Acl -LiteralPath $env:AK_P; $me=[Security.Principal.WindowsIdentity]::GetCurrent().User.Value;"
        "$r=@($a.GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier]) | % { @{sid=$_.IdentityReference.Value;"
        " rights=[int64]$_.FileSystemRights; type=[string]$_.AccessControlType; inh=[int]$_.InheritanceFlags; prop=[int]$_.PropagationFlags} });"
        "@{owner=$a.GetOwner([Security.Principal.SecurityIdentifier]).Value; protected=$a.AreAccessRulesProtected; rules=$r; me=$me}"
        " | ConvertTo-Json -Depth 4 -Compress", {"AK_P": path})
    d = json.loads(out)
    rules = d.get("rules") or []
    d["rules"] = rules if isinstance(rules, list) else [rules]
    return d, d.get("me", "")


def protect(path: str, me: str, root: bool) -> None:
    """Set the permissions of requirement 15.4.3 on the Programs folder (root) or an app's folder."""
    if root:
        grants = [f"*{ADMINS}:(OI)(CI)F", f"*{SYSTEM}:(OI)(CI)F", f"*{CREATOR_OWNER}:(OI)(CI)(IO)F",
                  f"*{USERS}:(OI)(CI)RX", f"*{USERS}:(AD)"]
    else:
        grants = [f"*{me}:(OI)(CI)F", f"*{ADMINS}:(OI)(CI)F", f"*{SYSTEM}:(OI)(CI)F", f"*{USERS}:(OI)(CI)RX"]
    p = run_hidden(["icacls", path, "/inheritance:r", "/grant:r", *grants])
    if p.returncode:
        raise OSError(p.returncode, f"couldn't set the permissions of {path}: {(p.stdout + p.stderr).strip()}")
    keep = {g.split(":")[0][1:] for g in grants}
    acl, _ = read_acl(path)
    others = sorted({r["sid"] for r in acl.get("rules", []) if r.get("sid") not in keep})
    if others:         # /grant:r only replaces the grants it names: remove everyone else's
        p = run_hidden(["icacls", path, "/remove", *[f"*{sid}" for sid in others]])
        if p.returncode:
            raise OSError(p.returncode, f"couldn't set the permissions of {path}: {(p.stdout + p.stderr).strip()}")


def secure_folder(path: str, root: bool) -> None:
    """Create a folder for everyone's apps, or check one, so no other account can change what's in it.
    A folder AppKata's user owns is (re)protected; anyone else's is refused (requirement 15.4.3)."""
    created = not os.path.isdir(path)
    os.makedirs(path, exist_ok=True)
    acl, me = read_acl(path)
    problem = acl_problem(acl, me, root)
    if problem and (created or acl.get("owner") in (me, ADMINS)):
        protect(path, me, root)
        acl, me = read_acl(path)
        problem = acl_problem(acl, me, root)
    if problem:
        raise PermissionError(f"{path} isn't safe for apps for everyone: {problem}")


# ---------------------------------------------------------------- Authenticode, Mark of the Web (15.11)
def authenticode(path: str) -> tuple[str, str]:
    """(status, signer) from Windows' signature check: Valid, NotSigned, HashMismatch, NotTrusted, …"""
    try:
        d = json.loads(powershell(
            "$s=Get-AuthenticodeSignature -LiteralPath $env:AK_P; @{status=[string]$s.Status; signer=$(if ($s.SignerCertificate)"
            " { $s.SignerCertificate.GetNameInfo('SimpleName',$false) } else { '' })} | ConvertTo-Json -Compress", {"AK_P": path}))
        return d.get("status", ""), d.get("signer") or ""
    except (OSError, ValueError) as e:
        log.warning("Authenticode check of %s failed: %s", path, e)
        return "", ""


def signature_verdict(status: str) -> str:
    """"signed" (Verified), "bad" (blocks the install) or "" (judged by its checksum alone)."""
    if status == "Valid":
        return "signed"
    if status == "HashMismatch":          # signed, but the file was changed since
        return "bad"
    return ""


def zone_identifier(url: str) -> str:
    return f"[ZoneTransfer]\r\nZoneId=3\r\nHostUrl={url}\r\n"


def mark_of_web(path: str, url: str) -> None:
    """Mark a file as downloaded from the internet, as a browser does (requirement 15.11.1)."""
    try:
        with open(path + ":Zone.Identifier", "w", newline="") as f:
            f.write(zone_identifier(url))
    except OSError as e:
        log.warning("couldn't mark %s: %s", path, e)


def mark_tree(folder: str, url: str) -> None:
    for dp, _, fs in os.walk(folder):
        for f in fs:
            mark_of_web(os.path.join(dp, f), url)


# ---------------------------------------------------------------- .msix (requirement 15.7.4)
def msix_name(file: str) -> str:
    """The package name in an .msix's AppxManifest.xml."""
    import zipfile
    import xml.etree.ElementTree as ET
    with zipfile.ZipFile(file) as z:
        root = ET.fromstring(z.read("AppxManifest.xml"))
    for el in root.iter():
        if el.tag.endswith("Identity"):
            return el.get("Name", "")
    return ""


def msix_install(file: str) -> str:
    """Install for the current user; returns the package's full name."""
    name = msix_name(file)
    powershell("Add-AppxPackage -Path $env:AK_P -ForceApplicationShutdown", {"AK_P": file}, timeout=1800)
    out = powershell("(Get-AppxPackage -Name $env:AK_N | Select -First 1).PackageFullName", {"AK_N": name}).strip()
    return out


def msix_remove(full_name: str) -> None:
    powershell("Remove-AppxPackage -Package $env:AK_N", {"AK_N": full_name}, timeout=600)


# ---------------------------------------------------------------- registering with Windows (15.14)
def _hkcu_set(path: str, values: dict[str, str]) -> None:
    import winreg
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, path) as k:
        for name, value in values.items():
            winreg.SetValueEx(k, name or None, 0, winreg.REG_SZ, value)


def autostart_get() -> str:
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            return winreg.QueryValueEx(k, "AppKata")[0]
    except OSError:
        return ""


def autostart_set(command: str) -> None:
    """command "" removes the value."""
    import winreg
    if command:
        _hkcu_set(RUN_KEY, {"AppKata": command})
        return
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            winreg.DeleteValue(k, "AppKata")
    except OSError:
        pass


def scheme_get() -> str:
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Classes\appkata\shell\open\command") as k:
            return winreg.QueryValueEx(k, None)[0]
    except OSError:
        return ""


def scheme_set(command: str) -> None:
    """appkata:// links (requirement 11.3); command "" removes the handler."""
    import winreg
    if command:
        _hkcu_set(r"Software\Classes\appkata", {"": "URL:AppKata link", "URL Protocol": ""})
        _hkcu_set(r"Software\Classes\appkata\shell\open\command", {"": command})
        return
    for sub in (r"shell\open\command", r"shell\open", "shell", ""):
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, r"Software\Classes\appkata" + ("\\" + sub if sub else ""))
        except OSError:
            pass


# ---------------------------------------------------------------- what else is installed (requirement 15.12)
def inventory() -> dict[str, tuple[str, str]]:
    """normalized name → (where, version) for apps installed on this computer."""
    found: dict[str, tuple[str, str]] = {}
    for e in uninstall_entries().values():
        if e.get("SystemComponent") or not e.get("DisplayName") or e.get("key") == APPKATA_UNINSTALL_KEY:
            continue
        found.setdefault(_norm(e["DisplayName"]), (f"Windows apps ({e['DisplayName']})", str(e.get("DisplayVersion") or "")))
        found.setdefault(_norm(re.sub(r"\s+\(?(x64|64-bit|\d[\d.]*)\)?.*$", "", e["DisplayName"])), (f"Windows apps ({e['DisplayName']})",
                                                                                              str(e.get("DisplayVersion") or "")))
    home = os.path.expanduser("~")
    for base, label in ((os.path.join(home, "scoop", "apps"), "Scoop"),
                        (os.path.join(os.environ.get("ProgramData") or "C:\\ProgramData", "chocolatey", "lib"), "Chocolatey")):
        if os.path.isdir(base):
            for name in os.listdir(base):
                found.setdefault(_norm(name), (f"{label} ({name})", ""))
    for scope in ("me", "everyone"):
        for dp, _, fs in os.walk(start_menu(scope)):
            for f in fs:
                if f.lower().endswith(".lnk") and not re.search(r"uninstall|readme|help|website", f, re.I):
                    found.setdefault(_norm(f[:-4]), (os.path.join(dp, f), ""))
    try:
        out = powershell("Get-AppxPackage | ? { -not $_.IsFramework -and $_.SignatureKind -ne 'System' } | Select Name, Version"
                         " | ConvertTo-Json -Compress", timeout=60)
        pkgs = json.loads(out or "[]")
        for p in pkgs if isinstance(pkgs, list) else [pkgs]:
            n = (p.get("Name") or "").rsplit(".", 1)[-1]
            found.setdefault(_norm(n), (f"Microsoft Store ({p.get('Name')})", p.get("Version") or ""))
    except (OSError, ValueError):
        pass
    return found


# ---------------------------------------------------------------- the Visual C++ run-time (requirement 15.18)
MSVC_DLL = re.compile(r"^(vcruntime140(_\d+)?|msvcp140(_\w+)?|concrt140|vcomp140|vccorlib140)\.dll$", re.I)
VC_REDIST_URL = "https://aka.ms/vs/17/release/vc_redist.x64.exe"
VC_RUNTIME_KEY = r"SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64"


def pe_imports(path: str) -> list[str]:
    """The DLLs a Windows program or library imports (its import and delay-load tables), read
    from its headers; [] for anything that isn't a readable PE file."""
    import struct
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError:
        return []
    try:
        if data[:2] != b"MZ":
            return []
        pe = struct.unpack_from("<I", data, 0x3C)[0]
        if data[pe:pe + 4] != b"PE\0\0":
            return []
        nsect, opt_size = struct.unpack_from("<H", data, pe + 6)[0], struct.unpack_from("<H", data, pe + 20)[0]
        opt = pe + 24
        magic = struct.unpack_from("<H", data, opt)[0]
        dirs = opt + (112 if magic == 0x20B else 96)
        ndirs = struct.unpack_from("<I", data, dirs - 4)[0]
        sections = []
        for i in range(nsect):
            off = opt + opt_size + 40 * i
            vsize, vaddr, rsize, rptr = struct.unpack_from("<IIII", data, off + 8)
            sections.append((vaddr, max(vsize, rsize), rptr))

        def at(rva: int) -> int:
            for vaddr, size, rptr in sections:
                if vaddr <= rva < vaddr + size:
                    return rptr + rva - vaddr
            return -1

        def name(rva: int) -> str:
            o = at(rva)
            if o < 0:
                return ""
            end = data.find(b"\0", o, o + 260)
            return data[o:end].decode("ascii", "replace") if end > o else ""

        out: list[str] = []
        if ndirs > 1:                       # imports: 20-byte descriptors, name at +12
            rva = struct.unpack_from("<I", data, dirs + 8)[0]
            o = at(rva) if rva else -1
            while o >= 0 and o + 20 <= len(data) and any(data[o:o + 20]):
                if n := name(struct.unpack_from("<I", data, o + 12)[0]):
                    out.append(n)
                o += 20
        if ndirs > 13:                      # delay-loaded imports: 32-byte descriptors, name at +4
            rva = struct.unpack_from("<I", data, dirs + 13 * 8)[0]
            o = at(rva) if rva else -1
            while o >= 0 and o + 32 <= len(data) and any(data[o:o + 32]):
                if n := name(struct.unpack_from("<I", data, o + 4)[0]):
                    out.append(n)
                o += 32
        return out
    except (struct.error, IndexError):
        return []


def needs_msvcrt(folder: str) -> bool:
    """Whether a program in the folder imports a Visual C++ run-time DLL the folder doesn't carry."""
    files = [os.path.join(dp, f) for dp, _, fs in os.walk(folder) for f in fs]
    local = {os.path.basename(f).lower() for f in files}
    for f in files:
        if f.lower().endswith((".exe", ".dll")):
            if any(MSVC_DLL.match(d) and d.lower() not in local for d in pe_imports(f)):
                return True
    return False


def msvcrt_installed() -> str:
    """The installed Visual C++ 2015–2022 run-time's version (x64), or "" when it's missing."""
    if not IS_WINDOWS:
        return ""
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, VC_RUNTIME_KEY, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as k:
            if winreg.QueryValueEx(k, "Installed")[0] == 1:
                return str(winreg.QueryValueEx(k, "Version")[0])
    except OSError:
        pass
    sysdir = os.path.join(os.environ.get("SystemRoot", "C:\\Windows"), "System32")
    return "present" if os.path.isfile(os.path.join(sysdir, "vcruntime140.dll")) else ""


# ---------------------------------------------------------------- git's gpg (requirement 15.15)
def git_gpg() -> str:
    """gpg.exe from Git for Windows (its usr\\bin isn't on the PATH)."""
    try:
        p = run_hidden(["git", "--exec-path"], timeout=10)
    except OSError:
        return ""
    d = p.stdout.strip().replace("/", "\\")
    for _ in range(4):
        cand = os.path.join(d, "usr", "bin", "gpg.exe")
        if os.path.isfile(cand):
            return cand
        d = os.path.dirname(d)
    return ""
