"""A pull request's test coverage impact (scripts/coverage_impact.py): the table its description
ends with, from the per-area tables two CI runs' coverage jobs printed.

Why: the coverage job's summary sits in the Actions run, where a reviewer doesn't look; the table
puts what a change did to each area's coverage in the pull request, worked out the same way each
time rather than read off logs by hand."""

import json
import os
import sys

import pytest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import coverage_impact as ci  # noqa: E402

# as coverage_report.py prints it, in the coverage job's log: job, step, time, then the row
PREFIX = "coverage\tRun echo\t2026-11-26T14:47:46.0317050Z "
MASTER = """
| Area | Files | Lines | Lines reached | Branches | Branches reached | Floor (lines / branches) |
|---|---:|---:|---:|---:|---:|---|
| sandbox | 6 | 97.2% | 445 of 458 | 93.2% | 110 of 118 | 0.0% / — |
| trust | 4 | 98.9% | 278 of 281 | 96.0% | 96 of 100 | — |
| store | 3 | 98.1% | 205 of 209 | 98.2% | 55 of 56 | — |
| ui-backend | 8 | 99.1% | 768 of 775 | 92.7% | 139 of 150 | — |
| scripts ⚠ | 14 | 34.8% | 921 of 2,643 | 35.7% | 333 of 932 | 15.2% / 15.4% |
| qml | 10 | not measured (coverage.py doesn't read QML) | | | | |
| **all** | 35 | 59.9% | 2,617 of 4,366 | 54.1% | 733 of 1,356 |  |
"""
BRANCH = """
| sandbox | 12 | 99.2% | 1,525 of 1,537 | 97.0% | 446 of 460 | 0.0% / — |
| trust | 5 | 99.1% | 342 of 345 | 96.4% | 108 of 112 | — |
| store | 3 | 98.1% | 205 of 209 | 98.2% | 55 of 56 | — |
| ui-backend | 11 | 99.5% | 2,359 of 2,372 | 96.7% | 532 of 550 | — |
| scripts | 14 | 34.9% | 923 of 2,645 | 36.4% | 340 of 934 | 15.2% / 15.4% |
| **all** | 45 | 75.3% | 5,354 of 7,108 | 70.1% | 1,481 of 2,112 |  |
"""


def log(table):
    return "\n".join(PREFIX + line for line in table.strip().splitlines())


def test_a_jobs_log_gives_each_measured_area_and_the_total_from_its_counts():
    found = ci.areas(log(MASTER))
    assert list(found) == ["sandbox", "trust", "store", "ui-backend", "scripts", "all"]
    assert found["scripts"] == ci.Area(921, 2643, 333, 932)
    assert found["all"].line_pct == pytest.approx(100 * 2617 / 4366)
    assert ci.areas(MASTER + MASTER.replace("445 of 458", "1 of 458"))["sandbox"].lines == 445
    assert ci.Area(0, 0, 0, 0).line_pct is None and ci.Area(1, 2, 0, 0).branch_pct is None


def test_an_area_below_its_floor_and_an_area_with_a_hyphen_in_its_name_are_read():
    """AppKata's coverage_report.py marks an area below its floor with " ⚠" after its name, and
    one of its areas is ui-backend: a row of either must not be passed over."""
    found = ci.areas(log(MASTER))
    assert found["scripts"] == ci.Area(921, 2643, 333, 932)  # its row is "scripts ⚠"
    assert found["ui-backend"] == ci.Area(768, 775, 139, 150)


def test_each_figure_after_carries_its_bands_mark():
    assert [ci.mark(p) for p in (100, 95.0, 94.99, 80.0, 79.9, 60.0, 59.9, 0)] == [
        "⭐", "⭐", "🟢", "🟢", "🟡", "🟡", "🔴", "🔴",
    ]  # fmt: skip


def test_the_table_has_the_areas_that_moved_half_a_point_and_the_total_always():
    out = ci.table(ci.areas(MASTER), ci.areas(BRANCH))
    lines = out.splitlines()
    assert lines[0] == (
        "| Area | Before (lines / branches) | After (lines / branches) | Gain (lines / branches) |"
    )
    rows = {line.split(" | ")[0].lstrip("| "): line for line in lines[2:] if line.startswith("|")}
    assert list(rows) == ["sandbox", "ui-backend", "scripts", "**all**"]  # trust and store moved less
    assert (
        rows["sandbox"] == "| sandbox | 97.2% / 93.2% | ⭐ 99.2% / ⭐ 97.0% | +2.1 / +3.7 |"
    )  # gains from the counts
    assert rows["scripts"].endswith("| 🔴 34.9% / 🔴 36.4% | +0.0 / +0.7 |")  # branches moved
    assert rows["**all**"] == "| **all** | 59.9% / 54.1% | 🟡 75.3% / 🟡 70.1% | +15.4 / +16.1 |"
    assert out.endswith("\n\n" + ci.LEGEND + "\n")


