#!/bin/sh
# Inside the Mint 22.3 desktop image, for scripts/test-appimage.sh: run the AppImage given as $1 the
# ways AppKata is used, under strace, and write to /out every file of the AppImage that each run
# opened, mapped to run, or looked for and didn't find (trace-<run>.txt).
# scripts/appimage_trim.py checks them against packaging/appimage-trim.txt: the build leaves out what
# AppKata never uses, and Qt and Python load most of what they use only when it's first used, so a
# part left out that was needed after all shows only on the screen, the session or the dialog that
# uses it.
#
# The runs: the whole screenshot tour on the demo data (/data), both themes, offscreen and then the
# dark one on X11 (Xvfb); the first-start screens from an empty home; AppKata started as a user
# would on X11 and on Wayland (weston), as scripts/appimage_desktop.sh does; --version and
# --install-self; and a probe that loads what none of those reach: every plugin of the kinds a
# desktop session loads (platforms, GL and shell integrations, input methods, images, icons), Qt's
# TLS backend, and the file, folder and message dialogs, both Qt's own and the GTK ones Qt uses on
# a GNOME-family desktop. TRACE_ONLY="x11 wayland" runs only those. Each run has 15 minutes.
set -u
IMG=$1
export HOME=/tmp/home XDG_RUNTIME_DIR=/tmp/xdg
mkdir -p "$HOME" "$XDG_RUNTIME_DIR" /tmp/tour && chmod 700 "$XDG_RUNTIME_DIR"
cd /tmp && "$IMG" --appimage-extract >/dev/null
A=/tmp/squashfs-root

# a session bus, as a desktop session has: without one AppKata starts its own, which strace follows
# and which outlives it
eval "$(dbus-launch --sh-syntax)"
export DBUS_SESSION_BUS_ADDRESS

trace() {      # trace <run> <command...>: the command under strace; its lines that name the AppImage's files
    run=$1; shift      # (and every "resumed" line: an interrupted call's result, its path on the line before)
    case " ${TRACE_ONLY:-$run} " in *" $run "*) ;; *) return 0;; esac
    timeout -k 10 900 strace -f -qq -y --seccomp-bpf -e trace=%file,mmap \
        -o "|grep -F -e $A/ -e 'resumed>' > /out/trace-$run.txt" "$@" > "/out/log-$run.txt" 2>&1
    echo "$run: exit $?"
}
quit_after() {      # quit_after <seconds>: end the AppKata started last, as the desktop session would
    sleep "$1"; pkill -TERM -f -- "-s -m appkata" 2>/dev/null; sleep 2; pkill -KILL -f -- "-s -m appkata" 2>/dev/null
}

cp -r /data /tmp/d
APPKATA_DATA=/tmp/d XDG_DATA_HOME=/tmp/d/xdg QT_QPA_PLATFORM=offscreen trace tour "$A/AppRun" --tour /tmp/tour/offscreen
mkdir -p /tmp/fresh
HOME=/tmp/fresh APPKATA_DATA=/tmp/fresh/data XDG_DATA_HOME=/tmp/fresh/.local/share QT_QPA_PLATFORM=offscreen \
    APPKATA_TOUR_FRESH=1 trace fresh "$A/AppRun" --tour /tmp/tour/fresh

Xvfb :99 -screen 0 1920x1080x24 >/dev/null 2>&1 &
sleep 2
rm -rf /tmp/d && cp -r /data /tmp/d
DISPLAY=:99 XDG_SESSION_TYPE=x11 APPKATA_DATA=/tmp/d XDG_DATA_HOME=/tmp/d/xdg APPKATA_TOUR_THEMES=dark \
    trace tour-x11 "$A/AppRun" --tour /tmp/tour/x11
DISPLAY=:99 XDG_SESSION_TYPE=x11 trace x11 "$A/AppRun" & pid=$!; quit_after 20; wait $pid      # (not Xvfb)

