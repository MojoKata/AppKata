#!/usr/bin/env python3
"""What the AppImage leaves out of the Python and Qt it carries (packaging/appimage-trim.txt).

PySide6's wheel brings all of Qt's essential modules, their tools and every plugin, and Python
brings Tcl/Tk; AppKata uses part of them. Qt and Python load most of what they use only when it's
first used (a QML module on the screen that imports it, a plugin in the session that wants it, a
dialog when it opens), so a part left out that's needed after all shows nowhere but there. The
class: a part the build leaves out that AppKata loads at run time. Three checks keep it out:

- apply (the build): each line of the list must still name something in the AppDir, so a Qt or
  Python update that renames a part fails the build instead of quietly carrying it again; and no
  library the AppImage keeps may link one the list leaves out.
- check (scripts/test-appimage.sh trace): scripts/appimage_trace.sh runs the AppImage the ways
  AppKata is used, under strace, and records every file of the AppImage each run used: opened,
  mapped to run, or looked for and not found. None may be one the list leaves out. A library only
  opened to read, as Qt reads every plugin in a folder for its metadata, isn't used; a line marked
  `?` is one AppKata looks for and does well without (reported, not failed). Given the
  AppDir of a build without the list (APPKATA_TRIM=0), it also lists the largest files no run
  used: the candidates for the list.
- tests/test_appimage_trim.py: no QML module AppKata imports, and no PySide6 module, is one the
  list leaves out.

    scripts/appimage_trim.py apply APPDIR
    scripts/appimage_trim.py check TRACE_DIR [UNTRIMMED_APPDIR]
"""

from __future__ import annotations

import fnmatch
import os
import re
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LIST = os.path.join(HERE, "..", "packaging", "appimage-trim.txt")
INSIDE = "/tmp/squashfs-root/"          # where scripts/appimage_trace.sh extracts the AppImage

sys.path.insert(0, os.path.join(HERE, "..", "src"))
from appkata_core.appkind import elf_needed  # noqa: E402


def _lines(path: str) -> list[str]:
    with open(path, encoding="utf-8") as f:
        return [line.split("#")[0].strip() for line in f if line.split("#")[0].strip()]


def patterns(path: str = LIST) -> list[str]:
    """The list's lines: paths in the AppDir, each part a shell pattern (`*` stays within a part)."""
    return [p.lstrip("? ") for p in _lines(path)]


def tolerated(path: str = LIST) -> set[str]:
    """The lines marked `?`: what AppKata looks for and does well without (Qt's translations, a
    plugin that can't load). A run that looks for one is reported, not failed."""
    return {p.lstrip("? ") for p in _lines(path) if p.startswith("?")}


def match(pats: list[str], rel: str) -> str | None:
    """The pattern that leaves `rel` (a path in the AppDir) out: it names it or a folder it's in."""
    parts = rel.strip("/").split("/")
    for p in pats:
        pp = p.strip("/").split("/")
        if len(parts) >= len(pp) and all(fnmatch.fnmatchcase(a, b) for a, b in zip(parts, pp)):
            return p
    return None


def is_library(rel: str) -> bool:
    return re.search(r"\.so(\.\d+)*$", rel) is not None


# --- apply

def plan(appdir: str, pats: list[str]) -> tuple[list[str], list[str]]:
    """The paths the list leaves out (the topmost of each), and the patterns that match nothing."""
    out, used = [], set()
    for root, dirs, files in os.walk(appdir):
        keep = []
        for name in sorted(dirs) + sorted(files):
            rel = os.path.relpath(os.path.join(root, name), appdir)
            p = match(pats, rel)
            if p:
                out.append(rel)
                used.add(p)
            elif name in dirs:
                keep.append(name)
        dirs[:] = keep
    return out, [p for p in pats if p not in used]


def broken_links(kept: dict[str, list[str]], gone: set[str], still: set[str]) -> list[tuple[str, str]]:
    """(library, soname) for each kept library (`kept`: path -> NEEDED) that links a soname only a
    left-out file provided (`gone`) and no kept one does (`still`)."""
    return sorted((f, n) for f, need in kept.items() for n in need
                  if os.path.basename(n) in gone and os.path.basename(n) not in still)


def apply(appdir: str) -> int:
    pats = patterns()
    out, stale = plan(appdir, pats)
    for p in stale:
        print(f"packaging/appimage-trim.txt names what the AppDir doesn't have: {p}", file=sys.stderr)
    gone_files = set()
    for rel in out:
        top = os.path.join(appdir, rel)
        if os.path.isdir(top) and not os.path.islink(top):
            for root, _, files in os.walk(top):
                gone_files.update(os.path.join(root, f) for f in files)
        else:
            gone_files.add(top)
    kept, still, gone = {}, set(), set()
    for root, _, files in os.walk(appdir):
        for name in files:
            f = os.path.join(root, name)
            if not is_library(name):
                continue
            (gone if f in gone_files else still).add(name)
            need = None if f in gone_files or os.path.islink(f) else elf_needed(f)
            if need:
                kept[os.path.relpath(f, appdir)] = need
    broken = broken_links(kept, gone, still)
    for f, n in broken:
        print(f"{f} links {n}, which packaging/appimage-trim.txt leaves out", file=sys.stderr)
    if stale or broken:
        return 1
    size = sum(os.path.getsize(f) for f in gone_files if not os.path.islink(f))
    for rel in out:
        top = os.path.join(appdir, rel)
        if os.path.isdir(top) and not os.path.islink(top):
            shutil.rmtree(top)
        else:
            os.remove(top)
    print(f"left out {len(gone_files)} files, {size / 1e6:.1f} MB (packaging/appimage-trim.txt)")
    return 0


