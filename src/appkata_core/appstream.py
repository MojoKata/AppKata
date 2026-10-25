"""The distribution's AppStream catalog (requirement 16.2.2): which repository packages, and which
Flatpaks, are apps, with their names, summaries and project links. Read directly from the files
apt and dnf keep (DEP-11 YAML, AppStream XML); appstreamcli isn't needed."""

from __future__ import annotations

import glob
import gzip
import os
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

from . import urls
from .platform import arch

APP_TYPES = ("desktop-application", "console-application")
# older DEP-11 and AppStream data call them "desktop-app" / "console-app" (or plain "desktop")
TYPE_ALIASES = {"desktop": "desktop-application", "desktop-app": "desktop-application",
                "console-app": "console-application"}
URL_KINDS = ("vcs-browser", "homepage", "bugtracker")


@dataclass
class Component:
    id: str
    type: str
    name: str = ""
    summary: str = ""
    package: str = ""             # <pkgname> / Package:
    bundle: str = ""              # a Flatpak ref ("app/org.x.Y/x86_64/stable"), for a Flatpak remote's catalog
    urls: dict = field(default_factory=dict)       # kind → URL
    compulsory: list = field(default_factory=list)  # <compulsory_for_desktop>
    origin: str = ""              # the catalog it came from: "ubuntu-noble-universe", "fedora", "flathub"
    icon: str = ""                # a cached icon's file name, or a stock icon name
    developer: str = ""

    @property
    def is_app(self) -> bool:
        """An app, not part of the desktop (requirement 16.2.2)."""
        return self.type in APP_TYPES and not self.compulsory

    def project_urls(self) -> list[str]:
        """Normalized forge project URLs among its links (requirement 16.1.3)."""
        out = []
        for k in URL_KINDS:
            u = urls.try_normalize(self.urls.get(k, "")) if self.urls.get(k) else None
            if u and _forge_project(u) and u not in out:
                out.append(u)
        return out


def _forge_project(url: str) -> bool:
    """A forge project URL looks like host/owner/name, nothing deeper (so a docs page doesn't count)."""
    path = url.split("://", 1)[-1].split("/", 1)[-1]
    return 1 <= path.count("/") <= 3 and not re.search(r"\.(html?|php)$", path)


# ---------------------------------------------------------------- DEP-11 (Debian, Ubuntu, Mint)
def _scalar(s: str) -> str:
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "'\"":
        inner = s[1:-1]
        return inner.replace("''", "'") if s[0] == "'" else inner.encode().decode("unicode_escape", "ignore") \
            if "\\" in inner else inner
    if s in ("~", "null"):
        return ""
    return s


