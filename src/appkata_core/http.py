"""A small HTTP client: per-host tokens (R9.2.2), rate limits (R9.2.1), typed errors (R2.10)."""

from __future__ import annotations

import contextlib
import ipaddress
import json
import socket
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime
from email.utils import parsedate_to_datetime
from http.client import HTTPException, IncompleteRead, InvalidURL
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


LIMIT_STATUSES = (403, 429)      # the answers that are a forge's rate limit, which a token raises


class RateLimited(SourceError):
    """A host that isn't to be asked again until `reset`. `status` is the HTTP status of the answer
    that said so, where one did: a forge's own rate limit (LIMIT_STATUSES), or another failing
    answer with a Retry-After, such as the 503 of a forge that is overloaded or being maintained
    (CR1 #277). It is kept in `extra`, so what a Source's row says can tell the two apart: a token
    raises the first and does nothing for the second."""
    code = "RateLimited"

    def __init__(self, host: str, reset: float, status: int | None = None):
        said = (f"{host} rate limit reached" if status in (None, *LIMIT_STATUSES)
                else f"{host} answered HTTP {status} and said when to come back")
        super().__init__(said, host=host, reset=reset, **({"status": status} if status else {}))
        self.host, self.reset, self.status = host, reset, status


class Renamed(SourceError):
    code = "Renamed"

    def __init__(self, new_url: str):
        super().__init__(f"moved to {new_url}", new_url=new_url)
        self.new_url = new_url


class Cancelled(BaseException):
    """A request given up because whoever asked for it said to stop (Http.stopping). It is no
    Exception, as asyncio's own isn't, and no SourceError: nothing that catches a host's failure to
    pass it over, to try the next address or to write it on a Source's row takes a Cancel for one."""


# R9.2.2's list, in its one place: the other hosts a host's token is sent to, which are the forge's
# own API and raw-file hosts. A host that isn't a key here has none, and its token goes to it alone.
# A host, here and wherever a token is looked up, is one address (_host): a name alone is the
# default port, and none of these is asked on another.
TOKEN_HOSTS = {"github.com": ("api.github.com", "raw.githubusercontent.com")}


def token_hosts(host: str) -> tuple[str, ...]:
    """Every host the token kept for `host` may be sent to (R9.2.2): itself and its named ones."""
    return (host, *TOKEN_HOSTS.get(host, ()))


def token_key(host: str) -> str:
    """The host a token is kept under, from what was typed for it (R11.1.6) or what a caller names:
    one address, written as a Source's host is (urls.parse), `git.example.org` or, on a port,
    `git.example.org:3000`. A name alone is the default port, so https's own port is left out, and so
    is the rest of a whole address where one was pasted."""
    text = host.strip().lower()
    try:
        parts = urlsplit(text if "://" in text else "https://" + text)
        parts.port
    except ValueError:
        return text
    return _host(parts) if parts.hostname else text


# How each forge type takes a token (CR1 #275): the header, and what stands before the token in it.
# GitLab reads PRIVATE-TOKEN and has no use for "Authorization: token", which is Gitea's and
# Forgejo's. The types are forges.LABELS'.
TOKEN_FORMS = {"github": ("Authorization", "Bearer "), "ghe": ("Authorization", "Bearer "),
               "gitlab": ("PRIVATE-TOKEN", ""),
               "forgejo": ("Authorization", "token "), "gitea": ("Authorization", "token ")}


def _forge_by_name(host: str) -> str:
    """A guess at a host's forge type from its name, for a request made before anything says what
    the host runs (forges.detect's last probe). Only github.com and the hosts under it are GitHub:
    a name that merely ends in those letters isn't."""
    name = urlsplit("//" + host).hostname or ""
    if name == "github.com" or name.endswith(".github.com"):
        return "github"
    return "gitlab" if "gitlab" in name else "forgejo"


PORTS = {"http": 80, "https": 443}


def _origin(parts) -> tuple:
    """(scheme, host, port) of an address: what a redirect must keep for a token to go on with it."""
    try:
        port = parts.port or PORTS.get(parts.scheme)
    except ValueError:
        port = None
    return parts.scheme, (parts.hostname or "").lower(), port


