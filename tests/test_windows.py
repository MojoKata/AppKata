"""Windows decisions (requirement 15), tested on any OS: installer arguments and scopes, exit
codes, Uninstall entries, command links, PATH, folder permissions, names, and file order."""

import os

import pytest

from appkata_core import windows as w
from appkata_core.assets import candidates, choose, exe_type
from appkata_core.forges import Asset

from test_install_review import APP, env, server  # noqa: F401  (fixtures)


def test_safe_names():
    assert w.safe_name("con") == "_con" and w.safe_name("NUL.txt") == "_NUL.txt" and w.safe_name("com1") == "_com1"
    assert w.safe_name("console") == "console"
    assert w.safe_name("app.") == "app_" and w.safe_name("app ") == "app_"
    assert w.safe_name('a<b>:c"d|e?f*') == "a_b_c_d_e_f_"


def test_installer_arguments_by_scope():
    prog, args, elev = w.installer_command("msi", "", r"C:\d\x.msi", "me", r"C:\d\msi.log")
    assert prog == "msiexec.exe" and "/qn" in args and "MSIINSTALLPERUSER=1" in args and '/l*v "C:\\d\\msi.log"' in args and not elev
    assert w.installer_command("msi", "", "x.msi", "everyone")[1].endswith("ALLUSERS=1") and w.installer_command("msi", "", "x.msi", "everyone")[2]
    assert w.installer_command("exe", "inno", "s.exe", "me") == ("s.exe", "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /CURRENTUSER", False)
    assert w.installer_command("exe", "inno", "s.exe", "everyone") == ("s.exe", "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /ALLUSERS", True)
    assert w.installer_command("exe", "electron", "s.exe", "me") == ("s.exe", "/S /currentuser", False)
    assert w.installer_command("exe", "electron", "s.exe", "everyone") == ("s.exe", "/S /allusers", True)
    # the installer decides who it's for: no scope argument, no forced elevation
    assert w.installer_command("exe", "nsis", "s.exe", "everyone") == ("s.exe", "/S", False)
    assert w.installer_command("exe", "squirrel", "s.exe", "me") == ("s.exe", "--silent", False)
    # unrecognized: interactive
    assert w.installer_command("exe", "installer", "s.exe", "me") == ("s.exe", "", False)


def test_scopes_offered():
    assert w.scopes("zip") == ["me", "everyone"] and w.scopes("exe", "portable") == ["me", "everyone"]
    assert w.scopes("msi") == ["me", "everyone"] and w.scopes("exe", "inno") == ["me", "everyone"]
    assert w.scopes("exe", "electron") == ["me", "everyone"]
    assert w.scopes("msix") == ["me"] and w.scopes("exe", "squirrel") == ["me"]
    assert w.scopes("exe", "nsis") == [] and w.scopes("exe", "wix") == []


def test_exit_codes():
    assert [w.exit_meaning(c) for c in (0, 3010, 1641, 1602, 1223, 1618, 1603)] == \
        ["ok", "restart", "restart", "cancelled", "cancelled", "busy", "failed"]


def test_installers_known_by_their_release():
    assert w.exe_kind_from_release(["App-Setup-1.2.exe", "latest.yml", "App-Setup-1.2.exe.blockmap"]) == "electron"
    assert w.exe_kind_from_release(["Setup.exe", "RELEASES", "App-1.2-full.nupkg"]) == "squirrel"
    assert w.exe_kind_from_release(["App-1.2.exe"]) == ""
    nsis = b"xx NullsoftInst yy"
    assert exe_type("App-Setup-1.2.exe", nsis, ["App-Setup-1.2.exe", "latest.yml"]) == "electron"
    assert exe_type("App-Setup-1.2.exe", nsis, []) == "nsis"
    assert exe_type("App-Setup.exe", b"", ["App-Setup.exe", "RELEASES", "App-1-full.nupkg"]) == "squirrel"
    assert exe_type("App-1.2-portable.exe", b"", ["App-1.2-portable.exe", "latest.yml"]) == "portable"
    assert exe_type("x.exe", b"Inno Setup Setup Data", ["latest.yml"]) == "inno"
    assert exe_type("Git-2.56.0-64-bit.exe", "..InnoSetupLdrWindow..".encode("utf-16-le")) == "inno"      # Inno Setup 6.3+


