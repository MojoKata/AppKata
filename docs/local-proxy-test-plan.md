# The sandbox's real-desktop checklist

Companion to [A1](architecture/A1-app-sandboxing/README.md) (the rationale) and R17 (the spec).
How the launcher works is
[A1.2.3](architecture/A1-app-sandboxing/A1.2-approach.md#a123-what-every-sandboxed-launch-does): the
launcher step by step (A1.2.3.11), the filtered D-Bus proxy (A1.2.3.12), the identity marker
(A1.2.3.13) and the capability mapping (A1.2.3.14). Its **exact text is the goldens** in
[`tests/data/launchers/`](../tests/data/launchers), one per grant set; `tests/test_launcher_golden.py`
keeps them byte for byte, so any change to the launcher shows in review as a shell diff (R17.4).

This file is [the real-desktop checklist](#the-real-desktop-checklist): what a logged-in desktop can
answer and the containers and VMs can't. `scripts/sandbox/field-test.sh` runs it against what AppKata
itself installs.

Status: built, and tested in the environments of [`testing.md`](testing.md). Review 2 (D1) replaced the planning-stage
spec that stood here. That spec put the marker in the private home and in the proxy's root, opened
the whole portal name, used `--new-session`, and expected the portal file chooser to hand files over.
None of those are built, for the reasons in R17.6.1, R17.6.3 and the review rounds.

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

Run it on **real hardware with a logged-in desktop**, on the environments R1.1 claims a sandbox on
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
| A-support | AppKata's sandbox can run here (setup done, no conflict with the system's own profile) | R17.10, R17.10.2 |
| ISO-keys, ISO-home | a sandboxed app can't read the home's keys; its writes land in its private home | R17.2, R17.3.1 |
| ISO-net, ISO-net-on | Strict has no network; Online app has it | R17.2 |
| D-theme | the desktop's themes are visible, read-only | R17.4 |
| P-filter, P-portal | the bus filter refuses `systemd1`; the portal answers through it | R17.5 |
| P-handover | a file given as an argument reaches the app (document portal) | R17.6.2 |
| INNER | whether an app's own sandbox can run inside AppKata's here, and the launcher agrees | R17.10.2 |
| D-wayland / D-x11 | screen capture from a sandbox, and the session warning saying so where it works | R17.9 |
| D-sound, D-nosound | a sound grant reaches the sound server; no grant, no server | R17.8 |
| D-gpu | the OpenGL renderer inside | R17.4 |
| T-cli, T-cli-home | a command-line tool works in its folder; run from the home, it gets its private home and says why | R17.3.3 |
| EXP-strict, EXP-online-app | everything a Strict and an Online app see of this desktop is listed in [A2](architecture/A2-sandbox-exposure.md), each row stated by a requirement | R17.4, R17.17 |
| GUI-run (`--app`) | a real app installed by AppKata starts from its launcher and keeps running | R17.4 |

### What it asks the tester

- **A1-prompt.** Where the setup is needed, before the setup, installing a first AppImage asks "Set
  up the sandbox?"; Not now installs it unsandboxed, and a second install doesn't ask (R17.10).
- **A1-pkexec.** Where the setup is needed, Settings → Sandbox → Set up… shows one password prompt,
  then "Ready". Where the system has a bwrap profile of its own no setup is needed, and Repair…
  appears only if AppKata's old profile sits beside it (R17.10.2).

The setup is needed where the kernel restricts unprivileged user namespaces and the system has no
bwrap profile of its own (R17.10); which of the tested systems that is, [`testing.md`](testing.md)
says ("What each environment boots with"). The field test asks the A1 questions only where it finds
that so, and records them N/A elsewhere.
- **P-dialog.** A sandboxed app's own file dialog shows its private home and its granted folders, and
  nothing else of the home (R17.6.3).
- **P-openwith.** "Open with", or a drop on its menu entry, of a file outside its folders opens that
  file (R17.6.2).
- **T-tray / T-mpris.** The messenger template's tray icon and notifications; the media player's
  media keys (R17.5.1).
- **U-selfupd.** An app that updates itself, sandboxed: AppKata offers its updates, and the app copes
  with its own updater failing (R17.12).
- **U-enable.** Switching an installed app from Off to a sandbox says, before Save, that it starts
  with fresh settings (R17.13).
- **E-native.** A password manager's browser integration (native messaging) still works.
