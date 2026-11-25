# Relay brief: CR1's unit U05, the sandbox: what may be granted, and file arguments

Temporary: `docs/relay/` is deleted before this unit's pull request merges. Read this whole brief,
then `docs/relay/progress.md`, then your batch file. Nothing else from earlier agents.

## Goal

AppKata is the owner's own project, and CR1 is its own code review. The review's findings are GitHub
issues, and the owner approved a schedule of work units, one pull request each
(`docs/remediation/CR1-schedule.json`). This relay is the unit **U05, "The sandbox: what may be
granted, and file arguments"**: 17 findings, fixed in five batches by one agent at a time on the
branch `cr1-u05-sandbox-grants`, in the worktree `/home/dev/kata/AppKata/.claude/worktrees/cr1-u05`.
You fix your batch's findings in the owner's own code and prove each fix. You push nothing and write
nothing on GitHub.

| Batch | Findings | What |
|---|---|---|
| 1 | #380, #381, #189 | the system places (/proc, /tmp, /etc …) refused to every grant and to a tool's working directory |
| 2 | #651, #379, #390, #666 | the file-argument helper: what it hands over, and what it never does |
| 3 | #665, #391, #401 | where a grant's path really leads: checked at launch, shown normalized, refused with a NUL |
| 4 | #384, #632, #701, #383, #392 | the places of the home the never-shared and secret lists miss |
| 5 | #400, #395 | uninstall: the portal's grants revoked, and a private home that can't be removed |

Your batch is one file, `docs/relay/batch-N.txt`. Its first lines say where its items came from. The
code at the head of `cr1-u05-sandbox-grants` is the code you work on: earlier batches' commits are
in it.

For each finding of your batch, read:

1. its record in `docs/remediation/CR1-schedule.json` (the file is 600 KB: take the record out with a
    short script, never read the file whole): its files, what it depends on, its proof and its note;
2. its issue: `gh issue view <n> -R MojoKata/AppKata --json title,body,comments`. Where the owner's
    decision is a comment or in the body, the decision is the remedy;
