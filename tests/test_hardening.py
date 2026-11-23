"""scripts/hardening.py, the Pages site's hardening page: each sweep's steps and their findings from
the repository's issues (the review skill's sweep labels, anchors and sub-issues), read from GitHub's
GraphQL API, the findings by area as the history keeps them, and a step's result at its merge."""

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


ANCHOR = "<!-- review CR1 anchor -->"
ISSUES = [
    issue(1, "CR1 Code review", "sweep:CR1", body=f"The steps.\n\n{ANCHOR}"),
    issue(2, "CR1.2 trust", "sweep:CR1", "area:trust", parent=1, prs=[(70, "open"), (69, "closed")]),
    issue(3, "CR1.1 tooling", "sweep:CR1", "area:tooling", parent=1, state="closed", reason="completed",
          prs=[(54, "merged")]),
    issue(4, "CR1.2-1 A signature's key isn't checked", "sweep:CR1", "area:trust", parent=2,
          body="severity High\n\n**Kind:** bug\n\nThe key ..."),
    issue(5, "CR1.2-2 Who decides", "area:store", "question", parent=2, body="Severity: **Med**"),
    issue(6, "CR1.2-3 Fixed one", parent=2, state="closed", reason="completed",
          body="severity Low. Fixed by #71.", prs=[(72, "merged")]),
    issue(7, "CR1.2-4 Not a bug", parent=2, state="closed", reason="not_planned", body="severity low"),
    issue(8, "A finding titled otherwise", parent=2),
    issue(9, "CR1-1 A finding with no area", "sweep:CR1", parent=1),
    issue(10, "Generic HTML Sources", "gap", "area:sources"),
    issue(11, "A badge?", "question"),
    issue(12, "An old gap", "gap", state="closed", reason="completed"),
    issue(13, "Field test: 0.1.0", "field-test"),
    issue(14, "CR1.3-1 Not under a step", "sweep:CR1", parent=13),
    # a finding's question is its own, not among the gaps and questions
    issue(15, "CR1.2-5 Which one?", "question", parent=2),
    # the label `hardening` and its titles aren't read
    issue(16, "H1.6 Trust and signatures", "hardening", "area:trust"),
    issue(17, "H1.6-1 Under an old step", parent=16),
    # a later sweep, closed, whose anchor isn't the only issue with its label and no parent
    issue(18, "CR2-3 Strayed", "sweep:CR2"),
    issue(19, "CR2 Code review", "sweep:CR2", body="<!-- review CR2 anchor -->", state="closed",
          reason="completed"),
    issue(20, "CR2.1 sources", "sweep:CR2", "area:sources", parent=19, state="closed", reason="completed"),
]


def test_the_sweeps_steps_findings_gaps_and_questions_come_from_the_issues():
    sweeps, found, others = hardening.from_issues(ISSUES)
    assert [w["name"] for w in sweeps] == ["CR1", "CR2"]
    cr1, cr2 = sweeps
    assert (cr1["anchor"]["id"], cr1["anchor"]["issue"], cr1["anchor"]["what"]) == ("CR1", 1, "Code review")
    # the steps in their numbers' order, whatever the issues' order
    assert [(s["id"], s["issue"], s["done"], s["pr"]) for s in cr1["steps"]] == [
        ("CR1.1", 3, True, 54), ("CR1.2", 2, False, 70)]
    trust = cr1["steps"][1]
    assert trust["areas"] == ["trust"] and trust["findings"] == [4, 5, 6, 7, 8, 15]
    # the anchor, with no area of its own, covers its findings' areas
    assert cr1["anchor"]["findings"] == [9] and cr1["anchor"]["areas"] == [hardening.NO_AREA]
    assert cr2["anchor"]["issue"] == 19 and cr2["anchor"]["done"] and [s["id"] for s in cr2["steps"]] == ["CR2.1"]
    got = {f["id"]: f for f in found}
    assert got[4] == {"id": 4, "step": "CR1.2", "sev": "High", "desc": "A signature's key isn't checked",
                      "state": "open", "pr": None, "area": "trust"}
    assert [got[n]["state"] for n in (5, 6, 7, 8, 15)] == ["question", "fixed", "closed", "open", "question"]
    assert [got[n]["sev"] for n in (5, 6, 7, 8)] == ["Med", "Low", "Low", None]
    # the pull request is GitHub's link, never one the body names
    assert got[5]["area"] == "store" and got[6]["pr"] == 72
    assert got[8]["desc"] == "A finding titled otherwise"
    assert got[9]["step"] == "CR1" and got[9]["desc"] == "A finding with no area" and got[9]["area"] == hardening.NO_AREA
    assert not {14, 16, 17, 18} & set(got)
    assert others == [{"id": 10, "title": "Generic HTML Sources", "kind": "gap", "areas": ["sources"]},
                      {"id": 11, "title": "A badge?", "kind": "question", "areas": []}]


