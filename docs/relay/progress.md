# Relay progress: CR1's unit U05, the sandbox: what may be granted, and file arguments

5 batches cover the unit's 17 findings, taken from `docs/remediation/CR1-schedule.json` at
`upstream/master` 6c3d380: batch 1 the system places refused to every grant and to a tool's working
directory; batch 2 the file-argument helper; batch 3 where a grant's path really leads; batch 4 the
places of the home the never-shared and secret lists miss; batch 5 what an uninstall leaves.
One agent at a time; the coordinator checks each batch before the next starts, and pushes.
This branch is stacked on U04's (`cr1-u04-downloads-checksums`): it started at U04's relay commit
b912a42, and each batch first merges U04's pushed tip in.

## Batch 1

The system places refused to every grant and to a tool's working directory: #380, #381, #189.
Fable 5.2, high effort. Nothing was taken over: the worktree was clean at the start.

**The merge of U04's tip**: up to date when the batch started (`origin/cr1-u04-downloads-checksums`
was b912a42, this branch's own start, and still was when #189 was committed); no merge commit.
U04's batch 1 was pushed after that (4ce5d38): it is not in this batch, touches none of this
batch's files, and merges with conflicts in `docs/relay/` alone (`git merge-tree`), which the
brief's `restore` line settles. Batch 2 takes it in.

**Counts**: fixed 3, no defect 0, remedy changed 0, set aside 0, still left 0, new 0.

**Files touched**: `src/appkata_core/sandbox.py`, `tests/test_sandbox.py`,
`tests/test_sandbox_adversarial.py`, `tests/test_sandbox_one_fact.py`, `tests/test_sandbox_run.py`,
`tests/data/launchers/cli-tool.sh` (written again by `UPDATE_GOLDEN=1`, the other goldens unchanged),
`docs/requirements/R17-app-sandboxing/R17.3-templates.md`, `docs/requirements-trace.md`.

### The findings

