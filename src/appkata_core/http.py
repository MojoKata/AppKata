"""A small HTTP client: per-host tokens (R9.2.2), rate limits (R9.2.1), typed errors (R2.10)."""

from __future__ import annotations

import contextlib
import http.client
import io
import ipaddress
import json
import re
import socket
import ssl
import threading
import time
import types
import urllib.error
import urllib.request
from datetime import datetime
from email.utils import parsedate_to_datetime
from http.client import HTTPException, IncompleteRead, InvalidURL
from urllib.parse import unquote, urlsplit

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
    is the rest of a whole address where one was pasted. The name is as every rule compares hosts
    (_one_host), in the form it is sent: one typed `übung.example` is kept as `xn--bung-zra.example`,
    the Source's own host however its Source and its token were typed."""
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
SOURCE_PORT = 443       # a Source's port when its host names none: every Source is asked over https (urls.parse)


def _one_host(name: str) -> str:
    """A host's name or address as every rule compares two hosts (_origin, and so _host, _is_for,
    token_key and a limit's key): in the form it is sent (_sent), from the host with its escapes
    decoded and in lower case. So the Source's own host in whichever form it is written, `übung.lan`
    as `xn--bung-zra.lan` or the other way, `git.example` as `%67it.example`, is the Source's own:
    its token's, and the one host that may be local (the review's pass 7, P7-2 and P7-B2). Read as
    written, it was another host, though the request was sent as the Source's own are: an avatar a
    forge on the user's network named in its IDNA form was refused as local, and the forge's
    redirect to itself in another form was refused, or followed without the token. A name with its
    final dot is another host, as it is sent: with its dot, to the lookup, in the Host header and as
    the name TLS checks the certificate against, which no certificate for the name without it is
    for. Taken for the Source's own, it was sent the token, and no request to it got past the
    handshake (the review's pass 8, P8-B2). A name with no IDNA form, which no address Http asks for
    has (_http_address), is kept with its escapes decoded and in lower case: a token typed for it is
    sent nowhere."""
    host = unquote(name).lower()
    with contextlib.suppress(UnicodeError):
        host = _sent(host)
    return host


def _origin(parts) -> tuple:
    """(scheme, host, port) of an address: what a redirect must keep for a token to go on with it.
    The host is as every rule compares hosts (_one_host). The port is the one it names, 0 too, or
    its scheme's where it names none (the review's pass 5, P5-B4: `parts.port or ...` read a written
    `:0` as 443, the Source's own port)."""
    try:
        port = PORTS.get(parts.scheme) if parts.port is None else parts.port
    except ValueError:
        port = None
    return parts.scheme, _one_host(parts.hostname or ""), port


def _host(parts) -> str:
    """An address's host, as a token is kept for it and as a Source's host is written (urls.parse):
    its name, as every rule compares hosts (_one_host), and the port it is asked on unless that is
    443, a Source's when its host names none.
    The one notion of a host that every lookup uses (CR1 #297): the forges named a Source's host
    with its port and Http looked a token up without it, so a token on a port was sent by some calls
    and not by others, and a token kept for a name went to every port of it.

    The port is the one the address is asked on, whatever its scheme (the review's pass 1, P1-2, as
    the owner decided it): `http://git.lan/` is on port 80, and is `git.lan:80`, another host than
    the Source `git.lan`. A host left out its own scheme's port, so it was `git.lan`, and was taken
    for the Source's own by the rule for a local address and shared the Source's rate limit."""
    scheme, name, port = _origin(parts)
    name = f"[{name}]" if ":" in name else name            # an IPv6 address, as an address writes it
    return name if port in (None, SOURCE_PORT) else f"{name}:{port}"


def _is_for(parts, whose: str) -> bool:
    """Whether an address is on the host `whose`, or on one of its named hosts (token_hosts): the
    same name and the same port."""
    return _host(parts) in token_hosts(whose)


# An address's host part as it is written (_http_address): a host, then a `:` and a port where it
# names one. And the host: an IPv6 address in brackets as they are written, not escaped, or a name
# (_a_name_as_sent).
_HOST_PART = re.compile(r"(\[[^\]]*\]|[^:\[\]]*)(?::[0-9]*)?")
_AN_IPV6_ADDRESS = re.compile(r"\[[0-9a-f:.]+\]")
# The most a host part is, its escapes decoded: more than any host and its port, since a name is at
# most 253 characters in the form it is sent, an IPv6 address 47 with its brackets, and a port 6
# with its `:` (the review's pass 8, P8-B1).
_LONGEST_HOST_PART = 300
# Where Python's idna codec ends a name's parts: at a `.` and at IDNA's own dots (the review's pass 6, P6-1).
_IDNA_DOTS = re.compile("[.\u3002\uff0e\uff61]")


