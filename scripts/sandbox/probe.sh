#!/bin/bash
# Part of scripts/test-sandbox.sh (docs/app-sandboxing.md).
# Runs inside the Mint container as root: sets up a user with secrets, installs Neovim's AppImage the
# way AppKata lays out portable apps, then runs the probe unsandboxed and under several bwrap profiles.
set -u
useradd -m kata 2>/dev/null
H=/home/kata
APPS=$H/bin/apps
mkdir -p $H/.ssh $H/.mozilla/firefox/abc.default $H/Documents $APPS/nvim/0.11 $APPS/otherapp
echo "-----BEGIN OPENSSH PRIVATE KEY----- fake" > $H/.ssh/id_ed25519
echo "SQLite format 3 cookies" > $H/.mozilla/firefox/abc.default/cookies.sqlite
echo "SSN 123-45-6789" > $H/Documents/taxes.txt
echo "# bashrc" > $H/.bashrc
echo "original" > $APPS/otherapp/OtherApp.AppImage
cp /x/nvim.appimage $APPS/nvim/0.11/nvim.AppImage
cp /x/probe.lua $APPS/nvim/0.11/probe.lua
chown -R kata:kata $H

# a second process of the user's, and a session bus with another app's service on it
cat > /usr/local/bin/svc.py <<'EOF'
from gi.repository import Gio, GLib
Gio.bus_own_name(Gio.BusType.SESSION, "org.example.Secrets", 0, None, None, None)
GLib.MainLoop().run()
EOF

su kata -s /bin/bash <<'EOS'
set -u
export HOME=/home/kata GITHUB_TOKEN=ghp_fakefakefake
export DBUS_SESSION_BUS_ADDRESS=$(dbus-daemon --session --fork --print-address)
python3 /usr/local/bin/svc.py 2>/dev/null &
exec -a secret-agent sleep 600 &
sleep 1
APP=$HOME/bin/apps/nvim/0.11
cd $APP && ./nvim.AppImage --appimage-extract >/dev/null && mv squashfs-root extracted && cd $HOME
SBX=$HOME/.local/share/appkata/sandboxes/nvim; mkdir -p $SBX

# the common part of every profile: the OS read-only, a private home, a clean environment
base() {
  echo bwrap --ro-bind /usr /usr --symlink usr/lib /lib --symlink usr/lib64 /lib64 \
    --symlink usr/bin /bin --symlink usr/sbin /sbin --ro-bind /etc /etc \
    --proc /proc --dev /dev --tmpfs /tmp --tmpfs /run \
    --bind $SBX $HOME --ro-bind $APP $APP \
    --unshare-all --die-with-parent --new-session \
    --clearenv --setenv HOME $HOME --setenv PATH /usr/bin --setenv REAL_HOME $HOME --setenv APP_DIR $APP \
    --setenv LANG C.UTF-8 --chdir $HOME
}
export APP_DIR=$APP
check() {
  local hit=""
  grep -q probe $HOME/.bashrc && hit="$hit ~/.bashrc"
  [ -e $HOME/.config/autostart/evil.desktop ] && hit="$hit autostart"
  [ -e $HOME/.config/systemd/user/evil.service ] && hit="$hit systemd-unit"
  [ -e $HOME/.local/share/applications/firefox.desktop ] && hit="$hit menu-entry"
  [ -e $APP/AppRun.evil ] && hit="$hit own-install-folder"
  grep -q original $HOME/bin/apps/otherapp/OtherApp.AppImage && [ $(wc -c < $HOME/bin/apps/otherapp/OtherApp.AppImage) -le 9 ] || hit="$hit other-app"
  echo "  REAL FILES CHANGED: ${hit:- none}"
}
reset() { echo "# bashrc" > $HOME/.bashrc; rm -rf $HOME/.config/autostart $HOME/.config/systemd $HOME/.local/share/applications $APP/AppRun.evil; echo original > $HOME/bin/apps/otherapp/OtherApp.AppImage; }

echo "== 0. Today: AppKata launches the AppImage directly"
reset; $APP/nvim.AppImage --appimage-extract-and-run -l $APP/probe.lua 2>&1; check

echo; echo "== 1. bwrap, running the AppImage file itself (needs FUSE)"
reset; $(base) $APP/nvim.AppImage -l $APP/probe.lua 2>&1 | head -5

echo; echo "== 2. Standard: extracted AppRun, private home, ~/Documents granted, network, filtered D-Bus"
reset
xdg-dbus-proxy "$DBUS_SESSION_BUS_ADDRESS" /tmp/bus-nvim --filter --talk=org.freedesktop.portal.Desktop &
PROXY=$!
sleep 0.5
$(base) --share-net --ro-bind /etc/resolv.conf /etc/resolv.conf --bind $HOME/Documents $HOME/Documents \
  --bind /tmp/bus-nvim /run/bus --setenv DBUS_SESSION_BUS_ADDRESS unix:path=/run/bus \
  $APP/extracted/AppRun -l $APP/probe.lua 2>&1; check
kill $PROXY

echo; echo "== 3. Strict: extracted AppRun, private home only, no network, no D-Bus"
reset; $(base) $APP/extracted/AppRun -l $APP/probe.lua 2>&1; check

echo; echo "== After the runs"
echo "  the real ~/.bashrc:  $(tail -1 $HOME/.bashrc)"
echo "  the sandbox home:    $(cd $SBX && find . -type f | tr '\n' ' ')"
EOS
