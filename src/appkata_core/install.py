"""Installing, updating and uninstalling (R4): AppImage, tarball, Flatpak bundle, .deb
and .rpm on Linux; portable .zip and .exe, installers (.msi, .exe) and .msix on Windows (R15).
macOS installers follow."""

from __future__ import annotations

import configparser
import hashlib
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import tarfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, replace
from functools import partial

import logging
import threading

from . import applog, appkind, flatpak, pkgbackend, sandbox
from .pkgbackend import NeedsConfirmation, PackageError
from .assets import checksum_for
from .db import DB, now
from .forges import Asset
from .http import UA
from .platform import OS, apps_dir, data_dir, desktop_dir


log = logging.getLogger("appkata.install")


class InstallError(Exception):
    pass


class Cancelled(InstallError):
    def __init__(self):
        super().__init__("cancelled")


class InUse(InstallError):
    """Windows can't replace a running program's files (R15.9)."""
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
    """Stop before touching a folder that a running program comes from (R15.9)."""
    if OS != "windows" or not folder or not os.path.isdir(folder):
        return
    from . import windows
    if procs := windows.processes_in(folder):
        raise InUse(name, procs)


def downloads_dir() -> str:
    """Where partial downloads wait to be resumed (R4.8.2)."""
    from .platform import data_dir
    return os.path.join(data_dir(), "downloads")


