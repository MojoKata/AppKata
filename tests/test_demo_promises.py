"""Every tour screen says what it needs from the demo data (review 3, R3-24).

How R3-24 slipped past: the tour checked that its text fits its boxes (R3-22) and that the demo
data held no failed sync (9d41e51), and each regenerated screen was viewed. Nothing compared a
screen with what screenshots/README.md says it shows, so a state staged once drifted unnoticed:
the minimum age that held Zettlr 4.8.0 back ran out on 2026-10-08, and the Windows set never had a
held update (Zettlr updates itself there). `scripts/demo_data.py check`, run before each tour, now
checks each claim the README makes about a screen's data on each platform. This test keeps its
list whole: a screen the tour takes has an entry, and a Linux-only screen's claims say so.
"""

import ast
import importlib.util
import os

from test_requirements_trace import _finding_exists

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")


def _demo():
    spec = importlib.util.spec_from_file_location("demo_data", os.path.join(ROOT, "scripts", "demo_data.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _tour():
    """tour.py's screen names and its Linux-only set, read without starting Qt."""
    with open(os.path.join(ROOT, "src", "appkata", "tour.py"), encoding="utf-8") as f:
        tree = ast.parse(f.read())
    names, linux_only = [], set()
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            if node.targets[0].id == "STEPS":
                names = [step.elts[0].value for step in node.value.elts]
            elif node.targets[0].id == "LINUX_ONLY":
                linux_only = ast.literal_eval(node.value)
    return names, linux_only


def test_every_tour_screen_has_an_entry():
    names, _ = _tour()
    promises = _demo().PROMISES
    assert len(names) > 50
    assert [n for n in names if n not in promises] == []
    assert [n for n in promises if n not in names and n != "every screen"] == []


def test_an_entry_checks_something_or_says_why():
    for screen, claims in _demo().PROMISES.items():
        if isinstance(claims, str):
            assert claims.strip(), screen
        else:
            assert claims, screen
            for claim in claims:
                assert isinstance(claim[0], str) and callable(claim[1]) and claim[2:] in ((), ("linux",), ("windows",)), (screen, claim)


def test_a_linux_only_screen_makes_no_claim_for_windows():
    _, linux_only = _tour()
    for screen, claims in _demo().PROMISES.items():
        if screen in linux_only and not isinstance(claims, str):
            assert all(c[2:] == ("linux",) for c in claims), screen


def test_each_claim_still_wrong_names_its_finding():
    demo = _demo()
    for wrong, finding in demo.STILL_WRONG.items():
        screen, _, rest = wrong.partition(" (")
        platform, _, text = rest.partition("): ")
        assert platform in ("linux", "windows"), wrong
        claims = demo.PROMISES[screen]
        assert any(c[0] == text for c in claims), wrong
        assert _finding_exists(finding), (wrong, finding)


def test_stage_holds_the_newest_release_with_days_to_go(tmp_path):
    """stage sets the minimum age so HELD's newest release has HELD_DAYS_LEFT days to go, whatever
    the hour, in the database and in Settings, and puts the sync times 50 minutes back."""
    import json
    from datetime import datetime, timedelta, timezone

    from appkata_core import catalog
    from appkata_core.db import DB

    demo = _demo()
    now = datetime.now(timezone.utc)
    for age in (36.01, 36.5, 36.99, 3.2):
        d = tmp_path / str(age)
        d.mkdir()
        (d / "gui.json").write_text(json.dumps({"minAgeDefault": 20}))
        rels = [{"version": "4.8.0", "date": (now - timedelta(days=age)).isoformat(), "assets": [{"name": "a"}]},
                {"version": "4.7.0", "date": (now - timedelta(days=age + 50)).isoformat(), "assets": [{"name": "a"}]}]
        db = DB(str(d / "appkata.db"))
        db.x("INSERT INTO apps(url, name, releases) VALUES(?,?,?)", (demo.GH + demo.HELD, "Zettlr", json.dumps(rels)))
        demo.stage(str(d))
        days = db.get("min_age_default")
        assert json.loads((d / "gui.json").read_text())["minAgeDefault"] == days
        assert catalog.eligible_release(rels, {"min_age": days}) == (rels[1], f"Held · {demo.HELD_DAYS_LEFT} days left")
        assert timedelta(minutes=49) < now - datetime.fromisoformat(db.get("last_sync")) < timedelta(minutes=52)


def test_stage_writes_the_audit_in_time_order_ending_before_now(tmp_path):
    """stage writes the demo's Audit again (R3-25): in the order the Audit lists it, the newest
    entry half an hour back whatever the hour, build's own entries gone (no entry twice), the same
    rows on every run, and the append-only triggers back afterwards."""
    import json
    import sqlite3
    from datetime import datetime, timedelta, timezone

    import pytest

    from appkata_core.db import DB

    demo = _demo()
    now = datetime.now(timezone.utc)
    d = tmp_path / "d"
    d.mkdir()
    (d / "gui.json").write_text("{}")
    db = DB(str(d / "appkata.db"))
    rels = [{"version": "4.8.0", "date": (now - timedelta(days=20)).isoformat(), "assets": [{"name": "a"}]}]
    db.x("INSERT INTO apps(url, name, releases) VALUES(?,?,?)", (demo.GH + demo.HELD, "Zettlr", json.dumps(rels)))
    db.x("INSERT INTO audit(at, actor, kind, action, subject, url, detail) VALUES(?,?,?,?,?,?,?)",    # as build's sync writes it
         (now.isoformat(), "sync", "authority", "found a new signer,", "nadia@desk.coop", "", "{}"))
    seen = []
    for _ in range(2):
        demo.stage(str(d))
        rows = db.all("SELECT at, actor, kind, action, subject FROM audit ORDER BY id")
        ats = [datetime.fromisoformat(r["at"]) for r in rows]
        assert ats == sorted(ats) and len(rows) > 20
        assert timedelta(minutes=29) < now - ats[-1] < timedelta(minutes=35)
        assert len({tuple(r.values()) for r in rows}) == len(rows)
        seen.append([tuple(r.values())[1:] for r in rows])
    assert seen[0] == seen[1]
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        db.x("DELETE FROM audit")
