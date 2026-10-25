"""Unit tests for the pure-Python pieces: URLs, versions, assets, metadata, AppKata.md, scoring."""

import pytest

from appkata_core import assets, metadata, scoring, trustfile, urls, versions
from appkata_core.catalog import eligible_release
from appkata_core.forges import Asset


# ---------------------------------------------------------------- urls (requirement 2.3, 2.5)
@pytest.mark.parametrize("given,want", [
    ("https://github.com/LocalSend/LocalSend", "https://github.com/LocalSend/LocalSend"),
    ("https://GitHub.com/localsend/localsend.git", "https://github.com/localsend/localsend"),
    ("https://github.com/localsend/localsend/", "https://github.com/localsend/localsend"),
    ("git@github.com:localsend/localsend.git", "https://github.com/localsend/localsend"),
    ("ssh://git@github.com/localsend/localsend", "https://github.com/localsend/localsend"),
    ("github.com/localsend/localsend", "https://github.com/localsend/localsend"),
    ("https://github.com/localsend/localsend/releases", "https://github.com/localsend/localsend"),
    ("https://github.com/localsend/localsend/releases/tag/v1.17.0", "https://github.com/localsend/localsend"),
    ("https://gitlab.com/inkscape/inkscape/-/releases", "https://gitlab.com/inkscape/inkscape"),
    ("https://invent.kde.org/graphics/krita/-/tree/master", "https://invent.kde.org/graphics/krita"),
    ("https://gitlab.com/group/sub/project", "https://gitlab.com/group/sub/project"),
    ("https://codeberg.org/tenacityteam/tenacity/src/branch/main", "https://codeberg.org/tenacityteam/tenacity"),
])
def test_normalize(given, want):
    assert urls.normalize(given) == want


def test_releases_page_flag_and_errors():
    assert urls.parse("https://github.com/a/b/releases").releases_page
    assert not urls.parse("https://github.com/a/b").releases_page
    for bad in ("", "https://github.com", "https://github.com/onlyowner", "ftp://x.org/a/b"):
        with pytest.raises(ValueError):
            urls.parse(bad)
    assert urls.parse("nostr://npub1abc/app-reviews").kind == "nostr"


# ---------------------------------------------------------------- versions (requirement 9.4)
def test_versions():
    assert versions.clean("v1.17.0") == "1.17.0"
    assert versions.clean("release-2.0") == "2.0"
    assert versions.clean("INKSCAPE_1_4") == "1.4" and versions.clean("Inkscape 1.4.2") == "1.4.2"
    assert versions.clean("app-2.0-rc1") == "2.0-rc1" and versions.clean("nightly") == "nightly"
    assert versions.compare("1.10.0", "1.9.2") == 1
    assert versions.compare("1.0.0-rc1", "1.0.0") == -1
    assert versions.compare("1.0.0-beta.2", "1.0.0-beta.10") == -1
    assert versions.compare("2.0", "2.0.0") == 0
    assert versions.compare("nightly", "1.0") is None
    assert versions.is_prerelease("1.2.0-beta1") and not versions.is_prerelease("1.2.0")
    assert not versions.is_prerelease("2.56.0.windows.1") and versions.is_prerelease("2.56.0-rc2.windows.1")   # Git for Windows
    assert versions.is_prerelease("3.1.0b2") and versions.newer("2.56.0.windows.1", "2.56.0-rc2.windows.1")
    assert versions.newer("25.08.1", "25.04.3")
    assert versions.newer("abc", "abd", "2026-02-01", "2026-01-01")


# ---------------------------------------------------------------- assets (requirement 4.2)
def A(*names):
    return [Asset(n, "https://x/" + n) for n in names]


