"""Flatpak as a channel (requirement 16.3.4, 16.4, 16.5, 16.6): per user, no elevation. Every
command goes through `run`, so tests can replace it."""

from __future__ import annotations

import configparser
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field

from . import applog

FLATHUB = "flathub"
FLATHUB_REPO = "https://dl.flathub.org/repo/flathub.flatpakrepo"


class FlatpakError(Exception):
    pass


def available() -> bool:
    return shutil.which("flatpak") is not None


def run(args: list[str], **kw) -> subprocess.CompletedProcess:
    return applog.run(["flatpak", *args], **kw)


def _err(p: subprocess.CompletedProcess, what: str) -> FlatpakError:
    lines = [l for l in (p.stderr or "").strip().splitlines() if l.strip()]
    return FlatpakError(f"{what}: {lines[-1] if lines else 'flatpak failed'}")


def _scope(system: bool) -> str:
    return "--system" if system else "--user"


# ---------------------------------------------------------------- remotes
def remotes(system: bool = False) -> list[str]:
    p = run(["remotes", _scope(system), "--columns=name"])
    return [l.strip() for l in p.stdout.splitlines() if l.strip()] if p.returncode == 0 else []


def has_remote(name: str = FLATHUB) -> bool:
    return name in remotes(False) or name in remotes(True)


def add_flathub() -> None:
    """Asked once, before the first Flathub install (requirement 16.3.4)."""
    p = run(["remote-add", "--user", "--if-not-exists", FLATHUB, FLATHUB_REPO])
    if p.returncode:
        raise _err(p, "couldn't add Flathub")


# ---------------------------------------------------------------- what's installed
@dataclass
class Installed:
    app_id: str
    version: str = ""
    origin: str = ""
    installation: str = "user"    # "user" or "system"
    commit: str = ""
    branch: str = "stable"


def installed() -> dict[str, Installed]:
    """Every installed app, user installs first (requirement 4.5, 16.4.1)."""
    out: dict[str, Installed] = {}
    for scope in ("--user", "--system"):
        p = run(["list", "--app", scope, "--columns=application,version,origin,branch,active"])
        if p.returncode:
            continue
        for line in p.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) >= 1 and parts[0].strip() and parts[0] not in out:
                g = parts + [""] * 5
                out[parts[0]] = Installed(parts[0], g[1], g[2], scope[2:], g[4], g[3] or "stable")
    return out


def parse_info(text: str) -> dict:
    """`flatpak info` → {"version", "commit", "origin", "installation", "ref", ...} (keys lowercased)."""
    out = {}
    for line in text.splitlines():
        m = re.match(r"^\s*([A-Za-z][A-Za-z -]*?):\s*(.*)$", line)
        if m:
            out[m.group(1).strip().lower()] = m.group(2).strip()
    return out


def info(app_id: str, system: bool = False) -> dict:
    p = run(["info", _scope(system), app_id])
    return parse_info(p.stdout) if p.returncode == 0 else {}


# ---------------------------------------------------------------- remote facts
def remote_info(app_id: str, remote: str = FLATHUB, system: bool = False) -> dict:
    """The newest build on the remote: version, commit, date (16.1.5, 16.5.5)."""
    p = run(["remote-info", _scope(system), remote, app_id])
    return parse_info(p.stdout) if p.returncode == 0 else {}


def parse_log(text: str) -> list[dict]:
    """`flatpak remote-info --log` → [{"commit", "subject", "date"}], newest first (16.5.7)."""
    out, cur = [], None
    for line in text.splitlines():
        m = re.match(r"^\s*(Commit|Subject|Date|History):\s*(.*)$", line)
        if not m:
            continue
        k, v = m.group(1).lower(), m.group(2).strip()
        if k == "commit":
            cur = {"commit": v, "subject": "", "date": ""}
            out.append(cur)
        elif cur is not None and k in ("subject", "date"):
            cur[k] = v
    return out


def history_log(app_id: str, remote: str = FLATHUB) -> list[dict]:
    p = run(["remote-info", "--user", "--log", remote, app_id])
    return parse_log(p.stdout) if p.returncode == 0 else []


