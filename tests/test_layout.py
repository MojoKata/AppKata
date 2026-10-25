"""Nothing a dialog shows runs past its card, whatever the length of what it shows (review 3, R3-22).

How R3-22 slipped past: Install options puts the command's folder in a Row of checkboxes, and a Row
never wraps. On Linux the folder is ~/.local/bin and the Row fits; on Windows it is a full path, and
"Stable name link" was drawn past the dialog's edge, over App Detail. The tour saved it as a
screenshot on Windows from the first release on, and nothing read where a text ends. layout.py
does: the tour runs it on every screen it saves, and here the dialogs are opened with the long
values a real machine gives (Windows' paths, long names), and checked the same way.
"""

import pytest

pytest.importorskip("PySide6")

from PySide6 import QtQuick                                         # noqa: E402,F401  (rootObjects() as a QQuickWindow)

from appkata import layout                                          # noqa: E402
from test_dialog_contract import HARNESS, _call, qapp               # noqa: E402,F401
from test_sandbox_backend import URL, be                            # noqa: E402,F401

HOME = "C:\\Users\\someone"
BIN = HOME + "\\AppData\\Local\\AppKata\\bin"
PROGRAMS = HOME + "\\AppData\\Local\\Programs"


def _plan(command="keepassxc", folder=PROGRAMS, command_dir=BIN, name="KeePassXC", windows=True):
    """Install options for a release with a portable zip and an .msi, as planFor gives it."""
    cards = [{"channel": "release", "name": f"{name}-2.7.12-Win64.zip", "kind": "zip", "category": "portable", "size": 35_000_000,
              "label": "zip archive", "scopes": ["me", "everyone"], "admin": False, "manager": "its installer", "exeKind": ""},
             {"channel": "release", "name": f"{name}-2.7.12-Win64.msi", "kind": "msi", "category": "system", "size": 36_000_000,
              "label": ".msi installer", "scopes": ["me", "everyone"], "admin": True, "manager": "its installer", "exeKind": ""}]
    plan = {"url": URL, "name": name, "version": "2.7.12", "chosen": 0, "ask": True, "reasons": ["both"],
            "os": "Windows x86_64" if windows else "Linux x86_64", "candidates": cards, "cards": cards, "updates": "",
            "portable": {"folder": folder, "appMenu": True, "commandLink": True, "stableName": True, "commandDir": command_dir,
                         "command": command, "keep": 2, "recommendedBy": ""},
            "autoUpdate": False, "autoUpdateBy": "", "sandbox": {"applicable": False}}
    if windows:
        plan["windows"] = {"scope": "me", "motw": False, "folderEveryone": "C:\\Program Files", "folderMe": folder}
    return plan


PLANS = {
    "Windows (W02, C11)": _plan(),
    "Windows, installed for everyone": dict(_plan(), windows={"scope": "everyone", "motw": True, "folderEveryone": "C:\\Program Files",
                                                              "folderMe": PROGRAMS}),
    "Linux, a long command and folder": _plan(command="org.example.a-rather-long-application-identifier",
                                              folder="/home/someone/an/unusually/deep/folder/for/portable/applications",
                                              command_dir="/home/someone/.local/share/bin/for/commands", windows=False),
}


@pytest.fixture
def window(qapp, be):
    from PySide6.QtCore import QCoreApplication, QEvent, QUrl
    from PySide6.QtQml import QQmlApplicationEngine
    engine = QQmlApplicationEngine()
    for name, value in (("backend", be), ("appVersion", "test"), ("themeOverride", ""), ("tourMode", False), ("platformOs", "linux")):
        engine.rootContext().setContextProperty(name, value)
    engine.load(QUrl.fromLocalFile(HARNESS))
    assert engine.rootObjects(), "the dialog harness did not load"
    root = engine.rootObjects()[0]
    yield root
    root.deleteLater()
    engine.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def _faults(window):
    """Faults once the layout has settled: a Column places its children in one frame and takes their
    height in the next, so render until two frames agree (the tour waits a second or more)."""
    from PySide6.QtCore import QCoreApplication
    last = None
    for _ in range(20):
        QCoreApplication.processEvents()
        window.grabWindow()
        now = [f["line"] for f in layout.faults(window)]
        if now == last:
            return now
        last = now
    return last


@pytest.mark.parametrize("which", list(PLANS))
def test_install_options_keeps_every_text_inside_its_card(window, which):
    from PySide6.QtCore import QObject
    dlg = window.findChild(QObject, "install")
    _call(dlg, "openWith", PLANS[which], True)
    assert dlg.property("opened"), which
    faults = _faults(window)
    assert not faults, which + ":\n" + "\n".join(faults)


CASES = b"""
import QtQuick
Window {
    width: 400; height: 300; visible: true
    Rectangle {
        objectName: "card"; x: 10; y: 10; width: 200; height: 90; color: "white"     // room for two lines in any font
        Text { text: "a text much longer than the card it sits in, and unwrapped" }
        Text { y: 20; width: parent.width; elide: Text.ElideRight; text: "elided: a text much longer than the card it sits in" }
        Text { y: 40; width: parent.width; wrapMode: Text.Wrap; text: "wrapped: long enough to take a second line in it" }
    }
    Rectangle {
        x: 10; y: 120; width: 200; height: 60; color: "white"
        Flickable { anchors.fill: parent; clip: true; contentY: 100; contentHeight: 400
                    Text { text: "scrolled out of view, past the card's top" }
                    Rectangle { y: 300; width: 150; height: 30; color: "grey"
                                Text { text: "a card scrolled out of view, still too narrow for this" } } }
    }
}
"""


def test_the_check_flags_only_a_text_drawn_past_its_card(qapp):
    # its own proof: the unwrapped text is flagged, and so is one too wide for a card scrolled out of
    # view (the card is laid out wrong whether it shows or not); an elided one, a wrapped one and a
    # bare one scrolled out of view are not
    from PySide6.QtCore import QUrl
    from PySide6.QtQml import QQmlComponent, QQmlEngine
    engine = QQmlEngine()
    comp = QQmlComponent(engine)
    comp.setData(CASES, QUrl())
    win = comp.create()
    assert win is not None, comp.errors()
    faults = _faults(win)
    assert len(faults) == 2, faults
    assert faults[0].startswith("'a text much longer") and "runs past card: right by" in faults[0], faults
    assert faults[1].startswith("'a card scrolled out of view") and "right by" in faults[1], faults
    win.deleteLater()
