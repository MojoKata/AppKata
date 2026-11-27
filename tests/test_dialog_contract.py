"""The Sandbox and Install dialogs, driven offscreen against a real Backend: the QML-to-backend
contract (R17.3, R17.11).

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
import time

import pytest

pytest.importorskip("PySide6")

from PySide6 import QtQuick                                 # noqa: E402,F401  (rootObjects() as a QQuickWindow, for runs_past)

from appkata_core import sandbox as sb                      # noqa: E402
from appkata_core import trustfile                          # noqa: E402
from test_sandbox_backend import URL, _installed, _review, _review_lines, _tarball_install, be   # noqa: E402,F401

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


def _hint(dlg, label):
    """What the dialog says under one of its switches."""
    from PySide6.QtCore import QObject
    return next(o.property("hint") for o in dlg.findChildren(QObject) if o.property("label") == label)


def test_a_named_media_player_keeps_its_name_through_the_sandbox_dialog(ui, be, monkeypatch):
    # CR1.5-36: the MPRIS name a review gives an app is part of its grant set, and the dialog has no
    # control for it: it rides in the working set. A Save that dropped it would hand the app every
    # player's name again under the same chips, which is all the untouched-Save test above compares.
    monkeypatch.setattr(be, "_app", lambda url: {"url": URL, "name": "Demo", "installed": ""})
    name = "org.mpris.MediaPlayer2.demo"
    _review_lines(be, f"- Sandbox (linux): media-player\n- Sandbox MPRIS name (linux): {name}\n")
    dlg = _dialog(ui, "sandbox")
    _call(dlg, "openFor", URL)
    assert _prop(dlg, "tpl") == "media-player" and _prop(dlg, "gs")["mpris_name"] == name
    assert _hint(dlg, "Media keys") == f"Play/pause and track info on the keyboard and lock screen (MPRIS), under its own player name alone: {name}."
    _call(dlg, "toggleIn", "caps", "mpris", False)               # Media keys off and on again: still its own name
    _call(dlg, "toggleIn", "caps", "mpris", True)
    _call(dlg, "setField", "network", True)                      # and another change beside it
    _press(dlg, "save")
    assert be._user_sandbox_config(URL) == {"template": "media-player", "overrides": {"network": True, "mpris_name": name}}
    args = sb.proxy_args(be._resolved_sandbox(URL)["grants"], "demo")
    assert f"--own={name}" in args and "--own=org.mpris.MediaPlayer2.*" not in args
    _call(dlg, "openFor", URL)                                   # reopened: the same
    assert _prop(dlg, "gs")["mpris_name"] == name
    # the bare template is the user's own set, with no name: the hint says what that reaches, and
    # the dialog offers the reviewer's narrower one, "Use theirs" (the review of PR #694, P1-1: it
    # never showed); the badge stays down, as this was chosen knowing it (R17.11)
    _pick(dlg, "templateSelect", "media-player")
    assert not _prop(dlg, "gs").get("mpris_name")
    assert _hint(dlg, "Media keys") == ("Play/pause and track info on the keyboard and lock screen (MPRIS). It has no player name of its own here "
                                        "(a review gives one), so it may take any, and can reach every other media player that is running.")
    _press(dlg, "save")
    info = be.sandboxInfo(URL)
    assert "--own=org.mpris.MediaPlayer2.*" in sb.proxy_args(be._resolved_sandbox(URL)["grants"], "demo")
    assert f"removing media-player names other than {name}" in info["reviewBadgeText"], info
    assert info["hasSuggestion"] is True and info["reviewBadge"] is False, info
    _call(dlg, "openFor", URL)
    assert _prop(dlg, "info")["hasSuggestion"] is True


def test_the_network_hint_says_what_an_app_without_the_network_can_still_send_out(ui, be, monkeypatch):
    # CR1.5-29: "No network" is an app with no network of its own, not an app that can send nothing
    # out. At Standard the OpenURI portal is open to every app on the bus (R17.5), so an app without
    # the grant can have the desktop open https://elsewhere.example/?d=<what it knows>, and the
    # user's browser fetches it. The design keeps that road (R17.6.3); what was missing is the
    # sentence, which the Network switch now carries, as R17.17 does. A Strict app has no bus and so
    # no such road, and its hint stops where it did. How it slipped past: the hints' evidence table
    # holds each hint to the facts it states, and nothing asks what a switch leaves unsaid.
    monkeypatch.setattr(be, "_app", lambda url: {"url": URL, "name": "Demo", "installed": ""})
    _review(be, "offline-editor")
    dlg = _dialog(ui, "sandbox")
    _call(dlg, "openFor", URL)
    assert _prop(dlg, "gs")["level"] == "standard" and not _prop(dlg, "gs")["network"]
    reach = "Let it reach the internet and the local network."
    still = reach + " Without it the app can still ask the desktop to open a link, which may carry what the app knows."
    assert _hint(dlg, "Network") == still
    # the road the hint tells of is the one the filter leaves this app: were OpenURI ever to get a
    # switch of its own, the sentence would be that switch's to say
    grants = be._resolved_sandbox(URL)["grants"]
    assert not grants["network"] and sb._portal_call("OpenURI") in sb.proxy_args(grants, "demo")
    _call(dlg, "setField", "network", True)                      # on, it says what off would still leave
    assert _hint(dlg, "Network") == still
    _pick(dlg, "templateSelect", "strict")                       # no bus: nothing to ask, nothing to say
    assert _prop(dlg, "gs")["level"] == "strict" and _hint(dlg, "Network") == reach
    assert "xdg-dbus-proxy" not in sb.build_launcher("demo", "Demo", "/apps/demo/1", "bin/demo", sb.resolve_template("strict"))


# What the screens add where a launch here starts an app without Password service (R17.5.1), word for
# word: the dialog's hint and App Detail (test_sandbox_ui_surfaces)
PASSWORD_SERVICE = "Offer the secret service (org.freedesktop.secrets) to other apps, e.g. KeePassXC. The app then holds every other app's saved passwords."
NOT_OFFERED = {
    "owned": "Not offered here: another program, or a running copy of this app, already provides saved passwords on this computer, so the "
             "app starts without Password service, which would reach that program and every password it holds.",
    "activatable": "Not offered here: another program that provides saved passwords is installed (such as gnome-keyring) and starts when "
                   "an app asks for it, so the app starts without Password service, which could start that program and reach every "
                   "password it holds.",
    "free": "",
}


def password_bus(tmp_path, monkeypatch, state):
    """This session's bus, as a stand-in gdbus first on the launcher's PATH (sandbox.host_path, which
    AppKata's ask runs with, whatever its own PATH) answers for org.freedesktop.secrets, in
    gdbus's own shapes (test_sandbox's _ANSWERS): "owned" by another program, "activatable" (the bus
    can start one), or "free"; or "hung", a bus that takes the ask and never answers (a stopped or
    wedged dbus-daemon), which the ask's `timeout 5` ends. Returns the file that holds what it was asked."""
    from test_sandbox import _ANSWERS
    import shlex
    fake, asked = tmp_path / "bus-answers", tmp_path / "bus-asked"
    fake.mkdir()
    owner, names = _ANSWERS["gdbus"]
    (fake / "gdbus").write_text(f'#!/bin/sh\necho "$*" >> {shlex.quote(str(asked))}\n' + ("exec sleep 30\n" if state == "hung" else
                                f'case "$*" in *NameHasOwner*) echo {shlex.quote(owner(state == "owned"))} ;; '
                                f'*) echo {shlex.quote(names(["org.freedesktop.secrets"] if state == "activatable" else []))} ;; esac\n'))
    (fake / "gdbus").chmod(0o755)
    from appkata_core import sandbox
    monkeypatch.setattr(sandbox, "HOST_PATH", f"{fake}{os.pathsep}{sandbox.HOST_PATH}")
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", f"unix:path={tmp_path}/bus")
    return asked


