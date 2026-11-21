#!/bin/sh
# The demo data the Linux tour runs on, build/tour-data, as CI's tour job makes it
# (docs/github-workflows.md, "The tour"; scripts/demo_data.py):
#   - kept as it is when it's there (CI's cache brought it) and scripts/demo_data.py hasn't changed
#     since it was made;
#   - made again from its own synced Catalog when demo_data.py has (remake: no network, the same
#     releases, so the screens change only by what demo_data.py changed);
#   - else built and synced from GitHub (GITHUB_TOKEN, when set, for the API's own limit), and kept
#     only when its claims hold (demo_data.py check: what screenshots/README.md says each screen shows);
#   - and when that fails, made from the snapshot in tests/data/demo (restore: no network).
# Then scripts/test-layout.sh tours it.
#   scripts/tour-data.sh
set -eu
HERE=$(cd "$(dirname "$0")/.." && pwd)
TD="$HERE/build/tour-data"
STAMP="$TD/made-by.sha256"
DEMO="python3 $HERE/scripts/demo_data.py"
want=$(sha256sum "$HERE/scripts/demo_data.py" | cut -d' ' -f1)
mkdir -p "$HERE/build"
made() {
    echo "$want" > "$STAMP"
    echo "tour data: $1"
    # build's gpg-agent for the OpenPGP Trust's key folder: nothing needs it now
    GNUPGHOME="$TD/gnupg-mara" gpgconf --kill gpg-agent 2>/dev/null || true
}
warn() {
    echo "tour data: $1" >&2
    [ "${GITHUB_ACTIONS:-}" != true ] || echo "::warning title=tour data::$1"
}
if [ -f "$TD/appkata.db" ]; then
    if [ "$(cat "$STAMP" 2>/dev/null)" = "$want" ]; then
        made "as it was (made by this scripts/demo_data.py)"
        exit 0
    fi
    if $DEMO remake "$TD"; then
        made "made again from its own synced Catalog (remake)"
        exit 0
    fi
    warn "remake failed; syncing from GitHub instead"
fi
if $DEMO build "$TD" && $DEMO sync "$TD" && $DEMO finish "$TD" && $DEMO check "$TD"; then
    made "built and synced from GitHub"
    exit 0
fi
warn "the sync from GitHub failed or its data doesn't keep screenshots/README.md's claims (above): the tour runs on the snapshot in tests/data/demo"
$DEMO restore "$TD"
made "restored from the snapshot (tests/data/demo)"
