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

## Batch 2

Agent: Fable 5.2, high effort. Head after the batch: the commit that adds this section; the code is at `715070b`.

### Files touched

`src/appkata_core/sandbox.py`; `tests/test_sandbox.py`, `tests/test_sandbox_run.py`, `tests/skips/tier1.txt`;
`tests/data/launchers/cli-tool.sh`, `developer-every-capability.sh`, `messenger-camera.sh`,
`online-app-appimage-with-folders.sh`, `standard-writable-no-x11.sh` (the proxy's block alone, by
`UPDATE_GOLDEN=1 pytest tests/test_launcher_golden.py`, in each of the two commits; `strict-tarball.sh` is unchanged);
`docs/requirements/R17-app-sandboxing/R17.5-filtered-session-bus.md`, `R17.17-limits.md`;
`docs/architecture/A1-app-sandboxing/A1.2-approach.md`, `A1.9-limits.md`; `docs/requirements-trace.md`; this file.

### Counts

fixed 2 · no defect 0 · remedy changed 0 · set aside 0 · still left 1 · new 0

### The findings

The containers, by hand as the brief says (the images and commands of `scripts/test-sandbox.sh launcher` and
`launcher-lmde7` and of `scripts/test-tier1.sh`, a 3 GB cap): Mint 22.3 has bwrap 0.9.0, xdg-desktop-portal 1.20.0,
GLib 2.80.0, dbus 1.14.10, xdg-dbus-proxy 0.1.5; LMDE 7 has bwrap 0.12.0, portal 1.20.3, GLib 2.84.4, dbus 1.16.2,
xdg-dbus-proxy 0.1.6.

**#393 (CR1.5-18), fixed: `a71b180`.** The launcher reads the session's address: unset or empty it is
`unix:path=$XDG_RUNTIME_DIR/bus`; a `unix:path=` socket is bound into the proxy's bwrap at its own path (the file
alone, read-only); `unix:abstract=` needs nothing bound; any other address gets no proxy, a line on stderr, and the
app runs with no session bus. Reproduced first in the Mint container: `dbus-run-session` prints
`unix:path=/tmp/dbus-…,guid=…`, and the proxy in the old bwrap answers every connection with "Failed to connect to
bus: Could not connect: No such file or directory".

- Tier 1 (`tests/test_sandbox.py`), the class: the generated launcher run against a bwrap that records its words,
  for each kind of address (`test_the_proxy_is_shown_the_session_bus_wherever_its_socket_is`, 6 cases) and for those
  it can't read (`test_a_bus_address_the_launcher_cannot_read_is_said_and_the_app_runs_with_no_bus`, 9 cases). On an
  export of `f075bcd` with the new test files: 15 failed (14 of those cases and the changed
  `test_proxy_startup_is_set_u_safe_and_bails_if_proxy_dies`); the abstract address passes there, as it should.
- Tier 2 (`tests/test_sandbox_run.py`): `test_standard_apps_reach_the_session_bus_wherever_it_listens` (a real
  `dbus-run-session`, and a bus in the runtime folder that no variable names: the app owns its name, the real
  xdg-desktop-portal answers, FileChooser is refused) and
  `test_a_session_bus_the_filter_cannot_be_shown_is_said_and_the_app_runs_without_one` (3 cases). On the export, in
  the Mint container: 5 failed ("Error connecting: Error receiving data: Connection reset by peer" for each call;
  a bus socket inside and nothing on stderr for the three addresses).
- On the fix: tier 1 2712 passed, 126 skipped; the launcher tier 135 passed, 5 skipped in the Mint 22.3 container
  and the same in the LMDE 7 one.

**#399 (CR1.5-24), fixed: `715070b`.** The owner's decision. The proxy's bwrap binds `/usr` and `/etc` read-only,
`$XDG_RUNTIME_DIR/appkata` read-write and the bus socket read-only; it has its own pid, IPC, UTS and cgroup
namespaces and, where the bus is a socket file, its own network (`--unshare-net`); it takes the terminal-injection
seccomp filter (`--seccomp 3` on a descriptor opened for that command alone), or `--new-session` where the
machine has no filter. R17.17 and A1.9 say what is left.

- The remedy's condition (the proxy reaches nothing else in the runtime folder): every bus test of the launcher
  tier passes with the narrowed sandbox, on xdg-dbus-proxy 0.1.5 and 0.1.6.
