"""Whether a portable app is a command-line tool or an app with a window (R17.3.3).

An unreviewed command-line tool gets the cli-tool template (it sees the folder it is run in) and an
unreviewed app Strict, so AppKata has to tell them apart. Review 2, F4: it did so by "a command link
and no app-menu entry", which Settings' defaults (both on) never produced, so every tool ran Strict
and saw nothing. Decided from the download instead (the owner's decision):

- an **AppImage** carries a `.desktop` file at its root; `Terminal=true` there means a command-line
  tool. Reading it means running the AppImage's own runtime (`--appimage-extract '*.desktop'`), the
  publisher's code, so that runs in the same locked-down bwrap as the launcher's unpacking;
- a **tarball** rarely carries a `.desktop` (Firefox's and VSCodium's don't); one that does says so
  the same way. Otherwise its program decides: an ELF that links a display library (X11, xcb,
  Wayland, GTK/GDK, Qt's GUI, SDL, OpenGL/EGL, Vulkan) is an app -- Electron links GTK -- and so is
  one with a shared library beside it, in its folder, that links one (Firefox's program loads
  `libxul.so`, which links GTK, at run time); one that links none (ripgrep, fd: static Rust or Go)
  is a command-line tool.

Anything that can't be told (a shell script, an unreadable file, no bwrap) is "unknown", which the
caller treats as an app: Strict, the tighter of the two.
"""

from __future__ import annotations

import configparser
import os
import re
import struct
import subprocess
import tempfile

CLI, GUI = "cli", "gui"

# sonames that mean "draws a window"
DISPLAY_LIB = re.compile(r"^lib(X11|xcb|wayland-client|gtk-[34]|gtk-4|gdk-[34]|gdk-4|Qt[56]Gui|Qt[56]Widgets|Qt[56]Quick|"
                         r"SDL2|SDL3|GL|GLX|EGL|OpenGL|vulkan)([.-]|$)")


# what is read of a dynamic section, and of one library's name: far more than any real one holds
_DYNAMIC_MAX, _SONAME_MAX = 1 << 20, 4096


def elf_needed(path: str) -> list[str] | None:
    """The DT_NEEDED sonames of an ELF file, [] for a static one, or None when it isn't ELF or
    can't be read. Reads the section headers (SHT_DYNAMIC and the string table it links to), each
    part where it is: a program's section headers are at its end, past any length read whole (a
    first 64 MB was read, so a larger program was "can't tell", CR1.3-19)."""
    try:
        with open(path, "rb") as f:
            return _needed(f)
    except OSError:
        return None


