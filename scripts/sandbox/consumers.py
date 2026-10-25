"""Real consumers of the sandbox's desktop integration, behind generated launchers (17.5.1, 17.6.3).

Run by `scripts/test-sandbox.sh consumers` as the test user in the Mint 22.1 consumers container:
Xvfb, a session bus with the real xdg-desktop-portal and its gtk backend, dunst as the
notification daemon (a stand-in that records what it is asked to show where dunst is absent), and the test handler
for https links registered on the host (scripts/sandbox/register-test-handler.sh). Three things
the run tests assert through proxy rules and stand-in services are done here with the real stack:

- a GLib app sends a notification (Gio.Notification -> the Notification portal -> the gtk backend
  -> the host's notification daemon): shown for an online-app (the capability), silently not for
  an offline-editor (round three, R3-6);
- a GTK3 app opens a link (Gtk.show_uri -> no handler in view -> the OpenURI portal -> the host's
  handler, on the host): the handler's mark lands in the host's home, never in the sandbox's
  (round three, R3-1); a GTK4 app too (GtkUriLauncher, with GTK's own portal road turned off by
  the launcher's GDK_DEBUG=no-portals, round six R6-4: GLib's road still reaches the host);
- an app opens a *file* on the host, through AppKata's xdg-open (a descriptor to OpenURI.OpenFile)
  and through `gio open`, with the real portal and its gtk backend: a file in a granted folder
  reaches the host's text handler by its host path, with no chooser when that handler is the
  only one (the portal asks only between several candidates); a file in the private home is
  refused, since the portal can't locate it on the host (round five, R5-5 and R5-6: every file
  claim in 17.6.3 rested on a stand-in portal before);
- Chromium opens a file chooser (a file input clicked with xdotool): its own GTK dialog as
  generated; with the Properties interface allowed it reads FileChooser's `version`, takes the
  portal road, is refused OpenFile and shows nothing; with FileChooser allowed too, the portal's
  dialog (round four, R4-5: the one toolkit for which the Properties denial is load-bearing).
"""
import json
import os
import re
import shutil

# What each verdict line must say (round six: a harness nobody asserts fails nothing). The script
# exits 1 when any expected line is missing or any line says FAILS/LEAKED/INSIDE unexpectedly.
EXPECTED = (
    ("notify  online-app", "shown on the host"), ("notify  offline-editor", "nothing reached the host daemon"),
    ("gtk3 link online-app", "the host handler ran: https://example.com/from-gtk3"),
    ("gtk4 link online-app", "the host handler ran: https://example.com/from-gtk4"),
    ("qt link online-app", "the host handler ran: https://example.com/from-qt"),
    ("electron (Obsidian)", "maps its window"),
    ("file via xdg-open (the shim)", "the host handler ran on the host path"), ("file via xdg-open (the shim)", "no chooser"),
    ("file via gio open", "the host handler ran on the host path"), ("file via gio open", "no chooser"),
    ("file in the private home", "refused by the portal; the shim failed as it should"),
    ("chromium as generated", "its own GTK dialog"), ("chromium Properties allowed", "no dialog"),
    ("chromium Properties and FileChooser allowed", "the portal's dialog"),
)
VERDICTS = []
_print = print


def print(*a, **k):                      # noqa: A001 -- every verdict line goes through here
    line = " ".join(str(x) for x in a)
    VERDICTS.append(line)
    _print(*a, **k)


def check():
    bad = []
    for prefix, need in EXPECTED:
        hits = [l for l in VERDICTS if l.startswith(prefix)]
        if not hits:
            if prefix.startswith("chromium") and any("not installed" in l for l in VERDICTS):
                continue
            if prefix.startswith("electron") and any("not present" in l for l in VERDICTS):
                continue
            bad.append(f"missing: {prefix}")
        elif not any(need in l for l in hits):
            bad.append(f"{prefix}: wanted '{need}', got {hits[-1][len(prefix):].strip()!r}")
    bad += [f"unexpected: {l}" for l in VERDICTS if "AND IT RAN INSIDE" in l or "OPENED ON THE HOST" in l]
    _print("EXPECTED:", "ok" if not bad else "FAILED -- " + "; ".join(bad), flush=True)
    return not bad
import subprocess
import sys
import time

