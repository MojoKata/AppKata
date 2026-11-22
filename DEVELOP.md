# Developing AppKata

What's built so far, and how to run AppKata from source and try it with the demo data. The rest is
in [`docs/`](docs/): building and the screenshots in [`build.md`](docs/build.md), which tests run
where in [`testing.md`](docs/testing.md), CI and the Pages site in
[`github-workflows.md`](docs/github-workflows.md), releasing in [`RELEASE.md`](docs/RELEASE.md), and
what AppKata does in the [requirements](docs/requirements/README.md). Users start at the
[README](README.md).

## Status (0.1.0: Linux and Windows)

| Area | State |
|---|---|
| Apps, Catalog, Sources and Audit perspectives, App Detail panel (with a version list), review dialog, tray icon | Done (PySide6/QML) |
| Audit: an immutable record of installs and changes to Sources, Trusts, Authorities and reviews (You / Sync) | Done |
| App log: two 2 MB files, "Show app log" in the ⋮ menu | Done |
| Explore: search GitHub, GitLab, Codeberg and ngit for projects to add | Done; live-tested on GitHub and GitLab.com |
| Releases from GitHub (with a no-API fallback when rate-limited), GitLab, Forgejo/Gitea; forge detection on other hosts | Done; live-tested on GitHub and GitLab.com; Forgejo/Codeberg against recorded responses (the machine it was developed on couldn't reach Codeberg) |
| Icons, hero images, README summaries, AppStream metainfo | Done |
| Trusts: `AppKata.md` parsing, signed-change checks (SSH in pure Python, OpenPGP via gpg), new signers, rewritten history, veto and averages | Done, tested with real signed repositories |
| Your reviews: edit the table row and section, commit, push only signed commits | Done |
| Installing on Linux: AppImage, tarball, Flatpak bundle, `.deb`/`.rpm` (through PackageKit or pkexec, with a dry run first); checksums; apps installed outside AppKata | Done (AppImage, tarball and packages tested end to end) |
| Portable vs system package decided from the file; install options asked on the first install only when needed, saved per app | Done |
| Installing on Windows: portable `.zip`/`.exe` first, then `.msi`, `.exe` installers (Inno, NSIS, electron-builder, WiX, Squirrel) and `.msix`; Just me or Everyone; junctions, Start-menu shortcuts, `.cmd` command links; uninstalling through the registry; files in use; Authenticode; Mark of the Web; the Visual C++ run-time (MSVCRT) | Done; real installs of six apps tested in a Windows 10 VM; UAC prompts, SmartScreen and Windows 11 Snap Layouts need a manual check |
| Pinning, minimum age, held updates, background sync, notifications; install queue with progress, Cancel and resumable downloads; apps that update themselves | Done |
| AppKata's own AppImage (the only Linux download: no Flatpak, `.deb` or `.rpm`, R1.6), installing itself on first start | Done: `scripts/build-appimage.sh`, tested on Mint 21.3 and 22.1 (`scripts/test-appimage.sh`) |
| AppKata's Windows setup (per user by default, no UAC prompt) and its own updates | Done: `scripts/build-windows.sh`, tested by `scripts/test-windows-vm.sh`; signing needs a certificate |
| App sandboxing on Linux (portable apps and AppImages in bubblewrap: Off/Standard/Strict, templates, per-app grants, filtered D-Bus, the AppArmor pkexec setup) | Implemented, reviewed ([`docs/reviews/`](docs/reviews); [A1](docs/architecture/A1-app-sandboxing/README.md), [R17](docs/requirements/R17-app-sandboxing/README.md); mechanisms validated in containers + a KVM VM, `scripts/sandbox/`; real-desktop checklist [`docs/local-proxy-test-plan.md`](docs/local-proxy-test-plan.md)) |
| macOS app and installers | Planned ([`docs/build.md`](docs/build.md)); the signing hand-off exists |
| ngit / Nostr (Zapstore events), Nostr Trusts | Planned |
| Version reviews in AppKata.md (`## <App>[<version>]` with Details and Settings), per-version scores, vetoes of an installed version, the review dialog's Version select | Done |
| Package channels on Linux: Flathub and apt/dnf (AppStream discovery, Explore, install cards, adopt, track, Flatpak permissions; the system's updates first; PackageKit or the command line) | Done; tested end to end in Ubuntu, PackageKit, Mint, Fedora and Rocky containers (`scripts/test-channels.sh`) with local repositories, where Flathub can't be reached. Not yet: installing an older Flatpak commit from Versions |
| Settings: general, reviews, updates, portable apps (install folder, app menu, stable name, command links), tokens, relays, data locations, import/export, `appkata://` links; Source settings (forge, track only, pre-releases, download filter) | Done |

## Run from source (development)

For development only; AppKata is installed from its AppImage (R1.6). It runs on the
Python its release carries (`packaging/versions.env`), which `scripts/python-standalone.sh` fetches:

Its PySide6 needs glibc 2.34 or newer; on an older machine (RHEL 8), `scripts/test-tier1.sh` runs
the tests in a container instead.

```sh
"$(scripts/python-standalone.sh)" -m venv .venv
(. packaging/versions.env && .venv/bin/pip install -e . "PySide6-Essentials==$PYSIDE" "shiboken6==$PYSIDE" $PYTEST)   # the release's PySide6
.venv/bin/appkata                    # or: .venv/bin/python -m appkata
.venv/bin/python -m pytest           # 92 tests (6 run only on Windows): core, trust signatures, installs, reviews, forges, audit, log, explore, Windows
```

Needs git 2.34+ and, for OpenPGP-signed Trusts, gpg.

## Try it with demo data

```sh
scripts/demo_data.py build build/demo     # signed demo Trusts, your AppKata.md, Sources (offline)
scripts/demo_data.py sync build/demo      # fetch the real apps from GitHub
scripts/demo_data.py finish build/demo    # some "installed" apps, a pin and a minimum age
scripts/demo_data.py restore build/demo   # or all three without the network, from the snapshot in tests/data/demo
APPKATA_DATA=build/demo XDG_DATA_HOME=build/demo/xdg .venv/bin/appkata
APPKATA_DATA=build/demo XDG_DATA_HOME=build/demo/xdg .venv/bin/appkata --tour build/my-tour   # every screen, as PNGs
```

The apps are real GitHub projects; the reviewers, their keys and "TurboShield VPN" are made up.

The Linux screenshots are this tour, made by CI on its own demo data (`scripts/test-layout.sh`,
[`build.md`](docs/build.md#running-from-source-tests-and-screenshots)) and published on the
[screenshots page](https://mojokata.github.io/AppKata/screenshots/).