def _idna(name: str) -> str:
    """A name's IDNA form, which is ASCII, by Python's idna codec, or UnicodeError where it has none.
    A part of more than 63 characters has none, and is refused before the codec is asked: the codec
    makes a part's form before it measures it, in a time that grows as the square of the part's
    length, so a README's image on a host of one part of 8,000 characters of CJK held a Sync for ten
    seconds, past its deadline and its Cancel, and one of a million would hold it for hours (the
    review's pass 8, P8-B1). A part the codec would bring to 63 by leaving out what it maps to
    nothing, a soft hyphen or a zero-width space, is refused with them: no address names one."""
    if any(len(part) > 63 for part in _IDNA_DOTS.split(name)):
        raise UnicodeError("a part of the name is more than 63 characters")
    return name.encode("idna").decode("ascii")


def _a_name_as_sent(name: str) -> bool:
    """Whether a host, its escapes decoded, is a name in the form it is sent, its IDNA form: ASCII
    letters, digits, `-` and `_`, in parts between dots, none of them empty but for what follows a
    name's one final dot. A name is sent in that form, in lower case (_sent), so a name in any script
    is one, its marks too (the review's pass 5, P5-1), and one whose IDNA form holds what no name
    does isn't: `a⑴b` is sent as `a(1)b`, and `%5b127.0.0.1%5d` as `[127.0.0.1]`, which a proxy reads
    as an address (P5-2). Nor is one with no IDNA form (an empty part, a part of more than 63
    characters, what IDNA has none for), or whose IDNA form has an empty part though the name has
    none: the codec looks for empty parts before it makes the form, which makes dots of `‥` and `㏇`,
    so `a‥b` is sent as `a..b` and `㏇.example` as `co..example` (the review's pass 6, P6-1). Nor is
    a name whose IDNA form changes with its case: with a letter Unicode 3.2 hadn't, such as `Ⱥ`, the
    name written and the one sent are two names, with two addresses."""
    try:
        sent = _idna(name).lower()
        looked_up = _idna(name.lower()).lower()
    except UnicodeError:                     # an empty part, one longer than 63, or what IDNA has no form for
        return False
    return sent == looked_up and re.fullmatch(r"[a-z0-9_-]+(\.[a-z0-9_-]+)*\.?", sent) is not None


def _a_host_and_port(text: str) -> bool:
    """Whether a host part is a host and its port and nothing else (_HOST_PART): an IPv6 address in
    brackets as they are written, or a name in the form it is sent (_a_name_as_sent). One longer
    than any host and its port, its escapes decoded (_LONGEST_HOST_PART), isn't, and is read no
    further: a long name of short parts, each through the idna codec, was a long wait too, and was
    asked for (the review's pass 8, P8-B1)."""
    if len(unquote(text)) > _LONGEST_HOST_PART:
        return False
    host = _HOST_PART.fullmatch(text)
    return host is not None and bool(_AN_IPV6_ADDRESS.fullmatch(host[1].lower()) or _a_name_as_sent(unquote(host[1])))


# An address's host part, as urlsplit reads it once it has dropped the address's tabs and line breaks,
# and as a proxy ends it, at the first `/`: only an address with a `//` right after its scheme has one.
_ITS_HOST_PART = re.compile(r"[a-z][a-z0-9+.-]*://([^/]*)", re.IGNORECASE)


