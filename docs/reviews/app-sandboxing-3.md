# App sandboxing — review 3: harnesses for the classes, and what they catch

Review 3 doesn't read the code for bugs. It builds the class harnesses that review 2 named, so
each bug class has one place that covers it whole. Each harness is built the way the owner asked
on 2026-10-17:

1. **Step back from a bug and ask how it slipped past:** what the existing tests looked at instead.
2. **Classify it.**
3. **Build a harness that covers the whole class**, not just the one bug.
4. **Run it and report what else it catches**, the originating bug included.

Each harness is its own commit, pushed as it lands. Its catches are findings here, numbered R3-n.
Catches that are still open stay in an explicit list inside the harness's test, so the suite stays
green and the list has to shrink as fixes land. Nothing here is fixed inside a harness commit: the
owner sees the catches first.

The order, from review 2's recommendation:

1. B, requirements traceability.
2. The lifecycle state machine.
3. The exposure inventory.
4. One fact, one function (including H, the warning from the compositor's globals).
5. Surface parity.
6. User-shaped arguments, and personas.

Then the extensions to the harnesses already built: the two-apps keyspace, the docs' facts, and
the platform matrix.

## Results

Each pass of this review: when it ran, what it found, when and where it was fixed, and the tiers at
its end. The commits, one per finding, are in the section the last column names; each finding's
heading says "fixed" or "closed" once it is.

| Pass | Ran | Found | Fixed | Tiers at the end | Recorded in |
|---|---|---|---|---|---|
| The harnesses B, 2 to 6, E1 to E3 | 2026-10-17/18, ae87060..eb1c4cd | R3-1 to R3-20: one HIGH (R3-6), five LOW–MEDIUM | 2026-10-18, 7b2fbc8..4e4f330, after the owner's five decisions | tier 1 2,201; the launcher tiers 123 to 126 | "Harnesses"; "Decisions"; "Fixes" |
| What review 2 left open | 2026-10-18/19 | R3-21, by the Debian 12 tier | 2026-10-18/19, e8f7697..1f5d909, after the owner's nine decisions | tier 1 2,392; the launcher tiers 124 to 127 | "The second pass" |
| R3-21, and Python 3.14 | 2026-10-19 | R3-22 (LOW), R3-23 (LOW–MEDIUM), three more by R3-22's check | 2026-10-19, df47af4..8f8d075; R3-21 closed by the owner's decision | tier 1 2,391; the launcher tiers 124 to 127; Windows 161 | "After the second pass" |
| The tour and the AppImage: E4 to E9 | 2026-10-24 | R3-24 to R3-32: one HIGH (R3-32) | 2026-10-24, e6ba49d..7e45d2b, after a walk thru | tier 1 2,427; the Linux tour 87 screens, Windows 74 | "R3-24 to R3-32" |
| The six environments | 2026-10-24 | — (the owner's lock-in) | 2026-10-24, 4500eeb, 09aaf61, ec0be4b | tier 1 2,428; `launcher`, `launcher-lmde7` 128; the Ubuntu VMs 124 | "The test environments, locked in" |
| The desktop VMs | 2026-10-24 | R3-33 to R3-36 | 2026-10-24, 1b18487..c5f0c40, option A each | tier 1 2,429; `launcher`, `launcher-lmde7` 130; the Ubuntu VMs 125; the Mint 22.3 and LMDE 7 VMs 126 | "The desktop VMs" |
| The manual-testing docs: E10, E11 | 2026-10-24 | R3-37, R3-38 (LOW) | 2026-10-24, a93909a and cc2cc8e, after a walk thru (R3-37 option B, R3-38 option A); the harnesses 72e9fa2, 9185331 | tier 1 2,438; the Ubuntu VMs 128; the Mint 22.3 and LMDE 7 VMs 129 | "The manual-testing docs: R3-37 and R3-38" |

Nothing of review 3 is open (2026-10-24).

## Harnesses

| # | Harness | Class | Commit | Originating bug, shown | Caught besides |
|---|---|---|---|---|---|
| B | `docs/requirements-trace.md` + `tests/test_requirements_trace.py` | a decision recorded but never built | ae87060 | 17.12's "Disable the app's own updater" (review 2, F3): run against the requirements before 7d639f6, its sentence names no test | R3-1 to R3-5 below; the two unwired slots of R2-F11 and R2-F12 |
| 2 | `tests/test_sandbox_lifecycle.py` | rules no single transition shows | 4880dd1 | R4-3 and round two's R1, each re-introduced; the harness flags them ("shown is what runs", "a re-save changes nothing") | R3-6 (HIGH); R2-F11, F12, F16; a second road to R2-F13 (Install options) |

| 3 | `docs/sandbox-exposure.md`, `scripts/sandbox/exposure.py`, `tests/test_sandbox_exposure.py`; the field test's EXP check | the sandbox shows something nobody listed | 1c2c005 | F18: with its rows taken out, tier 1 flags the five `/sys` binds and a run flags the MAC addresses. Also re-introduced and flagged: an agent socket passed into the environment, round three's R3-1 (the desktop entries back in view), the runtime folder bound whole | R3-7 to R3-12 |

| 4 | `tests/test_sandbox_one_fact.py` | one fact decided in two places; with H, a name standing in for behaviour | 58e8d3b | F7: Budgie:GNOME and Phosh:GNOME, run against the compositors' globals. Also re-introduced and flagged: round seven's R7-1 (KDE on the allowlist) and round one's `$cwd` bind with no rule | R3-13; R2-F12 again, from the support status |

| 5 | `tests/test_sandbox_surfaces.py` | a surface narrower than the grant set it shows | 04551d2 | F9, F10 and F11, each found on its first run. Also re-introduced and flagged: round three's R3-2 (a Strict set's folder shown, never bound) and a chip dropped | R3-14, R3-15 |

| 6 | `tests/test_sandbox_user_shaped.py` | a corpus drawn from the tester instead of from users | 171ece2 | F6 (four shapes of it) and F15 (four personas), each found on its first run. Also re-introduced and flagged: round two's R7 (no hand-over at all) and a variable dropped from the allow-list | R3-16, R3-17, R3-18 |

| E1 | `tests/test_sandbox_two_apps.py`: the keyspace | (class G, extended) a key that outlives or outreaches what it names | 626ffd2 | F14, found on its first run: both "Notes" apps append to `apps/Notes.log`. Also re-introduced and flagged: round six's R6-1 (one id for both) | — |

| E2 | `tests/test_docs_facts.py` | (class F, extended) a fact copied into prose that the code outgrew | b115780 | review 2's nits (13 facts) and D2 (6), each found on its first run. Also re-introduced and flagged: a template added without the documents (the nits' own origin) | R3-19 |

| E3 | `tests/test_platform_matrix.py`; `scripts/test-sandbox.sh launcher-rocky9` | (class D, extended) the tiers chosen from the tester's own family | eb1c4cd | F17: derived from 1.1, Debian 12, Fedora 39 and arm64 have no tier. RHEL, AlmaLinux and Rocky 9 now have one. Also re-introduced and flagged: the Rocky tier taken out again | R3-20; R3-8 on RHEL 9 too |

| E4 | `scripts/demo_data.py check` (`PROMISES`, run before each tour) + `tests/test_demo_promises.py` | a staged demo state that drifts: with time, with a sync, or from one platform to the other | e6ba49d | R3-24: on the demo data of 2026-10-09 it flags A01's held update on both platforms and the sync times every screen shows | R3-25, R3-26 |
| E5 | `RULES` in `src/appkata/tour.py`, checked on every screen the tour takes + `tests/test_tour_rules.py` | a state staged, or reached, through one reader of a fact and not the others: a screen that contradicts itself | 50a941b | R3-27: on the code of 70b6423 the test finds four breaks, and the Linux tour flags Syncthing from A01 on | — |
| E6 | `tourKeys` in Main.qml, checked by the tour on every screen (`STILL_UNREAD`) + `tests/test_tour_rules.py` | a setting a tour step makes that nothing applies | 54121bb | R3-28: U02's `auditFilter`, read nowhere; a review's settings with no review, re-introduced on A19, named key by key | — |
| E7 | `tests/test_time_shown.py` | a text worked out from the current time with nothing that works it out again as time passes | 60f868f | R3-29: `Theme.ago`, read once by the header (X01: "Synced 50 min ago" beside "Last synced 52 min ago") | the Audit's day labels |
| E8 | `scripts/test-windows-vm.sh`: the VM's clock against this machine's, before staging | the tour machine's clock differs from the clock the data was staged by | a5370c3 | R3-30: the VM 25,177 s ahead | — |
| E9 | `scripts/appimage_host_libs.py` (with `scripts/appimage_probe.sh`) and `scripts/appimage_desktop.sh`, run by `scripts/test-appimage.sh`; `tests/test_appimage_host_libs.py` | a library the AppImage takes from the host that no requirement names and no tier shows present; the release run only headless, so what a desktop session loads is never loaded | 5249653 | R3-31: 45 host libraries, none named; R3-32: X11 fails on 7 of 9 desktops | — |

**How harness 2's class slipped past.** Every earlier test drove one transition at a time and checked
its result. Nothing held the rules that must survive any order of transitions. The harness runs
120 seeded random walks of ten steps against the real Backend, on a fake host whose sandbox support
changes between steps. The steps: choose a template, Off, a custom folder, "Use theirs", Install
options (re-save, or with a sandbox), update, heal, setup, repair, a review changing upstream, and
the host changing state. Eight invariants are checked after every step:

| Invariant | Shortest walk that breaks it | Kept open by |
|---|---|---|
| never unsandboxed without the user choosing Off | host → conflict, update | R2-F16 |
| what the UI shows is what runs | — | holds |
| Strict runs sandboxed whenever bwrap works | (a ten-step walk ending on a bwrap-only host) | R2-F12 |
| the user is told when a sandbox starts | Off, then Install options with a sandbox | R2-F13 (a second road: Install options says nothing at all) |
| every grant change is audited with what changed | a custom folder | R2-F11 |
| only the user changes what runs (decision 5) | — | holds |
| re-saving Install options changes nothing | — | holds |
| AppKata itself never runs sandboxed | one heal | **R3-6** |

**How harness 3's class slipped past.** Every test of what a sandboxed app can reach asked about one
thing the tester thought of: `~/.ssh`, `~/.bashrc`, the real bus, the desktop entries, the X
server's abstract socket. None listed what is in view. So a bind nobody thought to ask about stood
unrecorded: `/sys`, for GPU identification (F18). The harness turns the question round.
`docs/sandbox-exposure.md` lists everything a launcher shows, with the condition each row is seen
under and the sentence of 17 that states it, or the finding that keeps it unstated. The harness
fails on anything seen that no row lists for that run, and on a row that should be seen and isn't.
It runs in three places:

- **Tier 1.** Every template's launcher, run against a stand-in bwrap that records its words.
- **Tier 2.** The probe runs inside real launchers in every `launcher` harness. It reads the mount
  table, the environment, `/dev`, sockets, the machine's identifiers, network interfaces, abstract
  sockets and other processes.
- **The field test**, on a real desktop.

It also checks 17.2's Strict row against the Strict launcher, since 17.2.1 says that row is the whole
story.

Harness 3 runs clean in every tier, with the open rows listed in the inventory:

| Tier | Result |
|---|---|
| tier 1 | 2,131 passed |
| `launcher` (Mint 22.1) | 109 passed |
| `launcher-21` (Mint 21.3) | 108 passed |
| `launcher-25` (Ubuntu 25.04) | 109 passed |
| `launcher-vm` (Ubuntu 24.04) | 109 passed |
| `launcher-vm26` (Ubuntu 26.04) | 109 passed |

**How harness 4's class slipped past.** Which display a sandboxed app gets is decided twice:

- the launcher gives the Wayland socket when `$WAYLAND_DISPLAY` names one;
- the session warning asks `$XDG_SESSION_TYPE`, then judges the compositor by the desktop's *name*.

Each was tested alone, on inputs its own author picked. The warning's test always set
`XDG_SESSION_TYPE=wayland`, and it took "GNOME" anywhere in the name to mean GNOME's compositor
(F7). The harness takes each fact that two places decide and runs every decider over one corpus,
against the truth where there is one:

| Fact | Decided by | Truth | Result |
|---|---|---|---|
| the display the app gets, and what it leaks | the launcher; `session_warning()` | the launcher's own words, and the globals the compositor offers. Run: sway 1.9, mutter 46, kwin 5.27 and 6.3. Read: labwc, phoc | 5 of 15 sessions wrong: Budgie and Phosh (F7); sway and Hyprland started from a TTY (R3-13) |
| the warning's wording | the X11 warning's advice; the tour's copy | the same | both wrong (F7) |
| whether a folder may be shared | the launcher's shell rule for the CLI tool's folder (17.3.3); `protected_folder()` for grants (17.3.1) | 17.3.1 | they agree on 28 folders: links, spaces, globs, the runtime folder, a secret |
| whether the app brings Chromium's sandbox | the launcher's shell test; App Detail's `_brings_own_sandbox` | — | they agree on 6 layouts |
| whether this machine can sandbox an app | `support_status()`; each level's launcher (tier 2) | the launcher, run | Strict runs without xdg-dbus-proxy, but nothing is sandboxed (F12) |
| whether the app has the network | the identity marker; the launcher | — | `tests/test_sandbox_properties.py` already holds this |

That sway gives its clients `WAYLAND_DISPLAY`, `DISPLAY` and `SWAYSOCK` and nothing else is a run
(sway 1.9, headless, in the session image). That a console login's `XDG_SESSION_TYPE` is logind's
`tty` is read.

Harness 4 runs in every tier:

| Tier | Result |
|---|---|
| tier 1 | 2,137 passed |
| `launcher` (Mint 22.1) | 114 passed |
| `launcher-21` (Mint 21.3) | 113 passed |
| `launcher-25` (Ubuntu 25.04) | 114 passed |
| `launcher-vm` (Ubuntu 24.04) | 114 passed |
| `launcher-vm26` (Ubuntu 26.04) | the support check passes |

On 26.04 a dangling link in `/usr/bin` first broke the test's own PATH copy; it now uses
`lexists`.

**How harness 5's class slipped past.** Each surface was tested on what it shows. The chips were
tested label by label, the Audit for writing an entry, the review lines for parsing, the dialog for
the switches it has. None was asked whether it can say everything a grant set can. The harness
takes the launcher as the truth and makes every one-step change of a grant set, from a bespoke
Standard set and from Strict. Wherever the launcher changes, each surface must tell the change
apart. Wherever it doesn't, the chips must show no difference either. The dialog is driven through
its own controls: every enabled switch, the folder picker, the remove buttons and the template list.

| Change that runs differently | Chips | Audit | One review | Dialog |
|---|---|---|---|---|
| Strict ↔ Standard | yes | yes | yes | yes |
| a folder read-write, or none | yes | F11 | yes | yes |
| a folder read-only, or read-only instead | yes | F11 | yes | F10 |
| no network | yes | F11 | yes | yes |
| sound (play or record bind the same sockets) | yes | F11 | yes | yes |
| the camera | yes | F11 | F9 | yes |
| no X11 apps | **R3-15** | F11 | F9 | yes |
| no notifications | yes | F11 | yes (`developer`) | **R3-14** |
| tray, media keys, screen awake, passwords, password service | yes | F11 | F9 | yes |
| can change its own files | yes | F11 | F9 | yes |

Execute-deny and ports change nothing that runs (Landlock is deferred, 17.18), and no surface shows
them as protection. A review the user writes carries no sandbox lines at all (F9). Harness 5 is
tier 1: 7 passed.

