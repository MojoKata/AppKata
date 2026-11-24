"""Forge API parsing against recorded responses, so no forge needs to be reachable."""

import io
import json
import re
import threading
import time
import urllib.error
import urllib.request
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from appkata_core import forges, sync, urls
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
    http = Http(opener=opener({"https://api.github.com/repos/a/b": 403}))
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
    http = Http({"github.com": "ghp_SECRET", "evil.example": ""}, opener=recording({}, seen))
    _ask(http, url, token_host="github.com")
    assert [u for u, _ in seen] == [url]
    assert tokened(seen) == ([url] if sent else []), seen
    if sent:
        assert seen[0][1]["authorization"] == "Bearer ghp_SECRET"


@pytest.mark.parametrize("host, header", [("gitlab.com", "private-token"), ("codeberg.org", "authorization")])
def test_another_hosts_token_goes_to_that_host_alone(host, header):
    seen = []
    http = Http({host: "SECRET"}, opener=recording({}, seen))
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
    http = Http({"github.com": "ghp_SECRET", "gitlab.com": "glpat_SECRET"}, opener=recording({url: PNG}, seen))
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
    http = Http({"github.com": "ghp_SECRET"}, opener=recording({
        api + "/releases": [{"tag_name": "v1.0.0", "name": "1.0", "published_at": "2026-05-02T00:00:00Z", "assets": []}],
        api + "/git/trees/main": {"tree": [{"path": p, "type": "blob"} for p in (
            "README.md", "data/org.example.r.metainfo.xml", "data/icons/icon.png", "docs/window.png")]},
        api: {"name": "r", "full_name": "o/r", "default_branch": "main",
              "owner": {"avatar_url": "https://avatars.githubusercontent.com/u/1"}},
        raw + "README.md": b"# R\n\n![shot](https://evil.example/screenshot.png)\n\n![window](docs/window.png)\n",
        raw + "data/org.example.r.metainfo.xml": METAINFO.encode(),
        raw + "docs/window.png": PNG,
        "https://avatars.githubusercontent.com/u/1": PNG,
    }, seen))
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


def _with_token(monkeypatch, header):
    """An Http with a token for server A, sent in the named header."""
    http = Http({"127.0.0.1": "SECRET-TOKEN"}, timeout=10)
    if header == "private-token":            # the form a host named for GitLab gets
        monkeypatch.setattr(http, "_auth", lambda *a, **k: {"PRIVATE-TOKEN": "SECRET-TOKEN"})
    return http


def _secrets(seen):
    return [(path, k) for path, h in seen for k, v in h.items() if "SECRET-TOKEN" in v]


@pytest.mark.parametrize("header", ["authorization", "private-token"])
def test_a_redirect_to_another_host_arrives_without_the_token(pair, monkeypatch, header):
    a, b = pair
    a.redirects["/api/x"] = f"https://{b.at}/elsewhere"
    assert _with_token(monkeypatch, header).json(f"https://{a.at}/api/x") == {"ok": True}
    assert _secrets(a.seen) == [("/api/x", header)]
    assert [path for path, _ in b.seen] == ["/elsewhere"] and _secrets(b.seen) == []
    assert not {"authorization", "private-token"} & set(b.seen[0][1])


@pytest.mark.parametrize("header", ["authorization", "private-token"])
def test_a_redirect_on_the_same_host_keeps_the_token(pair, monkeypatch, header):
    # a renamed repository's API address answers with a redirect on the same host
    a, b = pair
    a.redirects["/api/old"] = "/api/new"
    assert _with_token(monkeypatch, header).json(f"https://{a.at}/api/old") == {"ok": True}
    assert _secrets(a.seen) == [("/api/old", header), ("/api/new", header)]


@pytest.mark.parametrize("header", ["authorization", "private-token"])
@pytest.mark.parametrize("to", ["a", "b"])
def test_a_redirect_from_https_to_http_of_a_request_with_a_token_is_refused(pair, monkeypatch, header, to):
    a, b = pair
    a.redirects["/api/x"] = f"http://{(a if to == 'a' else b).at}/plain"
    with pytest.raises(Unreachable, match="http"):
        _with_token(monkeypatch, header).json(f"https://{a.at}/api/x")
    assert [path for path, _ in a.seen] == ["/api/x"] and b.seen == []      # /plain was never asked for


def test_a_redirect_from_https_to_http_without_a_token_is_followed(pair):
    a, b = pair
    a.redirects["/x"] = f"http://{b.at}/plain"
    assert Http({"gitlab.com": "SECRET-TOKEN"}, timeout=10).json(f"https://{a.at}/x") == {"ok": True}
    assert [path for path, _ in b.seen] == ["/plain"] and _secrets(a.seen + b.seen) == []
