"""Putting Sources, Trust reviews and installs together into the app list every view shows
(requirement 2.9, 9.4, 9.5, 10.5, 10.6)."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

from . import sandbox, scoring, trustfile, versions
from .assets import category, choose, exe_type
from . import APPKATA_REPO, __version__
from .db import DB
from .forges import Asset
from .platform import OS, arch, linux_family
from .selfinstall import own_icon
from .trustfile import WARNING_TAGS

PALETTE = [("#22d3ee", "#2563eb"), ("#60a5fa", "#1e40af"), ("#4ade80", "#15803d"), ("#a78bfa", "#4c1d95"),
           ("#f472b6", "#9d174d"), ("#38bdf8", "#0e7490"), ("#fb923c", "#c2410c"), ("#818cf8", "#3730a3"),
           ("#f87171", "#b91c1c"), ("#2dd4bf", "#115e59"), ("#facc15", "#a16207"), ("#c084fc", "#581c87")]


def colors(seed: str) -> tuple[str, str]:
    """A stable gradient for generated icons and avatars (requirement 3.2, 10.9)."""
    return PALETTE[int(hashlib.sha1(seed.encode()).hexdigest()[:6], 16) % len(PALETTE)]


def initials(name: str) -> str:
    parts = [p for p in name.replace("-", " ").replace("_", " ").split() if p[:1].isalnum()]
    if not parts:
        return "?"
    return (parts[0][0] + (parts[1][0] if len(parts) > 1 else "")).upper()


def _parse_date(s: str):
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def trust_rows(db: DB) -> list[dict]:
    """Trusts whose reviews count: enabled and verified (requirement 10.5)."""
    return db.all("SELECT * FROM trusts WHERE enabled=1 AND (own=1 OR verified_commit IS NOT NULL) ORDER BY own DESC, id")


def trust_score(t: dict) -> int:
    """A Trust's Score, 1–5; your own reviews always weigh 5 (requirement 10.6.2)."""
    return 5 if t.get("own") else max(1, min(5, int(t.get("score") or 3)))


def trust_order(t: dict):
    """Trusts are listed yours first, then by Score (highest first), then name (requirement 7.6.7)."""
    return (not t.get("own"), -trust_score(t), (t.get("name") or "").lower())


def trust_label(t: dict) -> dict:
    auth = db_authorities_cache.get(t["id"], [])
    short = t["name"].split(" / ")[0] if " / " in t["name"] else t["name"]
    if len(short) > 18:
        short = " ".join(short.split()[:2])
    return {"id": t["id"], "name": t["name"], "short": short,
            "own": bool(t["own"]), "score": trust_score(t), "avatars": auth[:1] or [avatar_for(t["name"], t["name"])]}


db_authorities_cache: dict[int, list[dict]] = {}


def avatar_for(name: str, seed: str) -> dict:
    c1, c2 = colors(seed)
    return {"init": initials(name), "c1": c1, "c2": c2}


def authorities(db: DB, trust_id: int, include_pending: bool = True) -> list[dict]:
    rows = db.all("SELECT * FROM authorities WHERE trust_id=? ORDER BY pending, id", (trust_id,))
    return [r for r in rows if include_pending or not r["pending"]]


def authority_view(a: dict) -> dict:
    av = avatar_for(a["name"] or a["email"] or a["fingerprint"], a["fingerprint"])
    return {**a, **av, "enabled": bool(a["enabled"]), "pending": bool(a["pending"]),
            "kindLabel": {"ssh": "SSH", "gpg": "GPG", "nostr": "Nostr"}.get(a["kind"], a["kind"]),
            "shortFp": short_fp(a["fingerprint"])}


def short_fp(fp: str) -> str:
    if fp.startswith("SHA256:"):
        return fp[:12] + "…" + fp[-4:]
    if len(fp) == 40:
        return " ".join(fp[i:i + 4] for i in range(0, 20, 4))
    return fp


def _days_left(newest_date, min_age: int) -> int:
    """Whole days until a release is old enough, rounded up."""
    if not newest_date:
        return min_age
    secs = (newest_date + timedelta(days=min_age) - datetime.now(timezone.utc)).total_seconds()
    return max(1, math.ceil(secs / 86400))


