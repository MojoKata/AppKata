# AppKata picks

43 free and open source desktop apps that publish downloadable releases on GitHub.
30 of them don't update themselves, so AppKata installs and updates them. The other
13 update themselves on some or all platforms; their `Auto update` setting tells AppKata to
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
| RustDesk | https://github.com/rustdesk/rustdesk | foss, donation, portable | 3 | 5 |
| Neovim | https://github.com/neovim/neovim | foss, donation, offline, portable | 3 | 5 |
| LocalSend | https://github.com/localsend/localsend | foss, donation, portable | 3 | 5 |
| Syncthing | https://github.com/syncthing/syncthing | foss, donation, portable, signed | 5 | 5 |
| Ventoy | https://github.com/ventoy/Ventoy | foss, donation, offline, portable, signed, upstreamnonfree | 4 | 5 |
| OBS Studio | https://github.com/obsproject/obs-studio | foss, donation, offline, portable | 3 | 5 |
| Alacritty | https://github.com/alacritty/alacritty | foss, offline | 3 | 5 |
| Joplin | https://github.com/laurent22/joplin | foss, donation, offline, portable, signed | 4 | 5 |
| Upscayl | https://github.com/upscayl/upscayl | foss, donation, offline, portable | 2 | 4 |
| Helix | https://github.com/helix-editor/helix | foss, donation, offline, portable | 3 | 5 |
| qBittorrent | https://github.com/qbittorrent/qBittorrent | foss, donation, portable, signed | 5 | 5 |
| FreeCAD | https://github.com/FreeCAD/FreeCAD | foss, donation, offline, portable, signed | 4 | 5 |
| Czkawka | https://github.com/qarmin/czkawka | foss, donation, offline, portable | 3 | 5 |
| VSCodium | https://github.com/VSCodium/vscodium | foss, offline, portable, signed | 4 | 5 |
| Anki | https://github.com/ankitects/anki | foss, offline | 3 | 5 |
| Flameshot | https://github.com/flameshot-org/flameshot | foss, offline, portable, signed | 4 | 5 |
| WezTerm | https://github.com/wezterm/wezterm | foss, donation, offline, portable, signed | 3 | 3 |
| KeePassXC | https://github.com/keepassxreboot/keepassxc | foss, donation, offline, portable, signed | 5 | 4 |
| DB Browser for SQLite | https://github.com/sqlitebrowser/sqlitebrowser | foss, donation, offline, portable | 2 | 3 |
| HandBrake | https://github.com/HandBrake/HandBrake | foss, offline, portable, signed | 5 | 4 |
| Cutter | https://github.com/rizinorg/cutter | foss, offline, portable | 3 | 4 |
| Audacity | https://github.com/audacity/audacity | foss, offline, portable, signed | 4 | 4 |
| Cryptomator | https://github.com/cryptomator/cryptomator | foss, donation, offline, portable, signed | 5 | 4 |
| Xournal++ | https://github.com/xournalpp/xournalpp | foss, offline, portable | 3 | 4 |
| Shotcut | https://github.com/mltframework/shotcut | foss, offline, portable, signed | 4 | 4 |
| Transmission | https://github.com/transmission/transmission | foss, portable | 3 | 4 |
| MuseScore Studio | https://github.com/musescore/MuseScore | foss, offline, portable, signed | 4 | 4 |
| espanso | https://github.com/espanso/espanso | foss, donation, offline, portable | 3 | 4 |
| Zettlr | https://github.com/Zettlr/Zettlr | foss, donation, offline, portable, signed | 4 | 4 |
| darktable | https://github.com/darktable-org/darktable | foss, offline, portable, signed | 5 | 4 |
| Tiled | https://github.com/mapeditor/tiled | foss, donation, offline, portable | 3 | 4 |
| CopyQ | https://github.com/hluk/CopyQ | foss, offline, portable, signed | 4 | 4 |
| VeraCrypt | https://github.com/veracrypt/VeraCrypt | foss, donation, offline, portable, signed | 5 | 4 |
| LMMS | https://github.com/LMMS/lmms | foss, donation, offline, portable | 2 | 3 |
| Stellarium | https://github.com/Stellarium/stellarium | foss, donation, offline, portable, signed | 5 | 4 |
| LibreSprite | https://github.com/LibreSprite/LibreSprite | foss, offline, portable | 3 | 3 |
| Mumble | https://github.com/mumble-voip/mumble | foss, donation, signed | 5 | 3 |
| BleachBit | https://github.com/bleachbit/bleachbit | foss, donation, offline, portable, signed | 5 | 3 |
| OpenShot | https://github.com/OpenShot/openshot-qt | foss, offline, portable, signed | 4 | 3 |
| Pinta | https://github.com/PintaProject/Pinta | foss, offline, portable, signed | 5 | 3 |
| qView | https://github.com/jurplel/qView | foss, offline, portable | 3 | 3 |
| Notepadqq | https://github.com/notepadqq/notepadqq | foss, offline, portable | 3 | 3 |
| Gaphor | https://github.com/gaphor/gaphor | foss, donation, offline | 3 | 3 |