- Tier 1: `test_the_proxys_own_sandbox_holds_its_socket_folder_and_the_session_bus_alone` (every word of the proxy's
  bwrap, 5 addresses) and `test_the_proxy_takes_the_terminal_filter_or_a_session_of_its_own`. On an export of
  `a71b180` with the new test files: 6 failed.
- Tier 2: `test_the_proxy_runs_in_a_sandbox_that_holds_its_socket_folder_and_the_bus_alone`, on a socket file and
  on an abstract bus: a bwrap wrapper runs the launcher's own words with a look inside before the proxy starts
  (what `find /` sees, the namespaces, `Seccomp:` in `/proc/self/status`), and the app still owns its name
  through it. On the export, Mint container: both cases failed (the keyring, gnupg, doc, pipewire and wayland
  entries of the runtime folder in sight).
- The dbus 1.12 case: no image here has dbus 1.12, so the abstract case is a dbus-daemon told
  `--address=unix:abstract=…` (1.14 and 1.16 still listen on one). The proxy stays in the host's network
  namespace there and has its own everywhere else.
- **A fault of the tests fixed in the same commit** (in `tests/test_sandbox_run.py`):
  `test_a_standard_launch_leaves_no_proxy_running` looked for the app's id in the proxy's command line, and the
  socket is named by a hash of the id since R3-12, so it found no proxy while the app ran either and could not
  fail. It now sees the proxy first, then wants it gone. It passes before and after.
