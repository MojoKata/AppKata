"""Installing, removing and updating the distribution's packages (requirement 16.3.5, 16.4.3,
16.5.5, 16.8): through PackageKit when its service is there (16.8.1), else apt-get or dnf through
pkexec (16.8.2). Every change is dry-run first, and the plan is reviewed before it runs."""

from __future__ import annotations

import glob
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field

from . import applog, dbus
from .platform import linux_family

LOCK_WAIT = 600            # seconds (requirement 16.8.3)


class PackageError(Exception):
    pass


class Refused(PackageError):
    """The plan touches something AppKata never changes (16.3.5)."""


# ---------------------------------------------------------------- plans
@dataclass
class Plan:
    install: list[str] = field(default_factory=list)     # new packages
    upgrade: list[str] = field(default_factory=list)
    remove: list[str] = field(default_factory=list)
    downgrade: list[str] = field(default_factory=list)

    def names(self) -> set[str]:
        return set(self.install + self.upgrade + self.remove + self.downgrade)


def parse_apt_sim(text: str) -> Plan:
    """`apt-get -s` output: Inst/Remv/Purg lines."""
    p = Plan()
    for line in text.splitlines():
        m = re.match(r"^(Inst|Remv|Purg)\s+(\S+)(?:\s+\[([^\]]+)\])?(?:\s+\(([^\s)]+))?", line)
        if not m:
            continue
        verb, name, old, new = m.groups()
        name = name.split(":")[0]
        if verb in ("Remv", "Purg"):
            p.remove.append(name)
        elif old and new and _deb_lt(new, old):
            p.downgrade.append(name)
        elif old:
            p.upgrade.append(name)
        else:
            p.install.append(name)
    return p


def _deb_lt(a: str, b: str) -> bool:
    if shutil.which("dpkg"):
        return subprocess.run(["dpkg", "--compare-versions", a, "lt", b], capture_output=True).returncode == 0
    return False


_DNF_SECTIONS = {"installing": "install", "installing dependencies": "install", "installing weak dependencies": "install",
                 "installing group/module packages": "install", "upgrading": "upgrade", "reinstalling": None,
                 "removing": "remove", "removing dependent packages": "remove", "removing unused dependencies": "remove",
                 "downgrading": "downgrade", "replacing": None, "installing dependencies:": "install"}


def parse_dnf_plan(text: str) -> Plan:
    """The transaction table dnf (4 and 5) prints before asking, as with --assumeno."""
    p = Plan()
    cur = None
    for line in text.splitlines():
        head = line.strip().rstrip(":").lower()
        if head in _DNF_SECTIONS and line.rstrip().endswith(":"):
            cur = _DNF_SECTIONS[head]
            continue
        if re.match(r"^\s*(Transaction Summary|Package\s+Arch|=+|-+)\s*", line) or not line.strip():
            if line.strip().startswith("Transaction Summary"):
                cur = None
            continue
        if cur and line.startswith(" "):
            name = line.split()[0]
            if name.startswith("replacing"):
                continue
            getattr(p, cur).append(name)
    return p


DESKTOP_META = re.compile(
    r"^(?:(?:ubuntu|kubuntu|xubuntu|lubuntu|ubuntu-budgie|ubuntu-mate|ubuntucinnamon|edubuntu|ubuntustudio|ubuntukylin)"
    r"-desktop(?:-minimal)?|task-[\w-]*desktop|mint-meta-[\w-]+|gnome-core|gnome|kde-standard|kde-plasma-desktop|"
    r"plasma-desktop|cinnamon-desktop-environment|mate-desktop-environment(?:-core)?|xfce4|"
    r"fedora-release(?:-\w+)?|redhat-release(?:-\w+)?|almalinux-release|rocky-release|gnome-shell|plasma-workspace)$")


@dataclass
class Facts:
    """What AppKata knows about the packages in a plan."""
    essential: set[str] = field(default_factory=set)       # Essential: yes, or dnf's protected packages
    auto: set[str] = field(default_factory=set)            # installed as a dependency

    def blocked(self, names) -> list[str]:
        return sorted(n for n in names if n in self.essential or DESKTOP_META.match(n))


@dataclass
class Verdict:
    refuse: str = ""                 # why AppKata won't run it
    confirm: list[str] = field(default_factory=list)   # what the user must see first ("Removes: x")


