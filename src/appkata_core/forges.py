"""Forge APIs: from a project to its releases, README and files (requirement 2.4)."""

from __future__ import annotations

import html as _html
import re as _re
import subprocess as _sp
from dataclasses import dataclass, field
from urllib.parse import quote

from .http import Http, NotFound, RateLimited, Renamed, Unsupported
from .urls import Repo
from . import versions


@dataclass
class Asset:
    name: str
    url: str
    size: int = 0
    digest: str = ""          # "sha256:<hex>" when the forge provides one
    content_type: str = ""


@dataclass
class Release:
    tag: str
    name: str
    version: str
    date: str                 # ISO 8601
    prerelease: bool = False
    notes: str = ""
    assets: list[Asset] = field(default_factory=list)
    html_url: str = ""


@dataclass
class RepoInfo:
    name: str
    description: str = ""
    default_branch: str = "main"
    avatar_url: str = ""
    html_url: str = ""
    archived: bool = False
    topics: list[str] = field(default_factory=list)


class Forge:
    kind = "?"
    label = "?"

    def __init__(self, http: Http, repo: Repo):
        self.http, self.repo = http, repo

    # each forge implements these
    def info(self) -> RepoInfo: raise NotImplementedError
    def releases(self, limit: int = 30) -> list[Release]: raise NotImplementedError
    def tags(self, limit: int = 30) -> list[Release]: raise NotImplementedError
    def tree(self, ref: str) -> list[str]: raise NotImplementedError
    def raw_url(self, path: str, ref: str) -> str: raise NotImplementedError

    def raw(self, path: str, ref: str) -> bytes:
        return self.http.bytes(self.raw_url(path, ref), token_host=self.repo.host)

    def readme(self, ref: str, paths: list[str]) -> tuple[str, str]:
        """(markdown, path) of the README at the repository root, or ("", "")."""
        for name in ("README.md", "readme.md", "Readme.md", "README.markdown", "README.rst", "README.txt", "README"):
            if name in paths:
                try:
                    return self.raw(name, ref).decode("utf-8", "replace"), name
                except NotFound:
                    continue
        return "", ""


def _git_out(args: list[str]) -> str:
    p = _sp.run(["git", *args], capture_output=True, text=True, timeout=120,
                env={"GIT_TERMINAL_PROMPT": "0", "PATH": __import__("os").environ.get("PATH", ""), "HOME": __import__("os").environ.get("HOME", "")})
    return p.stdout if p.returncode == 0 else ""


def _html_unescape(s: str) -> str:
    return _html.unescape(s)


def _html_to_text(h: str) -> str:
    """Release notes from the Atom feed's HTML, as simple Markdown."""
    t = _re.sub(r"<h[1-6][^>]*>", "\n### ", h)
    t = _re.sub(r"<li[^>]*>", "\n- ", t)
    t = _re.sub(r"<(br|/p|/h[1-6]|/ul|/ol)[^>]*>", "\n", t)
    t = _re.sub(r"<a [^>]*href=\"([^\"]+)\"[^>]*>(.*?)</a>", r"[\2](\1)", t, flags=_re.S)
    t = _re.sub(r"<(strong|b)>(.*?)</\1>", r"**\2**", t, flags=_re.S)
    t = _re.sub(r"<code>(.*?)</code>", r"`\1`", t, flags=_re.S)
    t = _re.sub(r"<[^>]+>", "", t)
    t = _html.unescape(t)
    return _re.sub(r"\n{3,}", "\n\n", t).strip()


def _ver(tag: str, name: str) -> str:
    v = versions.clean(tag)
    return v if versions.is_semverish(v) or not name else (versions.clean(name) if versions.is_semverish(versions.clean(name)) else v)


