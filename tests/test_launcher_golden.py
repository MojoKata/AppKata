"""The generated launcher, byte for byte, for a few representative grant sets (requirement 17.4).

The launcher's text is the enforcement, and every change to it is a change to what every
sandboxed app may do -- yet a change to build_launcher shows in review only as Python, with the
shell it produces nowhere in the diff. These goldens put the shell in the diff: a change to the
launcher fails here with the exact lines that changed, and is accepted deliberately by
regenerating the files (UPDATE_GOLDEN=1 pytest tests/test_launcher_golden.py) in the same commit,
where the reviewer sees them. The startup pass (install.launcher_is_current, round four R4-4)
then carries exactly that change to every installed app, which the last test ties together.
"""

import difflib
import os
import subprocess

import sys

import pytest

from appkata_core import install, sandbox as sb

pytestmark = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="the sandbox and its launchers are Linux-only (17.1)")

GOLDEN = os.path.join(os.path.dirname(__file__), "data", "launchers")
HOME = "/home/kata"
APPS = f"{HOME}/bin/apps"

CASES = {
    "strict-tarball": dict(gs=sb.resolve_template("strict"), appimage=None),
    "online-app-appimage-with-folders": dict(
        gs=sb.apply_overrides(sb.resolve_template("online-app"), {"folders": {"+~/Projects": "rw", "+~/Media": "ro", "+~/.ssh": "rw"}}),
        appimage=f"{APPS}/app/App-1.0.AppImage"),
    "messenger-camera": dict(gs=sb.resolve_template("messenger"), appimage=None),
    "cli-tool": dict(gs=sb.resolve_template("cli-tool"), appimage=None),
    "standard-writable-no-x11": dict(gs=sb.apply_overrides(sb.resolve_template("standard"), {"write_app": True, "devices": []}), appimage=None),
    "developer-every-capability": dict(gs=sb.apply_overrides(sb.resolve_template("developer"), {"caps": sorted(sb.CAP_LABELS), "sound": ["play", "record"]}), appimage=None),
}


@pytest.fixture
def fixed_host(monkeypatch):
    """The same host for every run: the launcher embeds the home, the runtime dir, the log path and
    the helper paths, the seccomp filter exists only on some machines, and whether an app's own
    sandbox can run inside, and whether xdg-dbus-proxy is here, are facts of the host too (17.10.2,
    17.10; pinned to the common case)."""
    monkeypatch.setattr(sb, "nested_userns_works", lambda refresh=False: True)
    monkeypatch.setattr(sb, "have_bus_filter", lambda: True)          # xdg-dbus-proxy is here (17.10)
    monkeypatch.setenv("HOME", HOME)
    monkeypatch.setenv("XDG_RUNTIME_DIR", "/run/user/1000")
    for v in ("XDG_DATA_HOME", "XDG_STATE_HOME", "APPKATA_APPS", "APPKATA_DATA", "APPKATA_LOG_DIR"):
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setattr(sb, "sandboxes_root", lambda: f"{HOME}/.local/share/appkata/sandboxes")
    monkeypatch.setattr(sb, "seccomp_filter", lambda machine=None: b"\0")


def _text(name):
    case = CASES[name]
    appdir = f"{APPS}/app/1.0.extracted" if case["appimage"] else f"{APPS}/app/1.0"
    exec_rel = "AppRun" if case["appimage"] else "bin/app"
    return sb.launcher_text("app", "App", APPS, appdir, exec_rel, case["gs"], case["appimage"])


@pytest.mark.parametrize("name", list(CASES))
def test_the_launcher_matches_its_golden(fixed_host, name):
    path = os.path.join(GOLDEN, name + ".sh")
    text = _text(name)
    if os.environ.get("UPDATE_GOLDEN"):
        os.makedirs(GOLDEN, exist_ok=True)
        with open(path, "w") as f:
            f.write(text)
    assert os.path.exists(path), f"no golden yet: UPDATE_GOLDEN=1 pytest {__file__}"
    with open(path) as f:
        want = f.read()
    if text != want:
        diff = "".join(difflib.unified_diff(want.splitlines(True), text.splitlines(True), f"tests/data/launchers/{name}.sh", "generated now"))
        pytest.fail("the launcher changed; if that is intended, regenerate the goldens in this commit "
                    f"(UPDATE_GOLDEN=1 pytest tests/test_launcher_golden.py) and review the diff:\n{diff}")
    assert subprocess.run(["sh", "-n"], input=text, text=True, capture_output=True).returncode == 0


def test_the_startup_pass_treats_the_golden_as_current_and_anything_else_as_stale(fixed_host, tmp_path, monkeypatch):
    # the golden is what AppKata writes today; a launcher that matches it is left alone, one that
    # differs by a byte is rewritten at the next start (R4-4) -- so a golden diff is also the list
    # of apps the next start will touch. The files it calls by path have their own check (review 2,
    # F5, test_the_startup_pass_restores_every_file_the_launcher_relies_on); this one is the text's.
    monkeypatch.setattr(sb, "helpers_current", lambda app_id, gs: True)
    name = "online-app-appimage-with-folders"
    lp = tmp_path / "run"
    lp.write_text(_text(name))
    rec = {"launcher": str(lp), "target": f"{APPS}/app",
           "current": {"version": "1.0", "path": CASES[name]["appimage"], "exec": "App-1.0.AppImage"}}
    app = {"name": "App", "sandbox": sb.to_json(CASES[name]["gs"])}
    port = install.Portable(folder=APPS)
    assert install.launcher_is_current(rec, app, port)
    lp.write_text(lp.read_text().replace("--share-net", ""))
    assert not install.launcher_is_current(rec, app, port)