weston --backend=headless --socket=wayland-9 >/tmp/compositor.log 2>&1 &
sleep 2
[ -S "$XDG_RUNTIME_DIR/wayland-9" ] || { weston --backend=headless-backend.so --socket=wayland-9 >/tmp/compositor.log 2>&1 & sleep 2; }
WAYLAND_DISPLAY=wayland-9 XDG_SESSION_TYPE=wayland trace wayland "$A/AppRun" & pid=$!; quit_after 20; wait $pid

trace version "$A/AppRun" --version
cp "$IMG" /tmp/AppKata.AppImage
HOME=/tmp/inst XDG_DATA_HOME=/tmp/inst/.local/share APPKATA_DATA=/tmp/inst/data trace install-self /tmp/AppKata.AppImage --appimage-extract-and-run --install-self

cat > /tmp/probe.py <<'PY'
import ctypes, glob, os, sys
from PySide6 import QtGui, QtNetwork, QtQml, QtQuick, QtWidgets  # noqa: F401  (what AppKata imports)
from PySide6.QtCore import QLibraryInfo, QTimer
from PySide6.QtNetwork import QSslSocket
from PySide6.QtWidgets import QApplication
os.environ["QT_QUICK_CONTROLS_STYLE"] = "Basic"          # as AppKata sets it (src/appkata/app.py)
app = QApplication([])
if sys.argv[1] == "plugins":
    print("tls:", QSslSocket.supportsSsl(), QSslSocket.activeBackend())
    p = QLibraryInfo.path(QLibraryInfo.LibraryPath.PluginsPath)
    for pat in ("platforms/libqxcb.so", "platforms/libqwayland.so", "platforms/libqoffscreen.so", "platforms/libqminimal.so",
                "xcbglintegrations/*.so", "wayland-graphics-integration-client/*.so", "wayland-shell-integration/*.so",
                "wayland-decoration-client/*.so", "platforminputcontexts/*.so", "platformthemes/*.so",
                "imageformats/*.so", "iconengines/*.so", "tls/*.so", "networkinformation/*.so"):
        for f in sorted(glob.glob(os.path.join(p, pat))):
            try:
                ctypes.CDLL(f)
            except OSError as e:
                print("failed:", e)
else:       # the dialogs AppKata opens (ReviewDialog.qml, SettingsDialog.qml, SandboxDialog.qml)
    engine = QtQml.QQmlApplicationEngine()
    engine.loadData(b"""import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Dialogs
ApplicationWindow { visible: true; width: 800; height: 600
    FileDialog { id: f; fileMode: FileDialog.SaveFile; nameFilters: ["Markdown (*.md)"] }
    FolderDialog { id: g }
    MessageDialog { id: m; text: "probe" }
    Timer { interval: 500; running: true; onTriggered: f.open() }
    Timer { interval: 2500; running: true; onTriggered: { f.close(); g.open() } }
    Timer { interval: 4500; running: true; onTriggered: { g.close(); m.open() } }
}""")
    print("dialogs:", "loaded" if engine.rootObjects() else "FAILED")
    QTimer.singleShot(7000, app.quit)
    app.exec()
PY
P="$A/usr/python/bin/python3 -s /tmp/probe.py"
DISPLAY=:99 QT_QPA_PLATFORM=xcb PYTHONPATH="$A/usr/lib/appkata" trace probe-plugins $P plugins
DISPLAY=:99 QT_QPA_PLATFORM=xcb PYTHONPATH="$A/usr/lib/appkata" trace probe-dialogs-qt $P dialogs
DISPLAY=:99 QT_QPA_PLATFORM=xcb XDG_CURRENT_DESKTOP=GNOME PYTHONPATH="$A/usr/lib/appkata" trace probe-dialogs-gtk $P dialogs
WAYLAND_DISPLAY=wayland-9 QT_QPA_PLATFORM=wayland PYTHONPATH="$A/usr/lib/appkata" trace probe-dialogs-wayland $P dialogs
for d in /tmp/tour/*; do echo "screens $(basename "$d"): $(find "$d" -name '*.png' | wc -l)"; done
grep -h "^tls:\|^dialogs:\|^failed:" /out/log-probe-*.txt
