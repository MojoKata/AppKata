"""App sandboxing (requirement 17): grant-set resolution, overrides, the launcher, and the review lines."""

import os
import shlex
import shutil
import subprocess
import sys

import pytest

from appkata_core import sandbox as sb
from appkata_core import trustfile

pytestmark = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="the sandbox and its launchers are Linux-only (17.1)")


# ---------------------------------------------------------------- templates & resolution (17.3)

def test_templates_resolve_to_normalized_grant_sets():
    for name in sb.TEMPLATE_ORDER:
        gs = sb.resolve_template(name)
        assert set(gs) == {"level", "folders", "network", "ports", "sound", "devices", "caps", "exec_deny", "write_app"}
        assert gs["level"] in ("standard", "strict")


def test_merge_across_trusts_is_least_privilege():
    # messenger ∩ offline-editor: strictest wins; only what both allow (merge.py's canonical case)
    _, gs = sb.resolve(reviews=[{"template": "messenger", "overrides": {}},
                                {"template": "offline-editor", "overrides": {}}])
    assert gs["network"] is False            # offline-editor forbids network
    assert gs["sound"] == set()              # offline-editor has no sound
    assert gs["devices"] == {"x11"}          # camera dropped; both keep the X11 fallback
    assert gs["exec_deny"] is True


def test_intersect_treats_none_ports_as_unrestricted():
    # None = all ports; intersecting it with a list must keep the list, not collapse to "no ports".
    base = sb.blank_grants("standard")
    allports = {**base, "network": True, "ports": None}
    limited = {**base, "network": True, "ports": [80, 443]}
    other = {**base, "network": True, "ports": [443, 8080]}
    assert sb.intersect(allports, limited)["ports"] == [80, 443]   # unrestricted ∩ list = the list
    assert sb.intersect(limited, other)["ports"] == [443]          # list ∩ list = overlap
    assert sb.intersect(allports, {**base, "ports": None})["ports"] is None   # both unrestricted


def test_execute_deny_is_contagious():
    _, gs = sb.resolve(reviews=[{"template": "developer", "overrides": {}},   # exec allowed
                                {"template": "online-app", "overrides": {}}])  # exec denied
    assert gs["exec_deny"] is True


def test_folder_only_if_all_trusts_grant_it():
    _, gs = sb.resolve(reviews=[{"template": "offline-editor", "overrides": {"folders": {"+~/Zettlr": "rw"}}},
                                {"template": "offline-editor", "overrides": {}}])
    assert "~/Zettlr" not in gs["folders"]   # only one Trust granted it


def test_user_choice_wins_and_unreviewed_defaults():
    src, gs = sb.resolve(user={"template": "strict", "overrides": {}})
    assert src == "user" and gs["level"] == "strict"
    src, gs = sb.resolve(is_cli=False)                 # unreviewed GUI → strict (17.3.3)
    assert src == "default" and gs["level"] == "strict"
    src, gs = sb.resolve(is_cli=True)                  # unreviewed CLI → cli-tool, not Off
    assert src == "default" and "$cwd" in gs["folders"]


def test_default_template_by_kind_and_review_state():
    assert sb.default_template(is_cli=False, reviewed=True)["template"] == "standard"
    assert sb.default_template(is_cli=True, reviewed=True)["template"] == "cli-tool"
    assert sb.default_template(is_cli=False, reviewed=False)["template"] == "strict"
    assert sb.default_template(is_cli=True, reviewed=False)["template"] == "cli-tool"


def test_user_default_applies_only_to_unreviewed_apps():
    # The Settings → Sandbox default is for apps "no Trust has reviewed"; reviewed apps follow their
    # review (baseline Standard/cli-tool, 17.3.3). Regression: the backend passed the user's kind
    # default into default_template's reviewed branch, so a reviewed GUI app with no Sandbox line got
    # the user default (Strict) instead of the Standard baseline.
    user = {"template": "off", "overrides": {}}
    assert sb.default_template(False, reviewed=True, unreviewed_default=user)["template"] == "standard"
    assert sb.default_template(True, reviewed=True, unreviewed_default=user)["template"] == "cli-tool"
    assert sb.default_template(False, reviewed=False, unreviewed_default=user)["template"] == "off"
    assert sb.default_template(False, reviewed=False)["template"] == "strict"   # no user default set


def test_parse_folders_prefixes_and_modes():
    ov = sb.parse_folders("+~/Zettlr, ~/Media:ro, -~/Downloads, ~/Projects:rw")
    assert ov == {"+~/Zettlr": "rw", "~/Media": "ro", "-~/Downloads": None, "~/Projects": "rw"}
    gs = sb.apply_overrides(sb.resolve_template("offline-editor"), {"folders": ov})
    assert gs["folders"]["~/Zettlr"] == "rw" and gs["folders"]["~/Media"] == "ro"
    assert "~/Downloads" not in gs["folders"]


def test_config_from_review_reads_sandbox_settings():
    cfg = sb.config_from_review({"sandbox": "messenger", "sandboxFolders": "+~/Media:ro", "sandboxNetwork": True})
    assert cfg["template"] == "messenger"
    assert cfg["overrides"]["folders"] == {"+~/Media": "ro"}
    assert cfg["overrides"]["network"] is True
    assert sb.config_from_review({}) is None
    assert sb.config_from_review({"sandbox": "nonsense"}) is None


def test_a_config_naming_no_template_is_refused_not_looked_up():
    # Round four, R4-1: "custom" is what choose() reports for a merged or bespoke set; resolving it
    # as a template raised KeyError deep inside every reader of the app's settings.
    assert sb.config_error({"template": "custom", "overrides": {}})
    assert sb.config_error({"template": "nonsense"})
    assert not sb.config_error({"template": "off"}) and not sb.config_error({"custom": sb.to_json(sb.resolve_template("standard"))})
    assert not sb.config_error(None) and not sb.config_error({"template": "cli-tool", "overrides": {"network": True}})
    with pytest.raises(ValueError):
        sb.grants_from_config({"template": "custom", "overrides": {}})
    assert sb.choose(None, None, [{"template": "online-app", "overrides": {}}, {"template": "offline-editor", "overrides": {}}],
                     {"template": "strict"})[2] == "custom"                 # the name that must round-trip as a custom set


def test_off_bypasses_the_sandbox():
    gs = sb.grants_from_config({"template": "off"})
    assert sb.level_of(gs) == "off"
    assert sb.summary(gs) == ["No sandbox"]
    assert sb.uses_bus(gs) is False


# ---------------------------------------------------------------- the launcher (17.4, 17.5, 17.7)

