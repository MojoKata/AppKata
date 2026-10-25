# App sandboxing — review 2: the requirements against the code

Review of PR #3 (`app-sandboxing` → `master`) at 76edcf4, 2026-10-17. Rounds one to nine, their
fixes and harnesses are in [`app-sandboxing-1.md`](app-sandboxing-1.md). That file closed with
"nothing is open against the PR". This one asks three different questions:

1. What is missing or flawed in the requirements or the code?
2. Does the code match the requirements, and where it doesn't, which one is right?
3. Does all the code have requirements?

## Results

Every finding of this review is fixed or closed, and nothing of it is open (since 2026-10-19).
Review 2 was taken to the end in three passes; tiers are passed / skipped.

| Pass | Fixed | Items | Tiers at the end | Recorded in |
|---|---|---|---|---|
| This review's fixes | 2026-10-17, 4b0b3f2..69dc368, one commit each, after the owner decided F2, F3, F4 and F8 | F1 and F2 (HIGH); F3, F4, F5, F8, F19 and D1 (MEDIUM) | tier 1 2,116 / 106; Mint 22.1 97 / 2; Mint 21.3 96 / 3; Ubuntu 25.04 97 / 2; the Ubuntu 24.04 and 26.04 VMs 97 / 2 each | "Decisions"; "Fixes", at the end |
| Review 3's fix pass | 2026-10-18 | F6, F7, F15, F18, F17's claim, the nits but three UI ones, D2 | tier 1 2,201; every launcher tier 123 to 126 | [review 3](app-sandboxing-3.md), "Fixes" |
| Review 3's second pass | 2026-10-18/19, after the owner's nine decisions | F9 to F14, F16, F17's tiers, the three UI nits | tier 1 2,392; every launcher tier 124 to 127 (Debian 12: 125, and R3-21's two expected failures) | [review 3](app-sandboxing-3.md), "The second pass" |

The class harnesses this review named were built in review 3, which has their results too.

## Where this stood on 2026-10-17

**After this review's fixes (2026-10-17):** the eight HIGH and MEDIUM items are fixed,
one commit each, most severe first, each with a test shown failing before it. The owner decided F2,
F3, F4 and F8 one at a time ("Decisions"); the commits are in "Fixes" at the end, together with the
tiers they leave and the class harnesses built. Two things were found *while* fixing:

- **The proxy hang (part of F2).** On Ubuntu 26.04 every Standard launch left its bus proxy running.
- **The destructive field test (part of D1).** The old script overwrote, then deleted, the tester's
  real `~/.ssh/id_ed25519`.

One claim of this review was corrected by running it: Obsidian's AppImage doesn't abort on 26.04,
because its AppRun drops its own sandbox. A tarball Electron app does abort, as shown.

Still open then (all done since; see Results): the LOW findings and the nits, D2, and class B's harness (requirements traceability)
and class H's (the warning from the compositor's globals). They are listed under "Fixes".

**Merge readiness.** The conditions the verdict below set are met: F1 is fixed, and F2 is decided
and fixed, with Ubuntu 26.04 now a tier. What a release still needs:

- the field pass on a physical desktop, which now tests the product itself;
- the owner's view on the LOW findings.

## Method

`docs/requirements.md` §17 was read sentence by sentence against `sandbox.py`,
`install.py`, `applog.py`, `trustfile.py`, `backend.py` and the QML, together with the sections §17
leans on (4.3.1, 4.9, 4.10, 10.3.1, 11.1, 13, 14.2.1) and the documents it delegates to
(`app-sandboxing.md`, `local-proxy-test-plan.md`, `scripts/sandbox/field-test.sh`, `gaps.md` §16,
the README row and the PR body). Every suspicion that could be run was run, and the evidence column
says which were run and which were only read. Tier 1 at 76edcf4: 2,042 passed, 90 skipped. The
probes are listed at the end. They are not committed; each should become a test with its fix.

## Verdict

- **Missing or flawed.** Two HIGH, both run:
  - **F1:** a review can name a *relative* folder (`home`) that passes the never-shared check and
    gives the app the real home read-write.
  - **F2:** on Ubuntu 26.04 LTS, Ubuntu's own bwrap profile leaves sandboxed apps without the nested
    user namespace Electron's sandbox needs. AppKata's setup, or an upgrade from 24.04 after it,
    breaks bwrap altogether.

  There are also six MEDIUM findings: F3
  (sandboxed self-updating apps are never updated), F4 (CLI tool undefined), F5 (helpers left stale),
  F8 (review threat model), F19 (a same-name app inherits a kept home) and D1 (the release gate tests
  a design that isn't built). The rest are LOW.
- **Code against requirements.** Most of §17 is built as written, and the run evidence behind it is
  thorough (see the traceability table). Where they differ, the requirement is usually right and the
  code incomplete: F1, F5, F6, F7, F10, F11, F13, F14, F19. In three places the requirement is the wrong
  one: 17.12 contradicts 4.10 (F3); 17.10 describes a prompt the design replaced with standing
  indicators (F12); and §17 delegates to a test plan that predates finding 0 (D1).
- **Code without requirements.** The CLI-tool rule is code only (F4), and so are the `standard`
  template's contents, the `/sys` binds (F18), the environment allow-list (F15), the DNS binds and
  the extraction's stamp and lock. Two slots and a preference are dead (F11, F12). The branch also
  carries work outside sandboxing (see "Does all the code have requirements?").
- **Merge readiness.** The earlier verdict ("ready to merge on code and evidence") no longer holds:
  - F1 must be fixed before merge.
  - F2 needs a decision and a fix before the PR claims Ubuntu 22.04+, or else the claim narrowed to
    24.04.
  - F3, F5 and F19 need fixing before a first release.
  - D1 needs fixing so the field pass tests the launcher that is actually built.

| | HIGH | MEDIUM | LOW |
|---|---|---|---|
| Code vs requirements | F1 | F3, F4, F5, F19 | F6, F7, F10, F11, F12, F13, F14, F16 |
| Requirements missing or wrong | F2 | F8 | F9, F15, F17, F18, nits |
| Docs | | D1 | D2 |

---

## Findings

### F1. A relative folder path gets past the never-shared check and binds the host path — HIGH (17.3.1, security; run)

**Requirement.** 17.3.1: some folders are "never shared, whoever asks (a review or the Customize
picker): the home folder and anything above it, …". 17.2.1 says a folder grant is "any path".

**Code.** `protected_folder()` (`src/appkata_core/sandbox.py:284`) judges
`os.path.realpath(os.path.expanduser(path))`, which resolves a relative path against *AppKata's*
working directory. The launcher binds the same string unchanged (`sandbox.py:1391-1396`). bwrap
resolves a bind source against the host's root (`/oldroot/<path>`), not against any working
directory. Nothing in between requires the path to be absolute or to start with `~`:
`trustfile._setting_value` keeps a `Sandbox folders` value as written, and `parse_folders`
(`sandbox.py:126`) and `apply_overrides` (`sandbox.py:153`) accept any string.

**Evidence (run: Mint 22.1 container, bwrap 0.9.0, probe `test_probe_relative_grant.py`).** The
review section was `- Sandbox (linux): offline-editor` / `- Sandbox folders (linux): tmp`, with the
test user's home under `/tmp`. `protected_folder('tmp')` returned `''` and the chips were `Standard`,
`tmp`, `No network`. The launcher had `--bind-try tmp tmp`, and the app printed the real
`~/.ssh/id_ed25519` and appended to the real `~/.bashrc`. The absolute path of the same home is
refused ("your whole home folder"). On a desktop the line would be `Sandbox folders (linux): home`,
which needs no user name, or `run/user/1000`, the session's runtime folder. That folder holds
`systemd/private`, which starts programs outside the sandbox, and the gpg and ssh agents.

**Why it matters.** It defeats the one rule that bounds what a review can grant. The summary shows
the grant as an ordinary folder chip ("home") on a "Standard" app, so the user believes the app is
sandboxed. A review can also say `Sandbox: off` (F8), but that shows plainly as "No sandbox".

**Which is right.** The requirement. **Fix:** refuse a folder that isn't `~`, `~/…` or absolute, in
`parse_folders`, `apply_overrides` and `protected_folder` ("not an absolute path"), and emit only
absolute binds. **Test:** add relative, bare-word and `run/user/<uid>` paths to the adversarial
corpus. Its `_bind_pairs` filter (`s.startswith(home)`, `tests/test_sandbox_adversarial.py:55`) is
exactly why relative paths were invisible to it, and every path in `HOSTILE` starts with `~/`. Also
assert from *inside* a run-tier sandbox that no protected file is readable, for every corpus entry
(class A below).

**Status: fixed.** `protected_folder()` refuses any folder that isn't absolute once `~` is expanded
("not a full path (start it with / or ~/)"). Every reader of a grant set passes through it: the
launcher's `strip_protected`, the chips, and the dialog's save. 17.3.1 says so.

Tests, both shown failing on the code before the fix:

- `test_a_folder_not_named_from_the_root_or_home_is_refused_and_never_bound` (tier 1). Twelve
  relative forms; 7 of 12 failed, and the rest passed only because `.` and `..` happened to sit
  above the test's home.
