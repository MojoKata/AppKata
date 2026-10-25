"""Installing, updating and uninstalling (requirement 4): AppImage, tarball, Flatpak bundle, .deb
and .rpm on Linux; portable .zip and .exe, installers (.msi, .exe) and .msix on Windows (15).
macOS installers follow."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tarfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, replace

import logging
import threading

from . import applog, appkind, flatpak, pkgbackend, sandbox
from .pkgbackend import NeedsConfirmation, PackageError
from .assets import checksum_for
from .db import DB, now
from .forges import Asset
from .http import UA
from .platform import OS, apps_dir, desktop_dir


log = logging.getLogger("appkata.install")


class InstallError(Exception):
    pass


class Cancelled(InstallError):
    def __init__(self):
        super().__init__("cancelled")


class InUse(InstallError):
    """Windows can't replace a running program's files (requirement 15.9)."""
    def __init__(self, name: str, programs: list[str]):
        self.name, self.programs = name, programs
        super().__init__(f"close {name} to continue")


def slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "app"
    if OS == "windows":
        from .windows import safe_name
        s = safe_name(s)
    return s


def app_id_of(rec: dict, app: dict) -> str:
    """The name everything about an installed app is keyed on -- its folder under the install root,
    the launcher, the desktop entry and command link, the `io.appkata.<id>` identity, the private
    home: the id recorded at install (unique among installs), else the name's slug for a record
    written before ids were recorded. Round six, R6-1: two Sources' apps with one name shared all
    of it -- one launcher ran the other's program with its grants, one private home held both."""
    return rec.get("id") or slug(app["name"])


def new_app_id(db: DB, url: str, name: str) -> str:
    """An id for a fresh install: the name's slug, or `<slug>-2`, `-3`... when another install
    already holds it, or a private home an uninstall kept belongs to another app (review 2, F19: the
    next "Notes" from another Source got the freed id, and with it the first one's home and tokens).
    The same app reinstalled finds its own kept home again."""
    base = slug(name)
    taken = set()
    for r in db.all("SELECT url, name, record FROM installs WHERE url<>?", (url,)):
        taken.add(app_id_of(json.loads(r["record"] or "{}"), {"name": r["name"]}))
    cand, n = base, 1
    while cand in taken or (OS == "linux" and sandbox.home_belongs_to_another(cand, url)):
        n += 1
        cand = f"{base}-{n}"
    return cand


def check_not_running(folder: str, name: str) -> None:
    """Stop before touching a folder that a running program comes from (requirement 15.9)."""
    if OS != "windows" or not folder or not os.path.isdir(folder):
        return
    from . import windows
    if procs := windows.processes_in(folder):
        raise InUse(name, procs)


def downloads_dir() -> str:
    """Where partial downloads wait to be resumed (requirement 4.8.2)."""
    from .platform import data_dir
    return os.path.join(data_dir(), "downloads")