def download(url: str, dest: str, progress=None, cancel=None, timeout: float = 60, retries: int = 3) -> str:
    """Download to dest through dest + ".part", resuming a broken or earlier download with a Range
    request when the server still has the same file (R4.8.2). Returns the SHA-256 hex
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
    """The first n bytes of a download (a Range request), to see what a .exe is (R4.2.1)."""
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Range": f"bytes=0-{n - 1}"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read(n)
    except OSError:
        return b""


def expected_sha256(asset: Asset, assets: list[Asset]) -> tuple[str, str]:
    """(hex, source) of the checksum to compare with: the forge digest, or a checksum file (R4.4)."""
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


_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f\u2028\u2029]")


def one_line(text: str) -> str:
    """Text someone else wrote (a project's name or summary, a review's), as one line: every control
    character and line separator becomes a space, and each run of whitespace one space. A value
    written into a line-based file, a menu entry above all, then can't end its line and start
    another (CR1.3-7: a summary's line break put the project's own `Exec=` into the entry)."""
    return " ".join(_CONTROL.sub(" ", text or "").split())


def desktop_value(text: str) -> str:
    """`text` as a string value of a desktop entry: one line, a backslash doubled (the Desktop Entry
    Specification's escapes: `\\s`, `\\n`, `\\t`, `\\r`, `\\\\`)."""
    return one_line(text).replace("\\", "\\\\")


def desktop_exec(exec_path: str, *words: str) -> str:
    """The value of `Exec=` that starts `exec_path` with AppKata's own `words` and the opened files
    (`%U`), written as the Desktop Entry Specification asks: the path in double quotes with `\\`, `$`
    and a backtick escaped, a `%` doubled, and then every backslash doubled again, as in any string
    value. A path with a quote or a control character (a line break) is refused with ValueError:
    no entry starts such a path, and nothing is written for it."""
    if '"' in exec_path or _CONTROL.search(exec_path):
        raise ValueError(f"{one_line(exec_path)!r} has a quote or a line break in it, which a menu entry can't start")
    quoted = re.sub(r"([\\$`])", r"\\\1", exec_path).replace("%", "%%")
    return " ".join([f'"{quoted}"', *words, "%U"]).replace("\\", "\\\\")


def _menu_exec(exec_path: str, *words: str) -> str:
    """:func:`desktop_exec`, as an install's step: a path no menu entry can start stops the install."""
    try:
        return desktop_exec(exec_path, *words)
    except ValueError as e:
        raise InstallError(f"couldn't add the app-menu entry: {e}") from None


def _menu_entry_path(app_id: str) -> str:
    return os.path.join(desktop_dir(), f"appkata-{app_id}.desktop")


def _menu_links_dir() -> str:
    """Where the links an app-menu entry starts are kept: AppKata's own folder (R4.3.1.1)."""
    return os.path.join(data_dir(), "menu")


def _menu_link_path(app_id: str) -> str:
    """The link an app's menu entry starts, to what the app runs (its stable name, program or sandbox
    launcher), named after the app's id (R4.3.1.1). The entry's `Exec=` holds this path, never one in
    the install folder: a `%` there, written `%%` as the Desktop Entry Specification asks, made GLib
    take the app for one that isn't installed -- it looks for the program before it reads `%%` as
    `%` -- and the app had no entry in the menus of Cinnamon, GNOME, MATE or Xfce (#685, the owner's
    decision: the entry starts the app through a link in AppKata's own folder, and nothing is
    refused). An id has no `%` (:func:`slug`)."""
    return os.path.join(_menu_links_dir(), app_id)


def _desktop_entry(app_id: str, name: str, exec_path: str, icon: str, summary: str, launcher: bool = False) -> str:
    """The app-menu entry, starting `exec_path` (an app's own: :func:`_menu_link_path`). For a sandbox
    launcher (`launcher=True`) Exec passes the word --appkata-menu first: started this way nothing
    shows stderr, so the launcher keeps its own in logs/apps/<id>.log, where a refused launch is then
    found (R14.2.1, R17.4).

    The name and the summary are the project's own text (its metainfo, its README, a review), and
    the path is AppKata's: each is written as one escaped line (:func:`desktop_value`,
    :func:`desktop_exec`), so the entry holds AppKata's keys and no other."""
    exec_value = _menu_exec(exec_path, *(["--appkata-menu"] if launcher else []))
    path = _menu_entry_path(app_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    icon = "" if _CONTROL.search(icon) else icon
    with open(path, "w") as f:
        f.write("[Desktop Entry]\nType=Application\n"
                f"Name={desktop_value(name) or app_id}\nComment={desktop_value(one_line(summary)[:120])}\nExec={exec_value}\n"
                + (f"Icon={desktop_value(icon)}\n" if icon else "") + "Categories=Utility;\nX-AppKata=true\n")
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


# what comes with a program and is never the program itself: Chromium's sandbox helper and crash
# handler (every Electron app has both beside its program), and `<program>-bin` beside `<program>`
_HELPER = re.compile(r"^chrome[-_]sandbox$|crashpad", re.I)


def _squash(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", name.lower())


def _exec_program(desktop: str) -> str:
    """The file name of the program a `.desktop` file's `Exec=` starts, "" when it can't be told: the
    first word that isn't `env` or one of its `NAME=value` words, without its folder (an archive's
    entry names its program as it would be installed: `codium`, `/usr/share/codium/codium`). The
    file is someone else's: nothing is read through a link, or of a file over 1 MB."""
    cp = configparser.ConfigParser(interpolation=None, strict=False)
    try:
        if os.path.islink(desktop) or os.path.getsize(desktop) > 1 << 20:
            return ""
        cp.read(desktop, encoding="utf-8")
        words = shlex.split(cp.get("Desktop Entry", "Exec", fallback=""))
    except (configparser.Error, OSError, UnicodeDecodeError, ValueError):
        return ""
    if words and os.path.basename(words[0]) == "env":
        words = words[1:]
        while words and re.match(r"[A-Za-z_][A-Za-z0-9_]*=", words[0]):
            words = words[1:]
    return os.path.basename(words[0]) if words else ""


def _is_elf(path: str) -> bool:
    try:
        with open(path, "rb") as f:
            return f.read(4) == b"\x7fELF"
    except OSError:
        return False


def _find_executable(root: str, names: list[str]) -> str:
    """The program of an unpacked archive (R4.3.1): what its links, its menu entry and its launcher
    start, and what its kind is read from. Among its executable files, in this order (CR1.3-17: by
    name alone, then depth and alphabet, VSCodium's program was `chrome-sandbox`):

    1. one the archive's own `.desktop` file starts (:func:`_exec_program`);
    2. by name: the app's or the repository's name, then a name that holds one of them, then a name
       one of them holds (`codium` in VSCodium), compared without case or punctuation;
    3. a compiled program (ELF) before a script;
    4. the one nearest the archive's top, then by alphabet.

    Never a shared library, a `.sh` or `.desktop` file, or a helper (:data:`_HELPER`)."""
    want = [w for w in map(_squash, names) if w]        # no name (an app with no repository) matches nothing
    found, started = [], set()
    for dp, dn, fn in os.walk(root):
        runs = []
        for f in fn:
            p = os.path.join(dp, f)
            if f.endswith(".desktop"):
                started.add(_exec_program(p))
                continue
            try:
                st = os.stat(p)
            except OSError:
                continue
            if not stat.S_ISREG(st.st_mode) or not (st.st_mode & stat.S_IXUSR) or f.endswith((".so", ".sh")) or ".so." in f:
                continue
            runs.append(f)
        found += [(f, os.path.join(dp, f)) for f in runs
                  if not (_HELPER.search(f) or (f.endswith("-bin") and f[:-4] in runs))]
    cands = []                                          # ranked once every .desktop file has been read
    for f, p in found:
        n = _squash(f)
        by_name = (0 if n in want else 1 if any(w in n for w in want)
                   else 2 if len(n) > 2 and any(n in w for w in want) else 3)
        cands.append((f not in started, by_name, p.count(os.sep), p))
    if not cands:
        raise InstallError("couldn't find the program in the archive")
    first = min(c[:2] for c in cands)                   # only the files that could be picked are opened
    return min((not _is_elf(c[3]), c[2], c[3]) for c in cands if c[:2] == first)[2]


def _folder(path: str) -> str:
    """A folder as Settings holds it (R11.1.4, what the user typed or picked), as the path it names:
    `~` and `$VARIABLES` (on Windows `%VARIABLES%` too) expanded, and absolute. The one reading
    of every such folder: the install folder was read this way and the command links folder with
    `~` alone, so one typed as `$HOME/bin` was a folder named `$HOME` under whatever AppKata's
    working directory was, and the link in it (CR1.3-32)."""
    return os.path.abspath(os.path.expandvars(os.path.expanduser(path)))


@dataclass
class Portable:
    """Where and how apps are installed (R4.3.1, R11.1.4, R15.4)."""
    folder: str = ""              # each app gets <folder>/<app>/ (default: platform.apps_dir())
    app_menu: bool = True         # add a .desktop entry / Start-menu shortcut
    stable_name: bool = True      # <App>.AppImage → the versioned file, so launchers survive updates
    command_dir: str = ""         # a folder on PATH for a command link per app ("" = none)
    keep: int = 2                 # older versions kept for a quick rollback
    scope: str = "me"             # Windows: "me" or "everyone" (R15.4)
    folder_everyone: str = ""     # Windows: where apps for everyone go (default C:\Programs)
    motw: bool = False            # Windows: Mark of the Web on downloads (R15.11.1)

    @property
    def root(self) -> str:
        if OS == "windows" and self.scope == "everyone":
            return _folder(self.folder_everyone) if self.folder_everyone else apps_dir("everyone")
        return _folder(self.folder) if self.folder else apps_dir()

    @property
    def command_folder(self) -> str:
        """The command links folder as a path (R4.3.1.3), or "" when the app gets no command link."""
        return _folder(self.command_dir) if self.command_dir else ""


def _where_it_is(rec: dict, portable: "Portable") -> "Portable":
    """`portable` for an app that is installed, `rec` being its record: its install folder is the
    one it was installed into, whatever Settings names now (R4.3.1: an installed app keeps its
    folder through its updates, and only a new install goes to the new one). Every step that
    reads the folder from the options -- the record's root, the launcher's place and the folder it
    protects, which links are AppKata's -- then means the folder the app is in. An update kept the
    files where they were and took the rest from Settings: the record's root became the new
    folder, so uninstalling left every version on disk, and a sandboxed app's launcher was written
    to <new folder>/<app>/run (CR1.3-12)."""
    root = rec.get("root") if rec.get("current") else ""
    return replace(portable, folder=root, folder_everyone=root) if root else portable


def _points_into(link: str, roots: tuple[str, ...]) -> bool:
    """Whether `link` is a symbolic link that leads into one of `roots`: a link AppKata made there
    (R4.3.1.3). One whose target is gone still counts, by where it led. This is the one test of
    "a link AppKata made", for a link it is about to replace and for one it is about to remove: a
    path in an install's record says where AppKata once made a link, not what is there today
    (CR1.3-11: the user's own link at a recorded path was removed by the next update, and by
    uninstalling)."""
    if not os.path.islink(link):
        return False
    dest = os.path.realpath(link) + os.sep
    return any(dest.startswith(os.path.realpath(r) + os.sep) for r in roots if r)


def _remove_links(links: list[str], own: tuple[str, ...]) -> None:
    """Remove the links an install's record names, each only while it is still a link AppKata made
    (:func:`_points_into` `own`, the install folders). Whatever else is at a recorded path now is
    the user's, and stays (R4.3.1.3, R4.7)."""
    for link in links:
        if _points_into(link, own):
            os.remove(link)


def _link_refusal(link: str, own: tuple[str, ...] | None = None) -> str:
    """Why :func:`_link` makes no link at `link`, or "": what is already there is replaced only when
    it is a link, and with `own` (the install folders: a command link's case, R4.3.1.3) only one
    that leads into them: the user's own `~/bin/tool -> /opt/tool` was replaced like any link
    (CR1.5-31)."""
    if os.path.lexists(link) and (not os.path.islink(link) or (own is not None and not _points_into(link, own))):
        return f"{link} exists and isn't a link AppKata made; not replacing it"
    return ""


def _link(target: str, link: str, own: tuple[str, ...] | None = None) -> str:
    """Point `link` at `target` (relative when they share a folder); returns the link path. Refused
    with an InstallError where :func:`_link_refusal` says why."""
    os.makedirs(os.path.dirname(link), exist_ok=True)
    if why := _link_refusal(link, own):
        raise InstallError(why)
    if os.path.islink(link):
        os.remove(link)
    rel = os.path.relpath(target, os.path.dirname(link)) if os.path.dirname(target) == os.path.dirname(link) else target
    os.symlink(rel, link)
    return link


# Names that never become a command link, whether or not this computer has such a command today
# (R4.3.1.3): a command link is named after an app, and its publisher picks the name. They are the
# commands a sandbox launcher runs by name (sandbox.HOST_COMMANDS), the ones AppKata itself runs by
# name (tests/test_install_review.py collects those from the code and holds them here: gio and
# gtk-launch, which Open on a system package runs, came in without, #689's review, P1-2), the shells
# and interpreters, and the commands that take a password or hold credentials, where a stand-in
# answering in the user's terminal does the most harm. One of them that isn't installed today may
# be tomorrow, and the link would then be ahead of it. The list is short on purpose: any other name
# is refused only while it is a command here (:func:`command_link_refusal`).
RESERVED_COMMANDS = frozenset(sandbox.HOST_COMMANDS) | frozenset((
    "git", "gpg", "pkexec", "flatpak", "snap", "apt", "apt-get", "apt-cache", "apt-config", "apt-mark", "dpkg", "dpkg-deb",
    "dpkg-query", "dnf", "rpm", "systemctl", "unshare", "xdg-open", "xdg-mime", "update-desktop-database", "gnome-software",
    "gio", "gtk-launch", "gsettings",
    "sh", "bash", "dash", "env", "python", "python3",
    "sudo", "su", "doas", "passwd", "ssh", "scp", "sftp", "ssh-add", "ssh-agent", "gpg2"))


def command_link_refusal(name: str, link: str, own: tuple[str, ...]) -> str:
    """Why AppKata makes no command link called `name` at `link` (R4.3.1.3), or "" when it may: the
    name is kept for the system's own commands (:data:`RESERVED_COMMANDS`), or it already is a
    command on this computer -- something on the PATH, or in the system's folders, answers to it. The
    app is then installed with its app-menu entry and no command, and the install says why (the
    owner's decision on CR1.5-31: the link put an app named python3, readlink or sudo first on the
    PATH, ahead of the real one). A link of AppKata's own at `link` (one leading into `own`, the
    install folders) doesn't count: that is this app's command from an earlier install. The folders
    after it are still looked in, so a command of that name further on the PATH is found while the
    app's own link is in place, first on it (AppKata's start asks this of a link it made,
    :func:`refresh_command_link`)."""
    if name in RESERVED_COMMANDS:
        return f"{name} is a name kept for the system's own command"
    folders = [d for d in os.environ.get("PATH", "").split(os.pathsep) + (sandbox.HOST_PATH + ":/usr/sbin:/sbin").split(":") if d]
    for folder in folders:
        found = shutil.which(name, path=folder)
        if found and not (os.path.realpath(os.path.dirname(found)) == os.path.realpath(os.path.dirname(link))
                          and os.path.basename(found) == os.path.basename(link) and _points_into(link, own)):
            return f"{name} is already a command on this computer ({found})"
    return ""


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
        dest = long_path(dest)          # deep archives (R15.16)
    with zipfile.ZipFile(file) as z:
        for m in z.infolist():          # no paths outside the folder
            if m.filename.startswith(("/", "\\")) or ".." in m.filename.replace("\\", "/").split("/"):
                raise InstallError(f"unsafe path in the archive: {m.filename}")
        for m in z.infolist():          # zipfile drops Unix permissions; keep the executable bit
            path = z.extract(m, dest)
            mode = (m.external_attr >> 16) & 0o777
            if mode and not m.is_dir():
                os.chmod(path, mode)


def _appimage_name(asset_name: str, version: str, versioned: bool = False) -> str:
    """The file name one version of an AppImage is kept under (R4.3.1): the release's own when it
    holds the version (`LocalSend-1.18.2-x86_64.AppImage`) or a version in a spelling of its own
    (a number with a dot in it: `Tool-26.11.AppImage` of the release 2026.11), else that name
    with the version added (`Tool-x86_64.AppImage` -> `Tool-x86_64-2.0.AppImage`). `versioned`
    adds it whatever the name holds: :func:`_place` asks for that when the name is another
    version's. Many projects release every version under one name, and each update then replaced
    the installed version's file with its own: nothing was kept to go back to (CR1.3-13)."""
    holds = version and re.search(rf"(?<![0-9])(?<![0-9]\.){re.escape(version)}(?!\.?[0-9])", asset_name)
    if not versioned and (holds or re.search(r"[0-9]\.[0-9]", asset_name)):
        return asset_name
    stem, ext = os.path.splitext(asset_name)
    return f"{stem}-{_safe(version)}{ext}"


def _aside(path: str) -> str:
    """Where :func:`_swap_in` keeps what was at `path` until the install has succeeded."""
    return path + ".old"


def _swap_in(staging: str, dest: str) -> None:
    """Put what was made at `staging` at `dest`. What is at `dest` already is the installed version
    -- an app that updates itself has one fixed name (R4.10.2), and a version installed again has
    its own -- and it is set aside (:func:`_aside`), not deleted: R4.6 keeps the previous version's
    files until the update succeeds. :func:`install` removes it once the record is stored, and
    :func:`_undo_portable` puts it back when a later step fails. A failure here puts it back at
    once (CR1.3-13: the installed version was deleted first, and the new one placed after)."""
    aside = _aside(dest)
    _remove_path(aside)                         # one that a crash left
    had = os.path.lexists(dest)
    if had:
        os.replace(dest, aside)
    try:
        os.replace(staging, dest)
    except BaseException:
        if had:
            os.replace(aside, dest)
        raise


def _place(kind: str, file: str, app: dict, target: str, version: str, asset_name: str, fixed: bool = False,
           others: tuple[str, ...] = ()) -> dict:
    """Put one version in the app's folder (R4.3.1): {version, path, exec} where path is
    the versioned file or folder and exec is relative to the app folder. `fixed`: an app that
    updates itself gets <App>.AppImage or an "app" folder instead (R4.10.2). `others`: where the
    app's other versions are, none of which this one may take the place of.

    All or nothing: the version is made beside its place and renamed into it (:func:`_swap_in`),
    so a download that can't be moved or unpacked leaves what is installed as it was."""
    os.makedirs(target, exist_ok=True)
    names = [app["name"], app.get("repo", "").rsplit("/", 1)[-1]]
    if kind == "appimage":
        dest = os.path.join(target, re.sub(r"[^A-Za-z0-9]+", "", app["name"]) + ".AppImage" if fixed
                            else _appimage_name(asset_name, version))
        if not fixed and dest in others:        # another version's own file, whatever the name seems to hold
            dest = os.path.join(target, _appimage_name(asset_name, version, versioned=True))
        staging = dest + ".new"
        _remove_path(staging)
        try:
            shutil.move(file, staging)
            os.chmod(staging, 0o755)
            _swap_in(staging, dest)
        except BaseException:
            _remove_path(staging)
            raise
        return {"version": version, "path": dest, "exec": os.path.basename(dest)}
    vdir = os.path.join(target, "app" if fixed else _safe(version))
    staging = vdir + ".new"
    shutil.rmtree(staging, ignore_errors=True)
    try:
        if kind == "exe":                      # a portable Windows program
            os.makedirs(staging)
            shutil.move(file, os.path.join(staging, re.sub(r"[^A-Za-z0-9]+", "", app["name"]) + ".exe"))
            exe = os.path.join(staging, re.sub(r"[^A-Za-z0-9]+", "", app["name"]) + ".exe")
        else:
            _extract(kind, file, staging)
            exe = _find_exe(staging, names) if OS == "windows" else _find_executable(staging, names)
        _swap_in(staging, vdir)
    except BaseException:                  # an archive that can't be unpacked, has no program or can't be put in
        _remove_tree(staging)              # place: nothing of it stays (CR1.3-15)
        raise
    return {"version": version, "path": vdir, "exec": os.path.relpath(exe.replace(staging, vdir, 1), target)}


def _apply_kind(rec: dict, app: dict, portable: "Portable", kind: str, target: str, prev: dict) -> "Portable":
    """The app's kind (R17.3.3), decided from the version just placed, before the launcher and the
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
    """The current version of an app that updated itself (R4.10.2: one fixed-name file or an `app`
    folder), renamed into the versioned layout as AppKata starts updating it -- because it now runs
    sandboxed and can't update itself (R17.12; review 2, F3). An AppImage's fixed name is exactly where
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


def _enter_fixed_layout(rec: dict, app: dict, portable: "Portable", target: str) -> tuple[list[dict], tuple[str, str, str]]:
    """The reverse of :func:`_leave_fixed_layout`: an app in version folders goes back to the
    fixed-name layout of R4.10.2 (one `<App>.AppImage`, or an `app` folder), as its sandbox is
    turned Off and it updates itself again (R4.10.5, R17.12; the owner's decision on CR1.11-41:
    nothing moved it back, so its own updater found version folders, a stable link and kept
    versions it knew nothing of). The current version is renamed to the fixed name and the record
    says so; `rec` is changed, nothing is stored. A kept version at that name (the `app` folder
    the app had before AppKata updated it) is set aside for it, as :func:`_swap_in` does.

    Returns what the caller removes once the record is stored (:func:`_forget`: the kept versions,
    where they are now), and (the fixed name, the name before, what was set aside or ""), to take
    back if a later step fails. Refused, before anything is changed, when something else is at the
    fixed name: neither a link AppKata made nor one of the app's own versions."""
    cur, kept, own = rec["current"], rec.get("kept", []), (portable.root, os.path.dirname(target))
    appimage = cur["path"].lower().endswith(".appimage") and not os.path.isdir(cur["path"])
    fixed = os.path.join(target, re.sub(r"[^A-Za-z0-9]+", "", app["name"]) + ".AppImage" if appimage else "app")
    aside = ""
    if fixed != cur["path"]:
        if os.path.lexists(fixed) and not _points_into(fixed, own) and fixed not in [k["path"] for k in kept]:
            raise InstallError(f"{fixed} is where the app's own file goes, and isn't AppKata's; not replacing it")
        _remove_links(rec.get("links", []), own)        # the stable link is exactly where an AppImage's fixed name is
        _swap_in(cur["path"], fixed)
        aside = _set_aside({"path": fixed})
    inner = os.path.relpath(os.path.join(target, cur["exec"]), cur["path"])        # the program, inside an unpacked archive
    rec.update(current={**cur, "path": fixed, "exec": os.path.normpath(os.path.join(os.path.basename(fixed), inner))},
               kept=[], selfUpdating=True)
    return [k for k in kept if k["path"] != fixed] + ([{"path": aside}] if aside else []), (fixed, cur["path"], aside)


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
    own = (portable.root, os.path.dirname(target))
    _remove_links(rec.get("links", []), own)      # the previous version's links
    rec["links"] = []
    # The app-menu entries the record names (AppKata's own, by name and folder) leave the record
    # here. One written below comes back into it; one that isn't -- the option was turned off, or
    # the new version is a command-line tool -- is removed there, not just forgotten: it stayed in
    # the desktop's menu, in no record, past uninstall (CR1.3-14).
    entries = [f for f in rec.get("files", []) if os.path.basename(f).startswith("appkata-")
               and os.path.dirname(f) == os.path.dirname(_menu_entry_path(app_id))]
    rec["files"] = [f for f in rec.get("files", []) if f not in entries]
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
    # The sandbox launcher (R17.4): when the app is sandboxed, the app-menu entry and the command link
    # point at ~/bin/apps/<app>/run, not the program itself, so every way AppKata starts it is sandboxed.
    launch_target = _sandbox_launcher(rec, app, portable, target, run) or run
    rec["exec"] = launch_target
    if target not in rec["files"]:
        rec["files"].insert(0, target)
    if rec.get("selfInstalled"):          # AppKata's own appkata.desktop points at the stable link (R2.11.3.1)
        pass
    elif portable.app_menu:               # the entry starts the app through a link in AppKata's own folder (#685)
        rec["links"].append(_link(launch_target, _menu_link_path(app_id)))
        rec["files"].append(_desktop_entry(app_id, app["name"], _menu_link_path(app_id), app.get("icon") or "",
                                           app.get("summary", ""), launcher=launch_target != run))
    for old in entries:
        if old not in rec["files"]:
            _remove_path(old)
    rec.pop("commandRefused", None)
    if portable.command_dir:
        # The command is named after the app, so its publisher picks the name: none is made for a name
        # that is already a command here, or a reserved one, and the record says why (R4.3.1.3). The
        # option stays as chosen, so the command comes once the name is free. Never an error: the
        # app is installed either way, with its app-menu entry.
        #
        # Nor is a place the user has taken (a file, or a link that isn't AppKata's) an error here:
        # the record says why there is no link, and the place is left alone. An install, an update
        # and a switch to a kept version stop at such a place before they change anything
        # (_check_before_placing). By this step the launcher is rewritten, and the launcher is the
        # enforcement (R17.4): a sandbox change and the startup pass, which come straight here,
        # stopped with the new launcher and menu entry on disk and their record not stored, so
        # AppKata started the app by the old record (CR1.3-46), and taking a failed install back
        # stopped half-way at the same place.
        link = os.path.join(portable.command_folder, app_id)
        if why := command_link_refusal(app_id, link, own) or _link_refusal(link, own):
            rec["commandRefused"] = why
            log.info("no command link %s: %s", link, why)
        else:
            rec["links"].append(_link(launch_target, link, own))
    rec["options"] = {"appMenu": portable.app_menu, "commandLink": bool(portable.command_dir), "stableName": portable.stable_name}


def _sandbox_launcher(rec: dict, app: dict, portable: "Portable", target: str, prog: str) -> str:
    """Generate (or remove) the per-app sandbox launcher and return its path, or "" when the app runs
    Off (R17.4, R17.7). The resolved grant set is `app["sandbox"]`, baked in by the backend;
    an absent/Off/unsupported sandbox leaves the program running directly, as before. Whether this
    system can sandbox is the backend's to decide: an app that has a launcher keeps it on a broken
    host (R17.10; review 2, F16: a missing tool here removed it)."""
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
    current version: an AppImage is extracted and run through AppRun (R17.7), a tarball as it is."""
    cur = rec["current"]
    if cur["path"].lower().endswith(".appimage"):
        appdir = sandbox.extracted_dir(target, cur["version"])
        return appdir, sandbox.appimage_exec(appdir), cur["path"]
    return cur["path"], os.path.relpath(os.path.join(target, cur["exec"]), cur["path"]), None


def launcher_is_current(rec: dict, app: dict, portable: "Portable") -> bool:
    """Whether the launcher on disk is the one AppKata would write today for this app and grant
    set (`app["sandbox"]`). The launcher is the enforcement (R17.4), and only an install, an update
    or a sandbox change rewrote it, so one written by an older AppKata -- before a launcher fix --
    kept running as written (round four, R4-4); the startup pass uses this to catch up, and it
    restores a hand-edited launcher the same way. False when there is no launcher or no grant set."""
    lp = rec.get("launcher")
    gs = app.get("sandbox")
    if not lp or not os.path.exists(lp) or not gs or not rec.get("current") or not rec.get("target"):
        return False
    portable = _where_it_is(rec, portable)
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
    """Windows (R15.5, R15.6): `current` is a directory junction, the app menu entry a
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
            shims.append(windows.write_shim(portable.command_folder, app_id, run))
        except FileExistsError as e:
            raise InstallError(str(e)) from None
    for old in rec.get("shims", []):
        if old not in shims:
            windows.remove_shim(old)
    rec["shims"] = shims
    rec["options"] = {"appMenu": portable.app_menu, "commandLink": bool(portable.command_dir), "stableName": portable.stable_name}


def _secure_target(portable: "Portable", target: str) -> None:
    """Apps for everyone live in folders only their owner and administrators can change (R15.4.3)."""
    if OS != "windows" or portable.scope != "everyone":
        return
    from . import windows
    try:
        windows.secure_folder(portable.root, root=True)
        windows.secure_folder(target, root=False)
    except (PermissionError, OSError) as e:
        raise InstallError(str(e)) from None


def _run_installer(app: dict, file: str, kind: str, exe_kind: str, portable: "Portable", prev: dict, tmpdir: str) -> dict:
    """Run a Windows installer for the app's scope, and find the Uninstall entry it made (R15.7, R15.8)."""
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

def _retain(rec: dict, keep: int) -> list[dict]:
    """Keep up to `keep` older versions in the record (R4.3.1.5), and return the rest: the caller
    removes them (:func:`_forget`) once the record that no longer names them is stored. They were
    deleted here, before that: an update whose record then couldn't be stored kept its previous
    record, which named versions that were gone (CR1.3-13)."""
    kept, out, rest = rec.get("kept", []), [], []
    seen = {rec["current"]["path"]}
    for k in kept:
        if k["path"] in seen or not os.path.lexists(k["path"]):
            continue
        seen.add(k["path"])
        (out if len(out) < max(0, keep) else rest).append(k)
    rec["kept"] = out
    return rest


def _forget(versions: list[dict]) -> None:
    """Remove versions no record names any more: each one's file or folder, and a sandboxed
    AppImage's unpacked copy (R17.7). Never a file AppKata adopted rather than placed. The record
    is stored by now, so one that can't be removed is logged, and fails nothing: it is in the app's
    folder, and goes with it."""
    for k in versions:
        if not k.get("external"):
            try:
                _remove_path(k["path"])
                _remove_extracted(k)
            except OSError as e:
                log.warning("couldn't remove %s: %s", k["path"], e)


def _set_aside(cur: dict) -> str:
    """Where the installed version that `cur`, just placed, took the place of is kept for now
    (:func:`_swap_in`), or "" when it took no version's place."""
    return _aside(cur["path"]) if os.path.lexists(_aside(cur["path"])) else ""


def _remove_extracted(k: dict) -> None:
    """Drop a kept AppImage version's derived extraction cache (R17.7)."""
    if k.get("path", "").lower().endswith(".appimage"):
        cache = sandbox.extracted_dir(os.path.dirname(k["path"]), k.get("version", ""))
        for p in (cache, cache + ".stamp", cache + ".lock"):
            _remove_path(p)


def _remove_path(path: str) -> None:
    if os.path.isdir(path) and not os.path.islink(path):
        _remove_tree(path)
    elif os.path.lexists(path):
        os.remove(path)


def _remove_tree(path: str) -> None:
    """Remove a folder AppKata made, with whatever is in it (a deep archive's paths too, R15.16)."""
    if OS == "windows":
        from .windows import long_path
        path = long_path(path)
    shutil.rmtree(path, ignore_errors=True)


def _check_before_placing(prev: dict, app: dict, portable: "Portable", app_id: str, target: str, kind: str = "") -> None:
    """Refuse now, before anything is placed or changed, the install :func:`_activate` would refuse
    after: a command link's place that holds something AppKata didn't make (R4.3.1.3, R15.6), and an
    app-menu entry that can't start the link it starts the app through. The files, the stable link
    and the menu entry were in place by the time the last step refused, with no record of them
    (CR1.3-15). What only shows later (a Start-menu shortcut Windows won't make) is taken back by
    :func:`_undo_portable`.

    Nothing is refused here that `_activate` would do: an app's kind is known once it is placed, and
    a command-line tool gets no menu entry when that option was Settings' default (`_apply_kind`),
    so the entry is checked only when it is sure to be written. The entry holds the path of the
    app's link in AppKata's own folder (:func:`_menu_link_path`), never the install folder's, so
    no install folder is refused for it (#685)."""
    if OS == "windows":
        from . import windows
        shim = os.path.join(portable.command_folder, app_id + ".cmd") if portable.command_dir else ""
        if shim and os.path.exists(shim):
            with open(shim, encoding="utf-8", errors="replace") as f:
                if not f.read().startswith(windows.SHIM_MARK):
                    raise InstallError(f"{shim} exists and isn't a command link AppKata made; not replacing it")
        return
    tool_maybe = bool(app.get("menuFromDefault")) and OS == "linux" and kind in ("appimage", "tarball")
    if portable.app_menu and not prev.get("selfInstalled") and not tool_maybe:
        _menu_exec(_menu_link_path(app_id))
    if portable.command_dir:
        link = os.path.join(portable.command_folder, app_id)
        own = (portable.root, os.path.dirname(target))
        if not command_link_refusal(app_id, link, own) and (why := _link_refusal(link, own)):
            raise InstallError(why)


def _options_of(rec: dict, portable: "Portable") -> "Portable":
    """The options an installed app's record was activated with, as a Portable (the rest is
    `portable`'s): its install folder, its three options (R4.3.1.6) and the folder its command link
    is in."""
    opts, target = rec.get("options") or {}, rec.get("target", "")
    folders = [os.path.dirname(l) for l in rec.get("links", []) if os.path.dirname(l) not in (target, _menu_links_dir())] + \
              [os.path.dirname(x) for x in rec.get("shims", [])]
    return replace(_where_it_is(rec, portable), scope=rec.get("scope") or portable.scope,
                   app_menu=bool(opts.get("appMenu")), stable_name=bool(opts.get("stableName")),
                   command_dir=(folders[0] if folders else portable.command_dir) if opts.get("commandLink") else "")


def _undo_portable(db: DB, app: dict, rec: dict, prev: dict, portable: "Portable", target: str, was: dict) -> None:
    """Take back a portable install, or a switch to a kept version, that failed after it began
    changing things, so what is on the disk is what the records say (R4.1, R4.6; CR1.3-15: the record
    is stored last, and a refusal at the command link left the files, the stable link, the launcher
    and the menu entry of an app AppKata had no record of, or the new version's under the previous
    version's record).

    `rec` is the record as far as the failed attempt wrote it, `prev` the stored one ({} for a first
    install), `was` what was there before (:func:`_was_there`), with what the attempt set aside or
    renamed since. A first install: its links, its menu
    entry, its launcher and marker and its folder go (a folder or a private home that was there
    before stays). An update: the new version's files go, and the previous version's stable link,
    launcher, menu entry and command link are made again as its record has them (`_activate`, with
    the record's own options). Never raises: the install's own error is the one to report."""
    try:
        with _ACTIVATE_LOCK:
            app_id, new = app_id_of(rec, app), rec.get("current") or {}
            old = {k.get("path") for k in [prev.get("current") or {}] + prev.get("kept", [])}
            if OS == "windows":
                from . import windows
                for x in rec.get("shortcuts", []):
                    if x not in prev.get("shortcuts", []):
                        windows.remove_shortcut(x["path"], x.get("elevated", False))
                for x in rec.get("shims", []):
                    if x not in prev.get("shims", []):
                        windows.remove_shim(x)
                for l in rec.get("links", []):
                    windows.remove_link(l)
            else:
                _remove_links(rec.get("links", []), (portable.root, os.path.dirname(target)))
                if not prev.get("selfInstalled") and _menu_entry_path(app_id) not in prev.get("files", []):
                    _remove_path(_menu_entry_path(app_id))
                if rec.get("launcher") and rec["launcher"] != prev.get("launcher"):
                    _remove_path(rec["launcher"])
            if was.get("aside") and os.path.lexists(was["aside"]):
                _remove_path(new["path"])       # the new version took the installed one's place (a fixed name,
                os.replace(was["aside"], new["path"])       # the same version again): that one goes back
            elif new.get("path") and new["path"] not in old:
                _remove_path(new["path"])
                _remove_extracted(new)
            if not prev.get("current"):
                if OS == "linux":
                    sandbox.remove_identity(app_id)
                    if not was["home"]:
                        sandbox.remove_sandbox_home(app_id)
                if not was["target"] and os.path.realpath(target).startswith(os.path.realpath(portable.root) + os.sep):
                    _remove_tree(target)
                return
            for moved, back in was.get("renamed", []):      # _leave_fixed_layout's rename
                if os.path.lexists(moved) and not os.path.lexists(back):
                    os.replace(moved, back)
            again = json.loads(json.dumps(prev))
            _activate(again, {**app, "sandbox": prev.get("sandbox")}, _options_of(prev, portable), target)
            db.x("UPDATE installs SET record=? WHERE url=?", (json.dumps(again), app["url"]))
    except Exception:       # noqa: BLE001
        log.exception("couldn't take back all of %s's failed install in %s", app.get("name"), target)


def _was_there(app_id: str, target: str) -> dict:
    """What a first install must leave when it fails (:func:`_undo_portable`): whether the app's
    folder was there before it, and a private home an earlier uninstall kept (R17.14)."""
    return {"target": os.path.lexists(target), "home": OS == "linux" and os.path.isdir(sandbox.sandbox_home(app_id))}


def install(db: DB, app: dict, asset: Asset, kind: str, assets: list[Asset], progress=None, cancel=None,
            portable: Portable | None = None, phase=None) -> dict:
    """Install one app's chosen asset. Returns the install record (also stored). `phase(name)` is
    told "Verifying" and "Installing" after the download (R4.8.1). An app that updates
    itself (app["autoUpdate"], R4.10) goes into its folder without a version number."""
    portable = portable or Portable()
    if app.get("foreign"):
        raise InstallError("installed outside AppKata; uninstall that copy first")   # R4.5.3
    rel_version = app.get("installVersion") or app.get("updateTo") or app.get("version", "")
    prev_row = db.one("SELECT record FROM installs WHERE url=?", (app["url"],))
    prev = json.loads(prev_row["record"] or "{}") if prev_row else {}
    # the install's own id (R6-1): kept across updates, unique among installs for a fresh one
    app_id = prev.get("id") or (app_id_of(prev, app) if prev.get("current") else new_app_id(db, app["url"], app["name"]))
    moving_from = {}
    if OS == "windows" and prev and prev.get("scope", "me") != portable.scope and not app.get("selfSetup"):
        moving_from, prev = prev, {}        # for someone else now: install afresh, then remove the old copy (R15.4.1)
        check_not_running(moving_from.get("target", ""), app["name"])
    portable = _where_it_is(prev, portable)        # an update: the app stays in the folder it is in (R4.3.1)
    tmpdir = os.path.join(downloads_dir(), app_id)          # kept when a download breaks, to resume it
    os.makedirs(tmpdir, exist_ok=True)
    check_not_running(prev.get("target", ""), app["name"])
    ok = keep = False
    signer = ""
    undo = None             # takes a portable install back, from its first change until its record is stored
    retired: list[dict] = []        # the versions the new record no longer names: removed once it is stored (R4.6)
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
            if portable.motw:            # R15.11.1
                windows.mark_of_web(file, asset.url)
            if kind in ("exe", "msi", "msix"):          # Authenticode (R15.11)
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
            # AppKata's own setup runs when the user restarts AppKata (R2.11.5)
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
            # it replaces its own files, so no version folders, kept versions or current link (R4.10.2)
            target = prev.get("target") if prev.get("current") else os.path.join(portable.root, app_id)
            check_not_running(target, app["name"])
            _check_before_placing(prev, app, portable, app_id, target, kind)
            was = _was_there(app_id, target)
            undo = partial(_undo_portable, db, app, rec, prev, portable, target, was)
            _secure_target(portable, target)
            rec.update(target=target, files=prev.get("files", []), links=prev.get("links", []), kept=[], selfUpdating=True)
            rec["current"] = _place(kind, file, app, target, rel_version, asset.name, fixed=True)
            was["aside"] = _set_aside(rec["current"])
            # the versions it had go once this one is installed, not before it is placed (R4.6)
            retired = [old for old in ([prev["current"]] + prev.get("kept", []) if prev.get("current") else [])
                       if old["path"] != rec["current"]["path"]]
            if OS == "windows" and portable.motw:
                windows.mark_tree(rec["current"]["path"], asset.url)
            if OS == "windows":
                rec["msvcrt"] = windows.needs_msvcrt(rec["current"]["path"])
            portable = _apply_kind(rec, app, portable, kind, target, prev)
            _activate(rec, app, replace(portable, stable_name=False, keep=0), target)
        elif portable_kind:
            # a portable app keeps its versions side by side in its own folder (R4.3.1)
            target = prev.get("target") if prev.get("current") else os.path.join(portable.root, app_id)
            check_not_running(target, app["name"])
            _check_before_placing(prev, app, portable, app_id, target, kind)
            was = _was_there(app_id, target)
            undo = partial(_undo_portable, db, app, rec, prev, portable, target, was)
            _secure_target(portable, target)
            if prev.get("selfUpdating") and prev.get("current"):
                left = _leave_fixed_layout(prev["current"], target)
                was["renamed"] = [(left["path"], prev["current"]["path"])] if left["path"] != prev["current"]["path"] else []
                prev = {**prev, "current": left}
            rec.update(target=target, links=prev.get("links", []), files=prev.get("files", []),
                       shortcuts=prev.get("shortcuts", []), shims=prev.get("shims", []),
                       kept=([prev["current"]] if prev.get("current") else []) + prev.get("kept", []))
            rec["current"] = _place(kind, file, app, target, rel_version, asset.name,
                                    others=tuple(k["path"] for k in rec["kept"] if k.get("version") != rel_version))
            was["aside"] = _set_aside(rec["current"])
            if OS == "windows" and portable.motw:
                windows.mark_tree(rec["current"]["path"], asset.url)
            if OS == "windows":           # R15.18
                rec["msvcrt"] = windows.needs_msvcrt(rec["current"]["path"])
            portable = _apply_kind(rec, app, portable, kind, target, prev)
            _activate(rec, app, portable, target)
            retired = _retain(rec, portable.keep)
        elif kind in ("exe", "msi") and OS == "windows":     # an installer (R15.7)
            rec.update(_run_installer(app, file, kind, app.get("exeKind") or "unknown", portable, prev, tmpdir))
        elif kind == "msix" and OS == "windows":            # R15.7.4
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
            # through the package backend, dry run first (R16.3.5, R16.8)
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
        undo = None
        ok = True
        _forget(retired + ([{"path": _aside(rec["current"]["path"])}] if rec.get("current") else []))
        return rec
    except Cancelled:
        ok = True                               # download() already removed the partial file
        raise
    except NeedsConfirmation:
        keep = True                             # the user is asked; Install again uses the same file
        raise
    finally:
        if undo:
            undo()                              # it failed before its record was stored (R4.6)
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
    """Make a kept older version current again, without downloading (R4.3.1.5)."""
    row = db.one("SELECT * FROM installs WHERE url=?", (app["url"],))
    rec = json.loads(row["record"] or "{}")
    k = next((x for x in rec.get("kept", []) if x["version"] == version), None)
    if not k or not os.path.lexists(k["path"]):
        raise InstallError(f"{version} isn't kept")
    portable = _where_it_is(rec, portable)
    check_not_running(rec.get("target", ""), app["name"])
    stored = json.loads(row["record"] or "{}")
    _check_before_placing(stored, app, portable, app_id_of(rec, app), rec["target"])
    rec["kept"] = [rec["current"]] + [x for x in rec["kept"] if x is not k]
    rec["current"] = k
    try:
        _activate(rec, app, portable, rec["target"])
        retired = _retain(rec, max(portable.keep, len(rec["kept"])))
        db.x("UPDATE installs SET version=?, date=?, record=?, installed_at=? WHERE url=?",
             (version, date or row["date"], json.dumps(rec), now(), app["url"]))
    except BaseException:           # the version that was current is current again, as its record says (CR1.3-15)
        _undo_portable(db, app, rec, stored, portable, rec["target"], {})
        raise
    _forget(retired)
    return rec


def rewrite_launcher(db: DB, app: dict, portable: "Portable") -> dict:
    """Regenerate ~/bin/apps/<app>/run for the current version and grant set, without reinstalling
    (R17.4): used when the user changes an installed app's sandbox. `app["sandbox"]` is the
    resolved grant set (or None/Off to drop the launcher).

    An app that updates itself (`app["autoUpdate"]`, R4.10) and has a launcher is in version
    folders, where AppKata updated it (R17.12). When its sandbox is turned Off here it updates
    itself again, so it goes back to the fixed-name layout of R4.10.2, without its kept versions
    (R4.10.5). If a step after the rename fails, the layout, the links, the launcher and the
    record are put back as they were. An app in that layout has no `current` link whatever the
    options say, here as at its install."""
    row = db.one("SELECT * FROM installs WHERE url=?", (app["url"],))
    if not row:
        return {}
    rec = json.loads(row["record"] or "{}")
    if not rec.get("current") or OS != "linux":
        return rec
    portable = _where_it_is(rec, portable)
    stored, target, gs = json.loads(row["record"]), rec["target"], app.get("sandbox")
    retired, moved = [], None
    try:
        if (app.get("autoUpdate") and rec.get("launcher") and (not gs or sandbox.level_of(gs) == "off")
                and not rec.get("selfUpdating") and not rec.get("selfInstalled")):
            retired, moved = _enter_fixed_layout(rec, app, portable, target)
        if rec.get("selfUpdating"):
            portable = replace(portable, stable_name=False, keep=0)
        _activate(rec, app, portable, target)
        db.x("UPDATE installs SET record=? WHERE url=?", (json.dumps(rec), app["url"]))
    except BaseException:
        if moved:               # back in version folders, under the record that says so
            fixed, before, aside = moved
            try:
                if os.path.lexists(fixed) and not os.path.lexists(before):
                    os.replace(fixed, before)
                if aside and os.path.lexists(aside) and not os.path.lexists(fixed):
                    os.replace(aside, fixed)
            except OSError:
                log.exception("couldn't move %s back to %s", fixed, before)
            _undo_portable(db, app, {**rec, "current": stored["current"]}, stored, portable, target, {})
        raise
    if moved:                   # a sandboxed AppImage's unpacked copies: it runs Off now (R17.7)
        for k in [stored["current"]] + stored.get("kept", []):
            _remove_extracted(k)
    _forget(retired)
    return rec


def refresh_command_link(db: DB, app: dict, portable: "Portable") -> bool:
    """The command link's step of an activation (:func:`_activate_linux`), alone, as AppKata starts
    (R4.3.1.3): a link that wasn't made, its name being a command or its place the user's, is made
    once the name and the place are free; a link whose name has since become a command is removed
    (only while it is AppKata's), and the record says why. Whether the app runs sandboxed, and
    whether this system can sandbox, change nothing here, and nothing else of the app is touched: a
    link already in place stays as it is. The start rewrote only a sandboxed app's launcher, and only
    one not up to date, so a link came back, or went from ahead of a newly installed command, only
    at the app's next update (#689's review, P1-1). `portable` is the app's options (the link's folder is
    the one its record names, else theirs); its record's own options say whether it has a command.
    Returns whether the record changed; it is stored then."""
    if OS != "linux":
        return False
    with _ACTIVATE_LOCK:
        row = db.one("SELECT record FROM installs WHERE url=?", (app["url"],))
        rec = json.loads(row["record"] or "{}") if row else {}
        if not rec.get("current") or not rec.get("target") or not rec.get("exec") or rec.get("selfInstalled"):
            return False
        p = _options_of(rec, portable)
        if not p.command_dir:
            return False
        before = json.dumps(rec, sort_keys=True)
        app_id, own = app_id_of(rec, app), (p.root, os.path.dirname(rec["target"]))
        link = os.path.join(p.command_folder, app_id)
        links = list(rec.get("links", []))
        if why := command_link_refusal(app_id, link, own) or _link_refusal(link, own):
            if link in links:
                _remove_links([link], own)
                links.remove(link)
            rec["commandRefused"] = why
        else:
            if not os.path.lexists(link):
                _link(rec["exec"], link, own)
            if link not in links:
                links.append(link)
            rec.pop("commandRefused", None)
        rec["links"] = links
        if json.dumps(rec, sort_keys=True) == before:
            return False
        db.x("UPDATE installs SET record=? WHERE url=?", (json.dumps(rec), app["url"]))
        log.info("command link %s: %s", link, rec.get("commandRefused") or "made")
        return True


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
              remove_sandbox: bool = False) -> list[str]:
    """Reverse what install recorded (R4.7). User data in the home folder is kept. A
    package whose removal takes other packages with it raises NeedsConfirmation unless `confirmed`.
    `remove_sandbox`: also delete the app's private sandbox home (R17.14).

    Returns what the record names and is still there afterwards, for the caller to say: only what
    is AppKata's is removed (a folder inside the install folder the app was installed into, a link
    that leads there, R4.3.1.3), and a folder can fail to delete. The app's row goes either way,
    and nothing said what stayed (CR1.3-12: every version of an app, once its record's root was
    another folder)."""
    row = db.one("SELECT * FROM installs WHERE url=?", (url,))
    if not row:
        return []
    rec = json.loads(row["record"] or "{}")
    if rec.get("package"):
        # a dry run first: anything else it would remove is shown first, and some removals are refused
        # (R16.4.3)
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
    _remove_links(rec.get("links", []), (rec.get("root") or apps_dir(), os.path.dirname(rec.get("target") or "")))
    root = os.path.realpath(rec.get("root") or apps_dir())
    for f in rec.get("files", []):
        if os.path.isdir(f) and os.path.realpath(f).startswith(root + os.sep):
            shutil.rmtree(f, ignore_errors=True)
        elif os.path.isfile(f) and os.path.basename(f).startswith("appkata-"):
            os.remove(f)
    left = [p for p in dict.fromkeys(rec.get("files", []) + rec.get("links", [])) if os.path.lexists(p)]
    if left:
        log.warning("uninstalling %s left %s in place", row["name"], ", ".join(left))
    db.x("DELETE FROM installs WHERE url=?", (url,))
    if OS == "linux":                           # only once the app itself is gone, not before a step can fail
        app_id = app_id_of(rec, {"name": row["name"]})
        sandbox.remove_identity(app_id)          # goes with the launcher; the home may stay (R17.14)
        if remove_sandbox:
            sandbox.remove_sandbox_home(app_id)
    return left


def install_msvcrt() -> str:
    """Download Microsoft's Visual C++ run-time, check it's signed by Microsoft, and install it for
    everyone (R15.18.3). Returns "ok" or "restart"."""
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
    """A portable app's shortcut, command link, junction and folder (R4.3.1.4, R15.5, R15.6)."""
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
    """Run the uninstaller recorded from the app's Uninstall entry (R15.8.2)."""
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
    is called when it fails to start (R14.2, :func:`applog.watch`): a sandboxed launch can
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
        from .platform import linux_family
        _launch_package(row["name"], rec["package"], rec.get("manager") or ("apt" if linux_family() == "debian" else "dnf"))


def _entry_string(value: str) -> str:
    """A desktop entry's string value as it reads: its escapes (`\\s`, `\\n`, `\\t`, `\\r`, `\\\\`) turned
    back into what they stand for."""
    return re.sub(r"\\([sntr\\])", lambda m: {"s": " ", "n": "\n", "t": "\t", "r": "\r", "\\": "\\"}[m.group(1)], value)


def _shown_on_this_desktop(entry) -> bool:
    """Whether an entry is for this desktop by its `OnlyShowIn` and `NotShowIn`: the names in
    $XDG_CURRENT_DESKTOP, in their order, the first one either key names deciding; with none named,
    it is shown unless it has `OnlyShowIn` (the Desktop Entry Specification, as GLib reads it)."""
    only, never = ({d for d in entry.get(k, "").split(";") if d} for k in ("OnlyShowIn", "NotShowIn"))
    for desktop in (d for d in os.environ.get("XDG_CURRENT_DESKTOP", "").split(":") if d):
        if desktop in only:
            return True
        if desktop in never:
            return False
    return not only


def _installed_program(word: str) -> bool:
    """Whether the program an entry names (`TryExec`, the first word of `Exec`) is here to run: a
    path that is an executable file, or a name found on the PATH."""
    if os.sep in word:
        return os.path.isfile(word) and os.access(word, os.X_OK)
    return bool(shutil.which(word))


def _menu_entry(path: str):
    """The [Desktop Entry] group of an app-menu entry the desktop's menu shows here, or None: not an
    application, hidden (`NoDisplay`, `Hidden`), for other desktops than this one (`OnlyShowIn`,
    `NotShowIn`), its program not installed (`TryExec`, or the first word of `Exec`), or not
    readable. These are the Desktop Entry Specification's rules as GLib applies them, which is what
    the menus of the desktops AppKata supports read entries with (R5.7.4; #689's review, P1-B4: only
    `NoDisplay` and `Hidden` were read, and a package's entry for KDE alone was opened on GNOME)."""
    cp = configparser.ConfigParser(interpolation=None, strict=False)
    try:
        if not os.path.isfile(path) or os.path.getsize(path) > 1 << 20:
            return None
        cp.read(path, encoding="utf-8")
        entry = cp["Desktop Entry"]
    except (configparser.Error, OSError, UnicodeDecodeError, KeyError):
        return None
    if entry.get("Type") != "Application" or "true" in (entry.get("NoDisplay", "").lower(), entry.get("Hidden", "").lower()):
        return None
    if not _shown_on_this_desktop(entry):
        return None
    if (try_exec := _entry_string(entry.get("TryExec", ""))) and not _installed_program(try_exec):
        return None
    if command := _entry_string(entry.get("Exec", "")):
        try:
            words = shlex.split(command)
        except ValueError:          # GLib can't read it either
            return None
        if not words or not _installed_program(words[0]):
            return None
    return entry


def _package_entries(package: str, manager: str) -> list[str]:
    """The app-menu entries that open a system package (R5.7.4's Open): the `.desktop` files it put in
    an `applications` folder that the menu shows, the one named after the package first. A package
    that ships none may have its program's entry in another of its family (neovim's `nvim.desktop`
    is neovim-runtime's): then the entries in the system's applications folders whose program is a
    file the package installed."""
    cmd = ["dpkg-query", "-L", package] if manager == "apt" else ["rpm", "-ql", package]
    if not shutil.which(cmd[0]):
        return []
    try:
        listed = subprocess.run(cmd, capture_output=True, text=True, timeout=60).stdout.splitlines()
    except (OSError, subprocess.SubprocessError):
        return []
    stem = lambda p: os.path.basename(p)[:-len(".desktop")]       # noqa: E731
    own = [p for p in listed if p.endswith(".desktop") and os.path.basename(os.path.dirname(p)) == "applications"
           and _menu_entry(p) is not None]
    if own:
        return sorted(own, key=lambda p: (_squash(package) not in _squash(stem(p)), stem(p)))
    files = {os.path.realpath(p) for p in listed if os.path.isfile(p)}
    found = []
    for folder in _APPLICATIONS:
        try:
            names = sorted(n for n in os.listdir(folder) if n.endswith(".desktop"))
        except OSError:
            continue
        for name in names:
            entry = _menu_entry(os.path.join(folder, name))
            try:
                words = shlex.split(entry.get("Exec", "")) if entry is not None else []
            except ValueError:
                continue
            while words and (os.path.basename(words[0]) == "env" or re.match(r"[A-Za-z_][A-Za-z0-9_]*=", words[0])):
                words = words[1:]
            program = words and (words[0] if os.path.isabs(words[0]) else shutil.which(words[0]))
            if program and os.path.realpath(program) in files:
                found.append(os.path.join(folder, name))
    return found


# where the system's app-menu entries are, for a package's program whose entry another package ships
_APPLICATIONS = ("/usr/share/applications", "/usr/local/share/applications")


def _launch_package(name: str, package: str, manager: str) -> None:
    """Open for a system package: its own app-menu entry, started as the desktop starts it (`gio
    launch`, else `gtk-launch`). Its name says nothing of its program's (`libreoffice-writer` installs
    `lowriter`; `openssh-clients`, `ssh`), and a program named after it may be another package's
    (CR1.3-21)."""
    entries = _package_entries(package, manager)
    if not entries:
        raise InstallError(f"{name} has no app-menu entry to open it with")
    if shutil.which("gio"):
        cmd = ["gio", "launch", entries[0]]
    elif shutil.which("gtk-launch"):
        cmd = ["gtk-launch", os.path.basename(entries[0])]
    else:
        raise InstallError(f"couldn't open {name}: neither gio nor gtk-launch is on this computer")
    subprocess.Popen(cmd, start_new_session=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


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


# ---------------------------------------------------------------- package channels (R16)
class NeedsFlathub(InstallError):
    """The Flathub remote isn't configured for this user: ask "Add Flathub?" first (R16.3.4)."""
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
    """Why a package can't be uninstalled from AppKata, or "" (R16.4.3)."""
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
    """Install from a Flatpak remote or the distribution's repositories (R16.3.4, R16.3.5).
    `option` is a card from channels.options(). Returns the install record (also stored)."""
    from . import channels
    if app.get("foreign"):
        raise InstallError("installed outside AppKata; adopt or uninstall that copy first")   # R4.5.3, R16.4.2
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
    """Update a channel install (R16.5.5); a Flatpak `commit` installs that older build and
    pins it (R16.5.7)."""
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
    """A Flatpak is pinned with flatpak mask, which stops every updater (R16.5.6); packages can't be."""
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
    """Install options → Updates: "system" or "appkata" (R16.5.3)."""
    row = db.one("SELECT record FROM installs WHERE url=?", (url,))
    if not row:
        return
    rec = json.loads(row["record"] or "{}")
    rec["updates"] = owner
    db.x("UPDATE installs SET record=? WHERE url=?", (json.dumps(rec), url))
