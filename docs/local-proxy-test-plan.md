# Sandbox launcher & bus proxy: how they work, and the real-desktop checklist

Companion to [`app-sandboxing.md`](app-sandboxing.md) (the rationale) and requirement 17 (the spec).
Two parts:

1. **[How the launcher works](#how-the-launcher-works)**: the parts of the text AppKata writes for
   each sandboxed app, the filtered D-Bus proxy, the identity marker and the capability mapping.
   The launcher's **exact text is the goldens** in [`tests/data/launchers/`](../tests/data/launchers/),
   one per grant set. `tests/test_launcher_golden.py` keeps them byte for byte, so any change to the
   launcher shows in review as a shell diff (requirement 17.4).
2. **[The real-desktop checklist](#the-real-desktop-checklist)**: what a logged-in desktop can answer
   and the containers and VMs can't. `scripts/sandbox/field-test.sh` runs it against what AppKata
   itself installs.

Status: built, and tested in the environments of [`testing.md`](testing.md). Review 2 (D1) replaced the planning-stage
spec that stood here. That spec put the marker in the private home and in the proxy's root, opened
the whole portal name, used `--new-session`, and expected the portal file chooser to hand files over.
None of those are built, for the reasons in 17.6.1, 17.6.3 and the review rounds.

---

## How the launcher works

`~/bin/apps/<app>/run` is a POSIX shell script that AppKata writes and rewrites:

- on every install, update and sandbox change;
- at AppKata's start, for any launcher whose text isn't today's, or whose helpers aren't (17.4).

Its only run-time decisions are about the host it starts on: the display, DNS, the CLI tool's
folder, the arguments, and whether the AppImage is unpacked yet. In order:

1. **Header.** The app's identity (`id=io.appkata.<app>`), its private home, its marker, its program
   and its log path. If the session's runtime folder is missing, it says so and stops. Started from
   the app menu (the entry passes `--appkata-menu`), it appends its stderr to `logs/apps/<id>.log`,
   rotated at 2 MB (14.2.1). Started by AppKata, that file is its stderr already. From a terminal,
   stderr stays the caller's.
2. **A command-line tool's folder (the `cli-tool` template).** The folder it runs in is shared
   read-write unless it is the home, above it, or never shared (17.3.1). Paths are compared
   physically (`pwd -P`). When it isn't shared, the tool runs in its private home and says why
   (17.3.3).
3. **File arguments (Standard).** A path or `file://` argument outside the granted folders is handed
   over through the document portal from the host side (`Documents.Add` + `GrantPermissions` for the
   app's id), and the argument becomes `$XDG_RUNTIME_DIR/doc/<doc>/<name>` (17.6.2).
4. **Strict, from a terminal.** With arguments and a terminal on stderr, it says the app sees only its
   private home (17.3.3).
5. **The symlink guard.** Every mount destination under `$HOME` lies inside the app-writable private
   home, so any symlink the app left at such a path is removed before mounting (17.4).
6. **A refused folder** is noted in a comment: never shared (17.3.1), or not a full path.
7. **An AppImage is unpacked lazily, in its own sandbox.** Its runtime runs in a bwrap that can write
   only a staging folder; the result is stamped with the file's size, mtime and inode, and serialised
   with `flock` (17.7).
8. **Chromium's own sandbox (only where it can't run).** Under Ubuntu 25.04+'s `bwrap-userns-restrict`
   a program that brings `chrome-sandbox` or `chrome_crashpad_handler` gets `--no-sandbox` (17.10.2).
9. **The bus proxy (Standard).** See [below](#the-filtered-d-bus-proxy).
10. **Display.** The Wayland socket if the session has one, else X11 with `XAUTHORITY`. On Wayland,
    X11 is added too with the X11 device grant (17.9).
11. **DNS (with the network grant).** Where `/etc/resolv.conf` points into `/run` (systemd-resolved,
    NetworkManager), that target is bound too.
12. **The host's desktop entries** (`/usr/share/applications`, `/usr/local/share/applications`) are
    masked with an empty tmpfs. GLib then asks the OpenURI portal instead of starting a host
    program inside (17.4, 17.6.3).
13. **The environment.** `--clearenv`, then an allow-list: locale, terminal, session and desktop
    names, theme and scaling variables. Then `HOME`, `PATH` (AppKata's shim folder first),
    `XDG_RUNTIME_DIR`, `GDK_DEBUG=no-portals`, `DBUS_SESSION_BUS_ADDRESS` (the proxy) and, for an
    AppImage, `APPDIR`/`APPIMAGE`/`ARGV0`.
14. **The bwrap command, run as the launcher's own child at every level.** The app outlives whatever
    started it (17.4), and its status is passed through.
    - Read-only: `/usr` and `/etc`, the fontconfig cache, the `/sys` paths that identify GPUs, the
      version folder (or read-write with the writable-app-folder grant), and the desktop's themes,
      icons and fonts.
    - Devices: `/dev/dri`, and with the camera grant `/dev/video*` and `/dev/media*`.
    - The rest: the private home over `$HOME`; the folder grants; the PipeWire and Pulse sockets with
      a sound grant; the marker at `/.flatpak-info`; the proxy socket at `$XDG_RUNTIME_DIR/bus`; the
      document portal's `by-app/<id>` view at `$XDG_RUNTIME_DIR/doc`; the shim folder at
      `/run/appkata`.
    - Flags: `--unshare-all`, plus `--share-net` with the network, `--die-with-parent`, and the
      terminal-injection seccomp filter (`--seccomp`, or `--new-session` only where the filter isn't
      built).
15. **Teardown.** The proxy is stopped and its socket removed.

### The filtered D-Bus proxy

- **One `xdg-dbus-proxy` per launch, in its own minimal bwrap.** It has a tmpfs root with `/usr` and
  `/etc`, and `$XDG_RUNTIME_DIR` bound read-write so its socket is visible to the launcher.
- **It has its own pid namespace (`--unshare-pid`), so it ends with its bwrap.** Its own death signal
  isn't enough: the kernel clears it at an exec that changes the security domain, as entering Ubuntu
  25.04+'s `unpriv_bwrap` does (review 2, F2).
- **Its root carries no `.flatpak-info`**, so the portals judge the app a *host* caller. That is why
  the portal name is opened per interface (17.5, 17.6.1):
  - always: OpenURI, Settings, Print, Email, NetworkMonitor, ProxyResolver and MemoryMonitor, with
    their Request and Session objects and the portal object's Introspectable;
  - with their capabilities: Notification and Inhibit;
  - never: anything else on that name, including FileChooser, Background, DynamicLauncher,
    Documents, Camera, ScreenCast and the `version` properties.
- **`--filter` is mandatory.** An unfiltered bus reaches `org.freedesktop.systemd1`.

### The app-identity marker

- **Where it lives.** `<data>/sandboxes/.identity/<app>`, outside the app's private home (an app
  could swap a marker in its home for a symlink to a host file). It is bound read-only at
  `/.flatpak-info` in the app's root only, never the proxy's.
- **What it says.**
  ```ini
  [Application]
  name=io.appkata.<app>        # io.appkata._7zip for a slug that starts with a digit

  [Instance]
  instance-id=<app>            # the install's own id (17.6)

  [Context]
  shared=network;              # only with the network grant
  ```
- **Who reads it.** PipeWire/WirePlumber, to treat the app as a sandboxed client (17.8), and GLib,
  for its portal use and network availability. The portals don't read it (17.6.1).
- **Kept current.** It is rewritten at start whenever it isn't today's text (17.4, review 2 F5).

### Capability → proxy arguments

| Capability | Proxy arguments | Notes |
|---|---|---|
| (always) | the per-interface `--call` rules above, `--own=io.appkata.<app>` | single instance, "open in the running window" |
| Notifications | `--call=…=org.freedesktop.portal.Notification.*@…` and `--talk=org.freedesktop.Notifications` | both roads with the capability, neither without (17.5.1) |
| Screensaver inhibit | `--call=…=org.freedesktop.portal.Inhibit.*@…` and `--talk=org.freedesktop.ScreenSaver` | likewise |
| Tray icon | `--talk=org.kde.StatusNotifierWatcher`, `--own=org.kde.StatusNotifierItem-<pid>-<n>` for pids 2–6, n 1–3 | xdg-dbus-proxy rejects `StatusNotifierItem-*`; two tray apps can collide (17.17) |
| Media keys | `--own=org.mpris.MediaPlayer2.*` | |
| Secrets (use) | `--talk=org.freedesktop.secrets` | the keyring has no per-app walls: every unlocked password |
| Secrets (provide) | `--own=org.freedesktop.secrets` | e.g. KeePassXC |
| Camera | none: `/dev/video*` and `/dev/media*` are bound | the Camera portal is closed to sandboxed apps (17.8) |

---

## The real-desktop checklist

### Running it: `scripts/sandbox/field-test.sh`

```sh
scripts/sandbox/field-test.sh                                   # automated checks, then a few questions
scripts/sandbox/field-test.sh --app ~/Downloads/SomeApp.AppImage  # also install and start a real app
scripts/sandbox/field-test.sh --non-interactive                 # no questions (they're listed as MANUAL)
```

**What it does.**

1. It installs a small probe app through AppKata's own install path, from a local HTTP server
   standing in for a forge.
2. It lets AppKata write the probe's launcher for each template a check needs, and runs that
   launcher. Every check is a check of the code a user gets.
3. With `--app`, it installs and starts the given AppImage the same way.

**Safety.** Everything happens in a throwaway home that it creates and removes; the real home is
never written. The session stays real: the display, the session bus, the portals, the sound server
and the GPU. (Review 2, D1: the script it replaced wrote a canary into the tester's real
`~/.ssh/id_ed25519` and then deleted that file.)

**Output.** It writes `appkata-fieldtest-<host>-<date>/`: `report.md`, a PASS/BLOCKED/LEAK/FAIL/
MANUAL table, plus `env.txt`, logs and screenshots, and a `.tar.gz` of it all. **Bring back the
`.tar.gz`.** Where each run goes, a release's tracking issue on GitHub, is in
[`testing.md`](testing.md), "Tracking the runs on GitHub" (not set up yet: once the repository is
published).

**Tested.** `tests/test_sandbox_run.py::test_the_field_test_checks_the_product_and_leaves_the_testers_home_alone`
runs it on every launcher tier: the Mint 22.3 and LMDE 7 containers and the Ubuntu 24.04 and 26.04
VMs. The Mint 22.3 and LMDE 7 desktop VMs, installed from the official ISOs
(`scripts/test-desktop-vm.sh run mint22.3|lmde7`), run the whole script with `--non-interactive`, as
a user logged in to Cinnamon: every automatic check passes or is blocked as it should be, and the
questions below come out as MANUAL. Those questions, and a real GPU, are what is left for a person.
`docs/build.md` asks for this run before tagging a release.

Run it on **real hardware with a logged-in desktop**, on the environments 1.1 claims a sandbox on
([`testing.md`](testing.md)):

- **Linux Mint 22.3**: Cinnamon on X11.
- **LMDE 7**: Cinnamon on X11, on Debian's kernel.
- **Ubuntu 24.04 LTS**: GNOME on Wayland.
- **Ubuntu 26.04 LTS**: GNOME on Wayland, under Ubuntu's own bwrap profile.
- Where available: a KDE session, a wlroots session (sway, Hyprland), and a machine with a real GPU,
  NVIDIA included.

Use real apps: KeePassXC, Krita, Signal or Element, a media player, VSCodium, and an Electron app
that updates itself (Obsidian).

### What it checks by itself

| ID | Check | Requirement |
|---|---|---|
| A-support | AppKata's sandbox can run here (setup done, no conflict with the system's own profile) | 17.10, 17.10.2 |
| ISO-keys, ISO-home | a sandboxed app can't read the home's keys; its writes land in its private home | 17.2, 17.3.1 |
| ISO-net, ISO-net-on | Strict has no network; Online app has it | 17.2 |
| D-theme | the desktop's themes are visible, read-only | 17.4 |
| P-filter, P-portal | the bus filter refuses `systemd1`; the portal answers through it | 17.5 |
| P-handover | a file given as an argument reaches the app (document portal) | 17.6.2 |
| INNER | whether an app's own sandbox can run inside AppKata's here, and the launcher agrees | 17.10.2 |
| D-wayland / D-x11 | screen capture from a sandbox, and the session warning saying so where it works | 17.9 |
| D-sound, D-nosound | a sound grant reaches the sound server; no grant, no server | 17.8 |
| D-gpu | the OpenGL renderer inside | 17.4 |
| T-cli, T-cli-home | a command-line tool works in its folder; run from the home, it gets its private home and says why | 17.3.3 |
| EXP-strict, EXP-online-app | everything a Strict and an Online app see of this desktop is listed in [`sandbox-exposure.md`](sandbox-exposure.md), each row stated by a requirement | 17.4, 17.17 |
| GUI-run (`--app`) | a real app installed by AppKata starts from its launcher and keeps running | 17.4 |

### What it asks the tester

- **A1-prompt.** Where the setup is needed, before the setup, installing a first AppImage asks "Set
  up the sandbox?"; Not now installs it unsandboxed, and a second install doesn't ask (17.10).
- **A1-pkexec.** Where the setup is needed, Settings → Sandbox → Set up… shows one password prompt,
  then "Ready". Where the system has a bwrap profile of its own no setup is needed, and Repair…
  appears only if AppKata's old profile sits beside it (17.10.2).

The setup is needed where the kernel restricts unprivileged user namespaces and the system has no
bwrap profile of its own (17.10); which of the tested systems that is, [`testing.md`](testing.md)
says ("What each environment boots with"). The field test asks the A1 questions only where it finds
that so, and records them N/A elsewhere.
- **P-dialog.** A sandboxed app's own file dialog shows its private home and its granted folders, and
  nothing else of the home (17.6.3).
- **P-openwith.** "Open with", or a drop on its menu entry, of a file outside its folders opens that
  file (17.6.2).
- **T-tray / T-mpris.** The messenger template's tray icon and notifications; the media player's
  media keys (17.5.1).
- **U-selfupd.** An app that updates itself, sandboxed: AppKata offers its updates, and the app copes
  with its own updater failing (17.12).
- **U-enable.** Switching an installed app from Off to a sandbox says, before Save, that it starts
  with fresh settings (17.13).
- **E-native.** A password manager's browser integration (native messaging) still works.
