"""The requirements as the tests read them: every section file under docs/requirements/, in order,
as one text (docs/requirements/README.md says how they're laid out).

A section is `RN-name.md`, or `RN-name/README.md` with its first-level items in `RN.K-name.md`
beside it once it passes 500 lines. Each item starts its own line with its id (`R17.4. `), so a
test finds an item by its id wherever its file is.
"""

import glob
import os
import re

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
REQ = os.path.join(ROOT, "docs", "requirements")
# where an item's text ends: the next item's id, or a heading
NEXT = r"(?=^R\d+\.\d+(?:\.\d+)*\. |^#|\Z)"


def _number(path: str) -> list[int]:
    m = re.match(r"R(\d+(?:\.\d+)*)", os.path.basename(path))
    return [int(x) for x in m.group(1).split(".")] if m else []


def files() -> list[str]:
    """The section files in order: R1 … R17, a split section's README before its items."""
    out = []
    for path in sorted(glob.glob(os.path.join(REQ, "R*")), key=_number):
        if os.path.isdir(path):
            items = sorted(glob.glob(os.path.join(path, "R*.md")), key=_number)
            out += [os.path.join(path, "README.md"), *items]
        else:
            out.append(path)
    return out


def text() -> str:
    parts = []
    for path in files():
        with open(path, encoding="utf-8") as f:
            parts.append(f.read())
    return "\n".join(parts)


def item(rid: str, req: str | None = None) -> str:
    """An item's own text, up to the next item or heading ("" when no item has that id)."""
    m = re.search(rf"^{re.escape(rid)}\. (.*?){NEXT}", text() if req is None else req, re.M | re.S)
    return m.group(1) if m else ""


def section(number: int) -> str:
    """One section's files as one text: R17's README and its items."""
    own = [p for p in files() if _number(p)[:1] == [number]
           or os.path.basename(os.path.dirname(p)).startswith(f"R{number}-")]
    parts = []
    for path in own:
        with open(path, encoding="utf-8") as f:
            parts.append(f.read())
    return "\n".join(parts)
