# Relay progress: CR1's unit U03, the portable install

Four batches cover the unit's 16 findings, taken from `docs/remediation/CR1-schedule.json` at
`upstream/master` 1c5c06c: batch 1 the two High findings and #388, batch 2 the command link and the
menu entry, batch 3 folders and versions through an update, batch 4 the program picked and started.
One agent at a time; the coordinator checks each batch before the next starts, and pushes.

## Batch 1

Done 2026-11-24 by one agent (Fable 5.2, high effort), on `cr1-u03-portable-install` from 2de5a26.

**Files touched**

- `src/appkata_core/install.py`, `src/appkata_core/selfinstall.py`, `src/appkata_core/sync.py`,
  `src/appkata_core/sandbox.py`, `src/appkata/backend.py`
- `tests/test_install_review.py`, `tests/test_selfinstall.py`, `tests/test_sandbox.py`,
  `tests/test_sandbox_adversarial.py`, `tests/test_sandbox_run.py`, `tests/test_sandbox_transitions.py`,
  `tests/test_launcher_golden.py`, `tests/test_sandbox_state.py`, the six goldens in `tests/data/launchers/`
- `docs/requirements/R4-installing-updating-and-uninstalling.md` (R4.3.1.3),
  `docs/requirements/R17-app-sandboxing/R17.4-the-launcher.md`,
  `docs/architecture/A1-app-sandboxing/A1.2-approach.md`, `docs/requirements-trace.md`

**Counts**: fixed 3, no defect 0, remedy changed 0, set aside 0, still left 0, new 4.

**The findings**

| Finding | Outcome | Commit | Tests | Shown failing on the code before |
|---|---|---|---|---|
| #305 (High) | fixed | e0c3004 | `tests/test_install_review.py`: `test_a_projects_name_and_summary_cannot_add_a_line_to_the_menu_entry` (12 line-ending characters), `test_the_menu_entry_escapes_the_path_it_starts_and_refuses_one_it_cannot_write`, `test_sync_stores_a_projects_name_and_summary_as_one_line_each` (metainfo, forge); `tests/test_selfinstall.py`: `test_appkatas_own_menu_entry_escapes_its_path_and_a_folder_it_cannot_start_is_refused_first` | `git archive` of 2de5a26 with the two test files copied in: 16 failed, 22 passed, each on its own assertion (the injected `MimeType=`, `Terminal=`, `[X]` lines; the unescaped path; the stored line breaks) |
| #407 (High) | fixed | 0b7e5bb | `tests/test_sandbox_adversarial.py`: `test_nothing_on_the_callers_path_is_ever_run_by_a_launcher` (5 grant sets, menu and command), `test_a_launcher_runs_no_host_command_but_the_listed_ones`, `test_whatever_the_helper_prints_is_read_as_arguments_and_never_run` (10 answers), `test_every_argument_survives_the_forward_helper_and_the_launchers_reading_of_it`; `tests/test_install_review.py`: `test_an_app_named_after_a_command_is_installed_without_a_command_link` (9 names), `test_no_command_link_is_ever_named_after_a_command_a_launcher_or_appkata_runs`, `test_an_apps_own_command_link_is_replaced_and_one_that_becomes_a_command_goes`, `test_a_link_that_is_not_appkatas_is_never_replaced_by_a_command_link`, `test_the_install_notice_says_why_no_command_was_added_and_says_it_once`; the six goldens | `git archive` of e0c3004 with the test files copied in: 47 failed. The install tests fail on behaviour (the link is made, `DID NOT RAISE`), the helper-answer tests on behaviour (`ESCAPED` on stderr, `=two: command not found`: the answer ran as shell). The two PATH tests fail there on `build_launcher` having no `path`; the scenario itself was run against that code by a scratch script (a stand-in for every command first on the caller's PATH): the stand-ins `mkdir`, `python3`, `readlink` and `bwrap` ran and the helper's output printed `ESCAPED-TO-THE-HOST-SHELL`; on the fix, none ran |
| #388 (Low) | fixed | d8f06b8 | `tests/test_sandbox.py`: `test_no_app_name_takes_the_place_of_a_file_appkata_keeps_for_every_app` (14 names, as the first app and after another); `tests/test_sandbox_transitions.py` reads the marker's new path; `tests/test_sandbox_state.py` looks for the marker after the startup pass; the six goldens | `git archive` of 0b7e5bb with the two test files copied in: 29 failed. For "bin", "Bin" and "BIN!" with the finding's own errors (`FileExistsError` as the first app, `IsADirectoryError` after another); the other names on the layout check |

