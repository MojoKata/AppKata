#!/usr/bin/env python3
"""What tier 1 reaches, by area (docs/github-workflows.md, "Coverage"), from the coverage.py data CI's
tier 1 parts measured: line and branch coverage of src/ and scripts/*.py, totalled by area
(scripts/areas.py), with the lines changed since the base.

    coverage_report.py report [--check] [--data DIR]   totals by area, the changed lines, HTML
    coverage_report.py floor [TOTALS]                  raise tests/coverage-floor.json to them

It runs on a Python with coverage.py: the one scripts/python-standalone.sh makes.

`report` combines the data files in DIR (build/coverage/ by default: each tier 1 part's, and each
process's in a part), prints the table by area and the lines changed since the base (in CI the
commit before: a pull request's merge commit's first parent is its base; otherwise the merge base
with master), and writes into build/coverage/ the HTML report (html/), summary.md, totals.json and
files.json. In GitHub Actions it also writes the job summary and annotations: the headline, and the
largest stretches of changed lines no test reaches, on those lines in the pull request. `--check`
fails when an area falls below its floor.

`floor` raises each area's floor to what was measured less SLACK lines and SLACK branches, rounded
down to a tenth of a point, so run-to-run jitter doesn't fail however small the area; it never lowers
one (that is done by hand, with the reason in the commit). Coverage comes from CI's tier 1 only: run
it on the totals.json of a CI run's `coverage` artifact (`gh run download RUN -n coverage`).

QML isn't Python, and coverage.py doesn't measure it: the qml area is shown with its file count and
no figure, and has no floor."""

import argparse
import importlib.util
import json
import math
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "build" / "coverage"
FLOOR = ROOT / "tests" / "coverage-floor.json"
SLACK = 3           # lines, and branches, an area's measure may move by between runs
ANNOTATIONS = 9     # GitHub shows 10 notices a step: the headline and the nine largest gaps
UNMEASURED = ("qml",)

_spec = importlib.util.spec_from_file_location("appkata_areas", ROOT / "scripts" / "areas.py")
areas = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(areas)


@dataclass
class File:
    """One file's measure: the lines that run and those that don't, and its branches."""

    area: str
    covered: set = field(default_factory=set)
    missed: set = field(default_factory=set)
    branches: int = 0
    branches_taken: int = 0


def git(*args):
    return subprocess.run([shutil.which("git") or "git", *args], cwd=ROOT, capture_output=True, text=True)


# ---------- the measure ----------


def measured(data):
    """{repository path: File} from the data files in folder data, combined there into .coverage."""
    import coverage

    data = Path(data)
    os.chdir(ROOT)
    cov = coverage.Coverage(data_file=str(data / ".coverage"), config_file=str(ROOT / "pyproject.toml"))
    if any(data.glob(".coverage.*")):
        cov.combine([str(data)], keep=False)
        cov.save()
    cov.load()
    OUT.mkdir(parents=True, exist_ok=True)
    shutil.rmtree(OUT / "html", ignore_errors=True)
    cov.html_report(directory=str(OUT / "html"), title="AppKata: what tier 1 reaches")
    cov.json_report(outfile=str(OUT / "coverage.json"))
    report = json.loads((OUT / "coverage.json").read_text())
    out = {}
    for name, f in report["files"].items():
        rel = Path(name).resolve().relative_to(ROOT).as_posix() if os.path.isabs(name) else name
        area = areas.area_of_code(rel)
        if area is None:
            continue
        s = f["summary"]
        out[rel] = File(area, set(f["executed_lines"]), set(f["missing_lines"]),
                        s.get("num_branches", 0), s.get("covered_branches", 0))
    return out


def unmeasured_files():
    """{area: file count} of the areas coverage.py can't measure."""
    out = {}
    for area in UNMEASURED:
        n = 0
        for p in areas.CODE[area]:
            n += len([f for f in ROOT.glob(p) if f.is_file()])
        out[area] = n
    return out


# ---------- totals ----------


def pct(part, whole):
    return round(100 * part / whole, 1) if whole else None


def counted(files, lines, reached, branches, taken):
    return {"files": files, "lines": pct(reached, lines), "branches": pct(taken, branches),
            "lineCount": lines, "linesReached": reached, "branchCount": branches, "branchesReached": taken}


