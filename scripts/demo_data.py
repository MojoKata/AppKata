#!/usr/bin/env python3
"""Demo data for the screenshot tour (appkata --tour) and for trying AppKata out.

    scripts/demo_data.py build DIR     Trust repos (really signed), your AppKata.md, Sources; no network
    scripts/demo_data.py sync DIR      sync the Catalog from GitHub (about 3 API calls per app)
    scripts/demo_data.py finish DIR    installs as of "a while ago", pins and a minimum age, from the real releases
    scripts/demo_data.py stage DIR     before a tour: the minimum age and the sync times, as of now
    scripts/demo_data.py check DIR     before a tour, after stage: exit 1 if an app's last sync failed (but for the errors the
                                       demo shows), or the data doesn't show what screenshots/README.md says
    scripts/demo_data.py retry DIR     sync again the apps whose last sync failed (GitHub answers 5xx at times)
    scripts/demo_data.py remake DIR    build and finish again, keeping DIR's synced Catalog for the apps the build
                                       lists (it stops on one DIR never synced); no network

The apps are real GitHub projects. Every reviewer and signer is made up, and so is
TurboShield VPN (on the reserved git.example.org domain). Then:

    APPKATA_DATA=DIR XDG_DATA_HOME=DIR/xdg appkata --tour screenshots/linux
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))

from appkata_core import APPKATA_REPO, devtools, sync  # noqa: E402
from appkata_core.db import DB, now  # noqa: E402
from appkata_core.http import Http  # noqa: E402

GH = "https://github.com/"
SOURCES = ["localsend/localsend", "signalapp/Signal-Desktop", "keepassxreboot/keepassxc", "obsproject/obs-studio",
           "laurent22/joplin", "ventoy/Ventoy", "syncthing/syncthing", "Zettlr/Zettlr"]
SOURCE_SETTINGS = {     # Source settings (requirement 2.6); Zettlr's are all set, for its review's Settings section
    "laurent22/joplin": {"track_only": True},
    "Zettlr/Zettlr": {"track_only": False, "prereleases": False, "forge": "github", "asset_filters": {"linux-x86_64": "x86_64\\.AppImage$"}},
}
TABLE = "| App | Source | Tags | Trust | Rating |\n|---|---|---|---|---|\n"


def row(app, src, tags, trust, rating):
    return f"| {app} | {src if '://' in src else GH + src} | {tags} | {trust} | {rating} |\n"


MARA = TABLE + "".join([
    row("LocalSend", "localsend/localsend", "foss, donation, offline", 5, 4.5 and 4),
    row("KeePassXC", "keepassxreboot/keepassxc", "foss, offline, signed, reproducible, portable", 5, 5),
    row("Syncthing", "syncthing/syncthing", "foss, donation, reproducible, offline", 5, 4),
    row("OBS Studio", "obsproject/obs-studio", "foss, donation", 5, 5),
    row("Joplin", "laurent22/joplin", "foss, donation", 4, 4),
    row("Signal Desktop", "signalapp/Signal-Desktop", "foss, saas, donation, nonfreenet", 4, 4),
    row("VSCodium", "VSCodium/vscodium", "foss", 4, 4),
    row("Zettlr", "Zettlr/Zettlr", "foss", 4, 4),
    row("Upscayl", "upscayl/upscayl", "foss, offline", 5, 5),
    row("Ventoy", "ventoy/Ventoy", "foss, upstreamnonfree", 3, 5),
    row("Proton VPN", "ProtonVPN/proton-vpn-gtk-app", "foss, freemium, saas", 4, 4),
    row("TurboShield VPN", "https://git.example.org/turboshield/vpn-desktop", "tracking, saas", 2, 2),
]) + """
# LocalSend

No account, no cloud: transfers stay on the LAN and are TLS-encrypted. Releases are built in CI
from tagged commits, with checksums.

# Upscayl

Runs the models locally, nothing is uploaded. GPU acceleration through Vulkan works well.

## Upscayl::Settings

- App menu: yes
- Command link: no
- Stable name link: yes

# KeePassXC

Offline password manager; no reason for it to touch the network. The Offline editor sandbox fits:
give it only the folder your database lives in.

## KeePassXC::Settings

- Sandbox (linux): offline-editor
- Sandbox folders (linux): +~/Documents/Passwords
- Sandbox network (linux): no

# Zettlr

## Zettlr::Settings

- Sandbox (linux): offline-editor
- Sandbox folders (linux): ~/Documents, ~/Zettlr, ~/Pictures
- Sandbox network (linux): yes

# TurboShield VPN

Closed-source servers and an analytics SDK in the client. Not something I'd recommend.
"""

DESK = TABLE + "".join([
    row("LocalSend", "localsend/localsend", "foss, donation", 4, 4),
    row("KeePassXC", "keepassxreboot/keepassxc", "foss, offline", 5, 4),
    row("Syncthing", "syncthing/syncthing", "foss, donation", 5, 5),
    row("OBS Studio", "obsproject/obs-studio", "foss, donation", 4, 5),
    row("Joplin", "laurent22/joplin", "foss, donation", 4, 5),
    row("Signal Desktop", "signalapp/Signal-Desktop", "foss, saas", 5, 4),
    row("Upscayl", "upscayl/upscayl", "foss, donation", 5, 5),
    row("Ventoy", "ventoy/Ventoy", "foss", 4, 4),
    row("Proton VPN", "ProtonVPN/proton-vpn-gtk-app", "foss, freemium", 4, 4),
    row("TurboShield VPN", "https://git.example.org/turboshield/vpn-desktop", "spyware, ads, saas", 0, 1),
    row("XZ Utils", "tukaani-project/xz", "foss, offline", 4, 4),
]) + """
# XZ Utils

General-purpose compression; most Linux systems depend on it.

## XZ Utils::Settings

- Trust: 4
- Rating: 4
- Tags: foss, offline

## XZ Utils[5.6.0]

The 5.6.0 and 5.6.1 release tarballs were backdoored (CVE-2024-3094). Avoid them.

### XZ Utils[5.6.0]::Settings

- Trust: 0
- Tags: foss, malware, knownvuln

## XZ Utils[5.6.2]

Cleaned up by the remaining maintainer; the backdoor is gone.

### XZ Utils[5.6.2]::Details

- Date: 2024-05-29
- Platform: linux x86_64
- Channel: GitHub release
- File: xz-5.6.2.tar.gz

### XZ Utils[5.6.2]::Settings

- Trust: 4
- Tags: foss, offline

# TurboShield VPN

Phones home with device IDs and browsing statistics even when disconnected, and injects ads into
pages. Avoid.
"""

KENJI = TABLE + "".join([
    row("AppKata", APPKATA_REPO, "foss, signed", 5, 4),
    row("LocalSend", "localsend/localsend", "foss", 5, 5),
    row("KeePassXC", "keepassxreboot/keepassxc", "foss", 5, 5),
    row("Syncthing", "syncthing/syncthing", "foss", 5, 5),
    row("Zettlr", "Zettlr/Zettlr", "foss", 4, 3),
]) + """
# Syncthing

Upgrades itself in place, so I let it: AppKata installs it and shows new releases.

## Syncthing::Settings

- App menu: yes
- Command link: yes
- Auto update: yes

# Zettlr

## Zettlr::Settings

