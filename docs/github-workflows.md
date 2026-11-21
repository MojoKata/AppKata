# GitHub Actions: CI, the signed AppImage and the draft release

What [`.github/workflows/ci.yml`](../.github/workflows/ci.yml) runs, when, and why it is built the
way it is: the CI walk thru's decisions of 2026-10-24. One-time setup (the repository's settings,
the release key) is in [`GENESIS.md`](GENESIS.md); building by hand, in [`build.md`](build.md);
the release checklist, in [`RELEASE.md`](RELEASE.md); what users can check a download against, in
[`gpg.md`](gpg.md).

## What runs when

| Event | Jobs | What it leaves |
|---|---|---|
| A pull request, a push to `master` | `tier1` in 3 parts, `appimage`, `windows`, then `coverage` and `ci-times`, then `ci` | the AppImage and `setup.exe`, each with its `.sha256`, unsigned, as the run's artifacts (`appimage`, `windows`; GitHub keeps them 90 days); the coverage report (`coverage`, 30 days); each part's tests' times (`durations-1` to `-3`, 30 days) |
| A `v*` tag | the same, built without the caches, and `version`; then, once the owner approves, `sign` and `release` | a **draft** release: the AppImage, its `.sha256` and `.asc`, `setup.exe` and its `.sha256` |

All of it runs on GitHub's hosted `ubuntu-24.04` runners, free for a public repository. Each job runs
the script it would run on a development machine, so a CI failure reproduces locally:

| Job | Runs | About |
|---|---|---|
| `tier1 1 of 3` to `3 of 3` | `scripts/test-tier1.sh`, a part each, measured ("Tier 1's parts", below) | 1½ min each |
| `coverage` | `scripts/coverage_report.py report --check` on the parts' data ("Coverage", below) | ½ min |
| `ci-times` | `scripts/ci_times.py` on its own run: each part within 5 minutes, the parts within 1.4:1 | |
| `appimage` | `scripts/build-appimage.sh` | 1 min |
| `windows` | `scripts/build-windows.sh`: PyInstaller and Inno Setup under Wine, in Docker, as the Windows VM tests it (`build.md`, "Windows") | 3 min |
| `ci` | passes only when tier 1's parts, `coverage` and both builds did | |
| `version` | tags only: the tag must be `v` and `__version__` (`src/appkata_core/__init__.py`) | |
| `sign` | tags only, in the `release` environment: signs the AppImage | |
| `release` | tags only: `gh release create --draft` with every file | |

`ci` is the one check the `master` ruleset requires (GENESIS.md, step 4): a pull request can't
merge while tier 1 fails, an area's coverage falls below its floor or either build breaks, and jobs
can be added without changing the ruleset. `ci-times` reports beside it and doesn't hold a merge.
The tiers that need KVM or a desktop (2 and 3, [`testing.md`](testing.md)) stay on the development
machine: GitHub advises against self-hosted runners for a public repository, since anyone can open a
pull request and run code on them.

## Tier 1's parts

Tier 1 runs as 3 jobs side by side, each `scripts/test-tier1.sh` with `APPKATA_PART=k/3`, which keeps
part k of the tests collected ([`tests/parts.py`](../tests/parts.py)). The parts are split by measured
time: each test weighs what it took in CI, from [`tests/durations/`](../tests/durations/), a file per
area ([`scripts/areas.py`](../scripts/areas.py)), or what a short test of its area takes; the
heaviest go first, each to the part with the least so far. Tests that share a module- or
class-scoped fixture stay in one part. Every part collects the whole suite and makes the same
choice, so a test runs in exactly one part; a time out of date only makes the parts less even.

Each part keeps what its tests took (`APPKATA_DURATIONS=1`, the `durations-k` artifacts).
`scripts/ci_times.py durations RUN` gathers a run's into `tests/durations/`, to refresh the split
after tests are added or moved, or when the parts come apart.

`ci-times` ([`scripts/ci_times.py`](../scripts/ci_times.py)) checks the run's times: each part within
**5 minutes**, and the slowest part at most **1.4 times** the quickest. Past either, the parts are
split again, by fresh times or into more parts; making a test itself quicker is the owner's call.
The script runs by hand too, on a run or a pull request (`scripts/ci_times.py --pr N`).

