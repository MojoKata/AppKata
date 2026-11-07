#!/usr/bin/env python3
"""Generate docs/AppKata.md from scripts/data/appkata-md-facts.json (gathered from GitHub on
2026-10-02: releases, assets, licenses, funding files, and a scan of each project's source for a
built-in updater). Trust and Rating follow the rubric written into the file; edit before signing.
Apps that update themselves are listed too, with an "Auto update" setting (requirement 4.10)."""

import json
import os
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
F = json.load(open(os.path.join(HERE, "data", "appkata-md-facts.json")))
TODAY = date(2026, 10, 2)

# name, repo, offline, updater evidence ("" = no updater found), license correction, extra note, command link
APPS = [
    ("KeePassXC", "keepassxreboot/keepassxc", True, "Checks for new versions and shows a dialog (`UpdateChecker`); it doesn't download or install.", "GPL-3.0", "", False),
    ("LocalSend", "localsend/localsend", False, "", "", "Needs a local network, not the internet.", False),
    ("Flameshot", "flameshot-org/flameshot", True, "Shows a notification when a new version is out (`updatenotificationwidget`).", "", "Its Linux packages are inside `.zip` files, which AppKata doesn't open yet; Windows and macOS downloads are direct.", False),
    ("Ventoy", "ventoy/Ventoy", True, "", "", "Ships prebuilt binary components inside its release archives.", False),
    ("Shotcut", "mltframework/shotcut", True, "Checks for new versions and links to the download page.", "", "", False),
    ("Audacity", "audacity/audacity", True, "Checks for new versions and opens the website (`UpdateManager`).", "GPL-3.0", "Optional audio.com cloud features need an account.", False),
    ("darktable", "darktable-org/darktable", True, "", "", "", False),
    ("FreeCAD", "FreeCAD/FreeCAD", True, "", "", "", False),
    ("Xournal++", "xournalpp/xournalpp", True, "", "", "", False),
    ("OpenShot", "OpenShot/openshot-qt", True, "", "GPL-3.0", "", False),
    ("VeraCrypt", "veracrypt/VeraCrypt", True, "", "Apache-2.0 / TrueCrypt 3.0", "", False),
    ("LMMS", "LMMS/lmms", True, "", "", "The last stable release is from 2020; development continues in nightly builds.", False),
    ("qView", "jurplel/qView", True, "Checks for new versions and shows a notice (`updatechecker`).", "", "", False),
    ("Czkawka", "qarmin/czkawka", True, "", "", "Linux builds are plain binaries, not AppImages or packages.", False),
    ("Neovim", "neovim/neovim", True, "", "Apache-2.0 / Vim", "", True),
    ("Alacritty", "alacritty/alacritty", True, "", "", "No Linux binaries in its releases (distributions package it).", False),
    ("WezTerm", "wezterm/wezterm", True, "Checks for new versions and links to the release (`update.rs`).", "MIT", "The last tagged release is from February 2024; nightly builds continue.", True),
    ("Helix", "helix-editor/helix", True, "", "", "", True),
    ("Pinta", "PintaProject/Pinta", True, "", "", "", False),
    ("Stellarium", "Stellarium/stellarium", True, "", "", "", False),
    ("espanso", "espanso/espanso", True, "", "", "", False),
    ("qBittorrent", "qbittorrent/qBittorrent", False, "Checks for new versions and opens the download page (`programupdater`).", "", "", False),
    ("LibreSprite", "LibreSprite/LibreSprite", True, "", "", "", False),
    ("Cutter", "rizinorg/cutter", True, "Checks for new versions and shows a message (`UpdateWorker`).", "", "", False),
    ("CopyQ", "hluk/CopyQ", True, "", "", "", False),
    ("DB Browser for SQLite", "sqlitebrowser/sqlitebrowser", True, "", "MPL-2.0 / GPL-3.0", "The last stable release is from October 2024; nightly builds continue.", False),
    ("BleachBit", "bleachbit/bleachbit", True, "Checks for new versions and links to the website; on Windows it can download cleaner definitions (winapp2.ini), not the app.", "", "", False),
    ("Tiled", "mapeditor/tiled", True, "Checks for new versions and shows a link (`newversionchecker`).", "", "", False),
    ("Notepadqq", "notepadqq/notepadqq", True, "", "", "", False),
    ("Gaphor", "gaphor/gaphor", True, "", "Apache-2.0", "", False),
]

