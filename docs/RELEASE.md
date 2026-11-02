# Releasing

How a version of AppKata is released: the steps in order, the commands, what each does and what it
prints. The one-time setup they rely on (the repository's settings, the release key) is in
[`GENESIS.md`](GENESIS.md); how the files are built, in [`build.md`](build.md); what CI's jobs do,
in [`github-workflows.md`](github-workflows.md).

**Publishing a release ships an update.** Every AppKata takes its own updates from this
repository's releases (requirement 2.11), and with immutable releases on, a published release's
files and tag can never change. A bad release is fixed by a new version, never in place.

The output under each command is what it printed for 0.1.0, on 2026-11-01 and 02. Where the owner's
own terminal wasn't captured, it comes from a rehearsal of every step on a test copy of the
repository, with this repository's names and key put in. Yours will differ in the version, the
commit, the dates, run and issue numbers, SHA-256s and paths. If anything else differs, stop, and
paste the output in an issue.

## Before you start

- On your own machine: `git`, `gpg` 2.2 or newer, `python3`, and `gh` logged in as an admin of
  MojoKata ([`GENESIS.md`](GENESIS.md#what-the-owner-needs)).
- A clone of the repository. Every command below runs from its top folder.
- Not the release key: CI signs with its own copy of the signing subkey (GENESIS.md, step 7).

## The workflow

[`.github/workflows/ci.yml`](../.github/workflows/ci.yml) runs tier 1 and both builds on every pull
request and every push to `master`. On a `v*` tag it also signs the AppImage (after your approval)
and makes a draft release. Its builds are the scripts [`build.md`](build.md) describes. What it
downloads is pinned in [`packaging/versions.env`](../packaging/versions.env), and its actions by
commit SHA (GitHub refuses any other, GENESIS.md step 5); `tests/test_pinned_inputs.py` fails on
anything named by a tag or a release that moves.

## The commands

`scripts/publish.sh`, with `gh` logged in as an admin. `VERSION` is `__version__` in
`src/appkata_core/__init__.py` unless given; the script's header lists its options.

| Command | What it does |
|---|---|
| `release` | Checks that `master` is clean and current, tags its tip `v<version>` and pushes it (it asks first), waits for CI's run of the tag, shows the SHA-256s of the two files it built, approves the signing (it asks first), waits for the draft release and verifies it, and checks that the draft holds the files whose SHA-256s you approved. |
| `resume [VERSION]` | The same from "waits for CI's run", for a tag already pushed: after an interruption, or after a failed run is run again. |
| `verify [VERSION]` | Downloads the release, or its draft, into `build/publish/v<version>/` and checks it: exactly five files, each against its `.sha256`, and the AppImage's signature by the release key (`packaging/appkata-release-key.asc`, matched by fingerprint). |
| `field-test [VERSION]` | Opens the release's field-test issue and, under it, one for each environment with its checklist ([`testing.md`](testing.md), "Tracking the runs on GitHub"). It asks first. |
| `publish [VERSION]` | Verifies the draft again, asks, publishes it as the latest release, and verifies the published one. |

The one-time commands, `setup`, `check` and the `key-` ones, are in GENESIS.md.

## The steps

1. **The tests:** `.venv/bin/python -m pytest` green, and the sandbox tiers
   ([`build.md`](build.md#running-from-source-tests-and-screenshots)) if anything under
   `src/appkata_core/sandbox.py`, `install.py` or the launcher goldens changed since the last tag.
2. **Read github.com both ways** (review 3, R3-23): `scripts/compare_github_paths.py` reads the demo
   data's projects through GitHub's API and through github.com's pages, which AppKata falls back to
   when the API's hour runs out (requirement 2.4.1), and exits 1 where the two disagree. It needs
   the network and about one API request per project; `GITHUB_TOKEN` raises the limit.
3. **Set the version, and freeze the release's on-disk state** for the upgrade tests, in one pull
   request. The version is `__version__` in `src/appkata_core/__init__.py`. `publish.sh release`
   tags `v` and it, and CI's `version` job stops a tag that doesn't match it. The README's
   "Status" heading names it too.
   ```sh
   UPDATE_STATE=<version> .venv/bin/python -m pytest tests/test_sandbox_state.py
   git add src/appkata_core/__init__.py README.md tests/data/state/<version>.json
   ```
   `tests/test_sandbox_state.py` thaws every file in `tests/data/state/` — the rows and files an
   installed, sandboxed app has after *that* release — into the current code on every test run,
   so a later AppKata is shown to read, heal, change and remove what an earlier one left. A
   release without its snapshot is a release the upgrade tests know nothing about. Drop a
   snapshot only when its release is no longer one AppKata upgrades from.
4. **The screenshots:** make them again if a screen changed
   ([`build.md`](build.md#running-from-source-tests-and-screenshots)), and check
   `git diff --stat screenshots`.
5. **Tag it, and let CI build and sign it**, once that pull request is merged and CI has passed on
   `master` at its merge. The tag's run builds the same commit again, so a run that fails on
   `master` fails on the tag too, with the tag already pushed. On `master`, up to date, with
   nothing changed:
   ```sh
   git checkout master && git pull && git status --short             # prints nothing
   gh run list --repo MojoKata/AppKata --branch master --limit 1      # "completed  success"
   scripts/publish.sh release
   ```
   It asks twice: answer `y`. Before the second question it shows the SHA-256s of the two files CI
   built; the draft must hold exactly those. It takes about 5 minutes.
   ```
   Tag 37a790c as v0.1.0 and push it to MojoKata/AppKata? [y/N] y
   remote: Bypassed rule violations for refs/tags/v0.1.0:
   remote:
   remote: - Cannot create ref due to creations being restricted.
   remote:
   == waiting for CI's run of v0.1.0
   run 41383071163: https://github.com/MojoKata/AppKata/actions/runs/41383071163
   == what CI built (its jobs' sha256 notices)
   9644f2c450a1ed72a017d6599170c1c0701c0f9dcfe8bfcb9aa502ff2b40e08e  AppKata-0.1.0-x86_64.AppImage
   d0fc755a3d870b86b24d09ec8a85859651e0275ecca5043c3675be2e07aab100  AppKata-0.1.0-setup.exe
   Sign the AppImage and make the draft release? [y/N] y
   Finding assets to download...
   Downloading AppKata-0.1.0-setup.exe...
   Downloading AppKata-0.1.0-x86_64.AppImage...
   Downloading AppKata-0.1.0-setup.exe.sha256...
   Downloading AppKata-0.1.0-x86_64.AppImage.asc...
   Downloading AppKata-0.1.0-x86_64.AppImage.sha256...
   AppKata-0.1.0-setup.exe: OK
   AppKata-0.1.0-x86_64.AppImage: OK
   v0.1.0 (draft): every file matches its .sha256, and the AppImage's signature is the release key's (A5C4FAB754C234D38C983D9402E771CD068A1ABD)
   9644f2c450a1ed72a017d6599170c1c0701c0f9dcfe8bfcb9aa502ff2b40e08e  AppKata-0.1.0-x86_64.AppImage
   d0fc755a3d870b86b24d09ec8a85859651e0275ecca5043c3675be2e07aab100  AppKata-0.1.0-setup.exe
   The draft's two files are the ones whose SHA-256s you approved.
   The draft: https://github.com/MojoKata/AppKata/releases (only you see it). Before publishing it: docs/RELEASE.md,
   step 6 (the field test by hand, with the draft's files); then publish.sh publish.
   ```
   What to check:
   - The "Bypassed rule violations" lines are expected: the tags ruleset lets only admins create
     tags, and you are one.
   - The fingerprint in the `(draft)` line is the release key's, the one the README publishes.
   - The two SHA-256s at the end are the two shown before you answered `y`.

   **If it stops with `publish.sh: the run ended without signing`:** open the run's link and see
   which job failed. Run the failed jobs again, then `resume`, which prints the same as `release`
   from `== waiting for CI's run` on. Use your own run number, from the `run …` line:
   ```sh
   gh run rerun 41383071163 --failed --repo MojoKata/AppKata
   scripts/publish.sh resume
   ```
6. **The field test by hand**, on real hardware with a logged-in desktop: the questions no tier
   answers ("What it asks the tester" in [`local-proxy-test-plan.md`](local-proxy-test-plan.md);
   the environments are in [`testing.md`](testing.md), "By hand, before a release"). First open the
   release's tracking issue and, under it, one for each environment with its checklist (answer `y`):
   ```sh
   scripts/publish.sh field-test
   ```
   ```
   Open MojoKata/AppKata's field-test issues for 0.1.0: one for the release, one under it for each of Ubuntu 24.04 LTS, Linux Mint 22.3, LMDE 7, Ubuntu 26.04 LTS? [y/N] y
   the release's: https://github.com/MojoKata/AppKata/issues/16
     Ubuntu 24.04 LTS: https://github.com/MojoKata/AppKata/issues/17
     Linux Mint 22.3: https://github.com/MojoKata/AppKata/issues/18
     LMDE 7: https://github.com/MojoKata/AppKata/issues/19
     Ubuntu 26.04 LTS: https://github.com/MojoKata/AppKata/issues/20
   ```
   Then on each of those desktops, from the commit being tagged and with the draft's AppImage
   (`field-test.sh` without `--non-interactive`, so it asks you what's on screen):
   ```sh
   V=0.1.0                                     # the version being released
   git clone git@github.com:MojoKata/AppKata.git && cd AppKata && git checkout v$V
   gh release download v$V --repo MojoKata/AppKata --pattern '*.AppImage'
   scripts/sandbox/field-test.sh --app ./AppKata-$V-x86_64.AppImage
   ```
   It leaves `appkata-fieldtest-<host>-<date>/`, with `report.md`, and a `.tar.gz` of it. Post the
   report on that environment's issue (17 is Ubuntu 24.04 LTS's above), attach the `.tar.gz` on the
   issue's web page (`gh` can't attach files), and tick each box the run answered "yes":
   ```sh
   gh issue comment 17 --repo MojoKata/AppKata --body-file appkata-fieldtest-*/report.md
   ```
   A "no" is a bug: open an issue labelled `bug` and link it from the box it leaves unticked. How
   the issues are used is in [`testing.md`](testing.md), "Tracking the runs on GitHub".
7. **Publish the draft**, once every environment's issue is closed, or you've waived one and said
   why in it. **This ships the update to every AppKata**, and its files and tag can never change
   after.
   ```sh
   scripts/publish.sh publish
   ```
   ```
   Finding assets to download...
   Downloading AppKata-0.1.0-setup.exe.sha256...
   Downloading AppKata-0.1.0-setup.exe...
   Downloading AppKata-0.1.0-x86_64.AppImage...
   Downloading AppKata-0.1.0-x86_64.AppImage.asc...
   Downloading AppKata-0.1.0-x86_64.AppImage.sha256...
   AppKata-0.1.0-setup.exe: OK
   AppKata-0.1.0-x86_64.AppImage: OK
   v0.1.0 (draft): every file matches its .sha256, and the AppImage's signature is the release key's (A5C4FAB754C234D38C983D9402E771CD068A1ABD)
   9644f2c450a1ed72a017d6599170c1c0701c0f9dcfe8bfcb9aa502ff2b40e08e  AppKata-0.1.0-x86_64.AppImage
   d0fc755a3d870b86b24d09ec8a85859651e0275ecca5043c3675be2e07aab100  AppKata-0.1.0-setup.exe
   Publish v0.1.0? Every AppKata offers it as an update from its next sync. [y/N] y
   Finding assets to download...
   …
   v0.1.0 (published): every file matches its .sha256, and the AppImage's signature is the release key's (A5C4FAB754C234D38C983D9402E771CD068A1ABD)
   9644f2c450a1ed72a017d6599170c1c0701c0f9dcfe8bfcb9aa502ff2b40e08e  AppKata-0.1.0-x86_64.AppImage
   d0fc755a3d870b86b24d09ec8a85859651e0275ecca5043c3675be2e07aab100  AppKata-0.1.0-setup.exe
   ```
   It checks the draft, asks, publishes, then checks the published release again. What to check:
   - The second check says `(published)`.
   - The SHA-256s are the ones `release` showed in step 5.
   - Between the `(published)` line and the SHA-256s, `gh release verify` prints GitHub's release
     attestation. The rehearsal ran with immutable releases off, so that part isn't shown here.

## The release key between releases

The key itself stays offline, in `DIR` on a USB stick (GENESIS.md, step 7). Plug it in for these.

**Before the subkey expires** (every 2 years): `publish.sh key-extend DIR` moves both dates on and
exports the key again; commit the new `packaging/appkata-release-key.asc` in a pull request, then
run `publish.sh key-github DIR`. The copy in GitHub carries the old date and stops signing when it
passes.

**If the copy in GitHub leaks:** `GNUPGHOME=DIR/gnupg gpg --edit-key $(cat DIR/fingerprint)`, then
`key 1`, `revkey`, `save`. Then `gpg --quick-add-key $(cat DIR/fingerprint) ed25519 sign 2y`,
`publish.sh key-export DIR` and `publish.sh key-github DIR`. The fingerprint users check stays the
same.