- Auto update (linux): no
- Auto update (windows): no
- Auto update (macos): yes
"""

MINE = TABLE + row("LocalSend", "localsend/localsend", "foss, donation, offline", 4, 5) + \
    row("Zettlr", "Zettlr/Zettlr", "foss, offline", 4, 4) + """
# LocalSend

Works great across Linux, Windows and my phone. No account, no cloud:
transfers stay on the LAN and are encrypted with TLS.

- Releases are built in CI from tagged commits; checksums are published.
- **Watch out:** the firewall prompt on Windows is easy to dismiss.

Donations via Open Collective.

# Zettlr

Good Markdown editor for long texts; citations work with Zotero.

## Zettlr::Settings

- App menu: yes
- Auto update (linux): no
- Auto update (windows): no
- Auto update (macos): yes
"""

PEOPLE = {   # name, email, Ed25519 seed (made-up reviewers)
    "jo": ("Jonas Okafor", "jonas@desk.coop", b"jo" * 16), "rp": ("Rita Prado", "rita@desk.coop", b"rp" * 16),
    "tk": ("Tomasz Kral", "tk@desk.coop", b"tk" * 16), "ab": ("Ade Bello", "ade@desk.coop", b"ab" * 16),
    "ln": ("Lea Novak", "lea@desk.coop", b"ln" * 16), "sv": ("Sam Vega", "sam@desk.coop", b"sv" * 16),
    "na": ("Nadia Haddad", "nadia@desk.coop", b"na" * 16),
    "kj": ("Kenji Mori", "kenji@mori.dev", b"kj" * 16), "ay": ("Aya Mori", "aya@mori.dev", b"ay" * 16),
}


def git(repo, *args):
    subprocess.run(["git", "-C", repo, *args], check=True, capture_output=True)


def write(repo, text, path="AppKata.md"):
    os.makedirs(os.path.dirname(os.path.join(repo, path)), exist_ok=True)
    with open(os.path.join(repo, path), "w") as f:
        f.write(text)
    git(repo, "add", "-A")


def ssh_commit(repo, who, msg, date):
    name, email, seed = PEOPLE[who]
    return devtools.commit(repo, msg, author=name, email=email, ssh_seed=seed, date=date)


def build(d: str) -> None:
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d)
    repos = os.path.join(d, "repos")
    db = DB(os.path.join(d, "appkata.db"))
    http = Http()

    # your own AppKata.md, in a repo with an origin (requirement 8.3)
    mine = os.path.join(d, "home", "src", "reviews")
    bare = os.path.join(repos, "reviews-origin.git")
    subprocess.run(["git", "init", "-q", "--bare", bare], check=True)
    subprocess.run(["git", "init", "-q", "-b", "main", mine], check=True)
    git(mine, "remote", "add", "origin", "https://github.com/dgriffin/reviews.git")
    git(mine, "config", "commit.gpgsign", "true")
    git(mine, "config", "gpg.format", "ssh")
    git(mine, "config", "user.signingkey", "~/.ssh/id_ed25519.pub")
    write(mine, MINE)
    devtools.commit(mine, "My reviews", author="You", email="you@example.com")
    path = os.path.join(mine, "AppKata.md")
    with open(os.path.join(d, "gui.json"), "w") as f:
        json.dump({"reviewPath": path, "autoCommit": True, "autoPush": True, "theme": "dark", "minAgeDefault": 20}, f)
    sync.sync_own(db, sync.own_trust(db, path))

    # Mara's FOSS picks: OpenPGP, key published in .appkata/keys/ (requirement 10.7)
    mara = os.path.join(repos, "foss-picks")
    subprocess.run(["git", "init", "-q", "-b", "main", mara], check=True)
    home = os.path.join(d, "gnupg-mara")
    fpr, pub = devtools.gpg_keygen(home, "Mara Lindqvist <mara@lindqvist.se>")
    write(mara, "# Mara's FOSS picks\n\nApps I use and trust.\n\n" + MARA)
    write(mara, pub, ".appkata/keys/mara.asc")
    devtools.commit(mara, "Picks", author="Mara Lindqvist", email="mara@lindqvist.se", gpg_key=fpr, gnupghome=home,
                    date="2026-03-12T10:00:00Z")
    p = sync.preview_trust(http, mara)
    assert not p.error, p.error
    sync.add_trust(db, p)

    # The desk collective: six SSH-signing members, one of them disabled, and a new signer (10.8)
    desk = os.path.join(repos, "desk-reviews")
    subprocess.run(["git", "init", "-q", "-b", "main", desk], check=True)
    write(desk, "# Desk Collective reviews\n\nReviewed by the Desk Collective members.\n\n" + DESK.replace("| 5 | 4 |\n| OBS", "| 4 | 4 |\n| OBS"), "docs/AppKata.md")
    ssh_commit(desk, "jo", "First reviews", "2025-03-12T09:00:00Z")
    p = sync.preview_trust(http, desk)
    assert not p.error, p.error
    tid = sync.add_trust(db, p)
    for k in ("rp", "tk", "ab", "ln", "sv"):          # earlier-approved members
        name, email, seed = PEOPLE[k]
        from appkata_core import sshsig
        blob = sshsig.ed25519_pub_blob(seed)
        db.x("""INSERT INTO authorities(trust_id, kind, fingerprint, key, name, email, first_commit, first_at, last_commit, last_at)
                VALUES(?,?,?,?,?,?,?,?,?,?)""", (tid, "ssh", sshsig.fingerprint(blob), sshsig.key_line(blob), name, email,
                                                 p.commit, "2025-03-12T09:00:00Z", p.commit, "2025-03-12T09:00:00Z"))
    write(desk, "# Desk Collective reviews\n\nReviewed by the Desk Collective members.\n\n" + DESK, "docs/AppKata.md")
    ssh_commit(desk, "rp", "KeePassXC", "2026-09-29T14:00:00Z")
    sync.sync_trust(db, http, tid)
    db.x("UPDATE authorities SET enabled=0 WHERE trust_id=? AND email='ade@desk.coop'", (tid,))
    for i, app in enumerate(("Zettlr", "Kdenlive", "Upscayl")):
        write(desk, open(os.path.join(desk, "docs/AppKata.md")).read() + f"\n<!-- {app} reviewed by Nadia -->\n", "docs/AppKata.md")
        ssh_commit(desk, "na", f"Note on {app}", f"2026-09-30T1{i}:00:00Z")
    sync.sync_trust(db, http, tid)

    # Kenji's app reviews: SSH, two authorities
    kenji = os.path.join(repos, "app-reviews")
    subprocess.run(["git", "init", "-q", "-b", "main", kenji], check=True)
    write(kenji, "# Kenji's app reviews\n\n" + KENJI)
    ssh_commit(kenji, "kj", "Reviews", "2025-06-01T08:00:00Z")
    p = sync.preview_trust(http, kenji)
    tid = sync.add_trust(db, p)
    name, email, seed = PEOPLE["ay"]
    from appkata_core import sshsig
    blob = sshsig.ed25519_pub_blob(seed)
    db.x("INSERT INTO authorities(trust_id, kind, fingerprint, key, name, email, first_commit, first_at) VALUES(?,?,?,?,?,?,?,?)",
         (tid, "ssh", sshsig.fingerprint(blob), sshsig.key_line(blob), name, email, p.commit, "2025-06-01T08:00:00Z"))

    # Scores (requirement 10.6.2): Kenji's reviews weigh most, the collective's least
    for name, score in (("Mara's FOSS picks", 4), ("Desk Collective reviews", 3), ("Kenji's app reviews", 5)):
        db.x("UPDATE trusts SET score=? WHERE name=?", (score, name))
    db.put("tokens", {"git.example.net": "demo-token-not-real-9F2a"})     # a made-up host and token, for Settings
    for s in SOURCES:
        db.x("INSERT OR IGNORE INTO sources(url, input_url, added_at, settings) VALUES(?,?,?,?)",
             (GH + s, GH + s, now(), json.dumps(SOURCE_SETTINGS.get(s, {}))))

    # OBS installed outside AppKata (requirement 4.5): a launcher entry like a distro package's
    apps = os.path.join(d, "xdg", "applications")
    os.makedirs(apps)
    with open(os.path.join(apps, "com.obsproject.Studio.desktop"), "w") as f:
        f.write("[Desktop Entry]\nType=Application\nName=OBS Studio\nExec=obs\nIcon=com.obsproject.Studio\n")
    print("built", d)


# the sync errors the demo shows on purpose; any other one is a sync that failed, whose message would
# show in the screenshots ("github.com answered HTTP 504" did, from 2026-10-09 on)
SHOWN_ERRORS = {"https://git.example.org/turboshield/vpn-desktop": "Unsupported"}


def _failed(db: DB) -> list[dict]:
    return [r for r in db.all("SELECT url, error, error_code FROM apps WHERE error IS NOT NULL AND error != ''")
            if SHOWN_ERRORS.get(r["url"]) != r["error_code"]]


def _http() -> Http:
    return Http({"github.com": os.environ["GITHUB_TOKEN"]} if os.environ.get("GITHUB_TOKEN") else {})


def do_sync(d: str) -> None:
    db = DB(os.path.join(d, "appkata.db"))
    http = _http()
    sync.sync_all(db, http, workers=4)
    print("synced", len(db.all("SELECT url FROM apps WHERE error IS NULL")), "apps;", http.calls, "requests")
    retry(d)


def retry(d: str, tries: int = 3) -> None:
    import time
    db = DB(os.path.join(d, "appkata.db"))
    http = _http()
    for n in range(tries):
        failed = _failed(db)
        if not failed:
            break
        if n:
            time.sleep(20)
        for r in failed:
            print("  sync again:", r["url"], "-", r["error"])
            sync.sync_app(db, http, r["url"])
    check_sync(d)


def check_sync(d: str) -> None:
    failed = _failed(DB(os.path.join(d, "appkata.db")))
    for r in failed:
        print(f"  {r['url']}: {r['error']} ({r['error_code']})", file=sys.stderr)
    if failed:
        sys.exit(f"{len(failed)} apps' last sync failed: scripts/demo_data.py retry {d}")


class Seen:
    """What the app shows of the demo data on one platform, now: the Catalog's rows by app name."""

    def __init__(self, d: str, db: DB, os_name: str):
        from appkata_core import catalog
        self.d, self.db, self.os = d, db, os_name
        self.apps = {a["name"]: a for a in catalog.build(db, os_name)}

    def __getitem__(self, name: str) -> dict:
        return self.apps[name]

    def installed(self) -> list[dict]:
        return [a for a in self.apps.values() if a["installed"]]

    def kept(self, name: str) -> list[str]:
        from appkata_core import install
        return install.kept_versions(self.db, self[name]["url"])

    def source(self, name: str) -> dict:
        r = self.db.one("SELECT settings FROM sources WHERE url=?", (self[name]["url"],))
        return json.loads(r["settings"] or "{}") if r else {}

    def trusted_only_by(self, name: str) -> list[str]:
        a = self[name]
        return [] if a["src"] else [t["name"] for t in a["trusts"]]

    def latest_files(self, name: str) -> list[str]:
        r = self.db.one("SELECT releases FROM apps WHERE url=?", (self[name]["url"],))
        rels = [x for x in json.loads(r["releases"] or "[]") if not x.get("prerelease")] if r else []
        return [x["name"] for x in rels[0]["assets"]] if rels else []

    def sandbox_choice(self, name: str) -> dict | None:
        """The sandbox you chose for the app (Install options or App Detail), as AppKata keeps it."""
        r = self.db.one("SELECT install FROM app_settings WHERE url=?", (self[name]["url"],))
        return json.loads(r["install"] or "{}").get("sandbox") if r and r["install"] else None

    def own_reviews_of_earlier(self, name: str) -> list[str]:
        """The versions older than the installed one that your own review of the app covers."""
        from appkata_core import versions
        return [v for v in self.own_version_reviews(name) if versions.newer(self[name]["installed"], v)]

    def own_version_reviews(self, name: str) -> list[str]:
        r = self.db.one("SELECT settings FROM reviews WHERE trust_id=(SELECT id FROM trusts WHERE own=1) AND app=?", (name,))
        return [v["v"] for v in json.loads(r["settings"] or "{}").get("_versions", [])] if r else []

    def hours_since(self, iso: str) -> float:
        from datetime import datetime, timezone
        return (datetime.now(timezone.utc) - datetime.fromisoformat(iso)).total_seconds() / 3600 if iso else float("inf")