# Apps that update themselves somewhere: name, repo, offline, updater evidence, license correction, note, command link,
# and where they update themselves (True = every platform), from a scan of each project's source
AUTO = [
    ("VSCodium", "VSCodium/vscodium", True, "Downloads and installs updates on Windows and macOS (VS Code's update service, pointed at VSCodium's GitHub releases); on Linux it only says a new version is out.", "", "", True, ["macos", "windows"]),
    ("OBS Studio", "obsproject/obs-studio", True, "Updates itself on Windows (its own updater) and macOS (Sparkle).", "", "Linux builds are `.deb` packages for Ubuntu.", False, ["macos", "windows"]),
    ("Joplin", "laurent22/joplin", True, "Updates itself on Windows and macOS (electron-updater, `AutoUpdaterService`); on Linux it offers the download.", "AGPL-3.0", "Syncing notes needs a sync target (Joplin Cloud, Nextcloud, WebDAV, or a folder).", False, ["macos", "windows"]),
    ("Syncthing", "syncthing/syncthing", False, "Upgrades its own program on every platform (`autoupgrade`), unless it was installed from a distribution package.", "", "A background program with a web interface; the Linux download is a tar archive with the `syncthing` binary.", True, True),
    ("Transmission", "transmission/transmission", False, "Updates itself on macOS (Sparkle).", "GPL-2.0 / GPL-3.0", "No Linux binaries in its GitHub releases (distributions package it).", False, ["macos"]),
    ("HandBrake", "HandBrake/HandBrake", True, "Downloads and runs the new installer on Windows (`UpdateService`) and updates through Sparkle on macOS.", "", "", False, ["macos", "windows"]),
    ("Anki", "ankitects/anki", True, "Downloads and installs the new `.msi` or `.dmg` on Windows and macOS; on Linux it opens the download page.", "AGPL-3.0", "Syncing between devices needs an AnkiWeb account (optional).", False, ["macos", "windows"]),
    ("MuseScore Studio", "musescore/MuseScore", True, "Downloads and installs updates on Windows and macOS (its update service).", "GPL-3.0", "", False, ["macos", "windows"]),
    ("Mumble", "mumble-voip/mumble", False, "Downloads the new installer and offers to run it on Windows (`VersionCheck`).", "BSD-3-Clause", "No Linux binaries in its GitHub releases (distributions package it).", False, ["windows"]),
    ("RustDesk", "rustdesk/rustdesk", False, "Downloads and installs updates on Windows and macOS (`updater.rs`).", "", "Uses RustDesk's public relay servers unless you run your own.", False, ["macos", "windows"]),
    ("Upscayl", "upscayl/upscayl", True, "Updates itself on every platform, including the AppImage (electron-updater).", "", "", False, True),
    ("Zettlr", "Zettlr/Zettlr", True, "Downloads the new installer and runs it on Windows and macOS; on Linux it downloads the file and opens its folder.", "", "", False, ["macos", "windows"]),
    ("Cryptomator", "cryptomator/cryptomator", True, "Updates itself from the new `.dmg` on macOS (`DmgUpdateMechanism`); on Linux only its Flatpak updates itself.", "", "", False, ["macos"]),
]


def months_since(d: str) -> float:
    y, m, dd = (int(x) for x in d.split("-"))
    return (TODAY - date(y, m, dd)).days / 30.4


def trust(f: dict) -> int:
    t = 3
    if f.get("sigs"):
        t += 1
    if f.get("sigs") or f.get("sums"):
        t += 1
    if months_since(f["date"]) > 18:
        t -= 1
    return max(1, min(5, t))


def rating(f: dict) -> int:
    s = f.get("stars", 0)
    r = 5 if s >= 30000 else 4 if s >= 10000 else 3
    if months_since(f["date"]) > 18:
        r -= 1
    return r


def platforms(f: dict) -> str:
    lab = {"appimage": "AppImage", "deb": ".deb", "rpm": ".rpm", "tarball": "tar archive", "zip": "zip", "msi": ".msi", "exe": ".exe",
           "msix": ".msix", "dmg": ".dmg", "pkg": ".pkg"}
    out = []
    for os_, key in (("Linux", "linux"), ("Windows", "windows"), ("macOS", "macos")):
        kinds = f.get(key) or []
        out.append(f"{os_}: {', '.join(lab.get(k, k) for k in kinds)}" if kinds else f"{os_}: none")
    return "; ".join(out)


