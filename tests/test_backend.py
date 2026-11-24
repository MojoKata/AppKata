"""The backend's own threads: what a worker hands back to the main thread gets there.

The backend does its slow work (a release's plan, a sync, an install) on Python threads and hands
the result to the main thread, where the screens and the catalog are. These tests run a real
Backend under a running event loop with real threads, as the application does: no test here patches
threading.Thread.start, since a worker run in line is already on the main thread and has nothing
to hand over.

How the class slipped past (CR1, #463): every backend test either called the step after the
hand-off itself (`_install`) or ran the worker in line, on the main thread, where a QTimer fires.
On a worker thread it never does: the thread has no Qt event loop, and ends."""

import ast
import glob
import json
import os
import threading

import pytest

import written

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


# ---------------------------------------------------------------- what follows a sync (R9.3, R10.6.5; CR1, #464)

def installed(be, version):
    be.db.x("INSERT INTO installs(url, name, version, date, asset, kind, record, installed_at) VALUES(?,?,?,?,?,?,?,?)",
            (URL, "Demo", version, "2026-01-01T00:00:00Z", APPIMAGE, "appimage", "{}", now()))
    be.reload()


def finds(monkeypatch, *found):
    """The next sync finds these: each a function of the database, as a sync writes what it fetched."""
    monkeypatch.setattr(sync, "sync_all", lambda db, http, progress=None, **k: [f(db) for f in found])


def a_newer_release(db):
    synced(db, release("1.1", APPIMAGE), release("1.0", APPIMAGE))


def a_veto_of_the_installed_version(db):
    tid = db.x("INSERT INTO trusts(url, name, own, verified_commit, score) VALUES(?,?,?,?,?)",
               ("https://example.org/trust", "Desk", 0, "abc", 3)).lastrowid
    said = {"_app": {"trust": 4}, "_versions": [{"v": "1.0", "text": "Backdoored.", "details": [], "opts": {}, "verdict": {"trust": 0}}]}
    db.x("INSERT INTO reviews(trust_id, url, app, source, tags, trust, rating, section, settings) VALUES(?,?,?,?,?,?,?,?,?)",
         (tid, URL, "Demo", URL, "[]", 0, 4, "An editor.", json.dumps(said)))      # the table row is its newest review's


@pytest.fixture
def notes(be):
    """The system notifications the backend asks the tray to show: (on the main thread, title, text)."""
    got = []
    be.notify.connect(lambda title, text: got.append((on_main(), title, text)))
    return got


@pytest.fixture
def followed(be, monkeypatch):
    """One entry each time what a background check does after its sync has run."""
    ran, sync_now = [], be.syncNow
    monkeypatch.setattr(be, "syncNow", lambda after=None: sync_now(lambda: (after(), ran.append(on_main()))))
    return ran


def test_what_follows_a_sync_runs_on_the_main_thread_once_the_catalog_has_what_it_found(be, monkeypatch):
    source(be, release("1.0", APPIMAGE))
    finds(monkeypatch, a_newer_release)
    seen = []
    be.syncNow(lambda: seen.append((on_main(), be.syncing, be._app(URL)["version"])))
    assert wait(lambda: seen), "what was to follow the sync never ran"
    assert not wait(lambda: len(seen) > 1, 0.2)
    assert seen == [(True, False, "1.1")]


def test_a_sync_with_nothing_to_follow_it_still_shows_what_it_found(be, monkeypatch):
    source(be, release("1.0", APPIMAGE))
    finds(monkeypatch, a_newer_release)
    be.sync()
    assert wait(lambda: be._app(URL)["version"] == "1.1") and not be.syncing


def test_a_background_check_that_finds_an_update_shows_a_notification(be, notes, monkeypatch):
    source(be, release("1.0", APPIMAGE))
    installed(be, "1.0")
    finds(monkeypatch, a_newer_release)
    assert be.updateCount == 0
    be._background_sync()
    assert wait(lambda: notes), "new updates were found and no notification was shown"
    assert notes == [(True, "1 app update available", "Demo")]


def test_a_background_check_that_newly_vetoes_the_installed_version_shows_a_notification(be, notes, monkeypatch):
    source(be, release("1.0", APPIMAGE))
    installed(be, "1.0")
    finds(monkeypatch, a_veto_of_the_installed_version)
    be._background_sync()
    assert wait(lambda: notes), "the installed version was newly vetoed and no notification was shown"
    assert notes == [(True, "A trusted reviewer says to avoid Demo 1.0", "Backdoored.")]


