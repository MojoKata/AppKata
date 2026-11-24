"""A small HTTP client: per-host tokens (R9.2.2), rate limits (R9.2.1), typed errors (R2.10)."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit

from . import APPKATA_REPO, __version__

UA = f"AppKata/{__version__} (+{APPKATA_REPO})"


class SourceError(Exception):
    """A Source problem shown on its row (R2.10). `code` is the error kind."""
    code = "Unreachable"

    def __init__(self, message: str = "", **extra):
        super().__init__(message or self.code)
        self.extra = extra


class NoReleases(SourceError): code = "NoReleases"
class NoMatchingAsset(SourceError): code = "NoMatchingAsset"
class NoVersion(SourceError): code = "NoVersion"
class Unreachable(SourceError): code = "Unreachable"
class NotFound(SourceError): code = "NotFound"
class Unsupported(SourceError): code = "Unsupported"


class RateLimited(SourceError):
    code = "RateLimited"

    def __init__(self, host: str, reset: float):
        super().__init__(f"{host} rate limit reached", host=host, reset=reset)
        self.host, self.reset = host, reset


class Renamed(SourceError):
    code = "Renamed"

    def __init__(self, new_url: str):
        super().__init__(f"moved to {new_url}", new_url=new_url)
        self.new_url = new_url


# R9.2.2's list, in its one place: the other hosts a host's token is sent to, which are the forge's
# own API and raw-file hosts. A host that isn't a key here has none, and its token goes to it alone.
TOKEN_HOSTS = {"github.com": ("api.github.com", "raw.githubusercontent.com")}


def token_hosts(host: str) -> tuple[str, ...]:
    """Every host the token kept for `host` may be sent to (R9.2.2): itself and its named ones."""
    return (host, *TOKEN_HOSTS.get(host, ()))


def _host_port(parts) -> str:
    """An address's host as a Source's host is written (urls.parse): with its port, unless that is
    http's or https's own."""
    try:
        port = parts.port
    except ValueError:
        port = None
    host = (parts.hostname or "").lower()
    return f"{host}:{port}" if port and port not in (80, 443) else host


def _origin(parts) -> tuple:
    """(scheme, host, port) of an address: what a redirect must keep for a token to go on with it."""
    try:
        port = parts.port or {"http": 80, "https": 443}.get(parts.scheme)
    except ValueError:
        port = None
    return parts.scheme, (parts.hostname or "").lower(), port


TOKEN_HEADERS = ("authorization", "private-token")


class _Redirects(urllib.request.HTTPRedirectHandler):
    """A redirect under R9.2.2. urllib copies a request's headers to wherever a redirect points, so
    Http sends the token as an unredirected header, which urllib never copies, and this hands it on
    by its own rule: only to the same scheme, host and port (a renamed repository's API address
    redirects on its own host). To any other host the request goes on without it, and a redirect to
    plain http of a request that carried a token is refused, the same host's too."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        token = {k: v for k, v in req.unredirected_hdrs.items() if k.lower() in TOKEN_HEADERS}
        if new is None or not token:
            return new
        was, to = urlsplit(req.full_url), urlsplit(newurl)
        if to.scheme != "https":
            fp.close()
            raise Unreachable(f"{was.hostname} redirected a request that carried its API token to plain http; "
                              "the redirect wasn't followed")
        if _origin(to) == _origin(was):
            for k, v in token.items():
                new.add_unredirected_header(k, v)
        return new


