#!/bin/sh
# Build releases/AppKata-<version>-x86_64.AppImage (requirement 1.6) and its .sha256.
#
#   python-build-standalone (CPython of PY_SERIES, x86_64, glibc 2.17+)  +  PySide6-Essentials from PyPI
#   (both versions in packaging/versions.env, requirement 1.2)
#   +  src/appkata, src/appkata_core  →  AppDir  →  appimagetool
#
# Builds in an Ubuntu 22.04 container (glibc 2.35, the oldest 1.1 supports): the bundled Python runs
# PySide6 during the build, and PySide6 6.10 and later need glibc 2.34, which a RHEL 8 host lacks.
# With docker absent it builds on the host. Downloads are cached in build/appimage-cache. Test it
# with scripts/test-appimage.sh.
set -eu
HERE=$(cd "$(dirname "$0")/.." && pwd)
VERSION=$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$HERE/src/appkata_core/__init__.py")
. "$HERE/packaging/versions.env"          # PY_SERIES, PYSIDE
. "$HERE/scripts/lib-python.sh"
if [ "${APPKATA_BUILD_IN_CONTAINER:-}" != 1 ] && command -v docker >/dev/null 2>&1; then
    # with the xcb-util libraries the AppImage carries (R3-32); the image's tag follows this recipe
    _df="FROM $JAMMY_IMAGE
RUN apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq curl ca-certificates file libgl1 libegl1 libxkbcommon0 libfontconfig1 libdbus-1-3 libglib2.0-0 libxcb-cursor0 libxcb-icccm4 libxcb-keysyms1 libxcb-image0 libxcb-render-util0 >/dev/null"
    IMG=appkata-build-jammy:$(printf '%s' "$_df" | sha256sum | cut -c1-12)
    docker image inspect "$IMG" >/dev/null 2>&1 || printf '%s\n' "$_df" | docker build -q -t "$IMG" - >/dev/null
    exec docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp -e APPKATA_BUILD_IN_CONTAINER=1 -e PY_SERIES -e PYSIDE \
        -v "$HERE:$HERE" -w "$HERE" "$IMG" sh "$HERE/scripts/build-appimage.sh" "$@"
fi
CACHE="$HERE/build/appimage-cache"
APPDIR="$HERE/build/AppKata.AppDir"
OUT="$HERE/releases/AppKata-$VERSION-x86_64.AppImage"
mkdir -p "$CACHE" "$HERE/releases"

# --- what the build takes from outside, as packaging/versions.env pins it, checked each time it's used
fetch_python "$PY_SERIES" "$CACHE"
pinned() {      # URL SHA256: CACHE/<the SHA-256's first 12>-<its name>, into PINNED
    PINNED="$CACHE/$(printf %s "$2" | cut -c1-12)-${1##*/}"
    echo "$2  $PINNED" | sha256sum -c --quiet >/dev/null 2>&1 && return 0
    curl -fsSL -o "$PINNED.part" "$1"
    echo "$2  $PINNED.part" | sha256sum -c --quiet || { echo "${1##*/} isn't the file packaging/versions.env pins" >&2; exit 1; }
    mv "$PINNED.part" "$PINNED"
}
pinned "$APPIMAGETOOL_URL" "$APPIMAGETOOL_SHA256"
APPIMAGETOOL=$PINNED
chmod +x "$APPIMAGETOOL"
pinned "$APPIMAGE_RUNTIME_URL" "$APPIMAGE_RUNTIME_SHA256"
RUNTIME=$PINNED

# --- AppDir
echo "== AppDir ($(basename "$PYTHON_TARBALL"))"
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/lib/appkata" "$APPDIR/usr/share/applications" "$APPDIR/usr/share/icons/hicolor/scalable/apps"
tar -xzf "$PYTHON_TARBALL" -C "$APPDIR/usr"            # → usr/python
PY="$APPDIR/usr/python/bin/python3"
"$PY" -m pip install --quiet --no-compile --no-deps --disable-pip-version-check --cache-dir "$CACHE/pip" \
    "PySide6-Essentials==$PYSIDE" "shiboken6==$PYSIDE"
# trim what a desktop app doesn't need
rm -rf "$APPDIR/usr/python/lib/python$PY_SERIES/test" "$APPDIR/usr/python/lib/python$PY_SERIES/idlelib" \
       "$APPDIR/usr/python/lib/python$PY_SERIES/tkinter" "$APPDIR/usr/python/lib/python$PY_SERIES/ensurepip"
