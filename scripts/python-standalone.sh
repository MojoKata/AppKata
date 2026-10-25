#!/bin/sh
# The Python every release carries (packaging/versions.env), for development, the tests and the
# field test (requirement 1.2): python-build-standalone of PY_SERIES unpacked to build/python-<series>
# with pytest, fetched once, and again when PYTHON_BUILD changes. Prints the path of its python3;
# progress goes to stderr.
set -eu
HERE=$(cd "$(dirname "$0")/.." && pwd)
. "$HERE/packaging/versions.env"
. "$HERE/scripts/lib-python.sh"
DEST="$HERE/build/python-$PY_SERIES"
PIN="$PY_SERIES from $PYTHON_BUILD"
# pytest and its dependencies, each pinned (tests/test_pinned_inputs.py)
PYTEST="pytest==9.1.1 iniconfig==2.3.1 packaging==26.3 pluggy==1.7.0 Pygments==2.21.0"
current() { [ -x "$DEST/python/bin/python3" ] && [ "$(cat "$DEST/.pin" 2>/dev/null)" = "$PIN" ]; }
if ! current; then
    # one at a time: the launcher tiers start together and each asks for it (flock, where present)
    mkdir -p "$HERE/build"
    exec 9>"$HERE/build/.python-$PY_SERIES.lock"
    command -v flock >/dev/null 2>&1 && flock 9
    if ! current; then
        fetch_python "$PY_SERIES" "$HERE/build/appimage-cache" >&2
        tmp=$(mktemp -d "$DEST.XXXXXX") && chmod 755 "$tmp"      # mktemp's 700 kept the containers' users out
        tar -xzf "$PYTHON_TARBALL" -C "$tmp"          # -> python/
        "$tmp/python/bin/python3" -m pip install -q --no-deps --disable-pip-version-check --no-warn-script-location $PYTEST >&2
        echo "$PIN" > "$tmp/.pin"
        rm -rf "$DEST" && mv "$tmp" "$DEST"
    fi
fi
echo "$DEST/python/bin/python3"
