# Follow-ups after the CI work: `demo_data.py remake` and the apps the build no longer lists

The walk thru of 2026-10-30, item 7 (a clear fix): `scripts/demo_data.py remake` keeps only the apps
the new build lists.

## Results

| Pass | When | What it found | Where fixed | Tiers at the end |
|---|---|---|---|---|
| The harness, `tests/test_demo_remake.py` | 2026-10-30 | D1 (all three tests fail on the old script); nothing else | d4ad0e4 | tier 1 2,458 passed; `remake` on copies of `build/tour-data` |

## D1. `remake` keeps the Catalog rows of apps no list names — LOW (demo data; noticed at the CI handoff) — fixed

`remake` builds the demo data again and copies the synced Catalog over from the old data, so the
screens keep their releases without the network. It copied every row of `apps` and `app_meta`. An
app taken off build's lists (a Source, a Trust's table) kept its row, with nothing naming it. Shown
on a copy of `build/tour-data` with a row added for `https://github.com/gone/app`: after `remake` it
was still in both tables.

**How it slipped past.** `remake` was checked by comparing a remade copy with the data it came from,
table by table (review 3, 419cacb). With the same lists on both sides, copying every row and copying
the listed rows give the same tables.

**The class:** a rebuild that merges the old state into the new, and keeps what the new one dropped.

**The harness:** `tests/test_demo_remake.py`: `carry_over` with an old database that has rows for
listed apps and for a dropped Source and a dropped Trust entry, and a new one listing fewer: only the
listed rows come over, with their releases. An app the new build lists that the old data never
synced is named. `remake` copies rows only through `carry_over`, and stops on such an app, the data
as it was. All three fail on the old script. Nothing else in `remake` carries rows over: the
Sources' forge goes by the new build's Sources, the Audit is written again by `stage`.

**The fix:** `carry_over` takes `sync.catalog_urls`, the Catalog's own list of what a sync fetches,
as what may come over. An app the build now lists that the old data has no row for can't be fetched
without the network, so `remake` stops, names it and says to run `sync`, and puts the old data back.

## Fixes

| Commit | Fixes | What | Proof |
|---|---|---|---|
| d4ad0e4 | D1 | `carry_over`: the rows of the apps `sync.catalog_urls` lists; `remake` stops on a listed app never synced | with a row added for an app no list names, the old `remake` kept it, the new drops it (14 apps left, all listed); with Zettlr's row taken out, `remake` exits 1 naming it, the database unchanged, no `.old` left |
