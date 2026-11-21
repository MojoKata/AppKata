"""Mutation testing's tools (scripts/mutate.py, docs/testing.md "Mutation testing"): what a run
mutates and with which tests, how the baseline's jobs are packed, how mutmut's outcomes are counted,
and the baseline each area keeps in docs/hardening/mutation/.

How it would slip past: mutmut runs only in the mutate workflow, by hand, hours at a time, so a
mistake in the tools around it (a module no job holds, an outcome counted as another, a survivor
kept without its change) shows only in a baseline that is quietly wrong. These run the tools on
small made-up runs instead."""

import argparse
import importlib.util
import json
import os
import re
import subprocess
import sys

import pytest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
_spec = importlib.util.spec_from_file_location("appkata_mutate", os.path.join(ROOT, "scripts", "mutate.py"))
mutate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mutate)


def meta(mutants, rel, codes, name=None):
    """mutmut's .meta file for rel, a change per exit code."""
    path = mutants / f"{rel}.meta"
    path.parent.mkdir(parents=True, exist_ok=True)
    module = re.sub(r"^src\.", "", rel.removesuffix(".py").replace("/", "."))
    keys = {f"{module}.x_{name or 'f'}__mutmut_{i}": c for i, c in enumerate(codes, 1)}
    path.write_text(json.dumps({"exit_code_by_key": keys, "estimated_durations_by_key": {}}))
    return list(keys)


# --- what is mutated, in which jobs ---------------------------------------------------------------


def test_every_python_file_an_area_holds_is_mutated_but_qml_and_the_plugin():
    found = mutate.modules()
    assert found["src/appkata_core/windows.py"][0] == "windows"
    assert found["scripts/areas.py"][0] == "scripts"
    assert "scripts/mutate_plugin.py" not in found
    assert not [m for m in found if not m.endswith(".py")]
    held = {p for ps in mutate.areas.CODE.values() for p in ps if p.endswith(".py")}
    assert all(any(__import__("fnmatch").fnmatchcase(m, p) for p in held) for m in found)


def test_modules_are_packed_largest_first_and_a_large_one_is_a_job_of_its_own():
    jobs = mutate.pack({"a.py": 700, "b.py": 400, "c.py": 300, "d.py": 1500, "e.py": 200}, 1000)
    assert jobs == [["d.py"], ["a.py", "c.py"], ["b.py", "e.py"]]


def test_the_plan_names_each_areas_jobs_and_holds_every_module_once():
    found = mutate.modules()
    jobs = mutate.plan_jobs(found, ["*"], 1000)
    held = [m for j in jobs for m in j["modules"].split()]
    assert sorted(held) == sorted(found)
    assert {j["area"] for j in jobs} == {a for a, _ in found.values()}
    for j in jobs:
        assert re.fullmatch(rf"{re.escape(j['area'])}-\d+", j["name"])
        assert j["lines"] <= 1000 or len(j["modules"].split()) == 1
    windows = mutate.plan_jobs(found, ["win*"], 1000)      # the area's jobs alone, however many
    assert windows and all(re.fullmatch(r"windows-\d+", j["name"]) for j in windows)


def test_plan_takes_jobs_by_name_and_refuses_one_it_doesnt_have(capsys):
    assert mutate.main(["plan", "--jobs", "trust-1"]) == 0
    jobs = json.loads(capsys.readouterr().out)
    assert [j["name"] for j in jobs] == ["trust-1"]
    assert mutate.main(["plan", "--jobs", "windows-9"]) == 1
    assert mutate.main(["plan", "--modules", "src/appkata_core/nowhere.py"]) == 1


def test_the_workflows_trial_is_a_module_the_plan_has():
    with open(os.path.join(ROOT, ".github", "workflows", "mutate.yml"), encoding="utf-8") as f:
        text = f.read()
    trial = re.search(r"--modules (\S+?)'", text).group(1)
    assert trial in mutate.modules()
    assert "default: \"14\"" in text and "default: \"1000\"" in text


# --- a run's copy and settings --------------------------------------------------------------------


def test_a_run_uses_tier_1s_tests_less_those_it_cant(tmp_path):
    (tmp_path / "tests").mkdir()
    for name in ("test_a.py", "test_b.py", "conftest.py", "parts.py"):
        (tmp_path / "tests" / name).write_text("")
    assert mutate.tests(tmp_path) == ["tests/test_a.py", "tests/test_b.py"]
    text = mutate.settings([], [], "")
    for test in mutate.UNFIT:
        assert os.path.exists(os.path.join(ROOT, test.split("::")[0]))
        assert f'"--deselect", "{test}"' in text


