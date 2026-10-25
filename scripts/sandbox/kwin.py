"""What KDE's kwin gives a sandboxed app (round seven, R7-1; requirement 17.9).

Run by `scripts/test-sandbox.sh kwin` as the test user in a Mint 22.1 container with kwin-wayland
(5.27), after a session bus and `kwin_wayland --virtual` are up. A generated `online-app` launcher
runs: a registry listing (which of the capture, clipboard and injection protocols kwin offers an
ordinary client), `wl-paste` against text a host client copied, and -- where kwin's Xwayland
starts -- an unauthenticated X11 connection over the abstract socket. Exits 1 when a verdict is
not the expected one; LEAKED for the clipboard is what 17.9 now states.
"""
import os
import subprocess
import sys
import time

sys.path.insert(0, "/src/src")
home = os.environ["HOME"]; rt = os.environ["XDG_RUNTIME_DIR"]
from appkata_core import sandbox as sb   # noqa: E402

EXPECTED = {"kwin offers the clipboard-manager protocol to a sandboxed app": "LEAKED",
            "kwin hides screencast, fake input and virtual keyboard from it": "BLOCKED",
            "a sandboxed app reads what the user copied (wl-paste)": "LEAKED",
            "what AppKata reads from kwin's globals for the warning (17.9, F7)": "clipboard"}
VERDICTS = {}
WATCH = ("data_control", "screencopy", "screencast", "virtual_keyboard", "virtual_pointer", "fake_input", "security_context", "image_copy")


def say(verdict, what, detail=""):
    VERDICTS[what] = verdict
    print(f"  {verdict:8} {what:62} {detail}", flush=True)


def install(name, program, gs=None):
    d = f"{home}/apps/{name}/1.0/bin"
    os.makedirs(d, exist_ok=True)
    with open(f"{d}/app", "w") as f:
        f.write("#!/bin/sh\n" + program)
    os.chmod(f"{d}/app", 0o755)
    return sb.write_launcher(name, name, f"{home}/apps", f"{home}/apps/{name}/1.0", "bin/app", gs or sb.resolve_template("online-app"))


print("kwin:", subprocess.run(["kwin_wayland", "--version"], capture_output=True, text=True).stdout.strip() or "?", "display", os.environ.get("WAYLAND_DISPLAY"), flush=True)
r = subprocess.run([install("globals", "exec wayland-info\n")], capture_output=True, text=True, timeout=30)
names = sorted({l.split("'")[1] for l in r.stdout.splitlines() if "interface: '" in l})
seen = [n for n in names if any(k in n for k in WATCH)]
say("LEAKED" if any("data_control" in n for n in seen) else "BLOCKED", "kwin offers the clipboard-manager protocol to a sandboxed app", ", ".join(seen) or "none of the watched protocols")
say("BLOCKED" if not any(k in n for n in seen for k in ("screencast", "screencopy", "fake_input", "virtual_keyboard", "virtual_pointer")) else "LEAKED",
    "kwin hides screencast, fake input and virtual keyboard from it", f"{len(names)} globals in all")
copier = subprocess.Popen(["wl-copy", "--foreground", "the-users-secret-clipboard"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(0.5)
r = subprocess.run([install("clip", 'timeout 5 wl-paste 2>&1\n')], capture_output=True, text=True, timeout=40)
say("LEAKED" if "the-users-secret-clipboard" in r.stdout else "BLOCKED", "a sandboxed app reads what the user copied (wl-paste)", r.stdout.strip()[:60])
copier.terminate()
leaks = sb.compositor_leaks()
say("unread" if leaks is None else ",".join(sorted(leaks)) or "nothing", "what AppKata reads from kwin's globals for the warning (17.9, F7)",
    f"{len(sb.compositor_globals() or ())} globals")
bad = [f"{k}: wanted {v}, got {VERDICTS.get(k)}" for k, v in EXPECTED.items() if VERDICTS.get(k) != v]
print("EXPECTED:", "ok" if not bad else "FAILED -- " + "; ".join(bad), flush=True)
sys.exit(0 if not bad else 1)