ALL = [a + (False,) for a in APPS] + AUTO
ALL.sort(key=lambda a: -F[a[1]].get("stars", 0))
rows, sections = [], []
for name, repo, offline, updater, lic, note, cmd, auto in ALL:
    f = F[repo]
    tags = ["foss"]
    if f.get("funding"):
        tags.append("donation")
    if offline:
        tags.append("offline")
    if "appimage" in (f.get("linux") or []) or "zip" in (f.get("windows") or []):
        tags.append("portable")
    if f.get("sigs") or f.get("sums"):
        tags.append("signed")
    if repo == "ventoy/Ventoy":
        tags.append("upstreamnonfree")
    rows.append(f"| {name} | https://github.com/{repo} | {', '.join(tags)} | {trust(f)} | {rating(f)} |")
    sig = (f"{len(f['sigs'])} signature files" if f.get("sigs") else "") + (" and " if f.get("sigs") and f.get("sums") else "") + \
          (f"{len(f['sums'])} checksum files" if f.get("sums") else "")
    lines = [f"# {name}", "", (f.get("desc") or "").strip().rstrip(".") + ".", "",
             f"- **License:** {lic or f.get('license') or 'see the repository'}",
             f"- **Latest release:** {f['version']} ({f['date']}), on GitHub",
             f"- **Downloads:** {platforms(f)}",
             f"- **Verification:** {sig or 'no published checksums or signatures; GitHub records a SHA-256 digest for each file'}",
             f"- **Updates:** {updater or 'no built-in updater found in the source'}",
             f"- **Popularity:** {f.get('stars', 0):,} GitHub stars"]
    if note:
        lines.append(f"- **Note:** {note}")
    opts = []
    if "appimage" in (f.get("linux") or []) or (auto and (f.get("linux") or [])):
        opts += ["- App menu: yes", f"- Command link: {'yes' if cmd else 'no'}"] + ([] if auto else ["- Stable name link: yes"])
    if auto is True:
        opts.append("- Auto update: yes")
    elif auto:      # one line per platform (requirement 10.3.1)
        opts += [f"- Auto update ({p}): {'yes' if p in auto else 'no'}" for p in ("linux", "windows", "macos")]
    if opts:
        lines += ["", f"## {name}::Settings", ""] + opts
    sections.append("\n".join(lines))

n_auto = len(AUTO)
doc = f"""# AppKata picks

{len(ALL)} free and open source desktop apps that publish downloadable releases on GitHub.
{len(APPS)} of them don't update themselves, so AppKata installs and updates them. The other
{n_auto} update themselves on some or all platforms; their `Auto update` setting tells AppKata to
install and track them there but leave the updating to the app.

This is an AppKata [trust file](requirements.md#10-trust-and-the-appkatamd-file): add this
repository as a Trust in AppKata (**Sources → Trusts → Add**) to see these apps in your Catalog.

## How the apps were chosen (2026-10-02)

- **Candidates:** popular FOSS desktop apps with GitHub releases.
- **Downloads:** the latest stable release (not a nightly) must have files to install, read
  from the project's release page.
- **Self-updating:** each project's source was scanned for updaters that download and install
  new versions (electron-updater, Sparkle, WinSparkle, Squirrel, built-in Windows updaters,
  self-upgrade code), and on which platforms they run. Apps that have one get an
  `Auto update` line in their `::Settings` section: `- Auto update: yes` when it
  updates itself everywhere, otherwise one line per platform, such as `- Auto update (linux): no`
  and `- Auto update (windows): yes`. Apps that only *notify* about a new version don't count as
  self-updating, and say so under **Updates**.
- **Left out:** Signal Desktop, which publishes no downloads on GitHub, so AppKata can't install
  it.
- **Order:** by GitHub stars, highest first.

## How Trust and Rating were set

These are a starting point from checkable facts, not personal opinions; adjust them before
signing.

- **Trust** starts at 3; +1 when the project publishes signature files with its releases; +1
  when it publishes signatures or checksum files; −1 when the latest stable release is more than
  18 months old.
- **Rating** is 5 for 30,000+ GitHub stars, 4 for 10,000+, otherwise 3; −1 when the latest
  stable release is more than 18 months old.

| App | Source | Tags | Trust | Rating |
|---|---|---|---|---|
""" + "\n".join(rows) + "\n\n" + "\n\n".join(sections) + "\n"
open(os.path.join(HERE, "..", "docs", "AppKata.md"), "w").write(doc)
print(f"wrote docs/AppKata.md ({len(ALL)} apps, {n_auto} that update themselves)")
