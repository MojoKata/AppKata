"""The Audit (requirement 13): an immutable record of key operations, newest first."""

from __future__ import annotations

import json
import logging

from .db import DB, now

log = logging.getLogger("appkata.audit")

KINDS = ("app", "source", "trust", "authority", "review", "setting")


def record(db: DB, actor: str, kind: str, action: str, subject: str, url: str = "", detail=None) -> None:
    """actor: "you", "sync", or "system" for changes found made by something else (requirement
    13.3, 16.9); kind: one of KINDS; action: a verb such as "installed"."""
    d = detail if isinstance(detail, str) else json.dumps(detail, ensure_ascii=False) if detail else ""
    db.x("INSERT INTO audit(at, actor, kind, action, subject, url, detail) VALUES(?,?,?,?,?,?,?)",
         (now(), actor, kind, action, subject, url or "", d))
    log.info("audit: %s %s %s %s%s", actor, kind, action, subject, f" ({d})" if d else "")


def page(db: DB, before: int = 0, limit: int = 100, kind: str = "", text: str = "") -> list[dict]:
    """Up to `limit` entries older than id `before` (0 = newest), optionally filtered."""
    where, args = [], []
    if before:
        where.append("id < ?"); args.append(before)
    if kind.startswith("actor:"):          # the System filter (requirement 16.9)
        where.append("actor = ?"); args.append(kind[6:])
    elif kind:
        where.append("kind = ?"); args.append(kind)
    if text:
        where.append("(subject LIKE ? OR action LIKE ? OR detail LIKE ? OR url LIKE ?)")
        args += [f"%{text}%"] * 4
    sql = "SELECT * FROM audit" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY id DESC LIMIT ?"
    return db.all(sql, args + [limit])


def count(db: DB) -> int:
    return db.one("SELECT COUNT(*) n FROM audit")["n"]
