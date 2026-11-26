"""App sandboxing (R17): grant-set resolution, overrides, the launcher, and the review lines."""

import fnmatch
import itertools
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time

import pytest

from appkata_core import sandbox as sb
from appkata_core import trustfile
from test_install_review import _tarball, server   # noqa: F401
import written

pytestmark = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="the sandbox and its launchers are Linux-only (R17.1)")


# ---------------------------------------------------------------- templates & resolution (R17.3)

def test_templates_resolve_to_normalized_grant_sets():
    for name in sb.TEMPLATE_ORDER:
        gs = sb.resolve_template(name)
        assert set(gs) == {"level", "folders", "network", "ports", "sound", "devices", "caps", "mpris_name", "exec_deny", "write_app"}
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
    src, gs = sb.resolve(is_cli=False)                 # unreviewed GUI → strict (R17.3.3)
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
    # review (baseline Standard/cli-tool, R17.3.3). Regression: the backend passed the user's kind
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


# ---------------------------------------------------------------- the launcher (R17.4, R17.5, R17.7)

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
    assert "xdg-dbus-proxy" in text                      # filtered session bus (R17.5)
    assert "--own=io.appkata.signal" in text             # app identity on the bus
    assert "--call=org.kde.StatusNotifierWatcher=org.kde.StatusNotifierWatcher.*@/StatusNotifierWatcher" in text  # the tray capability
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
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for tool in ("mkdir", "stat", "date", "mv", "id", "cat"):           # what the launcher's preamble uses
        if shutil.which(tool):
            (bindir / tool).symlink_to(shutil.which(tool))
    # the machine's command folders, which the launcher takes as its PATH (CR1.5-31): no bwrap in them
    monkeypatch.setattr(sb, "host_path", lambda apps_root=None: str(bindir))
    lp = sb.write_launcher("demo", "Demo App", str(home / "bin/apps"), str(home / "bin/apps/demo/1"), "bin/demo",
                           sb.resolve_template("strict"))
    env = {"PATH": os.environ["PATH"], "HOME": str(home), "XDG_RUNTIME_DIR": str(rt)}
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
    # network and services the launcher never gave. Strict now means R17.2's table everywhere.
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
    assert "--appimage-extract" in text                  # lazy extraction (R17.7)
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
    assert 'upstream="${DBUS_SESSION_BUS_ADDRESS:-unix:path=$rt/bus}"' in text
    assert 'kill -0 "$proxy"' in text
    assert _valid_sh(text)
    # the exact expansion tolerates an unset variable under `set -u`, and an empty one is no address either
    for unset in ("unset DBUS_SESSION_BUS_ADDRESS 2>/dev/null || true", "DBUS_SESSION_BUS_ADDRESS="):
        r = subprocess.run(["sh", "-c", f'set -eu; rt=/run/user/7; {unset}; x="${{DBUS_SESSION_BUS_ADDRESS:-unix:path=$rt/bus}}"; echo "ok:$x"'],
                           capture_output=True, text=True)
        assert r.returncode == 0 and r.stdout.strip() == "ok:unix:path=/run/user/7/bus"


# bwrap as a recorder: each call's words, a JSON line. For the proxy's own bwrap it leaves the
# socket the proxy would, so the launcher goes on to the app's. With it a generated launcher runs
# wherever `sh` does, and what it decides at run time -- from the session it finds itself in -- is
# read from the words it gives bwrap.
_RECORDER = """import json, socket, sys
argv = sys.argv[2:]
with open(sys.argv[1], "a") as f:
    f.write(json.dumps(argv) + "\\n")
if "xdg-dbus-proxy" in argv:
    socket.socket(socket.AF_UNIX).bind(argv[argv.index("xdg-dbus-proxy") + 2])
"""


def _launched(tmp_path, monkeypatch, address, template="standard", gs=None, cwd=None, tools=None,
              proxy_at="/usr/bin/xdg-dbus-proxy", app=True, hide=(), forward=None, args=(), before=None, home=None, leads=None):
    """A generated launcher run in a session whose bus is at `address` ({rt}: the runtime folder;
    None: no address set), for `template` or the grant set `gs`, from `cwd` (the home folder when
    None), with `tools` ({name: script}) first on its PATH: the words of the proxy's own bwrap (None
    where no proxy was started), the app's bwrap's (None where `app` is False and it didn't run),
    the run, and the runtime folder. The xdg-dbus-proxy its PATH finds is a stand-in that is
    really at `proxy_at` (None: no stand-in), as `readlink -f` tells the launcher (no machine's /usr
    is a test's). The
    rest of its PATH is this one's, without the programs `hide` names: a machine that lacks them.
    `forward`: the file-argument helper the launcher calls, and `args` its arguments. `before`, where
    given, is called once the launcher is written and before it runs. `home`: the user's home folder,
    tmp_path's own "home" unless given: a folder a test grants is one of the home, since everything
    else a test can make is under /tmp, which no grant shares (R17.3.1). `leads`: where each granted
    folder led when its grant was judged, as an install keeps it (sandbox.folder_leads); judged now
    where None."""
    home, rt, fake, log = home or tmp_path / "home", tmp_path / "run", tmp_path / "fakebin", tmp_path / "bwrap-words"
    home.mkdir(exist_ok=True)
    for d in (rt, fake):
        d.mkdir()
    monkeypatch.setattr(sb, "sandboxes_root", lambda: str(home / ".local/share/appkata/sandboxes"))
    monkeypatch.setenv("HOME", str(home))
    (fake / "record.py").write_text(_RECORDER)
    (fake / "bwrap").write_text(f'#!/bin/sh\nexec {shlex.quote(sys.executable)} {shlex.quote(str(fake / "record.py"))} {shlex.quote(str(log))} "$@"\n')
    (fake / "bwrap").chmod(0o755)
    if proxy_at:
        (fake / "xdg-dbus-proxy").write_text("#!/bin/sh\nexit 1\n")
        (fake / "readlink").write_text(f'#!/bin/sh\n[ "$*" = {shlex.quote("-f " + str(fake / "xdg-dbus-proxy"))} ] && exec echo {shlex.quote(proxy_at)}\n'
                                       f'exec {shlex.quote(shutil.which("readlink"))} "$@"\n')
        for tool in ("xdg-dbus-proxy", "readlink"):
            (fake / tool).chmod(0o755)
    for tool, script in (tools or {}).items():
        (fake / tool).write_text(script)
        (fake / tool).chmod(0o755)
    path = os.environ["PATH"]
    if hide:
        bare = tmp_path / "bare"
        bare.mkdir()
        for d in path.split(os.pathsep):
            for f in sorted(os.listdir(d)) if os.path.isdir(d) else ():
                if f not in hide and not os.path.lexists(bare / f):
                    (bare / f).symlink_to(os.path.join(d, f))
        path = str(bare)
    # A launcher takes its host commands from the PATH it is written with (sandbox.host_path, R17.4),
    # never from the one it is started with, so the stand-ins are given there, and in both
    lp = tmp_path / "launcher"
    lp.write_text(sb.build_launcher("demo", "Demo", str(home / "apps/demo/1"), "bin/demo", gs or sb.resolve_template(template),
                                    seccomp=str(fake / "record.py"), forward=forward,    # any file there is: nothing here reads it as a filter
                                    path=f"{fake}:{path}", **({"leads": leads} if leads is not None else {})))
    if before:
        before()
    env = {"HOME": str(home), "XDG_RUNTIME_DIR": str(rt), "PATH": f"{fake}:{path}"}
    if address is not None:
        env["DBUS_SESSION_BUS_ADDRESS"] = address.format(rt=rt)
    r = subprocess.run(["sh", str(lp), *args], env=env, cwd=str(cwd or home), capture_output=True, text=True, timeout=60)
    calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
    run = next((c for c in calls if "/.flatpak-info" in c), None)
    assert (run is not None) is app, (r.returncode, r.stdout, r.stderr)
    return next((c for c in calls if "xdg-dbus-proxy" in c), None), run, r, rt


def _binds(words: list) -> dict:
    """bwrap's binds among `words`: destination → (the option, the source)."""
    opts = ("--bind", "--bind-try", "--ro-bind", "--ro-bind-try", "--dev-bind", "--dev-bind-try")
    return {words[i + 2]: (w, words[i + 1]) for i, w in enumerate(words[:-2]) if w in opts}


# A session's bus address → the socket file the proxy has to be shown to reach it (None: an abstract
# socket, which has no file). The second and third are what `dbus-run-session -- sh -c 'echo
# $DBUS_SESSION_BUS_ADDRESS'` prints: with dbus 1.14 and later (Mint 22.3: 1.14.10), and with 1.12.
BUS_ADDRESSES = {
    "unix:path={rt}/bus": "{rt}/bus",
    "unix:path=/tmp/dbus-MZ8lHbtZ8K,guid=bc7bc2c1f523f8307163d71b6b05ecdf": "/tmp/dbus-MZ8lHbtZ8K",
    "unix:abstract=/tmp/dbus-MZ8lHbtZ8K,guid=bc7bc2c1f523f8307163d71b6b05ecdf": None,
    # `guid=` first: no program writes it, and libdbus and GIO read it all the same; the launcher
    # took `path=` and `abstract=` as an entry's first key alone (PR #694's review, P4-B1a)
    "unix:guid=bc7bc2c1f523f8307163d71b6b05ecdf,path=/tmp/dbus-MZ8lHbtZ8K": "/tmp/dbus-MZ8lHbtZ8K",
    "unix:guid=bc7bc2c1f523f8307163d71b6b05ecdf,abstract=/tmp/dbus-MZ8lHbtZ8K": None,
    # a key's name escaped: no program writes it, and GIO, the proxy's, reads it unescaped, as it
    # reads a value (PR #694's review, P6-1: the launcher matched the key as written, and started none)
    "unix:pa%74h=/tmp/dbus-MZ8lHbtZ8K,guid=bc7bc2c1f523f8307163d71b6b05ecdf": "/tmp/dbus-MZ8lHbtZ8K",
    "unix:abstr%61ct=/tmp/dbus-MZ8lHbtZ8K,guid=bc7bc2c1f523f8307163d71b6b05ecdf": None,
}


@pytest.mark.parametrize("address", [None, "", *BUS_ADDRESSES])
def test_the_proxy_is_shown_the_session_bus_wherever_its_socket_is(tmp_path, monkeypatch, address):
    # CR1.5-18: the proxy's own bwrap bound /usr, /etc and the runtime folder, so the proxy reached a
    # session bus only there (or on an abstract socket). dbus-run-session and dbus-launch listen at
    # unix:path=/tmp/dbus-… since dbus 1.14: in such a session the proxy made its socket, the
    # launcher's wait passed, and every connection the app made failed, with nothing said -- no
    # portals, no notifications, no "open on the host". And with no address set the proxy was given
    # "" rather than the runtime folder's bus. How it slipped past: every test's bus, in every tier,
    # was at $XDG_RUNTIME_DIR/bus, and tier 1 read the launcher's text, never what it does with the
    # session it starts in. This runs the launcher against each kind of address a session has.
    proxy, app, r, rt = _launched(tmp_path, monkeypatch, address)
    want = (address or "unix:path={rt}/bus").format(rt=rt)
    assert r.returncode == 0 and r.stderr == "", (r.stdout, r.stderr)
    at = proxy.index("xdg-dbus-proxy")
    assert proxy[at + 1] == want and proxy[at + 2].startswith(f"{rt}/appkata/bus-") and proxy[at + 3] == "--filter", proxy[at:at + 4]
    file = BUS_ADDRESSES.get(address or "unix:path={rt}/bus")
    shown = {dest: how for dest, how in _binds(proxy[:at]).items() if how[0] == "--ro-bind-try"}
    assert shown == ({file.format(rt=rt): ("--ro-bind-try", file.format(rt=rt))} if file else {}), shown
    # ...and the app's bus is that proxy's socket, whatever the session's own address was
    assert _binds(app)[f"{rt}/bus"] == ("--bind", proxy[at + 2])
    assert app[app.index("DBUS_SESSION_BUS_ADDRESS") + 1] == f"unix:path={rt}/bus" and "APPKATA_NO_BUS" not in app


@pytest.mark.parametrize("address", [None, *BUS_ADDRESSES])
def test_the_proxys_own_sandbox_holds_its_socket_folder_and_the_session_bus_alone(tmp_path, monkeypatch, address):
    # CR1.5-24: the proxy is the one program that parses bytes a hostile app chooses -- every D-Bus
    # message it sends -- yet its bwrap had --unshare-pid alone: the whole runtime folder read-write
    # (the ssh-agent and gpg-agent sockets, the document portal's mount, every other app's
    # sockets), the host's network and IPC, and no seccomp filter, so a fault in xdg-dbus-proxy
    # would hand the app what its own sandbox withholds. How it slipped past: the proxy's sandbox
    # was a documented shape (A1.2.3.12) that no test read; the tests of what a sandbox holds
    # (the inventory) looked at the app's bwrap alone. This holds every word of the proxy's, for
    # each kind of session bus: the binds are exactly these, and its namespaces are its own -- the
    # network too, but where the bus is an abstract socket, which has no file to bind. No word
    # shares anything back: `--share-net` in a launcher is the sign of the network grant, and the
    # proxy's bwrap never says it.
    proxy, _, r, rt = _launched(tmp_path, monkeypatch, address)
    assert r.returncode == 0 and r.stderr == "", (r.stdout, r.stderr)
    words = proxy[:proxy.index("--")]
    file = BUS_ADDRESSES.get(address or "unix:path={rt}/bus")
    want = {"/usr": ("--ro-bind", "/usr"), "/etc": ("--ro-bind", "/etc"), f"{rt}/appkata": ("--bind", f"{rt}/appkata")}
    if file:
        want[file.format(rt=rt)] = ("--ro-bind-try", file.format(rt=rt))
    assert _binds(words) == want
    # everything else that puts something in its root: the three links into /usr, /proc and /dev
    mounts = [w for w in words if w in ("--symlink", "--proc", "--dev", "--tmpfs", "--dir", "--file", "--bind-data", "--ro-bind-data", "--overlay", "--mqueue")]
    assert mounts == ["--symlink"] * 3 + ["--proc", "--dev"], words
    unshared = {w for w in words if w.startswith("--unshare")}
    assert unshared == {"--unshare-pid", "--unshare-ipc", "--unshare-uts", "--unshare-cgroup-try"} | ({"--unshare-net"} if file else set()), words
    assert "--die-with-parent" in words and not [w for w in words if w.startswith("--share")], words
    assert words[words.index("--seccomp") + 1] == "3" and "--new-session" not in words
    # nor the launcher's environment, which a terminal can fill with tokens: the app's own bwrap
    # clears it, the proxy's kept it whole (PR #694's review, P1-B2). Its address and socket are
    # arguments; PATH is for bwrap to find it, the folder of the one the launcher's PATH finds.
    assert "--clearenv" in words and [words[i + 1:i + 3] for i, w in enumerate(words) if w == "--setenv"] == [["PATH", "/usr/bin"]], words
    assert not [w for w in words if w in ("--unsetenv", "--chdir")] and words.index("--clearenv") < words.index("--setenv"), words


# PR #694's review, P2-B4: the proxy's bwrap had PATH=/usr/bin:/bin, while AppKata's own check
# (have_bus_filter) finds xdg-dbus-proxy on the launcher's PATH. One in /usr/local/bin -- a build of
# your own, the way to the fixed 0.1.8 where a distribution ships 0.1.7 (R17.17) -- failed every
# Standard app with "did not start", or, beside the distribution's, the older one ran without a word.
# How it slipped past: every test's proxy was /usr/bin's, or no program at all. The launcher now runs
# the one its PATH finds, from that folder, and refuses one its sandbox (/usr alone) can't run; where
# its PATH has none, /usr/bin:/bin as before (the inventory's and the persona tests' launchers in
# tier 1, where no machine's proxy is, among them).
@pytest.mark.parametrize("found,runs", [("/usr/local/bin/xdg-dbus-proxy", True), ("/usr/bin/xdg-dbus-proxy", True), (None, True),
                                        ("/usr/lib/xdp/0.1.8/xdg-dbus-proxy", True),
                                        ("/opt/xdp/bin/xdg-dbus-proxy", False), ("/usr/libexec/xdp/dbus-proxy-0.1.8", False),
                                        ("/usr/xdg-dbus-proxy", False), ("/usrlocal/bin/xdg-dbus-proxy", False),
                                        ("/home/kata/.local/bin/xdg-dbus-proxy", False), ("/usr/bin/xdg-dbus-proxy.real", False)])
def test_the_bus_filter_is_the_one_the_launchers_path_finds_run_where_its_sandbox_can(tmp_path, monkeypatch, found, runs):
    proxy, app, r, rt = _launched(tmp_path, monkeypatch, None, proxy_at=found, app=runs, hide=() if found else ("xdg-dbus-proxy",))
    # the launcher keeps the rule AppKata's own check keeps (bus_filter: PR #694's review, P3-B1)
    assert found is None or fnmatch.fnmatchcase(found, sb.BUS_FILTER_AT) is runs
    if runs:
        words = proxy[:proxy.index("--")]
        assert r.returncode == 0 and r.stderr == "", (words, r.stderr)
        assert words[words.index("PATH") + 1] == (os.path.dirname(found) if found else "/usr/bin:/bin"), words
        assert proxy[proxy.index("--") + 1] == "xdg-dbus-proxy", proxy
    else:
        assert proxy is None and r.returncode == 1, (r.returncode, r.stderr)
        assert r.stderr == (f"AppKata: the session-bus filter this PATH finds, {found}, is not an xdg-dbus-proxy under /usr, the one tree "
                            "its own sandbox holds, so Demo cannot run sandboxed here.\n"), r.stderr


# PR #694's review, P3-B1: AppKata's own check was `shutil.which` alone, so a PATH that finds an
# xdg-dbus-proxy outside /usr first (Linuxbrew, nix-env, a build in ~/.local/bin) read as "the bus
# filter is here": no hint in Settings or App Detail, and a launcher with a proxy, which the launcher
# refuses (P2-B4), so every Standard app exited 1 -- where with no proxy at all it runs with no bus
# and says why. How it slipped past: P2-B4's test held the launcher to its rule, and nothing held
# AppKata's own check to the same one. Both keep BUS_FILTER_AT now (bus_filter), so such a proxy
# counts as none, and the hint names the file in place of "isn't installed".
def test_a_bus_filter_the_launcher_would_refuse_counts_as_none_and_the_hint_names_it(monkeypatch, tmp_path):
    _apparmor_dir(tmp_path, monkeypatch, {})
    monkeypatch.setattr(sb, "OS", "linux")
    monkeypatch.setattr(sb, "userns_works", lambda refresh=False: True)
    monkeypatch.setattr(sb, "nested_userns_works", lambda refresh=False: True)
    monkeypatch.setattr("appkata_core.platform.linux_family", lambda: "debian")
    own = tmp_path / "bin"
    own.mkdir()
    for tool in ("bwrap", "xdg-dbus-proxy"):
        (own / tool).write_text("#!/bin/sh\nexit 1\n")
        (own / tool).chmod(0o755)
    monkeypatch.setenv("PATH", f"{own}:{os.environ['PATH']}")
    found = str(own / "xdg-dbus-proxy")
    st = sb.support_status()
    assert st["status"] == "ok" and st["busFilter"] is False and st["missing"] == ["xdg-dbus-proxy"], st
    assert sb.bus_filter() == (found, False) and not sb.have_bus_filter()
    assert st["toolsHint"] == (f"The xdg-dbus-proxy this PATH finds, {found}, is outside /usr, where the bus filter's own sandbox can't run "
                               "it, so sandboxed apps get no desktop services: they can't notify, open links or files on this computer, or "
                               "show a tray icon. Install xdg-dbus-proxy (sudo apt install xdg-dbus-proxy), have the PATH find /usr/bin's "
                               "first, and restart AppKata."), st["toolsHint"]
    assert st["appToolsHint"].startswith(f"Runs without desktop services: the xdg-dbus-proxy this PATH finds, {found}, is outside /usr, "
                                         "where the bus filter's own sandbox can't run it, so it can't notify"), st["appToolsHint"]
    # ...and the launcher AppKata writes starts no proxy: the app runs with no session bus, as with none
    text = sb.launcher_text("chat", "Chat", "/apps", "/apps/chat/1", "bin/chat", sb.resolve_template("online-app"))
    assert 'xdg-dbus-proxy "$upstream"' not in text and "--setenv APPKATA_NO_BUS no-filter" in text
    # beside a missing bubblewrap, named with it
    assert sb.tools_hints(["bubblewrap", "xdg-dbus-proxy"], found)["system"] == (
        f"bubblewrap isn't installed, nor xdg-dbus-proxy under /usr (this PATH finds {found}), so apps run without a sandbox. "
        "Install them (sudo apt install bubblewrap xdg-dbus-proxy) and restart AppKata.")
    # a PATH that finds none, or the one the launcher runs, is as before; #711 asks the launcher's own PATH
    assert sb.bus_filter(str(tmp_path / "none")) == ("", False) and sb.bus_filter(f"{tmp_path / 'none'}:{own}") == (found, False)


def test_the_proxy_takes_the_terminal_filter_or_a_session_of_its_own():
    # ...and the terminal-injection filter, as the app's bwrap does: on a descriptor opened for
    # that command alone, so the launcher's shell holds none (the app's is opened later). Where
    # the machine's ABI has no filter, a session of its own, which the proxy can afford.
    gs = sb.resolve_template("standard")
    with_filter = sb.build_launcher("demo", "Demo", "/apps/demo/1", "bin/demo", gs, seccomp="/data/seccomp-tty.bpf")
    command = with_filter[with_filter.index("start_proxy() {"):with_filter.index("proxy=$!")]
    assert "--die-with-parent --seccomp 3 -- " in command and command.rstrip().endswith("3< /data/seccomp-tty.bpf &")
    assert with_filter.index("3< /data/seccomp-tty.bpf &") < with_filter.index("exec 3< /data/seccomp-tty.bpf")
    without = sb.build_launcher("demo", "Demo", "/apps/demo/1", "bin/demo", gs)
    command = without[without.index("start_proxy() {"):without.index("proxy=$!")]
    assert "--die-with-parent --new-session -- " in command and "--seccomp" not in command and "3<" not in command
    assert _valid_sh(with_filter) and _valid_sh(without)


@pytest.mark.parametrize("address", ["unix:path=/tmp/a%20b/bus", "unix:path={rt}/bus;unix:path=/tmp/dbus-MZ8lHbtZ8K", "unix:path=relative/bus",
                                     "unix:path=/tmp/dbus-one,path={rt}/bus",           # GDBus, the proxy's, takes the last (P3-B4)
                                     # in any order of the keys; and a path with an abstract name, which no client takes (P4-B1a)
                                     "unix:guid=0123,path=/tmp/a%20b/bus", "unix:guid=0123,path=/tmp/dbus-one,path={rt}/bus",
                                     "unix:path={rt}/bus,abstract=/tmp/dbus-two", "unix:abstract=/tmp/dbus-two,path={rt}/bus",
                                     # a key the proxy's GDBus refuses the entry for (P5-1), and a comma inside the path,
                                     # where the rest is such a key (it was taken as ending the path, and GDBus refused it)
                                     "unix:path={rt}/bus,", "unix:guid,path={rt}/bus", "unix:path={rt}/bus,,guid=0123",
                                     "unix:=0123,path={rt}/bus", "unix:abstract=/tmp/dbus-two,", "unix:path=/srv/session,one/bus",
                                     # ...and a value with an escape it can't read, in any key
                                     "unix:path={rt}/bus,guid=%zz", "unix:guid=%00,path={rt}/bus", "unix:abstract=/tmp/dbus-two%",
                                     # ...or a key's name with one (P6-2)
                                     "unix:path={rt}/bus,g%zz=1", "unix:%=1,path={rt}/bus", "unix:abstract=/tmp/dbus-two,a%00=1",
                                     "unix:abstract=/tmp/dbus-one;unix:abstract=/tmp/dbus-two", "unix:tmpdir=/tmp", "unix:runtime=yes",
                                     "tcp:host=127.0.0.1,port=4000", "autolaunch:", "nonsense"])
def test_a_bus_address_the_launcher_cannot_read_is_said_and_the_app_runs_with_no_bus(tmp_path, monkeypatch, address):
    # CR1.5-18's other half: an address whose bus the proxy can't be shown -- one the launcher
    # doesn't read a socket from -- got a proxy all the same, which failed every connection in
    # silence. Now the launcher says so, starts no proxy, and the app runs as it does with no bus.
    proxy, app, r, rt = _launched(tmp_path, monkeypatch, address)
    address = address.format(rt=rt)
    assert proxy is None and r.returncode == 0, (r.stdout, r.stderr)
    assert r.stderr == (f"AppKata: the session bus here ({address}) is not one the bus filter can reach, "
                        "so Demo runs without a session bus and gets no desktop services.\n")
    assert f"{rt}/bus" not in _binds(app) and not [w for w in app if "/appkata/bus-" in w], app
    assert app[app.index("DBUS_SESSION_BUS_ADDRESS") + 1] == f"unix:path={rt}/bus"      # set all the same, and leads nowhere (R3-33)
    assert os.listdir(rt / "appkata") == []
    assert app[app.index("APPKATA_NO_BUS") + 1] == "address"            # and AppKata's xdg-open is told why (P1-B3, below)


# PR #694's review, P1-B3: AppKata's xdg-open took "no bus" for Strict, and told a Standard app with
# none -- no xdg-dbus-proxy here, or a session bus the filter can't reach -- that it runs Strict,
# and to change that in App Detail, where nothing would. How it slipped past: the shim was written
# when Strict was the one way to have no bus, and the ways added since were tested on the launcher's
# own line, never on what the app's xdg-open then said. The launcher now tells it, and it says that.
@pytest.mark.parametrize("why,says", [(None, "this app runs Strict, with no desktop services"),
                                      ("no-filter", "the bus filter (xdg-dbus-proxy) isn't installed, so this app has no desktop services"),
                                      ("address", "this session's bus is at an address AppKata's bus filter can't reach")])
def test_xdg_open_says_why_the_app_has_no_bus(tmp_path, why, says):
    shim = tmp_path / "xdg-open"
    shim.write_text(sb.XDG_OPEN_SHIM)
    told = {"APPKATA_NO_BUS": why} if why else {}                          # a Strict app is told nothing: no word, no bus
    r = subprocess.run(["sh", str(shim), "https://example.com/x"], env={"PATH": os.environ["PATH"], "XDG_RUNTIME_DIR": str(tmp_path), **told},
                       capture_output=True, text=True)
    assert r.returncode == 3 and r.stderr.startswith("AppKata: " + says) and r.stderr.count("\n") == 1, r.stderr


def test_each_launcher_tells_its_xdg_open_why_the_app_has_no_bus(tmp_path, monkeypatch):
    told = lambda gs, **kw: re.findall(r"--setenv APPKATA_NO_BUS (\S+)", sb.build_launcher("v", "V", "/apps/v/1", "bin/v", gs, **kw))  # noqa: E731
    assert told(sb.resolve_template("strict")) == []                    # no word and no bus is Strict
    assert told(sb.resolve_template("standard"), bus_filter=False) == ["no-filter"]
    assert told(sb.resolve_template("standard")) == ["address"]          # decided at run time, where no proxy starts
    proxy, app, r, rt = _launched(tmp_path, monkeypatch, None)            # and where one does, nothing
    assert proxy is not None and "APPKATA_NO_BUS" not in app, app


# CR1.5-46 (#707; the owner's decision of 2026-11-24): Password service owned org.freedesktop.secrets
# whoever held it, and to the filter an own is a talk, so beside gnome-keyring the app reached the
# keyring's whole connection, every unlocked password included. The launcher now asks the session's
# bus at the launch, and where another program holds the name starts the app without the own and
# says why; the sole provider keeps it. PR #694's review, P2-3: a name the bus can start a program
# for (gnome-keyring installed, not running) was "free", and the app, which may call the name it may
# own, could start the keyring itself and reach it: such a name counts as held. How it slipped past:
# the question asked was the one the decision named, "does another program hold it", and every
# test's bus started no keyring on demand. Here the asking is a stand-in gdbus or busctl, answering
# as each answers (gdbus, else busctl).
_ANSWERS = {"gdbus": (lambda held: f"({str(held).lower()},)",
                      lambda more: "(['org.freedesktop.DBus', 'org.gnome.keyring'" + "".join(f", '{n}'" for n in more) + "],)"),
            "busctl": (lambda held: f"b {str(held).lower()}",
                       lambda more: f'as {2 + len(more)} "org.freedesktop.DBus" "org.gnome.keyring"' + "".join(f' "{n}"' for n in more))}


@pytest.mark.parametrize("tool", ["gdbus", "busctl"])
@pytest.mark.parametrize("held,startable", [(True, False), (False, True), (False, False)],
                         ids=["another-provider", "one-the-bus-can-start", "the-only-provider"])
def test_password_service_owns_the_name_only_where_no_other_program_holds_it(tmp_path, monkeypatch, tool, held, startable):
    asked = tmp_path / "asked"
    owner, names = _ANSWERS[tool]
    answer = (f'#!/bin/sh\necho "$*" >> {shlex.quote(str(asked))}\ncase "$*" in *NameHasOwner*) echo {shlex.quote(owner(held))} ;; '
              f'*) echo {shlex.quote(names(["org.freedesktop.secrets"] if startable else []))} ;; esac\n')
    gs = sb.apply_overrides(sb.resolve_template("standard"), {"caps": ["secrets-provide"]})
    proxy, app, r, rt = _launched(tmp_path, monkeypatch, None, gs=gs, tools={tool: answer}, hide=("gdbus",) if tool == "busctl" else ())
    assert r.returncode == 0 and proxy is not None, (r.stdout, r.stderr)
    assert ("--own=org.freedesktop.secrets" in proxy) is not (held or startable), proxy
    if held:
        assert r.stderr == ("AppKata: another program already provides saved passwords on this session bus (org.freedesktop.secrets), so Demo "
                            "runs without Password service: offering that name through the bus filter would reach that program and the "
                            "passwords it holds.\n"), r.stderr
    elif startable:
        assert r.stderr == ("AppKata: this session bus can start another program that provides saved passwords (org.freedesktop.secrets), so "
                            "Demo runs without Password service: offering that name through the bus filter would let the app start that "
                            "program and reach the passwords it holds.\n"), r.stderr
    else:
        assert r.stderr == "", r.stderr
    bus = f"unix:path={rt}/bus"
    want = {"gdbus": [f"call --address {bus} --timeout 5 --dest org.freedesktop.DBus --object-path /org/freedesktop/DBus --method "
                      f"org.freedesktop.DBus.{m}" for m in ("NameHasOwner org.freedesktop.secrets", "ListActivatableNames")],
            "busctl": [f"--address={bus} --timeout=5 call org.freedesktop.DBus /org/freedesktop/DBus org.freedesktop.DBus {m}"
                       for m in ("NameHasOwner s org.freedesktop.secrets", "ListActivatableNames")]}[tool]
    assert asked.read_text().splitlines() == (want[:1] if held else want)       # a name held needs no list
    # and an app without the capability asks nothing
    assert "NameHasOwner" not in sb.build_launcher("demo", "Demo", "/apps/demo/1", "bin/demo", sb.resolve_template("standard"))


# PR #694's review, P2-2 and P2-B3: the ask failed open -- `|| true` inside it, so a failed or timed-out
# ask read as "no other provider" and kept the own -- and the tools' own --timeout bounds the call,
# not the connecting, so a bus that took the connection and never spoke held the launch for good.
# How it slipped past: the stand-in answered every time, and nothing asked a bus that didn't. Now the
# name is free only on two answers read as the tool writes them, `timeout 5` bounds each ask, and
# anything else counts as held, with a line of its own.
_UNASKED = [
    ("the ask fails", "exit 1", ()),
    ("an answer it can't read", "echo '(nonsense,)'", ()),
    ("the list fails", 'case "$*" in *NameHasOwner*) echo "(false,)" ;; *) exit 1 ;; esac', ()),
    ("a list it can't read", 'case "$*" in *NameHasOwner*) echo "(false,)" ;; *) echo "(@as [],)" ;; esac', ()),
    ("a bus that never answers", "exec sleep 60", ()),
    ("no tool to ask with", None, ("gdbus", "busctl")),
    ("no timeout to bound it", 'case "$*" in *NameHasOwner*) echo "(false,)" ;; *) echo "([\'org.freedesktop.DBus\'],)" ;; esac', ("timeout",)),
]


@pytest.mark.parametrize("case,gdbus,hide", _UNASKED, ids=[c[0] for c in _UNASKED])
def test_password_service_counts_the_name_held_where_the_bus_cannot_be_asked(tmp_path, monkeypatch, case, gdbus, hide):
    gs = sb.apply_overrides(sb.resolve_template("standard"), {"caps": ["secrets-provide"]})
    began = time.monotonic()
    proxy, app, r, rt = _launched(tmp_path, monkeypatch, None, gs=gs, tools={"gdbus": f"#!/bin/sh\n{gdbus}\n"} if gdbus else {}, hide=hide)
    assert time.monotonic() - began < 20, case                                      # bounded: `timeout 5`, not the bus
    assert r.returncode == 0 and proxy is not None and "--own=org.freedesktop.secrets" not in proxy, (case, proxy, r.stderr)
    assert r.stderr == ("AppKata: could not ask this session bus whether another program provides saved passwords (org.freedesktop.secrets), "
                        "so Demo runs without Password service: offering that name through the bus filter could reach such a program and "
                        "the passwords it holds.\n"), (case, r.stderr)


# PR #694's review, P3-B3: the never-answering stand-in above sleeps on every ask, so the first
# (NameHasOwner) times out and the second (ListActivatableNames) is never made: nothing held that
# second ask's `timeout 5`, and taking it off both tools' lines passed every test, while a bus that
# answers the first ask and then goes silent would hold the launch for good without it (gdbus's own
# --timeout doesn't bound the connecting: P2-B3). How it slipped past: one stand-in stood for every
# silent bus. This one answers "no owner" as each tool does, and never answers the list.
@pytest.mark.parametrize("tool", ["gdbus", "busctl"])
def test_password_service_counts_the_name_held_where_the_bus_answers_the_first_ask_alone(tmp_path, monkeypatch, tool):
    owner, _ = _ANSWERS[tool]
    answer = f'#!/bin/sh\ncase "$*" in *NameHasOwner*) echo {shlex.quote(owner(False))} ;; *) exec sleep 60 ;; esac\n'
    gs = sb.apply_overrides(sb.resolve_template("standard"), {"caps": ["secrets-provide"]})
    began = time.monotonic()
    proxy, app, r, rt = _launched(tmp_path, monkeypatch, None, gs=gs, tools={tool: answer}, hide=("gdbus",) if tool == "busctl" else ())
    assert time.monotonic() - began < 20, tool                                       # bounded: `timeout 5`, not the bus
    assert r.returncode == 0 and proxy is not None and "--own=org.freedesktop.secrets" not in proxy, (proxy, r.stderr)
    assert r.stderr == ("AppKata: could not ask this session bus whether another program provides saved passwords (org.freedesktop.secrets), "
                        "so Demo runs without Password service: offering that name through the bus filter could reach such a program and "
                        "the passwords it holds.\n"), r.stderr


