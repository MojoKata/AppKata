# Issue #13: tests that passed or failed by the hour tier 1 ran

Found on 2026-11-01 while running every `publish.sh` step on a test copy of the repository for
issue #12: the `v0.1.0` tag's run started at 00:25 UTC, tier 1 failed, and the release wasn't
signed. Then `resume`, after the failed job was run again, stopped short of showing what CI built.

## Results

| Pass | When | What it found | Where fixed | Tiers at the end |
|---|---|---|---|---|
| The harness, `scripts/test-clock.sh`: tier 1 at seven times and zones | 2026-11-01 | K1 (2 failed at 00:05 UTC, on master's tests); nothing else at any of the seven | 0d070d4 | tier 1 2,490 passed at all seven |
| `resume`, a fake `gh` with one to three attempts; the real run's attempts | 2026-11-01 | K2 (the old code fails both carried-over cases) | ad0ecb1 | `tests/test_publish.py` 11 passed |

## K1. Two demo tests fail from 00:00 to 00:36 UTC — MEDIUM (a release tagged then isn't signed) — fixed

`test_stage_holds_the_newest_release_with_days_to_go` and
`test_stage_writes_the_audit_in_time_order_ending_before_now` (`tests/test_demo_promises.py`) staged a
tour in UTC at the real hour. Since #10, `stage` stops while the tour's day has no room for today's
Audit entries (before 00:40 there; [`followups-audit-calendar.md`](followups-audit-calendar.md)), so
both failed whenever tier 1 ran in that half hour: on CI, every run then, a `v*` tag's included.
That's 6:00–6:36 PM in Chicago in winter.

**How it slipped past.** #10's harness ran `history()` at fixed hours, the refusal at 00:20
included, but these two older tests read the real clock, and every run of tier 1, by hand or on CI,
ran at whatever hour it was. None had run in that half hour since #10 merged.

**The class:** a test whose result depends on when, or in which time zone, it runs.

**The harness:** `scripts/test-tier1.sh` takes `APPKATA_CLOCK` and `APPKATA_TZ`: libfaketime, in tier
1's image, moves the clock of every process by an offset (so the processes the tests start share
it, and it still runs). `scripts/test-clock.sh` runs the whole of tier 1 at 00:05, 00:39, 12:00 and
23:58 UTC, on December 31 at 23:58, at local 00:05 in UTC+14 and at local 23:58 in UTC-12. On master's
tests: 2 failed at 00:05 UTC (these two), 2,490 passed at the other six. Nothing else in the class.

**The fix:** both tests stage the tour where it's about noon as they run (UTC-11 to UTC+12), so the
Audit always has room. They test the minimum age, the sync times and the Audit's order "whatever the
hour", and the UTC hour those use is still whatever it is. The refusal itself stays checked at 00:20
by `test_the_audit_groups_by_day_the_same_at_any_hour_of_the_tour`.

## K2. `resume` after `gh run rerun --failed` finds no SHA-256s — LOW (it stops; nothing wrong is signed) — fixed

After the failed tier 1 job was run again with `gh run rerun RUN --failed`, `resume` stopped: "the
run's build jobs posted no sha256 notices". GitHub carries the build jobs that passed into the new
attempt as new jobs (new IDs, the old finish times) without their annotations, and `resume` read
only the latest attempt's. Running the whole run again worked.

**The class:** a step that reads what a job wrote only from the run's latest attempt. `resume` is
the only reader of annotations in `publish.sh`.

**The fix and its test:** `resume` reads each build job's notice from the newest attempt that has
one. `test_resume_shows_what_ci_built_after_any_rerun` gives it a fake `gh` with one to three
attempts and the notices in the first, the latest, or none. The old code fails the two carried-over
cases. On the real run, attempt 2's jobs have no notice, and the lookup finds attempt 1's. What
`resume` shows is checked against the draft's files once they're signed, as before.

## Fixes

| Commit | Fixes | What | Proof |
|---|---|---|---|
| d6b8e2d | — | The harness: `APPKATA_CLOCK`, `APPKATA_TZ`, libfaketime in tier 1's image, `scripts/test-clock.sh` | on master's tests, 2 failed at 00:05 UTC, nothing else at the seven |
| 0d070d4 | K1 | The two tests stage a tour where it's noon | `test-clock.sh`: 2,490 passed at all seven |
| ad0ecb1 | K2 | `resume` reads each notice from the attempt that built the file | the new test (the old code fails 2 of 5); the real run's attempts |
