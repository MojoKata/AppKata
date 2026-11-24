# Relay progress: CR1's unit U09, the sandbox and the session bus

3 batches cover the unit's 9 findings, taken from `docs/remediation/CR1-schedule.json` at
`upstream/master` ae63101: batch 1 the High finding, the Media keys capability, and the capabilities' names; batch 2 the D-Bus proxy and the portals it opens; batch 3 what the dialog and the documents say of the portals.
One agent at a time; the coordinator checks each batch before the next starts, and pushes.

## Batch 1

Agent: Fable 5.2, high effort. Head after the batch: the commit that adds this section; the code is at `2daf340`.

### Files touched

`src/appkata_core/sandbox.py`, `src/appkata_core/trustfile.py`, `src/appkata/qml/SandboxDialog.qml`;
`tests/test_sandbox.py`, `tests/test_sandbox_run.py`, `tests/test_dialog_contract.py`, `tests/test_docs_facts.py`,
`tests/test_launcher_golden.py`; `tests/data/launchers/developer-every-capability.sh`, `messenger-camera.sh`,
`online-app-appimage-with-folders.sh`, `standard-writable-no-x11.sh` (each one line, the proxy's, by
`UPDATE_GOLDEN=1 pytest tests/test_launcher_golden.py`; `cli-tool.sh` and `strict-tarball.sh` are unchanged);
`docs/requirements/R10-trust-and-the-appkata-md-file.md`, `R17.3-templates.md`, `R17.5-filtered-session-bus.md`,
`R17.17-limits.md`; `docs/architecture/A1-app-sandboxing/A1.2-approach.md`, `A1.9-limits.md`, `A1.10-ui-text.md`;
`docs/requirements-trace.md`; this file.

### Counts

fixed 3 · no defect 0 · remedy changed 0 · set aside 0 · still left 0 · new 3

### The findings

**#378 (High), fixed: `d40a816`, with a correction of its own text in `2daf340`.**
The three direct names are opened as the portal's is (`sandbox._service_rules`): `--call` and `--broadcast` for the
service's own interface on its own object, `Introspectable` there, Properties `Get`/`GetAll` on the tray watcher.

- Tier 2: the stand-in shell and probe inside `test_standard_apps_reach_the_filtered_bus_when_there_is_one`
  (`tests/test_sandbox_run.py`), for notifications, inhibit and tray. Shown failing on `f2561f6` (a `git archive`
  export with the new test files, in the Mint 22.3 launcher container): `SECOND-OBJECT ANSWERED`,
  `UNIQUE-NAME ANSWERED`, `OTHER-INTERFACE … ANSWERED`, and the shell's own signal heard. Passes on the fix there
  (bwrap 0.9.0, xdg-dbus-proxy 0.1.5) and in the LMDE 7 container (bwrap 0.12.0, xdg-dbus-proxy 0.1.6).
- Tier 1, the class: `test_a_direct_name_is_opened_for_its_own_service_and_no_name_whole_but_the_listed`
  (`tests/test_sandbox.py`). On the export of `f2561f6` it fails, with the four tests that asserted the `--talk` word.
- The Properties calls, from real libraries behind a generated `messenger` launcher (a throwaway container from the
  dialogs image, with python3-pyqt5 and gir1.2-ayatanaappindicator3-0.1 added): Qt 6.4 and Qt 5.15 Introspect the
  watcher and `Get` `IsStatusNotifierHostRegistered`; each registers its icon as generated, and neither does with the
  Properties rule or the Introspectable rule taken out. libayatana-appindicator 0.5.93 registers in all three.
- Real notification clients behind a generated `standard` launcher against dunst 1.9.2 (the consumers image):
  `gdbus call … Notify` and dbus-python are shown; with the Introspectable rule taken out neither is.
- The consumers harness on the fixed tree: `EXPECTED: ok` (the GLib notification shown for `online-app`, not for
  `offline-editor`).
