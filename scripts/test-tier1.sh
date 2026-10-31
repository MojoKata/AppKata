#!/bin/sh
# Tier 1 -- the whole local suite (tests/) -- in a container, on the Python and the PySide6 the
# release carries (packaging/versions.env, requirement 1.2), whatever this machine has: PySide6 6.10
# and later need glibc 2.34, which a RHEL 8 host lacks. Extra args go to pytest. The environment
# can override PY_SERIES and PYSIDE to try others. A skip tests/skips/tier1.txt doesn't list fails the
# run (tests/conftest.py).
set -eu
HERE=$(cd "$(dirname "$0")/.." && pwd)
. "$HERE/scripts/lib-tier1.sh"
tier1_setup "$HERE"
CPY="/src${PYT#"$HERE"}"
exec docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp/home -e QT_QPA_PLATFORM=offscreen -e PYTHONDONTWRITEBYTECODE=1 \
    -e APPKATA_SKIPS="${APPKATA_SKIPS-tier1}" \
    -v "$HERE:/src:ro" -v "$SITE:/site:ro" "$IMG" sh -c \
    'mkdir -p "$HOME" && cd /src && echo "Python $('"$CPY"' -c "import sys; print(sys.version.split()[0])"), PySide6 $(PYTHONPATH=/site '"$CPY"' -c "import PySide6; print(PySide6.__version__)")" && PYTHONPATH=/src/src:/site exec '"$CPY"' -m pytest -q -p no:cacheprovider tests/ "$@"' sh "$@"
