"""Every test module loads where the POSIX-only modules don't exist, as on Windows.

How it slipped past: tests/test_coworker.py imported fcntl at its top. Tier 1 runs on Linux, where
fcntl is there; only the Windows VM's run (scripts/test-windows-vm.sh --tests, tier 3) loads the
suite without it, and one module that can't be imported stops the whole suite there ("1 error
during collection"). The class: a POSIX-only module imported when a test module (or what it
imports) loads. Here every test module is imported in a fresh interpreter in which those modules
can't be imported; a test that needs one imports it inside the test, and skips off POSIX."""

import os
import subprocess
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
POSIX_ONLY = ("fcntl", "pwd", "grp", "termios", "tty", "pty", "resource", "syslog", "crypt")

PROBE = r"""
import importlib, importlib.abc, os, sys
BLOCK = set(sys.argv[2].split(","))
class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] in BLOCK:
            raise ModuleNotFoundError(f"No module named {name!r}", name=name)
for m in list(sys.modules):
    if m.split(".")[0] in BLOCK:
        del sys.modules[m]
sys.meta_path.insert(0, Block())
root = sys.argv[1]
sys.path[:0] = [os.path.join(root, "tests"), os.path.join(root, "src")]
for f in sorted(os.listdir(os.path.join(root, "tests"))):
    if f.startswith("test_") and f.endswith(".py") and f != "test_imports_on_windows.py":
        try:
            importlib.import_module(f[:-3])
        except BaseException as e:
            print(f"{f}: {type(e).__name__}: {e}")
"""


def test_every_test_module_loads_without_posix_only_modules():
    if os.name == "nt":
        return                                                    # the real thing: the suite itself loaded
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen", "PYTHONDONTWRITEBYTECODE": "1"}
    res = subprocess.run([sys.executable, "-c", PROBE, ROOT, ",".join(POSIX_ONLY)], capture_output=True, text=True,
                         env=env, timeout=300)
    assert res.returncode == 0, res.stderr
    assert res.stdout == "", "test modules that won't load on Windows:\n" + res.stdout