def review(plan: Plan, action: str, targets: list[str], facts: Facts) -> Verdict:
    """Requirement 16.3.5 (install), 16.4.3 (remove), 16.5.5 (upgrade)."""
    tg = set(targets)
    bad = facts.blocked(plan.remove)
    if bad:
        return Verdict(refuse=f"It would remove {', '.join(bad)}, which this computer needs.")
    extra = []
    others_removed = [n for n in plan.remove if n not in tg]
    if others_removed:
        extra.append("Removes " + ", ".join(sorted(others_removed)))
    if plan.downgrade:
        extra.append("Downgrades " + ", ".join(sorted(plan.downgrade)))
    if action == "install":
        upgrades = [n for n in plan.upgrade if n not in tg]
        if upgrades:
            extra.append("Upgrades " + ", ".join(sorted(upgrades)))
    return Verdict(confirm=extra)


# ---------------------------------------------------------------- locks (16.8.3)
APT_LOCKS = ["/var/lib/dpkg/lock-frontend", "/var/lib/dpkg/lock", "/var/lib/apt/lists/lock", "/var/cache/apt/archives/lock"]
RPM_LOCKS = ["/var/lib/rpm/.rpm.lock", "/usr/lib/sysimage/rpm/.rpm.lock"]


def parse_proc_locks(text: str) -> dict[int, int]:
    """/proc/locks → {inode: pid} for the locks held."""
    out = {}
    for line in text.splitlines():
        parts = line.split()
        if "->" in parts:          # a waiter, not a holder
            continue
        try:
            pid = int(parts[4])
            ino = int(parts[5].split(":")[2])
        except (IndexError, ValueError):
            continue
        out.setdefault(ino, pid)
    return out


def _holder_name(pid: int) -> str:
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            argv = [a.decode(errors="replace") for a in f.read().split(b"\0") if a]
    except OSError:
        argv = []
    names = [os.path.basename(a) for a in argv[:3]]
    for n in names:
        if "unattended-upgrade" in n:
            return "unattended-upgrades"
        if n in ("packagekitd", "gnome-software", "plasma-discover", "mintupdate", "mintinstall", "synaptic"):
            return {"packagekitd": "PackageKit", "gnome-software": "GNOME Software", "plasma-discover": "Discover",
                    "mintupdate": "Update Manager", "mintinstall": "Software Manager"}.get(n, n)
    for n in names:
        if n and not n.startswith("python"):
            return n
    return names[0] if names else f"process {pid}"


def lock_holder(paths: list[str]) -> str:
    """Who holds the package manager's lock, or "" (needs no administrator rights)."""
    try:
        with open("/proc/locks") as f:
            held = parse_proc_locks(f.read())
    except OSError:
        return ""
    for p in paths:
        try:
            ino = os.stat(p).st_ino
        except OSError:
            continue
        if ino in held:
            return _holder_name(held[ino])
    return ""


def wait_for_lock(paths: list[str], on_wait=None, cancel=None, limit: float = LOCK_WAIT) -> None:
    end = time.monotonic() + limit
    while True:
        who = lock_holder(paths)
        if not who:
            return
        if on_wait:
            on_wait(who)
        if cancel and cancel():
            raise PackageError("cancelled")
        if time.monotonic() > end:
            raise PackageError(f"{who} kept the package manager busy for {int(limit // 60)} minutes")
        time.sleep(2)


# ---------------------------------------------------------------- facts from the system
def apt_facts(names) -> Facts:
    f = Facts()
    names = sorted(set(names))
    if not names:
        return f
    for line in _text(["dpkg-query", "-W", "-f", "${Package}\t${Essential}\t${Priority}\n", *names]).splitlines():
        parts = line.split("\t")
        if len(parts) >= 3 and (parts[1] == "yes" or parts[2] == "required"):
            f.essential.add(parts[0])
    f.auto = {l.strip() for l in _text(["apt-mark", "showauto", *names]).splitlines() if l.strip()}
    return f


def dnf_protected(root: str = "/") -> set[str]:
    out = {"dnf", "dnf5", "rpm", "systemd", "sudo", "kernel-core", "glibc", "bash"}
    for p in glob.glob(os.path.join(root, "etc/dnf/protected.d/*.conf")) + \
            glob.glob(os.path.join(root, "usr/share/dnf5/libdnf.conf.d/*.conf")):
        try:
            with open(p) as fh:
                out |= {l.strip() for l in fh if l.strip() and not l.startswith("#") and "=" not in l}
        except OSError:
            pass
    return out