# What the demo data has to show on each tour screen: every claim screenshots/README.md makes about a
# real screen's data, checked before each tour, on each platform whose set takes the screen. A state
# staged once drifts: as time passes (the minimum age that held Zettlr 4.8.0 back ran out on
# 2026-10-08), as a sync brings new releases, and from one platform to the other (Zettlr updates
# itself on Windows only, so the Windows set never had a held update): review 3, R3-24. A screen
# whose data needs no check says why. tests/test_demo_promises.py requires an entry for every tour
# screen. A claim is (text, test) or (text, test, the one platform it's made for).
PROMISES: dict = {
    "every screen": [
        ("the header says it synced minutes ago", lambda s: s.hours_since(s.db.get("last_sync", "")) < 1),
        ("each Trust synced within the day (Sources' Trust panel)",
         lambda s: all(s.hours_since(t["synced_at"]) < 24 for t in s.db.all("SELECT synced_at FROM trusts"))),
    ],
    "A01-apps": [
        ("an app with an update (\"Update available\")", lambda s: any(a["state"] == "update" and not a["self"] for a in s.installed())),
        ("AppKata itself, with an update", lambda s: s["AppKata"]["state"] == "update"),
        ("an update held back by the global minimum age (\"Held · N days left\")",
         lambda s: any(a["state"] == "held" and a["held"].startswith("Held · ") for a in s.installed())),
        ("\"Pinned at …\"", lambda s: any(a["state"] == "pinned" for a in s.installed())),
        ("an app that updates itself, a newer version out (\"N is out · Updates itself\")",
         lambda s: any(a["state"] == "selfupdating" and a["newer"] for a in s.installed())),
        ("Signal Desktop has no update (its GitHub releases carry no files)", lambda s: s["Signal Desktop"]["state"] != "update"),
    ],
    "A02-apps-detail": [
        ("LocalSend, installed, with an update", lambda s: s["LocalSend"]["state"] == "update"),
        ("LocalSend from its Source and the Trusts that list it", lambda s: s["LocalSend"]["src"] and len(s["LocalSend"]["trusts"]) >= 2),
        ("a Trust-only app such as VSCodium, installed (its row names the Trust)",
         lambda s: bool(s.trusted_only_by("VSCodium") and s["VSCodium"]["installed"])),
    ],
    "A03-review-dialog": "LocalSend's review dialog, which the tour fills in",
    "A04-review-avoid-unsigned": "Signal Desktop's review dialog, which the tour fills in and saves",
    "A05-apps-detail-versions": [
        ("Zettlr, installed, with kept versions", lambda s: bool(s["Zettlr"]["installed"] and s.kept("Zettlr"))),
        ("Zettlr's Versions list longer than 6 + 5 (\"Show next 5 older\")", lambda s: s["Zettlr"]["releaseCount"] >= 11),
    ],
    "A06-appkata-restart": "the tour stages AppKata's own update (selfUpdated)",
    "A07-apps-installing": [
        ("Syncthing marked Updates itself", lambda s: s["Syncthing"]["state"] == "selfupdating"),
    ],
    "A08-apps-detail-installing": [
        ("LocalSend has an update (its button shows the download)", lambda s: s["LocalSend"]["state"] == "update"),
    ],
    "A09-app-updates-itself": [
        ("Syncthing updates itself, a newer version out", lambda s: s["Syncthing"]["state"] == "selfupdating" and s["Syncthing"]["newer"]),
        ("\"Kenji's app reviews says it updates itself\"", lambda s: s["Syncthing"]["autoUpdateBy"] == "Kenji's app reviews"),
        # the tour's working system runs an app sandboxed unless it's Off, and AppKata updates a
        # sandboxed app (17.12): so A01's and A07's "Updates itself" rest on this too (R3-27)
        ("Syncthing's sandbox Off, as the Audit says you set it", lambda s: s.sandbox_choice("Syncthing") == {"template": "off"}, "linux"),
    ],
    "A10-confirm-uninstall": [("KeePassXC installed", lambda s: bool(s["KeePassXC"]["installed"]))],
    "A11-confirm-remove-version": [("Zettlr keeps 4.6.0", lambda s: "4.6.0" in s.kept("Zettlr"))],
    "A17-apps-detail-system-updated": "made-up channel facts that finish writes whole (demo-channels.json)",
    "A18-apps-version-avoided": [
        ("a Trust avoids XZ Utils' installed version, 5.6.1", lambda s: s["XZ Utils"]["installed"] == "5.6.1" and s["XZ Utils"]["installedVetoed"]),
        ("\"Update to\" the newest release no Trust avoids (there is one)", lambda s: bool(s["XZ Utils"]["avoidUpdateTo"])),
    ],
    "A19-review-dialog-version": [
        ("LocalSend installed, with no review of yours of that version (\"a new review of it\")",
         lambda s: bool(s["LocalSend"]["installed"]) and s["LocalSend"]["installed"] not in s.own_version_reviews("LocalSend")),
        ("your review of an earlier LocalSend stays in the file", lambda s: bool(s.own_reviews_of_earlier("LocalSend"))),
    ],
    **{n: "the tour pins the sandbox states (sandboxDemo); the Sandbox lines are the demo's own review files"
       for n in ("A20-apps-detail-sandbox", "A21-sandbox-dialog", "A22-update-review-badge", "A23-confirm-uninstall-sandbox",
                 "A24-sandbox-setup-needed", "A25-sandbox-advanced", "C11-install-sandbox", "X15-settings-sandbox")},
    "C01-catalog": [
        ("state marks: Update", lambda s: any(a["state"] == "update" for a in s.apps.values())),
        ("state marks: Installed", lambda s: any(a["state"] == "installed" for a in s.apps.values())),
        ("state marks: Outside AppKata", lambda s: any(a["state"] == "foreign" for a in s.apps.values())),
    ],
    "C02-catalog-detail": [
        ("Upscayl comes only from Trusts, not installed", lambda s: bool(s.trusted_only_by("Upscayl")) and not s["Upscayl"]["installed"]),
        ("Upscayl's hero image", lambda s: bool(s["Upscayl"]["hero"])),
    ],
    "C03-catalog-foreign": [("OBS Studio installed outside AppKata", lambda s: s["OBS Studio"]["state"] == "foreign")],
    "C04-catalog-search-veto": [
        ("TurboShield VPN vetoed", lambda s: s["TurboShield VPN"]["vetoed"]),
        ("TurboShield VPN's forge error", lambda s: bool(s["TurboShield VPN"]["errorCode"])),
    ],
    "C05-catalog-tags": [("KeePassXC has 5 tags", lambda s: len(s["KeePassXC"]["tags"]) == 5)],
    "C06-install-options": [
        ("Upscayl's latest release has an AppImage and an .rpm",
         lambda s: {".AppImage", ".rpm"} <= {os.path.splitext(n)[1] for n in s.latest_files("Upscayl")}, "linux"),
    ],
    "C07-catalog-all-tags": [("Upscayl not installed (the tour installs it)", lambda s: not s["Upscayl"]["installed"])],
    "C10-install-channels": "made-up channel facts that finish writes whole (demo-channels.json)",
    "S01-sources": [
        ("chips: Installed", lambda s: any(a["src"] and a["installed"] for a in s.apps.values())),
        ("chips: Built in (AppKata's own Source)", lambda s: s.source("AppKata").get("builtin") is True),
        ("chips: Pinned", lambda s: any(a["src"] and a["pinned"] for a in s.apps.values())),
        ("chips: Track only", lambda s: any(a["src"] and a["trackOnly"] for a in s.apps.values())),
        ("chips: outside AppKata", lambda s: any(a["src"] and a["state"] == "foreign" for a in s.apps.values())),
        ("an avatar stack with \"+N\" (a Trust with more than four enabled signers)", lambda s: any(r["n"] > 4 for r in s.db.all(
            "SELECT COUNT(*) n FROM authorities WHERE enabled=1 AND pending=0 GROUP BY trust_id"))),
        ("a Trust's warning", lambda s: bool(s.db.one("SELECT 1 FROM authorities WHERE pending=1"))),
    ],
    "S02-trust-detail": [("trust 3 has a pending new signer", lambda s: bool(s.db.one("SELECT 1 FROM authorities WHERE trust_id=3 AND pending=1")))],
    "S03-source-menu": "the ⋯ menu of KeePassXC's Source",
    "S04-add-source": [
        ("Upscayl isn't a Source, and a Trust lists it (\"Already listed by\")", lambda s: bool(s.trusted_only_by("Upscayl"))),
    ],
    "S05-remove-source": [
        ("KeePassXC installed, from its Source, and Trusts list it too",
         lambda s: bool(s["KeePassXC"]["installed"] and s["KeePassXC"]["src"] and s["KeePassXC"]["trusts"])),
    ],
    "S06-source-in-trusts": [("LocalSend \"In 3 trusts\"", lambda s: len(s["LocalSend"]["trusts"]) == 3)],
    "S07-explore": "a live search of GitHub",
    "S08-source-settings": "LocalSend's Source settings, which the tour fills in",
    "S09-source-highlight": [("Syncthing is a Source", lambda s: s["Syncthing"]["src"])],
    "S10-confirm-remove-trust": [
        ("an installed app with no origin but trust 2", lambda s: any(
            a["installed"] and not a["src"] and [t["name"] for t in a["trusts"]] == [s.db.one("SELECT name FROM trusts WHERE id=2")["name"]]
            for a in s.apps.values())),
    ],
    "S11-confirm-remove-authority": "the tour names the authority (Ade Bello)",
    "S12-confirm-trust-signer": "the tour names the signer (S02 checks the pending one)",
    "S13-confirm-ignore-signer": "the tour names the signer (S02 checks the pending one)",
    "S17-explore-flathub": "made-up Flathub results that finish writes whole (demo-channels.json)",
    "U01-audit": [
        ("entries by You and by Sync", lambda s: {r["actor"] for r in s.db.all("SELECT DISTINCT actor FROM audit")} >= {"you", "sync"}),
        # the Audit lists by id, as entries happen; the demo writes them all at once (R3-25)
        ("entries by day, newest first (each entry's time follows the one written before it)",
         lambda s: (lambda ts: ts == sorted(ts))([r["at"] for r in s.db.all("SELECT at FROM audit ORDER BY id")])),
        ("nothing after now", lambda s: s.hours_since(s.db.one("SELECT MAX(at) t FROM audit")["t"]) > 0),
        ("no entry twice", lambda s: not s.db.one("SELECT 1 FROM audit GROUP BY actor, kind, action, subject HAVING COUNT(*) > 1")),
        ("its newest entry from the last hours, as of the tour", lambda s: s.hours_since(s.db.one("SELECT MAX(at) t FROM audit")["t"]) < 2),
    ],
    "U02-audit-sandbox": [         # the Apps filter (R3-28)
        ("app entries, sandbox changes among them",
         lambda s: bool(s.db.one("SELECT 1 FROM audit WHERE kind='app' AND action='set the sandbox of'")), "linux"),
        ("a sandbox turned off", lambda s: any(json.loads(r["detail"] or "{}").get("level") == "off" for r in s.db.all(
            "SELECT detail FROM audit WHERE kind='app' AND action='set the sandbox of'")), "linux"),
        ("a launcher rewritten by the system", lambda s: bool(s.db.one("SELECT 1 FROM audit WHERE kind='app' AND actor='system'")), "linux"),
    ],
    "X01-app-menu": "the ⋮ menu (its \"Last synced\" is the header's, under every screen)",
    "X03-settings": [
        ("a global Minimum age", lambda s: int(s.db.get("min_age_default", 0) or 0) > 0),
        ("the Minimum age Settings shows is the one the Apps view applies",     # kept in both (backend.setPref)
         lambda s: json.load(open(os.path.join(s.d, "gui.json"))).get("minAgeDefault") == s.db.get("min_age_default")),
    ],
    "X04-settings-portable": "Settings, which show the defaults",
    "X05-settings-data": "Settings, which show the defaults",
    "X06-about": "the About dialog",
    "X07-confirm-remove-token": "the tour names the token's host",
    "X08-confirm-remove-relay": "the tour names the relay",
    "X09-confirm-quit": "the tour stages the installs (busy)",
    "X14-install-appkata": "the tour stages the downloaded AppImage (selfInstall)",
    "X16-first-start": "an empty database, not the demo data (scripts/test-layout.sh's second pass; tour.FRESH)",
}
# Claims the demo data doesn't keep yet, each with its finding: listed, they're reported, not failed.
# One that starts holding fails the check, so the list shrinks as fixes land.
STILL_WRONG: dict = {}


