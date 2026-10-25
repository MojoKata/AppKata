"""Forge API parsing against recorded responses, so no forge needs to be reachable."""

import io
import json
import time
import urllib.error

import pytest

from appkata_core import forges, urls
from appkata_core.http import Http, RateLimited


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
