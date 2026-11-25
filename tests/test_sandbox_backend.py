"""App sandboxing (R17): the backend glue — which grant set applies to an app, and when."""

import json
import os
import threading

import pytest

from appkata_core import sandbox as sb
from appkata_core import trustfile
from appkata_core.db import now

pytest.importorskip("PySide6")

URL = "https://github.com/example/demo"


@pytest.fixture
def be(tmp_path, monkeypatch):
    """A Backend whose home is the test's folder. It runs no start-up pass (a test that wants one
    calls it), and every thread the test started has ended before monkeypatch gives HOME back, so
    nothing it does reaches the real home (#689's review, P6-C1)."""
    monkeypatch.setenv("HOME", str(tmp_path))
    for v in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME"):
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from appkata.backend import Backend
    before = set(threading.enumerate())
    b = Backend(db_path=str(tmp_path / "appkata.db"), heal=False)
    b.db.x("INSERT INTO trusts(url, name, enabled, score) VALUES(?,?,1,3)", ("https://example.org/trust", "Alice"))
    b._is_cli = lambda url, eff=None: False
    b._sandbox_kind = lambda url: "appimage"
    yield b
    b._timer.stop()
    late = [t for t in set(threading.enumerate()) - before if not isinstance(t, threading._DummyThread)]
    for t in late:
        t.join(timeout=30)
    assert [t.name for t in late if t.is_alive()] == [], "a thread the test started outlives it, and would run with the real HOME"


def test_the_fixtures_backend_starts_no_thread_that_could_outlive_the_test(request, monkeypatch):
    # #689's review, P6-C1: the fixture's Backend started AppKata's start-up pass on a thread of its
    # own. Run late (a loaded machine), it read the test's database after the test had given HOME
    # back, and wrote the test's Demo into the real ~/bin: ~/bin/apps/demo/run and ~/bin/demo.
    # A test that wants the pass calls it, on its own thread or not, and waits for it.
    started = []
    real = threading.Thread.start
    monkeypatch.setattr(threading.Thread, "start", lambda self: started.append(self.name) or real(self))
    request.getfixturevalue("be")
    assert started == []


def test_no_backend_a_test_builds_runs_appkatas_start_up_pass_on_its_own(tmp_path):
    # P6-C1's class: a Backend built with the default (heal=True) starts that pass on a thread the
    # test doesn't wait for; four of them did, in three files. Each passes heal=False now.
    import ast
    folder = os.path.dirname(os.path.abspath(__file__))
    healing = []
    for name in sorted(os.listdir(folder)):
        if name.endswith(".py"):
            with open(os.path.join(folder, name), encoding="utf-8") as f:
                tree = ast.parse(f.read())
            for call in ast.walk(tree):
                if (isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == "Backend"
                        and not any(k.arg == "heal" and isinstance(k.value, ast.Constant) and k.value.value is False
                                    for k in call.keywords)):
                    healing.append(f"{name}:{call.lineno}")
    assert healing == []


def _review(be, template: str) -> None:
    section = f"## Demo::Settings\n\n- Trust: 4\n- Sandbox (linux): {template}\n"
    parsed, _ = trustfile.parse_section("Demo", section)
    tid = be.db.one("SELECT id FROM trusts")["id"]
    be.db.x("INSERT OR REPLACE INTO reviews(trust_id, url, app, settings) VALUES(?,?,?,?)",
            (tid, URL, "Demo", json.dumps(parsed["opts"])))


def _review_lines(be, lines: str) -> None:
    section = f"## Demo::Settings\n\n- Trust: 4\n{lines}"
    parsed, _ = trustfile.parse_section("Demo", section)
    tid = be.db.one("SELECT id FROM trusts")["id"]
    be.db.x("INSERT OR REPLACE INTO reviews(trust_id, url, app, settings) VALUES(?,?,?,?)",
            (tid, URL, "Demo", json.dumps(parsed["opts"])))


def _installed(be) -> None:
    be.db.x("INSERT OR REPLACE INTO installs(url, name, version, kind, record, installed_at) VALUES(?,?,?,?,?,?)",
            (URL, "Demo", "1.0", "appimage", "{}", now()))


def test_a_changed_review_never_changes_an_installed_apps_grants(be):
    # Regression (A1.12.5, R17.11): with no choice saved by the user, every update re-resolved the
    # grants from the current reviews, so a new review asking for network widened access silently.
    _review(be, "offline-editor")
    r = be._resolved_sandbox(URL, kind="appimage")
    assert r["source"] == "reviews" and r["grants"]["network"] is False
    _installed(be)
    be._pin_sandbox(URL, r)                       # what a successful install records

    _review(be, "online-app")                     # the reviewer now suggests network
    r = be._resolved_sandbox(URL, kind="appimage")
    assert r["source"] == "pinned" and r["grants"]["network"] is False      # unchanged on update
    be._app = lambda url: {"url": URL, "name": "Demo", "installed": "1.0"}
    info = be.sandboxInfo(URL)
    assert info["reviewBadge"] is True            # ... and the change is flagged for review instead
    assert "Network" in [c[0] for c in info["reviewSuggests"]]


def test_resetting_to_the_reviewers_suggestion_adopts_it(be):
    _review(be, "offline-editor")
    _installed(be)
    be._pin_sandbox(URL, be._resolved_sandbox(URL, kind="appimage"))
    _review(be, "online-app")
    be._app = lambda url: {"url": URL, "name": "Demo", "installed": "1.0"}
    be.setSandbox(URL, None)                      # "use the reviewers' suggestion"
    r = be._resolved_sandbox(URL, kind="appimage")
    assert r["grants"]["network"] is True
    assert be.sandboxInfo(URL)["reviewBadge"] is False


def test_uninstall_clears_the_pin_so_a_reinstall_resolves_afresh(be):
    _review(be, "offline-editor")
    _installed(be)
    be._pin_sandbox(URL, be._resolved_sandbox(URL, kind="appimage"))
    be._pin_sandbox(URL, None)                    # what uninstall does
    be.db.x("DELETE FROM installs WHERE url=?", (URL,))
    _review(be, "online-app")
    r = be._resolved_sandbox(URL, kind="appimage")
    assert r["source"] == "reviews" and r["grants"]["network"] is True


def test_choose_precedence():
    user = {"template": "strict", "overrides": {}}
    pinned = {"grants": sb.to_json(sb.resolve_template("offline-editor")), "template": "offline-editor"}
    reviews = [{"template": "online-app", "overrides": {}}]
    default = {"template": "strict", "overrides": {}}
    assert sb.choose(user, pinned, reviews, default)[0] == "user"
    assert sb.choose(None, pinned, reviews, default)[0:3:2] == ("pinned", "offline-editor")
    assert sb.choose(None, None, reviews, default)[0] == "reviews"
    assert sb.choose(None, None, [], default)[0] == "default"


def _tarball_install(be, tmp_path) -> str:
    target = tmp_path / "bin" / "apps" / "demo"
    (target / "1.0" / "bin").mkdir(parents=True)
    exe = target / "1.0" / "bin" / "demo"
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    rec = {"current": {"version": "1.0", "path": str(target / "1.0"), "exec": "1.0/bin/demo"},
           "target": str(target), "links": [], "files": [], "exec": str(exe)}
    be.db.x("INSERT OR REPLACE INTO installs(url, name, version, kind, record, installed_at) VALUES(?,?,?,?,?,?)",
            (URL, "Demo", "1.0", "tarball", json.dumps(rec), now()))
    be._app = lambda url: {"url": URL, "name": "Demo", "installed": "1.0"}
    return str(target)


def test_apps_installed_before_sandbox_support_get_their_launcher_once_it_works(be, tmp_path, monkeypatch):
    # Regression (R17.10): an app installed while AppArmor setup was pending (or bwrap was missing) ran
    # Off — fine — but nothing regenerated its launcher after setup, so it stayed unsandboxed while
    # App Detail showed its grants as if they applied.
    _review(be, "offline-editor")
    _tarball_install(be, tmp_path)
    status = {"status": "setup-needed"}
    monkeypatch.setattr(sb, "have_tools", lambda: True)
    monkeypatch.setattr(sb, "support_status", lambda: dict(status))
    assert be.sandboxInfo(URL)["active"] is False           # shown as not sandboxed
    assert be._heal_launchers() == []                       # nothing to do until the system can sandbox
    status["status"] = "ok"                                 # e.g. the one-time setup just succeeded
    assert be._heal_launchers() == [URL]
    rec = json.loads(be.db.one("SELECT record FROM installs WHERE url=?", (URL,))["record"])
    assert rec["launcher"] and os.path.exists(rec["launcher"]) and rec["exec"] == rec["launcher"]
    assert be.sandboxInfo(URL)["active"] is True
    assert be._heal_launchers() == []                       # idempotent


def test_apps_sandboxed_by_appkata_are_named_before_and_after(be, tmp_path, monkeypatch):
    # Review 2, F13: once setup succeeded the heal sandboxed every waiting app with only "Sandbox
    # support is set up", and at start with no word at all; each then started with an empty home.
    # The setup's entry points now name them first, and the heal names them after and audits each.
    _tarball_install(be, tmp_path)
    status = {"status": "setup-needed"}
    monkeypatch.setattr(sb, "have_tools", lambda: True)
    monkeypatch.setattr(sb, "support_status", lambda: dict(status))
    toasts = []
    be._toast.connect(lambda kind, text: toasts.append(text))
    note = be.sandboxSupport["waitingNote"]
    assert note == "Setting it up sandboxes Demo, which runs unsandboxed until then. It starts with fresh settings; your files aren't touched."
    assert be.sandboxInfo(URL)["support"]["waitingNote"] == note        # App Detail's Enable… banner says it too
    status["status"] = "ok"                                              # e.g. bwrap set up outside AppKata
    assert "waitingNote" not in be.sandboxSupport
    assert be._heal_launchers() == [URL]                                 # AppKata's start
    assert toasts == ["Demo now runs sandboxed, since this system can sandbox it. It starts with fresh settings; your files aren't touched."]
    row = be.db.one("SELECT actor, action, subject, detail FROM audit ORDER BY id DESC LIMIT 1")
    assert (row["actor"], row["action"], row["subject"]) == ("system", "sandboxed", "Demo") and "true" in row["detail"]


def test_the_waiting_note_tells_fresh_homes_from_kept_ones(be):
    note = be._sandboxed_note([("A", True), ("B", False), ("C", True)], waiting=True)
    assert note == ("Setting it up sandboxes the 3 apps that run unsandboxed until then: A, B and C. A and C start with "
                    "fresh settings; B keeps the ones from an earlier sandbox. Your files aren't touched.")
    assert be._sandboxed_note([("A", False), ("B", False)], waiting=False) == \
        "Now sandboxed, since this system can sandbox them: A and B. They keep the settings from an earlier sandbox."
    assert be._sandboxed_note([], waiting=True) == ""


