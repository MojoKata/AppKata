"""The mechanical checks of the requirements and the architecture (docs/requirements/README.md).

    python3 scripts/doccheck.py [--quiet]

Reads docs/requirements/ and docs/architecture/, the other documents and the code's comments, and
reports:

1. ids cited that name nothing: a requirement item (R17.4) or an architecture item (A1.12.5) that no
   file numbers;
2. a question, gap or other issue (`[Q#n]`, `[G#n]`, `[#n]`) whose link isn't that issue, and a
   placeholder for an issue not made yet (`[G#?name]`);
3. each index's sections against the files;
4. a section file past 500 lines, or an id numbered twice;
5. words and dates a statement doesn't carry, for a reader to judge: some are fine in context.

Exits 1 if any of 1 to 4 found something; 5 never fails. tests/test_doccheck.py runs it in tier 1.
--quiet prints only the problems. docs/reviews/ and docs/releases/ are records of their day, so
what they cite isn't checked.
"""

import os
import re
import subprocess
import sys

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
MAX_LINES = 500
ISSUES = "https://github.com/MojoKata/AppKata/issues/"
KINDS = ("", "G", "Q")
BOOKS = {"R": "docs/requirements", "A": "docs/architecture"}
# what cites ids: the documents (but the records), and the code's comments and strings
DOC_SKIP = ("docs/reviews/", "docs/releases/")
CODE_DIRS = ("src", "scripts", "tests", "packaging", "screenshots/src", ".github")
CODE_SKIP = ("tests/data/channels/", "packaging/licenses/")

# An item's own number starts its line or its heading: "R17.4. **The launcher.**", "# R17.4. The launcher".
DEFINED = re.compile(r"^(?:#+ )?([RA]\d+(?:\.\d+)*)\. ", re.M)
# A citation. R3-21 and A1-prompt (a review finding, a field-test check) are not items, nor are the
# screens' A01 or A20: an A id is checked once it is dotted.
CITED = re.compile(r"(?<![\w.\-/#$])(R\d+(?:\.\d+)*|A\d+(?:\.\d+)+)(?![\w\-]|\.\d)")
ISSUE = re.compile(r"\[([A-Z]*)#(\d+)\](\(([^)\s]*)\))?")
PLACEHOLDER = re.compile(r"\[([A-Z]*)#\?([\w-]+)\]")
SECTION_HEAD = re.compile(r"^# (\d+)\. (.+?)\s*$", re.M)
LINK = re.compile(r"\]\(([^)\s]+)\)")
CHANGELOG = re.compile(
    r"\b(now|no longer|revised|proposed|approved|previously|formerly|used to|not yet|for now|"
    r"(?:19|20)\d\d-\d\d-\d\d|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]* "
    r"(?:\d{1,2}, )?(?:19|20)\d\d)\b",
    re.IGNORECASE,
)


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


def _prose(text):
    """The text outside code fences, line numbers kept."""
    out, fenced = [], False
    for line in text.split("\n"):
        if line.lstrip().startswith(("```", "~~~")):
            fenced = not fenced
            out.append("")
        else:
            out.append("" if fenced else line)
    return "\n".join(out)


def book_files(prefix):
    """{relative path} of a book's section and item files: RN-name.md, RN-name/README.md, RN-name/RN.K-name.md."""
    top = BOOKS[prefix]
    out = []
    if not os.path.isdir(os.path.join(ROOT, top)):
        return out
    for name in sorted(os.listdir(os.path.join(ROOT, top))):
        path = f"{top}/{name}"
        if not name.startswith(prefix) or not re.match(rf"{prefix}\d+-", name):
            continue
        if os.path.isdir(os.path.join(ROOT, path)):
            out += [f"{path}/{n}" for n in sorted(os.listdir(os.path.join(ROOT, path))) if n.endswith(".md")]
        elif name.endswith(".md"):
            out.append(path)
    return out


def defined_ids():
    """{id: [(file, "heading" or "item")]} over both books: where each id is numbered."""
    ids = {}
    for prefix in BOOKS:
        for rel in book_files(prefix):
            for m in DEFINED.finditer(_prose(_read(rel))):
                ids.setdefault(m.group(1), []).append((rel, "heading" if m.group(0).startswith("#") else "item"))
    return ids


def issue_link_problems(line):
    """An issue cited as `[Q#n]`, `[G#n]` or `[#n]` links to that same issue."""
    found = []
    for m in ISSUE.finditer(line):
        cited, target = f"[{m.group(1)}#{m.group(2)}]", m.group(4)
        if m.group(1) not in KINDS:
            found.append(f"{cited}: the prefix is Q, G or none")
        if target is None:
            found.append(f"{cited} links to no issue")
        elif target != f"{ISSUES}{m.group(2)}":
            found.append(f"{cited} links to {target}, not issue {m.group(2)}")
    for m in PLACEHOLDER.finditer(line):
        found.append(f"{m.group(0)} waits for its issue to be made")
    return found


def _git_files():
    try:
        out = subprocess.run(["git", "-C", ROOT, "ls-files", "-co", "--exclude-standard"], capture_output=True,
                             text=True, check=True).stdout.split()
    except (OSError, subprocess.CalledProcessError):
        out = []
        for top, dirs, files in os.walk(ROOT):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("build", "node_modules")]
            out += [os.path.relpath(os.path.join(top, f), ROOT).replace(os.sep, "/") for f in files]
    return [f for f in out if os.path.isfile(os.path.join(ROOT, f))]


