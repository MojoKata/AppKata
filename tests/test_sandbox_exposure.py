"""What a sandboxed app can see is exactly docs/sandbox-exposure.md (review 3, harness 3).

How review 2's F18 slipped past: every test asked whether one thing the tester thought of was
hidden -- ~/.ssh, ~/.bashrc, the real bus, the desktop entries, the agent socket. None listed what
is in view, so a bind nobody thought to ask about stood unrecorded: /sys, for GPU identification,
with every network card's MAC address and the USB serials in it, even for a Strict app with no
network. The class: the sandbox shows something nobody listed.

This harness turns the question round. docs/sandbox-exposure.md is the inventory of everything in
view, each row with the sentence of requirement 17 that says so or the finding that keeps it
unstated. The harness fails on anything seen that the inventory doesn't list for that run, and on
a row that should be seen and isn't. Tier 1 runs each template's launcher with a stand-in bwrap
that records its words (mounts, variables, devices). Tier 2, in the launcher harnesses
(scripts/test-sandbox.sh launcher, launcher-21, launcher-25, launcher-vm, launcher-vm26), runs
scripts/sandbox/exposure.py's probe inside real launchers: the mount table, the environment, /dev,
sockets, the machine's identifiers, network interfaces and abstract sockets, other processes.

Three of its own originating faults are re-introduced to show it catches them: F18 (the /sys rows
taken out of the inventory), an agent socket passed into the environment, and round three's R3-1
(the host's desktop entries back in view).
"""

import glob
import json
import os
import re
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile

import pytest

from appkata_core import sandbox as sb
from test_requirements_trace import _finding_exists
from test_sandbox_run import Env, _bwrap_ok, _listen

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "scripts", "sandbox"))
import exposure as ex                                    # noqa: E402

pytestmark = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="the sandbox and its launchers are Linux-only (17.1)")


@pytest.fixture(autouse=True)
def _proxy_here(monkeypatch):
    """The launchers here are for a host with xdg-dbus-proxy, as every launcher tier is; one without
    it has its own tests (review 2, F12)."""
    monkeypatch.setattr(sb, "have_bus_filter", lambda: True)


# what the inventory shows but no requirement states, and the finding that keeps each so
STILL_UNSTATED: set = set()
# 17.2's table checked where 17.2.1 says it is the whole story (Strict), and what keeps a cell wrong
STILL_WRONG: dict = {}

# Every built-in template, with the folder a folder template is made for as the user would pick it
# (17.3), a writable app folder on one, and a CLI tool run from a project folder
RUNS = [("strict", {}), ("standard", {}), ("offline-editor", {"folders": {"~/Documents": "ro"}}),
        ("online-app", {}), ("messenger", {}), ("media-player", {"write_app": True}),
        ("developer", {"folders": {"~/Projects": "rw"}}), ("cli-tool", {})]
SESSIONS = ("wayland", "x11")
KINDS = {"mount", "env", "id", "net", "socket", "dev", "proc"}


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.replace("*", "").replace("`", "")).strip()


def _requirement(rid: str) -> str:
    with open(os.path.join(ROOT, "docs", "requirements.md"), encoding="utf-8") as f:
        text = f.read()
    m = re.search(rf"^{re.escape(rid)}\. (.*?)(?=^\d+\.\d+(?:\.\d+)*\. |^## )", text, re.M | re.S)
    return _norm(m.group(1)) if m else ""


# ------------------------------------------------------------------------------------- the inventory

