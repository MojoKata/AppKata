#!/bin/bash
# Part of the app-sandboxing round-3 de-risking (docs/app-sandboxing.md). Run inside the Mint 22.1 session container.
# De-risk the design-sweep items: theme/font binding, D-Bus own-name + capabilities, and the
# write-beside-itself grant. Runs in the session container.
set -u
export HOME=/home/kata XDG_RUNTIME_DIR=/run/user/$(id -u)
mkdir -p "$XDG_RUNTIME_DIR" && chmod 700 "$XDG_RUNTIME_DIR"
export DBUS_SESSION_BUS_ADDRESS=unix:path=$XDG_RUNTIME_DIR/bus
[ -S "$XDG_RUNTIME_DIR/bus" ] || dbus-daemon --session --address="$DBUS_SESSION_BUS_ADDRESS" --fork --nopidfile
RT=$XDG_RUNTIME_DIR
say(){ printf '  %-7s %-52s %s\n' "$1" "$2" "${3:-}"; }
base(){ echo --ro-bind /usr /usr --symlink usr/lib /lib --symlink usr/lib64 /lib64 --symlink usr/bin /bin \
  --ro-bind /etc /etc --proc /proc --dev /dev --tmpfs /tmp --dir $RT --bind "$1" $HOME \
  --unshare-all --share-net --die-with-parent --new-session --clearenv \
  --setenv HOME $HOME --setenv PATH /usr/bin --setenv XDG_RUNTIME_DIR $RT --setenv LANG C.UTF-8 --chdir $HOME; }

echo "== B. Theme / font binding (apps look native?)"
# host user has a custom theme + font; a private home normally hides them
mkdir -p $HOME/.themes/Custom $HOME/.icons/Custom $HOME/.fonts $HOME/.config/fontconfig
echo "THEME-DATA" > $HOME/.themes/Custom/index.theme
echo "FONT-DATA" > $HOME/.fonts/Custom.ttf
SBX=$HOME/.local/share/appkata/sandboxes/themed; mkdir -p $SBX
# without the theme binds (bare private home)
r=$(bwrap $(base $SBX) sh -c 'cat ~/.themes/Custom/index.theme 2>&1' )
echo "$r" | grep -q THEME-DATA && say LEAK "theme visible with no bind" || say OK "private home hides host theme (as expected)" "$r"
# with the read-only theme/font binds the launcher would add
binds="--ro-bind $HOME/.themes $HOME/.themes --ro-bind $HOME/.icons $HOME/.icons --ro-bind $HOME/.fonts $HOME/.fonts --ro-bind $HOME/.config/fontconfig $HOME/.config/fontconfig"
r=$(bwrap $(base $SBX) $binds sh -c 'cat ~/.themes/Custom/index.theme; cat ~/.fonts/Custom.ttf' 2>&1 | tr '\n' ' ')
echo "$r" | grep -q "THEME-DATA FONT-DATA" && say WORKS "theme + fonts visible when bound read-only" || say FAIL "theme/font bind" "$r"
# and still read-only
r=$(bwrap $(base $SBX) $binds sh -c 'echo x > ~/.themes/Custom/index.theme 2>&1' )
echo "$r" | grep -qi "read-only" && say OK "the bound theme is read-only to the app" || say WARN "theme writable?" "$r"

echo "== C. D-Bus own-name + capabilities (single-instance, tray, etc.)"
SBX=$HOME/.local/share/appkata/sandboxes/dbustest; mkdir -p $SBX $HOME/info
printf '[Application]\nname=io.appkata.Sandboxed.dbustest\n' > $HOME/info/dbustest
sock=$RT/appkata/bus-dbustest; mkdir -p $RT/appkata; rm -f $sock
# the launcher's proxy: portals + the app's own name + a tray-watcher talk (a capability), nothing else
xdg-dbus-proxy "$DBUS_SESSION_BUS_ADDRESS" $sock --filter \
  --talk=org.freedesktop.portal.Desktop --own=io.appkata.Sandboxed.dbustest \
  --talk=org.kde.StatusNotifierWatcher >/tmp/proxy.log 2>&1 &
for i in $(seq 30); do [ -S $sock ] && break; sleep 0.1; done
pbase="--bind $sock $RT/bus --setenv DBUS_SESSION_BUS_ADDRESS unix:path=$RT/bus"
cat > $SBX/own.py <<'PY'
import sys
from gi.repository import Gio, GLib
bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
def own(name):
    got = {'v': None}
    def ok(*a): got['v']=True
    def lost(*a):
        if got['v'] is None: got['v']=False
    Gio.bus_own_name(Gio.BusType.SESSION, name, Gio.BusNameOwnerFlags.NONE, None, ok, lost)
    GLib.MainLoop();
    import time; time.sleep(0.6)
    ctx=GLib.MainContext.default()
    for _ in range(50):
        ctx.iteration(False); time.sleep(0.02)
    return got['v']
print('own-own-name:', own('io.appkata.Sandboxed.dbustest'))
print('own-ungranted:', own('org.evil.Taker'))
PY
bwrap $(base $SBX) $pbase --setenv XDG_RUNTIME_DIR $RT python3 $HOME/own.py 2>&1 | sed 's/^/  /'
# from outside: did the app actually own its granted name on the real bus?
owned=$(gdbus call --session --dest org.freedesktop.DBus --object-path /org/freedesktop/DBus \
  --method org.freedesktop.DBus.ListNames 2>/dev/null | grep -c 'io.appkata.Sandboxed.dbustest' || true)
say "${owned:+INFO}" "note: name may have been released when the probe exited"
kill %1 2>/dev/null

echo "== E. Write-beside-itself + writable-app-folder grant"
APP=$HOME/bin/apps/besider/1; mkdir -p $APP; echo '#!/bin/sh' > $APP/run; echo 'echo hi > "$(dirname "$0")/log.txt" && echo WROTE || echo EROFS' >> $APP/run; chmod +x $APP/run
SBX=$HOME/.local/share/appkata/sandboxes/besider; mkdir -p $SBX
r=$(bwrap $(base $SBX) --ro-bind $APP $APP sh -c "$APP/run" 2>&1)
echo "$r" | grep -q EROFS && say OK "Standard: write beside the binary is blocked (read-only)" || say LEAK "wrote beside binary under Standard?" "$r"
r=$(bwrap $(base $SBX) --bind $APP $APP sh -c "$APP/run" 2>&1)   # the writable-app-folder grant
echo "$r" | grep -q WROTE && say WORKS "writable-app-folder grant lets it write beside the binary" || say FAIL "grant didn't allow write" "$r"