def _valid_sh(text: str) -> bool:
    return subprocess.run(["sh", "-n"], input=text, text=True,
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


@pytest.mark.parametrize("template", list(sb.TEMPLATE_ORDER))
def test_launcher_is_valid_shell_for_every_template(template):
    gs = sb.resolve_template(template)
    text = sb.build_launcher("demo", "Demo", "/apps/demo/1.0", "bin/demo", gs)
    assert _valid_sh(text)


def test_standard_launcher_has_proxy_and_private_home():
    gs = sb.resolve_template("messenger")
    text = sb.build_launcher("signal", "Signal", "/apps/signal/7", "AppRun", gs)
    assert "xdg-dbus-proxy" in text                      # filtered session bus (17.5)
    assert "--own=io.appkata.signal" in text             # app identity on the bus
    assert "--talk=org.kde.StatusNotifierWatcher" in text  # the tray capability
    assert "--share-net" in text                         # messenger has network
    assert '--bind "$home" "$HOME"' in text              # private home over $HOME
    assert _valid_sh(text)


def test_standard_launcher_points_dbus_at_the_proxy_after_clearenv():
    # The sandboxed app's DBUS_SESSION_BUS_ADDRESS must be the filtered proxy socket, set *after*
    # --clearenv so bwrap keeps it. Regression: it was emitted before --clearenv (wiped) and the host
    # address was then passed through via keepenv, so the app reached the proxy only when the host bus
    # happened to be unix:path=$XDG_RUNTIME_DIR/bus (breaking portals/notifications elsewhere).
    text = sb.build_launcher("signal", "Signal", "/apps/signal/7", "AppRun", sb.resolve_template("messenger"))
    assert "DBUS_SESSION_BUS_ADDRESS" not in " ".join(sb._ENV_PASSTHROUGH)   # not passed through from the host
    assert text.index("--clearenv") < text.index('--setenv DBUS_SESSION_BUS_ADDRESS "unix:path=$rt/bus"')
    assert _valid_sh(text)


def test_strict_launcher_has_no_bus_no_network():
    text = sb.build_launcher("vault", "Vault", "/apps/vault/1", "bin/vault", sb.resolve_template("strict"))
    assert "xdg-dbus-proxy" not in text
    assert "--share-net" not in text
    assert text.lstrip().startswith("#!/bin/sh")
    # bwrap is the shell's child at every level (round four, R4-2: exec'd, --die-with-parent tied a
    # Strict app to the launcher's caller, and quitting AppKata killed it), its status carried out
    assert "exec bwrap" not in text and '"$@" || status=$?' in text and text.rstrip().endswith("exit $status")
    assert _valid_sh(text)


def _host_tools(monkeypatch, *have):
    real = sb.shutil.which
    monkeypatch.setattr(sb.shutil, "which", lambda n, *a, **k: (f"/usr/bin/{n}" if n in have else None)
                        if n in sb.TOOL_PACKAGES else real(n, *a, **k))


def test_bwrap_alone_sandboxes_and_a_standard_app_gets_no_bus_without_the_proxy(monkeypatch):
    # Review 2, F12: have_tools() wanted xdg-dbus-proxy as well, so with bwrap alone every app, Strict
    # included, ran unsandboxed. bwrap is enough now. A Standard app without the proxy runs with no
    # session bus, and the files it's given still reach it: the document portal is asked from the
    # host side, and its view is bound as before.
    _host_tools(monkeypatch, "bwrap")
    assert sb.have_tools() and not sb.have_bus_filter() and sb.missing_tools() == ["xdg-dbus-proxy"]
    gs = sb.resolve_template("online-app")
    with_bus = sb.build_launcher("chat", "Chat", "/apps/chat/1", "bin/chat", gs, forward="/h/forward.py")
    without = sb.build_launcher("chat", "Chat", "/apps/chat/1", "bin/chat", gs, forward="/h/forward.py", bus_filter=False)
    assert "xdg-dbus-proxy \"$upstream\"" in with_bus and '--bind "$sock" "$rt/bus"' in with_bus
    assert "xdg-dbus-proxy \"$upstream\"" not in without and '--bind "$sock" "$rt/bus"' not in without
    for text in (with_bus, without):                     # set either way; without a bus it leads nowhere (R3-33)
        assert '--setenv DBUS_SESSION_BUS_ADDRESS "unix:path=$rt/bus"' in text
    assert '"$sock"' not in without and "# No session bus: xdg-dbus-proxy isn't installed here" in without
    for text in (with_bus, without):                     # the hand-over, and the portal's view of this app
        assert "/h/forward.py" in text and '--bind-try "$rt/doc/by-app/$id" "$rt/doc"' in text
        assert "--share-net" in text and '--bind "$home" "$HOME"' in text
        assert _valid_sh(text)
    # the launcher's text follows the machine, so the startup pass rewrites it once the proxy is installed
    args = ("chat", "Chat", "/apps", "/apps/chat/1", "bin/chat", gs)
    before = sb.launcher_text(*args)
    _host_tools(monkeypatch, "bwrap", "xdg-dbus-proxy")
    assert sb.launcher_text(*args) != before and "xdg-dbus-proxy \"$upstream\"" in sb.launcher_text(*args)


@pytest.mark.parametrize("have,status,system,app", [
    (("bwrap", "xdg-dbus-proxy"), "ok", "", ""),
    (("bwrap",), "ok", "xdg-dbus-proxy isn't installed, so sandboxed apps get no desktop services",
     "Runs without desktop services: xdg-dbus-proxy isn't installed"),
    (("xdg-dbus-proxy",), "unsupported", "bubblewrap isn't installed, so apps run without a sandbox. Install it (sudo apt install bubblewrap)",
     "Running unsandboxed: bubblewrap isn't installed. Install it (sudo apt install bubblewrap)"),
    ((), "unsupported", "bubblewrap and xdg-dbus-proxy aren't installed, so apps run without a sandbox. Install them (sudo apt install bubblewrap xdg-dbus-proxy)",
     "Running unsandboxed: bubblewrap and xdg-dbus-proxy aren't installed"),
])
def test_support_names_the_tool_that_is_missing(monkeypatch, tmp_path, have, status, system, app):
    # Review 2, F12: Settings said "bubblewrap isn't installed" when only xdg-dbus-proxy was missing,
    # and App Detail named both whatever was
    _apparmor_dir(tmp_path, monkeypatch, {})
    monkeypatch.setattr(sb, "OS", "linux")
    monkeypatch.setattr(sb, "userns_works", lambda refresh=False: True)
    monkeypatch.setattr(sb, "nested_userns_works", lambda refresh=False: True)
    monkeypatch.setattr("appkata_core.platform.linux_family", lambda: "debian")
    _host_tools(monkeypatch, *have)
    st = sb.support_status()
    assert st["status"] == status and st["busFilter"] is ("xdg-dbus-proxy" in have)
    assert st["toolsHint"].startswith(system) and st["appToolsHint"].startswith(app), st
    assert ("xdg-dbus-proxy" in st["toolsHint"]) is ("xdg-dbus-proxy" not in have)
    if sb.missing_tools():                               # the RHEL family's package manager
        monkeypatch.setattr("appkata_core.platform.linux_family", lambda: "fedora")
        assert "(sudo dnf install " in sb.tools_hints(sb.missing_tools())["system"]


def test_a_failed_userns_probe_is_asked_again_a_minute_later_and_a_pass_stands(monkeypatch):
    # Review 2, F16: one timeout of the probe stood for the whole session, so every update until a
    # restart counted the system as unable to sandbox
    clock, runs = [1000.0], []
    answers = iter([subprocess.TimeoutExpired("bwrap", 15), 0, 1])
    def run(cmd, **kw):
        runs.append(cmd)
        a = next(answers)
        if isinstance(a, Exception):
            raise a
        return subprocess.CompletedProcess(cmd, a)
    monkeypatch.setattr(sb, "OS", "linux")
    monkeypatch.setattr(sb, "_userns_cache", None)
    monkeypatch.setattr(sb.shutil, "which", lambda n, *a, **k: "/usr/bin/bwrap" if n == "bwrap" else None)
    monkeypatch.setattr(sb.subprocess, "run", run)
    monkeypatch.setattr(sb.time, "monotonic", lambda: clock[0])
    assert sb.userns_works() is False and len(runs) == 1
    clock[0] += 30
    assert sb.userns_works() is False and len(runs) == 1      # cheap for the UI's many reads
    clock[0] += sb.PROBE_RETRY_S
    assert sb.userns_works() is True and len(runs) == 2       # asked again
    clock[0] += 3600
    assert sb.userns_works() is True and len(runs) == 2       # a pass stands for the session


def test_a_launcher_says_plainly_when_bwrap_is_missing(tmp_path, monkeypatch):
    # Review 2, F16: an app keeps its launcher when bubblewrap goes, so a start must say why it fails,
    # on stderr or, started from the menu, in the app's log -- not the shell's "bwrap: not found"
    home, rt = tmp_path / "home", tmp_path / "run"
    rt.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(rt))
    for v in ("XDG_DATA_HOME", "XDG_STATE_HOME", "APPKATA_APPS", "APPKATA_DATA", "APPKATA_LOG_DIR"):
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setattr(sb, "sandboxes_root", lambda: str(home / ".local/share/appkata/sandboxes"))
    lp = sb.write_launcher("demo", "Demo App", str(home / "bin/apps"), str(home / "bin/apps/demo/1"), "bin/demo",
                           sb.resolve_template("strict"))
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for tool in ("mkdir", "stat", "date", "mv", "id", "cat"):           # what the launcher's preamble uses
        if shutil.which(tool):
            (bindir / tool).symlink_to(shutil.which(tool))
    env = {"PATH": str(bindir), "HOME": str(home), "XDG_RUNTIME_DIR": str(rt)}
    r = subprocess.run(["/bin/sh", lp, "--version"], env=env, capture_output=True, text=True, timeout=30)
    assert r.returncode == 1
    assert r.stderr.strip() == ("AppKata: bubblewrap (bwrap) isn't installed, so Demo App can't run sandboxed here. "
                                "Install it, or set its sandbox to Off in AppKata (App Detail > Sandbox).")
    r = subprocess.run(["/bin/sh", lp, "--appkata-menu"], env=env, capture_output=True, text=True, timeout=30)
    from appkata_core import applog
    assert r.returncode == 1 and "isn't installed, so Demo App can't run" in open(applog.app_log_path("demo")).read()


def test_strict_drops_every_grant_that_would_widen_it():
    # Regression (round three, R3-2): Strict only forced the network off. A Strict set with
    # overrides -- a review's `Sandbox: strict` plus a `Sandbox folders` line, or Strict customized
    # in the dialog -- had the folder and the sound sockets bound, while the chips also showed a
    # network and services the launcher never gave. Strict now means 17.2's table everywhere.
    gs = sb.apply_overrides(sb.resolve_template("strict"),
                            {"folders": {"+~/Documents": "rw"}, "network": True, "sound": ["play"],
                             "caps": ["notifications"], "devices": ["camera", "x11"], "write_app": True})
    n = sb.normalize(gs)
    assert n["folders"] == {} and n["network"] is False and n["sound"] == set() and n["caps"] == set()
    assert n["devices"] == {"x11"} and n["write_app"] is False
    assert sb.summary(gs) == ["Strict · private home", "No network"]          # the chips say what runs
    text = sb.build_launcher("vault", "Vault", "/apps/vault/1", "bin/vault", gs)
    for absent in ("Documents", "pipewire-0", "pulse/native", "--share-net", "xdg-dbus-proxy", "/dev/video"):
        assert absent not in text, absent
    assert '--ro-bind "$appdir" "$appdir"' in text                             # install folder read-only
    assert _valid_sh(text)
    cfg = sb.config_from_review({"sandbox": "strict", "sandboxFolders": "+~/Documents", "sandboxNetwork": True})
    r = sb.normalize(sb.grants_from_config(cfg))
    assert r["level"] == "strict" and r["folders"] == {} and r["network"] is False
    assert sb.normalize(sb.resolve_template("standard"))["devices"] == {"x11"}  # Standard untouched


def test_appimage_launcher_extracts_lazily_and_sets_env():
    gs = sb.resolve_template("online-app")
    text = sb.build_launcher("obsidian", "Obsidian", "/apps/obsidian/1.5.extracted", "AppRun", gs,
                             appimage_path="/apps/obsidian/Obsidian.AppImage")
    assert "--appimage-extract" in text                  # lazy extraction (17.7)
    assert "squashfs-root" in text
    assert "--setenv APPIMAGE /apps/obsidian/Obsidian.AppImage" in text
    assert '--ro-bind-try "$img" "$img"' in text          # the .AppImage is visible so $APPIMAGE resolves
    assert _valid_sh(text)


def test_non_appimage_launcher_has_no_appimage_bind():
    # A tarball app has no .AppImage, so no $img bind (and $img is undefined in that launcher).
    text = sb.build_launcher("tool", "Tool", "/apps/tool/1", "bin/tool", sb.resolve_template("standard"))
    assert '"$img"' not in text
    assert _valid_sh(text)


def test_appimage_exec_is_apprun_even_when_not_yet_extracted():
    # Extraction is lazy (in the launcher), so this is called before the dir exists; it is always AppRun.
    assert sb.appimage_exec("/does/not/exist/yet.extracted") == "AppRun"


def test_cli_launcher_binds_the_current_directory():
    text = sb.build_launcher("mytool", "MyTool", "/apps/mytool/1", "bin/mytool", sb.resolve_template("cli-tool"),
                             apps_root="/apps")
    assert 'set -- --bind "$here" "$here" --chdir "$here" "$@"' in text   # the working directory, unless guarded
    assert "'/apps'" in text or " /apps" in text          # the install root is protected
    assert _valid_sh(text)


def test_writable_app_folder_binds_appdir_read_write():
    gs = sb.apply_overrides(sb.resolve_template("standard"), {"write_app": True})
    text = sb.build_launcher("app", "App", "/apps/app/1", "bin/app", gs)
    assert '--bind "$appdir" "$appdir"' in text
    assert '--ro-bind "$appdir" "$appdir"' not in text


def test_proxy_startup_is_set_u_safe_and_bails_if_proxy_dies():
    # The proxy reads the host bus via a default, so `set -eu` can't abort when it's unset; and the
    # readiness loop stops early if the proxy exits instead of blocking for the whole timeout.
    text = sb.build_launcher("signal", "Signal", "/apps/signal/7", "AppRun", sb.resolve_template("messenger"))
    assert '"$DBUS_SESSION_BUS_ADDRESS"' not in text        # not referenced unguarded under set -u
    assert 'upstream="${DBUS_SESSION_BUS_ADDRESS:-}"' in text
    assert 'kill -0 "$proxy"' in text
    assert _valid_sh(text)
    # the exact expansion tolerates an unset variable under `set -u`
    r = subprocess.run(["sh", "-c", 'set -eu; unset DBUS_SESSION_BUS_ADDRESS 2>/dev/null || true; '
                        'x="${DBUS_SESSION_BUS_ADDRESS:-}"; echo "ok:$x"'], capture_output=True, text=True)
    assert r.returncode == 0 and r.stdout.strip() == "ok:"


def test_proxy_args_map_capabilities():
    args = sb.proxy_args(sb.resolve_template("media-player"), "vlc")
    assert "--own=org.mpris.MediaPlayer2.*" in args      # media keys
    assert "--talk=org.freedesktop.ScreenSaver" in args  # inhibit


