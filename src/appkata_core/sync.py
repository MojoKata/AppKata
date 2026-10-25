"""Sync (requirement 9.2): refresh every Catalog app's releases and metadata, and every Trust."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import logging

from . import audit, channels, forges, gitsig, metadata, trustfile, urls
from .db import DB, now
from .http import Http, NotFound, RateLimited, SourceError, Unreachable
from .platform import data_dir

MAX_IMAGE = 8 << 20
log = logging.getLogger("appkata.sync")


def cache_dir(url: str, root: str | None = None) -> str:
    d = os.path.join(root or data_dir(), "cache", hashlib.sha1(url.encode()).hexdigest()[:16])
    os.makedirs(d, exist_ok=True)
    return d


def _ext(name: str, data: bytes) -> str:
    if data[:4] == b"\x89PNG":
        return ".png"
    if data[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return ".gif"
    head = data[:512].lstrip().lower()
    if head.startswith(b"<svg") or b"<svg" in head:
        return ".svg"
    return os.path.splitext(name)[1].lower() or ".img"


def _save_image(http: Http, url: str, dest_base: str, token_host: str | None = None) -> str:
    data = http.bytes(url, token_host=token_host, max_bytes=MAX_IMAGE)
    ext = _ext(url, data)
    if ext not in (".png", ".jpg", ".svg", ".webp", ".gif"):
        raise Unreachable("not an image")
    for old in os.listdir(os.path.dirname(dest_base)):
        if old.startswith(os.path.basename(dest_base) + "."):
            os.remove(os.path.join(os.path.dirname(dest_base), old))
    path = dest_base + ext
    with open(path, "wb") as f:
        f.write(data)
    return path


def rel_to_root(path: str, root: str | None) -> str:
    """Cache paths are stored relative to the data folder, so it can move."""
    return os.path.relpath(path, root or data_dir()) if path else ""


def release_dict(r: forges.Release) -> dict:
    return {"tag": r.tag, "name": r.name, "version": r.version, "date": r.date, "prerelease": r.prerelease,
            "notes": r.notes[:20000], "html_url": r.html_url,
            "assets": [{"name": a.name, "url": a.url, "size": a.size, "digest": a.digest, "content_type": a.content_type}
                       for a in r.assets]}


# ---------------------------------------------------------------- apps
def sync_app(db: DB, http: Http, url: str, root: str | None = None) -> None:
    """Releases, README, icon and hero for one app (Source or Trust-listed; requirement 3, 9.2.3)."""
    src = db.one("SELECT * FROM sources WHERE url=?", (url,)) or {}
    settings = json.loads(src.get("settings") or "{}")
    repo = urls.parse(url)
    old = db.one("SELECT * FROM apps WHERE url=?", (url,)) or {}
    try:
        if repo.kind != "forge":
            raise forges.Unsupported("ngit sources aren't supported yet")
        from .catalog import recommended_for          # a Trust's recommended Source settings (requirement 10.3.1)
        rec = recommended_for(db, url)[0]
        kind = settings.get("forge") or rec.get("forge") or src.get("forge") or old.get("forge") or None
        if not kind:
            kind = forges.detect(http, repo.host)
        f = forges.forge_for(http, repo, kind)
        info = f.info()
        rels = f.releases()
        if not rels and settings.get("track_only"):
            rels = f.tags()
        for r in rels:           # "latest", "nightly", "continuous": moving tags, not versions
            if not any(ch.isdigit() for ch in r.version):
                r.prerelease = True
        rels.sort(key=lambda r: (r.date or "", r.version), reverse=True)
        try:
            paths = f.tree(info.default_branch)
        except SourceError:
            paths = []
        readme, readme_path = f.readme(info.default_branch, paths) if paths else ("", "")
        raw_base = f.raw_url("", info.default_branch).rstrip("/")
        d = cache_dir(url, root)
        icon = os.path.join(root or data_dir(), old["icon"]) if old.get("icon") else ""
        hero = ""
        meta_info: dict = {}
        for mp in metadata.metainfo_paths(paths)[:2]:
            try:
                meta_info = metadata.parse_metainfo(f.raw(mp, info.default_branch).decode("utf-8", "replace"))
                if meta_info:
                    break
            except SourceError:
                pass
        # icon (requirement 3.2): manifest → metainfo → fastlane / icon files → owner avatar
        icon_urls = ([meta_info["icon"]] if meta_info.get("icon") else []) + \
            [f.raw_url(p, info.default_branch) for p in metadata.icon_candidates(paths, info.name)[:4]] + \
            ([info.avatar_url] if info.avatar_url else [])
        for iu in icon_urls:
            try:
                icon = _save_image(http, iu, os.path.join(d, "icon"), token_host=repo.host)
                break
            except SourceError:
                continue
        # hero (requirement 3.3): metainfo screenshot → fastlane feature graphic → README image
        hero_urls = ([meta_info["screenshot"]] if meta_info.get("screenshot") else []) + \
            [f.raw_url(p, info.default_branch) for p in metadata.hero_candidates(paths)[:2]] + \
            [metadata.resolve(u, raw_base, os.path.dirname(readme_path)) for u in metadata.readme_images(readme)[:3]]
        for hu in hero_urls:
            if not hu.startswith("http"):
                continue
            try:
                hero = _save_image(http, hu, os.path.join(d, "hero"), token_host=repo.host)
                break
            except SourceError:
                continue
        summary = metadata.summary(readme, meta_info.get("summary") or info.description)
        with db.tx():
            db.x("""INSERT OR REPLACE INTO apps(url, name, description, summary, readme, raw_base, icon, hero, forge,
                    host, repo, releases, archived, fetched_at, error, error_code, error_extra)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,NULL,NULL,'{}')""",
                 (url, meta_info.get("name") if meta_info.get("name") and "@@" not in meta_info["name"] else info.name, info.description, summary, readme[:200000], raw_base,
                  rel_to_root(icon, root) if icon and os.path.isabs(icon) else icon,
                  rel_to_root(hero, root) if hero else "", kind, repo.host, repo.path, json.dumps([release_dict(r) for r in rels[:30]]),
                  int(info.archived), now()))
            if src and not src.get("forge"):
                db.x("UPDATE sources SET forge=? WHERE url=?", (kind, url))
            if meta_info.get("id"):          # links a Flatpak or package by its AppStream ID (requirement 16.1.3)
                db.x("INSERT OR REPLACE INTO app_meta(url, appstream_id) VALUES(?,?)", (url, meta_info["id"]))
    except SourceError as e:
        log.warning("%s: %s (%s)", url, e, e.code)
        extra = dict(e.extra)
        db.x("""INSERT INTO apps(url, name, host, repo, fetched_at, error, error_code, error_extra) VALUES(?,?,?,?,?,?,?,?)
                ON CONFLICT(url) DO UPDATE SET error=excluded.error, error_code=excluded.error_code,
                error_extra=excluded.error_extra, fetched_at=excluded.fetched_at""",
             (url, repo.name, repo.host, repo.path, now(), str(e), e.code, json.dumps(extra)))


# ---------------------------------------------------------------- trusts
def trust_dir(url: str, root: str | None = None) -> str:
    return os.path.join(root or data_dir(), "trusts", hashlib.sha1(url.encode()).hexdigest()[:16])


@dataclass
class Preview:
    """What adding a Trust would accept (requirement 7.6.2), shown before the user confirms."""
    url: str
    name: str
    path: str
    commit: str
    date: str
    signers: list[dict] = field(default_factory=list)   # {kind, fingerprint, key, name, email}
    apps: int = 0
    warnings: list[str] = field(default_factory=list)
    error: str = ""
    repo_dir: str = ""


def trust_name(url: str, content: str) -> str:
    try:
        r = urls.parse(url)
        if r.kind == "forge":
            return f"{r.owner.split('/')[-1]} / {r.name}" if r.owner else r.name
    except ValueError:
        pass
    m = re.search(r"^#\s+(.+)$", content or "", re.M)
    return m.group(1).strip() if m else os.path.basename(url.rstrip("/"))


def _lookup_gpg_key(http: Http, repo: str, commit: str, fpr: str) -> str:
    for k in gitsig.repo_gpg_keys(repo, commit):
        if any(i["fingerprint"].upper() == fpr.upper() for i in gitsig.gpg_key_info(k)):
            return k
    try:
        return http.text(f"https://keys.openpgp.org/vks/v1/by-fingerprint/{fpr.upper()}")
    except SourceError:
        return ""


def preview_trust(http: Http, url: str, root: str | None = None) -> Preview:
    loc = gitsig.locate(url)
    if not loc.clone_url:
        return Preview(url, "", loc.path, "", "", error="Only files in a git repository can be trusted (local files can't be signed).")
    dest = tempfile.mkdtemp(prefix="appkata-trust-")
    try:
        tip = gitsig.fetch(loc, os.path.join(dest, "repo"))
        repo = os.path.join(dest, "repo")
        path = gitsig.find_file(repo, tip, loc.path)
        commit = gitsig.last_commit_touching(repo, tip, path)
        content = gitsig.show(repo, commit, path)
        tf = trustfile.parse(content)
        chk = gitsig.check_commit(repo, commit)
        p = Preview(url, trust_name(url, content), path, commit, chk.date, apps=len(tf.rows), warnings=tf.warnings,
                    repo_dir=repo)
        if chk.status == "unsigned":
            p.error = f"The commit that last changed {path} ({commit[:7]}) isn't signed. A Trust needs signed changes."
            return p
        if chk.status == "nokey" and chk.signer:
            key = _lookup_gpg_key(http, repo, commit, chk.signer.fingerprint)
            if key:
                chk = gitsig.check_commit(repo, commit, [key])
                if chk.signer:
                    chk.signer.key = key
                    info = gitsig.gpg_key_info(key)
                    if info:
                        chk.signer.name, chk.signer.email = info[0]["name"] or chk.signer.name, info[0]["email"] or chk.signer.email
        if chk.status != "good" or not chk.signer:
            p.error = (f"The signature on {commit[:7]} couldn't be verified: {chk.reason or chk.status}." if chk.status != "nokey"
                       else f"The OpenPGP key {gitsig_short(chk.signer.fingerprint if chk.signer else '')} that signed {commit[:7]} "
                            "couldn't be found (looked in .appkata/keys/ and keys.openpgp.org).")
            return p
        s = chk.signer
        p.signers.append({"kind": s.kind, "fingerprint": s.fingerprint, "key": s.key, "name": s.name or chk.author,
                          "email": s.email or chk.author_email, "commit": commit, "date": chk.date})
        return p
    except gitsig.GitError as e:
        return Preview(url, "", loc.path, "", "", error=str(e))


def gitsig_short(fp: str) -> str:
    return fp[-16:] if len(fp) == 40 else fp


def add_trust(db: DB, p: Preview, root: str | None = None) -> int:
    """Create the Trust and its first Authorities (requirement 7.6.2, 10.7.1)."""
    dest = trust_dir(p.url, root)
    shutil.rmtree(dest, ignore_errors=True)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    shutil.move(p.repo_dir, dest)
    content = gitsig.show(dest, p.commit, p.path)
    tf = trustfile.parse(content)
    with db.tx():
        cur = db.x("""INSERT INTO trusts(url, name, path, verified_commit, verified_at, synced_at, warnings, added_at)
                      VALUES(?,?,?,?,?,?,?,?)""", (p.url, p.name, p.path, p.commit, now(), now(), json.dumps(tf.warnings), now()))
        tid = cur.lastrowid
        for s in p.signers:
            db.x("""INSERT INTO authorities(trust_id, kind, fingerprint, key, name, email, first_commit, first_at,
                    last_commit, last_at) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                 (tid, s["kind"], s["fingerprint"], s["key"], s["name"], s["email"], s["commit"], s["date"], s["commit"], s["date"]))
        _store_reviews(db, tid, tf)
    return tid


