"""The test plan's checklist is the one the field test runs and asks (review 3, E11).

How R3-38 slipped past: `docs/local-proxy-test-plan.md` lists what the field test checks by itself
and what it asks the tester, and `scripts/sandbox/fieldtest.py` runs and asks them. The two lists
were kept by hand, and a question added to the plan (A1-prompt, c1b69ae) and a check added to the
script (the exposure checks, 1c2c005) each reached only one of them. This reads both of the plan's
lists and every check and question the script records, and fails where they differ -- or when one
listed below agrees again, so the list shrinks.
"""

import ast
import json
import os
import re
import shutil
import subprocess
import sys

from test_requirements_trace import _finding_exists

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
PLAN = "docs/local-proxy-test-plan.md"
SCRIPT = "scripts/sandbox/fieldtest.py"
QUESTIONS = "scripts/sandbox/fieldtest_questions.py"       # what it asks, one list (the walk thru of 2026-10-30, item 4)

# ids only one side has, and the finding that keeps each
STILL_DIFFERENT: dict = {}

# a record only ever written with one of these says the field test couldn't run a check, or adds a
# note to one; it isn't a check of its own (INSTALL, D-capture, EXP, EXP-<template>-open)
NOT_A_RESULT = {"FAIL", "N/A", "INFO"}


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


def _section(text: str, heading: str) -> str:
    start = text.index(heading + "\n")
    m = re.search(r"^#{1,3} ", text[start + len(heading):], re.M)
    return text[start:start + len(heading) + m.start()] if m else text[start:]


def _plan(text: str) -> tuple[set, set]:
    """The plan's ids: the first column of "What it checks by itself", and the bold ids of "What it
    asks the tester". "A, B", "A / B" and "GUI-run (`--app`)" name one id each."""
    checks = set()
    for cell in re.findall(r"^\| ([^|]+?) \|", _section(text, "### What it checks by itself"), re.M):
        if cell in ("ID",) or set(cell) <= set("-"):
            continue
        checks |= {p.strip() for p in re.split(r",| / ", re.sub(r"\(`[^`]*`\)", "", cell)) if p.strip()}
    questions = set()
    for ids in re.findall(r"^- \*\*([^*]+?)\.\*\*", _section(text, "### What it asks the tester"), re.M):
        questions |= {p.strip() for p in ids.split(" / ")}
    return checks, questions


def _ids(node, exposure: tuple) -> list:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, ast.JoinedStr):         # f"EXP-{name}": one id per template the exposure check runs
        parts = [v.value if isinstance(v, ast.Constant) else "{}" for v in node.values]
        return ["".join(parts).replace("{}", name) for name in exposure]
    return []                                   # a variable: ask()'s own record of its question


def _asked(questions_text: str) -> set:
    """The ids of fieldtest_questions.py's QUESTIONS and SETUP_QUESTIONS, which fieldtest.py asks."""
    ids = set()
    for node in ast.parse(questions_text).body:
        if isinstance(node, ast.Assign) and node.targets[0].id in ("QUESTIONS", "SETUP_QUESTIONS"):
            ids |= {cid for cid, _ in ast.literal_eval(node.value)}
    return ids


def _script(text: str, questions_text: str = "") -> tuple[set, set]:
    """The script's ids: every r.rec() whose result can be a check's (not only NOT_A_RESULT), and
    every question it asks: each ask() of a string, and the lists it asks from."""
    tree = ast.parse(text)
    exposure: tuple = ()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_exposure":
            exposure = tuple(e.value for e in node.args[2].elts)
    results: dict = {}
    questions = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Attribute) and node.func.attr == "rec" and len(node.args) >= 2:
            status = node.args[0].value if isinstance(node.args[0], ast.Constant) else "a result"
            for cid in _ids(node.args[1], exposure):
                results.setdefault(cid, set()).add(status)
        elif isinstance(node.func, ast.Name) and node.func.id == "ask" and isinstance(node.args[2], ast.Constant):
            questions.add(node.args[2].value)
    if "from fieldtest_questions import QUESTIONS, SETUP_QUESTIONS" in text:
        questions |= _asked(questions_text)
    return {cid for cid, statuses in results.items() if statuses - NOT_A_RESULT}, questions


def _differences(plan_text: str, script_text: str, questions_text: str = "") -> dict:
    (plan_checks, plan_questions), (checks, questions) = _plan(plan_text), _script(script_text, questions_text or _read(QUESTIONS))
    return {**{c: "a check only the plan lists" for c in plan_checks - checks},
            **{c: "a check the plan doesn't list" for c in checks - plan_checks},
            **{q: "a question only the plan asks" for q in plan_questions - questions},
            **{q: "a question the plan doesn't list" for q in questions - plan_questions}}


def test_the_plan_lists_every_check_and_question_the_field_test_has_and_no_other():
    diff = _differences(_read(PLAN), _read(SCRIPT))
    report = "\n".join(f"  {cid}: {why}" for cid, why in sorted(diff.items()) if cid not in STILL_DIFFERENT)
    assert set(diff) - set(STILL_DIFFERENT) == set(), "the plan and the field test differ:\n" + report
    assert set(STILL_DIFFERENT) - set(diff) == set(), f"now agree (drop them from the list): {sorted(set(STILL_DIFFERENT) - set(diff))}"


