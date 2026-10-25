"""The check of what the AppImage takes from the host (scripts/appimage_host_libs.py; review 3, R3-31,
R3-32). The check itself needs a built AppImage and a container (scripts/test-appimage.sh); this
holds its working out to what it says: a soname from a loaded file's name, the files a process
mapped, what ldd resolved on the host, needs followed through the bundled libraries, and a library
loaded at run time that nothing links."""

import importlib.util
import os

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")


def _mod():
    spec = importlib.util.spec_from_file_location("appimage_host_libs", os.path.join(ROOT, "scripts", "appimage_host_libs.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_soname_from_a_loaded_files_name():
    m = _mod()
    assert m.soname("/usr/lib/x86_64-linux-gnu/libglib-2.0.so.0.8000.0") == "libglib-2.0.so.0"
    assert m.soname("/lib64/libstdc++.so.6.0.33") == "libstdc++.so.6"
    assert m.soname("/usr/lib/libgssapi_krb5.so.2.2") == "libgssapi_krb5.so.2"
    assert m.soname("/lib64/ld-linux-x86-64.so.2") == "ld-linux-x86-64.so.2"
    assert m.soname("/x/libqxcb.so") == "libqxcb.so"


def test_the_files_a_process_mapped_and_what_ldd_resolved_on_the_host():
    m = _mod()
    maps = ("7f00-7f01 r--p 00000000 08:05 1 /usr/lib/x86_64-linux-gnu/libz.so.1.3\n"
            "7f01-7f02 r-xp 00000000 08:05 2 /tmp/squashfs-root/usr/python/lib/libpython3.14.so.1.0\n"
            "7f02-7f03 rw-p 00000000 00:00 0 [heap]\n"
            "7f03-7f04 r--p 00000000 08:05 3 /usr/share/locale/locale.alias\n")
    assert m.loaded(maps) == {"/usr/lib/x86_64-linux-gnu/libz.so.1.3", "/tmp/squashfs-root/usr/python/lib/libpython3.14.so.1.0"}
    ldd = ("\tlibQt6Core.so.6 => /tmp/squashfs-root/usr/lib/libQt6Core.so.6 (0x1)\n"
           "\tlibglib-2.0.so.0 => /lib/x86_64-linux-gnu/libglib-2.0.so.0 (0x2)\n"
           "\tlibxcb-cursor.so.0 => not found\n")
    assert m.linked(ldd) == {"libglib-2.0.so.0"}


def test_needs_follow_the_bundled_libraries_and_count_a_plugin_that_did_not_load():
    """libqxcb.so names only bundled Qt libraries; libQt6XcbQpa, which it names, names
    libxcb-cursor: the check must reach it even when the plugin failed to load (R3-32)."""
    m = _mod()
    bundled = {"libqxcb.so": "/a/libqxcb.so", "libQt6XcbQpa.so.6": "/a/libQt6XcbQpa.so.6", "libQt6Gui.so.6": "/a/libQt6Gui.so.6"}
    elf = {"/a/libqxcb.so": ["libQt6XcbQpa.so.6", "libQt6Gui.so.6"],
           "/a/libQt6XcbQpa.so.6": ["libxcb-cursor.so.0", "libQt6Gui.so.6", "libc.so.6"],
           "/a/libQt6Gui.so.6": ["libEGL.so.1", "libc.so.6", "$ORIGIN/../lib/libQt6XcbQpa.so.6"]}
    assert m.closure({"/a/libqxcb.so"}, bundled, elf.__getitem__) == {"libxcb-cursor.so.0", "libEGL.so.1", "libc.so.6"}


def test_a_library_loaded_at_run_time_that_nothing_links_is_needed():
    """Qt's TLS backend loads OpenSSL only when first used; nothing names it (R3-31)."""
    m = _mod()
    need = m.needs(direct={"libglib-2.0.so.0"}, bundled={"libQt6Core.so.6"},
                   host_loaded={"libglib-2.0.so.0", "libpcre2-8.so.0", "libssl.so.3", "libcrypto.so.3"},
                   host_linked={"libglib-2.0.so.0", "libpcre2-8.so.0"})
    assert need == {"libglib-2.0.so.0", "libssl.so.3", "libcrypto.so.3"}


def test_each_library_still_unnamed_names_its_finding():
    from test_requirements_trace import _finding_exists
    for lib, finding in _mod().STILL_UNNAMED.items():
        assert lib.startswith(("lib", "ld-")) and _finding_exists(finding), lib


def test_requirement_1_6_names_each_group_of_the_listed_libraries():
    """1.6 says what the AppImage takes from the host, by group; packaging/appimage-host-libs.txt
    lists each library with its group, and the check holds the AppImage to that list (R3-31)."""
    m = _mod()
    with open(m.NAMED, encoding="utf-8") as f:
        rows = [line.split("#") for line in f if line.strip() and not line.startswith("#")]
    groups = {comment.strip() for _, comment in rows}
    assert len(rows) == len(m.named()) and all(g for g in groups)
    with open(os.path.join(ROOT, "docs", "requirements.md"), encoding="utf-8") as f:
        req = f.read()
    para = req[req.index("1.6. Distribution:"):req.index("- macOS: a signed")]
    para = " ".join(para.split())
    assert "packaging/appimage-host-libs.txt" in para
    assert [g for g in sorted(groups) if g not in para] == []