# --- check

CALL = re.compile(r'^(?P<pid>\d*)\s*(?P<call>\w+)\((?P<args>.*)')
RESUMED = re.compile(r'^(?P<pid>\d*)\s*<\.\.\. (?P<call>\w+) resumed>(?P<args>.*)')
PATH = re.compile(r'"(' + re.escape(INSIDE) + r'[^"]*)"')
RELATIVE = re.compile(r'\d+<(' + re.escape(INSIDE) + r'[^>]*)>, "([^"/][^"]*)"')
FD = re.compile(r'\d+<(' + re.escape(INSIDE) + r'[^>]*)>')


def used(lines) -> set[str]:
    """The AppImage's files a strace -f -y log shows used, by their path in the AppDir: a library
    mapped to run, run, or looked for and missing; any other file named by any call. A library only
    opened, read or looked at is one Qt read for its plugin metadata, not one it loaded. A call
    another process interrupted (`<unfinished ...>`) is read whole from its `resumed` line."""
    out, pending = set(), {}
    for line in lines:
        line = line.strip()
        r = RESUMED.match(line)
        if r:
            if r.group("pid") not in pending:
                continue
            line = pending.pop(r.group("pid")) + r.group("args")
        elif line.endswith("<unfinished ...>"):
            m = CALL.match(line)
            if m:
                pending[m.group("pid")] = line[:-len("<unfinished ...>")]
            continue
        m = CALL.match(line)
        if not m:
            continue
        call, args = m.group("call"), m.group("args")
        missing = "= -1 ENOENT" in args or "= -1 ENOTDIR" in args
        if call == "mmap":
            f = FD.search(args)
            if f and "PROT_EXEC" in args:
                out.add(f.group(1))
            continue
        p = PATH.search(args)
        r = RELATIVE.match(args)
        if p:
            path = p.group(1)
        elif r:                   # openat(3</tmp/squashfs-root/usr/x>, "y", ...)
            path = os.path.join(r.group(1), r.group(2))
        else:
            continue
        if missing or not is_library(path) or call == "execve":
            out.add(path)
    return {p[len(INSIDE):] for p in (os.path.normpath(x) for x in out) if p.startswith(INSIDE.rstrip("/") + "/")}


def check(trace_dir: str, untrimmed: str | None = None) -> int:
    pats = patterns()
    seen: dict[str, set[str]] = {}
    runs = sorted(f for f in os.listdir(trace_dir) if f.startswith("trace-") and f.endswith(".txt"))
    if not runs:
        print(f"no trace-*.txt in {trace_dir}", file=sys.stderr)
        return 1
    for name in runs:
        with open(os.path.join(trace_dir, name), encoding="utf-8", errors="replace") as f:
            for rel in used(f):
                seen.setdefault(rel, set()).add(name[len("trace-"):-len(".txt")])
    hits = sorted((rel, match(pats, rel)) for rel in seen if match(pats, rel))
    ok = tolerated()
    bad = [(rel, p) for rel, p in hits if p not in ok]
    for p in sorted({p for _, p in hits if p in ok}):
        n = sum(1 for _, q in hits if q == p)
        print(f"  looked for, and AppKata does without ('?' in the list): {n} paths under '{p}'")
    for rel, p in bad:
        print(f"  used by {', '.join(sorted(seen[rel]))}, left out by '{p}': {rel}")
    print(f"{len(runs)} runs used {len(seen)} of the AppImage's paths; {len(bad)} of them left out")
    if untrimmed:
        touched = set()
        for rel in seen:          # a file used, and the folders it's in
            parts = rel.split("/")
            touched.update("/".join(parts[:i]) for i in range(1, len(parts) + 1))
        sizes = []
        for root, _, files in os.walk(untrimmed):
            for n in files:
                f = os.path.join(root, n)
                rel = os.path.relpath(f, untrimmed)
                if rel not in touched and not os.path.islink(f):
                    sizes.append((os.path.getsize(f), rel, "left out" if match(pats, rel) else "kept"))
        sizes.sort(reverse=True)
        print(f"never used: {len(sizes)} files, {sum(s for s, _, _ in sizes) / 1e6:.1f} MB; the largest kept:")
        for s, rel, how in [x for x in sizes if x[2] == "kept"][:40]:
            print(f"  {s / 1e6:7.2f} MB  {rel}")
    return 1 if bad else 0


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[:1] == ["apply"] and len(a) == 2:
        sys.exit(apply(a[1]))
    if a[:1] == ["check"] and len(a) in (2, 3):
        sys.exit(check(a[1], a[2] if len(a) == 3 else None))
    sys.exit(__doc__)