def test_an_update_that_first_sandboxes_an_app_says_so(be, tmp_path, monkeypatch):
    # The update path, too: an app installed while the system couldn't sandbox, updated once it can
    _tarball_install(be, tmp_path)
    status = {"status": "setup-needed"}
    monkeypatch.setattr(sb, "have_tools", lambda: True)
    monkeypatch.setattr(sb, "support_status", lambda: dict(status))
    toasts = []
    be._toast.connect(lambda kind, text: toasts.append(text))
    had = be._sandbox_state(URL)
    assert had == (False, True)
    status["status"] = "ok"
    be._regenerate_launcher(URL)                                         # what the update writes
    be._settle_sandbox(URL, "tarball", had)
    assert toasts and "Demo now runs sandboxed" in toasts[0] and "fresh settings" in toasts[0]
    toasts.clear()
    be._settle_sandbox(URL, "tarball", be._sandbox_state(URL))          # the next update: nothing new to say
    be._settle_sandbox(URL, "tarball", None)                            # nor for a first install
    assert toasts == []


@pytest.mark.parametrize("answer", ["now", "not now"])
def test_the_first_install_that_needs_the_sandbox_asks_to_set_it_up(be, monkeypatch, answer):
    # Review 2, F12: R17.10's "offers a one-time setup on first need ... if declined" was never built;
    # the install card only pointed at Settings. Now a fresh install that would run sandboxed, on a
    # system that needs the setup, asks first; Not now is remembered and audited
    be._app = lambda url: {"url": URL, "name": "Demo", "installed": "", "foreign": False, "installKind": "tarball"}
    be._sandbox_kind = lambda url: "tarball"
    status = {"status": "setup-needed"}
    monkeypatch.setattr(sb, "have_tools", lambda: True)
    monkeypatch.setattr(sb, "support_status", lambda: dict(status))
    monkeypatch.setattr(threading.Thread, "start", lambda t: t.run())
    asked, installs, setups = [], [], []
    be.sandboxSetupNeeded.connect(asked.append)
    monkeypatch.setattr(sb, "install_profile", lambda: (setups.append(1), status.update(status="ok")))
    be._install(URL, "", {"kind": "tarball"})
    assert [a["url"] for a in asked] == [URL] and URL not in be._busy        # asked, nothing installing yet
    real = be._install
    monkeypatch.setattr(be, "_install", lambda *a, **k: installs.append((a, k)) if k.get("asked") else real(*a, **k))
    be.answerSandboxSetup(asked[0], answer == "now")
    assert installs and installs[0][0][0] == URL and installs[0][1]["asked"] is True   # then it installs
    actions = [r["action"] for r in be.db.all("SELECT action FROM audit")]
    if answer == "now":
        assert setups == [1] and "enabled system sandbox support" in actions and not be._prefs.get("sandboxSetupDeclined")
        return
    assert setups == [] and "put off system sandbox support" in actions and be._prefs.get("sandboxSetupDeclined")
    assert not be._setup_prompt_needed(URL, {"kind": "tarball"})            # a later install doesn't ask
    be.setupSandboxSupport()                                                 # Set up… / Enable… clear the Not now
    assert setups == [1] and not be._prefs.get("sandboxSetupDeclined")


@pytest.mark.parametrize("case", ["installed", "off", "cli-off", "ok host", "not linux kind"])
def test_the_setup_prompt_is_only_for_the_first_need(be, monkeypatch, case):
    # Not for an update, an app chosen Off, a host that needs nothing, or a kind that isn't sandboxed
    be._app = lambda url: {"url": URL, "name": "Demo", "installed": "1.0" if case == "installed" else "", "foreign": False}
    be._sandbox_kind = lambda url: "deb" if case == "not linux kind" else "tarball"
    monkeypatch.setattr(sb, "have_tools", lambda: True)
    monkeypatch.setattr(sb, "support_status", lambda: {"status": "ok" if case == "ok host" else "setup-needed"})
    if case in ("off", "cli-off"):
        be.setPref("sandboxGuiDefault" if case == "off" else "sandboxCliDefault", "off")
        monkeypatch.setattr(be, "_is_cli", lambda url, eff=None: case == "cli-off")
    assert not be._setup_prompt_needed(URL, {})


@pytest.mark.parametrize("broken", ["no bwrap", "setup-needed", "conflict"])
def test_an_app_with_a_launcher_keeps_it_on_a_broken_host(be, tmp_path, monkeypatch, broken):
    # Review 2, F16: an update, a rollback or a sandbox change while the support check failed (the
    # profile removed, another bwrap first on PATH, one cached timeout) removed a working launcher, and
    # the app ran with the real home until a later start healed it. Once it has one it keeps one; a
    # fresh install on such a host still runs Off, as before (R17.10).
    _tarball_install(be, tmp_path)
    host = {"tools": True, "status": "ok"}
    monkeypatch.setattr(sb, "have_tools", lambda: host["tools"])
    monkeypatch.setattr(sb, "support_status", lambda: {"status": host["status"]})
    be.setSandbox(URL, {"template": "offline-editor", "overrides": {}})
    launcher = json.loads(be.db.one("SELECT record FROM installs WHERE url=?", (URL,))["record"])["launcher"]
    assert os.path.exists(launcher)
    host.update(tools=broken != "no bwrap", status="unsupported" if broken == "no bwrap" else broken)
    be.setSandbox(URL, {"template": "online-app", "overrides": {}})        # a sandbox change
    rec = json.loads(be.db.one("SELECT record FROM installs WHERE url=?", (URL,))["record"])
    assert rec.get("launcher") == launcher and os.path.exists(launcher) and rec["exec"] == launcher
    assert rec["sandbox"]["network"] is True                                # written for the new grants
    be._regenerate_launcher(URL)                                            # what an update or rollback does
    assert os.path.exists(launcher) and be.sandboxInfo(URL)["active"] is True
    assert be._heal_launchers() == []                                       # the heal leaves it be, too
    assert os.path.exists(launcher)
    be.setSandbox(URL, {"template": "off"})                                 # only the user's own Off removes it
    assert not os.path.exists(launcher)
    be.setSandbox(URL, {"template": "strict", "overrides": {}})             # and with none, the host decides
    assert not json.loads(be.db.one("SELECT record FROM installs WHERE url=?", (URL,))["record"]).get("launcher")


def test_the_startup_pass_regenerates_a_launcher_an_older_appkata_wrote(be, tmp_path, monkeypatch, caplog):
    # Regression (round four, R4-4): the heal pass skipped any launcher that existed, so a launcher
    # written by an older AppKata -- before the symlink guard, the narrowed proxy, the desktop-entry
    # mask, every launcher change this branch made -- kept running as written until the user
    # happened to update the app or touch its sandbox. The launcher is the enforcement (R17.4), so
    # the pass now compares each one with what AppKata would write today and rewrites it if they
    # differ; a hand-edited launcher (R17.4: "do not edit") is restored the same way.
    _review(be, "online-app")
    _tarball_install(be, tmp_path)
    monkeypatch.setattr(sb, "have_tools", lambda: True)
    monkeypatch.setattr(sb, "support_status", lambda: {"status": "ok"})
    import logging
    caplog.set_level(logging.INFO, logger="appkata.gui")
    assert be._heal_launchers() == [URL]                             # written now
    assert "now that this system supports it" in caplog.text        # a launcher that was missing
    rec = json.loads(be.db.one("SELECT record FROM installs WHERE url=?", (URL,))["record"])
    current = open(rec["launcher"]).read()
    assert be._heal_launchers() == []                                # up to date: left alone
    stale = current.replace('set -- --tmpfs "$d" "$@"', "true")      # an older launcher: no desktop-entry mask
    assert stale != current
    open(rec["launcher"], "w").write(stale)
    caplog.clear()
    assert be._heal_launchers() == [URL]                             # noticed and rewritten ...
    # round five, R5-7: a catch-up is logged as one, not as "now that this system supports it"
    assert "up to today's text" in caplog.text and "now that this system supports it" not in caplog.text
    assert open(rec["launcher"]).read() == current
    assert be._heal_launchers() == []                                # ... once


def test_the_startup_pass_rewrites_and_audits_a_launcher_per_app(be, tmp_path, monkeypatch):
    # Review 2, F11: the startup pass rewrote launchers with no Audit entry. Each rewrite is one entry
    # now, by the system, with AppKata's version, the hash of the new text and the set it was written for
    import hashlib
    from appkata_core import __version__
    _tarball_install(be, tmp_path)
    monkeypatch.setattr(sb, "have_tools", lambda: True)
    monkeypatch.setattr(sb, "support_status", lambda: {"status": "ok"})
    be.setSandbox(URL, {"template": "online-app", "overrides": {}})
    lp = json.loads(be.db.one("SELECT record FROM installs WHERE url=?", (URL,))["record"])["launcher"]
    open(lp, "a").write("# a hand edit\n")
    assert be._heal_launchers() == [URL]
    row = be.db.one("SELECT actor, action, detail FROM audit ORDER BY id DESC LIMIT 1")
    detail = json.loads(row["detail"])
    assert (row["actor"], row["action"]) == ("system", "rewrote the launcher of")
    assert detail == {"by": f"AppKata {__version__}", "launcher": hashlib.sha256(open(lp).read().encode()).hexdigest()[:16],
                      "written for": "Online app"}


@pytest.mark.parametrize("which", ["shim", "shim-mode", "forward-helper", "marker", "seccomp"])
def test_the_startup_pass_restores_every_file_the_launcher_relies_on(be, tmp_path, monkeypatch, which):
    # Review 2, F5 (class C): launcher_is_current() compared the launcher's text alone, and the files it
    # calls -- the xdg-open shim, the file-argument helper, the seccomp filter, the app's .flatpak-info
    # -- are named in that text by path, not content. An older AppKata's shim (round five's R5-6 fix
    # lived entirely in it) or marker (no `shared=network`: GLib then reports no network) stayed.
    _review(be, "online-app")
    _tarball_install(be, tmp_path)
    monkeypatch.setattr(sb, "have_tools", lambda: True)
    monkeypatch.setattr(sb, "support_status", lambda: {"status": "ok"})
    monkeypatch.setattr(sb, "seccomp_filter", lambda machine=None: b"\x20\0\0\0\4\0\0\0")   # one on every host
    assert be._heal_launchers() == [URL]
    rec = json.loads(be.db.one("SELECT record FROM installs WHERE url=?", (URL,))["record"])
    app_id = rec.get("id") or "demo"
    path = {"shim": os.path.join(sb.shims_dir(), "xdg-open"), "shim-mode": os.path.join(sb.shims_dir(), "xdg-open"),
            "forward-helper": sb.forward_path(), "marker": sb.identity_path(app_id), "seccomp": sb.seccomp_path()}[which]
    good = open(path, "rb").read()
    if which == "shim-mode":
        os.chmod(path, 0o644)                                       # no longer executable: PATH would skip it
    else:
        with open(path, "wb") as f:
            f.write({"marker": b"[Application]\nname=io.appkata.demo\n"}.get(which, b"# an older AppKata's\n"))
    assert be._heal_launchers() == [URL], which                    # noticed ...
    assert open(path, "rb").read() == good and (which != "shim-mode" or os.access(path, os.X_OK))
    assert be._heal_launchers() == []                               # ... and put right once


