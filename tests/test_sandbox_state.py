"""State written by yesterday's AppKata (round five, "Coverage after round five").

Every other test starts from a fresh database and tree. A release leaves rows and files behind --
the install record with its launcher path, the settings row with the pin, the launcher text, the
identity marker, the desktop entry, the helpers -- and the next AppKata must read them. Round
four's R4-1 (a poisoned row) and R4-4 (a stale launcher) were both this class.

`tests/data/state/<label>.json` is a frozen snapshot of an installed, reviewed, sandboxed app as
one version of AppKata left it: both rows and every file under the home, with the home folder
replaced by `$HOME`. Each test here thaws every snapshot into a fresh Backend and asks today's
code to live with it: read it, show it, bring its launcher up to date, change it, uninstall it.
Freeze a new one before a release: `UPDATE_STATE=<label> pytest tests/test_sandbox_state.py`.
"""

import base64
import glob
import json
import os

import pytest

from appkata_core import sandbox as sb
from test_sandbox_backend import URL, _review, _tarball_install, be   # noqa: F401
from test_sandbox_transitions import sandboxed                          # noqa: F401

STATE_DIR = os.path.join(os.path.dirname(__file__), "data", "state")
SKIP = ("appkata.db", "appkata.db-journal", "appkata.db-wal", "appkata.db-shm", ".log")


def freeze(be, home: str) -> dict:
    files = {}
    for d, _, names in os.walk(home):
        for n in names:
            p = os.path.join(d, n)
            if any(p.endswith(s) for s in SKIP):
                continue
            rel = os.path.relpath(p, home)
            if os.path.islink(p):
                files[rel] = {"link": os.readlink(p).replace(home, "$HOME")}
            else:
                with open(p, "rb") as f:
                    data = f.read()
                try:
                    files[rel] = {"text": data.decode().replace(home, "$HOME"), "mode": oct(os.stat(p).st_mode & 0o777)}
                except UnicodeDecodeError:
                    files[rel] = {"base64": base64.b64encode(data).decode(), "mode": oct(os.stat(p).st_mode & 0o777)}
    row = dict(be.db.one("SELECT url, name, version, kind, record FROM installs WHERE url=?", (URL,)))
    row["record"] = json.loads(row["record"].replace(home, "$HOME"))
    return {"installs": row, "app_settings": json.loads(json.dumps(be._install_settings(URL)).replace(home, "$HOME")),
            "files": files}


def thaw(be, home: str, state: dict) -> None:
    for rel, f in state["files"].items():
        p = os.path.join(home, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        if "link" in f:
            os.symlink(f["link"].replace("$HOME", home), p)
            continue
        data = f["text"].replace("$HOME", home).encode() if "text" in f else base64.b64decode(f["base64"])
        with open(p, "wb") as out:
            out.write(data)
        os.chmod(p, int(f["mode"], 8))
    row = state["installs"]
    from appkata_core.db import now
    be.db.x("INSERT OR REPLACE INTO installs(url, name, version, kind, record, installed_at) VALUES(?,?,?,?,?,?)",
            (row["url"], row["name"], row["version"], row["kind"], json.dumps(row["record"]).replace("$HOME", home), now()))
    be._set_install_settings(URL, json.loads(json.dumps(state["app_settings"]).replace("$HOME", home)))
    be._app = lambda url: {"url": URL, "name": row["name"], "installed": row["version"]}


def test_freeze_todays_state_when_asked(be, sandboxed):
    label = os.environ.get("UPDATE_STATE")
    if not label:
        pytest.skip("set UPDATE_STATE=<label> to freeze today's state as tests/data/state/<label>.json")
    be.keepSandbox(URL)
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(os.path.join(STATE_DIR, f"{label}.json"), "w") as f:
        json.dump(freeze(be, str(sandboxed)), f, indent=1, sort_keys=True)


SNAPSHOTS = sorted(glob.glob(os.path.join(STATE_DIR, "*.json")))


@pytest.fixture
def thawed(be, tmp_path, monkeypatch, request):
    monkeypatch.setattr(sb, "have_tools", lambda: True)
    monkeypatch.setattr(sb, "support_status", lambda: {"status": "ok"})
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / ".local" / "share"))
    _review(be, "online-app")
    with open(request.param) as f:
        thaw(be, str(tmp_path), json.load(f))
    return tmp_path


@pytest.mark.parametrize("thawed", SNAPSHOTS, indirect=True, ids=[os.path.basename(s)[:-5] for s in SNAPSHOTS])
def test_todays_appkata_reads_shows_heals_changes_and_removes_yesterdays_app(be, thawed):
    info = be.sandboxInfo(URL)
    assert info["applicable"] and info["active"] and info["source"] in ("pinned", "user") and info["level"] != "off", info
    assert be.sandboxLaunchCommand(URL).startswith("#!/bin/sh")
    rec = json.loads(be.db.one("SELECT record FROM installs WHERE url=?", (URL,))["record"])
    assert os.path.exists(rec["launcher"]) and os.path.exists(sb.identity_path("demo"))
    # the startup pass brings yesterday's launcher up to today's text, at most once
    healed = be._heal_launchers()
    assert healed in ([], [URL])
    assert be._heal_launchers() == []
    assert be.sandboxLaunchCommand(URL) == open(rec["launcher"]).read()
    # the user can still change it, and switch it off, and come back
    be.setSandbox(URL, {"template": "strict", "overrides": {}})
    assert be.sandboxInfo(URL)["level"] == "strict" and "xdg-dbus-proxy" not in be.sandboxLaunchCommand(URL)
    be.setSandbox(URL, {"template": "off"})
    assert not os.path.exists(rec["launcher"]) and not os.path.exists(sb.identity_path("demo"))
    be.setSandbox(URL, None)
    assert os.path.exists(rec["launcher"]) and be.sandboxInfo(URL)["source"] == "pinned"
    # and remove it, leaving only the private home
    be._uninstall(URL, False, remove_home=False)
    assert be.db.one("SELECT 1 FROM installs WHERE url=?", (URL,)) is None
    assert not os.path.exists(rec["launcher"]) and not os.path.exists(sb.identity_path("demo"))