def _store_reviews(db: DB, tid: int, tf: trustfile.TrustFile) -> None:
    db.x("DELETE FROM reviews WHERE trust_id=?", (tid,))
    for r in tf.rows:
        db.x("INSERT OR REPLACE INTO reviews(trust_id, url, app, source, tags, trust, rating, section, settings) VALUES(?,?,?,?,?,?,?,?,?)",
             (tid, r.url, r.app, r.source, json.dumps(r.tags), r.trust, r.rating, tf.sections.get(r.app, ""),
              json.dumps(tf.settings.get(r.app, {}))))


def own_trust(db: DB, path: str) -> int:
    """The user's own AppKata.md, always applied (requirement 10.5.1)."""
    row = db.one("SELECT id FROM trusts WHERE own=1")
    if row:
        db.x("UPDATE trusts SET url=?, path=? WHERE id=?", ("file://" + path, path, row["id"]))
        return row["id"]
    return db.x("INSERT INTO trusts(url, name, path, own, added_at) VALUES(?,?,?,1,?)",
                ("file://" + path, "Your reviews", path, now())).lastrowid


def sync_own(db: DB, tid: int) -> None:
    t = db.one("SELECT * FROM trusts WHERE id=?", (tid,))
    try:
        with open(t["path"], encoding="utf-8") as f:
            content = f.read()
    except OSError:
        content = ""
    tf = trustfile.parse(content) if content else trustfile.TrustFile()
    with db.tx():
        _store_reviews(db, tid, tf)
        db.x("UPDATE trusts SET synced_at=?, warnings=? WHERE id=?", (now(), json.dumps(tf.warnings if content else []), tid))


