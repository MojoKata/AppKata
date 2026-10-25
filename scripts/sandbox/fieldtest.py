"""AppKata sandbox field test: the checks of docs/local-proxy-test-plan.md that a real, logged-in
desktop can answer and a container can't, run against what AppKata itself installs.

Run through scripts/sandbox/field-test.sh. It installs a small probe app through AppKata's own
install path (appkata_core.install, a local HTTP server standing in for a forge), lets AppKata write
its launcher for each template the checks need, and runs that launcher -- so every check is a check
of the code a user gets, not of commands written by hand (review 2, D1: the earlier script
reproduced the planning-stage commands, marker on the proxy and all).

Everything happens in a throwaway home: the probe's "secrets", its private home and AppKata's data
live there, and the real home is never written. (The earlier script wrote a canary into the tester's
real ~/.ssh/id_ed25519 and then deleted that file -- the tester's SSH key.) The session itself is
real: the display, the session bus, the portals, the sound server, the GPU.

Output: ./appkata-fieldtest-<host>-<date>/ (report.md, env.txt, logs/, shots/) and a .tar.gz of it.
"""

from __future__ import annotations

import argparse
import http.server
import io
import json
import os
import re
import shlex
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
import threading
import time

REAL = {k: os.environ.get(k, "") for k in ("HOME", "XDG_RUNTIME_DIR", "DISPLAY", "WAYLAND_DISPLAY", "XAUTHORITY",
                                           "DBUS_SESSION_BUS_ADDRESS", "XDG_SESSION_TYPE", "XDG_CURRENT_DESKTOP", "PATH")}
FAKE = tempfile.mkdtemp(prefix="appkata-fieldtest-home-")
# AppKata's paths follow HOME and the XDG variables, so from here on its data, apps and the probe's
# private home are all under the throwaway home
os.environ.update(HOME=FAKE, XDG_DATA_HOME=os.path.join(FAKE, ".local", "share"),
                  XDG_STATE_HOME=os.path.join(FAKE, ".local", "state"), XDG_CONFIG_HOME=os.path.join(FAKE, ".config"))
for v in ("APPKATA_DATA", "APPKATA_APPS"):
    os.environ.pop(v, None)

from appkata_core import install, sandbox as sb          # noqa: E402  (after HOME moved)
from appkata_core.assets import Asset                    # noqa: E402
from appkata_core.db import DB                           # noqa: E402

PROBE = "#!/bin/sh\n# AppKata field-test probe: runs its first argument as a shell snippet, inside the sandbox\neval \"$1\"\n"
STATUS = {"PASS": "pass", "BLOCKED": "pass", "OK": "pass", "FAIL": "fail", "LEAK": "fail"}


class Report:
    def __init__(self, out: str):
        self.out, self.rows, self.counts = out, [], {"pass": 0, "fail": 0, "manual": 0}
        os.makedirs(os.path.join(out, "logs"), exist_ok=True)
        os.makedirs(os.path.join(out, "shots"), exist_ok=True)

    def rec(self, status: str, cid: str, what: str, detail: str = "") -> None:
        self.rows.append((status, cid, what, detail))
        self.counts[STATUS.get(status, "manual")] += 1
        print(f"  {status:<8} {cid:<14} {what}{'  -- ' + detail if detail else ''}")

    def write(self, env: str) -> None:
        with open(os.path.join(self.out, "env.txt"), "w") as f:
            f.write(env)
        with open(os.path.join(self.out, "report.md"), "w") as f:
            f.write(f"# AppKata sandbox field test\n\nRun: {time.strftime('%Y-%m-%d %H:%M')} on `{socket.gethostname()}`\n\n")
            f.write("| Status | ID | Check | Detail |\n|---|---|---|---|\n")
            for r in self.rows:
                f.write("| " + " | ".join(x.replace("|", "\\|").replace("\n", " ") for x in r) + " |\n")
            c = self.counts
            f.write(f"\n## Summary\n\npass/blocked: **{c['pass']}**  fail/leak: **{c['fail']}**  manual/n-a: **{c['manual']}**\n")
            f.write("\n```\n" + env + "```\n")