def eligible_release(releases: list[dict], settings: dict, include_pre: bool = False) -> tuple[dict | None, str]:
    """The newest release allowed by pin and minimum age (requirement 9.4, 9.5): (release, held reason)."""
    rs = [r for r in releases if include_pre or not r.get("prerelease")]
    if not rs:
        return None, ""
    newest = rs[0]
    min_age = int(settings.get("min_age") or 0)
    if min_age > 0:
        cutoff = datetime.now(timezone.utc) - timedelta(days=min_age)
        for r in rs:
            d = _parse_date(r.get("date", ""))
            if d and d <= cutoff:
                if r is not newest:
                    nd = _parse_date(newest.get("date", ""))
                    left = _days_left(nd, min_age)
                    return r, f"Held · {left} day{'s' if left != 1 else ''} left"
                return r, ""
        nd = _parse_date(newest.get("date", ""))
        left = _days_left(nd, min_age)
        return None, f"Held · {left} day{'s' if left != 1 else ''} left"
    return newest, ""


def channel_view(rec: dict, version: str, releases: list[dict], det, check: dict | None = None) -> dict:
    """What the Apps row and App Detail panel show about an app installed from a package channel
    (requirement 16.5.1, 16.6, 16.7.2): its channel and publisher, who updates it, and its pending
    update."""
    from . import channels
    check = check or {}
    owner, who = channels.update_state(rec, det)
    pend = rec.get("pending") or {}
    pv = pend.get("projectVersion") or (channels.project_version("flatpak", pend.get("version", "")) if pend.get("version") else "")
    if rec.get("channel") == "flatpak":
        remote = rec.get("remote") or "flathub"
        flag = check.get("verified")
        name = "Flathub" if remote == "flathub" else remote
        label = name + (" · verified" if flag else " · community" if flag is not None and remote == "flathub" else "")
        raw = ""
    else:
        label = (rec.get("signer") or "Distribution") + (f" ({rec['origin']})" if rec.get("origin") else "")
        raw = rec.get("pkgVersion", "")
    return {"kind": rec.get("channel"), "label": label, "value": rec.get("flatpak") or rec.get("package") or "",
            "verified": check.get("verified"), "check": check.get("state", ""), "checkDetail": check.get("detail", ""),
            "builtFrom": check.get("built_from", ""), "updates": owner, "updatesBy": who,
            "updatedBy": rec.get("updatedBy", ""), "updatedAt": (rec.get("updatedAt") or "")[:10],
            "pkgVersion": raw, "projectVersion": version, "behind": channels.releases_behind(releases, version) if raw else 0,
            "distro": rec.get("signer", ""), "perms": rec.get("perms") or [], "addedPerms": pend.get("addedPerms") or [],
            "extraData": rec.get("extraData", ""), "pending": pv or pend.get("version", ""), "pendingRaw": pend.get("version", ""),
            "adopted": bool(rec.get("adopted")), "system": rec.get("installation") == "system",
            "manager": rec.get("manager", "")}


