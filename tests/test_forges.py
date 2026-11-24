"""Forge API parsing against recorded responses, so no forge needs to be reachable."""

import inspect
import io
import ipaddress
import json
import os
import re
import socket
import ssl
import subprocess
import threading
import time
import types
import urllib.error
import urllib.parse
import urllib.request
from http.client import BadStatusLine, HTTPConnection, IncompleteRead, InvalidURL, LineTooLong
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from appkata_core import channels, explore, forges, metadata, sync, urls
from appkata_core import http as http_
from appkata_core.db import DB, now
from appkata_core.http import Http, RateLimited, SourceError, Unreachable
import reqdocs


class FakeResponse(io.BytesIO):
    def __init__(self, url, body, headers=None):
        super().__init__(body if isinstance(body, bytes) else json.dumps(body).encode())
        self._url, self.headers = url, headers or {}

    def geturl(self):
        return self._url

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def opener(routes):
    def open_(req, timeout=0):
        url = req.full_url
        for prefix, body in routes.items():
            if url.startswith(prefix):
                if isinstance(body, BaseException):         # what opening the address ends in
                    raise body
                if isinstance(body, int):
                    raise urllib.error.HTTPError(url, body, "err", {"x-ratelimit-remaining": "0", "x-ratelimit-reset": str(int(time.time()) + 60)}, None)
                return FakeResponse(url, body)
        raise urllib.error.HTTPError(url, 404, "nf", {}, None)
    return open_


def test_gitlab_releases_and_uploads():
    api = "https://gitlab.com/api/v4/projects/inkscape%2Finkscape"
    http = Http(opener=opener({
        api + "/releases": [{"tag_name": "INKSCAPE_1_4_2", "name": "Inkscape 1.4.2", "released_at": "2026-05-02T00:00:00Z",
                             "description": "Downloads: [Inkscape-1.4.2.AppImage](/uploads/abc/Inkscape-1.4.2-x86_64.AppImage)",
                             "assets": {"links": [{"name": "inkscape-1.4.2.tar.xz", "direct_asset_url": "https://x/inkscape-1.4.2.tar.xz"}]}}],
        api: {"name": "inkscape", "path_with_namespace": "inkscape/inkscape", "default_branch": "master", "web_url": "https://gitlab.com/inkscape/inkscape"},
    }))
    f = forges.GitLab(http, urls.parse("https://gitlab.com/inkscape/inkscape"))
    assert f.info().default_branch == "master"
    r = f.releases()[0]
    assert r.name == "Inkscape 1.4.2" and {a.name for a in r.assets} == {"inkscape-1.4.2.tar.xz", "Inkscape-1.4.2-x86_64.AppImage"}
    assert f.raw_url("README.md", "master") == "https://gitlab.com/inkscape/inkscape/-/raw/master/README.md"


def test_forgejo_detection_and_releases():
    http = Http(opener=opener({
        "https://git.example.net/api/v1/version": {"version": "11.0.1+gitea-1.22.0"},
        "https://git.example.net/api/v1/repos/team/app/releases": [
            {"tag_name": "v2.0.0", "name": "", "published_at": "2026-02-01T00:00:00Z", "prerelease": False,
             "assets": [{"name": "app-2.0.0-x86_64.AppImage", "browser_download_url": "https://git.example.net/a", "size": 5}]},
            {"tag_name": "v2.1.0-rc1", "published_at": "2026-03-01T00:00:00Z", "prerelease": True, "assets": []}],
    }))
    assert forges.detect(http, "git.example.net") == "forgejo"
    f = forges.forge_for(http, urls.parse("https://git.example.net/team/app"), "forgejo")
    rels = f.releases()
    assert forges.latest(rels).version == "2.0.0" and forges.latest(rels, include_pre=True).version == "2.1.0-rc1"


def test_rate_limit_is_typed_and_remembered():
    http = names(Http(opener=opener({"https://api.github.com/repos/a/b": 403})))
    f = forges.GitHub(http, urls.parse("https://github.enterprise.example/a/b"), api="https://api.github.com")
    with pytest.raises(RateLimited):
        f._info_api()
    assert http.limited["api.github.com"] > time.time()


def test_github_pages_skip_bare_tags_when_rate_limited():
    """A monorepo's feed lists crate tags without files first; the real release still gets its files."""
    entry = ('<entry><updated>{d}</updated><link rel="alternate" href="https://github.com/o/r/releases/tag/{t}"/>'
             '<title>{t}</title><content></content></entry>')
    tags = [f"crate-0.4.{n}" for n in range(9, 3, -1)] + ["15.2.0"]
    atom = '<feed xmlns="http://www.w3.org/2005/Atom">' + "".join(entry.format(t=t, d="2026-07-15T00:00:00Z") for t in tags) + "</feed>"
    page = '<a href="/o/r/releases/download/15.2.0/r-15.2.0-x86_64-pc-windows-msvc.zip">x</a> <relative-time datetime="2026-07-15T16:26:10Z">'
    http = Http(opener=opener({
        "https://api.github.com/": 403,
        "https://github.com/o/r/releases.atom": atom.encode(),
        "https://github.com/o/r/releases/expanded_assets/15.2.0": page.encode(),
        "https://github.com/o/r/releases/expanded_assets/": b"<p>no files</p>",
    }))
    rels = forges.forge_for(http, urls.parse("https://github.com/o/r"), "github").releases()
    with_files = [r for r in rels if r.assets]
    assert [r.version for r in with_files] == ["15.2.0"] and with_files[0].assets[0].name.endswith("windows-msvc.zip")


# One repository, as GitHub serves it through the API and through its pages (review 3, R3-23). The
# fallback reads the feed, which lists bare tags too; the API lists releases only. The class is two
# paths deciding the same fact, here which releases a project has: they must agree.
REPO = [   # newest first: (tag, title, prerelease, files, released)
    ("v2.15.1", "v2.15.1", False, [], False),                 # a bare tag: on the feed, not a release
    ("v2.15.0", "2.15 New Year Update", False, ["app-2.15.0-linux.AppImage"], True),
    ("v2.15.0-pre-release", "2.15.0-pre-release", True, ["app-2.15.0-pre-linux.AppImage"], True),
    ("v2.14.0", "v2.14.0", False, ["app-2.14.0-linux.AppImage"], True),   # a release titled as its tag
    ("v2.13.0", "v2.13.0", False, [], True),                  # a release with only its source
    ("v2.12.5", "2.12.5", True, ["app-2.12.5-linux.AppImage"], True),   # marked a prerelease; its tag doesn't say
    ("crate-0.4.9", "crate-0.4.9", False, [], False),         # another bare tag, further down
    ("v2.12.0", "Twelve", False, ["app-2.12.0-linux.AppImage"], True),
]


def _github_both_ways(api_down):
    def stamp(n):
        return f"2026-0{9 - n}-01T00:00:00Z"
    entry = ('<entry><updated>{d}</updated><link rel="alternate" href="https://github.com/o/r/releases/tag/{t}"/>'
             '<title>{title}</title><content>notes</content></entry>')
    atom = '<feed xmlns="http://www.w3.org/2005/Atom">' + "".join(
        entry.format(t=t, title=title, d=stamp(n)) for n, (t, title, _, _, _) in enumerate(REPO)) + "</feed>"
    routes = {
        "https://github.com/o/r/releases.atom": atom.encode(),
    }
    label = '<span data-view-component="true" class="Label Label--warning Label--large">Pre-release</span>'
    listing = "".join(f'<a href="/o/r/releases/tag/{t}">{title}</a>{label if pre else ""}<div>notes, a Pre-release</div>'
                      for t, title, pre, _, rel in REPO if rel)
    for n, (t, title, pre, files, rel) in enumerate(REPO):
        routes[f"https://github.com/o/r/releases/tag/{t}"] = (
            f'<p>someone {"released" if rel else "tagged"} this</p>').encode()
        routes[f"https://github.com/o/r/releases/expanded_assets/{t}"] = (
            "".join(f'<a href="/o/r/releases/download/{t}/{f}">{f}</a> <span>1 MB</span>' for f in files)
            + f'<a href="/o/r/archive/refs/tags/{t}.zip">Source code</a><relative-time datetime="{stamp(n)}">').encode()
    api = [{"tag_name": t, "name": title, "prerelease": pre, "published_at": stamp(n), "draft": False,
            "assets": [{"name": f, "browser_download_url": f"https://github.com/o/r/releases/download/{t}/{f}", "size": 1}
                       for f in files]}
           for n, (t, title, pre, files, rel) in enumerate(REPO) if rel]
    if api_down:
        routes["https://api.github.com/"] = 403
    else:
        routes["https://api.github.com/repos/o/r/releases"] = api
    routes["https://github.com/o/r/releases"] = listing.encode()
    # opener() takes the first route that prefixes the URL: the longest first, so that v2.15.0's pages
    # don't answer for v2.15.0-pre-release's
    return Http(opener=opener(dict(sorted(routes.items(), key=lambda kv: -len(kv[0])))))


def _read(http):
    rels = forges.forge_for(http, urls.parse("https://github.com/o/r"), "github").releases()
    return rels, {r.tag: (r.prerelease, sorted(a.name for a in r.assets)) for r in rels}


def test_the_pages_and_the_api_list_the_same_releases():
    api_rels, api = _read(_github_both_ways(api_down=False))
    web_rels, web = _read(_github_both_ways(api_down=True))
    assert list(web) == list(api), (list(web), list(api))
    assert forges.latest(web_rels).version == forges.latest(api_rels).version == "2.15.0"
    for tag, (pre, files) in web.items():               # the pages read files for the newest few only
        assert pre == api[tag][0], tag
        assert not files or files == api[tag][1], tag


def test_without_the_releases_page_the_pages_keep_every_feed_entry():
    # unknown is kept, as before: a missing page must not lose releases
    http = _github_both_ways(api_down=True)
    real = http._open

    def no_listing(req, timeout=0):
        if req.full_url.rstrip("/") == "https://github.com/o/r/releases":
            raise urllib.error.HTTPError(req.full_url, 500, "err", {}, None)
        return real(req, timeout)
    http._open = no_listing
    _, web = _read(http)
    assert list(web) == [t for t, *_ in REPO]


# ---------------------------------------------------------------- where a token goes (R9.2.2)
# CR1's #263: Http took the token from a host its caller named, whatever the address it then asked
# for, and Sync named the Source's host for every image, the ones a project's README and metainfo
# write themselves too. No test looked at what a request carried: every fake opener here answered by
# the address alone. The class is "a request carries the token of a host it isn't for", so the
# harness records each request with its headers, and the whole-Sync test holds every request a Sync
# makes to the one rule, whichever line asked for it.
PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 16


def recording(routes, seen):
    """opener(), noting each request as (address, its headers by lower-case name)."""
    answer = opener(routes)

    def open_(req, timeout=0):
        seen.append((req.full_url, {k.lower(): v for k, v in req.header_items()}))
        return answer(req, timeout)
    return open_


PUBLIC = "8.8.8.8"


def names(http, table=None):
    """Stands in for the name lookup, so no test asks a name server: a host in `table` gets its
    addresses there, an address is itself, and every other name gets a public address."""
    def lookup(host):
        if host in (table or {}):
            return table[host]
        try:
            return [str(ipaddress.ip_address(host))]
        except ValueError:
            return [PUBLIC]
    http._lookup = lookup
    return http


def tokened(seen):
    """The addresses that were sent a token, in either header."""
    return [url for url, h in seen if "authorization" in h or "private-token" in h]


def _ask(http, url, **kw):
    try:
        http.bytes(url, **kw)
    except SourceError:
        pass


@pytest.mark.parametrize("url, sent", [
    ("https://github.com/o/r", True),
    ("https://api.github.com/repos/o/r", True),
    ("https://raw.githubusercontent.com/o/r/main/README.md", True),
    ("https://avatars.githubusercontent.com/u/1", False),            # GitHub's, but not a named host
    ("https://evil.example/screenshot.png", False),
    ("https://notgithub.com/o/r", False),                            # ends in the same letters
    ("https://api.github.com.evil.example/repos/o/r", False),        # starts with them
    ("https://github.com@evil.example/o/r", False),                  # the host is evil.example
    ("http://github.com/o/r", False),                                # plain http: never
    ("http://api.github.com/repos/o/r", False),
    ("http://raw.githubusercontent.com/o/r/main/icon.png", False),
])
def test_the_github_token_goes_to_its_named_hosts_over_https_and_nowhere_else(url, sent):
    seen = []
    http = names(Http({"github.com": "ghp_SECRET", "evil.example": ""}, opener=recording({}, seen)))
    _ask(http, url, token_host="github.com")
    assert [u for u, _ in seen] == [url]
    assert tokened(seen) == ([url] if sent else []), seen
    if sent:
        assert seen[0][1]["authorization"] == "Bearer ghp_SECRET"


@pytest.mark.parametrize("host, header", [("gitlab.com", "private-token"), ("codeberg.org", "authorization")])
def test_another_hosts_token_goes_to_that_host_alone(host, header):
    seen = []
    http = names(Http({host: "SECRET"}, opener=recording({}, seen)))
    for url in (f"https://{host}/api/x", f"https://api.{host}/x", f"https://raw.{host}/x", f"http://{host}/api/x",
                "https://api.github.com/x", "https://raw.githubusercontent.com/x", "https://evil.example/x.png"):
        _ask(http, url, token_host=host)
    assert tokened(seen) == [f"https://{host}/api/x"]
    assert "SECRET" in seen[0][1][header]


def test_a_request_that_names_no_host_gets_its_own_hosts_token_and_no_other():
    seen = []
    http = Http({"github.com": "ghp_SECRET", "gitlab.com": "glpat_SECRET"}, opener=recording({}, seen))
    for url in ("https://github.com/o/r/releases.atom", "http://github.com/o/r/releases.atom",
                "https://gitlab.com/o/r", "https://flathub.org/api/v2/x"):
        _ask(http, url)
    assert [(u, h.get("authorization") or h.get("private-token")) for u, h in seen if u in tokened(seen)] == [
        ("https://github.com/o/r/releases.atom", "Bearer ghp_SECRET"), ("https://gitlab.com/o/r", "glpat_SECRET")]


@pytest.mark.parametrize("url, sent", [
    ("https://raw.githubusercontent.com/o/r/main/icon.png", True),   # the Source's own file
    ("https://evil.example/screenshot.png", False),                  # what a README or a metainfo names
    ("http://evil.example/screenshot.png", False),
    ("https://gitlab.com/o/r/-/raw/main/shot.png", False),           # another forge the user has a token for
])
def test_an_image_on_another_host_is_fetched_without_the_sources_token(tmp_path, url, sent):
    seen = []
    http = names(Http({"github.com": "ghp_SECRET", "gitlab.com": "glpat_SECRET"}, opener=recording({url: PNG}, seen)))
    assert sync._save_image(http, url, str(tmp_path / "hero"), token_host="github.com") == str(tmp_path / "hero.png")
    assert tokened(seen) == ([url] if sent else []), seen


METAINFO = """<?xml version="1.0" encoding="UTF-8"?>
<component type="desktop-application"><id>org.example.r</id><name>R</name><summary>An app</summary>
<icon type="remote">https://evil.example/icon.png</icon>
<screenshots><screenshot type="default"><image>http://evil.example/shot.png</image></screenshot></screenshots>
</component>"""


def test_a_whole_sync_sends_the_token_to_the_sources_named_hosts_alone(tmp_path):
    """Every request of a Sync, against the rule: a token only over https, only to the Source's host and
    its named API and raw-file hosts. The project's metainfo and README name images elsewhere."""
    api, raw = "https://api.github.com/repos/o/r", "https://raw.githubusercontent.com/o/r/main/"
    seen = []
    http = names(Http({"github.com": "ghp_SECRET"}, opener=recording({
        api + "/releases": [{"tag_name": "v1.0.0", "name": "1.0", "published_at": "2026-05-02T00:00:00Z", "assets": []}],
        api + "/git/trees/main": {"tree": [{"path": p, "type": "blob"} for p in (
            "README.md", "data/org.example.r.metainfo.xml", "data/icons/icon.png", "docs/window.png")]},
        api: {"name": "r", "full_name": "o/r", "default_branch": "main",
              "owner": {"avatar_url": "https://avatars.githubusercontent.com/u/1"}},
        raw + "README.md": b"# R\n\n![shot](https://evil.example/screenshot.png)\n\n![window](docs/window.png)\n",
        raw + "data/org.example.r.metainfo.xml": METAINFO.encode(),
        raw + "docs/window.png": PNG,
        "https://avatars.githubusercontent.com/u/1": PNG,
    }, seen)))
    db = DB(str(tmp_path / "a.db"))
    sync.sync_app(db, http, "https://github.com/o/r", root=str(tmp_path))
    app = db.one("SELECT * FROM apps WHERE url=?", ("https://github.com/o/r",))
    assert app["error_code"] is None and app["icon"].endswith("icon.png") and app["hero"].endswith("hero.png")
    asked = [u for u, _ in seen]
    for elsewhere in ("https://evil.example/icon.png", "http://evil.example/shot.png",
                      "https://evil.example/screenshot.png", "https://avatars.githubusercontent.com/u/1"):
        assert elsewhere in asked, asked               # the Sync did ask for each of them
    allowed = ("https://api.github.com/", "https://raw.githubusercontent.com/", "https://github.com/")
    assert [u for u in tokened(seen) if not u.startswith(allowed)] == []
    assert sorted(set(tokened(seen))) == sorted({u for u in asked if u.startswith(allowed)})


def test_r9_2_2_names_the_hosts_the_code_sends_a_token_to():
    """CR1's #276: R9.2.2 said a token never goes to another host, while github.com's goes to its API
    and raw-file hosts by design, and it gave no list to hold the code to. It names them now, and the
    code keeps them in one place: the two say the same."""
    text = reqdocs.item("R9.2.2")
    named = set(re.findall(r"`([a-z0-9-]+(?:\.[a-z0-9-]+)+)`", text))
    assert named == {h for host in http_.TOKEN_HOSTS for h in http_.token_hosts(host)}, text
    assert named == {"github.com", "api.github.com", "raw.githubusercontent.com"}
    assert "every other host" in text and http_.token_hosts("git.example.net") == ("git.example.net",)


# ---------------------------------------------------------------- a redirect (R9.2.2)
# CR1's #264: urllib copies a request's headers to wherever a redirect points, the token with them,
# and follows https to http. The fake openers above stand in for urlopen whole, so no test ever ran
# a redirect: these go through Http's own opener and real sockets, to two servers on this machine.
class _Recorder(BaseHTTPRequestHandler):
    """Notes each request as (path, its headers by lower-case name), and redirects the paths it is told to.
    With `files` it is a forge: a path there (its query left out) is answered with its bytes, or as
    JSON, or by a function that writes the answer itself, and any other path is a 404."""

    def do_GET(self):
        self.server.seen.append((self.path, {k.lower(): v for k, v in self.headers.items()}))
        to = self.server.redirects.get(self.path)
        body, status = (b"" if to else b'{"ok": true}'), (302 if to else 200)
        if not to and self.server.files is not None:
            body = self.server.files.get(urllib.parse.urlsplit(self.path).path)
            if callable(body):
                return body(self)
            status = 404 if body is None else 200
            body = b"" if body is None else body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(status)
        if to:
            self.send_header("Location", to)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


@pytest.fixture
def pair(monkeypatch):
    """Servers A and B, reached as https://127.0.0.1:<port> and https://localhost:<port>: two host
    names. A token is only ever sent over https, and a certificate for this machine would have to be
    made first, so urllib's https handler is given a plain connection: the request, its headers and
    the redirect are handled as https all the way, and only the encryption is left out."""
    monkeypatch.setattr(urllib.request.HTTPSHandler, "https_open", lambda self, req: self.do_open(HTTPConnection, req))
    servers = []
    for host in ("127.0.0.1", "localhost"):
        server = ThreadingHTTPServer(("127.0.0.1", 0), _Recorder)
        server.seen, server.redirects, server.files = [], {}, None
        server.at = f"{host}:{server.server_address[1]}"
        threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True).start()
        servers.append(server)
    yield servers
    for server in servers:
        server.shutdown()
        server.server_close()


def _with_token(monkeypatch, header, a):
    """An Http with a token for server A (its address: its name and its port), sent in the named
    header. Server B's name counts as a public host's here: a redirect to an address on this computer
    is refused (further down)."""
    http = names(Http({a.at: "SECRET-TOKEN"}, timeout=10))
    if header == "private-token":            # the form a host named for GitLab gets
        monkeypatch.setattr(http, "_auth", lambda *a, **k: {"PRIVATE-TOKEN": "SECRET-TOKEN"})
    return http


def _secrets(seen):
    return [(path, k) for path, h in seen for k, v in h.items() if "SECRET-TOKEN" in v]


@pytest.mark.parametrize("header", ["authorization", "private-token"])
def test_a_redirect_to_another_host_arrives_without_the_token(pair, monkeypatch, header):
    a, b = pair
    a.redirects["/api/x"] = f"https://{b.at}/elsewhere"
    assert _with_token(monkeypatch, header, a).json(f"https://{a.at}/api/x") == {"ok": True}
    assert _secrets(a.seen) == [("/api/x", header)]
    assert [path for path, _ in b.seen] == ["/elsewhere"] and _secrets(b.seen) == []
    assert not {"authorization", "private-token"} & set(b.seen[0][1])


@pytest.mark.parametrize("header", ["authorization", "private-token"])
def test_a_redirect_on_the_same_host_keeps_the_token(pair, monkeypatch, header):
    # a renamed repository's API address answers with a redirect on the same host
    a, b = pair
    a.redirects["/api/old"] = "/api/new"
    assert _with_token(monkeypatch, header, a).json(f"https://{a.at}/api/old") == {"ok": True}
    assert _secrets(a.seen) == [("/api/old", header), ("/api/new", header)]


@pytest.mark.parametrize("header", ["authorization", "private-token"])
@pytest.mark.parametrize("to", ["a", "b"])
def test_a_redirect_from_https_to_http_of_a_request_with_a_token_is_refused(pair, monkeypatch, header, to):
    a, b = pair
    a.redirects["/api/x"] = f"http://{(a if to == 'a' else b).at}/plain"
    with pytest.raises(Unreachable, match="http"):
        _with_token(monkeypatch, header, a).json(f"https://{a.at}/api/x")
    assert [path for path, _ in a.seen] == ["/api/x"] and b.seen == []      # /plain was never asked for


def test_a_redirect_from_https_to_http_without_a_token_is_followed(pair):
    a, b = pair
    a.redirects["/x"] = f"http://{b.at}/plain"
    assert names(Http({"gitlab.com": "SECRET-TOKEN"}, timeout=10)).json(f"https://{a.at}/x") == {"ok": True}
    assert [path for path, _ in b.seen] == ["/plain"] and _secrets(a.seen + b.seen) == []


