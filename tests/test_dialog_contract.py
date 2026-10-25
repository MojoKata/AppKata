"""The Sandbox and Install dialogs, driven offscreen against a real Backend: the QML-to-backend
contract (requirement 17.3, 17.11).

The backend tests call setSandbox/installWith with hand-written arguments; the dialogs compose
those arguments in QML (template vs custom, "customized", "widened", "touched"), and three review
findings sat exactly there (round two R1, round four R4-1 and R4-3). Here the real QML is loaded
in a window with the real Backend as `backend`, each state the backend can put a dialog in is
opened, the dialog is driven through the same signals a click sends, and the result is read back
from the backend: nothing raises, nothing is refused, and what the backend then reports is what
the dialog showed.
"""

import json
import os

import pytest

pytest.importorskip("PySide6")

from appkata_core import sandbox as sb                      # noqa: E402
from appkata_core import trustfile                          # noqa: E402
from test_sandbox_backend import URL, _installed, _review, _tarball_install, be   # noqa: E402,F401

HARNESS = os.path.join(os.path.dirname(__file__), "qml", "DialogHarness.qml")


@pytest.fixture(scope="module")
def qapp():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture
def ui(qapp, be):
    from PySide6.QtCore import QUrl
    from PySide6.QtQml import QQmlApplicationEngine
    engine = QQmlApplicationEngine()
    ctx = engine.rootContext()
    for name, value in (("backend", be), ("appVersion", "test"), ("themeOverride", ""), ("tourMode", False), ("platformOs", "linux")):
        ctx.setContextProperty(name, value)
    engine.load(QUrl.fromLocalFile(HARNESS))
    assert engine.rootObjects(), "the dialog harness did not load"
    root = engine.rootObjects()[0]
    yield root
    from PySide6.QtCore import QCoreApplication, QEvent
    root.deleteLater()
    engine.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)      # before the backend goes


def _call(obj, name, *args):
    from PySide6.QtCore import Q_ARG, QMetaObject, Qt
    return QMetaObject.invokeMethod(obj, name, Qt.ConnectionType.DirectConnection, *[Q_ARG("QVariant", a) for a in args])


def _dialog(ui, which):
    from PySide6.QtCore import QObject
    return ui.findChild(QObject, which)


def _prop(obj, name):
    """A QML property as plain Python (a JS object comes back as a QJSValue)."""
    v = obj.property(name)
    return v.toVariant() if hasattr(v, "toVariant") else v


def _press(dlg, name):
    from PySide6.QtCore import QObject
    btn = dlg.findChild(QObject, name)
    assert btn is not None, name
    btn.clicked.emit()


def _pick(dlg, select, key):
    from PySide6.QtCore import QObject
    sel = dlg.findChild(QObject, select)
    assert sel is not None, select
    sel.picked.emit(key)


def _second_review(be, template):
    be.db.x("INSERT OR IGNORE INTO trusts(url, name, enabled, score) VALUES(?,?,1,2)", ("https://example.org/trust2", "Bob"))
    parsed, _ = trustfile.parse_section("Demo", f"## Demo::Settings\n\n- Trust: 4\n- Sandbox (linux): {template}\n")
    tid = be.db.one("SELECT id FROM trusts WHERE name='Bob'")["id"]
    be.db.x("INSERT OR REPLACE INTO reviews(trust_id, url, app, settings) VALUES(?,?,?,?)", (tid, URL, "Demo", json.dumps(parsed["opts"])))


# every state the backend can open the Sandbox dialog in: (how it comes about, the template shown)
STATES = {
    "unreviewed default": (lambda be: None, "strict"),
    "one review": (lambda be: _review(be, "online-app"), "online-app"),
    "two reviews, merged": (lambda be: (_review(be, "online-app"), _second_review(be, "offline-editor")), "custom"),
    "pinned from merged reviews": (lambda be: (_review(be, "online-app"), _second_review(be, "offline-editor"), _installed(be),
                                               be._pin_sandbox(URL, be._resolved_sandbox(URL, kind="appimage"))), "custom"),
    "user's template": (lambda be: be.setSandbox(URL, {"template": "media-player", "overrides": {}}), "media-player"),
    "user's custom set": (lambda be: be.setSandbox(URL, {"custom": sb.to_json(sb.apply_overrides(sb.resolve_template("standard"), {"network": False}))}), "custom"),
    "off": (lambda be: be.setSandbox(URL, {"template": "off"}), "off"),
}


