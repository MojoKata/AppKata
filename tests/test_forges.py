"""Forge API parsing against recorded responses, so no forge needs to be reachable."""

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