class GitHub(Forge):
    """GitHub's REST API, falling back to github.com's own pages and git when the API's rate limit
    is used up (60 requests an hour without a token): the releases Atom feed, each release's assets
    page (names, sizes, SHA-256 digests) and a shallow, blob-less clone for the file list."""
    kind, label = "github", "GitHub"

    def __init__(self, http: Http, repo: Repo, api: str | None = None):
        super().__init__(http, repo)
        self.api = api or ("https://api.github.com" if repo.host == "github.com" else f"https://{repo.host}/api/v3")
        self.base = f"{self.api}/repos/{repo.path}"
        self.web = repo.host == "github.com" and self._api_limited()

    def _api_limited(self) -> bool:
        import time
        reset = self.http.limited.get("api.github.com")
        return bool(reset and reset > time.time())

    def _get(self, url: str):
        data, hdr, final = self.http.json_with_headers(url, token_host=self.repo.host,
                                                       accept="application/vnd.github+json")
        return data

    def _try(self, api_call, web_call):
        if not self.web:
            try:
                return api_call()
            except RateLimited:
                if self.repo.host != "github.com":
                    raise
                self.web = True
        return web_call()

    def info(self) -> RepoInfo:
        return self._try(self._info_api, self._info_web)

    def releases(self, limit: int = 30) -> list[Release]:
        return self._try(lambda: self._releases_api(limit), lambda: self._releases_web(limit))

    def tags(self, limit: int = 30) -> list[Release]:
        return self._try(lambda: self._tags_api(limit), lambda: self._tags_web(limit))

    def tree(self, ref: str) -> list[str]:
        return self._try(lambda: self._tree_api(ref), lambda: self._tree_web(ref))

    # ---- web fallback
    def _info_web(self) -> RepoInfo:
        import re
        data, hdr, final = self.http.request(f"https://github.com/{self.repo.path}", accept="text/html")
        page = data.decode("utf-8", "replace")
        moved = final.rstrip("/").split("github.com/", 1)[-1]
        if moved and moved.lower() != self.repo.path.lower() and moved.count("/") == 1:
            raise Renamed(f"https://github.com/{moved}")
        m = re.search(r'<meta name="description" content="([^"]*)"', page)
        desc = _html_unescape(m.group(1)) if m else ""
        desc = re.sub(r"\s+-\s+" + re.escape(self.repo.path) + r"$", "", desc, flags=re.I)
        if desc.lower().startswith("contribute to " + self.repo.path.lower()):
            desc = ""
        branch = "main"
        out = _git_out(["ls-remote", "--symref", f"https://github.com/{self.repo.path}", "HEAD"])
        m = re.search(r"ref: refs/heads/(\S+)\s+HEAD", out)
        if m:
            branch = m.group(1)
        return RepoInfo(name=self.repo.name, description=desc, default_branch=branch,
                        avatar_url=f"https://github.com/{self.repo.owner}.png?size=256", html_url=f"https://github.com/{self.repo.path}",
                        archived="This repository has been archived" in page)

    def _releases_web(self, limit: int) -> list[Release]:
        import re
        import xml.etree.ElementTree as ET
        try:
            atom = self.http.text(f"https://github.com/{self.repo.path}/releases.atom")
        except NotFound:
            return []
        ns = {"a": "http://www.w3.org/2005/Atom"}
        try:
            root = ET.fromstring(atom)
        except ET.ParseError:
            return []
        out, stable, pre, pages = [], 0, 0, 0
        released = self._release_tags_web()
        for i, e in enumerate(root.findall("a:entry", ns)[:limit]):
            link = e.find("a:link", ns)
            href = link.attrib.get("href", "") if link is not None else ""
            tag = href.rsplit("/releases/tag/", 1)[-1] if "/releases/tag/" in href else (e.findtext("a:title", "", ns))
            from urllib.parse import unquote
            tag = unquote(tag)
            # the feed lists bare tags too, which the API doesn't count as releases (review 3, R3-23:
            # Upscayl's tag v2.15.1 was its "latest", with no files): one not on the releases page
            # whose own page says "tagged this" is left out
            if released is not None and tag not in released and self._bare_tag_web(tag):
                continue
            title = e.findtext("a:title", "", ns) or tag
            notes = _html_to_text(e.findtext("a:content", "", ns) or "")
            # a prerelease as GitHub marks it on the releases page, else as its tag reads (Upscayl marks
            # v2.10.9 a prerelease, which the API said and the tag didn't)
            pre = released[tag] if released and tag in released else versions.is_prerelease(versions.clean(tag))
            rel = Release(tag=tag, name=title, version=_ver(tag, title), date=e.findtext("a:updated", "", ns),
                          prerelease=pre, notes=notes, html_url=href)
            # files for the newest three stable releases and the newest prerelease, one page request each;
            # an entry with no files (a release with only source, or a bare tag the check above couldn't
            # rule out) doesn't count, up to 8 pages
            if pages < 8 and ((stable < 3 and not rel.prerelease) or (pre < 1 and rel.prerelease)):
                rel.assets, published = self._assets_web(tag)
                pages += 1
                rel.date = published or rel.date
                if rel.assets:
                    stable += not rel.prerelease
                    pre += rel.prerelease
            out.append(rel)
        return out

    def _release_tags_web(self) -> dict[str, bool] | None:
        """The releases on the releases page's first page, each tag with whether it is marked a
        prerelease (the label after its heading), or None if the page can't be read."""
        import re
        from urllib.parse import unquote
        try:
            page = self.http.text(f"https://github.com/{self.repo.path}/releases")
        except Exception:      # noqa: BLE001 — without the page, every feed entry is kept, as before
            return None
        prefix = f"/{self.repo.path}/releases/tag/"
        out: dict[str, bool] = {}
        last = None
        for m in re.finditer(re.escape(prefix) + r'([^"?#]+)"|Label--warning[^"]*">\s*Pre-release\s*<', page, re.I):
            if m.group(1):
                last = unquote(_html_unescape(m.group(1)))
                out.setdefault(last, False)
            elif last is not None:
                out[last] = True
        return out

    def _bare_tag_web(self, tag: str) -> bool:
        """Whether the tag has no release: its page says who tagged it, not who released it."""
        try:
            page = self.http.text(f"https://github.com/{self.repo.path}/releases/tag/{quote(tag, safe='')}")
        except Exception:      # noqa: BLE001 — unknown: keep it
            return False
        return "tagged this" in page and "released this" not in page

    def _assets_web(self, tag: str) -> tuple[list[Asset], str]:
        import re
        try:
            page = self.http.text(f"https://github.com/{self.repo.path}/releases/expanded_assets/{quote(tag, safe='')}")
        except Exception:      # noqa: BLE001 — a missing assets page just means no assets
            return [], ""
        prefix = f"/{self.repo.path}/releases/download/"
        links = [m for m in re.finditer(r'href="(' + re.escape(prefix) + r'[^"]+)"', page, re.I)]
        assets = []
        for k, m in enumerate(links):
            block = page[m.end(): links[k + 1].start() if k + 1 < len(links) else len(page)]
            path = _html_unescape(m.group(1))
            name = path.rsplit("/", 1)[-1]
            from urllib.parse import unquote
            name = unquote(name)
            dg = re.search(r"sha256:([0-9a-f]{64})", block)
            sz = re.search(r">\s*([\d.]+)\s*(KB|MB|GB|Bytes)\s*<", block)
            size = 0
            if sz:
                size = int(float(sz.group(1)) * {"Bytes": 1, "KB": 1e3, "MB": 1e6, "GB": 1e9}[sz.group(2)])
            assets.append(Asset(name, "https://github.com" + path, size, f"sha256:{dg.group(1)}" if dg else ""))
        dates = re.findall(r'datetime="([^"]+)"', page)
        return assets, min(dates) if dates else ""

    def _tags_web(self, limit: int) -> list[Release]:
        out = _git_out(["ls-remote", "--tags", "--refs", f"https://github.com/{self.repo.path}"])
        tags = [line.split("refs/tags/", 1)[1] for line in out.splitlines() if "refs/tags/" in line]
        rels = [Release(tag=t, name=t, version=versions.clean(t), date="") for t in tags]
        rels.sort(key=lambda r: versions.key(r.version) or (), reverse=True)
        return rels[:limit]

    def _tree_web(self, ref: str) -> list[str]:
        import shutil
        import tempfile
        d = tempfile.mkdtemp(prefix="appkata-tree-")
        try:
            _git_out(["clone", "--quiet", "--depth", "1", "--filter=blob:none", "--no-checkout", "--branch", ref,
                      f"https://github.com/{self.repo.path}", d])
            return _git_out(["-C", d, "ls-tree", "-r", "--name-only", "HEAD"]).splitlines()
        finally:
            shutil.rmtree(d, ignore_errors=True)

    # ---- REST API
    def _info_api(self) -> RepoInfo:
        d = self._get(self.base)
        full = d.get("full_name", "")
        if full and full.lower() != self.repo.path.lower():
            raise Renamed(d.get("html_url") or f"https://{self.repo.host}/{full}")
        return RepoInfo(name=d.get("name", self.repo.name), description=d.get("description") or "",
                        default_branch=d.get("default_branch") or "main",
                        avatar_url=(d.get("owner") or {}).get("avatar_url", ""), html_url=d.get("html_url", ""),
                        archived=bool(d.get("archived")), topics=d.get("topics") or [])

    def _releases_api(self, limit: int = 30) -> list[Release]:
        out = []
        for r in self._get(f"{self.base}/releases?per_page={min(limit, 100)}"):
            if r.get("draft"):
                continue
            out.append(Release(
                tag=r.get("tag_name", ""), name=r.get("name") or r.get("tag_name", ""),
                version=_ver(r.get("tag_name", ""), r.get("name") or ""),
                date=r.get("published_at") or r.get("created_at") or "", prerelease=bool(r.get("prerelease")),
                notes=r.get("body") or "", html_url=r.get("html_url", ""),
                assets=[Asset(a["name"], a["browser_download_url"], a.get("size", 0), a.get("digest") or "",
                              a.get("content_type", "")) for a in r.get("assets", [])]))
        return out

    def _tags_api(self, limit: int = 30) -> list[Release]:
        return [Release(tag=t["name"], name=t["name"], version=versions.clean(t["name"]), date="")
                for t in self._get(f"{self.base}/tags?per_page={min(limit, 100)}")]

    def _tree_api(self, ref: str) -> list[str]:
        d = self._get(f"{self.base}/git/trees/{quote(ref, safe='')}?recursive=1")
        return [t["path"] for t in d.get("tree", []) if t.get("type") == "blob"]

    def raw_url(self, path: str, ref: str) -> str:
        if self.repo.host == "github.com":
            return f"https://raw.githubusercontent.com/{self.repo.path}/{quote(ref)}/{quote(path)}"
        return f"https://{self.repo.host}/{self.repo.path}/raw/{quote(ref)}/{quote(path)}"