def entry(hive, key, name, version="1.0", **kw):
    return {"hive": hive, "key": key, "wow32": False, "DisplayName": name, "DisplayVersion": version, **kw}


def test_finding_the_entry_an_installer_made():
    before = {"HKCU\\a": entry("HKCU", "a", "Other App")}
    new = entry("HKCU", "kpx", "KeePassXC", "2.7.9")
    after = {**before, "HKCU\\kpx": new}
    assert w.changed_entry(before, after, ["KeePassXC"]) == new
    # an update changes the version of an existing entry
    upd = entry("HKCU", "kpx", "KeePassXC", "2.7.10")
    assert w.changed_entry(after, {**before, "HKCU\\kpx": upd}, ["KeePassXC"]) == upd
    # several changes: the one named like the app; none matching and several: unknown
    other = entry("HKLM", "vc", "Microsoft Visual C++ 2015-2022 Redistributable")
    both = {**before, "HKCU\\kpx": new, "HKLM\\vc": other}
    assert w.changed_entry(before, both, ["KeePassXC"]) == new
    assert w.changed_entry(before, both, ["Something"]) is None
    assert w.changed_entry(before, before, ["KeePassXC"]) is None
    assert w.entry_id(entry("HKLM", "{X}", "n", wow32=True)) == "HKLM32\\{X}"


def test_uninstall_commands():
    assert w.split_command('"C:\\P F\\unins000.exe" /SILENT') == ("C:\\P F\\unins000.exe", "/SILENT")
    assert w.split_command("C:\\Apps\\x\\uninst.exe") == ("C:\\Apps\\x\\uninst.exe", "")
    quiet = entry("HKCU", "k", "A", QuietUninstallString='"C:\\a\\u.exe" /quiet')
    assert w.uninstall_command(quiet) == ("C:\\a\\u.exe", "/quiet", False)
    msi = entry("HKLM", "{12345678-1234-1234-1234-123456789ABC}", "A", UninstallString="MsiExec.exe /X{12345678-1234-1234-1234-123456789ABC}",
                WindowsInstaller=1)
    assert w.uninstall_command(msi) == ("msiexec.exe", "/x {12345678-1234-1234-1234-123456789ABC} /qn /norestart", True)
    inno = entry("HKCU", "x_is1", "A", UninstallString='"C:\\a\\unins000.exe"')
    assert w.uninstall_command(inno, "inno") == ("C:\\a\\unins000.exe", "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART", False)
    nsis = entry("HKLM", "A", "A", UninstallString='"C:\\Program Files\\A\\Uninstall A.exe" /currentuser')
    assert w.uninstall_command(nsis, "electron") == ("C:\\Program Files\\A\\Uninstall A.exe", "/currentuser /S", True)
    sq = entry("HKCU", "app", "A", UninstallString='"C:\\Users\\u\\AppData\\Local\\app\\Update.exe" --uninstall')
    assert w.uninstall_command(sq, "squirrel") == ("C:\\Users\\u\\AppData\\Local\\app\\Update.exe", "--uninstall -s", False)


def test_path_edits():
    assert w.path_with("C:\\a;C:\\b", "C:\\x") == "C:\\a;C:\\b;C:\\x"
    assert w.path_with("C:\\a;C:\\x", "C:\\x") == "C:\\a;C:\\x"
    assert w.path_with("", "C:\\x") == "C:\\x"
    assert w.path_without("C:\\a;C:\\x;C:\\b", "C:\\x") == "C:\\a;C:\\b"