@pytest.mark.parametrize("state", list(STATES))
def test_saving_the_sandbox_dialog_untouched_keeps_what_it_showed(ui, be, state, monkeypatch):
    # Round four, R4-1: a Save with nothing changed must store exactly what the dialog displayed,
    # whatever the backend called the template ("custom" included), and never be refused.
    monkeypatch.setattr(be, "_app", lambda url: {"url": URL, "name": "Demo", "installed": ""})
    setup, template = STATES[state]
    setup(be)
    toasts = []
    be._toast.connect(lambda kind, text: toasts.append((kind, text)))
    dlg = _dialog(ui, "sandbox")
    _call(dlg, "openFor", URL)
    assert _prop(dlg, "tpl") == template, state
    shown = sb.summary(_prop(dlg, "gs"), template=template) if template != "off" else ["No sandbox"]
    _press(dlg, "save")
    info = be.sandboxInfo(URL)                                   # must not raise
    assert not [t for t in toasts if t[0] == "error"], toasts
    assert info["source"] == "user" and [c[0] for c in info["chips"]] == shown, state
    assert not sb.config_error(be._user_sandbox_config(URL))


@pytest.mark.parametrize("key", list(sb.TEMPLATE_ORDER) + ["off"])
def test_picking_a_template_in_the_sandbox_dialog_applies_that_template(ui, be, key, monkeypatch):
    monkeypatch.setattr(be, "_app", lambda url: {"url": URL, "name": "Demo", "installed": ""})
    _review(be, "online-app")
    dlg = _dialog(ui, "sandbox")
    _call(dlg, "openFor", URL)
    _pick(dlg, "templateSelect", key)
    assert _prop(dlg, "tpl") == key and not _prop(dlg, "customized")
    _press(dlg, "save")
    info = be.sandboxInfo(URL)
    assert info["source"] == "user" and info["template"] == key
    want = sb.summary(sb.resolve_template(key), template=key) if key != "off" else ["No sandbox"]
    assert [c[0] for c in info["chips"]] == want


def test_customizing_in_the_sandbox_dialog_round_trips_and_strict_widens(ui, be, monkeypatch):
    monkeypatch.setattr(be, "_app", lambda url: {"url": URL, "name": "Demo", "installed": ""})
    _review(be, "online-app")
    dlg = _dialog(ui, "sandbox")
    _call(dlg, "openFor", URL)
    _call(dlg, "setField", "network", False)                     # what the Network toggle does
    assert _prop(dlg, "customized") and _prop(dlg, "tpl") == "online-app"
    _press(dlg, "save")
    info = be.sandboxInfo(URL)
    # saved as its template plus the change, so it keeps the name (review 2, F10: it became "Custom")
    assert info["source"] == "user" and info["template"] == "online-app" and info["customized"] and info["network"] is False
    assert be._user_sandbox_config(URL) == {"template": "online-app", "overrides": {"network": False}}
    assert "No network" in [c[0] for c in info["chips"]] and "Sound · can also record" in [c[0] for c in info["chips"]]

    _call(dlg, "openFor", URL)                                   # reopened: the template, customized
    assert _prop(dlg, "tpl") == "online-app" and _prop(dlg, "customized")
    _pick(dlg, "templateSelect", "strict")
    _call(dlg, "setField", "folders", {"~/Projects": "rw"})      # a folder added at Strict (17.2, R3-2)
    assert _prop(dlg, "widened") and _prop(dlg, "tpl") == "standard" and _prop(dlg, "gs")["level"] == "standard"
    # described by what it is, not Standard's blurb ("Network and notifications"; review 2's nit)
    blurb = dlg.findChild(__import__("PySide6.QtCore", fromlist=["QObject"]).QObject, "blurb").property("text")
    assert blurb == "Standard, without the network and notifications, with ~/Projects (read-write).", blurb
    _press(dlg, "save")
    info = be.sandboxInfo(URL)
    assert info["level"] == "standard" and info["folders"] == [{"path": "~/Projects", "mode": "rw"}]