def test_the_notification_and_inhibit_portals_come_with_their_capabilities():
    # Regression (round three, R3-6): the Notification and Inhibit portals were open to every Standard
    # app, so a GLib app in an offline-editor sandbox (no "Notifications" chip) notified through the
    # portal anyway. Each capability now opens both roads -- the portal interface and the direct
    # name -- and an app without it has neither.
    portal = "--call=org.freedesktop.portal.Desktop=org.freedesktop.portal.{}.*@/org/freedesktop/portal/desktop"
    plain = sb.proxy_args(sb.resolve_template("offline-editor"), "ed")        # no capabilities
    assert portal.format("Notification") not in plain and "--talk=org.freedesktop.Notifications" not in plain
    assert portal.format("Inhibit") not in plain and "--talk=org.freedesktop.ScreenSaver" not in plain
    assert portal.format("OpenURI") in plain                                   # the always-on portals stay
    web = sb.proxy_args(sb.resolve_template("online-app"), "web")            # notifications only
    assert portal.format("Notification") in web and "--talk=org.freedesktop.Notifications" in web
    assert portal.format("Inhibit") not in web
    chat = sb.proxy_args(sb.resolve_template("messenger"), "chat")           # both
    assert portal.format("Notification") in chat and portal.format("Inhibit") in chat and "--talk=org.freedesktop.ScreenSaver" in chat


# ---------------------------------------------------------------- the review lines (10.3.1)

def test_trustfile_parses_sandbox_lines():
    section = ("## Zettlr::Settings\n\n- Trust: 4\n"
               "- Sandbox (linux): offline-editor\n"
               "- Sandbox folders (linux): +~/Zettlr, ~/Documents:ro\n"
               "- Sandbox network (linux): no\n")
    parsed, warns = trustfile.parse_section("Zettlr", section)
    assert not warns
    opts = trustfile.resolve_settings(parsed["opts"], "linux")
    assert opts["sandbox"] == "offline-editor"
    assert opts["sandboxFolders"] == "+~/Zettlr, ~/Documents:ro"
    assert opts["sandboxNetwork"] is False


def test_trustfile_writes_sandbox_lines_for_linux_only():
    out = trustfile.options_to_write({}, "", {"sandbox": "messenger", "sandboxNetwork": True}, "linux")
    text = trustfile.format_settings("Signal", out)
    assert "- Sandbox (linux): messenger" in text
    assert "- Sandbox network (linux): yes" in text
    # ignored on other platforms (17.1, 10.3.1)
    assert trustfile.resolve_settings(parsed_only(out), "windows").get("sandbox") is None


def parsed_only(opts: dict) -> dict:
    return opts


def test_invalid_sandbox_template_is_ignored():
    section = "## Foo::Settings\n\n- Sandbox: not-a-template\n"
    parsed, _ = trustfile.parse_section("Foo", section)
    assert "sandbox" not in trustfile.resolve_settings(parsed["opts"], "linux")


# ---------------------------------------------------------------- install wiring (17.4)

def test_activate_generates_launcher_and_points_everything_at_it(tmp_path, monkeypatch):
    from appkata_core import install
    monkeypatch.setattr(sb, "have_tools", lambda: True)          # pretend bwrap/proxy are present
    monkeypatch.setattr(sb, "sandboxes_root", lambda: str(tmp_path / "sandboxes"))
    monkeypatch.setattr(install, "desktop_dir", lambda: str(tmp_path / "applications"))
    root = tmp_path / "apps"
    target = root / "demo"
    vdir = target / "1.0" / "bin"
    vdir.mkdir(parents=True)
    exe = vdir / "demo"
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    rec = {"current": {"version": "1.0", "path": str(target / "1.0"), "exec": "1.0/bin/demo"},
           "links": [], "files": []}
    app = {"name": "Demo", "sandbox": sb.to_json(sb.resolve_template("messenger"))}
    port = install.Portable(folder=str(root), app_menu=True, command_dir=str(tmp_path / "cmd"), stable_name=False)
    install._activate(rec, app, port, str(target))
    launcher = str(target / "run")
    assert rec["exec"] == launcher and os.path.exists(launcher) and os.access(launcher, os.X_OK)
    assert rec["sandbox"]["level"] == "standard"
    # the .desktop entry and the command link point at the launcher, not the program
    desktop = next(f for f in rec["files"] if f.endswith(".desktop"))
    assert launcher in open(desktop).read()
    cmd_link = os.path.join(str(tmp_path / "cmd"), "demo")
    assert os.path.realpath(cmd_link) == os.path.realpath(launcher)
    # the identity marker was written outside the private home (the app can't touch it)
    assert os.path.exists(sb.identity_path("demo"))
    assert not os.path.lexists(os.path.join(sb.sandbox_home("demo"), ".flatpak-info"))


def test_off_uses_the_program_directly_no_launcher(tmp_path, monkeypatch):
    from appkata_core import install
    monkeypatch.setattr(sb, "have_tools", lambda: True)
    monkeypatch.setattr(sb, "sandboxes_root", lambda: str(tmp_path / "sandboxes"))
    monkeypatch.setattr(install, "desktop_dir", lambda: str(tmp_path / "applications"))
    target = tmp_path / "apps" / "demo"
    (target / "1.0" / "bin").mkdir(parents=True)
    exe = target / "1.0" / "bin" / "demo"
    exe.write_text("#!/bin/sh\n"); exe.chmod(0o755)
    rec = {"current": {"version": "1.0", "path": str(target / "1.0"), "exec": "1.0/bin/demo"}, "links": [], "files": []}
    app = {"name": "Demo", "sandbox": {"level": "off"}}
    port = install.Portable(folder=str(tmp_path / "apps"), app_menu=True, command_dir="", stable_name=False)
    install._activate(rec, app, port, str(target))
    assert not os.path.exists(str(target / "run"))              # Off bypasses the launcher
    assert rec["exec"].endswith("1.0/bin/demo")
    assert "sandbox" not in rec
    # Round four, R4-7: switching an app to Off removed the launcher but left .identity/<app>
    # behind (R10 had made uninstall remove it); the marker belongs with the launcher.
    app["sandbox"] = sb.to_json(sb.resolve_template("standard"))
    install._activate(rec, app, port, str(target))
    assert os.path.exists(str(target / "run")) and os.path.exists(sb.identity_path("demo"))
    app["sandbox"] = {"level": "off"}
    install._activate(rec, app, port, str(target))
    assert not os.path.exists(str(target / "run")) and not os.path.lexists(sb.identity_path("demo"))


def test_network_launcher_binds_where_resolv_conf_really_lives():
    text = sb.build_launcher("web", "Web", "/apps/web/1", "bin/web", sb.resolve_template("online-app"))
    assert "readlink -f /etc/resolv.conf" in text
    assert "set -- --ro-bind /run/systemd/resolve /run/systemd/resolve" in text
    assert _valid_sh(text)
    offline = sb.build_launcher("ed", "Ed", "/apps/ed/1", "bin/ed", sb.resolve_template("offline-editor"))
    assert "resolv.conf" not in offline                  # no network, no DNS


def test_proxy_args_are_names_xdg_dbus_proxy_accepts():
    # xdg-dbus-proxy accepts a bus name, optionally ending in ".*"; anything else (e.g. "Item-*") makes
    # it exit, taking the app's whole session bus with it.
    import re
    name = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*(\.[A-Za-z_-][A-Za-z0-9_-]*)+(\.\*)?$")
    for cap in sb.CAP_PROXY_ARGS:
        for a in sb.proxy_args({"caps": [cap]}, "demo")[1:]:
            # a --call/--broadcast rule is NAME=RULE; the name part is what must be valid
            assert name.match(a.split("=", 2)[1]), a
    assert "--own=org.kde.StatusNotifierItem-2-1" in sb.CAP_PROXY_ARGS["tray"]


def test_play_only_sound_is_not_shown_as_blocking_the_microphone():
    # PipeWire/WirePlumber let a sandboxed client record through the sockets it plays through (17.8),
    # so the summary says so rather than implying play-only protects the microphone.
    assert "Sound · can also record" in sb.summary(sb.resolve_template("online-app"))
    assert "Sound and microphone" in sb.summary(sb.resolve_template("messenger"))
    assert not any("ound" in c for c in sb.summary(sb.resolve_template("offline-editor")))


def test_an_off_review_adds_no_limit_of_its_own():
    # Regression: Off's grant set is empty, and intersecting with it literally stripped everything —
    # off ∩ online-app gave Standard with no network, sound or notifications, stricter than either.
    _, gs = sb.resolve(reviews=[{"template": "off", "overrides": {}}, {"template": "online-app", "overrides": {}}])
    assert gs == sb.resolve_template("online-app")
    _, gs = sb.resolve(reviews=[{"template": "online-app", "overrides": {}}, {"template": "off", "overrides": {}}])
    assert gs == sb.resolve_template("online-app")
    _, gs = sb.resolve(reviews=[{"template": "off", "overrides": {}}, {"template": "off", "overrides": {}}])
    assert sb.level_of(gs) == "off"


def _run_bpf(prog: bytes, arch: int, nr: int, arg1: int) -> int:
    """A minimal classic-BPF interpreter for the instructions the seccomp filter uses."""
    import struct
    data = struct.pack("=iI", nr, arch) + b"\0" * 8 + struct.pack("=QQQQQQ", 0, arg1, 0, 0, 0, 0)
    ins = [struct.unpack("=HBBI", prog[i:i + 8]) for i in range(0, len(prog), 8)]
    pc, acc = 0, 0
    while True:
        code, jt, jf, k = ins[pc]
        if code == 0x20:                         # ld [k]
            acc = struct.unpack_from("=I", data, k)[0]
            pc += 1
        elif code == 0x15:                       # jeq #k
            pc += 1 + (jt if acc == k else jf)
        elif code == 0x06:                       # ret #k
            return k
        else:
            raise AssertionError(f"unexpected opcode {code:#x}")


@pytest.mark.parametrize("machine,abis", [("x86_64", {"x86_64": 0xC000003E, "i386": 0x40000003}),
                                          ("aarch64", {"aarch64": 0xC00000B7, "arm": 0x40000028})])
def test_seccomp_filter_refuses_terminal_injection_on_every_abi(machine, abis):
    prog = sb.seccomp_filter(machine)
    allow, deny = 0x7FFF0000, 0x00050001
    ioctl = {"x86_64": [16, 0x40000000 | 514], "i386": [54], "aarch64": [29], "arm": [54]}
    for abi, arch in abis.items():
        for nr in ioctl[abi]:
            assert _run_bpf(prog, arch, nr, 0x5412) == deny                       # TIOCSTI
            assert _run_bpf(prog, arch, nr, 0x541C) == deny                       # TIOCLINUX
            assert _run_bpf(prog, arch, nr, 0xFFFFFFFF_00005412) == deny          # only the low 32 bits count
            assert _run_bpf(prog, arch, nr, 0x5401) == allow                      # TCGETS etc. still work
        assert _run_bpf(prog, arch, 1, 0x5412) == allow                           # not an ioctl
    assert sb.seccomp_filter("riscv64") is None                                  # unknown: --new-session instead


