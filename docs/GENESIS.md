# Genesis

How this repository, its CI and its release key were set up: every one-time step, in order, with
how to check it is still in place. When something breaks, walk it again from the top.

`scripts/publish.sh check` reads back what GitHub shows an admin and prints `ok` or `FAIL` for each
setting below; run it with `gh` logged in as the owner. `scripts/publish.sh setup` makes the CI
settings of step 8 where they're missing. What each workflow job does is in
[`github-workflows.md`](github-workflows.md); building by hand, in
[`build.md`](build.md); each release, in [`RELEASE.md`](RELEASE.md).

The output under a command is what it printed when the owner set this repository up, on 2026-11-01
and 02. Where the owner's own terminal wasn't captured, it comes from a rehearsal of every step on a
test copy of the repository, with this repository's names and key put in. A new run differs in the
dates, key IDs, fingerprints and paths. If anything else differs, stop, and paste the output in an
issue.

## What the owner needs

`git`, `gpg` 2.2 or newer, `python3` and `gh`, on your own machine (not a shared one), and a USB
stick for the key. `gh` must be logged in as an admin of MojoKata, with the `repo` scope:

```sh
gpg --version | head -1        # gpg (GnuPG) 2.2.20, or newer
gh auth status
```

```
github.com
  ✓ Logged in to github.com account <you> (keyring)
  - Active account: true
  - Git operations protocol: ssh
  - Token: gho_************************************
  - Token scopes: 'gist', 'read:org', 'repo'
```

Work in a clone of the repository, on `master`; every command below runs from its top folder:

```sh
git clone git@github.com:MojoKata/AppKata.git
cd AppKata
```

## 1. The organization and the repository

- The **MojoKata** organization, on GitHub's Free plan. Its repository **MojoKata/AppKata** is
  public, licensed GPL-3.0 ([`LICENSE`](../LICENSE)), with `master` as its default branch.
- Published on 2026-10-25 from one commit of the files as they stood then. The earlier history is
  private ([`reviews/README.md`](reviews/README.md)).
- `APPKATA_REPO` in `src/appkata_core/__init__.py` names it. Every AppKata takes its own updates
  from this repository's releases (requirement 2.11), so **publishing a release ships an update**.

Check: `gh api repos/MojoKata/AppKata --jq '"\(.visibility) \(.default_branch) \(.license.spdx_id)"'`
prints `public master GPL-3.0`.

## 2. Who does what

- **The owner** is the repository's admin: merges pull requests, changes settings, holds the
  release key and publishes releases.
- **Contributors** work from forks and open pull requests. Claude Code works this way, from a fork,
  as a member of the organization with read access to the repository.

Check: the organization's People page, and the repository's Settings → Collaborators and teams.

## 3. Merging

Settings → General → Pull Requests: **squash merging only** (merge commits and rebase merging off).

Check: `publish.sh check`, "merge methods".

## 4. The `master` ruleset

Settings → Rules → Rulesets → `master`, active, on the default branch:

- Restrict deletions; block force pushes.
- Require a pull request before merging: 0 approvals; squash the only merge method.
- Require status checks to pass: **`ci`**, from GitHub Actions. GitHub offers a check only once it
  has run, so it was added after the first green run of the pull request that added CI;
  `publish.sh setup` adds it.
- Bypass list: repository admins.

Check: `publish.sh check`, the "master ruleset" lines.

## 5. Actions

Settings → Actions → General:

- **Approval for running fork pull request workflows:** require approval for all external
  contributors. A pull request from anyone who isn't a member of the organization or the repository
  runs only after an admin clicks "Approve and run".
- **Workflow permissions:** read repository contents and packages. A job that needs more asks for
  it by name; only the release job does (`contents: write`). "Allow GitHub Actions to create and
  approve pull requests" is off.
- **Require actions to be pinned to a full-length commit SHA:** GitHub refuses to run a workflow
  that names an action by a tag or a branch. `tests/test_pinned_inputs.py` checks the same from
  inside a run, where a pull request could change it; the setting holds whatever a pull request changes.
  `publish.sh setup` turns it on.

Check: `publish.sh check`, "workflow token", "fork PR runs wait for approval" and "actions pinned by
SHA".

## 6. Security

Settings → Security: **private vulnerability reporting** on, so a security problem can be reported
without making it public.

Check: `publish.sh check`, "private vulnerability reporting". It read back off on 2026-10-24, after
it was meant to be turned on; on 2026-10-28 it read back on.

## 7. The release key

The AppImage's `.asc` is signed by the release key's signing subkey. The main key, whose fingerprint
users check, stays offline with the owner; GitHub holds only a copy of the subkey. On the owner's
own machine (not a shared one):