sys.path.insert(0, "/src/src")
os.environ["HOME"] = home = os.path.expanduser("~")
os.environ["XDG_RUNTIME_DIR"] = rt = f"/run/user/{os.getuid()}"
os.environ["DISPLAY"] = ":99"
os.environ["XDG_CURRENT_DESKTOP"] = "X-Generic"
os.environ["XDG_SESSION_TYPE"] = "x11"
os.environ["GTK_A11Y"] = "none"
os.environ.pop("WAYLAND_DISPLAY", None)
addr = f"unix:path={rt}/bus"
os.environ["DBUS_SESSION_BUS_ADDRESS"] = addr
from appkata_core import sandbox as sb   # noqa: E402

NOTIFY_DAEMON = """
import sys
from gi.repository import Gio, GLib
XML = '''<node><interface name="org.freedesktop.Notifications">
<method name="Notify"><arg type="s" direction="in"/><arg type="u" direction="in"/><arg type="s" direction="in"/><arg type="s" direction="in"/>
<arg type="s" direction="in"/><arg type="as" direction="in"/><arg type="a{sv}" direction="in"/><arg type="i" direction="in"/><arg type="u" direction="out"/></method>
<method name="GetCapabilities"><arg type="as" direction="out"/></method>
<method name="GetServerInformation"><arg type="s" direction="out"/><arg type="s" direction="out"/><arg type="s" direction="out"/><arg type="s" direction="out"/></method>
<method name="CloseNotification"><arg type="u" direction="in"/></method>
</interface></node>'''
log = open(sys.argv[1], "a")
def call(conn, sender, path, iface, method, params, inv):
    if method == "Notify":
        p = params.unpack(); log.write(f"NOTIFY app={p[0]!r} summary={p[3]!r} body={p[4]!r}\\n"); log.flush()
        inv.return_value(GLib.Variant("(u)", (1,)))
    elif method == "GetCapabilities":
        inv.return_value(GLib.Variant("(as)", (["body"],)))
    elif method == "GetServerInformation":
        inv.return_value(GLib.Variant("(ssss)", ("stand-in", "appkata", "1", "1.2")))
    else:
        inv.return_value(None)
bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
bus.register_object("/org/freedesktop/Notifications", Gio.DBusNodeInfo.new_for_xml(XML).interfaces[0], call, None, None)
Gio.bus_own_name_on_connection(bus, "org.freedesktop.Notifications", Gio.BusNameOwnerFlags.NONE, None, None)
GLib.MainLoop().run()
"""

NOTIFY_APP = """
import sys
from gi.repository import Gio, GLib
app = Gio.Application(application_id=sys.argv[1], flags=Gio.ApplicationFlags.NON_UNIQUE)
def act(a):
    a.hold()
    n = Gio.Notification.new("hello from " + sys.argv[1]); n.set_body("sent from inside the sandbox")
    a.send_notification("t", n)
    GLib.timeout_add(3000, a.release)
app.connect("activate", act); app.run([])
"""

GTK4_LINK = """
import sys
import gi; gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib
app = Gtk.Application(application_id=sys.argv[1])        # the app's own identity: the one name the proxy lets it own (17.5)
def act(a):
    w = Gtk.ApplicationWindow(application=a); w.present()
    Gtk.UriLauncher(uri="https://example.com/from-gtk4").launch(w, None, lambda l, r: print("launch:", "ok" if l.launch_finish(r) else "failed", flush=True))
    GLib.timeout_add(4000, a.quit)
app.connect("activate", act); app.run([])
"""

QT_LINK = """
import sys
from PyQt6.QtCore import QUrl, QTimer
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import QApplication
app = QApplication(sys.argv)
print("opened:", QDesktopServices.openUrl(QUrl("https://example.com/from-qt")), flush=True)
QTimer.singleShot(3000, app.quit); app.exec()
"""

GTK3_LINK = """
import gi; gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib
Gtk.show_uri_on_window(None, "https://example.com/from-gtk3", 0)
GLib.timeout_add(4000, Gtk.main_quit); Gtk.main()
"""

CHROMIUM = ("exec chromium --no-first-run --no-default-browser-check --disable-gpu --disable-dev-shm-usage --disable-features=TranslateUI "
            "--window-position=0,0 --window-size=600,400 "
            "'data:text/html,<input type=file style=\"position:fixed;left:0;top:0;width:500px;height:300px\">'\n")

PROPS = "'--call=org.freedesktop.portal.Desktop=org.freedesktop.DBus.Properties.*@/org/freedesktop/portal/desktop' "
CHOOSER = "'--call=org.freedesktop.portal.Desktop=org.freedesktop.portal.FileChooser.*@/org/freedesktop/portal/desktop' "
VARIANTS = (("as generated", ""), ("Properties allowed", PROPS), ("Properties and FileChooser allowed", PROPS + CHOOSER))


