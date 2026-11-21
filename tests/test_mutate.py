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
    got = json.loads((records / "baseline-sources.json").read_text())
    assert (got["area"], got["made"], got["mutants"], got["killed"], got["survived"], got["timeout"]) == (
        "sources", made, 3, 1, 1, 1)
    assert "survivors" not in got and got["dropped"] == {}
    # a module mutmut found nothing to change in is kept too, with its content
    assert got["files"]["src/appkata_core/http.py"] == {"content": "blob-src/appkata_core/http.py", "mutants": 0,
                                                       **{k: 0 for k in mutate.COUNTED}}  # fmt: skip
    text = (records / "survivors" / "sources.json").read_text()
    assert json.loads(text) == [{"name": "appkata_core.urls.x_parse__mutmut_2", "file": "src/appkata_core/urls.py",
                                 "function": "parse", "line": 2, "removed": ["    return x + 1"],
                                 "added": ["    return x - 1"]}]  # fmt: skip
    assert text.startswith('[\n{"name"') and text.count("\n") == 3      # a survivor a line
    assert (records / "survivors" / "trust.json").read_text() == "[]\n"
    assert not (records / "sources.json").exists()     # the name a settled record takes later


def test_a_job_run_again_later_is_the_later_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(mutate, "blob_at", lambda commit, rel, repo: "b")
    monkeypatch.setattr(mutate, "remade", lambda missing, content: {})       # no copy made here
    monkeypatch.setattr(mutate, "source", lambda blob: "")
    first, again = tmp_path / "1", tmp_path / "2"
    first.mkdir(), again.mkdir()
    d1, _ = job(first, "store-1", "store", ["src/appkata_core/db.py", "src/appkata_core/audit.py"],
                {"src/appkata_core/db.py": [1, 0], "src/appkata_core/audit.py": [0]})  # fmt: skip
    d2, _ = job(again, "store-1", "store", ["src/appkata_core/db.py"], {"src/appkata_core/db.py": [1, 1]})
    j = json.loads((d1 / "job.json").read_text())
    (d1 / "job.json").write_text(json.dumps({**j, "dropped": {"tests/test_x.py::test_y": {"kind": "unknown"}}}))
    records = tmp_path / "records"
    assert mutate.write_baselines([d1, d2], {}, "c", "o/r", records) == 0
    got = json.loads((records / "baseline-store.json").read_text())
    assert (got["killed"], got["survived"], got["dropped"]) == (2, 1, {})
    assert sorted(got["files"]) == ["src/appkata_core/audit.py", "src/appkata_core/db.py"]   # run again for db.py alone