def _named(url: str) -> str:
    """How a refusal names an address: by what follows the last `@` of its host part, written or
    escaped (`%40`, which the rule for a user part reads as an `@`), its escapes decoded, at most 200
    characters; and only where that is a host and its port in the form an address Http asks for has
    (_a_host_and_port), read alike from the host part as a proxy may end it, at the first `/`, and
    as urlsplit ends it, at a `?` or `#` before that; else not at all, "". So no refusal says any
    part of a user part, which may be a password, however it is spelled, nor any of a path or a
    query: a host part is read alone, and what isn't a host's name by both readings is never said.
    Read for an `@` alone, a user part spelled with a full-width `＠` or `%2540` was said whole, and
    the whole address was read where urlsplit can't read it, so the name after an `@` in its path or
    query was said as its host: `(2x.png)` for `.../secret-name@2x.png` (the review's passes 5 to 7,
    P5-B2, P6-B2 and P7-B4)."""
    part = _ITS_HOST_PART.match(re.sub(r"[\t\r\n]", "", url))
    as_a_proxy_reads = part[1] if part else ""
    as_urlsplit_reads = re.split(r"[?#]", as_a_proxy_reads, maxsplit=1)[0]
    named = {re.split(r"@|%40", text, flags=re.IGNORECASE)[-1] for text in (as_a_proxy_reads, as_urlsplit_reads)}
    return unquote(named.pop())[:200] if len(named) == 1 and _a_host_and_port(*named) else ""


def _refused(what: str, url: str) -> Unreachable:
    """The refusal of an address that `what` says, `an address with a user part before its host`,
    naming its host and port where it can (_named)."""
    named = _named(url)
    return Unreachable(f"{what} ({named}) isn't asked for" if named else f"{what} isn't asked for")


def _http_address(url: str):
    """An address in its parts, or Unreachable when it isn't an http or https one with a host: the
    only addresses Http opens, whoever asks (CR1 #266). A project's icon address can say file:, which
    on Windows can name a host to log in to over SMB, or ftp: or data:.

    Nor one whose host part, all that comes between its `//` and the first `/` after them, is more
    than a host and its port (_HOST_PART), the Source's own host's too: an IPv6 address in brackets
    as they are written (_AN_IPV6_ADDRESS), or a name in the form it is sent (_a_name_as_sent).
    urllib sends a proxy all of it: the host it asks for, decoded, in the Host header and a tunnel's
    CONNECT, and over http the whole address. The check reads one host out of that, and a proxy may
    read another (the review's passes 3 to 5):
    - a user part (`user@`, `10.0.0.5%2f@`), where the check read the host after the `@` and a proxy
      may read 10.0.0.5 out of `10.0.0.5/@images.example.com` (P3-1);
    - a `\\`, which this computer's lookup takes for an escape and a browser's reading of an address
      for a `/`: `127.0.0.1\\x.images.example.com` is looked up as `127.0.0.1x.images.example.com`,
      which a project's own domain can answer with a public address (P4-1);
    - a `?` or `#` right after the host, with no path before it: urlsplit's host part ends there,
      and a proxy that ends it only at the first `/` reads 10.0.0.5 out of
      `images.example.com?@10.0.0.5` (P4-1);
    - escaped brackets, which the check reads as a name, `[127.0.0.1]`, and http.client as the
      brackets of an address, 127.0.0.1, which a proxy is sent (P5-2);
    - a tab or a line break in its `//` or its host part, which urlsplit drops before it reads the
      address, and urllib's request doesn't: `http:/\\n/10.0.0.5@h/x//y` has the host part
      `10.0.0.5@h` to urlsplit, whose parts the check and every caller use, and `y` as written. The
      host part as written is held to be urlsplit's, up to a `?` or `#`, and is read once (P5-B1).
    No address Http asks for needs any of these: an image's address has a path, and the host of one
    with a user part is found by no lookup. A user part isn't said, since it may be a password: a
    refusal names an address by a host and its port alone, or not at all (_named; the review's
    passes 5 to 7, P5-B2, P6-B2 and P7-B4)."""
    try:
        parts = urlsplit(url)
        parts.port
    except ValueError:
        parts = None
    written = url.partition("//")[2].partition("/")[0]        # the host part: up to the first `/`, as a proxy may read it
    if parts is None or parts.scheme not in ("http", "https") or not parts.hostname:
        raise _refused("an address that isn't an http or https one", url)
    if re.split(r"[?#]", written, maxsplit=1)[0] != parts.netloc:      # and urlsplit's, up to a `?` or `#` (P5-B1)
        raise _refused("an address whose host part is more than a host and its port", url)
    if "@" in unquote(written):
        raise _refused("an address with a user part before its host", url)
    if not _a_host_and_port(written):
        raise _refused("an address whose host part is more than a host and its port", url)
    return parts