def test_an_upgrade_to_a_system_with_its_own_bwrap_profile_rewrites_launchers_at_start(be, tmp_path, monkeypatch):
    # Review 2, F2: whether an app's own sandbox (Chromium, Electron) can run inside AppKata's is a fact
    # of the system -- false under Ubuntu 25.04+'s bwrap-userns-restrict -- and the launcher bakes it in
    # (--no-sandbox for such an app). An upgrade changes the fact under installed launchers; the
    # startup pass, comparing with today's text, rewrites them.
    _review(be, "online-app")
    _tarball_install(be, tmp_path)
    monkeypatch.setattr(sb, "have_tools", lambda: True)
    monkeypatch.setattr(sb, "support_status", lambda: {"status": "ok"})
    monkeypatch.setattr(sb, "nested_userns_works", lambda refresh=False: True)
    assert be._heal_launchers() == [URL]
    rec = json.loads(be.db.one("SELECT record FROM installs WHERE url=?", (URL,))["record"])
    assert "--no-sandbox" not in open(rec["launcher"]).read()
    monkeypatch.setattr(sb, "nested_userns_works", lambda refresh=False: False)     # now on 26.04
    assert be._heal_launchers() == [URL]
    assert "--no-sandbox" in open(rec["launcher"]).read()
    assert be._heal_launchers() == []


def test_the_repair_removes_appkatas_profile_heals_and_is_audited(be, monkeypatch):
    # Review 2, F2: AppKata's profile left beside the system's own after an upgrade stops bwrap for
    # everyone (status "conflict"); Settings and App Detail offer Repair, which removes it.
    removed, healed = [], []
    monkeypatch.setattr(sb, "other_bwrap_profiles", lambda bwrap=None: ["bwrap-userns-restrict"])
    monkeypatch.setattr(sb, "remove_profile", lambda: removed.append(1) or True)
    monkeypatch.setattr(be, "_heal_launchers", lambda actor="system": healed.append(actor) or [])
    import threading
    monkeypatch.setattr(threading.Thread, "start", lambda self: self.run())
    be.repairSandboxSupport()
    assert removed == [1] and healed == ["you"]
    row = be.db.one("SELECT kind, action, subject, detail FROM audit ORDER BY id DESC LIMIT 1")
    assert (row["kind"], row["action"], row["subject"]) == ("setting", "removed AppKata's AppArmor profile", "AppArmor")
    assert "bwrap-userns-restrict" in row["detail"]


def test_setup_success_regenerates_launchers(be, tmp_path, monkeypatch):
    _review(be, "offline-editor")
    _tarball_install(be, tmp_path)
    monkeypatch.setattr(sb, "have_tools", lambda: True)
    monkeypatch.setattr(sb, "support_status", lambda: {"status": "ok"})
    monkeypatch.setattr(sb, "install_profile", lambda: True)
    import threading
    started = []
    monkeypatch.setattr(threading.Thread, "start", lambda self: (started.append(1), self.run()))
    be.setupSandboxSupport()
    rec = json.loads(be.db.one("SELECT record FROM installs WHERE url=?", (URL,))["record"])
    assert started and rec.get("launcher") and os.path.exists(rec["launcher"])


def test_a_custom_sandbox_cannot_share_a_protected_folder(be, tmp_path):
    # Regression: the Customize picker accepted any folder, the home one included, and the launcher
    # bound it; now the save drops it and says so.
    toasts = []
    be._toast.connect(lambda kind, text: toasts.append((kind, text)))
    gs = sb.to_json(sb.apply_overrides(sb.resolve_template("standard"),
                                       {"folders": {"+~": "rw", "+~/.ssh": "ro", "+~/Projects": "rw"}}))
    be.setSandbox(URL, {"custom": gs})
    saved = be._user_sandbox_config(URL)
    assert set(saved["custom"]["folders"]) == {"~/Projects"}
    assert toasts and toasts[0][0] == "error" and "~ (your whole home folder)" in toasts[0][1] and "~/.ssh" in toasts[0][1]
    assert "~/Projects" in [c[0] for c in be.sandboxInfo(URL)["chips"]]


def test_the_review_badge_clears_once_the_user_acts_on_the_suggestion(be):
    # Regression: the badge showed whenever the merged review differed from the current grants, the
    # user's own deliberate choice included, and nothing in the UI could adopt the suggestion or keep
    # the current grants — so it stood forever.
    be._app = lambda url: {"url": URL, "name": "Demo", "installed": "1.0"}
    _review(be, "offline-editor")
    _installed(be)
    be._pin_sandbox(URL, be._resolved_sandbox(URL, kind="appimage"))
    _review(be, "online-app")
    assert be.sandboxInfo(URL)["reviewBadge"] is True

    be.keepSandbox(URL)                                        # "Keep mine"
    info = be.sandboxInfo(URL)
    assert info["reviewBadge"] is False and info["grants"]["network"] is False and info["hasSuggestion"]

    _review(be, "messenger")                                   # a different suggestion later
    assert be.sandboxInfo(URL)["reviewBadge"] is True

    be.setSandbox(URL, {"template": "strict", "overrides": {}})   # chose my own, knowing it
    info = be.sandboxInfo(URL)
    assert info["reviewBadge"] is False and info["source"] == "user" and info["level"] == "strict"

    _review(be, "media-player")
    assert be.sandboxInfo(URL)["reviewBadge"] is True
    be.setSandbox(URL, None)                                   # "Use theirs"
    info = be.sandboxInfo(URL)
    assert info["reviewBadge"] is False and info["hasSuggestion"] is False
    assert [c[0] for c in info["chips"]] == [c[0] for c in info["reviewSuggests"]]


def test_open_reports_a_launch_that_fails_at_once(be, tmp_path, monkeypatch):
    # Regression: Open swallowed the launcher's output and exit code, so a sandboxed app that bwrap
    # couldn't start looked like nothing happened.
    _tarball_install(be, tmp_path)
    toasts = []
    be.toast.connect(lambda kind, text: toasts.append((kind, text)))
    captured = {}
    monkeypatch.setattr(be, "_app", lambda url: {"url": URL, "name": "Demo", "installed": "1.0"})
    from appkata_core import install
    monkeypatch.setattr(install, "launch", lambda db, url, on_failed=None: captured.setdefault("cb", on_failed))
    be.openApp(URL)
    captured["cb"](1, ["bwrap: setting up uid map: Permission denied"])
    assert toasts == [("error", "Demo didn't start (exit 1): bwrap: setting up uid map: Permission denied. See the App log.")]


def test_startup_healing_leaves_foreign_installs_alone(be, tmp_path, monkeypatch):
    # setSandbox never touches an app installed outside AppKata (R4.5); the startup healing pass did.
    _review(be, "offline-editor")
    _tarball_install(be, tmp_path)
    monkeypatch.setattr(sb, "have_tools", lambda: True)
    monkeypatch.setattr(sb, "support_status", lambda: {"status": "ok"})
    be._app = lambda url: {"url": URL, "name": "Demo", "installed": "1.0", "foreign": "found"}
    assert be._heal_launchers() == []
    be._app = lambda url: {"url": URL, "name": "Demo", "installed": "1.0"}
    assert be._heal_launchers() == [URL]


def test_appkata_itself_is_never_sandboxed_and_a_launcher_an_older_one_gave_it_goes(be, tmp_path, monkeypatch):
    # Review 3, R3-6 (found by the lifecycle harness): run as an AppImage, AppKata adopts its own file
    # as installed (R2.11), and nothing kept that install out of sandboxing. The heal pass gave it a
    # Strict launcher with no network, and its menu entry, command link, autostart and appkata://
    # links then started it where it could neither sync nor install (R17.1).
    from appkata_core import APPKATA_REPO, install
    monkeypatch.setattr(sb, "have_tools", lambda: True)
    monkeypatch.setattr(sb, "support_status", lambda: {"status": "ok"})
    image = tmp_path / "Downloads" / "AppKata-x86_64.AppImage"
    image.parent.mkdir()
    image.write_text("#!/bin/sh\n")
    image.chmod(0o755)
    monkeypatch.setenv("APPIMAGE", str(image))
    be._ensure_self()
    be._app = lambda url: {"url": url, "name": "AppKata", "installed": "9.9"} if url == APPKATA_REPO else None
    rec = lambda: json.loads(be.db.one("SELECT record FROM installs WHERE url=?", (APPKATA_REPO,))["record"])  # noqa: E731
    assert be._resolved_sandbox(APPKATA_REPO) is None and be._sandbox_for_install(APPKATA_REPO) is None
    assert be._heal_launchers() == [] and not rec().get("launcher") and rec()["exec"] == str(image)
    # what an older AppKata left behind: a launcher, with everything pointing at it
    install.rewrite_launcher(be.db, {"url": APPKATA_REPO, "name": "AppKata", "sandbox": sb.resolve_template("strict")},
                             be._app_options(APPKATA_REPO))
    left = rec()["launcher"]
    assert os.path.exists(left) and rec()["exec"] == left
    assert be._heal_launchers() == [APPKATA_REPO]                # the next start undoes it
    assert not rec().get("launcher") and not os.path.exists(left)
    assert os.path.realpath(rec()["exec"]) == os.path.realpath(image)      # the program again (its stable link)
    assert be._heal_launchers() == []


def test_settings_and_app_detail_warn_about_an_abstract_session_bus_for_apps_with_the_network(be, monkeypatch):
    # Review 3, R3-8 (R17.9): Settings > Sandbox says it for the session; App Detail only for an app the
    # network grant lets reach the bus
    monkeypatch.setattr(be, "_app", lambda url: {"url": URL, "name": "Demo", "installed": ""})
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", "unix:abstract=/tmp/dbus-AbCdEf,guid=0123")
    assert be.sandboxSupport["busWarning"]["text"]
    be.setSandbox(URL, {"template": "online-app", "overrides": {}})
    assert be.sandboxInfo(URL)["busWarning"]["text"]
    be.setSandbox(URL, {"template": "offline-editor", "overrides": {}})
    assert be.sandboxInfo(URL)["busWarning"] == {}
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", "unix:path=/run/user/1000/bus")
    be.setSandbox(URL, {"template": "online-app", "overrides": {}})
    assert be.sandboxInfo(URL)["busWarning"] == {} and be.sandboxSupport["busWarning"] == {}


