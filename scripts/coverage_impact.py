"""A pull request's test coverage impact (docs/github-workflows.md, "Coverage"): each area's line and
branch coverage before and after, from the per-area table CI's `coverage` job prints
(coverage_report.py), as the table a pull request's description ends with.

    coverage_impact.py --pr N              master's last green run against the PR's
    coverage_impact.py BASE_RUN HEAD_RUN   two runs of ci.yml, by id

Before is master's last CI run whose coverage job passed, After the pull request's on its head
commit (a run counts by its coverage job, so a deploy that failed after it doesn't hide it). A row
is an area that moved by MOVE points or more, in lines or in branches; the total, `all`, is always
there. Each After figure carries its band's mark (BANDS), and a Legend line under the table says
what they mean. The figures are worked out from the counts, unrounded."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass

REPO = "MojoKata/AppKata"
WORKFLOW = "ci.yml"
JOB = "coverage"
LOOK_BACK = 10  # runs looked through for one whose coverage job passed
MOVE = 0.5  # points, in lines or in branches, for an area's row
TOTAL = "all"
BANDS = ((95.0, "⭐"), (80.0, "🟢"), (60.0, "🟡"), (0.0, "🔴"))
LEGEND = "Legend: ⭐ 95% and up, 🟢 80–95%, 🟡 60–80%, 🔴 under 60%."

# a row of coverage_report.py's table: | area | files | 97.2% | 445 of 458 | 93.2% | 110 of 118 |;
# an area below its floor carries " ⚠" after its name, and an area's name may have a hyphen (ui-backend)
ROW = re.compile(
    r"\| (\*\*all\*\*|[a-z][a-z-]*)(?: ⚠)? \| [\d,]+ \| [\d.]+% \| ([\d,]+) of ([\d,]+) \| "
    r"(?:[\d.]+%|—) \| ([\d,]+) of ([\d,]+) \|"
)


@dataclass(frozen=True)
class Area:
    """An area's reach: lines and branches reached, of how many."""

    lines: int
    of_lines: int
    branches: int
    of_branches: int

    @property
    def line_pct(self) -> float | None:
        return 100 * self.lines / self.of_lines if self.of_lines else None

    @property
    def branch_pct(self) -> float | None:
        return 100 * self.branches / self.of_branches if self.of_branches else None


def areas(log: str) -> dict[str, Area]:
    """Each measured area of the first per-area table in `log` (a job's log, or summary.md), in
    its order; `all` is the total. Areas not measured (QML) have no row of figures."""
    out: dict[str, Area] = {}
    for m in ROW.finditer(log):
        name = TOTAL if m.group(1) == "**all**" else m.group(1)
        if name in out:  # a second table (the summary printed again): the first holds
            break
        n = [int(g.replace(",", "")) for g in m.groups()[1:]]
        out[name] = Area(*n)
    return out


def mark(pct: float) -> str:
    """The band's mark of a coverage figure."""
    return next(sign for low, sign in BANDS if pct >= low)


def _pct(p: float | None, marked: bool = False) -> str:
    if p is None:
        return "—"
    return f"{mark(p)} {p:.1f}%" if marked else f"{p:.1f}%"


def _gain(a: float | None, b: float | None) -> str:
    return "—" if a is None or b is None else f"{b - a:+.1f}"


def _moved(a: float | None, b: float | None) -> bool:
    return (a is None) != (b is None) or (a is not None and b is not None and abs(b - a) >= MOVE)


def table(before: dict[str, Area], after: dict[str, Area]) -> str:
    """The impact table: an area that moved by MOVE points or more, a new or gone area, and the
    total always, total last; then the Legend line."""
    names = [n for n in after if n != TOTAL] + [n for n in before if n not in after]
    rows = [
        "| Area | Before (lines / branches) | After (lines / branches) | Gain (lines / branches) |",
        "|---|---|---|---|",
    ]
    for name in names + [TOTAL]:
        a, b = before.get(name), after.get(name)
        al, ab = (a.line_pct, a.branch_pct) if a else (None, None)
        bl, bb = (b.line_pct, b.branch_pct) if b else (None, None)
        if name != TOTAL and not (_moved(al, bl) or _moved(ab, bb)):
            continue
        label = f"**{name}**" if name == TOTAL else name
        rows.append(
            f"| {label} | {_pct(al)} / {_pct(ab)} | {_pct(bl, True)} / {_pct(bb, True)} "
            f"| {_gain(al, bl)} / {_gain(ab, bb)} |"
        )
    return "\n".join(rows) + "\n\n" + LEGEND + "\n"