def build(db: DB, os_name: str = OS, cpu: str | None = None,
          runs_sandboxed: Callable[[str, dict], bool] | None = None) -> list[dict]:
    """Every Catalog app with its origins, reviews, score and state. `runs_sandboxed(url, record)`:
    whether an installed app runs sandboxed (17.12), the backend's answer, which App Detail gives
    too (review 3, R3-27); by default, whether its launcher is there."""
    cpu = cpu or arch()
    runs_sandboxed = runs_sandboxed or (lambda url, rec: sandbox.runs_sandboxed(rec))
    family = linux_family() if os_name == "linux" else ""
    trusts = {t["id"]: t for t in trust_rows(db)}
    db_authorities_cache.clear()
    for tid in trusts:
        db_authorities_cache[tid] = [authority_view(a) for a in authorities(db, tid, include_pending=False) if a["enabled"]]
    reviews: dict[str, list[dict]] = {}
    for r in db.all("SELECT * FROM reviews"):
        if r["trust_id"] in trusts:
            reviews.setdefault(r["url"], []).append(r)
    sources = {s["url"]: s for s in db.all("SELECT * FROM sources")}
    appsmeta = {a["url"]: a for a in db.all("SELECT * FROM apps")}
    installs = {i["url"]: i for i in db.all("SELECT * FROM installs")}
    settings = {s["url"]: s for s in db.all("SELECT * FROM app_settings")}
    foreign = {f["url"]: f for f in db.all("SELECT * FROM foreign_installs")}
    include_pre_default = bool(db.get("prereleases", False))
    from .autoupdate import Detection
    det = Detection.from_dict(db.get("autoupdate", {}) or {})
    checks = {(c["url"], c["kind"], c["value"]): c for c in db.all("SELECT * FROM channel_checks")}
    out = []
    for url in set(sources) | set(reviews):
        meta = appsmeta.get(url, {})
        src = sources.get(url)
        revs = sorted(reviews.get(url, []), key=lambda r: trust_order(trusts[r["trust_id"]]))
        releases = json.loads(meta.get("releases") or "[]")
        dates = release_dates(releases)
        chains = [review_chain(r, os_name, dates) for r in revs]
        inst = installs.get(url)
        is_self = url == APPKATA_REPO
        # a reviewer's App column is a curated name; then the forge's (requirement 10.1.1). Before any
        # sync, the name it was installed by, and AppKata its own, not its URL's last part (review 3, R3-36)
        name = ((revs[0]["app"] if revs else "") or meta.get("name") or (inst["name"] if inst else "")
                or ("AppKata" if is_self else "") or url.rsplit("/", 1)[-1])
        ssettings = json.loads(src["settings"]) if src and src.get("settings") else {}
        aset = settings.get(url, {})
        pin_min = {"min_age": db.get("min_age_default", 0)}         # a global setting only (requirement 9.5.2)
        cur_v = inst["version"] if inst else None       # options for the installed version, else the newest review
        rec, rec_by = pick_recommended([(r["settings"], trusts[r["trust_id"]]) for r in revs], os_name, cur_v, dates)
        eff = effective_source(ssettings, rec, rec_by, os_name, cpu, include_pre_default)
        include_pre, track_only = eff["prereleases"], eff["trackOnly"]
        offered = releases if track_only else [r for r in releases if r.get("assets")]   # a bare tag isn't installable
        rel, held = eligible_release(offered, pin_min, include_pre)
        latest = next((r for r in offered if include_pre or not r.get("prerelease")), None) or \
            next((r for r in releases if include_pre or not r.get("prerelease")), None)   # newest offered, else newest
        # scores for a version (requirement 10.6.5): the latest release, and the installed version
        score, tags, _ = score_at(revs, chains, trusts, (latest or {}).get("version"), os_name, dates, is_self)
        if is_self and not inst:        # AppKata itself, run from source or a package: it's installed, but not by AppKata
            inst = {"version": __version__, "date": "", "kind": "", "self_unmanaged": True}
        pinned = aset.get("pinned") or ""
        try:
            saved = json.loads(aset.get("install") or "{}")
        except ValueError:
            saved = {}
        # updates itself (requirement 4.10): your choice for this app, else the highest-Score Trust that says
        auto_by = ""
        if "autoUpdate" in saved:
            auto = bool(saved["autoUpdate"])
        else:
            auto = False
            for r in revs:
                rs = trustfile.resolve_settings(json.loads(r["settings"] or "{}") if r["settings"] else {}, os_name,
                                                inst["version"] if inst else (latest or {}).get("version"), dates)
                if "autoUpdate" in rs:
                    auto, auto_by = bool(rs["autoUpdate"]), trusts[r["trust_id"]]["name"]
                    break
        state, update_to = "", None
        irec = json.loads(inst.get("record") or "{}") if inst and inst.get("record") else {}
        sandboxed = bool(inst) and not is_self and runs_sandboxed(url, irec)       # 17.12
        chv = None
        if irec.get("channel"):          # a package channel: it updates through its channel (requirement 16.5)
            chv = channel_view(irec, inst["version"], releases, det,
                               checks.get((url, irec["channel"], irec.get("flatpak") or irec.get("package") or "")))
        if chv:
            state = "installed"
            if pinned:
                state = "pinned"
            elif chv["updates"] == "system":
                state = "system"         # tracked, updated by the system (16.5.1)
            elif chv["updates"] != "held" and chv["pending"]:
                state, update_to = "update", {"version": chv["pending"], "date": ""}
        elif inst and auto and not is_self and not sandboxed:
            state = "selfupdating"       # AppKata tracks it but doesn't update it (4.10.1) -- unless it runs
                                         # sandboxed, where it can't update itself and AppKata does (17.12)
        elif inst:
            state = "installed"
            if pinned:
                state = "pinned"
            elif rel and versions.newer(rel["version"], inst["version"], rel.get("date", ""), inst.get("date") or ""):
                state, update_to = "update", rel
            elif held and latest and versions.newer(latest["version"], inst["version"]):
                state = "held"
        elif url in foreign:
            state = "foreign"
        iscore, avoid, avoid_to, upd_avoided = None, None, "", False
        if inst and not inst.get("self_unmanaged"):
            iscore, _, applied = score_at(revs, chains, trusts, inst["version"], os_name, dates, is_self)
            if iscore.vetoed:
                r0, rv = next((r, x) for r, x in applied if x["trust"] == 0)
                avoid = {"by": trusts[r0["trust_id"]]["name"], "own": bool(trusts[r0["trust_id"]]["own"]),
                         "from": rv["version"], "note": _first_line(rv["text"] or (r0["section"] if not rv["version"] else ""))}
                for r in ([] if chv else offered):   # the newest release that isn't avoided, newer than yours
                    if not (include_pre or not r.get("prerelease")) or not versions.newer(r["version"], inst["version"], r.get("date", ""), inst.get("date") or ""):
                        continue
                    if not score_at(revs, chains, trusts, r["version"], os_name, dates, is_self)[0].vetoed:
                        avoid_to = r["version"]
                        break
                if chv and chv["pending"] and not score_at(revs, chains, trusts, chv["pending"], os_name, dates, is_self)[0].vetoed:
                    avoid_to = chv["pending"]      # the channel's update leaves the avoided version (16.5.5)
            if update_to:
                upd_avoided = score_at(revs, chains, trusts, update_to["version"], os_name, dates, is_self)[0].vetoed
        chosen = None
        prefer = saved.get("kind") or (inst["kind"] if inst else "")      # keep to the way it was installed (4.9.4)
        if rel:
            ch = choose_with(eff, [Asset(**a) for a in rel.get("assets", [])], os_name, cpu, family, prefer)
            if ch.asset:
                ek = saved.get("exeKind") or (exe_type(ch.asset.name, release=[x["name"] for x in rel.get("assets", [])]) if ch.kind == "exe" else "")
                chosen = {"name": ch.asset.name, "url": ch.asset.url, "size": ch.asset.size, "digest": ch.asset.digest,
                          "kind": ch.kind, "exeKind": ek, "category": category(ch.kind, ek)}
        c1, c2 = colors(url)
        out.append({
            "url": url, "name": name, "summary": meta.get("summary") or meta.get("description") or "",
            "description": meta.get("description") or "", "icon": _abs(meta.get("icon")) or (own_icon() if is_self else ""), "hero": _abs(meta.get("hero")),
            "c1": c1, "c2": c2, "init": initials(name),
            "host": meta.get("host") or url.split("/")[2], "repo": meta.get("repo") or "/".join(url.split("/")[3:]),
            "forge": meta.get("forge") or (src or {}).get("forge") or "",
            "version": (latest or {}).get("version", ""), "date": (latest or {}).get("date", ""),
            "src": bool(src), "trusts": [trust_label(trusts[r["trust_id"]]) for r in revs if not trusts[r["trust_id"]]["own"]],
            "ownReview": any(trusts[r["trust_id"]]["own"] for r in revs),
            "tags": tags, "warnTags": [t for t in tags if t in WARNING_TAGS],
            "trust": score.trust, "rating": score.rating, "reviewers": score.reviewers, "vetoed": score.vetoed,
            "state": state, "installed": inst["version"] if inst else "", "installKind": inst["kind"] if inst else "",
            "updateTo": update_to["version"] if update_to else "", "held": held if state == "held" else "",
            "pinned": pinned, "minAge": pin_min["min_age"] or 0, "trackOnly": track_only,
            "msvcrt": bool(inst and inst.get("record") and json.loads(inst["record"] or "{}").get("msvcrt")),   # 15.18
            "self": is_self, "selfManaged": bool(is_self and not inst.get("self_unmanaged")),
            "restartNeeded": bool(is_self and inst and not inst.get("self_unmanaged") and inst["version"] != __version__),
            "foreign": foreign.get(url, {}).get("location", ""), "foreignVersion": foreign.get(url, {}).get("version", ""),
            "error": meta.get("error") or "", "errorCode": meta.get("error_code") or "",
            "asset": chosen, "releaseCount": len(releases), "installChoice": saved, "sourceSettings": eff,
            "autoUpdate": auto, "autoUpdateBy": auto_by if "autoUpdate" not in saved else "you",
            "sandboxedUpdates": bool(inst and auto and not is_self and sandboxed),   # 17.12, review 2 F3
            "newer": bool(state in ("selfupdating", "system") and latest and versions.newer(latest["version"], inst["version"])),
            "installedVetoed": bool(iscore and iscore.vetoed), "installedTrust": iscore.trust if iscore else None,
            "installedRating": iscore.rating if iscore else None, "avoid": avoid, "avoidUpdateTo": avoid_to,
            "updateAvoided": upd_avoided,
            "ch": chv, "adoptable": bool(foreign.get(url, {}).get("adopt")),
            "permsGrow": bool(chv and chv["addedPerms"]),
        })
    return out


