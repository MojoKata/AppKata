# GitHub Actions for building and publishing releases

Whether AppKata needs its own build machines to use GitHub Actions (it doesn't), what the runners cost,
how each platform's build maps onto them, and a starting `release.yml`. Companion to
[`build.md`](build.md) (how the artifacts are built) and the publish command in the README notes.

Status: **no workflow exists yet** (`.github/workflows/` is absent). Releases are built with
`scripts/build-*.sh` on a Linux machine and published by hand with `gh release create`. This document is
the plan for moving that to Actions.

**Partly out of date (2026-10-25):** the AppImage now builds in an Ubuntu 22.04 container on glibc
2.35 ([`build.md`](build.md), "AppImage"), not on an old-glibc host; this plan gets refreshed with
the CI work.

## Do we need our own build servers?

**No.** GitHub provides **GitHub-hosted runners**: for each workflow job it spins up a fresh,
managed VM (or container), runs your steps, and tears it down. Nothing persists between runs by design.
You get Linux, Windows and macOS out of the box:

- `runs-on: ubuntu-latest`
- `runs-on: windows-latest`
- `runs-on: macos-latest` (Apple Silicon; `macos-13` for Intel)

You **can** register **self-hosted runners** (your own VM or machine) when you
need specific hardware or a controlled toolchain — but that's opt-in, not a requirement.

## Cost and minutes

- **Public repositories:** GitHub-hosted *standard* runners are free, subject to concurrency limits.
- **Private repositories:** a monthly free allotment, then paid, metered with per-OS multipliers —
  **Linux ×1, Windows ×2, macOS ×10**. macOS is the expensive one.

(Quotas and prices drift; confirm current numbers in GitHub's billing docs. The macOS multiplier being
the costly one has been stable.)

The runner compute is free/ephemeral; the only thing you must supply is **secrets** (signing
certificates, notarization credentials, a token for uploading) — stored as encrypted
repository/organization **Actions secrets**.

## Mapping AppKata's three targets onto runners

| Target | `build.md` today | On Actions | Watch out for |
|---|---|---|---|
| **Linux AppImage** | built on an **old-glibc host on purpose** (old glibc floor 2.17+, so it runs on Mint 21+, Ubuntu 22.04+, Debian 12+, Fedora 39+) | `ubuntu` runner, but **build inside an old-glibc container** to keep the floor | `ubuntu-latest` has a newer glibc; see below |
| **Windows installer** | PyInstaller + Inno Setup under **Dockerized Wine on Linux** | `windows-latest` natively (simpler), or keep the Wine image on an `ubuntu` runner | Authenticode signing needs a cert in secrets |
| **macOS `.dmg`** | unsigned tarball on Linux, then **handed off to a physical Mac** to sign/notarize | `macos-latest` can sign + notarize + build the `.dmg` directly — **removes the Mac hand-off** | ×10 minutes; needs Apple cert + notary creds in secrets |

### The Linux glibc caveat (the one real gotcha)

`scripts/build-appimage.sh` bundles its own CPython (python-build-standalone, glibc 2.17+) and
PySide6 manylinux wheels, which are old-glibc-safe. The risk is anything that links against the
*build host's* glibc. On `ubuntu-latest` (newer glibc) the produced AppImage could quietly raise its
minimum glibc and stop running on older distros — the very thing an old-glibc build host avoids. Two ways to keep
the floor on a hosted runner:

- run the build **in a container**: `container: quay.io/pypa/manylinux2014_x86_64` (glibc 2.17), or an
  old base image; or
- point a **self-hosted RHEL 8 runner** at the repo and run `scripts/build-appimage.sh` unchanged.

`appimagetool` itself is downloaded by the script (cached in `build/appimage-cache/`), so it doesn't
constrain the host.

## A starting `release.yml`

Triggered on a `v*` tag (the tag convention is `v<version>`, matching `AppKata-<version>-…` filenames
and `__version__` in `src/appkata_core/__init__.py`). It builds the AppImage in an old-glibc container
and the Windows installer natively, then publishes both **with their `.sha256` sidecars** — which
AppKata needs to verify downloads (4.4, see [`gpg.md`](gpg.md)). macOS is left as a later add so the
first workflow doesn't incur the ×10 minutes.

```yaml
name: Release
on:
  push:
    tags: ["v*"]
permissions:
  contents: write            # gh/action-gh-release needs this to create the Release
jobs:
  linux:
    runs-on: ubuntu-latest
    container: quay.io/pypa/manylinux2014_x86_64   # glibc 2.17 floor (see the caveat above)
    steps:
      - uses: actions/checkout@v4
      - run: scripts/build-appimage.sh             # → releases/AppKata-<ver>-x86_64.AppImage + .sha256
      - uses: actions/upload-artifact@v4
        with: { name: linux, path: releases/AppKata-*-x86_64.AppImage* }
  windows:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v4
      # PyInstaller + Inno Setup (natively, instead of the Dockerized-Wine path in build.md)
      - run: scripts/build-windows.ps1             # to be written; mirrors build-windows.sh
      - uses: actions/upload-artifact@v4
        with: { name: windows, path: releases/AppKata-*-setup.exe* }
  publish:
    needs: [linux, windows]
    runs-on: ubuntu-latest
    steps:
      - uses: actions/download-artifact@v4
        with: { path: releases, merge-multiple: true }
      - uses: softprops/action-gh-release@v2       # or: gh release create "$GITHUB_REF_NAME" releases/*
        with: { files: releases/* }
```

Notes:
- **`scripts/build-windows.sh` is Linux/Wine-oriented**; a native `windows-latest` job needs a
  PowerShell equivalent (or run the existing Wine image on an `ubuntu` runner with Docker). Pick one
  before wiring this up.
- Signing (Authenticode, Apple) is intentionally **not** in this sketch — add it once the certs are in
  Actions secrets; until then Windows shows "Unknown publisher" (as `build.md` already notes) and
  macOS isn't built here.
- **Which repo to release to:** AppKata's own updater reads releases from
  `APPKATA_REPO = github.com/MojoKata/AppKata` (its self-Source), not from a fork. The workflow runs
  in whatever repo it lives in and publishes there, so put it in that repository.

## Manual publishing (until the workflow exists)

```sh
VER=$(sed -n 's/^__version__ = "\(.*\)"/\1/p' src/appkata_core/__init__.py)
gh release create "v$VER" --repo MojoKata/AppKata --title "AppKata $VER" --notes "…" \
  releases/AppKata-$VER-*.AppImage releases/AppKata-$VER-*.AppImage.sha256 \
  releases/AppKata-$VER-setup.exe   releases/AppKata-$VER-setup.exe.sha256
```

See [`build.md`](build.md) for building each artifact and [`gpg.md`](gpg.md) for what the `.sha256`
sidecars (and, in future, signatures) are checked against.