def test_command_links(tmp_path):
    text = w.shim_text("C:\\Programs\\localsend\\current\\localsend.exe")
    assert text.startswith(w.SHIM_MARK) and '@"C:\\Programs\\localsend\\current\\localsend.exe" %*' in text
    p = w.write_shim(str(tmp_path), "localsend", "C:\\x.exe")
    assert os.path.basename(p) == "localsend.cmd"
    w.write_shim(str(tmp_path), "localsend", "C:\\y.exe")         # its own: replaced
    (tmp_path / "mine.cmd").write_text("@echo hello\r\n")
    with pytest.raises(FileExistsError):
        w.write_shim(str(tmp_path), "mine", "C:\\z.exe")             # someone else's: never
    w.remove_shim(p)
    assert not os.path.exists(p)


ME = "S-1-5-21-1-2-3-1001"


def rule(sid, rights, inh=3, prop=0, kind="Allow"):
    return {"sid": sid, "rights": rights, "type": kind, "inh": inh, "prop": prop}


FULL, RX = 0x1F01FF, 0x1200A9


def test_folder_permissions():
    app = {"owner": ME, "protected": True, "rules": [rule(ME, FULL), rule(w.ADMINS, FULL), rule(w.SYSTEM, FULL), rule(w.USERS, RX)]}
    assert w.acl_problem(app, ME, root=False) == ""
    assert "inherits" in w.acl_problem({**app, "protected": False}, ME, root=False)
    assert "another account" in w.acl_problem({**app, "owner": "S-1-5-21-9-9-9-1002"}, ME, root=False)
    loose = {**app, "rules": app["rules"] + [rule(w.AUTH_USERS, 0x1301BF)]}       # Modify
    assert w.AUTH_USERS in w.acl_problem(loose, ME, root=False)
    root = {"owner": w.ADMINS, "protected": True,
            "rules": [rule(w.ADMINS, FULL), rule(w.SYSTEM, FULL), rule(w.CREATOR_OWNER, 0x10000000, prop=2),
                      rule(w.USERS, RX), rule(w.USERS, w.APPEND_DATA, inh=0)]}
    assert w.acl_problem(root, ME, root=True) == ""
    # Windows' default for C:\: Authenticated Users may change everything created under it
    default = {**root, "protected": True, "rules": root["rules"] + [rule(w.AUTH_USERS, 0x1301BF, prop=2)]}
    assert w.acl_problem(default, ME, root=True) != ""
    # creating folders is fine on the Programs folder itself, not on an app's folder
    assert w.acl_problem({**app, "rules": app["rules"] + [rule(w.USERS, w.APPEND_DATA, inh=0)]}, ME, root=False) != ""


def test_mark_of_the_web_text():
    assert w.zone_identifier("https://x/y.exe") == "[ZoneTransfer]\r\nZoneId=3\r\nHostUrl=https://x/y.exe\r\n"


def test_signature_verdicts():
    assert w.signature_verdict("Valid") == "signed"
    assert w.signature_verdict("HashMismatch") == "bad"
    assert w.signature_verdict("NotSigned") == "" and w.signature_verdict("NotTrusted") == "" and w.signature_verdict("") == ""


def A(name, size=1):
    return Asset(name=name, url="https://h/" + name, size=size)


def test_windows_prefers_portable_files():
    rel = [A("App-1.2-x64.msi"), A("App-Setup-1.2.exe"), A("App-1.2-win-x64.zip"), A("App-1.2-portable.exe"), A("App-1.2.msix"),
           A("App-1.2-x86_64.AppImage"), A("App-1.2-linux.tar.gz")]
    kinds = [(c.kind, c.asset.name) for c in candidates(rel, "windows", "x86_64")]
    assert kinds == [("zip", "App-1.2-win-x64.zip"), ("exe", "App-1.2-portable.exe"), ("msi", "App-1.2-x64.msi"),
                     ("exe", "App-Setup-1.2.exe"), ("msix", "App-1.2.msix")]
    assert choose(rel, "windows", "x86_64").asset.name == "App-1.2-win-x64.zip"
    assert choose([A("App-Setup-1.2.exe"), A("App-1.2-x64.msi")], "windows", "x86_64").asset.name == "App-1.2-x64.msi"
    assert choose([A("App-Setup-1.2.exe"), A("App-1.2-portable.exe")], "windows", "x86_64").asset.name == "App-1.2-portable.exe"
    # Linux is unchanged
    assert choose(rel, "linux", "x86_64").asset.name == "App-1.2-x86_64.AppImage"


