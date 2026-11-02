# Releasing: the agent's part

The owner walks a release through by [`RELEASE.md`](RELEASE.md), and at three points hands a step
to the agent by name ("Prepare release 0.2.0"). Each of those is a section here. The agent is
Claude Code, working from its fork as a member with read access ([`GENESIS.md`](GENESIS.md), step
2). It does every step of the section, in order, and ends by telling the owner what to do next.

`scripts/publish.sh release` refuses to tag until the release pull request of section 1 is merged
with every step of its record ticked, so none of them can be skipped.

## 1. Prepare a release

The owner says: **"Prepare release `<version>`"**. `<last>` is the version released before it.

1. **A branch** from `MojoKata/AppKata`'s `master`, up to date: `release-<version>`.
2. **`tier1`:** `scripts/test-tier1.sh` passes, and `scripts/test-clock.sh` too. CI runs tier 1
   again on the pull request.
3. **`sandbox`:** if anything the sandbox runs changed since `v<last>`, the sandbox tiers
   ([`build.md`](build.md#running-from-source-tests-and-screenshots); which tier is which is in
   [`testing.md`](testing.md)):
   ```sh
   git diff --stat v<last>..HEAD -- src/appkata_core/sandbox.py src/appkata_core/install.py tests/data/launchers
   ```
   If that prints nothing, the step is "not needed", with that command as the reason.
4. **`github-paths`:** `scripts/compare_github_paths.py` exits 0 (review 3, R3-23). It reads the
   demo data's projects through GitHub's API and through github.com's pages, which AppKata falls
   back to when the API's hour runs out (requirement 2.4.1), and exits 1 where the two disagree.
   It needs the network and about one API request per project; `GITHUB_TOKEN` raises the limit.
5. **`version`:** `__version__` in `src/appkata_core/__init__.py` and the README's "Status" heading
   say `<version>`. `publish.sh release` tags `v<version>`, and CI's `version` job stops a tag that
   doesn't match `__version__`.
6. **`state`:** freeze the release's on-disk state for the upgrade tests:
   ```sh
   UPDATE_STATE=<version> .venv/bin/python -m pytest tests/test_sandbox_state.py
   ```
   `tests/test_sandbox_state.py` thaws every file in `tests/data/state/` (the rows and files an
   installed, sandboxed app has after *that* release) into the current code on every test run, so
   a later AppKata is shown to read, heal, change and remove what an earlier one left. A release
   without its snapshot is a release the upgrade tests know nothing about. Drop a snapshot only
   when its release is no longer one AppKata upgrades from.
7. **`screenshots`:** if a screen changed since `v<last>`, make the screenshots again
   ([`build.md`](build.md#running-from-source-tests-and-screenshots)), run
   `scripts/test-screenshot-text.sh`, and check `git diff --stat screenshots`. If none changed, the
   step is "not needed", with why.
8. **The record**, `docs/releases/<version>.md`: one ticked line per step above, each with its
   result. `publish.sh release` reads it, and refuses while a step is missing or unticked.
   ```markdown
   # AppKata <version>

   ## Prepared

   On <date>, in pull request #<n>, at <commit>.

   - [x] **tier1** 2,499 passed, 121 skipped; test-clock.sh: the seven runs passed
   - [x] **sandbox** not needed: `git diff --stat v<last>..HEAD -- …` prints nothing
   - [x] **github-paths** 43 projects, no difference
   - [x] **version** `__version__` and the README's Status heading say <version>
   - [x] **state** tests/data/state/<version>.json
   - [x] **screenshots** not needed: no QML or demo data changed since v<last>
   ```
9. **The pull request**, "Release `<version>`": the version, the README, the snapshot, the
   record, and any screenshots, with a body that links the record. Run `tests/test_public_text.py`
   first, since the repository is public. Wait for its CI to pass.

Then tell the owner: "Pull request #`<n>` is ready. Merge it, then [`RELEASE.md`](RELEASE.md), 3:
`scripts/publish.sh release`."

## 2. Look into a stopped release

The owner says: **"Release `<version>` stopped"**, with what `publish.sh` printed.

1. Read the run's failed jobs: `gh run view <run> --repo MojoKata/AppKata --log-failed`.
2. If the failure isn't the code's (a runner, the network, GitHub answering 5xx), tell the owner
   to run the failed jobs again and resume:
   ```sh
   gh run rerun <run> --failed --repo MojoKata/AppKata
   scripts/publish.sh resume
   ```
3. If it is the code's, open an issue for it, with the log. Fix it in a pull request, then tell the
   owner it needs a new version (section 1 again). A tag isn't moved or deleted to fix a release:
   the tags ruleset leaves that to an admin, and the owner decides.
4. If `release` refused before tagging, its message says why. CI failed on `master`, a step isn't
   ticked, or the snapshot is missing: fix that in a pull request.

## 3. Wrap up a release

The owner says: **"Wrap up release `<version>`"**, after `publish.sh publish`.

1. **Check the published release** from your own clone. Anyone can, once it's published:
   ```sh
   scripts/publish.sh verify <version>
   ```
   It must say `(published)` and the release key's fingerprint.
2. **Add a "Released" section to the record**, `docs/releases/<version>.md`:
   - the date it was published, and the tag's commit;
   - CI's run of the tag;
   - the two SHA-256s, from `verify`'s output;
   - the field test: the release's issue, and how each environment's closed. A waived one says why.
   - anything that went wrong, and the issue that has it.
3. **A pull request** with the record, "Release `<version>`: the record".

Then tell the owner the release is recorded, with the pull request's link.
