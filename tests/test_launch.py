"""Launching an installed app (R14.2): its output is kept and a failed launch is reported."""

import json
import os
import subprocess

import pytest

from appkata_core import applog, install
from appkata_core.db import DB, now

URL = "https://github.com/example/demo"


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("APPKATA_LOG_DIR", str(tmp_path / "logs"))
    return DB(str(tmp_path / "appkata.db"))


def _installed(db, tmp_path, script: str) -> str:
    exe = tmp_path / "apps" / "demo" / "run"
    exe.parent.mkdir(parents=True)
    exe.write_text("#!/bin/sh\n" + script)
    exe.chmod(0o755)
    db.x("INSERT INTO installs(url, name, version, kind, record, installed_at) VALUES(?,?,?,?,?,?)",
         (URL, "Demo App", "1.0", "appimage", json.dumps({"exec": str(exe)}), now()))
    return str(exe)


@pytest.mark.skipif(install.OS == "windows", reason="portable launch on Linux/macOS")
def test_a_failed_launch_is_reported_with_its_last_lines(db, tmp_path):
    # Regression: the launcher ran with stdout and stderr on /dev/null, so a sandboxed launch that
    # failed — bwrap refused, "didn't unpack to a folder", a CLI tool's "can't see" note — showed
    # nothing at all; the user clicked Open and nothing happened.
    _installed(db, tmp_path, 'echo "starting"; echo "bwrap: No permissions to create a new namespace" >&2; exit 3\n')
    seen = []
    t = install.launch(db, URL, on_failed=lambda code, tail: seen.append((code, tail)))
    t.join(timeout=30)
    assert len(seen) == 1 and seen[0][0] == 3
    assert seen[0][1][-2:] == ["starting", "bwrap: No permissions to create a new namespace"]
    log = applog.app_log_path("demo-app")                        # keyed by the install's id (review 2, F14)
    assert log.startswith(os.environ["APPKATA_LOG_DIR"]) and log.endswith("apps/demo-app.log")
    assert "No permissions" in open(log).read()


@pytest.mark.skipif(install.OS == "windows", reason="portable launch on Linux/macOS")
def test_a_launch_that_runs_is_not_reported(db, tmp_path):
    _installed(db, tmp_path, 'echo "hello from the app"; exit 0\n')
    seen = []
    t = install.launch(db, URL, on_failed=lambda code, tail: seen.append(code))
    t.join(timeout=30)
    assert seen == []
    assert "hello from the app" in open(applog.app_log_path("demo-app")).read()      # kept, not discarded


def test_launching_something_not_installed_still_raises(db):
    with pytest.raises(install.InstallError):
        install.launch(db, URL)


def _sandboxed(db, tmp_path, script: str) -> None:
    exe = _installed(db, tmp_path, script)
    db.x("UPDATE installs SET record=? WHERE url=?", (json.dumps({"exec": exe, "launcher": exe}), URL))


@pytest.mark.skipif(install.OS == "windows", reason="portable launch on Linux/macOS")
def test_launches_append_to_the_app_log_and_rotate_it(db, tmp_path, monkeypatch):
    # Regression (round two, R4): the log was opened fresh per launch, so a second instance of the
    # app truncated the first one's live output. Now each launch appends under a dated header, and
    # the file is replaced by <id>-prev.log past the limit, like AppKata's own log.
    _installed(db, tmp_path, 'echo "run $1"; exit 0\n')
    install.launch(db, URL).join(timeout=30)
    install.launch(db, URL).join(timeout=30)
    log = applog.app_log_path("demo-app")
    text = open(log).read()
    assert text.count("AppKata: starting Demo App") == 2 and text.count("run") == 2
    monkeypatch.setattr(applog, "APP_LOG_LIMIT", 10)
    install.launch(db, URL).join(timeout=30)
    assert open(log).read().count("AppKata: starting") == 1
    assert open(log[:-4] + "-prev.log").read() == text


@pytest.mark.skipif(install.OS == "windows", reason="portable launch on Linux/macOS")
@pytest.mark.parametrize("script,reported", [
    # the launcher refused before the program ran (no "running" line): reported however long it took
    ('sleep 1; echo "AppKata: /x.AppImage didn'"'"'t unpack to a folder; not running it." >&2; exit 1\n', True),
    # the program died right after the launcher started it, long after the launch began: reported
    ('sleep 1; echo "AppKata: running /x/AppRun ($(date +%s))" >&2; echo "Segmentation fault" >&2; exit 139\n', True),
    # the program ran for a while, then crashed: in the log, not a launch failure (the mark has whole
    # seconds, so the watcher allows a second beyond the grace; 2 s is past that)
    ('echo "AppKata: running /x/AppRun ($(date +%s))" >&2; sleep 2; exit 1\n', False)],
    ids=["refused", "died-at-start", "crashed-later"])     # the skip lists name each; pytest's own ids move
