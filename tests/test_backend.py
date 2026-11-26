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
import io
import json
import os
import threading
import time
import types
from http.client import IncompleteRead, InvalidURL

import pytest

import written

pytest.importorskip("PySide6")

from appkata_core import audit, channels, foreign, sandbox, sync      # noqa: E402
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

TIMERS = {"QTimer", "singleShot", "startTimer"}                     # Qt's names for a timer and for starting one
# threads the reader doesn't follow: a module that starts one may name no timer at all
OTHER_THREADS = {"ThreadPoolExecutor", "Timer", "QThread", "QThreadPool", "QRunnable", "start_new_thread"}


def named(node, names):
    """Each name, attribute or import under `node` that is one of `names`, however it is reached (`QTimer`, `QtCore.QTimer`)."""
    def said(n):
        return {n.id} if isinstance(n, ast.Name) else {n.attr} if isinstance(n, ast.Attribute) else \
            {n.name.split(".")[-1], n.asname} if isinstance(n, ast.alias) else set()
    return [n for n in ast.walk(node) if said(n) & names]


def unread_threads(tree):
    """A module's names for the threads the reader doesn't follow: the kinds of OTHER_THREADS, and
    any kind it imports by another name (`Thread as T`)."""
    return OTHER_THREADS | {a.asname for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))
                            for a in n.names if a.asname and a.name.split(".")[-1] in {"Thread"} | OTHER_THREADS}


def timer_names(tree):
    """What a module calls a timer: Qt's names, each other name it imports one by (`QTimer as Later`)
    and each attribute of `self` it keeps one in (`self._timer = QTimer(self)`)."""
    names = TIMERS | {a.asname for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))
                      for a in n.names if a.asname and a.name.split(".")[-1] in TIMERS}
    kept = {t.attr for n in ast.walk(tree) if isinstance(n, ast.Assign) and named(n.value, names)
            for t in n.targets if isinstance(t, ast.Attribute) and ast.unparse(t.value) == "self"}
    return names | kept


def worker_timers(text):
    """Each Qt timer a module's worker threads come to, as "line N: <the call>". A timer belongs to
    the thread that makes it and needs that thread's event loop, which a Python thread doesn't have:
    what a worker hands to the main thread goes by a signal.

    A worker's code is what a threading.Thread is given as its target, and all that code names in
    its module, and so on: a function or a lambda defined in the same method (called there, or
    handed to other code as a callback), a function of the module, and a method or property of
    `self`. A timer is one however it is named (timer_names), called or not. A thread whose target
    can't be told is listed too. What the reader doesn't follow is a call out of the module:
    timers_within_reach holds the modules such a call can reach to no timer at all."""
    tree = ast.parse(text)
    timers = timer_names(tree)
    plain = {f.name: [f] for f in tree.body if isinstance(f, ast.FunctionDef)}
    top_of, beside, methods = {}, {}, {}           # by each function or method at the top of the module or of a class
    for owner in [tree] + [c for c in tree.body if isinstance(c, ast.ClassDef)]:
        own = {f.name: f for f in owner.body if isinstance(f, ast.FunctionDef)}
        for top in own.values():
            beside[top], methods[top] = {}, own if owner is not tree else {}
            for n in ast.walk(top):
                top_of[n] = top
                if isinstance(n, ast.FunctionDef) and n is not top:
                    beside[top].setdefault(n.name, []).append(n)
                elif isinstance(n, ast.Assign) and isinstance(n.value, ast.Lambda):
                    for t in [t for t in n.targets if isinstance(t, ast.Name)]:
                        beside[top].setdefault(t.id, []).append(n.value)

    def stands_for(node):
        """The module's code that the names under `node` stand for."""
        top, out = top_of.get(node), []
        for n in ast.walk(node):
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load):
                out += beside.get(top, {}).get(n.id) or plain.get(n.id) or []
            elif isinstance(n, ast.Attribute) and ast.unparse(n.value) == "self" and n.attr in methods.get(top, {}):
                out.append(methods[top][n.attr])
        return out

    todo, unknown = [], []
    for call in [n for n in ast.walk(tree) if isinstance(n, ast.Call) and ast.unparse(n.func).split(".")[-1] == "Thread"]:
        target = next((k.value for k in call.keywords if k.arg == "target"), call.args[1] if len(call.args) > 1 else None)
        runs = [target] if isinstance(target, ast.Lambda) else stands_for(target) if isinstance(target, (ast.Name, ast.Attribute)) else []
        if not runs:
            unknown.append(f"line {call.lineno}: what does this thread run? {ast.unparse(call)}")
        todo += runs
    seen, found = set(), set()
    while todo:
        code = todo.pop()
        if code in seen:
            continue
        seen.add(code)
        told = set()
        for n in ast.walk(code):                   # an outer node comes before what is in it
            call = isinstance(n, ast.Call) and named(n.func, timers)
            if call or (n not in told and named(n, timers)[:1] == [n]):
                found.add((n.lineno, ast.unparse(n)))
                told.update(ast.walk(n.func if call else n))
        todo += stands_for(code)
    return [f"line {line}: {what}" for line, what in sorted(found)] + unknown


