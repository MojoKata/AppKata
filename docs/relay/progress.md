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