def sync_trust(db: DB, http: Http, tid: int, root: str | None = None) -> None:
    """Fetch a Trust and apply only changes signed by its enabled Authorities (requirement 10.7, 10.8)."""
    t = db.one("SELECT * FROM trusts WHERE id=?", (tid,))
    if t["own"]:
        return sync_own(db, tid)
    loc = gitsig.locate(t["url"])
    dest = trust_dir(t["url"], root)
    try:
        tip = gitsig.fetch(loc, dest)
        auths = authorities_for(db, tid)
        adv = gitsig.advance(dest, tip, t["path"], t["verified_commit"] or "", auths)
        # an OpenPGP signer we don't have the key for yet: look it up once, then re-check
        if adv.stopped and adv.stopped.status == "nokey" and adv.stopped.signer:
            key = _lookup_gpg_key(http, dest, adv.stopped.commit, adv.stopped.signer.fingerprint)
            if key:
                chk = gitsig.check_commit(dest, adv.stopped.commit, [key])
                if chk.signer:
                    chk.signer.key = key
                adv.stopped = chk
        problem, detail = adv.problem, ""
        pending = 0
        if adv.stopped:
            s = adv.stopped
            if adv.problem == "unknown-signer" and s.signer:
                later = gitsig.commits_touching(dest, tip, t["path"], adv.verified)
                pending = len(later)
                if not db.one("SELECT 1 FROM authorities WHERE trust_id=? AND fingerprint=?", (tid, s.signer.fingerprint)):
                    audit.record(db, "sync", "authority", "found a new signer,", s.signer.email or s.signer.name or s.signer.fingerprint,
                                 t["url"], {"trust": t["name"], "key": s.signer.fingerprint, "changes": pending})
                db.x("""INSERT INTO authorities(trust_id, kind, fingerprint, key, name, email, enabled, pending, first_commit,
                        first_at, last_commit, last_at, pending_commits) VALUES(?,?,?,?,?,?,0,1,?,?,?,?,?)
                        ON CONFLICT(trust_id, fingerprint) DO UPDATE SET pending_commits=excluded.pending_commits,
                        last_commit=excluded.last_commit, last_at=excluded.last_at""",
                     (tid, s.signer.kind, s.signer.fingerprint, s.signer.key, s.signer.name or s.author,
                      s.signer.email or s.author_email, s.commit, s.date, later[-1] if later else s.commit, s.date, pending))
                detail = f"{s.signer.email or s.author_email} signed {pending} change{'s' if pending != 1 else ''} since {adv.verified[:7]}"
            elif adv.problem == "unsigned":
                detail = f"Commit {s.commit[:7]} by {s.author} isn't signed; changes from it on aren't applied."
            elif adv.problem == "disabled":
                detail = f"Commit {s.commit[:7]} is signed by a disabled authority; not applied."
            elif adv.problem == "bad":
                detail = f"Commit {s.commit[:7]}: {s.reason or 'bad signature'}; not applied."
        elif adv.problem == "rewritten":
            detail = "The history was rewritten (force-pushed); the last verified version is kept."
        for chk in adv.checks:
            if chk is not adv.stopped and chk.status == "good" and chk.signer:
                db.x("UPDATE authorities SET last_commit=?, last_at=? WHERE trust_id=? AND fingerprint=?",
                     (chk.commit, chk.date, tid, chk.signer.fingerprint))
        content = gitsig.show(dest, adv.verified, t["path"]) if adv.verified else ""
        tf = trustfile.parse(content)
        if adv.verified and adv.verified != t["verified_commit"]:
            audit.record(db, "sync", "trust", "applied signed changes from", t["name"], t["url"],
                         {"commit": adv.verified[:7], "apps": len(tf.rows)})
        if problem and problem != (t["problem"] or "") and problem != "unknown-signer":
            audit.record(db, "sync", "trust", "refused a change to", t["name"], t["url"], {"reason": problem, "detail": detail})
        log.info("trust %s: verified %s, problem %r", t["name"], (adv.verified or "")[:7], problem)
        with db.tx():
            _store_reviews(db, tid, tf)
            db.x("UPDATE trusts SET verified_commit=?, verified_at=?, synced_at=?, problem=?, problem_detail=?, warnings=? WHERE id=?",
                 (adv.verified, now() if adv.verified != t["verified_commit"] else t["verified_at"], now(),
                  problem, detail, json.dumps(tf.warnings), tid))
    except gitsig.GitError as e:
        log.warning("trust %s: %s", t["name"], e)
        db.x("UPDATE trusts SET synced_at=?, problem='unreachable', problem_detail=? WHERE id=?", (now(), str(e), tid))