def totals(files):
    by = {}
    for f in files.values():
        by.setdefault(f.area, []).append(f)
    return {area: counted(len(fs), sum(len(f.covered) + len(f.missed) for f in fs), sum(len(f.covered) for f in fs),
                          sum(f.branches for f in fs), sum(f.branches_taken for f in fs))
            for area, fs in sorted(by.items(), key=lambda kv: areas.AREAS.index(kv[0]))}


def total(by_area):
    return counted(*(sum(t[k] for t in by_area.values())
                     for k in ("files", "lineCount", "linesReached", "branchCount", "branchesReached")))


def file_rows(files):
    return [{"path": rel, "area": f.area, **counted(1, len(f.covered) + len(f.missed), len(f.covered),
                                                     f.branches, f.branches_taken)}
            for rel, f in sorted(files.items())]


# ---------- the changed lines ----------


def base_ref():
    """What the changed lines are counted from: APPKATA_COVERAGE_BASE; in CI the commit before (a pull
    request's merge commit's first parent is its base, and master's squash commit's is the master
    before it); otherwise the merge base with master."""
    if os.environ.get("APPKATA_COVERAGE_BASE"):
        return os.environ["APPKATA_COVERAGE_BASE"]
    if os.environ.get("GITHUB_ACTIONS") == "true":
        return "HEAD^1"
    for master in ("upstream/master", "origin/master", "master"):
        r = git("merge-base", "HEAD", master)
        if r.returncode == 0:
            return r.stdout.strip()
    return None


HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


def parse_diff(text):
    """{path: the line numbers added or changed} from `git diff -U0`."""
    out, name = {}, None
    for line in text.splitlines():
        if line.startswith("+++ "):
            name = line[6:] if line.startswith("+++ b/") else None
        elif name and (m := HUNK.match(line)):
            start, count = int(m[1]), int(m[2] if m[2] is not None else 1)
            out.setdefault(name, set()).update(range(start, start + count))
    return out


def changed_lines(base):
    r = git("diff", "-U0", "--no-color", base, "--", "src", "scripts")
    return parse_diff(r.stdout) if r.returncode == 0 else {}


def ranges(lines):
    out = []
    for n in sorted(lines):
        if out and n == out[-1][1] + 1:
            out[-1][1] = n
        else:
            out.append([n, n])
    return [(a, b) for a, b in out]


def diff(files, changed):
    """The changed lines that run, those reached, and the stretches not reached, as (path, first, last)."""
    covered = missed = 0
    gaps = []
    for rel, lines in sorted(changed.items()):
        f = files.get(rel)
        if f is None:
            continue
        covered += len(lines & f.covered)
        miss = lines & f.missed
        missed += len(miss)
        gaps += [(rel, a, b) for a, b in ranges(miss)]
    return {"covered": covered, "lines": covered + missed, "gaps": gaps}


# ---------- floors ----------


def floors(path=FLOOR):
    return json.loads(Path(path).read_text()) if Path(path).exists() else {}


def under(by_area, fl):
    """The areas measured below their floor."""
    return [area for area, f in fl.items() if area in by_area and any(
        by_area[area][k] is not None and f.get(k) is not None and by_area[area][k] < f[k] for k in ("lines", "branches"))]


def slack_floor(reached, count):
    """What was reached less SLACK, as a percentage rounded down to a tenth."""
    return math.floor(1000 * max(0, reached - SLACK) / count) / 10


def raised(by_area, old):
    """The floors raised to what by_area measured less the slack; never lowered."""
    new = dict(old)
    for area, t in by_area.items():
        was = old.get(area, {})
        counts = {"lines": (t["linesReached"], t["lineCount"]), "branches": (t["branchesReached"], t["branchCount"])}
        new[area] = {k: max(was.get(k) or 0, slack_floor(r, n)) for k, (r, n) in counts.items() if n}
    return dict(sorted(new.items(), key=lambda kv: areas.AREAS.index(kv[0])))


# ---------- what is shown ----------


def show(v):
    return "—" if v is None else f"{v:.1f}%"


def reached(t, kind):
    count, got = (t["lineCount"], t["linesReached"]) if kind == "lines" else (t["branchCount"], t["branchesReached"])
    return f"{got:,} of {count:,}" if count else "—"


