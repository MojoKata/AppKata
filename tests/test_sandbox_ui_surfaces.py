"""App Detail, Settings > Sandbox and the uninstall confirmation, driven as QML against a real Backend
(review 3, R3-2).

Round four's dialog contract harness drove the Sandbox and Install dialogs. The three places where
R17 tells the user most were driven by no test: App Detail (the review badge and "Keep
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
import time

import pytest

pytest.importorskip("PySide6")

from appkata_core import sandbox as sb                                # noqa: E402
from appkata_core.db import now                                      # noqa: E402
from test_dialog_contract import _call, qapp                         # noqa: E402,F401
from test_sandbox_backend import URL, _review, _tarball_install, be  # noqa: E402,F401

HARNESS = os.path.join(os.path.dirname(__file__), "qml", "SurfacesHarness.qml")

# What these surfaces still don't say, and the finding that keeps each
STILL_MISSING: dict = {}
_START = threading.Thread.start        # a worker on its own thread, for a test that needs one (the fixture runs them in line)


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
    host["status"] = "unsupported"                                    # installed while the system couldn't (R17.10)
    _tools(host, ["bubblewrap"])
    seen = _seen(_show(ui, be))
    assert not _has(seen, "Not sandboxed", "Running unsandboxed: bubblewrap isn't installed. Install it (sudo "), seen
    assert not any("xdg-dbus-proxy" in t for t in seen), seen         # review 2, F12: it named both, whatever was missing


# R4.4 (CR1, #465): the chip of an installed app is its own install's result, and the file Install or
# Update would take gets a forecast, worded as one. The chips were driven by no test.
CHECK_CHIPS = ("Verified", "Checksum", "Unverified", "Checksum published", "No checksum published")
NEWER = {"tag": "v2.0", "name": "2.0", "version": "2.0", "date": "2026-02-01T00:00:00Z", "prerelease": False, "notes": "",
         "html_url": URL + "/releases/v2.0"}


def _file(name, digest=""):
    return {"name": name, "url": "u/" + name, "size": 1, "digest": digest, "content_type": ""}


@pytest.mark.parametrize("record, newer, chips", [
    ({"verified": "unverified"}, _file("demo-2.0-linux-x86_64.tar.gz", "sha256:" + "ab" * 32),
     {"Unverified": "", "Checksum published": "2.0 has a digest for the file Update would take: the download will be checked against it."}),
    # a checksum file in the release, which nothing has read yet: the chip says no more than that (pass 1 of #732, U04r2-7)
    ({"verified": "unverified"}, [_file("demo-2.0-linux-x86_64.tar.gz"), _file("SHA256SUMS")],
     {"Unverified": "", "Checksum published": "2.0 has a checksum file: the download of the file Update would take will be checked against it."}),
    ({"verified": "checksum", "checksum_source": "SHA256SUMS"}, _file("demo-2.0-linux-x86_64.tar.gz"),
     {"Checksum": "Checked against SHA256SUMS",
      "No checksum published": "2.0 publishes no checksum for the file Update would take: there is nothing to check the download against."}),
    ({"verified": "signed", "signer": "Demo Ltd"}, None, {"Verified · Demo Ltd": ""}),
    ({"verified": "unverified"}, _file("demo-2.0.dmg"), {"Unverified": ""}),            # 2.0 has no file for this computer
    ({"verified": "unverified", "checksum_reason": "SHA256SUMS doesn't list this file"}, None,       # CR1, #328
     {"Unverified": "Its release has a checksum file, but this download was checked against none: SHA256SUMS doesn't list this file"}),
    # a channel's copy: the chip and who signed it are its record's (R16.3.6; CR1, #318)
    ({"channel": "flatpak", "flatpak": "org.example.Demo", "remote": "vendor", "verified": "signed", "signer": "vendor"}, None,
     {"Verified": "Signed by vendor"}),
    ({"channel": "package", "package": "demo", "manager": "apt", "pkgVersion": "1.0-1", "verified": "signed", "signer": "LP-PPA-demo"}, None,
     {"Verified": "Signed by LP-PPA-demo"}),
    ({"channel": "flatpak", "flatpak": "org.example.Demo", "remote": "aktest", "verified": "unverified"}, None,
     {"Unverified": "No key checked this copy: flatpak doesn't check its remote, aktest, against one"}),
    (None, None, {"No checksum published": "1.0 publishes no checksum for the file Install would take: "
                                           "there is nothing to check the download against."}),
], ids=["unverified-and-an-update-with-a-digest", "unverified-and-an-update-with-a-checksum-file", "checksum-and-an-update-with-none", "signed", "no-file-in-the-newest",
        "a-checksum-file-without-the-file",
        "a-vendors-flatpak", "a-ppas-package", "a-flatpak-no-key-checked", "not-installed"])
def test_app_detail_shows_what_the_installed_file_was_checked_against_and_a_forecast_for_the_next_one(ui, be, app, record, newer, chips):
    rels = json.loads(be.db.one("SELECT releases FROM apps WHERE url=?", (URL,))["releases"])
    if newer:
        be.db.x("UPDATE apps SET releases=? WHERE url=?", (json.dumps([{**NEWER, "assets": newer if isinstance(newer, list) else [newer]}] + rels), URL))
    if record is None:
        be.db.x("DELETE FROM installs WHERE url=?", (URL,))
    else:
        old = json.loads(be.db.one("SELECT record FROM installs WHERE url=?", (URL,))["record"])
        be.db.x("UPDATE installs SET record=? WHERE url=?", (json.dumps({**old, **record}), URL))
    detail = _show(ui, be)
    shown = {o.property("text"): o.property("tip") for o in _items(detail) if o.metaObject().className().startswith("Pill")
             and o.property("visible") is True and str(o.property("text")).split(" · ")[0] in CHECK_CHIPS}
    assert shown == chips


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
    _review(be, "online-app")                                         # the reviewers now suggest more (R17.11)
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


@pytest.mark.parametrize("state", ["owned", "activatable", "free"])
def test_app_detail_says_where_a_launch_here_goes_without_password_service(ui, be, app, tmp_path, monkeypatch, state):
    # PR #694's review, P3-1 (the owner's decision of 2026-11-25): an app the user gave Password
    # service showed it among its chips wherever its launches went without it. App Detail now asks
    # this session's bus as the launcher does, and says why, in the words of the dialog's hint.
    from test_dialog_contract import NOT_OFFERED, password_bus, runs_past
    asked = password_bus(tmp_path, monkeypatch, state)
    be.setSandbox(URL, {"custom": sb.to_json(sb.apply_overrides(sb.resolve_template("standard"), {"caps": ["secrets-provide"]}))})
    be._regenerate_launcher(URL)
    detail = _show(ui, be)
    seen = _seen(detail)
    assert not _has(seen, "Sandboxed", "Password service"), seen
    assert [t for t in seen if t.startswith("Not offered here")] == ([NOT_OFFERED[state]] if NOT_OFFERED[state] else []), seen
    assert "NameHasOwner org.freedesktop.secrets" in asked.read_text()
    runs_past(ui, "Not offered here")                                     # laid out, then scrolled to the sandbox
    _call(detail, "scrollTo", "sandbox")
    assert runs_past(ui, "Not offered here") == ([] if NOT_OFFERED[state] else None)
    be.setSandbox(URL, {"template": "standard", "overrides": {}})          # an app without it: nothing to say, nothing asked
    be._regenerate_launcher(URL)
    asked.unlink()
    seen = _seen(_show(ui, be))
    assert not any(t.startswith("Not offered here") for t in seen) and not asked.exists(), seen


def test_app_detail_asks_the_bus_once_as_it_opens_and_never_holds_the_window(ui, be, app, tmp_path, monkeypatch):
    # PR #694's review, P8-1: App Detail read its Password service line through a binding every reload
    # ran again (an install, an update, a setting, the timed background sync), and each read asked the
    # bus on the GUI thread: on a session bus that takes the connection and never answers, the window
    # froze for the ask's five seconds as App Detail opened and at every reload. Now it asks once as it
    # opens on the app, on a worker; the line comes with the answer, and a reload keeps that answer.
    from test_dialog_contract import password_bus, running
    monkeypatch.setattr(threading.Thread, "start", _START)
    asked = password_bus(tmp_path, monkeypatch, "hung")
    be.setSandbox(URL, {"custom": sb.to_json(sb.apply_overrides(sb.resolve_template("standard"), {"caps": ["secrets-provide"]}))})
    be._regenerate_launcher(URL)
    began = time.monotonic()
    detail = _show(ui, be)
    for _ in range(3):
        be.reload()                                                       # a sync's, an install's, a setting's
    assert time.monotonic() - began < 1                                   # no wait on the bus
    line = lambda: [t for t in _seen(detail) if t.startswith("Not offered here")]   # noqa: E731
    assert line() == []                                                   # and no words until it answers
    came, gap = running(lambda: line() == [sb.PROVIDE_NOTES["ask"]], 15)
    assert came and gap < 1, (line(), gap)                                # the window turned all the while
    for _ in range(3):
        be.reload()
    assert line() == [sb.PROVIDE_NOTES["ask"]] and asked.read_text().count("NameHasOwner") == 1, asked.read_text()


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


# ------------------------------------------------------------------- the uninstall confirmation (R17.14)

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
    # Review 2, F12: the first-need prompt R17.10 promised, as Main shows it from sandboxSetupNeeded
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
    # "Include my sandbox" (R8.4.7: a sandbox can name personal folders)
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


# ------------------------------------------------------------------- the review dialog's Version select and Details (CR1, #497)

def _top(item):
    from PySide6.QtCore import QPointF
    return item.mapToScene(QPointF(0, 0)).y()


def _laid_out():
    """Let the window lay out what was just opened: a Column places its rows when it is polished."""
    from PySide6.QtTest import QTest
    QTest.qWait(60)


def _menu(under, first):
    """The menu under `under` whose first row is this one."""
    from PySide6.QtCore import QObject
    for o in under.findChildren(QObject):
        if o.metaObject().className().startswith("PopMenu"):
            items = o.property("items")
            items = items.toVariant() if hasattr(items, "toVariant") else items
            if items and items[0].get("text") == first:
                return o
    raise AssertionError(f"no menu that starts with {first!r}")


def _menu_rows(menu):
    """The menu's rows by their text, from the top down, and the Flickable they scroll in."""
    from PySide6.QtCore import QObject
    texts = [o for o in _items(menu) if o.metaObject().className().startswith("QQuickText") and o.property("font").bold()
             and o.property("visible") is True]
    return {o.property("text"): o for o in sorted(texts, key=_top)}, menu.findChild(QObject, "rows")


