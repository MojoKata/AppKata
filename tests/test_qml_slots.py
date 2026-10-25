"""Every Backend slot that takes an object or array from QML, called from QML.

With PySide 6.9 (the venv and the AppImage build) a JS object or array reaches a "QVariant" slot
as a QJSValue, which dict()/list() can't iterate: the install dialog's Save raised TypeError inside
installWith and did nothing (found by tests/test_dialog_contract.py). The same shape existed in
six more slots. Each is called here the way QML calls it -- a QML expression evaluated in an
engine with the real Backend -- and the Python side must see plain data.
"""

import json
import os

import pytest

pytest.importorskip("PySide6")

from test_sandbox_backend import URL, be        # noqa: E402,F401


@pytest.fixture
def qml(be):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from PySide6.QtQml import QQmlApplicationEngine, QQmlExpression
    QApplication.instance() or QApplication([])
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("backend", be)
    engine.loadData(b"import QtQuick\nItem {}")
    root = engine.rootObjects()[0]

    def call(js: str):
        e = QQmlExpression(engine.rootContext(), root, js)
        out = e.evaluate()
        assert not e.hasError(), e.error().toString()
        return out
    yield call
    root.deleteLater()
    engine.deleteLater()


def test_install_with_from_qml(qml, be, monkeypatch):
    got = []
    monkeypatch.setattr(be, "_install", lambda *a, **k: got.append(a[2]))
    monkeypatch.setattr(be, "_app", lambda url: {"url": URL, "name": "Demo", "installed": ""})
    qml(f"backend.installWith('{URL}', {{kind: 'appimage', appMenu: true, sandbox: {{template: 'strict', overrides: {{}}}}, scope: undefined}})")
    assert got and got[0]["kind"] == "appimage" and got[0]["sandbox"] == {"template": "strict", "overrides": {}}
    assert be._install_settings(URL)["sandbox"]["template"] == "strict"


def test_set_pref_from_qml(qml, be):
    qml("backend.setPref('sort', 'name'); backend.setPref('columns', {a: 1, b: [1, 2]})")
    assert be._prefs["sort"] == "name" and be._prefs["columns"] == {"a": 1, "b": [1, 2]}


def test_source_settings_from_qml(qml, be, monkeypatch):
    import threading
    monkeypatch.setattr(threading.Thread, "start", lambda self: None)       # no sync over the network
    qml(f"backend.addSourceWith('{URL}', false, {{assetFilter: 'amd64'}})")
    def saved():        # _clean_source_settings files the filter under this platform's key
        return json.loads(be.db.one("SELECT settings FROM sources WHERE url=?", (URL,))["settings"])
    assert "amd64" in saved()["asset_filters"].values()
    qml(f"backend.setSourceSettings('{URL}', {{assetFilter: 'arm64'}})")
    assert "arm64" in saved()["asset_filters"].values() and "amd64" not in saved()["asset_filters"].values()


def test_channel_options_from_qml(qml, be, monkeypatch):
    got = []
    monkeypatch.setattr(be, "_install_channel", lambda url, option, updates, **k: got.append((option, updates, k)))
    qml(f"backend.addFlathubAndInstall('{URL}', {{channel: 'flatpak', id: 'org.example.Demo'}}, 'system')")
    qml(f"backend.installChannelConfirmed('{URL}', {{channel: 'package', name: 'demo'}}, 'appkata')")
    assert got[0][0] == {"channel": "flatpak", "id": "org.example.Demo"} and got[0][2] == {"add_flathub": True}
    assert got[1][0] == {"channel": "package", "name": "demo"} and got[1][2] == {"confirmed": True}


def test_save_review_from_qml(qml, be, monkeypatch):
    import threading
    from types import SimpleNamespace
    from appkata_core import review, sync
    monkeypatch.setattr(threading.Thread, "start", lambda self: self.run())   # the worker, inline
    monkeypatch.setattr(be, "reviewData", lambda url: {})
    monkeypatch.setattr(be, "_app", lambda url: {"url": URL, "name": "Demo"})
    monkeypatch.setattr(sync, "sync_own", lambda *a, **k: None)
    monkeypatch.setattr(sync, "own_trust", lambda *a, **k: None)
    got = []

    def save(path, name, url, tags, trust, rating, *rest):
        got.append((tags, trust, rating))
        return SimpleNamespace(saved=True, committed="", signed=False, pushed=False, error="")
    monkeypatch.setattr(review, "save", save)
    qml(f"backend.saveReview('{URL}', ['editor', 'markdown'], 4, 5, 'Nice.', false, false, '', false)")
    assert got == [(["editor", "markdown"], 4, 5)]


def test_demo_busy_from_qml(qml, be):
    qml(f"backend.demoBusy('{URL}', {{phase: 'Downloading', progress: 0.5}})")
    assert be._busy[URL]["phase"] == "Downloading"