def _needed(f) -> list[str] | None:
    def at(off: int, n: int) -> bytes:
        f.seek(off)
        data = f.read(n)
        if len(data) < n:
            raise ValueError("past the end of the file")
        return data

    head = f.read(64)
    if len(head) < 52 or head[:4] != b"\x7fELF":
        return None
    klass, order = head[4], head[5]
    if klass not in (1, 2) or order not in (1, 2):
        return None
    e = "<" if order == 1 else ">"
    try:
        if klass == 2:
            shoff, = struct.unpack_from(e + "Q", head, 0x28)
            shentsize, shnum = struct.unpack_from(e + "HH", head, 0x3A)
            sh_fmt, dyn_fmt = e + "IIQQQQIIQQ", e + "qQ"
        else:
            shoff, = struct.unpack_from(e + "I", head, 0x20)
            shentsize, shnum = struct.unpack_from(e + "HH", head, 0x2E)
            sh_fmt, dyn_fmt = e + "IIIIIIIIII", e + "iI"
        if not shoff or not shnum or shentsize < struct.calcsize(sh_fmt):
            return None
        sh = lambda i: struct.unpack(sh_fmt, at(shoff + i * shentsize, struct.calcsize(sh_fmt)))     # noqa: E731
        dyn_size = struct.calcsize(dyn_fmt)
        for i in range(shnum):
            s = sh(i)
            if s[1] != 6:                     # SHT_DYNAMIC
                continue
            off, size, link = s[4], s[5], s[6]
            stroff = sh(link)[4]
            dyn = at(off, min(size, _DYNAMIC_MAX) // dyn_size * dyn_size)
            out = []
            for j in range(0, len(dyn), dyn_size):
                tag, val = struct.unpack_from(dyn_fmt, dyn, j)
                if tag == 0:
                    break
                if tag == 1:                  # DT_NEEDED
                    f.seek(stroff + val)
                    name = f.read(_SONAME_MAX)
                    out.append(name[:name.index(b"\0")].decode("utf-8", "replace"))
            return out
        return []                             # no dynamic section: static
    except (struct.error, ValueError, IndexError, OverflowError):
        return None


def desktop_terminal(path: str) -> bool | None:
    """Whether a .desktop file's [Desktop Entry] says Terminal=true; None when unreadable."""
    cp = configparser.ConfigParser(interpolation=None, strict=False)
    try:
        cp.read(path, encoding="utf-8")
        return cp.get("Desktop Entry", "Terminal", fallback="false").strip().lower() == "true"
    except (configparser.Error, OSError, UnicodeDecodeError):
        return None


def kind_of_program(path: str) -> str | None:
    """CLI or GUI from what an ELF program links; None for anything that isn't ELF."""
    needed = elf_needed(path)
    if needed is None:
        return None
    return GUI if any(DISPLAY_LIB.match(n) for n in needed) else CLI


def kind_of_folder(folder: str, exec_rel: str) -> str | None:
    """A tarball's kind: its .desktop files' Terminal key if it has any (within three levels), else
    its program's libraries and those of the shared libraries beside it; None when neither tells."""
    terminals = []
    base = folder.rstrip(os.sep).count(os.sep)
    for root, dirs, files in os.walk(folder):
        if root.count(os.sep) - base >= 3:
            dirs[:] = []
        for name in files:
            if name.endswith(".desktop"):
                t = desktop_terminal(os.path.join(root, name))
                if t is not None:
                    terminals.append(t)
    if terminals:
        return CLI if all(terminals) else GUI
    program = os.path.join(folder, exec_rel)
    kind = kind_of_program(program)
    return GUI if kind == CLI and _ships_a_display_library(os.path.dirname(program)) else kind


def _ships_a_display_library(folder: str) -> bool:
    """Whether a shared library in `folder`, the program's own, links a display library: a program
    that loads its window's libraries at run time links none itself (Firefox's `firefox` links only
    the C run-time; its `libxul.so` links GTK and X11, CR1.3-43)."""
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        return False
    for name in names:
        path = os.path.join(folder, name)
        if (name.endswith(".so") or ".so." in name) and os.path.isfile(path):
            needed = elf_needed(path)
            if needed and any(DISPLAY_LIB.match(n) for n in needed):
                return True
    return False


def kind_of_appimage(img: str, timeout: float = 60) -> str | None:
    """An AppImage's kind from the Terminal key of the .desktop at its root, read by its own runtime
    inside a bwrap that can write only a staging folder and has no network (the launcher's unpacking,
    R17.7). None where bwrap can't run or the runtime gives no .desktop. The bwrap is the one the
    launchers run (sandbox.host_which), which the AppArmor profile names (R17.10)."""
    from .sandbox import host_which
    bwrap = host_which("bwrap")
    if not bwrap or not os.path.isfile(img):
        return None
    with tempfile.TemporaryDirectory(prefix="appkata-kind-") as stg:
        cmd = [bwrap, "--ro-bind", "/usr", "/usr", "--symlink", "usr/lib", "/lib", "--symlink", "usr/lib64", "/lib64",
               "--symlink", "usr/bin", "/bin", "--symlink", "usr/sbin", "/sbin", "--ro-bind", "/etc", "/etc",
               "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp", "--ro-bind", img, img, "--bind", stg, stg,
               "--chdir", stg, "--unshare-all", "--die-with-parent", "--new-session", "--clearenv",
               "--setenv", "HOME", stg, "--setenv", "PATH", "/usr/bin:/bin", "--", img, "--appimage-extract", "*.desktop"]
        try:
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=timeout)
        except (OSError, subprocess.SubprocessError):
            return None
        root = os.path.join(stg, "squashfs-root")
        if os.path.islink(root) or not os.path.isdir(root):
            return None
        found = [desktop_terminal(os.path.join(root, n)) for n in sorted(os.listdir(root))
                 if n.endswith(".desktop") and os.path.isfile(os.path.join(root, n)) and not os.path.islink(os.path.join(root, n))]
        found = [t for t in found if t is not None]
        if not found:
            return None
        return CLI if found[0] else GUI


def detect(kind: str, current: dict, target: str) -> str | None:
    """The kind of an installed version: `kind` is the asset kind ("appimage", "tarball"),
    `current` the install record's {path, exec}, `target` the app's folder."""
    path = current.get("path", "")
    if kind == "appimage" or path.lower().endswith(".appimage"):
        return kind_of_appimage(path)
    if kind == "tarball" and os.path.isdir(path):
        return kind_of_folder(path, os.path.relpath(os.path.join(target, current.get("exec", "")), path))
    return None
