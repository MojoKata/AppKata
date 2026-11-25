# Relay progress: CR1's unit U04, downloads, checksums and what App Detail says of them

4 batches cover the unit's 15 findings, taken from `docs/remediation/CR1-schedule.json` at
`upstream/master` 6c3d380: batch 1 the High finding and what a release's version and an app's name
may be as a part of a path; batch 2 the installed file's SHA-256 and what App Detail and the review
dialog say of it; batch 3 what Verified means and the file an administrator's command installs;
batch 4 download() and the checksum fetch.
One agent at a time; the coordinator checks each batch before the next starts, and pushes.
U05 is stacked on this branch and merges its pushed tip in before each of its batches.

## Batch 1

Fable 5.2 at high effort, 2026-11-25. Nothing uncommitted was found in the worktree; nothing was
taken over.

**Files touched:** `src/appkata_core/install.py`,
`docs/requirements/R4-installing-updating-and-uninstalling.md`, `tests/test_install_review.py`,
`tests/test_windows.py`, `tests/skips/windows.txt`, `docs/relay/progress.md`.

**Counts:** fixed 4, no defect 0, remedy changed 0, set aside 0, still left 0, new 3 (two fixed
here, each in a commit of its own; one listed only).

### The findings

Each test was shown failing by exporting the commit before the fix (`git archive`) to a scratch
folder, putting the new test file over it, and running the new tests there in a scratch home.

