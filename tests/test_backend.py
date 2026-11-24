"""The backend's own threads: what a worker hands back to the main thread gets there.

The backend does its slow work (a release's plan, a sync, an install) on Python threads and hands
the result to the main thread, where the screens and the catalog are. These tests run a real
Backend under a running event loop with real threads, as the application does: no test here patches
threading.Thread.start, since a worker run in line is already on the main thread and has nothing
to hand over.

How the class slipped past (CR1, #463): every backend test either called the step after the
hand-off itself (`_install`) or ran the worker in line, on the main thread, where a QTimer fires.
On a worker thread it never does: the thread has no Qt event loop, and ends."""

import json
import threading

import pytest

pytest.importorskip("PySide6")

from appkata_core import foreign, sandbox, sync      # noqa: E402
from appkata_core.db import now                      # noqa: E402

URL = "https://github.com/example/demo"
APPIMAGE = "demo-1.0-x86_64.AppImage"


def release(version, *files):
    """A release as a sync stores it, with these files."""
    return {"tag": "v" + version, "name": version, "version": version, "date": "2026-01-01T00:00:00Z", "prerelease": False,
            "notes": "", "html_url": f"{URL}/releases/v{version}",
            "assets": [{"name": f, "url": f"{URL}/releases/download/v{version}/{f}", "size": 1, "digest": "", "content_type": ""}
                       for f in files]}


def synced(db, *releases):
    """What a sync of the Demo app leaves in the database."""
    db.x("INSERT OR REPLACE INTO apps(url, name, releases) VALUES(?,?,?)", (URL, "Demo", json.dumps(list(releases))))


@pytest.fixture
def be(tmp_path, monkeypatch):
    """A real Backend on a database of its own, its workers on real threads. Nothing reaches the
    network or this machine's sandbox: a test stubs the sync it starts, and the releases' files are
    already in the database. A worker that raises fails the test."""
    monkeypatch.setenv("HOME", str(tmp_path))
    for v in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME"):
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    monkeypatch.setattr(sandbox, "have_tools", lambda: False)          # no "Set up the sandbox?" from this machine
    monkeypatch.setattr(foreign, "scan", lambda db: None)              # nor its installed programs
    raised = []
    monkeypatch.setattr(threading, "excepthook", lambda a: raised.append(f"{a.thread.name}: {a.exc_type.__name__}: {a.exc_value}"))
    before = set(threading.enumerate())
    from appkata.backend import Backend
    b = Backend(db_path=str(tmp_path / "appkata.db"), heal=False)
    yield b
    b._timer.stop()
    for t in set(threading.enumerate()) - before:                      # no worker outlives its database
        t.join(timeout=10)
    assert raised == []


def source(be, *releases):
    """The Demo app as a Source that has been synced."""
    be.db.x("INSERT INTO sources(url, settings, added_at) VALUES(?,?,?)", (URL, "{}", now()))
    synced(be.db, *releases)
    be.reload()


def wait(done, seconds=5.0):
    """Run the event loop until done() holds, for `seconds` at most. Returns whether it held."""
    from PySide6.QtCore import QEventLoop, QTimer
    loop = QEventLoop()
    poll = QTimer()
    poll.timeout.connect(lambda: done() and loop.quit())
    poll.start(5)
    QTimer.singleShot(int(seconds * 1000), loop.quit)
    loop.exec()
    poll.stop()
    return bool(done())


def on_main():
    return threading.current_thread() is threading.main_thread()


@pytest.fixture
def installs(be, monkeypatch):
    """Every call of the backend's `_install`, the step that queues an install: (on the main thread, its arguments)."""
    got = []
    monkeypatch.setattr(be, "_install", lambda *a, **k: got.append((on_main(), a)))
    return got


# ---------------------------------------------------------------- a first install (R4.9.1; CR1, #463)

def test_a_first_install_with_nothing_to_ask_starts(be, installs):
    source(be, release("1.0", APPIMAGE))
    plan = be._plan(URL, "1.0")
    assert not plan["ask"] and not plan.get("error") and [c["name"] for c in plan["candidates"]] == [APPIMAGE]
    be.install(URL)
    assert wait(lambda: installs), "Install with no dialog to show never reached _install"
    assert not wait(lambda: len(installs) > 1, 0.2)
    assert installs == [(True, (URL, "", plan["candidates"][0]))]      # once, on the main thread, with the plan's file


def test_a_first_install_with_no_download_for_this_computer_says_so(be):
    source(be, release("1.0", "demo-1.0.dmg"))
    assert "no download for" in be._plan(URL, "1.0")["error"]
    toasts = []
    be.toast.connect(lambda kind, text: toasts.append((on_main(), kind, text)))
    be.install(URL)
    assert wait(lambda: toasts), "an install with no download for this computer said nothing"
    assert toasts == [(True, "error", "Demo: no download for this computer in 1.0")]
    assert wait(lambda: not be.busy)


# ---------------------------------------------------------------- Add and install (R7.2; CR1, #463)

def test_add_and_install_installs_once_the_source_is_synced(be, installs, monkeypatch):
    monkeypatch.setattr(sync, "sync_app", lambda db, http, url: synced(db, release("1.0", APPIMAGE)))
    be.addSourceWith(URL, True, {})
    assert wait(lambda: installs), "Add and install added the Source and never installed"
    assert not wait(lambda: len(installs) > 1, 0.2)
    assert [(main, a[:2], a[2]["name"]) for main, a in installs] == [(True, (URL, ""), APPIMAGE)]
    assert be._app(URL)["version"] == "1.0"


def test_add_alone_installs_nothing(be, installs, monkeypatch):
    monkeypatch.setattr(sync, "sync_app", lambda db, http, url: synced(db, release("1.0", APPIMAGE)))
    be.addSourceWith(URL, False, {})
    assert wait(lambda: (be._app(URL) or {}).get("version") == "1.0")
    assert not wait(lambda: installs, 0.3)