def test_every_row_names_known_things_and_where_each_is_stated():
    rows, bad, seen = ex.load(), [], set()
    assert len(rows) > 30
    for row in rows:
        for it in row["items"]:
            if it.split(" ", 1)[0] not in KINDS:
                bad.append(f"{it}: not a kind the probe reports")
            if it in seen:
                bad.append(f"{it}: on two rows")
            seen.add(it)
        for term in row["when"].split(" and "):
            if term.removeprefix("not ") not in ex.CONDITIONS:
                bad.append(f"{row['items'][0]}: unknown condition {term!r}")
        st = row["stated"]
        m = re.match(r'^(\d+(?:\.\d+)+) "(.+)"$', st)
        if m:
            if _norm(m.group(2)) not in _requirement(m.group(1)):
                bad.append(f"{row['items'][0]}: {m.group(1)} doesn't say {m.group(2)!r}")
        elif st.startswith("open: "):
            if not _finding_exists(st[6:]):
                bad.append(f"{row['items'][0]}: no finding {st[6:]}")
        elif st != "no host data":
            bad.append(f"{row['items'][0]}: 'Stated in' must quote a requirement, say 'no host data' or name an open finding")
    assert not bad, "\n".join(bad)


def test_the_unstated_rows_are_exactly_the_listed_findings():
    opened = {r["stated"][6:] for r in ex.load() if r["stated"].startswith("open: ")}
    assert opened - STILL_UNSTATED == set(), f"open in the inventory but not listed here: {sorted(opened - STILL_UNSTATED)}"
    assert STILL_UNSTATED - opened == set(), f"listed here, no row open on it any more (drop it): {sorted(STILL_UNSTATED - opened)}"


# ------------------------------------------------------------------------------------- a session

class Session:
    """A fake user's session for the runs: display, sound and X authority, the theme folders, folders
    to grant and a project to run a CLI tool in. `real` adds what only a real run can see: the X
    server's socket, an abstract socket and a session bus started the way dbus-launch starts one, a
    process the sandbox must not see."""

    def __init__(self, env: Env, tmp_path, monkeypatch, real: bool = False):
        self.env, self.closers = env, []
        # a runtime folder as short as a real one (/run/user/<uid>): pytest's own paths are long enough
        # to push the proxy's socket past the 108-byte limit (review 3, R3-12)
        rt = tempfile.mkdtemp(prefix="akx-", dir="/tmp")
        env.rt = type(env.rt)(rt)
        env.env["XDG_RUNTIME_DIR"] = rt
        monkeypatch.setenv("XDG_RUNTIME_DIR", rt)
        self.closers.append(lambda: shutil.rmtree(rt, ignore_errors=True))
        for d in (".themes", ".icons", ".fonts", ".config/fontconfig", ".local/share/fonts", ".local/share/icons",
                  ".local/share/themes", "Documents", "Projects", "src/proj"):
            (env.home / d).mkdir(parents=True, exist_ok=True)
        self.xa = tmp_path / "xauth"
        self.xa.write_text("cookie")
        (env.rt / "pulse").mkdir(exist_ok=True)
        for p in ("wayland-5", "pipewire-0", "pulse/native"):
            self.closers.append(_listen(str(env.rt / p)).close)
        self.marker, self.abstract_bus, self.bus_address = None, False, ""
        if real:
            self._real(tmp_path)

    def _real(self, tmp_path):
        try:
            os.makedirs("/tmp/.X11-unix", exist_ok=True)
            s = _listen("/tmp/.X11-unix/X55")
            self.closers += [s.close, lambda: os.unlink("/tmp/.X11-unix/X55")]
        except OSError:
            pass
        a = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        a.bind(f"\0appkata-exposure-{os.getpid()}")
        a.listen(1)
        self.closers.append(a.close)
        # a session bus started the way dbus-launch or dbus-run-session start one: on its configured
        # unix:tmpdir address, which dbus 1.12 (Mint 21.3) makes an abstract socket
        if shutil.which("dbus-daemon"):
            p = subprocess.run(["dbus-daemon", "--session", "--fork", "--print-address=1", "--print-pid=1"],
                               capture_output=True, text=True, env=self.env.env, timeout=10)
            lines = p.stdout.split()
            if len(lines) >= 2:
                self.abstract_bus = lines[0].startswith("unix:abstract=")
                self.bus_address = lines[0]
                self.closers.append(lambda pid=int(lines[1]): os.kill(pid, 15))
        link = tmp_path / "akmarker"
        link.symlink_to(shutil.which("sleep"))
        m = subprocess.Popen([str(link), "120"])
        self.marker = "akmarker"
        self.closers.append(m.kill)

    def close(self):
        for c in reversed(self.closers):
            try:
                c()
            except OSError:
                pass

    def launch_env(self, session: str) -> dict:
        """Every variable the launcher may pass through, set, and some it must never pass."""
        e = {v: "C.UTF-8" if v.startswith(("LANG", "LC_")) else "1" if "SCALE" in v or "SIZE" in v else "x"
             for v in sb._ENV_PASSTHROUGH}
        e.update(LANGUAGE="en", TERM="xterm", XDG_SESSION_TYPE=session, DISPLAY=":55", XAUTHORITY=str(self.xa),
                 SSH_AUTH_SOCK="/nonexistent/agent", GPG_AGENT_INFO="/nonexistent/gpg", http_proxy="http://u:secret@proxy:3128",
                 SESSION_MANAGER="local/host:@/tmp/.ICE-unix/1", GNOME_KEYRING_CONTROL="/nonexistent/keyring",
                 DBUS_SESSION_BUS_ADDRESS=f"unix:path={self.env.rt}/nonexistent-bus", LD_PRELOAD="")
        if session == "wayland":
            e["WAYLAND_DISPLAY"] = "wayland-5"
        return e

    def ctx(self, app_id: str, gs: dict, session: str, appdir: str, cwd: str | None, img: str | None = None) -> dict:
        return {"home": str(self.env.home), "rt": str(self.env.rt), "appdir": appdir, "img": img, "cwd": cwd,
                "folders": [os.path.expanduser(p) for p in gs["folders"] if p != "$cwd"], "xauthority": str(self.xa),
                "wayland": "wayland-5" if session == "wayland" else None, "launch_env": ex.shell_view(self.launch_env(session)),
                "id": sb.app_identity(app_id), "marker": self.marker, "abstract_bus": self.abstract_bus}


