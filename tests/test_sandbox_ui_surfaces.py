"""App Detail, Settings > Sandbox and the uninstall confirmation, driven as QML against a real Backend
(review 3, R3-2).

Round four's dialog contract harness drove the Sandbox and Install dialogs. The three places where
requirement 17 tells the user most were driven by no test: App Detail (the review badge and "Keep
mine", the setup-needed and Repair banners, the Sandboxed/Not sandboxed pill, the session and bus
caveats, the Chromium line, the sandboxed-updates line), Settings > Sandbox (System support with Set
up... and Repair..., the defaults, the templates, the home folders) and the uninstall dialog's offer
to delete the sandbox home. Here the real QML loads an app the catalog really has, each state is
made in the backend, and what the user would see -- every visible text, every visible button -- is
read back; pressing a button must reach the backend.
"""

import json
import os
import threading

import pytest

pytest.importorskip("PySide6")

from appkata_core import sandbox as sb                                # noqa: E402
from appkata_core.db import now                                      # noqa: E402
from test_dialog_contract import _call, qapp                         # noqa: E402,F401
from test_sandbox_backend import URL, _review, _tarball_install, be  # noqa: E402,F401

HARNESS = os.path.join(os.path.dirname(__file__), "qml", "SurfacesHarness.qml")

# What these surfaces still don't say, and the finding that keeps each
STILL_MISSING: dict = {}


