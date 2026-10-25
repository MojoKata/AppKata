"""The package-channel glue the screens use (requirement 16): what the Apps view and App Detail
panel show for a channel install, Explore on Flathub and the distribution, Source settings' links,
the Audit's System filter, and "Same file as … reviewed" (10.3.4)."""

import json
import os

import pytest

from appkata_core import appstream, audit, catalog, channels, explore
from appkata_core.autoupdate import Detection
from appkata_core.db import DB, now
from appkata_core.http import Http, Unreachable

HERE = os.path.dirname(os.path.abspath(__file__))
KEEPASSXC = "https://github.com/keepassxreboot/keepassxc"
RELEASES = [{"version": v, "date": f"2026-0{9 - i}-01T00:00:00Z", "assets": [{"name": "x.AppImage", "url": "u", "size": 1}]}
            for i, v in enumerate(("2.7.10", "2.7.9", "2.7.8", "2.7.6"))]


@pytest.fixture
def db(tmp_path):
    d = DB(str(tmp_path / "appkata.db"))
    d.x("INSERT INTO sources(url, settings, added_at) VALUES(?,?,?)", (KEEPASSXC, "{}", now()))
    d.x("INSERT INTO apps(url, name, releases) VALUES(?,?,?)", (KEEPASSXC, "KeePassXC", json.dumps(RELEASES)))
    return d


def _install(db, rec, version="2.7.6"):
    db.x("INSERT OR REPLACE INTO installs(url, name, version, kind, record, installed_at) VALUES(?,?,?,?,?,?)",
         (KEEPASSXC, "KeePassXC", version, rec["channel"], json.dumps(rec), now()))


def _app(db):
    return next(a for a in catalog.build(db, "linux", "x86_64") if a["url"] == KEEPASSXC)


def test_flatpak_updated_by_the_system(db):
    db.put("autoupdate", Detection(flatpak=["GNOME Software"]).as_dict())
    _install(db, {"channel": "flatpak", "flatpak": "org.keepassxc.KeePassXC", "remote": "flathub", "perms": ["Network"],
                  "pending": {"version": "2.7.10", "addedPerms": ["Home folder"]}})
    a = _app(db)
    assert a["state"] == "system" and a["ch"]["updates"] == "system" and a["ch"]["updatesBy"] == "GNOME Software"
    assert a["ch"]["label"] == "Flathub" and a["ch"]["addedPerms"] == ["Home folder"] and a["permsGrow"]
    assert a["updateTo"] == "" and a["newer"]                   # 2.7.10 is out, but the system updates it (16.5.1)
    db.x("INSERT INTO channel_checks(url, kind, value, state, verified) VALUES(?,?,?,?,?)",
         (KEEPASSXC, "flatpak", "org.keepassxc.KeePassXC", "matches", 1))
    assert _app(db)["ch"]["label"] == "Flathub · verified"


def test_package_not_updated_offers_its_update(db):
    db.put("autoupdate", Detection().as_dict())
    _install(db, {"channel": "package", "package": "keepassxc", "manager": "dnf", "signer": "Fedora", "pkgVersion": "2.7.6-1.fc41",
                  "pending": {"version": "2.7.9-1.fc41", "projectVersion": "2.7.9"}})
    a = _app(db)
    assert a["ch"]["updates"] == "not-updated" and a["state"] == "update" and a["updateTo"] == "2.7.9"
    assert a["ch"]["behind"] == 3 and a["ch"]["label"] == "Fedora" and not a["permsGrow"]
    rec = json.loads(db.one("SELECT record FROM installs")["record"])
    _install(db, {**rec, "held": True})
    assert _app(db)["ch"]["updates"] == "held" and _app(db)["state"] == "installed"       # 16.5.6
    _install(db, {**rec, "updates": "appkata"})
    assert _app(db)["ch"]["updates"] == "appkata" and _app(db)["state"] == "update"


def test_adoptable_foreign_install(db):
    db.x("INSERT INTO foreign_installs(url, location, version, checked_at, adopt) VALUES(?,?,?,?,?)",
         (KEEPASSXC, "Flatpak org.keepassxc.KeePassXC", "2.7.9", now(), json.dumps({"kind": "flatpak", "value": "org.keepassxc.KeePassXC"})))
    a = _app(db)
    assert a["state"] == "foreign" and a["adoptable"]


