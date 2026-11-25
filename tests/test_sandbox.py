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
              proxy_at="/usr/bin/xdg-dbus-proxy", app=True, hide=(), forward=None, args=(), before=None):
    """A generated launcher run in a session whose bus is at `address` ({rt}: the runtime folder;
    None: no address set), for `template` or the grant set `gs`, from `cwd` (the home folder when
    None), with `tools` ({name: script}) first on its PATH: the words of the proxy's own bwrap (None
    where no proxy was started), the app's bwrap's (None where `app` is False and it didn't run),
    the run, and the runtime folder. The xdg-dbus-proxy its PATH finds is a stand-in that is
    really at `proxy_at` (None: no stand-in), as `readlink -f` tells the launcher (no machine's /usr
    is a test's). The
    rest of its PATH is this one's, without the programs `hide` names: a machine that lacks them.
    `forward`: the file-argument helper the launcher calls, and `args` its arguments. `before`, where
    given, is called once the launcher is written and before it runs."""
    home, rt, fake, log = tmp_path / "home", tmp_path / "run", tmp_path / "fakebin", tmp_path / "bwrap-words"
    for d in (home, rt, fake):
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
    lp = tmp_path / "launcher"
    lp.write_text(sb.build_launcher("demo", "Demo", str(home / "apps/demo/1"), "bin/demo", gs or sb.resolve_template(template),
                                    seccomp=str(fake / "record.py"), forward=forward))   # any file there is: nothing here reads it as a filter
    if before:
        before()
    path = os.environ["PATH"]
    if hide:
        bare = tmp_path / "bare"
        bare.mkdir()
        for d in path.split(os.pathsep):
            for f in sorted(os.listdir(d)) if os.path.isdir(d) else ():
                if f not in hide and not os.path.lexists(bare / f):
                    (bare / f).symlink_to(os.path.join(d, f))
        path = str(bare)
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
        [(str(folder), "a folder above the session bus's socket")]
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
    for address in ("unix:path=" + sock.replace("/", "%2F"), f"unix:path={sock}%00zz", f"unix:path={tmp_path}/first,path={sock}"):
        monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", address)
        assert sock in sb.bus_files()[0] and sb.bus_files()[1], address
        assert sb.protected_folder(str(folder)) == "a folder above the session bus's socket" and sb.protected_folder(beside) == "", address
        assert sb.strip_protected(gs)[1] == [(str(folder), "a folder above the session bus's socket")], address
        assert f"# Refused folder grant {folder}: a folder above" in sb.build_launcher("demo", "Demo", "/apps/demo/1", "bin/demo", gs)
    # a path that isn't absolute, a broken escape, a newline: the file could be anywhere
    for address in ("unix:path=relative/bus", "unix:path=/tmp/dbus-%zz", "unix:path=/tmp/dbus-%2", "unix:path=/tmp/a%0Ab",
                    "unix:path=%00/tmp/x", "unix:path=", f"unix:abstract=/tmp/x;unix:path={sock},path=bus"):
        monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", address)
        assert sb.protected_folder(beside) == ("a folder the session bus's socket could be in (its address names a file AppKata "
                                               "can't read)") and sb.protected_folder("$cwd") == "", address   # $cwd: the launcher's own rule
        assert not sb.bus_files()[1] and sb.protected_folder("~") == "your whole home folder", address       # a reason of its own stays its own
        assert sorted(p for p, _ in sb.strip_protected(gs)[1]) == sorted([str(folder), beside]), address
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
    sock, path = _a_bus_socket(tmp_path / "tmp")
    run_in = os.path.realpath(path.parent if where == "the socket's folder" else path.parent / "project")
    os.makedirs(run_in, exist_ok=True)
    proxy, app, r, rt = _launched(tmp_path, monkeypatch, _bus_form(form, path), template="cli-tool", cwd=run_in)
    sock.close()
    assert (proxy is not None) is (form in ("plain", "guid first", "a link to it")) and r.returncode == 0, (r.stdout, r.stderr)   # the proxy takes those (R17.5)
    if where == "the socket's folder":
        assert run_in not in _binds(app) and app[app.index("--chdir") + 1] == str(tmp_path / "home"), app
        assert f"Demo runs sandboxed and can't see {run_in}" in r.stderr and "one that holds the session bus" in r.stderr, r.stderr
    else:
        assert _binds(app)[run_in] == ("--bind", run_in) and "can't see" not in r.stderr, (app, r.stderr)


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
    folder, notes = tmp_path / "project", tmp_path / "notes.txt"
    sock, deep = _a_bus_socket(folder / "deep")
    other, single = _a_bus_socket(tmp_path / "sockets")
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
    assert (f"Demo runs sandboxed and can't see the folders it was given ({', '.join(sorted(granted))}): this session bus's address "
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
                  "abstract=/tmp/dbus-a%00b"]

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