def timers_within_reach(sources):
    """Each timer a worker thread of these modules could come to, as "<module>: line N: ...".
    `sources` is {a module's path under src/: its text}. In a module that starts threads it is what
    worker_timers finds there. The reader doesn't follow a call out of its module (`self.ch.cards()`,
    `install.install(...)`), so every module that one imports, itself or through another, may name
    no timer at all; and the same for the module itself where it starts threads of another kind."""
    trees = {path: ast.parse(text) for path, text in sources.items()}
    name = {path: path[:-3].replace("/", ".").removesuffix(".__init__") for path in sources}
    path_of = {dotted: path for path, dotted in name.items()}
    imports = {}
    for path, tree in trees.items():
        package = name[path] if path.endswith("/__init__.py") else name[path].rpartition(".")[0]
        got = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                got |= {a.name for a in n.names}
            elif isinstance(n, ast.ImportFrom):
                above = package.split(".")[:len(package.split(".")) - n.level + 1] if n.level else []      # `from . import x`
                base = ".".join(above + ([n.module] if n.module else []))
                got |= {base} | {f"{base}.{a.name}" for a in n.names}
        got |= {dotted[:i] for dotted in got for i, c in enumerate(dotted) if c == "."}        # a module's packages are imported with it
        imports[path] = {path_of[dotted] for dotted in got if dotted in path_of}
    out = []
    for path in sorted(p for p, tree in trees.items() if named(tree, {"Thread"} | unread_threads(tree))):
        out += [f"{path}: {timer}" for timer in worker_timers(sources[path])]
        reach, todo = set(), [path]
        while todo:
            for other in imports[todo.pop()] - reach - {path}:
                reach.add(other)
                todo.append(other)
        for other in sorted(reach | ({path} if named(trees[path], unread_threads(trees[path])) else set())):
            lines = sorted({n.lineno for n in named(trees[other], timer_names(trees[other]))})
            if lines:
                out.append(f"{other}: line {lines[0]}: a timer, in a module the threads of {path} can reach unread")
    return out


# A module in the backend's shape. A line marked "found" is a timer one of its workers comes to, by
# the way the line says; "unknown" is a thread the reader can't follow; any other timer is the main thread's.
SAMPLE = '''
from PySide6 import QtCore
from PySide6.QtCore import QTimer, QTimer as Later


def tidy(db):
    QtCore.QTimer.singleShot(0, db.close)                       # found: a function of the module, the timer named through QtCore


def never_named():
    QTimer.singleShot(0, print)


class Backend:
    def __init__(self):
        self._timer = QTimer(self)

    def install(self, url):
        def prog(got, total):
            Later.singleShot(0, self.busyChanged.emit)          # found: a callback handed to other code, the timer imported by another name
        def helper():
            QTimer.singleShot(0, self.reload)                   # found: a function beside the worker, called by its name
        check = lambda: self.startTimer(50)                     # found: a lambda beside the worker
        def work():
            install.install(url, prog)
            sync.sync_all(self.db, on_item=lambda: QTimer.singleShot(0, self.reload))   # found: a lambda in the worker
            tidy(self.db) or helper() or check()
            self._arm()
            QTimer.singleShot(0, lambda: self._install(url, ""))                         # found: the worker itself
        threading.Thread(target=work, daemon=True).start()
        QTimer.singleShot(0, self.reload)

    def start(self, run):
        threading.Thread(target=self._heal, name="heal").start()
        threading.Thread(target=lambda: self._later()).start()
        threading.Thread(target=run).start()                    # unknown: `run` is whatever the caller gave

    def _heal(self):
        later = QTimer.singleShot                               # found: a method as the target, the timer not called here
        return later, self.count

    @property
    def count(self):
        return QTimer(self)                                     # found: a property the worker reads

    def _later(self):
        self._timer.start(5)                                    # found: a lambda as the target, the backend's own timer

    def _arm(self):
        self._timer.stop()                                      # found: a method the worker calls, the backend's own timer

    def sync(self):
        QTimer.singleShot(5, self.start)
'''


def test_a_worker_threads_timer_is_found_however_the_thread_reaches_it():
    marked = {kind: [n for n, line in enumerate(SAMPLE.split("\n"), 1) if f"# {kind}: " in line] for kind in ("found", "unknown")}
    got = worker_timers(SAMPLE)
    assert [int(line.split()[1].rstrip(":")) for line in got if "what does this thread run?" not in line] == marked["found"], got
    assert [int(line.split()[1].rstrip(":")) for line in got if "what does this thread run?" in line] == marked["unknown"], got
    assert got[-1] == f"line {marked['unknown'][0]}: what does this thread run? threading.Thread(target=run)"
    assert "line 29: QTimer.singleShot(0, lambda: self._install(url, ''))" in got and 29 in marked["found"]


