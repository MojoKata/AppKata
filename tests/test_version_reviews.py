"""Version reviews in AppKata.md (requirement 10.3, 10.6.5, 8.5)."""

import json

from appkata_core import catalog, review, trustfile
from appkata_core.db import DB

URL = "https://github.com/zettlr/zettlr"
FILE = """| App | Source | Tags | Trust | Rating |
|---|---|---|---|---|
| Zettlr | https://github.com/Zettlr/Zettlr | foss, donation, portable, signed | 5 | 4 |

# Zettlr

A Markdown editor for long-form writing.

## Zettlr::Settings

- Trust: 4
- Rating: 4
- Tags: foss, donation, portable
- Download filter (linux): `x86_64\\.AppImage$`
- Auto update (linux): no
- Auto update (windows): yes

## Zettlr[3.5.1]

Release files are now signed.

### Pros

Fast.

### Zettlr[3.5.1]::Details

- Date: 2026-09-14
- Platform: linux x86_64
- Channel: GitHub release

### Zettlr[3.5.1]::Settings

- Trust: 5
- Tags: foss, donation, portable, signed
- Auto updates (linux): yes
"""


def _parsed(text=FILE):
    tf = trustfile.parse(text)
    return tf, tf.settings["Zettlr"]


def test_parse_version_reviews():
    tf, s = _parsed()
    assert tf.warnings == []
    assert tf.sections["Zettlr"] == "A Markdown editor for long-form writing."
    assert s["_app"] == {"trust": 4, "rating": 4, "tags": ["foss", "donation", "portable"]}
    assert s["platforms"]["LINUX"]["assetFilter"] == "x86_64\\.AppImage$"
    (v,) = s["_versions"]
    assert v["v"] == "3.5.1" and v["text"] == "Release files are now signed.\n\n### Pros\n\nFast."   # other headings stay text
    assert v["details"][0] == ["Date", "2026-09-14"] and v["verdict"]["trust"] == 5
    assert v["opts"] == {"platforms": {"LINUX": {"autoUpdate": True}}}          # "Auto updates" is read too


def test_values_carry_forward_and_table_wins():
    _, s = _parsed()
    table = {"trust": 5, "rating": 4, "tags": ["foss", "donation", "portable", "signed"]}
    chain = trustfile.reviews_over_versions(s, table, "linux")
    app, v351 = chain
    assert (app["trust"], app["rating"], app["opts"]["autoUpdate"]) == (4, 4, False)
    assert (v351["trust"], v351["rating"], v351["opts"]["autoUpdate"]) == (5, 4, True)      # Rating carried
    assert v351["opts"]["assetFilter"] == "x86_64\\.AppImage$"                              # options carried too
    # on Windows the app review's own line applies at 3.5.1 too
    assert trustfile.reviews_over_versions(s, table, "windows")[1]["opts"]["autoUpdate"] is True
    assert trustfile.review_for(s, table, "3.4.0", "linux")["version"] == ""
    assert trustfile.review_for(s, table, "3.5.1", "linux")["version"] == "3.5.1"
    assert trustfile.review_for(s, table, "4.0.0", "linux")["trust"] == 5
    # the table row wins for the newest review, with a parse warning
    tf = trustfile.parse(FILE.replace("| 5 | 4 |", "| 3 | 4 |"))
    assert any("differ" in w for w in tf.warnings)
    assert trustfile.review_for(tf.settings["Zettlr"], {"trust": 3}, None, "linux")["trust"] == 3


def test_unplaceable_versions_and_dates():
    s = {"_versions": [{"v": "aurora", "text": "", "details": [], "opts": {}, "verdict": {"trust": 2}},
                       {"v": "comet", "text": "", "details": [], "opts": {}, "verdict": {"trust": 4}}]}
    table = {"trust": 4, "rating": 3, "tags": []}
    # not semver-like and no dates: exact match only, else the newest
    assert trustfile.review_for(s, table, "aurora", "linux")["trust"] == 2
    assert trustfile.review_for(s, table, "borealis", "linux")["trust"] == 4
    # placed by release dates
    dates = {"aurora": "2024-01-10", "borealis": "2024-03-01", "comet": "2024-06-01"}
    assert trustfile.review_for(s, table, "borealis", "linux", dates)["trust"] == 2