@pytest.fixture
def app(be, tmp_path, monkeypatch):
    """The Demo tarball app, in the catalog for real (a Source, a release, an install), on a host
    whose sandbox support each test sets."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / ".local" / "share"))
    for v in ("WAYLAND_DISPLAY", "DISPLAY", "DBUS_SESSION_BUS_ADDRESS"):
        monkeypatch.delenv(v, raising=False)
    be.db.x("INSERT INTO sources(url, settings, added_at) VALUES(?,?,?)", (URL, "{}", now()))
    be.db.x("INSERT INTO apps(url, name, releases) VALUES(?,?,?)", (URL, "Demo", json.dumps(        # as sync stores a release
        [{"tag": "v1.0", "name": "1.0", "version": "1.0", "date": "2026-01-01T00:00:00Z", "prerelease": False, "notes": "",
          "html_url": URL + "/releases/v1.0", "assets": [{"name": "demo-1.0-linux-x86_64.tar.gz", "url": "u", "size": 1,
                                                         "digest": "", "content_type": ""}]}])))
    _tarball_install(be, tmp_path)
    del be._app                                                       # the real lookup, through the catalog
    be._sandbox_kind = lambda url: "tarball"
    host = {"status": "ok"}
    monkeypatch.setattr(sb, "have_tools", lambda: host["status"] != "unsupported")
    monkeypatch.setattr(sb, "support_status", lambda: dict(host))
    calls = []
    monkeypatch.setattr(sb, "install_profile", lambda *a, **k: calls.append("setup"))
    monkeypatch.setattr(sb, "remove_profile", lambda *a, **k: calls.append("repair") or True)
    monkeypatch.setattr(threading.Thread, "start", lambda self: self.run())          # the workers, in line
    be.reload()
    return host, calls


@pytest.fixture
def ui(qapp, be, app):
    from PySide6.QtCore import QUrl
    from PySide6.QtQml import QQmlApplicationEngine
    engine = QQmlApplicationEngine()
    for name, value in (("backend", be), ("appVersion", "test"), ("themeOverride", ""), ("tourMode", False), ("platformOs", "linux")):
        engine.rootContext().setContextProperty(name, value)
    engine.load(QUrl.fromLocalFile(HARNESS))
    assert engine.rootObjects(), "the surfaces harness did not load"
    root = engine.rootObjects()[0]
    yield root
    from PySide6.QtCore import QCoreApplication, QEvent
    root.deleteLater()
    engine.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def _part(ui, name):
    from PySide6.QtCore import QObject
    return ui.findChild(QObject, name)


def _items(item):
    """Every object under `item`: its Qt children, and the visual tree, where a Repeater's items live.
    A Repeater's items have no QObject parent, and PySide wraps an object as the type it first met it
    by, so a Flow first reached as a QObject offers no childItems(): its Repeater is asked for them
    (itemAt) as well, else what it made could go unseen depending on what a test touched first."""
    from PySide6.QtCore import Q_ARG, Q_RETURN_ARG, QMetaObject, QObject, Qt
    from PySide6.QtQuick import QQuickItem
    seen, todo = {}, list(item.findChildren(QObject))
    while todo:
        o = todo.pop()
        if id(o) in seen:
            continue
        seen[id(o)] = o
        if isinstance(o, QQuickItem):
            todo += o.childItems()
        if o.metaObject().className() == "QQuickRepeater":
            todo += [QMetaObject.invokeMethod(o, "itemAt", Qt.ConnectionType.DirectConnection, Q_RETURN_ARG("QQuickItem*"),
                                              Q_ARG(int, i)) for i in range(o.property("count") or 0)]
    return [o for o in seen.values() if o is not None]


def _seen(item) -> list[str]:
    """Every text the user can see in `item`: Text, Pill, button and check-box labels that are visible."""
    out = []
    for o in _items(item):
        t = o.property("text")
        if isinstance(t, str) and t.strip() and o.property("visible") is True:
            out.append(t)
    return out


def _press(item, text):
    btn = next((o for o in _items(item) if o.metaObject().className().startswith("FButton")
                and o.property("text") == text and o.property("visible") is True), None)
    assert btn is not None, f"no visible button {text!r} in {sorted(set(_seen(item)))}"
    btn.clicked.emit()


def _show(ui, be):
    """App Detail for the app, as the backend now has it."""
    be.reload()
    detail = _part(ui, "detail")
    detail.setProperty("url", "")
    detail.setProperty("url", URL)
    return detail


def _has(texts, *words):
    return [w for w in words if not any(w in t for t in texts)]


# ------------------------------------------------------------------- App Detail

def test_app_detail_says_sandboxed_or_not_and_what_the_sandbox_gives(ui, be, app):
    host, calls = app
    be._regenerate_launcher(URL)                                      # sandboxed, as the default for its kind
    seen = _seen(_show(ui, be))
    assert not _has(seen, "Sandboxed", "Sandbox", "Strict · private home", "No network"), seen
    assert "Not sandboxed" not in seen and not any("system setup needed" in t for t in seen)
    os.unlink(json.loads(be.db.one("SELECT record FROM installs WHERE url=?", (URL,))["record"])["launcher"])
    host["status"] = "unsupported"                                    # installed while the system couldn't (17.10)
    _tools(host, ["bubblewrap"])
    seen = _seen(_show(ui, be))
    assert not _has(seen, "Not sandboxed", "Running unsandboxed: bubblewrap isn't installed. Install it (sudo "), seen
    assert not any("xdg-dbus-proxy" in t for t in seen), seen         # review 2, F12: it named both, whatever was missing


def _tools(host, missing):
    """The host lacks these packages, as support_status() would report it."""
    hints = sb.tools_hints(missing)
    host.update(missing=list(missing), busFilter="xdg-dbus-proxy" not in missing,
                toolsHint=hints["system"], appToolsHint=hints["app"], brokenHint=hints["broken"])


def test_app_detail_says_a_standard_app_runs_without_desktop_services_where_the_proxy_is_missing(ui, be, app):
    # Review 2, F12: with bwrap alone a Standard app runs sandboxed with no session bus, and says so
    host, _ = app
    _tools(host, ["xdg-dbus-proxy"])
    be.setSandbox(URL, {"template": "online-app", "overrides": {}})
    seen = _seen(_show(ui, be))
    assert not _has(seen, "Sandboxed", "Runs without desktop services: xdg-dbus-proxy isn't installed, so it can't notify"), seen
    be.setSandbox(URL, {"template": "strict", "overrides": {}})        # Strict has no bus to miss
    seen = _seen(_show(ui, be))
    assert _has(seen, "Runs without desktop services") and not _has(seen, "Sandboxed"), seen


@pytest.mark.parametrize("status,banner,button,call", [
    ("setup-needed", "Not sandboxed — system setup needed", "Enable…", "setup"),
    ("conflict", "Not sandboxed — AppArmor needs a repair", "Repair…", "repair"),
])
def test_app_detail_offers_the_system_setup_or_repair_and_reaches_it(ui, be, app, status, banner, button, call):
    host, calls = app
    host["status"] = status
    detail = _show(ui, be)
    assert not _has(_seen(detail), banner, button), _seen(detail)
    _press(detail, button)
    assert calls == [call]


@pytest.mark.parametrize("status,missing,title,says", [
    ("setup-needed", [], "Can't start — system setup needed", "Until then it can't start; set its sandbox to Off"),
    ("conflict", [], "Can't start — AppArmor needs a repair", "Until then it can't start; set its sandbox to Off"),
    ("unsupported", ["bubblewrap"], None, "Can't start: bubblewrap isn't installed, and it runs sandboxed. Install it (sudo "),
])
def test_app_detail_says_an_app_that_keeps_its_launcher_on_a_broken_host_cant_start(ui, be, app, status, missing, title, says):
    # Review 2, F16: such an app keeps its launcher rather than run unsandboxed unasked, so App Detail
    # mustn't call it "Not sandboxed" or say it "runs unsandboxed"
    host, _ = app
    be._regenerate_launcher(URL)
    host["status"] = status
    _tools(host, missing)
    seen = _seen(_show(ui, be))
    assert not _has(seen, "Sandboxed", says, *([title] if title else [])), seen
    assert not any("Not sandboxed" in t or "runs unsandboxed." in t or t.startswith("Running unsandboxed") for t in seen), seen


def test_app_detail_raises_the_review_badge_and_keep_mine_puts_it_down(ui, be, app):
    _review(be, "offline-editor")
    be._pin_sandbox(URL, be._resolved_sandbox(URL))
    _review(be, "online-app")                                         # the reviewers now suggest more (17.11)
    detail = _show(ui, be)
    assert not _has(_seen(detail), "Reviewers suggest a sandbox change", "Keep mine", "Review…",
                    "Alice suggests adding the network, sound and notifications. Until you review it, the app may not work fully."), _seen(detail)
    _press(detail, "Keep mine")
    assert not be.sandboxInfo(URL)["reviewBadge"]
    assert "Reviewers suggest a sandbox change" not in _seen(_show(ui, be))


def test_app_detail_shows_the_session_and_bus_caveats_the_backend_has(ui, be, app, monkeypatch):
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", "unix:abstract=/tmp/dbus-AbCdEf,guid=0")
    be.setSandbox(URL, {"template": "online-app", "overrides": {}})
    seen = _seen(_show(ui, be))
    assert not _has(seen, sb.session_warning()["text"][:60], sb.bus_warning()["text"][:60]), seen
    be.setSandbox(URL, {"template": "offline-editor", "overrides": {}})              # no network: no bus caveat
    seen = _seen(_show(ui, be))
    assert _has(seen, sb.bus_warning()["text"][:60]) and not _has(seen, sb.session_warning()["text"][:60])


def test_app_detail_says_a_chromium_app_runs_without_its_own_sandbox_where_it_must(ui, be, app):
    host, _ = app
    rec = json.loads(be.db.one("SELECT record FROM installs WHERE url=?", (URL,))["record"])
    open(os.path.join(rec["current"]["path"], "chrome-sandbox"), "w").close()
    host.update(status="ok", innerSandbox=False)                     # Ubuntu 25.04+: the system's own bwrap profile
    be._regenerate_launcher(URL)
    assert not _has(_seen(_show(ui, be)), "Runs without its own Chromium sandbox here")
    host["innerSandbox"] = True
    assert _has(_seen(_show(ui, be)), "Runs without its own Chromium sandbox here")


def test_app_detail_says_appkata_updates_a_self_updating_app_while_it_runs_sandboxed(ui, be, app):
    be.db.x("INSERT INTO app_settings(url, install) VALUES(?,?) ON CONFLICT(url) DO UPDATE SET install=excluded.install",
            (URL, json.dumps({"autoUpdate": True})))                  # the user marked it as updating itself
    be._regenerate_launcher(URL)
    assert not _has(_seen(_show(ui, be)), "It would update itself, but it runs sandboxed")


# ------------------------------------------------------------------- Settings > Sandbox

@pytest.mark.parametrize("status,inner,missing,pill,hint,button,call", [
    ("ok", True, [], "Ready", "Ready — the sandbox can run on this system.", None, None),
    ("ok", False, [], "Ready", "Ready, under this system's own AppArmor profile for bubblewrap.", None, None),
    ("ok", True, ["xdg-dbus-proxy"], "Ready", "Ready — the sandbox can run on this system. xdg-dbus-proxy isn't installed, so sandboxed apps get no desktop services", None, None),
    ("setup-needed", None, [], "Not enabled", "This system needs a one-time setup", "Set up…", "setup"),
    ("conflict", None, [], "Needs repair", "AppKata's AppArmor profile, set up before this system was upgraded", "Repair…", "repair"),
    ("unsupported", None, ["bubblewrap"], "Unavailable", "bubblewrap isn't installed, so apps run without a sandbox. Install it (sudo ", None, None),
    ("unsupported", None, ["bubblewrap", "xdg-dbus-proxy"], "Unavailable", "bubblewrap and xdg-dbus-proxy aren't installed, so apps run without a sandbox.", None, None),
])
def test_settings_sandbox_says_the_systems_support_and_reaches_its_setup(ui, be, app, status, inner, missing, pill, hint, button, call):
    host, calls = app
    host.update(status=status, **({"innerSandbox": inner} if inner is not None else {}))
    _tools(host, missing)
    be.prefsChanged.emit()
    dlg = _part(ui, "settings")
    _call(dlg, "open")
    seen = _seen(dlg)
    assert not _has(seen, "System support", pill, hint), seen
    assert ("Set up…" in seen) is (button == "Set up…") and ("Repair…" in seen) is (button == "Repair…")
    if button:
        _press(dlg, button)
        assert calls == [call]
    labels = {sb.TEMPLATE_LABELS[t] for t in sb.TEMPLATE_ORDER}
    assert not _has(seen, *labels), "the built-in templates row"
    assert not _has(seen, "Sandbox home folders", "~/.local/share/appkata/sandboxes"), seen
    _call(dlg, "close")


def test_settings_sandbox_defaults_reach_the_backend(ui, be, app):
    dlg = _part(ui, "settings")
    _call(dlg, "open")
    selects = [o for o in _items(dlg) if o.metaObject().className().startswith("Select") and o.property("visible") is True]
    gui = next(o for o in selects if o.property("label") == "Strict")
    gui.picked.emit("standard")
    assert be._prefs.get("sandboxGuiDefault") == "standard"
    _call(dlg, "close")


# ------------------------------------------------------------------- the uninstall confirmation (17.14)

def _missing_uninstall(ui, be, app):
    out, removed = set(), []
    be._uninstall = lambda url, confirmed, remove_home=False: removed.append(remove_home)
    be._regenerate_launcher(URL)
    dlg = _part(ui, "confirm")
    _call(dlg, "ask", "uninstall", URL)
    box = next((o for o in _items(dlg) if "CheckBox" in o.metaObject().className() and o.property("visible") is True), None)
    assert box is not None and "Also delete its sandbox home folder" in _seen(dlg), _seen(dlg)
    box.setProperty("checked", True)
    box.toggled.emit()
    _press(dlg, "Uninstall")
    assert removed == [True]                                          # the home goes with it, as asked
    be.setSandbox(URL, {"template": "off"})                           # switched Off: its home is kept, orphaned
    os.makedirs(sb.sandbox_home(be._app_id(URL)), exist_ok=True)
    _call(dlg, "ask", "uninstall", URL)
    if "Also delete its sandbox home folder" not in _seen(dlg):
        out.add("uninstall: an app switched Off is offered no deletion of the home it keeps")
        _call(dlg, "close")
        return out
    box = next(o for o in _items(dlg) if "CheckBox" in o.metaObject().className() and o.property("visible") is True)
    box.setProperty("checked", True)
    box.toggled.emit()
    _press(dlg, "Uninstall")
    if removed[-1:] != [True]:                                        # offered, and the answer reaches the uninstall
        out.add("uninstall: an app switched Off is offered no deletion of the home it keeps")
    return out


def test_the_uninstall_dialog_offers_to_delete_the_sandbox_home_but_the_listed(ui, be, app):
    assert _missing_uninstall(ui, be, app) == set(STILL_MISSING)


@pytest.mark.parametrize("button,now", [("Set up now", True), ("Not now", False)])
def test_the_setup_prompt_says_what_it_does_and_its_answers_reach_the_backend(ui, be, app, monkeypatch, button, now):
    # Review 2, F12: the first-need prompt 17.10 promised, as Main shows it from sandboxSetupNeeded
    host, calls = app
    host["status"] = "setup-needed"
    installs = []
    monkeypatch.setattr(be, "_install", lambda *a, **k: installs.append(k.get("asked")))
    dlg = _part(ui, "confirm")
    _call(dlg, "ask", "sandboxSetup", {"url": URL, "name": "Demo", "version": "", "choice": {}})
    seen = _seen(dlg)
    assert not _has(seen, "Set up the sandbox?", "Demo runs in a sandbox, but this system blocks it until a one-time setup",
                    "Not now installs it to run unsandboxed, and AppKata won't ask again", "Set up now", "Not now", "Cancel"), seen
    _press(dlg, button)
    assert installs == [True] and calls == (["setup"] if now else [])
    assert bool(be._prefs.get("sandboxSetupDeclined")) is not now
    if not now:                                                       # Settings says why installs don't ask
        dlg = _part(ui, "settings")
        be.prefsChanged.emit()
        _call(dlg, "open")
        assert _has(_seen(dlg), "You chose Not now at an install, so installs don't ask") == [], _seen(dlg)
        _call(dlg, "close")


def test_every_setup_entry_point_names_the_apps_it_will_sandbox(ui, be, app):
    # Review 2, F13: the setup sandboxed every waiting app, each with an empty home, and said nothing
    # of it beforehand. Settings' Set up..., App Detail's Enable... and the install prompt name them.
    host, _ = app
    host["status"] = "setup-needed"
    note = "Setting it up sandboxes Demo, which runs unsandboxed until then. It starts with fresh settings"
    assert not _has(_seen(_show(ui, be)), "Enable…", note)
    dlg = _part(ui, "settings")
    be.prefsChanged.emit()
    _call(dlg, "open")
    assert not _has(_seen(dlg), "Set up…", note), _seen(dlg)
    _call(dlg, "close")
    asked = []
    be.sandboxSetupNeeded.connect(asked.append)
    other, real = "https://example.org/other", be._app
    be._app = lambda url: {"url": other, "name": "Other", "installed": "", "foreign": False} if url == other else real(url)
    be._install("https://example.org/other", "", {"kind": "tarball"})
    assert asked and asked[0]["waitingNote"].startswith("Setting it up sandboxes Demo")


@pytest.mark.parametrize("include", [True, False])
def test_the_review_dialog_shows_the_sandbox_it_will_write_and_writes_it_only_when_included(ui, be, app, tmp_path, monkeypatch, include):
    # Review 2, F9: the user's own sandbox is written into their review, shown first as one line with
    # "Include my sandbox" (gaps.md 28's one exception: a sandbox can name personal folders)
    from appkata_core import sync
    path = tmp_path / "AppKata.md"
    path.write_text("# My Trust\n")
    be._prefs["reviewPath"] = str(path)
    monkeypatch.setattr(sync, "sync_own", lambda *a, **k: None)
    monkeypatch.setattr(sync, "own_trust", lambda *a, **k: None)
    be.setSandbox(URL, {"template": "offline-editor", "custom": sb.to_json(
        sb.apply_overrides(sb.resolve_template("offline-editor"), {"folders": {"+~/Notes": "rw"}}))})
    dlg = _part(ui, "review")
    _call(dlg, "openFor", URL)
    seen = _seen(dlg)
    assert any("Include my sandbox" in t for t in seen) and "Sandbox: Offline editor, with ~/Notes (read-write)" in seen, seen
    if not include:
        box = _part(dlg, "includeSandbox")
        box.setProperty("checked", False)
        box.toggled.emit()
    _press(dlg, "Save")
    assert ("- Sandbox folders (linux): +~/Notes" in path.read_text()) is include


def test_app_detail_shows_the_launch_command_and_the_audit_records_its_hash(ui, be, app):
    # Review 2, F11: 17.4 said the launcher's text "can be shown in App Detail ('Show the launch command')
    # and is recorded in the Audit"; no QML called sandboxLaunchCommand, and no entry held the text
    be.setSandbox(URL, {"template": "online-app", "overrides": {}})
    detail = _show(ui, be)
    link = _part(detail, "showLaunchCommand")
    assert link is not None and link.property("visible") is True
    text = be.sandboxLaunchCommand(URL)
    dlg = _part(ui, "launchCommand")
    _call(dlg, "openFor", URL)                                        # what the link opens (Main wires it)
    assert _part(dlg, "launchCommand").property("text") == text and text.startswith("#!/bin/sh")
    import hashlib
    h = hashlib.sha256(text.encode()).hexdigest()[:16]
    assert any(h in t for t in _seen(dlg))
    row = be.db.one("SELECT detail FROM audit WHERE action='set the sandbox of' ORDER BY id DESC LIMIT 1")
    assert f'"launcher": "{h}"' in row["detail"] and "Online app" in row["detail"]
    _call(dlg, "close")
    be.setSandbox(URL, {"template": "off"})                            # no launcher: no link
    assert _part(_show(ui, be), "showLaunchCommand").property("visible") is False
