"""scripts/tour-data.sh, the demo data CI's tour runs on (docs/github-workflows.md, "The tour"): kept
when the cache brought data made by this demo_data.py, remade from its own Catalog when demo_data.py
changed, else synced from GitHub, and restored from the snapshot in tests/data/demo when the sync or
its claims fail. Run here on a copy of the script beside a demo_data.py that only records what it was
asked and fails where the case says."""

import os
import shutil
import subprocess

import pytest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
pytestmark = pytest.mark.skipif(not (shutil.which("sh") and shutil.which("sha256sum")),
                                reason="runs scripts/tour-data.sh, a POSIX shell script")

STUB = '''import os, sys
here = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(here, "..", "calls"), "a") as f:
    f.write(sys.argv[1] + "\\n")
if sys.argv[1] in os.environ.get("FAIL", "").split():
    sys.exit(1)
d = sys.argv[2]
if sys.argv[1] in ("build", "restore"):
    os.makedirs(d, exist_ok=True)
    open(os.path.join(d, "appkata.db"), "w").close()
'''


def _run(tmp_path, fail="", data=None):
    """tour-data.sh in a copy of the tree at tmp_path: data is None (no cached data), "same" (made by
    this demo_data.py) or "older" (made by another). Returns the demo_data.py commands it ran and
    what it printed."""
    (tmp_path / "scripts").mkdir()
    shutil.copy(os.path.join(ROOT, "scripts", "tour-data.sh"), tmp_path / "scripts")
    (tmp_path / "scripts" / "demo_data.py").write_text(STUB)
    td = tmp_path / "build" / "tour-data"
    if data:
        td.mkdir(parents=True)
        (td / "appkata.db").write_text("")
        digest = subprocess.run(["sha256sum", str(tmp_path / "scripts" / "demo_data.py")], capture_output=True,
                                text=True).stdout.split()[0]
        (td / "made-by.sha256").write_text((digest if data == "same" else "0" * 64) + "\n")
    env = {**os.environ, "FAIL": fail, "GITHUB_ACTIONS": "true"}
    r = subprocess.run(["sh", str(tmp_path / "scripts" / "tour-data.sh")], capture_output=True, text=True, env=env)
    calls = (tmp_path / "calls").read_text().split() if (tmp_path / "calls").exists() else []
    return r.returncode, calls, r.stdout + r.stderr, (td / "made-by.sha256").read_text() if (td / "made-by.sha256").exists() else ""


@pytest.mark.parametrize("data, fail, calls, says", [
    ("same", "", [], "as it was"),
    ("older", "", ["remake"], "remake"),
    ("older", "remake", ["remake", "build", "sync", "finish", "check"], "synced from GitHub"),
    (None, "", ["build", "sync", "finish", "check"], "synced from GitHub"),
    (None, "sync", ["build", "sync", "restore"], "snapshot"),
    (None, "check", ["build", "sync", "finish", "check", "restore"], "snapshot"),
])
def test_what_the_tour_runs_on(tmp_path, data, fail, calls, says):
    rc, got, out, stamp = _run(tmp_path, fail, data)
    assert rc == 0, out
    assert got == calls
    assert says in out
    digest = subprocess.run(["sha256sum", str(tmp_path / "scripts" / "demo_data.py")], capture_output=True,
                            text=True).stdout.split()[0]
    assert stamp.strip() == digest                               # the next run keeps it as it is
    assert ("::warning title=tour data::" in out) == ("restore" in calls or "remake" in fail)


def test_a_snapshot_that_fails_fails_the_tour(tmp_path):
    rc, got, out, _ = _run(tmp_path, "sync restore")
    assert rc != 0 and got[-1] == "restore"
