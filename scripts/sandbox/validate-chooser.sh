#!/bin/bash
# Part of the app-sandboxing review (docs/reviews/app-sandboxing-1.md finding 0, requirement 17.6.1).
# Runs inside the Mint 22.1 session container as the test user. End to end: a real generated AppKata
# launcher (online-app template) asks the FileChooser portal for a file; the gtk portal backend shows
# its dialog in headless sway; wtype answers it with ~/Documents/secret.txt; the portal hands the file
# over through the document portal; the sandboxed app reads it at $XDG_RUNTIME_DIR/doc/<id>/secret.txt.
#
# Result at the time of the finding, on xdg-desktop-portal 1.18+ (Mint 22.1 ships 1.20): the OpenFile
# call itself was refused, "Portal operation not allowed: Failed to open file
# .../.flatpak/<instance>/bwrapinfo.json", because the portal accepts a caller that presents
# /.flatpak-info only when its instance id names a running Flatpak's records. On 1.14 (Mint 21.3) the
# dialog appeared instead.
# Result since the decision (17.6.1, option a — the proxy carries no marker and allows the portal
# interfaces safe for a host caller, FileChooser not among them): the call is refused by the *proxy*,
# a bare "org.freedesktop.DBus.Error.AccessDenied", on every portal version; the launcher no longer
# sets GTK_USE_PORTAL, so a real app shows its own dialog instead of asking. Kept as the record of
# both outcomes; the automated version is test_the_portals_answer_a_sandboxed_app_as_a_host_caller
# in tests/test_sandbox_run.py.
#
# Run (from the repo root; the image is built by `scripts/test-sandbox.sh session`, or use the plain
# linuxmintd/mint22.1-amd64 image with SESS_PKGS from test-sandbox.sh installed):
#   docker run --rm --security-opt seccomp=unconfined --security-opt systempaths=unconfined \
#     --security-opt apparmor=unconfined --device /dev/fuse --cap-add SYS_ADMIN \
#     -v "$PWD/scripts/sandbox:/x:ro" -v "$PWD:/src:ro" appkata-sandbox-session \
#     sh -c 'u=$(id -u kata); mkdir -p /run/user/$u && chown kata:kata /run/user/$u; su kata -s /bin/bash -c "bash /x/validate-chooser.sh"'
set -u
. /x/session.sh
pgrep -f xdg-document-portal >/dev/null || { /usr/libexec/xdg-document-portal > /tmp/docportal.log 2>&1 & sleep 1.5; }
echo "doc mount: $(ls -d "$XDG_RUNTIME_DIR/doc" 2>&1)"
echo "xdg-desktop-portal: $(dpkg-query -W -f '${Version}' xdg-desktop-portal)"
mkdir -p "$HOME/Documents"; echo "TOP SECRET" > "$HOME/Documents/secret.txt"

# the "app": asks the portal for one file and reads whatever URI comes back
mkdir -p "$HOME/apps/fc/1.0/bin"
cat > "$HOME/apps/fc/1.0/open.py" <<'PY'
from gi.repository import Gio, GLib
bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
loop = GLib.MainLoop()
out = {}
def on_resp(conn, sender, path, iface, sig, params):
    code, results = params.unpack(); out['uris'] = results.get('uris'); print('RESPONSE', code, out['uris']); loop.quit()
uniq = bus.get_unique_name()[1:].replace('.', '_'); token = 'tok1'
bus.signal_subscribe('org.freedesktop.portal.Desktop', 'org.freedesktop.portal.Request', 'Response',
    f'/org/freedesktop/portal/desktop/request/{uniq}/{token}', None, Gio.DBusSignalFlags.NONE, on_resp)
try:
    bus.call_sync('org.freedesktop.portal.Desktop', '/org/freedesktop/portal/desktop',
        'org.freedesktop.portal.FileChooser', 'OpenFile',
        GLib.Variant('(ssa{sv})', ('', 'Pick', {'handle_token': GLib.Variant('s', token)})),
        None, Gio.DBusCallFlags.NONE, 10000, None)
except GLib.Error as e:
    print('REFUSED', e.message); raise SystemExit(3)
GLib.timeout_add_seconds(40, loop.quit); loop.run()
for u in out.get('uris') or []:
    p = u.replace('file://', '')
    try: print('READ', p, open(p).read().strip())
    except Exception as e: print('CANNOT READ', p, e)
PY
printf '#!/bin/sh\nexec python3 "$(dirname "$0")/../open.py"\n' > "$HOME/apps/fc/1.0/bin/app"; chmod +x "$HOME/apps/fc/1.0/bin/app"

# the real launcher AppKata would write for it
lp=$(PYTHONPATH=/src/src python3 -c '
import os
from appkata_core import sandbox as sb
print(sb.write_launcher("fc", "Fc", os.path.expanduser("~/apps"), os.path.expanduser("~/apps/fc/1.0"), "bin/app", sb.resolve_template("online-app")))')
echo "launcher: $lp"; grep -n 'doc/by-app\|GTK_USE_PORTAL\|flatpak-info' "$lp"

# answer the gtk chooser if it appears: ctrl+L opens the location entry, then the path, Enter
answer() { for _ in 1 2 3; do sleep 6; wtype -M ctrl l -m ctrl; sleep 0.5; wtype "$HOME/Documents/secret.txt"; sleep 0.5; wtype -k Return; sleep 1; wtype -k Return; done; }
( answer ) & ans=$!
timeout 60 "$lp" 2>&1 | grep -v '^$' | tail -5
kill "$ans" 2>/dev/null; wait "$ans" 2>/dev/null
echo "== portal's view of the hand-over:"; ls -R "$XDG_RUNTIME_DIR/doc/by-app/" 2>&1 | head -8