def test_a_timer_is_found_in_any_module_a_worker_thread_can_call_into():
    timer = "from PySide6.QtCore import QTimer as Later\nLater.singleShot(0, print)\n"
    sources = {
        "app/__init__.py": "",
        "app/backend.py": "import threading\nfrom . import prefs as prefs_mod\nfrom .channelui import Channels\n"
                          "def go():\n    from app_core import sync\n    threading.Thread(target=lambda: Channels().cards()).start()\n",
        "app/channelui.py": "import app_core.db\nclass Channels:\n    def cards(self): pass\n",
        "app/prefs.py": "",
        "app/window.py": "from .backend import go\n" + timer,                  # the main thread's: it imports the backend, not the other way
        "app_core/__init__.py": "", "app_core/db.py": "", "app_core/sync.py": "from concurrent.futures import ThreadPoolExecutor\n",
        "app_core/other.py": timer,                                             # no module with threads imports it
    }
    assert timers_within_reach(sources) == []
    for path in ("app/__init__.py", "app/channelui.py", "app/prefs.py", "app_core/__init__.py", "app_core/db.py", "app_core/sync.py"):
        line = sources[path].count("\n") + 1
        assert timers_within_reach({**sources, path: sources[path] + timer})[0] == \
            f"{path}: line {line}: a timer, in a module the threads of app/backend.py can reach unread", path
    # its own threads' timers, by the reader; with threads the reader can't follow, any timer at all
    assert timers_within_reach({"app/backend.py": SAMPLE})[0] == "app/backend.py: line 7: QtCore.QTimer.singleShot(0, db.close)"
    for threads in (sources["app_core/sync.py"], "from threading import Thread as T\n"):
        assert timers_within_reach({"app_core/sync.py": threads + timer}) == [
            "app_core/sync.py: line 2: a timer, in a module the threads of app_core/sync.py can reach unread"]
    assert timers_within_reach({"app_core/other.py": "import threading\n" + timer}) == []      # it starts none


def test_no_worker_thread_of_the_application_makes_a_timer():
    # CR1, #463 and #464: three hand-offs were QTimer.singleShot calls on a worker thread, and none ever ran
    sources = {}
    for path in glob.glob(written.path("src/**/*.py"), recursive=True):
        with open(path, encoding="utf-8") as f:
            sources[os.path.relpath(path, written.path("src")).replace(os.sep, "/")] = f.read()
    assert {"appkata/backend.py", "appkata/channelui.py", "appkata_core/install.py"} <= set(sources)
    assert timers_within_reach(sources) == []


# ---------------------------------------------------------------- an API token's host (R11.1.6; CR1, #297)
def test_a_token_is_kept_under_the_one_address_it_belongs_to(be):
    """Settings' host field took any text as the key, and Http looked a token up under another: what
    is typed is kept as a Source's host is written, which is the key every request looks up."""
    be.setToken("Git.Example.org:3000", "on-the-port")
    be.setToken("https://git.example.org:443/o/r", "on-the-default-port")
    kept = {"git.example.org:3000": "on-the-port", "git.example.org": "on-the-default-port"}
    assert be.db.get("tokens") == kept == be.http.tokens
    assert [row["host"] for row in be.tokenHosts] == ["git.example.org", "git.example.org:3000"]
    be.setToken("git.example.org:3000", "")                        # the row's trash button
    assert be.db.get("tokens") == {"git.example.org": "on-the-default-port"} == be.http.tokens


def test_a_tokens_row_and_its_audit_line_show_its_host_in_its_script_and_it_is_kept_as_it_is_sent(be):
    """The review's pass 8, P8-1, as the owner decided it: a token is kept under its host in the form
    it is sent, the key every rule compares, and Settings' row and the Audit showed that key, so a
    token typed `übung.lan` for the Source `übung.lan` was listed as `xn--bung-zra.lan`."""
    be.setToken("Übung.lan", "typed-in-its-script")
    be.setToken("https://gitea.xn--bung-zra.lan:3000/o/r", "pasted-in-its-idna-form")
    be.setToken("[::1]:3000", "an-address")
    kept = {"xn--bung-zra.lan": "typed-in-its-script", "gitea.xn--bung-zra.lan:3000": "pasted-in-its-idna-form",
            "[::1]:3000": "an-address"}
    assert be.db.get("tokens") == kept == be.http.tokens
    assert [row["host"] for row in be.tokenHosts] == ["[::1]:3000", "gitea.übung.lan:3000", "übung.lan"]
    said = [(e["action"], e["subject"]) for e in audit.page(be.db, kind="setting")][::-1]
    assert said == [("set an API token for", "übung.lan"), ("set an API token for", "gitea.übung.lan:3000"),
                    ("set an API token for", "[::1]:3000")]
    be.setToken("übung.lan", "")                                    # the row's trash button, with the host it shows
    assert be.db.get("tokens") == {k: v for k, v in kept.items() if k != "xn--bung-zra.lan"} == be.http.tokens
    assert audit.page(be.db, kind="setting")[0]["subject"] == "übung.lan"


