#!/bin/sh
# Wrap the AppKata.app that the macOS build step assembled on Linux into the hand-off
# tarball that packaging/macos/mac-sign.sh finishes on a Mac. Writes
#   releases/AppKata-<version>-macos-unsigned.tar.gz and its .sha256
# Usage: scripts/package-macos.sh [path/to/AppKata.app]    (default: build/macos/AppKata.app)
set -eu
HERE=$(cd "$(dirname "$0")/.." && pwd)
APP=${1:-$HERE/build/macos/AppKata.app}
[ -d "$APP/Contents/MacOS" ] || { echo "not an app bundle: $APP" >&2; exit 1; }

# version from Info.plist (plain XML plist, as the build writes it)
VERSION=$(sed -n '/<key>CFBundleShortVersionString<\/key>/{n;s/.*<string>\(.*\)<\/string>.*/\1/p;}' "$APP/Contents/Info.plist")
[ -n "$VERSION" ] || { echo "Info.plist has no CFBundleShortVersionString" >&2; exit 1; }

# nothing in the bundle may change after signing, so no bytecode caches go in
if find "$APP" -name '*.pyc' -path '*__pycache__*' | grep -q .; then
    echo "warning: __pycache__ files in the bundle; precompile deliberately or remove them" >&2
fi
BROKEN=$(find "$APP" -type l ! -exec test -e {} \; -print)
[ -z "$BROKEN" ] || { echo "broken symlinks in the bundle:" >&2; echo "$BROKEN" >&2; exit 1; }

NAME="AppKata-$VERSION-macos"
STAGE="$HERE/build/macos-handoff/$NAME"
rm -rf "$STAGE"; mkdir -p "$STAGE" "$HERE/releases"
cp -a "$APP" "$STAGE/AppKata.app"                 # -a keeps symlinks and modes
cp "$HERE/packaging/macos/mac-sign.sh" "$HERE/packaging/macos/entitlements.plist" \
   "$HERE/packaging/macos/README-macos.txt" "$STAGE/"
chmod 755 "$STAGE/mac-sign.sh"

OUT="$NAME-unsigned.tar.gz"
# ustar/pax with numeric owner 0: bsdtar on macOS unpacks it with the user's ownership
tar -C "$HERE/build/macos-handoff" --format=pax --owner=0 --group=0 --numeric-owner \
    -czf "$HERE/releases/$OUT" "$NAME"
(cd "$HERE/releases" && sha256sum "$OUT" > "$OUT.sha256")
echo "wrote releases/$OUT"