def download(url: str, dest: str, progress=None, cancel=None, timeout: float = 60, retries: int = 3) -> str:
    """Download to dest through dest + ".part", resuming a broken or earlier download with a Range
    request when the server still has the same file (requirement 4.8.2). Returns the SHA-256 hex
    digest of the whole file. Cancelling deletes the partial file; other failures keep it."""
    part, meta_path = dest + ".part", dest + ".part.json"
    try:
        meta = json.load(open(meta_path)) if os.path.exists(part) else {}
    except (OSError, ValueError):
        meta = {}
    if meta.get("url") != url:                  # a different file: start over
        meta = {"url": url}
        for f in (part, meta_path):
            if os.path.exists(f):
                os.remove(f)
    attempt = 0
    while True:
        got = os.path.getsize(part) if os.path.exists(part) else 0
        headers = {"User-Agent": UA}
        if got and meta.get("validator"):
            headers.update({"Range": f"bytes={got}-", "If-Range": meta["validator"]})
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout) as r:
                resumed = r.status == 206
                if not resumed:
                    got = 0
                validator = r.headers.get("ETag") or r.headers.get("Last-Modified") or ""
                if validator and not validator.startswith("W/"):     # a weak ETag can't resume (RFC 9110)
                    meta["validator"] = validator
                    with open(meta_path, "w") as mf:
                        json.dump(meta, mf)
                length = int(r.headers.get("Content-Length") or 0)
                total = got + length if length else 0
                with open(part, "ab" if resumed else "wb") as f:
                    while True:
                        if cancel and cancel():
                            raise Cancelled()
                        chunk = r.read(1 << 16)
                        if not chunk:
                            break
                        f.write(chunk)
                        got += len(chunk)
                        if progress:
                            progress(got, total)
                if total and got < total:
                    raise OSError(f"the connection closed after {got} of {total} bytes")
            break
        except Cancelled:
            for f in (part, meta_path):
                if os.path.exists(f):
                    os.remove(f)
            raise
        except urllib.error.HTTPError as e:
            if e.code == 416 and got:           # the part is stale or already complete: start over
                os.remove(part)
                attempt += 1
                if attempt <= retries:
                    continue
            raise InstallError(f"download failed: HTTP {e.code}") from None
        except OSError as e:
            attempt += 1
            if attempt > retries:
                raise InstallError(f"download failed: {e}; press Update again to resume") from None
            log.warning("download of %s broke at %d bytes (%s); resuming", url, got, e)
            time.sleep(min(10, 2 * attempt))
    h = hashlib.sha256()
    with open(part, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    os.replace(part, dest)
    if os.path.exists(meta_path):
        os.remove(meta_path)
    return h.hexdigest()


def head_bytes(url: str, n: int = 1 << 20, timeout: float = 30) -> bytes:
    """The first n bytes of a download (a Range request), to see what a .exe is (requirement 4.2.1)."""
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Range": f"bytes=0-{n - 1}"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read(n)
    except OSError:
        return b""


def expected_sha256(asset: Asset, assets: list[Asset]) -> tuple[str, str]:
    """(hex, source) of the checksum to compare with: the forge digest, or a checksum file (requirement 4.4)."""
    if asset.digest.startswith("sha256:"):
        return asset.digest.split(":", 1)[1].lower(), "forge digest"
    sums = checksum_for(asset, assets)
    if not sums:
        return "", ""
    try:
        req = urllib.request.Request(sums.url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=30) as r:
            text = r.read(1 << 20).decode("utf-8", "replace")
    except OSError:
        return "", ""
    for line in text.splitlines():
        m = re.match(r"^([0-9a-fA-F]{64})\s+\*?(.+?)\s*$", line.strip())
        if m and os.path.basename(m.group(2)) == asset.name:
            return m.group(1).lower(), sums.name
    m = re.fullmatch(r"\s*([0-9a-fA-F]{64})\s*", text)
    return (m.group(1).lower(), sums.name) if m else ("", "")


def _elevate(cmd: list[str]) -> subprocess.CompletedProcess:
    """Run an install command with administrator rights for this action only (requirement 1.3)."""
    if OS == "linux":
        if os.geteuid() != 0:
            if not shutil.which("pkexec"):
                raise InstallError("pkexec isn't available to ask for administrator rights")
            cmd = ["pkexec"] + cmd
    return applog.run(cmd, timeout=1800)


def _desktop_entry(app_id: str, name: str, exec_path: str, icon: str, summary: str, launcher: bool = False) -> str:
    """The app-menu entry. For a sandbox launcher (`launcher=True`) Exec passes the word
    --appkata-menu first: started this way nothing shows stderr, so the launcher keeps its own in
    logs/apps/<id>.log, where a refused launch is then found (14.2.1, requirement 17.4)."""
    path = os.path.join(desktop_dir(), f"appkata-{app_id}.desktop")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    word = " --appkata-menu" if launcher else ""
    with open(path, "w") as f:
        f.write("[Desktop Entry]\nType=Application\n"
                f"Name={name}\nComment={summary[:120]}\nExec=\"{exec_path}\"{word} %U\n"
                + (f"Icon={icon}\n" if icon else "") + "Categories=Utility;\nX-AppKata=true\n")
    os.chmod(path, 0o755)
    return path


def _find_exe(root: str, names: list[str]) -> str:
    want = [n.lower().replace(" ", "") for n in names]
    exes = [os.path.join(d, f) for d, _, fs in os.walk(root) for f in fs if f.lower().endswith(".exe")
            and not re.search(r"unins|update|crash|helper", f, re.I)]
    if not exes:
        raise InstallError("couldn't find the program in the archive")
    exes.sort(key=lambda p: (not any(w in os.path.basename(p).lower() for w in want), p.count(os.sep)))
    return exes[0]


def _find_executable(root: str, names: list[str]) -> str:
    want = [n.lower().replace(" ", "") for n in names]
    cands = []
    for dp, dn, fn in os.walk(root):
        for f in fn:
            p = os.path.join(dp, f)
            try:
                st = os.stat(p)
            except OSError:
                continue
            if not (st.st_mode & stat.S_IXUSR) or f.endswith((".so", ".sh")) or ".so." in f:
                continue
            score = 0 if f.lower() in want else 1 if any(w in f.lower() for w in want) else 3
            cands.append((score, p.count(os.sep), p))
    if not cands:
        raise InstallError("couldn't find the program in the archive")
    cands.sort()
    return cands[0][2]


@dataclass
class Portable:
    """Where and how apps are installed (requirement 4.3.1, 11.1.4, 15.4)."""
    folder: str = ""              # each app gets <folder>/<app>/ (default: platform.apps_dir())
    app_menu: bool = True         # add a .desktop entry / Start-menu shortcut
    stable_name: bool = True      # <App>.AppImage → the versioned file, so launchers survive updates
    command_dir: str = ""         # a folder on PATH for a command link per app ("" = none)
    keep: int = 2                 # older versions kept for a quick rollback
    scope: str = "me"             # Windows: "me" or "everyone" (requirement 15.4)
    folder_everyone: str = ""     # Windows: where apps for everyone go (default C:\Programs)
    motw: bool = False            # Windows: Mark of the Web on downloads (requirement 15.11.1)

    @property
    def root(self) -> str:
        if OS == "windows" and self.scope == "everyone":
            return os.path.abspath(os.path.expandvars(self.folder_everyone)) if self.folder_everyone else apps_dir("everyone")
        return os.path.abspath(os.path.expandvars(os.path.expanduser(self.folder))) if self.folder else apps_dir()


def _link(target: str, link: str) -> str:
    """Point `link` at `target` (relative when they share a folder); returns the link path."""
    os.makedirs(os.path.dirname(link), exist_ok=True)
    if os.path.islink(link) or os.path.exists(link):
        if not os.path.islink(link):
            raise InstallError(f"{link} exists and isn't a link AppKata made; not replacing it")
        os.remove(link)
    rel = os.path.relpath(target, os.path.dirname(link)) if os.path.dirname(target) == os.path.dirname(link) else target
    os.symlink(rel, link)
    return link


def _safe(v: str) -> str:
    s = re.sub(r"[^A-Za-z0-9._+-]+", "_", v or "unknown")
    if OS == "windows":
        from .windows import safe_name
        s = safe_name(s)
    return s


def _extract(kind: str, file: str, dest: str) -> None:
    os.makedirs(dest)
    if kind == "tarball":
        with tarfile.open(file) as tf:
            tf.extractall(dest, filter="data")
        return
    import zipfile
    if OS == "windows":
        from .windows import long_path
        dest = long_path(dest)          # deep archives (requirement 15.16)
    with zipfile.ZipFile(file) as z:
        for m in z.infolist():          # no paths outside the folder
            if m.filename.startswith(("/", "\\")) or ".." in m.filename.replace("\\", "/").split("/"):
                raise InstallError(f"unsafe path in the archive: {m.filename}")
        for m in z.infolist():          # zipfile drops Unix permissions; keep the executable bit
            path = z.extract(m, dest)
            mode = (m.external_attr >> 16) & 0o777
            if mode and not m.is_dir():
                os.chmod(path, mode)


def _place(kind: str, file: str, app: dict, target: str, version: str, asset_name: str, fixed: bool = False) -> dict:
    """Put one version in the app's folder (requirement 4.3.1): {version, path, exec} where path is
    the versioned file or folder and exec is relative to the app folder. `fixed`: an app that
    updates itself gets <App>.AppImage or an "app" folder instead (requirement 4.10.2)."""
    os.makedirs(target, exist_ok=True)
    names = [app["name"], app.get("repo", "").rsplit("/", 1)[-1]]
    if kind == "appimage":
        dest = os.path.join(target, re.sub(r"[^A-Za-z0-9]+", "", app["name"]) + ".AppImage" if fixed else asset_name)
        if os.path.lexists(dest):
            os.remove(dest)
        shutil.move(file, dest)
        os.chmod(dest, 0o755)
        return {"version": version, "path": dest, "exec": os.path.basename(dest)}
    vdir = os.path.join(target, "app" if fixed else _safe(version))
    staging = vdir + ".new"
    shutil.rmtree(staging, ignore_errors=True)
    if kind == "exe":                      # a portable Windows program
        os.makedirs(staging)
        shutil.move(file, os.path.join(staging, re.sub(r"[^A-Za-z0-9]+", "", app["name"]) + ".exe"))
        exe = os.path.join(staging, re.sub(r"[^A-Za-z0-9]+", "", app["name"]) + ".exe")
    else:
        _extract(kind, file, staging)
        exe = _find_exe(staging, names) if OS == "windows" else _find_executable(staging, names)
    shutil.rmtree(vdir, ignore_errors=True)
    os.replace(staging, vdir)
    return {"version": version, "path": vdir, "exec": os.path.relpath(exe.replace(staging, vdir, 1), target)}


def _apply_kind(rec: dict, app: dict, portable: "Portable", kind: str, target: str, prev: dict) -> "Portable":
    """The app's kind (17.3.3), decided from the version just placed, before the launcher and the
    app-menu entry are written (review 2, F4: "a command link and no menu entry" decided it before,
    which Settings' defaults never produced, so every tool ran Strict and saw nothing).

    `rec["appKind"]` records what the download says ("cli" or "gui"; the previous version's when this
    one can't tell). The user's own choice, `app["cliKind"]`, wins over it. With the kind known, the
    caller's `app["sandbox_for_kind"](is_cli)` gives the grant set to bake in (an unreviewed tool gets
    the cli-tool template), and a command-line tool gets no menu entry when the menu option came
    from Settings' default rather than from the user or a Trust (`app["menuFromDefault"]`)."""
    if OS != "linux" or kind not in ("appimage", "tarball"):
        return portable
    detected = appkind.detect(kind, rec["current"], target) or prev.get("appKind")
    if detected:
        rec["appKind"] = detected
    is_cli = (app.get("cliKind") or detected) == appkind.CLI
    if callable(app.get("sandbox_for_kind")):
        app["sandbox"] = app["sandbox_for_kind"](is_cli)
    if is_cli and app.get("menuFromDefault") and portable.app_menu:
        portable = replace(portable, app_menu=False)
    return portable


def _leave_fixed_layout(cur: dict, target: str) -> dict:
    """The current version of an app that updated itself (4.10.2: one fixed-name file or an `app`
    folder), renamed into the versioned layout as AppKata starts updating it -- because it now runs
    sandboxed and can't update itself (17.12; review 2, F3). An AppImage's fixed name is exactly where
    the versioned layout's stable-name link goes, so left in place it stopped the update ("exists and
    isn't a link AppKata made"). Returns the entry as it is now, kept with the version it was."""
    path = cur.get("path", "")
    if path.lower().endswith(".appimage") and os.path.isfile(path) and not os.path.islink(path):
        stem = os.path.basename(path)[:-len(".AppImage")]
        new = os.path.join(target, f"{stem}-{_safe(cur.get('version', ''))}.AppImage")
        if not os.path.lexists(new):
            os.replace(path, new)
            return {**cur, "path": new, "exec": os.path.basename(new)}
    return cur


# _activate removes and re-creates the stable link, the menu entry, the command link and the
# launcher; two of them at once (the startup heal pass on its thread and a sandbox change on the UI
# thread, or an install on a worker) raced on the links -- "File exists: '1.0' -> .../current" --
# and the loser's regeneration was skipped (round five, found by tests/test_sandbox_threads.py).
_ACTIVATE_LOCK = threading.RLock()


def _activate(rec: dict, app: dict, portable: "Portable", target: str) -> None:
    """Point the stable name, the app-menu entry and the command link at rec["current"]."""
    if OS == "windows":
        return _activate_windows(rec, app, portable, target)
    with _ACTIVATE_LOCK:
        _activate_linux(rec, app, portable, target)


def _activate_linux(rec: dict, app: dict, portable: "Portable", target: str) -> None:
    cur, app_id = rec["current"], app_id_of(rec, app)
    for l in rec.get("links", []):           # the previous version's links
        if os.path.islink(l):
            os.remove(l)
    rec["links"] = []
    rec["files"] = [f for f in rec.get("files", []) if not os.path.basename(f).startswith("appkata-")]
    run = os.path.join(target, cur["exec"])
    if portable.stable_name and OS != "windows":       # symlinks need extra rights on Windows
        if cur["path"].lower().endswith(".appimage"):      # LocalSend.AppImage → LocalSend-1.18.2-x86_64.AppImage
            stable = os.path.join(target, re.sub(r"[^A-Za-z0-9]+", "", app["name"]) + ".AppImage")
            if stable != cur["path"]:
                run = _link(cur["path"], stable)
                rec["links"].append(stable)
        else:                                               # <app>/current → <app>/<version>
            link = _link(cur["path"], os.path.join(target, "current"))
            rec["links"].append(link)
            run = os.path.join(link, os.path.relpath(os.path.join(target, cur["exec"]), cur["path"]))
    # The sandbox launcher (17.4): when the app is sandboxed, the app-menu entry and the command link
    # point at ~/bin/apps/<app>/run, not the program itself, so every way AppKata starts it is sandboxed.
    launch_target = _sandbox_launcher(rec, app, portable, target, run) or run
    rec["exec"] = launch_target
    if target not in rec["files"]:
        rec["files"].insert(0, target)
    if rec.get("selfInstalled"):          # AppKata's own appkata.desktop points at the stable link (2.11.3.1)
        pass
    elif portable.app_menu:
        rec["files"].append(_desktop_entry(app_id, app["name"], launch_target, app.get("icon") or "", app.get("summary", ""),
                                           launcher=launch_target != run))
    if portable.command_dir:
        rec["links"].append(_link(launch_target, os.path.join(os.path.expanduser(portable.command_dir), app_id)))
    rec["options"] = {"appMenu": portable.app_menu, "commandLink": bool(portable.command_dir), "stableName": portable.stable_name}


def _sandbox_launcher(rec: dict, app: dict, portable: "Portable", target: str, prog: str) -> str:
    """Generate (or remove) the per-app sandbox launcher and return its path, or "" when the app runs
    Off (requirement 17.4, 17.7). The resolved grant set is `app["sandbox"]`, baked in by the backend;
    an absent/Off/unsupported sandbox leaves the program running directly, as before. Whether this
    system can sandbox is the backend's to decide: an app that has a launcher keeps it on a broken
    host (17.10; review 2, F16: a missing tool here removed it)."""
    app_id = app_id_of(rec, app)
    gs = app.get("sandbox")
    lp = sandbox.launcher_path(app_id, portable.root)
    if OS != "linux" or not gs or sandbox.level_of(gs) == "off":
        rec.pop("sandbox", None)
        rec.pop("launcher", None)
        if os.path.exists(lp):
            os.remove(lp)
        if OS == "linux":
            sandbox.remove_identity(app_id)        # the marker goes with the launcher (R10, round four R4-7)
        return ""
    appdir, exec_rel, appimage_path = _launcher_program(rec, target)
    launcher = sandbox.write_launcher(app_id, app["name"], portable.root, appdir, exec_rel, gs, appimage_path)
    if app.get("url"):
        sandbox.record_home_owner(app_id, app["url"])      # the home outlives an uninstall that keeps it (F19)
    rec["sandbox"] = sandbox.to_json(gs)
    rec["launcher"] = launcher
    return launcher


def _launcher_program(rec: dict, target: str) -> tuple[str, str, str | None]:
    """(appdir, program relative to it, the kept .AppImage or None) the launcher runs for the
    current version: an AppImage is extracted and run through AppRun (17.7), a tarball as it is."""
    cur = rec["current"]
    if cur["path"].lower().endswith(".appimage"):
        appdir = sandbox.extracted_dir(target, cur["version"])
        return appdir, sandbox.appimage_exec(appdir), cur["path"]
    return cur["path"], os.path.relpath(os.path.join(target, cur["exec"]), cur["path"]), None


def launcher_is_current(rec: dict, app: dict, portable: "Portable") -> bool:
    """Whether the launcher on disk is the one AppKata would write today for this app and grant
    set (`app["sandbox"]`). The launcher is the enforcement (17.4), and only an install, an update
    or a sandbox change rewrote it, so one written by an older AppKata -- before a launcher fix --
    kept running as written (round four, R4-4); the startup pass uses this to catch up, and it
    restores a hand-edited launcher the same way. False when there is no launcher or no grant set."""
    lp = rec.get("launcher")
    gs = app.get("sandbox")
    if not lp or not os.path.exists(lp) or not gs or not rec.get("current") or not rec.get("target"):
        return False
    appdir, exec_rel, appimage_path = _launcher_program(rec, rec["target"])
    want = sandbox.launcher_text(app_id_of(rec, app), app["name"], portable.root, appdir, exec_rel, gs, appimage_path)
    try:
        with open(lp) as f:
            if f.read() != want:
                return False
    except OSError:
        return False
    # ... and the files it calls by path: an older AppKata's shim or marker is as stale (review 2, F5)
    return sandbox.helpers_current(app_id_of(rec, app), gs)


def _activate_windows(rec: dict, app: dict, portable: "Portable", target: str) -> None:
    """Windows (requirement 15.5, 15.6): `current` is a directory junction, the app menu entry a
    Start-menu shortcut made once (for everyone, with administrator rights), the command link a .cmd."""
    from . import windows
    cur, app_id = rec["current"], app_id_of(rec, app)
    for l in rec.get("links", []):
        windows.remove_link(l)
    rec["links"] = []
    run = os.path.join(target, cur["exec"])
    if portable.stable_name and os.path.isdir(cur["path"]):
        link = os.path.join(target, "current")
        windows.make_junction(cur["path"], link)
        rec["links"].append(link)
        run = os.path.join(link, os.path.relpath(os.path.join(target, cur["exec"]), cur["path"]))
    rec["exec"] = run
    if target not in rec.setdefault("files", []):
        rec["files"].insert(0, target)
    want = []
    if portable.app_menu:
        lnk = os.path.join(windows.start_menu(portable.scope), windows.safe_name(app["name"]) + ".lnk")
        elevated = portable.scope == "everyone"
        old = next((x for x in rec.get("shortcuts", []) if x["path"] == lnk), None)
        if not old or old.get("target") != run or not os.path.exists(lnk):
            try:
                windows.make_shortcut(lnk, run, elevate=elevated, description=app.get("summary", ""))
            except OSError as e:
                raise InstallError(f"couldn't add the Start-menu shortcut: {e}") from None
        want.append({"path": lnk, "elevated": elevated, "target": run})
    for x in rec.get("shortcuts", []):
        if x["path"] not in [w["path"] for w in want]:
            windows.remove_shortcut(x["path"], x.get("elevated", False))
    rec["shortcuts"] = want
    shims = []
    if portable.command_dir:
        try:
            shims.append(windows.write_shim(os.path.expandvars(os.path.expanduser(portable.command_dir)), app_id, run))
        except FileExistsError as e:
            raise InstallError(str(e)) from None
    for old in rec.get("shims", []):
        if old not in shims:
            windows.remove_shim(old)
    rec["shims"] = shims
    rec["options"] = {"appMenu": portable.app_menu, "commandLink": bool(portable.command_dir), "stableName": portable.stable_name}


def _secure_target(portable: "Portable", target: str) -> None:
    """Apps for everyone live in folders only their owner and administrators can change (15.4.3)."""
    if OS != "windows" or portable.scope != "everyone":
        return
    from . import windows
    try:
        windows.secure_folder(portable.root, root=True)
        windows.secure_folder(target, root=False)
    except (PermissionError, OSError) as e:
        raise InstallError(str(e)) from None


def _run_installer(app: dict, file: str, kind: str, exe_kind: str, portable: "Portable", prev: dict, tmpdir: str) -> dict:
    """Run a Windows installer for the app's scope, and find the Uninstall entry it made (15.7, 15.8)."""
    from . import windows
    scope = portable.scope if portable.scope in windows.scopes(kind, exe_kind) else "me"
    msi_log = os.path.join(tmpdir, "msi.log") if kind == "msi" else ""
    prog, args, elevate = windows.installer_command(kind, exe_kind, file, scope, msi_log)
    before = windows.uninstall_entries()
    try:
        code = windows.shell_execute(prog, args, elevate=elevate, cwd=os.path.dirname(file))
    except (OSError, TimeoutError) as e:
        raise InstallError(f"couldn't run the installer: {e}") from None
    meaning = windows.exit_meaning(code)
    if meaning == "cancelled":
        raise Cancelled()
    if meaning == "busy":
        raise InstallError("another installation is running. Try again when it's finished")
    if meaning == "failed":
        if msi_log and os.path.exists(msi_log):
            with open(msi_log, encoding="utf-16", errors="replace") as f:
                log.warning("msiexec log (end):\n%s", "".join(f.readlines()[-40:]))
        raise InstallError(f"the installer exited with code {code}")
    entry = windows.changed_entry(before, windows.uninstall_entries(), [app["name"], app.get("repo", "").rsplit("/", 1)[-1]])
    entry = entry or prev.get("entry")
    rec = {"installer": exe_kind if kind == "exe" else "msi", "entry": entry, "restart": meaning == "restart"}
    if entry:
        rec["scope"] = "everyone" if entry["hive"] == "HKLM" else "me"
        rec["reported"] = str(entry.get("DisplayVersion") or "")
    else:
        log.warning("%s: no Uninstall entry appeared; AppKata can't uninstall it", app["name"])
    return rec

def _retain(rec: dict, keep: int) -> None:
    """Keep up to `keep` older versions (requirement 4.3.1.5); remove the rest."""
    kept, out = rec.get("kept", []), []
    seen = {rec["current"]["path"]}
    for k in kept:
        if k["path"] in seen or not os.path.lexists(k["path"]):
            continue
        seen.add(k["path"])
        if len(out) < max(0, keep):
            out.append(k)
        elif not k.get("external"):         # never delete a file AppKata adopted rather than placed
            _remove_path(k["path"])
            _remove_extracted(k)            # its sandboxed-AppImage cache, if any (17.7)
    rec["kept"] = out


def _remove_extracted(k: dict) -> None:
    """Drop a kept AppImage version's derived extraction cache (17.7)."""
    if k.get("path", "").lower().endswith(".appimage"):
        cache = sandbox.extracted_dir(os.path.dirname(k["path"]), k.get("version", ""))
        for p in (cache, cache + ".stamp", cache + ".lock"):
            _remove_path(p)


def _remove_path(path: str) -> None:
    if os.path.isdir(path) and not os.path.islink(path):
        shutil.rmtree(path, ignore_errors=True)
    elif os.path.lexists(path):
        os.remove(path)


def install(db: DB, app: dict, asset: Asset, kind: str, assets: list[Asset], progress=None, cancel=None,
            portable: Portable | None = None, phase=None) -> dict:
    """Install one app's chosen asset. Returns the install record (also stored). `phase(name)` is
    told "Verifying" and "Installing" after the download (requirement 4.8.1). An app that updates
    itself (app["autoUpdate"], requirement 4.10) goes into its folder without a version number."""
    portable = portable or Portable()
    if app.get("foreign"):
        raise InstallError("installed outside AppKata; uninstall that copy first")   # requirement 4.5.3
    rel_version = app.get("installVersion") or app.get("updateTo") or app.get("version", "")
    prev_row = db.one("SELECT record FROM installs WHERE url=?", (app["url"],))
    prev = json.loads(prev_row["record"] or "{}") if prev_row else {}
    # the install's own id (R6-1): kept across updates, unique among installs for a fresh one
    app_id = prev.get("id") or (app_id_of(prev, app) if prev.get("current") else new_app_id(db, app["url"], app["name"]))
    moving_from = {}
    if OS == "windows" and prev and prev.get("scope", "me") != portable.scope and not app.get("selfSetup"):
        moving_from, prev = prev, {}        # for someone else now: install afresh, then remove the old copy (15.4.1)
        check_not_running(moving_from.get("target", ""), app["name"])
    tmpdir = os.path.join(downloads_dir(), app_id)          # kept when a download breaks, to resume it
    os.makedirs(tmpdir, exist_ok=True)
    check_not_running(prev.get("target", ""), app["name"])
    ok = keep = False
    signer = ""
    try:
        file = os.path.join(tmpdir, asset.name)
        log.info("downloading %s", asset.url)
        got = download(asset.url, file, progress, cancel)
        log.info("downloaded %s (%d bytes, sha256 %s)", asset.name, os.path.getsize(file), got)
        if phase:
            phase("Verifying")
        want, how = expected_sha256(asset, assets)
        if want and got != want:
            raise InstallError(f"the download doesn't match its checksum ({how}); nothing was installed")
        verified = "checksum" if want else "unverified"
        if OS == "windows":
            from . import windows
            if portable.motw:            # requirement 15.11.1
                windows.mark_of_web(file, asset.url)
            if kind in ("exe", "msi", "msix"):          # Authenticode (requirement 15.11)
                status, who = windows.authenticode(file)
                verdict = windows.signature_verdict(status)
                if verdict == "bad":
                    raise InstallError("the file's digital signature doesn't match it (it was changed after it was "
                                       "signed); nothing was installed")
                if verdict == "signed":
                    verified, signer = "signed", who
        if cancel and cancel():
            raise Cancelled()
        if app.get("selfSetup") and OS == "windows" and kind == "exe":
            # AppKata's own setup runs when the user restarts AppKata (requirement 2.11.5)
            from .platform import data_dir
            updates = os.path.join(data_dir(), "updates")
            os.makedirs(updates, exist_ok=True)
            for old in os.listdir(updates):
                os.remove(os.path.join(updates, old))
            pending = os.path.join(updates, asset.name)
            shutil.move(file, pending)
            rec = {**prev, "pendingSetup": pending, "verified": verified, "signer": signer}
            db.x("""INSERT OR REPLACE INTO installs(url, name, version, date, asset, kind, record, installed_at)
                    VALUES(?,?,?,?,?,?,?,?)""",
                 (app["url"], app["name"], rel_version, app.get("date", ""), asset.name, kind, json.dumps(rec), now()))
            ok = True
            return rec
        if phase:
            phase("Installing")
        if moving_from.get("installer") and kind in ("exe", "msi"):
            _uninstall_windows(app["name"], moving_from)
        rec: dict = {"id": app_id, "files": [], "links": [], "verified": verified, "checksum_source": how, "root": portable.root,
                     **({"selfInstalled": True} if prev.get("selfInstalled") else {}),
                     "signer": signer, "motw": portable.motw}
        if OS == "windows":
            rec["scope"] = portable.scope
        portable_kind = kind in ("appimage", "tarball", "zip") or (kind == "exe" and app.get("exeKind") == "portable")
        if portable_kind and app.get("autoUpdate"):
            # it replaces its own files, so no version folders, kept versions or current link (requirement 4.10.2)
            target = prev.get("target") if prev.get("current") else os.path.join(portable.root, app_id)
            check_not_running(target, app["name"])
            _secure_target(portable, target)
            for old in [prev.get("current")] + prev.get("kept", []) if prev.get("current") else []:
                if old and not old.get("external"):
                    _remove_path(old["path"])
            rec.update(target=target, files=prev.get("files", []), links=prev.get("links", []), kept=[], selfUpdating=True)
            rec["current"] = _place(kind, file, app, target, rel_version, asset.name, fixed=True)
            if OS == "windows" and portable.motw:
                windows.mark_tree(rec["current"]["path"], asset.url)
            if OS == "windows":
                rec["msvcrt"] = windows.needs_msvcrt(rec["current"]["path"])
            portable = _apply_kind(rec, app, portable, kind, target, prev)
            _activate(rec, app, replace(portable, stable_name=False, keep=0), target)
        elif portable_kind:
            # a portable app keeps its versions side by side in its own folder (requirement 4.3.1)
            target = prev.get("target") if prev.get("current") else os.path.join(portable.root, app_id)
            check_not_running(target, app["name"])
            _secure_target(portable, target)
            if prev.get("selfUpdating") and prev.get("current"):
                prev = {**prev, "current": _leave_fixed_layout(prev["current"], target)}
            rec.update(target=target, links=prev.get("links", []), files=prev.get("files", []),
                       shortcuts=prev.get("shortcuts", []), shims=prev.get("shims", []),
                       kept=([prev["current"]] if prev.get("current") else []) + prev.get("kept", []))
            rec["current"] = _place(kind, file, app, target, rel_version, asset.name)
            if OS == "windows" and portable.motw:
                windows.mark_tree(rec["current"]["path"], asset.url)
            if OS == "windows":           # requirement 15.18
                rec["msvcrt"] = windows.needs_msvcrt(rec["current"]["path"])
            portable = _apply_kind(rec, app, portable, kind, target, prev)
            _activate(rec, app, portable, target)
            _retain(rec, portable.keep)
        elif kind in ("exe", "msi") and OS == "windows":     # an installer (requirement 15.7)
            rec.update(_run_installer(app, file, kind, app.get("exeKind") or "unknown", portable, prev, tmpdir))
        elif kind == "msix" and OS == "windows":            # requirement 15.7.4
            from . import windows
            try:
                rec.update(msix=windows.msix_install(file), scope="me")
            except OSError as e:
                raise InstallError(f"Windows couldn't install the package: {e}") from None
        elif kind in ("exe", "msi"):
            raise InstallError("installers run only on Windows")
        elif kind == "flatpak":
            p = applog.run(["flatpak", "install", "--user", "-y", "--noninteractive", file])
            if p.returncode:
                raise InstallError(p.stderr.strip().splitlines()[-1] if p.stderr.strip() else "flatpak install failed")
            m = re.search(r"Installing\s+\d+/\d+…?\s+(\S+)|(\w+(?:\.\w+){2,})", p.stdout + p.stderr)
            rec["flatpak"] = m.group(1) or m.group(2) if m else ""
        elif kind in ("deb", "rpm"):
            # through the package backend, dry run first (requirement 16.3.5, 16.8)
            if kind == "deb":
                pkg = subprocess.run(["dpkg-deb", "-f", file, "Package"], capture_output=True, text=True).stdout.strip()
            else:
                pkg = subprocess.run(["rpm", "-qp", "--qf", "%{NAME}", file], capture_output=True, text=True).stdout.strip()
            be = pkgbackend.backend()
            _apply(be, "install", [os.path.abspath(file)], app.get("confirmed", False), progress, cancel,
                   app.get("onWait"))
            rec["package"], rec["manager"] = pkg, be.manager
        else:
            raise InstallError(f"installing {kind} files isn't supported on {OS} yet")
        if moving_from and not moving_from.get("installer"):
            _remove_portable_windows(moving_from, app["name"])
        log.info("installed %s %s as %s", app["name"], rel_version, kind)
        db.x("""INSERT OR REPLACE INTO installs(url, name, version, date, asset, kind, record, installed_at)
                VALUES(?,?,?,?,?,?,?,?)""",
             (app["url"], app["name"], rel_version, app.get("date", ""), asset.name, kind, json.dumps(rec), now()))
        ok = True
        return rec
    except Cancelled:
        ok = True                               # download() already removed the partial file
        raise
    except NeedsConfirmation:
        keep = True                             # the user is asked; Install again uses the same file
        raise
    finally:
        if ok:
            shutil.rmtree(tmpdir, ignore_errors=True)
        elif keep:
            pass
        elif os.path.exists(os.path.join(tmpdir, asset.name)):
            os.remove(os.path.join(tmpdir, asset.name))      # complete but bad (checksum, install): don't resume it


def kept_versions(db: DB, url: str) -> list[str]:
    row = db.one("SELECT record FROM installs WHERE url=?", (url,))
    rec = json.loads(row["record"] or "{}") if row else {}
    return [k["version"] for k in rec.get("kept", []) if os.path.lexists(k["path"])]


def switch_to(db: DB, app: dict, version: str, portable: "Portable", date: str = "") -> dict:
    """Make a kept older version current again, without downloading (requirement 4.3.1.5)."""
    row = db.one("SELECT * FROM installs WHERE url=?", (app["url"],))
    rec = json.loads(row["record"] or "{}")
    k = next((x for x in rec.get("kept", []) if x["version"] == version), None)
    if not k or not os.path.lexists(k["path"]):
        raise InstallError(f"{version} isn't kept")
    check_not_running(rec.get("target", ""), app["name"])
    rec["kept"] = [rec["current"]] + [x for x in rec["kept"] if x is not k]
    rec["current"] = k
    _activate(rec, app, portable, rec["target"])
    _retain(rec, max(portable.keep, len(rec["kept"])))
    db.x("UPDATE installs SET version=?, date=?, record=?, installed_at=? WHERE url=?",
         (version, date or row["date"], json.dumps(rec), now(), app["url"]))
    return rec


def rewrite_launcher(db: DB, app: dict, portable: "Portable") -> dict:
    """Regenerate ~/bin/apps/<app>/run for the current version and grant set, without reinstalling
    (requirement 17.4): used when the user changes an installed app's sandbox. `app["sandbox"]` is the
    resolved grant set (or None/Off to drop the launcher)."""
    row = db.one("SELECT * FROM installs WHERE url=?", (app["url"],))
    if not row:
        return {}
    rec = json.loads(row["record"] or "{}")
    if not rec.get("current") or OS != "linux":
        return rec
    _activate(rec, app, portable, rec["target"])
    db.x("UPDATE installs SET record=? WHERE url=?", (json.dumps(rec), app["url"]))
    return rec


def remove_version(db: DB, url: str, version: str) -> None:
    row = db.one("SELECT record FROM installs WHERE url=?", (url,))
    rec = json.loads(row["record"] or "{}")
    for k in [x for x in rec.get("kept", []) if x["version"] == version]:
        check_not_running(k["path"] if os.path.isdir(k["path"]) else "", version)
        _remove_path(k["path"])
        _remove_extracted(k)
        rec["kept"].remove(k)
    db.x("UPDATE installs SET record=? WHERE url=?", (json.dumps(rec), url))


def uninstall(db: DB, url: str, confirmed: bool = False, progress=None, cancel=None, on_wait=None,
              remove_sandbox: bool = False) -> None:
    """Reverse what install recorded (requirement 4.7). User data in the home folder is kept. A
    package whose removal takes other packages with it raises NeedsConfirmation unless `confirmed`.
    `remove_sandbox`: also delete the app's private sandbox home (17.14)."""
    row = db.one("SELECT * FROM installs WHERE url=?", (url,))
    if not row:
        return
    rec = json.loads(row["record"] or "{}")
    if rec.get("package"):
        # a dry run first: anything else it would remove is shown first, and some removals are refused
        # (requirement 16.4.3)
        why = uninstall_blocker(rec)
        if why:
            raise InstallError(why)
        if pkgbackend.installed_version(rec["package"], rec.get("manager")):
            _apply(pkgbackend.backend(), "remove", [rec["package"]], confirmed, progress, cancel, on_wait)
    if rec.get("msix"):
        from . import windows
        try:
            windows.msix_remove(rec["msix"])
        except OSError as e:
            raise InstallError(f"Windows couldn't remove the package: {e}") from None
    elif rec.get("installer"):
        _uninstall_windows(row["name"], rec)
    if OS == "windows" and rec.get("target"):
        _remove_portable_windows(rec, row["name"])
    if rec.get("flatpak"):
        try:
            flatpak.uninstall(rec["flatpak"], system=rec.get("installation") == "system")
        except flatpak.FlatpakError as e:
            raise InstallError(str(e)) from None
    for l in rec.get("links", []):
        if os.path.islink(l):
            os.remove(l)
    root = os.path.realpath(rec.get("root") or apps_dir())
    for f in rec.get("files", []):
        if os.path.isdir(f) and os.path.realpath(f).startswith(root + os.sep):
            shutil.rmtree(f, ignore_errors=True)
        elif os.path.isfile(f) and os.path.basename(f).startswith("appkata-"):
            os.remove(f)
    db.x("DELETE FROM installs WHERE url=?", (url,))
    if OS == "linux":                           # only once the app itself is gone, not before a step can fail
        app_id = app_id_of(rec, {"name": row["name"]})
        sandbox.remove_identity(app_id)          # goes with the launcher; the home may stay (17.14)
        if remove_sandbox:
            sandbox.remove_sandbox_home(app_id)


def install_msvcrt() -> str:
    """Download Microsoft's Visual C++ run-time, check it's signed by Microsoft, and install it for
    everyone (requirement 15.18.3). Returns "ok" or "restart"."""
    from . import windows
    folder = downloads_dir()
    os.makedirs(folder, exist_ok=True)
    file = os.path.join(folder, "vc_redist.x64.exe")
    try:
        download(windows.VC_REDIST_URL, file)
        status, signer = windows.authenticode(file)
        if status != "Valid" or signer != "Microsoft Corporation":
            raise InstallError("the Visual C++ run-time download isn't signed by Microsoft; nothing was installed")
        try:
            code = windows.shell_execute(file, "/install /quiet /norestart", elevate=True)
        except (OSError, TimeoutError) as e:
            raise InstallError(f"couldn't run the Visual C++ run-time installer: {e}") from None
        meaning = windows.exit_meaning(code)
        if meaning == "cancelled":
            raise Cancelled()
        if meaning == "busy":
            raise InstallError("another installation is running. Try again when it's finished")
        if meaning == "failed":
            raise InstallError(f"the Visual C++ run-time installer exited with code {code}")
        log.info("installed the Visual C++ run-time (%s)", windows.msvcrt_installed() or "?")
        return meaning
    finally:
        if os.path.exists(file):
            os.remove(file)


def _remove_portable_windows(rec: dict, name: str) -> None:
    """A portable app's shortcut, command link, junction and folder (requirement 4.3.1.4, 15.5, 15.6)."""
    from . import windows
    check_not_running(rec.get("target", ""), name)
    for x in rec.get("shortcuts", []):
        windows.remove_shortcut(x["path"], x.get("elevated", False))
    for x in rec.get("shims", []):
        windows.remove_shim(x)
    for l in rec.get("links", []):
        windows.remove_link(l)
    rec["shortcuts"], rec["shims"], rec["links"] = [], [], []
    root = os.path.realpath(rec.get("root") or apps_dir())
    t = rec.get("target", "")
    if t and os.path.isdir(t) and os.path.realpath(t).startswith(root + os.sep):
        shutil.rmtree(windows.long_path(t), ignore_errors=True)


def _uninstall_windows(name: str, rec: dict) -> None:
    """Run the uninstaller recorded from the app's Uninstall entry (requirement 15.8.2)."""
    from . import windows
    entry = rec.get("entry")
    if OS != "windows" or not entry:
        raise InstallError(f"AppKata doesn't know how to uninstall {name}; uninstall it from Windows Settings → Apps")
    prog, args, elevate = windows.uninstall_command(entry, rec.get("installer", ""))
    if not prog:
        raise InstallError(f"{name}'s Uninstall entry has no uninstall command; uninstall it from Windows Settings → Apps")
    try:
        code = windows.shell_execute(prog, args, elevate=elevate)
    except (OSError, TimeoutError) as e:
        raise InstallError(f"couldn't run the uninstaller: {e}") from None
    meaning = windows.exit_meaning(code)
    if meaning == "cancelled":
        raise Cancelled()
    if meaning == "failed":
        raise InstallError(f"the uninstaller exited with code {code}")
    eid = windows.entry_id(entry)
    for _ in range(60):             # NSIS uninstallers finish from a copy of themselves
        if eid not in windows.uninstall_entries():
            return
        time.sleep(1)
    raise InstallError(f"{name} is still listed in Windows Settings → Apps after its uninstaller ran")


def launch(db: DB, url: str, on_failed=None, grace: float = applog.GRACE):
    """Start the installed app. Its output goes to logs/apps/<id>.log (appended; the generated
    launcher writes there itself when started from the menu, so every way of starting the app leaves
    the same trace), its last lines into the App log when it exits, and `on_failed(code, last_lines)`
    is called when it fails to start (requirement 14.2, :func:`applog.watch`): a sandboxed launch can
    fail before the app runs — bwrap refused, the AppImage didn't unpack, a CLI tool refused its
    folder — and the user should see why rather than nothing happening. Returns the watching thread
    for a portable app (tests join it), else None."""
    row = db.one("SELECT * FROM installs WHERE url=?", (url,))
    if not row:
        raise InstallError("not installed")
    rec = json.loads(row["record"] or "{}")
    if OS == "windows":
        return _launch_windows(row["name"], rec)
    if rec.get("exec"):
        logfile, out = applog.open_app_log(app_id_of(rec, {"name": row["name"]}), row["name"])
        with out:
            since = out.tell()
            p = subprocess.Popen([rec["exec"]], start_new_session=True, stdin=subprocess.DEVNULL,
                                 stdout=out, stderr=subprocess.STDOUT)
        return applog.watch(p, row["name"], logfile, on_failed, grace, since=since, launcher=bool(rec.get("launcher")))
    elif rec.get("flatpak"):
        subprocess.Popen(["flatpak", "run", rec["flatpak"]], start_new_session=True)
    elif rec.get("package"):
        exe = shutil.which(rec["package"])
        if not exe:
            raise InstallError(f"couldn't find a program called {rec['package']}")
        subprocess.Popen([exe], start_new_session=True)


def _launch_windows(name: str, rec: dict) -> None:
    from . import windows
    try:
        if rec.get("exec"):
            windows.launch(rec["exec"], through_shell=bool(rec.get("motw")))
            return
        if rec.get("msix"):
            windows.powershell("$p=Get-AppxPackage | ? PackageFullName -eq $env:AK_N | Select -First 1;"
                               "$id=@((Get-AppxPackageManifest $p).Package.Applications.Application)[0].Id;"
                               "Start-Process ('shell:AppsFolder\\' + $p.PackageFamilyName + '!' + $id)", {"AK_N": rec["msix"]})
            return
        icon = ((rec.get("entry") or {}).get("DisplayIcon") or "").split(",")[0].strip('"')
        if icon.lower().endswith(".exe") and os.path.isfile(icon) and not re.search(r"unins|uninstall", icon, re.I):
            windows.launch(icon)
            return
    except OSError as e:
        raise InstallError(f"couldn't start {name}: {e}") from None
    raise InstallError(f"open {name} from the Start menu")


# ---------------------------------------------------------------- package channels (requirement 16)
class NeedsFlathub(InstallError):
    """The Flathub remote isn't configured for this user: ask "Add Flathub?" first (16.3.4)."""
    def __init__(self):
        super().__init__("Flathub isn't set up on this computer")


def _apply(be, action: str, names: list[str], confirmed: bool, progress, cancel, on_wait) -> None:
    try:
        be.apply(action, names, confirmed=confirmed, progress=progress, cancel=cancel, on_wait=on_wait)
    except NeedsConfirmation:
        raise
    except PackageError as e:
        raise InstallError(str(e)) from None


def uninstall_blocker(rec: dict) -> str:
    """Why a package can't be uninstalled from AppKata, or "" (requirement 16.4.3)."""
    if not rec.get("package") or not pkgbackend.installed_version(rec["package"], rec.get("manager")):
        return ""
    be = pkgbackend.backend()
    facts = be.facts([rec["package"]])
    if rec["package"] in facts.auto or rec.get("wasAuto"):
        return "Other software on this computer needs it"
    if facts.blocked([rec["package"]]):
        return "This computer needs it"
    return ""


def _distro() -> str:
    from .channels import distro_name
    return distro_name()


def install_channel(db: DB, app: dict, option: dict, progress=None, cancel=None, phase=None, on_wait=None,
                    confirmed: bool = False, add_flathub: bool = False) -> dict:
    """Install from a Flatpak remote or the distribution's repositories (requirement 16.3.4, 16.3.5).
    `option` is a card from channels.options(). Returns the install record (also stored)."""
    from . import channels
    if app.get("foreign"):
        raise InstallError("installed outside AppKata; adopt or uninstall that copy first")   # 4.5.3, 16.4.2
    if phase:
        phase("Installing")
    if option["channel"] == "flatpak":
        remote = option.get("remote") or flatpak.FLATHUB
        if not flatpak.has_remote(remote):
            if remote != flatpak.FLATHUB or not add_flathub:
                raise NeedsFlathub()
            flatpak.add_flathub()
        meta = flatpak.metadata(option["value"], remote)
        try:
            got = flatpak.install(option["value"], remote, progress, cancel)
        except flatpak.FlatpakError as e:
            raise InstallError(str(e)) from None
        rec = {"channel": "flatpak", "flatpak": got.app_id, "remote": remote, "commit": got.commit,
               "installation": "user", "branch": got.branch, "verified": "signed", "signer": remote.capitalize(),
               "perms": flatpak.permissions(meta), "extraData": flatpak.extra_data_host(meta)}
        raw, kind, asset = got.version, "flatpak", f"{remote} {got.app_id}"
        version = channels.project_version("flatpak", got.version) or got.version
    elif option["channel"] == "package":
        be = pkgbackend.backend()
        name = option["value"]
        _apply(be, "install", [name], confirmed, progress, cancel, on_wait)
        raw = pkgbackend.installed_version(name, be.manager)
        rec = {"channel": "package", "package": name, "manager": be.manager, "verified": "signed",
               "signer": _distro(), "pkgVersion": raw, "origin": option.get("origin", "")}
        kind, asset = be.manager, name
        version = channels.project_version(be.manager, raw)
    else:
        raise InstallError(f"unknown channel {option.get('channel')}")
    db.x("""INSERT OR REPLACE INTO installs(url, name, version, date, asset, kind, record, installed_at)
            VALUES(?,?,?,?,?,?,?,?)""", (app["url"], app["name"], version, "", asset, kind, json.dumps(rec), now()))
    log.info("installed %s %s from %s", app["name"], raw, option["channel"])
    return rec


def update_channel(db: DB, url: str, progress=None, cancel=None, on_wait=None, confirmed: bool = False,
                   commit: str = "") -> dict:
    """Update a channel install (requirement 16.5.5); a Flatpak `commit` installs that older build and
    pins it (16.5.7)."""
    from . import channels
    row = db.one("SELECT * FROM installs WHERE url=?", (url,))
    if not row:
        raise InstallError("not installed")
    rec = json.loads(row["record"] or "{}")
    system = rec.get("installation") == "system"
    if rec.get("channel") == "flatpak":
        old = rec.get("perms") or []
        try:
            inf = flatpak.update(rec["flatpak"], system, commit, progress, cancel)
            if commit:
                flatpak.mask(rec["flatpak"], system)
        except flatpak.FlatpakError as e:
            raise InstallError(str(e)) from None
        rec["commit"] = inf.get("commit", rec.get("commit", ""))
        rec["perms"] = flatpak.permissions(flatpak.installed_metadata(rec["flatpak"], system)) or old
        raw = inf.get("version", "")
        version = channels.project_version("flatpak", raw) or row["version"]
    elif rec.get("channel") == "package":
        be = pkgbackend.backend()
        _apply(be, "upgrade", [rec["package"]], confirmed, progress, cancel, on_wait)
        raw = pkgbackend.installed_version(rec["package"], rec.get("manager"))
        rec["pkgVersion"] = raw
        version = channels.project_version(rec.get("manager", ""), raw)
    else:
        raise InstallError("not installed from a channel")
    rec.pop("pending", None)
    db.x("UPDATE installs SET version=?, record=?, installed_at=? WHERE url=?", (version, json.dumps(rec), now(), url))
    return rec


def set_pinned(db: DB, url: str, pinned: bool) -> None:
    """A Flatpak is pinned with flatpak mask, which stops every updater (16.5.6); packages can't be."""
    row = db.one("SELECT record FROM installs WHERE url=?", (url,))
    rec = json.loads(row["record"] or "{}") if row else {}
    if rec.get("channel") == "package":
        raise InstallError("packages can't be pinned from AppKata; that would change the whole system")
    if rec.get("channel") == "flatpak":
        try:
            (flatpak.mask if pinned else flatpak.unmask)(rec["flatpak"], rec.get("installation") == "system")
        except flatpak.FlatpakError as e:
            raise InstallError(str(e)) from None


def set_update_owner(db: DB, url: str, owner: str) -> None:
    """Install options → Updates: "system" or "appkata" (16.5.3)."""
    row = db.one("SELECT record FROM installs WHERE url=?", (url,))
    if not row:
        return
    rec = json.loads(row["record"] or "{}")
    rec["updates"] = owner
    db.x("UPDATE installs SET record=? WHERE url=?", (json.dumps(rec), url))
