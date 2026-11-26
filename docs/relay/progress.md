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

## Batch 3

Fable 5.2 at high effort, 2026-11-25. Nothing uncommitted was found in the worktree; nothing was
taken over. No failure of CI's was written here for batch 2's commits.

**Files touched:** `docs/requirements/R4-installing-updating-and-uninstalling.md`,
`docs/requirements/R15-windows.md`, `docs/requirements/R16-package-channels.md`,
`scripts/channels_e2e.py`, `src/appkata/backend.py`, `src/appkata/qml/AppDetail.qml`,
`src/appkata/qml/AppRow.qml`, `src/appkata_core/catalog.py`, `src/appkata_core/flatpak.py`,
`src/appkata_core/foreign.py`, `src/appkata_core/install.py`, `src/appkata_core/pkgbackend.py`,
`src/appkata_core/windows.py`, `tests/test_backend.py`, `tests/test_channels.py`,
`tests/test_docs_facts.py`, `tests/test_install_review.py`, `tests/test_sandbox_ui_surfaces.py`,
`tests/test_windows.py`, `tests/skips/windows.txt`, `docs/relay/progress.md`.

**Counts:** fixed 3 (one of them with its remedy changed in one point, listed), no defect 0, set
aside 0, still left 0, new 4 (one fixed here, in a commit of its own; three listed only).

### The findings

Each test was shown failing by exporting the commit before the fix (`git archive`) to a scratch
folder, putting the new test files over it, and running the new tests there in a scratch home. The
channels container was run from a scratch script that makes `scripts/test-channels.sh`'s own
`docker run` with this worktree as the sources and `--memory 3g`, one container at a time.

- **#223 (Med), fixed, `157c5ba`.** R4.4 lists the two checks that are made (a published checksum;
    Authenticode on Windows), says that a publisher's signature beside a release's file is not
    checked, and defines Verified by the three that check a signature (Windows, flatpak against
    its remote's key, the package manager against its repository's keys). `docs/gpg.md` said so
    already and is not changed. Test: a new fact in `tests/test_docs_facts.py`, "R4.4: the checks
    made before installing", which holds R4.4's numbered list to the checks `install()` makes.
    Before the fix it fails ("a publisher's signature": the document True, the code False).
