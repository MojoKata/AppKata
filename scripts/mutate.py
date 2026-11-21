#!/usr/bin/env python3
"""Mutation testing (docs/testing.md, "Mutation testing"): mutmut changes AppKata's code a change
at a time and runs the tests that reach it; a change no test fails on survives.

    sh scripts/test-mutate.sh run MODULE... [--workers N] [--only NAME...] [--resume DIR]
    sh scripts/test-mutate.sh summary | check CHANGE TEST | export DIR --name N --area A --modules M
    scripts/mutate.py plan [--areas GLOB...] [--size LINES] [--jobs NAME...] [--modules PATH...]
    scripts/mutate.py gather RUN... [--repo OWNER/NAME] | record --from DIR... [--commit REV] | stale

`run`, `summary`, `check` and `export` need mutmut, and run in tier 1's container
(scripts/test-mutate.sh); `plan`, `gather` and `record` run on any Python 3.

`run` makes a copy of the repository in APPKATA_MUTATE_WORK (mutmut changes the code it tests,
so never the checkout): src/, scripts/ and tests/ copied, everything else at the root linked into
mutmut's mutants/, so a test reads the repository as it does in tier 1. It writes mutmut's settings
and runs it over the modules named (paths from the root, such as src/appkata_core/windows.py) with
tier 1's tests, less those a mutation run can't use (UNFIT); mutmut runs each change against the
tests that reached its function when it ran them once first. The run is stopped past --limit GB
(PSS) of memory, and a change's worker past --worker-limit GB of its own, that change counted
killed. At the end, and with `summary`, it prints the outcomes by file and the survivors by
function, and writes each survivor's change to survivors.txt.

`--resume DIR` goes on from an earlier run of the same modules (its `export` folder): mutmut runs
only the changes it left without an outcome, such as a job out of time.

`check` runs one change against one test file by hand, the changed code ahead of the original.

The baseline (.github/workflows/mutate.yml): `plan` packs each area's modules (scripts/areas.py)
into jobs of about --size code lines, as JSON for the workflow's matrix; each job is a `run` and an
`export`, which keeps its outcomes, survivors and log in a directory for the job's artifact.
`gather` downloads a run's artifacts and `record` reads such directories; both write each area's
baseline to docs/hardening/mutation/baseline-<area>.json (its outcomes, each file's content, its git
blob, so a file changed since shows, and the tests its runs left out) and its survivors to
docs/hardening/mutation/survivors/<area>.json, each with its function, line and change, one a line.
A later directory's outcome for a change wins over an earlier one's (a job run again).

`stale` names each module whose content (its git blob) isn't what its area's latest record mutated,
and each module an area holds that no record covers: the counts out of date, for the next run.
"""

from __future__ import annotations

import argparse
import ast
import contextlib
import fnmatch
import functools
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import areas  # noqa: E402

WORK = Path(os.environ.get("APPKATA_MUTATE_WORK") or ROOT / "build" / "mutate")
COPY = WORK / "copy"
MUTANTS = COPY / "mutants"
RECORDS = ROOT / "docs" / "hardening" / "mutation"
REPO = "MojoKata/AppKata"
COPIED = ("src", "scripts", "tests")  # copied: what mutmut mutates, and the tests it copies itself
UNLINKED = {*COPIED, "build", "mutants"}  # not linked into mutants/
SOURCES = ("src", "scripts")  # mutmut's source_paths: where a change's file is
# Never mutated: mutmut's own plugin, which runs inside its sessions.
NOT_MUTATED = ["scripts/mutate_plugin.py"]
LIMIT_GB = 5.0  # the run stops past this (PSS); CI's runners give it more (--limit)
WORKER_GB = 2.0  # one change's worker past this much of its own is stopped, the change killed
OUT_OF_MEMORY = -signal.SIGUSR1  # mutmut keeps a worker stopped so as this exit code

# Where the code as written is, for a test that reads a module's source rather than running it
# (tests/written.py): in a run, the checkout, since the copy's modules are mutmut's, every change in
# one file.
WRITTEN = "APPKATA_WRITTEN_ROOT"

# Tier 1's tests a mutation run can't use, and why: mutmut runs every test once first, and stops
# at the first that fails. None of them runs AppKata's code in pytest's process, which is all
# mutmut can trace.
UNFIT = {
    "tests/test_publish.py::test_git_keeps_every_file_the_release_reads":
        "asks git whether it ignores files under docs/, which the copy links, and git won't look past a link",
}

# mutmut's exit codes as outcomes (mutmut.stats.status_by_exit_code), the run's own stop as killed.
OUTCOME = {1: "killed", 3: "killed", OUT_OF_MEMORY: "killed", 0: "survived", 5: "no tests",
           33: "no tests", 36: "timeout", 24: "timeout", -24: "timeout", 152: "timeout",
           255: "timeout", None: "not run"}  # fmt: skip
COUNTED = ("killed", "timeout", "survived", "no tests", "other", "not run")

# Each change's tests run in one session; a test's temporary folder goes when it passes, and the
# plugin names the change's worker for the watcher.
PYTEST_ARGS = ["-p", "no:cacheprovider", "-o", "tmp_path_retention_policy=failed",
               "-p", "scripts.mutate_plugin"]  # fmt: skip


# --- what is mutated, and how it is packed into jobs ------------------------------------------------


def code_lines(path: Path) -> int:
    """A file's lines of code: not blank, not a comment."""
    lines = path.read_text(encoding="utf-8").splitlines()
    return sum(1 for x in lines if x.strip() and not x.lstrip().startswith("#"))


def modules(root: Path = ROOT) -> dict[str, tuple[str, int]]:
    """Each Python file an area holds: its area and code lines. Not QML, which mutmut can't read,
    nor NOT_MUTATED, nor a file without code."""
    out = {}
    for pattern in sorted({p for ps in areas.CODE.values() for p in ps}):
        for p in sorted(root.glob(pattern)):
            rel = p.relative_to(root).as_posix()
            if not rel.endswith(".py") or rel in NOT_MUTATED or "__pycache__" in rel:
                continue
            area = areas.area_of_code(rel)
            if area and (n := code_lines(p)):
                out[rel] = (area, n)
    return dict(sorted(out.items()))