@pytest.mark.parametrize("typed, said", [
    ("Straße.example", "straße.example: a name with ß in it"), ("https://stra%C3%9Fe.example:3000/o/r", "straße.example:3000: a name with ß in it"),
    ("σίσυφος.example", "σίσυφος.example: a name with ς in it"),
    ("می\u200cخواهم.example", "می\u200cخواهم.example: a name with a zero-width non-joiner (U+200C) in it"),
    ("ශ්\u200dරී.example", "ශ්\u200dරී.example: a name with a zero-width joiner (U+200D) in it"),
])
def test_a_token_typed_for_a_name_idna_2003_and_2008_read_apart_isnt_kept_and_a_toast_says_why(be, typed, said):
    """The review's pass 7, P7-1: such a name's IDNA 2003 form, which Http sends a name in, is
    another host than the one it names, and a token typed for it was kept under that other host."""
    toasts = []
    be.toast.connect(lambda kind, text: toasts.append((kind, text)))
    logged = audit.count(be.db)
    be.setToken(typed, "a-token")
    assert be.db.get("tokens", {}) == {} == be.http.tokens and audit.count(be.db) == logged
    assert [kind for kind, _ in toasts] == ["error"] and toasts[0][1].startswith(f"No token kept for {said} is two different hosts")


@pytest.mark.parametrize("typed, kept", [
    ("straße.example", {}),                                         # refused, as above
    ("git.example.org", {"git.example.org": "made-once-1234"}),
])
def test_settings_plus_empties_the_token_field_only_once_the_token_is_kept(be, typed, kept):
    """The review's pass 12, P12-2: Settings' "+" emptied the token field after every setToken, and
    since pass 7 setToken can refuse a host and keep nothing, so a pasted token, which a forge shows
    once, was lost along with the refusal. The real dialog, offscreen, against the real Backend."""
    from PySide6.QtCore import QCoreApplication, QEvent, QMetaObject, QObject, QUrl
    from PySide6.QtQml import QQmlApplicationEngine
    toasts = []
    be.toast.connect(lambda kind, text: toasts.append(kind))
    engine = QQmlApplicationEngine()
    for name, value in (("backend", be), ("appVersion", "test"), ("themeOverride", ""), ("tourMode", False), ("platformOs", "linux")):
        engine.rootContext().setContextProperty(name, value)
    engine.loadData(b'import QtQuick\nimport QtQuick.Controls.Basic\nimport "../src/appkata/qml"\n'
                    b'ApplicationWindow { width: 1920; height: 1040; visible: true; SettingsDialog { objectName: "settings" } }',
                    QUrl.fromLocalFile(os.path.join(os.path.dirname(os.path.abspath(__file__)), "settings-tokens.qml")))
    assert engine.rootObjects(), "Settings did not load"
    root = engine.rootObjects()[0]
    try:
        dlg = root.findChild(QObject, "settings")
        QMetaObject.invokeMethod(dlg, "show")                       # as Main.qml opens Settings
        within = dlg.findChildren(QObject)
        host = next(o for o in within if o.property("placeholder") == "host or host:port")
        token = next(o for o in within if o.property("placeholder") == "Paste a token")
        plus = next(o for o in within if o.property("tip") == "Add token")
        host.setProperty("text", typed)
        token.setProperty("text", "made-once-1234")
        assert plus.property("enabledButton")
        plus.clicked.emit()
        assert be.db.get("tokens", {}) == kept
        if kept:
            assert (token.property("text"), toasts) == ("", [])
        else:                                                       # both fields as typed, to add again
            assert (host.property("text"), token.property("text"), toasts) == (typed, "made-once-1234", ["error"])
    finally:
        root.deleteLater()
        engine.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)      # before the backend goes


# ---------------------------------------------------------------- the Add source preview (R7.2; CR1, #269)

class Answer(io.BytesIO):
    """A forge's answer to one request, as Http reads one."""

    def __init__(self, url, body):
        super().__init__(json.dumps(body).encode())
        self.url, self.headers = url, {}

    def geturl(self):
        return self.url

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def a_forge_that_answers(info):
    """Http's opener for a host that says it runs Forgejo, and answers `info` for the project itself:
    what a forge can answer, or the error that opening its address ends in."""
    def open_(req, timeout=0):
        if req.full_url.endswith("/api/v1/version"):
            return Answer(req.full_url, {"version": "11.0.1+gitea-1.22.0"})
        if isinstance(info, BaseException):
            raise info
        return Answer(req.full_url, info)
    return open_


@pytest.mark.parametrize("info, says", [
    (["a", "list"], "unexpected error (AttributeError"),            # a forge's answer of another shape
    ({"name": "r", "full_name": 7}, "unexpected error (AttributeError"),
    (RuntimeError("anything at all"), "unexpected error (RuntimeError: anything at all)"),
    (InvalidURL("URL can't contain control characters"), "can't be sent"),      # Http's own errors, as before
    (IncompleteRead(b"half", 96), "cut its answer short"),
], ids=["a-list", "a-number-for-a-name", "RuntimeError", "InvalidURL", "IncompleteRead"])
def test_the_add_source_preview_answers_whatever_asking_the_forge_ends_in(be, monkeypatch, info, says):
    """The preview's thread caught a ValueError and a SourceError: anything else ended it, and the Add
    source dialog waited for an answer that never came."""
    from appkata_core import http
    waits = types.SimpleNamespace(time=time.time, monotonic=time.monotonic, sleep=lambda seconds: None)
    monkeypatch.setattr(http, "time", waits)                 # a cut answer is asked for three times: no waiting between
    be.http = http.Http(opener=a_forge_that_answers(info))
    got = []
    be.sourcePreview.connect(got.append)
    be.previewSource("https://git.example.org/o/r")
    assert wait(lambda: got), "the preview never answered"
    assert got[0]["ok"] is False and says in got[0]["error"] and got[0]["host"] == "git.example.org", got


