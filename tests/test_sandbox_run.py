"""App sandboxing (R17): generated launchers, actually run under bwrap.

These execute `~/bin/apps/<app>/run` as AppKata writes it, with a tiny shell "app" that runs the
snippet it's given, and check what the app can and can't reach. They need a bwrap new enough for the
launcher (`--clearenv`, 0.5+) that can create user namespaces; elsewhere they skip. Run them in the
Mint 22.1 container with `scripts/test-sandbox.sh launcher`.
"""

import hashlib
import os
import re
import shlex
import shutil
import subprocess
import sys
import time

import pytest

from appkata_core import sandbox as sb


def _bwrap_ok() -> bool:
    if not shutil.which("bwrap"):
        return False
    r = subprocess.run(["bwrap", "--ro-bind", "/usr", "/usr", "--symlink", "usr/lib", "/lib",
                        "--symlink", "usr/lib64", "/lib64", "--proc", "/proc", "--dev", "/dev",
                        "--unshare-all", "--clearenv", "--", "/usr/bin/true"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return r.returncode == 0


pytestmark = pytest.mark.skipif(not _bwrap_ok(), reason="needs a working bwrap 0.5+ (scripts/test-sandbox.sh launcher)")
needs_proxy = pytest.mark.skipif(not shutil.which("xdg-dbus-proxy") or not shutil.which("dbus-daemon"),
                                 reason="needs xdg-dbus-proxy and dbus-daemon")

# The "app": runs its first argument as a shell snippet, inside the sandbox.
APP = "#!/bin/sh\neval \"$1\"\n"


class Env:
    """A fake user: a real home with secrets, an install root, the runtime dir and AppKata's data."""

    def __init__(self, tmp_path, monkeypatch):
        self.home = tmp_path / "home"
        self.rt = tmp_path / "run"
        for d in (self.home / ".ssh", self.rt, self.home / "apps"):
            d.mkdir(parents=True)
        self.rt.chmod(0o700)
        (self.home / ".ssh" / "id_ed25519").write_text("SECRET-KEY\n")
        (self.home / ".bashrc").write_text("# real bashrc\n")
        monkeypatch.setattr(sb, "sandboxes_root", lambda: str(self.home / ".local/share/appkata/sandboxes"))
        # the generator's view of "home" too (expanduser, the protected folders), not just the app's
        monkeypatch.setenv("HOME", str(self.home))
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(self.rt))
        for v in ("XDG_DATA_HOME", "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_STATE_HOME", "APPKATA_APPS", "APPKATA_DATA"):
            monkeypatch.delenv(v, raising=False)     # this user's places are where a home has them (conftest.own_home)
        self.env = {"HOME": str(self.home), "XDG_RUNTIME_DIR": str(self.rt), "PATH": os.environ["PATH"],
                    "LANG": "C.UTF-8"}
        self.machines = 0

    def app(self, app_id: str, gs: dict, own: sb.Own | None = None) -> str:
        """Install the fake app and write its launcher; returns the launcher path. `own`: AppKata's
        other folders, as Settings and the other installs would name them (sandbox.Own)."""
        appdir = self.home / "apps" / app_id / "1.0"
        (appdir / "bin").mkdir(parents=True, exist_ok=True)
        exe = appdir / "bin" / "app"
        exe.write_text(APP)
        exe.chmod(0o755)
        return sb.write_launcher(app_id, app_id.title(), str(self.home / "apps"), str(appdir), "bin/app", gs, own=own)

    def on_a_machine_with(self, launcher: str, path: str) -> str:
        """`launcher` as AppKata writes it on a machine whose command folders are `path`: a copy with
        that PATH in the one line where a launcher sets its own (sandbox.host_path, CR1.5-31). The PATH
        a launcher is started with no longer decides what it runs, so a test that stands a bwrap in
        front of the real one, or takes a tool away, says so here: the machine has it there, or lacks it."""
        text = open(launcher).read()
        new, n = re.subn(r"^PATH=.*; export PATH$", lambda m: f"PATH={shlex.quote(path)}; export PATH", text, count=1, flags=re.M)
        assert n == 1 and text.count("export PATH") == 1, "a launcher sets its PATH once, in its header"
        self.machines += 1
        copy = self.home.parent / "machines" / str(self.machines) / "run"
        copy.parent.mkdir(parents=True)
        copy.write_text(new)
        copy.chmod(0o755)
        return str(copy)

    def run(self, launcher: str, snippet: str, cwd: str | None = None, env: dict | None = None,
            timeout: int = 30) -> subprocess.CompletedProcess:
        """Start the launcher with `snippet` for the app to run. A PATH in `env` is the machine's
        command folders (:meth:`on_a_machine_with`), as it was when the launcher took the caller's."""
        if env and "PATH" in env:
            launcher = self.on_a_machine_with(launcher, env["PATH"])
        return subprocess.run([launcher, snippet], cwd=cwd or str(self.home), env={**self.env, **(env or {})},
                              capture_output=True, text=True, timeout=timeout)


@pytest.fixture
def env(tmp_path, monkeypatch):
    return Env(tmp_path, monkeypatch)


def test_strict_app_runs_and_cannot_read_the_real_home(env):
    lp = env.app("vault", sb.resolve_template("strict"))
    r = env.run(lp, 'echo ran; cat "$HOME/.ssh/id_ed25519" 2>&1; echo x >> "$HOME/.bashrc"; echo done')
    assert r.returncode == 0, r.stderr
    assert "ran" in r.stdout and "SECRET-KEY" not in r.stdout
    assert (env.home / ".bashrc").read_text() == "# real bashrc\n"


def path_without(tmp_path, *tools) -> str:
    """A PATH with everything this machine has but `tools`: a system that lacks them."""
    bare = tmp_path / ("no-" + "-".join(tools))
    bare.mkdir(exist_ok=True)
    for d in ("/usr/local/bin", "/usr/bin", "/bin"):
        for f in os.listdir(d) if os.path.isdir(d) else ():
            if f not in tools and not os.path.lexists(bare / f):
                (bare / f).symlink_to(os.path.join(d, f))
    return str(bare)


def test_a_standard_app_without_xdg_dbus_proxy_runs_sandboxed_with_no_session_bus(env, tmp_path, monkeypatch):
    # Review 2, F12: with bwrap and no xdg-dbus-proxy, AppKata sandboxed nothing, Strict included.
    # A Standard app now runs sandboxed with no session bus: its private home, the network, and no
    # road to the host's bus, here a real socket at $XDG_RUNTIME_DIR/bus.
    import socket
    bus = socket.socket(socket.AF_UNIX)
    bus.bind(str(env.rt / "bus"))
    path = path_without(tmp_path, "xdg-dbus-proxy")
    monkeypatch.setenv("PATH", path)                      # what the generator sees: no proxy here
    lp = env.app("chat", sb.resolve_template("online-app"))
    assert "xdg-dbus-proxy \"$upstream\"" not in open(lp).read()
    r = env.run(lp, 'echo ran; cat "$HOME/.ssh/id_ed25519" 2>&1; echo "bus=${DBUS_SESSION_BUS_ADDRESS:-none}"; '
                    '[ -S "$XDG_RUNTIME_DIR/bus" ] && echo HOST-BUS; echo done',
                env={"PATH": path, "DBUS_SESSION_BUS_ADDRESS": f"unix:path={env.rt}/bus"})
    bus.close()
    assert r.returncode == 0, r.stderr
    assert "ran" in r.stdout and "done" in r.stdout and "SECRET-KEY" not in r.stdout
    assert "bus=unix:path=" in r.stdout and "HOST-BUS" not in r.stdout, r.stdout     # an address to nothing (R3-33)


def test_identity_marker_cannot_be_swapped_for_a_host_file(env):
    # Regression: .flatpak-info lived in the app's (writable) private home and was bound from there. An
    # app could replace it with a symlink to a host file; the next launch bound that file at
    # /.flatpak-info (bwrap resolves sources on the host), and the next regeneration overwrote it.
    gs = sb.resolve_template("strict")
    lp = env.app("evil", gs)
    key = str(env.home / ".ssh" / "id_ed25519")
    r = env.run(lp, f'cat /.flatpak-info; rm -f "$HOME/.flatpak-info"; ln -s {key} "$HOME/.flatpak-info"; echo planted')
    assert r.returncode == 0, r.stderr
    assert "name=io.appkata.evil" in r.stdout
    r = env.run(lp, "cat /.flatpak-info")
    assert "SECRET-KEY" not in r.stdout and "name=io.appkata.evil" in r.stdout
    env.app("evil", gs)                      # regenerating the launcher must not write through the link
    assert (env.home / ".ssh" / "id_ed25519").read_text() == "SECRET-KEY\n"
    assert not os.path.lexists(os.path.join(sb.sandbox_home("evil"), ".flatpak-info"))


# ---------------------------------------------------------------- the CLI tool's working directory (R17.3.3)

def _cli(env):
    return env.app("tool", sb.resolve_template("cli-tool"))


def test_cli_tool_sees_and_writes_the_project_folder_it_is_run_in(env):
    proj = env.home / "src" / "proj"
    proj.mkdir(parents=True)
    (proj / "in.txt").write_text("hello\n")
    r = env.run(_cli(env), 'pwd; cat in.txt; echo out > out.txt; ls "$HOME/.ssh" 2>&1; true', cwd=str(proj))
    assert r.returncode == 0, r.stderr
    assert str(proj) in r.stdout and "hello" in r.stdout
    assert (proj / "out.txt").read_text() == "out\n"
    assert "id_ed25519" not in r.stdout                   # the rest of the home stays hidden
    assert "bwrap" not in r.stderr                        # no warnings (e.g. two --chdir options)
    _a_tool_run_in_a_system_place_has_the_sandboxes_own(env)


def _a_tool_run_in_a_system_place_has_the_sandboxes_own(env):
    # CR1.5-6 (#381): ...and the folder it is run in is not the tool's where it is one of the system's
    # own places. Run from /tmp, /var/tmp or /dev/shm the tool got the whole folder read-write, bound
    # after the sandbox's own /tmp and /dev and over them, with what other programs keep there (tmux's
    # server socket, an ssh agent's). Now it runs in its private home, with the sandbox's own /tmp,
    # /dev and /proc, and says why. (Part of the test above, not one of its own, as the #380 run is.)
    lp = _cli(env)
    work = env.home.parent / "work"                        # a folder of /tmp that is not above this test's home
    work.mkdir()
    mark = f"appkata-cr1-5-6-{os.getpid()}"
    theirs = [str(work / mark), f"/var/tmp/{mark}", f"/dev/shm/{mark}"]
    mine = [t + "-mine" for t in theirs]
    try:
        for t in theirs:
            with open(t, "w") as f:
                f.write("x")
        for cwd in (str(work), "/var/tmp", "/dev/shm", "/proc", "/sys", "/etc", "/usr/share", "/var"):
            r = env.run(lp, f'pwd; [ -e {cwd}/{mark} ] && echo THEIRS; (echo x > {cwd}/{mark}-mine) 2>/dev/null; cat /proc/1/comm; true', cwd=cwd)
            assert r.returncode == 0 and r.stdout.split() == [str(env.home), "bwrap"], (cwd, r.stdout, r.stderr)   # in its private home, with its own /proc
            assert f"Tool runs sandboxed and isn't given {cwd} to work in: it is one of the system's own folders" in r.stderr, (cwd, r.stderr)
            assert "A file you name on the command line is handed over either way, unless it is in a never-shared folder" in r.stderr, (cwd, r.stderr)
            assert "bwrap" not in r.stderr, (cwd, r.stderr)
            assert not [m for m in mine if os.path.exists(m)], (cwd, mine)                                        # and nothing it wrote landed outside
    finally:
        for left in theirs + mine:
            if os.path.exists(left):
                os.unlink(left)


@pytest.mark.parametrize("where", ["home", "root", "parent", "symlink-to-home", "install-root", "sandboxes",
                                   "config", "ssh", "runtime", "local-bin", "environment.d", "plasma-env",
                                   "gnome-extensions", "kwin-scripts", "nemo-actions", "python-site", "chrome-hosts"])
def test_cli_tool_never_gets_the_home_or_above_or_appkata_areas(env, where):
    # Regression: the "$cwd" grant was `--bind "$PWD" "$PWD"`, mounted after the private home, so a
    # tool run from ~ (where terminals start) got the real home read-write — ~/.ssh, ~/.bashrc and all
    # — and one run from / got the whole filesystem. Later: ~/.config (autostart, systemd units),
    # ~/.ssh and $XDG_RUNTIME_DIR (the real session bus, bound over the filtered one) were still shared.
    # Later still (R3): ~/.local/bin (on PATH), ~/.config/environment.d and KDE's plasma-workspace/env
    # were, so a tool run from there could leave a program or a variable for the next login.
    lp = _cli(env)
    link = env.home.parent / "homelink"
    if not link.exists():
        link.symlink_to(env.home)
    for d in (".config/autostart", ".local/bin", ".config/environment.d", ".config/plasma-workspace/env",
              ".local/share/gnome-shell/extensions", ".local/share/kwin/scripts",
              ".local/share/nemo/actions", ".local/lib/python3.12/site-packages", ".config/google-chrome/NativeMessagingHosts"):
        (env.home / d).mkdir(parents=True, exist_ok=True)
    cwd = {"home": env.home, "root": "/", "parent": env.home.parent, "symlink-to-home": link,
           "install-root": env.home / "apps", "sandboxes": sb.sandboxes_root(),
           "config": env.home / ".config", "ssh": env.home / ".ssh", "runtime": env.rt,
           "local-bin": env.home / ".local" / "bin", "environment.d": env.home / ".config" / "environment.d",
           "plasma-env": env.home / ".config" / "plasma-workspace" / "env",
           # the desktop's extension and script folders (round four, R4-9)
           "gnome-extensions": env.home / ".local" / "share" / "gnome-shell" / "extensions",
           "kwin-scripts": env.home / ".local" / "share" / "kwin" / "scripts",
           # Mint's file manager, Python's user site and a browser's native-messaging folder (round five, R5-2)
           "nemo-actions": env.home / ".local" / "share" / "nemo" / "actions",
           "python-site": env.home / ".local" / "lib" / "python3.12" / "site-packages",
           "chrome-hosts": env.home / ".config" / "google-chrome" / "NativeMessagingHosts"}[where]
    r = env.run(lp, 'cat "$HOME/.ssh/id_ed25519" 2>&1; cat ' + str(env.home / ".ssh/id_ed25519") +
                ' 2>&1; echo pwned >> "$HOME/.bashrc"; echo pwned >> ' + str(env.home / ".bashrc") + ' 2>&1; pwd',
                cwd=str(cwd))
    assert r.returncode == 0, r.stderr
    assert "SECRET-KEY" not in r.stdout
    assert (env.home / ".bashrc").read_text() == "# real bashrc\n"
    assert "can't see" in r.stderr                        # it says why
    assert "bwrap" not in r.stderr and r.stdout.strip().endswith(str(env.home))   # in its private home


# ---------------------------------------------------------------- network (R17.2)

def _host_resolves(name: str, wait: float = 60) -> bool:
    """Whether this machine resolves name, given up to wait seconds: a VM's resolver can take a while
    to answer when several VMs share the host (the walk thru of 2026-10-30, item 2)."""
    deadline = time.monotonic() + wait
    while subprocess.run(["getent", "hosts", name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode:
        if time.monotonic() > deadline:
            return False
        time.sleep(2)
    return True


def test_a_network_grant_includes_working_dns(env):
    # Regression: on Ubuntu/Mint /etc/resolv.conf is a symlink into /run/systemd/resolve, which the
    # sandbox didn't bind, so an app with the network grant couldn't resolve any name. (Containers
    # bind a plain resolv.conf, so only a real install — scripts/test-sandbox.sh launcher-vm — shows it.)
    # Where this machine can't resolve names it skips, which the VMs' skip lists don't allow.
    if not _host_resolves("example.com"):
        pytest.skip("this host can't resolve names")
    r = env.run(env.app("web", sb.resolve_template("online-app")), "getent hosts example.com && echo RESOLVED; true")
    assert "RESOLVED" in r.stdout, (r.stdout, r.stderr, os.path.realpath("/etc/resolv.conf"))


def test_no_network_grant_means_no_network(env):
    r = env.run(env.app("offline", sb.resolve_template("offline-editor")), "getent hosts example.com && echo RESOLVED; true")
    assert "RESOLVED" not in r.stdout


# ---------------------------------------------------------------- display (17.9)

def _listen(path: str):
    import socket
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.bind(path)
    s.listen(1)
    return s


def test_wayland_display_reaches_the_app(env):
    # Regression: --setenv WAYLAND_DISPLAY/DISPLAY/XAUTHORITY were emitted before --clearenv, which
    # bwrap applies in order, so they were wiped: the socket was bound but no GUI app could find it.
    sock = _listen(str(env.rt / "wayland-7"))
    try:
        r = env.run(env.app("gui", sb.resolve_template("strict")),
                    'echo "W=$WAYLAND_DISPLAY"; [ -S "$XDG_RUNTIME_DIR/$WAYLAND_DISPLAY" ] && echo SOCKET',
                    env={"WAYLAND_DISPLAY": "wayland-7"})
    finally:
        sock.close()
    assert "W=wayland-7" in r.stdout and "SOCKET" in r.stdout, (r.stdout, r.stderr)


def test_x11_display_reaches_the_app(env, tmp_path):
    xdir = "/tmp/.X11-unix"
    try:
        os.makedirs(xdir, exist_ok=True)
        sock = _listen(f"{xdir}/X77")
    except OSError:
        pytest.skip("can't create an X11 socket here")
    xa = tmp_path / "xauth"
    xa.write_text("cookie")
    try:
        r = env.run(env.app("x", sb.resolve_template("strict")),
                    'echo "D=$DISPLAY A=$XAUTHORITY"; [ -S /tmp/.X11-unix/X77 ] && echo SOCKET; cat "$XAUTHORITY"',
                    env={"DISPLAY": ":77", "XAUTHORITY": str(xa)})
    finally:
        sock.close()
        os.unlink(f"{xdir}/X77")
    assert f"D=:77 A={xa}" in r.stdout and "SOCKET" in r.stdout and "cookie" in r.stdout, (r.stdout, r.stderr)


@pytest.mark.parametrize("x11_grant", [True, False])
def test_on_wayland_x11_apps_get_xwayland_only_with_the_grant(env, x11_grant):
    # An app that only speaks X11 couldn't open a window on a Wayland session: only the Wayland socket
    # was bound, even with XWayland running. The "x11" device grant (default on) adds it.
    xdir = "/tmp/.X11-unix"
    try:
        os.makedirs(xdir, exist_ok=True)
        xsock = _listen(f"{xdir}/X78")
    except OSError:
        pytest.skip("can't create an X11 socket here")
    wsock = _listen(str(env.rt / "wayland-8"))
    gs = sb.resolve_template("online-app")
    assert "x11" in gs["devices"]                      # on by default
    if not x11_grant:
        gs["devices"].discard("x11")
    try:
        r = env.run(env.app("mixed", gs), 'echo "W=$WAYLAND_DISPLAY D=$DISPLAY"; [ -S /tmp/.X11-unix/X78 ] && echo XSOCK; true',
                    env={"WAYLAND_DISPLAY": "wayland-8", "DISPLAY": ":78"})
    finally:
        xsock.close(); wsock.close()
        os.unlink(f"{xdir}/X78")
    assert "W=wayland-8" in r.stdout
    if x11_grant:
        assert "D=:78" in r.stdout and "XSOCK" in r.stdout, (r.stdout, r.stderr)
    else:
        assert "D=\n" in r.stdout and "XSOCK" not in r.stdout


@pytest.mark.parametrize("network", [True, False])
def test_the_x11_abstract_socket_follows_the_network_grant_not_the_x11_one(env, network):
    # Round four, R4-8 (R17.9): the "X11 apps" grant withholds the socket file, DISPLAY and the
    # cookie, but the X server's abstract-namespace socket lives in the network namespace, which
    # --share-net shares; so with the network an app can still connect to it, and only Xwayland's
    # cookie check (mutter, kwin; not wlroots) keeps it out. Documented rather than closed: there is
    # no namespace that shares the network and not the abstract sockets.
    import socket
    name = "\0/tmp/.X11-unix/X79"
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        s.bind(name)
    except OSError:
        pytest.skip("can't bind an abstract socket here")
    s.listen(1)
    wsock = _listen(str(env.rt / "wayland-9"))
    gs = sb.resolve_template("online-app" if network else "offline-editor")
    gs["devices"].discard("x11")
    try:
        r = env.run(env.app("abs", gs),
                    "python3 -c \"import socket; socket.socket(socket.AF_UNIX).connect('\\0/tmp/.X11-unix/X79'); print('CONNECTED')\" 2>&1; "
                    "[ -S /tmp/.X11-unix/X79 ] && echo XSOCK; true",
                    env={"WAYLAND_DISPLAY": "wayland-9", "DISPLAY": ":79"})
    finally:
        s.close(); wsock.close()
    assert "XSOCK" not in r.stdout                                   # the grant is off: no socket file either way
    # a line, not a substring: Python 3.13's traceback prints the failing source line, which names the
    # word (the version matrix's Ubuntu 25.04 corner, round eight)
    assert ("CONNECTED" in r.stdout.splitlines()) is network, (r.stdout, r.stderr)


# ---------------------------------------------------------------- the session bus (R17.5)

@pytest.mark.parametrize("bus", ["unset", "dead"])
def test_standard_apps_run_without_a_session_bus(env, bus):
    # Regression: Standard (cli-tool included) always started the bus proxy and bound its socket. With
    # no session bus — SSH, cron, a TTY — the proxy exited, bwrap failed on the missing socket and the
    # app never ran.
    extra = {"DBUS_SESSION_BUS_ADDRESS": f"unix:path={env.rt}/nonexistent"} if bus == "dead" else {}
    proj = env.home / "proj"
    proj.mkdir()
    r = env.run(env.app("tool", sb.resolve_template("cli-tool")), "echo RAN", cwd=str(proj), env=extra)
    assert r.returncode == 0 and "RAN" in r.stdout, (r.stdout, r.stderr)


# A desktop's shell, as far as the bus shows it: one connection that owns a capability's direct name
# and serves that service -- and owns a name of its own, with an object that runs what it is sent
# (as Cinnamon's org.Cinnamon.Eval does). It serves that interface on the service's own object
# too, and broadcasts a signal of its own beside the service's.
_SHELL = """
import sys
from gi.repository import Gio, GLib
name, paths, log = sys.argv[1], sys.argv[2].split(","), open(sys.argv[3], "a")
SERVICES = {
 "org.freedesktop.Notifications": '''<method name="GetServerInformation"><arg type="s" direction="out"/><arg type="s" direction="out"/>
   <arg type="s" direction="out"/><arg type="s" direction="out"/></method><signal name="NotificationClosed"><arg type="u"/><arg type="u"/></signal>''',
 "org.freedesktop.ScreenSaver": '''<method name="Inhibit"><arg type="s" direction="in"/><arg type="s" direction="in"/><arg type="u" direction="out"/></method>
   <signal name="ActiveChanged"><arg type="b"/></signal>''',
 "org.kde.StatusNotifierWatcher": '''<method name="RegisterStatusNotifierItem"><arg type="s" direction="in"/></method>
   <property name="IsStatusNotifierHostRegistered" type="b" access="read"/><signal name="StatusNotifierHostRegistered"/>''',
}
ANSWERS = {"GetServerInformation": GLib.Variant("(ssss)", ("stand-in", "AppKata", "1", "1.2")), "Inhibit": GLib.Variant("(u)", (42,)),
           "RegisterStatusNotifierItem": None}
SIGNALS = {"org.freedesktop.Notifications": ("NotificationClosed", GLib.Variant("(uu)", (1, 2))),
           "org.freedesktop.ScreenSaver": ("ActiveChanged", GLib.Variant("(b)", (False,))), "org.kde.StatusNotifierWatcher": ("StatusNotifierHostRegistered", None)}
service = Gio.DBusNodeInfo.new_for_xml(f'<node><interface name="{name}">{SERVICES[name]}</interface></node>').interfaces[0]
shell = Gio.DBusNodeInfo.new_for_xml('''<node><interface name="org.appkata.Shell"><method name="Eval"><arg type="s" direction="in"/>
  <arg type="b" direction="out"/></method><signal name="Said"><arg type="s"/></signal></interface></node>''').interfaces[0]
def call(conn, sender, path, iface, method, params, inv):
    log.write(f"{'EVAL' if method == 'Eval' else 'SERVED'} {iface}.{method} at {path} {params.unpack()}\\n"); log.flush()
    inv.return_value(GLib.Variant("(b)", (True,)) if method == "Eval" else ANSWERS[method])
bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
for path in paths:
    bus.register_object(path, service, call, lambda *a: GLib.Variant("b", True), None)
    bus.register_object(path, shell, call, None, None)              # another interface on the service's own object
bus.register_object("/org/appkata/Shell", shell, call, None, None)  # a second object on the same connection
def tick():
    bus.emit_signal(None, paths[0], name, *SIGNALS[name])
    bus.emit_signal(None, "/org/appkata/Shell", "org.appkata.Shell", "Said", GLib.Variant("(s)", ("the shell's own",)))
    return True
GLib.timeout_add(100, tick)
Gio.bus_own_name_on_connection(bus, "org.appkata.Shell", Gio.BusNameOwnerFlags.NONE, None, None)
Gio.bus_own_name_on_connection(bus, name, Gio.BusNameOwnerFlags.NONE, None, None)
GLib.MainLoop().run()
"""

# The app: its service's own call, then every road to the shell's Eval, then what it hears.
_SHELL_PROBE = """
import sys
from gi.repository import Gio, GLib
name, paths = sys.argv[1], sys.argv[2].split(",")
OWN = {"org.freedesktop.Notifications": ("GetServerInformation", None), "org.freedesktop.ScreenSaver": ("Inhibit", GLib.Variant("(ss)", ("appkata", "a call"))),
       "org.kde.StatusNotifierWatcher": ("RegisterStatusNotifierItem", GLib.Variant("(s)", ("/an/item",)))}
bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
heard = set()
bus.signal_subscribe(None, None, None, None, None, Gio.DBusSignalFlags.NONE, lambda c, s, p, i, m, a: heard.add(f"{i}.{m}"))
def ask(what, dest, path, iface, method, args=None):
    try:
        bus.call_sync(dest, path, iface, method, args, None, Gio.DBusCallFlags.NONE, 3000, None)
        print(what, "ANSWERED", flush=True)
    except GLib.Error as e:
        print(what, "REFUSED", Gio.DBusError.get_remote_error(e), flush=True)
eval_ = lambda road: GLib.Variant("(s)", (road,))
for path in paths:
    ask(f"SERVICE {path}", name, path, name, *OWN[name])
    ask(f"INTROSPECT {path}", name, path, "org.freedesktop.DBus.Introspectable", "Introspect")
    ask(f"OTHER-INTERFACE {path}", name, path, "org.appkata.Shell", "Eval", eval_("the service's own object"))
ask("PROPERTY", name, paths[0], "org.freedesktop.DBus.Properties", "Get", GLib.Variant("(ss)", (name, "IsStatusNotifierHostRegistered")))
ask("SECOND-OBJECT", name, "/org/appkata/Shell", "org.appkata.Shell", "Eval", eval_("the service's name"))
try:
    owner = bus.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "GetNameOwner", GLib.Variant("(s)", (name,)),
                          None, Gio.DBusCallFlags.NONE, 3000, None).unpack()[0]
    ask("UNIQUE-NAME", owner, "/org/appkata/Shell", "org.appkata.Shell", "Eval", eval_("the owner's unique name"))
except GLib.Error as e:
    print("OWNER HIDDEN", Gio.DBusError.get_remote_error(e), flush=True)
ask("SHELL-NAME", "org.appkata.Shell", "/org/appkata/Shell", "org.appkata.Shell", "Eval", eval_("the shell's own name"))
loop = GLib.MainLoop()
GLib.timeout_add(700, loop.quit)
loop.run()
print("HEARD", *sorted(h for h in heard if not h.startswith("org.freedesktop.DBus.")), flush=True)
"""

# capability: its direct name, the objects its service is on, the signal the stand-in sends from it,
# and whether the app hears it (Keep the screen awake hears nothing of the screen saver: CR1.5-44)
_DIRECT_NAMES = {"notifications": ("org.freedesktop.Notifications", "/org/freedesktop/Notifications", "NotificationClosed"),
                 "inhibit": ("org.freedesktop.ScreenSaver", "/org/freedesktop/ScreenSaver,/ScreenSaver", "ActiveChanged", False),
                 "tray": ("org.kde.StatusNotifierWatcher", "/StatusNotifierWatcher", "StatusNotifierHostRegistered")}


# A connection that owns a name and broadcasts on an interface and an object of its own beside the
# name's: what a proxy with a --call rule on the name lets through of its broadcasts.
_BROADCASTER = """
from gi.repository import Gio, GLib
bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
Gio.bus_own_name_on_connection(bus, "org.appkata.Leak", Gio.BusNameOwnerFlags.NONE, None, None)
def tick():
    bus.emit_signal(None, "/org/appkata/Other", "org.appkata.Other", "Said", None)
    return True
GLib.timeout_add(100, tick)
GLib.MainLoop().run()
"""
_LISTENER = """
import sys
from gi.repository import Gio, GLib
conn = Gio.DBusConnection.new_for_address_sync(sys.argv[1], Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION, None, None)
heard = set()
conn.signal_subscribe(None, None, None, None, None, Gio.DBusSignalFlags.NONE, lambda c, s, p, i, m, a: heard.add(f"{i}.{m}"))
loop = GLib.MainLoop()
GLib.timeout_add(1500, loop.quit)
loop.run()
print(*sorted(heard))
"""


def _the_proxy_keeps_broadcasts_to_their_rules(env, bus, tmp_path) -> bool:
    """Whether this xdg-dbus-proxy lets through only the broadcasts its rules name. 0.1.6 and 0.1.7
    let every broadcast of a name's owner through once any --call or --broadcast rule names the
    name (upstream's 0.1.8 fixed it: CVE-2026-93676, GHSA-r7hp-698j-2h6c); 0.1.5 never did, and
    Debian's 0.1.6-1+deb13u2 carries the fix while still saying 0.1.6, so it is asked of the proxy."""
    on_bus = {**env.env, "DBUS_SESSION_BUS_ADDRESS": bus.addr}
    sock = str(tmp_path / "leak-proxy")
    sender = subprocess.Popen(["python3", "-c", _BROADCASTER], env=on_bus, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    proxy = subprocess.Popen(["xdg-dbus-proxy", bus.addr, sock, "--filter", "--call=org.appkata.Leak=org.appkata.Leak.*@/org/appkata/Leak"],
                             env=on_bus, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(50):
            owned = subprocess.run(["gdbus", "call", "--session", "--dest", "org.freedesktop.DBus", "--object-path", "/org/freedesktop/DBus", "--method",
                                    "org.freedesktop.DBus.NameHasOwner", "org.appkata.Leak"], env=on_bus, capture_output=True, text=True).stdout
            if os.path.exists(sock) and "true" in owned:
                break
            time.sleep(0.1)
        heard = subprocess.run(["python3", "-c", _LISTENER, f"unix:path={sock}"], env=on_bus, capture_output=True, text=True, timeout=30).stdout
    finally:
        proxy.terminate()
        sender.terminate()
    return "org.appkata.Other.Said" not in heard


def _a_direct_name_reaches_its_service_and_nothing_else_its_owner_serves(env, bus, tmp_path, cap, keeps=True):
    """CR1.5-3: `--talk=NAME` is no grant of one service. xdg-dbus-proxy gives it to the connection
    that owns NAME -- every object and interface it serves, by its unique name too -- and on
    Cinnamon the desktop's own shell owns org.freedesktop.Notifications: a `standard` app's
    "Notifications" chip reached org.Cinnamon.Eval, which ran a command as the user outside the
    sandbox (shown on the Mint 22.3 desktop). Every stand-in until then owned one name and served
    one object, so nothing showed it. This one is a shell: the app's own service answers, on each
    of its objects, and the shell's Eval is refused by every road, and never arrives."""
    name, paths, signal, *heard = _DIRECT_NAMES[cap]
    log = tmp_path / f"shell-{cap}.log"
    on_bus = {**env.env, "DBUS_SESSION_BUS_ADDRESS": bus.addr}
    shell = subprocess.Popen(["python3", "-c", _SHELL, name, paths, str(log)], env=on_bus, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(50):
            r = subprocess.run(["gdbus", "call", "--session", "--dest", "org.freedesktop.DBus", "--object-path", "/org/freedesktop/DBus",
                                "--method", "org.freedesktop.DBus.NameHasOwner", name], env=on_bus, capture_output=True, text=True)
            if r.stdout.strip() == "(true,)":
                break
            subprocess.run(["sleep", "0.1"])
        for app_id in (cap, f"no-{cap}"):
            d = env.home / "apps" / app_id / "1.0" / "bin"
            d.mkdir(parents=True, exist_ok=True)
            (d / "probe.py").write_text(_SHELL_PROBE)
        probe = f'python3 "$(dirname "$0")/probe.py" {name} {paths}'
        gs = sb.apply_overrides(sb.resolve_template("standard"), {"caps": [cap]})
        r = env.run(env.app(cap, gs), probe, env={"DBUS_SESSION_BUS_ADDRESS": bus.addr}, timeout=60)
        served = log.read_text()
        r2 = env.run(env.app(f"no-{cap}", sb.apply_overrides(gs, {"caps": []})), probe, env={"DBUS_SESSION_BUS_ADDRESS": bus.addr}, timeout=60)
    finally:
        shell.terminate()
        shell.wait()
    out = r.stdout.splitlines()
    for path in paths.split(","):
        assert f"SERVICE {path} ANSWERED" in out and f"INTROSPECT {path} ANSWERED" in out, (r.stdout, r.stderr)   # the capability still works
        assert f"OTHER-INTERFACE {path} REFUSED org.freedesktop.DBus.Error.AccessDenied" in out, r.stdout
    for road in ("SECOND-OBJECT", "UNIQUE-NAME"):
        assert f"{road} REFUSED org.freedesktop.DBus.Error.AccessDenied" in out, r.stdout
    assert any(l.startswith("SHELL-NAME REFUSED") for l in out), r.stdout              # a name it was never given: not there at all
    assert "EVAL" not in served and served.count("SERVED") == len(paths.split(",")), served   # nothing but the service's own calls arrived
    # the Properties calls a tray library makes (Qt: IsStatusNotifierHostRegistered) pass; the other services have none
    assert ("PROPERTY ANSWERED" if cap == "tray" else "PROPERTY REFUSED org.freedesktop.DBus.Error.AccessDenied") in out, r.stdout
    hears = [l for l in out if l.startswith("HEARD")]
    if keeps:                       # the service's own signal, and not the shell's
        assert hears == [f"HEARD {name}.{signal}" if heard != [False] else "HEARD"], r.stdout
    else:                           # a proxy without the fix lets all the owner broadcasts through (R17.17), and only that
        assert len(hears) == 1 and set(hears[0].split()[1:]) == {f"{name}.{signal}", "org.appkata.Shell.Said"}, r.stdout
    out2 = r2.stdout.splitlines()                                                       # and without the capability, not even the service
    assert not [l for l in out2 if "ANSWERED" in l] and "OWNER HIDDEN org.freedesktop.DBus.Error.NameHasNoOwner" in out2, (r2.stdout, r2.stderr)
    assert "HEARD" in out2, r2.stdout


@needs_proxy
def test_standard_apps_reach_the_filtered_bus_when_there_is_one(env, tmp_path):
    bus = _Bus(env)
    try:
        r = env.run(env.app("gui", sb.resolve_template("online-app")),
                    'echo "A=$DBUS_SESSION_BUS_ADDRESS"; [ -S "$XDG_RUNTIME_DIR/bus" ] && echo BUS',
                    env={"DBUS_SESSION_BUS_ADDRESS": bus.addr})
        assert "BUS" in r.stdout and f"A=unix:path={env.rt}/bus" in r.stdout, (r.stdout, r.stderr)
        # and what they reach on it by a capability's direct name is that service alone (CR1.5-3); what
        # they hear of its owner's broadcasts, that service's signal alone where the proxy has the fix
        # for GHSA-r7hp-698j-2h6c, and everything the owner broadcasts where it hasn't (Ubuntu 26.04's
        # 0.1.7, an LMDE 7 not yet updated: the VMs found it, R17.17)
        keeps = _the_proxy_keeps_broadcasts_to_their_rules(env, bus, tmp_path)
        for cap in _DIRECT_NAMES:
            _a_direct_name_reaches_its_service_and_nothing_else_its_owner_serves(env, bus, tmp_path, cap, keeps)
    finally:
        bus.close()


# ---------------------------------------------------------------- run-time words stay whole

def test_empty_and_spaced_values_and_app_arguments_pass_through_intact(env):
    # Regression: the env passthrough and display options were collected in a string and expanded
    # unquoted, so a variable set to "" vanished and shifted bwrap's arguments (QT_STYLE_OVERRIDE=""
    # made bwrap set it to "--setenv" and then try to execute "LANG"), and spaces split values.
    lp = env.app("words", sb.resolve_template("strict"))
    r = subprocess.run([lp, 'printf "[%s]" "$QT_STYLE_OVERRIDE" "$XCURSOR_THEME" "$LANG" "$2" "$3"; echo',
                        "two words", "*"], cwd=str(env.home), capture_output=True, text=True, timeout=30,
                       env={**env.env, "QT_STYLE_OVERRIDE": "", "XCURSOR_THEME": "Breeze Snow"})
    assert r.returncode == 0, r.stderr
    assert "[][Breeze Snow][C.UTF-8][two words][*]" in r.stdout, (r.stdout, r.stderr)


def test_cli_tool_in_a_folder_with_spaces(env):
    proj = env.home / "My Projects" / "a b"
    proj.mkdir(parents=True)
    r = env.run(env.app("tool", sb.resolve_template("cli-tool")), "pwd; echo hi > out.txt", cwd=str(proj))
    assert r.returncode == 0 and str(proj) in r.stdout, (r.stdout, r.stderr)
    assert (proj / "out.txt").read_text() == "hi\n"


_PORTAL_SERVICES = ("org.freedesktop.portal.", "org.freedesktop.impl.portal.")


_BUS_CONF = """<!DOCTYPE busconfig PUBLIC "-//freedesktop//DTD D-Bus Bus Configuration 1.0//EN"
 "http://www.freedesktop.org/standards/dbus/1.0/busconfig.dtd">
<busconfig>
  <type>session</type>
  <keep_umask/>
  <listen>unix:tmpdir=/tmp</listen>
  <auth>EXTERNAL</auth>
  <servicedir>{services}</servicedir>
  <policy context="default">
    <allow send_destination="*" eavesdrop="true"/>
    <allow eavesdrop="true"/>
    <allow own="*"/>
  </policy>
</busconfig>
"""


def _bus_conf(env, starts=()) -> str:
    """The test bus's configuration: it starts on demand only the portal services this machine has
    (`--session` would start any it has installed, and on a desktop gnome-keyring then took a name
    the app under test should own: review 3, R3-34), and the service files `starts` names, and
    listens where a session's own bus does unless it is told an address."""
    services = env.rt / "bus-services"
    services.mkdir(exist_ok=True)
    for d in ("/usr/share/dbus-1/services", "/usr/local/share/dbus-1/services"):
        for f in sorted(os.listdir(d)) if os.path.isdir(d) else []:
            if (f.startswith(_PORTAL_SERVICES) or f in starts) and not (services / f).exists():
                (services / f).symlink_to(os.path.join(d, f))
    conf = env.rt / "bus.conf"
    conf.write_text(_BUS_CONF.format(services=services))
    return str(conf)


class _Bus:
    """A real session bus for the test user (dbus-daemon), torn down afterwards: in the runtime
    folder, where a login session's is, at the socket file `at`, or on an abstract socket, where
    dbus 1.12 put a dbus-run-session bus (R17.9)."""

    def __init__(self, env, abstract=False, at=None, starts=()):
        at = str(at or env.rt / "bus")
        self.addr = f"unix:abstract=/tmp/appkata-test-bus-{os.getpid()}-{id(self)}" if abstract else f"unix:path={at}"
        self.p = subprocess.Popen(["dbus-daemon", f"--config-file={_bus_conf(env, starts)}", f"--address={self.addr}", "--nofork", "--nopidfile"],
                                  env=env.env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(50):
            if os.path.exists(at) if not abstract else subprocess.run(
                    ["gdbus", "call", "--session", "--dest", "org.freedesktop.DBus", "--object-path", "/org/freedesktop/DBus", "--method",
                     "org.freedesktop.DBus.GetId"], env={**env.env, "DBUS_SESSION_BUS_ADDRESS": self.addr}, capture_output=True).returncode == 0:
                break
            subprocess.run(["sleep", "0.1"])

    def close(self):
        self.p.terminate()


class _RunSession:
    """A session started with `dbus-run-session`, as sway and other bare compositors are: its bus
    listens where the configuration says, unix:tmpdir=/tmp as the session's own does -- a socket
    file under /tmp with dbus 1.14 and later (Mint 22.3, LMDE 7, Ubuntu 24.04), an abstract socket
    with 1.12 -- and so outside the runtime folder either way."""

    def __init__(self, env):
        self.p = subprocess.Popen(["dbus-run-session", "--config-file", _bus_conf(env), "--", "sh", "-c", 'echo "$DBUS_SESSION_BUS_ADDRESS"; exec cat'],
                                  env=env.env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        self.addr = self.p.stdout.readline().strip()

    def close(self):
        self.p.stdin.close()            # the session ends with its program, and its bus with it
        self.p.wait(timeout=10)


@needs_proxy
def test_the_test_bus_starts_only_the_portals_on_demand(env):
    # Review 3, R3-34: the test bus was a plain `dbus-daemon --session`, which starts any service the
    # machine has installed. On stock Mint a host client's call started gnome-keyring, which took
    # org.freedesktop.secrets before the sandboxed app under test could, and a name the filter should
    # have refused was "refused" because it was taken. A test meets what it starts, and the portals.
    bus = _Bus(env)
    try:
        r = subprocess.run(["gdbus", "call", "--session", "--dest", "org.freedesktop.DBus", "--object-path", "/org/freedesktop/DBus",
                            "--method", "org.freedesktop.DBus.ListActivatableNames"],
                           env={**env.env, "DBUS_SESSION_BUS_ADDRESS": bus.addr}, capture_output=True, text=True)
    finally:
        bus.close()
    names = re.findall(r"'([^']+)'", r.stdout)
    assert "org.freedesktop.DBus" in names, (r.stdout, r.stderr)
    assert [n for n in names if n != "org.freedesktop.DBus" and not n.startswith(_PORTAL_SERVICES)] == []


_OWN = ('gdbus call --session --dest org.freedesktop.DBus --object-path /org/freedesktop/DBus '
        '--method org.freedesktop.DBus.RequestName {} 4 2>&1')


@needs_proxy
def test_an_app_with_a_long_id_still_starts_at_standard(env):
    # Review 3, R3-12: the proxy's socket was named by the id, and a Unix socket path holds 107 bytes,
    # so an id past ~60 characters (a long app name's slug) couldn't start: the proxy failed without a
    # word and bwrap said "Can't find source path". The socket is named by a hash of the id now.
    app_id = "ultimate-developer-toolkit-for-embedded-systems-and-firmware-engineering"
    bus = _Bus(env)
    try:
        r = env.run(env.app(app_id, sb.resolve_template("standard")), "echo RAN", env={"DBUS_SESSION_BUS_ADDRESS": bus.addr})
    finally:
        bus.close()
    assert r.returncode == 0 and "RAN" in r.stdout, (r.stdout, r.stderr)


@needs_proxy
def test_a_bus_filter_that_does_not_start_is_said_plainly(env):
    # a filter that can't make its socket ends the launch with a sentence, not bwrap's missing file
    lp = env.app("nofilter", sb.resolve_template("standard"))
    (env.rt / "appkata").mkdir(exist_ok=True)
    (env.rt / "appkata").chmod(0o500)
    try:
        r = env.run(lp, "echo RAN", env={"DBUS_SESSION_BUS_ADDRESS": f"unix:path={env.rt}/nobus"})
    finally:
        (env.rt / "appkata").chmod(0o700)
    assert r.returncode == 1 and "RAN" not in r.stdout, (r.stdout, r.stderr)
    assert "the session-bus filter (xdg-dbus-proxy) did not start, so Nofilter cannot run sandboxed here" in r.stderr
    assert "Can't find source path" not in r.stderr


@needs_proxy
def test_the_tray_capability_starts_the_proxy_and_lets_the_app_own_its_item_name(env):
    # Regression: the tray capability passed --own=org.kde.StatusNotifierItem-*, which xdg-dbus-proxy
    # rejects ("not a valid dbus name") and exits, so every messenger-template app got no bus at all.
    # StatusNotifierItem names are org.kde.StatusNotifierItem-<pid>-<n>; in bwrap's pid namespace the
    # app is pid 2 (as in Flatpak).
    if not shutil.which("gdbus"):
        pytest.skip("needs gdbus")
    bus = _Bus(env)
    try:
        r = env.run(env.app("chat", sb.resolve_template("messenger")),
                    'echo "PID=$$"; ' + _OWN.format("org.kde.StatusNotifierItem-2-1") + "; "
                    + _OWN.format("org.kde.StatusNotifierWatcher") + "; true",
                    env={"DBUS_SESSION_BUS_ADDRESS": bus.addr})
    finally:
        bus.close()
    out = r.stdout.splitlines()
    assert "PID=2" in out, (r.stdout, r.stderr)
    assert out[1] == "(uint32 1,)", (r.stdout, r.stderr)          # owned its tray item name
    assert "(uint32 1,)" not in out[2]                           # but can't impersonate the watcher


# ---------------------------------------------------------------- devices (R17.2.1)

def test_the_camera_grant_binds_the_video_devices(env):
    # Regression: the camera device grant changed nothing in the launcher, so apps that open the camera
    # directly (Chromium/Electron) couldn't, with or without it.
    if not os.path.exists("/dev/video0"):
        pytest.skip("no /dev/video0 here (scripts/test-sandbox.sh launcher makes one)")
    snippet = "[ -c /dev/video0 ] && echo CAMERA; true"
    with_cam = env.run(env.app("chat", sb.resolve_template("messenger")), snippet)
    without = env.run(env.app("web", sb.resolve_template("online-app")), snippet)
    assert "CAMERA" in with_cam.stdout, (with_cam.stdout, with_cam.stderr)
    assert "CAMERA" not in without.stdout


def test_gpu_nodes_can_be_identified_through_sys(env):
    # Regression: /sys wasn't bound, so libdrm's drmGetDevices2() (which maps a /dev/dri node's
    # major:minor through /sys/dev/char) found no devices and Mesa/Chromium fell back to software
    # rendering. The VM run (scripts/test-sandbox.sh launcher-vm) has a virtio GPU for this.
    nodes = sorted(n for n in os.listdir("/dev/dri") if n.startswith(("card", "renderD"))) if os.path.isdir("/dev/dri") else []
    if not nodes:
        pytest.skip("no /dev/dri here")
    node = f"/dev/dri/{nodes[0]}"
    r = env.run(env.app("gfx", sb.resolve_template("strict")),
                f'm=$(stat -c "%t %T" {node}); set -- $m; d=$(printf "%d:%d" 0x$1 0x$2); '
                'ls -d "/sys/dev/char/$d/device/drm" && echo FOUND; true')
    assert "FOUND" in r.stdout, (r.stdout, r.stderr)


# ---------------------------------------------------------------- terminals (R17.3.3)

def _run_on_tty(env, launcher: str, snippet: str, cwd: str) -> str:
    """Run the launcher with a pseudo-terminal as its controlling terminal, as from an interactive shell."""
    import fcntl
    import pty
    import termios
    master, slave = pty.openpty()

    def pre():
        os.setsid()
        fcntl.ioctl(slave, termios.TIOCSCTTY, 0)
    p = subprocess.Popen([launcher, snippet], stdin=slave, stdout=slave, stderr=slave, preexec_fn=pre,
                         env=env.env, cwd=cwd)
    os.close(slave)
    data = b""
    while True:
        try:
            chunk = os.read(master, 4096)
        except OSError:
            break
        if not chunk:
            break
        data += chunk
    p.wait(timeout=30)
    os.close(master)
    return data.decode(errors="replace")


def test_terminal_tools_keep_their_controlling_terminal(env):
    # Regression: --new-session (setsid) detached the sandboxed program from the terminal, so /dev/tty
    # couldn't be opened (fzf, less, editors, password prompts) and resize/job-control signals were lost.
    proj = env.home / "proj"
    proj.mkdir()
    out = _run_on_tty(env, env.app("tool", sb.resolve_template("cli-tool")),
                      'if (: </dev/tty) 2>/dev/null; then echo TTY-OK; else echo TTY-FAIL; fi', str(proj))
    assert "TTY-OK" in out, out


def test_terminal_input_injection_stays_blocked(env):
    # What --new-session was guarding against (CVE-2017-5226): TIOCSTI pushing keystrokes into the
    # terminal, to run as commands after the app exits. A seccomp filter now refuses TIOCSTI/TIOCLINUX.
    if not shutil.which("python3"):
        pytest.skip("needs python3 inside the sandbox")
    proj = env.home / "proj"
    proj.mkdir()
    out = _run_on_tty(env, env.app("tool", sb.resolve_template("cli-tool")),
                      "python3 -c 'import fcntl, termios\n"
                      "try:\n fcntl.ioctl(0, termios.TIOCSTI, b\"x\"); print(\"INJECTED\")\n"
                      "except OSError as e: print(\"BLOCKED\", e.errno)'", str(proj))
    assert "BLOCKED" in out and "INJECTED" not in out, out


@pytest.mark.parametrize("template", ["strict", "online-app"])
def test_the_app_outlives_the_process_that_started_it(env, template, tmp_path):
    # Regression (round four, R4-2): the Strict launcher exec'd bwrap with --die-with-parent, which
    # made bwrap's parent the launcher's *caller* -- AppKata's Open, the desktop shell, `gio launch`
    # -- so a Strict app was killed when that process exited (quit AppKata: the app vanished). A
    # Standard launcher ran bwrap as the shell's child and never had the problem. The parent here
    # starts the launcher, waits until the app is running, then exits; the app writes a mark into its
    # private home a few seconds later, which a dead app never does.
    import time
    lp = env.app("life", sb.resolve_template(template))
    mark = os.path.join(sb.sandbox_home("life"), "alive")
    parent = tmp_path / "parent.py"
    parent.write_text("import subprocess, time\n"
                      "subprocess.Popen([%r, 'sleep 5; echo survived > \"$HOME/alive\"'], stdin=subprocess.DEVNULL, "
                      "stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)\ntime.sleep(2)\n" % lp)
    subprocess.run(["python3", str(parent)], env=env.env, cwd=str(env.home), timeout=30)
    time.sleep(5)
    assert os.path.exists(mark), f"{template}: the app died with the process that started it"


def test_no_launcher_file_descriptors_leak_into_the_app(env):
    r = env.run(env.app("fds", sb.resolve_template("strict")), "ls /proc/self/fd | tr '\\n' ' '")
    assert r.stdout.split() == ["0", "1", "2", "3"], r.stdout     # stdio, plus ls's own directory fd


# ---------------------------------------------------------------- lazy AppImage extraction (R17.7)

def _fake_appimage(path, says: str, hostile_link: str = "") -> None:
    """A stand-in AppImage: `--appimage-extract` unpacks an AppRun that prints `says` (or, hostile,
    makes squashfs-root a symlink to `hostile_link`)."""
    extract = (f'ln -s {hostile_link} squashfs-root' if hostile_link else
               f'mkdir -p squashfs-root && printf "#!/bin/sh\\necho {says}\\n" > squashfs-root/AppRun '
               '&& chmod +x squashfs-root/AppRun && sleep 0.5')
    path.write_text(f'#!/bin/sh\n[ "$1" = --appimage-extract ] && {{ {extract}; exit 0; }}\necho not-extracted\n')
    path.chmod(0o755)


def _appimage_app(env, img):
    target = env.home / "apps" / "img"
    return sb.write_launcher("img", "Img", str(env.home / "apps"), sb.extracted_dir(str(target), "1.0"),
                             "AppRun", sb.resolve_template("strict"), str(img))


@pytest.mark.parametrize("desktop,kind", [("Terminal=true", "cli"), ("Terminal=false", "gui"), ("", "gui"), (None, None),
                                          ("hostile", None)])
def test_an_appimages_kind_is_read_by_its_runtime_inside_a_sandbox(env, tmp_path, desktop, kind):
    # Review 2, F4: an AppImage is a command-line tool when the .desktop at its root says
    # Terminal=true; its own runtime reads that out (--appimage-extract '*.desktop'), so it runs in the
    # unpacking's locked-down bwrap: no network, its only writable place a staging folder.
    from appkata_core import appkind
    img = tmp_path / "X.AppImage"
    if desktop == "hostile":
        body = 'ln -s /home squashfs-root'                                       # a link where the folder goes
    elif desktop is None:
        body = 'mkdir -p squashfs-root'                                          # no .desktop at all
    else:
        body = (f'mkdir -p squashfs-root && printf "[Desktop Entry]\\nName=X\\nExec=x\\n{desktop}\\n" > squashfs-root/x.desktop'
                ' && (echo leak > /tmp/../../outside-staging 2>/dev/null; true)')
    img.write_text(f'#!/bin/sh\n[ "$1" = --appimage-extract ] && [ "$2" = "*.desktop" ] && {{ {body}; exit 0; }}\nexit 1\n')
    img.chmod(0o755)
    assert appkind.kind_of_appimage(str(img)) == kind
    assert not os.path.exists("/outside-staging")


def test_a_strict_app_says_on_a_terminal_why_it_cannot_see_its_arguments(env):
    # Review 2, F4: a Strict tool run from a project folder failed on every argument and said nothing.
    import pty
    lp = env.app("tool", sb.resolve_template("strict"))
    master, slave = pty.openpty()
    try:
        r = subprocess.run([lp, "true", "notes.txt"], env=env.env, stdout=subprocess.PIPE, stderr=slave, timeout=30)
        os.close(slave)
        said = b""
        while True:
            try:
                chunk = os.read(master, 4096)
            except OSError:
                break
            if not chunk:
                break
            said += chunk
    finally:
        os.close(master)
    assert r.returncode == 0 and b"runs Strict: it sees only its own private home" in said, said
    piped = subprocess.run([lp, "true", "notes.txt"], env=env.env, capture_output=True, text=True, timeout=30)
    assert "runs Strict" not in piped.stderr                                    # not where no terminal shows it


def test_a_replaced_appimage_is_extracted_again(env):
    # Regression: the extracted copy was keyed only on the version, so an .AppImage replaced in place
    # (a fixed-name, self-updating app, or a reinstall of the same version) kept running the old copy.
    (env.home / "apps" / "img").mkdir(parents=True)
    img = env.home / "apps" / "img" / "Img.AppImage"
    _fake_appimage(img, "first")
    lp = _appimage_app(env, img)
    assert env.run(lp, "").stdout.strip() == "first"
    _fake_appimage(img, "second")
    os.utime(img, (1, 1))                     # a different file, whatever the clock says
    assert env.run(lp, "").stdout.strip() == "second"


def test_simultaneous_first_launches_both_start(env):
    (env.home / "apps" / "img").mkdir(parents=True)
    img = env.home / "apps" / "img" / "Img.AppImage"
    _fake_appimage(img, "ok")
    lp = _appimage_app(env, img)
    ps = [subprocess.Popen([lp], env=env.env, cwd=str(env.home), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           text=True) for _ in range(3)]
    outs = [p.communicate(timeout=60) for p in ps]
    assert all(p.returncode == 0 and o[0].strip() == "ok" for p, o in zip(ps, outs)), outs


def test_an_appimage_cannot_swap_its_extraction_for_a_host_folder(env):
    # A hostile AppImage runtime controls what --appimage-extract leaves behind. If squashfs-root was a
    # symlink, it was moved into place and the launcher bound whatever it pointed at.
    (env.home / "apps" / "img").mkdir(parents=True)
    img = env.home / "apps" / "img" / "Img.AppImage"
    _fake_appimage(img, "", hostile_link=str(env.home))
    lp = _appimage_app(env, img)
    r = env.run(lp, "")
    appdir = sb.extracted_dir(str(env.home / "apps" / "img"), "1.0")
    assert r.returncode != 0 and not os.path.islink(appdir), (r.stdout, r.stderr)


# ---------------------------------------------------------------- the document portal (R17.6)

_DOC_PORTAL = ("/usr/libexec/xdg-document-portal", "/usr/lib/xdg-desktop-portal/xdg-document-portal")

# Export a file to an app through the Documents portal, as the FileChooser portal does for a sandboxed
# caller: prints the document id. argv: <file> <app id>
_EXPORT = """
import os, sys
from gi.repository import Gio, GLib
bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
fdl = Gio.UnixFDList.new(); i = fdl.append(os.open(sys.argv[1], os.O_RDONLY))
res, _ = bus.call_with_unix_fd_list_sync("org.freedesktop.portal.Documents", "/org/freedesktop/portal/documents",
    "org.freedesktop.portal.Documents", "Add", GLib.Variant("(hbb)", (i, False, False)), GLib.VariantType("(s)"),
    Gio.DBusCallFlags.NONE, 5000, fdl, None)
doc = res.unpack()[0]
bus.call_sync("org.freedesktop.portal.Documents", "/org/freedesktop/portal/documents", "org.freedesktop.portal.Documents",
    "GrantPermissions", GLib.Variant("(ssas)", (doc, sys.argv[2], ["read"])), None, Gio.DBusCallFlags.NONE, 5000, None)
print(doc)
"""


class _DocPortal:
    """xdg-document-portal on the test bus, with its FUSE mount at $XDG_RUNTIME_DIR/doc."""

    def __init__(self, env, bus):
        exe = next((p for p in _DOC_PORTAL if os.path.exists(p)), None)
        has_gi = subprocess.run(["python3", "-c", "import gi"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
        if not exe or not has_gi or not os.path.exists("/dev/fuse"):
            pytest.skip("needs xdg-document-portal, python3-gi and /dev/fuse (scripts/test-sandbox.sh launcher)")
        self.env = {**env.env, "DBUS_SESSION_BUS_ADDRESS": bus.addr}
        self.p = subprocess.Popen([exe], env=self.env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(50):
            if os.path.isdir(env.rt / "doc" / "by-app"):
                return
            subprocess.run(["sleep", "0.1"])
        self.close()
        pytest.skip("xdg-document-portal didn't mount $XDG_RUNTIME_DIR/doc here (no FUSE in this container?)")

    def export(self, path: str, app_identity: str) -> str:
        r = subprocess.run(["python3", "-c", _EXPORT, path, app_identity], env=self.env, capture_output=True, text=True, timeout=30)
        assert r.returncode == 0, r.stderr
        return r.stdout.strip()

    def close(self):
        self.p.terminate()
        self.p.wait(timeout=10)


@needs_proxy
def test_a_file_handed_over_by_the_document_portal_is_readable_and_only_by_that_app(env):
    # Regression: the launcher never bound the document portal's FUSE export, so the path the portal
    # file chooser returns for a sandboxed caller ($XDG_RUNTIME_DIR/doc/<id>/<name>) didn't exist in
    # the sandbox; with folder grants all default Off a Standard app couldn't open any user file.
    bus = _Bus(env)
    try:
        portal = _DocPortal(env, bus)
        try:
            docs = env.home / "Documents"
            docs.mkdir()
            (docs / "picked.txt").write_text("PICKED\n")
            (docs / "theirs.txt").write_text("THEIRS\n")
            mine = portal.export(str(docs / "picked.txt"), sb.app_identity("web"))
            theirs = portal.export(str(docs / "theirs.txt"), sb.app_identity("other"))
            r = env.run(env.app("web", sb.resolve_template("online-app")),
                        f'cat "$XDG_RUNTIME_DIR/doc/{mine}/picked.txt"; cat "$XDG_RUNTIME_DIR/doc/{theirs}/theirs.txt" 2>&1; '
                        f'cat "$HOME/Documents/picked.txt" 2>&1; true', env={"DBUS_SESSION_BUS_ADDRESS": bus.addr})
        finally:
            portal.close()
    finally:
        bus.close()
    assert "PICKED" in r.stdout, (r.stdout, r.stderr)           # the picked file, at the path the chooser gives
    assert "THEIRS" not in r.stdout                               # another app's hand-over isn't visible
    assert r.stdout.count("PICKED") == 1                          # and ~/Documents itself still isn't


@needs_proxy
def test_an_app_whose_name_starts_with_a_digit_still_gets_the_bus(env):
    # Regression: the proxy was told --own=io.appkata.7zip, which xdg-dbus-proxy rejects ("not a valid
    # dbus name") and exits, so the app's bus socket never appeared and bwrap refused to start it.
    bus = _Bus(env)
    try:
        r = env.run(env.app("7zip", sb.resolve_template("online-app")),
                    '[ -S "$XDG_RUNTIME_DIR/bus" ] && echo BUS; grep name= /.flatpak-info',
                    env={"DBUS_SESSION_BUS_ADDRESS": bus.addr})
    finally:
        bus.close()
    assert r.returncode == 0 and "BUS" in r.stdout and "name=io.appkata._7zip" in r.stdout, (r.stdout, r.stderr)


# ---------------------------------------------------------------- the portals see a host caller (R17.6.1, finding 0)

_DESKTOP_PORTAL = ("/usr/libexec/xdg-desktop-portal", "/usr/lib/xdg-desktop-portal/xdg-desktop-portal")
_CALL = ("gdbus call --session --dest org.freedesktop.portal.Desktop --object-path /org/freedesktop/portal/desktop "
         "--method org.freedesktop.portal.{} 2>&1")


class _DesktopPortal:
    """xdg-desktop-portal itself on the test bus: no backends here, so only the portals that need
    none answer (NetworkMonitor, ProxyResolver...), which is enough to see whether it takes the
    caller for a host app or refuses it as an impostor Flatpak."""

    def __init__(self, env, bus):
        exe = next((p for p in _DESKTOP_PORTAL if os.path.exists(p)), None)
        if not exe:
            pytest.skip("needs xdg-desktop-portal (scripts/test-sandbox.sh launcher)")
        self.env = {**env.env, "DBUS_SESSION_BUS_ADDRESS": bus.addr}
        self.p = subprocess.Popen([exe], env=self.env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(100):
            r = subprocess.run(["sh", "-c", _CALL.format("NetworkMonitor.GetAvailable")], env=self.env,
                               capture_output=True, text=True)
            if r.stdout.startswith("("):
                return
            subprocess.run(["sleep", "0.1"])
        self.close()
        pytest.skip("xdg-desktop-portal didn't come up on the test bus")

    def close(self):
        self.p.terminate()
        self.p.wait(timeout=10)


@needs_proxy
def test_the_portals_answer_a_sandboxed_app_as_a_host_caller(env):
    # Regression (review finding 0): the proxy's bwrap carried /.flatpak-info, and xdg-desktop-portal
    # 1.18+ refused every call from it -- "Portal operation not allowed: Failed to open file
    # .../.flatpak/<id>/bwrapinfo.json" -- because the marker named no running Flatpak. Now the proxy
    # has no marker and the app is a host caller; the proxy itself denies the portals that would
    # trust one with the host (file chooser, autostart...), and the Documents name is not visible.
    # Round three, R3-6: the Notification and Inhibit portals come with their capabilities -- an
    # online-app (notifications, no inhibit) reaches the first and is refused the second by the proxy.
    calls = (_CALL.format("NetworkMonitor.GetAvailable") + "; " +
             _CALL.format('FileChooser.OpenFile "" Pick "{}"') + "; " +
             _CALL.format('Background.RequestBackground "" "{}"') + "; " +
             "gdbus call --session --dest org.freedesktop.portal.Documents --object-path /org/freedesktop/portal/documents "
             "--method org.freedesktop.portal.Documents.GetMountPoint 2>&1; " +
             _CALL.format('Notification.AddNotification n "{}"') + "; " +
             _CALL.format('Inhibit.Inhibit "" 8 "{}"') + "; " +
             # Round three, R3-4: the FileChooser `version` property is what Chromium/Electron reads
             # (it sees /.flatpak-info in the app's root) before switching to the portal file
             # chooser, which for a host caller returns paths the sandbox can't open; denied, it
             # never tries. GTK4 is held by the FileChooser denial above instead, and GTK3 and Qt
             # up to 6.4 never ask (round four, R4-5, shown with real apps: test-sandbox.sh filedialogs).
             "gdbus call --session --dest org.freedesktop.portal.Desktop --object-path /org/freedesktop/portal/desktop "
             "--method org.freedesktop.DBus.Properties.Get org.freedesktop.portal.FileChooser version 2>&1; " +
             # Round six, R6-2: the Camera portal is denied whatever the camera grant says -- R17.8 and the
             # hint used to promise "the camera portal, which asks you first"; nothing asks
             _CALL.format('Camera.AccessCamera "{}"') + "; " + _CALL.format("Camera.IsCameraPresent") + "; " +
             # CR1.5-28: what the host says of its network -- whether it is up, and the proxy a URL
             # goes through, with the proxy's credentials where the desktop's setting has them --
             # comes with the network grant, as the proxy variables do (R17.4)
             _CALL.format('ProxyResolver.Lookup "http://example.org/"') + "; true")
    bus = _Bus(env)
    try:
        portal = _DesktopPortal(env, bus)
        try:
            r = env.run(env.app("web", sb.resolve_template("online-app")), calls, env={"DBUS_SESSION_BUS_ADDRESS": bus.addr})
            r2 = env.run(env.app("ed", sb.resolve_template("offline-editor")), calls, env={"DBUS_SESSION_BUS_ADDRESS": bus.addr})
            r3 = env.run(env.app("cam", sb.resolve_template("messenger")), calls, env={"DBUS_SESSION_BUS_ADDRESS": bus.addr})
        finally:
            portal.close()
    finally:
        bus.close()
    lines = r.stdout.strip().splitlines()
    assert len(lines) == 10 and "Portal operation not allowed" not in r.stdout, (r.stdout, r.stderr)
    assert lines[7].endswith("AccessDenied") and lines[8].endswith("AccessDenied"), lines[7:]   # no camera portal
    assert lines[0] == "(true,)"                                           # answered, as a host app
    assert lines[9].startswith("(['"), lines[9]                            # ...and the proxies for a URL: this app has the network
    assert lines[1].endswith("AccessDenied") and lines[2].endswith("AccessDenied")   # the proxy, not the portal
    assert "ServiceUnknown" in lines[3]
    assert "AccessDenied" not in lines[4], lines[4]                        # the Notification portal answered
    assert lines[5].endswith("AccessDenied"), lines[5]                     # Inhibit: not this app's capability
    assert lines[6].endswith("AccessDenied"), lines[6]                     # no version probe, so no portal chooser
    lines = r2.stdout.strip().splitlines()                                 # an offline-editor: no network grant
    assert len(lines) == 10 and lines[0].endswith("AccessDenied") and lines[9].endswith("AccessDenied"), (r2.stdout, r2.stderr)
    assert lines[7].endswith("AccessDenied") and lines[8].endswith("AccessDenied")
    assert lines[4].endswith("AccessDenied") and lines[5].endswith("AccessDenied")   # no capability, no portal
    assert lines[6].endswith("AccessDenied")
    lines = r3.stdout.strip().splitlines()
    assert len(lines) == 10 and lines[7].endswith("AccessDenied") and lines[8].endswith("AccessDenied")   # the grant binds devices, opens no portal
    assert lines[0] == "(true,)" and lines[9].startswith("(['"), lines     # a messenger has the network



# A GLib program, as far as the network goes: its network monitor and its proxy resolver, which a
# GLib app that sees /.flatpak-info takes from the portal (gnetworkmonitorportal.c,
# gproxyresolverportal.c), and a connection to a server of its own on the loopback.
_GLIB_NETWORK = """
import socket, sys, threading, time
from gi.repository import Gio, GLib
server = socket.socket()
server.bind(("127.0.0.1", 0))
server.listen(1)
threading.Thread(target=lambda: server.accept()[0].send(b"hello"), daemon=True).start()
monitor, context, end = Gio.NetworkMonitor.get_default(), GLib.MainContext.default(), time.time() + float(sys.argv[1])
while time.time() < end and not monitor.get_network_available():      # the portal's answer comes on the main loop
    context.iteration(False)
    time.sleep(0.01)
print("MONITOR", type(monitor).__name__, monitor.get_network_available())
print("RESOLVER", type(Gio.ProxyResolver.get_default()).__name__, Gio.ProxyResolver.get_default().lookup("http://example.org/", None))
try:
    connection = Gio.SocketClient().connect_to_host("127.0.0.1", server.getsockname()[1], None)
    print("LOOPBACK", connection.get_input_stream().read_bytes(5, None).get_data().decode())
except GLib.Error as e:
    print("LOOPBACK failed:", e.message)
"""


@needs_proxy
@pytest.mark.parametrize("network", [True, False])
def test_a_glib_app_asks_the_portal_about_the_network_only_with_the_grant_and_works_either_way(env, network):
    # CR1.5-28: NetworkMonitor and ProxyResolver come with the network grant. GLib asks the
    # ProxyResolver portal before every connection it makes, and with the portal refused and
    # nothing else done, an app without the grant could no longer connect to a server of its own
    # on the loopback (GLib 2.80 and 2.84: "LOOPBACK failed: …AccessDenied"), where it had been
    # answered direct://, which is all GLib gives a sandbox without the network whatever the
    # portal says. So such an app gets GIO_USE_PROXY_RESOLVER=dummy: GLib's own resolver, which
    # says the same and asks nobody. Nothing reaches stderr either way.
    app_id = "online" if network else "offline"
    d = env.home / "apps" / app_id / "1.0" / "bin"
    d.mkdir(parents=True)
    (d / "network.py").write_text(_GLIB_NETWORK)
    bus = _Bus(env)
    try:
        portal = _DesktopPortal(env, bus)
        try:
            r = env.run(env.app(app_id, sb.apply_overrides(sb.resolve_template("offline-editor"), {"network": network})),
                        f'python3 "$(dirname "$0")/network.py" {10 if network else 1}; echo "ASKS ${{GIO_USE_PROXY_RESOLVER:-the portal}}"',
                        env={"DBUS_SESSION_BUS_ADDRESS": bus.addr}, timeout=60)
        finally:
            portal.close()
    finally:
        bus.close()
    assert r.returncode == 0 and r.stderr == "", (r.stdout, r.stderr)
    want = (["MONITOR GNetworkMonitorPortal True", "RESOLVER GProxyResolverPortal ['direct://']", "LOOPBACK hello", "ASKS the portal"] if network else
            ["MONITOR GNetworkMonitorPortal False", "RESOLVER GDummyProxyResolver ['direct://']", "LOOPBACK hello", "ASKS dummy"])
    assert r.stdout.splitlines() == want, r.stdout


# ---------------------------------------------------------------- the session's bus, wherever it listens (R17.5, CR1.5-18)

@needs_proxy
@pytest.mark.parametrize("session", ["no-address", "dbus-run-session", "guid-first", "an-escaped-key"])
def test_standard_apps_reach_the_session_bus_wherever_it_listens(env, session):
    # CR1.5-18: the proxy's own bwrap bound /usr, /etc and the runtime folder, so the proxy reached
    # a bus only there. A `dbus-run-session` bus is a socket under /tmp since dbus 1.14: the proxy
    # made its own socket, the launcher's wait passed, and every connection the app made failed with
    # nothing said -- a Standard app there had no portals, no notifications, no "open on the host".
    # And with no address set the proxy was given "", not the runtime folder's bus, which is where
    # libdbus and GLib look. Every bus of these tests was at $XDG_RUNTIME_DIR/bus with its address
    # set, so nothing met either. Here: a login session's bus that no variable names, and a real
    # dbus-run-session, whose address also carries the `,guid=…` every such address does; and that
    # address with `guid=` first, which libdbus and GIO read as well, and where the launcher started
    # no proxy, since it took the path or the abstract name as the first key alone (PR #694's
    # review, P4-B1a; at the merge base the proxy was given the address whole). And that address with
    # its key's name escaped, which GIO, the proxy's, reads unescaped, and the launcher read as
    # written, so it started no proxy, and showed a granted folder the socket (P6-1).
    session_bus = _Bus(env) if session == "no-address" else _RunSession(env)
    transport, _, keys = session_bus.addr.partition(":")
    addr = transport + ":" + ",".join(sorted(keys.split(","), key=lambda k: not k.startswith("guid="))) if session == "guid-first" else session_bus.addr
    if session == "an-escaped-key":
        addr = addr.replace("unix:path=", "unix:pa%74h=", 1).replace("unix:abstract=", "unix:abstr%61ct=", 1)
    said = {} if session == "no-address" else {"DBUS_SESSION_BUS_ADDRESS": addr}
    calls = (_OWN.format("io.appkata.web") + "; " + _CALL.format("NetworkMonitor.GetAvailable") + "; " +
             _CALL.format('FileChooser.OpenFile "" Pick "{}"') + "; true")
    try:
        assert session_bus.addr.startswith(("unix:path=", "unix:abstract=")), session_bus.addr
        if session != "no-address":             # neither in the runtime folder nor named plainly
            assert str(env.rt) not in addr and "guid=" in addr, addr
            assert addr.startswith("unix:guid=") is (session == "guid-first"), addr
            assert ("%" in addr) is (session == "an-escaped-key"), addr
        portal = _DesktopPortal(env, session_bus)
        try:
            r = env.run(env.app("web", sb.resolve_template("online-app")), calls, env=said)
        finally:
            portal.close()
    finally:
        session_bus.close()
    lines = r.stdout.strip().splitlines()
    assert r.returncode == 0 and len(lines) == 3, (session_bus.addr, r.stdout, r.stderr)
    assert lines[0] == "(uint32 1,)", lines                 # its own name is its own: single instance works
    assert lines[1] == "(true,)", lines                     # the portal answers through the proxy
    assert lines[2].endswith("AccessDenied"), lines         # and it is the filtered bus the app is on
    assert "Failed to connect to bus" not in r.stderr and "not one the bus filter can reach" not in r.stderr, r.stderr


@needs_proxy
def test_a_session_bus_socket_is_out_of_reach_of_a_tool_run_beside_it_and_of_a_grant_of_its_folder(env, monkeypatch):
    # The review of PR #694, P1-2: the never-shared rules kept the real bus from the app by refusing
    # the runtime folder, and a dbus-run-session or dbus-launch bus is a socket file under /tmp: a
    # command-line tool run in its folder shared it, and so did a grant of that folder, and the app
    # connected to it past the filter. Now the tool runs in its private home and says why, and the
    # grant -- made in a session whose bus was the runtime folder's, so nothing refused it -- has the
    # socket covered. The bus's folder is one of the user's own here: /tmp itself is no tool's and no
    # grant's (CR1.5-5, CR1.5-6), and a bus can be put anywhere (`dbus-daemon --address`).
    # And a grant of the socket file itself, or of a link to it, which the cover matched no part of
    # (PR #694's review, P5-B1): the app saw the live socket and reached the bus through it. And an
    # address with its key's name escaped, `pa%74h=`, which is GIO's `path=` and which the launcher
    # read as written, so it covered nothing and shared the tool's folder (P6-1).
    folder = env.home / "shared"
    folder.mkdir()
    bus = _Bus(env, at=folder / "dbus-MZ8lHbtZ8K")
    sock = str(folder / "dbus-MZ8lHbtZ8K")
    link = env.home / "bus-link"
    link.symlink_to(sock)
    probe = lambda at, said="": (f'[ -S {at} ] && echo SEEN{said}; gdbus call --address unix:path={at} --dest org.freedesktop.DBus '   # noqa: E731
                                 f'--object-path /org/freedesktop/DBus --method org.freedesktop.DBus.GetId >/dev/null 2>&1 && echo REACHED{said}; ')
    try:
        r = env.run(env.app("tool", sb.resolve_template("cli-tool")), probe(sock) + "echo DONE", cwd=str(folder), env={"DBUS_SESSION_BUS_ADDRESS": bus.addr})
        monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", f"unix:path={env.rt}/bus")
        viewer = env.app("viewer", sb.apply_overrides(sb.resolve_template("standard"), {"folders": {f"+{folder}": "ro"}}))
        assert "Refused folder grant" not in open(viewer).read()
        r2 = env.run(viewer, probe(sock) + f"echo DONE; ls {folder} >/dev/null && echo LISTED", env={"DBUS_SESSION_BUS_ADDRESS": bus.addr})
        files = env.app("files", sb.apply_overrides(sb.resolve_template("standard"), {"folders": {f"+{sock}": "rw", f"+{link}": "ro"}}))
        assert "Refused folder grant" not in open(files).read()
        r3 = env.run(files, probe(sock) + probe(link, "-LINK") + "echo DONE", env={"DBUS_SESSION_BUS_ADDRESS": bus.addr})
        escaped = {"DBUS_SESSION_BUS_ADDRESS": bus.addr.replace("unix:path=", "unix:pa%74h=", 1)}
        r4 = env.run(env.app("tool", sb.resolve_template("cli-tool")), probe(sock) + "echo DONE", cwd=str(folder), env=escaped)
        r5 = env.run(viewer, probe(sock) + f"echo DONE; ls {folder} >/dev/null && echo LISTED", env=escaped)
    finally:
        bus.close()
    assert r.returncode == 0 and r.stdout.split() == ["DONE"], (r.stdout, r.stderr)
    assert f"can't see {folder}" in r.stderr and "one that holds the session bus" in r.stderr, r.stderr
    assert r2.returncode == 0 and r2.stdout.split() == ["DONE", "LISTED"], (r2.stdout, r2.stderr)      # the folder is the app's, but not the bus
    assert r3.returncode == 0 and r3.stdout.split() == ["DONE"], (r3.stdout, r3.stderr)
    assert "%74" in escaped["DBUS_SESSION_BUS_ADDRESS"], escaped
    assert r4.returncode == 0 and r4.stdout.split() == ["DONE"] and f"can't see {folder}" in r4.stderr, (r4.stdout, r4.stderr)
    assert r5.returncode == 0 and r5.stdout.split() == ["DONE", "LISTED"], (r5.stdout, r5.stderr)


@needs_proxy
@pytest.mark.parametrize("address", ["tcp:host=127.0.0.1,port=1", "unix:path={rt}/bus;unix:path=/tmp/dbus-elsewhere", "unix:path={rt}/a%20bus",
                                     "unix:path={rt}/bus,", "unix:path={rt}/bus,g%zz=1"],
                         ids=["another-transport", "a-list", "an-escaped-path", "a-key-with-no-equals", "a-key-gdbus-cannot-unescape"])
def test_a_session_bus_the_filter_cannot_be_shown_is_said_and_the_app_runs_without_one(env, address):
    # CR1.5-18's other half: an address that names no one socket the launcher can show the proxy
    # (another transport, a list, an escaped path) still got a proxy, and the app a bus socket on
    # which every connection failed, with nothing said. Said now, on stderr, and the app runs as
    # it does where there is no bus: no proxy is started and nothing is left behind. And a trailing
    # comma, an empty key, for which the proxy's GDBus refuses the address (PR #694's review, P5-1),
    # and a key's name with an escape it can't unescape, which it refuses as well (P6-2).
    address = address.format(rt=env.rt)
    lp = env.app("web", sb.resolve_template("online-app"))
    r = env.run(lp, '[ -e "$XDG_RUNTIME_DIR/bus" ] && echo BUS; echo "A=$DBUS_SESSION_BUS_ADDRESS"; echo RAN; xdg-open https://example.com/x; echo "exit $?"',
                env={"DBUS_SESSION_BUS_ADDRESS": address})
    assert r.returncode == 0 and r.stdout.split() == [f"A=unix:path={env.rt}/bus", "RAN", "exit", "3"], (r.stdout, r.stderr)
    # and the app's xdg-open says why it can't open a link, not that the app runs Strict (PR #694's review, P1-B3)
    assert r.stderr == (f"AppKata: the session bus here ({address}) is not one the bus filter can reach, "
                        "so Web runs without a session bus and gets no desktop services.\n"
                        "AppKata: this session's bus is at an address AppKata's bus filter can't reach (the launcher named it when "
                        "the app started), so this app has no desktop services and can't open https://example.com/x on this computer.\n")
    assert os.listdir(env.rt / "appkata") == []


# ---------------------------------------------------------------- the proxy's own sandbox (R17.17, CR1.5-24)

# bwrap with a look inside the proxy's own sandbox: the launcher's words unchanged but for the
# program, which first says what it can see and which namespaces it is in, and then becomes the proxy.
_LOOK = r"""import os, sys
real, argv = sys.argv[1], sys.argv[2:]
if "xdg-dbus-proxy" in argv:
    look = ('{ find / -mindepth 1 \\( -path /usr -o -path /etc -o -path /proc -o -path /dev \\) -prune -o -exec stat -c "PROXY-SEES %A %n" {} +; '
            'for ns in net ipc uts pid; do echo "PROXY-NS $ns $(readlink /proc/self/ns/$ns)"; done; '
            'echo "PROXY-SECCOMP $(sed -n "s/^Seccomp:[[:space:]]*//p" /proc/self/status)"; '
            'echo "PROXY-ENV $(tr "\\0" "\\n" < /proc/$$/environ | cut -d= -f1 | sort | paste -sd, -)"; } >&2; exec "$@"')
    at = argv.index("xdg-dbus-proxy")
    argv[at:at] = ["sh", "-c", look, "sh"]
os.execv(real, [real] + argv)
"""


@needs_proxy
@pytest.mark.parametrize("bus_on", ["a-socket-file", "an-abstract-socket"])
def test_the_proxy_runs_in_a_sandbox_that_holds_its_socket_folder_and_the_bus_alone(env, tmp_path, bus_on):
    # CR1.5-24: the proxy parses every message a hostile app sends, and its bwrap gave it the whole
    # runtime folder read-write -- the ssh and gpg agents' sockets, the document portal's mount, the
    # sound and display sockets -- with the host's network and IPC and no seccomp filter: a fault in
    # it would hand the app all the app's own sandbox withholds. Nothing looked inside that
    # sandbox; this does, from the proxy's own place in it. What is left is the bus (R17.17).
    fake = tmp_path / "lookbin"
    fake.mkdir()
    (fake / "look.py").write_text(_LOOK)
    (fake / "bwrap").write_text(f'#!/bin/sh\nexec python3 {shlex.quote(str(fake / "look.py"))} {shlex.quote(shutil.which("bwrap"))} "$@"\n')
    (fake / "bwrap").chmod(0o755)
    for name in ("keyring/ssh", "gnupg/S.gpg-agent", "doc/by-app/io.appkata.web/a-document", "pipewire-0", "wayland-0"):
        (env.rt / name).parent.mkdir(parents=True, exist_ok=True)       # what a session keeps there beside its bus
        (env.rt / name).write_text("")
    bus = _Bus(env, abstract=bus_on == "an-abstract-socket")
    try:
        r = env.run(env.app("web", sb.resolve_template("online-app")), _OWN.format("io.appkata.web"),
                    env={"DBUS_SESSION_BUS_ADDRESS": bus.addr, "PATH": f"{fake}:{os.environ['PATH']}"})
    finally:
        bus.close()
    assert r.returncode == 0 and r.stdout.strip() == "(uint32 1,)", (r.stdout, r.stderr)   # and from in there it still does its work
    said = [l.split(" ", 2) for l in r.stderr.splitlines() if l.startswith("PROXY-")]
    sees = {(mode[0], path) for tag, mode, path in (l for l in said if l[0] == "PROXY-SEES")}     # d, l or s, as `ls -l` has it
    folders = {path for kind, path in sees if kind == "d"}
    assert folders and all(f"{env.rt}/appkata".startswith(f) for f in folders), sorted(folders)   # its socket folder, and the way to it
    want = {("l", "/lib"), ("l", "/lib64"), ("l", "/bin")}
    if bus_on == "a-socket-file":
        want.add(("s", f"{env.rt}/bus"))
    assert sees - {("d", f) for f in folders} == want, r.stderr
    inside = {kind: link for tag, kind, link in (l for l in said if l[0] == "PROXY-NS")}
    mine = {ns: os.readlink(f"/proc/self/ns/{ns}") for ns in ("net", "ipc", "uts", "pid")}
    assert set(inside) == set(mine) and not [ns for ns in ("ipc", "uts", "pid") if inside[ns] == mine[ns]], (inside, mine)
    # the host's network only where the bus is in it: an abstract socket has no file to bind (R17.9)
    assert (inside["net"] == mine["net"]) is (bus_on == "an-abstract-socket"), (inside, mine)
    if sb.seccomp_filter() is not None:
        assert ["PROXY-SECCOMP", "2"] in said, r.stderr                 # a filter is on: the terminal-injection one (R17.4)
    # and none of the launcher's environment (PR #694's review, P1-B2): the run's own here, its
    # home and its runtime folder among them, as a terminal's tokens would be. PATH is the
    # launcher's word, PWD bwrap's own: the folder it starts the proxy in.
    assert ["PROXY-ENV", "PATH,PWD"] in said, r.stderr


# A stand-in for the OpenURI portal on the test bus: records what it is asked to open. For a file it
# records the host path the descriptor points to, which is what the real portal opens.
_FAKE_OPENURI = """
import os, sys
from gi.repository import Gio, GLib
XML = '''<node><interface name="org.freedesktop.portal.OpenURI">
<method name="OpenURI"><arg type="s" direction="in"/><arg type="s" direction="in"/><arg type="a{sv}" direction="in"/><arg type="o" direction="out"/></method>
<method name="OpenFile"><arg type="s" direction="in"/><arg type="h" direction="in"/><arg type="a{sv}" direction="in"/><arg type="o" direction="out"/></method>
</interface></node>'''
log = open(sys.argv[1], "a")
def call(conn, sender, path, iface, method, params, inv):
    if method == "OpenURI":
        log.write(f"OpenURI {params[1]}\\n")
    else:
        fd = inv.get_message().get_unix_fd_list().get(params[1])
        path = os.readlink(f'/proc/self/fd/{fd}')
        log.write(f"OpenFile {path} {open(fd).read().strip()}\\n")
    log.flush()
    # answer like the portal: the request object, then its Response signal to the caller (GLib and
    # the shim wait for it); a file the host "can't open" gets the portal's failure code, 2
    code = 2 if method == "OpenFile" and "refuse" in path else 0
    token = params.unpack()[2].get("handle_token", "t")
    req = f"/org/freedesktop/portal/desktop/request/{sender[1:].replace('.', '_')}/{token}"
    inv.return_value(GLib.Variant("(o)", (req,)))
    conn.emit_signal(sender, req, "org.freedesktop.portal.Request", "Response", GLib.Variant("(ua{sv})", (code, {})))
bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
bus.register_object("/org/freedesktop/portal/desktop", Gio.DBusNodeInfo.new_for_xml(XML).interfaces[0], call, None, None)
Gio.bus_own_name_on_connection(bus, "org.freedesktop.portal.Desktop", Gio.BusNameOwnerFlags.NONE, None, None)
GLib.MainLoop().run()
"""


@needs_proxy
def test_links_and_files_an_app_opens_go_to_the_host_through_the_portal(env, tmp_path):
    # The app's PATH starts with AppKata's xdg-open, which asks the OpenURI portal (R17.6.3): a URL as
    # it is, a file as a descriptor the portal resolves to its host path. GLib-based programs (`gio
    # open`) take the same road on their own, from /.flatpak-info -- when they find no handler of
    # their own first, which the next test is about. The file is in a granted folder:
    # a file in the private home reaches the portal with the path it has *inside* the sandbox
    # ($HOME/x, where the host has no such file, or another one), so the real portal refuses it.
    if subprocess.run(["python3", "-c", "import gi"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode:
        pytest.skip("needs python3-gi")
    (env.home / "Documents").mkdir()
    gs = sb.apply_overrides(sb.resolve_template("online-app"), {"folders": {"+~/Documents": "rw"}})
    bus = _Bus(env)
    log = tmp_path / "opened.log"
    fake = subprocess.Popen(["python3", "-c", _FAKE_OPENURI, str(log)], env={**env.env, "DBUS_SESSION_BUS_ADDRESS": bus.addr},
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(50):
            r = subprocess.run(["sh", "-c", "gdbus call --session --dest org.freedesktop.DBus --object-path /org/freedesktop/DBus "
                                "--method org.freedesktop.DBus.NameHasOwner org.freedesktop.portal.Desktop"],
                               env={**env.env, "DBUS_SESSION_BUS_ADDRESS": bus.addr}, capture_output=True, text=True)
            if r.stdout.strip() == "(true,)":
                break
            subprocess.run(["sleep", "0.1"])
        r = env.run(env.app("web", gs),
                    'command -v xdg-open; xdg-open https://example.com/page && echo URL-OK; '
                    'echo "hello from the sandbox" > "$HOME/Documents/note.txt"; xdg-open "$HOME/Documents/note.txt" && echo FILE-OK; '
                    # round five, R5-6: the shim waits for the Request's Response and says when the host could not open the file
                    'echo x > "$HOME/Documents/refuse-me.txt"; xdg-open "$HOME/Documents/refuse-me.txt"; echo "REFUSED $?"; '
                    'if command -v gio >/dev/null; then timeout 10 gio open mailto:someone@example.com && echo GIO-OK; fi; true',
                    env={"DBUS_SESSION_BUS_ADDRESS": bus.addr})
        # CR1.5-29: the road is there whatever the network grant says. An offline-editor has no
        # network (its namespace holds the loopback alone), and what it knows leaves all the same,
        # in a link the desktop is asked to open, which the user's browser then fetches for it.
        # The design keeps the road (R17.6.3); R17.17 and the dialog's Network hint say so.
        offline = env.run(env.app("ed", sb.resolve_template("offline-editor")),
                          'echo NET $(cut -s -d: -f1 /proc/net/dev); echo k3y-from-the-sandbox > "$HOME/key"; '
                          'xdg-open "https://example.com/?d=$(cat "$HOME/key")" && echo URL-OK',
                          env={"DBUS_SESSION_BUS_ADDRESS": bus.addr})
    finally:
        fake.terminate()
        bus.close()
    assert r.stdout.startswith("/run/appkata/xdg-open\n") and "URL-OK" in r.stdout and "FILE-OK" in r.stdout, (r.stdout, r.stderr)
    opened = log.read_text().splitlines()
    assert "OpenURI https://example.com/page" in opened
    assert f"OpenFile {env.home}/Documents/note.txt hello from the sandbox" in opened          # the host path
    assert "REFUSED 1" in r.stdout and "the host couldn't open" in r.stderr and "refuse-me.txt" in r.stderr, r.stderr
    if "GIO-OK" in r.stdout:
        assert "OpenURI mailto:someone@example.com" in opened
    assert offline.stdout.splitlines() == ["NET lo", "URL-OK"], (offline.stdout, offline.stderr)     # no network, and the link went
    assert "OpenURI https://example.com/?d=k3y-from-the-sandbox" in opened, opened


_TEST_HANDLER = "/usr/share/applications/appkata-test-handler.desktop"      # scripts/sandbox/register-test-handler.sh


@needs_proxy
def test_a_glib_program_opens_links_on_the_host_even_when_the_host_has_a_handler(env, tmp_path):
    # Regression (round three, R3-1): GLib opens a link or file with the default handler it finds and
    # asks the OpenURI portal only when it finds none. The host's /usr is in view, so on a desktop
    # (firefox.desktop, xed.desktop in /usr/share/applications) a GLib or GTK app started the host's
    # browser or editor *inside* the sandbox -- a second Firefox on the private home -- and the
    # portal saw nothing; the test above passed only because the test host registered no handler.
    # The launcher now hides the host's desktop entries under an empty tmpfs, as a Flatpak runtime
    # has none (R17.4). The harness registers a handler as root before the tests, so the host side of
    # this test is a real desktop's.
    if not os.path.exists(_TEST_HANDLER) or not shutil.which("gio"):
        pytest.skip("needs the test handler registered as root (scripts/sandbox/register-test-handler.sh) and gio")
    if subprocess.run(["python3", "-c", "import gi"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode:
        pytest.skip("needs python3-gi")
    on_host = subprocess.run(["gio", "mime", "x-scheme-handler/https"], env=env.env, capture_output=True, text=True).stdout
    assert "appkata-test-handler.desktop" in on_host, on_host          # the host would open links with it
    (env.home / "Documents").mkdir()
    (env.home / "Documents" / "note.txt").write_text("from the host\n")
    gs = sb.apply_overrides(sb.resolve_template("online-app"), {"folders": {"+~/Documents": "rw"}})
    bus = _Bus(env)
    log = tmp_path / "opened.log"
    fake = subprocess.Popen(["python3", "-c", _FAKE_OPENURI, str(log)], env={**env.env, "DBUS_SESSION_BUS_ADDRESS": bus.addr},
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(50):
            r = subprocess.run(["sh", "-c", "gdbus call --session --dest org.freedesktop.DBus --object-path /org/freedesktop/DBus "
                                "--method org.freedesktop.DBus.NameHasOwner org.freedesktop.portal.Desktop"],
                               env={**env.env, "DBUS_SESSION_BUS_ADDRESS": bus.addr}, capture_output=True, text=True)
            if r.stdout.strip() == "(true,)":
                break
            subprocess.run(["sleep", "0.1"])
        r = env.run(env.app("web", gs),
                    'ls -A /usr/share/applications | wc -l; gio mime x-scheme-handler/https 2>&1 | head -1; '
                    'timeout 10 gio open https://example.com/x && echo URL-OK; '
                    'timeout 10 gio open "$HOME/Documents/note.txt" && echo FILE-OK; true',
                    env={"DBUS_SESSION_BUS_ADDRESS": bus.addr})
    finally:
        fake.terminate()
        bus.close()
    lines = r.stdout.splitlines()
    assert lines[0] == "0" and "No default applications" in lines[1], (r.stdout, r.stderr)   # nothing to find inside
    assert "URL-OK" in r.stdout and "FILE-OK" in r.stdout, (r.stdout, r.stderr)
    opened = log.read_text().splitlines() if log.exists() else []
    assert "OpenURI https://example.com/x" in opened, opened                               # the host's road
    assert f"OpenFile {env.home}/Documents/note.txt from the host" in opened, opened
    assert not os.path.exists(os.path.join(sb.sandbox_home("web"), "appkata-test-handler-ran"))   # never inside


# ---------------------------------------------------------------- mount destinations in the private home

@pytest.mark.parametrize("where", ["themes", "xauthority", "appdir", "cwd"])
def test_a_link_the_app_leaves_at_a_mount_point_is_not_followed(env, where):
    # Regression: bind destinations under $HOME sit inside the app-writable private home, and bwrap
    # resolved them through whatever was there. A symlink the app left at ~/.Xauthority made the next
    # launch create a file at the link's target on the host (bwrap creates a missing destination as
    # the user); one above the app's own version folder created folders there or aborted the launch.
    # /oldroot is where bwrap keeps the host tree while it mounts, so an absolute link reaches it.
    victim = env.home / ".config" / "autostart"
    victim.mkdir(parents=True)
    gs = sb.resolve_template("cli-tool") if where == "cwd" else sb.resolve_template("strict")
    lp = env.app("evil", gs)
    proj = env.home / "src" / "proj"
    proj.mkdir(parents=True)
    run = dict(cwd=str(proj) if where == "cwd" else None, env={"DISPLAY": ":1"})
    plant = {"themes": f'ln -s /oldroot{victim}/evil "$HOME/.themes"',          # not on the host yet, so not mounted
             "xauthority": f'ln -s /oldroot{victim}/evil.desktop "$HOME/.Xauthority"',
             "appdir": f'mv "$HOME/apps" "$HOME/apps.old" && ln -s /oldroot{victim} "$HOME/apps"',   # above a mount point
             "cwd": f'mv "$HOME/src" "$HOME/src.old" && ln -s /oldroot{victim} "$HOME/src"'}[where]
    r = env.run(lp, f'{plant} && echo planted', **run)
    assert "planted" in r.stdout, (r.stdout, r.stderr)
    (env.home / ".themes").mkdir()                         # now the host has what the launcher binds
    (env.home / ".Xauthority").write_text("cookie")
    r = env.run(lp, "echo RAN-AGAIN", **run)
    assert r.returncode == 0 and "RAN-AGAIN" in r.stdout, (r.stdout, r.stderr)
    assert sorted(os.listdir(victim)) == [], os.listdir(victim)          # nothing created on the host
    assert "removing a link" in r.stderr
    home = sb.sandbox_home("evil")
    assert not any(os.path.islink(os.path.join(home, p)) for p in (".themes", ".Xauthority", "apps", "src"))


# ---------------------------------------------------------------- protected folders (R17.3.1)

def test_a_grant_of_the_home_folder_or_the_keys_does_not_open_them(env):
    # Regression: a review's `Sandbox folders: +~` (or the picker) was bound as asked, and since the
    # bind came after the private home, the real home was back — keys, shell startup files and all.
    gs = sb.apply_overrides(sb.resolve_template("standard"),
                            {"folders": {"+" + str(env.home): "rw", "+" + str(env.home / ".ssh"): "ro"}})
    r = env.run(env.app("greedy", gs), 'cat "$HOME/.ssh/id_ed25519" 2>&1; echo pwned >> "$HOME/.bashrc"; echo done')
    assert r.returncode == 0 and "done" in r.stdout, (r.stdout, r.stderr)
    assert "SECRET-KEY" not in r.stdout
    assert (env.home / ".bashrc").read_text() == "# real bashrc\n"
    _a_review_that_grants_a_system_place_leaves_the_sandbox_its_own(env)


def _a_review_that_grants_a_system_place_leaves_the_sandbox_its_own(env):
    # CR1.5-5 (#380): a system place was an ordinary folder to the never-shared check, and a grant is
    # bound after the sandbox's own /proc, /dev and /tmp: a review's `Sandbox folders: /proc:ro` put
    # the host's process table over the sandbox's (and with it every file of the user's, through
    # /proc/<pid>/root), and /dev/shm or a folder of /tmp the host's own, with what other programs
    # keep there. Refused now, whoever asks: the app runs with the sandbox's own, and the folder of
    # the home on the same line is still its. (Part of the test above, not one of its own: a run test
    # is named in tests/skips/tier1.txt, which is another unit's file while this is written.)
    from appkata_core import trustfile
    beside = env.home.parent / "beside-the-home"                 # a folder of /tmp that isn't above this test's home
    beside.mkdir()
    (beside / "theirs.sock").write_text("x")
    shm, probe = f"/dev/shm/appkata-cr1-5-5-{os.getpid()}", f"/var/tmp/appkata-cr1-5-5-{os.getpid()}"
    (env.home / "Notes").mkdir()
    (env.home / "Notes" / "n.txt").write_text("a note\n")
    parsed, _ = trustfile.parse_section("Demo", "## Demo::Settings\n\n- Trust: 4\n- Sandbox (linux): standard\n"
                                                f"- Sandbox folders (linux): /proc:ro, /dev/shm, {beside}, /var/tmp, /etc:ro, /sys:ro, ~/Notes\n")
    gs = sb.grants_from_config(sb.config_from_review(trustfile.resolve_settings(parsed["opts"], "linux")))
    assert {"/proc", "/dev/shm", str(beside), "/var/tmp", "/etc", "/sys", "~/Notes"} <= set(gs["folders"])      # the line, as written
    lp = env.app("grabby", gs)
    with open(shm, "w") as f:
        f.write("x")
    try:
        r = env.run(lp, 'echo "pid1=$(cat /proc/1/comm)"; echo "procs=$(ls /proc | grep -c "^[0-9]")"; '
                        f'[ -e {shm} ] && echo HOST-SHM; [ -e {beside}/theirs.sock ] && echo HOST-TMP; '
                        f'echo probe > {probe} 2>/dev/null; cat "$HOME/Notes/n.txt"; echo done')
        wrote = os.path.exists(probe)
    finally:
        for left in (shm, probe):
            if os.path.exists(left):
                os.unlink(left)
    assert r.returncode == 0 and "done" in r.stdout and "a note" in r.stdout, (r.stdout, r.stderr)
    assert "pid1=bwrap" in r.stdout, r.stdout                         # the sandbox's own /proc: its first process is bwrap
    assert int(re.search(r"procs=(\d+)", r.stdout).group(1)) < 10, r.stdout
    assert not {"HOST-SHM", "HOST-TMP"} & set(r.stdout.split()) and not wrote, r.stdout      # nor the host's /dev/shm, /tmp and /var/tmp
    text = open(lp).read()                                           # and the launcher says what it refused, and why
    for place, of in (("/proc", "/proc"), ("/dev/shm", "/dev"), (str(beside), "/tmp"), ("/var/tmp", "/var/tmp"), ("/etc", "/etc"), ("/sys", "/sys")):
        assert f"# Refused folder grant {place}: the system's own {of} (R17.3.1)." in text, place


# ---------------------------------------------------------------- the field test itself (review 2, D1)

@needs_proxy
def test_the_field_test_checks_the_product_and_leaves_the_testers_home_alone(env, tmp_path):
    # Review 2, D1 (class F): the release gate's script reproduced the planning-stage commands (the
    # marker on the proxy, the whole portal name, --new-session) instead of running what AppKata
    # writes, and its secrets check wrote a canary into the tester's real ~/.ssh/id_ed25519, then
    # deleted that file. It now installs a probe through install.install() and runs AppKata's own
    # launchers, all in a throwaway home.
    tester = tmp_path / "tester"
    (tester / ".ssh").mkdir(parents=True)
    (tester / ".ssh" / "id_ed25519").write_text("THE-TESTERS-REAL-KEY\n")
    before = sorted(str(p.relative_to(tester)) for p in tester.rglob("*"))
    bus = _Bus(env)
    try:
        script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts", "sandbox", "field-test.sh")
        r = subprocess.run([script, "--non-interactive"], cwd=str(tmp_path), capture_output=True, text=True, timeout=300,
                           # on this test's own Python: the one the release carries (R1.2)
                           env={**env.env, "HOME": str(tester), "DBUS_SESSION_BUS_ADDRESS": bus.addr,
                                "APPKATA_PYTHON": sys.executable})
    finally:
        bus.close()
    assert (tester / ".ssh" / "id_ed25519").read_text() == "THE-TESTERS-REAL-KEY\n"
    assert sorted(str(p.relative_to(tester)) for p in tester.rglob("*")) == before        # nothing written there
    report = next(tmp_path.glob("appkata-fieldtest-*/report.md")).read_text()
    for cid in ("A-support", "ISO-keys", "ISO-home", "ISO-net", "D-theme", "P-filter", "INNER", "T-cli", "T-cli-home",
                "EXP-strict", "EXP-online-app"):       # the exposure inventory too (review 3, harness 3)
        row = next((l for l in report.splitlines() if f"| {cid} |" in l), "")
        assert row.startswith(("| PASS", "| BLOCKED")), (cid, row, r.stdout[-1500:])
    assert r.returncode == 0, r.stdout[-2000:]
    assert list(tmp_path.glob("appkata-fieldtest-*.tar.gz"))


# ---------------------------------------------------------------- an app's own sandbox inside ours (R17.10.2)

def test_the_inner_sandbox_probe_tells_the_truth_inside_a_generated_launcher(env):
    # Review 2, F2 (class D): nested_userns_works() decides whether a Chromium/Electron app is started
    # with --no-sandbox; this ties it to what an app inside a generated launcher really gets. On Ubuntu
    # 26.04, under its own bwrap profile, both say no; on 24.04 with AppKata's profile both say yes.
    r = env.run(env.app("probe", sb.resolve_template("strict")),
                'unshare --user --map-root-user true 2>/dev/null && echo NESTED-OK || echo NESTED-NO')
    assert r.returncode == 0, r.stderr
    assert ("NESTED-OK" in r.stdout) is sb.nested_userns_works(refresh=True), r.stdout


@needs_proxy
def test_a_standard_launch_leaves_no_proxy_running(env):
    # Review 2, F2: on Ubuntu 26.04 every Standard launch left its xdg-dbus-proxy running, reparented
    # to init and confined bwrap//&unpriv_bwrap. The proxy relied on --die-with-parent, a death signal
    # the kernel clears at an exec that changes the security domain -- entering unpriv_bwrap does --
    # so killing its bwrap left it alive (and a caller reading the launcher's output waited forever).
    # The proxy's bwrap now has its own pid namespace, which dies with bwrap's first process.
    # Its socket is named by a hash of the id since R3-12, and this test went on looking for the
    # id itself: it found no proxy while the app ran either, and so could not fail (seen while
    # changing the proxy's bwrap for CR1.5-24). It first sees the proxy it then wants gone.
    tag = hashlib.sha256(b"leak").hexdigest()[:16]

    def proxies():
        return [l for l in subprocess.run(["ps", "-eo", "args"], capture_output=True, text=True).stdout.splitlines()
                if "xdg-dbus-proxy" in l and f"bus-{tag}." in l]

    bus = _Bus(env)
    try:
        lp = env.app("leak", sb.resolve_template("developer"))
        p = subprocess.Popen([lp, "echo RAN; sleep 2"], env={**env.env, "DBUS_SESSION_BUS_ADDRESS": bus.addr},
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        seen = []
        for _ in range(40):
            seen = seen or proxies()
            subprocess.run(["sleep", "0.05"])
        assert seen and p.wait(timeout=30) == 0, seen
        left = []
        for _ in range(20):                                   # the namespace's processes go with bwrap, at once
            left = proxies()
            if not left:
                break
            subprocess.run(["sleep", "0.1"])
        assert left == [], left
    finally:
        bus.close()


@pytest.mark.parametrize("brings", [True, False])
@pytest.mark.parametrize("inner", [True, False])
def test_a_chromium_app_gets_no_sandbox_exactly_where_its_own_cannot_run(env, monkeypatch, inner, brings):
    monkeypatch.setattr(sb, "nested_userns_works", lambda refresh=False: inner)
    lp = env.app("chat", sb.resolve_template("strict"))
    appdir = env.home / "apps" / "chat" / "1.0"
    (appdir / "bin" / "app").write_text('#!/bin/sh\necho "ARGS:$*"\n')
    if brings:
        (appdir / "bin" / "chrome-sandbox").write_text("")
    r = subprocess.run([lp, "--some-flag", "file name.txt"], env=env.env, capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    expected = "ARGS:--no-sandbox --some-flag file name.txt" if brings and not inner else "ARGS:--some-flag file name.txt"
    assert r.stdout.strip() == expected, r.stdout


@pytest.mark.parametrize("form", ["top", "whole", "plus"])
def test_a_review_naming_a_relative_folder_never_opens_the_real_home(env, monkeypatch, form):
    # Review 2, F1: protected_folder() judged a relative path against AppKata's own working directory
    # while bwrap resolves a bind source from the host's root, so a review's `Sandbox folders: home`
    # (on a desktop; `tmp` here, where the test home lives under /tmp) passed as an ordinary folder and
    # bound the real home: the app read ~/.ssh and appended to the real ~/.bashrc. Judged from inside.
    from appkata_core import trustfile
    rel = os.path.relpath(str(env.home), "/")
    line = {"top": rel.split("/")[0], "whole": rel, "plus": "+" + rel.split("/")[0]}[form]
    monkeypatch.chdir("/tmp")                                      # where AppKata's own cwd made "tmp" look harmless
    parsed, _ = trustfile.parse_section("Demo", "## Demo::Settings\n\n- Trust: 4\n- Sandbox (linux): offline-editor\n"
                                                f"- Sandbox folders (linux): {line}\n")
    gs = sb.grants_from_config(sb.config_from_review(trustfile.resolve_settings(parsed["opts"], "linux")))
    r = env.run(env.app("lookalike", gs), 'cat "$HOME/.ssh/id_ed25519" 2>&1; echo pwned >> "$HOME/.bashrc"; echo done')
    assert r.returncode == 0 and "done" in r.stdout, (r.stdout, r.stderr)
    assert "SECRET-KEY" not in r.stdout
    assert (env.home / ".bashrc").read_text() == "# real bashrc\n"


# ---------------------------------------------------------------- a refused launch leaves a trace (R14.2, R4)

def _fake_bwrap(env, message: str) -> dict:
    """A PATH whose bwrap prints `message` and exits 1 — the userns restriction come back, say."""
    d = env.home / "fakebin"
    d.mkdir(exist_ok=True)
    (d / "bwrap").write_text(f'#!/bin/sh\necho "{message}" >&2\nexit 1\n')
    (d / "bwrap").chmod(0o755)
    return {"PATH": f"{d}:{os.environ['PATH']}"}


def test_a_launch_from_the_menu_writes_its_refusal_to_the_app_log(env, tmp_path):
    # Regression (round two, R4): the .desktop entry ran the launcher directly, so a bwrap refusal
    # there was invisible and unrecorded; only Open in AppKata captured it. The entry now passes
    # --appkata-menu first, and the launcher keeps its stderr in the app's log for that case.
    lp = env.app("menu", sb.resolve_template("strict"))
    log = tmp_path / "home" / ".local" / "state" / "appkata" / "apps" / "menu.log"                # the install's id (R14.2.1)
    assert f"log={log}" in open(lp).read()
    refused = _fake_bwrap(env, "bwrap: setting up uid map: Permission denied")
    lp_refused = env.on_a_machine_with(lp, refused["PATH"])
    r = subprocess.run([lp_refused, "--appkata-menu", "echo never"], cwd=str(env.home), env={**env.env, **refused},
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 1 and r.stderr == ""                 # the desktop's stderr got nothing ...
    text = log.read_text()
    assert "AppKata: starting Menu (from the menu)" in text and "Permission denied" in text    # ... the log did
    assert "AppKata: running" in text                           # bwrap was reached: the mark precedes it
    r = subprocess.run([lp, "--appkata-menu", "echo ran"], cwd=str(env.home), env=env.env, capture_output=True,
                       text=True, timeout=30)
    assert r.returncode == 0 and "ran" in r.stdout              # stdout is never taken; the word is not an argument
    assert log.read_text().count("AppKata: starting Menu") == 2   # appended, not truncated

    # from AppKata's Open: stderr already is the log, so no second header, and the mark is written
    log.write_text("")
    with open(log, "a") as out:
        subprocess.run([lp, "echo ran"], cwd=str(env.home), env=env.env, stdout=out, stderr=out, timeout=30)
    text = log.read_text()
    assert "starting Menu" not in text and text.startswith("AppKata: running ") and "ran\n" in text

    # any other way (a command link, a script): stderr stays the caller's and the log is left alone
    log.unlink()
    r = subprocess.run([lp_refused, "echo never"], cwd=str(env.home), env={**env.env, **refused}, capture_output=True,
                       text=True, timeout=30)
    assert "Permission denied" in r.stderr and not log.exists()


# ---------------------------------------------------------------- file arguments (R17.6.2, R7)

def _a_link_the_app_plants_in_its_folder_hands_it_nothing(env, lp, e):
    """CR1.5-4 (#379), with the real document portal, by the finding's own road: the app, given
    ~/Projects read-write, puts a link to a file of the user's where its own file was, and a link
    to a folder beside it; the user then opens both (a path, a file:// URI, a file through the
    linked folder). Each was handed over, read-write, by where it leads. Now each reaches the app as
    its own path in ~/Projects, where the link dangles, and nothing new is under
    $XDG_RUNTIME_DIR/doc. The other direction (R3-17: the user's link on the desktop to a file in
    ~/Projects) still reaches its file. A part of the test below, which tests/skips/tier1.txt names."""
    docs, proj, desk = env.home / "Documents", env.home / "Projects", env.home / "Desktop"
    (docs / "taxes.txt").write_text("TAXES\n")
    desk.mkdir()
    (desk / "mine").symlink_to(proj / "mine.txt.was")
    r = subprocess.run([lp, 'cd "$HOME/Projects" && mv mine.txt mine.txt.was && ln -s "$HOME/Documents/taxes.txt" mine.txt && '
                            'ln -s "$HOME/Documents" Photos && echo PLANTED'], cwd=str(env.home), env=e, capture_output=True, text=True, timeout=60)
    assert "PLANTED" in r.stdout and os.readlink(proj / "mine.txt") == str(docs / "taxes.txt"), (r.stdout, r.stderr)   # on the host, as the app meant
    exported = lambda: {(d, f) for d in os.listdir(env.rt / "doc") if d != "by-app" for f in os.listdir(env.rt / "doc" / d)}   # noqa: E731
    before = exported()
    args = [str(proj / "mine.txt"), "file://" + str(proj / "mine.txt"), str(proj / "Photos"), str(proj / "Photos" / "taxes.txt")]
    snippet = ('shift; for a in "$@"; do printf "ARG %s\\n" "$a"; done; cat "$1" "$4" "$XDG_RUNTIME_DIR"/doc/*/taxes.txt "$XDG_RUNTIME_DIR"/doc/*/*/taxes.txt 2>&1; '
               '(echo EDITED >> "$1") 2>/dev/null; ls "$3" 2>&1; cat "$5"; true')
    r = subprocess.run([lp, snippet, *args, str(desk / "mine")], cwd=str(env.home), env=e, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and [l[4:] for l in r.stdout.splitlines() if l.startswith("ARG ")] == args + [str(proj / "mine.txt.was")], (r.stdout, r.stderr)
    assert exported() == before, (exported() - before, r.stdout)
    assert "TAXES" not in r.stdout and (docs / "taxes.txt").read_text() == "TAXES\n" and "MINE" in r.stdout, (r.stdout, r.stderr)


def _a_link_to_a_file_outside_every_grant_reaches_the_app_as_a_path_that_opens(env, lp, e):
    """CR1.5-41 (#666), the finding's own run with the real document portal: an absolute and a
    relative link to a file outside every grant, as a path and as a file:// URI. The portal names
    the document after the file the link leads to, and the app was handed the link's name, a path
    that isn't there. A regular file and a linked folder as before. A part of the test below,
    which tests/skips/tier1.txt names."""
    sync = env.home / "sync"
    (sync / "project").mkdir(parents=True)
    for f, text in ((sync / "notes-2024.txt", "NOTES-2024\n"), (sync / "plain.txt", "PLAIN\n"), (sync / "project" / "inproj.txt", "x")):
        f.write_text(text)
    (env.home / "notes.txt").symlink_to(sync / "notes-2024.txt")
    (env.home / "rel-notes.txt").symlink_to("sync/notes-2024.txt")
    (env.home / "proj-link").symlink_to(sync / "project")
    args = [str(env.home / "notes.txt"), "rel-notes.txt", "file://" + str(env.home / "notes.txt"), str(sync / "plain.txt"), str(env.home / "proj-link")]
    snippet = ('shift; for a in "$@"; do printf "ARG %s\\n" "$a"; done; cat "$1" "$2" "${3#file://}" "$4"; ls "$5"; echo APPENDED >> "$2"; true')
    r = subprocess.run([lp, snippet, *args], cwd=str(env.home), env=e, capture_output=True, text=True, timeout=60)
    got = [l[4:] for l in r.stdout.splitlines() if l.startswith("ARG ")]
    doc = str(env.rt / "doc") + "/"
    assert r.returncode == 0 and len(got) == 5 and all(g.startswith(doc) for g in got[:2] + got[3:]), (r.stdout, r.stderr)
    assert got[0].endswith("/notes-2024.txt") and got[1] == got[0] and got[2] == "file://" + got[0], got       # one document, by the file's name
    assert got[3].endswith("/plain.txt") and got[4].endswith("/project"), got
    assert r.stdout.count("NOTES-2024") == 3 and "PLAIN" in r.stdout and "inproj.txt" in r.stdout, (r.stdout, r.stderr)
    assert (sync / "notes-2024.txt").read_text() == "NOTES-2024\nAPPENDED\n"                                    # and it is the file the app writes


@needs_proxy
def test_a_file_argument_is_handed_over_to_a_standard_app(env):
    # Regression (round two, R7): the desktop entry's %U, "Open with", a drop on the entry and
    # `tool ~/notes.txt` handed the app host paths that don't exist in its private home, so it opened
    # nothing. The launcher now exports such files through the document portal, from the host side,
    # and the argument becomes the path the app sees; files in a granted folder keep their path.
    bus = _Bus(env)
    try:
        portal = _DocPortal(env, bus)
        try:
            docs, proj = env.home / "Documents", env.home / "Projects"
            docs.mkdir(); proj.mkdir()
            (docs / "picked.txt").write_text("PICKED\n")
            (docs / "read only.txt").write_text("RO\n")
            (docs / "read only.txt").chmod(0o444)
            (proj / "mine.txt").write_text("MINE\n")
            gs = sb.apply_overrides(sb.resolve_template("online-app"), {"folders": {"+~/Projects": "rw"}})
            lp = env.app("editor", gs)
            snippet = ('shift; for a in "$@"; do printf "ARG %s\\n" "$a"; done; cat "$1"; echo EDITED >> "$1"; cat "$3"; '
                       'cat "$4"; (echo x >> "$4") 2>/dev/null || echo "no write"; true')
            r = subprocess.run([lp, snippet, str(docs / "picked.txt"), "file://" + str(docs / "picked.txt"), str(proj / "mine.txt"),
                                str(docs / "read only.txt"), "file://" + str(docs / "read%20only.txt"), "https://example.org/x"],
                               cwd=str(env.home), env={**env.env, "DBUS_SESSION_BUS_ADDRESS": bus.addr},
                               capture_output=True, text=True, timeout=60)
            assert r.returncode == 0, r.stderr
            args = [l[4:] for l in r.stdout.splitlines() if l.startswith("ARG ")]
            doc = str(env.rt / "doc") + "/"
            assert len(args) == 6
            assert args[0].startswith(doc) and args[0].endswith("/picked.txt") and str(docs) not in args[0]   # handed over
            assert args[1] == "file://" + args[0]                                     # a URI stays a URI, same document
            assert args[2] == str(proj / "mine.txt")                                  # in a granted folder: as it was
            assert args[3].startswith(doc) and args[3].endswith("/read only.txt")
            assert args[4] == "file://" + args[3].replace(" ", "%20")                 # decoded to find it, encoded again
            assert args[5] == "https://example.org/x"                                 # not a file
            assert "PICKED" in r.stdout and "MINE" in r.stdout and "RO" in r.stdout and "no write" in r.stdout
            assert (docs / "picked.txt").read_text() == "PICKED\nEDITED\n"          # the app's edit reached the real file
            assert (docs / "read only.txt").read_text() == "RO\n"                    # read-only for the user: read-only here
            _a_link_the_app_plants_in_its_folder_hands_it_nothing(env, lp, {**env.env, "DBUS_SESSION_BUS_ADDRESS": bus.addr})
            _a_link_to_a_file_outside_every_grant_reaches_the_app_as_a_path_that_opens(env, lp, {**env.env, "DBUS_SESSION_BUS_ADDRESS": bus.addr})
            _a_link_the_app_plants_in_a_folder_it_was_handed_hands_it_nothing(env, lp, {**env.env, "DBUS_SESSION_BUS_ADDRESS": bus.addr})
            _what_an_app_was_handed_is_taken_back_when_it_goes(env, lp, gs, {**env.env, "DBUS_SESSION_BUS_ADDRESS": bus.addr})
        finally:
            portal.close()
    finally:
        bus.close()


def _a_link_the_app_plants_in_a_folder_it_was_handed_hands_it_nothing(env, lp, e):
    """CR1.5-52 (#736), with the real document portal, by the finding's own road: the user hands
    the app a folder (`editor ~/work`), and in it, through the portal's file system, the app puts a
    link to another file of the user's where README.md was, and a link to a folder beside it. At a
    later start the user opens README.md, by a path and by a URI, and a file through the linked
    folder: each was handed over, read-write, by where it leads. Now each reaches the app as its
    own path in the folder's document, where the link dangles; a file that is the folder's own is
    its path there too, and nothing new is under $XDG_RUNTIME_DIR/doc. The same for a folder and
    a link in it named at one start. A part of the test above, which tests/skips/tier1.txt names."""
    docs, work, again = env.home / "Documents", env.home / "work", env.home / "again"
    for d in (work / "sub", again):
        d.mkdir(parents=True)
    for f, text in ((work / "README.md", "README\n"), (work / "sub" / "deep.txt", "DEEP\n"), (docs / "secret.txt", "SECRET-TAXES\n"), (again / "plain.txt", "PLAIN\n"),
                    (docs / "one.txt", "ONE\n")):
        f.write_text(text)
    (again / "README.md").symlink_to(docs / "secret.txt")

    def started(snippet, *args):
        r = subprocess.run([lp, 'shift; for a in "$@"; do printf "ARG %s\\n" "$a"; done; ' + snippet, *args], cwd=str(env.home), env=e,
                           capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, r.stderr
        return [l[4:] for l in r.stdout.splitlines() if l.startswith("ARG ")], r.stdout + r.stderr

    got, out = started(f'cd "$1" && mv README.md README.was && ln -s {shlex.quote(str(docs / "secret.txt"))} README.md && '
                       f'ln -s {shlex.quote(str(docs))} all && echo PLANTED; '
                       # what the fix rests on (A1.11): a file's document takes no link and no folder, and the app can
                       # neither remove nor rename a folder's document, so it stays in what the portal lists for the app
                       'one=$(dirname "$2"); ln -s /etc/hostname "$one/planted" 2>/dev/null && echo LINK-IN-A-FILES-DOCUMENT; '
                       'mkdir "$one/made" 2>/dev/null && echo FOLDER-IN-A-FILES-DOCUMENT; held=$(dirname "$1"); '
                       'rmdir "$held" 2>/dev/null && echo DOCUMENT-REMOVED; mv "$held" "$held.gone" 2>/dev/null && echo DOCUMENT-RENAMED; '
                       'mv "$1" "$held/renamed" 2>/dev/null && echo FOLDER-RENAMED; true', str(work), str(docs / "one.txt"))
    view = got[0]
    assert "PLANTED" in out and view.startswith(str(env.rt / "doc") + "/") and view.endswith("/work"), (got, out)
    assert os.readlink(work / "README.md") == str(docs / "secret.txt") and os.readlink(work / "all") == str(docs)       # on the host, as the app meant
    assert got[1].endswith("/one.txt") and not any(w in out for w in ("LINK-IN", "FOLDER-IN", "DOCUMENT-RE", "FOLDER-RENAMED")), out
    assert not os.path.lexists(docs / "planted") and not os.path.lexists(docs / "made") and work.is_dir()
    exported = lambda: {(d, f) for d in os.listdir(env.rt / "doc") if d != "by-app" for f in os.listdir(env.rt / "doc" / d)}   # noqa: E731
    before = exported()
    got, out = started('cat "$1" "$3" "$XDG_RUNTIME_DIR"/doc/*/secret.txt 2>&1; (echo EDITED >> "$1") 2>/dev/null; cat "$4"; echo MORE >> "$4"; true',
                       str(work / "README.md"), "file://" + str(work / "README.md"), str(work / "all" / "secret.txt"), str(work / "sub" / "deep.txt"))
    assert got == [f"{view}/README.md", f"file://{view}/README.md", f"{view}/all/secret.txt", f"{view}/sub/deep.txt"], (got, out)
    assert exported() == before, (exported() - before, out)
    assert "SECRET-TAXES" not in out and (docs / "secret.txt").read_text() == "SECRET-TAXES\n", out
    assert "DEEP" in out and (work / "sub" / "deep.txt").read_text() == "DEEP\nMORE\n", out                # the folder's own file, read and written
    # a folder, and a link in it, at one start: the folder is the app's by the time the link is judged
    got, out = started('cat "$2" "$3" "$XDG_RUNTIME_DIR"/doc/*/secret.txt 2>&1; true', str(again), str(again / "README.md"), str(again / "plain.txt"))
    assert got[0].endswith("/again") and got[1:] == [got[0] + "/README.md", got[0] + "/plain.txt"], (got, out)
    assert "SECRET-TAXES" not in out and "PLAIN" in out and (docs / "secret.txt").read_text() == "SECRET-TAXES\n", out


def _what_an_app_was_handed_is_taken_back_when_it_goes(env, lp, gs, e):
    """CR1.5-25 (#400), with the real document portal, which the review could not run: a file and a
    folder handed to an app are still its own at its next start, which is the hand-over working
    (the portal keeps them for the session). They stayed its own when it went to Strict or Off and
    came back, and they were the next app's of that id: the app uninstalled with its home removed,
    another Source's "Editor" installed under the freed id read the file and wrote to it. A part
    of the test above, which tests/skips/tier1.txt names (that file is another unit's)."""
    import json
    from appkata_core import install
    from appkata_core.db import DB, now
    picked, folder = env.home / "Documents" / "picked.txt", env.home / "Handed"
    folder.mkdir()
    (folder / "inside.txt").write_text("INSIDE\n")
    was = picked.read_text()
    look = ('cat "$XDG_RUNTIME_DIR"/doc/*/picked.txt "$XDG_RUNTIME_DIR"/doc/*/Handed/inside.txt 2>/dev/null; '
            'for d in "$XDG_RUNTIME_DIR"/doc/*; do [ -e "$d" ] && echo "DOCUMENT $d"; done; true')
    write = 'for f in "$XDG_RUNTIME_DIR"/doc/*/picked.txt "$XDG_RUNTIME_DIR"/doc/*/Handed/inside.txt; do (echo LATER >> "$f") 2>/dev/null; done; true'

    def run(launcher, snippet, *args):
        r = subprocess.run([launcher, snippet, *args], cwd=str(env.home), env=e, capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, r.stderr
        return r.stdout + r.stderr

    def hand():                         # the user opens the file and the folder with the app
        assert "PICKED" in run(lp, 'cat "$2" "$3"/inside.txt', str(picked), str(folder))
        held = run(lp, look)            # ...and at its next start they are still its own, by no argument
        assert "PICKED" in held and "INSIDE" in held and "DOCUMENT " in held, held

    def holds_nothing(launcher, when):
        held = run(launcher, look + "; " + write)
        assert "PICKED" not in held and "INSIDE" not in held and "DOCUMENT " not in held, (when, held)
        assert picked.read_text() == was and (folder / "inside.txt").read_text() == "INSIDE\n", when

    target, url = env.home / "apps" / "editor", "https://example.org/alice/editor"
    rec = {"id": "editor", "current": {"version": "1.0", "path": str(target / "1.0"), "exec": "1.0/bin/app"}, "target": str(target),
           "root": str(env.home / "apps"), "links": [], "files": [str(target)], "launcher": lp, "sandbox": sb.to_json(gs)}
    db = DB(str(env.home / ".local" / "share" / "appkata" / "handed.db"))
    db.x("INSERT INTO installs(url, name, version, kind, record, installed_at) VALUES(?,?,?,?,?,?)", (url, "Editor", "1.0", "tarball", json.dumps(rec), now()))
    portable = install.Portable(folder=str(env.home / "apps"), command_dir="", app_menu=False, stable_name=False)
    app = lambda level: {"url": url, "name": "Editor", "sandbox": level and sb.to_json(level)}      # noqa: E731
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("DBUS_SESSION_BUS_ADDRESS", e["DBUS_SESSION_BUS_ADDRESS"])          # AppKata runs in the same session
        for away in (sb.resolve_template("strict"), None):                              # to Strict and back, to Off and back
            hand()
            install.rewrite_launcher(db, app(away), portable)
            install.rewrite_launcher(db, app(gs), portable)
            holds_nothing(lp, "back from Strict" if away else "back from Off")
        hand()
        install.uninstall(db, url, remove_sandbox=True)
        assert not os.path.exists(sb.sandbox_home("editor")) and not os.path.exists(lp)
        assert install.new_app_id(db, "https://example.org/bob/editor", "Editor") == "editor"       # the id is free (R17.6)
        holds_nothing(env.app("editor", gs), "another Source's app under the freed id")
        assert not os.path.lexists(sb.handed_path("editor"))
        hand()                          # and what this one is handed is its own
        assert os.path.isfile(sb.handed_path("editor"))


def _a_session_with_no_document_portal_holds_nothing_and_is_not_made_to_start_one(env, addr):
    """CR1.5-25 (#400): AppKata's ask of the portal on a real session bus where none runs. The bus
    could start one (_bus_conf); the ask must not, and its answer is that nothing is held. With
    no bus to ask at all it couldn't be asked, and the note that the app was handed something
    stays for the next ask. A part of the test below, which tests/skips/tier1.txt names."""
    def note():
        os.makedirs(os.path.dirname(sb.handed_path("plain")), exist_ok=True)
        open(sb.handed_path("plain"), "w").close()

    with pytest.MonkeyPatch.context() as mp:
        note()
        mp.setenv("DBUS_SESSION_BUS_ADDRESS", addr)
        assert sb.revoke_documents("plain") is True and not os.path.lexists(sb.handed_path("plain"))
        assert not os.path.isdir(env.rt / "doc" / "by-app")             # no portal was started for it
        note()
        mp.setenv("DBUS_SESSION_BUS_ADDRESS", f"unix:path={env.rt}/nonexistent")
        assert sb.revoke_documents("plain") is False and os.path.isfile(sb.handed_path("plain"))


@needs_proxy
def test_file_arguments_pass_through_when_they_cannot_be_handed_over(env):
    # No session bus (so no document portal; a bus would activate one on demand), or no python3-gi
    # on the host: the arguments reach the app as they were, as before the hand-over existed.
    docs = env.home / "Documents"
    docs.mkdir()
    (docs / "a.txt").write_text("A\n")
    lp = env.app("plain", sb.resolve_template("online-app"))
    r = subprocess.run([lp, 'echo "ARG $2"', str(docs / "a.txt")], cwd=str(env.home), env=env.env,
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and f"ARG {docs}/a.txt" in r.stdout, (r.stdout, r.stderr)
    fake = env.home / "nogi"
    fake.mkdir()
    (fake / "python3").write_text("#!/bin/sh\necho 'ModuleNotFoundError: No module named gi' >&2; exit 1\n")
    (fake / "python3").chmod(0o755)
    bus = _Bus(env)
    try:
        r = subprocess.run([env.on_a_machine_with(lp, f"{fake}:{os.environ['PATH']}"), 'echo "ARG $2"', str(docs / "a.txt")],
                           cwd=str(env.home), env={**env.env, "DBUS_SESSION_BUS_ADDRESS": bus.addr},
                           capture_output=True, text=True, timeout=60)
        _a_session_with_no_document_portal_holds_nothing_and_is_not_made_to_start_one(env, bus.addr)
    finally:
        bus.close()
    assert r.returncode == 0 and f"ARG {docs}/a.txt" in r.stdout, (r.stdout, r.stderr)


def _a_never_shared_argument_is_handed_over_to_no_app(env, lp, e):
    """CR1.5-38 (#651), with the real document portal: `tool .` from the home folder, the home by
    its path and as a URI, a key and a startup file leave nothing under $XDG_RUNTIME_DIR/doc, reach
    the tool as they were typed, and each has its line on stderr. The tool's own line said it
    couldn't see the home, and the helper then exported the home, read-write. A part of the test
    below, which tests/skips/tier1.txt names (that file is another unit's)."""
    key, rc = env.home / ".ssh" / "id_ed25519", env.home / ".bashrc"
    exported = lambda: {(d, f) for d in os.listdir(env.rt / "doc") if d != "by-app" for f in os.listdir(env.rt / "doc" / d)}   # noqa: E731
    before = exported()
    snippet = ('shift; for a in "$@"; do printf "ARG %s\\n" "$a"; done; ls -A "$XDG_RUNTIME_DIR"/doc/* 2>&1; '
               'cat "$XDG_RUNTIME_DIR"/doc/*/id_ed25519 "$XDG_RUNTIME_DIR"/doc/*/*/.ssh/id_ed25519 "$2" 2>&1; echo x >> "$3"; true')
    args = [".", str(key), str(rc), str(env.home), "file://" + str(env.home), "--key=" + str(key)]
    r = subprocess.run([lp, snippet, *args], cwd=str(env.home), env=e, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and [l[4:] for l in r.stdout.splitlines() if l.startswith("ARG ")] == args, (r.stdout, r.stderr)
    assert exported() == before, (exported() - before, r.stderr)             # the portal was given nothing of them
    assert "SECRET-KEY" not in r.stdout and rc.read_text() == "# real bashrc\n", r.stdout
    said = [l for l in r.stderr.splitlines() if "isn't handed" in l]
    assert said == [f"Tool runs sandboxed and isn't handed .: your whole home folder is never shared with a sandboxed app.",
                    f"Tool runs sandboxed and isn't handed {key}: {env.home}/.ssh is never shared with a sandboxed app.",
                    f"Tool runs sandboxed and isn't handed {rc}: {rc} is never shared with a sandboxed app.",
                    f"Tool runs sandboxed and isn't handed {env.home}: your whole home folder is never shared with a sandboxed app."], r.stderr
    assert f"can't see {env.home} " in r.stderr and "unless it is in a never-shared folder of your home" in r.stderr, r.stderr


@needs_proxy
def test_a_cli_tool_run_from_a_refused_folder_is_still_given_its_file_arguments(env):
    # Regression (round three, R3-3): the file-argument block ran before the working-directory rule
    # and always counted $PWD as visible, so `cd ~ && tool Documents/notes.txt` (the home is refused)
    # handed over nothing and the tool, now in its private home, found no such file by either path.
    # The directory counts as visible only when it will be shared; a file named from a refused one is
    # exported like any other and the argument becomes the hand-over path, absolute whatever was typed.
    bus = _Bus(env)
    try:
        portal = _DocPortal(env, bus)
        try:
            docs = env.home / "Documents"
            docs.mkdir()
            (docs / "notes.txt").write_text("NOTES\n")
            proj = env.home / "src" / "proj"
            proj.mkdir(parents=True)
            (proj / "in.txt").write_text("IN\n")
            lp = env.app("tool", sb.resolve_template("cli-tool"))
            snippet = 'shift; for a in "$@"; do printf "ARG %s\\n" "$a"; done; cat "$1"; cat "$2"; true'
            e = {**env.env, "DBUS_SESSION_BUS_ADDRESS": bus.addr}
            r = subprocess.run([lp, snippet, "Documents/notes.txt", str(docs / "notes.txt")], cwd=str(env.home), env=e,
                               capture_output=True, text=True, timeout=60)
            r2 = subprocess.run([lp, snippet, "in.txt", str(docs / "notes.txt")], cwd=str(proj), env=e,
                                capture_output=True, text=True, timeout=60)
            # CR1.5-6 (#381): a folder of /tmp is no tool's to work in, and a file named there, by
            # either path, is handed over like any other
            work = env.home.parent / "work"
            work.mkdir()
            (work / "draft.txt").write_text("DRAFT\n")
            r3 = subprocess.run([lp, snippet, "draft.txt", str(work / "draft.txt")], cwd=str(work), env=e,
                                capture_output=True, text=True, timeout=60)
            _a_never_shared_argument_is_handed_over_to_no_app(env, lp, e)
        finally:
            portal.close()
    finally:
        bus.close()
    doc = str(env.rt / "doc") + "/"
    args = [l[4:] for l in r3.stdout.splitlines() if l.startswith("ARG ")]
    assert r3.returncode == 0 and f"isn't given {work} to work in" in r3.stderr, (r3.stdout, r3.stderr)
    assert len(args) == 2 and all(a.startswith(doc) and a.endswith("/draft.txt") for a in args), args
    assert r3.stdout.count("DRAFT") == 2, r3.stdout
    args = [l[4:] for l in r.stdout.splitlines() if l.startswith("ARG ")]
    assert r.returncode == 0 and "can't see" in r.stderr, (r.stdout, r.stderr)        # refused, as before
    assert len(args) == 2 and all(a.startswith(doc) and a.endswith("/notes.txt") for a in args), args
    assert r.stdout.count("NOTES") == 2, r.stdout                                      # and both readable
    args = [l[4:] for l in r2.stdout.splitlines() if l.startswith("ARG ")]
    assert args[0] == "in.txt" and args[1].startswith(doc), args                       # a shared folder: as typed
    assert "IN" in r2.stdout and "NOTES" in r2.stdout, r2.stdout


# ---------------------------------------------------------------- the first launch, and nested grants (R8, round two)

@needs_proxy
def test_a_file_exported_while_the_app_runs_is_readable_on_its_first_launch(env):
    # The by-app/<id> view is a directory as soon as the document portal runs — before anything is
    # exported for that id — so the launcher's --bind-try mounts $XDG_RUNTIME_DIR/doc on the very
    # first launch and a file picked or passed during that run is visible at once. (A review note
    # had claimed the view appears only after a first export, which would have needed a relaunch.)
    bus = _Bus(env)
    try:
        portal = _DocPortal(env, bus)
        try:
            assert os.path.isdir(env.rt / "doc" / "by-app" / sb.app_identity("fresh"))      # nothing exported yet
            docs = env.home / "Documents"
            docs.mkdir()
            (docs / "picked.txt").write_text("PICKED\n")
            lp = env.app("fresh", sb.resolve_template("online-app"))
            p = subprocess.Popen([lp, '[ -d "$XDG_RUNTIME_DIR/doc" ] && echo DOC-DIR-PRESENT; sleep 3; '
                                      'cat "$XDG_RUNTIME_DIR"/doc/*/picked.txt; true'],
                                 cwd=str(env.home), env={**env.env, "DBUS_SESSION_BUS_ADDRESS": bus.addr},
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            subprocess.run(["sleep", "1"])
            portal.export(str(docs / "picked.txt"), sb.app_identity("fresh"))      # while it runs
            out, err = p.communicate(timeout=60)
            assert p.returncode == 0, err
            assert "DOC-DIR-PRESENT" in out and "PICKED" in out, (out, err)
        finally:
            portal.close()
    finally:
        bus.close()


def test_nested_folder_grants_cannot_reopen_the_symlink_hole(env):
    # Two grants, one inside the other: the inner mount's destination sits in the outer grant, which
    # is the real folder, so a link the app leaves there lands on the host and the sweep (which
    # covers the private home) doesn't see it. It still can't be used: bwrap resolves the bind's
    # *source* on the host too, where /oldroot doesn't exist, so --ro-bind-try skips the mount.
    victim = env.home / ".config" / "autostart"
    victim.mkdir(parents=True)
    proj = env.home / "Projects"
    (proj / "sub" / "deep").mkdir(parents=True)
    gs = sb.apply_overrides(sb.resolve_template("standard"),
                            {"folders": {"+" + str(proj): "rw", "+" + str(proj / "sub" / "deep"): "ro"}})
    lp = env.app("nest", gs)
    r = env.run(lp, f'mv "$HOME/Projects/sub" "$HOME/Projects/sub.old" && ln -s /oldroot{victim} "$HOME/Projects/sub" && echo planted')
    assert "planted" in r.stdout and os.path.islink(proj / "sub")           # on the host, as the app intended
    r = env.run(lp, "echo RAN-AGAIN")
    assert r.returncode == 0 and "RAN-AGAIN" in r.stdout, r.stderr            # the next launch still works ...
    assert os.listdir(victim) == []                                            # ... and created nothing there
    _a_link_put_above_a_nested_grant_mounts_nothing_of_the_users(env)


def _a_link_put_above_a_nested_grant_mounts_nothing_of_the_users(env):
    # CR1.5-40 (#665): ...but a link to /oldroot leads nowhere on the host, so that plant was skipped
    # whatever bwrap did with a source. Relative links lead somewhere on both sides: with ~/Projects
    # read-write and ~/Projects/sub/deep granted too, the app made ~/.ssh in its private home, put a
    # folder `evil` in ~/Projects with `evil/deep` a link to `../../.ssh`, moved `sub` away and made
    # `sub` a link to `evil`; all of it landed in the real ~/Projects, and the next launch mounted the
    # user's real ~/.ssh at the app's (read-only as the inner grant was; with a read-write one, the
    # real ~/.config/autostart, written to). Each grant is asked again at every launch now, and one
    # that no longer leads where it led when the launcher was written is dropped, with a line; and a
    # launcher written again refuses a grant that a link in another granted folder is on the way to.
    # (Parts of the test above, not tests of their own: a run test is named in tests/skips/tier1.txt,
    # which is another unit's file while this is written.)
    (env.home / ".config" / "autostart" / "HOST-VICTIM-FILE").write_text("HOST-VICTIM-CONTENT\n")
    (env.home / "Documents").mkdir()
    (env.home / "Documents" / "taxes.txt").write_text("TAXES\n")
    hosts = {".ssh": ["id_ed25519"], ".config/autostart": ["HOST-VICTIM-FILE"], "Documents": ["taxes.txt"]}
    secret = ("SECRET-KEY", "HOST-VICTIM-CONTENT", "TAXES", "id_ed25519", "HOST-VICTIM-FILE", "taxes.txt")

    def untouched(r, *where):
        assert r.returncode == 0 and "RAN-AGAIN" in r.stdout, (where, r.stdout, r.stderr)
        assert not [w for w in secret if w in r.stdout], (where, r.stdout, r.stderr)             # nothing of the user's read or listed
        assert {v: sorted(os.listdir(env.home / v)) for v in hosts} == hosts, where              # and nothing written there
        assert "bwrap" not in r.stderr, (where, r.stderr)

    look = ('ls "$HOME/{victim}" 2>&1; cat "$HOME/{victim}"/* 2>&1; cat "$HOME/{inner}"/* 2>&1; (echo x > "$HOME/{victim}/planted-by-app") 2>&1; '
            '(echo x > "$HOME/{inner}/planted-by-app") 2>&1; echo out > "$HOME/{outer}/out.txt"; echo RAN-AGAIN')
    dropped = "{app} runs sandboxed and isn't given {folder} this time: it led to {folder} when AppKata wrote this launcher and leads to {now} now"

    # the finding's own run, the inner grant read-only and read-write; then a folder no list names
    for n, (mode, victim) in enumerate((("ro", ".ssh"), ("rw", ".config/autostart"), ("ro", "Documents")), 1):
        outer, up = f"P{n}", "../.."                           # from ~/P<n>/evil, where the link is, to the home
        proj = env.home / outer
        (proj / "sub" / "deep").mkdir(parents=True)
        (proj / "sub" / "deep" / "mine.txt").write_text("MINE\n")
        gs = sb.apply_overrides(sb.resolve_template("standard"), {"folders": {"+" + str(proj): "rw", "+" + str(proj / "sub" / "deep"): mode}})
        lp = env.app(f"nest{n}", gs)
        r = env.run(lp, f'cat "$HOME/{outer}/sub/deep/mine.txt" && mkdir -p "$HOME/{victim}" "$HOME/{outer}/evil" && ln -s {up}/{victim} "$HOME/{outer}/evil/deep" && '
                        f'mv "$HOME/{outer}/sub" "$HOME/{outer}/sub.old" && ln -s evil "$HOME/{outer}/sub" && echo planted')
        assert "MINE" in r.stdout and "planted" in r.stdout and os.path.islink(proj / "sub"), (r.stdout, r.stderr)   # the grant worked, and the links are the host's
        assert os.path.realpath(proj / "sub" / "deep") == str(env.home / victim)                    # where bwrap would be led
        r = env.run(lp, look.format(victim=victim, inner=f"{outer}/sub/deep", outer=outer))
        untouched(r, outer, "the next launch")
        assert dropped.format(app=f"Nest{n}", folder=proj / "sub" / "deep", now=env.home / victim) in r.stderr, r.stderr
        assert (proj / "out.txt").read_text() == "out\n"                                            # the folder above is still the app's
        # ...and AppKata writing the launcher again (its next start does) doesn't take the link for the folder
        lp = env.app(f"nest{n}", gs)
        assert f"# Refused folder grant ~/{outer}/sub/deep: " in open(lp).read()
        assert [c for c in sb.summary(gs, str(env.home / "apps")) if c.startswith(f"~/{outer}/sub/deep · refused: ")]
        untouched(env.run(lp, look.format(victim=victim, inner=f"{outer}/sub/deep", outer=outer)), outer, "written again")

    # a nested folder that wasn't there when the launcher was written, made as a link since
    proj = env.home / "P4"
    proj.mkdir()
    gs = sb.apply_overrides(sb.resolve_template("standard"), {"folders": {"+" + str(proj): "rw", "+" + str(proj / "later" / "deep"): "rw"}})
    lp = env.app("nest4", gs)
    r = env.run(lp, 'mkdir -p "$HOME/.config/autostart" "$HOME/P4/later" && ln -s ../../.config/autostart "$HOME/P4/later/deep" && echo planted')
    assert "planted" in r.stdout and os.path.islink(proj / "later" / "deep"), (r.stdout, r.stderr)
    r = env.run(lp, look.format(victim=".config/autostart", inner="P4/later/deep", outer="P4"))
    untouched(r, "P4")
    assert dropped.format(app="Nest4", folder=proj / "later" / "deep", now=env.home / ".config/autostart") in r.stderr, r.stderr

    # a command-line tool with a folder of its own, run once in a folder above it (its to write), then elsewhere
    proj, other = env.home / "src5" / "proj", env.home / "src5" / "other"
    (proj / "data").mkdir(parents=True)
    other.mkdir()
    gs = sb.apply_overrides(sb.resolve_template("cli-tool"), {"folders": {"+" + str(proj / "data"): "ro"}})
    lp = env.app("tool5", gs)
    r = env.run(lp, 'mkdir -p "$HOME/.ssh" && mv data data.old && ln -s ../../.ssh data && echo planted', cwd=str(proj))
    assert "planted" in r.stdout and os.path.islink(proj / "data"), (r.stdout, r.stderr)
    r = env.run(lp, look.format(victim=".ssh", inner="src5/proj/data", outer="src5/other"), cwd=str(other))
    untouched(r, "the tool")
    assert dropped.format(app="Tool5", folder=proj / "data", now=env.home / ".ssh") in r.stderr, r.stderr

    # The user's own link is no plant: a grant through one stands (~/Docs kept on another disk). Pointed
    # elsewhere after the launcher was written, it is not given at that launch, and is again once
    # AppKata has written the launcher for where it leads now.
    for d in ("Documents", "Other"):
        (env.home / "disk" / d).mkdir(parents=True)
        (env.home / "disk" / d / "note.txt").write_text(d.upper() + "-NOTE\n")
    (env.home / "Docs").symlink_to(env.home / "disk" / "Documents")
    gs = sb.apply_overrides(sb.resolve_template("standard"), {"folders": {"+~/Docs": "rw"}})
    lp = env.app("reader", gs)
    r = env.run(lp, 'cat "$HOME/Docs/note.txt"; echo mine > "$HOME/Docs/mine.txt"')
    assert r.returncode == 0 and "DOCUMENTS-NOTE" in r.stdout and "isn't given" not in r.stderr, (r.stdout, r.stderr)
    assert (env.home / "disk" / "Documents" / "mine.txt").read_text() == "mine\n"
    (env.home / "Docs").unlink()
    (env.home / "Docs").symlink_to(env.home / "disk" / "Other")
    r = env.run(lp, 'cat "$HOME/Docs/note.txt" 2>&1; echo RAN-AGAIN')
    assert r.returncode == 0 and "RAN-AGAIN" in r.stdout and "-NOTE" not in r.stdout, (r.stdout, r.stderr)
    assert (f"Reader runs sandboxed and isn't given {env.home}/Docs this time: it led to {env.home}/disk/Documents when AppKata wrote this "
            f"launcher and leads to {env.home}/disk/Other now") in r.stderr, r.stderr
    r = env.run(env.app("reader", gs), 'cat "$HOME/Docs/note.txt"')
    assert r.returncode == 0 and "OTHER-NOTE" in r.stdout and "isn't given" not in r.stderr, (r.stdout, r.stderr)


def test_a_launcher_rewritten_while_the_app_runs_still_tears_down_and_reports_its_status(env):
    # Round five, R5-3: AppKata rewrites a launcher while the app runs (Save in the Sandbox dialog, an
    # update, the startup pass after an upgrade). The running shell has yet to read its teardown; the
    # rewrite must leave that shell its own text. The app sleeps, the launcher is regenerated with other
    # grants (a different, longer text) meanwhile, and the app then exits 7: the status must come out as
    # 7 and the proxy socket must be gone, which a shell that lost or misread its tail never manages.
    lp = env.app("live", sb.resolve_template("strict"))
    p = subprocess.Popen([lp, 'sleep 3; exit 7'], env=env.env, cwd=str(env.home),
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    subprocess.run(["sleep", "1"])
    env.app("live", sb.apply_overrides(sb.resolve_template("online-app"), {"folders": {"+~/Documents": "rw", "+~/Pictures": "ro"}}))
    out, err = p.communicate(timeout=30)
    assert p.returncode == 7, (out, err)
    assert not [f for f in os.listdir(env.rt / "appkata") if f.startswith("bus-")] if (env.rt / "appkata").exists() else True
    assert "xdg-dbus-proxy" in open(lp).read()               # the next launch gets the new text
    r = env.run(lp, 'echo "$DBUS_SESSION_BUS_ADDRESS"')
    assert r.returncode == 0 and "unix:path=" in r.stdout


def _stand_in_browser() -> bool:
    """Whether the first browser xdg-open's generic road tries is the harness's stand-in."""
    try:
        with open("/usr/bin/x-www-browser", errors="replace") as f:
            return "appkata-test-browser-ran" in f.read(4096)
    except OSError:
        return False


def test_a_strict_apps_xdg_open_fails_plainly_instead_of_starting_a_browser_inside(env):
    # Regression (round five, R5-4): a Strict app had no shim, so `xdg-open` was the desktop's own in
    # /usr, run inside the sandbox; under Cinnamon or GNOME it failed quietly, and under a desktop it
    # didn't know (XDG_CURRENT_DESKTOP unset, as sway from a TTY leaves it) its generic road started the
    # host's firefox *inside* the sandbox -- no network, an empty profile. The harness installs a
    # stand-in browser as root; the shim is now bound at every level and says why it can't.
    if not any(os.access(f"/usr/bin/{b}", os.X_OK) for b in ("x-www-browser", "firefox")):
        pytest.skip("needs a browser, or the stand-in (scripts/sandbox/register-test-handler.sh)")
    lp = env.app("vault", sb.resolve_template("strict"))
    env.env.pop("XDG_CURRENT_DESKTOP", None)
    r = env.run(lp, 'command -v xdg-open; xdg-open https://example.com/x; echo "exit $?"', env={"DISPLAY": ":0"})
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines() == ["/run/appkata/xdg-open", "exit 3"], (r.stdout, r.stderr)
    assert "runs Strict" in r.stderr and "firefox" not in r.stderr.lower()
    assert not os.path.exists(os.path.join(sb.sandbox_home("vault"), "appkata-test-browser-ran"))   # never inside
    # The desktop's own xdg-open, called by its full path, under Cinnamon (XDG_CURRENT_DESKTOP set as it
    # sets it): what a stock Mint user's app meets fails within the bound too, and starts nothing inside
    # (review 3, R3-35). Where the host has xdg-utils at all: the Ubuntu cloud image of tier 3 does not.
    if os.path.exists("/usr/bin/xdg-open"):
        r = env.run(lp, 'timeout 10 /usr/bin/xdg-open https://example.com/x; echo "exit $?"',
                    env={"DISPLAY": ":0", "XDG_CURRENT_DESKTOP": "X-Cinnamon"}, timeout=30)
        assert r.stdout.split()[-1] not in ("exit", "0", "124") and r.stderr.strip(), (r.stdout, r.stderr)
        assert not os.path.exists(os.path.join(sb.sandbox_home("vault"), "appkata-test-browser-ran"))


def test_the_road_the_shim_covers_still_starts_the_first_browser_inside(env):
    # R5-4's remainder: the desktop's own xdg-open, called by its full path under a desktop it doesn't
    # know (XDG_CURRENT_DESKTOP unset, as sway from a TTY leaves it), runs the first browser on PATH,
    # inside the sandbox. Shown with the stand-in only: a real one (Mint's Firefox) starts, and the run
    # waits on it (review 3, R3-35). The stand-in is x-www-browser, the first name the road tries, which
    # Mint's Firefox doesn't provide; a host whose x-www-browser is a real browser skips.
    if not os.path.exists("/usr/bin/xdg-open") or not _stand_in_browser():
        pytest.skip("needs the stand-in x-www-browser, which register-test-handler.sh installs only where there's none")
    lp = env.app("vault", sb.resolve_template("strict"))
    env.env.pop("XDG_CURRENT_DESKTOP", None)
    r = env.run(lp, '/usr/bin/xdg-open https://example.com/x >/dev/null 2>&1; cat "$HOME/appkata-test-browser-ran" 2>/dev/null; true',
                env={"DISPLAY": ":0"})
    assert "browser ran inside" in r.stdout, (r.stdout, r.stderr)             # the road the shim now shadows


# ---------------------------------------------------------------- AppKata acting while the app runs (round five)

@pytest.mark.parametrize("operation", ["switch-to-off", "uninstall-keeping-the-home", "uninstall-removing-the-home", "heal"])
def test_appkata_can_act_on_an_app_while_it_runs_and_the_run_still_ends_cleanly(env, operation):
    # Round five's class behind R5-3: every run test started a launcher and waited for it; nothing
    # changed AppKata's side of the app mid-run, which is where a sandbox change, an update, a switch
    # to Off, an uninstall and the startup pass all act. Each operation here is what the backend does
    # on disk (install._sandbox_launcher at Off, install.uninstall, the heal pass) while the app
    # sleeps; the run must still end with the app's own status and leave no socket behind, whatever
    # happened to the files meanwhile.
    gs = sb.resolve_template("online-app")
    lp = env.app("live", gs)
    p = subprocess.Popen([lp, 'sleep 3; echo "still here, home=$(ls -d "$HOME" 2>/dev/null)"; exit 7'], env=env.env,
                         cwd=str(env.home), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    subprocess.run(["sleep", "1"])
    if operation == "switch-to-off":
        os.remove(lp)
        sb.remove_identity("live")
    elif operation == "uninstall-keeping-the-home":
        os.remove(lp)
        sb.remove_identity("live")
        shutil.rmtree(env.home / "apps" / "live")
    elif operation == "uninstall-removing-the-home":
        os.remove(lp)
        shutil.rmtree(env.home / "apps" / "live")
        sb.remove_sandbox_home("live")
    else:
        env.app("live", sb.apply_overrides(gs, {"folders": {"+~/Documents": "rw"}}))
    out, err = p.communicate(timeout=30)
    assert p.returncode == 7, (out, err)
    assert "still here" in out, (out, err)
    assert not [f for f in os.listdir(env.rt / "appkata") if f.startswith("bus-")]


# ---------------------------------------------------------------- the Strict counterpart (round five)

def test_a_strict_app_fails_fast_on_every_desktop_road_and_never_falls_back_inside(env):
    # Round five's class behind R5-4: every link, file, portal and notification test ran at Standard,
    # and Strict was tested only for what it withholds, never for what the app then does instead.
    # Each road a Standard app has to the host is tried here from a Strict app: it must fail within
    # a bound (no hang), say so on stderr, and never fall back into the host's own programs in /usr
    # (the browser, the editor) running inside the sandbox.
    lp = env.app("vault", sb.resolve_template("strict"))
    (env.home / "Documents").mkdir(exist_ok=True)
    env.env.pop("XDG_CURRENT_DESKTOP", None)
    roads = [("xdg-open link", 'xdg-open https://example.com/x'),
             ("xdg-open file", 'echo x > "$HOME/n.txt"; xdg-open "$HOME/n.txt"'),
             ("gio open link", 'gio open https://example.com/x'),
             ("gio open file", 'gio open "$HOME/n.txt"'),
             ("gio launch", 'gio launch /usr/share/applications/appkata-test-handler.desktop'),
             ("notification portal", 'gdbus call --session --dest org.freedesktop.portal.Desktop --object-path /org/freedesktop/portal/desktop '
                                     '--method org.freedesktop.portal.Notification.AddNotification n "{}"'),
             ("notify-send", 'if command -v notify-send >/dev/null; then notify-send hello; else exit 9; fi'),
             ("secrets", 'gdbus call --session --dest org.freedesktop.secrets --object-path /org/freedesktop/secrets --method org.freedesktop.DBus.Peer.Ping')]
    snippet = "; ".join(f'start=$(date +%s); timeout 10 sh -c {shlex.quote(cmd)} >/dev/null 2>"$HOME/{i}.err"; '
                        f'echo "ROAD {i} exit=$? took=$(( $(date +%s) - start ))"' for i, (_, cmd) in enumerate(roads))
    r = env.run(lp, snippet, env={"DISPLAY": ":0"}, timeout=120)
    assert r.returncode == 0, r.stderr
    lines = {int(l.split()[1]): l for l in r.stdout.splitlines() if l.startswith("ROAD ")}
    home = sb.sandbox_home("vault")
    for i, (name, _) in enumerate(roads):
        line = lines[i]
        code = int(line.split("exit=")[1].split()[0]); took = int(line.split("took=")[1])
        if code == 9:
            continue                                                     # the tool is not on this host
        assert code not in (0, 124), f"{name}: {line}"                   # failed, and not by the timeout
        assert took < 8, f"{name}: hung: {line}"
        err = open(os.path.join(home, f"{i}.err")).read()
        assert err.strip(), f"{name}: failed with nothing on stderr"
    for marker in ("appkata-test-handler-ran", "appkata-test-browser-ran"):
        assert not os.path.exists(os.path.join(home, marker)), marker        # nothing ran inside instead
    assert "runs Strict" in open(os.path.join(home, "0.err")).read()         # the shim's own line (R5-4)



# ---------------------------------------------------------------- the unknown input (round five)
# In this file, not tests/test_sandbox.py: the expectation comes from the platform, and the platform
# the sandbox targets is the tier-2 container's (Mint 22.1), whose skel sources ~/.bash_aliases.

def _sourced_by(rc_text: str) -> list[str]:
    """The home-relative files a shell rc file sources: `. ~/x`, `source ~/x`, `for f in ~/d/*`."""
    import re
    out = []
    for m in re.finditer(r"(?:^|[;\s])(?:\.|source)\s+(?:\"?)(~|\$HOME)/([^\s\"';]+)", rc_text, re.M):
        out.append("~/" + m.group(2))
    for m in re.finditer(r"for\s+\w+\s+in\s+(?:\"?)(~|\$HOME)/([^\s\"'/]+)/\*", rc_text):
        out.append("~/" + m.group(2))
    return sorted(set(out))


def test_every_file_the_distributions_default_bashrc_sources_is_refused():
    # Round five's class behind R5-1 and R5-2: a list tested on its members, with "allowed" as the
    # answer for a non-member. The expectation here comes from the platform, not from the list: the
    # files the host's default .bashrc (what a new user gets) sources in turn -- ~/.bash_aliases on
    # Ubuntu and Mint, ~/.bashrc.d/* on Fedora -- must each be refused, since a line appended to one
    # runs in every new terminal exactly as one in ~/.bashrc. On a host whose skel sources nothing the
    # test says so and passes; in the Mint container it finds ~/.bash_aliases.
    _what_the_desktops_own_programs_load_from_the_home_is_refused()      # CR1.5-9: the same question of other programs
    found = []
    for rc in ("/etc/skel/.bashrc", "/etc/bash.bashrc", "/etc/bashrc", "/etc/skel/.profile", "/etc/skel/.zshrc"):
        if os.path.exists(rc):
            found += _sourced_by(open(rc, errors="replace").read())
    found = sorted(set(found))
    assert _sourced_by("if [ -f ~/.bash_aliases ]; then\n    . ~/.bash_aliases\nfi\n"
                       'for rc in ~/.bashrc.d/*; do\n  if [ -f "$rc" ]; then . "$rc"; fi\ndone\n') == ["~/.bash_aliases", "~/.bashrc.d"]
    for path in found:
        assert sb.protected_folder(path), f"{path} is sourced by the host's default shell files and would be shared"
    if not found:
        pytest.skip("this host's default shell files source nothing under the home")


# CR1.5-9 (#384): the same class a round later. The list had GNOME's and KDE's extension folders and
# not Cinnamon's, the shell's startup files and not bash-completion's. So these expectations too come
# from the platform: what the programs installed here name, in their own files, as the places in the
# home they load code from. Where a program isn't installed its part finds nothing (the launcher
# containers have neither Cinnamon nor bash-completion; the desktop images have Cinnamon and
# im-config, and a stock Mint or Ubuntu all three), so each reader is first held to the lines of the
# versions it was written from, quoted here. It is a part of the test above, not one of its own:
# tests/skips/tier1.txt names every test of this file, and is another unit's.

def _home_path(expr: str) -> str:
    """A shell word that names a place in the home, as `~/...`: `$HOME/.x`, `~/.x`,
    `${XDG_DATA_HOME:-$HOME/.local/share}/x` (the place the variable has when it is unset)."""
    import re
    return re.sub(r"\$\{XDG_\w+_HOME:-([^}]+)\}", r"\1", expr).replace("$HOME", "~").rstrip("/")


def _bash_completion_loads(text: str) -> list[str]:
    """The places in the home bash-completion's own script, or its profile script, reads code from:
    the user file it sources, the folder it loads a command's completion from at a tab, and a file
    under the user's configuration folder it sources."""
    import re
    out = [m.group(1) for m in re.finditer(r"BASH_COMPLETION_USER_FILE:-([^}\s]+)\}", text)]
    out += [m.group(1) for m in re.finditer(r"(\$\{XDG_DATA_HOME:-[^}]+\}/bash-completion)", text)]
    out += [m.group(1) for m in re.finditer(r"^\s*\.\s+\"?((?:\$\{XDG_\w+_HOME:-[^}]+\}|\$HOME|~)/[^\s\"]+)", text, re.M)]
    return sorted({_home_path(p) for p in out})


def _cinnamon_loads(main_js: str, launchers_js: str) -> list[str]:
    """The places in the home Cinnamon's shell imports code from (the folders of its user data
    folder that main.js puts on the importer's path) and the folders its panel-launchers applet
    reads launchers from."""
    import re
    out = []
    if "imports.searchPath.unshift(global.userdatadir)" in main_js:
        for m in re.finditer(r"let types = \[([^\]]+)\]", main_js):
            out += ["~/.local/share/cinnamon/" + t for t in re.findall(r"'([^']+)'", m.group(1))]
    for m in re.finditer(r"GLib\.get_user_data_dir\(\)\s*\+\s*[\"']([^\"']+)[\"']", launchers_js):
        out.append("~/.local/share" + m.group(1).rstrip("/"))
    for m in re.finditer(r"GLib\.get_home_dir\(\)\s*\+\s*[\"']([^\"']+)[\"']", launchers_js):
        out.append("~" + m.group(1).rstrip("/"))
    return sorted(set(out))


def _read(path: str) -> str:
    try:
        with open(path, errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def _loaded_from_the_home() -> dict[str, str]:
    """{a place in the home: the program here that loads code from it}, by this system's own files."""
    found = {}
    for script in ("/usr/share/bash-completion/bash_completion", "/etc/bash_completion", "/etc/profile.d/bash_completion.sh"):
        for path in _bash_completion_loads(_read(script)):
            found[path] = script
    cinnamon = "/usr/share/cinnamon"
    for path in _cinnamon_loads(_read(f"{cinnamon}/js/ui/main.js"), _read(f"{cinnamon}/applets/panel-launchers@cinnamon.org/applet.js")):
        found[path] = cinnamon
    for line in _read("/usr/share/im-config/xinputrc.common").splitlines():     # the file im-config's Xsession hook sources
        if line.startswith("IM_CONFIG_XINPUTRC_USR="):
            found[_home_path(line.split("=", 1)[1].strip().strip('"'))] = "im-config"
    return found


def _what_the_desktops_own_programs_load_from_the_home_is_refused():
    # the readers, on the lines they were written from: bash-completion 2.11 (Mint 22.3, Ubuntu 24.04)
    # and 2.16 (LMDE 7), Cinnamon 6.6.9's js/ui/main.js and its panel-launchers applet, im-config 0.57
    assert _bash_completion_loads(
        '    local -a dirs=(${BASH_COMPLETION_USER_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/bash-completion}/completions)\n'
        'user_completion=${BASH_COMPLETION_USER_FILE:-~/.bash_completion}\n'
        '    local user_file=${BASH_COMPLETION_USER_FILE:-~/.bash_completion}\n'
        '        dirs=("${XDG_DATA_HOME:-$HOME/.local/share}/bash-completion/completions")\n'
        '        [ -r "${XDG_CONFIG_HOME:-$HOME/.config}/bash_completion" ] &&\n'
        '            . "${XDG_CONFIG_HOME:-$HOME/.config}/bash_completion"\n'
        '        relative_include_base="$HOME/.ssh"\n            . /usr/share/bash-completion/bash_completion\n') == [
            "~/.bash_completion", "~/.config/bash_completion", "~/.local/share/bash-completion"]
    assert _cinnamon_loads(
        "    imports.searchPath.unshift(global.datadir);\n    imports.searchPath.unshift(global.userdatadir);\n"
        "    let types = ['applets', 'desklets', 'extensions', 'search_providers'];\n",
        'const CUSTOM_LAUNCHERS_PATH = GLib.get_user_data_dir() + "/cinnamon/panel-launchers/";\n'
        "const OLD_CUSTOM_LAUNCHERS_PATH = GLib.get_home_dir() + '/.cinnamon/panel-launchers/';\n") == [
            "~/.cinnamon/panel-launchers", "~/.local/share/cinnamon/applets", "~/.local/share/cinnamon/desklets",
            "~/.local/share/cinnamon/extensions", "~/.local/share/cinnamon/panel-launchers", "~/.local/share/cinnamon/search_providers"]
    assert [_home_path(w) for w in ("$HOME/.xinputrc", "~/.x/", "${XDG_CONFIG_HOME:-$HOME/.config}/y")] == ["~/.xinputrc", "~/.x", "~/.config/y"]
    # ...and what this system's own copies name
    for path, where in sorted(_loaded_from_the_home().items()):
        assert path.startswith("~/") and sb.protected_folder(path), f"{where} loads {path}, which would be shared"


# ---------------------------------------------------------------- a degraded host (round five)

def test_a_missing_runtime_dir_refuses_the_launch_with_a_message(env):
    # Round five's "degraded host" category: the tiers assume a healthy host. Started with no logind
    # session (ssh without a session, cron, a container), $XDG_RUNTIME_DIR names a folder the user
    # can't create under /run/user; the header's `mkdir -p` fails under `set -e`. The launch must stop
    # with a line that says what is missing, never silently or with bwrap's own confusion.
    lp = env.app("plain", sb.resolve_template("strict"))
    r = env.run(lp, "echo RAN", env={"XDG_RUNTIME_DIR": "/proc/no-such-runtime-dir"})
    assert r.returncode != 0 and "RAN" not in r.stdout, (r.stdout, r.stderr)
    assert "no-such-runtime-dir" in r.stderr and "AppKata" in r.stderr, r.stderr
    assert "bwrap" not in r.stderr.lower(), r.stderr                    # refused before bwrap, with the reason


@needs_proxy
def test_a_document_portal_that_never_answers_only_delays_the_launch_and_passes_the_arguments_through(env, tmp_path):
    # The forward helper calls the document portal with a timeout (List, what the app holds, before
    # the first Add: CR1.5-52); a document portal that hangs (a stuck FUSE mount) must cost that
    # timeout and nothing more -- the launch goes on with the arguments as they were (R17.6.2), the
    # app runs, the status comes out.
    import time
    (env.home / "Documents").mkdir()
    (env.home / "Documents" / "n.txt").write_text("x\n")
    bus = _Bus(env)
    stuck = subprocess.Popen(["python3", "-c", _STUCK_DOCUMENTS], env={**env.env, "DBUS_SESSION_BUS_ADDRESS": bus.addr},
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(50):
            r = subprocess.run(["sh", "-c", "gdbus call --session --dest org.freedesktop.DBus --object-path /org/freedesktop/DBus "
                                "--method org.freedesktop.DBus.NameHasOwner org.freedesktop.portal.Documents"],
                               env={**env.env, "DBUS_SESSION_BUS_ADDRESS": bus.addr}, capture_output=True, text=True)
            if r.stdout.strip() == "(true,)":
                break
            subprocess.run(["sleep", "0.1"])
        lp = env.app("editor", sb.resolve_template("online-app"))
        start = time.monotonic()
        r = subprocess.run([lp, 'shift; printf "ARG %s\\n" "$@"; exit 3', str(env.home / "Documents" / "n.txt")],
                           cwd=str(env.home), env={**env.env, "DBUS_SESSION_BUS_ADDRESS": bus.addr},
                           capture_output=True, text=True, timeout=90)
        took = time.monotonic() - start
    finally:
        stuck.terminate()
        bus.close()
    assert r.returncode == 3, (r.stdout, r.stderr)
    assert f"ARG {env.home}/Documents/n.txt" in r.stdout                  # passed through unchanged
    assert took < 30, took                                                # the helper's timeout, not a hang


_STUCK_DOCUMENTS = """
from gi.repository import Gio, GLib
XML = '''<node><interface name="org.freedesktop.portal.Documents">
<method name="Add"><arg type="h" direction="in"/><arg type="b" direction="in"/><arg type="b" direction="in"/><arg type="s" direction="out"/></method>
<method name="GetMountPoint"><arg type="ay" direction="out"/></method>
<method name="List"><arg type="s" direction="in"/><arg type="a{say}" direction="out"/></method>
</interface></node>'''
def call(conn, sender, path, iface, method, params, inv):
    pass                                                        # never answers: the caller's timeout is all it gets
bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
bus.register_object("/org/freedesktop/portal/documents", Gio.DBusNodeInfo.new_for_xml(XML).interfaces[0], call, None, None)
Gio.bus_own_name_on_connection(bus, "org.freedesktop.portal.Documents", Gio.BusNameOwnerFlags.NONE, None, None)
GLib.MainLoop().run()
"""


@needs_proxy
def test_the_proxy_dying_mid_run_fails_the_apps_bus_calls_but_not_its_run(env):
    # xdg-dbus-proxy killed (or crashing) while the app runs: the app's later bus calls fail at once
    # rather than hanging, the app keeps running, its status comes out, and the teardown is clean.
    import time
    bus = _Bus(env)
    try:
        lp = env.app("web", sb.resolve_template("online-app"))
        p = subprocess.Popen([lp, 'gdbus call --session --dest org.freedesktop.DBus --object-path /org/freedesktop/DBus '
                                  '--method org.freedesktop.DBus.GetId >/dev/null && echo BUS-OK; sleep 3; '
                                  'start=$(date +%s); timeout 10 gdbus call --session --dest org.freedesktop.DBus '
                                  '--object-path /org/freedesktop/DBus --method org.freedesktop.DBus.GetId >/dev/null 2>&1; '
                                  'echo "LATER exit=$? took=$(( $(date +%s) - start ))"; exit 5'],
                             env={**env.env, "DBUS_SESSION_BUS_ADDRESS": bus.addr}, cwd=str(env.home),
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        time.sleep(1.5)
        subprocess.run(["pkill", "-f", f"xdg-dbus-proxy {bus.addr}"], stdout=subprocess.DEVNULL)
        out, err = p.communicate(timeout=60)
    finally:
        bus.close()
    assert p.returncode == 5, (out, err)
    assert "BUS-OK" in out, (out, err)
    later = next(l for l in out.splitlines() if l.startswith("LATER "))
    assert "exit=0" not in later and "exit=124" not in later and int(later.split("took=")[1]) < 8, later
    assert not [f for f in os.listdir(env.rt / "appkata") if f.startswith("bus-")]


def test_an_appimage_whose_runtime_unpacks_nothing_is_refused_with_a_message(env):
    # A runtime that doesn't honour --appimage-extract (a type-1 AppImage, a broken download): the
    # launcher must say so and exit, not run a missing AppRun or loop on extraction.
    (env.home / "apps" / "img").mkdir(parents=True)
    img = env.home / "apps" / "img" / "Img.AppImage"
    img.write_text('#!/bin/sh\necho "this runtime knows no --appimage-extract"\nexit 1\n')
    img.chmod(0o755)
    lp = _appimage_app(env, img)
    r = env.run(lp, "", timeout=60)
    assert r.returncode == 1 and "couldn't unpack it (exit 1)" in r.stderr and "AppKata" in r.stderr, (r.stdout, r.stderr)
    assert not os.path.exists(sb.extracted_dir(str(env.home / "apps" / "img"), "1.0"))
    assert not [p for p in os.listdir(env.home / "apps" / "img") if ".new." in p]     # no staging dir left


# ---------------------------------------------------------------- the field test, moved indoors (round six)

@pytest.mark.parametrize("write_app", [False, True])
def test_a_self_updating_app_can_change_its_folder_only_with_the_writable_grant(env, write_app):
    # "A self-updating app" was on the physical-desktop checklist since the PR's first version;
    # what it needs is a run, not a desktop. The app writes into its own version folder (what a
    # self-updater does): read-only without the grant (R17.4: EROFS, the app sees why), writable with
    # it (R17.7.1) -- and the files are the real ones, so the change is there at the next launch.
    gs = sb.resolve_template("online-app")
    gs["write_app"] = write_app
    lp = env.app("upd", gs)
    appdir = env.home / "apps" / "upd" / "1.0"
    r = env.run(lp, 'd=$(dirname "$0"); (echo "v2" > "$d/../VERSION") 2>&1 && echo WROTE || echo "DENIED $?"; cat "$d/../VERSION" 2>/dev/null; true')
    assert r.returncode == 0, r.stderr
    if write_app:
        assert "WROTE" in r.stdout and (appdir / "VERSION").read_text() == "v2\n", (r.stdout, r.stderr)
        r2 = env.run(lp, 'cat "$(dirname "$0")/../VERSION"')
        assert r2.stdout.strip() == "v2"                                  # the real folder changed, for good
    else:
        assert "DENIED" in r.stdout and "Read-only file system" in r.stdout and not (appdir / "VERSION").exists(), (r.stdout, r.stderr)


def test_a_self_updating_appimage_can_change_its_unpacked_copy_but_never_the_appimage_itself(env):
    # R17.7: the .AppImage is canonical and the extracted folder a derived cache. With the writable
    # grant the app changes its unpacked copy (and keeps it: the stamp is the .AppImage's, unchanged),
    # but the .AppImage file is bound read-only whatever the grant says -- AppKata's own update is
    # what replaces it (R17.12).
    (env.home / "apps" / "img").mkdir(parents=True)
    img = env.home / "apps" / "img" / "Img.AppImage"
    _fake_appimage(img, "v1")
    gs = sb.resolve_template("online-app")
    gs["write_app"] = True
    target = env.home / "apps" / "img"
    lp = sb.write_launcher("img", "Img", str(env.home / "apps"), sb.extracted_dir(str(target), "1.0"), "AppRun", gs, str(img))
    r = env.run(lp, "")
    assert r.stdout.strip() == "v1", (r.stdout, r.stderr)
    # the app "updates" its unpacked AppRun (the launcher passes the snippet as $1; AppRun ignores it, so run a shell app instead)
    extracted = sb.extracted_dir(str(target), "1.0")
    r = subprocess.run(["sh", "-c", f'exec "{lp}"'], env=env.env, capture_output=True, text=True, timeout=30)
    text = open(lp).read()
    assert '--bind "$home" "$HOME" --bind "$appdir" "$appdir"' in text and '--ro-bind-try "$img" "$img"' in text
    # from inside: write to the unpacked folder (allowed) and to the .AppImage (refused)
    probe = sb.write_launcher("img", "Img", str(env.home / "apps"), extracted, "AppRun", gs, str(img))
    with open(os.path.join(extracted, "AppRun"), "w") as f:
        f.write('#!/bin/sh\n(printf "#!/bin/sh\\necho v2\\n" > "$APPDIR/AppRun") && echo UPDATED-COPY; '
                '(echo x >> "$APPIMAGE") 2>&1 && echo WROTE-APPIMAGE || echo "APPIMAGE-DENIED"\n')
    r = env.run(probe, "")
    assert "UPDATED-COPY" in r.stdout and "APPIMAGE-DENIED" in r.stdout and "WROTE-APPIMAGE" not in r.stdout, (r.stdout, r.stderr)
    assert env.run(probe, "").stdout.strip() == "v2"                      # the changed copy is what runs next
    assert img.read_text().startswith("#!/bin/sh\n[ \"$1\" = --appimage-extract ]")   # the .AppImage untouched


_WATCHER = """
import sys
from gi.repository import Gio, GLib
XML = '''<node><interface name="org.kde.StatusNotifierWatcher">
<method name="RegisterStatusNotifierItem"><arg type="s" direction="in"/></method>
<method name="RegisterStatusNotifierHost"><arg type="s" direction="in"/></method>
<property name="RegisteredStatusNotifierItems" type="as" access="read"/>
<property name="IsStatusNotifierHostRegistered" type="b" access="read"/>
<property name="ProtocolVersion" type="i" access="read"/>
<signal name="StatusNotifierItemRegistered"><arg type="s"/></signal>
</interface></node>'''
log = open(sys.argv[1], "a"); items = []
def call(conn, sender, path, iface, method, params, inv):
    if method == "RegisterStatusNotifierItem":
        name = params.unpack()[0]
        service = sender if name.startswith("/") else name
        items.append(service); log.write(f"REGISTERED {name} from {sender}\\n"); log.flush()
        inv.return_value(None)                  # answer first: the item is blocked waiting for it
        # a real watcher's host then talks to the item: read its Title through the proxy, back into the sandbox
        def ask():
            try:
                title = conn.call_sync(service, "/StatusNotifierItem", "org.freedesktop.DBus.Properties", "Get",
                                       GLib.Variant("(ss)", ("org.kde.StatusNotifierItem", "Title")), None, Gio.DBusCallFlags.NONE, 5000, None)
                log.write(f"TITLE {title.unpack()[0]}\\n")
            except Exception as e:
                log.write(f"TITLE-FAILED {e}\\n")
            log.flush()
        GLib.timeout_add(200, ask)
    else:
        inv.return_value(None)
def get(conn, sender, path, iface, prop):
    return {"RegisteredStatusNotifierItems": GLib.Variant("as", items), "IsStatusNotifierHostRegistered": GLib.Variant("b", True),
            "ProtocolVersion": GLib.Variant("i", 0)}[prop]
bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
bus.register_object("/StatusNotifierWatcher", Gio.DBusNodeInfo.new_for_xml(XML).interfaces[0], call, get, None)
Gio.bus_own_name_on_connection(bus, "org.kde.StatusNotifierWatcher", Gio.BusNameOwnerFlags.NONE, None, None)
GLib.MainLoop().run()
"""

_ITEM = """
import sys
from gi.repository import Gio, GLib
XML = '''<node><interface name="org.kde.StatusNotifierItem">
<property name="Title" type="s" access="read"/><property name="Id" type="s" access="read"/><property name="Status" type="s" access="read"/>
<method name="Activate"><arg type="i" direction="in"/><arg type="i" direction="in"/></method>
</interface></node>'''
bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
bus.register_object("/StatusNotifierItem", Gio.DBusNodeInfo.new_for_xml(XML).interfaces[0], lambda *a: a[-1].return_value(None),
                    lambda c, s, p, i, prop: GLib.Variant("s", {"Title": "AppKata tray probe", "Id": "probe", "Status": "Active"}[prop]), None)
name = "org.kde.StatusNotifierItem-%d-1" % __import__("os").getpid()
Gio.bus_own_name_on_connection(bus, name, Gio.BusNameOwnerFlags.NONE, None, None)
bus.call_sync("org.kde.StatusNotifierWatcher", "/StatusNotifierWatcher", "org.kde.StatusNotifierWatcher", "RegisterStatusNotifierItem",
              GLib.Variant("(s)", (name,)), None, Gio.DBusCallFlags.NONE, 5000, None)
print("REGISTERED-AS", name, flush=True)
GLib.timeout_add(1500, lambda: sys.exit(0))
GLib.MainLoop().run()
"""


@needs_proxy
def test_a_tray_icon_registers_with_a_watcher_which_can_talk_back_to_it(env, tmp_path):
    # "A tray icon with a real StatusNotifierWatcher" was on the physical-desktop checklist. The
    # protocol is two-way: the app registers its item name with the watcher, and the desktop's host
    # then calls into the item on that name -- through the proxy, back into the sandbox, which only
    # an --own name allows. A watcher stand-in on the test bus does both; the tier-2 tray test only
    # ever checked that the app could own the name.
    if subprocess.run(["python3", "-c", "import gi"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode:
        pytest.skip("needs python3-gi")
    bus = _Bus(env)
    log = tmp_path / "watcher.log"
    watcher = subprocess.Popen(["python3", "-c", _WATCHER, str(log)], env={**env.env, "DBUS_SESSION_BUS_ADDRESS": bus.addr},
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(50):
            r = subprocess.run(["sh", "-c", "gdbus call --session --dest org.freedesktop.DBus --object-path /org/freedesktop/DBus "
                                "--method org.freedesktop.DBus.NameHasOwner org.kde.StatusNotifierWatcher"],
                               env={**env.env, "DBUS_SESSION_BUS_ADDRESS": bus.addr}, capture_output=True, text=True)
            if r.stdout.strip() == "(true,)":
                break
            subprocess.run(["sleep", "0.1"])
        for name in ("tray", "notray"):                     # each app sees only its own folder
            d = env.home / "apps" / name / "1.0" / "bin"
            d.mkdir(parents=True, exist_ok=True)
            (d / "item.py").write_text(_ITEM)
        item = str(env.home / "apps" / "tray" / "1.0" / "bin" / "item.py")
        # the real program exec'd straight from the app (pid 2), and one started after a command
        # substitution forked first (pid 4) -- what an AppRun script that computes a path does; the
        # proxy owns the names for a range of pids (round six, R6-3: it covered 2 and 3 only)
        r = env.run(env.app("tray", sb.resolve_template("messenger")), f'exec python3 {item}', env={"DBUS_SESSION_BUS_ADDRESS": bus.addr}, timeout=60)
        rf = env.run(env.app("tray", sb.resolve_template("messenger")), 'd=$(dirname "$0"); python3 "$d/item.py"', env={"DBUS_SESSION_BUS_ADDRESS": bus.addr}, timeout=60)
        r2 = env.run(env.app("notray", sb.resolve_template("online-app")), 'python3 "$(dirname "$0")/item.py" 2>&1 | tail -1',
                     env={"DBUS_SESSION_BUS_ADDRESS": bus.addr}, timeout=60)
    finally:
        watcher.terminate()
        bus.close()
    assert r.returncode == 0 and "REGISTERED-AS org.kde.StatusNotifierItem-2-1" in r.stdout, (r.stdout, r.stderr)   # pid 2 in its namespace
    assert rf.returncode == 0 and "REGISTERED-AS org.kde.StatusNotifierItem-4-1" in rf.stdout, (rf.stdout, rf.stderr)   # forked first: pid 4
    seen = log.read_text()
    for name in ("org.kde.StatusNotifierItem-2-1", "org.kde.StatusNotifierItem-4-1"):
        assert f"REGISTERED {name}" in seen, seen
    assert seen.count("TITLE AppKata tray probe") == 2 and "TITLE-FAILED" not in seen, seen     # the host talked back, through the proxy, both times
    assert "REGISTERED-AS" not in r2.stdout and ("AccessDenied" in r2.stdout or "Error" in r2.stdout), r2.stdout   # no capability: no watcher, no name

# ---------------------------------------------------------------- disk full (round six, a leftover of the degraded host)

_TINY = "/home/kata/tiny"            # a 1 MB tmpfs the harness mounts as root before the tests


def test_an_appimage_that_does_not_fit_on_the_disk_is_refused_with_a_message_and_leaves_nothing(env):
    if not os.path.ismount(_TINY) or not os.access(_TINY, os.W_OK):
        pytest.skip("needs the 1 MB tmpfs the harness mounts (scripts/test-sandbox.sh launcher)")
    import shutil as sh
    target = os.path.join(_TINY, "apps", "big")
    os.makedirs(target, exist_ok=True)
    for f in os.listdir(target):
        p = os.path.join(target, f)
        sh.rmtree(p) if os.path.isdir(p) else os.remove(p)
    img = os.path.join(target, "Big.AppImage")
    # a runtime whose extraction writes 2 MB into squashfs-root: more than the tmpfs holds
    with open(img, "w") as f:
        f.write('#!/bin/sh\n[ "$1" = --appimage-extract ] && { mkdir -p squashfs-root && printf "#!/bin/sh\\necho big\\n" > squashfs-root/AppRun '
                '&& chmod +x squashfs-root/AppRun && dd if=/dev/zero of=squashfs-root/payload bs=1024 count=2048 2>/dev/null; exit $?; }\necho not-extracted\n')
    os.chmod(img, 0o755)
    lp = sb.write_launcher("big", "Big", os.path.join(_TINY, "apps"), sb.extracted_dir(target, "1.0"), "AppRun",
                           sb.resolve_template("strict"), img)
    r = env.run(lp, "", timeout=60)
    assert r.returncode == 1 and "AppKata" in r.stderr and "couldn't unpack" in r.stderr, (r.stdout, r.stderr)
    left = set(os.listdir(target)) - {"Big.AppImage", "run", "1.0.extracted.lock"}        # the flock file is the launcher's own
    assert not left, left                                                                  # no staging folder, no half-extracted cache


# ---------------------------------------------------------------- the UI table's inferred rows (round seven)

_MPRIS_APP = """
import sys
from gi.repository import Gio, GLib
XML = '''<node><interface name="org.mpris.MediaPlayer2.Player"><method name="Play"/><method name="Pause"/>
<property name="PlaybackStatus" type="s" access="read"/></interface></node>'''
calls = []
def call(conn, sender, path, iface, method, params, inv):
    calls.append(method); print("CALLED", method, "by", sender, flush=True); inv.return_value(None)
bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
bus.register_object("/org/mpris/MediaPlayer2", Gio.DBusNodeInfo.new_for_xml(XML).interfaces[0], call,
                    lambda *a: GLib.Variant("s", "Playing"), None)
Gio.bus_own_name_on_connection(bus, "org.mpris.MediaPlayer2.appkataprobe", Gio.BusNameOwnerFlags.NONE,
                               lambda *a: print("OWNED", flush=True), lambda *a: print("NOT-OWNED", flush=True))
def others():                       # what the app can do to another player on the bus (CR1.5-36)
    def ask(what, dest, path, iface, method, args=None):
        try:
            r = bus.call_sync(dest, path, iface, method, args, None, Gio.DBusCallFlags.NONE, 3000, None)
            print(what, "ANSWERED", *([r.unpack()[0]] if method == "RequestName" else []), flush=True)
        except GLib.Error as e:
            print(what, "REFUSED", Gio.DBusError.get_remote_error(e), flush=True)
    names = bus.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "ListNames", None, None, 0, 3000, None).unpack()[0]
    print("SEES", *sorted(n for n in names if n.startswith("org.mpris.")), flush=True)
    ask("OTHER-PLAYER", "org.mpris.MediaPlayer2.other", "/org/mpris/MediaPlayer2", "org.mpris.MediaPlayer2.Player", "Pause")
    ask("OTHER-OBJECT", "org.mpris.MediaPlayer2.other", "/org/appkata/Other", "org.appkata.Other", "Open", GLib.Variant("(s)", ("file:///etc/hostname",)))
    ask("OTHER-NAME", "org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "RequestName", GLib.Variant("(su)", ("org.mpris.MediaPlayer2.another", 4)))
GLib.timeout_add(1200, others)
GLib.timeout_add(2500, lambda: sys.exit(0))
GLib.MainLoop().run()
"""

# Another media player on the bus, as the user's own one is: its MPRIS object, and a second object
# of its own on the same connection that opens what it is sent.
_OTHER_PLAYER = """
import sys
from gi.repository import Gio, GLib
log = open(sys.argv[1], "a")
player = Gio.DBusNodeInfo.new_for_xml('<node><interface name="org.mpris.MediaPlayer2.Player"><method name="Play"/><method name="Pause"/>'
                                      '<property name="PlaybackStatus" type="s" access="read"/></interface></node>').interfaces[0]
own = Gio.DBusNodeInfo.new_for_xml('<node><interface name="org.appkata.Other"><method name="Open"><arg type="s" direction="in"/></method></interface></node>').interfaces[0]
def call(conn, sender, path, iface, method, params, inv):
    log.write(f"OTHER {method} {params.unpack()}\\n"); log.flush(); inv.return_value(None)
bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
bus.register_object("/org/mpris/MediaPlayer2", player, call, lambda *a: GLib.Variant("s", "Playing"), None)
bus.register_object("/org/appkata/Other", own, call, None, None)
Gio.bus_own_name_on_connection(bus, "org.mpris.MediaPlayer2.other", Gio.BusNameOwnerFlags.NONE, None, None)
GLib.MainLoop().run()
"""

_MEDIA_KEYS = """
import sys, time
from gi.repository import Gio, GLib
bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
log = open(sys.argv[1], "a")
def tick():
    names = bus.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "ListNames", None, None, 0, -1, None).unpack()[0]
    for n in [x for x in names if x.startswith("org.mpris.MediaPlayer2.")]:
        try:
            bus.call_sync(n, "/org/mpris/MediaPlayer2", "org.mpris.MediaPlayer2.Player", "Play", None, None, 0, 3000, None)
            st = bus.call_sync(n, "/org/mpris/MediaPlayer2", "org.freedesktop.DBus.Properties", "Get",
                               GLib.Variant("(ss)", ("org.mpris.MediaPlayer2.Player", "PlaybackStatus")), None, 0, 3000, None).unpack()[0]
            log.write(f"PLAYED {n} status={st}\\n"); log.flush()
        except Exception as e:
            log.write(f"FAILED {n} {e}\\n"); log.flush()
    return True
GLib.timeout_add(500, tick)
GLib.MainLoop().run()
"""


@needs_proxy
def test_a_media_key_daemon_can_drive_an_app_with_the_mpris_capability_and_only_that_app(env, tmp_path):
    # The UI says "Play/pause and track info on the keyboard and lock screen (MPRIS)"; until now only the
    # proxy rule was tested. A stand-in media-key daemon on the test bus finds the app's MPRIS name,
    # calls Play on it and reads its status back -- through the proxy, into the sandbox -- for the app
    # with the capability; the app without it can't even own the name.
    # CR1.5-36: that was the daemon calling the app, and never the app calling out. To the proxy a
    # name an app may own is one it may call, so `--own=org.mpris.MediaPlayer2.*` let the app call
    # every other player, and whatever else that player's connection serves. Another player is on
    # the bus now: the app whose review names its MPRIS name owns that one, is driven on it, and
    # neither sees nor reaches the other; the app nobody named still does (R17.17 says so).
    # PR #694's review, P1-3: an own is a talk on the named name too, so a named app reaches a
    # player that holds that same name (another copy of the player, the host's own): the last run.
    bus = _Bus(env)
    log, other_log, same_log = tmp_path / "keys.log", tmp_path / "other.log", tmp_path / "same.log"
    on_bus = {**env.env, "DBUS_SESSION_BUS_ADDRESS": bus.addr}
    daemon = subprocess.Popen(["python3", "-c", _MEDIA_KEYS, str(log)], env=on_bus, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    other = subprocess.Popen(["python3", "-c", _OTHER_PLAYER, str(other_log)], env=on_bus, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for name in ("named", "player", "noplayer", "samename"):
            d = env.home / "apps" / name / "1.0" / "bin"
            d.mkdir(parents=True, exist_ok=True)
            (d / "mpris.py").write_text(_MPRIS_APP)
        its_own = sb.apply_overrides(sb.resolve_template("media-player"), {"mpris_name": "org.mpris.MediaPlayer2.appkataprobe"})
        rn = env.run(env.app("named", its_own), 'python3 "$(dirname "$0")/mpris.py"', env={"DBUS_SESSION_BUS_ADDRESS": bus.addr}, timeout=60)
        reached_by_named = [l for l in other_log.read_text().splitlines() if "Pause" in l or "Open" in l]
        r = env.run(env.app("player", sb.resolve_template("media-player")), 'python3 "$(dirname "$0")/mpris.py"',
                    env={"DBUS_SESSION_BUS_ADDRESS": bus.addr}, timeout=60)
        r2 = env.run(env.app("noplayer", sb.resolve_template("online-app")), 'python3 "$(dirname "$0")/mpris.py"',
                     env={"DBUS_SESSION_BUS_ADDRESS": bus.addr}, timeout=60)
        # the host's own copy of the player holds the name a review gives the sandboxed one
        same = "org.mpris.MediaPlayer2.hostplayer"
        host = subprocess.Popen(["python3", "-c", _OTHER_PLAYER.replace("org.mpris.MediaPlayer2.other", same), str(same_log)], env=on_bus,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(50):
            if subprocess.run(["gdbus", "call", "--session", "--dest", "org.freedesktop.DBus", "--object-path", "/org/freedesktop/DBus", "--method",
                               "org.freedesktop.DBus.NameHasOwner", same], env=on_bus, capture_output=True, text=True).stdout.strip() == "(true,)":
                break
            time.sleep(0.1)
        (env.home / "apps" / "samename" / "1.0" / "bin" / "mpris.py").write_text(
            _MPRIS_APP.replace("org.mpris.MediaPlayer2.appkataprobe", same).replace("org.mpris.MediaPlayer2.other", same))
        rs = env.run(env.app("samename", sb.apply_overrides(sb.resolve_template("media-player"), {"mpris_name": same})),
                     'python3 "$(dirname "$0")/mpris.py"', env={"DBUS_SESSION_BUS_ADDRESS": bus.addr}, timeout=60)
        host.terminate()
    finally:
        daemon.terminate()
        other.terminate()
        bus.close()
    assert "OWNED" in r.stdout and "CALLED Play" in r.stdout, (r.stdout, r.stderr)
    assert log.read_text().count("PLAYED org.mpris.MediaPlayer2.appkataprobe status=Playing") >= 2      # the named app and the unnamed one
    assert "NOT-OWNED" in r2.stdout and "CALLED" not in r2.stdout, (r2.stdout, r2.stderr)
    # named: driven on its own name, and that is all of MPRIS it has
    out = rn.stdout.splitlines()
    assert "OWNED" in out and any(l.startswith("CALLED Play") for l in out), (rn.stdout, rn.stderr)
    assert "SEES org.mpris.MediaPlayer2.appkataprobe" in out, rn.stdout                  # not the other player
    assert "OTHER-PLAYER REFUSED org.freedesktop.DBus.Error.ServiceUnknown" in out and "OTHER-OBJECT REFUSED org.freedesktop.DBus.Error.ServiceUnknown" in out, rn.stdout
    assert "OTHER-NAME REFUSED org.freedesktop.DBus.Error.ServiceUnknown" in out, rn.stdout   # nor a second name of its own
    assert reached_by_named == [], reached_by_named
    # nobody named it: every player's name, so every player, and what else its connection serves
    out = r.stdout.splitlines()
    assert "SEES org.mpris.MediaPlayer2.appkataprobe org.mpris.MediaPlayer2.other" in out, r.stdout
    assert "OTHER-PLAYER ANSWERED" in out and "OTHER-OBJECT ANSWERED" in out and "OTHER-NAME ANSWERED 1" in out, r.stdout
    reached = other_log.read_text()
    assert "OTHER Pause ()" in reached and "OTHER Open ('file:///etc/hostname',)" in reached, reached
    assert "OTHER-PLAYER REFUSED" in r2.stdout and "OTHER-OBJECT REFUSED" in r2.stdout, r2.stdout    # no capability: no player at all
    # named, but another program holds that name: the app can't own it, and reaches that program,
    # its player and what else its connection serves (R17.5.1, R17.17)
    out = rs.stdout.splitlines()
    assert "OWNED" not in out and "OTHER-PLAYER ANSWERED" in out and "OTHER-OBJECT ANSWERED" in out, (rs.stdout, rs.stderr)
    reached = same_log.read_text()
    assert "OTHER Pause ()" in reached and "OTHER Open ('file:///etc/hostname',)" in reached, reached


# org.freedesktop.ScreenSaver as the desktops declare it: KDE's screen locker (kwin 6.3, ksmserver
# 5.27) serves every member, and Lock locks the screen; GNOME's and Cinnamon's screensaver proxies
# declare the same and answer all but the inhibit pair with NotSupported. The stand-in answers all.
_SCREENSAVER = """
import sys
from gi.repository import Gio, GLib
XML = '''<node><interface name="org.freedesktop.ScreenSaver"><method name="Lock"/><method name="SimulateUserActivity"/>
<method name="GetActive"><arg type="b" direction="out"/></method><method name="GetActiveTime"><arg type="u" direction="out"/></method>
<method name="GetSessionIdleTime"><arg type="u" direction="out"/></method><method name="SetActive"><arg type="b" direction="out"/><arg type="b" direction="in"/></method>
<method name="Inhibit"><arg type="s" direction="in"/><arg type="s" direction="in"/><arg type="u" direction="out"/></method>
<method name="UnInhibit"><arg type="u" direction="in"/></method>
<method name="Throttle"><arg type="s" direction="in"/><arg type="s" direction="in"/><arg type="u" direction="out"/></method>
<method name="UnThrottle"><arg type="u" direction="in"/></method><signal name="ActiveChanged"><arg type="b"/></signal></interface></node>'''
ANSWERS = {"Inhibit": "(u)", "Throttle": "(u)", "GetActive": "(b)", "SetActive": "(b)", "GetActiveTime": "(u)", "GetSessionIdleTime": "(u)"}
log = open(sys.argv[1], "a")
def call(conn, sender, path, iface, method, params, inv):
    log.write(f"{method} {params.unpack()}\\n"); log.flush()
    t = ANSWERS.get(method)
    inv.return_value(GLib.Variant(t, (42 if "u" in t else True,)) if t else None)
bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
for path in ("/ScreenSaver", "/org/freedesktop/ScreenSaver"):
    bus.register_object(path, Gio.DBusNodeInfo.new_for_xml(XML).interfaces[0], call, None, None)
Gio.bus_own_name_on_connection(bus, "org.freedesktop.ScreenSaver", Gio.BusNameOwnerFlags.NONE, None, None)
GLib.MainLoop().run()
"""

# the members besides the inhibit pair, each with its arguments for `gdbus call`
_SCREENSAVER_OTHERS = {"Lock": "", "SetActive": "true", "SimulateUserActivity": "", "GetActive": "", "GetActiveTime": "",
                       "GetSessionIdleTime": "", "Throttle": 'appkata "a call"', "UnThrottle": "42"}


@needs_proxy
def test_the_direct_screensaver_name_takes_an_inhibit_only_with_the_capability(env, tmp_path):
    # "Keep the screen awake": the portal road is in the host-caller test; this is the direct
    # org.freedesktop.ScreenSaver name the non-GLib apps (Electron's powerSaveBlocker, Qt, mpv) use.
    # CR1.5-44: the stand-in served the inhibit pair alone, so the test could not see that the
    # capability opened the whole interface: an app with it locked the screen under KDE's locker.
    # It serves what the desktops declare now, and the app gets the pair, on both objects, alone.
    bus = _Bus(env)
    log = tmp_path / "ss.log"
    ss = subprocess.Popen(["python3", "-c", _SCREENSAVER, str(log)], env={**env.env, "DBUS_SESSION_BUS_ADDRESS": bus.addr},
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    call = ('gdbus call --session --dest org.freedesktop.ScreenSaver --object-path {} '
            '--method org.freedesktop.ScreenSaver.{} {} 2>&1')
    asked = "appkata 'a call'"
    calls = [f'echo "{path} Inhibit: $({call.format(path, "Inhibit", asked)})"; '
             f'echo "{path} UnInhibit: $({call.format(path, "UnInhibit", "42")})"' for path in ("/org/freedesktop/ScreenSaver", "/ScreenSaver")]
    calls += [f'echo "{m}: $({call.format("/ScreenSaver", m, a)})"' for m, a in _SCREENSAVER_OTHERS.items()]
    try:
        for _ in range(50):
            r = subprocess.run(["sh", "-c", "gdbus call --session --dest org.freedesktop.DBus --object-path /org/freedesktop/DBus "
                                "--method org.freedesktop.DBus.NameHasOwner org.freedesktop.ScreenSaver"],
                               env={**env.env, "DBUS_SESSION_BUS_ADDRESS": bus.addr}, capture_output=True, text=True)
            if r.stdout.strip() == "(true,)":
                break
            subprocess.run(["sleep", "0.1"])
        r = env.run(env.app("awake", sb.resolve_template("messenger")), "; ".join(calls), env={"DBUS_SESSION_BUS_ADDRESS": bus.addr})
        r2 = env.run(env.app("sleepy", sb.resolve_template("online-app")), calls[0], env={"DBUS_SESSION_BUS_ADDRESS": bus.addr})
    finally:
        ss.terminate()
        bus.close()
    out = r.stdout.splitlines()
    for path in ("/org/freedesktop/ScreenSaver", "/ScreenSaver"):
        assert f"{path} Inhibit: (uint32 42,)" in out and f"{path} UnInhibit: ()" in out, (r.stdout, r.stderr)    # inhibited, cookie back
    served = log.read_text()
    assert served.count("Inhibit ('appkata', 'a call')") == 2 and served.count("UnInhibit (42,)") == 2, served
    for m in _SCREENSAVER_OTHERS:
        assert any(l.startswith(f"{m}: Error: GDBus.Error:org.freedesktop.DBus.Error.AccessDenied") for l in out), (m, r.stdout)
        assert not [l for l in served.splitlines() if l.split()[0] == m], (m, served)       # and it never arrived
    assert "AccessDenied" in r2.stdout or "ServiceUnknown" in r2.stdout, r2.stdout        # no capability: no name


_SECRETS_APP = """
import sys
from gi.repository import Gio, GLib
XML = '''<node><interface name="org.freedesktop.Secret.Service"><method name="OpenSession"><arg type="s" direction="in"/><arg type="v" direction="in"/>
<arg type="v" direction="out"/><arg type="o" direction="out"/></method></interface></node>'''
def call(conn, sender, path, iface, method, params, inv):
    print("ASKED", method, "by", sender, flush=True)
    inv.return_value(GLib.Variant("(vo)", (GLib.Variant("s", ""), "/org/freedesktop/secrets/session/s1")))
bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
bus.register_object("/org/freedesktop/secrets", Gio.DBusNodeInfo.new_for_xml(XML).interfaces[0], call, None, None)
Gio.bus_own_name_on_connection(bus, "org.freedesktop.secrets", Gio.BusNameOwnerFlags.NONE,
                               lambda *a: print("OWNED", flush=True), lambda *a: print("NOT-OWNED", flush=True))
GLib.timeout_add(2500, lambda: sys.exit(0))
GLib.MainLoop().run()
"""


@needs_proxy
def test_a_password_service_app_serves_a_host_client_only_with_the_provide_capability(env, tmp_path):
    # "Password service": the app offers org.freedesktop.secrets (KeePassXC). A host client on the test
    # bus opens a session with it, through the proxy into the sandbox; without the capability the app
    # can't own the name, and a client finds no service.
    bus = _Bus(env)
    client = ('for i in $(seq 20); do gdbus call --session --dest org.freedesktop.secrets --object-path /org/freedesktop/secrets '
              '--method org.freedesktop.Secret.Service.OpenSession plain "<\'\'>" 2>/dev/null && break; sleep 0.1; done')
    try:
        for name, template in (("keeper", "custom"), ("plain", "online-app")):
            d = env.home / "apps" / name / "1.0" / "bin"
            d.mkdir(parents=True, exist_ok=True)
            (d / "secrets.py").write_text(_SECRETS_APP)
        gs = sb.apply_overrides(sb.resolve_template("online-app"), {"caps": ["secrets-provide"]})
        p = subprocess.Popen([env.app("keeper", gs), 'python3 "$(dirname "$0")/secrets.py"'], env={**env.env, "DBUS_SESSION_BUS_ADDRESS": bus.addr},
                             cwd=str(env.home), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        c = subprocess.run(["sh", "-c", client], env={**env.env, "DBUS_SESSION_BUS_ADDRESS": bus.addr}, capture_output=True, text=True, timeout=30)
        out, err = p.communicate(timeout=30)
        p2 = subprocess.Popen([env.app("plain", sb.resolve_template("online-app")), 'python3 "$(dirname "$0")/secrets.py"'],
                              env={**env.env, "DBUS_SESSION_BUS_ADDRESS": bus.addr}, cwd=str(env.home), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        c2 = subprocess.run(["sh", "-c", client], env={**env.env, "DBUS_SESSION_BUS_ADDRESS": bus.addr}, capture_output=True, text=True, timeout=30)
        out2, _ = p2.communicate(timeout=30)
    finally:
        bus.close()
    assert "OWNED" in out and "ASKED OpenSession" in out, (out, err)
    assert "/org/freedesktop/secrets/session/s1" in c.stdout, (c.stdout, c.stderr)       # the host client got a session from the sandboxed service
    assert "NOT-OWNED" in out2 and "ASKED" not in out2 and "session/s1" not in c2.stdout, (out2, c2.stdout)


# A keyring client, run inside the sandbox: libsecret by ctypes, as Chromium, Electron and QtKeychain
# use it (store, lookup, a search that unlocks and loads secrets, a relabel, a clear), then
# secretstorage (jeepney's, the Python `keyring` package's: store, search, relabel, delete, lock,
# and an unlock whose prompt must complete), then what else the keyring's connection serves.
_KEYRING_PROBE = """
import ctypes, faulthandler, sys
faulthandler.enable()               # a crash names its line on stderr, which the test shows
def say(*a): print(*a, flush=True)
try:
    ls = ctypes.CDLL("libsecret-1.so.0"); gl = ctypes.CDLL("libglib-2.0.so.0")
except OSError:
    ls = None; say("LIBSECRET absent")
class Attr(ctypes.Structure): _fields_ = [("name", ctypes.c_char_p), ("type", ctypes.c_int)]
class Schema(ctypes.Structure):
    _fields_ = [("name", ctypes.c_char_p), ("flags", ctypes.c_int), ("attributes", Attr * 32), ("reserved", ctypes.c_int)] + [(f"r{i}", ctypes.c_void_p) for i in range(1, 8)]
class GError(ctypes.Structure): _fields_ = [("domain", ctypes.c_uint32), ("code", ctypes.c_int), ("message", ctypes.c_char_p)]
schema = Schema(); schema.name = b"org.appkata.Probe"; schema.attributes[0] = Attr(b"app", 0)
def why(e): return ctypes.cast(e, ctypes.POINTER(GError)).contents.message.decode() if e.value else "no error"
if ls:
    e = ctypes.c_void_p()
    ok = ls.secret_password_store_sync(ctypes.byref(schema), b"default", b"AppKata probe", b"s3cret-1", None, ctypes.byref(e), b"app", b"probe", None)
    say("LIBSECRET store", "OK" if ok else "FAIL " + why(e))
    e = ctypes.c_void_p(); ls.secret_password_lookup_sync.restype = ctypes.c_char_p
    pw = ls.secret_password_lookup_sync(ctypes.byref(schema), None, ctypes.byref(e), b"app", b"probe", None)
    say("LIBSECRET lookup", "OK" if pw == b"s3cret-1" else f"FAIL {pw} {why(e)}")
    gl.g_hash_table_new.restype = ctypes.c_void_p      # a pointer: ctypes' default, a C int, cuts one above 2 GiB
    ht = gl.g_hash_table_new(ctypes.cast(gl.g_str_hash, ctypes.c_void_p), ctypes.cast(gl.g_str_equal, ctypes.c_void_p))
    gl.g_hash_table_insert(ctypes.c_void_p(ht), b"app", b"probe")
    for f, t in (("secret_service_search_sync", ctypes.c_void_p), ("secret_item_get_secret", ctypes.c_void_p), ("secret_value_get_text", ctypes.c_char_p)):
        getattr(ls, f).restype = t
    gl.g_list_nth_data.restype = ctypes.c_void_p
    e = ctypes.c_void_p()             # SECRET_SEARCH_ALL | UNLOCK | LOAD_SECRETS, as Chromium's OSCrypt searches
    found = ls.secret_service_search_sync(None, ctypes.byref(schema), ctypes.c_void_p(ht), 2 | 4 | 8, None, ctypes.byref(e))
    item = gl.g_list_nth_data(ctypes.c_void_p(found), 0) if found else None
    value = ls.secret_item_get_secret(ctypes.c_void_p(item)) if item else None
    say("LIBSECRET search", "OK" if value and ls.secret_value_get_text(ctypes.c_void_p(value)) == b"s3cret-1" else "FAIL " + why(e))
    e = ctypes.c_void_p()
    ok = item and ls.secret_item_set_label_sync(ctypes.c_void_p(item), b"AppKata probe, renamed", None, ctypes.byref(e))
    say("LIBSECRET relabel", "OK" if ok else "FAIL " + why(e))
    e = ctypes.c_void_p()
    ok = ls.secret_password_clear_sync(ctypes.byref(schema), None, ctypes.byref(e), b"app", b"probe", None)
    say("LIBSECRET clear", "OK" if ok else "FAIL " + why(e))
try:
    import secretstorage
except ImportError:
    secretstorage = None; say("SECRETSTORAGE absent")
if secretstorage:
    try:
        conn = secretstorage.dbus_init()
        col = secretstorage.get_default_collection(conn)
        col.create_item("AppKata probe 2", {"app": "probe2"}, b"s3cret-2", replace=True)
        item = next(col.search_items({"app": "probe2"}))
        say("SECRETSTORAGE store", "OK" if item.get_secret() == b"s3cret-2" and item.get_attributes()["app"] == "probe2" else "FAIL")
        item.set_label("AppKata probe 2, renamed")
        say("SECRETSTORAGE relabel", "OK" if item.get_label().endswith("renamed") else "FAIL")
        item.delete(); say("SECRETSTORAGE delete OK")
        col.lock()
        say("SECRETSTORAGE unlock", "OK, the prompt completed" if col.is_locked() and col.unlock() in (True, False) else "FAIL")
    except Exception as ex:
        say("SECRETSTORAGE FAIL", type(ex).__name__, ex)
from gi.repository import Gio, GLib
bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
def ask(what, dest, path, iface, method, args=None):
    try:
        bus.call_sync(dest, path, iface, method, args, None, Gio.DBusCallFlags.NONE, 3000, None)
        say("OTHER", what, "ANSWERED")
    except GLib.Error as e:
        say("OTHER", what, "REFUSED", Gio.DBusError.get_remote_error(e))
try:
    owner = bus.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "GetNameOwner", GLib.Variant("(s)", ("org.freedesktop.secrets",)),
                          None, Gio.DBusCallFlags.NONE, 3000, None).unpack()[0]
except GLib.Error as e:
    owner = None; say("OWNER HIDDEN", Gio.DBusError.get_remote_error(e))
guilt = "org.gnome.keyring.InternalUnsupportedGuiltRiddenInterface"
login = "/org/freedesktop/secrets/collection/login"
for road, dest in (("name", "org.freedesktop.secrets"), ("owner", owner), ("keyring", "org.gnome.keyring")):
    if not dest:
        continue
    ask(f"{road} GetEnvironment", dest, "/org/gnome/keyring/daemon", "org.gnome.keyring.Daemon", "GetEnvironment")
    ask(f"{road} GetControlDirectory", dest, "/org/gnome/keyring/daemon", "org.gnome.keyring.Daemon", "GetControlDirectory")
    ask(f"{road} UnlockWithMasterPassword", dest, "/org/freedesktop/secrets", guilt, "UnlockWithMasterPassword",
        GLib.Variant("(o(oayays))", (login, ("/", b"", b"x", "text/plain"))))
    ask(f"{road} ChangeWithPrompt", dest, "/org/freedesktop/secrets", guilt, "ChangeWithPrompt", GLib.Variant("(o)", (login,)))
    ask(f"{road} RetrieveSecret", dest, "/org/freedesktop/portal/desktop", "org.freedesktop.impl.portal.Secret", "RetrieveSecret",
        GLib.Variant("(osa{sv}h)", ("/r/1", "io.appkata.x", {}, 0)))
"""


@needs_proxy
@pytest.mark.skipif(not shutil.which("gnome-keyring-daemon"), reason="needs gnome-keyring")
def test_saved_passwords_reach_the_secret_service_and_nothing_else_the_keyring_serves(env, tmp_path):
    # CR1.5-43: Saved passwords passed `--talk=org.freedesktop.secrets`, which xdg-dbus-proxy gives to
    # the connection owning the name (CR1.5-3): gnome-keyring's, with its daemon interface (the
    # session's SSH agent socket and control folder), its master-password interface and the Secret
    # portal's backend beside the secret service. Real clients through the filter, against a real
    # keyring, unlocked as a login leaves it: they keep working, and the rest is refused by every road.
    bus = _Bus(env)
    on_bus = {**env.env, "DBUS_SESSION_BUS_ADDRESS": bus.addr}
    keyring = subprocess.Popen(["gnome-keyring-daemon", "--unlock", "--components=secrets", "--foreground"], env=on_bus,
                               stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    keyring.stdin.write(b"login-password")
    keyring.stdin.close()
    try:
        for _ in range(50):
            r = subprocess.run(["gdbus", "call", "--session", "--dest", "org.freedesktop.DBus", "--object-path", "/org/freedesktop/DBus",
                                "--method", "org.freedesktop.DBus.NameHasOwner", "org.freedesktop.secrets"], env=on_bus, capture_output=True, text=True)
            if r.stdout.strip() == "(true,)":
                break
            subprocess.run(["sleep", "0.1"])
        for app_id in ("keys", "nokeys"):
            d = env.home / "apps" / app_id / "1.0" / "bin"
            d.mkdir(parents=True, exist_ok=True)
            (d / "probe.py").write_text(_KEYRING_PROBE)
        gs = sb.apply_overrides(sb.resolve_template("standard"), {"caps": ["secrets"]})
        probe = 'python3 "$(dirname "$0")/probe.py"'
        r = env.run(env.app("keys", gs), probe, env={"DBUS_SESSION_BUS_ADDRESS": bus.addr}, timeout=90)
        r2 = env.run(env.app("nokeys", sb.apply_overrides(gs, {"caps": []})), probe, env={"DBUS_SESSION_BUS_ADDRESS": bus.addr}, timeout=90)
    finally:
        keyring.terminate()
        keyring.wait()
        bus.close()
    out = r.stdout.splitlines()
    clients = [l for l in out if l.startswith(("LIBSECRET", "SECRETSTORAGE"))]
    assert [l for l in clients if not l.endswith("absent")], (r.stdout, r.stderr)                  # one client at least
    assert not [l for l in clients if "FAIL" in l], (r.stdout, r.stderr)                           # each works through the filter
    others = [l for l in out if l.startswith("OTHER")]
    assert len(others) >= 10 and not [l for l in others if "ANSWERED" in l], (r.returncode, r.stdout, r.stderr)     # name and owner, five calls each
    assert not [l for l in others if not l.startswith("OTHER keyring") and not l.endswith("org.freedesktop.DBus.Error.AccessDenied")], \
        (r.returncode, r.stdout, r.stderr)
    out2 = r2.stdout.splitlines()                                                                     # and without the capability, no keyring
    assert not [l for l in out2 if "ANSWERED" in l or l.startswith(("LIBSECRET", "SECRETSTORAGE")) and "FAIL" not in l and not l.endswith("absent")], \
        (r2.returncode, r2.stdout, r2.stderr)
    assert "OWNER HIDDEN org.freedesktop.DBus.Error.NameHasNoOwner" in out2, (r2.returncode, r2.stdout, r2.stderr)


@needs_proxy
@pytest.mark.skipif(not shutil.which("gnome-keyring-daemon"), reason="needs gnome-keyring")
def test_password_service_beside_a_running_keyring_starts_without_the_name_and_never_reaches_it(env):
    # CR1.5-46 (#707; the owner's decision of 2026-11-24): with gnome-keyring holding
    # org.freedesktop.secrets, an app with Password service alone reached the keyring's whole
    # connection through the filter -- to it an own is a talk -- its daemon interface and every
    # unlocked password. Now the launch finds the name held, starts the app without the own and says
    # why. A real keyring, unlocked as a login leaves it; the sole-provider case is
    # test_a_password_service_app_serves_a_host_client_only_with_the_provide_capability.
    bus = _Bus(env)
    on_bus = {**env.env, "DBUS_SESSION_BUS_ADDRESS": bus.addr}
    keyring = subprocess.Popen(["gnome-keyring-daemon", "--unlock", "--components=secrets", "--foreground"], env=on_bus,
                               stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    keyring.stdin.write(b"login-password")
    keyring.stdin.close()
    ask = ('gdbus call --session --dest org.freedesktop.secrets --object-path {} --method {} 2>&1 | head -1; ')
    probe = (ask.format("/org/gnome/keyring/daemon", "org.gnome.keyring.Daemon.GetEnvironment") +
             ask.format("/org/freedesktop/secrets", "org.freedesktop.Secret.Service.OpenSession plain \"<\'\'>\"") +
             _OWN.format("org.freedesktop.secrets") + "; true")
    try:
        for _ in range(50):
            r = subprocess.run(["gdbus", "call", "--session", "--dest", "org.freedesktop.DBus", "--object-path", "/org/freedesktop/DBus",
                                "--method", "org.freedesktop.DBus.NameHasOwner", "org.freedesktop.secrets"], env=on_bus, capture_output=True, text=True)
            if r.stdout.strip() == "(true,)":
                break
            time.sleep(0.1)
        gs = sb.apply_overrides(sb.resolve_template("standard"), {"caps": ["secrets-provide"]})
        r = env.run(env.app("keeper", gs), probe, env={"DBUS_SESSION_BUS_ADDRESS": bus.addr}, timeout=60)
    finally:
        keyring.terminate()
        keyring.wait()
        bus.close()
    assert r.returncode == 0 and "runs without Password service" in r.stderr, (r.stdout, r.stderr)
    out = r.stdout.splitlines()
    assert len(out) == 3 and all("org.freedesktop.DBus.Error.ServiceUnknown" in l for l in out[:2]), out      # nothing of the keyring
    assert out[2].startswith("Error") and "uint32" not in out[2], out                                           # nor the name


_KEYRING_STARTS = "/usr/share/dbus-1/services/org.freedesktop.secrets.service"


@needs_proxy
@pytest.mark.skipif(not os.path.exists(_KEYRING_STARTS), reason="needs gnome-keyring")
def test_password_service_where_the_bus_can_start_a_keyring_starts_without_the_name_and_cannot_start_it(env):
    # PR #694's review, P2-3: gnome-keyring installs an activation file for org.freedesktop.secrets,
    # so where it is installed and not running (a password manager's own set-up) the launch found
    # the name free and gave the own; to the filter an own is a talk, so the app's own call to the
    # name had the bus start the keyring, and the app reached its whole connection. Now a name the
    # bus can start a program for counts as held. The bus here starts the keyring as a desktop's
    # would (its own service file); nothing runs it first.
    bus = _Bus(env, starts=(os.path.basename(_KEYRING_STARTS),))
    on_bus = {**env.env, "DBUS_SESSION_BUS_ADDRESS": bus.addr}
    driver = ["gdbus", "call", "--session", "--dest", "org.freedesktop.DBus", "--object-path", "/org/freedesktop/DBus", "--method"]
    probe = ('gdbus call --session --dest org.freedesktop.secrets --object-path /org/gnome/keyring/daemon '
             '--method org.gnome.keyring.Daemon.GetEnvironment 2>&1 | head -1; '
             'gdbus call --session --dest org.freedesktop.DBus --object-path /org/freedesktop/DBus '
             '--method org.freedesktop.DBus.StartServiceByName org.freedesktop.secrets 0 2>&1 | head -1; ' + _OWN.format("org.freedesktop.secrets") + "; true")
    try:
        names = subprocess.run(driver + ["org.freedesktop.DBus.ListActivatableNames"], env=on_bus, capture_output=True, text=True).stdout
        gs = sb.apply_overrides(sb.resolve_template("standard"), {"caps": ["secrets-provide"]})
        r = env.run(env.app("keeper", gs), probe, env={"DBUS_SESSION_BUS_ADDRESS": bus.addr}, timeout=60)
        started = subprocess.run(driver + ["org.freedesktop.DBus.NameHasOwner", "org.freedesktop.secrets"], env=on_bus,
                                 capture_output=True, text=True).stdout.strip()
    finally:
        pid = subprocess.run(driver + ["org.freedesktop.DBus.GetConnectionUnixProcessID", "org.freedesktop.secrets"], env=on_bus,
                             capture_output=True, text=True).stdout
        m = re.search(r"uint32 (\d+)", pid)
        if m:                                               # a keyring the app started: ended with the test
            os.kill(int(m.group(1)), 15)
        bus.close()
    assert "'org.freedesktop.secrets'" in names, names                                          # the bus can start it
    assert r.returncode == 0 and "this session bus can start another program that provides saved passwords" in r.stderr, (r.stdout, r.stderr)
    out = r.stdout.splitlines()
    assert len(out) == 3 and "org.freedesktop.DBus.Error.ServiceUnknown" in out[0] and out[1].startswith("Error"), out   # nothing of it,
    assert out[2].startswith("Error") and "uint32" not in out[2], out                                                  # nor the name,
    assert started == "(false,)", started                                                                              # nor started it


def test_extraction_still_works_without_flock_on_the_path(env, tmp_path):
    # The launcher serializes first launches on flock where present and goes on without it; a PATH
    # with everything the launcher runs except flock shows the "without".
    bindir = tmp_path / "noflock"
    bindir.mkdir()
    for tool in ("sh", "bwrap", "mkdir", "stat", "cat", "mktemp", "rm", "mv", "printf", "date", "id", "readlink", "kill", "sleep", "python3", "xdg-dbus-proxy", "dirname", "ls", "echo"):
        src = shutil.which(tool)
        if src:
            os.symlink(src, bindir / tool)
    (env.home / "apps" / "img").mkdir(parents=True)
    img = env.home / "apps" / "img" / "Img.AppImage"
    _fake_appimage(img, "unpacked-without-flock")
    lp = _appimage_app(env, img)
    r = subprocess.run([env.on_a_machine_with(lp, str(bindir)), ""], env=env.env, cwd=str(env.home), capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and r.stdout.strip() == "unpacked-without-flock", (r.stdout, r.stderr)
    assert "flock" not in r.stderr and not os.path.exists(str(img.parent / "1.0.extracted.lock"))


def test_the_gpu_renders_inside_the_sandbox_where_the_host_has_one(env):
    # "GPU acceleration" was on the physical-desktop checklist. The VM has a virtio GPU and the
    # launcher binds /dev/dri and the /sys paths Mesa needs (R17.4); eglinfo on the device platform
    # names the renderer without any display server. Hardware-accelerated means a renderer that is
    # not llvmpipe/softpipe; on this host that is virgl (tier 3) -- a container has no node and skips.
    if not os.path.isdir("/dev/dri") or not any(n.startswith("renderD") for n in os.listdir("/dev/dri")):
        pytest.skip("no render node here (the VM has a virtio GPU)")
    if not shutil.which("eglinfo"):
        pytest.skip("needs eglinfo (mesa-utils)")
    lp = env.app("gl", sb.resolve_template("online-app"))
    r = env.run(lp, 'eglinfo -B 2>&1 | grep -iE "renderer|vendor|platform|error" | head -12', timeout=60)
    assert r.returncode == 0, r.stderr
    assert "renderer" in r.stdout.lower(), (r.stdout, r.stderr)
    host = subprocess.run(["sh", "-c", 'eglinfo -B 2>&1 | grep -iE "renderer" | head -3'], env=env.env, capture_output=True, text=True).stdout
    inside = [l for l in r.stdout.splitlines() if "renderer" in l.lower()]
    assert any(l.strip() in host for l in inside), (inside, host)       # the same renderer the host sees, not a software fallback of its own


# ---------------------------------------------------------------- the real install path, end to end (round nine)

def _tarball(path, version: str) -> None:
    import io
    import tarfile
    script = (f'#!/bin/sh\necho "demo v{version} home=$HOME entries=$(ls -A "$HOME" | wc -l)"\n'
              'cat "$HOME/.ssh/id_ed25519" 2>/dev/null; echo "args: $*"\n').encode()
    with tarfile.open(path, "w:gz") as tf:
        info = tarfile.TarInfo(f"demo-{version}/bin/demo")
        info.size, info.mode = len(script), 0o755
        tf.addfile(info, io.BytesIO(script))


def test_a_real_install_update_rollback_and_uninstall_run_sandboxed_end_to_end(env, tmp_path, monkeypatch):
    # Every backend test composes install records by hand; nothing had driven install.install()
    # with a real archive, launched the result under bwrap through launch(), updated it, rolled it
    # back and uninstalled it -- the product's own path (R4.3.1, R17.4, R17.7, R17.14). A local HTTP
    # server serves two tarballs; the private home, the launcher, the menu entry, the command link,
    # the identity marker and the log are what the real path leaves, and what uninstall removes.
    import http.server
    import threading
    from appkata_core import applog, install
    from appkata_core.db import DB
    from appkata_core.forges import Asset
    monkeypatch.setenv("XDG_STATE_HOME", str(env.home / ".local" / "state"))
    monkeypatch.setattr(install, "desktop_dir", lambda: str(env.home / ".local" / "share" / "applications"))
    site = tmp_path / "site"
    site.mkdir()
    _tarball(site / "demo-1.0.tar.gz", "1.0")
    _tarball(site / "demo-2.0.tar.gz", "2.0")
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), lambda *a, **k: http.server.SimpleHTTPRequestHandler(*a, directory=str(site), **k))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    db = DB(str(env.home / ".local" / "share" / "appkata" / "appkata.db"))
    url = "https://example.org/demo/demo"
    portable = install.Portable(folder=str(env.home / "apps"), command_dir=str(env.home / "bin"), app_menu=True, keep=2)
    app = {"url": url, "name": "Demo", "version": "1.0", "sandbox": sb.to_json(sb.resolve_template("strict"))}

    def asset(v):
        return Asset(name=f"demo-{v}.tar.gz", url=f"http://127.0.0.1:{port}/demo-{v}.tar.gz")

    def run(expect: str):
        logfile = applog.app_log_path("demo")                              # the install's id (R14.2.1)
        before = os.path.getsize(logfile) if os.path.exists(logfile) else 0
        t = install.launch(db, url)
        t.join(timeout=60)
        with open(logfile) as f:
            f.seek(before)
            out = f.read()
        assert expect in out and "SECRET-KEY" not in out, out                 # the real home never shows
        assert "home=" + str(env.home) + " " in out                            # $HOME is the usual path, the private one behind it
        return out

    try:
        rec = install.install(db, {**app, "installVersion": "1.0"}, asset("1.0"), "tarball", [asset("1.0")], portable=portable)
        assert rec["launcher"] == str(env.home / "apps" / "demo" / "run") and rec["id"] == "demo"
        assert os.path.exists(rec["launcher"]) and os.path.exists(sb.identity_path("demo"))
        assert os.path.islink(env.home / "bin" / "demo") and os.path.exists(env.home / ".local/share/applications/appkata-demo.desktop")
        assert "--appkata-menu" in open(env.home / ".local/share/applications/appkata-demo.desktop").read()
        run("demo v1.0")
        assert os.path.isdir(sb.sandbox_home("demo"))                           # the private home came into being at the first run
        # update
        rec = install.install(db, {**app, "installVersion": "2.0", "updateTo": "2.0"}, asset("2.0"), "tarball", [asset("2.0")], portable=portable)
        assert rec["current"]["version"] == "2.0" and [k["version"] for k in rec["kept"]] == ["1.0"]
        run("demo v2.0")
        assert install.launcher_is_current(rec, app, portable)
        # rollback to the kept version, no download
        install.switch_to(db, app, "1.0", portable)
        run("demo v1.0")
        # drop the newer one, then the app, keeping nothing
        install.remove_version(db, url, "2.0")
        assert not os.path.exists(env.home / "apps" / "demo" / "2.0")
        install.uninstall(db, url, remove_sandbox=True)
    finally:
        srv.shutdown()
    assert db.one("SELECT 1 FROM installs WHERE url=?", (url,)) is None
    assert not os.path.exists(env.home / "apps" / "demo") or not os.listdir(env.home / "apps" / "demo")
    assert not os.path.lexists(env.home / "bin" / "demo") and not os.path.exists(env.home / ".local/share/applications/appkata-demo.desktop")
    assert not os.path.exists(sb.identity_path("demo")) and not os.path.exists(sb.sandbox_home("demo"))