def _ind(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _yaml_block(lines: list[str], i: int, indent: int):
    """Parse the block of `lines` starting at i whose items are indented by `indent`. Returns
    (value, next index). Only what DEP-11 uses: mappings, lists, scalars, and block scalars."""
    if i >= len(lines):
        return None, i
    first = lines[i]
    if first[indent:].startswith("-"):
        out_l: list = []
        while i < len(lines):
            ln = lines[i]
            if _ind(ln) != indent or not ln[indent:].startswith("-"):
                break
            item = ln[indent + 1:].lstrip(" ")
            j, sub = i + 1, []
            while j < len(lines) and _ind(lines[j]) > indent:
                sub.append(lines[j])
                j += 1
            if re.match(r"^[^:\s][^:]*:(\s|$)", item) and not item.startswith(("'", '"')):
                v, _ = _yaml_block([" " * (indent + 2) + item] + sub, 0, indent + 2)
            elif not item and sub:
                v, _ = _yaml_block(sub, 0, _ind(sub[0]))
            else:
                v = _scalar(item)
            out_l.append(v)
            i = j
        return out_l, i
    out: dict = {}
    while i < len(lines):
        ln = lines[i]
        ind = len(ln) - len(ln.lstrip(" "))
        if ind < indent:
            break
        if ind > indent:            # stray deeper line: skip
            i += 1
            continue
        m = re.match(r"^([^:#][^:]*?):(?:\s+(.*))?$", ln[indent:])
        if not m:
            i += 1
            continue
        key, rest = m.group(1).strip(), (m.group(2) or "").strip()
        if rest in ("|", "|-", ">", ">-", "|+", ">+"):
            j, buf = i + 1, []
            while j < len(lines) and (not lines[j].strip() or len(lines[j]) - len(lines[j].lstrip(" ")) > indent):
                buf.append(lines[j].strip())
                j += 1
            out[key] = ("\n" if rest.startswith("|") else " ").join(buf).strip()
            i = j
        elif rest:
            if rest.startswith("[") and rest.endswith("]"):
                out[key] = [_scalar(x) for x in rest[1:-1].split(",") if x.strip()]
            else:
                out[key] = _scalar(rest)
            i += 1
        else:
            j = i + 1
            if j < len(lines):
                sub_ind = len(lines[j]) - len(lines[j].lstrip(" "))
                if sub_ind > indent or (sub_ind == indent and lines[j][indent:].startswith("- ")):
                    v, i = _yaml_block(lines, j, sub_ind)
                    out[key] = v
                    continue
            out[key] = ""
            i = j
    return out, i


def _localized(v) -> str:
    if isinstance(v, dict):
        return v.get("C") or v.get("en") or next(iter(v.values()), "") or ""
    return v or ""


def parse_dep11(text: str, origin: str = "") -> list[Component]:
    """Components from a DEP-11 Components file (multi-document YAML)."""
    out: list[Component] = []
    docs = re.split(r"^---\s*$", text, flags=re.M)
    header = True
    for d in docs:
        lines = [l.rstrip("\n") for l in d.splitlines() if l.strip() and not l.lstrip().startswith("#")]
        if not lines:
            continue
        data, _ = _yaml_block(lines, 0, 0)
        if not isinstance(data, dict):
            continue
        if header and data.get("File") == "DEP-11":
            origin = origin or data.get("Origin", "")
            header = False
            continue
        header = False
        cid = data.get("ID")
        if not cid:
            continue
        typ = data.get("Type", "")
        icon = data.get("Icon") or {}
        icon_name = ""
        if isinstance(icon, dict):
            cached = icon.get("cached")
            if isinstance(cached, list) and cached and isinstance(cached[0], dict):
                icon_name = cached[0].get("name", "")
            icon_name = icon_name or (icon.get("stock") if isinstance(icon.get("stock"), str) else "")
        comp = data.get("CompulsoryForDesktops") or []
        dev = data.get("Developer") or data.get("DeveloperName") or ""
        out.append(Component(
            id=cid, type=TYPE_ALIASES.get(typ, typ), name=_localized(data.get("Name")),
            summary=_localized(data.get("Summary")), package=data.get("Package", ""),
            urls=data.get("Url") if isinstance(data.get("Url"), dict) else {},
            compulsory=comp if isinstance(comp, list) else [comp], origin=origin, icon=icon_name,
            developer=_localized(dev.get("name") if isinstance(dev, dict) and "name" in dev else dev)))
    return out


# ---------------------------------------------------------------- AppStream XML (Fedora family, Flatpak remotes)
_LANG = "{http://www.w3.org/XML/1998/namespace}lang"


def _text(el, tag: str) -> str:
    best = ""
    for c in el.findall(tag):
        if c.get(_LANG) in (None, "C", "en"):
            return (c.text or "").strip()
        best = best or (c.text or "").strip()
    return best


def parse_xml(data: bytes | str, origin: str = "") -> list[Component]:
    """Components from an AppStream collection (<components>)."""
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        return []
    origin = origin or root.get("origin", "")
    out = []
    for c in root.iter("component"):
        cid = _text(c, "id")
        if not cid:
            continue
        typ = c.get("type", "")
        bundle = next((b.text or "" for b in c.findall("bundle") if b.get("type") == "flatpak"), "")
        icon = next(((i.text or "").strip() for i in c.findall("icon") if i.get("type") in ("cached", "stock")), "")
        dev = c.find("developer")
        out.append(Component(
            id=cid, type=TYPE_ALIASES.get(typ, typ), name=_text(c, "name"), summary=_text(c, "summary"),
            package=_text(c, "pkgname"), bundle=bundle.strip(),
            urls={u.get("type"): (u.text or "").strip() for u in c.findall("url") if u.get("type")},
            compulsory=[(x.text or "").strip() for x in c.findall("compulsory_for_desktop")],
            origin=origin, icon=icon,
            developer=_text(dev, "name") if dev is not None else _text(c, "developer_name")))
    return out


# ---------------------------------------------------------------- finding the files
def _deb_arch() -> str:
    return {"x86_64": "amd64", "arm64": "arm64"}.get(arch(), arch())


def dep11_files(root: str = "/") -> list[str]:
    return sorted(glob.glob(os.path.join(root, "var/lib/apt/lists", f"*_dep11_Components-{_deb_arch()}.yml*")))


def xml_files(root: str = "/") -> list[str]:
    out = []
    for d in ("usr/share/swcatalog/xml", "usr/share/app-info/xmls", "var/cache/swcatalog/xml", "var/cache/app-info/xmls"):
        out += sorted(glob.glob(os.path.join(root, d, "*.xml*")))
    return out


def flatpak_files(home: str | None = None, remote: str = "flathub") -> list[str]:
    """A Flatpak remote's AppStream, which flatpak keeps once the remote is added (16.1.3)."""
    home = home or os.path.expanduser("~")
    pats = [os.path.join(home, ".local/share/flatpak/appstream", remote, "*", "active", "appstream.xml*"),
            os.path.join("/var/lib/flatpak/appstream", remote, "*", "active", "appstream.xml*")]
    return sorted(p for pat in pats for p in glob.glob(pat))


def _read(path: str) -> bytes:
    with open(path, "rb") as f:
        data = f.read()
    return gzip.decompress(data) if path.endswith(".gz") or data[:2] == b"\x1f\x8b" else data


def _origin_from_name(path: str) -> str:
    """'archive.ubuntu.com_ubuntu_dists_noble_universe_dep11_Components-amd64.yml.gz' → 'noble/universe'."""
    m = re.search(r"_dists_(.+)_dep11_", os.path.basename(path))
    return m.group(1).replace("_", "/") if m else ""


class Catalog:
    """Every app component found on this computer (requirement 16.2.2)."""

    def __init__(self, components: list[Component] | None = None):
        self.components = [c for c in (components or []) if c.is_app]
        self._by_id: dict[str, Component] = {}
        self._by_pkg: dict[str, list[Component]] = {}
        self._by_url: dict[str, list[Component]] = {}
        for c in self.components:
            self._by_id.setdefault(c.id.lower(), c)
            if c.package:
                self._by_pkg.setdefault(c.package, []).append(c)
            for u in c.project_urls():
                self._by_url.setdefault(u, []).append(c)

    @classmethod
    def load(cls, root: str = "/", home: str | None = None, flatpak_remote: str = "flathub") -> "Catalog":
        """The distribution's catalog plus, when its remote is added, Flathub's."""
        comps: list[Component] = []
        for p in dep11_files(root):
            try:
                comps += parse_dep11(_read(p).decode("utf-8", "replace"), _origin_from_name(p))
            except (OSError, ValueError):
                continue
        for p in xml_files(root):
            try:
                comps += parse_xml(_read(p))
            except (OSError, ValueError):
                continue
        for p in flatpak_files(home, flatpak_remote):
            try:
                comps += [replace_origin(c, flatpak_remote) for c in parse_xml(_read(p))]
            except (OSError, ValueError):
                continue
        return cls(comps)

    @property
    def available(self) -> bool:
        return any(not c.bundle for c in self.components)

    def distro(self) -> list[Component]:
        return [c for c in self.components if not c.bundle]

    def flatpaks(self) -> list[Component]:
        return [c for c in self.components if c.bundle]

    def by_id(self, cid: str) -> Component | None:
        c = self._by_id.get((cid or "").lower())
        if c is None and cid and not cid.endswith(".desktop"):
            c = self._by_id.get(cid.lower() + ".desktop")
        return c

    def by_package(self, name: str) -> list[Component]:
        return self._by_pkg.get(name, [])

    def by_project(self, url: str) -> list[Component]:
        return self._by_url.get(url, [])

    def search(self, text: str, flatpak: bool | None = None, limit: int = 50) -> list[Component]:
        """Name, summary, ID and package matches, best first (requirement 16.2.3)."""
        words = [w for w in (text or "").lower().split() if w]
        scored = []
        for c in self.components:
            if flatpak is not None and bool(c.bundle) != flatpak:
                continue
            hay_name = c.name.lower()
            hay = f"{hay_name} {c.summary.lower()} {c.id.lower()} {c.package.lower()}"
            if words and not all(w in hay for w in words):
                continue
            score = sum(3 if w in hay_name else 1 for w in words) + (5 if hay_name == " ".join(words) else 0)
            scored.append((-score, c.name.lower(), c))
        scored.sort(key=lambda t: (t[0], t[1]))
        seen, out = set(), []
        for _, _, c in scored:
            key = (c.id.lower(), bool(c.bundle))
            if key not in seen:
                seen.add(key)
                out.append(c)
            if len(out) >= limit:
                break
        return out


def replace_origin(c: Component, origin: str) -> Component:
    c.origin = origin
    return c


_CACHE: dict = {}


def load_cached(root: str = "/") -> Catalog:
    """The catalog, read again only when one of its files changed."""
    files = dep11_files(root) + xml_files(root) + flatpak_files()
    stamp = tuple((f, os.path.getmtime(f)) for f in files if os.path.exists(f))
    if _CACHE.get("stamp") != stamp:
        _CACHE["catalog"], _CACHE["stamp"] = Catalog.load(root), stamp
    return _CACHE["catalog"]


def is_snap_transitional(apt_show: str) -> bool:
    """Ubuntu's packages that install a Snap (requirement 16.2.2): they depend on snapd and say
    they're transitional."""
    deps = " ".join(re.findall(r"^(?:Pre-)?Depends:\s*(.*)$", apt_show, re.M))
    desc = " ".join(re.findall(r"^Description(?:-\w+)?:\s*(.*)$", apt_show, re.M)).lower()
    ver = " ".join(re.findall(r"^Version:\s*(.*)$", apt_show, re.M))
    return bool(re.search(r"\bsnapd\b", deps)) and ("transitional" in desc or "snap" in ver)


def snap_shims(packages: list[str]) -> set[str]:
    """Which of these packages are Snap transitional packages (Debian family only)."""
    import shutil
    import subprocess
    if not packages or not shutil.which("apt-cache"):
        return set()
    p = subprocess.run(["apt-cache", "show", "--no-all-versions", *packages], capture_output=True, text=True)
    out = set()
    for block in re.split(r"\n\s*\n", p.stdout):
        m = re.search(r"^Package:\s*(\S+)", block, re.M)
        if m and is_snap_transitional(block):
            out.add(m.group(1))
    return out
