# GitHub Actions: CI, the signed AppImage and the draft release

What [`.github/workflows/ci.yml`](../.github/workflows/ci.yml) runs, when, and why it is built the
way it is: the CI walk thru's decisions of 2026-10-24. One-time setup (the repository's settings,
the release key) is in [`GENESIS.md`](GENESIS.md); building by hand, in [`build.md`](build.md);
the release checklist, in [`RELEASE.md`](RELEASE.md); what users can check a download against, in
[`gpg.md`](gpg.md).

## What runs when

| Event | Jobs | What it leaves |
|---|---|---|
| A pull request, a push to `master` | `tier1` in 3 parts, `tour`, `appimage`, `windows`, then `coverage` and `ci-times`, then `site` and `ci` | the AppImage and `setup.exe`, each with its `.sha256`, unsigned, as the run's artifacts (`appimage`, `windows`; GitHub keeps them 90 days); the Linux screenshots (`tour`, 90 days); the coverage report (`coverage`, 30 days); each part's tests' times (`durations-1` to `-3`, 30 days); the Pages site as this commit would publish it (`site`, 30 days) |
| A push to `master` | the same, then `pages` | the site, published at the repository's GitHub Pages ("The Pages site", below), with this push's tour |
| A `v*` tag | the same, built without the caches (but the tour's demo data), and `version`; then, once the owner approves, `sign` and `release` | a **draft** release: the AppImage, its `.sha256` and `.asc`, `setup.exe` and its `.sha256`; the release's tour (`tour`), which the site keeps once the release is published |
| By hand, [`mutate.yml`](../.github/workflows/mutate.yml) (and a trial on a pull request that changes it or its tools) | `plan`, then a `mutate` job per 1000 code lines or so, 14 at once: mutation testing ([`testing.md`](testing.md#mutation-testing)) | each job's outcomes, survivors and log (`mutation-<job>`, 90 days), which `scripts/mutate.py gather` turns into the areas' baselines |

All of it runs on GitHub's hosted `ubuntu-24.04` runners, free for a public repository. Each job runs
the script it would run on a development machine, so a CI failure reproduces locally:

| Job | Runs | About |
|---|---|---|
| `tier1 1 of 3` to `3 of 3` | `scripts/test-tier1.sh`, a part each, measured ("Tier 1's parts", below) | 1 min each |
| `coverage` | `scripts/coverage_report.py report --check` on the parts' data ("Coverage", below) | ½ min |
| `tour` | `scripts/tour-data.sh`, `scripts/test-layout.sh`, then `scripts/test-screenshot-text.sh` on its screens ("The tour", below) | |
| `ci-times` | `scripts/ci_times.py` on its own run: each part within 5 minutes; the parts more than 1.4:1 apart are a warning | |
| `site` | `scripts/coverage_site.py release-tours` and `build` on the coverage report and the tour ("The Pages site", below) | |
| `appimage` | `scripts/build-appimage.sh` | 1 min |
| `windows` | `scripts/build-windows.sh`: PyInstaller and Inno Setup under Wine, in Docker, as the Windows VM tests it (`build.md`, "Windows") | 3 min |
| `ci` | passes only when tier 1's parts, `coverage` and both builds did | |
| `pages` | pushes to `master` only, after `ci` and `site`: publishes the site | |
| `version` | tags only: the tag must be `v` and `__version__` (`src/appkata_core/__init__.py`) | |
| `sign` | tags only, in the `release` environment: signs the AppImage | |
| `release` | tags only: `gh release create --draft` with every file | |

`ci` is the one check the `master` ruleset requires (GENESIS.md, step 4): a pull request can't
merge while tier 1 fails, an area's coverage falls below its floor or either build breaks, and jobs
can be added without changing the ruleset. `ci-times`, `tour` and `site` report beside it and don't hold
a merge; a `tour` that fails leaves `site`, and so `pages`, without a run.
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

`ci-times` ([`scripts/ci_times.py`](../scripts/ci_times.py)) checks the run's times: a part past
**5 minutes** fails it, and the parts are split again, by fresh times or into more parts. The slowest
part more than **1.4 times** the quickest is a warning: one GitHub runner can be half again as slow as
another at setup and tests alike, so one run can't tell an uneven split from a slow runner, and a
warning that keeps coming back is the sign to refresh the times. Making a test itself quicker is the
owner's call.
The script runs by hand too, on a run or a pull request (`scripts/ci_times.py --pr N`).

Within a part the tests run one at a time, without pytest-xdist. Measured on GitHub's runners, two
or four workers took about a third off a part's tests, which is now some 7 seconds of a job's
70: a part's tests take about 22 seconds, and its setup about 40. Two tests of
`test_sandbox_user_shaped.py` also fail under xdist: the launch their recording bwrap should see
isn't in its log. The parts meet the budget without it.

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

## The tour

The `tour` job makes the Linux screenshots on every run, a pull request's included: every screen of
`src/appkata/tour.py` in both themes, at the design point (1920 × 1040), in tier 1's container
(`scripts/test-layout.sh`, [`build.md`](build.md#running-from-source-tests-and-screenshots)). In order:

1. **The demo data**, `build/tour-data`, by `scripts/tour-data.sh`: as the cache brought it when
   `scripts/demo_data.py` hasn't changed since it was made; made again from its own synced Catalog
   (`demo_data.py remake`, no network) when it has; else built and synced from GitHub with the job's
   token (`GITHUB_TOKEN`: the API's own limit, not the 60 an hour a runner's address shares), and kept
   only when `demo_data.py check` passes; and when that fails, restored from the snapshot in
   `tests/data/demo` (`demo_data.py restore`, no network) with a warning on the run. The cache is
   keyed on `demo_data.py`, so a change to it remakes the data from the entry before; GitHub drops an
   entry unused for 7 days, and the next run syncs afresh. A tag's run uses the cache too: the demo
   data isn't a release input, and a release's tour should show what `master`'s did.
2. **The tour and its layout check**: a text drawn outside its box fails the job.
3. **The screenshot text check**, `scripts/test-screenshot-text.sh` on every screen (tesseract, in a
   container built from tier 1's pinned Ubuntu 24.04, `NOBLE_IMAGE`, so what it reads changes only
   when the pin moves): a private name, another repository's address or a screen it couldn't read fails the
   job, before anything is uploaded.
4. **The `tour` artifact**: `dark/` and `light/`, kept 90 days, so a tag's lasts until its release is
   published and the site takes it. `site` publishes master's.
5. **The `tour.html` artifact**, for a review in the browser: `scripts/tour_page.py` writes one page
   with every screen inlined, those whose bytes differ from master's published tour first, each beside
   master's, then the new ones, the ones gone and, folded away, the rest. It is uploaded unzipped
   (`actions/upload-artifact`'s `archive: false`), so the run's list of artifacts opens it in the
   browser rather than downloading a zip. The screens that show the day (the Audit's) differ from
   master's whenever the two were made on different days. The job's summary, which a pull request's
   checks link to, names the screens that changed and links the page.

The job runs from `~/kata/AppKata`, a link to the checkout, so the paths the screens show read as on
a development machine (`~/kata/AppKata/build/tour-data/…`). In the first hour of a UTC day the tour
shows its times an hour behind UTC, since the Audit's day has no room for today's entries yet
(`demo_data.py offset`). It takes about 7 minutes (the tour 4½, the text check 1½), and isn't part of
`ci`: it holds the site, not a merge.

The Windows screenshots and the mockups stay committed; the Windows VM makes the Windows set
([`build.md`](build.md), "Windows"), never a GitHub runner.

## The Pages site

The repository's GitHub Pages site, at `https://<owner>.github.io/<name>/` (for this repository
https://mojokata.github.io/AppKata/), is built by [`scripts/coverage_site.py`](../scripts/coverage_site.py)
and published by GitHub Actions on each push to `master`. It has three pages:

- **Coverage** (`index.html`): the `coverage` job's figures by area against their floors, each area's
  files linked to their line-by-line report (`report/`), and each area's line and branch coverage
  over the pushes, with the sums *App* (every area but the scripts') and *Overall*. Beside it are
  `history.json`, a point per push (its commit, pull request, totals by area and findings by area),
  and `files.json`.
- **Hardening** (`hardening.html`, [`scripts/hardening.py`](../scripts/hardening.py)): each sweep
  of the review skill ([`REVIEW.md`](REVIEW.md)), a label `sweep:<name>` such as `sweep:CR1`: its
  anchor, the issue with that label and no parent, which is the sweep's own step, and its steps, the
  anchor's sub-issues titled "CR1.n …", each with the pull request GitHub links as closing it; each
  step's findings, its sub-issues, with their severity (a body's "severity High", "Med" or "Low"),
  area (the `area:` label, else the step's) and state; the coverage and findings by area; and the
  open issues labelled `gap` or `question` that aren't findings. With no sweep label on any issue the
  page shows no sweeps and the rest as usual. It reads the issues, not the project board. Only an
  issue's number, title, labels, state and severity reach the page; its body text doesn't.
  A closed step shows what changed in its areas at its pull request's merge, from the history.
  Each area also shows its mutation testing, from its latest record in `docs/hardening/mutation/`
  (its survivors of its changes), marked "baseline, changed since" when a module has changed since
  that record or isn't in it ([`testing.md`](testing.md#mutation-testing), `mutate.py stale`).
- **Screenshots** (`screenshots/index.html`): the Linux tour ("The tour", above), master's under
  `screenshots/master/`, replaced by each push, and each release's under `screenshots/<version>/`,
  kept; all listed in `screenshots/index.json`. `--screenshots DIR` adds the versions a folder holds
  (`DIR/<version>/…`) and replaces those already published: the `site` job puts its run's `tour`
  artifact in `DIR/master/`, and `coverage_site.py release-tours DIR` puts in `DIR/<version>/` each
  published release's tour the site doesn't hold yet, the `tour` artifact of CI's passing run of its
  tag (`gh run download`, with the job's token and `actions: read`). A release's tour joins the site at
  the first push to `master` after the release is published; one whose run or artifact is gone (90
  days) is named in a warning and left out, and the site is built without it. Each build also writes
  `screenshots/latest/`, a copy of the newest release's tour, or of master's while no release is on
  the site, and names its version as `latest` in `screenshots/index.json`; it is made afresh each
  time, never carried. The README's screenshot is `screenshots/latest/dark/A01-apps.png`, so the
  front page shows what users download once a release exists.

The `site` job builds it on every run, a pull request's included, after `coverage` and `tour`: it
downloads the `coverage` and `tour` artifacts, brings the published releases' tours (`contents: read`,
`actions: read`), reads the issues with the job's token (`issues: read`, `pull-requests: read`),
runs `scripts/public_text.py check` on the pages and keeps the site as the `site` artifact, so a pull
request's site can be downloaded and opened (`gh run download RUN -n site`). A fork's own pushes
skip both jobs (`github.event.repository.fork`): its site would name the fork, which the check refuses,
and a pull request from a fork runs in this repository, so it still builds the site. The `pages` job runs on
a push to `master` only, after `ci` and `site`: it alone has `pages: write` and `id-token: write`,
deploys to the `github-pages` environment, which takes deployments from `master` alone, and publishes
the `site` artifact with `actions/upload-pages-artifact` and `actions/deploy-pages`.

A Pages deployment replaces the whole site, so what the site keeps across pushes lives on the site
itself: each build reads `history.json` and `screenshots/index.json` (and the files it lists) back
from the published site and carries them into the new one, with this commit's point added last (a
commit already there, a run done again, moves to the end). A site that answers with neither file
starts afresh only while there is no site at all; any other failure to read them, or the issues,
fails the job in CI, so a bad moment never starts the history over. A run on `master` never cancels
another that is running (`concurrency`), so each build reads what the one before it published; of
several pushes waiting behind a running one, GitHub keeps only the newest, so the others add no
point.

The repository is `GITHUB_REPOSITORY` in CI. Run by hand, `coverage_site.py build` takes the
repository `APPKATA_REPO` names (`src/appkata_core/__init__.py`), reads the issues with `gh`'s token,
and builds a preview into `build/site/` from a `coverage` artifact:

```sh
gh run download RUN -n coverage -D build/coverage
python3 scripts/coverage_site.py build
```

`APPKATA_SITE` reads the history from another address (a local server, say).

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
this repository's releases (R2.11). So CI makes a **draft**, which only the repository's
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
Python too), tier 1's PySide6 folder (tier 1's and the tour's) and `build/wine-cache` are cached between runs, keyed on `packaging/versions.env` (and, for
the Windows build, its script and the `icuuc.dll` stand-in's source). A tag's run uses none of these: a
release is built from the pinned sources alone. The tour's demo data, `build/tour-data`, is cached on
tags too, keyed on `scripts/demo_data.py` ("The tour"). The pinned files are checked against their
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