def pack(sizes: dict[str, int], size: int) -> list[list[str]]:
    """Modules in jobs of about `size` code lines, the largest first, each into the first job with
    room; a module larger than `size` is a job of its own."""
    jobs: list[tuple[int, list[str]]] = []
    for m, n in sorted(sizes.items(), key=lambda kv: (-kv[1], kv[0])):
        for i, (total, ms) in enumerate(jobs):
            if total + n <= size:
                jobs[i] = (total + n, [*ms, m])
                break
        else:
            jobs.append((n, [m]))
    return [sorted(ms) for _, ms in jobs]


def plan_jobs(found: dict[str, tuple[str, int]], globs: list[str], size: int) -> list[dict]:
    """The baseline's jobs: each area's modules (of the areas the globs name) packed by size."""
    by_area: dict[str, dict[str, int]] = defaultdict(dict)
    for m, (area, n) in found.items():
        if any(fnmatch.fnmatchcase(area, g) for g in globs):
            by_area[area][m] = n
    out = []
    for area in sorted(by_area):
        for k, ms in enumerate(pack(by_area[area], size), 1):
            lines = sum(by_area[area][m] for m in ms)
            out.append({"name": f"{area}-{k}", "area": area, "lines": lines,
                        "size": f"{lines} lines", "modules": " ".join(ms)})  # fmt: skip
    return out


def plan(args) -> int:
    found = modules()
    if args.modules:
        unknown = sorted(set(args.modules) - set(found))
        if unknown:
            print(f"not a module an area holds: {' '.join(unknown)}", file=sys.stderr)
            return 1
        found = {m: v for m, v in found.items() if m in args.modules}
    jobs = plan_jobs(found, args.areas, args.size)
    if args.jobs:  # an earlier run's jobs again: the same tree's plan names them the same
        unknown = sorted(set(args.jobs) - {j["name"] for j in jobs})
        if unknown:
            print(f"not in the plan: {' '.join(unknown)}", file=sys.stderr)
            return 1
        jobs = [j for j in jobs if j["name"] in args.jobs]
    print(json.dumps(jobs))
    print(f"{len(jobs)} jobs, {sum(j['lines'] for j in jobs)} code lines", file=sys.stderr)
    return 0


# --- a run, in tier 1's container ----------------------------------------------------------------


def tests(root: Path = ROOT) -> list[str]:
    """The test files a run uses: tier 1's, each of them (UNFIT's tests are deselected)."""
    return [f"tests/{f.name}" for f in sorted((root / "tests").glob("test_*.py"))]


def make_copy() -> None:
    """The copy mutmut runs in: COPIED copied, the rest of the root linked into mutants/, where
    mutmut runs the tests, and an empty mutants/ otherwise (a run starts afresh)."""
    shutil.rmtree(COPY, ignore_errors=True)
    MUTANTS.mkdir(parents=True)
    for name in COPIED:
        shutil.copytree(ROOT / name, COPY / name, symlinks=True,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))  # fmt: skip
    for p in sorted(ROOT.iterdir()):
        if p.name not in UNLINKED and p.name != "pyproject.toml":
            (MUTANTS / p.name).symlink_to(p)


USERBASE = WORK / "userbase"  # PYTHONUSERBASE for the run: its user site holds mutmut alone


def user_site(base: Path) -> Path:
    """The user site Python reads under PYTHONUSERBASE=base (site.getusersitepackages, POSIX)."""
    return base / "lib" / f"python{sys.version_info[0]}.{sys.version_info[1]}" / "site-packages"


def link_mutmut(package: Path | None = None) -> None:
    """mutmut's package and its metadata alone, linked into the run's user site (PYTHONUSERBASE, which the tests'
    processes inherit), and USERCUSTOMIZE. A changed module imports mutmut's trampoline (the standard library only),
    and a test that starts Python with a PYTHONPATH of its own still finds it there."""
    if package is None:
        import importlib.util

        package = Path(importlib.util.find_spec("mutmut").origin).parent
    shutil.rmtree(USERBASE, ignore_errors=True)
    user_site(USERBASE).mkdir(parents=True)
    for p in [package, *package.parent.glob("mutmut-*.dist-info")]:  # its version is read from its metadata
        (user_site(USERBASE) / p.name).symlink_to(p)
    (user_site(USERBASE) / "usercustomize.py").write_text(USERCUSTOMIZE)


# Run by every Python the tests start (the user site's usercustomize): mutmut's first pass counts
# which tests call each function, with MUTANT_UNDER_TEST=stats, which a test's own processes
# inherit; there a changed function would count its call in mutmut's settings, which a process
# started elsewhere can't read, and fail. Such a process runs the code unchanged instead, as its
# calls can't be counted anyway.
USERCUSTOMIZE = """import os
if os.environ.get("MUTANT_UNDER_TEST") == "stats":
    os.environ["MUTANT_UNDER_TEST"] = ""
"""


