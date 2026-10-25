"""Source URLs: normalizing (requirement 2.3) and recognizing releases links (2.5)."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from urllib.parse import urlsplit

_SCP = re.compile(r"^(?:[\w.-]+@)?([\w.-]+\.[a-z]{2,}):(?!//)(.+)$", re.I)
# trailing parts that point inside a project rather than at it
_INSIDE = re.compile(r"/(?:-/)?(?:releases|tags|tree|blob|src|commits?|issues|pulls?|merge_requests|wiki)(?:/.*)?$")
_RELEASES = re.compile(r"/(?:-/)?releases(?:/.*)?$")


@dataclass(frozen=True)
class Repo:
    url: str            # normalized project URL (the app's identity)
    kind: str           # "forge" | "nostr" | "local"
    host: str = ""
    path: str = ""      # owner/name, possibly with GitLab subgroups
    releases_page: bool = False   # the given URL was a releases page (requirement 2.5)

    @property
    def owner(self) -> str:
        return self.path.rsplit("/", 1)[0] if "/" in self.path else ""

    @property
    def name(self) -> str:
        return self.path.rsplit("/", 1)[-1]


def parse(url: str) -> Repo:
    """Parse any accepted Source/Trust URL. Raises ValueError for anything unusable."""
    u = (url or "").strip()
    if not u:
        raise ValueError("empty URL")
    if u.startswith(("nostr:", "naddr1")):
        ident = u.split("nostr://", 1)[-1].split("nostr:", 1)[-1].rstrip("/")
        return Repo(url="nostr://" + ident, kind="nostr", path=ident)
    if u.startswith("file://") or u.startswith(("/", "~", "./", "../")) or (os.name == "nt" and re.match(r"^[a-z]:[\\/]", u, re.I)):
        p = os.path.abspath(os.path.expanduser(u[7:] if u.startswith("file://") else u))
        return Repo(url="file://" + p.replace(os.sep, "/"), kind="local", path=p)
    m = _SCP.match(u)
    if m and "://" not in u:
        u = f"https://{m.group(1)}/{m.group(2)}"
    if "://" not in u:
        u = "https://" + u
    parts = urlsplit(u)
    if parts.scheme not in ("http", "https", "ssh", "git"):
        raise ValueError(f"unsupported URL scheme: {parts.scheme}")
    host = (parts.hostname or "").lower()
    if not host or "." not in host:
        raise ValueError("URL has no host")
    path = parts.path
    releases = bool(_RELEASES.search(path))
    path = _INSIDE.sub("", path)
    path = path.strip("/")
    if path.endswith(".git"):
        path = path[:-4]
    path = path.rstrip("/")
    if path.count("/") < 1:
        raise ValueError("URL doesn't name a repository (expected host/owner/name)")
    port = f":{parts.port}" if parts.port and parts.scheme in ("http", "https") and parts.port not in (80, 443) else ""
    return Repo(url=f"https://{host}{port}/{path}", kind="forge", host=host + port, path=path, releases_page=releases)


def normalize(url: str) -> str:
    """The canonical form used to compare Sources and Trust rows (requirement 2.3)."""
    return parse(url).url


def try_normalize(url: str) -> str | None:
    try:
        return normalize(url)
    except ValueError:
        return None
