"""What a sandboxed app can see, checked against docs/sandbox-exposure.md (review 3, harness 3).

Shared by tests/test_sandbox_exposure.py and the field test. PROBE runs inside a generated launcher,
and on the host for the values an identifier is compared with, and prints what it can see as JSON:
the mount table, the environment, the machine's identifiers, the network interfaces and abstract
sockets, the sockets and devices in view and the processes. items() turns that into the
inventory's words ("mount /usr ro", "env LANG", "id machine-id"), argv_items() does the same from
the launcher's own bwrap words (tier 1, no bwrap needed), and expected() says which of the
inventory's rows apply to a run. Anything seen and not expected is something the sandbox shows that
nobody listed: review 2's F18 (/sys, read but never written down) was one.
"""

from __future__ import annotations

import glob
import json
import os
import re

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
INVENTORY = os.path.join(ROOT, "docs", "sandbox-exposure.md")

PROBE = r'''
import json, os, socket, stat, sys

def read(p):
    try:
        with open(p) as f:
            return f.read().strip()
    except OSError:
        return ""

def each(top, sub):
    try:
        names = sorted(os.listdir(top))
    except OSError:
        return []
    return [v for v in (read(os.path.join(top, n, sub)) for n in names) if v]

def unescape(s):
    return s.encode().decode("unicode_escape") if "\\" in s else s

mounts = []
for line in read("/proc/self/mountinfo").splitlines():
    f = line.split()
    sep = f.index("-")
    mounts.append([unescape(f[4]), f[5].split(",")[0], f[sep + 1], unescape(f[3])])

ids = {
    "machine-id": read("/etc/machine-id") or read("/var/lib/dbus/machine-id"),
    "boot-id": read("/proc/sys/kernel/random/boot_id"),
    "hostname": socket.gethostname(),
    "mac-address": sorted(v for v in each("/sys/class/net", "address") if v.strip("0:")),
    "usb-serial": sorted(each("/sys/bus/usb/devices", "serial")),
    "block-serial": sorted(each("/sys/block", "device/serial") + each("/sys/block", "device/wwid") + each("/sys/block", "serial")),
    "dmi": [v for v in (read("/sys/class/dmi/id/" + k) for k in ("sys_vendor", "product_name", "product_uuid", "product_serial", "board_serial")) if v],
}
ifaces = [l.split(":")[0].strip() for l in read("/proc/net/dev").splitlines()[2:]]
abstract = sorted({l.split()[-1] for l in read("/proc/net/unix").splitlines()[1:] if l.split()[-1].startswith("@")})

# a D-Bus server on an abstract socket: does it let this process in?
buses = []
for name in abstract:
    if "dbus" not in name:
        continue
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(2)
    try:
        s.connect("\0" + name[1:])
        s.sendall(b"\0AUTH EXTERNAL " + str(os.getuid()).encode().hex().encode() + b"\r\n")
        if s.recv(256).startswith(b"OK"):
            buses.append(name)
    except OSError:
        pass
    finally:
        s.close()

socks, seen = [], 0
for top in sorted(os.listdir("/")):
    if top in ("proc", "sys", "usr", "dev"):
        continue
    for d, dirs, files in os.walk("/" + top):
        for n in files:
            seen += 1
            p = os.path.join(d, n)
            try:
                if stat.S_ISSOCK(os.lstat(p).st_mode):
                    socks.append(p)
            except OSError:
                pass
        if seen > 50000:
            dirs[:] = []
devs = []
for d, dirs, files in os.walk("/dev"):
    for n in files + dirs:
        p = os.path.join(d, n)
        try:
            m = os.lstat(p).st_mode
        except OSError:
            continue
        if stat.S_ISCHR(m) or stat.S_ISBLK(m):
            devs.append(p)
procs = sorted({read("/proc/%s/comm" % p) for p in os.listdir("/proc") if p.isdigit()})
print("EXPOSURE " + json.dumps({"mounts": mounts, "env": sorted(os.environ), "ids": ids, "ifaces": ifaces,
                                 "abstract": abstract, "buses": buses, "sockets": sorted(socks),
                                 "devs": sorted(devs), "procs": procs}))
'''