**How harness 6's class slipped past.** The corpus was the tester's own habits. The file-argument
tests passed absolute paths and `file://` URIs, from the home folder. Every sandbox test ran as one
person: English, no screen reader, no input method, no proxy, default formats. The harness has two
parts.

**Part one: arguments.** Sixteen arguments, shaped the way users shape them:

- from a shell: relative paths, `.`, `..`, and options carrying their values;
- from a desktop entry's `%U`: URIs, including an encoded space;
- from a file manager: links, and linked folders;
- from intent: a folder, or a file still to be made.

Each is given to a Standard app with `~/Docs` granted, with the real document portal (tier 2). The
check is whether the app reaches what the user meant:

| Argument | Reaches it |
|---|---|
| an absolute path, in a granted folder or outside one | yes |
| a relative path from elsewhere; a `file://` URI, plain or with an encoded space; spaces and accents | yes |
| a relative path, `./`, `../` or `.` from a granted folder | F6 |
| `--file=/path`, `-o/path` | **R3-16** |
| a folder outside the granted folders; a file still to be made | **R3-16** |
| a link on the desktop to a file in a granted folder; a path through a linked folder | **R3-17** |

**Part two: personas.** Eight users whose session carries what the tester's doesn't. Through the
launcher's own words (tier 1), the harness checks which of each persona's variables, sockets and bus
names reach the app:

| Persona | Gets what it needs |
|---|---|
| a German user | yes |
| a developer with an SSH agent and a keyring | yes: neither reaches the app, as 17.3.1 means |
| regional formats unlike the language | F15: eight `LC_*` variables stop |
| behind a proxy | F15 |
| Chinese or Japanese input (IBus) | F15: the variables and the IBus portal |
| a screen-reader user | F15: no AT-SPI socket and no `org.a11y.Bus` |
| another time zone (`TZ`) | **R3-18** |
| HiDPI on Plasma's X11 session | **R3-18**: `QT_SCREEN_SCALE_FACTORS` and `QT_AUTO_SCREEN_SCALE_FACTOR` stop (`GDK_SCALE` and `XCURSOR_SIZE` pass) |

Harness 6 runs in every tier:

| Tier | Result |
|---|---|
| tier 1 | 2,146 passed |
| `launcher` (Mint 22.1) | 118 passed |
| `launcher-21` (Mint 21.3) | 117 passed |
| `launcher-25` (Ubuntu 25.04) | 118 passed |
| `launcher-vm` (Ubuntu 24.04) | 118 passed |
| `launcher-vm26` (Ubuntu 26.04) | 118 passed |

**How E1's class slipped past.** Round six's two-apps tests, and review 2's sequences, compare
snapshots of what an install writes. That snapshot leaves the logs out (the transitions tests skip
`.log` files), and nothing in those tests started an app. F14 sat exactly there. The extension
snapshots everything but the database while each of two same-named apps is used as a user would use
it: started from the app menu (its launcher writes its log), its sandbox changed, its launcher
rewritten. It fails on any file both apps write, and on any file the second writes without its own
id in the path. Its only catch is F14.

**How E2's class slipped past.** Review 2's nits and D2 were all facts copied into prose that the
code later outgrew: seven templates, four review rounds, "Planned", "process 2 (or 3)", "(4.5)".
Class F's docs test caught retired identifiers in the documents §17 delegates to, but nothing
compared a stated fact with the code that decides it. E2 lists 23 such facts, each with where a
document states it and how the code decides it. They come from the requirements, `gaps.md`, the
README, `app-sandboxing.md`, the proxy test plan and the Settings dialog: template counts and
lists, portal interfaces, capabilities, the tray's process ids, the order of 17's sub-sections, a
cross-reference, the Settings groups, the Audit's entries, and statuses. 20 are wrong today. 19 of
those are review 2's nits and D2, and one is new (R3-19). The portal interfaces, the capabilities
in 17.5.1 and the proxy test plan's capability table are right.

**How E3's class slipped past.** The launcher tiers came from the family the tester uses, Mint and
Ubuntu. 17.1 then called their ends "both ends of what the supported platforms ship", but 1.1 also
supports Debian, Fedora, RHEL and its rebuilds, and arm64. E3 derives the claimed platforms from 1.1
and the tiers from `scripts/test-sandbox.sh`. It fails when a claimed platform has neither a tier
nor an entry in its list of untested ones. It adds the cheapest missing tier, `launcher-rocky9`:
RHEL, AlmaLinux and Rocky Linux 9, which ship bwrap 0.6.3, xdg-desktop-portal 1.12.6, GLib 2.68.4
and dbus 1.12.20. That is an older portal and GLib than any other tier. Every launcher test file
runs there, on python3.11, since the system's python3 is 3.9. The launcher's helpers use the
system python3 with its gi, as on a real RHEL 9 machine.

The Rocky tier passes 118 tests, the same as the Mint 22.1 tier. On its first run, the field test's
exposure check found one difference: R3-20. Its exposure run also reports "a dbus-launch bus here
is abstract", so R3-8 reaches RHEL 9 too. A second E3 check runs in each container tier: the
variables `/bin/sh` adds by itself to an empty environment, which the launcher would pass on.

After E3:

| Tier | Result |
|---|---|
| tier 1 | 2,154 passed |
| `launcher` (Mint 22.1) | 121 passed |
| `launcher-21` (Mint 21.3) | 120 passed |
| `launcher-25` (Ubuntu 25.04) | 121 passed |
| `launcher-rocky9` (Rocky Linux 9) | 121 passed |
| `launcher-vm` (Ubuntu 24.04) | 118 passed |
| `launcher-vm26` (Ubuntu 26.04) | 118 passed |

The VMs run every file but the platform test, which reads the harness script that the VMs aren't
sent.

## Where this stood on 2026-10-19

The state after each pass up to 2026-10-19, as it was written then; Results, at the top, is
current. All six harnesses and the three extensions are built, one commit each, and every tier passes with
each harness's open list as it is. Every open item of review 2 now sits in some harness's list:
F6, F7, F9 to F18, the nits and D2. Each list shrinks as fixes land, and a fixed item left on its
list fails the suite. The harnesses found 20 new findings:

| Severity | Findings |
|---|---|
| HIGH | **R3-6**: AppKata sandboxes itself, Strict with no network |
| LOW–MEDIUM | R3-2 (App Detail, Settings → Sandbox and the uninstall dialog driven by no test), R3-8 (the network grant reaches every abstract socket, an abstract session bus included on dbus 1.12: Mint 21.3, RHEL 9), R3-13 (a compositor started from a TTY gets no warning), R3-16 (an option's value, a folder or a file still to be made isn't handed over), R3-17 (a link to a granted file is passed by a path the app can't see) |
| LOW | R3-1, R3-3, R3-4 (test gaps); R3-5, R3-9, R3-10, R3-19 (wording); R3-7, R3-18 (unstated exposure, settings that stop at the sandbox); R3-11 (the field test's later Strict checks run Online app); R3-12 (a long id can't start at Standard); R3-14, R3-15 (a missing switch, a missing chip); R3-20 (`TERM=dumb` where `/bin/sh` is bash) |

**The fix pass (2026-10-18)** followed this order, after the owner's five decisions (Decisions,
below), one commit each (Fixes, below). All twenty findings are fixed. Review 2's F6, F7, F15 and F18,
F17's claim, the nits (all but three UI ones) and D2 were fixed alongside. Still open from review 2:
F9, F10, F11, F12, F13, F14 and F16, three UI nits (the review badge's wording, the widened-Strict
blurb, the orphaned home on uninstall), and tiers for Debian 12, Fedora 39 and arm64. Each is still
in its harness's list. The tiers at the end:

| Tier | Result |
|---|---|
| tier 1 | 2,201 passed |
| `launcher` (Mint 22.1) | 126 passed |
| `launcher-21` (Mint 21.3) | 125 passed |
| `launcher-25` (Ubuntu 25.04) | 126 passed |
| `launcher-rocky9` (Rocky Linux 9) | 126 passed |
| `launcher-vm` (Ubuntu 24.04) | 123 passed |
| `launcher-vm26` (Ubuntu 26.04) | 123 passed |
| `wayland`, `kwin`, `kwin6`, `inputmethod`, `consumers`, `filedialogs` | `EXPECTED: ok` |

**The second pass (2026-10-18/19)** took what review 2 left open, after the owner's nine decisions
(the second table under Decisions), one commit each ("The second pass", under Fixes): F12 (bwrap
alone is enough, and the first-need prompt), F16, F13, F14, F10, F9, F11, the three UI nits, and
F17's tiers, with arm64 made a later target. Nothing of review 2 is open. Every harness's open list
is empty but for what the owner decided (harness 5: the secrets class a review can never grant;
harness 6: the screen reader and a file still to be made, both deferred to 17.18), and the
requirements trace has no open rows.
Found along the way and fixed: the install card's one-letter chips, three template counts E2 never
read (it reads every one now), E2's blind spot for an actor passed by name, and the tour's leaks of
the machine running it. Found by the new Debian 12 tier: **R3-21**, closed since by the owner's
decision (below).
The tiers at the end (9ead7b8):

| Tier | Result |
|---|---|
| tier 1 | 2,392 passed |
| `launcher` (Mint 22.1) | 127 passed |
| `launcher-21` (Mint 21.3) | 126 passed |
| `launcher-25` (Ubuntu 25.04) | 127 passed |
| `launcher-rocky9` (Rocky Linux 9) | 127 passed |
| `launcher-debian12` (Debian 12) | 125 passed, 2 expected failures (R3-21) |
| `launcher-fedora39` (Fedora 39) | 127 passed |
| `launcher-fedora44` (Fedora 44) | 127 passed |
| `launcher-vm` (Ubuntu 24.04) | 124 passed |
| `launcher-vm26` (Ubuntu 26.04) | 124 passed |
| `wayland`, `kwin`, `kwin6`, `inputmethod`, `consumers`, `filedialogs`, `filedialogs-qt68` | `EXPECTED: ok` |

**After the second pass (2026-10-19).** The owner closed R3-21 by deciding that AppKata's code runs
only on the Python a release carries (R3-21, below). Then the owner asked to try Python 3.14 with
PySide6 6.11 and keep them if everything worked. Everything did, so every release now carries 3.14
and 6.11.2 ("After the second pass", under Fixes). Along the way, the Windows test suite ran in full
for the first time. The Windows build was also found to drop Qt's plugins without failing. Both are
fixed. Found and fixed: **R3-22** (LOW, older than this branch): on Windows, a row of Install
options ran out of its card. Also **R3-23** (LOW–MEDIUM): when the API's hour runs out, the
pages path counted bare tags as releases. Its harness, a layout check on every tour screen, found three more,
all fixed. The owner then made Windows 10 22H2, fully updated, the only Windows
10 target, and Setup refuses an older one (Decisions). The tiers at the end, on Python 3.14.8 and PySide6 6.11.2 (the
launcher tiers and verdict harnesses ran before cc096bb, which only skips tests off Linux):

| Tier | Result |
|---|---|
| tier 1 (`scripts/test-tier1.sh`, an Ubuntu 24.04 container) | 2,391 passed |
| `launcher` (Mint 22.1) | 127 passed |
| `launcher-21` (Mint 21.3) | 126 passed |
| `launcher-25` (Ubuntu 25.04) | 127 passed |
| `launcher-rocky9` (Rocky Linux 9) | 127 passed |
| `launcher-debian12` (Debian 12) | 127 passed |
| `launcher-fedora39` (Fedora 39) | 127 passed |
| `launcher-fedora44` (Fedora 44) | 127 passed |
| `launcher-vm` (Ubuntu 24.04) | 124 passed |
| `launcher-vm26` (Ubuntu 26.04) | 124 passed |
| `wayland`, `kwin`, `kwin6`, `inputmethod`, `consumers`, `filedialogs`, `filedialogs-qt68` | `EXPECTED: ok` |
| the AppImage (`scripts/test-appimage.sh`) | passes on Mint 21.3 and 22.1; starts and renders on Rocky 9, Debian 12, Fedora 39 and 44 |
| the Windows 10 22H2 VM | the suite 161 passed; the installer installs, starts, runs the 93-screen tour and uninstalls |

**The order of fixes it recommended** (followed in the fix pass of 2026-10-18), each in its own commit with the harness that caught it showing the
fix:

1. **R3-6.** Exclude AppKata from sandboxing wherever a sandbox is resolved, healed or baked, and
   say so in 17.1. Harness 2's "AppKata itself never runs sandboxed" then holds and leaves its list.
2. **R3-8.** Warn when the session bus is abstract and an app has the network grant (an owner
   decision: a warning, or something stronger).
3. **R3-13 with F7.** Decide the warning from what the launcher gives, then from the compositor's
   globals. Harness 4's table is ready to check both.
4. **R3-17, R3-16 and F6.** One rework of the file-argument helper and the working directory. How
   far R3-16 goes, folders and files still to be made, is an owner decision.
5. **R3-12 and R3-11.** The socket's name; the field test's own launcher reuse.
6. **The wording.** R3-5, R3-9, R3-10, R3-19, the nits and D2, in one pass, which shrinks E2's list.
7. **The UI.** R3-14, R3-15, then F9 to F11.
8. **The environment.** R3-7, R3-18, R3-20 and F15: for each, pass it through or state it as a
   limit. These are owner decisions, one at a time.
9. **The test gaps.** R3-1 to R3-4.

## Findings

### R3-1. 17.1's scope is shown by no test — LOW (test gap; found by B)

**Status: fixed** (see Fixes).

17.1 says only AppImages and tarballs, on Linux, get a sandbox. `_resolved_sandbox()` returns `None`
for anything else, and the UI then shows no Sandbox section, but no test ever asks for a .deb, a
Flatpak or a Windows install.

### R3-2. App Detail, Settings → Sandbox and the uninstall dialog's sandbox parts are driven by no test — LOW–MEDIUM (test gap; found by B)

**Status: fixed** (see Fixes).

Round four's dialog contract harness drove the Sandbox and Install dialogs as QML against the real
Backend. It never drove App Detail (`AppDetail.qml`), Settings → Sandbox (`SettingsDialog.qml`) or
the uninstall confirmation (`ConfirmDialog.qml`). Those three are where 17 tells the user most
things:

- in App Detail: the review badge and "Keep mine", the setup-needed and Repair banners, the
  "Sandboxed"/"Not sandboxed" pill, the session caveat, the Chromium line (17.10.2) and the
  sandboxed-updates line (17.12);
- in Settings: System support with Set up… and Repair…, the defaults, the built-in templates list
  and the home folders (17.15);
- in the uninstall dialog: the "Also delete its sandbox home folder" offer (17.14).

Eleven rows of the trace are open on this. It is the surface where review 2's F12 (a prompt that
doesn't exist) and F13 (a warning only after the fact) could go unseen.

### R3-3. `Backend.planFor`'s Sandbox card is never computed by a test — LOW (test gap; found by B)

**Status: fixed** (see Fixes).