def _wheel_to(ui, flick, row):
    """Turn the mouse wheel over the menu, as a user would, until the row is whole inside it and at rest."""
    from PySide6.QtCore import QCoreApplication, QPoint, QPointF, Qt
    from PySide6.QtGui import QWheelEvent
    from PySide6.QtTest import QTest
    over = flick.mapToScene(QPointF(flick.width() / 2, flick.height() / 2))
    for _ in range(100):
        for _ in range(100):                # a wheel's step is animated: where it comes to rest
            at = flick.property("contentY")
            QTest.qWait(20)
            if flick.property("contentY") == at and not flick.property("moving"):
                break
        top = row.mapToItem(flick, QPointF(0, 0)).y()
        if 0 <= top and top + row.height() <= flick.height():
            return True
        away = top + row.height() - flick.height() if top > 0 else -top
        for _ in range(max(1, min(8, int(away // 100)))):       # a few notches at a time while it is far
            ev = QWheelEvent(over, ui.mapToGlobal(over.toPoint()), QPoint(0, 0), QPoint(0, -120 if top > 0 else 120), Qt.MouseButton.NoButton,
                             Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
            ev.setTimestamp(int(time.monotonic() * 1000))      # as a real event has: a Flickable reads its wheel's speed from it
            QCoreApplication.sendEvent(ui, ev)
            QTest.qWait(15)
    return False


def _click(ui, item):
    from PySide6.QtCore import QCoreApplication, QPointF, Qt
    from PySide6.QtTest import QTest
    QTest.mouseClick(ui, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                     item.mapToScene(QPointF(item.width() / 2, item.height() / 2)).toPoint())
    QCoreApplication.processEvents()


def test_the_review_dialogs_version_select_reaches_every_release_and_every_reviewed_version(ui, be, app, tmp_path):
    # R8.4.1.1: "A select of the app's releases, newest first, plus Any version", and a review of a
    # version the user never installed is allowed. The menu showed its first 12 choices and didn't
    # scroll: with more releases, the installed version (the dialog's starting choice) couldn't be
    # returned to once another was picked, and an earlier review of an old version couldn't be opened.
    from appkata_core import review
    path = tmp_path / "AppKata.md"
    path.write_text("# My Trust\n")
    be._prefs["reviewPath"] = str(path)
    review.save(str(path), "Demo", URL, [], 4, 4, "An editor.", False, False, None, "", None, {})
    review.save(str(path), "Demo", URL, [], 2, 4, "It lost a file.", False, False, None, "0.5", None, {})    # no longer among the releases
    one = json.loads(be.db.one("SELECT releases FROM apps WHERE url=?", (URL,))["releases"])[0]
    newer = [{**one, "tag": f"v{n}.0", "name": f"{n}.0", "version": f"{n}.0", "date": f"2026-02-{n:02d}T00:00:00Z",
              "assets": [{**one["assets"][0], "name": f"demo-{n}.0-linux-x86_64.tar.gz", "url": f"u{n}"}]} for n in range(25, 1, -1)]
    be.db.x("UPDATE apps SET releases=? WHERE url=?", (json.dumps(newer + [one]), URL))
    be.reload()
    dlg = _part(ui, "review")
    _call(dlg, "openFor", URL)
    menu = _menu(dlg, "Any version")
    assert dlg.property("version") == "1.0"                              # the installed version, the 25th release
    for pick, note, exists in (("25.0", "", False), ("1.0", "Installed", False), ("0.5", "Reviewed", True)):
        _call(menu, "open")
        _laid_out()
        rows, flick = _menu_rows(menu)
        assert list(rows) == ["Any version"] + [f"{n}.0" for n in range(25, 0, -1)] + ["0.5"]
        assert flick.property("interactive") is True and 0 < flick.height() <= 460 < flick.property("contentHeight")
        assert _wheel_to(ui, flick, rows[pick]), f"{pick} can't be scrolled to"
        _click(ui, rows[pick])
        assert menu.property("visible") is False and dlg.property("version") == pick
        shown = _seen(dlg)
        assert (pick + (" · " + note if note else "")) in shown, shown        # the select's own box says which
        cur = dlg.property("cur")
        assert bool((cur.toVariant() if hasattr(cur, "toVariant") else cur).get("exists")) is exists     # an earlier review opens for editing


def test_a_menu_with_no_height_set_is_as_tall_as_its_rows_and_doesnt_scroll(ui, be, app):
    # PopMenu is every menu's: only one that sets maxHeight scrolls
    from PySide6.QtCore import QObject
    menu = _menu(_show(ui, be), "Pin at 1.0")                             # its ⋯ menu
    _call(menu, "open")
    _laid_out()
    flick = menu.findChild(QObject, "rows")
    assert flick.property("interactive") is False and flick.height() == flick.property("contentHeight") > 0
    assert menu.property("maxHeight") == 0 and menu.property("height") == flick.height() + 12
    _call(menu, "close")


def test_the_review_dialog_shows_the_details_it_will_write_whole(ui, be, app, tmp_path):
    # R8.4.5.1: "the exact lines in a small monospace preview". The SHA-256 was cut to 12 digits and
    # an ellipsis, in the user's one look at what gets published
    path = tmp_path / "AppKata.md"
    path.write_text("# My Trust\n")
    be._prefs["reviewPath"] = str(path)
    sha = "5e" * 32
    old = json.loads(be.db.one("SELECT record FROM installs WHERE url=?", (URL,))["record"])
    be.db.x("UPDATE installs SET asset=?, record=? WHERE url=?", ("demo-1.0-linux-x86_64.tar.gz", json.dumps({**old, "sha256": {"1.0": sha}}), URL))
    be.reload()
    dlg = _part(ui, "review")
    _call(dlg, "openFor", URL)
    _laid_out()
    lines = [o.property("text") for o in sorted(_items(dlg), key=lambda o: _top(o) if hasattr(o, "mapToScene") else 0)
             if isinstance(o.property("text"), str) and o.property("text").startswith("- ") and o.property("visible") is True]
    assert lines[-2:] == ["- File: demo-1.0-linux-x86_64.tar.gz", "- SHA-256: " + sha], lines
    assert [t.split(":")[0] for t in lines] == ["- Date", "- Platform", "- Channel", "- File", "- SHA-256"]
    written = [f"- {k}: {v}" for k, v in be.reviewData(URL)["details"]]
    assert lines == written                                               # the preview is what Save writes, line for line


def test_app_detail_shows_the_launch_command_and_the_audit_records_its_hash(ui, be, app):
    # Review 2, F11: R17.4 said the launcher's text "can be shown in App Detail ('Show the launch command')
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


@pytest.mark.parametrize("ch, says", [
    ({"kind": "package", "manager": "apt", "distro": "Ubuntu"}, "example.org · .deb · Ubuntu"),
    ({"kind": "package", "manager": "apt", "distro": ""}, "example.org · .deb"),          # no repository's key checked it (R16.3.6)
    ({"kind": "package", "manager": "dnf", "distro": ""}, "example.org · .rpm"),
    ({"kind": "flatpak", "distro": ""}, "example.org · Flatpak"),
])
def test_the_apps_row_of_a_package_names_its_repository_only_where_the_record_has_one(ui, be, app, ch, says):
    """CR1, #318: the row ended "· .deb · " once a package's record could name no repository."""
    from PySide6.QtCore import QUrl
    from PySide6.QtQml import QQmlComponent, qmlEngine
    made = QQmlComponent(qmlEngine(ui), QUrl.fromLocalFile(os.path.join(os.path.dirname(__file__), "..", "src", "appkata", "qml", "AppRow.qml")))
    row = made.createWithInitialProperties({"app": {"url": URL, "name": "Demo", "host": "example.org", "installed": "1.0", "ch": ch}})
    assert row is not None, made.errorString()
    try:
        assert says in _seen(row) and not any(t.endswith("· ") for t in _seen(row)), _seen(row)
    finally:
        row.deleteLater()