Each commit: the touched test files whole with the project's venv, the four document checks, and the
whole of tier 1 in its container (doubt 7 says how, from a worktree): 2763 passed, 121 skipped for
#388, 2735 passed for #407. For #305 the first such run had 5 failures, all git's ("not a git
repository": my container lacked the main checkout's `.git`); with it mounted, their four files
passed (79), and every later run had it. For #407 and for #388 the launcher tier's two containers
too, Mint 22.3 (bwrap 0.9.0) and LMDE 7 (bwrap 0.12.0): 130 passed, 5 skipped (all listed), each time.

**Remedy, where it differs in a detail** (each said in its commit; none changes the behaviour asked)

- #407: the helper's answer reaches the launcher as lines of data through the command substitution,
  not as NUL-separated words in a file. POSIX sh can't read NUL-separated input, so the words would
  need the same line encoding either way.
- #407: the name check is Linux's alone (`_activate_linux`). Windows' `.cmd` links are untouched: see **new**.
- #388: the markers moved (`.identity/apps/<id>`), the first of the finding's two ways.
- #388: the record's proof asks that a 0.1.0 state's old marker be removed by the startup pass. Not
  done: the brief rules out logic for what an earlier AppKata wrote. The startup pass does rewrite
  such a launcher, and writes its marker at the new path; the old `.identity/<id>` file stays. So
  `tests/test_sandbox_state.py`, which thaws the 0.1.0 state, had to change: it asserted the marker
  at `identity_path()` before the startup pass, and now asserts it after (doubt 9).

**new** (no finding covers them; nothing was changed for them)

1. `src/appkata_core/install.py:231`, `desktop_exec`: GLib looks for an entry's program before it reads
   `%%` as `%`, so an app-menu entry whose program's path holds a `%` (an install folder named
   `50% off`) is taken for an app that isn't installed and doesn't show in a GLib desktop's menu
   (Cinnamon, GNOME, MATE, Xfce). Seen with GLib 2.80: `Gio.DesktopAppInfo.new_from_filename` returns
   NULL. Unescaped, the entry showed and started a wrong path. The entry is now written as the
   specification says; whether to refuse such a folder instead is the owner's.
2. `src/appkata_core/desktop.py:75` and `:107`: the autostart entry and the `appkata://` handler's
   entry write `Exec=` with `shlex.quote`, not the Desktop Entry quoting #305 gave the other two
   entries: single quotes for a path with a space (outside the specification; GLib accepts them), `%`
   and a backslash unescaped. AppKata's own path, not a project's text. (`desktop.py` is U14's and U41's.)
3. `src/appkata_core/install.py`, `_activate_windows` (line 620): a Windows command link `<app>.cmd`
   is still written for an app named after a command (`git.cmd`, `python3.cmd`). The folder goes at
   the end of the user's PATH there, so it shadows nothing the system has, but it does answer for a
   command that isn't installed. The owner's decision on #407 names no platform.
4. `src/appkata/qml/InstallDialog.qml:230-236`: the install dialog still offers "Command `<app>` in
   `<folder>`" for a name that will be refused; the reason is said only by the notice after the
   install. `Backend.planFor` could carry `install.command_link_refusal`'s answer.

**needs your eye**

