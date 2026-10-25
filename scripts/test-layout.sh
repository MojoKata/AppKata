#!/bin/sh
# The screenshot tour on the demo data, in tier 1's container, checking that no screen draws a text
# outside its card, chip or dialog (src/appkata/layout.py; review 3, R3-22). Both themes unless
# APPKATA_TOUR_THEMES says otherwise; extra args go to the tour (--tour-only A01-apps,C10-install-channels).
# It runs on build/tour-data itself (scripts/demo_data.py), at the same path: the paths it shows are
# part of what is laid out. The screens, at the design point (requirement 5.2.1), go to
# build/layout-tour; with --shots, a passing tour also replaces screenshots/linux/{dark,light}.
#   scripts/test-layout.sh [--shots] [--tour-only NAMES]
set -eu
HERE=$(cd "$(dirname "$0")/.." && pwd)
SHOTS=0
[ "${1:-}" != --shots ] || { SHOTS=1; shift; }
. "$HERE/scripts/lib-tier1.sh"
tier1_setup "$HERE"
TD="$HERE/build/tour-data"
[ -f "$TD/appkata.db" ] || { echo "no demo data in $TD: see docs/build.md (scripts/demo_data.py)" >&2; exit 1; }
python3 "$HERE/scripts/demo_data.py" stage "$TD"      # the minimum age and the sync times, as of now (R3-24)
python3 "$HERE/scripts/demo_data.py" check "$TD"      # no failed sync, and what screenshots/README.md says each screen shows
OUT="$HERE/build/layout-tour"
rm -rf "$OUT" && mkdir -p "$OUT"
set +e
# this machine's home, so the paths the screens show read as here (~/appkata/build/tour-data/...);
# nothing is written there: the caches and settings go to /tmp
docker run --rm --user "$(id -u):$(id -g)" -e HOME="$HOME" -e XDG_CACHE_HOME=/tmp/cache -e XDG_CONFIG_HOME=/tmp/config \
    -e QT_QPA_PLATFORM=offscreen -e PYTHONDONTWRITEBYTECODE=1 \
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
    docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp/fresh \
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
    echo "$N screens: every text inside its box"
    if [ "$SHOTS" = 1 ]; then
        for t in dark light; do
            [ "$#" -gt 0 ] || rm -rf "$HERE/screenshots/linux/$t"      # the whole tour: what it no longer takes goes
            [ ! -d "$OUT/$t" ] || { mkdir -p "$HERE/screenshots/linux/$t" && cp "$OUT/$t"/*.png "$HERE/screenshots/linux/$t/"; }
        done
        echo "saved screenshots/linux/{dark,light}"
    fi
else
    echo "the tour exited $RC after $N screens (build/layout-tour/tour.log)"
    [ ! -s "$OUT/layout.txt" ] || cat "$OUT/layout.txt"
    exit 1
fi
