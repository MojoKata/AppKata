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
import os

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


def test_remake_stops_on_an_app_it_cant_fetch_and_leaves_the_data_as_it_was():
    text = open(os.path.join(ROOT, "scripts", "demo_data.py"), encoding="utf-8").read()
    body = text[text.index("def remake("):text.index("\n\n\n", text.index("def remake("))]
    assert "missing = carry_over(was, db)" in body and "raise SystemExit" in body
    assert "os.rename(old, d)" in body[body.index("except BaseException"):]     # the old data back
    assert "INSERT OR REPLACE" not in body                                        # only carry_over copies rows
