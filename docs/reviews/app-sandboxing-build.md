# App sandboxing: status, handoff and build log

A record of the sandboxing work as it stood when the design moved to
[`docs/architecture/A1-app-sandboxing/`](../architecture/A1-app-sandboxing/README.md), kept as it was written.

## Status and handoff

Status: **implemented and reviewed** — the design (Decisions 1–19) was agreed, written as formal
requirements in [requirements R17](../requirements/R17-app-sandboxing/README.md) (decisions in [`gaps.md` §16](../gaps.md),
feature row in the [README](../../README.md)), **built in `appkata_core`/`appkata` with tests and
real-app screenshots**, and taken through nine review rounds and two reviews since
([`reviews/`]()), whose findings are fixed or held open by a harness's list. The experiments behind it were run on
2026-10-08/09 (`scripts/sandbox/`, three rounds); the code landed 2026-10-09; the reviews and their
fixes 2026-10-10 to 2026-10-24. What remains is **the field test's questions on a real desktop** (below) and the explicitly
**deferred** items ([Plan](app-sandboxing-build.md#plan) step 7, R17.18).

**This document is the rationale and evidence; R17 is the spec.** Read R17 for the
contract and here for *why* each choice was made, the experiment results, the [Decisions](../architecture/A1-app-sandboxing/A1.12-decisions.md),
the [Plan](app-sandboxing-build.md#plan) (now a build log — what each step became), and the mockups ([Screens](../architecture/A1-app-sandboxing/A1.7-screens.md)).

**Handoff to a fresh session.** The work merged on 2026-10-24, before the repository was
published; the commits the review records cite are in the private history that came before it.

- **The code is written.** The map is in the [Plan](app-sandboxing-build.md#plan): the core is
  [`appkata_core/sandbox.py`](../../src/appkata_core/sandbox.py) (templates, resolve/merge, the
  never-shared folders, AppArmor detection + pkexec setup, the launcher, the bus proxy,
  `.flatpak-info`, the `xdg-open` shim, the file-argument helper, AppImage extraction, the session
  warning); wired through [`install.py`](../../src/appkata_core/install.py) (launcher generation and
  staleness, `launch()`, uninstall-home) and [`trustfile.py`](../../src/appkata_core/trustfile.py)
  (the `Sandbox*` review lines); the UI is in [`backend.py`](../../src/appkata/backend.py) and the QML
  dialogs (`SandboxDialog.qml`, plus the sandbox parts of `InstallDialog`/`AppDetail`/
  `SettingsDialog`/`ConfirmDialog`).
- **Tests, in four tiers.** Local: `tests/test_sandbox.py` (the model and the launcher text),
  `test_sandbox_backend.py` (resolution, pinning, healing), `test_launch.py` (failure reporting),
  `test_sandbox_properties.py` (every reader of a grant set agreeing, over every template and
  override), `test_launcher_golden.py` (the launcher byte for byte, `tests/data/launchers/`),
  `test_sandbox_transitions.py` (nothing left behind by Off/on, re-save, heal, uninstall; the audit
  table in the snapshot), `test_sandbox_audit.py` (every mutation's audit row),
  `test_sandbox_adversarial.py` (hostile paths, arguments and names at every boundary of the
  launcher), `test_sandbox_threads.py` (the startup heal pass overlapping the UI thread),
  `test_sandbox_state.py` (the rows and files each *release* left, thawed into today's code — one
  snapshot per release in `tests/data/state/`, frozen before tagging; the steps are in
  [`RELEASE_AGENT.md`](../RELEASE_AGENT.md#1-prepare-a-release)), `test_dialog_contract.py` and
  `test_qml_slots.py` (the real QML driven offscreen against the real Backend).
  `tests/test_sandbox_run.py` runs the generated launchers under real bwrap, in a Linux Mint 22.3
  container (`scripts/test-sandbox.sh launcher`: bwrap 0.9.0, portal 1.20), an LMDE 7 one
  (`launcher-lmde7`: Debian 13, bwrap 0.12), an Ubuntu 24.04 VM with the AppArmor profile applied
  (`launcher-vm`, where the virtio GPU renders inside the sandbox) and an Ubuntu 26.04 VM under the
  system's own bwrap profile (`launcher-vm26`: bwrap 0.11.1, portal 1.21, the newest); which run
  when is in [`testing.md`](../testing.md). Until 2026-10-24 it also ran on Mint 21.3, Ubuntu 25.04,
  Rocky Linux 9, Debian 12 and Fedora 39 and 44, which left with them (R1.1). It
  includes the degraded host (a dependency stalled or removed at
  a time), the Strict counterpart of every desktop road, AppKata acting on an app while it runs,
  stand-in daemons and clients on the other end of every capability, two apps at once, and the
  product's own path end to end (a real archive installed, launched, updated, rolled back and
  uninstalled). `filedialogs` and `filedialogs-qt68` (GTK 4.14/4.18, Qt 6.4/6.8) and `consumers`
  (GLib, GTK3, GTK4, Qt, Chromium, Obsidian, dunst) run real apps behind generated launchers with
  the real portal; `wayland` runs the generated launcher under headless sway and mutter and real
  PipeWire, `kwin` and `kwin6` under KDE's compositor, `inputmethod` real IBus and Fcitx 5 through
  the filter; each prints `EXPECTED: ok` or exits 1. The
  third-party claims the spec makes are listed with their evidence in "Claims and their evidence"
  below. `.venv/bin/python -m pytest` runs the local tier; the screenshot tour and the AppImage
  build are in [`build.md`](../build.md). On a host without `bwrap` the app runs everything Off (no
  launcher generated); without `xdg-dbus-proxy` a Standard app runs sandboxed with no session bus
  (R17.1; review 2, F12).
- **Still owed:** the questions of the checklist in
  [`local-proxy-test-plan.md`](../local-proxy-test-plan.md) ("What it asks the tester";
  `scripts/sandbox/field-test.sh`), answered by a person at a real desktop: the setup's prompt and
  pkexec (on Ubuntu 24.04), an app's own file dialog (Obsidian's among them), "Open with", a tray
  icon with a real StatusNotifierWatcher and the media keys, a self-updating app, switching an app
  on, a password manager's browser integration; and a real GPU, NVIDIA included. The checklist's
  automatic checks run in a logged-in desktop already: the Mint 22.3 and LMDE 7 VMs, installed from
  the official ISOs, run the whole field test in a Cinnamon session, PipeWire sound included
  (`scripts/test-desktop-vm.sh`, [`testing.md`](../testing.md)). Everything else the plan once listed
  as "real hardware" — the file hand-over, the portals, the toolkits' dialogs, notifications,
  links — has been shown in the containers. That file also explains the
  launcher and the proxy part by part; the launcher's exact text is the goldens in `tests/data/launchers/`.
- **Deferred, not v1** (R17.18): the **Landlock** layer (execute-deny, per-port TCP — the Advanced
  toggles exist in the UI, disabled, badged "Later"), the **Wayland security-context** protocol
  (wlroots sessions get the warning, not the fix), **personal/reviewer-defined templates**, config
  **import on enable-later**, a **fuller seccomp filter** beyond the terminal-injection one,
  **squashfuse**, enforcing the play/record sound split, and NVIDIA device nodes.
- **Adjacent follow-ups** raised during this work, each its own PR: publisher-GPG verification of
  downloads ([`gpg.md`](../gpg.md)) and a release workflow ([`github-workflows.md`](../github-workflows.md)).

The branch also holds [`local-proxy-test-plan.md`](../local-proxy-test-plan.md), the
`requirements.md`/`gaps.md`/README integration, the mockups (`screenshots/mocks/`, generated by
`screenshots/src/render.js`) and the real-app screenshots (`screenshots/linux/`), and the test harness
(`scripts/test-sandbox.sh` + `scripts/sandbox/`). Merging the PR adopts the feature.

## Plan

This was the build order; steps 1–6 are **done** (a build log now), step 7 is **deferred** (R17.18) and
step 8 is **separate work**. File pointers are to the commit on branch `app-sandboxing`.

1. **AppArmor profile + run-time detection.** ✅ `sandbox.userns_works()` (the `bwrap --unshare-user`
   probe, cached), `userns_restricted()`, `support_status()`, `PROFILE_TEXT` and `install_profile()`
   (the one-time pkexec write + `apparmor_parser -r` of `/etc/apparmor.d/appkata-sandbox`). Status and
   the Set-up/Enable controls are in Settings → Sandbox and the per-app App Detail banner; declined →
   the app runs Off with a warning (decision 6).
2. **Templates + launcher.** ✅ `appkata_core/sandbox.py`: the built-in templates and
   `resolve`/`intersect`/`apply_overrides` (porting `scripts/sandbox/merge.py`); `build_launcher()`
   emits `~/bin/apps/<app>/run` with the grant set baked in and the filtered `xdg-dbus-proxy`;
   `proxy_args()` maps capabilities; `write_flatpak_info()` the identity; `launcher_text()` the
   pure text the startup pass compares against. Tests: `tests/test_sandbox.py` (the model and the
   launcher text), `test_sandbox_properties.py` (every reader of a grant set agreeing over every
   template and override), `test_launcher_golden.py` (the launcher byte for byte), and
   `test_sandbox_run.py` (the launchers run under real bwrap in the Mint container and the Ubuntu
   24.04 VM).
3. **Tarballs.** ✅ `install._activate()` → `_sandbox_launcher()` generates the launcher and points the
   `.desktop` `Exec=` and the command link at it; `launch()` routes through it; the install Sandbox card,
   App Detail Sandbox section and the Change dialog are wired; sandbox changes are audited (R17.16).
4. **AppImage.** ✅ `.AppImage` runs directly at Off; Standard/Strict extract **lazily** inside the
   launcher (`_EXTRACT_BLOCK`, rebuilt if missing), run `AppRun`, and set `APPDIR`/`APPIMAGE`/`ARGV0`
   (decision 2). The extraction cache is cleaned up with kept versions.
5. **Display, sound, portals.** ✅ The launcher binds the Wayland or X11 socket at run time (X11 on
   Wayland too with the device grant), binds the PipeWire socket for sound (the play/record split
   is shown but not enforced — WirePlumber lets a sandboxed client record through the same
   sockets, deferred), hands file arguments over through the document portal, puts a portal-aware
   `xdg-open` first on the PATH, hides the host's desktop entries, and `session_warning()` drives
   the session caveat in App Detail and Settings (X11, and every Wayland compositor but GNOME's, R17.9). An end-to-end run on a physical desktop is
   the item still owed (`local-proxy-test-plan.md`). The **Wayland security-context** is deferred
   (step 7).
6. **Reviews.** ✅ `trustfile.py` parses/writes `Sandbox` / `Sandbox folders` / `Sandbox network` /
   `Sandbox sound` / `devices` / `services` / `app folder` (R10.3.1, Linux-only), and saving a review
   writes the user's own sandbox (`sandbox.as_review`, review 2 F9); `backend._resolved_sandbox()` merges Trusts least-privilege with the user
   winning; the **review badge** (`sandboxInfo.reviewBadge`) flags a version whose reviews suggest a
   change without widening access (decision 5).
7. **Deferred (R17.18), not v1:** the **Wayland security-context** protocol (close the wlroots
   screen/clipboard/input leak), the **Landlock** layer (execute-deny, per-port TCP; the Advanced
   toggles are present but disabled/"Later"), **personal templates** ("Save as template…"), config
   **import on enable-later** (v1 only warns, decision 12), a **fuller seccomp** filter beyond the
   terminal-injection one, **squashfuse** instead of unpacking, enforcing the play/record sound
   split, and proprietary-NVIDIA device nodes.
8. **Separate features (not this work):** [App categories](../architecture/A1-app-sandboxing/A1.4-app-categories.md) in the
   Catalog; reviewer-defined shared templates (deferred, leaned against). Adjacent, raised during this
   work: publisher-GPG verification ([`gpg.md`](../gpg.md)) and a release workflow
   ([`github-workflows.md`](../github-workflows.md)).

**After the build:** four review rounds (2026-10-10/12, [`reviews/app-sandboxing-1.md`](app-sandboxing-1.md))
found and fixed, each in its own commit with a test shown failing before: an escape through the
identity marker's location and another through the CLI tool's working directory, the real home put
back by a folder grant, planted symlinks at mount points, the portals refusing a marked caller
(decision 15), reviews widening a pinned app, Strict not enforcing its table, GLib starting the
host's browser inside, a Strict app dying with its caller, and a number of UI and state bugs. Then
five commits closed the *classes* those findings fell into (the QML driven against the real
Backend, grant-set invariants, launcher goldens, real consumers, transition snapshots), and the
branch was judged ready to merge, with the physical-desktop pass left for a release.

The feature now lives in R17 (decisions in `docs/gaps.md` §16), like the rest of
AppKata; this document is kept as its rationale and build log.
