"""AppKata installing itself on the first start of a downloaded AppImage (requirement 2.11.3.1):
a copy in the install folder with the stable-name link, an app-menu entry and icon, and the
appkata:// handler and autostart pointed at the stable link."""

from __future__ import annotations

import json
import os
import shutil
import subprocess

from . import APPKATA_REPO, __version__, audit, desktop
from .db import DB, now
from .platform import OS, arch

STABLE = "AppKata.AppImage"


def running_appimage() -> str:
    """The AppImage this AppKata runs from, or ""."""
    p = os.environ.get("APPIMAGE", "")
    return os.path.abspath(p) if OS == "linux" and p and os.path.isfile(p) else ""


def target(root: str) -> str:
    return os.path.join(root, "appkata")


def _record(db: DB) -> dict:
    row = db.one("SELECT record FROM installs WHERE url=?", (APPKATA_REPO,))
    return json.loads(row["record"] or "{}") if row else {}


def installed(db: DB) -> bool:
    """Whether AppKata has installed itself (its record says so and the stable link is there)."""
    rec = _record(db)
    return bool(rec.get("selfInstalled")) and os.path.exists(rec.get("exec", ""))


def should_ask(db: DB, root: str, declined: bool, image: str | None = None) -> bool:
    """Ask "Install AppKata?": an AppImage running from outside the install folder, not installed,
    and not answered with Run from here."""
    image = running_appimage() if image is None else image
    if not image or declined or installed(db):
        return False
    t = os.path.realpath(target(root))
    return not os.path.realpath(image).startswith(t + os.sep)


def desktop_entry_path() -> str:
    return os.path.join(os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"), "applications", "appkata.desktop")


def icon_paths() -> dict[str, str]:
    base = os.path.join(os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"), "icons", "hicolor")
    return {"svg": os.path.join(base, "scalable", "apps", "appkata.svg"), "png": os.path.join(base, "256x256", "apps", "appkata.png")}


def _icon_sources() -> dict[str, str]:
    """The icon from the AppImage's AppDir, else from the package (src/appkata/qml/assets)."""
    out = {}
    appdir = os.environ.get("APPDIR", "")
    for kind, rel in (("svg", "usr/share/icons/hicolor/scalable/apps/appkata.svg"), ("png", "usr/share/icons/hicolor/256x256/apps/appkata.png")):
        p = os.path.join(appdir, rel) if appdir else ""
        if p and os.path.isfile(p):
            out[kind] = p
    if "svg" not in out and own_icon():
        out["svg"] = own_icon()
    return out


def own_icon() -> str:
    """AppKata's icon as its package carries it (src/appkata/qml/assets), or "" where it's missing."""
    p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "appkata", "qml", "assets", "appkata.svg")
    return p if os.path.isfile(p) else ""


def _render_png(svg: str, dest: str) -> bool:
    """A 256 px PNG of the SVG, through Qt when it's there; best effort."""
    try:
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QImage, QPainter
        from PySide6.QtGui import QGuiApplication
        from PySide6.QtSvg import QSvgRenderer
        if QGuiApplication.instance() is None:          # `--install-self` has no GUI
            os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
            _render_png.app = QGuiApplication([])
        img = QImage(256, 256, QImage.Format.Format_ARGB32)
        img.fill(Qt.GlobalColor.transparent)
        p = QPainter(img)
        QSvgRenderer(svg).render(p)
        p.end()
        return img.save(dest, "PNG")
    except Exception:       # noqa: BLE001  (no Qt, or no GUI: the SVG icon is enough)
        return False


def write_icons() -> list[str]:
    src, dst, written = _icon_sources(), icon_paths(), []
    for kind in ("svg", "png"):
        os.makedirs(os.path.dirname(dst[kind]), exist_ok=True)
        if kind in src:
            shutil.copyfile(src[kind], dst[kind])
            written.append(dst[kind])
        elif kind == "png" and "svg" in src and _render_png(src["svg"], dst["png"]):
            written.append(dst["png"])
    return written


def write_desktop_entry(exec_path: str) -> str:
    """appkata.desktop: its name matches the window's desktop file name (app.setDesktopFileName)."""
    p = desktop_entry_path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    mime = "MimeType=x-scheme-handler/appkata;\n" if desktop.scheme_registered() else ""
    with open(p, "w") as f:
        f.write("[Desktop Entry]\nType=Application\nName=AppKata\nComment=A FOSS app store built on git\n"
                f"Exec=\"{exec_path}\" %U\nIcon=appkata\nCategories=System;PackageManager;\n{mime}"
                "StartupWMClass=appkata\nTerminal=false\n")
    os.chmod(p, 0o755)
    if shutil.which("update-desktop-database"):
        subprocess.run(["update-desktop-database", os.path.dirname(p)], capture_output=True)
    return p


def install_self(db: DB, root: str, image: str | None = None, delete_download: bool = False,
                 version: str = __version__, options: dict | None = None) -> dict:
    """Copy the running AppImage into <root>/appkata/, link AppKata.AppImage to it, record it as
    AppKata's installed version, and integrate it with the desktop. Returns the install record."""
    image = image or running_appimage()
    if not image:
        raise OSError("AppKata isn't running as an AppImage")
    t = target(root)
    os.makedirs(t, exist_ok=True)
    name = f"AppKata-{version}-{arch()}.AppImage"
    dest = os.path.join(t, name)
    if os.path.realpath(image) != os.path.realpath(dest):
        tmp = dest + ".new"
        shutil.copyfile(image, tmp)
        os.chmod(tmp, 0o755)
        os.replace(tmp, dest)
    stable = os.path.join(t, STABLE)
    if os.path.lexists(stable):
        os.remove(stable)
    os.symlink(name, stable)
    desktop.LAUNCH_OVERRIDE = stable
    entry = write_desktop_entry(stable)
    icons = write_icons()
    if desktop.scheme_registered():                 # the appkata:// handler and autostart follow the stable link
        desktop.register_scheme(True)
    if desktop.autostart_on():
        desktop.set_autostart(True)
    rec = {"files": [t, entry, *icons], "links": [stable], "root": root, "target": t, "kept": [], "exec": stable,
           "current": {"version": version, "path": dest, "exec": name}, "verified": "adopted", "selfInstalled": True,
           "options": options or {"appMenu": True, "commandLink": False, "stableName": True}}
    db.x("INSERT OR REPLACE INTO installs(url, name, version, date, asset, kind, record, installed_at) VALUES(?,?,?,?,?,?,?,?)",
         (APPKATA_REPO, "AppKata", version, "", name, "appimage", json.dumps(rec), now()))
    deleted = False
    if delete_download and os.path.realpath(image) != os.path.realpath(dest):
        try:
            os.remove(image)
            deleted = True
        except OSError:
            pass
    audit.record(db, "you", "app", "installed AppKata", "AppKata", APPKATA_REPO,
                 {"version": version, "to": dest, "from": image, "deletedDownload": deleted or None})
    return rec


def launch(rec: dict) -> None:
    """Start the installed copy (the GUI then quits)."""
    subprocess.Popen([rec["exec"]], start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     env={k: v for k, v in os.environ.items() if k not in ("APPIMAGE", "APPDIR", "ARGV0", "OWD")})