1. `scripts/publish.sh key-new DIR 'NAME <ADDRESS>'` makes, in `DIR`, an ed25519 main key that only
   certifies (expires in 5 years) and an ed25519 signing subkey (2 years), and keeps `DIR/gnupg`
   (the keyring), `DIR/appkata-release-key.asc` (the public key), `DIR/fingerprint` and
   `DIR/revocation.asc`. `ADDRESS` must receive mail: keys.openpgp.org publishes the key's name
   only once its address is verified. Plug in the USB stick and make the key straight onto it.
   gpg opens a window for the passphrase, and may ask for it again for the subkey: make a strong
   one and keep it in a password manager.
   ```sh
   DIR=/media/$USER/KEYS/appkata-key          # your stick's path
   scripts/publish.sh key-new "$DIR" 'AppKata <app@mojokata.xyz>'
   ```
   ```
   == the main key (gpg asks for its passphrase: keep it with the key, never in GitHub)
   gpg: keybox '/media/you/KEYS/appkata-key/gnupg/pubring.kbx' created
   gpg: /media/you/KEYS/appkata-key/gnupg/trustdb.gpg: trustdb created
   gpg: key 02E771CD068A1ABD marked as ultimately trusted
   gpg: directory '/media/you/KEYS/appkata-key/gnupg/openpgp-revocs.d' created
   gpg: revocation certificate stored as '/media/you/KEYS/appkata-key/gnupg/openpgp-revocs.d/A5C4FAB754C234D38C983D9402E771CD068A1ABD.rev'
   gpg: checking the trustdb
   gpg: marginals needed: 3  completes needed: 1  trust model: pgp
   gpg: depth: 0  valid:   1  signed:   0  trust: 0-, 0q, 0n, 0m, 0f, 1u
   gpg: next trustdb check due at 2031-11-01
   == the signing subkey
   pub   ed25519 2026-11-02 [C] [expires: 2031-11-01]
         A5C4FAB754C234D38C983D9402E771CD068A1ABD
   uid           [ultimate] AppKata <app@mojokata.xyz>
   sub   ed25519 2026-11-02 [S] [expires: 2028-11-01]

   Made the release key A5C4FAB754C234D38C983D9402E771CD068A1ABD in /media/you/KEYS/appkata-key.
   Next: copy /media/you/KEYS/appkata-key to the offline place you keep it, then key-github /media/you/KEYS/appkata-key and key-export /media/you/KEYS/appkata-key.
   ```
   Look for `[C]` with an expiry 5 years out and `[S]` 2 years out, both `ed25519`. The
   40-character line under `pub` is the **fingerprint**; it's also in `$DIR/fingerprint`.
2. Keep `DIR` offline, on a USB stick with a second copy elsewhere, and the passphrase in a password
   manager. Keep `revocation.asc` apart from both, as a printout or in the password manager: it
   revokes the key without the passphrase.
   ```sh
   ls -l "$DIR"
   ```
   ```
   total 12
   -rw-r--r--. 1 you you  803 Nov  2 00:22 appkata-release-key.asc
   -rw-r--r--. 1 you you   41 Nov  2 00:22 fingerprint
   drwx------. 4 you you  128 Nov  2 00:22 gnupg
   -rw-------. 1 you you 1196 Nov  2 00:22 revocation.asc
   ```
3. `scripts/publish.sh key-export DIR` writes `packaging/appkata-release-key.asc` and offers to send
   the key to keys.openpgp.org (answer `y`). Commit the file in a pull request, with the fingerprint
   in `README.md` and `docs/gpg.md`. CI doesn't need it, but `publish.sh verify` checks every
   release against it.
   ```sh
   scripts/publish.sh key-export "$DIR"
   gpg --show-keys packaging/appkata-release-key.asc          # the same key as key-new showed
   ```
   ```
   Wrote packaging/appkata-release-key.asc: commit it (with the fingerprint in README.md and docs/gpg.md).
   Send the key to keys.openpgp.org? [y/N] y
   gpg: sending key 02E771CD068A1ABD to hkps://keys.openpgp.org
   keys.openpgp.org publishes the key's name only once its address is verified: run
     curl -sS --data-urlencode keytext@packaging/appkata-release-key.asc https://keys.openpgp.org/vks/v1/upload
   and follow the link in its answer, or use https://keys.openpgp.org/upload.
   Fingerprint: A5C4FAB754C234D38C983D9402E771CD068A1ABD
   pub   ed25519 2026-11-02 [C] [expires: 2031-11-01]
         A5C4FAB754C234D38C983D9402E771CD068A1ABD
   uid                      AppKata <app@mojokata.xyz>
   sub   ed25519 2026-11-02 [S] [expires: 2028-11-01]
   ```
   Then verify the address: open <https://keys.openpgp.org/upload> in a browser, upload
   `packaging/appkata-release-key.asc`, click **Send Verification Email** next to the address, and
   click the link in the mail that arrives. That also proves the address receives mail. The web
   page is simpler than the `curl` line.

   Once the key's pull request is merged, bring the clone up to date. Remove the exported copy
   first, or `git pull` refuses to overwrite it; `git status --short` then prints nothing:
   ```sh
   rm packaging/appkata-release-key.asc
   git pull
   git status --short
   ```
