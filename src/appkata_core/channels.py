"""Package channels (requirement 16.1): which Flatpak and which distribution package an app has,
whether each link checks out against the project, how a package's version maps to the project's,
and which way to install is recommended."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field

from . import urls, versions
from .db import DB, now
from .http import Http, NotFound, SourceError
from .platform import OS, linux_family

FLATHUB_API = "https://flathub.org/api/v2"
RAW = "https://raw.githubusercontent.com"
MATCHES, UNCHECKED, MISMATCH = "matches", "unchecked", "mismatch"


def in_own_flatpak() -> bool:
    """AppKata runs inside a Flatpak sandbox (there's no Flatpak of AppKata, but it can be run in one):
    channels are off there (requirement 16.10)."""
    return os.path.exists("/.flatpak-info")


def enabled() -> bool:
    return OS == "linux" and not in_own_flatpak()


def manager() -> str:
    """"apt" or "dnf" for this computer's distribution, or ""."""
    fam = linux_family()
    return {"debian": "apt", "fedora": "dnf"}.get(fam, "")


def distro_name() -> str:
    """"Ubuntu", "Fedora", "Linux Mint"… for labels (16.2.3, 16.3.1)."""
    from .autoupdate import os_release
    name = os_release().get("NAME", "").replace(" GNU/Linux", "").strip()
    if name.endswith(" Linux") and not name.startswith("Linux"):        # "Fedora Linux" → "Fedora"
        name = name[:-6]
    return name or "Distribution"


# ---------------------------------------------------------------- Trusts' lines (10.3.1)
def _trusts_for(db: DB, url: str) -> list[dict]:
    """Trusts' channel lines for an app (`Flatpak`, `Debian package`, `Fedora package`, `Channel`, as
    trustfile parses them), for the installed version, else the newest review (10.3.3); yours first,
    then Score, then name (requirement 16.1.3)."""
    from . import trustfile
    rows = db.all("""SELECT r.settings, t.name, t.own, t.score FROM reviews r JOIN trusts t ON t.id=r.trust_id
                     WHERE r.url=? AND t.enabled=1 AND (t.own=1 OR t.verified_commit IS NOT NULL)""", (url,))
    inst = db.one("SELECT version FROM installs WHERE url=?", (url,))
    meta = db.one("SELECT releases FROM apps WHERE url=?", (url,))
    dates = {r.get("version"): r.get("date", "") for r in json.loads((meta or {}).get("releases") or "[]")}
    out = []
    for r in rows:
        try:
            s = json.loads(r["settings"] or "{}")
        except ValueError:
            s = {}
        o = trustfile.resolve_settings(s, "linux", inst["version"] if inst else None, dates)
        ch = str(o.get("channel") or "").lower()
        out.append({"name": r["name"], "own": r["own"], "score": r["score"], "flatpak": str(o.get("flatpak") or ""),
                    "debian": str(o.get("debianPackage") or ""), "fedora": str(o.get("fedoraPackage") or ""),
                    "channel": ch if ch in ("release", "flatpak", "package") else ""})
    return sorted(out, key=lambda r: (not r["own"], -(5 if r["own"] else int(r["score"] or 3)), (r["name"] or "").lower()))


# ---------------------------------------------------------------- links (16.1.3)
@dataclass
class Link:
    kind: str                 # "flatpak" | "package"
    value: str                # app ID, or package name
    remote: str = "flathub"   # for a Flatpak
    manager: str = ""         # for a package: "apt" | "dnf"
    source: str = ""          # "you" | "trust" | "appstream"
    via: str = ""             # the Trust's name, or the AppStream component ID
    extra: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {"kind": self.kind, "value": self.value, "remote": self.remote, "manager": self.manager,
                "source": self.source, "via": self.via}


def _flatpak_value(v: str) -> tuple[str, str]:
    parts = v.split()
    return (parts[0], parts[1]) if len(parts) >= 2 else ("flathub", parts[0] if parts else "")


def links(db: DB, url: str, catalog=None, mgr: str | None = None, ignore_mine: bool = False) -> dict[str, Link]:
    """The app's Flatpak and package, the first that applies of: yours (Source settings), a Trust's
    lines, AppStream (requirement 16.1.3). A name match alone never links. `ignore_mine`: what would
    apply without yours (Source settings' placeholders, 2.6.7)."""
    mgr = manager() if mgr is None else mgr
    out: dict[str, Link] = {}
    src = None if ignore_mine else db.one("SELECT settings FROM sources WHERE url=?", (url,))
    mine = json.loads(src["settings"] or "{}") if src else {}
    if mine.get("flatpak"):
        remote, app_id = _flatpak_value(mine["flatpak"])
        out["flatpak"] = Link("flatpak", app_id, remote, source="you")
    if mine.get("package") and mgr:
        out["package"] = Link("package", mine["package"], manager=mgr, source="you")
    for t in _trusts_for(db, url):
        if "flatpak" not in out and t["flatpak"]:
            remote, app_id = _flatpak_value(t["flatpak"])
            out["flatpak"] = Link("flatpak", app_id, remote, source="trust", via=t["name"])
        pkg = t["debian"] if mgr == "apt" else t["fedora"] if mgr == "dnf" else ""
        if "package" not in out and pkg:
            out["package"] = Link("package", pkg, manager=mgr, source="trust", via=t["name"])
    if catalog is not None and ("flatpak" not in out or "package" not in out):
        meta = db.one("SELECT appstream_id FROM app_meta WHERE url=?", (url,))
        aid = (meta or {}).get("appstream_id") or ""
        comps = list(catalog.by_project(url))
        if aid:
            c = catalog.by_id(aid)
            comps += [c] if c else []
            comps += [x for x in catalog.components if x.bundle and x.id.lower().removesuffix(".desktop") == aid.lower().removesuffix(".desktop")]
        for c in comps:
            if c.bundle and "flatpak" not in out:
                out["flatpak"] = Link("flatpak", c.id.removesuffix(".desktop"), c.origin or "flathub",
                                      source="appstream", via=c.id)
            elif not c.bundle and c.package and "package" not in out and mgr:
                out["package"] = Link("package", c.package, manager=mgr, source="appstream", via=c.id,
                                      extra={"origin": c.origin})
    return out


def recommended_channel(db: DB, url: str) -> tuple[str, str]:
    """(channel, Trust name) from the first Trust with a `Channel` line (16.3.2), or ("", "")."""
    for t in _trusts_for(db, url):
        if t["channel"]:
            return t["channel"], t["name"]
    return "", ""


# ---------------------------------------------------------------- link checks (16.1.4, 16.1.5)
def get_check(db: DB, url: str, kind: str, value: str) -> dict:
    return db.one("SELECT * FROM channel_checks WHERE url=? AND kind=? AND value=?", (url, kind, value)) or \
        {"url": url, "kind": kind, "value": value, "state": UNCHECKED, "detail": "", "verified": None, "etag": "",
         "commit_seen": "", "version_seen": "", "tag": "", "built_from": "", "checked_at": None}


def _save_check(db: DB, c: dict) -> dict:
    c["checked_at"] = now()
    db.x("""INSERT OR REPLACE INTO channel_checks(url, kind, value, state, detail, verified, etag, commit_seen,
            version_seen, tag, built_from, checked_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
         (c["url"], c["kind"], c["value"], c["state"], c["detail"], c["verified"], c["etag"], c["commit_seen"],
          c["version_seen"], c["tag"], c.get("built_from", ""), c["checked_at"]))
    return c


_FORGES = ("github.com", "gitlab.com", "codeberg.org", "gitlab.gnome.org", "invent.kde.org", "gitlab.freedesktop.org",
           "git.sr.ht", "salsa.debian.org", "bitbucket.org")


def project_of(u: str) -> str:
    """The forge project a download or repository URL belongs to, normalized, or ""."""
    u = (u or "").strip().strip("'\"")
    if not u:
        return ""
    m = re.match(r"^(?:https?|git)://([^/]+)/([^/?#]+)/([^/?#]+)", u) or \
        re.match(r"^(?:[\w.-]+@)?([\w.-]+):([^/]+)/([^/?#]+)", u)
    if not m:
        return ""
    host, owner, name = m.group(1).lower(), m.group(2), m.group(3)
    if name.endswith(".git"):
        name = name[:-4]
    if host not in _FORGES and not host.startswith(("gitlab.", "git.", "codeberg.")):
        return urls.try_normalize(u) or ""
    return urls.try_normalize(f"https://{host}/{owner}/{name}") or ""


def parse_manifest(text: str) -> list[dict]:
    """The sources in a flatpak-builder manifest (YAML or JSON): [{"type", "url", "tag", "commit"}]."""
    out, cur = [], None
    for m in re.finditer(r'(?m)(?:^|[\s{,\-])"?(type|url|tag|commit|branch)"?\s*:\s*"?([^"\s,}\]#]+)', text):
        k, v = m.group(1), m.group(2).strip()
        if k == "type" or cur is None or (k == "url" and cur.get("url")):
            cur = {"type": v if k == "type" else "", "url": "", "tag": "", "commit": ""}
            out.append(cur)
            if k == "type":
                continue
        cur[k] = v
    return [s for s in out if s.get("url")]


def _verified_flag(http: Http, app_id: str, etag: str) -> tuple[bool | None, str]:
    """Flathub's verified flag as a conditional request: (flag, etag); flag None when unchanged or
    unreachable (16.1.5)."""
    try:
        data, hdr, _ = http.request(f"{FLATHUB_API}/verification/{app_id}/status",
                                    headers={"If-None-Match": etag} if etag else None)
    except SourceError:            # unreachable, or 304 Not Modified: keep what we knew
        return None, etag
    try:
        d = json.loads(data.decode("utf-8"))
    except ValueError:
        return None, etag
    return bool(d.get("verified")), hdr.get("etag", "")


def _manifest(http: Http, app_id: str) -> str:
    for ext in ("yml", "yaml", "json"):
        try:
            return http.text(f"{RAW}/flathub/{app_id}/HEAD/{app_id}.{ext}")
        except NotFound:
            continue
    raise NotFound(f"no manifest for {app_id}")


def check_flatpak(db: DB, http: Http, url: str, app_id: str, remote_commit: str = "", metainfo_id: str = "") -> dict:
    """Requirement 16.1.4: the metainfo ID, Flathub's verified flag (every sync), and the build
    manifest's sources (only when the remote's commit changed)."""
    c = get_check(db, url, "flatpak", app_id)
    flag, c["etag"] = _verified_flag(http, app_id, c.get("etag") or "")
    if flag is not None:
        c["verified"] = int(flag)
    need_manifest = (remote_commit and remote_commit != c.get("commit_seen")) or (not remote_commit and not c.get("checked_at"))
    if need_manifest:
        try:
            srcs = parse_manifest(_manifest(http, app_id))
            projects = [project_of(s["url"]) for s in srcs]
            hit = next((s for s, p in zip(srcs, projects) if p == url), None)
            if hit:
                c["state"], c["detail"] = MATCHES, ""
                c["tag"] = hit.get("tag") or ""
                c["built_from"] = hit.get("tag") or (hit.get("commit") or "")[:10]
            elif any(projects):
                others = [p for p in projects if p and not p.startswith("https://github.com/flathub/")]
                c["state"] = MISMATCH if others else UNCHECKED
                c["detail"] = f"its build comes from {others[-1].split('://', 1)[1]}" if others else ""
            c["commit_seen"] = remote_commit or c.get("commit_seen", "")
        except SourceError:
            pass                   # Flathub or GitHub unreachable: keep what we knew (UNCHECKED at first)
    if c["state"] == UNCHECKED and metainfo_id and metainfo_id.removesuffix(".desktop").lower() == app_id.lower():
        c["state"], c["detail"] = MATCHES, "same ID as the project's metainfo"
    return _save_check(db, c)


def _deb_source(pkg: str) -> str:
    from .pkgbackend import _text
    m = re.search(r"^Source:\s*(\S+)", _text(["apt-cache", "show", "--no-all-versions", pkg]), re.M)
    return m.group(1) if m else pkg


def _debian_metadata(http: Http, src: str) -> str:
    d = http.json(f"https://sources.debian.org/api/src/{src}/")
    vers = [v.get("version") for v in d.get("versions", []) if v.get("version")]
    if not vers:
        raise NotFound(src)
    prefix = src[:4] if src.startswith("lib") else src[:1]
    return http.text(f"https://sources.debian.org/data/main/{prefix}/{src}/{vers[0]}/debian/upstream/metadata")


def _fedora_spec(http: Http, src: str) -> str:
    return http.text(f"https://src.fedoraproject.org/rpms/{src}/raw/rawhide/f/{src}.spec")


def spec_urls(spec: str) -> list[str]:
    """URL and Source0 from an rpm spec, with %{name}, %{url} and simple %global macros expanded."""
    macros = {}
    for m in re.finditer(r"^%(?:global|define)\s+(\w+)\s+(.+)$", spec, re.M):
        macros[m.group(1)] = m.group(2).strip()
    nm = re.search(r"^Name:\s*(\S+)", spec, re.M)
    if nm:
        macros["name"] = nm.group(1)
    um = re.search(r"^URL:\s*(\S+)", spec, re.M | re.I)
    if um:
        macros["url"] = um.group(1)

    def expand(s: str) -> str:
        for _ in range(4):
            s = re.sub(r"%\{\??(\w+)\}", lambda m: macros.get(m.group(1), m.group(0)), s)
        return s
    out = [expand(macros["url"])] if "url" in macros else []
    sm = re.search(r"^Source0?:\s*(\S+)", spec, re.M | re.I)
    if sm:
        out.append(expand(sm.group(1)))
    return out


def check_package(db: DB, http: Http, url: str, name: str, version: str, catalog=None, mgr: str | None = None) -> dict:
    """Requirement 16.1.4 for a package: the AppStream URLs, then the packaging's own metadata
    (Debian's debian/upstream/metadata, Fedora's spec), read again only when the version changes."""
    mgr = manager() if mgr is None else mgr
    c = get_check(db, url, "package", name)
    if catalog is not None:
        for comp in catalog.by_package(name):
            if url in comp.project_urls():
                c["state"], c["detail"] = MATCHES, "AppStream"
                c["version_seen"] = version
                return _save_check(db, c)
    if c.get("version_seen") == version and c.get("checked_at"):
        return c
    try:
        if mgr == "apt":
            text = _debian_metadata(http, _deb_source(name))
            found = [project_of(m.group(1)) for m in re.finditer(r"^Repository(?:-Browse)?:\s*(\S+)", text, re.M)]
        else:
            found = [project_of(u) for u in spec_urls(_fedora_spec(http, name))]
        found = [f for f in found if f]
        if url in found:
            c["state"], c["detail"] = MATCHES, ""
        elif found:
            c["state"], c["detail"] = MISMATCH, f"its packaging points to {found[0].split('://', 1)[1]}"
        c["version_seen"] = version
    except SourceError:
        pass
    return _save_check(db, c)


# ---------------------------------------------------------------- versions (16.7)
def project_version(kind: str, version: str) -> str:
    """A channel's version as the project's (requirement 16.7.1)."""
    v = (version or "").strip()
    if kind in ("apt", "deb", "debian"):
        v = v.split(":", 1)[1] if re.match(r"^\d+:", v) else v
        if "-" in v:
            v = v.rsplit("-", 1)[0]
        v = re.split(r"[+~](?:dfsg|ds|repack|really|git|nmu|deb|ubuntu)", v, maxsplit=1)[0]
        v = re.sub(r"[+~]$", "", v)
    elif kind in ("dnf", "rpm", "fedora"):
        v = v.split(":", 1)[1] if re.match(r"^\d+:", v) else v
        if "-" in v and re.search(r"-[^-]*\.(?:fc|el|mga|suse)\d*", v + "."):
            v = v.rsplit("-", 1)[0]
        elif re.match(r"^[\d.]+-\d+(\.\w+)*$", v):
            v = v.rsplit("-", 1)[0]
    return versions.clean(v)


def releases_behind(releases: list[dict], version: str) -> int:
    """How many of the project's stable releases are newer than `version` (requirement 16.7.2)."""
    if not version:
        return 0
    return sum(1 for r in releases if not r.get("prerelease") and r.get("version")
               and versions.compare(r["version"], version) == 1)


# ---------------------------------------------------------------- the install dialog's cards (16.3.1, 16.3.2)
def options(db: DB, url: str, release_files: list[dict], found: dict[str, Link], checks: dict[str, dict] | None = None,
            facts: dict[str, dict] | None = None) -> list[dict]:
    """Every way to install the app here, Recommended first. `release_files` are the release's cards
    in the order of 4.2; `checks` the link checks by kind; `facts` what's known about each channel
    (version, size…), passed through."""
    checks = checks or {}
    facts = facts or {}
    cards: list[dict] = []
    fl = found.get("flatpak")
    pk = found.get("package")
    flc = checks.get("flatpak", {})
    pkc = checks.get("package", {})

    def chan(kind: str, link: Link, chk: dict) -> dict:
        return {"channel": kind, "value": link.value, "remote": link.remote, "manager": link.manager,
                "source": link.source, "via": link.via, "state": chk.get("state", UNCHECKED),
                "detail": chk.get("detail", ""), "verified": chk.get("verified"), "builtFrom": chk.get("built_from", ""),
                **facts.get(kind, {})}

    verified_fp = fl and flc.get("verified") and flc.get("state") != MISMATCH
    if verified_fp:
        cards.append(chan("flatpak", fl, flc))
    cards += [{"channel": "release", **f} for f in release_files]
    if fl and not verified_fp:
        cards.append(chan("flatpak", fl, flc))
    if pk:
        cards.append(chan("package", pk, pkc))
    cards.sort(key=lambda c: c.get("state") == MISMATCH)          # a failed check comes last
    rec, by = recommended_channel(db, url)
    if rec:
        i = next((i for i, c in enumerate(cards) if c["channel"] == rec and c.get("state") != MISMATCH), None)
        if i is not None:
            cards.insert(0, cards.pop(i))
            cards[0]["recommendedBy"] = by
    for i, c in enumerate(cards):
        c["recommended"] = i == 0 and c.get("state") != MISMATCH
    return cards


# ---------------------------------------------------------------- who updates it (16.5.1)
def update_state(rec: dict, det, releases: list[dict] | None = None) -> tuple[str, str]:
    """("system", who) | ("not-updated", "") | ("appkata", "") | ("held", "") for a channel install."""
    from . import autoupdate
    if rec.get("held"):
        return "held", ""
    if rec.get("updates") == "appkata":
        return "appkata", ""
    if rec.get("channel") == "flatpak":
        who = autoupdate.flatpak_owner(det)
    elif rec.get("channel") == "package":
        who = autoupdate.package_owner(det, rec.get("manager", ""), releases)
    else:
        return "appkata", ""
    if rec.get("updates") == "system":
        return "system", who or "the system"
    return ("system", who) if who else ("not-updated", "")