def authorities_for(db: DB, tid: int) -> list[gitsig.Authority]:
    return [gitsig.Authority(a["kind"], a["fingerprint"], a["key"] or "", bool(a["enabled"]), bool(a["pending"]))
            for a in db.all("SELECT * FROM authorities WHERE trust_id=?", (tid,))]


def ensure_assets(db: DB, http: Http, url: str, version: str) -> dict | None:
    """A release's files, fetched now if the last sync didn't (the GitHub fallback only reads the
    newest few releases' files). Returns the release dict."""
    row = db.one("SELECT releases, forge FROM apps WHERE url=?", (url,))
    if not row:
        return None
    rels = json.loads(row["releases"] or "[]")
    rel = next((r for r in rels if r["version"] == version), None)
    if not rel or rel.get("assets"):
        return rel
    repo = urls.parse(url)
    f = forges.forge_for(http, repo, row["forge"] or None)
    if isinstance(f, forges.GitHub):
        try:
            if f.web:
                raise forges.RateLimited("api.github.com", 0)
            d = f._get(f"{f.base}/releases/tags/{forges.quote(rel['tag'], safe='')}")
            assets = [forges.Asset(a["name"], a["browser_download_url"], a.get("size", 0), a.get("digest") or "")
                      for a in d.get("assets", [])]
        except (forges.RateLimited, SourceError):
            assets, _ = f._assets_web(rel["tag"])
    else:
        match = next((r for r in f.releases() if r.tag == rel["tag"]), None)
        assets = match.assets if match else []
    rel["assets"] = [{"name": a.name, "url": a.url, "size": a.size, "digest": a.digest, "content_type": a.content_type}
                     for a in assets]
    db.x("UPDATE apps SET releases=? WHERE url=?", (json.dumps(rels), url))
    return rel


