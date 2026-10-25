"""The sandbox's lifecycle as a state machine: invariants after every step of random walks
(review 3, harness 2).

How review 2's F12, F13 and F16 slipped past: every test drove one transition at a time --
install options on an installed app (R4-3), a re-save (round two's R1), the heal pass, a broken host
at launch -- and asserted that transition's result. Nothing held the rules that must survive *any*
order of them: an app is never unsandboxed without the user choosing Off; what the UI shows is what
runs; the user is told when a sandbox starts; every grant change is audited with what changed; a
review never changes a pinned set. So a broken host *during an update*, or the heal after a setup,
broke a rule nobody had written down as one.

This harness writes them down. Seeded random sequences of operations run against the real Backend,
on a fake host whose sandbox support changes between steps, with AppKata's own install present as
it is when run from an AppImage; after every step each invariant is checked. The invariants still broken are listed with the finding that keeps them so; the test fails
if another breaks, or a listed one starts to hold (drop it then). Two of the harness's own
originating bugs are re-introduced to show it catches them.
"""

import json
import os
import random
import shutil
import threading

import pytest

from appkata_core import APPKATA_REPO, install, sandbox as sb, trustfile
from appkata_core.db import now
from test_sandbox_backend import URL, _tarball_install, be   # noqa: F401

SEEDS, STEPS = 120, 10

# invariant -> the finding that keeps it broken today (review 2 / review 3)
STILL_BROKEN = {
}
ALL_INVARIANTS = ("never-unsandboxed-unasked", "shown-is-what-runs", "bwrap-alone-sandboxes",
                  "told-when-a-sandbox-starts", "audited-with-what-changed", "reviews-never-change-what-runs",
                  "a-resave-changes-nothing", "appkata-itself-never-sandboxed")

HOSTS = ("ok", "setup-needed", "conflict", "no-tools", "bwrap-only")


class HostShutil:
    """shutil as the fake host has it: `which` finds bwrap and xdg-dbus-proxy only where the host has
    them, so what the code itself makes of a missing tool is what the walk sees. (Faking have_tools()
    instead hid R2-F12: the harness then said what AppKata needs, not the code.)"""

    def __init__(self, world):
        self.world = world

    def which(self, name, *a, **kw):
        if name in ("bwrap", "xdg-dbus-proxy"):
            has = {"no-tools": (), "bwrap-only": ("bwrap",)}.get(self.world.host, ("bwrap", "xdg-dbus-proxy"))
            return f"/usr/bin/{name}" if name in has else None
        return shutil.which(name, *a, **kw)

    def __getattr__(self, name):
        return getattr(shutil, name)


class World:
    """The Backend with one installed tarball app, a review, and a host whose support can change."""

    def __init__(self, be, tmp_path, monkeypatch):
        self.be, self.host, self.toasts = be, "ok", []
        _tarball_install(be, tmp_path)
        # AppKata's own AppImage, adopted as installed the way _ensure_self records it (2.11)
        image = tmp_path / "Downloads" / "AppKata-x86_64.AppImage"
        image.parent.mkdir(parents=True, exist_ok=True)
        image.write_text("#!/bin/sh\n")
        self_rec = {"files": [], "links": [], "root": str(tmp_path / "bin" / "apps"), "target": str(tmp_path / "bin" / "apps" / "appkata"),
                    "kept": [], "exec": str(image), "current": {"version": "9.9", "path": str(image), "exec": str(image), "external": True}}
        be.db.x("INSERT OR REPLACE INTO installs(url, name, version, kind, record, installed_at) VALUES(?,?,?,?,?,?)",
                (APPKATA_REPO, "AppKata", "9.9", "appimage", json.dumps(self_rec), now()))
        apps = {URL: {"url": URL, "name": "Demo", "installed": "1.0"},
                APPKATA_REPO: {"url": APPKATA_REPO, "name": "AppKata", "installed": "9.9", "self": True, "installKind": "appimage"}}
        be._app = lambda url: apps.get(url)
        be._sandbox_kind = lambda url: "appimage" if url == APPKATA_REPO else "tarball"
        self.review("online-app")
        monkeypatch.setattr(sb, "shutil", HostShutil(self))
        monkeypatch.setattr(sb, "userns_works", lambda refresh=False: self.host in ("ok", "bwrap-only"))
        monkeypatch.setattr(sb, "nested_userns_works", lambda refresh=False: True)
        # the status as support_status() derives it: "unsupported" where the code's own tools check fails
        monkeypatch.setattr(sb, "support_status", lambda: {
            "status": "unsupported" if not sb.have_tools() else
                      {"ok": "ok", "setup-needed": "setup-needed", "conflict": "conflict", "bwrap-only": "ok"}[self.host],
            "innerSandbox": True, "busFilter": self.host in ("ok", "setup-needed", "conflict")})
        monkeypatch.setattr(sb, "install_profile", self._setup)
        monkeypatch.setattr(sb, "remove_profile", self._repair)
        monkeypatch.setattr(threading.Thread, "start", lambda t: t.run())
        be._toast.connect(lambda kind, msg: self.toasts.append(msg))
        be.toast.connect(lambda kind, msg: self.toasts.append(msg))

    def _setup(self):
        if self.host != "setup-needed":
            raise sb.SandboxError("not needed here")
        self.host = "ok"
        return True

    def _repair(self):
        if self.host == "conflict":
            self.host = "ok"
        return True

    def review(self, template):
        parsed, _ = trustfile.parse_section("Demo", f"## Demo::Settings\n\n- Trust: 4\n- Sandbox (linux): {template}\n")
        tid = self.be.db.one("SELECT id FROM trusts")["id"]
        self.be.db.x("INSERT OR REPLACE INTO reviews(trust_id, url, app, settings) VALUES(?,?,?,?)",
                     (tid, URL, "Demo", json.dumps(parsed["opts"])))

    def rec(self):
        return json.loads(self.be.db.one("SELECT record FROM installs WHERE url=?", (URL,))["record"])

    def state(self):
        rec = self.rec()
        lp = rec.get("launcher")
        own = json.loads(self.be.db.one("SELECT record FROM installs WHERE url=?", (APPKATA_REPO,))["record"])
        return {"launcher": bool(lp and os.path.exists(lp)), "baked": rec.get("sandbox"),
                "runs": (self.be._resolved_sandbox(URL) or {}).get("grants"),
                "choice": self.be._install_settings(URL).get("sandbox"),
                "self-launcher": bool(own.get("launcher")),
                # an app that runs unsandboxed with no private home yet, and what the dialogs say before Save
                "fresh": self.be._sandbox_state(URL) == (False, True),
                "warning": self.be._fresh_warning(URL),
                "audit": self.be.db.one("SELECT COUNT(*) n FROM audit")["n"]}

    def update(self):
        """What an update does to the sandbox (backend._install): the launcher rewritten with the
        grant set to bake in, then the pin recorded."""
        be = self.be
        had = be._sandbox_state(URL)
        install.rewrite_launcher(be.db, {**be._app(URL), "sandbox": be._sandbox_for_install(URL, kind="tarball")}, be._app_options(URL))
        be._settle_sandbox(URL, "tarball", had)