def resume(earlier: Path) -> int:
    """An earlier run's outcomes (an `export` folder's .meta files) put where mutmut keeps them, so
    it runs only the changes they leave without one: mutmut keeps an outcome while its function's
    code is the same. Returns the outcomes carried."""
    carried = 0
    for rel, keys in codes(earlier).items():
        (MUTANTS / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(earlier / f"{rel}.meta", MUTANTS / f"{rel}.meta")
        carried += sum(c is not None for c in keys.values())
    return carried


def settings(mutate: list[str], selected: list[str], text: str, debug: bool = False,
             dropped: dict | None = None) -> str:
    """pyproject.toml with mutmut's settings: the modules, the tests, PYTEST_ARGS; with `debug`,
    mutmut prints each pytest run's command and output (a first run that fails says which test)."""
    text = re.sub(r"\n\[tool\.mutmut\][^\[]*", "\n", text)
    return text + (
        "\n[tool.mutmut]\n"
        f"source_paths = {json.dumps(list(SOURCES))}\n"
        f"only_mutate = {json.dumps(mutate)}\n"
        f"do_not_mutate = {json.dumps(NOT_MUTATED)}\n"
        f"pytest_add_cli_args_test_selection = {json.dumps(selected)}\n"
        f"pytest_add_cli_args = {json.dumps(PYTEST_ARGS + deselected(dropped))}\n"
        # Each session in a fork of a process that only collected the tests: in mutmut's fork mode
        # the workers fork from the process that ran them all, with Qt's threads gone in the fork.
        'process_isolation = "forkserver"\n'
        # The copy is a fresh one each run, and isn't a checkout: nothing to compare with.
        "use_git_change_detection = false\n"
        + ("debug = true\n" if debug else "")
    )


def deselected(dropped: dict | None = None) -> list[str]:
    """pytest's arguments that leave out UNFIT's tests and those a run dropped."""
    return [x for t in sorted({*UNFIT, *(dropped or {})}) for x in ("--deselect", t)]


def configure(mutate: list[str], selected: list[str], debug: bool = False, dropped: dict | None = None) -> None:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    (COPY / "pyproject.toml").write_text(settings(mutate, selected, text, debug, dropped), encoding="utf-8")


def _cmdline(pid: str) -> str:
    return Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")


def _run_pids() -> list[int]:
    """This copy's mutmut and its workers, still running: they rename themselves
    `mutmut: <change>` (mutate_plugin) or are `python -m mutmut run`."""
    out = []
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            cmd = _cmdline(pid)
            if not (cmd.startswith("mutmut: ") or "-m mutmut run" in cmd):
                continue
            cwd = Path(f"/proc/{pid}/cwd").resolve()
            if cwd == COPY.resolve() or COPY.resolve() in cwd.parents:
                out.append(int(pid))
        except OSError:
            continue
    return out


def _rollup(pid: int, *keys: str) -> float:
    """The sum of smaps_rollup's keys for a process, in GB."""
    total = 0
    for line in Path(f"/proc/{pid}/smaps_rollup").read_text().splitlines():
        if line.startswith(keys):
            total += int(line.split()[1])
    return total / 1024 / 1024


def _pss_gb() -> float:
    """The run's memory: mutmut and its workers, each page shared counted once (PSS)."""
    total = 0.0
    for pid in _run_pids():
        with contextlib.suppress(OSError):
            total += _rollup(pid, "Pss:")
    return total


def _workers() -> dict[int, tuple[str, float]]:
    """This run's change workers still running: each one's change and its own memory."""
    out = {}
    for pid in _run_pids():
        try:
            cmd = _cmdline(str(pid))
            if cmd.startswith("mutmut: "):
                out[pid] = (cmd.removeprefix("mutmut: ").strip(), _rollup(pid, "Private_Clean:", "Private_Dirty:"))
        except OSError:
            continue
    return out


def runaways(workers: dict[int, tuple[str, float]], cap: float) -> list[int]:
    """The workers past the memory one change may use."""
    return [pid for pid, (_, gb) in workers.items() if gb > cap]


def mutmut_command(args) -> list[str]:
    """mutmut over the changes --only and --only-file name, or every one."""
    only = [*(args.only or []), *(Path(args.only_file).read_text().split() if args.only_file else [])]
    return [sys.executable, "-m", "mutmut", "run", "--max-children", str(args.workers), *only]


def only_mutate(names: list[str]) -> list[str]:
    """mutmut's only_mutate patterns for modules named from the root."""
    return [n.rstrip("/") + "/*" if (ROOT / n).is_dir() else n for n in names]


DROPPED = 40  # the most tests a run leaves out as failing in its copy (DROPPED_FILE says which)


def run(args) -> int:
    known = modules()
    unknown = [m for m in args.modules if m not in known and not (ROOT / m).is_dir()]
    if unknown:
        print(f"not a module an area holds: {' '.join(unknown)}")
        return 2
    selected = tests()
    print(f"mutating {', '.join(args.modules)}, with {len(selected)} test files")
    make_copy()
    link_mutmut()
    if args.resume:
        print(f"going on from {resume(Path(args.resume))} outcomes of an earlier run")
    dropped: dict[str, dict] = {}
    (WORK / DROPPED_FILE).write_text("{}\n")
    while True:
        configure(only_mutate(args.modules), selected, args.debug, dropped)
        rc, stopped = mutmut(args)
        text = (WORK / "mutmut.log").read_text(errors="replace")
        if not rc or stopped or not FIRST_PASS_FAILED.search(text):
            break
        # A test fails in mutmut's first pass, which doesn't say which: one that reads a module's
        # source, which in the copy is mutmut's, say. Each such test is run once on the checkout
        # itself: one that fails there too is a real failure, and stops the run; the others are
        # left out of this run, each with its traceback and the kind of failure it looks like.
        print("mutmut's first pass over the tests failed, and says no more; pytest on the copy:")
        failing, shown_ = first_failure(selected, dropped)
        print(shown_)
        new = [t for t in failing if t not in dropped]
        if not new or len(dropped) + len(new) > DROPPED:
            break
        real = [t for t in new if not passes_as_written(t)]
        if real:
            print(f"failing on the checkout too, so a real failure, not the copy's: {' '.join(real)}")
            return 3
        for t in new:
            trace = traceback_of(t)
            dropped[t] = {"kind": kind_of(trace), "trace": trace}
        (WORK / DROPPED_FILE).write_text(json.dumps(dropped, indent=1) + "\n")
        print(f"left out of this run, and run again (each passes on the checkout): {' '.join(new)}")
    if rc:
        print("its log's last lines:\n" + "\n".join(log_lines(text)[-30:]))
    if dropped:
        print(f"{len(dropped)} tests left out, failing in the copy: {' '.join(dropped)}")
    summary(None)
    return 1 if stopped else rc


DROPPED_FILE = "dropped.json"


def mutmut(args) -> tuple[int, bool]:
    """mutmut over the copy, its memory watched: its exit code, and whether the watcher stopped it."""
    log = (WORK / "mutmut.log").open("w")
    env = {k: v for k, v in os.environ.items() if k != "APPKATA_SKIPS"}  # tier 1 checks skips; not here
    env["PYTHONUSERBASE"] = str(USERBASE)
    env[WRITTEN] = str(ROOT)
    proc = subprocess.Popen(mutmut_command(args), cwd=COPY, stdout=log, stderr=subprocess.STDOUT, env=env)  # noqa: S603
    peak, largest, stopped = 0.0, 0.0, threading.Event()

    def watch() -> None:
        nonlocal peak, largest
        while proc.poll() is None:
            workers = _workers()
            largest = max([largest, *(gb for _, gb in workers.values())])
            for pid in runaways(workers, args.worker_limit):
                name, gb = workers[pid]
                print(f"stopped {name}: {gb:.1f} GB of its own, past {args.worker_limit:.1f} GB", flush=True)
                with contextlib.suppress(OSError):
                    os.kill(pid, -OUT_OF_MEMORY)
            gb = _pss_gb()
            peak = max(peak, gb)
            if gb > args.limit:
                print(f"stopping: {gb:.1f} GB past the {args.limit:.1f} GB limit", flush=True)
                stopped.set()
                proc.terminate()
                return
            time.sleep(5)

    threading.Thread(target=watch, daemon=True).start()
    started = time.monotonic()
    while proc.poll() is None:
        time.sleep(30)
        print(f"  {int(time.monotonic() - started) // 60:4} min  {_progress()}", flush=True)
    log.close()
    print(f"mutmut exited {proc.returncode} after {int(time.monotonic() - started) // 60} min; peak memory "
          f"{peak:.1f} GB (PSS), a worker's own at most {largest:.1f} GB; log: {WORK / 'mutmut.log'}")  # fmt: skip
    return proc.returncode, stopped.is_set()


# what mutmut says when a test fails in its first passes over the tests, without saying which
FIRST_PASS_FAILED = re.compile(r"failed to collect stats|Failed to run clean test")


def log_lines(text: str) -> list[str]:
    """mutmut's log without its spinner's frames: the lines it redraws in place, but the last."""
    lines = [x.strip() for x in text.replace("\r", "\n").splitlines() if x.strip()]
    out = []
    for x in lines:
        if out and x[:1] in SPINNER and out[-1][:1] in SPINNER and x[1:].strip()[:12] == out[-1][1:].strip()[:12]:
            out[-1] = x
        else:
            out.append(x)
    return out


SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


def copy_env() -> dict[str, str]:
    """The environment of a pass like mutmut's first, in the copy: counting calls as it does, with
    the run's user site, and the copy's code ahead of the rest."""
    env = {k: v for k, v in os.environ.items() if k != "APPKATA_SKIPS"}
    env["PYTHONUSERBASE"] = str(USERBASE)
    env["MUTANT_UNDER_TEST"] = "stats"  # as in mutmut's pass: each changed function counts its calls
    env[WRITTEN] = str(ROOT)
    env["PYTHONPATH"] = os.pathsep.join([str(MUTANTS / "src"), str(MUTANTS), env.get("PYTHONPATH", "")])
    return env


def first_failure(selected: list[str], dropped: dict | None = None) -> tuple[list[str], str]:
    """The tests failing in a pass like mutmut's first, in the copy, with mutate_plugin loaded: what
    mutmut's pass stopped on, which it doesn't name. Their ids (at most DROPPED), and pytest's short
    summary."""
    cmd = [sys.executable, "-m", "pytest", "-q", "--tb=no", "-rfE", f"--maxfail={DROPPED + 1}", *PYTEST_ARGS,
           *deselected(dropped), *selected]  # fmt: skip
    r = subprocess.run(cmd, cwd=MUTANTS, env=copy_env(), capture_output=True, text=True)  # noqa: S603
    out = (r.stdout + r.stderr).splitlines()
    summary_at = next((i for i, x in enumerate(out) if "short test summary info" in x), max(0, len(out) - 40))
    return failed_tests(out), "\n".join(out[summary_at:][-60:])


TRACE_LINES = 20  # of a dropped test's short traceback, the last


def traceback_of(test: str) -> str:
    """A test's short traceback in the copy (pytest's --tb=short), its last TRACE_LINES lines."""
    cmd = [sys.executable, "-m", "pytest", "-q", "--tb=short", "-p", "no:cacheprovider", *PYTEST_ARGS[2:], test]
    r = subprocess.run(cmd, cwd=MUTANTS, env=copy_env(), capture_output=True, text=True)  # noqa: S603
    return short_trace((r.stdout + r.stderr).splitlines())


def short_trace(lines: list[str]) -> str:
    """The failure's own lines of pytest's output: after its "___ name ___" header, before the
    summary, the last TRACE_LINES of them."""
    start = next((i + 1 for i, x in enumerate(lines) if re.match(r"^_{3,} .* _{3,}$", x)), 0)
    end = next((i for i, x in enumerate(lines) if "short test summary info" in x or re.match(r"^=+ .*(failed|error)", x)
                and i > start), len(lines))  # fmt: skip
    return "\n".join([x.rstrip() for x in lines[start:end] if x.strip()][-TRACE_LINES:])


def passes_as_written(test: str) -> bool:
    """Whether a test passes on the checkout itself, as tier 1 runs it: what makes a test failing in
    the copy the copy's, not a real failure."""
    env = {k: v for k, v in os.environ.items() if k not in ("APPKATA_SKIPS", "MUTANT_UNDER_TEST", WRITTEN)}
    env["PYTHONPATH"] = os.pathsep.join([str(ROOT / "src"), env.get("PYTHONPATH", "")])
    cmd = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", test]
    return subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True).returncode == 0  # noqa: S603


