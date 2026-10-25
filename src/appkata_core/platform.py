"""This machine: OS, architecture, package tools and standard folders."""

from __future__ import annotations

import os
import platform as _p
import shutil
import sys

OS = "windows" if os.name == "nt" else "macos" if sys.platform == "darwin" else "linux"


def arch() -> str:
    m = _p.machine().lower()
    if m in ("x86_64", "amd64", "x64"):
        return "x86_64"
    if m in ("aarch64", "arm64", "armv8l"):
        return "arm64"
    return m


def linux_family() -> str:
    """'debian', 'fedora' or '' from /etc/os-release (which native package format fits)."""
    try:
        with open("/etc/os-release") as f:
            data = dict(line.rstrip("\n").split("=", 1) for line in f if "=" in line)
    except OSError:
        return ""
    ids = (data.get("ID", "") + " " + data.get("ID_LIKE", "")).replace('"', "").lower().split()
    if any(i in ("debian", "ubuntu", "linuxmint") for i in ids):
        return "debian"
    if any(i in ("fedora", "rhel", "centos", "rocky", "almalinux", "suse", "opensuse") for i in ids):
        return "fedora"
    return ""


def has(tool: str) -> bool:
    return shutil.which(tool) is not None


def data_dir() -> str:
    """Database, caches and trust clones (requirement 1.8)."""
    if override := os.environ.get("APPKATA_DATA"):
        return os.path.abspath(override)
    if OS == "windows":
        return os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "AppKata")
    if OS == "macos":
        return os.path.expanduser("~/Library/Application Support/AppKata")
    return os.path.join(os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"), "appkata")


def apps_dir(scope: str = "me") -> str:
    """Where portable apps are installed (requirement 4.3.1); on Windows for "me" or "everyone" (15.4)."""
    if override := os.environ.get("APPKATA_APPS"):
        return os.path.abspath(override) if scope != "everyone" else os.path.abspath(override) + "-everyone"
    if OS == "windows":
        from . import windows
        return windows.programs_for_everyone() if scope == "everyone" else windows.programs_for_me()
    if OS == "macos":
        return os.path.expanduser("~/Applications")
    return os.path.expanduser("~/bin/apps")


def command_dir_default() -> str:
    """Where command links go (requirement 4.3.1.3, 15.6)."""
    if OS == "windows":
        from . import windows
        return windows.command_dir_default()
    return "~/bin"


def use_system_certificates() -> None:
    """Verify TLS certificates with the operating system, as browsers do. On Windows, Python's own
    check sees only the root certificates already in Windows' store, while Windows fetches missing
    ones on demand, so downloads from some hosts would fail (requirement 15)."""
    if OS == "linux":
        return
    try:
        import truststore
        truststore.inject_into_ssl()
    except ImportError:
        import logging
        logging.getLogger("appkata").warning("truststore is missing: using Python's own certificate check")


def quiet_subprocesses() -> None:
    """On Windows, keep console programs (git, gpg, PowerShell) from flashing a console window
    when AppKata, a GUI program, runs them."""
    if OS != "windows":
        return
    import subprocess
    orig = subprocess.Popen.__init__
    if getattr(orig, "_appkata_quiet", False):
        return

    def init(self, *args, **kw):
        if not kw.get("creationflags"):
            kw["creationflags"] = 0x08000000        # CREATE_NO_WINDOW
        orig(self, *args, **kw)
    init._appkata_quiet = True
    subprocess.Popen.__init__ = init


def desktop_dir() -> str:
    """Where launcher entries go (Linux: ~/.local/share/applications)."""
    return os.path.join(os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"), "applications")
