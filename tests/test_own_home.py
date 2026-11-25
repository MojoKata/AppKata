"""Every test's own home (tests/conftest.py, issue #718): what a test writes to "~" lands in its
tmp_path, and a run fails when AppKata's files in the real home changed while it ran.

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


def test_a_homes_changes_are_named_and_only_those_of_appkatas_own_files(tmp_path):
    home = tmp_path / "someone"
    menu, data = home / ".local" / "share" / "applications", home / ".local" / "share" / "appkata"
    for d in ("bin/apps/demo", ".local/share/applications", ".config"):
        (home / d).mkdir(parents=True)
    (home / "bin" / "tool").write_text("a tool\n")
    (home / "bin" / "apps" / "demo" / "run").write_text("#!/bin/sh\n")
    (menu / "other.desktop").write_text("[Desktop Entry]\nName=Another program\n")
    (menu / "appkata-links.desktop").write_text("[Desktop Entry]\n")
    links = os.name != "nt"       # a command link is a symbolic link, which Windows keeps for administrators
    if links:
        os.symlink(str(home / "bin" / "apps" / "demo" / "run"), home / "bin" / "demo")
    before = conftest.home_state(str(home))
    assert conftest.home_changes(before, conftest.home_state(str(home))) == []

    # another program's files: elsewhere in the home, and in the two folders AppKata shares with them
    (home / ".config" / "other.conf").write_text("not AppKata's\n")
    (home / "notes.txt").write_text("nor this\n")
    (home / "bin" / "tool").write_text("a tool, changed\n")
    (home / "bin" / "my-own-tool").write_text("installed meanwhile\n")
    (menu / "other.desktop").unlink()
    (menu / "mimeinfo.cache").write_text("[MIME Cache]\n")
    (menu / "appkatalog.desktop").write_text("[Desktop Entry]\nName=Only named alike\n")
    if links:
        os.symlink("/usr/bin/true", home / "bin" / "true")                      # a link, and not into an apps folder
    assert conftest.home_changes(before, conftest.home_state(str(home))) == []

    # AppKata's own: its data, an app's files, the menu entries it names, the command links to its apps
    (data / "trusts").mkdir(parents=True)                                       # the data folder wasn't there
    (menu / "appkata-demo.desktop").write_text("[Desktop Entry]\n")
    (menu / "appkata.desktop").write_text("[Desktop Entry]\n")
    (menu / "appkata-links.desktop").write_text("[Desktop Entry]\nName=Links\n")
    (home / "bin" / "apps" / "demo" / "run").unlink()
    new = [data, data / "trusts", menu / "appkata-demo.desktop", menu / "appkata.desktop"]
    gone = [home / "bin" / "apps" / "demo" / "run"]
    if links:
        (home / "bin" / "demo").unlink()
        os.symlink("apps/fresh/run", home / "bin" / "fresh")                    # relative, to this home's apps
        os.symlink(str(tmp_path / "a-test" / "bin" / "apps" / "leaked" / "run"), home / "bin" / "leaked")   # to a test's own
        new += [home / "bin" / "fresh", home / "bin" / "leaked"]
        gone += [home / "bin" / "demo"]
    changes = conftest.home_changes(before, conftest.home_state(str(home)))
    # a folder that gained or lost an entry counts as changed too, by its time; the test holds what is certain
    assert sorted(c for c in changes if not c.startswith("changed: ")) == sorted(
        [f"new: {p}" for p in new] + [f"gone: {p}" for p in gone])
    assert f"changed: {menu / 'appkata-links.desktop'}" in changes
    assert not [c for c in changes if c.endswith(("tool", "true", "other.desktop", "mimeinfo.cache", "appkatalog.desktop"))]
    assert not [c for c in changes if c.split(": ")[1] in (str(home / "bin"), str(menu))]     # nor the shared folders themselves


INNER = '''import os
import conftest


def test_writes_to_its_own_home():
    os.makedirs(os.path.join(os.environ["APPKATA_DATA"], "trusts", "someone"))


def test_another_program_writes_in_the_real_home():        # as another process would meanwhile: the check can't tell who wrote
    for folder, name in (("bin", "my-own-tool"), (os.path.join(".local", "share", "applications"), "other.desktop")):
        os.makedirs(os.path.join(conftest.REAL_HOME, folder), exist_ok=True)
        with open(os.path.join(conftest.REAL_HOME, folder, name), "w") as f:
            f.write("not AppKata's\\n")


def test_reaches_the_real_home():
    os.makedirs(os.path.join(conftest.REAL_HOME, ".local", "share", "appkata", "trusts", "leaked"))
    os.makedirs(os.path.join(conftest.REAL_HOME, "bin", "apps", "leaked"))
'''


def _run(tmp_path, *tests):
    """pytest on INNER's tests (all of them when none is named) with tests/conftest.py as its plugin, by a
    user whose home is tmp_path/real."""
    real = tmp_path / "real"
    real.mkdir(exist_ok=True)
    (tmp_path / "test_inner.py").write_text(INNER)
    env = {k: v for k, v in os.environ.items() if not k.startswith("APPKATA_")}    # no list, part or measuring of the outer run's
    env.update(HOME=str(real), USERPROFILE=str(real), PYTHONDONTWRITEBYTECODE="1",
               PYTHONPATH=os.pathsep.join([os.path.join(ROOT, "tests"), os.path.join(ROOT, "src")]))
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p", "conftest", "--basetemp",
                        str(tmp_path / "inner-tmp"), *([f"test_inner.py::{t}" for t in tests] or ["test_inner.py"])],
                       cwd=tmp_path, env=env, capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr, real


HEADING = " failed: AppKata's files in the real home changed during the run"       # " failed" is what the tiers read


def test_a_run_that_changed_the_real_home_fails_and_one_that_kept_to_its_own_passes(tmp_path):
    rc, out, real = _run(tmp_path, "test_writes_to_its_own_home")
    assert rc == 0 and "1 passed" in out, out
    assert not (real / ".local").exists()                        # its trusts went to the test's tmp_path
    rc, out, real = _run(tmp_path)
    leaked = [real / ".local" / "share" / "appkata" / "trusts" / "leaked", real / "bin" / "apps" / "leaked"]
    assert all(p.is_dir() for p in leaked)
    assert rc == 1 and "3 passed" in out, out                    # no test failed: the run did
    assert HEADING in out and "another process" in out, out      # and says who else it may have been
    for p in leaked:
        assert f"new: {p}" in out, out
    assert "my-own-tool" not in out and "other.desktop" not in out, out


def test_another_programs_files_appearing_in_the_shared_folders_dont_fail_the_run(tmp_path):
    # P2-1 of pull request #717's review: the check counted ~/bin and the menu folder whole, so a tool
    # installed there while the tests ran failed a run in which every test passed, and named no cause.
    rc, out, real = _run(tmp_path, "test_writes_to_its_own_home", "test_another_program_writes_in_the_real_home")
    assert (real / "bin" / "my-own-tool").is_file() and (real / ".local" / "share" / "applications" / "other.desktop").is_file()
    assert rc == 0 and "2 passed" in out and HEADING not in out, out