def test_choose_linux_appimage_first():
    rel = A("LocalSend-1.17.0-linux-x86-64.AppImage", "LocalSend-1.17.0-linux-x86-64.deb", "LocalSend-1.17.0-windows-x86-64.exe",
            "LocalSend-1.17.0.dmg", "LocalSend-1.17.0-linux-arm-64.AppImage", "LocalSend-1.17.0-linux-x86-64.tar.gz",
            "LocalSend-1.17.0-android-arm64v8.apk", "sha256sum.txt")
    c = assets.choose(rel, "linux", "x86_64", "debian")
    assert c.asset.name == "LocalSend-1.17.0-linux-x86-64.AppImage" and c.kind == "appimage"
    c = assets.choose(rel, "linux", "arm64")
    assert c.asset.name == "LocalSend-1.17.0-linux-arm-64.AppImage" or "arm" in c.asset.name.lower()


def test_choose_native_and_filters():
    rel = A("app_2.0_amd64.deb", "app-2.0.x86_64.rpm", "app-2.0-src.tar.gz", "app-2.0.tar.gz.asc")
    assert assets.choose(rel, "linux", "x86_64", "fedora").asset.name == "app-2.0.x86_64.rpm"
    assert assets.choose(rel, "linux", "x86_64", "debian").asset.name == "app_2.0_amd64.deb"
    assert assets.choose(rel, "linux", "x86_64", "").asset is None          # no native format, source tarball skipped
    assert assets.choose(rel, "linux", "x86_64", "", override=r"\.rpm$").asset.name == "app-2.0.x86_64.rpm"
    win = A("Setup-1.0-x64.exe", "app-1.0-win32.zip", "app-1.0-x64.msi")
    assert assets.choose(win, "windows", "x86_64").asset.name == "app-1.0-x64.msi"
    mac = A("App-1.0-universal.dmg", "App-1.0-linux.AppImage")
    assert assets.choose(mac, "macos", "arm64").asset.name == "App-1.0-universal.dmg"
    assert assets.choose(A("x.exe"), "linux", "x86_64").reason == "no download for Linux x86_64"


def test_checksum_file():
    rel = A("app.AppImage", "app.AppImage.sha256", "SHA256SUMS")
    assert assets.checksum_for(rel[0], rel).name == "app.AppImage.sha256"


# ---------------------------------------------------------------- metadata (requirement 3)
def test_summary_skips_badges_and_headings():
    md = """<p align="center"><img src="logo.png"></p>

# LocalSend

[![CI](https://github.com/x/y/actions/workflows/ci.yml/badge.svg)](x) [![Translate](https://hosted.weblate.org/widgets/x.svg)](y)

LocalSend is a free, open-source app that allows you to securely share files and messages with nearby
devices over your local network **without needing an internet connection**.

## Install
"""
    s = metadata.summary(md)
    assert s.startswith("LocalSend is a free, open-source app") and "without needing an internet connection" in s
    assert "**" not in s


def test_icon_and_images():
    paths = ["assets/img/logo-32.png", "assets/img/logo-512.png", "assets/img/logo.svg", "test/fixtures/icon.png",
             "docs/screenshot-main.png", "linux/data/org.app.metainfo.xml", "assets/icons/tray-symbolic.svg"]
    c = metadata.icon_candidates(paths, "App")
    assert c[0] == "assets/img/logo.svg" and "test/fixtures/icon.png" not in c
    assert c.index("assets/img/logo-512.png") < c.index("assets/img/logo-32.png")
    assert metadata.hero_candidates(paths) == ["docs/screenshot-main.png"]
    assert metadata.metainfo_paths(paths) == ["linux/data/org.app.metainfo.xml"]
    md = "![badge](https://img.shields.io/x.svg) ![shot](docs/shot.png) <img src='https://e.com/a.jpg'>"
    assert metadata.readme_images(md) == ["docs/shot.png", "https://e.com/a.jpg"]
    assert metadata.resolve("../img/a.png", "https://raw/x/main", "docs") == "https://raw/x/main/img/a.png"


def test_metainfo():
    xml = """<?xml version="1.0"?><component type="desktop-application"><id>org.localsend.app</id>
    <developer id="org.localsend"><name>The LocalSend Team</name></developer>
    <name>LocalSend</name><name xml:lang="de">LokalSend</name><summary>Share files</summary>
    <screenshots><screenshot type="default"><image>https://e.com/s1.png</image></screenshot></screenshots></component>"""
    m = metadata.parse_metainfo(xml)
    assert m["name"] == "LocalSend" and m["summary"] == "Share files" and m["screenshot"] == "https://e.com/s1.png"


