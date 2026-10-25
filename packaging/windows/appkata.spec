# PyInstaller spec: one folder, AppKata/appkata.exe (requirement 1.6).
# Built under Wine by scripts/build-windows.sh.
import os
import sys

from PyInstaller.utils.hooks import collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, "..", ".."))
SRC = os.path.join(ROOT, "src")
ICON = os.path.join(SPECPATH, "appkata.ico")
sys.path.insert(0, SRC)          # for collect_submodules

# every module of both packages: some are imported lazily (inside functions), e.g. the tour
hidden = collect_submodules("appkata") + collect_submodules("appkata_core") + ["truststore"]

a = Analysis([os.path.join(SPECPATH, "appkata_gui.py")], pathex=[SRC],
             datas=[(os.path.join(SRC, "appkata", "qml"), "appkata/qml")],
             hiddenimports=hidden,
             excludes=["tkinter", "unittest", "pydoc", "pytest", "PySide6.Qt3DCore", "PySide6.Qt3DRender",
                       "PySide6.QtPdf", "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtMultimedia"])
exe = EXE(PYZ(a.pure), a.scripts, [], exclude_binaries=True, name="appkata",
          console=False, icon=ICON, version=None)
COLLECT(exe, a.binaries, a.datas, name="AppKata")
