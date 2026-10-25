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
import subprocess
import sys

from test_requirements_trace import _finding_exists

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
PLAN = "docs/local-proxy-test-plan.md"
SCRIPT = "scripts/sandbox/fieldtest.py"

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


def _script(text: str) -> tuple[set, set]:
    """The script's ids: every r.rec() whose result can be a check's (not only NOT_A_RESULT), and
    every ask()."""
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
        elif isinstance(node.func, ast.Name) and node.func.id == "ask":
            questions.add(node.args[2].value)
    return {cid for cid, statuses in results.items() if statuses - NOT_A_RESULT}, questions


def _differences(plan_text: str, script_text: str) -> dict:
    (plan_checks, plan_questions), (checks, questions) = _plan(plan_text), _script(script_text)
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
    checks, questions = _script(_read(SCRIPT))
    assert {"ISO-keys", "ISO-net", "D-wayland", "D-sound", "T-cli-home", "GUI-run", "EXP-strict"} <= checks
    assert "INSTALL" not in checks and "EXP-strict-open" not in checks
    assert {"A1-pkexec", "E-native"} <= questions
    plan_checks, plan_questions = _plan(_read(PLAN))
    assert {"ISO-keys", "ISO-home", "D-x11", "D-nosound", "GUI-run"} <= plan_checks
    assert {"T-tray", "T-mpris", "E-native"} <= plan_questions


def test_the_harness_catches_a_question_or_a_check_added_to_one_side():
    script = _read(SCRIPT)
    asked = script.replace('ask(r, not a.non_interactive, "E-native"',
                           'ask(r, not a.non_interactive, "Z-new", "?")\n    ask(r, not a.non_interactive, "E-native"')
    assert _differences(_read(PLAN), asked).get("Z-new") == "a question the plan doesn't list"
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
