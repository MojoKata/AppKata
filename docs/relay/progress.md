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

## Batch 2

Fable 5.2 at high effort, 2026-11-25. Nothing uncommitted was found in the worktree; nothing was
taken over. No failure of CI's was written here for batch 1's commits.

**Files touched:** `src/appkata/backend.py`, `src/appkata_core/install.py`,
`src/appkata/qml/AppDetail.qml`, `src/appkata/qml/ReviewDialog.qml`, `src/appkata/qml/PopMenu.qml`,
`docs/requirements/R4-installing-updating-and-uninstalling.md`,
`docs/requirements/R10-trust-and-the-appkata-md-file.md`, `tests/test_backend.py`,
`tests/test_install_review.py`, `tests/test_channel_ui.py`, `tests/test_sandbox_ui_surfaces.py`,
`tests/skips/windows.txt`, `docs/relay/progress.md`.

**Counts:** fixed 4 (one of them with its remedy changed in two points, listed), no defect 0, set
aside 0, still left 0, new 2 (neither fixed here).

### The findings

Each test was shown failing by exporting the commit before the fix (`git archive`) to a scratch
folder, putting the new test files over it, and running the new tests there in a scratch home.

- **#465 (Med), fixed, `1269665`.** `detail()` gives an installed app's chip from its install
    record (`verify`: signed, checksum or unverified, with `verifyTip` from `checksum_source`), and a
    forecast for the file Install or Update would take (`forecast`: published or none, with
    `forecastVersion`), read from the release that file is a file of (`_release_of`), not from
    `releases[0]`. App Detail shows the installed chip whatever the newest release holds (the
    QML's `&& !!root.d.asset` is gone) and the forecast as its own chip. R4.4 has the paragraph.
    Tests: in `tests/test_backend.py`,
    `test_an_installed_apps_chip_is_what_its_own_install_checked_whatever_the_next_release_publishes`
    (6 records), `test_an_installed_app_has_its_own_chip_and_no_forecast_when_there_is_no_file_to_take`,
    `test_a_file_that_isnt_installed_yet_gets_a_forecast_read_from_its_own_release` (6 kinds of
    release; case 4 is two of them), `test_nothing_is_forecast_for_an_app_install_isnt_offered_for`;
    in `tests/test_sandbox_ui_surfaces.py`, the chips and their tooltips read from the real App
    Detail: `test_app_detail_shows_what_the_installed_file_was_checked_against_and_a_forecast_for_the_next_one`.
    Before the fix: 18 of the first 19 fail (the two for foreign and Track only were written after
    that run and can only fail there: the key is new); the one that passes is the signed record in
    the QML, which was read before. Most fail on the new keys, so the old values were read
    directly too, on the code before: case 1 gave `checksum`, case 2 `unverified`, case 4
    `unverified` for a file whose own release has a `SHA256SUMS`. Cases 1, 2 and 4 reproduce; case 3
    is #328's (batch 4) and is as it was.
- **#467 (Med), fixed, `cb5f115`, the remedy changed in two points.** `install()` keeps the
    download's SHA-256 in the record, `installed_sha256(record, version)` reads it, and `detail()`
    and the review dialog's Details use it. R4.1 names it.
    1. **By version**, `"sha256": {<version>: <digest>}` with the kept versions' own, not the one
        key `"sha256": got`: `switch_to` makes a kept version current with no download, and it must
        have its own file's digest. It is in the record and not in the version's own entry
        (`current`), because `tests/test_sandbox_transitions.py` holds that entry to its three keys
        and is U03's and U17's file, not this unit's: the first form of the fix failed two of its
        tests, and was changed, not the test.
    2. **No fall-back to the release's data.** The remedy and the record's proof have one "for
        records made before that": left out by the brief's rule (nothing for what an earlier
        version stored). Records without a digest are otherwise those of copies AppKata never
        downloaded, where the forge's digest of a same-named file is the finding's own false claim.
    Tests: `tests/test_install_review.py::test_the_record_keeps_the_sha256_of_each_versions_own_download`
    (three installs with keep 1, then a switch back; Linux-only, its skip line is in the same
    commit) and `::test_a_record_has_no_sha256_for_a_copy_appkata_didnt_download`;
    `tests/test_backend.py::test_the_installed_files_own_sha256_is_what_a_reviewers_is_compared_with_and_what_a_review_says`
    (5 cases) and `::test_a_file_not_yet_installed_is_compared_by_the_digest_its_release_gives`.
    Before the fix: 7 of 8 fail (the pill shown for the replaced file and never for the installed
    one, no SHA-256 line without a forge digest, no digest in the record); the one that passes is
    the file not yet installed, which is unchanged.