def documents():
    return [f for f in _git_files() if f.endswith(".md") and not f.startswith(DOC_SKIP)
            and not f.startswith(("agents/", "coworker/"))]


def code_files():
    return [f for f in _git_files() if f.startswith(CODE_DIRS) and not f.startswith(CODE_SKIP)
            and not f.endswith((".png", ".svg", ".ico", ".ttf", ".woff2", ".gz", ".zip"))]


def citation_problems(rel, text, ids):
    found = []
    md = rel.endswith(".md")
    for n, line in enumerate((_prose(text) if md else text).split("\n"), 1):
        for m in CITED.finditer(line):
            if m.group(1) not in ids:
                found.append(f"{rel}:{n}: {m.group(1)} is numbered by no section")
        if md:
            found += [f"{rel}:{n}: {p}" for p in issue_link_problems(re.sub(r"`[^`]*`", "", line))]
    return found


def index_problems(prefix):
    """The book's README: a `# N. Title` heading per section, linking its file, under the file's own title."""
    top = BOOKS[prefix]
    readme = f"{top}/README.md"
    if not os.path.exists(os.path.join(ROOT, readme)):
        return [f"{readme} is missing"] if book_files(prefix) else []
    text = _prose(_read(readme))
    found, listed = [], {}
    heads = list(SECTION_HEAD.finditer(text))
    for i, h in enumerate(heads):
        body = text[h.end():heads[i + 1].start() if i + 1 < len(heads) else len(text)]
        links = [link for link in LINK.findall(body) if re.match(rf"{prefix}{h.group(1)}-", link)]
        if not links:
            found.append(f"{readme}: # {h.group(1)}. {h.group(2)} links no {prefix}{h.group(1)} file")
            continue
        listed[h.group(1)] = (h.group(2), links[0])
    sections = {}
    for rel in book_files(prefix):
        part = rel[len(top) + 1:]
        if "/" in part and not part.endswith("/README.md"):
            continue
        m = re.match(rf"{prefix}(\d+)-", part)
        sections[m.group(1)] = part
    for num, part in sorted(sections.items(), key=lambda kv: int(kv[0])):
        if num not in listed:
            found.append(f"{readme}: section {prefix}{num} ({part}) has no heading")
            continue
        title, link = listed[num]
        if link != part:
            found.append(f"{readme}: # {num}. links {link}, not {part}")
        own = re.match(rf"# {prefix}{num}\. (.+)", _read(f"{top}/{part}"))
        if not own or own.group(1).strip() != title:
            found.append(f"{readme}: # {num}. {title} isn't {part}'s own title")
    for num in sorted(set(listed) - set(sections), key=int):
        found.append(f"{readme}: # {num}. links {listed[num][1]}, which is not there")
    return found


def split_problems(prefix):
    """A split section's items: each in RN.K-name.md, holding item RN.K; the README's table lists each."""
    found = []
    top = BOOKS[prefix]
    for rel in book_files(prefix):
        parts = rel[len(top) + 1:].split("/")
        if len(parts) != 2 or parts[1] == "README.md":
            continue
        m = re.match(rf"({prefix}\d+\.\d+)-[\w-]+\.md$", parts[1])
        if not m:
            found.append(f"{rel}: an item file is named by its id ({prefix}N.K-name.md)")
            continue
        if not re.search(rf"^(?:# )?{re.escape(m.group(1))}\. ", _read(rel), re.M):
            found.append(f"{rel}: doesn't number {m.group(1)}")
        if f"]({parts[1]})" not in _read(f"{top}/{parts[0]}/README.md"):
            found.append(f"{top}/{parts[0]}/README.md: its table doesn't list {parts[1]}")
    return found


def problems():
    found = []
    ids = defined_ids()
    for ident, where in sorted(ids.items()):
        for kind in ("heading", "item"):
            places = [rel for rel, k in where if k == kind]
            if len(places) > 1:
                found.append(f"{ident} is numbered more than once ({kind}): {', '.join(places)}")
    for rel in documents():
        found += citation_problems(rel, _read(rel), ids)
    for rel in code_files():
        try:
            text = _read(rel)
        except UnicodeDecodeError:
            continue
        found += citation_problems(rel, text, ids)
    for prefix in BOOKS:
        found += index_problems(prefix) + split_problems(prefix)
        for rel in book_files(prefix):
            n = len(_read(rel).splitlines())
            if n > MAX_LINES:
                found.append(f"{rel}: {n} lines, past {MAX_LINES}: split it (docs/requirements/README.md)")
    return found


def warnings():
    out = []
    for prefix in BOOKS:
        for rel in book_files(prefix):
            for n, line in enumerate(_prose(_read(rel)).split("\n"), 1):
                prose = re.sub(r"`[^`]*`|\*\*[^*]*\*\*|\*[^*]*\*", " ", line)
                for m in CHANGELOG.finditer(prose):
                    out.append(f'{rel}:{n}: "{m.group(0)}": {line.strip()[:90]}')
    return out


def main(argv):
    found = problems()
    if "--quiet" in argv:
        print("\n".join(f"   {p}" for p in found))
        return 1 if found else 0
    for title, rows in (("Problems", found), ("To read (words and dates)", warnings())):
        print(f"## {title}: {len(rows)}\n")
        print("\n".join(f"- {r}" for r in rows) or "- none")
        print()
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