def operations(w: World):
    folder = sb.to_json(sb.apply_overrides(sb.resolve_template("standard"), {"folders": {"+~/Documents": "rw"}}))
    return {
        "host": lambda r: setattr(w, "host", r.choice(HOSTS)),
        "choose": lambda r: w.be.setSandbox(URL, {"template": r.choice(["strict", "online-app", "messenger"]), "overrides": {}}),
        "choose-off": lambda r: w.be.setSandbox(URL, {"template": "off"}),
        "custom-folder": lambda r: w.be.setSandbox(URL, {"custom": folder}),
        "use-theirs": lambda r: w.be.useSuggestion(URL),
        "install-options-resave": lambda r: w.be.installWith(URL, {"kind": "tarball", "install": False, "appMenu": True}),
        "install-options-sandbox": lambda r: w.be.installWith(URL, {"kind": "tarball", "install": False, "appMenu": True,
                                                                     "sandbox": {"template": r.choice(["strict", "online-app"]), "overrides": {}}}),
        "update": lambda r: w.update(),
        "heal": lambda r: w.be._heal_launchers(),
        "setup": lambda r: w.be.setupSandboxSupport(),
        "repair": lambda r: w.be.repairSandboxSupport(),
        "review-changes": lambda r: w.review(r.choice(["strict", "online-app", "messenger", "offline-editor"])),
    }


USER_OFF = {"choose-off"}
USER_DIALOG = {"choose", "custom-folder", "use-theirs", "install-options-sandbox"}     # the dialogs that warn before Save
NOT_USER = {"host", "update", "heal", "review-changes", "setup", "repair"}


