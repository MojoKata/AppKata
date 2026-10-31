# Testing

What runs when, on which environment, and how long it takes. Requirement 1.1 promises only what
these environments test (the owner's decision, 2026-10-24). An environment leaves this list, and 1.1,
together; Fedora, RHEL and its rebuilds come back if RPM packaging is taken up again.

## Tiers

| Tier | When | What it's for |
|---|---|---|
| 1 | every change | the whole suite in one container: the gate for every commit (about 2 minutes); CI runs it too, with both builds, on every pull request and push to `master` |
| 2 | before pushing, with a CI build in parallel | fast checks of what most changes can break, side by side (about 5 minutes) |
| 3 | in parallel, "just to be sure" | slower or specialised environments, side by side (about 15 minutes; the two Ubuntu VMs one after the other, since they share files) |

CI ([`github-workflows.md`](github-workflows.md)) runs tier 1, the AppImage build and the
installer build on GitHub's runners; its `ci` check gates merging. The rest of tiers 2 and 3 needs
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
| 1 | Ubuntu 24.04 LTS | 1, 2, 3 | 2 · 4 · 4 · 1 · 3 est. min | ~6 GB | **1:** the suite, `scripts/test-tier1.sh` (container, the release's Python and PySide6) · **2:** the screenshot tour and its checks, `scripts/test-layout.sh` · **2:** `scripts/test-sandbox.sh launcher-vm` (a VM: Ubuntu's kernel and user-namespace restriction, AppKata's AppArmor profile) · **3:** the AppImage started on X11 and Wayland (`scripts/test-appimage.sh`, desktops) · **3:** package channels, apt and Flatpak (`scripts/test-channels.sh ubuntu ubuntu-pk`) |
| 2 | Linux Mint 22.3, the current release | 2, 3 | 3 · 3 · 4 · 5 · 1 est. min | ~45 GB | **2:** `scripts/test-sandbox.sh launcher` (container, with what a stock install has that changes what a sandboxed app meets: dbus-x11, gnome-keyring, Firefox, a display) · **2:** the AppImage tour, `--install-self`, host libraries and desktop start (`scripts/test-appimage.sh`) · **3:** a VM installed from the official ISO, `scripts/test-desktop-vm.sh run mint22.3`: in its Cinnamon session, logged in as a user, the stock system reported, the AppImage started as a user starts it, the launcher tests, the field test (`scripts/sandbox/field-test.sh --non-interactive`), screenshots of the session (`build mint22.3` once: 3 min, 8 GB) · **3:** `wayland`, `kwin`, `inputmethod`, `filedialogs`, `consumers` (containers) · **3:** package channels, apt (`scripts/test-channels.sh mint`) |
| 3 | Ubuntu 22.04 LTS | 2, 3 | 1 · 1 min | ~3 GB | **2:** the AppImage build (`scripts/build-appimage.sh`), on the oldest glibc 1.1 supports (2.35) · **3:** the AppImage started on X11 and Wayland. The sandbox isn't tested here (1.1) |
| 4 | LMDE 7, the current release | 3 | 4 · 2 · 1 · 2 · 1 min | ~35 GB | **3:** a VM installed from the official ISO, `scripts/test-desktop-vm.sh run lmde7`: the same as Mint's (`build lmde7` once: 2 min, 8 GB) · **3:** `scripts/test-sandbox.sh launcher-lmde7` · **3:** the AppImage started on X11 and Wayland · **3:** `filedialogs-lmde7` (Qt 6.8, GTK 4.18) · **3:** `kwin-lmde7` (Plasma 6) |
| 5 | Windows 10 22H2 | 3 | 2 · 7 min | ~40 GB | **3:** the installer build (`scripts/build-windows.sh`, Wine in a container) · **3:** the VM (`scripts/test-windows-vm.sh --tests --e2e --shots`): install, the suite, end to end, the tour, uninstall. The VM can be shared with the machine's other projects (`coworker/vm`) |
| 6 | Ubuntu 26.04 LTS | 3 | 3 min | ~1 GB | **3:** `scripts/test-sandbox.sh launcher-vm26`: the newest sandbox versions (bwrap 0.11.1, portal 1.21), under the system's own bwrap profile |

The AppImage checks are described in [`build.md`](build.md) ("AppImage"), the sandbox runs in
[`app-sandboxing.md`](app-sandboxing.md) ("Tests, in four tiers"), the Windows VM in `build.md`
("Windows").

## What each environment boots with

What the documents say of a system's kernel and its boot-time settings is said here once, as each
VM that boots the system found it: the Ubuntu 24.04 and 26.04 VMs and the Mint 22.3 and LMDE 7
desktop VMs check their own row (`tests/test_booted.py`, review 3, E10). A container can't: it runs
on the test machine's kernel. Ubuntu 22.04 has no row, since the sandbox isn't tested there.

| Environment | Kernel, as tested | Unprivileged user namespaces | AppKata's AppArmor setup (17.10) |
|---|---|---|---|
| Ubuntu 24.04 LTS | 6.8 | restricted, by Ubuntu's `/usr/lib/sysctl.d/10-apparmor.conf` | needed |
| Linux Mint 22.3 | 6.14 | allowed: Mint's `/etc/sysctl.d/20-apparmor-mint.conf` lifts Ubuntu's restriction | not needed |
| LMDE 7 | 6.12 | allowed: Debian's kernel has no such restriction | not needed |
| Ubuntu 26.04 LTS | 7.0 | restricted, with Ubuntu's own `bwrap-userns-restrict` profile for bwrap | not needed: the system's own profile (17.10.2) |

## By hand, before a release

The field test's questions need a person at a real desktop: what an app's own file dialog shows,
whether a tray icon appears, the setup's password prompt and the rest of "What it asks the tester"
in [`local-proxy-test-plan.md`](local-proxy-test-plan.md). The desktop VMs (2 and 4 above) run every
automatic check of `scripts/sandbox/field-test.sh` and list these questions as MANUAL. Run it
without `--non-interactive` on real hardware, on Mint 22.3, LMDE 7, Ubuntu 24.04 and Ubuntu 26.04
(it asks the AppArmor setup's questions only where the table above says the setup is needed). It is
step 6 of [`build.md`](build.md)'s "Before tagging a release".

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
4. Still to do, at the first release: point this section and build.md's step 6 at its tracking issue.

## Downloaded ISOs

ISOs are shared with the machine's other projects by the protocol in
[`coworker/iso`](../coworker/iso/README.md): they live in one folder, `$ISO_DIR` (`~/iso` unless
`local.env` says otherwise), each beside its SHA-256 (`<iso>.sha256`), and a project that needs one
claims it with an empty file named after itself, `<iso>.appkata` here. `coworker/iso/download.sh ISO
PROJECT ISO_URL SHA_URL` fetches an ISO into that folder as `ISO.part` (run it again after a
failure and it resumes), checks its SHA-256 against `SHA_URL` (one hash, or a mirror's list naming
the ISO), keeps that as `ISO.sha256`, renames the ISO into place and claims it. When AppKata is done
with one, `scripts/test-desktop-vm.sh release NAME` gives up its claim, and the ISO goes only with
the last claim. Never download an ISO into this repository's folders.

AppKata claims `linuxmint-22.3-cinnamon-64bit.iso` and `lmde-7-cinnamon-64bit.iso`, for the desktop
VMs (`scripts/test-desktop-vm.sh` claims its ISO each time it runs):

    coworker/iso/download.sh linuxmint-22.3-cinnamon-64bit.iso appkata \
        https://pub.linuxmint.io/stable/22.3/linuxmint-22.3-cinnamon-64bit.iso \
        https://pub.linuxmint.io/stable/22.3/sha256sum.txt
    coworker/iso/download.sh lmde-7-cinnamon-64bit.iso appkata \
        https://pub.linuxmint.io/debian/lmde-7-cinnamon-64bit.iso \
        https://pub.linuxmint.io/debian/sha256sum.txt