def running(done, seconds):
    """Run the event loop, as the window does, until done() holds or `seconds` have passed. Returns
    whether it held, and the longest the GUI thread went between two turns of a 20 ms timer: how long
    the window went without repainting or taking input."""
    from PySide6.QtCore import QEventLoop, QTimer
    loop, last, gaps = QEventLoop(), [time.monotonic()], [0.0]

    def turn():
        now = time.monotonic()
        gaps.append(now - last[0])
        last[0] = now
        if done():
            loop.quit()
    timer = QTimer()
    timer.timeout.connect(turn)
    timer.start(20)
    QTimer.singleShot(int(seconds * 1000), loop.quit)
    loop.exec()
    timer.stop()
    return bool(done()), max(gaps)


def answered(be) -> bool:
    """Whether the latest opening's ask of the bus has its answer on the screens (Backend.askPasswordService)."""
    return be._provide_answered == be._provide_opening


def _open(dlg, be, url):
    """Open the Sandbox dialog on `url`, and run the window until the bus's answer is on it: the
    dialog asks on a worker (PR #694's review, P8-1)."""
    _call(dlg, "openFor", url)
    assert running(lambda: answered(be), 15)[0], "the bus's answer never came"


def runs_past(window, start: str) -> list[str] | None:
    """What layout.py finds drawn outside its box among the texts that begin with `start`, once the
    layout has settled (two frames that agree: test_layout's _faults), or None where no such text is
    in view, so the check can't pass on a text scrolled away. The tour never shows these texts (it
    shows a working system), so this is their layout check."""
    from PySide6.QtCore import QCoreApplication
    from appkata import layout
    last = "unsettled"
    for _ in range(20):
        QCoreApplication.processEvents()
        window.grabWindow()
        shown = [t for t in layout._texts(window.contentItem()) if str(t.property("text")).startswith(start)
                 and not layout._shown(t, layout._drawn(t), layout._box(t)[2]).isEmpty()]
        now = [f["line"] for f in layout.faults(window) if f["text"].startswith(start)] if shown else None
        if now == last:
            return now
        last = now
    return last