def metadata(app_id: str, remote: str = FLATHUB, commit: str = "") -> str:
    """The app's metadata keyfile (its permissions, extra data) from the remote (16.6)."""
    args = ["remote-info", "--user", "--show-metadata", remote, app_id]
    if commit:
        args[3:3] = [f"--commit={commit}"]
    p = run(args)
    return p.stdout if p.returncode == 0 else ""


def installed_metadata(app_id: str, system: bool = False) -> str:
    p = run(["info", _scope(system), "--show-metadata", app_id])
    return p.stdout if p.returncode == 0 else ""


# ---------------------------------------------------------------- permissions (16.6.3) and extra data (16.6.2)
_FS_WORDS = {"host": "Whole file system", "host-os": "System files", "host-etc": "System settings",
             "home": "Home folder", "xdg-download": "~/Downloads", "xdg-documents": "~/Documents",
             "xdg-music": "~/Music", "xdg-pictures": "~/Pictures", "xdg-videos": "~/Videos",
             "xdg-desktop": "~/Desktop", "xdg-config": "Settings folder (~/.config)", "xdg-data": "~/.local/share",
             "xdg-run": "Session runtime folder"}
_SHARED = {"network": "Network", "ipc": None}
_SOCKETS = {"x11": "Display (X11)", "fallback-x11": None, "wayland": None, "pulseaudio": "Sound",
            "session-bus": "All session services", "system-bus": "All system services", "ssh-auth": "SSH keys",
            "pcsc": "Smart cards", "cups": "Printing", "gpg-agent": "GPG keys"}
_DEVICES = {"all": "Devices", "dri": None, "kvm": "Virtualization", "shm": None, "input": "Input devices"}


def _keyfile(text: str) -> configparser.RawConfigParser:
    cp = configparser.RawConfigParser(strict=False, interpolation=None, delimiters=("=",))
    cp.optionxform = str
    try:
        cp.read_string(text)
    except configparser.Error:
        pass
    return cp


def permissions(meta: str) -> list[str]:
    """Plain words for what the app may reach, in a stable order (requirement 16.6.3)."""
    cp = _keyfile(meta)
    out: list[str] = []

    def vals(sec, key):
        return [v for v in (cp.get(sec, key, fallback="") or "").split(";") if v and not v.startswith("!")]

    for v in vals("Context", "shared"):
        w = _SHARED.get(v, v)
        if w:
            out.append(w)
    for v in vals("Context", "sockets"):
        w = _SOCKETS.get(v, v)
        if w:
            out.append(w)
    for v in vals("Context", "devices"):
        w = _DEVICES.get(v, v)
        if w:
            out.append(w)
    for v in vals("Context", "filesystems"):
        base, _, mode = v.partition(":")
        root, _, sub = base.partition("/")
        if root in _FS_WORDS and not sub:
            w = _FS_WORDS[root]
        elif root.startswith("~") or root.startswith("/"):
            w = base
        elif root in _FS_WORDS:
            w = _FS_WORDS[root].split(" (")[0].rstrip("/") + "/" + sub if root.startswith("xdg-") else base
        else:
            w = base
        out.append(w + (" (read-only)" if mode == "ro" else ""))
    if cp.has_section("Session Bus Policy"):
        for name, level in cp.items("Session Bus Policy"):
            if level in ("talk", "own"):
                out.append(f"Session service {name}")
    if cp.has_section("System Bus Policy"):
        for name, level in cp.items("System Bus Policy"):
            if level in ("talk", "own"):
                out.append(f"System service {name}")
    return list(dict.fromkeys(out))


def added_permissions(old: list[str], new: list[str]) -> list[str]:
    """What an update asks for that the installed version didn't have (16.6.3)."""
    return [p for p in new if p not in old]


def extra_data_host(meta: str) -> str:
    """The host an extra-data Flatpak downloads its program from, or "" (16.6.2)."""
    cp = _keyfile(meta)
    if not cp.has_section("Extra Data"):
        return ""
    uri = cp.get("Extra Data", "uri", fallback="")
    m = re.match(r"^\w+://([^/:]+)", uri)
    return m.group(1) if m else (uri or "elsewhere")


# ---------------------------------------------------------------- changing things
_PCT = re.compile(r"(\d{1,3})%")


