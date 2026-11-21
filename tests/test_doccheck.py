"""Every id the documents and the code cite names something (scripts/doccheck.py,
docs/requirements/README.md).

How it slipped past: the requirements were one file numbered 1 to 17 and cited as "(5.6)", "req
5.6" or "section 5.6", which no tool could tell from a version number. Items were renumbered and
split, and the comments citing them kept the old numbers: three pointed at items that had gone
(5.7.5.3, 6.4.1, 5.2.5) when the ids moved to R. Now an item's id carries its book's letter (R17.4,
A1.12.5), so a citation that names nothing can be found, and this fails on it.
"""

import os
import sys

import pytest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import doccheck  # noqa: E402

URL = "https://github.com/MojoKata/AppKata/issues/"


def test_every_id_cited_names_an_item_and_the_indexes_match_their_files():
    if not os.path.isdir(os.path.join(ROOT, ".git")) and not os.path.isfile(os.path.join(ROOT, ".git")):
        pytest.skip("not a git work tree (the Windows VM's copy of the sources)")
    found = doccheck.problems()
    assert not found, "\n".join(found)


@pytest.mark.parametrize(
    ("line", "found"),
    [
        (f"a gap ([G#81]({URL}81)).", []),
        (f"a question ([Q#82]({URL}82)).", []),
        (f"an issue ([#7]({URL}7)).", []),
        ("[Q#82] alone", ["[Q#82] links to no issue"]),
        (f"[N#5]({URL}5)", ["[N#5]: the prefix is Q, G or none"]),
        (f"[G#5]({URL}6)", [f"[G#5] links to {URL}6, not issue 5"]),
        ("[G#5](https://github.com/other/repo/issues/5)",
         ["[G#5] links to https://github.com/other/repo/issues/5, not issue 5"]),
        ("[G#?zipped-packages] stands in", ["[G#?zipped-packages] waits for its issue to be made"]),
    ],
)
def test_an_issue_is_cited_by_a_link_to_that_issue(line, found):
    assert doccheck.issue_link_problems(line) == found


@pytest.mark.parametrize(
    ("text", "cited"),
    [
        ("(R17.4) and R1.1's platforms", ["R17.4", "R1.1"]),
        ("R17.4–R17.8, R17", ["R17.4", "R17.8", "R17"]),
        ("review 3, R3-21; round four, R4-3", []),          # findings, not items
        ("screen A20, check A1-prompt", []),                 # mockups and field-test checks
        ("A1.12.5 and `R2.11` in code", ["A1.12.5", "R2.11"]),
        ("AR1.1, R1.1x, 2R1", []),
    ],
)
def test_what_counts_as_a_citation(text, cited):
    assert [m.group(1) for m in doccheck.CITED.finditer(text)] == cited


def test_a_citation_of_an_item_that_is_not_there_is_caught():
    ids = {"R1": [], "R1.1": []}
    assert doccheck.citation_problems("x.md", "see R1.1 and R1." "2\n```\nR9." "9 in code\n```\n", ids) == [
        "x.md:1: R1.2 is numbered by no section"]
    missing = "R" + "9.9"                   # spelled in parts, so this file cites nothing that isn't there
    assert doccheck.citation_problems("x.py", f"# {missing}\n", ids) == [f"x.py:1: {missing} is numbered by no section"]
