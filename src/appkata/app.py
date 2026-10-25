"""Application startup: window, tray icon (requirement 1.7) and the screenshot tour."""

from __future__ import annotations

import argparse
import os
import signal
import sys

from appkata_core import __version__

QML_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "qml")


def main(argv: list[str] | None = None) -> int:
    if os.name == "nt" and sys.stdout is None:      # the windowed appkata.exe: print to the console it was started from
        import ctypes
        if ctypes.windll.kernel32.AttachConsole(-1):
            sys.stdout = open("CONOUT$", "w")
            sys.stderr = open("CONOUT$", "w")
    ap = argparse.ArgumentParser(prog="appkata", description="AppKata: a FOSS app store built on git.")
    ap.add_argument("--data-dir", help="use this folder for the database and caches (tests and demos)")
    ap.add_argument("--theme", choices=["system", "dark", "light"], help="override the saved theme for this run")
    ap.add_argument("--tray", action="store_true", help="start in the tray without opening the window")
    ap.add_argument("--tour", metavar="DIR", help="save screenshots of each screen to DIR and exit")
    ap.add_argument("--tour-only", default="", metavar="NAMES", help="with --tour: only these screens (comma-separated)")
    ap.add_argument("--install-self", action="store_true",
                    help="install this AppImage into the install folder and the app menu, then exit (requirement 2.11.3.1)")
    ap.add_argument("--version", action="version", version=f"appkata {__version__}")
    ap.add_argument("link", nargs="?", default="", help="an appkata://add/<url> link (requirement 11.3)")
    a, qt_args = ap.parse_known_args(argv)
    if a.data_dir:
        os.environ["APPKATA_DATA"] = os.path.abspath(a.data_dir)

    if a.install_self:          # before the one-AppKata hand-off (1.9): it never reaches a running AppKata
        return install_self()

    if a.tour:
        if os.name != "nt":
            os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        os.environ.setdefault("QT_QUICK_BACKEND", "software")
    os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

    from PySide6.QtCore import QMetaObject, Q_ARG, QTimer, QUrl
    from PySide6.QtGui import QIcon
    from PySide6.QtQml import QQmlApplicationEngine
    from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon
    from PySide6 import QtQuick  # noqa: F401  (registers QQuickWindow for rootObjects())

    from .backend import Backend
    from appkata_core import applog
    import logging
    applog.setup()
    from PySide6.QtCore import QtMsgType, qInstallMessageHandler
    qtlog = logging.getLogger("appkata.qt")
    levels = {QtMsgType.QtDebugMsg: logging.DEBUG, QtMsgType.QtInfoMsg: logging.INFO, QtMsgType.QtWarningMsg: logging.WARNING,
              QtMsgType.QtCriticalMsg: logging.ERROR, QtMsgType.QtFatalMsg: logging.CRITICAL}

    def qt_messages(mode, context, message):        # Qt and QML warnings go to the App log (requirement 14.2)
        if message.startswith("qt.qpa"):
            return
        qtlog.log(levels.get(mode, logging.INFO), "%s", message)
        if mode != QtMsgType.QtDebugMsg:
            print(message, file=sys.stderr)
    qInstallMessageHandler(qt_messages)

    if os.name == "nt":
        import ctypes
        from appkata_core.platform import quiet_subprocesses, use_system_certificates
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("AppKata.AppKata")    # requirement 15.14
        quiet_subprocesses()
        use_system_certificates()
    app = QApplication([sys.argv[0]] + qt_args)
    app.setApplicationName("AppKata")
    app.setApplicationVersion(__version__)
    app.setOrganizationName("AppKata")
    app.setDesktopFileName("appkata")
    icon = QIcon(os.path.join(QML_DIR, "assets", "appkata.svg"))
    app.setWindowIcon(icon)
    app.setQuitOnLastWindowClosed(False)            # closing the window leaves AppKata in the tray (1.7.1)
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    from appkata_core.desktop import parse_link
    link = parse_link(a.link)
    server = None
    if not a.tour:          # one AppKata at a time (requirement 1.9)
        from .single import hand_over, listen
        if hand_over({"link": link, "tray": bool(a.tray)}):
            return 0
        server = listen()

    backend = Backend(heal=not a.tour)
    engine = QQmlApplicationEngine()
    ctx = engine.rootContext()
    ctx.setContextProperty("backend", backend)
    ctx.setContextProperty("appVersion", __version__)
    ctx.setContextProperty("themeOverride", a.theme or "")
    ctx.setContextProperty("tourMode", bool(a.tour))
    ctx.setContextProperty("platformOs", sys.platform)
    engine.load(QUrl.fromLocalFile(os.path.join(QML_DIR, "Main.qml")))
    if not engine.rootObjects():
        return 1
    win = engine.rootObjects()[0]
    frame = None
    if os.name == "nt" and not a.tour:          # requirement 15.13
        try:
            from .winframe import WinFrame
            frame = WinFrame(win)
            app.installNativeEventFilter(frame)
        except Exception:       # noqa: BLE001  (a plain frameless window still works)
            logging.getLogger("appkata").exception("window frame")
    win.setProperty("windowButtons", os.name == "nt")

    def show_window(view: str = "") -> None:
        if view:
            win.setProperty("view", view)
        win.show(); win.raise_(); win.requestActivate()

    tray = None
    if QSystemTrayIcon.isSystemTrayAvailable() and not a.tour:
        tray = QSystemTrayIcon(icon, app)
        tray.setToolTip("AppKata")
        menu = QMenu()
        upd = menu.addAction("")
        upd.triggered.connect(lambda: show_window("apps"))
        menu.addAction("Open AppKata").triggered.connect(lambda: show_window())
        menu.addAction("Check for updates").triggered.connect(backend.sync)
        menu.addSeparator()
        menu.addAction("Quit AppKata").triggered.connect(lambda: QMetaObject.invokeMethod(win, "requestQuit"))   # asks while installing (1.7.3)

        def refresh_tray() -> None:
            n = backend.updateCount
            upd.setText(f"{n} update{'s' if n != 1 else ''} available" if n else "No updates")
            upd.setEnabled(bool(n))
        backend.changed.connect(refresh_tray)
        refresh_tray()
        tray.setContextMenu(menu)
        tray.activated.connect(lambda reason: show_window() if reason == QSystemTrayIcon.ActivationReason.Trigger else None)
        backend.notify.connect(lambda title, text: tray.showMessage(title, text, icon))
        tray.messageClicked.connect(lambda: show_window("apps"))
        tray.show()
    else:
        app.setQuitOnLastWindowClosed(True)          # no tray: closing the window quits
    win.setProperty("hasTray", tray is not None)

    if a.tour:
        from .tour import Tour
        tour = Tour(win, backend, a.tour, only=a.tour_only)
        tour.start()
    elif a.tray and tray is not None:
        win.hide()
    else:
        show_window()
    def open_link(url: str) -> None:
        QTimer.singleShot(400, lambda: QMetaObject.invokeMethod(win, "openDeepLink", Q_ARG("QVariant", url)))
    if link:
        open_link(link)
    if server is not None:
        def from_other(msg: dict) -> None:     # a second start hands over its link (requirement 1.9)
            if msg.get("link"):
                show_window("sources")
                open_link(msg["link"])
            elif not msg.get("tray"):
                show_window()
        server.received.connect(from_other)
    return app.exec()


def install_self() -> int:
    """`appkata --install-self`: what Install does in the first-start dialog, without asking."""
    from appkata_core import selfinstall
    from appkata_core.db import DB
    from appkata_core.install import Portable
    from appkata_core.platform import data_dir
    from . import prefs as prefs_mod
    if not selfinstall.running_appimage():
        print("appkata: --install-self works only when running as an AppImage", file=sys.stderr)
        return 1
    p = prefs_mod.load()
    root = Portable(folder=p.get("installDir") or "").root
    os.makedirs(data_dir(), exist_ok=True)
    try:
        rec = selfinstall.install_self(DB(os.path.join(data_dir(), "appkata.db")), root)
    except OSError as e:
        print(f"appkata: couldn't install AppKata: {e}", file=sys.stderr)
        return 1
    print(rec["exec"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