@pytest.mark.parametrize("state", list(NOT_OFFERED))
def test_the_password_service_hint_says_where_a_launch_here_goes_without_it(ui, be, monkeypatch, tmp_path, state):
    # PR #694's review, P3-1 (the owner's decision of 2026-11-25): the launcher starts an app without
    # Password service where another program holds org.freedesktop.secrets or the bus can start one,
    # gnome-keyring's case wherever it is installed, running or not, and the switch's hint said only
    # what it gives. Now the dialog asks this session's bus when it opens, as the launcher asks it
    # (test_sandbox's harness holds the two to one rule), and the hint says why, on or off.
    monkeypatch.setattr(be, "_app", lambda url: {"url": URL, "name": "Demo", "installed": ""})
    asked = password_bus(tmp_path, monkeypatch, state)
    be.setSandbox(URL, {"custom": sb.to_json(sb.apply_overrides(sb.resolve_template("standard"), {"caps": ["secrets-provide"]}))})
    dlg = _dialog(ui, "sandbox")
    _open(dlg, be, URL)
    want = PASSWORD_SERVICE + (" " + NOT_OFFERED[state] if NOT_OFFERED[state] else "")
    assert "secrets-provide" in _prop(dlg, "gs")["caps"] and _hint(dlg, "Password service") == want
    assert f"--address unix:path={tmp_path}/bus" in asked.read_text() and "NameHasOwner org.freedesktop.secrets" in asked.read_text()
    _call(dlg, "scrollTo", "advanced")                            # Customize open, and once its groups are
    runs_past(ui, PASSWORD_SERVICE[:40])                          # laid out, scrolled to the services
    _call(dlg, "scrollTo", "advanced")
    assert runs_past(ui, PASSWORD_SERVICE[:40]) == []
    _call(dlg, "toggleIn", "caps", "secrets-provide", False)     # off, it says so too: before it is switched on
    assert _hint(dlg, "Password service") == want
    be.setSandbox(URL, {"template": "standard", "overrides": {}})  # an app without it is told before it asks for it
    _open(dlg, be, URL)
    assert "secrets-provide" not in _prop(dlg, "gs")["caps"] and _hint(dlg, "Password service") == want
    (tmp_path / "later").mkdir()                                  # and the bus is asked anew at each opening
    later = password_bus(tmp_path / "later", monkeypatch, "free")
    _open(dlg, be, URL)
    assert _hint(dlg, "Password service") == PASSWORD_SERVICE and later.exists()
    later.unlink()                                                # the tour shows a working system's, through
    be.demoSandbox("ok")                                          # its support status, not the machine's running it
    _open(dlg, be, URL)
    assert _hint(dlg, "Password service") == PASSWORD_SERVICE and be.passwordServiceNote == "" and not later.exists()


