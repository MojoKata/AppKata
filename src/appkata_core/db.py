"""The local SQLite cache (requirement 1.8, 9.1). Versioned schema, migrated on open."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime, timezone

SCHEMA_VERSION = 7
SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS sources(
    url TEXT PRIMARY KEY, input_url TEXT, releases_page INTEGER DEFAULT 0, forge TEXT,
    settings TEXT DEFAULT '{}', added_at TEXT);
CREATE TABLE IF NOT EXISTS apps(
    url TEXT PRIMARY KEY, name TEXT, description TEXT, summary TEXT, readme TEXT, raw_base TEXT,
    icon TEXT, hero TEXT, forge TEXT, host TEXT, repo TEXT, releases TEXT DEFAULT '[]',
    archived INTEGER DEFAULT 0, fetched_at TEXT, error TEXT, error_code TEXT, error_extra TEXT DEFAULT '{}');
CREATE TABLE IF NOT EXISTS trusts(
    id INTEGER PRIMARY KEY, url TEXT UNIQUE, name TEXT, path TEXT, own INTEGER DEFAULT 0,
    enabled INTEGER DEFAULT 1, verified_commit TEXT, verified_at TEXT, synced_at TEXT,
    problem TEXT DEFAULT '', problem_detail TEXT DEFAULT '', warnings TEXT DEFAULT '[]', added_at TEXT,
    score INTEGER DEFAULT 3);
CREATE TABLE IF NOT EXISTS authorities(
    id INTEGER PRIMARY KEY, trust_id INTEGER REFERENCES trusts(id) ON DELETE CASCADE, kind TEXT,
    fingerprint TEXT, key TEXT, name TEXT, email TEXT, enabled INTEGER DEFAULT 1, pending INTEGER DEFAULT 0,
    first_commit TEXT, first_at TEXT, last_commit TEXT, last_at TEXT, pending_commits INTEGER DEFAULT 0,
    UNIQUE(trust_id, fingerprint));
CREATE TABLE IF NOT EXISTS reviews(
    trust_id INTEGER REFERENCES trusts(id) ON DELETE CASCADE, url TEXT, app TEXT, source TEXT,
    tags TEXT DEFAULT '[]', trust INTEGER, rating INTEGER, section TEXT DEFAULT '', settings TEXT DEFAULT '{}',
    PRIMARY KEY(trust_id, url));
CREATE TABLE IF NOT EXISTS installs(
    url TEXT PRIMARY KEY, name TEXT, version TEXT, date TEXT, asset TEXT, kind TEXT,
    record TEXT DEFAULT '{}', installed_at TEXT);
CREATE TABLE IF NOT EXISTS app_settings(url TEXT PRIMARY KEY, pinned TEXT, min_age INTEGER, install TEXT);
CREATE TABLE IF NOT EXISTS foreign_installs(url TEXT PRIMARY KEY, location TEXT, version TEXT, checked_at TEXT,
    adopt TEXT DEFAULT '');
-- package channels (requirement 16): Trusts' channel lines, the project's AppStream ID, link checks
CREATE TABLE IF NOT EXISTS app_meta(url TEXT PRIMARY KEY, appstream_id TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS channel_checks(
    url TEXT, kind TEXT, value TEXT, state TEXT DEFAULT 'unchecked', detail TEXT DEFAULT '', verified INTEGER,
    etag TEXT DEFAULT '', commit_seen TEXT DEFAULT '', version_seen TEXT DEFAULT '', tag TEXT DEFAULT '',
    built_from TEXT DEFAULT '', checked_at TEXT, PRIMARY KEY(url, kind, value));
"""


