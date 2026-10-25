# Genesis

How this repository, its CI and its release key were set up: every one-time step, in order, with
how to check it is still in place. When something breaks, walk it again from the top.

`scripts/publish.sh check` reads back what GitHub shows an admin and prints `ok` or `FAIL` for each
setting below; run it with `gh` logged in as the owner. `scripts/publish.sh setup` makes the CI
settings of step 8 where they're missing. What each workflow job does is in
[`docs/github-workflows.md`](docs/github-workflows.md); building by hand, in
[`docs/build.md`](docs/build.md).

## 1. The organization and the repository

- The **MojoKata** organization, on GitHub's Free plan. Its repository **MojoKata/AppKata** is
  public, licensed GPL-3.0 ([`LICENSE`](LICENSE)), with `master` as its default branch.
- Published on 2026-10-25 from one commit of the files as they stood then. The earlier history is
  private ([`docs/reviews/README.md`](docs/reviews/README.md)).
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

Check: `publish.sh check`, "workflow token" and "fork PR runs wait for approval".

## 6. Security

Settings → Security: **private vulnerability reporting** on, so a security problem can be reported
without making it public.

Check: `publish.sh check`, "private vulnerability reporting". It read back off on 2026-10-24, after
it was meant to be turned on.

## 7. The release key

The AppImage's `.asc` is signed by the release key's signing subkey. The main key, whose fingerprint
users check, stays offline with the owner; GitHub holds only a copy of the subkey. On the owner's
own machine (not a shared one):

1. `scripts/publish.sh key-new DIR 'NAME <ADDRESS>'` makes, in `DIR`, an ed25519 main key that only
   certifies (expires in 5 years) and an ed25519 signing subkey (2 years), and keeps `DIR/gnupg`
   (the keyring), `DIR/appkata-release-key.asc` (the public key), `DIR/fingerprint` and
   `DIR/revocation.asc`. `ADDRESS` must receive mail: keys.openpgp.org publishes the key's name
   only once its address is verified.
2. Keep `DIR` offline, on a USB stick with a second copy elsewhere, and the passphrase in a password
   manager. Keep `revocation.asc` apart from both: it revokes the key without the passphrase.
3. `scripts/publish.sh key-export DIR` writes `packaging/appkata-release-key.asc` and offers to send
   the key to keys.openpgp.org. Commit the file in a pull request, with the fingerprint in
   `README.md` and `docs/gpg.md`. CI doesn't need it, but `publish.sh verify` checks every release
   against it.
4. `scripts/publish.sh key-github DIR`, after step 8 made the `release` environment, puts the subkey
   alone in the environment's secrets: `APPKATA_SIGNING_KEY` and `APPKATA_SIGNING_PASSPHRASE`, a
   random passphrase made for that copy. `DIR` keeps its own passphrase.

Check: `publish.sh check`, "release key" and "release environment: secrets";
`gpg --show-keys packaging/appkata-release-key.asc` shows both expiry dates.

**Before the subkey expires** (every 2 years): `publish.sh key-extend DIR` moves both dates on and
exports the key again, then run `publish.sh key-github DIR`. The copy in GitHub carries the old
date and stops signing when it passes.

**If the copy in GitHub leaks:** with `DIR` plugged in, `GNUPGHOME=DIR/gnupg gpg --edit-key
$(cat DIR/fingerprint)`, then `key 1`, `revkey`, `save`. Then
`gpg --quick-add-key $(cat DIR/fingerprint) ed25519 sign 2y`, `publish.sh key-export DIR` and
`publish.sh key-github DIR`. The fingerprint users check stays the same.

## 8. CI's settings

`scripts/publish.sh setup` makes each of these if it's missing, asking first:

- **The `release` environment** (Settings → Environments): you are its required reviewer, and it
  deploys only for tags matching `v*`. Its secrets come from step 7.4. The signing job names it, so
  a release is signed only after you approve its run.
- **The `tags` ruleset:** all tags. Only admins may create, move or delete one, so starting a release
  takes an admin, and a release can't be published on a tag nobody reviewed.
- **Immutable releases** (Settings → General → Releases): a published release's files and tag can't
  be changed, and GitHub adds a release attestation (`gh release verify`).
- **`ci` required** in the `master` ruleset (step 4), once it has passed.

Check: `publish.sh check`.

## 9. The workflow

[`.github/workflows/ci.yml`](.github/workflows/ci.yml) runs tier 1 and both builds on every pull
request and every push to `master`. On a `v*` tag it also signs the AppImage (after your approval)
and makes a draft release. What it downloads is pinned in
[`packaging/versions.env`](packaging/versions.env), and its actions by commit SHA;
`tests/test_pinned_inputs.py` fails on anything named by a tag or a release that moves.

## Each release

These steps aren't one-time, but they rely on everything above: build.md's "Before tagging a
release", then `scripts/publish.sh release` (tag, CI, approve the signing, check the draft),
the field test with the draft's files, and `scripts/publish.sh publish`.

## Read back

| Date | By | What it showed |
|---|---|---|
| 2026-10-24 | a read-only member | `master` ruleset as in step 4, without the required check; private vulnerability reporting off; no environments; merge methods and Actions settings not readable |
