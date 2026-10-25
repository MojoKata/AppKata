# AppKata — Requirements

AppKata is a cross-platform (Linux, macOS, Windows 10+) FOSS app store built on Git and ngit
(Nostr Git). Each app is a git project. Its releases are found from the project's forge,
AppKata installs and updates them, and reviewers publish trust and ratings in signed
`AppKata.md` files.

This document describes the current desired behavior of the application. It is not a
changelog. The analysis behind it, including the research into Obtainium, is in
[`gaps.md`](gaps.md). Mockups live in [`../screenshots`](../screenshots/README.md).

---

## 1. Platform and architecture

1.1. AppKata runs on what its tests cover (`docs/testing.md`):

- Linux x86_64:
  - Linux Mint 22.3, the current release.
  - LMDE 7, Mint's Debian edition, its current release.
  - Ubuntu 24.04 LTS.
  - Ubuntu 26.04 LTS.
  - Ubuntu 22.04 LTS, without the sandbox: the AppImage is built there, for its glibc (2.35), and
    starts there, but sandboxing (17) isn't tested on it.

  A later Mint or LMDE release joins once the tests move to it. Package channels (16) use apt and
  Flatpak. Fedora, RHEL and the other RPM-based distributions aren't supported until RPM packaging
  is taken up again, and openSUSE isn't supported. Linux on arm64 is a later target.
- Windows 10 22H2, the last release, with every update up to its end of support, x64. Windows 11
  isn't tested yet. Earlier Windows 10 releases aren't supported, nor is Windows on arm64.
- macOS is a later target: no macOS build is made or tested yet (1.2, 1.6). PySide6 6.11's floor,
  macOS 13, would be its own.

1.2. Everything is written in Python, and AppKata runs on the Python its release carries: the
AppImage, the Windows installer and, once built, the macOS app each carry one, of one version for
all, with one PySide6, both set in `packaging/versions.env`. Running from source is for development
only, never a way to install AppKata, and uses that same version (`scripts/python-standalone.sh`
fetches it); the tests run AppKata's code on it too (review 3, R3-21: from source on Debian 12's own
Python 3.11.2, no tarball could be installed). The one exception is what a sandboxed app's launcher
runs on the computer's own `python3`, the file-argument helper and the `xdg-open` shim (17.6.2,
17.6.3): they work on the `python3` and `gi` of every platform whose sandbox 1.1 supports, the oldest
being Mint 22.3's and Ubuntu 24.04's 3.12.
The GUI uses PySide6 (Qt 6 with QML) and the `Basic` Qt Quick Controls style; its look is 5.2.

1.3. AppKata is one desktop-user process with no privileged service. When an install,
update or uninstall needs administrator rights, AppKata asks for them for that action only:

- `pkexec` on Linux.
- UAC on Windows (15.2).
- The system authorization prompt on macOS.

1.4. Git operations use the system `git`, which must be 2.34 or newer for SSH signature
verification. If `git` is missing, AppKata explains how to install it.

1.5. Nostr access (ngit repositories, NIP-05, kind-0 profiles) uses a configurable list of
relays (11.1).

1.6. Distribution:

- Linux: an AppImage, x86_64 (arm64 is a later target, 1.1). It needs no installation and updates itself
  (2.11.3), and it installs itself into the app menu on first start (2.11.3.1). There is no Flatpak
  of AppKata: the sandbox would have to be opened to the host for portable installs into `~/bin`,
  for package channels (16) and for PackageKit, which defeats the sandbox and which Flathub is
  unlikely to accept. The AppImage is AppKata's only form on Linux, so there are no `.deb` or
  `.rpm` packages, which would also compete with the package manager over AppKata's own updates
  (2.11.4). It carries its Python, PySide6's Qt and the xcb-util libraries Qt's X11 plugin needs,
  which no Debian-family desktop installs (review 3, R3-32). From the computer it takes only
  libraries every 1.1 distro's desktop installs: glibc, the GCC runtime, zlib, zstd and Brotli,
  GLib, D-Bus, OpenGL and EGL, Fontconfig and FreeType, X11 and XCB, xkbcommon, Wayland, OpenSSL 3
  and Kerberos (GSSAPI), each listed by library in `packaging/appimage-host-libs.txt` (R3-31). Qt
  also uses GTK 3 for its theme and the desktop portal where the desktop has them, and does without
  them otherwise.
- macOS: a signed, notarized `.dmg`.
- Windows: a signed Inno Setup installer, for the current user by default, without a UAC prompt
  (15.10).

1.7. **Running in the background.** AppKata has a tray icon (the menu-bar extra on macOS).

1.7.1. Closing the window leaves AppKata running in the tray, where it keeps checking for
updates (9.3).

1.7.2. The tray menu has **Open AppKata**, **Check for updates**, an "N updates available"
item that opens the Apps view, and **Quit AppKata**.

1.7.3. Quitting stops all background work. While an install is running or queued, **Quit**
(from ⋮, the tray, or the shortcut, 5.4) first asks "Quit while installing?" (5.8), listing
the installs. Quitting stops them; a partial download is kept and resumed next time (4.8.2).

1.7.4. A setting starts AppKata in the tray at login (11.1.1). It is off by default.

1.8. Local data (Sources, Trusts, Authorities, release metadata, images, READMEs) is stored
in a SQLite database, `appkata.db`, in the platform's application data folder. The database
schema is versioned and migrated when AppKata starts. The Audit (13) is kept in the same
database; the App log (14) is kept in text files.

| | Database and caches | App log (14.3) |
|---|---|---|
| Linux | `~/.local/share/appkata/` (`$XDG_DATA_HOME`) | `~/.local/state/appkata/` (`$XDG_STATE_HOME`) |
| Windows | `%LOCALAPPDATA%\AppKata\` | `%LOCALAPPDATA%\AppKata\Logs\` |
| macOS | `~/Library/Application Support/AppKata/` | `~/Library/Logs/AppKata/` (shown by Console) |

These follow each platform's convention: per-user, not synced to other machines (Windows
roaming profiles use `%APPDATA%`; AppKata's cache is machine-specific), and logs kept apart from
data where the platform says so.

1.9. **One AppKata at a time.** Starting AppKata while it's already running (from the app menu,
at login, or by an `appkata://` link, 11.3) hands its arguments to the running AppKata over a
local socket (`QLocalServer`), one per user and data folder, and exits. The running AppKata shows its window, and for a
link the Add source dialog.

## 2. Apps and Sources

2.1. An **app** is identified by a git project URL. An app reaches AppKata in one of two ways
(2.9):

- From a **Source**: a project the user has decided to trust themselves.
- From a **Trust**: a reviewer's claim (10) that the user trusts to provide such information.

A Source usually represents one app.

2.2. A Source URL can be:

- A forge project URL, such as `https://github.com/owner/repo`.
- A direct link to a project's releases page (2.5).
- An ngit repository, as `nostr://<npub>/<identifier>` or an `naddr`.

2.3. **Normalizing URLs.** Before Source URLs are stored or compared, they are normalized:

1. Lowercase the scheme and host.
2. Strip a trailing `/` and `.git`.
3. Map `git@host:owner/repo` to `https://host/owner/repo`.

URLs that are the same after this are the same app.

2.4. **Finding releases.** AppKata decides how to read a Source's releases as follows.

2.4.1. Known hosts:

| Host | Releases |
|---|---|
| github.com | `api.github.com/repos/{o}/{r}/releases`. When the API's rate limit is used up (60 requests an hour without a token), github.com's own pages instead: the releases Atom feed, less the bare tags it also lists (one not on the releases page whose own page says it was tagged, not released), each release's assets page (names, sizes, SHA-256 digests) and a shallow, blob-less clone for the file list |
| gitlab.com | `/api/v4/projects/{id}/releases`, including subgroups. Assets are read from `assets.links` and from `/uploads/` links in the release description. |
| codeberg.org | `/api/v1/repos/{o}/{r}/releases` |
| git.sr.ht | The `refs/rss.xml` feed and the files attached to each ref |

2.4.2. Other hosts are probed in this order:

1. `/api/v1/version` (Gitea or Forgejo).
2. `/api/v4/projects?per_page=1` (GitLab; `/api/v4/version` needs a token).
3. `/api/v3/meta` (GitHub Enterprise).
4. The page's `<meta name="generator">` tag.

The forge type found is stored with the Source.

2.4.3. **ngit Sources.**

1. AppKata resolves the repository announcement (NIP-34, kind 30617).
2. If one of its `web` or `clone` URLs is on a supported forge, releases come from that
   forge.
3. Otherwise, AppKata uses the release events Zapstore publishes (NIP-82 software
   applications, 2.4.3.1), or an AppKata manifest (2.7).
4. If neither exists, the Source is **track only** and versions come from tags.

2.4.3.1. **Zapstore events.** AppKata reads the event format defined by Zapstore (NIP-82):

| Kind | Event | Used for |
|---|---|---|
| 32267 | Software application | Name, summary, icon, images, platforms. Identified by its `d` tag, the app ID. |
| 30063 | Software release | One version of the app, pointing to its assets |
| 3063 | Software asset | One file: `url` (often a Blossom server), `x` (SHA-256), `version`, `f` platform tags such as `linux-x86_64`, `windows-aarch64`, `darwin-arm64`, and its MIME type and size |

- The legacy kind 1063 (NIP-94 file metadata) is also read, as an asset.
- AppKata finds these events on the repository's relays and on the user's relays (11.1.4).
- Only events signed by one of the repository's maintainers count.
- The asset's `x` hash is a checksum for verification (4.4).

2.4.4. The following hosts have no reliable way to get from a project URL to release files:

- Bitbucket, Gogs, Launchpad, Pagure, Azure DevOps, AWS CodeCommit and Radicle.
- cgit, gitweb and plain git servers.
- Any page not identified by 2.4.2.

They need a direct releases link (2.5), a manifest (2.7), the generic HTML source (2.6.3),
or track only (2.6.1).

2.5. **Direct releases link.** A Source may be added with a releases page URL instead of the
project URL, for example `https://host/owner/repo/releases`. The Source then also records the
project URL, which is used for the README and images.

2.6. **Source settings.** These are optional and set per Source:

2.6.1. **Track only.** AppKata reports new versions but does not install them.

2.6.2. **Release selection:**

- Include prereleases. Draft releases are never used.
- A release-title filter regex.
- A version-extraction regex, with the match group to use.
- Use the release date as the version.
- Fall back to older releases when the newest has no suitable asset.

2.6.3. **Generic HTML source.** For a page that isn't a forge:

1. Collect the page's links and filter them with a regex.
2. Optionally follow a chain of intermediate-link regexes to the download.
3. Optionally extract the version from the page.

When no version string can be found, the version is a pseudo-version: the asset's ETag, or a
hash of its link.

2.6.4. **Asset filter.** A regex for each OS and architecture that overrides automatic asset
selection (4.2). The dialog edits the filter for the current platform and keeps the others.

2.6.5. **Forge type override**, used when detection (2.4.2) gets it wrong.

2.6.6. **Pinned** (9.5.1). Minimum age is a global setting only (9.5.2).

2.6.7. **Source settings dialog.** Opened from a Source's ⋯ menu (7.1.3), or from Add source
before the Source is saved (7.2). It holds, as label-and-hint rows like Settings (11.1):

- **Forge**: Detect automatically (showing what was detected), or "Recommended (GitLab)" when a
  Trust recommends one; GitHub, GitHub Enterprise, GitLab, Forgejo, Gitea.
- Track only and Include pre-releases are yours alone. The Forge and Download filter can come from
  a Trust's AppKata.md (10.3.1): the Forge then shows "Recommended (GitLab)", and the Download
  filter's placeholder and preview use the recommended filter. Leaving them unset keeps later
  recommendations applying.