def check(w: World, op: str, before: dict, after: dict, toasts: list) -> set[str]:
    broken = set()
    if before["launcher"] and not after["launcher"] and op not in USER_OFF:
        broken.add("never-unsandboxed-unasked")
    info = w.be.sandboxInfo(URL)
    if bool(info["active"]) != after["launcher"] or (after["launcher"] and sb.level_of(after["baked"]) != info["level"]):
        broken.add("shown-is-what-runs")
    # bwrap is all a sandbox needs: Strict uses no bus, and Standard runs with none (R2-F12)
    if w.host == "bwrap-only" and op in ("heal", "update", "choose") and info["level"] != "off" and not after["launcher"]:
        broken.add("bwrap-alone-sandboxes")
    # a sandbox that starts with an empty home is said: before Save in the dialog the user chose it in,
    # or in a notice when AppKata does it (17.13, R2-F13)
    if not before["launcher"] and after["launcher"] and before["fresh"] and \
            not (op in USER_DIALOG and before["warning"]) and not any("fresh settings" in t for t in toasts):
        broken.add("told-when-a-sandbox-starts")
    if before["baked"] != after["baked"] and after["baked"] and before["baked"]:
        rows = w.be.db.all("SELECT detail FROM audit ORDER BY id DESC LIMIT ?", (after["audit"] - before["audit"],)) \
            if after["audit"] > before["audit"] else []
        b, a = sb.normalize(before["baked"]), sb.normalize(after["baked"])
        said = " ".join(r["detail"] or "" for r in rows)
        # each grant that changed must be named in words a person reads (17.16, R2-F11: the entry said
        # only the template and level); the harness's own words, not the product's describer
        words = {"network": ["network"], "write_app": ["own files"],
                 "folders": sorted(set(a["folders"]) ^ set(b["folders"]) | {p for p in a["folders"] if b["folders"].get(p) not in (None, a["folders"][p])}),
                 "sound": [{"play": "sound", "record": "recording"}[x] for x in a["sound"] ^ b["sound"]],
                 "devices": [{"camera": "camera", "x11": "X11"}[x] for x in a["devices"] ^ b["devices"]],
                 "caps": [{"notifications": "notifications", "inhibit": "screen awake", "tray": "tray", "mpris": "media keys",
                           "secrets": "passwords", "secrets-provide": "password service"}[x] for x in a["caps"] ^ b["caps"]]}
        if any(a[k] != b[k] and not all(w in said for w in words[k]) for k in words):
            broken.add("audited-with-what-changed")
    if op in NOT_USER and before["runs"] != after["runs"]:
        broken.add("reviews-never-change-what-runs")         # decision 5: nothing but the user changes what runs
    if op == "install-options-resave" and (before["runs"] != after["runs"] or before["choice"] != after["choice"]):
        broken.add("a-resave-changes-nothing")
    if after["self-launcher"]:
        broken.add("appkata-itself-never-sandboxed")
    return broken


def walk(be, tmp_path, monkeypatch, seeds=SEEDS, inject=None):
    """{invariant: the shortest failing sequence} over `seeds` random walks."""
    found: dict[str, list[str]] = {}
    for seed in range(seeds):
        root = tmp_path / f"w{seed}"
        root.mkdir()
        monkeypatch.setenv("HOME", str(root))
        be.db.x("DELETE FROM installs")
        be.db.x("DELETE FROM app_settings")
        w = World(be, root, monkeypatch)
        if inject:
            inject(w, monkeypatch)
        w.update()                                  # start where an install leaves an app: sandboxed and pinned
        w.toasts.clear()
        ops = operations(w)
        r = random.Random(seed)
        seq = []
        for _ in range(STEPS):
            op = r.choice(sorted(ops))
            seq.append(op if op != "host" else f"host->{r.choice(HOSTS)}")
            if seq[-1].startswith("host->"):
                w.host = seq[-1][6:]
                op = "host"
            before, mark = w.state(), len(w.toasts)
            if op != "host":
                ops[op](r)
            after = w.state()
            for inv in check(w, op, before, after, w.toasts[mark:]):
                if inv not in found or len(seq) < len(found[inv]):
                    found[inv] = list(seq)
    return found


def test_the_lifecycle_invariants_hold_over_random_walks_but_the_listed(be, tmp_path, monkeypatch):
    found = walk(be, tmp_path, monkeypatch)
    unexpected = {k: v for k, v in found.items() if k not in STILL_BROKEN}
    assert not unexpected, "invariants broken (shortest sequence each):\n" + \
        "\n".join(f"  {k}: {' > '.join(v)}" for k, v in unexpected.items())
    healed = sorted(set(STILL_BROKEN) - set(found))
    assert not healed, f"listed as broken but held over {SEEDS} walks (drop them): {healed}"


def test_the_harness_catches_round_fours_install_options_applied_too_late(be, tmp_path, monkeypatch):
    # R4-3: a sandbox chosen in Install options for an installed app was saved and shown as in force
    # while the launcher kept the old grants. Re-introduced: the regeneration does nothing.
    def r4_3(w, mp):
        mp.setattr(w.be, "_regenerate_launcher", lambda url: None)
    found = walk(be, tmp_path, monkeypatch, seeds=30, inject=r4_3)
    assert "shown-is-what-runs" in found, found


def test_the_harness_catches_round_twos_resave_dropping_the_pin(be, tmp_path, monkeypatch):
    # Round two's R1: re-saving Install options rewrote the settings row from the dialog's keys alone,
    # dropping the pin, so the next update re-pinned from the current reviews -- a silent widening.
    def r1(w, mp):
        mp.setattr(w.be, "_answer_install_dialog", lambda url, answer: w.be._set_install_settings(url, dict(answer)))
    found = walk(be, tmp_path, monkeypatch, seeds=60, inject=r1)
    assert "a-resave-changes-nothing" in found, found          # the pin dropped: what runs follows the reviews