def test_long_paths():
    if os.name == "nt":
        assert w.long_path("C:\\x" + "\\x" * 130).startswith("\\\\?\\C:\\") and w.long_path("C:\\short") == "C:\\short"
    else:
        assert w.long_path("/x" * 200) == "/x" * 200


# ---------------------------------------------------------------- on Windows itself (the test VM)
on_windows = pytest.mark.skipif(os.name != "nt", reason="needs Windows")


@pytest.fixture
def winenv(tmp_path, monkeypatch, env):
    """Start menus inside the test folder, so nothing lands in the real ones."""
    monkeypatch.setenv("APPDATA", str(tmp_path / "roaming"))
    monkeypatch.setenv("ProgramData", str(tmp_path / "programdata"))
    return env


def _tool_zip(root, version: str) -> str:
    """A portable app: a copy of Windows' ping.exe, which can be left running."""
    import shutil
    import zipfile
    name = f"tool-{version}-win-x64.zip"
    src = os.path.join(os.environ.get("SystemRoot", "C:\\Windows"), "System32", "PING.EXE")
    with zipfile.ZipFile(root / name, "w") as z:
        z.write(src, f"tool-{version}/tool.exe")
    return name


@on_windows
def test_portable_zip_for_me(winenv, server, tmp_path):
    """Junction, Start-menu shortcut, .cmd command link on the PATH, files in use, uninstall (15.5, 15.6, 15.9)."""
    import subprocess
    import time
    from appkata_core import install
    root, base = server
    bin_dir = str(tmp_path / "bin")
    p = install.Portable(folder=str(tmp_path / "apps"), app_menu=True, stable_name=True, command_dir=bin_dir, keep=1)
    app = {**APP, "name": "Tool"}
    try:
        n = _tool_zip(root, "1.0")
        a = Asset(n, f"{base}/{n}")
        rec = install.install(winenv, {**app, "installVersion": "1.0"}, a, "zip", [a], portable=p)
        cur = os.path.join(rec["target"], "current")
        assert w.is_junction(cur) and os.path.realpath(cur).endswith("1.0")
        assert rec["exec"] == os.path.join(cur, "tool-1.0", "tool.exe")
        lnk = os.path.join(w.start_menu("me"), "Tool.lnk")
        assert rec["shortcuts"][0]["path"] == lnk and os.path.exists(lnk)
        shim = os.path.join(bin_dir, "tool.cmd")
        assert rec["shims"] == [shim] and rec["exec"] in open(shim).read()
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
            assert bin_dir in winreg.QueryValueEx(k, "Path")[0]
        out = subprocess.run(["cmd", "/c", shim, "-n", "1", "127.0.0.1"], capture_output=True)
        assert out.returncode == 0

        # running from its folder: no update until it's closed
        proc = subprocess.Popen([rec["exec"], "-n", "30", "127.0.0.1"], stdout=subprocess.DEVNULL)
        time.sleep(1)
        assert any(x.lower().endswith("tool.exe") for x in w.processes_in(rec["target"]))
        n2 = _tool_zip(root, "1.1")
        a2 = Asset(n2, f"{base}/{n2}")
        with pytest.raises(install.InUse):
            install.install(winenv, {**app, "installVersion": "1.1"}, a2, "zip", [a2], portable=p)
        proc.kill(); proc.wait(); time.sleep(0.5)
        rec = install.install(winenv, {**app, "installVersion": "1.1"}, a2, "zip", [a2], portable=p)
        assert os.path.realpath(cur).endswith("1.1") and os.path.isdir(os.path.join(rec["target"], "1.0"))   # kept
        assert os.path.exists(lnk)      # the shortcut points through `current`: unchanged

        install.uninstall(winenv, APP["url"])
        assert not os.path.exists(rec["target"]) and not os.path.exists(lnk) and not os.path.exists(shim)
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
            assert bin_dir not in winreg.QueryValueEx(k, "Path")[0]
    finally:
        w.remove_from_user_path(bin_dir)