- **#466 (Med), fixed, `84d5cb6`.** `_same_digest` is true only for the same 64 hexadecimal digits.
    R10.3.4 says so and R10's example has a whole digest. Tests:
    `tests/test_channel_ui.py::test_same_digest_and_source_settings` turned round (15 shortened or
    wrong forms, and two shortened values that agree), and
    `tests/test_backend.py::test_same_file_is_said_only_of_a_reviewers_whole_sha256` (7 forms ×
    installed and about to be installed, through `detail()`). Before the fix: 11 of 15 fail (every
    shortened form was a match); the 4 that pass are the whole digests.
- **#497 (Low), fixed, `086192d`.** The Version menu holds every choice and scrolls: `PopMenu` has
    a `maxHeight` (0, the default: as tall as its rows, as before), which this menu sets to 460.
    The Details preview shows each line as written, wrapped. Scrolling the list is the remedy
    taken, not the "more…" step. Tests, in `tests/test_sandbox_ui_surfaces.py`:
    `test_the_review_dialogs_version_select_reaches_every_release_and_every_reviewed_version` (25
    releases and a review of a version that is no longer one: the wheel is turned over the menu
    and the row clicked, for the newest, the installed oldest and the reviewed one),
    `test_a_menu_with_no_height_set_is_as_tall_as_its_rows_and_doesnt_scroll`,
    `test_the_review_dialog_shows_the_details_it_will_write_whole`. Before the fix: all 3 fail (12
    rows where 27 are expected; `- SHA-256: 5e5e5e5e5e5e…`; the second has no scrolling part to
    read). The screens were also rendered offscreen from a scratch copy and looked at.

### Needs your eye

