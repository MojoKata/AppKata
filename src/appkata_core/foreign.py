"""Apps installed outside AppKata (requirement 4.5): found, flagged, never managed."""

from __future__ import annotations

import configparser
import glob
import json
import logging
import os
import re
import shutil
import subprocess

from .db import DB, now
from .platform import OS

log = logging.getLogger("appkata.foreign")


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _desktop_dirs() -> list[str]:
    dirs = (os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share").split(":")
    home = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return [os.path.join(d, "applications") for d in [home, *dirs, "/var/lib/flatpak/exports/share",
                                                       os.path.expanduser("~/.local/share/flatpak/exports/share")]]


def inventory() -> dict[str, tuple[str, str]]:
    """normalized name → (where, version) for everything this machine says is installed."""
    found: dict[str, tuple[str, str]] = {}
    if OS == "windows":
        from . import windows
        return windows.inventory()
    if OS != "linux":
        return found
    for d in _desktop_dirs():
        for path in glob.glob(os.path.join(d, "*.desktop")):
            base = os.path.basename(path)
            if base.startswith("appkata-"):
                continue
            cp = configparser.RawConfigParser(strict=False, interpolation=None)
            try:
                cp.read(path, encoding="utf-8")
                name = cp.get("Desktop Entry", "Name", fallback="")
                if cp.get("Desktop Entry", "NoDisplay", fallback="false").lower() == "true":
                    continue
            except (configparser.Error, UnicodeDecodeError):
                continue
            for key in (name, base[:-8], base[:-8].rsplit(".", 1)[-1]):
                if key:
                    found.setdefault(_norm(key), (path, ""))
    if shutil.which("flatpak"):
        p = subprocess.run(["flatpak", "list", "--app", "--columns=application,name,version"], capture_output=True, text=True)
        for line in p.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) >= 2:
                for key in (parts[1], parts[0].rsplit(".", 1)[-1]):
                    found[_norm(key)] = (f"Flatpak {parts[0]}", parts[2] if len(parts) > 2 else "")
    if shutil.which("dpkg-query"):
        p = subprocess.run(["dpkg-query", "-W", "-f", "${Package}\t${Version}\t${Status}\n"], capture_output=True, text=True)
        for line in p.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) == 3 and "installed" in parts[2] and "not-installed" not in parts[2]:
                found.setdefault(_norm(parts[0]), (f"dpkg ({parts[0]} {parts[1]})", parts[1]))
    elif shutil.which("rpm"):
        p = subprocess.run(["rpm", "-qa", "--qf", "%{NAME}\t%{VERSION}\n"], capture_output=True, text=True)
        for line in p.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) == 2:
                found.setdefault(_norm(parts[0]), (f"rpm ({parts[0]} {parts[1]})", parts[1]))
    if shutil.which("snap"):
        p = subprocess.run(["snap", "list"], capture_output=True, text=True)
        for line in p.stdout.splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 2:
                found.setdefault(_norm(parts[0]), (f"Snap {parts[0]}", parts[1]))
    return found


def adoptable(db: DB, urls_: list[str]) -> dict[str, dict]:
    """url → the channel link of an install a package channel matches exactly: the Flatpak app ID or
    the package name (requirement 16.4.2). Name matches alone aren't adoptable."""
    from . import appstream, channels, flatpak, pkgbackend
    if not channels.enabled():
        return {}
    try:
        cat = appstream.load_cached()
    except OSError:
        cat = None
    fps = flatpak.installed() if flatpak.available() else {}
    mgr = channels.manager()
    out = {}
    for url in urls_:
        found = channels.links(db, url, cat, mgr)
        fl, pk = found.get("flatpak"), found.get("package")
        if fl and fl.value in fps:
            i = fps[fl.value]
            out[url] = {**fl.as_dict(), "version": i.version, "installation": i.installation, "origin": i.origin,
                        "where": f"Flatpak {fl.value}" + (" (for everyone)" if i.installation == "system" else "")}
        elif pk and mgr:
            ver = pkgbackend.installed_version(pk.value, mgr)
            if ver:
                out[url] = {**pk.as_dict(), "version": ver, "where": f"{'dpkg' if mgr == 'apt' else 'rpm'} ({pk.value} {ver})"}
    return out


