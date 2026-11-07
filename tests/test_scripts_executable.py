"""Every script the repository carries (a file under scripts/ or packaging/ that starts with `#!`) is
executable as git records it, so the commands the documents give run as written.

How it slipped past: scripts/test-desktop-vm.sh was committed as 644 in the first commit, and every
run since went through `sh scripts/test-desktop-vm.sh`, so nothing ran it the way docs/testing.md
writes it, `scripts/test-desktop-vm.sh run mint22.3`, which stops at "Permission denied". The same
held for demo_data.py (README), third_party_notices.py (build.md) and three more. This reads the mode
git keeps (what a clone gets), not the work tree's.
"""

import os
import subprocess

import pytest

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
SCRIPT_DIRS = ("scripts/", "packaging/")


def _index():
    """(mode, path) for each file git tracks."""
    try:
        out = subprocess.run(["git", "-C", ROOT, "ls-files", "-s", "-z"], capture_output=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("not a git work tree (the Windows VM's copy of the sources)")
    for entry in out.decode().split("\0"):
        if entry:
            meta, path = entry.split("\t", 1)
            yield meta.split()[0], path


def not_executable(index, root):
    bad = []
    for mode, path in index:
        if not path.startswith(SCRIPT_DIRS) or mode not in ("100644", "100755"):
            continue
        try:
            with open(os.path.join(root, path), "rb") as f:
                shebang = f.read(2) == b"#!"
        except FileNotFoundError:
            continue                                                        # deleted, not yet staged
        if shebang and mode != "100755":
            bad.append(path)
    return bad


def test_every_script_is_executable_in_git():
    bad = not_executable(_index(), ROOT)
    assert not bad, ("scripts git records without the executable bit (git update-index --chmod=+x):\n  "
                     + "\n  ".join(bad))


def test_the_check_sees_a_script_without_the_bit(tmp_path):
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "run.sh").write_text("#!/bin/sh\necho hi\n")
    (tmp_path / "scripts" / "lib.py").write_text("x = 1\n")
    (tmp_path / "scripts" / "ok.sh").write_text("#!/bin/sh\n")
    index = [("100644", "scripts/run.sh"), ("100644", "scripts/lib.py"), ("100755", "scripts/ok.sh")]
    assert not_executable(index, str(tmp_path)) == ["scripts/run.sh"]