def check_promises(d: str) -> list[str]:
    """The claims in PROMISES the data at d doesn't keep, as "screen (platform): claim"."""
    db = DB(os.path.join(d, "appkata.db"))
    os.environ.setdefault("XDG_DATA_HOME", os.path.join(d, "xdg"))
    out = []
    for os_name in ("linux", "windows"):      # Linux-only screens' claims say so (tests/test_demo_promises.py)
        seen = Seen(d, db, os_name)
        for screen, claims in PROMISES.items():
            if isinstance(claims, str):
                continue
            for text, test, *only in claims:
                if only and only[0] != os_name:
                    continue
                try:
                    ok = bool(test(seen))
                except (KeyError, TypeError, ValueError) as e:
                    ok, text = False, f"{text} [{type(e).__name__}: {e}]"
                if not ok:
                    out.append(f"{screen} ({os_name}): {text}")
    return out


def check(d: str) -> None:
    """Before a tour: no failed sync, and every claim the screenshots make of the data holds."""
    check_sync(d)
    wrong = check_promises(d)
    new = [w for w in wrong if w not in STILL_WRONG]
    for w in wrong:
        print(f"  {'' if w in new else STILL_WRONG[w] + ', still: '}{w}", file=sys.stderr)
    fixed = [w for w in STILL_WRONG if w not in wrong]
    for w in fixed:
        print(f"  holds now, take it off STILL_WRONG: {w}", file=sys.stderr)
    if new or fixed:
        sys.exit(f"{len(new)} claims of screenshots/README.md the demo data in {d} doesn't keep, "
                 f"{len(fixed)} listed ones that hold now")