- **#318 (Med), fixed, `8cf997c` (and `336cd40`, one line of R16.6.1).** The record of a channel's
    copy holds what the tools say, asked each time AppKata installs, adopts or updates it
    (`install.channel_verdict`): a Flatpak is `signed` when its own remote is one of the
    installation's with signature checking on (`flatpak.checks_signatures`, from
    `flatpak remotes --columns=name,options`); a package when a repository offers the installed
    version (`pkgbackend.signed_by`, from `apt-cache policy`), with the repository's own name
    (its release's `o=`, else `l=`) as the signer; everything else is `unverified`. `detail()`
    takes the chip and its tooltip from the record, never from `ch`; the QML's fixed "Signed by
    Flathub" is gone. The Unverified chip is R4.4's existing one; no fourth chip, and no refusal
    to adopt (the alternatives, not taken). The dnf half is fixed the same way, by reading
    (`dnf repoquery --installed`'s `%{from_repo}` and a signature in the package).
    **Beyond the stated remedy, by its own rule:** a repository apt is told to trust without a
    key (`[trusted=yes]`, `Trusted: yes`, read through `apt-get indextargets`' `$(SOURCESENTRY)`)
    doesn't make a package `signed`. It is the finding's own case, and the channels container's own
    repository: its package would have read Verified.
    Tests: in `tests/test_channels.py`,
    `test_a_package_is_signed_only_where_a_repository_whose_key_apt_checks_offers_the_installed_version`
    (9 forms of `apt-cache policy`, recorded from Ubuntu 24.04: the distribution's, a PPA's, by
    hand, by hand over the distribution's, a version no longer offered, a trusted-without-a-key
    repository…), `test_a_sources_entry_that_takes_a_repository_without_a_key`,
    `test_an_rpm_is_signed_only_from_a_repository_and_with_a_signature`,
    `test_flatpak_checks_a_remote_against_its_key_unless_told_not_to`,
    `test_a_flatpak_install_records_whether_its_remotes_key_checked_it`,
    `test_an_adopted_flatpak_is_signed_only_where_its_own_remotes_key_checked_it`,
    `test_a_package_is_recorded_as_what_apt_says_checked_it_when_adopted_installed_or_updated`;
    in `tests/test_backend.py`,
    `test_a_channels_copy_has_the_chip_its_record_says_and_none_for_being_from_a_channel` (10
    records) and `test_a_package_no_repository_checked_is_named_by_no_distribution`; in
    `tests/test_sandbox_ui_surfaces.py`, three more cases of the App Detail chip test and
    `test_the_apps_row_of_a_package_names_its_repository_only_where_the_record_has_one`.
    Before the fix: 50 of the 61 cases fail; the 11 that pass are what was right already
    (Flathub's own, the distribution's own, a row with a name). Many of the 50 fail on a function
    that isn't there yet; the ones that show the old behaviour directly are the records
    (`signed` by "Ubuntu" for a package put in by hand, by "Flathub" for a Flatpak of another
    remote) and the chip (`signed` for every record with a channel).
    **Container:** `scripts/channels_e2e.py` now asks the real tools, and passed in the ubuntu,
    ubuntu-pk and mint runs: a package of the local `[trusted=yes]` repository is not Verified,
    before and after its update; the distribution's `hello` is Verified, signed by "Ubuntu",
    adopted and installed; `hello` put in by hand over it (`dpkg -i`) is adopted as not Verified;
    a Flatpak from the `--no-gpg-verify` remote is not Verified, installed and adopted.
- **#327 (Med), fixed, `c76ed33`, the remedy changed in one point.** What runs with administrator
    rights takes its own copy of the file, compares the copy's SHA-256 with the one AppKata took of
    the download, and installs that copy.
    Linux, `pkgbackend.Cli.install_file`: after the dry run and its review, `pkexec` runs
    `/bin/sh` with a fixed script whose words are the file, the SHA-256 and the package manager's
    command. It makes a folder under `/var/cache` (`mktemp -d`, root's alone until the copy is
    checked), copies, hashes, compares, and hands the copy to `apt-get install` or `dnf install`;
    a copy that differs exits 65 with "the downloaded file changed after AppKata checked it;
    nothing was installed". A release's package file never goes to PackageKit (its `InstallFiles`
    branch is removed); `install()` takes the command line of the file's own kind.
    Windows, `windows.run_elevated`: what is elevated is Windows PowerShell, by its full path,
    with a script (`-EncodedCommand`, its values as base64) that makes a folder in Windows' `Temp`
    folder with a protected ACL of Administrators and SYSTEM, copies, hashes, compares, and starts
    the copy through the shell (an `.msi` with System32's `msiexec`), handing back its exit code.
    Used where AppKata itself elevated: an `.msi` or a known `.exe` installer for everyone, and
    the Visual C++ run-time.
    **The point changed:** on Windows the copy is made in Windows' own `Temp` folder, not in "the
    locked-down all-users folder" of the decision. `C:\Programs` (R15.4.3) is protected against
    other accounts and belongs to the user who made it, who may always change its permissions
    (R15.4.3 relies on that), so a program of the user's could rename it while the copy is checked.
    The decision's own rule, "a place only … administrators can write", is what is kept.
    Tests: in `tests/test_install_review.py`, with stand-in package tools on the PATH and the real
    script, `test_a_releases_package_is_installed_from_roots_own_copy_of_the_file_that_was_checked`
    (deb, rpm), `test_a_package_swapped_after_its_check_is_refused_on_the_administrators_side`
    (other bytes, the same size in place, a link to another file × deb, rpm; the swap is a hook
    after the dry run), `test_a_releases_package_never_goes_to_packagekit_which_takes_a_path_and_no_checksum`,
    `test_a_package_whose_plan_needs_the_users_ok_is_copied_nowhere_before_it_is_given`; in
    `tests/test_channels.py`, `test_a_package_file_is_installed_by_one_command_as_root_that_copies_checks_and_installs`
    (pkexec's words and the script's order) and `test_packagekit_is_never_handed_a_file`; in
    `tests/test_windows.py`, `test_an_installer_for_everyone_is_started_by_the_script_that_copies_and_checks_it`,
    `test_an_installer_appkata_doesnt_elevate_is_started_as_before`,
    `test_an_installer_that_isnt_the_file_that_was_checked_is_not_started`,
    `test_the_visual_cpp_runtime_is_started_by_the_same_script_held_to_the_file_whose_signature_was_read`,
    `test_the_administrators_side_starts_only_the_file_that_was_checked_from_a_folder_of_its_own`
    (the script's rules on any system; on Windows itself it is run).
    Before the fix: 21 of the 26 cases fail (the swapped file was installed; the package manager
    was handed the downloads path; PackageKit was asked for `InstallFiles`; the download itself
    was elevated). Two of the 21 (a declined prompt, a failed installer) fail there on the test's
    own stand-in, not on a behaviour that changed. The 5 that pass are what didn't change.
    **Container:** `scripts/channels_e2e.py` installs a real `.deb` from a "release" as root and,
    **through the real pkexec, as a user** with none of root's rights (polkit is told to let that
    one user through; the rule is removed after), then swaps the file after the dry run for a
    package whose script would run as root. Passed in the ubuntu, ubuntu-pk and mint runs. On the
    code before the fix the same script, in the ubuntu container: "a file swapped after its check
    is refused: it was installed" and `('6.6-6', True, [])`, the other package installed and its
    script run as root.
- `24c5a0d`: the new finding 1 below, fixed in a commit of its own.

### Needs your eye

- `157c5ba` (#223): **R4.4**: its list is two checks; the sentence "A signature a publisher puts
    beside a release's file (a GPG `.asc` or `.sig`, a minisign `.minisig`, a sigstore bundle) is
    not checked."; and what **Verified** means, by the three that check a signature.
- `8cf997c` (#318): **R16.3.6**, rewritten with its condition, and what App Detail shows:
    - **Unverified** for a channel's copy no key checked, where every channel's copy read
        Verified. Tooltips: "No key checked this copy: flatpak doesn't check its remote, <remote>,
        against one" / "Its remote isn't known, so AppKata can't tell that a key checked this
        copy" / "No repository offers the installed version (<version>), so AppKata can't tell
        that a repository's key checked it" / "No key checked this package: it is from
        <repository>, which isn't checked against one".
    - the Verified chip's tooltip is "Signed by <the record's signer>": the Flatpak's own remote
        (it said Flathub for every Flatpak), the package's repository by its own name (a PPA reads
        "Signed by LP-PPA-…"), or "Signed by its repository".
    - **a package's names come from its repository, not from the system**: on Mint a package
        from Ubuntu's archive reads "Ubuntu" where it read "Linux Mint" (its label, its Apps row,
        "Ubuntu 1.2-1 · project 1.2").
    - a package whose record names no repository has the label **Package** (it was the
        distribution's name), and its Apps row ends "· .deb".
    - **a distribution's package with an update pending is adopted as Unverified**: its
        repository no longer offers the installed version, so nothing says a key checked it. It
        turns Verified when AppKata updates it.
- `336cd40` (#318): **R16.6.1** lists the label **Package**.
- `c76ed33` (#327): **R4.4's new paragraph**, **R15.2's clause**, **R15.7.5** (new),
    **R15.18.3's clause**, **R16.8.5** (new). What the user meets:
    - on Windows the **UAC prompt of an installer for everyone names Windows PowerShell**
        (publisher Microsoft Windows), not the installer; for an `.msi` it named Windows Installer
        already.
    - a `.deb` or `.rpm` from a release is installed by `apt-get` or `dnf` through `pkexec` also
        on a desktop where PackageKit runs: the password is asked by pkexec's own prompt, once for
        this action, and the install doesn't queue behind a store's.
    - two new errors: "the downloaded file changed after AppKata checked it; nothing was
        installed" and "Windows couldn't make the administrators' copy of the installer or start
        it; nothing was installed".
    - **R15.7.5's last paragraph is a limit**: an installer AppKata starts without administrator
        rights and that asks Windows for them itself runs from the downloads folder as before.
- `24c5a0d` (new): an update from a release's `.deb` or `.rpm` no longer asks to confirm "Upgrades
    <the app's own package>".

### Needs a run

- **The Windows VM** (the coordinator's). The PowerShell script of `windows.run_elevated` **has
    run on no Windows**: it rests on reading. In this order:
    1. `scripts/test-windows-vm.sh --tests`. On real Windows, in the VM's session, which has
        administrator rights (so no UAC prompt): `tests/test_windows.py::test_the_administrators_side_starts_only_the_file_that_was_checked_from_a_folder_of_its_own`
        runs the real script with a copy of `cmd.exe` as the installer. It should show: exit code
        0; the installer ran from `C:\Windows\Temp\AppKata-<32 hex>`; that folder's ACL is
        Administrators and SYSTEM, full control, nothing else (`icacls`, English names); the
        folder is gone afterwards; a file one byte longer than its checked SHA-256 gives
        `CHANGED` (0x4B410001) and isn't started; a missing file gives `NOT_STARTED`
        (0x4B410002); an installer's own exit code (3010) comes back. **First thing it decides:**
        whether `ShellExecuteEx` takes the command line (about 6,000 characters of
        `-EncodedCommand`); a failure there is an `OSError` from `shell_execute`.
        The other new tests of `tests/test_windows.py` and `tests/test_channels.py` run there too,
        with stand-ins; the five Linux-only ones of `tests/test_install_review.py` are in
        `tests/skips/windows.txt`.
    2. `scripts/test-windows-vm.sh --e2e`. KeePassXC's `.msi` for everyone and Git's Inno Setup
        for everyone now go through `run_elevated`: check both install (their HKLM entries), that
        the `.msi`'s log is written, and that nothing is left in `C:\Windows\Temp\AppKata-*`.
    3. What neither shows, because the VM's session is already elevated (G#59): the UAC prompt
        itself (that it names Windows PowerShell), a swap made while it waits, SmartScreen's
        warning with the Mark of the Web on, and whether an antivirus objects to a hidden,
        encoded PowerShell started by AppKata.
- **CI's tour job**: App Detail of the demo's Flatpak and package (records `signed` by Flathub
    and Ubuntu: still Verified, tooltips "Signed by Flathub" and "Signed by Ubuntu").
- **The desktop VMs** take `tests/test_channels.py` (`scripts/sandbox/vm-desktop.sh`): its new
    tests run there with every tool stubbed. Not run here.
- **dnf**: nothing runs it (R1.1). `pkgbackend._rpm_signed_by` and the `.rpm` half of
    `install_file` rest on reading and on stand-ins.
- Run here, in a scratch home, all passing: the touched test files whole
    (`tests/test_channels.py`, `tests/test_backend.py`, `tests/test_sandbox_ui_surfaces.py`,
    `tests/test_install_review.py`, `tests/test_windows.py`, `tests/test_docs_facts.py`),
    `tests/test_skip_lists.py`, the document checks, and beside them `tests/test_channel_ui.py`,
    `tests/test_core.py`, `tests/test_selfinstall.py`, `tests/test_qml_slots.py`,
    `tests/test_sandbox_backend.py`, `tests/test_dialog_contract.py`,
    `tests/test_demo_promises.py`. The channels container: ubuntu, ubuntu-pk and mint, after the
    last code change. Tier 1 whole is CI's.

### Guard

- `tests/test_docs_facts.py`: "a shared file: add it to U04's files" (#223's fact).
- `src/appkata/qml/AppRow.qml`: "a shared file: add it to U04's files" (#318: one expression, so
    the row doesn't end "· .deb · " for a package with no repository's name).

### New

1. **Fixed, `24c5a0d`. Updating an app installed from a release's `.deb` or `.rpm` asks to confirm
    "Upgrades <the app's own package>", every time.** `src/appkata_core/pkgbackend.py`,
    `Backend.plan` (`targets = [os.path.basename(n) …]`): for a file the review's target is the
    file's name, which is no package's, so the package the file holds counts as "another package"
    being upgraded (R16.3.5 asks only for those). Case, run: `review()` on apt's own plan for the
    update ("Inst akfile [1.0-1] (2.0-1 …)") with the file as the target gives `confirm:
    ['Upgrades akfile']`. Low. `Cli.install_file` takes the package's name, which `install()`
    already reads from the file. Tests: `tests/test_channels.py::test_updating_an_app_from_its_releases_package_file_asks_only_about_other_packages`
    (4 plans) and `tests/test_install_review.py::test_an_update_from_a_releases_package_file_upgrades_the_apps_own_package_without_asking`;
    before the fix all 5 fail, the first plan and the install on the confirmation itself, the
    other three on the new argument. `scripts/channels_e2e.py` updates 1.0-1 to 2.0-1 from a
    "release" with the real apt, as root and as a user: it passes, and on the
    code before (`c76ed33`) fails with `['Upgrades akfile']`.
2. **Not fixed. A channel copy's Verified outlives the copy.** `src/appkata_core/sync.py`,
    `track_channel_installs` (the `rec["commit"] = i.commit` and `rec["pkgVersion"] = ver` lines,
    after `_changed_elsewhere`): when the copy is changed outside AppKata the record keeps the
    `verified` and `signer` of the copy that was there. Case, by reading: a distribution's
    package AppKata adopted as Verified, then a vendor's `.deb` of that name put over it with
    `dpkg -i`: the Audit says "was updated outside AppKata", App Detail still says Verified,
    "Signed by Ubuntu", until AppKata itself updates it. The same for a Flatpak whose remote's
    signature checking is turned off. Med by docs/REVIEW.md's rule (a trust verdict the code
    didn't establish), the class of #318. The fix is one line at each of the two places:
    `rec.update(install.channel_verdict(rec))`. Not this unit's file.
3. **Not fixed. An `.msi` installed for everyone writes its log, as administrator, into the
    downloads folder.** `src/appkata_core/install.py`, `_run_installer`
    (`msi_log = os.path.join(tmpdir, "msi.log")`, passed as `/l*v`). The folder is the user's, so
    a program of the user's can decide what is at that path before the elevated `msiexec` opens
    it for writing. By reading, not run; whether Windows lets it be turned into a write elsewhere
    was not tried. Low. The same question as #327, #326 and #370; left as it was by #327's fix
    (the log's path is one of the script's words).
4. **Not fixed. A refused plan never reaches the dialog that says so.** `src/appkata_core/install.py`,
    `_apply` (and `install()`'s package branch, which keeps its behaviour): every `PackageError`
    but `NeedsConfirmation` becomes an `InstallError`, `Refused` among them, so
    `src/appkata/backend.py`'s two `except Refused` / `except PackageRefused` branches (the plan
    dialog with `refused: True`) can't be reached, and a plan that would remove what the computer
    needs (R16.3.5) is an error toast. By reading. Low.

### The real home

Every run's `diff` of `/home/dev/bin`, `/home/dev/.local/share/appkata` and
`/home/dev/.local/share/applications` before and after was empty.

### Doubts

- **#327 on Windows departs from the decision's words** ("installers run from the locked-down
    all-users folder") for the reason above. If the owner wants that folder all the same, it is
    one line of the script; the copy's own folder would still be Administrators' and SYSTEM's.
- **The elevated PowerShell is a shape antivirus products watch** (hidden window, encoded
    command, started by another program). It calls .NET alone on purpose (a cmdlet could be the
    user's own module), which doesn't change how it looks from outside. The other way is a small
    signed helper program of AppKata's own: a choice for the owner if the VM or a real desktop
    shows a product objecting.
- **An installer that elevates itself is not covered** (R15.7.5 says so): "Other NSIS, WiX Burn,
    InstallShield" and any installer AppKata doesn't recognise. AppKata can't know beforehand
    that Windows will ask. Covering it means reading the file's manifest, or elevating every
    installer for everyone: a `refine` if wanted.
- **#318, the trusted-without-a-key rule is more than the remedy says.** It reads the sources
    entry apt names; a `.sources` file is judged whole (one `Trusted: yes` counts for each of
    its stanzas). `APT::Get::AllowUnauthenticated` and `Acquire::AllowInsecureRepositories` in
    apt's configuration are not read. Where `apt-get indextargets` says nothing, the remedy's own
    rule (a repository line) decides.
- **#318, "a version no longer offered" is Unverified**, as the remedy has it: it will be seen
    on adopting any distribution package that has an update waiting. The tooltip says what
    AppKata can't tell, not that the package is bad.
- **#318's dnf half**: a signed package from a repository with `gpgcheck=0` would read Verified
    (the signature is there; whether dnf checked it is not asked). No Fedora ran any of it.
- **`ch.distro` now means the repository** (it is the record's `signer`). The rows that use it
    as the distribution's name ("<distro> doesn't update this automatically", AppRow.qml) read
    "LP-PPA-… doesn't update this automatically" for a PPA's package, and "The system …" for a
    package with no repository's name.
- **An adopted Flatpak's `remote` is the copy's own origin**, no longer the link's remote when
    flatpak names no origin (it always names one in what was run).
- **The container shows no Flatpak that is Verified**: its one remote is `--no-gpg-verify`, and
    a signed one needs a key and a signed repository there. Flathub's own line of `flatpak
    remotes` (no options) was read in a container and is the unit tests' data.
- **`scripts/channels_e2e.py` now installs `polkitd`, `pkexec` and `dbus` in its container**,
    adds a user and a polkit rule that lets that user through, and removes the rule after. It
    runs only as root in a disposable container, as its first lines say.
- **`tests/skips/tier1.txt` is another unit's** (U44), so the check on Windows itself is not a
    test that skips elsewhere: it is the second half of a test whose first half (the script's
    rules) runs everywhere.
- **`/var/cache`** is where the copy's folder is made; a `kill -9` of the command would leave
    `/var/cache/appkata-install.*` behind, root's.
- **#223's fact** reads `install.py` and `assets.py` for a verifier's name; a signature check
    added elsewhere would need the fact widened.

## Batch 4

Fable 5.2 at high effort, 2026-11-25. Nothing uncommitted was found in the worktree; nothing was
taken over. No failure of CI's was written here for batch 3's commits.

**Files touched:** `docs/requirements/R4-installing-updating-and-uninstalling.md`,
`docs/requirements/R16-package-channels.md`, `scripts/channels_e2e.py`, `src/appkata/backend.py`,
`src/appkata_core/assets.py`, `src/appkata_core/install.py`, `src/appkata_core/sync.py`,
`tests/test_backend.py`, `tests/test_channels.py`, `tests/test_install_review.py`,
`tests/test_sandbox_ui_surfaces.py`, `tests/skips/windows.txt`, `docs/relay/progress.md`.

**Counts:** fixed 7, no defect 0, remedy changed 0, set aside 0, still left 0, new 5 (one fixed
here, in a commit of its own; four listed only).

### The findings

Each test was shown failing by exporting the commit before the fix (`git archive`) to a scratch
folder, putting the new test files over it, and running the new tests there in a scratch home. The
channels container was run from a scratch script that makes `scripts/test-channels.sh`'s own
`docker run` with a copy of this worktree's `src/` and `scripts/` as the sources and `--memory 3g`,
one container at a time.

- **#304 (Low), fixed, `a732f5c`.** `assets.checksums_for` gives every file of a release that may
    hold the file's SHA-256, its own first (`<file>.sha256`, `<file>.sha256sum`), then each list in
    the release's order; a `.sha512` is none of them. `expected_sha256` reads them until one lists
    the file. `checksum_for` stays, as the first of them: `backend._has_sums` and
    `tests/test_core.py` (not this unit's file) call it. SHA-512 is not computed (the alternative,
    not taken). Tests, in `tests/test_install_review.py`:
    `test_a_file_is_checked_against_the_first_of_its_releases_checksum_files_that_lists_it` (13
    releases, each read from a real server, each also with a file that doesn't match),
    `test_a_release_with_a_sha512_and_sha256sums_is_installed_as_checked` (Linux-only),
    `test_the_checksum_files_of_a_release_are_the_files_own_then_its_lists_and_never_another_digests`.
    Before the fix: 9 of 15 fail; the 6 that pass are the releases whose first-picked file was the
    right one, or that have no SHA-256 at all.
- **#328 (Low), fixed, `e2c61af`.** `expected_sha256` returns a third value, what became of each
    checksum file it tried; `install()` logs it and keeps it in the record (`checksum_reason`),
    and `detail()` gives it as the Unverified chip's tooltip. The install still goes on
    (stopping it is the alternative, not taken). `AppDetail.qml` is not changed: its Unverified
    chip reads `verifyTip` since batch 2. **In the same read, with the 1 MB case the finding
    names:** a list longer than 1 MB was cut wherever the 1 MB fell, and a line cut after
    `App.AppImage` of `App.AppImage.zsync` was read as this file's, with the other file's digest:
    a good download refused as not matching. A cut line is not read.
    Tests: in `tests/test_install_review.py`,
    `test_a_checksum_file_that_gives_no_checksum_is_said_with_the_reason` (13 releases: a 404, a
    server that doesn't answer, a list without the file, of another digest, empty, the file after
    the first 1 MB, the cut line, two files, and five with nothing to say) and
    `test_an_install_that_couldnt_use_its_releases_checksum_file_keeps_why_in_its_record` (the same
    13 through an install; Linux-only); three more records in `tests/test_backend.py`'s
    `test_an_installed_apps_chip_is_what_its_own_install_checked_whatever_the_next_release_publishes`
    and one in `tests/test_sandbox_ui_surfaces.py`'s chip test, read from the real App Detail.
    Before the fix: 24 of the 30 new cases fail; the 6 that pass have nothing to say (five
    installs, and a signed record, whose chip is Verified).
- **#308 (Low), fixed, `5967f9c`.** The owner's decision: https only. Every request of
    `install.py` is made by `_request`, which refuses an address that isn't `https:` before
    anything is asked or touched (`NotFetched`, an install error), and by `_opener`: urllib's
    default opener without its file:, ftp: and data: handlers, with a redirect handler that
    follows a redirect only where the same rule allows it after the address that sent it there.
    Plain `http:` is for this computer itself alone (`localhost`, or a loopback address written
    out), judged on urllib's own reading of the address, and never where a redirect from `https:`
    leads, loopback included. The .exe probe reads nothing of a refused address; a checksum file
    at one "couldn't be read" (#328's reason). Tests, in `tests/test_install_review.py`, with every
    connection and name lookup that leaves this computer refused and counted:
    `test_nothing_is_fetched_from_an_address_that_isnt_https` (32 addresses, through the three
    functions), `test_the_one_host_plain_http_is_used_to_is_this_computer_by_its_own_words` (24
    hosts), `test_a_redirect_is_followed_to_no_address_that_isnt_https` (8),
    `test_a_redirect_on_this_computer_itself_is_followed_as_the_tests_servers_need`,
    `test_a_redirect_from_https_down_to_http_is_not_followed` (4; a stand-in for the https: handler,
    no TLS server), `test_an_https_address_and_a_redirect_from_it_to_another_are_downloaded_from`,
    and for the class
    `test_every_request_install_makes_is_made_by_the_one_function_that_checks_its_address`.
    Before the fix: 66 of 71 fail. The 5 that pass: the redirects to file:, data: and gopher:,
    which urllib refuses by itself, and the two that say what still works.
- **#314 (Low), fixed, `2f5cdd8`.** `http.client.HTTPException` is caught with `OSError`
    (`_BROKEN`): a chunked answer that breaks is retried, from where it stopped where the server can
    resume and from the start where it can't, and after the last retry is an `InstallError` with
    its `.part` kept. **The same class, in the same commit:** the .exe probe and the checksum fetch
    caught an `OSError` alone too; and a Content-Length that is no number was a raw `ValueError`
    from `download()`'s own `int()`, now read as no length. Tests, in
    `tests/test_install_review.py`:
    `test_a_download_whose_answer_breaks_is_retried_then_kept_and_fails_as_an_install_error` (10
    ways a server breaks an answer, once, three times or every time) and
    `test_the_exe_probe_and_the_checksum_fetch_take_a_broken_answer_as_no_answer` (4). Before the
    fix: 13 of 14 fail (`IncompleteRead`, `BadStatusLine`, `LineTooLong`, `ValueError`, raw); the
    one that passes is a chunked answer that comes whole.
- **#731 (Low), fixed, `14ea077`.** Of the remedy's two ways, the suffix: `_not_anothers` gives a
    version the place its name gives it, or that name with `_2`, `_3`... (before an AppImage's
    extension) when that place is another of the app's versions', compared without case on
    Windows. The one-to-one escape would rename every version with a `_` in it and can't be
    one-to-one on Windows. **AppImages had the same fault** (one file name for every version:
    `Tool-x86_64-1.0_beta.AppImage` twice) and are fixed by the same lines. Tests, in
    `tests/test_install_review.py`:
    `test_versions_whose_names_in_a_path_are_one_each_keep_a_place_of_their_own` (12 sets of
    versions × archive and AppImage: each kept, run when switched to, and in its place when
    installed again; Linux-only) and
    `test_the_place_a_version_gets_when_its_names_is_another_versions` (as Linux and as Windows).
    Before the fix: 21 of 26 fail; the 5 that pass are AppImages whose two file names differ
    anyway (`current` and `_current`).
- **#740 (Med), fixed, `98a27fb` and `ca93a05`.** Where `track_channel_installs` sees the copy
    changed elsewhere it takes the verdict again; for a Flatpak, of the remote the copy now comes
    from, so the record's `remote` follows the copy (more than the remedy's one line: a copy from
    another remote was otherwise judged by the old remote's key). Only where the copy changed.
    Tests, in `tests/test_channels.py` (see the doubts for why not `tests/test_sync.py`):
    `test_a_package_changed_outside_appkata_is_recorded_as_what_checked_the_copy_there_now` (6) and
    `test_a_flatpak_changed_outside_appkata_is_recorded_as_what_checked_the_copy_there_now` (7).
    Before the fix: 9 of 13 fail; the 4 that pass are the copies whose verdict is the same after.
    **Container, the first run of this finding (it was filed by reading):**
    `scripts/channels_e2e.py` replaces the distribution's `hello`, installed through AppKata and
    Verified, with a hand-built 99.0-1 by `dpkg -i`, and syncs. Passes in the ubuntu, ubuntu-pk and
    mint runs; on the code before (`14ea077`) the ubuntu run fails with the record still
    `verified: signed, signer: Ubuntu` at 99.0-1.
- **#742 (Low), fixed, `622695a` and `d54e75a`.** `Refused` goes through `_apply` and
    `install()`'s package branch as `NeedsConfirmation` does. One caller knew only `InstallError`,
    Remove Source with its app (`backend.removeSource`, no plan dialog there): it says a refusal as
    the error line it was. Tests: in `tests/test_channels.py`,
    `test_a_plan_appkata_refuses_reaches_the_caller_as_a_refusal_and_runs_nothing` (install, update,
    uninstall × asked first and after an OK) and
    `test_a_package_error_that_is_no_refusal_is_an_install_error`; in
    `tests/test_install_review.py`,
    `test_a_releases_package_whose_plan_is_refused_is_refused_as_such_and_nothing_of_it_stays`
    (deb, rpm; Linux-only); in `tests/test_backend.py`, through the real Backend to its
    `planConfirm` signal, `test_a_refused_plan_is_shown_in_the_plan_dialog_as_refused` (3 roads) and
    `test_removing_a_source_with_its_app_says_a_refused_plan_as_an_error_and_removes_nothing`.
    Before the fix: 13 of 15 fail; the two that pass are what doesn't change. The release-package
    road is shown in two halves (install() raises `Refused`; the backend's branch for it is the
    one line beside the others): no test drives a release's `.deb` through the whole Backend.
    **Container:** `scripts/channels_e2e.py`'s own refusal step (a package a desktop metapackage
    depends on, removed with the real apt) expected an `InstallError`; it holds the refusal to
    `pkgbackend.Refused` now. Passes in the ubuntu, ubuntu-pk and mint runs.
- `b7297fb`: the new finding 1 below, fixed in a commit of its own.

### Needs your eye

- `a732f5c` (#304): **R4.4's new paragraph** ("The checksum is a SHA-256: …"): which files are
    read, in which order, and that a `.sha512` or `SHA512SUMS` is not. A release whose only checksum
    is a `.sha512` now forecasts **No checksum published** (it said Checksum published).
- `e2c61af` (#328): **R4.4's paragraph** ("When a release has checksum files and none of them
    gives …") and the Unverified chip's tooltip: "Its release has a checksum file, but this download
    was checked against none: <reason>". The reasons, joined with "; " when there are several:
    "couldn't read SHA256SUMS (HTTP 404)", "couldn't read SHA256SUMS", "SHA256SUMS doesn't list
    this file", "SHA256SUMS is longer than 1 MB, and the part AppKata reads doesn't list this file",
    and since #308 "couldn't read SHA256SUMS: it isn't at an https: address".
- `5967f9c` (#308): **R4.4's paragraph** ("Downloads are made over `https:` only. …") and the two
    errors: "AppKata downloads over https: only, and this isn't an https: address (<address>)" and
    "the download was sent on to an address that isn't https: (<address>), where AppKata doesn't
    follow it". **What the decision means for a forge on plain http:** a Source at
    `http://git.lan/…` can still be added and synced, and its files can't be installed.
    `localhost` counts as this computer, beside the loopback addresses.
- `2f5cdd8` (#314): "download failed: the connection closed before the whole file had come; press
    Update again to resume" and "download failed: the server's answer couldn't be read
    (BadStatusLine); …", where the exception's own text was.
- `14ea077` (#731): **R4.3.1's sentence** ("Two versions whose names come out the same …"): the
    later one is in `1.0_beta_2/` or `Tool-1.0_beta_2.AppImage`.
- `98a27fb` (#740): **R16.3.6's last sentences**: asked again when a sync finds the copy changed
    outside AppKata, of the remote a Flatpak then comes from; a copy that hasn't changed keeps its
    chip. A Flatpak's label follows its new remote.
- `622695a` (#742): **R16.3.5's sentence** on what the refusal's dialog shows. The user now gets
    the dialog "Can't install <app>" with "It would remove ubuntu-desktop, which this computer
    needs." and Close, where an error toast was.
- `b7297fb` (new): a version installed again under another file name or folder no longer leaves
    its earlier copy in the Versions list as a kept version.

### Needs a run

- **The Windows VM** (the coordinator's): `scripts/test-windows-vm.sh --tests`. Of this batch, on
    real Windows for the first time: #304's and #328's tables through `expected_sha256` (the
    "server that doesn't answer" is `127.0.0.1:1`, which Windows refuses after about two seconds a
    request), #308's tests (file: addresses with a drive letter; the fixture that replaces
    `socket.socket.connect` and `socket.getaddrinfo`), #314's server, `_not_anothers`, and
    `tests/test_channels.py`'s new tests, which stub every tool. **The one to watch:**
    `test_a_download_whose_answer_breaks_is_retried_then_kept_and_fails_as_an_install_error` holds
    the kept `.part` to exactly what `download()` had written (131,072 bytes) and the resuming
    request to `bytes=131072-`. On Linux the server's `shutdown` sends what it wrote before it
    closes; if Windows drops any of it, those two lines are too strict, not the fix. The five new
    Linux-only tests are in `tests/skips/windows.txt`.
- **The desktop VMs** take `tests/test_channels.py` (`scripts/sandbox/vm-desktop.sh`): its new tests
    run there with every tool stubbed. Not run here.
- **CI's tour job**: no screen changes (no demo record has a `checksum_reason`).
- **dnf**: nothing runs it (R1.1). #740's and #742's `.rpm` halves rest on stand-ins.
- No Flatpak was changed outside AppKata in a container: the container's one remote is
  `--no-gpg-verify`, so the verdict would be the same before and after. The Flatpak half of #740
  rests on `flatpak remotes`' and `flatpak list`'s recorded words.
- Run here, in a scratch home, all passing: the touched test files whole
    (`tests/test_install_review.py`, `tests/test_backend.py`, `tests/test_channels.py`,
    `tests/test_sandbox_ui_surfaces.py`), `tests/test_skip_lists.py`, the document checks, and
    beside them, from a copy of `b7297fb`, `tests/test_sandbox.py`,
    `tests/test_sandbox_transitions.py`, `tests/test_sandbox_backend.py`,
    `tests/test_sandbox_lifecycle.py`, `tests/test_sandbox_adversarial.py`,
    `tests/test_sandbox_docs_current.py`, `tests/test_selfinstall.py`, `tests/test_core.py`,
    `tests/test_channel_ui.py`, `tests/test_dialog_contract.py`, `tests/test_demo_promises.py`,
    `tests/test_qml_slots.py`, `tests/test_launch.py`, `tests/test_appkind.py`,
    `tests/test_windows.py`, `tests/test_tour_rules.py`, `tests/test_forges.py`,
    `tests/test_docs_facts.py` (with `tests/test_backend.py`, `tests/test_channels.py` and
    `tests/test_sandbox_ui_surfaces.py` again: 2529 passed, 6 skipped). The channels container: ubuntu, ubuntu-pk
    and mint, after the last change to anything they run. Tier 1 whole is CI's.

### Guard

Nothing: every file changed is in U04's files.

### New

1. **Fixed, `b7297fb`. A version installed again at another place stays among the kept versions.**
    `src/appkata_core/install.py`, `install()`'s versioned branch (`retired = _retain(…)`). Case,
    run: an AppImage app at 2.0 from `Tool-2.0-x86_64.AppImage`, installed again at 2.0 from
    `Tool-2.0-amd64.AppImage` (the release renamed its file): current 2.0, kept versions `['2.0']`,
    both files there. That one was there before this batch; #731's fix adds a second way (a
    version that had `_2` takes the plain name once the other version is removed). Low. Test:
    `tests/test_install_review.py::test_a_version_installed_again_at_another_place_is_not_also_kept_as_a_previous_one`
    (3 cases, all fail before; Linux-only, its skip line in the same commit). A file AppKata
    adopted and didn't place is never taken out this way.
2. **Not fixed. Remove Source, with its app, does nothing when the package's removal takes another
    package with it.** `src/appkata/backend.py`, `removeSource` (`install.uninstall(self.db, url)`
    under `except install.InstallError`). Case, run in a scratch copy with the real Backend and a
    package manager whose plan removes `demo-plugins` too: `removeSource(url, True)` raises
    `NeedsConfirmation` out of the slot; no toast, no dialog, and the Source stays. Uninstall from
    App Detail asks (R16.4.3); this road has no dialog to ask with. Low. Not small: it needs the
    confirmation, then the Source's removal after it.
3. **Not fixed. The dialog of a refused update is titled "Can't install <app>".**
    `src/appkata/qml/ConfirmDialog.qml`, the `plan:` title (`args.action === "uninstall" ?
    "uninstall " : "install "`): an update's refusal has the install's words. By reading; reachable
    only since #742. Low. Not this unit's file.
4. **Not fixed. A file its release names as a path is never found in a checksum list.**
    `src/appkata_core/install.py`, `_sha256_in` (a line's base name compared with the release's
    whole name): batch 1's doubt, still so. Such a file (`sub/x.tar.gz`, installed as `x.tar.gz`
    since #306) installs Unverified, and since #328 its chip says "SHA256SUMS doesn't list this
    file". By reading. Low.
5. **Not fixed. A checksum list that holds one digest and no name is taken as every file's.**
    `src/appkata_core/install.py`, `_sha256_in`'s last lines (the file's one value "when it holds
    nothing else"), which serve `<file>.sha256` and are applied to a list (`SHA256SUMS`) too: a
    release with two files and a `SHA256SUMS` of one bare digest refuses the other file as not
    matching. By reading. Low.

### The real home

Every run's `diff` of `/home/dev/bin`, `/home/dev/.local/share/appkata` and
`/home/dev/.local/share/applications` before and after was empty.

### Doubts

- **#740's test is in `tests/test_channels.py`**, not in the `tests/test_sync.py` its record names:
    that file doesn't exist, a new test file needs its line in `scripts/areas.py` (not this unit's
    file), and the fixtures that say what apt and flatpak answer are in `tests/test_channels.py`,
    beside `test_tracking`. `tests/test_sync.py` can leave U04's files.
- **#740, the record's `remote` follows the copy.** One line more than the remedy. The
    `installation` (user or system) is left as the record has it: `flatpak.installed()` lists a
    user copy before a system one of the same id, so which copy a record follows there is an older
    question than this finding.
- **#308 and a forge on plain http:.** Said under needs your eye: it is what the decision says,
    and it is the one place a user of a LAN forge meets it. Nothing in Sources says so beforehand.
- **#308, what "loopback" is.** `localhost` and an address `ipaddress` calls loopback, as written:
    `127.1`, `0x7f.0.0.1` and `localhost.` are refused, though a resolver would take them there.
- **#308 and a proxy.** The opener keeps urllib's `ProxyHandler` (the environment's proxies), as
    before, and is now made for each request, where urllib made its own once a process.
- **#328 keeps the reason whatever the chip.** A file with a valid Authenticode signature and an
    unreadable checksum file is Verified, with the reason in its record and not in its tooltip.
- **#328, "longer than 1 MB".** The limit stays; a longer list is read to 1 MB, and says so only
    when the file isn't in that part.
- **#314 loses the part of a read that broke.** `download()` reads 64 KiB at a time, and what
    http.client had of a read when the chunk broke is in the exception, not in the `.part`. The
    retry asks from what was written, so nothing is wrong, only up to 64 KiB asked for twice.
- **#731, the suffix can be another version's name too** (`1.0_beta_2` is a version's name): the
    next free number is taken, and the tests have both orders.
- **#731 and a sandboxed AppImage's unpacked copy** (`sandbox.extracted_dir`, by the version's
    name): two versions with one name share it. Its stamp is of the AppImage's own file, so the
    launcher unpacks again when the other one is current; nothing wrong was found, by reading.
- **#742's dialog for a release's package** has the action `install-release`, and for an update
    the title's words (new finding 3). Neither is new; both are reachable now.
- **Fixes that went beyond their finding's words**, each in its finding's own commit and said
    there: the cut line at 1 MB (#328), the probe's and the checksum fetch's `HTTPException` and
    the Content-Length that is no number (#314), AppImages (#731). If any should be a finding of
    its own, it has a test to point at.
- **The container ran from a copy** of this worktree's `src/` and `scripts/` (tracked files, as
    they were then), not from the worktree itself, so work on the next finding couldn't change
    what a running container read. The wider test run was from a `git archive` of `b7297fb` for
    the same reason; the touched files were always run whole from the worktree.
- **`tests/skips/windows.txt`'s order**: its lines are in ASCII order but for batch 3's two
    `test_a_releases_package_…` lines; this batch's five are placed by ASCII order. Nothing checks
    the order.