- e0c3004 (#305): an app's name and summary show in the app menu as one line each, control
  characters as spaces. A new refusal, as an install error: "couldn't add the app-menu entry: '…' has
  a quote or a line break in it, which a menu entry can't start" (for AppKata's own install:
  "Couldn't install AppKata: …"). Sync stores the name and the summary as one line.
- 0b7e5bb (#407): R4.3.1.3 says when no command link is made, and R17.4 that the launcher sets its
  own PATH and never evaluates its helper's answer (two new rows in `docs/requirements-trace.md`).
  A new notice after an install: "<App> <version> installed. No command was added: python3 is a name
  kept for the system's own command." or "… : ls is already a command on this computer (/usr/bin/ls)."
  The reserved names are `install.RESERVED_COMMANDS` (about 55): the "short list" is my pick.
  Every installed app's launcher is rewritten at the next start (its text changed).
- d8f06b8 (#388): A1.2 names the marker's new path (the outline and A1.2.3.13). Nothing a user sees.

**needs a run**

- `scripts/test-sandbox.sh launcher-vm` (the Ubuntu 24.04 VM), for #407 and #388: the launcher under
  AppArmor's restriction with the fixed PATH. `scripts/test-sandbox.sh launcher-vm26` likewise.
- `scripts/test-desktop-vm.sh run mint22.3` (and `lmde7`), for #305 and #407: the menu entries a real
  Cinnamon session shows, and the launchers started from it.
- `scripts/test-windows-vm.sh --tests`: nothing Windows-only changed, but `tests/test_install_review.py`
  gained tests that run there (`test_sync_stores…`, `test_no_command_link_is_ever_named…`,
  `test_the_install_notice…`), and `sync.py` now imports `install.one_line`.

**guard**

- `tests/test_launcher_golden.py`: no other unmerged unit claims it; add it to U03's files. Its
  `fixed_host` pins where the host's bwrap is (`sandbox.host_path`), with the host's other facts (#407).
- `tests/test_sandbox_state.py`: no other unmerged unit claims it; add it to U03's files (#388).

The guard reads commits (`upstream/master...HEAD`), so before a commit it says nothing of that
commit's files: I checked each file against the schedule first, and ran the guard after each commit.

**Doubts**

1. **Stand-ins in three other units' test files.** `tests/test_sandbox_exposure.py` (U36, U46),
   `tests/test_sandbox_one_fact.py` (U05, U34) and `tests/test_sandbox_user_shaped.py` (U05) put a
   stand-in bwrap on the PATH a launcher is started with, which no longer decides anything. I didn't
   touch them: `Env.run` in `tests/test_sandbox_run.py`, which all three use, runs a copy of the
   launcher with the test's PATH in its one PATH line (`Env.on_a_machine_with`). They pass unchanged,
   in tier 1 and in both launcher containers. Their units may prefer to give the folders when the
   launcher is written (`build_launcher(path=…)`, or `sandbox.host_path` patched).
2. **Systems whose commands aren't in `/usr/local/bin:/usr/bin:/bin`.** `host_path` adds the folder of
   a bwrap found elsewhere, and nothing else. On NixOS or Guix a launcher no longer finds `mkdir` or
   `stat`. R1.1 names no such system.
3. **The option stays on when the link is refused.** The link is then made at a later update or
   start once the name is free, and removed when its name becomes a command. The decision says
   "no command link for it, and say so"; turning the option off instead is the other reading.
4. **"Already a command" is judged by AppKata's own PATH** plus the system's folders. An AppImage's
   PATH may hold more than the user's shell does, so it can refuse a name the shell wouldn't find.
5. **`bwrap_path()` and AppKata's own commands** (`git`, `gpg`, `flatpak`, `pkexec`) still resolve
   through AppKata's PATH. No link of AppKata's is named after them now; a file of the user's own in
   `~/bin` still is found first. #385 and #379 are about those lookups.
6. **A refused `Exec=` path (#305) is an InstallError raised in `_activate`**, after the files are
   placed: #313's road (batch 2) for a program in an archive whose path holds a quote.
7. **How tier 1 and the launcher tier were run.** The worktree has no `build/`, and
   `scripts/test-tier1.sh` would fetch the Python and PySide6 into it. A scratch script made the same
   `docker run` (the same image, Python and PySide6, from the main checkout's `build/`, read-only,
   `APPKATA_SKIPS` set, held to 3 GB) over the worktree; likewise for `scripts/test-sandbox.sh launcher`
   and `launcher-lmde7`. Nothing was written into either checkout.
8. **This machine's `/bin/sh` is bash.** The launcher's new lines were run under dash too: tier 1's
   image and both launcher containers.
9. **The 0.1.0 state after #388.** A machine that ran 0.1.0 keeps a stray `.identity/<id>` file per
   sandboxed app, and one whose first app was named "bin" still can't write its shims, until that
   file is removed by hand. The record wanted the old marker removed and the brief says no such
   logic; if the owner wants it, it is three lines in `sandbox.write_flatpak_info`.

### The coordinator, after batch 1 (2026-11-24)

Checked: every answer of the agent on its named model; the guard; the touched fast tests and the
document tests, whole. `upstream/master` (U01 and U02, merged since) is taken in by a merge, and
the batch is pushed.

- **New findings filed:** #685 (new 1, the `%` in a path: the owner's choice, so it carries
    `refine` and is set aside in the schedule), #686 (new 2, `desktop.py`'s two entries: U14's),
    #687 (new 3, the Windows `.cmd` links: U14's, by the same decision as #407) and #688 (new 4,
    the install dialog's checkbox: this unit's, added to batch 2).
- **Guard:** `tests/test_launcher_golden.py` and `tests/test_sandbox_state.py` are in U03's files now.
- **Doubt 2** (#388 leaves an earlier version's marker where it is) is right: no logic for what an
    earlier AppKata wrote.
- **Doubts 3, 4 and 5** (the option stays on when a link is refused; the 57 reserved names; the
    fixed PATH on a system whose commands live elsewhere) go to the owner under Needs your eye in
    the pull request. Nothing for a later batch to change.
- **Doubt 1** (other units' test files that put a stand-in bwrap on the caller's PATH) is noted for
    those units.
- **Needs a run** (the launcher VMs, the two desktop VMs, the Windows VM tests): the coordinator
    runs them once, when the unit's last batch is in.

## Batch 2

Done 2026-11-24 by one agent (Fable 5.2, high effort), on `cr1-u03-portable-install` from 6672771.

**Files touched**

- `src/appkata_core/install.py`, `src/appkata/backend.py`, `src/appkata/qml/InstallDialog.qml`
- `tests/test_install_review.py`, `tests/test_windows.py`, `tests/test_dialog_contract.py`, `tests/skips/windows.txt`
- `docs/requirements/R4-installing-updating-and-uninstalling.md` (R4.3.1, R4.3.1.3, R4.6, R4.9.2)

**Counts**: fixed 5, no defect 0, remedy changed 0, set aside 0, still left 0, new 4.

**The findings**

| Finding | Outcome | Commit | Tests | Shown failing on the code before |
|---|---|---|---|---|
| #313 (Low) | fixed | ba17c17, and 3a1ff30 (a gap in it, found by a probe: doubt 1) | `tests/test_install_review.py`: `test_a_refused_install_leaves_everything_as_it_was` (four refusals, three of them real, as a first install and as an update), `test_whichever_step_of_an_install_fails_nothing_of_it_is_left` (each of five steps failing once × a first install, an update, the update out of the fixed layout, a kept version × sandboxed or not: 40 cases), `test_a_failed_first_install_takes_nothing_that_was_there_before_it`; `tests/test_windows.py`: `test_a_refused_portable_install_leaves_everything_as_it_was` (Windows' road on any OS, 6 cases) | `git archive` of 6672771 with the two test files copied in: 53 failed, 61 passed, each on what was left (`apps/demo-tool/Tool-2.0-x86_64.AppImage`, `cmd/demo-tool`, `apps/tool/2.0.new/…`, `current -> 2.0` under 1.0's record). For 3a1ff30: `git archive` of 4e5cc71, the update case of the fourth refusal fails (`apps/tool/2.0.new` left) |
| #309 (Low) | fixed | cf926df | `tests/test_install_review.py`: `test_what_the_user_put_where_a_command_link_was_is_never_removed_or_replaced` (a link to their program, a link to nothing, a file × an update, a kept version, the next start, uninstall × on and off the PATH: 24 cases) | `git archive` of ba17c17: 16 failed, the 16 with a link (9 `DID NOT RAISE`: the link was replaced; 3 no `commandRefused`: it was removed, then replaced; 4 at uninstall: the link was gone). The 8 with a file passed there and hold the class |
| #331 (Low) | fixed | ea28f92 | `tests/test_install_review.py`: `test_a_folder_typed_in_settings_is_read_one_way_for_the_apps_and_for_their_command_links` (`$HOME`, `${HOME}`, `~`, `$HOME/../home`, another variable) | `git archive` of cf926df: 5 failed. Four on the finding's own behaviour (the record holds `$HOME/bin/demo-tool`); `~`, which worked, only on the new `Portable.command_folder` |
| #312 (Low) | fixed | adcaa82 | `tests/test_install_review.py`: `test_what_an_option_made_goes_when_it_is_turned_off_and_nothing_outlasts_uninstall` (the app menu, the stable name, the command link × an update, the next start, a kept version), `test_an_update_that_shows_the_app_to_be_a_command_line_tool_takes_its_menu_entry_away` | `git archive` of ea28f92: 4 failed, the three of the app menu and the tool's (the entry still on disk). The 6 of the other two options passed there and hold the class |
| #688 (Low) | fixed | 4e5cc71 | `tests/test_dialog_contract.py`: `test_the_install_dialog_offers_no_command_checkbox_to_tick_for_a_name_no_link_is_made_for` (python3, Git, ls, Demo), `test_an_installed_apps_own_command_link_does_not_disable_its_checkbox` | `git archive` of adcaa82 with the test file copied in: 5 failed, each on the plan carrying no answer (`None == "python3 is a name kept for the system's own command"`); the dialog's half can't be reached there. The dialog was also looked at: an offscreen grab with the pointer on the disabled checkbox shows it unticked and dimmed, with its tooltip |

Each commit: the touched test files whole with the project's venv, the four document checks and
`tests/test_skip_lists.py`, the guard, and the whole of tier 1 in its container (doubt 12): 2833
passed for #313, 2857 for #309, 2862 for #331, 2872 for #312, 2877 for #688, 2879 for 3a1ff30, each
with 121 skipped, all listed. No launcher's text changed, so the launcher tier wasn't run.

**Remedy, where it differs in a detail** (each said in its commit; none changes the behaviour asked)

- #313: what is taken back after an update is made by running `_activate` again for the stored
  record, with the options that record has (`_options_of`), as the finding says; the result is
  stored, so the record is what is on the disk. `switch_to` had the same fault and got the same
  check and the same way back; no finding named it.
- #313: the check before placing covers the command link's place and a menu entry that can't start
  the app's folder, on Linux, and someone else's `<app>.cmd` on Windows. The stable link and the
  Start-menu shortcut can't be judged before the files are there; they are taken back.
- #309: the install half was closed by #407. For the rest, a link is AppKata's only when it leads
  into the install folder. The remedy's other clause ("or its path is in the app's recorded links")
  is not taken: the record's proof asks that uninstall leave a link the user put at the recorded
  path, and one link can't be the user's for uninstall and AppKata's for an update.
- #331: the for-everyone folder on Windows goes through the same helper (it had no `~`).
- #312: an entry is removed when it is named `appkata-*` and is in today's applications folder, as
  the record's note asks; one recorded anywhere else stays in the record, so uninstall removes it.
- #688: the checkbox is shown unticked while disabled, and the option the dialog sends is unchanged
  (R4.3.1.3 keeps it on). The tooltip is on an item around the checkbox: a disabled control gets no hover.

**new** (no finding covers them; nothing was changed for them)

1. `src/appkata_core/windows.py:424`, `remove_shim`: uninstalling on Windows, and an update whose
   command links folder changed (`install.py`, `_activate_windows`' loop over `rec["shims"]`),
   removes whatever file is at the recorded `<app>.cmd` path without looking for AppKata's first
   line, which `write_shim` does look for. A `.cmd` the user put there since is deleted. It is
   Windows' side of #309's uninstall half. Read, not run.
2. `src/appkata_core/install.py:1069`, `rewrite_launcher` (a sandbox change, the startup pass): when
   the command link's place holds something of the user's, `_activate` rewrites the launcher and the
   menu entry and then stops at the command link with an InstallError; the record (its `sandbox`
   and `launcher`) isn't stored, and the backend only logs it (`_regenerate_launcher`). Seen in
   #309's test (the "next start" cases raise). A file there did this before; since #309 a link of
   the user's does too, where it used to be replaced. Not taken back as an install is: that would
   put the old launcher back, and the launcher is the enforcement. A rewrite could go on without
   the command link and record why, as it does for a name that is a command; that is a choice.
3. `src/appkata_core/install.py:458`, `_place`: an archive's version folder is named by the version,
   and `current` (the stable link) and `run` (the sandbox launcher) are names in the same folder. A
   release whose version is "current" can't be installed: as a first install `_link` refuses
   ("…/current exists and isn't a link AppKata made"), as an update the rename fails with
   NotADirectoryError. Run by a scratch script (1.0, then "current", then 2.0). "run" by reading.
4. `src/appkata_core/install.py:652`, `_activate_windows`: `windows.make_junction` raises
   FileExistsError when `current` exists and isn't a junction, and nothing turns it into an
   InstallError as the shortcut's and the command link's refusals are, so the backend reports it
   through its handler for crashes. Read, not run.

**needs your eye**

- ba17c17 (#313): R4.6 gains "A portable install that fails leaves nothing of itself behind: after
  a first install there is no app folder, link, launcher or app-menu entry; after an update, or a
  switch to a kept version, the version that was current still is, with its links, its launcher and
  its app-menu entry." The errors' words are unchanged; a refusal at the command link now comes
  before anything is placed.
- cf926df (#309): R4.3.1.3 now reads "AppKata never replaces or removes a file there that isn't a
  link it made (a link that leads into the install folder), whether or not it made a link at that
  place before: an install or update stops with an error instead, and uninstalling leaves it." So
  an update of an app whose command link the user replaced with their own stops with "… exists
  and isn't a link AppKata made; not replacing it" (off the PATH), or goes on without a command
  and says why (on it), until the link is gone or the app's command option is off.
- ea28f92 (#331): R4.3.1 gains "The install folder and the command links folder (R4.3.1.3) are
  read the same way: a leading `~` is the user's home folder, and environment variables are filled
  in (`$HOME/bin`; on Windows `%LOCALAPPDATA%\Programs` too)." No requirement said how either was read.
- adcaa82 (#312): no requirement changes. An app's menu entry now goes at the next update or
  start once its option is off, and when an update shows it to be a command-line tool.
- 4e5cc71 (#688): R4.9.2 gains "On Linux the command checkbox is disabled and unticked when no
  command link would be made for the app's name (R4.3.1.3), with the reason as its tooltip ("No
  command will be added: `ls` is already a command on this computer (/usr/bin/ls)."); the option
  itself stays as it was." New interface: that disabled state and that tooltip.

**needs a run**

- `scripts/test-windows-vm.sh --tests`: `tests/test_windows.py`'s new test has only run off Windows,
  where the junction is a symbolic link (on Windows it is real, and only the shortcut and the PATH
  edit are stood in); `install.py`'s Windows branches of `_check_before_placing` and
  `_undo_portable` have run nowhere else; and `tests/skips/windows.txt` has 13 new lines no run has
  held it to (doubt 9).
- CI's `tour` job (`scripts/test-layout.sh`), at the next push: the install dialog's layout with
  #688's item around the command checkbox. Tier 1's own dialog and layout tests pass.
- `scripts/test-desktop-vm.sh run mint22.3` (and `lmde7`), with batch 1's: #312's entry leaving a
  real Cinnamon menu.

**guard**

- `tests/skips/windows.txt`: no other unmerged unit claims it; add it to U03's files. A new
  Linux-only test needs its line there, or the Windows run fails on the skip (#313, #309, #331,
  #312, and #688 for the one below).

**Doubts**

1. **#313 has two commits.** A probe after #688 (a release whose version is "current") showed
   `_place` leaving `<version>.new` when its last step, the rename, fails during an update. That is
   #313's own promise, so 3a1ff30 closes it under #313's number, with no amend. The class test
   didn't have it: its failing steps start at the stable link, and the three real refusals of
   `_place` were all before the rename.
2. **What is taken back is made again, so a failure that lasts isn't.** After a failed update
   `_undo_portable` runs `_activate` for the previous record. A step that fails for good (a full
   disk) fails there too: it is logged, and the install's own error is the one shown. The tests'
   failing steps fail once.
3. **Every failed update puts the previous version's links back, disturbed or not**: one that failed
   in `_place`, before anything of the previous version was touched, still has its links, launcher
   and entry written again, the same.
4. **An app that updates itself (#311 b, batch 3)**: `install()` removes its installed files before
   it places the new ones. The undo puts its links and entry back, not its files. Once #311 keeps
   the files until the update succeeds, the undo needs nothing more.
5. **The check before placing runs after the download**, where the folders are known in
   `install()` today. A refused install has downloaded its file first (R4.8.2 then deletes it).
   The command link's check could move ahead of the download.
6. **#309 makes one case stricter than the finding's remedy**: see "Remedy" above. The way out
   for the user is to remove their link, or untick the command in Install options.
7. **#331 leaves a relative folder relative** to AppKata's working directory, for both folders, as
   the install folder was. R4.3.1's new sentence doesn't promise it.
8. **#688 asks with the name the dialog shows** (`Backend._app_id`): the name's slug before an
   install, though a first install takes `<slug>-2` when another install holds the slug
   (`install.new_app_id`). The dialog's "Command `<app>`" has always shown the slug. And the
   reason is a tooltip only: nothing says it to a keyboard or a screen reader.
9. **`tests/skips/windows.txt` gained lines for batch 1's tests too**: five Linux-only tests of
   `tests/test_install_review.py` that #305 and #407 added without their lines, and
   `test_the_install_notice_says_why_no_command_was_added_and_says_it_once`, which imports the
   backend and so needs PySide6, which the Windows run doesn't have (it now skips there, with its
   line). Without them the Windows run would have failed on six tests. None of this has run on Windows.
10. **A folder made on the way stays**: a failed first install leaves the install folder itself
    (`~/bin/apps`) and a command links folder `_link` made, both empty. The tests' comparison
    leaves empty standing folders out.
11. **`tests/test_install_review.py` is now 986 lines** (646 before this batch); its `_left`
    snapshot is also used by `tests/test_windows.py`.
12. **How tier 1 was run**: as batch 1's doubt 7, by a scratch script making the same `docker run`
    as `scripts/test-tier1.sh` over the worktree, with the main checkout's Python, PySide6 and
    `.git` read-only, held to 3 GB. Nothing was written into either checkout.
13. **The session's working directory was moved twice under me** (to the main checkout, then to
    another unit's worktree). Every command of mine began with a `cd` into this worktree, every
    commit was made from it, and `git status` in both of those checkouts showed nothing of mine
    afterwards.