def test_the_password_service_ask_never_holds_the_window(ui, be, monkeypatch, tmp_path):
    # PR #694's review, P8-1: the dialog asked the bus on the GUI thread as it opened, so a session bus
    # that takes the connection and never answers (a stopped or wedged dbus-daemon) held the window,
    # unpainted and deaf to input, for the ask's five seconds at every opening, for every app. Now it
    # asks on a worker: the dialog opens at once, and the hint takes its words when the answer comes.
    # The words are the latest opening's: an earlier opening's answer, come late, is dropped.
    monkeypatch.setattr(be, "_app", lambda url: {"url": URL, "name": "Demo", "installed": ""})
    be.setSandbox(URL, {"custom": sb.to_json(sb.apply_overrides(sb.resolve_template("standard"), {"caps": ["secrets-provide"]}))})
    answers = []

    def ask(withheld=sb.password_service_withheld):
        why = withheld()
        answers.append(why)
        return why
    monkeypatch.setattr(sb, "password_service_withheld", ask)
    hung = password_bus(tmp_path, monkeypatch, "hung")
    dlg = _dialog(ui, "sandbox")
    began = time.monotonic()
    _call(dlg, "openFor", URL)
    assert time.monotonic() - began < 1 and _prop(dlg, "visible")                      # open at once,
    assert _hint(dlg, "Password service") == PASSWORD_SERVICE and not answered(be)      # with no words yet
    assert running(lambda: hung.exists(), 5)[0]                                         # the bus is being asked
    (tmp_path / "owned").mkdir()                                  # opened again while that ask waits,
    owned = password_bus(tmp_path / "owned", monkeypatch, "owned")  # on a bus that answers
    _call(dlg, "openFor", URL)
    want = PASSWORD_SERVICE + " " + NOT_OFFERED["owned"]
    came, gap = running(lambda: _hint(dlg, "Password service") == want, 15)
    assert came and owned.exists() and answers == ["held"], answers                     # its words, with its answer
    came, longest = running(lambda: len(answers) == 2, 15)        # the first ask ends with its five seconds,
    assert came and answers == ["held", "ask"], answers
    running(lambda: False, 0.3)
    assert _hint(dlg, "Password service") == want and answered(be)  # and its late answer is dropped
    assert max(gap, longest) < 1, (gap, longest)                  # the window turned all the while
    be.demoSandbox("ok")                                          # the tour shows a working system's, not
    assert _hint(dlg, "Password service") == PASSWORD_SERVICE     # what this machine's bus said before it


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
    _call(dlg, "setField", "folders", {"~/Projects": "rw"})      # a folder added at Strict (R17.2, R3-2)
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
                        "suggestsOff": info["suggestsOff"], "freshWarning": info["freshWarning"], "notYet": info.get("notYet", ""),
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
    # Review 2, F13: R17.13's warning that the app starts afresh came as a toast after the change was
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


_WHY_NOT_YET = {"bubblewrap missing": ("unsupported", "bubblewrap isn't installed, so apps run without a sandbox. Install it ("),
                "the setup pending": ("setup-needed", "this system needs a one-time setup before the sandbox can run (Set up… in Settings → Sandbox")}