Gh = Callable[[list[str]], str]


def gh(args: list[str]) -> str:
    """`gh` with `args`, its output."""
    return subprocess.run(["gh", *args], check=True, capture_output=True, text=True).stdout


def _coverage_job(gh: Gh, run: int | str) -> str | None:
    """The id of the run's coverage job when it passed: what the table needs, whatever else
    failed (a Pages deploy GitHub couldn't finish, a build that never got a runner)."""
    jobs = json.loads(gh(["run", "view", str(run), "--repo", REPO, "--json", "jobs"]))["jobs"]
    passed = [j for j in jobs if j["name"] == JOB and j["conclusion"] == "success"]
    return str(passed[0]["databaseId"]) if passed else None


def _measured(gh: Gh, run: int) -> bool:
    return _coverage_job(gh, run) is not None


def _green(gh: Gh, filters: list[str]) -> dict[str, str]:
    """The newest run of ci.yml under `filters` whose coverage job passed."""
    found = json.loads(
        gh(
            [
                "run",
                "list",
                "--repo",
                REPO,
                "--workflow",
                WORKFLOW,
                "--status",
                "completed",
                "--limit",
                str(LOOK_BACK),
                "--json",
                "databaseId,headSha",
                *filters,
            ]
        )  # fmt: skip
    )
    for run in found:
        if _measured(gh, run["databaseId"]):
            return {"id": str(run["databaseId"]), "sha": run["headSha"]}
    raise SystemExit(
        f"coverage_impact: no {WORKFLOW} run for {' '.join(filters)} whose {JOB} job passed"
    )


def runs_for_pr(gh: Gh, pr: int) -> tuple[dict[str, str], dict[str, str]]:
    """Master's last green run, and the pull request's on its head commit."""
    head = json.loads(gh(["pr", "view", str(pr), "--repo", REPO, "--json", "headRefOid"]))
    return (
        _green(gh, ["--branch", "master", "--event", "push"]),
        _green(gh, ["--commit", head["headRefOid"]]),
    )


def run_areas(gh: Gh, run: str) -> dict[str, Area]:
    """The areas the run's coverage job measured, from that job's log alone (a run's whole log
    can't be had while one of its jobs has none, as one cancelled before it started)."""
    job = _coverage_job(gh, run)
    if job is None:
        raise SystemExit(f"coverage_impact: run {run}'s {JOB} job didn't pass")
    log = gh(["run", "view", "--job", job, "--repo", REPO, "--log"])
    found = areas("\n".join(line for line in log.splitlines() if line.startswith(JOB + "\t")))
    if not found:
        raise SystemExit(f"coverage_impact: run {run} has no coverage table in its {JOB} job")
    return found


def report(gh: Gh, base: dict[str, str], head: dict[str, str]) -> str:
    """The section a pull request's description ends with: where the figures come from, the
    table, the legend."""

    def name(r: dict[str, str]) -> str:
        return f"{r['sha'][:8]} (run {r['id']})" if r.get("sha") else f"run {r['id']}"

    return f"Before: master at {name(base)}. After: this branch at {name(head)}.\n\n" + table(
        run_areas(gh, base["id"]), run_areas(gh, head["id"])
    )


def main(argv: list[str] | None = None, gh: Gh = gh) -> int:
    p = argparse.ArgumentParser(prog="coverage_impact.py", description=__doc__.split("\n\n")[0])
    p.add_argument("runs", nargs="*", metavar="RUN", help="the base run and the head run, by id")
    p.add_argument("--pr", type=int, help="the pull request: master's last green run against its")
    a = p.parse_args(argv)
    if a.pr is not None and not a.runs:
        base, head = runs_for_pr(gh, a.pr)
    elif a.pr is None and len(a.runs) == 2:
        base, head = {"id": a.runs[0]}, {"id": a.runs[1]}
    else:
        p.error("give --pr N, or the base run and the head run")
    sys.stdout.write(report(gh, base, head))
    return 0


if __name__ == "__main__":
    sys.exit(main())
