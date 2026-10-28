# GitHub Actions: CI, the signed AppImage and the draft release

What [`.github/workflows/ci.yml`](../.github/workflows/ci.yml) runs, when, and why it is built the
way it is: the CI walk thru's decisions of 2026-10-24. One-time setup (the repository's settings,
the release key) is in [`GENESIS.md`](../GENESIS.md); building by hand and the release checklist,
in [`build.md`](build.md); what users can check a download against, in [`gpg.md`](gpg.md).

## What runs when

| Event | Jobs | What it leaves |
|---|---|---|
| A pull request, a push to `master` | `tier1`, `appimage`, `windows`, then `ci` | the AppImage and `setup.exe`, each with its `.sha256`, unsigned, as the run's artifacts (`appimage`, `windows`; GitHub keeps them 90 days) |
| A `v*` tag | the same, built without the caches, and `version`; then, once the owner approves, `sign` and `release` | a **draft** release: the AppImage, its `.sha256` and `.asc`, `setup.exe` and its `.sha256` |

All of it runs on GitHub's hosted `ubuntu-24.04` runners, free for a public repository. Each job runs
the script it would run on a development machine, so a CI failure reproduces locally:

| Job | Runs | About |
|---|---|---|
| `tier1` | `scripts/test-tier1.sh` | 2 min |
| `appimage` | `scripts/build-appimage.sh` | 1 min |
| `windows` | `scripts/build-windows.sh`: PyInstaller and Inno Setup under Wine, in Docker, as the Windows VM tests it (`build.md`, "Windows") | 3 min |
| `ci` | passes only when the three above did | |
| `version` | tags only: the tag must be `v` and `__version__` (`src/appkata_core/__init__.py`) | |
| `sign` | tags only, in the `release` environment: signs the AppImage | |
| `release` | tags only: `gh release create --draft` with every file | |

`ci` is the one check the `master` ruleset requires (GENESIS.md, step 4): a pull request can't
merge while tier 1 fails or either build breaks, and jobs can be added without changing the ruleset.
The tiers that need KVM or a desktop (2 and 3, [`testing.md`](testing.md)) stay on the development
machine: GitHub advises against self-hosted runners for a public repository, since anyone can open a
pull request and run code on them.

## Signing

The AppImage is signed with the **release key**'s signing subkey, as a separate ASCII-armored
`AppKata-<version>-x86_64.AppImage.asc`. The AppImage's own bytes don't change, so its `.sha256`
describes the same file, and AppKata's updater, which skips `.asc` files (`assets.py`), is
unaffected. The main key stays offline with the owner; GitHub holds only a copy of the subkey, under
a passphrase of its own (GENESIS.md, step 7). A leaked copy is revoked and replaced without changing
the fingerprint users check.

Only the `sign` job sees the key:

- The subkey and its passphrase are secrets of the **`release` environment**, which deploys only for
  `v*` tags and only after the owner approves the run. The approval comes after both builds have
  finished, so the owner approves files whose SHA-256s are known: each build job posts them as a
  `sha256` notice, which `publish.sh release` shows before asking.
- The job checks out nothing and runs nothing it downloads. It takes the `appimage` artifact,
  checks it against its `.sha256`, imports the subkey into a throwaway keyring with the runner's
  own gpg, signs, verifies the signature and keeps the `.asc` as the `signature` artifact.
- The **`tags` ruleset** lets only admins create, move or delete a tag, so a release starts only
  when an admin tags it.

To check a download by hand:

```sh
gpg --import appkata-release-key.asc     # packaging/appkata-release-key.asc, or from keys.openpgp.org
gpg --verify AppKata-<version>-x86_64.AppImage.asc AppKata-<version>-x86_64.AppImage
```

The fingerprint `gpg` names must be the one the README publishes (with the first signed release,
GENESIS.md step 7). Windows' installer isn't signed yet
(Authenticode needs a certificate, `build.md`, "Signing"); it has its `.sha256`.

## The draft, and publishing it

