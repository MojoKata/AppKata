# Relay brief: CR1's unit U04, downloads, checksums and what App Detail says of them

Temporary: `docs/relay/` is deleted before this unit's pull request merges. Read this whole brief,
then `docs/relay/progress.md`, then your batch file. Nothing else from earlier agents.

## Goal

AppKata is the owner's own project, and CR1 is its own code review. The review's findings are GitHub
issues, and the owner approved a schedule of work units, one pull request each
(`docs/remediation/CR1-schedule.json`). This relay is the unit **U04, "Downloads, checksums and what
App Detail says of them"**: 15 findings, fixed in four batches by one agent at a time on the branch
`cr1-u04-downloads-checksums`, in the worktree `/home/dev/kata/AppKata/.claude/worktrees/cr1-u04`.
You fix your batch's findings in the owner's own code and prove each fix. You push nothing and write
nothing on GitHub.

| Batch | Findings | What |
|---|---|---|
| 1 | #306, #307, #628, #699 | the High finding: a release's file name, its version and the app's name as parts of a path |
| 2 | #465, #467, #466, #497 | the installed file's SHA-256, and what App Detail's chips and the review dialog say of it |
| 3 | #223, #318, #327 | what Verified means, and the file an administrator's command installs |
| 4 | #304, #328, #308, #314 | download() and the checksum fetch: which files, which URLs, which failures |

Your batch is one file, `docs/relay/batch-N.txt`. Its first lines say where its items came from. The
code at the head of `cr1-u04-downloads-checksums` is the code you work on: earlier batches' commits
are in it.

For each finding of your batch, read:

1. its record in `docs/remediation/CR1-schedule.json` (the file is 600 KB: take the record out with a
    short script, never read the file whole): its files, what it depends on, its proof and its note;
2. its issue: `gh issue view <n> -R MojoKata/AppKata --json title,body,comments`. Where the owner's
    decision is a comment or in the body, the decision is the remedy;
3. the code and the requirement sections it cites. The line numbers in the records and issues are of
    the code the review read; U01, U03, U07 and U09 have merged since, so find the code by its
    function's name (`install()`, `_place`, `_safe`, `download()`, `expected_sha256`, `detail()`).

`DEVELOP.md` and `docs/testing.md` say how this project's tests are run, and which need the tier 1
container. Load the `review-triage` skill and read its "What comes up mid-work": those standing
rules are the unit's, and this brief says below how a relay agent follows them.