def carry_over(was: DB, db: DB) -> list[str]:
    """The synced Catalog of was (apps, app_meta) into db, for the apps db's Sources and Trusts list
    (sync.catalog_urls) and no others: an app the build no longer lists stays behind. Returns the
    listed apps was has no synced row for."""
    listed = sync.catalog_urls(db)
    keep = set(listed)
    for table in ("apps", "app_meta"):
        for r in was.all(f"SELECT * FROM {table}"):
            if r["url"] in keep:
                cols = list(r.keys())
                db.x(f"INSERT OR REPLACE INTO {table}({', '.join(cols)}) VALUES({', '.join('?' * len(cols))})",
                     tuple(r[c] for c in cols))
    synced = {r["url"] for r in was.all("SELECT url FROM apps")}
    return [u for u in listed if u not in synced]


def remake(d: str) -> None:
    """build and finish again, keeping what sync brought into d: for a change to what build or
    finish writes, without the network or a new set of releases (and the screens they change).
    Only the apps the new build lists come over (carry_over); one it lists that d never synced stops
    it, d as it was."""
    old = d.rstrip("/") + ".old"
    shutil.rmtree(old, ignore_errors=True)
    # gpg 2.2 finds a key folder's agent by the folder's path: the one build started for d would
    # serve d's new key folder from the old one's files, and the key can't be made (exit 2)
    subprocess.run(["gpgconf", "--kill", "gpg-agent"], env={**os.environ, "GNUPGHOME": os.path.join(d, "gnupg-mara")},
                   capture_output=True)
    os.rename(d, old)
    try:
        build(d)
        db, was = DB(os.path.join(d, "appkata.db")), DB(os.path.join(old, "appkata.db"))
        missing = carry_over(was, db)
        if missing:
            raise SystemExit(f"{d.rstrip('/')}.old has no synced data for what the build now lists, which remake can't "
                             f"fetch: {', '.join(missing)}; run scripts/demo_data.py sync {d} instead")
        for r in was.all("SELECT url, forge FROM sources"):
            db.x("UPDATE sources SET forge=? WHERE url=?", (r["forge"], r["url"]))
        if was.get("autoupdate") is not None:
            db.put("autoupdate", was.get("autoupdate"))
        shutil.copytree(os.path.join(old, "cache"), os.path.join(d, "cache"), dirs_exist_ok=True)
        finish(d)
    except BaseException:
        shutil.rmtree(d, ignore_errors=True)
        os.rename(old, d)
        raise
    shutil.rmtree(old)


# The update A01 shows held back by the global minimum age, and the days it has to go (R3-24). The
# releases out up to 8 days before Zettlr 4.8.0 (VSCodium 1.135, XZ Utils 5.8.4, AppKata 0.2.0) are
# A01's updates, so the days left stay under that.
HELD, HELD_DAYS_LEFT = "Zettlr/Zettlr", 4


