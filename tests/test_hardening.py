"""scripts/hardening.py, the Pages site's hardening page: a sweep's steps and their findings from the
repository's issues, read from GitHub's GraphQL API, the findings by area as the history keeps them,
and a step's result at its merge."""

import importlib.util
import io
import json
import os

import pytest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
_spec = importlib.util.spec_from_file_location("appkata_hardening", os.path.join(ROOT, "scripts", "hardening.py"))
hardening = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(hardening)


def issue(n, title, *labels, parent=None, state="open", reason=None, body="", prs=()):
    """An issue as fetch_issues gives it."""
    return {"number": n, "title": title, "body": body, "state": state, "reason": reason, "labels": list(labels),
            "parent": parent, "prs": list(prs)}


ISSUES = [
    issue(1, "H1.0 CI parts and coverage", "hardening", "area:tooling", state="closed", reason="completed",
          prs=[(54, "merged")]),
    issue(2, "H1.6 Trust and signatures", "hardening", "area:trust", prs=[(70, "open"), (69, "closed")]),
    issue(3, "H1.6-1 A signature's key isn't checked (CR1-14)", "hardening", parent=2,
          body="severity High, kind bug.\n\nThe key ..."),
    issue(4, "H1.6-2 Who decides", "area:store", "question", parent=2, body="Severity: **Med**"),
    issue(5, "H1.6-3 Fixed one", "hardening", parent=2, state="closed", reason="completed",
          body="severity Low. Fixed by #71."),
    issue(6, "H1.6-4 Not a bug", parent=2, state="closed", reason="not_planned", body="severity low"),
    issue(7, "A finding titled otherwise", parent=2),
    issue(8, "H1.5 Code review 1 (CR1)", "hardening", body="done by #66"),
    issue(9, "H1.5-1 A process finding", parent=8),
    issue(10, "H1.16 Release readiness", "hardening"),
    issue(11, "Generic HTML Sources", "gap", "area:sources"),
    issue(12, "A badge?", "question"),
    issue(13, "An old gap", "gap", state="closed", reason="completed"),
    issue(14, "Field test: 0.1.0", "field-test"),
    issue(15, "H1.7-1 Not under a step", "hardening", parent=14),
    issue(16, "H1.9 not a step: no label"),
]


def test_the_steps_findings_gaps_and_questions_come_from_the_issues():
    path, found, others = hardening.from_issues(ISSUES)
    assert [(s["id"], s["issue"], s["done"], s["pr"]) for s in path] == [
        ("H1.0", 1, True, 54), ("H1.5", 8, False, 66), ("H1.6", 2, False, 70), ("H1.16", 10, False, None)]
    trust = path[2]
    assert trust["areas"] == ["trust"] and trust["findings"] == [3, 4, 5, 6, 7]
    # a step with no area of its own covers its findings' areas
    assert path[1]["areas"] == [hardening.NO_AREA]
    got = {f["id"]: f for f in found}
    assert got[3] == {"id": 3, "step": "H1.6", "cr": "CR1-14", "sev": "High",
                      "desc": "A signature's key isn't checked", "state": "open", "pr": None, "area": "trust"}
    assert [got[n]["state"] for n in (4, 5, 6, 7)] == ["question", "fixed", "closed", "open"]
    assert [got[n]["sev"] for n in (4, 5, 6, 7)] == ["Med", "Low", "Low", None]
    assert got[4]["area"] == "store" and got[5]["pr"] == 71
    assert got[7]["desc"] == "A finding titled otherwise" and got[9]["area"] == hardening.NO_AREA
    assert 15 not in got and 16 not in got
    assert others == [{"id": 11, "title": "Generic HTML Sources", "kind": "gap", "areas": ["sources"]},
                      {"id": 12, "title": "A badge?", "kind": "question", "areas": []}]


