"""App sandboxing (requirement 17): generated launchers, actually run under bwrap.

These execute `~/bin/apps/<app>/run` as AppKata writes it, with a tiny shell "app" that runs the
snippet it's given, and check what the app can and can't reach. They need a bwrap new enough for the
launcher (`--clearenv`, 0.5+) that can create user namespaces; elsewhere they skip. Run them in the
Mint 22.1 container with `scripts/test-sandbox.sh launcher`.
"""

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
        for v in ("XDG_DATA_HOME", "APPKATA_APPS", "APPKATA_DATA"):
            monkeypatch.delenv(v, raising=False)
        self.env = {"HOME": str(self.home), "XDG_RUNTIME_DIR": str(self.rt), "PATH": os.environ["PATH"],
                    "LANG": "C.UTF-8"}

    def app(self, app_id: str, gs: dict) -> str:
        """Install the fake app and write its launcher; returns the launcher path."""
        appdir = self.home / "apps" / app_id / "1.0"
        (appdir / "bin").mkdir(parents=True, exist_ok=True)
        exe = appdir / "bin" / "app"
        exe.write_text(APP)
        exe.chmod(0o755)
        return sb.write_launcher(app_id, app_id.title(), str(self.home / "apps"), str(appdir), "bin/app", gs)

    def run(self, launcher: str, snippet: str, cwd: str | None = None, env: dict | None = None,
            timeout: int = 30) -> subprocess.CompletedProcess:
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


# ---------------------------------------------------------------- the CLI tool's working directory (17.3.3)

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


# ---------------------------------------------------------------- network (17.2)

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
    # Round four, R4-8 (17.9): the "X11 apps" grant withholds the socket file, DISPLAY and the
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


# ---------------------------------------------------------------- the session bus (17.5)

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


@needs_proxy
def test_standard_apps_reach_the_filtered_bus_when_there_is_one(env, tmp_path):
    bus = _Bus(env)
    try:
        r = env.run(env.app("gui", sb.resolve_template("online-app")),
                    'echo "A=$DBUS_SESSION_BUS_ADDRESS"; [ -S "$XDG_RUNTIME_DIR/bus" ] && echo BUS',
                    env={"DBUS_SESSION_BUS_ADDRESS": bus.addr})
    finally:
        bus.close()
    assert "BUS" in r.stdout and f"A=unix:path={env.rt}/bus" in r.stdout, (r.stdout, r.stderr)


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


