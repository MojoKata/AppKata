# R1. Platform and architecture

R1.1. AppKata runs on what its tests cover (`docs/testing.md`):

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

R1.2. Everything is written in Python, and AppKata runs on the Python its release carries: the
AppImage, the Windows installer and, once built, the macOS app each carry one, of one version for
all, with one PySide6, both set in `packaging/versions.env`. Running from source is for development
only, never a way to install AppKata, and uses that same version (`scripts/python-standalone.sh`
fetches it); the tests run AppKata's code on it too (review 3, R3-21: from source on Debian 12's own
Python 3.11.2, no tarball could be installed). The one exception is what a sandboxed app's launcher
runs on the computer's own `python3`, the file-argument helper and the `xdg-open` shim (17.6.2,
17.6.3): they work on the `python3` and `gi` of every platform whose sandbox 1.1 supports, the oldest
being Mint 22.3's and Ubuntu 24.04's 3.12.
The GUI uses PySide6 (Qt 6 with QML) and the `Basic` Qt Quick Controls style; its look is 5.2.

R1.3. AppKata is one desktop-user process with no privileged service. When an install,
update or uninstall needs administrator rights, AppKata asks for them for that action only:

- `pkexec` on Linux.
- UAC on Windows (15.2).
- The system authorization prompt on macOS.

R1.4. Git operations use the system `git`, which must be 2.34 or newer for SSH signature
verification. If `git` is missing, AppKata explains how to install it.

R1.5. Nostr access (ngit repositories, NIP-05, kind-0 profiles) uses a configurable list of
relays (11.1).

R1.6. Distribution:

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

R1.7. **Running in the background.** AppKata has a tray icon (the menu-bar extra on macOS).

R1.7.1. Closing the window leaves AppKata running in the tray, where it keeps checking for
updates (9.3).

R1.7.2. The tray menu has **Open AppKata**, **Check for updates**, an "N updates available"
item that opens the Apps view, and **Quit AppKata**.

R1.7.3. Quitting stops all background work. While an install is running or queued, **Quit**
(from ⋮, the tray, or the shortcut, 5.4) first asks "Quit while installing?" (5.8), listing
the installs. Quitting stops them; a partial download is kept and resumed next time (4.8.2).

R1.7.4. A setting starts AppKata in the tray at login (11.1.1). It is off by default.

R1.8. Local data (Sources, Trusts, Authorities, release metadata, images, READMEs) is stored
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

R1.9. **One AppKata at a time.** Starting AppKata while it's already running (from the app menu,
at login, or by an `appkata://` link, 11.3) hands its arguments to the running AppKata over a
local socket (`QLocalServer`), one per user and data folder, and exits. The running AppKata shows its window, and for a
link the Add source dialog.