def release_dates(releases: list[dict]) -> dict:
    return {r["version"]: r.get("date", "") for r in releases if r.get("version")}


def review_chain(r: dict, os_name: str, dates: dict) -> list[dict]:
    """One Trust's reviews of an app over versions (requirement 10.3.3), from its reviews row."""
    s = json.loads(r["settings"] or "{}") if r.get("settings") else {}
    chain = trustfile.reviews_over_versions(s, {"trust": r["trust"], "rating": r["rating"], "tags": json.loads(r["tags"] or "[]")},
                                            os_name, dates)
    chain[0]["text"] = r.get("section") or ""
    return chain


def score_at(revs: list[dict], chains: list[list[dict]], trusts: dict, version: str | None, os_name: str, dates: dict,
             is_self: bool = False) -> tuple[scoring.Score, list[str], list[tuple[dict, dict]]]:
    """The combined score and tags for one version (requirement 10.6.5), and each Trust's review
    that applies to it: [(reviews row, review)]."""
    applied = [(r, trustfile.review_for({}, None, version, os_name, dates, chain=c)) for r, c in zip(revs, chains)]
    score = scoring.combine([(x["trust"], x["rating"], trust_score(trusts[r["trust_id"]])) for r, x in applied])
    if is_self:     # you're running it: AppKata's own Trust is 5 (requirement 10.6.4)
        score = scoring.Score(vetoed=False, trust=5.0, rating=score.rating, reviewers=score.reviewers)
    tags = []
    for _, x in applied:
        for t in x["tags"]:
            if t not in tags:
                tags.append(t)
    return score, tags, applied


