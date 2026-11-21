"""scripts/mutate.py's helpers inside a mutation run (docs/testing.md, "Mutation testing"), where
mutmut is installed: in tier 1's container, from the copy mutmut runs in.

As a pytest plugin (`-p scripts.mutate_plugin`, loaded into each of mutmut's test sessions), a
script runs under the module name mutmut gives its changes, whatever name a test imports it by;
and a change's worker takes the name `mutmut: <change>`, which mutmut's forkserver mode doesn't
give it, so scripts/mutate.py's watcher finds each change's worker and its memory by its name.

As a script (`python scripts/mutate_plugin.py`, run from the copy), the changes' diffs as
`mutmut show` prints them, many in one process: reads {"generate": bool, "names": {change: path}}
on stdin and prints {change: diff} as JSON on its last line. With "generate", it first makes the
copy's mutants (mutmut's own generation, no test run), so a run made elsewhere, on the same code
and the same mutmut, reads as that run: mutmut names the changes in the order it makes them.

scripts/mutate.py leaves this file out of what it mutates: it runs inside mutmut's own sessions."""

import json
import os
import sys


SCRIPTS = os.path.dirname(os.path.abspath(__file__))  # the copy's scripts/, which mutmut mutates


def canonical(path):
    """The name mutmut gives a script's changes' module (scripts/sandbox/x.py: scripts.sandbox.x),
    for a file in the copy's scripts/, or None."""
    rel = os.path.relpath(os.path.abspath(path), SCRIPTS)
    if rel.startswith("..") or not rel.endswith(".py"):
        return None
    return "scripts." + rel.removesuffix(".py").replace(os.sep, ".")


def _named_as_mutmut_names_it():
    """Each script runs under the name mutmut gives its changes, whatever name a test imports it by.

    A test imports a script by its file's name (`sys.path.insert(0, "scripts"); import areas`) or by
    one of its own (`spec_from_file_location("appkata_areas", ...)`), and a function's module is the
    name its file ran under. mutmut's trampoline runs a change only in the module it names
    (`scripts.areas`), and counts a test's calls by that name, so a script imported by any other
    name had no test and no change run. The module keeps the name it was imported by; its
    functions take mutmut's, as its code runs under it."""
    from importlib.machinery import SourceFileLoader

    exec_module = SourceFileLoader.exec_module
    if getattr(exec_module, "_appkata_named", False):
        return

    def named(self, module):
        name = canonical(self.path)
        if name is None or name == module.__name__:
            return exec_module(self, module)
        imported = module.__name__
        code = self.get_code(imported)  # as exec_module does, which checks the name it runs under
        module.__name__ = name
        sys.modules.setdefault(name, module)
        try:
            exec(code, module.__dict__)  # noqa: S102 - the file the import asked for
        finally:
            module.__name__ = imported

    named._appkata_named = True
    named.original = exec_module
    SourceFileLoader.exec_module = named


def pytest_configure(config):
    _named_as_mutmut_names_it()
    name = os.environ.get("MUTANT_UNDER_TEST", "")
    if "__mutmut_" in name:  # not the stats ("stats"), the forced failure ("fail") or the clean run
        from mutmut.utils.safe_setproctitle import safe_setproctitle

        safe_setproctitle(f"mutmut: {name}")


def diffs(asked):
    """{change: diff} of each change asked for, "" for one neither mutmut nor own_diff finds. With
    "sources" ({path: text}), those files are written into the copy first: a module as a run
    mutated it, changed since."""
    from pathlib import Path

    from mutmut.__main__ import copy_also_copy_files, copy_src_dir, create_mutants, setup_source_paths
    from mutmut.mutation.diff_apply import get_diff_for_mutant

    for rel, text in (asked.get("sources") or {}).items():
        Path(rel).write_text(text, encoding="utf-8")
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
        except Exception:  # noqa: BLE001 - a change mutmut doesn't find has no diff of its own
            out[name] = ""
        out[name] = out[name] or own_diff(name, os.path.join("mutants", path))
    return out


def own_diff(name, mutated):
    """A change's diff read from mutmut's mutated file directly: its function's original copy
    (`<key>__mutmut_orig`) against the change's (`<key>__mutmut_<n>`), each under the function's
    own name. mutmut finds a function by the first "__mutmut_" in a change's name, so one whose own
    name holds it (`_mutmut_pids`) had no diff; this splits at the last. "" when either is missing."""
    import ast
    import difflib
    import textwrap

    fn = name.rpartition(".")[2]
    key = fn.rpartition("__mutmut_")[0]
    try:
        with open(mutated, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return ""
    funcs = {n.name: n for n in ast.walk(ast.parse(text)) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    orig, changed = funcs.get(f"{key}__mutmut_orig"), funcs.get(fn)
    if orig is None or changed is None:
        return ""
    plain = key.rpartition("ǁ")[2] if "ǁ" in key else key.removeprefix("x_")
    lines = text.splitlines()

    def body(node):
        code = textwrap.dedent("\n".join(lines[node.lineno - 1 : node.end_lineno]))
        return code.replace(f"def {node.name}(", f"def {plain}(", 1).splitlines()

    return "\n".join(difflib.unified_diff(body(orig), body(changed), mutated, mutated, lineterm=""))


if __name__ == "__main__":
    sys.stdout.write("\n" + json.dumps(diffs(json.load(sys.stdin))) + "\n")