Within a part the tests run one at a time, without pytest-xdist. Measured on GitHub's runners, two
or four workers took about a third off a part's tests, about 15 seconds of a job's 90 once the parts
are balanced: each job spends about 40 seconds setting up, the publish tests wait on fixed sleeps,
and the workers start, and are measured, one by one. Two tests of `test_sandbox_user_shaped.py`
also fail under xdist: the launch their recording bwrap should see isn't in its log. The parts meet
the budget without it.

## Coverage

Each part runs its tests under coverage.py (`APPKATA_COVERAGE=1`; the pin is `COVERAGE` in
`packaging/versions.env`, the settings `[tool.coverage.*]` in [`pyproject.toml`](../pyproject.toml)):
lines and branches of `src/` and `scripts/`, in pytest's process and in every Python process the
tests start that inherits its environment (`patch = ["subprocess"]`). A process started with an
environment of its own, or on the system's `python3`, isn't measured.

The `coverage` job combines the parts' data and runs
[`scripts/coverage_report.py`](../scripts/coverage_report.py) `report --check`:

- **By area**: line and branch coverage of each area's code ([`scripts/areas.py`](../scripts/areas.py),
  the same areas as the `area:` labels), in the job's summary and in `summary.md`.
- **A floor per area**, in [`tests/coverage-floor.json`](../tests/coverage-floor.json): an area below
  its floor in lines or branches fails the job, and so `ci`. `coverage_report.py floor` raises each
  floor to a run's measure less **3 lines and 3 branches**, rounded down to a tenth of a point, so
  run-to-run jitter doesn't fail a small area; it never lowers one. A floor is lowered only by hand,
  with the reason in the commit.
- **The changed lines**: of the lines a pull request adds or changes in `src/` and `scripts/`, how
  many tier 1 reaches, and a notice on each of the largest stretches it doesn't, which the pull
  request shows on those lines.
- **QML** isn't Python, and coverage.py can't read it: the `qml` area is listed with its file count
  and no figure, and has no floor. Its tests (`test_qml_slots.py`, `test_dialog_contract.py`, the
  layout and theme tests) drive the QML offscreen against a real Backend, which counts in
  `ui-backend`.

Coverage comes from CI's tier 1 only: a floor is raised from the `coverage` artifact of a CI run on
the commit it describes (`gh run download RUN -n coverage -D build/coverage-ci`, then
`coverage_report.py floor build/coverage-ci/totals.json`), never from a local run. The artifact
holds the HTML report (`html/index.html`), `totals.json`, `files.json` (each file's counts) and
coverage.py's own `coverage.json` (each file's lines and branches missed).

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

The "Primary key fingerprint" `gpg` names must be the one the README publishes,
`A5C4 FAB7 54C2 34D3 8C98  3D94 02E7 71CD 068A 1ABD` (GENESIS.md step 7). Windows' installer isn't signed yet
(Authenticode needs a certificate, `build.md`, "Signing"); it has its `.sha256`.

## The draft, and publishing it

A published release reaches every AppKata at its next sync, since AppKata takes its own updates from
this repository's releases (requirement 2.11). So CI makes a **draft**, which only the repository's
writers see, and the owner publishes it after the checks no runner can make
([`RELEASE.md`](RELEASE.md#4-the-field-test), 4: the field test by hand, which uses the draft's files).

`scripts/publish.sh` walks through it: `release` tags, waits for the run, shows the two `sha256`
notices, approves the signing and verifies the draft, and `publish` publishes it once the field test
is done. What each command does and refuses is in [`RELEASE.md`](RELEASE.md#8-what-publishsh-does).
`resume`, after a failed run is run again (`gh run rerun RUN`, with or without `--failed`), reads
each `sha256` notice from the attempt that built the file, since a job carried into a new attempt
keeps none.

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

`build/appimage-cache` (Python, PySide6's wheels, appimagetool, the runtime; the coverage job's
Python too), tier 1's PySide6 folder and `build/wine-cache` are cached between runs, keyed on `packaging/versions.env` (and, for
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