The install-dialog contract tests build the plan by hand (`tests/test_dialog_contract.py::_plan`)
from `sandboxInfo()`. So what `planFor()` itself computes for the card goes untested: the
extraction cost (17.7's "shown in the install options"), F4's `byKind` and `kind`, and F8's
`suggestsOff`. A wrong key there would show the dialog something the tests never saw.

### R3-4. "A home with no owner recorded counts as another app's" is untested — LOW (test gap; found by B)

**Status: fixed** (see Fixes).

17.6 and `sandbox.home_belongs_to_another()` treat an ownerless home, one made before F19, as
taken. No test makes one.

### R3-5. 17.3's table says Strict has no devices; every template, Strict included, has the X11 grant — LOW (wording; found by B, review 2's nit)

**Status: fixed** (see Fixes).

17.2.1 and 17.9 say the X11 device grant applies at every level and is on in every template, and
`TEMPLATES["strict"]` has `devices={"x11"}`. The table's "Devices: no" for Strict should say "X11
only".

### R3-6. AppKata sandboxes itself: the heal pass gives its own install a Strict launcher, with no network — HIGH (functional; found by harness 2)

**Status: fixed** (see Fixes). AppKata's own install is never sandboxed, and a start removes a
launcher an older AppKata gave it. 17.1 says so.

**What happens.** Run as an AppImage, AppKata adopts its own file as installed (`_ensure_self`,
2.11): a record with `current` and `target`, of kind AppImage. Nothing excludes that record from
sandboxing:

- `_resolved_sandbox()` gives AppKata, an unreviewed GUI app, `strict`;
- `_heal_launchers()` sees no launcher and writes one;
- `_activate()` then points AppKata's `exec` at it, adds an "AppKata" menu entry whose `Exec=` is
  that launcher, and points the command link `appkata` at it.

Once AppKata is self-installed (2.11.3.1), its autostart entry and `appkata://` handler follow that
`exec` too (`desktop.LAUNCH_OVERRIDE`). An update of AppKata from AppKata bakes the same grant set.

**Evidence (run).** A real Backend with `APPIMAGE` set and sandboxing available:
`_resolved_sandbox(APPKATA_REPO)` gives `strict`. `_heal_launchers()` returns AppKata's URL. Its
`exec` becomes `~/bin/apps/appkata/run`, baked Strict with `network: False`, and
`appkata-appkata.desktop` runs that launcher. Started that way, AppKata has no network, cannot write
the install folder and cannot run package managers: it can neither sync nor install.

**How it slipped past.** No test ran the heal pass, or any sandbox resolution, with AppKata's own
install present. The fixtures never set `APPIMAGE`, and 17.1's scope ("the two portable kinds
AppKata installs itself") never says AppKata itself is out. The class: AppKata is one of its own
apps.

**Which is right.** Neither as written. AppKata needs the host: it installs apps, runs pkexec and
package managers, and writes the install folder. Requirement 17.1 should exclude AppKata itself, and
the code should skip it wherever a sandbox is resolved, healed or baked. The lifecycle harness keeps
this as an invariant, "AppKata itself never runs sandboxed".

### R3-7. Every app reads the machine's identifiers (machine-id, boot id, host name), and no requirement says so — LOW (unstated exposure; found by harness 3; run)

**Status: fixed as decided** (see Fixes).

A Strict app reads three identifiers, each equal to the host's in every tier-2 run (Mint 22.1,
Mint 21.3, Ubuntu 25.04):

- `/etc/machine-id`, because all of `/etc` is bound;
- `/proc/sys/kernel/random/boot_id`, which is global, so the sandbox's own `/proc` doesn't change
  it;
- the host name. The UTS namespace is new, but bwrap keeps the name.

Together with F18's values from `/sys` (MAC addresses, USB serials, the hardware model), any app can
recognise the machine, and a networked one can report it. 17.4 says "/etc read-only", which hides the
machine-id inside a folder name. 17.17 names none of them.

**How it slipped past.** As F18: nothing listed what is in view.

**Which is right.** The requirement is incomplete. The machine-id can't just be hidden: libdbus
aborts when it can't read one ("failed to read machine uuid"). **Recommend:** state all of these in
17.17 with F18's. Possible later steps: a stable machine-id per app, which libdbus accepts but which
doesn't link one app's runs to another's; and a generic host name through bwrap's `--hostname`.

### R3-8. The network grant shares every abstract socket on the host, not only the X server's; on dbus 1.12 that includes a session bus started by dbus-launch or dbus-run-session, unfiltered — LOW–MEDIUM (unstated exposure; found by harness 3; run)

**Status: fixed as decided** (see Fixes): stated in 17.9 and 17.17, warned about in Settings →
Sandbox and App Detail, a network of an app's own in 17.18.

**What happens.** `--share-net` shares the host's network namespace, and abstract-namespace sockets
belong to it. `/proc/net/unix` lists them, so an app needn't guess their names. 17.9 states this
for the X server alone.

