"""Every promise a requirement makes is shown by a test, or named as open (review 3, harness B).

Review 2's class B: a decision recorded but never built. Requirement 17.12 promised a "Disable the
app's own updater" install option for releases; 17.4 a "Show the launch command"; 17.10 an "if
declined" prompt. None was built, and no test noticed, because nothing tied a sentence of the
requirements to a test. docs/requirements-trace.md does: one row per sentence (and table row) of
each covered section, naming the tests that show it, a harness mode, a claim with evidence, a
finding that keeps it open, `deferred` or `statement`. This test splits the section the same way
and fails when a sentence has no row, a row no longer matches its sentence, a named test or harness
doesn't exist, or the rows still open differ from the list below.

A second check covers the same class from the other side: a Backend slot or property no QML file
uses is either a promise the UI never got (sandboxLaunchCommand: 17.4's "Show the launch command")
or dead code.
"""

import os
import re

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")

# what is still open, and which finding keeps it so (each must exist in docs/reviews/)
STILL_OPEN: set = set()
# Backend slots/properties no QML uses, and why each is still so
STILL_UNWIRED = {
}


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.replace("*", "").replace("`", "")).strip()


def section_units(text: str, number: int) -> list[tuple[str, str]]:
    """(requirement id, unit) for every sentence and table row of section `number`: the split
    docs/requirements-trace.md is written against."""
    start = text.index(f"\n## {number}. ")
    end = text.find("\n## ", start + 1)
    sec = text[start:end if end > 0 else None]
    out = []
    for item in re.split(rf"\n(?={number}\.[0-9.]+ )", sec)[1:]:
        rid = re.match(rf"({number}\.[0-9.]*[0-9])", item).group(1)
        prose, rows = [], []
        for line in item.split("\n"):
            if line.startswith("|"):
                if not re.match(r"^\|[-| ]+\|$", line) and not re.match(r"^\| (Level|Template) \|", line):
                    rows.append(_norm(line))
            else:
                prose.append(line)
        body = re.sub(rf"^{number}\.[0-9.]*[0-9]\.? ", "", _norm(" ".join(prose)))
        out += [(rid, s) for s in re.split(r"(?<=[.;:])\s+(?=[A-Z(*\"'])", body) if len(s) > 20]
        out += [(rid, r) for r in rows]
    return out


def trace_rows(text: str, number: int) -> list[tuple[str, str, list[str]]]:
    sec = text[text.index(f"\n## {number}. ") + 1:]
    out = []
    for line in sec.split("\n")[1:]:                 # after the section's own heading
        if line.startswith("## "):
            break
        m = re.match(r"^\| ((?:\d+\.)+\d+) \| (.+?) \| (.+?) \|$", line)
        if m:
            out.append((m.group(1), m.group(2).replace("\\|", "|"), [t.strip() for t in m.group(3).split(",")]))
    return out


def _test_names() -> set[str]:
    names = set()
    for f in os.listdir(os.path.join(ROOT, "tests")):
        if f.endswith(".py"):
            names |= set(re.findall(r"^def (test_\w+)", _read(os.path.join("tests", f)), re.M))
    return names


def _harness_modes() -> set[str]:
    """The modes scripts/test-sandbox.sh takes: `[ "${1:-}" = launcher ]` and kin."""
    return set(re.findall(r'\[ "\$\{?1(?::-[a-z]*)?\}?" = ([a-z0-9-]+) \]', _read("scripts/test-sandbox.sh")))


def _finding_exists(fid: str) -> bool:
    review, num = fid.split("-", 1)
    path = {"R2": "docs/reviews/app-sandboxing-2.md", "R3": "docs/reviews/app-sandboxing-3.md"}.get(review)
    if not path or not os.path.exists(os.path.join(ROOT, path)):
        return False
    head = num if review == "R2" else fid
    return re.search(rf"^#+ {re.escape(head)}\. ", _read(path), re.M) is not None


def test_every_sentence_of_17_has_a_row_and_every_row_its_sentence():
    units = section_units(_read("docs/requirements.md"), 17)
    rows = trace_rows(_read("docs/requirements-trace.md"), 17)
    unmatched = [(rid, u[:70]) for rid, u in units
                 if not any(r == rid and u.startswith(_norm(a)) for r, a, _ in rows)]
    assert not unmatched, "sentences of 17 with no row in docs/requirements-trace.md:\n" + \
        "\n".join(f"  {rid}: {u}" for rid, u in unmatched)
    dangling = [(r, a) for r, a, _ in rows if not any(rid == r and u.startswith(_norm(a)) for rid, u in units)]
    assert not dangling, "rows whose sentence changed or went (update them):\n" + "\n".join(f"  {r}: {a}" for r, a in dangling)


def test_every_row_names_tests_that_exist_or_says_why_not():
    tests, modes = _test_names(), _harness_modes()
    bad = []
    for rid, anchor, shown in trace_rows(_read("docs/requirements-trace.md"), 17):
        for tok in shown:
            ok = (tok in ("claim", "deferred", "statement")
                  or (tok.startswith("test_") and tok in tests)
                  or (tok.startswith("harness:") and tok[8:] in modes)
                  or (tok.startswith("open: ") and _finding_exists(tok[6:])))
            if not ok:
                bad.append(f"{rid} {anchor[:40]!r}: {tok}")
    assert not bad, "rows naming what doesn't exist:\n  " + "\n  ".join(bad)


def test_the_open_rows_are_exactly_the_listed_findings():
    opened = {tok[6:] for _, _, shown in trace_rows(_read("docs/requirements-trace.md"), 17)
              for tok in shown if tok.startswith("open: ")}
    assert opened - STILL_OPEN == set(), f"open in the table but not listed here: {sorted(opened - STILL_OPEN)}"
    assert STILL_OPEN - opened == set(), f"listed here but no row is open on it any more (drop it): {sorted(STILL_OPEN - opened)}"


def test_every_backend_slot_is_wired_to_the_ui_or_listed():
    backend = _read("src/appkata/backend.py")
    qml = "".join(_read(os.path.join("src/appkata/qml", f)) for f in os.listdir(os.path.join(ROOT, "src/appkata/qml"))
                  if f.endswith(".qml"))
    python = "".join(_read(os.path.join("src/appkata", f)) for f in os.listdir(os.path.join(ROOT, "src/appkata")) if f.endswith(".py"))
    exposed = re.findall(r"@(?:Slot|Property)\([^\n]*\)\n(?:    @Slot\([^\n]*\)\n)*    def (\w+)\(", backend)
    unwired = sorted(n for n in set(exposed) if not n.startswith("demo")
                     and not re.search(rf"\b{n}\b", qml)
                     and len(re.findall(rf"\b{n}\b", python)) < 2)          # its def, and nothing else
    assert set(unwired) - set(STILL_UNWIRED) == set(), f"slots the UI never uses: {sorted(set(unwired) - set(STILL_UNWIRED))}"
    assert set(STILL_UNWIRED) - set(unwired) == set(), f"now wired (drop from the list): {sorted(set(STILL_UNWIRED) - set(unwired))}"