@pytest.mark.parametrize("on, found", [(False, (a_newer_release, a_veto_of_the_installed_version)), (True, ())],
                         ids=["notifications-off", "nothing-new"])
def test_a_background_check_shows_no_notification_when_they_are_off_or_nothing_is_new(be, notes, followed, monkeypatch, on, found):
    source(be, release("1.0", APPIMAGE))
    installed(be, "1.0")
    be._prefs["notifications"] = on
    finds(monkeypatch, *found)
    be._background_sync()
    assert wait(lambda: followed), "what follows a background check's sync never ran"
    assert followed == [True] and notes == []
    assert be.updateCount == len(found) // 2 and bool(be._app(URL)["installedVetoed"]) == bool(found)   # the sync did find them


# ---------------------------------------------------------------- the class: every hand-off from a worker

def worker_timers(text):
    """Each Qt timer a module's worker threads would make, as "line N: <the call>". A worker's code
    is what a threading.Thread is given as its target (a lambda, the module's functions of that
    name, or a method named on `self`), and every method that code calls on `self`, and so on. A
    timer belongs to the thread that makes it and needs that thread's event loop, which a Python
    thread doesn't have: what a worker hands to the main thread goes by a signal. A thread whose
    target can't be told is listed too."""
    tree = ast.parse(text)
    functions = [f for f in ast.walk(tree) if isinstance(f, ast.FunctionDef)]
    methods = {f.name: f for c in ast.walk(tree) if isinstance(c, ast.ClassDef)
               for f in c.body if isinstance(f, ast.FunctionDef)}
    todo, unknown = [], []
    for call in [n for n in ast.walk(tree) if isinstance(n, ast.Call) and ast.unparse(n.func) in ("threading.Thread", "Thread")]:
        target = next((k.value for k in call.keywords if k.arg == "target"), call.args[1] if len(call.args) > 1 else None)
        runs = []
        if isinstance(target, ast.Lambda):
            runs = [target]
        elif isinstance(target, ast.Name):
            runs = [f for f in functions if f.name == target.id]
        elif isinstance(target, ast.Attribute) and ast.unparse(target.value) == "self":
            runs = [methods[target.attr]] if target.attr in methods else []
        if not runs:
            unknown.append(f"line {call.lineno}: what does this thread run? {ast.unparse(call)}")
        todo += runs
    seen, found = [], []
    while todo:
        code = todo.pop()
        if code in seen:
            continue
        seen.append(code)
        for call in [n for n in ast.walk(code) if isinstance(n, ast.Call)]:
            name = ast.unparse(call.func)
            if name.split(".")[0] == "QTimer":
                found.append(f"line {call.lineno}: {ast.unparse(call)}")
            elif name.startswith("self.") and name[5:] in methods:
                todo.append(methods[name[5:]])
    return sorted(set(found), key=lambda line: int(line.split()[1].rstrip(":"))) + unknown


def test_a_worker_threads_timer_is_found_however_the_thread_reaches_it():
    assert worker_timers('''
class Backend:
    def install(self, url):
        def work():
            QTimer.singleShot(0, lambda: self._install(url))
        threading.Thread(target=work, daemon=True).start()
        QTimer.singleShot(0, self.reload)

    def start(self):
        threading.Thread(target=self._heal, name="heal").start()
        threading.Thread(target=lambda: self._later()).start()

    def _heal(self):
        self._later()

    def _later(self):
        self._timer = QTimer(self)

    def _arm(self):
        QTimer.singleShot(5, self.start)
''') == ["line 5: QTimer.singleShot(0, lambda: self._install(url))", "line 17: QTimer(self)"]
    assert worker_timers("def f(g):\n    threading.Thread(target=g).start()\n") == [
        "line 2: what does this thread run? threading.Thread(target=g)"]


def test_no_worker_thread_of_the_application_makes_a_timer():
    # CR1, #463 and #464: three hand-offs were QTimer.singleShot calls on a worker thread, and none ever ran
    found = {}
    for path in sorted(glob.glob(written.path("src/appkata/*.py"))):
        with open(path, encoding="utf-8") as f:
            timers = worker_timers(f.read())
        if timers:
            found[os.path.basename(path)] = timers
    assert found == {}