def _grants(template: str, extra: dict) -> dict:
    gs = sb.resolve_template(template)
    gs["folders"] = {**gs["folders"], **extra.get("folders", {})}
    if "write_app" in extra:
        gs["write_app"] = extra["write_app"]
    return gs


# ------------------------------------------------------------------------------------- tier 1

RECORDER = """import json, socket, sys
argv = sys.argv[2:]
with open(sys.argv[1], "a") as f:
    f.write(json.dumps(argv) + "\\n")
if "xdg-dbus-proxy" in argv:                    # the proxy's own bwrap: leave its socket, as the proxy would
    s = socket.socket(socket.AF_UNIX)
    s.bind(argv[argv.index("xdg-dbus-proxy") + 2])
"""


def _recording_bwrap(env: Env) -> tuple[str, str]:
    """A PATH whose bwrap records its words (one JSON line per call) instead of running anything."""
    d = env.home.parent / "fakebin"
    d.mkdir(exist_ok=True)
    log = env.home.parent / "bwrap-words"
    (d / "record.py").write_text(RECORDER)
    (d / "bwrap").write_text(f'#!/bin/sh\nexec {shlex.quote(sys.executable)} {shlex.quote(str(d / "record.py"))} {shlex.quote(str(log))} "$@"\n')
    (d / "bwrap").chmod(0o755)
    return f"{d}:{os.environ['PATH']}", str(log)


