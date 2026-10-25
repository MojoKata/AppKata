"""Which file dialog a GTK3, GTK4 and Qt 6 app shows inside a generated launcher (requirement 17.6.3).

Run by `scripts/test-sandbox.sh filedialogs` as the test user in the Mint 22.1 dialogs container:
Xvfb, a session bus with the real xdg-desktop-portal and its gtk backend, and three tiny apps --
GTK3 (`Gtk.FileChooserNative`), GTK4 (`Gtk.FileDialog`) and Qt 6 (`QFileDialog`, with the
xdgdesktopportal platform theme installed, and once more with it forced) -- each installed behind a
real `online-app` launcher from appkata_core.sandbox. Each app opens its dialog, waits, prints the
toplevel windows it can see and exits; the launcher's proxy runs with --log, so the portal calls the
app made are printed too. Three variants per app: the launcher as generated, with the Properties
interface allowed on the portal name, and with Properties plus FileChooser allowed -- which shows
which denial keeps each toolkit on its own dialog (round four of docs/reviews/app-sandboxing-1.md,
R4-5: for GTK4 it is the FileChooser denial, not Properties; GTK3 and Qt 6.4 never ask).
"""
import os
import re
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

GTK3 = """
import gi; gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib
n = Gtk.FileChooserNative.new("pick", None, Gtk.FileChooserAction.OPEN, None, None)
n.show()
def report():
    print("TOPLEVELS", [type(w).__name__ for w in Gtk.Window.list_toplevels() if w.get_visible()], flush=True); Gtk.main_quit()
GLib.timeout_add(4000, report); Gtk.main()
"""
GTK4 = """
import gi; gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib
app = Gtk.Application(application_id="io.appkata.gtk4")
def act(a):
    w = Gtk.ApplicationWindow(application=a); w.present()
    dlg = Gtk.FileDialog()
    dlg.open(w, None, lambda d, res: None)
    def report():
        print("TOPLEVELS", [type(x).__name__ for x in Gtk.Window.list_toplevels() if x.get_visible()], flush=True); a.quit()
    GLib.timeout_add(4000, report)
app.connect("activate", act); app.run([])
"""
QT6 = """
import sys
from PyQt6.QtWidgets import QApplication, QFileDialog, QWidget
from PyQt6.QtCore import QTimer, qVersion
app = QApplication(sys.argv); w = QWidget(); w.show()
dlg = QFileDialog(w, "pick"); dlg.open()
def report():
    print("TOPLEVELS", [x.metaObject().className() for x in QApplication.topLevelWidgets() if x.isVisible()], "qt", qVersion(), flush=True)
    app.quit()
QTimer.singleShot(4000, report)
app.exec()
"""
# What each (app, variant) must show (round six: a harness nobody asserts fails nothing); the script
# exits 1 on a mismatch. Every app and variant shows its own dialog as generated (17.6.3; the launcher's
# GDK_DEBUG=no-portals since round six, R6-4); only GTK4 with that flag removed and FileChooser allowed takes the portal's.
EXPECTED = {("gtk4", "portals on, FileChooser allowed"): "the portal's dialog"}      # the only portal road left, and only with the launcher's flag removed
VERDICTS = {}

APPS = (("gtk3", GTK3, {}), ("gtk4", GTK4, {}), ("qt6", QT6, {}),
        ("qt6-portaltheme", QT6, {"QT_QPA_PLATFORMTHEME": "xdgdesktopportal"}))
PROPS = "'--call=org.freedesktop.portal.Desktop=org.freedesktop.DBus.Properties.*@/org/freedesktop/portal/desktop' "
CHOOSER = "'--call=org.freedesktop.portal.Desktop=org.freedesktop.portal.FileChooser.*@/org/freedesktop/portal/desktop' "
VARIANTS = (("as generated", ""), ("Properties allowed", PROPS), ("Properties and FileChooser allowed", PROPS + CHOOSER),
            ("portals on, FileChooser allowed", "NOENV" + PROPS + CHOOSER))   # without the launcher's GDK_DEBUG=no-portals: the portal road GTK4 would take (R6-4)
OWN = {"FileChooserDialog", "QFileDialog"}


def install(name, script):
    d = f"{home}/apps/{name}/1.0/bin"
    os.makedirs(d, exist_ok=True)
    with open(f"{d}/app.py", "w") as f:
        f.write(script)
    with open(f"{d}/app", "w") as f:
        f.write(f"#!/bin/sh\nexec python3 {d}/app.py\n")
    os.chmod(f"{d}/app", 0o755)
    return sb.write_launcher(name, name, f"{home}/apps", f"{home}/apps/{name}/1.0", "bin/app", sb.resolve_template("online-app"))


def portal_windows():
    r = subprocess.run(["xwininfo", "-root", "-tree"], capture_output=True, text=True)
    return [l.strip() for l in r.stdout.splitlines() if "xdg-desktop-portal-gtk" in l and "10x10" not in l]