- IBus, as the record asks: in the inputmethod harness's image, with ibus-daemon alone, `org.freedesktop.portal.IBus`
  is owned by `/usr/libexec/ibus-portal` (IBus 1.5.29), a process and connection of its own that owns that one name
  and serves `/org/freedesktop/IBus` with `org.freedesktop.IBus.Portal.CreateInputContext` alone. With fcitx5 beside
  it, as the harness starts both, fcitx5 5.1.7 holds both portal names, each on a connection of its own with the
  input-method objects alone. No wider reach: no new finding there.
- The whole launcher tier on the fix (Mint 22.3 container, its skip list): 133 passed, 5 skipped, run while the
  check was still three parametrized cases of its own; after it moved into the existing test (doubt 1) the
  capability tests were run again, and the whole tier with #631's fix on top, below.

**#631 (Med), fixed: `fdd6cd7`.** The owner's decision of 2026-11-24 as written on the issue.

- Tier 2: `test_a_media_key_daemon_can_drive_an_app_with_the_mpris_capability_and_only_that_app`, with a second
  player on the bus and a second object on its connection. Shown failing on `d40a816` (export, launcher container):
  the app whose set names its MPRIS name still `SEES … .other`, `OTHER-PLAYER ANSWERED`, `OTHER-OBJECT ANSWERED`,
  `OTHER-NAME ANSWERED 1`. On the fix it is refused all three and is still driven on its own name; the app nobody
  named reaches all three (the limit R17.17 and the hint now state). Mint 22.3 and LMDE 7 containers.
- Tier 1 (`tests/test_sandbox.py`): `test_media_keys_own_the_apps_own_mpris_name_and_every_name_only_when_nobody_named_it`,
  `test_a_review_names_the_apps_mpris_name_and_reviews_merge_to_the_narrower_one`,
  `test_a_named_mpris_name_shows_as_the_narrowing_it_is`; and the dialog's seam,
  `test_a_named_media_player_keeps_its_name_through_the_sandbox_dialog` (`tests/test_dialog_contract.py`). All four
  fail on the export of `d40a816`.
- The tray part (documents only): R17.17 and A1.9 say the shared item names are a road between two tray apps. Run
  once by hand in the launcher container: a `messenger` app called a second object on the connection holding
  `org.kde.StatusNotifierItem-2-1`; an `online-app` could not.
- The whole launcher tier on the fix, #378's included: 130 passed, 5 skipped (three fewer than above only because
  #378's three parametrized cases became part of one existing test).

**#195 (Low), fixed: `d365a59`.** A1.2.3.14 gains the review word and the names elsewhere; R17.5.1 points to it.

- `test_every_fact_the_documents_state_is_what_the_code_says_but_the_listed` (`tests/test_docs_facts.py`) reads the
  new columns against the code, the dialog and R17.3's table. On the export of `fdd6cd7` with the new test file it
  fails on all seven new facts.

Tier 1 in its container (the image and command of `scripts/test-tier1.sh`, `APPKATA_SKIPS=tier1`), run on the tree
of each commit before it was made: 2693 passed and 121 skipped at `d40a816`, 2697 and 121 at `fdd6cd7`, `d365a59`
and `2daf340`. The four document checks of the brief pass at each.

### Listed items

**new**

1. `src/appkata_core/sandbox.py`, `CAP_PROXY_ARGS["secrets"]` (`--talk=org.freedesktop.secrets`): the Saved passwords
   capability opens the keyring's whole connection, as #378 found of the three names it fixed. In the launcher
   container gnome-keyring 46.1's connection owns `org.gnome.keyring` too and serves `/org/gnome/keyring/daemon`
   (`org.gnome.keyring.Daemon`: GetEnvironment, GetControlDirectory), `org.freedesktop.impl.portal.Secret`
   (RetrieveSecret) on `/org/freedesktop/portal/desktop`, and on `/org/freedesktop/secrets`
   `org.gnome.keyring.InternalUnsupportedGuiltRiddenInterface` (ChangeWithMasterPassword, ChangeWithPrompt,
   CreateWithMasterPassword, UnlockWithMasterPassword). Low: only the user gives the capability and it is every
   unlocked password already. Narrowing it needs the secret service's object tree (collections, items, sessions,
   prompts) and its Properties calls found from real clients. `2daf340` writes this down and narrows nothing.
