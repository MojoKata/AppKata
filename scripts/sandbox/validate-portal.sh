#!/bin/bash
# Part of the app-sandboxing round-3 de-risking (docs/app-sandboxing.md). Run inside the Mint 22.1 session container.
# #1 de-risk: does presenting a synthetic .flatpak-info make the document portal hand a picked file
# (outside the private home) to the sandboxed app? Runs the client directly on the real bus so the
# portal reads the app's own /.flatpak-info (the proxy filtering is a separate, already-validated concern).
set -u
export HOME=/home/kata XDG_RUNTIME_DIR=/run/user/$(id -u)
mkdir -p "$XDG_RUNTIME_DIR" && chmod 700 "$XDG_RUNTIME_DIR"
export DBUS_SESSION_BUS_ADDRESS=unix:path=$XDG_RUNTIME_DIR/bus
[ -S "$XDG_RUNTIME_DIR/bus" ] || dbus-daemon --session --address="$DBUS_SESSION_BUS_ADDRESS" --fork --nopidfile
# bring up the portals (document portal creates the $XDG_RUNTIME_DIR/doc FUSE mount)
pgrep -f xdg-document-portal >/dev/null || /usr/libexec/xdg-document-portal >/tmp/docportal.log 2>&1 &
pgrep -f 'xdg-desktop-portal$' >/dev/null || /usr/libexec/xdg-desktop-portal >/tmp/portal.log 2>&1 &
sleep 2
ls -d "$XDG_RUNTIME_DIR/doc" >/dev/null 2>&1 && echo "  doc portal mounted: yes" || echo "  doc portal mounted: NO ($(tail -1 /tmp/docportal.log))"

mkdir -p $HOME/Documents $HOME/info
echo "TOP SECRET PICKED FILE" > $HOME/Documents/picked.txt
printf '[Application]\nname=io.appkata.Sandboxed.docfit\n\n[Instance]\ninstance-id=%s\n' "$RANDOM" > $HOME/info/docfit
SBX=$HOME/.local/share/appkata/sandboxes/docfit; mkdir -p $SBX

cat > $SBX/doctest.py <<'PY'
import os, sys
from gi.repository import Gio, GLib
bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
# 1) can the sandboxed app even reach the real path it needs? (should be hidden by the private home)
plain = None
try:
    plain = open('/home/kata/Documents/picked.txt').read().strip()
except Exception as e:
    plain = 'BLOCKED(%s)' % type(e).__name__
print('plain-path-read:', plain)
# 2) the document portal: Add the picked file (as the file chooser does for a sandboxed caller)
fd = os.open(sys.argv[1], os.O_PATH)   # the document portal wants an O_PATH fd
fl = Gio.UnixFDList.new(); idx = fl.append(fd)
try:
    res, _ = bus.call_with_unix_fd_list_sync(
        'org.freedesktop.portal.Documents', '/org/freedesktop/portal/documents',
        'org.freedesktop.portal.Documents', 'Add',
        GLib.Variant('(hbb)', (idx, False, False)),
        GLib.VariantType('(s)'), Gio.DBusCallFlags.NONE, 4000, fl, None)
    doc_id = res.unpack()[0]
    print('doc-add:', doc_id)
except Exception as e:
    print('doc-add: ERR', str(e)[:120]); sys.exit(0)
# 3) read the handed-over file from the doc mount, inside the sandbox
import glob
cand = glob.glob('%s/doc/%s/*' % (os.environ['XDG_RUNTIME_DIR'], doc_id)) + \
       glob.glob('%s/doc/by-app/io.appkata.Sandboxed.docfit/%s/*' % (os.environ['XDG_RUNTIME_DIR'], doc_id))
got = 'none'
for p in cand:
    try: got = open(p).read().strip(); break
    except Exception as e: got = 'ERR(%s)' % e
print('doc-read:', got, '::', cand[:2])
PY

RT=$XDG_RUNTIME_DIR
base=(--ro-bind /usr /usr --symlink usr/lib /lib --symlink usr/lib64 /lib64 --symlink usr/bin /bin
  --ro-bind /etc /etc --proc /proc --dev /dev --tmpfs /tmp --dir $RT --bind $SBX $HOME
  --ro-bind $HOME/info/docfit /.flatpak-info --bind $RT/bus $RT/bus --setenv DBUS_SESSION_BUS_ADDRESS unix:path=$RT/bus
  --ro-bind $HOME/Documents/picked.txt /tmp/picked.txt            # the opened fd source (chooser-opened)
  --bind $RT/doc $RT/doc --unshare-user --unshare-ipc --unshare-uts --unshare-cgroup --die-with-parent --new-session
  --clearenv --setenv HOME $HOME --setenv PATH /usr/bin --setenv XDG_RUNTIME_DIR $RT --setenv LANG C.UTF-8 --chdir $HOME)
echo "== document portal handover for a synthetic .flatpak-info app"
bwrap "${base[@]}" python3 $HOME/doctest.py /tmp/picked.txt 2>&1 | sed 's/^/  /'

echo "== control: the SAME app WITHOUT /.flatpak-info (should not get a doc handover)"
base2=(--ro-bind /usr /usr --symlink usr/lib /lib --symlink usr/lib64 /lib64 --symlink usr/bin /bin
  --ro-bind /etc /etc --proc /proc --dev /dev --tmpfs /tmp --dir $RT --bind $SBX $HOME
  --bind $RT/bus $RT/bus --setenv DBUS_SESSION_BUS_ADDRESS unix:path=$RT/bus
  --ro-bind $HOME/Documents/picked.txt /tmp/picked.txt --bind $RT/doc $RT/doc
  --unshare-all --share-net --die-with-parent --new-session
  --clearenv --setenv HOME $HOME --setenv PATH /usr/bin --setenv XDG_RUNTIME_DIR $RT --setenv LANG C.UTF-8 --chdir $HOME)
bwrap "${base2[@]}" python3 $HOME/doctest.py /tmp/picked.txt 2>&1 | sed 's/^/  /'