def test_launcher_uses_the_filter_instead_of_a_new_session():
    text = sb.build_launcher("t", "T", "/a/t/1", "bin/t", sb.resolve_template("cli-tool"), seccomp="/f/tty.bpf")
    assert "exec 3< /f/tty.bpf" in text and "--seccomp 3" in text and "--new-session" not in text.split("--appimage")[0]
    assert "--new-session" in sb.build_launcher("t", "T", "/a/t/1", "bin/t", sb.resolve_template("cli-tool"))
    assert _valid_sh(text)


def test_settings_keys_are_lowercase_labels():
    # Labels are lowercased before lookup, so a mixed-case key can never match (a stray
    # "fedoraPackage" entry was dead code).
    assert all(k == k.lower() for k in trustfile.SETTINGS_KEYS)


def test_every_template_can_be_named_in_a_review():
    # Regression: trustfile's list left out "standard", so `- Sandbox: standard` was silently ignored
    # although the sandbox module (and the dialog) offer it.
    assert set(trustfile.SANDBOX_TEMPLATES) == set(sb.TEMPLATE_ORDER)
    parsed, warns = trustfile.parse_section("Foo", "## Foo::Settings\n\n- Sandbox (linux): standard\n")
    opts = trustfile.resolve_settings(parsed["opts"], "linux")
    assert opts["sandbox"] == "standard" and sb.config_from_review(opts)["template"] == "standard"


def test_uninstall_keeps_the_private_home_until_the_app_is_really_gone(tmp_path, monkeypatch):
    # Regression: "also delete its private home" deleted it first, before steps that can refuse or fail,
    # so a failed uninstall lost the app's data while the app stayed installed.
    import json as _json
    from appkata_core import install
    from appkata_core.db import DB, now
    monkeypatch.setattr(sb, "sandboxes_root", lambda: str(tmp_path / "sandboxes"))
    monkeypatch.setattr(install, "OS", "linux")
    db = DB(str(tmp_path / "a.db"))
    home = sb.sandbox_home("demo")
    os.makedirs(home)
    db.x("INSERT INTO installs(url, name, version, kind, record, installed_at) VALUES(?,?,?,?,?,?)",
         ("u", "Demo", "1", "package", _json.dumps({"package": "demo"}), now()))
    monkeypatch.setattr(install, "uninstall_blocker", lambda rec: "it's needed by something else")
    with pytest.raises(install.InstallError):
        install.uninstall(db, "u", remove_sandbox=True)
    assert os.path.isdir(home)                          # still installed, so its data stays
    db.x("UPDATE installs SET record=? WHERE url=?", (_json.dumps({"files": []}), "u"))
    install.uninstall(db, "u", remove_sandbox=True)
    assert not os.path.exists(home)


def test_uninstall_keeping_the_home_still_removes_the_identity_marker(tmp_path, monkeypatch):
    # Round two, R10: the marker was only unlinked with the private home, so "uninstall, keep its
    # data" left .identity/<app> behind for good. It belongs with the launcher: gone on uninstall.
    import json as _json
    from appkata_core import install
    from appkata_core.db import DB, now
    monkeypatch.setattr(sb, "sandboxes_root", lambda: str(tmp_path / "sandboxes"))
    monkeypatch.setattr(install, "OS", "linux")
    db = DB(str(tmp_path / "a.db"))
    home = sb.sandbox_home("demo")
    os.makedirs(home)
    sb.write_flatpak_info("demo")
    assert os.path.exists(sb.identity_path("demo"))
    db.x("INSERT INTO installs(url, name, version, kind, record, installed_at) VALUES(?,?,?,?,?,?)",
         ("u", "Demo", "1", "appimage", _json.dumps({"files": []}), now()))
    install.uninstall(db, "u")                             # the home is kept ...
    assert os.path.isdir(home) and not os.path.lexists(sb.identity_path("demo"))     # ... the marker is not


def test_removing_a_kept_appimage_version_drops_its_whole_cache(tmp_path):
    from appkata_core import install
    img = tmp_path / "App-1.0.AppImage"
    img.write_text("x")
    cache = sb.extracted_dir(str(tmp_path), "1.0")
    os.makedirs(cache)
    for extra in (".stamp", ".lock"):
        open(cache + extra, "w").close()
    install._remove_extracted({"path": str(img), "version": "1.0"})
    assert not any(os.path.exists(cache + e) for e in ("", ".stamp", ".lock"))


# ---------------------------------------------------------------- the document portal & identity (17.6)

def test_standard_launcher_binds_the_apps_document_portal_view():
    # Regression: the launcher never bound the document portal's FUSE export, so the path a portal
    # file chooser returns ($XDG_RUNTIME_DIR/doc/<id>/<name>) didn't exist inside the sandbox. With
    # folder grants all default Off, a Standard app couldn't open any user file at all.
    text = sb.build_launcher("web", "Web", "/apps/web/1", "bin/web", sb.resolve_template("online-app"))
    assert '--bind-try "$rt/doc/by-app/$id" "$rt/doc"' in text       # this app's documents only
    assert "GTK_USE_PORTAL" not in text        # the app's own dialog shows that view (17.6.3, finding 0)
    # round six, R6-4: GTK 4.18 shows no dialog when the portal is denied; GDK_DEBUG=no-portals makes
    # GTK4 not ask, at every level, after --clearenv so it survives
    assert "--setenv GDK_DEBUG no-portals" in text and text.index("--clearenv") < text.index("GDK_DEBUG no-portals")
    assert "--setenv GDK_DEBUG no-portals" in sb.build_launcher("v", "V", "/apps/v/1", "bin/v", sb.resolve_template("strict"))
    assert text.index('--dir "$rt"') < text.index("/doc/by-app")      # the mount point exists first
    strict = sb.build_launcher("vault", "Vault", "/apps/vault/1", "bin/vault", sb.resolve_template("strict"))
    assert "/doc" not in strict                                        # no bus, so no portals


# ---------------------------------------------------------------- portals see a host caller (17.6.1, finding 0)

def test_the_portals_see_the_app_as_a_host_caller_through_a_narrowed_proxy(tmp_path, monkeypatch):
    # Regression (review finding 0): the bus proxy carried /.flatpak-info, and xdg-desktop-portal 1.18+
    # refuses a marked caller that is not a running Flatpak ("Portal operation not allowed"), so on
    # Ubuntu 24.04 / Mint 22 no portal answered a sandboxed app at all. The proxy now has no marker --
    # the app is a host caller to the portals -- and the talk-to-everything policy on the portal name
    # became per-interface rules, since some portals trust a host caller with the host.
    monkeypatch.setattr(sb, "sandboxes_root", lambda: str(tmp_path / "sandboxes"))
    args = sb.proxy_args(sb.resolve_template("online-app"), "web")
    assert "--talk=org.freedesktop.portal.Desktop" not in args
    rules = [a for a in args if a.startswith(("--call=", "--broadcast="))]
    assert all(a.startswith(("--call=org.freedesktop.portal.Desktop=", "--broadcast=org.freedesktop.portal.Desktop=")) for a in rules)
    for allowed in ("OpenURI", "Notification", "Settings", "Request", "Session"):   # Notification: online-app's capability
        assert any(f"org.freedesktop.portal.{allowed}.*@" in a for a in rules), allowed
    for denied in ("FileChooser", "Background", "DynamicLauncher", "Documents", "Camera", "ScreenCast",
                   "RemoteDesktop", "Screenshot", "Location", "Realtime", "Account", "Trash", "DBus.Properties"):
        assert not any(denied in a for a in rules), denied
    assert all("@/org/freedesktop/portal/desktop" in a for a in rules)      # the portal objects only
    lp = sb.write_launcher("web", "Web", str(tmp_path / "apps"), "/apps/web/1", "bin/web", sb.resolve_template("online-app"))
    text = open(lp).read()
    proxy_cmd, app_cmd = text.split("xdg-dbus-proxy", 1)
    assert "/.flatpak-info" not in proxy_cmd.rsplit("bwrap", 1)[1]        # the proxy's bwrap: no marker
    assert '--ro-bind "$info" /.flatpak-info' in app_cmd                    # the app's: PipeWire's identity
    assert "$rt/flatpak-info" not in text                                   # what GTK/Qt/xdg-open would read
    # the marker tells GLib whether the app has the network (its NetworkMonitor says "offline" otherwise)
    assert "shared=network;" in open(sb.identity_path("web")).read()
    sb.write_launcher("ed", "Ed", str(tmp_path / "apps"), "/apps/ed/1", "bin/ed", sb.resolve_template("offline-editor"))
    assert "[Context]" not in open(sb.identity_path("ed")).read()
    sb.write_launcher("vault", "Vault", str(tmp_path / "apps"), "/apps/vault/1", "bin/vault",
                      {**sb.resolve_template("strict"), "network": True})
    assert "[Context]" not in open(sb.identity_path("vault")).read()       # Strict: no network, whatever is said


def test_the_hosts_desktop_entries_are_hidden_from_the_sandbox():
    # Round three, R3-1 (17.4): GLib prefers a handler it can find over the OpenURI portal, and the
    # host's /usr/share/applications is in view, so without this a GTK app opened links in the host's
    # browser started inside the sandbox. Every level gets the mask; only folders that exist are
    # masked (no --tmpfs-try, and a missing one under the read-only /usr can't be created).
    for template in ("online-app", "strict", "cli-tool"):
        text = sb.build_launcher("app", "App", "/apps/app/1", "bin/app", sb.resolve_template(template))
        assert 'for d in /usr/share/applications /usr/local/share/applications; do' in text, template
        assert 'if [ -d "$d" ]; then set -- --tmpfs "$d" "$@"; fi' in text, template
        assert _valid_sh(text)


def test_a_sandboxed_app_gets_an_xdg_open_that_asks_the_host(tmp_path, monkeypatch):
    # xdg-open from the desktop would start the host's browser inside the sandbox; the app finds
    # AppKata's first on its PATH, which goes through the OpenURI portal (17.6.3).
    monkeypatch.setattr(sb, "sandboxes_root", lambda: str(tmp_path / "sandboxes"))
    lp = sb.write_launcher("web", "Web", str(tmp_path / "apps"), "/apps/web/1", "bin/web", sb.resolve_template("online-app"))
    shim = os.path.join(sb.shims_dir(), "xdg-open")
    assert os.access(shim, os.X_OK) and _valid_sh(open(shim).read())
    assert "org.freedesktop.portal.OpenURI.OpenURI" in open(shim).read()
    text = open(lp).read()
    assert f"--ro-bind-try {sb.shims_dir()} /run/appkata" in text
    assert "--setenv PATH /run/appkata:/usr/bin:/bin:/usr/sbin:/sbin" in text
    # Round five, R5-4: a Strict app gets the shim too -- it has no bus, so the shim says so and fails,
    # where the desktop's xdg-open in /usr would start the host's browser inside the sandbox.
    strict = open(sb.write_launcher("vault", "Vault", str(tmp_path / "apps"), "/apps/vault/1", "bin/vault",
                                    sb.resolve_template("strict"))).read()
    assert f"--ro-bind-try {sb.shims_dir()} /run/appkata" in strict and "--setenv PATH /run/appkata:/usr/bin:/bin:/usr/sbin:/sbin" in strict
    # Review 3, R3-33: no bus, but an address all the same, with nothing behind it -- unset, GLib and
    # libdbus would autolaunch a bus inside the sandbox through dbus-launch
    assert '--setenv DBUS_SESSION_BUS_ADDRESS "unix:path=$rt/bus"' in strict and '--bind "$sock" "$rt/bus"' not in strict
    r = subprocess.run(["sh", shim, "https://example.com/x"], env={"PATH": os.environ["PATH"]}, capture_output=True, text=True)
    assert r.returncode == 3 and "runs Strict" in r.stderr and "https://example.com/x" in r.stderr


