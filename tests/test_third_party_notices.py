"""The license files the AppImage and the installer carry (the walk thru of 2026-10-30, item 1):
LICENSE.txt and THIRD-PARTY-NOTICES.txt, which scripts/third_party_notices.py writes into both builds
and checks there. docs/reviews/followups-license-files.md has the findings.

How they were missed: the builds were checked for what AppKata needs to run (Qt's plugins and QML,
no ICU on Windows, the libraries the AppImage takes from the host), and nothing read them for what
the licenses of the parts they carry ask of a copy: AppKata's GPL text, the LGPL and Qt's notices,
those of the libraries Python and Qt are built with. The AppImage carried Python's own LICENSE.txt
only because python-build-standalone's tarball has it; the Windows build carried none.
The class: a part a build carries whose license goes unmet. check takes every library in a build to
the one part whose section gives its license, so a library that comes in with a new input stops the
build until the notices give it, and a Qt library from a repository they don't list stops it too."""

import os
import re
import sys

import pytest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import third_party_notices as tpn  # noqa: E402

SP = "usr/python/lib/python3.14/site-packages/"
# a library of each kind each build carries, where the build puts it
LIBS = {
    "linux": {
        "usr/python/bin/python3.14": "python", "usr/python/lib/libpython3.14.so.1.0": "python",
        "usr/python/lib/python3.14/lib-dynload/_dbm.cpython-314-x86_64-linux-gnu.so": "python",
        "usr/python/lib/libtcl9.0.so": "python",
        SP + "PySide6/Qt/lib/libQt6Core.so.6": "qt", SP + "PySide6/Qt/lib/libQt6WaylandClient.so.6": "qt",
        SP + "PySide6/Qt/lib/libQt6EglFSDeviceIntegration.so.6": "qt", SP + "PySide6/Qt/lib/libQt6Lottie.so.6": "qt",
        SP + "PySide6/Qt/plugins/platforms/libqxcb.so": "qt", SP + "PySide6/Qt/qml/QtQuick/libqtquick2plugin.so": "qt",
        SP + "PySide6/Qt/libexec/qmlcachegen": "qt",
        SP + "PySide6/QtCore.abi3.so": "pyside", SP + "PySide6/libpyside6.abi3.so.6.11": "pyside",
        SP + "PySide6/Qt/plugins/designer/libPySidePlugin.so": "pyside", SP + "shiboken6/Shiboken.abi3.so": "pyside",
        SP + "PySide6/Qt/lib/libicuuc.so.73": "icu", SP + "PySide6/Qt/lib/libxcb-cursor.so.0": "xcb",
    },
    "windows": {
        "appkata.exe": "pyinstaller", "_internal/python314.dll": "python", "_internal/_ssl.pyd": "python",
        "_internal/libcrypto-3.dll": "python", "_internal/VCRUNTIME140.dll": "msvc",
        "_internal/PySide6/Qt6Core.dll": "qt", "_internal/PySide6/Qt6QuickTimeline.dll": "qt",
        "_internal/PySide6/plugins/platforms/qwindows.dll": "qt", "_internal/PySide6/qml/QtQuick/qtquick2plugin.dll": "qt",
        "_internal/PySide6/pyside6.abi3.dll": "pyside", "_internal/PySide6/QtCore.pyd": "pyside",
        "_internal/PySide6/MSVCP140.dll": "msvc", "_internal/shiboken6/Shiboken.pyd": "pyside",
        "_internal/shiboken6/VCRUNTIME140_1.dll": "msvc",
    },
}
MIT = ("Copyright (c) 2026 A. Author\n\nPermission is hereby granted, free of charge, to any person obtaining a copy of "
       "this software and associated documentation files (the \"Software\"), to deal in the Software without "
       "restriction.\n")


def _tree(path, platform, extra=()):
    for rel in list(LIBS[platform]) + list(extra):
        f = path / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes((b"\x7fELF" if platform == "linux" else b"MZ\x90\x00") + b"\0" * 60)
    (path / "usr" / "lib" / "appkata").mkdir(parents=True, exist_ok=True)
    (path / "README.txt").write_text("not a library\n")
    return path


def _built(path, platform, python_license=None):
    """What the builds copy from their inputs, as the real ones look."""
    if platform == "linux":
        (path / "xcb-util").mkdir(parents=True)
        (path / "xcb-util" / "libxcb-cursor0").write_text("Upstream-Name: xcb-util-cursor\n" + MIT)
    else:
        for d in ("python", "truststore", "pyinstaller"):
            (path / d).mkdir(parents=True)
        (path / "python" / "LICENSE.txt").write_text(python_license if python_license is not None else
                                                     "A. HISTORY OF THE SOFTWARE\n\nAdditional Conditions for this "
                                                     "Windows binary build\n-----\n\nThis program is linked with ...\n")
        (path / "truststore" / "LICENSE").write_text(MIT)
        (path / "pyinstaller" / "COPYING.txt").write_text("The PyInstaller licensing terms\n" + MIT)
    return path


@pytest.fixture(params=["linux", "windows"])
def made(request, tmp_path):
    platform = request.param
    tree = _tree(tmp_path / "tree", platform)
    tpn.write(platform, str(tree), str(_built(tmp_path / "built", platform)))
    return platform, tree


def _notices(platform, tree):
    return (tree / tpn.PLACE[platform] / "THIRD-PARTY-NOTICES.txt").read_text()


def test_a_build_without_the_files_fails_the_check(tmp_path):
    for platform in ("linux", "windows"):
        found = tpn.problems(platform, str(_tree(tmp_path / platform, platform)))
        assert f"no {os.path.join(tpn.PLACE[platform], 'LICENSE.txt')}" in found
        assert f"no {os.path.join(tpn.PLACE[platform], 'THIRD-PARTY-NOTICES.txt')}" in found