def test_app_review_fallbacks():
    # no app-review values: the earliest version review's, else the table row's (10.3.3)
    s = {"_versions": [{"v": "5.6.0", "text": "", "details": [], "opts": {}, "verdict": {"trust": 0}},
                       {"v": "5.6.2", "text": "", "details": [], "opts": {}, "verdict": {"trust": 4}}]}
    chain = trustfile.reviews_over_versions(s, {"trust": 4, "rating": 4, "tags": ["foss"]}, "linux")
    assert chain[0]["trust"] == 0 and chain[0]["rating"] == 4
    assert [trustfile.review_for(s, {"trust": 4}, v, "linux")["trust"] for v in ("5.4.0", "5.6.0", "5.6.1", "5.6.2", "5.8.1")] == [0, 0, 0, 4, 4]


def test_parse_warnings():
    text = FILE + """
## Zettlr[]

Nothing.

## Zettlr[3.5.1]

Twice.

### Zettlr[9.9]::Details

- Date: x

## Zettlr[4.0]

### Zettlr[4.0]::Settings

- Trust (linux): 3
- Rating: 9
"""
    w = " ".join(trustfile.parse(text).warnings)
    assert "names no version" in w and "two reviews of 3.5.1" in w and "[9.9]::Details" in w
    assert "platform on “Trust”" in w and "“9” isn't a value" in w


def test_write_first_version_review_and_round_trip():
    base = """# Picks

| App | Source | Tags | Trust | Rating |
|---|---|---|---|---|
| Zettlr | https://github.com/Zettlr/Zettlr | foss | 4 | 4 |
| Other | https://github.com/a/b | foss | 3 | 3 |

# Zettlr

Good editor.

## Zettlr::Settings

- App menu: yes

# Other

Untouched.
"""
    out = trustfile.set_review(base, "Zettlr", "https://github.com/Zettlr/Zettlr", ["foss", "signed"], 5, 4, "Now signed.",
                               {"platforms": {"LINUX": {"autoUpdate": True}}}, "3.5.1", [["Date", "2026-09-14"], ["SHA-256", "abc"]])
    assert out.split("# Zettlr")[0].replace("| foss, signed | 5 | 4 |", "| foss | 4 | 4 |") == base.split("# Zettlr")[0]
    assert out.endswith("# Other\n\nUntouched.\n")
    tf = trustfile.parse(out)
    assert tf.warnings == []
    s = tf.settings["Zettlr"]
    assert s["_app"] == {"trust": 4, "rating": 4, "tags": ["foss"]}            # the app review kept its values (8.5)
    assert s["appMenu"] is True and tf.sections["Zettlr"] == "Good editor."
    (v,) = s["_versions"]
    assert v["text"] == "Now signed." and v["details"] == [["Date", "2026-09-14"], ["SHA-256", "abc"]]
    assert "### Zettlr[3.5.1]::Settings\n\n- Trust: 5\n- Rating: 4\n- Tags: foss, signed\n- Auto update (linux): yes" in out
    # an older version review goes before it and leaves the table row alone
    out2 = trustfile.set_review(out, "Zettlr", "https://github.com/Zettlr/Zettlr", ["foss"], 2, 3, "Crashed a lot.", None, "3.1.0")
    tf2 = trustfile.parse(out2)
    assert [r["v"] for r in tf2.settings["Zettlr"]["_versions"]] == ["3.1.0", "3.5.1"]
    assert tf2.rows[0].trust == 5 and tf2.warnings == []
    assert out2.index("## Zettlr[3.1.0]") < out2.index("## Zettlr[3.5.1]")
    # editing a review keeps its Details unless new ones are given
    out3 = trustfile.set_review(out2, "Zettlr", "https://github.com/Zettlr/Zettlr", ["foss", "signed"], 5, 5, "Signed and fast.", None, "3.5.1")
    v3 = trustfile.parse(out3).settings["Zettlr"]["_versions"][1]
    assert v3["text"] == "Signed and fast." and v3["details"][1] == ["SHA-256", "abc"] and out3.splitlines().count("## Zettlr[3.5.1]") == 1
    assert trustfile.parse(out3).rows[0].rating == 5
    # the app review can still be edited without touching the version reviews
    out4 = trustfile.set_review(out3, "Zettlr", "https://github.com/Zettlr/Zettlr", ["foss"], 4, 4, "Good editor, long texts.")
    tf4 = trustfile.parse(out4)
    assert tf4.sections["Zettlr"] == "Good editor, long texts." and len(tf4.settings["Zettlr"]["_versions"]) == 2
    assert tf4.rows[0].trust == 5            # not the newest review, so the table row stays


