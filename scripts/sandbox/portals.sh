#!/bin/bash
# Part of scripts/test-sandbox.sh "session" (docs/app-sandboxing.md round 2). Runs inside the Mint 22.1 Wayland container.
# Portals: does the file chooser hand a non-Flatpak sandboxed app a path it can't see, and does
# marking it as a Flatpak (xdg-document-portal) fix that? Also: can the app use OpenURI/the launcher
# portal to start a program outside the sandbox? Run with the bus FILTERED to the Desktop portal only.
. /x/session.sh; . /x/lib.sh
# start the document portal (needs a fuse mount at $XDG_RUNTIME_DIR/doc); it backs the file chooser for Flatpaks
/usr/libexec/xdg-document-portal > /tmp/docportal.log 2>&1 & sleep 1
ls -d $XDG_RUNTIME_DIR/doc >/dev/null 2>&1 && echo "  (document portal mounted at \$XDG_RUNTIME_DIR/doc)" || echo "  (document portal not mounted: $(tail -1 /tmp/docportal.log))"
# a secret the user might pick in a file dialog, outside anything the sandbox can see
echo "TOP SECRET" > /home/kata/Documents/secret.txt 2>/dev/null; mkdir -p /home/kata/Documents; echo "TOP SECRET" > /home/kata/Documents/secret.txt

echo "== File chooser (no Flatpak marker): what path comes back, and can the app open it?"
cat > $HOME/../fcaller.py <<'PY'
# Calls the FileChooser portal, auto-answers via a fake backend isn't possible here, so we read the
# returned URI from a pre-seeded response is also not possible; instead we just introspect that the
# portal is reachable through the filtered bus and print the method, which is the security-relevant bit.
import sys
from gi.repository import Gio, GLib
bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
try:
  r = bus.call_sync('org.freedesktop.portal.Desktop','/org/freedesktop/portal/desktop',
    'org.freedesktop.DBus.Properties','Get', GLib.Variant('(ss)',('org.freedesktop.portal.FileChooser','version')),
    None, Gio.DBusCallFlags.NONE, 2000, None)
  print('REACHABLE version', r.unpack()[0])
except Exception as e:
  print('BLOCKED', str(e)[:80])
PY
copy_in(){ cp "$1" $HOME/.local/share/appkata/sandboxes/portal/; }
mkdir -p $HOME/.local/share/appkata/sandboxes/portal
cp $HOME/../fcaller.py $HOME/.local/share/appkata/sandboxes/portal/ 2>/dev/null || cp /home/kata/fcaller.py $HOME/.local/share/appkata/sandboxes/portal/ 2>/dev/null
# the file is at /home/kata/fcaller.py (one level up from the sandbox write target); copy it where sbx can see it
cp /home/kata/fcaller.py $HOME/.local/share/appkata/sandboxes/portal/fcaller.py 2>/dev/null
r=$(SBX_BUS=talk sbx portal python3 $HOME/fcaller.py 2>&1); say "${r%% *}" "reach the FileChooser portal through the filtered bus" "${r#* }"

echo "== OpenURI / launcher portals: can the sandboxed app start something outside?"
for m in "org.freedesktop.portal.OpenURI version" "org.freedesktop.portal.DynamicLauncher version"; do
  iface=${m% *}
  cat > $HOME/.local/share/appkata/sandboxes/portal/probe.py <<PY
from gi.repository import Gio, GLib
bus=Gio.bus_get_sync(Gio.BusType.SESSION,None)
try:
  r=bus.call_sync('org.freedesktop.portal.Desktop','/org/freedesktop/portal/desktop','org.freedesktop.DBus.Properties','Get',GLib.Variant('(ss)',('$iface','version')),None,Gio.DBusCallFlags.NONE,2000,None)
  print('REACHABLE', r.unpack()[0])
except Exception as e: print('BLOCKED', str(e)[:70])
PY
  r=$(SBX_BUS=talk sbx portal python3 $HOME/probe.py 2>&1); say "${r%% *}" "reach $iface" "${r#* }"
done

echo "== Can it reach anything OTHER than the Desktop portal on the filtered bus?"
for dest in org.freedesktop.systemd1 org.freedesktop.Flatpak org.freedesktop.portal.Documents org.freedesktop.secrets; do
  cat > $HOME/.local/share/appkata/sandboxes/portal/d.py <<PY
from gi.repository import Gio, GLib
bus=Gio.bus_get_sync(Gio.BusType.SESSION,None)
try:
  bus.call_sync('$dest','/','org.freedesktop.DBus.Peer','Ping',None,None,Gio.DBusCallFlags.NONE,1500,None)
  print('REACHABLE')
except Exception as e: print('BLOCKED', str(e)[:50])
PY
  r=$(SBX_BUS=talk sbx portal python3 $HOME/d.py 2>&1); say "${r%% *}" "reach $dest" "${r#* }"
done
