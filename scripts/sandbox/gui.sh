#!/bin/bash
# Part of scripts/test-sandbox.sh (docs/app-sandboxing.md).
# Inside Mint 22.1 as root: start Xvfb, then run a Qt AppImage (AppKata) and an Electron AppImage
# (Obsidian) extracted and inside the Standard bwrap profile, and screenshot the display.
set -u
apt-get update -qq >/dev/null 2>&1; apt-get install -y -qq xvfb imagemagick libnss3 libxcb-cursor0 libgtk-3-0t64 libgbm1 libasound2t64 libxkbcommon-x11-0 libxcb-icccm4 libxcb-keysyms1 libxcb-shape0 libxcb-render-util0 libxcb-image0 >/dev/null 2>&1; echo deps: $?
useradd -m kata 2>/dev/null
mkdir -p /out && chmod 777 /out
su kata -s /bin/bash <<'EOS'
set -u
export HOME=/home/kata DISPLAY=:99
Xvfb :99 -screen 0 1280x800x24 >/dev/null 2>&1 &
sleep 2
export DBUS_SESSION_BUS_ADDRESS=$(dbus-daemon --session --fork --print-address)
run() {   # run <name> <appimage> <args...>
  local name=$1 img=$2; shift 2
  local APP=$HOME/bin/apps/$name/1 SBX=$HOME/.local/share/appkata/sandboxes/$name
  mkdir -p $APP $SBX && cp $img $APP/ && (cd $APP && ./$(basename $img) --appimage-extract >/dev/null && mv squashfs-root extracted)
  ( cd $HOME && HOME=/tmp/bare-$name timeout 12 "$APP/extracted/AppRun" "$@" > /out/$name-bare.log 2>&1; echo "$name unsandboxed: exit $? (124 = still running at 12 s)"; tail -2 /out/$name-bare.log | sed 's/^/    /' )
  rm -f /tmp/bus-$name
  xdg-dbus-proxy "$DBUS_SESSION_BUS_ADDRESS" /tmp/bus-$name --filter --talk=org.freedesktop.portal.Desktop &
  local proxy=$!; sleep 0.5
  bwrap --ro-bind /usr /usr --symlink usr/lib /lib --symlink usr/lib64 /lib64 \
    --symlink usr/bin /bin --symlink usr/sbin /sbin --ro-bind /etc /etc --ro-bind-try /var/cache/fontconfig /var/cache/fontconfig \
    --proc /proc --dev /dev --dev-bind-try /dev/dri /dev/dri --tmpfs /tmp --tmpfs /run \
    --bind $SBX $HOME --ro-bind $APP $APP \
    --ro-bind /tmp/.X11-unix/X99 /tmp/.X11-unix/X99 \
    --bind /tmp/bus-$name /run/bus \
    --unshare-all --share-net --die-with-parent --new-session \
    --clearenv --setenv HOME $HOME --setenv PATH /usr/bin --setenv LANG C.UTF-8 --setenv DISPLAY :99 \
    --setenv XDG_RUNTIME_DIR /run --setenv DBUS_SESSION_BUS_ADDRESS unix:path=/run/bus --chdir $HOME \
    "$APP/extracted/AppRun" "$@" > /out/$name.log 2>&1 &
  local pid=$!
  sleep 15
  import -window root /out/$name.png
  if kill -0 $pid 2>/dev/null; then echo "$name: still running after 15 s (good)"; else wait $pid; echo "$name: exited with $?"; fi
  kill $pid $proxy 2>/dev/null; sleep 1; pkill -u kata -f "$APP" 2>/dev/null; sleep 1
  echo "  log tail:"; tail -4 /out/$name.log | sed 's/^/    /'
  echo "  sandbox home: $(cd $SBX && find . -maxdepth 3 -type d | head -6 | tr '\n' ' ')"
}
run appkata /x/AppKata.AppImage
run obsidian /x/obsidian.AppImage
EOS