def have(cmd: str) -> bool:
    return shutil.which(cmd, path=REAL["PATH"]) is not None


class Probe:
    """The probe app, installed through install.install() from a local server, and its launcher."""

    def __init__(self, report: Report):
        self.r = report
        self.www = tempfile.mkdtemp(prefix="appkata-fieldtest-www-")
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tf:
            info = tarfile.TarInfo("probe-1.0/probe")
            info.size, info.mode = len(PROBE), 0o755
            tf.addfile(info, io.BytesIO(PROBE.encode()))
        with open(os.path.join(self.www, "probe-1.0-linux-x86_64.tar.gz"), "wb") as f:
            f.write(buf.getvalue())
        handler = lambda *a, **k: http.server.SimpleHTTPRequestHandler(*a, directory=self.www, **k)   # noqa: E731
        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.httpd.RequestHandlerClass.log_message = lambda *a: None
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        self.db = DB(os.path.join(FAKE, "appkata.db"))
        self.portable = install.Portable(folder=os.path.join(FAKE, "bin", "apps"), app_menu=False, stable_name=True, keep=1)
        self.app = {"url": "https://example.invalid/appkata/fieldtest-probe", "name": "Field Probe", "version": "1.0",
                    "date": "2026-01-01T00:00:00Z", "summary": "", "icon": "", "repo": "appkata/fieldtest-probe", "foreign": ""}
        asset = Asset("probe-1.0-linux-x86_64.tar.gz", f"{self.base}/probe-1.0-linux-x86_64.tar.gz")
        self.rec = install.install(self.db, {**self.app, "sandbox": sb.to_json(sb.resolve_template("strict"))},
                                   asset, "tarball", [asset], portable=self.portable)
        self.current, self.launcher = "strict", self.rec.get("launcher") or ""

    def use(self, template: str) -> str:
        """Let AppKata write the probe's launcher for this template, unless it already has; returns it.
        The probe has one launcher, rewritten per template, so every check names the template it runs
        (review 3, R3-11: checks made with a launcher path ran whatever template was written last)."""
        if self.current != template:
            rec = install.rewrite_launcher(self.db, {**self.app, "sandbox": sb.to_json(sb.resolve_template(template))}, self.portable)
            self.launcher, self.current = rec.get("launcher") or "", template
        return self.launcher

    @staticmethod
    def env() -> dict:
        return {k: v for k, v in REAL.items() if v and k != "HOME"} | {"HOME": FAKE, "LANG": os.environ.get("LANG", "C.UTF-8")}

    def run(self, template: str, snippet: str, *args: str, cwd: str | None = None, timeout: int = 30) -> subprocess.CompletedProcess:
        """Run `snippet` in the probe under `template`'s launcher."""
        return subprocess.run([self.use(template), snippet, *args], cwd=cwd or FAKE, env=self.env(), capture_output=True, text=True, timeout=timeout)

    def close(self) -> None:
        try:
            install.uninstall(self.db, self.app["url"], remove_sandbox=True)
        except Exception as e:                    # noqa: BLE001 -- cleanup must not hide the report
            print(f"  (cleanup: {e})")
        self.httpd.shutdown()
        shutil.rmtree(self.www, ignore_errors=True)


def _setup_questions(r: Report, interactive: bool) -> None:
    """The AppArmor setup's questions, only where AppKata's setup applies: the kernel restricts
    unprivileged user namespaces and the system has no bwrap profile of its own (17.10, 17.10.2;
    review 3, R3-37); N/A elsewhere. A1-prompt asks what the first install showed (review 3, R3-38)."""
    if sb.userns_restricted() and not sb.other_bwrap_profiles():
        ask(r, interactive, "A1-prompt", "Before the setup, did installing a first AppImage ask 'Set up the sandbox?', did Not now install it unsandboxed, and did a second install not ask again?")
        ask(r, interactive, "A1-pkexec", "Did Settings > Sandbox > Set up... show ONE password prompt, then 'Ready'?")
    else:
        for cid, what in (("A1-prompt", "the AppArmor setup's first-install prompt"), ("A1-pkexec", "the AppArmor setup's password prompt")):
            r.rec("N/A", cid, what, "no setup here: the kernel doesn't restrict user namespaces, or the system has a bwrap profile of its own")