class GitLab(Forge):
    kind, label = "gitlab", "GitLab"

    def __init__(self, http: Http, repo: Repo):
        super().__init__(http, repo)
        self.base = f"https://{repo.host}/api/v4/projects/{quote(repo.path, safe='')}"

    def _get(self, url: str):
        return self.http.json(url, token_host=self.repo.host)

    def info(self) -> RepoInfo:
        d = self._get(self.base)
        full = d.get("path_with_namespace", "")
        if full and full.lower() != self.repo.path.lower():
            raise Renamed(d.get("web_url") or f"https://{self.repo.host}/{full}")
        return RepoInfo(name=d.get("name", self.repo.name), description=d.get("description") or "",
                        default_branch=d.get("default_branch") or "main", avatar_url=d.get("avatar_url") or "",
                        html_url=d.get("web_url", ""), archived=bool(d.get("archived")), topics=d.get("topics") or [])

    def releases(self, limit: int = 30) -> list[Release]:
        out = []
        for r in self._get(f"{self.base}/releases?per_page={min(limit, 100)}"):
            notes = r.get("description") or ""
            assets = [Asset(link.get("name", ""), link.get("direct_asset_url") or link.get("url", ""))
                      for link in (r.get("assets") or {}).get("links", [])]
            # files uploaded into the release notes: [name](/uploads/<hash>/<file>)
            import re
            for m in re.finditer(r"\[([^\]]+)\]\((/uploads/[^)\s]+)\)", notes):
                assets.append(Asset(m.group(2).rsplit("/", 1)[-1], f"https://{self.repo.host}/{self.repo.path}{m.group(2)}"))
            out.append(Release(tag=r.get("tag_name", ""), name=r.get("name") or r.get("tag_name", ""),
                               version=_ver(r.get("tag_name", ""), r.get("name") or ""),
                               date=r.get("released_at") or r.get("created_at") or "",
                               prerelease=bool(r.get("upcoming_release")), notes=notes,
                               html_url=(r.get("_links") or {}).get("self", ""), assets=assets))
        return out

    def tags(self, limit: int = 30) -> list[Release]:
        return [Release(tag=t["name"], name=t["name"], version=versions.clean(t["name"]),
                        date=(t.get("commit") or {}).get("created_at", ""))
                for t in self._get(f"{self.base}/repository/tags?per_page={min(limit, 100)}")]

    def tree(self, ref: str) -> list[str]:
        out, page = [], 1
        while page <= 10:
            items = self._get(f"{self.base}/repository/tree?recursive=true&per_page=100&page={page}&ref={quote(ref)}")
            out += [t["path"] for t in items if t.get("type") == "blob"]
            if len(items) < 100:
                break
            page += 1
        return out

    def raw_url(self, path: str, ref: str) -> str:
        return f"https://{self.repo.host}/{self.repo.path}/-/raw/{quote(ref)}/{quote(path)}"