2. `src/appkata_core/sandbox.py:760` (`_CAP_CHIP`) against `src/appkata/qml/SandboxDialog.qml:266-272`: the summary
   chip says "Secrets" and "Keep screen awake" where the dialog's switch says "Saved passwords" and "Keep the screen
   awake". A term, Low; #195's table now records both.
3. The `org.freedesktop.ScreenSaver` interface is opened whole on its two objects, as #378's remedy says. Where a
   desktop's implementation has more than Inhibit and UnInhibit on that interface (Lock, SetActive), an app with
   Keep the screen awake can call them. Not run on any desktop: a check, then perhaps Low.

**needs your eye**

- `d40a816`: R17.5.1 gains two sentences (the direct names are opened for their service alone, and why); A1.2.3.14's
  three rows and a paragraph. Nothing the user sees. An app loses every call on those names' owners but the
  service's own; Properties calls pass on the tray watcher only.
- `fdd6cd7`: a new review line, `Sandbox MPRIS name` (R10.3.1), and what is no name for it; the merge rule for it in
  R17.3.2; R17.5.1 and R17.17; A1.9, A1.10. What the user sees: the Media keys hint, one of
  "…(MPRIS), under its own player name alone: <name>." and "…(MPRIS). It has no player name of its own here (a
  review gives one), so it may take any, and can reach every other media player that is running."; and in a set's
  description, the Audit and the review badge the phrases "media-player names other than <name>" (as a removal),
  "every media-player name" (as an addition) and "the media-player name <name>".
- `d365a59`: A1.2.3.14's two new columns and its opening paragraph; R17.5.1's last sentence.
- `2daf340`: A1.2.3.14's paragraph says the keyring's name is wider than the secret service and not narrowed yet.

**needs a run**

1. The finding's own run on the Mint 22.3 desktop VM. The probe script below is at `/tmp/cr1-u09-scratch/vm-378-eval.sh`
   (outside the repository); from a checkout at this branch's head that has the VM's base and the release's AppImage:
   `VMTEST_SCRIPT=/tmp/cr1-u09-scratch/vm-378-eval.sh scripts/test-desktop-vm.sh run mint22.3`.
   Wanted: both names owned by one connection; Eval answered outside the sandbox; from inside, `by name` and
   `by owner` `AccessDenied`; `RESULT: refused`; the Notify call answered with an id. Run dry in the launcher
   container against a stand-in shell that owns both names and runs what Eval is sent: on the fix exactly that; on
   an export of `f2561f6`, `(true, '42')` twice and `RESULT: ESCAPED`.
2. `scripts/test-desktop-vm.sh run mint22.3` and `run lmde7`: the launcher tests in the real Cinnamon session.
3. `scripts/test-sandbox.sh launcher-vm` and `launcher-vm26`: the launcher tests in the Ubuntu VMs.
4. The project's own commands, which I did not run as such from this worktree (it has no `build/`, and each
   registers its checkout with the coworker protocol): `scripts/test-tier1.sh`, `scripts/test-sandbox.sh launcher`,
   `launcher-lmde7`, `consumers`, `inputmethod`. I ran their container commands by hand, on the same images, with
   the release Python and PySide6 from the main checkout's `build/` mounted read-only.