def version_scores(db: DB, url: str, vs: list[str], os_name: str = OS) -> dict:
    """{version: (combined Trust, vetoed)} for the Versions list (requirement 10.6.5)."""
    trusts = {t["id"]: t for t in trust_rows(db)}
    revs = sorted([r for r in db.all("SELECT * FROM reviews WHERE url=?", (url,)) if r["trust_id"] in trusts],
                  key=lambda r: trust_order(trusts[r["trust_id"]]))
    meta = db.one("SELECT releases FROM apps WHERE url=?", (url,)) or {}
    dates = release_dates(json.loads(meta.get("releases") or "[]"))
    chains = [review_chain(r, os_name, dates) for r in revs]
    out = {}
    for v in vs:
        sc = score_at(revs, chains, trusts, v, os_name, dates, url == APPKATA_REPO)[0]
        out[v] = (sc.trust, sc.vetoed)
    return out


def _first_line(text: str) -> str:
    for l in (text or "").splitlines():
        l = l.strip().lstrip("-*> ").strip()
        if l and not l.startswith("#"):
            return l if len(l) <= 120 else l[:117] + "…"
    return ""


def pick_recommended(rows: list[tuple[str, dict]], os_name: str, version: str | None = None,
                     dates: dict | None = None) -> tuple[dict, dict]:
    """The settings the Trusts recommend for an app on this platform (requirement 10.3.1): for each
    option, the first Trust in Trust order (yours, then by Score, then name) that sets it, as each
    Trust's review for `version` has it (10.3.3; the newest review when None).
    rows: (settings JSON, trust row). Returns (values, {option: Trust name or "you"})."""
    out, by = {}, {}
    for js, t in sorted(rows, key=lambda r: trust_order(r[1])):
        if not t.get("enabled", 1):
            continue
        for k, v in trustfile.resolve_settings(json.loads(js or "{}"), os_name, version, dates).items():
            if k not in out:
                out[k], by[k] = v, "you" if t.get("own") else t.get("name", "")
    return out, by