# The Audit (requirement 13): append-only. Triggers refuse every UPDATE and DELETE.
AUDIT_SCHEMA = """
CREATE TABLE IF NOT EXISTS audit(
    id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, actor TEXT NOT NULL, kind TEXT NOT NULL,
    action TEXT NOT NULL, subject TEXT NOT NULL, url TEXT DEFAULT '', detail TEXT DEFAULT '');
CREATE INDEX IF NOT EXISTS audit_kind ON audit(kind, id);
CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit
    BEGIN SELECT RAISE(ABORT, 'the audit is append-only'); END;
CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit
    BEGIN SELECT RAISE(ABORT, 'the audit is append-only'); END;
"""


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class DB:
    def __init__(self, path: str):
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self.path = path
        self.lock = threading.RLock()
        self.c = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.c.row_factory = sqlite3.Row
        self.c.execute("PRAGMA foreign_keys = ON")
        self.c.execute("PRAGMA journal_mode = WAL")
        self._migrate()

    def _migrate(self) -> None:
        with self.lock:
            self.c.executescript(SCHEMA)
            row = self.c.execute("SELECT value FROM meta WHERE key='schema'").fetchone()
            v = int(row[0]) if row else 0
            if v < 2:
                self.c.executescript(AUDIT_SCHEMA)
            if v < 3:      # the install choice for each app (requirement 4.9)
                cols = [r[1] for r in self.c.execute("PRAGMA table_info(app_settings)")]
                if "install" not in cols:
                    self.c.execute("ALTER TABLE app_settings ADD COLUMN install TEXT")
            if v < 4:      # reviewers' recommended install options (requirement 10.3.1)
                cols = [r[1] for r in self.c.execute("PRAGMA table_info(reviews)")]
                if "settings" not in cols:
                    self.c.execute("ALTER TABLE reviews ADD COLUMN settings TEXT DEFAULT '{}'")
            if v < 5:      # each Trust's Score, 1–5 stars (requirement 10.6.2)
                cols = [r[1] for r in self.c.execute("PRAGMA table_info(trusts)")]
                if "score" not in cols:
                    self.c.execute("ALTER TABLE trusts ADD COLUMN score INTEGER DEFAULT 3")
            if v < 6:      # a foreign install a package channel matches exactly can be adopted (requirement 16.4.2)
                cols = [r[1] for r in self.c.execute("PRAGMA table_info(foreign_installs)")]
                if "adopt" not in cols:
                    self.c.execute("ALTER TABLE foreign_installs ADD COLUMN adopt TEXT DEFAULT ''")
            if v < 7:      # Trusts' channel lines are read from their reviews' settings now (requirement 16.1.3)
                self.c.execute("DROP TABLE IF EXISTS trust_channels")
            if v < SCHEMA_VERSION:
                self.c.execute("INSERT OR REPLACE INTO meta VALUES('schema', ?)", (str(SCHEMA_VERSION),))

    def x(self, sql: str, args=()) -> sqlite3.Cursor:
        with self.lock:
            return self.c.execute(sql, args)

    def all(self, sql: str, args=()) -> list[dict]:
        with self.lock:
            return [dict(r) for r in self.c.execute(sql, args).fetchall()]

    def one(self, sql: str, args=()) -> dict | None:
        with self.lock:
            r = self.c.execute(sql, args).fetchone()
            return dict(r) if r else None

    def tx(self):
        return _Tx(self)

    # settings (JSON values)
    def get(self, key: str, default=None):
        r = self.one("SELECT value FROM settings WHERE key=?", (key,))
        if not r:
            return default
        try:
            return json.loads(r["value"])
        except ValueError:
            return default

    def put(self, key: str, value) -> None:
        self.x("INSERT OR REPLACE INTO settings VALUES(?, ?)", (key, json.dumps(value)))


class _Tx:
    def __init__(self, db: DB):
        self.db = db

    def __enter__(self):
        self.db.lock.acquire()
        self.db.c.execute("BEGIN IMMEDIATE")
        return self.db

    def __exit__(self, et, ev, tb):
        try:
            self.db.c.execute("COMMIT" if et is None else "ROLLBACK")
        finally:
            self.db.lock.release()
        return False