def test_the_findings_are_counted_by_area():
    found = hardening.from_issues(ISSUES)[1]
    got = hardening.figures(["trust", "store", "docs"], found)
    assert got["trust"] == {"open": 2, "severe": 1, "fixed": 2, "all": 4}
    # a question is open, and its severity counts
    assert got["store"] == {"open": 1, "severe": 1, "fixed": 0, "all": 1}
    assert got["docs"] == {"open": 0, "severe": 0, "fixed": 0, "all": 0}
    assert got[hardening.NO_AREA]["all"] == 1


def node(n, title, labels=(), parent=None, state="OPEN", reason=None, prs=()):
    return {"number": n, "title": title, "body": None, "state": state, "stateReason": reason,
            "labels": {"nodes": [{"name": x} for x in labels]}, "parent": parent and {"number": parent},
            "closedByPullRequestsReferences": {"nodes": [{"number": p, "state": s} for p, s in prs]}}


def test_the_issues_are_read_page_by_page_with_the_token(monkeypatch):
    pages = [{"pageInfo": {"hasNextPage": True, "endCursor": "c1"},
              "nodes": [node(1, "H1.0 x", ["hardening"], state="CLOSED", reason="COMPLETED", prs=[(54, "MERGED")])]},
             {"pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": [node(2, "H1.0-1 y", parent=1)]}]
    asked = []

    def urlopen(req, timeout):
        body = json.loads(req.data)
        asked.append((body["variables"], req.get_header("Authorization")))
        return io.BytesIO(json.dumps({"data": {"repository": {"issues": pages[len(asked) - 1]}}}).encode())

    monkeypatch.setattr(hardening.urllib.request, "urlopen", urlopen)
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    got = hardening.fetch_issues("SomeOne/Store")
    assert [v for v, _ in asked] == [{"owner": "SomeOne", "name": "Store", "after": None},
                                     {"owner": "SomeOne", "name": "Store", "after": "c1"}]
    assert asked[0][1] == "Bearer t"
    assert got[0] == {"number": 1, "title": "H1.0 x", "body": "", "state": "closed", "reason": "completed",
                      "labels": ["hardening"], "parent": None, "prs": [(54, "merged")]}
    assert got[1]["parent"] == 1 and got[1]["reason"] is None


def test_an_answer_with_errors_fails(monkeypatch):
    monkeypatch.setattr(hardening.urllib.request, "urlopen",
                        lambda req, timeout: io.BytesIO(b'{"errors": [{"message": "no"}]}'))
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    with pytest.raises(ValueError, match="no"):
        hardening.fetch_issues("SomeOne/Store")