def stage(d: str) -> None:
    """Before a tour: what the screens show of time, as of now (R3-24). The data is made once and
    toured for weeks, so a minimum age set when it was made runs out, and its last sync ages. The
    minimum age is set so that HELD's newest release has HELD_DAYS_LEFT days to go, in the database
    and in Settings, the last sync and each Trust's are put 50 minutes back, and the Audit is
    written again to end half an hour back (R3-25)."""
    import math
    from datetime import datetime, timedelta, timezone
    db = DB(os.path.join(d, "appkata.db"))
    r = db.one("SELECT releases FROM apps WHERE url=?", (GH + HELD,))
    newest = next(x for x in json.loads(r["releases"] or "[]") if not x.get("prerelease"))
    t = datetime.now(timezone.utc).replace(microsecond=0)
    age = (t - datetime.fromisoformat(newest["date"].replace("Z", "+00:00"))).total_seconds() / 86400
    days = math.floor(age) + HELD_DAYS_LEFT
    db.put("min_age_default", days)
    gui = os.path.join(d, "gui.json")
    prefs = json.load(open(gui))
    prefs["minAgeDefault"] = days
    with open(gui, "w") as f:
        json.dump(prefs, f)
    synced = (t - timedelta(minutes=50)).isoformat()
    db.put("last_sync", synced)
    db.x("UPDATE trusts SET synced_at=?", (synced,))
    history(db)
    print(f"staged {d}: minimum age {days} days ({HELD.split('/')[1]} {newest['version']} held, {HELD_DAYS_LEFT} days left), synced 50 min ago")


def finish(d: str) -> None:
    """Installs and settings from the real release lists, so the Apps view has every state."""
    check_sync(d)
    db = DB(os.path.join(d, "appkata.db"))
    from datetime import datetime, timezone
    def rels(repo):
        r = db.one("SELECT releases FROM apps WHERE url=?", (GH + repo,))
        return [x for x in json.loads(r["releases"] if r and r["releases"] else "[]") if not x.get("prerelease")]
    def inst(repo, which, kind):
        rs = rels(repo)
        if len(rs) <= which:
            print("  skip", repo); return None
        r = rs[which]
        db.x("INSERT OR REPLACE INTO installs(url, name, version, date, asset, kind, record, installed_at) VALUES(?,?,?,?,?,?,?,?)",
             (GH + repo, repo.split("/")[1], r["version"], r["date"], "", kind, "{}", now()))
        return r
    inst("localsend/localsend", 1, "appimage")          # update available
    inst("signalapp/Signal-Desktop", 1, "deb")
    inst("Zettlr/Zettlr", 1, "appimage")
    inst("keepassxreboot/keepassxc", 0, "appimage")     # current
    inst("syncthing/syncthing", 1, "tarball")           # updates itself, a version behind ("N is out")
    inst("VSCodium/vscodium", 1, "rpm")
    # a version the Desk Collective says to avoid (requirement 10.6.5): xz 5.6.1, the backdoored release
    db.x("INSERT OR REPLACE INTO installs(url, name, version, date, asset, kind, record, installed_at) VALUES(?,?,?,?,?,?,?,?)",
         (GH + "tukaani-project/xz", "XZ Utils", "5.6.1", "2024-03-09T08:00:00Z", "xz-5.6.1.tar.gz", "tarball", "{}", now()))
    # per-app sandbox choices (requirement 17): KeePassXC customized off the reviewer's Offline editor;
    # Zettlr kept at the user's grants while a review suggests more access (the review badge, 17.11).
    def set_sandbox(repo, cfg):
        row = db.one("SELECT install FROM app_settings WHERE url=?", (GH + repo,))
        cur = json.loads(row["install"]) if row and row["install"] else {}
        cur["sandbox"] = cfg
        db.x("INSERT INTO app_settings(url, install) VALUES(?,?) ON CONFLICT(url) DO UPDATE SET install=excluded.install",
             (GH + repo, json.dumps(cur)))
    set_sandbox("keepassxreboot/keepassxc", {"custom": {
        "level": "standard", "folders": {"~/Documents/Passwords": "rw", "~/Downloads": "ro"},
        "network": False, "ports": None, "sound": [], "devices": [], "caps": [], "exec_deny": True, "write_app": False}})
    set_sandbox("Zettlr/Zettlr", {"custom": {
        "level": "standard", "folders": {"~/Documents": "rw", "~/Zettlr": "rw"},
        "network": False, "ports": None, "sound": [], "devices": [], "caps": [], "exec_deny": True, "write_app": False}})
    # Syncthing Off, as the Audit says you set it (history): so it updates itself (A01, A07, A09). The
    # tour's working system runs every other app sandboxed, and a sandboxed app is updated by AppKata
    # (17.12; review 3, R3-27)
    set_sandbox("syncthing/syncthing", {"template": "off"})
    version_review(db, d)
    v = inst("ventoy/Ventoy", 2, "tarball")             # pinned at an older version
    if v:
        db.x("INSERT OR REPLACE INTO app_settings(url, pinned) VALUES(?,?)", (GH + "ventoy/Ventoy", v["version"]))
    os.environ["XDG_DATA_HOME"] = os.path.join(d, "xdg")
    from appkata_core import foreign
    foreign.scan(db)
    portable_records(db, d)
    self_app(db, d)
    demo_channels(d)
    stage(d)                                            # the minimum age, the sync times and the Audit, set again before each tour
    print("finished", d)


def version_review(db: DB, d: str) -> None:
    """Your review of an older LocalSend release (requirement 10.3.2), so the review dialog offers a
    new review of the installed version (8.4.1.1)."""
    from appkata_core import review, trustfile
    rs = [x for x in json.loads((db.one("SELECT releases FROM apps WHERE url=?", (GH + "localsend/localsend",)) or {"releases": "[]"})["releases"] or "[]")
          if not x.get("prerelease")]
    if len(rs) < 3:
        return
    path = json.load(open(os.path.join(d, "gui.json")))["reviewPath"]
    old = rs[2]
    text = trustfile.set_review(review.read(path), "LocalSend", GH + "localsend/localsend", ["foss", "donation", "offline"], 4, 5,
                                "Fast on my home network; the Windows firewall prompt is still easy to miss.", None, old["version"],
                                [["Date", old["date"][:10]], ["Platform", "linux x86_64"], ["Channel", "GitHub release"],
                                 ["File", f"LocalSend-{old['version']}-linux-x86-64.AppImage"]],
                                {x["version"]: x["date"] for x in rs})
    with open(path, "w") as f:
        f.write(text)
    sync.sync_own(db, sync.own_trust(db, path))