def test_an_area_whose_job_ran_nothing_isnt_written(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(mutate, "blob_at", lambda commit, rel, repo: "b")
    d1, _ = job(tmp_path, "store-1", "store", ["src/appkata_core/db.py"], {"src/appkata_core/db.py": [None, None]})
    records = tmp_path / "records"
    assert mutate.write_baselines([d1], {}, "c", "o/r", records) == 1
    assert not (records / "baseline-store.json").exists()
    assert "store-1" in capsys.readouterr().out


def kept():
    """The baselines committed, each with its survivors: (area, record, survivors)."""
    for path in sorted(mutate.RECORDS.glob("baseline-*.json")):
        area = path.stem.removeprefix("baseline-")
        survivors = json.loads(mutate.survivors_path(area).read_text(encoding="utf-8"))
        yield area, json.loads(path.read_text(encoding="utf-8")), survivors


def test_the_baselines_kept_name_files_that_exist_and_add_up():
    assert list(kept()), "no baseline committed"
    for area, record, survivors in kept():
        assert record["area"] == area and area in mutate.areas.AREAS
        assert record["mutants"] == sum(record[k] for k in mutate.COUNTED), area
        assert record["survived"] == len(survivors), area
        for rel, c in record["files"].items():
            assert os.path.exists(os.path.join(ROOT, rel)), (area, rel)
            assert c["mutants"] == sum(c[k] for k in mutate.COUNTED), (area, rel)
        assert {s["file"] for s in survivors} <= set(record["files"]), area
        order = [(s["file"], s["line"] or 0) for s in survivors]
        assert order == sorted(order), area                     # each module's survivors in its order
    on_disk = {p.stem for p in (mutate.RECORDS / "survivors").glob("*.json")}
    assert on_disk == {a for a, _, _ in kept()}


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


# --- the commands, on made-up runs ------------------------------------------------------------------


@pytest.fixture(autouse=True)
def work(tmp_path, monkeypatch):
    """A work folder of its own, as APPKATA_MUTATE_WORK names one, for every test: a test never
    reaches the real one, which a mutation run running these tests is using (a remake makes the
    copy afresh, and the run's copy went with it)."""
    w = tmp_path / "work"
    monkeypatch.setattr(mutate, "WORK", w)
    monkeypatch.setattr(mutate, "COPY", w / "copy")
    monkeypatch.setattr(mutate, "MUTANTS", w / "copy" / "mutants")
    monkeypatch.setattr(mutate, "USERBASE", w / "userbase")
    (w / "copy" / "mutants").mkdir(parents=True)
    return w


def test_mutmut_and_its_metadata_alone_are_in_the_runs_user_site(tmp_path, work):
    site = tmp_path / "site"
    (site / "mutmut").mkdir(parents=True)
    (site / "mutmut-3.8.1.dist-info").mkdir()
    (site / "click").mkdir()
    mutate.link_mutmut(site / "mutmut")
    linked = mutate.user_site(work / "userbase")
    assert sorted(p.name for p in linked.iterdir()) == ["mutmut", "mutmut-3.8.1.dist-info", "usercustomize.py"]
    assert linked.as_posix().endswith(f"/lib/python{sys.version_info[0]}.{sys.version_info[1]}/site-packages")


def test_the_logs_spinner_frames_fold_into_their_last():
    text = "Generating mutants\n⠋ Running stats\r⠙ Running stats\r⠹ Running stats\nfailed to collect stats. runner returned 1\n"
    assert mutate.log_lines(text) == ["Generating mutants", "⠹ Running stats", "failed to collect stats. runner returned 1"]
    assert mutate.FIRST_PASS_FAILED.search(text)


def test_a_module_no_area_holds_isnt_run(work, capsys):
    assert mutate.main(["run", "src/appkata_core/nowhere.py"]) == 2
    assert "nowhere.py" in capsys.readouterr().out


def test_summary_counts_the_last_run_and_writes_each_survivors_change(work, monkeypatch, capsys):
    assert mutate.main(["summary"]) == 1                    # no run yet
    names = meta(work / "copy" / "mutants", "src/appkata_core/urls.py", [1, 0, 0], name="parse")
    asked = {}
    monkeypatch.setattr(mutate, "shown", lambda n, generate=False: asked.update(n) or {
        k: "@@ -1 +1 @@\n-    return 1\n+    return 2" for k in n})
    assert mutate.main(["summary"]) == 0
    out = capsys.readouterr().out
    assert "2 of    3  appkata_core.urls.x_parse" in out and "2 survivors" in out
    assert asked == {n: "src/appkata_core/urls.py" for n in names[1:]}
    assert (work / "survivors.txt").read_text() == "".join(f"# {n}\n-    return 1\n+    return 2\n" for n in names[1:])


def test_export_keeps_the_outcomes_the_survivors_and_the_log(work, tmp_path, monkeypatch):
    monkeypatch.setattr(mutate, "_run_pids", lambda: [])
    meta(work / "copy" / "mutants", "src/appkata_core/urls.py", [1, 0])
    meta(work / "copy" / "mutants", "scripts/areas.py", [1])
    (work / "mutmut.log").write_text("log\n")
    # a run stopped before its summary: its survivors' changes can't be shown, their names are kept
    monkeypatch.setattr(mutate, "shown", lambda n, generate=False: (_ for _ in ()).throw(OSError()))
    out = tmp_path / "export"
    assert mutate.main(["export", str(out), "--name", "sources-1", "--area", "sources",
                        "--modules", "src/appkata_core/urls.py"]) == 0  # fmt: skip
    assert json.loads((out / "job.json").read_text()) == {"name": "sources-1", "area": "sources",
                                                          "modules": "src/appkata_core/urls.py"}  # fmt: skip
    assert (out / "src/appkata_core/urls.py.meta").exists() and (out / "scripts/areas.py.meta").exists()
    assert (out / "survivors.txt").read_text() == "# appkata_core.urls.x_f__mutmut_2\n"
    assert (out / "mutmut.log").read_text() == "log\n"
    # after a summary, its survivors.txt is the one kept
    (work / "survivors.txt").write_text("# from the summary\n")
    assert mutate.main(["export", str(out), "--name", "sources-1", "--area", "sources", "--modules", "x"]) == 0
    assert (out / "survivors.txt").read_text() == "# from the summary\n"


def test_check_runs_one_change_against_one_test_file(work, monkeypatch, capsys):
    (work / "copy" / "mutants" / "tests").mkdir()
    ran = {}

    def fake_run(cmd, cwd, env):
        ran.update(cmd=cmd, cwd=cwd, env=env)
        return subprocess.CompletedProcess(cmd, 1)

    monkeypatch.setattr(mutate.subprocess, "run", fake_run)
    assert mutate.main(["check", "appkata_core.urls.x_parse__mutmut_2", "test_mutate.py"]) == 0
    assert "caught" in capsys.readouterr().out
    assert ran["env"]["MUTANT_UNDER_TEST"] == "appkata_core.urls.x_parse__mutmut_2"
    assert "tests/test_mutate.py" in ran["cmd"] and ran["cwd"] == work / "copy" / "mutants"
    assert (work / "copy" / "mutants" / "tests" / "test_mutate.py").exists()     # the test as it is now


def test_record_and_gather_write_each_areas_baseline_of_one_commit(work, tmp_path, monkeypatch):
    d, _ = job(tmp_path, "windows-1", "windows", ["src/appkata_core/windows.py"], {"src/appkata_core/windows.py": [1]})
    got = {}
    monkeypatch.setattr(mutate, "write_baselines", lambda dirs, made, commit, repo: got.update(
        dirs=dirs, made=made, commit=commit, repo=repo) or 0)
    monkeypatch.setattr(mutate, "_git", lambda *a: "c0ffee")
    assert mutate.main(["record", "--from", str(d)]) == 0
    assert got["made"] == {"repo": None, "runs": [], "commit": "c0ffee", "mutmut": mutate.mutmut_pin()}
    assert got["dirs"] == [d]

    monkeypatch.setattr(mutate, "downloaded", lambda run_id, repo: [d])
    heads = {"1": "a", "2": "a", "3": "b"}
    monkeypatch.setattr(mutate.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(
        cmd, 0, stdout=heads[cmd[3]] + "\n"))
    assert mutate.main(["gather", "1", "2"]) == 0
    assert got["made"] == {"repo": mutate.REPO, "runs": [1, 2], "commit": "a", "mutmut": mutate.mutmut_pin()}
    assert got["dirs"] == [d, d] and got["repo"] == mutate.REPO
    assert mutate.main(["gather", "1", "3"]) == 1        # two commits don't add up
    # a fork's run, recorded without the fork's name, as a commit of this repository with its code
    monkeypatch.setattr(mutate, "blob_at", lambda commit, rel, repo: "same" if commit in ("a", "c0ffee") else "other")
    assert mutate.main(["gather", "1", "--repo", "someone/AppKata", "--same-as", "HEAD"]) == 0
    assert got["made"] == {"repo": "a fork", "runs": [1], "commit": "c0ffee", "mutmut": mutate.mutmut_pin()}
    assert got["repo"] == mutate.REPO
    # runs of two such commits, each with the code of the one recorded (a run resumed after a fix)
    heads["3"] = "a2"
    monkeypatch.setattr(mutate, "blob_at", lambda commit, rel, repo: "same" if commit in ("a", "a2", "c0ffee") else "x")
    assert mutate.main(["gather", "1", "3", "--repo", "someone/AppKata", "--same-as", "HEAD"]) == 0
    assert got["made"]["runs"] == [1, 3] and got["made"]["commit"] == "c0ffee"
    monkeypatch.setattr(mutate, "_git", lambda *a: "beef")
    assert mutate.main(["gather", "1", "--repo", "someone/AppKata", "--same-as", "HEAD"]) == 1


def test_a_runs_artifacts_are_downloaded_once(work, monkeypatch):
    calls = []

    def fake_run(cmd, check):
        calls.append(cmd)
        dest = __import__("pathlib").Path(cmd[cmd.index("-D") + 1])
        (dest / "mutation-store-1").mkdir(parents=True)
        (dest / "mutation-store-1" / "job.json").write_text("{}")

    monkeypatch.setattr(mutate.subprocess, "run", fake_run)
    first = mutate.downloaded("7", "o/r")
    assert [p.name for p in first] == ["mutation-store-1"]
    assert mutate.downloaded("7", "o/r") == first and len(calls) == 1
    assert calls[0][:4] == ["gh", "run", "download", "7"] and "o/r" in calls[0]


def test_the_watcher_finds_no_run_when_none_is_running(work):
    assert mutate._run_pids() == [] and mutate._workers() == {} and mutate._pss_gb() == 0.0


def test_a_run_goes_on_from_an_earlier_ones_outcomes(work, tmp_path):
    earlier = tmp_path / "earlier"
    meta(earlier, "src/appkata_core/urls.py", [1, 0, None])
    meta(earlier, "scripts/areas.py", [None])
    assert mutate.resume(earlier) == 2
    assert mutate.codes(work / "copy" / "mutants") == mutate.codes(earlier)


def test_a_test_failing_in_the_copy_is_named_with_its_traceback_and_kind():
    out = ["....F", "=== short test summary info ===",
           "FAILED tests/test_field_test_plan.py::test_the_plan - AttributeError: 'Constant' object has no attribute 'elts'",
           "1 failed, 206 passed", "ERROR tests/test_x.py::test_y",
           "FAILED tests/test_field_test_plan.py::test_the_plan"]  # fmt: skip
    assert mutate.failed_tests(out) == ["tests/test_field_test_plan.py::test_the_plan", "tests/test_x.py::test_y"]
    assert mutate.failed_tests(["1 passed"]) == []
    shown = ["....F", "=== FAILURES ===", "___ test_the_plan ___", "tests/x.py:84: in _script",
             "    exposure = tuple(e.value for e in node.args[2].elts)",
             "E   AttributeError: 'Constant' object has no attribute 'elts'", "",
             "=== short test summary info ===", "FAILED tests/x.py::test_the_plan"]  # fmt: skip
    trace = mutate.short_trace(shown)
    assert trace.splitlines()[0] == "tests/x.py:84: in _script" and trace.endswith("no attribute 'elts'")
    assert len(mutate.short_trace(["___ t ___", *[f"line {i}" for i in range(50)]]).splitlines()) == mutate.TRACE_LINES
    assert mutate.kind_of(trace) == "reads the mutated source"
    assert mutate.kind_of("fatal: pathspec 'docs/x' is beyond a symbolic link") == "git or links in the copy"
    assert mutate.kind_of("E   subprocess.CalledProcessError: ... returned 1") == "leaks into processes tests start"
    assert mutate.kind_of("E   assert 1 == 2") == mutate.UNKNOWN


def test_a_dropped_tests_unfit_entry_is_printed_unless_unfit_has_it(capsys):
    unfit = next(iter(mutate.UNFIT))
    dropped = {"tests/test_x.py::test_y": {"kind": "reads the mutated source", "trace": "..."}, unfit: {"kind": "x"}}
    assert mutate.unfit_entries(dropped) == ['    "tests/test_x.py::test_y": "reads the mutated source: <why, in a line>",']
    mutate.print_unfit(dropped)
    assert '"tests/test_x.py::test_y"' in capsys.readouterr().out
    mutate.print_unfit({})
    assert capsys.readouterr().out == ""
    # an earlier run kept a line, or the summary's own
    assert mutate.as_kept("FAILED tests/test_x.py::test_y") == {"kind": mutate.UNKNOWN, "trace": ""}
    assert mutate.as_kept("AttributeError: 'Constant' object has no attribute 'elts'")["kind"] == "reads the mutated source"


def test_a_test_failing_on_the_checkout_too_stops_the_run_and_one_failing_in_the_copy_only_is_dropped(work, monkeypatch, capsys):
    passes = {"tests/test_a.py::test_copy": True, "tests/test_b.py::test_real": False}
    rounds = iter([["tests/test_a.py::test_copy"], ["tests/test_b.py::test_real"]])
    monkeypatch.setattr(mutate, "modules", lambda: {"src/appkata_core/urls.py": ("sources", 10)})
    for name in ("make_copy", "link_mutmut", "configure"):
        monkeypatch.setattr(mutate, name, lambda *a, **k: None)
    monkeypatch.setattr(mutate, "tests", lambda: ["tests/test_a.py"])
    monkeypatch.setattr(mutate, "summary", lambda _a: 0)

    def mutmut_fails(args):
        (work / "mutmut.log").write_text("failed to collect stats. runner returned 1\n")
        return 1, False

    monkeypatch.setattr(mutate, "mutmut", mutmut_fails)
    monkeypatch.setattr(mutate, "first_failure", lambda selected, dropped: (next(rounds), "FAILED"))
    monkeypatch.setattr(mutate, "passes_as_written", lambda t: passes[t])
    monkeypatch.setattr(mutate, "traceback_of", lambda t: "E   AttributeError: 'Constant' object has no attribute 'elts'")
    assert mutate.main(["run", "src/appkata_core/urls.py"]) == 3
    out = capsys.readouterr().out
    assert "left out of this run" in out and "a real failure" in out and "tests/test_b.py::test_real" in out
    kept = json.loads((work / mutate.DROPPED_FILE).read_text())
    assert kept == {"tests/test_a.py::test_copy": {"kind": "reads the mutated source",
                                                  "trace": "E   AttributeError: 'Constant' object has no attribute 'elts'"}}


def test_passes_as_written_runs_the_test_on_the_checkout(monkeypatch):
    seen = {}
    monkeypatch.setattr(mutate.subprocess, "run", lambda cmd, cwd, env, **k: seen.update(cmd=cmd, cwd=cwd, env=env)
                        or subprocess.CompletedProcess(cmd, 0))  # fmt: skip
    monkeypatch.setenv("MUTANT_UNDER_TEST", "stats")
    assert mutate.passes_as_written("tests/test_x.py::test_y")
    assert seen["cwd"] == mutate.ROOT and "MUTANT_UNDER_TEST" not in seen["env"] and seen["cmd"][-1] == "tests/test_x.py::test_y"


def test_a_dropped_test_is_deselected_and_kept_in_the_baseline(tmp_path, monkeypatch):
    text = mutate.settings([], [], "", dropped={"tests/test_x.py::test_y": {"kind": "unknown", "trace": "why"}})
    assert '"--deselect", "tests/test_x.py::test_y"' in text
    monkeypatch.setattr(mutate, "source", lambda blob: "")
    d, _ = job(tmp_path, "store-1", "store", ["src/appkata_core/db.py"], {"src/appkata_core/db.py": [1]})
    j = json.loads((d / "job.json").read_text())
    (d / "job.json").write_text(json.dumps({**j, "dropped": {"tests/test_x.py::test_y": "why"}}))
    record = mutate.baseline("store", [d], {}, {"src/appkata_core/db.py": "b"})
    assert record["dropped"] == {"tests/test_x.py::test_y": {"kind": "unknown", "trace": "why"}}


# --- inside a run (mutate_plugin) ----------------------------------------------------------------

_pspec = importlib.util.spec_from_file_location("appkata_mutate_plugin", os.path.join(ROOT, "scripts", "mutate_plugin.py"))
plugin = importlib.util.module_from_spec(_pspec)
_pspec.loader.exec_module(plugin)


def test_a_script_runs_under_the_name_mutmut_gives_it_whatever_it_is_imported_as(tmp_path, monkeypatch):
    scripts = tmp_path / "scripts"
    (scripts / "sandbox").mkdir(parents=True)
    (scripts / "sandbox" / "probe.py").write_text("def where():\n    return __name__\n")
    monkeypatch.setattr(plugin, "SCRIPTS", str(scripts))
    assert plugin.canonical(scripts / "sandbox" / "probe.py") == "scripts.sandbox.probe"
    assert plugin.canonical(tmp_path / "other.py") is None
    from importlib.machinery import SourceFileLoader

    # undone after; Python's own, also where mutmut's session (this plugin) has named it already
    current = SourceFileLoader.exec_module
    monkeypatch.setattr(SourceFileLoader, "exec_module", getattr(current, "original", current))
    plugin._named_as_mutmut_names_it()
    plugin._named_as_mutmut_names_it()                     # once only
    spec = importlib.util.spec_from_file_location("some_test_name", scripts / "sandbox" / "probe.py")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
        assert module.__name__ == "some_test_name"        # the module keeps the name it was imported by
        assert module.where.__module__ == "scripts.sandbox.probe"     # the name its functions were made under
    finally:
        sys.modules.pop("scripts.sandbox.probe", None)


def test_a_tests_own_python_runs_mutmuts_first_pass_unchanged(tmp_path):
    for value, want in (("stats", ""), ("appkata_core.urls.x_parse__mutmut_1", "appkata_core.urls.x_parse__mutmut_1")):
        env = {**os.environ, "MUTANT_UNDER_TEST": value}
        code = mutate.USERCUSTOMIZE + "print(repr(os.environ['MUTANT_UNDER_TEST']))"
        r = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, check=True)
        assert r.stdout.strip() == repr(want)