def _sent(host: str) -> str:
    """A host as it is sent, from the host _allowed judges (its escapes decoded, in lower case): a name
    in its IDNA form, which is ASCII, and an address as it is. The lookups have it, and so do the
    Host header, a tunnel's CONNECT, the name TLS checks and the address a proxy is sent over http
    (the review's pass 6, P6-B1). urllib sent the host as written, and http.client writes a Host
    header in Latin-1: a name in another script couldn't be sent at all, a Latin-1 one couldn't be
    sent to a proxy over http, and `übung.example` was sent to its server so, where its lookup and a
    tunnel's CONNECT had `xn--bung-zra.example`. A name's IDNA form is _idna's."""
    return _idna(host)


def _host_part_as_sent(parts) -> str:
    """An address's host part as Http sends it, from what _http_address read of it (`parts`): the
    host _allowed judged as it is sent (_sent), then its port as written. Its host part is a host and
    its port and nothing else (_http_address), so `parts.netloc` is all of it as written."""
    name = _sent(unquote(parts.hostname).lower())
    port = parts.netloc[len(_HOST_PART.fullmatch(parts.netloc)[1]):]      # `:` and the port's digits, as written, or nothing
    return (f"[{name}]" if ":" in name else name) + port


def _as_sent(url: str, parts) -> str:
    """An address as Http sends it, from what _http_address read of it (`parts`): its host part as
    it is sent (_host_part_as_sent), and the rest of it as written."""
    before, slashes, rest = url.partition("//")
    return before + slashes + _host_part_as_sent(parts) + rest[len(rest.partition("/")[0]):]


def _addresses(host: str) -> list[str]:
    """The addresses a host's name stands for, as a connection to it would look them up."""
    return [info[4][0] for info in socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)]


def _local(address: str) -> bool:
    """A loopback, private or link-local address, or any other that isn't a public one (0.0.0.0, a
    carrier's shared range)."""
    ip = ipaddress.ip_address(address.split("%")[0])          # fe80::1%eth0
    ip = getattr(ip, "ipv4_mapped", None) or ip                 # ::ffff:127.0.0.1
    return ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_unspecified or not ip.is_global


def _localhost(name: str) -> bool:
    """localhost and the names under it, which are the computer of whoever looks them up (RFC 6761):
    a proxy's, which may well be this one."""
    name = name.rstrip(".")
    return name == "localhost" or name.endswith(".localhost")


def _a_name(host: str) -> bool:
    """Whether a host is plainly a name, and no address however it is spelled: ASCII letters,
    digits, `-` and `_`, in parts between dots, the last of which isn't a number (all digits, or
    0x and hex digits), which makes the host an IPv4 address to a URL's reader (WHATWG) and to many
    a lookup, `127.1` and `0x7f.1` alike. A trailing dot is a name's own. An address this computer's
    lookup can't read, with a trailing dot, an IPv6 zone or a port inside the host, is one a proxy
    may well read, and connect to (the review's pass 2, P2-1)."""
    name = host.rstrip(".")
    return (re.fullmatch(r"[a-z0-9_-]+(\.[a-z0-9_-]+)*", name) is not None
            and re.fullmatch(r"[0-9]+|0x[0-9a-f]*", name.rsplit(".", 1)[-1]) is None)


def _refuse_local(host: str, addresses) -> None:
    local = [a for a in addresses if _local(a)]
    if local:
        raise Unreachable(f"{host} is on this computer or its local network ({local[0]}): not fetched, "
                          "since it isn't the Source's own host")


_reading = threading.local()     # .clock: the _Clock of the request this thread is making, while it makes it


class _Clock:
    """A request's deadline (R9.2.1) and its thread's Cancel (Http.stopping), which each step of
    the request is held to (_hold): connecting, a TLS handshake, and each read of the answer, its
    status line and headers, a redirect's, and its body (CR1 #695). A host that sent its headers a
    byte at a time held its request past the deadline, and Cancel waited for it."""

    def __init__(self, http: "Http", asked: dict):
        self.http, self.asked, self.started = http, asked, time.monotonic()

    def left(self) -> float:
        """How long the next step may wait: the timeout of a step, or what is left of the deadline
        where that is less. Cancelled at a Cancel, and the deadline's Unreachable once it has gone by."""
        self.http._stop()
        spent = time.monotonic() - self.started
        if spent > self.http.deadline:
            raise self.ended()
        return min(self.http.timeout, self.http.deadline - spent)

    def ended(self) -> Unreachable:
        return Unreachable(f"{self.asked['host']} hadn't finished its answer after {self.http.deadline:g} seconds",
                           timeout=True, deadline=True, no_answer=True)