# PR #694's review, P3-1 (the owner's decision of 2026-11-25): the launcher withheld Password service
# beside another provider, a running keyring or one the bus could start, which is every desktop that
# installs gnome-keyring (Mint, LMDE, Ubuntu), and said so only in the app's log: the Sandbox dialog
# offered the switch with a hint that said what it gives, and App Detail showed the chip. Now both
# say it, from AppKata's own ask of the session bus, in the launcher's words (_PROVIDE_ASK). How it
# slipped past: the decision was the launcher's, and its tests read the launcher's stderr; nothing
# asked what the screens that offer the switch say of it. This is the class's harness: every answer a
# bus or a host gives the launcher's tests above, for both tools, and two addresses, goes to the
# launcher and to AppKata's ask under the same PATH and session, and the two must decide alike and
# ask alike. The screens' text is test_dialog_contract's and test_sandbox_ui_surfaces' to show.
def _bus_answers(tool, held, startable):
    owner, names = _ANSWERS[tool]
    return (f'case "$*" in *NameHasOwner*) echo {shlex.quote(owner(held))} ;; '
            f'*) echo {shlex.quote(names(["org.freedesktop.secrets"] if startable else []))} ;; esac')


_SESSION = "unix:path={rt}/dbus-MZ8lHbtZ8K,guid=bc7bc2c1f523f8307163d71b6b05ecdf"
_PROVIDE_ANSWERS = [(f"{tool}, {what}, {where}", tool, _bus_answers(tool, held, start), ("gdbus",) if tool == "busctl" else (), address)
                    for tool in ("gdbus", "busctl")
                    for what, held, start in (("owned", True, False), ("activatable", False, True), ("free", False, False))
                    for where, address in (("no address", None), ("an address", _SESSION))]
_PROVIDE_ANSWERS += [(case, "gdbus", body, hide, None) for case, body, hide in _UNASKED]


@pytest.mark.parametrize("case,tool,body,hide,address", _PROVIDE_ANSWERS, ids=[c[0] for c in _PROVIDE_ANSWERS])
def test_appkata_asks_the_session_bus_what_the_launcher_asks_and_decides_alike(tmp_path, monkeypatch, case, tool, body, hide, address):
    asked = tmp_path / "asked"
    tools = {tool: f'#!/bin/sh\necho "$*" >> {shlex.quote(str(asked))}\n{body}\n'} if body else {}
    gs = sb.apply_overrides(sb.resolve_template("standard"), {"caps": ["secrets-provide"]})
    proxy, app, r, rt = _launched(tmp_path, monkeypatch, address, gs=gs, tools=tools, hide=hide)
    assert r.returncode == 0 and proxy is not None, (r.stdout, r.stderr)
    lines = {"held": "AppKata: another program already provides saved passwords", "start": "AppKata: this session bus can start another program",
             "ask": "AppKata: could not ask this session bus"}
    launcher = next((why for why, line in lines.items() if r.stderr.startswith(line)), "")
    assert (r.stderr == "") is (launcher == "") and ("--own=org.freedesktop.secrets" in proxy) is (launcher == ""), (case, r.stderr, proxy)
    launcher_asked = asked.read_text() if asked.exists() else ""
    asked.unlink(missing_ok=True)
    # AppKata in the same session: the same runtime folder and address as the launcher's run, and the
    # launcher's PATH (sandbox.host_path), which its ask runs with whatever AppKata's own is
    path = str(tmp_path / "bare") if hide else os.environ["PATH"]
    monkeypatch.setattr(sb, "HOST_PATH", f"{tmp_path / 'fakebin'}{os.pathsep}{path}")
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(rt))
    if address is None:
        monkeypatch.delenv("DBUS_SESSION_BUS_ADDRESS", raising=False)
    else:
        monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", address.format(rt=rt))
    began = time.monotonic()
    why = sb.password_service_withheld()
    assert time.monotonic() - began < 15, case        # bounded as the launch is (on a worker: test_the_password_service_ask_never_holds_the_window)
    assert why == launcher, (case, why, launcher)
    assert (asked.read_text() if asked.exists() else "") == launcher_asked, case     # the same names, of the same bus
    assert bool(launcher_asked) is (bool(body) and "timeout" not in hide), case      # a stand-in that is there is asked
    assert (sb.PROVIDE_NOTES.get(why, "") != "") is (why != ""), why                  # and the screens have words for each reason


# Where #689 (U03, CR1.5-31) met this unit: a launcher takes every host command from its own PATH
# (sandbox.host_path), whatever PATH it is started with, while AppKata's ask of the bus still took
# gdbus and timeout from AppKata's own, where a login's ~/bin and ~/.local/bin come first: the
# Sandbox dialog and App Detail could say one thing and the launch decide another. And the ask's
# tools weren't in sandbox.HOST_COMMANDS, the list a launcher's commands come from and no command
# link may be named after, so a machine whose command folders hold those alone answered "could not
# ask" at every launch. How it slipped past: each side's tests held its own rule, with the other's
# code not there yet. The class: AppKata's PATH is never the launcher's, and the launcher's commands
# are the listed ones.
def test_appkata_asks_with_the_launchers_path_not_its_own(tmp_path, monkeypatch):
    gs = sb.apply_overrides(sb.resolve_template("standard"), {"caps": ["secrets-provide"]})
    path = os.environ["PATH"]
    free, held = (f'#!/bin/sh\n{_bus_answers("gdbus", h, False)}\n' for h in (False, True))
    proxy, app, r, rt = _launched(tmp_path, monkeypatch, None, gs=gs, tools={"gdbus": free})
    assert r.returncode == 0 and r.stderr == "" and "--own=org.freedesktop.secrets" in proxy, (r.stderr, proxy)
    own = tmp_path / "own-bin"                              # AppKata's own PATH: a gdbus that says "held" first
    own.mkdir()
    (own / "gdbus").write_text(held)
    (own / "gdbus").chmod(0o755)
    monkeypatch.setenv("PATH", f"{own}{os.pathsep}{path}")
    monkeypatch.setattr(sb, "HOST_PATH", f"{tmp_path / 'fakebin'}{os.pathsep}{path}")   # the launcher's, as it ran
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(rt))
    monkeypatch.delenv("DBUS_SESSION_BUS_ADDRESS", raising=False)
    assert sb.password_service_withheld() == ""             # what the launch decided


def test_a_launcher_with_password_service_runs_no_host_command_but_the_listed_ones(tmp_path, monkeypatch):
    # As tests/test_sandbox_adversarial.py's test of the same name holds the launchers without a bus:
    # a machine whose command folders hold sandbox.HOST_COMMANDS and nothing else (the bus tools as
    # stand-ins answering "no other provider", so no real session bus is asked) still gets the ask
    # answered, the name owned and the app started. A tool the ask uses and the list lacks fails here
    # with the "could not ask" line.
    only = tmp_path / "only"
    only.mkdir()
    for n in sb.HOST_COMMANDS:
        if n in _ANSWERS:
            (only / n).write_text(f'#!/bin/sh\n{_bus_answers(n, False, False)}\n')
            (only / n).chmod(0o755)
        elif real := shutil.which(n, path=sb.HOST_PATH):
            os.symlink(real, only / n)
    os.symlink(shutil.which("sh"), only / "sh")                # what runs the launcher, not a command it runs
    monkeypatch.setenv("PATH", str(only))
    gs = sb.apply_overrides(sb.resolve_template("standard"), {"caps": ["secrets-provide"]})
    proxy, app, r, rt = _launched(tmp_path, monkeypatch, None, gs=gs)
    assert r.returncode == 0 and r.stderr == "" and "--own=org.freedesktop.secrets" in proxy, (r.stderr, proxy)


# The review of PR #694, P1-2: the never-shared rules kept the real session bus from the app by
# refusing the runtime folder alone, and dbus-run-session and dbus-launch put the bus under /tmp
# (BUS_ADDRESSES): a tool run in /tmp, or a grant of /tmp, showed the app the bus's socket file, and
# the app could connect to it past the filter. How it slipped past: every test of the rules had the
# bus where they assumed it, in the runtime folder; the tests that moved it (CR1.5-18) looked at the
# proxy, which was the change, and not at the rules that had assumed the old place.

def _a_bus_socket(folder):
    import socket
    folder.mkdir(parents=True, exist_ok=True)
    s = socket.socket(socket.AF_UNIX)
    s.bind(str(folder / "dbus-MZ8lHbtZ8K"))
    return s, folder / "dbus-MZ8lHbtZ8K"


def test_a_grant_that_would_show_the_session_bus_socket_is_refused_wherever_it_lies(tmp_path, monkeypatch):
    folder = tmp_path / "tmp"
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", f"unix:path={folder}/dbus-MZ8lHbtZ8K,guid=bc7bc2c1f523f8307163d71b6b05ecdf")
    assert sb.protected_folder(str(folder)) == "a folder above the session bus's socket"
    assert sb.protected_folder(str(folder / "dbus-MZ8lHbtZ8K")) == "the session bus's socket"
    assert sb.protected_folder(str(folder / "project")) == ""                      # the file is protected, not its neighbours
    assert sb.strip_protected(sb.apply_overrides(sb.resolve_template("standard"), {"folders": {f"+{folder}": "rw"}}))[1] == \
        [(sb.folder_path(str(folder)), "a folder above the session bus's socket")]      # named as every grant is (CR1.5-16)
    # each socket file a list names, unescaped, as libdbus reads it; an abstract socket has none
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", f"unix:abstract=/tmp/dbus-one;unix:path={tmp_path}/a%20b/bus")
    assert sb.bus_files()[0] == [f"{tmp_path}/a b/bus"]
    assert sb.protected_folder(str(tmp_path / "a b")) == "a folder above the session bus's socket"
    # an escaped byte as the byte it is, as the launcher's shell reads it, UTF-8 or not (PR #694's review, P2-1)
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", f"unix:path={tmp_path}/a%ffb/bus")
    odd = os.fsdecode(os.fsencode(str(tmp_path)) + b"/a\xffb")
    assert sb.bus_files()[0] == [odd + "/bus"] and sb.protected_folder(odd) == "a folder above the session bus's socket"
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", "unix:abstract=/tmp/dbus-MZ8lHbtZ8K,guid=0123")
    assert sb.bus_files()[0] == [] and sb.protected_folder(str(folder)) == ""


# PR #694's review, P3-2 and P3-B5: the grant-time reader (bus_sockets(), now bus_files(): P4-B2)
# looked for the leading `/` before it unescaped the path, so an address that escapes it (`%2F`:
# legal, though dbus never writes it) named no file and a grant of the socket's folder passed; and
# it kept an escaped NUL, so every folder check raised
# ValueError (from os.path.realpath) in such a session, where the launcher refuses the address
# cleanly. How it slipped past: P2-1 tested each form on the launcher's shell, which unescapes
# first, and the grant-time reader on the forms dbus writes. Now the path is judged once unescaped,
# an escaped NUL ends it (as libdbus and sd-bus read it; GIO refuses the address), and an address
# that names a file AppKata can't read refuses every folder, as the launcher then shares no
# working directory: the file could be in any.
def test_a_grant_is_judged_by_the_bus_address_unescaped_and_refused_everywhere_where_it_cannot_be_read(tmp_path, monkeypatch):
    folder, beside = tmp_path / "tmp", str(tmp_path / "project")
    sock = str(folder / "dbus-MZ8lHbtZ8K")
    gs = sb.apply_overrides(sb.resolve_template("standard"), {"folders": {f"+{folder}": "rw", f"+{beside}": "rw"}})
    # ...and a key's name unescaped, as GIO reads it, where libdbus and sd-bus take it as written
    # (PR #694's review, P6-1: `pa%74h=` named no file, and GIO connects to it)
    for address in ("unix:path=" + sock.replace("/", "%2F"), f"unix:path={sock}%00zz", f"unix:path={tmp_path}/first,path={sock}",
                    f"unix:pa%74h={sock}", f"unix:path={tmp_path}/first,%70ath={sock}"):
        monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", address)
        assert sock in sb.bus_files()[0] and sb.bus_files()[1], address
        assert sb.protected_folder(str(folder)) == "a folder above the session bus's socket" and sb.protected_folder(beside) == "", address
        assert sb.strip_protected(gs)[1] == [(sb.folder_path(str(folder)), "a folder above the session bus's socket")], address
        assert f"# Refused folder grant {sb.folder_path(str(folder))}: a folder above" in sb.build_launcher("demo", "Demo", "/apps/demo/1", "bin/demo", gs)
    # a path that isn't absolute, a broken escape, a newline: the file could be anywhere
    for address in ("unix:path=relative/bus", "unix:path=/tmp/dbus-%zz", "unix:path=/tmp/dbus-%2", "unix:path=/tmp/a%0Ab",
                    "unix:path=%00/tmp/x", "unix:path=", f"unix:abstract=/tmp/x;unix:path={sock},path=bus"):
        monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", address)
        assert sb.protected_folder(beside) == ("a folder the session bus's socket could be in (its address names a file AppKata "
                                               "can't read)") and sb.protected_folder("$cwd") == "", address   # $cwd: the launcher's own rule
        assert not sb.bus_files()[1] and sb.protected_folder("~") == "your whole home folder", address       # a reason of its own stays its own
        assert sorted(p for p, _ in sb.strip_protected(gs)[1]) == sorted(map(sb.folder_path, [str(folder), beside])), address
    for address in ("unix:path", "unix:guid=0123", "tcp:host=localhost,port=4000", "unix:abstract=/tmp/x"):   # no file named: nothing to read
        monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", address)
        assert sb.bus_files() == ([], True) and sb.protected_folder(beside) == "", address


# PR #694's review, P2-1: the launcher's own rules (the working directory, the cover of a granted
# folder) read the socket from a plain `unix:path=` address alone, while bus_files() reads every
# form, so a session whose address was a list, put `guid=` first or escaped a byte -- or named a link
# to the socket -- left the file in sight of a tool run beside it or a folder granted. How it slipped
# past: P1-2's tests used the address dbus itself writes, and the forms the proxy can't take were
# tested for the proxy alone. Each form is a way to name the socket `_a_bus_socket` makes in `tmp`.
BUS_FORMS = {
    "plain": "unix:path={tmp}/dbus-MZ8lHbtZ8K,guid=0123",
    "guid first": "unix:guid=0123,path={tmp}/dbus-MZ8lHbtZ8K",
    "a list": "unix:abstract=/tmp/dbus-none;unix:path={tmp}/dbus-MZ8lHbtZ8K",
    "an escaped byte": "unix:path={up}/%74mp/dbus-%4dZ8lHbtZ8K",
    "a link to it": "unix:path={up}/elsewhere/bus",
    # PR #694's review, P3-B4: GIO takes the last of two `path=` keys, and libdbus and sd-bus end a
    # path at an escaped NUL; the launcher read the first alone, and counted the NUL unreadable
    "a second path=": "unix:path={up}/elsewhere/none,path={tmp}/dbus-MZ8lHbtZ8K",
    "an escaped NUL": "unix:path={tmp}/dbus-MZ8lHbtZ8K%00zz",
    # P6-1: GIO unescapes a key's name, so this is its `path=`; the launcher read the key as written
    "an escaped key": "unix:pa%74h={tmp}/dbus-MZ8lHbtZ8K,guid=0123",
}


def _bus_form(form, path):
    """The session address of `form` for the socket at `path` (and the link it names, made)."""
    if form == "a link to it":
        os.makedirs(path.parent.parent / "elsewhere", exist_ok=True)
        (path.parent.parent / "elsewhere" / "bus").symlink_to(path)
    return BUS_FORMS[form].format(tmp=path.parent, up=path.parent.parent)


@pytest.mark.parametrize("form", BUS_FORMS)
@pytest.mark.parametrize("where", ["the socket's folder", "a folder beside it"])
def test_a_tool_run_where_the_session_bus_socket_is_is_not_shown_it(tmp_path, monkeypatch, where, form):
    sock, path = _a_bus_socket(tmp_path / "home" / "tmp")      # in the user's own folders: a tool is never given one under /tmp (CR1.5-6)
    run_in = os.path.realpath(path.parent if where == "the socket's folder" else path.parent / "project")
    os.makedirs(run_in, exist_ok=True)
    proxy, app, r, rt = _launched(tmp_path, monkeypatch, _bus_form(form, path), template="cli-tool", cwd=run_in)
    sock.close()
    assert (proxy is not None) is (form in ("plain", "guid first", "a link to it", "an escaped key")) and r.returncode == 0, (r.stdout, r.stderr)   # the proxy takes those (R17.5)
    if where == "the socket's folder":
        assert run_in not in _binds(app) and app[app.index("--chdir") + 1] == str(tmp_path / "home"), app
        assert f"Demo runs sandboxed and can't see {run_in}" in r.stderr and "one that holds the session bus" in r.stderr, r.stderr
    else:
        assert _binds(app)[run_in] == ("--bind", run_in) and "can't see" not in r.stderr, (app, r.stderr)


# CR1.5-6 (#381, the owner's decision of 2026-11-24): a command-line tool's working directory was
# refused when it was the home, a folder above it, or in or above a never-shared folder, and that
# list knew no system place. Run from /tmp, /var/tmp or /dev/shm (`cd /tmp && tool x`), the tool got
# the whole folder read-write, bound after the sandbox's own /tmp and /dev and over them, with
# every other program's sockets in it: tmux's server, an ssh agent's. Now the tool's rule is the
# grant's (sb.SYSTEM_PLACES): it runs in its private home and says why, in words of its own. How it
# slipped past: the refused directories the tests ran a tool from were the home's and AppKata's
# own; none was a place of the system. Each is here, with a folder of /tmp that is not above this
# test's home, as the launcher itself decides it (a stand-in bwrap records the words).
SYSTEM_RUNS = ["a folder of /tmp", "/var/tmp", "/dev/shm", "/dev", "/proc", "/sys", "/etc", "/usr/share", "/var", "/run"]


@pytest.mark.parametrize("where", SYSTEM_RUNS)
def test_a_tool_run_in_a_system_place_is_not_given_it_and_says_why(tmp_path, monkeypatch, where):
    import tempfile
    made = tempfile.mkdtemp(prefix="appkata-cr1-5-6-", dir="/tmp") if where == "a folder of /tmp" else None
    run_in = os.path.realpath(made or where)
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "run"))              # AppKata's own, as the tool's: /run is not above it
    try:
        proxy, app, r, rt = _launched(tmp_path, monkeypatch, None, template="cli-tool", cwd=run_in)
    finally:
        if made:
            os.rmdir(made)
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert _binds(app).get(run_in, ("",))[0] != "--bind", app                 # not the tool's (the launcher's own /etc is read-only)
    assert app[app.index("--chdir") + 1] == str(tmp_path / "home") and app.count("--chdir") == 1, app
    if str(tmp_path).startswith(run_in + os.sep):                             # above this test's home: refused for that, as before
        assert f"Demo runs sandboxed and can't see {run_in} (your home folder or a folder above it" in r.stderr, r.stderr
        return
    assert (f"Demo runs sandboxed and isn't given {run_in} to work in: it is one of the system's own folders "
            f"({', '.join(sb.SYSTEM_PLACES)}), or in or above one, and those are never shared.\n"
            "Run it from a project folder, or give it a folder in AppKata (App Detail > Sandbox). "
            "A file you name on the command line is handed over either way, unless it is in a never-shared folder of your home "
            "(your keys, your startup files, AppKata's own) or named through a link.\n") in r.stderr, r.stderr
    assert "can't see" not in r.stderr, r.stderr


def test_a_tool_run_where_a_disk_is_mounted_or_in_its_users_folders_is_still_given_the_folder(tmp_path, monkeypatch, tmp_path_factory):
    # ...and what the grant check leaves alone the tool's rule does too: the mount roots (a stick or a
    # disk under /media, /mnt or /run/media, R17.3.1), and a folder of the home, wherever the home is.
    project = tmp_path / "home" / "tmp" / "project"                           # named like a system place, and the user's own
    project.mkdir(parents=True)
    for n, run_in in enumerate([str(project)] + [d for d in ("/mnt", "/media", "/run/media") if os.path.isdir(d)]):
        run_in = os.path.realpath(run_in)
        proxy, app, r, rt = _launched(tmp_path if n == 0 else tmp_path_factory.mktemp("again"), monkeypatch, None, template="cli-tool", cwd=run_in)
        assert r.returncode == 0 and _binds(app)[run_in] == ("--bind", run_in), (run_in, app, r.stderr)
        assert app[app.index("--chdir") + 1] == run_in and "runs sandboxed and" not in r.stderr, (run_in, r.stderr)


@pytest.mark.parametrize("address", ["unix:path=relative/dbus-MZ8lHbtZ8K", "unix:path=/tmp/dbus-%zz", "unix:abstract=/tmp/x;unix:path=/tmp/a%0Ab"])
def test_a_tool_is_shown_no_folder_where_the_session_bus_names_a_file_it_cannot_read(tmp_path, monkeypatch, address):
    # ...and an address that names a socket file the launcher can't read (a relative path, a broken
    # escape, a newline) could name one anywhere: the tool is shown no working folder, and told why.
    run_in = tmp_path / "project"
    run_in.mkdir()
    proxy, app, r, rt = _launched(tmp_path, monkeypatch, address, template="cli-tool", cwd=run_in)
    assert proxy is None and r.returncode == 0 and str(run_in) not in _binds(app), (app, r.stderr)
    assert (f"Demo runs sandboxed and can't see {run_in}, nor any folder here: this session bus's address ({address}) names a socket "
            "file AppKata can't read, which could be there.") in r.stderr, r.stderr


_FORWARD_STUB = """import json, sys
with open(sys.argv[0] + ".args", "a") as f:
    f.write(json.dumps(sys.argv[1:]) + "\\n")
sys.exit(1)
"""


@pytest.mark.parametrize("address", ["unix:path=relative/dbus-MZ8lHbtZ8K", "unix:path=/tmp/dbus-%zz", "unix:abstract=/tmp/x;unix:path=/tmp/a%0Ab", None])
def test_no_granted_folder_is_shown_where_the_session_bus_names_a_file_it_cannot_read(tmp_path, monkeypatch, address):
    # PR #694's review, P3-B4: ...and such an address could name a socket in any granted folder, at any
    # depth, while the cover asked $bussocks alone. Each granted folder is shown empty and read-only
    # now, a granted socket file covered, a granted file left as it is, the app told why, and a file
    # named in a granted folder handed over rather than given as a path the app can't see.
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", f"unix:path={tmp_path}/run/bus")      # AppKata's own: the grants stand
    home = tmp_path / "home"                     # every folder here is the user's own: /tmp is no grant's (CR1.5-5)
    monkeypatch.setenv("HOME", str(home))        # ...and a grant is named from the home (CR1.5-16)
    folder, notes = home / "project", home / "notes.txt"
    sock, deep = _a_bus_socket(folder / "deep")
    other, single = _a_bus_socket(home / "sockets")
    notes.write_text("x")
    granted = {str(folder): "rw", str(single): "rw", str(notes): "ro"}
    gs = sb.apply_overrides(sb.resolve_template("standard"), {"folders": {f"+{p}": m for p, m in granted.items()}})
    stub = tmp_path / "forward.py"
    stub.write_text(_FORWARD_STUB)
    proxy, app, r, rt = _launched(tmp_path, monkeypatch, address, gs=gs, forward=str(stub), args=[str(folder / "a.txt")])
    sock.close()
    other.close()
    emptied = {app[i + 1]: (i, app[i + 2:i + 4]) for i, w in enumerate(app) if w == "--tmpfs" and app[i + 1] in granted}
    told = json.loads(stub.with_name("forward.py.args").read_text())
    visible = told[3:told.index("--")]                                      # id, runtime folder, working folder, then these
    assert r.returncode == 0 and _binds(app)[str(folder)] == ("--bind-try", str(folder)), (app, r.stderr)
    if address is None:                                                   # the address is read: the folders are shown
        assert emptied == {} and str(single) not in [app[i + 2] for i, w in enumerate(app) if w == "--ro-bind" and app[i + 1] == "/dev/null"]
        assert sorted(visible) == sorted(granted) and "can't see the folders" not in r.stderr, (visible, r.stderr)
        return
    assert emptied == {str(folder): (emptied[str(folder)][0], ["--remount-ro", str(folder)])}, app
    assert emptied[str(folder)][0] > app.index(str(folder)), app                       # after the folder's own bind
    assert _binds(app)[str(single)] == ("--ro-bind", "/dev/null") and _binds(app)[str(notes)] == ("--ro-bind-try", str(notes)), app
    assert visible == [], told                                            # a file named there is handed over instead
    assert (f"Demo runs sandboxed and can't see the folders it was given ({', '.join(sorted(map(sb.folder_path, granted)))}): this session bus's address "
            f"({address}) names a socket file AppKata can't read, which could be in one of them.\n") in r.stderr, r.stderr


# PR #694's review, P3-B4 (and P3-2 before it): two readers of one address, bus_files() when a grant
# is judged and the launcher's shell at the launch, read it differently: the shell took the first
# `path=` of an entry alone (GIO takes the last) and counted an escaped NUL unreadable (libdbus and
# sd-bus end the path there), so a live socket the clients reach stayed in sight of a granted folder.
# How it slipped past: each reader was tested on forms of its own, never one against the other. This
# runs the launcher's own reader on each form and holds it to bus_files(): the same files, and the
# same answer to whether the address names one it can't read. The paths are under no folder there
# is, so neither names them further (the shell's `pwd -P` and a link's target are tried above).
BUS_READS = [
    "unix:path=/nowhere/a/bus", "unix:path=/nowhere/a/bus,guid=0123", "unix:guid=0123,path=/nowhere/a/bus",
    "unix:path=/nowhere/a/first,path=/nowhere/b/second", "unix:path=/nowhere/a,path=relative",
    "unix:path=/nowhere/a/bus;unix:path=/nowhere/b/bus;", "unix:abstract=/nowhere/x;unix:path=/nowhere/b/bus",
    "unix:path=%2Fnowhere%2Fa%2Fbus", "unix:path=/nowhere/a%00b", "unix:path=/nowhere/a%00%zz", "unix:path=%00/nowhere",
    "unix:path=/nowhere/%e9t%C3%A9/bus", "unix:path=/nowhere/a%25b%2cc%5C%2a", "unix:path=/nowhere/a/../b/bus", "unix:path=/nowhere/a/",
    "unix:path=relative/bus", "unix:path=./bus", "unix:path=", "unix:path=/nowhere/%zz", "unix:path=/nowhere/%2", "unix:path=/nowhere/a%",
    "unix:path=/nowhere/a%0Ab", "unix:path=/nowhere/a%0ab", "unix:path=/nowhere/a\nb",
    "unix:path", "unix:", "unix:abstract=/nowhere/x,guid=1", "unix:runtime=yes", "tcp:host=localhost,port=4000", ";;", "nonsense",
    # a key's name unescaped, as GIO reads it (P6-1), once, exactly, and never into a newline
    "unix:pa%74h=/nowhere/a/bus", "unix:path=/nowhere/a/first,%70ath=/nowhere/b/second", "unix:p%61th=relative/bus",
    "unix:%70%61%74%68=/nowhere/a%20b", "unix:PA%54H=/nowhere/a/bus", "unix:p%2561th=/nowhere/a/bus", "unix:pa%0ath=/nowhere/a/bus",
]


@pytest.mark.parametrize("address", BUS_READS)
def test_the_launcher_reads_the_bus_address_as_bus_files_does(address):
    script = "set -u\nrt=/nowhere-rt\n" + sb._BUS_BLOCK + 'printf "%s" "$bussocks"; echo "busok=$busok"\n'
    r = subprocess.run(["sh", "-c", script], env={"PATH": os.environ["PATH"], "DBUS_SESSION_BUS_ADDRESS": address},
                       capture_output=True, timeout=30)
    assert r.returncode == 0 and r.stderr == b"", r.stderr
    *files, said, end = r.stdout.split(b"\n")
    assert said in (b"busok=1", b"busok=0") and end == b"", r.stdout
    want, readable = sb.bus_files(address)
    assert (files, said) == ([os.fsencode(f) for f in want], b"busok=1" if readable else b"busok=0"), address


# PR #694's review, P4-B1a and P4-B1b: the launcher's choice of the bus the proxy is shown, and
# bus_warning(), counted `path=` and `abstract=` only as an entry's first key, where bus_files() and
# the launcher's reader of the socket files (P3-B4) take a key in any place, as libdbus and GIO do:
# `unix:guid=…,path=…` left a Standard app with no session bus (at the merge base it had its filtered
# one), and `unix:guid=…,abstract=…` without the warning that an app with the network grant reaches
# that bus unfiltered. How it slipped past: P3-B4's harness held the two readers of the socket files
# to each other, while the proxy's choice and the warning kept readings of their own, tested on the
# forms dbus writes, which put the path or the name first. This holds every reading of the address
# to every order of each entry's keys: the files, whether one can't be read, the bus the proxy is
# shown and the warning stay the same, and the launcher's `abstract=` is the warning's.
BUS_KEY_ORDERS = {
    "unix:path=/nowhere/a/bus,guid=0123": "file /nowhere/a/bus",
    "unix:abstract=/tmp/dbus-x,guid=0123": "abstract",
    "unix:path=/nowhere/a/bus,guid=0123,foo=1": "file /nowhere/a/bus",       # a key the clients don't know: they connect
    "unix:abstract=/tmp/dbus-a,abstract=/tmp/dbus-b": "abstract",             # the proxy's GDBus takes the last: no file to show it
    "unix:path=/nowhere/a/bus,abstract=/tmp/dbus-x,guid=0123": "",           # no client takes both
    "unix:path=/nowhere/a/first,path=/nowhere/b/second,guid=0123": "",       # GDBus takes the last, the proxy would be shown one
    "unix:path=/nowhere/a%20b,guid=0123": "",                                # an escaped byte
    "unix:path=relative/bus,guid=0123": "",
    "unix:path=/nowhere/a/bus,guid=0123;unix:abstract=/tmp/dbus-x,guid=0123": "",   # a list
    "unix:tmpdir=/tmp,guid=0123": "",
    "tcp:host=localhost,port=4000": "",
    # a key the proxy's GDBus refuses the entry for (P5-1): an empty one (a trailing or doubled comma),
    # one with no `=`, one with nothing before it; libdbus takes the first, and bus_files() reads them
    "unix:path=/nowhere/a/bus,": "",
    "unix:path=/nowhere/a/bus,,guid=0123": "",
    "unix:path=/nowhere/a/bus,guid": "",
    "unix:path=/nowhere/a/bus,=0123": "",
    "unix:abstract=/tmp/dbus-x,": "",
    # a value with an escape GDBus can't read (not two hex digits, or an escaped NUL), in any key
    "unix:path=/nowhere/a/bus,guid=%zz": "",
    "unix:path=/nowhere/a/bus,guid=%00": "",
    "unix:abstract=/tmp/dbus-x%2,guid=0123": "",
    # a key's name as GIO reads it, unescaped (P6-1), and matched exactly: `PA%54H` is not `path`
    "unix:pa%74h=/nowhere/a/bus,guid=0123": "file /nowhere/a/bus",
    "unix:abstr%61ct=/tmp/dbus-x,guid=0123": "abstract",
    "unix:path=/nowhere/a/first,pa%74h=/nowhere/b/second": "",
    "unix:path=/nowhere/a/bus,%61bstract=/tmp/dbus-x": "",
    "unix:PA%54H=/nowhere/a/bus,guid=0123": "",
    # ...and a key's name GDBus can't unescape, for which it refuses the entry (P6-2)
    "unix:path=/nowhere/a/bus,g%zz=1": "",
    "unix:path=/nowhere/a/bus,%=1": "",
    "unix:abstract=/tmp/dbus-x,a%00=1": "",
}


def _key_orders(address):
    """`address` with each entry's keys in every order (the entries in theirs)."""
    entries = [e.partition(":") for e in address.split(";")]
    for keys in itertools.product(*(itertools.permutations(k.split(",")) for _, _, k in entries)):
        yield ";".join(t + c + ",".join(ks) for (t, c, _), ks in zip(entries, keys))


@pytest.mark.parametrize("address,proxy", BUS_KEY_ORDERS.items())
def test_every_reading_of_the_bus_address_takes_its_keys_in_any_order(monkeypatch, address, proxy):
    monkeypatch.setattr(sb, "OS", "linux")
    script = ("set -u\nrt=/nowhere-rt\n" + sb._BUS_BLOCK + 'printf "%s" "$bussocks"; echo "busok=$busok busabs=${busabs:-0}"\n'
              'case "$busat" in file) echo "proxy=file $busfile" ;; *) echo "proxy=$busat" ;; esac\n')
    seen = set()
    for order in _key_orders(address):
        r = subprocess.run(["sh", "-c", script], env={"PATH": os.environ["PATH"], "DBUS_SESSION_BUS_ADDRESS": order},
                           capture_output=True, timeout=30)
        assert r.returncode == 0 and r.stderr == b"", (order, r.stderr)
        *files, said, shown, end = r.stdout.split(b"\n")
        monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", order)
        want, readable = sb.bus_files()
        warns = bool(sb.bus_warning())
        assert said == f"busok={int(readable)} busabs={int(warns)}".encode() and end == b"", (order, r.stdout)
        assert sorted(files) == sorted(os.fsencode(f) for f in want), order
        assert shown == f"proxy={proxy}".encode(), (order, shown)
        seen.add((tuple(sorted(want)), readable, warns))
    assert len(seen) == 1, seen