# --- stale ------------------------------------------------------------------------------------------


def test_a_blob_is_gits_name_for_the_content(tmp_path):
    f = tmp_path / "x.py"
    f.write_text("X = 1\n")
    assert mutate.blob(f) == "96766802bd555f14ace322a7f376c4551f1bf5b7"          # `git hash-object` of the same file


def test_stale_names_the_modules_changed_since_their_latest_record_and_those_none_covers(tmp_path, capsys):
    root, records = tmp_path / "repo", tmp_path / "records"
    for rel, text in (("src/appkata_core/urls.py", "U = 1\n"), ("src/appkata_core/http.py", "H = 1\n"),
                      ("src/appkata_core/review.py", "R = 1\n")):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text)
    records.mkdir()
    same = mutate.blob(root / "src/appkata_core/urls.py")

    def keep(name, files):
        (records / name).write_text(json.dumps({"files": {rel: {"content": c} for rel, c in files.items()}}))

    keep("baseline-sources.json", {"src/appkata_core/urls.py": same, "src/appkata_core/http.py": "old"})
    found = mutate.stale_modules(root, records)
    assert {(f["module"], f["state"], f["record"]) for f in found} == {
        ("src/appkata_core/http.py", "changed since", "baseline-sources.json"),
        ("src/appkata_core/review.py", "no record", None)}
    # a settled record (<area>.json) is an area's latest, over its baseline
    keep("sources.json", {"src/appkata_core/urls.py": same, "src/appkata_core/http.py": mutate.blob(root / "src/appkata_core/http.py")})
    assert [f["module"] for f in mutate.stale_modules(root, records)] == ["src/appkata_core/review.py"]
    keep("trust.json", {"src/appkata_core/review.py": mutate.blob(root / "src/appkata_core/review.py")})
    assert mutate.stale_modules(root, records) == []