@pytest.mark.parametrize("why", list(_WHY_NOT_YET))
@pytest.mark.parametrize("where", ["sandbox dialog", "install options"])
def test_where_save_cant_sandbox_an_app_yet_the_dialogs_say_when_the_choice_takes_effect(ui, be, tmp_path, monkeypatch, where, why):
    # #689's review, P4-B7: where Save can't sandbox an installed app that runs unsandboxed (no
    # bwrap a launcher in its folder finds, or the system's setup pending), the dialogs said
    # R17.13's warning that Save resets its settings, and Save then left it unsandboxed, the choice
    # saved, with no word that it waits. The owner decided (option B): the warning stays, and a line
    # beside it says the choice takes effect once the sandbox can run for the app, and why (R17.13).
    # Once the sandbox can run, the line goes, and Save sandboxes it. Install options' own line for
    # a pending setup ("installing asks whether to set it up now") isn't said where Save asks nothing.
    from test_sandbox_ui_surfaces import _seen
    _tarball_install(be, tmp_path)
    status, said_why = _WHY_NOT_YET[why]
    host = {"status": status}
    monkeypatch.setattr(sb, "have_tools", lambda: host["status"] != "unsupported")
    monkeypatch.setattr(sb, "support_status", lambda: {"status": host["status"], "tools": host["status"] != "unsupported",
                                                       "missing": ["bubblewrap"] if host["status"] == "unsupported" else [],
                                                       **({"toolsHint": sb.tools_hints(["bubblewrap"])["system"]}
                                                          if host["status"] == "unsupported" else {})})
    monkeypatch.setattr(be, "_install", lambda *a, **k: None)
    be.setSandbox(URL, {"template": "off"})
    warning = "Sandboxing Demo gives it an empty private home of its own, as if newly installed"
    note = "This choice takes effect once the sandbox can run for Demo, which runs unsandboxed until then: " + said_why

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
    assert not any(warning in t or "takes effect" in t for t in _seen(dlg))     # Off: nothing to say
    dlg = pick("strict")
    seen = _seen(dlg)
    assert any(warning in t for t in seen) and any(t.startswith(note) for t in seen), seen
    assert not any("installing asks" in t for t in seen), seen
    _press(dlg, "save")
    assert be._install_settings(URL)["sandbox"]["template"] == "strict"         # the choice is saved
    assert not be.sandboxInfo(URL)["active"] and not os.path.exists(tmp_path / "bin" / "apps" / "demo" / "run")    # and waits, as said
    host["status"] = "ok"                                                       # the sandbox can run for it now
    assert be.sandboxInfo(URL)["notYet"] == ""
    dlg = pick("strict")
    seen = _seen(dlg)
    assert any(warning in t for t in seen) and not any("takes effect" in t for t in seen), seen
    _press(dlg, "save")
    assert be.sandboxInfo(URL)["active"]
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


# ---------------------------------------------------------------- the command checkbox (CR1.9-31)

def _real_plan(be, monkeypatch, name, installed=""):
    """What Backend.planFor itself gives the install dialog for an app called `name`, with an
    AppImage as its one download (the other tests here build their plan by hand)."""
    from test_sandbox_backend import _plan_with
    _plan_with(be, monkeypatch, ["App-1.0-x86_64.AppImage"])
    monkeypatch.setattr(be, "_app", lambda url: {"url": URL, "name": name, "installed": installed, "version": "1.0", "updateTo": ""})
    return be.planFor(URL)