# PR #694's review, P5-1: the launcher showed the proxy an entry with a key that has no `=` (a
# trailing or doubled comma, a bare `guid`), which its key loop skips, as _bus_keys() does, and which
# the proxy's own GDBus refuses whole: every connection the app made failed, and nothing said why.
# How it slipped past: the readings of the address were held to each other (BUS_KEY_ORDERS) and to
# the forms dbus writes, never to the reader that then connects with it, the proxy's GDBus. This
# holds the launcher's choice to it: every address the launcher shows the proxy (a socket file or an
# abstract name) is one GIO's own connect, g_dbus_address_get_stream(), the proxy's, takes -- it may
# find no bus there, but never refuses the address -- for each key shape alone and each pair in both
# orders, and every address the tests above read.
BUS_KEY_SHAPES = ["path=/nowhere/a/bus", "path=/nowhere/b/bus", "path=relative/bus", "path=/nowhere/a%20b", "path=",
                  "abstract=/tmp/dbus-x", "abstract=/tmp/dbus-a%20b", "guid=0123", "guid=", "foo=1", "tmpdir=/tmp",
                  "guid", "", "=0123", "guid=%zz", "guid=%2", "guid=%00", "foo=%", "guid=%41", "abstract=/tmp/dbus-%zz",
                  "abstract=/tmp/dbus-a%00b",
                  # a key's name escaped (P6-1): GIO unescapes it once and matches it exactly
                  "pa%74h=/nowhere/b/bus", "abstr%61ct=/tmp/dbus-y", "PA%54H=/nowhere/a/bus", "p%2561th=/nowhere/a/bus",
                  "pa%0ath=/nowhere/a/bus",
                  # ...and one GDBus can't unescape, for which it refuses the entry (P6-2)
                  "g%zz=1", "%=1", "a%00=1"]

_GIO_TAKES = """import json, sys
from gi.repository import Gio, GLib
refused = {}
for a in sys.argv[1:]:
    try:
        Gio.dbus_address_get_stream_sync(a, None)
    except GLib.Error as e:
        if e.matches(Gio.io_error_quark(), Gio.IOErrorEnum.INVALID_ARGUMENT):
            refused[a] = e.message
print(json.dumps(refused))
"""


def test_the_proxy_is_shown_a_bus_only_where_its_own_gdbus_takes_the_address():
    if subprocess.run(["python3", "-c", "from gi.repository import Gio"], capture_output=True).returncode:
        pytest.skip("needs python3-gi")
    addresses = {"unix:" + ",".join(keys) for n in (1, 2) for keys in itertools.product(BUS_KEY_SHAPES, repeat=n)}
    addresses |= {*BUS_READS, *(o for a in BUS_KEY_ORDERS for o in _key_orders(a)), *(a.format(rt="/nowhere-rt") for a in BUS_ADDRESSES)}
    addresses = sorted(addresses)
    script = 'set -u\nrt=/nowhere-rt\nfor DBUS_SESSION_BUS_ADDRESS in "$@"; do (\n' + sb._BUS_BLOCK + 'echo "${busat:--}"\n); done\n'
    r = subprocess.run(["sh", "-c", script, "sh", *addresses], capture_output=True, text=True, timeout=120)
    shown = dict(zip(addresses, r.stdout.splitlines()))
    assert r.returncode == 0 and r.stderr == "" and len(shown) == len(addresses) == len(r.stdout.splitlines()), r.stderr
    assert {"file", "abstract", "-"} == set(shown.values()), set(shown.values())
    to_proxy = [a for a, at in shown.items() if at != "-"]
    r = subprocess.run(["python3", "-I", "-c", _GIO_TAKES, *to_proxy], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout) == {}, r.stdout


# PR #694's review, P6-1: GDBus unescapes an address's key names as well as its values, so
# `unix:pa%74h=<socket>` is `path=` to GIO -- to every GLib and GTK program of that session, and to
# the proxy -- while libdbus and sd-bus take a key as written and refuse it. The launcher and
# bus_files() matched `path=` and `abstract=` as written, so neither saw that socket: a granted
# folder, or a tool's working folder, showed the app the unfiltered bus, and `abstr%61ct=` went
# without the warning. How it slipped past: P5-1's harness asked GIO only whether it refuses an
# address the proxy is shown, never which socket it then reaches, and no key shape had an escape in
# its name. This holds every reader to the socket GIO's own connect reaches, with a live socket at
# every file and abstract name the key shapes name: for each shape alone and each pair in both
# orders, a file it reaches is one bus_files() and the launcher's $bussocks name (or they count the
# address unreadable, which shows no folder at all), an abstract socket it reaches is warned of
# (bus_warning(), $busabs), and the bus the launcher shows the proxy is the one GIO reaches.
_GIO_REACHES = r"""import json, socket, sys
from gi.repository import Gio, GLib
job = json.load(sys.stdin)
ears = {}
for at in job["files"] + ["\0" + n for n in job["names"]]:
    ears[at] = socket.socket(socket.AF_UNIX)
    ears[at].bind(at)
    ears[at].listen(8)
    ears[at].setblocking(False)
def took(ear):
    try:
        ear.accept()[0].close()
        return True
    except BlockingIOError:
        return False
reached = {}
for a in job["addresses"]:
    try:
        Gio.dbus_address_get_stream_sync(a, None)[0].close(None)
    except GLib.Error:
        pass
    reached[a] = [at.replace("\0", "@", 1) for at, ear in ears.items() if took(ear)]
print(json.dumps(reached))
"""


def test_every_reader_of_the_bus_address_names_the_socket_gio_reaches(tmp_path, monkeypatch):
    if subprocess.run(["python3", "-c", "from gi.repository import Gio"], capture_output=True).returncode:
        pytest.skip("needs python3-gi")
    monkeypatch.setattr(sb, "OS", "linux")
    root, name = os.path.join(os.path.realpath(tmp_path), "s"), f"appkata-{os.getpid()}-{os.urandom(4).hex()}"   # $bussocks is `pwd -P`'s
    os.makedirs(f"{root}/a")
    os.makedirs(f"{root}/b")
    live = lambda shape: shape.replace("/nowhere/", f"{root}/").replace("/tmp/dbus-", f"{name}-")   # noqa: E731
    files = [f"{root}/a/bus", f"{root}/b/bus", f"{root}/a b"]
    names = [f"{name}-x", f"{name}-y", f"{name}-a b"]
    addresses = sorted({"unix:" + ",".join(map(live, keys)) for n in (1, 2) for keys in itertools.product(BUS_KEY_SHAPES, repeat=n)})
    job = json.dumps({"files": files, "names": names, "addresses": addresses})
    r = subprocess.run(["python3", "-I", "-c", _GIO_REACHES], input=job, capture_output=True, text=True, timeout=300, cwd=tmp_path)
    assert r.returncode == 0, r.stderr
    reached = json.loads(r.stdout)
    script = ('set -u\nrt=/nowhere-rt\nfor DBUS_SESSION_BUS_ADDRESS in "$@"; do (\n' + sb._BUS_BLOCK +
              'printf "%s" "$bussocks" | tr "\\n" "\\t"; echo "|$busok|${busabs:-0}|${busat:--}|$busfile"\n); done\n')
    r = subprocess.run(["sh", "-c", script, "sh", *addresses], capture_output=True, text=True, timeout=300)
    assert r.returncode == 0 and r.stderr == "" and len(r.stdout.splitlines()) == len(addresses), r.stderr
    wrong = {}
    for a, line in zip(addresses, r.stdout.splitlines()):
        socks, busok, busabs, busat, busfile = line.split("|")
        monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", a)
        want, readable = sb.bus_files()
        got, warns = reached[a], bool(sb.bus_warning())
        said = []
        for at in got:
            if at.startswith("@"):
                said += [] if warns and busabs == "1" else ["an abstract socket it isn't warned of"]
            else:
                said += [] if not readable or at in want else ["a file bus_files() doesn't name"]
                said += [] if busok == "0" or at in socks.split("\t") else ["a file $bussocks doesn't name"]
        if busat == "file" and got != [busfile]:
            said.append(f"the proxy shown {busfile}, and GIO reaches {got}")
        if busat == "abstract" and not (len(got) == 1 and got[0].startswith("@")):
            said.append(f"the proxy shown an abstract socket, and GIO reaches {got}")
        if said:
            wrong[a] = f"GIO reaches {got or 'nothing'}: {'; '.join(said)}"
    assert not wrong, f"{len(wrong)} of {len(addresses)}:\n" + "\n".join(f"{a}  {w}" for a, w in wrong.items()).replace(root, "S").replace(name, "N")


# PR #694's review, P5-B1: the cover matched a socket file only *under* a granted path, so a grant of
# the socket file itself, or of a link to it (a "folder" grant binds a file as readily as a folder,
# R17.3.1), left the live socket in sight, where an address the launcher can't read has a granted
# socket file covered. How it slipped past: the cover's tests varied how the address names the
# socket (P2-1, P3-B4) and granted its folder alone; how the grant shows it never varied. Each way
# here: the grant → where the app sees the socket through it (None: it doesn't). A link is followed
# when the app starts, as bwrap follows it. One pointed there after the launcher was written was
# covered too; since CR1.5-40 its grant is dropped at that launch, as any grant that no longer leads
# where it led, so nothing of it is there to cover.
GRANT_FORMS = {
    "its folder": "{tmp}/dbus-MZ8lHbtZ8K",
    "a folder above it": "{tmp}/dbus-MZ8lHbtZ8K",
    "the file itself": "{grant}",
    "a link to the file": "{grant}",
    "a link to its folder": "{grant}/dbus-MZ8lHbtZ8K",
    "a link pointed there later": None,
    "a folder beside it": None,
}


def _granted(grant, path, links):
    """The path `grant` grants for the socket at `path`, made (a link in `links`), and what to do
    once the launcher is written."""
    up = path.parent.parent
    (up / "beside").mkdir(exist_ok=True)
    made = {"its folder": path.parent, "a folder above it": up, "the file itself": path, "a folder beside it": up / "beside"}
    if grant in made:
        return str(made[grant]), None
    link = links / grant.replace(" ", "-")
    link.symlink_to({"a link to the file": path, "a link to its folder": path.parent, "a link pointed there later": up / "beside"}[grant])
    return str(link), (lambda: (link.unlink(), link.symlink_to(path.parent))) if grant == "a link pointed there later" else None


@pytest.mark.parametrize("form", BUS_FORMS)
@pytest.mark.parametrize("grant", GRANT_FORMS)
def test_a_folder_granted_where_the_session_bus_was_not_yet_hides_its_socket(tmp_path, tmp_path_factory, monkeypatch, grant, form):
    # A grant is judged when the launcher is written, by AppKata's own session's bus; a session
    # started another way can put its bus inside that folder later. The run covers the file, however
    # the session's address names it (P2-1, above), and however the grant shows it (P5-B1).
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", f"unix:path={tmp_path}/run/bus")
    home = tmp_path / "home"                     # every folder here is the user's own: /tmp is no grant's (CR1.5-5)
    monkeypatch.setenv("HOME", str(home))        # ...and a grant is named from the home (CR1.5-16)
    sock, path = _a_bus_socket(home / "up" / "tmp")
    (home / "links").mkdir()
    folder, then = _granted(grant, path, home / "links")
    shown = GRANT_FORMS[grant] and GRANT_FORMS[grant].format(tmp=path.parent, grant=folder)
    gs = sb.apply_overrides(sb.resolve_template("standard"), {"folders": {f"+{folder}": "rw"}})
    proxy, app, r, rt = _launched(tmp_path, monkeypatch, _bus_form(form, path), gs=gs, before=then)
    sock.close()
    assert r.returncode == 0 and "AppKata: the session bus here" not in r.stderr or proxy is None, (r.stdout, r.stderr)
    at = lambda *words: next((i for i in range(len(app)) if app[i:i + 3] == list(words)), None)   # noqa: E731
    covered = [app[i + 2] for i in range(len(app) - 2) if app[i:i + 2] == ["--ro-bind", "/dev/null"]]
    if grant == "a link pointed there later":
        assert at("--bind-try", folder, folder) is None and folder not in app, app          # dropped: it leads elsewhere now
        assert f"Demo runs sandboxed and isn't given {folder} this time" in r.stderr, r.stderr
    else:
        assert at("--bind-try", folder, folder) is not None, app                # the grant stands
    assert covered == ([shown] if shown else []), (covered, shown)
    if shown:
        assert at("--ro-bind", "/dev/null", shown) > at("--bind-try", folder, folder)     # after the folder's own bind
    # where this session's bus is elsewhere, nothing is covered
    _, app, r, _ = _launched(tmp_path_factory.mktemp("again"), monkeypatch, None, gs=gs, home=home)
    assert at("--bind-try", folder, folder) is not None and "/dev/null" not in app and r.returncode == 0, (app, r.stderr)


# CR1.5-40 (#665): a folder grant's source was text, judged once when the launcher was written and
# followed by bwrap, links and all, at every launch. With one grant inside another the app can put
# a link on the inner one's way (in the outer folder, which is the host's real one), and the next
# launch mounted what the link named: the user's real ~/.ssh, in the finding's run. How it slipped
# past: the one test of nested grants planted a link to /oldroot, which leads nowhere on the host
# and is skipped whatever bwrap does with a source; no test moved a grant's way between the
# launcher's writing and its run, but one for the bus's socket (GRANT_FORMS's "pointed there later").
# Here the launcher is run whole, a stand-in bwrap recording its words, and each folder's way is
# changed, or not, once the launcher is written: what leads elsewhere is not among the words, is
# not counted visible for a file argument, is covered by nothing, and is said on stderr.
def test_a_grant_that_no_longer_leads_where_it_led_is_dropped_at_the_launch_and_said(tmp_path, monkeypatch):
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", f"unix:path={tmp_path}/run/bus")
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    for d in ("Projects/sub/deep", "disk/Documents", "disk/Other", ".ssh", "Music"):
        (home / d).mkdir(parents=True)
    (home / "Docs").symlink_to(home / "disk" / "Documents")           # the user's own link, there before the grant
    (home / "Moved").symlink_to(home / "disk" / "Documents")          # ...and one the user points elsewhere later
    granted = {"Projects": "rw", "Projects/sub/deep": "ro", "Projects/later/deep": "rw", "Docs": "rw", "Moved": "ro", "Music": "ro", "NotThere/x": "rw"}
    gs = sb.apply_overrides(sb.resolve_template("standard"), {"folders": {f"+{home / p}": m for p, m in granted.items()}})
    stub = tmp_path / "forward.py"
    stub.write_text(_FORWARD_STUB)

    def since():                    # what the app does in ~/Projects, which is its to write, and the user to a link of their own
        (home / "Projects" / "evil").mkdir()
        (home / "Projects" / "evil" / "deep").symlink_to("../../.ssh")
        (home / "Projects" / "sub").rename(home / "Projects" / "sub.old")
        (home / "Projects" / "sub").symlink_to("evil")
        (home / "Projects" / "later").mkdir()
        (home / "Projects" / "later" / "deep").symlink_to(home / "Music")
        (home / "Moved").unlink()
        (home / "Moved").symlink_to(home / "disk" / "Other")

    _, app, r, _ = _launched(tmp_path, monkeypatch, None, gs=gs, forward=str(stub), args=[str(home / "a.txt")], before=since)
    assert r.returncode == 0, r.stderr
    users = lambda w: w.startswith(str(home) + "/") and os.path.relpath(w, home).split("/")[0] in ("Projects", "Docs", "Moved", "Music", "NotThere", "disk", ".ssh")      # noqa: E731
    binds = {dest: how for dest, how in _binds(app).items() if users(dest)}
    stand = {"Projects": "--bind-try", "Docs": "--bind-try", "Music": "--ro-bind-try", "NotThere/x": "--bind-try"}
    assert binds == {str(home / p): (flag, str(home / p)) for p, flag in stand.items()}, binds        # each as written, source and destination
    assert app.index(str(home / "Docs")) < app.index(str(home / "Music")) < app.index(str(home / "NotThere/x")) < app.index(str(home / "Projects"))
    assert not [w for w in app if "/.ssh" in w or "/Moved" in w or "/sub/deep" in w or "/later" in w], app
    told = json.loads(stub.with_name("forward.py.args").read_text())
    assert sorted(told[3:told.index("--")]) == sorted(str(home / p) for p in stand), told             # ...and no other is the app's to see
    said = [line for line in r.stderr.splitlines() if "isn't given" in line]
    led = {"Moved": ("disk/Documents", "disk/Other"), "Projects/later/deep": ("Projects/later/deep", "Music"), "Projects/sub/deep": ("Projects/sub/deep", ".ssh")}
    assert said == [LED.format(app="Demo", folder=home / p, was=home / was, now=home / now) for p, (was, now) in led.items()], r.stderr

    # Where the launcher can't ask (no `readlink` that answers), no grant stands; and one that doesn't
    # is not covered or shown empty either, where this session's bus names a file the launcher can't read
    gs = sb.apply_overrides(sb.resolve_template("standard"), {"folders": {f"+{home / 'Docs'}": "rw", f"+{home / 'Music'}": "ro"}})
    again = tmp_path / "again"
    again.mkdir()
    _, app, r, _ = _launched(again, monkeypatch, "unix:path=relative/bus", gs=gs, home=home, tools={"readlink": "#!/bin/sh\nexit 1\n"})
    assert r.returncode == 0 and not [w for w in app if users(w)], (app, r.stderr)
    for p, was in (("Docs", "disk/Documents"), ("Music", "Music")):
        assert LED.format(app="Demo", folder=home / p, was=home / was, now="nowhere that can be followed") in r.stderr, r.stderr
    (tmp_path / "once-more").mkdir()
    _, app, r, _ = _launched(tmp_path / "once-more", monkeypatch, "unix:path=relative/bus", gs=gs, home=home)
    assert {w for w in app if users(w)} == {str(home / "Docs"), str(home / "Music")} and app.count("--tmpfs") >= 2, app      # as before, where they stand


def test_a_grant_that_a_link_in_another_granted_folder_leads_to_is_refused_when_the_launcher_is_written(tmp_path, monkeypatch):
    # ...and a grant is judged anew: at the user's next Save of the sandbox (and, until CR1.5-53
    # below, at AppKata's next start, which wrote the launcher again once a grant led elsewhere).
    # Judged afresh there, the app's link would have become the folder's place for good, for every
    # folder no list names (~/Documents). So a grant is refused when a link on its way lies in
    # another folder of the set, whoever made the link: the chips, the launcher and the Sandbox
    # dialog's own check say so.
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "run"))
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", f"unix:path={tmp_path}/run/bus")
    for v in ("XDG_DATA_HOME", "XDG_CONFIG_HOME", "APPKATA_APPS", "APPKATA_DATA"):
        monkeypatch.delenv(v, raising=False)
    for d in ("Projects/real/deep", "Documents", "disk/Documents", "Music/albums"):
        (home / d).mkdir(parents=True)
    apps = str(home / "bin/apps")
    judged = lambda folders: sb.refused_folders({**sb.resolve_template("standard"), "folders": folders}, apps)      # noqa: E731
    both = {"~/Projects": "rw", "~/Projects/sub/deep": "ro"}
    assert judged(both) == {}                                                 # nothing there yet: both stand
    (home / "Projects" / "sub").symlink_to("real")                            # a link in the outer folder, to a folder in it
    why = "a link in ~/Projects, which the app can change, is on the way to it"
    assert judged(both) == {"~/Projects/sub/deep": why}
    assert judged({"~/Projects": "ro", "~/Projects/sub/deep": "ro"}) == {"~/Projects/sub/deep": why}      # a read-only one too: it may have been the app's before
    assert judged({"~/Projects/sub/deep": "ro"}) == {} and judged({"~/Projects/sub/deep": "ro", "~/Music": "rw"}) == {}      # the user's link, in no folder of the app's
    for target in ("../Documents", "sub", "/nowhere"):                        # ...one that leads out of it, a loop, one that leads nowhere
        (home / "Projects" / "sub").unlink()
        (home / "Projects" / "sub").symlink_to(target)
        assert judged(both) == {"~/Projects/sub/deep": why}, target
    # a link that is the grant itself, where it lies in another; a link outside every grant that leads into one, and what the app does there
    (home / "Projects" / "docs").symlink_to(home / "Documents")
    (home / "work").symlink_to(home / "Projects" / "real" / "deep")
    assert judged({"~/Projects": "rw", "~/Projects/docs": "rw"}) == {"~/Projects/docs": why}
    assert judged({"~/Projects": "rw", "~/work": "ro"}) == {}
    (home / "Projects" / "real").rename(home / "Projects" / "real.old")
    (home / "Projects" / "real").symlink_to("../Documents")
    assert judged({"~/Projects": "rw", "~/work": "ro"}) == {"~/work": why}
    # the user's own link to a folder kept elsewhere, and a folder granted in it: no link lies in a granted folder
    (home / "Docs").symlink_to(home / "disk" / "Documents")
    assert judged({"~/Docs": "rw", "~/Docs/letters": "ro", "~/Music": "ro", "~/Music/albums": "rw"}) == {}
    # a folder that is refused anyway is not the app's, so a link in it refuses nothing
    assert judged({"~": "rw", "~/Docs": "rw"}) == {"~": "your whole home folder"}
    # one judgement in every place a set is read
    gs = sb.apply_overrides(sb.resolve_template("standard"), {"folders": {"+" + p: m for p, m in both.items()}})
    assert f"~/Projects/sub/deep · refused: {why}" in sb.summary(gs, apps) and "~/Projects" in sb.summary(gs, apps)
    kept, refused = sb.strip_protected(gs, apps)
    assert set(kept["folders"]) == {"~/Projects"} and refused == [("~/Projects/sub/deep", why)]
    text = sb.build_launcher("app", "App", apps + "/app/1", "bin/app", gs, apps_root=apps)
    assert f"# Refused folder grant ~/Projects/sub/deep: {why} (R17.3.1)." in text
    assert f"g1={home}/Projects; leads \"$g1\" {home}/Projects || g1=\n" in text and "g2=" not in text and "/sub/deep" not in text.split("# Refused")[0]
    assert text.count("bind-try " + str(home)) == 1 and f'[ {home}/Projects = "$g1" ] && set -- --bind-try {home}/Projects {home}/Projects "$@"\n' in text

# CR1.5-53 (#743): where a granted folder leads was asked each time a launcher was written, and
# AppKata writes a launcher again at its start whenever its text would differ -- which it did as
# soon as a grant led elsewhere, where it leads being part of the text. So a link an app put on a
# grant's way was dropped for one launch (CR1.5-40) and taken for the folder's place from AppKata's
# next start on. The rule at writing (a link in another folder of the set, above) knows the set's
# own folders, and an app can write elsewhere: where a command-line tool was run, a folder it was
# handed, another app's grant above its own. In the finding's run a tool with ~/src5/proj/data
# read-only, run once in ~/src5/proj, put a link to ~/Documents where `data` was, and after
# AppKata's next start read the user's ~/Documents there. How it slipped past: #665's tests wrote
# the launcher again through the function that judges, and held the one road its rule names.
# Where each folder led is kept with the install now (its record), judged when an install takes the
# grant and when the user saves the app's sandbox, and every launcher written between is written
# with it: here through the code that writes them, with the launcher AppKata's start compares.
LED = ("{app} runs sandboxed and isn't given {folder} this time: it led to {was} when the app was given it and leads to {now} now, so a link on the "
       "way there was made or changed since. AppKata keeps to where it led: if the change is yours, save the app's sandbox again in its Sandbox "
       "dialog, and the folder is judged anew.")


def test_a_launcher_written_again_keeps_where_each_folder_led_and_only_an_install_or_the_users_save_judges_it_anew(fake_home, tmp_path, tmp_path_factory,
                                                                                                                   monkeypatch, server):   # noqa: F811
    import json as _json
    from appkata_core import install
    from appkata_core.db import DB, now
    monkeypatch.setattr(sb, "have_tools", lambda: True)
    monkeypatch.setattr(install, "desktop_dir", lambda: str(tmp_path / "applications"))
    monkeypatch.setenv("APPKATA_DATA", str(fake_home / ".local/share/appkata"))
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", f"unix:path={tmp_path}/run/bus")
    home, root = fake_home, fake_home / "Apps"
    target = root / "tool"
    (target / "1.0" / "bin").mkdir(parents=True)
    exe = target / "1.0" / "bin" / "tool"
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    for d in ("src/proj/data", "src/other", "Documents", "disk/Documents", "disk/Other", "Music"):
        (home / d).mkdir(parents=True)
    (home / "Docs").symlink_to(home / "disk" / "Documents")           # the user's own link, there before the grant
    gs = sb.apply_overrides(sb.resolve_template("cli-tool"), {"folders": {"+~/src/proj/data": "ro", "+~/Docs": "rw", "+~/Music": "ro"}})
    url = "https://example.org/alice/tool"
    app = {"name": "Tool", "url": url, "sandbox": sb.to_json(gs)}
    rec = {"id": "tool", "current": {"version": "1.0", "path": str(target / "1.0"), "exec": "1.0/bin/tool"}, "links": [], "files": [], "target": str(target)}
    db = DB(str(tmp_path / "a.db"))
    db.x("INSERT INTO installs(url, name, version, kind, record, installed_at) VALUES(?,?,?,?,?,?)", (url, "Tool", "1.0", "tarball", _json.dumps(rec), now()))
    port = install.Portable(folder=str(root), app_menu=False, command_dir="", stable_name=False)
    stored = lambda: _json.loads(db.one("SELECT record FROM installs WHERE url=?", (url,))["record"])      # noqa: E731
    monkeypatch.setattr(sb, "helpers_current", lambda app_id, gs: True)
    install.rewrite_launcher(db, app, port)                           # its first launcher: each folder judged now
    lp = target / "run"
    first = lp.read_text()
    led = {"~/Docs": str(home / "disk/Documents"), "~/Music": str(home / "Music"), "~/src/proj/data": str(home / "src/proj/data")}
    for n, (p, where) in enumerate(sorted(led.items()), 1):
        assert f'g{n}={home}/{p[2:]}; leads "$g{n}" {where} || g{n}=\n' in first, (p, first)
    assert install.launcher_is_current(stored(), app, port)

    # The tool, run once in ~/src/proj (its to write for that run), puts a link where its folder was;
    # and the user points a link of their own elsewhere. No rule at writing knows either road.
    (home / "src/proj/data").rename(home / "src/proj/data.old")
    (home / "src/proj/data").symlink_to("../../Documents")
    (home / "Docs").unlink()
    (home / "Docs").symlink_to(home / "disk" / "Other")
    assert sb.refused_folders(gs, str(root)) == {}
    # AppKata's next start finds the launcher it would write, so it writes none...
    assert install.launcher_is_current(stored(), app, port) and lp.read_text() == first
    # ...and where it does write one (a hand-edited launcher), the text is the same
    lp.write_text(first + "# edited by hand\n")
    assert not install.launcher_is_current(stored(), app, port)
    install.rewrite_launcher(db, app, port)
    assert lp.read_text() == first and stored()["sandboxLeads"] == led         # kept with the install
    # So does an update, the next version installed from its release, and a switch back to the kept one
    asset = _tarball(server, "tool-2.0.tar.gz", {"tool-2.0/bin/tool": 0o755})
    new = install.install(db, {**app, "installVersion": "2.0"}, asset, "tarball", [asset], portable=port)
    assert new["current"]["version"] == "2.0" and new["sandboxLeads"] == led == stored()["sandboxLeads"]
    updated = lp.read_text()
    assert updated != first and [line for line in updated.splitlines() if "; leads " in line] == [line for line in first.splitlines() if "; leads " in line]
    assert install.launcher_is_current(stored(), app, port)
    install.switch_to(db, app, "1.0", port)
    assert lp.read_text() == first and stored()["sandboxLeads"] == led

    # So the launch drops both, and says so, at every launch until the folder is judged anew
    _, bw, r, _ = _launched(tmp_path_factory.mktemp("launch"), monkeypatch, None, gs=gs, cwd=home / "src" / "other", home=home, leads=stored()["sandboxLeads"])
    assert r.returncode == 0, r.stderr
    binds = _binds(bw)
    assert binds[str(home / "Music")] == ("--ro-bind-try", str(home / "Music")) and str(home / "src" / "other") in binds, binds
    assert not [w for w in bw if "/Documents" in w or "/Docs" in w or "/proj/data" in w or "/disk" in w], bw
    assert [line for line in r.stderr.splitlines() if "isn't given" in line] == [
        LED.format(app="Demo", folder=home / "Docs", was=home / "disk/Documents", now=home / "disk/Other"),
        LED.format(app="Demo", folder=home / "src/proj/data", was=home / "src/proj/data", now=home / "Documents")], r.stderr

    # The user's own Save of the app's sandbox judges every folder anew: the link that is theirs
    # is followed again, and so is any other on a grant's way, which is why the line names both places
    install.rewrite_launcher(db, {**app, "sandboxAnew": True}, port)         # as the backend asks for it (Backend._apply_sandbox)
    anew = {"~/Docs": str(home / "disk/Other"), "~/Music": str(home / "Music"), "~/src/proj/data": str(home / "Documents")}
    assert stored()["sandboxLeads"] == anew and f'g1={home}/Docs; leads "$g1" {home}/disk/Other || g1=\n' in lp.read_text()
    assert install.launcher_is_current(stored(), app, port)
    # a set with no folder of its own keeps nothing, nor does an app that runs Off; its next launcher is a first one
    install.rewrite_launcher(db, {**app, "sandbox": sb.to_json(sb.resolve_template("cli-tool"))}, port)
    assert "sandboxLeads" not in stored() and "sandbox" in stored()
    install.rewrite_launcher(db, app, port)
    assert stored()["sandboxLeads"] == anew
    install.rewrite_launcher(db, {**app, "sandbox": None}, port)
    assert "sandboxLeads" not in stored() and "sandbox" not in stored() and not lp.exists()
    (home / "Docs").unlink()
    (home / "Docs").symlink_to(home / "disk" / "Documents")
    install.rewrite_launcher(db, app, port)
    assert stored()["sandboxLeads"] == {**anew, "~/Docs": str(home / "disk/Documents")}
    # A link that leads a grant to a never-shared folder gets it refused where a launcher is written,
    # which the start then does; the answer kept is still the first, so the link pointed elsewhere
    # next is not taken for the folder's place either
    (home / ".ssh").mkdir()
    (home / "Docs").unlink()
    (home / "Docs").symlink_to(home / ".ssh")
    assert not install.launcher_is_current(stored(), app, port)
    install.rewrite_launcher(db, app, port)
    assert "# Refused folder grant ~/Docs: SSH keys (R17.3.1)." in lp.read_text() and f"{home}/Docs;" not in lp.read_text()
    assert stored()["sandboxLeads"]["~/Docs"] == str(home / "disk/Documents")
    (home / "Docs").unlink()
    (home / "Docs").symlink_to(home / "Music")
    assert not install.launcher_is_current(stored(), app, port)
    install.rewrite_launcher(db, app, port)
    assert f'g1={home}/Docs; leads "$g1" {home}/disk/Documents || g1=\n' in lp.read_text() and "# Refused folder grant ~/Docs" not in lp.read_text()

    # The answer itself (sandbox.folder_leads): kept for each folder still in the set, asked now for a
    # folder new to it or one whose answer is no path, forgotten for one that left; never for "$cwd"
    kept = sb.folder_leads(gs, {"~/Docs": "/was/there", "~/Gone": "/x", "~/Music": "", "~/src/proj/data": 7, "$cwd": "/y"})
    assert kept == {"~/Docs": "/was/there", "~/Music": str(home / "Music"), "~/src/proj/data": str(home / "Documents")}
    assert sb.folder_leads(gs) == sb.folder_leads(gs, None) == sb.folder_leads(gs, "junk") == {**kept, "~/Docs": str(home / "Music")}
    assert sb.folder_leads(sb.resolve_template("cli-tool")) == {}


def test_proxy_args_map_capabilities():
    args = sb.proxy_args(sb.resolve_template("media-player"), "vlc")
    assert "--own=org.mpris.MediaPlayer2.*" in args      # media keys
    assert "--call=org.freedesktop.ScreenSaver=org.freedesktop.ScreenSaver.Inhibit@/org/freedesktop/ScreenSaver" in args  # inhibit


# The names a grant set opens whole (`--talk`: whatever the connection that owns the name serves),
# each with what was seen of that connection.
OPENED_WHOLE = {
    "org.freedesktop.portal.IBus": "IBus 1.5.29's ibus-portal: a process and connection of its own, with the portal object alone",
    "org.freedesktop.portal.Fcitx": "Fcitx 5.1.7: a connection of its own, with the input-method objects alone",
}


def test_a_direct_name_is_opened_for_its_own_service_and_no_name_whole_but_the_listed():
    # CR1.5-3: the notifications, inhibit and tray capabilities passed `--talk=NAME`, which
    # xdg-dbus-proxy gives to the connection owning NAME -- on Cinnamon the desktop's own shell,
    # with everything it serves (org.Cinnamon.Eval ran a command outside the sandbox). Each
    # direct name is opened as the portal is, for its service's own interface on its own objects;
    # and since the tests then checked that `--talk` word itself, this one holds the whole class:
    # no `--talk` but the listed names, and no rule without both an interface and an object.
    every = sb.proxy_args({"caps": sorted(sb.CAP_PROXY_ARGS)}, "demo")
    assert {a.split("=", 1)[1] for a in every if a.startswith("--talk=")} == set(OPENED_WHOLE)
    assert not [a for a in every if a.startswith("--see=")]
    for a in every:
        if a.startswith(("--call=", "--broadcast=")):
            name, rule = a.split("=", 2)[1:]
            member, at, path = rule.partition("@")
            assert member.startswith(("org.", "com.")) and at and path.startswith("/") and path != "/*", a
    # CR1.5-44: and of a service's interface, what its capability means. The ScreenSaver interface
    # also locks the screen, switches the screen saver on and tells how long the user has been idle
    # (KDE's screen locker serves all of it; GNOME's and Cinnamon's declare it), so Keep the screen
    # awake opens its inhibit pair alone, and hears none of its signals.
    services = {"notifications": ("org.freedesktop.Notifications", ["/org/freedesktop/Notifications"], ["*"], True),
                "inhibit": ("org.freedesktop.ScreenSaver", ["/org/freedesktop/ScreenSaver", "/ScreenSaver"], ["Inhibit", "UnInhibit"], False),
                "tray": ("org.kde.StatusNotifierWatcher", ["/StatusNotifierWatcher"], ["*"], True)}
    for cap, (name, paths, members, signals) in services.items():
        rules = [a for a in sb.CAP_PROXY_ARGS[cap] if a.split("=", 2)[1] == name]
        want = set()
        for path in paths:
            want |= {f"--call={name}={name}.{m}@{path}" for m in members} | {f"--call={name}=org.freedesktop.DBus.Introspectable.*@{path}"}
            want |= {f"--broadcast={name}={name}.*@{path}"} if signals else set()
        if cap == "tray":       # what Qt's tray icon reads before it registers (IsStatusNotifierHostRegistered)
            want |= {f"--call={name}=org.freedesktop.DBus.Properties.{m}@/StatusNotifierWatcher" for m in ("Get", "GetAll")}
        assert set(rules) == want, cap
    # an app without a capability has none of its rules, on either road
    plain = sb.proxy_args(sb.resolve_template("offline-editor"), "ed")
    assert not [a for a in plain for name, *_ in services.values() if name in a]


