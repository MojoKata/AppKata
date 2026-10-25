"""Package channels for the GUI (requirement 16): the install dialog's channel cards, the channels an
app has, and Explore on Flathub and the distribution. The core is appkata_core.channels and friends;
this module only gathers what the screens show."""

from __future__ import annotations

import json
import logging
import os

from appkata_core import appstream, channels, explore, flatpak, pkgbackend
from appkata_core.db import DB

log = logging.getLogger("appkata.channels")


# ---------------------------------------------------------------- DEV ONLY: demo channel facts
# This computer may have no flatpak, apt or AppStream catalog, yet the screenshot tour and the demo
# data need channel cards and Explore results. With APPKATA_DEMO_CHANNELS set (to a JSON file, or to
# 1 for <data folder>/demo-channels.json, written by scripts/demo_data.py), the facts below come from
# that file instead of this computer. Never set in normal use.
def demo(data_dir: str) -> dict | None:
    v = os.environ.get("APPKATA_DEMO_CHANNELS", "")
    if not v:
        return None
    path = os.path.join(data_dir, "demo-channels.json") if v == "1" else v
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        log.warning("DEV: channel facts come from %s (APPKATA_DEMO_CHANNELS)", path)
        return d
    except (OSError, ValueError):
        log.exception("DEV: couldn't read %s", path)
        return None


def load_demo_file(data_dir: str) -> dict | None:
    """DEV ONLY: the tour turns the demo facts on for its channel screens (backend.demoChannels)."""
    try:
        with open(os.path.join(data_dir, "demo-channels.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


class Channels:
    """What the screens need about channels on this computer (or from the demo file)."""

    def __init__(self, db: DB, data_dir: str):
        self.db = db
        self.data_dir = data_dir
        self.fake = demo(data_dir)

    @property
    def enabled(self) -> bool:
        return bool(self.fake) or channels.enabled()

    @property
    def manager(self) -> str:
        return self.fake.get("manager", "") if self.fake else channels.manager()

    @property
    def distro(self) -> str:
        return self.fake.get("distro", "") if self.fake else channels.distro_name()

    def catalog(self):
        if self.fake:
            return None
        try:
            return appstream.load_cached()
        except OSError:
            return None

    def catalog_available(self) -> bool:
        if self.fake:
            return bool(self.fake.get("catalog", True))
        cat = self.catalog()
        return bool(cat and cat.available)

    def links(self, url: str, ignore_mine: bool = False) -> dict:
        if not self.enabled:
            return {}
        if self.fake and url in (self.fake.get("links") or {}):          # DEV ONLY
            return {k: channels.Link(k, v["value"], v.get("remote", "flathub"), v.get("manager", ""), v.get("source", "trust"),
                                     v.get("via", "")) for k, v in self.fake["links"][url].items() if k in ("flatpak", "package")}
        return channels.links(self.db, url, self.catalog(), self.manager, ignore_mine)

    def facts(self, url: str, found: dict) -> dict:
        """What each channel offers now: version, size, repository (16.3.1)."""
        if self.fake:
            return (self.fake.get("facts") or {}).get(url, {})
        out = {}
        fl, pk = found.get("flatpak"), found.get("package")
        try:
            if fl and flatpak.available() and flatpak.has_remote(fl.remote):
                i = flatpak.remote_info(fl.value, fl.remote)
                out["flatpak"] = {"version": i.get("version", ""), "sizeText": i.get("download", ""), "commit": i.get("commit", "")}
            if pk and self.manager:
                v = pkgbackend.package_version_available(pk.value, self.manager)
                if v:
                    out["package"] = {"version": v, "origin": pk.extra.get("origin", "")}
        except Exception:      # noqa: BLE001 — facts are nice to have; never break the dialog
            log.exception("channel facts for %s", url)
        return out

    def checks(self, url: str, found: dict) -> dict:
        out = {k: channels.get_check(self.db, url, k, l.value) for k, l in found.items()}
        for k, v in ((self.fake or {}).get("checks") or {}).get(url, {}).items():     # DEV ONLY
            out[k] = {**out.get(k, {}), **v}
        return out

    def updater(self, kind: str) -> str:
        """Who would update a new install from this channel (16.5.2), e.g. "GNOME Software", or ""."""
        from appkata_core import autoupdate
        det = autoupdate.Detection.from_dict((self.fake or {}).get("autoupdate") or self.db.get("autoupdate", {}) or {})
        if kind == "flatpak":
            return autoupdate.flatpak_owner(det)
        if self.fake:
            return (det.packages or [""])[0] or ("unattended-upgrades" if self.fake.get("packagesAuto") else "")
        return autoupdate.package_owner(det, self.manager)

    def cards(self, url: str, release_files: list[dict], releases: list[dict]) -> list[dict]:
        """The install dialog's cards: release files and channels, Recommended first (16.3.1, 16.3.2)."""
        found = self.links(url)
        if not found:
            return [{"channel": "release", **f} for f in release_files]
        facts = self.facts(url, found)
        out = channels.options(self.db, url, release_files, found, self.checks(url, found), facts)
        rec = (((self.fake or {}).get("links") or {}).get(url) or {}).get("channel")      # DEV ONLY: a Trust's Channel line
        if rec:
            i = next((i for i, c in enumerate(out) if c["channel"] == rec[0]), None)
            if i is not None:
                out.insert(0, out.pop(i))
                out[0]["recommendedBy"] = rec[1]
                for j, c in enumerate(out):
                    c["recommended"] = j == 0
        for c in out:
            if c["channel"] == "package":
                pv = channels.project_version(self.manager, c.get("version", ""))
                c["behind"] = channels.releases_behind(releases, pv) if pv else 0
                c["distro"] = self.distro
                c["managerName"] = self.manager or "apt"
            if c["channel"] in ("flatpak", "package"):
                c["updater"] = self.updater(c["channel"])
                c["label"] = ("Flathub" if c.get("remote", "flathub") == "flathub" else c.get("remote")) \
                    if c["channel"] == "flatpak" else f"{self.distro} package"
        return out

    def summary(self, url: str) -> list[dict]:
        """The channels an app has, for the App Detail panel (16.6.1)."""
        found = self.links(url)
        checks = self.checks(url, found) if found else {}
        out = []
        for k, l in found.items():
            c = checks.get(k, {})
            if k == "flatpak":
                flag = c.get("verified")
                label = ("Flathub" if l.remote == "flathub" else l.remote) + \
                    (" · verified" if flag else " · community" if flag is not None else "")
            else:
                label = f"{self.distro} package"
            out.append({"kind": k, "label": label, "value": l.value, "check": c.get("state", ""), "detail": c.get("detail", ""),
                        "source": l.source, "via": l.via, "verified": c.get("verified")})
        return out

    def explore(self, http, service: str, q: str) -> dict:
        """Explore on Flathub or the distribution (16.2.3)."""
        if self.fake:
            res = (self.fake.get("explore") or {}).get(service)
            if res is not None:
                ms = res.get("matches", [])
                return {"matches": [{**explore.Match("", "", "", "").dict(), **m} for m in ms],
                        "error": res.get("error", ""), "note": res.get("note", "")}
        return explore.search(http, service, q, catalog=self.catalog())