def test_a_step_in_parts_is_one_step_with_every_parts_findings():
    # An issue takes 100 sub-issues, so the review skill cuts a fuller step into parts.
    issues = [
        issue(1, "CR1 Code review", "sweep:CR1", body=ANCHOR),
        issue(2, "CR1.1 trust", "sweep:CR1", "area:trust", parent=1),
        issue(30, "CR1.2 docs (2 of 2)", "sweep:CR1", "area:docs", parent=1, prs=[(80, "open")]),
        issue(3, "CR1.2 docs (1 of 2)", "sweep:CR1", "area:docs", parent=1, state="closed", reason="completed"),
        issue(4, "CR1.2-1 In the first part", "area:docs", parent=3, body="severity Med"),
        issue(31, "CR1.2-2 In the second part", "area:docs", parent=30, body="severity Low"),
        issue(5, "CR1.3 tooling", "sweep:CR1", "area:tooling", parent=1),
    ]
    sweeps, found, others = hardening.from_issues(issues)
    steps = sweeps[0]["steps"]
    assert [(s["id"], s["what"], s["issue"], s["parts"]) for s in steps] == [
        ("CR1.1", "trust", 2, [2]), ("CR1.2", "docs", 3, [3, 30]), ("CR1.3", "tooling", 5, [5])]
    docs = steps[1]
    # each finding once, under the one step; open while a part is; the pull request of the part that has one
    assert docs["findings"] == [4, 31] and [f["step"] for f in found] == ["CR1.2", "CR1.2"]
    assert not docs["done"] and docs["pr"] == 80 and docs["areas"] == ["docs"]
    assert not others
    # done once every part is closed
    issues[2]["state"] = "closed"
    assert hardening.from_issues(issues)[0][0]["steps"][1]["done"]
    # the page names the parts
    text = hardening.page([point(1, 50.0, 0)], ["docs"], "https://github.com/SomeOne/Store", issues, {})
    assert '"parts":[3,30]' in text and "s.parts.map(issue)" in text


def test_a_steps_findings_are_the_issues_below_it_at_any_depth_but_for_answered_questions():
    issues = [
        issue(1, "CR1 Code review", "sweep:CR1", body=ANCHOR),
        issue(2, "CR1.1 trust", "sweep:CR1", "area:trust", parent=1),
        # a question answered: closed, and still labelled so; what it opened is filed below it
        issue(3, "CR1.1-1 Question: Which key?", "question", "area:trust", parent=2, state="closed",
              reason="completed"),
        issue(4, "A key's owner is checked", "area:trust", parent=3, body="severity Med"),
        # a question that became the work: no label any more, and its own sub-issues
        issue(5, "CR1.1-2 The second row is skipped", "area:trust", parent=2, body="severity Low"),
        issue(6, "The parser warns", "area:trust", parent=5),
        issue(7, "The warning is shown", "area:store", parent=6, state="closed", reason="completed"),
        # a question still waiting
        issue(8, "CR1.1-3 Question: Who decides?", "question", parent=2),
        # under the anchor: a question answered, and what it opened
        issue(9, "CR1-1 Question: Which runs?", "question", parent=1, state="closed", reason="completed"),
        issue(10, "A run to make", parent=9),
    ]
    sweeps, found, others = hardening.from_issues(issues)
    trust = sweeps[0]["steps"][0]
    assert trust["findings"] == [4, 5, 6, 7, 8]
    assert sweeps[0]["anchor"]["findings"] == [10]
    got = {f["id"]: f for f in found}
    assert set(got) == {4, 5, 6, 7, 8, 10} and {f["step"] for f in found} == {"CR1.1", "CR1"}
    assert [got[n]["state"] for n in (4, 5, 6, 7, 8)] == ["open", "open", "open", "fixed", "question"]
    assert got[7]["area"] == "store" and got[6]["desc"] == "The parser warns"
    # the answered questions are in no count, and aren't among the open questions either
    assert hardening.figures(["trust"], found)["trust"] == {"open": 4, "severe": 1, "fixed": 0, "all": 4}
    assert not others


def test_a_finding_waits_on_the_owner_under_refine_dismiss_or_question():
    issues = [
        issue(1, "CR1 Code review", "sweep:CR1", body=ANCHOR),
        issue(2, "CR1.1 trust", "sweep:CR1", "area:trust", parent=1),
        issue(3, "CR1.1-1 Which reading?", "refine", parent=2, body="severity High"),
        issue(4, "CR1.1-2 Not a defect", "dismiss", parent=2, body="severity Med"),
        issue(5, "CR1.1-3 Question: Who decides?", "question", parent=2),
        issue(6, "CR1.1-4 Plain", parent=2, body="severity Low"),
        # dismissed by the owner: closed, and never a fix, whatever reason the close was given
        issue(7, "CR1.1-5 Dismissed", "dismiss", parent=2, state="closed", reason="completed"),
        issue(8, "CR1.1-6 Fixed", parent=2, state="closed", reason="completed"),
    ]
    _, found, _ = hardening.from_issues(issues)
    got = {f["id"]: f["state"] for f in found}
    assert got == {3: "refine", 4: "dismiss", 5: "question", 6: "open", 7: "closed", 8: "fixed"}
    assert [hardening.is_open(f) for f in found] == [True, True, True, True, False, False]
    # waiting or not, an open High or Med finding is counted as severe
    assert hardening.figures(["trust"], found)["trust"] == {"open": 4, "severe": 2, "fixed": 2, "all": 6}
    text = hardening.page([point(1, 50.0, 0)], ["trust"], "https://github.com/SomeOne/Store", issues, {})
    assert "const waits = f => isOpen(f) && f.state !== 'open';" in text
    assert '"state":"refine"' in text


