"""Trust verification against real git repositories (requirement 7.6, 10.7, 10.8)."""

import json
import os
import shutil
import subprocess

import pytest

from appkata_core import devtools, sync
from appkata_core.db import DB
from appkata_core.http import Http

A, B = b"\x11" * 32, b"\x22" * 32
TABLE = "| App | Source | Tags | Trust | Rating |\n|---|---|---|---|---|\n"


def write(repo, text, path="AppKata.md"):
    full = os.path.join(repo, path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w") as f:
        f.write(text)
    subprocess.run(["git", "-C", repo, "add", "-A"], check=True)


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("APPKATA_DATA", str(tmp_path / "data"))
    repo = str(tmp_path / "reviews")
    subprocess.run(["git", "init", "-q", "-b", "main", repo], check=True)
    db = DB(str(tmp_path / "data" / "appkata.db"))
    return repo, db, str(tmp_path / "data")


def rows(db, tid):
    return {r["app"]: r for r in db.all("SELECT * FROM reviews WHERE trust_id=?", (tid,))}


def test_ssh_trust_lifecycle(env):
    repo, db, root = env
    write(repo, TABLE + "| LocalSend | https://github.com/localsend/localsend | foss | 5 | 4 |\n")
    devtools.commit(repo, "first", author="Jo", email="jo@desk.coop", ssh_seed=A)
    p = sync.preview_trust(Http(), repo)
    assert not p.error and p.apps == 1 and len(p.signers) == 1
    assert p.signers[0]["kind"] == "ssh" and p.signers[0]["email"] == "jo@desk.coop"
    tid = sync.add_trust(db, p, root)
    assert rows(db, tid)["LocalSend"]["trust"] == 5

    # a change signed by the authority is applied
    write(repo, TABLE + "| LocalSend | https://github.com/localsend/localsend | foss | 4 | 4 |\n")
    devtools.commit(repo, "second", author="Jo", email="jo@desk.coop", ssh_seed=A)
    sync.sync_trust(db, Http(), tid, root)
    t = db.one("SELECT * FROM trusts WHERE id=?", (tid,))
    assert rows(db, tid)["LocalSend"]["trust"] == 4 and t["problem"] == ""

    # an unsigned change is not applied, and flagged (10.8)
    write(repo, TABLE + "| LocalSend | https://github.com/localsend/localsend | foss | 0 | 1 |\n")
    devtools.commit(repo, "sneaky", author="Eve", email="eve@x.org")
    sync.sync_trust(db, Http(), tid, root)
    t = db.one("SELECT * FROM trusts WHERE id=?", (tid,))
    assert t["problem"] == "unsigned" and rows(db, tid)["LocalSend"]["trust"] == 4


def test_new_signer_needs_approval(env):
    repo, db, root = env
    write(repo, TABLE + "| Krita | https://invent.kde.org/graphics/krita | foss | 5 | 5 |\n")
    devtools.commit(repo, "first", email="jo@desk.coop", ssh_seed=A)
    tid = sync.add_trust(db, sync.preview_trust(Http(), repo), root)
    write(repo, TABLE + "| Krita | https://invent.kde.org/graphics/krita | foss | 4 | 5 |\n")
    devtools.commit(repo, "by nadia", author="Nadia", email="nadia@desk.coop", ssh_seed=B)
    sync.sync_trust(db, Http(), tid, root)
    t = db.one("SELECT * FROM trusts WHERE id=?", (tid,))
    pend = db.one("SELECT * FROM authorities WHERE trust_id=? AND pending=1", (tid,))
    assert t["problem"] == "unknown-signer" and pend["email"] == "nadia@desk.coop" and pend["pending_commits"] == 1
    assert rows(db, tid)["Krita"]["trust"] == 5
    sync.trust_signer(db, tid, pend["fingerprint"])           # requirement 7.6.6
    sync.sync_trust(db, Http(), tid, root)
    assert rows(db, tid)["Krita"]["trust"] == 4
    assert db.one("SELECT problem FROM trusts WHERE id=?", (tid,))["problem"] == ""


def test_disabled_authority_and_rewritten_history(env):
    repo, db, root = env
    write(repo, TABLE + "| Zettlr | https://github.com/Zettlr/Zettlr | foss | 4 | 4 |\n")
    devtools.commit(repo, "first", ssh_seed=A)
    tid = sync.add_trust(db, sync.preview_trust(Http(), repo), root)
    db.x("UPDATE authorities SET enabled=0 WHERE trust_id=?", (tid,))
    write(repo, TABLE + "| Zettlr | https://github.com/Zettlr/Zettlr | foss | 3 | 4 |\n")
    devtools.commit(repo, "second", ssh_seed=A)
    sync.sync_trust(db, Http(), tid, root)
    assert db.one("SELECT problem FROM trusts WHERE id=?", (tid,))["problem"] == "disabled"
    # rewrite history: replace both commits with a new root commit
    db.x("UPDATE authorities SET enabled=1 WHERE trust_id=?", (tid,))
    subprocess.run(["git", "-C", repo, "checkout", "-q", "--orphan", "other"], check=True)
    devtools.commit(repo, "rewritten", ssh_seed=A)
    subprocess.run(["git", "-C", repo, "branch", "-q", "-M", "other", "main"], check=True)
    sync.sync_trust(db, Http(), tid, root)
    t = db.one("SELECT * FROM trusts WHERE id=?", (tid,))
    assert t["problem"] == "rewritten" and rows(db, tid)["Zettlr"]["trust"] == 4


def test_unsigned_trust_is_refused(env):
    repo, db, root = env
    write(repo, TABLE + "| X | https://github.com/a/b | | 3 | 3 |\n", "docs/AppKata.md")
    devtools.commit(repo, "unsigned")
    p = sync.preview_trust(Http(), repo)
    assert "isn't signed" in p.error and p.path == "docs/AppKata.md"


@pytest.mark.skipif(not shutil.which("gpg"), reason="gpg not installed")
def test_gpg_trust_with_published_key(env, tmp_path):
    repo, db, root = env
    home = str(tmp_path / "gnupg")
    fpr, pub = devtools.gpg_keygen(home, "Mara Lindqvist <mara@lindqvist.se>")
    write(repo, TABLE + "| KeePassXC | https://github.com/keepassxreboot/keepassxc | foss, offline | 5 | 5 |\n")
    write(repo, pub, ".appkata/keys/mara.asc")
    devtools.commit(repo, "first", author="Mara", email="mara@lindqvist.se", gpg_key=fpr, gnupghome=home)
    p = sync.preview_trust(Http(), repo)
    assert not p.error, p.error
    s = p.signers[0]
    assert s["kind"] == "gpg" and s["fingerprint"] == fpr and s["name"] == "Mara Lindqvist"
    tid = sync.add_trust(db, p, root)
    write(repo, TABLE + "| KeePassXC | https://github.com/keepassxreboot/keepassxc | foss | 5 | 4 |\n")
    devtools.commit(repo, "second", author="Mara", email="mara@lindqvist.se", gpg_key=fpr, gnupghome=home)
    sync.sync_trust(db, Http(), tid, root)
    r = rows(db, tid)["KeePassXC"]
    assert r["rating"] == 4 and json.loads(r["tags"]) == ["foss"]


def test_export_includes_trust_score(tmp_path):
    from appkata_core import transfer
    from appkata_core.db import DB, now
    db = DB(str(tmp_path / "a.db"))
    db.x("INSERT INTO trusts(url, name, path, enabled, added_at) VALUES(?,?,?,?,?)", ("https://example.org/r", "r", "AppKata.md", 1, now()))
    db.x("UPDATE trusts SET score=5")
    assert transfer.export(db, {})["trusts"][0]["score"] == 5


def test_appkata_itself_has_trust_5(tmp_path):
    # requirement 10.6.4: you're running it, so a Trust's lower value (or a veto) doesn't apply
    from appkata_core import APPKATA_REPO, catalog
    from appkata_core.db import DB, now
    db = DB(str(tmp_path / "a.db"))
    tid = db.x("INSERT INTO trusts(url, name, path, enabled, verified_commit, added_at) VALUES(?,?,?,?,?,?)",
               ("https://example.org/r", "r", "AppKata.md", 1, "abc1234", now())).lastrowid
    db.x("INSERT INTO reviews(trust_id, url, app, source, tags, trust, rating, section, settings) VALUES(?,?,?,?,?,?,?,?,?)",
         (tid, APPKATA_REPO, "AppKata", APPKATA_REPO, "[]", 0, 2, "", "{}"))
    a = next(x for x in catalog.build(db) if x["url"] == APPKATA_REPO)
    assert a["trust"] == 5.0 and not a["vetoed"] and a["rating"] == 2
