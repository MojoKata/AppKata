# AppKata — Building and releasing

How AppKata's release builds are made and finished for each platform. Requirements are in
[`requirements.md`](requirements.md) (packaging: 1.6).

Status: the Linux AppImage (`scripts/build-appimage.sh`, `scripts/test-appimage.sh`), the
Windows installer (`scripts/build-windows.sh`, `scripts/test-windows-vm.sh`) and the
macOS hand-off (`scripts/package-macos.sh`, `packaging/macos/mac-sign.sh`) exist. The steps
marked **(planned)** don't exist yet.

## Running from source, tests and screenshots

```sh
"$(scripts/python-standalone.sh)" -m venv .venv && .venv/bin/pip install -e . pytest   # the release's Python (1.2)
.venv/bin/python -m pytest                 # unit and integration tests (no network needed)
scripts/test-tier1.sh                      # the same in a container, on a host whose glibc is older than 2.34
scripts/demo_data.py build build/tour-data && scripts/demo_data.py sync build/tour-data \
    && scripts/demo_data.py finish build/tour-data
scripts/test-layout.sh                     # the tour in tier 1's container: no text drawn outside its box
scripts/test-layout.sh --shots             # the same, and its screens replace screenshots/linux
scripts/test-screenshot-text.sh            # after any screenshots are made again: no private name or other repository address in them
```

Which tests run when, on which environment, and how long each takes is in [`testing.md`](testing.md).
The sandbox's own runs are in containers and VMs (`scripts/test-sandbox.sh`; what each shows is in
[`app-sandboxing.md`](app-sandboxing.md), "Tests, in four tiers"): `launcher` (Linux Mint 22.3),
`launcher-lmde7` (LMDE 7), `launcher-vm` (Ubuntu 24.04 under KVM, the AppArmor profile applied),
`launcher-vm26` (Ubuntu 26.04 under its own bwrap profile), and on Mint 22.3 `filedialogs`,
`consumers`, `wayland`, `kwin` and `inputmethod`, with `filedialogs-lmde7` and `kwin-lmde7` on LMDE 7
(real toolkits, the real portal, headless sway, mutter and kwin, PipeWire, IBus and Fcitx 5). Each
verdict harness prints `EXPECTED: ok` or exits 1.
Run the launcher tiers after any change to `src/appkata_core/sandbox.py` or `install.py`, and the
verdict harnesses after a change to the proxy rules, the shim, the marker or the launcher's
environment words.

`--tour DIR` drives the real UI through every screen of the mockups (`src/appkata/tour.py`) and
saves `DIR/{dark,light}/<screen>.png`. It runs offscreen, so it works over SSH and in
containers. Its window is at the design point (requirement 5.2.1): 1920 × 1040 offscreen and, on
Windows, what the screen leaves beside the taskbar (`test-windows-vm.sh` sets the VM's screen to
1920 × 1080 for it). Tier 1's container prefers Nimbus Sans for sans-serif, the font the Linux
screenshots were first taken with, and the screenshots come from it (`--shots`), so they're the
same on any host, even one whose glibc can't run the release's PySide6. `APPKATA_TOUR_THEMES=dark` limits it to one theme; `--tour-only A01-apps,C01-catalog`
to some screens. On each screen it saves, it checks every visible text against the card, chip,
menu or dialog it is drawn in (`src/appkata/layout.py`). It writes what runs past to
`DIR/layout.txt` and exits 1 if anything does, apart from what `STILL_OUTSIDE` in `tour.py` lists.
`scripts/test-layout.sh` runs it on `build/tour-data` in tier 1's container. Run it after a change
to the QML. `tests/test_layout.py` opens the Install dialog with long values (Windows' paths, long
names) and checks it the same way in tier 1.