- `test_a_review_naming_a_relative_folder_never_opens_the_real_home` (tier 2). A real review
  section, judged from inside the sandbox; 3 of 3 failed.

The hostile-path test now also asserts that no bind source is ever relative.

### F2. On Ubuntu 26.04 LTS, Ubuntu's own bwrap profile stops Electron's sandbox inside AppKata's, and AppKata's setup breaks bwrap altogether — HIGH (17.1, 17.10, 17.10.1, 1.1; run in KVM)

**Requirements.** 17.10 describes one platform: Ubuntu 24.04 / Mint 22, where nothing grants bwrap
a user namespace until AppKata's profile does. 17.10.1 rejects "Ubuntu's later
`bwrap-userns-restrict` design" because "it breaks the Chromium/Electron sandbox nested inside
bwrap, which Electron apps rely on". 1.1 supports Ubuntu 22.04 and later.

**What Ubuntu ships now (read).** That later design is no longer optional. Both of these install
`/etc/apparmor.d/bwrap-userns-restrict`:

- Ubuntu 25.04's `apparmor` 4.1.0~beta5-0ubuntu14.2;
- Ubuntu 26.04.1 LTS's `apparmor` 5.0.2-0ubuntu1~26.04.1, alongside `glycin.bwrap`.

The file defines profile `bwrap` on `/usr/bin/bwrap`. It allows the user namespace, and it stacks
every child into `unpriv_bwrap` with `audit deny capability`.

**Evidence (run: Ubuntu 26.04 and 24.04 cloud images under KVM).** The probe `vm-probe.sh` ran a
generated launcher whose program tries what Chromium's sandbox does:

- `unshare --user --map-root-user --mount --pid --fork` plus a tmpfs mount;
- the same with only `--user`;
- `unshare -Ur chroot /`.

The 26.04 guest ran kernel 7.0.0-34 and bubblewrap 0.11.1; the 24.04 guest ran kernel 6.8.0-142
and bubblewrap 0.9.0.

| | `support_status()` | Strict and Standard launchers | Nested user namespace inside |
|---|---|---|---|
| 24.04, no AppKata profile | setup-needed | bwrap refused ("setting up uid map: Permission denied") | — |
| 24.04, AppKata's setup done | ok | run | **works**: caps, mount, chroot |
| 26.04 as installed (`bwrap` and `unpriv_bwrap` loaded) | **ok** | Strict runs; a Standard run didn't return within 60 s, and its `xdg-dbus-proxy` was still alive afterwards, confined `bwrap//&unpriv_bwrap` (seen once; cause not established) | **fails**: "unshare failed: Operation not permitted", "write failed /proc/self/uid_map" |
| 26.04 after AppKata's setup (its profile loaded beside Ubuntu's) | **setup-needed** | bwrap refused, with the same errors as 24.04 without a profile | — |
| 26.04, AppKata's profile file present at boot (as after an upgrade from 24.04), rebooted | **setup-needed** | bwrap refused (the same errors) | — |

**What this means on 26.04 and anything built on it:**

1. **Electron and Chromium apps lose their own sandbox.** AppKata reports the sandbox ready and
   offers no setup. Every sandboxed app runs under `unpriv_bwrap`, where no nested user namespace
   can be made. Chromium and Electron need one for their own sandbox, and an AppImage's
   `chrome-sandbox` isn't setuid, so they can't fall back. *Corrected while fixing:* this review
   first inferred that Obsidian would refuse to start. Run in the 26.04 guest, it doesn't: its
   AppRun, electron-builder's current template, probes `unshare -Ur true` and adds `--no-sandbox`
   itself, so it runs without its inner sandbox either way. A program started without such an
   AppRun (a tarball, an older AppImage) has no such probe; see the status below.
2. **AppKata's setup makes it worse.** `install_profile()` loads AppKata's profile next to Ubuntu's,
   and afterwards bwrap can't create a user namespace for anyone, AppKata's own launchers included.
   This presumably also covers every other program that runs `/usr/bin/bwrap`; Flatpak's apps were
   not run here. The setup's own check then fails ("the AppArmor profile loaded, but bwrap still
   can't …"), but `install_profile()` doesn't remove what it loaded, and the file persists across
   reboots. On 26.04 the setup is offered only when the probe fails for some other reason (F16).
3. **An upgrade breaks it unasked.** A 24.04 or Mint 22 machine where the setup ran carries
   `/etc/apparmor.d/appkata-sandbox` into the upgrade. The rebooted guest above is that state:
   every sandboxed app then fails to start. AppKata then shows "Set up…", which reloads the same
   profile and changes nothing.

**Which is right.** Neither. 17.10 describes 24.04 alone, and 17.10.1's objection is now Ubuntu's
default.

**Decide (owner).** What AppKata does where Ubuntu's own bwrap profile exists: accept Electron apps
without their inner sandbox, add a `local/bwrap-userns-restrict` override, which widens it for every
program, or something else.

**Code, whatever the decision:**

- Never install AppKata's profile when another profile already attaches to the bwrap path.
- Remove AppKata's profile when Ubuntu's arrives (an upgrade).
- Roll back a setup whose check fails.
- Probe for a nested user namespace, not just bwrap's own, before calling the system "ok".

**Tests:** a `launcher-vm` tier on 26.04, and a run test for the nested user namespace (class D).
Until then, 17.1 should say the AppArmor path is tested on 24.04 only.

**Status: fixed, as the owner decided.** Requirement 17.10.2 is new.

The code:

- **Detection.** `sandbox.other_bwrap_profiles()` finds a profile attached to bwrap: Ubuntu's, and
  not glycin's, which only names bwrap in a rule. `nested_userns_works()` probes `unshare --user`
  inside bwrap.
- **Status.** `support_status()` reports "conflict" when AppKata's profile sits beside the system's,
  and "ok" with `innerSandbox: false` under the system's profile alone.
- **The setup.** `install_profile()` refuses beside the system's profile. Its script checks bwrap
  as the user who asked (`PKEXEC_UID`, `setpriv`) and unloads and removes the profile when the check
  fails. `remove_profile()` behind **Repair…**, in Settings and App Detail, clears the conflict.
- **The launcher.** Where the inner sandbox can't run, it gives a program with `chrome-sandbox` or
  `chrome_crashpad_handler` beside it `--no-sandbox`. That is decided after an AppImage is unpacked.
  The host fact is part of the launcher text, so the startup pass rewrites launchers after an
  upgrade. App Detail says so for such an app, and Settings for the system.
- **Deferred.** 17.18 gains the zypak-style spawner.