# RustDesk

An open source remote desktop app designed for self-hosting, an alternative to TeamViewer.

- **License:** AGPL-3.0
- **Latest release:** 1.5.0 (2026-09-30), on GitHub
- **Downloads:** Linux: AppImage, flatpak, .deb, tar archive; Windows: .msi, .exe; macOS: .dmg
- **Verification:** no published checksums or signatures; GitHub records a SHA-256 digest for each file
- **Updates:** Downloads and installs updates on Windows and macOS (`updater.rs`).
- **Popularity:** 125,002 GitHub stars
- **Note:** Uses RustDesk's public relay servers unless you run your own.

## RustDesk::Settings

- App menu: yes
- Command link: no
- Auto update (linux): no
- Auto update (windows): yes
- Auto update (macos): yes

# Neovim

Vim-fork focused on extensibility and usability. Contribute to neovim/neovim development by creating an account on GitHub.

- **License:** Apache-2.0 / Vim
- **Latest release:** 0.12.5 (2026-08-23), on GitHub
- **Downloads:** Linux: AppImage, tar archive; Windows: .msi, zip; macOS: none
- **Verification:** no published checksums or signatures; GitHub records a SHA-256 digest for each file
- **Updates:** no built-in updater found in the source
- **Popularity:** 102,696 GitHub stars

## Neovim::Settings

- App menu: yes
- Command link: yes
- Stable name link: yes

# LocalSend

An open-source cross-platform alternative to AirDrop.

- **License:** Apache-2.0
- **Latest release:** 1.18.2 (2026-08-21), on GitHub
- **Downloads:** Linux: AppImage, .deb, tar archive; Windows: .exe, zip; macOS: .dmg
- **Verification:** no published checksums or signatures; GitHub records a SHA-256 digest for each file
- **Updates:** no built-in updater found in the source
- **Popularity:** 93,189 GitHub stars
- **Note:** Needs a local network, not the internet.

## LocalSend::Settings

- App menu: yes
- Command link: no
- Stable name link: yes

# Syncthing

Open source continuous file synchronization.

- **License:** MPL-2.0
- **Latest release:** 2.1.5 (2026-09-08), on GitHub
- **Downloads:** Linux: .deb, tar archive; Windows: zip; macOS: zip
- **Verification:** 3 signature files and 2 checksum files
- **Updates:** Upgrades its own program on every platform (`autoupgrade`), unless it was installed from a distribution package.
- **Popularity:** 89,104 GitHub stars
- **Note:** A background program with a web interface; the Linux download is a tar archive with the `syncthing` binary.

## Syncthing::Settings

- App menu: yes
- Command link: yes
- Auto update: yes

# Ventoy

