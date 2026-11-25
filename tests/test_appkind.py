"""An app's kind from its download (R17.3.3; review 2, F4)."""

import os
import struct
import subprocess

import pytest

from appkata_core import appkind


def make_elf(path, needed: list[str], bits: int = 64, gap: int = 0, gap_before: str = "shdrs") -> None:
    """A minimal ELF with a .dynstr and a .dynamic naming `needed` -- enough for the section-header
    reader, and no machine needed to produce it. `gap` bytes of nothing (a sparse file) go before
    the section headers, or before the string table (and so before everything but the ELF header)."""
    strtab = b"\0"
    offs = []
    for n in needed:
        offs.append(len(strtab))
        strtab += n.encode() + b"\0"
    if bits == 64:
        dyn = b"".join(struct.pack("<qQ", 1, o) for o in offs) + struct.pack("<qQ", 0, 0)
        ehsize, shentsize = 64, 64
    else:
        dyn = b"".join(struct.pack("<iI", 1, o) for o in offs) + struct.pack("<iI", 0, 0)
        ehsize, shentsize = 52, 40
    stroff = ehsize + (gap if gap_before == "strtab" else 0)
    dynoff = stroff + len(strtab)
    shoff = dynoff + len(dyn) + (gap if gap_before == "shdrs" else 0)
    ident = b"\x7fELF" + bytes([2 if bits == 64 else 1, 1, 1]) + b"\0" * 9
    if bits == 64:
        hdr = ident + struct.pack("<HHIQQQIHHHHHH", 2, 62, 1, 0, 0, shoff, 0, ehsize, 0, 0, shentsize, 3, 0)
        sh = lambda typ, off, size, link: struct.pack("<IIQQQQIIQQ", 0, typ, 0, 0, off, size, link, 0, 1, 0)   # noqa: E731
    else:
        hdr = ident + struct.pack("<HHIIIIIHHHHHH", 2, 3, 1, 0, 0, shoff, 0, ehsize, 0, 0, shentsize, 3, 0)
        sh = lambda typ, off, size, link: struct.pack("<IIIIIIIIII", 0, typ, 0, 0, off, size, link, 0, 1, 0)    # noqa: E731
    shdrs = sh(0, 0, 0, 0) + sh(3, stroff, len(strtab), 0) + sh(6, dynoff, len(dyn), 1)
    with open(path, "wb") as f:
        f.write(hdr)
        f.seek(stroff)
        f.write(strtab + dyn)
        f.seek(shoff)
        f.write(shdrs)
    os.chmod(path, 0o755)


@pytest.mark.parametrize("bits", [64, 32])
def test_the_elf_reader_finds_what_a_program_links(tmp_path, bits):
    p = tmp_path / "prog"
    make_elf(p, ["libgtk-3.so.0", "libc.so.6"], bits)
    assert appkind.elf_needed(str(p)) == ["libgtk-3.so.0", "libc.so.6"]
    p.write_text("#!/bin/sh\n")
    assert appkind.elf_needed(str(p)) is None                       # a script: not ELF


@pytest.mark.parametrize("needed,kind", [
    (["libgtk-3.so.0", "libnss3.so", "libc.so.6"], "gui"),          # Electron
    (["libQt6Widgets.so.6", "libQt6Gui.so.6"], "gui"),
    (["libX11.so.6"], "gui"), (["libwayland-client.so.0"], "gui"), (["libSDL2-2.0.so.0"], "gui"),
    (["libEGL.so.1"], "gui"), (["libxcb-shm.so.0"], "gui"),
    (["libc.so.6", "libm.so.6", "libgcc_s.so.1"], "cli"),           # ripgrep, fd
    ([], "cli"),                                                    # static Go
    (["libgdk_pixbuf-2.0.so.0", "libc.so.6"], "cli"),               # an image converter
])
def test_a_program_is_an_app_when_it_links_a_display_library(tmp_path, needed, kind):
    make_elf(tmp_path / "prog", needed)
    assert appkind.kind_of_program(str(tmp_path / "prog")) == kind


# ---------------------------------------------------------------- a program of any size (CR1.3-19)

@pytest.mark.parametrize("where", ["the section headers", "the libraries' names and the section headers"])
@pytest.mark.parametrize("bits", [64, 32])
@pytest.mark.parametrize("needed,kind", [([], "cli"), (["libc.so.6", "libm.so.6"], "cli"), (["libgtk-3.so.0", "libc.so.6"], "gui")])
def test_a_program_larger_than_any_length_read_whole_is_read_by_what_it_links(tmp_path, needed, kind, bits, where):
    # CR1.3-19: the reader took the first 64 MB, and a program's section headers are at its end, so
    # any larger program was "can't tell": a 70 MB static Go tool ran Strict as an app, and an
    # Electron program was an app only because "can't tell" falls that way. Each part is read where
    # it is now. The file is sparse: 80 MB on paper, nothing on the disk.
    big, small = tmp_path / "big", tmp_path / "small"
    make_elf(small, needed, bits)
    make_elf(big, needed, bits, gap=80 << 20, gap_before="shdrs" if where == "the section headers" else "strtab")
    assert os.path.getsize(big) > 80 << 20
    assert appkind.elf_needed(str(big)) == appkind.elf_needed(str(small)) == needed
    assert appkind.kind_of_program(str(big)) == appkind.kind_of_program(str(small)) == kind

def test_a_real_system_program_is_read(tmp_path):
    true = "/usr/bin/true"
    if not os.path.exists(true):
        pytest.skip("no /usr/bin/true")
    assert appkind.kind_of_program(true) == "cli"


