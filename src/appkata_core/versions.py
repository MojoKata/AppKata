"""Comparing release versions (requirement 9.4)."""

from __future__ import annotations

import re

_SEMVERISH = re.compile(r"^[vV]?(\d+(?:\.\d+){0,3})(?:[-+_.~]?([0-9A-Za-z][0-9A-Za-z.\-+]*))?$")
_PRE = re.compile(r"(alpha|beta|rc|pre|preview|dev|nightly|snapshot)", re.I)


def clean(tag: str, regex: str | None = None, group: int = 1) -> str:
    """The version string of a tag or title: the extraction regex if set, else minus a leading 'v'."""
    s = (tag or "").strip()
    if regex:
        m = re.search(regex, s)
        if m:
            s = m.group(group if m.lastindex and group <= m.lastindex else 0)
    for prefix in ("release-", "release_", "version-", "version "):
        if s.lower().startswith(prefix):
            s = s[len(prefix):]
    s = s[1:] if s[:1] in "vV" and s[1:2].isdigit() else s
    if not _SEMVERISH.match(s):      # "INKSCAPE_1_4", "Inkscape 1.4.2", "app-2.0-rc1": the version inside
        m = re.search(r"(?<![\d.])(\d+(?:[._]\d+){1,3})(?:[-.]?((?:alpha|beta|rc|pre)\.?\d*))?(?![\d])", s, re.I)
        if m:
            s = m.group(1).replace("_", ".") + (f"-{m.group(2)}" if m.group(2) else "")
    return s


def key(v: str):
    """Sort key for a semver-like version, or None when it isn't one."""
    m = _SEMVERISH.match((v or "").strip())
    if not m:
        return None
    nums = tuple(int(x) for x in m.group(1).split("."))
    nums = nums + (0,) * (4 - len(nums))
    suffix = m.group(2) or ""
    # a prerelease word, or the short a1/b2 forms; other words are labels ("2.56.0.windows.1")
    pre = bool(suffix) and (bool(_PRE.search(suffix)) or bool(re.match(r"^[ab]\d", suffix, re.I)))
    # a prerelease sorts before its release; numeric parts of the suffix compare numerically
    parts = tuple((0, int(p), "") if p.isdigit() else (1, 0, p.lower()) for p in re.split(r"[.\-+_]", suffix) if p)
    return nums + ((0, parts) if pre else (1, parts))


def is_semverish(v: str) -> bool:
    return key(v) is not None


def compare(a: str, b: str) -> int | None:
    """-1, 0, 1, or None when either isn't comparable (then dates decide)."""
    ka, kb = key(a), key(b)
    if ka is None or kb is None:
        return None if a != b else 0
    return (ka > kb) - (ka < kb)


def is_prerelease(v: str) -> bool:
    k = key(v)
    return k is not None and k[4] == 0


def newer(candidate: str, installed: str, candidate_date: str = "", installed_date: str = "") -> bool:
    c = compare(candidate, installed)
    if c is not None:
        return c > 0
    if candidate_date and installed_date:
        return candidate_date > installed_date
    return candidate != installed