`scripts/demo_data.py sync` needs github.com. It syncs again any app whose sync failed (GitHub answers
5xx at times), and stops if one still has: its message would show in the screenshots.
`scripts/demo_data.py check DIR` says so of existing demo data, and `retry DIR` syncs those apps again;
`finish` checks that first. `scripts/test-layout.sh` and the Windows VM's tour first run `stage`,
which sets what the screens show of time as of that day: the minimum age, so that Zettlr's newest
release is held with 4 days to go, and the last sync and the Trusts', 50 minutes back. Then all of `check`:
it also takes each claim `screenshots/README.md` makes about a screen's data (`PROMISES` in the
script), works out what the app shows on Linux and on Windows that day, and stops on a claim the
data doesn't keep, apart from what `STILL_WRONG` lists (review 3, R3-24). Without a token, GitHub's API allows 60 requests
an hour per IP address, shared with everything else on that address; when it runs out,
AppKata reads releases from github.com's pages instead (requirement 2.4.1), so the sync still
completes. `GITHUB_TOKEN=… scripts/demo_data.py sync DIR` uses the API throughout.

## Before tagging a release

1. `.venv/bin/python -m pytest` green, and the sandbox tiers above if anything under
   `src/appkata_core/sandbox.py`, `install.py` or the launcher goldens changed since the last tag.
2. **Read github.com both ways** (review 3, R3-23): `scripts/compare_github_paths.py` reads the demo
   data's projects through GitHub's API and through github.com's pages, which AppKata falls back to
   when the API's hour runs out (requirement 2.4.1), and exits 1 where the two disagree. It needs
   the network and about one API request per project; `GITHUB_TOKEN` raises the limit.
3. **Freeze the release's on-disk state** for the upgrade tests, and commit it with the tag:
   ```sh
   UPDATE_STATE=<version> .venv/bin/python -m pytest tests/test_sandbox_state.py
   git add tests/data/state/<version>.json
   ```
   `tests/test_sandbox_state.py` thaws every file in `tests/data/state/` — the rows and files an
   installed, sandboxed app has after *that* release — into the current code on every test run,
   so a later AppKata is shown to read, heal, change and remove what an earlier one left. A
   release without its snapshot is a release the upgrade tests know nothing about. Drop a
   snapshot only when its release is no longer one AppKata upgrades from.
4. Regenerate the screenshots if a screen changed (above), and check `git diff --stat screenshots`.
5. Build (below), and check each release file's `.sha256`.
6. **The field test by hand** (`scripts/sandbox/field-test.sh`, from the commit being tagged,
   without `--non-interactive`), on real hardware with a logged-in desktop: the questions no tier
   answers ("What it asks the tester" in `docs/local-proxy-test-plan.md`; the environments are in
   `docs/testing.md`, "By hand, before a release"). Each run is posted to the release's tracking
   issue on GitHub, as `testing.md` ("Tracking the runs on GitHub") describes; until that is set up,
   once the repository is published, keep each run's `.tar.gz` with the release.

## Overview

| Platform | Built on | Output | Finished on |
|---|---|---|---|
| Linux x86_64 | Linux, in an Ubuntu 22.04 container | AppImage, AppKata's only Linux form (1.6) | the same; tested in Mint/Ubuntu containers |
| Windows 10 22H2, Windows 11 x64 | Linux (PyInstaller + Inno Setup under Wine, in Docker) | `AppKata-<version>-setup.exe` | the same; tested in a Windows 10 VM; signing needs a code-signing certificate |
| macOS 13+ (universal2) | Linux: unsigned `AppKata.app` | `AppKata-<version>-macos-unsigned.tar.gz` | **a Mac** (an Intel MacBook is fine): `mac-sign.sh` → signed, notarized `AppKata-<version>.dmg` |

Every release file gets a `.sha256` next to it in `releases/`.

## Linux

### AppImage

```sh
scripts/build-appimage.sh      # → releases/AppKata-<version>-x86_64.AppImage + .sha256 (about 98 MB)
scripts/test-appimage.sh       # runs it in Mint containers, checks what it takes from the host, starts it on each 1.1 desktop
```