def test_use_theirs_in_the_sandbox_dialog_adopts_the_suggestion(ui, be, monkeypatch):
    monkeypatch.setattr(be, "_app", lambda url: {"url": URL, "name": "Demo", "installed": "1.0"})
    _review(be, "offline-editor")
    _installed(be)
    be._pin_sandbox(URL, be._resolved_sandbox(URL, kind="appimage"))
    _review(be, "online-app")                                    # the suggestion changed
    dlg = _dialog(ui, "sandbox")
    _call(dlg, "openFor", URL)
    assert _prop(dlg, "info")["hasSuggestion"] and be.sandboxInfo(URL)["reviewBadge"]
    _press(dlg, "useTheirs")
    info = be.sandboxInfo(URL)
    assert info["network"] is True and not info["reviewBadge"] and not info["hasSuggestion"]


def _plan(be):
    """What Backend.planFor gives the install dialog, for a portable AppImage with its sandbox card."""
    info = be.sandboxInfo(URL)
    return {"url": URL, "name": "Demo", "version": "1.0", "chosen": 0, "ask": True, "reasons": [],
            "cards": [{"channel": "release", "category": "portable", "kind": "appimage", "label": "AppImage"}],
            "portable": {"appMenu": True, "commandLink": True, "stableName": True},
            "sandbox": {"applicable": True, "source": info["source"], "template": info["template"], "level": info["level"],
                        "chips": info["chips"], "grants": info["grants"], "templates": info["templates"],
                        "recommendedBy": info["reviewBy"], "support": info["support"], "extractMb": 0,
                        "suggestsOff": info["suggestsOff"], "freshWarning": info["freshWarning"],
                        "byKind": {k: {key: (r := be._resolved_sandbox(URL, kind="appimage", is_cli=k == "cli"))[key] if key != "level"
                                       else sb.level_of(r["grants"]) for key in ("template", "source", "level")}
                                   | {"chips": sb.summary_chips(be._resolved_sandbox(URL, kind="appimage", is_cli=k == "cli")["grants"])}
                                   for k in ("gui", "cli")}},
            "kind": {"detected": "", "choice": be._install_settings(URL).get("cliKind") or ""}}


def test_the_install_dialog_sends_a_sandbox_only_when_the_card_was_touched(ui, be, tmp_path, monkeypatch):
    # Round two R1 / round four R4-3: an untouched card sends no sandbox key (so nothing of the
    # user's is overwritten); a touched one is saved and, on an installed app, applied at once.
    _review(be, "online-app")
    _tarball_install(be, tmp_path)
    monkeypatch.setattr(sb, "have_tools", lambda: True)
    monkeypatch.setattr(sb, "support_status", lambda: {"status": "ok"})
    installs = []
    monkeypatch.setattr(be, "_install", lambda *a, **k: installs.append((a, k)))
    be._regenerate_launcher(URL)
    rec = json.loads(be.db.one("SELECT record FROM installs WHERE url=?", (URL,))["record"])
    dlg = _dialog(ui, "install")
    _call(dlg, "openWith", _plan(be), True)                      # "Install options…" on the installed app
    assert _prop(dlg, "sandboxTpl") == "online-app" and not _prop(dlg, "sandboxTouched")
    _press(dlg, "save")
    assert installs == [] and "sandbox" not in be._install_settings(URL)
    assert "--share-net" in open(rec["launcher"]).read()

    _call(dlg, "openWith", _plan(be), True)
    _pick(dlg, "sandboxSelect", "strict")
    assert _prop(dlg, "sandboxTouched")
    _press(dlg, "save")
    assert installs == []
    assert be._install_settings(URL)["sandbox"] == {"template": "strict", "overrides": {}}
    assert be.sandboxInfo(URL)["level"] == "strict" and "--share-net" not in open(rec["launcher"]).read()


