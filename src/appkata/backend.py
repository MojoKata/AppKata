"""The QML-facing backend: lists for each perspective, actions, and background work."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import threading
import time
import traceback

from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot

import logging

from appkata_core import applog, audit, catalog, desktop, explore, foreign, install, review, sandbox, selfinstall, sync, transfer, trustfile, urls
from appkata_core import versions as vcmp
from appkata_core.catalog import authority_view, short_fp
from appkata_core.db import DB, now
from appkata_core.forges import Asset
from appkata_core.http import Http, SourceError
from appkata_core import APPKATA_REPO, __version__ as APPKATA_VERSION
from appkata_core.platform import data_dir

from . import prefs as prefs_mod
from .channelui import Channels
from appkata_core.pkgbackend import NeedsConfirmation as PackageNeedsConfirmation, Refused as PackageRefused

log = logging.getLogger("appkata.gui")


def _plain_readme(md: str) -> str:
    """README as Markdown that Qt's renderer shows well: no HTML, no images or badge rows."""
    t = re.sub(r"<!--.*?-->", "", md or "", flags=re.S)
    t = re.sub(r"<(picture|details|summary|p|div|span|a|img|br|h\d|sup|sub|kbd|table|tr|td|th|thead|tbody|center)\b[^>]*>", "", t, flags=re.I)
    t = re.sub(r"</(picture|details|summary|p|div|span|a|h\d|sup|sub|kbd|table|tr|td|th|thead|tbody|center)>", "", t, flags=re.I)
    t = re.sub(r"\[!\[[^\]]*\]\([^)]*\)\]\([^)]*\)", "", t)          # linked badges
    t = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", t)                        # images
    t = re.sub(r"!\[[^\]]*\]\[[^\]]*\]", "", t)                       # reference-style images
    t = re.sub(r"(?m)^\s*\[[^\]]+\]:\s*\S+.*$", "", t)                # link reference definitions
    t = re.sub(r"(?m)^\.\. (\|[^|]+\| )?image::.*$|^\s+:(target|alt|width|height|align):.*$", "", t)   # rst images
    t = t.replace("![", "[")             # anything image-like left: never fetch from the network
    out, blank = [], 0
    for l in t.splitlines():
        if not l.strip():
            blank += 1
            if blank > 1:
                continue
        else:
            blank = 0
        out.append(l)
    return "\n".join(out).strip()[:60000]


_TONES: dict[str, str] = {}


def icon_tone(path: str) -> str:
    """'light' or 'dark': which plate an icon reads best on. Transparent icons with light glyphs
    (white logos) need a dark plate; dark glyphs need a light one; opaque icons look fine on either."""
    if not path:
        return ""
    if path in _TONES:
        return _TONES[path]
    from PySide6.QtGui import QImage
    img = QImage(path)
    tone = ""
    if not img.isNull():
        img = img.scaled(48, 48)
        total = lum = opaque = 0.0
        for y in range(img.height()):
            for x in range(img.width()):
                c = img.pixelColor(x, y)
                a = c.alphaF()
                total += 1
                if a > 0.05:
                    opaque += a
                    lum += a * (0.2126 * c.redF() + 0.7152 * c.greenF() + 0.0722 * c.blueF())
        if opaque and opaque / total < 0.75:          # mostly transparent: the glyph decides
            tone = "dark" if lum / opaque > 0.6 else "light" if lum / opaque < 0.35 else ""
    _TONES[path] = tone
    return tone


def _plain(v):
    """A QML argument as plain Python. With PySide 6.9 a JS object or array reaches a "QVariant"
    slot as a QJSValue, which dict()/list() can't iterate; a scalar arrives converted. Every slot
    that takes a QVariant from QML goes through this (found by tests/test_dialog_contract.py: the
    install dialog's Save raised TypeError inside installWith and did nothing)."""
    return v.toVariant() if hasattr(v, "toVariant") else v