# ---------------------------------------------------------------- a Source that is to be asked again later (R2.10; CR1, #277)
def a_forge_that_says_come_back(status, headers, asked):
    """Http's opener for hosts whose every answer is this failing status with these headers."""
    import urllib.error

    def open_(req, timeout=0):
        asked.append(req.full_url)
        raise urllib.error.HTTPError(req.full_url, status, "err", dict(headers), None)
    return open_


@pytest.mark.parametrize("status, headers, hint", [
    (403, {"x-ratelimit-remaining": "0", "x-ratelimit-reset": str(int(time.time()) + 600)}, True),    # a forge's own rate limit
    (429, {"Retry-After": "600"}, True), (429, {}, True),
    (503, {"Retry-After": "600"}, False),                              # a forge that is overloaded or being maintained
    (502, {"Retry-After": "600"}, False), (500, {"Retry-After": "600"}, False),
    (429, {"Retry-After": "9" * 30}, True),                            # no time a clock can show: the row is still shown
], ids=["403-limit", "429-retry-after", "429", "503-retry-after", "502-retry-after", "500-retry-after", "429-no-time"])
def test_a_rate_limit_hints_at_a_token_and_a_forge_being_maintained_says_only_until_when(be, monkeypatch, status, headers, hint):
    """Since any failing answer's Retry-After is heard, a forge being maintained had "add a token in
    Settings" on its rows, which no token helps. Two Sources on the host, through a whole Sync: the
    one whose request was answered and the one refused after it read the same."""
    import datetime
    from appkata_core import http
    monkeypatch.setattr(channels, "enabled", lambda: False)        # none of this machine's package channels
    sources = ["https://git.example.org/o/r", "https://git.example.org/o/s"]
    for url in sources:
        be.db.x("INSERT INTO sources(url, settings, added_at) VALUES(?,?,?)", (url, json.dumps({"forge": "forgejo"}), now()))
    asked = []
    be.http = http.Http(opener=a_forge_that_says_come_back(status, headers, asked))
    sync.sync_all(be.db, be.http, workers=1)
    be.reload()
    shown = {row["url"]: row["errorText"] for row in be.sourceItems}
    assert set(sources) <= set(shown) and len([url for url in asked if "git.example.org" in url]) == 1
    for url in sources:
        extra = json.loads(be.db.one("SELECT error_extra FROM apps WHERE url=?", (url,))["error_extra"])
        until = "Rate limited until " + datetime.datetime.fromtimestamp(extra["reset"]).strftime("%H:%M")
        assert shown[url] == until + (" · add a token in Settings" if hint else ""), shown


# ---------------------------------------------------------------- what App Detail says of a file's check (R4.4; CR1, #465)
# How it slipped past: no test read detail()'s "verify" at all, for an installed app or any other.
SHA = "ab" * 32


def file_of(version):
    return f"demo-{version}-x86_64.AppImage"


def published(version, digest="", sums=False, prerelease=False, file=True):
    """A release of Demo: its AppImage (or no file for this computer), with a forge digest for it or a
    SHA256SUMS beside it."""
    r = release(version, file_of(version) if file else f"demo-{version}.dmg", *(["SHA256SUMS"] if sums else []))
    r["prerelease"] = prerelease
    r["assets"][0]["digest"] = "sha256:" + digest if digest else ""
    return r


def installed_as(be, version, record):
    """Demo, installed by AppKata with this install record."""
    be.db.x("INSERT INTO installs(url, name, version, date, asset, kind, record, installed_at) VALUES(?,?,?,?,?,?,?,?)",
            (URL, "Demo", version, "2026-01-01T00:00:00Z", file_of(version), "appimage", json.dumps(record), now()))
    be.reload()


@pytest.mark.parametrize("record, next_digest, chip, tip", [
    ({"verified": "unverified", "checksum_source": ""}, SHA, "unverified", ""),                  # the finding's case 1
    ({"verified": "checksum", "checksum_source": "forge digest"}, "", "checksum", "Checked against the forge's digest"),    # case 2
    ({"verified": "checksum", "checksum_source": "SHA256SUMS"}, "", "checksum", "Checked against SHA256SUMS"),
    ({"verified": "signed", "signer": "Demo Ltd", "checksum_source": ""}, "", "signed", ""),
    ({"verified": "adopted"}, SHA, "unverified", "AppKata adopted this copy as it found it and didn't download it, so it checked nothing"),
    ({}, SHA, "unverified", ""),                                                                  # a record that names no check
    # its release had a checksum file that gave no checksum: the chip says so (CR1, #328)
    ({"verified": "unverified", "checksum_source": "", "checksum_reason": "couldn't read SHA256SUMS (HTTP 404)"}, SHA, "unverified",
     "Its release has a checksum file, but this download was checked against none: couldn't read SHA256SUMS (HTTP 404)"),
    ({"verified": "unverified", "checksum_reason": "App.AppImage.sha256 doesn't list this file; SHA256SUMS doesn't list this file"}, "",
     "unverified", "Its release has a checksum file, but this download was checked against none: "
                   "App.AppImage.sha256 doesn't list this file; SHA256SUMS doesn't list this file"),
    ({"verified": "signed", "signer": "Demo Ltd", "checksum_reason": "couldn't read SHA256SUMS"}, "", "signed", ""),
], ids=["unverified-then-a-digest", "forge-digest-then-none", "sums-file-then-none", "signed", "adopted", "no-result",
        "a-checksum-file-that-couldnt-be-read", "checksum-files-without-the-file", "signed-whatever-the-checksum-file"])
