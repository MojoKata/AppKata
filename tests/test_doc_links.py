"""Every link a Markdown file makes to another file of the repository, or to a heading in one, leads
somewhere.

How it slipped past: GENESIS.md moved into docs/ and build.md's release checklist into RELEASE.md,
and nothing read the links that named them: a moved file or section leaves a link that GitHub shows
as a 404 or that opens at the top of the page. This reads every relative link and `#heading` in the
documents, outside code blocks.
"""

import os
import re

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
SKIP = {".git", ".venv", "build", "releases", ".pytest_cache", "temp", "__pycache__", "node_modules"}


def _documents(root):
    for top, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in SKIP and not d.endswith(".egg-info"))
        for name in sorted(files):
            if name.endswith(".md"):
                yield os.path.join(top, name)


def _prose(text):
    text = re.sub(r"^(```|~~~).*?^\1", "", text, flags=re.M | re.S)    # fenced code
    return re.sub(r"`[^`\n]*`", "", text)                                # inline code


def _anchors(path):
    """The anchors GitHub gives a document's headings: lower case, punctuation dropped, spaces as
    hyphens, a repeat numbered."""
    with open(path, encoding="utf-8") as f:
        text = re.sub(r"^(```|~~~).*?^\1", "", f.read(), flags=re.M | re.S)
    seen, out = {}, set()
    for heading in re.findall(r"^#{1,6} +(.+?) *#* *$", text, re.M):
        slug = re.sub(r"[^\w\- ]", "", heading.strip().lower()).replace(" ", "-")
        n = seen.get(slug, 0)
        seen[slug] = n + 1
        out.add(slug if n == 0 else f"{slug}-{n}")
    return out


def broken_links(root):
    bad = []
    for doc in _documents(root):
        with open(doc, encoding="utf-8") as f:
            text = _prose(f.read())
        for target in re.findall(r"\]\(<?([^)\s>]+)>?(?: \"[^\"]*\")?\)", text):
            if re.match(r"[a-z][a-z0-9+.-]*:", target, re.I):
                continue                                                    # https:, mailto:
            path, _, anchor = target.partition("#")
            dest = os.path.normpath(os.path.join(os.path.dirname(doc), path)) if path else doc
            rel = os.path.relpath(doc, root).replace(os.sep, "/")
            if not os.path.exists(dest):
                bad.append((rel, target, "no such file"))
            elif anchor and dest.endswith(".md") and anchor not in _anchors(dest):
                bad.append((rel, target, "no such heading"))
    return bad


def test_every_link_between_the_documents_leads_somewhere():
    assert not broken_links(ROOT)


def test_a_moved_file_or_heading_is_caught(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "README.md").write_text("[setup](GENESIS.md), [kept](docs/b.md#the-steps)\n"
                                        "[gone](docs/b.md#before-tagging-a-release)\n"
                                        "```\n[in code](nowhere.md)\n```\n", encoding="utf-8")
    (tmp_path / "docs" / "b.md").write_text("# B\n\n## The steps\n\n[up](../README.md), [here](#b)\n",
                                            encoding="utf-8")
    assert broken_links(str(tmp_path)) == [
        ("README.md", "GENESIS.md", "no such file"),
        ("README.md", "docs/b.md#before-tagging-a-release", "no such heading")]