def test_the_install_dialogs_choice_goes_into_the_install(ui, be, monkeypatch):
    monkeypatch.setattr(be, "_app", lambda url: {"url": URL, "name": "Demo", "installed": ""})
    _review(be, "online-app")
    installs = []
    monkeypatch.setattr(be, "_install", lambda *a, **k: installs.append(a))
    dlg = _dialog(ui, "install")
    _call(dlg, "openWith", _plan(be), False)                     # a first install
    _pick(dlg, "sandboxSelect", "messenger")
    _press(dlg, "save")
    assert len(installs) == 1 and installs[0][2]["sandbox"] == {"template": "messenger", "overrides": {}}
    assert be._install_settings(URL)["sandbox"]["template"] == "messenger"
    assert be.sandboxInfo(URL)["reviewBadge"] is False           # chosen knowing the suggestion (R2)


def test_a_reviews_off_is_offered_on_the_install_card_and_applied_only_by_a_click(ui, be, monkeypatch):
    # Review 2, F8: a review's `Sandbox: off` no longer applies by itself; the card shows the reviewed
    # baseline and offers "Use theirs", and only that click sends Off.
    monkeypatch.setattr(be, "_app", lambda url: {"url": URL, "name": "Demo", "installed": ""})
    _review(be, "off")
    installs = []
    monkeypatch.setattr(be, "_install", lambda *a, **k: installs.append(a))
    dlg = _dialog(ui, "install")
    plan = _plan(be)
    assert plan["sandbox"]["suggestsOff"] and plan["sandbox"]["level"] == "standard"
    _call(dlg, "openWith", plan, False)
    assert _prop(dlg, "sandboxTpl") == "standard"
    _press(dlg, "save")
    assert installs[-1][2].get("sandbox") is None                        # untouched: the baseline, nothing sent
    _call(dlg, "openWith", _plan(be), False)
    from PySide6.QtCore import QObject
    off = dlg.findChild(QObject, "useTheirsOff")
    assert off is not None and off.property("visible")
    dlg.setProperty("sandboxTpl", "off"); dlg.setProperty("sandboxTouched", True)   # what its click does
    _press(dlg, "save")
    assert installs[-1][2]["sandbox"] == {"template": "off"}


def test_the_install_dialogs_kind_choice_moves_the_sandbox_card_and_is_saved(ui, be, monkeypatch):
    # Review 2, F4: the install dialog shows the app's kind as a choice the user can flip, and an
    # untouched Sandbox card follows it (an unreviewed command-line tool: the cli-tool template).
    monkeypatch.setattr(be, "_app", lambda url: {"url": URL, "name": "Demo", "installed": ""})
    installs = []
    monkeypatch.setattr(be, "_install", lambda *a, **k: installs.append(a))
    dlg = _dialog(ui, "install")
    _call(dlg, "openWith", _plan(be), False)
    assert _prop(dlg, "sandboxTpl") == "strict" and _prop(dlg, "effKind") == "gui"
    _pick(dlg, "kindSelect", "cli")
    assert _prop(dlg, "sandboxTpl") == "cli-tool" and _prop(dlg, "appMenu") is False and not _prop(dlg, "sandboxTouched")
    _press(dlg, "save")
    assert installs[-1][2]["cliKind"] == "cli" and installs[-1][2].get("sandbox") is None
    assert be._install_settings(URL)["cliKind"] == "cli"
    _call(dlg, "openWith", _plan(be), False)
    assert _prop(dlg, "appKindChoice") == "cli" and _prop(dlg, "sandboxTpl") == "cli-tool"
    _pick(dlg, "kindSelect", "")                                                  # back to what the download shows
    _press(dlg, "save")
    assert "cliKind" not in be._install_settings(URL)