def dnf_facts(names) -> Facts:
    f = Facts(essential=dnf_protected())
    for n in set(names):
        if _text(["dnf", "-q", "repoquery", "--installed", "--qf", "%{reason}", n]).strip().lower() == "dependency":
            f.auto.add(n)
    return f


# ---------------------------------------------------------------- the backends
class Backend:
    name = ""
    manager = ""         # "apt" or "dnf"

    def simulate(self, action: str, names: list[str]) -> Plan: ...
    def run(self, action: str, names: list[str], progress=None, cancel=None, on_wait=None) -> None: ...

    def facts(self, names) -> Facts:
        return apt_facts(names) if self.manager == "apt" else dnf_facts(names)

    def plan(self, action: str, names: list[str]) -> tuple[Plan, Verdict]:
        """The dry run and its review (16.3.5, 16.4.3)."""
        plan = self.simulate(action, names)
        targets = [os.path.basename(n) if os.path.sep in n else n for n in names]
        return plan, review(plan, action, targets, self.facts(plan.names() | set(targets)))

    def apply(self, action: str, names: list[str], confirmed: bool = False, progress=None, cancel=None,
              on_wait=None) -> Plan:
        """Dry run, review, then run. Raises Refused, or PackageError("confirm: …") when the plan needs
        the user's OK and `confirmed` isn't set."""
        plan, v = self.plan(action, names)
        if v.refuse:
            raise Refused(v.refuse)
        if v.confirm and not confirmed:
            raise NeedsConfirmation(v.confirm, plan)
        self.run(action, names, progress, cancel, on_wait)
        return plan


class NeedsConfirmation(PackageError):
    def __init__(self, lines: list[str], plan: Plan):
        super().__init__("; ".join(lines))
        self.lines, self.plan = lines, plan


def _priv(cmd: list[str], env: dict | None = None) -> list[str]:
    """For this action only (requirement 1.3)."""
    env_args = [f"{k}={v}" for k, v in (env or {}).items()]
    if os.geteuid() == 0:
        return ["env", *env_args, *cmd] if env_args else cmd
    if not shutil.which("pkexec"):
        raise PackageError("pkexec isn't available to ask for administrator rights")
    return ["pkexec", "env", *env_args, *cmd]


APT_OPTS = ["-y", "-o", "Dpkg::Options::=--force-confdef", "-o", "Dpkg::Options::=--force-confold",
            "-o", "APT::Status-Fd=1", "-o", f"DPkg::Lock::Timeout={LOCK_WAIT}"]


def _apt_progress(line: str):
    """APT::Status-Fd lines → percent: downloading is the first half, installing the second."""
    m = re.match(r"^(dlstatus|pmstatus):[^:]*:([\d.]+):", line)
    if not m:
        return None
    pct = float(m.group(2))
    return int(pct / 2) if m.group(1) == "dlstatus" else 50 + int(pct / 2)


class Cli(Backend):
    """apt-get or dnf on the command line (requirement 16.8.2)."""
    name = "cli"

    def __init__(self, manager: str | None = None):
        self.manager = manager or ("apt" if linux_family() == "debian" else "dnf")

    def _sim_cmd(self, action: str, names: list[str]) -> list[str]:
        if self.manager == "apt":
            verb = {"install": ["install"], "remove": ["remove"], "upgrade": ["install", "--only-upgrade"]}[action]
            return ["apt-get", "-s", *verb, *names]
        verb = {"install": ["install"], "remove": ["remove", "--noautoremove"], "upgrade": ["upgrade"]}[action]
        return ["dnf", "--assumeno", *verb, *names]

    def simulate(self, action: str, names: list[str]) -> Plan:
        p = applog.run(self._sim_cmd(action, names), timeout=600)
        out = p.stdout + "\n" + p.stderr
        if self.manager == "apt":
            if p.returncode:
                raise PackageError(_last(p.stderr) or "apt-get couldn't plan it")
            return parse_apt_sim(out)
        if "superuser" in out.lower() or "root" in _last(p.stderr).lower():
            p = applog.run(_priv(self._sim_cmd(action, names)), timeout=600)
            out = p.stdout + "\n" + p.stderr
        plan = parse_dnf_plan(out)
        if not plan.names() and re.search(r"^Error", out, re.M):
            raise PackageError(_last(out))
        return plan

    def run(self, action: str, names: list[str], progress=None, cancel=None, on_wait=None) -> None:
        if self.manager == "apt":
            wait_for_lock(APT_LOCKS, on_wait, cancel)
            verb = {"install": ["install"], "remove": ["remove"], "upgrade": ["install", "--only-upgrade"]}[action]
            cmd = _priv(["apt-get", *APT_OPTS, *verb, *names], {"DEBIAN_FRONTEND": "noninteractive"})
            if action == "upgrade":
                inner = " ".join(_q(a) for a in ["apt-get", *APT_OPTS, *verb, *names])
                cmd = _priv(["sh", "-c", f"apt-get update -qq && {inner}"], {"DEBIAN_FRONTEND": "noninteractive"})
        else:
            wait_for_lock(RPM_LOCKS, on_wait, cancel)
            # packages left unneeded stay: that's the system's business (requirement 16.4.3)
            verb = {"install": ["install"], "remove": ["remove", "--noautoremove"], "upgrade": ["upgrade"]}[action]
            cmd = _priv(["dnf", "-y", *verb, *names])
        _stream(cmd, progress, cancel, _apt_progress if self.manager == "apt" else None)


