"""AppKata installing itself on the first start of a downloaded AppImage (R2.11.3.1):
a copy in the install folder with the stable-name link, an app-menu entry and icon, and the
appkata:// handler and autostart pointed at the stable link."""

from __future__ import annotations

import contextlib
import glob
import json
import logging
import os
import re
import shutil
import subprocess

from . import APPKATA_REPO, __version__, audit, desktop
from .install import _write_whole, desktop_exec
from .db import DB, now
from .platform import OS, arch

STABLE = "AppKata.AppImage"

log = logging.getLogger("appkata.selfinstall")


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
    """AppKata's icons, each written whole beside its place and renamed over it, as its menu entry
    is (#689's review, P7-B3: copied in place, so a copy that failed left part of an icon)."""
    src, dst, written = _icon_sources(), icon_paths(), []
    for kind in ("svg", "png"):
        os.makedirs(os.path.dirname(dst[kind]), exist_ok=True)
        if kind in src:
            with open(src[kind], "rb") as f:
                _write_whole(dst[kind], f.read(), 0o644)
            written.append(dst[kind])
        elif kind == "png" and "svg" in src and _render_whole(src["svg"], dst["png"]):
            written.append(dst["png"])
    return written


def _render_whole(svg: str, dest: str) -> bool:
    """:func:`_render_png` to a file beside `dest`, renamed over it once it is written."""
    tmp = f"{dest}.{os.getpid()}.tmp"
    try:
        if _render_png(svg, tmp):
            os.replace(tmp, dest)
            return True
        return False
    finally:
        if os.path.lexists(tmp):
            with contextlib.suppress(OSError):
                os.remove(tmp)


def _exec_value(exec_path: str) -> str:
    """`Exec=` for AppKata's own entry, escaped as every entry's is (:func:`install.desktop_exec`).
    Its program is `/bin/sh`, which runs `exec_path` by its own path with the opened files
    (`sh -c 'exec "$0" "$@"'`): GLib looks for an entry's program before it reads `%%` as `%`, so
    with a `%` in the install folder's path AppKata, its program there, was in no menu of
    Cinnamon, GNOME, MATE or Xfce (#689's review, P4-2), as an app was before #685. Not a script
    of its own, as an app's entry has (`/bin/sh "<script>"`): AppKata's program is an AppImage,
    which sh can't read as a script, and `exec` runs it as it is, with no file to write, record
    or remove. A path it refuses (a quote or a line break in the install folder's name) is an
    OSError, which both callers of :func:`install_self` report."""
    try:
        return desktop_exec(exec_path, sh_exec=True)
    except ValueError as e:
        raise OSError(str(e)) from None


def write_desktop_entry(exec_path: str) -> str:
    """appkata.desktop: its name matches the window's desktop file name (app.setDesktopFileName).
    Written whole beside it and renamed over it (install._write_whole), as an app's entry is, so a
    write that fails (a full disk, a quota) leaves the entry as it was. #689's review, P7-B3: it
    was emptied before it was written, so such a write left AppKata in no app menu."""
    exec_value = _exec_value(exec_path)
    p = desktop_entry_path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    mime = "MimeType=x-scheme-handler/appkata;\n" if desktop.scheme_registered() else ""
    _write_whole(p, ("[Desktop Entry]\nType=Application\nName=AppKata\nComment=A FOSS app store built on git\n"
                     f"Exec={exec_value}\nIcon=appkata\nCategories=System;PackageManager;\n{mime}"
                     "StartupWMClass=appkata\nTerminal=false\n").encode("utf-8"), 0o755)
    if shutil.which("update-desktop-database"):
        subprocess.run(["update-desktop-database", os.path.dirname(p)], capture_output=True)
    return p


def install_self(db: DB, root: str, image: str | None = None, delete_download: bool = False,
                 version: str = __version__, options: dict | None = None) -> dict:
    """Copy the running AppImage into <root>/appkata/, link AppKata.AppImage to it, record it as
    AppKata's installed version, and integrate it with the desktop. Returns the install record.
    The copy is made beside its place (`<copy>.<pid>.tmp`) and renamed over it, and removed when
    it fails (#689's review, P7-B3: a failed copy left a partial `.new` there for good)."""
    image = image or running_appimage()
    if not image:
        raise OSError("AppKata isn't running as an AppImage")
    t = target(root)
    _exec_value(os.path.join(t, STABLE))        # refused before anything is copied, never half-way
    os.makedirs(t, exist_ok=True)
    name = f"AppKata-{version}-{arch()}.AppImage"
    dest = os.path.join(t, name)
    if os.path.realpath(image) != os.path.realpath(dest):
        tmp = f"{dest}.{os.getpid()}.tmp"
        try:
            shutil.copyfile(image, tmp)
            os.chmod(tmp, 0o755)
            os.replace(tmp, dest)
        except BaseException:
            if os.path.lexists(tmp):
                with contextlib.suppress(OSError):      # the copy's own error is the one raised
                    os.remove(tmp)
            raise
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


def sweep_left_beside(db: DB, root: str) -> list[str]:
    """AppKata's start: remove what a write of AppKata's own install stopped part-way (killed, the
    power gone) left beside its files: `<file>.<pid>.tmp` beside its menu entry and its icons, and
    `AppKata-<version>-<arch>.AppImage.<pid>.tmp`, a copy, in its install folder (the one its record
    names, and `root`'s, where a first install may have stopped). Only one whose process is gone:
    `appkata --install-self` runs beside a running AppKata, and may be writing it. Returns what it
    removed; one it can't remove is logged with why and left for the next start (#689's review,
    P7-B3)."""
    if OS != "linux":
        return []
    rec = _record(db)
    found = [(f, f[len(p) + 1:-4]) for p in (desktop_entry_path(), *icon_paths().values())
             for f in glob.glob(glob.escape(p) + ".*.tmp")]
    for folder in dict.fromkeys(f for f in (rec.get("target") if rec.get("selfInstalled") else "", target(root)) if f):
        for f in glob.glob(os.path.join(glob.escape(folder), "AppKata-*.AppImage.*.tmp")):
            m = re.fullmatch(r"AppKata-.+\.AppImage\.([0-9]+)\.tmp", os.path.basename(f))
            found.append((f, m.group(1) if m else ""))
    gone = []
    for f, pid in found:
        if re.fullmatch(r"[0-9]+", pid) and not os.path.isdir(f) and not _runs(int(pid)):
            try:
                os.remove(f)
                gone.append(f)
            except OSError as e:
                log.warning("couldn't remove %s: %s", f, e.strerror or e)
    return gone


def _runs(pid: int) -> bool:
    """Whether a process `pid` runs, or may: only one there is none of is taken as gone."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except (OSError, OverflowError):      # another user's, which runs; or no pid at all, so none of AppKata's
        return True
    return True


def launch(rec: dict) -> None:
    """Start the installed copy (the GUI then quits)."""
    subprocess.Popen([rec["exec"]], start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     env={k: v for k, v in os.environ.items() if k not in ("APPIMAGE", "APPDIR", "ARGV0", "OWD")})
