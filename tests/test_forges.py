"""Forge API parsing against recorded responses, so no forge needs to be reachable."""

import io
import ipaddress
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from appkata_core import explore, forges, sync, urls
from appkata_core import http as http_
from appkata_core.db import DB
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
    """Notes each request as (path, its headers by lower-case name), and redirects the paths it is told to."""

    def do_GET(self):
        self.server.seen.append((self.path, {k.lower(): v for k, v in self.headers.items()}))
        to = self.server.redirects.get(self.path)
        body = b"" if to else b'{"ok": true}'
        self.send_response(302 if to else 200)
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
        server.seen, server.redirects = [], {}
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