def test_stale_prints_each_module_and_what_holds_its_counts(monkeypatch, capsys):
    monkeypatch.setattr(mutate, "stale_modules", lambda: [
        {"area": "scripts", "module": "scripts/areas.py", "state": "changed since", "record": "baseline-scripts.json"},
        {"area": "scripts", "module": "scripts/hardening.py", "state": "no record", "record": "baseline-scripts.json"},
        {"area": "qmlx", "module": "x.py", "state": "no record", "record": None}])
    assert mutate.main(["stale"]) == 0
    out = capsys.readouterr().out
    assert "changed since baseline-scripts.json's run" in out
    assert "in no record (baseline-scripts.json doesn't hold it)" in out and out.count("in no record") == 2
    assert "3 modules, in 2 areas" in out
    monkeypatch.setattr(mutate, "stale_modules", lambda: [])
    mutate.main(["stale"])
    assert "every module is as its latest record mutated it" in capsys.readouterr().out


# --- a survivor's change made again -----------------------------------------------------------------


def test_a_survivor_no_job_showed_is_found_and_made_again_from_its_modules_recorded_code(tmp_path, work, monkeypatch):
    diff = "# appkata_core.urls.x_parse__mutmut_2\n def parse(x):\n-    return x + 1\n+    return x - 1\n"
    d, keys = job(tmp_path, "sources-1", "sources", ["src/appkata_core/urls.py"],
                  {"src/appkata_core/urls.py": [0, 0]}, diff + "# appkata_core.urls.x_parse__mutmut_1\n")  # fmt: skip
    assert mutate.unshown([d]) == {"appkata_core.urls.x_parse__mutmut_1": "src/appkata_core/urls.py"}
    monkeypatch.setattr(mutate, "source", lambda blob: f"def parse(x):  # {blob}\n    return x + 1\n")
    monkeypatch.setattr(mutate.importlib.util, "find_spec", lambda name: None)
    ran = []

    def container(cmd, check):
        ran.append(cmd)
        asked = json.loads((work / "remake-in.json").read_text())
        assert asked == {"names": {"appkata_core.urls.x_parse__mutmut_1": "src/appkata_core/urls.py"},
                         "sources": {"src/appkata_core/urls.py": "def parse(x):  # b1\n    return x + 1\n"}}
        (work / "remake-out.json").write_text(json.dumps({"appkata_core.urls.x_parse__mutmut_1": ["-a", "+b"]}))

    monkeypatch.setattr(mutate.subprocess, "run", container)
    got = mutate.remade(mutate.unshown([d]), {"src/appkata_core/urls.py": "b1"})
    assert got == {"appkata_core.urls.x_parse__mutmut_1": ["-a", "+b"]}
    assert ran[0][1].endswith("scripts/test-mutate.sh") and ran[0][2:] == ["remake", "/work/remake-in.json", "/work/remake-out.json"]
    entries = mutate.survivor_entries([d], {"src/appkata_core/urls.py": "b1"}, got)
    assert {e["name"]: (e["removed"], e["added"]) for e in entries}["appkata_core.urls.x_parse__mutmut_1"] == (["a"], ["b"])
    assert mutate.remade({"x": "src/nowhere.py"}, {}) == {}


