"""The generated launcher under a real Wayland compositor and a real PipeWire (round five,
"Coverage after round five": stand-ins with a real counterpart).

Run by `scripts/test-sandbox.sh wayland` as the test user in the round-2 session image
(`appkata-sandbox-session`: headless sway, PipeWire with WirePlumber and its PulseAudio server, the
portals), after `scripts/sandbox/session.sh` has started the session. The run tests bind a listening
socket as "the Wayland display" and never play a sound; here real apps run behind launchers
AppKata generates:

- a GTK3 app maps a window on sway (seen in sway's tree by its app_id), and on headless mutter;
- the Xwayland cookie (17.9): from a sandboxed app with the network and the X11 grant off, an
  unauthenticated X11 connection over the abstract socket is accepted by sway's Xwayland (no
  -auth) and refused by mutter's (-auth) -- the compositor's cookie is what "off" rests on;
- an app with the sound grant plays a tone through PipeWire, which sees it as a sandboxed client
  (`pipewire.access = flatpak`, the app's identity as the portal app id -- 17.8); the same app
  without the grant has no socket to play through;
- the same app records (17.8 says play-only can't be enforced; shown rather than inferred).
"""
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, "/src/src")
home = os.environ["HOME"]; rt = os.environ["XDG_RUNTIME_DIR"]
from appkata_core import sandbox as sb   # noqa: E402

GTK3_WINDOW = """
import gi; gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib
w = Gtk.Window(title="appkata-wayland-probe"); w.set_default_size(300, 200); w.show_all()
GLib.timeout_add(6000, Gtk.main_quit); Gtk.main()
print("backend:", type(w.get_window()).__name__)
"""


def install(name, gs, program):
    d = f"{home}/apps/{name}/1.0/bin"
    os.makedirs(d, exist_ok=True)
    with open(f"{d}/app", "w") as f:
        f.write("#!/bin/sh\n" + program)
    os.chmod(f"{d}/app", 0o755)
    return sb.write_launcher(name, name, f"{home}/apps", f"{home}/apps/{name}/1.0", "bin/app", gs)


# What each verdict must be (round six: a harness nobody asserts fails nothing); the script exits 1
# on a mismatch. LEAKED for the recording is what 17.8 states, not a failure.
EXPECTED = {"a GTK3 app maps a window on sway behind the generated launcher": "WORKS",
            "the same GTK3 app maps a window on mutter (headless)": "WORKS",
            "sway's Xwayland (no -auth): an unauthenticated connection over the abstract socket": "LEAKED",   # 17.9 says so
            "mutter's Xwayland (-auth): the same connection": "BLOCKED",
            "sway: a sandboxed app reads what the user copied (wl-paste)": "LEAKED",       # 17.9: wlroots leaks the clipboard
            "mutter: a sandboxed app reads what the user copied (wl-paste)": "BLOCKED",
            "online-app: plays a tone through PipeWire": "WORKS",
            "offline-editor: no sound grant, so no socket to play through": "BLOCKED",
            "online-app (play only): records from the same sockets": "LEAKED",
            # what AppKata reads from each compositor's globals for the warning (17.9; review 2, F7)
            "sway: what AppKata reads from its globals": "capture,clipboard,input",
            "mutter: what AppKata reads from its globals": "nothing"}
VERDICTS = {}


def say(verdict, what, detail=""):
    VERDICTS[what.split(" (")[0] if what.startswith("online-app: plays") else what] = verdict
    print(f"  {verdict:8} {what:60} {detail}", flush=True)


print(f"session: WAYLAND_DISPLAY={os.environ.get('WAYLAND_DISPLAY')} sway={'yes' if os.environ.get('SWAYSOCK') else 'no'} "
      f"pipewire={'yes' if os.path.exists(f'{rt}/pipewire-0') else 'no'} pulse={'yes' if os.path.exists(f'{rt}/pulse/native') else 'no'}", flush=True)

# 1. a GTK3 window on sway, behind a generated launcher
os.makedirs(f"{home}/apps/gtkwin/1.0/bin", exist_ok=True)
with open(f"{home}/apps/gtkwin/1.0/bin/app.py", "w") as f:
    f.write(GTK3_WINDOW)