@pytest.mark.parametrize("kind,os_name,applies", [
    ("appimage", "linux", True), ("tarball", "linux", True),
    ("deb", "linux", False), ("rpm", "linux", False), ("flatpak", "linux", False), ("package", "linux", False),
    ("shell", "linux", False), ("", "linux", False),
    ("appimage", "windows", False), ("tarball", "macos", False), ("exe", "windows", False),
])
def test_only_appimages_and_tarballs_on_linux_get_a_sandbox(be, monkeypatch, kind, os_name, applies):
    # R17.1: Linux only, and only the two portable kinds AppKata installs itself. A .deb's or .rpm's
    # scripts ran as root at install, a Flatpak has its own sandbox, and Windows and macOS have none of
    # this. Review 3, R3-1: no test ever asked for any of them.
    import appkata_core.platform as platform
    monkeypatch.setattr(platform, "OS", os_name)
    monkeypatch.setattr(be, "_app", lambda url: {"url": URL, "name": "Demo", "installed": ""})
    monkeypatch.setattr(be, "_sandbox_kind", lambda url: kind)
    r = be._resolved_sandbox(URL)
    assert (r is not None) is applies
    assert be.sandboxInfo(URL)["applicable"] is applies
    if not applies:
        assert be._sandbox_for_install(URL) is None                        # no launcher, ever


def _plan_with(be, monkeypatch, names):
    """Backend._plan for a release offering these files (100 MB each), with no package channels."""
    from appkata_core import channels, sync
    assets = [{"name": n, "url": f"https://example.org/{n}", "size": 100_000_000} for n in names]
    monkeypatch.setattr(sync, "ensure_assets", lambda db, http, url, version: {"assets": assets})
    monkeypatch.setattr(channels, "enabled", lambda: False)
    monkeypatch.setattr(be, "_app", lambda url: {"url": URL, "name": "Demo", "installed": "", "version": "1.0", "updateTo": ""})
    return be._plan(URL, "1.0")


def test_the_install_dialogs_sandbox_card_is_what_planfor_computes(be, monkeypatch):
    # Review 3, R3-3: the dialog tests build the plan by hand, so what planFor itself gives the Sandbox
    # card went untested -- the unpacking cost (R17.7), the card for each kind (review 2, F4) and a
    # review's Off offered, never applied (F8). Here planFor computes it, against App Detail's view.
    monkeypatch.setattr(sb, "have_tools", lambda: True)
    monkeypatch.setattr(sb, "support_status", lambda: {"status": "ok"})
    img = "Demo-1.0-x86_64.AppImage"
    card = _plan_with(be, monkeypatch, [img])["sandbox"]
    info = be.sandboxInfo(URL)
    assert card["applicable"] and card["appImage"] and card["suggestsOff"] is False
    assert (card["template"], card["level"], card["chips"]) == (info["template"], info["level"], info["chips"])
    assert card["extractMb"] == 250                                    # 2.5 x the AppImage (R17.7)
    assert card["byKind"]["gui"]["template"] == "strict" and card["byKind"]["cli"]["template"] == "cli-tool"   # R17.3.3
    assert set(_plan_with(be, monkeypatch, [img])["kind"]) == {"detected", "choice"}
    _review(be, "off")                                                 # a review's Off: offered, not applied
    card = _plan_with(be, monkeypatch, [img])["sandbox"]
    assert card["suggestsOff"] is True and card["level"] != "off" and card["extractMb"] == 250
    be.setSandbox(URL, {"template": "off"})                           # the user's Off: nothing to unpack
    card = _plan_with(be, monkeypatch, [img])["sandbox"]
    assert card["level"] == "off" and card["extractMb"] == 0
    card = _plan_with(be, monkeypatch, ["demo-1.0-linux-x86_64.tar.gz"])["sandbox"]
    assert card["applicable"] and not card["appImage"] and card["extractMb"] == 0
    # a system package (whichever this distribution family takes): no Sandbox card
    assert _plan_with(be, monkeypatch, ["demo_1.0_amd64.deb", "demo-1.0-1.x86_64.rpm"])["sandbox"] == {"applicable": False}


def test_a_review_that_changes_only_the_mpris_name_raises_the_badge_and_offers_it(be):
    # The review of PR #694, P1-1: the badge and the dialog's "Use theirs" rose only where the
    # suggestion's chips differed from the app's, and no chip shows the MPRIS name (the chip is the
    # capability's, CR1.9-32). An app pinned with every player's name, whose Trust then named its own,
    # kept every player and was never offered the narrowing (CR1.5-36); nor was a review that dropped
    # a name the user's own set had. The badge's own words said it, under a badge that never showed.
    # How it slipped past: the chips stood for the grant set there, and the test of the named player
    # (test_dialog_contract) read the badge's words, never whether the badge was up.
    name = "org.mpris.MediaPlayer2.demo"
    be._app = lambda url: {"url": URL, "name": "Demo", "installed": "1.0"}
    _review(be, "media-player")
    _installed(be)
    be._pin_sandbox(URL, be._resolved_sandbox(URL, kind="appimage"))         # installed while no review named it
    _review_lines(be, f"- Sandbox (linux): media-player\n- Sandbox MPRIS name (linux): {name}\n")
    info = be.sandboxInfo(URL)
    assert info["source"] == "pinned" and info["reviewBadge"] is True and info["hasSuggestion"] is True, info
    assert f"removing media-player names other than {name}" in info["reviewBadgeText"]
    be.keepSandbox(URL)                                                       # "Keep mine": this suggestion is seen
    assert be.sandboxInfo(URL)["reviewBadge"] is False and be.sandboxInfo(URL)["hasSuggestion"] is True
    be.useSuggestion(URL)                                                     # "Use theirs"
    info = be.sandboxInfo(URL)
    assert info["grants"]["mpris_name"] == name and info["reviewBadge"] is False and info["hasSuggestion"] is False, info
    # the other way: the user's own set names it, and the review drops the name
    be.setSandbox(URL, {"template": "media-player", "overrides": {"mpris_name": name}})
    _review(be, "media-player")
    info = be.sandboxInfo(URL)
    assert info["reviewBadge"] is True and info["hasSuggestion"] is True and "adding every media-player name" in info["reviewBadgeText"], info


def test_resaving_install_options_keeps_the_pin_the_seen_marker_and_the_users_choice(be, monkeypatch):
    # Regression (A1.12.5, R17.11): installWith rewrote app_settings.install from the dialog's fields
    # alone, so "Install options…" saved without touching the Sandbox card dropped the pin, the "seen"
    # marker and the user's own sandbox choice; the next install then re-pinned from the current
    # reviews — the silent widening the pin exists to prevent, one step earlier.
    monkeypatch.setattr(be, "_app", lambda url: {"url": URL, "name": "Demo", "installed": "1.0"})
    monkeypatch.setattr(be, "_install", lambda *a, **k: None)
    _review(be, "offline-editor")
    _installed(be)
    be._pin_sandbox(URL, be._resolved_sandbox(URL, kind="appimage"))
    _review(be, "online-app")
    be.keepSandbox(URL)                                        # "Keep mine" on the new suggestion
    be.installWith(URL, {"kind": "appimage", "appMenu": True, "install": False})      # options re-saved
    after = be._install_settings(URL)
    assert after["kind"] == "appimage" and after["appMenu"] is True
    assert "sandboxPinned" in after and after["sandboxReviewSeen"] is not None
    r = be._resolved_sandbox(URL, kind="appimage")
    assert r["source"] == "pinned" and r["grants"]["network"] is False
    assert be.sandboxInfo(URL)["reviewBadge"] is False      # "Keep mine" is remembered

    be.setSandbox(URL, {"template": "strict", "overrides": {}})          # a choice of the user's own
    be.installWith(URL, {"kind": "appimage", "appMenu": False, "install": False})
    assert be._resolved_sandbox(URL, kind="appimage")["source"] == "user"
    assert be._install_settings(URL)["appMenu"] is False       # the dialog's own keys do change

    # a package channel replaces how the app is installed, not what the user decided about its sandbox;
    # and back to a portable, the stale channel key doesn't linger to preselect that card
    monkeypatch.setattr(be, "_install_channel", lambda *a, **k: None)
    be.installWith(URL, {"channel": "flatpak", "install": False})
    assert be._install_settings(URL).get("channel") == "flatpak" and "kind" not in be._install_settings(URL)
    assert be._install_settings(URL)["sandbox"]["template"] == "strict"
    be.installWith(URL, {"kind": "appimage", "appMenu": True, "install": False})
    assert "channel" not in be._install_settings(URL) and be._install_settings(URL)["sandbox"]["template"] == "strict"


def test_a_sandbox_chosen_in_the_install_dialog_counts_as_seen(be, monkeypatch):
    # Regression (R17.11): the install dialog's Sandbox card says "suggested by <reviewer>" beside the
    # dropdown, yet a template picked there was saved without the "seen" marker, so the review badge
    # greeted the user as soon as the install finished — for a suggestion they had just overruled.
    monkeypatch.setattr(be, "_app", lambda url: {"url": URL, "name": "Demo", "installed": "1.0"})
    monkeypatch.setattr(be, "_install", lambda *a, **k: None)
    _review(be, "online-app")
    be.installWith(URL, {"kind": "appimage", "appMenu": True, "sandbox": {"template": "strict", "overrides": {}}})
    _installed(be)
    be._pin_sandbox(URL, be._resolved_sandbox(URL, kind="appimage"))      # what the install then records
    info = be.sandboxInfo(URL)
    assert info["source"] == "user" and info["level"] == "strict"
    assert info["reviewBadge"] is False and info["hasSuggestion"] is True
    _review(be, "messenger")                                   # a different suggestion later still badges
    assert be.sandboxInfo(URL)["reviewBadge"] is True


def test_the_startup_pass_warms_the_bwrap_probe_even_with_nothing_to_heal(be, monkeypatch):
    # Regression (round two, R5): _heal_launchers only called support_status() when some app needed
    # a launcher, so on an ordinary start the 15 s-timeout bwrap probe still ran on the UI thread at
    # the first sandboxInfo()/sandboxSupport — what moving the pass off that thread was meant to end.
    probes = []
    monkeypatch.setattr(sb, "userns_works", lambda refresh=False: (probes.append(1), True)[1])
    monkeypatch.setattr(sb, "have_tools", lambda: True)
    assert be.db.one("SELECT 1 FROM installs") is None       # nothing installed, nothing to heal
    be._heal_launchers_at_startup()
    assert probes == [1]