def test_remake_makes_the_copy_of_the_modules_asked_and_keeps_the_diffs_lines(work, tmp_path, monkeypatch):
    made = []
    monkeypatch.setattr(mutate, "make_copy", lambda: made.append("copy"))
    monkeypatch.setattr(mutate, "link_mutmut", lambda: made.append("link"))
    monkeypatch.setattr(mutate, "configure", lambda mutate_, selected: made.append(("configure", mutate_)))
    monkeypatch.setattr(mutate, "shown", lambda names, generate, sources: {
        "a__mutmut_1": "--- f\n+++ f\n@@ -1 +1 @@\n-x\n+y", "a__mutmut_2": ""})
    inp, out = tmp_path / "in.json", tmp_path / "out.json"
    inp.write_text(json.dumps({"names": {"a__mutmut_1": "scripts/a.py", "a__mutmut_2": "scripts/a.py"},
                               "sources": {"scripts/a.py": "def a(): pass\n"}}))  # fmt: skip
    assert mutate.main(["remake", str(inp), str(out)]) == 0
    assert made == ["copy", "link", ("configure", ["scripts/a.py"])]
    assert json.loads(out.read_text()) == {"a__mutmut_1": ["-x", "+y"]}


def test_own_diff_reads_a_change_whose_functions_name_holds_mutmuts_marker(tmp_path):
    mutated = tmp_path / "m.py"
    mutated.write_text(
        "def x__mutmut_pids__mutmut_orig(a):\n    return a + 1\n\n"
        "def x__mutmut_pids__mutmut_2(a):\n    return a - 1\n\n"
        "class K:\n    def xǁKǁget__mutmut_orig(self):\n        return 1\n    def xǁKǁget__mutmut_1(self):\n        return 2\n")
    lines = mutate.hunk(plugin.own_diff("scripts.mutate.x__mutmut_pids__mutmut_2", str(mutated)))
    assert lines == [" def _mutmut_pids(a):", "-    return a + 1", "+    return a - 1"]
    assert mutate.hunk(plugin.own_diff("m.xǁKǁget__mutmut_1", str(mutated))) == [" def get(self):", "-    return 1", "+    return 2"]
    assert plugin.own_diff("m.x_gone__mutmut_1", str(mutated)) == ""
    assert plugin.own_diff("m.x_gone__mutmut_1", str(tmp_path / "none.py")) == ""
