#!/usr/bin/env bash
# AppKata sandbox field test -- run on a real, logged-in Linux desktop (Mint, Ubuntu, GNOME, KDE, ...)
# from a checkout of this repository. It installs a small probe app through AppKata's own install path
# and runs the launchers AppKata writes for it -- the code a user gets, not commands written by hand --
# answers what it can, asks the tester the few visual questions, and bundles the results to bring back.
# The work is scripts/sandbox/fieldtest.py; the checklist it follows is docs/local-proxy-test-plan.md.
#
# Usage:  scripts/sandbox/field-test.sh [--app /path/to/App.AppImage] [--non-interactive]
# Needs:  bwrap and xdg-dbus-proxy (it says so if sandboxing can't run here, and what to do), python3
#         with python3-gi for what the launchers run on the host, and the Python the release carries
#         (requirement 1.2): $APPKATA_PYTHON, else build/python-<series>, else fetched once;
#         gdbus, pactl, glxinfo, grim / ImageMagick's import widen what it can check.
# Safety: everything happens in a throwaway home it creates and removes; it never writes your real
#         home. (Review 2, D1: the script this replaces wrote a canary into the tester's real
#         ~/.ssh/id_ed25519 and then deleted that file.)
# Output: ./appkata-fieldtest-<host>-<date>/ (report.md, env.txt, logs, shots) and a .tar.gz of it.
set -u
HERE="$(cd "$(dirname "$0")/../.." && pwd)"
. "$HERE/packaging/versions.env"
# AppKata's own code on the Python its release carries, not this desktop's python3 (requirement 1.2;
# review 3, R3-21: Debian 12's 3.11.2 can't unpack a tarball the way AppKata does)
PY=${APPKATA_PYTHON:-$HERE/build/python-$PY_SERIES/python/bin/python3}
[ -x "$PY" ] || PY=$(sh "$HERE/scripts/python-standalone.sh") || { echo "couldn't fetch the Python AppKata runs on (above)" >&2; exit 1; }
exec env PYTHONPATH="$HERE/src" "$PY" "$HERE/scripts/sandbox/fieldtest.py" "$@"