def test_saved_passwords_open_the_secret_service_alone():
    # CR1.5-43: Saved passwords opened org.freedesktop.secrets whole (`--talk`), and gnome-keyring's
    # connection serves more than the Secret Service on it: its daemon interface (the session's SSH
    # agent socket and control folder), its master-password interface beside the service on the
    # service's own object, and the Secret portal's backend. The Secret Service's five interfaces
    # are opened on its object tree alone (the service, and below it the collections and aliases,
    # items, sessions and prompts), with the property calls and the listing clients make, and the
    # service's own signals.
    name, tree = "org.freedesktop.secrets", "/org/freedesktop/secrets/*"
    secret = [f"org.freedesktop.Secret.{i}" for i in ("Service", "Collection", "Item", "Session", "Prompt")]
    want = {f"--call={name}={i}.*@{tree}" for i in [*secret, "org.freedesktop.DBus.Properties", "org.freedesktop.DBus.Introspectable"]}
    want |= {f"--broadcast={name}={i}.*@{tree}" for i in secret[:2] + secret[4:]}
    want.add(f"--broadcast={name}=org.freedesktop.DBus.Properties.PropertiesChanged@{tree}")
    assert set(sb.CAP_PROXY_ARGS["secrets"]) == want
    args = sb.proxy_args(sb.apply_overrides(sb.resolve_template("standard"), {"caps": ["secrets"]}), "keys")
    assert {a for a in args if name in a} == want and not [a for a in args if "org.gnome.keyring" in a or "impl.portal" in a]
    assert not [a for a in sb.proxy_args(sb.resolve_template("standard"), "plain") if name in a]       # none without it


def test_the_notification_and_inhibit_portals_come_with_their_capabilities():
    # Regression (round three, R3-6): the Notification and Inhibit portals were open to every Standard
    # app, so a GLib app in an offline-editor sandbox (no "Notifications" chip) notified through the
    # portal anyway. Each capability now opens both roads -- the portal interface and the direct
    # name -- and an app without it has neither.
    portal = "--call=org.freedesktop.portal.Desktop=org.freedesktop.portal.{}.*@/org/freedesktop/portal/desktop"
    plain = sb.proxy_args(sb.resolve_template("offline-editor"), "ed")        # no capabilities
    direct = "--call=org.freedesktop.{0}=org.freedesktop.{0}.*@/org/freedesktop/{0}"
    assert portal.format("Notification") not in plain and not [a for a in plain if "org.freedesktop.Notifications" in a]
    assert portal.format("Inhibit") not in plain and not [a for a in plain if "org.freedesktop.ScreenSaver" in a]
    assert portal.format("OpenURI") in plain                                   # the always-on portals stay
    web = sb.proxy_args(sb.resolve_template("online-app"), "web")            # notifications only
    assert portal.format("Notification") in web and direct.format("Notifications") in web
    assert portal.format("Inhibit") not in web and not [a for a in web if "org.freedesktop.ScreenSaver" in a]
    chat = sb.proxy_args(sb.resolve_template("messenger"), "chat")           # both
    assert portal.format("Notification") in chat and portal.format("Inhibit") in chat
    assert "--call=org.freedesktop.ScreenSaver=org.freedesktop.ScreenSaver.Inhibit@/org/freedesktop/ScreenSaver" in chat
    # CR1.5-28: so do the two portals that tell of the host's network, with the network grant. An
    # offline-editor has no network: neither portal, nor the signal that says the network changed.
    changed = "--broadcast=org.freedesktop.portal.Desktop=org.freedesktop.portal.NetworkMonitor.changed@/org/freedesktop/portal/desktop"
    assert not [a for a in plain if "NetworkMonitor" in a or "ProxyResolver" in a], plain
    assert portal.format("NetworkMonitor") in web and portal.format("ProxyResolver") in web and changed in web


def _portals_opened(args: list) -> set:
    """The Desktop portal's interfaces a filter opens, by a call or by a broadcast signal."""
    return {a.split("Desktop=org.freedesktop.portal.", 1)[1].split(".")[0] for a in args
            if a.startswith(("--call=org.freedesktop.portal.Desktop=org.freedesktop.portal.", "--broadcast=org.freedesktop.portal.Desktop=org.freedesktop.portal."))}


@pytest.mark.parametrize("template", [t for t in sb.TEMPLATE_ORDER if sb.resolve_template(t)["level"] == "standard"])
@pytest.mark.parametrize("network", [True, False])
def test_what_the_host_says_of_its_network_reaches_an_app_only_with_the_network_grant(template, network):
    # CR1.5-28: the launcher withholds the host's proxy variables from an app without the network
    # grant, since they can carry the proxy's user name and password (R17.4; review 2, F15) -- and
    # the filter opened the ProxyResolver portal to every app on the bus, which answers Lookup(uri)
    # with those same settings (GIO's resolver builds http://user:password@host:port from the
    # desktop's), and NetworkMonitor with the host's connection state. An app that may not use the
    # network gains nothing from either call but the settings, so the withholding was undone for
    # exactly the apps it protects. How it slipped past: each road had its own test (the variables,
    # the marker) or none (the portals were checked against R17.5's own list, which said the same),
    # and nothing put the roads side by side. This does, for every Standard template either way:
    # the variables, the marker's [Context] and the two portals all follow the one grant -- and
    # every portal interface the filter opens has a switch that accounts for it.
    assert "GIO_USE_PROXY_RESOLVER" not in sb.build_launcher("vault", "Vault", "/apps/vault/1", "bin/vault", sb.resolve_template("strict"))   # no bus, nothing to ask
    gs = sb.apply_overrides(sb.resolve_template(template), {"network": network})
    text = sb.build_launcher("demo", "Demo", "/apps/demo/1", "bin/demo", gs)
    passed = next(line for line in text.splitlines() if line.startswith("for v in ") and "LANG" in line).removesuffix("; do").split()
    assert all((v in passed) is network for v in sb._PROXY_PASSTHROUGH), passed
    assert ("shared=network;" in sb.flatpak_info_text("demo", sb._marker_network(gs))) is network
    # ...and where the portal is closed GLib is told not to ask it: it asks before every connection
    # it makes, the app's own loopback included, and a refusal fails the connection (tier 2)
    assert ("  --setenv GIO_USE_PROXY_RESOLVER dummy \\\n" in text) is not network
    args = sb.proxy_args(gs, "demo")
    assert all((sb._portal_call(i) in args) is network for i in sb.NETWORK_PORTAL_INTERFACES), args
    switched = {"Notification": "notifications" in gs["caps"], "Inhibit": "inhibit" in gs["caps"],
                **{i: network for i in sb.NETWORK_PORTAL_INTERFACES}}
    assert _portals_opened(args) == {*sb.PORTAL_INTERFACES, "Request", "Session", *[i for i, on in switched.items() if on]}
    assert not set(sb.PORTAL_INTERFACES) & set(switched)          # and "every app" names none that has a switch


# ---------------------------------------------------------------- the app's own MPRIS name (R17.5.1, CR1.5-36)

VLC = "org.mpris.MediaPlayer2.vlc"


def _player(name=None, template="media-player"):
    return sb.apply_overrides(sb.resolve_template(template), {"mpris_name": name} if name else {})


def test_media_keys_own_the_apps_own_mpris_name_and_every_name_only_when_nobody_named_it():
    # CR1.5-36: Media keys passed `--own=org.mpris.MediaPlayer2.*`, and to xdg-dbus-proxy an own is
    # a talk too, on every name below the prefix, whoever owns it: the app could call every other
    # media player (and whatever else that player's connection serves). The need is the reverse,
    # the desktop calling the app on the app's own name, so the launcher owns the name a review
    # gives, and that alone. The only test of the capability ran the daemon calling the app.
    own = lambda gs: [a for a in sb.proxy_args(gs, "player") if "mpris" in a]      # noqa: E731
    assert own(_player(VLC)) == [f"--own={VLC}"]
    assert own(_player("org.mpris.MediaPlayer2.chromium.*")) == ["--own=org.mpris.MediaPlayer2.chromium.*"]   # a name per instance
    assert own(_player()) == ["--own=org.mpris.MediaPlayer2.*"]                 # nobody named it: every name, as before
    assert sb.CAP_PROXY_ARGS["mpris"] == ["--own=org.mpris.MediaPlayer2.*"]
    # a name is no capability: without Media keys it grants nothing, and the set doesn't keep it
    plain = sb.apply_overrides(sb.resolve_template("online-app"), {"mpris_name": VLC})
    assert own(plain) == [] and sb.normalize(plain)["mpris_name"] is None
    assert sb.normalize({**_player(VLC), "level": "strict"})["mpris_name"] is None     # Strict has no bus
    # what isn't one name below the prefix is no name: the whole prefix, another service's name, an
    # element xdg-dbus-proxy refuses (it exits, and the app has no bus), a second argument
    for bad in ("org.mpris.MediaPlayer2.*", "org.mpris.MediaPlayer2", "org.freedesktop.secrets", "org.mpris.MediaPlayer2.7zip",
                "org.mpris.MediaPlayer2..vlc", "org.mpris.MediaPlayer2.*.vlc", "org.mpris.MediaPlayer2.vlc --talk=org.freedesktop.secrets",
                "org.mpris.MediaPlayer2.vlc.", "org.mpris.MediaPlayer3.vlc", "vlc", "org.mpris.MediaPlayer2." + "x" * 240, 7, ["x"]):
        assert sb.mpris_name(bad) is None, bad
        assert own(_player(bad)) == ["--own=org.mpris.MediaPlayer2.*"], bad
        assert trustfile._setting_value("sandboxMprisName", str(bad)) is None, bad      # the review line's reader agrees
    for good in (VLC, "org.mpris.MediaPlayer2.chromium.instance4711", "org.mpris.MediaPlayer2.firefox.instance_1_23",
                 "org.mpris.MediaPlayer2.io.github.Some-Player", "org.mpris.MediaPlayer2.chromium.*"):
        assert sb.mpris_name(good) == good and trustfile._setting_value("sandboxMprisName", f"`{good}`") == good, good
    # the grant set carries it wherever a set goes: stored, compared, customized, reset
    gs = _player(VLC)
    assert sb.to_json(gs)["mpris_name"] == VLC and sb.normalize(sb.to_json(gs)) == sb.normalize(gs)
    assert sb.customized("media-player", gs) and not sb.customized("media-player", _player())
    assert sb.as_overrides("media-player", gs) == {"mpris_name": VLC}
    assert sb.grants_from_config({"template": "media-player", "overrides": sb.as_overrides("media-player", gs)}) == sb.normalize(gs)


def test_a_review_names_the_apps_mpris_name_and_reviews_merge_to_the_narrower_one():
    # R10.3.1: the line a review names it with, read, applied, written back and merged across Trusts
    section = ("## VLC::Settings\n\n- Sandbox (linux): media-player\n"
               f"- Sandbox MPRIS name (linux): `{VLC}`\n")
    parsed, warns = trustfile.parse_section("VLC", section)
    assert not warns
    opts = trustfile.resolve_settings(parsed["opts"], "linux")
    assert opts["sandboxMprisName"] == VLC
    assert trustfile.resolve_settings(parsed["opts"], "windows").get("sandboxMprisName") is None      # Linux-only, as every Sandbox line
    gs = sb.grants_from_config(sb.config_from_review(opts))
    assert gs["mpris_name"] == VLC and f"--own={VLC}" in sb.proxy_args(gs, "vlc")
    bad, _ = trustfile.parse_section("VLC", "## VLC::Settings\n\n- Sandbox: media-player\n- Sandbox MPRIS name: org.freedesktop.secrets\n")
    assert "sandboxMprisName" not in bad["opts"]                                 # no name below the prefix: ignored, as an unknown word is
    # ...and written: the user's own set as their review's lines, and read back the same
    written, refused = sb.as_review("media-player", gs)
    assert written == {"sandbox": "media-player", "sandboxMprisName": VLC} and not refused
    assert sb.grants_from_config(sb.config_from_review(written)) == sb.normalize(gs)
    text = trustfile.format_settings("VLC", trustfile.options_to_write({}, "", written, "linux"))
    assert f"- Sandbox MPRIS name (linux): {VLC}" in text
    assert "sandboxMprisName" not in sb.as_review("media-player", _player())[0]
    assert "sandboxMprisName" in trustfile.SANDBOX_KEYS and "sandboxMprisName" in trustfile.SETTINGS_ORDER
    # across Trusts the least privilege (R17.3.2): a name beats no name, the narrower of two wins,
    # and two reviews that name different players leave no name both allow, so no media keys
    one = lambda a, b: sb.intersect(_player(a), _player(b))                      # noqa: E731
    assert one(VLC, None)["mpris_name"] == VLC and one(None, VLC)["mpris_name"] == VLC
    assert one(VLC, VLC)["mpris_name"] == VLC and one(None, None)["mpris_name"] is None
    assert "mpris" in one(VLC, None)["caps"] and "mpris" in one(None, None)["caps"]
    per, inst = "org.mpris.MediaPlayer2.chromium.*", "org.mpris.MediaPlayer2.chromium.instance7"
    assert one(per, inst)["mpris_name"] == inst and one(inst, per)["mpris_name"] == inst
    assert one(per, "org.mpris.MediaPlayer2.chromium")["mpris_name"] == "org.mpris.MediaPlayer2.chromium"     # `.*` covers the name itself too
    assert one("org.mpris.MediaPlayer2.chromium.*", "org.mpris.MediaPlayer2.chromium.beta.*")["mpris_name"] == "org.mpris.MediaPlayer2.chromium.beta.*"
    for a, b in ((VLC, "org.mpris.MediaPlayer2.mpv"), (per, "org.mpris.MediaPlayer2.chromiumdev"), (VLC, "org.mpris.MediaPlayer2.vlc.instance1")):
        both = one(a, b)
        assert "mpris" not in both["caps"] and both["mpris_name"] is None and "inhibit" in both["caps"], (a, b)
    assert sb.intersect(_player(VLC), sb.resolve_template("online-app"))["mpris_name"] is None     # no Media keys in one: none
    # ...whatever the two say, in either order: the merged set never has a name one of them lacks
    covers = lambda wide, name: wide is None or wide == name or (wide.endswith(".*") and (name == wide[:-2] or name.startswith(wide[:-1])))   # noqa: E731
    names = (None, VLC, "org.mpris.MediaPlayer2.mpv", per, inst, "org.mpris.MediaPlayer2.chromium", "org.mpris.MediaPlayer2.chromium.beta.*",
             "org.mpris.MediaPlayer2.chromium.beta.instance1")
    for a in names:
        assert sb.intersect(_player(a), _player(a)) == sb.normalize(_player(a))
        for b in names:
            m = one(a, b)
            assert m == one(b, a), (a, b)
            if "mpris" in m["caps"]:
                assert covers(a, m["mpris_name"] or "org.mpris.MediaPlayer2.*") and covers(b, m["mpris_name"] or "org.mpris.MediaPlayer2.*"), (a, b, m["mpris_name"])
            else:
                assert a and b and not covers(a, b) and not covers(b, a), (a, b)
    _, merged = sb.resolve(reviews=[{"template": "media-player", "overrides": {"mpris_name": VLC}}, {"template": "media-player", "overrides": {}}])
    assert merged["mpris_name"] == VLC


def test_a_named_mpris_name_shows_as_the_narrowing_it_is():
    # the dialog's description, the Audit and the review badge say a set by its changes (R17.3.4,
    # R17.11): a name takes away every other one, so it reads as less access, never as more
    named, any_ = _player(VLC), _player()
    assert sb.changes(any_, named) == ([], [f"media-player names other than {VLC}"])
    assert sb.changes(named, any_) == (["every media-player name"], [])
    assert sb.changes(named, _player("org.mpris.MediaPlayer2.mpv")) == (["the media-player name org.mpris.MediaPlayer2.mpv"], [f"the media-player name {VLC}"])
    assert sb.changes(named, named) == ([], [])
    assert sb.describe("media-player", named) == f"Media player, without media-player names other than {VLC}"
    assert sb.describe("media-player", any_) == "Media player"
    narrower = sb.suggestion_text(any_, named, "Ana")
    assert narrower == f"Ana suggests removing media-player names other than {VLC}. The app may have more access than it needs."
    wider = sb.suggestion_text(named, any_, "Ana")
    assert wider == "Ana suggests adding every media-player name. Until you review it, the app may not work fully."
    # Media keys itself coming or going is said as that, once
    assert sb.changes(sb.resolve_template("online-app"), sb.apply_overrides(sb.resolve_template("online-app"), {"caps": ["notifications", "mpris"], "mpris_name": VLC})) == (["media keys"], [])
    assert sb.summary(named) == sb.summary(any_)                                  # the chip is the capability's; its hint says which names


# ---------------------------------------------------------------- the review lines (R10.3.1)

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
    # ignored on other platforms (R17.1, R10.3.1)
    assert trustfile.resolve_settings(parsed_only(out), "windows").get("sandbox") is None


def parsed_only(opts: dict) -> dict:
    return opts


def test_invalid_sandbox_template_is_ignored():
    section = "## Foo::Settings\n\n- Sandbox: not-a-template\n"
    parsed, _ = trustfile.parse_section("Foo", section)
    assert "sandbox" not in trustfile.resolve_settings(parsed["opts"], "linux")


# ---------------------------------------------------------------- install wiring (R17.4)

def test_activate_generates_launcher_and_points_everything_at_it(tmp_path, monkeypatch):
    from appkata_core import install
    from test_install_review import _menu_starts
    monkeypatch.setattr(sb, "have_tools", lambda: True)          # pretend bwrap/proxy are present
    monkeypatch.setattr(sb, "sandboxes_root", lambda: str(tmp_path / "sandboxes"))
    monkeypatch.setattr(install, "desktop_dir", lambda: str(tmp_path / "applications"))
    monkeypatch.setenv("APPKATA_DATA", str(tmp_path / "data"))      # where the script the menu entry starts goes
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
    # the .desktop entry (through its script, R4.3.1.1) and the command link point at the launcher, not the program
    desktop, menu = next(f for f in rec["files"] if f.endswith(".desktop")), str(tmp_path / "data" / "menu" / "demo")
    assert f'Exec=/bin/sh "{menu}" --appkata-menu %U' in open(desktop).read() and _menu_starts(menu) == launcher
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
    monkeypatch.setenv("APPKATA_DATA", str(tmp_path / "data"))
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
    # PipeWire/WirePlumber let a sandboxed client record through the sockets it plays through (R17.8),
    # so the summary says so rather than implying play-only protects the microphone.
    assert "Sound · can also record" in sb.summary(sb.resolve_template("online-app"))
    assert "Sound and microphone" in sb.summary(sb.resolve_template("messenger"))
    assert not any("ound" in c for c in sb.summary(sb.resolve_template("offline-editor")))


def test_a_chip_names_a_capability_as_its_switch_in_the_sandbox_dialog_does():
    # CR1.9-32: the summary's chip said "Secrets" and "Keep screen awake" where the Sandbox dialog's
    # switch for the same capability says "Saved passwords" and "Keep the screen awake": one
    # capability under two names on two screens, and A1.2.3.14's table of the names recorded both.
    # How it slipped past: the chips' words were held to nothing but the table that copied them.
    # Here every capability and the camera are held to the dialog itself: the chip a grant adds,
    # and the name a keyring capability refused to a review is shown under (R17.3.1), are the label
    # of its switch, word for word.
    with open(written.path("src/appkata/qml/SandboxDialog.qml"), encoding="utf-8") as f:
        switch = {key: label for label, key in re.findall(
            r'SbxToggle \{ label: "([^"]+)"; ic: "[a-z]+";(?: warn: true;)? on: root\.has\(root\.gs\.(?:caps|devices), "([a-z0-9-]+)"\)', f.read())}
    assert set(switch) == set(sb.CAP_LABELS) | set(sb.DEVICE_LABELS), switch          # each has its switch
    bare = sb.apply_overrides(sb.resolve_template("standard"), {"caps": [], "devices": ["x11"]})
    for field, key in [("caps", c) for c in sb.CAP_LABELS] + [("devices", "camera")]:   # x11, the default, has no chip
        granted = sb.apply_overrides(bare, {field: sorted({*bare[field], key})})
        assert [c for c in sb.summary(granted) if c not in sb.summary(bare)] == [switch[key]], key
    assert {c: name for c, (name, _) in sb.SECRET_CAPS.items()} == {c: switch[c] for c in sb.SECRET_CAPS}


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


class _Full:
    """A file being written on a full disk: it is there, and its write fails."""

    def __init__(self, f):
        self._f = f

    def write(self, *_):
        raise OSError(28, "No space left on device")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self._f.close()

    def __getattr__(self, name):
        return getattr(self._f, name)


@pytest.mark.parametrize("fails", ["a write", "a rename"])
def test_a_file_the_launcher_relies_on_whose_write_fails_leaves_nothing_beside_it(tmp_path, monkeypatch, fails):
    # #689's review, P5-B3: the launcher was written whole or not at all (P4-1), but the five files
    # written with it -- the identity marker, the seccomp filter, the file-argument helper, the
    # xdg-open shim and the private home's owner record -- went to <name>.<pid>.tmp and were renamed
    # with nothing removing the .tmp when the write or the rename failed (a full disk): each failure
    # left one in .identity/, its apps/ or bin/, or .owners/, one more per AppKata process that
    # tried, and nothing removed them. Each write and each rename fails in turn here: nothing is left
    # beside any of them, and each file is whole, as it was or as it is written.
    import builtins
    monkeypatch.setattr(sb, "sandboxes_root", lambda: str(tmp_path / "sandboxes"))
    apps = str(tmp_path / "apps")

    def write(template, url):
        sb.write_launcher("demo", "Demo", apps, f"{apps}/demo/1", "bin/demo", sb.resolve_template(template))
        sb.record_home_owner("demo", url)
    files = lambda: {p: open(p, "rb").read() for p in (sb.launcher_path("demo", apps), sb.identity_path("demo"), sb.forward_path(),
                                                       os.path.join(sb.shims_dir(), "xdg-open"), sb.home_owner_path("demo"))
                     + ((sb.seccomp_path(),) if sb.seccomp_filter() is not None else ())}
    write("online-app", "https://example.org/demo")
    new = files()
    shutil.rmtree(tmp_path / "sandboxes")
    shutil.rmtree(tmp_path / "apps")
    write("strict", "https://example.org/old")                  # what is there before: another marker, launcher and owner
    old = files()
    real_open, real_fdopen, real_replace = builtins.open, os.fdopen, os.replace
    for n in range(1, 20):
        count = []

        def hit(path):
            if str(path).startswith(str(tmp_path)):
                count.append(path)
                return len(count) == n
            return False
        if fails == "a write":
            monkeypatch.setattr(builtins, "open", lambda p, m="r", *a, **k: (
                _Full(real_open(p, m, *a, **k)) if "w" in m and hit(p) else real_open(p, m, *a, **k)))
            monkeypatch.setattr(os, "fdopen", lambda fd, m="r", *a, **k: (
                _Full(real_fdopen(fd, m, *a, **k)) if "w" in m and hit(os.readlink(f"/proc/self/fd/{fd}"))
                else real_fdopen(fd, m, *a, **k)))
        else:
            def replace(a, b, *x, **k):
                if hit(b):
                    raise OSError(28, "No space left on device")
                return real_replace(a, b, *x, **k)
            monkeypatch.setattr(os, "replace", replace)
        try:
            write("online-app", "https://example.org/demo")
            raised = None
        except OSError as e:
            raised = e
        finally:
            monkeypatch.setattr(builtins, "open", real_open)
            monkeypatch.setattr(os, "fdopen", real_fdopen)
            monkeypatch.setattr(os, "replace", real_replace)
        left = [os.path.join(d, f) for d, _, fs in os.walk(tmp_path) for f in fs if ".tmp" in f]
        assert left == [], (n, count[n - 1:n])                      # nothing beside the file that failed
        now = files()
        assert all(now[p] in (old[p], new[p]) for p in new), n     # each file whole, the old or the new
        if raised is None:
            assert now == new and len(count) < n                   # past the last write: all written
            break
        assert raised.errno == 28
        write("strict", "https://example.org/old")              # back to before, for the next one to fail
    else:
        raise AssertionError("every write failed")
    assert n == len(new) + 1                                       # each of the files' writes failed once


# Every name AppKata's own files have beside the per-app ones, and names an app could be given to meet them
COLLIDING_NAMES = ["bin", "Bin", "BIN!", "apps", "seccomp-tty.bpf", "forward-files.py", "xdg-open", ".identity", ".owners",
                   "identity", "owners", "run", "tmp", "1"]


@pytest.mark.parametrize("name", COLLIDING_NAMES)
@pytest.mark.parametrize("first", [True, False], ids=["the-first-app", "after-another"])
def test_no_app_name_takes_the_place_of_a_file_appkata_keeps_for_every_app(name, first, tmp_path, monkeypatch):
    # CR1.5-13: every app's marker was .identity/<id>, and the shims' folder .identity/bin beside
    # them. An app named "bin" -- its id is the name's slug -- installed after any other couldn't
    # have its launcher written (a file renamed over a folder, and a .tmp left behind); installed
    # first, its marker took the name and no app's launcher could be written again. How it slipped
    # past: no test gave an app a name that AppKata uses itself. The class is every file an app's id
    # names, against every file AppKata writes for all apps: here each is written, both orders, for
    # ids that are AppKata's own file names, and all of them are still there, each what it should be.
    from appkata_core.install import slug
    monkeypatch.setattr(sb, "sandboxes_root", lambda: str(tmp_path / "sandboxes"))
    app_id = slug(name)
    gs, apps = sb.resolve_template("online-app"), str(tmp_path / "apps")
    order = [app_id, "other"] if first else ["other", app_id]
    launchers = {i: sb.write_launcher(i, i.title(), apps, f"{apps}/{i}/1", f"bin/{i}", gs) for i in order}
    for i in order:
        sb.record_home_owner(i, f"https://example.org/{i}")
        os.makedirs(sb.sandbox_home(i), exist_ok=True)
        assert open(launchers[i]).read() == sb.launcher_text(i, i.title(), apps, f"{apps}/{i}/1", f"bin/{i}", gs)
        assert open(sb.identity_path(i)).read() == sb.flatpak_info_text(i, True)
        assert sb.helpers_current(i, gs)                           # the marker, the shim, the helper, the filter
        assert not sb.home_belongs_to_another(i, f"https://example.org/{i}")
    assert os.path.isdir(sb.shims_dir()) and os.access(os.path.join(sb.shims_dir(), "xdg-open"), os.X_OK)
    left = [os.path.join(d, f) for d, _, fs in os.walk(tmp_path) for f in fs if f.endswith(".tmp")]
    assert left == []                                              # nothing half-written is left behind
    # ... and the layout that makes it so: a folder for the markers alone, a folder for the owner
    # records alone, and no id that could be one of the names beside the private homes
    shared = [sb.shims_dir(), sb.seccomp_path(), sb.forward_path()]
    assert all(os.path.dirname(sb.identity_path(app_id)) not in (f, os.path.dirname(f)) for f in shared)
    assert os.path.dirname(sb.identity_path(app_id)) == os.path.dirname(sb.identity_path("other"))
    assert os.path.dirname(sb.home_owner_path(app_id)) not in [os.path.dirname(f) for f in shared]
    assert re.fullmatch(r"[a-z0-9-]+", app_id) and os.path.dirname(sb.sandbox_home(app_id)) == sb.sandboxes_root()
    # the marker's folders are the user's alone, as .identity was when the markers were directly in it
    for folder in (os.path.dirname(sb.identity_path(app_id)), os.path.dirname(os.path.dirname(sb.identity_path(app_id)))):
        assert os.stat(folder).st_mode & 0o777 == 0o700, folder
    sb.remove_sandbox_home(app_id)                                 # an uninstall takes the app's files and no other's
    assert not os.path.lexists(sb.identity_path(app_id)) and os.path.exists(sb.identity_path("other"))
    assert sb.helpers_current("other", gs)


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


# ---------------------------------------------------------------- the document portal & identity (R17.6)

def test_standard_launcher_binds_the_apps_document_portal_view():
    # Regression: the launcher never bound the document portal's FUSE export, so the path a portal
    # file chooser returns ($XDG_RUNTIME_DIR/doc/<id>/<name>) didn't exist inside the sandbox. With
    # folder grants all default Off, a Standard app couldn't open any user file at all.
    text = sb.build_launcher("web", "Web", "/apps/web/1", "bin/web", sb.resolve_template("online-app"))
    assert '--bind-try "$rt/doc/by-app/$id" "$rt/doc"' in text       # this app's documents only
    assert "GTK_USE_PORTAL" not in text        # the app's own dialog shows that view (R17.6.3, finding 0)
    # round six, R6-4: GTK 4.18 shows no dialog when the portal is denied; GDK_DEBUG=no-portals makes
    # GTK4 not ask, at every level, after --clearenv so it survives
    assert "--setenv GDK_DEBUG no-portals" in text and text.index("--clearenv") < text.index("GDK_DEBUG no-portals")
    assert "--setenv GDK_DEBUG no-portals" in sb.build_launcher("v", "V", "/apps/v/1", "bin/v", sb.resolve_template("strict"))
    assert text.index('--dir "$rt"') < text.index("/doc/by-app")      # the mount point exists first
    strict = sb.build_launcher("vault", "Vault", "/apps/vault/1", "bin/vault", sb.resolve_template("strict"))
    assert "/doc" not in strict                                        # no bus, so no portals


# ---------------------------------------------------------------- portals see a host caller (R17.6.1, finding 0)

def test_the_portals_see_the_app_as_a_host_caller_through_a_narrowed_proxy(tmp_path, monkeypatch):
    # Regression (review finding 0): the bus proxy carried /.flatpak-info, and xdg-desktop-portal 1.18+
    # refuses a marked caller that is not a running Flatpak ("Portal operation not allowed"), so on
    # Ubuntu 24.04 / Mint 22 no portal answered a sandboxed app at all. The proxy now has no marker --
    # the app is a host caller to the portals -- and the talk-to-everything policy on the portal name
    # became per-interface rules, since some portals trust a host caller with the host.
    monkeypatch.setattr(sb, "sandboxes_root", lambda: str(tmp_path / "sandboxes"))
    args = sb.proxy_args(sb.resolve_template("online-app"), "web")
    assert "--talk=org.freedesktop.portal.Desktop" not in args
    ruled = [a for a in args if a.startswith(("--call=", "--broadcast="))]
    # rules on the portal's name, and on the direct name of online-app's one capability (CR1.5-3), no other
    assert {a.split("=", 2)[1] for a in ruled} == {"org.freedesktop.portal.Desktop", "org.freedesktop.Notifications"}
    rules = [a for a in ruled if a.split("=", 2)[1] == "org.freedesktop.portal.Desktop"]
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
    # Round three, R3-1 (R17.4): GLib prefers a handler it can find over the OpenURI portal, and the
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
    # AppKata's first on its PATH, which goes through the OpenURI portal (R17.6.3).
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
    assert "APPKATA_NO_BUS" not in strict                               # no word and no bus is Strict (PR #694's review, P1-B3)
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


# ---------------------------------------------------------------- protected folders (R17.3.1)

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
    # what else the supported desktops load code from or start programs by (CR1.5-9, #384): Cinnamon's
    # folders, bash-completion's files, im-config's, the compositors' and window managers'
    # configurations, PipeWire's, an editor's extensions, and Cargo's and Go's programs
    ("~/.local/share/cinnamon", True), ("~/.local/share/cinnamon/applets", True), ("~/.local/share/cinnamon/desklets", True),
    ("~/.local/share/cinnamon/extensions/x@y", True), ("~/.local/share/cinnamon/search_providers", True),
    ("~/.local/share/cinnamon/panel-launchers", True), ("~/.cinnamon", True), ("~/.cinnamon/panel-launchers", True),
    ("~/.bash_completion", True), ("~/.config/bash_completion", True), ("~/.local/share/bash-completion", True),
    ("~/.local/share/bash-completion/completions", True), ("~/.xinputrc", True),
    ("~/.config/sway", True), ("~/.config/sway/config.d", True), ("~/.sway", True), ("~/.config/i3", True), ("~/.i3", True),
    ("~/.config/hypr", True), ("~/.config/labwc", True), ("~/.config/openbox", True), ("~/.config/river", True),
    ("~/.config/niri", True), ("~/.config/wayfire.ini", True), ("~/.config/pipewire", True),
    ("~/.config/pipewire/pipewire.conf.d", True), ("~/.vscode/extensions", True), ("~/.vscode", True),
    ("~/.vscode-oss/extensions", True), ("~/.cargo/bin", True), ("~/.cargo", True), ("~/go/bin", True), ("~/go", True),
    # the desktop's settings database, which names commands Cinnamon runs, and the file xdg-user-dir
    # runs as a script (pr-review pass 1 of #735, P1-2); the files beside them are no code
    ("~/.config/dconf", True), ("~/.config/dconf/user", True), ("~/.config/user-dirs.dirs", True),
    ("~/.config/dconf-editor", False), ("~/.config/user-dirs.locale", False), ("~/.config/user-dirs.conf", False),
    # more places of the same kinds, each found by a review of this unit and none by a test (pr-review
    # pass 2 of #735): the user's own menu files, which add app-menu entries from any folder (P2-1)
    ("~/.config/menus", True), ("~/.config/menus/applications-merged", True), ("~/.config/menus/cinnamon-applications.menu", True),
    ("~/.config/menus-old", False), ("~/.config/menulibre", False),
    # what cinnamon-session's Xsession hook sources, and Xsession's other name for ~/.xsession (P2-2)
    ("~/.gnomerc", True), ("~/.Xsession", True), ("~/.xsession", True), ("~/.gnomerc.bak", False), ("~/.gnome", False),
    ("~/.xsession-errors", False),
    # the user's thumbnailers, whose commands the file manager runs (P2B-1); the pictures they make are no code
    ("~/.local/share/thumbnailers", True), ("~/.local/share/thumbnailers/x.thumbnailer", True), ("~/.cache/thumbnails", False),
    ("~/.local/share/thumbnailers-old", False),
    # WirePlumber's configuration beside PipeWire's (P2C-1): the folder, since the file read is the instance's choice
    ("~/.config/wireplumber", True), ("~/.config/wireplumber/wireplumber.conf", True), ("~/.config/wireplumber/main.conf", True),
    ("~/.config/wireplumber/wireplumber.conf.d", True), ("~/.config/wireplumber-old", False), ("~/.local/state/wireplumber", False),
    # Readline's file, where a key can be made to type a command (P2C-2)
    ("~/.inputrc", True), ("~/.inputrc.bak", False), ("~/.input", False),
    # the sound clients' configuration, and the older folder libpulse reads instead where it exists (P2B-2)
    ("~/.config/pulse", True), ("~/.config/pulse/client.conf", True), ("~/.config/pulse/cookie", True), ("~/.pulse", True),
    ("~/.pulse/client.conf", True), ("~/.config/pulseeffects", False), ("~/.config/pavucontrol.ini", False), ("~/.pulse-old", False),
    ("~/go/src/proj", False), ("~/.config/swaylock", False), ("~/.bash_completion.bak", False), ("~/.cargo-target", False),
    ("~/.local/share/cinnamon-backup", False), ("~/.config/Code/User", False),
    ("~/Projects", False), ("~/Documents", False), ("~/.config/obsidian", False), ("/mnt/data", False), ("$cwd", False),
    ("~/.local/share/fonts", False), ("~/.config/git-extras", False), ("~/.bashrc.dev", False),
    # above a hosts folder; a profile beside it, which is no never-shared folder but a secret (CR1.5-8:
    # this line held it as a folder anyone could be granted; SECRETS has it now); above Nemo's two
    ("~/.config/chromium", True), ("~/.config/google-chrome/Default", False), ("~/.local/share/nemo", True),
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
    # (CR1.5-37: the default root is refused under a custom one too, since the earlier installs stay
    # there; the test held it as granted then.)
    custom = str(fake_home / "Apps")
    gs = sb.apply_overrides(sb.resolve_template("standard"), {"folders": {"+~/Apps/x": "rw", "+~/bin/apps": "rw", "+~/Projects": "rw"}})
    text = sb.build_launcher("app", "App", f"{custom}/app/1", "bin/app", gs, apps_root=custom)
    assert "# Refused folder grant ~/Apps/x: AppKata's installed apps" in text and f"--bind-try {home}/Projects" in text
    assert "# Refused folder grant ~/bin/apps: AppKata's installed apps" in text and f"--bind-try {home}/bin/apps" not in text
    chips = sb.summary(gs, custom)
    assert "~/Apps/x · refused: AppKata's installed apps" in chips and "~/bin/apps · refused: AppKata's installed apps" in chips
    chips = sb.summary(gs)                                                          # the default root: ~/Apps is nothing of AppKata's
    assert "~/bin/apps · refused: AppKata's installed apps" in chips and "~/Apps/x" in chips