**Shown in the KVM guests** (Obsidian's binary run the way a tarball app is, with no AppRun probe):

| Guest | Launcher as generated | Launcher without the block |
|---|---|---|
| 26.04 | runs (`--no-sandbox` added) | aborts, exit 133: "The SUID sandbox helper binary was found, but is not configured correctly" |
| 24.04, AppKata's profile | runs with its own sandbox (zygotes); the block isn't there | — |

**Tests:**

- tier 1: the profile scan, the conflict status, the refused setup, the setup script's rollback
  (run with stub tools: check passes, fails, or no `setpriv`), the launcher block, the startup pass
  after a change of host fact, and the audited repair;
- tier 2: the `--no-sandbox` block for a fake Chromium payload in all four cases, and
  `test_the_inner_sandbox_probe_tells_the_truth_inside_a_generated_launcher` (class D);
- new `scripts/test-sandbox.sh launcher-vm26`: the whole run tier in Ubuntu 26.04, which mirrors
  the setup and loads AppKata's profile only where the system has none.

**Found by the new tier: the proxy hang.** On 26.04 every Standard launch left its `xdg-dbus-proxy`
running, reparented to init and confined `bwrap//&unpriv_bwrap`. This was the "didn't return within
60 s" seen once above: a caller reading the launcher's output waited on the surviving proxy.

- **Cause.** `--die-with-parent` is a parent-death signal, and the kernel clears it at an exec that
  changes the security domain. Entering `unpriv_bwrap` is such a change.
- **Fix.** The proxy's bwrap now has its own pid namespace (`--unshare-pid`). It ends with bwrap's
  first process, which keeps the signal. The goldens show the one word.
- **Evidence.** The hang probe, before and after, in the 26.04 guest: the proxy was left running,
  then nothing was left. `test_a_standard_launch_leaves_no_proxy_running` keeps it.

**Tiers at this commit:**

| Tier | Passed | Skipped |
|---|---|---|
| 1 | 2,063 | 99 |
| 2, Mint 22.1 | 90 | 2 |
| 3, Ubuntu 24.04 (AppKata's profile) | 90 | 2 |
| 3, Ubuntu 26.04 (Ubuntu's profile, inner sandbox false) | 90 | 2 |

### F3. A sandboxed app that updates itself is never updated by anyone — MEDIUM (17.12 against 4.10; read)

**Requirements, in conflict.** 17.12: "'Disable the app's own updater' is its own install option …;
AppKata then updates the app itself (4.10). Sandboxing turns it on and warns". Decision 11 and the
design doc's AppImage point 7 say the same ("AppKata takes updates over"), test plan U1 checks it,
and 17.16 audits "enabling/disabling an app's updater". But 4.10.3 says "AppKata can't turn an app's
own updater on or off", 4.10.4 says turning it off from outside "isn't supported", and 4.9.2's hint
says "AppKata can't turn an app's own updater off."

**Code.** No such option exists. An app marked "updates itself" (a Trust's `Auto update`, or the
checkbox) has state `selfupdating` whatever its sandbox (`catalog.py:235`). `Backend.update()`
(`backend.py:1101`) answers "updates itself", and Update all skips it. Meanwhile the launcher binds
its folder read-only, and for an AppImage it binds the `.AppImage` read-only too.
`test_a_self_updating_appimage_can_change_its_unpacked_copy_but_never_the_appimage_itself` shows
the updater's write refused *even with* the writable-app-folder grant, whose hint says it is "for
apps that self-update". `sandboxInfo()["selfUpdating"]` (`backend.py:1834`) is computed and shown
nowhere.

**Result.** Take an Electron AppImage (Obsidian, Signal) whose Trust says `Auto update: yes` and
which runs sandboxed. It stays at the version installed: its updater can't write, AppKata doesn't
try, and nothing says so. A sandbox that freezes a network-facing app on an old version is a
security regression the user can't see.

**Which is right.** 17.12's intent (someone must update it) is right. Its mechanism (an option that
disables the app's updater) contradicts 4.10.3/4.10.4 and was never built. **Requirement:** "While an
app runs sandboxed, AppKata updates it as if it didn't update itself, since its own updater can't
write its files; the install dialog and App Detail say so." Then drop the updater from 17.16, and
fix the writable-folder hint for AppImages. **Code:** treat `selfupdating` as `installed` when the
resolved level isn't Off. 4.10.2's fixed-name layout then becomes versioned at the next install.

**Status: fixed, as the owner decided.** 4.10.5 is new; 17.12 is rewritten; 17.7.1, 17.16, 4.9.2,
`gaps.md` item 9 and the design doc's AppImage point 7 and decision 11 are updated.

- **Who updates it.** In the catalog, an app that updates itself has state `selfupdating` only
  while it has no launcher. Running sandboxed, it gets Update and Update all, and the field
  `sandboxedUpdates` drives App Detail's line: "It would update itself, but it runs sandboxed and
  can't change its own files, so AppKata updates it". `Backend._updates_itself()` lays a sandboxed
  install out in versions.
- **Leaving the fixed layout.** `install._leave_fixed_layout()` renames the old `<App>.AppImage` to
  a versioned name, so it is kept as the previous version. Left in place, it stopped the first
  update: `_link()` refused to replace a file at the stable name.
- **The texts.** The install dialog's "This app updates itself" hint says what happens while it
  runs sandboxed. The writable-app-folder hint no longer claims to help self-update; its evidence
  row is updated.

Tests (both failed before the fix):

- `test_a_self_updating_app_is_updated_by_appkata_while_it_runs_sandboxed`, on the backend and the
  catalog;
- `test_a_self_updating_app_that_runs_sandboxed_moves_to_versions_when_appkata_updates_it`, on
  install with a local server. It failed with "exists and isn't a link AppKata made".

Tier 1: 2,094 passed, 99 skipped. Tier 2 (Mint 22.1): 90 / 2.

### F4. "CLI tool" is never defined; with Settings' defaults every unreviewed tool is a GUI app, runs Strict and sees nothing — MEDIUM (17.3.3; run)

**Requirement.** 17.3.3, 17.15, decisions 1 and 10 and `gaps.md` §16 item 2 use "CLI tool" and "GUI
app" without saying how AppKata tells them apart.

**Code.** `Backend._is_cli()` (`backend.py:1653`) treats an app as a CLI tool when the command link
is on and the app-menu entry is off. Settings' defaults are app menu on and command links on
(`prefs.py`). So an unreviewed tool, with no Trust saying `App menu: no`, is a GUI app and gets
`strict`. Probe: `is_cli with defaults: False -> strict`.

**Evidence (run, Mint 22.1).** A Strict tool run from `~/Projects` as `tool . notes.txt
~/Projects/notes.txt` starts in the private home. `.` lists the private home, all three arguments
fail with "No such file or directory", and nothing on stderr says why: the cli-tool template's
message comes only from its `$cwd` block. Every backend test stubs `_is_cli` to `False`
(`tests/test_sandbox_backend.py:26`, `tests/test_sandbox_two_apps.py:31`), so the rule itself has
never run.

**Also.** The install dialog's Sandbox card is computed when the dialog opens, from the saved
options. Unticking "Add to the app menu" doesn't change it, so it keeps saying Strict, yet the
install resolves `cli-tool` (probe: the worker's `_is_cli` sees the dialog's answer). The card isn't
live for the very box that decides its default.

**Which is right.** The requirement's intent: unreviewed tools get `cli-tool`, real protection
rather than Off. The rule needs an owner's decision. Options: a payload with no `.desktop` file, a
question in the install dialog, or a Trust's `App menu: no` alone, stated as such. Write the rule
into 17.3.3. A Strict app started from a terminal should print why it can't see its arguments. Test
the rule without stubbing it.

**Status: fixed, as the owner decided.** 17.3.3, 4.9.2, 4.3.1.1 and 17.4 are updated.

- **Detection.** The new `appkind` module decides an app's kind:
  - an AppImage, from the `Terminal` key of its root `.desktop`, read out by its own runtime inside
    the unpacking's bwrap;
  - a tarball, from its `.desktop` files, or else from the display libraries its program links (a
    small ELF reader).
- **Where it's applied.** `install._apply_kind()` runs right after the files are placed. It records
  `appKind`, asks the backend for the grant set again with the kind, and leaves a tool's menu entry
  out when that option was only Settings' default.
- **Precedence.** `Backend._is_cli()` is now the user's `cliKind`, then `appKind`, otherwise an app;
  the menu-entry rule is gone.
- **The dialog.** The install dialog has "It is: …", and an untouched Sandbox card follows it live.
  Correcting the kind on an installed app with no sandbox of the user's own re-applies the default
  at once, audited.
- **The Strict note.** A Strict launcher started from a terminal with arguments says on stderr why
  it can't see them. The strict golden shows the three lines.

Tests:

- `tests/test_appkind.py`: synthetic ELFs at 64 and 32 bits, ten library sets, `.desktop`
  precedence, and the sandboxed runtime command;
- install against a local server: CLI and GUI tarballs, the menu default, the user's word winning;
- backend precedence (the old rule's shape no longer counts; an unreviewed tool gets `cli-tool`);
- the dialog contract: the kind choice moves the card, and is saved and cleared;
- tier 2: an AppImage's kind read by its runtime under real bwrap (Terminal true and false, no
  `.desktop`, a hostile symlink), and the Strict note on a pty but not on a pipe.

Tier 1: 2,114 passed, 105 skipped. Tier 2 (Mint 22.1): 96 / 2.

### F5. The startup pass brings the launcher up to date, but not the helpers it relies on — MEDIUM (17.4; round four R4-4's class; run)

**Requirement.** 17.4: a launcher that isn't "the text AppKata would write today" is rewritten at
start, "so a launcher fix reaches every installed app at the next start".

**Code.** `install.launcher_is_current()` (`install.py:426`) compares the launcher text only. The
files the launcher calls are written only by `sandbox.write_launcher()` (`sandbox.py:1470`): the
`xdg-open` shim, the file-argument helper, the seccomp filter and the per-app `.flatpak-info`. The
launcher's text holds their paths, not their contents.

**Evidence (run, tier 1, probe `test_probe_helpers.py`).** After a heal, overwriting the shim, the
helper and the marker with an older AppKata's text and running `_heal_launchers()` returns `[]`, and
all three stay old. Round five's R5-6 fix lived entirely in the shim; under this pass it would have
reached no installed app until something else rewrote that app's launcher. An older marker without
`[Context] shared=network` makes GLib report no network to an app that has the grant (the claims
table's NetworkMonitor row).

**Which is right.** The requirement. **Fix:** "current" covers every file `write_launcher` writes,
compared one by one or as a fingerprint. **Test:** corrupt each one and check the startup pass
restores it (class C).

**Status: fixed.** `sandbox.helpers_current()` compares each file the launcher calls by path with
what AppKata would write today: the app's marker, the shim and its exec bit, the file-argument
helper and the seccomp filter. `install.launcher_is_current()` now requires it, so the startup pass
rewrites the launcher, and with it those files, when any differs. 17.4 says so.

The class-C harness, `test_the_startup_pass_restores_every_file_the_launcher_relies_on`, has five
cases: the shim, the shim's mode, the helper, the marker, and the filter. All five fail on the code
before this commit. The golden startup test now pins this half, since it tests the text's.

Tier 1: 2,070 passed, 99 skipped. Tier 2 (Mint 22.1): 90 / 2.

### F6. `.` or a relative path given to a non-CLI app from inside a granted folder opens the private home — LOW–MEDIUM (17.6.2 silent; run)

**Status: fixed in review 3's fix pass** (see review 3, Fixes): such a path now becomes the path the
app sees it at, inside the grant.

**Evidence (run, Mint 22.1, probe `test_probe_run.py`).** The developer template, with `~/Projects`
granted read-write, was started from `~/Projects` as `codium . notes.txt src/main.c
~/Projects/notes.txt`. `PWD` inside is the private home and `.` lists the private home. `notes.txt`
and `src/main.c` fail with "No such file or directory"; only the absolute path works. From a folder
that *isn't* granted, the same relative file works, because it is handed over with an absolute
path. So the granted case is the broken one, and `codium .` is the developer template's own use.

**Code.** A non-CLI app always gets `--chdir "$HOME"` (`sandbox.py:1443-1444`). The file-argument
helper (`sandbox.py:880-882`) leaves an argument inside a granted folder as it was, relative or not.

**Requirement.** 17.6.2 says a file inside a granted folder "keeps its real path". Neither it nor
17.4 says what a non-CLI app's working directory is.

**Fix.** The helper makes every path argument absolute (from the caller's directory) before
deciding. A non-CLI app starts in `$PWD` when that lies inside a granted folder, otherwise in the
private home. Say so in 17.6.2.

### F7. The session warning clears any desktop that lists GNOME, and tells X11 users that KDE closes the leak — LOW (17.9; run, compositor facts read)

**Status: fixed in review 3's fix pass** (see review 3, Fixes): the warning also reads the
compositor's globals, the X11 advice names GNOME alone, and the tour shows the product's text.

**Requirement.** 17.9: "Only GNOME Wayland needs no warning: the rule is that allowlist".

**Code.** `_CLEAR = ("gnome",)` is matched as a substring of the whole `XDG_CURRENT_DESKTOP`
(`sandbox.py:564, 578`).

**Evidence (run).** On Wayland, `Budgie:GNOME` and `Phosh:GNOME` get no warning. Phosh's
compositor, phoc, is wlroots-based, and Budgie 10.10's Wayland session runs on labwc, also wlroots.
Those compositor facts were read, not run here. So the allowlist is wider than GNOME.

**Two more texts disagree.** The X11 warning (`sandbox.py:595-597`, run) says "Log into a Wayland
session (GNOME or KDE) to close this", but R7-1 showed KDE leaks the clipboard. The tour's demo
warning (`backend.py:1639-1644`) still says "true on X11 and on wlroots Wayland … a GNOME/mutter
Wayland session closes it". That is the pre-R5-1 wording, and it is what the committed screenshots
show (A20, A21, A25, C11, X15), not what the product says.

**Which is right.** The requirement. **Fix:** decide from the compositor, not the desktop's name.
The leak is which Wayland globals an ordinary client is offered: `zwlr_screencopy_manager_v1`,
`zwlr_data_control_manager_v1` or `ext_data_control_manager_v1`, `zwp_virtual_keyboard_manager_v1`
and `org_kde_kwin_fake_input`. AppKata can list these itself with one registry round trip on
`$WAYLAND_DISPLAY`, as the `wayland` and `kwin` harnesses already do. Drop "or KDE" from the X11 text,
and have the tour show the product's own text.

### F8. Nothing says what a review may do: one Trust can turn the sandbox off, and the never-shared list doesn't cover the secrets the goals name — MEDIUM (requirement gap: 17.3.1, 17.3.2, 17.11; run)

**The goal.** The PR's first goal is "Secrets stay private. It can't read SSH keys, browser profiles,
tokens …". The never-shared list (17.3.1) covers persistence, plus `~/.ssh` and `~/.gnupg`.

**Evidence (run).** `protected_folder` returns *shareable* for all of these:

- `~/.mozilla/firefox` (Firefox profiles and saved logins);
- `~/.var/app` (every Flatpak app's private data, while AppKata's own sandbox homes are protected);
- `~/.aws`, `~/.config/gh`, `~/.git-credentials`, `~/.netrc`, `~/.docker` and `~/.kube`;
- `~/.password-store` and `~/.local/share/keyrings`.

The Chromium family's profiles are refused, but only as "a folder above" their
`NativeMessagingHosts`.

**Evidence (run).** `sandbox.choose()` with one Trust's `Sandbox: off` and no choice of the user's
returns `reviews` at level `off`, so a fresh install runs unsandboxed. The card shows "Off ·
suggested by …". 17.3.2's merge means "one careless reviewer can't widen an app". That holds across
Trusts, but when only one Trust has a `Sandbox` line, its review is the whole input.

**Gap.** The requirements never say whose mistakes the never-shared list guards against: a careless
reviewer, a compromised one, or the user. So neither the list's scope nor `Sandbox: off` can be
judged against them.

**Recommend (an owner's decision).** State the review threat model in 17.3. If reviews come from
people the user trusts but who may be wrong or compromised, a review may narrow access, but it may
not widen it past the kind's default without an explicit click at install. A suggestion of Off, or
of a folder outside the XDG user dirs, would show as "X asks for … — Allow?". Separately, add a
*secrets* class that reviews can't grant (the user's own picker still can, with a warning).

**Status: fixed, as the owner decided.** Requirement 17.3.5 is new, and 17.3.1, 17.3.2 and 17.11 are
updated.

- **Off is only a suggestion.** `sandbox.choose()` no longer applies merged reviews that say Off:
  the reviewed baseline applies instead.
- **"Use theirs".** `Backend.useSuggestion()`, behind "Use theirs" in the Sandbox dialog and the
  review badge, adopts a suggested Off as the user's own `{template: off}`. Any other suggestion is
  adopted as before. The install card shows "X suggests running it with no sandbox. Use theirs".
- **The secrets class.** `sandbox.secret_folder()` covers Firefox's and Thunderbird's profiles,
  `~/.var/app`, `~/snap`, cloud, forge and registry credentials, password stores and keyrings, with
  anything inside or above them.
- **Where secrets are stripped.** A review-sourced grant set loses them in `_resolved_sandbox` and in
  the suggestion, so they are never pinned or bound, and the chips show "refused: a review can't
  grant …". The user's own grant stands, with a "holds passwords or tokens" warning chip.

Tests:

- tier 1: the Off rule (alone, beside another Trust, and the user's own Off); fourteen secret paths
  refused from a review but allowed, with a warning, for the user; ordinary folders untouched;
- backend: a review's `~/.aws` refused and never pinned; the user's own kept with a warning; a
  review's Off needing "Use theirs"; "Use theirs" for an ordinary suggestion; `useSuggestion` in the
  audit table;
- the dialog contract: the install card's Off sent only after the click.

Tier 1: 2,091 passed, 99 skipped. Tier 2 (Mint 22.1): 90 / 2.

### F9. Reviews can express three of the grant set's dimensions, and AppKata never writes them — LOW–MEDIUM (10.3.1, 8.4.7, 17.3.1; read)

**What a review can say.** 10.3.1 has three lines: `Sandbox`, `Sandbox folders` and `Sandbox
network`. A review can't override sound, devices, capabilities or the writable app folder; it can
only pick a template that has them. The design doc's Portable point 1 says of the writable app
folder that "a reviewer's settings line can set it up front", but no such line exists.

**What AppKata writes.** 8.4.7: saving a review writes "the install and Source options". The user's
sandbox choice isn't among `reviewData()`'s `installSettings` (`backend.py:1464` onward), so a
reviewer's own sandbox is never written. The writer's support for the lines (`PLATFORM_SPECIFIC`,
`_format_value`) only round-trips lines typed by hand. Nothing checks such a line as it is written,
so a reviewer gets no "refused folder" feedback; F1 shows why that matters.

**Which is right.** The design's intent: reviews are the main source of sandbox suggestions (17.11).

**Recommend.**

- Write the user's sandbox choice into their review as `Sandbox*` lines: the template, plus the
  overrides the vocabulary can express.
- Add at least a writable-app-folder line to 10.3.1.
- Say in 17.3.1 that the other grants come only from templates.

### F10. Three templates promise a folder they don't have, and the dialog can only add read-write folders — LOW (17.3, 17.2.1, decision 4; read)

**Templates.** 17.3's table gives offline-editor "one picked docs/pictures folder", media-player "a
media folder (read-only)" and developer "a projects folder (rw)". The blurbs say "A folder you
pick…" and "Plays a media folder…". In code all three have `folders={}` (`sandbox.py:91-95`), and
picking one in either dropdown asks for no folder.

**Read-only folders.** The Customize picker adds every folder read-write
(`SandboxDialog.qml:74`); the row's pill shows the mode, but nothing changes it. 17.2.1 says a grant
is "read-only or read-write". So media-player as specified, with a read-only media folder, can't be
made in the UI; only a review's `:ro` can make it.

**The template's name is lost.** Adding a folder saves the set as `{custom: …}`, so from then on the
app's template reads "Custom" in App Detail and the Audit, and "Reset to template" is gone. The
config format already supports `{"template", "overrides"}` (`apply_overrides`), which would keep the
name.

**Decision 4** (PR body and design doc) promised one-click grants for Documents, Downloads, Pictures,
Videos and Music through the XDG user dirs. They aren't built, and they aren't in §17.

**Which is right.** The requirement, for read-only and read-write folders. For the folder templates,
decide one of two: the dialog asks for the folder when such a template is picked, or the table says
"no folder until you add one". Either way, save a customization as template plus overrides.

### F11. The launcher text is neither shown nor audited, and the Audit doesn't say what changed — LOW (17.4, 17.16; read)

**Showing and recording the text.** 17.4 says the launcher's text "can be shown in App Detail ('Show
the launch command') and is recorded in the Audit". `Backend.sandboxLaunchCommand`
(`backend.py:1837`) exists, but no QML calls it, and no audit entry contains launcher text.

**What changed.** 17.16 "records every change of a sandbox level, grant or template". The entry's
detail is only `{template, level}` (`backend.py:1885-1887`), so a Customize change that adds
`~/Documents` reads "set the sandbox of X · Custom · standard". The Audit can't say when an app got a
folder. `tests/test_sandbox_audit.py` checks only (kind, action, subject). Startup heals that rewrite
a launcher, and the apps sandboxed after setup, are not audited at all.

**Which is right.** The requirement.

**Recommend.**

- Add a "Show the launch command" link in App Detail.
- Make audit details carry the grant diff: folders, network, sound, devices and services added or
  removed.
- For a launcher rewrite, record a hash of the new text.
- Test the details, not only the action.

### F12. "Offers on first need" and "if declined" describe a prompt that doesn't exist — LOW (17.10; read)

**What is specified.** 17.10: on first need AppKata "offers a one-time setup … If declined, the app
runs Off with a warning". The design doc agrees ("offers to set it up the first time a sandbox is
actually needed"), and test plan cases A1 and A2 test that prompt.

**What is built.** There is no prompt. Instead, the install card prints "Set it up in Settings →
Sandbox" (`InstallDialog.qml:244`), App Detail shows a standing banner with Enable…
(`AppDetail.qml:130`), and Settings has Set up…. `declineSandboxSetup` (`backend.py:1983`), the
`sandboxSetupDeclined` preference and `sandboxSupport.declined` are never used by the UI.

**Two related faults.**

- Settings' "unsupported" hint says "bubblewrap isn't installed" (`SettingsDialog.qml:192`). It says
  this even when bwrap is present and only xdg-dbus-proxy is missing; App Detail's text is right.
- `have_tools()` requires xdg-dbus-proxy at every level. So on such a system a Strict app, which uses
  no proxy, runs entirely unsandboxed.

**Which is right.** The code's standing indicators are a sound design, so 17.10 and the test plan
should describe them. Remove the dead decline state, and let Strict need only bwrap.

### F13. Enabling a sandbox warns after the fact, and the heal pass enables it without any warning — LOW (17.13; read)

**Requirement.** 17.13: enabling a sandbox after install "warns that the app is effectively being
reinstalled and its configuration may be reset".

**After the fact.** The code shows a toast after Save (`backend.py:1889`), so the user is told only
once the change is made.

**No warning at all.** Apps installed while setup was pending, or while tools were missing, ran Off
with their settings in the real home. When setup succeeds, `_heal_launchers` sandboxes them all, and
the only message is "Sandbox support is set up. Sandboxed apps will now run contained."
(`backend.py:1975`). Each of those apps then starts with an empty private home.

**Which is right.** The requirement.

**Recommend.** Say it in the Sandbox dialog before Save, when the app is installed and currently
Off. Say it in the setup flow too, for example "3 apps will start with fresh settings".

### F14. App logs are keyed by name, so two installs with one name share one log — LOW (14.2.1; R6-1's class; read)

R6-1 gave each install its own id, but `applog.app_log_path(name)` (`applog.py:101`) and the
launcher's baked `log=` use the app's name. Two "Notes" apps from two Sources append to one
`logs/apps/Notes.log`. The toast for one can show the other's last line, and `_running_at` can read
the other's start mark. 14.2.1 itself says `<name>.log`, so fix both the requirement and the code to
use the install id.

### F15. Nothing says what happens to accessibility, input methods and regional formats — LOW (requirement gap: 17.4's allow-list, Limits; read)

**Status: decided and fixed in review 3's fix pass** (see review 3, Decisions and Fixes): formats,
time zone, scaling and input methods reach the app, the proxy with the network grant; accessibility is
stated as a limit, its filtered proxy in 17.18.

This touches the goal "Normal apps keep working". The launcher's environment allow-list
(`sandbox.py:1042-1047`) and the proxy rules leave out four things:

- **Accessibility.** There is no AT-SPI bus, so screen readers can't see a sandboxed app. The
  `org.a11y.Bus` name is filtered out and `$XDG_RUNTIME_DIR/at-spi` isn't bound. Flatpak runs a
  second proxy for it.
- **Input methods.** There are no input-method variables (`GTK_IM_MODULE`, `QT_IM_MODULE`,
  `XMODIFIERS`) and no IBus or Fcitx portal. On X11, Mint's default session, CJK input stops working
  in sandboxed apps.
- **Regional formats.** Only some `LC_*` variables pass. `LC_PAPER`, `LC_MEASUREMENT`,
  `LC_MONETARY`, `LC_ADDRESS`, `LC_TELEPHONE`, `LC_NAME` and `LC_COLLATE` don't, though GNOME and
  Cinnamon set them from "Formats".
- **Proxies.** No proxy variables pass (`http_proxy`, `https_proxy`, `no_proxy`).

None of these is in §17, the Limits or the claims table. **Recommend:** decide each one (pass it
through, or state it as a limit), and run AT-SPI and IBus in the session image.

### F16. When a system loses sandbox support, the next update or sandbox change runs the app Off without asking — LOW (17.10; read)

`_sandbox_for_install` (`backend.py:1752`) returns `None` whenever tools are missing or the probe
fails, and `_sandbox_launcher` (`install.py:394`) then removes a working launcher. So an update, a
rollback or a sandbox change can silently de-sandbox the app if it happens while the probe fails,
until a later start heals it. The probe can fail because:

- a bwrap earlier on `PATH` isn't the one the profile names;
- the profile was removed;
- it timed out once, and the result stays cached for the whole process.

17.10 covers only a declined first setup. **Recommend:** once an app has a launcher, keep it; if a
launch then fails, it is reported (14.2.1). Say so in 17.10.

### F17. 17.1's platform claim is narrower than 1.1's platform list — LOW (17.1; run)

**Status: the claim is fixed** (review 3, Fixes; a Rocky 9 tier came with E3). Debian 12, Fedora 39
and arm64 still have no tier, and 17.1 says so.

17.1 says "the launcher tests run on both ends of what the supported platforms ship". But 1.1 also
supports Debian 12+, Fedora 39+, RHEL/Alma/Rocky 9+ and arm64.

Run: Rocky 9 ships bubblewrap 0.6.3, which is fine. It also ships xdg-desktop-portal 1.12.6 and GLib
2.68.4, older than the oldest tested (1.14 and 2.72). Fedora and Debian never ran, and nor did
arm64's seccomp filter (`_IOCTL_NR["aarch64"]`). **Recommend:** say "the Ubuntu/Mint family, x86_64"
in 17.1, or add a Rocky 9 tier, the cheapest gap to close (an older portal and GLib).

### F18. Every sandboxed app sees the host's hardware in `/sys` — LOW (17.4, 17.17; read)

**Status: stated, as the owner decided** (review 3, R3-7): 17.4 and 17.17 say it; narrowing `/sys`
is in 17.18.

`build_launcher` binds `/sys/block`, `/sys/bus`, `/sys/class`, `/sys/dev` and `/sys/devices`
read-only at every level (`sandbox.py:1368-1369`), for GPU identification. That exposes
`/sys/class/net/*/address` (MAC addresses) and world-readable USB serials, a stable fingerprint, even
to a Strict app with no network. Flatpak does the same. None of it is in 17.4, the Limits or the
claims table. **Recommend:** state it in 17.17, or narrow the binds to what `drmGetDevices2` reads
(`/sys/dev/char` and the DRM devices' subtrees).

### F19. A later app with the same name inherits the private home an uninstalled one left behind — MEDIUM (17.6, 17.14; R6-1's class, in sequence; run)

**Requirement.** 17.6 says two Sources' apps with one name each get their own private home, and
"uninstalling one leaves the other whole". 17.14 says uninstalling *offers* to remove the home, and
the dialog's checkbox starts unticked (`ConfirmDialog.qml`, `deleteSandboxHome: false`).

**Code.** `install.new_app_id()` looks only at the installs table. Once an app is uninstalled its id
is free, but its private home is still at `sandboxes/<id>`.

**Evidence (run, tier 1, a one-off script).** Install "Notes" from `github.com/alice/notes`; it gets
id `notes`, and its home holds `.config/notes/session-token`. "Notes" from
`codeberg.org/mallory/notes` would get `notes-2` while Alice's is installed. Uninstall Alice's,
keeping its home as the dialog suggests. Mallory's now gets `notes`, and with it Alice's home and
token.

**Why it matters.** R6-1 closed this for two apps installed side by side; it is still open for two
apps installed one after the other. The second app can be a lookalike from another Source, and it
starts with the first app's accounts, cookies and tokens.

**Which is right.** The requirement. **Fix:** record which app (URL) a kept home belongs to, in
`.identity/`, and skip an id whose home belongs to another URL. Reinstalling the *same* app still
gets its old home back. Add the sequential case to `tests/test_sandbox_two_apps.py`.

**Status: fixed.**

- **The record.** `sandbox.record_home_owner()` writes the app's URL to
  `sandboxes/.owners/<id>`, beside the homes and never inside one. It does so whenever a launcher is
  written, and `remove_sandbox_home()` removes it with the home.
- **The id.** `install.new_app_id()` skips an id whose home belongs to another URL. A home with no
  owner recorded, from before this commit, counts as another's: the worst case is a fresh home for a
  reinstall, never someone else's.
- **Requirements.** 17.6 and 17.14 say so.

Tests (tier 1, the class-G sequence in `tests/test_sandbox_two_apps.py`):

- `test_a_later_app_with_the_same_name_never_inherits_a_kept_private_home` fails on the code before
  this commit. A third "Notes" got `notes` and the first app's token.
- `test_a_home_removed_with_its_app_frees_the_name`.

Tier 1: 2,065 passed, 99 skipped. Tier 2 (Mint 22.1): 90 / 2.

### Smaller mismatches (nits)

**Status: fixed in review 3's fix pass** (see review 3, Fixes); the three that change the UI — the
review badge's wording, the widened-Strict blurb, the orphaned home — in its second pass, after the
owner's decisions (bd4158c, 180de8c, c943a93). 17.10.1 had already been put right by F2's fix.

**Template and review values**

- **`standard`:** 10.3.1 lists seven template names plus `off`, but the code also accepts `standard`
  (run), and both dropdowns offer it. 17.3's table has no row for it, so its contents (network and
  notifications) are code only.
- **Strict's devices:** 17.3's table says Strict has no devices, but every template, Strict included,
  carries the X11 grant (17.2.1 and 17.9 say so).

**Wording in §17**

- **Introspectable:** 17.5 says "nothing else on that name", but the proxy also allows
  `org.freedesktop.DBus.Introspectable` on the portal object, for `gdbus` (`sandbox.py:768-770`).
  That is harmless, but it should be said.
- **Order:** 17.6.2 comes before 17.6.1 in the document.
- **bwrap path:** 17.10.1 says "on `/usr/bin/bwrap`", while 17.10 says the profile names the bwrap
  actually installed.
- **Wrong cross-reference:** 17.14 cites "(4.5)", which is Foreign installs; uninstalling is 4.7.
- **Tray pids:** 17.17 says "process 2 (or 3) … `-2-1`", but the proxy has owned pids 2–6 since R6-3.
  The collision still holds; only the numbers are old.
- **Extracted folder:** 17.7 says the folder is "droppable at Off", while decision 2 says it is kept
  as a cache. The code keeps it, so choose one wording.

**Other sections not updated for sandboxing**

- **4.3.1.2** says "Launchers and command links point at the stable name"; for a sandboxed app they
  point at `<app>/run` (17.4).
- **4.9.2, 4.9.3 and 4.9.5** don't mention the Sandbox card. 4.9.5's "changes apply from the next
  update" is wrong for it, since it applies at once (R4-3).
- **11.1** lists the Settings groups in order, without Sandbox.
- **13.3** lists what the Audit records without the sandbox entries, and its Settings line lacks
  "enabled system sandbox support".

**UI text**

- **Review badge:** 17.11 says "the UI says the app may be partly non-functional until reviewed",
  but the badge (`AppDetail.qml:119`) says only "Running with your current sandbox. X suggests …".
- **Templates row:** Settings' "Built-in templates" row omits Standard, which both dropdowns offer.
- **Widened Strict:** a Strict set widened by a grant reads "Standard · customized" with Standard's
  blurb ("Network and notifications") over a set that has neither.
- **Orphaned home:** the uninstall dialog offers to delete the sandbox home only while the level
  isn't Off. An app switched to Off keeps an orphaned home, and the dialog doesn't offer to delete it.

---

## Docs that disagree with the spec or the code

### D1. The documents §17 delegates to specify the design before finding 0, and the release gate runs them — MEDIUM

17.4 says "the exact launcher and proxy shape is specified in `local-proxy-test-plan.md`", and 17.18
says the real-hardware validation still owed is that file's checklist, run by
`scripts/sandbox/field-test.sh`. Both still describe the planning-stage design (the file's status
line still says "Status: planning").

**The spec section of `local-proxy-test-plan.md`:**

- The marker sits at `$home/.flatpak-info`, inside the app-writable home. That is the escape fixed by
  016476a.
- The marker is bound in *both* the proxy's and the app's bwrap, which finding 0 removed.
- `instance-id=<random per launch>`, where the code uses the install id.
- The proxy runs under `--ro-bind / /`.
- "Depended on by the document portal", which is no longer true.
- "Open (requirement 17.6.1) … can't pass until that decision is made", though it was decided.
- The capability table: Camera through "camera portal + PipeWire" (the portal is denied, R6-2), and
  tray names `-2-1 … -3-3`.
- The CLI tool's bind is `--bind "$PWD" "$PWD"`, with none of the never-shared checks.

**The checklist:**

- A1 expects a prompt at the first sandboxed launch (F12).
- P2 picks a file in the portal chooser and expects the app to open it. The decided design uses the
  app's own dialog, so P2 can't pass as written.
- U1 checks a "Disable the app's own updater" option (F3).
- D5 expects recording to be refused without the grant (17.8 says it can't be).

**`field-test.sh`.** Its header says "AppKata's own sandbox code isn't built yet". It reproduces
commands by hand, with the marker on the proxy, `--talk=org.freedesktop.portal.Desktop` (the whole
portal name) and `--new-session`, rather than running a launcher AppKata generates. On Mint 22 its
portal checks would report the refusal finding 0 was about, and none of its passes would say
anything about the code under review.

**Fix.** Make the goldens in `tests/data/launchers/` the launcher spec (17.4 → them), and cut the
test plan's spec section down to what the goldens can't show. Rewrite the checklist for the decided
design. Have `field-test.sh` install a small archive through `appkata_core.install` and run *its*
launcher, as round nine's end-to-end test does, then add the visual checks on top.

**Status: fixed** (69dc368).

- **`local-proxy-test-plan.md`** is rewritten. The launcher's exact text is the goldens, and 17.4
  points there. The file explains the launcher part by part as built, along with the proxy (no
  marker, its own pid namespace, the per-interface rules), the marker and an accurate capability
  table. Its checklist now matches the decided design and what the field test checks.
- **`scripts/sandbox/field-test.sh`** now runs `fieldtest.py`. That installs a probe app through
  `install.install()` from a local HTTP server and runs the launchers AppKata writes for Strict,
  Online app and CLI tool. It answers twelve checks by itself and asks the tester seven questions,
  all in a throwaway home.
- **Found while rewriting.** The old script's "secrets" check wrote `FIELDTEST-SECRET` into the
  tester's real `~/.ssh/id_ed25519`, and its cleanup then deleted that file. Run on a real desktop,
  it destroyed the tester's SSH private key. It also wrote into the real `~/.themes` and
  `~/.local/share/appkata`.

Tests (class F):

- `test_the_field_test_checks_the_product_and_leaves_the_testers_home_alone`, tier 2: the script run
  non-interactively; the tester's home byte-identical afterwards; every automated row PASS or
  BLOCKED;
- `tests/test_sandbox_docs_current.py`, tier 1: none of the identifiers finding 0 and this review
  retired may appear in the documents 17 delegates to. Run against the old files, it fails.

Tier 1: 2,116 passed, 106 skipped. Tier 2 (Mint 22.1): 97 / 2.

### D2. Stale summaries — LOW

**Status: fixed in review 3's fix pass** (see review 3, Fixes), the PR body's history paragraphs aside.

- **`gaps.md` §16:**
  - Item 7 says v1 warns on "X11 and wlroots sessions; mutter Wayland is clear", but since R5-1 it
    warns on every compositor except GNOME's, and on KDE about the clipboard.
  - Item 9 says "sandboxing requires and warns it" (F3).
  - Item 11 says the document portal relies on `.flatpak-info`, which finding 0 changed.
  - Item 12 lists "seccomp" as not yet done, but there is a terminal-injection filter.
- **README row:** says sandboxing is "Planned".
- **`app-sandboxing.md`:**
  - Its header says "Decisions 1–19 … taken through four review rounds".
  - Round 2 still offers "a no-root fallback" through Landlock, which decision 6 rejects.
  - Plan step 5 says the warning covers "X11/wlroots".
  - "How templates are presented" says App Detail shows the template name as a chip, which it doesn't.
- **PR body:**
  - It says "14 decisions" and calls the implementation "one commit", against 142.
  - It reports "189 passed / 35 skipped".
  - Round 1 says "AppImages are unpacked at install time", against decision 2.
  - Decision 4's folder grants were never built.
  - "Still owed" names the tray watcher twice, and still lists Qt 6.5+'s dialog, now run in
    `filedialogs-qt68`.
  - The 🤖 footer sits in the middle, with rounds five to nine appended after it.

---

## Does all the code have requirements?

Most of it does: every function in `sandbox.py` maps to a §17 item, and the traceability table
below lists them. The exceptions follow.

**Behaviour in the code that no requirement states** (only some is in the design doc):

| Behaviour | Where | Says it |
|---|---|---|
| What makes an app a CLI tool: command link on, app menu off | `backend.py:1653` | nothing (F4) |
| The `standard` template's grants (network, notifications) | `sandbox.py:90` | nothing; 17.3.3 names it as a baseline |
| One review's `off` adds no limit when merged (off ∩ X = X) | `sandbox.py:338-341` | c97ef39's message only |
| `/sys` binds, `/var/cache/fontconfig`, `/dev/dri` at every level | `sandbox.py:1354-1369` | design doc point 9 (F18) |
| DNS: binding `/run/systemd/resolve` or resolv.conf's target | `sandbox.py:1305-1313` | design doc only |
| The environment allow-list's contents | `sandbox.py:1042-1047` | design doc point 4, partly (F15) |
| Extraction stamp, lock, staging, no timeout or size limit | `sandbox.py:1101-1133` | design doc AppImage point 2 |
| `Introspectable` allowed on the portal | `sandbox.py:768-770` | nothing (nit) |
| The options in Settings' default dropdowns (GUI: strict, standard, off; CLI: cli-tool, strict, off) | `SettingsDialog.qml:203-215` | 17.15 says only "by kind" |
| `ports` and per-port intersection; `exec_deny` merged and stored, never enforced | `sandbox.py:47, 317-326` | deferred (17.18); fine, but nothing uses `ports` |

**Code that nothing uses.** `sandboxLaunchCommand` (F11), `declineSandboxSetup`,
`sandboxSetupDeclined` and `sandboxSupport.declined` (F12), and `sandboxInfo().selfUpdating` (F3).

**Changes on the branch outside sandboxing**, each sound but with no §17 requirement:

- The `_plain()` QJSValue fix across non-sandbox slots: Add source, Source settings, Save review, the
  channel cards and `setPref` (4de6722). It is a real cross-platform bug fix, and deserves its own
  line in the PR body or its own PR.
- `docs/gpg.md` and `docs/github-workflows.md` (494868b). The design doc calls them "each its own
  PR".
- The Windows VM container rename and its notes (09bfffe, `docs/build.md`,
  `scripts/test-windows-vm.sh`).
- About 80 regenerated screenshots of non-sandbox screens, and `/temp/` in `.gitignore`.

14.2.1 (an app's own log) covers every portable launch, not only sandboxed ones. It is specified, but
it is a behaviour change for every Linux app AppKata starts, so it is worth a line in the PR body.

---

## Traceability: §17 against the code

✔ built as written · ◐ partly · ✘ not built or contradicted. The evidence for ✔ rows is in
`app-sandboxing-1.md` and the claims table.

| Req | What it says | Code | Status |
|---|---|---|---|
| 17.1 | portable kinds; bwrap + proxy; tested on both ends | `_resolved_sandbox` kinds, `have_tools` | ◐ claim narrower than 1.1 (F17); proxy required even for Strict (F12) |
| 17.2 | Off / Standard / Strict table | `normalize`, `uses_bus`, `build_launcher` | ✔ |
| 17.2.1 | grants; Strict drops them; dialog flips | `normalize`, `SandboxDialog.setField` | ◐ no read-only folders in the UI (F10) |
| 17.3 | seven templates | `TEMPLATES` | ◐ folder columns (F10); `standard` missing (nit) |
| 17.3.1 | overrides; never shared, whoever asks | `apply_overrides`, `protected_folder` | ✘ relative paths (F1); list scope (F8) |
| 17.3.2 | least-privilege merge | `intersect`, `resolve` | ✔ (off-adds-no-limit is code only) |
| 17.3.3 | defaults by kind and review state | `default_template`, `_is_cli` | ◐ "CLI tool" undefined (F4) |
| 17.3.4 | personal and reviewer templates deferred | — | ✔ |
| 17.4 | the launcher; regenerated at start; shown and audited | `build_launcher`, `launcher_is_current` | ◐ helpers not refreshed (F5); not shown or audited (F11); cwd (F6) |
| 17.5 | proxy rules | `portal_rules`, `proxy_args` | ✔ (Introspectable nit) |
| 17.5.1 | capabilities | `CAP_PROXY_ARGS` | ✔ (the secrets cost is in the UI, not the requirement) |
| 17.6 | identity; one id per install | `app_identity`, `new_app_id` | ✔ (logs keyed by name, F14) |
| 17.6.1 | host caller | proxy without marker | ✔ |
| 17.6.2 | file arguments | `FORWARD_HELPER` | ◐ relative arguments (F6) |
| 17.6.3 | own dialog; OpenURI; shim | `GDK_DEBUG`, `XDG_OPEN_SHIM` | ✔ |
| 17.7 | lazy sandboxed extraction | `_EXTRACT_BLOCK` | ✔ |
| 17.7.1 | writable app folder | `write_app` | ◐ doesn't help an AppImage's updater (F3) |
| 17.8 | sound and camera | sound binds, camera devices | ✔ |
| 17.9 | display; warning allowlist | `session_warning` | ◐ substring allowlist; X11 text; tour text (F7) |
| 17.10 | AppArmor; offer on first need; declined | `install_profile`, banners | ✘ on 26.04 (F2); ◐ no offer or decline (F12); fail-open (F16) |
| 17.10.1 | the profile's cost | Settings and banner text | ✘ on 26.04 the rejected design is Ubuntu's default (F2) |
| 17.11 | pin and badge | `choose`, `keepSandbox`, `setSandbox(None)` | ✔ (badge wording, nit) |
| 17.12 | "Disable the app's own updater" | — | ✘ (F3) |
| 17.13 | warn on enabling | toast after Save | ◐ (F13) |
| 17.14 | offer to remove the home | `ConfirmDialog`, `uninstallSandbox` | ✔ (Off-switched apps, nit) |
| 17.15 | Settings → Sandbox | `SettingsDialog` | ✔ ("unsupported" text, F12) |
| 17.16 | audit every change | `_audit` calls | ◐ no grant detail; heals unaudited (F11) |
| 17.17 | limits | — | ◐ misses `/sys` (F18), relative args (F6), F15 |
| 17.18 | deferred; field checklist owed | — | ◐ checklist stale (D1) |
| 10.3.1 | `Sandbox*` lines | `trustfile` | ◐ `standard` omitted; vocabulary (F9) |
| 14.2.1 | an app's log | `applog`, launcher | ✔ (keyed by name, F14) |

---

## Checked, no finding

- **The install dialog's answer reaches the sandbox resolution in time.** Suspected: the worker read
  the app's cached options from before the dialog's Save. Probe: the worker's `_is_cli` sees the
  dialog's answer (`cli-tool`). Only the card is stale (F4).
- **RHEL 9's bwrap is new enough for the launcher.** Run: bubblewrap 0.6.3 on Rocky 9, at or above
  17.1's 0.5. The portal and GLib versions are what's old (F17).
- **Nested grants with a relative link.** Suspected: round two's "nested grants can't reopen the
  symlink hole" was argued for an absolute link target only. Run with `..`: the inner grant is a
  mount point inside the sandbox, so the app can't replace it ("Device or resource busy"). The
  conclusion holds, though for that reason rather than the one in the comment at
  `sandbox.py:1156-1159`, which should say so.
- **Ubuntu 24.04 with AppKata's profile: Chromium's sandbox has what it needs.** Round 2 claimed
  this from Obsidian alone; the KVM probe now shows it directly. Inside Strict and Standard
  launchers a nested user namespace is created with capabilities, mounts a tmpfs and `chroot`s. The
  claim holds on 24.04 and fails on 26.04 (F2).
- **Tier 1 at 76edcf4:** 2,042 passed, 90 skipped, as round nine recorded.

---

## Classes, and the harness for each

Each finding above has a class, following the method `app-sandboxing-1.md` closes with. Each class
should get a harness that catches it. Build the harness in its own commit, showing it failing with
the fault re-introduced, and record it here once built.

| Class | Findings | Harness |
|---|---|---|
| **A. The check and the enforcement read a path differently.** AppKata's verdict comes from Python's `realpath` against its own working directory and a home it computed. bwrap's mount comes from the host root at launch. | F1 (also behind R2, R4 and R5 in round two) | A *differential* run test. For every entry in a much larger path corpus (relative, bare words, `run/user/<uid>`, `~user`, `..`, symlinked parents, paths outside home), generate the launcher, run it, and from **inside** try to read `~/.ssh/id_ed25519`, write the real `~/.bashrc`, and connect to `$XDG_RUNTIME_DIR/systemd/private`. Assert the verdict from inside, never the launcher text. |
| **B. A decision recorded but never built.** | F3, F10 (decision 4), F11, F12, F13 | A *requirements traceability* test, like the claims-table test. Each §17 sentence that promises behaviour gets a row naming the test that shows it; a row without a test fails the local tier. A second check fails when a Backend slot or property is never referenced from QML or tests. |
| **C. State outside the launcher text.** | F5 | The startup-pass test, made general. Corrupt or replace each file `write_launcher` writes (shim, helper, seccomp filter, marker, launcher), and assert one start restores all of them. The frozen-state test should also carry the helpers. |
| **D. The platform moved under the evidence.** | F2, F17 | `launcher-vm` on the newest Ubuntu LTS (26.04) and on 24.04, both with AppArmor enforcing. Add a run test that a sandboxed app can create a nested user namespace with capabilities, as Chromium's sandbox needs; until now that rested on Obsidian in round 2. A Rocky 9 container tier (portal 1.12, GLib 2.68). A yearly reminder in `build.md`'s release steps to re-check what the distributions ship. |
| **E. Terms the requirements use but never define, and tests that stub them.** | F4 (CLI tool), "reviewed", the `standard` template, the review threat model (F8) | A glossary in §17 (CLI tool, reviewed, suggestion, user choice). A rule that backend tests may stub I/O but not decisions, checked by grepping the tests for `_is_cli =` and friends. |
| **F. Documents the spec delegates to.** | D1, D2 | A docs test. A file §17 names must not say "Status: planning", and none of the identifiers finding 0 retired (`$home/.flatpak-info`, `--talk=org.freedesktop.portal.Desktop`, `GTK_USE_PORTAL=1`, "Disable the app's own updater") may appear outside the review files. Better still, point 17.4 at the goldens. |
| **G. A key that outlives what it names.** R6-1 made ids unique among *installed* apps, but a kept home, a log file and a seen marker outlive the install. | F19, F14 | Extend `tests/test_sandbox_two_apps.py` from "side by side" to sequences: install A, uninstall keeping its home, install a same-name B (and the reverse, and a reinstall of A). Assert that no file, home, log or marker of A is visible to or written by B. |
| **H. Names used as a proxy for behaviour.** | F7 (desktop names for compositor capabilities), F4 (menu checkbox for app kind) | Decide from what is measured: the Wayland globals offered (the `wayland`/`kwin` harnesses' registry listing, in the product); the payload, for the app's kind. The harness runs the warning against each compositor image (sway, mutter, kwin 5/6) by globals, not by `XDG_CURRENT_DESKTOP`. |

---

## Decisions (owner, 2026-10-17)

The four owner decisions above were taken one at a time:

- **F2.** Where Ubuntu's own bwrap profile is active, AppKata starts Chromium/Electron apps with
  `--no-sandbox` *inside* its own sandbox. They keep everything AppKata's sandbox gives and lose
  Chromium's inner renderer sandbox, and App Detail says so.
  - The safety half ships with it: AppKata's profile is never loaded beside Ubuntu's, a setup that
    fails its own check is rolled back, and AppKata's profile is removed when Ubuntu's turns up
    after an upgrade.
  - A zypak-style spawner joins 17.18 as a future item. It would restore the inner sandbox, by
    having a host-side helper start each Chromium child in its own tighter bwrap.
  - Considered and declined: running those apps Off, and AppKata's own copy of bwrap (it misses
    Ubuntu's bwrap updates, and it reopens the door Ubuntu narrowed).
- **F3.** While an app runs sandboxed, AppKata updates it as if it didn't update itself (versioned
  installs, Update, Update all), and says why. Switched Off, it updates itself again. 17.12 and
  4.10 are rewritten to match, and the never-built "Disable the app's own updater" option goes.
- **F4.** An app's kind is detected from its download, and the install dialog shows it as a choice
  the user can flip:
  - an AppImage is a command-line tool when its `.desktop` says `Terminal=true`;
  - a tarball is one when it has no `.desktop` and its program links no display library.

  A command-line tool defaults to no app-menu entry. A Strict app started from a terminal says why
  it can't see its arguments.
- **F8.** A review may narrow freely. A review's `Sandbox: off` is never applied by itself: the app
  gets the reviewed baseline, and "Use theirs" is one click. A *secrets* class can't be granted by a
  review: browser and Flatpak or snap app data, cloud and developer credentials, password stores
  and keyrings. The user's own picker may grant it, with a warning. 17.3 states this threat model.

## Order of work

1. **F1:** one commit. The test fails on today's code with the relative-path corpus and the
   inside-the-sandbox check (class A).
2. **F2's safety half,** safe whatever is decided: stop the setup from loading a profile beside
   Ubuntu's, roll back a failed check, and remove AppKata's profile when Ubuntu's is present, which
   repairs an upgraded machine. Then add the 26.04 `launcher-vm` tier and the nested-namespace run
   test. Until then, say in 17.1 that the AppArmor path is shown on 24.04 only.
3. **F19 and F5**, each with its class harness (G, C).
4. **Decisions for the owner:**
   - F2: Electron apps on Ubuntu 25.04+ and its derivatives;
   - F3: 17.12 against 4.10;
   - F4: what a CLI tool is;
   - F8: what a review may do.

   Then the code for each.
5. **D1:** retire the planning-stage spec and field test, and point them at the goldens and the
   product's own path.
6. The LOW findings, one commit each, then the nits, then D2 and the PR body.

## Probes used in this review (not committed)

| Probe | Tier | What it showed |
|---|---|---|
| `test_probe_relative_grant.py` | 2 (Mint 22.1 image) | F1: `tmp` and the relative home path bound; the real key read and the real `.bashrc` changed |
| `test_probe_run.py` | 2 | F6: `.`, `notes.txt` and `src/main.c` resolve to the private home; F4: a Strict tool fails every argument silently |
| `test_probe_nested_link.py` | 2 | no finding: the inner grant can't be replaced while mounted |
| `test_probe_backend.py` | 1 | F4: `is_cli` with defaults is `False` → strict; the worker sees the dialog's answer; F7: desktop strings and the X11 text |
| `test_probe_helpers.py` | 1 | F5: `_heal_launchers()` → `[]` with the shim, helper and marker stale |
| one-off `protected_folder` and `choose` script | 1 | F8: the shareable secret folders; `Sandbox: off` from one review gives level off |
| `docker run rockylinux:9 dnf list`, `ubuntu:25.04`/`26.04` `apt-get download apparmor` | — | F17 versions; F2 the shipped `bwrap-userns-restrict` |
| `vm-probe.sh` (and a reboot variant) in Ubuntu 26.04 and 24.04 KVM guests, via the `appkata-qvm` image | 3 | F2: the support status, a nested user namespace inside Strict and Standard launchers, with and without AppKata's profile, and after a reboot |

---

## Fixes

| Commit | Item | What changed |
|---|---|---|
| 4b0b3f2 | F1 (HIGH) | A folder that isn't a full path is refused wherever a grant set is read |
| 8f8051c | F2 (HIGH) | On Ubuntu 25.04 and later: no AppKata profile beside Ubuntu's, Repair… after an upgrade, the setup checked as the user and rolled back on failure, `--no-sandbox` for Chromium/Electron where their sandbox can't run; the proxy's own pid namespace (found by the 26.04 tier); `launcher-vm26`; 17.10.2 |
| 573d34e | F19 | A kept private home records its app, and a same-name app takes the next id |
| 8e23638 | F5 | The startup pass checks and rewrites the marker, the shim, the file-argument helper and the seccomp filter |
| 084cb4b | F8 | A review's Off applies only on "Use theirs"; a review can't grant secrets, and the user's picker can with a warning; 17.3.5 |
| 7d639f6 | F3 | AppKata updates a self-updating app while it runs sandboxed; the fixed-name layout moves to versions; 4.10.5, 17.12 |
| 0b4712a | F4 | The app's kind comes from its download (`appkind`), shown in the install dialog; a tool's menu entry dropped by default; the Strict note on a terminal |
| 69dc368 | D1 | `local-proxy-test-plan.md` explains the launcher as built, with the goldens as its exact text; the field test runs AppKata's own install and launchers in a throwaway home |

**Class harnesses built** (see "Classes, and the harness for each"):

- **A**: relative paths in the adversarial corpus, plus a review judged from inside the sandbox (F1).
- **C**: every file the launcher calls, corrupted and restored by one start (F5).
- **D**: `launcher-vm26` and the inner-sandbox probe checked against an app inside (F2).
- **E**: the kind precedence tested with the real `_is_cli` (F4).
- **F**: the delegated documents test, and the field test run on every launcher tier (D1).
- **G**: the two-apps fixture's sequence cases (F19).

**Not built yet**: B (a requirements traceability test), and H (the session warning decided from
the compositor's globals, which is F7).

**Open, LOW:** F6, F7, F9, F10, F11, F12, F13, F14, F15, F16, F17, F18, the nits, and D2 (the PR
body's history paragraphs are left as history).

**Tiers after the fixes** (at 69dc368, plus this commit's harness fix):

| Tier | Platform | Result |
|---|---|---|
| 1 | local | 2,116 passed, 106 skipped |
| 2 | Mint 22.1 | 97 passed, 2 skipped |
| 2b | Mint 21.3 | 96 passed, 3 skipped |
| 2c | Ubuntu 25.04 | 97 passed, 2 skipped |
| 3 | Ubuntu 24.04 VM, AppKata's profile, inner sandbox true | 97 passed, 2 skipped |
| 3 | Ubuntu 26.04 VM, Ubuntu's own profile, inner sandbox false | 97 passed, 2 skipped |
| — | `consumers`, `filedialogs`, `filedialogs-qt68` | `EXPECTED: ok` |

The verdict harnesses were re-run because the proxy's process changed (its own pid namespace). The
real portal, Chromium's dialog road, Obsidian, and GTK and Qt dialogs behave as before.

The VM harness copied only `src`, `tests` and one helper into the guest, so the field-test test
first failed there for want of its script. `scripts/test-sandbox.sh` now ships both field-test files
too, so the field test also runs in the 24.04 and 26.04 guests.


**The rest of this review** was fixed in review 3 ([`app-sandboxing-3.md`](app-sandboxing-3.md)): F6,
F7, F15, F18, F17's claim, the nits and D2 in its fix pass; F9, F10, F11, F12, F13, F14, F16, F17's
tiers and the three UI nits in its second pass, after the owner's nine decisions (its Decisions and
"The second pass"). Nothing of this review is open.