def test_an_area_new_or_gone_has_a_row_with_a_dash_for_the_side_it_isnt_on():
    before = {"trust": ci.Area(1, 2, 1, 2), "all": ci.Area(1, 2, 1, 2)}
    after = {"sandbox": ci.Area(9, 10, 0, 0), "all": ci.Area(9, 10, 1, 2)}
    rows = ci.table(before, after).splitlines()[2:4]
    assert rows[0] == "| sandbox | — / — | 🟢 90.0% / — | — / — |"
    assert rows[1] == "| trust | 50.0% / 50.0% | — / — | — / — |"


class Gh:
    """`gh` as the script calls it, answering from canned output."""

    def __init__(self, master_runs=None, unmeasured=()):
        self.calls = []
        self.master_runs = (
            [{"databaseId": 1, "headSha": "a" * 40}] if master_runs is None else (master_runs)
        )
        self.unmeasured = set(unmeasured)  # runs whose coverage job didn't pass

    def __call__(self, args):
        self.calls.append(args)
        if args[:2] == ["pr", "view"]:
            return json.dumps({"headRefOid": "b" * 40})
        if args[:2] == ["run", "list"]:
            if "master" in args:
                return json.dumps(self.master_runs)
            return json.dumps([{"databaseId": 2, "headSha": "b" * 40}])
        if args[:2] == ["run", "view"] and "--json" in args:
            coverage = "failure" if int(args[2]) in self.unmeasured else "success"
            jobs = [
                {"name": "pages", "conclusion": "failure", "databaseId": 90},
                {"name": "coverage", "conclusion": coverage, "databaseId": 100 + int(args[2])},
            ]
            return json.dumps({"jobs": jobs})
        if args[:3] == ["run", "view", "--job"]:  # the coverage job's log alone
            body = MASTER if args[3] == "101" else BRANCH
            return log(body)
        raise AssertionError(args)


def test_for_a_pr_it_compares_masters_last_green_run_with_the_pr_heads(capsys):
    fake = Gh()
    assert ci.main(["--pr", "44"], gh=fake) == 0
    out = capsys.readouterr().out
    assert out.startswith(
        "Before: master at aaaaaaaa (run 1). After: this branch at bbbbbbbb (run 2).\n\n| Area"
    )
    assert "| sandbox | 97.2% / 93.2% |" in out
    # each run's coverage job's own log, not the run's: a job cancelled unstarted has none
    assert ["run", "view", "--job", "101", "--repo", ci.REPO, "--log"] in fake.calls
    listed = [c for c in fake.calls if c[:2] == ["run", "list"]]
    assert listed[1][-2:] == ["--commit", "b" * 40] and "completed" in listed[0]


def test_a_run_counts_by_its_coverage_job_not_by_how_the_whole_run_ended(capsys):
    """Master's run after a merge failed at its Pages deploy, with its coverage measured: it is
    the base; a run whose coverage job didn't pass is passed over for the one before."""
    runs = [{"databaseId": 7, "headSha": "c" * 40}, {"databaseId": 1, "headSha": "a" * 40}]
    fake = Gh(master_runs=runs, unmeasured={7})
    base, _ = ci.runs_for_pr(fake, 58)
    assert base == {"id": "1", "sha": "a" * 40}
    assert ci.runs_for_pr(Gh(master_runs=runs), 58)[0]["id"] == "7"  # its pages job failed


def test_two_runs_by_id_are_compared_as_given(capsys):
    assert ci.main(["1", "2"], gh=Gh()) == 0
    assert capsys.readouterr().out.startswith(
        "Before: master at run 1. After: this branch at run 2."
    )


def test_no_green_run_or_no_table_stops_it_saying_why():
    with pytest.raises(SystemExit, match="whose coverage job passed"):
        ci.main(["--pr", "44"], gh=Gh(master_runs=[]))
    with pytest.raises(SystemExit, match="whose coverage job passed"):
        ci.main(["--pr", "44"], gh=Gh(unmeasured={1}))
    fake = Gh()
    with pytest.raises(SystemExit, match="no coverage table"):
        ci.run_areas(lambda a: fake(a) if "--json" in a else "coverage\tRun\tt none\n", "3")
    with pytest.raises(SystemExit, match="coverage job didn't pass"):
        ci.main(["1", "2"], gh=Gh(unmeasured={2}))  # a run given by id whose job failed


def test_it_wants_a_pr_or_two_runs():
    for argv in ([], ["1"], ["--pr", "4", "1", "2"]):
        with pytest.raises(SystemExit):
            ci.main(argv, gh=Gh())


def test_gh_is_run_and_its_output_returned(monkeypatch):
    seen = []

    class Done:
        stdout = "out"

    monkeypatch.setattr(ci.subprocess, "run", lambda cmd, **kw: seen.append(cmd) or Done())
    assert ci.gh(["run", "list"]) == "out" and seen == [["gh", "run", "list"]]
