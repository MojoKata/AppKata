#!/bin/sh
# Tier 1 -- the whole local suite (tests/) -- in a container, on the Python and the PySide6 the
# release carries (packaging/versions.env, requirement 1.2), whatever this machine has: PySide6 6.10
# and later need glibc 2.34, which a RHEL 8 host lacks. Extra args go to pytest. The environment
# can override PY_SERIES and PYSIDE to try others. A skip tests/skips/tier1.txt doesn't list fails the
# run (tests/conftest.py).
#
# When and where it runs (scripts/test-clock.sh; issue #13, tests that passed or failed by the hour):
# APPKATA_CLOCK=HH:MM (the next time it's that, UTC) or 'YYYY-MM-DD HH:MM' (in the future) moves every
# process's clock there (libfaketime, by an offset: the clock still runs, and the processes the tests
# start share it); APPKATA_TZ=a POSIX TZ ('XST-14' is UTC+14) sets the time zone, UTC otherwise.
set -eu
HERE=$(cd "$(dirname "$0")/.." && pwd)
CW=${COWORKER_HOME:-$HOME/coworker}   # the coworker protocol (MojoKata/coworker): remembers AppKata, mentions what the host lacks
[ -x "$CW/bin/deps" ] || { echo "coworker isn't installed in $CW: run install.sh from a checkout of MojoKata/coworker" >&2; exit 1; }
"$CW/bin/deps" register "$HERE"
. "$HERE/scripts/lib-tier1.sh"
tier1_setup "$HERE"
CPY="/src${PYT#"$HERE"}"
FAKETIME=
if [ -n "${APPKATA_CLOCK:-}" ]; then
    now=$(date -u +%s)
    case $APPKATA_CLOCK in
        *-*) to=$(date -u -d "$APPKATA_CLOCK" +%s) ;;
        *) to=$(date -u -d "$(date -u +%F) $APPKATA_CLOCK" +%s) && { [ "$to" -gt "$now" ] || to=$((to + 86400)); } ;;
    esac || { echo "test-tier1.sh: APPKATA_CLOCK=$APPKATA_CLOCK isn't a time" >&2; exit 2; }
    # ahead only: libfaketime moves the monotonic clock too, which mustn't go below zero
    [ "$to" -gt "$now" ] || { echo "test-tier1.sh: APPKATA_CLOCK=$APPKATA_CLOCK is in the past" >&2; exit 2; }
    FAKETIME=+$((to - now))
    echo "== the clock at $(date -u -d "@$to" '+%Y-%m-%d %H:%M') UTC${APPKATA_TZ:+, TZ=$APPKATA_TZ}" >&2
fi
export FAKETIME APPKATA_TZ="${APPKATA_TZ:-}"
exec docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp/home -e QT_QPA_PLATFORM=offscreen -e PYTHONDONTWRITEBYTECODE=1 \
    -e APPKATA_SKIPS="${APPKATA_SKIPS-tier1}" -e FAKETIME -e APPKATA_TZ \
    -v "$HERE:/src:ro" -v "$SITE:/site:ro" "$IMG" sh -c \
    'if [ -n "$FAKETIME" ]; then export LD_PRELOAD=/usr/lib/x86_64-linux-gnu/faketime/libfaketime.so.1; else unset FAKETIME; fi
    if [ -n "$APPKATA_TZ" ]; then export TZ="$APPKATA_TZ"; fi
    mkdir -p "$HOME" && cd /src && echo "Python $('"$CPY"' -c "import sys; print(sys.version.split()[0])"), PySide6 $(PYTHONPATH=/site '"$CPY"' -c "import PySide6; print(PySide6.__version__)")" && PYTHONPATH=/src/src:/site exec '"$CPY"' -m pytest -q -p no:cacheprovider tests/ "$@"' sh "$@"