def _words(env: Env, s: Session, template: str, extra: dict, session: str) -> tuple[set, dict, dict]:
    """The items the launcher's bwrap words give for one template and session, the condition facts
    and the context they were read in."""
    path, log = _recording_bwrap(env)
    gs = _grants(template, extra)
    lp = env.app(template, gs)
    cwd = str(env.home / "src" / "proj") if template == "cli-tool" else None
    if os.path.exists(log):
        os.unlink(log)
    r = env.run(lp, "true", cwd=cwd, env={**s.launch_env(session), "PATH": path})
    with open(log) as f:
        calls = [json.loads(line) for line in f]
    argv = next((a for a in reversed(calls) if "/.flatpak-info" in a), None)
    assert argv, (r.stdout, r.stderr, calls)
    ctx = s.ctx(template, gs, session, str(env.home / "apps" / template / "1.0"), os.path.realpath(cwd) if cwd else None)
    return ex.argv_items(argv, ctx), ex.facts_for(gs, session, cli_shared=cwd is not None, appimage=False), ctx


def _tier1(rows, tmp_path, monkeypatch, session: str) -> list[str]:
    env = Env(tmp_path, monkeypatch)
    s = Session(env, tmp_path, monkeypatch)
    problems = []
    try:
        for template, extra in RUNS:
            seen, facts, ctx = _words(env, s, template, extra, session)
            seen = {i for i in seen if ex.argv_kind(i)}
            want = {i for i in ex.expected(rows, facts, ctx) if ex.argv_kind(i)}
            problems += [f"{template}/{session}: seen, not listed for this run: {i}" for i in sorted(seen - want)]
            problems += [f"{template}/{session}: listed, not seen: {i}" for i in sorted(want - seen)]
    finally:
        s.close()
    return problems


@pytest.mark.parametrize("session", SESSIONS)
def test_the_launchers_words_give_exactly_what_the_inventory_lists(tmp_path, monkeypatch, session):
    problems = _tier1(ex.load(), tmp_path, monkeypatch, session)
    assert not problems, "\n".join(problems)


def test_the_harness_catches_review_twos_f18_with_its_rows_taken_out(tmp_path, monkeypatch):
    # Before F18 there was nothing to quote for /sys: without its rows (as the inventory would have
    # been), every template's run shows the binds as unlisted
    rows = [r for r in ex.load() if not {"mount /sys/class ro", "id mac-address"} & set(r["items"])]
    problems = _tier1(rows, tmp_path, monkeypatch, "wayland")
    assert "strict/wayland: seen, not listed for this run: mount /sys/class ro" in problems, problems


def test_the_harness_catches_an_agent_socket_passed_into_the_environment(tmp_path, monkeypatch):
    monkeypatch.setattr(sb, "_ENV_PASSTHROUGH", sb._ENV_PASSTHROUGH + ("SSH_AUTH_SOCK",))
    problems = _tier1(ex.load(), tmp_path, monkeypatch, "x11")
    assert "online-app/x11: seen, not listed for this run: env SSH_AUTH_SOCK" in problems, problems


def test_the_harness_catches_round_threes_desktop_entries_back_in_view(tmp_path, monkeypatch):
    # R3-1 (round three): with the host's desktop entries in view, GLib started the host's browser
    # inside the sandbox; the empty tmpfs over them is a listed row, so losing it is flagged
    if not os.path.isdir("/usr/share/applications"):
        pytest.skip("no /usr/share/applications here")
    build = sb.build_launcher
    monkeypatch.setattr(sb, "build_launcher", lambda *a, **k: build(*a, **k).replace('set -- --tmpfs "$d" "$@"', ":"))
    problems = _tier1(ex.load(), tmp_path, monkeypatch, "wayland")
    assert "strict/wayland: listed, not seen: mount /usr/share/applications tmpfs" in problems, problems


