"""AppKata installing itself on the first start of a downloaded AppImage (requirement 2.11.3.1)."""

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
    assert f'Exec="{stable}" %U' in entry and "Icon=appkata" in entry and "StartupWMClass=appkata" in entry
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