def test_the_token_comes_from_the_environment_or_gh_outside_ci(monkeypatch):
    for var in ("GITHUB_TOKEN", "GH_TOKEN", "GITHUB_ACTIONS"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("GH_TOKEN", "g")
    assert hardening.token() == "g"
    monkeypatch.delenv("GH_TOKEN")
    monkeypatch.setattr(hardening.shutil, "which", lambda name: "/usr/bin/gh")
    monkeypatch.setattr(hardening.subprocess, "run",
                        lambda *a, **k: hardening.subprocess.CompletedProcess(a, 0, "from-gh\n", ""))
    assert hardening.token() == "from-gh"
    # CI never asks gh
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    assert hardening.token() is None


def point(pr, lines, fixed):
    return {"pr": pr, "commit": f"{pr:040d}", "date": "2026-11-21T06:00:00-06:00", "subject": f"x (#{pr})",
            "areas": {"trust": {"lines": lines, "branches": 70.0}}, "hardening": {"trust": {"fixed": fixed}}}


def test_a_step_s_result_is_what_changed_at_its_merge():
    history = [point(40, 80.0, 1), point(41, 82.5, 4)]
    step = {"pr": 41, "areas": ["trust", "windows"]}
    assert hardening.result(step, history) == {
        "trust": {"fixed": 3, "lines": 2.5, "branches": 0.0},
        "windows": {"fixed": 0, "lines": None, "branches": None}}
    # the history's first entry has none before it, and a merge it doesn't hold has no result
    assert hardening.result({"pr": 40, "areas": ["trust"]}, history) is None
    assert hardening.result({"pr": 99, "areas": ["trust"]}, history) is None
    assert hardening.result({"pr": None, "areas": ["trust"]}, history) is None


def test_the_page_carries_its_data_and_no_body_text():
    history = [point(40, 80.0, 1), point(54, 81.0, 1)]
    text = hardening.page(history, ["trust", "tooling"], "https://github.com/SomeOne/Store", ISSUES)
    assert "/*DATA*/" not in text and "The key ..." not in text
    data = json.loads(text.split('type="application/json">', 1)[1].split("</script>", 1)[0])
    assert [s["id"] for s in data["steps"]] == ["H1.0", "H1.5", "H1.6", "H1.16"]
    assert data["steps"][0]["result"] == {"tooling": {"fixed": 0, "lines": None, "branches": None}}
    assert data["steps"][2]["result"] is None
    assert data["issues"] == "https://github.com/SomeOne/Store/issues?q=label%3Ahardening+no%3Aparent-issue"
    # the areas given, then any other a finding is in
    assert [a["area"] for a in data["areas"]] == ["trust", "tooling", hardening.NO_AREA, "store"]
    assert data["areas"][0]["now"] == {"lines": 81.0, "branches": 70.0}
    assert data["areas"][0]["was"] == {"lines": 80.0, "branches": 70.0}
    assert len(data["findings"]) == 6 and len(data["others"]) == 2
    assert data["head"]["pr"] == 54 and data["base"]["pr"] == 40


def test_a_title_cannot_close_the_page_s_script():
    issues = [issue(1, "H1.0 x", "hardening"), issue(2, "H1.0-1 </script><script>alert(1)", parent=1)]
    text = hardening.page([point(1, 50.0, 0)], ["trust"], "https://github.com/SomeOne/Store", issues)
    assert "</script><script>alert" not in text and "<\\/script><script>alert(1)" in text


def test_an_areas_mutation_testing_is_its_latest_records_and_what_changed_since(tmp_path):
    """The By area table's Mutation column (docs/testing.md, "Mutation testing"): an area's record's
    figures, and "baseline, changed since" when a module changed after it or isn't in it."""
    root, records = tmp_path / "repo", tmp_path / "records"
    (root / "src" / "appkata_core").mkdir(parents=True)
    for name in ("urls", "http", "review"):
        (root / "src" / "appkata_core" / f"{name}.py").write_text(f"{name.upper()} = 1\n")
    records.mkdir()
    m = hardening._mutate()
    same = m.blob(root / "src/appkata_core/urls.py")
    (records / "baseline-sources.json").write_text(json.dumps({
        "mutants": 9, "killed": 5, "timeout": 1, "survived": 3, "no tests": 0,
        "files": {"src/appkata_core/urls.py": {"content": same}, "src/appkata_core/http.py": {"content": "old"}}}))
    got = hardening.mutation(root, records)
    assert got["sources"] == {"record": "baseline-sources.json", "mutants": 9, "killed": 5, "timeout": 1,
                              "survived": 3, "noTests": 0, "changed": ["src/appkata_core/http.py"], "new": []}
    assert got["trust"] == {"record": None, "changed": [], "new": ["src/appkata_core/review.py"]}
    text = hardening.page([point(1, 50.0, 0)], ["trust"], "https://github.com/SomeOne/Store", [], got)
    data = json.loads(text.split('type="application/json">', 1)[1].split("</script>", 1)[0])
    assert data["mutation"] == got
    assert "baseline, changed since" in hardening.PAGE.read_text(encoding="utf-8")


def test_the_checkouts_records_are_read_when_none_are_given():
    got = hardening.mutation()
    assert {"windows", "trust", "store"} <= set(got)
    assert all(v["record"] is None or v["record"].endswith(".json") for v in got.values())