# What the shell running the probe sets for itself, not the launcher
SHELL_VARS = {"PWD", "OLDPWD", "SHLVL", "_"}
CONDITIONS = {"always", "bus", "network", "sound", "camera", "folder-ro", "folder-rw", "cli", "write_app",
              "appimage", "wayland", "x11"}


def parse(stdout: str) -> dict:
    """The probe's JSON line, from whatever else the launcher printed."""
    for line in reversed(stdout.splitlines()):
        if line.startswith("EXPOSURE "):
            return json.loads(line[len("EXPOSURE "):])
    raise ValueError("no EXPOSURE line in: " + stdout[-500:])


# ------------------------------------------------------------------------------------- the inventory

def load(path: str = INVENTORY) -> list[dict]:
    """The inventory's rows: {"items": [...], "when": "...", "stated": "..."}."""
    with open(path, encoding="utf-8") as f:
        text = f.read()
    rows = []
    for line in text[text.index("\n## The inventory"):].split("\n"):
        m = re.match(r"^\| (`.+?) \| (.+?) \| (.+?) \|$", line)
        if m:
            rows.append({"items": re.findall(r"`([^`]+)`", m.group(1)), "when": m.group(2).strip(),
                         "stated": m.group(3).strip()})
    return rows


def holds(when: str, facts: dict) -> bool:
    """A row's "When": condition words joined by "and", each may start with "not"."""
    ok = True
    for term in when.split(" and "):
        neg = term.startswith("not ")
        word = term[4:] if neg else term
        ok = ok and (facts.get(word, False) if word != "always" else True) != neg
    return ok


def facts_for(gs: dict, session: str, cli_shared: bool, appimage: bool) -> dict:
    """The condition words' truth for a run of grant set `gs` (as the launcher normalizes it) on a
    "wayland" or "x11" session."""
    from appkata_core import sandbox as sb
    g = sb.normalize(gs)
    std = g["level"] == "standard"
    return {"bus": std, "network": std and g["network"], "sound": std and bool(g["sound"]),
            "camera": std and "camera" in g["devices"],
            "folder-ro": std and any(p != "$cwd" and m == "ro" for p, m in g["folders"].items()),
            "folder-rw": std and any(p != "$cwd" and m == "rw" for p, m in g["folders"].items()),
            "cli": std and "$cwd" in g["folders"] and cli_shared, "write_app": std and g["write_app"],
            "appimage": appimage, "wayland": session == "wayland",
            "x11": session == "x11" or (session == "wayland" and "x11" in g["devices"])}


# ------------------------------------------------------------------------------------- normalizing

def _path(p: str, ctx: dict) -> str:
    exact = {ctx["home"]: "~", ctx["rt"]: "$rt", ctx["appdir"]: "$appdir", ctx["rt"] + "/bus": "$rt/bus", ctx["rt"] + "/doc": "$rt/doc"}
    if ctx.get("img"):
        exact[ctx["img"]] = "$img"
    if ctx.get("cwd"):
        exact[ctx["cwd"]] = "<cwd>"
    if ctx.get("xauthority"):
        exact[ctx["xauthority"]] = "$XAUTHORITY"
    if ctx.get("wayland"):
        exact[ctx["rt"] + "/" + ctx["wayland"]] = "$rt/$WAYLAND_DISPLAY"
    for f in ctx.get("folders", ()):
        exact[f] = "<folder>"
    if p in exact:
        return exact[p]
    for raw, word in ((ctx["home"] + "/", "~/"), (ctx["rt"] + "/", "$rt/")):
        if p.startswith(raw):
            return word + p[len(raw):]
    return re.sub(r"^/tmp/\.X11-unix/X\d+$", "/tmp/.X11-unix/X*", p)


def _dev(p: str) -> str:
    if p.startswith("/dev/dri/"):
        return "/dev/dri/*"
    return re.sub(r"^(/dev/(?:video|media))\d+$", r"\1*", p)


def _same(a, b) -> bool:
    if isinstance(a, list):
        return bool(set(a) & set(b or []))
    return bool(a) and a == b


FRESH = ("tmpfs", "proc", "devpts")


