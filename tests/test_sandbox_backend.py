"""App sandboxing (requirement 17): the backend glue — which grant set applies to an app, and when."""

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
    monkeypatch.setenv("HOME", str(tmp_path))
    for v in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME"):
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from appkata.backend import Backend
    b = Backend(db_path=str(tmp_path / "appkata.db"))
    b.db.x("INSERT INTO trusts(url, name, enabled, score) VALUES(?,?,1,3)", ("https://example.org/trust", "Alice"))
    b._is_cli = lambda url, eff=None: False
    b._sandbox_kind = lambda url: "appimage"
    return b


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
    # Regression (decision 5, 17.11): with no choice saved by the user, every update re-resolved the
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
    # Regression (17.10): an app installed while AppArmor setup was pending (or bwrap was missing) ran
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
    # Review 2, F12: 17.10's "offers a one-time setup on first need ... if declined" was never built;
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
    # fresh install on such a host still runs Off, as before (17.10).
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
    # happened to update the app or touch its sandbox. The launcher is the enforcement (17.4), so
    # the pass now compares each one with what AppKata would write today and rewrites it if they
    # differ; a hand-edited launcher (17.4: "do not edit") is restored the same way.
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
    # setSandbox never touches an app installed outside AppKata (4.5); the startup healing pass did.
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
    # as installed (2.11), and nothing kept that install out of sandboxing. The heal pass gave it a
    # Strict launcher with no network, and its menu entry, command link, autostart and appkata://
    # links then started it where it could neither sync nor install (17.1).
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
    # Review 3, R3-8 (17.9): Settings > Sandbox says it for the session; App Detail only for an app the
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
    # 17.1: Linux only, and only the two portable kinds AppKata installs itself. A .deb's or .rpm's
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
    # card went untested -- the unpacking cost (17.7), the card for each kind (review 2, F4) and a
    # review's Off offered, never applied (F8). Here planFor computes it, against App Detail's view.
    monkeypatch.setattr(sb, "have_tools", lambda: True)
    monkeypatch.setattr(sb, "support_status", lambda: {"status": "ok"})
    img = "Demo-1.0-x86_64.AppImage"
    card = _plan_with(be, monkeypatch, [img])["sandbox"]
    info = be.sandboxInfo(URL)
    assert card["applicable"] and card["appImage"] and card["suggestsOff"] is False
    assert (card["template"], card["level"], card["chips"]) == (info["template"], info["level"], info["chips"])
    assert card["extractMb"] == 250                                    # 2.5 x the AppImage (17.7)
    assert card["byKind"]["gui"]["template"] == "strict" and card["byKind"]["cli"]["template"] == "cli-tool"   # 17.3.3
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


def test_resaving_install_options_keeps_the_pin_the_seen_marker_and_the_users_choice(be, monkeypatch):
    # Regression (decision 5, 17.11): installWith rewrote app_settings.install from the dialog's fields
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
    # Regression (17.11): the install dialog's Sandbox card says "suggested by <reviewer>" beside the
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
    # Review 2, F3 (owner's decision): an app marked "updates itself" (4.10) can't while sandboxed --
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