def _q(s: str) -> str:
    return "'" + s.replace("'", "'\\''") + "'"


def _last(text: str) -> str:
    lines = [l for l in (text or "").strip().splitlines() if l.strip()]
    return lines[-1].strip() if lines else ""


def _stream(cmd: list[str], progress=None, cancel=None, parse=None) -> None:
    import logging
    lg = logging.getLogger("appkata.cmd")
    lg.info("$ %s", " ".join(cmd))
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
    for line in iter(p.stdout.readline, ""):
        lg.info("  out| %s", line.rstrip())
        if parse and progress:
            pct = parse(line)
            if pct is not None:
                progress(pct, 100)
        if cancel and cancel():
            break             # a running dpkg/rpm transaction isn't interrupted; wait for it
    err = p.stderr.read()
    p.wait()
    for line in err.splitlines()[-50:]:
        lg.info("  err| %s", line)
    if p.returncode:
        if p.returncode in (126, 127) and cmd[0] == "pkexec":
            raise PackageError("the administrator password wasn't given")
        raise PackageError(_last(err) or f"{cmd[1] if cmd[0] == 'pkexec' else cmd[0]} failed (exit {p.returncode})")


# ---------------------------------------------------------------- PackageKit (16.8.1)
PK = "org.freedesktop.PackageKit"
PK_PATH = "/org/freedesktop/PackageKit"
PK_TX = "org.freedesktop.PackageKit.Transaction"
FLAG_ONLY_TRUSTED, FLAG_SIMULATE = 1 << 1, 1 << 2
FILTER_INSTALLED, FILTER_NOT_INSTALLED, FILTER_NEWEST, FILTER_ARCH = 1 << 2, 1 << 3, 1 << 16, 1 << 18
INFO = {1: "installed", 2: "available", 11: "upgrade", 12: "install", 13: "remove", 15: "remove",
        19: "reinstall", 20: "downgrade"}


class PkTransport:
    """One PackageKit transaction over D-Bus: call `method` and collect its signals until Finished.
    Tests replace it with a fake."""

    def __init__(self, connect=dbus.Connection):
        self._connect = connect

    def available(self) -> bool:
        try:
            with self._connect() as c:
                return c.has_name(PK)
        except (OSError, dbus.DBusError):
            return False

    def transaction(self, method: str, sig: str, args: list, on_event=None, cancel=None) -> list[tuple]:
        events: list[tuple] = []
        with self._connect(timeout=3600) as c:
            path = c.call(PK, PK_PATH, PK, "CreateTransaction")[0]
            c.add_match(f"type='signal',sender='{PK}',path='{path}'")
            c.call(PK, path, PK_TX, "SetHints", "as", [["interactive=true", f"locale={os.environ.get('LANG', 'C')}"]])
            c.call(PK, path, PK_TX, method, sig, args, interactive=True)
            while True:
                m = c.next_signal(timeout=1.0)
                if cancel and cancel():
                    try:
                        c.call(PK, path, PK_TX, "Cancel")
                    except dbus.DBusError:
                        pass
                    cancel = None
                if m is None:
                    continue
                member, a = m.get("member"), m.get("args", [])
                if member == "Package":
                    ev = ("package", a[0], a[1], a[2])
                elif member == "ErrorCode":
                    ev = ("error", a[0], a[1])
                elif member == "Finished":
                    ev = ("finished", a[0])
                elif member == "PropertiesChanged" and isinstance(a[1], dict) and "Percentage" in a[1]:
                    ev = ("percentage", a[1]["Percentage"].value)
                elif member == "PropertiesChanged" and isinstance(a[1], dict) and "Status" in a[1]:
                    ev = ("status", a[1]["Status"].value)
                else:
                    continue
                events.append(ev)
                if on_event:
                    on_event(ev)
                if ev[0] == "finished":
                    return events
                if ev[0] == "error" and ev[1] in (19,):   # PK_ERROR_ENUM_TRANSACTION_CANCELLED
                    pass


