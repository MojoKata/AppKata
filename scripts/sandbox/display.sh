#!/bin/bash
# Part of scripts/test-sandbox.sh "session" (docs/app-sandboxing.md round 2). Runs inside the Mint 22.1 Wayland container.
# Display tests: what a sandboxed app can do to the user's other windows on Wayland (sway) and X11.
. /x/session.sh; . /x/lib.sh
H=$HOME/.local/share/appkata/sandboxes/probe
echo "== Wayland (sway, no XWayland): the sandbox gets only the Wayland socket"
GDK_BACKEND=wayland python3 /x/typebox.py wayland > /tmp/typebox-w.log 2>&1 & TB=$!
sleep 2; wl-copy "secret from the clipboard"; sleep 0.5
rm -f $H/screen.png /tmp/typed-wayland.txt
SBX_DISPLAY=wayland sbx probe grim $HOME/screen.png >/dev/null 2>&1
[ -s $H/screen.png ] && say LEAKED "capture the whole screen (grim, wlr-screencopy)" "$(identify -format %wx%h $H/screen.png)" || say BLOCKED "capture the whole screen (grim, wlr-screencopy)"
clip=$(SBX_DISPLAY=wayland sbx probe timeout 3 wl-paste 2>/dev/null)
[ -n "$clip" ] && say LEAKED "read the clipboard while not focused (wl-paste, data-control)" "\"$clip\"" || say BLOCKED "read the clipboard while not focused"
SBX_DISPLAY=wayland sbx probe wtype "typed-by-sandbox" >/dev/null 2>&1; sleep 0.5
t=$(cat /tmp/typed-wayland.txt 2>/dev/null)
[ -n "$t" ] && say LEAKED "type into another app's window (wtype, virtual-keyboard)" "\"$t\"" || say BLOCKED "type into another app's window (wtype)"
SBX_DISPLAY=wayland sbx probe sh -c 'ls $XDG_RUNTIME_DIR/sway-ipc.* 2>/dev/null' | grep -q sock && say LEAKED "reach sway's IPC socket (swaymsg exec)" || say BLOCKED "reach sway's IPC socket (swaymsg exec runs anything)"
# what the same calls do outside the sandbox, to show the protocols are there
SWAYSOCK=$SWAYSOCK swaymsg -t get_version >/dev/null 2>&1 && say "(host)" "swaymsg works outside the sandbox: binding all of \$XDG_RUNTIME_DIR would leak it"
kill $TB 2>/dev/null

echo "== Wayland (mutter 46, GNOME's compositor; Cinnamon's muffin is a fork of it), no Xwayland"
mutter --headless --wayland --no-x11 --virtual-monitor 1280x800 --wayland-display wayland-m > /tmp/mutter.log 2>&1 & MU=$!
for i in $(seq 50); do [ -S $XDG_RUNTIME_DIR/wayland-m ] && break; sleep 0.2; done
export WAYLAND_DISPLAY=wayland-m
GDK_BACKEND=wayland python3 /x/typebox.py mutter > /tmp/typebox-m.log 2>&1 & TB=$!
sleep 2; wl-copy "secret from the clipboard" 2>/dev/null & sleep 1
rm -f $H/screen-m.png /tmp/typed-mutter.txt
SBX_DISPLAY=wayland sbx probe grim $HOME/screen-m.png >/dev/null 2>&1
[ -s $H/screen-m.png ] && say LEAKED "capture the whole screen (grim)" || say BLOCKED "capture the whole screen (grim)" "$(SBX_DISPLAY=wayland sbx probe grim $HOME/x.png 2>&1 | head -1)"
if [ "$(timeout 3 wl-paste 2>/dev/null)" = "secret from the clipboard" ]; then
  clip=$(SBX_DISPLAY=wayland sbx probe timeout 3 wl-paste 2>/dev/null)
  [ -n "$clip" ] && say LEAKED "read the clipboard while not focused (wl-paste)" "\"$clip\"" || say BLOCKED "read the clipboard while not focused (wl-paste)"
else      # headless mutter has no keyboard, and the core protocol only gives the clipboard to the focused app
  say "N/A" "read the clipboard (no keyboard in headless mutter)" "$(timeout 3 wl-paste 2>&1 | head -1)"
fi
SBX_DISPLAY=wayland sbx probe wtype "typed-by-sandbox" >/dev/null 2>&1; sleep 0.5
t=$(cat /tmp/typed-mutter.txt 2>/dev/null)
[ -n "$t" ] && say LEAKED "type into another app's window (wtype)" "\"$t\"" || say BLOCKED "type into another app's window (wtype)" "$(SBX_DISPLAY=wayland sbx probe wtype x 2>&1 | head -1)"
kill $TB $MU 2>/dev/null; export WAYLAND_DISPLAY=wayland-1

echo "== X11 (Xvfb): the sandbox gets only the X socket"
Xvfb :99 -screen 0 1280x800x24 >/dev/null 2>&1 & XV=$!; sleep 1.5
DISPLAY=:99 GDK_BACKEND=x11 python3 /x/typebox.py x11 > /tmp/typebox-x.log 2>&1 & TB=$!; sleep 2
rm -f $H/screen-x11.png /tmp/typed-x11.txt
SBX_DISPLAY=x11 sbx probe import -window root $HOME/screen-x11.png >/dev/null 2>&1
[ -s $H/screen-x11.png ] && say LEAKED "capture the whole screen (import -window root)" "$(identify -format %wx%h $H/screen-x11.png)" || say BLOCKED "capture the whole screen"
SBX_DISPLAY=x11 sbx probe sh -c 'xdotool search --name Password windowactivate --sync; xdotool type typed-by-sandbox' >/dev/null 2>&1; sleep 0.5
t=$(cat /tmp/typed-x11.txt 2>/dev/null)
[ -n "$t" ] && say LEAKED "type into another app's window (xdotool)" "\"$t\"" || say BLOCKED "type into another app's window (xdotool)"
# keylogging: the sandbox listens to raw key events while the user types into the other window
rm -f $H/keys.txt
SBX_DISPLAY=x11 sbx probe sh -c 'timeout 4 xinput test-xi2 --root > $HOME/keys.txt 2>&1' & KL=$!; sleep 1
DISPLAY=:99 xdotool type "hunter2"; wait $KL
n=$(grep -c "RawKeyPress" $H/keys.txt 2>/dev/null)
[ "${n:-0}" -gt 0 ] && say LEAKED "log the user's keystrokes in other windows (xinput test-xi2)" "$n key presses seen" || say BLOCKED "log keystrokes in other windows" "$(head -c 80 $H/keys.txt)"
kill $TB $XV 2>/dev/null