def test_a_tarball_says_so_in_its_desktop_file_else_its_program_decides(tmp_path):
    v = tmp_path / "1.0"
    (v / "bin").mkdir(parents=True)
    make_elf(v / "bin" / "tool", ["libgtk-3.so.0"])
    assert appkind.kind_of_folder(str(v), "bin/tool") == "gui"
    (v / "share").mkdir()
    (v / "share" / "tool.desktop").write_text("[Desktop Entry]\nType=Application\nName=Tool\nExec=tool\nTerminal=true\n")
    assert appkind.kind_of_folder(str(v), "bin/tool") == "cli"       # the publisher's own word wins
    (v / "share" / "tool.desktop").write_text("[Desktop Entry]\nType=Application\nName=Tool\nExec=tool\n")
    assert appkind.kind_of_folder(str(v), "bin/tool") == "gui"
    os.remove(v / "share" / "tool.desktop")
    (v / "bin" / "tool").write_text("#!/bin/sh\nexec java -jar x.jar\n")
    assert appkind.kind_of_folder(str(v), "bin/tool") is None        # can't tell: the caller treats it as an app


# ---------------------------------------------------------------- a program that loads its window's libraries (CR1.3-43)

_C = ["libpthread.so.0", "libc.so.6"]
_CXX = ["libdl.so.2", "libstdc++.so.6", "libm.so.6", "libgcc_s.so.1", "libpthread.so.0", "libc.so.6", "ld-linux-x86-64.so.2"]

# tarballs with no .desktop file, as their publishers lay them out: {file: what it links}, the
# program, and the kind
_TARBALLS = {
    # Firefox 159.0: firefox and firefox-bin link the C and C++ run-times; libxul.so, loaded at run
    # time, links GTK and X11
    "Firefox": ({"firefox": _C, "firefox-bin": _CXX, "libxul.so": ["libgtk-3.so.0", "libgdk-3.so.0", "libX11.so.6", "libc.so.6"],
                 "libmozgtk.so": ["libgtk-3.so.0"], "libnss3.so": _C}, "firefox", "gui"),
    "a library beside it, versioned": ({"app": _C, "libui.so.2": ["libwayland-client.so.0"]}, "app", "gui"),
    "a tool with libraries of its own": ({"bin/tool": _CXX, "bin/libtoolcore.so": ["libz.so.1", "libc.so.6"]}, "bin/tool", "cli"),
    "a tool with none": ({"rg": []}, "rg", "cli"),
    "an app that links its own": ({"app": ["libgtk-3.so.0"]}, "app", "gui"),
}


@pytest.mark.parametrize("tarball", list(_TARBALLS))
def test_a_tarballs_program_is_an_app_when_it_or_a_library_beside_it_links_a_display_library(tmp_path, tarball):
    # CR1.3-43: R17.3.3 made a tarball a command-line tool when its program links no display library,
    # and Firefox's program links none: it loads libxul.so, which does. So Firefox was installed as
    # a command-line tool, with the cli-tool template and no app-menu entry. The owner's decision: a
    # shared library in the program's folder that links a display library makes it an app too.
    files, program, kind = _TARBALLS[tarball]
    for name, needed in files.items():
        (tmp_path / "v" / name).parent.mkdir(parents=True, exist_ok=True)
        make_elf(tmp_path / "v" / name, needed)
    assert appkind.kind_of_folder(str(tmp_path / "v"), program) == kind

def test_an_appimage_without_bwrap_is_unknown(tmp_path, monkeypatch):
    from appkata_core import sandbox
    monkeypatch.setattr(sandbox, "host_which", lambda name, apps_root=None: None)        # no bwrap a launcher can run
    img = tmp_path / "X.AppImage"
    img.write_text("#!/bin/sh\n")
    assert appkind.kind_of_appimage(str(img)) is None


def test_the_appimage_runtime_runs_sandboxed_and_its_desktop_decides(tmp_path, monkeypatch):
    # what kind_of_appimage asks bwrap to run: the AppImage's own runtime, no network, a staging
    # folder its only writable place; a stand-in bwrap runs the "runtime" so the reading is checked
    seen = []

    def fake_run(cmd, **kw):
        seen.append(cmd)
        stg = cmd[cmd.index("--chdir") + 1]
        os.makedirs(os.path.join(stg, "squashfs-root"))
        with open(os.path.join(stg, "squashfs-root", "nvim.desktop"), "w") as f:
            f.write("[Desktop Entry]\nName=Neovim\nExec=nvim %F\nTerminal=true\n")
        return subprocess.CompletedProcess(cmd, 0)
    from appkata_core import sandbox
    monkeypatch.setattr(sandbox, "host_which", lambda name, apps_root=None: f"/usr/bin/{name}")    # the launchers' bwrap
    monkeypatch.setattr(appkind.subprocess, "run", fake_run)
    img = tmp_path / "nvim.AppImage"
    img.write_text("x")
    assert appkind.kind_of_appimage(str(img)) == "cli"
    cmd = seen[0]
    assert cmd[0] == "/usr/bin/bwrap" and "--unshare-all" in cmd and "--share-net" not in cmd
    assert cmd[-3:] == [str(img), "--appimage-extract", "*.desktop"]
    i = cmd.index("--ro-bind", cmd.index("/etc"))                    # the image read-only, the staging dir the only rw bind
    assert cmd[i:i + 3] == ["--ro-bind", str(img), str(img)]
    assert [cmd[j + 1] for j, w in enumerate(cmd) if w == "--bind"] == [cmd[cmd.index("--chdir") + 1]]
