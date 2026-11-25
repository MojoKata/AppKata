"""The tests a tier may skip (the walk thru of 2026-10-30, item 2; docs/reviews/followups-skips.md).

A tier that sets APPKATA_SKIPS=<name> runs against tests/skips/<name>.txt, the tests it may skip and
why. A skip the list doesn't name is a failure, and so is a listed test that ran, so the list only
shrinks; each counts in the run's summary line, which is what the tiers read. A run by hand,
without APPKATA_SKIPS, checks nothing. A tier without a list yet fails on each skip, and each
failure gives the line the list would need.

How the class slipped past: a test that skips says why and the run still passes, and the tiers'
results were read as counts ("128 passed, 6 skipped"). In one run three VMs couldn't resolve names,
so the test that exists for their DNS skipped, and tier 1 skipped the ISO download test on every
run: its image has no curl.

And every test's own home (issue #718), below: `own_home` and the check of AppKata's files in the real one."""

import functools
import json
import os
import re
import stat

import pytest

import parts

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKIPS = os.path.join(ROOT, "tests", "skips")


@functools.lru_cache(maxsize=None)
def listed(name):
    """{test id: why it may skip} of a tier's list: a line per test, the reason after "  # "."""
    path = os.path.join(SKIPS, name + ".txt")
    out = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                if line.strip() and not line.startswith("#"):
                    test, _, why = line.rstrip("\n").partition("  # ")
                    out[test.strip()] = why.strip()
    return out


def case_id(item):
    """A test's id from the repository's root, whichever folder a tier runs pytest from."""
    return os.path.relpath(str(item.path), ROOT).replace(os.sep, "/") + "::" + item.nodeid.partition("::")[2]


def allows(name, test):
    """Whether tier name's list names test: by its id, by its name without the [parameters] (every case
    of a parametrized test), or as <file>::* (every test of a file the tier skips whole, the Windows
    run's Linux-only ones)."""
    entries = listed(name)
    return test in entries or test.split("[")[0] in entries or test.split("::")[0] + "::*" in entries


def verdict(name, test, skipped, why, ran):
    """Why a test's report fails tier name's list, or None: a skip it doesn't list, a listed test that ran."""
    if skipped and not allows(name, test):
        return f"skipped, and tests/skips/{name}.txt doesn't list it:\n{test}  # {why}"
    if ran and allows(name, test):
        return f"tests/skips/{name}.txt lists it as a skip, and it ran: take it off the list"
    return None


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    report = (yield).get_result()
    name = os.environ.get("APPKATA_SKIPS")
    if not name or hasattr(report, "wasxfail"):
        return
    why = ""
    if report.skipped:
        why = report.longrepr[2] if isinstance(report.longrepr, tuple) else str(report.longrepr)
        why = " ".join(re.sub(r"^Skipped: ", "", why).split())
    failed = verdict(name, case_id(item), report.skipped, why, report.when == "call" and report.passed)
    if failed:
        report.outcome, report.longrepr = "failed", failed


collected = set()    # the case_id of every test collected, before -k or -m deselects any


def pytest_itemcollected(item):
    collected.add(case_id(item))


_modules = []        # (module, why, verdict) of each module skipped whole, which no test report carries


@pytest.hookimpl(hookwrapper=True)
def pytest_make_collect_report(collector):
    report = (yield).get_result()
    name = os.environ.get("APPKATA_SKIPS")
    if name and report.skipped and isinstance(collector, pytest.Module):
        module = os.path.relpath(str(collector.path), ROOT).replace(os.sep, "/")
        why = " ".join(re.sub(r"^Skipped: ", "", report.longrepr[2]).split())
        failed = verdict(name, module, True, why, False)
        if failed:
            _modules.append(failed)


# CI's parts of tier 1 (tests/parts.py): APPKATA_PART=k/n keeps part k of n of the tests collected,
# and APPKATA_DURATIONS=<file> writes what each test took, for the next split.
@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(config, items):
    part = parts.env_part()
    if not part:
        return
    keep = parts.choose([(case_id(item), parts.unit(item)) for item in items], *part, *parts.load())
    config.hook.pytest_deselected(items=[item for item, ok in zip(items, keep) if not ok])
    items[:] = [item for item, ok in zip(items, keep) if ok]


_took = parts.Recorder()


def pytest_runtest_logreport(report):
    if os.environ.get("APPKATA_DURATIONS"):
        _took.add(report.nodeid, report.duration)      # tier 1 runs from the root: the nodeid is the case_id


def pytest_sessionfinish(session, exitstatus):
    _home_changed[:] = home_changes(_home_before, home_state())
    if _modules or _home_changed:
        session.exitstatus = pytest.ExitCode.TESTS_FAILED
    if out := os.environ.get("APPKATA_DURATIONS"):
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            f.write(json.dumps(_took.written(), indent=1) + "\n")


