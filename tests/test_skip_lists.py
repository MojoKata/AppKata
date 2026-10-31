"""The tests each tier may skip (tests/conftest.py, tests/skips/; the walk thru of 2026-10-30, item 2):
the verdict on a test's report, that every tier runs against a list, and that each list names tests
that exist, each with its reason. docs/reviews/followups-skips.md has what the lists caught."""

import glob
import os
import re

import conftest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
LISTS = sorted(os.path.basename(p)[:-4] for p in glob.glob(os.path.join(ROOT, "tests", "skips", "*.txt")))


def test_a_skip_the_list_doesnt_name_fails_and_so_does_a_listed_test_that_ran(monkeypatch, tmp_path):
    (tmp_path / "t.txt").write_text("# a tier\ntests/test_a.py::test_listed  # needs Windows\ntests/test_b.py  # no PySide6\n")
    monkeypatch.setattr(conftest, "SKIPS", str(tmp_path))
    conftest.listed.cache_clear()
    try:
        assert conftest.verdict("t", "tests/test_a.py::test_listed", True, "needs Windows", False) is None
        assert conftest.verdict("t", "tests/test_a.py::test_other", False, "", True) is None
        assert conftest.verdict("t", "tests/test_b.py", True, "no PySide6", False) is None
        assert conftest.verdict("t", "tests/test_a.py::test_other", True, "no network", False) == \
            "skipped, and tests/skips/t.txt doesn't list it:\ntests/test_a.py::test_other  # no network"
        assert conftest.verdict("t", "tests/test_a.py::test_listed", False, "", True) == \
            "tests/skips/t.txt lists it as a skip, and it ran: take it off the list"
        assert conftest.verdict("none", "tests/test_a.py::test_listed", True, "x", False).startswith("skipped")
    finally:
        conftest.listed.cache_clear()


def test_every_tier_runs_against_a_list():
    for script in ("scripts/test-tier1.sh", "scripts/test-sandbox.sh", "scripts/sandbox/vm-launcher.sh",
                   "scripts/sandbox/vm-desktop.sh", "scripts/test-windows-vm.sh"):
        text = open(os.path.join(ROOT, script)).read()
        assert text.count("pytest") and "APPKATA_SKIPS" in text, f"{script} runs pytest without APPKATA_SKIPS"
    assert {"tier1", "launcher-mint22.3", "launcher-lmde7", "launcher-vm-24.04", "launcher-vm-26.04", "windows"} <= set(LISTS)
    assert [n for n in LISTS if n.startswith("desktop-")], "the desktop VMs' lists"


def test_each_listed_test_exists_and_says_why_it_may_skip():
    for name in LISTS:
        conftest.listed.cache_clear()
        for test, why in conftest.listed(name).items():
            path, _, rest = test.partition("::")
            assert os.path.isfile(os.path.join(ROOT, path)), f"{name}: {test}: no such file"
            func = re.sub(r"\[.*\]$", "", rest.split("::")[-1]) if rest else ""
            if func and func != "*":
                assert re.search(rf"^\s*(async )?def {re.escape(func)}\(", open(os.path.join(ROOT, path)).read(), re.M), \
                    f"{name}: {test}: no such test"
            assert why, f"{name}: {test} says no reason"
    conftest.listed.cache_clear()


# the test modules each tier's run takes: tier 1 and Windows take tests/ whole, the others what their
# scripts name (test_tiers_take_the_modules_listed holds the scripts to it)
LAUNCHER = ["test_sandbox_run.py", "test_sandbox_exposure.py", "test_sandbox_one_fact.py", "test_sandbox_user_shaped.py"]
TAKES = {"tier1": None, "windows": None, "launcher": LAUNCHER + ["test_platform_matrix.py"],
         "launcher-vm": LAUNCHER + ["test_booted.py"], "desktop": LAUNCHER + ["test_booted.py"]}
# tests that may skip in every tier, each with why; the rest of the class is a test that never runs
# (docs/reviews/followups-skips.md). The test fails on anything new, and on a listed test some tier runs.
NEVER_RUN = {
    "tests/test_sandbox_state.py::test_freeze_todays_state_when_asked":
        "a tool, not a check: docs/build.md's release step 3 runs it with UPDATE_STATE",
    "tests/test_channels.py::test_system_bus":
        "S2, open: tier 1's container has no system bus, and no tier that has one takes test_channels.py",
}


def _takes(name):
    return next(v for k, v in sorted(TAKES.items(), key=lambda kv: -len(kv[0])) if name.startswith(k))


def test_tiers_take_the_modules_listed():
    for script, kind in (("scripts/test-sandbox.sh", "launcher"), ("scripts/sandbox/vm-launcher.sh", "launcher-vm"),
                         ("scripts/sandbox/vm-desktop.sh", "desktop")):
        lines = open(os.path.join(ROOT, script)).read().splitlines()
        at = next(i for i, line in enumerate(lines) if "APPKATA_SKIPS" in line and not line.lstrip().startswith("#"))
        run = [lines[at]]
        while run[-1].rstrip().endswith("\\"):           # the command, to its last continued line
            run.append(lines[at + len(run)])
        run = "\n".join(run)
        assert sorted(set(re.findall(r"tests/(test_\w+\.py)", run))) == sorted(TAKES[kind]), script


def test_every_test_some_tier_skips_another_runs():
    never = set()
    for test in conftest_listed_all():
        file = test.split("::")[0].split("/")[-1]
        runs = [n for n in LISTS if (_takes(n) is None or file in _takes(n)) and not conftest.allows(n, test)]
        if not runs:
            never.add(test)
    conftest.listed.cache_clear()
    assert sorted(never - set(NEVER_RUN)) == [], "skipped by every tier that takes them"
    assert sorted(set(NEVER_RUN) - never) == [], "listed as never run, but a tier runs them"


def conftest_listed_all():
    conftest.listed.cache_clear()
    return sorted({t for n in LISTS for t in conftest.listed(n)})
