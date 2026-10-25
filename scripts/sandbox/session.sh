# Sourced as the test user: a desktop session in the container. A session bus, a headless sway
# Part of scripts/test-sandbox.sh "session" (docs/app-sandboxing.md round 2). Runs inside the Mint 22.1 Wayland container.
# (Wayland only, no XWayland), PipeWire with its PulseAudio server, and the portals (activated on the bus).
export HOME=/home/kata XDG_RUNTIME_DIR=/run/user/$(id -u) XDG_CURRENT_DESKTOP=sway XDG_SESSION_TYPE=wayland
mkdir -p "$XDG_RUNTIME_DIR" && chmod 700 "$XDG_RUNTIME_DIR"
export DBUS_SESSION_BUS_ADDRESS=unix:path=$XDG_RUNTIME_DIR/bus
[ -S "$XDG_RUNTIME_DIR/bus" ] || dbus-daemon --session --address="$DBUS_SESSION_BUS_ADDRESS" --fork --nopidfile
mkdir -p $HOME/.config/sway $HOME/.config/xdg-desktop-portal
printf 'xwayland disable\noutput HEADLESS-1 resolution 1280x800\ndefault_border none\n' > $HOME/.config/sway/config
printf '[preferred]\ndefault=gtk\norg.freedesktop.impl.portal.Screenshot=wlr\norg.freedesktop.impl.portal.ScreenCast=wlr\n' > $HOME/.config/xdg-desktop-portal/portals.conf
if [ ! -S "$XDG_RUNTIME_DIR/wayland-1" ]; then
  WLR_BACKENDS=headless WLR_RENDERER=pixman WLR_LIBINPUT_NO_DEVICES=1 sway -c $HOME/.config/sway/config > /tmp/sway.log 2>&1 &
  for i in $(seq 50); do [ -S "$XDG_RUNTIME_DIR/wayland-1" ] && break; sleep 0.2; done
fi
export WAYLAND_DISPLAY=wayland-1
export SWAYSOCK=$(ls $XDG_RUNTIME_DIR/sway-ipc.*.sock 2>/dev/null | head -1)
dbus-update-activation-environment WAYLAND_DISPLAY XDG_CURRENT_DESKTOP XDG_SESSION_TYPE XDG_RUNTIME_DIR
if [ ! -S "$XDG_RUNTIME_DIR/pipewire-0" ]; then
  pipewire > /tmp/pipewire.log 2>&1 &
  sleep 0.5; wireplumber > /tmp/wireplumber.log 2>&1 & pipewire-pulse > /tmp/pipewire-pulse.log 2>&1 &
  for i in $(seq 50); do [ -S "$XDG_RUNTIME_DIR/pulse/native" ] && break; sleep 0.2; done
fi