def test_an_installed_apps_chip_is_what_its_own_install_checked_whatever_the_next_release_publishes(be, record, next_digest, chip, tip):
    """The chip was read from the file of the release Update would take: Checksum for a file that was
    never checked once a later release had a digest, Unverified for a checked one once it had none."""
    source(be, published("2.0", digest=next_digest), published("1.0"))
    installed_as(be, "1.0", record)
    d = be.detail(URL)
    assert (d["state"], d["updateTo"], d["asset"]["name"]) == ("update", "2.0", file_of("2.0"))
    assert (d["verify"], d["verifyTip"], d["signer"]) == (chip, tip, record.get("signer", ""))
    assert (d["forecast"], d["forecastVersion"]) == ("published" if next_digest else "none", "2.0")     # the update's file, beside it


# R16.3.6 (CR1, #318): the chip of a copy from a package channel is what its record says checked it.
# It was Verified for every record with a channel, whatever the record said.
FLATPAK = {"channel": "flatpak", "flatpak": "org.example.Demo", "installation": "user"}
PACKAGE = {"channel": "package", "package": "demo", "manager": "apt", "pkgVersion": "1.0-1"}


@pytest.mark.parametrize("record, chip, tip", [
    ({**FLATPAK, "remote": "flathub", "verified": "signed", "signer": "Flathub"}, "signed", "Signed by Flathub"),
    ({**FLATPAK, "remote": "vendor", "verified": "signed", "signer": "vendor"}, "signed", "Signed by vendor"),
    ({**FLATPAK, "remote": "aktest", "verified": "unverified", "signer": ""}, "unverified",
     "No key checked this copy: flatpak doesn't check its remote, aktest, against one"),
    ({**FLATPAK, "remote": "", "verified": "unverified", "signer": ""}, "unverified",
     "Its remote isn't known, so AppKata can't tell that a key checked this copy"),
    ({**PACKAGE, "verified": "signed", "signer": "Ubuntu", "repository": "Ubuntu"}, "signed", "Signed by Ubuntu"),
    ({**PACKAGE, "verified": "signed", "signer": "LP-PPA-mozillateam", "repository": "LP-PPA-mozillateam"}, "signed", "Signed by LP-PPA-mozillateam"),
    ({**PACKAGE, "verified": "signed", "signer": "", "repository": "https://deb.example.org/apt"}, "signed", "Signed by its repository"),
    ({**PACKAGE, "verified": "unverified", "signer": "", "repository": ""}, "unverified",
     "No repository offers the installed version (1.0-1), so AppKata can't tell that a repository's key checked it"),
    ({**PACKAGE, "verified": "unverified", "signer": "", "repository": "file:/tmp/akrepo"}, "unverified",
     "No key checked this package: it is from file:/tmp/akrepo, which isn't checked against one"),
    ({**PACKAGE, "adopted": True}, "unverified",
     "No repository offers the installed version (1.0-1), so AppKata can't tell that a repository's key checked it"),     # names no check
], ids=["flathub", "a-vendors-remote", "a-remote-not-checked", "no-remote", "the-distribution", "a-ppa", "a-repository-with-no-name",
        "a-package-put-in-by-hand", "a-repository-trusted-without-a-key", "no-result"])
def test_a_channels_copy_has_the_chip_its_record_says_and_none_for_being_from_a_channel(be, record, chip, tip):
    source(be, published("1.0"))
    installed_as(be, "1.0", record)
    d = be.detail(URL)
    assert d["ch"]["kind"] == record["channel"]
    assert (d["verify"], d["verifyTip"], d["signer"], d["forecast"]) == (chip, tip, "", "")       # the signer is in the tooltip


def test_a_package_no_repository_checked_is_named_by_no_distribution(be):
    """Its label and the rows that name its distribution took the record's signer, which was the
    distribution's name for every package."""
    source(be, published("1.0"))
    installed_as(be, "1.0", {**PACKAGE, "verified": "unverified", "signer": "", "repository": ""})
    assert (be.detail(URL)["ch"]["label"], be.detail(URL)["ch"]["distro"]) == ("Package", "")
    be.db.x("DELETE FROM installs")
    installed_as(be, "1.0", {**PACKAGE, "verified": "signed", "signer": "LP-PPA-mozillateam", "origin": "main"})
    assert (be.detail(URL)["ch"]["label"], be.detail(URL)["ch"]["distro"]) == ("LP-PPA-mozillateam (main)", "LP-PPA-mozillateam")