def test_saving_the_dialog_on_a_merged_review_app_keeps_what_it_showed(be, monkeypatch):
    # Regression (round four, R4-1): two Trusts' Sandbox lines merge to the template name "custom"
    # (so does a pin taken from them); the dialog's Save with nothing customized sent
    # {template: "custom"}, grants_from_config looked that up as a built-in template (KeyError),
    # and since setSandbox had already written the choice, every sandboxInfo() for the app raised
    # from then on. Now an invalid config is refused before anything is written, and the resolver
    # ignores one already in a row.
    monkeypatch.setattr(be, "_app", lambda url: {"url": URL, "name": "Demo", "installed": "1.0"})
    be.db.x("INSERT INTO trusts(url, name, enabled, score) VALUES(?,?,1,2)", ("https://example.org/trust2", "Bob"))
    _review(be, "online-app")
    section = "## Demo::Settings\n\n- Trust: 4\n- Sandbox (linux): offline-editor\n"
    parsed, _ = trustfile.parse_section("Demo", section)
    tid = be.db.one("SELECT id FROM trusts WHERE name='Bob'")["id"]
    be.db.x("INSERT OR REPLACE INTO reviews(trust_id, url, app, settings) VALUES(?,?,?,?)", (tid, URL, "Demo", json.dumps(parsed["opts"])))
    _installed(be)
    info = be.sandboxInfo(URL)
    assert info["template"] == "custom" and info["source"] == "reviews"
    toasts = []
    be._toast.connect(lambda kind, text: toasts.append((kind, text)))
    be.setSandbox(URL, {"template": info["template"], "overrides": {}})     # what the dialog sent
    after = be.sandboxInfo(URL)                                             # must not raise
    assert "sandbox" not in be._install_settings(URL)                       # nothing written ...
    assert toasts and toasts[0][0] == "error"                               # ... and said so
    assert [c[0] for c in after["chips"]] == [c[0] for c in info["chips"]]
    be.setSandbox(URL, {"custom": info["grants"]})                          # what it sends now
    after = be.sandboxInfo(URL)
    assert after["source"] == "user" and [c[0] for c in after["chips"]] == [c[0] for c in info["chips"]]
    # a row poisoned by the old code is ignored rather than fatal
    saved = be._install_settings(URL)
    saved["sandbox"] = {"template": "custom", "overrides": {}}
    be._set_install_settings(URL, saved)
    assert be.sandboxInfo(URL)["source"] == "reviews"