def ask(r: Report, interactive: bool, cid: str, question: str) -> None:
    if not interactive or not sys.stdin.isatty():
        r.rec("MANUAL", cid, question, "non-interactive: review by hand")
        return
    a = input(f"\n  >> {cid}\n     {question} [y=pass / n=fail / s=skip]: ").strip().lower()
    r.rec("PASS" if a == "y" else "FAIL" if a == "n" else "MANUAL", cid, question, "tester's answer" if a in ("y", "n") else "skipped")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--app", default="", help="an AppImage to install and start through AppKata's launcher")
    ap.add_argument("--non-interactive", "-y", action="store_true")
    a = ap.parse_args()
    out = os.path.abspath(f"appkata-fieldtest-{socket.gethostname().split('.')[0]}-{time.strftime('%Y%m%d-%H%M%S')}")
    r = Report(out)
    st = sb.support_status()
    warn = sb.session_warning()
    env = (f"distro:   {_os_release()}\nkernel:   {os.uname().release}\n"
           f"session:  {REAL['XDG_SESSION_TYPE'] or '?'} ({REAL['XDG_CURRENT_DESKTOP'] or '?'})  wayland={REAL['WAYLAND_DISPLAY']} x11={REAL['DISPLAY']}\n"
           f"bwrap:    {_out(['bwrap', '--version'])}   xdg-dbus-proxy: {'yes' if have('xdg-dbus-proxy') else 'MISSING'}\n"
           f"support:  {json.dumps(st)}\n"
           f"warning:  {warn.get('text', '(none)')}\n"
           f"gpu:      {' '.join(sorted(os.listdir('/dev/dri'))) if os.path.isdir('/dev/dri') else 'no /dev/dri'}\n")
    print("== environment ==\n" + env + "== checks ==")

    # A. can AppKata sandbox here at all (17.10, 17.10.2)
    status = st.get("status")
    if status == "ok":
        r.rec("PASS", "A-support", "AppKata's sandbox can run here",
              "under the system's own bwrap profile: apps with their own sandbox get --no-sandbox" if st.get("innerSandbox") is False else "")
    elif status == "setup-needed":
        r.rec("FAIL", "A-support", "this system needs AppKata's one-time setup", "Settings > Sandbox > Set up..., then re-run")
    elif status == "conflict":
        r.rec("FAIL", "A-support", "AppKata's AppArmor profile sits beside the system's own", "Settings > Sandbox > Repair..., then re-run")
    else:
        r.rec("FAIL", "A-support", f"sandbox support: {status}", "install bubblewrap and xdg-dbus-proxy")
    if status != "ok":
        r.write(env)
        return _finish(r, out)

    os.makedirs(os.path.join(FAKE, ".ssh"))
    with open(os.path.join(FAKE, ".ssh", "id_ed25519"), "w") as f:
        f.write("FIELDTEST-SECRET\n")
    with open(os.path.join(FAKE, ".bashrc"), "w") as f:
        f.write("# the throwaway home's bashrc\n")
    os.makedirs(os.path.join(FAKE, ".themes", "FieldTest"))
    with open(os.path.join(FAKE, ".themes", "FieldTest", "theme"), "w") as f:
        f.write("THEME-OK\n")
    os.makedirs(os.path.join(FAKE, "Documents"))
    with open(os.path.join(FAKE, "Documents", "note.txt"), "w") as f:
        f.write("HANDED-OVER\n")
    try:
        probe = Probe(r)
    except Exception as e:                        # noqa: BLE001
        r.rec("FAIL", "INSTALL", "AppKata couldn't install the probe app", str(e))
        r.write(env)
        return _finish(r, out)
    try:
        _checks(r, probe, warn, a)
    finally:
        probe.close()
    _setup_questions(r, not a.non_interactive)
    ask(r, not a.non_interactive, "P-dialog", "In a sandboxed app, does its own file dialog show its private home and the folders you gave it -- and nothing else of your home?")
    ask(r, not a.non_interactive, "P-openwith", "Does 'Open with' (or a drop on its menu entry) of a file outside its folders open that file in the sandboxed app?")
    ask(r, not a.non_interactive, "T-tray", "Messenger template: does its tray icon appear and do its notifications arrive?")
    ask(r, not a.non_interactive, "T-mpris", "Media player template: do the keyboard's media keys / the lock screen's controls work?")
    ask(r, not a.non_interactive, "U-selfupd", "An app that updates itself, sandboxed: does AppKata offer its updates, and does the app cope with its own updater failing?")
    ask(r, not a.non_interactive, "U-enable", "Switching an installed app from Off to a sandbox: are you told it starts with fresh settings?")
    ask(r, not a.non_interactive, "E-native", "A password manager's browser integration (native messaging): does it still work?")
    r.write(env)
    return _finish(r, out)