# The kinds of failure a test in the copy shows, by what its traceback says, the first that fits.
KINDS = (
    ("git or links in the copy", r"not a git repository|beyond a symbolic link|symlink|\bgit\b"),
    ("reads the mutated source", r"mutmut|trampoline|XX\w|\bast\b|object has no attribute '(elts|id|value|args)'"),
    ("leaks into processes tests start", r"subprocess|CalledProcessError|returncode|Popen|MUTANT_UNDER_TEST"),
)
UNKNOWN = "unknown"


def kind_of(trace: str) -> str:
    """The kind of failure a dropped test's traceback looks like (KINDS), or UNKNOWN: a guess, for the
    one who settles it."""
    return next((k for k, pattern in KINDS if re.search(pattern, trace)), UNKNOWN)


def unfit_entries(dropped: dict) -> list[str]:
    """For each dropped test UNFIT doesn't name, a line to paste into UNFIT, its kind the reason to
    write over."""
    out = []
    for test, why in sorted(dropped.items()):
        if test not in UNFIT:
            kind = why.get("kind", UNKNOWN) if isinstance(why, dict) else UNKNOWN
            out.append(f'    "{test}": "{kind}: <why, in a line>",')
    return out


def failed_tests(lines: list[str]) -> list[str]:
    """The tests pytest's short summary names as failed (-rfE), in its order."""
    out = []
    for x in lines:
        if (m := re.match(r"(?:FAILED|ERROR) (\S+?)(?: - .*)?$", x)) and m.group(1) not in out:
            out.append(m.group(1))
    return out


