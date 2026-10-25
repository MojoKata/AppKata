"""The Audit (requirement 13), the App log (14) and Explore (7.7)."""

import base64
import hashlib
import json
import logging
import os
import socket
import sqlite3
import struct
import threading

import pytest

from appkata_core import applog, audit, explore, nostr
from appkata_core.db import DB
from appkata_core.http import Http

from test_forges import opener


# ---------------------------------------------------------------- audit
def test_audit_is_append_only_and_pages(tmp_path):
    db = DB(str(tmp_path / "a.db"))
    for i in range(250):
        audit.record(db, "you" if i % 2 else "sync", "app", "installed", f"App {i}", f"https://github.com/x/app{i}", {"version": f"1.{i}"})
    first = audit.page(db)
    assert len(first) == 100 and first[0]["subject"] == "App 249"          # newest first
    second = audit.page(db, before=first[-1]["id"])
    assert second[0]["subject"] == "App 149" and len(audit.page(db, before=second[-1]["id"])) == 50
    assert [r["subject"] for r in audit.page(db, text="App 7")][:2] == ["App 79", "App 78"]
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        db.x("DELETE FROM audit")
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        db.x("UPDATE audit SET subject='x' WHERE id=1")
    assert audit.count(db) == 250


# ---------------------------------------------------------------- app log
def test_two_file_rotation(tmp_path):
    h = applog.TwoFileHandler(str(tmp_path), limit=1000)
    h.setFormatter(logging.Formatter("%(message)s"))
    lg = logging.getLogger("test.rotation")
    lg.addHandler(h); lg.setLevel(logging.INFO); lg.propagate = False
    for i in range(60):
        lg.info("line %03d %s", i, "x" * 40)
    cur, prev = tmp_path / "AppKata.log", tmp_path / "AppKata-prev.log"
    assert cur.exists() and prev.exists() and not (tmp_path / "AppKata.log.1").exists()
    assert os.path.getsize(cur) <= 1000 and os.path.getsize(prev) <= 1000
    joined = prev.read_text() + cur.read_text()
    assert "line 059" in cur.read_text() and joined.index("line 040") < joined.index("line 059")
    assert "line 000" not in joined                                          # the oldest are gone: fixed size
    h.close()


def test_combined_log(tmp_path, monkeypatch):
    monkeypatch.setenv("APPKATA_LOG_DIR", str(tmp_path))
    (tmp_path / "AppKata-prev.log").write_text("older\n")
    (tmp_path / "AppKata.log").write_text("newer\n")
    with open(applog.combined()) as f:
        assert f.read() == "older\nnewer\n"


# ---------------------------------------------------------------- explore
def test_gitlab_and_codeberg_search():
    http = Http(opener=opener({
        "https://gitlab.com/api/v4/projects?search=inkscape": [
            {"name": "inkscape", "path_with_namespace": "inkscape/inkscape", "namespace": {"full_path": "inkscape"},
             "web_url": "https://gitlab.com/inkscape/inkscape", "description": "Vector graphics", "star_count": 3500,
             "last_activity_at": "2026-09-30T10:00:00Z"}],
        "https://codeberg.org/api/v1/repos/search?q=tenacity": {"ok": True, "data": [
            {"name": "tenacity", "owner": {"login": "tenacityteam"}, "html_url": "https://codeberg.org/tenacityteam/tenacity",
             "description": "Audio editor", "stars_count": 900, "updated_at": "2026-09-01T00:00:00Z"}]},
    }))
    g = explore.search(http, "gitlab", "inkscape")["matches"][0]
    assert (g["owner"], g["name"], g["stars"], g["url"]) == ("inkscape", "inkscape", 3500, "https://gitlab.com/inkscape/inkscape")
    c = explore.search(http, "codeberg", "tenacity")["matches"][0]
    assert c["owner"] == "tenacityteam" and c["addable"]