def _checks(r: Report, p: Probe, warn: dict, a) -> None:
    # isolation, from inside the launcher AppKata wrote
    res = p.run("strict", 'cat "$HOME/.ssh/id_ed25519" 2>&1; echo pwned >> "$HOME/.bashrc"; echo done')
    r.rec("BLOCKED" if "FIELDTEST-SECRET" not in res.stdout else "LEAK", "ISO-keys", "a sandboxed app can't read ~/.ssh")
    with open(os.path.join(FAKE, ".bashrc")) as f:
        r.rec("BLOCKED" if "pwned" not in f.read() else "LEAK", "ISO-home", "its writes to ~ land in its private home")
    net = 'python3 -c "import socket; socket.create_connection((\'1.1.1.1\', 443), 4); print(\'NET-OK\')" 2>/dev/null; true'
    r.rec("BLOCKED" if "NET-OK" not in p.run("strict", net).stdout else "LEAK", "ISO-net", "Strict has no network")
    res = p.run("strict", 'cat "$HOME/.themes/FieldTest/theme" 2>&1; echo x > "$HOME/.themes/FieldTest/theme" 2>/dev/null && echo WROTE; true')
    r.rec("PASS" if "THEME-OK" in res.stdout and "WROTE" not in res.stdout else "FAIL", "D-theme", "the desktop's themes are visible and read-only")

    res = p.run("online-app", net)
    r.rec("PASS" if "NET-OK" in res.stdout else "INFO", "ISO-net-on", "Online app reaches the network", "" if "NET-OK" in res.stdout else "no route to 1.1.1.1 here?")
    if have("gdbus") and REAL["DBUS_SESSION_BUS_ADDRESS"]:
        call = 'gdbus call --session --dest {} --object-path {} --method org.freedesktop.DBus.Peer.Ping 2>&1; true'
        res = p.run("online-app", call.format("org.freedesktop.systemd1", "/org/freedesktop/systemd1"))
        r.rec("BLOCKED" if "()" not in res.stdout else "LEAK", "P-filter", "the bus filter refuses systemd1")
        # the filter opens the portal per interface (17.5): Introspect is one it allows, Peer.Ping isn't
        res = p.run("online-app", 'gdbus introspect --session --dest org.freedesktop.portal.Desktop --object-path /org/freedesktop/portal/desktop 2>&1; true')
        ok = "org.freedesktop.portal.OpenURI" in res.stdout
        r.rec("PASS" if ok else "INFO", "P-portal", "the portal answers through the filter", "" if ok else res.stdout.strip()[-120:])
    else:
        r.rec("N/A", "P-filter", "bus filter", "no gdbus or no session bus")
    note = os.path.join(FAKE, "Documents", "note.txt")
    res = p.run("online-app", 'cat "$2" 2>&1; true', note)
    r.rec("PASS" if "HANDED-OVER" in res.stdout else "INFO", "P-handover", "a file given as an argument is handed over (document portal)",
          "" if "HANDED-OVER" in res.stdout else "no document portal or python3-gi?")
    res = p.run("strict", 'unshare --user --map-root-user true 2>/dev/null && echo NESTED-OK; true')
    r.rec("PASS" if ("NESTED-OK" in res.stdout) is sb.nested_userns_works() else "FAIL", "INNER",
          "an app's own sandbox inside AppKata's: " + ("possible" if "NESTED-OK" in res.stdout else "not here (Chromium/Electron get --no-sandbox)"))

    # the display: the session warning says what the sandbox can't hide; check it says so where it leaks
    if REAL["XDG_SESSION_TYPE"] == "wayland" and have("grim"):
        res = p.run("strict", 'grim "$HOME/shot.png" 2>/dev/null && echo SHOT; true')
        leak = "SHOT" in res.stdout
        r.rec("LEAK" if leak and not warn else "PASS", "D-wayland", "screen capture from a sandbox " + ("works" if leak else "is refused"),
              "and the session warning says so" if leak and warn else "" if not leak else "BUT NO WARNING IS SHOWN")
    elif REAL["DISPLAY"] and have("import"):
        res = p.run("strict", 'import -window root "$HOME/shot.png" 2>/dev/null && echo SHOT; true')
        leak = "SHOT" in res.stdout
        r.rec("PASS" if not leak or warn else "LEAK", "D-x11", "X11 screen capture from a sandbox " + ("works" if leak else "is refused"),
              "and the session warning says so" if warn else "")
    else:
        r.rec("N/A", "D-capture", "screen capture check", "needs grim (Wayland) or ImageMagick's import (X11)")
    if have("pactl"):
        r.rec("PASS" if p.run("online-app", "pactl info >/dev/null 2>&1 && echo SND; true").stdout.strip() == "SND" else "INFO",
              "D-sound", "a sound grant reaches the sound server")
        r.rec("BLOCKED" if "SND" not in p.run("strict", "pactl info >/dev/null 2>&1 && echo SND; true").stdout else "LEAK",
              "D-nosound", "no sound server without the grant")
    if have("glxinfo") and os.path.isdir("/dev/dri"):
        res = p.run("strict", "glxinfo 2>/dev/null | sed -n 's/^.*OpenGL renderer string: //p' | head -1")
        r.rec("PASS" if res.stdout.strip() else "INFO", "D-gpu", "OpenGL renderer inside: " + (res.stdout.strip() or "?"))

    _exposure(r, p, ("strict", "online-app"))

    work = os.path.join(FAKE, "Projects", "demo")
    os.makedirs(work)
    with open(os.path.join(work, "in.txt"), "w") as f:
        f.write("hi\n")
    res = p.run("cli-tool", 'cat in.txt >/dev/null && echo w > out.txt && echo OK', cwd=work)
    r.rec("PASS" if "OK" in res.stdout and os.path.exists(os.path.join(work, "out.txt")) else "FAIL", "T-cli", "a command-line tool works in the folder it's run in")
    res = p.run("cli-tool", 'cat "$HOME/.ssh/id_ed25519" 2>&1; true', cwd=FAKE)
    r.rec("BLOCKED" if "FIELDTEST-SECRET" not in res.stdout and "runs sandboxed and can't see" in res.stderr else "LEAK",
          "T-cli-home", "run from the home folder, it gets its private home and says why")

    if a.app:
        _gui(r, p, a)