@on_windows
def test_portable_zip_for_everyone(winenv, server, tmp_path):
    """The everyone folder and the app's folder are locked down; the all-users shortcut (15.4.3, 15.5)."""
    from appkata_core import install
    root, base = server
    p = install.Portable(folder_everyone=str(tmp_path / "Programs"), scope="everyone", app_menu=True, command_dir="")
    n = _tool_zip(root, "2.0")
    a = Asset(n, f"{base}/{n}")
    rec = install.install(winenv, {**APP, "name": "Tool", "installVersion": "2.0"}, a, "zip", [a], portable=p)
    assert rec["scope"] == "everyone" and rec["target"].startswith(str(tmp_path / "Programs"))
    for folder, is_root in ((str(tmp_path / "Programs"), True), (rec["target"], False)):
        acl, me = w.read_acl(folder)
        assert w.acl_problem(acl, me, is_root) == "", folder
    lnk = os.path.join(w.start_menu("everyone"), "Tool.lnk")
    assert os.path.exists(lnk) and rec["shortcuts"][0]["elevated"]
    # someone loosens the app folder: an update refuses it… unless it's ours, which AppKata repairs
    w.run_hidden(["icacls", rec["target"], "/grant", f"*{w.AUTH_USERS}:(OI)(CI)M"])
    acl, me = w.read_acl(rec["target"])
    assert w.acl_problem(acl, me, False)
    w.secure_folder(rec["target"], root=False)
    acl, me = w.read_acl(rec["target"])
    assert w.acl_problem(acl, me, False) == ""
    install.uninstall(winenv, APP["url"])
    assert not os.path.exists(lnk) and not os.path.exists(rec["target"])


@on_windows
def test_registering_with_windows():
    from appkata_core import desktop
    before_run, before_scheme = w.autostart_get(), w.scheme_get()
    try:
        desktop.set_autostart(True)
        assert desktop.autostart_on() and "--tray" in w.autostart_get()
        desktop.set_autostart(False)
        assert not desktop.autostart_on()
        assert desktop.register_scheme(True) and desktop.scheme_registered() and w.scheme_get().endswith('"%1"')
        desktop.register_scheme(False)
        assert not desktop.scheme_registered()
    finally:
        w.autostart_set(before_run)
        if before_scheme:
            w.scheme_set(before_scheme)


@on_windows
def test_signatures_and_mark_of_the_web(tmp_path):
    notepad = os.path.join(os.environ.get("SystemRoot", "C:\\Windows"), "System32", "notepad.exe")
    status, _ = w.authenticode(notepad)
    assert w.signature_verdict(status) == "signed"
    f = tmp_path / "unsigned.exe"
    f.write_bytes(b"MZ not really a program")
    assert w.signature_verdict(w.authenticode(str(f))[0]) == ""
    w.mark_of_web(str(f), "https://example.org/unsigned.exe")
    assert "ZoneId=3" in open(str(f) + ":Zone.Identifier").read()


@on_windows
def test_uninstall_entries_are_read():
    entries = w.uninstall_entries()
    assert entries and all({"hive", "key"} <= set(e) for e in entries.values())