def as_kept(why) -> dict:
    """A dropped test's entry as a record keeps it, {"kind", "trace"}: an earlier run kept a line."""
    if isinstance(why, dict):
        return {"kind": why.get("kind", UNKNOWN), "trace": why.get("trace", "")}
    text = str(why).strip()
    text = "" if text.startswith(("FAILED ", "ERROR ")) else text
    return {"kind": kind_of(text), "trace": text}


def _progress() -> str:
    try:
        tail = (WORK / "mutmut.log").read_bytes()[-400:].decode(errors="replace")
    except OSError:
        return "starting"
    lines = [x for x in tail.replace("\r", "\n").split("\n") if x.strip()]
    return lines[-1].strip()[:100] if lines else "starting"


def codes(mutants: Path) -> dict[str, dict[str, int | None]]:
    """Each change's exit code from mutmut's .meta files under `mutants`, by file from the root."""
    out = {}
    for top in SOURCES:
        for meta in sorted((mutants / top).rglob("*.meta")):
            rel = meta.relative_to(mutants).as_posix().removesuffix(".meta")
            out[rel] = json.loads(meta.read_text())["exit_code_by_key"]
    return out


def outcome(code: int | None) -> str:
    return OUTCOME.get(code, "other")


def counted(by_file_codes: dict[str, dict[str, int | None]]):
    """Exit codes by file as outcomes: by file, by function, and the survivors' names."""
    by_file: dict[str, Counter] = defaultdict(Counter)
    by_fn: dict[str, Counter] = defaultdict(Counter)
    survivors = []
    for rel, keys in by_file_codes.items():
        for name, code in keys.items():
            what = outcome(code)
            by_file[rel][what] += 1
            by_fn[name.rsplit("__mutmut_", 1)[0]][what] += 1
            if what == "survived":
                survivors.append(name)
    return by_file, by_fn, survivors


def summary(_args) -> int:
    """The outcomes by file and the survivors by function, and each survivor's change."""
    by_file, by_fn, survivors = counted(codes(MUTANTS))
    if not by_file:
        print("no run yet")
        return 1
    print("\nby file:" + "".join(f" {k}," for k in COUNTED).rstrip(","))
    for rel, c in by_file.items():
        print(f"  {rel:40}" + "".join(f" {c[k]:6}" for k in COUNTED))
    print("\nsurvivors by function")
    for fn, c in sorted(by_fn.items(), key=lambda x: -x[1]["survived"]):
        if c["survived"]:
            print(f"  {c['survived']:4} of {sum(c.values()):4}  {fn}")
    write_survivors(WORK / "survivors.txt", survivors, files_of(MUTANTS))
    print(f"\n{len(survivors)} survivors; each change in {WORK / 'survivors.txt'}")
    dropped = json.loads((WORK / DROPPED_FILE).read_text()) if (WORK / DROPPED_FILE).exists() else {}
    print_unfit(dropped)
    return 0


def print_unfit(dropped: dict) -> None:
    """The tests a run left out, and for those UNFIT doesn't name, the lines to settle them with in
    UNFIT, if leaving them out is right (else the test is changed so it doesn't depend on the copy)."""
    lines = unfit_entries(dropped)
    if lines:
        print(f"\n{len(lines)} tests left out, failing in the copy only; for UNFIT, each with its real reason:")
        print("\n".join(lines))


def files_of(mutants: Path) -> dict[str, str]:
    """Each change's file from the root, by its .meta."""
    return {n: rel for rel, keys in codes(mutants).items() for n in keys}


def shown(names: dict[str, str], generate: bool = False) -> dict[str, str]:
    """`mutmut show`'s diff of each change, in one process in the copy (mutate_plugin)."""
    cmd = [sys.executable, str(ROOT / "scripts" / "mutate_plugin.py")]
    asked = json.dumps({"generate": generate, "names": names})
    r = subprocess.run(cmd, cwd=COPY, input=asked, capture_output=True, text=True, check=True)  # noqa: S603
    return json.loads(r.stdout.strip().rsplit("\n", 1)[-1])


def write_survivors(path: Path, survivors: list[str], files: dict[str, str]) -> None:
    """Each survivor's name and its diff's lines, as `diffs` reads them."""
    got = shown({n: files[n] for n in survivors}) if survivors else {}
    with path.open("w", encoding="utf-8") as out:
        for name in survivors:
            out.write(f"# {name}\n" + "".join(x + "\n" for x in hunk(got.get(name, ""))))


def hunk(diff: str) -> list[str]:
    """The lines of `mutmut show`'s diff, without its headers: unchanged (` `), removed (`-`) and
    added (`+`)."""
    lines = diff.splitlines()
    at = next((i for i, x in enumerate(lines) if x.startswith("@@")), len(lines))
    return [x for x in lines[at + 1 :] if x[:1] in (" ", "-", "+")]