def trust_signer(db: DB, tid: int, fingerprint: str) -> None:
    """Accept a pending signer as an Authority (requirement 7.6.6)."""
    db.x("UPDATE authorities SET pending=0, enabled=1, pending_commits=0 WHERE trust_id=? AND fingerprint=?", (tid, fingerprint))


# ---------------------------------------------------------------- everything
@dataclass
class Progress:
    done: int = 0
    total: int = 0
    current: str = ""
    cancelled: bool = False
    lock: threading.Lock = field(default_factory=threading.Lock)


def catalog_urls(db: DB) -> list[str]:
    srcs = [r["url"] for r in db.all("SELECT url FROM sources")]
    trust_listed = [r["url"] for r in db.all("""SELECT DISTINCT r.url FROM reviews r JOIN trusts t ON t.id=r.trust_id
                                                 WHERE t.enabled=1""")]
    return list(dict.fromkeys(srcs + trust_listed))


def sync_all(db: DB, http: Http, progress: Progress | None = None, root: str | None = None, workers: int = 4,
             on_item=None) -> None:
    """Trusts first (they add Catalog apps), then every app, four hosts at a time (requirement 9.2.1)."""
    progress = progress or Progress()
    trusts = [t["id"] for t in db.all("SELECT id FROM trusts WHERE enabled=1")]
    progress.total = len(trusts)
    for tid in trusts:
        if progress.cancelled:
            return
        progress.current = db.one("SELECT name FROM trusts WHERE id=?", (tid,))["name"]
        sync_trust(db, http, tid, root)
        progress.done += 1
        on_item and on_item()
    apps = catalog_urls(db)
    progress.total += len(apps)

    def one(url: str):
        if progress.cancelled:
            return
        progress.current = url.split("/", 3)[-1]
        sync_app(db, http, url, root)
        with progress.lock:
            progress.done += 1
        on_item and on_item()

    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(one, apps))
    if not progress.cancelled:
        sync_channels(db, http)
    db.put("last_sync", now())