def pytest_terminal_summary(terminalreporter):
    if _modules:
        terminalreporter.section(f"{len(_modules)} failed: modules skipped whole, against tests/skips/", red=True)
        for line in _modules:
            terminalreporter.line(line)
    if _home_changed:
        terminalreporter.section(f"{len(_home_changed)} failed: AppKata's files in the real home changed during the run"
                                 " (a test wrote there, or another process did)", red=True)
        for line in _home_changed[:40]:
            terminalreporter.line(line)


# ---- every test's own home (issue #718) ----
# A test ran with the run's HOME: in a container that is a throwaway, on a developer's machine their
# own. The test that builds the demo's Trusts cloned them into ~/.local/share/appkata/trusts on every
# local run, and a launcher, its command link and its menu entry turned up in ~/bin and
# ~/.local/share/applications, and nothing said so. Now each test's home is its own, and a run fails
# when AppKata's files in the real one changed while it ran, whoever wrote them: a fixture of a wider
# scope, a thread a test left running, a test that set HOME back. Or no test at all: the AppKata
# installed there updating an app, another checkout's tests. The check can't tell, so its heading
# says both. What other programs keep in ~/bin and the menu folder is theirs and doesn't count: a
# tool installed there while the tests ran failed a run in which every test passed.
REAL_HOME = os.path.expanduser("~")      # read as the suite loads, before any test has a home of its own
OWNED = ("bin/apps", ".local/share/appkata")     # AppKata's folders in a home: the apps, its data; all that is in them
# what names a home's places, and where a home has each
OWN = {"HOME": "", "XDG_DATA_HOME": ".local/share", "XDG_CONFIG_HOME": ".config", "XDG_CACHE_HOME": ".cache",
       "XDG_STATE_HOME": ".local/state", "APPKATA_DATA": ".local/share/appkata", "APPKATA_APPS": "bin/apps"}


@pytest.fixture(autouse=True)
def own_home(monkeypatch, tmp_path):
    """Every test's home is its tmp_path: HOME, the XDG folders and AppKata's own two variables
    (platform.data_dir, apps_dir) each name the place a home has for it, under tmp_path, so what the
    test, or a program it starts, writes to "~" lands in the folder pytest gives it. Nothing is made
    there until something writes. A test with a made-up user sets that user's HOME and deletes the
    rest (tests/test_sandbox_run.py's Env); a test that needs the real home says so, by setting
    HOME to conftest.REAL_HOME."""
    for var, place in OWN.items():
        monkeypatch.setenv(var, os.path.normpath(os.path.join(str(tmp_path), place)))


def _command_link(path):
    """Whether path is a link into an apps folder (install.py's command link, bin/<app> to
    bin/apps/<app>/...): this home's, or a test's own, which is <its home>/bin/apps too."""
    try:
        target = os.path.normpath(os.path.join(os.path.dirname(path), os.readlink(path)))
    except OSError:                          # not a link
        return False
    parts = target.split(os.sep)
    return ("bin", "apps") in zip(parts, parts[1:])


def _menu_entry(path):
    """Whether path has a name AppKata gives a menu entry: its own appkata.desktop (selfinstall.py),
    an app's appkata-<app>.desktop (install.py), appkata-links.desktop (desktop.py)."""
    name = os.path.basename(path)
    return name == "appkata.desktop" or (name.startswith("appkata-") and name.endswith(".desktop"))


# the folders of a home that AppKata shares with other programs, and which entries of each are its own
SHARED = {"bin": _command_link, ".local/share/applications": _menu_entry}


def home_state(home=REAL_HOME):
    """{path: (kind, size, modified)} of AppKata's files in a home: all that is in its own folders
    (OWNED), and in the folders it shares (SHARED) the command links and the menu entries, not the
    folders themselves or what else is there. A link is itself, not what it names."""
    paths = []
    for top in OWNED:
        root = os.path.normpath(os.path.join(home, top))
        paths += [root] + [os.path.join(d, n) for d, dirs, files in os.walk(root) for n in dirs + files]
    for top, appkatas in SHARED.items():
        folder = os.path.normpath(os.path.join(home, top))
        try:
            paths += [p for p in (os.path.join(folder, n) for n in os.listdir(folder)) if appkatas(p)]
        except OSError:                      # no such folder
            pass
    out = {}
    for path in paths:
        try:
            st = os.lstat(path)
        except OSError:                      # not there, or gone since it was listed
            continue
        out[path] = (stat.S_IFMT(st.st_mode), st.st_size, st.st_mtime_ns)
    return out


def home_changes(before, after):
    """What differs between two states of a home, a line each: new, gone, changed."""
    kinds = (("new", after.keys() - before.keys()), ("gone", before.keys() - after.keys()),
             ("changed", {p for p in before.keys() & after.keys() if before[p] != after[p]}))
    return [f"{kind}: {path}" for kind, paths in kinds for path in sorted(paths)]


_home_before = home_state()
_home_changed = []   # the real home's changes over the run, which fail it (pytest_sessionfinish)