`build-appimage.sh`:

1. Downloads the newest **python-build-standalone** CPython of the series in `packaging/versions.env`
   (requirement 1.2) for x86_64 (glibc 2.17+), found on its GitHub release page, and checks it
   against the release's `SHA256SUMS`.
2. Installs **PySide6-Essentials** into it from PyPI and removes what AppKata doesn't use (Qt 3D,
   PDF, the virtual keyboard, translations, pip, tkinter, tests), and adds the five xcb-util
   libraries Qt's X11 plugin needs and no Debian-family desktop installs (`libxcb-cursor`, `-icccm`,
   `-keysyms`, `-image`, `-render-util`; review 3, R3-32).
3. Copies `src/appkata` and `src/appkata_core`, precompiles everything, and adds `AppRun`
   (which sets `PYTHONDONTWRITEBYTECODE`), the desktop entry, the SVG icon and a 256 px PNG rendered
   from it (for the first-start install, requirement 2.11.3.1).
4. Packs it with **appimagetool** (run with `--appimage-extract-and-run`, so FUSE isn't needed
   on the build machine) and writes the `.sha256`.

Downloads are cached in `build/appimage-cache`. The build runs in an Ubuntu 22.04 container
(`appkata-build-jammy`): PySide6 6.10 and later need glibc 2.34, which an older build host lacks, and
Ubuntu 22.04's 2.35 is the oldest 1.1 supports, so the result runs on every platform 1.1 names (it
was built on Rocky Linux 9 until RPM support retired). Everything else the AppImage needs it takes
from the desktop: the libraries in `packaging/appimage-host-libs.txt` (requirement 1.6).

`test-appimage.sh` starts a Linux Mint 22.3 container offscreen, checks `--version`, runs part of the
screenshot tour on the demo data (`build/tour-data`, or the folder given), then copies the AppImage
to `/tmp` and runs `--install-self` (requirement 2.11.3.1): it checks the copy and its
`AppKata.AppImage` link in `~/bin/apps/appkata/`, `appkata.desktop`, both icons, and that the
installed copy starts. Screenshots land in `build/appimage-test/`. The tour runs offscreen, so two
more steps check what a desktop session loads (review 3, R3-31, R3-32):

- **hostlibs**: a probe in the Mint 22.3 desktop image loads the X11 and Wayland plugins, the image,
  icon and input-method plugins and Qt's TLS backend; `scripts/appimage_host_libs.py` checks that
  everything they and the tour need from the host is in `packaging/appimage-host-libs.txt`, and that
  each listed one is still needed.
- **desktops**: AppKata started as a user would, on X11 (Xvfb) and on Wayland (weston), in the
  desktop package sets of the platforms 1.1 names: Ubuntu 22.04 and 24.04 (`ubuntu-desktop-minimal`),
  Linux Mint 22.3 and LMDE 7 (`mint-meta-cinnamon`). Each must keep running, load the session's Qt
  plugin, show a window on X11, and load no host library that the desktop's own packages don't
  provide. The images (`appkata-desktop-*`, 2 to 4 GB each) are built once. Until RPM support
  retired, Fedora 39 and 44, Rocky 9 and Debian 12 ran in this step too.

`APPIMAGE_STEPS="mint hostlibs desktops"` picks the steps.

appimagetool embeds the static type-2 runtime, so the AppImage needs only `fusermount` or
`fusermount3`, not `libfuse2`: checked on Ubuntu 24.04 with only `fuse3` installed. Without FUSE
at all (some containers), `./AppKata-*.AppImage --appimage-extract-and-run` works too.

### Testing package channels

```sh
scripts/test-channels.sh                 # all runs: ubuntu ubuntu-pk mint
scripts/test-channels.sh ubuntu mint     # some of them
```

Each run starts a disposable container with `--privileged` (flatpak's bubblewrap needs to make
namespaces) and runs `scripts/channels_e2e.py` as root against local repositories only, so no test
needs Flathub:

| Run | Image | Covers |
|---|---|---|
| `ubuntu` | ubuntu:24.04 | apt through the command line; a local Flatpak remote with a hand-built runtime and app |
| `ubuntu-pk` | ubuntu:24.04 | apt through PackageKit (`packagekitd` on a private system bus); adopting and uninstalling the distribution's `hello` |
| `mint` | linuxmintd/mint22.3-amd64 | apt through the command line |

The dnf runs (Fedora, Rocky Linux) retired with RPM support (requirement 1.1) and come back with it.

Package steps: install, a pending update, update, the metapackage refusal, the cascade
confirmation, waiting for a held lock, adopting, uninstalling. Flatpak steps: install, a pending
update that adds a permission, update, the version log, mask and unmask, an update made outside
AppKata recorded in the Audit, uninstall, adopting.

### No Flatpak

AppKata isn't built as a Flatpak (requirement 1.6). To do its job from inside the sandbox it would
need the home folder (portable installs into `~/bin`), `--talk-name=org.freedesktop.Flatpak` (to run
host commands with `flatpak-spawn --host`) and `--system-talk-name=org.freedesktop.PackageKit` (package
channels, 16). That is the sandbox opened to the host, which Flathub is unlikely to accept and which
leaves the Flatpak no safer than the AppImage.

### No `.deb` or `.rpm`

A system package would put AppKata in the app menu with no first-run step. But it can't update
itself without competing with the package manager, so AppKata would only notify about its own
updates, unless it also published apt and dnf repositories. The AppImage carries everything AppKata
needs, updates itself (requirement 2.11.3) and installs itself into the app menu on first start
(2.11.3.1), so it is AppKata's only form on Linux (1.6).

## Windows

### The installer

```sh
scripts/build-windows.sh     # → releases/AppKata-<version>-setup.exe + .sha256 (about 36 MB; 1–2 minutes)
```

1. **PyInstaller under Wine** (`tobix/pywine:` the series in `packaging/versions.env`) builds the one-folder app
   `build/windows/dist/AppKata/appkata.exe` from `packaging/windows/appkata.spec`, with
   PyInstaller, PySide6-Essentials and `truststore` pinned in the script. `truststore` makes
   Python check TLS certificates with Windows itself: Python's own check sees only the root
   certificates already in Windows' store, and downloads from GitHub's file host failed without it. It bundles every module of `appkata`
   and `appkata_core` and the QML files (`_internal/appkata/qml`). pip downloads are cached in
   `build/wine-cache`.
   - Qt 6.10+ imports Windows' own ICU (`icuuc.dll`), which Wine lacks.
     Without it Qt won't load under Wine, and PyInstaller's Qt hook warns but collects no Qt
     plugins or QML, so the app can't start. The script compiles a stand-in
     (`packaging/windows/icuuc-stub.c`, MinGW in a `debian:12` container) into Wine's `system32`
     for the build only.
   - The script stops if the bundle lacks Qt's Windows platform plugin or the Basic controls. It
     also stops if the bundle carries any ICU DLL, the stand-in among them: the installed app
     must use Windows' own ICU.
2. The script removes the Qt parts AppKata doesn't use (translations, Quick 3D, PDF, the
   virtual keyboard, the software OpenGL fallback), leaving about 135 MB unpacked.
3. **Inno Setup under Wine** (`amake/innosetup`) builds the installer from
   `packaging/windows/appkata.iss` (requirement 15.10):
   - **Just me** by default, with no UAC prompt, into `%LOCALAPPDATA%\Programs\AppKata`
     (`PrivilegesRequired=lowest`). The dialog, or `/ALLUSERS`, installs for **Everyone** into
     `Program Files`.
   - A Start-menu shortcut with the AppUserModelID `AppKata.AppKata`, and the `appkata://`
     handler (`Software\Classes\appkata`, in HKCU or HKLM to match).
   - Its Uninstall entry is `{8E3B9C51-6A2D-4F7E-B1C4-3D5A7E9F0B12}_is1`, which AppKata reads
     to adopt its own installation (requirement 2.11.5). Don't change the `AppId`.
   - `/RELAUNCH=1` starts AppKata again when Setup finishes, even with `/VERYSILENT`; AppKata's
     own updates use it.
   - The uninstaller removes the start-at-login entry, offers to delete `%LOCALAPPDATA%\AppKata`
     (No by default, and kept when silent), and says the apps AppKata installed stay installed.

