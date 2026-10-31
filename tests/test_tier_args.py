"""The arguments a tier hands on to pytest arrive as they were given (the walk thru of 2026-10-30,
item 6; docs/reviews/followups-vm-pytest-args.md).

How it slipped past: test-sandbox.sh launcher-vm passed its arguments as "$*", one string, through
the cloud-config and the VM's environment into vm-launcher.sh's `bash -lc "..."`, which split them
again on spaces: `-k 'a or b'` reached pytest as `-k a or b`. Every run used one-word arguments.
The class: arguments that cross a layer as one string (an environment variable, a config file, a
shell command line) and are split again on the other side. This test sends awkward arguments
through the same steps the scripts take, run as they run them, and checks the tiers that pass "$@"
straight on keep doing so."""

import os
import re
import shutil
import subprocess

import pytest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
AWKWARD = ["-k", "a or b", "-k", "not c and d", "it's", 'say "hi"', "$HOME", "*", "x  y", "back\\slash", "-x"]


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


def _line(text, start):
    return next(line.strip() for line in text.splitlines() if line.strip().startswith(start))


@pytest.mark.skipif(not (shutil.which("sh") and shutil.which("bash")), reason="runs the scripts' POSIX shell steps")
def test_launcher_vm_hands_pytest_each_argument_whole():
    host = _line(_read("scripts/test-sandbox.sh"), "ARGS=")
    vm = _line(_read("scripts/sandbox/vm-launcher.sh"), "PYTEST_ARGS=")
    # the host's encoding, as test-sandbox.sh makes it from its arguments
    encoded = subprocess.run(["sh", "-c", f'{host}\nprintf %s "$ARGS"', "sh", *AWKWARD],
                             capture_output=True, text=True, check=True).stdout
    assert re.fullmatch(r"[A-Za-z0-9+/=]*", encoded)          # safe in the cloud-config and the environment
    # the VM's decoding, then its `bash -lc "... $PYTEST_ARGS ..."`, with printf standing in for pytest
    out = subprocess.run(["bash", "-c", f'{vm}\nbash -c "printf \'<%s>\\n\' $PYTEST_ARGS"'],
                         env={**os.environ, "PYTEST_ARGS_B64": encoded, "HOME": "/nowhere"},
                         capture_output=True, text=True, check=True).stdout
    assert out.splitlines() == [f"<{a}>" for a in AWKWARD]


def test_the_cloud_config_and_the_vm_carry_the_encoded_arguments():
    sandbox, launcher = _read("scripts/test-sandbox.sh"), _read("scripts/sandbox/vm-launcher.sh")
    assert '-e PYTEST_ARGS_B64="$ARGS"' in sandbox and '\\"PYTEST_ARGS_B64=$PYTEST_ARGS_B64\\"' in sandbox
    assert "PYTEST_ARGS=" not in sandbox.replace("PYTEST_ARGS_B64", "")
    assert re.search(r"test_booted\.py \$PYTEST_ARGS ", launcher)


def test_the_tiers_that_pass_arguments_straight_on_keep_them_whole():
    # tier 1 and the launcher containers hand "$@" through sh -c's own arguments, never through a string
    assert re.search(r"""tests/ "\$@"' sh "\$@"$""", _read("scripts/test-tier1.sh"), re.M)
    sandbox = _read("scripts/test-sandbox.sh")
    assert 'exec su kata -c "$0" -- sh "$@"' in sandbox
    assert re.search(r"""test_platform_matrix\.py "\$@"' "\$@"$""", sandbox, re.M)