def test_a_sandbox_chosen_in_install_options_for_an_installed_app_applies_at_once(be, tmp_path, monkeypatch):
    # Regression (round four, R4-3): the install dialog's Save for an installed app sends
    # install: false with the Sandbox card's choice; installWith saved it and reloaded, and only an
    # install or the Sandbox dialog ever regenerated the launcher. App Detail then showed the new
    # level as in force (the user's choice wins in the resolver) while ~/bin/apps/<app>/run kept the
    # old grants until the next update. Now the choice regenerates the launcher and is audited, as
    # the Sandbox dialog's is.
    _review(be, "online-app")
    _tarball_install(be, tmp_path)
    monkeypatch.setattr(sb, "have_tools", lambda: True)
    monkeypatch.setattr(sb, "support_status", lambda: {"status": "ok"})
    monkeypatch.setattr(be, "_install", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no install expected")))
    be._regenerate_launcher(URL)                                  # running with its launcher: online-app
    be._pin_sandbox(URL, be._resolved_sandbox(URL))
    rec = json.loads(be.db.one("SELECT record FROM installs WHERE url=?", (URL,))["record"])
    assert "--share-net" in open(rec["launcher"]).read()
    be.installWith(URL, {"kind": "tarball", "appMenu": True, "install": False,
                         "sandbox": {"template": "strict", "overrides": {}}})
    info = be.sandboxInfo(URL)
    assert info["level"] == "strict" and info["source"] == "user" and info["active"]
    text = open(rec["launcher"]).read()
    assert "--share-net" not in text and "xdg-dbus-proxy" not in text      # the launcher says what the detail says
    assert be.db.one("SELECT action FROM audit ORDER BY id DESC LIMIT 1")["action"] == "set the sandbox of"


def test_a_sandbox_change_that_cant_be_written_says_so_and_leaves_the_app_as_it_was(be, tmp_path, monkeypatch):
    # #689's review, P4-B3: turning a sandbox Off with the menu entry's write failing (a full disk)
    # left the launcher removed under a record that still named it, and the Sandbox dialog's Save
    # said nothing: _regenerate_launcher only logged it. The change is taken back (install's
    # test_a_sandbox_change_whose_menu_file_cant_be_written_leaves_the_app_as_it_was), and a toast
    # says it wasn't made.
    from appkata_core import install
    _review(be, "online-app")
    _tarball_install(be, tmp_path)
    monkeypatch.setattr(sb, "have_tools", lambda: True)
    monkeypatch.setattr(sb, "support_status", lambda: {"status": "ok"})
    be._regenerate_launcher(URL)
    be._pin_sandbox(URL, be._resolved_sandbox(URL))
    rec = json.loads(be.db.one("SELECT record FROM installs WHERE url=?", (URL,))["record"])
    with open(rec["launcher"], "rb") as f:
        launcher = f.read()
    toasts, real, failed = [], install._write_whole, []
    be._toast.connect(lambda kind, text: toasts.append((kind, text)))

    def full_once(path, data, mode):
        if path.endswith(".desktop") and not failed:
            failed.append(path)
            raise OSError(28, "No space left on device")
        return real(path, data, mode)
    monkeypatch.setattr(install, "_write_whole", full_once)
    be.setSandbox(URL, {"template": "off"})
    assert failed and toasts == [("error", "Couldn't change the sandbox of Demo, so it runs as it did: [Errno 28] No space left on device")]
    assert json.loads(be.db.one("SELECT record FROM installs WHERE url=?", (URL,))["record"]) == rec
    with open(rec["launcher"], "rb") as f:
        assert f.read() == launcher and be.sandboxInfo(URL)["active"]          # it runs sandboxed, as it did
    be.setSandbox(URL, {"template": "off"})                                   # saved again, with room on the disk
    assert len(toasts) == 1 and not os.path.exists(rec["launcher"]) and not be.sandboxInfo(URL)["active"]


# What App Detail and the Sandbox dialog say of an app's sandbox (sandboxInfo's own words for it)
_SHOWN = ("source", "template", "level", "grants", "chips", "network", "customized", "active", "launcherHash", "reviewBadge",
          "isCli")


@pytest.mark.parametrize("how", ["the Sandbox dialog, Strict", "the Sandbox dialog, Off", "Install options, Strict",
                                 "a corrected kind"])
def test_a_sandbox_change_that_cant_be_written_takes_its_choice_back_with_it(be, tmp_path, monkeypatch, how):
    # #689's review, P5-3: a Save whose change was taken back (the menu entry's write failing on a
    # full disk) kept the choice saved. App Detail and the Sandbox dialog showed it as in force,
    # Strict and no network, while the app ran with the network; the Audit's "set the sandbox of"
    # row named the old launcher's hash as written for Strict; and a failed Off stayed sandboxed
    # under "Off", which AppKata's start never rewrites. The choice goes back with the change, and a
    # failed change has no Audit entry (R13.3).
    from appkata_core import install
    if how == "a corrected kind":           # the kind the user says the app is, as the dialog saves it (R17.3.3):
        monkeypatch.setattr(be, "_is_cli", lambda url, eff=None: be._install_settings(url).get("cliKind") == "cli")
    else:                                   # with no review, the default for that kind applies
        _review(be, "online-app")
    _tarball_install(be, tmp_path)
    monkeypatch.setattr(sb, "have_tools", lambda: True)
    monkeypatch.setattr(sb, "support_status", lambda: {"status": "ok"})
    be._regenerate_launcher(URL)
    be._pin_sandbox(URL, be._resolved_sandbox(URL))
    rec = json.loads(be.db.one("SELECT record FROM installs WHERE url=?", (URL,))["record"])
    shown, settings = {k: be.sandboxInfo(URL)[k] for k in _SHOWN}, be._install_settings(URL)
    audited = [(r["action"], r["subject"]) for r in be.db.all("SELECT action, subject FROM audit")]
    toasts, real, failed = [], install._write_whole, []
    be._toast.connect(lambda kind, text: toasts.append((kind, text)))

    def full_once(path, data, mode):
        if path.endswith(".desktop") and not failed:
            failed.append(path)
            raise OSError(28, "No space left on device")
        return real(path, data, mode)
    monkeypatch.setattr(install, "_write_whole", full_once)
    monkeypatch.setattr(be, "_install", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no install expected")))
    strict = {"template": "strict", "overrides": {}}

    def save():
        if how == "the Sandbox dialog, Strict":
            be.setSandbox(URL, strict)
        elif how == "the Sandbox dialog, Off":
            be.setSandbox(URL, {"template": "off"})
        elif how == "Install options, Strict":
            be.installWith(URL, {"kind": "tarball", "appMenu": True, "install": False, "sandbox": strict})
        else:
            be.installWith(URL, {"kind": "tarball", "appMenu": True, "install": False, "cliKind": "cli"})
    save()
    assert failed and toasts == [("error", "Couldn't change the sandbox of Demo, so it runs as it did: [Errno 28] No space left on device")]
    assert json.loads(be.db.one("SELECT record FROM installs WHERE url=?", (URL,))["record"]) == rec      # it runs as it did
    assert {k: be.sandboxInfo(URL)[k] for k in _SHOWN} == shown                 # and is shown as it runs
    assert {k: v for k, v in be._install_settings(URL).items() if k in be._SANDBOX_KEYS + ("cliKind",)} == \
           {k: v for k, v in settings.items() if k in be._SANDBOX_KEYS + ("cliKind",)}
    assert [r["action"] for r in be.db.all("SELECT action FROM audit")][len(audited):] in ([], ["chose how to install"])                            # no sandbox change to audit
    save()                                                                      # saved again, with room on the disk
    assert len(toasts) == 1 and be.sandboxInfo(URL)["template"] == {"the Sandbox dialog, Off": "off", "a corrected kind": "cli-tool"}.get(how, "strict")
    assert be.db.one("SELECT action FROM audit ORDER BY id DESC LIMIT 1")["action"] == "set the sandbox of"


def test_a_sandbox_change_that_cant_be_put_back_says_what_isnt_as_it_was(be, tmp_path, monkeypatch):
    # #689's review, P5-2: where a failed change couldn't all be put back either, the toast said the
    # app "runs as it did" all the same. Here the file system makes no hard links, so putting the
    # change back writes what it replaced, and the disk is full from the menu entry's write on: the
    # toast names what isn't as it was (install's
    # test_a_sandbox_change_that_cant_be_put_back_names_what_isnt_as_it_was holds the names to the
    # files), and the choice goes back as for a change put back in full (P5-3).
    from appkata_core import install
    _review(be, "online-app")
    _tarball_install(be, tmp_path)
    monkeypatch.setattr(sb, "have_tools", lambda: True)
    monkeypatch.setattr(sb, "support_status", lambda: {"status": "ok"})
    be._regenerate_launcher(URL)
    be._pin_sandbox(URL, be._resolved_sandbox(URL))
    shown = {k: be.sandboxInfo(URL)[k] for k in _SHOWN if k not in ("active", "launcherHash")}
    toasts, real, failed = [], install._write_whole, []
    be._toast.connect(lambda kind, text: toasts.append((kind, text)))

    def full(path, data, mode):             # the menu entry's write, and every one after it
        if path.endswith(".desktop") or failed:
            failed.append(path)
            raise OSError(28, "No space left on device")
        return real(path, data, mode)

    def no_hard_links(*a, **k):
        raise OSError(1, "Operation not permitted")
    monkeypatch.setattr(install, "_write_whole", full)
    monkeypatch.setattr(os, "link", no_hard_links)
    be.setSandbox(URL, {"template": "off"})
    assert toasts == [("error", "Couldn't change the sandbox of Demo: [Errno 28] No space left on device. It couldn't all be "
                                "put back either: its launcher and its app-menu entry aren't as they were.")]
    assert {k: be.sandboxInfo(URL)[k] for k in shown} == shown              # the choice it runs with, as it was


def test_an_error_rewriting_one_apps_launcher_is_said_and_stops_nothing_else(be, tmp_path, monkeypatch):
    # #689's review, C-1 (its checker's note on P4-1): _regenerate_launcher caught InstallError and
    # OSError alone. Any other error (P4-1's UnicodeEncodeError was one) left the Sandbox dialog's
    # Save after the choice was saved and before its audit row and the reload: the choice was in
    # force, unaudited, and the window not refreshed. At AppKata's start it stopped the heal pass,
    # so the apps after that one kept their stale launchers, at every start. Here the launcher's
    # rewrite fails for one app with an error AppKata doesn't expect.
    from appkata_core import install
    other = URL + "-other"
    _review(be, "online-app")
    _tarball_install(be, tmp_path)
    target = tmp_path / "bin" / "apps" / "other"
    (target / "1.0" / "bin").mkdir(parents=True)
    (target / "1.0" / "bin" / "other").write_text("#!/bin/sh\n")
    (target / "1.0" / "bin" / "other").chmod(0o755)
    rec = {"current": {"version": "1.0", "path": str(target / "1.0"), "exec": "1.0/bin/other"},
           "target": str(target), "links": [], "files": []}
    be.db.x("INSERT INTO installs(url, name, version, kind, record, installed_at) VALUES(?,?,?,?,?,?)",
            (other, "Other", "1.0", "tarball", json.dumps(rec), now()))
    be._app = lambda url: {"url": url, "name": "Demo" if url == URL else "Other", "installed": "1.0"}
    monkeypatch.setattr(sb, "have_tools", lambda: True)
    monkeypatch.setattr(sb, "support_status", lambda: {"status": "ok"})
    launchers = {}
    for url in (URL, other):
        be._regenerate_launcher(url)
        be._pin_sandbox(url, be._resolved_sandbox(url))
        launchers[url] = json.loads(be.db.one("SELECT record FROM installs WHERE url=?", (url,))["record"])["launcher"]
        with open(launchers[url], "wb") as f:
            f.write(b"#!/bin/sh\n# hand-edited\n")                     # not today's text: the start rewrites it
    real, toasts, reloads = install.rewrite_launcher, [], []

    def fails_for_demo(db, app, portable):
        if app["url"] == URL:
            raise ValueError("a stand-in for an error AppKata doesn't expect")
        return real(db, app, portable)
    monkeypatch.setattr(install, "rewrite_launcher", fails_for_demo)
    be._toast.connect(lambda kind, text: toasts.append((kind, text)))
    monkeypatch.setattr(be, "reload", lambda: reloads.append(1))
    be._heal_launchers()                                                    # AppKata's start goes on past Demo
    with open(launchers[other], "rb") as f:
        assert f.read() != b"#!/bin/sh\n# hand-edited\n"
    audited = be.db.one("SELECT COUNT(*) AS n FROM audit")["n"]
    be.setSandbox(URL, {"template": "strict", "overrides": {}})
    assert toasts == [("error", "Couldn't change the sandbox of Demo, so it runs as it did: a stand-in for an error AppKata doesn't expect")]
    # the window is refreshed, and the choice goes back with the change, which isn't audited (P5-3)
    assert reloads == [1] and be.sandboxInfo(URL)["template"] == "online-app"
    assert be.db.one("SELECT COUNT(*) AS n FROM audit")["n"] == audited


@pytest.mark.parametrize("fails", ["the menu entry", "the launcher"])
def test_a_launcher_appkatas_start_cant_rewrite_is_left_as_it_was_and_not_audited(be, tmp_path, monkeypatch, caplog, fails):
    # #689's review, P6-1: AppKata's start rewrites a launcher that isn't today's text (an older
    # AppKata's, or a hand-edited one), and dropped what the rewrite returned. Where it couldn't be
    # written (a full disk, the menu folder read-only), the rewrite was put back (P5-2) and the start
    # still wrote "rewrote the launcher of Demo", with the hash of the launcher left on disk, written
    # for a set it wasn't written for, again at every start while the failure lasted, and logged
    # that it had brought the launcher up to today's text. A failed operation is no Audit entry; the
    # App log has it (R13.3), and the next start tries again.
    import hashlib
    import logging
    from appkata_core import install
    _review(be, "online-app")
    _tarball_install(be, tmp_path)
    monkeypatch.setattr(sb, "have_tools", lambda: True)
    monkeypatch.setattr(sb, "support_status", lambda: {"status": "ok"})
    be._regenerate_launcher(URL)
    be._pin_sandbox(URL, be._resolved_sandbox(URL))
    launcher = json.loads(be.db.one("SELECT record FROM installs WHERE url=?", (URL,))["record"])["launcher"]
    with open(launcher, "wb") as f:
        f.write(b"#!/bin/sh\n# hand-edited\n")                            # not today's text: the start rewrites it
    audit = lambda: [json.loads(r["detail"]) for r in be.db.all(                               # noqa: E731
        "SELECT detail FROM audit WHERE action='rewrote the launcher of' ORDER BY id")]
    caplog.set_level(logging.INFO, logger="appkata.gui")

    def full(*a, **k):
        raise OSError(28, "No space left on device")
    with monkeypatch.context() as m:
        m.setattr(install, "_desktop_entry", full) if fails == "the menu entry" else m.setattr(sb, "write_launcher", full)
        assert be._heal_launchers() == [] and be._heal_launchers() == []      # two starts: nothing rewritten
    with open(launcher, "rb") as f:
        assert f.read() == b"#!/bin/sh\n# hand-edited\n"                    # put back, as R17.4 has it
    assert audit() == []                                                    # and no Audit entry says otherwise
    assert caplog.text.count("couldn't regenerate the launcher for") == 2 and "up to today's text" not in caplog.text
    caplog.clear()
    assert be._heal_launchers() == [URL]                                    # with room, the next start rewrites it
    with open(launcher, "rb") as f:
        written = f.read()
    assert written != b"#!/bin/sh\n# hand-edited\n" and "up to today's text" in caplog.text
    assert [d["launcher"] for d in audit()] == [hashlib.sha256(written).hexdigest()[:16]]   # once, the launcher it wrote
    assert be._heal_launchers() == [] and len(audit()) == 1


def test_a_launcher_appkatas_start_wrote_and_couldnt_put_back_is_audited_as_it_runs(be, tmp_path, monkeypatch, caplog):
    # #689's review, P7-1: AppKata's start rewrites a hand-edited launcher; the launcher is written,
    # the menu entry's write fails (a full disk), and putting the launcher back fails too. The start
    # skipped every failed rewrite (P6-1), this one included: today's launcher was left in place,
    # the one that runs, with no Audit entry, and the next start found it current, so no start ever
    # audited it, though R17.4 has the Audit record a hash each time AppKata writes a launcher.
    import hashlib
    import logging
    from appkata_core import install
    _review(be, "online-app")
    _tarball_install(be, tmp_path)
    monkeypatch.setattr(sb, "have_tools", lambda: True)
    monkeypatch.setattr(sb, "support_status", lambda: {"status": "ok"})
    be._regenerate_launcher(URL)
    be._pin_sandbox(URL, be._resolved_sandbox(URL))
    launcher = json.loads(be.db.one("SELECT record FROM installs WHERE url=?", (URL,))["record"])["launcher"]
    with open(launcher, "wb") as f:
        f.write(b"#!/bin/sh\n# hand-edited\n")                            # not today's text: the start rewrites it
    audit = lambda: [json.loads(r["detail"]) for r in be.db.all(                               # noqa: E731
        "SELECT detail FROM audit WHERE action='rewrote the launcher of' ORDER BY id")]
    caplog.set_level(logging.INFO, logger="appkata.gui")
    real = os.replace

    def full(*a, **k):
        raise OSError(28, "No space left on device")

    def no_put_back(src, dst, *a, **k):
        if dst == launcher and str(src).endswith(".was"):
            raise OSError(28, "No space left on device")
        return real(src, dst, *a, **k)
    with monkeypatch.context() as m:
        m.setattr(install, "_desktop_entry", full)
        m.setattr(install.os, "replace", no_put_back)
        assert be._heal_launchers() == [URL]                                # its launcher was rewritten
    with open(launcher, "rb") as f:
        written = f.read()
    assert written != b"#!/bin/sh\n# hand-edited\n" and not [n for n in os.listdir(os.path.dirname(launcher)) if n.endswith(".was")]
    assert [d["launcher"] for d in audit()] == [hashlib.sha256(written).hexdigest()[:16]]   # the launcher that runs
    assert "not put back: its launcher" in caplog.text and "couldn't be put back: it runs as written" in caplog.text
    assert be._heal_launchers() == [] and len(audit()) == 1                 # the next start finds it current


def test_appkatas_own_launcher_the_start_cant_remove_is_left_and_not_said_removed(be, tmp_path, monkeypatch, caplog):
    # #689's review, P7-1 (the second read's P7-T2): AppKata's start removes the launcher an older
    # AppKata gave AppKata itself (R17.1). Where that can't be written (here its record can't be
    # stored), it is put back, and the start neither says AppKata runs unsandboxed again nor returns
    # it as done; the next start removes it. No test failed with the start saying so whatever
    # happened.
    import logging
    from appkata_core import APPKATA_REPO, install
    monkeypatch.setattr(sb, "have_tools", lambda: True)
    monkeypatch.setattr(sb, "support_status", lambda: {"status": "ok"})
    image = tmp_path / "Downloads" / "AppKata-x86_64.AppImage"
    image.parent.mkdir()
    image.write_text("#!/bin/sh\n")
    image.chmod(0o755)
    monkeypatch.setenv("APPIMAGE", str(image))
    be._ensure_self()
    be._app = lambda url: {"url": url, "name": "AppKata", "installed": "9.9"} if url == APPKATA_REPO else None
    rec = lambda: json.loads(be.db.one("SELECT record FROM installs WHERE url=?", (APPKATA_REPO,))["record"])  # noqa: E731
    install.rewrite_launcher(be.db, {"url": APPKATA_REPO, "name": "AppKata", "sandbox": sb.resolve_template("strict")},
                             be._app_options(APPKATA_REPO))                 # what an older AppKata left behind
    left = rec()["launcher"]
    with open(left, "rb") as f:
        text = f.read()
    caplog.set_level(logging.INFO, logger="appkata.gui")
    real, failed = be.db.x, []

    def store(sql, *a, **k):
        if sql.startswith("UPDATE installs") and not failed:
            failed.append(sql)
            raise OSError(28, "No space left on device")
        return real(sql, *a, **k)
    with monkeypatch.context() as m:
        m.setattr(be.db, "x", store)
        assert be._heal_launchers() == []                                   # not done
    assert failed and rec()["launcher"] == left and rec()["exec"] == left
    with open(left, "rb") as f:
        assert f.read() == text                                             # put back, as it was
    assert "couldn't regenerate the launcher for" in caplog.text and "runs unsandboxed again" not in caplog.text
    assert be._heal_launchers() == [APPKATA_REPO]                           # the next start removes it
    assert not rec().get("launcher") and not os.path.exists(left) and "runs unsandboxed again" in caplog.text


def test_appkatas_start_removes_what_a_stopped_change_left_beside_an_apps_files(be, tmp_path, monkeypatch):
    # #689's review, P6-B2: a sandbox change keeps the files it replaces as hard links beside them
    # (<path>.<pid>.was) and drops them once it is written or put back. A process stopped between
    # the two (killed, the power gone) left them, as a write stopped part-way leaves
    # <path>.<pid>.tmp, and only the app's next sandbox change removed the .was. AppKata's start
    # removes both now, for every app it installed, and nothing else.
    import re
    from appkata_core import install
    _review(be, "online-app")
    _tarball_install(be, tmp_path)
    monkeypatch.setattr(sb, "have_tools", lambda: True)
    monkeypatch.setattr(sb, "support_status", lambda: {"status": "ok"})
    monkeypatch.setattr(sb, "userns_works", lambda refresh=False: True)
    be._regenerate_launcher(URL)
    be._pin_sandbox(URL, be._resolved_sandbox(URL))
    with monkeypatch.context() as m:
        m.setattr(install, "_drop_aside", lambda kept: None)                # stopped before it dropped what it kept
        assert be._regenerate_launcher(URL) is None
    rec = json.loads(be.db.one("SELECT record FROM installs WHERE url=?", (URL,))["record"])
    files = [rec["launcher"], sb.identity_path("demo"), sb.home_owner_path("demo")] + rec["files"][1:]
    assert len(files) == 5 and all(os.path.isfile(f) for f in files), files    # its launcher, marker, owner, menu script and entry
    for f in files:
        open(f"{f}.4242.tmp", "w").close()                                  # a write another process didn't finish
        open(f"{f}.mine", "w").close()                                      # and a file that isn't AppKata's
    beside = lambda: sorted(os.path.join(d, n) for d, _, names in os.walk(tmp_path) for n in names      # noqa: E731
                            if re.search(r"\.[0-9]+\.(was|tmp)$", n))
    assert len(beside()) == 10, beside()
    be._heal_launchers_at_startup()
    assert beside() == [] and all(os.path.isfile(f) and os.path.isfile(f + ".mine") for f in files)


def test_appkatas_start_removes_what_a_stopped_write_left_beside_the_launchers_shared_files_and_logs_what_it_removed(be, tmp_path, monkeypatch, caplog):
    # #689's review, P7-B2 and P7-B1b, the owner's decisions (option A each). Every launcher write
    # writes the files all the sandboxed apps' launchers share -- the seccomp filter, the
    # file-argument helper and the xdg-open shim -- through <path>.<pid>.tmp, and no sweep reached
    # what a stopped write left beside them. And AppKata's start removed what it found beside an
    # app's files and said nothing of it, though it logs each launcher and command link it changes.
    # The start removes the shared files' leftovers too (a .tmp only: nothing keeps them aside, so a
    # .was beside them isn't AppKata's), and the App log has one line for each app whose files it
    # removed something beside, naming what, and one for the shared files (R17.4).
    import logging
    from appkata_core import install
    _review(be, "online-app")
    _tarball_install(be, tmp_path)
    monkeypatch.setattr(sb, "have_tools", lambda: True)
    monkeypatch.setattr(sb, "support_status", lambda: {"status": "ok"})
    monkeypatch.setattr(sb, "userns_works", lambda refresh=False: True)
    be._regenerate_launcher(URL)
    rec = json.loads(be.db.one("SELECT record FROM installs WHERE url=?", (URL,))["record"])
    shared = [p for p in (sb.seccomp_path(), sb.forward_path(), os.path.join(sb.shims_dir(), "xdg-open")) if os.path.isfile(p)]
    assert shared[-2:] == [sb.forward_path(), os.path.join(sb.shims_dir(), "xdg-open")], shared
    apps = [f"{rec['launcher']}.4241.was", f"{sb.identity_path('demo')}.4242.tmp"]          # beside Demo's own files
    stopped = [f"{p}.4242.tmp" for p in shared]                                            # and beside the shared ones
    kept = [f"{p}.4242.was" for p in shared] + [f"{p}.abc.tmp" for p in shared] + [f"{shared[0]}.4242.tmp.d", f"{shared[0]}.mine"]
    for f in apps + stopped + kept:
        open(f, "w").close()
    os.mkdir(f"{shared[-1]}.77.tmp")                                                       # a folder of the shape
    kept.append(f"{shared[-1]}.77.tmp")
    caplog.set_level(logging.INFO, logger="appkata.install")
    be._heal_launchers_at_startup()
    assert [f for f in apps + stopped if os.path.lexists(f)] == [] and [f for f in kept if not os.path.lexists(f)] == []
    assert all(os.path.isfile(p) for p in shared)
    said = [r.getMessage() for r in caplog.records if r.name == "appkata.install" and r.getMessage().startswith("removed")]
    assert said == ["removed what a stopped change or write left beside the files of Demo: " + ", ".join(apps),
                    "removed what a stopped write left beside the files every sandboxed app's launcher uses: " + ", ".join(stopped)], said
    caplog.clear()
    be._heal_launchers_at_startup()                                                        # nothing left: nothing said
    assert [r for r in caplog.records if r.getMessage().startswith("removed")] == []
    assert install.sweep_left_beside(be.db) == []


def test_a_launcher_whose_paths_arent_utf8_is_shown_and_hashed_as_it_is_written(be, tmp_path, monkeypatch):
    # #689's review, P4-1: a launcher holds its paths as their own bytes, UTF-8 or not (an install
    # folder named in Latin-1 on a UTF-8 system), where it was written as text and such a folder
    # stopped the install. "Show the launch command" and the Audit's hash of it read it back as
    # UTF-8 text, which such a launcher isn't: App Detail and the change's audit row stopped with
    # Python's decoding error. The command is shown with the byte as the replacement character,
    # and the hash is of the bytes written, as it always was of a UTF-8 launcher's.
    import hashlib
    _review(be, "online-app")
    target = _tarball_install(be, tmp_path / os.fsdecode(b"\xe9t\xe9"))
    rec = json.loads(be.db.one("SELECT record FROM installs WHERE url=?", (URL,))["record"])
    be.db.x("UPDATE installs SET record=? WHERE url=?", (json.dumps({**rec, "root": os.path.dirname(target)}), URL))
    monkeypatch.setattr(sb, "have_tools", lambda: True)
    monkeypatch.setattr(sb, "support_status", lambda: {"status": "ok"})
    be._regenerate_launcher(URL)
    rec = json.loads(be.db.one("SELECT record FROM installs WHERE url=?", (URL,))["record"])
    with open(rec["launcher"], "rb") as f:
        data = f.read()
    assert rec["launcher"] == os.path.join(target, "run") and os.fsencode(target) in data
    assert be.sandboxLaunchCommand(URL) == data.decode("utf-8", "replace") and "�t�" in be.sandboxLaunchCommand(URL)
    assert be.sandboxInfo(URL)["launcherHash"] == hashlib.sha256(data).hexdigest()[:16]
    assert be._heal_launchers() == []                                     # AppKata's start finds it up to date
    be.setSandbox(URL, {"template": "strict", "overrides": {}})
    row = be.db.one("SELECT action, detail FROM audit ORDER BY id DESC LIMIT 1")
    with open(rec["launcher"], "rb") as f:
        assert row["action"] == "set the sandbox of" and hashlib.sha256(f.read()).hexdigest()[:16] in row["detail"]


def test_follow_reviewers_off_uses_the_users_default_and_never_badges(be, monkeypatch):
    # Round two, R6 (17.15): with "Follow reviewers' suggestions" off, the reviews' Sandbox lines were
    # dropped but the reviewed baseline (standard) still applied instead of the user's own default,
    # and the app was badged — and "Use theirs" offered — for a suggestion the user asked not to
    # follow. Decided: off takes reviews out of sandboxing; the dialog still shows the suggestion.
    monkeypatch.setattr(be, "_app", lambda url: {"url": URL, "name": "Demo", "installed": "1.0"})
    _review(be, "online-app")
    be.setPref("sandboxGuiDefault", "strict")
    assert be._resolved_sandbox(URL, kind="appimage")["source"] == "reviews"
    be.setPref("followReviewerSandbox", False)
    r = be._resolved_sandbox(URL, kind="appimage")
    assert r["source"] == "default" and r["template"] == "strict" and r["grants"]["network"] is False
    _installed(be)
    be._pin_sandbox(URL, r)
    info = be.sandboxInfo(URL)
    assert info["reviewBadge"] is False and info["level"] == "strict"
    assert info["hasSuggestion"] is True and info["reviewBy"] == "Alice"     # shown, not applied
    be.setPref("followReviewerSandbox", True)
    assert be.sandboxInfo(URL)["reviewBadge"] is True                       # pinned to strict, reviews differ


def test_a_review_cannot_grant_a_secret_folder_and_the_summary_says_so(be):
    # Review 2, F8: a review's `Sandbox folders` could grant ~/.aws, Firefox's profiles, every Flatpak
    # app's data. Such a folder is refused when it comes from a review; the summary shows why.
    _review_lines(be, "- Sandbox (linux): online-app\n- Sandbox folders (linux): ~/.aws:ro, ~/Documents\n")
    r = be._resolved_sandbox(URL, kind="appimage")
    assert "~/.aws" not in r["grants"]["folders"] and "~/Documents" in r["grants"]["folders"]
    be._app = lambda url: {"url": URL, "name": "Demo", "installed": ""}
    chips = [c[0] for c in be.sandboxInfo(URL)["chips"]]
    assert any(c.startswith("~/.aws · refused") for c in chips) and "~/Documents" in chips
    be._pin_sandbox(URL, r)
    _installed(be)
    assert "~/.aws" not in be._resolved_sandbox(URL)["grants"]["folders"]          # nor is it pinned


def test_the_users_own_secret_folder_stands_with_a_warning(be):
    gs = sb.apply_overrides(sb.resolve_template("standard"), {"folders": {"+~/.aws": "ro"}})
    be._app = lambda url: {"url": URL, "name": "Demo", "installed": ""}
    be.setSandbox(URL, {"custom": sb.to_json(gs)})
    assert "~/.aws" in be._resolved_sandbox(URL)["grants"]["folders"]
    assert any(c[0].startswith("~/.aws") and c[2] == "warn" for c in be.sandboxInfo(URL)["chips"])


def test_a_review_saying_off_needs_the_users_click(be):
    # Review 2, F8: one Trust's `Sandbox: off` ran a fresh install unsandboxed. Now the reviewed
    # baseline applies, the dialogs offer "Use theirs", and adopting it is the user's own choice.
    _review(be, "off")
    r = be._resolved_sandbox(URL, kind="appimage")
    assert r["grants"]["level"] == "standard" and r["source"] == "default"
    be._app = lambda url: {"url": URL, "name": "Demo", "installed": "1.0"}
    _installed(be)
    be._pin_sandbox(URL, r)
    info = be.sandboxInfo(URL)
    assert info["hasSuggestion"] and info["suggestsOff"] and "No sandbox" in [c[0] for c in info["reviewSuggests"]]
    be.useSuggestion(URL)
    assert be._install_settings(URL)["sandbox"] == {"template": "off"}
    assert be._resolved_sandbox(URL)["grants"]["level"] == "off" and not be.sandboxInfo(URL)["hasSuggestion"]


def test_use_theirs_for_an_ordinary_suggestion_still_adopts_the_reviews(be):
    _review(be, "online-app")
    be._app = lambda url: {"url": URL, "name": "Demo", "installed": "1.0"}
    _installed(be)
    be._pin_sandbox(URL, {"grants": sb.to_json(sb.resolve_template("strict")), "template": "strict"})
    be.useSuggestion(URL)
    r = be._resolved_sandbox(URL)
    assert "sandbox" not in be._install_settings(URL) and r["grants"]["network"] is True


def test_a_self_updating_app_is_updated_by_appkata_while_it_runs_sandboxed(be, tmp_path, monkeypatch):
    # Review 2, F3 (owner's decision): an app marked "updates itself" (R4.10) can't while sandboxed --
    # its folder, and an AppImage's own file, are read-only -- and AppKata didn't either, so it stayed
    # on its installed version unseen. While it runs sandboxed (it has a launcher) AppKata updates it.
    from appkata_core import catalog
    rel = [{"version": "2.0", "date": "2026-09-01T00:00:00Z", "assets": [{"name": "demo.tar.gz", "url": "u", "size": 1}]},
           {"version": "1.0", "date": "2026-08-01T00:00:00Z", "assets": [{"name": "demo.tar.gz", "url": "u", "size": 1}]}]
    be.db.x("INSERT OR REPLACE INTO sources(url, settings, added_at) VALUES(?,?,?)", (URL, "{}", now()))
    be.db.x("INSERT OR REPLACE INTO apps(url, name, releases) VALUES(?,?,?)", (URL, "Demo", json.dumps(rel)))
    be._set_install_settings(URL, {"autoUpdate": True})
    target = _tarball_install(be, tmp_path)
    app = lambda: next(a for a in catalog.build(be.db, "linux", "x86_64") if a["url"] == URL)     # noqa: E731
    assert app()["state"] == "selfupdating" and not app()["sandboxedUpdates"]        # runs Off: it updates itself
    rec = json.loads(be.db.one("SELECT record FROM installs WHERE url=?", (URL,))["record"])
    rec["launcher"] = os.path.join(target, "run")
    be.db.x("UPDATE installs SET record=? WHERE url=?", (json.dumps(rec), URL))
    assert app()["state"] == "selfupdating"         # a launcher named, its file gone: it runs Off (R3-27)
    with open(rec["launcher"], "w") as f:
        f.write("#!/bin/sh\n")
    a = app()
    assert a["state"] == "update" and a["updateTo"] == "2.0" and a["sandboxedUpdates"] and a["autoUpdate"]
    assert be._updates_itself(a, sb.to_json(sb.resolve_template("online-app"))) is False      # installed versioned
    assert be._updates_itself(a, None) is True                                                  # Off: as before
    assert be._updates_itself(a, sb.to_json(sb.resolve_template("off"))) is True


def test_an_apps_kind_is_the_users_word_then_the_downloads_then_an_app(be, tmp_path):
    # Review 2, F4: the kind was "a command link and no app-menu entry"; now the user's choice in
    # Install options, else what install() read from the download (appKind), else an app.
    from appkata.backend import Backend
    is_cli = lambda: Backend._is_cli(be, URL)                                   # noqa: E731  (the fixture stubs it)
    assert is_cli() is False
    _tarball_install(be, tmp_path)
    be._set_install_settings(URL, {"appMenu": False, "commandLink": True})     # the old rule's shape: no longer the test
    assert is_cli() is False
    rec = json.loads(be.db.one("SELECT record FROM installs WHERE url=?", (URL,))["record"])
    be.db.x("UPDATE installs SET record=? WHERE url=?", (json.dumps({**rec, "appKind": "cli"}), URL))
    assert is_cli() is True
    be._set_install_settings(URL, {"cliKind": "gui"})
    assert is_cli() is False
    be._set_install_settings(URL, {"cliKind": "cli"})
    be._is_cli = lambda url, eff=None: Backend._is_cli(be, url)
    assert be._resolved_sandbox(URL, kind="tarball")["template"] == "cli-tool"    # unreviewed tool: cli-tool, not Strict


def test_saving_a_review_writes_the_users_own_sandbox_whole_and_only_when_included(be, tmp_path, monkeypatch):
    # Review 2, F9: a review could carry three sandbox lines, and AppKata never wrote even those; the
    # user's sandbox choice stayed out of their review. Saving writes it now, read back by the
    # reader's AppKata as the user runs it; a review can't carry the secrets class, so that's left out
    # and said; unchecking "Include my sandbox" writes nothing of it; a rewrite drops stale lines.
    from appkata_core import sync
    path = tmp_path / "AppKata.md"
    path.write_text("# My Trust\n")
    be._prefs["reviewPath"] = str(path)
    monkeypatch.setattr(be, "_app", lambda url: {"url": URL, "name": "Demo", "installed": ""})
    monkeypatch.setattr(threading.Thread, "start", lambda t: t.run())
    monkeypatch.setattr(sync, "sync_own", lambda *a, **k: None)
    monkeypatch.setattr(sync, "own_trust", lambda *a, **k: None)
    assert be.reviewData(URL)["sandboxSettings"] is None                  # nothing of the user's: nothing written
    gs = sb.apply_overrides(sb.resolve_template("offline-editor"),
                            {"folders": {"+~/Notes": "rw", "+~/.mozilla/firefox": "ro"}, "devices": ["camera", "x11"],
                             "caps": ["tray", "secrets"], "write_app": True})
    be.setSandbox(URL, {"template": "offline-editor", "custom": sb.to_json(gs)})
    rd = be.reviewData(URL)
    assert rd["sandboxLine"] == ("Offline editor, with ~/Notes (read-write), the camera, a tray icon and changing its own files")
    assert [x[0] for x in rd["sandboxRefused"]] == ["~/.mozilla/firefox", "Saved passwords"]
    be.saveReview(URL, [], 4, None, "", False, False, "", False, True)
    text = path.read_text()
    assert "- Sandbox (linux): offline-editor" in text and "- Sandbox folders (linux): +~/Notes" in text
    assert "- Sandbox devices (linux): +camera" in text and "- Sandbox services (linux): +tray" in text
    assert "- Sandbox app folder (linux): yes" in text and "firefox" not in text and "passwords" not in text
    be.setSandbox(URL, {"template": "online-app", "overrides": {}})        # a plain template: the other lines go
    be.saveReview(URL, [], 4, None, "", False, False, "", False, True)
    text = path.read_text()
    assert "- Sandbox (linux): online-app" in text and "Sandbox folders" not in text and "Sandbox app folder" not in text
    be.setSandbox(URL, {"template": "strict", "overrides": {}})
    be.saveReview(URL, [], 4, None, "", False, False, "", False, False)    # "Include my sandbox" off
    assert "- Sandbox (linux): online-app" in path.read_text()


def test_the_review_lines_round_trip_through_the_file():
    # every kind of line AppKata writes reads back the same; unknown words drop out, a line of none drops
    opts = {"sandbox": "messenger", "sandboxFolders": "+~/Chats:ro, -$cwd", "sandboxNetwork": False,
            "sandboxSound": "-record", "sandboxDevices": "-camera, +x11", "sandboxServices": "+media-keys, -tray",
            "sandboxAppFolder": True}
    text = trustfile.format_settings("Demo", {"platforms": {"LINUX": opts}}, ["- Trust: 4"])
    parsed, warns = trustfile.parse_section("Demo", text + "\n")
    assert trustfile.resolve_settings(parsed["opts"], "linux") == opts and warns == []
    parsed, _ = trustfile.parse_section("Demo", "## Demo::Settings\n\n- Sandbox services: +tray, +bogus, -nope\n- Sandbox sound: bogus\n")
    assert parsed["opts"] == {"sandboxServices": "+tray"}
    merged = trustfile.merge_settings({"platforms": {"LINUX": {"sandbox": "strict", "sandboxFolders": "+~/X"}}},
                                      {"sandbox": "standard", "sandboxFolders": None}, "linux")
    assert merged == {"platforms": {"LINUX": {"sandbox": "standard"}}}
    for key, words in trustfile.SANDBOX_SETS.items():        # the file's words are the sandbox's
        assert words == set(sb.LINE_NAMES[{"sandboxSound": "sound", "sandboxDevices": "devices", "sandboxServices": "caps"}[key]])