`packaging/windows/appkata.ico` is made from `src/appkata/qml/assets/appkata.svg` with
`.venv/bin/python packaging/windows/make_ico.py`; run it again when the logo changes.

Silent installs, as AppKata's own update and the test use them:

```
AppKata-<version>-setup.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /CURRENTUSER   (or /ALLUSERS, elevated)
```

### Signing (when a certificate is available)

Authenticode-sign `appkata.exe` before step 3 and the installer after it, with `osslsigncode`
or `jsign` and a timestamp server. Until then Windows shows "Unknown publisher", and SmartScreen
warns when the installer is downloaded with a browser.

### Testing in the VM

```sh
scripts/test-windows-vm.sh                    # install, check, uninstall
scripts/test-windows-vm.sh --shots            # also the screenshot tour → screenshots/windows/{dark,light}
scripts/test-windows-vm.sh --shots --tour-only A01-apps,C01-catalog
scripts/test-windows-vm.sh --tests            # also the unit tests, with Python on Windows
scripts/test-windows-vm.sh --e2e              # also real installs from GitHub (scripts/windows_e2e.py)
```

It uses the shared VM (below), starting it if needed, and:

1. Copies the newest `releases/AppKata-*-setup.exe` to `C:\Users\Public\appkata-test`.
2. Installs for the current user, silently, **without administrator rights**. The VM's SSH
   session is elevated, so Setup is run as a scheduled task in the signed-in console session
   with a limited token, as a normal user would run it.
3. Checks the files (including the QML), the HKCU Uninstall entry (and that there's none in
   HKLM), the `appkata://` handler and the Start-menu shortcut, and that `appkata.exe`
   starts and exits cleanly.
4. With `--shots`: copies the demo data (`build/tour-data`, from `scripts/demo_data.py`) with
   its absolute Linux paths rewritten for the VM, runs `appkata.exe --tour` in the console
   session and copies the screenshots back. The tour gets a neutral account's folders,
   `C:\Users\you` (made for the run, removed after), so the paths the screens show are the
   mockups', not the VM's account. The VM's screen is 1920 × 1080 while the tour runs
   (`scripts/windows-display.ps1`, not saved, since the VM can be shared), and the screens must
   come back 1920 × 1040. It prints the tour's `layout.txt` and fails if the tour found a text
   drawn outside its box, after uninstalling. Session 0 (plain SSH) has no real
   display: there the dialogs land off-centre. The demo data was made on Linux, so its installed apps show
   Linux file kinds (AppImage, .deb); the Windows-only screens are `W01` to `W03`, and the
   Linux-only ones (`LINUX_ONLY` in `tour.py`: the sandbox, package channels, the AppImage's first
   start) are left out.
5. With `--tests`: unpacks a Python of that same series for Windows (python-build-standalone from GitHub,
   checked against its `SHA256SUMS`) into `C:\Users\Public\appkata-py` the first time, adds
   pytest and truststore, and runs the whole suite. `tests/test_windows.py` has tests that run
   only on Windows: a portable app with its junction, Start-menu shortcut, `.cmd` command link
   on the PATH and a running copy that blocks its update; an app for everyone in locked-down
   folders; the registry entries; Authenticode and the Mark of the Web; which programs need the
   Visual C++ run-time. The trust tests need
   Git for Windows, which `--e2e` installs.
