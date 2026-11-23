"""Every module, script and test file is in exactly one area (scripts/areas.py), so each counts in one
area's coverage and one area's durations file, and the areas are the repository's Area values.

How it would slip past: a new module or test file in no area's list is left out of every area's
total, and its tests' times fall into no durations file, with nothing to say so."""

import glob
import importlib.util
import os
import subprocess
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
_spec = importlib.util.spec_from_file_location("appkata_areas", os.path.join(ROOT, "scripts", "areas.py"))
areas = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(areas)


def _files(*patterns):
    out = []
    for p in patterns:
        out += [os.path.relpath(f, ROOT).replace(os.sep, "/") for f in glob.glob(os.path.join(ROOT, p))]
    return sorted(f for f in out if os.path.isfile(os.path.join(ROOT, f)) and "__pycache__" not in f)


def test_every_module_and_script_is_in_one_area():
    code = _files("src/*/*.py", "src/appkata/qml/*", "scripts/*.py", "scripts/sandbox/*.py")
    assert "src/appkata_core/sandbox.py" in code and "scripts/public_text.py" in code
    assert [f for f in code if areas.area_of_code(f) is None] == []


def test_every_test_file_is_in_one_area():
    tests = _files("tests/test_*.py")
    assert [f for f in tests if areas.area_of_test(f) is None] == []
    assert areas.area_of_test("tests/test_trust.py::test_x[1]") == "trust"


def test_each_pattern_matches_something_and_the_areas_are_the_area_values():
    for table in (areas.CODE, areas.TESTS):
        assert set(table) <= set(areas.AREAS)
        for area, patterns in table.items():
            for p in patterns:
                assert glob.glob(os.path.join(ROOT, p)), f"{area}: {p} matches nothing"
    assert len(areas.AREAS) == len(set(areas.AREAS)) == 12


def test_a_file_in_two_areas_is_in_none():
    assert areas._area({"a": ["x/*.py"], "b": ["x/y.py"]}, "x/y.py") is None
    assert areas._area({"a": ["x/*.py", "x/y.py"]}, "x/y.py") == "a"


def test_run_it_prints_the_areas_one_per_line():
    # docs/review.json's areas_command: the review's steps, one per line, in AREAS' order
    out = subprocess.run([sys.executable, "-B", os.path.join(ROOT, "scripts", "areas.py")],
                         capture_output=True, text=True, check=True).stdout
    assert out == "".join(f"{a}\n" for a in areas.AREAS)