def _hold(sock, step, *a, **k):
    """One step of a connection's socket, held to the clock of the request its thread is making:
    a look at Cancel and the deadline first, then no longer a wait than what is left of it. A step
    that ran out of the deadline's time is the deadline's error, and isn't asked for again as a
    timeout would be. Outside a request, the step as it is."""
    clock = getattr(_reading, "clock", None)
    if clock is None:
        return step(*a, **k)
    wait = clock.left()
    sock.settimeout(wait)
    try:
        return step(*a, **k)
    except TimeoutError:
        if wait < clock.http.timeout:
            raise clock.ended() from None
        raise


class _HeldReads(io.RawIOBase):
    """A socket's reads, each held to the request's clock (_hold): what an answer of Http's own
    connections is read through, its status line and headers as much as its body, and a proxy's
    answer to a tunnel's CONNECT. It is the reading, not the socket, that is held, so it is the
    same whatever made the socket: a TLS socket is made by the TLS context, which can be the
    operating system's (platform.use_system_certificates) and make its sockets its own way."""

    def __init__(self, sock):
        super().__init__()
        self.sock, self.reads = sock, sock.makefile("rb", buffering=0)

    def readable(self) -> bool:
        return True

    def readinto(self, buffer) -> int | None:
        return _hold(self.sock, self.reads.readinto, buffer)

    def close(self) -> None:
        if not self.closed:
            self.reads.close()
        super().close()


class _HeldAnswer(http.client.HTTPResponse):
    """http.client's answer, read through _HeldReads. It makes its reader with the socket's
    makefile alone, and this one is handed a socket whose makefile is that reader."""

    def __init__(self, sock, *a, **k):
        super().__init__(types.SimpleNamespace(makefile=lambda *_a, **_k: io.BufferedReader(_HeldReads(sock))), *a, **k)


class _HeldTLS:
    """The TLS context of Http's connections: the system's context, whose handshake, one step
    whatever the context does inside it, is held to the request's clock (_hold)."""

    def __init__(self):
        self.context = ssl.create_default_context()        # as urllib's own: the system's certificates, the name checked
        self.context.set_alpn_protocols(["http/1.1"])

    def wrap_socket(self, sock, **kw):
        return _hold(sock, self.context.wrap_socket, sock, **kw)


class _Connections(urllib.request.AbstractHTTPHandler):
    """urllib's handlers of http and https, with connections whose socket is Http's own (`connect`,
    Http._connect): the name is looked up once, held to the rule for a local address, and the socket
    connects to the addresses that were checked. urllib's own connections look the name up again
    when they connect, so a name that answered with a public address for the check and a local one
    for the connection got its request sent into this computer or its network (CR1 #682). Each
    step after that is held to the request's clock (CR1 #695): connecting (Http._connect), the TLS
    handshake (_HeldTLS) and each read of the answer (_HeldAnswer)."""

    def __init__(self, connect):
        super().__init__()
        self.connect = connect
        self.tls = _HeldTLS()

    def _with(self, kind, req, **args):
        def made(host, **kw):
            conn = kind(host, **kw, **args)
            conn._create_connection = lambda address, timeout, source=None: self.connect(req, address, timeout, source)
            conn.response_class = _HeldAnswer
            return conn
        return made

    def http_open(self, req):
        return self.do_open(self._with(http.client.HTTPConnection, req), req)

    def https_open(self, req):
        return self.do_open(self._with(http.client.HTTPSConnection, req, context=self.tls), req)

    http_request = https_request = urllib.request.AbstractHTTPHandler.do_request_


def _proxies() -> dict[str, str]:
    """The system's proxies for http and https: the ones Http's own opener sends through."""
    return {k: v for k, v in urllib.request.getproxies().items() if k in ("http", "https")}


