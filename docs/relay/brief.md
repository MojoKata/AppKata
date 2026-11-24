# Relay brief: CR1's unit U03, the portable install

Temporary: `docs/relay/` is deleted before this unit's pull request merges. Read this whole brief,
then `docs/relay/progress.md`, then your batch file. Nothing else from earlier agents.

## Goal

AppKata is the owner's own project, and CR1 is its own code review. The review's findings are GitHub
issues, and the owner approved a schedule of work units, one pull request each
(`docs/remediation/CR1-schedule.json`). This relay is the unit **U03, "The portable install: layout,
command links and menu entries"**: 17 findings (16, and one found by batch 1), fixed in four batches by one agent at a time on the
branch `cr1-u03-portable-install`. You fix your batch's findings in the owner's own code and prove
each fix. You push nothing and write nothing on GitHub.

| Batch | Findings | What |
|---|---|---|
| 1 | #305, #407, #388 | the two High findings, and the launcher files #407 and #388 share |
| 2 | #313, #309, #331, #312, #688 | the command link and the menu entry, and one finding batch 1 found |
| 3 | #310, #311, #336, #156 | folders and versions through an update |
| 4 | #315, #319, #329, #317, #661 | the program that is picked and started, and what kind of app it is |

Your batch is one file, `docs/relay/batch-N.txt`. Its first lines say where its items came from. The
code at the head of `cr1-u03-portable-install` is the code you work on: earlier batches' commits are
in it.

For each finding of your batch, read:

1. its record in `docs/remediation/CR1-schedule.json` (the file is 600 KB: take the record out with a
    short script, never read the file whole): its files, what it depends on, its proof and its note;
2. its issue: `gh issue view <n> -R MojoKata/AppKata --json title,body,comments`. Where the owner's
    decision is a comment or in the body, the decision is the remedy;
3. the code and the requirement sections it cites.

`DEVELOP.md` and `docs/testing.md` say how this project's tests are run, and which need the tier 1
container. Load the `review-triage` skill and read its "What comes up mid-work": those standing
rules are the unit's, and this brief says below how a relay agent follows them.

## The rule

Take the findings in your batch file's order. Each gets exactly one outcome:

1. **fixed**: a test that fails on the code before your commit, then the fix, in one commit for the
    finding. Ask how the fault slipped past the tests; where a test of its whole class is small and
    natural, write that one. The requirement's text changes in the same commit when the record or
    the decision says it does. A rule the user or a project can observe belongs in the
    requirement that covers it, in the same commit: a rule that lives only in the code is a gap.
    Say each such sentence under **needs your eye**.
2. **no defect**: the finding does not reproduce. One tests-only commit shows the behaviour is right.
    List it with the evidence; the coordinator puts it on the issue.
3. **remedy changed**: the stated remedy is wrong, or an alternative fits better, and the choice is
    one between two ways to the same behaviour. Take it, say why in the commit, and list it.
4. **set aside**: fixing it needs a choice that is the owner's (new interface no requirement
    describes, a change to what a requirement asks). Make no commit for it. List it with the
    question, the options and what you would recommend.
5. **still left**: anything of the batch you could not finish, with why.

A fault you find that no finding covers: fix it in the same commit only when it is small and in the
file you are already changing for that finding, and say so in the commit. Otherwise list it under
**new** with its file, line and case; the coordinator files it.

No fix carries logic for what an earlier AppKata version registered, stored or wrote: no one is
using AppKata yet.

## What you may change

- **Only** the files your findings' records list, the tests that prove them, and
    `docs/relay/progress.md`. A new test goes in the existing test file the record names; a new test
    file also needs its line in `scripts/areas.py`.
- Before each commit run the guard: `python3 -B agents/skills/review-triage/triage.py guard U03 --base upstream/master`.
    A file it says another unit claims: undo that change and list the finding as still left, with
    the file. A file it says to add to U03's files: keep it and list it under **guard**.
    It always names the files of `docs/relay/` as outside the plan: that is expected, and they are
    not listed.
- Never `docs/remediation/CR1-schedule.json`, never anything under `agents/` or `coworker/`, never
    another file of `docs/relay/`.
- The repository is public: no private project, account or domain name in code, comments or commit
    messages.
- Scratch files stay out of the repository. Use `python3 -B` for anything that imports from
    `agents/skills`, so no cache folder is left there.

## Checks before you commit (all must pass)

1. The test files you touched, run whole, from this worktree's root:
    `/home/dev/kata/AppKata/.venv/bin/python -m pytest -q <the files>`; and for what `docs/testing.md`
    says needs it, the tier 1 container. Show each new test failing on the code before your fix
    (export the earlier commit with `git archive` to a scratch folder and run the test file there).
2. `/home/dev/kata/AppKata/.venv/bin/python -m pytest -q tests/test_public_text.py tests/test_doccheck.py tests/test_doc_links.py tests/test_areas.py`
3. The guard, as above.

A container run from this worktree: the worktree has no `build/`, so make the same `docker run`
as the project's script from a scratch script outside the repository, with the main checkout's
`build/` Python and PySide6 and its `.git` mounted read-only and a 3 GB memory cap, as batch 1 did
(its doubt 7 in the progress file). Start no VM. A proof that needs the Windows VM or a desktop VM is listed under **needs a run**, with
the exact command; the coordinator runs it. This machine's limit is 10 GB of memory for all work
together, and other units run beside this one: stay under 3 GB. A command that takes over a minute
runs in the background and you wait for its own completion.

## Commit and report

1. Commit on `cr1-u03-portable-install` (never push, never another branch, never amend or rebase):
    one commit per finding, the fix explained in its message, with the finding's number in its
    first line, ending with the line `Co-Authored-By: Claude Fable 5.2 <noreply@anthropic.com>`.
    Never set `user.name` or `user.email` and never pass `--no-gpg-sign`: let git sign it; if
    signing fails, stop and report.
2. Append to `docs/relay/progress.md`, under `## Batch N`, in a commit of its own at the end: the
    files you touched; the counts (fixed, no defect, remedy changed, set aside, still left, new);
    for each finding its outcome, its commit and its test, and how the test was shown failing; the
    listed items, each with its line; **needs your eye** (each commit that changes what the user
    sees or what a requirement says, in a line); **needs a run**; **guard**; then your doubts for
    the coordinator.
3. Your final message to the coordinator: the commits' hashes, the counts and the doubts. Keep it
    short; the progress file holds the detail.

The machine is shared. Leave no process running when you finish.