def _exposure(r: Report, p: Probe, templates: tuple) -> None:
    """Review 3's harness 3 on a real desktop: everything the probe can see from inside AppKata's
    launcher -- mounts, variables, devices, sockets, identifiers, network reach -- against
    docs/sandbox-exposure.md. A container can't show a real session's sockets, GPU or resolver."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import exposure as ex
    try:
        rows = ex.load()
    except OSError:
        r.rec("N/A", "EXP", "the exposure inventory", "docs/sandbox-exposure.md isn't beside this checkout")
        return
    host = ex.parse(subprocess.run([sys.executable, "-c", ex.PROBE], capture_output=True, text=True, timeout=120).stdout)
    session = "wayland" if REAL["WAYLAND_DISPLAY"] else "x11"
    for name in templates:
        lp = p.use(name)
        res = p.run(name, "python3 -c " + shlex.quote(ex.PROBE), timeout=120)
        try:
            inside = ex.parse(res.stdout)
        except ValueError:
            r.rec("FAIL", f"EXP-{name}", f"{name}: the exposure probe didn't run", res.stderr.strip()[-160:])
            continue
        with open(lp) as f:
            words = dict(shlex.split(line)[0].split("=", 1) for line in f if re.match(r"^(id|appdir)=", line))
        ctx = {"home": FAKE, "rt": REAL["XDG_RUNTIME_DIR"], "appdir": words.get("appdir", ""), "img": None, "cwd": None,
               "folders": [], "xauthority": REAL["XAUTHORITY"] or os.path.join(FAKE, ".Xauthority"),
               "wayland": REAL["WAYLAND_DISPLAY"] or None, "launch_env": ex.shell_view(p.env()), "id": words.get("id", ""),
               "marker": None, "abstract_bus": REAL["DBUS_SESSION_BUS_ADDRESS"].startswith("unix:abstract=")}
        seen = ex.items(inside, host, ctx)
        extra = sorted(seen - ex.expected(rows, ex.facts_for(sb.resolve_template(name), session, False, False), ctx, host))
        r.rec("FAIL" if extra else "PASS", f"EXP-{name}", f"{name}: everything it sees is listed in docs/sandbox-exposure.md",
              ("not listed: " + "; ".join(extra)) if extra else "")
        opened = sorted({row["stated"][6:] for row in rows for i in seen if i in row["items"] and row["stated"].startswith("open: ")})
        if opened:
            r.rec("INFO", f"EXP-{name}-open", f"{name}: sees what no requirement states yet", ", ".join(opened))


def _gui(r: Report, p: Probe, a) -> None:
    """Install the tester's AppImage through AppKata (Online app template) and start its launcher."""
    name = os.path.basename(a.app)
    shutil.copy(a.app, os.path.join(p.www, name))
    asset = Asset(name, f"{p.base}/{name}")
    app = {**p.app, "url": "https://example.invalid/appkata/fieldtest-gui", "name": "Field GUI", "repo": "appkata/fieldtest-gui"}
    try:
        rec = install.install(p.db, {**app, "sandbox": sb.to_json(sb.resolve_template("online-app"))}, asset, "appimage", [asset], portable=p.portable)
    except Exception as e:                        # noqa: BLE001
        r.rec("FAIL", "GUI-install", "AppKata couldn't install the app", str(e))
        return
    env = {k: v for k, v in REAL.items() if v and k != "HOME"} | {"HOME": FAKE, "LANG": os.environ.get("LANG", "C.UTF-8")}
    with open(os.path.join(r.out, "logs", "gui.log"), "w") as log:
        proc = subprocess.Popen([rec["launcher"]], env=env, stdout=log, stderr=subprocess.STDOUT)
        time.sleep(15)
        running = proc.poll() is None
        r.rec("PASS" if running else "FAIL", "GUI-run", "the app runs from AppKata's launcher", "" if running else "see logs/gui.log")
        for cmd in (["grim"], ["import", "-window", "root"]):
            if have(cmd[0]):
                subprocess.run([*cmd, os.path.join(r.out, "shots", "gui.png")], capture_output=True)
                break
        proc.terminate()
    try:
        install.uninstall(p.db, app["url"], remove_sandbox=True)
    except Exception:                             # noqa: BLE001
        pass


def _os_release() -> str:
    try:
        with open("/etc/os-release") as f:
            return next((l.split("=", 1)[1].strip().strip('"') for l in f if l.startswith("PRETTY_NAME=")), "?")
    except OSError:
        return "?"


def _out(cmd: list[str]) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=10).stdout.strip() or "?"
    except (OSError, subprocess.SubprocessError):
        return "MISSING"


def _finish(r: Report, out: str) -> int:
    shutil.rmtree(FAKE, ignore_errors=True)
    with tarfile.open(out + ".tar.gz", "w:gz") as tf:
        tf.add(out, arcname=os.path.basename(out))
    c = r.counts
    print(f"\n== done ==\npass/blocked: {c['pass']}   fail/leak: {c['fail']}   manual/n-a: {c['manual']}")
    print(f"Report:  {out}/report.md\nBundle:  {out}.tar.gz  (bring this back for review)")
    return 1 if c["fail"] else 0


if __name__ == "__main__":
    sys.exit(main())
