#!/bin/sh
# Mutation testing (docs/testing.md, "Mutation testing"): scripts/mutate.py's commands that run
# mutmut, in tier 1's container, on the Python and the PySide6 the release carries
# (packaging/versions.env, R1.2), so a change is tested by the tests as tier 1 runs them.
#
#     sh scripts/test-mutate.sh run src/appkata_core/windows.py src/appkata/winframe.py [--workers N]
#     sh scripts/test-mutate.sh summary | export DIR --name N --area A --modules M | check CHANGE TEST
#
# mutmut and its dependencies (MUTMUT, packaging/versions.env) are installed once, beside PySide6,
# in build/mutmut-<hash>, which the container reads at /mutmut. The run's own files (a copy of the
# repository that mutmut changes, its mutants and its log) are in APPKATA_MUTATE_WORK, build/mutate
# by default, which the container writes at /work; the checkout itself is read-only to it, as to
# tier 1. APPKATA_MUTATE_MEMORY (6g by default) caps the container's memory, swap included.
set -eu
HERE=$(cd "$(dirname "$0")/.." && pwd)
. "$HERE/scripts/lib-tier1.sh"
tier1_setup "$HERE"
CPY="/src${PYT#"$HERE"}"
MUT="$HERE/build/mutmut-$(printf '%s %s' "$MUTMUT" "$PY_SERIES" | sha256sum | cut -c1-12)"
if [ ! -d "$MUT/mutmut" ]; then
    echo "== $MUTMUT for Python $PY_SERIES" >&2
    rm -rf "$MUT.part" && mkdir -p "$MUT.part"
    docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp -v "$HERE:/src:ro" -v "$MUT.part:/mutmut" "$IMG" \
        "$CPY" -m pip install -q --no-deps --disable-pip-version-check --target /mutmut $MUTMUT
    rm -rf "$MUT" && mv "$MUT.part" "$MUT"
fi
WORK=${APPKATA_MUTATE_WORK:-$HERE/build/mutate}
MEM=${APPKATA_MUTATE_MEMORY:-6g}
mkdir -p "$WORK"
# A worktree's .git names the repository's own, which the container reads at the same path, so the
# tests that ask git read the checkout as in a clone.
GITDIR=$HERE/.git
[ ! -f "$GITDIR" ] || GITDIR=$(cd "$HERE" && cd "$(git rev-parse --git-common-dir)" && pwd)
exec docker run --rm --init --user "$(id -u):$(id -g)" --memory="$MEM" --memory-swap="$MEM" \
    -e HOME=/tmp/home -e QT_QPA_PLATFORM=offscreen -e PYTHONDONTWRITEBYTECODE=1 -e APPKATA_MUTATE_WORK=/work \
    -v "$HERE:/src:ro" -v "$SITE:/site:ro" -v "$MUT:/mutmut:ro" -v "$WORK:/work" -v "$GITDIR:$GITDIR:ro" "$IMG" sh -c \
    'mkdir -p "$HOME" && cd /src && PYTHONPATH=/site:/mutmut exec '"$CPY"' scripts/mutate.py "$@"' sh "$@"
