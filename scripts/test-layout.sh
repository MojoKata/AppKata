#!/bin/sh
# The screenshot tour on the demo data, in tier 1's container, checking that no screen draws a text
# outside its card, chip or dialog (src/appkata/layout.py; review 3, R3-22). Both themes unless
# APPKATA_TOUR_THEMES says otherwise; extra args go to the tour (--tour-only A01-apps,C10-install-channels).
# It runs on build/tour-data itself (scripts/demo_data.py), at the same path: the paths it shows are
# part of what is laid out. The screens, at the design point (R5.2.1), go to
# build/layout-tour/{dark,light}: CI's tour job makes them on each run and publishes master's on the
# Pages site (docs/github-workflows.md, "The tour").
# APPKATA_TOUR_OFFSET=+HH:MM is the tour's time zone, UTC by default and an hour behind it in the
# first hour of a UTC day, whose Audit has no room yet (demo_data.py offset, stage).
#   scripts/test-layout.sh [--tour-only NAMES]
set -eu
HERE=$(cd "$(dirname "$0")/.." && pwd)
"$HERE/coworker/bin/deps" register "$HERE"   # the coworker protocol (the coworker/ submodule, MojoKata/coworker): remembers AppKata, mentions what the host lacks
[ "${1:-}" != --shots ] || { echo "test-layout.sh: --shots is gone: screenshots/linux left the tree; the screens are in build/layout-tour (docs/build.md)" >&2; exit 2; }
OFF=${APPKATA_TOUR_OFFSET:-}
[ -n "$OFF" ] || OFF=$(python3 "$HERE/scripts/demo_data.py" offset)
case $OFF in [+-][0-9][0-9]:[0-9][0-9]) ;; *) echo "APPKATA_TOUR_OFFSET is +HH:MM or -HH:MM, not $OFF" >&2; exit 2 ;; esac
# the same zone for the container, as POSIX writes it: the sign turned round, the name in <>
TZ_POSIX="<$(echo "$OFF" | tr -d :)>$(echo "$OFF" | tr '+-' '-+')"
. "$HERE/scripts/lib-tier1.sh"
tier1_setup "$HERE"
TD="$HERE/build/tour-data"
[ -f "$TD/appkata.db" ] || { echo "no demo data in $TD: see docs/build.md (scripts/demo_data.py)" >&2; exit 1; }
# the minimum age and the sync times, as of now (R3-24); the Audit's days in the tour's time zone,
# which its container gets as TZ
python3 "$HERE/scripts/demo_data.py" stage "$TD" --utc-offset "$OFF"
python3 "$HERE/scripts/demo_data.py" check "$TD"      # no failed sync, and what screenshots/README.md says each screen shows
OUT="$HERE/build/layout-tour"
rm -rf "$OUT" && mkdir -p "$OUT"
set +e
# this machine's home, so the paths the screens show read as here (~/kata/AppKata/build/tour-data/...);
# nothing is written there: the caches and settings go to /tmp
docker run --rm --user "$(id -u):$(id -g)" -e HOME="$HOME" -e XDG_CACHE_HOME=/tmp/cache -e XDG_CONFIG_HOME=/tmp/config \
    -e TZ="$TZ_POSIX" -e QT_QPA_PLATFORM=offscreen -e PYTHONDONTWRITEBYTECODE=1 \
    -e APPKATA_TOUR_THEMES="${APPKATA_TOUR_THEMES:-dark,light}" -e APPKATA_DATA="$TD" -e XDG_DATA_HOME="$TD/xdg" \
    -v "$HERE:$HERE" -v "$SITE:/site:ro" -v "$OUT:/out" "$IMG" sh -c \
    'cd "$1" && shift && PYTHONPATH="$PWD/src:/site" exec "$@"' sh "$HERE" "$PYT" -m appkata --tour /out "$@" \
    > "$OUT/tour.log" 2>&1
RC=$?
# The first start, from an empty database: what every new user sees first, before any sync (tour.py's
# FRESH; review 3, R3-36). A home of its own in the container, empty but for the AppImage just
# downloaded, which AppKata adopts; its screens join the others.
if [ "$RC" = 0 ]; then
    mkdir -p "$OUT/fresh"
    V=$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$HERE/src/appkata_core/__init__.py")
    docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp/fresh -e TZ="$TZ_POSIX" \
        -e QT_QPA_PLATFORM=offscreen -e PYTHONDONTWRITEBYTECODE=1 -e APPKATA_TOUR_FRESH=1 \
        -e APPKATA_TOUR_THEMES="${APPKATA_TOUR_THEMES:-dark,light}" -e APPIMAGE="/tmp/fresh/Downloads/AppKata-$V-x86_64.AppImage" \
        -v "$HERE:$HERE" -v "$SITE:/site:ro" -v "$OUT/fresh:/out" "$IMG" sh -c \
        'mkdir -p /tmp/fresh/Downloads && : > "$APPIMAGE" && cd "$1" && shift && PYTHONPATH="$PWD/src:/site" exec "$@"' sh "$HERE" "$PYT" -m appkata --tour /out "$@" \
        >> "$OUT/tour.log" 2>&1
    RC=$?
    cat "$OUT/fresh/layout.txt" >> "$OUT/layout.txt" 2>/dev/null || true
    for t in dark light; do [ ! -d "$OUT/fresh/$t" ] || { mkdir -p "$OUT/$t" && mv "$OUT/fresh/$t"/*.png "$OUT/$t/"; }; done
    rm -rf "$OUT/fresh"
fi
set -e
grep '^layout (listed)' "$OUT/tour.log" || true
N=$(find "$OUT" -name '*.png' | wc -l)
if [ "$RC" = 0 ]; then
    echo "$N screens: every text inside its box (build/layout-tour/{dark,light})"
else
    echo "the tour exited $RC after $N screens (build/layout-tour/tour.log)"
    [ ! -s "$OUT/layout.txt" ] || cat "$OUT/layout.txt"
    exit 1
fi