# CR1.5-37 (#632): the never-shared list held one folder of AppKata's programs, the install folder of
# the app asked about, so ~/bin, where the command links are (on PATH, R4.3.1.3), was refused only as
# the folder above the default ~/bin/apps. With the install folder set elsewhere ~/bin and ~/bin/apps
# (the earlier installs' launchers, which the links start) could be granted, and a command links
# folder set elsewhere never was refused: a review's `Sandbox folders: ~/tools` gave an app the
# commands the user runs. How it slipped past: every test's settings were the defaults, or one custom
# install folder asked about itself. Each setting → the folders refused under it, and why.
LINKS = "the command links folder, which is on your PATH"
APPS = "AppKata's installed apps"
OWN_FOLDERS = [
    # (the install folder, the command links folders Settings and the records name), {folder: why, or "" when it is shared}
    ((None, ()), {"~/bin": "a folder above " + APPS, "~/bin/apps": APPS, "~/bin/apps/x/1.0": APPS, "~/bin/mine": LINKS, "~/tools": "", "~/Apps": ""}),
    (("~/Apps", ()), {"~/bin": "a folder above " + APPS, "~/bin/": "a folder above " + APPS, "~/bin/apps": APPS, "~/bin/apps/x/run": APPS,
                      "~/bin/mine": LINKS, "~/Apps": APPS, "~/Apps/x": APPS, "~/tools": ""}),
    (("~/Apps", ("~/tools",)), {"~/tools": LINKS, "~/tools/": LINKS, "~/tools/sub": LINKS, "~/tools/app": LINKS, "~/bin": "a folder above " + APPS,
                                 "~/bin/mine": LINKS, "~/bin/apps": APPS, "~/Apps/x": APPS, "~/tools-old": ""}),
    ((None, ("~/tools", "~/.local/opt/cmd")), {"~/tools": LINKS, "~/.local/opt/cmd": LINKS, "~/.local/opt": "a folder above " + LINKS,
                                                "~/.local/opt/other": "", "~/bin/mine": LINKS}),
    # a links folder that is the home, or above it, makes no folder of the home the links' own
    ((None, ("~",)), {"~/tools": "", "~/Notes/sub": "", "~": "your whole home folder", "~/bin/mine": LINKS}),
    ((None, ("/",)), {"~/tools": "", "/mnt/data": "", "~/bin/mine": LINKS}),
]


@pytest.mark.parametrize("setting,folders", OWN_FOLDERS, ids=[repr(s) for s, _ in OWN_FOLDERS])
def test_the_command_links_folder_and_the_default_install_folder_are_never_shared_wherever_apps_are_installed(setting, folders, a_users_home):
    root, commands = setting
    apps = os.path.expanduser(root) if root else None
    own = sb.Own(commands=tuple(os.path.expanduser(c) for c in commands))
    for mode in ("rw", "ro"):
        gs = sb.apply_overrides(sb.resolve_template("cli-tool"), {"folders": {"+" + p: mode for p in [*folders, "~/Notes"]}})
        text = sb.build_launcher("app", "App", (apps or "/home/kata/bin/apps") + "/app/1", "bin/app", gs, apps_root=apps, own=own,
                                 forward="/helper.py")
        chips = sb.summary(gs, apps, own=own)
        kept, refused = sb.strip_protected(gs, apps, own)
        for path, why in folders.items():
            named, full = sb.folder_path(path), os.path.expanduser(path).rstrip("/") or "/"
            assert sb.protected_folder(path, apps, own) == why, (path, sb.protected_folder(path, apps, own))
            assert (f"{named} · refused: {why}" in chips) is bool(why) and ((named, why) in refused) is bool(why), (path, chips)
            assert (f"# Refused folder grant {named}: {why} (R17.3.1)." in text) is bool(why)
            assert (f"bind-try {full} {full} " in text) is (not why), path        # mounted exactly when it is shared
        assert "~/Notes" in kept["folders"] and "bind-try /home/kata/Notes /home/kata/Notes " in text
    # ...and the launcher's own two lists hold the folders: the one a command-line tool's working
    # directory is refused by, and the one no file argument is handed over from (R17.3.3, R17.6.2)
    cwd_list = shlex.split(next(line for line in text.splitlines() if line.startswith('for d in "$hm" ')).split('"$hm" ', 1)[1].split(' "$rt"')[0])
    helper = shlex.split(next(line for line in text.splitlines() if "/helper.py" in line and "fwd=$(" in line).split("fwd=$(", 1)[1].rsplit(')', 1)[0], posix=True)
    never = helper[helper.index("--") + 2:helper.index("--", helper.index("--") + 1)]
    want = {"/home/kata/bin", "/home/kata/bin/apps", *([apps] if apps else []), *(c for c in own.commands if c not in ("/", "/home/kata"))}
    assert want <= set(cwd_list) and want <= set(never), (want, cwd_list, never)
    assert not {"/", "/home/kata"} & (set(cwd_list) | set(never))


# CR1.5-17 (#392): every root of both lists was joined to `~`. A user who moved the XDG folders, the
# GnuPG home or zsh's has the real autostart folder, systemd units, app-menu entries, keys and keyring
# where no list looked, and a grant of that place was an ordinary folder. Read only, never run: no
# test set one of the variables to anything but the default place. Each variable → the moved places
# refused, and why; the default places stay refused beside them, since a desktop reads the default
# wherever the variable isn't set for it.
MOVED = {"XDG_CONFIG_HOME": "/home/kata/cfg", "XDG_DATA_HOME": "/home/kata/data", "GNUPGHOME": "/home/kata/keys/gnupg", "ZDOTDIR": "/home/kata/cfg/zsh",
         "INPUTRC": "/home/kata/rl/inputrc"}
WM = "your window manager's configuration, which starts programs"
MOVED_PROTECTED = {
    "~/cfg/autostart": "autostart entries", "~/cfg/autostart/x.desktop": "autostart entries", "~/cfg/systemd/user": "systemd user units",
    "~/cfg/environment.d": "your login environment", "~/cfg/git": "your git configuration (hooks, aliases)", "~/cfg/fish": "your shell's startup files",
    "~/cfg/sway": WM, "~/cfg/bash_completion": "your shell's startup files",
    "~/cfg/dconf/user": "your desktop's settings, which name programs to start", "~/cfg/user-dirs.dirs": "your folders' names, which some programs run as a script", "~/cfg/google-chrome/NativeMessagingHosts": "programs browser extensions may start",
    "~/cfg/menus/cinnamon-applications-merged": "your app menu's layout, which can add app-menu entries from any folder",
    "~/data/thumbnailers": "thumbnailers, which your file manager runs as it shows a folder",
    "~/cfg/wireplumber/wireplumber.conf": "WirePlumber's configuration, which can start programs",
    "~/cfg/pulse/client.conf": "your sound setup, which can start a program or send your sound elsewhere", "~/.config/pulse": "your sound setup, which can start a program or send your sound elsewhere", "~/.pulse": "your sound setup, which can start a program or send your sound elsewhere",
    "~/rl/inputrc": "your terminal's key bindings, which can type commands", "~/rl": "a folder above your terminal's key bindings, which can type commands", "~/.inputrc": "your terminal's key bindings, which can type commands",
    "~/cfg/google-chrome": "a folder above programs browser extensions may start", "~/cfg": "a folder above autostart entries",
    "~/data/applications": "app-menu entries", "~/data/systemd": "systemd user units", "~/data/dbus-1/services": "D-Bus service activation",
    "~/data/flatpak": "Flatpak's user installation", "~/data/gnome-shell/extensions": "GNOME Shell extensions",
    "~/data/cinnamon/applets": "Cinnamon's applets, desklets, extensions and panel launchers", "~/data/nemo/actions": "file-manager actions",
    "~/data/bash-completion": "your shell's completion scripts", "~/data/appkata": "AppKata's own data and the apps' private homes",
    "~/keys/gnupg": "GPG keys", "~/keys/gnupg/private-keys-v1.d": "GPG keys", "~/keys": "a folder above GPG keys",
    "~/cfg/zsh/.zshrc": "your shell's startup files", "~/cfg/zsh/.zshenv": "your shell's startup files", "~/cfg/zsh/.zlogin": "your shell's startup files",
    # the default places, as before
    "~/.config/autostart": "autostart entries", "~/.config/systemd/user": "systemd user units", "~/.local/share/applications": "app-menu entries",
    "~/.gnupg": "GPG keys", "~/.zshrc": "your shell's startup files", "~/.config/sway": WM, "~/.config": "a folder above autostart entries"}
MOVED_SECRET = {
    "~/data/keyrings": "your keyring", "~/data/kwalletd": "your KDE wallet", "~/data/evolution/mail": "Evolution's mail and accounts",
    "~/cfg/gh": "your GitHub token", "~/cfg/gcloud": "cloud credentials", "~/cfg/rclone": "cloud storage tokens",
    "~/cfg/google-chrome/Default": "a browser's profiles and saved logins", "~/cfg/goa-1.0": "your online accounts' sign-ins",
    "~/cfg/mozilla/firefox": "Firefox's profiles and saved logins",
    "~/.local/share/keyrings": "your keyring", "~/.config/gh": "your GitHub token", "~/.config/google-chrome/Default": "a browser's profiles and saved logins"}
MOVED_SHARED = ["~/cfg-old", "~/data2/applications", "~/keys2", "~/Notes", "~/cfg/zsh/plugins", "~/cfg/obsidian", "~/data/fonts", "/media/usb",
                "~/rl2", "~/rl-old/inputrc"]


def test_a_never_shared_or_secret_folder_is_refused_where_the_environment_moves_it_and_at_its_default_place(a_users_home, monkeypatch):
    before = sb._protected_roots(), sb._secret_roots()
    for p in [*MOVED_PROTECTED, *MOVED_SECRET]:
        if not p.startswith(("~/.", "~/data/appkata")):
            assert not sb.protected_folder(p) and not sb.secret_folder(p), p          # an ordinary folder, while nothing is moved
    for var, where in MOVED.items():
        monkeypatch.setenv(var, where)
    for p, why in MOVED_PROTECTED.items():
        assert sb.protected_folder(p) == why, (p, sb.protected_folder(p))
    for p, why in MOVED_SECRET.items():
        assert sb.secret_folder(p) == why and not sb.protected_folder(p), (p, sb.secret_folder(p))
    for p in MOVED_SHARED:
        assert not sb.protected_folder(p) and not sb.secret_folder(p), p
    # a review's line: the never-shared ones refused in the chips, the picker and the launcher, the secrets by strip_secrets
    asked = [p for p in MOVED_PROTECTED if p.startswith(("~/cfg", "~/data", "~/keys", "~/rl"))]
    cfg = sb.config_from_review({"sandbox": "standard", "sandboxFolders": ", ".join(asked + list(MOVED_SECRET)) + ", ~/Notes"})
    source, gs, _ = sb.choose(None, None, [cfg], {"template": "strict"})
    gs, secret = sb.strip_secrets(gs)
    assert source == "reviews" and {p for p, _ in secret} >= set(MOVED_SECRET)
    chips = sb.summary(gs)
    text = sb.build_launcher("app", "App", "/home/kata/bin/apps/app/1", "bin/app", gs, apps_root="/home/kata/bin/apps")
    for p in asked:
        if not sb.secret_folder(p):               # ~/cfg and ~/cfg/google-chrome are above a secret too, which a review is refused first
            assert f"{p} · refused: {MOVED_PROTECTED[p]}" in chips and f"# Refused folder grant {p}: {MOVED_PROTECTED[p]} (R17.3.1)." in text
    assert [w for w in shlex.split(text.split("; do guard")[1].split("\nbwrap ")[0], comments=True) if w.startswith("/home/kata/")] == ["/home/kata/Notes"] * 3
    kept, refused = sb.strip_protected({**sb.to_json(sb.resolve_template("standard")), "folders": {p: "rw" for p in [*asked, "~/Notes"]}})
    assert set(kept["folders"]) == {"~/Notes"} and dict(refused) == {p: MOVED_PROTECTED[p] for p in asked}
    # a command-line tool's launcher holds the moved places in its two lists (R17.3.3, R17.6.2)
    tool = sb.build_launcher("tool", "Tool", "/home/kata/bin/apps/tool/1", "bin/tool", sb.resolve_template("cli-tool"), apps_root="/home/kata/bin/apps",
                             forward="/helper.py")
    for root in ("/home/kata/cfg/autostart", "/home/kata/data/applications", "/home/kata/keys/gnupg", "/home/kata/cfg/zsh/.zshrc",
                 "/home/kata/.config/autostart", "/home/kata/.gnupg"):
        assert tool.count(root + " ") == 3, root
    # the lists are as they were with the variables unset, set to the default place, empty, or no full path
    for var, where in {"XDG_CONFIG_HOME": "/home/kata/.config", "XDG_DATA_HOME": "/home/kata/.local/share/", "GNUPGHOME": "/home/kata/.gnupg",
                       "ZDOTDIR": "/home/kata", "INPUTRC": "/home/kata/.inputrc"}.items():
        monkeypatch.setenv(var, where)
    assert (sb._protected_roots(), sb._secret_roots()) == before
    # (but AppKata's own data folder, which is where platform.data_dir() says, whatever it makes of the variable)
    places = lambda roots: [r for r in roots if r[1] != "AppKata's own data and the apps' private homes"]      # noqa: E731
    for value in ("", "cfg", "./x"):
        for var in MOVED:
            monkeypatch.setenv(var, value)
        assert (places(sb._protected_roots()), sb._secret_roots()) == (places(before[0]), before[1]), value
    # ...and written with `~`, for the variables whose readers take it as it is (the XDG pair's and
    # zsh expand nothing); Readline and GnuPG expand it, which the test below holds them to
    for var in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "ZDOTDIR"):
        monkeypatch.setenv(var, "~/cfg")
    assert (places(sb._protected_roots()), sb._secret_roots()) == (places(before[0]), before[1])
    # a GnuPG home that is the home folder, or above it, makes no folder of the home the keys'
    monkeypatch.setenv("GNUPGHOME", "/home/kata")
    assert places(sb._protected_roots()) == places(before[0]) and not sb.protected_folder("~/Notes")


# pr-review pass 3 of #735 (P3B-1, P3-1): round 2's INPUTRC root took the value whatever it named, so
# one naming the home (or a folder above it) made every folder of the home "your terminal's key
# bindings"; and neither it nor GNUPGHOME was followed when written with `~`, which Readline and
# GnuPG expand, so the file or the keys such a value names were an ordinary folder. The moved test
# above gave both a full path below the home, and held "~/cfg" ignored for every variable alike.
# Each variable → the home and above add nothing, in every way of writing them; a value with `~`
# is refused as its full path is; and a value naming a folder stays refused, folder and all (a
# folder skipped would be one the app, granted the folder above, could swap for a file).
@pytest.mark.parametrize("var,why", [("INPUTRC", "your terminal's key bindings, which can type commands"), ("GNUPGHOME", "GPG keys")])
def test_a_variable_its_program_expands_is_followed_written_with_a_tilde_and_adds_nothing_as_the_home_or_above(var, why, fake_home, monkeypatch):
    for v in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME", "GNUPGHOME", "ZDOTDIR", "INPUTRC", "DBUS_SESSION_BUS_ADDRESS"):
        monkeypatch.delenv(v, raising=False)
    home = str(fake_home)
    for d in ("Notes", "Projects/sub", "rl/dir", "dots"):
        (fake_home / d).mkdir(parents=True)
    (fake_home / "rl" / "file").write_text("")
    os.symlink(home, fake_home / "dots" / "home")
    before = sb._protected_roots()
    ordinary = ("~/Notes", "~/Projects", "~/Projects/sub", "~/rl", "~/rl/dir", "~/rl/file", "~/dots")
    assert not any(sb.protected_folder(p) for p in ordinary)
    # the home, or above it: no root, and no folder of the home refused for it
    for value in (home, home + "/", home + "/.", home + "/Notes/..", os.path.dirname(home), "/", "~", "~/", "~/.", "~/Notes/..", "~/..",
                  home + "/dots/home", "~/dots/home"):
        monkeypatch.setenv(var, value)
        assert sb._protected_roots() == before, value
        assert not any(sb.protected_folder(p) for p in ordinary), value
    # a file or a folder of the home, as a full path and with `~`: refused, with what is in it and
    # the folders above it, and nothing beside it
    for value, named in ((home + "/rl/file", "~/rl/file"), ("~/rl/file", "~/rl/file"), (home + "/rl/dir", "~/rl/dir"), ("~/rl/dir", "~/rl/dir"),
                         ("~/rl/dir/", "~/rl/dir"), ("~/Projects/sub", "~/Projects/sub"), ("~/rl/new", "~/rl/new")):
        monkeypatch.setenv(var, value)
        assert sb._protected_roots() == before + [(os.path.join(home, named[2:]), why)], value
        assert sb.protected_folder(named) == why and sb.protected_folder(named + "/x") == why, value
        assert sb.protected_folder(os.path.dirname(named)) == "a folder above " + why, value
        assert not sb.protected_folder("~/Notes") and not sb.protected_folder("~/dots"), value
        kept, refused = sb.strip_protected({**sb.to_json(sb.resolve_template("standard")), "folders": {named: "rw", os.path.dirname(named): "rw", "~/Notes": "rw"}})
        assert set(kept["folders"]) == {"~/Notes"} and dict(refused) == {named: why, os.path.dirname(named): "a folder above " + why}, value
    # no other way of writing one is a path its program opens there
    for value in ("rl/file", "./rl/file", "~rl/file"):
        monkeypatch.setenv(var, value)
        assert sb._protected_roots() == before, value


def test_the_startup_pass_writes_a_launcher_again_once_a_variable_moves_a_never_shared_folder(fake_home, tmp_path, monkeypatch):
    # The lists are in the launcher's text (a tool's working-directory rule, the file-argument
    # helper's), as AppKata's own environment named the folders when it wrote it. Started with a
    # variable changed, AppKata's startup pass finds the text stale and writes it again (R17.4).
    from appkata_core import install
    monkeypatch.setattr(sb, "have_tools", lambda: True)
    monkeypatch.setattr(sb, "helpers_current", lambda app_id, gs: True)
    monkeypatch.setattr(install, "desktop_dir", lambda: str(tmp_path / "applications"))
    monkeypatch.setenv("APPKATA_DATA", str(fake_home / ".local/share/appkata"))
    for var in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "GNUPGHOME", "ZDOTDIR", "INPUTRC"):
        monkeypatch.delenv(var, raising=False)
    home, root = str(fake_home), fake_home / "bin" / "apps"
    target = root / "demo"
    (target / "1.0" / "bin").mkdir(parents=True)
    exe = target / "1.0" / "bin" / "demo"
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    rec = {"current": {"version": "1.0", "path": str(target / "1.0"), "exec": "1.0/bin/demo"}, "links": [], "files": [], "target": str(target)}
    app = {"name": "Demo", "sandbox": sb.to_json(sb.resolve_template("cli-tool"))}
    port = install.Portable(folder=str(root), app_menu=False, command_dir="", stable_name=False)
    install._activate(rec, app, port, str(target))
    assert install.launcher_is_current(rec, app, port) and f"{home}/cfg/autostart" not in open(target / "run").read()
    for var, where in (("XDG_CONFIG_HOME", f"{home}/cfg"), ("XDG_DATA_HOME", f"{home}/data"), ("GNUPGHOME", f"{home}/keys"), ("ZDOTDIR", f"{home}/zsh"),
                       ("INPUTRC", f"{home}/rl/inputrc")):
        monkeypatch.setenv(var, where)
        assert not install.launcher_is_current(rec, app, port), var
        install._activate(rec, app, port, str(target))
        assert install.launcher_is_current(rec, app, port)
    text = open(target / "run").read()
    for moved in (f"{home}/cfg/autostart", f"{home}/data/applications", f"{home}/keys", f"{home}/zsh/.zshrc", f"{home}/rl/inputrc",
                  f"{home}/.config/autostart"):
        assert moved + " " in text, moved


# CR1.5-45 (#701): ...and it held one install folder, the app's own. An app stays where it was
# installed when the setting changes (R4.3.1), so apps are in two folders, and an app in one could
# be granted the other read-write: another app's program and launcher. Each app's install folder
# and the folders the others are in → what it is refused. The two are told apart by where the app
# asked about is (`apps_root`); `own.roots` is every folder, the same for both.
TWO_ROOTS = ("/home/kata/Apps", "/home/kata/OldApps")


@pytest.mark.parametrize("mine,theirs", [TWO_ROOTS, TWO_ROOTS[::-1]], ids=["an app in the new folder", "an app in the old folder"])
def test_an_app_in_one_install_folder_is_never_given_another_folder_apps_are_installed_in(mine, theirs, a_users_home):
    own = sb.Own(roots=TWO_ROOTS)
    other = "~/" + os.path.basename(theirs)
    asked = [other, other + "/", other + "/victim", other + "/victim/run", other + "/victim/1.0/bin", "/home/kata/" + os.path.basename(theirs)]
    named = sorted({sb.folder_path(p) for p in asked})
    # a review's line, through config_from_review and choose
    cfg = sb.config_from_review({"sandbox": "standard", "sandboxFolders": ", ".join(asked) + ", ~/Notes"})
    source, gs, _ = sb.choose(None, None, [cfg], {"template": "strict"})
    assert source == "reviews" and set(gs["folders"]) == {*named, "~/Notes"}
    for p in asked:
        assert sb.protected_folder(p, mine, own) == APPS, p
        assert sb.protected_folder(p, mine) == ""                      # told of its own folder alone, as it was: shared
    chips = sb.summary(gs, mine, own=own)
    text = sb.build_launcher("app", "App", mine + "/app/1", "bin/app", gs, apps_root=mine, own=own)
    for p in named:
        assert f"{p} · refused: {APPS}" in chips and f"# Refused folder grant {p}: {APPS} (R17.3.1)." in text
    assert "bind-try " + theirs not in text and "bind-try /home/kata/Notes /home/kata/Notes " in text
    # the user's own pick, as the Sandbox dialog saves it
    kept, refused = sb.strip_protected({**sb.to_json(sb.resolve_template("standard")), "folders": {p: "rw" for p in [*named, "~/Notes"]}}, mine, own)
    assert set(kept["folders"]) == {"~/Notes"} and refused == [(p, APPS) for p in named]
    # a command-line tool installed in one is not given the other to work in, nor a file in it by its name
    tool = sb.build_launcher("tool", "Tool", mine + "/tool/1", "bin/tool", sb.resolve_template("cli-tool"), apps_root=mine, own=own, forward="/helper.py")
    cwd_list = shlex.split(next(line for line in tool.splitlines() if line.startswith('for d in "$hm" ')).split('"$hm" ', 1)[1].split(' "$rt"')[0])
    assert {mine, theirs, "/home/kata/bin/apps"} <= set(cwd_list)
    assert tool.count(theirs) == 3 and tool.count(mine + " ") >= 3      # the two lists of the tool's rule, and the helper's
    # an install folder that is the home folder, or above it, adds nothing: every folder would be AppKata's
    assert sb.protected_folder("~/Notes", mine, sb.Own(roots=("/home/kata", "/", *TWO_ROOTS))) == ""
    assert sb.protected_folder(other, mine, sb.Own(roots=("/home/kata", "/", *TWO_ROOTS))) == APPS


def test_a_launcher_an_install_writes_keeps_out_the_other_folders_apps_are_installed_in(fake_home, tmp_path, monkeypatch):
    # through the code that tells the sandbox: install.Portable as the backend fills it in (`others`)
    from appkata_core import install
    monkeypatch.setattr(sb, "have_tools", lambda: True)
    monkeypatch.setattr(install, "desktop_dir", lambda: str(tmp_path / "applications"))
    monkeypatch.setenv("APPKATA_DATA", str(fake_home / ".local/share/appkata"))
    home, root = str(fake_home), fake_home / "Apps"
    target = root / "demo"
    (target / "1.0" / "bin").mkdir(parents=True)
    exe = target / "1.0" / "bin" / "demo"
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    gs = sb.apply_overrides(sb.resolve_template("standard"), {"folders": {"+~/OldApps/victim": "rw", "+~/Projects": "rw"}})
    rec = {"current": {"version": "1.0", "path": str(target / "1.0"), "exec": "1.0/bin/demo"}, "links": [], "files": [], "target": str(target),
           "root": str(root)}
    app = {"name": "Demo", "sandbox": sb.to_json(gs)}
    both = sb.Own(roots=(str(root), f"{home}/OldApps"))
    port = install.Portable(folder=str(root), app_menu=False, command_dir="", stable_name=False, others=both)
    assert port.own == both
    install._activate(rec, app, port, str(target))
    text = open(target / "run").read()
    assert f"# Refused folder grant ~/OldApps/victim: {APPS} (R17.3.1)." in text and f"bind-try {home}/OldApps" not in text
    assert f"bind-try {home}/Projects {home}/Projects " in text
    monkeypatch.setattr(sb, "helpers_current", lambda app_id, gs: True)
    assert install.launcher_is_current(rec, app, port)
    # an install into a third folder, or Settings naming one: the startup pass writes this launcher again (R17.4)
    third = install.Portable(folder=str(root), app_menu=False, command_dir="", stable_name=False, others=both._replace(roots=(*both.roots, f"{home}/Third")))
    assert not install.launcher_is_current(rec, app, third)
    # ...and an update keeps the app where it is, told of the same folders (install._where_it_is)
    moved = install.Portable(folder=f"{home}/Third", command_dir="", others=both)
    assert install._where_it_is(rec, moved).root == str(root) and install._where_it_is(rec, moved).own == both


def test_a_review_cannot_grant_the_command_links_folder_and_a_launcher_an_install_writes_keeps_it_out(fake_home, tmp_path, monkeypatch):
    # the finding's own road, through the code that tells the sandbox where the links are: an install
    # with the install folder and the command links folder set elsewhere (install.Portable, as the
    # backend builds it from Settings), and a review that asks for ~/tools and ~/bin
    from appkata_core import install
    monkeypatch.setattr(sb, "have_tools", lambda: True)
    monkeypatch.setattr(install, "desktop_dir", lambda: str(tmp_path / "applications"))
    monkeypatch.setenv("APPKATA_DATA", str(fake_home / ".local/share/appkata"))
    home, root = str(fake_home), fake_home / "Apps"
    target = root / "demo"
    (target / "1.0" / "bin").mkdir(parents=True)
    exe = target / "1.0" / "bin" / "demo"
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    cfg = sb.config_from_review({"sandbox": "standard", "sandboxFolders": "~/tools, ~/bin:ro, ~/bin/apps, ~/Projects"})
    source, gs, _ = sb.choose(None, None, [cfg], {"template": "strict"})
    assert source == "reviews" and set(gs["folders"]) == {"~/tools", "~/bin", "~/bin/apps", "~/Projects"}
    rec = {"current": {"version": "1.0", "path": str(target / "1.0"), "exec": "1.0/bin/demo"}, "links": [], "files": [], "target": str(target)}
    app = {"name": "Demo", "sandbox": sb.to_json(gs)}
    port = install.Portable(folder=str(root), app_menu=False, command_dir="~/tools", stable_name=False)
    assert port.own == sb.Own(commands=(f"{home}/tools",))
    install._activate(rec, app, port, str(target))
    text = open(target / "run").read()
    assert os.path.realpath(f"{home}/tools/demo") == str(target / "run")                 # the command link, in ~/tools
    assert f"# Refused folder grant ~/tools: {LINKS} (R17.3.1)." in text and f"# Refused folder grant ~/bin/apps: {APPS} (R17.3.1)." in text
    assert f"# Refused folder grant ~/bin: a folder above {APPS} (R17.3.1)." in text
    assert f"bind-try {home}/Projects {home}/Projects " in text and f"bind-try {home}/tools" not in text and f"bind-try {home}/bin" not in text
    assert f"~/tools · refused: {LINKS}" in sb.summary(gs, port.root, own=port.own)       # the chips, told the same
    # the startup pass compares with the same folders (R17.4): current as written, and written again
    # once Settings or another install names a folder this launcher's lists don't hold
    monkeypatch.setattr(sb, "helpers_current", lambda app_id, gs: True)
    assert install.launcher_is_current(rec, app, port)
    elsewhere = install.Portable(folder=str(root), app_menu=False, command_dir="~/tools", stable_name=False, others=sb.Own(commands=(f"{home}/cmds",)))
    assert elsewhere.own == sb.Own(commands=(f"{home}/cmds", f"{home}/tools")) and not install.launcher_is_current(rec, app, elsewhere)
    # an app with no command link of its own is still told where the others' are
    none = install.Portable(folder=str(root), command_dir="", others=sb.Own(commands=(f"{home}/tools",)))
    assert none.own == sb.Own(commands=(f"{home}/tools",))


# CR1.5-9 (#384): the never-shared list is kept by hand, and places of the kinds it names were not in
# it on the desktops AppKata supports: Cinnamon's applet, desklet and extension folders (Mint's
# desktop, where GNOME's and KDE's were listed), bash-completion's files, im-config's ~/.xinputrc,
# the compositors' and window managers' configurations, PipeWire's, an editor's extensions and the
# folders Cargo and Go put on PATH. How it slipped past: the list was tested on its members, and
# "allowed" was the answer for any place not in it. The members are in the list above now; the
# finding's own road is here, and what the platform's own programs name as the places they load
# from is asked of the platform in tests/test_sandbox_run.py
# (a part of test_every_file_the_distributions_default_bashrc_sources_is_refused).
LATER = {"~/.local/share/cinnamon": "Cinnamon's applets, desklets, extensions and panel launchers",
         "~/.local/share/cinnamon/applets/weather@mockturtl": "Cinnamon's applets, desklets, extensions and panel launchers",
         "~/.cinnamon": "Cinnamon's panel launchers",
         "~/.bash_completion": "your shell's startup files", "~/.config/bash_completion": "your shell's startup files",
         "~/.local/share/bash-completion/completions": "your shell's completion scripts",
         "~/.xinputrc": "your session's startup files",
         "~/.config/sway": "your window manager's configuration, which starts programs",
         "~/.config/i3/config": "your window manager's configuration, which starts programs",
         "~/.config/pipewire": "PipeWire's configuration, which can start programs",
         "~/.vscode/extensions": "your editor's extensions", "~/.vscode": "a folder above your editor's extensions",
         "~/.cargo/bin": "programs on your PATH", "~/go": "a folder above programs on your PATH",
         # pr-review pass 1 of #735, P1-2: Cinnamon runs a custom keybinding's command, and opens the
         # terminal, that the settings database names; xdg-user-dir runs user-dirs.dirs as shell
         "~/.config/dconf": "your desktop's settings, which name programs to start", "~/.config/dconf/user": "your desktop's settings, which name programs to start",
         "~/.config/user-dirs.dirs": "your folders' names, which some programs run as a script",
         # pr-review pass 2 of #735, each a place a review could grant read-write. P2-1: a menu file of
         # the user's adds a folder of app-menu entries from anywhere, over the system's own
         "~/.config/menus": "your app menu's layout, which can add app-menu entries from any folder",
         "~/.config/menus/cinnamon-applications-merged": "your app menu's layout, which can add app-menu entries from any folder",
         # P2-2: sourced at every Cinnamon X11 login; run as the session where no other is named
         "~/.gnomerc": "your session's startup files", "~/.Xsession": "your session's startup files",
         # P2B-1: a .thumbnailer file's command, which Nemo runs for a file of its kind in a folder it shows
         "~/.local/share/thumbnailers": "thumbnailers, which your file manager runs as it shows a folder",
         # P2C-1: WirePlumber's own file has PipeWire's list of programs to start
         "~/.config/wireplumber": "WirePlumber's configuration, which can start programs", "~/.config/wireplumber/wireplumber.conf": "WirePlumber's configuration, which can start programs",
         # P2C-2: a key macro in Readline's file adds a command to the line the user wrote
         "~/.inputrc": "your terminal's key bindings, which can type commands",
         # P2B-2: client.conf names the program a sound client starts and the server it talks to
         "~/.config/pulse": "your sound setup, which can start a program or send your sound elsewhere", "~/.pulse": "your sound setup, which can start a program or send your sound elsewhere"}