class Gitea(Forge):
    """Gitea and Forgejo (Codeberg) share this API (requirement 2.4.1)."""
    kind, label = "forgejo", "Forgejo"

    def __init__(self, http: Http, repo: Repo, label: str = "Forgejo"):
        super().__init__(http, repo)
        self.label = label
        self.base = f"https://{repo.host}/api/v1/repos/{repo.path}"

    def _get(self, url: str):
        return self.http.json(url, token_host=self.repo.host)

    def info(self) -> RepoInfo:
        d = self._get(self.base)
        full = d.get("full_name", "")
        if full and full.lower() != self.repo.path.lower():
            raise Renamed(d.get("html_url") or f"https://{self.repo.host}/{full}")
        return RepoInfo(name=d.get("name", self.repo.name), description=d.get("description") or "",
                        default_branch=d.get("default_branch") or "main",
                        avatar_url=d.get("avatar_url") or (d.get("owner") or {}).get("avatar_url", ""),
                        html_url=d.get("html_url", ""), archived=bool(d.get("archived")), topics=d.get("topics") or [])

    def releases(self, limit: int = 30) -> list[Release]:
        out = []
        for r in self._get(f"{self.base}/releases?limit={min(limit, 50)}"):
            if r.get("draft"):
                continue
            out.append(Release(tag=r.get("tag_name", ""), name=r.get("name") or r.get("tag_name", ""),
                               version=_ver(r.get("tag_name", ""), r.get("name") or ""),
                               date=r.get("published_at") or r.get("created_at") or "",
                               prerelease=bool(r.get("prerelease")), notes=r.get("body") or "",
                               html_url=r.get("html_url", ""),
                               assets=[Asset(a["name"], a["browser_download_url"], a.get("size", 0))
                                       for a in r.get("assets", [])]))
        return out

    def tags(self, limit: int = 30) -> list[Release]:
        return [Release(tag=t["name"], name=t["name"], version=versions.clean(t["name"]),
                        date=(t.get("commit") or {}).get("created", ""))
                for t in self._get(f"{self.base}/tags?limit={min(limit, 50)}")]

    def tree(self, ref: str) -> list[str]:
        d = self._get(f"{self.base}/git/trees/{quote(ref, safe='')}?recursive=true&per_page=10000")
        return [t["path"] for t in d.get("tree", []) if t.get("type") == "blob"]

    def raw_url(self, path: str, ref: str) -> str:
        return f"https://{self.repo.host}/{self.repo.path}/raw/branch/{quote(ref)}/{quote(path)}"


