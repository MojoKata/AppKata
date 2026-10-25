# App sandboxing (Linux)

Status: **implemented and reviewed** — the design (Decisions 1–19) was agreed, written as formal
requirements in [`requirements.md` §17](requirements.md) (decisions in [`gaps.md` §16](gaps.md),
feature row in the [README](../README.md)), **built in `appkata_core`/`appkata` with tests and
real-app screenshots**, and taken through nine review rounds and two reviews since
([`reviews/`](reviews/)), whose findings are fixed or held open by a harness's list. The experiments behind it were run on
2026-10-08/09 (`scripts/sandbox/`, three rounds); the code landed 2026-10-09; the reviews and their
fixes 2026-10-10 to 2026-10-24. What remains is **the field test's questions on a real desktop** (below) and the explicitly
**deferred** items ([Plan](#plan) step 7, requirement 17.18).

**This document is the rationale and evidence; `requirements.md` §17 is the spec.** Read §17 for the
contract and here for *why* each choice was made, the experiment results, the [Decisions](#decisions),
the [Plan](#plan) (now a build log — what each step became), and the mockups ([Screens](#screens)).

**Handoff to a fresh session.** The work merged on 2026-10-24, before the repository was
published; the commits the review records cite are in the private history that came before it.

- **The code is written.** The map is in the [Plan](#plan): the core is
  [`appkata_core/sandbox.py`](../src/appkata_core/sandbox.py) (templates, resolve/merge, the
  never-shared folders, AppArmor detection + pkexec setup, the launcher, the bus proxy,
  `.flatpak-info`, the `xdg-open` shim, the file-argument helper, AppImage extraction, the session
  warning); wired through [`install.py`](../src/appkata_core/install.py) (launcher generation and
  staleness, `launch()`, uninstall-home) and [`trustfile.py`](../src/appkata_core/trustfile.py)
  (the `Sandbox*` review lines); the UI is in [`backend.py`](../src/appkata/backend.py) and the QML
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
  [`build.md`](build.md), "Before tagging a release"), `test_dialog_contract.py` and
  `test_qml_slots.py` (the real QML driven offscreen against the real Backend).
  `tests/test_sandbox_run.py` runs the generated launchers under real bwrap, in a Linux Mint 22.3
  container (`scripts/test-sandbox.sh launcher`: bwrap 0.9.0, portal 1.20), an LMDE 7 one
  (`launcher-lmde7`: Debian 13, bwrap 0.12), an Ubuntu 24.04 VM with the AppArmor profile applied
  (`launcher-vm`, where the virtio GPU renders inside the sandbox) and an Ubuntu 26.04 VM under the
  system's own bwrap profile (`launcher-vm26`: bwrap 0.11.1, portal 1.21, the newest); which run
  when is in [`testing.md`](testing.md). Until 2026-10-24 it also ran on Mint 21.3, Ubuntu 25.04,
  Rocky Linux 9, Debian 12 and Fedora 39 and 44, which left with them (requirement 1.1). It
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
  build are in [`build.md`](build.md). On a host without `bwrap` the app runs everything Off (no
  launcher generated); without `xdg-dbus-proxy` a Standard app runs sandboxed with no session bus
  (17.1; review 2, F12).
- **Still owed:** the questions of the checklist in
  [`local-proxy-test-plan.md`](local-proxy-test-plan.md) ("What it asks the tester";
  `scripts/sandbox/field-test.sh`), answered by a person at a real desktop: the setup's prompt and
  pkexec (on Ubuntu 24.04), an app's own file dialog (Obsidian's among them), "Open with", a tray
  icon with a real StatusNotifierWatcher and the media keys, a self-updating app, switching an app
  on, a password manager's browser integration; and a real GPU, NVIDIA included. The checklist's
  automatic checks run in a logged-in desktop already: the Mint 22.3 and LMDE 7 VMs, installed from
  the official ISOs, run the whole field test in a Cinnamon session, PipeWire sound included
  (`scripts/test-desktop-vm.sh`, [`testing.md`](testing.md)). Everything else the plan once listed
  as "real hardware" — the file hand-over, the portals, the toolkits' dialogs, notifications,
  links — has been shown in the containers. That file also explains the
  launcher and the proxy part by part; the launcher's exact text is the goldens in `tests/data/launchers/`.
- **Deferred, not v1** (17.18): the **Landlock** layer (execute-deny, per-port TCP — the Advanced
  toggles exist in the UI, disabled, badged "Later"), the **Wayland security-context** protocol
  (wlroots sessions get the warning, not the fix), **personal/reviewer-defined templates**, config
  **import on enable-later**, a **fuller seccomp filter** beyond the terminal-injection one,
  **squashfuse**, enforcing the play/record sound split, and NVIDIA device nodes.
- **Adjacent follow-ups** raised during this work, each its own PR: publisher-GPG verification of
  downloads ([`gpg.md`](gpg.md)) and a release workflow ([`github-workflows.md`](github-workflows.md)).

The branch also holds [`local-proxy-test-plan.md`](local-proxy-test-plan.md), the
`requirements.md`/`gaps.md`/README integration, the mockups (`screenshots/mocks/`, generated by
`screenshots/src/render.js`) and the real-app screenshots (`screenshots/linux/`), and the test harness
(`scripts/test-sandbox.sh` + `scripts/sandbox/`). Merging the PR adopts the feature.

AppKata installs apps from the projects' own releases, so it can't vouch for what's inside them;
Trusts and reviews lower the odds of a hostile app, they don't contain one. This document plans
how AppKata could limit the harm an app does to the user's computer once it's installed.

**Scope.** Linux only, and only the two portable kinds AppKata installs itself (requirement 4.2.1):

- **AppImage** (`kind == "appimage"`)
- **Portable archives**: tarballs (`kind == "tarball"`), unpacked into versioned folders

Out of scope: `.deb`/`.rpm` (their scripts run as root at install time, so a run-time sandbox can't
undo what they did), Flatpak (already sandboxed; AppKata shows its permissions, 16.6.3), shell
installers (`.run`/`.sh`, not supported, and they stay unsupported), Windows and macOS.

## What a hostile app can do today

`launch()` (`install.py`) and the app-menu entry (`_desktop_entry`, `Exec="<path>" %U`) run the app
directly, as the user (sandboxed, the entry runs the launcher with `--appkata-menu` first, see Limits). On a desktop, the user's account holds everything that matters, so root
isn't needed. The experiment's probe, run unsandboxed, did all of this:

- read `~/.ssh` keys, browser cookies and `~/Documents`; read tokens in the environment
  (`GITHUB_TOKEN`, and anything else the session exports)
- come back on every login: append to `~/.bashrc`, write `~/.config/autostart/*.desktop`, a
  systemd user unit, or replace another app's menu entry
- replace other installed apps in `~/bin/apps/`, and its own files (so a future launch runs
  different code than AppKata checked)
- reach the network, see the user's other processes, and call any service on the session D-Bus

## Approach

In brief (kept current as findings land; detail in the rest of this document):

- **bubblewrap (`bwrap`) per app**, unprivileged — no root, daemon or setuid helper of AppKata's own.
- **Three profiles, chosen per app:** Off, **Standard** (private home, install files read-only,
  filtered session bus, network, granted folders), **Strict** (a private home and nothing else — no
  folders, network, sound, bus or services; a grant that would widen it is dropped, not kept beside
  it). Grants (folders, network, sound, devices, capabilities) adjust Standard per app. Some folders
  are **never shared**, whoever asks: the home and anything above it, AppKata's own folders, the
  user's keys, and every place a program could start again from at the next login.
- **A generated launcher per app** that `launch()`, the desktop entry and the command link point at,
  so starting from the menu is sandboxed too. Its text is the enforcement: it is regenerated on
  every install, update and sandbox change, and at AppKata's start whenever it is not the text
  AppKata would write today, so a launcher fix reaches every installed app.
- **Permissions come from signed `AppKata.md` reviews** (new `Sandbox*` lines), overridable per app;
  reviews never auto-change grants — a new version keeps the user's grants and raises a review badge,
  which stands until the user acts on that suggestion.
- **AppImages are unpacked lazily, on the first sandboxed launch, inside a sandbox** (an AppImage
  can't mount itself in bwrap — no FUSE); ≈2.5–3.5× the disk space, paid only by apps that run
  sandboxed.
- **⚠ One privileged step where the kernel restricts unprivileged user namespaces (found in round 2):**
  there bwrap won't start until an AppArmor profile grants the carve-out. AppKata installs it **on first need**, behind a single **pkexec** prompt (the one place
  sandboxing needs root; one-time, persists across reboots), re-engageable from Settings → Sandbox.
  If declined, the app runs **Off with a warning** (no false-comfort fallback). A system without the
  restriction, or with a bwrap profile of its own (17.10.2), needs none of this; which of the tested
  systems are which, [`testing.md`](testing.md) says ("What each environment boots with").
- **Desktop-integration holes have specific fixes:** the session bus is filtered to the safe portal
  interfaces, and the portals see the app as a *host* caller (xdg-desktop-portal 1.18+ refuses any
  other non-Flatpak identity), so the file chooser portal is not used — the app's own dialog shows
  exactly what the sandbox sees; audio goes through the session manager as a sandboxed client (not
  the raw socket); files given to an app ("Open with", a drop, a command-line argument) are handed
  over through the document portal from the host side; and links and files it opens go to the host
  through the OpenURI portal, with the host's desktop entries hidden from the sandbox so GLib asks
  the portal rather than starting the host's browser inside. Screen capture, clipboard and input
  injection are **not** closed in v1:
  on X11 that's unfixable, and on wlroots Wayland the fix (the security-context protocol) is **deferred
  past v1** — so AppKata **warns** on both, and only GNOME/mutter-style Wayland is clear (see
  [Limits](#limits)).

### bubblewrap

Run each sandboxed app inside **bubblewrap** (`bwrap`): unprivileged, the tool Flatpak itself is
built on, and already installed on Mint 21.3 (0.6.1) and 22.1 (0.9.0) together with
**xdg-dbus-proxy**. Neither needs root, a daemon or a setuid helper of AppKata's own.

**One privileged requirement, and only where the kernel restricts unprivileged user namespaces.**
There bwrap won't run at all until an AppArmor profile grants the carve-out (round 2 confirmed the
block and the fix, on Ubuntu 24.04; which tested systems restrict, [`testing.md`](testing.md) says). This is the one place sandboxing needs root, so it's worth being
precise about when and how (all verified in the VM, [Experiment](#experiment)):

- **Done on first need, not at AppKata's own install.** AppKata installs as a per-user AppImage
  without admin (requirement 1.6, 2.11), so it has no root at its own install time anyway. Instead,
  the launcher detects that bwrap can't create a user namespace and AppKata offers to set it up the
  first time a sandbox is actually needed, with a clear explanation. Detection is cheap: try a
  no-op `bwrap --unshare-user` once and cache the result.
- **It needs root once.** An unprivileged user cannot do any of it — writing `/etc/apparmor.d/`,
  `apparmor_parser`, and the `kernel.apparmor_restrict_unprivileged_userns` sysctl are all denied
  (confirmed). So AppKata asks for admin rights once, through **pkexec** — the same mechanism it
  already uses for `.deb`/`.rpm` installs (`_apply`/PackageKit, requirement 16) — to write
  `/etc/apparmor.d/appkata-sandbox` and load it (`apparmor_parser -r`), the way Flatpak, Chrome,
  Obsidian and Signal ship theirs. The profile that worked in the VM, attached to the system
  `/usr/bin/bwrap` (present on Mint 22):
  ```
  abi <abi/4.0>,
  include <tunables/global>
  profile appkata-sandbox /usr/bin/bwrap flags=(unconfined) {
    userns,
    include if exists <local/appkata-sandbox>
  }
  ```
  If AppKata ships its own bwrap at a non-standard path instead, the profile's path must match it.
- **The cost is one-time and permanent.** `apparmor.service` is enabled and reloads
  `/etc/apparmor.d/` at every boot, so the profile survives reboots and upgrades; no prompt again.
- **What it costs (requirement 17.10.1).** The carve-out applies to `/usr/bin/bwrap` itself, not to
  AppKata: any program the user runs can again get a user namespace by way of bwrap — the kernel attack
  surface Ubuntu's restriction exists to shrink. Ubuntu's own `flatpak` and Chrome profiles have the same
  shape, but for their own programs. Ubuntu's later `bwrap-userns-restrict` profile instead strips
  capabilities from bwrap's children; that breaks the Chromium/Electron sandbox nested inside bwrap
  (round 2), so it's deferred, and the setup says plainly what it enables.
- **If declined, the app runs Off with a warning** (decision 6). There is deliberately no
  Landlock-only fallback: Landlock protects files but can't mediate the session D-Bus socket, so a
  Landlock-only app could still reach `systemd` and escape — offering it as "protection" would
  mislead. Landlock stays on the roadmap only as a defense-in-depth layer *inside* bwrap. The status
  and re-engage control live in Settings → Sandbox and a per-app indicator ([Prompts and
  recovery](#prompts-and-recovery)).

Mint 21.3 (bwrap 0.6.1) has no such restriction: no profile, no prompt.

**Ubuntu 25.04 and later bring their own profile** (`/etc/apparmor.d/bwrap-userns-restrict`, in 25.04's
`apparmor` 4.1 and 26.04 LTS's 5.0; requirement 17.10.2, review 2 F2). It is the capability-stripping
design above: bwrap may create a user namespace, and everything it runs is stacked into `unpriv_bwrap`,
which denies capabilities. Shown in a 26.04 KVM guest:
- the sandbox works with no setup (the probe passes), but nothing inside it can make a user
  namespace of its own, so Chromium's and Electron's own sandbox can't start;
- AppKata's profile loaded *beside* Ubuntu's leaves bwrap with no user namespace for anyone, live and
  after a reboot, which is the state a 24.04 machine where the setup ran reaches when it upgrades.

So AppKata never installs its profile beside the system's, a setup whose check fails for the user is
undone in the same pkexec run, and Settings offers **Repair…** (remove AppKata's) when it finds both.
There the launcher starts an app that brings Chromium's sandbox with `--no-sandbox`: still inside
AppKata's sandbox, without its inner one (the owner's decision; App Detail says so). A zypak-style
spawner that would restore the inner sandbox is a later item (17.18).

Alternatives considered:

| Option | Verdict |
|---|---|
| **bubblewrap** + xdg-dbus-proxy | **Chosen.** Namespaces for files, processes, network and IPC; tested below |
| Firejail | No: a setuid-root binary with a history of privilege-escalation bugs; adds attack surface to protect against apps |
| Landlock | Later, as a defense-in-depth layer *inside* bwrap only — not a standalone fallback (decision 6): it can't mediate the session D-Bus socket, so alone it can't stop a systemd-based escape. File and (6.7+) TCP rules, no namespaces or root. Round 2 confirmed it's present and usable unprivileged on Ubuntu 24.04's 6.8 kernel (ABI 4) |
| systemd-run `--user` sandbox properties | No: most `Protect*=` options need privileges or `PrivateUsers=` in the user manager, and differ between systemd versions |
| A separate Unix user, a VM, distrobox | Strong but awkward for desktop apps; a "really don't trust this" suggestion in the docs, not a feature |

### Profiles

Three levels, chosen per app; the defaults and their precedence are set in [Decisions](#decisions).

| Level | Home | Install folders | Network | Session D-Bus | Display, sound, GPU |
|---|---|---|---|---|---|
| **Off** | The real one | Writable | Yes | Full | Yes |
| **Standard** | Private, plus granted folders | Read-only | Yes | Filtered (portals only) | Yes |
| **Strict** | Private only | Read-only | No | None | Yes |

**Grants** adjust Standard per app: a folder (`~/Documents`, `~/Pictures`, any path; read-only or
read-write), network on or off, sound (play, record), the camera, X11 on a Wayland session, a
writable app folder (for apps that update themselves or keep their settings beside the program),
and the desktop-services capabilities (notifications, inhibit, tray, media keys, secrets). At
Strict the table is the whole story: a folder, network, sound, service or writable app folder
given to a Strict set is dropped when the set is read, so the launcher, the summary chips and the
review badge all see the same thing. The real home is never shared, not even read-only, and
neither is anything above it, AppKata's own folders, `~/.ssh`, `~/.gnupg`, the session's runtime
folder, or the places a program could start again from at the next login (autostart, systemd
units, `~/.local/bin`, the shell's startup files, the desktop's extension and script folders, …;
the full list is `_protected_roots()` and requirement 17.3.1) — whoever asks, a review line or the
folder picker; such a grant is refused by name in the launcher, the chips and the dialog.

### What every sandboxed launch does

The Standard profile, in outline (the exact text AppKata writes is kept byte for byte in
`tests/data/launchers/` for six grant sets, and explained part by part in `local-proxy-test-plan.md`):

```sh
bwrap \
  --ro-bind /usr /usr --symlink usr/lib /lib --symlink usr/lib64 /lib64 \
  --symlink usr/bin /bin --symlink usr/sbin /sbin --ro-bind /etc /etc \
  --ro-bind-try /var/cache/fontconfig /var/cache/fontconfig \
  --proc /proc --dev /dev --dev-bind-try /dev/dri /dev/dri --tmpfs /tmp --dir "$XDG_RUNTIME_DIR" \
  --bind-try "$XDG_RUNTIME_DIR/doc/by-app/io.appkata.<app>" "$XDG_RUNTIME_DIR/doc" \  # handed-over files
  --ro-bind-try /sys/class /sys/class ... \                                          # GPU identification
  --bind ~/.local/share/appkata/sandboxes/<app> "$HOME" \
  --ro-bind ~/bin/apps/<app>/<version> ~/bin/apps/<app>/<version> \
  --ro-bind-try ~/.themes ~/.themes ... ~/.local/share/fonts ... \                   # looks native
  --bind-try "$HOME/Documents" "$HOME/Documents" \                                   # a grant
  --ro-bind-try "$XDG_RUNTIME_DIR/pipewire-0" ... \                                  # a sound grant
  --ro-bind <sandboxes>/.identity/<app> /.flatpak-info \                             # the identity
  --bind "$XDG_RUNTIME_DIR/appkata/bus-<app>.$$" "$XDG_RUNTIME_DIR/bus" \            # xdg-dbus-proxy
  --ro-bind-try <sandboxes>/.identity/bin /run/appkata \                             # the xdg-open shim
  --unshare-all --share-net --die-with-parent --seccomp 3 \
  --clearenv --setenv HOME "$HOME" --setenv PATH /run/appkata:/usr/bin:... \
  --setenv DBUS_SESSION_BUS_ADDRESS "unix:path=$XDG_RUNTIME_DIR/bus" \
  --tmpfs /usr/share/applications --ro-bind "$XDG_RUNTIME_DIR/wayland-0" ... \       # decided at run time
  -- ~/bin/apps/<app>/<version>/<exec> "$@"
```

1. **The OS read-only.** `/usr` and `/etc` are bound read-only; nothing else of the host's
   filesystem is visible. The host's desktop entries (`/usr/share/applications`,
   `/usr/local/share/applications`) are hidden under an empty tmpfs, as a Flatpak runtime has none:
   GLib opens a link or file with the first handler it finds and asks the portal only when there is
   none, so with the host's entries in view a GTK app started the host's browser *inside* the
   sandbox (see [Limits](#limits)).
2. **A private home.** `~/.local/share/appkata/sandboxes/<app>/` is mounted over `$HOME`. The app
   keeps its settings there (it writes `~/.config/<app>` as usual and lands in its own folder).
   Writes to `~/.bashrc`, autostart or systemd units also land there, where nothing reads them.
   Uninstalling offers to remove this folder, like any app data (requirement 4.5). **So apps look
   native, the host's `~/.themes`, `~/.icons`, `~/.fonts`, `~/.config/fontconfig` and
   `~/.local/share/{fonts,icons,themes}` are bound read-only** — without this a private home strips
   the user's theme and fonts and the app looks wrong. Every mount destination under `$HOME` lies
   inside this app-writable folder, and bwrap resolves a destination through whatever is there, so
   before mounting the launcher removes any symlink the app has left at such a path (otherwise bwrap
   follows it on the host side and creates files or folders at its target as the user). The app's
   identity marker lives *outside* the home for the same reason.
3. **The app's own files read-only.** Only its current version folder is bound, read-only; other
   apps in `~/bin/apps/` aren't visible at all. A **writable app folder** grant binds it read-write
   for apps that keep settings beside the program or self-update — close to Off for tampering.
4. **A clean environment.** `--clearenv`, then an allow-list: `HOME`, `PATH` (with AppKata's shim
   folder first, for its portal-aware `xdg-open`), `LANG`/`LC_*`, `DISPLAY` or `WAYLAND_DISPLAY`,
   `XDG_RUNTIME_DIR`, `XDG_SESSION_TYPE`, `XDG_CURRENT_DESKTOP`, theme variables (`GTK_THEME`,
   `QT_QPA_PLATFORMTHEME`), `DBUS_SESSION_BUS_ADDRESS` (the proxy), and for AppImages
   `APPDIR`/`APPIMAGE`/`ARGV0`, and `GDK_DEBUG=no-portals` (GTK4's file dialog is its own, round six R6-4). Tokens in the session stay out. `GTK_USE_PORTAL` is deliberately not
   set (point 6).
5. **Own process, IPC and network namespaces** (`--unshare-all`), with the network shared back
   unless the profile says no. A small seccomp filter refuses the `TIOCSTI`/`TIOCLINUX` ioctls — the
   old trick of typing commands into the terminal that started it — without `--new-session`, which
   cut terminal tools off their tty; `--new-session` remains only on a machine the filter is not
   built for. `--die-with-parent` ties the sandbox to bwrap's parent, so bwrap is always the
   launcher's own child, at every level: the launcher waits as long as the app runs, and the app
   outlives whatever started the launcher (AppKata, the desktop shell, a script).
6. **Filtered D-Bus, plus the app's own name and its capabilities.** `xdg-dbus-proxy --filter` with
   per-interface `--call` rules on `org.freedesktop.portal.Desktop` gives the app the portals that are
   safe for a host caller (open-URI, settings, print, email, the network and memory monitors) and
   nothing else by default — the notification and inhibit portals come with those capabilities, so
   the summary's chips are the truth — not the file chooser (the app's own dialog shows
   what the sandbox sees), not the `version` properties (what Chromium/Electron reads before
   switching to the portal chooser; GTK4 asks the chooser outright and falls back cleanly when
   refused; GTK3 and Qt up to 6.4 never ask — shown with real apps, `scripts/test-sandbox.sh
   filedialogs` and `consumers`), and not the portals that would trust a host caller with the host
   (autostart, launcher installation, camera, screen, documents). Without the filter, an app can ask
   `org.freedesktop.systemd1` to start any program outside the sandbox, so an unfiltered bus is the
   same as no sandbox. The system bus
   isn't bound. On top of that the launcher lets the app **own its own name** (`--own=io.appkata.<app>`
   — so single-instance and "open a second file in the running window" work) and grants the small
   **desktop-services capabilities** its template allows (tray via `StatusNotifierItem`, media keys via
   MPRIS, screensaver inhibit, `org.freedesktop.secrets`, notifications) with the matching `--own`/
   `--talk` — see [Templates](#templates).
7. **App identity (load-bearing).** The launcher presents each sandboxed app a stable id,
   `io.appkata.<app>`, via a synthesized `.flatpak-info` bound in the app's root — not the bus
   proxy's. **PipeWire/WirePlumber** take the app for a sandboxed client from it (so recording can be
   restricted, not handed the raw socket), GLib takes its portal use and network availability from
   it, and the Wayland **security-context** will use it too when that lands (deferred). The portals do
   *not* see it: xdg-desktop-portal 1.18+ refuses a marked caller that is not a running Flatpak, so the
   proxy carries no marker and the portals answer the app as a host caller, on the narrowed set of
   interfaces above (requirement 17.6.1). The id is also the document portal's per-app folder, which
   AppKata exports file arguments into from the host side. (It leans on Flatpak's convention; revisit
   if a non-Flatpak standard matures.)
8. **Files the app is given.** A path or `file://` URI among the app's arguments — the menu entry's
   `%U`, "Open with", a drop, `tool ~/notes.txt` — that lies outside the granted folders is exported
   through the document portal *from the host side* (`Documents.Add` + `GrantPermissions` for the
   app's id, what the chooser portal does for a picked file) and the argument becomes the path the
   app sees under `$XDG_RUNTIME_DIR/doc`, with write permission when the user has it. The app sees
   that file, not its folder. Strict apps have no bus and so no hand-over. Links and files the app
   wants *opened on the host* go the other way, through the OpenURI portal: GLib and GTK apps on
   their own (the host's desktop entries are hidden so they find no handler to run inside), Qt by
   calling it when it sees the marker, Electron and the rest through AppKata's `xdg-open` first on
   the PATH. A file in the private home can't be opened on the host that way (the portal sees the
   path it has inside, `$HOME/<x>`); one in a granted folder or the hand-over view can.
9. **Display, sound, GPU, camera.** The Wayland socket when the session is Wayland, else the X11
   socket with `XAUTHORITY` bound read-only at its own path; on Wayland the X11 socket *too* when
   the app has the X11 device grant (on by default, for apps that can't use Wayland). PipeWire and
   PulseAudio sockets with a sound grant; `/dev/dri` and the `/sys` paths that identify it always;
   `/dev/video*` with the camera grant. X11 is a known hole (see [Limits](#limits)). Proprietary
   NVIDIA needs `/dev/nvidia*` beyond `/dev/dri` — a known later complication, not solved here.
10. **Its own output.** Started from AppKata, the launcher's stderr is the app's log
    (`logs/apps/<id>.log`) and a failure before the program runs, or within ten seconds of it, is
    reported with a toast; started from the app menu (`--appkata-menu`) it appends to the same log
    itself; started from a terminal it leaves stderr where the caller put it.

### The Landlock layer

Landlock is a second, independent lock applied by the launcher *inside* bwrap — never instead of it
(decision 6). bwrap does the isolating (namespaces, private home, read-only binds, the D-Bus proxy);
Landlock, enforced by a different kernel subsystem, still holds if the bwrap construction has a bug.
It only ever *adds* restriction — it can't grant access or remap paths — so it can't stand in for the
mount/user namespaces, and it can't mediate the session D-Bus socket (which is why it's a layer, not
a fallback). What it adds on top of a working bwrap sandbox:

1. **Defense-in-depth against a launcher bug** — the main reason. AppKata builds the bwrap command
   from each app's profile and grants; a mistake there (a too-broad bind, a symlink that escapes a
   read-only tree, a missed path) silently over-shares. A Landlock policy derived from the *same*
   grant set but enforced by the LSM hooks would still deny it. Two independent derivations of "what
   this app may touch" would both have to be wrong to leak; it also covers a class of namespace/mount
   kernel bugs.
2. **Execute-deny on writable areas** — a rule bind mounts can't express: allow write but **deny
   execute** on the app's private home and any writable-app-folder grant, so it can't drop a binary
   into its own data and run it (closes some persistence/exploit chains). This is the "Block running
   programs it writes" control.
3. **Irrevocable inheritance** — the restriction is inherited by every child, so helpers and plugins
   stay confined; nothing can re-exec its way out.
4. **Per-port TCP (kernel ≥ 6.7, ABI 4)** — where a profile shares the network, restrict connect/bind
   to specific ports (e.g. 443 only), finer than bwrap's all-or-nothing `--unshare-net`.

**Kernel-dependent, so opportunistic.** Ubuntu 24.04's 6.8 kernel is ABI 4 (file rules + TCP, confirmed in
round 2; this said Mint 22's, corrected 2026-10-24, R3-37: Mint 22.3 boots 6.14); Mint 21.3's ~5.15 is ABI 1 (file rules only, no per-port TCP). The launcher probes the ABI
and applies what's supported, skipping the rest. This is why Landlock is a later step, not first
release. In the UI it lives under the **Advanced** group of the Customize section, each control marked
as an extra hardening layer.

### Where AppKata changes

| Place | Today | Sandboxed |
|---|---|---|
| `launch()` | `Popen([rec["exec"]])` | Runs the app's launcher |
| `_desktop_entry()` | `Exec="<exec>" %U` | `Exec="<launcher>" --appkata-menu %U` (the word makes the launcher keep its stderr in `logs/apps/<id>.log`) |
| Command link (`Portable.command_dir`) | Symlink to the program | Symlink to the launcher |
| Stable name (`<App>.AppImage`, `current`) | Symlink to the version | Kept for humans, but **anything that runs it directly bypasses the sandbox** (a file manager double-click, AppImageLauncher, appimaged); the desktop entry and command link stop pointing at it |
| `rec["exec"]` | The program | The launcher; `rec["launcher"]` its path, `rec["sandbox"]` the grants baked into it |

**The launcher** is a script AppKata writes per app, `~/bin/apps/<app>/run`. It is regenerated on
every install, update and sandbox change, and — because its text *is* the enforcement — at
AppKata's start for any app whose launcher is not the text AppKata would write today (one a
previous AppKata wrote before a launcher fix, or a hand-edited one), so a fix reaches every
installed app at the next start rather than at its next update. It decides the CLI tool's working
directory, hands file arguments over, sweeps the private home for planted links, starts
`xdg-dbus-proxy` for this launch and waits for its socket, runs `bwrap` as its own child, and
stops the proxy when the app exits. A generated script and not `appkata run <app>`: AppKata is a
~110 MB AppImage, and mounting it plus starting Python on every app launch costs a second or two.

Writing the launcher is AppKata's job only; the script contains no policy of its own (its only
run-time decisions are about the host it is started on: the display, DNS, the working directory,
the arguments), so its text can be shown in the App Detail panel ("Show the launch command"), the
Audit records a hash of it with the set it was written for (review 2, F11), and the goldens in `tests/data/launchers/` make any change to it a reviewed diff.

### Where the permissions come from

AppImages and tarballs don't declare what they need, so AppKata needs a source:

1. **Reviews.** `AppKata.md`'s `## <App>::Settings` (10.3.1) gains platform lines. Usually just a
   **template** name plus any overrides (see [Templates](#templates)):
   ```
   - Sandbox (linux): offline-editor
   - Sandbox folders (linux): +~/Zettlr
   ```
   or the full form where no template fits:
   ```
   - Sandbox (linux): standard
   - Sandbox folders (linux): ~/Documents, ~/Pictures:ro
   - Sandbox network (linux): yes
   ```
   Every other kind of grant has a line of its own, in the same `+`/`-` form: `Sandbox sound`,
   `Sandbox devices`, `Sandbox services` and `Sandbox app folder` (review 2, F9); saving a review
   writes the user's own sandbox as these lines, shown first with "Include my sandbox".
   A version's `::Settings` can change them from that version on, like Auto update today
   (`Zettlr[3.5.1]`). Several Trusts disagreeing: take the **most restrictive** template/level and the
   **intersection** of grants, so one careless reviewer can't open an app up.
2. **The user's choice** per app, asked in the install options (requirement 4.2) on the first
   install, saved with the other install options, and changeable from the App Detail panel or
   Install options; either applies at the app's next start. It always wins over reviews. A
   template the user changes is stored as that template plus the changes, so it keeps its name
   (review 2, F10); a choice the resolver reports as "custom" (a merged review set, a bespoke set)
   is stored as the grant set itself, never as a template name.
3. **A default template** (by app kind, [decision 1](#decisions)) for apps nobody has reviewed —
   the user's own default for the kind, from Settings → Sandbox.

**What a review may do on its own** (requirement 17.3.5, review 2 F8, the owner's decision):
- **Narrow freely.** A review picks a template, narrows access and grants ordinary folders.
- **Off is never applied by itself.** Where the merged reviews say Off, the reviewed baseline
  applies and the dialogs offer "Use theirs".
- **Secrets need the user.** Browser and mail profiles, other sandboxes' data, cloud and forge
  credentials, password stores and keyrings are refused when a review asks. The user's own picker
  may grant them, and the summary warns that the folder holds passwords or tokens.

Reviews never change grants on their own (decision 5). The grant set an app was installed with is
**pinned** in its settings; a new version installs normally and keeps it, and if the reviews now
suggest **more or less** access the app gets a standing **review badge** ("Reviewers suggest a
sandbox change — Review… / Keep mine"), and the App Detail banner explains it may be partly
non-functional until reviewed. The badge stands until the user acts on *that* suggestion — adopts it
("Use theirs"), keeps their grants, or saves a choice of their own knowing it — and a later,
different suggestion raises it again. Access is never widened silently. With "Follow reviewers'
suggestions" off (Settings → Sandbox) reviews play no part at all: the user's default for the kind
applies and no badge shows, though the dialog still says what the reviewers suggest.

Every change of a sandbox level or grant is an audit event (requirement 13).

## Templates

A **template** is a named preset of (level + grants + desktop-services capabilities + Landlock extras)
— nothing new under the hood; it resolves to the controls above. Apps cluster into a handful of
archetypes by what they legitimately need, so a template is the usual way a reviewer or user picks a
sandbox, with per-app tweaks on top. It keeps reviews simple (`Sandbox: offline-editor` instead of a
list of toggles), gives users one meaningful choice instead of a wall of switches, and reads better in
the audit.

Eight built-in templates for the first release. The **Services** column is the capabilities dimension
(point 6 of the launch recipe): the fiddly, non-obvious D-Bus/portal pieces an app needs to behave
normally, which cluster hard by archetype — exactly the knowledge a reviewer has and a user doesn't,
so baking them into the built-ins is where templates earn their keep:

| Template | Level | Files | Network | Sound | Devices | Services | Landlock |
|---|---|---|---|---|---|---|---|
| **Strict** | Strict | none | no | no | X11 only | — | execute-deny |
| **Standard** | Standard | none (files given to it are handed over, 17.6.2) | yes | — | X11 | notifications | execute-deny |
| **Offline editor** | Standard | a folder you pick (rw): Documents or Pictures in one click | no | no | X11 | — | execute-deny |
| **Online app** | Standard | none (files given to it are handed over, 17.6.2) | yes | play | X11 | notifications | execute-deny |
| **Messenger / calls** | Standard | none | yes | play + record | camera, X11 | tray, notifications, inhibit | execute-deny |
| **Media player** | Standard | a media folder you pick (read-only): Music or Videos in one click | optional | play | X11 | MPRIS media keys, inhibit | execute-deny |
| **Developer tool** | Standard | a projects folder you pick (rw) | yes | — | X11 | — | **execute allowed** + terminal |
| **Command-line tool** | Standard | the directory it's run in (rw) | optional | — | X11 | — | execute allowed |

The Developer tool row shows why a named preset beats inlining: it's the one case where execute-deny
must be **off** (the app legitimately runs code), so bundling that stops a reviewer from thoughtlessly
breaking it. The Services column is the other half: nobody expects their messenger's tray icon to need
`StatusNotifierItem`, and every messenger needs the same bundle — so it belongs in the template.

The **CLI tool** template is special: its one folder is **the directory the tool is run in**, bound
read-write by the launcher at each invocation (not a fixed path). Validated in round 3 — a tool can
read and write files in the current directory and spawn subprocesses, while `~/.ssh`, browser data,
other apps and autostart stay hidden. This is the default for command-line tools (replacing the
earlier "Off"). The directory is *not* shared when it is the home folder (where terminals start),
anything above it, or one of the never-shared folders; the tool then runs in its private home and
says why on stderr. A file the tool is named on the command line is handed over whatever directory
it lies in (point 8 of the launch recipe), so `tool ~/notes.txt` works from anywhere; what it can't
see is a *directory* elsewhere, so a tool that routinely works on whole trees outside the current
one can be given a folder grant or set to Off.

**Thin and overridable, not a straitjacket.** A template is a starting point; explicit lines override
it. `Sandbox: offline-editor` + `Sandbox folders: +~/Zettlr` means "the editor preset, plus one more
folder"; a `+`/`-` prefix adds or removes from the template's set. The resolved result is what the
launcher enforces; the UI shows "Offline editor · customized" with a **Reset to template** affordance
once anything differs.

### Resolving several sources

A template is never merged as an opaque name — it is resolved to a **grant set** first, then combined,
which makes the multi-Trust case well-defined (validated in `scripts/sandbox/merge.py`, round 3):

1. **Each review → a grant set:** resolve its template, then apply its `+`/`-` overrides.
2. **Across Trusts → the least-privilege combination:** strictest level; a folder only if *all* grant
   it (read-write only if all do); network/sound/devices/capabilities = the **intersection**; per-port
   lists intersected (no limit means "all"); execute-deny if **any** Trust denies. So one careless
   reviewer can't widen an app, and two Trusts naming *different* templates (e.g. Messenger vs Offline
   editor) resolve cleanly to "only what both allow".
3. **The user's own choice wins** over the merged reviews; an app **no** Trust has reviewed falls to
   the default template (by app kind, [decision 1](#decisions)).

### Built-in, personal and reviewer-defined

- **Built-in** (v1). AppKata ships the seven above; reviewers reference a name plus overrides.
- **Personal templates** (likely later; cheap, no Trust involvement). A user saves a customized app's
  settings as a named, reusable template of their own — via **"Save as template…"** in the Customize
  dialog, or **"New template…"** in Settings → Sandbox. Their distinct value is that they can name
  **personal resources** a reviewer fundamentally can't know (`~/Projects/clientX`, a specific vault
  folder): shared settings describe the app in the abstract, personal templates bind it to *your*
  filesystem. Picking **Custom** in the dropdown (bespoke for one app, not saved) is the v1 story;
  saving a *named* personal template is the later addition.
- **Reviewer-defined templates** (deferred open question, leaning against). Trusts already transport a
  reviewer's settings, so sharing isn't the new part — the new part would be a signed **definition
  format** in the reviews repo, **name resolution + namespacing** (built-in names reserved; a Trust's
  names scoped so one can't redefine `strict`), and treating the definition as access-granting. A
  reviewer can already inline full per-app settings, so a custom shared template only buys DRY reuse
  across many apps in one Trust — modest value for that machinery. Good built-ins (with the Services
  bundles) plus inline overrides are expected to cover it, so this is recorded as a future item we
  lean against building, not a plan.

### How templates are presented

- **`AppKata.md`** — a `Sandbox: <template>` line plus optional `Sandbox folders/network/...`
  overrides (`X16` mockup). Named, diffable, signed with the rest of the review.
- **Install options** (`C11`) — a compact Sandbox card: a template dropdown, the live summary chips,
  and **Customize…**; the reviewer's suggestion is preselected.
- **App Detail → Sandbox** — the summary chips (the level, then the key grants), and **Change…**; the
  dialog names the template, "<template> · customized" when tweaked.
- **The Change dialog** (`A21`) — a **template dropdown + a plain-language summary and grant chips**
  that update live, then a collapsed **Customize** disclosure. (Not a wizard: it's a settings surface
  you return to.) Customize opens into grouped sections — **Files / Connections / Devices & media /
  Advanced** (`A25` shows Connections and Devices; Advanced holds the Landlock execute-deny). A full tabbed dialog is a fallback
  only if Customize grows too tall in practice.
- **Settings → Sandbox** — the default template for new apps (via the by-kind rules, decision 1) and a
  **Browse templates** list of the built-in set; the home of **"New template…"** when personal
  templates land.

## App categories (separate work)

Raised during sandbox design and recorded here, but it is **its own feature, not part of the
sandboxing work** — a Catalog change (touching req 3/12), kept out of this PR.

At Flathub scale AppKata wants freedesktop/AppStream **categories** (Game, Graphics, Network, Office…)
to group and filter the catalog. They are a third axis, distinct from both of AppKata's existing ideas
and from templates:

- **Tags** (AppKata's) = trust/nature: `foss`, `signed`, `tracking`, `spyware` — provenance signals,
  some driving warnings or a veto.
- **Categories** = function: where an app belongs in a menu, from its own AppStream/`.desktop`
  metadata. For browsing.
- **Templates** = sandbox profile: what the app may touch. For security.

Conflating any two loses something; in particular **a category is not a sandbox archetype.** The
mapping category→sandbox is many-to-many and lossy: *Graphics* holds both Krita (Offline editor) and a
screenshot tool (needs the screencast portal — the opposite); *Network* holds a torrent client, a
messenger and a browser, three different profiles. And categories come from the app's *own* (untrusted,
spoofable) metadata, so they must **never determine** the sandbox — only ever suggest.

**The one productive dovetail:** when AppKata has categories, use them as a **non-authoritative hint to
pick a better *suggested* template for an unreviewed app** (Development → Developer tool, Graphics →
Offline editor), always user-confirmed. That sharpens [decision 1](#decisions)'s "unreviewed" branch
from a blunt kind-based default to a smarter first guess. The sandbox plan only *consumes* categories
as this optional hint; it works fine without them.

Note the deliberate naming overlap: template names (*Media player*, *Developer tool*) resemble
categories because it's intuitive, but they are sandbox profiles — an app's category never forces its
template.

## AppImage

Experiment: Neovim 0.11 (CLI), AppKata 0.1.0 (Qt 6), Obsidian 1.14.4 (Electron).

**AppImages can't mount themselves inside bwrap.** Running the `.AppImage` file in the sandbox
fails: `Error: No suitable fusermount binary found ... Cannot mount AppImage`. FUSE needs the
setuid `fusermount`, and bwrap (rightly) sets `no_new_privs`. Opening `/dev/fuse` and FUSE to
the app would hand it a way to mount things. So (decision 2): **at Off, run the `.AppImage` file
directly** (it self-mounts via FUSE, outside any sandbox); **at Standard/Strict, extract and run
`AppRun`** from the unpacked folder. Running `AppRun` worked for all three test apps unchanged.

1. **The `.AppImage` is canonical; the extracted folder is a derived cache** (decision 2). `_place()`
   keeps the `.AppImage` file (its checksum, rollback, "run outside AppKata", and Off). The extracted
   directory is built **lazily** on the first sandboxed launch, rebuilt if missing, and may be dropped
   when the app is switched to Off.
2. **Unpack in a sandbox too.** `./X.AppImage --appimage-extract` runs the AppImage's own
   *runtime*, an ELF the publisher wrote: untrusted code. It runs inside a Strict bwrap that can
   write only a staging folder (the same machinery, no new dependency; the alternative — finding
   the squashfs offset in the ELF header and unpacking with `unsquashfs` or a Python reader — was
   not needed). Only a real directory `squashfs-root` is accepted (a symlink the runtime left would
   make the launcher bind whatever it points at); the result is stamped with the `.AppImage`'s
   size, mtime and inode so a file replaced in place is extracted again; simultaneous first
   launches serialize on a lock. No timeout or size limit is applied.
3. **Layout.** Extracted into `~/bin/apps/<app>/<version>.extracted/` beside the kept `.AppImage`.
4. **Disk space, only when sandboxed.** Because Off runs the `.AppImage` directly, the extraction
   cost is paid only by apps running Standard/Strict. Unpacked is 2.5 to 3.5 times the AppImage:
   Neovim 11 → 40 MB, Obsidian 133 → 343 MB, AppKata 108 → 358 MB; with two kept versions
   (`Portable.keep`) an Electron app at Standard is about 1 GB on top of the `.AppImage`s. Show the
   size in the install options when sandboxing is on. A later option: mount the squashfs with
   `squashfuse -o offset=N` **outside** the sandbox (AppKata, not the app, owns the mount) and bind
   the mount point read-only; no extra disk, but a FUSE mount per running app and a dependency.
5. **Environment.** `AppRun` scripts expect `APPDIR` (the unpacked folder), and some apps read
   `APPIMAGE` (the file's path, for desktop integration or updates) and `ARGV0`. The launcher sets
   all three; `APPIMAGE` points at the kept file, which is bound read-only so the path resolves.
6. **Electron and Chromium apps.** Their own sandbox works inside bwrap: bwrap allows nested user
   namespaces, and Obsidian started without `--no-sandbox` and without errors about its sandbox.
   AppKata must never chmod `chrome-sandbox` setuid (it doesn't today), and must not pass
   `--disable-userns` to bwrap, or Chromium falls back to no sandbox at all.
7. **Apps that update themselves** (requirement 4.10, AppImageUpdate/zsync, electron-updater)
   replace their own file, which the read-only folder blocks, and an AppImage's own `.AppImage` is
   bound read-only whatever the grants. So while such an app runs sandboxed, AppKata updates it as
   if it didn't update itself (4.10.5, 17.12; review 2, F3, the owner's decision): Update, Update
   all, version folders from its next update, and App Detail says why. Switched Off, it updates
   itself again. An earlier draft named a "Disable the app's own updater" install option; 4.10.3 rules
   that out (AppKata can't switch an app's updater off) and it was never built, so until this
   nobody updated a sandboxed self-updating app. Still owed on a real desktop: whether a blocked
   updater makes an app degrade gracefully or crash.
8. **Desktop integration tools** (AppImageLauncher, appimaged) register AppImages they find and
   run them unsandboxed. AppKata can't stop that; the Limits say so. Detecting them
   (`~/.config/appimagelauncher.cfg`, a running `appimaged`) and warning once is a later nicety,
   not built.

## Portable (tarballs)

Tarballs are already unpacked into `~/bin/apps/<app>/<version>/` (`_place()`), with
`tarfile.extractall(filter="data")` so paths can't escape. They need nothing like the AppImage
unpacking; the launcher runs `rec["current"]["exec"]` from the version folder. What's different:

1. **Apps that write beside themselves.** Some portable apps keep their settings or a `data/`
   folder next to the program, or write logs there; the read-only folder breaks them. The
   "writable app folder" grant binds the version folder read-write; the app can then change its
   own code, so that grant is close to Off for tampering (not for secrets). A reviewer's settings
   line can set it up front; detecting it from a failed first run (`EROFS` in the app's output) is
   a later nicety. bwrap 0.10's `--overlay` could give a private writable layer instead, but Mint
   22.1 has 0.9.
2. **Wrong executable.** `_find_executable()` picks the program by name. A sandboxed launch of a
   helper (an updater, `chrome-sandbox`) instead of the app shows up as "the app didn't open", the
   same as today; the launcher's output and bwrap's exit status go to the app's log, and a failure
   at start is reported with a toast (launch recipe, point 10).
3. **Command-line tools — the CLI tool template.** A CLI tool reached through a command link
   (`Portable.command_dir`) is useless if it can't see the directory it's run in, but it doesn't need
   the rest of the home. The launcher binds **just the current working directory** (rw) at each
   invocation and nothing else — unless that directory is the home, above it, or a never-shared
   folder, in which case the tool runs in its private home and says so; round 3 confirmed a tool can
   then read/write files there and spawn subprocesses while `~/.ssh`, browser data, other apps and
   autostart stay hidden. This is the default for CLI tools (not Off). A file named on the command
   line is handed over from wherever it is; a *directory* elsewhere isn't visible, so a tool that
   works on trees outside the current one can take a folder grant or Off. Strict binds nothing.
4. **Bundled libraries and `/usr`.** Tarballs often expect host libraries (Obsidian needed
   `libnspr4`, `libnss3`, GTK in the minimal container). `/usr` is bound read-only, so whatever the
   host has, the app has; no difference from today.
5. **Electron tarballs** behave as in AppImage point 5.

## Screens

Mockups (`screenshots/src/render.js`, in `screenshots/mocks/`); see [`screenshots/README.md`](../screenshots/README.md). Each name links to its dark mockup:

| Screen | What it adds |
|---|---|
| [`C11-install-sandbox`](../screenshots/mocks/dark/C11-install-sandbox.png) | Install options: a Sandbox card with the template dropdown, the live summary, Customize…, and the disk cost of unpacking |
| [`A20-apps-detail-sandbox`](../screenshots/mocks/dark/A20-apps-detail-sandbox.png) | Apps rows and App Detail: the sandbox level, the Sandboxed chip, the Sandbox section, the X11 caveat |
| [`A21-sandbox-dialog`](../screenshots/mocks/dark/A21-sandbox-dialog.png) | The per-app Sandbox dialog: template dropdown, live summary chips, "customized / Reset to template", collapsed Customize, home folder |
| [`A25-sandbox-advanced`](../screenshots/mocks/dark/A25-sandbox-advanced.png) | Customize expanded, showing Connections (Network, per-port Landlock, portals), Devices & media and the start of Services; the Advanced group (execute-deny Landlock) is below the fold |
| [`A22-update-review-badge`](../screenshots/mocks/dark/A22-update-review-badge.png) | A new version kept the user's grants; a standing review badge asks them to review the suggested change (decision 5) |
| [`A23-confirm-uninstall-sandbox`](../screenshots/mocks/dark/A23-confirm-uninstall-sandbox.png) | Uninstall offers to delete the sandbox home folder |
| [`A24-sandbox-setup-needed`](../screenshots/mocks/dark/A24-sandbox-setup-needed.png) | On Ubuntu 24.04 with the setup declined: the app runs Off with a standing "needs one-time system setup · Enable…" indicator (decision 6, recovery) |
| [`X15-settings-sandbox`](../screenshots/mocks/dark/X15-settings-sandbox.png) | Settings → Sandbox: the System-support status/Set-up row, defaults and their precedence, the review-badge and X11 warnings |
| [`X16-appkata-md-sandbox`](../screenshots/mocks/dark/X16-appkata-md-sandbox.png) | The `Sandbox*` lines in `AppKata.md` |
| [`U02-audit-sandbox`](../screenshots/mocks/dark/U02-audit-sandbox.png) | Audit entries for sandbox changes |

## Experiment

Three rounds, reproducible through `scripts/test-sandbox.sh <mode>` (Docker; the `apparmor` mode also
needs `/dev/kvm`) and the round-3 probes run directly in the session container. The probes live in
`scripts/sandbox/`:

| Mode / probe | What it does | Key scripts |
|---|---|---|
| `probe` | The hostile-app probe in Mint 21.3 and 22.1 containers (table below) | `probe.sh`, `probe.lua` |
| `gui` | AppKata (Qt) and Obsidian (Electron) on Xvfb/X11, screenshots | `gui.sh` |
| `session` | Round 2 display/sound/portals in a Mint 22.1 Wayland container (sway + mutter, PipeWire, portals) | `session.sh`, `lib.sh`, `display.sh`, `sound.sh`, `portals.sh`, `filechooser.sh`, `apps-wayland.sh`, `typebox.py` |
| `apparmor` | Round 2 AppArmor/userns in a real Ubuntu 24.04 VM under KVM | `vmtest.sh` |
| round 3 | De-risking: theme/font binds, D-Bus own-name/caps, write-beside-itself, the full launcher, portal identity, and the merge rule | `validate2.sh`, `validate-launcher.sh`, `validate-portal.sh`, `merge.py` |
| review | The file-chooser call through a generated launcher: showed xdg-desktop-portal 1.18+ refusing the marked caller (requirement 17.6.1, `docs/reviews/app-sandboxing-1.md` finding 0); since the decision it shows the proxy's own AccessDenied, the portal never asked | `validate-chooser.sh` |
| `filedialogs` | Which file dialog real GTK3, GTK4 and Qt 6 apps show behind a generated launcher, with the portal and its gtk backend on the bus, and which proxy denial makes it so (17.6.3; round four R4-5): their own, GTK4 held by the FileChooser denial, GTK3 and Qt 6.4 never asking | `filedialogs.py` |
| `consumers` | Real consumers behind generated launchers, with the real portal, its gtk backend, a stand-in notification daemon and the test link handler on the host: a GLib app's notification reaches the host daemon with the capability and nowhere without it (17.5.1, R3-6); a GTK3 app's link runs the host's handler on the host, never inside (17.6.3, R3-1); Chromium 154 shows its own GTK file dialog as generated, *no dialog* with only Properties allowed (it reads `version`, takes the portal road, is refused `OpenFile`), the portal's with FileChooser allowed too — the Properties denial is load-bearing for Chromium/Electron and for it alone (R4-5) | `consumers.py` |

`lib.sh` holds the `sbx` helper that builds the Standard/Strict bwrap command the tests exercise;
`session.sh` brings up the headless desktop session. Output and screenshots land in
`build/sandbox-test/`.

**Environment gotchas**, on a host with an older kernel (4.18), no desktop and no GPU, where everything
runs in containers and VMs; recorded so a new session doesn't rediscover them:

- The host kernel (4.18) has **neither** the Ubuntu userns restriction **nor** Landlock, so both
  round-2 questions need Mint containers or the Ubuntu VM, not the host.
- Containers must run with `--security-opt seccomp=unconfined --security-opt systempaths=unconfined
  --security-opt apparmor=unconfined` (and `--device /dev/fuse --cap-add SYS_ADMIN` for the Wayland
  session) so bwrap can nest. On a real desktop none of that is needed.
- **Mint's own package servers (`packages.linuxmint.com`) are often unreachable here;** the session
  container pulls most packages from Ubuntu's `archive.ubuntu.com` (over HTTP — HTTPS to it is
  firewalled). `cloud-images.ubuntu.com` and `github.com` do work over HTTPS.
- The Ubuntu 24.04 VM uses the cloud image from `cloud-images.ubuntu.com` + cloud-init; `qemu` runs
  inside a container with `/dev/kvm` passed through. The cloud image has **polkit but not `pkexec`**
  installed (a real Mint desktop has both; AppKata already assumes pkexec for packages).
- Known harness limitation: `filechooser.sh`'s document-portal re-export step fails on nested-bwrap
  socket propagation (a test-rig issue, not a finding). The design-relevant half — a picked path is
  unreadable inside the private home without the portal — does pass.

`scripts/test-sandbox.sh probe` runs in Docker (Mint 21.3 and 22.1 images). The containers run with
seccomp, AppArmor and `/proc` masking opened so bwrap can nest; on a real desktop that isn't needed.

**Probe.** A user `kata` with a fake SSH key, Firefox cookies, `~/Documents/taxes.txt`,
`GITHUB_TOKEN` in the environment, another installed app, a second process (`secret-agent`) and a
session bus with another app's service (`org.example.Secrets`). Neovim's official AppImage,
installed in `~/bin/apps/nvim/0.11/` as AppKata lays it out, runs `scripts/sandbox/probe.lua`
(`nvim -l`), playing a hostile app. Afterwards the harness checks the **real** files. Same result
on Mint 21.3 (bwrap 0.6.1) and 22.1 (bwrap 0.9.0):

| Attempt | Today | Standard | Strict |
|---|---|---|---|
| Read `~/.ssh/id_ed25519` | Leaked | Blocked | Blocked |
| Read Firefox cookies | Leaked | Blocked | Blocked |
| Read `~/Documents/taxes.txt` | Leaked | Leaked (granted) | Blocked |
| Read `$GITHUB_TOKEN` | Leaked | Blocked | Blocked |
| Append to `~/.bashrc` | **Real file changed** | Private home only | Private home only |
| Autostart entry, systemd user unit, hijacked menu entry | **Real files changed** | Private home only | Private home only |
| Write into its own install folder | **Changed** | Blocked (read-only) | Blocked |
| Modify another installed app | **Changed** | Private home only | Private home only |
| TCP connect to github.com:443 | Yes | Yes | Blocked |
| See the user's other processes | Yes | Blocked | Blocked |
| Reach the session bus | Yes | The proxy only | No bus |
| Call `org.example.Secrets` | Yes | Blocked by the filter | Blocked |
| Its own settings | Work | Work (private home) | Work (private home) |
| Run the `.AppImage` file itself | Works | Fails: no FUSE | Fails: no FUSE |

**GUI apps** (Mint 22.1, Xvfb, Standard profile with X11, `/dev/dri` if present and the D-Bus
proxy): AppKata's own AppImage (Qt 6) and Obsidian 1.14.4 (Electron) both started, drew their
first window and were still running after 15 s; Obsidian's Chromium sandbox worked inside bwrap
and it reached GitHub for its update check. AppKata, started for the first time in its private
home, installed itself there (2.11.3), harmlessly.

### Round 2: display, sound, portals, Ubuntu 24.04

A second pass (`scripts/sandbox/` driven by `scripts/test-sandbox.sh session|apparmor`) covered what
the first pass left out. A Mint 22.1 container with a headless **sway** (Wayland, no XWayland),
**mutter 46** as a second compositor, **PipeWire** and the **xdg-desktop-portal** stack; and, for
AppArmor, a real **Ubuntu 24.04** VM booted under KVM (its own 6.8 kernel, which a container can't
provide). Findings that change or confirm the plan:

- **Ubuntu 24.04 blocks bwrap outright — AppKata must ship an AppArmor profile.** On a stock 24.04
  VM (`kernel.apparmor_restrict_unprivileged_userns = 1`), a plain `/usr/bin/bwrap` run from a login
  shell **fails** in every profile: `setting up uid map: Permission denied`, or, once a net namespace
  is made, `loopback: Failed RTM_NEWADDR`. Plain `unshare --user` is denied too. The system's loaded
  `unprivileged_userns` AppArmor profile is why. The fix every sandboxing app already uses: ship an
  AppArmor profile that grants the carve-out — the VM has `/etc/apparmor.d/` profiles for `flatpak`,
  `chrome`, `obsidian`, `signal-desktop`, `code`, `1password`, `element-desktop`, `steam` and more.
  A four-line profile for bwrap (`profile appkata-sandbox /usr/bin/bwrap flags=(unconfined) { userns, }`)
  made bwrap **work**, including the **nested** user namespace that Electron/Chromium's own sandbox
  needs. A third VM run checked the privilege model (see [bubblewrap](#bubblewrap)): an unprivileged
  user cannot write `/etc/apparmor.d/`, run `apparmor_parser`, or set the sysctl (all denied), so the
  profile is installed **on first need** behind a single **pkexec** prompt and then persists across
  reboots (`apparmor.service` is enabled and reloads the profile at boot). Disabling the sysctl also
  works but weakens the whole system. Where the user declines, the app runs Off (17.10): a Landlock-only
  fallback was considered and rejected (decision 6), since Landlock can't mediate the session bus.
  Mint 21.3 (bwrap 0.6.1) has no such restriction. *(Corrected 2026-10-24, review 3, R3-37: this said
  Mint 22 ships the same restriction as the 24.04 it's built on, which was inferred, not run. Mint 22
  lifts it in its own `/etc/sysctl.d/20-apparmor-mint.conf`, as the Mint 22.3 desktop VM shows.)*

- **Wayland isolation is compositor-dependent, not automatic.** On **sway** (and other wlroots
  compositors that enable the `wlr-screencopy`, `wlr-data-control` and `virtual-keyboard` protocols),
  a sandboxed app given only the Wayland socket could still **capture the whole screen**, **read the
  clipboard while unfocused**, and **type into another app's window** — the same three leaks as X11.
  On **mutter** (GNOME, and the base of Cinnamon's muffin) all three were **blocked**: it doesn't
  offer those protocols, and screencast goes through the portal with user consent. The real fix for
  wlroots is the Wayland **security-context** protocol (the Wayland analog of the D-Bus proxy): the
  launcher tags the app's connection so the compositor withholds the privileged protocols. **Decision:
  that protocol is deferred past v1** (it was not tested in round 2 and needs a real wlroots desktop to
  validate). v1 therefore **warns** on X11 and wlroots sessions rather than closing the leak; only
  mutter-style Wayland is clear. Sway's IPC socket was **not** reachable (it isn't under the bound
  socket path) — good, since it runs arbitrary commands; the launcher must never bind all of
  `$XDG_RUNTIME_DIR`.

- **Sound: playback is fine, but the raw socket also grants recording and server control.** With the
  PipeWire and PulseAudio sockets bound in, playback worked (and was correctly **blocked** without the
  grant). But the same socket let the app **record the microphone and a monitor of what other apps
  play** (captured another app's tone at full amplitude), and **load PulseAudio server modules**
  (`module-pipe-sink`, `module-native-protocol-tcp`) that run outside the sandbox. So "sound" can't be
  a single raw-socket grant. The mitigation is real and present: a client launched with a
  `.flatpak-info` marker was classified by PipeWire as `pipewire.access: flatpak` /
  `pipewire.sec.flatpak: true`, which is the hook WirePlumber uses to restrict recording and module
  loading per app. The plan gains: route audio so the session manager sees the app as sandboxed (the
  marker, or the camera/record portals), rather than handing over the bare socket; split the grant
  into **play** and **record**.

- **The D-Bus filter holds, and the file-chooser needs the document portal.** Through the filtered
  bus a sandboxed app reached **only** `org.freedesktop.portal.Desktop` (FileChooser, OpenURI,
  DynamicLauncher — each applying its own policy) and was **blocked** from `org.freedesktop.systemd1`,
  `org.freedesktop.Flatpak`, `org.freedesktop.portal.Documents` and `org.freedesktop.secrets`. A path
  the user would pick in a file dialog (e.g. `~/Documents/secret.txt`) is **not** readable inside the
  private home, confirming the chooser must hand files over through the **document portal**, which
  re-exports just the picked file — and that needs the app to be seen as sandboxed (the same
  `.flatpak-info` marker). This is standard Flatpak mechanics, now confirmed against this design.

- **Real GUI apps on Wayland only.** AppKata's own Qt AppImage and Obsidian 1.14.4 (Electron, run with
  `--ozone-platform=wayland`) both started and kept running in the Standard profile with only the sway
  Wayland socket, sound and the filtered bus — no X server present. Screenshots in `build/sandbox-test/`.

### Round 3: de-risking the plan before coding

A third pass validated the mechanisms the plan leans on (`scripts/sandbox/validate*.sh`, `merge.py`):

- **Theme/font binding — confirmed.** A private home hides the host's `~/.themes`/`~/.fonts`; binding
  them read-only makes them visible again and they stay read-only. Apps will look native. ✓
- **D-Bus capabilities — confirmed.** Through the proxy an app **can** own its own granted name
  (single-instance, "open in running window") and **cannot** own a name that wasn't granted. The
  capability model (own/talk per template) works as designed. ✓
- **Write-beside-itself + the writable-app-folder grant — confirmed.** Under Standard, writing next to
  the binary is blocked (read-only); the grant binds the folder read-write and the write succeeds. ✓
- **Full launcher, end to end — confirmed.** AppKata (Qt) and Obsidian (Electron) both run under the
  *complete* Standard launcher — identity marker + filtered proxy (own-name + a capability) + theme/font
  binds + a folder grant + network + X11 + sound — and `~/.ssh` stays blocked with all of it composed.
  The whole mechanism holds together, not just the pieces. ✓
- **Multi-Trust merge — resolved and tested.** `merge.py` implements the resolution rule (below) and
  its cases pass, including the previously-undefined "two different templates" case. ✓
- **App identity for portals — partly confirmed.** The synthetic `.flatpak-info` is **recognized** by
  the document portal (it handles a marked vs unmarked caller differently) and by PipeWire
  (`access=flatpak`), and the private home blocks the raw path. The exact file-chooser *handover* (the
  portal re-opening the picked fd) hit a container filesystem limit (the test file sat on the sandbox
  tmpfs, which the portal won't re-export) and still needs confirmation on a real desktop.
  **Later finding (review):** on xdg-desktop-portal 1.20 (Mint 22.1 / Ubuntu 24.04) a generated
  launcher's `FileChooser.OpenFile` call is refused — "Portal operation not allowed: Failed to open
  file …/.flatpak/<instance>/bwrapinfo.json" — because 1.18+ validates a marked caller against a live
  Flatpak instance; "recognized" above meant only that the marker changed the portal's behaviour.
  **Decided** (requirement 17.6.1, decision 15): the bus proxy carries no marker, the portals see a
  host caller, the file chooser portal is not used, and file arguments are handed over from the host
  side — all shown end to end in the containers since (`tests/test_sandbox_run.py`,
  `scripts/test-sandbox.sh filedialogs` and `consumers`).

**Still needs a physical desktop** — real GPUs (a VM has only a virtual adapter; the VM shows
the `/dev/dri` nodes resolve through `/sys`); a self-updating app sandboxed (round 1 already shows
the write to its own folder is blocked, so the updater will fail — the open question is whether apps
degrade gracefully or crash); the pkexec prompt where the setup is needed (this said "on Mint 22",
which needs none: corrected 2026-10-24, R3-37); a tray icon against a real
StatusNotifierWatcher; and a full run on a physical Mint 22 session (Cinnamon/X11 and a GNOME/Wayland
session). These are the human checklist in [`local-proxy-test-plan.md`](local-proxy-test-plan.md),
which `scripts/sandbox/field-test.sh` runs against a probe app AppKata itself installs. The document-portal hand-over, the portals as a
host caller, the toolkits' file dialogs, notifications and link opening, once on this list, have
been shown in the containers with the real portal and real apps.

## Limits

Say these in the UI and the docs, plainly:

- **The X11 toggle withholds the socket, not the server's reach.** With the network grant the X
  server's abstract-namespace socket (`@/tmp/.X11-unix/X<n>`) is in the shared network namespace
  and a sandboxed app can connect to it whatever the "X11 apps" grant says (a launcher test shows
  it); what keeps it out is Xwayland requiring the `XAUTHORITY` cookie, which GNOME/mutter and
  KDE/kwin do and wlroots compositors (no auth file) do not — the same sessions the next bullet
  already warns about. Flatpak has the same property. Said in 17.9 and the toggle's hint.
- **The network grant reaches every abstract socket on the host** (review 3, R3-8), not the X
  server's alone. Where dbus is 1.12 (Mint 21.3, Ubuntu 22.04, RHEL 9), a session bus started with
  `dbus-run-session` or `dbus-launch` listens on one, and an app with the network grant reaches it
  past the filtering proxy. A desktop's own login uses systemd's user bus, a path, and isn't
  affected. AppKata warns about such a session in Settings → Sandbox and, for an app with the
  network grant, in App Detail. The real fix, a network of the app's own (`pasta`, `slirp4netns`),
  is in 17.18.
- **Screen, clipboard and keystrokes — X11 and wlroots Wayland (a v1 limit).** Any X11 client can read
  keystrokes sent to other windows and capture the screen; on X11 a sandbox protects files, not what's
  typed, and Mint's Cinnamon is X11 by default. **Wayland is not automatically safe either:** wlroots
  compositors (sway and others) that expose the screencopy, data-control and virtual-keyboard protocols
  leak the same three vectors (confirmed in round 2); GNOME's mutter blocks them. KDE's kwin blocks
  capture and injection but offers the clipboard-manager protocol to every client, so the
  clipboard leaks there (round seven, R7-1, run under kwin 5.27). The
  Wayland fix — the **security-context** protocol — is **deferred past v1** (see the Plan; sway
  advertises it since wlroots 0.17), so in v1 AppKata does **not** close these on X11 or on Wayland;
  it **warns** plainly — on KDE about the clipboard alone — and treats only GNOME Wayland as clear:
  an allowlist, since a list of leaking compositors can only fall behind
  (round five, R5-1: it was one, and sway started from a TTY, which sets no `XDG_CURRENT_DESKTOP`,
  got no warning). The in-app warning (Settings → Sandbox, and the App Detail caveat) names this for
  the session the user is actually on, and the compositor when the session says which.
- **AppArmor where the kernel restricts unprivileged user namespaces.** There, without AppKata's
  AppArmor profile the sandbox doesn't launch at all (confirmed in round 2, on Ubuntu 24.04). The
  profile is required there, not optional; which tested systems restrict, [`testing.md`](testing.md)
  says.
- **Granted is granted.** A folder or the network given to an app is the app's — and a read-write
  folder is also a road to the host's programs: a file the app writes there and opens through the
  OpenURI portal is opened by the host's handler for its type, with no question when that handler
  is the only one installed (the portal asks only between several candidates with no settled
  choice; shown with the real portal in `scripts/test-sandbox.sh consumers`). Flatpak has the same
  property (round five, R5-5).
- **Chromium's own sandbox on Ubuntu 25.04 and later.** Under the system's `bwrap-userns-restrict`
  nothing inside the sandbox can make a user namespace, so a Chromium/Electron app runs with
  `--no-sandbox` inside AppKata's: a renderer exploit gets the app's own sandboxed access (its private
  home, its grants), not the rest of the account. App Detail says so (17.10.2).
- **The kernel.** A kernel exploit leaves any namespace sandbox; this isn't a VM.
- **Bypasses outside AppKata.** Running the `.AppImage` or the program directly, or through
  AppImageLauncher, skips the sandbox.
- **Only the terminal-injection seccomp filter.** The launcher's `--seccomp` filter refuses `TIOCSTI`
  and `TIOCLINUX` (what `--new-session` guarded, without cutting a tool off its terminal). Flatpak's
  fuller filter (blocking `ptrace` of other sandboxes, `perf_event_open`, unusual socket families) is
  worth adding after the first version.
- **Tray icons collide between sandboxed apps.** A tray item's bus name is
  `org.kde.StatusNotifierItem-<pid>-<n>`, and every sandboxed app is process 2 (or 3) in its own pid
  namespace, so every tray-capable proxy owns the same `…-2-1`. Two such apps running at once contend
  for it on the host bus; the second can't take the name and its icon may not appear. Flatpak has the
  same limitation. The Sandbox dialog's tray toggle says so.
- **File arguments reach a Standard app through the document portal; a Strict app gets none.** The
  launcher exports a file argument outside the granted folders from the host side (`Documents.Add`,
  so it works on xdg-desktop-portal 1.18+ too) and rewrites the argument to the `$XDG_RUNTIME_DIR/doc`
  path; the app sees that file alone, not its folder, so "open the sibling file" or relative paths
  next to it don't work — grant the folder for that. Needs `python3-gi` on the host and a running
  document portal; otherwise the argument passes through unchanged and the app can't open it.
- **The file dialog is the app's own, and the portals see a host caller.** xdg-desktop-portal 1.18+
  (Ubuntu 24.04, Mint 22) refuses any caller that claims a sandbox identity without being a running
  Flatpak, so the bus proxy carries no `.flatpak-info` and the portals answer the app as a host app,
  on the interfaces the proxy allows (open-URI, settings, print, email, the monitors; notifications
  and inhibit with their capabilities). The FileChooser portal is not among them: for a host caller it returns real paths the
  sandbox can't open, so the app's own dialog is used and shows exactly what the sandbox sees; a file
  elsewhere reaches the app by "Open with", a drop on its menu entry or a folder grant. An app whose
  own start script sets `GTK_USE_PORTAL=1` loses its file dialog. Links and files the app opens go
  to the host through the OpenURI portal — GLib and GTK apps on their own, but only because the
  host's desktop entries are hidden from the sandbox (GLib uses any handler it finds and asks the
  portal only when there is none, so `/usr/share/applications` is an empty tmpfs inside, and an app
  that lists installed applications sees none, as in Flatpak); Qt apps by calling the portal when
  they see `/.flatpak-info`; Electron and the rest through AppKata's `xdg-open`, first on the app's
  PATH — but a file in the private home can't be located by the portal (it reaches it as
  `$HOME/<x>`), only one in a granted folder or the hand-over view. A Strict app opens nothing on
  the host: it has no bus, and AppKata's `xdg-open` is on its PATH too, saying so and failing, so
  the desktop's own `xdg-open` in `/usr` never gets to start the host's browser inside the
  sandbox (round five, R5-4: it did, under a desktop it didn't know).
- **A launch that fails is reported from AppKata, recorded from the menu, and the user's own from a
  terminal.** The launcher keeps its stderr in `logs/apps/<id>.log` when AppKata's Open started it
  (that file is its stderr already) or the app-menu entry did (`--appkata-menu`); a command link run
  in a terminal or a script keeps stderr where the caller put it, so a tool's `2>file` and pipelines
  mean what they say — and a refusal there is on the terminal, not in the log. Only Open gets the
  toast; a menu launch that fails shows nothing on screen, the log has it. The toast covers the
  launcher's own refusals whenever they happen and the program dying within 10 s of being started;
  a later crash is in the log only. An entry written before this word existed gains it when the
  entry is next rewritten — at an update, a sandbox change, or AppKata's start if the launcher's
  text has changed too.
- **The symlink sweep covers a stopped app, not a running one.** Before bwrap mounts anything under
  the private home, the launcher removes any symlink the app left at a mount destination (otherwise
  bwrap follows it on the host side and creates files or folders at its target). A second, already
  running instance of the same app can still plant one between that check and the mount; bwrap has no
  fd-based destination to close the gap. The worst case is empty files or folders created as the user
  at a path the app chose, or a launch that fails.

## UI text and its evidence

The Sandbox dialog's hints state facts about what an app can and cannot do. Each is a claim like the
ones above, and round five and six found four that were not so ("always on", the password hints, the
camera portal). `tests/test_sandbox_ui_claims.py` reads every hint in `SandboxDialog.qml` and
requires a row here, matched on the hint's first words, so a new or changed hint without evidence
fails the local tier. Keep a row's first words identical to the hint's.

| Hint (first words) | What it claims | Evidence |
|---|---|---|
| "Let it reach the internet and the local network." | the network grant is all-or-nothing | tier 2 `test_a_network_grant_includes_working_dns`, `test_no_network_grant_means_no_network` |
| "Allow only certain ports (Landlock" | deferred | 17.18; the toggle is disabled |
| "Strict has no session bus: the app can't open links or files" | Strict opens nothing on the host | tier 2 `test_a_strict_app_fails_fast_on_every_desktop_road_and_never_falls_back_inside` (R5-4) |
| "Opening links and files on this computer, settings, printing — always on at Standard." | the portal roads at Standard | tier 2 host-caller test, `consumers` (links and files with the real portal) |
| "Send audio to the speakers. Not yet separable from recording" | play-only cannot be enforced | `wayland` harness: the play-only app records (17.8) |
| "Record audio from the microphone. Today any sound access allows this" | any sound grant also records | `wayland` harness: the play-only app records 385 KB from the same sockets (17.8) |
| "The camera devices themselves. Without this the app has no camera" | no camera portal road | tier 2 host-caller test: `AccessCamera` denied with and without the grant (R6-2) |
| "On Wayland, also offer X11 for apps that can't use Wayland." | the X11 toggle's reach | tier 2 `test_on_wayland_x11_apps_get_xwayland_only_with_the_grant`, `test_the_x11_abstract_socket_follows_the_network_grant_not_the_x11_one` (R4-8) |
| "Show a status-bar icon (StatusNotifierItem) and own its own bus name." | the tray road and the name collision | tier 2 `test_a_tray_icon_registers_with_a_watcher_which_can_talk_back_to_it` (round six); the collision is stated in 17.17 |
| "Play/pause and track info on the keyboard and lock screen (MPRIS)." | the MPRIS own | tier 2 `test_a_media_key_daemon_can_drive_an_app_with_the_mpris_capability_and_only_that_app` (a media-key stand-in calls `Play` on the app through the proxy; without the capability the app can't own the name) |
| "Show desktop notifications, through the notification portal" | the notification roads | `consumers` (a GLib notification shown with the capability, not without) and tier 1 `test_the_notification_and_inhibit_portals_come_with_their_capabilities` (review 3, R3-14) |
| "Inhibit the screensaver while it's doing something" | the inhibit roads | tier 2 host-caller test (the portal with the capability, denied without) and `test_the_direct_screensaver_name_takes_an_inhibit_only_with_the_capability` (the direct name, a ScreenSaver stand-in) |
| "Store and read passwords in your keyring (org.freedesktop.secrets)." | the keyring has no per-app walls | the Secret Service specification (one collection, any client): **read** |
| "Offer the secret service (org.freedesktop.secrets) to other apps" | owning the name | tier 2 `test_a_password_service_app_serves_a_host_client_only_with_the_provide_capability` (a host client opens a session with the sandboxed service; without the capability there is none) |
| "A second lock (Landlock) so the app can write its data but not execute" | deferred | 17.18; the toggle is disabled |
| "Only for apps that keep settings or data beside the program" | the writable app folder; an AppImage's own file stays read-only; AppKata updates a sandboxed app | tier 2 `test_a_self_updating_app_can_change_its_folder_only_with_the_writable_grant`, `…appimage_can_change_its_unpacked_copy_but_never_the_appimage_itself` (round six); tier 1 `test_a_self_updating_app_is_updated_by_appkata_while_it_runs_sandboxed` (review 2, F3) |

## Claims and their evidence

Every claim below is about someone else's behaviour — a toolkit, a portal, a daemon, a kernel —
and the spec states it as fact. Round five found that the ones written from reading source or from
a stand-in were where the wording drifted (R5-5, R5-6, the Chromium sentence of R5-2), so each is
marked here with its evidence: **run** (which harness shows it, on which version), **read** (which
source, which version), or **inferred**. A new claim gets a row; a row marked *inferred* is the next
round's finding until it is run or read. Harnesses: `scripts/test-sandbox.sh launcher` (Mint 22.3:
bwrap 0.9.0, xdg-desktop-portal 1.20, GLib 2.80), `launcher-lmde7`, `launcher-vm` (Ubuntu 24.04),
`filedialogs` (and `-lmde7`), `consumers`, `session` (round 2, sway/mutter/PipeWire), `probe` (round
1). A row run on an environment that has since retired (Mint 21.3 and 22.1, Ubuntu 25.04, Rocky,
Debian 12, Fedora) records where it was run; `testing.md` lists what runs now.

| Claim (where) | Evidence | How |
|---|---|---|
| bwrap follows a symlink at a bind *destination* on the host side and creates files there (17.4) | run | tier 2/3, `test_a_link_the_app_leaves_at_a_mount_point_is_not_followed` (bwrap 0.4.0 and 0.9.0) |
| An AppImage can't FUSE-mount inside bwrap, so it is extracted (17.7) | run | round 1 `probe` (Mint 21.3, 22.1) |
| dash's `printf` takes a format starting with `---` as options (14.2.1) | run | tier 2, the menu-launch test (round two, R4) |
| xdg-dbus-proxy accepts `IFACE.*@/path` and `@/path/*` call rules, makes the name visible, passes unicast signals, needs `--broadcast` for broadcasts; rejects `StatusNotifierItem-*` and a digit-led `--own` (17.5) | run + read | tier 2 `test_the_portals_answer_a_sandboxed_app_as_a_host_caller`, `test_an_app_whose_name_starts_with_a_digit_still_gets_the_bus`; `filter_new_from_rule` (finding 0) |
| xdg-desktop-portal 1.18+ refuses a caller presenting `.flatpak-info` whose instance id names no running Flatpak (17.6.1) | run | tier 2, the same test fails on the pre-15ae403 proxy with the exact refusal; `xdp-app-info-flatpak.c` |
| The portals' `open-uri.c` treats a host caller like a sandboxed one for the chooser and content-type logic; only the writable-fd check is relaxed; the chooser is skipped for a default-app scheme, a single handler, or a settled choice (17.6.3) | read + run | `open-uri.c` 1.20.0 (round four, R5-5); `consumers`: a single handler runs with no chooser |
| `Documents.Add` + `GrantPermissions` from a host process exports a file to an app id readable at `$rt/doc/by-app/<id>`, and only by that id (17.6.2) | run | tier 2/3 `test_a_file_handed_over_by_the_document_portal_is_readable_and_only_by_that_app`, `test_a_file_argument_is_handed_over_to_a_standard_app` (document portal 1.20 on FUSE) |
| The `by-app/<id>` view exists as soon as the document portal runs, before any export (17.6.2) | run | tier 2 `test_a_file_exported_while_the_app_runs_is_readable_on_its_first_launch` |
| The real portal's `OpenFile` for a host caller resolves the descriptor to the host path and opens it; a private-home file is refused with Response 2 (17.6.3) | run | `consumers` (round five, R5-6; it found the shim not waiting) |
| GLib opens a link or file with the default handler it finds and asks the OpenURI portal only when there is none (17.4, 17.6.3) | run | tier 2/3 `test_a_glib_program_opens_links_on_the_host_even_when_the_host_has_a_handler` (GLib 2.80); `gappinfo.c` |
| IBus and Fcitx 5 serve a sandboxed app through their portals behind AppKata's filter: an input context created and driven; refused without the rules; none at Strict (17.5; review 2, F15) | run | `inputmethod` harness (IBus 1.5.29, Fcitx 5.1.7, headless) |
| GLib sends notifications through the portal when it sees `/.flatpak-info`; nothing reaches the host daemon without the capability (17.5.1) | run | `consumers` (notification shown / not), tier 2 host-caller test |
| GLib's NetworkMonitor reads `[Context] shared=network` from the marker (17.6) | run | tier 2 `NetworkMonitor.GetAvailable` answers true; `gnetworkmonitorportal.c` |
| GTK3 never asks the portal for a file dialog without `GTK_USE_PORTAL` or `$XDG_RUNTIME_DIR/flatpak-info` (17.6.3) | run | `filedialogs` (GTK 3.24); no `/.flatpak-info` string in `libgtk-3.so.0` |
| GTK4 calls FileChooser.OpenFile without reading `version`; GTK 4.14 falls back to its own dialog when refused, GTK 4.18 shows none; `GDK_DEBUG=no-portals` stops GTK4 asking on both, and leaves GLib's link road alone (17.6.3) | run | `filedialogs` (GTK 4.14) and `filedialogs-qt68` (GTK 4.18), the "portals on" variant for the road the flag closes; `consumers` (a GTK4 link lands on the host) — round six, R6-4 |
| Qt 6.4 never touches the portal (reads `$XDG_RUNTIME_DIR/flatpak-info`); Qt 6.5+ reads `/.flatpak-info`, probes FileChooser's `version` and keeps its own dialog whatever the proxy answers (17.6.3) | run | `filedialogs` (Qt 6.4.2, Mint 22.1) and `filedialogs-qt68` (Qt 6.8.3, Ubuntu 25.04: `Properties.Get` in every variant, its own dialog in every variant, round six) |
| Qt calls the OpenURI portal itself when it sees `/.flatpak-info`, `xdg-open` only as a fallback (17.6.3) | run | `consumers` (Qt 6.4) and `filedialogs-qt68` (Qt 6.8): `QDesktopServices.openUrl` from a sandboxed app, the host handler ran, nothing inside — round seven |
| Chromium reads FileChooser's `version` first and cancels its dialog when `OpenFile` then fails; Electron ships the same code (17.5, 17.6.3) | run / inferred | `consumers` (Chromium 154, three proxy variants); Electron itself (Obsidian) **inferred** from the shared `select_file_dialog_linux_portal` |
| xdg-open's generic road (no known desktop) runs the first of `x-www-browser`, `firefox`, … on `PATH` (17.4) | run | tier 2/3 `test_a_strict_apps_xdg_open_fails_plainly_instead_of_starting_a_browser_inside` (xdg-utils 1.1.3) |
| PipeWire/WirePlumber take the app for a sandboxed client from `/.flatpak-info` and let it play — and record from the same sockets (17.8) | run | round 2 `session` (`sound.sh`: WirePlumber 0.4.17, PipeWire 1.0.5), and behind a *generated* launcher in `scripts/test-sandbox.sh wayland` (`pipewire.access = flatpak`, `app_id = io.appkata.<app>`; a play-only app records) |
| The Camera portal is denied to sandboxed apps, with and without the camera grant, so nothing asks (17.8) | run | tier 2 `test_the_portals_answer_a_sandboxed_app_as_a_host_caller` (`AccessCamera`, `IsCameraPresent`, the property); round six R6-2 corrected the earlier "asks the user first" |
| wlroots compositors expose screencopy, data-control and virtual-keyboard to any client; mutter exposes none; kwin hides screencast and fake input but exposes data-control, so the clipboard leaks there (17.9) | run | `wayland` harness (sway: `wl-paste` reads the host's clipboard from the sandbox; mutter: nothing of the kind advertised) and `kwin` harness (kwin 5.27: the globals it offers and `wl-paste` reading the clipboard) — round seven, R7-1; and `kwin6` (kwin 6.3, Ubuntu 25.04): the same, with `wp_security_context_manager_v1` advertised too (round eight) |
| mutter starts Xwayland with an auth cookie; wlroots does not; kwin: read (17.9) | run / read | `wayland` harness: an unauthenticated X11 connection over the abstract socket from a sandboxed app is accepted by sway's Xwayland and refused by mutter's ("Authorization required"); kwin `xwayland.cpp` **read** |
| AppKata reads which leaking globals a compositor offers an ordinary client: sway capture, clipboard and input; mutter none; kwin 5.27 and 6.3 the clipboard alone (17.9; review 2, F7) | run | `wayland`, `kwin`, `kwin6` harnesses (`sandbox.compositor_leaks`, as a host client); tier 1 against `tests/fake_wayland.py` |
| The X server's abstract socket is reachable from a shared network namespace whatever the socket bind says (17.9) | run | tier 2/3 `test_the_x11_abstract_socket_follows_the_network_grant_not_the_x11_one` |
| sway started from a TTY sets no `XDG_CURRENT_DESKTOP`; display managers export it from the session file (17.9) | read | sway's man page and `sway.desktop` (`DesktopNames=sway`); the warning no longer depends on it (R5-1) |
| Ubuntu 24.04 restricts unprivileged user namespaces through AppArmor, and Mint 22 lifts that restriction in its own `/etc/sysctl.d/20-apparmor-mint.conf`; an `(unconfined)` profile with `userns` on bwrap's path lifts it (17.10) | run | tier 3 (the VM applies the profile first), round 2 `apparmor`; each VM checks `testing.md`'s table (`tests/test_booted.py`, review 3, R3-37) |
| Ubuntu 25.04 and 26.04 ship `bwrap-userns-restrict` on `/usr/bin/bwrap`; under it bwrap runs but nothing inside can make a user namespace (17.10.2) | run + read | `launcher-vm26` (26.04: `test_the_inner_sandbox_probe_tells_the_truth_inside_a_generated_launcher`); 25.04's `apparmor` 4.1.0~beta5 and 26.04's 5.0.2 packages read (review 2, F2) |
| AppKata's profile loaded beside Ubuntu's leaves bwrap with no user namespace, live and after a reboot (17.10.2) | run | review 2's KVM probe in a 26.04 guest (`vm-probe.sh` and its reboot variant) |
| Chromium/Electron abort without a nested user namespace and a setuid `chrome-sandbox` ("The SUID sandbox helper binary was found, but is not configured correctly"), and run with `--no-sandbox`; electron-builder's AppRun adds `--no-sandbox` itself when `unshare -Ur true` fails (17.10.2) | run | Obsidian 1.x in the 26.04 guest: its binary behind a generated launcher aborts (exit 133) without the launcher's block and runs with it; its AppImage runs either way, its AppRun read (review 2, F2) |
| Mint 22.1's and Ubuntu's default `.bashrc` sources `~/.bash_aliases`; Fedora's sources `~/.bashrc.d/*` (17.3.1) | run | tier 2 `test_every_file_the_distributions_default_bashrc_sources_is_refused` (Mint skel); Fedora 40's `/etc/skel/.bashrc` lines 18–19 (round six) |
| Python runs `.pth` files from `~/.local/lib/python3.X/site-packages` without `-s` (17.3.1) | read | CPython `site.py`; AppKata's AppImage sets `PYTHONNOUSERSITE=1` |
| A browser's `NativeMessagingHosts` manifest names a program it starts on an extension's request (17.3.1) | read | Chromium and Firefox native-messaging documentation |

## Decisions

Resolved for the first release (the open questions these replace are in the PR history):

1. **Defaults, with a precedence rule.** *Reviewed* beats *unreviewed*; the app kind sets the
   starting point. A **reviewed GUI app** → the review's level (baseline Standard); a **reviewed CLI
   tool** → the review's level (baseline **CLI tool**); an **unreviewed GUI app** → **Strict**; an
   **unreviewed CLI tool** → the **CLI tool** template (binds the directory it's run in — real
   protection, not Off; Off remains the fallback for tools that need wider paths). Every default is one
   click to change in Install
   options or App Detail. (When AppKata gains [categories](#app-categories-separate-work), the
   unreviewed default may use the app's category as a non-authoritative hint for a better suggested
   template — a separate feature, not a dependency.)
2. **The `.AppImage` file is canonical; the extracted directory is a derived cache.** At **Off** the
   original `.AppImage` is run directly (it self-mounts via FUSE outside any sandbox — most faithful
   to a normal install, no extraction). At **Standard/Strict** AppKata extracts **lazily** on first
   sandboxed launch and runs `AppRun` in bwrap. Switching Off→sandboxed extracts then; sandboxed→Off
   leaves the extracted dir as a cache (it goes with the version when that is removed). So the
   2.5–3.5× disk cost is paid only by apps that actually run sandboxed, and the `.AppImage` stays
   for rollback and "run outside AppKata".
3. **No migration path.** Sandboxing is in the first release's baseline, so there are no pre-sandbox
   installs to upgrade. An app gets its default level with a **fresh private home** (its old
   `~/.config/<app>` is not copied in); an AppImage re-extracts on next launch if sandboxed.
4. **One-click folder grants:** Documents, Downloads, Pictures, Videos, Music — **all default Off**,
   resolved through the localized XDG user dirs. Note these only gate the app *browsing* those trees:
   at Standard, a file given to the app ("Open with", a drop on its menu entry, a command-link
   argument) is handed over through the document portal from the host side and is readable at the
   path the portal gives (the launcher binds the portal's per-app view at `$XDG_RUNTIME_DIR/doc`, as
   Flatpak does; verified with a generated launcher in the Mint 22.1 container). The app's *file
   dialog* is its own and shows what the sandbox sees (the private home, the granted folders, that
   view): the portal file chooser is not used, since xdg-desktop-portal 1.18+ refuses a non-Flatpak
   caller that claims a sandbox identity, and for a host caller it returns paths the sandbox can't
   open — requirement 17.6.1 records the decision, 17.6.3 the consequences. Strict has no bus and so
   no portals: a Strict app can open only what's in its private home.
5. **Reviews never auto-change grants.** A new version installs normally and keeps the user's current
   grants; if its reviews suggest *more or less* access, the app gets a **review badge** (not a
   blocked update). The UI says plainly that a new version may be partly non-functional until the
   user reviews — the safe direction, since access is never silently widened.
6. **No Landlock-only fallback.** Landlock protects files but can't mediate the session D-Bus socket,
   so a Landlock-only app could still reach `systemd` and escape; offering it as "protection" would
   mislead. On Ubuntu 24.04, if the user declines the one-time AppArmor prompt, the app runs **Off
   with a clear warning**. Landlock stays on the roadmap only as **defense-in-depth layered inside
   bwrap** ([The Landlock layer](#the-landlock-layer)), never as a substitute.
7. **Templates, and a progressive dialog (not a wizard).** A sandbox is picked as a named
   [template](#templates) (seven built-in), a thin, overridable preset of level + grants + **Services
   capabilities** (tray, MPRIS, inhibit, notifications, secrets) + Landlock. Reviews name one plus
   overrides. **Personal** templates (naming the user's own paths) are a likely later addition;
   **reviewer-defined** templates are a deferred open question we lean against. The per-app dialog is a
   **template dropdown + live summary + collapsed Customize** (grouped Files / Connections / Devices &
   media / Advanced, with Landlock under Advanced), not a wizard; tabs only if Customize grows too tall.
8. **Desktop-integration details (from the design sweep).** The sandbox binds the host's themes, icons
   and fonts read-only so apps look native; lets each app own its own bus name (single-instance) and
   its template's Services capabilities; and presents a stable `io.appkata.<app>` identity (via
   `.flatpak-info` in the app's root) that PipeWire and GLib rely on and that names the app's
   document-portal folder (the Wayland security-context will use it too, once that's built); the
   portals themselves see a host caller on a narrowed proxy (requirement 17.6.1). Hardware/device
   tools (Ventoy, disk utilities) legitimately run **Off** — the
   expected outcome, not a gap. Proprietary-NVIDIA device nodes are a known later complication.
9. **Wayland deferred to post-v1.** The security-context protocol (the only way to close the wlroots
   screen/clipboard/input leak) is **not in the first release**. v1 ships the honest in-app warning for
   X11 and wlroots sessions instead; mutter-style Wayland is unaffected. The protocol moves to the Plan's
   "later" step, where it can be validated on a real wlroots desktop (it was not tested in round 2).
10. **CLI tools get real protection** (not Off). An app's kind is decided from its download — an
    AppImage's `.desktop` saying `Terminal=true`, or a tarball whose program links no display library —
    and the user can correct it in the install options (17.3.3; review 2, F4: it had been "a command
    link and no menu entry", which Settings' defaults never produced). The default is the **CLI tool** template — the
    launcher binds the directory the tool is run in (rw) and nothing else of the home (validated
    in round 3), except when that directory is the home, above it or a never-shared folder, where
    the tool runs in its private home and says so. A file named on the command line is handed over
    from anywhere (decision 16); a directory elsewhere isn't visible, and such tools can take a
    folder grant or Off.
11. **A sandboxed app is updated by AppKata.** Self-update can't work in a sandbox (the install folder
    and an AppImage's own file are read-only), so while an app runs sandboxed AppKata updates it as if
    it didn't update itself, and says why (4.10.5, 17.12). This replaces the original "Disable the app's
    own updater" option, which contradicted 4.10.3 and was never built (review 2, F3). (Whether a
    given app degrades gracefully or crashes when its updater is blocked is the self-update item still
    owed on a real desktop.)
12. **Enabling a sandbox after install warns it's effectively a reinstall.** The app's real files are
    never touched — they're just hidden by the private home — so there's no data *loss*, but the app
    sees an empty home: settings/accounts appear reset, absolute paths stored in its config (recent
    files, a vault/library location) dangle, and external integrations that live in the real home
    (browser native-messaging hosts, MIME associations, autostart/systemd units) may stop working.
    v1 therefore **warns on enabling** that the app is effectively being reinstalled and its
    configuration may be reset — a plain, honest heads-up rather than a silent surprise. No automatic
    config import in v1 (a possible later convenience if the reset proves painful); the real files remain
    on disk, so a user can copy anything across by hand.
13. **Multi-Trust merge rule ratified** (validated in `scripts/sandbox/merge.py`): resolve each review's
    template + overrides to a grant set, then across Trusts take the strictest level and the intersection
    of grants (a folder only if all grant it, rw only if all rw; execute-deny if any denies); the user's
    choice wins; no reviews → the default template. See [Resolving several sources](#resolving-several-sources).
14. **v1 scope = this plan minus the deferred items.** Everything in [Decisions](#decisions) and Plan
    steps 1–6 ships in the first release — the AppArmor pkexec setup, the launcher, the eight templates
    with Services capabilities, Off/Standard/Strict + grants, lazy AppImage extraction, tarballs, the
    `AppKata.md` review lines with the merge rule and review badge, AppKata updating sandboxed
    self-updating apps (4.10.5), and the session-type warning. **Deferred to later** (Plan steps 7–8): the Wayland security-context, the
    Landlock layer, personal templates, reviewer-defined templates, App categories, a fuller seccomp
    filter, squashfuse, NVIDIA nodes.

Decided during the review rounds (the findings and evidence are in
[`reviews/app-sandboxing-1.md`](reviews/app-sandboxing-1.md); the requirement numbers are the spec):

15. **The portals see a host caller; the file dialog is the app's own** (17.6.1, 17.6.3).
    xdg-desktop-portal 1.18+ refuses any caller that presents a sandbox identity without being a
    running Flatpak, so the bus proxy carries no `.flatpak-info` and the portal name is opened
    per interface — only what is safe for a host caller, with Notification and Inhibit gated on
    their capabilities so the summary chips are the truth (decision 17). AppKata never fabricates
    Flatpak instance records. The file chooser portal is therefore not used (for a host caller it
    returns paths the sandbox can't open); the app's own dialog shows what the sandbox sees, and
    the proxy's denials — FileChooser for GTK4, the `version` properties for Chromium/Electron —
    are what keep every toolkit there, shown with real apps.
16. **Files given to an app are handed over from the host side** (17.6.2): the launcher exports a
    file argument outside the granted folders through the document portal and rewrites the
    argument; the app sees the file, not its folder; Strict apps get none.
17. **A capability opens both roads.** The notifications and inhibit capabilities open the portal
    interface *and* the direct bus name; an app without the capability has neither (17.5.1).
18. **"Follow reviewers' suggestions" off takes reviews out of sandboxing entirely** (17.15): the
    user's default for the kind applies, no badge shows, the dialog still says what they suggest.
19. **Installed launchers are kept current by comparison, not by version** (17.4): at start, any
    launcher that is not the text AppKata would write today is rewritten — a previous AppKata's,
    or a hand-edited one — so a launcher fix reaches every installed app without an update.

### Prompts and recovery

No sandbox prompt is a dead end; every dismissible prompt maps to a persistent control.

- **The AppArmor system-setup prompt (Ubuntu 24.04, pkexec).** Installing the first app that would
  run sandboxed asks *"Set up the sandbox?"*: **Set up now** runs the setup, then installs; **Not
  now** installs the app to run Off and is remembered, so later installs don't ask (review 2, F12:
  the prompt was specified and never built). It's system-wide (one profile for `/usr/bin/bwrap`
  covers every app), so it's re-engaged from **Settings → Sandbox**, a status row: *"System support:
  Not enabled — Set up…"* (reads *"Ready"* once done), which says installs don't ask after a Not now.
  An app running Off meanwhile shows a standing indicator in its App Detail — *"Not sandboxed —
  system setup needed · Enable…"* — running the same setup. Set up… and Enable… clear a Not now.
  AppKata shows a standing indicator, not a per-launch popup.
- **Per-app level and grants.** Always editable in **App Detail → Sandbox → Change…**; the
  first-install choice being skipped or defaulted locks nothing.
- **The review badge (decision 5).** Standing, not modal — it persists until the user opens the
  Sandbox dialog and acts, so it can't be lost.

## Plan

This was the build order; steps 1–6 are **done** (a build log now), step 7 is **deferred** (17.18) and
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
   App Detail Sandbox section and the Change dialog are wired; sandbox changes are audited (17.16).
4. **AppImage.** ✅ `.AppImage` runs directly at Off; Standard/Strict extract **lazily** inside the
   launcher (`_EXTRACT_BLOCK`, rebuilt if missing), run `AppRun`, and set `APPDIR`/`APPIMAGE`/`ARGV0`
   (decision 2). The extraction cache is cleaned up with kept versions.
5. **Display, sound, portals.** ✅ The launcher binds the Wayland or X11 socket at run time (X11 on
   Wayland too with the device grant), binds the PipeWire socket for sound (the play/record split
   is shown but not enforced — WirePlumber lets a sandboxed client record through the same
   sockets, deferred), hands file arguments over through the document portal, puts a portal-aware
   `xdg-open` first on the PATH, hides the host's desktop entries, and `session_warning()` drives
   the session caveat in App Detail and Settings (X11, and every Wayland compositor but GNOME's, 17.9). An end-to-end run on a physical desktop is
   the item still owed (`local-proxy-test-plan.md`). The **Wayland security-context** is deferred
   (step 7).
6. **Reviews.** ✅ `trustfile.py` parses/writes `Sandbox` / `Sandbox folders` / `Sandbox network` /
   `Sandbox sound` / `devices` / `services` / `app folder` (10.3.1, Linux-only), and saving a review
   writes the user's own sandbox (`sandbox.as_review`, review 2 F9); `backend._resolved_sandbox()` merges Trusts least-privilege with the user
   winning; the **review badge** (`sandboxInfo.reviewBadge`) flags a version whose reviews suggest a
   change without widening access (decision 5).
7. **Deferred (17.18), not v1:** the **Wayland security-context** protocol (close the wlroots
   screen/clipboard/input leak), the **Landlock** layer (execute-deny, per-port TCP; the Advanced
   toggles are present but disabled/"Later"), **personal templates** ("Save as template…"), config
   **import on enable-later** (v1 only warns, decision 12), a **fuller seccomp** filter beyond the
   terminal-injection one, **squashfuse** instead of unpacking, enforcing the play/record sound
   split, and proprietary-NVIDIA device nodes.
8. **Separate features (not this work):** [App categories](#app-categories-separate-work) in the
   Catalog; reviewer-defined shared templates (deferred, leaned against). Adjacent, raised during this
   work: publisher-GPG verification ([`gpg.md`](gpg.md)) and a release workflow
   ([`github-workflows.md`](github-workflows.md)).

**After the build:** four review rounds (2026-10-10/12, [`reviews/app-sandboxing-1.md`](reviews/app-sandboxing-1.md))
found and fixed, each in its own commit with a test shown failing before: an escape through the
identity marker's location and another through the CLI tool's working directory, the real home put
back by a folder grant, planted symlinks at mount points, the portals refusing a marked caller
(decision 15), reviews widening a pinned app, Strict not enforcing its table, GLib starting the
host's browser inside, a Strict app dying with its caller, and a number of UI and state bugs. Then
five commits closed the *classes* those findings fell into (the QML driven against the real
Backend, grant-set invariants, launcher goldens, real consumers, transition snapshots), and the
branch was judged ready to merge, with the physical-desktop pass left for a release.

The feature now lives in `docs/requirements.md` §17 (decisions in `docs/gaps.md` §16), like the rest of
AppKata; this document is kept as its rationale and build log.
