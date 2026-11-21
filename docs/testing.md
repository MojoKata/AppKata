# Testing

What runs when, on which environment, and how long it takes. R1.1 promises only what
these environments test (the owner's decision, 2026-10-24). An environment leaves this list, and R1.1,
together; Fedora, RHEL and its rebuilds come back if RPM packaging is taken up again.

## Tiers

| Tier | When | What it's for |
|---|---|---|
| 1 | every change | the whole suite in one container: the gate for every commit (about 2 minutes); CI runs it too, with both builds, on every pull request and push to `master` |
| 2 | before pushing, with a CI build in parallel | fast checks of what most changes can break, side by side (about 5 minutes) |
| 3 | in parallel, "just to be sure" | slower or specialised environments, side by side (about 15 minutes; the two Ubuntu VMs one after the other, since they share files) |

CI ([`github-workflows.md`](github-workflows.md)) runs tier 1 (in 3 parts, measured by coverage.py),
the AppImage build and the installer build on GitHub's runners; its `ci` check gates merging. The rest of tiers 2 and 3 needs
KVM, a desktop or the shared Windows VM, and runs on the development machine.

### What each run may skip

Every pytest run a tier makes names its list of the tests it may skip, and why:
`tests/skips/<name>.txt` (`tests/conftest.py`; the walk thru of 2026-10-30, item 2). A skip the list
doesn't name is a failure, and so is a listed test that ran (take it off the list), so a run's
summary line counts both. The lists: `tier1` (CI's too), `launcher-mint22.3` and `launcher-lmde7`
(the containers), `launcher-vm-24.04` and `launcher-vm-26.04`, `desktop-mint22.3` and `desktop-lmde7`,
and `windows` (`test-windows-vm.sh --tests`). A run by hand, without `APPKATA_SKIPS`, checks nothing.
A skip that comes and goes with the machine (a VM that can't resolve names, a tool missing from an
image) is a fault of the run, not an entry for the list: the DNS test waits a minute for the
resolver before it skips.

## Environments

Run times are measured where a number is given plainly, and estimated where it says "est.".
Containers run on the test machine's kernel; the VMs on their own.

| # | Environment | Tier | Run time | Disk | Uses: tier, and notes |
|---|---|---|---|---|---|
| 1 | Ubuntu 24.04 LTS | 1, 2, 3 | 2 · 12 · 4 · 4 · 1 · 3 est. min | ~6 GB | **1:** the suite, `scripts/test-tier1.sh` (container, the release's Python and PySide6) · **1:** the suite at the times and in the zones where a test that reads the clock goes wrong, `scripts/test-clock.sh` (seven runs of tier 1, [issue #13](reviews/issue-13-clock.md)) · **2:** the screenshot tour and its checks, `scripts/test-layout.sh` · **2:** `scripts/test-sandbox.sh launcher-vm` (a VM: Ubuntu's kernel and user-namespace restriction, AppKata's AppArmor profile) · **3:** the AppImage started on X11 and Wayland (`scripts/test-appimage.sh`, desktops) · **3:** package channels, apt and Flatpak (`scripts/test-channels.sh ubuntu ubuntu-pk`) |
| 2 | Linux Mint 22.3, the current release | 2, 3 | 3 · 3 · 4 · 5 · 1 est. min | ~45 GB | **2:** `scripts/test-sandbox.sh launcher` (container, with what a stock install has that changes what a sandboxed app meets: dbus-x11, gnome-keyring, Firefox, a display) · **2:** the AppImage tour, `--install-self`, host libraries and desktop start (`scripts/test-appimage.sh`) · **3:** a VM installed from the official ISO, `scripts/test-desktop-vm.sh run mint22.3`: in its Cinnamon session, logged in as a user, the stock system reported, the AppImage started as a user starts it, the launcher tests, the field test (`scripts/sandbox/field-test.sh --non-interactive`), screenshots of the session (`build mint22.3` once: 3 min, 8 GB) · **3:** `wayland`, `kwin`, `inputmethod`, `filedialogs`, `consumers` (containers) · **3:** package channels, apt (`scripts/test-channels.sh mint`) |
| 3 | Ubuntu 22.04 LTS | 2, 3 | 1 · 1 min | ~3 GB | **2:** the AppImage build (`scripts/build-appimage.sh`), on the oldest glibc R1.1 supports (2.35) · **3:** the AppImage started on X11 and Wayland. The sandbox isn't tested here (R1.1) |
| 4 | LMDE 7, the current release | 3 | 4 · 2 · 1 · 2 · 1 min | ~35 GB | **3:** a VM installed from the official ISO, `scripts/test-desktop-vm.sh run lmde7`: the same as Mint's (`build lmde7` once: 2 min, 8 GB) · **3:** `scripts/test-sandbox.sh launcher-lmde7` · **3:** the AppImage started on X11 and Wayland · **3:** `filedialogs-lmde7` (Qt 6.8, GTK 4.18) · **3:** `kwin-lmde7` (Plasma 6) |
| 5 | Windows 10 22H2 | 3 | 2 · 7 min | ~40 GB | **3:** the installer build (`scripts/build-windows.sh`, Wine in a container) · **3:** the VM (`scripts/test-windows-vm.sh --tests --e2e --shots`): install, the suite, end to end, the tour, uninstall. The VM can be shared with the machine's other projects (the coworker protocol, `vms`) |
| 6 | Ubuntu 26.04 LTS | 3 | 3 min | ~1 GB | **3:** `scripts/test-sandbox.sh launcher-vm26`: the newest sandbox versions (bwrap 0.11.1, portal 1.21), under the system's own bwrap profile |

The AppImage checks are described in [`build.md`](build.md) ("AppImage"), the sandbox runs in
[the sandboxing record](reviews/app-sandboxing-build.md) ("Tests, in four tiers"), the Windows VM in `build.md`
("Windows").

## What each environment boots with

What the documents say of a system's kernel and its boot-time settings is said here once, as each
VM that boots the system found it: the Ubuntu 24.04 and 26.04 VMs and the Mint 22.3 and LMDE 7
desktop VMs check their own row (`tests/test_booted.py`, review 3, E10). A container can't: it runs
on the test machine's kernel. Ubuntu 22.04 has no row, since the sandbox isn't tested there.

| Environment | Kernel, as tested | Unprivileged user namespaces | AppKata's AppArmor setup (R17.10) |
|---|---|---|---|
| Ubuntu 24.04 LTS | 6.8 | restricted, by Ubuntu's `/usr/lib/sysctl.d/10-apparmor.conf` | needed |
| Linux Mint 22.3 | 6.14 | allowed: Mint's `/etc/sysctl.d/20-apparmor-mint.conf` lifts Ubuntu's restriction | not needed |
| LMDE 7 | 6.12 | allowed: Debian's kernel has no such restriction | not needed |
| Ubuntu 26.04 LTS | 7.0 | restricted, with Ubuntu's own `bwrap-userns-restrict` profile for bwrap | not needed: the system's own profile (R17.10.2) |

## By hand, before a release

The field test's questions need a person at a real desktop: what an app's own file dialog shows,
whether a tray icon appears, the setup's password prompt and the rest of "What it asks the tester"
in [`local-proxy-test-plan.md`](local-proxy-test-plan.md). The desktop VMs (2 and 4 above) run every
automatic check of `scripts/sandbox/field-test.sh` and list these questions as MANUAL. Run it
without `--non-interactive` on real hardware, on Mint 22.3, LMDE 7, Ubuntu 24.04 and Ubuntu 26.04
(it asks the AppArmor setup's questions only where the table above says the setup is needed). It is
step 4 of [`RELEASE.md`](RELEASE.md#4-the-field-test).

### Tracking the runs on GitHub

Set up on 2026-10-30 (the walk thru, item 4), once the repository was published: `scripts/publish.sh
setup` makes the `field-test` label, and `scripts/publish.sh field-test [VERSION]` opens a release's
issues as below. A release's issue can also be opened by hand, from the "Field test of a release"
template (`.github/ISSUE_TEMPLATE/field-test.yml`).

Each release gets one **tracking issue**, and each environment a **sub-issue** of it:

- **The release's issue**, "Field test: <version>", lists the environments above and closes when
  every sub-issue has closed, or when the owner waives one and says why in it.
- **An environment's sub-issue**, "Field test: <version> on <environment>", holds that
  environment's checklist, one box per question the field test asks there (the A1 questions only
  where the setup is needed), and one for a real GPU. Each environment can have its own tester and
  machine, and closes on its own.
- **A run is a comment** on its sub-issue: the run's `report.md`, which is Markdown already
  (`gh issue comment <n> --body-file appkata-fieldtest-…/report.md`), and its `.tar.gz`, attached
  through the web page (`gh` can't attach files). The tester ticks each box the run answered "yes".
- **A "no" is a bug**: its own issue, labelled `bug`, linked from the box it leaves unticked. The
  box is ticked once a later run, after the fix, answers "yes".
- **Review files record the outcome only**: the release's issue number and how it closed.

A [GitHub Project](https://docs.github.com/en/issues/planning-and-tracking-with-projects) over these
issues, with fields for the environment and the result, can follow once there are a few releases.
Discussions and commit statuses fit less well: neither holds a checklist with a state, and a status
can't carry the report.

**How it is set up:**

1. The `field-test` label, on the tracking issues and sub-issues: `publish.sh setup` makes it,
   `publish.sh check` reads it back (GENESIS.md, step 8).
2. The issue template, `.github/ISSUE_TEMPLATE/field-test.yml`, for the release's issue.
3. `scripts/sandbox/field-test.sh --issue-body ENVIRONMENT` prints an environment's checklist from
   the questions the field test itself asks there (`scripts/sandbox/fieldtest_questions.py`), so the
   plan, the script and the issue are one list: E11, in `tests/test_field_test_plan.py`, compares
   the checklist too, and the environments are this file's table.
4. Still to do, at the first release: point this section and RELEASE.md's step 4 at its tracking issue.

## Mutation testing

[mutmut](https://github.com/boxed/mutmut) changes AppKata's code one change at a time (a `<` for a
`<=`, a string emptied, a call's argument dropped) and runs the tests on each change. A change some
test fails on is **killed**; one every test passes with **survives**, and shows code the tests run but
don't check. It complements coverage ("Coverage", [`github-workflows.md`](github-workflows.md)),
which says only that a line ran. mutmut can't change QML, so the `qml` area has no mutation run.

[`scripts/mutate.py`](../scripts/mutate.py) holds the tools. mutmut changes the code it tests, so a
run never touches the checkout: it works in a copy (`APPKATA_MUTATE_WORK`, `build/mutate` unless set)
with `src/`, `scripts/` and `tests/` copied and the rest of the repository linked, so the tests read
it as in tier 1. It runs in tier 1's container, on the release's Python and PySide6
(`scripts/test-mutate.sh`, mutmut pinned as `MUTMUT` in `packaging/versions.env`), with all of tier
1's tests but those `UNFIT` names (each with its reason). mutmut runs every test once first, noting
the functions each one reaches, then runs each change against only the tests that reached its
function. Code a test reaches only in a process it starts is out of mutmut's sight: its changes count
as **no tests**.

mutmut stops at the first test that fails in that first pass, without naming it. A run then runs
pytest over the copy itself and runs each test that fails there once more on the checkout, as tier
1 does. A test that fails on the checkout too is a real failure, and stops the run. The others are
left out of the run, and mutmut starts again; the run's export and the area's baseline name each
(`dropped`) with its short traceback and the kind of failure it looks like: reads the mutated source,
git or links in the copy, leaks into processes tests start, or unknown. `summary` and `gather`
print, for each one `UNFIT` doesn't name, the line to add there. A test that
reads a module's source rather than running it reads it as written (`tests/written.py`): in a run,
from the checkout, since the copy's file holds every change at once.
Two things make the copy behave as the checkout for the rest (`scripts/mutate_plugin.py`): a script
runs under the module name mutmut gives its changes (`scripts.areas`), whatever name a test imports
it by, so its changes run at all; and a process a test starts runs the code unchanged during the
first pass, where it couldn't count its calls.

### A run by hand

    sh scripts/test-mutate.sh run src/appkata_core/windows.py src/appkata/winframe.py --workers 3
    sh scripts/test-mutate.sh summary            # the outcomes by file, the survivors by function
    sh scripts/test-mutate.sh check CHANGE tests/test_windows.py   # one change against one test file

A run's container is capped at `APPKATA_MUTATE_MEMORY` (6 GB unless set), swap included. The run
watches its own memory, as PSS: past `--limit` GB it stops, and a change's worker past
`--worker-limit` GB of its own is stopped, that change counted killed. `--only` runs named changes
again, `--debug` puts each of mutmut's pytest runs in its log (a run that fails at its first full
pass names the test there), and `--resume DIR` goes on from an earlier run's `export` folder. Each
survivor's change is written to `survivors.txt` in the work folder.

### The baseline

The `mutate` workflow ([`.github/workflows/mutate.yml`](../.github/workflows/mutate.yml)) runs every
area at once on GitHub's runners, started by hand (Actions, `mutate`, Run workflow):

- **`plan`** packs each area's modules ([`scripts/areas.py`](../scripts/areas.py)) into jobs of
  about `size` code lines (1000), the largest first; a larger module is a job of its own. Jobs are
  named by area (`store-1`, `scripts-3`), the same for the same tree, so `jobs` runs chosen ones again.
- **Each job** is a `run` of its modules with 4 workers, stopped at 5½ hours so what finished is
  kept (mutmut saves each outcome as it comes), and `export`, kept as its `mutation-<job>` artifact
  for 90 days. At most `parallel` (14) run at once, leaving room for pull requests' checks.
- **`resume`**, an earlier run's id: each job takes its artifact from that run and runs only the
  changes it left without an outcome (`run --resume`; mutmut keeps an outcome while its function's
  code is the same), so a job out of time goes on where it stopped. Its artifact holds every
  outcome, the earlier ones too.
- A pull request that changes the workflow or these tools runs a trial on one small module.

A run of every area is 20 jobs and takes about 4 hours. Most jobs take 3 to 30 minutes; the ones
whose code the most tests reach take longest, `store-1` (`db.py` and the rest of the store, about
3¾ hours) and `ui-backend-1` (`backend.py`, about 3 hours). Most jobs stay under 2 GB of memory;
a change that makes the code allocate without end grows its worker until the run stops it at 3 GB
of its own, so a trust job reaches 7½ GB (PSS) at its peak, within the runner's 16.

`scripts/mutate.py gather RUN...` downloads a run's artifacts and writes each area's baseline to
`docs/hardening/mutation/baseline-<area>.json` and its survivors to
`docs/hardening/mutation/survivors/<area>.json`; `record --from DIR...` does the same from a local
run's `export` folders. Runs gathered together must be of one commit, and a later run's outcome for
a change replaces an earlier one's, as a job run again in a later run replaces its tests left out. A fork's run (`--repo OWNER/NAME`) is recorded as a fork's,
without its name, and `--same-as COMMIT` records a commit of this repository whose code is the
run's own (checked file by file) in place of the run's: a run started from a branch made only to
start it, with a `push` trigger in its copy of the workflow (GitHub starts a `workflow_dispatch`
only from a workflow on the default branch).

### Reading a baseline

Each area has two files in `docs/hardening/mutation/`. `baseline-<area>.json` holds:

- **`made`**: the repository, the workflow runs and the commit it was made from, and mutmut's version.
- **The counts**: `mutants` (the changes), `killed`, `timeout` (a change that made the tests run past
  mutmut's limit, counted as caught), `survived`, `no tests` (no test reached its function), `other`
  (mutmut's "suspicious", a crash) and `not run` (a job stopped first).
- **`files`**: the same counts by file, and each file's `content`, its git blob at that commit:
  a file whose blob differs from the checkout's has changed since, and its counts are out of date.
- **`dropped`**: the tests left out of the area's runs, each with its traceback and kind; none, once settled.

`survivors/<area>.json` holds its survivors, one a line in each module's order: mutmut's name for the
change (`check` takes it), its file, function and line, and the lines it `removed` and `added`.

The baseline records the survivors; it doesn't settle them. Each area's step of a hardening sweep
settles its own: a test that fails on the change, a change to the code, or `# pragma: no mutate` on
the line with the reason it can't be caught (an equivalent change, say). An area with more than
about 200 survivors is settled in a relay. A settled area runs again (`jobs`) and its baseline is
gathered again.

## Downloaded ISOs

ISOs are shared with the machine's other projects by the
[coworker protocol](https://github.com/MojoKata/coworker) (the `coworker/` submodule;
`coworker/bin/coworker status` first): they live in one folder, `$COWORKER_HOME/downloads` (`~/coworker/downloads` unless
`COWORKER_HOME` says otherwise), each beside its SHA-256 (`<iso>.sha256`), and a project that needs
one claims it with an empty file named after its checkout directory, `<iso>.AppKata` here.
`downloads fetch ISO PROJECT ISO_URL SHA_URL` fetches an ISO into that folder as `ISO.part` (run it
again after a failure and it resumes), checks its SHA-256 against `SHA_URL` (one hash, or a mirror's list naming
the ISO), keeps that as `ISO.sha256`, renames the ISO into place and claims it. When AppKata is done
with one, `scripts/test-desktop-vm.sh release NAME` gives up its claim, and the ISO goes only with
the last claim. Never download an ISO into this repository's folders.

AppKata claims `linuxmint-22.3-cinnamon-64bit.iso` and `lmde-7-cinnamon-64bit.iso`, for the desktop
VMs (`scripts/test-desktop-vm.sh` claims its ISO each time it runs):

    coworker/bin/downloads fetch linuxmint-22.3-cinnamon-64bit.iso AppKata \
        https://pub.linuxmint.io/stable/22.3/linuxmint-22.3-cinnamon-64bit.iso \
        https://pub.linuxmint.io/stable/22.3/sha256sum.txt
    coworker/bin/downloads fetch lmde-7-cinnamon-64bit.iso AppKata \
        https://pub.linuxmint.io/debian/lmde-7-cinnamon-64bit.iso \
        https://pub.linuxmint.io/debian/sha256sum.txt