# ---------------------------------------------------------------- package channels (requirement 16)
def sync_channels(db: DB, http: Http) -> None:
    """Every sync: who updates what (16.5.2), channel installs still there or changed elsewhere
    (16.4.1, 16.5.4), pending updates (16.5.5) and the link checks (16.1.5). Skipped off Linux and
    inside a Flatpak sandbox (16.10). Never fails the sync."""
    if not channels.enabled():
        return
    from . import autoupdate
    try:
        det = autoupdate.detect()
        db.put("autoupdate", det.as_dict())
    except Exception:
        log.exception("couldn't read the system's update settings")
    for step in (track_channel_installs, check_links):
        try:
            step(db, http)
        except Exception:
            log.exception("channels: %s failed", step.__name__)


def track_channel_installs(db: DB, http: Http | None = None) -> None:
    """Requirement 16.4.1, 16.5.4, 16.5.5, 16.5.6, 16.6.3."""
    from . import autoupdate, flatpak, pkgbackend
    rows = [r for r in db.all("SELECT * FROM installs") if json.loads(r["record"] or "{}").get("channel")]
    if not rows:
        return
    fps = flatpak.installed() if flatpak.available() else {}
    fp_updates = {**flatpak.updates(True), **flatpak.updates(False)} if fps else {}
    fp_history = None
    mgr = channels.manager()
    pkgs = [json.loads(r["record"])["package"] for r in rows if json.loads(r["record"]).get("channel") == "package"]
    pending = pkgbackend.pending_updates(pkgs, mgr) if pkgs and mgr else {}
    held = set()
    if pkgs and mgr == "apt":
        held = set(autoupdate._out(["apt-mark", "showhold"]).split())
    det = autoupdate.Detection.from_dict(db.get("autoupdate", {}) or {})
    for r in rows:
        rec = json.loads(r["record"])
        url, name = r["url"], r["name"]
        if rec["channel"] == "flatpak":
            i = fps.get(rec["flatpak"])
            if i is None:
                db.x("DELETE FROM installs WHERE url=?", (url,))
                audit.record(db, "system", "app", "was removed outside AppKata", name, url, {"flatpak": rec["flatpak"]})
                continue
            cur, known = i.commit, rec.get("commit", "")       # `flatpak list` shows a shortened commit
            if cur and known and not (known.startswith(cur) or cur.startswith(known)):
                if fp_history is None:
                    fp_history = flatpak.history()
                ch = next((c for c in reversed(fp_history) if c.app_id == rec["flatpak"] and "update" in c.change), None)
                who = flatpak.tool_name(ch.tool) if ch else ""
                _changed_elsewhere(db, r, rec, i.version, channels.project_version("flatpak", i.version), who,
                                   ch.time if ch else "", det, "flatpak")
                rec["commit"] = i.commit
            up = fp_updates.get(rec["flatpak"])
            if up:
                new_perms = flatpak.permissions(flatpak.metadata(rec["flatpak"], rec.get("remote") or flatpak.FLATHUB))
                rec["pending"] = {"version": up.get("version", ""), "commit": up.get("commit", ""),
                                  "addedPerms": flatpak.added_permissions(rec.get("perms") or [], new_perms) if new_perms else []}
            else:
                rec.pop("pending", None)
        else:
            ver = pkgbackend.installed_version(rec["package"], rec.get("manager"))
            if not ver:
                db.x("DELETE FROM installs WHERE url=?", (url,))
                audit.record(db, "system", "app", "was removed outside AppKata", name, url, {"package": rec["package"]})
                continue
            if rec.get("pkgVersion") and ver != rec["pkgVersion"]:
                who, when = autoupdate.last_change(rec.get("manager", ""), rec["package"], ver)
                _changed_elsewhere(db, r, rec, ver, channels.project_version(rec.get("manager", ""), ver), who, when,
                                   det, "package")
                rec["pkgVersion"] = ver
            if rec["package"] in pending:
                rec["pending"] = {"version": pending[rec["package"]],
                                  "projectVersion": channels.project_version(rec.get("manager", ""), pending[rec["package"]])}
            else:
                rec.pop("pending", None)
            rec["held"] = rec["package"] in held
        db.x("UPDATE installs SET record=? WHERE url=?", (json.dumps(rec), url))