procs = [subprocess.Popen(["Xvfb", ":99", "-screen", "0", "1280x800x24"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL),
         subprocess.Popen(["dbus-daemon", "--session", f"--address={addr}", "--nofork", "--nopidfile"],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)]
time.sleep(1)
os.makedirs(f"{home}/.config/xdg-desktop-portal", exist_ok=True)
with open(f"{home}/.config/xdg-desktop-portal/portals.conf", "w") as f:
    f.write("[preferred]\ndefault=gtk\n")


def backend():
    return subprocess.Popen(["/usr/libexec/xdg-desktop-portal-gtk"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


procs.append(backend())
time.sleep(1)
procs.append(subprocess.Popen(["/usr/libexec/xdg-desktop-portal"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
time.sleep(2)
r = subprocess.run(["gdbus", "call", "--session", "--dest", "org.freedesktop.portal.Desktop", "--object-path",
                    "/org/freedesktop/portal/desktop", "--method", "org.freedesktop.DBus.Properties.Get",
                    "org.freedesktop.portal.FileChooser", "version"], capture_output=True, text=True)
print("host: FileChooser version", r.stdout.strip() or r.stderr.strip(), flush=True)
print("host: Qt platform themes", sorted(os.listdir("/usr/lib/x86_64-linux-gnu/qt6/plugins/platformthemes")), flush=True)

for name, script, extra in APPS:
    for k, v in extra.items():
        os.environ[k] = v
    lp = install(name, script)
    generated = open(lp).read().replace('xdg-dbus-proxy "$upstream" "$sock" ', 'xdg-dbus-proxy "$upstream" "$sock" --log ', 1)
    for variant, rules in VARIANTS:
        with open(lp, "w") as f:
            f.write(generated.replace('--setenv GDK_DEBUG no-portals \\\n', '', 1).replace("--filter ", "--filter " + rules[5:], 1) if rules.startswith("NOENV")
                    else generated.replace("--filter ", "--filter " + rules, 1))
        p = subprocess.Popen([lp], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        time.sleep(3)
        on_host = portal_windows()
        try:
            out, err = p.communicate(timeout=20)
        except subprocess.TimeoutExpired:
            p.kill()
            out, err = p.communicate()
        tops = re.search(r"TOPLEVELS (\[.*?\])", out)
        tops = eval(tops.group(1)) if tops else []        # noqa: S307 -- our own print
        calls = [m for m in re.findall(r"call (org\.freedesktop\.(?:portal\.FileChooser|DBus\.Properties)\.\w+)", out)]
        verdict = ("its own dialog" if OWN & set(tops) else "the portal's dialog" if on_host else "no dialog")
        print(f"{name:16} {variant:36} -> {verdict:20} portal calls: {sorted(set(calls)) or 'none'}"
              + (f"   app said: {(err.strip().splitlines() or [''])[-1][:90]}" if verdict == "no dialog" else ""), flush=True)
        VERDICTS[(name, variant)] = verdict
        subprocess.run(["pkill", "-f", "xdg-desktop-portal-gtk"], stdout=subprocess.DEVNULL)      # closes a portal dialog left open
        procs.append(backend())
        time.sleep(1)
    for k in extra:
        del os.environ[k]
# Links: Qt's own road to the host (17.6.3: Qt calls the OpenURI portal itself when it sees
# /.flatpak-info, xdg-open only as a fallback). With the harness's handler registered on the host
# (scripts/sandbox/register-test-handler.sh, run as root by the mode), QDesktopServices.openUrl from
# a sandboxed Qt app must leave the handler's mark in the *host* home, not the sandbox's.
QT_LINK = """
import sys
from PyQt6.QtCore import QUrl, QTimer
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import QApplication
app = QApplication(sys.argv)
print("opened:", QDesktopServices.openUrl(QUrl("https://example.com/from-qt")), flush=True)
QTimer.singleShot(3000, app.quit); app.exec()
"""
mark_host = f"{home}/appkata-test-handler-ran"
if os.path.exists("/usr/share/applications/appkata-test-handler.desktop"):
    for p in (mark_host, os.path.join(sb.sandbox_home("qtlink"), "appkata-test-handler-ran")):
        if os.path.exists(p):
            os.unlink(p)
    lp = install("qtlink", QT_LINK)
    r = subprocess.run([lp], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=30)
    time.sleep(2)
    ran = open(mark_host).read().strip().replace("ran inside: ", "") if os.path.exists(mark_host) else ""
    inside = os.path.exists(os.path.join(sb.sandbox_home("qtlink"), "appkata-test-handler-ran"))
    verdict = "the host handler ran" if ran and not inside else "RAN INSIDE THE SANDBOX" if inside else "the host handler did not run"
    print(f"{'qt link':16} {'as generated':36} -> {verdict:20} {ran} ({(r.stdout.strip().splitlines() or [''])[-1]})", flush=True)
    VERDICTS[("qt link", "as generated")] = verdict
    EXPECTED[("qt link", "as generated")] = "the host handler ran"
else:
    print("qt link: no test handler registered on this host (scripts/sandbox/register-test-handler.sh); skipped", flush=True)

bad = [f"{k}: wanted {EXPECTED.get(k, 'its own dialog')!r}, got {v!r}" for k, v in VERDICTS.items() if v != EXPECTED.get(k, "its own dialog")]
bad += [f"missing: {k}" for k in [(n, v) for n, _, _ in APPS for v, _ in VARIANTS] if k not in VERDICTS]
print("EXPECTED:", "ok" if not bad else "FAILED -- " + "; ".join(bad), flush=True)
for p in procs:
    p.terminate()
sys.exit(0 if ok else 1) if False else sys.exit(0 if not bad else 1)
