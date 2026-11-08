"""What the AppImage leaves out (packaging/appimage-trim.txt, scripts/appimage_trim.py).

Qt and Python load most of what they use only when it's first used: a QML module when the screen
that imports it is built, a plugin in the session that wants it, a dialog when it opens. A part
the build leaves out that AppKata needs after all fails there, and only there. The class: a part
left out that AppKata loads at run time. scripts/test-appimage.sh's trace step catches it in the
built AppImage (scripts/appimage_trace.sh, then `appimage_trim.py check`); the build catches a
kept library that links a left-out one, and a line that names nothing any more. These tests hold
the working out of both, and catch the commonest case before any build: a QML module or a PySide6
module AppKata imports that the list leaves out."""

import importlib.util
import os
import re

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
SITE = "usr/python/lib/python3.14/site-packages"
A = "/tmp/squashfs-root"


def _mod():
    spec = importlib.util.spec_from_file_location("appimage_trim", os.path.join(ROOT, "scripts", "appimage_trim.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_a_line_names_a_path_or_a_folder_it_is_in_and_a_star_stays_within_a_part():
    m = _mod()
    pats = ["usr/python/lib/python*/tkinter", f"{SITE}/PySide6/Qt/lib/libQt6Test.*"]
    assert m.match(pats, "usr/python/lib/python3.14/tkinter") == pats[0]
    assert m.match(pats, "usr/python/lib/python3.14/tkinter/ttk.py") == pats[0]
    assert m.match(pats, f"{SITE}/PySide6/Qt/lib/libQt6Test.so.6") == pats[1]
    assert m.match(pats, f"{SITE}/PySide6/Qt/lib/libQt6TestLib.so.6") is None
    assert m.match(pats, "usr/python/lib/python3.14/site-packages/tkinter") is None      # * doesn't cross a /
    assert m.match(pats, "usr/python/lib/python3.14/tkinterx") is None


def _tree(tmp_path, files):
    for rel in files:
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x")
    return str(tmp_path)


def test_the_plan_names_each_topmost_path_and_every_line_that_names_nothing(tmp_path):
    m = _mod()
    appdir = _tree(tmp_path, ["a/tk/x.py", "a/tk/y/z.py", "a/keep.py", "lib/libQt6Sql.so.6"])
    out, stale = m.plan(appdir, ["a/tk", "lib/libQt6Sql.*", "lib/libQt63D*"])
    assert out == ["a/tk", "lib/libQt6Sql.so.6"]
    assert stale == ["lib/libQt63D*"]


def test_a_kept_library_that_links_a_left_out_one_is_a_broken_link():
    m = _mod()
    kept = {"lib/libQt6EglFsKmsSupport.so.6": ["libQt6EglFSDeviceIntegration.so.6", "libc.so.6"],
            "lib/libQt6Quick.so.6": ["libQt6Qml.so.6"]}
    gone = {"libQt6EglFSDeviceIntegration.so.6", "libQt6Sql.so.6"}
    still = {"libQt6Qml.so.6", "libQt6EglFsKmsSupport.so.6", "libQt6Quick.so.6"}
    assert m.broken_links(kept, gone, still) == [("lib/libQt6EglFsKmsSupport.so.6", "libQt6EglFSDeviceIntegration.so.6")]
    assert m.broken_links(kept, gone, still | {"libQt6EglFSDeviceIntegration.so.6"}) == []   # another copy is kept


def test_apply_removes_nothing_when_the_list_breaks_a_link_or_names_nothing(tmp_path, monkeypatch):
    m = _mod()
    appdir = _tree(tmp_path, ["lib/libA.so.6", "lib/libB.so.6", "lib/tool"])
    monkeypatch.setattr(m, "elf_needed", lambda f: ["libB.so.6"] if f.endswith("libA.so.6") else [])
    monkeypatch.setattr(m, "patterns", lambda: ["lib/libB.*"])
    assert m.apply(appdir) == 1
    assert os.path.exists(os.path.join(appdir, "lib/libB.so.6"))
    monkeypatch.setattr(m, "patterns", lambda: ["lib/tool", "lib/gone"])
    assert m.apply(appdir) == 1
    assert os.path.exists(os.path.join(appdir, "lib/tool"))
    monkeypatch.setattr(m, "patterns", lambda: ["lib/tool"])
    assert m.apply(appdir) == 0
    assert not os.path.exists(os.path.join(appdir, "lib/tool"))
    assert os.path.exists(os.path.join(appdir, "lib/libB.so.6"))


# lines as strace -f -y writes them (scripts/appimage_trace.sh); the first two from a real trace
QT = f"{A}/{SITE}/PySide6/Qt"
LINES = [
    f'18    mmap(0x7fc766d2c000, 2183168, PROT_READ|PROT_EXEC, MAP_PRIVATE|MAP_FIXED|MAP_DENYWRITE, 3<{A}/{SITE}/PySide6/QtCore.abi3.so>, 0xbb000) = 0x7fc766d2c000',
    f'26    openat(AT_FDCWD</tmp>, "{QT}/qml/QtQuick/Window/qmldir", O_RDONLY|O_CLOEXEC) = 13<{QT}/qml/QtQuick/Window/qmldir>',
    # Qt reads every plugin in a folder for its metadata: opened, mapped to read, never run
    f'26    openat(AT_FDCWD</tmp>, "{QT}/plugins/platforms/libqvnc.so", O_RDONLY|O_CLOEXEC) = 14<{QT}/plugins/platforms/libqvnc.so>',
    f'26    mmap(NULL, 4096, PROT_READ, MAP_PRIVATE, 14<{QT}/plugins/platforms/libqvnc.so>, 0) = 0x7f0000000000',
    f'26    statx(AT_FDCWD</tmp>, "{QT}/plugins/platforms/libqeglfs.so", AT_STATX_SYNC_AS_STAT, STATX_ALL, {{}}) = 0',
    # looked for and missing: a library the loader wanted, a QML module an import wanted
    f'27    openat(AT_FDCWD</tmp>, "{QT}/lib/libQt6QuickParticles.so.6", O_RDONLY|O_CLOEXEC) = -1 ENOENT (No such file or directory)',
    f'27    openat(AT_FDCWD</tmp>, "{QT}/qml/QtQuick/Controls/Material/qmldir" <unfinished ...>',
    '30    openat(AT_FDCWD</tmp>, "/etc/hosts", O_RDONLY) = 3</etc/hosts>',
    '27    <... openat resumed>) = -1 ENOENT (No such file or directory)',
    f'28    openat(AT_FDCWD</tmp>, "{QT}/lib/libQt6Lottie.so.6" <unfinished ...>',
    '28    <... openat resumed>) = -1 ENOENT (No such file or directory)',
    f'29    openat(9<{QT}/qml/QtQuick>, "Shapes/qmldir", O_RDONLY) = 10<{QT}/qml/QtQuick/Shapes/qmldir>',
    f'18    execve("{A}/AppRun", ["{A}/AppRun", "--tour"], 0x7ffc10053910 /* 13 vars */) = 0',
    f'18    openat(AT_FDCWD</tmp>, "{A}/usr/python/bin/../lib/glibc-hwcaps/x86-64-v4/libpthread.so.0", O_RDONLY) = -1 ENOENT (No such file or directory)',
]


def test_the_trace_counts_what_ran_what_was_read_and_what_was_looked_for():
    used = _mod().used(LINES)
    assert f"{SITE}/PySide6/QtCore.abi3.so" in used
    assert f"{SITE}/PySide6/Qt/qml/QtQuick/Window/qmldir" in used
    assert f"{SITE}/PySide6/Qt/lib/libQt6QuickParticles.so.6" in used
    assert f"{SITE}/PySide6/Qt/qml/QtQuick/Controls/Material/qmldir" in used      # interrupted, then missing
    assert f"{SITE}/PySide6/Qt/lib/libQt6Lottie.so.6" in used
    assert f"{SITE}/PySide6/Qt/qml/QtQuick/Shapes/qmldir" in used                 # relative to a folder
    assert "AppRun" in used
    assert "usr/python/lib/glibc-hwcaps/x86-64-v4/libpthread.so.0" in used
    assert f"{SITE}/PySide6/Qt/plugins/platforms/libqvnc.so" not in used         # metadata only
    assert f"{SITE}/PySide6/Qt/plugins/platforms/libqeglfs.so" not in used
    assert not any(p.startswith("/") or p.startswith("etc") for p in used)


def test_check_fails_when_a_run_used_a_file_the_list_leaves_out(tmp_path, monkeypatch, capsys):
    m = _mod()
    (tmp_path / "trace-tour.txt").write_text("\n".join(LINES) + "\n")
    monkeypatch.setattr(m, "patterns", lambda: [f"{SITE}/PySide6/Qt/plugins/platforms/libqvnc.so"])
    assert m.check(str(tmp_path)) == 0
    monkeypatch.setattr(m, "patterns", lambda: [f"usr/python/lib/python*/site-packages/PySide6/Qt/qml/QtQuick/Controls/Material"])
    assert m.check(str(tmp_path)) == 1
    assert "used by tour" in capsys.readouterr().out
    monkeypatch.setattr(m, "tolerated", lambda: {"usr/python/lib/python*/site-packages/PySide6/Qt/qml/QtQuick/Controls/Material"})
    assert m.check(str(tmp_path)) == 0                       # looked for, and AppKata does without
    assert "does without" in capsys.readouterr().out


def test_a_line_marked_with_a_question_mark_is_left_out_and_tolerated(tmp_path):
    m = _mod()
    f = tmp_path / "list.txt"
    f.write_text("# a comment\na/b\n? a/c   # Qt looks for it\n")
    assert m.patterns(str(f)) == ["a/b", "a/c"]
    assert m.tolerated(str(f)) == {"a/c"}


def _qml_imports():
    out = set()
    for root, _, files in os.walk(os.path.join(ROOT, "src")):
        for n in files:
            if n.endswith(".qml"):
                with open(os.path.join(root, n), encoding="utf-8") as f:
                    out |= set(re.findall(r"^\s*import\s+([A-Z][\w.]*)", f.read(), re.M))
    return out


def _pyside_imports():
    out = set()
    for root, _, files in os.walk(os.path.join(ROOT, "src")):
        for n in files:
            if n.endswith(".py"):
                with open(os.path.join(root, n), encoding="utf-8") as f:
                    text = f.read()
                out |= set(re.findall(r"\bPySide6\.(Qt\w+)", text))
                for names in re.findall(r"from PySide6 import ([^\n#]+)", text):
                    out |= {x.strip() for x in names.split(",") if x.strip().startswith("Qt")}
    return out


def _qml_left_out(pats):
    m = _mod()
    return {i: m.match(pats, f"{SITE}/PySide6/Qt/qml/{i.replace('.', '/')}/qmldir") for i in _qml_imports()
            if m.match(pats, f"{SITE}/PySide6/Qt/qml/{i.replace('.', '/')}/qmldir")}


def _pyside_left_out(pats):
    m = _mod()
    out = {}
    for q in _pyside_imports():
        for rel in (f"{SITE}/PySide6/{q}.abi3.so", f"{SITE}/PySide6/Qt/lib/libQt6{q[2:]}.so.6"):
            if m.match(pats, rel):
                out[rel] = m.match(pats, rel)
    return out


def test_no_qml_module_appkata_imports_is_left_out():
    assert {"QtQuick", "QtQuick.Controls.Basic", "QtQuick.Dialogs", "QtQuick.Shapes"} <= _qml_imports()
    assert _qml_left_out(_mod().patterns()) == {}


def test_no_pyside6_module_appkata_imports_is_left_out():
    assert {"QtCore", "QtGui", "QtWidgets", "QtQml", "QtQuick", "QtNetwork", "QtSvg"} <= _pyside_imports()
    assert _pyside_left_out(_mod().patterns()) == {}


def test_the_import_checks_catch_a_module_appkata_uses_left_out():
    pats = _mod().patterns()
    assert _qml_left_out(pats + ["usr/python/lib/python*/site-packages/PySide6/Qt/qml/QtQuick/Controls/Basic"])
    assert _pyside_left_out(pats + ["usr/python/lib/python*/site-packages/PySide6/QtSvg.abi3.so"])