def demo_channels(d: str) -> None:
    """DEV ONLY: package-channel facts for the tour's channel screens (requirement 16), read by the app
    when the tour asks (backend.demoChannels) or with APPKATA_DEMO_CHANNELS=1. This computer may have no
    flatpak, apt or AppStream catalog, so these stand in for an Ubuntu 24.04 desktop with Flathub.
    The Ubuntu package versions and the Flathub search results are sample data."""
    mara = "Mara's FOSS picks"
    facts = {
        "os": "Ubuntu 24.04 (x86_64)", "manager": "apt", "distro": "Ubuntu", "catalog": True,
        # GNOME Software updates Flatpaks; unattended-upgrades installs security updates only (16.5.2)
        "autoupdate": {"flatpak": ["GNOME Software"], "packages": [], "aptOrigins": ["o=Ubuntu,a=noble-security"],
                       "aptUnattended": True},
        "links": {
            GH + "localsend/localsend": {
                "flatpak": {"value": "org.localsend.localsend_app", "source": "trust", "via": mara},
                "package": {"value": "localsend", "manager": "apt", "source": "appstream", "via": "localsend_app.desktop"},
                "channel": ["flatpak", mara]},
            GH + "keepassxreboot/keepassxc": {
                "flatpak": {"value": "org.keepassxc.KeePassXC", "source": "appstream", "via": "org.keepassxc.KeePassXC"},
                "package": {"value": "keepassxc", "manager": "apt", "source": "appstream", "via": "org.keepassxc.KeePassXC.desktop"}},
        },
        "checks": {
            GH + "localsend/localsend": {"flatpak": {"state": "matches", "verified": 1, "built_from": "v1.18.2"},
                                         "package": {"state": "matches", "detail": "AppStream"}},
            GH + "keepassxreboot/keepassxc": {"flatpak": {"state": "matches", "verified": 1},
                                              "package": {"state": "matches"}},
        },
        "facts": {
            GH + "localsend/localsend": {"flatpak": {"version": "1.18.2", "sizeText": "48 MB"},
                                         "package": {"version": "1.14.0-1", "origin": "universe", "size": 41_000_000}},
        },
        # in the tour, LocalSend from Flathub (updated by GNOME Software) and KeePassXC from Ubuntu
        # (security updates only, so nothing updates it)
        "installs": {
            GH + "localsend/localsend": {"release": 0, "record": {
                "channel": "flatpak", "flatpak": "org.localsend.localsend_app", "remote": "flathub", "installation": "user",
                "verified": "signed", "signer": "Flathub", "perms": ["Network", "Downloads folder", "Display (Wayland)"],
                "pending": {"addedPerms": ["Home folder"]}, "updatedBy": "GNOME Software", "updatedAt": "2026-10-03"}},
            GH + "keepassxreboot/keepassxc": {"version": "2.7.6", "tip": True, "record": {
                "channel": "package", "package": "keepassxc", "manager": "apt", "verified": "signed", "signer": "Ubuntu",
                "origin": "universe", "pkgVersion": "2.7.6+dfsg.1-1build1"}},
        },
        "explore": {"flathub": {"matches": [
            {"name": "Joplin", "link": "net.cozic.joplin_desktop", "description": "A note taking and to-do application with synchronisation",
             "url": GH + "laurent22/joplin", "page": GH + "laurent22/joplin", "verified": True, "found": "AppStream",
             "channel": "flatpak", "service": "flathub", "addable": True},
            {"name": "Xournal++", "link": "com.github.xournalpp.xournalpp", "description": "Take handwritten notes",
             "url": GH + "xournalpp/xournalpp", "page": GH + "xournalpp/xournalpp", "verified": True, "found": "AppStream",
             "channel": "flatpak", "service": "flathub", "addable": True},
            {"name": "Pocket Notes", "link": "io.example.PocketNotes", "description": "Quick notes in your panel (sample data)",
             "url": "", "page": "https://flathub.org/apps/io.example.PocketNotes", "verified": False,
             "channel": "flatpak", "service": "flathub", "addable": False},
            {"name": "Zettlr", "link": "com.zettlr.Zettlr", "description": "A markdown editor for the 21st century",
             "url": GH + "Zettlr/Zettlr", "page": GH + "Zettlr/Zettlr", "verified": True, "found": "AppStream",
             "channel": "flatpak", "service": "flathub", "addable": True},
        ]}},
    }
    with open(os.path.join(d, "demo-channels.json"), "w") as f:
        json.dump(facts, f, indent=1)


def portable_records(db: DB, d: str) -> None:
    """Real files for the AppImage installs: the current version and kept older ones (req 4.3.1.5)."""
    for r in db.all("SELECT url, name, version, kind FROM installs WHERE kind='appimage'"):
        slug = r["name"].lower().replace(" ", "-")
        target = os.path.join(d, "apps", slug)
        os.makedirs(target, exist_ok=True)
        rels = [x for x in json.loads((db.one("SELECT releases FROM apps WHERE url=?", (r["url"],)) or {"releases": "[]"})["releases"] or "[]")
                if not x.get("prerelease")]
        vers = [x["version"] for x in rels]
        i = vers.index(r["version"]) if r["version"] in vers else 0
        def place(v):
            p = os.path.join(target, f"{r['name'].replace(' ', '')}-{v}-x86_64.AppImage")
            open(p, "w").write("demo"); os.chmod(p, 0o755)
            return {"version": v, "path": p, "exec": os.path.basename(p)}
        cur = place(r["version"])
        kept = [place(v) for v in vers[i + 1:i + 3]]
        rec = {"files": [target], "links": [], "root": os.path.join(d, "apps"), "target": target, "current": cur, "kept": kept,
               "exec": cur["path"], "verified": "checksum", "options": {"appMenu": True, "commandLink": True, "stableName": True}}
        db.x("UPDATE installs SET record=? WHERE url=?", (json.dumps(rec), r["url"]))


def self_app(db: DB, d: str) -> None:
    """AppKata itself (requirement 2.11): its repository isn't published yet, so its metadata and
    two releases are made up here; the running AppImage is adopted at the current version."""
    from appkata_core import __version__
    cache = os.path.join(d, "cache", "appkata"); os.makedirs(cache, exist_ok=True)
    shutil.copy(os.path.join(HERE, "..", "src", "appkata", "qml", "assets", "appkata.svg"), os.path.join(cache, "icon.svg"))
    files = lambda v: [{"name": f"AppKata-{v}-x86_64.AppImage", "url": f"{APPKATA_REPO}/releases/download/v{v}/AppKata-{v}-x86_64.AppImage",
                        "size": 112000000, "digest": "sha256:" + "ab" * 32, "content_type": ""},
                       {"name": f"AppKata-{v}-macos-unsigned.tar.gz", "url": "x", "size": 1, "digest": "", "content_type": ""}]
    rels = [{"tag": "v0.2.0", "name": "AppKata 0.2.0", "version": "0.2.0", "date": "2026-09-10T18:00:00Z", "prerelease": False,
             "notes": "- Trust Scores weight each Trust's reviews\n- Keeps older versions for a quick rollback\n- Settings: data locations, import and export",
             "assets": files("0.2.0")},
            {"tag": "v0.1.0", "name": "AppKata 0.1.0", "version": __version__, "date": "2026-09-01T12:00:00Z", "prerelease": False,
             "notes": "First release.", "assets": files(__version__)}]
    readme = ("AppKata is a FOSS app store built on git. Apps come from your Sources and from Trusts. "
              "It installs and updates apps from the projects' own releases.")
    db.x("""INSERT OR REPLACE INTO apps(url, name, description, summary, readme, raw_base, icon, hero, forge, host, repo, releases,
            archived, fetched_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,0,?)""",
         (APPKATA_REPO, "AppKata", "A FOSS app store built on git", readme, readme, "", "cache/appkata/icon.svg", "", "github",
          "github.com", APPKATA_REPO.split("github.com/", 1)[1], json.dumps(rels), now()))
    if not db.one("SELECT 1 FROM sources WHERE url=?", (APPKATA_REPO,)):
        db.x("INSERT INTO sources(url, input_url, settings, added_at) VALUES(?,?,?,?)", (APPKATA_REPO, APPKATA_REPO, '{"builtin": true}', now()))
    target = os.path.join(d, "apps", "appkata"); os.makedirs(target, exist_ok=True)
    image = os.path.join(d, "Downloads", f"AppKata-{__version__}-x86_64.AppImage"); os.makedirs(os.path.dirname(image), exist_ok=True)
    open(image, "w").write("demo"); os.chmod(image, 0o755)
    rec = {"files": [], "links": [], "root": os.path.join(d, "apps"), "target": target, "kept": [], "exec": image, "verified": "adopted",
           "current": {"version": __version__, "path": image, "exec": image, "external": True},
           "options": {"appMenu": True, "commandLink": True, "stableName": True}}
    db.x("INSERT OR REPLACE INTO installs(url, name, version, date, asset, kind, record, installed_at) VALUES(?,?,?,?,?,?,?,?)",
         (APPKATA_REPO, "AppKata", __version__, rels[1]["date"], os.path.basename(image), "appimage", json.dumps(rec), now()))


