"""What an input method gives a sandboxed app (review 2, F15; review 3, R3-18; requirement 17.5).

Run by `scripts/test-sandbox.sh inputmethod` as the test user in a Mint 22.1 container with IBus
and Fcitx 5, after a session bus, `ibus-daemon` and `fcitx5` are up (headless: their D-Bus front
ends need no display). Generated launchers call the portals IBus and Fcitx provide for sandboxed
apps, through AppKata's filter: the app creates an input context and drives it. Without the portal
rules (how the filter was before the owner's decision) the same call is refused, and a Strict app
has no bus at all. Exits 1 when a verdict is not the expected one.
"""
import os
import subprocess
import sys

sys.path.insert(0, "/src/src")
home = os.environ["HOME"]
from appkata_core import sandbox as sb   # noqa: E402

EXPECTED = {"IBus: a sandboxed app creates an input context through the filter": "WORKS",
            "IBus: and drives it (SetCapabilities)": "WORKS",
            "Fcitx: a sandboxed app creates an input context through the filter": "WORKS",
            "IBus: without the portal rules, the call is refused": "BLOCKED",
            "IBus: a Strict app has no bus, so no input method": "BLOCKED",
            "the input-method variables reach the app": "WORKS"}
VERDICTS = {}
IBUS = "gdbus call --session --dest org.freedesktop.portal.IBus --object-path /org/freedesktop/IBus --method org.freedesktop.IBus.Portal.CreateInputContext probe 2>&1"
FCITX = ("gdbus call --session --dest org.freedesktop.portal.Fcitx --object-path /org/freedesktop/portal/inputmethod "
         "--method org.fcitx.Fcitx.InputMethod1.CreateInputContext \"[('program','probe')]\" 2>&1")


def say(verdict, what, detail=""):
    VERDICTS[what] = verdict
    print(f"  {verdict:8} {what:70} {detail}", flush=True)


def install(name, program, template="online-app"):
    d = f"{home}/apps/{name}/1.0/bin"
    os.makedirs(d, exist_ok=True)
    with open(f"{d}/app", "w") as f:
        f.write("#!/bin/sh\n" + program)
    os.chmod(f"{d}/app", 0o755)
    return sb.write_launcher(name, name, f"{home}/apps", f"{home}/apps/{name}/1.0", "bin/app", sb.resolve_template(template))


def run(lp, env=None):
    return subprocess.run([lp], capture_output=True, text=True, timeout=40, env={**os.environ, **(env or {})}).stdout.strip()


print("ibus", subprocess.run(["ibus", "version"], capture_output=True, text=True).stdout.strip(), "/ fcitx5",
      subprocess.run(["fcitx5", "--version"], capture_output=True, text=True).stdout.strip(), flush=True)
# one connection for both calls, as an app has: IBus ties a context to the connection that made it
DRIVE = """python3 - <<'EOF' 2>&1
from gi.repository import Gio, GLib
bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
ctx = bus.call_sync("org.freedesktop.portal.IBus", "/org/freedesktop/IBus", "org.freedesktop.IBus.Portal", "CreateInputContext",
                    GLib.Variant("(s)", ("probe",)), None, 0, 5000, None).unpack()[0]
print("CONTEXT", ctx)
bus.call_sync("org.freedesktop.portal.IBus", ctx, "org.freedesktop.IBus.InputContext", "SetCapabilities",
              GLib.Variant("(u)", (8,)), None, 0, 5000, None)
print("DRIVEN")
EOF
"""
out = run(install("ibus", DRIVE))
say("WORKS" if "CONTEXT /org/freedesktop/IBus/InputContext_" in out else "BLOCKED", "IBus: a sandboxed app creates an input context through the filter", out.splitlines()[0][:60] if out else "")
say("WORKS" if "DRIVEN" in out else "BLOCKED", "IBus: and drives it (SetCapabilities)", out.splitlines()[-1][:60] if out else "")
out = run(install("fcitx", FCITX + "\n"))
say("WORKS" if "objectpath '/org/freedesktop/portal/inputcontext/" in out else "BLOCKED", "Fcitx: a sandboxed app creates an input context through the filter", out[:60])
portals = sb.INPUT_METHOD_PORTALS
sb.INPUT_METHOD_PORTALS = ()
out = run(install("before", IBUS + "\n"))
sb.INPUT_METHOD_PORTALS = portals
say("BLOCKED" if "objectpath" not in out else "WORKS", "IBus: without the portal rules, the call is refused", out[:60])
out = run(install("strict", IBUS + "\n", "strict"))
say("BLOCKED" if "objectpath" not in out else "WORKS", "IBus: a Strict app has no bus, so no input method", out[:60])
out = run(install("vars", 'echo "$GTK_IM_MODULE $QT_IM_MODULE $XMODIFIERS"\n'),
          {"GTK_IM_MODULE": "ibus", "QT_IM_MODULE": "ibus", "XMODIFIERS": "@im=ibus"})
say("WORKS" if out == "ibus ibus @im=ibus" else "BLOCKED", "the input-method variables reach the app", out)
bad = [f"{k}: wanted {v}, got {VERDICTS.get(k)}" for k, v in EXPECTED.items() if VERDICTS.get(k) != v]
print("EXPECTED:", "ok" if not bad else "FAILED -- " + "; ".join(bad), flush=True)
sys.exit(0 if not bad else 1)
