"""scripts/coverage_report.py, which totals tier 1's coverage by area, holds each area to its floor and
shows the changed lines no test reaches: its working out, without coverage.py's data."""

import importlib.util
import os

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
_spec = importlib.util.spec_from_file_location("coverage_report", os.path.join(ROOT, "scripts", "coverage_report.py"))
cr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cr)


def files():
    return {
        "src/appkata_core/trustfile.py": cr.File("trust", {1, 2, 3, 4}, {5, 6}, 4, 3),
        "src/appkata_core/gitsig.py": cr.File("trust", {1, 2}, set(), 0, 0),
        "scripts/public_text.py": cr.File("scripts", {1}, {2, 3, 4}, 2, 0),
    }


def test_files_are_totalled_by_area_in_the_areas_order():
    by = cr.totals(files())
    assert list(by) == ["trust", "scripts"]
    assert by["trust"] == {"files": 2, "lines": 75.0, "branches": 75.0, "lineCount": 8, "linesReached": 6,
                           "branchCount": 4, "branchesReached": 3}
    assert by["scripts"]["lines"] == 25.0 and by["scripts"]["branches"] == 0.0
    assert cr.total(by)["lineCount"] == 12 and cr.total(by)["linesReached"] == 7


def test_the_floor_is_what_was_reached_less_the_slack_and_only_rises():
    assert cr.slack_floor(100, 200) == 48.5
    assert cr.slack_floor(2, 10) == 0.0
    assert cr.slack_floor(1000, 1000) == 99.7
    by = {"trust": {"lineCount": 200, "linesReached": 103, "branchCount": 0, "branchesReached": 0}}
    assert cr.raised(by, {}) == {"trust": {"lines": 50.0}}
    assert cr.raised(by, {"trust": {"lines": 60.0}}) == {"trust": {"lines": 60.0}}
    # an area not measured this time keeps its floor
    assert cr.raised(by, {"windows": {"lines": 10.0}})["windows"] == {"lines": 10.0}


def test_an_area_below_its_floor_in_lines_or_branches_is_named():
    by = cr.totals(files())
    assert cr.under(by, {"trust": {"lines": 75.0, "branches": 75.0}}) == []
    assert cr.under(by, {"trust": {"lines": 75.1}}) == ["trust"]
    assert cr.under(by, {"scripts": {"branches": 1.0}, "windows": {"lines": 99}}) == ["scripts"]


DIFF = """diff --git a/src/appkata_core/trustfile.py b/src/appkata_core/trustfile.py
--- a/src/appkata_core/trustfile.py
+++ b/src/appkata_core/trustfile.py
@@ -3,0 +4,3 @@ def f():
+a
+b
+c
@@ -10 +13 @@
-x
+y
diff --git a/scripts/gone.py b/scripts/gone.py
--- a/scripts/gone.py
+++ /dev/null
@@ -1,2 +0,0 @@
"""


def test_the_changed_lines_come_from_the_diffs_hunks():
    assert cr.parse_diff(DIFF) == {"src/appkata_core/trustfile.py": {4, 5, 6, 13}}


def test_the_changed_lines_not_reached_are_shown_as_stretches():
    d = cr.diff(files(), {"src/appkata_core/trustfile.py": {4, 5, 6, 13}, "src/appkata_core/none.py": {1}})
    assert d == {"covered": 1, "lines": 3, "gaps": [("src/appkata_core/trustfile.py", 5, 6)]}
    assert cr.ranges({1, 2, 3, 7, 9, 10}) == [(1, 3), (7, 7), (9, 10)]
    lines = cr.annotations(cr.totals(files()), d)
    assert lines[0] == "::notice title=Coverage::58.3% of lines, 50.0% of branches; changed lines 1 of 3 reached"
    assert lines[1] == "::notice file=src/appkata_core/trustfile.py,line=5,endLine=6,title=Not reached::no test runs these lines"


def test_the_summary_shows_each_area_its_floor_qml_unmeasured_and_the_gaps():
    by = cr.totals(files())
    d = cr.diff(files(), {"src/appkata_core/trustfile.py": {5}})
    text = cr.summary(by, {"trust": {"lines": 80.0, "branches": 70.0}}, d, "HEAD^1", ["trust"], {"qml": 44})
    assert "**Changed lines** (since `HEAD^1`): 0 of 1 reached, 0.0%." in text
    assert "| trust ⚠ | 2 | 75.0% | 6 of 8 | 75.0% | 3 of 4 | 80.0% / 70.0% |" in text
    assert "| scripts | 1 | 25.0% | 1 of 4 | 0.0% | 0 of 2 | — |" in text
    assert "| qml | 44 | not measured" in text
    assert "- `src/appkata_core/trustfile.py`: 5" in text and "**Below the floor:** trust." in text


def test_the_committed_floors_are_areas_measured_and_percentages():
    fl = cr.floors()
    assert set(fl) <= set(cr.areas.CODE) - set(cr.UNMEASURED)
    for f in fl.values():
        assert set(f) <= {"lines", "branches"} and all(0 <= v <= 100 for v in f.values())
    assert list(fl) == list(cr.raised({}, fl))       # in the areas' order, as `floor` writes them
