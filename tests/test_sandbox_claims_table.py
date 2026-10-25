"""The claims tables in docs/app-sandboxing.md name their evidence, and an inferred row is a
deliberate one (round seven).

Six rounds in, the findings that mattered most were claims written from reading source that
turned out false when run (GTK 4.18's dialog, kwin's clipboard). The tables mark each claim run,
read or inferred. This test keeps that honest: every row must carry one of the three words, and
the set of rows still inferred must equal the list below, so adding an inferred claim -- or
quietly dropping one that should have been run -- is a change to this test too.
"""

import os
import re

DOC = os.path.join(os.path.dirname(__file__), "..", "docs", "app-sandboxing.md")

# what is still inferred, and why it stays so for now
STILL_INFERRED = {
    "Chromium reads FileChooser's `version` first": "Electron ships Chromium's dialog code; Obsidian itself runs behind the launcher (consumers) but its dialog needs a click",
}


def rows(section: str) -> list[tuple[str, str]]:
    text = open(DOC).read()
    i = text.index(f"## {section}")
    body = text[i:]
    body = body[:body.index("\n## ", 10)] if "\n## " in body[10:] else body
    out = []
    for line in body.splitlines():
        if line.startswith("| ") and not line.startswith("| Claim") and not line.startswith("|---") and not line.startswith("| Hint"):
            cells = [c.strip() for c in line.strip("|").split(" | ")]
            if len(cells) >= 3:
                out.append((cells[0], " | ".join(cells[1:])))
    return out


def test_every_claim_names_its_evidence():
    for claim, evidence in rows("Claims and their evidence"):
        assert re.search(r"\b(run|read|inferred)\b", evidence), claim


def test_the_inferred_claims_are_exactly_the_listed_ones():
    inferred = [c for c, e in rows("Claims and their evidence") if "inferred" in e]
    unlisted = [c for c in inferred if not any(c.startswith(k) for k in STILL_INFERRED)]
    assert not unlisted, "inferred without being listed in this test: " + "; ".join(c[:70] for c in unlisted)
    gone = [k for k in STILL_INFERRED if not any(c.startswith(k) for c in inferred)]
    assert not gone, "listed as inferred but no longer so in the table (drop it here): " + "; ".join(gone)


def test_every_ui_hint_row_names_its_evidence():
    for hint, evidence in rows("UI text and its evidence"):
        assert re.search(r"test_|`|tier|harness|17\.|read|inferred", evidence), hint