def history(db: DB) -> None:
    """The demo's Audit (requirement 13), as if the last two weeks had happened up to now: stage
    writes it again before each tour, so U01 ends on the tour's day (review 3, R3-25). The Audit
    lists by id, as entries happen, so its rows go in by time; and build's own entries go, which
    history tells again ("found a new signer" was there twice). The Audit is append-only: its
    triggers are dropped while it's written, in the demo data only, and put back as they were."""
    from datetime import datetime, timedelta, timezone
    # Each row is (days back, hour, minute) as if the tour ran at 13:00, so the newest, at 12:30, is
    # half an hour back: a tour earlier in the day moves the whole history earlier, never past now
    t0 = datetime.now(timezone.utc).replace(microsecond=0)
    def at(days, h, m):
        return (t0 - timedelta(days=days, hours=13) + timedelta(hours=h, minutes=m)).replace(second=17).isoformat()
    ins = db.all("SELECT url, name, version FROM installs")
    v = {r["url"].rsplit("/", 1)[-1].lower(): r["version"] for r in ins}
    rows = [
        (at(14, 9, 2), "you", "setting", "chose the review file", "~/src/reviews/AppKata.md", "", ""),
        (at(14, 9, 5), "you", "trust", "added", "Mara's FOSS picks", "github.com/mara-dev/foss-picks", '{"file": "AppKata.md", "commit": "8129f1f", "apps": 12}'),
        (at(14, 9, 5), "you", "authority", "added", "Mara Lindqvist", "", '{"trust": "Mara\'s FOSS picks", "type": "gpg"}'),
        (at(14, 9, 11), "you", "trust", "added", "Desk Collective reviews", "codeberg.org/desk-collective/reviews", '{"file": "docs/AppKata.md", "apps": 11}'),
        (at(13, 18, 40), "you", "source", "added", "keepassxreboot/keepassxc", GH + "keepassxreboot/keepassxc", ""),
        (at(13, 18, 41), "you", "app", "installed", "KeePassXC", GH + "keepassxreboot/keepassxc", json.dumps({"version": v.get("keepassxc", ""), "file": "KeePassXC-x86_64.AppImage"})),
        (at(12, 8, 15), "you", "source", "added", "syncthing/syncthing", GH + "syncthing/syncthing", ""),
        (at(12, 8, 16), "you", "app", "installed", "Syncthing", GH + "syncthing/syncthing", json.dumps({"version": v.get("syncthing", "")})),
        (at(10, 21, 3), "you", "app", "installed", "Zettlr", GH + "Zettlr/Zettlr", json.dumps({"version": v.get("zettlr", "")})),
        (at(9, 12, 30), "you", "app", "pinned", "Ventoy", GH + "ventoy/Ventoy", json.dumps({"version": v.get("ventoy", "")})),
        (at(8, 7, 0), "sync", "trust", "applied signed changes from", "Desk Collective reviews", "", '{"commit": "fa7237e", "apps": 11}'),
        (at(6, 14, 22), "you", "authority", "disabled", "Ade Bello", "", '{"trust": "Desk Collective reviews"}'),
        (at(5, 10, 9), "you", "app", "set the minimum age for", "VSCodium", GH + "VSCodium/vscodium", '{"days": 30}'),
        (at(3, 19, 45), "you", "review", "reviewed", "LocalSend", GH + "localsend/localsend", '{"trust": 4, "rating": 5, "commit": "c41e7d3", "signed": true, "pushed": true}'),
        (at(1, 7, 0), "sync", "authority", "found a new signer,", "nadia@desk.coop", "", '{"trust": "Desk Collective reviews", "changes": 3}'),
        (at(1, 7, 0), "sync", "trust", "refused a change to", "Desk Collective reviews", "", '{"reason": "unknown-signer"}'),
        (at(0, 9, 12), "you", "source", "added", "laurent22/joplin", GH + "laurent22/joplin", '{"track only": true}'),
        (at(0, 9, 30), "you", "app", "uninstalled", "Flameshot", GH + "flameshot-org/flameshot", '{"version": "13.1.0"}'),
        # sandbox changes (requirement 17.16)
        (at(2, 12, 30), "you", "setting", "enabled system sandbox support", "AppArmor", "", '{"profile": "/etc/apparmor.d/appkata-sandbox"}'),
        # in the shape the product writes them (review 2, F11): what was added and removed, the launcher's hash
        (at(1, 21, 3), "you", "app", "set the sandbox of", "KeePassXC", GH + "keepassxreboot/keepassxc", json.dumps(
            {"template": "Standard · customized", "level": "standard", "added": "~/Documents/Passwords (read-write)",
             "launcher": "6f1c0e2a9b7d4e31", "written for": "Standard, without the network and notifications, with ~/Documents/Passwords (read-write)"},
            ensure_ascii=False)),
        (at(0, 7, 0), "system", "app", "rewrote the launcher of", "LocalSend", GH + "localsend/localsend", json.dumps(
            {"by": "AppKata 0.2.0", "launcher": "0d8e5a1c7f2b9346", "written for": "Online app"})),
        (at(0, 10, 12), "you", "app", "set the sandbox of", "Zettlr", GH + "Zettlr/Zettlr", json.dumps(
            {"template": "Offline editor · customized", "level": "standard", "added": "~/Zettlr (read-write)",
             "launcher": "b41d93e07c2a5f68", "written for": "Offline editor, with ~/Zettlr (read-write)"}, ensure_ascii=False)),
        (at(0, 12, 30), "you", "app", "set the sandbox of", "Syncthing", GH + "syncthing/syncthing", json.dumps(
            {"template": "Off", "level": "off", "removed": "the network, X11 apps"})),
    ]
    triggers = db.all("SELECT name, sql FROM sqlite_master WHERE type='trigger' AND tbl_name='audit'")
    for t in triggers:
        db.x(f"DROP TRIGGER {t['name']}")
    try:
        db.x("DELETE FROM audit")
        for r in sorted(rows, key=lambda r: r[0]):            # stable: rows of one minute keep their order
            db.x("INSERT INTO audit(at, actor, kind, action, subject, url, detail) VALUES(?,?,?,?,?,?,?)", r)
    finally:
        for t in triggers:
            db.x(t["sql"])


if __name__ == "__main__":
    cmd, d = sys.argv[1], os.path.abspath(sys.argv[2])
    os.environ["APPKATA_DATA"] = d
    {"build": build, "sync": do_sync, "finish": finish, "remake": remake, "stage": stage, "check": check, "retry": retry}[cmd](d)