SITE="$APPDIR/usr/python/lib/python$PY_SERIES/site-packages"
rm -rf "$SITE/pip" "$SITE"/pip-* "$SITE/PySide6/Qt/translations" "$SITE/PySide6/Qt/qml/QtQuick/VirtualKeyboard" \
       "$SITE/PySide6/Qt/lib/libQt6Pdf"* "$SITE/PySide6/Qt/qml/QtQuick3D" "$SITE/PySide6/Qt/lib/libQt63D"* \
       "$SITE/PySide6/Qt/lib/libQt6Quick3D"* "$SITE/PySide6/designer" "$SITE/PySide6/assistant" "$SITE/PySide6/linguist" 2>/dev/null || true
# Qt's X11 plugin needs five xcb-util libraries no Debian-family desktop installs, libxcb-cursor
# above all: without them AppKata doesn't start on X11, every Mint edition's session (review 3,
# R3-32). They carry no settings of their own; taken from Ubuntu 22.04, the oldest glibc 1.1
# supports, they sit beside Qt's libraries, where Qt's RUNPATH finds them.
LIC="$HERE/build/appimage-licenses"      # their copyright files, for the notices below
rm -rf "$LIC" && mkdir -p "$LIC/xcb-util"
for so in libxcb-cursor.so.0 libxcb-icccm.so.4 libxcb-keysyms.so.1 libxcb-image.so.0 libxcb-render-util.so.0; do
    cp -L "/usr/lib/x86_64-linux-gnu/$so" "$SITE/PySide6/Qt/lib/$so"
    pkg=$(dpkg -S "/usr/lib/x86_64-linux-gnu/$so" | cut -d: -f1 | head -1)
    cp "/usr/share/doc/$pkg/copyright" "$LIC/xcb-util/$pkg"
done
cp -r "$HERE/src/appkata" "$HERE/src/appkata_core" "$APPDIR/usr/lib/appkata/"
find "$APPDIR/usr/lib/appkata" -name __pycache__ -prune -exec rm -rf {} +
"$PY" -m compileall -q -j 0 "$APPDIR/usr/lib/appkata" "$APPDIR/usr/python/lib/python$PY_SERIES" >/dev/null 2>&1 || true

cat > "$APPDIR/AppRun" <<'EOF'
#!/bin/sh
HERE=$(dirname "$(readlink -f "$0")")
export PYTHONPATH="$HERE/usr/lib/appkata" PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1
exec "$HERE/usr/python/bin/python3" -s -m appkata "$@"
EOF
chmod +x "$APPDIR/AppRun"
cat > "$APPDIR/appkata.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=AppKata
Comment=A FOSS app store built on git
Exec=appkata %U
Icon=appkata
Categories=System;PackageManager;
MimeType=x-scheme-handler/appkata;
X-AppImage-Version=$VERSION
EOF
cp "$APPDIR/appkata.desktop" "$APPDIR/usr/share/applications/"
cp "$HERE/src/appkata/qml/assets/appkata.svg" "$APPDIR/appkata.svg"
cp "$HERE/src/appkata/qml/assets/appkata.svg" "$APPDIR/usr/share/icons/hicolor/scalable/apps/appkata.svg"
mkdir -p "$APPDIR/usr/share/icons/hicolor/256x256/apps"      # a PNG too, for the first-start install (2.11.3.1)
QT_QPA_PLATFORM=offscreen "$PY" - "$HERE/src/appkata/qml/assets/appkata.svg" "$APPDIR/usr/share/icons/hicolor/256x256/apps/appkata.png" <<'PNG'
import sys
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer
app = QGuiApplication([])
img = QImage(256, 256, QImage.Format.Format_ARGB32)
img.fill(Qt.GlobalColor.transparent)
p = QPainter(img); QSvgRenderer(sys.argv[1]).render(p); p.end()
sys.exit(0 if img.save(sys.argv[2], "PNG") else 1)
PNG
ln -sf appkata.svg "$APPDIR/.DirIcon"
# AppKata's license and the notices of every part the AppImage carries that others made, in
# usr/share/licenses/appkata; the build stops if a library in it is a part they don't give
"$PY" "$HERE/scripts/third_party_notices.py" write linux "$APPDIR" "$LIC"
"$PY" "$HERE/scripts/third_party_notices.py" check linux "$APPDIR"

echo "== appimagetool"
rm -f "$OUT"
ARCH=x86_64 "$APPIMAGETOOL" --appimage-extract-and-run --runtime-file "$RUNTIME" --no-appstream "$APPDIR" "$OUT" >/dev/null 2>&1 ||
    ARCH=x86_64 "$APPIMAGETOOL" --appimage-extract-and-run --runtime-file "$RUNTIME" --no-appstream "$APPDIR" "$OUT"
(cd "$HERE/releases" && sha256sum "$(basename "$OUT")" > "$(basename "$OUT").sha256")
echo "wrote releases/$(basename "$OUT") ($(du -h "$OUT" | cut -f1))"