def test_options_written_only_when_they_change():
    _, s = _parsed()
    opts = trustfile.options_to_write(s, "3.6.0", {"appMenu": True, "autoUpdate": True}, "linux")
    assert opts == {"appMenu": True}           # Auto update (linux) is already yes from 3.5.1
    assert trustfile.options_to_write(s, "", {"appMenu": True}, "linux")["appMenu"] is True


def test_scores_per_version(tmp_path):
    db = DB(str(tmp_path / "a.db"))
    tid = db.x("INSERT INTO trusts(url, name, own, verified_commit, score) VALUES(?,?,?,?,?)", ("t", "Desk", 0, "abc", 3)).lastrowid
    s = {"_app": {"trust": 4}, "_versions": [
        {"v": "5.6.0", "text": "Backdoored.", "details": [], "opts": {}, "verdict": {"trust": 0}},
        {"v": "5.6.2", "text": "Clean.", "details": [], "opts": {}, "verdict": {"trust": 4}}]}
    url = "https://github.com/tukaani-project/xz"
    db.x("INSERT INTO reviews(trust_id, url, app, source, tags, trust, rating, section, settings) VALUES(?,?,?,?,?,?,?,?,?)",
         (tid, url, "XZ Utils", url, '["foss"]', 4, 4, "Compression.", json.dumps(s)))
    rels = [{"version": v, "date": d, "assets": [{"name": f"xz-{v}.tar.gz", "url": "u", "size": 1}]}
            for v, d in (("5.8.1", "2025-04-03"), ("5.6.2", "2024-05-29"), ("5.4.6", "2024-01-26"))]
    db.x("INSERT INTO apps(url, name, releases) VALUES(?,?,?)", (url, "XZ Utils", json.dumps(rels)))
    db.x("INSERT INTO installs(url, name, version, date, asset, kind, record) VALUES(?,?,?,?,?,?,?)",
         (url, "XZ Utils", "5.6.1", "2024-03-09", "", "tarball", "{}"))
    a = catalog.build(db, "linux", "x86_64")[0]
    assert not a["vetoed"] and a["trust"] == 4.0                  # the latest release
    assert a["installedVetoed"] and a["avoid"]["by"] == "Desk" and a["avoid"]["from"] == "5.6.0"
    assert a["avoid"]["note"] == "Backdoored." and a["avoidUpdateTo"] == "5.8.1"
    vs = catalog.version_scores(db, url, ["5.8.1", "5.6.1", "5.4.6"])
    assert vs["5.6.1"] == (None, True) and vs["5.8.1"] == (4.0, False) and vs["5.4.6"] == (4.0, False)


def test_review_current_and_save(tmp_path):
    p = str(tmp_path / "AppKata.md")
    open(p, "w").write(FILE)
    cur = review.current(p, "Zettlr", URL)
    assert cur["exists"] and cur["versions"][0]["v"] == "3.5.1" and "_versions" not in cur["settings"]
    res = review.save(p, "Zettlr", "https://github.com/Zettlr/Zettlr", ["foss"], 5, 5, "3.6 is great.", version="3.6.0")
    assert res.saved
    tf = trustfile.parse(open(p).read())
    assert [v["v"] for v in tf.settings["Zettlr"]["_versions"]] == ["3.5.1", "3.6.0"] and tf.rows[0].rating == 5