class Backend(QObject):
    changed = Signal()
    syncChanged = Signal()
    prefsChanged = Signal()
    busyChanged = Signal()
    toast = Signal(str, str)                     # kind, text
    sourcePreview = Signal("QVariant")
    trustPreview = Signal("QVariant")
    reviewSaved = Signal("QVariant")
    notify = Signal(str, str)                    # title, text (tray)
    exploreResults = Signal("QVariant")
    installPlan = Signal("QVariant")
    inUse = Signal("QVariant")                   # {url, name, action, version}: "Close <App> to continue" (15.9)
    _inUse = Signal("QVariant")
    msvcrtNeeded = Signal("QVariant")            # {url, name}: offer the Visual C++ run-time (15.18.3)
    flathubNeeded = Signal("QVariant")           # {url, name, option, updates}: "Add Flathub?" (16.3.4)
    planConfirm = Signal("QVariant")             # {url, name, action, lines, refused, ...}: a package plan to confirm (16.3.5, 16.4.3)
    permsNeeded = Signal(str)                    # url: its update asks for more permissions (16.6.3)
    sandboxSetupNeeded = Signal("QVariant")      # {url, name, version, choice, ...}: "Set up the sandbox?" (17.10)
    _setupThenInstall = Signal("QVariant")
    _flathubNeeded = Signal("QVariant")
    _planConfirm = Signal("QVariant")
    _msvcrtNeeded = Signal("QVariant")
    auditChanged = Signal()
    _refresh = Signal()
    _toast = Signal(str, str)

    def __init__(self, db_path: str | None = None, heal: bool = True):
        super().__init__()
        self.root = data_dir()
        self.db = DB(db_path or os.path.join(self.root, "appkata.db"))
        self._prefs = prefs_mod.load()
        self.http = Http(self.db.get("tokens", {}))
        self._apps: list[dict] = []
        self._search, self._tag = "", ""
        self._busy: dict[str, dict] = {}
        self._install_lock = threading.Lock()      # one install at a time; the rest wait (requirement 4.8.1)
        self._cancel: set[str] = set()
        self._preview_assets: dict[str, list] = {}
        self._sync = sync.Progress()
        self._syncing = False
        self._previews: dict[str, sync.Preview] = {}
        self._refresh.connect(self.reload)
        self._toast.connect(self.toast)
        self._inUse.connect(self.inUse)
        self._msvcrtNeeded.connect(self.msvcrtNeeded)
        self._flathubNeeded.connect(self.flathubNeeded)
        self._planConfirm.connect(self.planConfirm)
        self._setupThenInstall.connect(self._install_after_prompt)
        self.ch = Channels(self.db, os.path.dirname(os.path.abspath(db_path)) if db_path else self.root)
        self._ensure_own_trust()
        self._ensure_self()
        self.reload()
        # e.g. bwrap installed since these apps were (17.10). Off the UI thread: deciding whether
        # anything needs healing can run the bwrap probe (up to 15 s on a stuck system). Not for the
        # tour (heal=False): its world is staged, and this machine's tools mustn't change it.
        if heal:
            threading.Thread(target=self._heal_launchers_at_startup, name="heal launchers", daemon=True).start()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._background_sync)
        self._arm_timer()

    def _audit(self, actor: str, kind: str, action: str, subject: str, url: str = "", detail=None) -> None:
        audit.record(self.db, actor, kind, action, subject, url, detail)
        self.auditChanged.emit()

    # ---------------------------------------------------------------- data
    def _ensure_self(self) -> None:
        """AppKata is a built-in Source (requirement 2.11). Run as an AppImage, it adopts that file as
        installed by AppKata, so it can update itself like any portable app."""
        if not self.db.one("SELECT 1 FROM sources WHERE url=?", (APPKATA_REPO,)):
            self.db.x("INSERT INTO sources(url, input_url, settings, added_at) VALUES(?,?,?,?)",
                      (APPKATA_REPO, APPKATA_REPO, json.dumps({"builtin": True}), now()))
        image = os.environ.get("APPIMAGE")
        if image and os.path.isfile(image) and not self.db.one("SELECT 1 FROM installs WHERE url=?", (APPKATA_REPO,)):
            p = self.portable()
            rec = {"files": [], "links": [], "root": p.root, "target": os.path.join(p.root, "appkata"), "kept": [], "exec": image,
                   "current": {"version": APPKATA_VERSION, "path": image, "exec": image, "external": True}, "verified": "adopted",
                   "options": {"appMenu": p.app_menu, "commandLink": bool(p.command_dir), "stableName": p.stable_name}}
            self.db.x("INSERT INTO installs(url, name, version, date, asset, kind, record, installed_at) VALUES(?,?,?,?,?,?,?,?)",
                      (APPKATA_REPO, "AppKata", APPKATA_VERSION, "", os.path.basename(image), "appimage", json.dumps(rec), now()))
            log.info("adopted the running AppImage %s", image)
        self._adopt_windows_setup()
        if selfinstall.installed(self.db):          # links and autostart follow the stable link (2.11.3.1)
            desktop.LAUNCH_OVERRIDE = json.loads(self.db.one("SELECT record FROM installs WHERE url=?", (APPKATA_REPO,))["record"])["exec"]

    # ---------------------------------------------------------------- installing itself (2.11.3.1)
    @Property("QVariant", notify=changed)
    def selfInstallOffer(self):
        """{version, image, dest} when AppKata can install itself, else null; `ask` when it should ask now."""
        image = selfinstall.running_appimage() or (getattr(self, "_demo_self_install", "") or "")
        if not image or (not getattr(self, "_demo_self_install", "") and selfinstall.installed(self.db)):
            return None
        root = self.portable().root
        if not getattr(self, "_demo_self_install", "") and os.path.realpath(image).startswith(os.path.realpath(selfinstall.target(root)) + os.sep):
            return None
        return {"version": APPKATA_VERSION, "image": image, "folder": selfinstall.target(root),
                "dest": os.path.join(selfinstall.target(root), selfinstall.STABLE),
                "ask": bool(getattr(self, "_demo_self_install", "")) or selfinstall.should_ask(self.db, root, bool(self._prefs.get("selfInstallDeclined")), image)}

    @Slot(bool)
    def installSelf(self, delete_download: bool) -> None:
        p = self.portable()
        try:
            rec = selfinstall.install_self(self.db, p.root, delete_download=delete_download,
                                           options={"appMenu": True, "commandLink": False, "stableName": True})
        except OSError as e:
            self.toast.emit("error", f"Couldn't install AppKata: {e}")
            return
        self.auditChanged.emit()
        log.info("installed itself to %s", rec["exec"])
        selfinstall.launch(rec)
        from PySide6.QtWidgets import QApplication
        QApplication.quit()

    @Slot()
    def declineSelfInstall(self) -> None:
        """Run from here: don't ask again; ⋮ → Install AppKata… still offers it."""
        self.setPref("selfInstallDeclined", True)
        self.changed.emit()

    @Slot(str)
    def demoSelfInstall(self, image: str) -> None:
        """The tour: offer to install AppKata from a pretend download (2.11.3.1)."""
        if getattr(self, "_demo_self_install", "") != image:
            self._demo_self_install = image
            self.changed.emit()

    def _adopt_windows_setup(self) -> None:
        """Installed with its Windows setup, AppKata adopts that installation (requirement 2.11.5)."""
        from appkata_core.platform import OS
        if OS != "windows" or not getattr(sys, "frozen", False):
            return
        from appkata_core import windows
        e = next((x for x in windows.uninstall_entries().values() if x["key"] == windows.APPKATA_UNINSTALL_KEY), None)
        if not e:
            return
        row = self.db.one("SELECT version, record FROM installs WHERE url=?", (APPKATA_REPO,))
        old = json.loads(row["record"] or "{}") if row else {}
        if row and row["version"] == APPKATA_VERSION and old.get("entry"):
            return
        rec = {"installer": "inno", "entry": e, "scope": "everyone" if e["hive"] == "HKLM" else "me", "selfSetup": True,
               "verified": "adopted", "files": [], "links": []}
        self.db.x("INSERT OR REPLACE INTO installs(url, name, version, date, asset, kind, record, installed_at) VALUES(?,?,?,?,?,?,?,?)",
                  (APPKATA_REPO, "AppKata", APPKATA_VERSION, "", "", "exe", json.dumps(rec), now()))
        log.info("adopted AppKata %s installed by its setup (%s)", APPKATA_VERSION, rec["scope"])

    @Slot()
    def restartSelf(self) -> None:
        """Start the newly installed AppKata and quit this one (requirement 2.11.3)."""
        row = self.db.one("SELECT record FROM installs WHERE url=?", (APPKATA_REPO,))
        rec = json.loads(row["record"] or "{}") if row else {}
        if rec.get("pendingSetup"):         # Windows: run the new setup silently; it starts AppKata again (2.11.5)
            from appkata_core import windows
            setup = rec["pendingSetup"]
            if not os.path.exists(setup):
                self.toast.emit("error", "The downloaded AppKata setup is gone; update again.")
                return
            scope = "/ALLUSERS" if rec.get("scope") == "everyone" else "/CURRENTUSER"
            try:
                windows.shell_execute(setup, f"/VERYSILENT /SUPPRESSMSGBOXES /NORESTART {scope} /RELAUNCH=1",
                                      elevate=rec.get("scope") == "everyone", wait=False)
            except OSError as e:
                self.toast.emit("error", f"Couldn't start the AppKata setup: {e}")
                return
            from PySide6.QtWidgets import QApplication
            QApplication.quit()
            return
        exe = rec.get("exec", "")
        if not exe or not os.path.exists(exe):
            self.toast.emit("error", "Couldn't find the new AppKata to start.")
            return
        import subprocess
        log.info("restarting into %s", exe)
        subprocess.Popen([exe], start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        from PySide6.QtWidgets import QApplication
        QApplication.quit()

    @Property(str, constant=True)
    def selfUrl(self):
        return APPKATA_REPO

    @Slot(int, int)
    def setTrustScore(self, tid: int, score: int) -> None:
        """A Trust's Score, 1–5 stars, weights its reviews (requirement 10.6.2)."""
        score = max(1, min(5, int(score)))
        t = self.db.one("SELECT name, url, own FROM trusts WHERE id=?", (tid,))
        if not t or t["own"]:
            return
        self.db.x("UPDATE trusts SET score=? WHERE id=?", (score, tid))
        self._audit("you", "trust", "set the Score of", t["name"], t["url"], {"score": score})
        self.reload()

    def _ensure_own_trust(self) -> None:
        p = self._prefs.get("reviewPath")
        if p:
            tid = sync.own_trust(self.db, p)
            sync.sync_own(self.db, tid)

    @Slot()
    def reload(self) -> None:
        self._apps = catalog.build(self.db, runs_sandboxed=self._runs_sandboxed)
        from appkata_core.platform import OS
        runtime = ""
        if OS == "windows" and any(a.get("msvcrt") for a in self._apps):
            from appkata_core.windows import msvcrt_installed
            runtime = msvcrt_installed()
        demo_rt = getattr(self, "_demo_msvcrt", set())
        for a in self._apps:
            if a["url"] in demo_rt:             # the tour (requirement 15.18)
                a["msvcrt"] = True
            a["msvcrtMissing"] = bool(a.get("msvcrt") and (a["url"] in demo_rt or not runtime))
            a["iconTone"] = icon_tone(a["icon"])
            if a.get("self") and getattr(self, "_demo_self_updated", False):     # the tour: just after a self-update
                a.update(installed=a["version"], state="installed", updateTo="", restartNeeded=True, selfManaged=True)
        if self.ch.fake and self.ch.fake.get("installs"):
            self._demo_channel_installs()
        self.changed.emit()

    def _demo_channel_installs(self) -> None:
        """DEV ONLY (APPKATA_DEMO_CHANNELS, or the tour's demoChannels): show some apps as installed
        from a package channel, from the demo file, without touching the database (requirement 16)."""
        from appkata_core.autoupdate import Detection
        det = Detection.from_dict(self.ch.fake.get("autoupdate") or {})
        for url, ov in self.ch.fake["installs"].items():
            a = self._app(url)
            if not a:
                continue
            meta = self.db.one("SELECT releases FROM apps WHERE url=?", (url,)) or {}
            releases = [r for r in json.loads(meta.get("releases") or "[]") if not r.get("prerelease")]
            idx = min(int(ov.get("release", 0)), max(0, len(releases) - 1))
            version = ov.get("version") or (releases[idx]["version"] if releases else "")
            rec = dict(ov["record"])
            if ov.get("pendingRelease") is not None and releases:
                rec["pending"] = {**(rec.get("pending") or {}), "version": releases[int(ov["pendingRelease"])]["version"],
                                  "projectVersion": releases[int(ov["pendingRelease"])]["version"]}
            chk = ((self.ch.fake.get("checks") or {}).get(url) or {}).get(rec["channel"])
            chv = catalog.channel_view(rec, version, releases, det, chk)
            state, upd = "installed", ""
            if chv["updates"] == "system":
                state = "system"
            elif chv["updates"] != "held" and chv["pending"]:
                state, upd = "update", chv["pending"]
            a.update(installed=version, installKind=rec["channel"], ch=chv, state=state, updateTo=upd, foreign="",
                     permsGrow=bool(chv["addedPerms"]), held="", pinned="", tourTip=bool(ov.get("tip")),
                     newer=bool(state == "system" and releases and vcmp.newer(releases[0]["version"], version)))

    @Slot(bool)
    def demoChannels(self, on: bool) -> None:
        """DEV ONLY, the tour: channel facts from <data folder>/demo-channels.json (scripts/demo_data.py)."""
        from .channelui import load_demo_file
        want = load_demo_file(self.ch.data_dir) if on else None
        if bool(self.ch.fake) != bool(want) and not os.environ.get("APPKATA_DEMO_CHANNELS"):
            self.ch.fake = want
            self.reload()

    def _sorted(self) -> list[dict]:
        return catalog.sort(self._apps, self._prefs.get("sort", "trust"))

    @Property("QVariant", notify=changed)
    def catalogItems(self):
        items, _ = catalog.visible(self._sorted(), self._search, self._tag)
        return items

    @Property(int, notify=changed)
    def vetoedShown(self):
        return catalog.visible(self._apps, self._search, self._tag)[1]

    @Property(int, notify=changed)
    def catalogCount(self):
        return len([a for a in self._apps if not a["vetoed"]])

    @Property(str, notify=changed)
    def search(self):
        return self._search

    @Property(str, notify=changed)
    def tag(self):
        return self._tag

    @Slot(str)
    def setSearch(self, s: str) -> None:
        if s != self._search:
            self._search = s
            self.changed.emit()

    @Slot(str)
    def setTag(self, t: str) -> None:
        self._tag = "" if t == self._tag else t
        self.changed.emit()

    @Slot(str)
    def selectTag(self, t: str) -> None:
        """A tag chip clicked on a tile or review: filter the Catalog by it (requirement 12.2)."""
        self._tag = t
        self.changed.emit()

    @Property("QVariant", notify=changed)
    def topTags(self):
        counts: dict[str, int] = {}
        for a in self._apps:
            if not a["vetoed"]:
                for t in a["tags"]:
                    counts[t] = counts.get(t, 0) + 1
        return [t for t, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]

    @Property("QVariant", notify=changed)
    def installedItems(self):
        inst = [a for a in self._apps if a["state"] in ("installed", "update", "held", "pinned", "selfupdating", "system")]
        return sorted(inst, key=lambda a: (a["state"] != "update", a["name"].lower()))

    @Property(int, notify=changed)
    def updateCount(self):
        return len([a for a in self._apps if a["state"] == "update"])

    @Property("QVariant", notify=changed)
    def sourceItems(self):
        by = {a["url"]: a for a in self._apps}
        out = []
        for s in self.db.all("SELECT * FROM sources ORDER BY added_at, url"):
            a = by.get(s["url"])
            if not a:
                continue
            st = json.loads(s["settings"] or "{}")
            meta = self.db.one("SELECT error, error_code, error_extra FROM apps WHERE url=?", (s["url"],)) or {}
            out.append({**a, "trackOnly": bool(st.get("track_only")), "inputUrl": s["input_url"],
                        "errorText": self._error_text(meta), "builtin": bool(st.get("builtin")) or s["url"] == APPKATA_REPO})
        return out

    def _error_text(self, meta: dict) -> str:
        code = meta.get("error_code") or ""
        if not code:
            return ""
        extra = json.loads(meta.get("error_extra") or "{}")
        if code == "RateLimited":
            import datetime as dt
            t = dt.datetime.fromtimestamp(extra.get("reset", 0)).strftime("%H:%M")
            return f"Rate limited until {t} · add a token in Settings"
        if code == "Renamed":
            return f"Moved to {extra.get('new_url', '')}"
        return {"NoReleases": "No releases found", "NotFound": "Repository not found",
                "Unsupported": meta.get("error") or "Not supported yet"}.get(code, meta.get("error") or code)

    @Property("QVariant", notify=changed)
    def trustItems(self):
        out = []
        for t in sorted(self.db.all("SELECT * FROM trusts"), key=catalog.trust_order):
            auths = [authority_view(a) for a in catalog.authorities(self.db, t["id"])]
            enabled = [a for a in auths if a["enabled"] and not a["pending"]]
            n = self.db.one("SELECT COUNT(*) n FROM reviews WHERE trust_id=?", (t["id"],))["n"]
            warn = bool(t["problem"]) or any(a["pending"] for a in auths) or bool(json.loads(t["warnings"] or "[]"))
            out.append({"id": t["id"], "name": t["name"], "url": t["url"], "own": bool(t["own"]), "apps": n,
                        "synced": t["synced_at"] or "", "avatars": enabled or [catalog.avatar_for(t["name"], t["name"])],
                        "warn": warn, "nostr": t["url"].startswith("nostr:"), "enabled": bool(t["enabled"]),
                        "score": catalog.trust_score(t)})
        return out

    @Slot(str, result="QVariant")
    def detail(self, url: str):
        a = next((x for x in self._apps if x["url"] == url), None)
        if not a:
            return {}
        meta = self.db.one("SELECT * FROM apps WHERE url=?", (url,)) or {}
        releases = json.loads(meta.get("releases") or "[]")
        latest = releases[0] if releases else {}
        revs = []
        rows = self.db.all("""SELECT r.*, t.name tname, t.name name, t.own, t.score FROM reviews r JOIN trusts t ON t.id=r.trust_id
                              WHERE r.url=? AND t.enabled=1""", (url,))
        from appkata_core.platform import OS
        dates = catalog.release_dates(releases)
        shown = a["installed"] if a["installed"] and a["state"] != "foreign" else (a["version"] or None)
        same = []           # (Trust, SHA-256, Flatpak commit, version) from each review's Details (10.3.4)
        for r in sorted(rows, key=catalog.trust_order):
            auths = [authority_view(x) for x in catalog.authorities(self.db, r["trust_id"], include_pending=False) if x["enabled"]]
            chain = catalog.review_chain(r, OS, dates)
            cur = trustfile.review_for({}, None, shown, OS, dates, chain=chain)     # the review for this version (10.6.5)
            others = [{"version": x["version"] or "Any version", "trust": x["trust"], "rating": x["rating"], "tags": x["tags"],
                       "text": x["text"] if x["version"] else (r["section"] or ""),
                       "date": next((d[1] for d in x["details"] if d[0].lower() == "date"), ""),
                       "newer": bool(x["version"] and cur["version"] and (vcmp.compare(x["version"], cur["version"]) or 0) > 0)}
                      for x in reversed(chain) if x is not cur and (x["version"] or x["text"] or r["section"])]
            text = cur["text"] if cur["version"] else (r["section"] or "")
            det = {k.lower(): v for k, v in cur.get("details") or []}
            same.append((r["tname"] if not r["own"] else "you", det.get("sha-256", ""), det.get("commit", ""), cur["version"]))
            revs.append({"trustId": r["trust_id"], "name": "Your review" if r["own"] else r["tname"], "own": bool(r["own"]),
                         "avatars": auths or [catalog.avatar_for(r["tname"], r["tname"])], "trust": cur["trust"],
                         "rating": cur["rating"], "tags": cur["tags"], "section": text or "",
                         "reviewedVersion": cur["version"], "others": others,
                         "othersLabel": ("Other reviews" if any(o["newer"] for o in others) else "Earlier reviews") + f" ({len(others)})",
                         "score": catalog.trust_score(r)})
        asset = a.get("asset") or {}
        verify = "checksum" if (asset.get("digest") or self._has_sums(latest, asset)) else "unverified"
        signer = ""
        irow = self.db.one("SELECT record FROM installs WHERE url=?", (url,)) if a["installed"] else None
        irec = json.loads(irow["record"] or "{}") if irow else {}
        if irec.get("verified") == "signed":
            verify, signer = "signed", irec.get("signer", "")
        if a.get("ch"):            # checked by flatpak, apt or dnf against the repository's keys (requirement 16.3.6)
            verify, signer = "signed", ""
        size = asset.get("size") or 0
        # versions (requirement 5.7.5): stable releases, plus the installed one if it's a prerelease
        include_pre = bool(self.db.get("prereleases", False))
        vers = [r for r in releases if include_pre or not r.get("prerelease") or r["version"] == a["installed"]]
        newest = a["updateTo"] or a["version"]
        kept = set(install.kept_versions(self.db, url))
        vscore = catalog.version_scores(self.db, url, [r["version"] for r in vers]) if rows else {}
        versions = [{"version": r["version"], "date": r["date"], "installed": r["version"] == a["installed"], "kept": r["version"] in kept,
                     "newest": r["version"] == newest, "files": len(r.get("assets") or []), "tag": r.get("tag", ""),
                     "trust": (vscore.get(r["version"]) or (None, False))[0], "avoided": (vscore.get(r["version"]) or (None, False))[1]}
                    for r in vers]
        inst_i = next((i for i, v in enumerate(versions) if v["installed"]), -1)
        new_i = next((i for i, v in enumerate(versions) if v["newest"]), 0)
        mine = {}
        if a["installed"] and a["state"] != "foreign" and not a.get("self"):    # the installed version's score (10.6.5)
            mine = {"trust": a["installedTrust"], "rating": a["installedRating"], "vetoed": a["installedVetoed"]}
        # the file or Flatpak commit a reviewer had is the one here (requirement 10.3.4)
        mine_sha = mine_commit = ""
        if a["installed"] and a["state"] != "foreign":
            irow2 = self.db.one("SELECT asset FROM installs WHERE url=?", (url,)) or {}
            rel_i = next((r for r in releases if r["version"] == a["installed"]), None) or {}
            ast = next((x for x in rel_i.get("assets") or [] if x.get("name") == irow2.get("asset")), None) or {}
            mine_sha, mine_commit = (ast.get("digest") or "").removeprefix("sha256:"), irec.get("commit", "")
        else:
            mine_sha = (asset.get("digest") or "").removeprefix("sha256:")
        same_as = [t for t, sha, com, _ in same if (sha and _same_digest(sha, mine_sha)) or (com and _same_digest(com, mine_commit))]
        chans, blocker = [], ""
        if self.ch.enabled and not a.get("self"):
            try:
                chans = self.ch.summary(url)
                if a.get("ch") and a["ch"]["kind"] == "package" and not self.ch.fake:
                    blocker = install.uninstall_blocker(irec)
            except Exception:      # noqa: BLE001 — never break the panel
                log.exception("channels for %s", url)
        return {**a, **mine, "readme": _plain_readme(meta.get("readme") or ""),
                "channels": chans, "uninstallBlocker": blocker or (a.get("ch") or {}).get("blocker", ""),
                "sameFileAs": same_as, "notes": _plain_readme(latest.get("notes") or ""),
                "versions": versions, "versionsShown": max(inst_i, new_i) + 1 + 5,
                "reviews": revs, "releases": [{"version": r["version"], "date": r["date"], "prerelease": r["prerelease"]} for r in releases[:15]],
                "verify": verify, "signer": signer, "scope": irec.get("scope", ""),
                "reportedVersion": irec.get("reported", "") if irec.get("reported") and irec.get("reported") != a["installed"] else "",
                "assetLabel": (asset.get("kind") or "").replace("appimage", "AppImage").replace("tarball", "tar.gz"),
                "size": f"{size / 1e6:.0f} MB" if size else "", "archived": bool(meta.get("archived")),
                "sandbox": self.sandboxInfo(url)}

    def _has_sums(self, rel: dict, asset: dict) -> bool:
        from appkata_core.assets import checksum_for
        if not asset:
            return False
        assets = [Asset(**x) for x in rel.get("assets", [])]
        a = next((x for x in assets if x.name == asset.get("name")), None)
        return bool(a and checksum_for(a, assets))

    @Slot(int, result="QVariant")
    def trustDetail(self, tid: int):
        t = self.db.one("SELECT * FROM trusts WHERE id=?", (tid,))
        if not t:
            return {}
        auths = [authority_view(a) for a in catalog.authorities(self.db, tid)]
        n = self.db.one("SELECT COUNT(*) n FROM reviews WHERE trust_id=?", (tid,))["n"]
        return {**t, "own": bool(t["own"]), "apps": n, "warnings": json.loads(t["warnings"] or "[]"), "score": catalog.trust_score(t),
                "authorities": auths, "verifiedShort": (t["verified_commit"] or "")[:7]}

    # ---------------------------------------------------------------- prefs
    @Property("QVariant", notify=prefsChanged)
    def prefs(self):
        return self._prefs

    @Slot(str, "QVariant")
    def setPref(self, key: str, value) -> None:
        self._prefs[key] = _plain(value)
        prefs_mod.save(self._prefs)
        self.prefsChanged.emit()
        if key == "sort":
            self.changed.emit()
        if key == "syncHours":
            self._arm_timer()
        if key == "prereleases":
            self.db.put("prereleases", bool(value)); self.reload()
        if key == "minAgeDefault":
            self.db.put("min_age_default", int(value or 0)); self.reload()
        if key == "startInTray":
            try:
                desktop.set_autostart(bool(value))
            except OSError as e:
                self.toast.emit("error", f"Couldn't change start at login: {e}")
        if key in ("installDir", "installDirEveryone", "installFor", "appMenu", "stableName", "commandLinks", "commandDir", "relays", "startInTray",
                   "prereleases", "minAgeDefault", "syncHours", "notifications"):
            log.info("setting %s = %r", key, value)
        if key == "reviewPath" and value:
            self._audit("you", "setting", "chose the review file", str(value))
            self._ensure_own_trust()
            self.reload()

    @Property("QVariant", notify=prefsChanged)
    def tokens(self):
        return self.db.get("tokens", {})

    @Slot(str, str)
    def setToken(self, host: str, token: str) -> None:
        t = self.db.get("tokens", {})
        if token:
            t[host.lower()] = token
        else:
            t.pop(host.lower(), None)
        self.db.put("tokens", t)
        self.http.tokens = t
        self._audit("you", "setting", "set an API token for" if token else "removed the API token for", host.lower())
        self.prefsChanged.emit()

    # ---------------------------------------------------------------- sync
    @Property(bool, notify=syncChanged)
    def syncing(self):
        return self._syncing

    @Property(int, notify=syncChanged)
    def syncDone(self):
        return self._sync.done

    @Property(int, notify=syncChanged)
    def syncTotal(self):
        return self._sync.total

    @Property(str, notify=syncChanged)
    def syncCurrent(self):
        return self._sync.current

    @Property(str, notify=syncChanged)
    def lastSync(self):
        return self.db.get("last_sync", "") or ""

    def _arm_timer(self) -> None:
        h = float(self._prefs.get("syncHours") or 0)
        self._timer.stop()
        if h > 0:
            self._timer.start(int(h * 3600 * 1000))

    def _background_sync(self) -> None:
        before = self.updateCount
        avoided = {a["url"]: a["installed"] for a in self._apps if a.get("installedVetoed")}
        def done():
            if self._prefs.get("notifications", True) and self.updateCount > before:
                names = [a["name"] for a in self.installedItems if a["state"] == "update"]
                self.notify.emit(f"{len(names)} app update{'s' if len(names) != 1 else ''} available", ", ".join(names[:4]))
            if self._prefs.get("notifications", True):        # an installed version newly avoided (10.6.5)
                for a in self._apps:
                    if a.get("installedVetoed") and avoided.get(a["url"]) != a["installed"]:
                        self.notify.emit(f"A trusted reviewer says to avoid {a['name']} {a['installed']}", (a.get("avoid") or {}).get("note", ""))
        self.syncNow(done)

    @Slot()
    def sync(self) -> None:
        self.syncNow()

    def syncNow(self, after=None) -> None:
        if self._syncing:
            return
        self._syncing = True
        self._sync = sync.Progress()
        self.syncChanged.emit()

        def work():
            try:
                sync.sync_all(self.db, self.http, self._sync, on_item=lambda: self.syncChanged.emit())
                foreign.scan(self.db)
            except Exception as e:        # noqa: BLE001 — a sync must never take the app down
                traceback.print_exc()
                self._toast.emit("error", f"Sync failed: {e}")
            finally:
                self._syncing = False
                self.syncChanged.emit()
                self._refresh.emit()
                if after:
                    QTimer.singleShot(0, after)
        threading.Thread(target=work, daemon=True).start()

    @Slot()
    def cancelSync(self) -> None:
        self._sync.cancelled = True

    # ---------------------------------------------------------------- installs
    @Property("QVariant", notify=busyChanged)
    def busy(self):
        return self._busy

    def _app(self, url: str) -> dict | None:
        return next((a for a in self._apps if a["url"] == url), None)

    @Slot(str)
    def install(self, url: str) -> None:
        """Install, or update. The first install probes the release and asks only when there's a
        real choice to make (requirement 4.9); later installs reuse the saved choice."""
        a = self._app(url)
        if not a:
            return
        if a["installed"] or a.get("installChoice"):
            self._install(url, "")
            return
        def work():
            plan = self._plan(url, a["version"])
            if plan.get("error") or not plan["ask"]:
                choice = plan["candidates"][plan["chosen"]] if plan.get("candidates") else None
                QTimer.singleShot(0, lambda: self._install(url, "", choice))
            else:
                self.installPlan.emit(plan)
        threading.Thread(target=work, daemon=True).start()

    @Slot(str, result="QVariant")
    def planFor(self, url: str):
        """The same probe for "Install options…" on an installed app (and the tour)."""
        a = self._app(url)
        return self._plan(url, a["updateTo"] or a["version"]) if a else {}

    def _plan(self, url: str, version: str) -> dict:
        from appkata_core.assets import candidates, category, exe_type
        from appkata_core.platform import OS, arch, linux_family
        a = self._app(url) or {}
        out = {"url": url, "name": a.get("name", ""), "version": version, "candidates": [], "chosen": 0, "ask": False,
               "reasons": [], "os": {"linux": "Linux", "windows": "Windows", "macos": "macOS"}[OS] + " " + arch()}
        try:
            rel = sync.ensure_assets(self.db, self.http, url, version)
        except SourceError as e:
            return {**out, "error": str(e)}
        assets = [Asset(**x) for x in (rel or {}).get("assets", [])]
        saved = a.get("installChoice") or {}
        p = self.portable()
        for ch in candidates(assets, OS, arch(), linux_family()):
            ek = ""
            if ch.kind == "exe":        # look inside the file for an installer's markers (requirement 4.2.1)
                ek = exe_type(ch.asset.name, install.head_bytes(ch.asset.url), [x.name for x in assets])
            cat = category(ch.kind, ek)
            from appkata_core.windows import scopes
            out["candidates"].append({"scopes": scopes(ch.kind, ek) if OS == "windows" else [],
                "name": ch.asset.name, "kind": ch.kind, "exeKind": ek, "category": cat, "size": ch.asset.size,
                "label": {"appimage": "AppImage", "tarball": "tar archive", "zip": "zip archive", "flatpak": "Flatpak bundle",
                          "exe": ".exe", "deb": ".deb package", "rpm": ".rpm package", "msi": ".msi installer", "msix": ".msix package",
                          "dmg": "disk image", "pkg": ".pkg installer"}.get(ch.kind, ch.kind),
                "admin": cat == "system" and ch.kind not in ("flatpak",),
                "manager": {"deb": "apt", "rpm": "dnf", "flatpak": "flatpak --user"}.get(ch.kind, "its installer")})
            if ch.kind == "exe" and ek in ("squirrel", "electron"):       # updates itself (requirement 15.7.1)
                out["candidates"][-1]["updatesItself"] = ek == "squirrel"
        # package channels next to the release's files (requirement 16.3.1)
        releases = json.loads((self.db.one("SELECT releases FROM apps WHERE url=?", (url,)) or {}).get("releases") or "[]")
        out["cards"] = self.ch.cards(url, out["candidates"], releases) if self.ch.enabled and OS == "linux" \
            else [{"channel": "release", **c} for c in out["candidates"]]
        if self.ch.fake:
            out["os"] = self.ch.fake.get("os", out["os"])
        if not out["cards"]:
            return {**out, "error": f"no download for {out['os']} in {version}"}
        cats = {c["category"] for c in out["candidates"]}
        if len(cats - {"unknown"}) > 1:
            out["reasons"].append("both")
        if "unknown" in cats:
            out["reasons"].append("exe")
        if any(c["channel"] != "release" for c in out["cards"]):
            out["reasons"].append("channels")      # 16.3.3
        out["ask"] = bool(out["reasons"])
        want, want_ch = saved.get("kind"), saved.get("channel")
        out["chosen"] = next((i for i, c in enumerate(out["cards"]) if want_ch and c["channel"] == want_ch), None)
        if out["chosen"] is None:
            out["chosen"] = next((i for i, c in enumerate(out["cards"]) if want and c.get("kind") == want), 0)
        out["updates"] = saved.get("updates", "")
        out["distro"] = self.ch.distro if self.ch.enabled else ""
        eff, rec = self._app_options(url), self._recommended(url)
        out["portable"] = {"folder": p.root, "appMenu": eff.app_menu, "commandLink": bool(eff.command_dir),
                           "stableName": eff.stable_name, "commandDir": self._prefs.get("commandDir") or "~/bin",
                           "command": self._app_id(url), "keep": p.keep,
                           "recommendedBy": rec.get("by", "") if not saved else ""}
        out["autoUpdate"], out["autoUpdateBy"] = bool(a.get("autoUpdate")), a.get("autoUpdateBy", "")
        # the Sandbox card (17.3, C11): the chosen template, its live summary, and the disk cost of
        # unpacking an AppImage when it's sandboxed (17.7).
        chosen_card = out["cards"][out["chosen"]] if out["cards"] else {}
        if OS == "linux" and chosen_card.get("kind") in ("appimage", "tarball"):
            r = self._resolved_sandbox(url, kind=chosen_card["kind"]) or {}
            gs = r.get("grants") or sandbox.to_json(sandbox.resolve_template("strict"))
            img_mb = (next((c["size"] for c in out["candidates"] if c.get("kind") == "appimage"), 0) or 0) / 1e6
            out["sandbox"] = {"applicable": True, "source": r.get("source", "default"),
                              "template": r.get("template", "strict"), "level": sandbox.level_of(gs),
                              "chips": sandbox.summary_chips(gs, self._app_options(url).root, r.get("template")) + sandbox.refused_chips(r.get("refused")),
                              "grants": gs, "suggestsOff": self._suggests_off(url),
                              "templates": self.sandboxTemplates,
                              "isCli": self._is_cli(url), "appImage": chosen_card["kind"] == "appimage",
                              "recommendedBy": self._sandbox_reviewer(url),
                              "support": self._sb_support(), "sessionWarning": self._sb_session_warning(),
                              "freshWarning": self._fresh_warning(url),
                              "extractMb": round(img_mb * 2.5) if chosen_card["kind"] == "appimage" and sandbox.level_of(gs) != "off" else 0}
            # the app's kind (17.3.3, review 2 F4): what the download showed, the user's own choice, and
            # the card as each kind would have it, so the dialog's kind choice moves the card live
            by_kind = {}
            for k in ("gui", "cli"):
                rk = self._resolved_sandbox(url, kind=chosen_card["kind"], is_cli=k == "cli") or {}
                gk = rk.get("grants") or gs
                by_kind[k] = {"template": rk.get("template", "strict"), "level": sandbox.level_of(gk), "source": rk.get("source", "default"),
                              "chips": sandbox.summary_chips(gk, self._app_options(url).root) + sandbox.refused_chips(rk.get("refused"))}
            out["sandbox"]["byKind"] = by_kind
            out["kind"] = {"detected": self._detected_kind(url), "choice": self._install_settings(url).get("cliKind") or ""}
        else:
            out["sandbox"] = {"applicable": False}
        if OS == "windows":
            out["windows"] = {"scope": eff.scope, "motw": eff.motw, "folderEveryone": install.Portable(
                scope="everyone", folder_everyone=self._prefs.get("installDirEveryone") or "").root,
                "folderMe": install.Portable(folder=self._prefs.get("installDir") or "").root}
        return out

    # the install dialog's own keys in app_settings.install: how to install (4.9.3) and the package
    # channel (16.3). Everything else in that row — the sandbox pin, the "seen" marker, the user's
    # sandbox choice — belongs to other code and survives a dialog answer.
    _PORTABLE_KEYS = ("kind", "exeKind", "appMenu", "commandLink", "stableName", "autoUpdate", "scope", "motw", "cliKind")
    _CHANNEL_KEYS = ("channel", "updates")

    def _answer_install_dialog(self, url: str, answer: dict) -> None:
        """Replace the install dialog's keys in the app's settings row with this answer, keeping the
        rest. Regression (decision 5, 17.11): the row was rewritten from the dialog's fields alone, so
        re-saving Install options dropped `sandboxPinned`, `sandboxReviewSeen` and a `sandbox` choice
        the dialog didn't send (it only sends the card when it was touched), and the next install
        re-pinned from the current reviews — the silent widening the pin exists to prevent."""
        saved = self._install_settings(url)
        for k in self._PORTABLE_KEYS + self._CHANNEL_KEYS:
            saved.pop(k, None)
        saved.update(answer)
        self._set_install_settings(url, saved)

    @Slot(str, "QVariant")
    def installWith(self, url: str, choice) -> None:
        """The install dialog's answer: saved for updates, then installed (requirement 4.9.3)."""
        c = dict(_plain(choice))
        if c.get("channel") in ("flatpak", "package"):        # a package channel (requirement 16.3)
            self._choose_channel(url, c)
            return
        kind_was = self._is_cli(url)
        before_options = self._resolved_sandbox(url)          # what the Audit compares a sandbox change with (17.16)
        saved = {k: c[k] for k in self._PORTABLE_KEYS if k in c and not (k == "cliKind" and c[k] not in ("cli", "gui"))}
        if c.get("sandbox") is not None and sandbox.config_error(c["sandbox"]):
            self._toast.emit("error", f"That sandbox choice can't be applied: {sandbox.config_error(c['sandbox'])}.")
            c.pop("sandbox")
        if c.get("sandbox") is not None:         # the Sandbox card's choice, when the user changed it (17.11)
            saved["sandbox"] = dict(c["sandbox"])
            # the card shows "suggested by <reviewer>" beside the dropdown, so this choice was made
            # knowing the suggestion: the review badge must not greet the user after the install (17.11)
            saved["sandboxReviewSeen"] = self._review_suggestion_summary(url)
        self._answer_install_dialog(url, saved)
        a = self._app(url)
        self._audit("you", "app", "chose how to install", a["name"] if a else url, url,
                    {"as": c.get("label") or c.get("kind"), "portable": c.get("category") == "portable"})
        self.reload()
        if c.get("install", True):
            self._install(url, "", c)
        elif a and a.get("installed") and c.get("scope") and c["scope"] != self._installed_scope(url):
            self._install(url, a["installed"], c, pin=False)     # for someone else now: reinstall it (15.4.1)
        elif (a and a.get("installed") and not a.get("foreign") and c.get("sandbox") is None and kind_was != self._is_cli(url)
              and self._user_sandbox_config(url) is None):
            # the user corrected the app's kind (17.3.3): with no sandbox of their own, the default for
            # that kind applies now, as a choice in the dialog would (review 2, F4)
            before = self._resolved_sandbox(url)
            self._pin_sandbox(url, None)
            self._pin_sandbox(url, self._resolved_sandbox(url))
            self._regenerate_launcher(url)
            r = self._resolved_sandbox(url)
            self._audit("you", "app", "set the sandbox of", a["name"], url,
                        self._sandbox_detail(url, before, r, kind="command-line tool" if self._is_cli(url) else "app"))
            self.reload()
        elif c.get("sandbox") is not None and a and a.get("installed") and not a.get("foreign"):
            # Install options... on an installed app: the sandbox choice applies now, as the Sandbox
            # dialog's does, and is audited like it (17.16). Round four, R4-3: it was saved and shown
            # in App Detail as in force while the launcher kept the old grants until the next update.
            self._regenerate_launcher(url)
            r = self._resolved_sandbox(url)
            self._audit("you", "app", "set the sandbox of", a["name"], url, self._sandbox_detail(url, before_options, r))
            self.reload()

    # ---------------------------------------------------------------- package channels (requirement 16)
    def _choose_channel(self, url: str, c: dict) -> None:
        a = self._app(url)
        opt = dict(c.get("option") or {})
        saved = {"channel": c["channel"], **({"updates": c["updates"]} if c.get("updates") else {})}
        self._answer_install_dialog(url, saved)
        self._audit("you", "app", "chose how to install", a["name"] if a else url, url,
                    {"as": c.get("label") or c["channel"], **({"updates": c["updates"]} if c.get("updates") else {})})
        if not c.get("install", True):          # Install options…: who updates it (16.5.3)
            if a and a.get("ch") and c.get("updates"):
                install.set_update_owner(self.db, url, c["updates"])
            self.reload()
            return
        self.reload()
        self._install_channel(url, opt, c.get("updates", ""))

    @Slot(str, "QVariant", str)
    def addFlathubAndInstall(self, url: str, option, updates: str) -> None:
        """The answer to "Add Flathub?" (16.3.4)."""
        self._install_channel(url, dict(_plain(option)), updates, add_flathub=True)

    @Slot(str, "QVariant", str)
    def installChannelConfirmed(self, url: str, option, updates: str) -> None:
        """Install after the user confirmed a plan that changes other packages (16.3.5)."""
        self._install_channel(url, dict(_plain(option)), updates, confirmed=True)

    def _install_channel(self, url: str, option: dict, updates: str, confirmed: bool = False, add_flathub: bool = False,
                         update: bool = False) -> None:
        from appkata_core.pkgbackend import NeedsConfirmation, PackageError, Refused
        a = self._app(url)
        if not a or url in self._busy:
            return
        self._cancel.discard(url)
        self._busy[url] = {"phase": "Waiting", "progress": 0.0, "got": 0, "total": 0, "speed": 0}
        self.busyChanged.emit()

        def prog(frac, *_):
            f = frac if isinstance(frac, float) and frac <= 1 else 0.0
            self._busy[url] = {**self._busy.get(url, {}), "phase": "Installing", "progress": f}
            self.busyChanged.emit()

        def phase(name):
            self._busy[url] = {**self._busy.get(url, {}), "phase": name}
            self.busyChanged.emit()

        def waiting(holder):
            self._busy[url] = {**self._busy.get(url, {}), "phase": "Waiting", "holder": holder}
            self.busyChanged.emit()

        def work():
            self._install_lock.acquire()
            was = a["installed"]
            try:
                cancel = lambda: url in self._cancel
                if update:
                    rec = install.update_channel(self.db, url, prog, cancel, waiting, confirmed)
                else:
                    rec = install.install_channel(self.db, a, option, prog, cancel, phase, waiting, confirmed, add_flathub)
                    if updates:
                        install.set_update_owner(self.db, url, updates)
                row = self.db.one("SELECT version FROM installs WHERE url=?", (url,)) or {}
                self._audit("you", "app", "updated" if update else "installed", a["name"], url,
                            {"version": row.get("version", ""), "from": was or None,
                             "channel": rec.get("flatpak") and "Flatpak " + rec["flatpak"] or rec.get("package") and f"{rec.get('manager')} {rec['package']}"})
                self._toast.emit("info", f"{a['name']} {row.get('version', '')} {'updated' if update else 'installed'}.")
            except install.NeedsFlathub:
                self._flathubNeeded.emit({"url": url, "name": a["name"], "option": option, "updates": updates})
            except NeedsConfirmation as e:
                self._planConfirm.emit({"url": url, "name": a["name"], "action": "update" if update else "install",
                                        "lines": list(e.lines), "option": option, "updates": updates})
            except Refused as e:
                self._planConfirm.emit({"url": url, "name": a["name"], "action": "update" if update else "install",
                                        "lines": [str(e)], "refused": True})
            except install.Cancelled:
                self._toast.emit("info", f"{a['name']}: cancelled.")
            except (install.InstallError, PackageError, SourceError) as e:
                log.warning("channel install %s failed: %s", a["name"], e)
                self._toast.emit("error", f"{a['name']}: {e}")
            except Exception as e:      # noqa: BLE001
                log.exception("channel install %s crashed", a["name"])
                self._toast.emit("error", f"{a['name']}: {e}")
            finally:
                self._install_lock.release()
                self._cancel.discard(url)
                self._busy.pop(url, None)
                self.busyChanged.emit()
                self._refresh.emit()
        threading.Thread(target=work, daemon=True).start()

    @Slot(str)
    def updateChannelConfirmed(self, url: str) -> None:
        self._install_channel(url, {}, "", confirmed=True, update=True)

    @Slot(str)
    def adopt(self, url: str) -> None:
        """Track a copy installed outside AppKata that a channel matches exactly (16.4.2)."""
        a = self._app(url)
        try:
            rec = foreign.adopt(self.db, url)
        except (ValueError, install.InstallError) as e:
            self.toast.emit("error", str(e))
            return
        self._audit("you", "app", "adopted", a["name"] if a else url, url,
                    {"channel": rec.get("flatpak") and "Flatpak " + rec["flatpak"] or f"{rec.get('manager')} {rec.get('package')}"})
        self.toast.emit("info", f"{a['name'] if a else 'The app'} is now tracked by AppKata.")
        self.reload()

    @Slot(str)
    def uninstallConfirmed(self, url: str) -> None:
        self._uninstall(url, True)

    def _installed_scope(self, url: str) -> str:
        row = self.db.one("SELECT record FROM installs WHERE url=?", (url,))
        return json.loads(row["record"] or "{}").get("scope", "me") if row else ""

    @Slot(str, str)
    def installVersion(self, url: str, version: str) -> None:
        """Install a chosen (usually older) version, and pin it there (requirement 5.7.5)."""
        self._install(url, version)

    @Slot(str)
    def installReleaseConfirmed(self, url: str) -> None:
        """Install a release's .deb or .rpm after confirming the packages it changes (16.3.5)."""
        self._install(url, "", None, confirmed=True)

    def _install(self, url: str, version: str, choice=None, pin: bool = True, confirmed: bool = False,
                 asked: bool = False) -> None:
        a = self._app(url)
        if not a or url in self._busy:
            return
        if not asked and self._setup_prompt_needed(url, choice):     # the first need: ask before installing (17.10)
            self.sandboxSetupNeeded.emit({"url": url, "name": a["name"], "version": version, "choice": choice or {},
                                          "pin": pin, "confirmed": confirmed,
                                          "waitingNote": self._sb_support().get("waitingNote", "")})
            return
        if a.get("self") and (not a.get("selfManaged") or a.get("trackOnly")):   # notify only (2.11.4, 2.11.6)
            Qt_open = __import__("PySide6.QtGui", fromlist=["QDesktopServices"]).QDesktopServices
            from PySide6.QtCore import QUrl
            Qt_open.openUrl(QUrl(url + "/releases"))
            return
        if a["foreign"]:
            self.toast.emit("error", f"{a['name']} is installed outside AppKata; uninstall that copy first.")
            return
        if a.get("ch"):                    # installed from a package channel: update through it (16.5.5)
            self._install_channel(url, {}, "", update=True)
            return
        target = version or a["updateTo"] or a["version"]
        was = a["installed"]
        had = self._sandbox_state(url)            # (a launcher, a fresh home): what this install may change (17.13)
        self._cancel.discard(url)
        self._busy[url] = {"phase": "Waiting", "progress": 0.0, "got": 0, "total": 0, "speed": 0}
        self.busyChanged.emit()
        started = [0.0, 0]          # time and bytes of the last speed sample

        def prog(got, total):
            t = time.monotonic()
            b = self._busy.get(url, {})
            speed = b.get("speed", 0)
            if t - started[0] >= 0.5:
                speed = (got - started[1]) / (t - started[0]) if started[0] else 0
                started[0], started[1] = t, got
            self._busy[url] = {"phase": "Downloading", "progress": got / total if total else 0.0, "got": got, "total": total,
                               "speed": speed}
            self.busyChanged.emit()

        def phase(name):
            self._busy[url] = {**self._busy.get(url, {}), "phase": name, "progress": 1.0}
            self.busyChanged.emit()

        def work():
            self._install_lock.acquire()
            try:
                if url in self._cancel:
                    raise install.Cancelled()
                started[0] = time.monotonic()
                self._busy[url] = {**self._busy[url], "phase": "Downloading"}
                self.busyChanged.emit()
                rel = sync.ensure_assets(self.db, self.http, url, target)
                from appkata_core.assets import choose
                from appkata_core.platform import OS, arch, linux_family
                assets = [Asset(**x) for x in (rel or {}).get("assets", [])]
                saved = dict(choice or {}) or a.get("installChoice") or {}
                prefer = saved.get("kind") or a.get("installKind") or ""
                ch = catalog.choose_with(a.get("sourceSettings") or {}, assets, OS, arch(), linux_family(), prefer)
                if not rel or not ch.asset:
                    raise install.InstallError(f"no download for this computer in {target}")
                ek = saved.get("exeKind", "")
                if ch.kind == "exe" and not ek:
                    from appkata_core.assets import exe_type
                    ek = exe_type(ch.asset.name, install.head_bytes(ch.asset.url), [x.name for x in assets])
                port = self._app_options(url, choice)
                sbx = self._sandbox_for_install(url, kind=ch.kind)    # the grant set to bake in (17.4, 17.11)
                rec = {}
                if pin and target in install.kept_versions(self.db, url):      # a kept version: no download (4.3.1.5)
                    install.switch_to(self.db, {**a, "sandbox": sbx}, target, port, rel["date"])
                else:
                    # the app's kind is known once its files are placed (17.3.3, review 2 F4): install()
                    # asks for the grant set again with it, and drops a command-line tool's menu entry
                    # when that option was only Settings' default
                    ck = self._install_settings(url).get("cliKind")
                    rec = install.install(self.db, {**a, "date": rel["date"], "installVersion": target, "exeKind": ek,
                                                    "autoUpdate": self._updates_itself(a, sbx), "selfSetup": bool(a.get("self")),
                                                    "sandbox": sbx, "confirmed": confirmed,
                                                    "sandbox_for_kind": lambda is_cli, k=ch.kind: self._sandbox_for_install(url, kind=k, is_cli=is_cli),
                                                    "menuFromDefault": self._menu_from_default(url, choice, a),
                                                    **({"cliKind": ck} if ck in ("cli", "gui") else {})},
                                          ch.asset, ch.kind, assets, prog, cancel=lambda: url in self._cancel, portable=port,
                                          phase=phase)
                    if rec.get("restart"):
                        self._toast.emit("info", f"Restart Windows to finish installing {a['name']}.")
                    if rec.get("msvcrt"):
                        from appkata_core.windows import msvcrt_installed
                        if not msvcrt_installed():
                            self._msvcrtNeeded.emit({"url": url, "name": a["name"]})
                if "appMenu" in (rec.get("options") or {}):       # what install() applied (a tool's menu entry dropped)
                    port.app_menu = bool(rec["options"]["appMenu"])
                self._save_options(url, port, {"kind": ch.kind, "exeKind": ek} if ek else {"kind": ch.kind})
                self._settle_sandbox(url, ch.kind, had if was else None)
                action = "updated" if was and not version else "installed" if pin else "reinstalled"
                if version and pin:      # an older version stays put until unpinned
                    self.db.x("INSERT INTO app_settings(url, pinned) VALUES(?,?) ON CONFLICT(url) DO UPDATE SET pinned=excluded.pinned",
                              (url, target))
                self._audit("you", "app", action, a["name"], url, {"version": target, "from": was or None, "file": ch.asset.name,
                                                                    "pinned": bool(version and pin),
                                                                    **({"launcher": h} if (h := self._launcher_hash(url)) else {})})
                if a.get("self"):
                    self._toast.emit("info", f"AppKata {target} installed. Restart AppKata to use it.")
                else:
                    self._toast.emit("info", f"{a['name']} {target} installed" + (" and pinned." if version else "."))
            except PackageNeedsConfirmation as e:          # a .deb/.rpm that changes other packages (16.3.5)
                self._planConfirm.emit({"url": url, "name": a["name"], "action": "install-release", "lines": list(e.lines)})
            except PackageRefused as e:
                self._planConfirm.emit({"url": url, "name": a["name"], "action": "install-release", "lines": [str(e)], "refused": True})
            except install.Cancelled:
                log.info("install %s %s cancelled", a["name"], target)
                self._toast.emit("info", f"{a['name']}: cancelled.")
            except install.InUse as e:
                log.info("install %s %s waits: running from %s", a["name"], target, e.programs)
                self._inUse.emit({"url": url, "name": a["name"], "action": "install", "version": version,
                                  "programs": [os.path.basename(x) for x in e.programs]})
            except (install.InstallError, SourceError) as e:
                log.warning("install %s %s failed: %s", a["name"], target, e)
                self._toast.emit("error", f"{a['name']}: {e}")
            except Exception as e:      # noqa: BLE001
                log.exception("install %s %s crashed", a["name"], target)
                self._toast.emit("error", f"{a['name']}: {e}")
            finally:
                self._install_lock.release()
                self._cancel.discard(url)
                self._busy.pop(url, None)
                self.busyChanged.emit()
                self._refresh.emit()
        threading.Thread(target=work, daemon=True).start()

    @Slot()
    def installMsvcrt(self) -> None:
        """Microsoft's Visual C++ run-time, for every app that needs it (requirement 15.18.3)."""
        def work():
            try:
                meaning = install.install_msvcrt()
                self._audit("you", "app", "installed", "Microsoft Visual C++ Run-time", "", {"from": "Microsoft"})
                self._toast.emit("info", "Microsoft Visual C++ Run-time installed." +
                                 (" Restart Windows to finish." if meaning == "restart" else ""))
            except install.Cancelled:
                self._toast.emit("info", "Visual C++ run-time: cancelled.")
            except install.InstallError as e:
                self._toast.emit("error", f"Visual C++ run-time: {e}")
            self._refresh.emit()
        threading.Thread(target=work, daemon=True).start()

    @Slot(str)
    def cancelInstall(self, url: str) -> None:
        """Stop a download (its partial file is deleted) or take a waiting app out of the queue (4.8.3)."""
        if url in self._busy:
            self._cancel.add(url)
            if self._busy[url].get("phase") == "Waiting":
                self._busy[url] = {**self._busy[url], "phase": "Cancelling"}
                self.busyChanged.emit()

    @Property(bool, notify=busyChanged)
    def installing(self) -> bool:
        return bool(self._busy)

    @Slot(str)
    def update(self, url: str) -> None:
        a = self._app(url)
        if a and a["state"] == "selfupdating":
            self.toast.emit("info", f"{a['name']} updates itself.")
            return
        if a and a["state"] == "system":
            self.toast.emit("info", f"{a['name']} is updated by {a['ch'].get('updatesBy') or 'the system'}.")
            return
        if a and a.get("permsGrow"):           # asks first (requirement 16.6.3)
            self.permsNeeded.emit(url)
            return
        self.install(url)

    @Slot(str)
    def updateWithPermissions(self, url: str) -> None:
        """The user accepted an update that asks for more permissions (16.6.3)."""
        self.install(url)

    @Slot()
    def updateAll(self) -> None:
        """Queues every update; they install one at a time (requirement 4.8.1). Apps that update
        themselves aren't in it (4.10.1)."""
        for a in [x for x in self._apps if x["state"] == "update" and not x.get("trackOnly") and not x.get("updateAvoided")
                  and not x.get("permsGrow")]:          # an update asking for more permissions asks first (16.6.3)
            self.install(a["url"])

    @Slot(str)
    def uninstall(self, url: str) -> None:
        self._uninstall(url, False)

    def _uninstall(self, url: str, confirmed: bool, remove_home: bool = False) -> None:
        from appkata_core.pkgbackend import NeedsConfirmation, Refused
        a = self._app(url)
        if url == APPKATA_REPO:
            self.toast.emit("error", "AppKata can't uninstall itself.")
            return
        def work():
            try:
                ver = a["installed"] if a else ""
                install.uninstall(self.db, url, confirmed=confirmed, remove_sandbox=remove_home)
                self._pin_sandbox(url, None)        # a reinstall resolves its sandbox afresh (17.11)
                self._audit("you", "app", "uninstalled", a["name"] if a else url, url, {"version": ver})
                self._toast.emit("info", f"{a['name'] if a else 'App'} uninstalled.")
            except NeedsConfirmation as e:          # it would remove other packages too (16.4.3)
                self._planConfirm.emit({"url": url, "name": a["name"] if a else "", "action": "uninstall", "lines": list(e.lines)})
            except Refused as e:
                self._planConfirm.emit({"url": url, "name": a["name"] if a else "", "action": "uninstall", "lines": [str(e)],
                                        "refused": True})
            except install.Cancelled:
                self._toast.emit("info", f"{a['name'] if a else 'App'}: cancelled.")
            except install.InUse as e:
                self._inUse.emit({"url": url, "name": a["name"] if a else "", "action": "uninstall", "version": "",
                                  "programs": [os.path.basename(x) for x in e.programs]})
            except install.InstallError as e:
                self._toast.emit("error", str(e))
            self._refresh.emit()
        from appkata_core.platform import OS
        if OS == "windows" or (a and (a.get("ch") or a.get("installKind") in ("deb", "rpm"))):
            threading.Thread(target=work, daemon=True).start()     # installers, UAC and package managers take a while
        else:
            work()

    @Slot(str)
    def openApp(self, url: str) -> None:
        a = self._app(url)
        name = a["name"] if a else "The app"

        def failed(code: int, tail: list[str]) -> None:       # from the watching thread: _toast, like every worker
            why = next((l for l in reversed(tail) if l), "")
            self._toast.emit("error", f"{name} didn't start (exit {code})" + (f": {why}" if why else "") + ". See the App log.")
        try:
            install.launch(self.db, url, on_failed=failed)
        except install.InstallError as e:
            self.toast.emit("error", str(e))

    @Slot(str, bool)
    def setPinned(self, url: str, on: bool) -> None:
        a = self._app(url)
        ver = a["installed"] if a else ""
        if a and a.get("ch"):              # a Flatpak is masked; a package can't be pinned (16.5.6)
            try:
                install.set_pinned(self.db, url, on)
            except install.InstallError as e:
                self.toast.emit("error", str(e))
                return
        self.db.x("INSERT INTO app_settings(url, pinned) VALUES(?,?) ON CONFLICT(url) DO UPDATE SET pinned=excluded.pinned",
                  (url, ver if on else None))
        self._audit("you", "app", "pinned" if on else "unpinned", a["name"] if a else url, url, {"version": ver} if on else None)
        self.reload()


    # ---------------------------------------------------------------- sources
    @Slot(str)
    def previewSource(self, text: str) -> None:
        def work():
            out = {"input": text}
            try:
                repo = urls.parse(text)
                out.update(url=repo.url, host=repo.host, releasesPage=repo.releases_page)
                if repo.kind != "forge":
                    raise SourceError("ngit sources come in a later version")
                from appkata_core import forges
                kind = forges.detect(self.http, repo.host)
                f = forges.forge_for(self.http, repo, kind)
                info = f.info()
                rels = f.releases()
                rel = forges.latest(rels)
                from appkata_core.assets import choose
                from appkata_core.platform import OS, arch, linux_family
                ch = choose(rel.assets, OS, arch(), linux_family()) if rel else None
                self._preview_assets[repo.url] = {"assets": list(rel.assets) if rel else [], "forge": kind}
                listed = [t["name"] for t in self.db.all("""SELECT t.name FROM reviews r JOIN trusts t ON t.id=r.trust_id
                                                             WHERE r.url=? AND t.own=0""", (repo.url,))]
                out.update(ok=True, forge=forges.LABELS.get(kind, kind), name=info.name, description=info.description,
                           releases=len(rels), version=rel.version if rel else "", date=rel.date if rel else "",
                           asset=ch.asset.name if ch and ch.asset else "", assetSize=(ch.asset.size if ch and ch.asset else 0),
                           assetReason=ch.reason if ch else "no releases", listedBy=listed,
                           exists=bool(self.db.one("SELECT 1 FROM sources WHERE url=?", (repo.url,))))
            except (ValueError, SourceError) as e:
                out.update(ok=False, error=str(e))
            self.sourcePreview.emit(out)
        threading.Thread(target=work, daemon=True).start()

    @Slot(str, bool)
    def addSource(self, text: str, and_install: bool) -> None:
        self.addSourceWith(text, and_install, {})

    @Slot(str, bool, "QVariant")
    def addSourceWith(self, text: str, and_install: bool, settings) -> None:
        """Add a Source, with the Source settings chosen in the Add source dialog (requirement 7.2)."""
        try:
            repo = urls.parse(text)
        except ValueError as e:
            self.toast.emit("error", str(e))
            return
        self.db.x("INSERT OR IGNORE INTO sources(url, input_url, releases_page, settings, added_at) VALUES(?,?,?,?,?)",
                  (repo.url, text, int(repo.releases_page), json.dumps(_clean_source_settings(dict(_plain(settings) or {}))), now()))
        self._audit("you", "source", "added", repo.path or repo.url, repo.url, {"from": text} if text != repo.url else None)
        def work():
            sync.sync_app(self.db, self.http, repo.url)
            foreign.scan(self.db)
            self._refresh.emit()
            if and_install:
                QTimer.singleShot(300, lambda: self.install(repo.url))
        self.reload()
        threading.Thread(target=work, daemon=True).start()

    # ---------------------------------------------------------------- Source settings (requirement 2.6)
    @Slot(str, result="QVariant")
    def sourceSettings(self, url: str):
        """A Source's settings for the Source settings dialog, with what it means on this computer."""
        from appkata_core import forges
        from appkata_core.platform import OS, arch
        src = self.db.one("SELECT settings, forge FROM sources WHERE url=?", (url,))
        st = json.loads(src["settings"] or "{}") if src else {}
        meta = self.db.one("SELECT forge FROM apps WHERE url=?", (url,)) or {}
        detected = (src or {}).get("forge") or meta.get("forge") or (self._preview_assets.get(url) or {}).get("forge") or ""
        key = f"{OS}-{arch()}"
        rec, rec_by = catalog.recommended_for(self.db, url, OS)       # a Trust's recommendation (requirement 10.3.1)
        pre_default = bool(self._prefs.get("prereleases"))
        return {"url": url, "exists": bool(src), "forge": st.get("forge", ""), "detected": forges.LABELS.get(detected, detected),
                "trackOnly": bool(st.get("track_only", False)), "prereleases": st.get("prereleases"),
                "prereleasesDefault": bool(pre_default),
                "assetFilter": (st.get("asset_filters") or {}).get(key, st.get("asset_filter", "")),
                "recommended": {k: rec[k] for k in ("forge", "assetFilter") if k in rec},
                "recommendedBy": {k: rec_by[k] for k in ("forge", "assetFilter") if k in rec_by},
                "platform": {"linux": "Linux", "windows": "Windows", "macos": "macOS"}[OS] + " " + arch(),
                "forges": [["", "Detect automatically"]] + [[k, v] for k, v in forges.LABELS.items()],
                **self._channel_settings(url, st)}

    def _channel_settings(self, url: str, st: dict) -> dict:
        """Source settings' Flatpak and Package fields (requirement 2.6.7, 16.1.3): yours, and what
        applies without yours, with where it comes from and its check."""
        if not self.ch.enabled:
            return {"channels": False}
        from appkata_core import channels as chmod
        found = {}
        try:
            found = self.ch.links(url, ignore_mine=True)
        except Exception:      # noqa: BLE001
            log.exception("channel links for %s", url)
        def hint(kind):
            l = found.get(kind)
            if not l:
                return {"found": "", "from": "", "check": "", "detail": ""}
            c = chmod.get_check(self.db, url, kind, l.value)
            return {"found": (l.remote + " " + l.value) if kind == "flatpak" and l.remote != "flathub" else l.value,
                    "from": l.via if l.source == "trust" else "AppStream" if l.source == "appstream" else "",
                    "check": c.get("state", ""), "detail": c.get("detail", "")}
        return {"channels": True, "flatpak": st.get("flatpak", ""), "package": st.get("package", ""),
                "flatpakHint": hint("flatpak"), "packageHint": hint("package"), "distro": self.ch.distro}

    def _source_assets(self, url: str) -> list:
        from appkata_core.forges import Asset
        row = self.db.one("SELECT releases FROM apps WHERE url=?", (url,))
        for r in json.loads(row["releases"] or "[]") if row and row["releases"] else []:
            if r.get("assets") and not r.get("prerelease"):
                return [Asset(**x) for x in r["assets"]]
        return list((self._preview_assets.get(url) or {}).get("assets") or [])

    @Slot(str, str, result="QVariant")
    def previewAssetFilter(self, url: str, rx: str):
        """Which file the asset filter picks from the latest release (requirement 2.6.4)."""
        from appkata_core.assets import choose
        from appkata_core.platform import OS, arch, linux_family
        assets = self._source_assets(url)
        if not assets:
            return {"file": "", "note": "No release files to try it on yet."}
        rec, rec_by = catalog.recommended_for(self.db, url, OS)
        if not rx and rec.get("assetFilter"):           # empty: a Trust's recommended filter applies (10.3.1)
            ch = catalog.choose_with({"assetFilter": rec["assetFilter"], "by": {"assetFilter": rec_by.get("assetFilter", "")}},
                                     assets, OS, arch(), linux_family())
            return {"file": ch.asset.name if ch.asset else "", "note": "" if ch.asset else ch.reason, "kind": ch.kind,
                    "recommended": rec["assetFilter"], "by": rec_by.get("assetFilter", "")}
        try:
            re.compile(rx or "")
        except re.error as e:
            return {"file": "", "note": f"Not a valid regular expression: {e}", "bad": True}
        ch = choose(assets, OS, arch(), linux_family(), rx or "")
        return {"file": ch.asset.name if ch.asset else "", "note": "" if ch.asset else ch.reason, "kind": ch.kind}

    @Slot(str, "QVariant")
    def setSourceSettings(self, url: str, settings) -> None:
        src = self.db.one("SELECT settings FROM sources WHERE url=?", (url,))
        if not src:
            return
        cur = json.loads(src["settings"] or "{}")
        new = _clean_source_settings({**cur, **dict(_plain(settings))})
        self.db.x("UPDATE sources SET settings=? WHERE url=?", (json.dumps(new), url))
        a = self._app(url)
        changed = {k: new.get(k) for k in set(cur) | set(new) if cur.get(k) != new.get(k)}
        self._audit("you", "source", "changed the settings of", a["name"] if a else url, url, changed or None)
        self.reload()
        def work():
            sync.sync_app(self.db, self.http, url)
            self._refresh.emit()
        threading.Thread(target=work, daemon=True).start()

    @Slot(str, bool)
    def removeSource(self, url: str, and_uninstall: bool) -> None:
        if url == APPKATA_REPO:
            self.toast.emit("error", "AppKata's own Source is built in.")
            return
        if and_uninstall:
            try:
                install.uninstall(self.db, url)
            except install.InstallError as e:
                self.toast.emit("error", str(e))
                return
        a = self._app(url)
        self.db.x("DELETE FROM sources WHERE url=?", (url,))
        self._audit("you", "source", "removed", a["name"] if a else url, url, {"uninstalled": True} if and_uninstall else None)
        if and_uninstall:
            self._audit("you", "app", "uninstalled", a["name"] if a else url, url)
        self.reload()

    @Slot(str, result="QVariant")
    def trustsListing(self, url: str):
        rows = self.db.all("""SELECT t.id, t.name, t.own, t.score, r.trust, r.rating FROM reviews r JOIN trusts t ON t.id=r.trust_id
                              WHERE r.url=? AND t.own=0 AND t.enabled=1""", (url,))
        return [{"id": t["id"], "name": t["name"], "trust": t["trust"], "rating": t["rating"], "score": catalog.trust_score(t),
                 "avatars": [authority_view(x) for x in catalog.authorities(self.db, t["id"], False) if x["enabled"]][:1]}
                for t in sorted(rows, key=catalog.trust_order)]          # Score, then name (requirement 7.6.7)

    # ---------------------------------------------------------------- trusts
    @Slot(str)
    def previewTrust(self, text: str) -> None:
        def work():
            p = sync.preview_trust(self.http, text.strip())
            self._previews[text.strip()] = p
            self.trustPreview.emit({"url": text.strip(), "error": p.error, "name": p.name, "path": p.path,
                                    "commit": p.commit[:7], "apps": p.apps, "warnings": p.warnings,
                                    "signers": [{**s, "shortFp": short_fp(s["fingerprint"]),
                                                 **catalog.avatar_for(s["name"] or s["email"], s["fingerprint"])} for s in p.signers]})
        threading.Thread(target=work, daemon=True).start()

    @Slot(str)
    def addTrust(self, text: str) -> None:
        self.addTrustScored(text, 3)

    @Slot(str, int)
    def addTrustScored(self, text: str, score: int) -> None:
        p = self._previews.pop(text.strip(), None)
        if not p or p.error:
            return
        if self.db.one("SELECT 1 FROM trusts WHERE url=?", (p.url,)):
            self.toast.emit("error", "That Trust is already added.")
            return
        tid = sync.add_trust(self.db, p)
        self.db.x("UPDATE trusts SET score=? WHERE id=?", (max(1, min(5, int(score))), tid))
        self._audit("you", "trust", "added", p.name, p.url, {"file": p.path, "commit": p.commit[:7], "apps": p.apps, "score": score})
        for s in p.signers:
            self._audit("you", "authority", "added", s["name"] or s["email"], p.url,
                        {"trust": p.name, "key": s["fingerprint"], "type": s["kind"]})
        self.reload()
        def work():
            for u in [r["url"] for r in self.db.all("SELECT url FROM reviews WHERE trust_id=(SELECT MAX(id) FROM trusts)")]:
                if not self.db.one("SELECT 1 FROM apps WHERE url=? AND error IS NULL", (u,)):
                    sync.sync_app(self.db, self.http, u)
            foreign.scan(self.db)
            self._refresh.emit()
        threading.Thread(target=work, daemon=True).start()

    @Slot(int, result="QVariant")
    def trustRemoval(self, tid: int):
        """What removing a Trust affects (requirement 7.5): installed apps it is the only origin of."""
        t = self.db.one("SELECT name, url FROM trusts WHERE id=?", (tid,)) or {}
        alone = [{"url": a["url"], "name": a["name"], "installed": a["installed"]} for a in self._apps
                 if a["installed"] and not a["src"] and not a.get("self")
                 and [r["trust_id"] for r in self.db.all("SELECT trust_id FROM reviews WHERE url=?", (a["url"],))] == [tid]]
        apps = self.db.one("SELECT COUNT(*) n FROM reviews WHERE trust_id=?", (tid,))["n"]
        return {"id": tid, "name": t.get("name", ""), "url": t.get("url", ""), "apps": apps, "alone": alone}

    @Slot(int, bool)
    def removeTrust(self, tid: int, keep_as_sources: bool = False) -> None:
        """Remove a Trust. With keep_as_sources, its installed apps that have no other origin become
        Sources first, so they keep getting updates (requirement 7.5)."""
        info = self.trustRemoval(tid)
        if keep_as_sources:
            for a in info["alone"]:
                self.db.x("INSERT OR IGNORE INTO sources(url, input_url, added_at) VALUES(?,?,?)", (a["url"], a["url"], now()))
                self._audit("you", "source", "added", a["name"], a["url"], {"kept from": info["name"]})
        self.db.x("DELETE FROM trusts WHERE id=?", (tid,))
        if info["name"]:
            self._audit("you", "trust", "removed", info["name"], info["url"],
                        {"kept as sources": [a["name"] for a in info["alone"]]} if keep_as_sources and info["alone"] else None)
        self.reload()

    @Slot(int, str, bool)
    def setAuthorityEnabled(self, tid: int, fp: str, on: bool) -> None:
        self.db.x("UPDATE authorities SET enabled=? WHERE trust_id=? AND fingerprint=?", (int(on), tid, fp))
        self._audit_authority(tid, fp, "enabled" if on else "disabled")
        self.reload()

    @Slot(int, str)
    def removeAuthority(self, tid: int, fp: str) -> None:
        self._audit_authority(tid, fp, "removed")
        self.db.x("DELETE FROM authorities WHERE trust_id=? AND fingerprint=?", (tid, fp))
        self.reload()

    @Slot(int, str)
    def trustSigner(self, tid: int, fp: str) -> None:
        sync.trust_signer(self.db, tid, fp)
        self._audit_authority(tid, fp, "approved the new signer")
        def work():
            sync.sync_trust(self.db, self.http, tid)
            self._refresh.emit()
        threading.Thread(target=work, daemon=True).start()

    @Slot(int, str)
    def ignoreSigner(self, tid: int, fp: str) -> None:
        self.db.x("UPDATE authorities SET pending_commits=0 WHERE trust_id=? AND fingerprint=?", (tid, fp))
        self._audit_authority(tid, fp, "ignored the new signer")
        self.reload()

    def _audit_authority(self, tid: int, fp: str, action: str) -> None:
        a = self.db.one("SELECT a.name, a.email, a.kind, t.name tname, t.url FROM authorities a JOIN trusts t ON t.id=a.trust_id "
                        "WHERE a.trust_id=? AND a.fingerprint=?", (tid, fp))
        if a:
            self._audit("you", "authority", action, a["name"] or a["email"] or fp, a["url"], {"trust": a["tname"], "key": fp})

    # ---------------------------------------------------------------- reviews
    @Slot(str, result="QVariant")
    def reviewData(self, url: str):
        a = self._app(url) or {}
        path = self._prefs.get("reviewPath") or ""
        cur = review.current(path, a.get("name", ""), url) if path else {"exists": False, "tags": [], "trust": None, "rating": None, "section": ""}
        st = review.repo_state(path) if path else review.RepoState()
        known = list(dict.fromkeys(trustfile.PREDEFINED_TAGS + sorted({t for x in self._apps for t in x["tags"]})))
        opts = {}
        inst = self.db.one("SELECT record FROM installs WHERE url=?", (url,))
        if inst:
            opts = json.loads(inst["record"] or "{}").get("options") or {}
        if not opts and a.get("installChoice"):
            opts = {k: a["installChoice"][k] for k in ("appMenu", "commandLink", "stableName") if k in a["installChoice"]}
        if "autoUpdate" in (a.get("installChoice") or {}):         # only when you chose it (requirement 4.10.3)
            opts = {**opts, "autoUpdate": bool(a["installChoice"]["autoUpdate"])}
        from appkata_core.platform import OS, arch
        src = self.db.one("SELECT settings FROM sources WHERE url=?", (url,))
        ss = json.loads(src["settings"] or "{}") if src else {}
        # your Source settings for this app (requirement 2.6) are written too, the ones you set
        if ss.get("forge"):        # Track only and pre-releases are personal, so they aren't written (10.3.1)
            opts["forge"] = ss["forge"]
        if (ss.get("asset_filters") or {}).get(f"{OS}-{arch()}"):
            opts["assetFilter"] = ss["asset_filters"][f"{OS}-{arch()}"]
        rv = self._review_versions(url, a, cur)
        sbx = self._review_sandbox_lines(url)
        return {**cur, **rv, "installSettings": opts, "settingsHeading": trustfile.settings_heading(a.get("name", "")),
                "sandboxSettings": sbx["settings"] if sbx else None, "sandboxLine": sbx["summary"] if sbx else "",
                "sandboxRefused": [list(x) for x in sbx["refused"]] if sbx else [],
                "settingsLabels": trustfile.SETTINGS_LABELS, "app": a.get("name", ""), "url": url, "path": path, "inRepo": st.in_repo, "remote": st.remote,
                "branch": st.branch, "signs": st.signs, "signFormat": st.format, "signKey": st.key, "knownTags": known,
                "tagMeanings": trustfile.TAG_MEANINGS, "autoCommit": bool(self._prefs.get("autoCommit")),
                "autoPush": bool(self._prefs.get("autoPush")), "defaultDir": os.path.expanduser("~")}

    def _review_sandbox_lines(self, url: str) -> dict | None:
        """The user's own sandbox for `url` as their review's lines (10.3.1, 8.4.7; review 2, F9): only a
        choice of their own, not one from the reviews or the default, as "Auto update" is written only
        when chosen (4.10.3). {"settings": every Sandbox option, None for a line to drop, so the
        sandbox is written whole; "summary": what a reader gets, read back from those lines;
        "refused": [(what, why)] a review can't carry}. None when there is nothing of the user's."""
        r = self._resolved_sandbox(url)
        if not r or r["source"] != "user":
            return None
        opts, refused = sandbox.as_review(r["template"], r["grants"])
        back = sandbox.grants_from_config(sandbox.config_from_review(opts))
        return {"settings": {k: opts.get(k) for k in trustfile.SANDBOX_KEYS},
                "summary": sandbox.describe(opts["sandbox"], back), "refused": refused}

    def _review_versions(self, url: str, a: dict, cur: dict) -> dict:
        """The review dialog's Version select (requirement 8.4.1.1) and Details (8.4.5.1): each choice
        with the review it loads, or the values a new review of it starts from."""
        from appkata_core.platform import OS, arch
        meta = self.db.one("SELECT releases FROM apps WHERE url=?", (url,)) or {}
        releases = json.loads(meta.get("releases") or "[]")
        dates = catalog.release_dates(releases)
        full = cur.get("full") or {}
        table = {"trust": cur.get("trust"), "rating": cur.get("rating"), "tags": cur.get("tags") or []} if cur.get("exists") else None
        chain = trustfile.reviews_over_versions(full, table, OS, dates) if cur.get("exists") else []
        mine = {x["version"]: x for x in chain[1:]}
        inst = a.get("installed") if a.get("state") not in ("foreign", "") and not a.get("self") else ""
        include_pre = bool(self.db.get("prereleases", False))
        vs = [r["version"] for r in releases if include_pre or not r.get("prerelease") or r["version"] == inst]
        vs += [v for v in mine if v not in vs]
        def date_of(x):
            return next((d[1] for d in x["details"] if d[0].lower() == "date"), "")
        choices, load = [], {}
        for v in [""] + vs:
            x = mine.get(v) if v else (chain[0] if chain else None)
            note = " · ".join(n for n, on in (("Installed", v and v == inst), ("Reviewed", bool(v and x))) if on)
            choices.append({"key": v, "text": v or "Any version", "note": note})
            if x is not None and (v or cur.get("exists")):
                load[v] = {"exists": True, "trust": x["trust"], "rating": x["rating"], "tags": x["tags"],
                           "text": x["text"] if v else cur.get("section", ""), "date": date_of(x)}
            else:
                base = trustfile.review_for({}, None, v, OS, dates, chain=chain) if chain else None
                load[v] = {"exists": False, "trust": base["trust"] if base else None, "rating": base["rating"] if base else None,
                           "tags": base["tags"] if base else [], "text": "",
                           "from": base["version"] if base else "", "fromDate": date_of(base) if base else ""}
        if inst:
            default = inst
        elif mine and vs:
            default = vs[0]
        else:
            default = ""
        details = []
        irow = self.db.one("SELECT * FROM installs WHERE url=?", (url,)) if inst else None
        if irow:
            rel = next((r for r in releases if r["version"] == irow["version"]), {})
            asset = next((x for x in rel.get("assets") or [] if x.get("name") == irow["asset"]), {})
            forge = {"github": "GitHub", "gitlab": "GitLab", "forgejo": "Forgejo", "gitea": "Gitea"}.get(a.get("forge", ""), "")
            details = [["Date", now()[:10]], ["Platform", f"{OS} {arch()}"], ["Channel", f"{forge} release".strip()]]
            if irow["asset"]:
                details.append(["File", irow["asset"]])
            if (asset.get("digest") or "").startswith("sha256:"):
                details.append(["SHA-256", asset["digest"].split(":", 1)[1]])
        pref = self._prefs.get("includeDetails")
        return {"versionChoices": choices, "versionReviews": load, "defaultVersion": default, "installedVersion": inst,
                "details": details, "includeDetails": bool(irow) if pref is None else bool(pref)}

    @Slot(str, "QVariant", "QVariant", "QVariant", str, bool, bool, str, bool)
    @Slot(str, "QVariant", "QVariant", "QVariant", str, bool, bool, str, bool, bool)
    def saveReview(self, url, tags, trust, rating, section, commit, push, version="", include_details=False,
                   include_sandbox=True) -> None:
        tags, trust, rating = _plain(tags), _plain(trust), _plain(rating)
        a = self._app(url) or {}
        path = self._prefs.get("reviewPath")
        def norm(v):
            return None if v is None or v == "" or (isinstance(v, (int, float)) and v < 0) else int(v)
        def work():
            try:
                from appkata_core.platform import OS
                rd = self.reviewData(url)
                meta = self.db.one("SELECT releases FROM apps WHERE url=?", (url,)) or {}
                dates = catalog.release_dates(json.loads(meta.get("releases") or "[]"))
                # this computer's options become the lines without a platform; other platforms' lines stay (10.3.1);
                # a version review writes only what differs from the review before it (8.4.7)
                # and the user's own sandbox, whole, unless "Include my sandbox" is off (review 2, F9)
                new = {**(rd.get("installSettings") or {}), **((rd.get("sandboxSettings") or {}) if include_sandbox else {})}
                opts = trustfile.options_to_write(rd.get("full") or {}, version or "", new, OS, dates) or None
                details = None
                if version and version == rd.get("installedVersion"):
                    details = rd.get("details") if include_details else None
                res = review.save(path, a.get("name", url), url, list(tags or []), norm(trust), norm(rating), section or "",
                                  commit, push, opts, version or "", details, dates)
                out = {"saved": res.saved, "committed": res.committed[:7], "signed": res.signed, "pushed": res.pushed, "error": res.error}
                self._audit("you", "review", "reviewed", a.get("name", url), url,
                            {"version": version or None, "trust": norm(trust), "rating": norm(rating), "tags": list(tags or []),
                             "commit": res.committed[:7] or None, "signed": res.signed if res.committed else None, "pushed": res.pushed})
            except OSError as e:
                out = {"saved": False, "error": f"Couldn't write {path}: {e}"}
            sync.sync_own(self.db, sync.own_trust(self.db, path))
            self.reviewSaved.emit(out)
            self._refresh.emit()
        threading.Thread(target=work, daemon=True).start()

    @Slot()
    def amendSigned(self) -> None:
        res = review.amend_signed(self._prefs.get("reviewPath"))
        if res.committed:
            self._audit("you", "review", "re-signed the last commit", os.path.basename(self._prefs.get("reviewPath") or ""), "",
                        {"commit": res.committed[:7], "signed": res.signed})
        self.reviewSaved.emit({"saved": True, "committed": res.committed[:7], "signed": res.signed, "pushed": False,
                               "error": res.error, "amended": True})

    # ---------------------------------------------------------------- settings (requirement 11)
    def portable(self) -> install.Portable:
        p = self._prefs
        from appkata_core.platform import command_dir_default
        return install.Portable(folder=p.get("installDir") or "", app_menu=bool(p.get("appMenu", True)),
                                stable_name=bool(p.get("stableName", True)),
                                command_dir=(p.get("commandDir") or command_dir_default()) if p.get("commandLinks", True) else "",
                                keep=int(p.get("keepVersions", 2) or 0), scope=p.get("installFor") or "me",
                                folder_everyone=p.get("installDirEveryone") or "")

    def _recommended(self, url: str) -> dict:
        """Install options recommended in the Trusts' AppKata.md files (requirement 10.3.1): for each
        option, yours first, then the highest-Score Trust's, then by name."""
        rows = self.db.all("""SELECT r.settings, t.name, t.own, t.score FROM reviews r JOIN trusts t ON t.id=r.trust_id
                              WHERE r.url=? AND t.enabled=1""", (url,))
        out, by = {}, ""
        from appkata_core.platform import OS
        for r in sorted(rows, key=lambda r: catalog.trust_order(dict(r))):
            for k, v in trustfile.resolve_settings(json.loads(r["settings"] or "{}"), OS).items():
                if k not in out and k != "autoUpdate":
                    out[k] = v
                    by = by or ("you" if r["own"] else r["name"])
        return {"settings": out, "by": by} if out else {}

    def _app_options(self, url: str, choice: dict | None = None) -> install.Portable:
        """The portable options for one app: its own (saved at install), else a Trust's recommendation,
        else Settings (requirement 4.3.1.6)."""
        p = self.portable()
        a = self._app(url) or {}
        own = dict(choice or {}) or a.get("installChoice") or {}
        rec = self._recommended(url).get("settings", {})
        def pick(k, default):
            return own[k] if k in own else rec[k] if k in rec else default
        p.app_menu = bool(pick("appMenu", p.app_menu))
        p.stable_name = bool(pick("stableName", p.stable_name))
        from appkata_core.platform import command_dir_default
        p.command_dir = (self._prefs.get("commandDir") or command_dir_default()) if pick("commandLink", bool(p.command_dir)) else ""
        # who it's for and Mark of the Web are about this computer: never a Trust's (requirement 15.4.1, 15.11.1)
        row = self.db.one("SELECT record FROM installs WHERE url=?", (url,))
        rec = json.loads(row["record"] or "{}") if row else {}
        p.scope = own.get("scope") or rec.get("scope") or p.scope
        p.motw = bool(own.get("motw", rec.get("motw", False)))
        return p

    def _save_options(self, url: str, port: install.Portable, extra: dict | None = None) -> None:
        """Copy the options an app was installed with into its own settings (requirement 4.3.1.6)."""
        row = self.db.one("SELECT install FROM app_settings WHERE url=?", (url,))
        cur = json.loads(row["install"] or "{}") if row and row["install"] else {}
        cur.update({"appMenu": port.app_menu, "commandLink": bool(port.command_dir), "stableName": port.stable_name,
                    "scope": port.scope, "motw": port.motw}, **(extra or {}))
        self.db.x("INSERT INTO app_settings(url, install) VALUES(?,?) ON CONFLICT(url) DO UPDATE SET install=excluded.install",
                  (url, json.dumps(cur)))

    # ---------------------------------------------------------------- sandboxing (requirement 17)
    def _sb_session_warning(self) -> dict:
        if getattr(self, "_demo_sandbox", "") in ("x11", "setup"):
            return dict(sandbox.X11_WARNING)       # the product's own text (review 2, F7: the tour kept an old one)
        if getattr(self, "_demo_sandbox", "") == "ok":
            return {}                              # a session nothing leaks from (GNOME on Wayland)
        return sandbox.session_warning()

    def _sb_support(self) -> dict:
        # `declined`: "Not now" was answered at an install, so installs don't ask (17.10); `waitingNote`:
        # what the setup will sandbox, said before its password prompt (17.13; review 2, F13)
        st = {**sandbox.support_status(), "declined": bool(self._prefs.get("sandboxSetupDeclined"))}
        if getattr(self, "_demo_sandbox", "") == "setup":
            st = {**st, "status": "setup-needed", "tools": True}
        if st.get("status") == "setup-needed":
            st["waitingNote"] = self._sandboxed_note([(n, f) for _, n, f in self._waiting_for_sandbox()], waiting=True)
        if getattr(self, "_demo_sandbox", "") in ("x11", "ok"):         # the tour's sandboxed state: a working system
            st = {**st, "status": "ok", "tools": True}
        if getattr(self, "_demo_sandbox", "") in ("x11", "setup", "ok"):  # the tour: a machine with both tools
            st = {**st, "busFilter": True, "missing": [], "toolsHint": "", "appToolsHint": "", "brokenHint": ""}
        return st

    def _is_cli(self, url: str, eff: install.Portable | None = None) -> bool:
        """A command-line tool (17.3.3): the user's own choice in Install options (`cliKind`), else
        what the download showed (`appKind`, appkind.detect: a `.desktop` saying Terminal=true, or a
        program that links no display library), else an app. Review 2, F4: it was "a command link
        and no app-menu entry", which Settings' defaults never produced, so every tool ran Strict."""
        choice = self._install_settings(url).get("cliKind")
        if choice in ("cli", "gui"):
            return choice == "cli"
        row = self.db.one("SELECT record FROM installs WHERE url=?", (url,))
        return (json.loads(row["record"] or "{}") if row else {}).get("appKind") == "cli"

    def _detected_kind(self, url: str) -> str:
        row = self.db.one("SELECT record FROM installs WHERE url=?", (url,))
        return (json.loads(row["record"] or "{}") if row else {}).get("appKind") or ""

    def _menu_from_default(self, url: str, choice: dict | None, a: dict) -> bool:
        """Whether this install's app-menu option is only Settings' default -- not the user's (an
        install dialog answer, a saved option) nor a Trust's: then a command-line tool gets none."""
        saved = dict(choice or {}) or a.get("installChoice") or {}
        return "appMenu" not in saved and "appMenu" not in self._recommended(url).get("settings", {})

    def _app_id(self, url: str) -> str:
        """The name an app's folder, launcher, identity and private home are keyed on: the id its
        install recorded (unique among installs, R6-1), else the name's slug (not yet installed, or
        a record from before ids were recorded)."""
        a = self._app(url) or {}
        row = self.db.one("SELECT record FROM installs WHERE url=?", (url,))
        return install.app_id_of(json.loads(row["record"] or "{}") if row else {}, {"name": a.get("name", "app")})

    def _sandbox_kind(self, url: str) -> str:
        """The portable kind for sandboxing (17.1), from the chosen asset or how it was installed."""
        a = self._app(url) or {}
        return (a.get("installKind") or (a.get("asset") or {}).get("kind") or "")

    def _review_sandbox_configs(self, url: str) -> list[dict]:
        """Each enabled Trust's suggested sandbox config (17.3.2), highest Score first; only reviews
        whose Settings carry a Sandbox line."""
        return [c for _, c in self._review_sandbox_named(url)]

    def _review_sandbox_named(self, url: str) -> list[tuple[str, dict]]:
        """(reviewer name, sandbox config) for each enabled Trust with a Sandbox line, highest Score first."""
        rows = self.db.all("""SELECT r.settings, t.name, t.own, t.score FROM reviews r JOIN trusts t ON t.id=r.trust_id
                              WHERE r.url=? AND t.enabled=1""", (url,))
        from appkata_core.platform import OS
        out = []
        for r in sorted(rows, key=lambda r: catalog.trust_order(dict(r))):
            opts = trustfile.resolve_settings(json.loads(r["settings"] or "{}"), OS)
            cfg = sandbox.config_from_review(opts)
            if cfg:
                out.append(("you" if r["own"] else r["name"], cfg))
        return out

    @staticmethod
    def _updates_itself(a: dict, sbx: dict | None) -> bool:
        """Whether the install is laid out for an app that updates itself (4.10.2): not while it runs
        sandboxed, where its own updater can't write its files and AppKata updates it (17.12; review
        2, F3). `sbx`: the grant set the launcher gets, None when it runs Off or can't be sandboxed."""
        return bool(a.get("autoUpdate")) and not (sbx and sandbox.level_of(sbx) != "off")

    def _suggests_off(self, url: str) -> bool:
        """Whether the merged reviews suggest no sandbox (shown, never applied by itself, 17.3.2)."""
        suggested, _ = self._suggestion(url)
        return suggested is not None and sandbox.level_of(suggested) == "off"

    def _sandbox_reviewer(self, url: str) -> str:
        """Who suggested the sandbox (the highest-Score Trust with a Sandbox line), for the labels."""
        named = self._review_sandbox_named(url)
        return named[0][0] if named else ""

    def _user_sandbox_config(self, url: str) -> dict | None:
        """The sandbox the user chose for this app (install options or App Detail), or None (17.11)."""
        row = self.db.one("SELECT install FROM app_settings WHERE url=?", (url,))
        saved = json.loads(row["install"] or "{}") if row and row["install"] else {}
        cfg = saved.get("sandbox")
        if cfg is not None and (why := sandbox.config_error(cfg)):     # a row an older AppKata poisoned (R4-1)
            log.warning("ignoring the saved sandbox choice for %s: %s", url, why)
            return None
        return cfg

    def _resolved_sandbox(self, url: str, kind: str | None = None, is_cli: bool | None = None) -> dict | None:
        """The grant set that applies and where it came from (17.11, :func:`sandbox.choose`): the user's
        choice, else the grants the installed app was pinned to, else merged reviews, else the default by
        kind. Returns {"source", "grants", "template"} or None when the app can't be sandboxed (not
        Linux, or not a portable AppImage/tarball)."""
        from appkata_core.platform import OS
        kind = kind if kind is not None else self._sandbox_kind(url)
        if OS != "linux" or kind not in ("appimage", "tarball"):
            return None
        # AppKata itself, adopted as installed when it runs as an AppImage (2.11), is never sandboxed:
        # it installs apps, runs package managers and pkexec, and writes the install folder (17.1).
        # Review 3, R3-6: the heal pass gave it a Strict launcher with no network.
        if url == APPKATA_REPO:
            return None
        is_cli = self._is_cli(url) if is_cli is None else is_cli
        user = self._user_sandbox_config(url)
        installed = bool(self.db.one("SELECT 1 FROM installs WHERE url=?", (url,)))
        pinned = self._install_settings(url).get("sandboxPinned") if installed else None
        # "Follow reviewers' suggestions" off (17.15) takes the reviews out of sandboxing altogether:
        # neither their Sandbox lines nor the reviewed baseline apply, so the user's own default for
        # the kind does. Round two, R6: the baseline still applied with the pref off.
        follow = bool(self._prefs.get("followReviewerSandbox", True))
        reviews = self._review_sandbox_configs(url) if follow else []
        reviewed = follow and bool(self.db.one("""SELECT 1 FROM reviews r JOIN trusts t ON t.id=r.trust_id
                                                  WHERE r.url=? AND t.enabled=1""", (url,)))
        default = sandbox.default_template(is_cli, reviewed=reviewed,
                                           unreviewed_default=self._kind_default_config(is_cli))
        src, gs, template = sandbox.choose(user, pinned, reviews, default, is_cli)
        refused = []
        if src == "reviews":            # a review can't grant a secret folder (17.3.1, review 2 F8)
            gs, refused = sandbox.strip_secrets(gs)
        return {"source": src, "grants": sandbox.to_json(gs), "template": template, "refused": refused}

    def _suggestion(self, url: str) -> tuple[dict | None, list]:
        """The merged reviews' suggestion as a grant set, without the secret folders a review can't
        grant, and those refused [(path, why)]; (None, []) when no review says anything (17.11)."""
        reviews = self._review_sandbox_configs(url)
        if not reviews:
            return None, []
        gs = sandbox.resolve(reviews=reviews, is_cli=self._is_cli(url))[1]
        return sandbox.strip_secrets(gs) if sandbox.level_of(gs) != "off" else (gs, [])

    def _suggested_template(self, url: str) -> str | None:
        """The template the reviews suggest, when one review does; merged ones are "custom" (17.3.2)."""
        cfgs = self._review_sandbox_configs(url)
        return cfgs[0].get("template") if len(cfgs) == 1 else None

    def _install_settings(self, url: str) -> dict:
        row = self.db.one("SELECT install FROM app_settings WHERE url=?", (url,))
        return json.loads(row["install"] or "{}") if row and row["install"] else {}

    def _set_install_settings(self, url: str, saved: dict) -> None:
        self.db.x("INSERT INTO app_settings(url, install) VALUES(?,?) ON CONFLICT(url) DO UPDATE SET install=excluded.install",
                  (url, json.dumps(saved)))

    def _pin_sandbox(self, url: str, r: dict | None) -> None:
        """Record the grant set an installed app now runs with, so later reviews can't change it (17.11)."""
        saved = self._install_settings(url)
        if r:
            saved["sandboxPinned"] = {"grants": r["grants"], "template": r["template"]}
        else:
            saved.pop("sandboxPinned", None)
        self._set_install_settings(url, saved)

    def _kind_default_config(self, is_cli: bool) -> dict:
        """The user's chosen default template for this kind (Settings → Sandbox, 17.15)."""
        key = "sandboxCliDefault" if is_cli else "sandboxGuiDefault"
        name = self._prefs.get(key) or ("cli-tool" if is_cli else "strict")
        return {"template": name, "overrides": {}}

    def _runs_sandboxed(self, url: str, rec: dict | None = None) -> bool:
        """Whether the installed app runs sandboxed (17.4): its launcher is there. App Detail's pill,
        the Apps list's 17.12 rule (catalog.build) and the empty-home warning all ask here. The tour
        stages a working system, healed: an installed app whose sandbox isn't Off runs sandboxed.
        Review 3, R3-27: the tour forced App Detail's answer alone, and the Apps list read only the
        record's launcher, so A09 showed Syncthing sandboxed and updating itself."""
        row = self.db.one("SELECT kind, record FROM installs WHERE url=?", (url,))
        if not row:
            return False
        if getattr(self, "_demo_sandbox", "") in ("x11", "ok"):
            r = self._resolved_sandbox(url, kind=row["kind"])
            return bool(r) and sandbox.level_of(r["grants"]) != "off"
        return sandbox.runs_sandboxed(json.loads(row["record"] or "{}") if rec is None else rec)

    def _sandbox_state(self, url: str) -> tuple[bool, bool]:
        """(whether the installed app runs sandboxed, whether sandboxing it now would give it an empty
        private home) -- before an install, an update or a heal changes it (17.13)."""
        if self._runs_sandboxed(url):
            return True, False
        try:
            return False, not os.listdir(sandbox.sandbox_home(self._app_id(url)))
        except OSError:
            return False, True

    def _fresh_warning(self, url: str) -> str:
        """What the Sandbox dialog and Install options say above Save when a sandboxed choice would give
        an installed app that runs unsandboxed its first private home (17.13; review 2, F13: a toast said
        it after the change was made)."""
        a = self._app(url) or {}
        if not a.get("installed") or a.get("foreign") or self._sandbox_state(url) != (False, True):
            return ""
        return (f"Sandboxing {a.get('name', 'it')} gives it an empty private home of its own, as if newly installed: "
                "its settings and accounts will look reset, and paths it remembers may point nowhere. Your files aren't touched.")

    def _waiting_for_sandbox(self) -> list[tuple[str, str, bool]]:
        """(url, name, starts fresh) of each installed app that would run sandboxed but has no launcher
        yet: what a setup, or tools installed since, will sandbox (17.10, 17.13)."""
        out = []
        for row in self.db.all("SELECT url, name FROM installs ORDER BY name"):
            a = self._app(row["url"])
            if row["url"] == APPKATA_REPO or not a or a.get("foreign"):
                continue
            r = self._resolved_sandbox(row["url"])
            if r and sandbox.level_of(r["grants"]) != "off":
                launcher, fresh = self._sandbox_state(row["url"])
                if not launcher:
                    out.append((row["url"], a["name"], fresh))
        return out

    @staticmethod
    def _sandboxed_note(items: list[tuple[str, bool]], waiting: bool) -> str:
        """[(name, starts fresh)] said as setup entry points say what they will sandbox (`waiting`), or
        as the notice once they are (17.13). Empty for none."""
        if not items:
            return ""
        def both(xs):
            return xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + " and " + xs[-1]
        names = [n for n, _ in items]
        fresh = [n for n, f in items if f]
        kept = [n for n, f in items if not f]
        one = len(items) == 1
        if waiting:
            head = (f"Setting it up sandboxes {names[0]}, which runs unsandboxed until then." if one else
                    f"Setting it up sandboxes the {len(items)} apps that run unsandboxed until then: {both(names)}.")
        else:
            head = f"Now sandboxed, since this system can sandbox them: {both(names)}." if not one else \
                   f"{names[0]} now runs sandboxed, since this system can sandbox it."
        if fresh and not kept:
            tail = (" It starts" if one else " They start") + " with fresh settings; your files aren't touched."
        elif fresh:
            tail = (f" {both(fresh)} start{'s' if len(fresh) == 1 else ''} with fresh settings; {both(kept)} "
                    f"keep{'s' if len(kept) == 1 else ''} the ones from an earlier sandbox. Your files aren't touched.")
        else:
            tail = (" It keeps" if one else " They keep") + " the settings from an earlier sandbox."
        return head + tail

    def _tell_sandboxed(self, items: list[tuple[str, str, bool]], actor: str) -> None:
        """A notice and an Audit entry for each installed app that has just been sandboxed for the
        first time by something other than the user's own choice in a dialog (17.13, 17.16)."""
        if not items:
            return
        for url, name, fresh in items:
            self._audit(actor, "app", "sandboxed", name, url,
                        self._sandbox_detail(url, None, self._resolved_sandbox(url), **{"fresh settings": fresh}))
        self._toast.emit("info", self._sandboxed_note([(n, f) for _, n, f in items], waiting=False))

    def _settle_sandbox(self, url: str, kind: str, had: tuple[bool, bool] | None) -> None:
        """After an install or update: pin the grant set it now runs with, with the kind the download
        showed (17.11); and when this update sandboxed an app that ran unsandboxed (`had`, the state
        before; None for a first install), say so (17.13)."""
        self._pin_sandbox(url, self._resolved_sandbox(url, kind=kind))
        if had and not had[0] and self._sandbox_state(url)[0]:
            a = self._app(url) or {}
            self._tell_sandboxed([(url, a.get("name", url), had[1])], "you")

    def _sandbox_for_install(self, url: str, kind: str | None = None, is_cli: bool | None = None) -> dict | None:
        """The grant set (as JSON) to bake into the launcher at install, or None for Off/unsupported.
        An app that has a launcher keeps one whatever the support check says now: an update, a
        rollback or a sandbox change on a broken host writes it, and a start that then fails is
        reported (14.2.1), so only the user's own Off unsandboxes it (17.10; review 2, F16: the
        launcher was removed and the app ran with the real home until a later start healed it)."""
        r = self._resolved_sandbox(url, kind=kind, is_cli=is_cli)
        if not r or sandbox.level_of(r["grants"]) == "off":
            return r["grants"] if r else None
        row = self.db.one("SELECT record FROM installs WHERE url=?", (url,))
        if row and json.loads(row["record"] or "{}").get("launcher"):
            return r["grants"]
        if not sandbox.have_tools() or sandbox.support_status()["status"] in ("setup-needed", "conflict"):
            return None            # can't sandbox here yet: run Off (the UI warns, 17.10, 17.10.2)
        return r["grants"]

    @Property("QVariant", notify=prefsChanged)
    def sandboxSupport(self):
        """System support, defaults and the session warning for Settings → Sandbox (17.15, 17.9)."""
        st = self._sb_support()
        return {**st, "sessionWarning": self._sb_session_warning(), "busWarning": sandbox.bus_warning(),
                "guiDefault": self._prefs.get("sandboxGuiDefault") or "strict",
                "cliDefault": self._prefs.get("sandboxCliDefault") or "cli-tool",
                "followReviewers": bool(self._prefs.get("followReviewerSandbox", True)),
                "reviewBadge": bool(self._prefs.get("sandboxReviewBadge", True)),
                "templates": self.sandboxTemplates}

    @Property("QVariant", constant=True)
    def sandboxTemplates(self):
        """The built-in templates for the dropdowns (17.3)."""
        return [{"key": n, "label": sandbox.TEMPLATE_LABELS[n], "blurb": sandbox.TEMPLATE_BLURB[n],
                 "chips": sandbox.summary_chips(sandbox.resolve_template(n), template=n),   # [label, icon, tone], as every chip
                 "folder": sandbox.FOLDER_TEMPLATES.get(n),          # made for a folder the user picks (F10)
                 "grants": sandbox.to_json(sandbox.resolve_template(n))} for n in sandbox.TEMPLATE_ORDER]

    @Slot(str, "QVariant", result=str)
    def describeSandbox(self, template: str, grants) -> str:
        """A set as its template and its changes, for the Sandbox dialog's description of a customized
        one: "Standard, without the network and notifications, with ~/Shared (read-write)" (the
        widened-Strict nit of review 2: it showed Standard's own blurb over a set with neither)."""
        g = _plain(grants)
        return sandbox.describe(template, dict(g) if g else {}) if template in sandbox.TEMPLATES else ""

    @Slot("QVariant", result="QVariantList")
    @Slot("QVariant", str, result="QVariantList")
    @Slot("QVariant", str, str, result="QVariantList")
    def summaryChips(self, grants, url: str = "", template: str = ""):
        """Live summary chips for a grant set the Sandbox dialog is editing (17.3); `url` names the
        app, so a refused folder is judged against its install root, as the launcher does; `template`
        the template it is named after (a folder template says "No folder yet", F10)."""
        grants = _plain(grants)
        root = self._app_options(url).root if url else None
        return sandbox.summary_chips(dict(grants) if grants else {}, root, template or None)

    @Slot(str, result="QVariant")
    def sandboxInfo(self, url: str):
        """Everything App Detail and the Sandbox dialog need for one app (17.3, 17.9, 17.11)."""
        r = self._resolved_sandbox(url)
        if r is None:
            return {"applicable": False}
        gs = r["grants"]
        is_cli = self._is_cli(url)
        root = self._app_options(url).root           # the chips judge refused folders as the launcher does
        suggested, srefused = self._suggestion(url)
        a = self._app(url) or {}
        # whether the app really runs sandboxed: its launcher exists. An app installed while the system
        # couldn't sandbox runs Off until then, whatever its grants say (17.10).
        active = self._runs_sandboxed(url)
        return {"applicable": True, "source": r["source"], "template": r["template"], "active": active,
                "level": sandbox.level_of(gs), "levelLabel": sandbox.LEVEL_LABELS[sandbox.level_of(gs)],
                "chips": sandbox.summary_chips(gs, root, r["template"]) + sandbox.refused_chips(r.get("refused")), "grants": gs, "isCli": is_cli,
                # named after its template, with changes: "Offline editor · customized" (review 2, F10)
                "customized": sandbox.customized(r["template"], gs), "userFolders": sandbox.user_folders(),
                "folders": [{"path": p, "mode": m} for p, m in sorted(sandbox.normalize(gs)["folders"].items())],
                "network": sandbox.normalize(gs)["network"],
                "sound": sorted(sandbox.normalize(gs)["sound"]), "devices": sorted(sandbox.normalize(gs)["devices"]),
                "caps": sorted(sandbox.normalize(gs)["caps"]), "execDeny": sandbox.normalize(gs)["exec_deny"],
                "capLabels": sandbox.CAP_LABELS, "deviceLabels": sandbox.DEVICE_LABELS, "soundLabels": sandbox.SOUND_LABELS,
                "templates": self.sandboxTemplates, "support": self._sb_support(),
                "freshWarning": self._fresh_warning(url), "launcherHash": self._launcher_hash(url),
                "sessionWarning": self._sb_session_warning(),
                # only an app that has the network can reach an abstract session bus (17.9, R3-8)
                "busWarning": sandbox.bus_warning() if sandbox.normalize(gs)["network"] else {},
                "reviewSuggests": sandbox.summary_chips(suggested, root, self._suggested_template(url)) + sandbox.refused_chips(srefused)
                                  if suggested is not None else [],
                # a review's Off is a suggestion the user adopts with "Use theirs", never applied by itself (17.3.2)
                "suggestsOff": suggested is not None and sandbox.level_of(suggested) == "off",
                # the badge stands until the user acts on *this* suggestion: adopts it, keeps their own
                # grants, or saves a choice of their own knowing it (17.11); a later, different suggestion
                # raises it again. Without that, a user who deliberately chose otherwise had it forever.
                # With "Follow reviewers' suggestions" off there is nothing to act on, so no badge; the
                # dialog still shows what they suggest, and "Use theirs" stays an explicit choice (17.15).
                "reviewBadge": bool(self._prefs.get("sandboxReviewBadge", True)
                                    and self._prefs.get("followReviewerSandbox", True) and suggested is not None
                                    and sandbox.summary(suggested, root) != sandbox.summary(gs, root)
                                    and sandbox.summary(suggested, root) != self._install_settings(url).get("sandboxReviewSeen")),
                # a suggestion that differs from what's in force: the dialog offers to adopt it
                "hasSuggestion": suggested is not None and sandbox.summary(suggested, root) != sandbox.summary(gs, root),
                "reviewBy": self._sandbox_reviewer(url),
                # the badge's words: what the suggestion adds and removes, and what that means (17.11)
                "reviewBadgeText": sandbox.suggestion_text(gs, suggested, self._sandbox_reviewer(url) or "A reviewer")
                                   if suggested is not None else "",
                "appImage": self._sandbox_kind(url) == "appimage",
                "home": sandbox.sandbox_home(self._app_id(url)),
                # a private home on disk, at any level: the uninstall dialog offers to delete it (17.14)
                "hasHome": os.path.isdir(sandbox.sandbox_home(self._app_id(url))),
                "installed": bool(a.get("installed")),
                "selfUpdating": bool(a.get("autoUpdate")),
                # Chromium/Electron apps run without their own sandbox where the system's bwrap
                # profile forbids it inside AppKata's (17.10.2); App Detail says so for such an app
                "ownSandbox": self._brings_own_sandbox(url)}

    def _brings_own_sandbox(self, url: str) -> bool:
        """Whether the installed program brings Chromium's sandbox (chrome-sandbox or
        chrome_crashpad_handler beside it): the launcher's test (17.10.2), made here on the files.
        An AppImage is known once it has been unpacked, at its first sandboxed launch."""
        row = self.db.one("SELECT record FROM installs WHERE url=?", (url,))
        rec = json.loads(row["record"] or "{}") if row else {}
        cur = rec.get("current") or {}
        if not cur.get("path") or not rec.get("target"):
            return False
        appdir, exec_rel, _ = install._launcher_program(rec, rec["target"])
        dirs = {appdir, os.path.dirname(os.path.join(appdir, exec_rel))}
        return any(os.path.exists(os.path.join(d, f)) for d in dirs for f in ("chrome-sandbox", "chrome_crashpad_handler"))


    def _launcher_hash(self, url: str) -> str:
        """The first 16 hex digits of the SHA-256 of the app's launcher text, or "" when it has none:
        what the Audit records of a launcher (17.4; review 2, F11)."""
        text = self.sandboxLaunchCommand(url)
        return hashlib.sha256(text.encode()).hexdigest()[:16] if text else ""

    def _sandbox_detail(self, url: str, before: dict | None, after: dict | None, **extra) -> dict:
        """An Audit entry's detail for a sandbox change (17.16; review 2, F11: it said only the template
        and level, so a folder added read "set the sandbox of X · Custom · standard"): the template as
        the dialog names it, the level, what was added and removed, and the launcher it wrote: a hash
        of its text and the set it was written for (17.4)."""
        off = sandbox.resolve_template("off")
        bg, ag = (before or {}).get("grants") or off, (after or {}).get("grants") or off
        tpl = (after or {}).get("template") or "off"
        label = sandbox.TEMPLATE_LABELS.get(tpl, tpl) + (" · customized" if tpl in sandbox.TEMPLATES and sandbox.customized(tpl, ag) else "")
        added, removed = sandbox.changes(bg, ag)
        out = {"template": label, "level": sandbox.level_of(ag),
               **({"added": ", ".join(added)} if added else {}), **({"removed": ", ".join(removed)} if removed else {})}
        if h := self._launcher_hash(url):
            out.update({"launcher": h, "written for": sandbox.describe(tpl, ag)})
        out.update(extra)
        return out

    @Slot(str, result=str)
    def sandboxLaunchCommand(self, url: str) -> str:
        """The generated launcher text, for "Show the launch command" (17.4)."""
        row = self.db.one("SELECT record FROM installs WHERE url=?", (url,))
        rec = json.loads(row["record"] or "{}") if row else {}
        lp = rec.get("launcher")
        if lp and os.path.exists(lp):
            try:
                with open(lp) as f:
                    return f.read()
            except OSError:
                pass
        return ""

    @Slot(str, "QVariant")
    def setSandbox(self, url: str, config) -> None:
        """Save the user's sandbox choice and, if installed, regenerate the launcher (17.4, 17.11, 17.16).

        config: {"template": name|"off", "overrides": {...}} or {"custom": grant set}, or null to
        clear the user's choice and fall back to reviews/default.
        """
        a = self._app(url)
        config = _plain(config)
        cfg = dict(config) if config else None
        if cfg and (why := sandbox.config_error(cfg)):      # refused before anything is written (R4-1)
            self._toast.emit("error", f"That sandbox choice can't be applied: {why}.")
            return
        if cfg and cfg.get("custom") is not None:      # a picked folder AppKata never shares (17.3.1)
            kept, refused = sandbox.strip_protected(cfg["custom"], self._app_options(url).root)
            if refused:
                cfg["custom"] = sandbox.to_json(kept)
                self._toast.emit("error", "Not shared: " + "; ".join(f"{p} ({why})" for p, why in refused)
                                 + ". AppKata never gives an app these folders.")
        if cfg and cfg.get("custom") is not None and cfg.get("template") in sandbox.TEMPLATES:
            # a template customized in the dialog: saved as it plus the changes, so it keeps its name
            # and Reset to template (review 2, F10: it became "Custom")
            cfg = {"template": cfg["template"], "overrides": sandbox.as_overrides(cfg["template"], cfg["custom"])}
        row = self.db.one("SELECT install FROM app_settings WHERE url=?", (url,))
        saved = json.loads(row["install"] or "{}") if row and row["install"] else {}
        before = self._resolved_sandbox(url)
        if cfg is None:             # back to the reviewers' suggestion / the default: adopt it now (17.11)
            saved.pop("sandbox", None)
            saved.pop("sandboxPinned", None)
        else:
            saved["sandbox"] = cfg
        saved["sandboxReviewSeen"] = self._review_suggestion_summary(url)      # chosen knowing it (17.11)
        self._set_install_settings(url, saved)
        r = self._resolved_sandbox(url)
        if cfg is None and a and a.get("installed"):
            self._pin_sandbox(url, r)
        if a and a.get("installed") and not a.get("foreign"):
            self._regenerate_launcher(url)
        self._audit("you", "app", "set the sandbox of", a["name"] if a else url, url, self._sandbox_detail(url, before, r))
        self.reload()

    def _review_suggestion_summary(self, url: str) -> list | None:
        """The merged reviews' suggestion as summary labels, or None when no review says anything."""
        suggested, _ = self._suggestion(url)
        return sandbox.summary(suggested, self._app_options(url).root) if suggested is not None else None

    @Slot(str)
    def useSuggestion(self, url: str) -> None:
        """"Use theirs" (17.11): adopt the reviewers' suggestion. A suggestion of Off becomes the user's
        own choice, since a review never turns the sandbox off by itself (17.3.2, review 2 F8); any
        other clears the user's choice and pins the merged reviews."""
        suggested, _ = self._suggestion(url)
        if suggested is not None and sandbox.level_of(suggested) == "off":
            self.setSandbox(url, {"template": "off"})
        else:
            self.setSandbox(url, None)

    @Slot(str)
    def keepSandbox(self, url: str) -> None:
        """"Keep mine" on the review badge (17.11): the app keeps its grants and the badge clears for
        this suggestion; a later, different one raises it again."""
        saved = self._install_settings(url)
        saved["sandboxReviewSeen"] = self._review_suggestion_summary(url)
        self._set_install_settings(url, saved)
        a = self._app(url)
        self._audit("you", "app", "kept the sandbox of", a["name"] if a else url, url,
                    {"suggested": ", ".join(saved["sandboxReviewSeen"] or [])})
        self.reload()

    def _regenerate_launcher(self, url: str) -> None:
        """Rewrite ~/bin/apps/<app>/run for the current grant set, without reinstalling (17.4)."""
        a = self._app(url)
        if not a:
            return
        gs = self._sandbox_for_install(url)
        try:
            install.rewrite_launcher(self.db, {**a, "sandbox": gs}, self._app_options(url))
        except (install.InstallError, OSError) as e:
            log.warning("couldn't regenerate the launcher for %s: %s", url, e)

    def _heal_launchers_at_startup(self) -> None:
        """The startup pass, on its own thread: warm the bwrap probe (a 15 s timeout at worst) so the
        first App Detail or Settings → Sandbox on the UI thread finds the answer cached, then give any
        app installed while the system couldn't sandbox its launcher. Regression (round two, R5): the
        heal pass only probed when something needed healing, so on an ordinary start — every launcher
        in place — the probe still ran on the UI thread, the very thing moving it here was for."""
        try:
            sandbox.userns_works()
            # logs an older AppKata kept by name move to their install's id, before the heal pass
            # rewrites the launchers that name them (14.2.1; review 2, F14)
            applog.adopt_name_logs([(install.app_id_of(json.loads(r["record"] or "{}"), {"name": r["name"]}), r["name"])
                                    for r in self.db.all("SELECT name, record FROM installs")])
            if self._heal_launchers():
                self._refresh.emit()
        except Exception:           # never let this block startup
            log.exception("couldn't regenerate sandbox launchers")

    def _heal_launchers(self, actor: str = "system") -> list[str]:
        """Give every installed app that should be sandboxed, but was installed while this system
        couldn't (AppArmor setup pending, or bwrap missing), its launcher now that it can (17.10) --
        and every app whose launcher is not the one AppKata would write today (one an older AppKata
        wrote before a launcher fix, a hand-edited one, or one written before xdg-dbus-proxy was
        installed) the current text (17.4; round four, R4-4: a launcher that existed was never looked
        at again). Returns the URLs
        regenerated. Nothing happens until sandboxing actually works here. An app installed outside
        AppKata (foreign, 4.5) is left alone, as setSandbox leaves it. The apps sandboxed for the first
        time are named in a notice and audited, by `actor` (17.13; review 2, F13: nothing said so)."""
        todo, undo = [], []
        for row in self.db.all("SELECT url, record FROM installs"):
            rec = json.loads(row["record"] or "{}")
            if not rec.get("current"):
                continue
            if row["url"] == APPKATA_REPO:         # never sandboxed: undo a launcher an older AppKata gave it (R3-6)
                if rec.get("launcher"):
                    undo.append(row["url"])
                continue
            a = self._app(row["url"])
            if not a or a.get("foreign"):          # nothing to regenerate from, or not AppKata's to touch
                continue
            r = self._resolved_sandbox(row["url"])
            if not r or sandbox.level_of(r["grants"]) == "off":
                continue
            if not install.launcher_is_current(rec, {**a, "sandbox": r["grants"]}, self._app_options(row["url"])):
                todo.append(row["url"])
        for url in undo:
            self._regenerate_launcher(url)
            log.info("AppKata runs unsandboxed again: removed the launcher an older version gave it")
        if not todo or not sandbox.have_tools() or sandbox.support_status()["status"] != "ok":
            return undo
        first = []
        for url in todo:
            had, fresh = self._sandbox_state(url)
            self._regenerate_launcher(url)
            log.info("brought the launcher of %s up to today's text" if had else "sandboxed %s now that this system supports it", url)
            if not had and self._sandbox_state(url)[0]:
                first.append((url, (self._app(url) or {}).get("name", url), fresh))
            elif had:          # an older AppKata's launcher, or a hand-edited one: one entry per app (17.16, F11)
                r = self._resolved_sandbox(url)
                self._audit(actor, "app", "rewrote the launcher of", (self._app(url) or {}).get("name", url), url,
                            {"by": f"AppKata {APPKATA_VERSION}", "launcher": self._launcher_hash(url),
                             "written for": sandbox.describe(r["template"], r["grants"]) if r else ""})
        self._tell_sandboxed(first, actor)
        return undo + todo

    @Slot()
    def setupSandboxSupport(self) -> None:
        """The one-time AppArmor setup behind a single pkexec prompt (17.10): Settings' Set up… and App
        Detail's Enable…. Asking for it clears a "Not now" given at an install (review 2, F12)."""
        self.setPref("sandboxSetupDeclined", False)
        threading.Thread(target=self._run_setup, daemon=True).start()

    def _run_setup(self) -> bool:
        """The setup itself, on a worker thread; whether it worked."""
        ok = False
        try:
            sandbox.install_profile()
            self._heal_launchers("you")     # apps installed meanwhile ran Off; sandbox them now
            self._audit("you", "setting", "enabled system sandbox support", "AppArmor", "",
                        {"profile": sandbox.PROFILE_PATH})
            self._toast.emit("info", "Sandbox support is set up. Sandboxed apps will now run contained.")
            ok = True
        except sandbox.SandboxError as e:
            self._toast.emit("error", f"Sandbox setup: {e}")
        self.prefsChanged.emit()
        self._refresh.emit()
        return ok

    def _setup_prompt_needed(self, url: str, choice=None) -> bool:
        """Whether installing `url` is the sandbox's first need (17.10; review 2, F12): a fresh install
        that would run sandboxed, on a system that blocks bwrap until the one-time setup, and no "Not
        now" given at an earlier install."""
        a = self._app(url)
        if not a or a.get("installed") or a.get("foreign") or self._prefs.get("sandboxSetupDeclined"):
            return False
        r = self._resolved_sandbox(url, kind=(choice or {}).get("kind") or None)
        if not r or sandbox.level_of(r["grants"]) == "off":
            return False
        return sandbox.have_tools() and self._sb_support()["status"] == "setup-needed"

    @Slot("QVariant", bool)
    def answerSandboxSetup(self, info, now: bool) -> None:
        """The first-need prompt's answer (17.10). "Set up now" runs the setup, then installs, sandboxed
        if it worked. "Not now" installs it to run Off and is remembered, so later installs don't ask;
        Set up… and Enable… still can, and clear it. Either way the Audit says so."""
        info = dict(_plain(info))
        if not now:
            self.setPref("sandboxSetupDeclined", True)
            self._audit("you", "setting", "put off system sandbox support", "AppArmor", info.get("url", ""),
                        {"installing": info.get("name", "")})
            self._install_after_prompt(info)
            return
        self.setPref("sandboxSetupDeclined", False)

        def work():
            self._run_setup()
            self._setupThenInstall.emit(info)
        threading.Thread(target=work, daemon=True).start()

    def _install_after_prompt(self, info) -> None:
        info = dict(_plain(info))
        self._install(info["url"], info.get("version") or "", info.get("choice") or None,
                      info.get("pin", True), info.get("confirmed", False), asked=True)

    @Slot()
    def repairSandboxSupport(self) -> None:
        """Remove AppKata's AppArmor profile where the system now has its own for bwrap (an upgrade to
        Ubuntu 25.04+, status "conflict", 17.10.2): with both loaded bwrap starts for no one."""
        def work():
            try:
                others = sandbox.other_bwrap_profiles()
                sandbox.remove_profile()
                self._heal_launchers("you")     # apps that couldn't start get today's launcher, under the system's profile
                self._audit("you", "setting", "removed AppKata's AppArmor profile", "AppArmor", "",
                            {"profile": sandbox.PROFILE_PATH, "system profile": ", ".join(others)})
                self._toast.emit("info", "AppKata's old AppArmor profile is removed; sandboxes run under the system's own.")
            except sandbox.SandboxError as e:
                self._toast.emit("error", f"Sandbox repair: {e}")
            self.prefsChanged.emit()
            self._refresh.emit()
        threading.Thread(target=work, daemon=True).start()

    @Slot(str, bool)
    def uninstallSandbox(self, url: str, remove_home: bool) -> None:
        """Uninstall, optionally deleting the app's private sandbox home (17.14)."""
        self._uninstall(url, False, remove_home=remove_home)

    @Slot(str, str)
    def removeVersion(self, url: str, version: str) -> None:
        a = self._app(url)
        try:
            install.remove_version(self.db, url, version)
        except install.InUse as e:
            self.inUse.emit({"url": url, "name": a["name"] if a else "", "action": "removeVersion", "version": version,
                             "programs": [os.path.basename(x) for x in e.programs]})
            return
        self._audit("you", "app", "removed a kept version of", a["name"] if a else url, url, {"version": version})
        self.reload()

    @Property("QVariant", notify=prefsChanged)
    def locations(self):
        from appkata_core.platform import OS, apps_dir, command_dir_default
        return {"windows": OS == "windows", "defaultInstallDirEveryone": apps_dir("everyone"),
                "installDirEveryone": install.Portable(scope="everyone", folder_everyone=self._prefs.get("installDirEveryone") or "").root,
                "defaultCommandDir": command_dir_default(), "autostartOn": desktop.autostart_on(),
                "database": self.db.path, "dataDir": self.root, "logDir": applog.log_dir(),
                "logFile": os.path.join(applog.log_dir(), applog.CURRENT), "defaultInstallDir": apps_dir(),
                "installDir": self.portable().root, "home": os.path.expanduser("~"),
                "sandboxDir": sandbox.sandboxes_root(),
                "linksRegistered": desktop.scheme_registered(), "autostartFile": desktop.autostart_path()}

    @Property("QVariant", notify=prefsChanged)
    def tokenHosts(self):
        return [{"host": h, "hint": "••••" + t[-4:] if len(t) > 4 else "••••"} for h, t in sorted(self.db.get("tokens", {}).items())]

    @Slot(str)
    def openFolder(self, path: str) -> None:
        try:
            desktop.open_folder(os.path.dirname(path) if os.path.isfile(path) else path)
        except OSError as e:
            self.toast.emit("error", str(e))

    @Slot(bool)
    def registerLinks(self, on: bool) -> None:
        ok = desktop.register_scheme(on)
        self._audit("you", "setting", "registered appkata:// links" if ok else "unregistered appkata:// links", "appkata://")
        self.prefsChanged.emit()

    @Slot(str)
    def exportTo(self, path: str) -> None:
        try:
            data = transfer.export(self.db, self._prefs)
            transfer.write(path, data)
            self._audit("you", "setting", "exported settings to", path, "", {"sources": len(data["sources"]), "trusts": len(data["trusts"])})
            self.toast.emit("info", f"Exported {len(data['sources'])} sources and {len(data['trusts'])} trusts.")
        except OSError as e:
            self.toast.emit("error", f"Export failed: {e}")

    @Slot(str)
    def importFrom(self, path: str) -> None:
        def work():
            try:
                data = transfer.read(path)
                res = transfer.apply(self.db, self.http, data)
                for k, v in (data.get("settings") or {}).items():
                    if k in prefs_mod.DEFAULTS and k not in ("reviewPath",):
                        self._prefs[k] = v
                prefs_mod.save(self._prefs)
                self._audit("you", "setting", "imported settings from", path, "",
                            {"sources": res["sources"], "trusts": res["trusts"], "skipped": res["skipped"], "problems": len(res["problems"])})
                for p in res["problems"]:
                    log.warning("import: %s", p)
                msg = f"Imported {res['sources']} sources and {res['trusts']} trusts" + (f"; {res['skipped']} already here" if res["skipped"] else "")
                self._toast.emit("error" if res["problems"] else "info", msg + (f"; {len(res['problems'])} problems (see the app log)" if res["problems"] else "."))
                self.prefsChanged.emit()
                sync.sync_all(self.db, self.http)
            except (OSError, ValueError) as e:
                self._toast.emit("error", f"Import failed: {e}")
            self._refresh.emit()
        threading.Thread(target=work, daemon=True).start()

    # ---------------------------------------------------------------- audit, explore, log
    @Slot(int, str, str, result="QVariant")
    def auditPage(self, before: int, kind: str, text: str):
        """Requirement 13.4: pages of 100, newest first, loaded as the list scrolls."""
        out = []
        for r in audit.page(self.db, before, 100, kind, text):
            try:
                d = json.loads(r["detail"]) if r["detail"] else {}
            except ValueError:
                d = {"note": r["detail"]}
            out.append({**r, "details": [[k, v if isinstance(v, str) else json.dumps(v)] for k, v in (d or {}).items()
                                          if v is not None and v != [] and v != ""]})
        return out

    @Property(int, notify=auditChanged)
    def auditCount(self):
        return audit.count(self.db)

    @Property("QVariant", notify=changed)
    def exploreServices(self):
        """Explore's picker: the forges, ngit, and on Linux Flathub and the distribution (7.7.1, 16.2.3)."""
        out = [{"key": k, "label": v, "enabled": True, "tip": ""} for k, v in explore.SERVICES]
        if self.ch.enabled:
            out.append({"key": "flathub", "label": "Flathub", "enabled": True, "tip": ""})
            ok = self.ch.catalog_available()
            out.append({"key": "distro", "label": self.ch.distro or "Distribution", "enabled": ok,
                        "tip": "" if ok else "No AppStream catalog on this computer"})
        return out

    @Slot(str, str)
    def explore(self, service: str, q: str) -> None:
        def work():
            if service in ("flathub", "distro"):
                res = self.ch.explore(self.http, service, q)
            else:
                res = explore.search(self.http, service, q, self._prefs.get("relays") or None)
            mine = {s["url"] for s in self.db.all("SELECT url FROM sources")}
            listed = {r["url"] for r in self.db.all("SELECT DISTINCT url FROM reviews")}
            for m in res["matches"]:
                n = urls.try_normalize(m["url"]) if m["url"] else None
                m["isSource"] = n in mine
                m["listed"] = n in listed
            self.exploreResults.emit({"service": service, "q": q, **res})
        threading.Thread(target=work, daemon=True).start()

    @Slot()
    def showAppLog(self) -> None:
        """Requirement 14.5: both log files, joined into a temp file, opened in the text editor."""
        log.info("showing the app log")
        try:
            applog.open_in_editor(applog.combined())
        except OSError as e:
            self.toast.emit("error", f"Couldn't open the log: {e}")

    # ---------------------------------------------------------------- tour hooks
    @Slot(bool)
    def demoSelfUpdated(self, on: bool) -> None:
        if getattr(self, "_demo_self_updated", False) != on:
            self._demo_self_updated = on
            self.reload()

    @Slot(str)
    def demoMsvcrt(self, url: str) -> None:
        """The tour: show an app as needing the Visual C++ run-time, which is missing (15.18)."""
        want = {url} if url else set()
        if getattr(self, "_demo_msvcrt", set()) != want:
            self._demo_msvcrt = want
            self.reload()

    @Slot(str)
    def demoSandbox(self, mode: str) -> None:
        """The tour: force a sandbox state the offscreen run can't show for real — "x11" (the session
        warning), "setup" (AppArmor setup needed), "ok" (a working system, no warning: every other
        screen, so none shows the machine running the tour), or "" (none)."""
        if getattr(self, "_demo_sandbox", "") != mode:
            self._demo_sandbox = mode
            self.reload()               # the Apps list's 17.12 rule asks _runs_sandboxed too
            self.prefsChanged.emit()
            self.changed.emit()

    @Slot()
    def demoClearBusy(self) -> None:
        if self._busy:
            self._busy.clear()
            self.busyChanged.emit()

    @Slot(str, "QVariant")
    def demoBusy(self, url: str, value) -> None:
        if value:
            self._busy[url] = dict(_plain(value))
        else:
            self._busy.pop(url, None)
        self.busyChanged.emit()


def _same_digest(theirs: str, mine: str) -> bool:
    """A digest from a review's Details, possibly shortened as "3c1f…9e07", is this one (10.3.4)."""
    theirs, mine = (theirs or "").strip().lower().removeprefix("sha256:"), (mine or "").strip().lower()
    if not theirs or not mine:
        return False
    for sep in ("…", "..."):
        if sep in theirs:
            pre, _, suf = theirs.partition(sep)
            return len(pre) + len(suf) >= 6 and mine.startswith(pre) and mine.endswith(suf)
    return mine.startswith(theirs) if len(theirs) >= 7 else False


def _clean_source_settings(st: dict, track_default: bool = False) -> dict:
    """Source settings as stored (requirement 2.6): the asset filter is kept per platform; Track
    only only when it differs from what applies anyway."""
    from appkata_core.platform import OS, arch
    out = {k: v for k, v in st.items() if k not in ("assetFilter", "trackOnly")}
    if "trackOnly" in st:
        out["track_only"] = bool(st["trackOnly"])
    if "assetFilter" in st:
        filters = dict(out.get("asset_filters") or {})
        filters[f"{OS}-{arch()}"] = st["assetFilter"] or ""
        out["asset_filters"] = {k: v for k, v in filters.items() if v}
        out.pop("asset_filter", None)
    if out.get("prereleases") is None:
        out.pop("prereleases", None)
    if not out.get("forge"):
        out.pop("forge", None)
    if "track_only" in out and bool(out["track_only"]) == track_default:
        out.pop("track_only", None)
    if not out.get("asset_filters"):
        out.pop("asset_filters", None)
    for k in ("flatpak", "package"):          # the user's own channel links (requirement 16.1.3)
        if k in out and not str(out[k] or "").strip():
            out.pop(k)
        elif k in out:
            out[k] = " ".join(str(out[k]).split())
    return out