def recommended_for(db: DB, url: str, os_name: str = OS) -> tuple[dict, dict]:
    rows = db.all("SELECT r.settings, t.* FROM reviews r JOIN trusts t ON t.id=r.trust_id WHERE r.url=?", (url,))
    return pick_recommended([(r["settings"], r) for r in rows], os_name)


def effective_source(ss: dict, rec: dict, rec_by: dict, os_name: str, cpu: str, pre_default: bool) -> dict:
    """A Source's settings as they apply (requirement 2.6, 10.3.1): yours, else a Trust's
    recommendation, else the default. `by` says where each came from ("you", a Trust's name, "")."""
    own_filter = (ss.get("asset_filters") or {}).get(f"{os_name}-{cpu}") or ss.get("asset_filter", "")
    def pick(own_key, rec_key, default):
        if own_key in ss:
            return ss[own_key], "you"
        if rec_key in rec:
            return rec[rec_key], rec_by.get(rec_key, "")
        return default, ""
    track, track_by = (bool(ss["track_only"]), "you") if "track_only" in ss else (False, "")          # personal only
    pre, pre_by = (bool(ss["prereleases"]), "you") if "prereleases" in ss else (pre_default, "")
    forge, forge_by = pick("forge", "forge", "")
    filt, filt_by = (own_filter, "you") if own_filter else (rec.get("assetFilter", ""), rec_by.get("assetFilter", ""))
    return {"trackOnly": bool(track), "prereleases": bool(pre), "forge": forge or "", "assetFilter": filt or "",
            "by": {"trackOnly": track_by, "prereleases": pre_by, "forge": forge_by, "assetFilter": filt_by if filt else ""},
            "recommended": {k: rec[k] for k in ("forge", "assetFilter") if k in rec},
            "recommendedBy": {k: rec_by[k] for k in ("forge", "assetFilter") if k in rec_by}}


def choose_with(eff: dict, assets: list, os_name: str, cpu: str, family: str, prefer: str = ""):
    """choose() with the Source's download filter. A Trust's recommended filter that matches nothing
    here is ignored; your own filter is not (requirement 2.6.4, 10.3.1)."""
    ch = choose(assets, os_name, cpu, family, eff.get("assetFilter", ""), prefer=prefer)
    if not ch.asset and eff.get("assetFilter") and eff.get("by", {}).get("assetFilter") not in ("you", ""):
        ch = choose(assets, os_name, cpu, family, "", prefer=prefer)
    return ch


def asset_filter(ssettings: dict, os_name: str, cpu: str) -> str:
    """A Source's asset filter for this platform (requirement 2.6.4)."""
    return (ssettings.get("asset_filters") or {}).get(f"{os_name}-{cpu}") or ssettings.get("asset_filter", "")


def _abs(p: str | None) -> str:
    import os
    from .platform import data_dir
    if not p:
        return ""
    return p if os.path.isabs(p) else os.path.join(data_dir(), p)


def sort(apps: list[dict], by: str = "trust") -> list[dict]:
    if by == "recent":          # newest release first, then name (requirement 12.2)
        return sorted(sorted(apps, key=lambda a: a["name"].lower()), key=lambda a: a.get("date") or "", reverse=True)
    return sorted(apps, key=lambda a: scoring.sort_key(a["name"], scoring.Score(a["vetoed"], a["trust"], a["rating"], a["reviewers"]), by))


def visible(apps: list[dict], search: str = "", tag: str = "") -> tuple[list[dict], int]:
    """Catalog filtering (requirement 12.2, 12.6): vetoed apps only when the search matches them."""
    q = search.strip().lower()
    out, vetoed_shown = [], 0
    for a in apps:
        hay = " ".join([a["name"], a["summary"], a["url"], " ".join(a["tags"])]).lower()
        if q and q not in hay:
            continue
        if tag and tag not in a["tags"]:
            continue
        if a["vetoed"]:
            if not q:
                continue
            vetoed_shown += 1
        out.append(a)
    return out, vetoed_shown
