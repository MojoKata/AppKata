"""Desktop integration: start in the tray at login (requirement 1.7.4), the appkata:// link
handler (11.3). Linux and Windows (15.14); macOS follows with its build."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys

from .platform import OS


# AppKata's stable-name link once it has installed itself (requirement 2.11.3.1), so the appkata://
# handler and autostart survive updates
LAUNCH_OVERRIDE = ""


def launch_command() -> list[str]:
    """How to start this AppKata: its installed stable link, the AppImage itself, or Python and the package."""
    if LAUNCH_OVERRIDE and os.path.exists(LAUNCH_OVERRIDE):
        return [LAUNCH_OVERRIDE]
    if os.environ.get("APPIMAGE"):
        return [os.environ["APPIMAGE"]]
    if getattr(sys, "frozen", False):           # the Windows build: appkata.exe
        return [sys.executable]
    exe = sys.executable
    if OS == "windows":                         # no console window for a run from source
        w = os.path.join(os.path.dirname(exe), "pythonw.exe")
        exe = w if os.path.exists(w) else exe
    return [exe, "-m", "appkata"]


def _win_command(extra: list[str]) -> str:
    return subprocess.list2cmdline(launch_command() + extra)


def _config(*parts: str) -> str:
    return os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), *parts)


def _apps(*parts: str) -> str:
    return os.path.join(os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"), "applications", *parts)


def autostart_path() -> str:
    if OS == "windows":
        return "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run\\AppKata"
    return _config("autostart", "appkata.desktop")


def autostart_on() -> bool:
    """Whether AppKata really starts at login (Task Manager can turn it off on Windows)."""
    if OS == "windows":
        from . import windows
        return bool(windows.autostart_get())
    return os.path.exists(autostart_path())


def set_autostart(on: bool) -> str:
    """Write or remove the autostart entry; returns its path ("" where unsupported)."""
    if OS == "windows":
        from . import windows
        windows.autostart_set(_win_command(["--tray"]) if on else "")
        return autostart_path()
    if OS != "linux":
        return ""
    p = autostart_path()
    if not on:
        if os.path.exists(p):
            os.remove(p)
        return p
    os.makedirs(os.path.dirname(p), exist_ok=True)
    cmd = " ".join(shlex.quote(c) for c in launch_command() + ["--tray"])
    with open(p, "w") as f:
        f.write("[Desktop Entry]\nType=Application\nName=AppKata\nComment=Checks for app updates\n"
                f"Exec={cmd}\nIcon=appkata\nX-GNOME-Autostart-enabled=true\nNoDisplay=true\n")
    return p


def scheme_entry_path() -> str:
    return _apps("appkata-links.desktop")


def scheme_registered() -> bool:
    if OS == "windows":
        from . import windows
        return bool(windows.scheme_get())
    return os.path.exists(scheme_entry_path())


def register_scheme(on: bool) -> bool:
    """appkata://add/<url> opens Add source (requirement 11.3). Returns whether it's registered."""
    if OS == "windows":
        from . import windows
        windows.scheme_set(_win_command([]) + ' "%1"' if on else "")
        return on
    if OS != "linux":
        return False
    p = scheme_entry_path()
    if not on:
        if os.path.exists(p):
            os.remove(p)
        return False
    os.makedirs(os.path.dirname(p), exist_ok=True)
    cmd = " ".join(shlex.quote(c) for c in launch_command())
    with open(p, "w") as f:
        f.write("[Desktop Entry]\nType=Application\nName=AppKata\nExec=" + cmd + " %u\nIcon=appkata\n"
                "NoDisplay=true\nMimeType=x-scheme-handler/appkata;\n")
    if shutil.which("xdg-mime"):
        subprocess.run(["xdg-mime", "default", os.path.basename(p), "x-scheme-handler/appkata"], capture_output=True)
    if shutil.which("update-desktop-database"):
        subprocess.run(["update-desktop-database", os.path.dirname(p)], capture_output=True)
    return True


def parse_link(arg: str) -> str:
    """The Source URL in appkata://add/<url-encoded url>, or ""."""
    from urllib.parse import unquote
    if not arg.startswith("appkata://add/"):
        return ""
    return unquote(arg[len("appkata://add/"):])


def open_folder(path: str) -> None:
    os.makedirs(path, exist_ok=True)
    if OS == "windows":
        os.startfile(path)          # noqa: S606
    elif OS == "macos":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path], start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
