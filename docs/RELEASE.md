# Releasing

How the owner walks a version of AppKata out: six steps, two of them handed to the agent by name.
The agent's side of those is in [`RELEASE_AGENT.md`](RELEASE_AGENT.md). The one-time setup they
rely on (the repository's settings, the release key) is in [`GENESIS.md`](GENESIS.md); how the
files are built, in [`build.md`](build.md); what CI's jobs do, in
[`github-workflows.md`](github-workflows.md).

**Publishing a release ships an update.** Every AppKata takes its own updates from this
repository's releases (requirement 2.11), and with immutable releases on, a published release's
files and tag can never change. A bad release is fixed by a new version, never in place.

## The flow

```
 1. You → agent   "Prepare release 0.2.0"       the release pull request: tests, version,
                                                 snapshot, record          (RELEASE_AGENT.md, 1)
 2. You           merge it
 3. You           scripts/publish.sh release     tag → CI builds → you approve the signing →
                                                 the draft, checked → the field-test issues
 4. You           the field test, each desktop   field-test.sh; post the report; close its issue
 5. You           scripts/publish.sh publish     the update goes out
 6. You → agent   "Wrap up release 0.2.0"       the release's record      (RELEASE_AGENT.md, 3)
```

Each command checks that the step before it is done, and refuses otherwise, saying what's missing:

| Command | Refuses until |
|---|---|
| `publish.sh release` | you're on `master`, up to date, with nothing changed; `v<version>` isn't tagged yet; the release pull request is merged: `docs/releases/<version>.md` has every step ticked, the state snapshot is there, and the README names the version; CI has passed on `master` at that commit |
| `publish.sh publish` | the draft is there, and verifies; the release's field-test issues are there, and every one is closed |

If anything stops, see [7](#7-when-a-step-stops).

The output under each command is what it printed for 0.1.0, on 2026-11-02, except the lines
`publish.sh` has printed since: the check before the tag, the field-test question and the `Next:`
lines, shown where they now come. Yours will differ in the version, the commit, the run and issue
numbers, and the SHA-256s.

## 1. Ask the agent to prepare the release

Tell the agent: **"Prepare release 0.2.0"**, with the version to release.

It runs the tests and the checks no runner can make, sets the version, freezes the release's state
for the upgrade tests, writes the release's record (`docs/releases/0.2.0.md`, a ticked line per
step) and opens one pull request with all of it ([`RELEASE_AGENT.md`](RELEASE_AGENT.md), 1). It
tells you when the pull request's CI has passed.

## 2. Merge the release pull request

Read the record in the pull request, then squash-merge it as usual. Merging starts CI on `master`;
`release` waits for that run to pass.

## 3. Tag, build and sign: `publish.sh release`

You need, once: `git`, `gpg` 2.2 or newer, `python3`, and `gh` logged in as an admin of MojoKata
([`GENESIS.md`](GENESIS.md#what-the-owner-needs)), and a clone of the repository. You don't need
the release key: CI signs with its own copy of the signing subkey.

```sh
git checkout master && git pull
scripts/publish.sh release
```

It asks three times: answer `y` to each. Before the second question it shows the SHA-256s of the
two files CI built; the draft must hold exactly those. It takes about 20 minutes, most of it CI's run.

```
CI passed on master at 37a790c, and docs/releases/0.1.0.md has every step done.
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
The draft: https://github.com/MojoKata/AppKata/releases (only you see it).
Open MojoKata/AppKata's field-test issues for 0.1.0: one for the release, one under it for each of Ubuntu 24.04 LTS, Linux Mint 22.3, LMDE 7, Ubuntu 26.04 LTS? [y/N] y
the release's: https://github.com/MojoKata/AppKata/issues/16
  Ubuntu 24.04 LTS: https://github.com/MojoKata/AppKata/issues/17
  Linux Mint 22.3: https://github.com/MojoKata/AppKata/issues/18
  LMDE 7: https://github.com/MojoKata/AppKata/issues/19
  Ubuntu 26.04 LTS: https://github.com/MojoKata/AppKata/issues/20
Next: docs/RELEASE.md, 4: the field test on each desktop, with the draft's AppImage; then publish.sh publish.
```

What to check:
- The "Bypassed rule violations" lines are expected: the tags ruleset lets only admins create
  tags, and you are one.
- The fingerprint in the `(draft)` line is the release key's, the one the README publishes.
- The two SHA-256s at the end are the two shown before you approved the signing.

## 4. The field test

The questions no automatic tier can answer need a person at a real desktop: what an app's own
file dialog shows, whether a tray icon appears, and the rest of "What it asks the tester" in
[`local-proxy-test-plan.md`](local-proxy-test-plan.md). Run it on each environment that has an
issue from step 3 (the list is in [`testing.md`](testing.md), "By hand, before a release"), on
real hardware, logged in to the desktop. Each environment can have its own tester and machine.

```sh
V=0.1.0                                     # the version being released
git clone git@github.com:MojoKata/AppKata.git && cd AppKata && git checkout v$V
gh release download v$V --repo MojoKata/AppKata --pattern '*.AppImage'
scripts/sandbox/field-test.sh --app ./AppKata-$V-x86_64.AppImage
```

It installs a small probe app through AppKata, in a throwaway home it removes afterwards, and checks
what it can by itself, one line each. This is the Linux Mint 22.3 test VM's run of 2026-10-31,
from its first check:

```
== checks ==
  PASS     A-support      AppKata's sandbox can run here
  BLOCKED  ISO-keys       a sandboxed app can't read ~/.ssh
  BLOCKED  ISO-home       its writes to ~ land in its private home
  BLOCKED  ISO-net        Strict has no network
  PASS     D-theme        the desktop's themes are visible and read-only
  PASS     ISO-net-on     Online app reaches the network
  BLOCKED  P-filter       the bus filter refuses systemd1
  PASS     P-portal       the portal answers through the filter
  PASS     P-handover     a file given as an argument is handed over (document portal)
  PASS     INNER          an app's own sandbox inside AppKata's: possible
  N/A      D-capture      screen capture check  -- needs grim (Wayland) or ImageMagick's import (X11)
  PASS     D-sound        a sound grant reaches the sound server
  BLOCKED  D-nosound      no sound server without the grant
  PASS     D-gpu          OpenGL renderer inside: llvmpipe (LLVM 20.1.2, 256 bits)
  PASS     EXP-strict     strict: everything it sees is listed in docs/sandbox-exposure.md
  PASS     EXP-online-app online-app: everything it sees is listed in docs/sandbox-exposure.md
  PASS     T-cli          a command-line tool works in the folder it's run in
  BLOCKED  T-cli-home     run from the home folder, it gets its private home and says why
  N/A      A1-prompt      the AppArmor setup's first-install prompt  -- no setup here: the kernel doesn't restrict user namespaces, or the system has a bwrap profile of its own
  N/A      A1-pkexec      the AppArmor setup's password prompt  -- no setup here: the kernel doesn't restrict user namespaces, or the system has a bwrap profile of its own
```

`PASS` and `BLOCKED` are good: `BLOCKED` is the sandbox stopping what it should. `FAIL` or `LEAK`
is a bug. `N/A` is a check this machine can't make, and says why. On a real GPU, `D-gpu` should
name it, not `llvmpipe`.

Then it asks you about what's on screen, one question at a time. Answer `y` (it works), `n` (it
doesn't) or `s` (you can't tell, or skip). Each answer becomes a line like the ones above:

```
  >> P-dialog
     In a sandboxed app, does its own file dialog show its private home and the folders you gave it -- and nothing else of your home? [y=pass / n=fail / s=skip]: y
  PASS     P-dialog       In a sandboxed app, does its own file dialog show its private home and the folders you gave it -- and nothing else of your home?  -- tester's answer

  >> P-openwith
     Does 'Open with' (or a drop on its menu entry) of a file outside its folders open that file in the sandboxed app? [y=pass / n=fail / s=skip]: n
  FAIL     P-openwith     Does 'Open with' (or a drop on its menu entry) of a file outside its folders open that file in the sandboxed app?  -- tester's answer

  >> T-tray
     Messenger template: does its tray icon appear and do its notifications arrive? [y=pass / n=fail / s=skip]: s
  MANUAL   T-tray         Messenger template: does its tray icon appear and do its notifications arrive?  -- skipped
```

and so on through the seven questions (nine where the AppArmor setup is needed). It ends with a
count and where it left the results:

```
== done ==
pass/blocked: 17   fail/leak: 0   manual/n-a: 10
Report:  /home/kata/vmtest/appkata-fieldtest-appkata-vm-20261031-032804/report.md
Bundle:  /home/kata/vmtest/appkata-fieldtest-appkata-vm-20261031-032804.tar.gz  (bring this back for review)
```

(The VM's run answered no questions: it ran with `--non-interactive`, so all seven read `MANUAL`,
and its counts are that run's. The questions above are fieldtest.py's own prompts, answered `y`,
`n` and `s` in a terminal.)

Post the report on that environment's issue, attach the `.tar.gz` on the issue's web page (`gh`
can't attach files), tick each box the run answered "yes", and close the issue:

```sh
gh issue comment 18 --repo MojoKata/AppKata --body-file appkata-fieldtest-*/report.md
```

A "no" is a bug: open an issue labelled `bug`, link it from the box it leaves unticked, and tell
the agent. To release without an environment, close its issue with a comment saying why: that's a
waiver. The release's issue closes once every environment's has.

## 5. Publish: `publish.sh publish`

**This ships the update to every AppKata**, and its files and tag can never change after.

```sh
scripts/publish.sh publish
```

```
Every field-test issue of 0.1.0 is closed.
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
…
9644f2c450a1ed72a017d6599170c1c0701c0f9dcfe8bfcb9aa502ff2b40e08e  AppKata-0.1.0-x86_64.AppImage
d0fc755a3d870b86b24d09ec8a85859651e0275ecca5043c3675be2e07aab100  AppKata-0.1.0-setup.exe
Next: docs/RELEASE.md, 6: ask the agent to wrap up release 0.1.0.
```

What to check:
- The second check says `(published)`.
- The SHA-256s are the ones `release` showed in step 3.
- Between the `(published)` line and the SHA-256s, `gh release verify` prints GitHub's release
  attestation. It isn't shown here: #12's rehearsal ran with immutable releases off.

## 6. Ask the agent to wrap up

Tell the agent: **"Wrap up release 0.2.0"**. It checks the published release from its own clone,
and adds what was released to the record (the run, the SHA-256s, the field test and any waiver) in
a pull request for you to merge ([`RELEASE_AGENT.md`](RELEASE_AGENT.md), 3).

## 7. When a step stops

- **`release` or `publish` refused:** its message says what's missing and where. Do that, then run
  it again. A refusal changes nothing.
- **`release` stopped after the tag** (`publish.sh: the run ended without signing`, or you pressed
  Ctrl-C): tell the agent **"Release 0.2.0 stopped"**, with the output
  ([`RELEASE_AGENT.md`](RELEASE_AGENT.md), 2). If it was the runner's fault, the agent tells you to
  run the failed jobs again and resume. `resume` prints the same as `release` from
  `== waiting for CI's run` on:
  ```sh
  gh run rerun 41383071163 --failed --repo MojoKata/AppKata     # your run number, from the "run …" line
  scripts/publish.sh resume
  ```
- **You answered `n`** to a question: nothing after it happened. Run the same command again.

## 8. What `publish.sh` does

`scripts/publish.sh`, with `gh` logged in as an admin. `VERSION` is `__version__` in
`src/appkata_core/__init__.py` unless given; the script's header lists its options. The one-time
commands, `setup`, `check` and the `key-` ones, are in GENESIS.md.

| Command | What it does |
|---|---|
| `release` | Checks what step 1 and 2 leave (the table under "The flow"), tags `master`'s tip `v<version>` and pushes it, waits for CI's run of the tag, shows the SHA-256s of the two files it built, approves the signing, waits for the draft release and verifies it, checks that the draft holds the files whose SHA-256s you approved, and opens the field-test issues. It asks before the tag, the signing and the issues. |
| `resume [VERSION]` | The same from "waits for CI's run", for a tag already pushed: after an interruption, or after a failed run is run again. |
| `verify [VERSION]` | Downloads the release, or its draft, into `build/publish/v<version>/` and checks it: exactly five files, each against its `.sha256`, and the AppImage's signature by the release key (`packaging/appkata-release-key.asc`, matched by fingerprint). |
| `field-test [VERSION]` | Opens the release's field-test issue and, under it, one for each environment with its checklist ([`testing.md`](testing.md), "Tracking the runs on GitHub"). `release` does this itself; on its own it's for when you answered `n` there. |
| `publish [VERSION]` | Checks that every field-test issue is closed, verifies the draft again, asks, publishes it as the latest release, and verifies the published one. |

[`.github/workflows/ci.yml`](../.github/workflows/ci.yml) runs tier 1 and both builds on every pull
request and every push to `master`. On a `v*` tag it also signs the AppImage (after your approval)
and makes a draft release. Its builds are the scripts [`build.md`](build.md) describes. What it
downloads is pinned in [`packaging/versions.env`](../packaging/versions.env), and its actions by
commit SHA (GitHub refuses any other, GENESIS.md step 5); `tests/test_pinned_inputs.py` fails on
anything named by a tag or a release that moves.

## 9. The release key between releases

The key itself stays offline, in `DIR` on a USB stick (GENESIS.md, step 7). Plug it in for these.

**Before the subkey expires** (every 2 years): `publish.sh key-extend DIR` moves both dates on and
exports the key again; commit the new `packaging/appkata-release-key.asc` in a pull request, then
run `publish.sh key-github DIR`. The copy in GitHub carries the old date and stops signing when it
passes.

**If the copy in GitHub leaks:** `GNUPGHOME=DIR/gnupg gpg --edit-key $(cat DIR/fingerprint)`, then
`key 1`, `revkey`, `save`. Then `gpg --quick-add-key $(cat DIR/fingerprint) ed25519 sign 2y`,
`publish.sh key-export DIR` and `publish.sh key-github DIR`. The fingerprint users check stays the
same.