def _bypassed(host: str) -> bool:
    """Whether the system says to reach a host directly, `host` being its host part as it is sent
    (_host_part_as_sent): as urllib decides it (urllib.request.proxy_bypass: by the environment's
    no_proxy where the environment names a proxy, else by the bypass list of the system's own
    settings), and by each of no_proxy's entries in the form it is sent, as every rule compares
    hosts. urllib compares an entry as it is written with the host as it is sent, its IDNA form, so
    an entry in a name's script named no host: with `no_proxy=übung.lan`, every request to the
    Source `übung.lan` went through the proxy, its token inside the tunnel (the review's pass 8,
    P8-2). An entry with no IDNA form is compared as it is written alone."""
    if urllib.request.proxy_bypass(host):
        return True
    entries = []
    for entry in urllib.request.getproxies_environment().get("no", "").split(","):
        with contextlib.suppress(UnicodeError):
            entries.append(_sent(entry.strip().lstrip(".").lower()))      # as urllib reads one, then as it is sent
    return urllib.request.proxy_bypass_environment(host, {"no": ",".join(entries)})


class _Proxies(urllib.request.ProxyHandler):
    """urllib's ProxyHandler, whose request reaches its host directly where Http's rule says so
    (_bypassed), the rule Http._proxied reads too, so Http's check of an address and its request go
    the same way. The check read the host as written and urllib's handler as it is sent, and for a
    name outside ASCII the two went two ways (the review's pass 8, P8-2)."""

    def proxy_open(self, req, proxy, type):
        if req.host and _bypassed(req.host):        # req.host: the host part as it is sent, Http's own request's
            return None
        return super().proxy_open(req, proxy, type)


def _opener(proxies, redirects, connect) -> urllib.request.OpenerDirector:
    """Http's own opener: urllib's default one without its file:, ftp: and data: handlers (CR1 #266),
    with Http's rule for a proxy (_Proxies) and for a redirect, and Http's own connections (CR1 #682)."""
    opener = urllib.request.OpenerDirector()
    for handler in (_Proxies(proxies), urllib.request.UnknownHandler(), _Connections(connect),
                    urllib.request.HTTPDefaultErrorHandler(), redirects, urllib.request.HTTPErrorProcessor()):
        opener.add_handler(handler)
    return opener


TOKEN_HEADERS = ("authorization", "private-token")