def check(args) -> int:
    """One change against one test file, the changed code ahead of the original."""
    test = f"tests/{Path(args.test).name}"
    if (ROOT / test).exists():  # the test as it is now, written since the run
        shutil.copy2(ROOT / test, MUTANTS / test)
    env = {**os.environ, "MUTANT_UNDER_TEST": args.change}
    env["PYTHONPATH"] = os.pathsep.join([str(MUTANTS / "src"), str(MUTANTS), env.get("PYTHONPATH", "")])
    flags = ["-q", "-p", "no:cacheprovider"]
    r = subprocess.run([sys.executable, "-m", "pytest", test, *flags], cwd=MUTANTS, env=env)  # noqa: S603
    print("caught" if r.returncode else "not caught: every test passed with the change")
    return 0


def export(args) -> int:
    """The last run's outcomes (mutmut's .meta files), survivors and log, in `dir`. A run the
    job's time limit stopped is stopped here for good first; what it finished is kept, since mutmut
    saves each outcome as it comes."""
    for pid in _run_pids():
        with contextlib.suppress(OSError):
            os.kill(pid, signal.SIGKILL)
    out = Path(args.dir)
    out.mkdir(parents=True, exist_ok=True)
    for top in SOURCES:
        for meta in (MUTANTS / top).rglob("*.meta"):
            at = out / meta.relative_to(MUTANTS)
            at.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(meta, at)
    by_file, _, survivors = counted(codes(MUTANTS))
    if (WORK / "survivors.txt").exists():
        shutil.copy2(WORK / "survivors.txt", out / "survivors.txt")
    else:  # a run stopped before its summary: the diffs from its mutants, or the names alone
        try:
            write_survivors(out / "survivors.txt", survivors, files_of(MUTANTS))
        except (OSError, subprocess.CalledProcessError, ValueError):
            (out / "survivors.txt").write_text("".join(f"# {n}\n" for n in survivors))
    if (WORK / "mutmut.log").exists():
        shutil.copy2(WORK / "mutmut.log", out / "mutmut.log")
    job = {"name": args.name, "area": args.area, "modules": args.modules}
    if (WORK / DROPPED_FILE).exists():
        job["dropped"] = json.loads((WORK / DROPPED_FILE).read_text())
    (out / "job.json").write_text(json.dumps(job) + "\n")
    changes = sum(sum(c.values()) for c in by_file.values())
    print(f"{out}: {changes} changes, {len(survivors)} survivors")
    return 0


# --- the baseline, from the jobs' directories -------------------------------------------------------


def merged(dirs: list[Path]) -> dict[str, dict[str, int | None]]:
    """The exit codes of the directories `export` wrote, change by change: a later directory's
    outcome over an earlier one's, and an outcome over none."""
    out: dict[str, dict[str, int | None]] = defaultdict(dict)
    for d in dirs:
        for rel, keys in codes(d).items():
            for name, code in keys.items():
                if code is not None or name not in out[rel]:
                    out[rel][name] = code
    return dict(out)


def counts(by_file: dict[str, Counter]) -> dict:
    """Outcomes as a baseline keeps them: the changes, and each outcome's count."""
    whole = sum(by_file.values(), Counter())
    return {"mutants": sum(whole.values()), **{k: whole[k] for k in COUNTED}}


def diffs(dirs: list[Path]) -> dict[str, list[str]]:
    """Each survivor's diff lines, by name, from the directories' survivors.txt (a later one's over
    an earlier one's: the same code, so the same change)."""
    out: dict[str, list[str]] = {}
    for d in dirs:
        f = d / "survivors.txt"
        lines: list[str] = []
        for x in f.read_text(encoding="utf-8").splitlines() if f.exists() else []:
            if x.startswith("# "):
                lines = out[x[2:].strip()] = []
            else:
                lines.append(x)
    return out


def function_of(name: str) -> str:
    """The function a change is in, from mutmut's name for it: `appkata_core.urls.x_parse__mutmut_8`
    is `parse`, `appkata_core.db.xǁStoreǁget__mutmut_7` is `Store.get`."""
    key = re.sub(r"__mutmut_\d+$", "", name)
    key = key[key.index("xǁ") :] if "xǁ" in key else key.rsplit(".", 1)[-1]
    return ".".join(key[1:].split("ǁ")[1:]) if key.startswith("xǁ") else key[2:]


def line_of(text: str, function: str, diff: list[str]) -> int | None:
    """The line of a module where a change's first removed line is: where its unchanged and removed
    lines are found in its function, when found there once."""
    tree = ast.parse(text)
    *owner, fn = function.split(".")
    body = tree.body
    for cls in owner:
        body = next((n.body for n in body if isinstance(n, ast.ClassDef) and n.name == cls), [])
    node = next((n for n in body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == fn), None)
    old = [x for x in diff if x[:1] in (" ", "-")]
    first = next((i for i, x in enumerate(old) if x[:1] == "-"), None)
    if node is None or first is None:
        return None
    start = (node.decorator_list[0].lineno if node.decorator_list else node.lineno) - 1
    lines = [x.strip() for x in text.splitlines()[start : node.end_lineno]]
    want = [x[1:].strip() for x in old]  # mutmut prints a method dedented
    at = [i for i in range(len(lines) - len(want) + 1) if lines[i : i + len(want)] == want]
    return start + at[0] + first + 1 if len(at) == 1 else None


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()  # noqa: S603, S607


@functools.lru_cache(maxsize=None)
def blob_at(commit: str, rel: str, repo: str = REPO) -> str:
    """A file's content (its git blob id) at a commit, fetched from `repo` when the checkout lacks it."""
    try:
        return _git("rev-parse", f"{commit}:{rel}")
    except subprocess.CalledProcessError:
        _git("fetch", "--no-tags", "-q", f"https://github.com/{repo}", commit)
        return _git("rev-parse", f"{commit}:{rel}")


@functools.lru_cache(maxsize=None)
def source(blob: str) -> str:
    return _git("cat-file", "-p", blob)