**Evidence (run).** On Mint 21.3 (dbus 1.12.20), a bus started the way dbus-launch starts one
listens on `unix:abstract=/tmp/dbus-dEHzKN2rsb`. A sandboxed `online-app` found it in
`/proc/net/unix` and called it: `ListNames` returned `(['org.freedesktop.DBus', ':1.0'],)`. An
`offline-editor` (no network) found nothing. On Mint 22.1 (dbus 1.14.10) and Ubuntu 25.04 (1.16.2),
the same bus listens on a path in `/tmp`, which the sandbox's own `/tmp` hides. Rocky Linux 9
(dbus 1.12.20, E3's tier) is abstract like Mint 21.3. The tier-2 run checks
this on each distro ("a dbus-launch bus here is abstract / a path").

**When it matters.** The desktop's own session bus is systemd's user bus (`/run/user/<uid>/bus`, a
path) wherever dbus-user-session is installed, as on stock Mint 21.3, where PipeWire and the portal
pull it in. A session started with `dbus-run-session` or `dbus-launch` gets a bus of its own. On
dbus 1.12 (Mint 21.3, Ubuntu 22.04) that bus is abstract. The common case is sway started from a TTY
with `dbus-run-session sway`. There, an app given the network reaches the unfiltered session bus,
which 17.5 says must always be filtered. The same applies to any other abstract socket a host
program listens on.

**How it slipped past.** Round four's R4-8 test checked the X server's abstract socket as one fact,
not abstract sockets as a class. The containers had no other abstract socket to find.

**Which is right.** The requirement is incomplete. For an abstract session bus, the code should act.
**Recommend:**

- state the general case in 17.9 and 17.17;
- when `DBUS_SESSION_BUS_ADDRESS` is `unix:abstract=…`, warn in App Detail and Settings → Sandbox
  that the bus filter doesn't hold for apps with the network grant, as the session warning does
  for the display.

No namespace shares the network without its abstract sockets, so the warning is the fix available.

### R3-9. 17.2's table gives Strict sound; Strict has none — LOW (wording; found by harness 3)

**Status: fixed** (see Fixes).

17.2's Strict row says "Display, sound, GPU: yes". 17.2.1 says sound given at Strict is dropped and
that "the table above is the whole story". The Strict launcher binds no PipeWire or Pulse socket,
shown in tier 1 and in every tier-2 run. The cell should read "display and GPU; no sound". In
Standard's row, "yes" means "with the sound grant".

### R3-10. 17.4's list of what the launcher binds misses the font cache and the resolver's folder — LOW (wording; found by harness 3)

**Status: fixed as decided** (see Fixes).

Neither bind is in 17.4:

- `/var/cache/fontconfig`, read-only at every level;
- with the network grant, where the host uses systemd-resolved, `/run/systemd/resolve`: the stub
  `resolv.conf` and the varlink sockets that nss-resolve uses. Elsewhere, the one file that
  `/etc/resolv.conf` points to in `/run`. This is round two's DNS fix, which only the code and a
  test describe.

Both binds are harmless. **Recommend:** state them in 17.4.

### R3-11. The field test runs its later "Strict" checks with the Online app launcher — LOW (test tooling; found by harness 3's field-test check; run)

**Status: fixed** (see Fixes).

**What happens.** `Probe.use()` rewrites the probe's one launcher for each template and returns its
path, so `strict` and `online` in `fieldtest.py` are the same file. Once the first Online app check
has run, four later checks all run the Online app launcher:

- INNER;
- the screen-capture check (D-wayland or D-x11);
- D-nosound;
- D-gpu.

D-nosound then reports LEAK on every desktop that has `pactl`, because Online app has sound. That is
a false failure in the release gate.

**Evidence (run).** The field test's new EXP check found it on its first run: "strict" saw the
filtered bus, the network and the document view. EXP now rewrites each template's launcher before
probing. The older checks are left as they were, since a harness commit fixes nothing.

**How it slipped past.** The field test's own regression test checks only rows recorded before the
first Online app check (the ISO checks, D-theme, P-filter), plus INNER, whose answer is the same
either way. The container has no `pactl`. The class is D1's: a test that checks something other than
what it names.

### R3-12. An app id longer than about 60 characters can't start at Standard: the proxy's socket path passes the 108-byte limit — LOW (functional; found by harness 3's VM run; run)

**Status: fixed** (see Fixes).

**What happens.** The launcher puts the bus proxy's socket at `$XDG_RUNTIME_DIR/appkata/bus-io.appkata.<id>.<pid>`.
A Unix socket path holds at most 107 bytes. With a real runtime folder (`/run/user/1000`), an id
longer than about 61 characters goes past it, or about 59 for a uid of six digits.
xdg-dbus-proxy then can't create its socket and exits without a word, and the launch fails with
bwrap's `Can't find source path …/bus-io.appkata.<id>.<pid>: No such file or directory`. An id is the
app name's slug, and nothing caps its length (`install.slug`, `new_app_id`).

**Evidence (run).** In the Mint 22.1 container with the runtime folder at `/run/user/1001`:

- "Some Application Name That Is Long But Fine" (43 characters) started;
- "Ultimate Developer Toolkit For Embedded Systems And Firmware Engineering" (72 characters) failed
  with the message above.

The harness first met the limit in the 24.04 and 26.04 VMs. There, pytest's long temporary runtime
folder and the user name "ubuntu" pushed even `offline-editor`'s socket path to 109 bytes. In the
containers, the user "kata" kept it at 107, just under the limit. The harness now uses a runtime
folder as short as a real one.

**How it slipped past.** Every launcher test used short ids, and nothing tried the longest name the
id function can produce. The class is a path the launcher builds passing a system limit. The other
paths it builds stay well inside theirs: 4096 bytes for a path, 255 for a name.

**Which is right.** The code. **Recommend:** name the socket by something of fixed length, for
example a hash of the id, or cap the id's length when it is chosen. The launcher should also say
when the proxy fails to start, rather than leave bwrap to report a missing file.

### R3-13. Sway, or any compositor, started from a TTY gets no session warning: the warning reads `XDG_SESSION_TYPE`, and the launcher reads `WAYLAND_DISPLAY` — LOW–MEDIUM (functional; found by harness 4)

**Status: fixed** (see Fixes). The warning asks the display the launcher gives
(`sandbox.given_display`), not `XDG_SESSION_TYPE`.

**What happens.** The launcher gives the app the Wayland socket whenever `$WAYLAND_DISPLAY` names
one. `session_warning()` warns about Wayland only when `XDG_SESSION_TYPE` is `wayland`. A compositor
started from a console doesn't set that: sway 1.9 sets `WAYLAND_DISPLAY`, `DISPLAY` and `SWAYSOCK`
(run), and the login leaves logind's `tty`. The results:

- **`XDG_SESSION_TYPE=tty`:** no warning at all. This covers sway, and Hyprland, which names itself
  in `XDG_CURRENT_DESKTOP`.
- **No logind, so no `XDG_SESSION_TYPE`:** the X11 warning. It tells the user to "log into a Wayland
  session (GNOME or KDE)", though they are already on Wayland, on a compositor that leaks all three.

17.9 promises the opposite: "sway started from a TTY sets nothing, and is warned about as 'this
Wayland compositor'". Round five's fix (R5-1) was tested with `XDG_SESSION_TYPE=wayland` and no
desktop name, which is not what a TTY start gives.

**How it slipped past.** Two places decide one fact, each tested on its author's own inputs.

**Which is right.** The requirement. **Recommend:** decide the warning from what the launcher gives:
`WAYLAND_DISPLAY`, then `DISPLAY`. Better still, decide it from the compositor's globals, F7's fix,
which this harness's table is ready to check.

### R3-14. The Sandbox dialog has no Notifications switch, though its own hint says there is one — LOW (UI gap; found by harness 5)

**Status: fixed** (see Fixes).

Notifications is a capability (17.5.1) in three templates (`standard`, `online-app`, `messenger`),
and the chips show it. Customize has switches for the tray icon, media keys, keeping the screen
awake and both password services, but not for notifications. So the user can neither take
notifications from a template nor give them to a custom set, except by picking another template.
The "Desktop services" hint promises it: "Notifications and keeping the screen awake are the
switches below". **Recommend:** add the switch beside "Keep the screen awake".

### R3-15. Turning "X11 apps" off shows on no chip — LOW (UI gap; found by harness 5)

**Status: fixed as decided** (see Fixes).

The X11 device grant changes what runs: off withholds the X11 socket, `DISPLAY` and the cookie
(17.9). `summary_chips` leaves it out ("the X11 fallback is the default, not worth a chip"). So the
install card and App Detail look the same with it on or off, and only the dialog shows it.
**Recommend:** a chip when it is off ("No X11 apps"), so the default stays unchipped and the
hardening shows.

### R3-16. The hand-over misses three shapes users give: an option's value, a folder, and a file still to be made — LOW–MEDIUM (functional; found by harness 6; run)

**Status: fixed as decided** (see Fixes): option values and folders are handed over; a file still
to be made is in 17.18.

The file-argument helper hands over an argument only when the whole argument is the path of an
existing file. Three common shapes miss that:

- **An option carrying its value** (`--file=/home/u/x.txt`, `-o/home/u/x.txt`) isn't seen as a file.
  The app gets the host path and finds nothing there.
- **A folder outside the granted folders.** "Open with" on a folder, or `codium ~/elsewhere`,
  reaches the app as a path it can't see. Newer document portals can export a folder (the `AddFull`
  call's export-directory flag), and nothing asks for it.
- **A file still to be made** (`gedit ~/elsewhere/new.txt`) can't be handed over as an existing
  file. The app shows an empty buffer it can't save. The portal's `AddNamed` hands over a name in a
  parent folder for exactly this.

17.6.2 promises "a file the app is given" and is silent on all three. All three are shown in the
Mint 22.1 tier with the real document portal. **Recommend:** decide each and state it in 17.6.2.
Reading an option's value as a path is the cheapest, and the folder needs the portal version
checked.

### R3-17. A link outside the granted folders to a file inside one is passed by the link's path, which the app can't see — LOW–MEDIUM (functional; found by harness 6; run)

**Status: fixed** (see Fixes).

The helper resolves links to decide whether an argument is already visible (`seen_inside` uses
`realpath`), but passes the argument on unresolved. Two cases show it, both run:

- a link on the desktop, `~/Desktop/link.txt`, pointing into the granted `~/Docs`;
- a path through a linked folder, `~/docs-link/in.txt`.

Each is judged already in view, so nothing is handed over. Inside the sandbox the link's path
doesn't exist, and the app opens nothing. This is class A again: the check and the use read one
path differently. **Recommend:** when the resolved path is in a granted folder, pass the resolved
path; otherwise hand it over.

### R3-18. Two more of the user's settings stop at the sandbox: the time zone and Qt's per-screen scaling — LOW (requirement gap; found by harness 6)

**Status: fixed as decided** (see Fixes).

These don't pass the allow-list:

- `TZ`, which a user who sets their own time zone has, and whose apps then show the system's;
- `QT_SCREEN_SCALE_FACTORS` and `QT_AUTO_SCREEN_SCALE_FACTOR`, which Plasma's X11 session sets for a
  HiDPI screen (read). A Qt app in a sandbox then draws at scale 1. `GDK_SCALE` and `XCURSOR_SIZE`
  do pass.

These belong to F15's decision: pass each through, or state it as a limit.

### R3-19. 13.3 leaves out five more entries the Audit records — LOW (wording; found by E2)

**Status: fixed** (see Fixes).

Besides the four sandbox entries (review 2's nit), the Backend records five Audit actions that
13.3's list of "What's recorded" doesn't name:

- an AppImage adopted as installed (`adopted`, 2.11);
- a kept version removed;
- `appkata://` links registered;
- settings imported;
- settings exported.

E2 checks every `_audit` call in the Backend against 13.3, and a new action without words for 13.3
fails it.

### R3-20. On RHEL and Fedora, where `/bin/sh` is bash, every app started without a terminal gets `TERM=dumb` — LOW (platform; found by E3's Rocky tier; run)

**Status: fixed** (see Fixes).

The launcher is a `/bin/sh` script. It passes each allow-listed variable that its shell sees as set.
Bash sets `TERM=dumb` when `TERM` is unset, even when it runs as `sh`; dash, Debian and Ubuntu's
`/bin/sh`, doesn't. So on RHEL, AlmaLinux, Rocky and Fedora, an app started from the menu, a
shortcut or AppKata gets `TERM=dumb`, which it was never given. A terminal inside it, or a tool it
runs, then turns off colour and line editing.

Shown in the Rocky 9 tier: a launcher started with no `TERM` gave the app `TERM=dumb`. The field
test's exposure check flagged it as a variable never set at launch. The inventory now judges a
variable by what the launcher's own shell sees (`exposure.shell_view`). E3's shell check keeps the
difference visible, listing bash's `TERM` against this finding. **Recommend:** read the variable
from the launcher's own environment before the shell can add it, for example by testing it in an
`env -0` listing, or pass `TERM` only when the launcher runs on a terminal.

### R3-21. On a Python that predates tarfile's extraction filter, AppKata from source can't install a tarball — LOW (platform; found by the Debian 12 tier; run) — closed

Found by the `launcher-debian12` tier added for review 2's F17. Debian 12 ships Python 3.11.2.
`tarfile`'s `filter=` argument came with Python 3.12 and was backported to 3.8.17, 3.9.17, 3.10.12
and 3.11.4. `install._extract` calls `extractall(dest, filter="data")`, so on 3.10.0–3.10.11 and
3.11.0–3.11.3 every tarball install fails: "TarFile.extractall() got an unexpected keyword
argument 'filter'". Requirement 1.2 says Python 3.10 or newer.

AppKata's own AppImage carries CPython 3.12 (`build.md`), so a user of a release isn't affected.
Running from source on Debian 12's own `python3` is. The field test's ISO-keys check fails the
same way, since it installs through AppKata's own path. Both tests are marked as expected failures
on such a Python (`no_tar_filter` in `tests/test_sandbox_run.py`, strict, so a fix must drop it).

**Recommend** (an owner decision):
- (a) a fallback for such a Python that refuses what the filter refuses: absolute paths, `..`,
  links leaving the folder, device files;
- (b) raise 1.2's floor to the patch levels with the filter (3.10.12, 3.11.4);
- (c) state it as a limit of running from source.

**Closed by the owner's decision (2026-10-19):** the AppImage is AppKata's only form on Linux and
running from source is for development only, so no user runs AppKata's code on a system's Python.
1.2 now says AppKata runs on the Python its release carries, one version and one PySide6 for every
release, set in `packaging/versions.env`, and that development uses the same; 1.6 drops the
`.deb`/`.rpm` maybe and 2.11.4 "a system package". Every launcher tier, both VMs and the field test
run AppKata's code on that Python (`scripts/python-standalone.sh`), while what a launcher runs on the
host (the file-argument helper, the `xdg-open` shim) stays on each system's own `python3`; the two
expected-failure marks are gone. E2 checks that no build script pins a Python or PySide6 of its own
and that `pyproject.toml` asks for the same Python.

### R3-22. On Windows, Install options' "Stable name link" runs out of its card: the row doesn't wrap — LOW (UI; found viewing the 3.14 Windows tour) — fixed

The Windows tour's screens from the 3.14 installer show the problem in Install options for a
portable app (C11, W02). One row holds "Add to the app menu", "Command keepassxc in
C:\Users\…\AppData\Local\AppKata\bin" and "Stable name link". It is wider than its card, so the
last checkbox and its label are drawn past the dialog's edge, over App Detail behind it. The row is
a `Row` in `InstallDialog.qml`, which never wraps. On Linux the command's folder, `~/.local/bin`, is
short enough to fit. The bug is older than this branch: the Windows screenshot committed with the
first release (`screenshots/windows/light/W02-install-options.png`, #2) shows it, and so does the
3.12 build.

The class is text that a dialog doesn't bound: a row of values of any length (paths, names) in a
fixed-width card. The "Installs to" line above the row is another one.

**Recommend:** a `Flow` for that row, and a harness that opens each dialog with long values and
checks that nothing visible extends past its card.

**Fixed (855d660).** The row is a `Flow`, with the command last, and each label wraps, as does the
"Installs to" path. The harness is wider than recommended: `src/appkata/layout.py` checks every
visible text against the card, chip, menu or dialog it is drawn in, and the tour runs it on every
screen it saves, on Linux (`scripts/test-layout.sh`, in tier 1's container) and on Windows
(`scripts/test-windows-vm.sh --shots`). `tests/test_layout.py` opens Install options with Windows'
paths and long Linux values in tier 1. On the old row it names the command, "Stable name link" and
the "Installs to" path.

Its first run over the Linux tour found three more, listed in the tour's `STILL_OUTSIDE` and fixed
one commit each:
- C10's Install dialog was taller than an 800 px window, so its footer and buttons were drawn below
  it. A dialog's body now scrolls when the window has no room (85589d7). At 800 px, Install options
  for a portable app on Windows now scrolls too: its command takes a line of its own.
- C10's "AppKata updates it — GNOME Software keeps updating it too…" ran past its card (75e82c0).
- S03's source menu subtitle ran past the menu (662e8fd).

Fixing the dialog found a blind spot in the check itself: the scrolled body hid the updates card,
and the check, skipping what a clip hides, called it fixed. A clip now hides only what lies between
a text and its own box, so a card scrolled out of view is still judged (a self-test case).

Shown: tier 1 2,396 passed; the Linux tour, 87 screens in both themes, has every text inside its
box with `STILL_OUTSIDE` empty; the Windows tour on the 22H2 VM, 93 screens, likewise.

### R3-23. When the API's hour runs out, github.com's pages count bare tags as releases and guess prereleases from the tag — LOW–MEDIUM (functional; found viewing the regenerated Linux S04) — fixed

The fallback (2.4.1) reads the releases feed, which lists bare tags as well as releases. Upscayl's
tag v2.15.1 has no release behind it, so through the pages it was the latest, with no files: Add
source said "No download for this computer", and App Detail listed 2.15.1 above 2.15.0. Through
the API, 2.15.0 is the latest, with a Linux download. The committed Linux S04 (3fc1a8d) showed
this, and it was missed when viewed. Any user whose API hour runs out sees the same.

How it slipped past: the API reading and the pages reading were each tested alone, and nothing
read one project both ways. The class is two paths deciding the same fact, here which releases a
project has and which are prereleases.

**Fixed (7f8b1e3).** The pages path reads the releases page once. A feed entry that isn't on that
page, and whose own page says "tagged this" rather than "released this", is left out. The same
page's labels give each release's prerelease mark. `tests/test_forges.py` serves one repository
through both paths and requires them to agree; on the old reader it fails.
`scripts/compare_github_paths.py` reads real projects both ways. On the demo's 12 projects with
the old reader, it found Upscayl's two bare tags (v2.15.1 and v2.11) and its wrong latest. It also
found a third disagreement: v2.10.9, which Upscayl marks a prerelease, though its tag doesn't say
so. With the fix, all 12 agree. The demo data's Upscayl was synced again through the API.

### R3-24. The demo data's staged states drift: the minimum-age example ran out, the Windows set never had one, and every screen says the last sync was 10 days ago — LOW (demo data; found reading the regenerated A01; run by E4) — fixed

`scripts/demo_data.py finish` sets the minimum age to 20 days, so that Zettlr 4.8.0 (out
2026-09-18) shows "Held · N days left" in A01. From 2026-10-08 it was older than that, so nothing
was held: both sets committed on 2026-10-19 (5823fcf, 02dba0a) show Zettlr with "Update
available" on Linux and "4.8.0 is out · Updates itself" on Windows, and `screenshots/README.md`'s
A01 row promises a held update.

The two platforms differ for another reason. The demo reviews say Zettlr updates itself on
Windows and macOS, not on Linux (`Auto update (windows): yes`), so on Windows AppKata doesn't
update it and no minimum age applies. The Windows A01 has shown "4.8.0 is out · Updates itself"
since the first set (9dc2b29, 2026-10-05), when the Linux one showed "Held · 4 days left". The
Windows set never had a held update. 17.12 (a sandboxed app that updates itself is updated by
AppKata) plays no part: on Linux, Zettlr doesn't update itself at all.

The demo data was made on 2026-10-09 and the screenshots taken from it on 2026-10-19, so every
screen's header says "Synced 10 days ago", and the Trust panel says each Trust synced 10 days ago.

How it slipped past: the tour checks that its text fits its boxes (R3-22) and that the demo data
holds no failed sync (9d41e51), and each regenerated screen was viewed. Nothing compared a screen
with what the README says it shows, and nothing looked at the data as of the day the tour runs.
The class is a staged demo state that drifts: with time, with a sync that brings new releases, or
from one platform to the other.

The harness, E4: `PROMISES` in `scripts/demo_data.py` holds each claim the README makes about a
tour screen's data (A01's update, AppKata's own, the held update, the pin; A09's "Kenji's app
reviews says it updates itself"; the kept versions A05 and A11 use; and so on), and the sync times
every screen shows. `check`, which `scripts/test-layout.sh` and the Windows VM's tour run first,
computes what the app shows on Linux and on Windows, now, and stops on a claim the data doesn't
keep, apart from what `STILL_WRONG` lists. A screen whose data needs no check says why (the tour
stages it, or the facts are written whole). `tests/test_demo_promises.py` requires an entry for
every tour screen, a Linux-only screen's claims marked as Linux's, and a finding for each listed
claim. On the data of 2026-10-09 it flags the held update on both platforms and both sync times,
and it found R3-25 and R3-26.

### R3-25. The Audit screenshot shows the days out of order, "Today" and "Yesterday" twice each — LOW (demo data; found viewing U01 while building E4, which now checks it) — fixed

The Audit lists entries in the order they were written, which in use is the order they happened:
AppKata records each one as it happens (`audit.record`). The demo writes its whole history at once
(`history()`), in the order its list gives, and the sandbox entries added to the list's end
(1f5d909) are dated two days ago, yesterday and this morning, before entries above them. So the
committed U01, Linux and Windows, reads Today, Yesterday, Saturday, October 17, Today, Yesterday.
It was missed when the screens were viewed.

`remake`, run on a copy of the data, showed two more. `history()` dates its rows by day and hour back from the day it
runs, so today's rows at 09:12, 10:12 and 12:30 UTC are in the future when it runs earlier in the
day. And build's own sync records "found a new signer, nadia@desk.coop" as it happens; the seeded
history records it again, a day earlier. The committed data hid this: it was re-seeded by hand,
which dropped build's entry.

### R3-26. The README gives four real screens the mockups' values — LOW (wording; found by E4) — fixed

The README's table describes the mockups and the real screens together, and its "Differences
from the mockups" lists where the real data differs. Seven claims hold for the mockups only, each
seen in the committed Linux screens:

- A02: "From (Source plus two Trusts)": LocalSend has three. "a Trust's name for Trust-only apps
  such as Zettlr and VSCodium": Zettlr is a Source ("Source · 2 trusts").
- A18: "Update to 5.6.2": the screen offers 5.8.4, the newest release no Trust avoids.
- A19: "at 2.0.1 · Installed" and "the 1.18.2 review": LocalSend 1.18.1 is installed, and your
  review is of 1.18.0.
- S01: "a rate-limit error": the demo data has none (S16, a mockup, shows one). The "+2" avatar
  stack: the Desk Collective has five enabled signers, so the screen shows "+1".

### R3-27. A09 shows Syncthing both sandboxed and updating itself, which 17.12 rules out — LOW (tour staging; found viewing A09 for R3-24) — fixed

In A09, App Detail shows Syncthing with the **Sandboxed** chip and its Sandbox section at
Standard, and also **Updates itself**: "AppKata only tracks its releases and leaves updating to the
app". By 17.12 a sandboxed app can't update itself, so AppKata updates it, and App Detail says "It
would update itself, but it runs sandboxed and can't change its own files, so AppKata updates it."
The demo's own Audit says you set Syncthing's sandbox to Off. The committed A09 (5823fcf) shows the
same.

Whether an app runs sandboxed is whether its launcher exists (17.4), and two places read it: App
Detail (the launcher file) and the Apps list's 17.12 test (the launcher named in the install
record). The tour stages "a working system, healed: its apps run sandboxed" (6564a33) by forcing
App Detail's answer, while the Apps list keeps reading the demo's install records, which name no
launcher. Under the tour the two disagree. And the demo never records Syncthing's Off: `finish`
sets KeePassXC's and Zettlr's sandboxes only, and the Off is in the Audit `history()` writes. In use
both places read the launcher; they differ only when the record names a launcher whose file is
gone, where App Detail says "Not sandboxed" and the Apps list still applies 17.12 (read, not run).

How it slipped past: harness 4 (one fact, one function) compares the product's own deciders, and
the tour's staging stands outside it. E4 checks the README's claims, and A09's, "Updates itself",
holds.

The class: a state staged, or reached, through one reader of a fact and not the others, so a
screen contradicts itself. The harness, E5: `RULES` in `src/appkata/tour.py`, what no screen may
show whatever the README says (shown sandboxed and updating itself; AppKata updating an app "because
it runs sandboxed" that's shown not sandboxed; a sandbox at Off with a launch command offered; a
package-channel install sandboxed by AppKata), checked by the tour on every screen it takes, on the
Apps list's row and App Detail's `sandboxInfo` of each installed app, under the state that screen
stages. A break listed in `STILL_CONTRADICTS` is reported; any other fails the tour, and so does a
listed one the whole tour no longer shows. `tests/test_tour_rules.py` puts a self-updating app
through each state the tour stages, crossed with the launcher's (none, there, named but gone) and
the user's Off. Run on the code of 70b6423: the test finds four breaks, all R3-27 (the tour's
working system and its X11 session: shown sandboxed and updating itself; with the user's Off: run
sandboxed; a launcher named, its file gone: updated by AppKata, shown not sandboxed, which was read
before and is now run). The Linux tour, 87 screens, finds Syncthing from A01 on, and nothing else.

### R3-28. The real U02 shows U01 again: no QML reads the tour's audit filter — LOW (tour; found viewing U02 for R3-25; run by E6) — fixed

The tour's U02 step asks for the Audit's Apps filter (`"auditFilter": "app"`), and nothing in
Main.qml reads that key, so the screen is U01 with "All" selected: the committed U02 in
`screenshots/linux` (5823fcf) is U01's list, R3-25's order included. The README's U02 row says
"Mockup only" while the real set has the screen. The Windows set leaves U02 out.

How it slipped past: the layout check (R3-22) looks at what a screen draws, E4 at the data a screen
needs, E5 at what two parts of a screen say; none asks whether a step's own settings took effect,
and U02 was viewed as "the Audit". The class: a setting a tour step makes that nothing applies,
which a key read only under another key (a review's settings, under `review`) can be too. The
harness, E6: Main.qml records the keys of each step it reads (`tourKeys`, through a Proxy, a
review's settings as `reviewSet.<key>`), and the tour fails on a key nothing read, apart from
`STILL_UNREAD`; `tests/test_tour_rules.py` checks the same without running the tour, by the keys
the hooks' code reads. Run: the six screens toured find U02's `auditFilter` and nothing else; with
A19's `review` taken out, the tour names its `reviewSet` and each of its four settings; with U02's
entry off `STILL_UNREAD`, the test names it. Not fixed: the owner decides between applying the
filter (the real U02 then shows the Apps entries, sandbox changes among them) and leaving U02 to the
mockups.

### R3-29. The header's "Synced N ago" never moves on: it's worked out once, when the last sync changes — LOW (UI; found viewing the regenerated X01; run by E7) — fixed

`Theme.ago()` works "50 min ago" out from `Date.now()`, which a QML binding doesn't depend on, so
a binding that calls it is worked out again only when what it does depend on changes. The
header's "Synced 50 min ago" is worked out when the last sync changes: AppKata left open says
"Synced just now" until the next sync, by default six hours on. The Trust panel's "synced N ago"
is the same, and the Audit's "Today" and "Yesterday" go stale past midnight. The ⋮ menu works its
"Last synced" out each time it opens, so the regenerated X01 shows "Synced 50 min ago" beside
"Last synced 52 min ago" on one screen.

How it slipped past: the tour checks that texts fit their boxes and that two parts of a screen
tell the backend's facts alike (E5); a text the QML works out from the time is neither, and no
test let time pass under a screen. The class: a text worked out from the current time with nothing
that works it out again as time passes. The harness, E7: `tests/test_time_shown.py` requires that
QML reads the time in one place, Theme's clock, and that everything else reads `Theme.now`. It
names the two reads there are (`Theme.ago` and the Audit's day label). Fixed by the owner's
decision (option A), before the screenshot sets are committed.

### R3-30. The Windows VM's clock is 7 hours fast, so every time the Windows set shows is off — LOW (test environment; found viewing the regenerated Windows A01; run by E8) — fixed

The VM's hardware clock is UTC, Windows reads it as local time (Pacific), and its time sync is
off ("Free-running System Clock"), so the VM's UTC runs 7 hours ahead: at 14:52 UTC it said 21:52.
`stage` sets the screens' times by this machine's clock and the tour shows them by the VM's, so the
Windows A01 said "Synced 8 h ago" and "Held · 3 days left" where Linux said 52 minutes and 4 days,
and the Audit's days shift by as much.

How it slipped past: E4 checks the staged times against the clock of the machine that staged them,
and the Windows set was viewed for what the data says. The class: the tour machine's clock differs
from the clock the data was staged by. The harness, E8: the VM test compares the VM's UTC time with
this machine's before staging, and fails past a minute. Run: 25,177 s ahead. Fixed by the owner's
decision (option A): the VM test sets the VM's clock from this machine's first; the VM itself,
which other projects share, is left as it is.

### R3-31. The AppImage takes about 20 libraries from the host, Kerberos's `libgssapi_krb5` among them, while 1.6 says it carries everything AppKata needs — LOW (requirement gap; found trying the AppImage in a minimal container; run) — fixed

1.6 says the AppImage "carries everything AppKata needs (its Python, Qt and runtime)". It carries
its Python and PySide6's Qt, and takes the rest from the host. Qt's network library links
`libgssapi_krb5.so.2`, Kerberos's library behind "Negotiate" sign-in, and QML and Qt Quick need the
network library, so without Kerberos AppKata stops before any of its code runs.

Run on the AppImage built today from 2bd1bf0's packaging (Python 3.14.8, PySide6 6.11.2):

- Its binaries name 86 libraries they don't bundle. Most belong to Qt plugins AppKata never loads
  (the SQL drivers, WebEngine, 3D, PDF, the GTK 3 theme).
- In the tour, in the Mint 22.1 image, the Python process loads 37 host libraries. About 20 of them
  are named directly by what it loads: glibc's, `libstdc++` and `libgcc_s`, `libz`, `libzstd`,
  brotli, glib and gthread, D-Bus, GL, EGL and GLX, fontconfig and FreeType, X11 and xcb,
  xkbcommon, and `libgssapi_krb5`. The rest are their own dependencies (Kerberos's four, systemd,
  gcrypt, PCRE2, …). On a desktop the X11 or Wayland platform plugin adds the xcb-* or wayland-*
  libraries.
- In a bare `ubuntu:24.04` or `debian:12` container the tour stops at glib. With glib, D-Bus, GL,
  EGL, fontconfig, FreeType, X11, xkbcommon, zstd and brotli installed it stops at `ImportError:
  libgssapi_krb5.so.2`, and with `libgssapi-krb5-2` added it takes its screen.
- Every 1.1 distro's desktop has it: the Ubuntu 22.04 base image already does, and Ubuntu 24.04's
  `ubuntu-desktop-minimal` and Debian 12's `task-gnome-desktop` install it (dry runs, without
  recommends); the Mint 21.3 and 22.1 images have it; Rocky 9's, Fedora 39's and 44's base images
  carry `krb5-libs`. So no supported desktop is known to lack it; the gap is 1.6's wording, and a
  machine without a desktop.

How it slipped past: `scripts/test-appimage.sh` runs only the two Mint images, which carry a full
desktop's libraries; the Rocky, Debian and Fedora runs of 10-19 were by hand, and nothing lists what
the AppImage takes from the host. 1.6's sentence was written as the design intent and never checked.
The class: a library the AppImage takes from the host that no requirement names and no tier shows
present. Open, for the owner: whether 1.1 or 1.6 names the host libraries (with a check that the
AppImage needs no other), or the AppImage bundles Kerberos (its five libraries, and the risk of
not matching the host's Kerberos setup).

### R3-32. On X11, the AppImage doesn't start on a default Linux Mint desktop: Qt's X11 plugin needs `libxcb-cursor0`, which no Debian-family desktop installs — HIGH (functional; found building R3-31's check; run by E9) — fixed

Qt 6.5 and later load their X11 platform plugin only with `libxcb-cursor.so.0`, and the plugin
also links `libxcb-icccm`, `libxcb-keysyms`, `libxcb-image` and `libxcb-render-util`. The AppImage
bundles none of them. On an X11 session (every Linux Mint edition, Debian's Cinnamon and Xfce,
Ubuntu on Xorg) Qt then stops before AppKata's window: "From 6.5.0, xcb-cursor0 or libxcb-cursor0
is needed to load the Qt xcb platform plugin. … This application failed to start because no Qt
platform plugin could be initialized." AppKata can't say anything first. Wayland sessions (the
GNOME default on Ubuntu, Debian, Fedora and Rocky) use the Wayland plugin and start.

Run on today's AppImage:

- Mint 21.3 and 22.1 images with `mint-meta-cinnamon` installed (Mint's Cinnamon desktop, with its
  recommends), on an X server (Xvfb, `XDG_SESSION_TYPE=x11`): AppKata exits with the message above
  and opens no window. With the five libraries added, it opens its windows.
- Dry runs, recommends included: `ubuntu-desktop` and `ubuntu-desktop-minimal` on 22.04 and 24.04,
  Debian 12's GNOME, Cinnamon and Xfce tasks, and `mint-meta-cinnamon` on 21.3 and 22.1 all leave out
  `libxcb-cursor0`; Mint 22.1's Cinnamon and Debian's Cinnamon and Xfce leave out the other four
  too. Only Debian's KDE task installs it.
- Not tried: a Mint installed from its ISO, which may carry more than its meta-package. The field
  test's real-desktop pass would show it.

How it slipped past: every run of the AppImage was offscreen. `test-appimage.sh` runs `--version`,
the tour, which sets `QT_QPA_PLATFORM=offscreen` itself (`app.py`), and `--install-self`; the
real-desktop pass in `local-proxy-test-plan.md` is still owed. Nothing ever loaded the platform
plugin a desktop session loads. R3-31's check, loading the X11 and Wayland plugins, found it on its
first run. E9's desktop tier, AppKata started as a user would in each 1.1 distro's desktop package
set: on X11 it fails on Ubuntu 22.04 and 24.04, Debian 12 GNOME and Cinnamon, Mint 21.3 and 22.1,
and Rocky 9 (Server with GUI); it starts on Fedora 39 and 44, whose Workstation installs carry
`xcb-util-cursor`. On Wayland it starts on all nine, with only the desktop's own libraries. The class: the release run only headless, so what a desktop session loads is never
loaded. Open, for the owner: bundle the five xcb libraries (small, without settings of their own,
which Qt AppImages commonly carry), or name them as host requirements, which leaves a default
Mint unable to start AppKata until the user installs them.

### R3-33. On a stock desktop, a Strict app starts a D-Bus of its own inside its sandbox, and the host's portal services with it; its `gio open` hangs — LOW–MEDIUM (functional; found by the Mint 22.3 desktop VM; run) — fixed

A Strict app has no session bus: its launcher leaves `DBUS_SESSION_BUS_ADDRESS` unset. With the
variable unset and `DISPLAY` set, GLib and libdbus *autolaunch* one: they run `dbus-launch
--autolaunch`, from dbus-x11, which every Mint and Ubuntu desktop installs. Inside the sandbox it
starts a new session bus, and the first call on it starts what the call names, from the host's
`/usr`, inside the sandbox.

Run in the Mint 22.3 VM installed from its ISO, in its Cinnamon session (scripts/test-desktop-vm.sh):
a Strict app's `gio open https://example.com/x` hung until R5-4's test stopped it at 10 s. Four
seconds in, the sandbox held `dbus-launch`, two `dbus-daemon`s, `xdg-desktop-portal`,
`xdg-permission-store`, `xdg-desktop-portal-gtk` (`-xapp` with `XDG_CURRENT_DESKTOP=X-Cinnamon`) and
`gvfsd`; the bus outlived the call. Each sees only the sandbox, so nothing reaches the host, but
these are the host's programs running inside the sandbox, which R5-4's class rules out, and the app
waits on them instead of failing.

How it slipped past: R5-4's test of every desktop road from a Strict app ran in the launcher
containers, minimal images without dbus-x11 or a display a client can reach; there autolaunch failed
at once. The class: what a stock install carries that changes what a sandboxed app meets, absent
from the minimal images the launcher tiers run in. R3-34 and R3-35 are two more of it. Decision
(owner, option A): at Strict the launcher points `DBUS_SESSION_BUS_ADDRESS` at the bus the sandbox
doesn't have, so GLib and libdbus fail at once and never autolaunch; the xdg-open shim tells Strict
by the missing socket. Probed in the VM: all eight roads fail in under a second, nothing left
running. The harness: the `launcher` container carries dbus-x11, gnome-keyring and Firefox, and an
X server on the tests' display.

### R3-34. The tests' private bus starts any service the machine has installed: on stock Mint, gnome-keyring took the name the sandboxed app under test should own — LOW (test tooling; found by the Mint 22.3 desktop VM; run) — fixed

`_Bus` in tests/test_sandbox_run.py was a plain `dbus-daemon --session`, which reads the machine's
service files: in the Mint VM, more than 20 (gnome-keyring's `org.freedesktop.secrets`, Nemo, gvfs,
evolution-data-server, …); in the containers, only the portals'. "A password service app serves a
host client only with the provide capability" failed with `NOT-OWNED`: its host client called
`org.freedesktop.secrets` before the sandboxed app owned the name, the bus started gnome-keyring,
and gnome-keyring took it. The test's other half (no capability, no name) passes there for the
wrong reason: the name is taken, not refused.

Not a product bug: on a desktop gnome-keyring owns that name already, and a password manager
offering it has to take it over, sandboxed or not (KeePassXC tells users to turn gnome-keyring's
off). Decision (owner, option A): the test bus starts only the portal services on demand; a test
meets what it starts. The harness: a test that it can start nothing else.

### R3-35. R5-4's test of the road the shim covers assumes the stand-in browser; with a real Firefox it starts the real browser inside the sandbox and waits — LOW (test tooling; found by the Mint 22.3 desktop VM; run) — fixed

R5-4's test shows the road the xdg-open shim covers: the desktop's own `/usr/bin/xdg-open`, called
by its full path under a desktop it doesn't know (`XDG_CURRENT_DESKTOP` unset, as sway from a TTY
leaves it), runs the first browser it finds, inside the sandbox. It expects the stand-in browser
`register-test-handler.sh` installs where there is none. On Mint, `/usr/bin/firefox` is Firefox, which
the script rightly leaves alone: the real browser started inside the sandbox and ran until the
test's 30 s timeout. This is R5-4's known remainder, not a new road. Under Cinnamon, which sets
`XDG_CURRENT_DESKTOP=X-Cinnamon`, the same call fails at once in the VM ("OpenURI portal is not
available"). Decision (owner, option A): that half runs only with the stand-in; a new check that
with Cinnamon's `XDG_CURRENT_DESKTOP` the desktop's own xdg-open fails within the bound and runs
nothing inside. Within A, the stand-in moved to `x-www-browser`, the first name the road tries,
which Mint's Firefox doesn't provide: beside a real browser the road still reaches the stand-in, so
the Mint tiers show it. Left at `firefox`, no locked environment would show the road at all (the
Ubuntu VMs have no xdg-utils).

### R3-36. On first start AppKata lists itself as "appkata" with a placeholder icon, until a sync — LOW (UI; found viewing the Mint 22.3 desktop VM's first start) — fixed

The VM's first start of the AppImage shows, behind "Install AppKata?", the Apps view with one row:
"appkata 0.1.0" and a letter "A". With no metadata synced, an app's name falls back to its URL's
last part and its icon to its initial; AppKata's install record says "AppKata", but nothing reads
it. No sync runs at first start (9.3: every 6 hours, or on request), so it stays until the user
syncs.

How it slipped past: every tour screen stages a synced Catalog, X14 "Install AppKata?" included; no
screen shows a fresh database, which is what every new user sees first. The class: states before
the first sync. Decision (owner, option A): an installed app with no synced metadata takes its
install record's name; AppKata's own row shows the icon it carries; the tour gains a first-start
screen from an empty database.

### R3-37. Mint 22 needs no AppArmor setup: Mint turns Ubuntu's user-namespace restriction off, while 17.10, the design doc, the test plan and the field test say it needs one — LOW (wording; found bringing the manual-testing docs up to date, from the Mint 22.3 desktop VM's report; run) — fixed

The documents name "Ubuntu 24.04 / Mint 22" wherever they say where the kernel blocks unprivileged
user namespaces, so that bwrap needs AppKata's one-time AppArmor setup behind a pkexec prompt:
17.10's heading and 17.10.2, `gaps.md` §16's item 6, `app-sandboxing.md` (the Approach, "One
privileged requirement", round 2's results, the Limits, and the claims table, which marks the row
run), the test plan's A1-prompt and A1-pkexec, the field test's A1-pkexec question, and
`sandbox.py`'s docstring.

Mint 22.3 installed from its ISO reports `kernel.apparmor_restrict_unprivileged_userns=0`, and
AppKata's own check finds no setup needed (the desktop VM's serial log, 2026-10-24). The setting
is Mint's own: `/etc/sysctl.d/20-apparmor-mint.conf`, from Mint's `ubuntu-system-adjustments`
package, sets it to 0 over Ubuntu's `/usr/lib/sysctl.d/10-apparmor.conf` (1), with the comment
"Allow the use of unprivileged user namespaces. See
https://github.com/linuxmint/mint22-beta/issues/82." (read from the ISO's squashfs). LMDE 7, on
Debian's kernel, has no such setting at all. So of the environments 1.1 claims a sandbox on, only
Ubuntu 24.04 needs the setup, and the field test's A1 questions can be answered only there; a
tester following the plan on Mint would wait for a prompt that never comes.

The product is right: AppKata decides from the kernel's setting, not from the distribution's
name, so on Mint it never offers the setup. Only the documents are wrong. Found reading for it: the
Landlock paragraph's "Mint 22's 6.8 kernel is ABI 4 (confirmed in round 2)" was Ubuntu 24.04's
kernel; Mint 22.3 boots 6.14.

How it slipped past: round 2 of the experiments (2026-10-08) ran the restriction on an Ubuntu 24.04
VM and wrote "Mint 22 is built on 24.04 and ships the same restriction". The Mint containers run on
the test machine's kernel, which has no such setting, so no tier could show Mint's; the claims
table marked the row run because its Ubuntu half was. The first run on Mint's own kernel and
sysctl was the desktop VM's, today. The class: a fact about a system's kernel or boot-time
settings, said of a distribution from its base or from a container. Harness (E10): what each
environment boots with, in one table in `docs/testing.md`, checked from inside each VM that boots
it, and every document's naming of the systems that need the setup checked against that table.

### R3-38. The test plan and the field test list different checks: the plan asks A1-prompt, which the script never asks, and the script's exposure checks are in neither of the plan's lists — LOW (test tooling; found bringing the manual-testing docs up to date; run) — fixed

`local-proxy-test-plan.md`'s "What it checks by itself" and "What it asks the tester" are the
checklist `scripts/sandbox/fieldtest.py` follows (the script's header says so). They have drifted:

- The plan's **A1-prompt** ("before the setup, installing a first AppImage asks 'Set up the
  sandbox?'; Not now installs it unsandboxed, and a second install doesn't ask"), added with R2-F12's
  prompt (c1b69ae), is asked nowhere: the script has no `ask()` for it, so a tester never sees it
  and no report lists it. The Mint 22.3 VM's report has eight MANUAL lines; the plan has nine
  questions.
- The script's **EXP-strict** and **EXP-online-app** (everything a sandboxed app sees is listed in
  `docs/sandbox-exposure.md`: harness 3's check in the field test, 1c2c005) pass or fail in every
  report and are in neither list of the plan.

How it slipped past: the plan and the script are two lists of one checklist, kept by hand; c1b69ae
changed one and 1c2c005 the other, and nothing compares them. The class: one checklist written
twice. Harness (E11): a test that reads both of the plan's lists and every check and question the
script records, and fails where they differ.

## Decisions (owner, 2026-10-18)

The owner took five decisions in a walk thru, one item at a time, then approved them as a whole:

| Finding | Decision | Recorded in 17.18 |
|---|---|---|
| R3-7 | State the machine-id, boot id and host name in 17.17, with F18's `/sys` values | a machine-id per app, together with narrowing `/sys` once real GPUs show it's safe |
| R3-8 | State the general case in 17.9 and 17.17, and warn in Settings → Sandbox and App Detail when the session bus is abstract and the app has network | each networked app on a network of its own (`pasta`, `slirp4netns`) |
| R3-15 | A "No XWayland" chip, shown only when the grant is off | — |
| R3-16 | Hand over option values (`--name=VALUE`, and `-oVALUE` with an absolute path) and folders, where the portal can, with today's behaviour as the fallback; 17.6.2 says exactly what is handed over | files still to be made |
| R3-18, F15 | Pass `TZ`, every `LC_*`, Qt's scaling and the input-method variables; the proxy variables only with the network grant; let Standard apps reach the IBus and Fcitx portals, if a run in the session image shows they work | accessibility, through a filtered AT-SPI proxy |

**A second walk thru (2026-10-18)** took what review 2 left open, after the fix pass, nine items
one at a time, then approved as a whole:

| Item | Decision |
|---|---|
| R2-F12 | Build the first-need prompt: on Install, when the system needs the one-time setup, "Set up now" or "Not now"; Not now is remembered (later installs don't ask), the banners stay, Settings' Set up… and App Detail's Enable… clear it, and the Audit records it. Strict needs only bwrap. Without xdg-dbus-proxy, a Standard app runs sandboxed with no session bus, App Detail says so, and the next start after the proxy appears rewrites its launcher. Settings' hint names the tool that is missing |
| R2-F16 | Once an app has a launcher it keeps one: an update, rollback or sandbox change writes it whatever the support check says, a start that then fails is reported (14.2.1), and a failed check isn't cached for the session; 17.10 says so |
| R2-F13 | A warning above Save in the Sandbox dialog when an app that runs Off, with no private home yet, is about to be sandboxed (instead of the toast after it); every setup entry point names the waiting apps before the password prompt; at startup, apps sandboxed for the first time are named in a notice and audited |
| R2-F9 | Review lines for every kind of grant, in the `+`/`-` form: `Sandbox sound`, `Sandbox devices`, `Sandbox services`, `Sandbox app folder`; a review can't grant the password service (the secrets class, F8). Saving a review writes the user's own sandbox choice (not one from reviews or the default), shown as one line with an "Include my sandbox" checkbox, on by default; what a review can't grant is left out and said. This is gaps.md §28's one exception: the sandbox can carry personal paths |
| R2-F10 | A folder template shows "Pick its folder:" with one-click buttons (Offline editor: Documents, Pictures; Media player: Music, Videos, read-only; Developer: Other… only) and says "no folder yet" until one is picked; the Files group gets one-click Documents, Downloads, Pictures, Videos and Music (the XDG user folders); each folder row toggles read-only; a customization is saved as its template plus changes |
| R2-F11 | "Show the launch command" in App Detail; Audit entries say what was added and removed; the Audit records a hash of the launcher text with the grant set it was written for (17.4 says so); a startup rewrite is one system entry per app |
| Nit: widened Strict | A customized app's description is built from its differences from the template; a widened Strict set is Standard plus those changes |
| Nit: review badge | The badge names what the suggestion adds and removes, then "may not work fully until you review it" (more) or "may have more access than it needs" (less); 17.11 says so |
| R2-F17 | Container tiers for Debian 12, Fedora 39 and the current Fedora; arm64 becomes a future target: 1.1 claims Linux x86_64 only |

Without a decision: R2-F14 (app logs keyed by install id), the uninstall dialog's offer to delete
an orphaned home, 17.3.4's count of templates, and the tour's screenshots.

**After the second pass (2026-10-19)** the owner took five more decisions: R3-21's (above), the
Python 3.14 trial, two in a walk thru on Windows 10, approved as a whole, and the design point:

| Item | Decision |
|---|---|
| R3-21 | The AppImage is AppKata's only form on Linux, and running from source is for development: 1.2 says AppKata runs on the Python its release carries |
| Python 3.14 | Try Python 3.14 with PySide6 6.11 and keep them if everything works out (it did) |
| Windows 10 (1 of 2) | The only Windows 10 target is 22H2, the last release, with every update up to its end of support; earlier releases aren't supported (1.1, 15.1). It came up when the ICU check's reason named 1809, 1.1's old floor |
| Windows 10 (2 of 2) | Setup refuses an older Windows (`MinVersion=10.0.19045`, 15.10) but doesn't check the updates installed; tests run on the supported version only, not on an older Windows to see the refusal (too costly) |
| The design point | The window is designed for a 1920 × 1080 screen, a 1080p laptop's, with AppKata maximized: what that leaves, 1920 × 1040 beside Windows' taskbar or Mint's panel (5.2.1). The screenshots and the layout check use it; nothing smaller is tested |

## Fixes

| Commit | Item | What changed | Shown by |
|---|---|---|---|
| 7b2fbc8 | R3-6 (HIGH) | AppKata's own install is never sandboxed (`_resolved_sandbox`), and the heal pass removes a launcher an older AppKata gave it; 17.1 | `test_appkata_itself_is_never_sandboxed_and_a_launcher_an_older_one_gave_it_goes` fails on the old code; harness 2's invariant now holds and has left its list |
| 55d08ac | R3-8 | `sandbox.bus_warning()`: Settings → Sandbox warns when the session bus is abstract, App Detail for an app with the network grant; 17.9 and 17.17 state every abstract socket, 17.18 a network of an app's own; the exposure inventory's row is stated | `test_the_bus_warning_is_said_only_for_an_abstract_session_bus`, the backend test, and in each launcher tier `test_the_bus_warning_is_on_exactly_where_a_dbus_launch_bus_is_reachable` (on: Mint 21.3, Rocky 9; off: Mint 22.1) |
| dfbd3cd | R3-13 | The session warning decides the session the way the launcher does: Wayland when `$WAYLAND_DISPLAY` names a socket in the runtime folder, else X11 when `$DISPLAY` is set (`sandbox.given_display`); 17.9 says so. A console-started X server (`startx`) is now warned about too | harness 4's three TTY sessions left its list (it flags them on the old code); `test_the_display_leak_warning_clears_only_gnome_wayland` now varies the display, not the session type; E2's own probe of the warning was updated to give it a Wayland socket |
| f6a373b | R2-F7 | `sandbox.compositor_globals()`: one registry round trip on the compositor's socket; the warning adds every leak the globals show to the name's verdict and never clears one, so Budgie (labwc) and Phosh (phoc) are warned about; the X11 advice names GNOME alone; the tour shows the product's text (`X11_WARNING`); 17.9 | harness 4 against `tests/fake_wayland.py` (all F7 entries left its list; on the old code it flags them), and the real reader in the `wayland`, `kwin` and `kwin6` harnesses: sway capture, clipboard and input; mutter nothing; kwin 5.27 and 6.3 the clipboard. The committed tour screenshots still show the old text until the next `--tour` run |
| a16adbb | R3-16, R3-17, R2-F6 | The file-argument helper turns a path in a granted folder into the path the app sees it at (the grant's mount path plus the rest), unless it already resolves there (a CLI tool's shared folder), so relative paths, `.`, `..`, links and linked folders reach the file; it reads option values (`--name=PATH`, `-o/PATH`) and exports folders with `AddFull`; 17.6.2 says exactly this, and 17.18 a file still to be made | harness 6: nine of ten listed cases left its list (on the old code they fail); three tier-1 tests run the helper on links, a linked home, option values and a CLI tool's in-place paths; folder export shown on document portals 1.12 (interface 4) to 1.20 (5); every launcher tier passes |
| 158dfad | R3-12 | The proxy's socket is named by a hash of the id (`bus-<16 hex>.<pid>`), whatever the id's length; a filter that doesn't start ends the launch with a sentence rather than bwrap's missing file | `test_an_app_with_a_long_id_still_starts_at_standard` and `test_a_bus_filter_that_does_not_start_is_said_plainly` fail on the old launcher; every launcher tier passes; the tier-1 stand-in bwrap now leaves the proxy's socket, as the proxy would |
| 2b507f4 | R3-11 | Every field-test check names the template it runs (`Probe.run(template, …)`), and the probe rewrites its one launcher whenever the template changes | `test_the_field_test_runs_each_check_under_the_template_it_names` (fails on the old probe, whose checks took a launcher path); the field test passes end to end on Mint 22.1 and Rocky 9 |
| 92aac1c | R3-5, R3-9 | 17.2's table: Strict has "display and GPU, no sound", Standard sound "with its grant"; 17.3's Devices column names X11 for every template ("X11 only" for Strict) | harness 3's check of 17.2's Strict row now expects no sound and has nothing listed; the trace's two open rows closed |
| a0e399e | R3-7, R3-10, R2-F18 | 17.4 names the font cache, the `/sys` parts GPU drivers read and the resolver's folder; 17.17 says every app can read the machine-id, boot id and host name, and through `/sys` the MAC addresses, USB serials and hardware model, as in Flatpak; 17.18 a machine-id per app with `/sys` narrowed | every row of `docs/sandbox-exposure.md` now quotes a requirement: harness 3's unstated list is empty; its F18 self-tests take the `/sys` rows out and still flag them |
| 505750d | R3-19, review 2's nits | 13.3 names every Audit entry; 17.3 has eight templates with `standard` in its table, and 10.3.1 lets a review name it; Settings' templates row lists Standard (with the product's "Command-line tool"); 17.5 says `Introspectable`; 17.17 the tray's pids 2 to 6; 17.6.1 comes before 17.6.2; 17.14 cites 4.7; 11.1 lists the Sandbox group; 4.3.1.2 says a sandboxed app's entries point at its launcher; 4.9.2 to 4.9.5 the Sandbox card; 17.7 keeps the extracted folder at Off | E2's list is down to D2's six facts. E2 itself had one false catch, 17.10.1, which F2's fix had already put right; its check now looks for the claim of a fixed path |
| 75ffdbc | R2-D2 | `gaps.md` §16 says the warning covers every compositor but GNOME's, by globals as well as name, that the document portal doesn't rely on the marker, and that only a fuller seccomp filter is deferred; the README's row says implemented and reviewed; `app-sandboxing.md` drops "planning" from its title, counts nine rounds and two reviews, drops the Landlock no-root fallback decision 6 rejected, and says what App Detail and the session caveat show | E2's list is empty: every documented fact it checks matches the code. The PR body's history paragraphs stay as history |
| 29421d4 | R2-F17 (the claim) | 17.1 lists every tier the launcher tests run on, Rocky Linux 9 among them, and says Debian 12, Fedora 39 and arm64 have none yet | E3 keeps those three in its untested list, so a tier for one of them must take it off |
| f6aa08c | R3-14 | A Notifications switch in the Sandbox dialog's services, beside "Keep the screen awake", with its evidence row | harness 5's dialog column: the change is now made through the dialog's own controls, and "no notifications" left its list |
| a171c2d | R3-15 | A "No XWayland" chip when the grant is off (the default stays unchipped); 17.9 says so. The trace's open tag for R3-14, left on one row by its commit, is removed | harness 5's chips column has nothing listed: the chips now tell apart every change that runs differently, and show none that doesn't |
| 7596953 | R3-18, R2-F15 | The allow-list passes `TZ`, every `LC_*`, Qt's per-screen scaling and the input-method variables; the proxy variables only with the network grant; the filter lets Standard apps reach `org.freedesktop.portal.IBus` and `org.freedesktop.portal.Fcitx`; 17.4, 17.5 say so, 17.17 states that screen readers can't see a sandboxed app, 17.18 a filtered AT-SPI proxy | the new `inputmethod` harness (IBus 1.5.29, Fcitx 5.1.7, headless): a sandboxed app creates and drives an IBus input context and creates a Fcitx one through the filter, is refused without the rules, has none at Strict, and gets the variables — `EXPECTED: ok`; harness 6's personas: only the screen reader is still listed; the exposure inventory lists the new variables; every launcher tier passes |
| b3bb421 | R3-20 | The launcher's pass-through reads the names from the shell's own list of exported variables (`export -p`), not from its variables, so bash's unexported `TERM=dumb` stays out; no outside program is needed (a first try with `env` and `sed` was caught by the launcher's minimal-PATH test); 17.4 says so | `test_the_launcher_passes_no_variable_its_shell_made_up` runs the launcher's own block under each tier's `/bin/sh` (fails on bash with the old block); the exposure inventory now judges variables by that same block; every launcher tier passes, Rocky 9 included |
| 700fd27 | R3-4 | A test makes an ownerless kept home: it counts as another app's, a same-name install takes the id after it, and once its owner is recorded it is that app's again | the trace's open row now names the test |
| ae2ef2f | R3-1 | A test asks for every other kind (`.deb`, `.rpm`, Flatpak, a package channel, a shell installer, none) and for Windows and macOS: no grant set, no Sandbox section (`applicable: false`), no launcher; an AppImage and a tarball on Linux get one | the trace's 17.1 row names the test |
| 136f37f | R3-3 | A test runs planFor's own computation of the Sandbox card for a stand-in release: it matches App Detail's view, the AppImage's unpacking cost (2.5×, none at Off or for a tarball), the card for each kind (`strict`, `cli-tool`), a review's Off offered but not applied, and no card for a system package | the trace's open rows name the test |
| 4e4f330 | R3-2 | `tests/test_sandbox_ui_surfaces.py` loads App Detail, Settings → Sandbox and the uninstall confirmation as QML against a real Backend, with the app really in the catalog; each state is made in the backend and every visible text and button is read back, and pressing a button must reach the backend: the pill, the chips, the setup and Repair banners and their buttons, the review badge and Keep mine, the session and bus caveats, the Chromium line, the sandboxed-updates line, System support in all five states with Set up… and Repair…, the defaults, the templates and home folders rows, and the offer to delete the home | 14 tests; the trace's eight open rows name them. It found one more gap, already one of review 2's nits: an app switched Off is offered no deletion of the home it keeps (listed in the test) |

### The second pass: what review 2 left open (2026-10-18/19)

After the owner's nine decisions (the second table under Decisions), one commit each, most severe
first; each item's harness entry left its list when the fix landed, and every launcher tier ran on
the commits that change the launcher.

| Commit | Item | What changed | Shown by |
|---|---|---|---|
| e8f7697 | R2-F12 (bwrap alone) | `have_tools()` is bwrap; a Standard app without xdg-dbus-proxy runs sandboxed with no bus, its files still handed over; the launcher text follows the proxy, so the next start adds the filtered bus; Settings and App Detail name the missing tool and the command (apt or dnf); 17.1 | harness 2 models the host's tools, not `have_tools()` (faking it hid the bug), and its invariant `bwrap-alone-sandboxes` fails on the old code (`repair > host->bwrap-only > update`); harness 4's entry left; a launcher-tier run test with no proxy on `PATH` and a real socket at `$XDG_RUNTIME_DIR/bus` |
| eb0f522 | R2-F16 | An app with a launcher keeps it on a broken host; the launcher says plainly when bwrap is missing; App Detail says "Can't start —" instead of "Not sandboxed"; a failed userns probe is asked again after a minute; 17.10 | harness 2's `never-unsandboxed-unasked` left its list (old code: `host->conflict > update`); backend, probe, launcher and QML tests fail on the old code |
| c1b69ae | R2-F12 (the prompt) | "Set up the sandbox?" before the first install that needs it: Set up now / Not now (remembered, audited; Set up… and Enable… clear it); the dead `declineSandboxSetup` gives way to `answerSandboxSetup`; 17.10, 13.3, 17.16, the design doc, the field test plan | backend and QML tests; the requirements trace's last open 17.10 rows; E2 required 13.3's words for the new entry |
| f655efa | R2-F13 | The dialogs warn above Save before a sandbox gives an app that runs unsandboxed an empty home; every setup entry point names the waiting apps first; what AppKata sandboxes itself (start, setup, update) is named in a notice and audited; 17.13 | harness 2's `told-when-a-sandbox-starts` left its list; dialog, backend and QML tests |
| 7752373 | R2-F14 | Logs are `logs/apps/<id>.log`; an older AppKata's name-keyed log moves to its id at start unless two installs share the name; 14.2.1, 17.6 | E1's two-apps keyspace has nothing shared (old code: `Notes.log`); a launcher-tier test caught after the tier run had still named the old path, fixed in the same commit |
| 821c732 | found while fixing F10 | The install card's pills showed one letter each once a template was picked: the template list's chips were bare labels | a test reads every pill the card draws for each template (old code: `'N', 'S'`) |
| dcbad6d | R2-F10 | "Pick its folder:" with one-click user folders for a folder template, "No folder yet" until then; one-click Documents, Downloads, Pictures, Videos, Music (this system's names); read-only toggle; a customization saved as template + overrides, keeping its name and Reset; the install card's link opens the dialog on its template and follows what is saved; 17.2.1, 17.3, 17.3.4 | harness 5's dialog column is empty (it now presses the row and folder buttons; its QML walk asks each Repeater for its items, since PySide wraps by first type met); a property test round-trips every corpus set through every template |
| a85a2af | R2-F9 | Review lines for sound, devices, services and the app folder; the keyring capabilities are in the secrets class; saving a review writes the user's own sandbox whole, shown with "Include my sandbox"; 10.3.1, 8.4.7, 17.3.1, 17.3.5, gaps.md 28 | harness 5 writes with the product's writer and reads back; only the secrets class can't be said (F8's decision); a real AppKata.md saved with the box on and off |
| 3da0330 | R2-F11 | "Show the launch command" in App Detail; every sandbox Audit entry names what was added and removed and the launcher's hash with the set it was written for; one system entry per startup rewrite; 13.3, 17.4, 17.16 | harness 2's `audited-with-what-changed` (now in its own words) left its list, so its list is empty; harness 5's Audit column is empty; E2's pattern now takes an actor passed by name |
| bd4158c | review 2's nit | A customized template is described by its changes, not its template's blurb; 17.3.4 | the dialog contract's Strict-widens test reads the description |
| 180de8c | review 2's nit | The review badge says what the suggestion adds and removes and what that means; 17.11 | unit and QML tests |
| c943a93 | review 2's nit | The uninstall dialog offers to delete the home an app switched Off still has; 17.14 | the QML surface test presses Uninstall for the Off app; its list is empty |
| 043621c | R2-F17 | Tiers `launcher-debian12`, `launcher-fedora39` (from the archive) and `launcher-fedora44`; arm64 a later target in 1.1; 17.1 | E3's untested list is empty; the requirements trace has no open rows |
| ff123de | found while fixing | 17.3.4 and the design doc said "seven" templates, and the design doc's table lacked Standard | E2 now reads every count of the templates in every document and the design table (five facts wrong on the old documents) |
| bfc26ee | — | `sandbox.changes()` leaves the level to its callers (an Audit entry read "added: Off instead of Standard") | the suites |
| 1f5d909 | — | The sandbox screenshots regenerated; the tour no longer runs the startup heal, and its demo states pin a machine with both tools | the nine screens viewed |
| 77092ae | **R3-21** (new) | Found by the Debian 12 tier; recorded, not fixed (an owner decision); two launcher tests are strict expected failures on such a Python | `launcher-debian12`: 125 passed, 2 xfailed |

### After the second pass: R3-21 and Python 3.14 (2026-10-19)

The owner's decision on R3-21, then the owner's ask to try Python 3.14 with PySide6 6.11 and keep
them if everything worked. Each commit is shown by the tiers it names; the tiers at the end are
under "Where this stands".

| Commit | Item | What changed | Shown by |
|---|---|---|---|
| df47af4 | R3-21 (the owner's decision) | 1.2: one Python and one PySide6 for every release, set in `packaging/versions.env`, and development on the same; 1.6 and 2.11.4 drop the system packages; the build scripts read the one setting | E2: no build script pins its own (three did), and `pyproject.toml` asks for the release's series |
| 4e3beba | R3-21 | Every launcher tier, both VMs and the field test run AppKata's code on the release's Python; what a launcher runs on the host stays on the system's `python3` | the two expected-failure marks are gone; Debian 12: 127 passed |
| 8861fbe | found trying 3.14 | Two tests found the folder picker by its class name, which PySide 6.11 reports as `QFileDialogOptions`; `re.split`'s maxsplit was passed by position (deprecated in 3.13) | tier 1 on 3.14, deprecations as errors |
| b29bb7b | for 3.14 | `scripts/test-tier1.sh` runs tier 1 in an Ubuntu 24.04 container on the release's Python and PySide6: PySide6 6.10+ needs glibc 2.34, which this RHEL 8 machine lacks | 2,391 passed on 3.12 |
| 8faebfe | for 3.14 | The AppImage builds in a Rocky Linux 9 container (glibc 2.34) | the AppImage's tests |
| 166e47e | found by the tiers | The unpacked Python's folder was 700, so tiers whose user isn't the host's couldn't run it | the Mint 22.1 and Ubuntu 25.04 tiers |
| 29f8fbb | found trying 3.14 | The tour's sandboxed screens pinned the tools' hints but not the system's support, so a machine without bwrap showed "Running unsandboxed" | the tour on Rocky 9 |
| cc096bb | found on Windows | The Windows suite copied five paths to the VM, so every test reading another file failed there; seven Linux-only modules ran on Windows; three tests were wrong off Linux (an encoding, PySide6 not asked for, names that differ only in case) | 161 passed on the Windows VM |
| 984c061 | — | build.md: the Windows VM is Windows 10 Pro 22H2, held on Windows 10 | — |
| 5b6e227 | found trying 3.14 | Qt 6.10+ imports Windows' ICU, which Wine lacks, so PyInstaller collected no Qt plugins or QML, and the installed app couldn't start: a stand-in ICU for the build only. The class is a build that succeeds without what the app needs to start: the build now stops when Qt's platform plugin or the controls are missing, and when the bundle carries any ICU DLL (a newer Windows' one needs `icu.dll`, which 1809 lacks) | the check stops the build without the stand-in; the VM test passes |
| cbf6216 | the owner's ask | Python 3.14 and PySide6 6.11.2 in every release; 1.1: macOS 13+; build.md's sizes | the tiers at the end |
| a339378 | the owner's Windows 10 decisions | 1.1, 15.1 and build.md: Windows 10 22H2, fully updated, and Windows 11; Setup's `MinVersion` is 10.0.19045 (15.10); the ICU check's reason no longer names 1809 | E2 compares where the documents name the release with `MinVersion` (on the old documents it flags 15.10 and the table); tier 1; the 22H2 VM: install, start, uninstall, the suite (162) and the end-to-end run |
| 674eb02 | found reading for it | The README and build.md still said ".deb/.rpm maybe later" after R3-21's decision dropped it from 1.6 | E2 now compares them with 1.6 (on the old documents it names both) |
| 855d660 | **R3-22** | Install options' row of checkboxes wraps, with the command last, and so does the "Installs to" path; `layout.py` checks every visible text against its box, on every tour screen (`scripts/test-layout.sh`, the Windows VM's tour) and in `tests/test_layout.py` | on the old row, `test_layout` names three texts; the tour's first Linux run found three more (`STILL_OUTSIDE`) |
| 85589d7 | found by R3-22's check | A dialog's body scrolls when the window has no room, so its footer stays in it (C10 at 800 px; Install options at the 660 px minimum) | C10's footer left `STILL_OUTSIDE` |
| 75e82c0 | found by R3-22's check | The Install dialog's "who updates it" choices wrap | C10's entry left `STILL_OUTSIDE`, still judged when scrolled out of view |
| 662e8fd | found by R3-22's check | A menu item's texts wrap, and its row grows | S03's entry left; `STILL_OUTSIDE` is empty, and the Linux (87 screens) and Windows (93) tours pass |
| 4788a65 | the design point | 5.2.1; the tour's window is 1920 × 1040 (on Windows, the work area of a 1920 × 1080 screen the VM test switches to and back); tier 1's dialog window is the same; tier 1's container prefers Nimbus Sans; `test-layout.sh --shots` makes the Linux screenshots | the VM test fails unless the screens come back 1920 × 1040 |
| 6564a33 | found regenerating | A screen that pins no sandbox state showed the machine running the tour ("Running unsandboxed: bubblewrap isn't installed" in the container): it now shows a working system | A02, A08, A09, A18 viewed |
| be39733, 9080e4d | found regenerating | A list's icons drew below it at the top of a list cut by its edge (S07's star, on Linux and Windows): the clip layer is on whenever a list inside a dialog overflows. On the main views it painted the Catalog black in the light theme, so they keep it only once scrolled | S07, C02, C06, C10 viewed |
| 3fc1a8d | — | The Linux screenshots at 1920 × 1040, 87 screens | each viewed |
| 88e18db | found regenerating | The Windows tour left out Linux's own screens (sandbox, channels, the AppImage's first start); the pointer moved off the window | the Windows tour, 74 screens |
| fad1693 | — | The Windows screenshots at 1920 × 1040, 74 screens (A18 and A19 new). Its message wrongly says 21 Linux-only screens were removed: they were never committed | each viewed |
| c6d468b | found viewing the screenshots | Settings' Theme row and the ⋮ menu read the theme shown, not the setting (light screens said "Dark") | `test_theme_shown.py`: only Main.qml reads the setting; the Theme row says the theme shown (4 fail on the old QML) |
| 9d41e51 | found viewing the screenshots | The demo data's sync syncs a failed app again and stops if it still fails; `check` and `retry`; the tour scripts check first | check stops on the old data (Upscayl and XZ Utils' 504s) |
| 7f8b1e3 | **R3-23** | The pages path leaves bare tags out and reads prerelease marks | the both-ways test fails on the old reader; the live comparison: 12 of 12 projects agree (old: Upscayl's 2 bare tags, latest, a prerelease) |
| d7f755d | found regenerating | The tour waits for Add source's check and Explore's search to finish before its shot (the Windows light S04 caught "Checking…") | S04 retaken on Windows |
| 5823fcf, and the Windows set after d7f755d | — | Both screenshot sets regenerated: Linux 17 screens changed, Windows 12, each viewed | — |

### R3-24 to R3-32 (2026-10-24)

The owner's decisions on R3-24 (options X and A), then on R3-25, R3-26 and R3-27 (option B each), in
a walk thru, and on R3-28, R3-29 and R3-30 (option A each). Each commit is shown by the harness that
caught its finding. At the end: tier 1 2,421 passed; the Linux tour, 87 screens, and the Windows
tour, 74, with no text past its box, no contradiction (E5) and no unread setting (E6); the Windows
VM's install, start and uninstall pass. The launcher tiers and VMs weren't run again: nothing here
changes a launcher.

| Commit | Item | What changed | Shown by |
|---|---|---|---|
| e6ba49d | E4 (R3-24's harness) | `demo_data.py check`: each claim `screenshots/README.md` makes of a tour screen's data (`PROMISES`), on Linux and Windows, as of the day the tour runs; `tests/test_demo_promises.py` | on the data of 2026-10-09 it flags 22 claims: R3-24's held update and sync times, R3-25, R3-26 |
| 4f65fd0 | **R3-24** (option X) | `stage`, before each tour and at the end of `finish`: the minimum age that leaves Zettlr's newest release 4 days to go, the sync times 50 minutes back | a test stages at four ages; `check`: the held update on Linux and both sync times hold |
| 419cacb | for R3-24 | `remake`: build and finish again, keeping the synced Catalog, without the network | a remade copy matches table for table but for Mara's key, the paths and the sync time |
| 053bce3 | — | R3-25's text names no commit for `remake`'s run | — |
| 6175d80 | **R3-24** (option A) | The demo reviews say Zettlr updates itself on macOS only, so Windows holds it too; Syncthing is installed a version behind ("2.1.6 is out · Updates itself") | `check`: the Windows held update holds |
| 869370c | after R3-23 | `scripts/compare_github_paths.py` is step 2 of build.md's "Before tagging a release" | — |
| 2bd1bf0 | — | `packaging/versions.env` notes that Qt 6.12 is the last Qt for Windows 10 | — |
| 70b6423 | R3-27 recorded | — | — |
| 50a941b | E5 (R3-27's harness) | `RULES` in tour.py, checked on every screen; `tests/test_tour_rules.py` | four breaks on the old code, all R3-27; the Linux tour flags Syncthing from A01 on |
| c8a0563 | **R3-27** (option B) | `Backend._runs_sandboxed` decides whether an app runs sandboxed (its launcher is there), and App Detail, the empty-home warning and the Apps list's 17.12 rule (`catalog.build`) ask it; the tour's working system is staged there only: an app whose sandbox isn't Off runs sandboxed. A record naming a launcher whose file is gone runs Off in the Apps list too | `tests/test_tour_rules.py`: no break in any case, and the tour's sandbox state read only by the deciders (the old backend reads it in `sandboxInfo` and `_fresh_warning` too); tier 1 2,417 passed; the Linux tour, 87 screens, no break: A09 shows Syncthing sandboxed and updated by AppKata, consistent, until the demo records its Off |
| 97fa0a6 | found remaking for R3-27 | `remake` failed making Mara's key (`gpg` exit 2): gpg 2.2 finds a key folder's agent by its path, and the agent the last build started served the new folder from the moved one. `remake` stops it before moving the data | the second remake of the day failed; with the fix it passes, and `check` with it |
| b8b5564 | **R3-27** (option B, the demo) | `finish` records Syncthing's Off, which the demo's Audit says you chose; E4 claims it for A09 (Linux), since A01's and A07's "Updates itself" rest on it too; the README's A09 row says so | `check` flags the claim on the old data; on the remade data it holds, and the Linux tour (87 screens) finds no break: A09 shows Syncthing "Updates itself" with no sandbox |
| 3dc1925 | **R3-25** (option B) | `stage` writes the demo's Audit again before each tour: in time order (the order the Audit lists), as if the tour ran at 13:00, so the newest entry is half an hour back at any hour; build's own entries go (its "found a new signer" was there twice); the append-only triggers are dropped and put back, in the demo data only. E4's U01 adds "nothing after now", "no entry twice" and "its newest entry from the last hours" | `check` flags the order and the duplicate on the data remade this morning; a test of `stage` fails on the old script (one entry, build's) and passes: in order, 30 minutes back, the same rows twice, the triggers back; U01 reads Today, Yesterday, Thursday, Wednesday |
| 796558a | **R3-26** (option B) | The README's A02, A18, A19 and S01 rows say what holds for the mockups and the real screens alike: "From (its Source and the Trusts that list it)", a Trust-only app such as VSCodium (Zettlr is a Source), "Update to the newest release no Trust avoids", the review dialog at the installed version with your review of an earlier one in the file, avatar stacks "+N" past four signers; the rate-limit chip is the mockup's, and "Differences from the mockups" says the real S01 has none. E4 checks the reworded claims | `STILL_WRONG` is empty and `check` holds on today's data |
| 54121bb | E6 (R3-28 found) | Main.qml records the step keys it reads; the tour fails on one nothing read, apart from `STILL_UNREAD` | U02's `auditFilter` found; A19 without `review` names its five keys; the static test names U02 when it isn't listed |
| 10a53c7 | **R3-28** (option A) | The tour sets the Audit's kind filter from the step and clears it elsewhere; the README's U02 row says what the real screen shows beside the mockup; E4 claims U02's data (Linux): sandbox changes, one turned off, a launcher the system rewrote | `STILL_UNREAD` is empty; U02 toured shows the Apps filter: the three sandbox changes, the launcher rewrite, an uninstall, a minimum age, a pin, the installs |
| 60f868f | E7 (R3-29 found) | QML reads the time only in Theme's clock | the two reads named: `Theme.ago` and the Audit's day label |
| b5f8036 | **R3-29** (option A) | Theme keeps the time (`now`, ticking every 30 s); `ago()` and the Audit's day labels read it, so the header's and the Trust panel's "synced N ago" and the Audit's Today and Yesterday move on by themselves | E7 has nothing listed; a QML test moves the clock 2 minutes, then 3 hours, and the header's text follows (on the old Theme it stayed "Synced 50 min ago"); tier 1 2,421 passed |
| 10ce7be | — | The Linux screenshots regenerated, 87 screens, each viewed | — |
| a5370c3 | E8 (R3-30 found) | The VM test fails when the VM's clock is more than a minute off this machine's | the VM: 25,177 s ahead |
| aa1bbc4 | **R3-30** (option A) | The VM test sets the VM's clock from this machine's (`Set-Date`) before staging, for the run only | E8: the VM 1 s behind; the Windows tour, 74 screens, passes |
| 4f71941 | — | The Windows screenshots regenerated, 74 screens, each viewed | — |
| 5249653 | E9 (R3-31, R3-32 found) | What the AppImage takes from the host, against 1.6; AppKata started on X11 and Wayland in nine desktop package sets | 45 host libraries listed (R3-31, five of them R3-32); X11 fails on seven desktops (R3-32); the whole `test-appimage.sh` passes with both lists |
| 763be9a | **R3-32** (option A) | The AppImage carries the five xcb-util libraries Qt's X11 plugin needs (`libxcb-cursor`, `-icccm`, `-keysyms`, `-image`, `-render-util`), built on Rocky 9 beside Qt's libraries; the build image is `appkata-build-el9:2` | E9: AppKata starts on X11 and on Wayland in all nine desktop package sets, with only each desktop's own libraries (18 of 18); the five leave E9's host list, which is 40 |
| 7e45d2b | **R3-31** (option A) | 1.6 says what the AppImage carries (its Python, Qt and the xcb-util libraries) and names, by group, what it takes from the desktop; `packaging/appimage-host-libs.txt` lists the 40 libraries; E9 holds the AppImage to that list; `build.md` describes the build container and the two new steps | E9: 40 of 40 named, none new; a test fails on the old 1.6 (no list); tier 1 2,427 passed; the whole `test-appimage.sh` passes: both Mint tours, the host list, 18 of 18 desktop starts |

## The test environments, locked in (2026-10-24)

The owner reviewed every test run by cost (time and disk) and locked in six environments, one per
platform 1.1 now names: Ubuntu 24.04 (tier 1's suite, the screenshot tour, `launcher-vm`), Linux Mint
22.3 and LMDE 7 (the current releases), Ubuntu 22.04 (the AppImage's build and start, no sandbox),
Windows 10 22H2 and Ubuntu 26.04. Fedora, RHEL and its rebuilds retired until RPM packaging is taken
up again, with Debian 12, Mint 21.3 and 22.1, and Ubuntu 25.04; their images are deleted. Tiers: 1 on
every change, 2 before a push, 3 in parallel, "just to be sure". The table, with run times and disk,
is `docs/testing.md`; 1.1 promises only what it tests, so Windows 11 and macOS are "not tested yet".
Ubuntu 25.04's two unique checks (Qt 6.8's file dialog, Plasma 6's clipboard) moved to LMDE 7, which
carries the same Qt, GTK and KWin.

| Commit | What changed |
|---|---|
| 4500eeb | The lock-in: 1.1, 1.2, 15.1, 17.1, E3 and the scripts; the AppImage builds on Ubuntu 22.04 (glibc 2.35) |
| 09aaf61 | The Windows end-to-end run's KeePassXC filter: 2.8.0 names its installer `-x64.msi` |
| ec0be4b | The Wayland session image installs Xwayland, which the hand-made image had carried |
| fe1376e | The ISO download protocol (`download.sh`, then claim and release), in `docs/testing.md` |

| Run | Result |
|---|---|
| tier 1 | 2,428 passed |
| `launcher` (Mint 22.3: bwrap 0.9.0, portal 1.20, GLib 2.80) | 128 passed, 5 skipped |
| `launcher-lmde7` (LMDE 7: bwrap 0.12.0, portal 1.20.3, GLib 2.84) | 128 passed, 5 skipped |
| `launcher-vm` (Ubuntu 24.04, kernel 6.8, AppKata's profile) | 124 passed, 5 skipped |
| `launcher-vm26` (Ubuntu 26.04, kernel 7.0, the system's own bwrap profile) | 124 passed, 5 skipped |
| the AppImage, built on Ubuntu 22.04 | the Mint 22.3 tour and `--install-self`; 40 of 40 host libraries named; started on X11 and Wayland in Ubuntu 22.04 and 24.04, Mint 22.3 and LMDE 7 desktop package sets (8 of 8) |

The skips are by design: three tests need PySide6, which the VMs don't carry (tier 1 runs them), and
two need the tmpfs and the stand-in camera only the container harness makes.

## The desktop VMs: R3-33 to R3-36 (2026-10-24)

Linux Mint 22.3 and LMDE 7 as their ISOs install them, in KVM VMs (`scripts/test-desktop-vm.sh`,
tier 3): the installer's squashfs with the live-only packages removed, a user logged in to Cinnamon
on X11 by LightDM, and, in that session, the stock system's versions, AppKata's AppImage started
through FUSE, the launcher tests as that user, the field test and screenshots of the session. The
ISOs come from the folder the projects on this machine share, claimed and released with its
scripts. What the stock systems carry that the containers didn't: dbus-x11, gnome-keyring, Firefox
(Mint's own build, with no `x-www-browser`), `libxcb-cursor0` on LMDE only (R3-32's library), and
no AppArmor user-namespace restriction on either. The first runs found R3-33 to R3-36; the owner
decided each (option A) in a walk thru, then approved them together.

| Commit | Item | What changed | Shown by |
|---|---|---|---|
| 34fa0bf | R3-33 to R3-36 recorded | — | — |
| 1b18487 | the desktop VMs, and the class's harness | `scripts/test-desktop-vm.sh` and `scripts/sandbox/vm-desktop.sh`; the `launcher` container carries dbus-x11, gnome-keyring, Firefox and an X server on the tests' display; a test that the tests' bus can start only the portals | the Mint VM: 3 failed, 121 passed; the LMDE VM: 4 failed, with the new test; the container fails the same 4 |
| 708fdd7 | **R3-33** (option A) | Every launcher sets `DBUS_SESSION_BUS_ADDRESS`; without a bus it points at `$rt/bus`, where the sandbox has nothing, so GLib and libdbus fail at once instead of autolaunching a bus inside; the xdg-open shim tells Strict by the missing socket; 17.4 and the exposure inventory say so | the container: R5-4's eight roads fail fast again (`gio open` waited 10 s); tier 1 2,428 passed |
| f54bbeb | **R3-34** (option A) | The tests' bus runs on its own config, whose only service folder holds the machine's portal services | the container: the bus test and the password-service test pass |
| 023facd | **R3-35** (option A) | The old road's half is its own test, run with the stand-in only, which is now `x-www-browser`; in its place, Cinnamon's own xdg-open fails within the bound | the container with Mint's Firefox: 130 passed, 5 skipped |
| c5f0c40 | **R3-36** (option A) | An installed app with no synced metadata takes its install record's name, AppKata its own, and AppKata's row its package's icon; the tour's X16 is taken from an empty home | a test on a fresh database: "appkata" and no icon before, "AppKata" and its SVG now; X16 viewed in both themes; the Linux tour, 89 screens |

| Run, after c5f0c40 | Result |
|---|---|
| tier 1 | 2,429 passed |
| `launcher` (Mint 22.3, now with dbus-x11, gnome-keyring, Firefox and a display) | 130 passed, 5 skipped |
| `launcher-lmde7` (LMDE 7, the same) | 130 passed, 5 skipped |
| `launcher-vm`, `launcher-vm26` | 125 passed, 6 skipped each: the old road's test skips, with no xdg-utils there |
| the Mint 22.3 VM (kernel 6.14) | 126 passed, 5 skipped; the field test 17 pass or blocked, none failed; the AppImage starts on X11 and its first start lists AppKata by its name and icon; 4 minutes, after a 3-minute build |
| the LMDE 7 VM (kernel 6.12) | the same; 4 minutes, after a 2-minute build |
| the Linux tour | 89 screens, X16 new; every text inside its box |

The VMs' five skips: the stand-in camera and the 1 MB tmpfs only the container harness makes, and
three tests that need PySide6, which the VMs don't carry.

## The manual-testing docs: R3-37 and R3-38 (2026-10-24)

The owner asked that the manual-testing docs be brought up to date (38ba741: the test plan, the
design doc's "Still owed", `testing.md`'s "By hand, before a release", step 6 of `build.md`'s
release steps). Doing so found R3-37 and R3-38; each got its class's harness, run to see what else
it catches. The owner decided three items in a walk thru, then approved them together: R3-37,
option B (say the condition, not a list of systems; `testing.md`'s table says which); R3-38, option
A (each side gets what it lacked); and the field test's runs tracked on GitHub, documented now and
set up after the repository moves to its new organization.

| Commit | Item | What changed | Shown by |
|---|---|---|---|
| 7b13d9f | R3-37, R3-38 recorded | — | — |
| 72e9fa2 | E11 (R3-38's harness) | `tests/test_field_test_plan.py`: the plan's two lists against every check and question `fieldtest.py` records | on today's files: A1-prompt, a question only the plan asks; EXP-strict and EXP-online-app, checks the plan doesn't list; nothing else. Its open list |
| 9185331 | E10 (R3-37's harness) | `testing.md`'s "What each environment boots with"; `tests/test_booted.py`, which each VM runs against its own row (`APPKATA_BOOTED=1`); E2 holds every naming of where the setup is needed, or the namespaces restricted, and every "<system>'s N kernel", to the table | the four VMs agree with the table; 15 places in the documents don't, all R3-37, among them "Mint 22's 6.8 kernel" twice. Its open list |
| 8c529fe | found reading the VMs' logs (the owner asked for the fix) | The desktop VM's log shows every check the field test makes, from "== checks ==" on; it showed the last 30 lines, so the first check, A-support, had scrolled off | the Mint 22.3 VM: A-support PASS shown, 17 pass or blocked, none failed, 9 manual or n/a; 129 passed, 5 skipped |
| a93909a | **R3-37** (option B) | Every place that named "Ubuntu 24.04 / Mint 22" states the condition (the kernel restricts unprivileged user namespaces and the system has no bwrap profile of its own) and points to `testing.md`'s table; the claims table names what was run; the experiment history is corrected in place, dated; the field test asks A1-pkexec only where the condition holds | E10's open list is empty, and a test puts "Mint 22" back into 17.10's heading and sees it caught; the four VMs: A1-pkexec N/A on the desktop VMs |
| cc2cc8e | **R3-38** (option A) | The field test asks A1-prompt beside A1-pkexec, both from `_setup_questions()`, N/A where the setup doesn't apply; the plan lists EXP-strict and EXP-online-app | E11's open list is empty; a test runs `_setup_questions()` under the three cases |
| 796bc98 | the owner's decision | `testing.md`, "Tracking the runs on GitHub": a tracking issue per release, a sub-issue per environment, runs as comments, a "no" as a bug; marked not set up yet, with the setup's four steps | — |
| ef273b2 | found beside 8c529fe | The Ubuntu VMs' pytest summary lists failures and errors (`-rfEs`), not only skips (`-rs`), since the output is cut to 40 lines | a failing and a skipped test under both flags; `launcher-vm` 128 passed |

| Run, at 9185331 | Result |
|---|---|
| tier 1 | 2,436 passed, 121 skipped |
| `launcher-vm` (Ubuntu 24.04), `launcher-vm26` (Ubuntu 26.04) | 128 passed, 6 skipped each |
| the Mint 22.3 and LMDE 7 desktop VMs | 129 passed, 5 skipped each; the field test none failed |

| Run, at cc2cc8e and after | Result |
|---|---|
| tier 1 | 2,438 passed, 121 skipped |
| `launcher-vm`, `launcher-vm26` | 128 passed, 6 skipped each |
| the Mint 22.3 and LMDE 7 desktop VMs | 129 passed, 5 skipped each; the field test 17 pass or blocked, none failed, A1-prompt and A1-pkexec N/A beside the seven questions |

In the run at a93909a three VMs skipped the DNS test: their guests couldn't resolve names while four
VMs ran at once. It passed at 9185331 and at cc2cc8e. Noticed, not fixed: `scripts/test-sandbox.sh
launcher-vm` passes extra pytest arguments unquoted, so `-k 'a or b'` reaches pytest as three
words.