6. With `--e2e`: installs and uninstalls real releases through AppKata's own code: ripgrep
   (portable `.zip`), hyperfine (a `.zip` that needs the Visual C++ run-time: it's flagged, fails to
   start, then AppKata installs Microsoft's run-time, which stays installed, and it starts), WinMerge (Inno Setup, just me), KeePassXC (`.msi`, everyone, signed),
   MarkText (NSIS by electron-builder, just me), and Git for Windows (Inno Setup, everyone; left
   installed). Each checks the scope, the Uninstall entry, the signature, and that the
   uninstall removed it.
7. Uninstalls silently and checks that everything above is gone.

What these can't cover headless: a UAC prompt a person answers, SmartScreen's warning with the
Mark of the Web on, Windows 11's Snap Layouts (only the hit test that enables them is checked),
and Squirrel and `.msix` installs (no small FOSS release to test with).

Windows on arm64 isn't supported (requirement 1.1).

## macOS

The Linux build can't sign for Apple, so the release has two halves.

### 1. On the Linux VM: the hand-off tarball

The macOS build step (planned) assembles `build/macos/AppKata.app`:

- a universal2 (x86_64 + arm64) Python runtime from `python-build-standalone`,
- PySide6 universal2 wheels (`pip download --platform macosx_…_universal2 --only-binary=:all:`),
- AppKata's code, precompiled to `.pyc`, with `PYTHONDONTWRITEBYTECODE=1` set by the
  launcher, because anything written into the bundle after signing breaks the signature,
- a compiled (Mach-O) launcher as `Contents/MacOS/AppKata`, and `Info.plist` and
  `AppKata.icns`; no data files in `Contents/MacOS`.

Then:

```sh
scripts/package-macos.sh            # → releases/AppKata-<version>-macos-unsigned.tar.gz + .sha256
```

It refuses bundles with broken symlinks, warns about bytecode caches, and packs
`AppKata.app`, `mac-sign.sh`, `entitlements.plist` and `README-macos.txt` into one
folder, `AppKata-<version>-macos/`.

### 2. On the Mac: signing, notarizing, the .dmg

**One-time setup on the Mac**

1. `xcode-select --install` (Command Line Tools: `codesign`, `notarytool`, `stapler`).
2. A **Developer ID Application** certificate with its private key (a `.p12` from the Apple
   Developer account) imported into the login keychain. If macOS says it isn't valid, install
   Apple's "Developer ID - G2" intermediate certificate from
   <https://www.apple.com/certificateauthority/>.
3. Notarization credentials, saved in the keychain:
   ```sh
   xcrun notarytool store-credentials appkata-notary --apple-id you@example.com --team-id TEAMID
   ```
   It asks for an app-specific password (appleid.apple.com → Sign-In and Security →
   App-Specific Passwords). An App Store Connect API key works too
   (`NOTARY_KEY`, `NOTARY_KEY_ID`, `NOTARY_ISSUER`).

**Each release**

1. Copy the **`.tar.gz` file and its `.sha256`** to the Mac (AirDrop, USB, `scp` of the
   file). Don't copy an unpacked folder: shared folders and some copy tools drop the
   symlinks the Qt frameworks need.
2. Unpack and check:
   ```sh
   shasum -a 256 -c AppKata-*-macos-unsigned.tar.gz.sha256
   tar -xzf AppKata-*-macos-unsigned.tar.gz
   cd AppKata-*-macos
   ./mac-sign.sh --check --profile appkata-notary
   ```
   `--check` changes nothing. It checks:
   - the Mac (macOS 13+, the Command Line Tools),
   - the bundle (Info.plist, the Mach-O launcher, no broken symlinks, no data files in
     `Contents/MacOS`, both architectures in every binary, free space),
   - the certificate (valid, with a trial signature that needs the timestamp server),
   - the notarization credentials (a call to Apple's notary service).
3. Sign, notarize and build the disk image:
   ```sh
   ./mac-sign.sh --profile appkata-notary
   ```
   After a summary and a confirmation it:
   1. signs every library, framework and executable from the inside out, with the hardened
      runtime and a secure timestamp (`entitlements.plist` for executables),
   2. verifies that every binary has a valid signature, a timestamp and the same Team ID,
   3. notarizes the app and staples its ticket (so it opens offline once copied out of the
      `.dmg`),
   4. builds `AppKata-<version>.dmg` (the app and an Applications shortcut), signs it,
      notarizes it and staples it,
   5. checks both with Gatekeeper (`spctl`: "Notarized Developer ID") and writes the
      `.sha256`.

   Notarization usually takes 1–10 minutes per upload. Everything is logged to
   `mac-sign-<date>.log`.
4. Publish `AppKata-<version>.dmg` and `AppKata-<version>.dmg.sha256`. Opening the `.dmg` on
   another Mac is a good final check.

**When something fails**, the script stops with what went wrong and what to do. It never
publishes anything, and it's safe to run again from the start. Common cases:

| Message | Cause |
|---|---|
| Broken symlinks | The folder was copied instead of the `.tar.gz`. |
| Binaries missing an architecture | A build problem: ask for a new tarball. |
| Certificate isn't valid | The intermediate certificate is missing, or the certificate has expired. |
| Trial signature failed | The keychain is locked, or the timestamp server can't be reached. |
| Notary credentials rejected | The app-specific password changed, or a new Apple agreement needs accepting. |
| Apple rejected the app (Invalid) | Apple's report (`notary-app-<id>.json`) lists each problem; a build fix is needed. |

`./mac-sign.sh --no-notarize` signs and builds the `.dmg` without contacting Apple, for a
local look; it opens only with right-click → Open.

**Testing.** `mac-sign.sh` was exercised on Linux against stubs of the macOS tools (success,
and each failure above). Its first run on a real Mac is the real test. On an Intel Mac, only
the x86_64 half of the app can be run; test the arm64 half on an Apple silicon Mac or a
`macos-14` CI runner.

## Shared Windows test VM

The Windows tests run in a Windows 10 Pro 22H2 VM that the machine's other projects can share, by
the protocol in [`coworker/vm`](../coworker/vm/README.md). It is `win10` in `$VM_DIR` (`~/vm`
unless `local.env` says otherwise; `WINDOWS_VM` names another), and its folder's `vm.env` says how
to reach it: its container, SSH port, account and key, the same for every project.
`scripts/test-windows-vm.sh` claims it for `appkata`, holds its lock for the whole run (another
project's run waits, or AppKata's waits for it), starts it if it isn't running and leaves it
running. AppKata's files go in `C:\Users\Public\appkata-test` and `appkata-py`, the screen size it
sets is put back and not saved, and what it installs it uninstalls, except Git for Windows and the
Visual C++ run-time from `--e2e`.

What the tests need of the VM, and how this one was made:

- **Windows 10 Pro 22H2, unactivated** (a watermark only): not an evaluation, so it doesn't expire.
  An evaluation's licensing service shuts Windows down an hour after each start once its 90 days
  are up, and a Windows 11 Enterprise evaluation build never finished installing.
- **Held on Windows 10 22H2** by Windows Update's target-release policy (`TargetReleaseVersion` 1,
  `ProductVersion` "Windows 10", `TargetReleaseVersionInfo` 22H2): 1.1's Windows 10 floor, with
  Windows 11 never offered.
- **OpenSSH Server** with key sign-in for an administrator account and PowerShell as its shell,
  and a signed-in console session for that account (the tour and the limited-token installs run
  there, through a scheduled task).
- It runs in Docker (`dockurr/windows`, `VERSION=10`, KVM), whose OEM hook installs OpenSSH and
  sets the policy at the end of setup; its screen is on port 8006 (noVNC) and RDP on 3389. Built
  from scratch, setup takes 30 to 60 minutes. The VM's own `README.md` says how to rebuild it,
  keeping its account, key and ports.
