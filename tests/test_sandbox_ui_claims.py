"""Every statement of fact the Sandbox dialog makes has evidence (round six, "UI text as claims").

Round five found three hints stating things that were not so, and round six a fourth (the camera
portal "asks you first"). The dialog contract test drives behaviour, not wording, and the claims
table in docs/app-sandboxing.md covers the spec, not the QML. This test reads every `hint:` string
in SandboxDialog.qml and requires a row for it in the design doc's "UI text and its evidence"
table (matched on the hint's first words), so a new or changed hint without evidence fails here.
"""

import os
import re

QML = os.path.join(os.path.dirname(__file__), "..", "src", "appkata", "qml", "SandboxDialog.qml")
DOC = os.path.join(os.path.dirname(__file__), "..", "docs", "app-sandboxing.md")


def hints() -> list[str]:
    text = open(QML).read()
    found = []
    for m in re.finditer(r'hint:\s*', text):
        rest = text[m.end():]
        end = min(i for i in (rest.find("onToggled:"), rest.find("SbxToggle {"), rest.find("SbxHeader {"), rest.find("\n            }")) if i >= 0)
        found += [s for s in re.findall(r'"((?:[^"\\]|\\.)*)"', rest[:end]) if len(s) > 20]     # the quoted sentences of that hint
    return found


def table_keys() -> list[str]:
    text = open(DOC).read()
    section = text[text.index("## UI text and its evidence"):]
    section = section[:section.index("\n## ", 10)] if "\n## " in section[10:] else section
    return [m.group(1) for m in re.finditer(r'^\| "([^"]+?)…?" \|', section, re.M)]


def test_every_dialog_hint_has_a_row_in_the_evidence_table():
    keys = table_keys()
    assert keys, "no 'UI text and its evidence' table in docs/app-sandboxing.md"
    missing = [h for h in hints() if not any(h.startswith(k) for k in keys)]
    assert not missing, "hints without an evidence row: " + "; ".join(repr(h[:60]) for h in missing)


def test_every_evidence_row_still_matches_a_hint():
    hs = hints()
    stale = [k for k in table_keys() if not any(h.startswith(k) for h in hs)]
    assert not stale, "rows whose hint no longer exists: " + "; ".join(stale)
