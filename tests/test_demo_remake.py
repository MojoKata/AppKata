"""scripts/demo_data.py remake carries the synced Catalog over only for the apps the new build lists
(the walk thru of 2026-10-30, item 7; docs/reviews/followups-demo-remake.md).

How it slipped past: remake was written to keep the screens' releases while build changed what it
writes around them, and it was checked by comparing a remade copy with the data it came from,
table by table: with the same lists on both sides, copying every row and copying the listed rows
give the same tables. An app taken off the lists stayed in the Catalog's table, with nothing
naming it. The class: a rebuild that merges the old state into the new and keeps what the new
one dropped. carry_over now takes the Catalog's own list (sync.catalog_urls) as what may come over,
and says which listed apps have no synced row, which remake can't fetch."""

import importlib.util
import json
import os
import shutil

import pytest

from appkata_core.db import DB

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
GH = "https://github.com/"


def _demo():
    spec = importlib.util.spec_from_file_location("demo_data", os.path.join(ROOT, "scripts", "demo_data.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _db(path, sources=(), reviewed=(), synced=()):
    db = DB(str(path))
    for u in sources:
        db.x("INSERT INTO sources(url, input_url) VALUES(?,?)", (GH + u, GH + u))
    if reviewed:
        db.x("INSERT INTO trusts(id, url, name) VALUES(1, 'https://example.org/t', 'T')")
        for u in reviewed:
            db.x("INSERT INTO reviews(trust_id, url, app) VALUES(1,?,?)", (GH + u, u))
    for u in synced:
        db.x("INSERT INTO apps(url, name, releases) VALUES(?,?,?)", (GH + u, u, '[{"version": "1.0"}]'))
        db.x("INSERT INTO app_meta(url, appstream_id) VALUES(?,?)", (GH + u, "org." + u.replace("/", ".")))
    return db


def test_only_the_apps_the_new_build_lists_come_over(tmp_path):
    demo = _demo()
    was = _db(tmp_path / "old.db", sources=["a/a", "gone/source"], reviewed=["b/b", "gone/review"],
              synced=["a/a", "b/b", "gone/source", "gone/review"])
    new = _db(tmp_path / "new.db", sources=["a/a"], reviewed=["b/b"])
    assert demo.carry_over(was, new) == []
    assert sorted(r["url"] for r in new.all("SELECT url FROM apps")) == [GH + "a/a", GH + "b/b"]
    assert sorted(r["url"] for r in new.all("SELECT url FROM app_meta")) == [GH + "a/a", GH + "b/b"]
    assert new.one("SELECT releases FROM apps WHERE url=?", (GH + "a/a",))["releases"] == '[{"version": "1.0"}]'


def test_an_app_the_new_build_lists_and_the_old_data_never_synced_is_named(tmp_path):
    demo = _demo()
    was = _db(tmp_path / "old.db", sources=["a/a"], synced=["a/a"])
    new = _db(tmp_path / "new.db", sources=["a/a", "new/app"])
    assert demo.carry_over(was, new) == [GH + "new/app"]


def _body(text, name):
    return text[text.index(f"def {name}("):text.index("\n\n\n", text.index(f"def {name}("))]


def test_remake_stops_on_an_app_it_cant_fetch_and_leaves_the_data_as_it_was():
    text = open(os.path.join(ROOT, "scripts", "demo_data.py"), encoding="utf-8").read()
    body, carry = _body(text, "remake"), _body(text, "_carry")
    assert "_carry(d, " in body and "finish(d)" in body
    assert "missing = carry_over(was, db)" in carry and "raise SystemExit" in carry
    assert "os.rename(old, d)" in body[body.index("except BaseException"):]     # the old data back
    assert "INSERT OR REPLACE" not in body + carry                                # only carry_over copies rows


def _synced(path):
    """A database as sync leaves one: two apps listed and synced, one Source with its forge."""
    db = _db(path, sources=["a/a"], reviewed=["b/b"], synced=["a/a", "b/b"])
    db.x("UPDATE sources SET forge='github' WHERE url=?", (GH + "a/a",))
    db.x("UPDATE apps SET icon='cache/abc/icon.svg' WHERE url=?", (GH + "a/a",))
    db.put("autoupdate", {"flatpak": [], "packages": []})
    return db


def test_the_snapshot_holds_what_sync_fetched_and_reads_back_the_same(tmp_path):
    """snapshot writes the synced Catalog, its forges, the updaters and the icons it names; snapshot_db
    reads it back in sync's shape, which _carry takes as it takes remake's old data."""
    demo = _demo()
    d = tmp_path / "data"
    was = _synced(d / "appkata.db")
    (d / "cache" / "abc").mkdir(parents=True)
    (d / "cache" / "abc" / "icon.svg").write_text("<svg/>")
    (d / "cache" / "unused").mkdir()                      # no app names it: it stays behind
    out = tmp_path / "snap"
    demo.snapshot(str(d), str(out))
    data = json.loads((out / "catalog.json").read_text())
    assert [a["url"] for a in data["apps"]] == [GH + "a/a", GH + "b/b"]
    assert data["apps"][0]["releases"] == [{"version": "1.0"}]             # JSON, not a string of it
    assert data["forges"] == {GH + "a/a": "github"} and data["autoupdate"] == {"flatpak": [], "packages": []}
    assert sorted(p.name for p in (out / "cache").iterdir()) == ["abc"]
    back = demo.snapshot_db(str(out), str(tmp_path / "back.db"))
    for table in ("apps", "app_meta"):
        assert [dict(r) for r in back.all(f"SELECT * FROM {table} ORDER BY url")] == \
            [dict(r) for r in was.all(f"SELECT * FROM {table} ORDER BY url")]
    assert back.get("autoupdate") == was.get("autoupdate")
    new = _db(tmp_path / "new" / "appkata.db", sources=["a/a"], reviewed=["b/b"])
    demo._carry(str(tmp_path / "new"), back, str(out / "cache"), "the snapshot")
    assert new.one("SELECT forge FROM sources WHERE url=?", (GH + "a/a",))["forge"] == "github"
    assert (tmp_path / "new" / "cache" / "abc" / "icon.svg").read_text() == "<svg/>"
    assert sorted(r["url"] for r in new.all("SELECT url FROM apps")) == [GH + "a/a", GH + "b/b"]


def test_restore_stops_on_an_app_the_snapshot_never_had(tmp_path):
    demo = _demo()
    out = tmp_path / "snap"
    _synced(tmp_path / "data" / "appkata.db")
    demo.snapshot(str(tmp_path / "data"), str(out))
    new = _db(tmp_path / "new" / "appkata.db", sources=["a/a", "new/app"])
    with pytest.raises(SystemExit, match="the snapshot has no synced data .*new/app"):
        demo._carry(str(tmp_path / "new"), demo.snapshot_db(str(out), str(tmp_path / "back.db")), str(out / "cache"),
                    "the snapshot")


@pytest.mark.skipif(not shutil.which("gpg"), reason="needs gpg")
def test_the_committed_snapshot_covers_what_the_build_lists(tmp_path):
    """tests/data/demo, CI's fallback, has a synced row for every app the demo's build lists: restore
    makes the tour's data from it without the network. The build itself is offline."""
    demo = _demo()
    d = tmp_path / "tour-data"
    demo.build(str(d))
    db = DB(str(d / "appkata.db"))
    snap = demo.snapshot_db(demo.SNAPSHOT, str(tmp_path / "snap.db"))
    assert demo.carry_over(snap, db) == []
    for a in snap.all("SELECT icon, hero FROM apps"):
        for p in (a["icon"], a["hero"]):
            assert not p or not p.startswith("cache/") or os.path.exists(os.path.join(demo.SNAPSHOT, p)), p
    # AppKata's own Source lists last, however soon after the build finish adds it (S01)
    demo.self_app(db, str(d))
    order = [r["url"] for r in db.all("SELECT url FROM sources ORDER BY added_at, url")]
    assert order[-1] == demo.APPKATA_REPO and len(order) == len(demo.SOURCES) + 1


@pytest.mark.parametrize("hour, offset", [(0, "-01:00"), (1, "+00:00"), (23, "+00:00")])
def test_the_tours_zone_is_utc_but_in_the_first_hour_of_its_day(monkeypatch, hour, offset):
    """The Audit's day has no room in its first hour (history stops), so the tour then shows an hour
    behind UTC, where the day is ending; scripts/test-layout.sh gives its container the same zone."""
    from datetime import datetime, timezone
    demo = _demo()
    monkeypatch.delenv("APPKATA_TOUR_OFFSET", raising=False)
    assert demo.tour_offset(datetime(2026, 11, 21, hour, 30, tzinfo=timezone.utc)) == offset
    monkeypatch.setenv("APPKATA_TOUR_OFFSET", "+05:30")
    assert demo.tour_offset() == "+05:30"
    sh = open(os.path.join(ROOT, "scripts", "test-layout.sh"), encoding="utf-8").read()
    assert 'demo_data.py" offset' in sh and '--utc-offset "$OFF"' in sh and '-e TZ="$TZ_POSIX"' in sh
