#!/bin/sh
# Tier 1 at the times and in the time zones where a test that reads the clock goes wrong: the start
# of the UTC day (the demo's Audit has no room for today's entries before 00:40), its end, a year's
# end, and the zones furthest from UTC either way. Issue #13: two tests passed or failed by the hour
# CI ran them, and a release tagged in the wrong half hour wasn't signed. Each run is
# scripts/test-tier1.sh with APPKATA_CLOCK and APPKATA_TZ; extra args go to pytest. About 1.5
# minutes a run. Exits 1 if any run fails, after all of them.
set -u
HERE=$(cd "$(dirname "$0")/.." && pwd)
YEAR_END="$(date -u +%Y)-12-31 23:58"
[ "$(date -u +%s)" -lt "$(date -u -d "$YEAR_END" +%s)" ] || YEAR_END="$(($(date -u +%Y) + 1))-12-31 23:58"
FAILED=
run() {     # CLOCK TZ [PYTEST ARGS]
    clock=$1 tz=$2 log=$(mktemp)
    shift 2
    APPKATA_CLOCK=$clock APPKATA_TZ=$tz sh "$HERE/scripts/test-tier1.sh" "$@" >"$log" 2>&1
    rc=$?
    printf '%-18s %-8s %s\n' "$clock" "${tz:-UTC}" "$(grep -E '^[0-9]+ (passed|failed)|^=+ .*(passed|failed)' "$log" | tail -1 | tr -d '=')"
    [ "$rc" = 0 ] || { FAILED=1; grep -E '^(FAILED|ERROR) ' "$log" | sed 's/^/    /'; }
    rm -f "$log"
}
for t in 00:05 00:39 12:00 23:58 "$YEAR_END"; do run "$t" "" "$@"; done
run 10:05 XST-14 "$@"      # UTC+14: 00:05 tomorrow there
run 11:58 YST12 "$@"       # UTC-12: 23:58 yesterday there
[ -z "$FAILED" ]