def test_github_search_falls_back_to_the_web_page():
    page = {"payload": {"blackbirdSearchRoute": {"results": [
        {"hl_name": "keepassxreboot/<em>keepassxc</em>", "hl_trunc_description": "A <em>password</em> manager", "followers": 25000,
         "language": "C++", "archived": False, "repo": {"repository": {"updated_at": "2026-09-30T00:00:00Z"}}}]}}}
    http = Http(opener=opener({"https://api.github.com/search": 403, "https://github.com/search?q=": page}))
    m = explore.search(http, "github", "password manager")["matches"][0]
    assert m["url"] == "https://github.com/keepassxreboot/keepassxc" and m["description"] == "A password manager"


class FakeRelay:
    """A tiny WebSocket Nostr relay on localhost that answers one REQ with stored events."""

    def __init__(self, events):
        self.events = events
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0)); self.sock.listen(1)
        self.url = f"ws://127.0.0.1:{self.sock.getsockname()[1]}"
        threading.Thread(target=self.serve, daemon=True).start()

    def serve(self):
        c, _ = self.sock.accept()
        req = b""
        while b"\r\n\r\n" not in req:
            req += c.recv(4096)
        key = next(l.split(b": ", 1)[1] for l in req.split(b"\r\n") if l.lower().startswith(b"sec-websocket-key"))
        acc = base64.b64encode(hashlib.sha1(key + b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11").digest())
        c.sendall(b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: " + acc + b"\r\n\r\n")
        hdr = c.recv(2); n = hdr[1] & 0x7f
        if n == 126:
            n = struct.unpack(">H", c.recv(2))[0]
        mask = c.recv(4); data = b""
        while len(data) < n:
            data += c.recv(n - len(data))
        sub = json.loads(bytes(b ^ mask[i % 4] for i, b in enumerate(data)))[1]
        for msg in [["EVENT", sub, e] for e in self.events] + [["EOSE", sub]]:
            p = json.dumps(msg).encode()
            c.sendall(bytes([0x81, 126]) + struct.pack(">H", len(p)) + p if len(p) > 125 else bytes([0x81, len(p)]) + p)
        c.close()


def test_ngit_search_over_a_relay():
    pk = "3bf0c63fcb93463407af97a5e5ee64fa883d107ef9e558472c4eb9aaaefa459d"
    relay = FakeRelay([
        {"kind": 30617, "pubkey": pk, "created_at": 1790000000, "tags": [["d", "ngit"], ["name", "ngit"], ["description", "nostr plugin for git"]]},
        {"kind": 30617, "pubkey": pk, "created_at": 1780000000, "tags": [["d", "other"], ["name", "Other"], ["description", "unrelated"]]},
    ])
    matches, errors = explore.ngit("git plugin", [relay.url])
    assert not errors and len(matches) == 1
    m = matches[0]
    assert m.name == "ngit" and not m.addable and m.page == f"https://gitworkshop.dev/{nostr.npub(pk)}/ngit"
    assert nostr.npub(pk) == "npub180cvv07tjdrrgpa0j7j7tmnyl2yr6yr7l8j4s3evf6u64th6gkwsyjh6w6"


def test_ngit_reports_unreachable_relays():
    matches, errors = explore.ngit("x", ["ws://127.0.0.1:9"])
    assert matches == [] and errors and "127.0.0.1:9" in errors[0]


def test_older_version_files_fetched_on_demand(tmp_path):
    """The version list can install a release whose files the last sync didn't read (requirement 5.7.5)."""
    from appkata_core import sync
    db = DB(str(tmp_path / "a.db"))
    url = "https://git.example.net/team/app"
    db.x("INSERT INTO apps(url, name, forge, releases) VALUES(?,?,?,?)", (url, "App", "forgejo", json.dumps(
        [{"tag": "v2.0.0", "version": "2.0.0", "date": "2026-02-01", "assets": [{"name": "a"}]},
         {"tag": "v1.0.0", "version": "1.0.0", "date": "2025-02-01", "assets": []}])))
    http = Http(opener=opener({"https://git.example.net/api/v1/repos/team/app/releases": [
        {"tag_name": "v1.0.0", "published_at": "2025-02-01T00:00:00Z",
         "assets": [{"name": "app-1.0.0-x86_64.AppImage", "browser_download_url": "https://git.example.net/f", "size": 7}]}]}))
    rel = sync.ensure_assets(db, http, url, "1.0.0")
    assert rel["assets"][0]["name"] == "app-1.0.0-x86_64.AppImage"
    stored = json.loads(db.one("SELECT releases FROM apps WHERE url=?", (url,))["releases"])
    assert stored[1]["assets"][0]["size"] == 7


@pytest.mark.skipif(os.name == "nt", reason="Linux desktop files; Windows: tests/test_windows.py")
def test_autostart_and_links(tmp_path, monkeypatch):
    from appkata_core import desktop
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    p = desktop.set_autostart(True)
    assert "--tray" in open(p).read() and "Exec=" in open(p).read()
    desktop.set_autostart(False)
    assert not os.path.exists(p)
    assert desktop.register_scheme(True) and "x-scheme-handler/appkata" in open(desktop.scheme_entry_path()).read()
    assert desktop.parse_link("appkata://add/https%3A%2F%2Fgithub.com%2Flocalsend%2Flocalsend") == "https://github.com/localsend/localsend"
    assert desktop.parse_link("https://x") == ""


def test_export_import_roundtrip(tmp_path, monkeypatch):
    """Sources, app settings and Trusts with their Authorities; tokens never (requirement 11.2)."""
    import subprocess
    from appkata_core import devtools, sync, transfer
    monkeypatch.setenv("APPKATA_DATA", str(tmp_path / "data"))
    repo = str(tmp_path / "rev")
    subprocess.run(["git", "init", "-q", "-b", "main", repo], check=True)
    with open(os.path.join(repo, "AppKata.md"), "w") as f:
        f.write("| App | Source | Tags | Trust | Rating |\n|---|---|---|---|---|\n| X | https://github.com/a/x | foss | 4 | 4 |\n")
    subprocess.run(["git", "-C", repo, "add", "-A"], check=True)
    devtools.commit(repo, "r", ssh_seed=b"\x33" * 32)
    db = DB(str(tmp_path / "a.db"))
    sync.add_trust(db, sync.preview_trust(Http(), repo), str(tmp_path / "data"))
    db.x("INSERT INTO sources(url, input_url, settings, added_at) VALUES('https://github.com/a/y','https://github.com/a/y','{\"track_only\": true}','x')")
    db.x("INSERT INTO app_settings(url, pinned) VALUES('https://github.com/a/y','1.0')")
    db.put("tokens", {"github.com": "secret"})
    data = transfer.export(db, {"theme": "dark", "reviewPath": "/home/me/AppKata.md"})
    out = tmp_path / "e.json"
    transfer.write(str(out), data)
    text = out.read_text()
    assert "secret" not in text and "reviewPath" not in text and data["trusts"][0]["authorities"][0]["kind"] == "ssh"
    db2 = DB(str(tmp_path / "b.db"))
    res = transfer.apply(db2, Http(), transfer.read(str(out)), str(tmp_path / "data2"))
    assert res == {"sources": 1, "trusts": 1, "skipped": 0, "problems": []}
    assert json.loads(db2.one("SELECT settings FROM sources")["settings"]) == {"track_only": True}
    assert db2.one("SELECT trust FROM reviews")["trust"] == 4 and db2.one("SELECT pinned FROM app_settings")["pinned"] == "1.0"
    assert transfer.apply(db2, Http(), transfer.read(str(out)), str(tmp_path / "data2"))["skipped"] == 2
    lst = tmp_path / "urls.txt"
    lst.write_text("# my apps\nhttps://github.com/a/z\nnot a url\ngit@github.com:a/y.git\n")
    assert transfer.apply(db2, Http(), transfer.read(str(lst)))["sources"] == 1