def survivor_entries(dirs: list[Path], content: dict[str, str]) -> list[dict]:
    """The surviving changes, each with its file, function, line and the lines it removed and
    added, in each file's order."""
    by_name = {n: rel for rel, keys in merged(dirs).items() for n, c in keys.items() if outcome(c) == "survived"}
    kept = diffs(dirs)
    out = []
    for name, rel in by_name.items():
        diff = kept.get(name, [])
        fn = function_of(name)
        out.append({
            "name": name, "file": rel, "function": fn,
            "line": line_of(source(content[rel]), fn, diff) if diff and rel in content else None,
            "removed": [x[1:] for x in diff if x[:1] == "-"],
            "added": [x[1:] for x in diff if x[:1] == "+"],
        })  # fmt: skip
    number = lambda e: int(e["name"].rsplit("_", 1)[1])  # noqa: E731
    return sorted(out, key=lambda e: (e["file"], e["line"] or 0, e["function"], number(e)))


def latest(dirs: list[Path]) -> dict[str, dict]:
    """Each job's job.json by its name, a later directory's over an earlier one's: a job run again
    in a later run is that run's (its modules, its dropped tests)."""
    return {(j := json.loads((d / "job.json").read_text()))["name"]: j for d in dirs}


def held(dirs: list[Path]) -> list[str]:
    """The modules the jobs mutated, those a later run's job left out included: a job run again
    for some of its modules keeps the earlier outcomes of the rest."""
    return sorted({m for d in dirs for m in json.loads((d / "job.json").read_text())["modules"].split()})


def baseline(area: str, dirs: list[Path], made: dict, content: dict[str, str]) -> dict:
    """An area's baseline: how it was made, its outcomes, each file's with its content, and the tests
    its runs left out."""
    jobs = list(latest(dirs).values())
    named = held(dirs)
    by_file, _, _ = counted(merged(dirs))
    files = {}
    for rel in named:
        c = by_file.get(rel, Counter())
        files[rel] = {"content": content.get(rel), "mutants": sum(c.values()), **{k: c[k] for k in COUNTED}}
    dropped = {t: as_kept(why) for j in jobs for t, why in sorted(j.get("dropped", {}).items())}
    return {"area": area, "made": made, **counts(by_file), "files": files, "dropped": dict(sorted(dropped.items()))}


def dump_survivors(entries: list[dict]) -> str:
    """An area's survivors as JSON, one a line in each module's order, so a diff of two shows the
    changes that moved."""
    lines = ",\n".join(json.dumps(e, ensure_ascii=False) for e in entries)
    return f"[\n{lines}\n]\n" if entries else "[]\n"


def baseline_path(area: str, records: Path = RECORDS) -> Path:
    return records / f"baseline-{area}.json"


def survivors_path(area: str, records: Path = RECORDS) -> Path:
    return records / "survivors" / f"{area}.json"


def write_baselines(dirs: list[Path], made: dict, commit: str, repo: str, records: Path = RECORDS) -> int:
    """Each area's baseline from the jobs' directories, in baseline-<area>.json, and its survivors, in
    survivors/<area>.json; an area whose job ran nothing isn't written."""
    by_area: dict[str, list[Path]] = defaultdict(list)
    for d in dirs:
        by_area[json.loads((d / "job.json").read_text())["area"]].append(d)
    print(f"{'area':12} {'mutants':>8}" + "".join(f" {k:>9}" for k in COUNTED))
    empty, dropped = [], {}
    (records / "survivors").mkdir(parents=True, exist_ok=True)
    for area, ds in sorted(by_area.items()):
        by_name: dict[str, list[Path]] = defaultdict(list)
        for d in ds:
            by_name[json.loads((d / "job.json").read_text())["name"]].append(d)
        ran = [n for n, jd in by_name.items() if any(c is not None for k in merged(jd).values() for c in k.values())]
        if len(ran) < len(by_name):
            empty += sorted(set(by_name) - set(ran))
            continue
        content = {rel: blob_at(commit, rel, repo) for rel in held(ds)}
        record = baseline(area, ds, made, content)
        baseline_path(area, records).write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        survivors_path(area, records).write_text(dump_survivors(survivor_entries(ds, content)), encoding="utf-8")
        dropped.update(record["dropped"])
        print(f"{area:12} {record['mutants']:8}" + "".join(f" {record[k]:9}" for k in COUNTED))
    if empty:
        print(f"ran nothing, so their areas aren't written: {' '.join(sorted(empty))}")
    print_unfit(dropped)
    return 1 if empty else 0


def downloaded(run_id: str, repo: str) -> list[Path]:
    """A mutate workflow run's job directories, downloaded once."""
    dest = WORK / "ci" / f"{repo.replace('/', '_')}-{run_id}"
    if not dest.exists():
        part = dest.with_name(dest.name + ".part")
        shutil.rmtree(part, ignore_errors=True)
        subprocess.run(["gh", "run", "download", run_id, "-R", repo, "-p", "mutation-*", "-D", str(part)], check=True)  # noqa: S603, S607
        part.rename(dest)
    return sorted(p.parent for p in dest.glob("*/job.json"))


def gather(args) -> int:
    """The runs' artifacts, the earliest first, as each area's baseline. The runs must be of one
    commit, so their outcomes add up. A fork's runs (--repo) are recorded as a fork's, without its
    name; with --same-as, a commit of this repository whose code is each run's own is recorded as
    theirs (runs on branches made only to start them, their workflow file changed)."""
    dirs, ran = [], {}
    for run_id in args.run:
        these = downloaded(run_id, args.repo)
        dirs += these
        view = ["gh", "run", "view", run_id, "-R", args.repo, "--json", "headSha", "-q", ".headSha"]
        head = subprocess.run(view, capture_output=True, text=True, check=True).stdout.strip()  # noqa: S603
        ran.setdefault(head, []).extend(these)
    if len(ran) != 1 and not args.same_as:
        print(f"the runs are of {len(ran)} commits; a baseline is of one: {' '.join(sorted(ran))}")
        return 1
    commit = sorted(ran)[0]
    if args.same_as:  # each run's code, module by module, is the commit's
        same = _git("rev-parse", args.same_as)
        for head, these in sorted(ran.items()):
            named = sorted({m for d in these for m in json.loads((d / "job.json").read_text())["modules"].split()})
            differ = [m for m in named if blob_at(head, m, args.repo) != blob_at(same, m, REPO)]
            if differ:
                print(f"{same} differs from the runs' {head} in {' '.join(differ)}")
                return 1
        commit = same
    where = args.repo if args.repo == REPO else "a fork"
    made = {"repo": where, "runs": [int(r) for r in args.run], "commit": commit, "mutmut": mutmut_pin()}
    return write_baselines(dirs, made, commit, args.repo if not args.same_as else REPO)