def test_no_sweep_label_is_no_sweeps():
    issues = [issue(1, "H1.6 Trust and signatures", "hardening", "area:trust"), issue(2, "A badge?", "question"),
              issue(3, "H1.6-1 Under it", parent=1)]
    sweeps, found, others = hardening.from_issues(issues)
    assert sweeps == [] and found == [] and [o["id"] for o in others] == [2]
    assert hardening.from_issues([]) == ([], [], [])


def test_the_sweeps_go_by_their_numbers():
    issues = [issue(n, f"{name} Code review", f"sweep:{name}") for n, name in ((1, "CR10"), (2, "CR2"), (3, "AB1"))]
    assert [w["name"] for w in hardening.from_issues(issues)[0]] == ["AB1", "CR2", "CR10"]


def test_the_findings_are_counted_by_area():
    found = hardening.from_issues(ISSUES)[1]
    got = hardening.figures(["trust", "store", "docs"], found)
    assert got["trust"] == {"open": 3, "severe": 1, "fixed": 2, "all": 5}
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
              "nodes": [node(1, "CR1 x", ["sweep:CR1"], state="CLOSED", reason="COMPLETED", prs=[(54, "MERGED")])]},
             {"pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": [node(2, "CR1-1 y", parent=1)]}]
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
    assert got[0] == {"number": 1, "title": "CR1 x", "body": "", "state": "closed", "reason": "completed",
                      "labels": ["sweep:CR1"], "parent": None, "prs": [(54, "merged")]}
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


def _data(text):
    return json.loads(text.split('type="application/json">', 1)[1].split("</script>", 1)[0])


def test_the_page_carries_its_data_and_no_body_text():
    history = [point(40, 80.0, 1), point(54, 81.0, 1)]
    text = hardening.page(history, ["trust", "tooling"], "https://github.com/SomeOne/Store", ISSUES)
    assert "/*DATA*/" not in text and "The key ..." not in text and "Fixed by" not in text
    data = _data(text)
    assert [(w["name"], w["anchor"]["id"], [s["id"] for s in w["steps"]]) for w in data["sweeps"]] == [
        ("CR1", "CR1", ["CR1.1", "CR1.2"]), ("CR2", "CR2", ["CR2.1"])]
    cr1 = data["sweeps"][0]
    assert cr1["steps"][0]["result"] == {"tooling": {"fixed": 0, "lines": None, "branches": None}}
    assert cr1["steps"][1]["result"] is None and cr1["anchor"]["result"] is None
    assert cr1["issues"] == "https://github.com/SomeOne/Store/issues?q=label%3Asweep%3ACR1"
    # the areas given, then any other a finding is in
    assert [a["area"] for a in data["areas"]] == ["trust", "tooling", hardening.NO_AREA, "store"]
    assert data["areas"][0]["now"] == {"lines": 81.0, "branches": 70.0}
    assert data["areas"][0]["was"] == {"lines": 80.0, "branches": 70.0}
    assert len(data["findings"]) == 7 and len(data["others"]) == 2
    assert "cr" not in data["findings"][0]
    assert data["head"]["pr"] == 54 and data["base"]["pr"] == 40


def test_the_page_works_with_no_sweeps():
    text = hardening.page([point(1, 50.0, 0)], ["trust"], "https://github.com/SomeOne/Store",
                          [issue(1, "A badge?", "question")])
    data = _data(text)
    assert data["sweeps"] == [] and data["findings"] == [] and [o["id"] for o in data["others"]] == [1]
    assert "No sweeps." in text


def test_a_title_cannot_close_the_page_s_script():
    issues = [issue(1, "CR1 x", "sweep:CR1"), issue(2, "CR1-1 </script><script>alert(1)", parent=1)]
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
    assert _data(text)["mutation"] == got
    assert "baseline, changed since" in hardening.PAGE.read_text(encoding="utf-8")


def test_the_checkouts_records_are_read_when_none_are_given():
    got = hardening.mutation()
    assert {"windows", "trust", "store"} <= set(got)
    assert all(v["record"] is None or v["record"].endswith(".json") for v in got.values())