lp = install("gtkwin", sb.resolve_template("online-app"), f"exec python3 {home}/apps/gtkwin/1.0/bin/app.py\n")
p = subprocess.Popen([lp], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
time.sleep(3)
tree = subprocess.run(["swaymsg", "-t", "get_tree"], capture_output=True, text=True).stdout
nodes = [n for n in json.dumps(json.loads(tree or "{}")).split('"name": ') if "appkata-wayland-probe" in n[:60]]
out, err = p.communicate(timeout=20)
mapped = "appkata-wayland-probe" in tree
say("WORKS" if mapped else "FAILS", "a GTK3 app maps a window on sway behind the generated launcher",
    out.strip().splitlines()[-1] if out.strip() else err.strip().splitlines()[-1] if err.strip() else "")

# 1b. the same window under headless mutter (GNOME's compositor; the one 17.9 calls clear), on its own
# display beside sway's: the launcher binds whichever socket $WAYLAND_DISPLAY names
mutter = subprocess.Popen(["mutter", "--headless", "--wayland", "--no-x11", "--virtual-monitor", "1280x800",
                           "--wayland-display", "wayland-9"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
for _ in range(50):
    if os.path.exists(f"{rt}/wayland-9"):
        break
    time.sleep(0.2)
with open(f"{home}/apps/gtkwin/1.0/bin/app.py", "w") as f:
    f.write(GTK3_WINDOW.replace('w.show_all()', 'w.connect("map-event", lambda *a: print("MAPPED", flush=True)); w.show_all()'))
r = subprocess.run([lp], env={**os.environ, "WAYLAND_DISPLAY": "wayland-9"}, capture_output=True, text=True, timeout=30)
say("WORKS" if "MAPPED" in r.stdout and "GdkWaylandWindow" in r.stdout else "FAILS",
    "the same GTK3 app maps a window on mutter (headless)", (r.stdout.strip().splitlines() or [r.stderr.strip()[-80:]])[-1])
mutter.terminate()

# 1c. the Xwayland cookie (17.9, R4-8): with the network grant and the X11 grant off, the X server's
# abstract socket is still reachable; what keeps the app out is Xwayland requiring the cookie. A
# second sway with Xwayland on (no -auth) and a mutter with Xwayland on (-auth): a sandboxed app
# sends an X11 connection setup with no authorization to every abstract socket it can reach.
os.makedirs(f"{home}/.config/sway2", exist_ok=True)
with open(f"{home}/.config/sway2/config", "w") as f:
    f.write("xwayland enable\noutput HEADLESS-1 resolution 1280x800\n")
sway2 = subprocess.Popen(["sway", "-c", f"{home}/.config/sway2/config"], env={**os.environ, "WLR_BACKENDS": "headless", "WLR_RENDERER": "pixman",
                         "WLR_LIBINPUT_NO_DEVICES": "1", "WAYLAND_DISPLAY": "wayland-5"}, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
mutter2 = subprocess.Popen(["mutter", "--headless", "--wayland", "--virtual-monitor", "1280x800", "--wayland-display", "wayland-6"],
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
time.sleep(4)
os.makedirs(f"{home}/apps/xprobe/1.0/bin", exist_ok=True)
with open(f"{home}/apps/xprobe/1.0/bin/probe.py", "w") as f:
    f.write(r"""
import socket, struct
for n in range(0, 6):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM); s.settimeout(2)
    try:
        s.connect("\0/tmp/.X11-unix/X%d" % n)
    except OSError:
        continue
    s.sendall(struct.pack("<BxHHHHxx", ord("l"), 11, 0, 0, 0))
    r = s.recv(64)
    print("display :%d -> %s" % (n, {0: "REFUSED", 1: "ACCEPTED", 2: "AUTHENTICATE"}.get(r[0], r[0])), flush=True)
""")
gs = sb.resolve_template("online-app"); gs["devices"] = set()                  # the network, the X11 grant off
lp = install("xprobe", gs, f"exec python3 {home}/apps/xprobe/1.0/bin/probe.py\n")
env = {**os.environ}; env.pop("DISPLAY", None)
r = subprocess.run([lp], env=env, capture_output=True, text=True, timeout=30)
answers = dict(l.split(" -> ") for l in r.stdout.strip().splitlines() if " -> " in l)
sway_x = next((d for d in sorted(answers) if d == "display :0"), None)                 # sway took :0 (the first)
mutter_x = [d for d in sorted(answers) if d != "display :0"]
say("LEAKED" if answers.get("display :0") == "ACCEPTED" else "BLOCKED", "sway's Xwayland (no -auth): an unauthenticated connection over the abstract socket", answers.get("display :0", "no socket"))
say("BLOCKED" if mutter_x and all(answers[d] == "REFUSED" for d in mutter_x) else "LEAKED", "mutter's Xwayland (-auth): the same connection", ", ".join(f"{d} {answers[d]}" for d in mutter_x) or "no socket")
sway2.terminate(); mutter2.terminate()

# 1d. the clipboard (17.9, round seven R7-1): a sandboxed app runs wl-paste against text a host client
# copied -- sway offers zwlr_data_control to every client and the text comes out; mutter offers no
# such protocol, and the ordinary selection needs keyboard focus the app never has.
for comp, display in (("sway", os.environ["WAYLAND_DISPLAY"]), ("mutter", "wayland-6")):
    if comp == "mutter":
        mutter3 = subprocess.Popen(["mutter", "--headless", "--wayland", "--no-x11", "--virtual-monitor", "1280x800", "--wayland-display", display],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(50):
            if os.path.exists(f"{rt}/{display}"):
                break
            time.sleep(0.2)
    env = {**os.environ, "WAYLAND_DISPLAY": display}
    copier = subprocess.Popen(["wl-copy", "--foreground", "the-users-secret-clipboard"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(0.5)
    lp = install("clip", sb.resolve_template("online-app"), 'timeout 5 wl-paste 2>&1\n')
    r = subprocess.run([lp], env=env, capture_output=True, text=True, timeout=40)
    say("LEAKED" if "the-users-secret-clipboard" in r.stdout else "BLOCKED", f"{comp}: a sandboxed app reads what the user copied (wl-paste)", r.stdout.strip()[:50])
    leaks = sb.compositor_leaks(env)
    say("unread" if leaks is None else ",".join(sorted(leaks)) or "nothing", f"{comp}: what AppKata reads from its globals",
        f"{len(sb.compositor_globals(env) or ())} globals")
    copier.terminate()
    if comp == "mutter":
        mutter3.terminate()

# 2. sound through PipeWire as a sandboxed client, with and without the grant
subprocess.run(["sox", "-n", f"{home}/tone.wav", "synth", "4", "sine", "440"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
for name, template in (("player", "online-app"), ("mute", "offline-editor")):
    gs = sb.resolve_template(template)
    lp = install(name, gs, f'cp {home}/tone.wav "$HOME/tone.wav" 2>/dev/null; exec pw-play "$HOME/tone.wav"\n')
    # the app's private home can't see the host's tone; give it the file by a granted folder instead
    os.makedirs(f"{home}/Music", exist_ok=True)
    subprocess.run(["cp", f"{home}/tone.wav", f"{home}/Music/tone.wav"])
    gs = sb.apply_overrides(gs, {"folders": {"+~/Music": "ro"}})
    lp = install(name, gs, f'exec pw-play "$HOME/Music/tone.wav"\n')
    p = subprocess.Popen([lp], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    time.sleep(1.5)
    streams = subprocess.run(["pactl", "list", "short", "sink-inputs"], capture_output=True, text=True).stdout.strip().splitlines()
    clients = [c for c in json.loads(subprocess.run(["pw-dump"], capture_output=True, text=True).stdout or "[]")
               if c.get("type") == "PipeWire:Interface:Client"
               and (c.get("info", {}).get("props", {}).get("pipewire.access") == "flatpak"
                    or c.get("info", {}).get("props", {}).get("pipewire.sec.flatpak"))]
    props = clients[-1]["info"]["props"] if clients else {}
    out, err = p.communicate(timeout=20)
    if "sound" in gs and gs["sound"]:
        ok = bool(streams) and p.returncode == 0
        say("WORKS" if ok else "FAILS", f"{template}: plays a tone through PipeWire ({len(streams)} stream)",
            f"client access={props.get('pipewire.access')!r} app_id={props.get('pipewire.access.portal.app_id')!r}" if props else (err.strip().splitlines() or [""])[-1])
    else:
        say("BLOCKED" if p.returncode != 0 and not streams else "LEAKED", f"{template}: no sound grant, so no socket to play through",
            (err.strip().splitlines() or [""])[-1][:70])

# 3. recording from the same sockets (17.8: play-only cannot be enforced)
lp = install("rec", sb.apply_overrides(sb.resolve_template("online-app"), {"folders": {"+~/Music": "rw"}}),
             'timeout 2 pw-record "$HOME/Music/rec.wav"; ls -l "$HOME/Music/rec.wav" >&2\n')
r = subprocess.run([lp], capture_output=True, text=True, timeout=30)
size = os.path.getsize(f"{home}/Music/rec.wav") if os.path.exists(f"{home}/Music/rec.wav") else 0
say("LEAKED" if size > 44 else "BLOCKED", "online-app (play only): records from the same sockets", f"{size} bytes recorded")

bad = [f"{k}: wanted {v}, got {VERDICTS.get(k)}" for k, v in EXPECTED.items() if VERDICTS.get(k) != v]
print("EXPECTED:", "ok" if not bad else "FAILED -- " + "; ".join(bad), flush=True)
sys.exit(0 if not bad else 1)
