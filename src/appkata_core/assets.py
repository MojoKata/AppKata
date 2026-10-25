"""Choosing the release asset for this OS and architecture (requirement 4.2)."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .forges import Asset

ARCH_WORDS = {
    "x86_64": r"x86[_-]?64|amd64|x64|win64|64bit",
    "arm64": r"aarch64|arm64|armv8",
}
OTHER_ARCH = r"\b(i[3-6]86|x86(?![_-]?64)|win32|armhf|armv7l?|armel|ppc64le|s390x|riscv64|loong64|mips)\b"
SKIP = re.compile(r"(\.(sha\d+|sha256sum|md5|asc|sig|minisig|sbom|spdx|json|txt|blockmap|yml|yaml|zsync|sym|pdb|dsym)$)|"
                  r"(^sha\d+sums?|checksums?|^source|[-_.](src|sources?)[-_.]|debug|dbgsym|symbols)", re.I)
UNIVERSAL = re.compile(r"universal|all[-_.]?arch|noarch", re.I)
OS_WORDS = {
    "linux": re.compile(r"linux|appimage|\.deb$|\.rpm$|flatpak", re.I),
    "windows": re.compile(r"win(dows)?|\.exe$|\.msi$|\.msix$", re.I),
    "macos": re.compile(r"mac|darwin|osx|\.dmg$|\.pkg$", re.I),
}
OTHER_OS = re.compile(r"android|\.apk$|\.aab$|\bios\b|\.ipa$|freebsd|openbsd|netbsd|haiku", re.I)


@dataclass
class Choice:
    asset: Asset | None
    kind: str            # "appimage" | "flatpak" | "deb" | "rpm" | "tarball" | "zip" | "dmg" | "pkg" | "msi" | "exe" | "msix"
    reason: str = ""


def kind_of(name: str) -> str:
    n = name.lower()
    for ext, k in ((".appimage", "appimage"), (".flatpak", "flatpak"), (".deb", "deb"), (".rpm", "rpm"),
                   (".tar.gz", "tarball"), (".tgz", "tarball"), (".tar.xz", "tarball"), (".tar.bz2", "tarball"),
                   (".tar.zst", "tarball"), (".dmg", "dmg"), (".pkg", "pkg"), (".msi", "msi"), (".msix", "msix"),
                   (".exe", "exe"), (".zip", "zip")):
        if n.endswith(ext):
            return k
    return ""


def preference(os_name: str, family: str = "") -> list[str]:
    if os_name == "linux":
        native = ["deb"] if family == "debian" else ["rpm"] if family == "fedora" else []
        return ["appimage", "flatpak", *native, "tarball"]
    if os_name == "macos":
        return ["dmg", "pkg", "zip"]
    return ["zip", "exe-portable", "msi", "exe", "msix"]       # portable first (requirement 15.3)


def order_key(kind: str, name: str) -> str:
    """A portable .exe ranks apart from an installer .exe (requirement 15.3)."""
    return "exe-portable" if kind == "exe" and exe_hint(name) == "portable" else kind


# Which install methods are portable (requirement 4.2.1). "exe" depends on the file.
PORTABLE = {"appimage", "tarball", "dmg", "zip"}
SYSTEM = {"deb", "rpm", "flatpak", "pkg", "msi", "msix"}


def category(kind: str, exe_kind: str = "") -> str:
    """"portable", "system" or "unknown" (a Windows .exe AppKata couldn't classify)."""
    if kind == "exe":
        if exe_kind == "portable":
            return "portable"
        return "system" if exe_kind and exe_kind != "unknown" else "unknown"
    return "portable" if kind in PORTABLE else "system"


def exe_hint(name: str) -> str:
    """From the file name: "portable", "installer" or ""."""
    n = name.lower()
    if re.search(r"portable|standalone|no[-_]?install", n):
        return "portable"
    if re.search(r"setup|installer|install[-_.]", n):
        return "installer"
    return ""


def exe_type(name: str, head: bytes = b"", release: list[str] | tuple = ()) -> str:
    """What a Windows .exe is (requirement 4.2.1, 15.7.1): "inno", "nsis", "electron" (NSIS made by
    electron-builder), "squirrel", "wix", "installshield" (installers, found from markers in its first
    bytes and the release's other files), "installer" or "portable" (from its name), or "unknown"."""
    from .windows import exe_kind_from_release
    by_release = exe_kind_from_release(list(release))
    found = ""
    if head:
        for marker, kind in ((b"Inno Setup", "inno"), (b"InnoSetupLdrWindow", "inno"), (b"jrsoftware.org/ishelp", "inno"),
                             (b"NullsoftInst", "nsis"), (b"Nullsoft.NSIS", "nsis"),
                             (b".wixburn", "wix"), (b"InstallShield", "installshield"), (b"Squirrel", "squirrel")):
            if marker in head or marker.decode().encode("utf-16-le") in head:     # newer loaders keep UTF-16 text
                found = kind
                break
    if by_release == "electron" and found in ("nsis", "") and exe_hint(name) != "portable":
        return "electron"
    if by_release == "squirrel" and found in ("squirrel", "") and re.search(r"setup", name, re.I):
        return "squirrel"
    return found or exe_hint(name) or "unknown"


def candidates(assets: list[Asset], os_name: str, arch: str, family: str = "") -> list[Choice]:
    """The best file of each installable kind for this computer, in order of preference."""
    seen, out = set(), []
    for _, _, a, k in _scored(assets, os_name, arch, preference(os_name, family)):
        key = order_key(k, a.name)
        if key not in seen:
            seen.add(key)
            out.append(Choice(a, k))
    return out


def choose(assets: list[Asset], os_name: str, arch: str, family: str = "", override: str = "",
           invert: bool = False, prefer: str = "") -> Choice:
    """prefer: "portable", "system" or a kind ("deb"), used when the release has such a file."""
    if override:
        rx = re.compile(override, re.I)
        assets = [a for a in assets if bool(rx.search(a.name)) != invert]
        if not assets:
            return Choice(None, "", "the asset filter matches nothing")
    order = preference(os_name, family)
    if override:     # the user picked the file: any format this OS can install will do
        order = order + [k for k in preference(os_name, "debian") + preference(os_name, "fedora") if k not in order]
    cands = _scored(assets, os_name, arch, order)
    if prefer and cands:
        want = [c for c in cands if c[3] == prefer or category(c[3], exe_type(c[2].name)) == prefer]
        cands = want or cands
    if not cands:
        return Choice(None, "", f"no download for {pretty(os_name)} {arch}")
    _, _, a, k = cands[0]
    return Choice(a, k)


def _scored(assets: list[Asset], os_name: str, arch: str, order: list[str]) -> list:
    cands = []
    for a in assets:
        n = a.name
        k = kind_of(n)
        key = order_key(k, n)
        if key not in order and k in order:
            key = k
        if not k or key not in order or SKIP.search(n) or OTHER_OS.search(n):
            continue
        other = [o for o, rx in OS_WORDS.items() if o != os_name and rx.search(n)]
        mine = OS_WORDS[os_name].search(n)
        if other and not mine:
            continue
        if k == "zip" and os_name == "linux":
            continue
        arch_hit = re.search(ARCH_WORDS.get(arch, re.escape(arch)), n, re.I)
        other_arch = [x for x, rx in ARCH_WORDS.items() if x != arch and re.search(rx, n, re.I)]
        if other_arch and not arch_hit:
            continue
        if re.search(OTHER_ARCH, n, re.I) and not arch_hit:
            continue
        if k == "tarball" and not (mine or arch_hit or UNIVERSAL.search(n)):
            continue            # "name-1.2.tar.xz" with no platform in its name is the source code
        score = (order.index(key) * 10
                 - (3 if arch_hit else 1 if UNIVERSAL.search(n) else 0)
                 - (2 if mine else 0)
                 + (1 if "portable" in n.lower() and k == "zip" else 0))
        cands.append((score, len(n), a, k))
    cands.sort(key=lambda c: (c[0], c[1]))
    return cands


def pretty(os_name: str) -> str:
    return {"linux": "Linux", "windows": "Windows", "macos": "macOS"}.get(os_name, os_name)


def checksum_for(asset: Asset, assets: list[Asset]) -> Asset | None:
    """A checksum file that covers this asset, if the release has one (requirement 4.4)."""
    names = {a.name.lower(): a for a in assets}
    for cand in (asset.name + ".sha256", asset.name + ".sha256sum", asset.name + ".sha512"):
        if cand.lower() in names:
            return names[cand.lower()]
    for a in assets:
        if re.match(r"^(sha256sums?|sha256sums\.txt|checksums?(\.txt)?|.*sha256sums?\.txt)$", a.name, re.I):
            return a
    return None
