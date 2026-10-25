#!/bin/sh
# Build the Windows installer on Linux (requirement 1.6): PyInstaller under Wine
# (tobix/pywine), then Inno Setup under Wine (amake/innosetup). Writes
# releases/AppKata-<version>-setup.exe and its .sha256. See docs/build.md § Windows.
set -eu
HERE=$(cd "$(dirname "$0")/.." && pwd)
VERSION=$(python3 -c "import sys; sys.path.insert(0, '$HERE/src'); import appkata_core; print(appkata_core.__version__)")
. "$HERE/packaging/versions.env"          # PY_SERIES, PYSIDE (requirement 1.2)
PYINSTALLER=6.16.0
TRUSTSTORE=0.10.4
mkdir -p "$HERE/releases" "$HERE/build/wine-cache"
rm -rf "$HERE/build/windows"

# Wine has no ICU and Qt 6.10+ imports Windows' icuuc.dll: a stand-in, for the build only
ICU="icuuc-$(sha256sum < "$HERE/packaging/windows/icuuc-stub.c" | cut -c1-12).dll"
test -f "$HERE/build/wine-cache/$ICU" || docker run --rm -v "$HERE:/src" debian:12 sh -c "
  apt-get -qq update && apt-get -qq install -y --no-install-recommends gcc-mingw-w64-x86-64-win32 >/dev/null 2>&1
  x86_64-w64-mingw32-gcc -shared -s -nostdlib -Wl,--entry,0 -o /src/build/wine-cache/$ICU /src/packaging/windows/icuuc-stub.c
  chown $(id -u):$(id -g) /src/build/wine-cache/$ICU"
test -f "$HERE/build/wine-cache/$ICU" || { echo "couldn't build the icuuc.dll stand-in"; exit 1; }

echo "== PyInstaller (Wine)"
docker run --rm -e PYTHONDONTWRITEBYTECODE=1 -v "$HERE:/src" -v "$HERE/build/wine-cache:/cache" -w /src tobix/pywine:$PY_SERIES sh -c "
  cp /cache/$ICU \$WINEPREFIX/drive_c/windows/system32/icuuc.dll
  wine python -m pip install -q --cache-dir Z:\\\\cache pyinstaller==$PYINSTALLER PySide6-Essentials==$PYSIDE truststore==$TRUSTSTORE >/dev/null 2>&1
  wine python -m PyInstaller --noconfirm --clean --log-level WARN \
       --distpath Z:\\\\src\\\\build\\\\windows\\\\dist --workpath Z:\\\\src\\\\build\\\\windows\\\\work packaging\\\\windows\\\\appkata.spec
" 2>&1 | grep -vE "^(wine|[0-9a-f]{4}:(fixme|err|warn))" | grep -v "^$" || true

# the containers run as root: hand the outputs back to the invoking user
docker run --rm -v "$HERE:/src" tobix/pywine:$PY_SERIES sh -c "chown -R $(id -u):$(id -g) /src/build /src/releases; find /src/src /src/packaging -name __pycache__ -prune -exec rm -rf {} +" >/dev/null 2>&1 || true
DIST="$HERE/build/windows/dist/AppKata"
test -f "$DIST/appkata.exe" || { echo "PyInstaller didn't produce appkata.exe"; exit 1; }
test -f "$DIST/_internal/appkata/qml/Main.qml" || { echo "the QML files are missing from the build"; exit 1; }
# PyInstaller's Qt hook skips Qt's plugins and QML, with only a warning, when Qt won't load under Wine
for f in plugins/platforms/qwindows.dll qml/QtQuick/Controls/Basic; do
  test -e "$DIST/_internal/PySide6/$f" || { echo "the build lacks PySide6/$f: Qt didn't load under Wine (see the warnings above)"; exit 1; }
done
# and it must carry no ICU at all: Windows' own serves Qt, and the stand-in, which does nothing,
# must never ship
ICUS=$(find "$DIST" -iname 'icu*.dll')
test -z "$ICUS" || { echo "the build carries ICU, where Windows' own must serve: $ICUS"; exit 1; }

# Qt parts AppKata doesn't use (it needs Core, Gui, Widgets, Qml, Quick, QuickControls2, Svg, Network)
I="$DIST/_internal/PySide6"
rm -rf "$I/translations" "$I/qml/QtQuick3D" "$I/qml/Qt3D" "$I/qml/QtMultimedia" "$I/qml/QtPdf" "$I/qml/QtCharts" \
       "$I/qml/QtDataVisualization" "$I/qml/QtSensors" "$I/qml/QtWebSockets" "$I/qml/QtTest" "$I/qml/QtQuick/VirtualKeyboard"
rm -f "$I"/Qt6Quick3D*.dll "$I"/Qt6Pdf*.dll "$I"/Qt6VirtualKeyboard*.dll "$I"/opengl32sw.dll "$I"/Qt6Charts*.dll \
      "$I"/Qt6Multimedia*.dll "$I"/Qt6Sensors*.dll "$I"/Qt6Test*.dll
echo "build/windows/dist/AppKata: $(du -sh "$DIST" | cut -f1)"

echo "== Inno Setup (Wine)"
docker run --rm -v "$HERE:/work" -w /work/packaging/windows amake/innosetup "/DAppVersion=$VERSION" appkata.iss 2>&1 | tail -3
docker run --rm -v "$HERE:/src" tobix/pywine:$PY_SERIES chown -R "$(id -u):$(id -g)" /src/releases >/dev/null 2>&1 || true
OUT="AppKata-$VERSION-setup.exe"
test -f "$HERE/releases/$OUT"
(cd "$HERE/releases" && sha256sum "$OUT" > "$OUT.sha256" && ls -l "$OUT" && cat "$OUT.sha256")
