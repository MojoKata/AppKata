"""Whether a portable app is a command-line tool or an app with a window (requirement 17.3.3).

An unreviewed command-line tool gets the cli-tool template (it sees the folder it is run in) and an
unreviewed app Strict, so AppKata has to tell them apart. Review 2, F4: it did so by "a command link
and no app-menu entry", which Settings' defaults (both on) never produced, so every tool ran Strict
and saw nothing. Decided from the download instead (the owner's decision):

- an **AppImage** carries a `.desktop` file at its root; `Terminal=true` there means a command-line
  tool. Reading it means running the AppImage's own runtime (`--appimage-extract '*.desktop'`), the
  publisher's code, so that runs in the same locked-down bwrap as the launcher's unpacking;
- a **tarball** rarely carries a `.desktop` (Firefox's and VSCodium's don't); one that does says so
  the same way. Otherwise its program decides: an ELF that links a display library (X11, xcb,
  Wayland, GTK/GDK, Qt's GUI, SDL, OpenGL/EGL, Vulkan) is an app -- Electron links GTK -- and one that
  links none (ripgrep, fd: static Rust or Go) is a command-line tool.

Anything that can't be told (a shell script, an unreadable file, no bwrap) is "unknown", which the
caller treats as an app: Strict, the tighter of the two.
"""

from __future__ import annotations

import configparser
import os
import re
import shutil
import struct
import subprocess
import tempfile

CLI, GUI = "cli", "gui"

# sonames that mean "draws a window"
DISPLAY_LIB = re.compile(r"^lib(X11|xcb|wayland-client|gtk-[34]|gtk-4|gdk-[34]|gdk-4|Qt[56]Gui|Qt[56]Widgets|Qt[56]Quick|"
                         r"SDL2|SDL3|GL|GLX|EGL|OpenGL|vulkan)([.-]|$)")


def elf_needed(path: str) -> list[str] | None:
    """The DT_NEEDED sonames of an ELF file, [] for a static one, or None when it isn't ELF or
    can't be read. Reads the section headers (SHT_DYNAMIC and the string table it links to)."""
    try:
        with open(path, "rb") as f:
            data = f.read(64 << 20)
    except OSError:
        return None
    if len(data) < 64 or data[:4] != b"\x7fELF":
        return None
    klass, order = data[4], data[5]
    if klass not in (1, 2) or order not in (1, 2):
        return None
    e = "<" if order == 1 else ">"
    try:
        if klass == 2:
            shoff, = struct.unpack_from(e + "Q", data, 0x28)
            shentsize, shnum = struct.unpack_from(e + "HH", data, 0x3A)
            sh = lambda i: struct.unpack_from(e + "IIQQQQIIQQ", data, shoff + i * shentsize)     # noqa: E731
            dyn_fmt, dyn_size = e + "qQ", 16
        else:
            shoff, = struct.unpack_from(e + "I", data, 0x20)
            shentsize, shnum = struct.unpack_from(e + "HH", data, 0x2E)
            sh = lambda i: struct.unpack_from(e + "IIIIIIIIII", data, shoff + i * shentsize)     # noqa: E731
            dyn_fmt, dyn_size = e + "iI", 8
        if not shoff or not shnum:
            return None
        for i in range(shnum):
            s = sh(i)
            if s[1] != 6:                     # SHT_DYNAMIC
                continue
            off, size, link = s[4], s[5], s[6]
            stroff = sh(link)[4]
            out = []
            for j in range(0, size, dyn_size):
                tag, val = struct.unpack_from(dyn_fmt, data, off + j)
                if tag == 0:
                    break
                if tag == 1:                  # DT_NEEDED
                    end = data.index(b"\0", stroff + val)
                    out.append(data[stroff + val:end].decode("utf-8", "replace"))
            return out
        return []                             # no dynamic section: static
    except (struct.error, ValueError, IndexError):
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
    its program's libraries; None when neither tells."""
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
    return kind_of_program(os.path.join(folder, exec_rel))


def kind_of_appimage(img: str, timeout: float = 60) -> str | None:
    """An AppImage's kind from the Terminal key of the .desktop at its root, read by its own runtime
    inside a bwrap that can write only a staging folder and has no network (the launcher's unpacking,
    17.7). None where bwrap can't run or the runtime gives no .desktop."""
    if not shutil.which("bwrap") or not os.path.isfile(img):
        return None
    with tempfile.TemporaryDirectory(prefix="appkata-kind-") as stg:
        cmd = ["bwrap", "--ro-bind", "/usr", "/usr", "--symlink", "usr/lib", "/lib", "--symlink", "usr/lib64", "/lib64",
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
