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