def test_a_launchers_refusal_is_reported_after_any_delay_but_a_crash_later_is_not(db, tmp_path, script, reported):
    # Regression (round two, R4): the grace period ran from the moment the launcher started, so a
    # first launch that unpacked a large AppImage for longer than that, then failed, was log-only.
    _sandboxed(db, tmp_path, script)
    seen = []
    install.launch(db, URL, on_failed=lambda code, tail: seen.append(code), grace=0.3).join(timeout=30)
    assert bool(seen) is reported, seen


@pytest.mark.skipif(install.OS == "windows", reason="portable launch on Linux/macOS")
def test_a_program_run_directly_is_only_reported_within_the_grace(db, tmp_path):
    _installed(db, tmp_path, 'sleep 1; exit 2\n')                # unsandboxed: no launcher, no marker
    seen = []
    install.launch(db, URL, on_failed=lambda code, tail: seen.append(code), grace=0.3).join(timeout=30)
    assert seen == []


def test_logs_kept_by_name_move_to_their_installs_id_unless_two_shared_one(tmp_path, monkeypatch):
    # Review 2, F14: logs were keyed by the app's name, so two "Notes" from two Sources wrote one log.
    # Keyed by the install's id now; an older AppKata's logs move to it at start, but a log two
    # installs with one name shared stays as it is, since its lines are both apps'.
    monkeypatch.setenv("APPKATA_LOG_DIR", str(tmp_path / "logs"))
    apps = tmp_path / "logs" / "apps"
    apps.mkdir(parents=True)
    for name, text in (("Demo-App.log", "demo"), ("Demo-App-prev.log", "older demo"), ("Notes.log", "both notes"),
                       ("Taken.log", "old taken")):
        (apps / name).write_text(text)
    # where file names ignore case (Windows, macOS), Taken.log and taken.log are one file: start without it
    folded = (apps / "taken.log").exists()
    if folded:
        (apps / "Taken.log").unlink()
    (apps / "taken.log").write_text("new taken")                         # the id's own log stands
    applog.adopt_name_logs([("demo-app", "Demo App"), ("notes", "Notes"), ("notes-2", "Notes"), ("taken", "Taken")])
    assert (apps / "demo-app.log").read_text() == "demo" and (apps / "demo-app-prev.log").read_text() == "older demo"
    assert (apps / "Notes.log").read_text() == "both notes"
    assert (apps / "taken.log").read_text() == "new taken"
    if not folded:                                                        # names that differ only in case
        assert not (apps / "Demo-App.log").exists() and not (apps / "notes.log").exists()
        assert (apps / "Taken.log").read_text() == "old taken"


# ---------------------------------------------------------------- Open for a system package (CR1.3-21)

def _package(db, package, manager="apt"):
    db.x("INSERT INTO installs(url, name, version, kind, record, installed_at) VALUES(?,?,?,?,?,?)",
         (URL, "Demo App", "1.0", "deb", json.dumps({"package": package, "manager": manager}), now()))


_SHOWN = "[Desktop Entry]\nType=Application\nName=X\nExec=x %U\n"
_NVIM = "[Desktop Entry]\nType=Application\nName=Neovim\nTryExec=nvim\nExec=nvim %F\nTerminal=true\n"


def _a_system(tmp_path, monkeypatch, own, others, program="prog"):
    """A system whose package installed `program` and the .desktop files `own`, {name: text}, and
    whose applications folder also has `others`, other packages' entries. Returns what its manager
    lists of the package's files."""
    apps, bin_ = tmp_path / "usr" / "share" / "applications", tmp_path / "usr" / "bin"
    apps.mkdir(parents=True)
    bin_.mkdir(parents=True)
    for name in ("nvim", "prog", "other"):
        (bin_ / name).write_text("#!/bin/sh\n")
        (bin_ / name).chmod(0o755)
    listed = [str(bin_ / program), str(tmp_path / "usr" / "share" / "doc")]
    for name, text in {**own, **others}.items():
        (apps / name).write_text(text)
        listed += [str(apps / name)] if name in own else []
    monkeypatch.setattr(install, "_APPLICATIONS", (str(apps), str(tmp_path / "nowhere")))
    return "\n".join(listed) + "\n"


