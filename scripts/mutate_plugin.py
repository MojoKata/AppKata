"""scripts/mutate.py's helpers inside a mutation run (docs/testing.md, "Mutation testing"), where
mutmut is installed: in tier 1's container, from the copy mutmut runs in.

As a pytest plugin (`-p scripts.mutate_plugin`, loaded into each of mutmut's test sessions), a
change's worker takes the name `mutmut: <change>`, which mutmut's forkserver mode doesn't give
it, so scripts/mutate.py's watcher finds each change's worker and its memory by its name.

As a script (`python scripts/mutate_plugin.py`, run from the copy), the changes' diffs as
`mutmut show` prints them, many in one process: reads {"generate": bool, "names": {change: path}}
on stdin and prints {change: diff} as JSON on its last line. With "generate", it first makes the
copy's mutants (mutmut's own generation, no test run), so a run made elsewhere, on the same code
and the same mutmut, reads as that run: mutmut names the changes in the order it makes them.

scripts/mutate.py leaves this file out of what it mutates: it runs inside mutmut's own sessions."""

import json
import os
import sys


def pytest_configure(config):
    name = os.environ.get("MUTANT_UNDER_TEST", "")
    if "__mutmut_" in name:  # not the stats ("stats"), the forced failure ("fail") or the clean run
        from mutmut.utils.safe_setproctitle import safe_setproctitle

        safe_setproctitle(f"mutmut: {name}")


def diffs(asked):
    """{change: diff} of each change asked for, "" for one mutmut doesn't find."""
    from pathlib import Path

    from mutmut.__main__ import copy_also_copy_files, copy_src_dir, create_mutants, setup_source_paths
    from mutmut.mutation.diff_apply import get_diff_for_mutant

    if asked.get("generate"):
        os.makedirs("mutants", exist_ok=True)
        copy_src_dir()
        copy_also_copy_files()
        setup_source_paths()
        create_mutants(os.cpu_count() or 4)
    out = {}
    for name, path in asked["names"].items():
        try:
            out[name] = get_diff_for_mutant(name, path=Path(path))
        except Exception:  # noqa: BLE001 - a change mutmut doesn't find has no diff
            out[name] = ""
    return out


if __name__ == "__main__":
    sys.stdout.write("\n" + json.dumps(diffs(json.load(sys.stdin))) + "\n")