**The batches run on Fable 5.2 at high effort** (the owner's word for this wave). An agent that finds
the worktree holding uncommitted changes it didn't make: they are a stopped agent's work on this
batch. Read them with `git diff`, keep what is right, finish it under the rules below, and say in
the progress section what was taken over. Never discard them with `git checkout` or `git restore`
without reading them first.

**U05 is stacked on this branch** (the owner's rule of 2026-11-25: a unit whose files overlap an
open unit's, a shared file included, starts on that unit's branch). U05 shares
`src/appkata/backend.py` and `src/appkata_core/install.py` with this unit, and its agents merge this
branch's pushed tip in before each of their batches. So a commit here is never rewritten, and each
finding stays in commits of its own: U05 builds on them as they are.

## What this unit's findings hold

- **Decided by the owner** (the decision is the remedy, in a comment or the body): #223, #308,
    #318, #327, #465, #466. The others' records say which remedy is taken.
- **Choices left out, a `refine` if wanted, never taken by a batch**: #318's fourth chip ("Adopted ·
    not checked") and refusing to adopt; #466's 32-digit shortened match; #304's SHA-512; #328's
    stopping the install. The records name them; take the remedy the record names.
- **Containers**: #318 and #327 are proven in the channels container (`scripts/test-channels.sh`);
    #465's App Detail screens change, which CI's tour job makes again.
- **The Windows VM, the coordinator's run**: #327's Windows half (an `.msi` and an `.exe` installer
    run from the all-users folder), #306's Startup-folder case and #628's portable `.exe` where a
    test under `OS="windows"` can't show them.
- **Needs your eye, already known**: #318's Unverified chip with the origin in its tooltip; #328's
    tooltip reason; #465's forecast chip words and R4.4's sentence; #466's R10.3.4 sentence and R10's
    example digest; #308's R4.4 transport rule; #327's R4.4, R15 and R16 sentences.
- **Shared files** (the schedule's `shared_files`: other units change them too): every file of this
    unit but `src/appkata/qml/PopMenu.qml`. Change only the lines your finding needs.

## The rule

Take the findings in your batch file's order. Each gets exactly one outcome:

1. **fixed**: a test that fails on the code before your commit, then the fix, in one commit for the
    finding. Ask how the fault slipped past the tests; where a test of its whole class is small and
    natural, write that one. The requirement's text changes in the same commit when the record or
    the decision says it does. A rule the user or a project can observe (which URLs a download may
    use, what a chip says) belongs in the requirement that covers it, in the same commit: a rule
    that lives only in the code is a gap. Say each such sentence under **needs your eye**.
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
small and in this unit's own files (U04's `files` in the schedule): then in a commit of its own,
whose first line names it as a new finding, listed with that commit. A High one goes first in your
final message too.

No fix carries logic for what an earlier AppKata version registered, stored or wrote: no one is
using AppKata yet.

**Begin every shell command with `cd` into this worktree**
(`cd /home/dev/kata/AppKata/.claude/worktrees/cr1-u04 && ...`). The session's working directory can
be moved under you between commands, and other checkouts of this repository are being worked in at
the same time: a `git` command run from the wrong folder would land in another unit's branch.

## What you may change

- **Only** the files your findings' records list, the tests that prove them, and
    `docs/relay/progress.md`. A new test goes in the existing test file the record names; a new test
    file also needs its line in `scripts/areas.py`.
- A test that only means anything on Linux gets its line in `tests/skips/windows.txt` (the file's
    own first lines say the form), in the same commit as the test: a skip that file doesn't list
    fails the Windows run.
- Before each commit run the guard:
    `python3 -B agents/skills/review-triage/triage.py guard U04 --base upstream/master`.
    A file it says another unit claims: undo that change and list the finding as still left, with
    the file. A file it says to add to U04's files: keep it and list it under **guard**.
    It always names the files of `docs/relay/` as outside the plan: that is expected, and they are
    not listed.
- Never `docs/remediation/CR1-schedule.json`, never anything under `agents/` or `coworker/`, never
    another file of `docs/relay/`.
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
    S=$(mktemp -d /tmp/cr1-u04-home.XXXXXX) && mkdir -m 700 "$S/run" &&
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
2. The document checks:
    `/home/dev/kata/AppKata/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_public_text.py tests/test_doccheck.py tests/test_doc_links.py tests/test_docs_facts.py tests/test_requirements_trace.py tests/test_areas.py`
3. The guard, as above.

**A container run from this worktree** (tier 1, or the channels container for #318 and #327): make
the same `docker run` as the project's script (`scripts/test-tier1.sh`, `scripts/test-channels.sh`)
from a scratch script outside the repository, with this worktree as the sources, the main checkout's
`build/` Python and PySide6 and its `.git` mounted read-only, and a 3 GB memory cap
(`--memory 3g`). The images are already built: never build one. Start no VM. A proof that needs the
Windows VM or a desktop VM is listed under **needs a run**, with the exact command; the coordinator
runs it. This machine's limit is 10 GB of memory for all work together, and other units run beside
this one: stay under 3 GB. A command that takes over a minute runs in the background and you wait
for its own completion, never by a loop that searches the process list.

## Commit and report

1. Commit on `cr1-u04-downloads-checksums` (never push, never another branch, never amend or
    rebase): one commit per finding, the fix explained in its message, with the finding's number in
    its first line, ending with the line `Co-Authored-By: Claude Fable 5.2 <noreply@anthropic.com>`.
    Never set `user.name` or `user.email` and never pass `--no-gpg-sign`: let git sign it; if
    signing fails, stop and report.
2. Append to `docs/relay/progress.md`, under `## Batch N`, in a commit of its own at the end: the
    files you touched; the counts (fixed, no defect, remedy changed, set aside, still left, new);
    for each finding its outcome, its commit and its test, and how the test was shown failing; the
    listed items, each with its line; **needs your eye** (each commit that changes what the user
    sees or what a requirement says, in a line); **needs a run**; **guard**; **new**; the real
    home's `diff`; then your doubts for the coordinator.
3. Your final message to the coordinator: the commits' hashes, the counts and the doubts. Keep it
    short; the progress file holds the detail.

After your batch the coordinator checks it, pushes, and CI runs on that push (tier 1 in three parts,
the AppImage, the tour, Windows). A failure CI finds in a batch's commits is written at the top of
the next batch's section, and that batch fixes it first.

The machine is shared. Leave no process running when you finish.
