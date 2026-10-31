# Follow-ups after the CI work: the demo Audit's days at any hour of the tour

The walk thru of 2026-10-30, item 3, decided **A**: the demo's Audit is pinned to the tour's
calendar, in the time zone the tour shows it in. Each entry of an earlier day is on its day at its
clock time; today's keep the newest half an hour back and move with the hour; before there is room
for them, `stage` stops.

## Results

| Pass | When | What it found | Where fixed | Tiers at the end |
|---|---|---|---|---|
| The harness, history at four hours in three zones | 2026-10-30 | C1 (it fails on the old script); nothing else | e8d195f | tier 1 2,456 passed; the full Linux tour, 89 screens; U01 on Linux and Windows |

## C1. The Audit screens group by day at the hour the tour runs — LOW (demo data, screenshots; noticed at the CI handoff) — fixed

`history()` (review 3, R3-25) wrote each entry a fixed time back from now, as if the tour ran at
13:00, so the newest was half an hour back at any hour. The Audit groups by the calendar day of the
machine showing it: UTC in the Linux tour's container, the VM's own zone on Windows. At 03:00 UTC
the Linux tour's U01 showed two entries under Today and today's other three under Yesterday, with
yesterday's under Thursday (seen at 03:07 UTC on 2026-10-31). The screens changed with the hour,
and Linux and Windows could disagree.

**How it slipped past.** R3-25's checks ask whether the entries are in order, none after now and
the newest within the last hours, and its test ran `stage` at whatever hour tier 1 ran: all true at
any hour. Nothing asked on which day each entry lands.

**The class:** a screen whose content depends on when the tour runs.

**The harness:** `tests/test_demo_promises.py::test_the_audit_groups_by_day_the_same_at_any_hour_of_the_tour`
runs `history` at 00:40, 03:00, 08:15 and 23:50, in UTC, UTC-7 and UTC+5:30: every entry must be on
the same day as at 13:00, in time order, the newest half an hour back; at 00:20 `stage` stops. It
fails on the old script. The other times the screens show are already staged as of now (R3-24: the
minimum age, the sync times), so nothing else in the class turned up.

**The fix:** `history(db, tz, now)`: earlier days' entries on their day at their clock time in `tz`;
today's moved so the newest is half an hour back, and squeezed in proportion between 00:01 and then
when the tour runs early in the day; stored in UTC as before. `stage DIR --utc-offset +HH:MM` gives
the zone: `test-layout.sh` passes `+00:00` (its container sets no TZ), `test-windows-vm.sh` the VM's
own (`(Get-Date).ToString('zzz')`).

## Fixes

| Commit | Fixes | What | Proof |
|---|---|---|---|
| e8d195f | C1 | `history(db, tz, now)`; `stage --utc-offset`; both tours pass their zone; the harness | U01 on Linux at 03:07 UTC: Today 5, Yesterday 3, the days before at their own times (the old staging at the same minute: Today 2, Yesterday 4); on Windows, the VM at 20:08 UTC-7, the same groups; the full Linux tour, 89 screens, every text inside its box |
| b275cfe | — | The test names its databases without a `:` | on Windows `0:00:00` read as a drive and the test failed; found running all eight follow-up branches merged on the Windows tier, which then passed |