A new bootable USB solution. Contribute to ventoy/Ventoy development by creating an account on GitHub.

- **License:** GPL-3.0
- **Latest release:** 1.1.17 (2026-07-24), on GitHub
- **Downloads:** Linux: tar archive; Windows: zip; macOS: none
- **Verification:** 1 checksum files
- **Updates:** no built-in updater found in the source
- **Popularity:** 79,674 GitHub stars
- **Note:** Ships prebuilt binary components inside its release archives.

# OBS Studio

Free and open source software for live streaming and screen recording.

- **License:** GPL-2.0
- **Latest release:** 32.2.2 (2026-08-14), on GitHub
- **Downloads:** Linux: .deb; Windows: .exe, zip; macOS: .dmg
- **Verification:** no published checksums or signatures; GitHub records a SHA-256 digest for each file
- **Updates:** Updates itself on Windows (its own updater) and macOS (Sparkle).
- **Popularity:** 76,880 GitHub stars
- **Note:** Linux builds are `.deb` packages for Ubuntu.

## OBS Studio::Settings

- App menu: yes
- Command link: no
- Auto update (linux): no
- Auto update (windows): yes
- Auto update (macos): yes

# Alacritty

A cross-platform, OpenGL terminal emulator. Contribute to alacritty/alacritty development by creating an account on GitHub.

- **License:** Apache-2.0
- **Latest release:** 0.17.0 (2026-04-06), on GitHub
- **Downloads:** Linux: none; Windows: .msi, .exe; macOS: .dmg
- **Verification:** no published checksums or signatures; GitHub records a SHA-256 digest for each file
- **Updates:** no built-in updater found in the source
- **Popularity:** 65,879 GitHub stars
- **Note:** No Linux binaries in its releases (distributions package it).

# Joplin

A privacy-focused note-taking app with sync, for Windows, macOS, Linux, Android and iOS.

- **License:** AGPL-3.0
- **Latest release:** 3.7.21 (2026-09-25), on GitHub
- **Downloads:** Linux: AppImage, .deb; Windows: .exe; macOS: .dmg, .pkg, zip
- **Verification:** 1 checksum files
- **Updates:** Updates itself on Windows and macOS (electron-updater, `AutoUpdaterService`); on Linux it offers the download.
- **Popularity:** 56,560 GitHub stars
- **Note:** Syncing notes needs a sync target (Joplin Cloud, Nextcloud, WebDAV, or a folder).

## Joplin::Settings

- App menu: yes
- Command link: no
- Auto update (linux): no
- Auto update (windows): yes
- Auto update (macos): yes

# Upscayl

A free and open source AI image upscaler for Linux, macOS and Windows.

- **License:** AGPL-3.0
- **Latest release:** 2.15.0 (2024-12-25), on GitHub
- **Downloads:** Linux: AppImage, .deb; Windows: .exe, zip; macOS: .dmg, zip
- **Verification:** no published checksums or signatures; GitHub records a SHA-256 digest for each file
- **Updates:** Updates itself on every platform, including the AppImage (electron-updater).
- **Popularity:** 50,063 GitHub stars

## Upscayl::Settings

- App menu: yes
- Command link: no
- Auto update: yes

# Helix

A post-modern modal text editor. Contribute to helix-editor/helix development by creating an account on GitHub.

- **License:** MPL-2.0
- **Latest release:** 25.07.1 (2025-07-18), on GitHub
- **Downloads:** Linux: AppImage, .deb, tar archive; Windows: zip; macOS: none
- **Verification:** no published checksums or signatures; GitHub records a SHA-256 digest for each file
- **Updates:** no built-in updater found in the source
- **Popularity:** 46,433 GitHub stars

## Helix::Settings

- App menu: yes
- Command link: yes
- Stable name link: yes

# qBittorrent

qBittorrent BitTorrent client. Contribute to qbittorrent/qBittorrent development by creating an account on GitHub.