@pytest.mark.parametrize("releases, state", [
    ([published("1.0", digest=SHA)], "installed"),                                   # nothing newer: no file to forecast
    ([published("2.0", digest=SHA, file=False), published("1.0", digest=SHA)], "update"),     # 2.0 has no file for this computer
], ids=["up-to-date", "no-file-in-the-newest"])
def test_an_installed_app_has_its_own_chip_and_no_forecast_when_there_is_no_file_to_take(be, releases, state):
    source(be, *releases)
    installed_as(be, "1.0", {"verified": "unverified", "checksum_source": ""})
    d = be.detail(URL)
    assert (d["state"], d["verify"], d["forecast"], d["forecastVersion"]) == (state, "unverified", "", "")


@pytest.mark.parametrize("releases, forecast, version", [
    ([published("1.0", digest=SHA)], "published", "1.0"),
    ([published("1.0", sums=True)], "published", "1.0"),
    ([published("1.0")], "none", "1.0"),
    # the finding's case 4: the newest release is a pre-release, so the file Install takes is 1.0's,
    # and what is published for it is in 1.0, not in the newest release
    ([published("2.0-rc1", prerelease=True), published("1.0", sums=True)], "published", "1.0"),
    ([published("2.0-rc1", sums=True, prerelease=True), published("1.0")], "none", "1.0"),
    ([published("1.0", digest=SHA, file=False)], "", ""),                             # no file for this computer: nothing to forecast
], ids=["digest", "sums-file", "nothing", "sums-in-its-own-release", "sums-only-in-a-newer-release", "no-file"])
def test_a_file_that_isnt_installed_yet_gets_a_forecast_read_from_its_own_release(be, releases, forecast, version):
    source(be, *releases)
    d = be.detail(URL)
    assert d["installed"] == "" and d["verify"] == "" and d["verifyTip"] == ""        # nothing was checked: no result to show
    assert (d["forecast"], d["forecastVersion"]) == (forecast, version)


def found_outside_appkata(be):
    be.db.x("INSERT INTO foreign_installs(url, location, version, checked_at) VALUES(?,?,?,?)", (URL, "/opt/demo", "1.0", now()))


def tracked_only(be):
    be.db.x("UPDATE sources SET settings=? WHERE url=?", (json.dumps({"track_only": True}), URL))


@pytest.mark.parametrize("how, state", [(found_outside_appkata, "foreign"), (tracked_only, "")], ids=["foreign", "track-only"])
def test_nothing_is_forecast_for_an_app_install_isnt_offered_for(be, how, state):
    source(be, published("1.0", digest=SHA))
    assert be.detail(URL)["forecast"] == "published"
    how(be)
    be.reload()
    d = be.detail(URL)
    assert (d["state"], bool(d["foreign"]), d["trackOnly"]) == (state, how is found_outside_appkata, how is tracked_only)
    assert d["asset"]["name"] == file_of("1.0") and (d["verify"], d["forecast"], d["forecastVersion"]) == ("", "", "")


# ---------------------------------------------------------------- the installed file's SHA-256 (R10.3.4, R8.4.5.1; CR1, #467)
# How it slipped past: the install logged the download's SHA-256 and kept it nowhere, so there was
# nothing but the release's data to read, and no test compared a reviewer's digest with anything.
DOWNLOADED, REPLACED = "d0" * 32, "4e" * 32


def a_review_of(db, version, details):
    """A Trust, Desk, whose review of this version has these Details."""
    tid = db.x("INSERT INTO trusts(url, name, own, verified_commit, score) VALUES(?,?,?,?,?)",
               ("https://example.org/trust", "Desk", 0, "abc", 3)).lastrowid
    said = {"_app": {"trust": 4}, "_versions": [{"v": version, "text": "Read.", "details": details, "opts": {}, "verdict": {"trust": 4}}]}
    db.x("INSERT INTO reviews(trust_id, url, app, source, tags, trust, rating, section, settings) VALUES(?,?,?,?,?,?,?,?,?)",
         (tid, URL, "Demo", URL, "[]", 4, 4, "An editor.", json.dumps(said)))


@pytest.mark.parametrize("record, forge, reviewed, same", [
    # the project replaced 1.0's file under its name after the install, and a reviewer recorded the new one
    ({"sha256": {"1.0": DOWNLOADED}}, REPLACED, REPLACED, False),
    ({"sha256": {"1.0": DOWNLOADED}}, REPLACED, DOWNLOADED, True),
    ({"sha256": {"1.0": DOWNLOADED}}, "", DOWNLOADED, True),           # the forge gave no digest: AppKata hashed the download all the same
    ({"sha256": {"0.9": REPLACED, "1.0": DOWNLOADED}}, "", REPLACED, False),     # a kept version's file isn't the installed one
    ({"verified": "adopted"}, REPLACED, REPLACED, False),              # never downloaded: no digest, whatever the forge says of that name
], ids=["replaced-and-reviewed-since", "replaced-since", "no-forge-digest", "a-kept-versions", "adopted"])
def test_the_installed_files_own_sha256_is_what_a_reviewers_is_compared_with_and_what_a_review_says(be, record, forge, reviewed, same):
    source(be, published("1.0", digest=forge))
    installed_as(be, "1.0", record)
    a_review_of(be.db, "1.0", [["SHA-256", reviewed]])
    be.reload()
    mine = "" if record.get("verified") == "adopted" else DOWNLOADED
    assert be.detail(URL)["sameFileAs"] == (["Desk"] if same else [])
    said = be.reviewData(URL)["details"]                           # the review dialog's Details: what Save would publish
    assert [k for k, _ in said] == ["Date", "Platform", "Channel", "File"] + (["SHA-256"] if mine else [])
    assert dict(said)["File"] == file_of("1.0") and dict(said).get("SHA-256", "") == mine