@pytest.mark.parametrize("name", ["python3", "Git", "ls", "Demo"])
def test_the_install_dialog_offers_no_command_checkbox_to_tick_for_a_name_no_link_is_made_for(ui, be, tmp_path, monkeypatch, name):
    # CR1.9-31: since CR1.5-31 no command link is made for an app named after a command (R4.3.1.3),
    # and the install's notice says why afterwards. The dialog didn't know: it still showed
    # "Command <app> in <folder>" as a checkbox to tick. planFor now carries the installer's own
    # answer, and with one the checkbox is disabled and unticked, the reason its tip; the option the
    # dialog sends is what it was, so the link is made once the name is free. A name that is free
    # leaves the checkbox as it was: ticked from the plan, and the user's to change.
    from PySide6.QtCore import QObject
    from appkata_core import install
    monkeypatch.setattr(sb, "have_tools", lambda: True)
    monkeypatch.setattr(sb, "support_status", lambda: {"status": "ok"})
    plan = _real_plan(be, monkeypatch, name)
    slug = install.slug(name)
    want = install.command_link_refusal(slug, str(tmp_path / "bin" / slug))
    assert plan["portable"].get("commandRefusal") == want and plan["portable"]["command"] == slug and plan["portable"]["commandLink"] is True
    assert bool(want) is (name != "Demo")
    if name in ("python3", "Git"):
        assert want == f"{slug} is a name kept for the system's own command"
    installs = []
    monkeypatch.setattr(be, "_install", lambda *a, **k: installs.append(a))
    dlg = _dialog(ui, "install")
    _call(dlg, "openWith", plan, False)
    item, box = dlg.findChild(QObject, "commandLink"), dlg.findChild(QObject, "commandLinkBox")
    assert item.property("refusal") == want and item.property("tip") == (f"No command will be added: {want}." if want else "")
    assert box.property("enabled") is (not want) and box.property("checked") is (not want)
    if not want:                                                   # free: the user's to turn off
        box.setProperty("checked", False)
        box.toggled.emit()
        assert _prop(dlg, "commandLink") is False
    _press(dlg, "save")
    assert len(installs) == 1 and installs[0][2]["commandLink"] is bool(want)       # refused: the option stays on


def test_an_installed_apps_own_command_link_does_not_disable_its_checkbox(ui, be, tmp_path, monkeypatch):
    # The other side of the name check: an installed app's own command link is on the PATH too
    # (~/bin comes first on it), and "Install options…" must not take it for someone else's command.
    from PySide6.QtCore import QObject
    monkeypatch.setattr(sb, "have_tools", lambda: True)
    monkeypatch.setattr(sb, "support_status", lambda: {"status": "ok"})
    target = _tarball_install(be, tmp_path)
    os.symlink(os.path.join(target, "1.0", "bin", "demo"), tmp_path / "bin" / "demo")
    monkeypatch.setenv("PATH", f"{tmp_path / 'bin'}{os.pathsep}{os.environ['PATH']}")
    plan = _real_plan(be, monkeypatch, "Demo", installed="1.0")
    assert plan["portable"].get("commandRefusal") == ""
    dlg = _dialog(ui, "install")
    _call(dlg, "openWith", plan, True)
    assert dlg.findChild(QObject, "commandLinkBox").property("enabled") is True
    # and someone else's `demo` there is no refusal either: the install stops at it with its error,
    # on the PATH as off it (R4.3.1.3; #689's review, P1-B2: it was taken for a command already on
    # this computer, the checkbox was unticked, and the install went on without a link)
    os.remove(tmp_path / "bin" / "demo")
    (tmp_path / "bin" / "demo").write_text("#!/bin/sh\n")
    (tmp_path / "bin" / "demo").chmod(0o755)
    plan = _real_plan(be, monkeypatch, "Demo", installed="1.0")
    assert plan["portable"]["commandRefusal"] == ""
    # while a `demo` elsewhere on the PATH is one
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    os.rename(tmp_path / "bin" / "demo", elsewhere / "demo")
    monkeypatch.setenv("PATH", f"{os.environ['PATH']}{os.pathsep}{elsewhere}")
    plan = _real_plan(be, monkeypatch, "Demo", installed="1.0")
    assert plan["portable"]["commandRefusal"] == f"demo is already a command on this computer ({elsewhere / 'demo'})"


# ---------------------------------------------------------------- an installed app's own folder (CR1.3-12)

