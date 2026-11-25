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