# 17.2's Strict row, where 17.2.1 says the table is the whole story: column -> (the cell as it is
# written, {claim: what the Strict launcher must then give})
STRICT_ROW = {
    "Home": ("private only", {"home": lambda s: "mount ~ rw" in s and not any("<folder>" in i or "<cwd>" in i for i in s)}),
    "Install files": ("read-only", {"install files": lambda s: "mount $appdir ro" in s and "mount $appdir rw" not in s}),
    "Network": ("no", {"network": lambda s: "net host interfaces" not in s}),
    "Session D-Bus": ("none", {"session bus": lambda s: "mount $rt/bus rw" not in s}),
    "Display, sound, GPU": ("display and GPU, no sound", {
        "display": lambda s: "mount $rt/$WAYLAND_DISPLAY ro" in s,
        "sound": lambda s: "mount $rt/pipewire-0 ro" not in s and "mount $rt/pulse/native ro" not in s,
        "GPU": lambda s: "dev /dev/dri/*" in s or not glob.glob("/dev/dri/*")}),
}


def test_17_2s_strict_row_is_what_the_strict_launcher_gives_but_the_listed(tmp_path, monkeypatch):
    text = _requirement("17.2")
    header = [c.strip() for c in re.search(r"\| Level \|(.+?)\|\s*\|-", text).group(1).split("|")]
    cells = [c.strip() for c in re.search(r"\| Strict \|(.+?)\| (?:17|$)", text + " 17").group(1).split("|")]
    row = dict(zip(header, cells))
    assert set(row) == set(STRICT_ROW), f"17.2's columns changed: {sorted(row)}"
    env = Env(tmp_path, monkeypatch)
    s = Session(env, tmp_path, monkeypatch)
    try:
        seen, _, _ = _words(env, s, "strict", {}, "wayland")
    finally:
        s.close()
    wrong = set()
    for col, (written, claims) in STRICT_ROW.items():
        assert row[col] == written, f"17.2 now says {row[col]!r} for Strict's {col}: update STRICT_ROW and STILL_WRONG"
        wrong |= {f"Strict: {name}" for name, holds in claims.items() if not holds(seen)}
    assert wrong == set(STILL_WRONG), f"17.2's Strict row against the Strict launcher: wrong {sorted(wrong)}, listed {sorted(STILL_WRONG)}"


# ------------------------------------------------------------------------------------- tier 2

needs_bwrap = pytest.mark.skipif(not _bwrap_ok(), reason="needs a working bwrap 0.5+ (scripts/test-sandbox.sh launcher)")


def _appimage(env: Env, gs: dict) -> tuple[str, str, str]:
    """A stand-in AppImage whose unpacked AppRun runs its first argument, and its launcher."""
    img = env.home / "apps" / "img" / "Img-1.0.AppImage"
    img.parent.mkdir(parents=True, exist_ok=True)
    img.write_text('#!/bin/sh\n[ "$1" = --appimage-extract ] && { mkdir -p squashfs-root && '
                   "printf '#!/bin/sh\\neval \"$1\"\\n' > squashfs-root/AppRun && chmod +x squashfs-root/AppRun; exit 0; }\n"
                   "echo not-extracted\n")
    img.chmod(0o755)
    appdir = sb.extracted_dir(str(env.home / "apps" / "img"), "1.0")
    lp = sb.write_launcher("img", "Img", str(env.home / "apps"), appdir, "AppRun", gs, str(img))
    return lp, appdir, str(img)


def _tier2(rows, env: Env, s: Session, session: str, runs) -> tuple[list[str], set[str]]:
    problems, opened = [], set()
    probe = "python3 -c " + shlex.quote(ex.PROBE)
    host = ex.parse(subprocess.run([sys.executable, "-c", ex.PROBE], capture_output=True, text=True, timeout=60).stdout)
    for template, extra in runs:
        gs = _grants("strict" if template == "appimage" else template, extra)
        cwd = str(env.home / "src" / "proj") if template == "cli-tool" else None
        if template == "appimage":
            lp, appdir, img = _appimage(env, gs)
        else:
            lp, appdir, img = env.app(template, gs), str(env.home / "apps" / template / "1.0"), None
        r = env.run(lp, probe, cwd=cwd, env=s.launch_env(session), timeout=60)
        try:
            inside = ex.parse(r.stdout)
        except ValueError:
            problems.append(f"{template}/{session}: the probe didn't run: {r.stderr[-1500:]}")
            continue
        ctx = s.ctx("img" if template == "appimage" else template, gs, session, appdir,
                    os.path.realpath(cwd) if cwd else None, img)
        seen = ex.items(inside, host, ctx)
        want = ex.expected(rows, ex.facts_for(gs, session, cli_shared=cwd is not None, appimage=img is not None), ctx, host)
        problems += [f"{template}/{session}: seen, not listed for this run: {i}" for i in sorted(seen - want)]
        problems += [f"{template}/{session}: listed, not seen: {i}" for i in sorted(want - seen)]
        opened |= {r["stated"] for r in rows for i in seen if i in r["items"] and r["stated"].startswith("open: ")}
    return problems, opened