def test_what_the_dialogs_show_of_an_installed_app_is_the_folder_it_is_in_not_the_one_settings_names_now(be, tmp_path, monkeypatch):
    # CR1.3-12, the owner's decision: an installed app keeps its folder through its updates, and only
    # a new install goes to the folder Settings names now. Whatever the backend says of an installed
    # app's folder was Settings' own: "Installs to" in Install options, the folders a sandbox's
    # chips call never shared, and the launcher's place. They are the app's own folder, from its
    # record, so the chips still judge a folder as the launcher does (round two, R9) once the
    # setting has changed; a new install's are Settings'.
    from appkata_core import install
    monkeypatch.setattr(sb, "have_tools", lambda: True)
    monkeypatch.setattr(sb, "support_status", lambda: {"status": "ok"})
    old, new = tmp_path / "bin" / "apps", tmp_path / "elsewhere"
    assert be._app_options(URL).root == be.portable().root == str(old)
    target = _tarball_install(be, tmp_path)
    rec = json.loads(be.db.one("SELECT record FROM installs WHERE url=?", (URL,))["record"])
    be.db.x("UPDATE installs SET record=? WHERE url=?", (json.dumps({**rec, "root": str(old)}), URL))      # as an install records it
    be._prefs["installDir"] = str(new)                               # the setting, changed in Settings
    assert be.portable().root == str(new) and be._app_options(URL).root == str(old)
    plan = _real_plan(be, monkeypatch, "Demo", installed="1.0")
    assert plan["portable"]["folder"] == str(old)
    # (The chips were told apart by their answer, which differed between the two folders. It no
    # longer does: the default install folder, which `old` is, is never shared whatever folder an
    # app is in, CR1.5-37. So the folder the backend judges by is read where it hands it over.)
    gs = sb.to_json({**sb.resolve_template("standard"), "folders": {str(old / "another-app"): "rw"}})
    chips, judged_by = sb.summary_chips, []
    monkeypatch.setattr(sb, "summary_chips", lambda gs, apps_root=None, *a, **k: judged_by.append(apps_root) or chips(gs, apps_root, *a, **k))
    assert be.summaryChips(gs, URL) == chips(gs, str(old)) and judged_by == [str(old)]
    monkeypatch.setattr(sb, "summary_chips", chips)
    _review(be, "online-app")
    be._regenerate_launcher(URL)
    rec = json.loads(be.db.one("SELECT record FROM installs WHERE url=?", (URL,))["record"])
    assert rec["launcher"] == os.path.join(target, "run") and os.path.exists(rec["launcher"]) and not os.path.lexists(new)
    assert be._heal_launchers() == []                                # and it is the launcher AppKata would write today
    # an app that isn't installed goes where Settings says
    be.db.x("DELETE FROM installs WHERE url=?", (URL,))
    assert be._app_options(URL).root == str(new) and _real_plan(be, monkeypatch, "Demo")["portable"]["folder"] == str(new)


# ---------------------------------------------------------------- Settings' Portable apps hint (CR1.9-33)

def test_settings_portable_apps_hint_says_when_its_settings_apply_as_r11_1_4_does():
    # CR1.9-33: since CR1.3-12 an installed app keeps its folder through its updates (R4.3.1), but the
    # hint still said "Changes apply to new installs and updates; apps already installed stay where
    # they are", as R4.3.1 used to. Which settings apply at an update is a rule the user reads in
    # Settings and in R11.1.4: the hint's words are R11.1.4's.
    import re
    root = os.path.join(os.path.dirname(__file__), "..")
    qml = open(os.path.join(root, "src", "appkata", "qml", "SettingsDialog.qml"), encoding="utf-8").read()
    section = qml[qml.index('Section { id: secPortable'):]
    hint = re.search(r'\+ " ([^"]+)" \}', section[:section.index("SettingRow")]).group(1)
    req = open(os.path.join(root, "docs", "requirements", "R11-settings.md"), encoding="utf-8").read()
    r11 = " ".join(req[req.index("R11.1.4. "):req.index("R11.1.4.1. ")].split())
    said = re.search(r'The group\'s hint says when its settings apply: "([^"]+)"', r11)
    assert said and said.group(1) == hint
    assert "updates; apps already installed stay where they are" not in hint
    for setting in ("Command links folder", "Keep older versions"):          # the two it names are rows of the section
        assert f'label: "{setting}"' in section
