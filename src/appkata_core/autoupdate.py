"""Who updates an app installed from a channel (requirement 16.5): the updaters AppKata knows
(16.5.2), and, afterwards, the package managers' history (16.5.4)."""

from __future__ import annotations

import configparser
import glob
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field


def _out(cmd: list[str]) -> str:
    if not shutil.which(cmd[0]):
        return ""
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return p.stdout if p.returncode == 0 else ""


def _timer_enabled(name: str) -> bool:
    return _out(["systemctl", "is-enabled", name]).strip() in ("enabled", "static", "enabled-runtime")


# ---------------------------------------------------------------- what's set up (16.5.2)
@dataclass
class Detection:
    flatpak: list[str] = field(default_factory=list)       # updaters that update Flatpaks automatically
    packages: list[str] = field(default_factory=list)      # updaters that update every package
    apt_origins: list[str] = field(default_factory=list)   # unattended-upgrades' allowed origins (patterns)
    apt_unattended: bool = False

    def as_dict(self) -> dict:
        return {"flatpak": self.flatpak, "packages": self.packages, "aptOrigins": self.apt_origins,
                "aptUnattended": self.apt_unattended}

    @classmethod
    def from_dict(cls, d: dict) -> "Detection":
        return cls(d.get("flatpak", []), d.get("packages", []), d.get("aptOrigins", []), d.get("aptUnattended", False))


def parse_apt_config(text: str) -> tuple[bool, list[str]]:
    """`apt-config dump` → (unattended upgrades on, allowed origins as "o=…,a=…" patterns)."""
    on = False
    origins: list[str] = []
    for line in text.splitlines():
        m = re.match(r'^(\S+)\s+"(.*)";$', line.strip())
        if not m:
            continue
        key, val = m.groups()
        if key == "APT::Periodic::Unattended-Upgrade":
            on = val not in ("0", "", "false")
        elif key.startswith("Unattended-Upgrade::Allowed-Origins::") and val:
            o, _, a = val.partition(":")
            origins.append(f"o={o},a={a}" if a else f"o={o}")
        elif key.startswith("Unattended-Upgrade::Origins-Pattern::") and val:
            origins.append(val)
    return on, origins


def _subst(pattern: str, distro_id: str, codename: str) -> str:
    return pattern.replace("${distro_id}", distro_id).replace("${distro_codename}", codename)


def origin_matches(pattern: str, release: dict, distro_id: str = "", codename: str = "") -> bool:
    """Does one unattended-upgrades pattern ("o=Ubuntu,a=noble-security") match a repository's release
    fields ({"o": "Ubuntu", "a": "noble-updates", "n": "noble", "l": …, "c": …})?"""
    pattern = _subst(pattern, distro_id, codename)
    keys = {"origin": "o", "archive": "a", "suite": "a", "codename": "n", "label": "l", "component": "c", "site": "site"}
    for part in pattern.split(","):
        k, _, v = part.partition("=")
        k = keys.get(k.strip(), k.strip())
        if v and release.get(k, "") != v.strip() and not (v.endswith("*") and release.get(k, "").startswith(v[:-1])):
            return False
    return True


def apt_auto(det: Detection, releases: list[dict], distro_id: str = "", codename: str = "") -> bool:
    """unattended-upgrades updates this package: one of the repositories its new versions come from is
    allowed, other than a security pocket (requirement 16.5.2: security-only doesn't count)."""
    if not det.apt_unattended:
        return False
    for r in releases:
        if "security" in (r.get("a", "") + r.get("l", "")).lower():
            continue
        if any(origin_matches(p, r, distro_id, codename) for p in det.apt_origins):
            return True
    return False


def parse_dnf_automatic(conf: str) -> bool:
    cp = configparser.RawConfigParser(strict=False)
    try:
        cp.read_string(conf)
    except configparser.Error:
        return False
    apply = cp.get("commands", "apply_updates", fallback="no").strip().lower() in ("yes", "true", "1", "on")
    kind = cp.get("commands", "upgrade_type", fallback="default").strip().lower()
    return apply and kind != "security"


def os_release(root: str = "/") -> dict:
    try:
        with open(os.path.join(root, "etc/os-release")) as f:
            return {k: v.strip().strip('"') for k, _, v in (l.rstrip("\n").partition("=") for l in f) if k}
    except OSError:
        return {}