def items(inside: dict, host: dict, ctx: dict) -> set[str]:
    """What the probe saw inside, in the inventory's words. `host` is the probe's view from outside
    (identifiers are counted only when they equal the host's; a mount the host has itself under a
    bound tree, like Docker's /etc/hosts, is carried with that tree)."""
    out = set()
    host_mounts = {m[0] for m in host["mounts"]}
    trees = [m[0] for m in inside["mounts"] if m[0] != "/" and m[2] not in FRESH and _path(m[0], ctx) == m[0]]
    for mp, opt, fs, root in inside["mounts"]:
        if mp.startswith(("/dev/", "/proc/")):
            continue
        if mp in host_mounts and any(mp.startswith(t.rstrip("/") + "/") for t in trees):
            continue
        fresh = fs in FRESH and (root == "/" or mp == "/")
        out.add(f"mount {_path(mp, ctx)} {fs if fresh else opt}")
    out |= {f"env {n}" for n in inside["env"] if n not in SHELL_VARS}
    out |= {f"id {k}" for k, v in inside["ids"].items() if _same(v, host["ids"].get(k))}
    if set(inside["ifaces"]) - {"lo"} & set(host["ifaces"]):
        out.add("net host interfaces")
    if set(inside["abstract"]) & set(host["abstract"]):
        out.add("net abstract sockets")
    if inside["buses"]:
        out.add("net abstract session bus")
    out |= {f"socket {_path(s, ctx)}" for s in inside["sockets"]}
    out |= {f"dev {_dev(d)}" for d in inside["devs"]}
    if ctx.get("marker") and ctx["marker"] in inside["procs"]:
        out.add("proc host processes")
    return out


TWO = {"--ro-bind", "--ro-bind-try", "--bind", "--bind-try", "--dev-bind", "--dev-bind-try", "--symlink",
       "--setenv", "--file", "--bind-data", "--ro-bind-data"}
ONE = {"--tmpfs", "--proc", "--dev", "--dir", "--chdir", "--seccomp", "--hostname", "--remount-ro", "--unsetenv",
       "--uid", "--gid", "--perms", "--size", "--chmod", "--sync-fd", "--block-fd", "--info-fd", "--userns-block-fd"}


def argv_items(argv: list[str], ctx: dict) -> set[str]:
    """The mounts, devices and variables the launcher's bwrap words give (tier 1: no bwrap runs).
    A -try bind whose source is missing is skipped, as bwrap skips it."""
    out, i = set(), 0
    while i < len(argv) and argv[i] != "--":
        a = argv[i]
        if a in TWO:
            src, dst = argv[i + 1], argv[i + 2]
            if a == "--setenv":
                out.add(f"env {src}")
            elif a != "--symlink" and (not a.endswith("-try") or os.path.exists(src)):
                if dst.startswith("/dev/"):
                    if dst != "/dev/dri" or glob.glob("/dev/dri/*"):
                        out.add(f"dev {_dev(dst)}" if dst != "/dev/dri" else "dev /dev/dri/*")
                else:
                    out.add(f"mount {_path(dst, ctx)} {'ro' if a.startswith('--ro-') else 'rw'}")
            i += 3
        elif a in ONE:
            if a in ("--tmpfs", "--dev"):
                out.add(f"mount {_path(argv[i + 1], ctx)} tmpfs")
            elif a == "--proc":
                out.add(f"mount {argv[i + 1]} proc")
            i += 2
        else:
            if a == "--share-net":
                out.add("net host interfaces")
            i += 1
    return out


# What tier 1 can see in the bwrap words; the rest only a run shows
ARGV_KINDS = ("mount", "env", "net")
ARGV_DEVS = {"dev /dev/dri/*", "dev /dev/video*", "dev /dev/media*"}
BWRAP_OWN = {"mount / tmpfs"}         # bwrap's own root, never a word
# Variables the launcher sets itself (the rest it passes through only when set at launch)
LAUNCHER_SET = {"HOME", "PATH", "XDG_RUNTIME_DIR", "GDK_DEBUG", "DBUS_SESSION_BUS_ADDRESS", "APPDIR", "APPIMAGE", "ARGV0",
                "DISPLAY"}