class _Down(Http):
    def request(self, url, **kw):
        raise Unreachable("couldn't reach flathub.org")


def test_explore_flathub_offline_and_distro(db):
    cat = appstream.Catalog([appstream.Component("org.keepassxc.KeePassXC", "desktop-application", "KeePassXC", "Password manager",
                                                 bundle="app/org.keepassxc.KeePassXC/x86_64/stable", origin="flathub",
                                                 urls={"vcs-browser": KEEPASSXC}),
                             appstream.Component("org.keepassxc.KeePassXC.desktop", "desktop-application", "KeePassXC", "Password manager",
                                                 package="keepassxc", urls={"homepage": "https://keepassxc.org"})])
    r = explore.search(_Down(), "flathub", "password", catalog=cat)
    assert r["matches"][0]["url"] == KEEPASSXC and r["matches"][0]["link"] == "org.keepassxc.KeePassXC"
    assert "Couldn't reach Flathub" in r["note"] and "on this computer" in r["note"]
    assert explore.search(_Down(), "flathub", "password", catalog=None)["error"].startswith("Couldn't reach Flathub")
    d = explore.search(Http(), "distro", "keepass", catalog=cat)["matches"]
    assert d[0]["channel"] == "package" and d[0]["link"] == "keepassxc" and d[0]["url"] == "" and not d[0]["addable"]   # 16.2.4
    assert explore.search(Http(), "distro", "keepass", catalog=None)["error"] == "No AppStream catalog on this computer."


def test_links_without_mine(db):
    db.x("UPDATE sources SET settings=? WHERE url=?", (json.dumps({"flatpak": "org.mine.K"}), KEEPASSXC))
    assert channels.links(db, KEEPASSXC, None, "apt")["flatpak"].source == "you"
    assert "flatpak" not in channels.links(db, KEEPASSXC, None, "apt", ignore_mine=True)       # Source settings' placeholder


def test_audit_system_filter(db):
    audit.record(db, "system", "app", "was updated outside AppKata", "KeePassXC", KEEPASSXC, {"by": "GNOME Software"})
    audit.record(db, "you", "app", "installed", "KeePassXC", KEEPASSXC)
    assert [r["actor"] for r in audit.page(db, kind="actor:system")] == ["system"]
    assert len(audit.page(db, kind="app")) == 2


def test_same_digest_and_source_settings():
    pytest.importorskip("PySide6")                       # the backend module is Qt's (the Windows tests run without it)
    from appkata.backend import _clean_source_settings, _same_digest
    full = "3c1f" + "0" * 56 + "9e07"
    assert _same_digest("3c1f…9e07", full) and _same_digest(full, full) and _same_digest("sha256:" + full, full)
    assert not _same_digest("3c1f…9e08", full) and not _same_digest("3c…07", full) and not _same_digest("", full)
    assert _clean_source_settings({"flatpak": " flathub  org.x.Y ", "package": ""}) == {"flatpak": "flathub org.x.Y"}


def test_demo_channels_recommend(db, tmp_path):
    from appkata.channelui import Channels
    (tmp_path / "demo-channels.json").write_text(json.dumps({
        "manager": "apt", "distro": "Ubuntu",
        "links": {KEEPASSXC: {"flatpak": {"value": "org.keepassxc.KeePassXC"}, "package": {"value": "keepassxc", "manager": "apt"},
                              "channel": ["package", "Mara"]}},
        "facts": {KEEPASSXC: {"package": {"version": "2.7.6+dfsg.1-1build1"}}}}))
    os.environ["APPKATA_DEMO_CHANNELS"] = "1"
    try:
        ch = Channels(db, str(tmp_path))
    finally:
        del os.environ["APPKATA_DEMO_CHANNELS"]
    cards = ch.cards(KEEPASSXC, [{"kind": "appimage", "category": "portable", "label": "AppImage"}], RELEASES)
    assert [c["channel"] for c in cards] == ["package", "release", "flatpak"]
    assert cards[0]["recommended"] and cards[0]["recommendedBy"] == "Mara" and cards[0]["behind"] == 3
    assert cards[0]["label"] == "Ubuntu package"