@pytest.mark.parametrize("where", ["sandbox dialog", "install options"])
def test_sandboxing_an_app_that_runs_unsandboxed_warns_before_save(ui, be, tmp_path, monkeypatch, where):
    # Review 2, F13: 17.13's warning that the app starts afresh came as a toast after the change was
    # made. It is said above Save now, once a sandboxed choice is picked, and only where it is true:
    # an installed app that runs unsandboxed and has no private home with anything in it
    from test_sandbox_ui_surfaces import _seen
    _tarball_install(be, tmp_path)
    monkeypatch.setattr(sb, "have_tools", lambda: True)
    monkeypatch.setattr(sb, "support_status", lambda: {"status": "ok"})
    monkeypatch.setattr(be, "_install", lambda *a, **k: None)
    be.setSandbox(URL, {"template": "off"})
    toasts = []
    be._toast.connect(lambda kind, text: toasts.append(text))
    warning = "Sandboxing Demo gives it an empty private home of its own, as if newly installed"

    def pick(key):
        dlg = _dialog(ui, "sandbox" if where == "sandbox dialog" else "install")
        if where == "sandbox dialog":
            _call(dlg, "openFor", URL)
            _pick(dlg, "templateSelect", key)
        else:
            _call(dlg, "openWith", _plan(be), True)
            _pick(dlg, "sandboxSelect", key)
        return dlg
    dlg = pick("off")
    assert not any(warning in t for t in _seen(dlg))                 # Off stays Off: nothing to warn of
    dlg = pick("strict")
    assert any(warning in t for t in _seen(dlg)), _seen(dlg)
    _press(dlg, "save")
    assert be.sandboxInfo(URL)["active"] and not any("fresh" in t or "reset" in t for t in toasts), toasts
    be.setSandbox(URL, {"template": "off"})
    home = sb.sandbox_home(be._app_id(URL))
    os.makedirs(home, exist_ok=True)
    open(os.path.join(home, ".config"), "w").close()                  # it has a home from before: no reset
    assert be.sandboxInfo(URL)["freshWarning"] == ""
    dlg = pick("strict")
    assert not any(warning in t for t in _seen(dlg))
    _call(dlg, "close")


@pytest.mark.parametrize("template,button,mode", [("offline-editor", "Documents", "rw"), ("media-player", "Music", "ro"),
                                                  ("developer", None, "rw")])
def test_a_folder_template_offers_its_folder_in_place_and_keeps_its_name(ui, be, monkeypatch, template, button, mode):
    # Review 2, F10: picking offline-editor, media-player or developer asked for no folder, though each
    # promised one, and any customization saved as "Custom". Now the dialog offers the folder in place
    # (one click for the user folders that fit, Other... for any), the summary says "No folder yet"
    # until then, and the choice is saved as the template plus the folder, under the template's name.
    from test_sandbox_ui_surfaces import _seen
    from PySide6.QtCore import QObject, QMetaObject, Qt, QUrl
    monkeypatch.setattr(be, "_app", lambda url: {"url": URL, "name": "Demo", "installed": ""})
    for d in ("Documents", "Pictures", "Music", "Videos", "Code"):
        os.makedirs(os.path.join(be.locations["home"], d), exist_ok=True)
    dlg = _dialog(ui, "sandbox")
    _call(dlg, "openFor", URL)
    _pick(dlg, "templateSelect", template)
    seen = _seen(dlg)
    want = {"offline-editor": ["Documents", "Pictures"], "media-player": ["Music", "Videos"], "developer": []}[template]
    pick = dlg.findChild(QObject, "pickFolder")
    from test_sandbox_ui_surfaces import _items
    offered = [o.property("text") for o in _items(pick) if o.metaObject().className().startswith("FButton")]
    assert "Pick its folder:" in seen and "No folder yet" in seen and sorted(offered) == sorted(want + ["Other…"]), (seen, offered)
    if button:
        next(o for o in _items(pick) if o.metaObject().className().startswith("FButton") and o.property("text") == button).clicked.emit()
        path = "~/" + button
    else:                                                    # a projects folder: Other...
        picker = dlg.findChild(QObject, "folderPicker")
        QMetaObject.invokeMethod(picker, "open", Qt.ConnectionType.DirectConnection)
        picker.setProperty("selectedFolder", QUrl.fromLocalFile(os.path.join(be.locations["home"], "Code")))
        QMetaObject.invokeMethod(picker, "accept", Qt.ConnectionType.DirectConnection)
        path = "~/Code"
    assert _prop(dlg, "gs")["folders"] == {path: mode} and "No folder yet" not in _seen(dlg)
    _press(dlg, "save")
    assert be._user_sandbox_config(URL) == {"template": template, "overrides": {"folders": {"+" + path: mode}}}
    info = be.sandboxInfo(URL)
    assert info["template"] == template and info["customized"] and {"path": path, "mode": mode} in info["folders"]
    _call(dlg, "openFor", URL)                               # reopened: the template, customized, Reset there
    seen = _seen(dlg)
    assert _prop(dlg, "tpl") == template and "· customized" in seen and "Reset to template" in seen
    _call(dlg, "close")