def detect(root: str = "/", home: str | None = None) -> Detection:
    """Read the settings of the updaters AppKata knows (requirement 16.5.2). Failures count as off."""
    home = home or os.path.expanduser("~")
    d = Detection()
    # unattended-upgrades
    if shutil.which("apt-config"):
        on, origins = parse_apt_config(_out(["apt-config", "dump"]))
        d.apt_unattended = on and os.path.exists(os.path.join(root, "usr/bin/unattended-upgrade")) and \
            (_timer_enabled("apt-daily-upgrade.timer") or not shutil.which("systemctl"))
        d.apt_origins = origins
    # dnf-automatic (dnf 4 and 5)
    if _timer_enabled("dnf-automatic-install.timer"):
        d.packages.append("dnf-automatic")
    elif _timer_enabled("dnf-automatic.timer") or _timer_enabled("dnf5-automatic.timer"):
        for conf in ("etc/dnf/automatic.conf", "etc/dnf/dnf5-plugins/automatic.conf"):
            try:
                with open(os.path.join(root, conf)) as f:
                    if parse_dnf_automatic(f.read()):
                        d.packages.append("dnf-automatic")
                        break
            except OSError:
                continue
    # GNOME Software: Flatpaks update on their own; packages wait for Restart & Update
    if _out(["gsettings", "get", "org.gnome.software", "download-updates"]).strip() == "true" and \
            (shutil.which("gnome-software") or os.path.exists(os.path.join(root, "usr/bin/gnome-software"))):
        d.flatpak.append("GNOME Software")
    # KDE Discover
    cp = configparser.RawConfigParser(strict=False)
    try:
        cp.read(os.path.join(home, ".config/PlasmaDiscoverUpdates"))
        if cp.get("Global", "UseUnattendedUpdates", fallback="false").lower() == "true":
            d.flatpak.append("Discover")
            d.packages.append("Discover")
    except configparser.Error:
        pass
    # Linux Mint's Update Manager automation
    if os.path.exists(os.path.join(root, "var/lib/linuxmint/mintupdate-automatic-upgrades-enabled")):
        d.packages.append("Update Manager")
    if os.path.exists(os.path.join(root, "var/lib/linuxmint/mintupdate-automatic-flatpak-upgrades-enabled")) or \
            _out(["gsettings", "get", "com.linuxmint.updates", "auto-update-flatpaks"]).strip() == "true":
        d.flatpak.append("Update Manager")
    return d


def package_owner(det: Detection, manager: str, releases: list[dict] | None = None) -> str:
    """The updater that updates a package automatically, or "" (16.5.1)."""
    if det.packages:
        return det.packages[0]
    if manager == "apt":
        rel = os_release()
        if apt_auto(det, releases or [], rel.get("ID", "").capitalize() if rel.get("ID") != "linuxmint" else "Ubuntu",
                    rel.get("VERSION_CODENAME") or rel.get("UBUNTU_CODENAME", "")):
            return "unattended-upgrades"
    return ""


def flatpak_owner(det: Detection) -> str:
    return det.flatpak[0] if det.flatpak else ""


# ---------------------------------------------------------------- what happened (16.5.4)
@dataclass
class Event:
    date: str
    who: str                  # "unattended-upgrades", "GNOME Software", "you (apt)", …
    packages: dict            # name → (old, new)
    action: str = "upgrade"


def _who_apt(cmd: str, by: str) -> str:
    c = cmd.lower()
    if "unattended-upgrade" in c:
        return "unattended-upgrades"
    if "packagekit" in c:
        return "PackageKit"
    if "mintupdate" in c:
        return "Update Manager"
    if "appkata" in c:
        return "AppKata"
    return f"{by.split()[0]} (apt)" if by else "apt"


def parse_apt_history(text: str) -> list[Event]:
    """/var/log/apt/history.log blocks: Start-Date, Commandline, Requested-By, Upgrade/Install/Remove."""
    out = []
    for block in re.split(r"\n\s*\n", text):
        f = {}
        for line in block.strip().splitlines():
            k, _, v = line.partition(": ")
            f[k.strip()] = v.strip()
        if "Start-Date" not in f:
            continue
        for action in ("Upgrade", "Install", "Remove", "Downgrade", "Purge"):
            if action not in f:
                continue
            pk = {}
            for m in re.finditer(r"([^\s,:]+)(?::\w+)? \(([^)]*)\)", f[action]):
                vs = [x.strip() for x in m.group(2).split(",")]
                pk[m.group(1)] = (vs[0], vs[1]) if len(vs) > 1 and action in ("Upgrade", "Downgrade") else ("", vs[0])
            out.append(Event(f["Start-Date"], _who_apt(f.get("Commandline", ""), f.get("Requested-By", "")), pk,
                             action.lower()))
    return out


def parse_dnf_history(text: str) -> list[dict]:
    """`dnf history list <pkg>` → [{"id", "command", "date", "action"}]."""
    out = []
    for line in text.splitlines():
        parts = [p.strip() for p in line.split("|")]
        if len(parts) >= 4 and parts[0].isdigit():
            out.append({"id": parts[0], "command": parts[1], "date": parts[2], "action": parts[3]})
    return out


def who_dnf(command: str) -> str:
    c = command.lower()
    if "automatic" in c:
        return "dnf-automatic"
    if "packagekit" in c or not c:
        return "PackageKit"
    return "dnf"


def apt_history(root: str = "/") -> list[Event]:
    out = []
    for p in sorted(glob.glob(os.path.join(root, "var/log/apt/history.log*")), reverse=True):
        if p.endswith(".gz"):
            continue        # older rotations: the current file covers the time since the last sync
        try:
            with open(p, encoding="utf-8", errors="replace") as f:
                out += parse_apt_history(f.read())
        except OSError:
            pass
    return out


def last_change(manager: str, package: str, version: str = "") -> tuple[str, str]:
    """(who, date) of the newest change to a package, from the history (16.5.4); ("", "") if unknown."""
    if manager == "apt":
        for e in reversed(apt_history()):
            if package in e.packages and (not version or e.packages[package][1] == version):
                return e.who, e.date
        return "", ""
    rows = parse_dnf_history(_out(["dnf", "history", "list", package]))
    if rows:
        return who_dnf(rows[0]["command"]), rows[0]["date"]
    return "", ""