def test_with_them_written_it_passes(made):
    platform, tree = made
    assert tpn.problems(platform, str(tree)) == []
    assert (tree / tpn.PLACE[platform] / "LICENSE.txt").read_text() == open(os.path.join(ROOT, "LICENSE")).read()


def test_each_library_is_one_parts(tmp_path):
    for platform, libs in LIBS.items():
        for rel, key in libs.items():
            assert tpn.parts_of(rel, platform) == [key], rel


def test_a_library_no_part_takes_fails_it(made, tmp_path):
    platform, tree = made
    stray = "usr/lib/libstray.so.1" if platform == "linux" else "_internal/stray/stray.dll"
    _tree(tree, platform, [stray])
    assert tpn.problems(platform, str(tree)) == [f"{stray}: no part the notices give"]


def test_a_qt_library_of_a_repository_the_notices_dont_list_fails_it(made):
    platform, tree = made
    charts = SP + "PySide6/Qt/lib/libQt6Charts.so.6" if platform == "linux" else "_internal/PySide6/Qt6Charts.dll"
    _tree(tree, platform, [charts])
    assert tpn.problems(platform, str(tree)) == [
        f"{charts}: Qt's Charts, a module of none of the repositories the Qt section lists"]


def test_a_section_left_empty_or_another_license_fails_it(made):
    platform, tree = made
    notices = tree / tpn.PLACE[platform] / "THIRD-PARTY-NOTICES.txt"
    text = notices.read_text()
    title = f"Qt {tpn.pins()['PYSIDE']}"
    start = text.index(f"{tpn.RULE}\n{title}\n{tpn.RULE}\n\n") + len(f"{tpn.RULE}\n{title}\n{tpn.RULE}\n\n")
    notices.write_text(text[:start] + "\n" + text[text.index(tpn.RULE, start):])
    (tree / tpn.PLACE[platform] / "LICENSE.txt").write_text("MIT\n")
    found = tpn.problems(platform, str(tree))
    assert f"the notices have no section \"{title}\", or an empty one" in found
    assert "LICENSE.txt isn't AppKata's LICENSE" in found


def test_each_section_gives_the_license_texts(made):
    platform, tree = made
    text = _notices(platform, tree)
    sections = {title: " ".join(body.split()) for title, body in    # as one line: a phrase may wrap
                re.findall(rf"^{tpn.RULE}\n([^\n]+)\n{tpn.RULE}\n\n(.*?)(?=^{tpn.RULE}\n|\Z)", text, re.M | re.S)}
    p = tpn.pins()
    python, qt = sections[f"Python {p['PYTHON']}"], sections[f"Qt {p['PYSIDE']}"]
    assert "PYTHON SOFTWARE FOUNDATION LICENSE VERSION 2" in python and "libmpdec" in python and "expat" in python
    assert "GNU LESSER GENERAL PUBLIC LICENSE" in qt and "Version 3, 29 June 2007" in qt
    assert "The Qt Company GPL Exception 1.0" in qt and "libpng" in qt and "harfbuzz" in qt.lower()
    assert "GNU Lesser General Public License, version 3" in sections[f"PySide6 and Shiboken6 {p['PYSIDE']}"]
    if platform == "linux":
        assert "Apache License" in python and "zstd" in python and "sqlite" in python.lower()
        assert "UNICODE, INC. LICENSE AGREEMENT" in sections[f"ICU {p['ICU']}"]
        assert "xcb-util-cursor" in sections["xcb-util"]
    else:
        assert "Additional Conditions for this Windows binary build" in python and "zlib-ng" in python
        assert " ".join(MIT.split()) in sections[f"truststore {p['TRUSTSTORE']}"]
        assert "bootloader exception" in sections[f"PyInstaller's bootloader {p['PYINSTALLER']}"]
        assert "Distributable Code" in sections["The Microsoft Visual C++ runtime"]


def test_write_stops_when_a_build_input_lacks_its_text(tmp_path):
    tree = _tree(tmp_path / "tree", "windows")
    with pytest.raises(SystemExit, match="Additional Conditions"):
        tpn.write("windows", str(tree), str(_built(tmp_path / "built", "windows", python_license="no conditions\n")))
    with pytest.raises(SystemExit, match="xcb-util"):
        tpn.write("linux", str(_tree(tmp_path / "linux", "linux")), str(tmp_path / "nothing"))


def test_the_texts_are_of_the_versions_the_builds_pin():
    # a version moved without `scripts/third_party_notices.py refresh`: the notices would name and
    # quote another Qt, Python or Wine image than the build carries
    made, p = tpn.sources(), tpn.pins()
    assert {k: made.get(k) for k in ("PYSIDE", "PYTHON_BUILD", "PYWINE_IMAGE")} == \
        {k: p[k] for k in ("PYSIDE", "PYTHON_BUILD", "PYWINE_IMAGE")}, "run scripts/third_party_notices.py refresh"
    for name in ("qt.txt", "pyside.txt", "python.txt", "python-linux.txt", "python-windows.txt", "icu.txt", "msvc-runtime.txt"):
        assert os.path.getsize(os.path.join(tpn.LICENSES, name)) > 400, name


def test_both_builds_write_and_check_them():
    for script, platform in (("build-appimage.sh", "linux"), ("build-windows.sh", "windows")):
        text = open(os.path.join(ROOT, "scripts", script)).read()
        assert re.search(rf"third_party_notices\.py\" write {platform} ", text), script
        assert re.search(rf"third_party_notices\.py\" check {platform} ", text), script