4. `scripts/publish.sh key-github DIR`, after step 8 made the `release` environment, puts the subkey
   alone in the environment's secrets: `APPKATA_SIGNING_KEY` and `APPKATA_SIGNING_PASSPHRASE`, a
   random passphrase made for that copy. `DIR` keeps its own passphrase. It asks for the main
   key's passphrase, and doesn't show what you type:
   ```sh
   scripts/publish.sh key-github "$DIR"
   ```
   ```
   The main key's passphrase:

   ✓ Set Actions secret APPKATA_SIGNING_KEY for MojoKata/AppKata
   ✓ Set Actions secret APPKATA_SIGNING_PASSPHRASE for MojoKata/AppKata
   MojoKata/AppKata's release environment now holds the signing subkey DE752F4068F71729A32E24991EE277E969EF8CF8.
   ```
   Then unplug the stick and put it away.

Check: `publish.sh check`, "release key" and "release environment: secrets";
`gpg --show-keys packaging/appkata-release-key.asc` shows both expiry dates.

Renewing the subkey before it expires, and replacing a leaked copy:
[`RELEASE.md`](RELEASE.md#9-the-release-key-between-releases), 9.

## 8. CI's settings

`scripts/publish.sh setup` makes each of these if it's missing, asking first (answer `y`):

- **The `release` environment** (Settings → Environments): you are its required reviewer, and it
  deploys only for tags matching `v*`. Its secrets come from step 7.4. The signing job names it, so
  a release is signed only after you approve its run.
- **The `tags` ruleset:** all tags. Only admins may create, move or delete one, so starting a release
  takes an admin, and a release can't be published on a tag nobody reviewed.
- **Immutable releases** (Settings → General → Releases): a published release's files and tag can't
  be changed, and GitHub adds a release attestation (`gh release verify`).
- **Actions pinned by SHA** required (step 5).
- **`ci` required** in the `master` ruleset (step 4), once it has passed.
- **The `field-test` label**, on a release's field-test issues (`publish.sh field-test`,
  docs/testing.md).

```sh
scripts/publish.sh setup
```

```
== MojoKata/AppKata
Make the release environment (you approve, v* tags only)? [y/N] y
release environment: made
Make the tags ruleset (only admins create, move or delete any tag)? [y/N] y
tags ruleset: made
Turn on immutable releases? [y/N] y
immutable releases: turned on
Require every action to be pinned to a full-length commit SHA? [y/N] y
actions pinned by SHA: required
Require the ci check in the master ruleset? [y/N] y
the ci check: required
Make the field-test label, for a release's field-test issues (docs/testing.md)? [y/N] y
the field-test label: made
```

A setting already in place prints `there` (or `on`, `required`) and asks nothing.

Check: `publish.sh check`, among them "field-test label".

`publish.sh check` reads back every step above. Once step 7 is done, every line is `ok`:

```sh
scripts/publish.sh check
```

```
ok    visibility: public
ok    default branch: master
ok    merge methods (squash merge rebase): true false false
ok    master ruleset: active branch ~DEFAULT_BRANCH
ok    master ruleset: rules: deletion non_fast_forward pull_request required_status_checks
ok    master ruleset: pull requests: 0 approvals, squash
ok    master ruleset: required checks: ci
ok    master ruleset: admins bypass: 1
ok    tags ruleset: active tag ~ALL creation,deletion,update
ok    tags ruleset: admins bypass: 1
ok    workflow token: read, approves PRs: false
ok    fork PR runs wait for approval: all_external_contributors
ok    actions pinned by SHA: true
ok    release environment: branch_policy,required_reviewers, custom: true
ok    release environment: deploys: tag v*
ok    release environment: secrets: APPKATA_SIGNING_KEY,APPKATA_SIGNING_PASSPHRASE
ok    immutable releases: true
ok    private vulnerability reporting: true
ok    field-test label: there
ok    release key: packaging/appkata-release-key.asc A5C4FAB7...
```

Two lines read `FAIL` until step 7 is done: `release key` until 7.3's pull request is merged, and
`release environment: secrets` until 7.4. A `FAIL` on any other line is a setting that isn't as it
should be: walk its step again.

## Each release

These steps aren't one-time, but they rely on everything above: the release checklist, CI's
workflow and the commands, in [`RELEASE.md`](RELEASE.md).

## Read back

| Date | By | What it showed |
|---|---|---|
| 2026-10-24 | a read-only member | `master` ruleset as in step 4, without the required check; private vulnerability reporting off; no environments; merge methods and Actions settings not readable |
| 2026-11-01 | a read-only member | after step 8's `publish.sh setup`: `master` ruleset with `ci` required, the `tags` ruleset, the `release` environment (required reviewers, `v*` tags), private vulnerability reporting on, the `field-test` label. The release key, posted on issue #12 and committed as `packaging/appkata-release-key.asc`: fingerprint `A5C4 FAB7 54C2 34D3 8C98  3D94 02E7 71CD 068A 1ABD`, `AppKata <app@mojokata.xyz>`, an ed25519 main key that only certifies, made 2026-11-02 (UTC), expires 2031-11-01, and an ed25519 signing subkey, expires 2028-11-01. Not readable: the environment's secrets, immutable releases, merge methods, the Actions settings, the rulesets' bypass lists |