def install(name, template, script=None, args="", program=None, log=False, grants=None):
    """A tiny app behind a generated launcher: a Python `script` (written into the app's own
    folder, the only one of the host's the sandbox sees) or a shell `program`. `grants`: a grant
    set to use instead of the template's."""
    d = f"{home}/apps/{name}/1.0/bin"
    os.makedirs(d, exist_ok=True)
    if script is not None:
        with open(f"{d}/app.py", "w") as f:
            f.write(script)
        program = f"exec python3 {d}/app.py {args}\n"
    with open(f"{d}/app", "w") as f:
        f.write("#!/bin/sh\n" + program)
    os.chmod(f"{d}/app", 0o755)
    lp = sb.write_launcher(name, name, f"{home}/apps", f"{home}/apps/{name}/1.0", "bin/app", grants or sb.resolve_template(template))
    if log:
        text = open(lp).read().replace('xdg-dbus-proxy "$upstream" "$sock" ', 'xdg-dbus-proxy "$upstream" "$sock" --log ', 1)
        with open(lp, "w") as f:
            f.write(text)
    return lp


def windows(pattern):
    r = subprocess.run(["xwininfo", "-root", "-tree"], capture_output=True, text=True)
    return [l.strip() for l in r.stdout.splitlines() if re.search(pattern, l) and "10x10" not in l]


