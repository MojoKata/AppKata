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

**The merge of U04's tip**: up to date (`origin/cr1-u04-downloads-checksums` was still b912a42, this
branch's own start, at the start and at the end of the batch); no merge commit.

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