def test_a_review_cannot_grant_a_place_code_runs_from_later_and_the_user_cannot_pick_one(a_users_home):
    # the finding's own case: a review's line through config_from_review and choose
    cfg = sb.config_from_review({"sandbox": "standard", "sandboxFolders": ", ".join(LATER) + ", ~/go/src/proj:ro, ~/Notes"})
    source, gs, _ = sb.choose(None, None, [cfg], {"template": "strict"})
    assert source == "reviews" and set(LATER) <= set(gs["folders"])            # a review's line is kept as written...
    assert sb.strip_secrets(gs)[1] == []                                       # ...is no secret, which only a review is refused...
    chips = sb.summary(gs)
    text = sb.build_launcher("app", "App", "/home/kata/bin/apps/app/1", "bin/app", gs, apps_root="/home/kata/bin/apps")
    for p, why in LATER.items():
        assert f"{p} · refused: {why}" in chips, (p, chips)                    # ...shown as refused...
        assert f"# Refused folder grant {p}: {why} (R17.3.1)." in text
        assert f"bind-try /home/kata/{p[2:]} " not in text                     # ...and never mounted
    assert "~/go/src/proj · read-only" in chips and "--ro-bind-try /home/kata/go/src/proj /home/kata/go/src/proj" in text
    assert "~/Notes" in chips and "--bind-try /home/kata/Notes /home/kata/Notes" in text
    # the user's own pick, as the Sandbox dialog saves it (Backend.setSandbox): dropped, with the same reason
    kept, refused = sb.strip_protected({**sb.to_json(sb.resolve_template("standard")), "folders": {p: "rw" for p in [*LATER, "~/Notes"]}})
    assert set(kept["folders"]) == {"~/Notes"} and dict(refused) == LATER
    # a command-line tool run from one of them is not given it (R17.3.3): the same list, in its launcher
    tool = sb.build_launcher("tool", "Tool", "/home/kata/bin/apps/tool/1", "bin/tool", sb.resolve_template("cli-tool"), apps_root="/home/kata/bin/apps")
    listed = shlex.split(next(line for line in tool.splitlines() if line.startswith('for d in "$hm" ')).split('"$hm" ', 1)[1].split(' "$rt"')[0])
    for p in LATER:
        if not LATER[p].startswith("a folder above"):
            assert any(("/home/kata/" + p[2:] + "/").startswith(d + "/") for d in listed), (p, listed)


# CR1.5-5 (#380, the owner's decision of 2026-11-24): the never-shared check knew the home, what is
# above it, and places under the home and the runtime folder. A system path was an ordinary folder to
# it, whoever asked, and a grant is bound after the sandbox's own /proc, /dev and /tmp: one line of a
# review, `Sandbox folders: /proc:ro`, put the host's process table over the sandbox's own, and with
# it every file of the user's (/proc/<pid>/root); /run/docker.sock, /tmp and /etc passed the same way.
# How it slipped past: every folder the tests granted was under a test's home or a made-up /mnt/data,
# and a test's home is under /tmp, which made /tmp "above the home" and hid that it was allowed. So
# the home here is where a user's is, and the class's test is the list itself, each place with what
# is inside and above it, beside the places outside the home that must still be shared.
@pytest.fixture
def a_users_home(monkeypatch, tmp_path):
    """A home where a user has one, outside every system place (nothing is written there), and
    AppKata running in a folder that is no part of it."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", "/home/kata")
    monkeypatch.setenv("XDG_RUNTIME_DIR", "/run/user/1000")
    for v in ("XDG_DATA_HOME", "XDG_CONFIG_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME", "APPKATA_APPS", "APPKATA_DATA", "DBUS_SESSION_BUS_ADDRESS"):
        monkeypatch.delenv(v, raising=False)
    return "/home/kata"


SYSTEM_REFUSED = {
    "/proc": "/proc", "/proc/1/environ": "/proc", "/proc/self/cwd": "/proc", "/sys": "/sys", "/sys/kernel/debug": "/sys",
    "/dev": "/dev", "/dev/shm": "/dev", "/run/dbus": "/run", "/run/dbus/system_bus_socket": "/run",
    "/run/docker.sock": "/run", "/run/podman": "/run", "/run/libvirt": "/run", "/run/snapd.socket": "/run",
    "/run/systemd": "/run", "/var/run/docker.sock": "/var/run", "/tmp": "/tmp", "/tmp/ssh-XXXXab12cd/agent.4242": "/tmp",
    "/tmp/tmux-1000/default": "/tmp", "/var/tmp": "/var/tmp", "/var/tmp/build": "/var/tmp", "/etc": "/etc",
    "/etc/ssl/private": "/etc", "/usr": "/usr", "/usr/share/fonts": "/usr", "/boot": "/boot", "/boot/efi": "/boot",
    # however it is written: the path as written is where the grant is mounted in the sandbox
    "//proc": "/proc", "/proc/": "/proc", "/./tmp/x": "/tmp", "/run/media/../docker.sock": "/run", "/mnt/../dev/shm": "/dev",
}
SYSTEM_ABOVE = ["/var"]                # above /var/run and /var/tmp
# /run and /var/run themselves were refused before, as folders above the runtime folder, and still are
SYSTEM_SHARED = ["/media", "/media/usb", "/mnt", "/mnt/data", "/run/media", "/run/media/kata", "/run/media/kata/disk",
                 "/var/run/media/kata/disk", "/opt/data", "/srv/share", "~/Projects", "~/tmp", "~/etc/x", "~/proc"]


@pytest.mark.parametrize("path", list(SYSTEM_REFUSED) + SYSTEM_ABOVE + ["/run", "/var/run"] + SYSTEM_SHARED)
def test_a_system_place_is_never_granted_nor_what_is_inside_or_above_it(a_users_home, path):
    why = sb.protected_folder(path)
    if path in SYSTEM_SHARED:
        assert why == "", (path, why)
    elif path in SYSTEM_REFUSED:
        assert why == f"the system's own {SYSTEM_REFUSED[path]}", (path, why)
        assert sb.system_folder(path) == why
    else:
        assert why.startswith("a folder above "), (path, why)
    # ...and the same answer for the user's picker as for a review: one check, whoever asks
    gs = sb.apply_overrides(sb.resolve_template("standard"), {"folders": {"+" + path: "ro"}})
    kept, refused = sb.strip_protected(gs)
    named = sb.folder_path(path)                 # as every grant is named: `//proc` and `/proc/` are /proc (CR1.5-16)
    assert (named in kept["folders"]) is (path in SYSTEM_SHARED) and [p for p, _ in refused] == ([] if path in SYSTEM_SHARED else [named])


def test_a_review_cannot_grant_a_system_place_and_the_user_cannot_pick_one(a_users_home):
    # the finding's own case, as it was run: a review's line through config_from_review and choose
    asked = ["/proc", "/run/docker.sock", "/tmp", "/dev/shm", "/etc", "/var/tmp"]
    cfg = sb.config_from_review({"sandbox": "standard", "sandboxFolders": ", ".join(p + ":ro" for p in asked) + ", /media/usb:ro, ~/Notes"})
    source, gs, _ = sb.choose(None, None, [cfg], {"template": "strict"})
    assert source == "reviews" and set(asked) <= set(gs["folders"])           # a review's line is kept as written...
    chips = sb.summary(gs)
    text = sb.build_launcher("app", "App", "/home/kata/bin/apps/app/1", "bin/app", gs, apps_root="/home/kata/bin/apps")
    for p in asked:
        place = sb.SYSTEM_PLACES[[p == s or p.startswith(s + "/") for s in sb.SYSTEM_PLACES].index(True)]
        assert f"{p} · refused: the system's own {place}" in chips, chips    # ...shown as refused...
        assert f"# Refused folder grant {p}: the system's own {place} (R17.3.1)." in text
        assert f"bind-try {p} {p}" not in text                                # ...and never bound
    assert "/media/usb · read-only" in chips and "--ro-bind-try /media/usb /media/usb" in text
    assert "~/Notes" in chips and "--bind-try /home/kata/Notes /home/kata/Notes" in text
    # the sandbox's own /proc, /dev and /tmp are the only ones in the launcher
    assert "--proc /proc --dev /dev --dev-bind-try /dev/dri /dev/dri --tmpfs /tmp" in text
    # the user's own pick, as the Sandbox dialog saves it (Backend.setSandbox): dropped, with the same reason
    kept, refused = sb.strip_protected({**sb.to_json(sb.resolve_template("standard")), "folders": {p: "rw" for p in asked + ["~/Notes"]}})
    assert set(kept["folders"]) == {"~/Notes"} and [p for p, _ in refused] == sorted(asked)


# CR1.5-16 (#391): a folder was kept and shown as it was written, and judged and mounted by where it
# leads, so a line could write a grant that reads as one place and is another:
# `~/Documents/../.config/google-chrome/Default` showed, in the chip, the Audit and the badge, as a
# folder of Documents. How it slipped past: every test wrote a folder the one plain way, and the
# never-shared checks, which the hostile ways of writing were aimed at, resolve the path. Now a
# grant set's folders are named one way wherever a set is read (sb.folder_path, in sb.normalize),
# and a `..` is refused whoever asks. Each way of writing a folder → the name it is kept, shown
# and mounted under; one refused for how it is written stays as written, and is no grant.
WRITTEN = {
    "~/Notes": "~/Notes", "~/Notes/": "~/Notes", "~//Notes": "~/Notes", "~/./Notes/.": "~/Notes", "~/Notes//sub/./x/": "~/Notes/sub/x",
    "/home/kata/Notes": "~/Notes", "/home/kata//Notes/": "~/Notes", "//home/kata/Notes": "~/Notes", "/home//kata/./Notes": "~/Notes",
    "/media/usb": "/media/usb", "/media/usb/": "/media/usb", "//media//usb/./music": "/media/usb/music", "/home/kata2/Notes": "/home/kata2/Notes",
    "~/My Notes/": "~/My Notes", "~/...": "~/...", "~/a..b/..c": "~/a..b/..c", "~/.hidden/": "~/.hidden",
}
DOTTED = ["~/Documents/../.config/google-chrome/Default", "~/Documents/../.cache", "~/Notes/sub/..", "/media/usb/../other",
          "/home/kata/Documents/../Notes", "~/Notes/../Notes", "~/../kata/Notes", "~/Notes/..x/../y"]


@pytest.mark.parametrize("written", list(WRITTEN) + DOTTED)
def test_a_folder_is_kept_shown_and_mounted_under_one_name_and_never_with_a_dotdot(a_users_home, written):
    named = WRITTEN.get(written, written)
    assert sb.folder_path(written) == named and sb.folder_path(named) == named
    for mode, said in (("rw", ""), ("ro", " · read-only")):
        # a review's line or the dialog's pick, and a set saved before, as it is read
        gs = sb.apply_overrides(sb.resolve_template("standard"), {"folders": {"+" + written: mode}})
        saved = sb.normalize({**sb.to_json(sb.resolve_template("standard")), "folders": {written: mode}})
        assert gs["folders"] == saved["folders"] == {named: mode} and sb.to_json(saved)["folders"] == {named: mode}
        chips = sb.summary(gs)
        text = sb.build_launcher("app", "App", "/home/kata/bin/apps/app/1", "bin/app", gs, apps_root="/home/kata/bin/apps")
        added, _ = sb.changes(sb.resolve_template("standard"), gs)             # the Audit's phrase and the review badge's
        assert added == [named + (" (read-write)" if mode == "rw" else " (read-only)")]
        mounted = os.path.expanduser(named)
        binds = [line for line in text.splitlines() if "bind-try " in line and "/home/kata/Notes" in line or "/media/usb" in line and "bind-try " in line]
        if written in DOTTED:
            assert sb.protected_folder(written) == sb.DOTDOT == "not a full path (it has a .. in it: name the folder it leads to)"
            noted = f"# Refused folder grant {written}: {sb.DOTDOT} (R17.3.1).\n"
            assert f"{written} · refused: {sb.DOTDOT}" in chips and text.count(noted) == 1
            assert not binds and "g1=" not in text and os.path.expanduser(written) not in text.replace(noted, "")
            assert sb.strip_protected(gs)[1] == [(written, sb.DOTDOT)]         # the user's own pick too (Backend.setSandbox)
        else:
            assert named + said in chips and not [c for c in chips if "refused" in c], chips
            flag = "--bind-try" if mode == "rw" else "--ro-bind-try"
            assert f'[ {shlex.quote(mounted)} = "$g1" ] && set -- {flag} {shlex.quote(mounted)} {shlex.quote(mounted)} "$@"\n' in text
            assert f"g1={shlex.quote(mounted)}; leads" in text
            assert os.path.expanduser(written) == mounted or shlex.quote(os.path.expanduser(written)) + " " not in text       # by no other name


def test_a_review_cannot_write_a_folder_so_that_it_reads_as_another_and_two_ways_of_writing_one_are_one_grant(a_users_home):
    # the finding's own case, as it was run: a review's line through config_from_review and choose
    line = "~/Documents/../.config/google-chrome/Default, ~/Documents/../.cache:ro, ~/Media//:ro, /home/kata/Notes/"
    source, gs, _ = sb.choose(None, None, [sb.config_from_review({"sandbox": "standard", "sandboxFolders": line})], {"template": "strict"})
    chips = sb.summary(gs)
    assert source == "reviews" and gs["folders"] == {"~/Documents/../.config/google-chrome/Default": "rw", "~/Documents/../.cache": "ro", "~/Media": "ro", "~/Notes": "rw"}
    assert [c for c in chips if "Documents" in c] == [f"~/Documents/../.cache · refused: {sb.DOTDOT}", f"~/Documents/../.config/google-chrome/Default · refused: {sb.DOTDOT}"]
    assert "~/Media · read-only" in chips and "~/Notes" in chips
    kept, refused = sb.strip_protected(gs)
    assert set(kept["folders"]) == {"~/Media", "~/Notes"} and [p for p, _ in refused] == ["~/Documents/../.cache", "~/Documents/../.config/google-chrome/Default"]
    assert sb.changes(sb.resolve_template("standard"), kept)[0] == ["~/Media (read-only)", "~/Notes (read-write)"]
    # what is never shared is still said first, by where the path leads: the reason a reader needs
    assert sb.protected_folder("~/Documents/../.ssh") == "SSH keys" and sb.protected_folder("/mnt/../proc") == "the system's own /proc"
    assert sb.protected_folder("~/Documents/..") == "your whole home folder"
    # one folder written two ways is one grant: the stricter mode of the two, removed by either name, and kept where two reviews both ask
    two = sb.apply_overrides(sb.resolve_template("standard"), {"folders": {"+~/Notes/": "rw", "+/home/kata/Notes": "ro", "+/media//usb": "rw"}})
    assert two["folders"] == {"~/Notes": "ro", "/media/usb": "rw"}
    assert sb.apply_overrides(sb.resolve_template("standard"), {"folders": {"+/home/kata/Notes": "ro", "+~/Notes/": "rw"}})["folders"] == {"~/Notes": "ro"}
    assert sb.apply_overrides(two, {"folders": {"~/Notes/": "rw"}})["folders"]["~/Notes"] == "rw"           # a later change of the mode is one
    assert sb.normalize({**sb.to_json(two), "folders": {"~/Notes/": "rw", "/home/kata//Notes": "ro", "~/Notes": "rw"}})["folders"] == {"~/Notes": "ro"}
    assert sb.apply_overrides(two, {"folders": {"-/home/kata/Notes/": None, "/media/usb/.": None}})["folders"] == {}
    _, both = sb.resolve(reviews=[{"template": "standard", "overrides": {"folders": {"+~/Notes/": "rw"}}},
                                  {"template": "standard", "overrides": {"folders": {"+/home/kata/Notes": "ro", "+~/Other": "rw"}}}])
    assert both["folders"] == {"~/Notes": "ro"}
    assert sb.as_review("standard", two)[0]["sandboxFolders"] == "+/media/usb, +~/Notes:ro"
    # the folder the launcher is run in, and a path refused for how it is written, are named as they are
    assert [sb.folder_path(p) for p in ("$cwd", "home", "./x", "Documents/", "~no-such-user-x/y/")] == ["$cwd", "home", "./x", "Documents/", "~no-such-user-x/y/"]
    assert sb.folder_path("~") == sb.folder_path("/home/kata/") == sb.folder_path("~/.") == "~" and sb.folder_path("/") == sb.folder_path("//") == "/"


def test_a_review_whose_folder_has_a_control_character_breaks_nothing_and_is_refused(a_users_home):
    # CR1.5-26 (#401): os.path.realpath() raises ValueError on a NUL, and no folder check caught it, so
    # one line of a review the user trusts, `Sandbox folders: +~/a<NUL>b`, made the install card's chips
    # and strip_secrets (asked for every fresh install's reviews) raise, and no launcher could be
    # written: every app the review covers, until the review changed. "Any other path is refused the
    # same way" (R17.3.1); this one broke the check instead. The finding's own road, a review's
    # section to the launcher: the folder is refused like any other that is no full path, with a mark
    # where the character was, and the folders beside it on the line stand. How it slipped past: the
    # hostile corpus (tests/test_sandbox_adversarial.py) cut its one NUL off before it was used.
    section = ("## Demo::Settings\n\n- Trust: 4\n- Sandbox (linux): standard\n"
               "- Sandbox folders (linux): +~/a\x00b, ~/Notes, ~/Media/\x1b[2J:ro, /media/usb\x00/../../proc, ~/.aws\x07\n")
    parsed, warns = trustfile.parse_section("Demo", section)
    cfg = sb.config_from_review(trustfile.resolve_settings(parsed["opts"], "linux"))
    source, gs, _ = sb.choose(None, None, [cfg], {"template": "strict"})
    why = "not a full path (it has a control character in it, shown as \ufffd)"
    bad = ["/media/usb\ufffd/../../proc", "~/.aws\ufffd", "~/Media/\ufffd[2J", "~/a\ufffdb"]
    assert source == "reviews" and gs["folders"] == {**dict.fromkeys(bad, "rw"), "~/Media/\ufffd[2J": "ro", "~/Notes": "rw"}
    kept, refused = sb.strip_secrets(gs)                      # a review's set, as every fresh install asks (Backend._resolved_sandbox)
    assert refused == [] and kept["folders"] == gs["folders"]
    chips = sb.summary(gs)
    assert [c for c in chips if "refused" in c] == [f"{p} · refused: {why}" for p in bad] and "~/Notes" in chips
    assert sb.strip_protected(gs) == ({**kept, "folders": {"~/Notes": "rw"}}, [(p, why) for p in bad])
    text = sb.build_launcher("app", "App", "/home/kata/bin/apps/app/1", "bin/app", gs, apps_root="/home/kata/bin/apps")
    assert all(f"# Refused folder grant {p}: {why} (R17.3.1).\n" in text for p in bad) and "\x00" not in text and "\x1b" not in text and "\x07" not in text
    assert text.count("bind-try /home/kata/") == 1 and "--bind-try /home/kata/Notes /home/kata/Notes" in text and "/media/usb" not in text.replace("# Refused folder grant /media/usb", "")
    assert sb.as_review("standard", gs) == ({"sandbox": "standard", "sandboxFolders": "+~/Notes"}, [(p, why) for p in bad])
    assert json.loads(json.dumps(sb.to_json(gs)))["folders"] == gs["folders"]              # as the install record keeps it
    # each check, asked of the path as it came and as it is kept: an answer, never an exception
    for p in ("~/a\x00b", "\x00", "/\x00", "~/new\nline", "~/tab\tbed", "/media/usb\x7f", "~/c1\x9b", "~/a\ufffdb"):
        assert sb.protected_folder(p) == sb.protected_folder(sb.folder_path(p)) == why == sb.CONTROL, p
        assert sb.secret_folder(p) == sb.system_folder(p) == "" and sb.folder_path(p) == sb._shown(p) and "\ufffd" in sb.folder_path(p), p
    # ...and the user's own pick of a folder whose name has one (the Sandbox dialog, Backend.setSandbox): not shared, and said
    picked, refused = sb.strip_protected({**sb.to_json(sb.resolve_template("standard")), "folders": {"/home/kata/odd\nname": "rw", "~/Notes": "ro"}})
    assert picked["folders"] == {"~/Notes": "ro"} and refused == [("/home/kata/odd\ufffdname", why)]
    # what is no control character is a folder's own: a space, an accent, a byte no encoding reads
    for p in ("~/My Notes", "~/unicode-ünïcødé", "~/emoji 👩‍💻", os.fsdecode(b"/media/usb/a\xffb")):
        assert sb.protected_folder(p) == "" and sb.folder_path(p) == p, p


def test_a_folder_of_the_home_is_the_homes_wherever_the_home_is(tmp_path, monkeypatch):
    # A home inside a system place (every test's is under /tmp; a throwaway HOME=$(mktemp -d)) is
    # still a home: its folders are judged as the home's, and nothing else of the place is shared,
    # by the path as written or by where it leads. Shown with this test's own folder as the place.
    place = tmp_path / "place"
    home, other = place / "home", place / "other"
    (home / "Projects").mkdir(parents=True)
    other.mkdir()
    (home / "out").symlink_to(other)                     # written in the home, leads into the place
    (place / "in").symlink_to(home / "Projects")         # written in the place, leads into the home
    places = sb.SYSTEM_PLACES
    monkeypatch.setattr(sb, "SYSTEM_PLACES", (str(place),))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "run"))
    for v in ("XDG_DATA_HOME", "APPKATA_APPS", "APPKATA_DATA", "DBUS_SESSION_BUS_ADDRESS"):
        monkeypatch.delenv(v, raising=False)
    assert sb.protected_folder("~/Projects") == "" and sb.protected_folder(str(home / "Projects" / "x")) == ""
    for path in (str(other), str(other / "x"), "~/out", "~/out/x", str(place / "in")):
        assert sb.protected_folder(path) == f"the system's own {place}", path
    assert sb.protected_folder(str(place)) == "everything, your home folder included"
    # a home that is `/` (a bare container's) makes nothing a folder of the home
    monkeypatch.setattr(sb, "SYSTEM_PLACES", places)
    monkeypatch.setenv("HOME", "/")
    monkeypatch.setenv("XDG_RUNTIME_DIR", "/run/user/1000")
    for path, place in (("/proc", "/proc"), ("/tmp/x", "/tmp"), ("/dev/shm", "/dev")):
        assert sb.protected_folder(path) == f"the system's own {place}", path


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


# ---------------------------------------------------------------- AppArmor setup (R17.10)

def test_profile_names_the_bwrap_actually_installed(monkeypatch, tmp_path):
    # Regression: the profile hard-coded /usr/bin/bwrap, so with bwrap elsewhere it attached to nothing.
    # It names the bwrap the launchers run, the system's folders' (R17.4), through its links (a
    # stand-in system folder here; tests/test_sandbox_adversarial.py has the user's bwrap beside it).
    real = tmp_path / "opt" / "bwrap"
    real.parent.mkdir()
    real.write_text("#!/bin/sh\n")
    real.chmod(0o755)
    link = tmp_path / "bin" / "bwrap"
    link.parent.mkdir()
    link.symlink_to(real)
    monkeypatch.setattr(sb, "HOST_PATH", str(tmp_path / "bin"))
    monkeypatch.setenv("PATH", str(tmp_path / "bin"))
    assert f"profile appkata-sandbox {real} flags=(unconfined)" in sb.profile_text()
    assert "profile appkata-sandbox /usr/bin/bwrap flags=(unconfined)" in sb.PROFILE_TEXT      # the documented shape


@pytest.mark.parametrize("works", [True, False])
def test_setup_counts_only_when_bwrap_then_works(monkeypatch, works):
    # Regression: install_profile returned True whatever the probe said afterwards, and the UI then
    # told the user sandbox support was set up while every app kept running Off.
    monkeypatch.setattr(sb, "OS", "linux")
    monkeypatch.setattr(sb.shutil, "which", lambda name, path=None: f"/usr/bin/{name}")
    ran = []
    monkeypatch.setattr(sb.subprocess, "run", lambda cmd, **kw: (ran.append(cmd), subprocess.CompletedProcess(cmd, 0, "", ""))[1])
    monkeypatch.setattr(sb, "userns_works", lambda refresh=False: works)
    if works:
        assert sb.install_profile() is True
    else:
        with pytest.raises(sb.SandboxError, match="still can't create a user namespace"):
            sb.install_profile()
    assert ran and ran[0][:3] == ["/usr/bin/pkexec", "/bin/sh", "-c"] and "apparmor_parser -r" in ran[0][3]


# ---------------------------------------------------------------- Ubuntu 25.04+: the system's own bwrap profile (R17.10.2)

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
    r = subprocess.run(sb.setup_command("/usr/bin/bwrap"), env={"PATH": str(stub), "PKEXEC_UID": "1000"},
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


_BWRAP_FOLDERS = {"a line break": "real\nAAEOF\ntouch {ran}\n#", "a space": "my tools", "a brace": "x{a,b}",
                  "a quote and a dollar": "it's $(touch {ran})", "plain": "tools-1.0_x+y"}


@pytest.mark.parametrize("folder", list(_BWRAP_FOLDERS))
def test_the_apparmor_setup_has_no_path_in_its_script_and_profiles_only_a_path_it_can_name(tmp_path, monkeypatch, folder):
    # #689's review, P2-B2: the one-time setup wrote bwrap's real path into the script pkexec runs as
    # root, inside a heredoc, so a path holding a line break and the heredoc's end ran what followed
    # it as root; a space or a brace made a profile apparmor_parser refused, with its own message
    # alone. And pkexec was run by name, on AppKata's own PATH, where ~/.local/bin comes first. The
    # script's text is the same whatever the paths: the profile's file, its text and the bwrap the
    # probe runs are its arguments. A bwrap whose path an AppArmor profile can't name as it is (only
    # letters, digits and . _ + - /) is refused before any prompt, saying why. pkexec is the
    # system's. Here the setup runs for real, as the user, with stand-ins for the root-only tools.
    d = _apparmor_dir(tmp_path, monkeypatch, {})
    monkeypatch.setattr(sb, "OS", "linux")
    ran = tmp_path / "ROOT-RAN"
    bwrap = tmp_path / _BWRAP_FOLDERS[folder].replace("{ran}", str(ran)) / "bwrap"
    bwrap.parent.mkdir(parents=True)
    bwrap.write_text("#!/bin/sh\nexit 0\n")
    bwrap.chmod(0o755)
    monkeypatch.setattr(sb, "bwrap_path", lambda *a, **k: str(bwrap))
    stub, system, theirs, log = tmp_path / "stub", tmp_path / "system", tmp_path / "home" / ".local" / "bin", tmp_path / "log"
    for folder_ in (stub, system, theirs):
        folder_.mkdir(parents=True)
    for real in ("cat", "rm", "cut", "touch"):                                 # the script's PATH is the stand-ins alone
        (stub / real).symlink_to(subprocess.run(["sh", "-c", f"command -v {real}"], capture_output=True, text=True).stdout.strip())
    for where, name, body in ((stub, "apparmor_parser", f'echo "apparmor_parser $*" >> {log}\n'), (stub, "getent", 'echo "kata:x:1000:1001::/h:/bin/sh"\n'),
                              (stub, "setpriv", "exit 0\n"), (system, "pkexec", "exit 0\n"), (theirs, "pkexec", "exit 0\n")):
        (where / name).write_text("#!/bin/sh\n" + body)
        (where / name).chmod(0o755)
    monkeypatch.setattr(sb, "HOST_PATH", str(system))
    monkeypatch.setenv("PATH", f"{theirs}:{system}")                          # a login's: the user's own folder first
    prompts, real_run = [], subprocess.run

    def run(cmd, **kw):                         # pkexec's prompt, approved: what it runs, as the user here
        prompts.append(cmd)
        return real_run(cmd[1:], env={"PATH": str(stub), "PKEXEC_UID": "1000"}, capture_output=True, text=True, timeout=30)
    monkeypatch.setattr(sb.subprocess, "run", run)
    monkeypatch.setattr(sb, "userns_works", lambda refresh=False: True)
    monkeypatch.setattr(sb, "nested_userns_works", lambda refresh=False: True)
    if folder != "plain":
        with pytest.raises(sb.SandboxError, match="an AppArmor profile can't name"):
            sb.install_profile()
        assert prompts == [] and not ran.exists() and not (d / "appkata-sandbox").exists()     # no prompt, nothing run or written
        return
    assert sb.install_profile() is True
    (pkexec, shell, c, script, *args), = prompts
    assert (pkexec, shell, c) == (str(system / "pkexec"), "/bin/sh", "-c")   # the system's pkexec, not the one first on PATH
    assert str(bwrap) not in script and str(d) not in script                  # no path is part of the script's text
    assert str(bwrap) in args and (d / "appkata-sandbox").read_text() == sb.profile_text(str(bwrap))
    assert log.read_text().splitlines() == [f"apparmor_parser -r {d / 'appkata-sandbox'}"]


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
    assert 'Exec=/bin/sh "/x/run" --appkata-menu %U\n' in open(p).read()
    p = install._desktop_entry("app", "App", "/x/bin/app", "", "An app")
    assert 'Exec=/bin/sh "/x/bin/app" %U\n' in open(p).read()


def test_launcher_hands_over_file_arguments_only_for_standard_apps(fake_home):
    # Round two, R7 (17.6.2): a Standard launcher runs the forwarding helper over its arguments with
    # the granted folders (and a CLI tool's directory) as "already visible"; a Strict app has no bus,
    # so no document portal, so no block. The helper is written beside the seccomp filter.
    gs = sb.apply_overrides(sb.resolve_template("standard"), {"folders": {"+~/Projects": "rw"}})
    lp = sb.write_launcher("app", "App", str(fake_home / "bin/apps"), str(fake_home / "bin/apps/app/1"), "bin/app", gs)
    text = open(lp).read()
    helper = sb.forward_path()
    assert os.path.exists(helper) and "org.freedesktop.portal.Documents" in open(helper).read()
    # ...each only where the launcher shows it, which it doesn't where the session bus's address names
    # a file it can't read (PR #694's review, P3-B4), nor where the folder no longer leads where it
    # led when the launcher was written ($g1 is empty then: CR1.5-40)
    # ...then the never-shared folders, which win over an argument (CR1.5-38): the session bus's
    # socket files as the launcher read them, and R17.3.1's list as it is written
    never = " ".join(shlex.quote(r) for r in dict.fromkeys([sb.sandboxes_root()] + [r for r, _ in sb._protected_roots(str(fake_home / "bin/apps"))]))
    assert str(fake_home / ".ssh") in never.split() and str(fake_home / "bin/apps") in never.split()
    assert f'python3 {helper} "$id" "$rt" "" ${{folders:+${{g1:+{fake_home}/Projects}}}} -- "${{bussocks:-}}" {never} -- "$@"' in text
    assert text.index('folders=1; [ "${busok:-1}" = 1 ] || folders=') < text.index("forward-files.py")
    assert text.index("forward-files.py") < text.index('set -- -- "$appdir/$exe" "$@"')     # before the words are fixed
    assert text.index("--appkata-menu") < text.index("forward-files.py")                  # after the menu word is shifted off
    cli = sb.build_launcher("t", "T", "/x/1", "bin/t", sb.resolve_template("cli-tool"), forward=helper)
    # the tool's directory counts as visible only when the $cwd rule shares it (round three, R3-3),
    # so that rule is decided first and the forward call takes its answer
    assert f'python3 {helper} "$id" "$rt" "${{cwdvis:-}}" ${{cwdvis:+"$cwdvis"}} -- "${{bussocks:-}}" ' in cli
    assert cli.index("share=1") < cli.index("forward-files.py") < cli.index('set -- --bind "$here" "$here"')
    assert _valid_sh(cli)
    assert "forward-files.py" not in sb.build_launcher("v", "V", "/x/1", "bin/v", sb.resolve_template("strict"), forward=helper)


def _forward(tmp_path, cwd, incwd, visible, args):
    return _handed(tmp_path, cwd, args, visible, incwd)[0]


# A stand-in for python3-gi, first on the helper's path: it answers the document portal's calls and
# writes each down ($PORTAL_LOG), with the file every descriptor it was passed leads to. What the
# portal holds for each app is the file $PORTAL_DOCS names ({identity: {document id: host path}}):
# List answers from it and is a question, so it is not written down; RevokePermissions takes the
# document out of it, unless $PORTAL_KEEPS says this portal revokes nothing. $PORTAL_GONE is the
# D-Bus error every plain call gets, as from a session where no document portal runs.
_STAND_IN_GI = """import json, os


class _Answer:
    def __init__(self, value):
        self.value = value

    def unpack(self):
        return self.value


class _FDs:
    def __init__(self):
        self.fds = []

    def append(self, fd):
        self.fds.append(fd)
        return len(self.fds) - 1


def _held():
    try:
        with open(os.environ["PORTAL_DOCS"]) as f:
            return json.load(f)
    except (KeyError, OSError):
        return {}


class _Bus:
    def _note(self, method, args, fds=()):
        with open(os.environ["PORTAL_LOG"], "a") as f:
            f.write(json.dumps([method, list(args), [os.readlink(f"/proc/self/fd/{fd}") for fd in fds]]) + "\\n")

    def call_with_unix_fd_list_sync(self, name, path, iface, method, args, answer, flags, timeout, fds, cancel):
        self._note(method, args.value, fds.fds)
        return _Answer(("DOC",) if method == "Add" else (["DOC"], {})), None

    def call_sync(self, name, path, iface, method, args, answer, flags, timeout, cancel):
        if os.environ.get("PORTAL_GONE"):
            raise GLib.Error(os.environ["PORTAL_GONE"])
        if method == "List":
            return _Answer(({doc: list(os.fsencode(host)) + [0] for doc, host in _held().get(args.value[0], {}).items()},))
        self._note(method, args.value)
        if method == "RevokePermissions" and not os.environ.get("PORTAL_KEEPS"):
            held = _held()
            held.get(args.value[1], {}).pop(args.value[0], None)
            with open(os.environ["PORTAL_DOCS"], "w") as f:
                json.dump(held, f)


class Gio:
    class UnixFDList:
        new = staticmethod(_FDs)

    class BusType:
        SESSION = 1

    class DBusCallFlags:
        NONE = 0
        NO_AUTO_START = 2

    class DBusError:
        is_remote_error = staticmethod(lambda error: True)
        get_remote_error = staticmethod(lambda error: error.args[0])

    bus_get_sync = staticmethod(lambda kind, cancel: _Bus())


class GLib:
    class Error(Exception):
        pass

    class Variant:
        def __init__(self, signature, value):
            self.value = value

    VariantType = staticmethod(lambda signature: signature)