class Http:
    def __init__(self, tokens: dict[str, str] | None = None, timeout: float = 20.0, opener=None):
        self.tokens = {k.lower(): v for k, v in (tokens or {}).items() if v}
        self.timeout = timeout
        self._open = opener or urllib.request.build_opener(_Redirects()).open
        self.limited: dict[str, float] = {}      # host -> reset time
        self.calls = 0

    def _auth(self, host: str) -> dict:
        tok = self.tokens.get(host)
        if not tok:
            return {}
        if host.endswith("github.com") or host.startswith("api.github."):
            return {"Authorization": f"Bearer {tok}"}
        if "gitlab" in host:
            return {"PRIVATE-TOKEN": tok}
        return {"Authorization": f"token {tok}"}      # Gitea / Forgejo

    def _token(self, parts, token_host: str | None) -> dict:
        """The token header a request to this address carries (R9.2.2), decided here for every caller
        from the address itself. `token_host` only says whose token is meant (without it, the
        address's own host's): it is sent over https alone, and only when the address's host is one
        of that host's token_hosts(). A caller that names a host for an address elsewhere, as Sync
        does for an image a project's README or metainfo names, sends no token."""
        host = (parts.hostname or "").lower()
        whose = (token_host or host).lower()
        if parts.scheme != "https" or not {host, _host_port(parts)} & set(token_hosts(whose)):
            return {}
        return self._auth(whose)

    def request(self, url: str, **kw) -> tuple[bytes, dict, str]:
        """With up to two retries for a forge's temporary errors (HTTP 502, 503, 504, timeouts)."""
        for attempt in range(3):
            try:
                return self._request(url, **kw)
            except Unreachable as e:
                if attempt == 2 or not (e.extra.get("status") in (502, 503, 504) or e.extra.get("timeout")):
                    raise
                time.sleep(1.5 * (attempt + 1))

    def _request(self, url: str, *, token_host: str | None = None, accept: str = "application/json",
                 headers: dict | None = None, method: str = "GET", max_bytes: int = 64 << 20,
                 body: bytes | None = None) -> tuple[bytes, dict, str]:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
        reset = self.limited.get(host)
        if reset and reset > time.time():
            raise RateLimited(host, reset)
        token = self._token(parts, token_host)
        h = {"User-Agent": UA, "Accept": accept, **(headers or {})}
        req = urllib.request.Request(url, data=body, headers=h, method=method)
        for k, v in token.items():
            req.add_unredirected_header(k, v)      # so a redirect doesn't carry it on: _Redirects decides
        self.calls += 1
        try:
            with self._open(req, timeout=self.timeout) as r:
                data = r.read(max_bytes + 1)
                if len(data) > max_bytes:
                    raise Unreachable(f"response from {host} too large")
                return data, {k.lower(): v for k, v in r.headers.items()}, r.geturl()
        except urllib.error.HTTPError as e:
            hdr = {k.lower(): v for k, v in (e.headers or {}).items()}
            if e.code in (403, 429) and (hdr.get("x-ratelimit-remaining") == "0" or "retry-after" in hdr or e.code == 429):
                reset = _reset_time(hdr)
                self.limited[host] = reset
                raise RateLimited(host, reset) from None
            if e.code == 404:
                raise NotFound(f"{url} not found") from None
            if e.code == 401 and token:
                raise Unreachable(f"{host} rejected the API token (HTTP 401)") from None
            raise Unreachable(f"{host} answered HTTP {e.code}", status=e.code) from None
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            reason = getattr(e, "reason", e)
            raise Unreachable(f"couldn't reach {host}: {reason}", timeout=isinstance(reason, TimeoutError) or "timed out" in str(reason)) from None

    def json(self, url: str, **kw):
        data, hdr, final = self.request(url, **kw)
        try:
            return json.loads(data.decode("utf-8"))
        except ValueError:
            raise Unreachable(f"{urlsplit(url).hostname} didn't return JSON") from None

    def json_with_headers(self, url: str, **kw):
        data, hdr, final = self.request(url, **kw)
        try:
            return json.loads(data.decode("utf-8")), hdr, final
        except ValueError:
            raise Unreachable(f"{urlsplit(url).hostname} didn't return JSON") from None

    def text(self, url: str, **kw) -> str:
        data, _, _ = self.request(url, accept="*/*", **kw)
        return data.decode("utf-8", "replace")

    def bytes(self, url: str, **kw) -> bytes:
        data, _, _ = self.request(url, accept="*/*", **kw)
        return data


def _reset_time(hdr: dict) -> float:
    if hdr.get("x-ratelimit-reset", "").isdigit():
        return float(hdr["x-ratelimit-reset"])
    ra = hdr.get("retry-after", "")
    if ra.isdigit():
        return time.time() + int(ra)
    if ra:
        try:
            return parsedate_to_datetime(ra).timestamp()
        except (TypeError, ValueError):
            pass
    return time.time() + 60
