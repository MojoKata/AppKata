"""Tier 1's parts in CI (docs/github-workflows.md): `APPKATA_PART=k/n` keeps the k-th of n parts of
the tests collected, split by measured time so the parts take about as long as each other.

A unit is a test, or the tests that share a fixture of module or class scope, which stay together so
the fixture is set up once. Each unit weighs its tests' times from tests/durations/<area>.json (the
area is the test file's, scripts/areas.py); a test not named there weighs what a short test of its
area takes. The units go longest first, each to the part with the least so far, the first such on a
tie. Times out of date make the parts less even, never a test run twice or not at all.

With `APPKATA_DURATIONS=<file>`, a run writes what its tests took (setup, call and teardown): those
of at least KEEP seconds by name, the rest as a total and a count, by area.
`scripts/ci_times.py durations RUN` gathers a CI run's files into tests/durations/."""

import functools
import importlib.util
import json
import os
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DURATIONS = ROOT / "tests" / "durations"
KEEP = 1.0      # seconds: a test at least this long is named in its area's file
SHORT = 0.05    # seconds: what a test weighs whose area has no file yet



@functools.cache
def _areas():
    """scripts/areas.py, loaded only when a run is split or timed: the VM tiers carry tests/ without it."""
    spec = importlib.util.spec_from_file_location("appkata_areas", ROOT / "scripts" / "areas.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def area_of_test(test):
    return _areas().area_of_test(test)


def load(folder=DURATIONS):
    """The named tests' times, and what a short test of each area takes."""
    times, short = {}, {}
    for path in sorted(Path(folder).glob("*.json")):
        d = json.loads(path.read_text())
        times.update(d["tests"])
        short[path.stem] = d["short"]
    return times, short


def weight(test, times, short):
    """What a test takes: its own time, or what a short test of its area takes."""
    return times[test] if test in times else short.get(area_of_test(test), SHORT)


def assign(weights, n):
    """Each unit's part (0 to n-1): the heaviest first, each to the part with the least."""
    load_ = [0.0] * n
    out = [0] * len(weights)
    for i in sorted(range(len(weights)), key=lambda i: (-weights[i], i)):
        p = min(range(n), key=lambda j: (load_[j], j))
        out[i] = p
        load_[p] += weights[i]
    return out


def choose(items, k, n, times, short):
    """Whether each test, given as (test id, its unit's key or None), is in part k of n."""
    units = {}
    for i, (test, unit) in enumerate(items):
        units.setdefault(f"unit:{unit}" if unit else test, []).append(i)
    keys = list(units)
    part = assign([sum(weight(items[i][0], times, short) for i in units[u]) for u in keys], n)
    keep = [False] * len(items)
    for u, p in zip(keys, part):
        for i in units[u]:
            keep[i] = p == k - 1
    return keep


def unit(item):
    """The key that keeps a test with the others sharing its module- or class-scoped fixture, or None.
    pytest names a test's fixtures in its _fixtureinfo (pytest is pinned: packaging/versions.env)."""
    info = getattr(item, "_fixtureinfo", None)
    scopes = {d.scope for defs in (info.name2fixturedefs.values() if info else ()) for d in defs}
    if "module" in scopes or "package" in scopes:
        return item.nodeid.split("::")[0]
    if "class" in scopes and item.cls is not None:
        return item.nodeid.rsplit("::", 1)[0]
    return None


def parse(value):
    """APPKATA_PART's k and n."""
    k, _, n = value.partition("/")
    k, n = int(k), int(n)
    if not 1 <= k <= n:
        raise ValueError(f"APPKATA_PART={value}: k/n with 1 <= k <= n")
    return k, n


class Recorder:
    """What each test took, added up over its phases, for APPKATA_DURATIONS."""

    def __init__(self):
        self.took = defaultdict(float)

    def add(self, test, duration):
        self.took[test] += duration

    def written(self):
        """{area: {"tests": {test: seconds} of the long ones, "shortTotal", "shortCount"}}."""
        out = {}
        for test, s in sorted(self.took.items()):
            a = out.setdefault(area_of_test(test) or "none", {"tests": {}, "shortTotal": 0.0, "shortCount": 0})
            if s >= KEEP:
                a["tests"][test] = round(s, 1)
            else:
                a["shortTotal"] += s
                a["shortCount"] += 1
        for a in out.values():
            a["shortTotal"] = round(a["shortTotal"], 2)
        return out


def gathered(runs):
    """A run's parts' files (each Recorder.written()) as tests/durations/ keeps them, by area:
    each long test by name, and what a short one takes on average."""
    out = {}
    for run in runs:
        for area, d in run.items():
            a = out.setdefault(area, {"tests": {}, "total": 0.0, "count": 0})
            a["tests"].update(d["tests"])
            a["total"] += d["shortTotal"]
            a["count"] += d["shortCount"]
    # a short test weighs at least a millisecond: weighing nothing, every one would go to part 1
    return {area: {"short": max(round(a["total"] / a["count"], 3), 0.001) if a["count"] else SHORT,
                   "tests": dict(sorted(a["tests"].items()))}
            for area, a in sorted(out.items())}


def write(found, folder=DURATIONS):
    """tests/durations/ made from gathered(): a file per area, and none for an area no test ran in."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    for old in folder.glob("*.json"):
        if old.stem not in found:
            old.unlink()
    for area, d in found.items():
        (folder / f"{area}.json").write_text(json.dumps(d, indent=1) + "\n")


def env_part():
    value = os.environ.get("APPKATA_PART")
    return parse(value) if value else None