3. the code and the requirement sections it cites. The line numbers in the records and issues are of
    the code the review read; U01, U03, U07 and U09 have merged since (U09 changed the never-shared
    list and the launcher a great deal), so find the code by its function's name
    (`_protected_roots`, `_secret_roots`, `protected_folder`, `parse_folders`, `build_launcher`,
    the helper's `hand` and `export`, `remove_sandbox_home`).

`DEVELOP.md` and `docs/testing.md` say how this project's tests are run, and which need the tier 1
container. Load the `review-triage` skill and read its "What comes up mid-work": those standing
rules are the unit's, and this brief says below how a relay agent follows them.

**The batches run on Fable 5.2 at high effort** (the owner's word for this wave). An agent that finds
the worktree holding uncommitted changes it didn't make: they are a stopped agent's work on this
batch. Read them with `git diff`, keep what is right, finish it under the rules below, and say in
the progress section what was taken over. Never discard them with `git checkout` or `git restore`
without reading them first.

## Stacked on U04

The owner's rule (2026-11-25): a unit whose files overlap an open unit's, a shared file included,
starts on that unit's branch. U05 shares `src/appkata/backend.py` and `src/appkata_core/install.py`
with U04 (`cr1-u04-downloads-checksums`, worked by its own relay at the same time), so this branch
started at U04's branch tip, and its pull request is a draft against master that says so. The owner
merges U04 first.

**Before you start your batch's work, take U04's pushed tip in, by a merge** (never a rebase):

```
cd /home/dev/kata/AppKata/.claude/worktrees/cr1-u05 && git fetch origin cr1-u04-downloads-checksums &&
git merge --no-ff --no-commit origin/cr1-u04-downloads-checksums;
git restore --source=HEAD --staged --worktree -- docs/relay && git status --short
```

- `origin/cr1-u04-downloads-checksums` is the copy U04's coordinator checked and pushed; never merge
    the local branch, which can hold a batch still being worked.
- "Already up to date": nothing to do.
- `docs/relay/` is this relay's, and U04's branch has a folder of the same name: the `restore` line
    keeps this branch's, whatever the merge brought (a conflict, a new batch file, a deletion).
    After it `git diff --cached HEAD -- docs/relay` shows nothing.
- A conflict anywhere else is yours to resolve, keeping both units' changes; then run the test files
    of the conflicted files whole, as in *Checks* below.
- Commit it with the message `Merge U04's branch in at <its short hash>: U05 is stacked on it`, a
    line saying what was resolved where there was a conflict, and the `Co-Authored-By:` line below.
    It is listed in your progress section with its hash.

When U04's pull request has merged, the coordinator says so at the top of the next batch's section:
from then on the merge is of `upstream/master` (after `git fetch upstream`), the same way, and the
guard's base is `upstream/master`.

## What this unit's findings hold

- **Decided by the owner** (the decision is the remedy, in a comment or the body): #380, #381,
    #390, #651. The others' records say which remedy is taken.
- **Order inside the unit**: #381 after #380 (the same list); #379 after #651 (its second part is
    #651's change). #665 rests on #407's PATH part, which U03 merged; #701 on #310, merged.
- **A file argument under /tmp** (#380 with #651): once /tmp and /var/tmp join the never-shared
    list, a helper given the whole list stops handing over a file under them. Batch 2 follows the
    coordinator's answer, written at the top of its section; if none is there, the helper is given
    the list as it stood before batch 1 added the system places, so a file under /tmp is still
    handed over as R17.6.2 promises today, and the commit is listed under **needs your eye**.
- **Choices left out, a `refine` if wanted, never taken by a batch**: #665's refusing a nested
    grant when it is saved; #384's "no dot folder" and allow-list; #632's every folder of the login
    PATH; #400's not reusing a freed id. The records name them; take the remedy the record names.
- **Left to the batch, and said under needs your eye**: #391, whether `..` is refused for everyone
    or the resolved path is shown (what is shown must be what is mounted); #392, whether the startup
    pass sees a variable changed after a launcher was written; the stderr lines of #381, #651 and
    #665; #395's line when a private home can't be removed; the sentences R17.3, R17.4, R17.6,
    R17.14 and R17.17 gain.
- **Runs**: almost every finding is proven in tier 2 (the launcher container, below) as well as tier
    1. #665 (a planted run) and #400 (first on today's code with the real document portal: if a
    grant doesn't outlive the uninstall, the finding is **no defect**) count double.
- **Shared files** (the schedule's `shared_files`: other units change them too): `sandbox.py`,
    `backend.py`, `install.py`, `tests/test_sandbox.py`, `tests/test_sandbox_run.py`, the five
    launcher goldens under `tests/data/launchers/`, `docs/requirements-trace.md`, A1.11 and R17.3,
    R17.4, R17.6, R17.17. Change only the lines your finding needs.

## The rule

Take the findings in your batch file's order. Each gets exactly one outcome:

1. **fixed**: a test that fails on the code before your commit, then the fix, in one commit for the
    finding. Ask how the fault slipped past the tests; where a test of its whole class is small and
    natural, write that one. The requirement's text changes in the same commit when the record or
    the decision says it does, with its row in `docs/requirements-trace.md`. A rule the user or an
    app can observe (which folders are refused, what a tool is handed) belongs in the requirement
    that covers it, in the same commit: a rule that lives only in the code is a gap. Say each such
    sentence under **needs your eye**.
2. **no defect**: the finding does not reproduce. One tests-only commit shows the behaviour is right.
    List it with the evidence; the coordinator puts it on the issue.
3. **remedy changed**: the stated remedy is wrong, or an alternative fits better, and the choice is
    one between two ways to the same behaviour. Take it, say why in the commit, and list it.
4. **set aside**: fixing it needs a choice that is the owner's (new interface no requirement
    describes, a change to what a requirement asks). Make no commit for it. List it with the
    question, the options and what you would recommend; the coordinator gives it `refine`.
5. **still left**: anything of the batch you could not finish, with why.

**A new finding** (a fault no finding of this unit covers) is reported to the coordinator, who files
it with `.git/cr1-tools/new_finding.py`; you never file one. List it under **new** with its file,
line, the case that shows it and the severity you would give it. Fix it in this unit only when it is
small and in this unit's own files (U05's `files` in the schedule): then in a commit of its own,
whose first line names it as a new finding, listed with that commit. A High one goes first in your
final message too.

No fix carries logic for what an earlier AppKata version registered, stored or wrote: no one is
using AppKata yet.

**Begin every shell command with `cd` into this worktree**
(`cd /home/dev/kata/AppKata/.claude/worktrees/cr1-u05 && ...`). The session's working directory can
be moved under you between commands, and other checkouts of this repository are being worked in at
the same time: a `git` command run from the wrong folder would land in another unit's branch.

## What you may change

- **Only** the files your findings' records list, the tests that prove them, and
    `docs/relay/progress.md`. A new test goes in the existing test file the record names; a new test
    file also needs its line in `scripts/areas.py`. A launcher golden changes only through the
    project's own way of writing it again, never by hand.
- A test that only means anything on Linux gets its line in `tests/skips/windows.txt` (the file's
    own first lines say the form), in the same commit as the test, unless its file is listed there
    whole: a skip that file doesn't list fails the Windows run.
- Before each commit run the guard:
    `python3 -B agents/skills/review-triage/triage.py guard U05 --base origin/cr1-u04-downloads-checksums`
    (the base is `upstream/master` once U04 has merged). A file it says another unit claims: undo
    that change and list the finding as still left, with the file. A file it says to add to U05's
    files: keep it and list it under **guard**. It always names the files of `docs/relay/` as
    outside the plan: that is expected, and they are not listed.
- Never U04's files beyond what a merge conflict needs, never `docs/remediation/CR1-schedule.json`,
    never anything under `agents/` or `coworker/`, never another file of `docs/relay/`.
- The repository is public: no private project, account or domain name in code, comments or commit
    messages.
- Scratch files stay out of the repository. Use `python3 -B` for anything that imports from
    `agents/skills`, so no cache folder is left there.
- Never run one of the project's scripts to read its usage (no `--help`, no run without arguments):
    read the script. Some of them build, start VMs or delete what they find.

## Checks before you commit (all must pass)

1. The test files you touched, run whole, from this worktree's root, **in a scratch home**. Every
    test already has its own home (`tests/conftest.py`'s `own_home`), and a run fails if AppKata's
    files in the real home change; a batch keeps to its own all the same:

    ```
    S=$(mktemp -d /tmp/cr1-u05-home.XXXXXX) && mkdir -m 700 "$S/run" &&
    find /home/dev/bin /home/dev/.local/share/appkata /home/dev/.local/share/applications -printf '%M %s %T@ %p\n' | sort -k4 > "$S.before" &&
    HOME="$S" XDG_CONFIG_HOME="$S/.config" XDG_DATA_HOME="$S/.local/share" XDG_CACHE_HOME="$S/.cache" \
      XDG_STATE_HOME="$S/.local/state" XDG_RUNTIME_DIR="$S/run" \
      /home/dev/kata/AppKata/.venv/bin/python -m pytest -q -p no:cacheprovider <the files>;
    find /home/dev/bin /home/dev/.local/share/appkata /home/dev/.local/share/applications -printf '%M %s %T@ %p\n' | sort -k4 > "$S.after"; diff "$S.before" "$S.after"
    ```

    A line the `diff` shows goes under your doubts as it is; never remove or "fix" anything in the
    real home. For what `docs/testing.md` says needs it, the tier 1 container. Show each new test
    failing on the code before your fix (export the earlier commit with `git archive` to a scratch
    folder, put the new test file over it, and run it there, in the same scratch home).
2. **Tier 2**, for each finding whose proof names it: the launcher tests in the Linux Mint 22.3
    container, as `scripts/test-sandbox.sh launcher` runs them, on just the test files and cases
    your batch touched (pytest's `-k` or node ids), failing first on the earlier commit as above. The
    LMDE 7 image as well (`launcher-lmde7`) when your change is in the launcher's shell text.
3. The document checks:
    `/home/dev/kata/AppKata/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_public_text.py tests/test_doccheck.py tests/test_doc_links.py tests/test_docs_facts.py tests/test_requirements_trace.py tests/test_areas.py`
4. The guard, as above.

**A container run from this worktree** (tier 1, or tier 2's `appkata-sandbox-mint22.3` and
`appkata-sandbox-lmde7`): make the same `docker run` as the project's script (`scripts/test-tier1.sh`,
`scripts/test-sandbox.sh`'s `launcher` part, with its `OPEN` options and `/dev/fuse`) from a scratch
script outside the repository, with this worktree as `/src`, the main checkout's `build/` Python
and PySide6 (`/home/dev/kata/AppKata/build/python-3.14`, at `/src/build/python-3.14`) and its
`.git` mounted read-only at their own paths, and a 3 GB memory cap (`--memory 3g`). The images are
already built: never build one. Start no VM. A proof that needs a VM (`launcher-vm`, `launcher-vm26`,
a desktop VM) is listed under **needs a run**, with the exact command; the coordinator runs it. This
machine's limit is 10 GB of memory for all work together, and other units run beside this one: stay
under 3 GB. A command that takes over a minute runs in the background and you wait for its own
completion, never by a loop that searches the process list.

## Commit and report

1. Commit on `cr1-u05-sandbox-grants` (never push, never another branch, never amend or rebase):
    one commit per finding, the fix explained in its message, with the finding's number in its
    first line, ending with the line `Co-Authored-By: Claude Fable 5.2 <noreply@anthropic.com>`.
    Never set `user.name` or `user.email` and never pass `--no-gpg-sign`: let git sign it; if
    signing fails, stop and report.
2. Append to `docs/relay/progress.md`, under `## Batch N`, in a commit of its own at the end: the
    merge of U04's tip (its hash, or "up to date", and what was resolved); the files you touched;
    the counts (fixed, no defect, remedy changed, set aside, still left, new); for each finding its
    outcome, its commit and its test, and how the test was shown failing (tier 1 and tier 2); the
    listed items, each with its line; **needs your eye** (each commit that changes what the user
    sees or what a requirement says, in a line); **needs a run**; **guard**; **new**; the real
    home's `diff`; then your doubts for the coordinator.
3. Your final message to the coordinator: the commits' hashes, the counts and the doubts. Keep it
    short; the progress file holds the detail.

After your batch the coordinator checks it, pushes, and CI runs on that push (tier 1 in three parts,
the AppImage, the tour, Windows). A failure CI finds in a batch's commits is written at the top of
the next batch's section, and that batch fixes it first.

The machine is shared. Leave no process running when you finish.