```sh
#!/bin/bash
# CR1.5-3's own run, again, for scripts/test-desktop-vm.sh (VMTEST_SCRIPT): in the real Cinnamon
# session, a `standard` launcher written by AppKata's own code, and from inside it org.Cinnamon.Eval
# sent to org.freedesktop.Notifications. Before the fix the command ran in the shell, as the user.
exec > /dev/ttyS0 2>&1
echo "=====VMTEST BEGIN====="
. /etc/os-release
echo "$PRETTY_NAME, kernel $(uname -r), session ${XDG_SESSION_TYPE:-?} on ${XDG_CURRENT_DESKTOP:-?}, bus ${DBUS_SESSION_BUS_ADDRESS:-?}"
mkdir -p ~/vmtest && cd ~/vmtest || exit 1
curl -sSf http://10.0.2.2:8000/src.tgz | tar -xz
curl -sSf http://10.0.2.2:8000/py.tgz | tar -xz
PY=$PWD/python/bin/python3
bus() { gdbus call --session --dest org.freedesktop.DBus --object-path /org/freedesktop/DBus --method "org.freedesktop.DBus.$1" "$2" 2>&1; }
echo "-- who owns what in this session"
echo "  org.freedesktop.Notifications: $(bus GetNameOwner org.freedesktop.Notifications)"
echo "  org.Cinnamon:                  $(bus GetNameOwner org.Cinnamon)"
owner=$(bus GetNameOwner org.freedesktop.Notifications | sed "s/[(),']//g")
echo "-- outside any sandbox the shell still answers Eval (so a refusal below is the filter's)"
echo "  $(gdbus call --session --dest org.Cinnamon --object-path /org/Cinnamon --method org.Cinnamon.Eval '6*7' 2>&1)"
echo "-- a standard launcher, as AppKata writes it"
mkdir -p apps/probe/1.0/bin
printf '#!/bin/sh\neval "$1"\n' > apps/probe/1.0/bin/app && chmod +x apps/probe/1.0/bin/app
run=$(PYTHONPATH=src $PY -c '
import os, sys
from appkata_core import sandbox as sb
here = os.getcwd()
gs = sb.resolve_template("standard")
print("  capabilities:", sorted(gs["caps"]), file=sys.stderr)
print("  its rules on the name:", [a for a in sb.proxy_args(gs, "probe") if "org.freedesktop.Notifications" in a], file=sys.stderr)
print(sb.write_launcher("probe", "Probe", here + "/apps", here + "/apps/probe/1.0", "bin/app", gs))')
echo "  launcher: $run"
mark=$HOME/U09_ESCAPED_$$
eval_call() { echo "gdbus call --session --dest $1 --object-path /org/Cinnamon --method org.Cinnamon.Eval 'imports.gi.GLib.spawn_command_line_async(\"touch $mark\")' 2>&1"; }
echo "-- from inside it: Eval by the service's name, then by its owner's unique name"
echo "  by name:   $("$run" "$(eval_call org.freedesktop.Notifications)")"
echo "  by owner:  $("$run" "$(eval_call "$owner")")"
echo "  org.Cinnamon itself: $("$run" "$(eval_call org.Cinnamon)")"
sleep 2
if [ -e "$mark" ]; then echo "  RESULT: ESCAPED, $mark exists in the real home"; else echo "  RESULT: refused, no $mark in the real home"; fi
echo "-- and its own service still answers: a notification from inside"
echo "  $("$run" 'gdbus call --session --dest org.freedesktop.Notifications --object-path /org/freedesktop/Notifications --method org.freedesktop.Notifications.Notify appkata 0 "" "from the sandbox" "CR1.5-3" "[]" "{}" 5000 2>&1')"
sleep 2
echo "VMSHOT 01-notification"
sleep 3
echo "=====VMTEST END====="
sleep 5
sudo poweroff
```

**guard** (exit 0 after each commit)

- `tests/test_dialog_contract.py`: a shared file, add it to U09's files.
- `tests/test_docs_facts.py`: a shared file, add it to U09's files.
- `tests/test_launcher_golden.py`: no other unmerged unit claims it, add it to U09's files.

### Doubts for the coordinator

1. **`tests/skips/tier1.txt` belongs to U44 and is not a shared file.** A new test in `tests/test_sandbox_run.py`
   skips in tier 1 and so needs its line there, or tier 1 fails. I did not change the file. #378's tier 2 check
   therefore runs inside `test_standard_apps_reach_the_filtered_bus_when_there_is_one`, which the list already
   names, as a loop over the three capabilities; #631's is in the existing media-key test, where it fits anyway.
   With the list available the first would read better as a parametrized test of its own
   (`_a_direct_name_reaches_its_service_and_nothing_else_its_owner_serves` is written to be called that way), and
   one line covers every case of it. Batches 2 and 3 will meet the same wall.