def test_each_difference_names_a_finding_that_exists():
    for cid, fid in STILL_DIFFERENT.items():
        assert _finding_exists(fid), (cid, fid)


def test_the_harness_reads_both_sides_whole():
    checks, questions = _script(_read(SCRIPT), _read(QUESTIONS))
    assert {"ISO-keys", "ISO-net", "D-wayland", "D-sound", "T-cli-home", "GUI-run", "EXP-strict"} <= checks
    assert "INSTALL" not in checks and "EXP-strict-open" not in checks
    assert {"A1-pkexec", "E-native"} <= questions
    plan_checks, plan_questions = _plan(_read(PLAN))
    assert {"ISO-keys", "ISO-home", "D-x11", "D-nosound", "GUI-run"} <= plan_checks
    assert {"T-tray", "T-mpris", "E-native"} <= plan_questions


def test_the_harness_catches_a_question_or_a_check_added_to_one_side():
    script = _read(SCRIPT)
    asked = _read(QUESTIONS).replace('    ("E-native",', '    ("Z-new", "?"),\n    ("E-native",')
    assert _differences(_read(PLAN), script, asked).get("Z-new") == "a question the plan doesn't list"
    dropped = _read(PLAN).replace("| D-theme |", "| D-theme, D-gone |")
    assert _differences(dropped, script).get("D-gone") == "a check only the plan lists"


def test_the_setup_questions_are_asked_only_where_the_setup_applies(tmp_path):
    # R3-37 and R3-38: A1-prompt and A1-pkexec where the kernel restricts user namespaces and the
    # system has no bwrap profile of its own, N/A elsewhere. fieldtest.py moves HOME when imported,
    # so it runs in a process of its own.
    code = """
import json, shutil, sys
sys.path.insert(0, "scripts/sandbox")
import fieldtest as ft
out = []
for restricted, others in ((True, []), (True, ["bwrap-userns-restrict"]), (False, [])):
    ft.sb.userns_restricted = lambda: restricted
    ft.sb.other_bwrap_profiles = lambda: others
    r = ft.Report(sys.argv[1] + "/" + str(len(out)))
    ft._setup_questions(r, False)
    out.append([[row[0], row[1]] for row in r.rows])
shutil.rmtree(ft.FAKE, ignore_errors=True)
print(json.dumps(out))
"""
    res = subprocess.run([sys.executable, "-c", code, str(tmp_path)], cwd=ROOT, capture_output=True, text=True,
                         env={**os.environ, "PYTHONPATH": os.path.join(ROOT, "src")})
    assert res.returncode == 0, res.stderr[-1500:]
    needed, own_profile, unrestricted = json.loads(res.stdout.splitlines()[-1])
    assert needed == [["MANUAL", "A1-prompt"], ["MANUAL", "A1-pkexec"]]
    assert own_profile == unrestricted == [["N/A", "A1-prompt"], ["N/A", "A1-pkexec"]]


def test_each_environments_checklist_is_what_the_field_test_asks_there():
    """An environment's GitHub sub-issue holds one box per question the field test asks there, the A1
    questions only where testing.md says the setup is needed, and one for a real GPU (the walk thru
    of 2026-10-30, item 4): field-test.sh --issue-body prints it from the list fieldtest.py asks."""
    sys.path.insert(0, os.path.join(ROOT, "scripts", "sandbox"))
    import fieldtest_questions as fq
    envs = fq.environments()
    assert envs == {"Ubuntu 24.04 LTS": True, "Linux Mint 22.3": False, "LMDE 7": False, "Ubuntu 26.04 LTS": False}
    asked = _asked(_read(QUESTIONS))
    for env, needed in envs.items():
        boxes = re.findall(r"^- \[ \] \*\*([\w-]+)\*\* ", fq.issue_body(env), re.M)
        setup = [cid for cid, _ in fq.SETUP_QUESTIONS]
        assert boxes == (setup if needed else []) + [cid for cid, _ in fq.QUESTIONS] + ["D-gpu"], env
        assert set(boxes) - {"D-gpu"} <= asked and (set(setup) <= set(boxes)) == needed
    if shutil.which("sh"):                       # field-test.sh, a POSIX shell script, prints the same
        out = subprocess.run(["sh", os.path.join(ROOT, "scripts", "sandbox", "field-test.sh"), "--issue-body", "LMDE 7"],
                             capture_output=True, text=True, check=True).stdout
        assert out == fq.issue_body("LMDE 7")


def test_the_release_issues_template_names_the_same_environments():
    """.github/ISSUE_TEMPLATE/field-test.yml, for opening a release's issue by hand: labelled
    field-test, its environments testing.md's, in its order (read as text: tier 1 has no YAML)."""
    sys.path.insert(0, os.path.join(ROOT, "scripts", "sandbox"))
    import fieldtest_questions as fq
    text = _read(".github/ISSUE_TEMPLATE/field-test.yml")
    assert re.search(r'^labels: \["field-test"\]$', text, re.M)
    options = text[text.index("id: environments"):]
    assert re.findall(r"^        - label: (.+)$", options, re.M) == list(fq.environments())
