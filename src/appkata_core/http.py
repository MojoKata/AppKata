"""A small HTTP client: per-host tokens (requirement 9.2.2), rate limits (9.2.1), typed errors (2.10)."""

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
    """A Source problem shown on its row (requirement 2.10). `code` is the error kind."""
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


class Http:
    def __init__(self, tokens: dict[str, str] | None = None, timeout: float = 20.0, opener=None):
        self.tokens = {k.lower(): v for k, v in (tokens or {}).items() if v}
        self.timeout = timeout
        self._open = opener or urllib.request.urlopen
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
        host = (urlsplit(url).hostname or "").lower()
        reset = self.limited.get(host)
        if reset and reset > time.time():
            raise RateLimited(host, reset)
        h = {"User-Agent": UA, "Accept": accept, **self._auth((token_host or host).lower()), **(headers or {})}
        req = urllib.request.Request(url, data=body, headers=h, method=method)
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
            if e.code == 401 and (h.get("Authorization") or h.get("PRIVATE-TOKEN")):
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