"""


def _handed(tmp_path, cwd, args, visible=(), incwd="", never=(), sockets=(), home=None, helper=None, held=None, gone=""):
    """The file-argument helper's own text run from `cwd` over `args`, against a stand-in document
    portal: the arguments it answers, the lines it has the launcher say, and the portal's calls,
    each [method, arguments, what the descriptors passed lead to]. `visible`: the folders the app
    is shown; `incwd`: a command-line tool's shared directory; `never` and `sockets`: the
    never-shared folders and the session bus's socket files the launcher gives it; `home`: the
    user's home folder, the test's own unless given; `helper`: the helper as AppKata wrote it
    (sandbox.write_forward_helper), a copy of its text in `tmp_path` unless given; `held`: what
    the portal holds for the app from before, {document id: host path}, each also at its place in
    the portal's own view ($XDG_RUNTIME_DIR/doc/<id>/<name>); `gone`: the D-Bus error the portal's
    plain calls get, the question what the app holds among them."""
    gi, log, docs = tmp_path / "stand-in" / "gi", tmp_path / "portal.log", tmp_path / "portal-held.json"
    docs.write_text(json.dumps({"io.appkata.t": held or {}}))
    for doc, host in (held or {}).items():
        (tmp_path / "run" / "doc" / doc).mkdir(parents=True, exist_ok=True)
        if not os.path.lexists(tmp_path / "run" / "doc" / doc / os.path.basename(host)):
            (tmp_path / "run" / "doc" / doc / os.path.basename(host)).symlink_to(host)
    if helper is None:
        helper = tmp_path / "forward-files.py"
        helper.write_text(sb.FORWARD_HELPER)
    gi.mkdir(parents=True, exist_ok=True)
    (gi / "__init__.py").write_text("")
    (gi / "repository.py").write_text(_STAND_IN_GI)
    if log.exists():
        log.unlink()
    r = subprocess.run([sys.executable, str(helper), "io.appkata.t", str(tmp_path / "run"), incwd, *map(str, visible), "--",
                        "".join(f"{s}\n" for s in sockets), *map(str, never), "--", *args], cwd=str(cwd), capture_output=True, text=True, timeout=30,
                       env={**os.environ, "PYTHONPATH": str(gi.parent), "PORTAL_LOG": str(log), "PORTAL_DOCS": str(docs), "PORTAL_GONE": gone,
                            "PORTAL_KEEPS": "", **({"HOME": str(home)} if home else {})})
    assert r.returncode == 0, r.stderr
    lines = r.stdout.split("\n")
    assert lines.pop() == "" and all(l[:1] in ("=", "!") for l in lines), r.stdout
    calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
    return forwarded_words("".join(l + "\n" for l in lines if l[0] == "=")), [l[1:] for l in lines if l[0] == "!"], calls


def _through_a_link(arg, link, real) -> str:
    """What the helper has the launcher say of an argument it didn't follow through `link`, which
    leads to `real` (R17.6.2)."""
    return f"runs sandboxed and isn't handed {arg}: {link} is a link, and a file argument is never followed through one (give {real} instead)."


def _the_helper_where(tmp_path, owners: dict, locked=()) -> str:
    """The file-argument helper as it runs on a machine where each link of `owners` is that user's
    ({path: uid}) and each folder of `locked` is not the user's to change: no test can make a
    link root's, or a folder of its own someone else's, so the two answers the helper asks the
    system for (a link's owner, whether its folder can be written) are given here, and the
    helper's own text does the rest."""
    helper, there = tmp_path / "forward-files.py", tmp_path / "forward-files-there.py"
    helper.write_text(sb.FORWARD_HELPER)
    there.write_text(f"""import os, runpy
OWNERS, LOCKED = {dict((str(k), v) for k, v in owners.items())!r}, {sorted(map(str, locked))!r}
lstat, access = os.lstat, os.access


def _lstat(path, *a, **k):
    st = lstat(path, *a, **k)
    uid = OWNERS.get(os.fspath(path))
    return st if uid is None else os.stat_result(tuple(st)[:4] + (uid,) + tuple(st)[5:])


def _access(path, mode, *a, **k):
    return False if mode == os.W_OK and os.fspath(path) in LOCKED else access(path, mode, *a, **k)


os.lstat, os.access = _lstat, _access
runpy.run_path({str(helper)!r}, run_name="__main__")
""")
    return there


def forwarded_words(answer: str) -> list[str]:
    """The file-argument helper's answer, read by its own rules: an argument a line, "=" first, a
    backslash doubled and a line break as a backslash and n (CR1.5-31: it is data, no longer shell)."""
    lines = answer.split("\n")
    assert lines.pop() == "" and all(l.startswith("=") for l in lines), answer
    return [re.sub(r"\\(.)", lambda m: "\n" if m[1] == "n" else m[1], l[1:]) for l in lines]


def test_file_arguments_in_a_granted_folder_become_the_path_the_app_sees(tmp_path):
    # Review 2, F6: a relative path or `.` from a granted folder reached the app's private home (its
    # working directory inside); R3-16: an option's value was never looked at. Neither needs the
    # document portal: the app finds them under the grant's mount. Review 3, R3-17 had a link outside
    # the granted folders to a file inside one become the file's path; since CR1.5-55 no link is
    # followed for an app, and such an argument passes as typed, with the path to give instead.
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
    linked = [str(desk / "link.txt"), str(home / "docs-link" / "in.txt"), "--file=" + str(desk / "link.txt"), "-o" + str(desk / "link.txt")]
    words, said, calls = _handed(tmp_path, home, linked, visible=[docs])
    assert words == linked and calls == [], (words, calls)
    assert said == [_through_a_link(desk / "link.txt", desk / "link.txt", want), _through_a_link(home / "docs-link" / "in.txt", home / "docs-link", want)], said
    assert _forward(tmp_path, home, "", [docs], ["Docs/in.txt", "--file=Docs/in.txt", "-o" + want]) == [want, "--file=" + want, "-o" + want]
    # unchanged: already the app's path (as a path, a URI, with a trailing slash), not a file, not there
    same = [want, "file://" + want, str(docs / "sub") + "/", "https://example.org/x", str(home / "nothing.txt"), "-v", "--level=3"]
    assert _forward(tmp_path, home, "", [docs], same) == same


def test_a_link_in_a_granted_folder_is_never_followed_out_of_it_to_hand_a_file_over(tmp_path):
    # CR1.5-4: an app with ~/Docs read-write put a link to a file of the user's where report.md was;
    # the user opened report.md, and the helper, which judged an argument by where it leads alone,
    # handed the app the link's target through the document portal, read-write (a link to a folder,
    # the folder whole). A link in a folder the app is shown is the app's to make: the argument is
    # passed as its own path there, where the link dangles, and the portal is asked nothing. How it
    # slipped past: the tests had the other direction alone (R3-17, a link outside to a file inside).
    # Since CR1.5-55 no link is followed for an app, wherever it lies and wherever it leads: what
    # this test holds is the same, a planted link never hands over what it leads to, and an argument
    # that is not the app's own path as typed now passes as typed too, with a line, where it had
    # become its path in the granted folder.
    home = tmp_path / "home"
    docs, media, private, desk = home / "Docs", home / "Media", home / "private", home / "Desktop"
    for d in (docs / "sub", media, private / "deep", desk):
        d.mkdir(parents=True)
    for f in (private / "taxes.txt", private / "deep" / "file", media / "song.ogg", docs / "in.txt"):
        f.write_text("x")
    (docs / "report.md").symlink_to(private / "taxes.txt")                 # where the app's own file was
    (docs / "rel.md").symlink_to("../private/taxes.txt")
    (docs / "Photos").symlink_to(private)                                  # a folder, whole
    (docs / "sub" / "up").symlink_to("../../private")
    (docs / "chain").symlink_to(docs / "report.md")                        # a link to a link
    (docs / "song").symlink_to(media / "song.ogg")                         # into another granted folder
    (docs / "self").symlink_to("in.txt")
    (desk / "shortcut").symlink_to(docs / "report.md")                     # the user's own link, to the planted one
    (desk / "good").symlink_to(docs / "in.txt")
    (home / "docs-link").symlink_to(docs)
    as_typed = [str(docs / "report.md"), "file://" + str(docs / "report.md"), str(docs / "rel.md"), str(docs / "Photos"), str(docs / "Photos") + "/",
                str(docs / "Photos" / "taxes.txt"), str(docs / "Photos" / "deep" / "file"), str(docs / "sub" / "up" / "taxes.txt"),
                str(docs / "chain"), "--file=" + str(docs / "report.md"), "-o" + str(docs / "Photos" / "taxes.txt"),
                str(docs / "Photos" / ".." / "private" / "taxes.txt")]
    words, said, calls = _handed(tmp_path, home, as_typed, visible=[docs, media], home=home)
    assert words == as_typed and calls == [], (words, calls, said)
    # each is the app's own path as typed, and said nothing of, but the one with a ".." in it, which is read by no text
    taxes = private / "taxes.txt"
    assert said == [_through_a_link(as_typed[-1], docs / "Photos", taxes)], said
    # named another way, it is not followed either, and is said
    other = ["Docs/report.md", str(home / "docs-link" / "Photos" / "taxes.txt"), str(desk / "shortcut")]
    words, said, calls = _handed(tmp_path, home, other, visible=[docs, media], home=home)
    assert words == other and calls == [], (words, calls)
    assert said == [_through_a_link(other[0], docs / "report.md", taxes), _through_a_link(other[1], home / "docs-link", taxes),
                    _through_a_link(other[2], desk / "shortcut", taxes)], said
    # ...in a command-line tool's shared folder too, where a relative path stays as typed
    typed = ["report.md", "./rel.md", "Photos/taxes.txt", "Photos"]
    words, said, calls = _handed(tmp_path, docs, typed + [str(docs / "report.md")], visible=[docs], incwd=str(docs), home=home)
    assert words == typed + [str(docs / "report.md")] and calls == [] and said == [], (words, calls, said)
    # ...and where the folder is granted through the user's own link (~/Documents kept on another
    # disk): by the grant's own path a file opens as before, links and all, and nothing is said; by
    # the path the link leads to, a file becomes the grant's, and the planted link is not followed
    (tmp_path / "homes").symlink_to(tmp_path)
    written = tmp_path / "homes" / "home" / "Docs"
    through = [str(written / "in.txt"), str(written / "report.md"), str(written / "Photos"), "file://" + str(written / "sub") + "/"]
    words, said, calls = _handed(tmp_path, home, through + [str(docs / "in.txt"), str(docs / "report.md")], visible=[written], home=home)
    assert words == through + [str(written / "in.txt"), str(docs / "report.md")] and calls == [], (words, calls)
    assert said == [_through_a_link(docs / "report.md", docs / "report.md", taxes)], said
    # A link that stays in the granted folders is the app's to follow where the argument is its own
    # path; the user's link from outside to a file inside (R3-17) is followed no more
    stays = [str(docs / "song"), str(docs / "self"), str(desk / "good")]
    words, said, calls = _handed(tmp_path, home, stays, visible=[docs, media], home=home)
    assert words == stays and calls == [] and said == [_through_a_link(desk / "good", desk / "good", docs / "in.txt")], (words, calls, said)
    # And with no grant of the folder now (CR1.5-55: one the app could write once, a grant taken
    # away since), where the link was taken for the user's own and followed: nothing is handed over
    once = [str(docs / "report.md"), str(docs / "Photos"), str(docs / "Photos" / "deep" / "file")]
    words, said, calls = _handed(tmp_path, home, once, visible=[media], home=home)
    assert words == once and calls == [], (words, calls)
    assert said == [_through_a_link(once[0], docs / "report.md", taxes), _through_a_link(once[1], docs / "Photos", private),
                    _through_a_link(once[2], docs / "Photos", private / "deep" / "file")], said


# CR1.5-55 (#759), the owner's decision of 2026-11-25: a file argument is never followed through a
# link. CR1.5-4 and CR1.5-52 kept the helper from following a link out of a folder the app is shown
# now, or holds through the portal now; a link stays on the disk longer than that. A tool run once
# in ~/src/proj left a link to ~/Documents/taxes.txt where README.md was, and `tool
# ~/src/proj/README.md`, run from the home folder, was handed taxes.txt, read-write; an app handed
# ~/work did the same through the portal, and was handed the target after the next login. How it
# slipped past: each fix asked "is the link in a folder the app has", and the tests beside them held
# a link in a folder it has no more to be the user's own ("with no grant of the folder the link is
# the user's own, followed"). The rule is asked of the link alone now, wherever it lies.
def test_a_file_argument_is_followed_through_no_link_but_one_only_root_can_have_put_there(tmp_path):
    home = tmp_path / "home"
    sync, proj, docs = home / "sync", home / "src" / "proj", home / "Documents"
    for d in (sync / "project", proj / "sub", docs / "deep", home / "elsewhere"):
        d.mkdir(parents=True)
    for f in (sync / "notes-2024.txt", sync / "plain.txt", docs / "taxes.txt", docs / "deep" / "file", proj / "main.c", proj / "sub" / "own.txt"):
        f.write_text("x")
    taxes, doc = docs / "taxes.txt", str(tmp_path / "run" / "doc" / "DOC")
    # What a tool left in the folder it was run in once: a link where its file was, to a file and
    # to a folder, by a full path and a relative one, a link to a link, a link in a folder below
    (proj / "README.md").symlink_to(taxes)
    (proj / "rel.md").symlink_to("../../Documents/taxes.txt")
    (proj / "all").symlink_to(docs)
    (proj / "hop").symlink_to("README.md")
    (proj / "sub" / "up").symlink_to("../../../Documents")
    (proj / "own").symlink_to("sub/own.txt")                             # ...and one that stays in the folder
    planted = {str(proj / "README.md"): (proj / "README.md", taxes),
               str(proj / "rel.md"): (proj / "rel.md", taxes),
               str(proj / "all"): (proj / "all", docs),
               str(proj / "all") + "/": (proj / "all", docs),
               str(proj / "all" / "taxes.txt"): (proj / "all", taxes),
               str(proj / "all" / "deep" / "file"): (proj / "all", docs / "deep" / "file"),
               str(proj / "hop"): (proj / "hop", taxes),
               str(proj / "sub" / "up" / "taxes.txt"): (proj / "sub" / "up", taxes),
               str(proj / "own"): (proj / "own", proj / "sub" / "own.txt"),
               "src/proj/README.md": (proj / "README.md", taxes),
               "./src/proj/all/taxes.txt": (proj / "all", taxes),
               "src/proj/sub/../README.md": (proj / "README.md", taxes)}
    forms = list(planted) + ["file://" + str(proj / "README.md"), "--file=" + str(proj / "README.md"), "-o" + str(proj / "all" / "taxes.txt"),
                             "--dir=src/proj/all"]
    lines = [_through_a_link(arg, link, real) for arg, (link, real) in planted.items()] + [_through_a_link("src/proj/all", proj / "all", docs)]
    # run from the home folder, from another folder the tool is given (its shared one), with a
    # folder granted, with the file the link leads to in a granted folder, with the folder held
    # through the portal by another name: nothing is handed over, nothing becomes another path
    for where in ({}, {"visible": [home / "elsewhere"]}, {"visible": [docs]}, {"held": {"D7": str(home / "elsewhere")}}):
        words, said, calls = _handed(tmp_path, home, forms, home=home, **where)
        assert words == forms and calls == [] and said == lines, (where, words, calls, said)
    relative = {"../src/proj/README.md": (proj / "README.md", taxes), "../src/proj/all/taxes.txt": (proj / "all", taxes),
                "../src/proj/hop": (proj / "hop", taxes), "../src/proj/all": (proj / "all", docs)}
    typed = forms + list(relative) + ["--file=../src/proj/hop"]
    words, said, calls = _handed(tmp_path, home / "elsewhere", typed, visible=[home / "elsewhere"], incwd=str(home / "elsewhere"), home=home)
    assert words == typed and calls == [], (words, calls)
    assert said == lines[:9] + [_through_a_link(arg, link, real) for arg, (link, real) in relative.items()], said
    # ...while the files beside them are handed over as before, a folder too
    words, said, calls = _handed(tmp_path, home, [str(proj / "main.c"), "src/proj/sub/own.txt", str(proj / "sub")], home=home)
    assert words == [f"{doc}/main.c", f"{doc}/own.txt", f"{doc}/sub"] and said == [], (words, said)
    assert [c[2] for c in calls if c[2]] == [[str(proj / "main.c")], [str(proj / "sub" / "own.txt")], [str(proj / "sub")]], calls

    # The user's own links are followed no more either (the cost the decision takes): a file kept
    # elsewhere and linked into the home, by a full path, a relative one, a URI, an option's value,
    # a link to a link, a linked folder. Each is said once, with the path to give instead.
    (home / "notes.txt").symlink_to(sync / "notes-2024.txt")
    (home / "rel-notes.txt").symlink_to("sync/notes-2024.txt")
    (home / "first").symlink_to("notes.txt")                               # a link to a link
    (home / "proj-link").symlink_to(sync / "project")
    notes = sync / "notes-2024.txt"
    args = [str(home / "notes.txt"), "rel-notes.txt", "file://" + str(home / "notes.txt"), "--file=first", str(sync / "plain.txt"),
            str(home / "proj-link"), "proj-link/"]
    words, said, calls = _handed(tmp_path, home, args, home=home)
    assert words == args[:4] + [f"{doc}/plain.txt"] + args[5:], words
    assert said == [_through_a_link(home / "notes.txt", home / "notes.txt", notes), _through_a_link("rel-notes.txt", home / "rel-notes.txt", notes),
                    _through_a_link("first", home / "first", notes), _through_a_link(home / "proj-link", home / "proj-link", sync / "project"),
                    _through_a_link("proj-link/", home / "proj-link", sync / "project")], said
    assert [c[2] for c in calls if c[2]] == [[str(sync / "plain.txt")]], calls
    # ...and the path each line gives is handed over
    words, said, calls = _handed(tmp_path, home, [str(notes), str(sync / "project")], home=home)
    assert words == [f"{doc}/notes-2024.txt", f"{doc}/project"] and said == [], (words, said)

    # A link only root can have put there is no app's, and is followed: root's own, in a folder the
    # user can't change (a system's /home -> /var/home, /bin -> usr/bin). What is handed over is the
    # file it leads to, by that file's own name (CR1.5-41: the portal names a document after the
    # file its descriptor reaches, and the link's name was a path that isn't there).
    roots = {home / "notes.txt": 0, home / "first": 0, home / "proj-link": 0}
    system = [str(home / "notes.txt"), "rel-notes.txt", "--file=first", "file://" + str(home / "first"), str(home / "proj-link"), "proj-link/"]
    words, said, calls = _handed(tmp_path, home, system, home=home, helper=_the_helper_where(tmp_path, roots, locked=[home]))
    assert words == [f"{doc}/notes-2024.txt", "rel-notes.txt", f"--file={doc}/notes-2024.txt", f"file://{doc}/notes-2024.txt", f"{doc}/project",
                     f"{doc}/project/"], words
    assert said == [_through_a_link("rel-notes.txt", home / "rel-notes.txt", notes)], said          # the user's own, beside them
    assert [c[2] for c in calls if c[2]] == [[str(notes)]] * 3 + [[str(sync / "project")]], calls
    # ...as the system's own are, asked of the system itself: /etc/os-release, a link on the systems AppKata runs on, and /bin/sh
    there = [os.path.realpath("/etc/os-release"), os.path.realpath("/bin/sh")]
    words, said, calls = _handed(tmp_path, home, ["/etc/os-release", "file:///bin/sh"], home=home)
    assert words == [f"{doc}/{os.path.basename(there[0])}", f"file://{doc}/{os.path.basename(there[1])}"] and said == [], (words, said)
    assert [c[2] for c in calls if c[2]] == [[there[0]], [there[1]]], calls
    # ...root's own in a folder the user can change is anyone's to move there, and another user's link is no better
    for owners, locked in ((roots, []), ({link: 4242 for link in roots}, [home]), ({home / "first": 0}, [home])):
        words, said, calls = _handed(tmp_path, home, system, home=home, helper=_the_helper_where(tmp_path, owners, locked))
        assert words == system and calls == [] and len(said) == 6, (owners, locked, words, calls, said)        # each said, by its own words
    # ...and the process's own descriptors, which lead through the kernel's links in /proc, pass as
    # typed with no line: the app has its own, and a tool's `-o /dev/stdout` is no file argument
    own = ["/dev/stdout", "/dev/stderr", "/proc/self/fd/1", "-o/dev/stdout", "--log=/dev/stderr", "/dev/fd/1", "/dev/null"]
    words, said, calls = _handed(tmp_path, home, own, home=home)
    assert words == own and calls == [] and said == [], (words, calls, said)
    # ...and a never-shared place is said as that, never as a path to give, whoever made the link
    (home / ".ssh").mkdir()
    (home / ".ssh" / "id").write_text("KEY")
    (home / "key").symlink_to(home / ".ssh" / "id")
    for helper in (None, _the_helper_where(tmp_path, {home / "key": 0}, locked=[home])):
        words, said, calls = _handed(tmp_path, home, [str(home / "key")], never=[home / ".ssh"], home=home, helper=helper)
        assert words == [str(home / "key")] and calls == [], (words, calls)
        assert said == [f"runs sandboxed and isn't handed {home}/key: {home}/.ssh is never shared with a sandboxed app."], said


@pytest.mark.parametrize("template", ["cli-tool", "standard"])
def test_the_launcher_says_why_an_argument_through_a_link_is_not_handed_over(tmp_path, monkeypatch, template):
    # CR1.5-55, the finding's own road through the launcher's own lines: a tool run once in
    # ~/src/proj left a link there; `tool ~/src/proj/README.md ~/src/proj/main.c`, run from another
    # folder, reaches the program with the first argument as typed, the portal is given the second
    # file alone, and the launcher says why after the app's name.
    home = tmp_path / "home"
    proj, taxes = home / "src" / "proj", home / "Documents" / "taxes.txt"
    for d in (proj, taxes.parent, home / "other"):
        d.mkdir(parents=True)
    taxes.write_text("TAXES")
    (proj / "main.c").write_text("x")
    (proj / "README.md").symlink_to(taxes)
    (tmp_path / "forward-files.py").write_text(sb.FORWARD_HELPER)
    args = [str(proj / "README.md"), "--readme=" + str(proj / "README.md"), str(proj / "main.c")]
    proxy, app, r, rt = _launched(tmp_path, monkeypatch, "unix:path={rt}/bus", template=template, forward=str(tmp_path / "forward-files.py"),
                                  tools={"python3": _a_python3_with_the_stand_in_portal(tmp_path)}, args=args, cwd=home / "other")
    calls = [json.loads(line) for line in (tmp_path / "portal.log").read_text().splitlines()]
    assert r.returncode == 0 and app[-3:] == args[:2] + [str(rt / "doc" / "DOC" / "main.c")], (app[-4:], r.stderr)
    assert [c[2] for c in calls if c[2]] == [[str(proj / "main.c")]], calls
    assert r.stderr.splitlines().count("Demo " + _through_a_link(proj / "README.md", proj / "README.md", taxes)) == 1, r.stderr


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


def _a_home_with_its_never_shared_places(tmp_path, monkeypatch):
    """A home folder holding each never-shared place of R17.3.1 with a file in it, and ordinary
    files beside them; AppKata's own folders are this home's. Returns the home and the list the
    launcher gives the file-argument helper."""
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "run"))
    for v in ("XDG_DATA_HOME", "APPKATA_APPS", "APPKATA_DATA"):
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setattr(sb, "sandboxes_root", lambda: str(home / ".local/share/appkata/sandboxes"))
    never = list(dict.fromkeys([sb.sandboxes_root()] + [r for r, _ in sb._protected_roots()]))
    for root in never:
        os.makedirs(os.path.join(root, "inside"), exist_ok=True)
        with open(os.path.join(root, "inside", "file"), "w") as f:
            f.write("x")
    for rel in ("Documents/notes.txt", "proj/src/main.c", "dotfiles/bashrc", "dotfiles/ssh_config"):
        (home / rel).parent.mkdir(parents=True, exist_ok=True)
        (home / rel).write_text("x")
    return home, never


def test_a_never_shared_folder_is_handed_over_by_no_argument_and_the_helper_says_why(tmp_path, monkeypatch):
    # CR1.5-38 (the owner's decision of 2026-11-23: the never-shared list wins over an argument). The
    # helper exported whatever an argument named, whole and read-write: `tool .` from the home
    # folder, `tool ~/.ssh`, `/`, the home dropped on a menu entry. How it slipped past: the helper
    # was never given the list, and every hand-over test named a file in ~/Documents.
    home, never = _a_home_with_its_never_shared_places(tmp_path, monkeypatch)
    ssh, rt = home / ".ssh", tmp_path / "run"
    (ssh / "id_ed25519").write_text("KEY")
    (home / "Documents" / "key").symlink_to(ssh / "id_ed25519")            # a link elsewhere that leads in
    (ssh / "config").symlink_to(home / "dotfiles" / "ssh_config")         # a file of ~/.ssh kept elsewhere
    os.rename(home / ".bashrc", home / ".bashrc.was")
    (home / ".bashrc").symlink_to(home / "dotfiles" / "bashrc")           # a startup file kept elsewhere
    (home / "keys").symlink_to(ssh)
    refused = {".": "your whole home folder is never shared",
               str(home): "your whole home folder is never shared",
               str(home) + "/": "your whole home folder is never shared",
               "/": "it holds your whole home folder, which is never shared",
               str(tmp_path): "it holds your whole home folder, which is never shared",
               "..": "it holds your whole home folder, which is never shared",
               ".ssh": f"{ssh} is never shared",
               str(ssh): f"{ssh} is never shared",
               str(ssh / "id_ed25519"): f"{ssh} is never shared",
               ".ssh/id_ed25519": f"{ssh} is never shared",
               "Documents/../.ssh/id_ed25519": f"{ssh} is never shared",
               str(home / "keys" / "id_ed25519"): f"{ssh} is never shared",
               str(home / "Documents" / "key"): f"{ssh} is never shared",
               str(ssh / "config"): f"{ssh} is never shared",
               str(home / ".bashrc"): f"{home}/.bashrc is never shared",
               str(home / ".config"): f"it holds {home}/.config/autostart, which is never shared",
               str(home / ".local" / "share"): f"it holds {home}/.local/share/appkata/sandboxes, which is never shared",
               str(home / "bin" / "apps" / "inside" / "file"): f"{home}/bin/apps is never shared",
               str(rt / "inside" / "file"): f"{rt} is never shared"}
    args = list(refused) + ["file://" + str(ssh / "id_ed25519"), "--key=" + str(ssh / "id_ed25519"), "-i" + str(ssh / "id_ed25519"),
                            "file://" + str(home)]
    words, said, calls = _handed(tmp_path, home, args, never=never, home=home)
    assert words == args and calls == [], (words, calls)                # each passes as it was, and the portal is asked nothing
    for arg, why in refused.items():
        assert f"runs sandboxed and isn't handed {arg}: {why} with a sandboxed app." in said, (arg, said)
    assert len(said) == len(refused), said                              # a file named three ways is said once
    # ...and what is no never-shared place is handed over as before: a file, a folder, an option's
    # value, a file under /tmp (the system's own places are a grant's rule, never an argument's: R17.3.3)
    (tmp_path / "work").mkdir()
    (tmp_path / "work" / "draft.txt").write_text("x")
    given = ["Documents/notes.txt", str(home / "proj"), "--file=" + str(home / "Documents" / "notes.txt"), str(tmp_path / "work" / "draft.txt"),
             str(home / ".config" / "other.conf"), str(home / ".bashrc.was" / "inside" / "file")]
    (home / ".config" / "other.conf").write_text("x")
    doc = str(rt / "doc" / "DOC")
    words, said, calls = _handed(tmp_path, home, given, never=never, home=home)
    assert words == [f"{doc}/notes.txt", f"{doc}/proj", f"--file={doc}/notes.txt", f"{doc}/draft.txt", f"{doc}/other.conf", f"{doc}/file"] and said == []
    assert [c[0] for c in calls] == ["Add", "GrantPermissions", "AddFull", "Add", "GrantPermissions", "Add", "GrantPermissions",
                                     "Add", "GrantPermissions", "Add", "GrantPermissions"], calls


def test_the_session_bus_socket_is_handed_over_by_no_argument_nor_a_folder_above_it(tmp_path, monkeypatch):
    # ...and the bus's own socket file, wherever the session's address puts it ($bussocks, as the
    # launcher read it): the file and what is above it, never what is beside it (R17.3.1)
    home, never = _a_home_with_its_never_shared_places(tmp_path, monkeypatch)
    sock, bus = _a_bus_socket(home / "session")
    (home / "session" / "notes.txt").write_text("x")
    bus = str(bus)
    try:
        words, said, calls = _handed(tmp_path, home, [bus, str(home / "session"), "session/notes.txt"], never=never, sockets=[bus], home=home)
    finally:
        sock.close()
    assert words == [bus, str(home / "session"), str(tmp_path / "run" / "doc" / "DOC" / "notes.txt")], words
    assert said == [f"runs sandboxed and isn't handed {bus}: {bus} is never shared with a sandboxed app.",
                    f"runs sandboxed and isn't handed {home}/session: it holds {bus}, which is never shared with a sandboxed app."]
    assert [c[0] for c in calls] == ["Add", "GrantPermissions"] and calls[0][2] == [str(home / "session" / "notes.txt")], calls


def test_the_helper_hands_over_nothing_a_grant_could_not_share_but_under_the_systems_places(tmp_path, monkeypatch):
    # The class: two rules for one list. A folder grant is judged by protected_folder(), a file
    # argument by the helper's own lines, in another language and another process, and nothing held
    # the second to the first. For every never-shared place, what is in it and what is above it:
    # whatever a grant is refused, no argument is handed. The other way round only where the grant
    # rule's reason is one of the system's own places, which an argument is not judged by (a file
    # under /tmp is handed over, R17.3.3).
    home, never = _a_home_with_its_never_shared_places(tmp_path, monkeypatch)
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", f"unix:path={tmp_path}/run/bus")
    places = [p for root in never for p in (root, os.path.join(root, "inside"), os.path.join(root, "inside", "file"), os.path.dirname(root))]
    places += [str(home), str(tmp_path), "/", str(home / "Documents"), str(home / "Documents" / "notes.txt"), str(home / "proj"),
               str(home / ".config" / "inside"), str(home / ".local" / "state")]
    for d in (home / ".config" / "inside", home / ".local" / "state", tmp_path / "work"):
        d.mkdir()
    (tmp_path / "work" / "draft.txt").write_text("x")
    places = list(dict.fromkeys(places + [str(tmp_path / "work"), str(tmp_path / "work" / "draft.txt")]))
    words, said, calls = _handed(tmp_path, home, places, never=never, home=home)
    kept = {p for p, w in zip(places, words) if p == w}
    system = 0
    for p in places:
        why = sb.protected_folder(p)
        if why.startswith(("the system's own ", "a folder above the system's own ")):
            system, why = system + 1, ""
        assert (p in kept) == bool(why), (p, why, said)
    # what is handed over is a document of its own, or a path in a folder handed over just before it (CR1.5-52)
    assert len(kept) == len(said) > 3 * len(never) and system == 2 and len(places) - len(kept) == 7 and len(calls) == 5, (len(kept), len(said), system, calls)


def _a_python3_with_the_stand_in_portal(tmp_path) -> str:
    """The script of a `python3` that finds the stand-in document portal (_STAND_IN_GI), for a
    launcher to run its file-argument helper with."""
    gi = tmp_path / "stand-in" / "gi"
    gi.mkdir(parents=True, exist_ok=True)
    (gi / "__init__.py").write_text("")
    (gi / "repository.py").write_text(_STAND_IN_GI)
    return (f"#!/bin/sh\nPYTHONPATH={shlex.quote(str(gi.parent))} PORTAL_LOG={shlex.quote(str(tmp_path / 'portal.log'))} "
            f'exec {shlex.quote(sys.executable)} "$@"\n')


@pytest.mark.parametrize("template", ["cli-tool", "standard"])
def test_the_launcher_says_why_an_argument_in_a_never_shared_folder_is_not_handed_over(tmp_path, monkeypatch, template):
    # CR1.5-38, through the launcher's own lines: `tool . ~/.ssh/id_ed25519 Documents/notes.txt` from
    # the home folder. The tool's line said it couldn't see the home, and the helper then handed the
    # home over, read-write. Now neither the home nor the key is handed over, each with its line on
    # stderr after the app's name, and the file beside them still is.
    home = tmp_path / "home"
    key = home / ".ssh" / "id_ed25519"
    for f in (key, home / "Documents" / "notes.txt"):
        f.parent.mkdir(parents=True)
        f.write_text("x")
    (tmp_path / "forward-files.py").write_text(sb.FORWARD_HELPER)
    args = [".", str(key), "--key=" + str(key), "Documents/notes.txt"]
    proxy, app, r, rt = _launched(tmp_path, monkeypatch, "unix:path={rt}/bus", template=template, forward=str(tmp_path / "forward-files.py"),
                                  tools={"python3": _a_python3_with_the_stand_in_portal(tmp_path)}, args=args)
    calls = [json.loads(line) for line in (tmp_path / "portal.log").read_text().splitlines()]
    assert r.returncode == 0 and app[-4:] == [".", str(key), "--key=" + str(key), str(rt / "doc" / "DOC" / "notes.txt")], (app[-5:], r.stderr)
    assert [c[2] for c in calls if c[2]] == [[str(home / "Documents" / "notes.txt")]], calls       # the one file, and nothing else
    lines = r.stderr.splitlines()
    assert f"Demo runs sandboxed and isn't handed .: your whole home folder is never shared with a sandboxed app." in lines, r.stderr
    assert lines.count(f"Demo runs sandboxed and isn't handed {key}: {home}/.ssh is never shared with a sandboxed app.") == 1, r.stderr
    if template == "cli-tool":                    # the tool's own line no longer promises every named file
        assert f"Demo runs sandboxed and can't see {home} " in r.stderr, r.stderr
        assert "is handed over either way, unless it is in a never-shared folder of your home" in r.stderr, r.stderr