procs = [subprocess.Popen(["Xvfb", ":99", "-screen", "0", "1280x800x24"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL),
         subprocess.Popen(["dbus-daemon", "--session", f"--address={addr}", "--nofork", "--nopidfile"],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)]
time.sleep(1)
os.makedirs(f"{home}/.config/xdg-desktop-portal", exist_ok=True)
with open(f"{home}/.config/xdg-desktop-portal/portals.conf", "w") as f:
    f.write("[preferred]\ndefault=gtk\n")
notify_log = f"{home}/notifications.log"
DUNST = shutil.which("dunst") is not None            # a real notification daemon where the image has one (round seven)
if DUNST:
    procs.append(subprocess.Popen(["dunst"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
else:
    procs.append(subprocess.Popen(["python3", "-c", NOTIFY_DAEMON, notify_log], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
procs.append(subprocess.Popen(["/usr/libexec/xdg-desktop-portal-gtk"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
time.sleep(1)
procs.append(subprocess.Popen(["/usr/libexec/xdg-desktop-portal"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
time.sleep(2)
print("host: handler for https:", subprocess.run(["gio", "mime", "x-scheme-handler/https"], capture_output=True, text=True).stdout.splitlines()[0], flush=True)

# 1. notifications, with and without the capability
for name, template in (("web", "online-app"), ("ed", "offline-editor")):
    open(notify_log, "w").close()
    if DUNST:
        subprocess.run(["dunstctl", "history-clear"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    lp = install(name, template, NOTIFY_APP, sb.app_identity(name))
    r = subprocess.run([lp], capture_output=True, text=True, timeout=30)
    time.sleep(1)
    if DUNST:
        subprocess.run(["dunstctl", "close-all"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)   # history lists closed ones
        time.sleep(0.3)
        hist = json.loads(subprocess.run(["dunstctl", "history"], capture_output=True, text=True).stdout or '{"data": [[]]}')
        shown = [f"dunst: {n['summary']['data']!r} {n['body']['data']!r}" for n in hist.get("data", [[]])[0]]
    else:
        shown = [l for l in open(notify_log).read().splitlines() if "NOTIFY" in l]
    print(f"notify  {template:16} -> {'shown on the host: ' + shown[0] if shown else 'nothing reached the host daemon'}", flush=True)

# 2. a GTK3 app opens a link
mark_host, mark_inside = f"{home}/appkata-test-handler-ran", os.path.join(sb.sandbox_home("gtk3"), "appkata-test-handler-ran")
for p in (mark_host, mark_inside):
    if os.path.exists(p):
        os.unlink(p)
lp = install("gtk3", "online-app", GTK3_LINK)
subprocess.run([lp], capture_output=True, text=True, timeout=30)
time.sleep(2)
on_host = open(mark_host).read().strip().replace("ran inside: ", "") if os.path.exists(mark_host) else ""     # the handler's own wording
print(f"gtk3 link online-app      -> {'the host handler ran: ' + on_host if on_host else 'the host handler did not run'}"
      f"{'; AND IT RAN INSIDE THE SANDBOX' if os.path.exists(mark_inside) else ''}", flush=True)

# 2a. a GTK4 app opens a link (GtkUriLauncher; with the launcher's GDK_DEBUG=no-portals it does not take
# GTK's portal road but GLib's, which asks the OpenURI portal when no handler is in view -- R6-4)
mark_inside4 = os.path.join(sb.sandbox_home("gtk4"), "appkata-test-handler-ran")
for p in (mark_host, mark_inside4):
    if os.path.exists(p):
        os.unlink(p)
lp = install("gtk4", "online-app", GTK4_LINK, sb.app_identity("gtk4"))
r = subprocess.run([lp], capture_output=True, text=True, timeout=30)
time.sleep(2)
on_host = open(mark_host).read().strip().replace("ran inside: ", "") if os.path.exists(mark_host) else ""
print(f"gtk4 link online-app      -> {'the host handler ran: ' + on_host if on_host else 'the host handler did not run'}"
      f"{'; AND IT RAN INSIDE THE SANDBOX' if os.path.exists(mark_inside4) else ''} ({(r.stdout.strip().splitlines() or ['no launch result'])[-1]}; "
      f"stderr: {(r.stderr.strip().splitlines() or [''])[-1][:120]})", flush=True)

# 2c. a Qt app opens a link (QDesktopServices.openUrl: Qt calls the OpenURI portal itself when it sees
# /.flatpak-info, xdg-open only as a fallback -- 17.6.3, read until round seven ran it)
mark_insideq = os.path.join(sb.sandbox_home("qtlink"), "appkata-test-handler-ran")
for p in (mark_host, mark_insideq):
    if os.path.exists(p):
        os.unlink(p)
try:
    import PyQt6  # noqa: F401
    lp = install("qtlink", "online-app", QT_LINK)
    r = subprocess.run([lp], capture_output=True, text=True, timeout=30)
    time.sleep(2)
    on_host = open(mark_host).read().strip().replace("ran inside: ", "") if os.path.exists(mark_host) else ""
    print(f"qt link online-app        -> {'the host handler ran: ' + on_host if on_host else 'the host handler did not run'}"
          f"{'; AND IT RAN INSIDE THE SANDBOX' if os.path.exists(mark_insideq) else ''} ({(r.stdout.strip().splitlines() or ['no result'])[-1]})", flush=True)
except ImportError:
    print("qt link: PyQt6 not installed in this image", flush=True)

# 2b. files opened on the host through AppKata's xdg-open and through gio, with the real portal
FILES = ('echo "from the sandbox" > "$HOME/Documents/note.txt"; echo "private" > "$HOME/private.txt"\n'
         'xdg-open "$HOME/Documents/note.txt" && echo SHIM-OK; sleep 2\n'
         'gio open "$HOME/Documents/note.txt" && echo GIO-OK; sleep 2\n'
         'xdg-open "$HOME/private.txt" 2>&1 && echo PRIVATE-OK; true\n')
os.makedirs(f"{home}/Documents", exist_ok=True)
mark_inside = os.path.join(sb.sandbox_home("files"), "appkata-test-handler-ran")
for p in (mark_host, mark_inside, f"{home}/Documents/note.txt"):
    if os.path.exists(p):
        os.unlink(p)
lp = install("files", "online-app", program=FILES,
             grants=sb.apply_overrides(sb.resolve_template("online-app"), {"folders": {"+~/Documents": "rw"}}))
print("host: handler for text/plain:", subprocess.run(["gio", "mime", "text/plain"], capture_output=True, text=True).stdout.splitlines()[0], flush=True)
r = subprocess.run([lp], capture_output=True, text=True, timeout=60)
time.sleep(2)
chooser = windows(r'\("xdg-desktop-portal-gtk"')
ran = [l.replace("ran inside: ", "") for l in open(mark_host).read().splitlines()] if os.path.exists(mark_host) else []
for road, ok in (("xdg-open (the shim)", "SHIM-OK"), ("gio open", "GIO-OK")):
    hit = [l for l in ran if l == f"{home}/Documents/note.txt"]
    print(f"file via {road:18} online-app + ~/Documents -> "
          f"{'the host handler ran on the host path' if hit else 'the host handler did not run'}"
          f"{' (' + ok + ' from inside)' if ok in r.stdout else ' (the call failed inside)'}"
          f"{'; a chooser appeared' if chooser else '; no chooser (the only handler)'}"
          f"{'; AND IT RAN INSIDE THE SANDBOX' if os.path.exists(mark_inside) else ''}", flush=True)
    ran = ran[1:] if hit else ran
private = [l for l in r.stdout.splitlines() if l.startswith("AppKata:")]
print(f"file in the private home            -> "
      f"{'OPENED ON THE HOST' if any(l.endswith('/private.txt') for l in ran) else 'refused by the portal'}"
      f"{'; and the shim reported success' if 'PRIVATE-OK' in r.stdout else '; the shim failed as it should'}: "
      f"{(private or ['(no message)'])[-1][-110:]}", flush=True)

# 2d. Electron itself: Obsidian's AppImage (build/sandbox-test/, fetched by the gui/session modes) behind a
# generated launcher -- unpacked by the launcher, started, its window mapped. Its file dialog needs a
# click on its start screen and stays the field's; Chromium 154 below is the same dialog code.
OBSIDIAN = "/src/build/sandbox-test/obsidian.AppImage"
if os.path.exists(OBSIDIAN):
    target = f"{home}/apps/obsidian"
    os.makedirs(target, exist_ok=True)
    img = f"{target}/Obsidian.AppImage"
    if not os.path.exists(img):
        subprocess.run(["cp", OBSIDIAN, img]); os.chmod(img, 0o755)
    lp = sb.write_launcher("obsidian", "Obsidian", f"{home}/apps", sb.extracted_dir(target, "1.0"), "AppRun",
                           sb.resolve_template("online-app"), img)
    text = open(lp).read().replace('xdg-dbus-proxy "$upstream" "$sock" ', 'xdg-dbus-proxy "$upstream" "$sock" --log ', 1)
    with open(lp, "w") as f:
        f.write(text)
    p = subprocess.Popen([lp, "--no-sandbox", "--disable-gpu"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    win = []
    for _ in range(45):
        time.sleep(2)
        win = windows(r'"Obsidian"') or windows(r'\("obsidian"')
        if win:
            break
    subprocess.run(["pkill", "-f", "obsidian"], stdout=subprocess.DEVNULL)
    try:
        out, _ = p.communicate(timeout=20)
    except subprocess.TimeoutExpired:
        p.kill(); out, _ = p.communicate()
    unpacked = os.path.isdir(sb.extracted_dir(target, "1.0"))
    print(f"electron (Obsidian)       -> {'maps its window' if win else 'no window'} behind the generated launcher; "
          f"{'unpacked by the launcher' if unpacked else 'NOT unpacked'}; proxy saw: {sorted(set(re.findall(r'call (org[.]freedesktop[.][A-Za-z.]+)', out)))[:4] or 'nothing'}", flush=True)
else:
    print("electron (Obsidian): build/sandbox-test/obsidian.AppImage not present (scripts/test-sandbox.sh gui fetches it)", flush=True)

# 3. Chromium's file chooser, three proxy variants
if subprocess.run(["which", "chromium"], capture_output=True).returncode == 0:
    lp = install("chromium", "online-app", program=CHROMIUM, log=True)
    generated = open(lp).read()
    for variant, rules in VARIANTS:
        with open(lp, "w") as f:
            f.write(generated.replace("--filter ", "--filter " + rules, 1))
        p = subprocess.Popen([lp], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        time.sleep(10)
        subprocess.run(["xdotool", "mousemove", "250", "220", "click", "1"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(5)
        own = windows(r'"Open File".*\("chromium"')
        portal = windows(r'\("xdg-desktop-portal-gtk"')
        subprocess.run(["pkill", "-f", "chromium"], stdout=subprocess.DEVNULL)
        try:
            out, _ = p.communicate(timeout=15)
        except subprocess.TimeoutExpired:
            p.kill(); out, _ = p.communicate()
        calls = sorted(set(re.findall(r"call (org\.freedesktop\.(?:portal\.FileChooser|DBus\.Properties)\.\w+)", out)))
        verdict = "its own GTK dialog" if own else "the portal's dialog" if portal else "no dialog"
        print(f"chromium {variant:36} -> {verdict:20} portal calls: {calls or 'none'}", flush=True)
        subprocess.run(["pkill", "-f", "xdg-desktop-portal-gtk"], stdout=subprocess.DEVNULL)
        procs.append(subprocess.Popen(["/usr/libexec/xdg-desktop-portal-gtk"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        time.sleep(1)
else:
    print("chromium: not installed in this image", flush=True)
ok = check()
for p in procs:
    p.terminate()
sys.exit(0 if ok else 1)