@needs_bwrap
@pytest.mark.parametrize("session", SESSIONS)
def test_what_an_app_sees_inside_is_exactly_what_the_inventory_lists(tmp_path, monkeypatch, session):
    env = Env(tmp_path, monkeypatch)
    s = Session(env, tmp_path, monkeypatch, real=True)
    try:
        problems, opened = _tier2(ex.load(), env, s, session, RUNS + [("appimage", {})])
    finally:
        s.close()
    assert not problems, "\n".join(problems)
    print(f"\nexposures seen that no requirement states: {sorted(opened)}; a dbus-launch bus here is "
          f"{'abstract' if s.abstract_bus else 'a path'}")


@needs_bwrap
def test_a_run_catches_f18s_identifiers_with_its_rows_taken_out(tmp_path, monkeypatch):
    env = Env(tmp_path, monkeypatch)
    s = Session(env, tmp_path, monkeypatch, real=True)
    try:
        problems, _ = _tier2([r for r in ex.load() if not {"mount /sys/class ro", "id mac-address"} & set(r["items"])],
                             env, s, "wayland", [("strict", {})])
    finally:
        s.close()
    assert "strict/wayland: seen, not listed for this run: mount /sys/class ro" in problems, problems
    if glob.glob("/sys/class/net/*/address") and any(open(a).read().strip().strip("0:") for a in glob.glob("/sys/class/net/*/address")):
        assert "strict/wayland: seen, not listed for this run: id mac-address" in problems, problems


@needs_bwrap
def test_a_run_catches_the_runtime_folder_bound_whole(tmp_path, monkeypatch):
    # The real session bus, the display sockets and every other app's runtime files in one bind: the
    # class's worst member (17.3.3's never-shared runtime folder, R3 of round one for CLI tools)
    build = sb.build_launcher
    monkeypatch.setattr(sb, "build_launcher", lambda *a, **k: build(*a, **k).replace(
        '  --setenv XDG_RUNTIME_DIR "$rt"', '  --ro-bind "$rt" "$rt" --setenv XDG_RUNTIME_DIR "$rt"'))
    env = Env(tmp_path, monkeypatch)
    s = Session(env, tmp_path, monkeypatch, real=True)
    try:
        problems, _ = _tier2(ex.load(), env, s, "wayland", [("strict", {})])
    finally:
        s.close()
    assert "strict/wayland: seen, not listed for this run: mount $rt ro" in problems, problems


@needs_bwrap
def test_the_bus_warning_is_on_exactly_where_a_dbus_launch_bus_is_reachable(tmp_path, monkeypatch):
    # Review 3, R3-8 (17.9): the warning follows the measured fact on each distro -- a bus started the
    # way dbus-launch starts one is abstract on dbus 1.12 (Mint 21.3, RHEL 9), a path on 1.14 and later
    env = Env(tmp_path, monkeypatch)
    s = Session(env, tmp_path, monkeypatch, real=True)
    try:
        if not s.bus_address:
            pytest.skip("no dbus-daemon here")
        monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", s.bus_address)
        assert bool(sb.bus_warning()) is s.abstract_bus, s.bus_address
    finally:
        s.close()