def summary(by_area, fl, d, base, below, unmeasured):
    out = ["## Coverage", ""]
    if d is not None and d["lines"]:
        out.append(f"**Changed lines** (since `{base}`): {d['covered']} of {d['lines']} reached, "
                   f"{show(pct(d['covered'], d['lines']))}.")
    elif d is not None:
        out.append(f"**Changed lines** (since `{base}`): none that run.")
    out += ["", "| Area | Files | Lines | Lines reached | Branches | Branches reached | Floor (lines / branches) |",
            "|---|---:|---:|---:|---:|---:|---|"]

    def row(name, t, floor):
        return "| " + " | ".join([name, f"{t['files']:,}", show(t["lines"]), reached(t, "lines"),
                                  show(t["branches"]), reached(t, "branches"), floor]) + " |"

    for area, t in by_area.items():
        f = fl.get(area)
        out.append(row(area + (" ⚠" if area in below else ""), t,
                       f"{show(f.get('lines'))} / {show(f.get('branches'))}" if f else "—"))
    for area, n in unmeasured.items():
        out.append(f"| {area} | {n:,} | not measured (coverage.py doesn't read QML) | | | | |")
    out.append(row("**all**", total(by_area), ""))
    if d and d["gaps"]:
        out += ["", "**Changed lines no test reaches:**", ""]
        out += [f"- `{rel}`: {a}" + (f"–{b}" if b > a else "") for rel, a, b in d["gaps"]]
    if below:
        out += ["", f"**Below the floor:** {', '.join(below)}."]
    return "\n".join(out) + "\n"


def annotations(by_area, d):
    """GitHub's workflow commands: a notice with the headline, and one on each of the largest stretches
    of changed lines no test reaches, which the pull request shows on those lines."""
    t = total(by_area)
    head = f"{show(t['lines'])} of lines, {show(t['branches'])} of branches"
    if d is not None and d["lines"]:
        head += f"; changed lines {d['covered']} of {d['lines']} reached"
    out = [f"::notice title=Coverage::{head}"]
    for rel, a, b in sorted((d or {"gaps": []})["gaps"], key=lambda g: (g[1] - g[2], g))[:ANNOTATIONS]:
        out.append(f"::notice file={rel},line={a},endLine={b},title=Not reached::no test runs these lines")
    return out


# ---------- the commands ----------


def cmd_report(data, check):
    files = measured(data)
    if not files:
        print(f"nothing measured in {data}: run tier 1 with APPKATA_COVERAGE=1 (scripts/test-tier1.sh)")
        return 1
    by_area = totals(files)
    fl = floors()
    base = base_ref()
    d = diff(files, changed_lines(base)) if base else None
    below = under(by_area, fl)
    text = summary(by_area, fl, d, base, below, unmeasured_files())
    (OUT / "summary.md").write_text(text)
    (OUT / "totals.json").write_text(json.dumps(by_area, indent=2) + "\n")
    (OUT / "files.json").write_text(json.dumps(file_rows(files), indent=1) + "\n")
    print(text)
    print(f"HTML: {OUT / 'html' / 'index.html'}")
    if os.environ.get("GITHUB_ACTIONS") == "true":
        if os.environ.get("GITHUB_STEP_SUMMARY"):
            with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
                f.write(text)
        print("\n".join(annotations(by_area, d)))
    return 1 if check and below else 0


def cmd_floor(totals_file):
    if not Path(totals_file).exists():
        print(f"no {totals_file}: download a CI run's coverage artifact (gh run download RUN -n coverage)")
        return 1
    new = raised(json.loads(Path(totals_file).read_text()), floors())
    FLOOR.write_text(json.dumps(new, indent=2) + "\n")
    print(f"{FLOOR.relative_to(ROOT)}: {len(new)} areas")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="coverage_report.py", description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="what", required=True)
    r = sub.add_parser("report", help="totals by area, the changed lines, HTML")
    r.add_argument("--check", action="store_true", help="fail when an area is below its floor")
    r.add_argument("--data", default=str(OUT), help="the folder of coverage data files (default build/coverage)")
    f = sub.add_parser("floor", help="raise tests/coverage-floor.json to a run's totals")
    f.add_argument("totals", nargs="?", default=str(OUT / "totals.json"))
    args = p.parse_args(argv)
    return cmd_report(args.data, args.check) if args.what == "report" else cmd_floor(args.totals)


if __name__ == "__main__":
    sys.exit(main())