@pytest.mark.parametrize("slug,ident", [("obsidian", "io.appkata.obsidian"), ("local-send", "io.appkata.local-send"),
                                        ("7zip", "io.appkata._7zip")])
def test_identity_is_a_valid_bus_name(slug, ident):
    # Regression: xdg-dbus-proxy rejects an --own name whose element starts with a digit ("not a valid
    # dbus name") and exits, so an app whose name started with a digit ran with no bus at all.
    assert sb.app_identity(slug) == ident
    assert f"--own={ident}" in sb.proxy_args(sb.resolve_template("standard"), slug)
    text = sb.build_launcher(slug, slug, f"/apps/{slug}/1", "bin/x", sb.resolve_template("standard"))
    assert f"id={ident}\n" in text


# ---------------------------------------------------------------- mount destinations in the private home

def test_launcher_guards_every_mount_destination_under_home():
    # Regression: a symlink the app left in its private home at a bind destination (~/.themes, ~/bin
    # above its own version folder, ~/.Xauthority) was followed by bwrap on the host side.
    gs = sb.apply_overrides(sb.resolve_template("cli-tool"), {"folders": {"+~/Projects": "rw"}})
    text = sb.build_launcher("tool", "Tool", os.path.expanduser("~/bin/apps/tool/1.0.extracted"), "AppRun", gs,
                             appimage_path=os.path.expanduser("~/bin/apps/tool/Tool.AppImage"))
    assert "guard() {" in text and 'rm -f "$p"' in text
    for d in ('"$HOME/.themes"', '"$HOME/.icons"', '"$HOME/.fonts"', '"$HOME/.config/fontconfig"', '"$appdir"',
              '"$img"', os.path.expanduser("~/Projects")):
        assert d in text.split("do guard")[0].rsplit("\n", 1)[-1], d
    assert 'guard "$here"' in text and 'guard "$xa"' in text               # the run-time ones too
    assert text.index("do guard") < text.index("bwrap \\\n")             # before the app's bwrap
    subprocess.run(["sh", "-n"], input=text, text=True, check=True)


# ---------------------------------------------------------------- protected folders (17.3.1)

@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "run"))
    for v in ("XDG_DATA_HOME", "APPKATA_APPS", "APPKATA_DATA"):
        monkeypatch.delenv(v, raising=False)
    return tmp_path / "home"


@pytest.mark.parametrize("path,refused", [
    ("~", True), ("/", True), ("~/..", True), ("~/.ssh", True), ("~/.ssh/keys", True), ("~/.gnupg", True),
    ("~/.config", True), ("~/.config/autostart", True), ("~/.config/systemd/user", True), ("~/.local", True),
    ("~/.local/share", True), ("~/.local/share/applications", True), ("~/.local/share/appkata", True),
    ("~/.local/share/appkata/sandboxes/other", True), ("~/bin", True), ("~/bin/apps", True), ("~/bin/apps/x/1.0", True),
    ("$XDG_RUNTIME_DIR", True),
    # other ways to start again later, or to change what the user's own commands do (round two, R3)
    ("~/.local/bin", True), ("~/.local/bin/sub", True), ("~/.config/environment.d", True), ("~/.pam_environment", True),
    ("~/.config/plasma-workspace/env", True), ("~/.config/autostart-scripts", True), ("~/.local/share/flatpak", True),
    ("~/.local/share/dbus-1/services", True), ("~/.local/share/systemd/user", True),
    ("~/.gitconfig", True), ("~/.config/git", True), ("~/.bashrc", True), ("~/.profile", True), ("~/.zshenv", True),
    ("~/.config/fish", True), ("~/.xsessionrc", True), ("~/.xprofile", True),
    # the desktop's extension and script folders, and Firefox's native-messaging hosts (round four, R4-9)
    ("~/.local/share/gnome-shell/extensions", True), ("~/.local/share/gnome-shell", True), ("~/.local/share/kwin/scripts", True),
    ("~/.local/share/plasma/plasmoids", True), ("~/.local/share/nautilus/scripts", True), ("~/.local/share/kservices5", True),
    ("~/.local/share/kio/servicemenus", True), ("~/.mozilla/native-messaging-hosts", True),
    # Mint's own hooks and the Chromium family's native-messaging folders (round five, R5-2)
    ("~/.bash_aliases", True), ("~/.bashrc.d", True), ("~/.bashrc.d/10-aliases.sh", True), ("~/.local/lib", True),
    ("~/.local/lib/python3.12/site-packages", True), ("~/.local/share/nemo/scripts", True), ("~/.local/share/nemo/actions", True),
    ("~/.config/chromium/NativeMessagingHosts", True), ("~/.config/google-chrome/NativeMessagingHosts", True),
    ("~/.config/BraveSoftware/Brave-Browser/NativeMessagingHosts", True), ("~/.config/microsoft-edge/NativeMessagingHosts", True),
    ("~/Projects", False), ("~/Documents", False), ("~/.config/obsidian", False), ("/mnt/data", False), ("$cwd", False),
    ("~/.local/share/fonts", False), ("~/.config/git-extras", False), ("~/.bashrc.dev", False),
    ("~/.config/chromium", True), ("~/.config/google-chrome/Default", False), ("~/.local/share/nemo", True),   # above a hosts folder; a sibling
    ("~/.mozilla/firefox", False), ("~/.local/share/plasma/look-and-feel", False)])
def test_protected_folders_are_never_granted(fake_home, path, refused):
    # Regression: a review's `Sandbox folders` line or the Customize picker could name ~, /, ~/.ssh or
    # AppKata's own folders, and the launcher bound them as asked — `~` landing after the private home
    # put the real home back. Only the CLI tool's $cwd had a protected set. Later (R3): the list missed
    # ~/.local/bin (on PATH, so a dropped `ls` shadows the real one), the login-environment and KDE
    # login-script dirs, Flatpak's user installation, D-Bus activation, git config and the shell/session
    # startup files — a "folder" grant binds a file as readily as a folder.
    p = os.environ["XDG_RUNTIME_DIR"] if path == "$XDG_RUNTIME_DIR" else path
    assert bool(sb.protected_folder(p)) is refused, sb.protected_folder(p)
    if path in ("~/.bashrc", "~/.gitconfig"):
        (fake_home).mkdir(parents=True, exist_ok=True)
        (fake_home / path[2:]).write_text("x")           # existing or not, a file is refused the same
        assert sb.protected_folder(p) == sb.protected_folder(path)


def test_launcher_and_summary_refuse_protected_folders(fake_home):
    gs = sb.apply_overrides(sb.resolve_template("standard"),
                            {"folders": {"+~": "rw", "+~/.ssh": "ro", "+~/Projects": "rw"}})
    text = sb.build_launcher("app", "App", str(fake_home / "bin/apps/app/1"), "bin/app", gs, apps_root=str(fake_home / "bin/apps"))
    home = str(fake_home)
    assert f"--bind-try {home}/Projects {home}/Projects" in text
    assert f"{home} {home}" not in text and "/.ssh" not in text.split("# Refused")[0]
    assert "# Refused folder grant ~: your whole home folder" in text
    assert "# Refused folder grant ~/.ssh: SSH keys" in text
    chips = sb.summary(gs)
    assert "~ · refused: your whole home folder" in chips and "~/.ssh · refused: SSH keys" in chips
    assert "~/Projects" in chips
    kept, refused = sb.strip_protected(gs)
    assert set(kept["folders"]) == {"~/Projects"} and [p for p, _ in refused] == ["~", "~/.ssh"]

    # Round two, R9: under a custom install folder (Settings → Portable apps) the chips judged folders
    # against the default root while the launcher used the app's, so a grant under the custom root
    # showed as granted but was refused, and the unused default root showed as refused.
    custom = str(fake_home / "Apps")
    gs = sb.apply_overrides(sb.resolve_template("standard"), {"folders": {"+~/Apps/x": "rw", "+~/bin/apps": "rw"}})
    text = sb.build_launcher("app", "App", f"{custom}/app/1", "bin/app", gs, apps_root=custom)
    assert "# Refused folder grant ~/Apps/x: AppKata's installed apps" in text and f"--bind-try {home}/bin/apps" in text
    chips = sb.summary(gs, custom)
    assert "~/Apps/x · refused: AppKata's installed apps" in chips and "~/bin/apps" in chips
    assert "~/bin/apps · refused: AppKata's installed apps" in sb.summary(gs)       # the default root, as before


def test_cli_launcher_protects_the_persistence_dirs_and_the_runtime_folder(fake_home):
    # Regression: the $cwd rule protected only the home, its ancestors and AppKata's areas, so a tool
    # run from ~/.config got autostart/ and systemd/ read-write, and one run from $XDG_RUNTIME_DIR had
    # the real session bus bound over the filtered proxy socket.
    text = sb.build_launcher("tool", "Tool", str(fake_home / "bin/apps/tool/1"), "bin/tool", sb.resolve_template("cli-tool"),
                             apps_root=str(fake_home / "bin/apps"))
    words = text.split("for d in ", 1)[1].split(";")[0]
    for p in (".config/autostart", ".config/systemd", ".local/share/applications", ".ssh", ".gnupg", "bin/apps",
              ".local/share/appkata", ".local/bin", ".config/environment.d", ".config/plasma-workspace",
              ".local/share/flatpak", ".local/share/dbus-1", ".gitconfig", ".bashrc", ".profile", ".xprofile",
              ".local/share/gnome-shell/extensions", ".local/share/kwin/scripts", ".mozilla/native-messaging-hosts",
              ".bash_aliases", ".bashrc.d", ".local/lib", ".local/share/nemo/scripts", ".local/share/nemo/actions",
              ".config/chromium/NativeMessagingHosts", ".config/BraveSoftware/Brave-Browser/NativeMessagingHosts"):
        assert str(fake_home / p) in words, p
    assert '"$rt"' in words


# ---------------------------------------------------------------- AppArmor setup (17.10)

def test_profile_names_the_bwrap_actually_installed(monkeypatch, tmp_path):
    # Regression: the profile hard-coded /usr/bin/bwrap, so with bwrap elsewhere it attached to nothing.
    real = tmp_path / "opt" / "bwrap"
    real.parent.mkdir()
    real.write_text("")
    link = tmp_path / "bin" / "bwrap"
    link.parent.mkdir()
    link.symlink_to(real)
    monkeypatch.setattr(sb.shutil, "which", lambda name: str(link) if name == "bwrap" else None)
    assert f"profile appkata-sandbox {real} flags=(unconfined)" in sb.profile_text()
    assert "profile appkata-sandbox /usr/bin/bwrap flags=(unconfined)" in sb.PROFILE_TEXT      # the documented shape


