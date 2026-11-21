#!/usr/bin/env python3
"""A CI run's times (docs/github-workflows.md, "Tier 1's parts"): each job's wall time, slowest first,
the run's own, and how evenly tier 1's parts split the work. A part past BUDGET, or parts further
apart than SPREAD (the slowest over the quickest), fails the check: the parts are then split again,
by fresh times (`durations`) or into more parts. A change to what a test does to make it quicker is
the owner's to decide.

    scripts/ci_times.py [RUN | --pr N] [--attempt A]

With no argument, the run on the current branch's last pushed commit. The CI job `ci-times` runs it
on its own run. It reads GitHub's API through the gh CLI.

    scripts/ci_times.py durations [RUN | --pr N]

gathers what each test took in a run (its `durations-*` artifacts) into tests/durations/, a file per
area, by which CI splits tier 1 into parts (tests/parts.py): refreshed when the check finds the parts
uneven, or when tests are added or moved."""

import argparse
import datetime as dt
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPO = os.environ.get("GITHUB_REPOSITORY", "MojoKata/AppKata")
WORKFLOW = "CI"
BUDGET = 5 * 60     # seconds: a part past it is split further
SPREAD = 1.4        # the slowest part over the quickest: past it, the parts are split again
PART = re.compile(r"^(.*?) (\d+) of (\d+)\b")


def gh(*args):
    return subprocess.run([shutil.which("gh") or "gh", *args], capture_output=True, text=True, check=True).stdout


def seconds(start, end):
    if not start or not end:
        return None
    a, b = (dt.datetime.fromisoformat(x.replace("Z", "+00:00")) for x in (start, end))
    return int((b - a).total_seconds())


def clock(s):
    return "—" if s is None else f"{s // 60}m{s % 60:02d}s"


def report(jobs):
    """The run's lines, and what fails the check: each part past the budget, and each family of parts
    (tier1 1 of 3, ...) whose slowest is more than SPREAD times its quickest."""
    ran = [j for j in jobs if j.get("conclusion") not in ("skipped", None) and j.get("started_at")]
    times = {j["name"]: seconds(j["started_at"], j.get("completed_at")) for j in ran}
    starts = [j["started_at"] for j in ran]
    ends = [j["completed_at"] for j in ran if j.get("completed_at")]
    wall = seconds(min(starts), max(ends)) if starts and ends else None
    lines = [f"run: {clock(wall)} from the first job's start to the last one's end"]
    families = {}
    for name, s in times.items():
        if (m := PART.match(name)) and s:
            families.setdefault(m[1], []).append((name, s))
    parts = {name for ps in families.values() for name, _ in ps}
    for name, s in sorted(times.items(), key=lambda kv: -(kv[1] or 0)):
        mark = "  ⚠ over budget" if name in parts and s is not None and s > BUDGET else ""
        lines.append(f"  {clock(s):>8}  {name}{mark}")
    todo = [f"{n}: {clock(s)}, past the {clock(BUDGET)} budget" for ps in families.values() for n, s in ps if s > BUDGET]
    for family, ps in sorted(families.items()):
        ts = [s for _, s in ps]
        if len(ts) > 1:
            lines.append(f"{family}: {len(ts)} parts, {clock(min(ts))} to {clock(max(ts))}, "
                         f"{max(ts) / min(ts):.2f}:1 (at most {SPREAD}:1)")
            if max(ts) > SPREAD * min(ts):
                todo.append(f"{family}: parts from {clock(min(ts))} to {clock(max(ts))}, more than {SPREAD}:1")
    return lines, todo


def find_run(pr):
    if pr is not None:
        sha = gh("pr", "view", str(pr), "-R", REPO, "--json", "headRefOid", "-q", ".headRefOid")
    else:
        sha = subprocess.run([shutil.which("git") or "git", "rev-parse", "@{push}"], cwd=ROOT,
                             capture_output=True, text=True).stdout
    runs = json.loads(gh("api", f"repos/{REPO}/actions/runs?head_sha={sha.strip()}"))
    found = [r for r in runs["workflow_runs"] if r["name"] == WORKFLOW]
    if not found:
        raise SystemExit(f"no {WORKFLOW} run for {sha.strip()[:7]} yet")
    return str(found[0]["id"])


def _parts_module():
    spec = importlib.util.spec_from_file_location("appkata_parts", ROOT / "tests" / "parts.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def durations(argv=None):
    p = argparse.ArgumentParser(prog="scripts/ci_times.py durations", description="what each test took")
    p.add_argument("run", nargs="?", help="a run id; by default the current branch's last run")
    p.add_argument("--pr", type=int, help="the run on a pull request's head")
    args = p.parse_args(argv)
    run = args.run or find_run(args.pr)
    parts = _parts_module()
    with tempfile.TemporaryDirectory() as tmp:
        gh("run", "download", run, "-R", REPO, "-p", "durations-*", "-D", tmp)
        files = sorted(Path(tmp).rglob("*.json"))
        if not files:
            raise SystemExit(f"run {run} kept no durations")
        found = parts.gathered([json.loads(f.read_text()) for f in files])
    found.pop("none", None)        # a test in no area: tests/test_areas.py fails on it
    parts.write(found)
    named = sum(len(d["tests"]) for d in found.values())
    print(f"tests/durations/: {len(found)} areas, {named} tests named, from {len(files)} parts of run {run}")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="scripts/ci_times.py", description=__doc__.split("\n\n")[0])
    p.add_argument("run", nargs="?", help="a run id; by default the current branch's last run")
    p.add_argument("--pr", type=int, help="the run on a pull request's head")
    p.add_argument("--attempt", type=int, help="the run's attempt (by default its latest)")
    args = p.parse_args(argv)
    run = args.run or find_run(args.pr)
    path = f"repos/{REPO}/actions/runs/{run}" + (f"/attempts/{args.attempt}" if args.attempt else "") + "/jobs?per_page=100"
    lines, todo = report(json.loads(gh("api", path))["jobs"])
    text = "\n".join([f"CI run {run}", *lines, "",
                      *(["to split again:", *(f"  {t}" for t in todo)] if todo else ["within budget: nothing to split"])])
    print(text)
    if os.environ.get("GITHUB_ACTIONS") == "true":
        if os.environ.get("GITHUB_STEP_SUMMARY"):
            with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
                f.write("## CI times\n\n```\n" + text + "\n```\n")
        for t in todo:
            print(f"::error title=ci-times::{t}")
    return 1 if todo else 0


if __name__ == "__main__":
    if sys.argv[1:2] == ["durations"]:
        sys.exit(durations(sys.argv[2:]))
    sys.exit(main())