# PR #694's review, P5-B1: the cover matched a socket file only *under* a granted path, so a grant of
# the socket file itself, or of a link to it (a "folder" grant binds a file as readily as a folder,
# R17.3.1), left the live socket in sight, where an address the launcher can't read has a granted
# socket file covered. How it slipped past: the cover's tests varied how the address names the
# socket (P2-1, P3-B4) and granted its folder alone; how the grant shows it never varied. Each way
# here: the grant → where the app sees the socket through it (None: it doesn't). A link is followed
# when the app starts, as bwrap follows it, so one pointed there after the launcher was written
# counts too.
GRANT_FORMS = {
    "its folder": "{tmp}/dbus-MZ8lHbtZ8K",
    "a folder above it": "{tmp}/dbus-MZ8lHbtZ8K",
    "the file itself": "{grant}",
    "a link to the file": "{grant}",
    "a link to its folder": "{grant}/dbus-MZ8lHbtZ8K",
    "a link pointed there later": "{grant}/dbus-MZ8lHbtZ8K",
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
    sock, path = _a_bus_socket(tmp_path / "up" / "tmp")
    (tmp_path / "links").mkdir()
    folder, then = _granted(grant, path, tmp_path / "links")
    shown = GRANT_FORMS[grant] and GRANT_FORMS[grant].format(tmp=path.parent, grant=folder)
    gs = sb.apply_overrides(sb.resolve_template("standard"), {"folders": {f"+{folder}": "rw"}})
    proxy, app, r, rt = _launched(tmp_path, monkeypatch, _bus_form(form, path), gs=gs, before=then)
    sock.close()
    assert r.returncode == 0 and "AppKata: the session bus here" not in r.stderr or proxy is None, (r.stdout, r.stderr)
    at = lambda *words: next((i for i in range(len(app)) if app[i:i + 3] == list(words)), None)   # noqa: E731
    covered = [app[i + 2] for i in range(len(app) - 2) if app[i:i + 2] == ["--ro-bind", "/dev/null"]]
    assert at("--bind-try", folder, folder) is not None, app                    # the grant stands
    assert covered == ([shown] if shown else []), (covered, shown)
    if shown:
        assert at("--ro-bind", "/dev/null", shown) > at("--bind-try", folder, folder)     # after the folder's own bind
    # where this session's bus is elsewhere, nothing is covered
    _, app, r, _ = _launched(tmp_path_factory.mktemp("again"), monkeypatch, None, gs=gs)
    assert "/dev/null" not in app and r.returncode == 0, (app, r.stderr)


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


# ---------------------------------------------------------------- AppArmor setup (R17.10)

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
    # ...each only where the launcher shows it, which it doesn't where the session bus's address names
    # a file it can't read (PR #694's review, P3-B4)
    assert f'python3 {helper} "$id" "$rt" "" ${{folders:+{fake_home}/Projects}} -- "$@"' in text
    assert text.index('folders=1; [ "${busok:-1}" = 1 ] || folders=') < text.index("forward-files.py")
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