def test_a_file_not_yet_installed_is_compared_by_the_digest_its_release_gives(be):
    source(be, published("1.0", digest=REPLACED))                 # the one about to be installed (R10.3.4): checked at the install
    a_review_of(be.db, "1.0", [["SHA-256", REPLACED]])
    be.reload()
    assert be.detail(URL)["sameFileAs"] == ["Desk"] and be.reviewData(URL)["details"] == []


# ---------------------------------------------------------------- only a whole digest is the same file (R10.3.4; CR1, #466)
@pytest.mark.parametrize("written, same", [
    (DOWNLOADED, True), ("sha256:" + DOWNLOADED.upper(), True),
    (DOWNLOADED[:4] + "…" + DOWNLOADED[-4:], False),               # as R10's example wrote it
    (DOWNLOADED[:7], False), (DOWNLOADED[:32], False), ("…" + DOWNLOADED[-6:], False), (DOWNLOADED[:63], False),
], ids=["whole", "whole-with-its-prefix", "both-ends", "first-7", "first-32", "last-6", "all-but-one"])
@pytest.mark.parametrize("is_installed", [True, False], ids=["installed", "about-to-be-installed"])
def test_same_file_is_said_only_of_a_reviewers_whole_sha256(be, written, same, is_installed):
    source(be, published("1.0", digest="" if is_installed else DOWNLOADED))
    if is_installed:
        installed_as(be, "1.0", {"sha256": {"1.0": DOWNLOADED}})
    a_review_of(be.db, "1.0", [["SHA-256", written]])
    be.reload()
    assert be.detail(URL)["sameFileAs"] == (["Desk"] if same else [])


# ---------------------------------------------------------------- a plan AppKata refuses (R16.3.5, R16.4.3; CR1, #742)
# How it slipped past: the dialog's refused form was drawn by no test of the backend, so nothing
# saw that no refusal ever got there: install.py made an install error of each on its way.
NEEDED = "It would remove ubuntu-desktop, which this computer needs."


@pytest.fixture
def refusing(monkeypatch):
    """A package manager whose plan for anything removes the desktop's metapackage, which AppKata
    refuses to run. Returns what it was told to run."""
    from appkata_core import pkgbackend

    class Refusing(pkgbackend.Backend):
        name, manager, ran = "fake", "apt", []

        def simulate(self, action, names):
            return pkgbackend.Plan(install=list(names) if action == "install" else [], upgrade=list(names) if action == "upgrade" else [],
                                   remove=(list(names) if action == "remove" else []) + ["ubuntu-desktop"])

        def facts(self, names):
            return pkgbackend.Facts()

        def run(self, action, names, progress=None, cancel=None, on_wait=None):
            self.ran.append((action, names))

    Refusing.ran = []
    monkeypatch.setattr(pkgbackend, "backend", lambda: Refusing())
    monkeypatch.setattr(pkgbackend, "installed_version", lambda name, manager=None: "1.0-1")
    monkeypatch.setattr(channels, "enabled", lambda: False)             # none of this machine's package channels
    return Refusing.ran


@pytest.mark.parametrize("road", ["install", "update", "uninstall"])
def test_a_refused_plan_is_shown_in_the_plan_dialog_as_refused(be, refusing, road):
    source(be, published("1.0"))
    if road != "install":
        installed_as(be, "1.0", {**PACKAGE, "verified": "signed", "signer": "Ubuntu", "repository": "Ubuntu"})
    shown, toasts = [], []
    be.planConfirm.connect(shown.append)
    be.toast.connect(lambda kind, text: toasts.append((kind, text)))
    if road == "install":
        be._install_channel(URL, {"channel": "package", "value": "demo"}, "")
    elif road == "update":
        be._install_channel(URL, {}, "", update=True)
    else:
        be.uninstall(URL)
    assert wait(lambda: shown), toasts
    assert not wait(lambda: len(shown) > 1 or toasts, 0.3), (shown, toasts)                 # the dialog, once, and no error line beside it
    assert dict(shown[0]) == {"url": URL, "name": "Demo", "action": "update" if road == "update" else road, "lines": [NEEDED], "refused": True}
    assert refusing == [] and bool(be.db.one("SELECT 1 FROM installs WHERE url=?", (URL,))) == (road != "install")


def test_removing_a_source_with_its_app_says_a_refused_plan_as_an_error_and_removes_nothing(be, refusing):
    # the one road with no plan dialog: the refusal is the error line it was, and the Source stays
    source(be, published("1.0"))
    installed_as(be, "1.0", dict(PACKAGE))
    toasts = []
    be.toast.connect(lambda kind, text: toasts.append((kind, text)))
    be.removeSource(URL, True)
    assert toasts == [("error", NEEDED)] and refusing == []
    assert be.db.one("SELECT 1 FROM sources WHERE url=?", (URL,)) and be.db.one("SELECT 1 FROM installs WHERE url=?", (URL,))