# ---------------------------------------------------------------- which addresses are opened at all
# CR1's #266: Http opened whatever urllib can, so a project's icon address could be a file on this
# computer, or on Windows a file: address that makes it log in to a host over SMB; and any image
# address could be on this computer or its local network. Only the hero loop looked at an address,
# and only for "http" at its start. The class is "an address a project wrote is opened as it stands",
# so the rule is Http's, for every caller: http and https alone, and no host that stands for a local
# address unless it is the Source's own.
NOT_HTTP = ["file:///etc/hostname", "file://attacker.example/share/icon.png", "file:////attacker.example/share/icon.png",
            "ftp://attacker.example/icon.png", "data:image/png;base64,iVBORw0KGgo=", "FILE:///etc/hostname",
            "gopher://attacker.example/", "icon.png", ""]


@pytest.mark.parametrize("url", NOT_HTTP)
@pytest.mark.parametrize("call", ["bytes", "text", "json", "json_with_headers", "request"])
def test_only_http_and_https_addresses_are_opened_whoever_asks(url, call):
    seen = []
    http = names(Http(opener=recording({url or "x": PNG}, seen)))
    with pytest.raises(Unreachable):
        getattr(http, call)(url)
    assert seen == [] and http.calls == 0


def test_https_own_opener_has_no_way_to_open_anything_but_http_and_https(tmp_path):
    (tmp_path / "private.png").write_bytes(PNG)
    http = Http(timeout=5)
    for url in ((tmp_path / "private.png").as_uri(), "ftp://127.0.0.1:1/icon.png", "data:text/plain,hi"):
        with pytest.raises(urllib.error.URLError, match="unknown url type"):
            http._open(urllib.request.Request(url), timeout=5).close()


def test_a_file_address_is_not_saved_as_an_icon(tmp_path):
    # with Http's own opener: the review saved a local file's bytes as icon.png this way
    (tmp_path / "private.png").write_bytes(PNG)
    with pytest.raises(Unreachable):
        sync._save_image(Http(timeout=5), (tmp_path / "private.png").as_uri(), str(tmp_path / "icon"), token_host="github.com")
    assert sorted(p.name for p in tmp_path.iterdir()) == ["private.png"]


LOCAL = ["127.0.0.1", "127.8.9.1", "192.168.1.1", "10.0.0.5", "172.16.0.9", "169.254.1.1", "169.254.169.254", "0.0.0.0",
         "100.64.0.1", "::1", "fe80::1", "fe80::1%eth0", "fd00::1", "::ffff:127.0.0.1", "::ffff:192.168.1.1", "::"]


@pytest.mark.parametrize("address", LOCAL)
def test_an_image_whose_host_stands_for_a_local_address_is_refused(tmp_path, address):
    url, seen = "https://img.example/shot.png", []
    for addresses in ([address], [PUBLIC, address]):          # one local address among a host's is enough
        http = names(Http(opener=recording({url: PNG}, seen)), {"img.example": addresses})
        with pytest.raises(Unreachable, match="img.example"):
            sync._save_image(http, url, str(tmp_path / "hero"), token_host="github.com")
    assert seen == [] and list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("url", ["http://127.0.0.1:8080/shot.png", "http://192.168.1.1/shot.png", "https://169.254.1.1/shot.png",
                                 "http://[::1]:8080/shot.png", "http://localhost:631/shot.png"])
def test_an_image_at_a_local_address_is_refused_by_the_real_lookup(tmp_path, url):
    # no stand-in: an address needs no name server, and neither does localhost
    seen = []
    with pytest.raises(Unreachable):
        sync._save_image(Http(opener=recording({url: PNG}, seen)), url, str(tmp_path / "hero"), token_host="github.com")
    assert seen == [] and list(tmp_path.iterdir()) == []


def test_a_host_whose_name_cant_be_looked_up_is_refused_too(tmp_path):
    def fails(host):
        raise OSError("Name or service not known")
    seen = []
    http = Http(opener=recording({"https://img.example/shot.png": PNG}, seen))
    http._lookup = fails
    with pytest.raises(Unreachable, match="img.example"):
        sync._save_image(http, "https://img.example/shot.png", str(tmp_path / "hero"), token_host="github.com")
    assert seen == []


@pytest.mark.parametrize("address", ["127.0.0.1", "192.168.1.1", "169.254.1.1"])
def test_the_sources_own_host_may_stand_for_a_local_address(tmp_path, address):
    # a forge on the user's own network: its files, its API and what names no other host
    url, seen = "https://git.lan.example/o/r/raw/branch/main/shot.png", []
    http = names(Http({"git.lan.example": "SECRET"}, opener=recording({"https://git.lan.example/": PNG}, seen)),
                 {"git.lan.example": [address]})
    assert sync._save_image(http, url, str(tmp_path / "hero"), token_host="git.lan.example").endswith("hero.png")
    assert http.bytes("https://git.lan.example/api/v1/version") == PNG
    assert [u for u, _ in seen] == [url, "https://git.lan.example/api/v1/version"]


def test_a_whole_sync_opens_only_http_and_https_and_no_local_address_but_the_sources(tmp_path):
    """A forge on the local network, whose project names a file, an ftp address, and images on this
    computer and on other hosts of the network: the Sync fetches the forge's own, and none of those."""
    (tmp_path / "private.png").write_bytes(PNG)
    private = (tmp_path / "private.png").as_uri()
    web, api = "https://git.lan.example/", "https://git.lan.example/api/v1/repos/o/r"
    raw = web + "o/r/raw/branch/main/"
    metainfo = METAINFO.replace("https://evil.example/icon.png", private).replace(
        "http://evil.example/shot.png", "http://nas.lan.example/shot.png")
    readme = ("# R\n\n![shot](http://192.168.1.7/screenshot.png)\n\n![shot](http://localhost:631/screenshot2.png)\n\n"
              "![window](docs/window.png)\n")
    seen = []
    http = names(Http({"git.lan.example": "SECRET"}, opener=recording({
        web + "api/v1/version": {"version": "1.22.0"},
        api + "/releases": [{"tag_name": "v1.0.0", "name": "1.0", "published_at": "2026-05-02T00:00:00Z", "assets": []}],
        api + "/git/trees/main": {"tree": [{"path": p, "type": "blob"} for p in (
            "README.md", "data/org.example.r.metainfo.xml", "docs/window.png")]},
        api: {"name": "r", "full_name": "o/r", "default_branch": "main", "avatar_url": "ftp://nas.lan.example/avatar.png"},
        raw + "README.md": readme.encode(),
        raw + "data/org.example.r.metainfo.xml": metainfo.encode(),
        raw + "docs/window.png": PNG,
        private: PNG, "ftp://": PNG, "http://": PNG,            # each would answer, if it were asked
    }, seen)), {"git.lan.example": ["192.168.1.5"], "nas.lan.example": ["192.168.1.9"], "localhost": ["127.0.0.1"]})
    db = DB(str(tmp_path / "a.db"))
    sync.sync_app(db, http, "https://git.lan.example/o/r", root=str(tmp_path / "data"))
    app = db.one("SELECT * FROM apps WHERE url=?", ("https://git.lan.example/o/r",))
    assert app["error_code"] is None and app["forge"] == "gitea" and app["readme"].startswith("# R")
    assert app["icon"] == "" and app["hero"].endswith("hero.png")      # no icon: each one it names is refused
    assert [u for u, _ in seen if not u.startswith(web)] == []
    assert raw + "docs/window.png" in [u for u, _ in seen]


def test_a_redirect_to_a_local_address_is_refused(pair):
    # server A is the host asked, so it may be local; B is another name for this computer
    a, b = pair
    a.redirects["/x"] = f"http://{b.at}/admin"
    a.redirects["/y"] = f"https://{b.at}/admin"
    for path in ("/x", "/y"):
        with pytest.raises(Unreachable, match="localhost"):
            Http(timeout=10).json(f"https://{a.at}{path}")
    assert b.seen == []
    a.redirects["/z"] = "/elsewhere"                 # on the host itself, as before
    assert Http(timeout=10).json(f"https://{a.at}/z") == {"ok": True}


@pytest.mark.parametrize("to, says", [("ftp://127.0.0.1:1/x", "isn't an http or https address"),    # urllib would follow it
                                      ("file:///etc/hostname", "HTTP 302")])                      # urllib's own refusal
def test_a_redirect_to_anything_but_http_and_https_is_refused(pair, to, says):
    a, b = pair
    a.redirects["/x"] = to
    with pytest.raises(Unreachable, match=says):
        Http(timeout=10).json(f"https://{a.at}/x")


# ---------------------------------------------------------------- the form a token is sent in (R9.2.2, R2.6.5)
# CR1's #275: Http chose the token's header from the host's name, so a GitLab without "gitlab" in its
# name (three of the hosts forges.KNOWN lists) was sent "Authorization: token", which GitLab has no use
# for: the token did nothing, and nothing said so. No test looked at a header's form, and every host
# in the tests had its forge in its name. The class is "what a host runs is read from what it is
# called", so the hosts here have names that say nothing or say the wrong thing, and the stand-in
# forge answers only the form its type takes.
NEUTRAL = "git.example.org"
FORMS = {"github": ("authorization", "Bearer SECRET"), "ghe": ("authorization", "Bearer SECRET"),
         "gitlab": ("private-token", "SECRET"),
         "forgejo": ("authorization", "token SECRET"), "gitea": ("authorization", "token SECRET")}


def tokens_sent(seen):
    """Of each request, the token headers it carried: [(address, {header: value})]."""
    return [(url, {k: v for k, v in h.items() if k in http_.TOKEN_HEADERS}) for url, h in seen]


def test_every_forge_type_has_its_form_and_a_redirect_knows_each_header():
    assert set(http_.TOKEN_FORMS) == set(forges.LABELS) == set(FORMS)
    assert {header.lower() for header, _ in http_.TOKEN_FORMS.values()} == set(http_.TOKEN_HEADERS)
    assert {kind: (header.lower(), before + "SECRET") for kind, (header, before) in http_.TOKEN_FORMS.items()} == FORMS


@pytest.mark.parametrize("host", [NEUTRAL, "gitlab.example.org", "notgithub.com", "code.gitea.example"])
@pytest.mark.parametrize("kind", sorted(FORMS))
def test_a_forges_requests_carry_the_token_in_its_types_form_whatever_the_host_is_called(tmp_path, kind, host):
    seen = []
    http = names(Http({host: "SECRET"}, opener=recording({f"https://{host}/": PNG}, seen)))
    f = forges.forge_for(http, urls.parse(f"https://{host}/o/r"), kind)
    with pytest.raises(Unreachable, match="JSON"):
        f.info()                                                     # its API
    assert f.raw("icon.png", "main") == PNG                          # a file of the repository
    sync._save_image(http, f.raw_url("icon.png", "main"), str(tmp_path / "icon"), token_host=host)   # and as Sync asks
    assert len(seen) == 3 and [sent for _, sent in tokens_sent(seen)] == [dict([FORMS[kind]])] * 3, seen


@pytest.mark.parametrize("host", sorted(forges.KNOWN))
def test_every_host_appkata_knows_gets_the_form_of_the_forge_it_runs(host):
    # the finding's three: invent.kde.org, salsa.debian.org and framagit.org are GitLab's
    seen = []
    http = names(Http({host: "SECRET"}, opener=recording({"https://": PNG}, seen)))
    forges.forge_for(http, urls.parse(f"https://{host}/o/r")).raw("README.md", "main")
    assert tokens_sent(seen) == [(seen[0][0], dict([FORMS[forges.KNOWN[host]]]))]
    assert {h: forges.KNOWN[h] for h in ("invent.kde.org", "salsa.debian.org", "framagit.org")} == {
        "invent.kde.org": "gitlab", "salsa.debian.org": "gitlab", "framagit.org": "gitlab"}


def only_its_form(kind, routes, seen):
    """A forge of this type that needs its token: recording(), which answers 401 unless the request
    carries the token in the one form the type takes. (A real GitLab or Gitea takes Bearer too.)"""
    answer = recording(routes, seen)

    def open_(req, timeout=0):
        sent = {k.lower(): v for k, v in req.header_items() if k.lower() in http_.TOKEN_HEADERS}
        if sent != dict([FORMS[kind]]):
            seen.append((req.full_url, sent))
            raise urllib.error.HTTPError(req.full_url, 401, "Unauthorized", {}, None)
        return answer(req, timeout)
    return open_


PROJECT = {"name": "r", "full_name": "o/r", "path_with_namespace": "o/r", "default_branch": "main"}


@pytest.mark.parametrize("kind, probe, answer", [
    ("gitlab", "/api/v4/projects?per_page=1", []),
    ("ghe", "/api/v3/meta", {"installed_version": "3.14.0"}),
    ("gitea", "/api/v1/version", {"version": "1.22.0"}),
    ("forgejo", "/api/v1/version", {"version": "11.0.1+gitea-1.22.0"}),
])
@pytest.mark.parametrize("host", [NEUTRAL, "gitlab-mirror.example.org"])
def test_a_forge_that_needs_its_token_is_detected_and_read_on_a_host_whose_name_says_nothing(tmp_path, host, kind, probe, answer):
    """From the first probe to an image, as Sync goes: a host whose type nothing says yet, which
    answers only its own form. Each probe asks in the form of the forge whose API it asks for."""
    seen = []
    web = f"https://{host}"
    http = names(Http({host: "SECRET"}, opener=only_its_form(kind, {
        web + probe: answer, web + "/api/": PROJECT, web + "/o/r/": PNG}, seen)))
    repo = urls.parse(web + "/o/r")
    assert forges.detect(http, host) == kind
    f = forges.forge_for(http, repo, kind)
    assert f.info().name == "r" and f.raw("icon.png", "main") == PNG
    assert sync._save_image(http, f.raw_url("icon.png", "main"), str(tmp_path / "icon"), token_host=host).endswith("icon.png")
    assert all(url.startswith(web + "/") and len(sent) == 1 for url, sent in tokens_sent(seen)), seen


@pytest.mark.parametrize("host, value", [
    ("github.com", "Bearer SECRET"), ("api.github.com", "Bearer SECRET"),
    ("notgithub.com", "token SECRET"),                       # ends in the same letters: not GitHub's form
    ("github.com.evil.example", "token SECRET"), ("api.github.evil.example", "token SECRET"),
    (NEUTRAL, "token SECRET"),
])
def test_with_no_forge_type_known_only_github_coms_own_names_get_its_form(host, value):
    seen = []
    _ask(names(Http({host: "SECRET"}, opener=recording({}, seen))), f"https://{host}/x")
    assert tokens_sent(seen) == [(f"https://{host}/x", {"authorization": value})]


def test_a_search_sends_the_token_in_the_form_of_the_forge_it_searches():
    seen = []
    http = names(Http({"invent.kde.org": "SECRET", "gitlab-mirror.example.org": "SECRET", "github.com": "SECRET"},
                      opener=recording({"https://invent.kde.org/": [], "https://gitlab-mirror.example.org/": {"data": []},
                                        "https://api.github.com/": {"items": []}}, seen)))
    assert explore.gitlab(http, "q", host="invent.kde.org") == []
    assert explore.codeberg(http, "q", host="gitlab-mirror.example.org") == []
    assert explore.github(http, "q") == []
    assert [sent for _, sent in tokens_sent(seen)] == [dict([FORMS["gitlab"]]), dict([FORMS["forgejo"]]), dict([FORMS["github"]])]


# ---------------------------------------------------------------- which host a token is kept for (R9.2.2, R11.1.6)
# CR1's #297: two notions of a host met. A Source's host carries its port (urls.parse) and the forges
# named it so, while Http looked a token up by the address's name alone: a token kept for a forge on
# a port was sent by some calls and not by others, and one kept for a name went to every port of it.
# The owner's decision: a token belongs to one address; a name alone means the default port. The
# hosts in the tests had no ports, so the two notions never differed. The class is "one fact, two
# spellings", so the tests hold every call a Source makes to the Source's host as urls.parse writes it.
LAN = "git.lan.example"


@pytest.mark.parametrize("kept, url, token_host, sent", [
    # kept for the forge on its port: its calls (which name the Source's host) and the probes (which don't)
    (LAN + ":3000", f"https://{LAN}:3000/api/v1/repos/o/r", LAN + ":3000", True),
    (LAN + ":3000", f"https://{LAN}:3000/api/v1/version", None, True),
    (LAN + ":3000", f"https://{LAN}/api/v1/version", None, False),              # the default port: another address
    (LAN + ":3000", f"https://{LAN}:9999/other-service", None, False),
    (LAN + ":3000", f"https://{LAN}:9999/other-service", LAN + ":3000", False),
    (LAN + ":3000", f"https://{LAN}/o/r/raw/branch/main/icon.png", LAN + ":3000", False),
    (LAN + ":3000", f"http://{LAN}:3000/api/v1/version", None, False),          # plain http: never
    # kept for the name alone: the default port only
    (LAN, f"https://{LAN}/api/v1/repos/o/r", LAN, True),
    (LAN, f"https://{LAN}/api/v1/version", None, True),
    (LAN, f"https://{LAN}:443/api/v1/version", None, True),                     # the default port, written out
    (LAN, f"https://{LAN}:3000/api/v1/version", None, False),
    (LAN, f"https://{LAN}:3000/api/v1/repos/o/r", LAN + ":3000", False),
    (LAN, f"https://{LAN}:3000/api/v1/repos/o/r", LAN, False),
    (LAN, f"https://{LAN}:9999/other-service", LAN, False),
    (LAN, f"https://{LAN}:80/x", None, False),                                  # https on http's port isn't the default
    (LAN + ":443", f"https://{LAN}/api/v1/version", None, True),                # however the default port was typed
    # a named host is asked on its default port too
    ("github.com", "https://api.github.com/repos/o/r", "github.com", True),
    ("github.com", "https://api.github.com:8443/repos/o/r", "github.com", False),
    ("github.com", "https://raw.githubusercontent.com:8443/o/r/main/icon.png", "github.com", False),
    ("github.com:8443", "https://api.github.com/repos/o/r", "github.com:8443", False),
])
def test_a_token_is_sent_to_the_one_address_it_is_kept_for(kept, url, token_host, sent):
    seen = []
    http = names(Http({kept: "SECRET"}, opener=recording({}, seen)))
    _ask(http, url, **({"token_host": token_host} if token_host else {}))
    assert [u for u, _ in seen] == [url] and tokened(seen) == ([url] if sent else []), seen


@pytest.mark.parametrize("source, host", [
    (f"https://{LAN}/o/r", LAN), (f"https://{LAN}:443/o/r", LAN), (f"http://{LAN}/o/r", LAN),
    (f"https://{LAN}:3000/o/r", LAN + ":3000"), (f"http://{LAN}:3000/o/r.git", LAN + ":3000"),
    (f"https://{LAN.upper()}:8443/o/r/releases", LAN + ":8443"),
])
@pytest.mark.parametrize("kind", ["gitlab", "forgejo", "ghe"])
def test_every_call_for_a_source_finds_the_token_kept_for_the_sources_host(tmp_path, source, host, kind):
    """The token is kept under the host as the Source shows it (urls.parse), and another port of the
    same name has a token of its own. From the probes to an image, every request for the Source
    carries the Source's, and none carries the other."""
    repo = urls.parse(source)
    other = LAN + ":9999" if repo.host == LAN else LAN
    assert repo.host == host == http_.token_key(host)
    seen = []
    web = f"https://{host}"
    http = names(Http({host: "SECRET", other: "OTHER"}, opener=recording({web + "/api/": PROJECT, web + "/": PNG}, seen)))
    with pytest.raises(SourceError):
        forges.detect(http, repo.host)                    # the four probes: nothing here says what it runs
    f = forges.forge_for(http, repo, kind)
    assert f.info().name == "r" and f.raw("icon.png", "main") == PNG
    assert sync._save_image(http, f.raw_url("icon.png", "main"), str(tmp_path / "icon"), token_host=repo.host).endswith("icon.png")
    assert len(seen) == 7 and all(url.startswith(web + "/") for url, _ in seen), seen
    sent = [value for _, headers in tokens_sent(seen) for value in headers.values()]
    assert len(sent) == 7 and all("SECRET" in value for value in sent), seen
    _ask(http, f"https://{other}/elsewhere", token_host=repo.host)       # an address on the other port, asked for the Source
    assert tokens_sent(seen)[-1] == (f"https://{other}/elsewhere", {})


@pytest.mark.parametrize("typed, key", [
    ("github.com", "github.com"), ("  GitHub.com ", "github.com"),
    ("git.example.org:3000", "git.example.org:3000"), ("Git.Example.Org:3000", "git.example.org:3000"),
    ("git.example.org:443", "git.example.org"),                       # the default port, typed out
    ("https://git.example.org:3000/o/r", "git.example.org:3000"),     # a whole address, pasted
    ("https://git.example.org/", "git.example.org"), ("git.example.org/o/r", "git.example.org"),
    ("[::1]:3000", "[::1]:3000"), ("192.168.1.5:3000", "192.168.1.5:3000"),
    ("git.example.org:port", "git.example.org:port"),                 # no address: kept as typed
])
def test_what_is_typed_for_a_tokens_host_is_kept_as_a_sources_host_is_written(typed, key):
    assert http_.token_key(typed) == key == http_.token_key(key)
    seen = []
    http = names(Http({typed: "SECRET"}, opener=recording({}, seen)))
    assert list(http.tokens) == [key]
    if ":port" not in key:
        _ask(http, f"https://{key}/x")
        assert tokened(seen) == [f"https://{key}/x"]


@pytest.mark.parametrize("source_host, url, fetched", [
    (LAN + ":3000", f"https://{LAN}:3000/o/r/raw/branch/main/shot.png", True),
    (LAN + ":3000", f"http://{LAN}:3000/o/r/raw/branch/main/shot.png", True),      # the same port, in plain http
    (LAN + ":3000", f"https://{LAN}:9999/admin/shot.png", False),                  # whatever else listens on that machine
    (LAN + ":3000", f"https://{LAN}/shot.png", False),
    (LAN, f"https://{LAN}/o/r/raw/branch/main/shot.png", True),
    (LAN, f"http://{LAN}/o/r/raw/branch/main/shot.png", True),                     # http's own port, as the Source's host is written
    (LAN, f"http://{LAN}:631/admin/shot.png", False),
    (LAN, f"https://{LAN}:9999/admin/shot.png", False),
])
def test_on_a_local_forge_only_the_sources_own_address_may_be_local(tmp_path, source_host, url, fetched):
    # CR1 #266's exception is for the Source's own host, and a host is one address (#297)
    seen = []
    http = names(Http({source_host: "SECRET"}, opener=recording({url: PNG}, seen)), {LAN: ["192.168.1.5"]})
    if fetched:
        assert sync._save_image(http, url, str(tmp_path / "hero"), token_host=source_host).endswith("hero.png")
    else:
        with pytest.raises(Unreachable, match="local network"):
            sync._save_image(http, url, str(tmp_path / "hero"), token_host=source_host)
    assert [u for u, _ in seen] == ([url] if fetched else [])