def _pk_name(package_id: str) -> str:
    return package_id.split(";", 1)[0]


class PackageKit(Backend):
    name = "packagekit"

    def __init__(self, transport: PkTransport | None = None, manager: str | None = None):
        self.t = transport or PkTransport()
        self.manager = manager or ("apt" if linux_family() == "debian" else "dnf")

    def _check(self, events: list[tuple]) -> None:
        errs = [e for e in events if e[0] == "error"]
        if errs:
            raise PackageError(errs[-1][2] or f"PackageKit error {errs[-1][1]}")

    def resolve(self, names: list[str], installed: bool | None = None) -> dict[str, str]:
        """name → package ID (the newest)."""
        flt = FILTER_NEWEST | FILTER_ARCH | (FILTER_INSTALLED if installed else FILTER_NOT_INSTALLED if installed is False else 0)
        ev = self.t.transaction("Resolve", "tas", [flt, names])
        self._check(ev)
        out = {}
        for e in ev:
            if e[0] == "package":
                n = _pk_name(e[2])
                if n not in out or (installed and e[1] == 1):
                    out[n] = e[2]
        missing = [n for n in names if n not in out]
        if missing:
            raise PackageError(f"no package called {', '.join(missing)}")
        return out

    def _call(self, action: str, names: list[str], flags: int, on_event=None, cancel=None) -> list[tuple]:
        files = [n for n in names if os.path.sep in n]
        if files:
            return self.t.transaction("InstallFiles", "tas", [flags, files], on_event, cancel)
        if action == "remove":
            ids = list(self.resolve(names, installed=True).values())
            return self.t.transaction("RemovePackages", "tasbb", [flags, ids, True, False], on_event, cancel)
        if action == "upgrade":
            if not flags & FLAG_SIMULATE:
                self.t.transaction("RefreshCache", "b", [False])
            ev = self.t.transaction("GetUpdates", "t", [0])
            ids = [e[2] for e in ev if e[0] == "package" and _pk_name(e[2]) in names]
            if not ids:
                return [("finished", 1)]
            return self.t.transaction("UpdatePackages", "tas", [flags, ids], on_event, cancel)
        ids = list(self.resolve(names, installed=False).values())
        return self.t.transaction("InstallPackages", "tas", [flags, ids], on_event, cancel)

    def simulate(self, action: str, names: list[str]) -> Plan:
        ev = self._call(action, names, FLAG_SIMULATE)
        self._check(ev)
        p = Plan()
        for e in ev:
            if e[0] == "package" and INFO.get(e[1]) in ("install", "upgrade", "remove", "downgrade"):
                getattr(p, INFO[e[1]]).append(_pk_name(e[2]))
        return p

    def run(self, action: str, names: list[str], progress=None, cancel=None, on_wait=None) -> None:
        def on_event(e):
            if e[0] == "percentage" and progress and 0 <= e[1] <= 100:
                progress(e[1], 100)
            if e[0] == "status" and e[1] == 30 and on_wait:      # PK_STATUS_ENUM_WAITING_FOR_LOCK
                on_wait(lock_holder(APT_LOCKS if self.manager == "apt" else RPM_LOCKS) or "another program")
        ev = self._call(action, names, FLAG_ONLY_TRUSTED, on_event, cancel)
        self._check(ev)


def backend() -> Backend:
    """PackageKit when its service is there, else the command line (requirement 16.8)."""
    t = PkTransport()
    if os.environ.get("APPKATA_NO_PACKAGEKIT") != "1" and t.available():
        return PackageKit(t)
    return Cli()