# packages whose program isn't named after them, as their managers list them: the package, its
# manager, its own .desktop files, other packages' entries, its program, and the entry Open starts
_PACKAGES = {
    "libreoffice-writer": ("apt", {"libreoffice-writer.desktop": _SHOWN}, {}, "prog", "libreoffice-writer.desktop"),
    "kde-spectacle": ("dnf", {"org.kde.spectacle.desktop": _SHOWN,
                              "org.kde.spectacle.service.desktop": _SHOWN.replace("Type=Application", "Type=Service")},
                      {}, "prog", "org.kde.spectacle.desktop"),
    # Ubuntu 24.04: neovim installs /usr/bin/nvim, and its entry is neovim-runtime's
    "neovim": ("apt", {}, {"nvim.desktop": _NVIM, "a-vim.desktop": _SHOWN.replace("Exec=x", "Exec=other")}, "nvim", "nvim.desktop"),
    "demo-suite": ("apt", {"demo-helper.desktop": _SHOWN + "NoDisplay=true\n", "zz-other.desktop": _SHOWN,
                           "demo-suite.desktop": _SHOWN, "aa-hidden.desktop": _SHOWN + "Hidden=true\n"},
                   {"nvim.desktop": _NVIM}, "nvim", "demo-suite.desktop"),
}


@pytest.mark.skipif(install.OS == "windows", reason="system packages are Linux's (R16)")
@pytest.mark.parametrize("launcher", ["gio", "gtk-launch"])
@pytest.mark.parametrize("package", list(_PACKAGES))
def test_open_starts_a_packages_own_menu_entry_whatever_its_program_is_called(db, tmp_path, monkeypatch, package, launcher):
    # CR1.3-21: Open looked for a program named after the package, so it failed for every package
    # whose program is named otherwise (libreoffice-writer's is lowriter), and would have started
    # another package's program that had the name. It starts the package's app-menu entry now, as
    # the desktop does: its own, the one named after it first and never one the menu doesn't show;
    # else the entry of a program it installed.
    manager, own, others, program, started = _PACKAGES[package]
    listing = _a_system(tmp_path, monkeypatch, own, others, program)
    asked, ran = [], []

    def run(cmd, **kw):
        asked.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, listing, "")
    monkeypatch.setattr(install.subprocess, "run", run)
    monkeypatch.setattr(install.subprocess, "Popen", lambda cmd, **kw: ran.append(cmd))
    monkeypatch.setattr(install.shutil, "which", lambda name: str(tmp_path / "usr" / "bin" / name) if name in (
        "nvim", "prog", "other") else f"/usr/bin/{name}" if name in ("dpkg-query", "rpm", launcher, package) else None)
    _package(db, package, manager)
    install.launch(db, URL)
    assert asked == [["dpkg-query", "-L", package] if manager == "apt" else ["rpm", "-ql", package]]
    entry = str(tmp_path / "usr" / "share" / "applications" / started)
    assert ran == [["gio", "launch", entry] if launcher == "gio" else ["gtk-launch", started]]


@pytest.mark.skipif(install.OS == "windows", reason="system packages are Linux's (R16)")
@pytest.mark.parametrize("own,others", [({}, {}), ({"ssh.desktop": _SHOWN + "NoDisplay=true\n"}, {}), ({}, {"nvim.desktop": _NVIM})],
                         ids=["none", "one the menu doesn't show", "another program's"])
def test_a_package_with_no_menu_entry_is_not_opened_by_a_program_of_its_name(db, tmp_path, monkeypatch, own, others):
    listing = _a_system(tmp_path, monkeypatch, own, others)
    ran = []
    monkeypatch.setattr(install.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, listing, ""))
    monkeypatch.setattr(install.subprocess, "Popen", lambda cmd, **kw: ran.append(cmd))
    monkeypatch.setattr(install.shutil, "which", lambda name: str(tmp_path / "usr" / "bin" / name) if name == "nvim"
                        else f"/usr/bin/{name}")                     # a program called openssh-clients too
    _package(db, "openssh-clients")
    with pytest.raises(install.InstallError, match="Demo App has no app-menu entry to open it with"):
        install.launch(db, URL)
    assert ran == []