def _stream(args: list[str], progress=None, cancel=None) -> subprocess.CompletedProcess:
    """Run a long flatpak command, reporting its percentage to progress(done, total)."""
    if progress is None and cancel is None:
        return run(args, timeout=3600)
    p = subprocess.Popen(["flatpak", *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
    out = []
    for line in iter(p.stdout.readline, ""):
        out.append(line)
        if cancel and cancel():
            p.terminate()
            break
        m = _PCT.findall(line)
        if m and progress:
            progress(min(100, int(m[-1])), 100)
    err = p.stderr.read()
    p.wait()
    return subprocess.CompletedProcess(p.args, p.returncode, "".join(out), err)


def install(app_id: str, remote: str = FLATHUB, progress=None, cancel=None) -> Installed:
    p = _stream(["install", "--user", "--noninteractive", "-y", remote, app_id], progress, cancel)
    if p.returncode:
        raise _err(p, f"couldn't install {app_id}")
    i = info(app_id)
    return Installed(app_id, i.get("version", ""), i.get("origin", remote), "user", i.get("commit", ""),
                     i.get("branch", "stable"))


def uninstall(app_id: str, system: bool = False) -> None:
    """The app's data in ~/.var/app is kept (requirement 16.4.3)."""
    p = run(["uninstall", _scope(system), "--noninteractive", "-y", app_id])
    if p.returncode and "not installed" not in (p.stderr or "").lower():
        raise _err(p, f"couldn't uninstall {app_id}")


def update(app_id: str, system: bool = False, commit: str = "", progress=None, cancel=None) -> dict:
    """Update to the newest build, or to `commit` (an older version, 16.5.7)."""
    args = ["update", _scope(system), "--noninteractive", "-y"] + ([f"--commit={commit}"] if commit else []) + [app_id]
    p = _stream(args, progress, cancel)
    if p.returncode:
        raise _err(p, f"couldn't update {app_id}")
    return info(app_id, system)


def mask(app_id: str, system: bool = False) -> None:
    """Pinning (requirement 16.5.6): stops every updater, the desktop's store included."""
    p = run(["mask", _scope(system), app_id])
    if p.returncode:
        raise _err(p, f"couldn't pin {app_id}")


def unmask(app_id: str, system: bool = False) -> None:
    p = run(["mask", _scope(system), "--remove", app_id])
    if p.returncode and "no current mask" not in (p.stderr or "").lower():
        raise _err(p, f"couldn't unpin {app_id}")


def parse_updates(text: str) -> dict[str, dict]:
    out = {}
    for line in text.splitlines():
        parts = line.split("\t")
        if parts and parts[0].strip():
            g = parts + ["", ""]
            out[parts[0].strip()] = {"version": g[1].strip(), "commit": g[2].strip()}
    return out


def updates(system: bool = False) -> dict[str, dict]:
    """Apps with a newer build on their remote (requirement 16.5.5)."""
    p = run(["remote-ls", "--updates", _scope(system), "--app", "--columns=application,version,commit"])
    return parse_updates(p.stdout) if p.returncode == 0 else {}


# ---------------------------------------------------------------- history (16.5.4)
@dataclass
class Change:
    time: str
    change: str          # "install", "update", "uninstall", "deploy install"…
    app_id: str
    commit: str = ""
    installation: str = ""
    tool: str = ""       # "flatpak", "gnome-software", "plasma-discover"…
    extra: dict = field(default_factory=dict)


def parse_history(text: str) -> list[Change]:
    out = []
    for line in text.splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        g = parts + [""] * 7
        ref = g[2]
        app = ref.split("/")[1] if ref.count("/") >= 2 else ref
        out.append(Change(g[0].strip(), g[1].strip(), app.strip(), g[3].strip(), g[4].strip(), g[5].strip()))
    return out


def history(since: str = "") -> list[Change]:
    args = ["history", "--columns=time,change,ref,commit,installation,tool"]
    if since:
        args.append(f"--since={since}")
    p = run(args)
    return parse_history(p.stdout) if p.returncode == 0 else []


TOOL_NAMES = {"gnome-software": "GNOME Software", "plasma-discover": "Discover", "discover": "Discover",
              "mintinstall": "Software Manager", "mintupdate": "Update Manager", "flatpak": "flatpak",
              "appkata": "AppKata", "python3": "AppKata"}


def tool_name(tool: str) -> str:
    return TOOL_NAMES.get(os.path.basename(tool or ""), tool or "")
