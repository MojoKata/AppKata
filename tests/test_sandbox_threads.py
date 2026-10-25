"""AppKata's own threads over the sandbox state (round five, "Coverage after round five").

The startup thread (the bwrap probe, the heal pass) and the UI thread (sandboxInfo, setSandbox,
installWith) share the database and the settings rows; nothing had ever run them at once. This
drives the heal pass on a thread under a loop of UI-thread calls and asks for no exception on
either side and a consistent row at the end.
"""

import json
import threading

import pytest

from appkata_core import sandbox as sb
from test_sandbox_backend import URL, _review, _tarball_install, be   # noqa: F401
from test_sandbox_transitions import sandboxed, snapshot               # noqa: F401


def test_the_heal_pass_and_the_ui_thread_can_overlap_without_an_error_or_a_torn_row(be, sandboxed, caplog):
    # Found on its first run: the heal pass and setSandbox both rewrite the app's links through
    # install._activate, and the two raced on the stable link ("File exists: '1.0' -> .../current");
    # the loser logged "couldn't regenerate the launcher" and skipped it. _activate is serialized now.
    import logging
    caplog.set_level(logging.WARNING, logger="appkata.gui")
    errors = []
    stop = threading.Event()

    def startup():
        try:
            for _ in range(40):
                be._heal_launchers_at_startup()
                if stop.is_set():
                    break
        except Exception as e:                      # noqa: BLE001
            errors.append(("startup", repr(e)))

    t = threading.Thread(target=startup)
    t.start()
    try:
        for i in range(60):
            be.sandboxInfo(URL)
            be.setSandbox(URL, {"template": "messenger" if i % 2 else "online-app", "overrides": {}})
            be.sandboxLaunchCommand(URL)
            be.keepSandbox(URL)
    except Exception as e:                          # noqa: BLE001
        errors.append(("ui", repr(e)))
    finally:
        stop.set()
        t.join(timeout=60)
    assert not t.is_alive() and errors == [], errors
    assert "couldn't regenerate" not in caplog.text, caplog.text         # no regeneration lost to the race
    info = be.sandboxInfo(URL)
    assert info["applicable"] and info["source"] == "user" and info["template"] == "messenger"   # the last choice (i = 59)
    row = be._install_settings(URL)
    assert row["sandbox"] == {"template": "messenger", "overrides": {}}
    rec = json.loads(be.db.one("SELECT record FROM installs WHERE url=?", (URL,))["record"])
    assert open(rec["launcher"]).read() == be.sandboxLaunchCommand(URL)
    # the heal thread may have regenerated from a choice it read just before the UI's last save;
    # one reconciliation at most, then the launcher on disk is today's text for the final choice
    be._heal_launchers()
    assert be._heal_launchers() == []
