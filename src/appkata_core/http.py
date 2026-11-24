"""A small HTTP client: per-host tokens (R9.2.2), rate limits (R9.2.1), typed errors (R2.10)."""

from __future__ import annotations

import ipaddress
import json
import socket
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


def _is_for(parts, whose: str) -> bool:
    """Whether an address is on the host `whose`, or on one of its named hosts (token_hosts)."""
    return bool({(parts.hostname or "").lower(), _host_port(parts)} & set(token_hosts(whose)))


def _http_address(url: str):
    """An address in its parts, or Unreachable when it isn't an http or https one with a host: the
    only addresses Http opens, whoever asks (CR1 #266). A project's icon address can say file:, which
    on Windows can name a host to log in to over SMB, or ftp: or data:."""
    try:
        parts = urlsplit(url)
        parts.port
    except ValueError:
        parts = None
    if parts is None or parts.scheme not in ("http", "https") or not parts.hostname:
        raise Unreachable(f"{url[:200]!r} isn't an http or https address")
    return parts


def _addresses(host: str) -> list[str]:
    """The addresses a host's name stands for, as a connection to it would look them up."""
    return [info[4][0] for info in socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)]


def _local(address: str) -> bool:
    """A loopback, private or link-local address, or any other that isn't a public one (0.0.0.0, a
    carrier's shared range)."""
    ip = ipaddress.ip_address(address.split("%")[0])          # fe80::1%eth0
    ip = getattr(ip, "ipv4_mapped", None) or ip                 # ::ffff:127.0.0.1
    return ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_unspecified or not ip.is_global


def _opener(redirects) -> urllib.request.OpenerDirector:
    """Http's own opener: urllib's default one without its file:, ftp: and data: handlers (CR1 #266),
    and with Http's rules for a redirect."""
    proxies = {k: v for k, v in urllib.request.getproxies().items() if k in ("http", "https")}
    opener = urllib.request.OpenerDirector()
    for handler in (urllib.request.ProxyHandler(proxies), urllib.request.UnknownHandler(), urllib.request.HTTPHandler(),
                    urllib.request.HTTPSHandler(), urllib.request.HTTPDefaultErrorHandler(), redirects,
                    urllib.request.HTTPErrorProcessor()):
        opener.add_handler(handler)
    return opener


TOKEN_HEADERS = ("authorization", "private-token")


class _Redirects(urllib.request.HTTPRedirectHandler):
    """A redirect under R9.2.2. urllib copies a request's headers to wherever a redirect points, so
    Http sends the token as an unredirected header, which urllib never copies, and this hands it on
    by its own rule: only to the same scheme, host and port (a renamed repository's API address
    redirects on its own host). To any other host the request goes on without it, and a redirect to
    plain http of a request that carried a token is refused, the same host's too.

    Where a redirect points is held to the rule for a first address (`allowed`, Http._allowed): http
    or https, and no local address but the host's the request was made for (`req.whose`)."""

    def __init__(self, allowed):
        self.allowed = allowed

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        was = urlsplit(req.full_url)
        whose = getattr(req, "whose", (was.hostname or "").lower())
        token = {k: v for k, v in req.unredirected_hdrs.items() if k.lower() in TOKEN_HEADERS}
        try:
            to = self.allowed(newurl, whose)
            if token and to.scheme != "https":
                raise Unreachable(f"{was.hostname} redirected a request that carried its API token to plain http; "
                                  "the redirect wasn't followed")
        except Unreachable:
            fp.close()
            raise
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None:
            new.whose = whose
            if _origin(to) == _origin(was):
                for k, v in token.items():
                    new.add_unredirected_header(k, v)
        return new


class Http:
    def __init__(self, tokens: dict[str, str] | None = None, timeout: float = 20.0, opener=None):
        self.tokens = {k.lower(): v for k, v in (tokens or {}).items() if v}
        self.timeout = timeout
        self._open = opener or _opener(_Redirects(self._allowed)).open
        self._lookup = _addresses                # host -> its addresses
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

    def _token(self, parts, whose: str) -> dict:
        """The token header a request to this address carries (R9.2.2), decided here for every caller
        from the address itself. `whose` only says whose token is meant (a caller's `token_host`, or
        without one the address's own host): it is sent over https alone, and only when the address's
        host is one of that host's token_hosts(). A caller that names a host for an address
        elsewhere, as Sync does for an image a project's README or metainfo names, sends no token."""
        if parts.scheme != "https" or not _is_for(parts, whose):
            return {}
        return self._auth(whose)

    def _allowed(self, url: str, whose: str | None = None):
        """The parts of an address Http may open, or Unreachable (CR1 #266). It is an http or https
        address, and its host doesn't stand for a loopback, private or link-local address: a project
        names its images' addresses, and a forge its avatars' and its redirects', and none of them
        gets a request sent into this computer or its network. The one host that may be local is
        `whose`, the host the request is made for (a forge on the user's own network), with its
        named hosts; without one, that is the address's own host. A first address and every
        redirect of it are held to this."""
        parts = _http_address(url)
        host = parts.hostname.lower()
        if whose is None or _is_for(parts, whose.lower()):
            return parts
        try:
            local = [a for a in self._lookup(host) if _local(a)]
        except (OSError, ValueError) as e:        # no such name: what the connection would have found
            raise Unreachable(f"couldn't reach {host}: {e}") from None
        if local:
            raise Unreachable(f"{host} is on this computer or its local network ({local[0]}): not fetched, "
                              "since it isn't the Source's own host")
        return parts

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
        """`token_host` is the host the request is made for, a Source's: its token is the one that may
        be sent (_token), and it is the one host that may be on the local network (_allowed). An
        address that a project, or a forge's answer, names is always asked with it."""
        parts = self._allowed(url, token_host)
        host = parts.hostname.lower()
        whose = (token_host or host).lower()       # the host this request is made for
        reset = self.limited.get(host)
        if reset and reset > time.time():
            raise RateLimited(host, reset)
        token = self._token(parts, whose)
        h = {"User-Agent": UA, "Accept": accept, **(headers or {})}
        req = urllib.request.Request(url, data=body, headers=h, method=method)
        req.whose = whose                          # for a redirect: _Redirects
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
