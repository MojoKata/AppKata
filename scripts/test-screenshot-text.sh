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
# tesseract from Ubuntu 24.04's tag, not a digest (.coworker/deps.json says why)
if ! docker image inspect appkata-ocr >/dev/null 2>&1; then
    printf 'FROM ubuntu:24.04\nRUN apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq tesseract-ocr >/dev/null\n' \
        | timeout 600 docker build -q -t appkata-ocr - >/dev/null
fi
rm -rf "$OUT" && mkdir -p "$OUT"
cd "$HERE"
if [ $# -gt 0 ]; then printf '%s\n' "$@" | sed "s|^$HERE/||"; else git ls-files -co --exclude-standard 'screenshots/*.png'; fi > "$OUT/list.txt"
# a tesseract per core, each on one thread
docker run --rm --user "$(id -u):$(id -g)" -e OMP_THREAD_LIMIT=1 -v "$HERE:/src:ro" -v "$OUT:/out" appkata-ocr sh -c '
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
