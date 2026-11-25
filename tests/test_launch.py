"""Launching an installed app (R14.2): its output is kept and a failed launch is reported."""

import json
import os
import shutil
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


_SHOWN = "[Desktop Entry]\nType=Application\nName=X\nExec=prog %U\n"
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
    # on the PATH, where an entry's program is looked for as GLib looks (install._found_program)
    monkeypatch.setenv("PATH", f"{bin_}{os.pathsep}{os.environ.get('PATH', '')}")
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
    "neovim": ("apt", {}, {"nvim.desktop": _NVIM, "a-vim.desktop": _SHOWN.replace("Exec=prog", "Exec=other")}, "nvim", "nvim.desktop"),
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


# What a desktop's menu shows of an entry, by the Desktop Entry Specification as GLib applies it (the
# reader the menus of the desktops AppKata supports use), on each desktop of $XDG_CURRENT_DESKTOP
# here: {case: (the entry's lines after its Name, as text or as bytes, the desktops it shows on)}.
# `{bin}` is a folder on the PATH with `prog`, `my prog`, `a$b` and a file that can't run, `notes.txt`;
# `{lib}` one not on it with `tool`; both are in the working directory.
_DESKTOPS = ("GNOME", "ubuntu:GNOME", "X-Cinnamon", "KDE", "")
_ALL, _GNOME = set(_DESKTOPS), {"GNOME", "ubuntu:GNOME"}
_MENU_CASES = {
    "an app": ("Type=Application\nExec=prog %U\n", _ALL),
    "for KDE alone": ("Type=Application\nExec=prog\nOnlyShowIn=KDE;\n", {"KDE"}),
    "for GNOME alone": ("Type=Application\nExec=prog\nOnlyShowIn=GNOME;\n", _GNOME),
    "for Ubuntu's session alone": ("Type=Application\nExec=prog\nOnlyShowIn=ubuntu;\n", {"ubuntu:GNOME"}),
    "not for GNOME": ("Type=Application\nExec=prog\nNotShowIn=GNOME;\n", _ALL - _GNOME),
    "for GNOME and not for it": ("Type=Application\nExec=prog\nOnlyShowIn=GNOME;\nNotShowIn=GNOME;\n", _GNOME),
    "for GNOME, not for Ubuntu's": ("Type=Application\nExec=prog\nOnlyShowIn=GNOME;\nNotShowIn=ubuntu;\n", {"GNOME"}),
    "TryExec on the PATH": ("Type=Application\nExec=prog\nTryExec=prog\n", _ALL),
    "TryExec not installed": ("Type=Application\nExec=prog\nTryExec=no-such-program-here\n", set()),
    "TryExec a path not there": ("Type=Application\nExec=prog\nTryExec={bin}/gone\n", set()),
    "TryExec a file that can't run": ("Type=Application\nExec=prog\nTryExec={bin}/notes.txt\n", set()),
    "its program not installed": ("Type=Application\nExec=no-such-program-here %F\n", set()),
    "its program's path not there": ("Type=Application\nExec={bin}/gone %U\n", set()),
    "its program by its path, quoted": ('Type=Application\nExec="{bin}/my\\sprog" %U\n', _ALL),
    "through env": ("Type=Application\nExec=env FOO=1 no-such-program-here\n", _ALL),
    "no Exec": ("Type=Application\n", _ALL),
    "a link": ("Type=Link\nURL=https://example.org\n", set()),
    "no Type": ("Exec=prog\n", set()),
    "NoDisplay": ("Type=Application\nExec=prog\nNoDisplay=true\n", set()),
    "Hidden": ("Type=Application\nExec=prog\nHidden=true\n", set()),
    # #689's review, P2-2: the file read as GLib reads a key file, and its values as GLib has them
    "NoDisplay=1": ("Type=Application\nExec=prog\nNoDisplay=1\n", set()),
    "Hidden=1": ("Type=Application\nExec=prog\nHidden=1\n", set()),
    "NoDisplay=True, not a boolean": ("Type=Application\nExec=prog\nNoDisplay=True\n", _ALL),
    "NoDisplay=true;, not a boolean": ("Type=Application\nExec=prog\nNoDisplay=true;\n", _ALL),
    "NoDisplay=true, white space after": ("Type=Application\nExec=prog\nNoDisplay=true \t\n", set()),
    "a key's case": ("Type=Application\nExec=prog\nonlyshowin=KDE;\n", _ALL),
    "an empty OnlyShowIn": ("Type=Application\nExec=prog\nOnlyShowIn=\n", set()),
    "OnlyShowIn of no desktop": ("Type=Application\nExec=prog\nOnlyShowIn=;\n", set()),
    "OnlyShowIn with an escape GLib refuses": ("Type=Application\nExec=prog\nOnlyShowIn=K\\xDE;\n", _ALL),
    "an indented line": ("Type=Application\nExec=prog\n  NoDisplay=true\n", set()),
    "an indented line, by a tab": ("Type=Application\nExec=prog\n\tNoDisplay=true\n", set()),
    "white space before =": ("Type=Application\nExec=prog\nNoDisplay \t=true\n", set()),
    "white space around =": ("Type = Application\nExec = prog\n", _ALL),
    "a colon for =": ("Type=Application\nExec:prog\n", set()),
    "a line starting with ;": ("Type=Application\nExec=prog\n; a note\n", set()),
    "a key GLib doesn't allow": ("Type=Application\nExec=prog\nX]Y=1\n", set()),
    "an empty key": ("Type=Application\nExec=prog\n =x\n", set()),
    "Type with white space after": ("Type=Application \nExec=prog\n", set()),
    "an Encoding other than UTF-8": ("Encoding=Legacy-Mixed\nType=Application\nExec=prog\n", set()),
    "Encoding=utf-8": ("Encoding=utf-8\nType=Application\nExec=prog\n", _ALL),
    "a group line with more after it": ("Type=Application\nExec=prog\n[Other] x\n", set()),
    "a group name with a bracket": ("Type=Application\nExec=prog\n[a[b]\n", set()),
    "NoDisplay in another group": ("Type=Application\nExec=prog\n[Other]\nNoDisplay=true\n", _ALL),
    "[Desktop Entry] again, hidden there": ("Type=Application\nExec=prog\n[Other]\n[Desktop Entry]\nNoDisplay=true\n", set()),
    "Exec given twice": ("Type=Application\nExec=no-such-program-here\nExec=prog\n", _ALL),
    "Exec ending in an escape": ("Type=Application\nExec=no-such-program-here\\\n", _ALL),
    "TryExec with an escape GLib refuses": ("Type=Application\nExec=prog\nTryExec=no\\xsuch\n", _ALL),
    "a comment": ("# NoDisplay=true\nType=Application\nExec=prog\n", _ALL),
    # #689's review, P3-1: the file read as bytes, as GLib reads it. A byte that isn't UTF-8 makes no
    # file unreadable, only a string value that holds it, which GLib then has no value for
    "a byte that isn't UTF-8 in a translated Comment": (b"Type=Application\nExec=prog\nComment[fr]=caf\xe9\n", _ALL),
    "a byte that isn't UTF-8 in a comment line": (b"# caf\xe9\nType=Application\nExec=prog\n", _ALL),
    "a byte that isn't UTF-8 in another group": (b"Type=Application\nExec=prog\n[Other]\nX=caf\xe9\n", _ALL),
    "a byte that isn't UTF-8 in a key's and a group's name": (b"Type=Application\nExec=prog\nX-caf\xe9=1\n[caf\xe9]\n", _ALL),
    "a byte that isn't UTF-8 in Exec, no value then": (b"Type=Application\nExec=no-such-program-here caf\xe9\n", _ALL),
    "a byte that isn't UTF-8 in TryExec": (b"Type=Application\nExec=prog\nTryExec=no-such\xe9\n", _ALL),
    "a byte that isn't UTF-8 in OnlyShowIn": (b"Type=Application\nExec=prog\nOnlyShowIn=KDE\xe9;\n", _ALL),
    "a byte that isn't UTF-8 in Type": (b"Type=Application\xe9\nExec=prog\n", set()),
    "a byte that isn't UTF-8 in a key's locale": (b"Type=Application\nExec=prog\nName[d\xe9]=x\n", set()),
    "a vertical tab before a key": ("Type=Application\nExec=prog\n\vNoDisplay=true\n", _ALL),
    "a vertical tab before =": ("Type=Application\nExec=prog\nNoDisplay\v=true\n", _ALL),
    "a vertical tab after a boolean": ("Type=Application\nExec=prog\nNoDisplay=true\v\n", _ALL),
    "a form feed before a key": ("Type=Application\nExec=prog\n\fNoDisplay=true\n", set()),
    "lines ending in a carriage return and a line break": ("Type=Application\r\nExec=prog\r\n", _ALL),
    "two carriage returns before a line break": ("Type=Application\r\r\nExec=prog\n", set()),
    "a carriage return ending the file": ("Exec=prog\nType=Application\r", set()),
    "a space before a key's locale": ("Type=Application\nExec=prog\nName [de]=x\n", set()),
    "a tab before a key's locale": ("Type=Application\nExec=prog\nName\t[de]=x\n", _ALL),
    "a NUL in a value, which ends it": (b"Type=Application\nExec=prog\nNoDisplay=true\x00 and more\n", set()),
    "a NUL in a key": (b"Type=Application\nExec=prog\nNo\x00Display=true\n", set()),
    "a NUL starting a line, a comment": (b"Type=Application\nExec=prog\n\x00NoDisplay=true\n", _ALL),
    # #689's review, P4-B4: GLib steps over a character's continuation bytes with it, so a lone one in a
    # locale after a letter is taken, and one first in it isn't
    "a lone continuation byte in a key's locale, after a letter": (b"Type=Application\nExec=prog\nName[de_DE\xa0.UTF-8]=x\n", _ALL),
    "a lone continuation byte first in a key's locale": (b"Type=Application\nExec=prog\nName[\xa0de]=x\n", set()),
    "continuation bytes after a letter of another script": (b"Type=Application\nExec=prog\nName[\xc3\xa9\x80\xbf]=x\n", _ALL),
    # P4-B5: Exec split as GLib splits it, not as a POSIX shell (shlex) does
    "a carriage return ending the file, after Exec's program": ("Type=Application\nExec=prog\r", set()),
    "a carriage return after Exec's program, escaped": ("Type=Application\nExec=prog\\r --x\n", set()),
    "a vertical tab after Exec's program": ("Type=Application\nExec=prog\v --x\n", set()),
    "a comment before Exec's program": ("Type=Application\nExec=# a note\\nprog %U\n", _ALL),
    "a # ending Exec, which GLib can't read": ("Type=Application\nExec=prog #\n", set()),
    "a # after a tab, not a comment": ("Type=Application\nExec=prog\t#x\n", _ALL),
    "a $ escaped in double quotes": ('Type=Application\nExec="{bin}/a\\\\$b" %U\n', _ALL),
    "a backslash before a letter in double quotes, kept": ('Type=Application\nExec="{bin}/\\\\prog"\n', set()),
    "single quotes": ("Type=Application\nExec='{bin}/my prog' %U\n", _ALL),
    # P4-3: a program by a relative path, found as GLib 2.80 finds it: from the working directory (here
    # the test's folder, where bin/ is), then in each folder of the PATH, and first from the entry's Path
    "its program by a relative path, on the PATH": ("Type=Application\nExec=./prog\n", _ALL),
    "its program by a relative path out and back, on the PATH": ("Type=Application\nExec=../bin/prog\n", _ALL),
    "its program by a path from the working directory": ("Type=Application\nExec=bin/prog\n", _ALL),
    "its program by a relative path found nowhere": ("Type=Application\nExec=./no-such-program-here\n", set()),
    "TryExec by a relative path, on the PATH": ("Type=Application\nExec=prog\nTryExec=./prog\n", _ALL),
    "its program by name, in the entry's Path": ("Type=Application\nPath={lib}\nExec=tool\n", _ALL),
    "its program by name, not in the entry's Path or the PATH": ("Type=Application\nPath={bin}\nExec=tool\n", set()),
    "TryExec by a relative path, in the entry's Path": ("Type=Application\nPath={lib}\nExec=prog\nTryExec=./tool\n", _ALL),
    "its program by a relative path from the entry's Path": ("Type=Application\nPath={lib}\nExec=../bin/prog\n", _ALL),
}