def test_r11_1_6_r9_2_2_and_settings_say_which_host_a_token_is_kept_for():
    """The finding's last part: Settings' host field took any text and nothing said which key was
    meant. The requirement, the field and its help text say it, and the example they give is a key."""
    r11, r9 = " ".join(reqdocs.item("R11.1.6").split()), " ".join(reqdocs.item("R9.2.2").split())
    assert "A token belongs to one address" in r11 and "a name alone means the default port" in r11
    assert "A host is one address" in r9 and "a name alone means the default port" in r9
    assert "nor to another port of its own" in r9
    with open(os.path.join(reqdocs.ROOT, "src", "appkata", "qml", "SettingsDialog.qml"), encoding="utf-8") as f:
        qml = f.read()
    assert 'placeholder: "host or host:port"' in qml and '"host or host:port"' in r11
    example = "git.example.org:3000"
    assert f"`{example}`" in r11 and f"({example})" in qml and http_.token_key(example) == example
    assert "a host alone means the default port" in qml


# ---------------------------------------------------------------- R9.2.2, held whole (CR1 #292)
# CR1's #292: no test built an Http with a token and looked at what was sent where, so #263, #264,
# #275 and #297 all passed the suite, and so would a regression of any of their fixes. Each of those
# has its own tests above, written against its own fault. These hold the requirement instead: the
# rule is written once more here, from R9.2.2's and R11.1.6's words and apart from Http (no name of
# Http's own is used below), and every request of three whole Syncs and three searches is held to it,
# whichever line of the application asked. A redirect needs Http's own opener, so the last test goes
# through real sockets.
CARRIES = ("authorization", "private-token")
NAMED = {"github.com": ("api.github.com", "raw.githubusercontent.com")}       # R9.2.2's list
KEPT = {"github.com": ("github", "ghp_GITHUB"), "git.example.org": ("gitlab", "glpat_NEUTRAL"),
        "code.example.net:3000": ("forgejo", "FORGEJO-ON-ITS-PORT"), "code.example.net": ("forgejo", "FORGEJO-DEFAULT-PORT"),
        "gitlab.com": ("gitlab", "glpat_COM"), "codeberg.org": ("forgejo", "CODEBERG"), "evil.example": ("forgejo", "EVIL")}
TAKES = {"github": "authorization: Bearer {}", "gitlab": "private-token: {}", "forgejo": "authorization: token {}"}


def may_carry(url):
    """R9.2.2: the hosts whose token a request to this address may carry. Over https only; a host is
    one address, its name and its port, and a name alone is the default port; github.com's goes to
    its two named hosts as well."""
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https":
        return set()
    host = parts.hostname if parts.port in (None, 443) else f"{parts.hostname}:{parts.port}"
    return {host} | {kept for kept, named in NAMED.items() if host in named}


def probe(url):
    """An address forges.detect asks to find out what a host runs: the three APIs and the home page."""
    parts = urllib.parse.urlsplit(url)
    return parts.path == "/" or url.endswith(("/api/v1/version", "/api/v4/projects?per_page=1", "/api/v3/meta"))


def breaks_r9_2_2(seen):
    """Each request that carried what R9.2.2 doesn't let it: a token of a host the address isn't,
    one over plain http, two at once, or one in a form its forge doesn't take. A probe asks before
    anything says what the host runs, so it may carry the host's token in any forge's form."""
    out = []
    for url, headers in seen:
        sent = [f"{k}: {v}" for k, v in headers.items() if k in CARRIES]
        allowed = [form.format(token) for host, (kind, token) in KEPT.items() if host in may_carry(url)
                   for form in ([TAKES[kind]] if not probe(url) else TAKES.values())]
        if sent and (len(sent) > 1 or sent[0] not in allowed):
            out.append((url, sent))
    return out


def project(hostile):
    """A project's files that name four addresses elsewhere, as its icon, its screenshot and two README
    images, and one image of its own."""
    metainfo = METAINFO.replace("https://evil.example/icon.png", hostile[0]).replace("http://evil.example/shot.png", hostile[1])
    readme = f"# R\n\n![shot]({hostile[2]})\n\n![shot]({hostile[3]})\n\n![window](docs/shot-window.png)\n"
    return {"README.md": readme.encode(), "data/org.example.r.metainfo.xml": metainfo.encode(), "docs/shot-window.png": PNG}


ELSEWHERE = {
    "https://github.com/o/r": ["https://evil.example/icon.png", "http://raw.githubusercontent.com/o/r/main/shot.png",
                               "https://notgithub.com/o/r/shot.png", "https://raw.githubusercontent.com:8443/o/r/main/shot.png"],
    "https://git.example.org/o/r": ["http://git.example.org/o/r/-/raw/main/icon.png", "https://git.example.org:8443/shot.png",
                                    "https://git.example.org.evil.example/shot.png", "https://gitlab.com/o/r/-/raw/main/shot.png"],
    "https://code.example.net:3000/o/r": ["https://code.example.net/shot-on-the-default-port.png", "https://code.example.net:9999/shot.png",
                                          "http://code.example.net:3000/o/r/raw/branch/main/shot.png", "https://evil.example:3000/shot.png"],
}
OWN = {      # each Source's own addresses: every request to them carries its token
    "https://github.com/o/r": ("https://api.github.com/", "https://raw.githubusercontent.com/"),
    "https://git.example.org/o/r": ("https://git.example.org/",),
    "https://code.example.net:3000/o/r": ("https://code.example.net:3000/",),
}


def three_forges():
    """github.com, a GitLab whose name says nothing and a Forgejo on a port, each with a project that
    names images elsewhere; and the three searches."""
    release = {"tag_name": "v1.0.0", "name": "1.0", "published_at": "2026-05-02T00:00:00Z", "released_at": "2026-05-02T00:00:00Z", "assets": []}
    blobs = [{"path": p, "type": "blob"} for p in project([""] * 4)]
    info = {"name": "r", "full_name": "o/r", "path_with_namespace": "o/r", "default_branch": "main"}
    routes = {"https://gitlab.com/api/v4/projects?search=": [], "https://codeberg.org/api/v1/repos/search": {"data": []},
              "https://api.github.com/search/": {"items": []}}
    for api, raw, tree, listing, avatar in (
            ("https://api.github.com/repos/o/r", "https://raw.githubusercontent.com/o/r/main/", "/git/trees/main", {"tree": blobs},
             {"owner": {"avatar_url": "https://avatars.githubusercontent.com/u/1"}}),
            ("https://git.example.org/api/v4/projects/o%2Fr", "https://git.example.org/o/r/-/raw/main/", "/repository/tree", blobs,
             {"avatar_url": "https://git.example.org/uploads/avatar.png"}),
            ("https://code.example.net:3000/api/v1/repos/o/r", "https://code.example.net:3000/o/r/raw/branch/main/", "/git/trees/main",
             {"tree": blobs}, {"avatar_url": "https://code.example.net:3000/avatars/1"})):
        source = next(s for s in ELSEWHERE if raw.startswith(OWN[s]))
        routes.update({api: {**info, **avatar}, api + "/releases": [release], api + tree: listing,
                       (avatar.get("owner") or avatar)["avatar_url"]: PNG})
        routes.update({raw + path: body for path, body in project(ELSEWHERE[source]).items()})
    routes["https://git.example.org/api/v4/projects?per_page=1"] = []                      # the probes that answer
    routes["https://code.example.net:3000/api/v1/version"] = {"version": "11.0.1+gitea-1.22.0"}
    return dict(sorted(routes.items(), key=lambda kv: -len(kv[0])))         # opener() takes the first prefix: the longest first


def test_every_request_of_three_syncs_and_three_searches_keeps_r9_2_2(tmp_path):
    seen = []
    http = names(Http({host: token for host, (_, token) in KEPT.items()}, opener=recording(three_forges(), seen)))
    db = DB(str(tmp_path / "a.db"))
    for source, kind in zip(ELSEWHERE, ("github", "gitlab", "forgejo")):
        sync.sync_app(db, http, source, root=str(tmp_path))
        app = db.one("SELECT * FROM apps WHERE url=?", (source,))
        assert app["error_code"] is None and app["forge"] == kind, (source, app["error"])
        assert app["icon"].endswith("icon.png") and app["hero"].endswith("hero.png")
    for service in ("gitlab", "codeberg", "github"):
        assert explore.search(http, service, "q") == {"matches": [], "error": ""}
    asked = [url for url, _ in seen]
    assert [u for urls_ in ELSEWHERE.values() for u in urls_ if u not in asked] == []        # each was asked for
    assert breaks_r9_2_2(seen) == []
    # and the rule isn't kept by sending nothing: every request to a Source's own addresses, and every
    # search, carried that host's token in its forge's form, and no request elsewhere carried any
    for source, own in OWN.items():
        kind, token = KEPT[urls.parse(source).host]
        mine = [[f"{k}: {v}" for k, v in h.items() if k in CARRIES] for url, h in seen if url.startswith(own) and not probe(url)]
        assert len(mine) >= 7 and all(sent == [TAKES[kind].format(token)] for sent in mine), (source, mine)
        probes = [[v for k, v in h.items() if k in CARRIES] for url, h in seen if url.startswith(own) and probe(url)]
        assert all(len(sent) == 1 and sent[0].endswith(token) for sent in probes), (source, probes)
    for url, h in seen:
        if "search" in url:
            kind, token = KEPT[may_carry(url).intersection(KEPT).pop()]
            assert [f"{k}: {v}" for k, v in h.items() if k in CARRIES] == [TAKES[kind].format(token)], url
    assert [url for url, h in seen if set(h) & set(CARRIES) and url in sum(ELSEWHERE.values(), [])] == []


def test_the_harness_itself_sees_each_way_r9_2_2_is_broken():
    # the rule above, tried on requests that break it: a check that passes whatever it is shown holds nothing
    wrong = [("https://evil.example/shot.png", {"authorization": "Bearer ghp_GITHUB"}),            # another host
             ("https://notgithub.com/o/r", {"authorization": "Bearer ghp_GITHUB"}),                # ends in the same letters
             ("http://api.github.com/repos/o/r", {"authorization": "Bearer ghp_GITHUB"}),          # plain http
             ("https://api.github.com:8443/repos/o/r", {"authorization": "Bearer ghp_GITHUB"}),    # a named host, another port
             ("https://code.example.net/x", {"authorization": "token FORGEJO-ON-ITS-PORT"}),       # another port of its own name
             ("https://code.example.net:9999/x", {"authorization": "token FORGEJO-DEFAULT-PORT"}),
             ("https://git.example.org/api/v4/x", {"authorization": "token glpat_NEUTRAL"}),       # a form GitLab doesn't take
             ("https://evil.example/api/v1/version", {"authorization": "token glpat_NEUTRAL"}),    # a probe, with another host's
             ("https://api.github.com/x", {"authorization": "Bearer ghp_GITHUB", "private-token": "ghp_GITHUB"})]
    right = [("https://api.github.com/repos/o/r", {"authorization": "Bearer ghp_GITHUB", "accept": "x"}),
             ("https://raw.githubusercontent.com:443/o/r/main/x", {"authorization": "Bearer ghp_GITHUB"}),
             ("https://git.example.org/api/v4/x", {"private-token": "glpat_NEUTRAL"}),
             ("https://code.example.net:3000/x", {"authorization": "token FORGEJO-ON-ITS-PORT"}),
             ("https://code.example.net/x", {"authorization": "token FORGEJO-DEFAULT-PORT"}),
             ("https://git.example.org/api/v1/version", {"authorization": "token glpat_NEUTRAL"}),     # a probe: any form
             ("http://evil.example/shot.png", {"accept": "*/*"})]
    assert [url for url, _ in breaks_r9_2_2(wrong + right)] == [url for url, _ in wrong]


@pytest.mark.parametrize("kind", ["gitlab", "forgejo", "ghe"])
def test_through_real_sockets_a_forges_token_reaches_its_own_address_alone(pair, kind):
    """Http's own opener, a forge on a port, and its redirects: a file that is kept on another host, an
    API address that moved on its own, and one that points at plain http."""
    a, b = pair
    repo = urls.parse(f"https://{a.at}/o/r")
    http = names(Http({a.at: "SECRET-TOKEN", "127.0.0.1": "ITS-DEFAULT-PORT", b.at: "ANOTHER-HOSTS"}, timeout=10))
    f = forges.forge_for(http, repo, kind)
    raw, api = urllib.parse.urlsplit(f.raw_url("big.bin", "main")).path, urllib.parse.urlsplit(f.base).path
    a.redirects[raw] = f"https://{b.at}/storage/big.bin"
    a.redirects[api] = api + "-renamed"
    a.redirects[api + "/releases"] = f"http://{a.at}{api}/releases"
    assert f.raw("big.bin", "main") == b'{"ok": true}' and f._get(f.base) == {"ok": True}
    with pytest.raises(Unreachable, match="plain http"):
        f._get(f.base + "/releases")
    form = TAKES["github" if kind == "ghe" else kind].format("SECRET-TOKEN")
    assert [(path, [f"{k}: {v}" for k, v in h.items() if k in CARRIES]) for path, h in a.seen] == [
        (raw, [form]), (api, [form]), (api + "-renamed", [form]), (api + "/releases", [form])]
    assert [(path, [k for k in h if k in CARRIES]) for path, h in b.seen] == [("/storage/big.bin", [])]


# ---------------------------------------------------------------- what a Sync didn't expect (R9.2, R2.10)
# CR1's #269: Http promised typed errors and mapped urllib's OSErrors alone, and a Sync recorded on
# an app's row only a SourceError: anything else, such as http.client's own errors for an address it
# can't send or an answer cut short, a forge's answer of another shape, or git missing, left the
# worker and ended the whole Sync, with the apps still queued dropped and no time of the last Sync
# kept. How it slipped past: no test called sync_all, every stand-in opener raised only an HTTPError,
# and every stand-in forge answered as its documentation says. The class is "something a Sync didn't
# expect ends it", so it is held at each of its layers: whatever opening or reading an address ends
# in, Http gives a SourceError; whatever one app's sync ends in, wherever, the Sync goes on, that
# app's row says so and every other app is stored.
class Clock:
    """Http's clock and its waits: a wait is noted and moves the time on, and nothing waits."""

    def __init__(self):
        self.now, self.waits = time.time(), []

    def time(self):
        return self.now

    monotonic = time

    def sleep(self, seconds):
        self.waits.append(seconds)
        self.now += seconds


@pytest.fixture
def clock(monkeypatch):
    monkeypatch.setattr(http_, "time", Clock())
    return http_.time


class Broken(FakeResponse):
    """An answer whose body can't be read."""

    def __init__(self, url, error):
        super().__init__(url, b"")
        self.error = error

    def read(self, *a):
        raise self.error

    read1 = read


def ending_in(error, when, seen=None):
    """An opener whose every request ends in `error`: when the address is opened, or when its answer is read."""
    def open_(req, timeout=0):
        seen is not None and seen.append(req.full_url)
        if when == "opened":
            raise error
        return Broken(req.full_url, error)
    return open_


ENDS_IN = [InvalidURL("URL can't contain control characters. '/a b.png' (found at least ' ')"),       # http.client's own
           UnicodeEncodeError("ascii", "/ä.png", 1, 2, "ordinal not in range(128)"),
           ValueError("Invalid header value b'x\\n'"), BadStatusLine("\x16\x03\x01"), LineTooLong("header line"),
           IncompleteRead(b"half", 96),
           ssl.SSLError(1, "[SSL: WRONG_VERSION_NUMBER] wrong version number"),                         # and what was mapped already
           ConnectionResetError(104, "Connection reset by peer"), TimeoutError("timed out"),
           urllib.error.URLError(OSError(111, "Connection refused"))]


@pytest.mark.parametrize("error", ENDS_IN, ids=lambda e: type(e).__name__)
@pytest.mark.parametrize("when", ["opened", "read"])
@pytest.mark.parametrize("call", ["bytes", "text", "json", "json_with_headers", "request"])
def test_whatever_opening_or_reading_an_address_ends_in_http_gives_a_source_error(clock, error, when, call):
    http = names(Http(opener=ending_in(error, when)))
    with pytest.raises(Unreachable) as e:
        getattr(http, call)("https://git.example.org/api/x")
    assert "git.example.org" in str(e.value) and json.dumps(e.value.extra)        # a Sync writes both on the row


def test_an_answer_cut_short_is_asked_for_again(clock):
    seen = []
    http = names(Http(opener=ending_in(IncompleteRead(b"half", 96), "read", seen)))
    with pytest.raises(Unreachable, match="git.example.org cut its answer short"):
        http.bytes("https://git.example.org/api/x")
    assert len(seen) == 3 and clock.waits == [1.5, 3.0]
    seen.clear()                                             # an address that can't be sent isn't: it never can be
    http._open = ending_in(InvalidURL("URL can't contain control characters"), "opened", seen)
    with pytest.raises(Unreachable):
        http.bytes("https://git.example.org/a b.png")
    assert len(seen) == 1


