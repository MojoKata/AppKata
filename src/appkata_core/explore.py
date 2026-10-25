"""Explore (requirement 7.7): search well-known forges, and ngit on Nostr relays, for projects."""

from __future__ import annotations

import html
import re
from dataclasses import asdict, dataclass, field
from urllib.parse import quote

from . import nostr
from .http import Http, RateLimited, SourceError

SERVICES = [("github", "GitHub"), ("gitlab", "GitLab"), ("codeberg", "Codeberg"), ("ngit", "ngit")]


@dataclass
class Match:
    name: str
    owner: str
    url: str                 # what Add source uses ("" when it can't be added yet)
    page: str                # the project page to open
    description: str = ""
    stars: int = 0
    updated: str = ""
    language: str = ""
    archived: bool = False
    topics: list[str] = field(default_factory=list)
    service: str = ""
    addable: bool = True
    channel: str = ""        # Flathub and the distribution (requirement 16.2.3): "flatpak" | "package"
    link: str = ""           # the app ID, or the package name
    verified: bool | None = None
    found: str = ""          # where the project URL came from ("AppStream")

    def dict(self) -> dict:
        return asdict(self)


def _strip(s: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", s or ""))


def github(http: Http, q: str, limit: int = 20) -> list[Match]:
    try:
        d = http.json(f"https://api.github.com/search/repositories?q={quote(q)}&per_page={limit}",
                      token_host="github.com", accept="application/vnd.github+json")
        return [Match(i["name"], i["owner"]["login"], i["html_url"], i["html_url"], i.get("description") or "",
                      i.get("stargazers_count", 0), i.get("pushed_at") or i.get("updated_at") or "", i.get("language") or "",
                      bool(i.get("archived")), (i.get("topics") or [])[:5], "github")
                for i in d.get("items", [])[:limit]]
    except RateLimited:
        pass       # github.com's own search page answers JSON too, without the API's limit
    d = http.json(f"https://github.com/search?q={quote(q)}&type=repositories", token_host="github.com")
    out = []
    for r in (d.get("payload") or {}).get("blackbirdSearchRoute", {}).get("results", [])[:limit]:
        full = _strip(r.get("hl_name", ""))
        owner, _, name = full.partition("/")
        repo = (r.get("repo") or {}).get("repository") or {}
        out.append(Match(name, owner, f"https://github.com/{full}", f"https://github.com/{full}",
                         _strip(r.get("hl_trunc_description", "")), int(r.get("followers") or 0), repo.get("updated_at", ""),
                         r.get("language") or "", bool(r.get("archived")), (r.get("topics") or [])[:5], "github"))
    return out


def gitlab(http: Http, q: str, limit: int = 20, host: str = "gitlab.com") -> list[Match]:
    d = http.json(f"https://{host}/api/v4/projects?search={quote(q)}&order_by=star_count&sort=desc&per_page={limit}&simple=true",
                  token_host=host)
    return [Match(p.get("name", ""), (p.get("namespace") or {}).get("full_path", "") or p.get("path_with_namespace", "").rsplit("/", 1)[0],
                  p.get("web_url", ""), p.get("web_url", ""), p.get("description") or "", p.get("star_count", 0),
                  p.get("last_activity_at", ""), "", bool(p.get("archived")), (p.get("topics") or [])[:5], "gitlab")
            for p in d[:limit]]


def codeberg(http: Http, q: str, limit: int = 20, host: str = "codeberg.org") -> list[Match]:
    d = http.json(f"https://{host}/api/v1/repos/search?q={quote(q)}&sort=stars&order=desc&limit={limit}", token_host=host)
    return [Match(r.get("name", ""), (r.get("owner") or {}).get("login", ""), r.get("html_url", ""), r.get("html_url", ""),
                  r.get("description") or "", r.get("stars_count", 0), r.get("updated_at", ""), r.get("language") or "",
                  bool(r.get("archived")), (r.get("topics") or [])[:5], "codeberg")
            for r in (d.get("data") or [])[:limit]]


def ngit(q: str, relays: list[str] | None = None, limit: int = 20) -> tuple[list[Match], list[str]]:
    """ngit repository announcements matching the query. They open on gitworkshop.dev; adding one
    as a Source waits for ngit Sources (requirement 2.4.3)."""
    events, errors = nostr.repo_announcements(relays or nostr.DEFAULT_RELAYS)
    words = q.lower().split()
    out = []
    for e in events:
        tags = {}
        for t in e.get("tags", []):
            if t and len(t) > 1:
                tags.setdefault(t[0], t[1])
        name, desc, ident = tags.get("name") or tags.get("d", ""), tags.get("description", ""), tags.get("d", "")
        hay = f"{name} {desc} {ident}".lower()
        if words and not all(w in hay for w in words):
            continue
        np = nostr.npub(e["pubkey"])
        out.append(Match(name, np[:12] + "…", "", f"https://gitworkshop.dev/{np}/{ident}", desc,
                         updated=_iso(e.get("created_at", 0)), service="ngit", addable=False))
    out.sort(key=lambda m: m.updated, reverse=True)
    return out[:limit], errors


def _iso(ts: int) -> str:
    from datetime import datetime, timezone
    return datetime.fromtimestamp(ts, timezone.utc).isoformat().replace("+00:00", "Z") if ts else ""


FLATHUB = "https://flathub.org/api/v2"


def _component_match(c, service: str, channel: str) -> Match:
    """An AppStream component as a match: adding it needs its project's git URL (requirement 16.2.4)."""
    proj = (c.project_urls() or [""])[0]
    owner, name = (proj.split("://", 1)[-1].split("/")[1:3] + ["", ""])[:2] if proj else ("", "")
    link = c.id.removesuffix(".desktop") if channel == "flatpak" else c.package
    return Match(c.name or c.id, owner, proj, proj or c.urls.get("homepage", ""), c.summary, service=service,
                 addable=bool(proj), channel=channel, link=link, found="AppStream" if proj else "")


def flathub(http: Http, q: str, catalog=None, limit: int = 15) -> tuple[list[Match], str]:
    """Flathub's search, each match's project URL from its AppStream data. Flathub unreachable: the
    Flathub catalog already on this computer, with a note (requirement 16.2.3)."""
    import json as _json
    from . import urls
    try:
        d = _json.loads(http.request(f"{FLATHUB}/search", method="POST", body=_json.dumps({"query": q}).encode(),
                                     headers={"Content-Type": "application/json"})[0].decode("utf-8"))
    except (SourceError, ValueError) as e:
        local = [c for c in (catalog.search(q, flatpak=True, limit=limit) if catalog is not None else [])]
        note = "Couldn't reach Flathub (" + str(e) + ")."
        if local:
            return [_component_match(c, "flathub", "flatpak") for c in local], \
                note + " These are from the Flathub catalog on this computer."
        return [], note
    out = []
    for h in (d.get("hits") or [])[:limit]:
        app_id = h.get("app_id") or h.get("id") or ""
        proj, found = "", ""
        try:
            a = http.json(f"{FLATHUB}/appstream/{app_id}")
            for k in ("vcs_browser", "homepage", "bugtracker"):
                u = urls.try_normalize((a.get("urls") or {}).get(k) or "")
                if u and u.split("://", 1)[-1].count("/") == 2:
                    proj, found = u, "AppStream"
                    break
        except SourceError:
            pass
        owner, name = (proj.split("://", 1)[-1].split("/")[1:3] if proj else ["", ""])
        out.append(Match(h.get("name") or app_id, owner, proj, proj or f"https://flathub.org/apps/{app_id}",
                         h.get("summary") or "", service="flathub", addable=bool(proj), channel="flatpak", link=app_id,
                         verified=bool(h.get("verification_verified")), found=found))
    return out, ""


def distro(q: str, catalog=None, limit: int = 30) -> tuple[list[Match], str]:
    """The distribution's AppStream catalog, offline (requirement 16.2.2, 16.2.3)."""
    if catalog is None or not catalog.available:
        return [], "No AppStream catalog on this computer."
    return [_component_match(c, "distro", "package") for c in catalog.search(q, flatpak=False, limit=limit)], ""


def search(http: Http, service: str, q: str, relays: list[str] | None = None, catalog=None) -> dict:
    """{matches: [...], error: "", note: ""} for the Explore dialog."""
    q = q.strip()
    if not q:
        return {"matches": [], "error": ""}
    try:
        if service == "github":
            m = github(http, q)
        elif service == "gitlab":
            m = gitlab(http, q)
        elif service == "codeberg":
            m = codeberg(http, q)
        elif service in ("flathub", "distro"):
            m, note = flathub(http, q, catalog) if service == "flathub" else distro(q, catalog)
            if not m and note:
                return {"matches": [], "error": note}
            return {"matches": [x.dict() for x in m], "error": "", "note": note}
        elif service == "ngit":
            m, errs = ngit(q, relays)
            if not m and errs:
                return {"matches": [], "error": "Couldn't reach any Nostr relay (" + "; ".join(errs[:2]) + ")"}
        else:
            return {"matches": [], "error": f"unknown service {service}"}
    except SourceError as e:
        return {"matches": [], "error": str(e)}
    return {"matches": [x.dict() for x in m], "error": ""}
