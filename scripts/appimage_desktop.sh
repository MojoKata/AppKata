#!/bin/sh
# Inside a desktop image (scripts/test-appimage.sh): start the AppImage given as $1 as a user would,
# on X11 (Xvfb) and on Wayland (a headless compositor), and check that it runs there with only the
# desktop's own libraries (requirement 1.1, 1.6; review 3, R3-31, R3-32). The tour is no help here:
# it runs offscreen, so it never loads the platform plugin a desktop session loads.
#
# For each session: AppKata still running after 20 s, Qt's plugin for that session loaded, on X11 a
# window, and every library it took from the host owned by a package the desktop installs (listed in
# /desktop-packages.txt before the test's own tools went in, so Xvfb or weston can't stand in for
# the desktop). Prints "<session>: ok" or "<session>: FAILED: ..." for each.
set -u
IMG=$1
export HOME=/tmp/home APPKATA_DATA=/tmp/home/data XDG_RUNTIME_DIR=/tmp/xdg
mkdir -p "$HOME" "$XDG_RUNTIME_DIR" && chmod 700 "$XDG_RUNTIME_DIR"
cp "$IMG" /tmp/AppKata.AppImage

owner() {      # the package that owns a file; dpkg may know it by its path before /usr was merged
    for f in "$1" "${1#/usr}"; do dpkg -S "$f" 2>/dev/null | head -1 | cut -d: -f1 | grep . && return; done
}

check() {      # check <session> <plugin library> <pid of the AppImage's runtime>
    session=$1 plugin=$2 pid=$3 why=""
    sleep 20
    py=$(pgrep -n -f -- "-s -m appkata")       # the runtime forks the bundled Python, which runs AppKata
    if [ -z "$py" ]; then
        why="exited: $(grep -i -m1 'platform plugin\|error\|not found' /tmp/log.$session)"
    else
        grep -q "$plugin" /proc/$py/maps || why="$why $plugin not loaded;"
        if [ "$session" = x11 ] && ! xwininfo -root -tree -display :99 2>/dev/null | grep -qi appkata; then why="$why no window;"; fi
        for f in $(awk '{print $6}' /proc/$py/maps | grep '\.so' | grep -v appimage_extracted | sort -u); do
            p=$(owner "$(readlink -f "$f")")
            grep -qx "$p" /desktop-packages.txt || why="$why $(basename "$f") from ${p:-no package}, not the desktop's;"
        done
        kill "$py" "$pid" 2>/dev/null; wait "$pid" 2>/dev/null; sleep 1
    fi
    if [ -z "$why" ]; then echo "$session: ok"; else echo "$session: FAILED:$why"; fi
}

# X11
Xvfb :99 -screen 0 1920x1080x24 >/dev/null 2>&1 &
sleep 2
DISPLAY=:99 XDG_SESSION_TYPE=x11 /tmp/AppKata.AppImage --appimage-extract-and-run > /tmp/log.x11 2>&1 &
check x11 libQt6XcbQpa $!

# Wayland: weston's headless backend (its option's name changed in weston 10)
weston --backend=headless --socket=wayland-9 >/tmp/compositor.log 2>&1 &
sleep 2
[ -S "$XDG_RUNTIME_DIR/wayland-9" ] || { weston --backend=headless-backend.so --socket=wayland-9 >/tmp/compositor.log 2>&1 & sleep 2; }
if [ -S "$XDG_RUNTIME_DIR/wayland-9" ]; then
    WAYLAND_DISPLAY=wayland-9 XDG_SESSION_TYPE=wayland /tmp/AppKata.AppImage --appimage-extract-and-run > /tmp/log.wayland 2>&1 &
    check wayland libQt6WaylandClient $!
else
    echo "wayland: FAILED: no compositor ($(tail -1 /tmp/compositor.log))"
fi
