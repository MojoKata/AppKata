"""Import and export (requirement 11.2): Sources, Trusts with their Authorities, and settings, as
JSON. Tokens are never exported. A plain text list of URLs can be imported as Sources."""

from __future__ import annotations

import json
import os
import shutil
import tempfile

from . import gitsig, sync, trustfile, urls
from .db import DB, now
from .http import Http

FORMAT = "appkata-export"
VERSION = 1
SKIP_PREFS = {"reviewPath"}          # machine-specific


def export(db: DB, prefs: dict) -> dict:
    trusts = []
    for t in db.all("SELECT * FROM trusts WHERE own=0 ORDER BY id"):
        trusts.append({"url": t["url"], "name": t["name"], "path": t["path"], "enabled": bool(t["enabled"]), "score": t["score"] or 3,
                       "authorities": [{k: a[k] for k in ("kind", "fingerprint", "key", "name", "email")} | {"enabled": bool(a["enabled"])}
                                       for a in db.all("SELECT * FROM authorities WHERE trust_id=? AND pending=0", (t["id"],))]})
    return {"format": FORMAT, "version": VERSION, "exported": now(),
            "sources": [{"url": s["url"], "input_url": s["input_url"], "settings": json.loads(s["settings"] or "{}")}
                        for s in db.all("SELECT * FROM sources ORDER BY added_at, url")],
            "app_settings": [{k: r[k] for k in ("url", "pinned", "min_age")} for r in db.all("SELECT * FROM app_settings")],
            "trusts": trusts,
            "settings": {k: v for k, v in prefs.items() if k not in SKIP_PREFS}}


def write(path: str, data: dict) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1, ensure_ascii=False)
    os.replace(tmp, path)


def read(path: str) -> dict:
    """An export file, or a plain list of URLs (one per line; # comments)."""
    with open(path, encoding="utf-8") as f:
        text = f.read()
    try:
        data = json.loads(text)
        if isinstance(data, dict) and data.get("format") == FORMAT:
            return data
        raise ValueError("not an AppKata export")
    except ValueError:
        lines = [l.strip() for l in text.splitlines() if l.strip() and not l.lstrip().startswith("#")]
        good = [l for l in lines if urls.try_normalize(l)]
        if not good:
            raise ValueError("neither an AppKata export nor a list of repository URLs") from None
        return {"format": FORMAT, "version": VERSION, "sources": [{"url": l} for l in good], "trusts": [], "settings": {}}


def apply(db: DB, http: Http, data: dict, root: str | None = None) -> dict:
    """Add what's new; existing Sources and Trusts are left as they are. Returns counts and problems."""
    out = {"sources": 0, "trusts": 0, "skipped": 0, "problems": []}
    for s in data.get("sources", []):
        u = urls.try_normalize(s.get("url", ""))
        if not u:
            out["problems"].append(f"not a repository URL: {s.get('url')}")
            continue
        if db.one("SELECT 1 FROM sources WHERE url=?", (u,)):
            out["skipped"] += 1
            continue
        db.x("INSERT INTO sources(url, input_url, settings, added_at) VALUES(?,?,?,?)",
             (u, s.get("input_url") or s["url"], json.dumps(s.get("settings") or {}), now()))
        out["sources"] += 1
    for r in data.get("app_settings", []):
        db.x("INSERT OR IGNORE INTO app_settings(url, pinned, min_age) VALUES(?,?,?)", (r["url"], r.get("pinned"), r.get("min_age")))
    for t in data.get("trusts", []):
        if db.one("SELECT 1 FROM trusts WHERE url=?", (t["url"],)):
            out["skipped"] += 1
            continue
        err = _import_trust(db, t, root)
        if err:
            out["problems"].append(f"{t.get('name') or t['url']}: {err}")
        else:
            out["trusts"] += 1
    return out


def _import_trust(db: DB, t: dict, root: str | None) -> str:
    """A Trust from an export keeps its Authorities: its current AppKata.md is accepted when the
    commit that last changed it is signed by one of them (requirement 10.7)."""
    loc = gitsig.locate(t["url"])
    dest = tempfile.mkdtemp(prefix="appkata-import-")
    try:
        tip = gitsig.fetch(loc, os.path.join(dest, "repo"))
        repo = os.path.join(dest, "repo")
        path = gitsig.find_file(repo, tip, t.get("path") or loc.path)
        commit = gitsig.last_commit_touching(repo, tip, path)
        auths = t.get("authorities") or []
        chk = gitsig.check_commit(repo, commit, [a["key"] for a in auths if a["kind"] == "gpg" and a.get("key")])
        fps = {a["fingerprint"].upper() for a in auths if a.get("enabled", True)}
        if chk.status != "good" or not chk.signer or chk.signer.fingerprint.upper() not in fps:
            return f"the latest change ({commit[:7]}) isn't signed by one of its authorities"
        tf = trustfile.parse(gitsig.show(repo, commit, path))
        final = sync.trust_dir(t["url"], root)
        shutil.rmtree(final, ignore_errors=True)
        os.makedirs(os.path.dirname(final), exist_ok=True)
        shutil.move(repo, final)
        with db.tx():
            tid = db.x("""INSERT INTO trusts(url, name, path, enabled, verified_commit, verified_at, synced_at, warnings, added_at)
                          VALUES(?,?,?,?,?,?,?,?,?)""", (t["url"], t.get("name") or sync.trust_name(t["url"], ""), path,
                                                       int(t.get("enabled", True)), commit, now(), now(), json.dumps(tf.warnings),
                                                       now())).lastrowid
            db.x("UPDATE trusts SET score=? WHERE id=?", (max(1, min(5, int(t.get("score") or 3))), tid))
            for a in auths:
                db.x("""INSERT INTO authorities(trust_id, kind, fingerprint, key, name, email, enabled, first_commit, first_at)
                        VALUES(?,?,?,?,?,?,?,?,?)""", (tid, a["kind"], a["fingerprint"], a.get("key", ""), a.get("name", ""),
                                                      a.get("email", ""), int(a.get("enabled", True)), commit, now()))
            sync._store_reviews(db, tid, tf)
        return ""
    except gitsig.GitError as e:
        return str(e)
    finally:
        shutil.rmtree(dest, ignore_errors=True)