def _changed_elsewhere(db: DB, row: dict, rec: dict, raw: str, version: str, who: str, when: str, det, kind: str) -> None:
    """A version AppKata didn't install (requirement 16.5.4)."""
    audit.record(db, "system", "app", "was updated outside AppKata", row["name"], row["url"],
                 {"version": raw, **({"by": who} if who else {})})
    rec["updatedBy"], rec["updatedAt"] = who, when
    state, _ = channels.update_state(rec, det)
    person = not who or who.endswith("(apt)") or who in ("dnf", "flatpak", "AppKata")
    if state == "not-updated" and not person:
        rec["updates"] = "system"          # something updates it after all
    db.x("UPDATE installs SET version=? WHERE url=?", (version or raw, row["url"]))


def check_links(db: DB, http: Http) -> None:
    """The link checks, each when its answer can change (requirement 16.1.5)."""
    from . import appstream, flatpak, pkgbackend
    try:
        cat = appstream.load_cached()
    except OSError:
        cat = None
    mgr = channels.manager()
    has_fp = flatpak.available()
    for url in catalog_urls(db):
        found = channels.links(db, url, cat, mgr)
        meta = db.one("SELECT appstream_id FROM app_meta WHERE url=?", (url,)) or {}
        fl, pk = found.get("flatpak"), found.get("package")
        if fl:
            commit = flatpak.remote_info(fl.value, fl.remote).get("commit", "") if has_fp and flatpak.has_remote(fl.remote) else ""
            try:
                channels.check_flatpak(db, http, url, fl.value, commit, meta.get("appstream_id", ""))
            except Exception:
                log.exception("checking %s's Flatpak", url)
        if pk:
            try:
                channels.check_package(db, http, url, pk.value, pkgbackend.package_version_available(pk.value, mgr), cat, mgr)
            except Exception:
                log.exception("checking %s's package", url)