- **License:** GPL-2.0 / GPL-3.0
- **Latest release:** 5.2.4 (2026-09-27), on GitHub
- **Downloads:** Linux: AppImage; Windows: .exe; macOS: none
- **Verification:** 5 signature files
- **Updates:** Checks for new versions and opens the download page (`programupdater`).
- **Popularity:** 40,505 GitHub stars

## qBittorrent::Settings

- App menu: yes
- Command link: no
- Stable name link: yes

# FreeCAD

Official source code of FreeCAD, a free and opensource multiplatform 3D parametric modeler.

- **License:** LGPL-2.1
- **Latest release:** 2026.10.01 (2026-10-01), on GitHub
- **Downloads:** Linux: AppImage; Windows: .exe; macOS: .dmg
- **Verification:** 8 checksum files
- **Updates:** no built-in updater found in the source
- **Popularity:** 33,891 GitHub stars

## FreeCAD::Settings

- App menu: yes
- Command link: no
- Stable name link: yes

# Czkawka

Multi functional app to find duplicates, empty folders, similar images etc.

- **License:** MIT
- **Latest release:** 12.0.2 (2026-09-09), on GitHub
- **Downloads:** Linux: none; Windows: .exe, zip; macOS: zip
- **Verification:** no published checksums or signatures; GitHub records a SHA-256 digest for each file
- **Updates:** no built-in updater found in the source
- **Popularity:** 33,858 GitHub stars
- **Note:** Linux builds are plain binaries, not AppImages or packages.

# VSCodium

Binary releases of VS Code without Microsoft branding, telemetry or licensing.

- **License:** MIT
- **Latest release:** 1.135.06055 (2026-09-08), on GitHub
- **Downloads:** Linux: AppImage, .deb, tar archive; Windows: .msi, .exe, zip; macOS: .dmg, zip
- **Verification:** 108 checksum files
- **Updates:** Downloads and installs updates on Windows and macOS (VS Code's update service, pointed at VSCodium's GitHub releases); on Linux it only says a new version is out.
- **Popularity:** 33,489 GitHub stars

## VSCodium::Settings

- App menu: yes
- Command link: yes
- Auto update (linux): no
- Auto update (windows): yes
- Auto update (macos): yes

# Anki

A smart spaced-repetition flashcard program.

- **License:** AGPL-3.0
- **Latest release:** 26.09.3 (2026-09-22), on GitHub
- **Downloads:** Linux: tar archive; Windows: .msi; macOS: .dmg
- **Verification:** no published checksums or signatures; GitHub records a SHA-256 digest for each file
- **Updates:** Downloads and installs the new `.msi` or `.dmg` on Windows and macOS; on Linux it opens the download page.
- **Popularity:** 31,709 GitHub stars
- **Note:** Syncing between devices needs an AnkiWeb account (optional).

## Anki::Settings

- App menu: yes
- Command link: no
- Auto update (linux): no
- Auto update (windows): yes
- Auto update (macos): yes

# Flameshot

Powerful yet simple to use screenshot software :desktop_computer: :camera_flash: - GitHub.

- **License:** GPL-3.0
- **Latest release:** 14.0.0 (2026-06-10), on GitHub
- **Downloads:** Linux: none; Windows: .msi, zip; macOS: .dmg, zip
- **Verification:** 16 checksum files
- **Updates:** Shows a notification when a new version is out (`updatenotificationwidget`).
- **Popularity:** 31,059 GitHub stars
- **Note:** Its Linux packages are inside `.zip` files, which AppKata doesn't open yet; Windows and macOS downloads are direct.

# WezTerm

A GPU-accelerated cross-platform terminal emulator and multiplexer written by @wez and implemented in Rust.

- **License:** MIT
- **Latest release:** 20240203-110809-5046fc22 (2024-02-03), on GitHub
- **Downloads:** Linux: AppImage, .deb; Windows: .exe, zip; macOS: zip
- **Verification:** 21 checksum files
- **Updates:** Checks for new versions and links to the release (`update.rs`).
- **Popularity:** 29,096 GitHub stars
- **Note:** The last tagged release is from February 2024; nightly builds continue.