@pytest.mark.parametrize("works", [True, False])
def test_setup_counts_only_when_bwrap_then_works(monkeypatch, works):
    # Regression: install_profile returned True whatever the probe said afterwards, and the UI then
    # told the user sandbox support was set up while every app kept running Off.
    monkeypatch.setattr(sb, "OS", "linux")
    monkeypatch.setattr(sb.shutil, "which", lambda name: f"/usr/bin/{name}")
    ran = []
    monkeypatch.setattr(sb.subprocess, "run", lambda cmd, **kw: (ran.append(cmd), subprocess.CompletedProcess(cmd, 0, "", ""))[1])
    monkeypatch.setattr(sb, "userns_works", lambda refresh=False: works)
    if works:
        assert sb.install_profile() is True
    else:
        with pytest.raises(sb.SandboxError, match="still can't create a user namespace"):
            sb.install_profile()
    assert ran and ran[0][:2] == ["pkexec", "/bin/sh"] and "apparmor_parser -r" in ran[0][-1]


# ---------------------------------------------------------------- Ubuntu 25.04+: the system's own bwrap profile (17.10.2)

# The header lines of Ubuntu 25.04's and 26.04's /etc/apparmor.d/bwrap-userns-restrict, and a profile
# that only *names* bwrap in a rule (26.04's glycin.bwrap): only an attachment counts.
UBUNTU_BWRAP = ("abi <abi/4.0>,\ninclude <tunables/global>\n\n"
                "profile bwrap /usr/bin/bwrap flags=(attach_disconnected,mediate_deleted) {\n  allow userns,\n"
                "  allow pix /** -> &bwrap//&unpriv_bwrap,\n}\n\n"
                "profile unpriv_bwrap flags=(attach_disconnected,mediate_deleted) {\n  audit deny capability,\n}\n")
GLYCIN = "profile :glycin:bwrap flags=(attach_disconnected) {\n  /{,usr/}bin/bwrap mr,\n}\n"


def _apparmor_dir(tmp_path, monkeypatch, files: dict):
    d = tmp_path / "apparmor.d"
    (d / "disable").mkdir(parents=True)
    for name, text in files.items():
        (d / name).write_text(text)
    monkeypatch.setattr(sb, "APPARMOR_DIR", str(d))
    monkeypatch.setattr(sb, "PROFILE_PATH", str(d / "appkata-sandbox"))
    return d


def test_the_systems_own_bwrap_profile_is_found_and_nothing_else(tmp_path, monkeypatch):
    # Review 2, F2: Ubuntu 25.04 and 26.04 ship bwrap-userns-restrict. Beside it AppKata's profile left
    # bwrap able to create no user namespace at all (shown in a 26.04 KVM guest, live and after a reboot).
    d = _apparmor_dir(tmp_path, monkeypatch, {"bwrap-userns-restrict": UBUNTU_BWRAP, "glycin.bwrap": GLYCIN,
                                              "appkata-sandbox": sb.PROFILE_TEXT, "old-bwrap": "/usr/bin/bwrap {\n}\n",
                                              "flatpak": "profile flatpak /usr/bin/flatpak flags=(unconfined) {\n  userns,\n}\n"})
    (d / "disable" / "old-bwrap").symlink_to(d / "old-bwrap")          # switched off: doesn't count
    assert sb.other_bwrap_profiles() == ["bwrap-userns-restrict"]


def test_support_says_conflict_beside_the_systems_profile_and_no_inner_sandbox_under_it(tmp_path, monkeypatch):
    d = _apparmor_dir(tmp_path, monkeypatch, {"bwrap-userns-restrict": UBUNTU_BWRAP, "appkata-sandbox": sb.PROFILE_TEXT})
    monkeypatch.setattr(sb, "OS", "linux")
    monkeypatch.setattr(sb, "have_tools", lambda: True)
    monkeypatch.setattr(sb, "userns_works", lambda refresh=False: False)       # what 26.04 does with both loaded
    assert sb.support_status()["status"] == "conflict"
    (d / "appkata-sandbox").unlink()                                          # the repair
    monkeypatch.setattr(sb, "userns_works", lambda refresh=False: True)
    monkeypatch.setattr(sb, "nested_userns_works", lambda refresh=False: False)
    st = sb.support_status()
    assert st["status"] == "ok" and st["innerSandbox"] is False and st["otherProfiles"] == ["bwrap-userns-restrict"]


def test_the_setup_is_refused_beside_the_systems_own_profile(tmp_path, monkeypatch):
    _apparmor_dir(tmp_path, monkeypatch, {"bwrap-userns-restrict": UBUNTU_BWRAP})
    monkeypatch.setattr(sb, "OS", "linux")
    ran = []
    monkeypatch.setattr(sb.subprocess, "run", lambda cmd, **kw: (ran.append(cmd), subprocess.CompletedProcess(cmd, 0, "", ""))[1])
    with pytest.raises(sb.SandboxError, match="its own AppArmor profile for bwrap"):
        sb.install_profile()
    assert ran == []                                                           # no password prompt, nothing written


@pytest.mark.parametrize("check", ["passes", "fails", "no-setpriv"])
def test_a_setup_whose_check_fails_for_the_user_leaves_nothing_installed(tmp_path, monkeypatch, check):
    # Review 2, F2: install_profile() checked bwrap only after pkexec had returned, and on failure raised
    # but left the profile loaded and on disk -- on 26.04 that broke bwrap for everyone, across reboots.
    # The setup script now runs the probe as the user who asked (PKEXEC_UID) and undoes itself.
    d = _apparmor_dir(tmp_path, monkeypatch, {})
    stub, log = tmp_path / "stub", tmp_path / "log"
    stub.mkdir()
    for real in ("cat", "rm", "cut"):                                          # PATH is the stubs alone
        (stub / real).symlink_to(subprocess.run(["sh", "-c", f"command -v {real}"], capture_output=True, text=True).stdout.strip())

    def tool(name, body):
        (stub / name).write_text("#!/bin/sh\n" + body)
        (stub / name).chmod(0o755)
    tool("apparmor_parser", f'echo "apparmor_parser $*" >> {log}\n')
    tool("getent", 'echo "kata:x:1000:1001::/home/kata:/bin/sh"\n')
    if check != "no-setpriv":
        tool("setpriv", f'echo "setpriv $1 $2 $3" >> {log}\nexit {0 if check == "passes" else 1}\n')
    r = subprocess.run(["/bin/sh", "-c", sb.setup_script("/usr/bin/bwrap")], env={"PATH": str(stub), "PKEXEC_UID": "1000"},
                       capture_output=True, text=True, timeout=30)
    calls = log.read_text().splitlines()
    assert calls[0] == f"apparmor_parser -r {d / 'appkata-sandbox'}"
    if check == "fails":
        assert r.returncode == 3 and "removed again" in r.stderr, (r.returncode, r.stderr)
        assert calls[1] == "setpriv --reuid=1000 --regid=1001 --clear-groups"
        assert calls[2] == f"apparmor_parser -R {d / 'appkata-sandbox'}" and not (d / "appkata-sandbox").exists()
    else:
        assert r.returncode == 0, r.stderr
        assert (d / "appkata-sandbox").read_text() == sb.PROFILE_TEXT and not any(" -R " in c for c in calls)


def test_a_chromium_app_gets_no_sandbox_only_where_its_own_cannot_run():
    # Review 2, F2 (owner's decision): where the system's bwrap profile confines everything bwrap runs,
    # Chromium/Electron can't make their own sandbox inside AppKata's and refuse to start; they are
    # started with --no-sandbox there, still inside AppKata's. Elsewhere the launcher is unchanged.
    gs = sb.resolve_template("online-app")
    usual = sb.build_launcher("chat", "Chat", "/apps/chat/1", "bin/chat", gs)
    here = sb.build_launcher("chat", "Chat", "/apps/chat/1", "bin/chat", gs, inner_sandbox=False)
    assert "--no-sandbox" not in usual
    assert '"$appdir/chrome-sandbox"' in here and 'set -- -- "$appdir/$exe" --no-sandbox "$@"' in here
    img = sb.build_launcher("chat", "Chat", "/apps/chat/1.extracted", "AppRun", gs, "/apps/chat/Chat.AppImage", inner_sandbox=False)
    assert img.index("--appimage-extract") < img.index("chrome-sandbox")     # decided once the AppImage is unpacked


# ---------------------------------------------------------------- the smaller review notes

def test_launcher_binds_the_xdg_font_icon_and_theme_dirs_read_only():
    # User-installed fonts and cursor themes live in ~/.local/share/{fonts,icons,themes} today; only the
    # legacy dot-folders were bound, so they vanished inside sandboxed apps.
    text = sb.build_launcher("app", "App", "/apps/app/1", "bin/app", sb.resolve_template("strict"))
    for d in ("fonts", "icons", "themes"):
        assert f'--ro-bind-try "$HOME/.local/share/{d}" "$HOME/.local/share/{d}"' in text
        assert f'"$HOME/.local/share/{d}"' in text.split("do guard")[0].rsplit("\n", 1)[-1]   # guarded too


def test_extraction_is_keyed_on_the_folder_and_the_stamp_not_on_apprun():
    # A dangling or symlinked AppRun made `-e "$appdir/AppRun"` fail and the launcher re-extract on
    # every launch; the stamp (written last) already says whether the extraction is complete.
    text = sb.build_launcher("img", "Img", "/apps/img/1.0.extracted", "AppRun", sb.resolve_template("strict"),
                             appimage_path="/apps/img/Img.AppImage")
    assert '[ ! -d "$appdir" ] || [ "$(cat "$appdir.stamp" 2>/dev/null)" != "$stamp" ]' in text
    assert '-e "$appdir/AppRun"' not in text


def test_launcher_keeps_its_stderr_when_nothing_else_shows_it(fake_home, monkeypatch):
    # Regression (round two, R4): only Open in AppKata captured the launcher's output; from the app
    # menu a refused launch (bwrap, extraction) said nothing and wrote nothing. The launcher now bakes
    # in the app's log path and appends its stderr there when the desktop entry's word --appkata-menu
    # leads its arguments; AppKata's own launch hands it that file already.
    monkeypatch.setenv("APPKATA_LOG_DIR", str(fake_home / "logs"))
    text = sb.build_launcher("app", "My App", str(fake_home / "bin/apps/app/1"), "bin/app", sb.resolve_template("standard"),
                             apps_root=str(fake_home / "bin/apps"))
    assert f"log={fake_home}/logs/apps/app.log\n" in text                          # the install's id, not its name (F14)
    assert '[ /dev/fd/2 -ef "$log" ]' in text and '[ "${1:-}" = --appkata-menu ]' in text and 'exec 2>>"$log"' in text
    assert "AppKata: starting %s (from the menu)" in text and "'My App' >> \"$log\"" in text
    head, run = text.split("AppKata: running", 1)
    assert "bwrap \\" not in head.split(_GUARD_END, 1)[-1] and 'bwrap \\' in run       # the mark precedes the program
    assert text.index('if [ "$logging" = 1 ]') > text.index("guard \"$d\"; done")     # ... but follows the launcher's own work