# ---------------------------------------------------------------- AppKata.md (requirement 10)
SAMPLE = """# Mara's FOSS picks

Apps I trust.

| App | Source | Tags | Trust | Rating |
|---|---|---|---|---|
| LocalSend | https://github.com/localsend/localsend | foss, Donation, offline | 5 | ⭐⭐⭐⭐ |
| TurboShield VPN | github.com/turboshield-free/vpn-desktop | spyware, ads | 0 | ★☆☆☆☆ |
| Unrated | https://codeberg.org/a/b |  |  |  |
| Dup | https://github.com/a/c | foss | 9 | 1 |
| LocalSend | https://github.com/x/y | foss | 1 | 1 |
| BadTag | https://github.com/a/d | 9lives | 3 | 3 |

# LocalSend

No account, no cloud.

- Checksums published.

# Nobody

Orphan section.
"""


def test_parse_trust_file():
    tf = trustfile.parse(SAMPLE)
    assert [r.app for r in tf.rows] == ["LocalSend", "TurboShield VPN", "Unrated"]
    ls, vpn, un = tf.rows
    assert ls.tags == ["foss", "donation", "offline"] and ls.trust == 5 and ls.rating == 4
    assert vpn.url == "https://github.com/turboshield-free/vpn-desktop" and vpn.trust == 0 and vpn.rating == 1
    assert un.trust is None and un.rating is None and un.tags == []
    assert tf.sections["LocalSend"].startswith("No account") and "Nobody" not in tf.sections
    w = " ".join(tf.warnings)
    assert "“9” isn't a value" in w and "listed twice" in w and "invalid tag 9lives" in w and "# Nobody" in w


def test_set_review_edits_only_its_parts():
    out = trustfile.set_review(SAMPLE, "LocalSend", "https://github.com/localsend/localsend", ["foss"], 4, 5, "Updated text.")
    tf = trustfile.parse(out)
    ls = tf.by_url()["https://github.com/localsend/localsend"]
    assert (ls.trust, ls.rating, ls.tags) == (4, 5, ["foss"]) and tf.sections["LocalSend"] == "Updated text."
    assert "Apps I trust." in out and "Orphan section." in out and out.splitlines().count("# LocalSend") == 1
    out2 = trustfile.set_review(out, "Krita", "https://invent.kde.org/graphics/krita", ["foss", "donation"], 5, None, "Great.")
    tf2 = trustfile.parse(out2)
    assert tf2.by_url()["https://invent.kde.org/graphics/krita"].rating is None and tf2.sections["Krita"] == "Great."
    new = trustfile.set_review("", "Zettlr", "https://github.com/Zettlr/Zettlr", [], 3, 3, "")
    assert trustfile.parse(new).rows[0].app == "Zettlr" and trustfile.HEADER.splitlines()[0] in new


def test_values():
    assert trustfile.parse_value("") is None and trustfile.parse_value("0") == 0 and trustfile.parse_value("★★★☆☆") == 3
    assert trustfile.parse_value("⭐️⭐️") == 2
    with pytest.raises(ValueError):
        trustfile.parse_value("6")


# ---------------------------------------------------------------- scoring (requirement 10.6)
def test_scoring():
    s = scoring.combine([(5, 4), (4, None), (None, 2)])
    assert not s.vetoed and s.trust == 4.5 and s.rating == 3.0 and s.reviewers == 3
    assert scoring.combine([(5, 5), (0, 1)]).vetoed
    assert scoring.combine([]).unreviewed
    apps = [("b", scoring.combine([(4, 4)])), ("a", scoring.combine([(4, 4)])), ("z", scoring.combine([])),
            ("c", scoring.combine([(5, 1)]))]
    assert [n for n, _ in sorted(apps, key=lambda x: scoring.sort_key(x[0], x[1]))] == ["c", "a", "b", "z"]