def half_a_chunk(handler):
    handler.wfile.write(b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n64\r\nhalf of the first chunk")


@pytest.mark.parametrize("path", ["/a b.png", "/ä.png", "/截图.png", "/a\tb.png"])
def test_through_real_sockets_an_address_that_cant_be_sent_and_an_answer_cut_short_are_unreachable(pair, clock, tmp_path, path):
    # the finding's own runs, with Http's own opener: http.client refuses the address before it connects
    a, b = pair
    a.files = {"/cut.png": half_a_chunk}
    http = Http(timeout=10)
    with pytest.raises(Unreachable, match="127.0.0.1"):
        sync._save_image(http, f"https://{a.at}{path}", str(tmp_path / "hero"), token_host=a.at)
    assert a.seen == [] and clock.waits == []
    with pytest.raises(Unreachable, match="cut its answer short"):
        sync._save_image(http, f"https://{a.at}/cut.png", str(tmp_path / "hero"), token_host=a.at)
    assert [p for p, _ in a.seen] == ["/cut.png"] * 3 and list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("url, at", [
    ("a b.png", "/a%20b.png"), ("docs/screen shot.png", "/docs/screen%20shot.png"),
    ("docs/截图.png", "/docs/%E6%88%AA%E5%9B%BE.png"), ("../img/ä \"1\".png", "/img/%C3%A4%20%221%22.png"),
    ("docs/screen%20shot.png", "/docs/screen%20shot.png"),                     # written quoted: left as it is
    ("docs/shot.png?raw=true", "/docs/shot.png?raw=true"), ("/docs/shot.png#gh-dark-mode-only", "/docs/shot.png#gh-dark-mode-only"),
    ("docs/a+b_(1)~x.png", "/docs/a+b_(1)~x.png"),
])
def test_a_readme_images_own_path_is_written_as_an_address_can_be_sent(url, at):
    base = "https://raw.githubusercontent.com/o/r/main"
    assert metadata.resolve(url, base, "docs" if url.startswith("..") else "") == base + at
    http = names(Http(opener=opener({base + at: PNG})))
    assert http.bytes(metadata.resolve(url, base, "docs" if url.startswith("..") else "")) == PNG


@pytest.mark.parametrize("error", [FileNotFoundError(2, "No such file or directory: 'git'"), PermissionError(13, "Permission denied"),
                                   subprocess.TimeoutExpired(["git"], 120)], ids=lambda e: type(e).__name__)
def test_git_missing_or_too_slow_is_no_answer_from_it(monkeypatch, error):
    def run(*a, **k):
        raise error
    monkeypatch.setattr(forges._sp, "run", run)
    assert forges._git_out(["ls-remote", "--tags", "--refs", "https://github.com/o/r"]) == ""
    # and so the pages' way to a project's tags and files, which is what asks git, has none to show
    http = Http(opener=opener({"https://api.github.com/": 403}))
    http.limited["api.github.com"] = time.time() + 60
    f = forges.forge_for(http, urls.parse("https://github.com/o/r"), "github")
    assert f.web and f.tags() == [] and f.tree("main") == []


def test_with_no_git_on_the_path_there_is_no_answer_from_it(monkeypatch, tmp_path):
    monkeypatch.setenv("PATH", str(tmp_path))                # the real subprocess call, and nothing to find
    assert forges._git_out(["--version"]) == ""


# ---- a whole Sync
FORGEJO = {"https://code.example.net:3000/o/r": "https://code.example.net:3000/api/v1/repos/o/r"}
PLACES = {      # where in an app's sync: what its address ends in
    "info": ("/repos/o/r", "/projects/o%2Fr"), "releases": ("/releases",), "files": ("/git/trees/main", "/repository/tree"),
    "readme": ("/README.md",), "metainfo": (".metainfo.xml",), "image": ("/docs/shot-window.png",),
}
SHAPES = {      # what a forge can answer that its documentation doesn't say
    "info": ["a", "list"], "releases": {"message": "an object, where the releases are a list"},
    "files": [{"type": "blob"}],
}


def catalog(tmp_path, monkeypatch, sources):
    """A database with these Sources, and no package channels of this machine's to read."""
    monkeypatch.setattr(channels, "enabled", lambda: False)
    db = DB(str(tmp_path / "a.db"))
    for url in sources:
        db.x("INSERT INTO sources(url, settings, added_at) VALUES(?,?,?)", (url, "{}", now()))
    return db


def rows(db):
    return {a["url"]: a for a in db.all("SELECT * FROM apps")}


def at(routes, source, place, answer):
    """The routes, with `answer` wherever a request of this Source's sync reaches `place`."""
    hit = [k for k in routes if k.startswith(OWN[source]) and k.endswith(PLACES[place])]
    assert hit, (source, place)
    return {k: answer if k in hit else v for k, v in routes.items()}


def synced_but(tmp_path, monkeypatch, routes, source):
    """A Sync of the three forges' Sources over these routes: it ends, the time of it is kept, every
    Source has its row, and each one but `source` is stored whole. Returns that one's row."""
    db = catalog(tmp_path, monkeypatch, ELSEWHERE)
    progress = sync.Progress()
    sync.sync_all(db, names(Http({}, opener=opener(routes))), progress, root=str(tmp_path))
    apps = rows(db)
    assert db.get("last_sync") and sorted(apps) == sorted(ELSEWHERE) and (progress.done, progress.total) == (3, 3)
    for url, app in apps.items():
        if url != source:
            assert app["error_code"] is None and app["releases"] and app["hero"].endswith("hero.png"), (url, app["error"])
    return apps[source]


@pytest.mark.parametrize("source", sorted(ELSEWHERE))
@pytest.mark.parametrize("place", sorted(PLACES))
@pytest.mark.parametrize("error", [RuntimeError("anything at all"), KeyError("name"), InvalidURL("can't contain control characters"),
                                   UnicodeEncodeError("ascii", "ä", 0, 1, "ordinal not in range(128)")],
                         ids=lambda e: type(e).__name__)
def test_whatever_one_apps_sync_ends_in_wherever_the_sync_goes_on_and_its_row_says_so(tmp_path, monkeypatch, source, place, error):
    app = synced_but(tmp_path, monkeypatch, at(three_forges(), source, place, error), source)
    if isinstance(error, (InvalidURL, UnicodeEncodeError)) and place in ("files", "metainfo", "image"):
        assert app["error_code"] is None                 # Http's own error for it, which those three pass over
    else:
        assert app["error_code"] == "Unreachable" and app["error"] and app["fetched_at"], app
        if isinstance(error, (RuntimeError, KeyError)):
            assert f"unexpected error ({type(error).__name__}" in app["error"]


@pytest.mark.parametrize("source", sorted(ELSEWHERE))
@pytest.mark.parametrize("place", sorted(SHAPES))
def test_a_forges_answer_of_another_shape_is_an_error_on_that_apps_row(tmp_path, monkeypatch, source, place):
    app = synced_but(tmp_path, monkeypatch, at(three_forges(), source, place, SHAPES[place]), source)
    assert app["error_code"] == "Unreachable" and "unexpected error (" in app["error"], app


def test_an_error_on_an_apps_row_keeps_what_the_last_sync_stored(tmp_path, monkeypatch):
    source = "https://git.example.org/o/r"
    db = catalog(tmp_path, monkeypatch, [source])
    http = names(Http({}, opener=opener(three_forges())))
    sync.sync_all(db, http, root=str(tmp_path))
    before = rows(db)[source]
    assert before["error_code"] is None and before["readme"] and before["icon"] and before["hero"]
    http._open = opener(at(three_forges(), source, "releases", SHAPES["releases"]))
    sync.sync_all(db, http, root=str(tmp_path))
    after = rows(db)[source]
    assert after["error_code"] == "Unreachable" and "unexpected error (AttributeError" in after["error"]
    kept = ("name", "readme", "releases", "icon", "hero", "forge", "summary")
    assert {k: after[k] for k in kept} == {k: before[k] for k in kept}


def test_what_sync_app_itself_lets_out_is_passed_over_and_the_rest_are_synced(tmp_path, monkeypatch, caplog):
    # what is left for sync_all: a Catalog address nothing can parse, a database that can't be written
    db = catalog(tmp_path, monkeypatch, ELSEWHERE)
    real, bad = sync.sync_app, "https://git.example.org/o/r"

    def sync_app(db_, http_, url, root=None):
        if url == bad:
            raise ValueError("URL doesn't name a repository")
        real(db_, http_, url, root)
    monkeypatch.setattr(sync, "sync_app", sync_app)
    progress, items = sync.Progress(), []
    sync.sync_all(db, names(Http({}, opener=opener(three_forges()))), progress, root=str(tmp_path), workers=1,
                  on_item=lambda: items.append(progress.done))
    assert db.get("last_sync") and sorted(rows(db)) == sorted(set(ELSEWHERE) - {bad})
    assert (progress.done, progress.total) == (3, 3) and items == [1, 2, 3]
    assert [r for r in caplog.records if r.exc_info and bad in r.getMessage()]         # with its traceback, in the app log


def forgejo_project(server, path, files, **info):
    """A project on the stand-in forge, which answers as Forgejo: its info, a release, its file list and its files."""
    api = f"/api/v1/repos/{path}"
    server.files = {**(server.files or {}), "/api/v1/version": {"version": "11.0.1+gitea-1.22.0"},
                    api: {"name": path.rsplit("/", 1)[-1], "full_name": path, "default_branch": "main", **info},
                    api + "/releases": [{"tag_name": "v1.0.0", "name": "1.0", "published_at": "2026-05-02T00:00:00Z", "assets": []}],
                    api + "/git/trees/main": {"tree": [{"path": p, "type": "blob"} for p in files]},
                    **{f"/{path}/raw/branch/main/{urllib.parse.quote(p)}": body for p, body in files.items()}}
    return f"https://{server.at}/{path}"


def test_through_real_sockets_a_readme_image_that_cant_be_sent_as_written_doesnt_end_the_sync(pair, tmp_path, monkeypatch, clock):
    """The finding's case, with Http's own opener: a README names its images as its author wrote them,
    with a space and with letters outside ASCII. The Sync ends, both apps are stored, and the image
    is asked for as an address can be sent."""
    a, b = pair
    spaced = forgejo_project(a, "o/spaced", {"README.md": b'# Spaced\n\n<img src="a b.png">\n', "a b.png": PNG})
    other = forgejo_project(a, "o/other", {"README.md": "# Other\n\n![shot](docs/截图.png)\n".encode(), "docs/截图.png": PNG})
    db = catalog(tmp_path, monkeypatch, [spaced, other])
    sync.sync_all(db, Http(timeout=10), root=str(tmp_path))
    apps = rows(db)
    assert db.get("last_sync") and sorted(apps) == sorted([spaced, other])
    for app in apps.values():
        assert app["error_code"] is None and app["forge"] == "forgejo" and app["hero"].endswith("hero.png"), app["error"]
    asked = [p for p, _ in a.seen]
    assert "/o/spaced/raw/branch/main/a%20b.png" in asked and "/o/other/raw/branch/main/docs/%E6%88%AA%E5%9B%BE.png" in asked


def test_through_real_sockets_a_source_whose_own_address_cant_be_sent_has_that_on_its_row(pair, tmp_path, monkeypatch, clock):
    # a row stored with such a path still reaches Sync: its error is its own, and the app after it is stored
    a, b = pair
    spaced, other = f"https://{a.at}/o/my app", forgejo_project(a, "o/other", {"README.md": b"# Other\n"})
    db = catalog(tmp_path, monkeypatch, [spaced, other])
    sync.sync_all(db, Http(timeout=10), root=str(tmp_path), workers=1)
    apps = rows(db)
    assert db.get("last_sync") and apps[other]["error_code"] is None and apps[other]["readme"] == "# Other\n"
    assert apps[spaced]["error_code"] == "Unreachable" and "127.0.0.1" in apps[spaced]["error"], apps[spaced]
    assert [p for p, _ in a.seen if "my" in p] == []


# ---------------------------------------------------------------- a host that answers slowly (R9.2, R9.2.1)
# CR1's #296: Http's timeout is for each read of the socket, and the answer was read in one call
# with no limit on the whole: a host that sent a byte every few seconds held a Sync's worker for as
# long as it liked, and Cancel, which was looked at only before an app's sync started, couldn't stop
# it, so the Sync never ended and no later one started. Any project can name such a host for its
# images. How it slipped past: every stand-in answer was whole at its first read, and no test
# cancelled a Sync. The class is "how long a request may take is up to the host", so the answers
# here come a byte a read on a stepped clock, where no read is slow and only the whole is.
class Dripping(FakeResponse):
    """An answer that comes a byte a read, each read taking `every` seconds of the clock: none of
    them is slow enough to time out. `then` is called with the number of reads so far."""

    def __init__(self, url, body, clock, every, then=None):
        super().__init__(url, body)
        self.clock, self.every, self.reads, self.then = clock, every, 0, then

    def read1(self, n=-1):
        self.reads += 1
        self.clock.now += self.every
        self.then and self.then(self.reads)
        return super().read(1)

    read = read1


def dripping(clock, every, body=b"x" * 1_000_000, then=None, answers=None):
    def open_(req, timeout=0):
        answer = Dripping(req.full_url, body, clock, every, then)
        answers is not None and answers.append(answer)
        return answer
    return open_


@pytest.mark.parametrize("call", ["bytes", "text", "json", "json_with_headers", "request"])
def test_an_answer_that_comes_a_byte_at_a_time_ends_at_the_requests_deadline(clock, call):
    answers = []
    http = names(Http(opener=dripping(clock, 4.0, answers=answers)))
    assert (http.timeout, http.deadline) == (20, 120)                 # no read takes as long as the timeout
    with pytest.raises(Unreachable, match="git.example.org hadn't finished its answer after 120 seconds") as e:
        getattr(http, call)("https://git.example.org/shot.png")
    assert e.value.extra["timeout"] is True
    assert [a.reads for a in answers] == [31]                # 124 seconds of it, and it isn't asked for again
    assert clock.waits == []


def test_the_deadline_counts_the_wait_for_an_answer_to_start(clock):
    answers = []

    def open_(req, timeout=0):
        clock.now += 121                                      # redirects, and headers that come slowly
        return dripping(clock, 0.0, answers=answers)(req, timeout)
    with pytest.raises(Unreachable, match="hadn't finished its answer"):
        names(Http(opener=open_)).bytes("https://git.example.org/shot.png")
    assert [a.reads for a in answers] == [0]


def test_an_answer_that_comes_in_pieces_in_time_is_whole_and_the_size_limit_holds(clock):
    body, answers = PNG * 50, []
    http = names(Http(opener=dripping(clock, 0.05, body, answers=answers)))
    assert http.bytes("https://git.example.org/shot.png") == body
    assert http.bytes("https://git.example.org/shot.png", max_bytes=len(body)) == body
    assert [a.reads for a in answers] == [len(body) + 1] * 2
    answers.clear()
    with pytest.raises(Unreachable, match="too large"):
        http.bytes("https://git.example.org/shot.png", max_bytes=100)
    assert [a.reads for a in answers] == [101]               # and no more of it is read than shows that


def test_r9_2_1_says_how_long_a_request_is_given_and_that_cancel_stops_one():
    text = " ".join(reqdocs.item("R9.2.1").split())
    assert "A request is given two minutes for the whole of its answer" in text and Http().deadline == 120
    assert "**Cancel** stops the requests under way as well" in text


def test_a_cancel_is_its_own_threads_and_its_own_blocks(clock):
    """The application has one Http for everything: a Sync's Cancel stops that Sync's requests, and
    isn't left on the client for an install's lookup, or the next Sync, to trip over."""
    url = "https://git.example.org/shot.png"
    http = names(Http(opener=opener({url: PNG})))
    elsewhere = []
    with http.stopping(lambda: True):
        with pytest.raises(http_.Cancelled):
            http.bytes(url)
        other = threading.Thread(target=lambda: elsewhere.append(http.bytes(url)))       # an install's lookup, meanwhile
        other.start()
        other.join()
        with http.stopping(lambda: False):                   # a block inside a block is its own, too
            assert http.bytes(url) == PNG
        with pytest.raises(http_.Cancelled):
            http.bytes(url)
    assert elsewhere == [PNG] and http.bytes(url) == PNG
    assert http.calls == 3                                   # a cancelled request is never sent
    assert not issubclass(http_.Cancelled, Exception)        # so nothing takes it for a failure of the host


def test_a_cancel_stops_a_request_before_it_is_asked_for_again(clock):
    seen = []
    http = names(Http(opener=recording({"https://git.example.org/": urllib.error.HTTPError("", 503, "busy", {}, None)}, seen)))
    with http.stopping(lambda: bool(seen)):
        with pytest.raises(http_.Cancelled):
            http.bytes("https://git.example.org/api/x")
    assert len(seen) == 1 and clock.waits == [1.5]


@pytest.mark.parametrize("place", ["releases", "readme", "metainfo", "image"])
def test_cancel_stops_a_sync_while_an_answer_is_still_being_read(tmp_path, monkeypatch, clock, place):
    """A Sync, then one that is cancelled as the user would, while an answer of one app's sync drips
    in: it ends at the next read, that app keeps what the first Sync stored with no error on its row,
    and the Cancel was that Sync's own."""
    source, routes = "https://git.example.org/o/r", three_forges()
    db = catalog(tmp_path, monkeypatch, ELSEWHERE)
    http = names(Http({}, opener=opener(routes)))
    sync.sync_all(db, http, root=str(tmp_path))
    db.x("UPDATE apps SET fetched_at='by the first Sync'")
    before = rows(db)
    assert sorted(before) == sorted(ELSEWHERE) and all(app["error_code"] is None for app in before.values())

    slow = tuple(k for k in routes if k.startswith(OWN[source]) and k.endswith(PLACES[place]))
    progress, answers = sync.Progress(), []
    drip = dripping(clock, 4.0, answers=answers, then=lambda reads: reads == 5 and setattr(progress, "cancelled", True))
    http._open = lambda req, timeout=0: (drip if req.full_url.startswith(slow) else opener(routes))(req, timeout)
    sync.sync_all(db, http, progress, root=str(tmp_path), workers=1)
    assert [a.reads for a in answers] == [5] and clock.waits == []        # not a read more, and no other request for it
    after = rows(db)
    assert after[source] == before[source]                    # as the first Sync left it: no error, no half of an app
    assert progress.done == len([u for u in after if after[u] != before[u]]) < 3 and progress.total == 3       # the apps before it

    http._open = opener(routes)                               # the next Sync, with the same Http, is a whole one
    again = sync.Progress()
    sync.sync_all(db, http, again, root=str(tmp_path))
    assert (again.done, again.total) == (3, 3) and all(app["error_code"] is None for app in rows(db).values())


def a_byte_at_a_time(handler):
    handler.wfile.write(b"HTTP/1.1 200 OK\r\nContent-Length: 1000000\r\n\r\n")
    try:
        for _ in range(60):                                   # three seconds of it at most
            handler.wfile.write(b"x")
            time.sleep(0.05)
    except OSError:                                           # its reader has gone
        pass


def test_through_real_sockets_a_byte_at_a_time_ends_at_the_deadline_and_at_cancel(pair):
    # the finding's own run, with Http's own opener and the real clock: no read meets the two-second timeout
    a, b = pair
    a.files = {"/slow.png": a_byte_at_a_time}
    http = Http(timeout=2.0)
    http.deadline = 0.4
    started = time.monotonic()
    with pytest.raises(Unreachable, match="hadn't finished its answer") as e:
        http.bytes(f"https://{a.at}/slow.png")
    assert e.value.extra["timeout"] is True and time.monotonic() - started < 2.0 and len(a.seen) == 1
    http.deadline = 120
    started = time.monotonic()
    with http.stopping(lambda: time.monotonic() - started > 0.3):
        with pytest.raises(http_.Cancelled):
            http.bytes(f"https://{a.at}/slow.png")
    assert time.monotonic() - started < 2.0 and len(a.seen) == 2


# ---------------------------------------------------------------- a host that says when to come back, and one that says nothing (R9.2.1, R2.10)
# CR1's #277: Retry-After was read on a 403 and a 429 alone. A forge that is overloaded or being
# maintained answers 503 with it, and was asked again after 1.5 and 3 seconds, whatever it had asked
# for, by every app on it and by each of four workers. And a host that gave no answer at all was
# asked four times over by forges.detect, each probe with its retries, four minutes an app, to be
# told at the end that AppKata couldn't tell which forge it runs. How it slipped past: the stand-in
# opener sent one kind of error answer, a 403 with both rate-limit headers, and no stand-in host was
# out of reach. The class is "what a host says about when to ask again is not heard", so the answers
# here say it in each form on each failing status, and say nothing at all.
def answering(status, headers, seen):
    """An opener whose every answer is this error status with these headers."""
    def open_(req, timeout=0):
        seen.append(req.full_url)
        raise urllib.error.HTTPError(req.full_url, status, "err", dict(headers), None)
    return open_


def in_two_minutes(clock):
    return time.strftime("%a, %d %b %Y %H:%M:%S GMT", time.gmtime(clock.now + 120))


@pytest.mark.parametrize("status", [500, 502, 503, 504])
@pytest.mark.parametrize("said", ["120", in_two_minutes], ids=["seconds", "a-date"])
def test_a_retry_after_on_a_failing_answer_is_the_hosts_limit(clock, status, said):
    seen = []
    said = said if isinstance(said, str) else said(clock)
    http = names(Http(opener=answering(status, {"Retry-After": said}, seen)))
    with pytest.raises(RateLimited) as e:
        http.json("https://git.example.org/api/v1/repos/o/r")
    assert len(seen) == 1 and clock.waits == []               # not asked again after 1.5 seconds, whatever it asked for
    assert abs(http.limited["git.example.org"] - (clock.now + 120)) <= 1 and e.value.reset == http.limited["git.example.org"]
    for url in ("https://git.example.org/api/v1/repos/o/s", "https://git.example.org/o/s/raw/branch/main/README.md"):
        with pytest.raises(RateLimited):                      # the next app on that host is refused at once
            http.bytes(url)
    assert len(seen) == 1
    _ask(http, "https://codeberg.org/api/v1/version")         # another host is still asked
    assert seen[1:] == ["https://codeberg.org/api/v1/version"]
    clock.now += 121                                          # and the host itself, once the time it gave has passed
    _ask(http, "https://git.example.org/api/v1/repos/o/s")
    assert seen[2] == "https://git.example.org/api/v1/repos/o/s"


@pytest.mark.parametrize("status", [500, 502, 503, 504])
def test_a_failing_answer_that_says_nothing_is_asked_for_again_as_before(clock, status):
    seen = []
    http = names(Http(opener=answering(status, {}, seen)))
    with pytest.raises(Unreachable, match=f"git.example.org answered HTTP {status}") as e:
        http.json("https://git.example.org/api/x")
    assert e.value.extra["status"] == status and http.limited == {}
    assert (len(seen), clock.waits) == ((1, []) if status == 500 else (3, [1.5, 3.0]))


@pytest.mark.parametrize("said, waits", [("2", [2, 3.0]), ("3", [3, 3]), ("1", [1.5, 3.0]), ("0", [1.5, 3.0]),
                                         ("Wed, 21 Oct 2015 07:28:00 GMT", [1.5, 3.0])])
def test_a_retry_after_no_longer_than_the_retries_wait_is_waited_out(clock, said, waits):
    seen = []
    http = names(Http(opener=answering(503, {"Retry-After": said}, seen)))
    with pytest.raises(Unreachable, match="answered HTTP 503"):
        http.json("https://git.example.org/api/x")
    assert len(seen) == 3 and clock.waits == waits and http.limited == {}


@pytest.mark.parametrize("status, error, says", [(404, http_.NotFound, "not found"), (401, Unreachable, "rejected the API token"),
                                                (410, Unreachable, "answered HTTP 410")])
def test_a_retry_after_on_another_answer_is_remembered_and_the_answer_means_what_it_did(clock, status, error, says):
    seen = []
    http = names(Http({"git.example.org": "SECRET"}, opener=answering(status, {"Retry-After": "120"}, seen)))
    with pytest.raises(error, match=says) as e:
        http.json("https://git.example.org/api/x")
    assert type(e.value) is error and http.limited["git.example.org"] == clock.now + 120
    with pytest.raises(RateLimited):
        http.json("https://git.example.org/api/y")
    assert len(seen) == 1 and clock.waits == []


def test_a_sync_asks_a_host_that_said_when_to_come_back_once(tmp_path, monkeypatch, clock):
    """A forge being maintained, with two Sources: one request, both rows say until when, no waiting."""
    seen = []
    sources = ["https://git.example.org/o/r", "https://git.example.org/o/s"]
    db = catalog(tmp_path, monkeypatch, sources)
    http = names(Http(opener=answering(503, {"Retry-After": "600"}, seen)))
    sync.sync_all(db, http, root=str(tmp_path), workers=1)
    apps = rows(db)
    assert seen == ["https://git.example.org/api/v1/version"] and clock.waits == []
    for url in sources:
        assert apps[url]["error_code"] == "RateLimited" and json.loads(apps[url]["error_extra"])["reset"] == clock.now + 600
        assert json.loads(apps[url]["error_extra"])["status"] == 503          # both rows: the one answered and the one refused


@pytest.mark.parametrize("status, headers, a_limit", [
    (403, {"x-ratelimit-remaining": "0", "x-ratelimit-reset": "4102444800"}, True), (403, {"Retry-After": "120"}, True),
    (429, {}, True), (429, {"Retry-After": "120"}, True),
    (500, {"Retry-After": "120"}, False), (502, {"Retry-After": "120"}, False), (503, {"Retry-After": "120"}, False),
    (504, {"Retry-After": "120"}, False),
])
def test_what_said_when_to_come_back_is_kept_with_the_limit(clock, status, headers, a_limit):
    """A forge's own rate limit and a forge being maintained are both RateLimited (R2.10), and a
    token raises only the first: the answer's status goes with the error, for the row to tell them
    apart, and with the host's limit, so the next app refused there says the same as the first."""
    seen = []
    http = names(Http(opener=answering(status, headers, seen)))
    assert (status in http_.LIMIT_STATUSES) == a_limit
    for path in ("o/r", "o/s"):                                # the app that was answered, and the next on that host
        with pytest.raises(RateLimited) as e:
            http.json(f"https://git.example.org/api/v1/repos/{path}")
        assert e.value.extra == {"host": "git.example.org", "reset": http.limited["git.example.org"], "status": status}
        assert ("rate limit reached" in str(e.value)) == a_limit and (f"answered HTTP {status}" in str(e.value)) == (not a_limit)
    assert len(seen) == 1 and json.dumps(e.value.extra)


def test_a_limit_nothing_gave_a_status_for_has_none(clock):
    http = names(Http(opener=opener({})))
    http.limited["git.example.org"] = clock.now + 60           # as a test sets one, and as nothing in the application does
    with pytest.raises(RateLimited, match="rate limit reached") as e:
        http.json("https://git.example.org/api/x")
    assert e.value.extra == {"host": "git.example.org", "reset": clock.now + 60} and e.value.status is None


NO_ANSWER = [TimeoutError("timed out"), urllib.error.URLError(TimeoutError("timed out")),
             urllib.error.URLError(OSError(-2, "Name or service not known")), ConnectionRefusedError(111, "Connection refused"),
             ssl.SSLError(1, "[SSL: WRONG_VERSION_NUMBER] wrong version number")]


@pytest.mark.parametrize("error", NO_ANSWER, ids=lambda e: type(getattr(e, "reason", e)).__name__)
def test_a_host_that_gives_no_answer_is_unreachable_at_its_first_probe(tmp_path, monkeypatch, clock, error):
    seen, source = [], "https://git.example.org/o/r"
    http = names(Http(opener=ending_in(error, "opened", seen)))
    with pytest.raises(Unreachable, match="couldn't reach git.example.org"):
        forges.detect(http, "git.example.org")
    assert set(seen) == {"https://git.example.org/api/v1/version"}        # the first probe, and none of the other three
    assert (len(seen), clock.waits) == ((3, [1.5, 3.0]) if "timed out" in str(error) else (1, []))
    db = catalog(tmp_path, monkeypatch, [source])
    sync.sync_all(db, http, root=str(tmp_path))
    app = rows(db)[source]
    assert app["error_code"] == "Unreachable" and "couldn't reach git.example.org" in app["error"]      # R2.10's kind for it


@pytest.mark.parametrize("answer", [404, 500, 401, b"<html>a sign-in page</html>", {"message": "another shape"}, ["a", "list"]],
                         ids=["404", "500", "401", "html", "an-object", "a-list"])
def test_a_host_that_answers_but_not_as_a_forges_api_is_probed_to_the_end(clock, answer):
    routes = {f"https://git.example.org/api/{p}": answer for p in ("v1/version", "v3/meta")}
    routes["https://git.example.org/api/v4/projects"] = answer if answer != ["a", "list"] else {"an": "object"}
    seen = []
    plain = opener({**routes, "https://git.example.org/": b'<html><meta name="generator" content="Gitea - Git with a cup of tea">'})

    def open_(req, timeout=0):
        seen.append(req.full_url)
        if isinstance(routes.get(req.full_url.split("?")[0]), int):
            raise urllib.error.HTTPError(req.full_url, routes[req.full_url.split("?")[0]], "err", {}, None)
        return plain(req, timeout)
    assert forges.detect(names(Http(opener=open_)), "git.example.org") == "gitea"
    assert list(dict.fromkeys(seen)) == ["https://git.example.org/api/v1/version", "https://git.example.org/api/v4/projects?per_page=1",
                                         "https://git.example.org/api/v3/meta", "https://git.example.org/"]
    seen.clear()
    with pytest.raises(forges.Unsupported, match="couldn't tell which forge git.example.org runs"):      # and with no page that says
        forges.detect(names(Http(opener=lambda req, timeout=0: open_(req, timeout) if "/api/" in req.full_url else opener({})(req))),
                      "git.example.org")


def maintenance(handler):
    handler.wfile.write(b"HTTP/1.1 503 Service Unavailable\r\nRetry-After: 120\r\nContent-Length: 0\r\n\r\n")


def test_through_real_sockets_a_503_that_says_when_and_a_host_with_nothing_listening(pair, clock):
    a, b = pair
    a.files = {"/api/v1/version": maintenance}
    http = Http(timeout=5)
    for _ in range(2):
        with pytest.raises(RateLimited):
            forges.detect(http, a.at)
    assert [p for p, _ in a.seen] == ["/api/v1/version"] and clock.waits == []
    assert http.limited == {"127.0.0.1": clock.now + 120}
    with socket.socket() as nothing:                          # a port of this machine where nothing listens
        nothing.bind(("127.0.0.1", 0))
        closed = nothing.getsockname()[1]
    with pytest.raises(Unreachable, match="couldn't reach 127.0.0.1"):
        forges.detect(Http(timeout=5), f"127.0.0.1:{closed}")
    assert clock.waits == []


# ---------------------------------------------------------------- an answer cut off before its declared length (R3.2, R3.3, R9.1)
# CR1's #626: http.client hands back a short body without an error when a connection ends before
# the Content-Length it declared, and Http didn't compare the two: a cut-off image that starts as a
# PNG was saved as the icon, and a cut-off README or file list was stored as the whole one. How it
# slipped past: no stand-in answer declared a length. The class is "what arrived is taken for what
# was sent", so the answers here declare one, and each kind of answer that declares a length it
# rightly doesn't send is held as well.
def declaring(headers, body, seen=None, method="GET"):
    def open_(req, timeout=0):
        seen is not None and seen.append(req.full_url)
        assert req.get_method() == method
        return FakeResponse(req.full_url, body, dict(headers))
    return open_


@pytest.mark.parametrize("call", ["bytes", "text", "json", "json_with_headers", "request"])
def test_an_answer_shorter_than_the_length_it_declared_is_cut_short_and_asked_for_again(clock, call):
    seen = []
    http = names(Http(opener=declaring({"Content-Length": "1000"}, b"[" + b"1," * 49 + b"1", seen)))       # 100 bytes of them
    with pytest.raises(Unreachable, match="git.example.org cut its answer short \\(100 of 1000 bytes\\)") as e:
        getattr(http, call)("https://git.example.org/api/x")
    assert e.value.extra["cut"] is True and len(seen) == 3 and clock.waits == [1.5, 3.0]
    with pytest.raises(Unreachable, match="cut its answer short"):
        http._request("https://git.example.org/api/x")


def test_an_answer_cut_short_once_is_whole_the_second_time(clock):
    whole, answers = PNG * 10, []

    def open_(req, timeout=0):
        answers.append(FakeResponse(req.full_url, whole[:100] if not answers else whole, {"content-length": str(len(whole))}))
        return answers[-1]
    assert names(Http(opener=open_)).bytes("https://git.example.org/icon.png") == whole
    assert len(answers) == 2 and clock.waits == [1.5]


@pytest.mark.parametrize("headers, body, method", [
    ({"Content-Length": "100"}, b"x" * 100, "GET"),                              # whole
    ({}, b"x" * 100, "GET"), ({"Content-Length": "0"}, b"", "GET"),              # none declared; nothing declared, nothing sent
    ({"Content-Length": "1000"}, b"", "HEAD"),                                   # an answer to HEAD says what a GET would send
    ({"Content-Length": "1000", "Transfer-Encoding": "chunked"}, b"x" * 100, "GET"),      # the chunks say where it ends, not the length
    ({"Content-Length": "1000", "Content-Encoding": "gzip"}, b"x" * 100, "GET"),          # not a plain body
    ({"Content-Length": "a thousand"}, b"x" * 100, "GET"), ({"Content-Length": ""}, b"x" * 100, "GET"),
    ({"Content-Length": "-5"}, b"x" * 100, "GET"),
], ids=["whole", "none", "nothing", "head", "chunked", "encoded", "not-a-number", "empty", "negative"])
def test_an_answer_that_is_whole_or_rightly_declares_what_it_doesnt_send_is_taken(clock, headers, body, method):
    http = names(Http(opener=declaring(headers, body, method=method)))
    data, hdr, _ = http.request("https://git.example.org/api/x", method=method)
    assert data == body and clock.waits == []


def cut_off(body, declared=1000):
    def answer(handler):
        handler.wfile.write(f"HTTP/1.1 200 OK\r\nContent-Length: {declared}\r\n\r\n".encode() + body)
    return answer


def test_through_real_sockets_a_cut_off_image_isnt_saved_and_a_cut_off_readme_isnt_stored(pair, tmp_path, monkeypatch, clock):
    """The finding's own run, with Http's own opener: a server on this machine declares 1000 bytes,
    sends a PNG's first 100 and closes. Then a whole Sync whose README is cut off the same way."""
    a, b = pair
    a.files = {"/icon.png": cut_off(PNG + b"\0" * (100 - len(PNG)))}
    http = Http(timeout=10)
    with pytest.raises(Unreachable, match="127.0.0.1 cut its answer short \\(100 of 1000 bytes\\)"):
        sync._save_image(http, f"https://{a.at}/icon.png", str(tmp_path / "icon"), token_host=a.at)
    assert [p for p, _ in a.seen] == ["/icon.png"] * 3 and list(tmp_path.iterdir()) == []
    with pytest.raises(Unreachable, match="cut its answer short"):          # where it was "didn't return JSON"
        http.json(f"https://{a.at}/icon.png")

    readme = b"# Whole\n\nThe whole README, which says what the app is and how it is installed.\n" * 5
    source = forgejo_project(a, "o/r", {"README.md": readme})
    db = catalog(tmp_path, monkeypatch, [source])
    sync.sync_all(db, http, root=str(tmp_path))
    assert rows(db)[source]["error_code"] is None and rows(db)[source]["readme"] == readme.decode()
    a.files["/o/r/raw/branch/main/README.md"] = cut_off(readme[:100], len(readme))
    sync.sync_all(db, http, root=str(tmp_path))
    app = rows(db)[source]
    assert app["error_code"] == "Unreachable" and "cut its answer short" in app["error"]
    assert app["readme"] == readme.decode()                   # the whole one, from the Sync before


# ---------------------------------------------------------------- github.com's pages are github.com's alone (R2.4.1)
# CR1's #265: forges.GitHub is the class of a GitHub Enterprise Source too, and of any host whose
# forge type is set to GitHub, and the pages that stand in for github.com's API have github.com
# written into them. A Sync's own calls kept to github.com (_try); sync.ensure_assets, which reads a
# release's files when it is opened for install, had its own fallback with no such test, on any
# failure of the API: off the VPN, or with an expired token, an Enterprise release was given the
# files and the SHA-256 digests of whatever project has its path on github.com. How it slipped
# past: ensure_assets had one test, on a Forgejo, and no test put a GitHub on another host through a
# failing API. The class is "github.com answers for a host that isn't github.com", so a project of
# the same path is there in every test below, ready to answer with a file and its digest, and what
# is held is that nothing is asked of it: by the file list, by a whole Sync, and by each way to the
# pages there is, whichever is added next.
GHE = "https://ghe.corp.example/team/tool"
GHE_API = "https://ghe.corp.example/api/v3/repos/team/tool"
DIGEST = "sha256:" + "ab" * 32
FILE = "/team/tool/releases/download/v1.0.0/tool-1.0.0-x86_64.AppImage"
THEIR_PAGE = (f'<a href="{FILE}">tool-1.0.0-x86_64.AppImage</a> <span>{DIGEST}</span> <span>5 MB</span>'
              '<relative-time datetime="2026-01-01T00:00:00Z">').encode()
THEIRS = {       # github.com's project of the same path: its API and its pages, each of which would answer
    "https://api.github.com/": {"assets": [{"name": "tool-1.0.0-x86_64.AppImage", "browser_download_url": "https://github.com" + FILE,
                                            "digest": DIGEST}]},
    "https://github.com/": THEIR_PAGE,
}
FROM_THE_PAGE = [{"name": "tool-1.0.0-x86_64.AppImage", "url": "https://github.com" + FILE, "size": 5000000, "digest": DIGEST,
                  "content_type": ""}]


def _status(code, **headers):
    return urllib.error.HTTPError("", code, "err", headers, None)


API_FAILS = {      # what the API's answer can be when a release's files are asked for
    "limit-used-up": 403, "429": _status(429), "503-come-back-later": _status(503, **{"Retry-After": "600"}),     # RateLimited
    "token-expired": _status(401), "no-such-release": _status(404), "500": _status(500),
    "off-the-vpn": urllib.error.URLError(OSError(-2, "Name or service not known")), "timeout": TimeoutError("timed out"),
    "a-sign-in-page": b"<html>Sign in to continue</html>",
}
SAYS_COME_BACK = ("limit-used-up", "429", "503-come-back-later")


def stored_without_files(tmp_path, url, kind):
    """An app as a Sync left it: its newest release with its files, an older one without."""
    db = DB(str(tmp_path / "a.db"))
    db.x("INSERT INTO apps(url, name, forge, releases) VALUES(?,?,?,?)", (url, "Tool", kind, json.dumps(
        [{"tag": "v2.0.0", "version": "2.0.0", "date": "2026-02-01", "assets": [{"name": "tool-2.0.0-x86_64.AppImage"}]},
         {"tag": "v1.0.0", "version": "1.0.0", "date": "2025-02-01", "assets": []}])))
    return db


def files_of(db, url, version="1.0.0"):
    releases = json.loads(db.one("SELECT releases FROM apps WHERE url=?", (url,))["releases"])
    return next(r for r in releases if r["version"] == version)["assets"]


@pytest.fixture
def git(monkeypatch):
    """Stands in for git, noting what it was asked."""
    asked = []
    monkeypatch.setattr(forges, "_git_out", lambda args: asked.append(args) or "")
    return asked


def off(host, seen):
    return [url for url, _ in seen if not url.startswith(f"https://{host}/")]


@pytest.mark.parametrize("kind", ["ghe", "github"])            # a GitHub Enterprise, and a host whose forge type is set to GitHub
@pytest.mark.parametrize("fails", sorted(API_FAILS))
def test_a_github_on_another_host_takes_no_files_from_github_coms_project_of_its_path(tmp_path, clock, git, kind, fails):
    seen = []
    db = stored_without_files(tmp_path, GHE, kind)
    http = names(Http({"ghe.corp.example": "SECRET"}, opener=recording({GHE_API + "/releases/tags/v1.0.0": API_FAILS[fails], **THEIRS}, seen)))
    with pytest.raises(SourceError):                           # the error is the caller's to show
        sync.ensure_assets(db, http, GHE, "1.0.0")
    assert seen and off("ghe.corp.example", seen) == [] and git == []
    assert files_of(db, GHE) == []                             # and what was stored is as it was


@pytest.mark.parametrize("kind", ["ghe", "github"])
def test_a_github_on_another_host_has_its_own_apis_files(tmp_path, git, kind):
    seen = []
    db = stored_without_files(tmp_path, GHE, kind)
    own = {"name": "tool-1.0.0.tar.gz", "browser_download_url": "https://ghe.corp.example/f", "size": 7, "digest": "sha256:" + "cd" * 32}
    http = names(Http({"ghe.corp.example": "SECRET"}, opener=recording({GHE_API + "/releases/tags/v1.0.0": {"assets": [own]}, **THEIRS}, seen)))
    assert sync.ensure_assets(db, http, GHE, "1.0.0")["assets"] == files_of(db, GHE) == [
        {"name": "tool-1.0.0.tar.gz", "url": "https://ghe.corp.example/f", "size": 7, "digest": "sha256:" + "cd" * 32, "content_type": ""}]
    assert [url for url, _ in seen] == [GHE_API + "/releases/tags/v1.0.0"] and tokened(seen) == [url for url, _ in seen]


@pytest.mark.parametrize("fails", sorted(API_FAILS))
def test_github_com_itself_reads_its_page_when_its_api_says_to_come_back_and_only_then(tmp_path, clock, git, fails):
    url, api = "https://github.com/team/tool", "https://api.github.com/repos/team/tool/releases/tags/v1.0.0"
    page, seen = "https://github.com/team/tool/releases/expanded_assets/v1.0.0", []
    db = stored_without_files(tmp_path, url, "github")
    http = names(Http(opener=recording({api: API_FAILS[fails], page: THEIR_PAGE}, seen)))
    if fails in SAYS_COME_BACK:                                # R2.4.1: the pages, when the API's limit is used up
        assert sync.ensure_assets(db, http, url, "1.0.0")["assets"] == files_of(db, url) == FROM_THE_PAGE
        assert [u for u, _ in seen] == [api, page]
    else:                                                      # any other failure is an error, as it is for a Sync's own calls
        with pytest.raises(SourceError):
            sync.ensure_assets(db, http, url, "1.0.0")
        assert set(u for u, _ in seen) == {api} and files_of(db, url) == []


def test_github_com_known_to_be_limited_is_asked_for_its_page_alone(tmp_path, git):
    url, seen = "https://github.com/team/tool", []
    db = stored_without_files(tmp_path, url, "github")
    http = names(Http(opener=recording(THEIRS, seen)))
    http.limited["api.github.com"] = time.time() + 600
    assert sync.ensure_assets(db, http, url, "1.0.0")["assets"] == FROM_THE_PAGE
    assert [u for u, _ in seen] == ["https://github.com/team/tool/releases/expanded_assets/v1.0.0"]


WEB_ARGS = {"tag": "v1.0.0", "limit": 30, "ref": "main"}


@pytest.mark.parametrize("kind", ["ghe", "github"])
def test_every_way_to_github_coms_pages_is_refused_for_another_host(git, kind):
    """Each function that reads github.com's pages or asks git for the project there, found by its
    name, so the next one written is held too; and each call of a forge that somehow came to think
    its API's limit is used up."""
    seen = []
    http = names(Http({"ghe.corp.example": "SECRET"}, opener=recording(THEIRS, seen)))
    f = forges.forge_for(http, urls.parse(GHE), kind)
    assert not f.web
    ways = sorted(name for name in dir(f) if name.endswith("_web"))
    assert {"_info_web", "_releases_web", "_release_tags_web", "_bare_tag_web", "_assets_web", "_tags_web", "_tree_web"} <= set(ways)
    for name in ways:
        way = getattr(f, name)
        with pytest.raises(forges.Unsupported, match="ghe.corp.example isn't github.com"):
            way(*[WEB_ARGS[p] for p in inspect.signature(way).parameters])
    f.web = True
    for call in (f.info, f.releases, f.tags, lambda: f.tree("main"), lambda: f.release_assets("v1.0.0")):
        with pytest.raises(forges.Unsupported, match="ghe.corp.example isn't github.com"):
            call()
    assert seen == [] and git == []
    theirs = forges.forge_for(http, urls.parse("https://github.com/team/tool"), "github")       # and for github.com they are open
    assert theirs._page("/releases.atom") == "https://github.com/team/tool/releases.atom"
    assert theirs._assets_web("v1.0.0")[0] == [forges.Asset(a["name"], a["url"], a["size"], a["digest"]) for a in FROM_THE_PAGE]


GHE_PLACES = {"info": "", "releases": "/releases", "files": "/git/trees/main", "a-releases-files": "/releases/tags/v1.0.0"}


@pytest.mark.parametrize("place", sorted(GHE_PLACES))
@pytest.mark.parametrize("fails", sorted(API_FAILS))
def test_a_sync_and_a_file_list_of_an_enterprise_source_ask_nothing_of_github_com(tmp_path, monkeypatch, clock, git, place, fails):
    """Whatever the Enterprise's API answers, wherever: a whole Sync of the Source, then the files of
    the release it stored without any, as an install asks for them."""
    raw = "https://ghe.corp.example/team/tool/raw/main/"
    routes = {GHE_API: {"name": "tool", "full_name": "team/tool", "default_branch": "main"},
              GHE_API + "/releases": [{"tag_name": "v1.0.0", "name": "1.0", "published_at": "2025-02-01T00:00:00Z", "assets": []}],
              GHE_API + "/git/trees/main": {"tree": [{"path": "README.md", "type": "blob"}]},
              GHE_API + "/releases/tags/v1.0.0": {"assets": []}, raw + "README.md": b"# Tool\n", **THEIRS}
    routes[GHE_API + GHE_PLACES[place]] = API_FAILS[fails]
    seen = []
    db = catalog(tmp_path, monkeypatch, [GHE])
    db.x("UPDATE sources SET settings=? WHERE url=?", (json.dumps({"forge": "ghe"}), GHE))
    http = names(Http({"ghe.corp.example": "SECRET"}, opener=recording(dict(sorted(routes.items(), key=lambda kv: -len(kv[0]))), seen)))
    sync.sync_all(db, http, root=str(tmp_path))
    app = rows(db)[GHE]
    assert (app["error_code"] is None) == (place in ("files", "a-releases-files")), (app["error_code"], app["error"])
    try:
        sync.ensure_assets(db, http, GHE, "1.0.0")
    except SourceError:
        pass
    assert seen and off("ghe.corp.example", seen) == [] and git == []


# ---------------------------------------------------------------- what Http makes of each answer (R9.2.1, R2.10)
# CR1's #298: one test held Http's handling of a failing answer, a 403 with both of GitHub's
# rate-limit headers, because the stand-in opener sent no other: both headers on every error status,
# and a 404 for every address it had no route for. A Retry-After in either form, a 429 that says
# nothing, the retries and their waits, the 401 of a token, an answer that isn't JSON and a 404 were
# all unheld, and #269 and #277 were in those gaps. The fixes of #269, #277, #296 and #626 each
# brought tests of their own branch. This is the whole of it in one table instead, a row for each
# thing a host can answer and what Http makes of it: the error's kind, its words and its `extra` as
# a Sync writes them on a row, how many times the address was asked and after which waits, and what
# is remembered of the host. The stand-in sends exactly what a row says and nothing more. Left to
# their own tests above: the deadline and Cancel, which need an answer that comes in pieces.
ASKED = "https://git.example.org/api/x"
OK = (200, {}, b'{"ok": true}')
Y2100, Y2100_AS_A_DATE = 4102444800, "Fri, 01 Jan 2100 00:00:00 GMT"
Y2015, Y2015_AS_A_DATE = 1445412480, "Wed, 21 Oct 2015 07:28:00 GMT"
USED_UP = {"x-ratelimit-remaining": "0"}


def scripted(answers, seen):
    """A recording opener that answers the first request with the first of `answers`, the second
    with the second, and every later one with the last. An answer is (status, headers, body), sent
    as it stands, or what opening the address ends in."""
    def open_(req, timeout=0):
        seen.append(req)
        answer = answers[min(len(seen), len(answers)) - 1]
        if isinstance(answer, BaseException):
            raise answer
        status, headers, body = answer
        if status >= 400:                                      # as urllib's own opener hands a failing status on
            raise urllib.error.HTTPError(req.full_url, status, "err", dict(headers), None)
        return FakeResponse(req.full_url, body, dict(headers))
    return open_


def answer(id, *answers, call="json", raises=None, says=None, extra=None, gives=None, asked=1, waits=(), limited_in=None,
           limited_at=None, tokens=None, **kw):
    return pytest.param(types.SimpleNamespace(answers=answers, call=call, raises=raises, says=says, extra=extra or {}, gives=gives,
                                              asked=asked, waits=list(waits), limited_in=limited_in, limited_at=limited_at,
                                              tokens=tokens, kw=kw), id=id)


def failing(status, **extra):
    return dict(raises=Unreachable, says=f"git.example.org answered HTTP {status}", extra={"status": status, **extra})


def limit(status, **when):
    """A RateLimited whose status is `status`, until `limited_in` seconds from now or the time `limited_at`."""
    says = "rate limit reached" if status in (403, 429) else f"answered HTTP {status} and said when to come back"
    return dict(raises=RateLimited, says="git.example.org " + says, extra={"host": "git.example.org", "status": status}, **when)


NO_ANSWER_AT_ALL = dict(raises=Unreachable, extra={"no_answer": True})
ANSWERS = [
    # an answer
    answer("200", OK, gives={"ok": True}),
    answer("200-as-text", OK, call="text", gives='{"ok": true}'),
    answer("200-as-bytes", OK, call="bytes", gives=b'{"ok": true}'),
    answer("200-with-its-headers", (200, {"ETag": "W/1", "X-RateLimit-Remaining": "59"}, b"[1]"), call="json_with_headers",
           gives=([1], {"etag": "W/1", "x-ratelimit-remaining": "59"}, ASKED)),
    answer("200-not-json", (200, {}, b"<html>Sign in</html>"), raises=Unreachable, says="git.example.org didn't return JSON"),
    answer("200-not-json-with-its-headers", (200, {}, b"<html>Sign in</html>"), call="json_with_headers", raises=Unreachable,
           says="git.example.org didn't return JSON"),
    answer("200-not-utf-8", (200, {}, b"\xff\xfe{"), raises=Unreachable, says="git.example.org didn't return JSON"),
    answer("200-empty", (200, {}, b""), raises=Unreachable, says="git.example.org didn't return JSON"),
    answer("200-not-utf-8-as-text", (200, {}, b"caf\xe9"), call="text", gives="caf\ufffd"),
    answer("200-as-large-as-allowed", (200, {}, b"x" * 100), call="bytes", max_bytes=100, gives=b"x" * 100),
    answer("200-a-byte-too-large", (200, {}, b"x" * 101), call="bytes", max_bytes=100, raises=Unreachable,
           says="response from git.example.org too large"),
    # a failing status that says nothing about when: its own kind, and no retry but for 502, 503 and 504
    answer("404", (404, {}, b""), raises=http_.NotFound, says=ASKED + " not found"),
    answer("401-with-the-hosts-token", (401, {}, b""), tokens={"git.example.org": "SECRET"}, raises=Unreachable,
           says="git.example.org rejected the API token (HTTP 401)"),
    answer("401-with-no-token", (401, {}, b""), **failing(401)),
    answer("401-with-another-hosts-token", (401, {}, b""), tokens={"codeberg.org": "SECRET"}, **failing(401)),
    answer("401-with-a-token-for-another-port-of-it", (401, {}, b""), tokens={"git.example.org:8080": "SECRET"}, **failing(401)),
    answer("403-that-says-nothing", (403, {}, b""), **failing(403)),
    answer("403-with-requests-left", (403, {"x-ratelimit-remaining": "12", "x-ratelimit-reset": str(Y2100)}, b""), **failing(403)),
    answer("410", (410, {}, b""), **failing(410)),
    answer("500", (500, {}, b""), **failing(500)),
    answer("502", (502, {}, b""), asked=3, waits=[1.5, 3.0], **failing(502)),
    answer("503", (503, {}, b""), asked=3, waits=[1.5, 3.0], **failing(503)),
    answer("504", (504, {}, b""), asked=3, waits=[1.5, 3.0], **failing(504)),
    answer("503-then-200", (503, {}, b""), OK, gives={"ok": True}, asked=2, waits=[1.5]),
    answer("502-504-then-200", (502, {}, b""), (504, {}, b""), OK, gives={"ok": True}, asked=3, waits=[1.5, 3.0]),
    answer("503-then-404", (503, {}, b""), (404, {}, b""), raises=http_.NotFound, says=ASKED + " not found", asked=2, waits=[1.5]),
    answer("503-then-500", (503, {}, b""), (500, {}, b""), asked=2, waits=[1.5], **failing(500)),
    # a forge's rate limit: a 403 that says the requests are used up or when to come back, and any 429
    answer("403-used-up-until", (403, {**USED_UP, "x-ratelimit-reset": str(Y2100)}, b""), **limit(403, limited_at=Y2100)),
    answer("403-used-up-and-no-time", (403, USED_UP, b""), **limit(403, limited_in=60)),
    answer("403-retry-after-seconds", (403, {"Retry-After": "30"}, b""), **limit(403, limited_in=30)),
    answer("403-retry-after-a-short-one", (403, {"Retry-After": "2"}, b""), **limit(403, limited_in=2)),
    answer("403-retry-after-a-date", (403, {"Retry-After": Y2100_AS_A_DATE}, b""), **limit(403, limited_at=Y2100)),
    answer("429-that-says-nothing", (429, {}, b""), **limit(429, limited_in=60)),
    answer("429-retry-after-seconds", (429, {"Retry-After": "120"}, b""), **limit(429, limited_in=120)),
    answer("429-retry-after-zero", (429, {"Retry-After": "0"}, b""), **limit(429, limited_in=0)),
    answer("429-retry-after-a-date", (429, {"Retry-After": Y2100_AS_A_DATE}, b""), **limit(429, limited_at=Y2100)),
    answer("429-retry-after-a-date-gone-by", (429, {"Retry-After": Y2015_AS_A_DATE}, b""), **limit(429, limited_at=Y2015)),
    answer("429-retry-after-unreadable", (429, {"Retry-After": "soon"}, b""), **limit(429, limited_in=60)),
    answer("429-the-reset-time-comes-first", (429, {"x-ratelimit-reset": str(Y2100), "Retry-After": "120"}, b""), **limit(429, limited_at=Y2100)),
    answer("429-reset-time-unreadable", (429, {"x-ratelimit-reset": "soon", "Retry-After": "120"}, b""), **limit(429, limited_in=120)),
    answer("429-retry-after-a-digit-that-is-no-number", (429, {"Retry-After": "\u00b2"}, b""), **limit(429, limited_in=60)),
    answer("429-retry-after-no-time-a-clock-can-show", (429, {"Retry-After": "9" * 30}, b""), **limit(429, limited_in=60)),
    answer("403-reset-time-no-time-a-clock-can-show", (403, {**USED_UP, "x-ratelimit-reset": "9" * 17}, b""), **limit(403, limited_in=60)),
    # a Retry-After on any other failing answer (CR1 #277)
    answer("503-retry-after-long", (503, {"Retry-After": "120"}, b""), **limit(503, limited_in=120)),
    answer("500-retry-after-a-date", (500, {"Retry-After": Y2100_AS_A_DATE}, b""), **limit(500, limited_at=Y2100)),
    answer("503-retry-after-short", (503, {"Retry-After": "2"}, b""), asked=3, waits=[2, 3.0], **failing(503, retry_after=2)),
    answer("503-retry-after-short-then-200", (503, {"Retry-After": "3"}, b""), OK, gives={"ok": True}, asked=2, waits=[3]),
    answer("500-retry-after-short", (500, {"Retry-After": "2"}, b""), **failing(500, retry_after=2)),
    answer("404-retry-after-long", (404, {"Retry-After": "120"}, b""), raises=http_.NotFound, says=ASKED + " not found", limited_in=120),
    answer("404-retry-after-short", (404, {"Retry-After": "3"}, b""), raises=http_.NotFound, says=ASKED + " not found"),
    answer("401-retry-after-long", (401, {"Retry-After": "120"}, b""), limited_in=120, **failing(401)),
    # no answer at all: asked again only when it timed out
    answer("timed-out", TimeoutError("timed out"), asked=3, waits=[1.5, 3.0], says="couldn't reach git.example.org: timed out",
           **{**NO_ANSWER_AT_ALL, "extra": {"no_answer": True, "timeout": True}}),
    answer("timed-out-as-urllib-says-it", urllib.error.URLError(TimeoutError("timed out")), asked=3, waits=[1.5, 3.0],
           says="couldn't reach git.example.org: timed out", **{**NO_ANSWER_AT_ALL, "extra": {"no_answer": True, "timeout": True}}),
    answer("timed-out-in-words-alone", urllib.error.URLError("_ssl.c:1011: The handshake operation timed out"), asked=3, waits=[1.5, 3.0],
           says="couldn't reach git.example.org: _ssl.c:1011: The handshake operation timed out",
           **{**NO_ANSWER_AT_ALL, "extra": {"no_answer": True, "timeout": True}}),
    answer("timed-out-without-a-word", TimeoutError(), asked=3, waits=[1.5, 3.0], says="couldn't reach git.example.org: ",
           **{**NO_ANSWER_AT_ALL, "extra": {"no_answer": True, "timeout": True}}),
    answer("timed-out-then-200", TimeoutError("timed out"), OK, gives={"ok": True}, asked=2, waits=[1.5]),
    answer("refused", urllib.error.URLError(ConnectionRefusedError(111, "Connection refused")),
           says="couldn't reach git.example.org: [Errno 111] Connection refused", **{**NO_ANSWER_AT_ALL, "extra": {"no_answer": True, "timeout": False}}),
    answer("no-such-name", urllib.error.URLError(OSError(-2, "Name or service not known")),
           says="couldn't reach git.example.org: [Errno -2] Name or service not known",
           **{**NO_ANSWER_AT_ALL, "extra": {"no_answer": True, "timeout": False}}),
    answer("reset", ConnectionResetError(104, "Connection reset by peer"),
           says="couldn't reach git.example.org: [Errno 104] Connection reset by peer", **{**NO_ANSWER_AT_ALL, "extra": {"no_answer": True, "timeout": False}}),
    # an answer that isn't whole, and one that can't be read (CR1 #269, #626)
    answer("cut-short-in-its-chunks", IncompleteRead(b"half", 96), raises=Unreachable, says="git.example.org cut its answer short",
           extra={"cut": True}, asked=3, waits=[1.5, 3.0]),
    answer("cut-short-of-its-length", (200, {"Content-Length": "40"}, b'{"ok": true}'), raises=Unreachable,
           says="git.example.org cut its answer short (12 of 40 bytes)", extra={"cut": True}, asked=3, waits=[1.5, 3.0]),
    answer("cut-short-then-whole", (200, {"Content-Length": "40"}, b'{"ok": true}'), (200, {"Content-Length": "12"}, b'{"ok": true}'),
           gives={"ok": True}, asked=2, waits=[1.5]),
    answer("an-address-that-cant-be-sent", InvalidURL("URL can't contain control characters"), raises=Unreachable,
           says=f"couldn't ask git.example.org: the address {ASKED!r} can't be sent (InvalidURL)"),
    answer("an-answer-that-cant-be-read", BadStatusLine("\x16\x03\x01"), raises=Unreachable,
           says="couldn't read git.example.org's answer (BadStatusLine: \x16\x03\x01)"),
]


@pytest.mark.parametrize("c", ANSWERS)
def test_what_http_makes_of_each_answer(clock, c):
    seen = []
    http = names(Http(c.tokens, opener=scripted(c.answers, seen)))
    started = clock.now
    if c.raises:
        with pytest.raises(c.raises) as e:
            getattr(http, c.call)(ASKED, **c.kw)
        assert type(e.value) is c.raises and str(e.value) == c.says
        assert {k: e.value.extra.get(k) for k in c.extra} == c.extra and json.dumps(e.value.extra)      # as a row keeps them
        if c.raises is not RateLimited:
            assert not {"host", "reset"} & set(e.value.extra)
    else:
        assert getattr(http, c.call)(ASKED, **c.kw) == c.gives
    assert len(seen) == c.asked == http.calls and clock.waits == c.waits
    until = c.limited_at if c.limited_at is not None else None if c.limited_in is None else started + c.limited_in
    assert http.limited == ({} if until is None else {"git.example.org": until})
    if c.raises is RateLimited:
        assert e.value.reset == e.value.extra["reset"] == until and e.value.host == "git.example.org"


def test_the_table_has_a_row_for_each_kind_of_error_and_each_thing_a_retry_turns_on():
    # the table is only as whole as its rows: every kind Http itself gives, every reason it asks again, each status it tells apart
    rows_ = [p.values[0] for p in ANSWERS]
    assert {c.raises for c in rows_ if c.raises} == {Unreachable, http_.NotFound, RateLimited}
    assert {k for c in rows_ for k in c.extra} == {"status", "retry_after", "timeout", "no_answer", "cut", "host"}
    statuses = {a[0] for c in rows_ for a in c.answers if isinstance(a, tuple)}
    assert statuses >= {200, 401, 403, 404, 429, 500, 502, 503, 504}
    assert {c.call for c in rows_} == {"json", "json_with_headers", "text", "bytes"}


@pytest.mark.parametrize("headers, at, after", [
    ({}, None, 60),
    ({"x-ratelimit-reset": str(Y2100)}, Y2100, None), ({"x-ratelimit-reset": "1000000000"}, 1000000000, None),
    ({"x-ratelimit-reset": str(Y2100), "retry-after": "5"}, Y2100, None),               # GitHub's own header first
    ({"x-ratelimit-reset": "", "retry-after": "5"}, None, 5), ({"x-ratelimit-reset": "soon"}, None, 60),
    ({"x-ratelimit-reset": "-1"}, None, 60), ({"x-ratelimit-reset": "1.5e9"}, None, 60),
    ({"retry-after": "0"}, None, 0), ({"retry-after": "1"}, None, 1), ({"retry-after": "86400"}, None, 86400),
    ({"retry-after": Y2100_AS_A_DATE}, Y2100, None), ({"retry-after": Y2015_AS_A_DATE}, Y2015, None),
    ({"retry-after": "Friday, 01-Jan-00 00:00:00 GMT"}, 946684800, None),                 # the older form of a date
    ({"retry-after": ""}, None, 60), ({"retry-after": "soon"}, None, 60), ({"retry-after": "-5"}, None, 60),
    ({"retry-after": "1.5"}, None, 60), ({"retry-after": "12 seconds"}, None, 60),
    # a digit to str.isdigit that is no number to int or float: it raised out of Http
    ({"retry-after": "\u00b2"}, None, 60), ({"x-ratelimit-reset": "\u00b2"}, None, 60), ({"x-ratelimit-reset": "\u00b2", "retry-after": "5"}, None, 5),
    ({"retry-after": "\u0661\u0662\u0660"}, None, 60),
    # a number that is no time a clock can show: it raised where the Source's row was shown
    ({"x-ratelimit-reset": "9" * 17}, None, 60), ({"x-ratelimit-reset": "9" * 400}, None, 60), ({"retry-after": "9" * 30}, None, 60),
    ({"retry-after": "9" * 400}, None, 60), ({"x-ratelimit-reset": "9" * 17, "retry-after": "5"}, None, 5),
    ({"retry-after": "Fri, 01 Jan 99999 00:00:00 GMT"}, None, 60),
])
def test_when_a_host_may_be_asked_again_is_read_from_its_headers(clock, headers, at, after):
    """_reset_time: GitHub's reset time, else a Retry-After in seconds or as a date, else a minute."""
    assert http_._reset_time(headers) == (at if at is not None else clock.now + after)


def test_a_limited_host_is_refused_without_being_asked_until_its_time_has_come(clock):
    seen = []
    http = names(Http(opener=scripted([(429, {"Retry-After": "120"}, b""), OK], seen)))
    with pytest.raises(RateLimited):
        http.json(ASKED)
    for call, url in (("json", ASKED), ("bytes", "https://git.example.org/o/r/raw/branch/main/icon.png"),
                      ("text", "http://git.example.org/"), ("json", "https://git.example.org:3000/api/x")):
        with pytest.raises(RateLimited, match="git.example.org rate limit reached") as e:
            getattr(http, call)(url)
        assert e.value.reset == clock.now + 120 and e.value.extra["status"] == 429
    assert len(seen) == 1 == http.calls and clock.waits == []            # refused here: nothing was sent, and nothing waited
    assert http.json("https://codeberg.org/api/x") == {"ok": True}       # the limit is that host's
    assert http.json("https://api.git.example.org/x") == {"ok": True}    # and not a host's whose name ends in its name
    clock.now += 119.5                                                   # until the time it gave, to the second
    with pytest.raises(RateLimited):
        http.json(ASKED)
    clock.now += 1
    assert http.json(ASKED) == {"ok": True} and len(seen) == 4


def test_a_time_to_come_back_that_has_gone_by_limits_nothing(clock):
    seen = []
    http = names(Http(opener=scripted([(429, {"Retry-After": Y2015_AS_A_DATE}, b""), OK], seen)))
    with pytest.raises(RateLimited):
        http.json(ASKED)
    assert http.json(ASKED) == {"ok": True} and len(seen) == 2


@pytest.mark.parametrize("call, kw, accept", [
    ("json", {}, "application/json"), ("json_with_headers", {}, "application/json"), ("request", {}, "application/json"),
    ("text", {}, "*/*"), ("bytes", {}, "*/*"),
    ("json", {"accept": "application/vnd.github+json"}, "application/vnd.github+json"),
    ("request", {"accept": "text/html"}, "text/html"),
])
def test_what_a_request_carries(clock, call, kw, accept):
    seen = []
    http = names(Http({"git.example.org": "SECRET"}, opener=scripted([OK], seen)))
    http.set_forge("git.example.org", "gitlab")
    getattr(http, call)(ASKED, **kw)
    (req,) = seen
    assert (req.full_url, req.get_method(), req.data) == (ASKED, "GET", None)
    assert {k.lower(): v for k, v in req.header_items()} == {
        "user-agent": http_.UA, "accept": accept, "private-token": "SECRET"}
    assert http_.UA.startswith("AppKata/") and "(+https://" in http_.UA
    assert dict(req.unredirected_hdrs) == {"Private-token": "SECRET"}       # the token: never a header a redirect copies


def test_a_request_with_a_method_a_body_and_headers_of_its_own(clock):
    seen = []
    http = names(Http(opener=scripted([OK], seen)))
    assert http.request(ASKED, method="POST", body=b'{"q": 1}', headers={"Content-Type": "application/json", "Accept": "text/plain"}) == (
        b'{"ok": true}', {}, ASKED)
    (req,) = seen
    assert (req.get_method(), req.data) == ("POST", b'{"q": 1}')
    assert {k.lower(): v for k, v in req.header_items()} == {"user-agent": http_.UA, "accept": "text/plain", "content-type": "application/json"}
    http.request(ASKED, method="HEAD")
    assert [r.get_method() for r in seen] == ["POST", "HEAD"]


def test_how_large_an_answer_may_be_and_how_long_a_request_is_given():
    # the numbers themselves: R9.2.1's two minutes, the 64 MiB of an answer and the 8 MiB of an image
    limits = inspect.signature(Http._request).parameters
    assert limits["max_bytes"].default == 64 << 20 == 67108864 and sync.MAX_IMAGE == 8 << 20
    made = inspect.signature(Http.__init__).parameters
    assert (made["timeout"].default, made["deadline"].default) == (20.0, 120.0) and http_.WAITS == (1.5, 3.0)


def test_an_image_larger_than_an_image_may_be_is_passed_over(tmp_path, clock):
    seen = []
    http = names(Http(opener=scripted([(200, {}, PNG + b"\0" * sync.MAX_IMAGE)], seen)))
    with pytest.raises(Unreachable, match="too large"):
        sync._save_image(http, "https://git.example.org/o/r/raw/branch/main/icon.png", str(tmp_path / "icon"), token_host="git.example.org")
    assert len(seen) == 1 and list(tmp_path.iterdir()) == []


# ---------------------------------------------------------------- what a Sync stores, and how it runs (R9.2, R9.2.1, R9.2.3, R3.2, R3.3)
# CR1's #293: the forges' parsers were tested, each on its own, and nothing called the function that
# joins them: no test ran sync_app or sync_all, so what a Sync stores for an app, the order it tries
# the images in, which apps it syncs, how many at a time and what Cancel does were held by nothing
# (#263, #266, #269 and #296 were all in there). The fixes of those brought a Sync's tests for
# their own fault: what it sends where, and that it survives whatever one app's sync ends in. These
# hold the rest, on one project that has everything a Sync reads, as GitHub, a GitLab and a Forgejo
# serve it: every column of the row, each image by which address it came from, and the Sync as a
# whole (the Trusts' apps, the forge type kept, four at a time, Cancel, the channels after it).
DESCRIPTION = "The forge's own description of Widget"
WIDGET_PATHS = [
    "README.md", "src/main.c", "data/org.acme.widget.metainfo.xml",
    "icon.png", "data/widget.png", "assets/logo-512.png", "assets/icon.svg", "fastlane/metadata/android/en-US/images/icon.png",
    "docs/screenshot-main.png", "docs/screenshot-other.png", "fastlane/metadata/android/en-US/images/featureGraphic.png",
    "docs/shot-two.png", "media/demo.png", "media/window.png",
]
WIDGET_METAINFO = """<?xml version="1.0" encoding="UTF-8"?>
<component type="desktop-application"><id>org.acme.widget</id><name>Widget Pro</name><summary>From the metainfo</summary>
<icon type="remote">https://cdn.example/widget-icon.png</icon>
<screenshots><screenshot type="default"><image>https://cdn.example/widget-shot.png</image></screenshot></screenshots>
</component>"""
WIDGET_README = ("# Widget\n\n[![build](https://img.shields.io/badge/build-passing-green.svg)](https://ci.example/acme/widget)\n\n"
                 "Widget turns your files into tidy little boxes, quickly and offline.\n\nIt has more to say further down.\n\n"
                 "![the window](media/window.png)\n\n<img src=\"https://cdn.example/readme.png\">\n\n"
                 "![a demo](media/demo.png)\n\n![shot](docs/shot-two.png)\n")
SUMMARY = "Widget turns your files into tidy little boxes, quickly and offline."
# R3.2 and R3.3, as addresses: the metainfo's first, then the repository's files, best first and at
# most four and two of them, then the owner's avatar for the icon and three of the README's images
# for the hero (a screenshot before another picture). The rest are never asked for.
ICON_FILES = ["fastlane/metadata/android/en-US/images/icon.png", "assets/icon.svg", "assets/logo-512.png", "data/widget.png"]
HERO_FILES = ["fastlane/metadata/android/en-US/images/featureGraphic.png", "docs/screenshot-main.png",
              "media/demo.png", "docs/shot-two.png", "media/window.png"]
NEVER_FILES = ["icon.png", "docs/screenshot-other.png"]
WIDGET_RELEASES = [      # as the forge lists them, in no order: (tag, name, date, marked a prerelease, files)
    ("v1.2.0", "1.2", "2026-03-01T00:00:00Z", False, ["widget-1.2.0-x86_64.AppImage", "widget-1.2.0.tar.gz"]),
    ("nightly", "Nightly build", "2026-06-01T00:00:00Z", False, ["widget-nightly-x86_64.AppImage"]),
    ("v1.10.0", "Widget 1.10", "2026-05-01T00:00:00Z", False, ["widget-1.10.0-x86_64.AppImage"]),
    ("v1.3.0-rc1", "", "2026-04-01T00:00:00Z", True, []),
]
STORED = [      # as a Sync keeps them, the newest first: (tag, name, version, prerelease); a tag that is no version is a prerelease
    ("nightly", "Nightly build", "nightly", True), ("v1.10.0", "Widget 1.10", "1.10.0", False),
    ("v1.3.0-rc1", "v1.3.0-rc1", "1.3.0-rc1", True), ("v1.2.0", "1.2", "1.2.0", False),
]
WIDGETS = {
    "github": dict(source="https://github.com/acme/widget", api="https://api.github.com/repos/acme/widget",
                   raw="https://raw.githubusercontent.com/acme/widget/trunk/", tree="/git/trees/trunk", tags="/tags",
                   avatar="https://avatars.githubusercontent.com/u/7", probe=None, file=dict(size=1234, digest=DIGEST, content_type="application/x-iso9660-appimage")),
    "gitlab": dict(source="https://git.example.org/acme/widget", api="https://git.example.org/api/v4/projects/acme%2Fwidget",
                   raw="https://git.example.org/acme/widget/-/raw/trunk/", tree="/repository/tree", tags="/repository/tags",
                   avatar="https://git.example.org/uploads/-/system/project/avatar/7/widget", probe="https://git.example.org/api/v4/projects?per_page=1",
                   file=dict(size=0, digest="", content_type="")),
    "forgejo": dict(source="https://code.example.net:3000/acme/widget", api="https://code.example.net:3000/api/v1/repos/acme/widget",
                    raw="https://code.example.net:3000/acme/widget/raw/branch/trunk/", tree="/git/trees/trunk", tags="/tags",
                    avatar="https://code.example.net:3000/avatars/7", probe="https://code.example.net:3000/api/v1/version",
                    file=dict(size=1234, digest="", content_type="")),
}
PROBE_ANSWERS = {"gitlab": [], "forgejo": {"version": "11.0.1+gitea-1.22.0"}}


def picture(address):
    """An image that says which address it came from, so what was kept can be read from the file."""
    if address.endswith(".svg"):
        return b'<svg xmlns="http://www.w3.org/2000/svg"><!-- ' + address.encode() + b" --></svg>"
    return PNG + address.encode()


def longest_first(routes):
    return dict(sorted(routes.items(), key=lambda kv: -len(kv[0])))      # opener() takes the first prefix


def widget(forge, paths=WIDGET_PATHS, **info):
    """The Widget project as this forge serves it: its Source, its routes, and the addresses of its
    images in the order R3.2 and R3.3 give."""
    w = types.SimpleNamespace(kind=forge, **WIDGETS[forge])
    w.host = urls.parse(w.source).host
    w.info = {"name": "widget", "full_name": "acme/widget", "path_with_namespace": "acme/widget", "description": DESCRIPTION,
              "default_branch": "trunk", "avatar_url": w.avatar, "owner": {"avatar_url": w.avatar}, "html_url": w.source,
              "web_url": w.source, "archived": True, **info}
    w.releases = []
    for tag, name, date, pre, files in WIDGET_RELEASES:
        links = [(f, f"{w.source}/releases/download/{tag}/{f}") for f in files]
        page = f"{w.source}/releases/tag/{tag}"
        if forge == "gitlab":
            w.releases.append({"tag_name": tag, "name": name, "released_at": date, "upcoming_release": pre, "description": f"Notes of {tag}",
                               "_links": {"self": page}, "assets": {"links": [{"name": f, "direct_asset_url": u} for f, u in links]}})
        else:
            w.releases.append({"tag_name": tag, "name": name, "published_at": date, "prerelease": pre, "draft": False,
                               "body": f"Notes of {tag}", "html_url": page,
                               "assets": [{"name": f, "browser_download_url": u, "size": 1234, "digest": DIGEST,
                                           "content_type": "application/x-iso9660-appimage"} for f, u in links]})
    if forge != "gitlab":
        w.releases.insert(1, {"tag_name": "v2.0.0", "name": "Not out yet", "published_at": "2026-07-01T00:00:00Z", "draft": True, "assets": []})
    blobs = [{"path": p, "type": "blob"} for p in paths] + [{"path": "docs", "type": "tree"}]
    w.icons = ["https://cdn.example/widget-icon.png"] + [w.raw + p for p in ICON_FILES] + [w.avatar]
    w.heroes = ["https://cdn.example/widget-shot.png"] + [w.raw + p for p in HERO_FILES]
    w.never = [w.raw + p for p in NEVER_FILES] + ["https://cdn.example/readme.png"]
    files = {"README.md": WIDGET_README.encode(), "data/org.acme.widget.metainfo.xml": WIDGET_METAINFO.encode(), "src/main.c": b"int main;"}
    w.routes = {w.api: w.info, w.api + "/releases": w.releases, w.api + w.tree: blobs if forge == "gitlab" else {"tree": blobs},
                **{w.raw + p: files.get(p) or picture(w.raw + p) for p in paths},
                **{u: picture(u) for u in ("https://cdn.example/widget-icon.png", "https://cdn.example/widget-shot.png",
                                           "https://cdn.example/readme.png", w.avatar)}}
    if w.probe:
        w.routes[w.probe] = PROBE_ANSWERS[forge]
    return w


def sync_of(tmp_path, monkeypatch, w, routes=None, seen=None, db=None, **kw):
    """A whole Sync of the Catalog over these routes. Returns the database and what was asked for, in order."""
    seen = [] if seen is None else seen
    db = db or catalog(tmp_path, monkeypatch, [w.source])
    http = names(Http({}, opener=recording(longest_first(w.routes if routes is None else routes), seen)))
    sync.sync_all(db, http, root=str(tmp_path), **kw)
    return db, [url for url, _ in seen]


def kept(tmp_path, app, which):
    """The image file a row names, or None where it names none."""
    if not app[which]:
        return None
    assert not os.path.isabs(app[which]) and os.path.basename(os.path.dirname(app[which])) == os.path.basename(sync.cache_dir(app["url"], str(tmp_path)))
    with open(os.path.join(str(tmp_path), app[which]), "rb") as f:
        return f.read()


@pytest.mark.parametrize("forge", sorted(WIDGETS))
def test_what_a_sync_stores_for_an_app(tmp_path, monkeypatch, forge):
    w = widget(forge)
    before = now()
    db, asked = sync_of(tmp_path, monkeypatch, w)
    app = rows(db)[w.source]
    assert {k: app[k] for k in ("name", "description", "summary", "readme", "raw_base", "forge", "host", "repo", "archived", "error",
                                "error_code", "error_extra")} == {
        "name": "Widget Pro",                                   # the metainfo's, before the repository's
        "description": DESCRIPTION, "summary": SUMMARY,         # R3.4.1: the README's first prose, before the metainfo's and the forge's
        "readme": WIDGET_README, "raw_base": w.raw.rstrip("/"), "forge": forge, "host": w.host, "repo": "acme/widget", "archived": 1,
        "error": None, "error_code": None, "error_extra": "{}"}
    assert before <= app["fetched_at"] <= now()
    assert kept(tmp_path, app, "icon") == picture(w.icons[0]) and kept(tmp_path, app, "hero") == picture(w.heroes[0])
    assert os.path.basename(app["icon"]) == "icon.png" and os.path.basename(app["hero"]) == "hero.png"
    stored = json.loads(app["releases"])
    assert [(r["tag"], r["name"], r["version"], r["prerelease"]) for r in stored] == STORED        # no draft among them
    by_tag = {tag: (date, files) for tag, _, date, _, files in WIDGET_RELEASES}
    for r in stored:
        date, files = by_tag[r["tag"]]
        assert r == {"tag": r["tag"], "name": r["name"], "version": r["version"], "prerelease": r["prerelease"], "date": date,
                     "notes": f"Notes of {r['tag']}", "html_url": f"{w.source}/releases/tag/{r['tag']}",
                     "assets": [{"name": f, "url": f"{w.source}/releases/download/{r['tag']}/{f}", **w.file} for f in files]}
    assert db.one("SELECT forge FROM sources WHERE url=?", (w.source,))["forge"] == forge        # found once, kept for the next Sync
    assert db.one("SELECT appstream_id FROM app_meta WHERE url=?", (w.source,))["appstream_id"] == "org.acme.widget"
    assert db.get("last_sync") >= before
    assert len(asked) == len(set(asked))                        # and nothing was asked for twice


@pytest.mark.parametrize("forge", sorted(WIDGETS))
def test_the_images_are_tried_in_r3_2s_and_r3_3s_order_and_no_others(tmp_path, monkeypatch, forge):
    """Every image address answers 404: each is asked for once, in the order of the two lists, then
    the app is stored without an icon or a hero, and with no error. The files past the fourth icon,
    the second hero and the third README image are never asked for."""
    w = widget(forge)
    images = w.icons + w.heroes + w.never
    db, asked = sync_of(tmp_path, monkeypatch, w, {k: v for k, v in w.routes.items() if k not in images})
    assert [url for url in asked if url in images] == w.icons + w.heroes
    app = rows(db)[w.source]
    assert (app["error_code"], app["icon"], app["hero"], app["name"]) == (None, "", "", "Widget Pro")


@pytest.mark.parametrize("forge", sorted(WIDGETS))
@pytest.mark.parametrize("which, n", [(which, n) for which in ("icon", "hero") for n in range(6)])
def test_the_first_image_that_answers_is_the_one_kept(tmp_path, monkeypatch, forge, which, n):
    """The first n addresses of R3.2's list, or of R3.3's, give no image, each in another way: the next one is kept, and none after it is asked for."""
    w = widget(forge)
    wanted = w.icons if which == "icon" else w.heroes
    no_image = [_status(404), _status(500), urllib.error.URLError(OSError(111, "Connection refused")), b"x" * (sync.MAX_IMAGE + 1)]
    db, asked = sync_of(tmp_path, monkeypatch, w, {**w.routes, **{url: no_image[i % len(no_image)] for i, url in enumerate(wanted[:n])}})
    app = rows(db)[w.source]
    assert app["error_code"] is None and kept(tmp_path, app, which) == picture(wanted[n])
    assert [url for url in asked if url in wanted] == wanted[:n + 1]
    other = "hero" if which == "icon" else "icon"
    assert kept(tmp_path, app, other) == picture((w.heroes if which == "icon" else w.icons)[0])


def test_an_app_keeps_the_icon_it_had_when_none_answers(tmp_path, monkeypatch):
    w = widget("forgejo")
    db, _ = sync_of(tmp_path, monkeypatch, w)
    first = rows(db)[w.source]
    db, asked = sync_of(tmp_path, monkeypatch, w, {k: v for k, v in w.routes.items() if k not in w.icons}, db=db)
    app = rows(db)[w.source]
    assert [url for url in asked if url in w.icons] == w.icons
    assert app["error_code"] is None and app["icon"] == first["icon"] and kept(tmp_path, app, "icon") == picture(w.icons[0])


@pytest.mark.parametrize("forge", sorted(WIDGETS))
def test_a_project_that_says_nothing_of_itself_is_stored_as_its_forge_describes_it(tmp_path, monkeypatch, forge):
    # no README, no metainfo, no image in the repository: the forge's name and description, and the owner's avatar
    w = widget(forge, paths=["src/main.c"])
    db, asked = sync_of(tmp_path, monkeypatch, w)
    app = rows(db)[w.source]
    assert (app["error_code"], app["name"], app["summary"], app["readme"], app["hero"]) == (None, "widget", DESCRIPTION, "", "")
    assert kept(tmp_path, app, "icon") == picture(w.avatar)
    assert db.one("SELECT appstream_id FROM app_meta WHERE url=?", (w.source,)) is None
    assert [url for url in asked if url.startswith(w.raw)] == []


def test_a_metainfo_whose_name_is_a_placeholder_leaves_the_forges_name(tmp_path, monkeypatch):
    w = widget("gitlab")
    w.routes[w.raw + "data/org.acme.widget.metainfo.xml"] = WIDGET_METAINFO.replace("Widget Pro", "@@APP_NAME@@").encode()
    db, _ = sync_of(tmp_path, monkeypatch, w)
    assert rows(db)[w.source]["name"] == "widget" and rows(db)[w.source]["summary"] == SUMMARY


@pytest.mark.parametrize("forge", sorted(WIDGETS))
def test_a_project_that_moved_has_where_to_on_its_row(tmp_path, monkeypatch, forge):
    w = widget(forge, full_name="acme/gadget", path_with_namespace="acme/gadget",
               html_url=WIDGETS[forge]["source"].replace("widget", "gadget"), web_url=WIDGETS[forge]["source"].replace("widget", "gadget"))
    db, asked = sync_of(tmp_path, monkeypatch, w)
    app = rows(db)[w.source]
    assert app["error_code"] == "Renamed" and json.loads(app["error_extra"]) == {"new_url": w.source.replace("widget", "gadget")}
    assert asked[-1] == w.api and asked.count(w.api) == 1                  # and nothing more is read under the old name


@pytest.mark.parametrize("forge", sorted(WIDGETS))
@pytest.mark.parametrize("track_only", [True, False])
def test_tags_stand_in_for_releases_only_where_the_source_tracks_them(tmp_path, monkeypatch, forge, track_only):
    w = widget(forge)
    w.routes[w.api + "/releases"] = []
    w.routes[w.api + w.tags] = [{"name": "v1.2.0", "commit": {"created": "2026-03-01T00:00:00Z", "created_at": "2026-03-01T00:00:00Z"}},
                                {"name": "v1.3.0", "commit": {"created": "2026-04-01T00:00:00Z", "created_at": "2026-04-01T00:00:00Z"}}]
    db = catalog(tmp_path, monkeypatch, [w.source])
    db.x("UPDATE sources SET settings=? WHERE url=?", (json.dumps({"track_only": track_only}), w.source))
    db, asked = sync_of(tmp_path, monkeypatch, w, db=db)
    app = rows(db)[w.source]
    assert app["error_code"] is None and (w.api + w.tags in [url.split("?")[0] for url in asked]) == track_only
    assert sorted((r["tag"], r["version"], r["assets"]) for r in json.loads(app["releases"])) == (
        [("v1.2.0", "1.2.0", []), ("v1.3.0", "1.3.0", [])] if track_only else [])


# ---- which forge type a Sync takes a host for (R2.4.2, R2.6.5, R10.3.1)
def own_reviews(tmp_path, db, *listed, settings=""):
    """The user's own review file, which lists these apps: a Trust that is always applied."""
    path = tmp_path / "AppKata.md"
    table = "".join(f"| App {n} | {url} | foss | 4 | 4 |\n" for n, url in enumerate(listed, 1))
    path.write_text("# Mine\n\n| App | Source | Tags | Trust | Rating |\n|---|---|---|---|---|\n" + table + settings, encoding="utf-8")
    return sync.own_trust(db, str(path))


def test_a_hosts_forge_type_is_found_once_and_kept_for_the_next_sync(tmp_path, monkeypatch):
    w = widget("forgejo")
    db, asked = sync_of(tmp_path, monkeypatch, w)
    assert asked[0] == w.probe and asked.count(w.probe) == 1
    db, asked = sync_of(tmp_path, monkeypatch, w, db=db)
    assert w.probe not in asked and asked[0] == w.api and rows(db)[w.source]["error_code"] is None


def test_an_app_a_trust_lists_keeps_the_forge_type_found_for_it_too(tmp_path, monkeypatch):
    # it has no Source to keep the type on: its own row does
    w = widget("gitlab")
    db = catalog(tmp_path, monkeypatch, [])
    own_reviews(tmp_path, db, w.source)
    db, asked = sync_of(tmp_path, monkeypatch, w, db=db)
    assert asked.count(w.probe) == 1 and rows(db)[w.source]["forge"] == "gitlab"
    db, asked = sync_of(tmp_path, monkeypatch, w, db=db)
    assert w.probe not in asked and rows(db)[w.source]["error_code"] is None


@pytest.mark.parametrize("own, trusts, kept_on_source, taken_for", [
    ("forgejo", "gitlab", "gitlab", "forgejo"),          # the Source's own setting first (R2.6.5)
    (None, "forgejo", "gitlab", "forgejo"),              # then what a Trust recommends (R10.3.1)
    (None, None, "forgejo", "forgejo"),                  # then what an earlier Sync found
])
def test_the_forge_type_is_the_sources_setting_then_a_trusts_then_the_one_found(tmp_path, monkeypatch, own, trusts, kept_on_source, taken_for):
    """A Forgejo on a host whose name says GitLab, and no probe that answers: each way the type is known without asking."""
    w = widget("forgejo")
    source = "https://gitlab.example.org/acme/widget"
    routes = {k.replace("https://code.example.net:3000/", "https://gitlab.example.org/"): v for k, v in w.routes.items() if k != w.probe}
    db = catalog(tmp_path, monkeypatch, [source])
    db.x("UPDATE sources SET settings=?, forge=? WHERE url=?", (json.dumps({"forge": own} if own else {}), kept_on_source, source))
    if trusts:
        own_reviews(tmp_path, db, source, settings=f"\n# App 1\n\nFine.\n\n## App 1::Settings\n\n- Forge: {forges.LABELS[trusts]}\n")
    w.source = source
    db, asked = sync_of(tmp_path, monkeypatch, w, routes, db=db)
    app = rows(db)[source]
    assert (app["error_code"], app["forge"], app["name"]) == (None, taken_for, "Widget Pro"), app["error"]
    assert asked[0] == "https://gitlab.example.org/api/v1/repos/acme/widget"
    assert db.one("SELECT forge FROM sources WHERE url=?", (source,))["forge"] == kept_on_source


# ---- which apps a Sync syncs, and how it runs (R9.2, R9.2.1, R9.2.3)
def test_a_sync_reads_the_trusts_first_and_syncs_every_app_of_the_catalog_once(tmp_path, monkeypatch):
    """R9.2.3: a Source, an app only a Trust lists, and one that is both; an app only a disabled
    Trust lists is left out. The user's own review file is read by this very Sync, before its apps."""
    github, gitlab, forgejo = widget("github"), widget("gitlab"), widget("forgejo")
    left_out = "https://codeberg.org/acme/left-out"
    db = catalog(tmp_path, monkeypatch, [gitlab.source, forgejo.source])
    own_reviews(tmp_path, db, github.source, forgejo.source)
    off = db.x("INSERT INTO trusts(url, name, path, enabled, added_at) VALUES(?,?,?,0,?)",
               ("https://example.org/reviews", "Switched off", "AppKata.md", now())).lastrowid
    db.x("INSERT INTO reviews(trust_id, url, app) VALUES(?,?,?)", (off, left_out, "Left out"))
    assert db.all("SELECT url FROM reviews WHERE trust_id!=?", (off,)) == []          # the file hasn't been read yet
    progress, items, seen = sync.Progress(), [], []
    http = names(Http({}, opener=recording(longest_first({**github.routes, **gitlab.routes, **forgejo.routes}), seen)))
    sync.sync_all(db, http, progress, root=str(tmp_path), on_item=lambda: items.append((progress.done, progress.total)))
    apps = rows(db)
    assert sorted(apps) == sorted([github.source, gitlab.source, forgejo.source])
    assert all(app["error_code"] is None and app["name"] == "Widget Pro" for app in apps.values())
    assert [url for url, _ in seen if "left-out" in url] == []
    assert [[url for url, _ in seen].count(w.api) for w in (github, gitlab, forgejo)] == [1, 1, 1]       # the one that is both, once
    assert (progress.done, progress.total) == (4, 4)            # the Trust, then the three apps
    assert items[0] == (1, 1) and sorted(items[1:]) == [(2, 4), (3, 4), (4, 4)]
    assert db.one("SELECT synced_at FROM trusts WHERE own=1")["synced_at"] and db.get("last_sync")


@pytest.mark.parametrize("workers", [None, 2, 1])
def test_at_most_four_apps_are_fetched_at_the_same_time(tmp_path, monkeypatch, workers):
    """R9.2.1. Eight Sources on eight hosts. The first requests wait for one another: that as many as
    are allowed do run together is certain, and a request more than that is seen if it ever starts."""
    allowed = workers or 4
    sources = [f"https://forge{i}.example.org/acme/widget" for i in range(8)]
    db = catalog(tmp_path, monkeypatch, sources)
    db.x("UPDATE sources SET forge='forgejo'")
    together, lock, state = threading.Barrier(allowed, timeout=10), threading.Lock(), {"now": 0, "most": 0, "met": False}

    def open_(req, timeout=0):
        with lock:
            state["now"] += 1
            state["most"] = max(state["most"], state["now"])
            first = not state["met"]
        try:
            if first:
                together.wait()                               # until `allowed` requests are under way at once
                state["met"] = True
            time.sleep(0.002)
            raise urllib.error.HTTPError(req.full_url, 404, "nf", {}, None)
        finally:
            with lock:
                state["now"] -= 1
    sync.sync_all(db, names(Http({}, opener=open_)), root=str(tmp_path), **({"workers": workers} if workers else {}))
    assert state["met"] and state["most"] == allowed
    assert sorted(rows(db)) == sorted(sources) and all(app["error_code"] == "NotFound" for app in rows(db).values())


def test_a_sync_cancelled_before_it_starts_asks_for_nothing(tmp_path, monkeypatch):
    w, seen, after = widget("forgejo"), [], []
    monkeypatch.setattr(sync, "sync_channels", lambda db, http: after.append("channels"))
    for with_a_trust in (False, True):
        folder = tmp_path / ("with-a-trust" if with_a_trust else "without")
        folder.mkdir()
        db = catalog(folder, monkeypatch, [w.source])
        if with_a_trust:
            own_reviews(folder, db, widget("gitlab").source)
        progress = sync.Progress(cancelled=True)
        sync.sync_all(db, names(Http({}, opener=recording(longest_first(w.routes), seen))), progress, root=str(folder))
        assert seen == [] and rows(db) == {} and after == [] and progress.done == 0
        assert db.all("SELECT * FROM reviews") == []           # nor was the Trust read


def test_a_sync_cancelled_between_two_apps_leaves_the_rest_as_they_were(tmp_path, monkeypatch):
    widgets = [widget("github"), widget("gitlab"), widget("forgejo")]
    seen, after = [], []
    monkeypatch.setattr(sync, "sync_channels", lambda db, http: after.append("channels"))
    db = catalog(tmp_path, monkeypatch, [w.source for w in widgets] + ["nostr://naddr1widget"])     # one whose sync asks for nothing
    progress = sync.Progress()
    http = names(Http({}, opener=recording(longest_first({k: v for w in widgets for k, v in w.routes.items()}), seen)))
    sync.sync_all(db, http, progress, root=str(tmp_path), workers=1, on_item=lambda: setattr(progress, "cancelled", True))
    (done,) = rows(db).values()                                # the one app that was synced before the Cancel, whole
    assert done["error_code"] is None and done["name"] == "Widget Pro"
    assert (progress.done, progress.total) == (1, 4) and after == []          # nor are the package channels read
    assert [url for url, _ in seen if url.startswith(tuple(w.api for w in widgets if w.source != done["url"]))] == []


def test_the_package_channels_are_read_once_after_the_apps_and_never_end_a_sync(tmp_path, monkeypatch):
    w, after = widget("forgejo"), []
    db = catalog(tmp_path, monkeypatch, [w.source])
    monkeypatch.setattr(sync, "sync_channels", lambda db_, http_: after.append(sorted(rows(db_))))
    sync_of(tmp_path, monkeypatch, w, db=db)
    assert after == [[w.source]]                               # the apps were stored by then
    monkeypatch.undo()

    def fails(db_, http_=None):
        raise RuntimeError("the package manager isn't answering")
    monkeypatch.setattr(channels, "enabled", lambda: True)
    monkeypatch.setattr(sync, "track_channel_installs", fails)
    monkeypatch.setattr(sync, "check_links", fails)
    from appkata_core import autoupdate
    monkeypatch.setattr(autoupdate, "detect", fails)
    db.put("last_sync", "")
    sync.sync_all(db, names(Http({}, opener=opener(longest_first(w.routes)))), root=str(tmp_path))
    assert db.get("last_sync") and rows(db)[w.source]["error_code"] is None


def test_a_source_that_is_no_forges_project_has_that_on_its_row(tmp_path, monkeypatch):
    db = catalog(tmp_path, monkeypatch, ["nostr://naddr1widget"])
    sync.sync_all(db, names(Http({}, opener=opener({}))), root=str(tmp_path))
    app = rows(db)["nostr://naddr1widget"]
    assert app["error_code"] == "Unsupported" and "ngit" in app["error"]


# ---- each probe of forges.detect (R2.4.2)
P1, P2, P3, P4 = ("https://git.example.org/api/v1/version", "https://git.example.org/api/v4/projects?per_page=1",
                  "https://git.example.org/api/v3/meta", "https://git.example.org/")


@pytest.mark.parametrize("answers, kind", [
    ({P1: {"version": "1.22.0"}}, "gitea"),
    ({P1: {"version": "11.0.1+gitea-1.22.0"}}, "forgejo"),                       # Forgejo, as it gives its version
    ({P1: {"version": "9.0.3", "name": "Forgejo"}}, "forgejo"),
    ({P1: {"message": "no version here"}, P2: []}, "gitlab"),                    # the first isn't a Gitea's answer: the next is asked
    ({P1: ["a", "list"], P2: [{"id": 7, "path_with_namespace": "o/r"}]}, "gitlab"),
    ({P2: {"message": "401 Unauthorized"}, P3: {"installed_version": "3.14.0"}}, "ghe"),
    ({P3: {"verifiable_password_authentication": False}}, "ghe"),
    ({P3: {"message": "another API"}, P4: b'<html><head><meta name="generator" content="Forgejo"></head>'}, "forgejo"),
    ({P4: b'<META NAME="generator" CONTENT="Gitea - Git with a cup of tea">'}, "gitea"),
    ({P4: b'<meta content="GitLab" property="og:site_name">'}, "gitlab"),
    ({P4: b'<meta property="og:site_name" content="GitLab">'}, "gitlab"),
    ({P4: b"<html>A page that says nothing</html>"}, None),
    ({}, None),
])
def test_each_probe_of_a_hosts_forge_type_in_its_order(clock, answers, kind):
    """R2.4.2: the probes are asked in their order, each is passed over unless its answer is that
    forge's own, and the first that is ends the asking."""
    seen = []
    http = names(Http(opener=recording(longest_first(answers), seen)))
    if kind is None:
        with pytest.raises(forges.Unsupported, match="couldn't tell which forge git.example.org runs; set the forge type in Source settings"):
            forges.detect(http, "git.example.org")
        assert [url for url, _ in seen] == [P1, P2, P3, P4]
    else:
        assert forges.detect(http, "git.example.org") == kind
        last = [p for p in (P1, P2, P3, P4) if p in answers][-1]
        assert [url for url, _ in seen] == [P1, P2, P3, P4][:[P1, P2, P3, P4].index(last) + 1]
    assert clock.waits == [] and all("authorization" not in h and "private-token" not in h for _, h in seen)


@pytest.mark.parametrize("host", sorted(forges.KNOWN))
def test_a_host_appkata_knows_is_never_probed(host):
    seen = []
    http = names(Http(opener=recording({}, seen)))
    assert forges.detect(http, host) == forges.KNOWN[host] and forges.KNOWN[host] in forges.LABELS
    assert forges.forge_for(http, urls.parse(f"https://{host}/o/r")).label == forges.LABELS[forges.KNOWN[host]] and seen == []


# ---- github.com's own pages and git, the whole way (R2.4.1)
def test_a_whole_sync_of_a_github_project_by_its_pages_and_git(tmp_path, monkeypatch):
    """The API's limit is used up, so nothing is asked of it: the project's page, the releases feed,
    each release's files with their digests, and git for the default branch and the file list."""
    w = widget("github")
    web = "https://github.com/acme/widget"
    asked_of_git = []

    def git_out(args):
        asked_of_git.append(args)
        if args[:2] == ["ls-remote", "--symref"]:
            return "ref: refs/heads/trunk\tHEAD\n8a1f3c\tHEAD\n"
        if args[0] == "-C" and "ls-tree" in args:
            return "\n".join(WIDGET_PATHS) + "\n"
        return ""
    monkeypatch.setattr(forges, "_git_out", git_out)
    entry = ('<entry><updated>{d}</updated><link rel="alternate" href="' + web + '/releases/tag/{t}"/><title>{n}</title>'
             '<content type="html">&lt;p&gt;Notes of {t}&lt;/p&gt;</content></entry>')
    feed = '<feed xmlns="http://www.w3.org/2005/Atom">' + "".join(
        entry.format(t=tag, n=name or tag, d=date.replace("T00:00", "T09:30")) for tag, name, date, _, _ in WIDGET_RELEASES) + "</feed>"
    label = '<span class="Label Label--warning Label--large">Pre-release</span>'
    listing = "".join(f'<a href="/acme/widget/releases/tag/{tag}">{name}</a>{label if pre else ""}' for tag, name, _, pre, _ in WIDGET_RELEASES)
    routes = {k: v for k, v in w.routes.items() if not k.startswith("https://api.github.com/")}
    routes.update({
        web: (f'<html><head><meta name="description" content="{DESCRIPTION} - acme/widget"></head>'
              "<p>This repository has been archived by the owner.</p></html>").encode(),
        web + "/releases.atom": feed.encode(), web + "/releases": listing.encode(),
        "https://github.com/acme.png?size=256": picture(w.avatar),
        **{f"{web}/releases/expanded_assets/{tag}": ("".join(
            f'<a href="/acme/widget/releases/download/{tag}/{f}">{f}</a><span>{DIGEST}</span><span>1.5 MB</span>' for f in files)
            + f'<relative-time datetime="{date}">').encode() for tag, _, date, _, files in WIDGET_RELEASES}})
    seen = []
    db = catalog(tmp_path, monkeypatch, [w.source])
    http = names(Http({}, opener=recording(longest_first(routes), seen)))
    http.limited["api.github.com"] = time.time() + 600
    sync.sync_all(db, http, root=str(tmp_path))
    app = rows(db)[w.source]
    assert (app["error_code"], app["name"], app["description"], app["summary"], app["archived"], app["raw_base"]) == (
        None, "Widget Pro", DESCRIPTION, SUMMARY, 1, w.raw.rstrip("/")), app["error"]
    assert [url for url, _ in seen if "api.github.com" in url] == []
    stored = json.loads(app["releases"])
    published = {tag: date if files else date.replace("T00:00", "T09:30") for tag, _, date, _, files in WIDGET_RELEASES}
    assert [(r["tag"], r["version"], r["prerelease"], r["date"]) for r in stored] == [      # a release's own date, where its files' page gave one
        (tag, version, pre, published[tag]) for tag, _, version, pre in STORED]
    assert {r["tag"]: r["assets"] for r in stored} == {
        tag: [{"name": f, "url": f"{web}/releases/download/{tag}/{f}", "size": 1500000, "digest": DIGEST, "content_type": ""} for f in files]
        for tag, _, _, _, files in WIDGET_RELEASES}
    assert stored[1]["notes"] == "Notes of v1.10.0"
    assert kept(tmp_path, app, "icon") == picture(w.icons[0]) and kept(tmp_path, app, "hero") == picture(w.heroes[0])
    assert [a[:2] for a in asked_of_git if a[0] == "ls-remote"] == [["ls-remote", "--symref"]]
    assert all(web in a for a in asked_of_git if a[0] in ("ls-remote", "clone"))       # git was given the project's own address, and no other


def test_by_the_pages_a_projects_tags_come_from_git_newest_version_first(monkeypatch):
    monkeypatch.setattr(forges, "_git_out", lambda args: "".join(f"{n:040x}\trefs/tags/{t}\n" for n, t in enumerate(
        ["v1.9.0", "v1.10.0", "v1.2.0", "v2.0.0-rc1"])))
    http = names(Http(opener=opener({})))
    http.limited["api.github.com"] = time.time() + 600
    tags = forges.forge_for(http, urls.parse("https://github.com/acme/widget"), "github").tags(limit=3)
    assert [(t.tag, t.version, t.date) for t in tags] == [("v2.0.0-rc1", "2.0.0-rc1", ""), ("v1.10.0", "1.10.0", ""), ("v1.9.0", "1.9.0", "")]


def test_by_the_pages_a_project_that_moved_is_renamed(monkeypatch):
    monkeypatch.setattr(forges, "_git_out", lambda args: "")
    http = names(Http(opener=lambda req, timeout=0: FakeResponse("https://github.com/acme/gadget", b"<html></html>")))
    http.limited["api.github.com"] = time.time() + 600
    with pytest.raises(forges.Renamed) as e:
        forges.forge_for(http, urls.parse("https://github.com/acme/widget"), "github").info()
    assert e.value.new_url == "https://github.com/acme/gadget"


# ---------------------------------------------------------------- whose answer an error is, after a redirect (R2.10, R9.2.2)
# CR1's #683: Http named the host it asked first in every error, and called a 401 the token's
# whenever the first address had carried one. Since a redirect to another host goes on without the
# token (#264), a 401 can come from a host that was sent none: the row said the first host had
# rejected the user's API token, and sent them to Settings to replace a token that was fine. How it
# slipped past: a stand-in opener never redirects, and the tests of a redirect looked at what was
# sent, not at what an error said. The class is "an answer after a redirect is taken for the first
# host's", so each failing answer here comes from the last of two or three hosts' hops, through
# Http's own opener, and its error is held to that host and to what that host was sent.
def saying(status):
    def answer(handler):
        handler.wfile.write(f"HTTP/1.1 {status} Said\r\nContent-Length: 0\r\n\r\n".encode())
    return answer


@pytest.mark.parametrize("path, status, says", [
    ("/direct", 401, "127.0.0.1 rejected the API token (HTTP 401)"),              # the token's own host, asked first
    ("/moved-on-the-host", 401, "127.0.0.1 rejected the API token (HTTP 401)"),   # a redirect on the host keeps the token: still the token's
    ("/to-another-host", 401, "localhost answered HTTP 401"),                     # the finding: that host was sent no token
    ("/there-and-back", 401, "127.0.0.1 answered HTTP 401"),                      # back on the first host, without the token it lost on the way
    ("/to-another-host", 403, "localhost answered HTTP 403"),
    ("/to-another-host", 500, "localhost answered HTTP 500"),
    ("/direct", 500, "127.0.0.1 answered HTTP 500"),
], ids=["direct-401", "moved-on-the-host-401", "to-another-host-401", "there-and-back-401", "to-another-host-403", "to-another-host-500",
        "direct-500"])
def test_through_real_sockets_an_error_after_a_redirect_is_the_last_hosts_and_the_tokens_only_if_it_went_there(pair, clock, path, status, says):
    a, b = pair
    a.redirects.update({"/moved-on-the-host": "/api/new", "/to-another-host": f"https://{b.at}/elsewhere", "/there-and-back": f"https://{b.at}/back"})
    b.redirects["/back"] = f"https://{a.at}/again"
    a.files = {p: saying(status) for p in ("/direct", "/api/new", "/again")}
    b.files = {"/elsewhere": saying(status)}
    http = names(Http({a.at: "SECRET-TOKEN", b.at: "ANOTHER-HOSTS"}, timeout=10))       # B's own token isn't sent on a redirect to B either
    with pytest.raises(Unreachable) as e:
        http.json(f"https://{a.at}{path}")
    assert str(e.value) == says and e.value.extra == ({"status": status} if "answered" in says else {})
    last = (b if "localhost" in says else a).seen[-1]
    assert ("authorization" in last[1]) == ("rejected the API token" in says or path == "/direct")      # what the answering host was sent
    assert [k for _, h in b.seen for k in h if k in http_.TOKEN_HEADERS] == []


def test_a_401_with_no_token_sent_is_never_the_tokens(pair, clock):
    a, b = pair
    a.files = {"/direct": saying(401)}
    for tokens in ({}, {b.at: "ANOTHER-HOSTS"}, {"127.0.0.1": "ITS-DEFAULT-PORT"}):
        with pytest.raises(Unreachable, match="^127.0.0.1 answered HTTP 401$"):
            names(Http(tokens, timeout=10)).json(f"https://{a.at}/direct")
    assert _secrets(a.seen) == [] and len(a.seen) == 3


@pytest.fixture
def zone(monkeypatch):
    """Sets this process's time zone, where the platform lets a process set its own, and puts it back."""
    def set_(name):
        if hasattr(time, "tzset"):
            monkeypatch.setenv("TZ", name)
            time.tzset()
    yield set_
    monkeypatch.undo()
    if hasattr(time, "tzset"):
        time.tzset()


@pytest.mark.parametrize("tz", ["UTC", "Asia/Tokyo", "Pacific/Kiritimati", "America/Chicago", "Pacific/Pago_Pago"])
@pytest.mark.parametrize("headers", [
    {"retry-after": "Fri, 31 Dec 9999 23:59:59 GMT"},          # the year 10000 east of Greenwich, which no clock there shows
    {"retry-after": "Fri, 31 Dec 9999 00:00:00 GMT"}, {"retry-after": "Thu, 01 Jan 1970 00:00:00 GMT"},
    {"retry-after": "Mon, 01 Jan 0001 00:00:00 GMT"}, {"retry-after": "253402300800"}, {"x-ratelimit-reset": "253402300799"},
    {"x-ratelimit-reset": "253402300800"}, {"retry-after": "9" * 12}, {"retry-after": Y2100_AS_A_DATE}, {},
], ids=lambda h: "-".join(h.values()).replace(" ", "_") or "nothing")
def test_whatever_a_host_says_and_wherever_the_clock_is_the_time_to_come_back_is_one_a_clock_shows(zone, tz, headers):
    import datetime
    zone(tz)
    at = http_._reset_time(headers)
    assert datetime.datetime.fromtimestamp(at).strftime("%H:%M")           # as a Source's row shows it
    if headers == {"retry-after": Y2100_AS_A_DATE}:
        assert at == Y2100


def test_a_time_no_clock_can_show_never_reaches_a_sources_row(tmp_path, monkeypatch, clock):
    """Found beside #683: a host's Retry-After of thirty nines was kept as the time to come back,
    which the Sources list then failed to show. Whatever a host says, what a Sync writes is a time."""
    import datetime
    source = "https://git.example.org/o/r"
    for said in ({"Retry-After": "9" * 30}, {"x-ratelimit-reset": "9" * 17}, {"x-ratelimit-reset": "9" * 400}, {"Retry-After": "\u00b2"}):
        db = catalog(tmp_path, monkeypatch, [source])
        sync.sync_all(db, names(Http(opener=answering(429, said, []))), root=str(tmp_path))
        app = rows(db)[source]
        assert app["error_code"] == "RateLimited" and json.loads(app["error_extra"])["reset"] == clock.now + 60
        assert datetime.datetime.fromtimestamp(json.loads(app["error_extra"])["reset"])
        db.x("DELETE FROM sources")
        db.x("DELETE FROM apps")


# ---------------------------------------------------------------- a README's link to a file's page on github.com (R3.4)
# CR1's #681: metadata.resolve turns a link to a file's page on github.com into the address of the
# file itself, and it knew such a link by its text: "github.com/" and "/blob/" anywhere in it. An
# address on another host that held both, in its host's name or in a query, was rewritten into one
# its README never named. How it slipped past: resolve was tested for a relative path alone. The
# class is "an address read as text", so the two pieces of text are put in every part of an address
# here, and only github.com's own page of a file is turned into anything.
RAW = "https://raw.githubusercontent.com/o/r/main"


@pytest.mark.parametrize("url", [
    "https://notgithub.com/o/r/blob/main/shot.png",                       # the finding's: ends in the same letters
    "https://other.example/x?u=github.com/o/r/blob/main/shot.png",        # the finding's: in its query
    "https://github.com.evil.example/o/r/blob/main/shot.png", "https://evil.example/github.com/o/r/blob/main/shot.png",
    "https://github.com@evil.example/o/r/blob/main/shot.png",             # the host is evil.example
    "https://evil.example/shot.png#github.com/o/r/blob/main/shot.png",
    "https://gist.github.com/o/r/blob/main/shot.png", "https://raw.github.com/o/r/blob/main/shot.png",       # GitHub's, and no page of a file
    "https://github.com:8443/o/r/blob/main/shot.png",                     # another port is another host (R9.2.2)
    "https://github.com/o/r/raw/main/shot.png", "https://github.com/o/r/tree/main/blob/shot.png",            # github.com, and no page of a file
    "https://github.com/o/blob/shot.png", "https://github.com/blob/main/shot.png", "https://github.com/o/r/blob/",
    "https://raw.githubusercontent.com/o/r/main/blob/shot.png",
    "ftp://github.com/o/r/blob/main/shot.png", "data:image/png;base64,github.com/o/r/blob/main/shot.png",
    "http://[github.com/o/r/blob/main/shot.png",                          # no address at all: as it was written
])
def test_an_address_that_is_no_github_page_of_a_file_is_asked_for_as_its_readme_wrote_it(url):
    assert metadata.resolve(url, RAW, "docs") == url


@pytest.mark.parametrize("url, becomes", [
    ("https://github.com/o/r/blob/main/shot.png", RAW + "/shot.png"),
    ("https://github.com/o/r/blob/main/docs/img/shot.png?raw=true#readme", RAW + "/docs/img/shot.png?raw=true#readme"),
    ("https://www.github.com/o/r/blob/main/shot.png", RAW + "/shot.png"),
    ("HTTPS://GitHub.com/o/r/blob/main/shot.png", RAW + "/shot.png"),
    ("https://github.com:443/o/r/blob/main/shot.png", RAW + "/shot.png"),
    ("http://github.com/o/r/blob/main/shot.png", "http://raw.githubusercontent.com/o/r/main/shot.png"),      # as it was: the scheme is the README's
    ("https://github.com/o/r/blob/release/blob/docs/blob/shot.png", "https://raw.githubusercontent.com/o/r/release/blob/docs/blob/shot.png"),
    ("https://github.com/o/r/blob/main/screen shot.png", RAW + "/screen%20shot.png"),
    ("https://github.com/o/r/blob/main/截图.png", RAW + "/%E6%88%AA%E5%9B%BE.png"),
])
def test_a_github_page_of_a_file_becomes_the_address_of_the_file(url, becomes):
    assert metadata.resolve(url, "https://code.example.net/o/r/raw/branch/main", "docs") == becomes


@pytest.mark.parametrize("url, sent", [
    ("https://cdn.example/a b.png", "https://cdn.example/a%20b.png"),
    ("https://cdn.example/docs/截图.png?v=ä 1#top", "https://cdn.example/docs/%E6%88%AA%E5%9B%BE.png?v=%C3%A4%201#top"),
    ("https://cdn.example/a%20b.png?x=1&y=a+b", "https://cdn.example/a%20b.png?x=1&y=a+b"),          # written quoted: left as it is
    ("https://user:pw@cdn.example:8443/a b.png", "https://user:pw@cdn.example:8443/a%20b.png"),
    ("HTTP://CDN.example/Shot.PNG", "HTTP://CDN.example/Shot.PNG"),                                   # nothing to quote: not a letter of it changes
])
def test_a_whole_address_is_written_as_an_address_can_be_sent_too(url, sent):
    assert metadata.resolve(url, RAW) == sent
    seen = []
    _ask(names(Http(opener=recording({}, seen))), metadata.resolve(url, RAW))
    assert [u for u, _ in seen] == [sent]                     # and Http asks for it, where it refused the address as written


def test_a_sync_asks_for_a_readmes_images_on_other_hosts_as_they_are_written(tmp_path, monkeypatch):
    w = widget("forgejo")
    theirs = ["https://notgithub.com/o/r/blob/main/demo-1.png", "https://other.example/demo.png?u=github.com/o/r/blob/main/x.png",
              "https://github.com/acme/widget/blob/trunk/media/demo-3.png"]
    readme = "# Widget\n\n" + "".join(f"![demo]({url})\n\n" for url in theirs)
    images = set(w.icons + w.heroes + w.never)
    routes = {**{k: v for k, v in w.routes.items() if k not in images}, w.raw + "README.md": readme.encode()}
    db, asked = sync_of(tmp_path, monkeypatch, w, routes)
    assert rows(db)[w.source]["error_code"] is None
    assert [url for url in asked if "demo" in url] == theirs[:2] + ["https://raw.githubusercontent.com/acme/widget/trunk/media/demo-3.png"]
    assert [url for url in asked if "notraw" in url or "u=raw." in url] == []


def garbage(handler):
    handler.wfile.write(b"\x16\x03\x01 this is no HTTP at all\r\n\r\n")


REDIRECTED_TO = {       # what the host a redirect led to does: the error's kind, and its words about that host
    "/not-found": (saying(404), http_.NotFound, "https://{b}/not-found not found"),
    "/cut-short": (cut_off(b'{"half": ', 1000), Unreachable, "localhost cut its answer short (9 of 1000 bytes)"),
    "/half-a-chunk": (half_a_chunk, Unreachable, "localhost cut its answer short"),
    "/garbage": (garbage, Unreachable, "couldn't read localhost's answer (BadStatusLine: "),
    "/not-json": (cut_off(b"<html>Sign in</html>", 20), Unreachable, "localhost didn't return JSON"),
    "/too-large": (cut_off(b"x" * 2000, 2000), Unreachable, "response from localhost too large"),
    "/a-byte-at-a-time": (a_byte_at_a_time, Unreachable, "localhost hadn't finished its answer after 0.3 seconds"),
}


@pytest.mark.parametrize("path", sorted(REDIRECTED_TO))
def test_through_real_sockets_whatever_a_request_ends_in_after_a_redirect_is_said_of_the_host_it_led_to(pair, clock, monkeypatch, path):
    """The class of #683, past a failing status: an answer that is cut short, too large, too slow,
    no JSON or no HTTP at all. Each was said of the host asked first, which had only redirected."""
    a, b = pair
    answer, kind, says = REDIRECTED_TO[path]
    a.redirects["/api/x"] = f"https://{b.at}{path}"
    a.files, b.files = {path: answer}, {path: answer}
    monkeypatch.setattr(http_.time, "monotonic", time.monotonic)        # the real clock for the deadline, and no waiting between retries
    http = names(Http(timeout=10, deadline=0.3 if path == "/a-byte-at-a-time" else 120))
    with pytest.raises(kind) as e:
        http.json(f"https://{a.at}/api/x", max_bytes=1000)
    assert type(e.value) is kind and str(e.value).startswith(says.format(b=b.at)), str(e.value)
    assert [p for p, _ in a.seen] == ["/api/x"] * len(b.seen) and b.seen
    with pytest.raises(kind) as e:                             # and the same answer from the host itself is said of it
        http.json(f"https://{a.at}{path}", max_bytes=1000)
    assert str(e.value).startswith(says.format(b=a.at).replace("localhost", "127.0.0.1")), str(e.value)


def test_through_real_sockets_a_redirect_to_where_nothing_listens_is_that_hosts_failure(pair, clock):
    a, b = pair
    with socket.socket() as nothing:
        nothing.bind(("127.0.0.1", 0))
        closed = nothing.getsockname()[1]
    a.redirects["/api/x"] = f"https://localhost:{closed}/elsewhere"
    with pytest.raises(Unreachable, match="^couldn't reach localhost: ") as e:
        names(Http(timeout=5)).json(f"https://{a.at}/api/x")
    assert e.value.extra["no_answer"] is True and len(a.seen) == 1