_GUARD_END = "set -- -- \"$appdir/$exe\" \"$@\""


def test_the_menu_entry_passes_the_menu_word_only_to_a_launcher(fake_home, monkeypatch):
    # The .desktop entry of a sandboxed app tells the launcher it was started from the menu (R4); a
    # program run directly, or AppKata's own entry, gets the plain Exec line as before.
    from appkata_core import install
    monkeypatch.setenv("XDG_DATA_HOME", str(fake_home / ".local/share"))
    p = install._desktop_entry("app", "App", "/x/run", "", "An app", launcher=True)
    assert 'Exec="/x/run" --appkata-menu %U\n' in open(p).read()
    p = install._desktop_entry("app", "App", "/x/bin/app", "", "An app")
    assert 'Exec="/x/bin/app" %U\n' in open(p).read()


def test_launcher_hands_over_file_arguments_only_for_standard_apps(fake_home):
    # Round two, R7 (17.6.2): a Standard launcher runs the forwarding helper over its arguments with
    # the granted folders (and a CLI tool's directory) as "already visible"; a Strict app has no bus,
    # so no document portal, so no block. The helper is written beside the seccomp filter.
    gs = sb.apply_overrides(sb.resolve_template("standard"), {"folders": {"+~/Projects": "rw"}})
    lp = sb.write_launcher("app", "App", str(fake_home / "bin/apps"), str(fake_home / "bin/apps/app/1"), "bin/app", gs)
    text = open(lp).read()
    helper = sb.forward_path()
    assert os.path.exists(helper) and "org.freedesktop.portal.Documents" in open(helper).read()
    assert f'python3 {helper} "$id" "$rt" "" {fake_home}/Projects -- "$@"' in text
    assert text.index("forward-files.py") < text.index('set -- -- "$appdir/$exe" "$@"')     # before the words are fixed
    assert text.index("--appkata-menu") < text.index("forward-files.py")                  # after the menu word is shifted off
    cli = sb.build_launcher("t", "T", "/x/1", "bin/t", sb.resolve_template("cli-tool"), forward=helper)
    # the tool's directory counts as visible only when the $cwd rule shares it (round three, R3-3),
    # so that rule is decided first and the forward call takes its answer
    assert f'python3 {helper} "$id" "$rt" "${{cwdvis:-}}" ${{cwdvis:+"$cwdvis"}} -- "$@"' in cli
    assert cli.index("share=1") < cli.index("forward-files.py") < cli.index('set -- --bind "$here" "$here"')
    assert _valid_sh(cli)
    assert "forward-files.py" not in sb.build_launcher("v", "V", "/x/1", "bin/v", sb.resolve_template("strict"), forward=helper)


def _forward(tmp_path, cwd, incwd, visible, args):
    helper = tmp_path / "forward-files.py"
    helper.write_text(sb.FORWARD_HELPER)
    r = subprocess.run([sys.executable, str(helper), "io.appkata.t", str(tmp_path / "run"), incwd, *map(str, visible), "--", *args],
                       cwd=str(cwd), capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    return shlex.split(r.stdout)


def test_file_arguments_in_a_granted_folder_become_the_path_the_app_sees(tmp_path):
    # Review 2, F6: a relative path or `.` from a granted folder reached the app's private home (its
    # working directory inside); review 3, R3-17: a link outside the granted folders to a file inside
    # one was passed by the link's path, which the app can't see; R3-16: an option's value was never
    # looked at. None of these needs the document portal: the app finds them under the grant's mount.
    home = tmp_path / "home"
    docs, desk = home / "Docs", home / "Desktop"
    (docs / "sub").mkdir(parents=True)
    desk.mkdir()
    (docs / "in.txt").write_text("x")
    (desk / "link.txt").symlink_to(docs / "in.txt")
    (home / "docs-link").symlink_to(docs)
    want = str(docs / "in.txt")
    assert _forward(tmp_path, docs, "", [docs], ["in.txt", "./in.txt", ".", "sub/"]) == [want, want, str(docs), str(docs / "sub") + "/"]
    assert _forward(tmp_path, docs / "sub", "", [docs], ["../in.txt"]) == [want]
    assert _forward(tmp_path, home, "", [docs], [str(desk / "link.txt"), str(home / "docs-link" / "in.txt")]) == [want, want]
    assert _forward(tmp_path, home, "", [docs], ["--file=" + str(desk / "link.txt"), "-o" + str(desk / "link.txt")]) == \
        ["--file=" + want, "-o" + want]
    # unchanged: already the app's path (as a path, a URI, with a trailing slash), not a file, not there
    same = [want, "file://" + want, str(docs / "sub") + "/", "https://example.org/x", str(home / "nothing.txt"), "-v", "--level=3"]
    assert _forward(tmp_path, home, "", [docs], same) == same


def test_a_grant_reached_through_a_linked_home_maps_to_where_the_launcher_mounts_it(tmp_path):
    # Fedora Silverblue: /home links to /var/home. The grant is mounted at the path as written, so a
    # file named by its real path becomes that path, never the other way round
    real = tmp_path / "var" / "home" / "u"
    (real / "Docs").mkdir(parents=True)
    (real / "Docs" / "in.txt").write_text("x")
    (tmp_path / "home").symlink_to(tmp_path / "var" / "home")
    written = tmp_path / "home" / "u" / "Docs"
    assert _forward(tmp_path, tmp_path, "", [written], [str(real / "Docs" / "in.txt")]) == [str(written / "in.txt")]


def test_a_cli_tools_relative_paths_in_its_shared_folder_stay_as_typed(tmp_path):
    # inside, the tool runs in the same folder, so `find .` and `git add src/` must see what was typed
    proj = tmp_path / "proj"
    (proj / "src").mkdir(parents=True)
    (proj / "a.txt").write_text("x")
    assert _forward(tmp_path, proj, str(proj), [proj], ["a.txt", ".", "src/"]) == ["a.txt", ".", "src/"]


def test_the_field_test_runs_each_check_under_the_template_it_names(tmp_path):
    # Review 3, R3-11: the probe has one launcher, rewritten per template, and checks were handed its
    # path, so every Strict check after the first Online app one ran Online app (D-nosound reported a
    # false LEAK wherever pactl exists). A check now names its template, and the probe rewrites the
    # launcher whenever that changes. Run in a subprocess: importing the field test moves HOME.
    code = """
import sys
sys.argv = ["fieldtest"]
import fieldtest as ft
written = []
ft.install.rewrite_launcher = lambda db, app, portable: written.append(ft.sb.normalize(app["sandbox"])["network"]) or {"launcher": "/x/run"}
ft.subprocess.run = lambda argv, **kw: ft.subprocess.CompletedProcess(argv, 0, "", "")
p = ft.Probe.__new__(ft.Probe)
p.db, p.app, p.portable, p.current, p.launcher = None, {"url": "u", "name": "P"}, None, "strict", "/x/run"
for t in ("strict", "online-app", "online-app", "strict", "cli-tool", "strict"):
    p.run(t, "true")
print(written)
"""
    root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60, cwd=str(tmp_path),
                       env={**os.environ, "PYTHONPATH": os.pathsep.join([os.path.join(root, "scripts", "sandbox"), os.path.join(root, "src")]),
                            "HOME": str(tmp_path), "TMPDIR": str(tmp_path)})
    assert r.returncode == 0, r.stderr
    # rewritten on each change of template, and only then: Online app (network), Strict, CLI tool, Strict
    assert r.stdout.strip().splitlines()[-1] == "[True, False, False, False]", r.stdout


# ---------------------------------------------------------------- the session warning (17.9)

@pytest.mark.parametrize("display,session,desktop,expect", [
    ("x11", "x11", "X-Cinnamon", "x11"), ("x11", "x11", "GNOME", "x11"), ("x11", "", "", "x11"),
    ("x11", "tty", "", "x11"),                      # startx from a console: logind's type stays tty (R3-13)
    ("wayland", "wayland", "GNOME", None), ("wayland", "wayland", "ubuntu:GNOME", None),
    ("wayland", "wayland", "GNOME-Classic:GNOME", None),
    ("wayland", "wayland", "KDE", "wayland"),       # round seven, R7-1: kwin offers the clipboard to every client
    ("wayland", "wayland", "sway", "wayland"), ("wayland", "wayland", "Hyprland", "wayland"),
    ("wayland", "wayland", "niri", "wayland"), ("wayland", "wayland", "", "wayland"),
    ("wayland", "wayland", "COSMIC", "wayland"), ("wayland", "wayland", "X-Cinnamon", "wayland"),
    ("wayland", "wayland", "Weston", "wayland"),
    ("wayland", "tty", "", "wayland"),              # sway from a TTY: logind's tty, no desktop name (R3-13)
    ("wayland", "", "", "wayland"),                 # ... and with no logind session at all
    ("wayland", "tty", "Hyprland", "wayland"),
    ("wayland-gone", "wayland", "sway", "x11"),     # WAYLAND_DISPLAY names no socket: the launcher gives X11
    ("none", "wayland", "GNOME", None), ("none", "tty", "", None)])
def test_the_display_leak_warning_clears_only_gnome_wayland(monkeypatch, tmp_path, display, session, desktop, expect):
    # Regression (round five, R5-1): the Wayland branch warned only when XDG_CURRENT_DESKTOP named one
    # of seven wlroots compositors, so sway started from a TTY (no variable), COSMIC, Cinnamon's
    # Wayland session and any compositor outside the list were reported as clear -- the same as GNOME
    # and KDE, the only two known to withhold the screen, the clipboard and input from a client. The
    # rule is now an allowlist: everything else on Wayland warns, naming the compositor when known.
    # Round seven, R7-1: KDE left the allowlist -- kwin offers the clipboard-manager protocol to
    # every client -- and gets a warning that names the clipboard alone. Review 3, R3-13: the session
    # is the display the launcher gives, not XDG_SESSION_TYPE, which a console start leaves as tty.
    monkeypatch.setattr(sb, "OS", "linux")
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    monkeypatch.setenv("XDG_SESSION_TYPE", session)
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", desktop)
    for v in ("WAYLAND_DISPLAY", "DISPLAY"):
        monkeypatch.delenv(v, raising=False)
    if display.startswith("wayland"):
        monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
        if display == "wayland":
            (tmp_path / "wayland-0").write_text("")
    if display != "none":
        monkeypatch.setenv("DISPLAY", ":0")
    w = sb.session_warning()
    assert (w.get("session") if w else None) == expect, w
    if expect == "wayland" and "kde" in desktop.lower():
        assert w["leak"] == "clipboard" and "clipboard" in w["text"] and "keystrokes are protected" not in w["text"]
        assert "the screen and your keystrokes" in w["text"]
    elif expect == "wayland":
        assert "only GNOME is known to block all three" in w["text"]
        if desktop:
            assert w["compositor"] == desktop.lower().split(":")[0] and desktop.lower().split(":")[0] in w["text"]
        else:
            assert "this Wayland compositor" in w["text"]
    if expect == "wayland" and desktop.lower() in ("sway", "hyprland", "niri"):
        assert "a wlroots compositor" in w["text"]