class _Bus:
    """A real session bus for the test user (dbus-daemon), torn down afterwards. It starts on demand
    only the portal services this machine has: `--session` would start any it has installed, and on a
    desktop gnome-keyring then took a name the app under test should own (review 3, R3-34)."""

    def __init__(self, env):
        self.addr = f"unix:path={env.rt}/bus"
        services = env.rt / "bus-services"
        services.mkdir(exist_ok=True)
        for d in ("/usr/share/dbus-1/services", "/usr/local/share/dbus-1/services"):
            for f in sorted(os.listdir(d)) if os.path.isdir(d) else []:
                if f.startswith(_PORTAL_SERVICES) and not (services / f).exists():
                    (services / f).symlink_to(os.path.join(d, f))
        conf = env.rt / "bus.conf"
        conf.write_text(_BUS_CONF.format(services=services))
        self.p = subprocess.Popen(["dbus-daemon", f"--config-file={conf}", f"--address={self.addr}", "--nofork", "--nopidfile"],
                                  env=env.env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(50):
            if (env.rt / "bus").exists():
                break
            subprocess.run(["sleep", "0.1"])

    def close(self):
        self.p.terminate()


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


# ---------------------------------------------------------------- devices (17.2.1)

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


# ---------------------------------------------------------------- terminals (17.3.3)

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


# ---------------------------------------------------------------- lazy AppImage extraction (17.7)

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


# ---------------------------------------------------------------- the document portal (17.6)

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


# ---------------------------------------------------------------- the portals see a host caller (17.6.1, finding 0)

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
             # Round six, R6-2: the Camera portal is denied whatever the camera grant says -- 17.8 and the
             # hint used to promise "the camera portal, which asks you first"; nothing asks
             _CALL.format('Camera.AccessCamera "{}"') + "; " + _CALL.format("Camera.IsCameraPresent") + "; true")
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
    assert len(lines) == 9 and "Portal operation not allowed" not in r.stdout, (r.stdout, r.stderr)
    assert lines[7].endswith("AccessDenied") and lines[8].endswith("AccessDenied"), lines[7:]   # no camera portal
    assert lines[0] == "(true,)"                                           # answered, as a host app
    assert lines[1].endswith("AccessDenied") and lines[2].endswith("AccessDenied")   # the proxy, not the portal
    assert "ServiceUnknown" in lines[3]
    assert "AccessDenied" not in lines[4], lines[4]                        # the Notification portal answered
    assert lines[5].endswith("AccessDenied"), lines[5]                     # Inhibit: not this app's capability
    assert lines[6].endswith("AccessDenied"), lines[6]                     # no version probe, so no portal chooser
    lines = r2.stdout.strip().splitlines()
    assert len(lines) == 9 and lines[0] == "(true,)", (r2.stdout, r2.stderr)
    assert lines[7].endswith("AccessDenied") and lines[8].endswith("AccessDenied")
    assert lines[4].endswith("AccessDenied") and lines[5].endswith("AccessDenied")   # no capability, no portal
    assert lines[6].endswith("AccessDenied")
    lines = r3.stdout.strip().splitlines()
    assert len(lines) == 9 and lines[7].endswith("AccessDenied") and lines[8].endswith("AccessDenied")   # the grant binds devices, opens no portal


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
    # The app's PATH starts with AppKata's xdg-open, which asks the OpenURI portal (17.6.3): a URL as
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


_TEST_HANDLER = "/usr/share/applications/appkata-test-handler.desktop"      # scripts/sandbox/register-test-handler.sh


@needs_proxy
def test_a_glib_program_opens_links_on_the_host_even_when_the_host_has_a_handler(env, tmp_path):
    # Regression (round three, R3-1): GLib opens a link or file with the default handler it finds and
    # asks the OpenURI portal only when it finds none. The host's /usr is in view, so on a desktop
    # (firefox.desktop, xed.desktop in /usr/share/applications) a GLib or GTK app started the host's
    # browser or editor *inside* the sandbox -- a second Firefox on the private home -- and the
    # portal saw nothing; the test above passed only because the test host registered no handler.
    # The launcher now hides the host's desktop entries under an empty tmpfs, as a Flatpak runtime
    # has none (17.4). The harness registers a handler as root before the tests, so the host side of
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


# ---------------------------------------------------------------- protected folders (17.3.1)

def test_a_grant_of_the_home_folder_or_the_keys_does_not_open_them(env):
    # Regression: a review's `Sandbox folders: +~` (or the picker) was bound as asked, and since the
    # bind came after the private home, the real home was back — keys, shell startup files and all.
    gs = sb.apply_overrides(sb.resolve_template("standard"),
                            {"folders": {"+" + str(env.home): "rw", "+" + str(env.home / ".ssh"): "ro"}})
    r = env.run(env.app("greedy", gs), 'cat "$HOME/.ssh/id_ed25519" 2>&1; echo pwned >> "$HOME/.bashrc"; echo done')
    assert r.returncode == 0 and "done" in r.stdout, (r.stdout, r.stderr)
    assert "SECRET-KEY" not in r.stdout
    assert (env.home / ".bashrc").read_text() == "# real bashrc\n"


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
                           # on this test's own Python: the one the release carries (requirement 1.2)
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


