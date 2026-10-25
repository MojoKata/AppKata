#!/bin/bash
# Part of the app-sandboxing round-3 de-risking (docs/app-sandboxing.md). Run inside the Mint 22.1 session container.
# Capstone: a full Standard-profile launcher with ALL the pieces composed, running a real GUI app.
# identity marker + filtered dbus-proxy (portals + own-name + a capability) + theme/font binds +
# a folder grant + network + X11 display + sound. Confirms the whole thing starts a real app.
set -u
export HOME=/home/kata XDG_RUNTIME_DIR=/run/user/$(id -u) DISPLAY=:99
mkdir -p "$XDG_RUNTIME_DIR" && chmod 700 "$XDG_RUNTIME_DIR"
export DBUS_SESSION_BUS_ADDRESS=unix:path=$XDG_RUNTIME_DIR/bus
[ -S "$XDG_RUNTIME_DIR/bus" ] || dbus-daemon --session --address="$DBUS_SESSION_BUS_ADDRESS" --fork --nopidfile
pgrep -f "Xvfb :99" >/dev/null || Xvfb :99 -screen 0 1280x800x24 >/tmp/xvfb.log 2>&1 &
pgrep -f xdg-document-portal >/dev/null || /usr/libexec/xdg-document-portal >/tmp/docportal.log 2>&1 &
pgrep -f 'xdg-desktop-portal$' >/dev/null || /usr/libexec/xdg-desktop-portal >/tmp/portal.log 2>&1 &
pgrep -x pipewire >/dev/null || { pipewire >/tmp/pw.log 2>&1 & sleep 0.5; wireplumber >/tmp/wp.log 2>&1 & pipewire-pulse >/tmp/pwp.log 2>&1 & }
sleep 3
RT=$XDG_RUNTIME_DIR
name=${1:-appkata}; img=${2:-/x/AppKata.AppImage}
APP=$HOME/bin/apps/$name/1 SBX=$HOME/.local/share/appkata/sandboxes/$name
mkdir -p $APP $SBX $HOME/.themes/Custom $HOME/.fonts $HOME/Documents $HOME/info
echo "THEME" > $HOME/.themes/Custom/index.theme; echo "SECRET" > $HOME/.ssh_key 2>/dev/null; mkdir -p $HOME/.ssh; echo SECRET > $HOME/.ssh/id_ed25519
[ -x $APP/extracted/AppRun ] || { cp $img $APP/ && (cd $APP && ./$(basename $img) --appimage-extract >/dev/null 2>&1 && mv squashfs-root extracted); }
printf '[Application]\nname=io.appkata.Sandboxed.%s\n' "$name" > $HOME/info/$name

# the launcher's dbus-proxy: portals + the app's own name + the notifications capability, nothing else
sock=$RT/appkata/bus-$name; mkdir -p $RT/appkata; rm -f $sock
xdg-dbus-proxy "$DBUS_SESSION_BUS_ADDRESS" $sock --filter --talk=org.freedesktop.portal.Desktop \
  --own=io.appkata.Sandboxed.$name --talk=org.freedesktop.Notifications >/tmp/proxy-$name.log 2>&1 &
for i in $(seq 30); do [ -S $sock ] && break; sleep 0.1; done

case $name in appkata) appenv=(--setenv QT_QPA_PLATFORM xcb);; *) appenv=();; esac
timeout 18 bwrap \
  --ro-bind /usr /usr --symlink usr/lib /lib --symlink usr/lib64 /lib64 --symlink usr/bin /bin --symlink usr/sbin /sbin \
  --ro-bind /etc /etc --ro-bind-try /var/cache/fontconfig /var/cache/fontconfig \
  --proc /proc --dev /dev --tmpfs /tmp --dir $RT \
  --bind $SBX $HOME --ro-bind $APP $APP \
  --ro-bind $HOME/.themes $HOME/.themes --ro-bind $HOME/.fonts $HOME/.fonts \
  --bind $HOME/Documents $HOME/Documents \
  --ro-bind /tmp/.X11-unix/X99 /tmp/.X11-unix/X99 \
  --ro-bind-try $RT/pipewire-0 $RT/pipewire-0 --ro-bind-try $RT/pulse/native $RT/pulse/native \
  --ro-bind $HOME/info/$name /.flatpak-info \
  --bind $sock $RT/bus \
  --unshare-all --share-net --die-with-parent --new-session \
  --clearenv --setenv HOME $HOME --setenv PATH /usr/bin --setenv DISPLAY :99 \
  --setenv XDG_RUNTIME_DIR $RT --setenv DBUS_SESSION_BUS_ADDRESS unix:path=$RT/bus \
  --setenv LANG C.UTF-8 "${appenv[@]}" --chdir $HOME \
  $APP/extracted/AppRun > /tmp/$name-run.log 2>&1 &
pid=$!
sleep 14
import -window root /out/$name-launcher.png 2>/dev/null || true
if kill -0 $pid 2>/dev/null; then echo "RESULT: $name RUNNING under the full Standard launcher after 14s"; else wait $pid; echo "RESULT: $name exited $?"; fi
# prove isolation still holds from inside while all this is composed
iso=$(bwrap --ro-bind /usr /usr --symlink usr/lib /lib --symlink usr/lib64 /lib64 --symlink usr/bin /bin --proc /proc --dev /dev --tmpfs /tmp --bind $SBX $HOME --unshare-all --clearenv --setenv HOME $HOME --setenv PATH /usr/bin sh -c 'cat ~/.ssh/id_ed25519 2>&1' )
echo "$iso" | grep -q SECRET && echo "  ISOLATION: LEAK (read ~/.ssh)" || echo "  ISOLATION: ~/.ssh still blocked"
echo "  proxy log: $(tail -1 /tmp/proxy-$name.log 2>/dev/null)"
echo "  app log tail: $(grep -iE 'error|fatal' /tmp/$name-run.log | grep -v 'Failed to connect to the bus' | tail -1)"
pkill -f "$APP/extracted" 2>/dev/null; kill %1 2>/dev/null; true