@pytest.mark.parametrize("addr,warns", [
    ("unix:path=/run/user/1000/bus", False),                              # systemd's user bus: a desktop's login
    ("unix:abstract=/tmp/dbus-AbCdEf,guid=0123", True),                   # dbus-run-session / dbus-launch on dbus 1.12
    ("unix:path=/tmp/dbus-AbCdEf,guid=0123", False),                      # the same on dbus 1.14 and later
    ("unix:path=/run/user/1000/bus;unix:abstract=/tmp/dbus-x", True),     # any address of a list counts
    ("", False),
])
def test_the_bus_warning_is_said_only_for_an_abstract_session_bus(monkeypatch, addr, warns):
    # Review 3, R3-8: with the network grant an app reaches every abstract socket on the host, and an
    # abstract session bus is reached past the filtering proxy (17.9, 17.5)
    monkeypatch.setattr(sb, "OS", "linux")
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", addr)
    w = sb.bus_warning()
    assert bool(w) is warns
    if warns:
        assert "bus filter doesn't hold" in w["text"] and "offline" in w["text"]
    monkeypatch.setattr(sb, "OS", "windows")
    assert sb.bus_warning() == {}


def test_the_warning_is_quiet_with_no_display_and_off_linux(monkeypatch):
    monkeypatch.setattr(sb, "OS", "linux")
    monkeypatch.delenv("XDG_SESSION_TYPE", raising=False)
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    assert sb.session_warning() == {}
    monkeypatch.setattr(sb, "OS", "windows")
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    assert sb.session_warning() == {}


# ---------------------------------------------------------------- rewriting a launcher that is running (17.4)

def test_a_launcher_is_replaced_not_truncated_so_a_running_copy_keeps_its_text(tmp_path, monkeypatch):
    # Regression (round five, R5-3): write_launcher opened ~/bin/apps/<app>/run with "w", truncating the
    # inode every running instance's shell has open; a shell that had not yet read its teardown then
    # found EOF (no `kill "$proxy"`, no `exit $status`: exit 0, the socket left behind) or executed the
    # new text at its old offset. Writing beside and renaming over keeps the old inode whole for the
    # shells that hold it; only a new launch reads the new text.
    monkeypatch.setattr(sb, "sandboxes_root", lambda: str(tmp_path / "sandboxes"))
    root = tmp_path / "apps"
    first = sb.write_launcher("app", "App", str(root), str(root / "app/1.0"), "bin/app", sb.resolve_template("strict"))
    with open(first) as held:                       # a running launcher's shell holds the file like this
        ino = os.stat(first).st_ino
        old_text = held.read()
        held.seek(0)
        second = sb.write_launcher("app", "App", str(root), str(root / "app/1.0"), "bin/app", sb.resolve_template("online-app"))
        assert second == first
        assert os.stat(first).st_ino != ino                                  # a new inode, renamed over
        assert held.read() == old_text                                       # the held one is intact, whole
        assert "xdg-dbus-proxy" in open(first).read() and "xdg-dbus-proxy" not in old_text   # a new launch gets the new text
    assert os.access(first, os.X_OK) and not [p for p in os.listdir(root / "app") if p.endswith(".tmp")]


def test_every_file_a_running_app_may_hold_open_is_replaced_never_truncated(tmp_path, monkeypatch):
    # The class behind round five's R5-3, as an invariant over every writer rather than the one
    # that was caught: a running app's shell holds the launcher, bwrap holds the marker and the
    # seccomp filter, the launcher holds the helper and the shim at the moment it runs them. Each
    # writer must write beside and rename over, so what a running process holds stays whole and the
    # new text reaches the next launch only. A writer that truncates in place fails here.
    monkeypatch.setattr(sb, "sandboxes_root", lambda: str(tmp_path / "sandboxes"))
    monkeypatch.setattr(sb, "seccomp_filter", lambda machine=None: b"\0" * 8)
    root = str(tmp_path / "apps")
    writers = {
        "launcher": lambda: sb.write_launcher("app", "App", root, f"{root}/app/1.0", "bin/app", sb.resolve_template("strict")),
        "marker": lambda: sb.write_flatpak_info("app", network=False),
        "seccomp": sb.write_seccomp_filter,
        "forward helper": sb.write_forward_helper,
        "xdg-open shim": lambda: os.path.join(sb.write_shims(), "xdg-open"),
    }
    for name, write in writers.items():
        path = write()
        with open(path, "rb") as held:
            ino = os.stat(path).st_ino
            before = held.read()
            held.seek(0)
            assert write() == path
            assert os.stat(path).st_ino != ino, f"{name}: rewritten in place"
            assert held.read() == before, f"{name}: the held copy changed"
        assert not [p for p in os.listdir(os.path.dirname(path)) if p.endswith(".tmp")], name


# ---------------------------------------------------------------- what a review may do on its own (17.3, review 2 F8)

def test_a_review_saying_off_is_only_a_suggestion_and_the_reviewed_baseline_applies():
    # Review 2, F8 (owner's decision): one Trust's `Sandbox: off` turned a fresh install's sandbox off
    # with no click. A review may narrow freely; Off is applied only when the user adopts it.
    default = sb.default_template(False, reviewed=True)
    src, gs, tpl = sb.choose(None, None, [{"template": "off", "overrides": {}}], default)
    assert (src, gs["level"], tpl) == ("default", "standard", "standard")
    cli = sb.default_template(True, reviewed=True)
    assert sb.choose(None, None, [{"template": "off", "overrides": {}}], cli, is_cli=True)[2] == "cli-tool"
    # beside another Trust's review, off still adds no limit of its own: the other one applies
    src, gs, _ = sb.choose(None, None, [{"template": "off", "overrides": {}}, {"template": "messenger", "overrides": {}}], default)
    assert src == "reviews" and "camera" in gs["devices"]
    assert sb.choose({"template": "off"}, None, [{"template": "off", "overrides": {}}], default)[1]["level"] == "off"   # the user's own


SECRETS = ["~/.mozilla/firefox", "~/snap/firefox/common/.mozilla/firefox", "~/.var/app/org.signal.Signal", "~/.thunderbird",
           "~/.aws", "~/.config/gh", "~/.config/gcloud", "~/.git-credentials", "~/.netrc", "~/.docker", "~/.kube",
           "~/.password-store", "~/.local/share/keyrings", "~/.var"]


@pytest.mark.parametrize("path", SECRETS)
def test_a_secret_folder_is_one_a_review_cannot_grant_but_the_user_can(path, fake_home):
    assert sb.secret_folder(path), path
    assert not sb.protected_folder(path), path                       # not never-shared: the user's picker may grant it
    gs = sb.apply_overrides(sb.resolve_template("standard"), {"folders": {"+" + path: "ro", "+~/Documents": "rw"}})
    kept, refused = sb.strip_secrets(gs)
    assert path not in kept["folders"] and "~/Documents" in kept["folders"] and [p for p, _ in refused] == [path]
    chip = next(c for c in sb.summary_chips(gs) if c[0].startswith(path))                   # the user's own grant
    assert "passwords or tokens" in chip[0] and chip[2] == "warn"
    assert any(c[0].startswith(path + " · refused") for c in sb.refused_chips(refused))      # a review's, refused


def test_ordinary_folders_are_no_secrets(fake_home):
    for p in ("~/Documents", "~/Projects/x", "~/.config/obsidian", "/media/usb", "~/.mozilla-backup"):
        assert not sb.secret_folder(p), p


def test_the_user_folders_are_this_systems_own_names_and_only_those_that_exist(tmp_path, monkeypatch):
    # Review 2, F10 (decision 4): one-click Documents, Downloads, Pictures, Videos and Music, under the
    # names this system gives them (a German desktop's Dokumente), from ~/.config/user-dirs.dirs
    home = tmp_path / "home"
    for d in ("Dokumente", "Bilder", "Musik", "Downloads"):
        (home / d).mkdir(parents=True)
    (home / ".config").mkdir()
    (home / ".config" / "user-dirs.dirs").write_text(
        '# written by xdg-user-dirs-update\nXDG_DOCUMENTS_DIR="$HOME/Dokumente"\nXDG_PICTURES_DIR="$HOME/Bilder"\n'
        'XDG_MUSIC_DIR="$HOME/Musik"\nXDG_VIDEOS_DIR="$HOME/Videos"\nXDG_DESKTOP_DIR="$HOME/"\nXDG_DOWNLOAD_DIR="$HOME/"\n')
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    got = sb.user_folders(str(home))
    # Videos is named but missing; Download names the home itself, which means "none" (and ~/Downloads
    # isn't it then)
    assert got == [{"key": "DOCUMENTS", "label": "Dokumente", "path": "~/Dokumente"},
                   {"key": "PICTURES", "label": "Bilder", "path": "~/Bilder"},
                   {"key": "MUSIC", "label": "Musik", "path": "~/Musik"}]
    (home / ".config" / "user-dirs.dirs").unlink()                       # no file: the English names
    assert [f["path"] for f in sb.user_folders(str(home))] == ["~/Downloads"]


@pytest.mark.parametrize("template", sorted(sb.FOLDER_TEMPLATES))
def test_a_folder_template_says_no_folder_yet_until_it_has_one(template):
    # Review 2, F10: three templates promised a folder they don't have; the summary says so now
    gs = sb.resolve_template(template)
    assert "No folder yet" in sb.summary(gs, template=template) and "No folder yet" not in sb.summary(gs)
    with_one = sb.apply_overrides(gs, {"folders": {"+~/Documents": sb.FOLDER_TEMPLATES[template]["mode"]}})
    assert "No folder yet" not in sb.summary(with_one, template=template)
    assert "No folder yet" not in sb.summary(sb.resolve_template("online-app"), template="online-app")


def test_the_review_badge_says_what_a_suggestion_adds_and_removes_and_what_that_means():
    # Review 2's nit: 17.11 said the UI tells the app "may be partly non-functional until reviewed"; the
    # badge listed the whole suggestion and said nothing of the kind, and the sentence is only true one
    # way round: with less access suggested, the app works but has more than the reviewers think it needs
    r = sb.resolve_template
    more = sb.suggestion_text(r("offline-editor"), r("online-app"), "Alice")
    less = sb.suggestion_text(r("online-app"), r("strict"), "Bob")
    both = sb.suggestion_text(r("messenger"), sb.apply_overrides(r("messenger"), {"network": False, "folders": {"+~/Notes": "rw"}}), "Grace")
    assert more == "Alice suggests adding the network, sound and notifications. Until you review it, the app may not work fully."
    assert less == ("Bob suggests Strict instead of Standard, removing the network, sound and notifications. "
                    "The app may have more access than it needs.")
    assert both == ("Grace suggests adding ~/Notes (read-write) and removing the network. Until you review it, the app may "
                    "not work fully. The app may have more access than it needs.")
    assert sb.suggestion_text(r("strict"), r("off"), "Dan") == \
        "Dan suggests running it with no sandbox. Until you review it, the app may not work fully."
    assert sb.suggestion_text(r("strict"), r("strict")) == ""