- **Track only** (2.6.1), a switch.
- **Include pre-releases**: Default (Settings' value, as On or Off), Yes, No.
- **Download filter for <OS> <arch>** (2.6.4): a regex field and a live preview of the file it
  picks from the latest release ("AppKata's choice" when empty), or why nothing matches; an
  invalid regex disables **Save**.
- On Linux, **Flatpak** (an app ID) and **Package** (a package name) (16.1.3), with placeholders
  showing the link AppKata found and where from ("org.zettlr.Zettlr · from mara-dev / foss-picks"),
  and the link check's result (16.1.4).
- **Cancel** and **Save**. Saving records the change in the Audit and syncs the Source again.

The other release-selection settings (2.6.2) and generic HTML Sources (2.6.3) aren't built yet.

2.7. **AppKata manifest.** A project may include an optional `.appkata.toml` in its
repository root. It may declare:

- The app's name.
- Its icon and hero image paths.
- Asset patterns for each OS and architecture.
- The install type, and silent-install arguments.

When present, its values take priority over heuristics. Source settings (2.6) take priority
over the manifest.

2.9. **Origins.** Every app records where it comes from.

2.9.1. An app's origin is its Source, one or more Trusts that list it (10.5), or both. Matching
uses normalized URLs (2.3).

2.9.2. A Trust's apps are never copied into Sources. Installing, updating and uninstalling an
app work the same whatever its origin.

2.9.3. Apps show their origin (5.7.3, 6.1, 12.4):

- A Source origin uses the branch icon and the word "Source".
- A Trust origin uses the Trust's avatar and name, or a count ("2 trusts").

2.9.4. A Source that is also listed by Trusts is flagged on its row with the Trusts it is part
of (7.1.1).

2.9.5. Wherever a Trust is named as an origin, it links to that Trust. Clicking it opens the
Sources perspective with the Trust selected and its Trust Detail panel open (7.6.5). The
**Source** pill opens the Sources perspective scrolled to that Source's row, highlighted for a
few seconds.

2.10. **Errors.** Each Source records its last error, which is shown on its row (7.1.3):

| Error | Shown as |
|---|---|
| `NoReleases` | "No releases found" |
| `NoMatchingAsset` | "No download for Linux x86_64" (for the current platform) |
| `NoVersion` | "Couldn't read a version" |
| `RateLimited` | "Rate limited until 14:32" (the reset time) |
| `Renamed` | "Moved to …", with an **Update URL** button |
| `Unreachable` | "Couldn't reach the host" |

2.11. **AppKata itself.** AppKata updates itself like any other app.

2.11.1. Its own repository (`github.com/MojoKata/AppKata`, kept in one place in the code:
`APPKATA_REPO`) is a **built-in Source**. It is always present, its row shows
a "Built in" chip, and **Remove source** is disabled for it.

2.11.2. AppKata shows in the Apps perspective, with its running version as the installed
version. It has no Uninstall or Open button; the App Detail panel explains why.

2.11.3. **Run as an AppImage**, AppKata adopts its own file on first start: it records it as the
current version (marked as adopted, so it is never deleted by version retention, 4.3.1.5).
Updates install into the install folder (4.3.1) like any portable app. After an update AppKata
shows "AppKata X installed. Restart AppKata to use it." and a **Restart AppKata** button in its
App Detail panel, which starts the new version and quits.

2.11.3.1. **First start of a downloaded AppImage.** When the AppImage runs from outside the install
folder (4.3.1), usually from `~/Downloads`, and AppKata hasn't installed itself yet, it first shows
"Install AppKata?" with the version and where it will go, then:

- **Install** (the default):
  1. Copies itself to `<install folder>/appkata/AppKata-<version>-x86_64.AppImage`, with the
     stable-name link `AppKata.AppImage` (4.3.1.2), and records that copy as the installed version.
  2. Writes `appkata.desktop` in `~/.local/share/applications/` and its icon in
     `~/.local/share/icons/hicolor/` (scalable and 256 px), pointing at the stable link. The entry's
     name matches the window's desktop file name, so the taskbar shows AppKata's icon.
  3. Points the `appkata://` handler (11.3) and the autostart entry (1.7.4), when on, at the stable
     link, so updates never break them.
  4. Starts the installed copy and quits. With **Delete the downloaded file** (checked) it deletes
     the file it was started from.
- **Run from here**: the AppImage runs where it is, adopted as before, without a menu entry; the
  question isn't asked again. **Install AppKata…** in ⋮ asks it later.

The step is recorded in the Audit. `appkata --install-self` does the same without asking (for
scripts and tests). An AppImage already in the install folder is never asked about. AppKata isn't
uninstalled from itself (2.11.2): removing `<install folder>/appkata/`, the desktop entry and the
icon removes it, and the data folder (1.8) stays until deleted.

2.11.4. **Run from source (development, 1.2) or from another build**, AppKata only notifies: the
update shows as usual, and **Update** opens the project's releases page instead of installing.

2.11.5. **Installed with its Windows setup** (15.10), AppKata adopts its installation on first
start, from its own Uninstall registry entry. It downloads and verifies the new
`AppKata-<version>-setup.exe` like any update, then shows the same **Restart AppKata** button.
Restarting runs the setup silently, for the same scope (15.4), and starts the new version when it
finishes.

2.11.6. **Track only** (2.6.1) on AppKata's own Source turns this off on every platform: AppKata
then only notifies, as in 2.11.4.

## 3. App metadata

3.1. For each app, AppKata reads the following from the project and caches it (1.8):

- An icon (small, 32–128 px).
- A high-resolution hero image (about 1280 × 640).
- The README.
- The latest release's notes.

3.2. **Icon.** AppKata uses the first one it finds:

1. The manifest (2.7).
2. AppStream `*.metainfo.xml` (`<icon>`).
3. Fastlane metadata (`fastlane/metadata/**/images/icon.png`).
4. An icon file at the repo root or in `assets/`, `icons/`, `data/` (`icon.svg`, `icon.png`,
   `logo.*`).
5. The owner's avatar.
6. A generated tile: the app's initial on a gradient chosen from a hash of its Source URL.

3.3. **Hero image.** AppKata uses the first one it finds:

1. The manifest.
2. The first AppStream screenshot.
3. Fastlane `featureGraphic.png`.
4. The forge's social-preview image.
5. The first non-badge image in the README.
6. A generated banner from the icon's colours.

3.4. **README.**

- The README is rendered as Markdown.
- Relative links and images are resolved against the repository's raw-file URL at the default
  branch.
- Raw HTML is reduced to a safe subset; scripts, iframes and forms are removed.

3.4.1. The **summary** is the README's first prose paragraph. Headings, badge-only lines,
images and HTML-only blocks are skipped. If there isn't one, the summary is the forge's
project description.

## 4. Installing, updating and uninstalling

4.1. AppKata manages only the apps it installed. Each install is recorded with:

- Its Source and version.
- The asset it came from.
- Its install type (4.3).
- Everything needed to uninstall it.

4.2. **Choosing an asset.** For the current OS and architecture:

1. The Source's asset filter (2.6.4), if set.
2. Otherwise the manifest (2.7).
3. Otherwise the asset file names are matched to the platform's formats in order of
   preference, then to the architecture (`x86_64|amd64|x64`, `aarch64|arm64`, `universal`).
   A filter is applied only if it narrows the list without emptying it.

Format order on Linux:

1. AppImage
2. Flatpak bundle
3. `.deb` (Debian-family) or `.rpm` (Fedora-family)
4. `.tar.gz` / `.tar.xz`

On macOS: `.dmg`, `.pkg`, a zipped `.app`.

On Windows, portable first (15.3): a portable `.zip`, a portable `.exe`, `.msi`, a `.exe`
installer, `.msix`. Only x64 files are chosen.

4.2.1. **Portable or system package.** AppKata decides from the file, without asking:

| File | Install |
|---|---|
| AppImage, `.tar.*` with a program inside, macOS `.app` (in a `.dmg` or `.zip`), Windows `.zip` with a `.exe` inside | Portable (4.3.1) |
| `.deb`, `.rpm`, Flatpak bundle, `.msi`, `.msix`, `.pkg` | System package (4.3.2, 4.3.3) |
| Windows `.exe` | Probed: AppKata reads the file's first megabyte (a ranged download) for Inno Setup, NSIS, WiX and InstallShield markers, which also give the silent-install arguments (4.3.3). Otherwise its name decides (`portable`, `standalone` → portable; `setup`, `installer` → installer). If neither does, it's **unknown** and the install dialog asks (4.9). |

4.3. **Install types.**

4.3.1. **Portable** (AppImage, tarball, zipped `.app`, portable `.zip`). Each app gets its own
folder, `<install folder>/<app>/`, holding its versions side by side: an AppImage as its
versioned file (`LocalSend-1.18.2-x86_64.AppImage`), an archive unpacked into a folder named
after its version (`2.1/`). The install folder is a setting (11.1.4); by default it is:

- `~/bin/apps` on Linux, with command links (4.3.1.3) directly in `~/bin`. Ubuntu, Debian and
  Mint put `~/bin` on the PATH at login when it exists.
- `~/Applications` on macOS: the per-user Applications folder, shown by Finder and Launchpad,
  writable without an admin password.
- On Windows, by who the app is for (15.4): `%LOCALAPPDATA%\Programs` for **Just me** (the
  default), `C:\Programs` for **Everyone**. Neither needs administrator rights.

No elevation is needed. Changing the install folder applies to new installs and updates; apps
already installed stay where they are until they're updated or reinstalled.

4.3.1.1. **App menu.** When on (the default), AppKata adds a launcher: a `.desktop` entry on
Linux, a Start-menu shortcut on Windows (15.5). On Linux, an app its download shows to be a
command-line tool (17.3.3) gets none unless the user or a Trust chose the option for it.

4.3.1.2. **Stable name.** When on (the default), the current version also gets a link with a
stable name next to it: `LocalSend.AppImage` → `LocalSend-1.18.2-x86_64.AppImage`, or
`current` → `2.1/` for an unpacked archive. Launchers and command links point at the stable
name, so they keep working across updates; for a sandboxed app they point at its launcher,
`~/bin/apps/<app>/run`, which runs the current version (17.4). (On Windows, `current` is a directory junction,
which needs no extra rights, 15.5.)

4.3.1.3. **Command links.** When on (the default), AppKata puts a link named after the app
(`localsend`) in the command links folder (default `~/bin`), so the app can be started
from a terminal. AppKata never replaces a file there that isn't a link it made; the install
stops with an error instead. On Windows a command link is a `<app>.cmd` file (15.6).

4.3.1.4. Uninstalling removes the app's folder (every version), its launcher and its links.

4.3.1.5. **Older versions.** After an update, AppKata keeps up to *N* previous versions in the
app's folder (Keep older versions, 11.1.4; default 2) and removes older ones. A kept version
reinstalls instantly, without downloading (5.7.5.1); the user can also remove a kept version
from the version list.

4.3.1.6. **Per-app options.** The three options above (app menu, stable name, command link) are
copied into each app's own settings when it's installed, so changing Settings later doesn't
change apps already installed. An app's options can be changed from **Install options…** (4.9.5).
For a new install the starting values are, in order: the app's own saved options, the options a
Trust recommends for it (10.3.1, yours first), then Settings.

4.3.2. **Flatpak bundle.** Installed with `flatpak install --user`.

4.3.3. **System packages** (`.deb`, `.rpm`, `.pkg`, `.msi`, `.exe` installers, `.msix`).
These need elevation (1.3). Installers run silently when the installer type is recognized:

| Installer | Silent arguments |
|---|---|
| MSI | `msiexec /i … /qn` |
| Inno Setup | `/VERYSILENT /SUPPRESSMSGBOXES` |
| NSIS | `/S` |
| WiX Burn bundle | `/quiet /norestart` |
| InstallShield | `/s` |
| Squirrel | `--silent` |
| Unrecognized | Runs interactively |

On Windows, who an installer installs for, elevation, exit codes and uninstalling are in 15.4,
15.7 and 15.8.

4.4. **Verifying downloads.** Before installing, AppKata:

1. Checks the file against `SHA256SUMS`, `*.sha256` or a forge-provided digest, when one
   exists.
2. Checks a minisign or GPG signature, or a sigstore bundle, when one exists.
3. Reads the OS code-signing status: Authenticode on Windows (15.11); notarization and Gatekeeper on
   macOS.

The App Detail panel shows the result as a chip: **Verified** (a signature checked),
**Checksum** (a checksum only), or **Unverified**. Unverified downloads can still be
installed. A failed check blocks the install and explains why.

4.5. **Foreign installs.** An app is **foreign-installed** when AppKata finds it on the system
but didn't install it. AppKata looks for it in:

- The package database (dpkg, rpm, flatpak).
- On Windows, the places listed in 15.12.
- `/Applications` (by bundle ID).
- The Start menu or `.desktop` entries.

The match uses the manifest's IDs, the AppStream ID, or the app name.

4.5.1. Foreign-installed apps are flagged with an **Installed outside AppKata** badge
wherever they appear: Catalog tiles, the App Detail panel, and Source rows. The badge's
tooltip says where the install was found, and its version if known.

4.5.2. Foreign-installed apps are never listed in the Apps view (6) and are never managed by
AppKata, unless the user adopts one that a package channel matches exactly (16.4.2).

4.5.3. AppKata does not install on top of a foreign install. The Install button is replaced
by a disabled **Installed outside AppKata** button with the note "Uninstall the existing copy
first to manage it with AppKata." When a package channel matches it exactly, the button is
**Adopt** instead (16.4.2).

4.5.4. Adding a Source for a foreign-installed app is allowed, and the row is flagged
(7.1.1).

4.6. **Updating** installs the new version using the same install type, and keeps the
previous version's files until the update succeeds.

4.7. **Uninstalling** reverses what AppKata recorded at install (4.1), after a confirmation.
User data in the home folder is kept.

4.8. **Install progress.**

4.8.1. **Phases**: Waiting, Downloading, Verifying, Installing. One install runs at a time;
**Update all** and further installs queue behind it as "Waiting". The progress shows:

- **Apps row**: the phase ("Downloading 45%", "Verifying…", "Waiting") above a progress bar,
  with "41.4 MB of 92.0 MB · 3.4 MB/s" beside it when the row is wide enough. The Update and
  Uninstall buttons give way to an icon-only **Cancel** (✕; for a waiting app, "Remove from the
  queue").
- **App Detail panel**: the Install or Update button shows the phase and percentage, followed by
  a **Cancel** button, a progress bar, and the size and speed.
- **Catalog tile**: the state mark becomes "Installing 45%".
- **Header bar**: a turning sync icon in the Apps segment while anything installs.

4.8.2. **Resuming.** Downloads go to `<data folder>/downloads/<app>/<file>.part`. If the
connection breaks, AppKata retries up to three times, continuing from where it stopped with a
Range request, as long as the server still has the same file (`If-Range` with its ETag or
Last-Modified date). Otherwise it starts over. A download that still fails, or that was
interrupted by quitting, is kept and resumed the next time the app is installed or updated.
The checksum (4.4) is always checked over the whole file. A complete file that fails its
checksum or its install is deleted.

4.8.3. **Cancelling** is possible until the Installing phase starts. It deletes the partial
download and installs nothing.

4.9. **Install options on the first install.** The first time an app is installed, AppKata
probes the release's files for this computer (4.2, 4.2.1) and shows a dialog only when a choice
is needed to get the app's settings right:

4.9.1. **When it asks:** the app also has a package channel on Linux (16.3.3), or the release has both a portable file and a system package (for
example an AppImage and an `.rpm`), or a Windows `.exe` it couldn't classify. Otherwise it
installs straight away with the preferred file.

4.9.2. **The dialog**, titled "Install <App> <version>":

- One card per kind of file, in order of preference, the first marked **Recommended**. On Linux,
  one card per package channel too (16.3.1). Each
  shows the kind (AppImage, `.rpm` package…), a **Portable** or **System package** chip, what it
  means ("Runs from your install folder; no admin password. Updates replace the file." or
  "Installed for all users with dnf; needs your admin password."), the file name and its size.
- For an unclassified `.exe`: "This file is **A portable program** / **An installer**"; Install
  stays disabled until one is picked.
- For a portable choice: where it will go (`<install folder>/<app>`), and this app's **Add to
  the app menu** and **Command `<app>` in `<folder>`** checkboxes, starting from Settings (11.1.4).
  On Linux, **It is**: "As the download shows" (or "Decide from the download" before it's known), "An
  app with a window" or "A command-line tool" (17.3.3); choosing one moves the Sandbox card with it.
- On Windows, **Install for**: **Just me** or **Everyone on this computer** (15.4), when the file
  supports both; otherwise a note saying which one it does.
- On Linux, for an AppImage or a tarball, the **Sandbox** card: the template the app will run under
  and its summary chips, **Change…** (the Sandbox dialog, 17.3), the reviewers' suggestion with
  **Use theirs** when it differs (17.3.2, 17.11), and for an AppImage the cost of unpacking it (17.7).
- **This app updates itself** (4.10), checked when a Trust says so, with "<Trust> says it updates
  itself", and the hint "AppKata installs it and shows new releases, but leaves updating to the
  app. AppKata can't turn an app's own updater off." — with, when it will run sandboxed, "While it
  runs sandboxed it can't update itself, so AppKata updates it." (4.10.5)
- "You can change this later from the app's ⋯ menu.", **Cancel** and **Install**.

4.9.3. **The answer is saved** with the app (the kind of file, what an `.exe` is, the two
portable options, on Linux the app's kind and the sandbox when the card was changed, and on Windows
who it's for) and recorded in the Audit. Updates use it without asking; if a later release
lacks that kind of file, the preferred one is used.

4.9.4. Apps installed before a choice was saved keep to the kind of file they were installed
from.

4.9.5. The App Detail panel shows how the app is, or would be, installed: a chip such as
"AppImage · portable" or ".rpm · system package". For installed apps, the ⋯ menu has **Install
options…**, which opens the same dialog with **Save** instead of Install; changes apply from the
next update, except the Sandbox card's, which applies at once (17.13).

4.9.6. On Windows, AppKata uninstalls apps installed by their own installer with the uninstall
command it recorded at install (15.8).

4.10. **Apps that update themselves.** Some apps download and install their own updates
(electron-updater, Sparkle, their own updaters), on some or all platforms.

4.10.1. AppKata still finds, installs, tracks and uninstalls them. It doesn't update them: their
state is **Updates itself** (a chip on the Apps row and in the App Detail panel, with "<version>
is out" when a newer release exists), they have no Update button, **Update all** skips them, and
older versions can't be installed from the Versions list.

4.10.2. A portable app that updates itself is installed as `<install folder>/<app>/<App>.AppImage`
(or an `app` folder for archives), with no version folders, kept versions or `current` link, since
the app replaces its own files.

4.10.3. **Whether an app updates itself** is a statement about the app, not a switch: AppKata
can't turn an app's own updater on or off, it only steps back. Unticking it means "this app
doesn't update itself", and AppKata then updates it. It comes from, in order: the app's own setting (the **This
app updates itself** checkbox in the install dialog and Install options…, 4.9), then the
`Auto update` option of the highest-Score Trust that sets one for this platform, as its review for the installed or latest version has it (10.3.3; its
`(<platform>)` line, else its line without one; 10.3.1, 7.6.8).
The App Detail panel says where it came from ("Kenji's app reviews says it updates itself; change
this in Install options.", or "You marked it as updating itself in Install options.").

4.10.4. Turning off an app's own updater from outside (Syncthing's `STNOUPGRADE`, VSCodium's
`update.mode`, Joplin's preference) so AppKata can update it instead isn't supported; it would need
a recipe per app.

4.10.5. **While it runs sandboxed** (17), an app that updates itself can't: its files, and an
AppImage's own file, are read-only. AppKata then updates it as if it didn't update itself — it has
the Update button, Update all includes it, and its next update moves it from the fixed-name layout
of 4.10.2 to version folders — and App Detail and the install dialog say why (17.12). Switched to
Off, it updates itself again.

## 5. Main window

5.1. The main window has four perspectives, chosen from a segmented switcher in the header
bar:

- **Apps**: the default when any app is installed. Shows the apps AppKata installed.
- **Catalog**: the default otherwise. Shows the apps available.
- **Sources**: manages Sources and Trusts.
- **Audit**: the record of key operations (13).

5.2. The design goal is a visually delightful, simple interface: generous spacing, soft cards,
clear typography. Dark is the main design target, and both themes use the design tokens in
`Theme.qml`.

5.2.1. **Design point.** The window is designed for a 1920 × 1080 screen, a 1080p laptop's, with
AppKata maximized on it: whatever that leaves the window, which is 1920 × 1040 beside Windows'
taskbar or Linux Mint's panel at 100% scaling. The screenshots and the tour's layout check are made
at that size, and smaller windows aren't tested.

5.3. **Header bar.** The window draws its own header bar instead of a system title bar. Dragging
it moves the window, and double-clicking maximizes or restores. It holds:

- The app icon and name.
- The perspective switcher. The Apps segment shows a count badge when updates are available.
- A sync indicator (9.2).
- The app menu (⋮).
- On Windows, **Minimize** and **Maximize** (**Restore** when maximized) before the close button
  (15.13).
- A close button, which closes the window to the tray (1.7.1).

5.4. **App menu (⋮).** In this order:

1. **Sync** (9.2), with the time of the last sync as subtext.
2. **Settings…** (11).
3. The theme: Match system, Dark, Light.
4. **Show app log** (14.5).
5. **About AppKata**.
   - **Install AppKata…**, after About, only for an AppImage running from outside the install
     folder that wasn't installed (2.11.3.1).
6. **Close window**.
7. **Quit AppKata**, with its shortcut: Alt+Q (⌘Q on macOS), which works anywhere in the window.

5.4.1. **About AppKata** opens a dialog with the app icon, name and version, a one-line
description, the license (GPL-3.0-or-later), the project link (2.11.1), the platforms it runs on, what it's built with,
and **Check for updates** (which starts a sync, 9.2) and
**Close** buttons.

5.5. Errors and confirmations of finished actions are shown in a short-lived message at the
bottom of the window.

5.6. **App Detail panel.** Clicking an app in Apps or Catalog opens a closable App Detail
panel docked to the right. It is the same panel in both perspectives (5.7).

5.7. **Contents of the App Detail panel.** From top to bottom:

5.7.1. A header row with the "APP DETAILS" label, the pencil button (8.6), a ⋯ menu and the
close button. For installed apps, the ⋯ menu has **Pin** / **Unpin** (9.5)
and **Open project page**.

5.7.2. The hero image (3.3), with the icon overlapping its lower-left corner.

5.7.3. The name, the project host and path, and a **From** row listing the app's origins
(2.9). The row shows a "Source" pill if the app is a Source, and one pill per Trust with that
Trust's avatar and name. Each pill links to its Source row or Trust (2.9.5).

Then the chips that apply:

- Verification (4.4).
- **Installed outside AppKata** (4.5).
- Pinned.
- Track only.
- For a channel install (16): the channel and its publisher ("Flathub · verified"), and who
  updates it (**Updated by the system**, **Not updated automatically**, 16.5.1).

5.7.4. Action buttons, each an icon plus a word:

- Not installed: **Install**; **Adopt** for an adoptable foreign install (16.4.2).
- Installed by AppKata: **Update** (only when an update is available, 9.4), **Uninstall**,
  and **Open**.
- While it installs: the phase in the Install or Update button, and **Cancel** (4.8).

There is no "Add to sources" action for an app that comes from a Trust (2.9.2).

5.7.5. Version information:

- The installed version.
- The latest version and its date.
- Whether the update is held back (9.4).

5.7.5.1. **Versions**: a list of the app's releases, newest first. Prereleases are left out
unless prereleases are on (11.1.2) or one is installed.

- It shows the newest available version, the installed version, and up to 5 versions older
  than the lower of the two.
- The installed version has a "▶" marker on its left, the row is tinted in the success
  colour, and it says "Installed".
- The newest available version has a "★" after it.
- Every other row has small icon-only buttons on the right, labelled by tooltips: **Install**
  (download icon; **Update**, in the accent colour, for the newest when an older one is
  installed). Installing a version older than the newest **pins** the app at that version
  (9.5), so the next sync doesn't upgrade it again; a note under the list says so.
- A version kept in the app's folder (4.3.1.5) has a **Kept** chip; its install button's tooltip
  says it reinstalls without downloading, and a red trash button (tooltip "Remove this version")
  deletes it.
- When there are more versions, a link-style "Show next 5 older" item extends the list by 5.
- A version's files that the last sync didn't read are fetched when it's installed.

5.7.6. **Reviews**: the combined Trust and Rating (10.6), then one row for each Trust that
lists the app. Each row shows:

- The Trust's avatar stack and name. The name links to the Trust (2.9.5).
- That Trust's Trust value, Rating and tags for the app.
- A disclosure arrow that expands the review section (10.3) as rendered Markdown.

The first review with a section starts expanded. The user's own review, when there is one,
comes first and is labelled "Your review".

5.7.7. **Release notes** for the latest version, collapsed after 6 lines.

5.7.8. The **README** (3.4).

5.7.9. The panel scrolls (with a scroll bar) whenever its content is taller than the
window, so long lists of origins, versions and reviews stay reachable.

5.8. **Confirmations.** Every removal asks first, in a short dialog with **Cancel** and a button
named for the action (red for removals). The ones that ask, with their screenshots:

| Action | Where | The dialog says |
|---|---|---|
| Uninstall (4.7) | Apps row trash, App Detail | "<App> <version> will be removed. Your settings and documents in your home folder are kept." |
| Remove a kept version (4.3.1.5) | App Detail → Versions | "This kept version will be deleted…" |
| Remove source (7.3) | Source ⋯ menu | Its own dialog: **Remove and uninstall** / **Remove only** |
| Remove trust (7.5) | Trust Detail | Its reviews leave the Catalog; installed apps with no other origin are listed, with **Keep updating as my sources** |
| Remove an Authority | Trust Detail (red trash) | "Changes signed only by this key will no longer be accepted…" |
| Trust signer / Ignore (10.8) | Trust Detail, new signer | What accepting, or ignoring, their changes means |
| Remove a token, a relay | Settings (11.1.6, 11.1.7) | What AppKata does without it |
| Quit while installing (1.7.3) | ⋮, tray, Alt+Q | The installs that will stop |

## 6. Apps perspective

6.1. The Apps perspective is a vertical scrolling list of the apps AppKata installed (4.1).
Each row shows:

- The small icon (32 px).
- The name.
- The installed version. When an update is available: installed → new version.
- The origin (2.9.3): "Source", the Trust's name, or "Source · 2 trusts".
- For a channel install, its channel and update chip (16.5.1); for an avoided version, a red
  **Avoid** pill (10.6.5).
- Small icon-only buttons for **Update** and **Uninstall**.

6.2. **Sort order.** Apps with an update available come first, and are marked with an accent
stripe, an "Update available" pill, and an accent Update button. Everything else follows,
sorted by name. Within the update group, apps are also sorted by name.

6.3. **Held-back updates.** An update held back by pinning or minimum age (9.4) doesn't count
as available. It doesn't sort the app to the top, and its row shows a muted "Pinned" or
"Held · 3 days left" note instead of an Update button.

6.4. **Title row.**

- "Apps" with "N installed · M updates".
- **Update all**, when updates are available.
- A filter box.

6.5. Clicking a row opens the App Detail panel (5.6). The selected row is highlighted.

6.6. On a row, Update and Uninstall are icon-only buttons with tooltips. In the detail panel
the same icons appear with the words "Update" and "Uninstall".

6.7. **Empty state.** When nothing is installed, the view shows "No apps installed yet" and
a button that opens the Catalog.

## 7. Sources perspective

7.1. **Sources list.** The main area of the Sources perspective is a vertical scrolling list
of Sources.

7.1.1. Each row shows:

- The app's icon and name.
- The Source URL, in monospace.
- **Also in trusts**: when Trusts also list the app (2.9.4), a pill with their avatars and
  "In 2 trusts". Hovering it lists the Trusts by name, each with **Open**. Clicking it opens the
  Trust when there is one, or keeps the list open when there are several (2.9.5).
- The detected forge type.
- The latest version and its date, and the installed version if any.
- State chips: Installed, **Installed outside AppKata**, **Built in** (2.11.1), Pinned, Track only.
- An error, if any (2.10).
- A ⋯ menu.

7.1.2. Apps that only Trusts list (10.5) are not rows here, including installed ones
(2.9.2).

7.1.3. The row's ⋯ menu has:

- **Pin** or **Unpin**.
- **Source settings…** (2.6).
- **Open project page**.
- **Remove source**.

7.1.4. The title row holds, from left to right after the title: a **Filter** box, an
**Explore** button (7.7) and the **+ Add source** button.

7.2. **Adding a Source.** The **+ Add source** button opens a dialog:

1. Enter a URL (2.2).
2. AppKata detects the forge type (2.4) and shows a preview: icon, name, latest version and
   the asset it would choose.
3. The user can open **Source settings** to adjust them.
4. **Add** saves the Source.

If the app is foreign-installed (4.5), the preview says so. If Trusts already list the app, the
preview says "Already listed by desk-collective / reviews". Adding it anyway is allowed and
makes it the user's own Source as well.

7.3. **Removing a Source.**

7.3.1. If AppKata installed the app, the confirmation offers **Remove and uninstall** and
**Remove only**.

7.3.2. **Remove only** warns that the app will stay installed but will get no more updates.
This warning appears only when no enabled Trust lists the app. If one does, the dialog instead
says "Also listed by N trusts, so it stays in the Catalog." AppKata never updates an app that
isn't installed.

7.4. **Pinning** (9.5.1) is set from a Source's ⋯ menu (7.1.3), and for any installed app from
the App Detail panel (5.7.1). Minimum age is set only in Settings (9.5.2, 11.1.3).

7.5. **Removing a Trust.** If an installed app has no other origin, the confirmation warns
that the app will get no more updates. It lists them and offers **Keep updating as my sources**, which
adds them as Sources and then removes the Trust. This is the only case where AppKata turns a Trust's app into a Source,
and only when the user asks.

7.6. **Trust panel.** A collapsible panel on the right side of the Sources perspective lists
the Trusts (10). When it is collapsed, it becomes a narrow rail with a shield icon and a
warning dot if any Trust needs attention.

7.6.1. A **Trust** is a git repository URL. It may be the repository root, or point to a
specific `AppKata.md` file.

7.6.2. **Adding a Trust.** The **+ Add trust** button opens a dialog:

1. Enter a URL.
2. For a root URL, AppKata looks for `AppKata.md` in the root, then in `docs/`. The file must
   exist.
3. AppKata checks that the commits that last changed `AppKata.md` are signed (10.7).
4. It shows each signing key: its type, its fingerprint, and the identity it maps to.
5. The user picks the Trust's **Score** (7.6.8; default 3 stars).
6. The user confirms. The Trust and one **Authority** record per signing key are created.

7.6.3. **Trust rows** form a vertical scrolling list. Each row shows:

- The Trust's name: the repo owner and name, or the file's title.
- Its Score (7.6.8) as 1–5 stars in the accent colour.
- The number of apps it lists.
- When it was last synced.
- Partly overlapping avatars of its enabled Authorities. After four, a "+N" chip is shown
  instead of more avatars.
- A warning indicator when the Trust needs attention: an unsigned change, a commit by an
  unknown signer (10.8), or parse warnings (10.2).

7.6.4. Hovering an avatar shows a popup with details of the signer:

- Name and avatar.
- Email, or NIP-05 for Nostr keys.
- Key type (GPG, SSH or Nostr) and fingerprint.
- When the key was first and last seen.
- Whether it is enabled.

The popup closes by itself about 3 seconds after the pointer leaves.

7.6.5. **Trust Detail panel.** Clicking a Trust row opens a Trust Detail panel at the bottom
of the Trust panel. Its **X** button closes it. It shows:

- The URL and file path.
- Its **Score** (7.6.8), with a 1–5 star picker. The user's own file shows a fixed 5 stars.
- The last verified commit.
- The number of apps listed.
- Parse warnings (10.2).
- A scrolling list of Authorities, each with an avatar, name, key fingerprint, an enable
  switch and a remove button.
- A **Remove trust** button.

7.6.6. A **new signer** (10.8) appears in the Authority list as a pending Authority, marked
"New signer · not trusted", with **Trust signer** and **Ignore** buttons.

7.6.7. **Order.** Wherever Trusts are listed (the Trust panel, the "In N trusts" popup on a
Source row, an app's reviews in the App Detail panel), they are sorted by Score,
highest first, then by name. The user's own file comes first.

7.6.8. **Score.** Each Trust has a Score from 1 to 5 stars (no 0): how much its reviews count in
the combined score (10.6.2). A new Trust starts at 3. The user's own `AppKata.md` is fixed at 5.
Changing a Score is recorded in the Audit (13.3).

7.7. **Explore.** The **Explore** button opens a dialog for finding projects to add as Sources.

7.7.1. The first field is a segmented picker like the perspective switcher: **GitHub**,
**GitLab** (gitlab.com), **Codeberg**, **ngit**, and on Linux **Flathub** and the distribution
(16.2.3). Changing it repeats the search there.

7.7.2. A search box with a **Search** button. Searches use each service's public search:

| Service | Search |
|---|---|
| GitHub | `api.github.com/search/repositories`; when rate-limited, github.com's own search results (JSON) |
| GitLab | `gitlab.com/api/v4/projects?search=`, ordered by stars |
| Codeberg | `codeberg.org/api/v1/repos/search`, ordered by stars |
| ngit | Repository announcements (NIP-34, kind 30617) from the Nostr relays (11.1.4), matched on name, description and identifier |

7.7.3. Each match is a minimal summary: owner and name, description (one line), stars,
language, last activity, and **Archived** or **In your trusts** chips when they apply. Each has
two small icon-only buttons, labelled by tooltips so they don't outweigh the matches:

- **Project page** (open icon): opens it in the browser (tooltip "Open on gitworkshop.dev" for
  ngit).
- **Add source** (plus icon, in the accent colour): opens Add source (7.2) with its URL. When
  the project is already a Source it shows a check, is disabled, and its tooltip says
  "Already a source". For ngit it is disabled until ngit Sources exist (2.4.3), and its tooltip
  says so.

7.7.4. Errors (no network, rate limits, unreachable relays) are shown in the results area.

## 8. Writing reviews

8.1. The user's own `AppKata.md` holds their reviews. Its path is set in Settings (11.1).

8.2. **Choosing the file.** The first time the user writes a review, if no path is set,
AppKata asks for a location:

- The default is `AppKata.md` in the user's home folder.
- A folder can be chosen; AppKata then uses `AppKata.md` inside it.
- If the file doesn't exist, it is created with the Trust table header (10.1).

8.3. **Git repositories.** If the chosen file is in a local git repository that has an
`origin` remote, AppKata offers to commit automatically, and to push automatically. These
choices are saved, and appear as checkboxes in the review dialog (8.4.5).

8.4. **Review dialog.** The review dialog contains:

8.4.1. The app name. It can't be edited.

8.4.1.1. **Version**: which review this is (10.3). A select of the app's releases, newest first,
plus **Any version** (the app review). Each item says "Installed" or "Reviewed" when it is.

- It starts at the installed version, or at the latest release when the app isn't installed. When
  the user has no version reviews of the app and the app isn't installed, it starts at **Any
  version**.
- Choosing a version that has a review loads it ("· editing your review of 1.18.2"). Choosing one
  that hasn't starts a new review: Trust, Rating and Tags start from the values in effect for that
  version (10.3.3), the editor starts empty, and a note under the select says "New review of
  2.0.1. Your review of 1.18.2 (2026-03-04) stays in AppKata.md."
- A review of a version the user never installed is allowed, for warnings such as a compromised
  release (10.3.2).

8.4.2. **Tags**: a multi-select dropdown.

- It lists the predefined tags (10.4), then tags already used in any Trust file.
- The user can also type a new tag. Tags are validated as identifiers (10.4.1).
- Warning tags (`spyware`, `malware`, `ads`, `tracking`, `knownvuln`) are shown in the
  warning colour.

8.4.3. **Trust**: a row of clickable symbols, `–★★★★★`.

- Clicking `–` sets **0, Avoid**, and the row turns the error colour.
- Clicking a star sets 1–5.
- A small × clears the value (no opinion).

The current value is spelled out next to it, for example "3 · Trusted with reservations".

8.4.4. **Rating**: the same control as Trust, but `–` means 0 stars and has no veto meaning
and no special colour.

8.4.4.1. Trust and Rating sit side by side on one line, each with a one-line hint under it
("How far you trust this app and its authors", "How much you like it"); the Avoid warning
replaces the Trust hint. The dialog is wide enough for both (about 780 px).

8.4.4.2. In the Tags box, the tag chips and the input are vertically centred.

8.4.5. A **Markdown editor** for the review's text (the `# <App>` or `## <App>[<version>]` text),
with Edit and Preview tabs.

8.4.5.1. **Include what I have installed**, a checkbox shown when the chosen version is the
installed one. It writes the review's Details (10.3.4) from the install record (4.1): Date,
Platform, Channel, and File and SHA-256, or the Flatpak Commit. Under it, the exact lines in a
small monospace preview. They describe the reviewer's computer and are public once pushed, so the
choice is the user's: it starts checked for apps AppKata installed, unchecked otherwise, and the
last choice is remembered. A review saved without it keeps any Details it already had.

8.4.6. **Auto-commit** and **Auto-push** checkboxes.

- They are shown only when 8.3 applies.
- Auto-push requires auto-commit.

8.4.7. **Settings sub-section.** Saving writes the review's Settings (10.3.1): `## <App>::Settings`
for the app review, `### <App>[<version>]::Settings` for a version review. It always holds the
review's Trust, Rating and Tags; the install and Source options are written there only when they
differ from the values carried from the review before (10.3.3). The dialog doesn't show it, and it
isn't part of the Markdown editor's text. The one exception is the sandbox: a sandbox the user chose
for the app themselves (not one from the reviews or the default) is written whole, as the `Sandbox`
lines a reader's AppKata reads back to the same thing, and the dialog shows it first as one line
("Sandbox: Offline editor, with ~/Notes (read-write)") with **Include my sandbox**, on by default,
since it can name personal folders; what a review can't grant (17.3.1) is left out, and the dialog
says so (review 2, F9).

8.4.8. **Save** and **Cancel** buttons.

8.5. **Saving.**

1. AppKata replaces the review being edited, or adds the new version review after the app's
   other version reviews, in version order. When the review is the app's newest (10.3.3), it also
   updates the app's row in the table. When it adds the first version review and the app review
   has no Trust, Rating or Tags lines of its own, it first writes the table row's values into
   `## <App>::Settings`, so the app review keeps its verdict. Everything else in the file is kept
   exactly as it was.
2. With auto-commit, AppKata commits the file on its own (message: `Review <App>`, or
   `Review <App> <version>`) and checks
   the commit with `git verify-commit`.
3. If the commit isn't signed, AppKata does **not** push. It says so, and offers **Amend with
   signing** and **How to set up signing**.
4. If the commit is signed and auto-push is on, AppKata pushes.

Before Save, if auto-commit is on and git isn't set up to sign commits (`commit.gpgsign`),
the dialog shows a warning in advance.

8.6. **Opening the dialog.** The pencil button in the App Detail panel (5.7.1) opens the
review dialog in both Apps and Catalog. It opens at the version chosen by 8.4.1.1, with that
review filled in when there is one.

## 9. Sync and updates

9.1. Catalog, Sources and Trust data are cached in the database (1.8). Every view shows
cached data straight away, including offline.

9.2. **Sync** refreshes:

- Each Source: releases, metadata, images and README.
- Each Trust: fetch, verify (10.7) and parse.

While Sync runs, the header shows a progress ring with "Syncing 12 / 40". Clicking it shows
the current item and a **Cancel** button.

9.2.1. At most four hosts are fetched at the same time. Rate limits are respected:
`x-ratelimit-reset`, `Retry-After`, and backoff for other failures.

9.2.2. API tokens are kept per host (11.1) and are never sent to any other host.

9.2.3. Sync fetches release information for every app in the Catalog, whether it comes from a
Source or a Trust, so tiles show current versions.

9.3. **Background checks.** While AppKata is running, including in the tray, it syncs
automatically every 6 hours by default (11.1).

When new updates are found, AppKata shows a system notification: "3 app updates available".
Clicking it opens the Apps view.

9.4. **Comparing versions.** A version is newer when it compares greater as semver, after
stripping a leading `v` and taking the version-extraction regex (2.6.2) into account. If
either version isn't semver-like, AppKata compares release dates instead. The same comparison
places reviews on versions (10.3.5); package versions are first mapped to the project's (16.7).

A release with no files attached (a bare tag) is skipped, except for track-only Sources.

An update is **available** when the release is newer than the installed version and all of
these hold:

- The app isn't pinned (9.5).
- The release is at least the minimum age old (9.5).
- The Source isn't track only (2.6.1). A track-only Source shows "New version" without an
  Update button.

9.5. **Pinning and minimum age.** Both belong to the app, whatever its origin (2.9).

9.5.1. A pinned app gets no updates until it is unpinned. AppKata records the version it was
pinned at.

9.5.2. **Minimum age** in days: a release is considered only once it is at least that old.
It is a global setting only (Settings → Updates → Minimum age, 11.1.3; default 0), with no
per-Source or per-app override.

## 10. Trust and the AppKata.md file

10.1. **The Trust table.** The load-bearing content of an `AppKata.md` file is the first
GitHub-flavoured Markdown table whose header row is `App | Source | Tags | Trust | Rating`.
Header matching ignores case and surrounding spaces. A title and introduction may come before
the table.

10.1.1. **App**: the name of the application. Names must be unique within a file.

10.1.2. **Source**: the git URL for the app. Rows are matched to Sources by normalized URL
(2.3).

10.1.3. **Tags**: a comma-separated list of tags (10.4).

10.1.4. **Trust**: how trustworthy the reviewer considers the app.

- `0`–`5`, or `⭐`, `★` or `☆` repeated up to 5 times. `☆` counts as empty.
- **0** tells the reviewer's audience to avoid the app (10.6.1).
- An empty cell means no opinion.

10.1.5. **Rating**: the reviewer's subjective rating, `0`–`5` stars, written the same way as
Trust. 0 is just a low rating. An empty cell means no opinion.

10.2. **Parse warnings.** Invalid rows are skipped and reported as parse warnings on the
Trust (7.6.3, 7.6.5). This includes:

- A duplicate App name.
- A bad tag.
- A Trust or Rating value that isn't 0–5.
- A version review without a version (`## <App>[]`), or two for the same version.
- A `::Details` or `::Settings` sub-section whose heading names no review in the section.
- A platform on a Trust, Rating or Tags line.
- The newest review's Trust, Rating or Tags differing from the table row (10.3.3).

10.3. **Review sections.** Below the table, each `# <App>` heading starts that app's section. The
heading text must exactly match the App column. A row without a section is valid. A section
without a row is ignored, with a parse warning.

A section holds the review of the app as a whole and, optionally, reviews of particular versions
(10.3.2). Only these headings have a meaning; any other heading is part of the review text around
it:

| Heading | Holds |
|---|---|
| `# <App>` | The **app review**: text about the app, for no particular version |
| `## <App>::Settings` | The app review's settings (10.3.1) |
| `## <App>[<version>]` | A **version review**: text about that version (10.3.2) |
| `### <App>[<version>]::Details` | What the reviewer had installed when writing it (10.3.4) |
| `### <App>[<version>]::Settings` | What changes from that version on (10.3.3) |

The file is already `AppKata.md`, so the headings don't repeat "AppKata". A reviewer writes the app
review first, then its settings, then version reviews oldest first; AppKata writes them in that
order, but reading them doesn't depend on it.

```
| App | Source | Tags | Trust | Rating |
|---|---|---|---|---|
| Zettlr | https://github.com/Zettlr/Zettlr | foss, donation, portable, signed | 5 | 4 |

# Zettlr

A Markdown editor for long-form writing, with citations.

## Zettlr::Settings

- Trust: 4
- Rating: 4
- Tags: foss, donation, portable
- Download filter (linux): `x86_64\.AppImage$`
- Auto update (linux): no
- Auto update (windows): yes

## Zettlr[3.5.1]

Release files are now signed, and the Linux AppImage updates itself.

### Zettlr[3.5.1]::Details

- Date: 2026-09-14
- Platform: linux x86_64
- Channel: GitHub release
- File: Zettlr-3.5.1-x86_64.AppImage
- SHA-256: 3c1f…9e07

### Zettlr[3.5.1]::Settings

- Trust: 5
- Tags: foss, donation, portable, signed
- Auto update (linux): yes
```

Here Zettlr 3.5.1 and later have Trust 5, Rating 4 (carried forward) and update themselves on
Linux too; versions before 3.5.1 have Trust 4.

10.3.1. **Settings.** A `## <App>::Settings` sub-section (and a version's `### <App>[<version>]::Settings`)
is a list of `- <Option>: <value>` lines: the review's Trust, Rating and Tags (10.3.3), the app's
recommended install options, the Source settings that describe the app (forge and download filter,
2.6), and its package channels (16.1.3). Track only and Include pre-releases are personal
preferences, so they aren't part of it. A line may name a platform, `- <Option> (<platform>): <value>`,
which overrides the line without one on that platform.

| Option | Value | Meaning |
|---|---|---|
| Trust | 0–5, as in the table | The review's Trust (10.3.3) |
| Rating | 0–5, as in the table | The review's Rating |
| Tags | comma-separated tags | The review's tags, as a whole list |
| App menu | yes / no | Add a launcher (4.3.1.1) |
| Command link | yes / no | A command in the command links folder (4.3.1.3) |
| Stable name link | yes / no | The stable-name link (4.3.1.2) |
| Forge | `github`, `github enterprise`, `gitlab`, `forgejo` (or `codeberg`), `gitea` | The forge type override (2.6.5) |
| Download filter | a regex, in backticks | The download filter (2.6.4) |
| Auto update | yes / no (`Auto updates` is read too) | The app updates itself (4.10) |
| Flatpak | an app ID, optionally after a remote: `org.zettlr.Zettlr`, `flathub org.zettlr.Zettlr` | The app's Flatpak (16.1.3); the remote defaults to `flathub` |
| Debian package | a package name | The app's package on Debian, Ubuntu and Mint (16.1.3) |
| Fedora package | a package name | The app's package on Fedora, RHEL, AlmaLinux and Rocky Linux (16.1.3) |
| Channel | `release`, `flatpak` or `package` | The way to install the app the reviewer recommends (16.3.2) |
| Sandbox | a template name (`standard`, `offline-editor`, `online-app`, `messenger`, `media-player`, `developer`, `cli-tool`, `strict`) or `off` | The suggested sandbox template (17.3) |
| Sandbox folders | paths, comma-separated; `+`/`-` prefixes add to / remove from the template's set; `:ro` marks read-only | Folder grants (17.2, 17.3) |
| Sandbox network | yes / no | Whether the app may use the network (17.2) |
| Sandbox sound | `play`, `record`, comma-separated; `+`/`-` prefixes add to / remove from the template's | Sound (17.8) |
| Sandbox devices | `camera`, `x11`, the same way | Devices (17.2.1, 17.9) |
| Sandbox services | `notifications`, `keep-awake`, `tray`, `media-keys`, `passwords`, `password-service`, the same way | Desktop-services capabilities (17.5.1); a review can't grant the last two (17.3.1) |
| Sandbox app folder | yes / no | The writable app folder (17.7.1) |

Trust, Rating and Tags take no platform; a platform on them is ignored, with a parse warning.
The `Sandbox*` lines are Linux-only; on other platforms they're ignored.

- A **Download filter** is written in backticks so Markdown leaves its `\`, `*` and `_` alone. A
  value that isn't a valid regex, or an unknown forge, is ignored.
- **Recommended Source settings** apply to an app on this platform unless you set your own in
  Source settings (2.6.7), with the same Trust order as the other options (4.3.1.6): yours, then
  the highest Score, then name. They also apply to apps that only Trusts list. A recommended
  Download filter that matches no file here is ignored; your own isn't.
- **Platforms** are `linux`, `win` or `windows`, and `mac` or `macos`, without case. Internally
  there are three: LINUX, WIN and MAC. AppKata writes `linux`, `windows` and `macos`.
- **Which line applies:** within one Settings sub-section, the line for this platform if there is
  one, else the line without a platform. Across reviews, see 10.3.3. With no line at all,
  AppKata's own default applies (Settings, 11.1).
- Unknown options and unknown platforms are ignored.
- **The review dialog** (8.4.7) writes this computer's options: App menu, Command link, Stable
  name link and Forge as lines without a platform, and **Auto update** (when you chose it) and the
  **Download filter** (this platform's, from Source settings) as this platform's lines, e.g.
  `- Download filter (linux): \`x86_64\.AppImage$\``, since their right value depends on the
  platform. It keeps the file's other lines, and drops this platform's lines for the options it
  writes without a platform, so the new values apply here too.

Options are matched without case; unknown ones are ignored. For people who trust the file, the
install options are a recommendation: they become the starting values when they install that app
(4.3.1.6), and the install dialog says who recommended them ("Options recommended by mara-dev /
foss-picks"). Settings sub-sections aren't part of the review text shown in the App Detail panel.

10.3.2. **Version reviews.** A `## <App>[<version>]` sub-section says "I reviewed this version". It
holds for that version and every later one, until a later version review says otherwise.

- The version is the project's own version, as its releases name it (`1.2.3`), without a leading
  `v`. A package's version (`1.2.3-4`, `1:1.2.3-1ubuntu2`) isn't used; the Details say which
  package it was (10.3.4), and package versions are mapped to the project's version (16.7).
- The text is optional. A heading with only a Settings sub-section changes the verdict from that
  version on, for example to warn against a release the reviewer never installed:
  `## xz[5.6.0]` with `- Trust: 0`, then `## xz[5.6.2]` with `- Trust: 4`.
- There are no version ranges: a sequence of version reviews describes them.

10.3.3. **Values over versions.** Each review (the app review, then the version reviews in version
order) has a Trust, Rating, Tags and options:

1. A review's value for an option is its own line, after resolving its platform lines (10.3.1),
   else the value carried from the review before it. A version review sets only what changes.
2. The app review's own lines are those in `## <App>::Settings`. When it has no Trust, Rating or
   Tags line, it takes them from the earliest version review that has one, else from the table
   row.
3. **The table row is the newest review's Trust, Rating and Tags.** If the newest review's Settings
   give different values, the table row wins, with a parse warning: what people read in the table
   is what AppKata uses for the newest versions.
4. AppKata, when it writes a review (8.5), always writes Trust, Rating and Tags into that
   review's Settings and updates the table row when it's the newest, so the fallbacks in 2 matter
   only for hand-written files.

10.3.4. **Details.** A `### <App>[<version>]::Details` sub-section is a list of facts about what the
reviewer had installed. Every line is optional; unknown lines are kept and shown as written.

| Line | Example |
|---|---|
| Date | `2026-09-14`, the day the review was written |
| Platform | `linux x86_64`, `windows x64` |
| Channel | `GitHub release`, `Flathub org.zettlr.Zettlr (verified)`, `Debian package 3.5.1-1`, `Fedora package 3.5.1-2.fc41` |
| File | The release file installed |
| SHA-256 | Its digest |
| Commit | The Flatpak commit installed |

Details never change scores. When the reviewer's SHA-256 or Flatpak commit equals the one about to
be installed, or the one installed, the App Detail panel says "Same file as <Trust> reviewed".

10.3.5. **Which review applies to a version.** For a version *v*, a Trust's review is its newest
version review whose version is *v* or older, else its app review. Versions are compared as in 9.4;
a version that isn't semver-like is placed by its release's date when the release is known, and
otherwise matches only a version review of exactly that version. An installed version that can't be
placed gets the newest review.

10.4. **Tags** describe characteristics of the app that the reviewer wants to surface.

10.4.1. A tag starts with a letter, followed by letters and digits. Tags are case-insensitive
and are stored and shown in lowercase.

10.4.2. Predefined tags:

| Tag | Meaning |
|---|---|
| `foss` | Free and open source |
| `donation` | The author accepts donations |
| `freemium` | Free, with paid features |
| `saas` | An account is required to use the app |
| `spyware` | Collects data about the user without consent |
| `malware` | Harmful or malicious |
| `ads` | Shows advertising |
| `tracking` | Telemetry or analytics, including opt-out ones |
| `nonfreenet` | Relies on a non-free network service |
| `nonfreedep` | Depends on non-free libraries or components |
| `nonfreeassets` | Artwork, sound or data under a non-free license |
| `upstreamnonfree` | The upstream source contains non-free parts that are stripped out |
| `knownvuln` | Has a known, unfixed security vulnerability |
| `unmaintained` | No upstream activity for a long time |
| `archived` | The upstream repository is archived or read-only |
| `nsfw` | Adult content |
| `reproducible` | Reproducible builds have been verified |
| `signed` | Release binaries are signed or have checksums |
| `offline` | Works fully without a network |
| `portable` | Runs without installation |

10.4.3. **Warning tags** are `spyware`, `malware`, `ads`, `tracking` and `knownvuln`. They are
shown in the warning colour wherever tags appear.

10.5. **The Catalog's apps.** The Catalog lists every Source, plus every app listed in the
`AppKata.md` of an enabled Trust whose latest change is verified (10.7). An app that is a
Source and is also listed by Trusts, or is listed by several Trusts, appears once, with all its
origins (2.9).

10.5.1. The user's own `AppKata.md` (8.1) is always treated as an enabled Trust. Its rows
count toward 10.6, without signature checks.

10.5.2. Trusts are added only by the user. There is no default or starter Trust, and AppKata
works with Sources alone and no Trusts.

10.6. **Combined score** for an app, across the enabled Trusts that list it:

10.6.1. **Veto.** If any enabled Trust gives the app a Trust of 0, the app is **vetoed**.

10.6.2. Otherwise, its Trust is the average of the Trust values given, and its Rating is the
average of the Rating values given, both weighted by each Trust's Score (7.6.8): a 5-star
Trust's review counts five times as much as a 1-star Trust's. Score doesn't affect the veto. Both are shown to one decimal place, with the number of
reviewers.

10.6.3. An app that no Trust reviews is **Unreviewed**. It has no score, and it is not
vetoed.

10.6.4. **AppKata itself** (2.11) always has a combined Trust of 5: you're running it. Its Trusts'
Trust values, including a 0, don't change that; its Rating is combined as usual.

10.6.5. **Scores for a version.** Each Trust's Trust, Rating and tags are those of its review for a
version (10.3.5), and are combined as above for that version:

- **Catalog** tiles and the App Detail panel of an app that isn't installed: the latest release,
  the one **Install** would install. Vetoed apps (12.6) are those vetoed for it.
- **Apps** rows and the App Detail panel of an installed app: the installed version. When it's
  vetoed, the row has a red **Avoid** pill and the panel a red banner, "A trusted reviewer says to
  avoid the version you have (5.6.1)", with the reviewer, the version their review starts at, and
  **Update to 5.6.2** when a newer release isn't vetoed. A sync that newly vetoes an installed
  version shows a system notification, "A trusted reviewer says to avoid xz 5.6.1".
- An **update** to a vetoed version shows "Avoid" next to it and is left out of **Update all**.
- The **Versions** list (5.7.5.1): each version's combined Trust, and avoided versions dimmed.
- Each review row in the App Detail panel (5.7.6) says which version the review is of ("reviewed
  2.0.1"), and its earlier reviews are under a collapsed "Earlier reviews (2)".

10.7. **Signed changes.** Every commit that changed `AppKata.md` since the last verified
commit must be signed by an enabled Authority of the Trust. Accepted signature types:

- **GPG**, verified against the Authority's public key.
- **SSH**, verified with an `allowed_signers` file that AppKata builds from the Authorities.
- **Nostr**, for ngit Trusts, where the repository state event is signed by a maintainer's
  npub.

X.509 is not supported. Signatures are verified locally; the forge's "Verified" badge is not
used. SSH signatures are checked by AppKata itself (Ed25519, RSA, ECDSA P-256), because
`ssh-keygen -Y` needs OpenSSH 8.2+ and some supported systems ship older ones.

10.7.1. When a Trust is added (7.6.2), the commit that last changed `AppKata.md` must be
signed. Its signing keys become the first Authorities, trusted on first use after the user
confirms them.

10.7.2. **Rewritten history.** If the last verified commit is no longer an ancestor of the
branch, for example after a force-push, the change is treated as unsigned.

10.8. **Unsigned changes and unknown signers.**

- A change that is unsigned, or signed by a disabled or removed Authority, is **not applied**.
  AppKata keeps using the last verified version, and the Trust row shows a warning.
- A change signed by a key that isn't an Authority is also not applied. The key appears in
  the Trust Detail panel as a pending new signer (7.6.6). Choosing **Trust signer** adds it as
  an Authority and applies the change.
- Disabling an Authority doesn't affect commits verified before it was disabled.

10.9. **Authority identities.**

- **Nostr keys**: the kind-0 profile gives the name, avatar and NIP-05.
- **GPG and SSH keys**: the key's user ID or the commit author gives the name and email; the
  avatar comes from the forge account that owns the key where the forge exposes it, otherwise
  an identicon generated from the fingerprint.

## 11. Settings

11.1. **Settings** (from ⋮) is a scrolling dialog. Each setting is a row: its name and a short
hint on the left, its control on the right. Every control (switches, fields, folder buttons,
selects, list buttons) ends on the same right edge. Changes apply immediately; the dialog has only a
**Close** button. The groups, in order:

11.1.1. **General**: the theme (Match system, Dark, Light; the same choice as in ⋮), **Start in
the tray at login** (1.7.4; an autostart entry that runs `appkata --tray`; on Windows, 15.14), and **Open
appkata:// links** (11.3).

11.1.2. **Reviews**: the path to the user's `AppKata.md` (a text field and an icon-only folder button, tooltip "Browse…"), and the
default auto-commit and auto-push choices (8.3; push requires commit).

11.1.3. **Updates**:

- Check for updates: Off, Every hour, Every 6 hours, Every day.
- Notify me about updates.
- Include pre-releases, for apps without their own setting.
- Minimum age in days, for every app (9.5.2). This is the only place it is set.

11.1.4. **Portable apps** (4.3.1): the install folder (with an icon-only folder button, tooltip "Browse…"), Add to the app menu,
Stable name for the current version, Command links, the command links folder, and **Keep older
versions** (per app; default 2). These are the defaults copied into each newly installed app
(4.3.1.6).

On Windows the group also has **Install apps for** (Just me, Everyone; 15.4), and two install
folders in place of one: **For me** (default `%LOCALAPPDATA%\Programs`) and **For everyone**
(default `C:\Programs`). The command links folder defaults to `%LOCALAPPDATA%\AppKata\bin`
(15.6).

11.1.4.1. **List settings** (tokens, relays) look the same: each item has a red, icon-only
trash button (tooltip "Remove") on the right; the add row ends with an icon-only "+" button
(tooltip "Add token", "Add relay"), enabled once the fields are valid. These buttons line up on
the right edge of the dialog.

11.1.5. **Sandbox** (Linux; 17.15): system support with **Set up…** and **Repair…**, the warnings
for the session (17.9), the default template for new apps by kind, following the reviewers'
suggestions, the review badge, the built-in templates and the sandbox home folders.

11.1.6. **Accounts and tokens**: one row per host with a token, showing only its last four
characters and a trash button; then a host field, a hidden token field and a "+" button. The help
text explains that tokens raise rate limits (GitHub allows 60 requests an hour without one),
are only sent to their own host, and are never exported.

11.1.7. **Nostr relays** (1.5): the relay list, each with a trash button, and a field and "+"
button to add one (`wss://…`).

11.1.8. **Data**: where AppKata keeps its files (1.8), each with an icon-only folder button
(tooltip "Open folder"):

- **Database**: the SQLite file.
- **App log**: the log folder (14.3), and an icon-only external-link button (tooltip "Show")
  that opens the log (14.5).
- **Import and export** (11.2): **Import…** (download icon) and **Export…** (floppy-disk icon).

11.2. **Import and export.** Sources (with their settings), pins, Trusts (with
their Authorities and Scores) and settings are exported to a JSON file. Tokens and the review file path
are not exported. Importing adds what isn't already there and leaves existing Sources and
Trusts as they are. An imported Trust is accepted only if the commit that last changed its
`AppKata.md` is signed by one of its exported Authorities. A plain text file of URLs (one per
line, `#` for comments) can also be imported as Sources. Import and export are recorded in the
Audit (13).

11.3. **Deep links.** `appkata://add/<url-encoded source URL>` opens the Sources perspective and
the Add Source dialog with the URL filled in. On Linux, **Open appkata:// links** registers
AppKata as the desktop's handler for `appkata:` links; on Windows, see 15.14.

## 12. Catalog perspective

12.1. The Catalog should look like a cool, modern app store for browsing the available apps
(10.5).

12.2. **Title row.**

- "Catalog" with the app count.
- A **search box** that matches name, summary, tags and Source URL.
- **Tag filter chips**: the most-used tags, plus **More…**, which opens a popup of every tag
  ("All tags · 10"). A tag chosen there replaces "More…" as the chip's label while it filters.
  Clicking a tag chip on a tile, in a tile's tags popup or on a review filters the Catalog by
  that tag.
- A **sort** select: Trust, Rating, Recently updated (newest release first), Name. The default is Trust (highest
  first), then name. Every sort falls back to name for ties. Unreviewed apps sort after
  reviewed ones when sorting by Trust or Rating.

12.3. **Tiles.** Apps are tiles that flow left to right and wrap. Tiles are responsive: a tile is
designed at 300 × 210 px and scales with its width, keeping that aspect ratio, between 280 px and
2× that size.

12.4. **Tile contents.**

- The icon (56 px).
- The name and latest version.
- The origin (2.9.3): the branch icon for a Source, and the avatars of the Trusts that list
  the app.
- The summary (3.4.1), up to three lines.
- At the bottom: the combined Trust (shield) and Rating (stars) with the reviewer count, or
  "Unreviewed"; the app's tag chips (12.4.1); and a state mark: **Installed**, **Update**, or
  **Installed outside AppKata**.

12.4.1. **Tags on a tile.**

- Tags are shown in the order the Trusts list them, for as many as fit on the footer line
  beside the Trust badge.
- If they don't all fit, the tile drops tags from the end until there is room for a small
  **›** button at the end of the line.
- Hovering the button, or focusing it with the keyboard, shows a popup listing all of the
  app's tags with the count ("5 tags"). Warning tags (10.4.3) keep their warning colour. The
  popup closes when the pointer leaves it or focus moves away.

12.5. Clicking a tile opens the App Detail panel (5.6). The selected tile is outlined in the
accent colour.

12.6. **Vetoed apps** (10.6.1) are not shown unless they match the current search text.
Clearing a search hides them again.

12.6.1. When shown, a vetoed tile is dimmed and has a red **Avoid** badge with a warning icon.
The App Detail panel shows a red banner: "A trusted reviewer says to avoid this app".

12.6.2. If the search also matches vetoed apps, a line at the end of the results says
"N apps hidden by trusted reviewers are shown because they match your search."

12.7. **Empty state.** With no Sources and no Trusts, the Catalog shows "Add a source or a
trust to fill your catalog", with **Add source** and **Add trust** buttons.

## 13. Audit

13.1. The **Audit** perspective is an immutable record of key operations, newest first.

13.2. It is stored in the app's SQLite database (1.8). Entries can only be added: the database
refuses every change or deletion (triggers), and the UI offers neither.

13.3. **What's recorded.** Each entry has a time, an actor, a kind, an action, a subject (the
app, Source, Trust, Authority or file), the URL when there is one, and details.

- The actor is **You** for what the user does, **Sync** for what AppKata does on its own, or
  **System** for changes AppKata found made by something else (16.9).
- **Apps**: installed, updated, uninstalled (with the version and file), how to install chosen (4.9), pinned, unpinned, and installs of older versions (pinned); a kept version removed; AppKata's own AppImage adopted as installed (2.11); the sandbox set or kept, with the template and level (17.16); an app sandboxed by a setup, an update or AppKata's start once the system can (17.13); a launcher rewritten at AppKata's start, with a hash of its text (17.4).
- **Sources**: added, removed (and whether the app was uninstalled too), settings changed; Sources
  kept from a removed Trust.
- **Trusts**: added (with their Score), removed, Score changed; Sync applying newly verified changes (commit, app count) and
  refusing a change (unsigned, disabled authority, bad signature, rewritten history).
- **Authorities**: added with a Trust, enabled, disabled, removed; a new signer found by Sync,
  approved or ignored.
- **Reviews**: saved (Trust, Rating, tags, commit, signed, pushed); a commit re-signed.
- **Settings**: the review file chosen; API tokens set or removed (never the token itself); `appkata://` links registered (11.3); settings imported or exported; system sandbox support enabled, or put off with Not now, and AppKata's AppArmor profile removed by Repair (17.10, 17.10.2).

Failed operations aren't Audit entries; they're in the App log (14).

13.4. **Layout.** A title with the entry count and "newest first", a filter box
(subject, action, details, URL) and kind chips (All, Apps, Sources, Trusts, Authorities,
Reviews, Settings). Entries are grouped under day headings ("Today", "Yesterday", then the
date). Each row shows an icon for the kind, a sentence ("You installed **KeePassXC**"), detail
chips, the URL, a **You** or **Sync** pill and the time.

13.5. The list is virtualized and loads 100 entries at a time as it scrolls; "Start of the
audit" marks the end.

## 14. App log

14.1. A fixed-size text history of background activity: syncs, downloads, installs, Trust
checks, and anything that went wrong.

14.2. Error messages, Qt and QML warnings, and the output of commands AppKata runs (git,
package managers, flatpak, pkexec) go here for diagnostics. Secrets (API tokens) never do.

14.2.1. An app AppKata launches (4.3.1.1) writes its own output to `logs/apps/<id>.log` in the
same folder, keyed by the install's own id (17.6), so two apps with one name each have their own
(appended under a dated line at each launch; past 2 MB the file becomes `<id>-prev.log`), and its
last lines are copied into the App log when it exits. A log an older AppKata kept by name moves to
its install's id at start, unless two installs share the name (review 2, F14: they shared one log). A sandboxed app
started from the app menu, a file manager or a shortcut writes its launcher's errors to the same file
(the entry passes `--appkata-menu`; from a terminal or a script, stderr stays the caller's), so a
refused launch leaves the same trace whichever way it was started. If it fails to start — the
launcher's own refusal (a sandbox that couldn't start, an AppImage that didn't unpack, a command-line
tool refusing its folder, 17.3.3) however long the unpacking took, or the program exiting non-zero
within seconds of the launcher starting it — the user is told so, with the last line of output,
instead of nothing happening.

14.3. The files are in the platform's log folder (1.8): `~/.local/state/appkata` on Linux
(`$XDG_STATE_HOME`), `%LOCALAPPDATA%\AppKata\Logs` on Windows, `~/Library/Logs/AppKata` on macOS.

14.4. There are two files: **AppKata.log** (current) and **AppKata-prev.log** (previous).

14.4.1. When AppKata.log would pass 2 MB:

1. AppKata-prev.log is deleted, if it exists.
2. AppKata.log is closed and renamed to AppKata-prev.log.
3. A new AppKata.log is opened for writing.

14.5. **Show app log** in the ⋮ menu (5.4):

14.5.1. Joins the two files, previous first, into `AppKata-log.txt` in the system's temp folder.

14.5.2. Opens that file in the system's text editor (the desktop's default for text files on
Linux, `open -t` on macOS, Notepad on Windows).

## 15. Windows

15.1. AppKata runs on Windows 10 22H2 (fully updated), x64 only; Windows 11 isn't tested yet (1.1). This section
collects what is specific to Windows. The sections it refers to still apply.

15.2. **Elevation.** AppKata runs without administrator rights. It starts every installer and
uninstaller through the shell (`ShellExecuteEx`), as Explorer does, and waits for its exit code:
an installer whose manifest needs administrator rights then gets the UAC prompt, and with the
Mark of the Web (15.11.1) SmartScreen checks it. When AppKata itself asks for administrator rights
(15.4, 15.7, 15.8), it uses the `runas` verb. Declining the prompt cancels the action.
AppKata never starts a per-machine installer through `CreateProcess`, where it would fail (error
740), or for a silent `.msi`, fail without asking.

15.3. **Choosing a file.** Portable files come first (4.2): a `.zip` with a program inside, a
portable `.exe`, then `.msi`, a `.exe` installer and `.msix`. When a release has both a portable
file and an installer, the install dialog asks, with the portable file **Recommended** (4.9.1).

15.4. **Who an app is for.** Every app installed on Windows is for **Just me** or for
**Everyone on this computer**.

15.4.1. It is a per-app setting, like the portable options (4.3.1.6). Its starting value is
**Install apps for** in Settings (11.1.4; default Just me). The install dialog (4.9.2) shows it
when the file supports both. **Install options…** can change it later: AppKata reinstalls the
installed version in the new place, then removes the old copy. Trusts don't recommend it
(10.3.1), because it describes this computer, not the app.

15.4.2. What each means:

| | Just me | Everyone |
|---|---|---|
| Portable apps | `%LOCALAPPDATA%\Programs\<app>\` | `C:\Programs\<app>\` (15.4.3) |
| Start-menu shortcut | The user's Start menu | The all-users Start menu; UAC at install and uninstall only |
| Installers | The per-user arguments (15.7.2) | The per-machine arguments, elevated |
| `.msix` | Always | Not offered |
| Command links (15.6) | The user's | Still only the installing user's; others use the Start menu |

Both folders are settings (11.1.4).

15.4.3. **Protecting `C:\Programs`.** By default every user may change what is created at the
root of the system drive, so another account could replace a program that others then run.
AppKata prevents this without a UAC prompt, because the owner of a folder may set its
permissions:

1. When AppKata creates `C:\Programs`, it turns off inherited permissions and grants:
   Administrators and SYSTEM full control; Users read, run, and create folders (this folder
   only); CREATOR OWNER full control of subfolders.
2. Each app folder grants the installing user, Administrators and SYSTEM full control, and
   Users read and run.
3. Before installing or updating an app for everyone, AppKata checks both folders' owner and
   permissions. A folder owned by the user or by Administrators whose permissions were loosened
   is set right again. A folder owned by another account is refused: the install stops with an
   error naming the folder, and installs nothing.

15.4.4. Another user's AppKata sees an app installed for everyone as **Installed outside
AppKata** (4.5), through its all-users Start-menu shortcut.

15.5. **Shortcuts and the stable name** (4.3.1.1, 4.3.1.2).

- `current` is a directory junction to the current version's folder; junctions need no extra
  rights. A portable `.exe` is placed in its own version folder, so every portable app on
  Windows has a `current`.
- The Start-menu shortcut is a `.lnk` directly in the Start menu's `Programs` folder (Windows
  11 shows only one level of folders), named after the app. It points at the program inside
  `current`, with the program's own icon and its folder as the working directory. It is made at
  install and doesn't change on updates. It sets no AppUserModelID: one the app doesn't use
  itself would break pinning and grouping on the taskbar.
- An app that updates itself (4.10.2) has an `app` folder and no junction; its shortcut points
  into that folder.

15.6. **Command links** (4.3.1.3) are `<app>.cmd` files: a first line `@rem made by AppKata`, then
`@"<install folder>\<app>\current\<Program>.exe" %*`. The default command links folder is
`%LOCALAPPDATA%\AppKata\bin`.

- When AppKata writes the first one, it adds the folder to the user's PATH (`HKCU\Environment`,
  then a `WM_SETTINGCHANGE` broadcast; terminals opened afterwards see it). When it removes the
  last one, it removes the folder from the PATH.
- AppKata never replaces a `.cmd` it didn't write (one without that first line).

15.7. **Installers** (4.3.3).

15.7.1. The installer type comes from probing (4.2.1): markers in the file's first megabyte, in
ASCII or UTF-16 (Inno Setup 6.3 and later keep only `InnoSetupLdrWindow` and a jrsoftware.org
link), and the release's other files: `latest.yml` marks electron-builder's NSIS, and a
`RELEASES` file or `-full.nupkg` packages mark Squirrel. An app installed by Squirrel is marked
as updating itself (4.10) unless the user unticks it.

15.7.2. **Arguments for each scope** (15.4). Where the installer can't choose, the dialog's
**Install for** row says what it does ("This installer installs for everyone") instead of
offering a choice:

| Installer | Silent | Just me | Everyone |
|---|---|---|---|
| MSI | `msiexec /i … /qn /norestart` | `ALLUSERS=2 MSIINSTALLPERUSER=1` | `ALLUSERS=1`, elevated |
| Inno Setup | `/VERYSILENT /SUPPRESSMSGBOXES /NORESTART` | `/CURRENTUSER` | `/ALLUSERS`, elevated |
| NSIS by electron-builder | `/S` | `/currentuser` | `/allusers`, elevated |
| Other NSIS, WiX Burn, InstallShield | `/S`, `/quiet /norestart`, `/s` | The installer decides | The installer decides |
| Squirrel | `--silent` | Always | Not offered |
| `.msix` | `Add-AppxPackage` | Always | Not offered |

An Inno Setup installer accepts `/CURRENTUSER` only when it was built to allow it. AppKata
learns the real scope from where the app's Uninstall entry appears (15.8.1) and records that. An
installer that turns out to need administrator rights is started again, elevated (15.2).

15.7.3. **Exit codes.**

| Code | Meaning | AppKata |
|---|---|---|
| 0 | Done | Installed |
| 3010, 1641 | Done; Windows must restart | Installed; a toast says "Restart Windows to finish installing <App>" |
| 1602, 1223 | Cancelled (1223: the UAC prompt was declined) | Cancelled; nothing recorded |
| 1618 | Another installation is running | "Another installation is running. Try again when it's finished." |
| Other | Failed | The error, with the installer's output in the App log |

15.7.4. **`.msix`** installs with `Add-AppxPackage` for the current user, with no UAC prompt. A
package whose signer Windows doesn't trust can't be installed, and AppKata says so. The
package's full name is recorded for uninstalling.

15.8. **Uninstalling installer apps** (4.9.6).

15.8.1. AppKata reads the Uninstall registry keys (HKCU, and HKLM in its 64-bit and 32-bit
views) before and after running an installer. The entry that is new or changed is recorded with
the install (4.1): its key, `DisplayName`, `DisplayVersion`, `QuietUninstallString`,
`UninstallString`, and for MSI the product code. Its hive gives the real scope (15.4). If no
entry appears, the install still succeeds, with a note that AppKata can't uninstall it.

15.8.2. Uninstalling runs `QuietUninstallString`, else `UninstallString` with the silent
argument for its installer type, else `msiexec /x {product code} /qn`. It is elevated when the
entry is under HKLM. The uninstall succeeds when the entry is gone; AppKata waits up to a
minute for that, since NSIS uninstallers finish from a copy of themselves. `.msix` packages are removed
with `Remove-AppxPackage`.

15.8.3. After each update AppKata reads `DisplayVersion` again. If it doesn't match the release,
the App Detail panel says "Windows reports version <X>".

15.9. **Files in use.** Windows can't replace or delete a running program's files. Before the
Installing phase of a portable app's update, switching to or removing a kept version, or
uninstalling a portable app, AppKata checks for processes running from the app's folder. If there
are any, it shows "Close <App> to continue" with **Try again** and **Cancel**. AppKata never
stops the app itself. Installers handle this themselves.

15.10. **AppKata's own setup** (1.6) is built with Inno Setup, `PrivilegesRequired=lowest`, with
overrides allowed:

- Just me by default, into `%LOCALAPPDATA%\Programs\AppKata`; or Everyone, into `Program Files`.
- It refuses a Windows older than Windows 10 22H2 (`MinVersion=10.0.19045`, 1.1). It doesn't
  check the updates installed.
- It adds the Start-menu shortcut (with AppKata's AppUserModelID, 15.14) and the `appkata://`
  handler.
- Its uninstaller removes AppKata, offers to remove `%LOCALAPPDATA%\AppKata`, and leaves the
  apps AppKata installed in place, saying so.
- Updates: 2.11.5.

15.11. **Authenticode** (4.4). AppKata checks `.exe`, `.msi` and `.msix` downloads with
Windows' own check (`Get-AuthenticodeSignature`, which uses `WinVerifyTrust`).

- A valid signature makes the chip **Verified · <signer>**.
- A signature that doesn't match the file (it changed after signing) blocks the install, like a
  failed checksum.
- An unsigned file, or one signed with a certificate Windows doesn't trust (a self-signed one,
  common for small FOSS projects), is judged by its checksum alone.

15.11.1. **Mark of the Web.** **Mark downloads as from the internet** is a per-app setting, off by
default, in **Install options…** (4.9.5) on Windows. Trusts don't recommend it (10.3.1).

- When it's on, AppKata gives each download the mark a browser would (a `Zone.Identifier` stream
  with `ZoneId=3` and the download's URL). It copies the mark to every file it unpacks from an
  archive, as Explorer does. It starts installers, and opens the app, with `ShellExecuteEx`, so
  that SmartScreen checks them. If the user chooses not to run a file at SmartScreen's warning,
  the install is cancelled.
- When it's off, downloads carry no mark, and AppKata's own checks (4.4, 15.11) are the only
  ones.
- Changing it applies from the next install or update, and is recorded in the Audit (13.3).

15.12. **Foreign installs** (4.5) on Windows are found in:

- The Uninstall registry (HKCU, and HKLM 64-bit and 32-bit), which also covers winget installs.
- Store and `.msix` apps (`Get-AppxPackage`).
- Scoop (`~\scoop\apps`) and Chocolatey (`%ProgramData%\chocolatey\lib`).
- Start-menu shortcuts, the user's and all users'.

Entries AppKata recorded itself (15.8.1) aren't foreign.

15.13. **The window** (5.3). The header bar also has **Minimize** and **Maximize** (**Restore**
when maximized) before the close button, in Windows' usual order and shapes. The window behaves
like any other Windows window:

- Dragging it to a screen edge snaps it (Aero Snap). Hovering over Maximize shows Windows 11's
  Snap Layouts, because the button answers `WM_NCHITTEST` as `HTMAXBUTTON`.
- Its edges resize it, and it keeps its size when moved between monitors with different scaling.
- Double-clicking the header bar maximizes or restores it, and Alt+Space opens the system menu.

Closing still leaves AppKata in the tray (1.7.1).

15.14. **Registering with Windows.** All of this is under HKCU and needs no UAC prompt.

- **Start in the tray at login** (1.7.4): an `AppKata` value under
  `Software\Microsoft\Windows\CurrentVersion\Run` that runs `"…\appkata.exe" --tray`. Settings
  shows the value's real state, because Task Manager can also turn it off.
- **Open appkata:// links** (11.3): `Software\Classes\appkata`, with `URL Protocol` and
  `shell\open\command` set to `"…\appkata.exe" "%1"`. The setup registers it (15.10); the
  setting does it for other builds.
- **Notifications** (9.3): AppKata sets its AppUserModelID, `AppKata.AppKata`, at startup, the
  same as on its Start-menu shortcut, so its toasts are shown as AppKata's. Clicking an update
  toast, including one in the Action Center, opens the Apps view.

15.15. **git and gpg** (1.4). When git is missing, AppKata suggests `winget install Git.Git`.
AppKata looks for `gpg` on the PATH, then in Git for Windows' `usr\bin` (found from
`git --exec-path`).

15.16. **Files and processes.**

- App folder and file names avoid the names Windows reserves (`CON`, `PRN`, `AUX`, `NUL`,
  `COM1`–`COM9`, `LPT1`–`LPT9`, with any extension), and trailing dots and spaces, by adding `_`.
- Names are compared without case, so two apps can't get the same folder.
- Paths longer than 260 characters use the `\\?\` prefix, so deep archives and Trust clones work
  without Windows' long-path setting.
- An app AppKata opens is started detached (`DETACHED_PROCESS`), so it keeps running when
  AppKata quits.

15.17. **TLS certificates** are checked by Windows itself (`truststore`). Python's own check sees
only the root certificates already in Windows' store, while Windows fetches missing roots when
it needs them, so downloads from some hosts (GitHub's file host among them) would fail.

15.18. **The Visual C++ run-time.** Some apps need Microsoft's Visual C++ run-time
(`vcruntime140.dll`, `vcruntime140_1.dll`, `msvcp140.dll`). Mostly these are portable `.zip`
files, such as Rust and C++ command-line tools; installers usually bring the run-time
themselves. One package covers every app built with Visual Studio 2015 to 2022: the
**Microsoft Visual C++ 2015–2022 Redistributable**, x64. Any copy at least as new as the app's
works, so the latest serves all of them. The older run-times (2005–2013) aren't handled.

15.18.1. **Detecting it.** After unpacking a portable app, AppKata reads the import table of each
`.exe` and `.dll` in it. When one imports a run-time DLL that isn't in the app's own folder, the
app needs the run-time, and AppKata records that with the install. Trusts don't declare it in
AppKata.md: the app's own files decide.

15.18.2. **Showing it.** An app that needs it has an **MSVCRT** chip (tooltip "Microsoft Visual
C++ Run-time") on its Apps row and in the App Detail panel. The chip is in the warning colour
when the run-time is missing from this computer, and clicking it then offers to install it
(15.18.3). AppKata finds an installed copy from the registry
(`HKLM\SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64`, `Installed` and `Version`), or
from `vcruntime140.dll` in `System32`.

15.18.3. **Installing it.** When an app that needs the run-time is installed and the run-time is
missing, AppKata offers **Install the Visual C++ run-time**. It downloads Microsoft's
`vc_redist.x64.exe` (`https://aka.ms/vs/17/release/vc_redist.x64.exe`), checks its Authenticode
signature (15.11; the signer must be Microsoft Corporation), and runs it with
`/install /quiet /norestart`, elevated; exit code 1638 (a newer copy is already installed) counts
as done. Installing it is recorded in the Audit (13.3). The run-time installs only for everyone, so this one step
asks for administrator rights even for an app that is Just me (15.4). The dialog says why. Exit
codes are read as for other installers (15.7.3). This normally happens once per computer.

15.18.4. **Never removed.** Other software shares the run-time, so AppKata doesn't track it as an
app, never uninstalls it, and doesn't copy its DLLs into app folders.

## 16. Package channels (Linux)

AppKata should be one place to find, install and review apps, and still get along with the
distribution's own updates and app stores (GNOME Software, KDE Discover, Mint's Software Manager).
This section adds Flatpak remotes and the distribution's repositories as ways to install an app.
It is built and tested in containers (`scripts/test-channels.sh`), except installing an older
Flatpak commit from the Versions list (16.5.7), which isn't built yet.

16.1. **Channels.**

16.1.1. An app is still its git project URL (2.1); what Trusts review doesn't change. A **channel**
is a way to install it:

| Channel | Identified by | Built by | Signed by |
|---|---|---|---|
| **Release** (2.4, 4.2) | A file in the project's release | The project | The project, sometimes (4.4) |
| **Flatpak** | A remote (`flathub`) and an app ID | Flathub's build servers, from a manifest kept by the project (verified) or by someone else | The remote's key |
| **Package** | A package name in the distribution's repositories: apt on Debian, Ubuntu and Mint; dnf on Fedora, RHEL, AlmaLinux and Rocky Linux | The distribution's packagers, often with patches | The distribution's keys |

An app may have all three. Channels exist on Linux only.

16.1.2. A channel that comes from a repository AppKata didn't add (a PPA, a vendor's apt
repository, a Flatpak remote other than Flathub) is shown with that repository's name. AppKata
never adds repositories itself, except Flathub (16.3.4).

16.1.3. **Linking a channel to an app.** The first that applies:

1. The user's own link, set in Source settings (2.6.7: **Flatpak** and **Package** fields) or
   when adding a Source from Explore (16.2.4).
2. A Trust's `Flatpak`, `Debian package` or `Fedora package` line (10.3.1), with your own
   `AppKata.md` first, then the highest Score, then name. `Debian package` is used on Debian,
   Ubuntu and Mint; `Fedora package` on Fedora, RHEL, AlmaLinux and Rocky Linux.
3. **AppStream** (16.2.2): a component whose `vcs-browser`, `homepage` or `bugtracker` URL is a
   forge project URL that normalizes (2.3) to the app's, or whose ID equals the `<id>` in the
   project's own metainfo (3.2).

A name match alone never links a channel (it can still find a foreign install, 4.5).

16.1.4. **Checking a link.** AppKata checks every link it uses against what it can fetch:

| Channel | Checked against |
|---|---|
| Flatpak (Flathub) | The ID in the project's own metainfo; Flathub's **verified** flag (the project proved it owns the ID); the build manifest in `github.com/flathub/<id>`, whose sources should include the app's git URL |
| Debian package | The AppStream URLs; `Repository` in the package's `debian/upstream/metadata` |
| Fedora package | The AppStream URLs; `URL` and `Source0` in the package's spec on `src.fedoraproject.org` |

The result shows on the channel (16.3.1, 16.6.1): **Matches the project**, **Unchecked** (nothing
to check against), or, in the warning colour, "<Trust> links org.example.App, but its build comes
from github.com/someone/fork". A channel that fails its check is never **Recommended**; it can
still be installed.

16.1.5. **When the checks run.** Each check runs when its answer can change:

- **Flathub's verified flag:** every sync (9.2), as a conditional request (`If-None-Match`), so an
  unchanged answer costs almost nothing. Losing verification shows at the next sync.
- **The build manifest:** only when the Flatpak's newest commit on the remote changes, that is,
  when Flathub publishes a new build; between builds the manifest that made it can't change. It is
  read as a raw file (`raw.githubusercontent.com`), not through GitHub's API, so it doesn't use up
  the API's rate limit (2.4.1).
- **Distribution packaging metadata:** when the package's version in the repositories changes.

16.2. **Finding apps.**

16.2.1. Channels don't add apps to the Catalog (10.5): the Catalog is still the Sources and the
Trusts' apps. An app in the Catalog shows the channels it has (16.6.1).

16.2.2. **AppStream catalog.** The distribution publishes AppStream data for its repositories.
AppKata reads it directly; `appstreamcli` isn't needed.

| Distribution | Where | Refreshed by |
|---|---|---|
| Debian, Ubuntu, Mint | `/var/lib/apt/lists/*_dep11_Components-<arch>.yml.gz`, and the icon tarballs next to it | `apt update` |
| Fedora, RHEL, AlmaLinux, Rocky Linux | `/usr/share/swcatalog/xml/` (older releases: `/usr/share/app-info/xmls/`) | Updates to the `appstream-data` package |

Only components that are apps are used: type `desktop-application` or `console-application`.
Left out:

- Every other type (`runtime`, `font`, `codec`, `inputmethod`, `firmware`, `driver`,
  `localization`, `addon`, `service`, `operating-system`).
- Parts of the desktop: components with `<compulsory_for_desktop>`.
- Ubuntu's transitional packages that install a Snap (`firefox`, `chromium-browser`,
  `thunderbird` on releases where they do): a package that depends on `snapd` and whose
  description says it's transitional.

Without a catalog (servers, minimal installs), the distribution's Explore item is disabled, with
the tooltip "No AppStream catalog on this computer".

16.2.3. **Explore** (7.7) gains two items after **ngit**: **Flathub** (Flathub's public search API)
and the distribution, named for it (**Ubuntu**, **Fedora**…; the local AppStream catalog, 16.2.2,
offline). A match shows its app ID or package name, summary, Flathub's **Verified** chip, and the
project URL found (16.1.3), such as "github.com/laurent22/joplin".

16.2.4. **Adding one as a Source.** An app is still a git project, so **Add source** needs the
project URL: it opens Add source (7.2) with that URL and the channel link filled in. When no
project URL was found, the button is disabled ("No project link found") and **Enter git URL…**
opens Add source with only the channel link; the user types the project URL, and AppKata checks
the link against it (16.1.4) before saving.

16.3. **Installing.**

16.3.1. **Channel cards.** The install dialog (4.9) has one card per way to install the app here:
the release files (4.2.1), then each linked channel. A channel card shows:

- **Flatpak**: "Flathub · <app ID>", a **Verified** or **Community** chip (16.6.1), "Built by
  Flathub from <tag>" when its manifest says so, "Sandboxed · for you only; no admin password",
  and its download size.
- **Package**: "<Distribution> package · <name> <version>" and its repository ("universe"),
  "Installed for all users with apt (or dnf); needs your admin password", how far it is behind the
  project ("4 releases behind", 16.7.2), and its size.
- For either: who will update it (16.5): "Ubuntu updates it automatically" or "Not updated
  automatically", and the result of the link check (16.1.4).

16.3.2. **Which card is Recommended.** A Trust's `Channel` line (10.3.1; your own first, then
Score), "Recommended by <Trust>". Otherwise, in this order: a verified Flatpak, the release files
in the order of 4.2, a community Flatpak, the distribution's package. A channel that failed its
link check (16.1.4) comes last.

16.3.3. **When the dialog asks.** As in 4.9.1, when there is more than one card. The answer (the
channel, or the kind of file) is saved with the app (4.9.3) and used for updates. Apps with only a
channel and no release files still open the dialog to show what will happen.

16.3.4. **Installing a Flatpak.** Per user, with no elevation:

1. When the Flathub remote isn't configured for the user, AppKata asks once, "Add Flathub?", and
   runs `flatpak remote-add --user --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo`.
2. `flatpak install --user --noninteractive flathub <app ID>`, with its progress shown as in 4.8.
3. The record (4.1) holds the remote, the ref and the commit.

16.3.5. **Installing a package.** Through the package backend (16.8):

1. A dry run first gives the plan. A plan that only adds the package and its new dependencies
   installs straight away; the dialog's card already said how much it downloads.
2. A plan that removes or downgrades anything, or upgrades packages other than new dependencies,
   is shown in a confirmation listing those packages; **Install** is red and the default is
   **Cancel**. A plan that removes a package marked essential or protected, or a metapackage of
   the desktop (`ubuntu-desktop`, `task-gnome-desktop`, `@workstation-product`…), is refused.
3. The record holds the package name, the manager, the repository, and whether the package was
   already marked as a dependency (16.4.3).

16.3.6. **Verification** (4.4). Flatpak commits and packages are checked by flatpak, apt and dnf
against their repositories' keys; AppKata shows **Verified** with the tooltip "Signed by Flathub"
or "Signed by Ubuntu" (the repository's name).

16.4. **Tracking.**

16.4.1. **Still installed?** Each sync checks every channel install (`flatpak info`, `dpkg-query`,
`rpm -q`). One removed outside AppKata leaves the Apps view, and the Audit records "Removed outside
AppKata" (13; actor **System**).

16.4.2. **Adopting.** A foreign install (4.5) that a channel link (16.1.3) matches exactly (the
Flatpak app ID, or the package name) is adoptable: the disabled **Installed outside AppKata**
button (4.5.3) becomes **Adopt**, with the tooltip "Track this copy with AppKata, without
reinstalling". Adopting records it as if AppKata had installed it, adds it to the Apps view, and
is recorded in the Audit. A Flatpak installed for all users (`--system`) can be adopted too; changing
it then needs the administrator password, which flatpak asks for itself. Matches by name only stay
foreign.

16.4.3. **Uninstalling** (4.7):

- **Flatpak:** `flatpak uninstall --user --noninteractive <app ID>`. The app's data in
  `~/.var/app/<app ID>` is kept, like other user data.
- **Package:** a dry run first. When it would remove anything but the package itself, the
  confirmation lists what else goes and the user must confirm; the refusals of 16.3.5 apply. This
  applies to `.deb` and `.rpm` files installed from releases (4.3.3) too. Packages left unneeded are
  not removed (no autoremove); that is the system's business. A package that was installed as a
  dependency of something else, or that other installed packages need, can't be uninstalled from
  AppKata: the button is disabled with "Other software on this computer needs it".

16.5. **Updates.**

16.5.1. **Who updates it.** Each channel install is in one of three states, shown as a chip on its
Apps row and in the App Detail panel:

| State | When | AppKata |
|---|---|---|
| **Updated by the system** | The system updates it automatically (16.5.2) | Shows new versions ("1.20.0 is out") but has no Update button; **Update all** skips it, as for an app that updates itself (4.10) |
| **Not updated automatically**, in the warning colour | Nothing updates it automatically | Offers its updates like any other app |
| **AppKata updates it** | The user chose so in Install options (16.5.3) | Offers its updates like any other app |

16.5.2. **Detecting automatic updates.** AppKata reads the settings of the updaters it knows:

| Updater | Updates | Checked |
|---|---|---|
| unattended-upgrades (Debian, Ubuntu, Mint) | Packages from its allowed origins: by default **security updates only** | `APT::Periodic::Unattended-Upgrade` from `apt-config dump`, the `apt-daily-upgrade.timer`, and whether the package's repository is among `Unattended-Upgrade::Allowed-Origins` / `Origins-Pattern` |
| dnf-automatic (Fedora, RHEL family) | Packages | Its timer is enabled and `apply_updates = yes` (and `upgrade_type`) in its configuration |
| GNOME Software | Flatpaks automatically; packages only download and wait for **Restart & Update** | `org.gnome.software` `download-updates` |
| KDE Discover | Flatpaks and packages, when unattended updates are on | Its unattended-updates setting |
| Mint's Update Manager | Packages and Flatpaks, when its automation is on | Its automation timers and settings |

An updater AppKata doesn't know (a cron job, Ansible) isn't detected; 16.5.4 catches its updates
afterwards. Only security updates being automatic counts as **Not updated automatically**,
since app releases don't arrive that way.

16.5.3. **Choosing.** By default AppKata goes with what it detects, to stay out of the system's
way. **Install options…** (4.9.5) has **Updates**: **Let the system update it** or **AppKata
updates it**. Choosing AppKata while the system also updates it says so ("GNOME Software also
updates this app automatically; AppKata can't turn that off"): like an app's own updater (4.10.3),
AppKata can step back but can't stop another updater.

16.5.4. **Updates made elsewhere.** When a sync finds a channel install at a version AppKata didn't
install, it records it in the Audit (actor **System**) and, where the history says who, the App
Detail panel shows "Updated by GNOME Software on 3 Oct". The history comes from
`/var/log/apt/history.log` and `/var/log/unattended-upgrades/`, `dnf history`, and
`flatpak history`. A change made by an automatic updater to an app marked **Not updated automatically**
moves it to **Updated by the system**; a change made by a person (`apt`, `dnf` or `flatpak` run by
hand) doesn't.

16.5.5. **Finding and installing updates.**

| Channel | New versions | Update |
|---|---|---|
| Flatpak | `flatpak remote-ls --updates --user` | `flatpak update --user --noninteractive <app ID>` |
| apt | The repositories' lists as they are (`apt list --upgradable`); refreshed when AppKata updates something, through the backend | `apt-get install --only-upgrade <package>`, after a dry run (16.3.5) |
| dnf | `dnf check-update <package>`, which needs no administrator rights | `dnf upgrade <package>`, after a dry run |

16.5.6. **Pinning** (9.5). A Flatpak is pinned with `flatpak mask --user <app ID>`, which also stops
GNOME Software and Discover from updating it; unpinning removes the mask. Packages can't be pinned
from AppKata (it would take `apt-mark hold` or `dnf versionlock`, which change the whole system):
**Pin** is disabled with that explanation. A package already held that way shows **Held by the
system** and gets no Update button.

16.5.7. **Versions and minimum age.** For a Flatpak, the Versions list (5.7.5.1) comes from
`flatpak remote-info --log`, an older version installs with `flatpak update --commit=<commit>` and
pins it, and minimum age (9.5.2) uses the commit's date. For a package, the list shows only what
the repositories offer, older versions can't be installed, and minimum age doesn't apply: the
distribution already decides when a version is ready.

16.6. **Publisher and permissions.**

16.6.1. The App Detail panel shows each channel the app has, with who publishes it:

- **Flathub · verified**: published by the project itself.
- **Flathub · community**: packaged by someone else.
- **Ubuntu (universe)**, **Fedora**, or the repository's name (16.1.2).
- The link check (16.1.4).

These describe the channel, not the app: they never change the app's Trust or Rating (10.6).

16.6.2. A Flatpak whose program is downloaded from elsewhere at install time (an extra-data
Flatpak, which wraps someone else's binary) has a chip "Downloads its program from <host>".

16.6.3. **Flatpak permissions** come from the app's metadata (`flatpak remote-info --show-metadata`,
its `finish-args`) and are shown in plain words: Network, Home folder, Whole file system, Devices,
Display (X11), and named session services. An update that asks for more than the installed version
shows "Asks for more: Home folder" on its row in the warning colour; **Update all** skips it, and
updating it asks first. A reviewer's Trust was given for what the app could do before.

16.7. **Versions across channels.**

16.7.1. A channel's version is mapped to the project's version, to choose the review (10.3.5) and to
compare with the releases:

- **Flatpak:** the version of the newest `<release>` in the installed commit's metainfo, as
  `flatpak info` shows it.
- **Debian package:** without the epoch (`1:`), the Debian revision (from the last `-`), and
  repack suffixes (`+dfsg…`, `+ds…`, `~…`).
- **rpm:** its `%{VERSION}`.

16.7.2. The App Detail panel shows both when they differ: "Ubuntu 1.14.0-1 · project 1.18.2 (4
releases behind)", counting the project's releases newer than the mapped version.

16.8. **The package backend.** apt and dnf are driven in two ways; reading never needs
administrator rights.

16.8.1. **PackageKit**, when its service is running (as it is on desktop installs of Ubuntu,
Debian, Fedora, Mint and the RHEL family). AppKata talks to it over the system D-Bus with a small
D-Bus client of its own, in pure Python, so no new dependency. (PySide6's QtDBus can't send the
unsigned 64-bit flags PackageKit's methods take.) PackageKit is what GNOME Software and Discover use, so:

- Installs queue behind theirs rather than fighting over the package manager's lock.
- polkit asks for the administrator password and keeps it for a few minutes, so **Update all**
  asks once.
- Progress, cancelling and dry runs (the *simulate* flag) come from PackageKit.

16.8.2. **The command line**, when PackageKit isn't running (servers, minimal installs), through
`pkexec` (1.3):

- **apt:** `apt-get` with `DEBIAN_FRONTEND=noninteractive`,
  `-o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold` (keep the user's
  configuration files), and `-o APT::Status-Fd` for progress; dry runs with `apt-get -s`, which
  needs no administrator rights.
- **dnf:** `dnf -y`; dry runs with `--assumeno`.
- `pkexec` asks for the password once per action.

16.8.3. **Busy package manager.** When another program holds the package manager's lock
(unattended-upgrades, a store), the install waits as "Waiting for unattended-upgrades" (the lock
holder's name) for up to 10 minutes, then fails with that reason. **Cancel** works while waiting.

16.8.4. Reading uses the command line and files: `dpkg-query`, `rpm -q`, `apt list`,
`dnf check-update` and `dnf repoquery`, the AppStream catalog (16.2.2), and `flatpak` (which never
needs administrator rights for `--user`).

16.9. **The Audit** (13) records channel installs, adoptions (16.4.2), uninstalls, updates, the
**Updates** choice, and what changed outside AppKata (16.4.1, 16.5.4), with the actor **System**.

16.10. **Inside a sandbox.** There is no Flatpak of AppKata (1.6). If AppKata is nonetheless run inside
a Flatpak sandbox (`/.flatpak-info` exists), it can't see the host's packages or Flatpaks, so
channels are off and their Explore items and channel cards are hidden.

16.11. **Not supported:** openSUSE (zypper), installing Snaps (Snaps are still found as foreign
installs, 4.5), adding vendor repositories, browsing every package of the distribution, and reviews
of a distribution's own revision of a version (10.3.2 reviews the project's versions).

## 17. App sandboxing (Linux)

AppKata installs apps from the projects' own releases, so it can't vouch for what's inside them;
Trusts and reviews lower the odds of a hostile app, they don't contain one. This section limits the
harm a **portable app or AppImage** can do to the rest of the computer once installed. The rationale,
the experiments behind each decision, and the mockups are in [`app-sandboxing.md`](app-sandboxing.md);
the human validation checklist and an explanation of the launcher and the proxy are in
[`local-proxy-test-plan.md`](local-proxy-test-plan.md) (`scripts/sandbox/field-test.sh`); the launcher's
exact text is the goldens in `tests/data/launchers/` (17.4). Deferred
items are listed at 17.18.

17.1. **Scope.** Linux only, and only the two portable kinds AppKata installs itself (4.2.1): AppImage
(`appimage`) and tarball (`tarball`). AppKata itself is never sandboxed, though run as an AppImage it is
one of its own installs (2.11): it installs apps, runs package managers and pkexec, and writes the
install folder, none of which a sandbox allows (review 3, R3-6). Out of scope: `.deb`/`.rpm` (their scripts run as root at install
time, so a run-time sandbox can't undo them), Flatpak (already sandboxed; its permissions are shown,
16.6.3), shell installers (unsupported), and Windows/macOS. The sandbox is built on **bubblewrap**
(`bwrap`) with **xdg-dbus-proxy**; neither needs root, a daemon, or a setuid helper of AppKata's own.
A sandbox needs bwrap alone: where xdg-dbus-proxy is missing, a Standard app still runs sandboxed,
with no session bus and so no desktop services (17.5.1), while the files it is given still reach it
(17.6.2); App Detail and Settings → Sandbox name the missing tool and the command that installs it,
and AppKata's next start after it is installed gives the app its filtered bus (review 2, F12).
The launcher needs bwrap 0.5 or later (`--clearenv`, `--ro-bind-try`, `--seccomp`); the launcher
tests run, with the same results, on Linux Mint 22.3 (bwrap 0.9.0, xdg-desktop-portal 1.20, GLib
2.80), LMDE 7 (bwrap 0.12, portal 1.20, GLib 2.84), an Ubuntu 24.04 VM (bwrap 0.9.0, under its
user-namespace restriction with AppKata's profile, 17.10) and an Ubuntu 26.04 LTS VM under the
system's own bwrap profile (bwrap 0.11.1, portal 1.21, GLib 2.88; 17.10.2), so every platform 1.1
claims a sandbox on has a tier (review 2, F17; review 3, E3). On Ubuntu 22.04 the sandbox isn't
tested (1.1). The containers run on the test machine's kernel; the VMs, and the Mint 22.3 and LMDE 7
installs `docs/testing.md` runs, on their own.

17.2. **Levels and grants.** Each app runs at one of three levels, and grants adjust it per app:

| Level | Home | Install files | Network | Session D-Bus | Display, sound, GPU |
|---|---|---|---|---|---|
| **Off** | the real home | writable | yes | full | yes |
| **Standard** | private, plus granted folders | read-only | yes | filtered (portals only) | yes (sound with its grant) |
| **Strict** | private only | read-only | no | none | display and GPU, no sound |

17.2.1. **Grants** adjust a level: a folder (any path, read-only or read-write), network on/off, sound
(play and/or record, 17.8), desktop-services capabilities (17.5.1), a writable app folder (17.7.1),
and devices (camera). "Off" bypasses the launcher entirely (17.4). Grants adjust **Standard**: at
**Strict** the table above is the whole story, so a folder, the network, sound, a service or a
writable app folder given to a Strict grant set (a review's `Sandbox folders` line beside
`Sandbox: strict`, a customized set) is dropped when the set is read, and the launcher, the summary
chips and the review badge all see the same dropped set. The Sandbox dialog switches the set to
Standard the moment such a grant is added at Strict, and says so, rather than keeping a level the
grant contradicts. The X11 device grant is about the display and applies at every level.
The Sandbox dialog adds the user's Documents, Downloads, Pictures, Videos and Music in one click,
under this system's names for them, and turns any granted folder read-only or read-write (review
2, F10).

17.3. **Templates.** A sandbox is normally picked as a named **template** — a preset of level + grants
+ capabilities + Landlock extras — thin and overridable, not a straitjacket. Eight are built in:

| Template | Level | Files | Network | Sound | Devices | Services (17.5.1) | Landlock (17.18) |
|---|---|---|---|---|---|---|---|
| `strict` | Strict | none | no | no | X11 only | — | execute-deny |
| `standard` | Standard | none | yes | — | X11 | notifications | execute-deny |
| `offline-editor` | Standard | a folder you pick (rw): Documents or Pictures in one click | no | no | X11 | — | execute-deny |
| `online-app` | Standard | none | yes | play | X11 | notifications | execute-deny |
| `messenger` | Standard | none | yes | play + record | camera, X11 | tray, notifications, inhibit | execute-deny |
| `media-player` | Standard | a media folder you pick (read-only): Music or Videos in one click | optional | play | X11 | MPRIS, inhibit | execute-deny |
| `developer` | Standard | a projects folder you pick (rw) | yes | — | X11 | — | execute allowed |
| `cli-tool` | Standard | the directory it's run in (rw) | optional | — | X11 | — | execute allowed |

The three made for a folder come with none, since which one is the user's to say: picking one offers
it in place ("Pick its folder:", one click for the user folders that fit, **Other…** for any, read-only
under `media-player`), and the summary says "No folder yet" until it has one (review 2, F10: the
table promised a folder and nothing asked for it).

17.3.1. **Overrides.** Explicit settings override a template; `Sandbox folders: +~/Zettlr` adds to the
template's set (`+`/`-` prefixes add/remove). A template is resolved to a **grant set** before it is
combined or enforced, so it is never an opaque name. Some folders are **never shared**, whoever asks
(a review or the Customize picker): the home folder and anything above it, AppKata's install root
and data folder (the database, the private homes), the places that make a program start again later
or change what the user's own commands do — `~/.config/autostart`, `~/.config/autostart-scripts`,
`~/.config/systemd` and `~/.local/share/systemd` (user units), `~/.local/share/applications`,
`~/.local/share/dbus-1` (service activation), `~/.local/share/flatpak`, `~/.local/bin` (on `PATH`),
`~/.config/environment.d` and `~/.pam_environment`, `~/.config/plasma-workspace` (KDE's login
scripts), the desktop's own extension and script folders (`~/.local/share/gnome-shell/extensions`,
`~/.local/share/kwin/scripts`, `~/.local/share/plasma/plasmoids`, `~/.local/share/nautilus/scripts`,
`~/.local/share/kservices5`, `~/.local/share/kio/servicemenus` — code there runs inside the shell at
the next login or as the user from a file manager's menu; Mint's Nemo has `~/.local/share/nemo/scripts`
and `actions`), the browsers' native-messaging manifests (`~/.mozilla/native-messaging-hosts`, and
`NativeMessagingHosts` under the Chromium family's profile folders in `~/.config` — chromium,
google-chrome, Brave, Edge, Vivaldi, Opera — named one by one, since the match is on exact roots, so
those profile folders are refused too, as folders above one: programs the browser starts on an
extension's request), `~/.local/lib` (Python's user site, where a
`.pth` file runs in every Python the user starts), `~/.gitconfig` and `~/.config/git` (hooks,
aliases), and the shell and session startup files (`~/.bashrc`, `~/.profile`, `~/.zshrc`,
`~/.config/fish`, `~/.xsessionrc`, `~/.xprofile` and their kin, and what the default `.bashrc` sources
in turn: `~/.bash_aliases` on Ubuntu and Mint, `~/.bashrc.d` on Fedora; a "folder" grant binds a file
as readily as a folder) — the user's keys (`~/.ssh`,
`~/.gnupg`), the session's runtime folder, and anything inside or above one of these. Such a grant
is dropped — the launcher records why, the summary shows it as refused, and the picker says so —
because sharing it would hand the app the real home over its private one, a way to start again
later, or the keys the sandbox exists to protect. The list is `_protected_roots()` in
`src/appkata_core/sandbox.py`. A folder is named from `/` or `~` (`/media/usb`, `~/Projects`); any
other path — a bare word such as `home`, `run/user/1000`, `./x`, an unknown `~user` — is refused the
same way ("not a full path"), since bwrap resolves a bind source from the host's root while the
check would resolve it from AppKata's own working directory (review 2, F1: `Sandbox folders: home`
bound the real `/home`).
**Secrets** are refused when a review asks and allowed, with a warning in the summary ("holds
passwords or tokens"), when the user picks them: browsers' and mail clients' profiles
(`~/.mozilla/firefox`, `~/.thunderbird`), other sandboxes' data (`~/.var/app` for Flatpak, `~/snap`),
credentials for clouds, forges and registries (`~/.aws`, `~/.azure`, `~/.config/gcloud`, `~/.kube`,
`~/.docker`, `~/.config/gh`, `~/.git-credentials`, `~/.netrc`, `~/.npmrc`, `~/.pypirc`, Cargo's,
`~/.config/rclone`, `~/.vault-token`), and password stores (`~/.password-store`, the keyrings, KDE's
wallet), with anything inside or above them. A review's request shows as refused ("a review can't
grant …"). The list is `_secret_roots()` in `src/appkata_core/sandbox.py`. The keyring capabilities
(saved passwords, the password service, 17.5.1) are in the secrets class too: a review asking for
one is refused the same way (review 2, F9).

17.3.2. **Resolving several sources.** When reviews and the user both weigh in (validated,
`scripts/sandbox/merge.py`):
1. Each review → a grant set (its template, then its overrides).
2. Across Trusts → the least-privilege combination: strictest level; a folder only if **all** grant it
   (read-write only if all do); network, sound, devices and capabilities = the **intersection**;
   execute-deny if **any** Trust denies. One careless reviewer can't widen an app.
3. The **user's own choice wins** over the merged reviews; an app **no** Trust has reviewed falls to
   the default template (17.3.3).
4. A review's `off` adds no limit when merged with others (`off` ∩ X is X), and where the merged
   reviews say Off, the sandbox is **not** turned off: the reviewed baseline of 17.3.3 applies, and the
   install card and the Sandbox dialog offer "X suggests no sandbox — Use theirs", which makes Off the
   user's own choice (review 2, F8).

17.3.3. **Defaults, by app kind and review state.** Reviewed beats unreviewed. A reviewed GUI app uses
the review's template (baseline `standard`); a reviewed CLI tool uses the review's template (baseline
`cli-tool`); an **unreviewed GUI app** uses `strict`; an **unreviewed CLI tool** uses `cli-tool`
(real protection, not Off). Every default is one click to change in the install options (4.9) or App
Detail. **The app's kind** is decided from the download, once its files are placed and before its
launcher and menu entry are written (review 2, F4): an AppImage is a command-line tool when the
`.desktop` at its root says `Terminal=true` (its own runtime reads it out, in the unpacking's
sandbox, 17.7); a tarball is one when its `.desktop` files say so, or, with none, when its program
links no display library (X11, xcb, Wayland, GTK/GDK, Qt's GUI, SDL, OpenGL/EGL, Vulkan; Electron links
GTK). What can't be told (a script, no bwrap) counts as an app — Strict, the tighter. The user's own
choice in the install options ("It is: an app with a window / a command-line tool", 4.9.2) wins, and
correcting it on an installed app with no sandbox of the user's own applies the default for the new
kind at once. A command-line tool gets no app-menu entry when that option was only Settings' default
(4.3.1.1). The `cli-tool` template binds the directory the tool is run in (rw) via the command-link
wrapper (4.3.1.3) and nothing else of the home; a path outside that directory isn't visible, so a tool
that needs wider paths can take a folder grant or Off. The directory is **not** shared when it is the
home folder, a folder above it (including `/`), one of the never-shared folders of 17.3.1 (AppKata's
install root, data folder and sandbox homes, the autostart, systemd, app-menu, D-Bus-activation and
Flatpak dirs, `~/.local/bin`, the login-environment and KDE login-script dirs, the desktop's
extension and script folders, the browsers' native-messaging hosts, `~/.local/lib`, the git config,
`~/.ssh`, `~/.gnupg`, the session's runtime folder), or inside or above one of those — that would be
the whole home or more, a way to start again later, or the real session bus, not a project folder;
the tool then runs in its private home and says why on stderr.

17.3.4. **Personal templates** (naming the user's own paths) and **reviewer-defined** templates are
deferred (17.18). v1 ships the eight built-in templates plus per-app customization: a template the user
changes is kept as that template plus the changes, shown as "Offline editor · customized" with **Reset
to template**; only a merged or bespoke set is "Custom" (review 2, F10). The Sandbox dialog describes
such a set by its changes ("Standard, without the network and notifications, with ~/Projects
(read-write)"), not with the template's own description (review 2's widened-Strict nit).

17.3.5. **What a review may do.** Reviews are suggestions from people the user trusts, who may be
wrong or compromised. On its own a review may pick a template, narrow access and grant ordinary
folders, sound, devices, services and the writable app folder (10.3.1); it may not turn the sandbox
off (17.3.2) nor grant the user's secrets (17.3.1) — those take the user's own click. The never-shared folders (17.3.1) are refused whoever asks (review 2, F8).

17.4. **The launcher.** For every sandboxed app AppKata generates `~/bin/apps/<app>/run`, regenerated
on each install, update and sandbox-settings change, with the resolved grant set baked in (no run-time
policy resolution) — and at AppKata's start, for any app whose launcher is not the text AppKata
would write today (one a previous AppKata wrote, or a hand-edited one), or whose files the launcher
calls by path are not (the identity marker, the `xdg-open` shim, the file-argument helper, the
seccomp filter; review 2, F5), so a launcher fix reaches every installed app at the next start
rather than at its next update. `launch()`, the app-menu entry's `Exec=` (4.3.1.1) and the command link (4.3.1.3)
all point at it, so starting the app from anywhere AppKata controls is sandboxed. Its text can be shown
in App Detail ("Show the launch command"), and the Audit (13) records a hash of it, with the set it
was written for, each time AppKata writes it: an install or update, a sandbox change, AppKata's
start (review 2, F11: no screen showed it and no entry held it). It binds `/usr` and `/etc`
read-only; mounts a **private home** at `~/.local/share/appkata/sandboxes/<app>` over `$HOME`; binds the
app's current version folder read-only and no other app's; binds the host's `~/.themes`, `~/.icons`,
`~/.fonts`, `~/.config/fontconfig` and `~/.local/share/{fonts,icons,themes}` read-only so apps look
native; binds the font cache (`/var/cache/fontconfig`) read-only, and the parts of `/sys` GPU drivers
read to identify the GPU (`/sys/block`, `/sys/bus`, `/sys/class`, `/sys/dev`, `/sys/devices`)
read-only, as Flatpak does; with the network grant, binds where `/etc/resolv.conf` really lives when
that is in `/run` (systemd-resolved's folder, or NetworkManager's file) read-only, so names resolve
(review 3, R3-10); when the level uses the bus, binds
the document portal's view of this app's documents (`$XDG_RUNTIME_DIR/doc/by-app/<id>`) at
`$XDG_RUNTIME_DIR/doc`, so a file handed to the app through the document portal (a file argument,
17.6.2) is readable at the path the portal gives; sets `GDK_DEBUG=no-portals` and no `GTK_USE_PORTAL`
(the app's own file dialog is used, 17.6.3); clears the environment to an allow-list (the user's
locale, regional formats, time zone, theme, scaling and input method, read from the environment the
launcher was started with, not from its shell, which may add some: review 3, R3-20), passing the proxy settings
only to an app with the network grant, since they can carry its credentials (review 2, F15); and uses `--unshare-all`
(with the network shared back unless the level forbids it), the terminal-injection seccomp filter
(`--new-session` only on a machine the filter is not built for) and `--die-with-parent`, with
bwrap as the launcher's own child at every level, so the app outlives whatever started it (AppKata,
the desktop shell, a script). Strict adds no network, no folder grants and no bus proxy — and so no portals,
and no bus at all: the launcher points `DBUS_SESSION_BUS_ADDRESS` at a bus the sandbox doesn't have,
so GLib and libdbus fail at once rather than start one inside the sandbox through `dbus-launch`, and
the host's portal services with it (review 3, R3-33). A
Strict app can open only files in its private home (started from a terminal with arguments, it says
so on stderr), and nothing on the host — its `xdg-open` is
AppKata's (17.6.3), which says so and fails, rather than the desktop's own in `/usr`, which under a
desktop it doesn't know would start the host's browser inside the sandbox. The host's desktop entries
(`/usr/share/applications`, `/usr/local/share/applications`) are hidden under an empty tmpfs, as a
Flatpak runtime has none: GLib opens a link or file with the default handler it finds and asks the
OpenURI portal only when there is none, so with the host's entries in view a GLib or GTK app started
the host's browser or editor *inside* the sandbox (17.6.3); an app that lists installed applications
sees none, as in Flatpak. Every mount destination under `$HOME` lies inside
the app-writable private home, so before mounting the launcher removes any symlink the app has left
at such a path (bwrap would otherwise follow it on the host side and create files or folders there).
The launcher's exact text is the goldens in `tests/data/launchers/` (one per grant set, kept byte
for byte by `tests/test_launcher_golden.py`, so a change shows in review as a shell diff);
`local-proxy-test-plan.md` explains its parts and the proxy (review 2, D1: it had kept the
planning-stage shape).

17.5. **Filtered session bus.** When the level uses the bus, the launcher starts one `xdg-dbus-proxy`
for the launch (torn down with the app) that exposes the safe part of `org.freedesktop.portal.Desktop`
plus the app's own well-known name (`--own=io.appkata.<app>`, so single-instance and "open in the
running window" work), the portals IBus and Fcitx provide for sandboxed apps
(`org.freedesktop.portal.IBus`, `org.freedesktop.portal.Fcitx`, so the input method works; review 2,
F15, shown in the `inputmethod` harness) and its granted capabilities. An unfiltered bus lets an app reach
`org.freedesktop.systemd1` and start programs outside the sandbox, so filtering is mandatory. The
portals see the app as a host caller (17.6.1), and some portals trust a host caller with the host, so
the portal name is not opened whole: per-interface `--call` rules allow OpenURI, Settings, Print,
Email, NetworkMonitor, ProxyResolver and MemoryMonitor (and the Request and Session objects they
create) for every app on the bus, Notification and Inhibit only with the matching capability
(17.5.1), `Introspectable` on the portal object (what `gdbus introspect` asks), and nothing else on that
name — not Background (writes the caller's
command into `~/.config/autostart`), DynamicLauncher, Documents, Camera, ScreenCast, RemoteDesktop,
Screenshot, Location, Realtime, Account, Trash, nor FileChooser (17.6.3), nor the `version`
properties (what Chromium/Electron reads before switching to the portal file chooser; GTK4 is held
by the FileChooser denial itself, 17.6.3).

17.5.1. **Capabilities.** The fiddly desktop-services an app may use, bundled into templates and
mapped to proxy arguments: **notifications** and **screensaver inhibit** (each opens both roads — the
portal interface, which GLib and GTK apps take when they see `/.flatpak-info`, and the direct
`org.freedesktop.Notifications` / `org.freedesktop.ScreenSaver` name the others use — so the
capability is the one switch and an app without it has neither), **tray** (`StatusNotifierWatcher` +
its item name), **media keys** (MPRIS), and **secrets** (`org.freedesktop.secrets`, talk to consume
or own to provide, e.g. KeePassXC). The full mapping table is in `local-proxy-test-plan.md`.

17.6. **App identity.** The launcher presents each app a stable id, `io.appkata.<app>`, via a
synthesized `.flatpak-info`, bound read-only at `/.flatpak-info` in the app sandbox — and only there
(17.6.1). **PipeWire/WirePlumber** take the app for a sandboxed client from it (17.8), and GLib takes
its portal use and, from `[Context] shared=network`, whether the network is available (the marker says
so exactly when the app has the network grant); the Wayland security-context will use it too, once
built (17.18). The id is also the app's D-Bus name (17.5), whose elements may not start with a digit:
an app slug that does gets a leading underscore (`io.appkata._7zip`), and the document portal's
per-app folder (17.6.2). `<app>` is the install's own id, chosen once at install and recorded: the
name's slug, or `<slug>-2`, `-3`… when another installed app already holds it — so two Sources'
apps with one name (two "Notes") have their own folder, launcher, menu entry, command link,
identity, private home and log (14.2.1), and uninstalling one leaves the other whole (round six, R6-1: everything
was keyed on the name alone, and the two shared all of it). A private home an uninstall keeps
(17.14) stays its app's: AppKata records which app (URL) each home belongs to, and a later install of
another app with the same name takes the next free id rather than that home; the same app
reinstalled finds its own home again (review 2, F19: the next "Notes" from another Source got the
first one's home, accounts and tokens). A home with no owner recorded counts as another app's.

17.6.1. **The portals see a host caller.** xdg-desktop-portal 1.18 and later (Ubuntu 24.04, Mint 22)
accept a caller that presents `.flatpak-info` only when its instance id matches a running Flatpak
instance's records; any other such caller is refused outright ("Portal operation not allowed"), so a
marked bus proxy got no portal at all there — no notifications, no OpenURI, no settings (confirmed in
the Mint 22.1 session container with a generated launcher; older portals, Mint 21.3, accepted it).
Decided: the bus proxy carries **no** marker, so the portals judge the app a host caller and answer it
on every portal version; the proxy allows only the interfaces that are safe for one (17.5). AppKata
never fabricates Flatpak instance records to pass that check. The consequences: a file the user picks
is not handed over by the file chooser portal (17.6.3; file arguments are, 17.6.2), and the marker's
other readers are unaffected (17.6).

17.6.2. **File arguments.** A file or folder the app is given as an argument — the menu entry's `%U`
("Open with", a file dropped on it), a command link run as `tool ~/notes.txt`, or an option's value
(`--file=~/notes.txt`, or `-o/home/u/notes.txt` with a full path; review 3, R3-16) — is a host path
the sandbox can't see unless it lies in a granted folder. For a Standard app the launcher hands such
files and folders over through the document portal **from the host side** (Documents `Add` +
`GrantPermissions` for a file, `AddFull` with the export-directory flag for a folder, what the file
chooser portal does for a pick, so it works whatever the portal makes of the marker in 17.6.1;
folders shown on document portals 1.12 to 1.20), with write permission when the user has it, and the
argument becomes the path the app sees (`$XDG_RUNTIME_DIR/doc/<id>/<name>`; a `file://` URI stays a
URI). A path in a granted folder becomes the path the app sees it at — the grant's own mount path
plus the rest — unless it already resolves there, as a CLI tool's relative paths in its shared
directory do (17.3.3); so a relative path, `.` or `..` from a granted folder (review 2, F6) and a
link outside the granted folders to a file inside one (review 3, R3-17) reach the file, and a file
named from a refused directory is handed over like any other. A file not yet made is not handed over
(17.18). Strict apps have no bus and so no hand-over, as in 17.6. Without `python3-gi` or a running
document portal the arguments pass through unchanged, as before.

17.6.3. **File dialogs and opening things on the host.** A sandboxed app's file dialog is its own,
not the portal's: for a host caller the FileChooser portal returns real paths the sandbox cannot open,
so the proxy does not allow it and the launcher does not set `GTK_USE_PORTAL` (nor bind the marker
at `$XDG_RUNTIME_DIR/flatpak-info`, which is what GTK3 and xdg-open read to switch to the portal).
GTK4, Qt 6.5+ and Chromium/Electron read `/.flatpak-info` instead, which the app's root does
have, and would then ask the FileChooser portal, which the proxy denies (17.5). GTK4 is told not to
ask: the launcher sets `GDK_DEBUG=no-portals`, GTK4's switch for its portal dialogs — GTK 4.14 fell
back to its own dialog when `OpenFile` was refused, but GTK 4.18 shows *no dialog at all* (round
six, R6-4, Ubuntu 25.04), and `GTK_USE_PORTAL=0` does not stop a marked process from asking. The
flag is GTK's alone: GTK3 ignores it and never asked, and GLib's roads (links, notifications) read
the marker, not it. Its cost: GTK4's other portal dialogs (print, colour) are the in-sandbox ones.
Qt 6.5+ reads the marker and probes the `version` property, and keeps its own dialog whatever the
proxy answers (Qt 6.8); Qt up to 6.4 looks for the runtime-dir marker like GTK3 and never asks.
Chromium/Electron reads `version` first, which is denied, and so keeps its own GTK dialog — were
Properties allowed it would take the portal road, be refused `OpenFile` and show no dialog at all.
Shown with real GTK3, GTK4 and Qt apps behind generated launchers, with the portal and its gtk
backend running, on Mint 22.1 (GTK 4.14, Qt 6.4: `scripts/test-sandbox.sh filedialogs`) and Ubuntu
25.04 (GTK 4.18, Qt 6.8: `filedialogs-qt68`), and with Chromium 154 under the three proxy variants
(`scripts/test-sandbox.sh consumers`); allowing Properties alone changed nothing for GTK4 and lost
Chromium its dialog, allowing FileChooser too gave Chromium the portal's, and GTK4 the portal's only
with the launcher's flag removed as well.
The app's dialog then shows exactly what the sandbox sees — the private home, the granted folders and
the hand-over view at `$XDG_RUNTIME_DIR/doc` — and a file elsewhere reaches the app by "Open with" or
a drop on its menu entry (17.6.2) or by granting its folder. An app whose own start script sets
`GTK_USE_PORTAL=1` loses its file dialog; AppKata does not undo that. Links and files the app wants
*opened on the host* do go through the OpenURI portal: GLib and GTK apps call it on their own once
the host's desktop entries are hidden from them (17.4; GLib prefers any handler it can find), Qt apps
call it directly when they see `/.flatpak-info` (and run `xdg-open` only if that fails), and for the
rest (Electron, and anything else that runs `xdg-open`) the launcher puts an `xdg-open` of AppKata's first on the
app's PATH that passes a URL to the portal, or a file as a descriptor the portal resolves to its host
path and opens with a host program, instead of starting the desktop's browser or viewer inside the
sandbox. The portal asks which program only when it has to — more than one installed handler for
the type and no choice the user has settled on (the same program picked three times); a type with
one handler (`.jar` with a JRE, `.deb` with gdebi) opens at once, for a host caller and a Flatpak
app alike — so a read-write folder grant is also a road to the host's programs for files the app
writes there (17.17). AppKata's `xdg-open` waits for the portal's answer and says when the host
could not open the file (shown with the real portal, `scripts/test-sandbox.sh consumers`). It is on the app's PATH at every level: a Strict app
has no bus to ask through, so there it prints that the app runs Strict and fails, instead of
leaving the desktop's `xdg-open` to start the host's browser inside the sandbox. That resolves a file in a granted folder or in the
hand-over view, which have the same path on both sides; a file in the private home reaches the portal
as `$HOME/<x>` (the private home is mounted over `$HOME`), where the host has no such file, so the
portal refuses it — grant the folder for that. It uses `gdbus` or `busctl` for URLs and `python3-gi`
for files; without them it says so on stderr and fails.

17.7. **AppImage.** An AppImage can't FUSE-mount inside bwrap, so: at **Off** the `.AppImage` is run
directly; at **Standard/Strict** AppKata extracts it (in a sandbox, since `--appimage-extract` runs the
publisher's code) on first sandboxed launch and runs `AppRun` from the extracted folder. The `.AppImage`
file is canonical (checksum, rollback, "run outside AppKata"); the extracted directory is a derived
cache (lazy, rebuilt if missing, kept when the app runs Off). `APPDIR`/`APPIMAGE`/`ARGV0` are set. Extraction
costs 2.5–3.5× the AppImage, shown in the install options when sandboxing is on.

17.7.1. **Writable app folder.** Apps that keep settings or data beside the program break against
the read-only install folder; a per-app **writable app folder** grant binds the version folder
read-write (the app can then change its own code, so it is close to Off for tampering). An
AppImage's own `.AppImage` stays read-only whatever the grant, so it never helps an AppImage update
itself; a sandboxed app is updated by AppKata instead (17.12).

17.8. **Sound.** Audio reaches the app through the session manager as a **sandboxed client** (the
`.flatpak-info` identity, 17.6). The grant is split into **play** and **record**, but v1 can't enforce
the split: PipeWire and WirePlumber let a sandboxed client record from the same sockets it plays through
(verified with WirePlumber 0.4.17 / PipeWire 1.0.5), so play-only is shown as "can also record" rather
than as protection; enforcing it is deferred (17.18). The **camera** grant binds the V4L2 devices
(`/dev/video*`, `/dev/media*`); without it the app has no camera: the Camera portal is not open to
sandboxed apps (17.5), so nothing asks the user (round six, R6-2 — the earlier "asks the user first"
was written before finding 0 narrowed the proxy, and the hint said the same).

17.9. **Display and the session warning.** The Wayland socket is bound on a Wayland session, else the
X11 socket (with `XAUTHORITY`). On Wayland the X11 (XWayland) socket is bound **too** when the app has
the **X11 apps** device grant — on in every built-in template, so apps that only speak X11 (older
Electron, Qt builds without the Wayland plugin) still open; an app that speaks Wayland keeps preferring
it. Such an app can see and inject into other XWayland windows, not native Wayland ones; Customize
turns it off (shown by a "No XWayland" chip; review 3, R3-15) — which withholds the socket, `DISPLAY` and the `XAUTHORITY` cookie, not the server's
reach: with the **network** grant the X server's abstract-namespace socket is in the shared
network namespace and can still be connected to (shown in the launcher tests), so "off" rests on
the compositor's Xwayland requiring the cookie, which GNOME/mutter and KDE/kwin do and wlroots
compositors do not (the session warned about below). Flatpak has the same property. The same holds for
**every** abstract-namespace socket on the host, not the X server's alone (review 3, R3-8): where dbus
is 1.12 (Mint 21.3, Ubuntu 22.04, RHEL 9), a session bus started with `dbus-run-session` or
`dbus-launch` is one, and an app with the network grant reaches it unfiltered, past the proxy of
17.5; AppKata warns about such a session in Settings → Sandbox (17.15) and, for an app with the
network grant, in App Detail. A desktop's own login uses systemd's user bus, a path, and isn't
affected. On **X11**, and on **any Wayland compositor other than
GNOME/mutter**, a sandboxed app can still capture the screen, read the clipboard and inject input
into other windows: the wlroots family (sway, Hyprland, river, wayfire, labwc, niri) was confirmed
to leak, and a compositor AppKata has never heard of is not assumed safe. **KDE/kwin** is in
between: it hides screen capture and input injection from untrusted clients but offers the
clipboard-manager protocol (`zwlr_data_control`) to every client, so a sandboxed app reads and
changes the clipboard there (round seven, R7-1, kwin 5.27; a sandboxed `wl-paste` printed what the
user had copied) — KDE gets a warning that names the clipboard alone. v1 does
**not** close this (the fix, the Wayland security-context protocol, is deferred, 17.18) — it
**warns** plainly, for the session the user is on, in Settings → Sandbox (17.15) and the App Detail
caveat, naming the compositor when `XDG_CURRENT_DESKTOP` says it (sway started from a TTY sets
nothing, and is warned about as "this Wayland compositor"). The session is the display the launcher
gives the app: Wayland when `$WAYLAND_DISPLAY` names a socket in the runtime folder, else X11 when
`$DISPLAY` is set; `XDG_SESSION_TYPE` doesn't decide it, since a compositor or X server started from a
console keeps logind's `tty` there (review 3, R3-13). Only GNOME Wayland needs no warning:
the rule is that allowlist, not a list of leaking compositors, which could only fall behind. A
desktop's name can mislead, though — Budgie's and Phosh's sessions list GNOME but run wlroots
compositors (labwc, phoc) — so AppKata also lists the globals the compositor offers an ordinary
client (one registry round trip on its socket) and warns, whatever the name says, about each leak
they show: screen capture (`zwlr_screencopy`, `ext_image_copy_capture`), the clipboard manager
(`zwlr`/`ext_data_control`) and input injection (a virtual keyboard or pointer, KDE's fake input).
The globals only add to the warning; they never clear one (review 2, F7; AppKata's reading of sway,
mutter and kwin 5 and 6 is shown in the `wayland`, `kwin` and `kwin6` harnesses).

17.10. **AppArmor setup (where the kernel restricts unprivileged user namespaces; where the system has a bwrap profile of its own, see 17.10.2).** There
bwrap won't run until an AppArmor profile grants the carve-out. AppKata
detects this (a one-off `bwrap --unshare-user` probe) and, on first need, offers a one-time setup that
writes and loads `/etc/apparmor.d/appkata-sandbox` behind a single **pkexec** prompt (the same
mechanism as 16.8; the one place sandboxing needs root). It persists across reboots. The first need
is installing an app that would run sandboxed: before it installs, AppKata asks "Set up the
sandbox?". **Set up now** runs the setup, then installs the app, sandboxed if the setup worked.
**Not now** installs it to run **Off** and is remembered, so later installs don't ask. Settings →
Sandbox's **Set up…** and App Detail's standing **Enable…** banner set it up at any time and clear a
Not now, and the Audit records the answer (review 2, F12). A system without the restriction needs no setup;
which of the tested systems restrict, and so need it, `docs/testing.md` says ("What each environment boots with",
checked in each VM; review 3, R3-37). The profile
names the `bwrap` actually installed (the one on `PATH`, symlinks resolved), since a profile attaches
to one executable path; and the setup counts as done only when the probe passes afterwards — if the
profile loaded but bwrap still can't create a user namespace, the setup reports that failure rather
than success. The setup checks bwrap as the user who asked, in the same privileged run, and when it
still fails it unloads and removes its profile again, so a failed setup leaves nothing behind.
Once an app has a launcher it keeps one: an update, a rollback or a sandbox change on a system whose
support has since broken (a different bwrap first on `PATH` than the profile names, the profile
removed, bubblewrap uninstalled) still writes it, a start that then fails says why in the app's log
and a toast (14.2.1), and App Detail says the app can't start; only the user's own Off runs it
unsandboxed (review 2, F16). A failed check is asked again a minute later rather than standing for
the session.

17.10.1. **What the profile costs.** It is `flags=(unconfined)` with `userns` on the bwrap it names (usually
`/usr/bin/bwrap`), the same shape as Ubuntu 24.04's own profiles for `flatpak`, Chrome and Discord. But
bwrap is a general tool, so the carve-out is not AppKata's alone: **any program the user runs** can
create a user namespace through bwrap again, which is the kernel attack surface Ubuntu's restriction
shrinks. Settings → Sandbox and the per-app setup banner say so. AppKata does not install the tighter
design that strips capabilities from bwrap's children (`bwrap-userns-restrict`): it breaks the
Chromium/Electron sandbox nested inside bwrap. Ubuntu 25.04 and later ship it themselves (17.10.2).

17.10.2. **Ubuntu 25.04 and later.** These ship their own AppArmor profile for `/usr/bin/bwrap`
(`/etc/apparmor.d/bwrap-userns-restrict`): bwrap may create a user namespace, and everything it runs is
confined by a second profile (`unpriv_bwrap`) that denies capabilities. There the sandbox runs with no
setup (the probe passes), and AppKata never installs a profile of its own: two profiles on one path
don't combine, and with both loaded bwrap creates no user namespace for anyone (shown in an Ubuntu
26.04 guest, live and after a reboot; review 2, F2). So:
- the setup refuses where the system has its own profile for bwrap;
- where AppKata's profile is found beside it — a machine where the setup ran, then upgraded to a
  release with its own profile — Settings → Sandbox and App Detail say that no sandbox can start and offer **Repair…**,
  which removes AppKata's profile behind one pkexec prompt;
- under the system's profile no program inside the sandbox can make a user namespace of its own, and
  Chromium's and Electron's own sandbox needs one (an AppImage's `chrome-sandbox` isn't setuid to fall
  back on, so the app would refuse to start). The launcher starts a program that brings that sandbox
  (`chrome-sandbox` or `chrome_crashpad_handler` beside it) with `--no-sandbox`: it stays inside
  AppKata's sandbox and loses only its inner one, the isolation of the content it displays from the
  rest of the app. App Detail says so for such an app, and Settings → Sandbox for the system.
  Whether the inner sandbox can run is probed once per start (`unshare --user` inside bwrap) and baked
  into the launcher, so the startup pass (17.4) rewrites launchers when an upgrade changes it.
  Restoring the inner sandbox there is deferred (17.18).

17.11. **Where permissions come from.** In order: the user's per-app choice (install options 4.9, App
Detail) wins; then the merged reviews' `Sandbox*` lines (10.3.1, resolved per 17.3.2); then the default
template (17.3.3). Reviews **never** change an app's grants on their own: a new version installs
normally and keeps the user's current grants, and if its reviews suggest more or less access the app
gets a standing **review badge** (not a blocked update). The badge names what the suggestion adds and
removes; with more access it says the app may not work fully until reviewed, with less that the app
may have more access than it needs (review 2's nit: it listed the whole suggestion and said neither).
Access is never silently widened. The badge stands until the user
**acts on that suggestion**: adopts it (one click, in the badge's Review… dialog; a suggested Off is
adopted as the user's own choice, 17.3.2), keeps their current
grants ("Keep mine"), or saves a sandbox choice of their own knowing it. A later, different
suggestion raises it again; a user's deliberate choice never leaves a permanent badge.

17.12. **Self-update.** An app that updates itself (4.10) can't while it runs sandboxed: its install
folder is read-only, and for an AppImage the `.AppImage` file too. So while it runs sandboxed —
whenever it has a launcher, 17.4 — AppKata updates it as if it didn't update itself (4.10.5): the
Update button, Update all, the minimum age and pinning apply, and its next update moves it to
version folders, with the old fixed-name file kept as the previous version. App Detail says "It
would update itself, but it runs sandboxed and can't change its own files, so AppKata updates it",
and the install dialog's "This app updates itself" hint says the same. Its own updater simply fails
(how gracefully is each app's). Switched to Off, it updates itself again. (Review 2, F3: an
earlier draft named a "Disable the app's own updater" option, which 4.10.3–4.10.4 rule out and
which was never built; nobody updated a sandboxed self-updating app.)

17.13. **Enabling a sandbox after install** warns that the app is **effectively being reinstalled and
its configuration may be reset**: the real files aren't touched, but the app sees an empty private home,
so settings/accounts appear reset, absolute paths stored in its config dangle, and external
integrations (browser native-messaging hosts, MIME associations, autostart) may stop working. No
automatic config import in v1 (17.18). The warning comes before the change: the Sandbox dialog and
Install options say it above Save as soon as a sandboxed choice is picked for an installed app that
runs unsandboxed and has no private home yet. Every way to set up system support (the install
prompt, Settings' Set up…, App Detail's Enable…) first names the apps it will sandbox and which of
them start with fresh settings. When AppKata itself sandboxes an installed app (at start once the
system can, after a setup, or with an update), a notice names it and the Audit records it (review 2,
F13).

17.14. **Uninstalling** a sandboxed app offers to remove its private home
(`~/.local/share/appkata/sandboxes/<app>`), like any app data (4.7); so does uninstalling an app
switched Off that still has one (review 2's nit: its home stayed behind, orphaned). A kept home remains that app's
alone (17.6).

17.15. **Settings → Sandbox** (11.1): the default template for new apps (by kind, 17.3.3); the
**System support** status and one-time **Set up…** (17.10), or **Repair…** where AppKata's profile sits
beside the system's own (17.10.2); "Follow reviewers' suggestions"; the
review-badge toggle (17.11); a read-only **Built-in templates** list; the sandbox home folders; and the
session-type warning (17.9) shown prominently. "Follow reviewers' suggestions" **off** takes the
reviews out of sandboxing: neither their `Sandbox` lines nor the reviewed baseline of 17.3.3 apply,
so an app with no choice of the user's own gets the default template for its kind, and the review
badge never shows. The Sandbox dialog still says what the reviewers suggest, and "Use theirs" stays
available as an explicit choice.

17.16. **The Audit** (13) records every change of a sandbox level, grant or template, naming what was
added and removed ("Offline editor · customized: added ~/Notes (read-write)"; review 2, F11); the AppArmor
system setup, a Not now to it (17.10), and its repair; and review-badge resolutions.

17.17. **Limits**, stated plainly in the UI and docs: on X11 and on every Wayland compositor but GNOME's
the sandbox protects files, not the screen/clipboard/keystrokes (on KDE the clipboard alone, 17.9); a granted folder or network is the app's, the network
reaching every abstract-namespace socket on the host (a session bus among them where dbus is 1.12,
17.9), and a read-write folder is also a road to the host's programs: a file the app writes there and
opens through the portal is opened by the host's handler for its type, without a question when
that handler is the only one (17.6.3; Flatpak has the same property); a kernel
exploit leaves any namespace sandbox (this is not a VM); every app, Strict included, can read the
machine's identifiers — the machine-id, the boot id and the host name, and through `/sys` the network
cards' MAC addresses, USB serial numbers and the hardware model — as in Flatpak, and a networked app
can report them (review 2, F18; review 3, R3-7); screen readers can't see a sandboxed app, which
is not given the accessibility (AT-SPI) bus until a filtered proxy for it is built (17.18; review 2,
F15); running the `.AppImage` or program directly
(or via AppImageLauncher) bypasses the sandbox; there is no per-host/domain network filtering (only
on/off, and per-port via Landlock later); the only seccomp filter is the terminal-injection one
(17.4); on Ubuntu 25.04 and later, apps that bring their own sandbox (Chromium, Electron) run without
it, inside AppKata's (17.10.2); and two sandboxed apps with the **tray** capability running at once can collide on the tray
item's bus name — every sandboxed app is one of processes 2 to 6 in its own namespace, so each proxy
owns the same `org.kde.StatusNotifierItem-<pid>-<n>` names, and the second app's icon may not appear (the same
limitation as Flatpak's).

17.18. **Deferred to later releases** (not v1): the **Wayland security-context** protocol (closes the
wlroots leak and KDE's clipboard leak, 17.9; sway since wlroots 0.17 and kwin 6 advertise it, shown in
the `wayland` and `kwin6` harnesses — the next release's first item); the **Landlock** layer as defense-in-depth inside bwrap (execute-deny, per-port
TCP); **personal templates** and **reviewer-defined/shared templates** (17.3.4); **config import** on
enable-later (17.13); a **fuller seccomp filter** beyond the terminal-injection one of 17.4
(Flatpak's: `ptrace` of other sandboxes, `perf_event_open`, unusual socket families); **squashfuse**
mounting instead of extraction (17.7);
proprietary-**NVIDIA** device nodes; **enforcing play-only sound** (17.8); a **capability-stripping AppArmor profile** for bwrap's children
on 24.04 (17.10.1); a **spawner for Chromium's and Electron's own sandbox** on Ubuntu 25.04 and later
(17.10.2: as Flatpak's zypak does, a host-side helper per launch that starts each sandboxed Chromium
child in its own, tighter bwrap, so the app's inner sandbox comes back instead of `--no-sandbox`); a
network of an app's own (**user-mode networking**, `pasta` or `slirp4netns`), which keeps the host's
abstract sockets out for every session (17.9; review 3, R3-8); a machine-id of each app's own,
with `/sys` narrowed to what GPU drivers need, once real GPUs show that safe (17.17; review 3, R3-7);
a filtered **AT-SPI proxy**, as Flatpak runs, so screen readers reach sandboxed apps
(17.17; review 2, F15); a file still to be made handed
over as a name in its folder (the document portal's `AddNamed`, 17.6.2; review 3, R3-16); and
**App categories** in the Catalog (a separate feature, not
sandboxing). The real-hardware validation still owed is the checklist in `local-proxy-test-plan.md`,
run by `scripts/sandbox/field-test.sh` against a probe app AppKata itself installs, in a throwaway
home.
