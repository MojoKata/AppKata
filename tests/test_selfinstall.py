"""AppKata installing itself on the first start of a downloaded AppImage (R2.11.3.1)."""

import json
import os

import pytest

from appkata_core import APPKATA_REPO, desktop, platform, selfinstall
from appkata_core.db import DB

pytestmark = pytest.mark.skipif(platform.OS != "linux", reason="AppImages are Linux only")


@pytest.fixture
def env(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / "Downloads").mkdir(parents=True)
    image = home / "Downloads" / "AppKata-0.1.0-x86_64.AppImage"
    image.write_bytes(b"\x7fELF fake appimage")
    image.chmod(0o755)
    appdir = tmp_path / "appdir"
    (appdir / "usr/share/icons/hicolor/scalable/apps").mkdir(parents=True)
    (appdir / "usr/share/icons/hicolor/256x256/apps").mkdir(parents=True)
    (appdir / "usr/share/icons/hicolor/scalable/apps/appkata.svg").write_text("<svg/>")
    (appdir / "usr/share/icons/hicolor/256x256/apps/appkata.png").write_bytes(b"\x89PNG")
    monkeypatch.setenv("APPIMAGE", str(image))
    monkeypatch.setenv("APPDIR", str(appdir))
    monkeypatch.setenv("XDG_DATA_HOME", str(home / ".local/share"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    monkeypatch.setattr(desktop, "LAUNCH_OVERRIDE", "")
    monkeypatch.setattr(desktop.shutil, "which", lambda _: None)        # no xdg-mime / update-desktop-database
    monkeypatch.setattr(selfinstall.shutil, "which", lambda _: None)
    return {"home": home, "image": image, "root": str(home / "bin/apps"), "db": DB(str(tmp_path / "appkata.db"))}


def test_asks_only_for_a_downloaded_appimage(env, monkeypatch):
    db, root = env["db"], env["root"]
    assert selfinstall.should_ask(db, root, declined=False)
    assert not selfinstall.should_ask(db, root, declined=True)          # Run from here
    inside = os.path.join(root, "appkata", "AppKata-0.1.0-x86_64.AppImage")
    os.makedirs(os.path.dirname(inside))
    open(inside, "wb").close()
    assert not selfinstall.should_ask(db, root, declined=False, image=inside)
    monkeypatch.delenv("APPIMAGE")
    assert not selfinstall.should_ask(db, root, declined=False)         # run from source


def test_install_self(env):
    db, root, image = env["db"], env["root"], env["image"]
    desktop.register_scheme(True)
    desktop.set_autostart(True)
    rec = selfinstall.install_self(db, root, delete_download=True, version="0.1.0")
    t = os.path.join(root, "appkata")
    copy = os.path.join(t, f"AppKata-0.1.0-{platform.arch()}.AppImage")
    stable = os.path.join(t, "AppKata.AppImage")
    assert os.path.isfile(copy) and os.access(copy, os.X_OK)
    assert os.path.islink(stable) and os.readlink(stable) == os.path.basename(copy)
    assert not image.exists()                                           # the download was deleted
    entry = open(selfinstall.desktop_entry_path()).read()
    assert f'Exec=/bin/sh -c "exec \\\\"\\\\$0\\\\" \\\\"\\\\$@\\\\"" "{stable}" %U\n' in entry, entry
    assert "Icon=appkata" in entry and "StartupWMClass=appkata" in entry
    assert "MimeType=x-scheme-handler/appkata;" in entry
    icons = selfinstall.icon_paths()
    assert open(icons["svg"]).read() == "<svg/>" and os.path.getsize(icons["png"]) == 4
    # the appkata:// handler and autostart now start the stable link
    assert stable in open(desktop.scheme_entry_path()).read()
    assert stable in open(desktop.autostart_path()).read()
    row = db.one("SELECT * FROM installs WHERE url=?", (APPKATA_REPO,))
    stored = json.loads(row["record"])
    assert row["kind"] == "appimage" and row["version"] == "0.1.0"
    assert stored["selfInstalled"] and stored["exec"] == stable and stored["current"]["path"] == copy
    assert not stored["current"].get("external")
    assert selfinstall.installed(db)
    assert not selfinstall.should_ask(db, root, declined=False)
    assert db.one("SELECT action FROM audit ORDER BY id DESC LIMIT 1")["action"] == "installed AppKata"
    assert rec == stored


def test_install_self_keeps_the_download_and_skips_off_options(env):
    db, root, image = env["db"], env["root"], env["image"]
    selfinstall.install_self(db, root, version="0.1.0")
    assert image.exists()
    assert "MimeType" not in open(selfinstall.desktop_entry_path()).read()      # no appkata:// handler registered
    assert not os.path.exists(desktop.autostart_path())


def test_appkatas_own_menu_entry_escapes_its_path_and_a_folder_it_cannot_start_is_refused_first(env):
    # CR1.3-7: AppKata's own entry wrote its path in quotes and escaped nothing, as the apps' did,
    # so an install folder with a $, a %, a backtick or a backslash in its name gave AppKata a menu
    # entry that started something else or nothing. Its Exec= is read back by the specification's
    # rules; and a folder no entry can name (a quote, a line break) is refused before anything is
    # copied or recorded, with the error both callers report.
    from test_install_review import _exec_words
    db, home = env["db"], env["home"]
    root = str(home / "my apps" / "50% $ `id` back\\slash")
    rec = selfinstall.install_self(db, root, version="0.1.0")
    stable = os.path.join(root, "appkata", "AppKata.AppImage")
    exec_line = next(l for l in open(selfinstall.desktop_entry_path()).read().splitlines() if l.startswith("Exec="))
    assert rec["exec"] == stable and _exec_words(exec_line[len("Exec="):]) == [*_SH_EXEC, stable, "%U"], exec_line
    os.remove(selfinstall.desktop_entry_path())
    db.x("DELETE FROM installs")
    for bad in ('quo"te', "line\nbreak"):
        with pytest.raises(OSError, match="quote or a line break"):
            selfinstall.install_self(db, str(home / bad / "apps"), version="0.1.0")
        assert not (home / bad).exists()
    assert not os.path.exists(selfinstall.desktop_entry_path()) and db.one("SELECT * FROM installs") is None
    with pytest.raises(OSError, match="quote or a line break"):
        selfinstall.write_desktop_entry('/opt/quo"te/AppKata.AppImage')
    assert not os.path.exists(selfinstall.desktop_entry_path())


_SH_EXEC = ["/bin/sh", "-c", 'exec "$0" "$@"']        # AppKata's own entry: sh runs its program (#689's review, P4-2)


def _glib_starts(path):
    """What GLib starts from the entry at `path` as a desktop's menu does, with no file
    (Gio.DesktopAppInfo.launch): the program's output, "not shown" where GLib loads no app from it
    or its menu doesn't show it, or None where no system python3 has python3-gi (tier 1's
    container has it). shutil.which is the env fixture's stand-in here, so python3 is looked for
    by its path."""
    import subprocess
    py = next((p for p in ("/usr/bin/python3", "/bin/python3") if os.access(p, os.X_OK)), None)
    if not py or subprocess.run([py, "-c", "import gi"], capture_output=True).returncode:
        return None
    code = ("import sys, gi\ngi.require_version('Gio', '2.0')\nfrom gi.repository import Gio\n"
            "try:\n    i = Gio.DesktopAppInfo.new_from_filename(sys.argv[1])\nexcept TypeError:\n    i = None\n"
            "if not i or not i.should_show():\n    print('not shown', end='')\nelse:\n    i.launch([], None)\n")
    return subprocess.run([py, "-c", code, str(path)], capture_output=True, text=True, timeout=60).stdout


@pytest.mark.parametrize("folder", ["apps", "100% apps", "a%U b"], ids=["plain", "a percent", "a field code"])
def test_appkatas_own_menu_entry_starts_it_whatever_its_install_folder_holds(env, folder):
    # #689's review, P4-2: AppKata's own entry named its program, the stable link in the install
    # folder, as the entry's program. GLib looks for an entry's program before it reads %% as %, so
    # with a % in the install folder (Settings names it, R4.3.1) AppKata, installed and recorded,
    # was in no menu of Cinnamon, GNOME, MATE or Xfce, as an app was before #685. The entry's
    # program is /bin/sh, which runs the stable link by its own path with the opened files; here
    # the AppImage is a program that isn't a script (a copy of echo), which `/bin/sh "<path>"`
    # couldn't run, and GLib itself, where it is here, loads, shows and starts the entry.
    from test_install_review import _exec_words
    import subprocess
    db, home = env["db"], env["home"]
    with open("/bin/echo", "rb") as f:
        env["image"].write_bytes(f.read())
    root = str(home / folder)
    rec = selfinstall.install_self(db, root, version="0.1.0")
    stable = os.path.join(root, "appkata", "AppKata.AppImage")
    exec_line = next(l for l in open(selfinstall.desktop_entry_path()).read().splitlines() if l.startswith("Exec="))
    words = _exec_words(exec_line[len("Exec="):])
    assert rec["exec"] == stable and words == [*_SH_EXEC, stable, "%U"], exec_line
    if (glib := _glib_starts(selfinstall.desktop_entry_path())) is not None:
        assert glib == "\n", glib                                     # GLib shows the entry and starts echo, with no file
    started = subprocess.run(words[:-1] + ["a file.txt", "100%"], capture_output=True, text=True)
    assert (started.returncode, started.stdout, started.stderr) == (0, "a file.txt 100%\n", ""), started


def test_icon_falls_back_to_the_package(env, monkeypatch):
    monkeypatch.delenv("APPDIR")
    monkeypatch.setattr(selfinstall, "_render_png", lambda svg, dest: False)
    written = selfinstall.write_icons()
    assert written == [selfinstall.icon_paths()["svg"]]
    assert "<svg" in open(written[0]).read()


def test_updates_keep_appkatas_own_menu_entry(env):
    """An update of the installed AppKata relinks AppKata.AppImage and adds no second launcher."""
    from appkata_core import install
    db, root = env["db"], env["root"]
    rec = selfinstall.install_self(db, root, version="0.1.0")
    t = rec["target"]
    new = os.path.join(t, "AppKata-0.2.0-x86_64.AppImage")
    open(new, "wb").close()
    rec2 = {**rec, "current": {"version": "0.2.0", "path": new, "exec": os.path.basename(new)}}
    install._activate(rec2, {"name": "AppKata", "url": APPKATA_REPO}, install.Portable(folder=root), t)
    assert os.readlink(os.path.join(t, "AppKata.AppImage")) == os.path.basename(new)
    assert not os.path.exists(os.path.join(os.path.dirname(selfinstall.desktop_entry_path()), "appkata-appkata.desktop"))
    assert os.path.exists(selfinstall.desktop_entry_path())


def test_a_fresh_start_lists_appkata_by_its_name_and_icon_before_any_sync(env, monkeypatch, tmp_path):
    # Review 3, R3-36: on the AppImage's first start, before any sync, the Apps view listed AppKata as
    # "appkata" (its URL's last part) with a letter for an icon: with no metadata synced, nothing read
    # its install record's name, and every tour screen stages a synced Catalog. A fresh database here.
    monkeypatch.setenv("HOME", str(env["home"]))
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from appkata.backend import Backend
    be = Backend(db_path=str(tmp_path / "fresh.db"))
    assert not be.lastSync
    me = [a for a in be.installedItems if a["url"] == APPKATA_REPO]
    assert len(me) == 1 and me[0]["name"] == "AppKata", me
    assert me[0]["icon"].endswith(".svg") and "<svg" in open(me[0]["icon"]).read(), me[0]["icon"]