- **First try, undone before the commit**: `--unshare-all` with `--share-net` for the abstract case failed 49 cases
  of `tests/test_sandbox_properties.py` (U16's), which read `--share-net` in a launcher's text as the network
  grant, as `scripts/sandbox/exposure.py` and others do. The namespaces are named one by one, and a tier 1 test
  holds that the proxy's bwrap never says `--share…`.
- On the fix: tier 1 2718 passed, 128 skipped (on the committed tree); the launcher tier 137 passed, 5 skipped in
  each container (on a snapshot that differs only in the wording of A1.9's bullet and R17.17's second sentence).
- The harnesses with real programs, on an export of `715070b` (their own images and commands): `inputmethod`,
  `wayland`, `filedialogs` and `consumers` each end `EXPECTED: ok`.

**#403 (CR1.5-28), still left: no commit.** The fix is written and proven, and one word of it is in a file U46
claims.

- **What the decided remedy does when taken alone.** With ProxyResolver refused, a GLib program without the network
  grant can no longer make any connection through GIO, one to a server of its own on the loopback included: GLib
  asks that portal for a proxy before every connection (`gproxyresolverportal.c`) and fails the connection when
  the answer is a refusal. Run with GLib 2.80 and 2.84, a `Gio.SocketClient` to `127.0.0.1` inside an
  `offline-editor`: "LOOPBACK failed: GDBus.Error:org.freedesktop.DBus.Error.AccessDenied", where the same
  program connected before. The record's proof ("still starts, GLib's network monitor falls back without an
  error the user sees") holds for the monitor (it says "no network" and prints nothing) and missed this.
- **The fix as written**: the two interfaces and `NetworkMonitor.changed` are in the filter only with the network
  grant (`portal_rules(network)`), and for a Standard app without it the launcher adds
  `--setenv GIO_USE_PROXY_RESOLVER dummy`: GLib's built-in resolver, which answers `direct://` and asks nobody,
  and `direct://` is all GLib gives a sandbox without the network whatever the portal says. R17.5 says both;
  A1.2.3.12 and A2's inventory follow (`env GIO_USE_PROXY_RESOLVER`, when `bus and not network`).
- **Why it is not committed**: A2's inventory tests (`tests/test_sandbox_exposure.py`, tier 1 too) expect a
  variable only when the host sets it at launch or `LAUNCHER_SET` in `scripts/sandbox/exposure.py` names it, and
  that file is U46's alone. Without the name they fail ("seen, not listed for this run: env
  GIO_USE_PROXY_RESOLVER"). `docs/architecture/A2-sandbox-exposure.md` is a shared file and would be added.
- **Proven whole**, as a patch outside the repository: `/tmp/cr1-u09-b2/403.patch` (sha256 `0bf3a19fe16e013b…`,
  11 files, applies to `715070b`). With it: tier 1 2732 passed, 130 skipped; the launcher tier 139 passed, 5
  skipped in each container. Its tests: `test_what_the_host_says_of_its_network_reaches_an_app_only_with_the_network_grant`
  (tier 1, every Standard template with the grant and without: the proxy variables, the marker, the two portals
  and the GLib setting follow the one grant, and every portal interface the filter opens has a switch),
  the extended `test_the_notification_and_inhibit_portals_come_with_their_capabilities` and R17.5's two lists in
  `tests/test_docs_facts.py`; tier 2, the extended `test_the_portals_answer_a_sandboxed_app_as_a_host_caller`
  (ProxyResolver.Lookup and NetworkMonitor refused to an `offline-editor`, answered to an `online-app`) and
  `test_a_glib_app_asks_the_portal_about_the_network_only_with_the_grant_and_works_either_way`. On `715070b` with
  the new test files: 19 failed in tier 1's two files, and in the Mint container the portal test and the GLib
  test without the grant.
- **What it needs**: `scripts/sandbox/exposure.py` in U09's files (or the one word there by U46 first), then
  `git apply /tmp/cr1-u09-b2/403.patch` and a commit. If the patch is gone, the code is three edits of
  `sandbox.py`: `NETWORK_PORTAL_INTERFACES = ("NetworkMonitor", "ProxyResolver")` taken out of `PORTAL_INTERFACES`,
  `portal_rules(network)` called with `gs["network"]` from `proxy_args`, and in `build_launcher`, after the
  `GDK_DEBUG` word, `if standard and not net: parts.append('  --setenv GIO_USE_PROXY_RESOLVER dummy \\')`.

### Listed items

**new**: none filed. (The proxy-leak test that could not fail is fixed in `715070b`, above.)

**needs your eye**

- `a71b180`: R17.5 gains three sentences: which bus is filtered (the address, or the runtime folder's when none is
  set), that the proxy is shown it wherever it listens, and that an address that names neither a socket file nor
  an abstract socket is not filtered. What the user sees, on stderr or in the app's log, in a session with such
  an address: "AppKata: the session bus here (<address>) is not one the bus filter can reach, so <App> runs
  without a session bus and gets no desktop services." And in a `dbus-run-session` session a Standard app now
  has its bus. A1.2.3.12 gains a bullet.
- `715070b`: R17.17 gains two sentences (what a fault in the bus filter would still give the app, and what its
  sandbox holds); A1.9 a bullet; A1.2.3.12's first bullet is rewritten. R17.17 opens "stated plainly in the UI and
  docs": this limit is in the documents only, no dialog says it.
- #403, when it lands: R17.5 moves NetworkMonitor and ProxyResolver to the network grant, and says the launcher
  sets `GIO_USE_PROXY_RESOLVER=dummy` for a Standard app without it. That variable is a rule no decision named:
  it is what keeps the decided remedy from breaking GLib programs.

**needs a run**

1. `scripts/test-sandbox.sh launcher-vm` and `launcher-vm26`: the Ubuntu VMs. The proxy's bwrap has new words
   (`--unshare-ipc --unshare-uts --unshare-cgroup-try --unshare-net --seccomp 3`), all of which the app's own
   bwrap already uses there through `--unshare-all`, and the look-inside test runs `find`, `readlink` and `sed`
   under Ubuntu 26.04's `unpriv_bwrap` profile: neither is shown outside the containers.
2. `scripts/test-desktop-vm.sh run mint22.3` and `run lmde7`: the launcher tests in the real Cinnamon session,
   whose bus is systemd's at `$XDG_RUNTIME_DIR/bus`.
3. The project's own commands, which I did not run as such (the worktree has no `build/`): `scripts/test-tier1.sh`,
   `scripts/test-sandbox.sh launcher`, `launcher-lmde7`, `consumers`, `inputmethod`, `wayland`, `filedialogs`. I ran
   their container commands by hand, with the main checkout's `build/` Python, PySide6 and fetched AppImages
   mounted read-only.

**guard**: exit 0 after each commit, and no file to add. #403's patch would add
`docs/architecture/A2-sandbox-exposure.md` (shared) and stops on `scripts/sandbox/exposure.py` (U46).

### Doubts for the coordinator

1. **#403 is one word short of a commit**, and it carries something for the owner: the decision, taken as
   written, breaks GLib's connections in apps without the network. I would keep the decision and add the GLib
   setting (the patch). The other roads: gate NetworkMonitor alone and leave ProxyResolver to R17.4's wording
   (the finding's alternative), or take the decision as written and list the breakage as a limit. I made no
   partial commit, so R17.5 still lists the two portals for every app.
2. **What #393's rule leaves out, by choice.** A list of addresses, a path with an escaped byte (`%20`) and every
   transport but `unix:path=` and `unix:abstract=` get no proxy and the line on stderr; the launcher does not
   decode escapes. dbus escapes every byte outside `[-0-9A-Za-z_/.\*]`, so a runtime folder or `/tmp` socket
   never has one, and a home with a space or an accent under it would. `tcp:` did not work before either (run:
   "The connection is closed"; its cookie authentication has no home in the proxy's root).
3. **A bus socket that isn't there stays silent**, as before: the proxy starts, the app runs, its calls fail
   (`test_standard_apps_run_without_a_session_bus`). A command-line tool under cron or ssh would otherwise print
   a line on every run.
4. **The app's bind of the proxy socket moved** from the baked bwrap words to `"$@"`, since it is now decided at
   run time. It still lands after every baked bind and before a command-line tool's folder. The teardown is one
   line now (`if [ -n "$proxy" ]; then …; fi`).
5. **The seccomp filter is the terminal-injection one**, the first of the remedy's two ("reuse … or a tighter
   one"). R17.17's "the only seccomp filter is the terminal-injection one" stays true. A filter of the proxy's
   own syscalls would be tighter and would have to hold across four systems' GLib builds.
6. **The socket folder is shared**: `$XDG_RUNTIME_DIR/appkata` holds every running app's proxy socket, so a
   faulty proxy could reach the other apps' filtered buses. R17.17 says so. A folder per launch would close it,
   and changes the socket's path, which other units' tests and harnesses read.
7. **`/etc` stays whole** in the proxy's root, as in the app's own: the decision did not name it.
8. **`A1.2-approach.md` is at 496 of its 500 lines** (`tests/test_doccheck.py`), 499 with #403's patch. Batch 3's
   text there has no room without a split of the file.
9. **Other units' files I read and did not change**: `scripts/sandbox/consumers.py` and `filedialogs.py` replace
   the literal `xdg-dbus-proxy "$upstream" "$sock" ` in a launcher, which I kept; `scripts/sandbox/lib.sh`,
   `validate-launcher.sh` and `validate2.sh` start a proxy by hand in the old shape; A2's inventory and
   `tests/test_sandbox_exposure.py` look at the app's bwrap alone, so the proxy's sandbox is held only by this
   batch's tests.
10. **For batch 3 (#202, #404)**: A1.9's list "(open-URI, settings, print, email, the monitors; …)" and the other
    lists of the always-open portals depend on what becomes of #403.
11. **The coordinator's rule of 2:24 PM** (every command starts with `cd` into the worktree, and the checkout
    and branch are checked before a commit) is followed from there on. `a71b180` was made before it, from this
    worktree: `git log` shows it on `cr1-u09-session-bus`.
12. Scratch (outside the repository): `/tmp/cr1-u09-b2/`, the container scripts, the logs of every run named
    here, and `403.patch`. No container or process of mine is left running.
13. No refusal and no model change on my side.

### The coordinator, after batch 2 (2026-11-24)

Checked: every answer of the agent on its named model; the guard; `tests/test_sandbox.py`,
`tests/test_launcher_golden.py` and the document tests, whole; the batch pushed.

- **#403 (doubt 1): take the complete fix.** The owner decided that ProxyResolver and NetworkMonitor
    open only with the network grant. Having the launcher also set `GIO_USE_PROXY_RESOLVER=dummy`
    for a Standard app without the network is what makes that decision work for GLib programs, not
    a second decision: it is a way to the decided behaviour. `scripts/sandbox/exposure.py` and
    `docs/architecture/A2-sandbox-exposure.md` are in U09's files now, so the guard lets them in.
    **Batch 3 starts with it:** apply batch 2's patch, `/tmp/cr1-u09-b2/403.patch` (it applies to
    this branch's head: `git apply --check` passes), read it whole, run its tests as the brief says
    (show the new ones failing on the code before), and commit it as #403's fix. List the new
    variable and R17.5's sentence under needs your eye.
- **Doubt 5** (`A1.2-approach.md` is at 496 of its 500 lines): #202 is about the portals being
    listed four times; joining those lists is where the room comes from. Don't raise the limit.
- **Doubts 2, 3, 4 and 6** stand as built; 2 and 6 go to the owner under Needs your eye.
- **#693 and #691** move to a fourth batch, since each needs real clients run through the filter.
- **Needs a run** (the Ubuntu launcher VMs, the desktop VMs, #378's Cinnamon script): the
    coordinator's, when the last batch is in.

## Batch 3

Agents: Fable 5.2, high effort, made the first four commits (`0583283`, `2e05a9b`, `0d659f9`, `5b22d69`, 3:00 to
3:14 PM) and stopped at a usage limit in the middle of #692; Opus 5.5, high effort, took the batch over at 4:06 PM,
finished #692 from the uncommitted change it found (`99b7bd2`) and wrote this section. Of the four commits it did
not make, the outcome, the test and how it was shown failing are taken from their commit messages and `git show`,
the stopped agent's logs in `/tmp/cr1-u09-b3/`, and a run of each commit's test files on its parent, below. Head
after the batch: the commit that adds this section; the code is at `99b7bd2`.

### Files touched

`src/appkata_core/sandbox.py`, `src/appkata/qml/SandboxDialog.qml`, `scripts/sandbox/exposure.py`;
`tests/test_sandbox.py`, `tests/test_sandbox_run.py`, `tests/test_dialog_contract.py`, `tests/test_docs_facts.py`,
`tests/skips/tier1.txt`; `tests/data/launchers/cli-tool.sh` (the proxy's block, by
`UPDATE_GOLDEN=1 pytest tests/test_launcher_golden.py`; the other goldens are unchanged);
`docs/requirements/R17-app-sandboxing/R17.5-filtered-session-bus.md`, `R17.17-limits.md`;
`docs/architecture/A1-app-sandboxing/A1.2-approach.md` (497 of its 500 lines), `A1.9-limits.md`, `A1.10-ui-text.md`;
`docs/architecture/A2-sandbox-exposure.md`; `docs/requirements-trace.md`; this file.

### Counts

fixed 5 · no defect 0 · remedy changed 0 · set aside 0 · still left 0 · new 0

### The findings

**#403 (CR1.5-28), fixed: `0583283`** (Fable 5.2). Batch 2's patch as the coordinator said: applied to a scratch
export of `0583283^`, `/tmp/cr1-u09-b2/403.patch` gives every one of the commit's 11 files byte for byte, so the
commit is the patch unchanged. NetworkMonitor, ProxyResolver and `NetworkMonitor.changed` are in the filter only
with the network grant; a Standard app without it gets `--setenv GIO_USE_PROXY_RESOLVER dummy`, named in
`LAUNCHER_SET` and in A2's inventory.

- Tests, tier 1: `test_what_the_host_says_of_its_network_reaches_an_app_only_with_the_network_grant` (new), the
  extended `test_the_notification_and_inhibit_portals_come_with_their_capabilities`, R17.5's two lists in
  `tests/test_docs_facts.py`. Tier 2: the extended `test_the_portals_answer_a_sandboxed_app_as_a_host_caller` and
  `test_a_glib_app_asks_the_portal_about_the_network_only_with_the_grant_and_works_either_way` (new, two lines in
  `tests/skips/tier1.txt`).
- Shown failing on `0583283^` with the new test files (the stopped agent's logs): 19 failed in `tests/test_sandbox.py`
  and `tests/test_docs_facts.py` (`pre403-fast.log`); in the Mint 22.3 launcher container the portal test and the GLib
  test's `[False]` case (`pre403-launcher.log`: 2 failed, 1 passed).
- On the fix: tier 1 2732 passed, 130 skipped; the launcher tier 139 passed, 5 skipped in Mint 22.3 and in LMDE 7.

**#404 (CR1.5-29), fixed: `2e05a9b`** (Fable 5.2). The owner's decision: R17.17 and the Network hint say that an
app without the network can still have the desktop open a link that carries what it knows. A Strict app (no bus)
keeps the one-sentence hint. A1.9 gains a bullet, A1.10 the hint's row, the trace R17.17's row. No behaviour changes.

- Tests: tier 1 `test_the_network_hint_says_what_an_app_without_the_network_can_still_send_out`
  (`tests/test_dialog_contract.py`) and two facts in `tests/test_docs_facts.py` (R17.17's sentence, A1.9's bullet);
  tier 2 `test_links_and_files_an_app_opens_go_to_the_host_through_the_portal` now also runs an offline-editor
  (the hint row's evidence; it passes before and after, as the message says).
- Shown failing, run again by me (an export of `2e05a9b^` with the commit's three test files): the hint test
  (`'Let it reach…ocal network.' == 'Let it reach…he app knows.'`) and the facts (`A1.9: the s… desktop for`);
  2 failed, 47 passed. The message says `tests/test_requirements_trace.py` fails too "until its row is there": on
  the parent, which has neither the sentence nor the row, it passes; it is a check of the commit's own state.
- On the fix (stopped agent's logs): tier 1 2733 passed, 130 skipped; the launcher tier 139 passed, 5 skipped in
  each container.

**#202 (CR1.11-86), fixed: `0d659f9`** (Fable 5.2). One list of the portals, R17.5's: A1.2.3.6 and A1.9 point to it,
A1.2.3.12 says what kinds the list has and keeps the GLib note, A1.2.3.14's "(always)" row points to R17.5. No
requirement and no code changes; A1.2-approach.md three lines shorter, the room batch 2's doubt 8 asked for.

- Test: the fact "R17.5: the one list of the portal interfaces" (`tests/test_docs_facts.py`): no sentence outside
  R17.5 names three or more of the interfaces.
- Shown failing, run again by me (export of `0d659f9^`, the commit's test file): the facts test, on that fact;
  1 failed, 6 passed. On the fix, tier 1 2733 passed, 130 skipped (stopped agent's log).

**#201 (CR1.11-85), fixed: `5b22d69`** (Fable 5.2). A1.2.3.6 says what R17.6.3 says: refused the file chooser,
GTK 4.14 fell back and GTK 4.18 showed nothing, hence `GDK_DEBUG=no-portals`. No requirement and no code changes.

- Test: the fact "R17.6.3: which GTK4 falls back to its own dialog" (`tests/test_docs_facts.py`).
- Shown failing, run again by me (export of `5b22d69^`, the commit's test file): the facts test, on that fact;
  1 failed, 6 passed. On the fix, tier 1 2733 passed, 130 skipped (stopped agent's log).

**#692 (CR1.9-32), fixed: `99b7bd2`** (begun by Fable 5.2, finished by Opus 5.5). Taken over: the uncommitted change
in `sandbox.py` (`_CAP_CHIP` says "Keep the screen awake" and "Saved passwords", and the comment above the portal
interfaces quotes the new chip), A1.2.3.14 (the "(chip: …)" spellings gone, its paragraph says a chip says what its
switch says), `tests/test_docs_facts.py` (the chips' fact held to the table's dialog names) and the new test in
`tests/test_sandbox.py`. I read it whole and kept all of it unchanged: no other place in the code, the QML or the
documents names the old chip words, and no requirement names the chips' words.

- Test, the class: `test_a_chip_names_a_capability_as_its_switch_in_the_sandbox_dialog_does` reads the switches from
  `SandboxDialog.qml` and holds to their labels the chip each capability and the camera add to a bare Standard set,
  and the names `SECRET_CAPS` gives a keyring capability refused to a review.
- Shown failing (export of `1d56bd3`, the code before, with the two test files): `AssertionError: inhibit` (`['Keep
  screen awake'] == ['Keep the screen awake']`) and the facts test; 2 failed, 247 passed.
- On the fix: the touched files with `tests/test_sandbox_properties.py` (which reads `_CAP_CHIP`) and the four
  document checks, 2034 passed; tier 1 in its container 2734 passed, 130 skipped. The stopped agent also ran the
  launcher tier on a snapshot it named 692 (139 passed, 5 skipped in each container); the change touches no launcher.

### Listed items

**new**: none.

**needs your eye**

- `0583283` (#403): R17.5 moves NetworkMonitor and ProxyResolver from every app on the bus to the network grant and
  says the launcher sets `GIO_USE_PROXY_RESOLVER=dummy` for a Standard app without it; A1.2.3.12 and A2's inventory
  follow. The variable is no decision's own word: it is what keeps the decided remedy from failing every GLib
  connection, the loopback included, in an app without the network.
- `2e05a9b` (#404): what the user sees, the Network switch's hint for a Standard app: "Let it reach the internet and
  the local network. Without it the app can still ask the desktop to open a link, which may carry what the app
  knows." (Strict keeps the first sentence alone.) R17.17 gains the sentence "No network is not no way out: …"; A1.9
  a bullet, A1.10 a row.
- `0d659f9` (#202): A1.2.3.6, A1.2.3.12, A1.2.3.14 and A1.9 point to R17.5's list instead of copying it. No requirement.
- `5b22d69` (#201): A1.2.3.6's sentence on GTK4's fallback. No requirement.
- `99b7bd2` (#692): what the user sees, the summary's chips on the install card, App Detail and the Sandbox dialog:
  "Keep the screen awake" for "Keep screen awake", "Saved passwords" for "Secrets". A1.2.3.14's paragraph and table.
  The rule "a chip says what its switch says" is in the design and the test, not in a requirement: no requirement
  names the chips' words.

**needs a run**

1. `scripts/test-sandbox.sh launcher-vm` and `launcher-vm26`, `scripts/test-desktop-vm.sh run mint22.3` and
   `run lmde7`: #403 changes the filter's portal rules and the launcher's environment for an app without the
   network, and its GLib test and #404's offline-editor case are new in the launcher tier; neither is shown
   outside the containers. With batches 1 and 2's runs, when the last batch is in.
2. The screenshot tour (CI's `tour` job): "Keep the screen awake" is a longer chip than the one it replaces; I did
   not look at it on screen.
3. The project's own commands, which neither agent ran as such (the worktree has no `build/`): `scripts/test-tier1.sh`,
   `scripts/test-sandbox.sh launcher`, `launcher-lmde7`. Their container commands were run by hand, on the same images,
   with the main checkout's `build/` Python and PySide6 mounted read-only and a 3 GB cap.

**guard**: exit 0 after `99b7bd2`, with no file to add but those of `docs/relay/`. The four earlier commits'
files are all in U09's files.

### Doubts for the coordinator

1. **The two agents shared one scratch folder.** `/tmp/cr1-u09-b3/` was the stopped agent's, and my first run there
   overwrote its `tier1.sh` (with batch 2's, the same command), its draft `msg-692.txt`, `snap-692/` and
   `tier1-692.log`. Its other logs and exports are as it left them; the numbers above for its commits come from them.
   My own exports are the `mine-*` folders there.
2. **What the stopped agent ran for #692 before it stopped** is not known from its files: its launcher logs for "692"
   are from a snapshot taken at 3:14 PM, which my copy replaced. The launcher tier does not read the chips.
3. **A chip's words are stored**: `sandboxReviewSeen` (`src/appkata/backend.py`) keeps the summary's labels to tell
   a new review suggestion from one seen. A suggestion seen under the old words would show as new once; no one uses
   AppKata yet, so nothing is carried over, as the brief says.
4. **#404's message** says `tests/test_requirements_trace.py` fails on the commit before; run on the parent it passes
   (see #404 above). The other tests it names fail there as it says.
5. **The four earlier commits carry `Co-Authored-By: Claude Fable 5.2`**, the model they ran on, made before 4 PM.
   `99b7bd2` carries Opus 5.5.
6. `A1.2-approach.md` is at 497 of its 500 lines: batch 4's text there has three lines of room.
7. No refusal and no model change on my side.

### The coordinator, after batch 3 (2026-11-24)

Batch 3 ran in two parts: a Fable 5.2 agent made #403, #404, #202 and #201 and stopped at its usage
limit in the middle of #692; an Opus 5.5 agent finished #692 and wrote the section above. Checked:
both agents' answers on their named models; the guard; `tests/test_sandbox.py` and the document
tests, whole; the batch pushed.

- **Doubt 4** (#404's message names a test that passes on its parent): the commit message is loose,
    the fix is proven by the other tests it names. Said in the pull request, not amended.
- **Doubt 3** (a suggestion seen under the chips' old words shows as new once): no carry-over, as
    the brief says.
- **Doubt 6:** `A1.2-approach.md` has three lines left. Batch 4 writes what it must say of the
    keyring and the ScreenSaver interface in `A1.2.3.14`'s table, replacing words, not adding lines;
    if it can't fit, it lists it and the coordinator decides.
- **Batch 4 runs on Opus 5.5.** #693 is a check that needs a desktop: the agent writes the command
    under needs a run and does what it can without the desktop (the launcher's words, and a test
    that holds them); the coordinator runs the desktop and settles it.
- **Needs a run** (the Ubuntu launcher VMs, the desktop VMs, the tour, the project's own scripts):
    the coordinator's, after batch 4.

