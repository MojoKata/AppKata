"""The theme the UI says is chosen is the theme it shows.

How it slipped past: Settings' Theme row and the ⋮ menu each worked the choice out again from the
setting (themeOverride || prefs.theme), while Main.qml decides the theme shown (Theme.mode) and the
screenshot tour sets that alone. So every light screenshot showed "Dark" chosen. The class is a
fact the UI shows decided in more than one place: here, which theme. Main.qml decides it once;
everything else reads Theme.mode.
"""

import glob
import os
import re

import pytest

from test_dialog_contract import qapp                   # noqa: F401
from test_sandbox_backend import be                    # noqa: F401

QML = os.path.join(os.path.dirname(__file__), "..", "src", "appkata", "qml")


def test_only_main_qml_decides_the_theme():
    others = {}
    for path in glob.glob(os.path.join(QML, "*.qml")):
        if os.path.basename(path) == "Main.qml":
            continue
        with open(path, encoding="utf-8") as f:
            hits = [n for n, line in enumerate(f, 1) if re.search(r"themeOverride|prefs\.theme|\bp\.theme\b", line)]
        if hits:
            others[os.path.basename(path)] = hits
    assert others == {}, f"read the theme shown (Theme.mode), not the setting: {others}"


@pytest.mark.parametrize("shown, setting", [("light", "dark"), ("dark", "light"), ("system", "light")])
def test_the_theme_row_says_the_theme_shown(qapp, be, shown, setting):
    pytest.importorskip("PySide6")
    from PySide6 import QtQuick  # noqa: F401
    from PySide6.QtCore import QCoreApplication, QEvent, QObject, QUrl
    from PySide6.QtQml import QQmlApplicationEngine
    from test_dialog_contract import _call
    be.setPref("theme", setting)
    engine = QQmlApplicationEngine()
    for name, value in (("backend", be), ("appVersion", "test"), ("themeOverride", ""), ("tourMode", True), ("platformOs", "linux")):
        engine.rootContext().setContextProperty(name, value)
    engine.load(QUrl.fromLocalFile(os.path.join(os.path.dirname(__file__), "qml", "ThemeHarness.qml")))
    root = engine.rootObjects()[0]
    try:
        _call(root, "showTheme", shown)                    # as the tour sets it
        dlg = root.findChild(QObject, "settings")
        _call(dlg, "open")
        choice = dlg.findChild(QObject, "themeChoice")
        assert choice is not None and choice.property("mode") == shown
    finally:
        root.deleteLater()
        engine.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