# ---------------------------------------------------------------- an app's own sandbox inside ours (17.10.2)

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
    bus = _Bus(env)
    try:
        lp = env.app("leak", sb.resolve_template("developer"))
        r = subprocess.run([lp, "echo RAN"], env={**env.env, "DBUS_SESSION_BUS_ADDRESS": bus.addr},
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
        assert r.returncode == 0
        left = []
        for _ in range(20):                                   # the namespace's processes go with bwrap, at once
            left = [l for l in subprocess.run(["ps", "-eo", "args"], capture_output=True, text=True).stdout.splitlines()
                    if "xdg-dbus-proxy" in l and "bus-io.appkata.leak." in l]
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


# ---------------------------------------------------------------- a refused launch leaves a trace (14.2, R4)

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
    log = tmp_path / "home" / ".local" / "state" / "appkata" / "apps" / "menu.log"                # the install's id (14.2.1)
    assert f"log={log}" in open(lp).read()
    refused = _fake_bwrap(env, "bwrap: setting up uid map: Permission denied")
    r = subprocess.run([lp, "--appkata-menu", "echo never"], cwd=str(env.home), env={**env.env, **refused},
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
    r = subprocess.run([lp, "echo never"], cwd=str(env.home), env={**env.env, **refused}, capture_output=True,
                       text=True, timeout=30)
    assert "Permission denied" in r.stderr and not log.exists()


# ---------------------------------------------------------------- file arguments (17.6.2, R7)

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
        finally:
            portal.close()
    finally:
        bus.close()


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
        r = subprocess.run([lp, 'echo "ARG $2"', str(docs / "a.txt")], cwd=str(env.home),
                           env={**env.env, "DBUS_SESSION_BUS_ADDRESS": bus.addr, "PATH": f"{fake}:{os.environ['PATH']}"},
                           capture_output=True, text=True, timeout=60)
    finally:
        bus.close()
    assert r.returncode == 0 and f"ARG {docs}/a.txt" in r.stdout, (r.stdout, r.stderr)


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
        finally:
            portal.close()
    finally:
        bus.close()
    doc = str(env.rt / "doc") + "/"
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
    # The forward helper calls Documents.Add with a timeout; a document portal that hangs (a stuck
    # FUSE mount) must cost that timeout and nothing more -- the launch goes on with the arguments as
    # they were (17.6.2), the app runs, the status comes out.
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
    # self-updater does): read-only without the grant (17.4: EROFS, the app sees why), writable with
    # it (17.7.1) -- and the files are the real ones, so the change is there at the next launch.
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
    # 17.7: the .AppImage is canonical and the extracted folder a derived cache. With the writable
    # grant the app changes its unpacked copy (and keeps it: the stamp is the .AppImage's, unchanged),
    # but the .AppImage file is bound read-only whatever the grant says -- AppKata's own update is
    # what replaces it (17.12).
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
GLib.timeout_add(2500, lambda: sys.exit(0))
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
    bus = _Bus(env)
    log = tmp_path / "keys.log"
    daemon = subprocess.Popen(["python3", "-c", _MEDIA_KEYS, str(log)], env={**env.env, "DBUS_SESSION_BUS_ADDRESS": bus.addr},
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for name in ("player", "noplayer"):
            d = env.home / "apps" / name / "1.0" / "bin"
            d.mkdir(parents=True, exist_ok=True)
            (d / "mpris.py").write_text(_MPRIS_APP)
        r = env.run(env.app("player", sb.resolve_template("media-player")), 'python3 "$(dirname "$0")/mpris.py"',
                    env={"DBUS_SESSION_BUS_ADDRESS": bus.addr}, timeout=60)
        r2 = env.run(env.app("noplayer", sb.resolve_template("online-app")), 'python3 "$(dirname "$0")/mpris.py"',
                     env={"DBUS_SESSION_BUS_ADDRESS": bus.addr}, timeout=60)
    finally:
        daemon.terminate()
        bus.close()
    assert "OWNED" in r.stdout and "CALLED Play" in r.stdout, (r.stdout, r.stderr)
    assert "PLAYED org.mpris.MediaPlayer2.appkataprobe status=Playing" in log.read_text()
    assert "NOT-OWNED" in r2.stdout and "CALLED" not in r2.stdout, (r2.stdout, r2.stderr)


_SCREENSAVER = """
import sys
from gi.repository import Gio, GLib
XML = '''<node><interface name="org.freedesktop.ScreenSaver">
<method name="Inhibit"><arg type="s" direction="in"/><arg type="s" direction="in"/><arg type="u" direction="out"/></method>
<method name="UnInhibit"><arg type="u" direction="in"/></method></interface></node>'''
log = open(sys.argv[1], "a")
def call(conn, sender, path, iface, method, params, inv):
    log.write(f"{method} {params.unpack()}\\n"); log.flush()
    inv.return_value(GLib.Variant("(u)", (42,)) if method == "Inhibit" else None)
bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
for path in ("/ScreenSaver", "/org/freedesktop/ScreenSaver"):
    bus.register_object(path, Gio.DBusNodeInfo.new_for_xml(XML).interfaces[0], call, None, None)
Gio.bus_own_name_on_connection(bus, "org.freedesktop.ScreenSaver", Gio.BusNameOwnerFlags.NONE, None, None)
GLib.MainLoop().run()
"""


@needs_proxy
def test_the_direct_screensaver_name_takes_an_inhibit_only_with_the_capability(env, tmp_path):
    # "Keep the screen awake": the portal road is in the host-caller test; this is the direct
    # org.freedesktop.ScreenSaver name the non-GLib apps (Electron's powerSaveBlocker, Qt, mpv) use.
    bus = _Bus(env)
    log = tmp_path / "ss.log"
    ss = subprocess.Popen(["python3", "-c", _SCREENSAVER, str(log)], env={**env.env, "DBUS_SESSION_BUS_ADDRESS": bus.addr},
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    call = ('gdbus call --session --dest org.freedesktop.ScreenSaver --object-path /org/freedesktop/ScreenSaver '
            '--method org.freedesktop.ScreenSaver.Inhibit appkata "a call" 2>&1')
    try:
        for _ in range(50):
            r = subprocess.run(["sh", "-c", "gdbus call --session --dest org.freedesktop.DBus --object-path /org/freedesktop/DBus "
                                "--method org.freedesktop.DBus.NameHasOwner org.freedesktop.ScreenSaver"],
                               env={**env.env, "DBUS_SESSION_BUS_ADDRESS": bus.addr}, capture_output=True, text=True)
            if r.stdout.strip() == "(true,)":
                break
            subprocess.run(["sleep", "0.1"])
        r = env.run(env.app("awake", sb.resolve_template("messenger")), call, env={"DBUS_SESSION_BUS_ADDRESS": bus.addr})
        r2 = env.run(env.app("sleepy", sb.resolve_template("online-app")), call, env={"DBUS_SESSION_BUS_ADDRESS": bus.addr})
    finally:
        ss.terminate()
        bus.close()
    assert r.stdout.strip() == "(uint32 42,)", (r.stdout, r.stderr)                       # inhibited, cookie back
    assert "Inhibit ('appkata', 'a call')" in log.read_text()
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
    r = subprocess.run([lp, ""], env={**env.env, "PATH": str(bindir)}, cwd=str(env.home), capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and r.stdout.strip() == "unpacked-without-flock", (r.stdout, r.stderr)
    assert "flock" not in r.stderr and not os.path.exists(str(img.parent / "1.0.extracted.lock"))


def test_the_gpu_renders_inside_the_sandbox_where_the_host_has_one(env):
    # "GPU acceleration" was on the physical-desktop checklist. The VM has a virtio GPU and the
    # launcher binds /dev/dri and the /sys paths Mesa needs (17.4); eglinfo on the device platform
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
    # back and uninstalled it -- the product's own path (4.3.1, 17.4, 17.7, 17.14). A local HTTP
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
        logfile = applog.app_log_path("demo")                              # the install's id (14.2.1)
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