A published release reaches every AppKata at its next sync, since AppKata takes its own updates from
this repository's releases (requirement 2.11). So CI makes a **draft**, which only the repository's
writers see, and the owner publishes it after the checks no runner can make (`build.md`, "Before
tagging a release": the field test by hand, which can use the draft's files).

`scripts/publish.sh` walks through it:

- `release`: checks that `master` is clean and current, tags `v<version>` and pushes it, waits for
  the run, shows the two `sha256` notices, approves the signing, waits for the draft and verifies it.
- `resume`: the same from "waits for the run", after an interruption.
- `verify [VERSION]`: downloads the draft or release, checks that it holds exactly the five files,
  each against its `.sha256`, and that the AppImage's signature is the release key's
  (`packaging/appkata-release-key.asc`, matched by fingerprint).
- `publish [VERSION]`: verifies again and publishes the draft as the latest release.

With **immutable releases** on (GENESIS.md, step 8), a published release's files and tag can't be
changed, and GitHub adds a release attestation (`gh release verify v<version>`). A bad release is
fixed by a new version, never in place.

## What the builds take from outside

Every input is pinned in [`packaging/versions.env`](../packaging/versions.env), next to the Python
and PySide6 the release carries: the python-build-standalone build and the SHA-256 of its tarball,
appimagetool and the AppImage runtime with their SHA-256s, and the Docker images by digest. pip
installs every package with `--no-deps` and its version, dependencies included. The workflow's
actions are pinned by commit SHA, and the repository refuses an action named any other way
(GENESIS.md, step 5). A pin changes only by a commit, so a release built twice from one
commit takes the same inputs, and a changed input shows in a diff.

`tests/test_pinned_inputs.py`, in tier 1, reads every file the builds and CI run and fails on an
input named by something that moves: a URL through `latest` or `continuous`, an image without its
digest, a pip install that leaves a version or a dependency open, a download pin without its
SHA-256, appimagetool without `--runtime-file` (without it, it downloads the newest runtime into the
AppImage), an action without its SHA. When it was written it found twelve, all since pinned.

To move a pin: a release's asset SHA-256 is in GitHub's API (`gh api
repos/OWNER/NAME/releases/tags/TAG --jq '.assets[] | .name + " " + .digest'`); an image's digest is
`docker image inspect --format '{{index .RepoDigests 0}}' IMAGE` after a pull; an action's SHA is
`gh api repos/OWNER/NAME/commits/TAG --jq .sha`. Then run the builds and their tests, as for any
change to them.

## Caches

`build/appimage-cache` (Python, PySide6's wheels, appimagetool, the runtime), tier 1's PySide6
folder and `build/wine-cache` are cached between runs, keyed on `packaging/versions.env` (and, for
the Windows build, its script and the `icuuc.dll` stand-in's source). A tag's run uses no cache: a
release is built from the pinned sources alone. The pinned files are checked against their
SHA-256s each time they're used, cached or not.

## When a job fails

GitHub keeps a run's logs in storage that some networks can't reach. Each script step therefore tees
its output to `build/ci-<job>.log`, and when it fails, `scripts/ci-tail.sh` posts its last 40 lines
as one error annotation: the reason shows on the pull request's Checks page and through GitHub's API
(`gh api repos/OWNER/NAME/check-runs/JOB/annotations`). Steps run under `bash -eo pipefail`, so a
script's failure isn't hidden by the `tee`.

## Not yet

- **Signing Windows' installer** (Authenticode), and a signed `SHA256SUMS` covering every file:
  the owner's next topic.
- **macOS**: `build.md`'s hand-off to a Mac stays as it is; a `macos-latest` job could sign and
  notarize once Apple's certificate is in secrets.
- **AppKata checking signatures itself**: it checks a release's `.sha256`, not its `.asc`; checking
  a publisher's signature is a feature of its own (`gpg.md`).
- **Field-test tracking issues** ([`testing.md`](testing.md), "Tracking the runs on GitHub").