def record(args) -> int:
    """Local runs' directories as each area's baseline, of the commit they ran."""
    commit = _git("rev-parse", args.commit)
    made = {"repo": None, "runs": [], "commit": commit, "mutmut": mutmut_pin()}
    return write_baselines([Path(d) for d in args.from_], made, commit, REPO)


# --- what changed since its record --------------------------------------------------------------


def blob(path: Path) -> str:
    """A file's content as git names it (its blob id), without git."""
    import hashlib

    data = path.read_bytes()
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()  # noqa: S324 - git's own name for it


def latest_records(records: Path = RECORDS) -> dict[str, tuple[str, dict]]:
    """Each area's latest record, by its file's name: the settled one (<area>.json) where an area has
    one, else its baseline (baseline-<area>.json)."""
    out = {}
    for path in sorted(records.glob("*.json")):
        area = path.stem.removeprefix("baseline-")
        if area not in out or not path.stem.startswith("baseline-"):
            out[area] = (path.name, json.loads(path.read_text(encoding="utf-8")))
    return out


def stale_modules(root: Path = ROOT, records: Path = RECORDS) -> list[dict]:
    """The modules an area holds whose content isn't what their latest record mutated ("changed
    since"), and those no record covers ("no record"), each with its area and record."""
    recs = latest_records(records)
    out = []
    for rel, (area, _) in modules(root).items():
        name, record = recs.get(area, (None, {}))
        ran = record.get("files", {}).get(rel)
        if ran is None:
            out.append({"area": area, "module": rel, "state": "no record", "record": name})
        elif ran.get("content") != blob(root / rel):
            out.append({"area": area, "module": rel, "state": "changed since", "record": name})
    return out


def stale(_args) -> int:
    """The modules changed since their latest record, and those no record covers."""
    found = stale_modules()
    for f in found:
        if f["state"] == "changed since":
            what = f"changed since {f['record']}'s run"
        else:
            what = "in no record" + (f" ({f['record']} doesn't hold it)" if f["record"] else "")
        print(f"{f['area']:12} {f['module']:44} {what}")
    if found:
        areas_ = sorted({f["area"] for f in found})
        print(f"{len(found)} modules, in {len(areas_)} areas ({' '.join(areas_)}): their counts are out of date")
    else:
        print("every module is as its latest record mutated it")
    return 0


def mutmut_pin() -> str:
    text = (ROOT / "packaging" / "versions.env").read_text(encoding="utf-8")
    m = re.search(r"\bmutmut==([\w.]+)", text)
    return m.group(1) if m else "?"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="scripts/mutate.py", description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="what", required=True)
    r = sub.add_parser("run", help="mutate modules and run the tests on each change (in the container)")
    r.add_argument("modules", nargs="+", help="paths from the root, such as src/appkata_core/windows.py")
    r.add_argument("--workers", type=int, default=2)
    r.add_argument("--only", nargs="*", help="run only these changes (names or globs)")
    r.add_argument("--only-file", help="and those named in this file, one a line")
    r.add_argument("--limit", type=float, default=LIMIT_GB, help="stop past this many GB (PSS)")
    r.add_argument("--worker-limit", type=float, default=WORKER_GB,
                   help="stop a change's worker past this many GB of its own; the change is killed")  # fmt: skip
    r.add_argument("--resume", help="an earlier run's export folder: run only the changes it left unrun")
    r.add_argument("--debug", action="store_true", help="mutmut's pytest runs' commands and output, in its log")
    sub.add_parser("summary", help="the last run's outcomes and survivors")
    c = sub.add_parser("check", help="one change against one test file")
    c.add_argument("change")
    c.add_argument("test")
    pl = sub.add_parser("plan", help="the baseline's jobs, as JSON")
    pl.add_argument("--areas", nargs="*", default=["*"], help="area globs (scripts/areas.py)")
    pl.add_argument("--size", type=int, default=1000, help="code lines per job")
    pl.add_argument("--jobs", nargs="*", help="only these jobs, by name")
    pl.add_argument("--modules", nargs="*", help="only these modules (a trial)")
    e = sub.add_parser("export", help="the last run's outcomes, kept in a directory")
    e.add_argument("dir")
    e.add_argument("--name", required=True)
    e.add_argument("--area", required=True)
    e.add_argument("--modules", required=True)
    g = sub.add_parser("gather", help="a mutate workflow run's artifacts, as each area's baseline")
    g.add_argument("run", nargs="+", help="the runs' ids, the earliest first")
    g.add_argument("--repo", default=REPO, help="the repository the runs are in (a fork's, say)")
    g.add_argument("--same-as", help="record this commit, whose code is the runs' own, as theirs")
    k = sub.add_parser("record", help="directories export wrote, as each area's baseline")
    k.add_argument("--from", dest="from_", nargs="+", required=True)
    k.add_argument("--commit", default="HEAD", help="the commit the runs ran")
    sub.add_parser("stale", help="the modules changed since their latest record, and those none covers")
    args = p.parse_args(argv)
    commands = {"run": run, "summary": summary, "check": check, "plan": plan, "export": export,
                "gather": gather, "record": record, "stale": stale}  # fmt: skip
    return commands[args.what](args)


if __name__ == "__main__":
    sys.exit(main())