def scan(db: DB) -> None:
    """Refresh foreign_installs for every Catalog app AppKata didn't install."""
    inv = inventory()
    mine = {r["url"] for r in db.all("SELECT url FROM installs")}
    rows = db.all("SELECT url, name, repo FROM apps")
    try:
        exact = adoptable(db, [a["url"] for a in rows if a["url"] not in mine])
    except Exception:          # never let channel probing break the scan
        log.exception("couldn't look for adoptable installs")
        exact = {}
    with db.tx():
        db.x("DELETE FROM foreign_installs")
        for a in rows:
            if a["url"] in mine:
                continue
            if a["url"] in exact:
                e = exact[a["url"]]
                db.x("INSERT OR REPLACE INTO foreign_installs(url, location, version, checked_at, adopt) VALUES(?,?,?,?,?)",
                     (a["url"], e["where"], e["version"], now(), json.dumps(e)))
                continue
            keys = {_norm(a["name"]), _norm((a["repo"] or "").rsplit("/", 1)[-1])} - {""}
            for k in keys:
                if k in inv and len(k) >= 3:
                    where, ver = inv[k]
                    db.x("INSERT OR REPLACE INTO foreign_installs(url, location, version, checked_at) VALUES(?,?,?,?)",
                         (a["url"], where, ver, now()))
                    break


def adopt(db: DB, url: str) -> dict:
    """Track an install AppKata didn't make, without reinstalling it (requirement 16.4.2). Returns
    the install record."""
    from . import audit, channels, flatpak
    row = db.one("SELECT * FROM foreign_installs WHERE url=?", (url,))
    link = json.loads(row["adopt"] or "{}") if row and row.get("adopt") else {}
    if not link:
        raise ValueError("this copy can't be adopted: no package channel matches it exactly")
    app = db.one("SELECT name FROM apps WHERE url=?", (url,)) or {"name": url.rsplit("/", 1)[-1]}
    if link["kind"] == "flatpak":
        system = link.get("installation") == "system"
        inf = flatpak.info(link["value"], system)
        rec = {"channel": "flatpak", "flatpak": link["value"], "remote": link.get("origin") or link.get("remote", ""),
               "commit": inf.get("commit", ""), "installation": "system" if system else "user", "adopted": True,
               "verified": "signed", "signer": (link.get("origin") or "flathub").capitalize(),
               "perms": flatpak.permissions(flatpak.installed_metadata(link["value"], system))}
        raw, kind, asset = link.get("version", ""), "flatpak", f"{rec['remote']} {link['value']}"
        version = channels.project_version("flatpak", raw) or raw
    else:
        from . import pkgbackend
        facts = pkgbackend.backend().facts([link["value"]])
        rec = {"channel": "package", "package": link["value"], "manager": link["manager"], "adopted": True,
               "verified": "signed", "signer": channels.distro_name(), "pkgVersion": link.get("version", ""),
               "wasAuto": link["value"] in facts.auto}
        raw, kind, asset = link.get("version", ""), link["manager"], link["value"]
        version = channels.project_version(link["manager"], raw)
    with db.tx():
        db.x("""INSERT OR REPLACE INTO installs(url, name, version, date, asset, kind, record, installed_at)
                VALUES(?,?,?,?,?,?,?,?)""", (url, app["name"], version, "", asset, kind, json.dumps(rec), now()))
        db.x("DELETE FROM foreign_installs WHERE url=?", (url,))
    audit.record(db, "you", "app", "adopted", app["name"], url, {"version": raw, "from": row["location"]})
    return rec