def test_a_bare_word_is_a_file_argument_when_it_names_a_file_and_never_a_folder(tmp_path):
    # CR1.5-15, part 1 (the owner's decision of 2026-11-24): every argument that named something
    # there was taken for a file argument, so `tool build --verbose help`, run where a folder
    # `build` lies, exported the folder, read-write, and gave the tool a path where its word was.
    # How it slipped past: every argument the tests passed was meant as a path.
    home = tmp_path / "home"
    proj, docs = home / "proj", home / "Docs"
    for d in (proj / "build", proj / "help", proj / ".git", docs / "sub"):
        d.mkdir(parents=True)
    for f in (proj / "notes.txt", proj / "run", docs / "in.txt"):
        f.write_text("x")
    (proj / "latest").symlink_to("build")
    doc = str(tmp_path / "run" / "doc" / "DOC")
    words, said, calls = _handed(tmp_path, proj, ["build", "--verbose", "help", "latest", "--mode=build", "notes.txt", "run", "--file=notes.txt"], home=home)
    assert words == ["build", "--verbose", "help", "latest", "--mode=build", f"{doc}/notes.txt", f"{doc}/run", f"--file={doc}/notes.txt"], words
    assert "AddFull" not in [c[0] for c in calls] and [c[2] for c in calls if c[2]] == [[str(proj / f)] for f in ("notes.txt", "run", "notes.txt")], calls
    # the folder is named by a path: ./build, build/, its full path, a URI, . itself, or a dot folder
    named = ["./build", "build/", str(proj / "build"), "file://" + str(proj / "build"), ".", ".git", "--dir=./build"]
    words, said, calls = _handed(tmp_path, proj, named, home=home)
    # (handed over once, the folder is the app's for the arguments after it, CR1.5-52: `.git` is then a path in `.`'s document)
    assert words == [f"{doc}/build", f"{doc}/build/", f"{doc}/build", f"file://{doc}/build", f"{doc}/proj", f"{doc}/proj/.git", f"--dir={doc}/build"], words
    assert [c[0] for c in calls] == ["AddFull"] * 2 and [c[2] for c in calls] == [[str(proj / "build")], [str(proj)]], calls
    # in a granted folder the same: the word stays the program's own, and a file becomes its path there
    assert _forward(tmp_path, docs, "", [docs], ["sub", "in.txt", "./sub", "sub/"]) == ["sub", str(docs / "in.txt"), str(docs / "sub"), str(docs / "sub") + "/"]


def test_a_tools_relative_path_that_leaves_its_shared_folder_is_handed_over(tmp_path):
    # CR1.5-15, part 2: in its shared folder a tool's relative path always passed unchanged, also
    # one that leaves the folder, so `tool ../notes.txt` reached nothing inside, though R17.6.2
    # hands over what the sandbox can't see. As typed only while it stays in the folder.
    home = tmp_path / "home"
    proj, docs = home / "src" / "proj", home / "Docs"
    for d in (proj / "sub", docs):
        d.mkdir(parents=True)
    for f in (home / "src" / "notes.txt", proj / "a.txt", proj / "sub" / "b.txt", docs / "in.txt"):
        f.write_text("x")
    (proj / "up").symlink_to("..")                                         # a way out that is a link in the folder: never followed
    doc = str(tmp_path / "run" / "doc" / "DOC")
    typed = ["a.txt", "./a.txt", "sub/b.txt", "sub/../a.txt", ".", "sub", "../proj/a.txt", "up/notes.txt"]
    words, said, calls = _handed(tmp_path, proj, typed + ["../notes.txt", "../../Docs/in.txt", "--file=../notes.txt"],
                                 visible=[proj, docs], incwd=str(proj), home=home)
    assert words == typed + [f"{doc}/notes.txt", str(docs / "in.txt"), f"--file={doc}/notes.txt"], words
    assert [c[2] for c in calls if c[2]] == [[str(home / "src" / "notes.txt")]] * 2, calls
    # from the folder's own sub-folder the tool is not in place: every relative path is made whole
    assert _forward(tmp_path, proj / "sub", str(proj), [proj], ["b.txt", "../a.txt"]) == [str(proj / "sub" / "b.txt"), str(proj / "a.txt")]


def test_a_link_in_a_folder_the_app_was_handed_is_never_followed_out_of_it(tmp_path):
    # CR1.5-52 (#736): CR1.5-4's road, by a folder argument where that one had a grant. A folder
    # handed over (`editor ~/proj`) is the app's to write through the portal, links too; a later
    # `editor ~/proj/README.md` was judged by the launcher's folders alone, the app's link was
    # followed, and its target handed over, read-write. How it slipped past: #379's test made the
    # helper's rule for the folders it is told of, and the folders the portal knows of were never
    # among them; nothing ran two starts of one app. The helper asks the portal what the app holds.
    # Since CR1.5-55 no link is followed for an app at all, so a link in such a folder passes as
    # typed, with a line (it had become its path in the folder's document, dangling); what the
    # portal holds still decides where a file of the folder is: its path in that document.
    home, rt = tmp_path / "home", tmp_path / "run"
    proj, docs, other, new = home / "proj", home / "Documents", home / "other", home / "new"
    for d in (proj / "sub", docs, other, new, home / ".ssh"):
        d.mkdir(parents=True)
    for f in (docs / "taxes.txt", docs / "single.txt", proj / "notes.md", proj / "sub" / "deep.txt", other / "in.txt", new / "plain.md", home / ".ssh" / "id"):
        f.write_text("x")
    # what the app left in the folder it was handed, and the user's own links beside it
    (proj / "README.md").symlink_to(docs / "taxes.txt")
    (proj / "rel.md").symlink_to("../Documents/taxes.txt")
    (proj / "sub" / "all").symlink_to(docs)
    (proj / "hop").symlink_to("README.md")
    (proj / "back.md").symlink_to("sub/deep.txt")
    (home / "mine.md").symlink_to(proj / "notes.md")
    (home / "via").symlink_to(proj / "README.md")
    (new / "README.md").symlink_to(docs / "taxes.txt")
    held = {"D1": str(proj), "D2": str(docs / "single.txt")}
    view, doc = str(rt / "doc" / "D1" / "proj"), str(rt / "doc" / "DOC")
    taxes = docs / "taxes.txt"
    led_out = {str(proj / "README.md"): (proj / "README.md", taxes),       # each passes as typed, the link not followed,
               str(proj / "rel.md"): (proj / "rel.md", taxes),             # and is said with what it leads to
               str(proj / "sub" / "all" / "taxes.txt"): (proj / "sub" / "all", taxes),
               str(proj / "sub" / "all"): (proj / "sub" / "all", docs),
               str(proj / "hop"): (proj / "hop", taxes),
               str(home / "via"): (home / "via", taxes),                   # the user's own link to the app's
               "proj/README.md": (proj / "README.md", taxes),
               str(proj / "back.md"): (proj / "back.md", proj / "sub" / "deep.txt"),      # a link that stays in the folder
               str(home / "mine.md"): (home / "mine.md", proj / "notes.md")}              # the user's link into it (R3-17's direction)
    forms = ["file://" + str(proj / "README.md"), "--file=" + str(proj / "README.md")]    # said once, with the path's own line
    stays = {str(proj / "notes.md"): f"{view}/notes.md",                   # a file of the folder: its path there, and no
             str(proj / "sub" / "deep.txt"): f"{view}/sub/deep.txt",       # document of its own
             str(proj): view, str(proj) + "/": view + "/"}
    words, said, calls = _handed(tmp_path, home, list(led_out) + forms + list(stays), home=home, held=held, never=[home / ".ssh"])
    assert words == list(led_out) + forms + list(stays.values()) and calls == [], (words, calls)
    assert said == [_through_a_link(arg, link, real) for arg, (link, real) in led_out.items()], said
    # what the app holds no folder of is handed over as before, and a link in a folder the portal
    # lists for no one is followed no more than any other (it was the user's own, as far as the
    # launcher could tell: CR1.5-55's road, once the portal has forgotten the folder)
    words, said, calls = _handed(tmp_path, home, [str(docs / "single.txt"), str(other / "in.txt"), str(new / "README.md")], home=home, held=held)
    assert words == [f"{doc}/single.txt", f"{doc}/in.txt", str(new / "README.md")], words
    assert [c[2] for c in calls if c[2]] == [[str(docs / "single.txt")], [str(other / "in.txt")]], calls
    assert said == [_through_a_link(new / "README.md", new / "README.md", taxes)], said
    words, said, calls = _handed(tmp_path, home, [str(proj / "README.md")], home=home)                  # held by no one: CR1.5-52's own run
    assert words == [str(proj / "README.md")] and calls == [] and said == [_through_a_link(proj / "README.md", proj / "README.md", taxes)], (words, calls)
    # a folder handed over by one argument is the app's for the arguments after it, at the same start
    words, said, calls = _handed(tmp_path, home, [str(new), str(new / "README.md"), str(new / "plain.md"), str(other / "in.txt")], home=home)
    assert words == [f"{doc}/new", str(new / "README.md"), f"{doc}/new/plain.md", f"{doc}/in.txt"], words
    assert [c[0] for c in calls] == ["AddFull", "Add", "GrantPermissions"] and calls[1][2] == [str(other / "in.txt")], calls
    # a granted folder comes first: a file in both is where the grant is mounted
    assert _handed(tmp_path, home, [str(proj / "notes.md"), str(proj / "README.md")], visible=[proj], home=home, held=held)[0] == [
        str(proj / "notes.md"), str(proj / "README.md")]
    # what the portal lists counts only where it is a folder that is there in the portal's own
    # view, and no never-shared one (the helper hands none over; the list is asked all the same)
    ssh = home / ".ssh"
    words, said, calls = _handed(tmp_path, home, [str(ssh / "id")], home=home, held={"D3": str(ssh)}, never=[ssh])
    assert words == [str(ssh / "id")] and calls == [], (words, calls)
    assert said == [f"runs sandboxed and isn't handed {ssh}/id: {ssh} is never shared with a sandboxed app."], said
    os.unlink(rt / "doc" / "D1" / "proj")
    (rt / "doc" / "D1" / "proj").write_text("no folder")                  # listed, and the view has no folder of that name
    words, said, calls = _handed(tmp_path, home, [str(proj / "notes.md")], home=home, held=held)
    assert words == [f"{doc}/notes.md"] and [c[0] for c in calls] == ["Add", "GrantPermissions"], (words, calls)
    # where the portal doesn't say what the app holds, nothing is handed over; a granted folder's
    # files are still the paths the app sees
    words, said, calls = _handed(tmp_path, home, [str(other / "in.txt"), str(new), str(proj / "notes.md"), str(proj / "README.md")],
                                 visible=[proj], home=home, gone="org.freedesktop.DBus.Error.NoReply")
    assert words == [str(other / "in.txt"), str(new), str(proj / "notes.md"), str(proj / "README.md")] and calls == [] and said == [], (words, calls)


# CR1.5-25 (#400): what an app is handed through the document portal is the portal's to keep, under
# the app's identity, for as long as the portal runs. Nothing took it back, so an app uninstalled
# with its home removed left every file the user had opened with it to the next app of that name:
# the id is free again (R17.6), and the launcher binds `doc/by-app/io.appkata.<id>`. The same for
# an app sent to Strict or Off and back. How it slipped past: every hand-over test stopped at the
# hand-over, and every test of an uninstall or a level change was of an app handed nothing; the
# review itself could not run a portal. Shown with the real one in tests/test_sandbox_run.py.
ALL_PERMISSIONS = ["read", "write", "grant-permissions", "delete"]


def a_portal_holding(tmp_path, monkeypatch, held):
    """The stand-in document portal holding `held` ({identity: {document id: host path}}) for
    AppKata's own asks of it (sandbox.revoke_documents): a python3 where the launchers find theirs
    whose gi is the stand-in. Returns the file the documents are in, the file the portal's calls
    are written to, and the file each run of that python3 is written to (its first two arguments)."""
    gi, docs, log, runs = tmp_path / "stand-in" / "gi", tmp_path / "portal-docs.json", tmp_path / "portal.log", tmp_path / "python3.runs"
    gi.mkdir(parents=True, exist_ok=True)
    (gi / "__init__.py").write_text("")
    (gi / "repository.py").write_text(_STAND_IN_GI)
    docs.write_text(json.dumps(held))
    python = tmp_path / "host-bin" / "python3"
    python.parent.mkdir(exist_ok=True)
    # AppKata passes -I, which keeps PYTHONPATH out; the stand-in is found by it, so the flag is
    # written down and then dropped
    python.write_text(f'#!/bin/sh\nprintf "%s %s\\n" "$1" "$2" >> {shlex.quote(str(runs))}\n[ "$1" = -I ] && shift\n'
                      f'PYTHONPATH={shlex.quote(str(gi.parent))} exec {shlex.quote(sys.executable)} "$@"\n')
    python.chmod(0o755)
    monkeypatch.setattr(sb, "host_which", lambda name, apps_root=None: str(python) if name == "python3" else None)
    monkeypatch.setenv("PORTAL_DOCS", str(docs))
    monkeypatch.setenv("PORTAL_LOG", str(log))
    for v in ("PORTAL_GONE", "PORTAL_KEEPS"):
        monkeypatch.delenv(v, raising=False)
    return docs, log, runs


def _portal_calls(log) -> list:
    return [json.loads(line)[:2] for line in log.read_text().splitlines()] if log.exists() else []


def test_the_helper_says_beside_itself_that_an_app_was_handed_something_before_it_hands_it_over(tmp_path, monkeypatch):
    home = tmp_path / "home"
    docs, proj = home / "Documents", home / "proj"
    for d in (docs, proj):
        d.mkdir(parents=True)
    (docs / "taxes.txt").write_text("x")
    (proj / "in.txt").write_text("x")
    monkeypatch.setattr(sb, "sandboxes_root", lambda: str(home / ".local/share/appkata/sandboxes"))
    helper = type(tmp_path)(sb.write_forward_helper())
    record = sb.handed_path("t")
    # where AppKata looks is where the helper it wrote writes: beside the helper, named after the identity
    assert record == str(helper.parent / "handed" / "io.appkata.t") and os.path.basename(sb.handed_path("7zip")) == sb.app_identity("7zip")
    # nothing is handed over by a file the app is shown, one that isn't there, or a program's own word
    words, said, calls = _handed(tmp_path, home, [str(proj / "in.txt"), "nothing.txt", "proj", "https://example.org/x"], visible=[proj], home=home, helper=helper)
    assert calls == [] and not os.path.lexists(record) and not os.path.lexists(helper.parent / "handed")
    # ...and a file or a folder that is, is noted first
    for arg in (str(docs / "taxes.txt"), str(docs)):
        words, said, calls = _handed(tmp_path, home, [arg], visible=[proj], home=home, helper=helper)
        assert words[0].startswith(str(tmp_path / "run" / "doc")) and calls and os.path.isfile(record), (words, calls)
        assert os.stat(helper.parent / "handed").st_mode & 0o777 == 0o700 and os.path.getsize(record) == 0
        os.unlink(record)
    # where it can't be noted, nothing is handed over: the argument passes as it was
    os.rmdir(helper.parent / "handed")
    (helper.parent / "handed").write_text("in the way")
    words, said, calls = _handed(tmp_path, home, [str(docs / "taxes.txt"), str(docs), str(proj / "in.txt")], visible=[proj], home=home, helper=helper)
    assert words == [str(docs / "taxes.txt"), str(docs), str(proj / "in.txt")] and calls == [], (words, calls)


def test_what_an_app_was_handed_is_taken_back_and_the_portal_is_asked_only_for_an_app_the_helper_named(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(sb, "sandboxes_root", lambda: str(tmp_path / "sandboxes"))
    held = {"io.appkata.notes": {"d1": "/home/u/Documents/taxes.txt", "d2": "/home/u/proj"},
            "io.appkata.notes-2": {"d1": "/home/u/Documents/taxes.txt"}, "io.appkata._7zip": {"d3": "/home/u/a.7z"}}
    docs, log, runs = a_portal_holding(tmp_path, monkeypatch, held)

    def note(app_id):
        os.makedirs(os.path.dirname(sb.handed_path(app_id)), exist_ok=True)
        open(sb.handed_path(app_id), "w").close()

    # an app the helper handed nothing: no process, no bus, nothing changed
    assert sb.revoke_documents("notes") is True
    assert not runs.exists() and _portal_calls(log) == [] and json.loads(docs.read_text()) == held
    # one it did: every document the portal lists for its identity loses every permission, and no
    # other identity's does (the second "Notes" was handed the same file)
    note("notes")
    assert sb.revoke_documents("notes") is True
    assert _portal_calls(log) == [["RevokePermissions", [d, "io.appkata.notes", ALL_PERMISSIONS]] for d in ("d1", "d2")]
    assert json.loads(docs.read_text()) == {**held, "io.appkata.notes": {}}
    assert runs.read_text() == "-I -c\n" and not os.path.lexists(sb.handed_path("notes"))
    assert sb.revoke_documents("notes") is True and runs.read_text() == "-I -c\n"     # taken back once
    # an identity that isn't the id as it is
    note("7zip")
    assert sb.revoke_documents("7zip") is True and _portal_calls(log)[-1] == ["RevokePermissions", ["d3", "io.appkata._7zip", ALL_PERMISSIONS]]
    # no document portal on the session's bus: nothing is held, since a document lasts as long as the portal
    for gone in ("org.freedesktop.DBus.Error.ServiceUnknown", "org.freedesktop.DBus.Error.NameHasNoOwner"):
        note("notes-2")
        monkeypatch.setenv("PORTAL_GONE", gone)
        assert sb.revoke_documents("notes-2") is True and not os.path.lexists(sb.handed_path("notes-2"))
    # where the portal can't be asked, or still holds one afterwards: said, and asked again next time
    note("notes-2")
    before = len(_portal_calls(log))
    monkeypatch.setenv("PORTAL_GONE", "org.freedesktop.DBus.Error.NoReply")
    assert sb.revoke_documents("notes-2") is False
    monkeypatch.delenv("PORTAL_GONE")
    monkeypatch.setenv("PORTAL_KEEPS", "1")
    assert sb.revoke_documents("notes-2") is False
    monkeypatch.delenv("PORTAL_KEEPS")
    python = sb.host_which("python3")
    monkeypatch.setattr(sb, "host_which", lambda name, apps_root=None: None)
    assert sb.revoke_documents("notes-2") is False
    nogi = tmp_path / "host-bin" / "python3-without-gi"
    nogi.write_text("#!/bin/sh\necho \"ModuleNotFoundError: No module named 'gi'\" >&2; exit 1\n")
    nogi.chmod(0o755)
    monkeypatch.setattr(sb, "host_which", lambda name, apps_root=None: str(nogi))
    assert sb.revoke_documents("notes-2") is False
    said = [r.getMessage() for r in caplog.records if r.name == "appkata.sandbox"]
    assert len(said) == 4 and all(m.startswith("couldn't take back what io.appkata.notes-2 was handed through the document portal: ") for m in said), said
    assert "NoReply" in said[0] and "No module named 'gi'" in said[3] and "no python3" in said[2], said
    assert os.path.isfile(sb.handed_path("notes-2")) and json.loads(docs.read_text())["io.appkata.notes-2"] == held["io.appkata.notes-2"]
    assert len(_portal_calls(log)) == before + 1                           # the portal that revokes nothing was asked to
    monkeypatch.setattr(sb, "host_which", lambda name, apps_root=None: python)
    assert sb.revoke_documents("notes-2") is True and json.loads(docs.read_text())["io.appkata.notes-2"] == {}


def test_an_uninstall_a_change_away_from_standard_and_a_first_launcher_take_back_what_the_app_was_handed(fake_home, tmp_path, monkeypatch):
    # the three moments (R17.14), through the code that writes and removes launchers: asked[] is
    # each ask, with whether the app's row was still there
    import json as _json
    from appkata_core import install
    from appkata_core.db import DB, now
    monkeypatch.setattr(sb, "have_tools", lambda: True)
    monkeypatch.setattr(install, "desktop_dir", lambda: str(tmp_path / "applications"))
    monkeypatch.setenv("APPKATA_DATA", str(fake_home / ".local/share/appkata"))
    root = fake_home / "Apps"
    target = root / "notes"
    (target / "1.0" / "bin").mkdir(parents=True)
    exe = target / "1.0" / "bin" / "notes"
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    db = DB(str(tmp_path / "a.db"))
    url = "https://example.org/alice/notes"
    rec = {"id": "notes", "current": {"version": "1.0", "path": str(target / "1.0"), "exec": "1.0/bin/notes"}, "links": [], "files": [], "target": str(target)}
    port = install.Portable(folder=str(root), app_menu=False, command_dir="", stable_name=False)
    asked, real = [], sb.revoke_documents
    monkeypatch.setattr(sb, "revoke_documents", lambda app_id: asked.append((app_id, bool(db.one("SELECT 1 FROM installs WHERE url=?", (url,))))) or real(app_id))
    level = lambda template: {"name": "Notes", "url": url, "sandbox": template and sb.to_json(sb.resolve_template(template))}   # noqa: E731

    def becomes(template):
        asked.clear()
        install._activate(rec, level(template), port, str(target))
        return [a for a, _ in asked]

    assert becomes("online-app") == ["notes"]           # its first launcher: the holder of an id starts with nothing
    assert becomes("online-app") == [] and becomes("messenger") == []         # Standard to Standard: what it holds is its own
    assert becomes("strict") == ["notes"]               # it leaves Standard
    assert becomes("offline-editor") == []              # and comes back: nothing was left to take
    assert becomes(None) == ["notes"] and "launcher" not in rec               # Off
    assert becomes("standard") == ["notes"]             # sandboxed again, a first launcher
    # ...and the uninstall, once the app's row is gone, whether its home is kept or not
    for remove in (False, True):
        db.x("INSERT INTO installs(url, name, version, kind, record, installed_at) VALUES(?,?,?,?,?,?)", (url, "Notes", "1.0", "tarball", _json.dumps(rec), now()))
        asked.clear()
        install.uninstall(db, url, remove_sandbox=remove)
        assert asked == [("notes", False)], asked
    # with the portal behind it: the app was handed a file while Standard, and is uninstalled
    held = {"io.appkata.notes": {"d1": str(fake_home / "Documents" / "taxes.txt")}}
    docs, log, runs = a_portal_holding(tmp_path, monkeypatch, held)
    os.makedirs(os.path.dirname(sb.handed_path("notes")), exist_ok=True)
    open(sb.handed_path("notes"), "w").close()
    db.x("INSERT INTO installs(url, name, version, kind, record, installed_at) VALUES(?,?,?,?,?,?)", (url, "Notes", "1.0", "tarball", _json.dumps(rec), now()))
    install.uninstall(db, url, remove_sandbox=True)
    assert json.loads(docs.read_text()) == {"io.appkata.notes": {}} and _portal_calls(log) == [["RevokePermissions", ["d1", "io.appkata.notes", ALL_PERMISSIONS]]]


# CR1.5-20 (#395): a private home is its app's to write, and what an app leaves there need not be
# removable as it lies. The uninstall removed what it could, said nothing of the rest, and removed
# the owner record, after which the home was no app's (a home with no owner counts as another's):
# the data the user asked to have deleted stayed, and not even the same app installed again got it.
# How it slipped past: every uninstall test's home was one a file manager could delete.
def _a_home_its_app_made_hard_to_remove(home, outside):
    """The private home `home`, as an app can leave it: a folder no one may open with more inside
    (the finding's first case), two nested read-only folders (its second), a read-only tree as
    Go's module cache is, and links to a file and to a read-only folder in `outside`, the user's."""
    (outside / "kept").mkdir(parents=True)
    (outside / "kept" / "notes.txt").write_text("NOTES")
    (outside / "file.txt").write_text("FILE")
    for d in ("a/b", "locked/inner", "go/pkg/mod/example.org/x@v1.0.0/sub", ".config/app"):
        (home / d).mkdir(parents=True)
    for f in ("a/b/f", "locked/inner/f", "go/pkg/mod/example.org/x@v1.0.0/x.go", "go/pkg/mod/example.org/x@v1.0.0/sub/y.go", ".config/app/token"):
        (home / f).write_text("x")
        (home / f).chmod(0o444)
    (home / "to-folder").symlink_to(outside / "kept")
    (home / "locked" / "inner" / "to-file").symlink_to(outside / "file.txt")
    (home / "a" / "b" / "to-folder").symlink_to(outside / "kept")
    (outside / "kept").chmod(0o500)
    (outside / "file.txt").chmod(0o400)
    for d in ("go/pkg/mod/example.org/x@v1.0.0/sub", "go/pkg/mod/example.org/x@v1.0.0", "go/pkg/mod", "locked/inner", "locked"):
        (home / d).chmod(0o500)
    (home / "a").chmod(0o000)


def test_a_private_home_with_folders_no_one_may_open_or_change_is_removed_whole_and_nothing_outside_it(tmp_path, monkeypatch):
    monkeypatch.setattr(sb, "sandboxes_root", lambda: str(tmp_path / "sandboxes"))
    home, outside = type(tmp_path)(sb.sandbox_home("demo")), tmp_path / "users"
    _a_home_its_app_made_hard_to_remove(home, outside)
    sb.record_home_owner("demo", "https://example.org/demo")
    sb.write_flatpak_info("demo")
    try:
        assert sb.remove_sandbox_home("demo") is True
        assert not os.path.lexists(home) and not os.path.lexists(sb.home_owner_path("demo")) and not os.path.lexists(sb.identity_path("demo"))
        # a link in the home was removed as a link: what it led to is as it was, its mode too
        assert os.stat(outside / "kept").st_mode & 0o777 == 0o500 and os.stat(outside / "file.txt").st_mode & 0o777 == 0o400
        assert os.listdir(outside / "kept") == ["notes.txt"] and (outside / "file.txt").read_text() == "FILE"
        assert sb.remove_sandbox_home("demo") is True                      # no home: nothing to do, and that is gone too
    finally:                                                               # for pytest's own cleanup, whatever was left
        for d in (outside / "kept", home / "a", home / "locked", home / "locked" / "inner", home / "go" / "pkg" / "mod",
                  home / "go" / "pkg" / "mod" / "example.org" / "x@v1.0.0", home / "go" / "pkg" / "mod" / "example.org" / "x@v1.0.0" / "sub"):
            if d.is_dir() and not d.is_symlink():
                d.chmod(0o700)


def test_a_private_home_that_cannot_be_removed_whole_stays_its_apps_and_the_uninstall_says_so(tmp_path, monkeypatch, caplog):
    import json as _json
    from appkata_core import install
    from appkata_core.db import DB, now
    monkeypatch.setattr(sb, "sandboxes_root", lambda: str(tmp_path / "sandboxes"))
    monkeypatch.setattr(install, "OS", "linux")
    url, other = "https://example.org/alice/notes", "https://example.org/bob/notes"
    home = type(tmp_path)(sb.sandbox_home("notes"))
    (home / "data" / "deep").mkdir(parents=True)
    for f in ("data/deep/immutable.dat", "data/deep/plain.dat", "settings.ini"):
        (home / f).write_text("x")
    sb.record_home_owner("notes", url)
    sb.write_flatpak_info("notes")
    db = DB(str(tmp_path / "a.db"))
    rec = {"id": "notes", "files": [], "links": []}
    db.x("INSERT INTO installs(url, name, version, kind, record, installed_at) VALUES(?,?,?,?,?,?)", (url, "Notes", "1", "tarball", _json.dumps(rec), now()))
    # a file its owner can't remove whatever the folders' modes (an immutable one, `chattr +i`, which
    # no test can make as an ordinary user): the removal of that one file is refused
    unlink = os.unlink

    def refusing(path, *args, **kwargs):
        if os.path.basename(os.fspath(path)) == "immutable.dat":
            raise PermissionError(1, "Operation not permitted", os.fspath(path))
        return unlink(path, *args, **kwargs)

    monkeypatch.setattr(os, "unlink", refusing)
    assert install.uninstall(db, url, remove_sandbox=True) == [str(home)]                  # the uninstall's result names the home
    assert db.one("SELECT 1 FROM installs WHERE url=?", (url,)) is None                  # the app itself is gone
    assert sorted(os.path.join(d, f)[len(str(home)) + 1:] for d, _, fs in os.walk(home) for f in fs) == ["data/deep/immutable.dat"]
    assert not os.path.lexists(sb.identity_path("notes"))                                 # the marker went with the launcher, as ever
    assert [r.getMessage() for r in caplog.records if r.name == "appkata.sandbox"] == [
        f"couldn't remove the private home {home} whole: it stays, with its owner record"]
    # what is left is still that app's (R17.6): its own again when it is installed again, and no other's
    with open(sb.home_owner_path("notes")) as f:
        assert f.read().strip() == url
    assert not sb.home_belongs_to_another("notes", url) and sb.home_belongs_to_another("notes", other)
    assert install.new_app_id(db, url, "Notes") == "notes" and install.new_app_id(db, other, "Notes") == "notes-2"
    # once it can be removed, it is, and the id is free
    monkeypatch.setattr(os, "unlink", unlink)
    assert sb.remove_sandbox_home("notes") is True and not os.path.lexists(home) and not os.path.lexists(sb.home_owner_path("notes"))
    assert install.new_app_id(db, other, "Notes") == "notes"


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


# ---------------------------------------------------------------- the session warning (R17.9)

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
    ("unix:guid=0123,abstract=/tmp/dbus-AbCdEf", True),                   # in any place among its keys (PR #694's review, P4-B1b)
    ("unix:abstr%61ct=/tmp/dbus-AbCdEf,guid=0123", True),                 # its name unescaped, as GIO reads it (P6-1)
    ("unix:ABSTR%41CT=/tmp/dbus-AbCdEf", False),                          # ...and matched exactly: GIO connects to none
    (" unix:abstract=/tmp/dbus-AbCdEf", False),                           # ...and as the clients read an entry: none takes this one
    ("", False),
])
def test_the_bus_warning_is_said_only_for_an_abstract_session_bus(monkeypatch, addr, warns):
    # Review 3, R3-8: with the network grant an app reaches every abstract socket on the host, and an
    # abstract session bus is reached past the filtering proxy (R17.9, R17.5)
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


# ---------------------------------------------------------------- rewriting a launcher that is running (R17.4)

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


# ---------------------------------------------------------------- what a review may do on its own (R17.3, review 2 F8)

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
           "~/.password-store", "~/.local/share/keyrings", "~/.var",
           # CR1.5-8 (#383): a profile in each Chromium-family data folder, the Firefox forks, Tor
           # Browser, Evolution's two folders and GNOME Online Accounts' sign-ins
           "~/.config/google-chrome/Default", "~/.config/google-chrome/Profile 1", "~/.config/google-chrome/Default/Login Data",
           "~/.config/google-chrome-beta/Default", "~/.config/google-chrome-unstable/Default", "~/.config/chromium/Default",
           "~/.config/BraveSoftware/Brave-Browser/Default", "~/.config/microsoft-edge/Default", "~/.config/vivaldi/Default",
           "~/.config/opera/Cookies", "~/.config/mozilla/firefox", "~/.config/mozilla/firefox/abc.default-release",
           "~/.librewolf", "~/.librewolf/abc.default-default", "~/.waterfox", "~/.floorp", "~/.zen/abc.Default (release)",
           "~/.local/share/torbrowser", "~/.config/evolution", "~/.config/evolution/sources", "~/.local/share/evolution",
           "~/.local/share/evolution/mail", "~/.config/goa-1.0", "~/.config/goa-1.0/accounts.conf"]


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
    for p in ("~/Documents", "~/Projects/x", "~/.config/obsidian", "/media/usb", "~/.mozilla-backup", "~/.config/google-chrome-backup",
              "~/.config/chromium-flags.conf", "~/.config/evolution-data", "~/.librewolf.tar", "~/.local/share/evolution-backup"):
        assert not sb.secret_folder(p), p


# CR1.5-8 (#383): R17.3.1 says browsers' and mail clients' profiles are secrets, and the list had
# Firefox and Thunderbird. A Chromium-family profile lies beside the browser's NativeMessagingHosts
# folder, which is what made the data folder itself "never shared", so the profile was in neither
# list: a review's line granted it with no warning. How it slipped past: the secrets were tested on
# their members, and the one test that named a profile held it as grantable ("a sibling"). The
# family's eight data folders: the top is never shared whoever asks, and that answer comes first;
# what is in it is a secret, which a review is refused and the user is warned of.
CHROMIUM_FAMILY = ["~/.config/chromium", "~/.config/google-chrome", "~/.config/google-chrome-beta", "~/.config/google-chrome-unstable",
                   "~/.config/BraveSoftware/Brave-Browser", "~/.config/microsoft-edge", "~/.config/vivaldi", "~/.config/opera"]


@pytest.mark.parametrize("top", CHROMIUM_FAMILY)
def test_a_chromium_data_folder_is_never_shared_at_its_top_and_what_is_in_it_is_a_secret(top, a_users_home):
    profile, hosts, above = top + "/Default", top + "/NativeMessagingHosts", "a folder above programs browser extensions may start"
    assert sb.protected_folder(top) == above and sb.protected_folder(hosts) == "programs browser extensions may start"
    assert sb.protected_folder(profile) == "" and sb.secret_folder(profile) == sb.secret_folder(top) == "a browser's profiles and saved logins"
    # the finding's own road: a review's line, as the backend resolves it (choose, then strip_secrets)
    cfg = sb.config_from_review({"sandbox": "standard", "sandboxFolders": f"{profile}:ro, {top}:ro, ~/Notes"})
    source, gs, _ = sb.choose(None, None, [cfg], {"template": "strict"})
    kept, refused = sb.strip_secrets(gs)
    assert source == "reviews" and set(kept["folders"]) == {"~/Notes"}
    assert refused == [(p, "a review can't grant a browser's profiles and saved logins") for p in sorted([top, profile])]
    chips = sb.summary(kept) + [c[0] for c in sb.refused_chips(refused)]
    assert f"{profile} · refused: a review can't grant a browser's profiles and saved logins" in chips and "~/Notes" in chips
    text = sb.build_launcher("app", "App", "/home/kata/bin/apps/app/1", "bin/app", kept, apps_root="/home/kata/bin/apps")
    assert os.path.expanduser(profile) not in text and f"bind-try {os.path.expanduser(top)}" not in text
    # the user's own pick: the top is refused as never shared, said first; the profile is theirs to give, with the warning
    mine = sb.apply_overrides(sb.resolve_template("standard"), {"folders": {"+" + top: "ro", "+" + profile: "ro"}})
    chips = sb.summary(mine)
    assert f"{top} · refused: {above}" in chips and f"{profile} · read-only · holds passwords or tokens" in chips
    kept, refused = sb.strip_protected(mine)
    assert set(kept["folders"]) == {profile} and refused == [(top, above)]
    text = sb.build_launcher("app", "App", "/home/kata/bin/apps/app/1", "bin/app", mine, apps_root="/home/kata/bin/apps")
    full = os.path.expanduser(profile)
    assert f"--ro-bind-try {shlex.quote(full)} {shlex.quote(full)} " in text and f"# Refused folder grant {top}: {above} (R17.3.1)." in text


def test_the_user_folders_are_this_systems_own_names_and_only_those_that_exist(tmp_path, monkeypatch):
    # Review 2, F10 (A1.12.4): one-click Documents, Downloads, Pictures, Videos and Music, under the
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
    # Review 2's nit: R17.11 said the UI tells the app "may be partly non-functional until reviewed"; the
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