- **#306 (High), fixed, `1bd3953`.** `_file_name` reduces the release's file name once, at the top
    of `install()`, to what follows its last `/` or `\`, and refuses what is then no file's name;
    that one name makes every path (the download and its `.part`, `_place`'s destination, the
    pending setup, the failure path's delete). `_in_folder` is the check at the place of use. The
    record's `asset` column keeps the release's own name: backend.py compares it with the
    release's names only (checked at its two reads), and nothing compares the reduced name with a
    release's. forges.py is not changed (the alternative, not taken): both it and
    `tests/test_forges.py` leave #306's files.
    Tests, in `tests/test_install_review.py`:
    `test_a_release_file_named_as_a_path_is_kept_under_its_last_part_in_the_apps_own_folders`
    (6 forms of a path × AppImage, archive, self-updating AppImage),
    `test_a_download_named_as_a_path_that_fails_its_checksum_is_deleted_where_it_was_downloaded`
    (runs on Windows too), `test_appkatas_own_setup_named_as_a_path_waits_in_the_updates_folder`
    (Windows' road, any system), `test_the_one_file_name_a_release_file_is_kept_under` (name by
    name, as Linux and as Windows; the Startup-folder name is one),
    `test_a_release_whose_file_has_no_usable_name_is_refused_before_anything_is_downloaded`,
    `test_no_name_is_joined_to_a_folder_unless_it_names_a_file_in_it`.
    Before the fix: 100 of the 101 cases fail. Of the 27 that install or download, 26 fail: the
    user's or another app's file replaced or deleted, the setup placed outside the updates
    folder, or the download stopped at a folder that isn't there. The one that passes is the
    backslash name on Linux, where it is one file's name: Windows' case.
- **#307, fixed, `7002f9c`.** `_safe` puts `_` before a name that starts with a dot; `_place`
    makes the version's folder through `_in_folder`. The release is installed (in `_../`), not
    refused. Tests: `test_a_release_whose_version_is_dots_gets_a_folder_in_the_apps_own_and_takes_no_other_apps`,
    `test_a_version_is_always_one_plain_name_in_the_apps_folder` (every string up to five
    characters of `./\ a_`, both systems), `test_no_version_is_placed_in_a_folder_that_isnt_in_the_apps_own`.
    Before the fix: all 8 cases fail. **What the finding says happened no longer does:** since
    CR1.3-13 (`_swap_in`, U03) the folder is renamed aside, not emptied, which the system refuses
    for `.` and `..`, so before this fix such an install stopped with a raw "Device or resource
    busy" and nothing was deleted. The name was still the defect, and is what is fixed.
- **#628, fixed, `b66ddab`.** `_file_stem`, one helper for the four places (the record says three;
    U03 added `_enter_fixed_layout`), falling back to the app's id. It takes the id as the name of
    the app's folder, which all four places have; `_place` has no record for `app_id_of`.
    Tests: `test_an_app_whose_name_has_no_ascii_letter_or_digit_gets_its_id_in_the_file_named_after_it`
    (the fixed layout, versions with the stable link, and back) and
    `test_the_file_named_after_an_app_has_its_names_ascii_letters_and_digits_or_its_id` in
    `tests/test_install_review.py`; `test_a_portable_program_is_named_after_its_app_or_by_the_apps_id`
    in `tests/test_windows.py` (Windows' road, any system). Before the fix: 8 of 10 fail
    (`.AppImage`, `1.0/.exe`); the two that pass are the names that don't change.
- **#699, fixed, `07634b5`.** `_version_folder`: `_` before a version that is `current` or `run`,
    compared without case on every system. The escaped name, not the refusal, as #307 went.
    Tests: `test_a_release_whose_version_is_a_name_appkata_keeps_in_the_apps_folder_is_installed_beside_it`
    (sandboxed and not), `test_the_folder_a_version_is_unpacked_into`. Before the fix: all 10 fail
    (`current`: "exists and isn't a link AppKata made"; `run`: a raw "Is a directory", at the
    install when sandboxed and at the sandbox change when not; `Current` and `RUN` on the name
    only: on Linux they could be installed before).
- `c5a8e32`: the lines of `tests/skips/windows.txt` for the Linux-only tests of #306, #307 and
    #628, which their own commits lacked (see the doubts).

### Needs your eye

- `1bd3953` (#306): R4.8.2 says what `<file>` is and which names aren't installed. The message
    of the refusal, an install error like the others: "the release's file has a name that can't
    be used ('<name>'); nothing was installed".
- `7002f9c` (#307): R4.3.1 says how a version is written as a name (`_` for other characters,
    `_` before a leading dot: `_..`).
- `b66ddab` (#628): R4.3.1.2 says what a file named after an app is named, and `app.AppImage`.
- `07634b5` (#699): R4.3.1: a version `current` or `run`, in any case, is in `_current/`. On
    Linux a version `Current` was installable before, in `Current/`.
- `59fa749` (new): R4.3.1: a version ending `.new` or `.old` is in `2.0.old_/`.
- `b583897` (new): a portable Windows program of an app named Con is `_Con.exe` (R15.16 says so
    already; no text changed).

### Needs a run

- **The Windows VM** (the coordinator's): `scripts/test-windows-vm.sh --tests`. The tests of this
    batch that aren't Linux-only run there on real Windows, none of which could run here:
    #306's checksum-failure test with real backslashes and a `C:\` path, the pending setup,
    `_file_name` and `_in_folder` on Windows' own paths; #628's portable `.exe`; the new finding's
    `_Con.exe` (the one proof that Windows takes that file); `_safe` and `_version_folder`.
    The four Linux-only tests are in `tests/skips/windows.txt`.
- No container was needed or run. Run here, in a scratch home, all passing:
    `tests/test_install_review.py`, `tests/test_windows.py` and `tests/test_skip_lists.py` whole
    (476 passed, 6 skipped), the document checks (37 passed), and beside them
    `tests/test_backend.py`, `tests/test_sandbox_transitions.py`,
    `tests/test_sandbox_docs_current.py`, `tests/test_sandbox.py`, `tests/test_selfinstall.py`
    and `tests/test_core.py`, which install too. Tier 1 whole is CI's.

### Guard

- `tests/skips/windows.txt`: "no other unmerged unit claims it: add it to U04's files".

### New

1. **Fixed, `b583897`. A portable Windows program of an app named as a device is `Con.exe`.**
    `src/appkata_core/install.py`, `_place` (the `.exe` lines, now `_file_stem`). Case: an app
    named Con, AUX, nul! or "Com 1", installed as a portable `.exe`: its program is `Con.exe`,
    `AUX.exe`, `nul.exe`, `Com1.exe`, names R15.16 says are avoided by adding `_`, as the app's
    folder and Start-menu shortcut do. By reading: not run on Windows. Low. Test:
    `tests/test_windows.py::test_a_portable_program_of_an_app_named_as_a_device_has_a_name_windows_accepts`
    (4 of 6 fail before). #365 (U10) widens `windows.safe_name`; its record calls the shortcut's
    name "the one place this can reach", and since this batch `_file_stem` and `_file_name` (the
    refusal on Windows) go through it too.
2. **Fixed, `59fa749`. Installing 2.0 deletes a version named 2.0.new or 2.0.old.**
    `src/appkata_core/install.py`, `_place` (`staging = vdir + ".new"`, removed first) and
    `_swap_in` (`_aside`, removed first). Case, run on this branch before the fix: with version
    2.0.new in use, an install of 2.0 from an archive that can't be unpacked leaves the app's
    folder with a `current` link to nothing (R4.6); a kept 2.0.new or 2.0.old is gone after 2.0
    is installed, and leaves the kept list. Low: it takes a project that releases both names, and
    only that app's versions are lost. Test:
    `tests/test_install_review.py::test_installing_a_version_never_removes_one_named_as_its_staging_or_set_aside_folder`
    (6 of 12 fail before; `.NEW` passes on Linux, Windows' case).
3. **Not fixed. Two versions whose names come out as one folder name: the later takes the
    earlier's folder, and the earlier is no longer kept.** `src/appkata_core/install.py`, `_place`
    (the archive branch has no `others`, as the AppImage branch has since CR1.3-13) with `_safe`.
    Case, run: an archive app at version `1.0 beta`, updated to `1.0_beta` with keep 3: one folder
    `1.0_beta`, kept versions none, where R4.3.1.5 keeps the previous one. Since this batch
    `current` and `_current` are such a pair too. Low. Not small: it needs a rule for the second
    name.

### The real home

Every run's `diff` of `/home/dev/bin`, `/home/dev/.local/share/appkata` and
`/home/dev/.local/share/applications` before and after was empty.

### Doubts

- **The skip lines came late.** The commits of #306, #307 and #628 each added a Linux-only test
    without its line in `tests/skips/windows.txt`; the brief asks for it in the same commit. Seen
    at #699, whose commit has its own line; `c5a8e32` adds the other three. No commit was
    amended. Between `1bd3953` and `c5a8e32` the Windows run would fail on those skips.
- **#307's severity.** Its worst effect was already gone when this batch started (above). The
    issue may want that said.
- **#306, refuse or rename on Windows.** The remedy says to refuse the names Windows reserves,
    and the fix does, with the characters Windows can't hold and a trailing dot or space
    (whatever `windows.safe_name` would change). R15.16's own rule for the names AppKata makes is
    "by adding `_`". A release's file with such a name is refused, not renamed: the remedy's
    words, and one rule fewer. Also refused beyond the remedy's list: a control character.
- **`_in_folder` is stricter than the remedy's `commonpath`**: directly in the folder, not
    anywhere under it. Every path it checks is a single name in its folder.
- **#699 leaves `app` out.** `app` is the fixed layout's folder (R4.10.2); in the versioned
    layout AppKata keeps nothing there, and a version named `app` over a kept `app/` is new
    finding 3's case, not a failed install.
- **A checksum file's line and a file named as a path** (batch 4's ground, #304 and #314):
    `expected_sha256` compares a line's base name with the release's name as it came, so a file
    the release names `sub/x.tar.gz` never matches its line and installs Unverified. Not changed
    here.
- **The Windows suite wasn't run.** What the new tests do on real Windows rests on reading them
    against `ntpath`; the VM run above is their first.
- **The runs before each fix wrote outside their test's folder**, as the defect does: #306's left
    a file in pytest's own temporary folder (`/tmp/pytest-of-dev/pytest-<n>/`, which pytest
    rotates), nowhere else.
