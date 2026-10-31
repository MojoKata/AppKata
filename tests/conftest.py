"""The tests a tier may skip (the walk thru of 2026-10-30, item 2; docs/reviews/followups-skips.md).

A tier that sets APPKATA_SKIPS=<name> runs against tests/skips/<name>.txt, the tests it may skip and
why. A skip the list doesn't name is a failure, and so is a listed test that ran, so the list only
shrinks; each counts in the run's summary line, which is what the tiers read. A run by hand,
without APPKATA_SKIPS, checks nothing. A tier without a list yet fails on each skip, and each
failure gives the line the list would need.

How the class slipped past: a test that skips says why and the run still passes, and the tiers'
results were read as counts ("128 passed, 6 skipped"). In one run three VMs couldn't resolve names,
so the test that exists for their DNS skipped, and tier 1 skipped the ISO download test on every
run: its image has no curl."""

import functools
import os
import re

import pytest

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
    """Whether tier name's list names test: by its id, or as <file>::* (every test of a file the tier
    skips whole, the Windows run's Linux-only ones)."""
    entries = listed(name)
    return test in entries or test.split("::")[0] + "::*" in entries


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


def pytest_sessionfinish(session, exitstatus):
    if _modules:
        session.exitstatus = pytest.ExitCode.TESTS_FAILED


def pytest_terminal_summary(terminalreporter):
    if _modules:
        terminalreporter.section(f"{len(_modules)} failed: modules skipped whole, against tests/skips/", red=True)
        for line in _modules:
            terminalreporter.line(line)