## WezTerm::Settings

- App menu: yes
- Command link: yes
- Stable name link: yes

# KeePassXC

KeePassXC is a cross-platform community-driven port of the Windows application “KeePass Password Safe”.

- **License:** GPL-3.0
- **Latest release:** 2.7.12 (2026-03-10), on GitHub
- **Downloads:** Linux: AppImage; Windows: .msi, zip; macOS: .dmg
- **Verification:** 18 signature files
- **Updates:** Checks for new versions and shows a dialog (`UpdateChecker`); it doesn't download or install.
- **Popularity:** 29,048 GitHub stars

## KeePassXC::Settings

- App menu: yes
- Command link: no
- Stable name link: yes

# DB Browser for SQLite

Official home of the DB Browser for SQLite (DB4S) project. Previously known as &quot;SQLite Database Browser&quot; and &quot;Database Browser for SQLite&quot;. Website at:  - GitHub.

- **License:** MPL-2.0 / GPL-3.0
- **Latest release:** 3.13.1 (2024-10-15), on GitHub
- **Downloads:** Linux: none; Windows: .msi, .exe, zip; macOS: .dmg, zip
- **Verification:** no published checksums or signatures; GitHub records a SHA-256 digest for each file
- **Updates:** no built-in updater found in the source
- **Popularity:** 24,654 GitHub stars
- **Note:** The last stable release is from October 2024; nightly builds continue.

# HandBrake

An open source video transcoder.

- **License:** GPL-2.0
- **Latest release:** 1.11.2 (2026-06-07), on GitHub
- **Downloads:** Linux: flatpak; Windows: .exe, zip; macOS: .dmg
- **Verification:** 13 signature files
- **Updates:** Downloads and runs the new installer on Windows (`UpdateService`) and updates through Sparkle on macOS.
- **Popularity:** 24,548 GitHub stars

## HandBrake::Settings

- App menu: yes
- Command link: no
- Auto update (linux): no
- Auto update (windows): yes
- Auto update (macos): yes

# Cutter

Free and Open Source Reverse Engineering Platform powered by rizin.

- **License:** GPL-3.0
- **Latest release:** 2.5.0 (2026-06-30), on GitHub
- **Downloads:** Linux: AppImage; Windows: zip; macOS: .dmg
- **Verification:** no published checksums or signatures; GitHub records a SHA-256 digest for each file
- **Updates:** Checks for new versions and shows a message (`UpdateWorker`).
- **Popularity:** 19,861 GitHub stars

## Cutter::Settings

- App menu: yes
- Command link: no
- Stable name link: yes

# Audacity

Audio Editor                                     . Contribute to audacity/audacity development by creating an account on GitHub.

- **License:** GPL-3.0
- **Latest release:** 4.0.1 (2026-09-29), on GitHub
- **Downloads:** Linux: AppImage; Windows: .msi; macOS: .dmg
- **Verification:** 1 checksum files
- **Updates:** Checks for new versions and opens the website (`UpdateManager`).
- **Popularity:** 18,629 GitHub stars
- **Note:** Optional audio.com cloud features need an account.

## Audacity::Settings

- App menu: yes
- Command link: no
- Stable name link: yes

# Cryptomator

Client-side encryption for your cloud storage, for Windows, macOS and Linux.

- **License:** GPL-3.0
- **Latest release:** 1.19.3 (2026-06-29), on GitHub
- **Downloads:** Linux: AppImage, .deb; Windows: .msi, .exe; macOS: .dmg
- **Verification:** 10 signature files
- **Updates:** Updates itself from the new `.dmg` on macOS (`DmgUpdateMechanism`); on Linux only its Flatpak updates itself.
- **Popularity:** 16,231 GitHub stars

## Cryptomator::Settings