**#380, fixed, c1f4a8c.** `sandbox.SYSTEM_PLACES` is the owner's list (/proc, /sys, /dev, /run,
/var/run, /tmp, /var/tmp, /etc, /usr, /boot); `system_folder()` refuses each, what is inside it and
what is above it, and `protected_folder()` asks it, so the chips, the launcher's "# Refused folder
grant" line, `strip_protected()` and the Sandbox dialog's toast all say "the system's own /proc".
The launcher's working-directory block bakes the same list (the cli-tool golden), so the tool's rule
and the grant check still agree. Tests:
- tier 1, `tests/test_sandbox.py`: `test_a_system_place_is_never_granted_nor_what_is_inside_or_above_it`
    (48 cases: each place, inside, above, each way of writing it, and /media, /mnt, /run/media/<user>
    and the home's own folders still shared), `test_a_review_cannot_grant_a_system_place_and_the_user_cannot_pick_one`
    (the finding's own road: a review's line through `config_from_review` and `choose`, the chips,
    the launcher, and the picker's `strip_protected`), `test_a_folder_of_the_home_is_the_homes_wherever_the_home_is`;
    `tests/test_sandbox_adversarial.py`: `test_a_system_place_is_refused_and_never_bound_however_it_is_written`
    (35 paths). Shown failing: the base tree (`git archive 99bcc6f`) with the new test files over it,
    in the scratch home: 32 of the 48 cases, both other tests and 31 of the 35 adversarial ones
    failed (the rest are the shared places, and /run, /var/run, /run/user and /proc/self/root, which
    other rules refused already).
- tier 2: the run is part of `tests/test_sandbox_run.py::test_a_grant_of_the_home_folder_or_the_keys_does_not_open_them`
    (see **guard**): a review's `/proc:ro, /dev/shm, <a folder of /tmp>, /var/tmp, /etc:ro, /sys:ro,
    ~/Notes`. Shown failing on the base tree in both containers (Mint 22.3: bwrap 0.9.0; LMDE 7:
    bwrap 0.12.0): the app's `/proc/1` was the container's `su`, 16 processes in sight, the host's
    /dev/shm and the folder of /tmp visible. With the fix: `pid1=bwrap`, neither visible, nothing
    written to /var/tmp, ~/Notes still the app's. The whole launcher tier passed in the Mint 22.3
    container after it (147 passed, 5 skipped), and the touched cases in LMDE 7 (36 passed).

**#381, fixed, f880840.** The list reached the tool's rule with #380's commit; this one is what the
tool says, R17.3.3 and the tests. Tests:
- tier 1, `tests/test_sandbox.py`: `test_a_tool_run_in_a_system_place_is_not_given_it_and_says_why`
    (10 places, the launcher itself run from each with a stand-in bwrap),
    `test_a_tool_run_where_a_disk_is_mounted_or_in_its_users_folders_is_still_given_the_folder`;
    `tests/test_sandbox_one_fact.py`'s agreement test now asks the system places and the mount
    roots. Shown failing: on the base tree all 10 failed because the tool was given the folder
    (`--bind`), and the agreement test failed; on #380's commit (c1f4a8c) all 10 failed on the
    line said (the old "can't see … (your home folder …)").
- tier 2: parts of `test_cli_tool_sees_and_writes_the_project_folder_it_is_run_in` (a real bwrap,
    run from a folder of /tmp, /var/tmp, /dev/shm, /proc, /sys, /etc, /usr/share, /var: private
    home, the sandbox's own /proc, nothing of another program's seen, nothing written outside) and
    of `test_a_cli_tool_run_from_a_refused_folder_is_still_given_its_file_arguments` (a file named
    from a folder of /tmp, by a relative and a full path: both handed over through the document
    portal). Shown failing in both containers: on the base tree the tool saw the other program's
    file and got `draft.txt` as typed, in the shared folder; on c1f4a8c both failed on the line
    said. With the fix: Mint 22.3 whole launcher tier 147 passed, 5 skipped; LMDE 7 touched cases
    36 passed.

**#189, fixed, 5d06a08.** R17.3.3 loses its parenthesis and keeps "one of the never-shared folders
of R17.3.1". No test (nothing observable changes); the document checks pass, and the sentence's
trace row still matches.

### Needs your eye

- c1f4a8c (#380): R17.3.1 gains the sentence "The **system's own places** are never shared either
    …". Beside the owner's list it says three things the decision didn't: a path is judged as
    written and by where it leads (so `/proc/self/cwd` is refused, wherever it leads); **a folder
    of the home is judged as the home's, wherever the home is** (without it no test could grant
    anything: every test's home is under /tmp; a home that is `/` makes nothing a folder of the
    home); and `/var/run/media` is excepted beside `/run/media`. The words a user sees: "the
    system's own /tmp", "a folder above the system's own /var/run". R17.3.1's remark that a folder
    beside a dbus-run-session bus under /tmp is shared is corrected.
- f880840 (#381): the launcher's new line on stderr, "<Tool> runs sandboxed and isn't given <dir>
    to work in: it is one of the system's own folders (/proc, /sys, /dev, /run, /var/run, /tmp,
    /var/tmp, /etc, /usr, /boot), or in or above one, and those are never shared.", followed by the
    line it already had ("Run it from a project folder …"). R17.3.3 gains the sentence "A **system
    place** of R17.3.1 is one of those never-shared folders: …".
- 5d06a08 (#189): R17.3.3's second list is gone.
- **A file argument under /tmp** (the coordinator's answer: the brief's fallback). Batch 1 changed
    nothing in the file-argument helper, which is given no never-shared list today: a file under
    /tmp or /var/tmp named on the command line is still handed over (shown in tier 2 by #381's
    test, and said in R17.3.3 and both commits). **For batch 2 (#651)**: give the helper
    `_protected_roots()` and the bus's files, as they stood before this batch, never
    `SYSTEM_PLACES` or `protected_folder()` whole, or a file under /tmp stops being handed over.

### Needs a run

The VMs (the coordinator's): the same cases under Ubuntu's kernel and AppArmor profile, and with
bwrap 0.11.1:

```
scripts/test-sandbox.sh launcher-vm -k "home_folder_or_the_keys or sees_and_writes_the_project or refused_folder_is_still_given or agree_on_every_folder or session_bus_socket"
scripts/test-sandbox.sh launcher-vm26 -k "home_folder_or_the_keys or sees_and_writes_the_project or refused_folder_is_still_given or agree_on_every_folder or session_bus_socket"
```

### Guard

The guard passes on every commit, with no file outside U05's plan (but `docs/relay/`).
**`tests/skips/tier1.txt` is U44's**, and it names every test and case of `tests/test_sandbox_run.py`
(tier 1 has no bwrap): a new run test, or a new case of the refused-directory list near line 154
that #381's record names, needs a line there, which the guard would stop. So the three run checks
are parts of run tests that file already names, each in a helper of its own with the finding's
comment, and no line was added. If the schedule gives U05 that file, they can become tests and
cases of their own.

### New

None.

### The real home

Every run's `diff` of `/home/dev/bin`, `~/.local/share/appkata` and `~/.local/share/applications`
before and after: empty.

### Doubts for the coordinator

1. The rule "a folder of the home is the home's" is mine, not the decision's (see **Needs your
    eye**). The other reading, a home under /tmp has nothing to grant, fails nearly every sandbox
    test.
2. `/run` and `/var/run` themselves keep the reason they had, "a folder above the session's runtime
    folder": the home's and the runtime folder's reasons are asked first.
3. What the list leaves shareable outside the home: `/opt`, `/srv`, `/var/lib`, `/snap`, other
    users' homes, and `/run/media` whole, not only `/run/media/<user>`. `/var` is refused, as a
    folder above two of the places.
4. Tests that granted, or ran a tool from, a folder of their own under /tmp outside the test's home
    now use one inside it (the bus-socket tests of `tests/test_sandbox.py` and
    `tests/test_sandbox_run.py`, `_launched()`'s new `home=`, the links of
    `tests/test_sandbox_one_fact.py`'s corpus). A later batch's test that needs a shareable folder
    puts it in the test's home.
5. `docs/architecture/A1-app-sandboxing/A1.2-approach.md` (lines 9-11 and 131-136) sums up the
    never-shared set without the system places and points at `_protected_roots()` alone. It is not
    in U05's files; not changed.
6. The cli-tool golden holds the places as they resolve on the machine that writes it (`/var/run`
    is a link to `/run` on every tier's system, so the list is the ten names); a machine whose
    `/tmp` or `/usr` is a link elsewhere would write a longer list.
7. The whole tier 1 suite was run once in its container at 5d06a08, under a 3 GB cap: 4889 passed,
    138 skipped, none failed. The touched test files were run whole in the scratch home after each
    fix (2592 passed, 45 skipped at #381's) and in the tier 1 container (2482 passed, 122 skipped).

## Batch 2

The file-argument helper: what it hands over, and what it never does: #651, #379, #390, #666.
Fable 5.2, high effort. Nothing was taken over: the worktree was clean at the start.

**The merge of U04's tip**: b68d18c, "Merge U04's branch in at 4ce5d38". One conflict outside
`docs/relay/`: `docs/remediation/CR1-schedule.json`, where both sides added records at the end of
the findings (U04's #729, #730, #731; this branch's #734). Both kept, in the issues' order; the
newer `triage.py check --offline` says "49 units holding 590 findings, 0 set aside: no problems".
`docs/relay/` stayed this unit's (the brief's `restore` line). U04's tip had not moved again when
the batch ended (4ce5d38).

**Counts**: fixed 4, no defect 0, remedy changed 0, set aside 0, still left 0, new 1 (not fixed).

**Files touched**: `src/appkata_core/sandbox.py`, `tests/test_sandbox.py`,
`tests/test_sandbox_run.py`, `tests/test_sandbox_adversarial.py`,
`tests/test_sandbox_user_shaped.py`, the five goldens under `tests/data/launchers/` (written again
by `UPDATE_GOLDEN=1`, in #651's commit alone),
`docs/requirements/R17-app-sandboxing/R17.6-app-identity.md`, `docs/requirements-trace.md`.

### The findings

**#651, fixed, 8bb96cc.** The launcher gives the helper the never-shared list (the folders of
`_protected_roots()` and the private homes as they are written, `$bussocks`; the runtime folder is
the helper's second argument, the home its own to find; never `SYSTEM_PLACES`, as settled). A file
or folder that is one, in one or above one is not handed over, judged by where its path leads and
by each link on the way (`follow()`); the helper's answer says why in a line with "!" first, which
the launcher prints after the app's name on stderr. Tests:
- tier 1, `tests/test_sandbox.py`: `test_a_never_shared_folder_is_handed_over_by_no_argument_and_the_helper_says_why`
    (the helper's own text against a stand-in portal: `.`, the home, `/`, `..`, `~/.ssh`, a key by
    six paths and through three kinds of link, `~/.config`, AppKata's own, the runtime folder; and
    what is still handed over, a file under /tmp among it),
    `test_the_session_bus_socket_is_handed_over_by_no_argument_nor_a_folder_above_it`,
    `test_the_helper_hands_over_nothing_a_grant_could_not_share_but_under_the_systems_places` (the
    class: every root of the list, what is in it and above it, held to `protected_folder()`),
    `test_the_launcher_says_why_an_argument_in_a_never_shared_folder_is_not_handed_over` (a cli-tool
    and a standard launcher run whole, a stand-in bwrap and portal: the lines on stderr).
    Shown failing: the tree of b68d18c (`git archive`) with the new test files over it, in the
    scratch home: all four failed, with `test_launcher_hands_over_file_arguments_only_for_standard_apps`
    (the launcher's words). The launcher-level one shows the fault itself (the app's first argument
    was `…/run/doc/DOC/home`); the three helper-level ones fail there on the helper's argument
    layout, which is new, so they show the list is asked for, not the export.
- tier 2: `_a_never_shared_argument_is_handed_over_to_no_app`, a part of
    `test_a_cli_tool_run_from_a_refused_folder_is_still_given_its_file_arguments`. Shown failing on
    the b68d18c tree in both containers (Mint 22.3: bwrap 0.9.0, portal 1.20.0; LMDE 7: bwrap
    0.12.0, portal 1.20.3): the real portal exported the home, the tool's first argument was
    `…/run/doc/<id>/home` (what the issue could not show). With the fix: nothing new under
    `$XDG_RUNTIME_DIR/doc`, each argument as typed, the four lines on stderr.

**#379, fixed, 18d532c.** `follow()` says where each link on the way is; the first that lies in a
visible folder ends the way unless the whole leads back into one. The argument becomes its own
path in the granted folder; nothing is exported. The second part is #651's commit. Tests:
- tier 1: `test_a_link_in_a_granted_folder_is_never_followed_out_of_it_to_hand_a_file_over` (a link
    to a file and to a folder, absolute and relative, a link mid-path, a link to a link, the
    user's own link to the planted one, a path, a `file://` URI and an option's value, a tool's
    shared folder, a folder granted through a link; and R3-17's direction, a link between two
    granted folders, and the same link with no grant, all as before). Shown failing on the
    8bb96cc tree: `…/run/doc/DOC/report.md` handed, `Add` and `GrantPermissions … ['read', 'write']`
    on the target.
- tier 2: `_a_link_the_app_plants_in_its_folder_hands_it_nothing`, a part of
    `test_a_file_argument_is_handed_over_to_a_standard_app`: the app itself plants the links in
    its read-write ~/Projects, then the user opens them. Shown failing on the 8bb96cc tree in both
    containers: the app read the target ("TAXES") three ways and listed the linked folder. With
    the fix: the arguments are their own paths, nothing new under `doc`, the target unread and
    unchanged, and the desktop link to a file in the grant still opens.

**#390, fixed, cc79896.** A bare word (no "/", neither "." nor "~" first) that names a folder
passes as typed, also as an option's value and in a granted folder; one that names a file is
handed over. In its shared folder a tool's relative path stays as typed only while it stays in
the folder. Tests:
- tier 1: `test_a_bare_word_is_a_file_argument_when_it_names_a_file_and_never_a_folder`,
    `test_a_tools_relative_path_that_leaves_its_shared_folder_is_handed_over`. Shown failing on
    the 18d532c tree: `…/doc/DOC/build` where `build` was typed; `../notes.txt` passed unchanged.
- tier 2: eight new cases in `tests/test_sandbox_user_shaped.py`'s corpus (three of them a
    command-line tool's). Shown failing on the 18d532c tree in both containers: "a bare word that
    names a folder (the program's own word)", "an option whose value is such a word" and "a
    tool's ../ out of its shared folder" joined the listed "a file still to be made".

**#666, fixed, 4608e05.** The helper exports what the argument leads to, opened by that path and
named by it. Tests:
- tier 1: `test_a_link_to_a_file_outside_every_grant_is_handed_over_under_the_files_own_name`.
    Shown failing on the cc79896 tree (`…/doc/DOC/notes.txt`).
- tier 2: `_a_link_to_a_file_outside_every_grant_reaches_the_app_as_a_path_that_opens`, a part of
    `test_a_file_argument_is_handed_over_to_a_standard_app` (the finding's own run). Shown failing
    on the cc79896 tree in both containers (`…/doc/<id>/notes.txt`, which isn't there). With the
    fix the app reads the file three ways and its write reaches the real file.

After the last commit (4608e05): the whole launcher tier in the Mint 22.3 container, 147 passed, 5
skipped, and in the LMDE 7 container, 147 passed, 5 skipped; the whole tier 1 suite in its
container under a 3 GB cap, 5045 passed, 138 skipped, none failed. After each fix: the touched
test files and the document checks whole in the scratch home (844 passed, 47 skipped at #666's),
the touched files in the tier 1 container (730 passed, 124 skipped), and the hand-over tests and
the argument corpus in both launcher containers (9 passed).

### Needs your eye

- 8bb96cc (#651): the line a user sees, once for each refused argument:
    "<App> runs sandboxed and isn't handed <path as typed>: <why>." with <why> one of "your whole
    home folder is never shared with a sandboxed app", "it holds your whole home folder, which is
    never shared with a sandboxed app", "<folder> is never shared with a sandboxed app", "it holds
    <folder>, which is never shared with a sandboxed app" (<folder> as R17.3.1's list writes it,
    the first that matches). The tool's line for a refused directory now ends "… is handed over
    either way, unless it is in a never-shared folder of your home (your keys, your startup files,
    AppKata's own)."; the line for a bus address AppKata can't read ends "… all the same, unless
    it is in a never-shared folder of your home." R17.6.2 gains three sentences ("The never-shared
    folders of R17.3.1 win over an argument …", "The argument then passes unchanged …", "The
    system's own places of R17.3.1 are a grant's rule and no argument's …") and narrows "handed
    over like any other". Beside the decision it says: judged "by each link on the way there"
    (`~/.ssh/config`, a link to a file kept elsewhere, is refused; so is `~/.bashrc` kept in a
    dotfiles folder), and the session bus's socket file is in the list.
- 18d532c (#379): R17.6.2 gains "A link in a granted folder is never followed out of it …". The
    rule holds for every granted folder, read-only ones too (the helper is not told the modes),
    so the user's own link in a granted folder to a file outside every grant no longer opens by
    being named: the app is handed the link's path, which dangles inside.
- cc79896 (#390): R17.6.2 gains "A bare word — an argument with no `/` in it that starts with
    neither `.` nor `~` — …" and "In its shared directory a command-line tool's relative path
    that leads out of it …". Mine, beside the decision: what a bare word is (the issue's own
    remedy words: so `.`, `..` and `.git` are paths), that an option's value is read the same
    way (`--mode=build`), that in a granted folder the word is left as typed too (it was made
    the folder's path), and that nothing is said on stderr when a word is left alone.
- 4608e05 (#666): no requirement changes; the handed path's name is now the file's own.

### Needs a run

The VMs (the coordinator's): the same cases under Ubuntu's kernel, AppArmor profile and portals
(1.18 on 24.04, 1.21 on 26.04): #666's test rests on the portal naming a document after the file,
and #651's on what it exports:

```
scripts/test-sandbox.sh launcher-vm -k "refused_folder_is_still_given or file_argument_is_handed_over or arguments_shaped or never_handed_over"
scripts/test-sandbox.sh launcher-vm26 -k "refused_folder_is_still_given or file_argument_is_handed_over or arguments_shaped or never_handed_over"
```

### Guard

The guard (agents#21's `triage.py guard U05 --on U04 --base origin/cr1-u04-downloads-checksums`)
passes on every commit, with no file outside U05's plan (but `docs/relay/`). The tier 2 checks are
helpers inside run tests `tests/skips/tier1.txt` already names, as settled. `tests/test_sandbox.py`
and `tests/test_sandbox_adversarial.py` are not in #666's or #390's own records but are U05's.

### New

1. **A link the app plants in a folder it was handed through the document portal is followed at a
    later launch, and its target handed over** (#379's road, by a folder argument instead of a
    grant). `src/appkata_core/sandbox.py`, `FORWARD_HELPER`'s `hand()` and `inside()`: the
    folders counted as the app's are the launcher's `visible` list (the grants, a tool's shared
    directory) alone; a folder exported earlier with `AddFull` is not among them. The case, run
    at 4608e05 in the Mint 22.3 container with the real document portal (a scratch test, not in
    the repository): an online-app "editor" with no folder grant is started as `editor ~/proj`
    and, in the folder it is handed (`…/doc/<id>/proj`), moves README.md away and makes a link
    README.md to ~/Documents/taxes.txt (the link is made on the host: the portal's file system
    lets an app make links in a folder's document). Started again as `editor ~/proj/README.md`,
    it is handed `…/doc/<id>/taxes.txt`, reads it and appends to it (the real file then held
    "TAXES", "EDITED").
    Severity I would give: High, as #379 (any file of the user's the never-shared list doesn't
    hold, read-write; it needs the user to have handed the app a folder once, which `editor .`
    does, and to open a file of that folder by name later). Not fixed here: not small. The fix I
    would make: before an export the helper asks the portal's `List(<app identity>)` (it answers
    document id → host path, for a folder too: seen with the real portal), and counts each folder
    in it that is no never-shared one as visible at `$XDG_RUNTIME_DIR/doc/<id>/<name>`; then
    #379's rule covers it, and a file in a folder handed over before becomes its path in that
    folder's document instead of a second export. It touches the same portal records as #400
    (batch 5). A file handed over can't be swapped for a link that way: the portal refuses a
    link in a file's document ("Operation not permitted"), seen in the same probe.

### The real home

Every run's `diff` of `/home/dev/bin`, `~/.local/share/appkata` and `~/.local/share/applications`
before and after: empty.

### Doubts for the coordinator

1. **A folder argument that is one of the system's own places is still exported whole**
    (`tool /tmp`, `/etc`, `/var`, `/proc`): the helper's list has no `SYSTEM_PLACES`, as settled,
    so that a file under /tmp is handed over. A rule between the two (a folder that is a system
    place or above one is refused, a file inside is not) would close it; not taken, it is a
    choice. `/run` and `/` are refused through the runtime folder and the home.
2. Where the session bus's address names a file the launcher can't read (`$busok` 0), arguments
    are handed over as before, folders too: the helper is given the socket files that could be
    read, and nothing for the others. Through the document portal's file system a socket can't
    be connected to, so I left it.
3. An argument under `$XDG_RUNTIME_DIR` is refused now, the portal's own `…/doc/<id>/…` paths
    included (the runtime folder is in the list); such a path was exported again before.
4. `tool ..` in its shared folder now hands the folder above over whole (R17.6.2's rule for a
    path the sandbox can't see), unless that folder is a never-shared one.
5. R17.4's "What its file-argument helper answers (R17.6.2) it reads as arguments, one a line, and
    never evaluates" doesn't say the lines with "!" first, which it prints (as data, `%s`) and
    takes for no argument. R17.4 is U05's but in none of this batch's records; not changed.
6. A launcher written before 8bb96cc calls the helper without the list; the new helper then
    fails and that launcher passes its arguments unchanged until the startup pass writes it
    again (no logic for an earlier version's launchers, as the brief says).
7. `tests/test_sandbox_user_shaped.py`'s stand-in for "no hand-over at all" printed its answer
    in the form the launcher stopped reading at CR1.5-31, so it showed "nothing handed over" by
    being ignored; it now answers in the helper's own form, after the second "--".
8. Two of batch 1's tests quoted the tool's line whole ("… is handed over either way."); they
    quote the new ending.

## Batch 3

Where a grant's path really leads: #665, #391, #401. Fable 5.2, high effort. Nothing was taken
over: the worktree was clean at the start.

**The merge of U04's tip**: 0bc5b38, "Merge U04's branch in at 0bff619". No conflict outside
`docs/relay/`, which stayed this unit's (the brief's `restore` line). U04's tip moved once after
that (158f5c2, its batch 2's new findings #737 and #738 in the schedule): not in this batch. It
touches `docs/remediation/CR1-schedule.json` alone and conflicts there with this branch's record of
#736 (`git merge-tree`), both sides adding records at the end, as batch 2 met; batch 4 takes it in.

**Counts**: fixed 3, no defect 0, remedy changed 0, set aside 0, still left 0, new 3 (none fixed:
one High, two Low). Beside them, the coordinator's item: R17.4's sentence on the helper's answer
(batch 2's doubt), 9902711.

**Files touched**: `src/appkata_core/sandbox.py`, `tests/test_sandbox.py`,
`tests/test_sandbox_adversarial.py`, `tests/test_sandbox_run.py`,
`tests/data/launchers/online-app-appimage-with-folders.sh` (written again by `UPDATE_GOLDEN=1`, in
#665's commit; the other goldens unchanged),
`docs/requirements/R17-app-sandboxing/R17.3-templates.md`,
`docs/requirements/R17-app-sandboxing/R17.4-the-launcher.md`, `docs/requirements-trace.md`.

### The findings

**#665, fixed, 457857a.** The remedy is the finding's, with one rule added (see **Needs your eye**).
At each launch, before bwrap, the launcher asks where each granted folder leads (`readlink -m`) and
compares it with where it led when the launcher was written, baked beside it
(`g1=<folder>; leads "$g1" <where it led> || g1=`). A grant that leads elsewhere is dropped for that
launch: not mounted, no visible folder to the file-argument helper, nothing of it covered or shown
empty for the session bus, and a line on stderr. A grant through the user's own link stands. The
grants' binds are words put before "$@" just ahead of bwrap now (text of the bwrap command can't
be dropped at a launch), in their order. And `refused_folders()`, which the chips,
`strip_protected()` and `build_launcher()` share, refuses a grant when a link on its way lies in
another folder of the same set. The note beside the guard that called the source side safe is
corrected. Tests:
- tier 1, `tests/test_sandbox.py`: `test_a_grant_that_no_longer_leads_where_it_led_is_dropped_at_the_launch_and_said`
    (the launcher run whole with a stand-in bwrap, seven grants, their ways changed or not once it
    is written: the finding's links, a nested folder made as a link, the user's own link moved, a
    user's link left alone, a folder not there; then no `readlink` that answers, and an unreadable
    bus address), `test_a_grant_that_a_link_in_another_granted_folder_leads_to_is_refused_when_the_launcher_is_written`
    (the rule at writing: a link in the outer folder, out of it, a loop, one that leads nowhere, a
    link that is the grant, a link outside every grant that leads into one, the user's link in no
    granted folder, a link in a refused folder; the chips, `strip_protected` and the launcher).
    Changed with it: `test_a_folder_granted_where_the_session_bus_was_not_yet_hides_its_socket`'s
    "a link pointed there later" (dropped now, not covered), the helper's words in
    `test_launcher_hands_over_file_arguments_only_for_standard_apps`, and
    `tests/test_sandbox_adversarial.py`'s reader of the launcher's binds (`_bwrap_words`).
    Shown failing: the tree of 0bc5b38 (`git archive`) with the new test files and goldens over
    it, in the scratch home: both new tests, the eight "pointed there later" cases, the helper's
    words and the golden failed.
- tier 2, `_a_link_put_above_a_nested_grant_mounts_nothing_of_the_users`, a part of
    `test_nested_folder_grants_cannot_reopen_the_symlink_hole`: the finding's run with the inner
    grant read-only (`~/.ssh`) and read-write (`~/.config/autostart`), a folder no list names
    (`~/Documents`) with the launcher written again after each, a nested folder made as a link
    after the launcher was written, a command-line tool run once above its own folder and then
    elsewhere, and the user's own link (it stands; moved, it is dropped; written again, it is
    given). Shown failing on the 0bc5b38 tree in both containers (Mint 22.3: bwrap 0.9.0; LMDE 7:
    bwrap 0.12.0): the app listed `~/.ssh` and read the key (`id_ed25519`, `SECRET-KEY`, twice:
    by the victim's path and by the grant's). With the launch check alone (the rule at writing
    switched off in a scratch copy) the third case failed in the Mint container: the launcher
    written again had no refusal. With the fix: passed in both; the whole launcher tier at
    457857a, Mint 22.3 147 passed, 5 skipped, LMDE 7 147 passed, 5 skipped.

**#391, fixed, 0aba660.** `sandbox.folder_path()` is a folder's one name (from `~` in the home, from
`/` elsewhere, no doubled slash, no `.` step, no slash last); `normalize()` names every set's
folders so, `apply_overrides()` adds and removes by that name. A `..` is refused for everyone
(`DOTDOT`). Tests:
- tier 1, `tests/test_sandbox.py`: `test_a_folder_is_kept_shown_and_mounted_under_one_name_and_never_with_a_dotdot`
    (25 ways of writing a folder, each read-write and read-only: the override, a saved set read
    back, the chip, the Audit's phrase, the launcher's bind), `test_a_review_cannot_write_a_folder_so_that_it_reads_as_another_and_two_ways_of_writing_one_are_one_grant`
    (the finding's line through `config_from_review` and `choose`; two ways of writing one folder).
    Shown failing on the 457857a tree: all 26 failed, at the name function, which is new; the
    fault itself by a scratch script on both trees: before, the chips of the finding's line were
    `/home/kata/Notes/`, `~/Documents/../.config/google-chrome/Default`, `~/Media// · read-only`;
    after, `~/Documents/../.config/google-chrome/Default · refused: not a full path (it has a ..
    in it: name the folder it leads to)`, `~/Media · read-only`, `~/Notes`.
- Changed with it, in U05's test files: tests that quoted a folder as written where that was a
    full path in the test's home or `//proc` quote its name (`sb.folder_path`), and three that
    built a grant set before `_launched()` set the home it is for set the home first. The other
    test files that name the sandbox (38, other units' among them) passed unchanged.

**#401, fixed, 9f56bec.** A path with a control character (Unicode's Cc) is "not a full path" in
`protected_folder()`; `secret_folder()` and `system_folder()` say nothing of it; `parse_folders()`
and `folder_path()` keep it with U+FFFD where each such character was, so no grant set, chip,
launcher or record holds one, and the refusal is shown like the others. Tests:
- tier 1: `tests/test_sandbox_adversarial.py`'s `HOSTILE` gains ten paths (`~/a<NUL>b`, a bare
    NUL, a NUL before `..`, BEL, ESC, backspace, DEL, NEL, CR), held by
    `test_a_hostile_folder_path_is_bound_whole_or_refused_and_the_launcher_stays_valid_shell` and
    `test_parse_folders_keeps_every_hostile_path_whole`; `tests/test_sandbox.py`'s
    `test_a_review_whose_folder_has_a_control_character_breaks_nothing_and_is_refused` (the
    finding's road, a review's section to the launcher). Shown failing on the 0aba660 tree: the
    twelve control cases of the hostile test (three with `ValueError: lstat: embedded null
    character in path`, the others bound where they are refused now), the parse test and the
    road test; a scratch script on that tree: `protected_folder`, `strip_secrets`, `summary` and
    `build_launcher` each raised the ValueError for the finding's line.

**The coordinator's item, 9902711.** R17.4's sentence on the helper's answer says each kind of line
("=" an argument, "!" why one was not handed over, printed as text and no argument, any other
nothing). Its trace row gains #651's test and a new one,
`test_a_line_of_the_answer_that_says_why_is_printed_as_text_and_is_no_argument`. No code changes.

After the last commit (9902711): the whole launcher tier in the Mint 22.3 container, 147 passed, 5
skipped, and in the LMDE 7 container, 147 passed, 5 skipped; the whole tier 1 suite in its
container under a 3 GB cap, 5131 passed, 138 skipped, none failed; the 38 other test files that
name the sandbox in the scratch home, 2751 passed, 2 skipped. After each fix: the unit's own tier 1
files and the document checks whole in the scratch home (2564 passed at #401's), and the touched
run tests in the Mint 22.3 container.

How #665 slipped past, as a class: a bind source that lies under a folder the app can write on the
host. The launcher's other sources are not such (the private home and the install folder are
mounted whole and nothing above them is the app's; the identity marker was moved out of the private
home in an earlier round), so the members are a grant under another grant and a grant under a
folder a tool was run in: both are in the run test, and what remains of the second is **New** 1.

### Needs your eye

- 457857a (#665): the line a user sees when a grant is dropped at a launch: "<App> runs sandboxed
    and isn't given <folder> this time: it led to <where> when AppKata wrote this launcher and
    leads to <where> now, so a link on the way there was made or changed since. AppKata judges the
    folder again the next time it starts." (<where> now is "nowhere that can be followed" when
    `readlink` gives no answer.) R17.4 gains two sentences ("A folder grant's source is the host's
    own folder …", "One that leads elsewhere …").
- 457857a (#665): **a rule the record doesn't name.** R17.3.1 gains "A grant is refused the same
    way when a link on the way to its folder lies in another folder the same app is granted …",
    and the chip, the launcher's note and the dialog's toast say "a link in ~/Projects, which the
    app can change, is on the way to it". Why: where a folder leads is baked into the launcher, so
    once a link moves it the launcher's text differs and AppKata's start writes it again; judged
    afresh there, the app's link became the folder's place for every folder no list names (shown
    in tier 2). It holds for a read-only outer folder too, and for the user's own link in a granted
    folder (the folder the link names can be granted itself). It is not the alternative the brief
    keeps for the owner: a nested grant with no link on its way stands.
- 457857a (#665): a grant whose link was pointed at the session bus's folder after the launcher was
    written (PR #694's P5-B1) was mounted with the socket covered; it is dropped at that launch.
    The user's own link moved after the launcher was written is dropped the same way until AppKata
    starts again.
- 0aba660 (#391): **`..` is refused for everyone**, the choice the brief left to the batch: "not a
    full path (it has a .. in it: name the folder it leads to)". A `..` that leads to a
    never-shared folder still says that reason. R17.3.1 gains "A path with a `..` in it is refused
    the same way too …" and "A grant is kept, shown … and mounted under one name …". What the user
    sees change: a folder written `/home/<user>/Notes/` shows as `~/Notes`; a folder written two
    ways is one grant, read-only where one of the two is.
- 9f56bec (#401): the reason "not a full path (it has a control character in it, shown as �)", and
    the folder shown with `�` where the character was. A newline or a tab in a folder's name was
    bound until now; both are refused. R17.3.1 gains "So is a path with a control character in it
    …".
- 9902711: R17.4's sentence on the helper's answer, rewritten.

### Needs a run

The VMs (the coordinator's). #665's check is `readlink -m`, which GNU coreutils has; Ubuntu 26.04's
coreutils are another make, and where `readlink -m` gave no answer every folder grant would be
dropped at every launch, with the line. The same cases under Ubuntu's kernel and AppArmor profiles:

```
scripts/test-sandbox.sh launcher-vm -k "nested_folder_grants or home_folder_or_the_keys or file_argument_is_handed_over or session_bus_socket or relative_folder"
scripts/test-sandbox.sh launcher-vm26 -k "nested_folder_grants or home_folder_or_the_keys or file_argument_is_handed_over or session_bus_socket or relative_folder"
```

### Guard

The guard (`triage.py guard U05 --on U04 --base origin/cr1-u04-downloads-checksums`, from the main
checkout's `agents/` since the coordinator's note) passes on every commit, with no file outside
U05's plan (but `docs/relay/`). `tests/test_sandbox_properties.py` is U16's and reads a grant's
bind from the launcher's text (`--bind-try P P` in it, P the second word of its line): the new
lines keep both (`[ P = "$g1" ] && set -- --bind-try P P "$@"`), so that file is unchanged. The
tier 2 checks are a helper inside a run test `tests/skips/tier1.txt` already names, as settled.

### New

1. **High. A launcher written again takes an app's link for a folder's place, where the link lies
    in a folder the app could write by another road than its own grants.** #665's rule at writing
    knows the set's own folders. It doesn't know (a) the folders a command-line tool was run in
    (`$cwd`, read-write), (b) a folder handed over through the document portal (#736's road), (c)
    another app's read-write grant above this app's. `src/appkata_core/sandbox.py`,
    `refused_folders()` and `build_launcher()` (where a folder leads is `os.path.realpath()` at
    each writing). The case, run at 457857a in the Mint 22.3 container (a scratch test, not in the
    repository): a `cli-tool` with `~/src5/proj/data` granted read-only is run once in
    `~/src5/proj`, where it does `mv data data.old; ln -s ../../Documents data`. Run from
    elsewhere, the grant is dropped (#665). The launcher written again (AppKata's next start)
    bakes `~/Documents` as where the folder leads, and the launch after reads
    `~/Documents/taxes.txt` at `~/src5/proj/data` ("TAXES"). The never-shared folders stay refused
    (the path is judged by where it leads); a folder of the secret list (`~/.aws`, the password
    store) is not, since a pinned set is the user's. High as #665, by its outcome; it needs a tool
    the user gave a folder inside a place it is run in, and AppKata started once between. Not
    fixed here: not small. The fix I would make: where a folder led when it was granted is kept
    with the grant (the pin in the install record), every launcher is written with that, and only
    the user's own save in the Sandbox dialog, or an install, judges where it leads anew; then
    the line's last sentence ("AppKata judges the folder again the next time it starts") changes.
2. **Low. A1.2.3's sketch of the launcher shows a folder grant as text of the bwrap command**
    (`docs/architecture/A1-app-sandboxing/A1.2-approach.md`, line 154, `--bind-try
    "$HOME/Documents" "$HOME/Documents" \  # a grant`), and A1.2 says nothing of the launch check
    or of a link in another granted folder. Not U05's file; with #734, U13's.
3. **Low. The review badge and the Audit name a refused folder among what a set adds.**
    `sandbox.changes()`, through `suggestion_text()` (`backend.py`, the badge's text and
    `hasSuggestion`) and the Audit's entry: a review that asks `~/.ssh`, or
    `~/Documents/../.cache`, reads "A reviewer suggests adding ~/Documents/../.cache (read-only)",
    though the chips show it refused and nothing is mounted. As it was before this batch for every
    never-shared folder (`Backend._suggestion()` strips the secret folders alone); #391's own
    words name the badge, so it is said here. Not fixed: it changes when a suggestion counts as
    one (`backend.py` and the backend's tests).

### The real home

Every run's `diff` of `/home/dev/bin`, `~/.local/share/appkata` and `~/.local/share/applications`
before and after: empty.

### Doubts for the coordinator

1. **The rule at writing (Needs your eye) is mine.** Without it #665's fix holds only until
    AppKata next starts. With it the roads of **New** 1 remain.
2. A live race stays, as the guard's note says of its own: a second instance still running can put
    a link on a grant's way between the launcher's asking and bwrap's mounts.
3. A loop of links on a grant's way (`sub -> sub`): `readlink -m` and `os.path.realpath()` both give
    the path back, so the grant stands and bwrap then fails the launch on it ("Can't find source
    path"), as before this batch. At writing, a loop in another granted folder is refused by the
    new rule.
4. `readlink` is run by bare name, on the launcher's own PATH (#407). Where it gives no answer
    (not coreutils') every grant is dropped, with the line: closed, not open.
5. #401 takes U+FFFD (`�`) in a folder's path for the mark of a control character, so a folder
    whose real name holds `�` is refused, with a reason that says "control character". Other
    characters that mislead a reader are not refused: the bidi controls (U+202E; category Cf, as a
    zero-width joiner in a name is), a no-break space.
6. Named from `~`, a grant set means what it says under the home it is read in. Three tests built a
    set under one HOME and ran its launcher under another; they set the home first now. A full
    path under the home was kept as written before, and is `~/…` now.
7. `folder_path()` leaves a path as written where `os.sep` is not `/` (no sandbox there, R17.1):
    the Windows tier is not one I could run.
8. The grants' binds come after the sound sockets, the identity marker and the `xdg-open` shim in
    bwrap's words now (they were before them); no grant can name those places (`/`, `/run`, the
    runtime folder are never shared), so nothing they mount changes.
9. The cover of a bus socket in a granted folder still asks `readlink -f` for where the grant
    leads; with the launch check that is where it led when written, for a grant that stands. Left
    as it was.

## Batch 4

The places of the home the never-shared and secret lists miss: #384, #632, #701, #383, #392, and
#745 (added by the coordinator after batch 3). Fable 5.2, high effort. Nothing was taken over: the
worktree was clean at the start.

**The merge of U04's tip**: 4164112, "Merge U04's branch in at 97cf7e3". One conflict outside
`docs/relay/`: `docs/remediation/CR1-schedule.json`, where both sides added records at the end of
the findings (U04's #737–#742; this branch's #734, #736, #743–#745). Both kept, in the issues'
order; the units' findings and files merged by themselves (U04, U06 and U10 as U04's branch has
them, U05 and U42 as this branch has them). `triage.py check --offline`: "49 units holding 600
findings, 0 set aside: no problems". `docs/relay/` stayed this unit's. **U04's tip moved after
that**, by eight commits, to 0c08e3f (its batch 4, its `docs/relay/` deleted, `upstream/master`
merged in): not in this batch. `git merge-tree` says the next merge conflicts, outside
`docs/relay/`, in `docs/remediation/CR1-schedule.json` and in `tests/test_backend.py`, where both
branches added tests at the file's end (keep both).

**Counts**: fixed 6, no defect 0, remedy changed 0, set aside 0, still left 0, new 2 (both Low,
none fixed).

**Files touched**: `src/appkata_core/sandbox.py`, `src/appkata_core/install.py`,
`src/appkata/backend.py`, `tests/test_sandbox.py`, `tests/test_sandbox_adversarial.py`,
`tests/test_sandbox_one_fact.py`, `tests/test_sandbox_run.py`, `tests/test_backend.py`, the five
goldens under `tests/data/launchers/` (written again by `UPDATE_GOLDEN=1`, in #384's and #632's
commits), `docs/requirements/R17-app-sandboxing/R17.3-templates.md`,
`docs/requirements/R17-app-sandboxing/R17.17-limits.md`,
`docs/architecture/A1-app-sandboxing/A1.11-claims.md`, `docs/requirements-trace.md`; and, outside
U05's files (see **Guard**), `tests/test_sandbox_claims_table.py`, `tests/test_dialog_contract.py`
and `tests/test_launcher_golden.py`.

### The findings

**#384, fixed, b5af552 (and d1bc8bc, a test it broke).** `_protected_roots()` gains, each with what
is inside and above it: Cinnamon's `~/.local/share/cinnamon`, whole, and `~/.cinnamon`;
bash-completion's `~/.bash_completion`, `~/.config/bash_completion` and
`~/.local/share/bash-completion`; im-config's `~/.xinputrc`; the compositors' and window managers'
configurations (`~/.config/sway`, `~/.sway`, `~/.config/i3`, `~/.i3`, `~/.config/hypr`,
`~/.config/labwc`, `~/.config/openbox`, `~/.config/river`, `~/.config/niri`,
`~/.config/wayfire.ini`); `~/.config/pipewire`; `~/.vscode/extensions` and
`~/.vscode-oss/extensions`; `~/.cargo/bin` and `~/go/bin`. A command-line tool run from one is not
given it, and the file-argument helper, which is given the same list since #651, hands no file of
one over. The alternatives (no dot folder for a review; an allow-list) are not taken. Tests:
- tier 1, `tests/test_sandbox.py`: 39 new cases of `test_protected_folders_are_never_granted`,
    `test_a_review_cannot_grant_a_place_code_runs_from_later_and_the_user_cannot_pick_one` (the
    finding's road: a review's line through `config_from_review` and `choose`, the chips, the
    launcher, the picker's `strip_protected`, a tool's list); `tests/test_sandbox_adversarial.py`:
    `test_a_place_code_runs_from_later_is_refused_and_never_bound_however_it_is_written` (39 paths).
    Shown failing: the tree of 4164112 (`git archive`) with the new test files over it, in the
    scratch home: 33 of the list's new cases, the road test and 37 of the 39 adversarial ones.
- tier 2, a part of `test_every_file_the_distributions_default_bashrc_sources_is_refused` (see
    **Guard**): `_what_the_desktops_own_programs_load_from_the_home_is_refused` asks the platform,
    as that test asks the default `.bashrc`: what bash-completion's script and profile script,
    Cinnamon's `js/ui/main.js` and panel-launchers applet, and im-config's `xinputrc.common`
    themselves name as the places in the home they load from, each reader first held to the lines
    it was written from. **The launcher images carry neither bash-completion nor Cinnamon**, so
    there the part finds nothing. Shown failing and passing where the programs are:
    in both launcher containers with the distribution's own bash-completion package unpacked into
    the container for the run (`apt-get download`, then `dpkg-deb -x`: 2.11 on Mint 22.3, 2.16 on
    LMDE 7; no image built or changed): failed on the 4164112 tree, passed with the fix; and in the
    `appkata-desktop-mint22.3` and `appkata-desktop-lmde7` images (Cinnamon 6.6.9, im-config 0.57),
    where the file's tests are skipped for want of bwrap, by calling the part itself: "AssertionError:
    /usr/share/cinnamon loads ~/.cinnamon/panel-launchers, which would be shared" on that tree,
    seven places held with the fix. `tests/test_sandbox_one_fact.py`'s agreement test gains eight
    folders (it passes before and after: it holds the tool's rule to the grant check).
- d1bc8bc: `tests/test_sandbox_claims_table.py` holds A1.11's inferred rows to its own list; the
    new row is listed there. b5af552 was committed without that file run.

**#632, fixed, 437fa6f (and 10148e0, a test it turned round).** `sandbox.Own` names AppKata's own
folders beside the app's install folder; `protected_folder`, `refused_folders`, `strip_protected`,
`summary_chips`, `summary`, `build_launcher`, `launcher_text` and `write_launcher` take one where
they take `apps_root`. The list holds the app's install folder, the default one whatever Settings
name, and the command links folders: the default `~/bin` and those of `own`.
`install.Portable` carries them (`others`, and `own`, which adds the folder the app's own link
goes in) to the launcher's writers and the startup pass's comparison; the backend fills them in
(`_own_folders`): the command links folder of Settings, and each folder an installed app's command
link is in today. The alternative (every folder of the login PATH) is not taken. Tests:
- tier 1, `tests/test_sandbox.py`:
    `test_the_command_links_folder_and_the_default_install_folder_are_never_shared_wherever_apps_are_installed`
    (six settings: each folder's reason, the chips, the picker, the binds, a tool's list and the
    helper's), `test_a_review_cannot_grant_the_command_links_folder_and_a_launcher_an_install_writes_keeps_it_out`
    (through `install._activate` and `launcher_is_current`), and
    `test_launcher_and_summary_refuse_protected_folders`' line that held `~/bin/apps` as granted
    under a custom install folder, turned round; `tests/test_backend.py`:
    `test_the_sandbox_is_told_the_command_links_folder_of_settings_and_of_every_install`.
    Shown failing on the b5af552 tree: all ten (the turned-round line on what the launcher holds;
    the others at `sb.Own`, which is new, so the fault itself by a scratch script on that tree:
    with the install folder `~/Apps`, `protected_folder` gave "" for `~/bin`, `~/bin/apps`,
    `~/bin/apps/x/run` and `~/tools`).
- tier 2: `tests/test_sandbox_one_fact.py`'s agreement test asks every folder twice, with the links
    in `~/bin` and in `~/tools` (a real launcher, a stand-in bwrap), and holds `~/bin`, the default
    install folder and `~/tools` to the right answer. Mint 22.3 and LMDE 7: failed on the b5af552
    tree (at the new argument), passed with the fix.
- 10148e0: `tests/test_dialog_contract.py` told an installed app's own folder from Settings' by the
    chips' answer, which is now the same for both (the first is the default install folder); it
    reads the folder the backend hands the chips. 437fa6f's run had left that file out.

**#701, fixed, 03e86bb.** `sandbox.Own.roots`: every install folder AppKata has apps in, and the
one Settings name for the next install, gathered by the backend from the install records. Tests:
- tier 1, `tests/test_sandbox.py`:
    `test_an_app_in_one_install_folder_is_never_given_another_folder_apps_are_installed_in` (both
    directions: a review's line, the user's pick, a tool's lists),
    `test_a_launcher_an_install_writes_keeps_out_the_other_folders_apps_are_installed_in`;
    `tests/test_sandbox_adversarial.py`:
    `test_another_folder_apps_are_installed_in_is_refused_and_never_bound_however_it_is_written` (12
    paths); `tests/test_backend.py`:
    `test_the_sandbox_is_told_every_install_folder_apps_are_in_and_the_one_settings_name` (apps
    recorded in two folders, Settings naming a third). Shown failing on the 437fa6f tree: all 16
    (at `Own.roots`, which is new; by a scratch script on that tree an app in `~/Apps` asked of
    `~/OldApps` and `~/OldApps/victim/run`: "" for both).

**#383, fixed, b191b0b.** `_secret_roots()` gains the Chromium family's eight data folders, whole
(their top stays never shared, and that answer comes first), `~/.config/mozilla/firefox`, the
Firefox forks' `~/.librewolf`, `~/.waterfox`, `~/.floorp` and `~/.zen`, Tor Browser's
`~/.local/share/torbrowser`, Evolution's two folders and `~/.config/goa-1.0`. Tests:
- tier 1, `tests/test_sandbox.py`: 24 new paths in `SECRETS`
    (`test_a_secret_folder_is_one_a_review_cannot_grant_but_the_user_can`),
    `test_a_chromium_data_folder_is_never_shared_at_its_top_and_what_is_in_it_is_a_secret` (the
    eight folders: the finding's road, the user's own pick, what the launcher mounts), five
    look-alikes in `test_ordinary_folders_are_no_secrets`; the line that held the profile as
    grantable says what it is now. Shown failing on the 03e86bb tree: the 24 and the 8; by a
    scratch script the finding's line kept all four folders there, and has them refused now.

**#392, fixed, e8b5eab.** A root of either list under `~/.config` or `~/.local/share` is also
under `$XDG_CONFIG_HOME` or `$XDG_DATA_HOME` where the variable names another folder; the
never-shared list also holds `$GNUPGHOME` and zsh's startup files in `$ZDOTDIR`. Tests:
- tier 1, `tests/test_sandbox.py`:
    `test_a_never_shared_or_secret_folder_is_refused_where_the_environment_moves_it_and_at_its_default_place`
    (all four variables: 26 moved and 7 default never-shared places, 12 secrets, 8 folders still
    shared; a review's line, the picker, a tool's two lists; the lists unchanged for the default,
    empty and relative values),
    `test_the_startup_pass_writes_a_launcher_again_once_a_variable_moves_a_never_shared_folder`.
    Shown failing on the b191b0b tree: both, on the fault itself ("" for `~/cfg/autostart`; the
    launcher still current after `XDG_CONFIG_HOME` changed). The goldens don't change.

**#745, fixed, ae0aba5.** `Backend._given()` is a grant set without the folders AppKata refuses,
judged as the app's launcher judges them; the badge (its words, `reviewBadge`, `hasSuggestion`)
and the Audit's sandbox detail (`added`, `removed`, the template's label, `written for`) compare
sets so. The sets themselves stay as written, so the summary, the dialog's "what they suggest"
and the launcher still say a folder was refused. Tests:
- tier 1, `tests/test_backend.py`:
    `test_the_review_badge_and_the_audit_leave_a_refused_folder_out_of_what_a_reviewers_set_adds`,
    `test_a_review_that_asks_only_for_refused_folders_suggests_nothing_to_act_on`. Shown failing on
    the e8b5eab tree: both (the badge read "Desk suggests adding ~/.local/share/cinnamon/applets
    (read-write), ~/.ssh (read-only), ~/Documents/../.cache (read-only), ~/Notes (read-write) and
    ~/bin/apps/other (read-write)"; with that assertion taken out of a scratch copy, the Audit's
    `added` held the same five).

After the last commit (ae0aba5): the whole launcher tier in the Mint 22.3 container, 147 passed, 5
skipped, and in the LMDE 7 container, 147 passed, 5 skipped; the whole tier 1 suite in its
container under a 3 GB cap, 5356 passed, 138 skipped, none failed. Before a commit, in the scratch
home, beside the touched files and the document checks: for #632 every test file that names the
sandbox with the backend's and the install's (3444 passed; `tests/test_dialog_contract.py` was not
among them, see 10148e0), for #701 the same with the dialogs' (3512 passed, and that one failure),
for #383 the same without the four run files (2990 passed), for #392 all of them (3551 passed),
for #745 the 14 files that use the backend, the badge or the Audit's detail (1121 passed).

### Needs your eye

- b5af552 (#384): R17.3.1's list gains the places above, and the sentence "It is a list of the
    places AppKata knows, kept by hand, and it is not complete …"; R17.17 gains "the never-shared
    folders of R17.3.1 are a list of the places AppKata knows and not of every place …". The
    reasons a user sees: "Cinnamon's applets, desklets, extensions and panel launchers",
    "Cinnamon's panel launchers", "your shell's completion scripts", "PipeWire's configuration,
    which can start programs", "your editor's extensions", "your window manager's configuration,
    which starts programs", and for the PATH folders "programs on your PATH". Mine, beside the
    remedy: `~/.local/share/cinnamon` whole, not its three folders (its `search_providers` and
    `panel-launchers` are read the same way, by Cinnamon's own files); `~/.config/bash_completion`,
    `~/.sway`, `~/.i3`, river, niri, Wayfire and `~/.vscode-oss/extensions`. `~/go` and `~/.cargo`
    are refused as folders above (`~/go/src/…` is shared). A file in one of these is no longer
    handed to a sandboxed app by being named (`editor ~/.config/sway/config`): the helper's list
    is the same one (#651's decision). A1.11 gains five rows; one is **inferred** (i3, Hyprland,
    labwc, Openbox, river, niri, Wayfire, VS Code, Cargo, Go: none installed in a tier), and is
    listed in `tests/test_sandbox_claims_table.py` as such.
- 437fa6f (#632): R17.3.1 says which of AppKata's folders are never shared: the install root
    "(the folder the app is installed in, and the default one whatever Settings name …)" and "its
    command links folder (R4.3.1.3, on `PATH`: the one Settings name, the default `~/bin`, and any
    folder a command link AppKata made is still in)". The reason a user sees: "the command links
    folder, which is on your PATH". Mine: the default `~/bin` is refused whatever Settings name; a
    folder an installed app's link is still in is refused until that app is updated; a command
    links folder that is the home folder or above it adds nothing.
- 03e86bb (#701): R17.3.1's install root is "the folder the app is installed in, every other
    folder AppKata has an app in and the one Settings name for the next …".
- b191b0b (#383): R17.3.1's Secrets sentence names the new places, and its sentence on the
    Chromium folders is corrected. The reasons: "a browser's profiles and saved logins", "Tor
    Browser and its profile", "Evolution's mail and accounts", "your online accounts' sign-ins".
    The forks' list is mine (the record leaves it), and so is `~/.config/mozilla/firefox`.
- e8b5eab (#392): R17.3.1 gains "A folder of the list that lies in `~/.config` or `~/.local/share`
    is refused there and where `XDG_CONFIG_HOME` or `XDG_DATA_HOME` puts it …". **What the brief
    left to the batch**: the startup pass sees a variable changed after a launcher was written
    when AppKata itself is started with it, and then writes the sandboxed apps' launchers again; a
    variable set only where AppKata's own start doesn't read it (a shell's startup file, for an
    AppKata started from the menu) it never sees, and the moved folder is not refused. The
    sentence says the first half.
- ae0aba5 (#745): no requirement changes. The badge and the Audit no longer name a refused folder;
    a review that asks only for refused folders raises no badge and offers no "Use theirs".

### Needs a run

The VMs (the coordinator's), where bash-completion is installed and the launcher images don't have
it: #384's part reads the system's own files there, and #632's agreement runs under Ubuntu's
kernel and AppArmor profile:

```
scripts/test-sandbox.sh launcher-vm -k "default_bashrc or agree_on_every_folder or sees_and_writes_the_project"
scripts/test-sandbox.sh launcher-vm26 -k "default_bashrc or agree_on_every_folder or sees_and_writes_the_project"
```

A Mint or LMDE desktop VM would run #384's part against a real Cinnamon; the two desktop images
gave the same files to the part called by itself (above).

### Guard

The guard (`triage.py guard U05 --on U04 --base origin/cr1-u04-downloads-checksums`, from the main
checkout's `agents/`) passes on every commit. Outside U05's plan, each "no other unmerged unit
claims it: add it to U05's files": `tests/test_sandbox_claims_table.py` (d1bc8bc) and
`tests/test_launcher_golden.py` (e8b5eab: its fixed host unsets the three variables #392 reads).
`tests/test_dialog_contract.py` (10148e0) is a shared file, and the guard says to add it too. `tests/skips/tier1.txt` is U44's and
names every test of `tests/test_sandbox_run.py`, as batch 1 said: #384's platform check is a part
of a run test that file already names. `tests/test_sandbox_surfaces.py` is U16's and stands in for
`summary_chips` with a function of three arguments: `summary()` passes `own` only when it is given
one, so that file is unchanged.

### New

1. **Low. AppKata's data folder follows a relative `XDG_DATA_HOME` as it is written.**
    `src/appkata_core/platform.py`, `data_dir()`: with `XDG_DATA_HOME=cfg` the database, the logs
    and every private home are in `cfg/appkata` under whatever folder AppKata was started in (seen
    in #392's test: the never-shared list's own entry was `cfg/appkata`). The XDG rule is that a
    value that is no full path is ignored. `sandbox.user_folders()` reads `XDG_CONFIG_HOME` the
    same way. Not U05's file.
2. **Low. An install folder that is the home folder, or above it, makes every folder of the home
    "AppKata's installed apps" to the app installed there.** `src/appkata_core/sandbox.py`,
    `_protected_roots()`, the `apps_root` entry: `protected_folder("~/Notes", apps_root=<home>)`
    is refused, as it was before this batch. For the folders this batch added (`own`) such a
    folder is left out; the app's own is as it was, since leaving it out there would share the
    folder its program is in. It needs Settings' install folder set to the home folder.

### The real home

Every run's `diff` of `/home/dev/bin`, `~/.local/share/appkata` and `~/.local/share/applications`
before and after: empty.

### Doubts for the coordinator

1. **Two commits broke a test in a file I had not run, and each has a follow-up commit**: #384's
    inferred row (`tests/test_sandbox_claims_table.py`, d1bc8bc) and #632's default install folder
    (`tests/test_dialog_contract.py`, 10148e0). From #701 on, every test file that names the
    sandbox, the backend or an install was run before each commit.
2. The never-shared list is in every sandboxed app's launcher (the helper's list), so a new
    command links folder, an install into a new folder, or a changed variable makes the startup
    pass write all of them again, once. Between the change and AppKata's next start the launchers
    hold the earlier list.
3. `~/bin` reads "a folder above AppKata's installed apps" where the install folder is the
    default, as before: the install folders are asked first. `~/bin/<anything else>` reads "the
    command links folder, which is on your PATH".
4. What #384's list still doesn't hold, that I know of and didn't add for want of evidence:
    `~/.config/cinnamon/spices` (an applet's settings; Cinnamon 6.6.9 reads them, whether one
    names a command is the applet's), `~/.cargo/env` (sourced by the shell where rustup set it
    up), WirePlumber's and other desktops' folders. The requirement now says the list is not
    complete.
5. #392 follows the four variables the finding names. Others move a secret the same way and are
    not followed: `PASSWORD_STORE_DIR`, `KUBECONFIG`, `DOCKER_CONFIG`, `CARGO_HOME`,
    `AWS_SHARED_CREDENTIALS_FILE`.
6. #745 leaves a review's set as written in `sandboxReviewSeen` (what the badge remembers) and in
    the install record; only comparisons use the set as given. The "kept the sandbox of" Audit
    entry lists the suggestion's chips, a refused folder among them with "· refused: …".
7. `tests/test_sandbox_one_fact.py`'s agreement test runs its folders twice now (about twice as
    long: some 9 s more on this machine).
8. In the launcher containers `/home/kata` is a real home, and `tests/test_sandbox.py`'s
    `a_users_home` names it without writing there; the new tests that use it write nothing.
9. `Backend._app_options()` reads every install record at each call now (`_own_folders`), where it
    read one; the startup pass asks it once for each sandboxed app, so that pass parses the records
    a number of times that grows with the square of the apps installed. Not measured beyond the
    tests; a cache would need to know when an install changes.
10. For #384's run with bash-completion, each distribution's package was fetched from its archive
    (`apt-get download` in a throwaway container) into a scratch folder under /tmp, read there and
    unpacked into throwaway containers; nothing of it is in the repository or in an image.