# ---------------------------------------------------------------- pin and minimum age (requirement 9.5)
def test_minimum_age():
    from datetime import datetime, timedelta, timezone
    d = lambda days: (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    rels = [{"version": "1.4.2", "date": d(2)}, {"version": "1.4.1", "date": d(40)}]
    r, held = eligible_release(rels, {"min_age": 7})
    assert r["version"] == "1.4.1" and held == "Held · 5 days left"
    r, held = eligible_release(rels, {})
    assert r["version"] == "1.4.2" and held == ""


def test_icon_ranking_real_repos():
    # cases met while syncing real projects
    upscayl = ["renderer/public/alert-icon.svg", "renderer/public/logo.svg", "docs/logo/logo.svg", "build/icon.png"]
    assert metadata.icon_candidates(upscayl, "upscayl")[0] != "renderer/public/alert-icon.svg"
    obs = ["docs/sphinx/logo.svg", "frontend/cmake/linux/icons/obs-logo-512.png"]
    assert metadata.icon_candidates(obs, "obs-studio")[0] == "frontend/cmake/linux/icons/obs-logo-512.png"
    assert metadata.summary("[ci-badge]: https://x/badge.svg\n\nHomepage • Discord • GitHub • Codeberg\n\n"
                            "LocalSend is a free, open-source app that allows you to share files.") \
        .startswith("LocalSend is a free")
    assert metadata.summary(".. image:: https://x/badge.svg\n   :target: x\n\nOBS Studio is software designed for capturing video.") \
        .startswith("OBS Studio is software")


def test_portable_or_system(tmp_path):
    """Requirement 4.2.1: the file decides; Windows .exe files are probed."""
    assert assets.category("appimage") == "portable" and assets.category("rpm") == "system"
    assert assets.category("exe", "inno") == "system" and assets.category("exe", "portable") == "portable"
    assert assets.category("exe", "unknown") == "unknown"
    assert assets.exe_type("App-1.0-portable.exe") == "portable" and assets.exe_type("App-Setup-1.0.exe") == "installer"
    assert assets.exe_type("app.exe", b"MZ....Inno Setup Setup Data (6.2.0)") == "inno"
    assert assets.exe_type("app.exe", b"MZ" + b"\0" * 64 + b"NullsoftInst") == "nsis"
    assert assets.exe_type("app.exe", b"MZ") == "unknown"
    rel = A("upscayl-2.15.0-linux.AppImage", "upscayl-2.15.0-linux.rpm", "upscayl-2.15.0-linux.deb", "upscayl-2.15.0-win.exe")
    c = assets.candidates(rel, "linux", "x86_64", "fedora")
    assert [x.kind for x in c] == ["appimage", "rpm"]
    assert assets.choose(rel, "linux", "x86_64", "fedora", prefer="system").kind == "rpm"
    assert assets.choose(rel, "linux", "x86_64", "fedora", prefer="rpm").kind == "rpm"
    assert assets.choose(rel, "linux", "x86_64", "fedora", prefer="flatpak").kind == "appimage"     # not offered: the default


def test_saved_install_choice_is_used(tmp_path):
    import json
    from appkata_core import catalog
    from appkata_core.db import DB
    db = DB(str(tmp_path / "a.db"))
    url = "https://github.com/upscayl/upscayl"
    files = [{"name": n, "url": "https://x/" + n, "size": 1, "digest": "", "content_type": ""}
             for n in ("upscayl-2.15.0-linux.AppImage", "upscayl-2.15.0-linux.rpm")]
    db.x("INSERT INTO sources(url, input_url, added_at) VALUES(?,?,'x')", (url, url))
    db.x("INSERT INTO apps(url, name, releases) VALUES(?,?,?)", (url, "Upscayl", json.dumps([{"version": "2.15.0", "date": "2025-01-01", "assets": files}])))
    a = catalog.build(db, "linux", "x86_64")[0]
    assert a["asset"]["kind"] == "appimage" and a["asset"]["category"] == "portable"
    db.x("INSERT INTO app_settings(url, install) VALUES(?,?)", (url, json.dumps({"kind": "rpm"})))
    a = catalog.build(db, "linux", "x86_64")[0]
    assert a["asset"]["kind"] in ("rpm", "appimage")            # rpm only where the family is fedora
    assert a["installChoice"] == {"kind": "rpm"}


def test_settings_subsection():
    """'## <App>::Settings' (requirement 8.4.7, 10.3.1)."""
    text = trustfile.set_review("", "Flameshot", "https://github.com/flameshot-org/flameshot", ["foss"], 4, 4,
                                "Review about flameshot.", {"appMenu": True, "commandLink": False, "stableName": True})
    assert ("## Flameshot::Settings\n\n- Trust: 4\n- Rating: 4\n- Tags: foss\n- App menu: yes\n- Command link: no\n"
            "- Stable name link: yes") in text
    tf = trustfile.parse(text)
    assert tf.sections["Flameshot"] == "Review about flameshot."
    assert tf.settings["Flameshot"] == {"appMenu": True, "commandLink": False, "stableName": True,
                                        "_app": {"trust": 4, "rating": 4, "tags": ["foss"]}} and tf.warnings == []
    again = trustfile.set_review(text, "Flameshot", "https://github.com/flameshot-org/flameshot", ["foss"], 4, 4,
                                 "Better review.", {"appMenu": False, "commandLink": True, "stableName": True})
    assert again.count("::Settings") == 1 and "- App menu: no" in again
    assert trustfile.parse(again).sections["Flameshot"] == "Better review."
    assert trustfile.parse(open("docs/AppKata.md", encoding="utf-8").read()).warnings == []          # the published file parses cleanly


def test_weighted_scoring_by_trust_score():
    # a 5-star Trust's review counts five times a 1-star Trust's (requirement 10.6.2)
    s = scoring.combine([(5, 5, 5), (1, 1, 1)])
    assert s.trust == round((25 + 1) / 6, 1) and s.rating == round(26 / 6, 1) and s.reviewers == 2
    assert scoring.combine([(4, 4), (2, 2)]).trust == 3.0          # no weight: plain average
    v = scoring.combine([(5, 5, 5), (0, 1, 1)])                    # a 0 still vetoes, whatever its Score
    assert v.vetoed and v.trust is None


def test_trust_order_and_score():
    from appkata_core.catalog import trust_order, trust_score
    ts = [{"name": "b", "score": 3}, {"name": "a", "score": 3}, {"name": "z", "score": 5}, {"name": "mine", "own": 1, "score": 1}]
    assert [t["name"] for t in sorted(ts, key=trust_order)] == ["mine", "z", "a", "b"]
    assert trust_score({"own": 1, "score": 2}) == 5 and trust_score({"score": None}) == 3 and trust_score({"score": 9}) == 5


def test_settings_per_platform():
    # requirement 10.3.1: "- <Option> (<platform>): yes|no" overrides the line without a platform
    sec = ("Notes.\n\n## Zettlr::Settings\n\n- App menu: yes\n- Auto update: no\n- Auto update (Win): yes\n"
           "- Auto update (mac): yes\n- Command link (windows): no\n- Auto update (amiga): yes\n")
    text, opts = trustfile.split_settings("Zettlr", sec)
    assert text == "Notes."
    assert opts == {"appMenu": True, "autoUpdate": False,
                    "platforms": {"WIN": {"autoUpdate": True, "commandLink": False}, "MAC": {"autoUpdate": True}}}
    assert trustfile.resolve_settings(opts, "linux") == {"appMenu": True, "autoUpdate": False}
    assert trustfile.resolve_settings(opts, "windows") == {"appMenu": True, "autoUpdate": True, "commandLink": False}
    assert trustfile.resolve_settings(opts, "macos")["autoUpdate"] is True
    out = trustfile.format_settings("Zettlr", opts)
    assert out.splitlines()[2:] == ["- App menu: yes", "- Auto update: no", "- Command link (windows): no",
                                    "- Auto update (windows): yes", "- Auto update (macos): yes"]
    assert trustfile.split_settings("Zettlr", "## Zettlr::Settings\n\n" + out.split("\n\n", 1)[1])[1] == opts
    # the review dialog: Auto update and the download filter are written for this platform, the
    # others without one (and this platform's lines for them dropped)
    merged = trustfile.merge_settings(opts, {"autoUpdate": False, "commandLink": True, "assetFilter": "x64\\.msi$"}, "windows")
    assert merged["commandLink"] is True and "commandLink" not in merged["platforms"]["WIN"]
    assert merged["platforms"]["WIN"] == {"autoUpdate": False, "assetFilter": "x64\\.msi$"} and merged["autoUpdate"] is False
    assert trustfile.resolve_settings(merged, "windows") == {"appMenu": True, "autoUpdate": False, "commandLink": True, "assetFilter": "x64\\.msi$"}
    assert trustfile.resolve_settings(merged, "macos")["autoUpdate"] is True and "assetFilter" not in trustfile.resolve_settings(merged, "linux")
    assert "signed" in trustfile.PREDEFINED_TAGS and "signedbinaries" not in trustfile.PREDEFINED_TAGS


def test_source_archives_are_not_downloads():
    names = ["transmission-4.1.3.tar.xz", "OBS-Studio-32.2.2-Sources.tar.gz", "HandBrake-1.11.2-source.tar.bz2",
             "syncthing-linux-amd64-v2.1.5.tar.gz"]
    got = assets.candidates([Asset(n, "") for n in names], "linux", "x86_64", "debian")
    assert [c.asset.name for c in got] == ["syncthing-linux-amd64-v2.1.5.tar.gz"]


def test_recently_updated_sort():
    from appkata_core import catalog
    apps = [{"name": "B", "date": "2026-01-01", "vetoed": False, "trust": 5, "rating": 5, "reviewers": 1},
            {"name": "A", "date": "2026-09-01", "vetoed": False, "trust": 1, "rating": 1, "reviewers": 1},
            {"name": "C", "date": "", "vetoed": False, "trust": None, "rating": None, "reviewers": 0}]
    assert [a["name"] for a in catalog.sort(apps, "recent")] == ["A", "B", "C"]


def test_source_settings_in_appkata_md():
    # requirement 10.3.1: forge and download filter can be recommended (a regex in backticks);
    # Track only and pre-releases are personal, so they're ignored
    sec = ("## Zettlr::Settings\n\n- Track only: no\n- Include pre-releases: yes\n- Forge: GitLab\n"
           "- Download filter: `x86_64\\.AppImage$`\n- Download filter (windows): `setup.*\\.exe$`\n- Forge: svn\n- Download filter (mac): `(`\n")
    opts = trustfile.split_settings("Zettlr", sec)[1]
    assert opts == {"forge": "gitlab", "assetFilter": "x86_64\\.AppImage$", "platforms": {"WIN": {"assetFilter": "setup.*\\.exe$"}}}
    lines = trustfile.format_settings("Zettlr", opts).splitlines()[2:]
    assert lines == ["- Forge: gitlab", "- Download filter: `x86_64\\.AppImage$`", "- Download filter (windows): `setup.*\\.exe$`"]


def test_recommended_source_settings_apply_unless_set():
    from appkata_core import catalog
    rows = [('{"forge": "gitlab", "assetFilter": "nomatch"}', {"name": "B", "score": 3}),
            ('{"forge": "gitea"}', {"name": "A", "score": 5})]
    rec, by = catalog.pick_recommended(rows, "linux")
    assert rec == {"forge": "gitea", "assetFilter": "nomatch"} and by["forge"] == "A"
    eff = catalog.effective_source({"forge": "github", "track_only": True}, rec, by, "linux", "x86_64", False)
    assert eff["forge"] == "github" and eff["by"]["forge"] == "you" and eff["trackOnly"] is True and eff["prereleases"] is False
    # a recommended filter that matches nothing here is ignored; your own isn't
    a = [Asset("Tool-1.0-x86_64.AppImage", "")]
    assert catalog.choose_with(eff, a, "linux", "x86_64", "").asset.name == "Tool-1.0-x86_64.AppImage"
    assert catalog.choose_with({**eff, "by": {"assetFilter": "you"}}, a, "linux", "x86_64", "").asset is None
