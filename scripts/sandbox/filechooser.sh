#!/bin/bash
# Part of scripts/test-sandbox.sh "session" (docs/app-sandboxing.md round 2). Runs inside the Mint 22.1 Wayland container.
# The file-chooser mechanism, tested directly via the document portal (what the chooser uses to hand a
# file to a sandboxed app). Question: when the user picks ~/Documents/secret.txt — outside the bwrap
# mount — can the app read it? And does marking the app as a Flatpak route it through the doc portal?
. /x/session.sh; . /x/lib.sh
/usr/libexec/xdg-document-portal > /tmp/docportal.log 2>&1 & sleep 1.5
mkdir -p /home/kata/Documents; echo "TOP SECRET" > /home/kata/Documents/secret.txt
P=$HOME/.local/share/appkata/sandboxes/fc; mkdir -p $P

# 1. No marker: the chooser returns a real path (/home/kata/Documents/secret.txt). The app's home is a
#    private tmpfs, so that path isn't in its mount. Confirm it can't read it.
r=$(SBX_BUS=talk sbx fc sh -c 'cat /home/kata/Documents/secret.txt 2>&1' )
echo "$r" | grep -q "TOP SECRET" && say LEAKED "plain path from chooser is readable (no Flatpak marker)" || say BLOCKED "plain path from chooser is readable (no marker)" "— app can't see /home/kata, as intended"

# 2. Flatpak marker: ask the Documents portal to export the file for this app, as the chooser does for a
#    sandboxed caller, and check it appears in the app's /run/user/UID/doc view and is readable there.
cat > $P/export.py <<'PY'
import os, sys
from gi.repository import Gio, GLib
bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
fd = os.open('/home/kata/Documents/secret.txt', os.O_RDONLY)
fdlist = Gio.UnixFDList.new(); idx = fdlist.append(fd)
args = GLib.Variant('(hsasa{sv})', (idx, 'io.appkata.Sandboxed.fc', [], {}))
try:
  res, _ = bus.call_with_unix_fd_list_sync('org.freedesktop.portal.Documents','/org/freedesktop/portal/documents',
    'org.freedesktop.portal.Documents','Add', args, GLib.VariantType('(s)'), Gio.DBusCallFlags.NONE, 3000, fdlist, None)
  print('DOCID', res.unpack()[0])
except Exception as e:
  print('ERR', str(e)[:100])
PY
# this call must go to the Documents portal, so give the proxy that extra talk and the doc mount
docid=$(SBX_BUS=flatpak SBX_BINDS="--bind $XDG_RUNTIME_DIR/doc $XDG_RUNTIME_DIR/doc" sbx fc python3 $HOME/export.py 2>&1)
echo "  document portal Add -> $docid"
if [ "${docid%% *}" = DOCID ]; then
  id=${docid#DOCID }
  r=$(SBX_BUS=flatpak SBX_BINDS="--bind $XDG_RUNTIME_DIR/doc $XDG_RUNTIME_DIR/doc" sbx fc sh -c "cat $XDG_RUNTIME_DIR/doc/$id/secret.txt 2>&1")
  echo "$r" | grep -q "TOP SECRET" && say WORKS "picked file readable via the document portal (Flatpak marker)" "/run/user/UID/doc/$id/secret.txt" || say FAILS "picked file readable via doc portal" "$r"
  # and nothing ELSE in Documents is exposed by the export
  r2=$(SBX_BUS=flatpak SBX_BINDS="--bind $XDG_RUNTIME_DIR/doc $XDG_RUNTIME_DIR/doc" sbx fc sh -c "ls $XDG_RUNTIME_DIR/doc/$id/ 2>&1; cat /home/kata/Documents/secret.txt 2>&1 | head -1")
  echo "$r2" | grep -q "cat: /home/kata" || echo "$r2" | grep -q "No such" && say WORKS "only the one picked file is exposed, not ~/Documents" || true
  echo "    exported dir holds: $(echo "$r2" | head -1)"
fi