KNOWN = {"github.com": "github", "gitlab.com": "gitlab", "codeberg.org": "forgejo",
         "invent.kde.org": "gitlab", "gitlab.gnome.org": "gitlab", "salsa.debian.org": "gitlab",
         "gitlab.freedesktop.org": "gitlab", "framagit.org": "gitlab", "gitea.com": "gitea"}
LABELS = {"github": "GitHub", "gitlab": "GitLab", "forgejo": "Forgejo", "gitea": "Gitea", "ghe": "GitHub Enterprise"}


def detect(http: Http, host: str) -> str:
    """The forge type of a host (requirement 2.4.2): known hosts first, then API probes."""
    if host in KNOWN:
        return KNOWN[host]
    try:
        d = http.json(f"https://{host}/api/v1/version")
        if isinstance(d, dict) and "version" in d:
            return "forgejo" if "forgejo" in str(d).lower() or "+gitea" in str(d.get("version", "")) else "gitea"
    except Exception:
        pass
    try:
        d = http.json(f"https://{host}/api/v4/projects?per_page=1")   # /version needs a token; this doesn't
        if isinstance(d, list):
            return "gitlab"
    except Exception:
        pass
    try:
        d = http.json(f"https://{host}/api/v3/meta")
        if isinstance(d, dict) and ("verifiable_password_authentication" in d or "installed_version" in d):
            return "ghe"
    except Exception:
        pass
    try:
        page = http.text(f"https://{host}/")
        low = page.lower()
        for marker, kind in (('content="forgejo', "forgejo"), ('content="gitea', "gitea"), ("og:site_name\" content=\"gitlab", "gitlab"),
                             ('content="gitlab', "gitlab")):
            if marker in low:
                return kind
    except Exception:
        pass
    raise Unsupported(f"couldn't tell which forge {host} runs; set the forge type in Source settings")


def forge_for(http: Http, repo: Repo, kind: str | None = None) -> Forge:
    kind = kind or detect(http, repo.host)
    if kind == "github":
        return GitHub(http, repo)
    if kind == "ghe":
        return GitHub(http, repo, api=f"https://{repo.host}/api/v3")
    if kind == "gitlab":
        return GitLab(http, repo)
    if kind in ("forgejo", "gitea"):
        return Gitea(http, repo, label=LABELS[kind])
    raise Unsupported(f"{kind} isn't supported yet")


def latest(releases: list[Release], include_pre: bool = False) -> Release | None:
    rs = [r for r in releases if include_pre or not r.prerelease]
    if not rs:
        return None
    def k(r: Release):
        vk = versions.key(r.version)
        return (r.date or "", vk is not None, vk or ())
    return max(rs, key=k)