- `1269665` (#465): **R4.4's new paragraph**, and what App Detail shows:
    - a file not yet installed: **Checksum published** or **No checksum published** where
        Checksum or Unverified was, in the same colours. Tooltip: "2.0 publishes a checksum for
        the file Update would take: the download is checked against it." / "2.0 publishes no
        checksum for the file Install would take: there is nothing to check the download against."
    - the Checksum chip's tooltip: "Checked against the forge's digest" / "Checked against
        SHA256SUMS" (the file's name).
    - **an installed app whose record names no check is Unverified**, AppKata's own adopted copy
        among them, with the tooltip "AppKata adopted this copy as it found it and didn't download
        it, so it checked nothing". Before, its chip was the next release's (Checksum, on GitHub).
    - no forecast where neither Install nor Update is offered: a copy installed outside AppKata,
        a Track only app, a channel's update, an AppKata that only tells of its releases. Those
        showed Checksum or Unverified before.
- `cb5f115` (#467): **R4.1** lists "the SHA-256 of that file as it was downloaded" (the record
    named no requirement to change; R8.4.5.1 fills Details "from the install record (R4.1)").
    An app AppKata didn't download has no SHA-256 line in a review's Details and no pill.
- `84d5cb6` (#466): **R10.3.4's two new sentences** and **R10's example digest**, now 64 digits
    (made up: `3c1f6a0b…be9e07`).
- `086192d` (#497): the Version menu is at most 460 high and shows a scroll bar while it scrolls;
    12 plain rows were 480 before. The Details preview wraps a long line.

### Needs a run

- **CI's tour job** (#465): App Detail's screens change. Not made here.
- **The Windows VM** (the coordinator's): `scripts/test-windows-vm.sh --tests`. Of this batch only
    `tests/test_install_review.py::test_a_record_has_no_sha256_for_a_copy_appkata_didnt_download`
    runs there (the rest need PySide6 or the Linux layout, and are in `tests/skips/windows.txt`).
    Nothing asserts on Windows that an installer's record has its digest: the line that writes it
    is the same for every kind.
- No container was needed or run. Run here, in a scratch home, all passing: the touched test
    files whole (`tests/test_backend.py`, `tests/test_install_review.py`,
    `tests/test_channel_ui.py`, `tests/test_sandbox_ui_surfaces.py`), `tests/test_skip_lists.py`,
    the document checks, every other test file that loads QML, and `tests/test_windows.py`,
    `tests/test_selfinstall.py`, `tests/test_sandbox_transitions.py`, `tests/test_sandbox.py`,
    `tests/test_sandbox_backend.py`, `tests/test_core.py`, `tests/test_channels.py`,
    `tests/test_dialog_contract.py`. Tier 1 whole is CI's.

### Guard

Nothing: every file changed is in U04's files.

### New

1. **Not fixed. A review of an app installed from a package channel says "Channel: GitHub
    release" and has no Commit.** `src/appkata/backend.py`, `_review_versions` (the `details`
    lines). Case, run on this branch: Demo installed as a Flatpak (record `channel: flatpak`, a
    64-digit `commit`): the review dialog's Details are Date, Platform and `Channel: <forge>
    release`, with no Commit line. R8.4.5.1: "Date, Platform, Channel, and File and SHA-256, or the
    Flatpak Commit"; R10.3.4's examples: `Flathub org.zettlr.Zettlr (verified)`, `Debian package
    3.5.1-1`. So a published review names a channel the reviewer didn't install from, and the
    Commit half of R10.3.4's pill has only hand-written Details to match. Low (Med if a wrong
    fact in a published, signed review counts as one). Not small: the Channel line for a Flatpak
    and for a package, and the Commit.
2. **Not fixed. After a Flatpak is updated outside AppKata its record holds the shortened commit,
    so "Same file" can't show for it.** `src/appkata_core/sync.py`, the `rec["commit"] = i.commit`
    line of the Flatpak pass (its own comment: "`flatpak list` shows a shortened commit").
    By reading, not run. Before #466 a reviewer's whole commit didn't match such a record either
    (`mine.startswith(theirs)`); only a shortened one did, which is what #466 ends. Low. Not this
    unit's file.

### The real home

Every run's `diff` of `/home/dev/bin`, `/home/dev/.local/share/appkata` and
`/home/dev/.local/share/applications` before and after was empty.

### Doubts

- **The tour's demo installs.** `scripts/demo_data.py` (not this unit's file; shared) gives its
    .deb, .rpm and tarball installs the record `{}`, and AppKata's own copy `verified: adopted`:
    those App Detail screens will now say **Unverified** where they said Checksum. Its AppImage
    installs have `verified: checksum` and stay Checksum. If the tour should show checked
    installs, `inst()` there needs `{"verified": "checksum", "checksum_source": "forge digest"}`.
- **Unverified for a record with no result.** R4.4 has three chips, and #318's record uses
    Unverified for the unchecked case, so an adopted AppKata is Unverified, not chip-less. The
    alternative is no chip at all for it.
- **#467 without the fall-back** departs from its record's proof ("a record without one falls
    back to the release's"), by the brief's rule. Say so on the issue.
- **`_release_of` finds the release by the file's name and URL.** `catalog.build` doesn't say
    which release `asset` came from, and `catalog.py` is not in #465's files. Two releases that
    list one URL under one name would give the newer; their file is then the same one.
- **#656 (a first install goes around the minimum age)** makes the forecast describe the file the
    catalog offers (the eligible release's), while Install today takes the newest release's. The
    forecast follows the catalog's file; #656's fix makes the two one.
- **A wheel event with no timestamp scrolls a menu once and no further** (Qt's Flickable reads
    the wheel's speed from it). The test's events carry one, as real ones do; without it the menu
    looked stuck after 72 pixels. Nothing in the product: said so the next reader of that helper
    knows why the line is there.
- **`tests/test_sandbox_ui_surfaces.py` holds #465's chip test**, though #465's record names
    `tests/test_backend.py`: the harness that loads the real App Detail is there. The new
    Version-select test takes about 5 seconds (the wheel's animation).
- **The pending setup's record** (AppKata's own setup on Windows) gets no digest here: that is
    #326's (`pendingSha256`), in another unit.