def test_the_copy_holds_the_code_and_links_the_rest(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    for d in ("src/appkata_core", "scripts", "tests", "docs", "build", ".git"):
        (root / d).mkdir(parents=True)
    (root / "src/appkata_core/x.py").write_text("X = 1\n")
    (root / "docs/a.md").write_text("a\n")
    (root / "pyproject.toml").write_text("[tool.pytest.ini_options]\n")
    copy = tmp_path / "work" / "copy"
    monkeypatch.setattr(mutate, "ROOT", root)
    monkeypatch.setattr(mutate, "COPY", copy)
    monkeypatch.setattr(mutate, "MUTANTS", copy / "mutants")
    mutate.make_copy()
    assert (copy / "src/appkata_core/x.py").read_text() == "X = 1\n"
    assert not (copy / "src/appkata_core/x.py").is_symlink()
    assert (copy / "mutants/docs").is_symlink() and (copy / "mutants/docs/a.md").exists()
    assert (copy / "mutants/.git").is_symlink()     # the tests that ask git read the checkout
    assert not any((copy / "mutants" / n).exists() for n in ("build", "src", "pyproject.toml"))


def test_mutmuts_settings_replace_any_earlier_ones():
    text = mutate.settings(["src/appkata_core/windows.py"], ["tests/test_windows.py"],
                           "[tool.pytest.ini_options]\nx = 1\n\n[tool.mutmut]\nold = 1\n")  # fmt: skip
    assert "old = 1" not in text and text.count("[tool.mutmut]") == 1
    assert 'only_mutate = ["src/appkata_core/windows.py"]' in text
    assert 'do_not_mutate = ["scripts/mutate_plugin.py"]' in text
    assert 'process_isolation = "forkserver"' in text
    assert "[tool.pytest.ini_options]\nx = 1" in text


def test_only_and_only_file_name_the_changes_to_run(tmp_path):
    f = tmp_path / "only.txt"
    f.write_text("a__mutmut_1\nb__mutmut_2\n")
    args = argparse.Namespace(only=["c__mutmut_*"], only_file=str(f), workers=3)
    cmd = mutate.mutmut_command(args)
    assert cmd[1:] == ["-m", "mutmut", "run", "--max-children", "3", "c__mutmut_*", "a__mutmut_1", "b__mutmut_2"]


def test_a_worker_past_its_share_is_a_runaway():
    assert mutate.runaways({1: ("a", 0.5), 2: ("b", 2.5)}, 2.0) == [2]


# --- outcomes ----------------------------------------------------------------------------------


def test_outcomes_are_counted_by_file_and_the_odd_ones_as_other(tmp_path):
    # killed (1, 3, the watcher's stop), survived (0), no tests (33), timeout (36), not run, segfault (-11)
    meta(tmp_path, "src/appkata_core/urls.py", [1, 3, mutate.OUT_OF_MEMORY, 0, 33, 36, None, -11])
    meta(tmp_path, "scripts/areas.py", [0])
    by_file, by_fn, survivors = mutate.counted(mutate.codes(tmp_path))
    assert survivors == ["appkata_core.urls.x_f__mutmut_4", "scripts.areas.x_f__mutmut_1"]
    assert mutate.counts(by_file) == {"mutants": 9, "killed": 3, "timeout": 1, "survived": 2, "no tests": 1,
                                      "other": 1, "not run": 1}  # fmt: skip
    assert by_fn["appkata_core.urls.x_f"]["killed"] == 3


def test_a_later_directorys_outcome_wins_and_an_outcome_beats_none(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    meta(a, "src/appkata_core/urls.py", [0, None, 1])
    meta(b, "src/appkata_core/urls.py", [1, 0, None])
    codes = mutate.merged([a, b])["src/appkata_core/urls.py"]
    assert list(codes.values()) == [1, 0, 1]


def test_a_diff_is_its_lines_without_headers():
    shown = "--- a\n+++ a\n@@ -1,2 +1,2 @@\n def f(x):\n-    return x + 1\n+    return x - 1"
    assert mutate.hunk(shown) == [" def f(x):", "-    return x + 1", "+    return x - 1"]


def test_a_changes_function_and_line():
    assert mutate.function_of("appkata_core.urls.x_parse__mutmut_8") == "parse"
    assert mutate.function_of("appkata_core.db.xǁStoreǁget__mutmut_7") == "Store.get"
    text = "class Store:\n    def get(self, k):\n        if k:\n            return 1\n        return 2\n"
    diff = [" def get(self, k):", "     if k:", "-        return 1", "+        return None"]
    assert mutate.line_of(text, "Store.get", diff) == 4
    assert mutate.line_of(text, "Store.put", diff) is None


# --- the baseline --------------------------------------------------------------------------------


def job(tmp_path, name, area, modules, codes, survivors=""):
    d = tmp_path / name
    d.mkdir()
    keys = [k for m, c in codes.items() for k in meta(d, m, c, name="parse")]
    (d / "job.json").write_text(json.dumps({"name": name, "area": area, "modules": " ".join(modules)}))
    (d / "survivors.txt").write_text(survivors)
    return d, keys


def test_each_areas_baseline_keeps_its_outcomes_content_and_survivors(tmp_path, monkeypatch):
    text = "def parse(x):\n    return x + 1\n"
    monkeypatch.setattr(mutate, "blob_at", lambda commit, rel, repo: f"blob-{rel}")
    monkeypatch.setattr(mutate, "source", lambda blob: text)
    diff = "# appkata_core.urls.x_parse__mutmut_2\n def parse(x):\n-    return x + 1\n+    return x - 1\n"
    d1, _ = job(tmp_path, "sources-1", "sources", ["src/appkata_core/urls.py", "src/appkata_core/http.py"],
                {"src/appkata_core/urls.py": [1, 0, 36]}, diff)  # fmt: skip
    d2, _ = job(tmp_path, "trust-1", "trust", ["src/appkata_core/review.py"], {"src/appkata_core/review.py": [1]})
    records = tmp_path / "records"
    made = {"repo": "o/r", "runs": [1], "commit": "c", "mutmut": "3.8.1"}
    assert mutate.write_baselines([d1, d2], made, "c", "o/r", records) == 0
    got = json.loads((records / "sources.json").read_text())
    assert (got["area"], got["made"], got["mutants"], got["killed"], got["survived"], got["timeout"]) == (
        "sources", made, 3, 1, 1, 1)
    # a module mutmut found nothing to change in is kept too, with its content
    assert got["files"]["src/appkata_core/http.py"] == {"content": "blob-src/appkata_core/http.py", "mutants": 0,
                                                       **{k: 0 for k in mutate.COUNTED}}  # fmt: skip
    assert got["survivors"] == [{"name": "appkata_core.urls.x_parse__mutmut_2", "file": "src/appkata_core/urls.py",
                                 "function": "parse", "line": 2, "removed": ["    return x + 1"],
                                 "added": ["    return x - 1"]}]  # fmt: skip
    # a survivor a line
    assert (records / "sources.json").read_text().count("\n    {\"name\"") == 1
    assert json.loads((records / "trust.json").read_text())["survivors"] == []


def test_an_area_whose_job_ran_nothing_isnt_written(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(mutate, "blob_at", lambda commit, rel, repo: "b")
    d1, _ = job(tmp_path, "store-1", "store", ["src/appkata_core/db.py"], {"src/appkata_core/db.py": [None, None]})
    records = tmp_path / "records"
    assert mutate.write_baselines([d1], {}, "c", "o/r", records) == 1
    assert not (records / "store.json").exists()
    assert "store-1" in capsys.readouterr().out


def test_the_baselines_kept_name_files_that_exist_and_add_up():
    for path in sorted(mutate.RECORDS.glob("*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        assert record["area"] == path.stem and path.stem in mutate.areas.AREAS
        assert record["mutants"] == sum(record[k] for k in mutate.COUNTED), path.name
        assert record["survived"] == len(record["survivors"]), path.name
        for rel, c in record["files"].items():
            assert os.path.exists(os.path.join(ROOT, rel)), (path.name, rel)
            assert c["mutants"] == sum(c[k] for k in mutate.COUNTED), (path.name, rel)
        assert {s["file"] for s in record["survivors"]} <= set(record["files"]), path.name


@pytest.mark.skipif(not os.path.exists(os.path.join(ROOT, ".git")), reason="the copy isn't a checkout")
def test_a_files_content_is_its_blob_at_the_commit():
    rel = "scripts/areas.py"
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True)
    if head.returncode:
        pytest.skip("git can't read this checkout here")
    want = subprocess.run(["git", "rev-parse", f"HEAD:{rel}"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    assert mutate.blob_at(head.stdout.strip(), rel, "o/r") == want


def test_the_pin_is_read_from_versions_env():
    assert re.fullmatch(r"\d+\.\d+\.\d+", mutate.mutmut_pin())


def test_main_names_every_command():
    p = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "mutate.py"), "--help"],
                       capture_output=True, text=True)  # fmt: skip
    for what in ("run", "summary", "check", "plan", "export", "gather", "record"):
        assert what in p.stdout
