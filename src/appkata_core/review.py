"""Writing a review to the user's AppKata.md, optionally committing and pushing it (requirement 8)."""

from __future__ import annotations

import os
from dataclasses import dataclass

from . import gitsig, trustfile


@dataclass
class RepoState:
    in_repo: bool = False
    top: str = ""
    remote: str = ""          # origin URL
    branch: str = ""
    signs: bool = False       # commit.gpgsign is on
    format: str = "openpgp"
    key: str = ""


def repo_state(path: str) -> RepoState:
    d = os.path.dirname(os.path.abspath(path))
    if not os.path.isdir(d):
        return RepoState()
    top = gitsig.git(d, "rev-parse", "--show-toplevel", check=False).strip()
    if not top:
        return RepoState()
    cfg = lambda k: gitsig.git(top, "config", "--get", k, check=False).strip()
    return RepoState(True, top, gitsig.git(top, "remote", "get-url", "origin", check=False).strip(),
                     gitsig.git(top, "branch", "--show-current", check=False).strip(),
                     cfg("commit.gpgsign").lower() == "true", cfg("gpg.format") or "openpgp", cfg("user.signingkey"))


def read(path: str) -> str:
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


def current(path: str, app: str, url: str) -> dict:
    """The user's existing review of an app (requirement 8.6)."""
    tf = trustfile.parse(read(path))
    row = next((r for r in tf.rows if r.url == url or r.app.lower() == app.lower()), None)
    if not row:
        return {"exists": False, "tags": [], "trust": None, "rating": None, "section": "", "settings": {}, "full": {},
                "versions": []}
    full = tf.settings.get(row.app, {})
    return {"exists": True, "tags": row.tags, "trust": row.trust, "rating": row.rating, "section": tf.sections.get(row.app, ""),
            "settings": {k: v for k, v in full.items() if not k.startswith("_")}, "full": full,
            "versions": full.get("_versions") or []}


@dataclass
class SaveResult:
    saved: bool
    committed: str = ""       # commit id
    signed: bool = False
    pushed: bool = False
    error: str = ""


def save(path: str, app: str, source: str, tags: list[str], trust: int | None, rating: int | None, section: str,
         commit: bool = False, push: bool = False, settings: dict | None = None, version: str = "",
         details: list | None = None, dates: dict | None = None) -> SaveResult:
    """Save the app review, or with `version` that version review (requirement 8.5); with commit,
    commit only AppKata.md; push only if that commit is signed."""
    text = trustfile.set_review(read(path), app, source, tags, trust, rating, section, settings, version, details, dates)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)
    res = SaveResult(True)
    if not commit:
        return res
    st = repo_state(path)
    if not st.in_repo:
        res.error = "The file isn't in a git repository, so it wasn't committed."
        return res
    rel = os.path.relpath(os.path.abspath(path), st.top)
    try:
        gitsig.git(st.top, "add", "--", rel)
        if not gitsig.git(st.top, "diff", "--cached", "--name-only", "--", rel).strip():
            return res                                     # nothing changed
        gitsig.git(st.top, "commit", "--quiet", "-m", f"Review {app} {version}" if version else f"Review {app}", "--", rel)
        res.committed = gitsig.git(st.top, "rev-parse", "HEAD").strip()
    except gitsig.GitError as e:
        res.error = f"Commit failed: {e}"
        return res
    # %G? is N only when there's no signature at all; E/U/G all mean it was signed
    res.signed = gitsig.git(st.top, "log", "-1", "--format=%G?", res.committed, check=False).strip() not in ("", "N")
    if push:
        if not res.signed:
            res.error = f"Commit {res.committed[:7]} isn't signed, so it wasn't pushed."
            return res
        try:
            gitsig.git(st.top, "push", "--quiet", "origin", "HEAD", timeout=180)
            res.pushed = True
        except gitsig.GitError as e:
            res.error = f"Push failed: {e}"
    return res


def amend_signed(path: str) -> SaveResult:
    """Re-sign the last commit (the "Amend with signing" action)."""
    st = repo_state(path)
    res = SaveResult(True)
    try:
        gitsig.git(st.top, "commit", "--quiet", "--amend", "--no-edit", "-S")
        res.committed = gitsig.git(st.top, "rev-parse", "HEAD").strip()
        res.signed = gitsig.git(st.top, "log", "-1", "--format=%G?", check=False).strip() not in ("", "N")
    except gitsig.GitError as e:
        res.error = f"Signing failed: {e}"
    return res