def _host(parts) -> str:
    """An address's host, as a token is kept for it and as a Source's host is written (urls.parse):
    its name, and its port unless that is its scheme's own. The one notion of a host that every
    lookup uses (CR1 #297): the forges named a Source's host with its port and Http looked a token
    up without it, so a token on a port was sent by some calls and not by others, and a token kept
    for a name went to every port of it."""
    scheme, name, port = _origin(parts)
    name = f"[{name}]" if ":" in name else name            # an IPv6 address, as an address writes it
    return name if port in (None, PORTS.get(scheme)) else f"{name}:{port}"


def _is_for(parts, whose: str) -> bool:
    """Whether an address is on the host `whose`, or on one of its named hosts (token_hosts): the
    same name and the same port."""
    return _host(parts) in token_hosts(whose)


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
    or https, and no local address but the host's the request was made for (`req.whose`).

    It also keeps `req.asked` up to where the request has got to: the address and the host asked
    last, and whether the token went there. An error is that host's, and is the token's only if it
    was sent (CR1 #683)."""

    def __init__(self, allowed):
        self.allowed = allowed

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        was = urlsplit(req.full_url)
        whose = getattr(req, "whose", _host(was))
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
            carried = bool(token) and _origin(to) == _origin(was)
            if carried:
                for k, v in token.items():
                    new.add_unredirected_header(k, v)
            new.asked = asked = getattr(req, "asked", None)
            if asked is not None:
                asked.update(url=newurl, host=to.hostname.lower(), token=carried)
        return new


PIECE = 64 << 10        # an answer is read this much at a time at most, with a look at the clock between
WAITS = (1.5, 3.0)      # before a request is asked for again: after its first failure, after its second


class Http:
    def __init__(self, tokens: dict[str, str] | None = None, timeout: float = 20.0, opener=None, deadline: float = 120.0):
        """`timeout` is for each step of a request (connecting, each read of the answer): a host that
        keeps sending, however little, never meets it. `deadline` is for a request as a whole, from
        when it is sent to the last byte of its answer (R9.2.1)."""
        self.tokens = {token_key(k): v for k, v in (tokens or {}).items() if v}     # by host: one address each
        self.timeout, self.deadline = timeout, deadline
        self._here = threading.local()           # this thread's `cancelled`, inside a `stopping` block
        self._open = opener or _opener(_Redirects(self._allowed)).open
        self._lookup = _addresses                # host -> its addresses
        self.forges: dict[str, str] = {}         # host -> its forge type (set_forge)
        self.limited: dict[str, float] = {}      # host -> reset time
        self.limit_status: dict[str, int] = {}   # host -> the status of the answer that set its reset time
        self.calls = 0

    def set_forge(self, host: str, forge: str) -> None:
        """Says which forge type a host runs: each Forge says it of its Source's host when it is
        made (forges.Forge), from the type the Source has (R2.6.5) or the one that was detected."""
        if forge in TOKEN_FORMS:
            self.forges[token_key(host)] = forge

    def _auth(self, host: str, forge: str | None = None) -> dict:
        """The header a host's token is sent in, in the form its forge type takes (TOKEN_FORMS).
        The type is the request's own `forge`, where its caller knows which forge's API it is asking
        (a probe of forges.detect, a search of explore), else the one the host is known to run
        (set_forge), which holds for every request made for that host, an image's too. A host's
        name decides only when neither says (CR1 #275: three of the GitLab hosts AppKata knows have
        no "gitlab" in their names, and were sent the form GitLab ignores)."""
        tok = self.tokens.get(host)
        if not tok:
            return {}
        header, before = TOKEN_FORMS.get(forge or self.forges.get(host) or "") or TOKEN_FORMS[_forge_by_name(host)]
        return {header: before + tok}

    def _token(self, parts, whose: str, forge: str | None = None) -> dict:
        """The token header a request to this address carries (R9.2.2), decided here for every caller
        from the address itself. `whose` only says whose token is meant (a caller's `token_host`, or
        without one the address's own host): it is sent over https alone, and only when the address's
        host is one of that host's token_hosts(), on the same port. A caller that names a host for an
        address elsewhere, as Sync does for an image a project's README or metainfo names, sends no
        token, and neither does a request to another port of the host."""
        if parts.scheme != "https" or not _is_for(parts, whose):
            return {}
        return self._auth(whose, forge)

    def _allowed(self, url: str, whose: str | None = None):
        """The parts of an address Http may open, or Unreachable (CR1 #266). It is an http or https
        address, and its host doesn't stand for a loopback, private or link-local address: a project
        names its images' addresses, and a forge its avatars' and its redirects', and none of them
        gets a request sent into this computer or its network. The one host that may be local is
        `whose`, the host the request is made for (a forge on the user's own network), with its
        named hosts; without one, that is the address's own host. A host is one address (_host):
        another port of a Source's host is whatever else listens there, and isn't the Source's. A
        first address and every redirect of it are held to this."""
        parts = _http_address(url)
        host = parts.hostname.lower()
        if whose is None or _is_for(parts, token_key(whose)):
            return parts
        try:
            local = [a for a in self._lookup(host) if _local(a)]
        except (OSError, ValueError) as e:        # no such name: what the connection would have found
            raise Unreachable(f"couldn't reach {host}: {e}") from None
        if local:
            raise Unreachable(f"{host} is on this computer or its local network ({local[0]}): not fetched, "
                              "since it isn't the Source's own host")
        return parts

    @contextlib.contextmanager
    def stopping(self, cancelled):
        """While its block runs, this thread's requests end in Cancelled as soon as `cancelled()`
        says so: before one is sent, between two reads of an answer, and before one is asked for
        again. A Sync's worker runs each app's sync in one, with the Sync's own Cancel (R9.2).

        It is the thread's, and the block's: the application has one Http for everything, an
        install's lookups too, so a Cancel is never a flag left on the client for the next request,
        whoever makes it, to trip over (CR1 #296)."""
        before = getattr(self._here, "cancelled", None)
        self._here.cancelled = cancelled
        try:
            yield
        finally:
            self._here.cancelled = before

    def _stop(self) -> None:
        cancelled = getattr(self._here, "cancelled", None)
        if cancelled is not None and cancelled():
            raise Cancelled()

    def request(self, url: str, **kw) -> tuple[bytes, dict, str]:
        """With up to two retries for a forge's temporary errors (HTTP 502, 503, 504, timeouts, an
        answer cut short), after WAITS, or after what the host's Retry-After asked for where that
        is longer (one longer than the last of WAITS is no retry: _request makes it the host's
        limit). A request that met its deadline isn't asked for again: its host was given the
        whole of it once, and three in a row would be three times the wait."""
        for attempt in range(len(WAITS) + 1):
            try:
                return self._request(url, **kw)
            except Unreachable as e:
                again = e.extra.get("status") in (502, 503, 504) or e.extra.get("timeout") or e.extra.get("cut")
                if attempt == len(WAITS) or not again or e.extra.get("deadline"):
                    raise
                time.sleep(max(WAITS[attempt], e.extra.get("retry_after") or 0))

    def _read(self, r, host: str, max_bytes: int, started: float) -> bytes:
        """An answer's body, a piece at a time, with a look at the clock and at Cancel before each
        piece (CR1 #296). `timeout` alone is for each read: a host that sent one byte every few
        seconds never met it, and held its reader for as long as it liked, with the Sync's Cancel
        unable to stop it. read1 comes back with what one read of the socket gave, so no piece
        waits for more than `timeout`."""
        read = getattr(r, "read1", None) or r.read
        pieces, size = [], 0
        while True:
            self._stop()
            if time.monotonic() - started > self.deadline:
                raise Unreachable(f"{host} hadn't finished its answer after {self.deadline:g} seconds", timeout=True, deadline=True,
                                  no_answer=True)
            piece = read(min(PIECE, max_bytes + 1 - size))
            if not piece:
                return b"".join(pieces)
            pieces.append(piece)
            size += len(piece)
            if size > max_bytes:
                raise Unreachable(f"response from {host} too large")

    def _request(self, url: str, *, token_host: str | None = None, accept: str = "application/json",
                 headers: dict | None = None, method: str = "GET", max_bytes: int = 64 << 20,
                 body: bytes | None = None, forge: str | None = None) -> tuple[bytes, dict, str]:
        """`token_host` is the host the request is made for, a Source's: its token is the one that may
        be sent (_token), and it is the one host that may be on the local network (_allowed). An
        address that a project, or a forge's answer, names is always asked with it. `forge` is the
        forge type whose API the address is, where the caller knows it: the form the token is sent
        in (_auth)."""
        self._stop()
        parts = self._allowed(url, token_host)
        host = parts.hostname.lower()
        whose = token_key(token_host) if token_host else _host(parts)      # the host this request is made for
        reset = self.limited.get(host)
        if reset and reset > time.time():
            raise RateLimited(host, reset, self.limit_status.get(host))
        token = self._token(parts, whose, forge)
        h = {"User-Agent": UA, "Accept": accept, **(headers or {})}
        req = urllib.request.Request(url, data=body, headers=h, method=method)
        req.whose = whose                          # for a redirect: _Redirects
        # the address and the host asked last, and whether the token went there: _Redirects moves
        # them on, since what comes after a redirect is another host's answer, or its failure to
        # give one, and that host may have been sent no token. Every error below is said of the
        # host asked last (CR1 #683); `host`, the one asked first, is whose limit is kept.
        req.asked = asked = {"url": url, "host": host, "token": bool(token)}
        for k, v in token.items():
            req.add_unredirected_header(k, v)      # so a redirect doesn't carry it on: _Redirects decides
        self.calls += 1
        started = time.monotonic()
        try:
            with self._open(req, timeout=self.timeout) as r:
                data = self._read(r, asked["host"], max_bytes, started)
                hdr = {k.lower(): v for k, v in r.headers.items()}
                declared = _declared_length(hdr, method)
                if declared is not None and len(data) < declared:
                    # http.client hands back a short body without an error when the connection ends
                    # before the Content-Length (CR1 #626): a cut-off image, README or file list was
                    # taken for the whole one. Worth asking again, like a chunked answer cut short.
                    raise Unreachable(f"{asked['host']} cut its answer short ({len(data)} of {declared} bytes)", cut=True)
                return data, hdr, r.geturl()
        except urllib.error.HTTPError as e:
            hdr = {k.lower(): v for k, v in (e.headers or {}).items()}
            if e.code in (403, 429) and (hdr.get("x-ratelimit-remaining") == "0" or "retry-after" in hdr or e.code == 429):
                reset = _reset_time(hdr)
                self.limited[host], self.limit_status[host] = reset, e.code
                raise RateLimited(host, reset, e.code) from None
            # Retry-After on any other failing answer (R9.2.1; CR1 #277): an overloaded forge, or one
            # being maintained, answers 503 with it, and was asked again after 1.5 and 3 seconds
            # whatever it had asked for, by every app on it. Longer than the retries wait, it is
            # the host's limit like a 429's, and nothing is sent there until then; a 5xx with it is
            # that limit and no more, and another answer still means what it says. Shorter, the
            # retry waits it out (request).
            wait = 0.0
            if "retry-after" in hdr:
                reset = _reset_time({"retry-after": hdr["retry-after"]})
                wait = max(0.0, reset - time.time())
                if wait > WAITS[-1]:
                    self.limited[host], self.limit_status[host] = reset, e.code
                    if e.code >= 500:
                        raise RateLimited(host, reset, e.code) from None
            if e.code == 404:
                raise NotFound(f"{asked['url']} not found") from None
            # the answer is the host's that was asked last. A 401 is the token's only when the
            # token went there: a redirect to another host drops it (R9.2.2), and that host's 401
            # was said to be the first host rejecting a token it had never seen, which sent the
            # user to Settings to replace a token that was fine (CR1 #683)
            if e.code == 401 and asked["token"]:
                raise Unreachable(f"{asked['host']} rejected the API token (HTTP 401)") from None
            raise Unreachable(f"{asked['host']} answered HTTP {e.code}", status=e.code, **({"retry_after": wait} if wait else {})) from None
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            reason = getattr(e, "reason", e)
            raise Unreachable(f"couldn't reach {asked['host']}: {reason}", timeout=isinstance(reason, TimeoutError) or "timed out" in str(reason),
                              no_answer=True) from None
        except IncompleteRead:                     # a chunked answer that ended early: worth asking again
            raise Unreachable(f"{asked['host']} cut its answer short", cut=True) from None
        except (HTTPException, ValueError) as e:
            # what urllib lets through as http.client raised it (CR1 #269): an address that can't be
            # sent (InvalidURL for a space or a control character in it, UnicodeEncodeError for a
            # letter outside ASCII, both before anything is sent) and an answer that can't be read (a
            # status line or a header that isn't one). Every error of a request is a SourceError.
            if isinstance(e, (InvalidURL, ValueError)):
                raise Unreachable(f"couldn't ask {asked['host']}: the address {asked['url'][:200]!r} can't be sent ({type(e).__name__})") from None
            raise Unreachable(f"couldn't read {asked['host']}'s answer ({type(e).__name__}: {str(e)[:200]})") from None

    def json(self, url: str, **kw):
        data, hdr, final = self.request(url, **kw)
        try:
            return json.loads(data.decode("utf-8"))
        except ValueError:
            raise Unreachable(f"{urlsplit(final).hostname} didn't return JSON") from None      # the host that answered: a redirect's

    def json_with_headers(self, url: str, **kw):
        data, hdr, final = self.request(url, **kw)
        try:
            return json.loads(data.decode("utf-8")), hdr, final
        except ValueError:
            raise Unreachable(f"{urlsplit(final).hostname} didn't return JSON") from None

    def text(self, url: str, **kw) -> str:
        data, _, _ = self.request(url, accept="*/*", **kw)
        return data.decode("utf-8", "replace")

    def bytes(self, url: str, **kw) -> bytes:
        data, _, _ = self.request(url, accept="*/*", **kw)
        return data


def _declared_length(hdr: dict, method: str) -> int | None:
    """How many bytes an answer said its body has, where it is to send that many: a plain body's
    Content-Length. An answer to HEAD declares what a GET would send, a chunked one ends where its
    chunks say, and an encoded one isn't a plain body; none of them is held to the number."""
    length = hdr.get("content-length", "")
    plain = hdr.get("content-encoding", "identity").strip().lower() in ("", "identity")
    if method.upper() == "HEAD" or "transfer-encoding" in hdr or not plain or not (length.isascii() and length.isdigit()):
        return None
    return int(length)


def _a_time(seconds: float) -> bool:
    """Whether a number of seconds since 1970 is a time a clock can show: one that isn't can't be
    shown on a Source's row either."""
    try:
        datetime.fromtimestamp(seconds)
    except (OverflowError, OSError, ValueError):
        return False
    return True


def _reset_time(hdr: dict) -> float:
    """When a host that said to come back may be asked again: GitHub's reset time, else a
    Retry-After in seconds or as a date, else in a minute. A value that can't be read counts for
    nothing, and that is any that isn't a plain number or a date, or isn't a time at all: "²" is a
    digit to str.isdigit and no number to int, which raised out of Http; and thirty nines are a
    number, and no time a clock can show, which raised where the Source's row was shown."""
    now = time.time()
    reset, after = hdr.get("x-ratelimit-reset", ""), hdr.get("retry-after", "")
    if reset.isascii() and reset.isdigit() and _a_time(float(reset)):
        return float(reset)
    if after.isascii() and after.isdigit():
        if _a_time(now + float(after)):
            return now + int(after)
    elif after:
        try:
            return parsedate_to_datetime(after).timestamp()
        except (TypeError, ValueError, OverflowError):
            pass
    return now + 60
