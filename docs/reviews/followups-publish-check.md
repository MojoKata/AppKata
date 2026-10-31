# Follow-ups after the CI work: what `publish.sh check` says when it can't read

The walk thru of 2026-10-30, item 5 (a clear fix): `scripts/publish.sh check` prints only
"(can't read)" where GitHub refuses a read. Only members without admin rights see it: the owner,
an admin, reads everything; the check is also for anyone else who wants to see how the repository
stands.

## Results

| Pass | When | What it found | Where fixed | Tiers at the end |
|---|---|---|---|---|
| The harness, a refusing `gh` | 2026-10-30 | P1, P2 | 3acb480 | — |
| `check` against MojoKata as a read-only member | 2026-10-30 | P3 | 8063434 | tier 1 2,456 passed; `check` as a read-only member: no JSON, every line; as the fork's admin: the real values |

## P1. A refused read prints the API's error JSON as its value — LOW (output; noticed at the CI handoff) — fixed

`api()` ran `gh api ... 2>/dev/null || echo "(can't read)"`. When GitHub refuses a read, gh prints
the API's error JSON on stdout and exits 1, so the line read
`FAIL  workflow token: {"message":"Must have admin rights to Repository.",...}(can't read)`.

**How it slipped past.** `check` was run as the fork's admin, where every read succeeds, and once
against MojoKata as a read-only member, where the lines were read past as "can't read".

**The class:** a command's refusal taken as its answer.

**The harness:** `tests/test_publish.py::test_check_says_it_cant_read_what_github_refuses_and_goes_on`
runs `check` with a `gh` on the PATH that refuses every read the way GitHub does (the error JSON on
stdout, exit 1): every line must say "(can't read)", nothing else, through to the last.

## P2. A refused read of the rulesets ends the check — LOW (found by the harness) — fixed

`id=$(ruleset_id master)` failed under `set -e`, so `check` stopped after three lines with gh's
error, and the settings after the rulesets were never read. In `setup`, `[ -n "$(ruleset_id tags)" ]`
took the error JSON for a ruleset that is there. `ruleset_id` now fails when the rulesets can't be
read: `check` says "(can't read)" and goes on, `setup` stops and says so. The release environment's
line likewise said "missing" for any failed read; it now reads the environments list, and says
"(can't read)" when that is refused.

## P3. What GitHub leaves out for a non-admin reads as a wrong value — LOW (found running check as a read-only member) — fixed

Two reads succeed for a member without admin rights but leave out what only an admin may read:
the merge methods (`null null null`) and a ruleset's bypass list (no `bypass_actors`, which read as
`0`). Both lines said FAIL with a value that wasn't the repository's. Both now say "(can't read)".

## Fixes

| Commit | Fixes | What | Proof |
|---|---|---|---|
| 3acb480 | P1, P2 | `api()` keeps gh's output only when it succeeds; `ruleset_id` fails on a refused read, `check` goes on, `setup` stops; the environment and secrets lines | the test fails on the old script (JSON in the output, three lines, then gh's error) and passes |
| 8063434 | P3 | the merge methods and the bypass lists say "(can't read)" when GitHub leaves them out | as a read-only member both say "(can't read)"; as the fork's admin `true true true`, and `admins bypass: 1` with a throwaway tags ruleset, deleted after |