- App menu: yes
- Command link: no
- Auto update (linux): no
- Auto update (windows): no
- Auto update (macos): yes

# Xournal++

Xournal++ is a handwriting notetaking software with PDF annotation support. Written in C++ with GTK3, supporting Linux (e.g. Ubuntu, Debian, Arch, SUSE), macOS and Windows 10. Supports pen input from devices such as Wacom Tablets.

- **License:** GPL-2.0
- **Latest release:** 1.3.8 (2026-09-25), on GitHub
- **Downloads:** Linux: AppImage, .deb, tar archive; Windows: .exe, zip; macOS: .dmg
- **Verification:** no published checksums or signatures; GitHub records a SHA-256 digest for each file
- **Updates:** no built-in updater found in the source
- **Popularity:** 15,464 GitHub stars

## Xournal++::Settings

- App menu: yes
- Command link: no
- Stable name link: yes

# Shotcut

cross-platform (Qt), open-source (GPLv3) video editor.

- **License:** GPL-3.0
- **Latest release:** 26.9.27 (2026-09-27), on GitHub
- **Downloads:** Linux: AppImage; Windows: .exe, zip; macOS: .dmg
- **Verification:** 1 checksum files
- **Updates:** Checks for new versions and links to the download page.
- **Popularity:** 15,332 GitHub stars

## Shotcut::Settings

- App menu: yes
- Command link: no
- Stable name link: yes

# Transmission

A fast, easy and free BitTorrent client.

- **License:** GPL-2.0 / GPL-3.0
- **Latest release:** 4.1.3 (2026-06-29), on GitHub
- **Downloads:** Linux: none; Windows: .msi, zip; macOS: .dmg, zip
- **Verification:** no published checksums or signatures; GitHub records a SHA-256 digest for each file
- **Updates:** Updates itself on macOS (Sparkle).
- **Popularity:** 15,262 GitHub stars
- **Note:** No Linux binaries in its GitHub releases (distributions package it).

## Transmission::Settings

- Auto update (linux): no
- Auto update (windows): no
- Auto update (macos): yes

# MuseScore Studio

Free and open source music notation software.

- **License:** GPL-3.0
- **Latest release:** 4.7.5 (2026-08-31), on GitHub
- **Downloads:** Linux: AppImage; Windows: .msi, .exe; macOS: .dmg
- **Verification:** 1 checksum files
- **Updates:** Downloads and installs updates on Windows and macOS (its update service).
- **Popularity:** 15,166 GitHub stars

## MuseScore Studio::Settings

- App menu: yes
- Command link: no
- Auto update (linux): no
- Auto update (windows): yes
- Auto update (macos): yes

# espanso

A Privacy-first, Cross-platform Text Expander written in Rust.

- **License:** GPL-3.0
- **Latest release:** 2.4.1 (2026-09-01), on GitHub
- **Downloads:** Linux: AppImage, .deb; Windows: .exe, zip; macOS: .dmg
- **Verification:** no published checksums or signatures; GitHub records a SHA-256 digest for each file
- **Updates:** no built-in updater found in the source
- **Popularity:** 14,572 GitHub stars

## espanso::Settings

- App menu: yes
- Command link: no
- Stable name link: yes

# Zettlr

A one-stop publication workbench: a Markdown editor for writing and research.

- **License:** GPL-3.0
- **Latest release:** 4.8.0 (2026-09-18), on GitHub
- **Downloads:** Linux: AppImage, .deb; Windows: .exe; macOS: .dmg
- **Verification:** 1 checksum files
- **Updates:** Downloads the new installer and runs it on Windows and macOS; on Linux it downloads the file and opens its folder.
- **Popularity:** 13,638 GitHub stars

## Zettlr::Settings

- App menu: yes
- Command link: no
- Auto update (linux): no
- Auto update (windows): yes
- Auto update (macos): yes

# darktable

darktable is an open source photography workflow application and raw developer.

