"""Every test's own home (tests/conftest.py, issue #718): what a test writes to "~" lands in its
tmp_path, and a run fails when the real home's AppKata folders changed while it ran.

How it slipped past: tier 1 and CI run in containers, whose home is thrown away with them, so where
a test wrote never showed. On a developer's machine the same tests ran with that person's HOME:
tests/test_demo_remake.py built the demo's Trusts into ~/.local/share/appkata/trusts on every run
(54 clones by 2026-11-25), and a launcher, its command link and its menu entry appeared in ~/bin
and ~/.local/share/applications. The class: a test that reaches what the machine's user owns
because nothing gave it a place of its own. The fixture gives every test one; the check at the
end of a run is for what the fixture can't hold: a fixture of a wider scope, a thread a test left
running, a test that set HOME back."""

import os
import subprocess
import sys

import conftest
from appkata_core import platform

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")


def _under(path, folder):
    return os.path.commonpath([os.path.abspath(path), str(folder)]) == str(folder)


def test_what_a_test_writes_to_its_home_lands_in_its_tmp_path(tmp_path):
    places = [platform.data_dir(), platform.apps_dir()]
    if os.name != "nt":       # Windows asks its own variables for a home, not HOME: there AppKata's two are what count
        places += [platform.desktop_dir(), os.path.expanduser("~"), os.path.expanduser("~/bin")]
    for place in places:
        assert _under(place, tmp_path), place                    # before anything is written
    trusts = os.path.join(platform.data_dir(), "trusts", "someone")
    os.makedirs(trusts)
    assert (tmp_path / ".local" / "share" / "appkata" / "trusts" / "someone").is_dir()
    if os.name != "nt":       # and a program the test starts has the same home
        subprocess.run(["sh", "-c", "mkdir -p ~/.local/share/appkata/sandboxes/demo ~/bin/apps/demo"], check=True)
        assert (tmp_path / ".local" / "share" / "appkata" / "sandboxes" / "demo").is_dir()
        assert (tmp_path / "bin" / "apps" / "demo").is_dir()


def test_a_homes_changes_are_named_and_only_those_in_appkatas_folders(tmp_path):
    home = tmp_path / "someone"
    for d in ("bin/apps/demo", ".local/share/applications", ".config"):
        (home / d).mkdir(parents=True)
    (home / "bin" / "tool").write_text("a tool\n")
    (home / "bin" / "apps" / "demo" / "run").write_text("#!/bin/sh\n")
    before = conftest.home_state(str(home))
    assert conftest.home_changes(before, conftest.home_state(str(home))) == []
    (home / ".config" / "other.conf").write_text("not AppKata's\n")
    (home / "notes.txt").write_text("nor this\n")
    assert conftest.home_changes(before, conftest.home_state(str(home))) == []
    (home / ".local" / "share" / "appkata" / "trusts").mkdir(parents=True)                     # the data folder wasn't there
    (home / ".local" / "share" / "applications" / "appkata-demo.desktop").write_text("[Desktop Entry]\n")
    (home / "bin" / "tool").write_text("a tool, changed\n")
    (home / "bin" / "apps" / "demo" / "run").unlink()
    changes = conftest.home_changes(before, conftest.home_state(str(home)))
    data = home / ".local" / "share" / "appkata"
    # a folder that gained or lost an entry counts as changed too, by its time; the test holds what is certain
    assert [c for c in changes if not c.startswith("changed: ")] == [
        f"new: {data}", f"new: {data / 'trusts'}", f"new: {home / '.local' / 'share' / 'applications' / 'appkata-demo.desktop'}",
        f"gone: {home / 'bin' / 'apps' / 'demo' / 'run'}"]
    assert f"changed: {home / 'bin' / 'tool'}" in changes


INNER = '''import os
import conftest


def test_writes_to_its_own_home():
    os.makedirs(os.path.join(os.environ["APPKATA_DATA"], "trusts", "someone"))


def test_reaches_the_real_home():
    os.makedirs(os.path.join(conftest.REAL_HOME, ".local", "share", "appkata", "trusts", "leaked"))
'''


def _run(tmp_path, *args):
    """pytest on INNER with tests/conftest.py as its plugin, by a user whose home is tmp_path/real."""
    real = tmp_path / "real"
    real.mkdir(exist_ok=True)
    (tmp_path / "test_inner.py").write_text(INNER)
    env = {k: v for k, v in os.environ.items() if not k.startswith("APPKATA_")}    # no list, part or measuring of the outer run's
    env.update(HOME=str(real), USERPROFILE=str(real), PYTHONDONTWRITEBYTECODE="1",
               PYTHONPATH=os.pathsep.join([os.path.join(ROOT, "tests"), os.path.join(ROOT, "src")]))
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p", "conftest", "--basetemp",
                        str(tmp_path / "inner-tmp"), "test_inner.py", *args], cwd=tmp_path, env=env, capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr, real


def test_a_run_that_changed_the_real_home_fails_and_one_that_kept_to_its_own_passes(tmp_path):
    rc, out, real = _run(tmp_path, "-k", "own_home")
    assert rc == 0 and "1 passed" in out, out
    assert not (real / ".local").exists()                        # its trusts went to the test's tmp_path
    rc, out, real = _run(tmp_path)
    leaked = real / ".local" / "share" / "appkata" / "trusts" / "leaked"
    assert leaked.is_dir()
    assert rc == 1 and "2 passed" in out, out                    # no test failed: the run did
    assert " failed: the real home's AppKata folders changed during the run" in out     # " failed" is what the tiers read
    assert f"new: {leaked}" in out
