#!/bin/sh
# Reads the text in every committed screenshot (screenshots/**/*.png) with tesseract, in a container,
# and fails if any of it is a private name (scripts/public_text.py) or the repository address isn't
# AppKata's own (APPKATA_REPO). Run it after the screenshots are made again (test-windows-vm.sh
# --shots, screenshots/src/render.js), and on a Linux tour before it goes anywhere (CI's tour job runs
# it on build/layout-tour): tests/test_public_text.py reads only text files. About 5 minutes for the
# ~190 committed screens, 2 for a Linux tour's; the text read goes to build/screenshot-text/.
#   scripts/test-screenshot-text.sh [PATH...]     only these screenshots (paths under the checkout)
set -eu
HERE=$(cd "$(dirname "$0")/.." && pwd)
OUT="$HERE/build/screenshot-text"
. "$HERE/packaging/versions.env"
# tesseract on tier 1's pinned Ubuntu 24.04 (NOBLE_IMAGE), as scripts/lib-tier1.sh builds its image: a
# CI gate's tool, so what it reads changes only when the pin moves. The image's tag follows this
# recipe, so a change makes a new image; a failed build shows its own output.
_df="FROM $NOBLE_IMAGE
RUN apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq tesseract-ocr >/dev/null"
IMG=appkata-ocr:$(printf '%s' "$_df" | sha256sum | cut -c1-12)
if ! docker image inspect "$IMG" >/dev/null 2>&1; then
    _log=$(mktemp)
    if ! printf '%s\n' "$_df" | timeout 600 docker build --progress=plain -t "$IMG" - >"$_log" 2>&1; then
        echo "test-screenshot-text.sh: building $IMG failed or took over 10 minutes; docker build said:" >&2
        cat "$_log" >&2
        rm -f "$_log"
        exit 1
    fi
    rm -f "$_log"
fi
rm -rf "$OUT" && mkdir -p "$OUT"
cd "$HERE"
if [ $# -gt 0 ]; then printf '%s\n' "$@" | sed "s|^$HERE/||"; else git ls-files -co --exclude-standard 'screenshots/*.png'; fi > "$OUT/list.txt"
# a tesseract per core, each on one thread
docker run --rm --user "$(id -u):$(id -g)" -e OMP_THREAD_LIMIT=1 -v "$HERE:/src:ro" -v "$OUT:/out" "$IMG" sh -c '
    cd /src && xargs -P "$(nproc)" -I{} sh -c '\''mkdir -p "$(dirname "/out/$1")" && tesseract "$1" "/out/$1" >/dev/null 2>&1 || { rm -f "/out/$1.txt"; echo "could not read $1"; }'\'' sh {} < /out/list.txt'
echo "read $(wc -l < "$OUT/list.txt") screenshots"
python3 - "$OUT" <<'PY'
import os, re, sys
sys.path.insert(0, "scripts"); sys.path.insert(0, "src")
import public_text
from appkata_core import APPKATA_REPO
own = APPKATA_REPO.split("://", 1)[1].lower()
bad = 0
# a screen tesseract couldn't read is a screen not checked
for shot in open(os.path.join(sys.argv[1], "list.txt")).read().split("\n"):
    if shot and not os.path.exists(os.path.join(sys.argv[1], shot + ".txt")):
        bad = 1
        print(f"{shot}: not read")
for root, _, files in os.walk(sys.argv[1]):
    for name in files:
        if not name.endswith(".png.txt"):
            continue
        path = os.path.join(root, name)
        text = open(path, encoding="utf-8", errors="replace").read()
        shot = os.path.relpath(path, sys.argv[1])[:-4]
        hits = public_text.found(text)
        # a repository address naming AppKata that isn't its own (OCR may change case and spacing)
        hits += [m for m in re.findall(r"github\.com/[\w.-]+/appkata\b", text, re.I) if m.lower() != own]
        hits += public_text.PLACEHOLDER.findall(text)
        if hits:
            bad = 1
            print(f"{shot}: {', '.join(hits)}")
sys.exit(bad)
PY
echo "EXPECTED: ok"