- **License:** GPL-3.0
- **Latest release:** 5.6.1 (2026-08-26), on GitHub
- **Downloads:** Linux: AppImage; Windows: .exe; macOS: .dmg
- **Verification:** 1 signature files
- **Updates:** no built-in updater found in the source
- **Popularity:** 13,176 GitHub stars

## darktable::Settings

- App menu: yes
- Command link: no
- Stable name link: yes

# Tiled

Flexible level editor. Contribute to mapeditor/tiled development by creating an account on GitHub.

- **License:** Apache-2.0 / GPL-2.0
- **Latest release:** 1.12.2 (2026-05-27), on GitHub
- **Downloads:** Linux: AppImage; Windows: .msi; macOS: zip
- **Verification:** no published checksums or signatures; GitHub records a SHA-256 digest for each file
- **Updates:** Checks for new versions and shows a link (`newversionchecker`).
- **Popularity:** 12,935 GitHub stars

## Tiled::Settings

- App menu: yes
- Command link: no
- Stable name link: yes

# CopyQ

Clipboard manager with advanced features. Contribute to hluk/CopyQ development by creating an account on GitHub.

- **License:** GPL-3.0
- **Latest release:** 16.0.0 (2026-05-30), on GitHub
- **Downloads:** Linux: AppImage; Windows: .exe, zip; macOS: .dmg, zip
- **Verification:** 1 checksum files
- **Updates:** no built-in updater found in the source
- **Popularity:** 12,332 GitHub stars

## CopyQ::Settings

- App menu: yes
- Command link: no
- Stable name link: yes

# VeraCrypt

Disk encryption with strong security based on TrueCrypt.

- **License:** Apache-2.0 / TrueCrypt 3.0
- **Latest release:** 1.26.29 (2026-06-11), on GitHub
- **Downloads:** Linux: AppImage, .deb; Windows: .msi, .exe; macOS: .dmg
- **Verification:** 64 signature files and 6 checksum files
- **Updates:** no built-in updater found in the source
- **Popularity:** 11,733 GitHub stars

## VeraCrypt::Settings

- App menu: yes
- Command link: no
- Stable name link: yes

# LMMS

Cross-platform music production software. Contribute to LMMS/lmms development by creating an account on GitHub.

- **License:** GPL-2.0
- **Latest release:** 1.2.2 (2020-07-04), on GitHub
- **Downloads:** Linux: AppImage; Windows: .exe; macOS: .dmg
- **Verification:** no published checksums or signatures; GitHub records a SHA-256 digest for each file
- **Updates:** no built-in updater found in the source
- **Popularity:** 10,421 GitHub stars
- **Note:** The last stable release is from 2020; development continues in nightly builds.

## LMMS::Settings

- App menu: yes
- Command link: no
- Stable name link: yes

# Stellarium

Stellarium is a free GPL software which renders realistic skies in real time with OpenGL. It is available for Linux/Unix, Windows, macOS and Haiku. With Stellarium, you really see what you can see with your eyes, binoculars or a small telescope.

- **License:** GPL-2.0
- **Latest release:** 26.3 (2026-09-28), on GitHub
- **Downloads:** Linux: AppImage; Windows: .exe, zip; macOS: zip
- **Verification:** 12 signature files
- **Updates:** no built-in updater found in the source
- **Popularity:** 10,027 GitHub stars

## Stellarium::Settings

- App menu: yes
- Command link: no
- Stable name link: yes

# LibreSprite

Animated sprite editor &amp; pixel art tool -- Fork of the last GPLv2 commit of Aseprite.

- **License:** GPL-2.0
- **Latest release:** 1.3 (2026-10-01), on GitHub
- **Downloads:** Linux: AppImage; Windows: .exe, zip; macOS: .dmg
- **Verification:** no published checksums or signatures; GitHub records a SHA-256 digest for each file
- **Updates:** no built-in updater found in the source
- **Popularity:** 8,479 GitHub stars