# ---------------------------------------------------------------- the Visual C++ run-time (requirement 15.18)
def make_pe(path, dlls, delay=(), pe32plus=True):
    """A minimal Windows program whose import tables name `dlls` (and delay-loaded `delay`)."""
    import struct
    rva, off = 0x1000, 0x200
    n_desc, n_delay = len(dlls) + 1, (len(delay) + 1) if delay else 0
    names, name_rva = b"", []
    base = rva + 20 * n_desc + 32 * n_delay
    for d in list(dlls) + list(delay):
        name_rva.append(base + len(names))
        names += d.encode() + b"\0"
    data = b"".join(struct.pack("<IIIII", 0, 0, 0, r, 0) for r in name_rva[:len(dlls)]) + b"\0" * 20
    if delay:
        data += b"".join(struct.pack("<IIIIIIII", 1, r, 0, 0, 0, 0, 0, 0) for r in name_rva[len(dlls):]) + b"\0" * 32
    data += names
    opt_size = 240 if pe32plus else 224
    dd = 112 if pe32plus else 96
    opt = bytearray(opt_size)
    struct.pack_into("<H", opt, 0, 0x20B if pe32plus else 0x10B)
    struct.pack_into("<I", opt, dd - 4, 16)
    struct.pack_into("<II", opt, dd + 8, rva, 20 * n_desc)
    if delay:
        struct.pack_into("<II", opt, dd + 13 * 8, rva + 20 * n_desc, 32 * n_delay)
    coff = struct.pack("<HHIIIHH", 0x8664, 1, 0, 0, 0, opt_size, 0x22)
    sect = struct.pack("<8sIIIIIIHHI", b".idata", len(data), rva, len(data), off, 0, 0, 0, 0, 0x40000040)
    head = b"MZ" + b"\0" * 0x3A + struct.pack("<I", 0x40) + b"PE\0\0" + coff + bytes(opt) + sect
    with open(path, "wb") as f:
        f.write(head + b"\0" * (off - len(head)) + data)


def test_reading_a_programs_imports(tmp_path):
    p = tmp_path / "tool.exe"
    make_pe(p, ["KERNEL32.dll", "VCRUNTIME140.dll", "api-ms-win-crt-runtime-l1-1-0.dll"], delay=["MSVCP140.dll"])
    assert w.pe_imports(str(p)) == ["KERNEL32.dll", "VCRUNTIME140.dll", "api-ms-win-crt-runtime-l1-1-0.dll", "MSVCP140.dll"]
    make_pe(tmp_path / "old.exe", ["USER32.dll"], pe32plus=False)
    assert w.pe_imports(str(tmp_path / "old.exe")) == ["USER32.dll"]
    (tmp_path / "notes.exe").write_bytes(b"not a program")
    assert w.pe_imports(str(tmp_path / "notes.exe")) == [] and w.pe_imports(str(tmp_path / "missing.exe")) == []


def test_which_apps_need_the_runtime(tmp_path):
    needs, carries, static = tmp_path / "needs", tmp_path / "carries", tmp_path / "static"
    for d in (needs, carries, static):
        (d / "bin").mkdir(parents=True)
    make_pe(needs / "bin" / "hyperfine.exe", ["KERNEL32.dll", "VCRUNTIME140.dll"])
    make_pe(carries / "bin" / "app.exe", ["KERNEL32.dll", "MSVCP140.dll", "VCRUNTIME140_1.dll"])
    for dll in ("msvcp140.dll", "vcruntime140_1.dll"):         # the app brings its own copies
        (carries / dll).write_bytes(b"MZ")
    make_pe(static / "bin" / "rg.exe", ["KERNEL32.dll", "ntdll.dll"])
    assert w.needs_msvcrt(str(needs)) and not w.needs_msvcrt(str(carries)) and not w.needs_msvcrt(str(static))
    assert w.MSVC_DLL.match("vcruntime140_1.dll") and w.MSVC_DLL.match("MSVCP140_ATOMIC_WAIT.dll") and not w.MSVC_DLL.match("msvcrt.dll")
    assert w.exit_meaning(1638) == "ok"          # vc_redist: a newer one is already installed


@on_windows
def test_runtime_on_real_programs(tmp_path):
    import shutil
    import sys
    home = os.path.dirname(sys.executable)          # Python for Windows imports the run-time, and carries it
    dll = next(f for f in os.listdir(home) if f.lower().startswith("python3") and f.lower().endswith(".dll") and f.lower() != "python3.dll")
    assert any(w.MSVC_DLL.match(d) for d in w.pe_imports(os.path.join(home, dll)))
    assert not w.needs_msvcrt(home)
    shutil.copy(os.path.join(home, dll), tmp_path / dll)  # the same library without the run-time beside it
    assert w.needs_msvcrt(str(tmp_path))
    w.msvcrt_installed()                              # reads the registry without failing
