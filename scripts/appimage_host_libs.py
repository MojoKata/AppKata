#!/usr/bin/env python3
"""What the AppImage takes from the host, against what requirement 1.6 names (review 3, R3-31).

1.6 said the AppImage "carries everything AppKata needs". It carries its Python and Qt, and takes
the rest from the host: about 20 libraries, Kerberos's libgssapi_krb5 among them, which no
requirement named and only the Mint images' full desktops happened to have. The class: a library
the AppImage takes from the host that no requirement names and no tier shows present.

scripts/test-appimage.sh runs the AppImage in a container and writes, into RUN:

- maps-tour.txt: the libraries the tour's process has loaded, mid-tour;
- maps-probe.txt: the same for a probe that loads what the tour can't reach offscreen: the X11 and
  Wayland platform plugins and their integrations, and Qt's TLS backend, which loads OpenSSL only
  when it's first used (a Markdown image from the web);
- plugins.txt: the plugins the probe loaded, or tried to (one that fails to load still counts);
- ldd.txt: `ldd` of each AppImage library either one loaded, resolved on that host.

What the AppImage needs from the host is then what those libraries and plugins name (readelf, on
the AppImage extracted in APPDIR), followed through the libraries it bundles, that it doesn't
bundle; plus what was loaded from the host that nothing links (loaded at run time, as OpenSSL).
Each must be in NAMED (packaging/appimage-host-libs.txt), and each named one must still be needed.

    scripts/appimage_host_libs.py APPDIR RUN [RUN...]
"""

from __future__ import annotations

import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
NAMED = os.path.join(HERE, "..", "packaging", "appimage-host-libs.txt")
INSIDE = "/tmp/squashfs-root/"          # where test-appimage.sh extracts the AppImage in the container

# What the AppImage takes from the host that 1.6 doesn't name yet, and the finding that keeps each:
# reported, not failed. One that's named, or no longer needed, fails the check
STILL_UNNAMED: dict = {}


def soname(path: str) -> str:
    """A loaded file's soname, from its name: libglib-2.0.so.0.8000.0 -> libglib-2.0.so.0."""
    m = re.match(r"(.*?\.so(?:\.\d+)?)(?:\.\d+)*$", os.path.basename(path))
    return m.group(1) if m else os.path.basename(path)


def loaded(maps: str) -> set[str]:
    """The files a process had mapped that look like libraries (/proc/PID/maps)."""
    out = set()
    for line in maps.splitlines():
        parts = line.split(None, 5)
        if len(parts) == 6 and ".so" in os.path.basename(parts[5]):
            out.add(parts[5].strip())
    return out


def linked(ldd: str) -> set[str]:
    """The host libraries `ldd` resolved for the AppImage's libraries (their link-time closure)."""
    return {soname(m.group(1)) for m in re.finditer(r"=>\s+(/\S+)", ldd) if not m.group(1).startswith(INSIDE)}


def closure(start: set[str], bundled: dict[str, str], needed) -> set[str]:
    """The sonames the files in `start` need, followed through the bundled ones (`bundled`: soname
    -> file), that aren't bundled. `needed(file)` lists a file's NEEDED entries."""
    out, seen, todo = set(), set(), list(start)
    while todo:
        f = todo.pop()
        if f in seen:
            continue
        seen.add(f)
        for n in needed(f):
            n = os.path.basename(n)            # "$ORIGIN/../lib/libpython3.14.so.1.0"
            if n in bundled:
                todo.append(bundled[n])
            else:
                out.add(n)
    return out


def needs(direct: set[str], bundled: set[str], host_loaded: set[str], host_linked: set[str]) -> set[str]:
    """What the AppImage needs from the host: the sonames its libraries name and don't bundle, and
    what was loaded from the host that nothing links (loaded at run time)."""
    return (direct - bundled) | (host_loaded - host_linked - bundled)


def readelf_needed(path: str) -> list[str]:
    out = subprocess.run(["readelf", "-d", path], capture_output=True, text=True).stdout
    return re.findall(r"\(NEEDED\)\s+Shared library: \[(.+?)\]", out)


def named() -> set[str]:
    if not os.path.exists(NAMED):
        return set()
    with open(NAMED, encoding="utf-8") as f:
        return {line.split("#")[0].strip() for line in f if line.split("#")[0].strip()}


def main(appdir: str, runs: list[str]) -> int:
    bundled: dict[str, str] = {}
    for root, _, files in os.walk(appdir):
        for name in files:
            if ".so" in name:
                bundled.setdefault(name, os.path.join(root, name))
    need: set[str] = set()
    for run in runs:
        maps = "".join(open(os.path.join(run, f)).read() for f in ("maps-tour.txt", "maps-probe.txt"))
        files = loaded(maps)
        with open(os.path.join(run, "plugins.txt")) as fh:
            tried = {line.strip() for line in fh if line.strip()}
        mine = {os.path.join(appdir, f[len(INSIDE):]) for f in ({f for f in files if f.startswith(INSIDE)} | tried)}
        direct = closure(mine, bundled, readelf_needed)
        host = {soname(f) for f in files if not f.startswith(INSIDE)}
        with open(os.path.join(run, "ldd.txt")) as fh:
            need |= needs(direct, set(bundled), host, linked(fh.read()))
    have = named()
    unnamed = sorted(need - have)
    stale = sorted(have - need)
    for s in unnamed:
        print(f"  {STILL_UNNAMED[s] + ', still: ' if s in STILL_UNNAMED else ''}needed from the host, not named: {s}")
    fixed = sorted(s for s in STILL_UNNAMED if s in have or s not in need)
    for s in fixed:
        print(f"  named or no longer needed, take it off STILL_UNNAMED: {s}")
    for s in stale:
        print(f"  named in {os.path.relpath(NAMED)}, no longer needed: {s}")
    new = [s for s in unnamed if s not in STILL_UNNAMED]
    print(f"{len(need)} libraries from the host: {len(need) - len(unnamed)} named, {len(new)} new, "
          f"{len(unnamed) - len(new)} listed")
    return 1 if new or fixed or stale else 0


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    sys.exit(main(sys.argv[1], sys.argv[2:]))