## LibreSprite::Settings

- App menu: yes
- Command link: no
- Stable name link: yes

# Mumble

Open source, low-latency, high-quality voice chat.

- **License:** BSD-3-Clause
- **Latest release:** 1.5.915 (2026-07-18), on GitHub
- **Downloads:** Linux: none; Windows: .exe; macOS: none
- **Verification:** 3 signature files
- **Updates:** Downloads the new installer and offers to run it on Windows (`VersionCheck`).
- **Popularity:** 8,314 GitHub stars
- **Note:** No Linux binaries in its GitHub releases (distributions package it).

## Mumble::Settings

- Auto update (linux): no
- Auto update (windows): yes
- Auto update (macos): no

# BleachBit

BleachBit system cleaner for Windows and Linux. Contribute to bleachbit/bleachbit development by creating an account on GitHub.

- **License:** GPL-3.0
- **Latest release:** 6.0.4 (2026-09-08), on GitHub
- **Downloads:** Linux: none; Windows: .exe, zip; macOS: zip
- **Verification:** 22 signature files and 2 checksum files
- **Updates:** Checks for new versions and links to the website; on Windows it can download cleaner definitions (winapp2.ini), not the app.
- **Popularity:** 7,037 GitHub stars

# OpenShot

OpenShot Video Editor is an award-winning free and open-source video editor for Linux, Mac, and Windows, and is dedicated to delivering high quality video editing and animation solutions to the world.

- **License:** GPL-3.0
- **Latest release:** 4.0.1 (2026-09-27), on GitHub
- **Downloads:** Linux: AppImage; Windows: .exe; macOS: none
- **Verification:** 8 checksum files
- **Updates:** no built-in updater found in the source
- **Popularity:** 6,579 GitHub stars

## OpenShot::Settings

- App menu: yes
- Command link: no
- Stable name link: yes

# Pinta

Simple GTK Paint Program. Contribute to PintaProject/Pinta development by creating an account on GitHub.

- **License:** MIT
- **Latest release:** 3.1.2 (2026-04-02), on GitHub
- **Downloads:** Linux: none; Windows: .exe, zip; macOS: .dmg, zip
- **Verification:** 1 signature files and 1 checksum files
- **Updates:** no built-in updater found in the source
- **Popularity:** 4,065 GitHub stars

# qView

Practical and minimal image viewer. Contribute to jurplel/qView development by creating an account on GitHub.

- **License:** GPL-3.0
- **Latest release:** 7.1 (2025-07-26), on GitHub
- **Downloads:** Linux: AppImage; Windows: .exe, zip; macOS: .dmg
- **Verification:** no published checksums or signatures; GitHub records a SHA-256 digest for each file
- **Updates:** Checks for new versions and shows a notice (`updatechecker`).
- **Popularity:** 3,570 GitHub stars

## qView::Settings

- App menu: yes
- Command link: no
- Stable name link: yes

# Notepadqq

A simple, general-purpose editor for Linux and MacOS.

- **License:** GPL-3.0
- **Latest release:** 2.1.1 (2026-07-03), on GitHub
- **Downloads:** Linux: AppImage; Windows: none; macOS: .dmg
- **Verification:** no published checksums or signatures; GitHub records a SHA-256 digest for each file
- **Updates:** no built-in updater found in the source
- **Popularity:** 2,330 GitHub stars

## Notepadqq::Settings

- App menu: yes
- Command link: no
- Stable name link: yes

# Gaphor

Gaphor is the simple modeling tool. Contribute to gaphor/gaphor development by creating an account on GitHub.

- **License:** Apache-2.0
- **Latest release:** 3.3.2 (2026-05-02), on GitHub
- **Downloads:** Linux: none; Windows: .exe; macOS: .dmg
- **Verification:** no published checksums or signatures; GitHub records a SHA-256 digest for each file
- **Updates:** no built-in updater found in the source
- **Popularity:** 2,275 GitHub stars