def test_the_install_cards_folder_link_opens_the_dialog_on_its_template_and_adopts_what_is_saved(ui, be, monkeypatch):
    # The install card's "Pick its folder…" (and Customize…) opened the Sandbox dialog on the saved
    # choice, not the card's pick; Install then sent the card's template over what was saved there
    from test_sandbox_ui_surfaces import _seen
    monkeypatch.setattr(be, "_app", lambda url: {"url": URL, "name": "Demo", "installed": ""})
    dlg = _dialog(ui, "install")
    opened = []
    dlg.openSandbox.connect(lambda url, tpl: opened.append((url, tpl)))
    _call(dlg, "openWith", _plan(be), False)
    _pick(dlg, "sandboxSelect", "offline-editor")
    assert any("Offline editor works on a folder you pick" in t for t in _seen(dlg)), _seen(dlg)
    text = next(o for o in dlg.findChildren(__import__("PySide6.QtCore", fromlist=["QObject"]).QObject)
                if isinstance(o.property("text"), str) and "works on a folder you pick" in o.property("text"))
    text.linkActivated.emit("#")
    assert opened == [(URL, "offline-editor")]
    be.setSandbox(URL, {"template": "offline-editor", "custom": sb.to_json(
        sb.apply_overrides(sb.resolve_template("offline-editor"), {"folders": {"+~/Documents": "rw"}}))})
    _call(dlg, "sandboxSaved", URL)                          # what Main does when the Sandbox dialog saves
    assert not _prop(dlg, "sandboxTouched") and _prop(dlg, "sandboxTpl") == "offline-editor"
    assert "~/Documents" in [c[0] for c in _prop(dlg, "sbxChips")]
    assert not any("works on a folder you pick" in t for t in _seen(dlg))
    monkeypatch.setattr(be, "_install", lambda *a, **k: None)
    _press(dlg, "save")                                      # an untouched card leaves the saved choice be
    assert be._user_sandbox_config(URL) == {"template": "offline-editor", "overrides": {"folders": {"+~/Documents": "rw"}}}
@pytest.mark.parametrize("key", list(sb.TEMPLATE_ORDER))
def test_the_install_card_shows_each_picked_templates_chips_whole(ui, be, monkeypatch, key):
    # Found while fixing review 2's F10: the template list carried its chips as bare labels, while the
    # card's pills read [label, icon, tone], so once a template was picked each pill showed one letter
    # ("N", "N", "N"). Nothing read what the card draws; this reads every pill it shows.
    from test_sandbox_ui_surfaces import _items
    monkeypatch.setattr(be, "_app", lambda url: {"url": URL, "name": "Demo", "installed": ""})
    dlg = _dialog(ui, "install")
    _call(dlg, "openWith", _plan(be), False)
    _pick(dlg, "sandboxSelect", key)
    pills = [o.property("text") for o in _items(dlg) if o.metaObject().className().startswith("Pill")
             and o.property("visible") is True and o.property("text")]
    want = sb.summary(sb.resolve_template(key))
    assert sorted(p for p in pills if p in want) == sorted(want), pills