# ---------------------------------------------------------------- reading (16.8.4)
def installed_version(name: str, manager: str | None = None) -> str:
    manager = manager or ("apt" if linux_family() == "debian" else "dnf")
    if manager == "apt":
        st, _, ver = _text(["dpkg-query", "-W", "-f", "${Status}\t${Version}", name]).partition("\t")
        return ver if "installed" in st and "not-installed" not in st and "config-files" not in st else ""
    out = _text(["rpm", "-q", "--qf", "%{VERSION}-%{RELEASE}", name]).strip()
    return "" if "not installed" in out else out


def parse_apt_policy(text: str) -> dict:
    """`apt-cache policy <pkg>` → {"installed", "candidate", "sources": [(site, "suite/component")]} where
    `sources` are the repositories that offer the candidate (or the installed version)."""
    out = {"installed": "", "candidate": "", "sources": []}
    want, cur = None, None
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("Installed:"):
            out["installed"] = "" if "(none)" in s else s.split(":", 1)[1].strip()
        elif s.startswith("Candidate:"):
            out["candidate"] = "" if "(none)" in s else s.split(":", 1)[1].strip()
            want = out["candidate"] or out["installed"]
        elif s.startswith("Version table:"):
            continue
        else:
            m = re.match(r"^(?:\*\*\*\s+)?(\S+)\s+-?\d+$", s)
            if m:
                cur = m.group(1)
                continue
            m = re.match(r"^-?\d+\s+(\S+)\s+(\S+)\s+\S+\s+Packages$", s)
            if m and cur == want:
                out["sources"].append((m.group(1), m.group(2)))
    return out


def parse_apt_releases(text: str) -> list[dict]:
    """`apt-cache policy` (no package) → every repository with its release fields (o, a, n, l, c)."""
    out, cur = [], None
    for line in text.splitlines():
        s = line.strip()
        m = re.match(r"^-?\d+\s+(\S+)\s+(\S+)\s+\S+\s+Packages$", s)
        if m:
            suite, _, comp = m.group(2).partition("/")
            cur = {"site": m.group(1), "suite": suite, "component": comp}
            out.append(cur)
            continue
        m = re.match(r"^release\s+(.*)$", s)
        if m and cur is not None:
            cur.update(dict(x.split("=", 1) for x in m.group(1).split(",") if "=" in x))
    return out


def apt_releases_for(name: str) -> list[dict]:
    """The release fields of the repositories a package's new versions come from (16.5.2)."""
    pol = parse_apt_policy(_text(["apt-cache", "policy", name]))
    allr = parse_apt_releases(_text(["apt-cache", "policy"]))
    srcs = set(pol["sources"])
    return [r for r in allr if (r["site"], f"{r['suite']}/{r['component']}" if r["component"] else r["suite"]) in srcs]


def _text(cmd: list[str]) -> str:
    """A command's output, or "" when it's missing or fails."""
    if not shutil.which(cmd[0]):
        return ""
    p = subprocess.run(cmd, capture_output=True, text=True)
    return p.stdout if p.returncode == 0 else ""


def apt_policy(name: str) -> dict:
    return parse_apt_policy(_text(["apt-cache", "policy", name]))


def package_version_available(name: str, manager: str | None = None) -> str:
    """The repositories' newest version (apt: the candidate)."""
    manager = manager or ("apt" if linux_family() == "debian" else "dnf")
    if manager == "apt":
        return apt_policy(name)["candidate"]
    lines = [l for l in _text(["dnf", "-q", "repoquery", "--latest-limit=1", "--qf", "%{version}-%{release}\n", name]).splitlines() if l.strip()]
    return lines[-1].strip() if lines else ""


def pending_updates(names: list[str], manager: str | None = None) -> dict[str, str]:
    """name → newer version, without administrator rights (requirement 16.5.5)."""
    manager = manager or ("apt" if linux_family() == "debian" else "dnf")
    out = {}
    if not names:
        return out
    if manager == "apt":
        for line in _text(["apt", "list", "--upgradable", *names]).splitlines():
            m = re.match(r"^([^/\s]+)/\S+\s+(\S+)\s", line)
            if m and m.group(1) in names:
                out[m.group(1)] = m.group(2)
        return out
    p = subprocess.run(["dnf", "-q", "check-update", *names], capture_output=True, text=True) if shutil.which("dnf") else None
    for line in (p.stdout if p else "").splitlines():       # exit 100 means "updates available"
        parts = line.split()
        if len(parts) >= 3:
            n = parts[0].rsplit(".", 1)[0]
            if n in names:
                out[n] = parts[1]
    return out
