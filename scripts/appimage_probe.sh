#!/bin/sh
# Inside a container, for scripts/test-appimage.sh: run the AppImage given as $1 on the demo data in
# /data and write to /out what its processes loaded, for scripts/appimage_host_libs.py (requirement
# 1.6; review 3, R3-31). The tour runs offscreen, so a probe then loads what a desktop session would
# and the tour can't: the X11 and Wayland platform plugins with their GL, shell and decoration
# plugins, the input-method, image and icon plugins, and Qt's TLS backend, which loads OpenSSL only
# when first used. The platform themes (GTK 3, the desktop portal) are left out: Qt uses them when
# the host has them and does without otherwise. So is the PDF image plugin: PySide6's wheel ships it
# without the Qt PDF library it needs, so it never loads anywhere.
set -eu
cd /tmp && "$1" --appimage-extract >/dev/null
A=/tmp/squashfs-root
cp -r /data /tmp/d && mkdir -p /tmp/tour
APPKATA_DATA=/tmp/d XDG_DATA_HOME=/tmp/d/xdg QT_QPA_PLATFORM=offscreen APPKATA_TOUR_THEMES=dark \
    "$A/AppRun" --tour /tmp/tour --tour-only C01-catalog,C02-catalog-detail,A02-apps-detail,S02-trust-detail,X03-settings \
    > /out/tour.log 2>&1 &
pid=$!          # AppRun execs the bundled Python
for _ in $(seq 1 180); do [ "$(ls /tmp/tour/dark 2>/dev/null | wc -l)" -ge 3 ] && break; sleep 1; done
cat /proc/$pid/maps > /out/maps-tour.txt 2>/dev/null || true
wait $pid || true
ls /tmp/tour/dark > /out/tour-screens.txt 2>/dev/null || true
PYTHONPATH="$A/usr/lib/appkata" QT_QPA_PLATFORM=offscreen "$A/usr/python/bin/python3" -s - > /out/probe.log 2>&1 <<'PY' || true
import ctypes, glob, os
from PySide6 import QtGui, QtNetwork, QtQml, QtQuick, QtWidgets  # noqa: F401  (what AppKata imports)
from PySide6.QtCore import QCoreApplication, QLibraryInfo
from PySide6.QtNetwork import QSslSocket
app = QCoreApplication([])
print("tls:", QSslSocket.supportsSsl(), QSslSocket.activeBackend())
p = QLibraryInfo.path(QLibraryInfo.LibraryPath.PluginsPath)
tried = open("/out/plugins.txt", "w")
for pat in ("platforms/libqxcb.so", "platforms/libqwayland.so", "xcbglintegrations/*.so",
            "wayland-graphics-integration-client/libqt-plugin-wayland-egl.so", "wayland-shell-integration/libxdg-shell.so",
            "wayland-decoration-client/*.so", "platforminputcontexts/libcompose*.so", "platforminputcontexts/libibus*.so",
            "imageformats/*.so", "iconengines/*.so"):
    for f in sorted(glob.glob(os.path.join(p, pat))):
        if f.endswith("libqpdf.so"):
            continue
        tried.write(f + "\n")
        try:
            ctypes.CDLL(f)
        except OSError as e:
            print("failed:", e)
tried.close()
with open("/out/maps-probe.txt", "w") as out, open("/proc/self/maps") as maps:
    out.write(maps.read())
PY
for f in $(cat /out/maps-tour.txt /out/maps-probe.txt | awk '{print $6}' | grep "^$A/" | grep '\.so' | sort -u); do
    ldd "$f" 2>/dev/null
done > /out/ldd.txt