2. **U16's files don't know the new field.** `tests/test_sandbox_properties.py` (`OVERRIDES`, "every kind of override
   a review line or the dialog can apply") and `tests/test_sandbox_surfaces.py` have no named player. My own tests
   hold the same invariants for it (storage, the review round trip, the merge over every pair), but the corpus is
   the right home.
3. **U36's files.** The real tray libraries and notification clients were scratch runs; `scripts/sandbox/consumers.py`
   could carry one (its image has PyQt6 with Qt 6.4), and `scripts/sandbox/fieldtest.py` the Eval check of the
   probe script, so the desktop VMs run it every time.
4. **Beside the remedy's words in #378**: Introspectable on each service's object (shown necessary above), and
   GetAll beside Get on the watcher (what a GDBus proxy loads; no library I ran needed it).
5. **Not run**: Chromium's or Electron's tray icon (the rule covers the `Get` its source makes, from memory only);
   what GNOME's and KDE's shells own, as the finding says of itself; any real desktop.
6. **Choices in #631 that the decision leaves open**, each made the narrow way and easy to turn:
   the line is named `Sandbox MPRIS name` and takes the full bus name; two reviews naming different players merge
   to no Media keys at all (written into R17.3.2); picking a template in the dialog, or Reset, gives the bare
   template without the review's name, as it drops a review's folders, with the hint and the badge saying so (a
   Save after other changes keeps the name); the summary chip is unchanged.
7. **The goldens and U03.** Only the proxy line of four goldens changed, and `tests/test_launcher_golden.py` now
   gives the every-capability case a named player, so the wildcard is in no golden (tier 1 holds it). After a
   merge with U03, `UPDATE_GOLDEN=1 pytest tests/test_launcher_golden.py` settles any conflict in those files.
8. **The guard reads commits**, so before a commit it cannot name a pending file: I judged each from the schedule
   (which is how the tier 1 list was left alone) and ran the guard after each commit. It failed once on GitHub's
   503 and passed on the retry.
9. **#378 has two commits**: `2daf340` corrects what `d40a816`'s test comment and A1.2.3.14 said of the keyring,
   found after it was committed; no amend.
10. No refusal and no model change on my side.

### The coordinator, after batch 1 (2026-11-24)

Checked: every answer of the agent on its named model; the guard; the touched fast tests and the
document tests, whole; the batch pushed.

- **New findings filed**, and added to this unit and to batch 3: #691 (new 1, Saved passwords
    opens the keyring's whole connection), #692 (new 2, the chip's two names) and #693 (new 3,
    the ScreenSaver interface: a check).
- **Guard, and doubt 1:** `tests/test_dialog_contract.py`, `tests/test_docs_facts.py`,
    `tests/test_launcher_golden.py` and `tests/skips/tier1.txt` are in U09's files now, so a new
    test in `tests/test_sandbox_run.py` gets its own line in the skip list from here on.
- **Doubt 6** (the line's name `Sandbox MPRIS name` and its full-bus-name form; two reviews
    naming different players merge to no Media keys; a template pick or Reset drops the review's
    name) goes to the owner under Needs your eye. Nothing for a later batch to change.
- **Doubts 2 and 3** are for other units (U16's property tests don't know `mpris_name`; U36's
    harnesses are where the real tray and notification runs belong): the coordinator carries them.
- **Doubts 4, 5, 7 and 8** are noted. After U03 merges, the goldens are settled by
    `UPDATE_GOLDEN=1 pytest tests/test_launcher_golden.py`, by the coordinator.
- **Needs a run** (the Cinnamon run of #378 with the script in batch 1's section, and the usual
    launcher and desktop VMs): the coordinator's, when the last batch is in.