def _glib_shows(paths, desktop, path_env):
    """Which of `paths` GLib's menu shows on `desktop`: loaded (Gio.DesktopAppInfo), not hidden, and
    should_show(). None where no system python3 has python3-gi (tier 1's container has it)."""
    py = shutil.which("python3", path="/usr/bin:/bin")
    if not py or subprocess.run([py, "-c", "import gi"], capture_output=True).returncode:
        return None
    code = ("import json, sys, gi\ngi.require_version('Gio', '2.0')\nfrom gi.repository import Gio\nout = []\n"
            "for p in sys.argv[1:]:\n"
            "    try:\n        i = Gio.DesktopAppInfo.new_from_filename(p)\n    except TypeError:\n        i = None\n"
            "    out.append(bool(i) and not i.get_is_hidden() and i.should_show())\n"
            "print(json.dumps(out))\n")
    r = subprocess.run([py, "-c", code, *paths], capture_output=True, text=True, check=True,
                       env={"PATH": path_env, "XDG_CURRENT_DESKTOP": desktop, "HOME": os.environ.get("HOME", "/")})
    return json.loads(r.stdout)


@pytest.mark.skipif(install.OS == "windows", reason="system packages are Linux's (R16)")
@pytest.mark.parametrize("desktop", _DESKTOPS, ids=[d or "no desktop" for d in _DESKTOPS])
def test_open_takes_only_an_entry_the_desktops_menu_shows(tmp_path, monkeypatch, desktop):
    # #689's review, P1-B4: R5.7.4's Open starts a system package's own menu entry, "never one the
    # menu doesn't show", and AppKata read NoDisplay and Hidden alone. An entry meant for other
    # desktops (OnlyShowIn, NotShowIn, by $XDG_CURRENT_DESKTOP's names in order) or for a program
    # that isn't installed (TryExec, and Exec's own program, which GLib looks for too) isn't in the
    # menu: a package whose first entry by name was KDE's was opened by it on GNOME or Cinnamon.
    # The class is every rule a menu applies to an entry, so each case is held to GLib's own answer
    # where it is here, and to the specification's everywhere.
    bin_, lib = tmp_path / "bin", tmp_path / "lib"
    for folder, names in ((bin_, ("prog", "my prog", "a$b")), (lib, ("tool",))):
        folder.mkdir()
        for name in names:
            (folder / name).write_text("#!/bin/sh\n")
            (folder / name).chmod(0o755)
    (bin_ / "notes.txt").write_text("not a program\n")
    path_env = f"{bin_}:/usr/bin:/bin"
    monkeypatch.setenv("PATH", path_env)
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", desktop)
    monkeypatch.chdir(tmp_path)                                     # GLib's working directory, and AppKata's
    paths = []
    for i, (case, (lines, _)) in enumerate(_MENU_CASES.items()):
        p = tmp_path / f"entry-{i}.desktop"
        lines = lines if isinstance(lines, bytes) else lines.encode()
        lines = lines.replace(b"{bin}", os.fsencode(bin_)).replace(b"{lib}", os.fsencode(lib))
        p.write_bytes(f"[Desktop Entry]\nName={case}\n".encode() + lines)
        paths.append(str(p))
    want = {case: desktop in shown for case, (_, shown) in _MENU_CASES.items()}
    assert {case: install._menu_entry(p) is not None for case, p in zip(_MENU_CASES, paths)} == want
    if (glib := _glib_shows(paths, desktop, path_env)) is not None:
        assert dict(zip(_MENU_CASES, glib)) == want                 # and the table is GLib's