class _Redirects(urllib.request.HTTPRedirectHandler):
    """A redirect under R9.2.2. urllib copies a request's headers to wherever a redirect points, so
    Http sends the token as an unredirected header, which urllib never copies, and this hands it on
    by its own rule: only to the same scheme, host and port (a renamed repository's API address
    redirects on its own host), the host in whichever form it is written (_origin). To any other
    host the request goes on without it, and a redirect to plain http of a request that carried a
    token is refused, the same host's too.

    Where a redirect points is held to the rule for a first address (`allowed`, Http._allowed): http
    or https, and no local address but the host's the request was made for (`req.whose`).

    It also keeps `req.asked` up to where the request has got to: the address and the host asked
    last, and whether the token went there. An error is that host's, and is the token's only if it
    was sent (CR1 #683)."""

    def __init__(self, allowed, unlimited):
        self.allowed, self.unlimited = allowed, unlimited

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # a path alone is made an address with the host part the request was sent with, and a forge
        # may write its host out in any form: each is the request's own host to the rules, which
        # compare hosts in the form they are sent (_one_host; the review's pass 7, P7-B2)
        was = urlsplit(req.written)
        whose = getattr(req, "whose", _host(was))
        token = {k: v for k, v in req.unredirected_hdrs.items() if k.lower() in TOKEN_HEADERS}
        try:
            to = self.allowed(newurl, whose)
            if token and to.scheme != "https":
                raise Unreachable(f"{was.hostname} redirected a request that carried its API token to plain http; "
                                  "the redirect wasn't followed")
            self.unlimited(to)                     # a host that said when to come back isn't asked before then (CR1 #705)
        except SourceError:
            fp.close()
            raise
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None:
            new.written, new.full_url = newurl, _as_sent(newurl, to)     # as Http's own request is (Http._request)
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
        # the proxies Http's own opener sends through, the system's; a stand-in opener's requests go
        # through none, whatever the system's settings say
        self.proxies = {} if opener else _proxies()
        self._open = opener or _opener(self.proxies, _Redirects(self._allowed, self._unlimited), self._connect).open
        self._lookup = _addresses                # host -> its addresses: the check's and the connection's (_connect)
        self.forges: dict[str, str] = {}         # host -> its forge type (set_forge)
        self.limited: dict[str, float] = {}      # host (_host: one address) -> reset time
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
        named hosts, in whichever form an address writes it (_one_host); without one, that is the
        address's own host. A host is one address (_host):
        another port of a Source's host is whatever else listens there, and isn't the Source's. A
        first address and every redirect of it are held to this.

        Behind a proxy (_proxied) the name is the proxy's to look up, and the proxy may know names
        this computer doesn't: one this computer can't look up is left to it (the review's pass 1,
        P1-1). What this computer can tell is local is refused all the same: an address, localhost,
        a name it looks up as a local address.

        The host judged is the one the request is sent to: its escapes decoded, in lower case, and in
        the form it is sent (_sent: a name in its IDNA form), in which this lookup and the
        connection's are given it, and a proxy is sent it in the Host header, a tunnel's CONNECT and
        the address over http (_request; the review's pass 6, P6-B1). Only a plain name (_a_name) is
        left to a proxy (the review's pass 2, P2-1). Judged as the address spells it, `%31%30.0.0.5`,
        `127.0.0.1.` or `[fe80::1%25eth0]` failed this computer's lookup and was left to the proxy as
        a name, and the proxy was sent `10.0.0.5`, or an address it reads with its dot or its zone.
        It is judged in the form it is sent, so a name in any script is one: judged in its script,
        `übung.example.org` was refused where `xn--bung-zra.example.org`, the name the proxy is sent,
        was left to it (the review's pass 7, P7-3); and full-width `ｌｏｃａｌｈｏｓｔ`, sent as
        `localhost`, is refused. An address whose host part is more than a host and its port (a user part, a `\\`, a `?` or
        `#` before any path), which urllib sends to a proxy along with the host, is refused before
        any of this, by _http_address (the review's passes 3 and 4, P3-1 and P4-1)."""
        parts = _http_address(url)
        host = unquote(parts.hostname).lower()     # as it is judged: the host alone here (_http_address)
        if whose is None or _is_for(parts, token_key(whose)):
            return parts
        sent = _sent(host)                         # as it is sent, the lookup's and the proxy's
        try:
            addresses = self._lookup(sent)
        except (OSError, ValueError) as e:        # no such name: what the connection would have found
            if self._proxied(parts) and _a_name(sent) and not _localhost(sent):
                return parts                      # unless it is the proxy's, which looks the name up itself
            raise Unreachable(f"couldn't reach {host}: {e}") from None
        _refuse_local(host, addresses)
        return parts

    def _proxied(self, parts) -> bool:
        """Whether a request to this address goes through a proxy, as Http's own opener decides it
        (_Proxies): one of Http's proxies is for its scheme, and the system doesn't say to reach its
        host directly (_bypassed: no_proxy, or the bypass list of the system's own settings), its
        host part read as it is sent, as the opener reads it. Read as written, a name outside ASCII
        was taken for direct where the request went through the proxy, or the other way (the
        review's pass 8, P8-2)."""
        return parts.scheme in self.proxies and not _bypassed(_host_part_as_sent(parts))

    def _unlimited(self, parts) -> None:
        """RateLimited when the host of this address said when to come back and that time hasn't
        come (R9.2.1): before a request is sent, and before a redirect is followed. A host's limit
        is kept as its token is (CR1 #697): under the one address, its name and its port (_host).
        Kept by the name alone, two forges on one name shared it, and a limit one of them answered
        refused every request to the other until it ran out."""
        limit = _host(parts)
        reset = self.limited.get(limit)
        if reset and reset > time.time():
            raise RateLimited(limit, reset, self.limit_status.get(limit))

    def _connect(self, req, address, timeout, source=None) -> socket.socket:
        """The socket of a connection of Http's own opener (_Connections), to `address`, (name, port).
        The name is looked up here, once, and the socket connects to the addresses that lookup gave:
        so the rule of _allowed holds for the address the request is sent to, whatever the name
        answers to another lookup (CR1 #682). _allowed checks a first address and each redirect
        before it is asked for, with its own lookup; this is what the request is held to.

        Behind a proxy the connection is the proxy's, which may well be on this computer: the
        request's own host is then looked up by the proxy, and only _allowed's check is made.

        An address that fails at any step, reading it, making its socket (an IPv6 one on a
        computer with IPv6 off) or connecting, is passed over for the next, as
        socket.create_connection does (the review's pass 1, P1-B3); the last failure is the
        request's when none connects."""
        name, port = address
        addresses = self._lookup(name)              # an OSError: urllib's "couldn't reach", as before
        parts = urlsplit(req.written)               # as written, as the refusal names it; the rule reads it as sent (_one_host)
        if not (req.has_proxy() or req._tunnel_host or _is_for(parts, getattr(req, "whose", None) or _host(parts))):
            _refuse_local(parts.hostname or name, addresses)
        failed = OSError(f"{name} has no address")
        for each in addresses:
            sock = None
            try:
                family, kind, proto, _, at = socket.getaddrinfo(each, port, type=socket.SOCK_STREAM, flags=socket.AI_NUMERICHOST)[0]
                sock = socket.socket(family, kind, proto)
                if isinstance(timeout, (int, float)):        # else urllib's "no timeout given"
                    sock.settimeout(timeout)
                if source:
                    sock.bind(source)
                _hold(sock, sock.connect, at)                # held to the request's clock, as each read is
                return sock
            except OSError as e:
                if sock is not None:
                    sock.close()
                failed = e
            except BaseException:                            # the deadline, or a Cancel
                if sock is not None:
                    sock.close()
                raise
        raise failed

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

    def _read(self, r, clock: _Clock, max_bytes: int) -> bytes:
        """An answer's body, a piece at a time, with a look at the clock and at Cancel before each
        piece (CR1 #296). `timeout` alone is for each read: a host that sent one byte every few
        seconds never met it, and held its reader for as long as it liked, with the Sync's Cancel
        unable to stop it. read1 comes back with what one read of the socket gave, so no piece
        waits for more than `timeout`; Http's own connections hold each read to the clock as well
        (_HeldAnswer), as they held what came before the body."""
        read = getattr(r, "read1", None) or r.read
        pieces, size = [], 0
        while True:
            clock.left()
            piece = read(min(PIECE, max_bytes + 1 - size))
            if not piece:
                return b"".join(pieces)
            pieces.append(piece)
            size += len(piece)
            if size > max_bytes:
                raise Unreachable(f"response from {clock.asked['host']} too large")

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
        self._unlimited(parts)
        token = self._token(parts, whose, forge)
        h = {"User-Agent": UA, "Accept": accept, **(headers or {})}
        # sent with its host as it is sent (_as_sent; the review's pass 6, P6-B1), and kept as written,
        # which a redirect's and a connection's refusals name; every rule compares hosts in the form
        # they are sent (_one_host), whichever form they are written in (the review's pass 7, P7-2)
        req = urllib.request.Request(_as_sent(url, parts), data=body, headers=h, method=method)
        req.written = url
        req.whose = whose                          # for a redirect: _Redirects
        # the address and the host asked last, and whether the token went there: _Redirects moves
        # them on, since what comes after a redirect is another host's answer, or its failure to
        # give one, and that host may have been sent no token. Every error below is said of the
        # host asked last (CR1 #683), and so is a limit (CR1 #705).
        req.asked = asked = {"url": url, "host": host, "token": bool(token)}
        for k, v in token.items():
            req.add_unredirected_header(k, v)      # so a redirect doesn't carry it on: _Redirects decides
        self.calls += 1
        _reading.clock = clock = _Clock(self, asked)    # from here to the last byte, each step is held to it
        try:
            with self._open(req, timeout=self.timeout) as r:
                data = self._read(r, clock, max_bytes)
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
            # a limit is the host's that answered with it (CR1 #705): after a redirect, the host it
            # led to, such as a forge's file storage, and not the forge first asked, whose own API
            # was held back for a limit it never gave
            limit = _host(urlsplit(asked["url"]))
            if e.code in (403, 429) and (hdr.get("x-ratelimit-remaining") == "0" or "retry-after" in hdr or e.code == 429):
                reset = _reset_time(hdr)
                self.limited[limit], self.limit_status[limit] = reset, e.code
                raise RateLimited(limit, reset, e.code) from None
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
                    self.limited[limit], self.limit_status[limit] = reset, e.code
                    if e.code >= 500:
                        raise RateLimited(limit, reset, e.code) from None
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
        finally:
            _reading.clock = None

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
            at = parsedate_to_datetime(after).timestamp()
        except (TypeError, ValueError, OverflowError):
            at = None
        if at is not None and _a_time(at):            # the last hours of the year 9999 are the year 10000 east of Greenwich
            return at
    return now + 60