def argv_kind(item: str) -> bool:
    return item not in BWRAP_OWN and (item.split(" ", 1)[0] in ARGV_KINDS or item in ARGV_DEVS) and item != "net abstract sockets" \
        and item != "net abstract session bus"


def present(item: str, ctx: dict, host: dict | None = None) -> bool:
    """Whether the host has the thing an inventory row names, so the row can be seen at all: a -try
    bind's source, a variable set at launch, an identifier, a device."""
    kind, _, rest = item.partition(" ")
    if kind == "mount":
        path = rest.rsplit(" ", 1)[0]
        special = {"~": True, "$appdir": True, "$rt/bus": True, "/.flatpak-info": True, "/run/appkata": True,
                   "/": True, "/tmp": True, "/proc": True, "/dev": True, "<folder>": bool(ctx.get("folders")),
                   "<cwd>": bool(ctx.get("cwd")), "$img": bool(ctx.get("img")),
                   "$rt/doc": os.path.isdir(os.path.join(ctx["rt"], "doc", "by-app", ctx.get("id", ""))),
                   "$XAUTHORITY": bool(ctx.get("xauthority")) and os.path.exists(ctx["xauthority"]),
                   "$rt/$WAYLAND_DISPLAY": bool(ctx.get("wayland")) and os.path.exists(os.path.join(ctx["rt"], ctx["wayland"]))}
        if path in special:
            return special[path]
        if path.startswith("/run/"):           # where /etc/resolv.conf really lives (the network grant's DNS)
            return (os.path.realpath("/etc/resolv.conf") + "/").startswith(path + "/")
        real = ctx["home"] + path[1:] if path.startswith("~/") else ctx["rt"] + path[3:] if path.startswith("$rt/") else path
        return os.path.exists(real)
    if kind == "env":
        if rest in ("XAUTHORITY", "WAYLAND_DISPLAY"):
            return present({"XAUTHORITY": "mount $XAUTHORITY ro", "WAYLAND_DISPLAY": "mount $rt/$WAYLAND_DISPLAY ro"}[rest], ctx)
        return rest in LAUNCHER_SET or rest in ctx.get("launch_env", {})
    if kind == "id":
        return host is None or bool(host["ids"].get(rest))
    if kind == "dev":
        return bool(glob.glob(rest)) if "*" in rest else os.path.exists(rest)
    if kind == "socket":
        if rest == "$rt/bus":                  # the proxy's, made at launch
            return True
        real = rest.replace("$rt/$WAYLAND_DISPLAY", os.path.join(ctx["rt"], ctx.get("wayland") or "-")).replace("$rt/", ctx["rt"] + "/")
        return bool(glob.glob(real))
    if kind == "net":
        if host is None:
            return True
        return {"host interfaces": bool(set(host["ifaces"]) - {"lo"}), "abstract sockets": bool(host["abstract"]),
                "abstract session bus": bool(ctx.get("abstract_bus"))}.get(rest, True)
    return True


def passed_through(env: dict) -> set[str]:
    """The names the launcher's own pass-through block, run by this machine's /bin/sh, gives an app
    started with `env` (the proxy names included)."""
    import subprocess
    from appkata_core import sandbox as sb
    r = subprocess.run(["/bin/sh", "-c", "\n".join(sb._launcher_env(True)) + '\nprintf "%s\\n" "$@"'],
                       env=env, capture_output=True, text=True)
    words = r.stdout.split("\n")
    return {words[i + 1] for i, w in enumerate(words[:-1]) if w == "--setenv"}


def shell_view(env: dict) -> dict:
    """The variables the launcher passes on, given the environment it is started with: the
    launcher's own block decides, so a shell that adds variables of its own (bash sets TERM=dumb;
    review 3, R3-20) shows here exactly as it would in a launch."""
    return {**env, **{n: env.get(n, "") for n in passed_through(env)}}


def expected(rows: list[dict], facts: dict, ctx: dict, host: dict | None = None, kinds=None) -> set[str]:
    out = set()
    for row in rows:
        if holds(row["when"], facts):
            out |= {it for it in row["items"] if (kinds is None or it.split(" ", 1)[0] in kinds) and present(it, ctx, host)}
    return out


def listed(rows: list[dict]) -> set[str]:
    return {it for row in rows for it in row["items"]}
