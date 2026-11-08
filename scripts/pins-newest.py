#!/usr/bin/env python3
"""Every input the builds, the tests and CI pin, how old its pinned release is, and the newest release
old enough to move to (the pin cooldown, docs/build.md "Pinned inputs").

    scripts/pins-newest.py [--min-age DAYS] [--allow NAME ...]

A pin moves only to a release at least --min-age days old (default 14) on the day it is pinned. This
reads the pins from the files that hold them (FILES below and .github/workflows), looks each one up
where it comes from (PyPI, python-build-standalone's releases, Docker Hub's registry, GitHub releases,
the actions' tags), and prints a table: the pin and its age, the newest eligible release, and the newest
of all. Exits 1 when a pin is younger than --min-age, unless it is named with --allow: an exception
the owner made for a security fix that can't wait, which the commit that pins it records.

Uses the network, about 30 requests; GITHUB_TOKEN raises GitHub's limit of 60 an hour.
"""

from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import os
import re
import sys
import urllib.request

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
# the files that hold pins (the release inputs tests/test_pinned_inputs.py reads, and the Windows tests')
FILES = ["packaging/versions.env", "scripts/build-windows.sh", "scripts/test-windows-vm.sh"]
# a variable a script installs a package at, for a pip spec written as name==$VAR
PIP_VARS = {"PYSIDE": ["PySide6-Essentials", "shiboken6"], "PYINSTALLER": ["pyinstaller"], "TRUSTSTORE": ["truststore"]}
# where a pin may not go, whatever its age, and why
CEILINGS = {"PySide6-Essentials": ("6.13", "Qt 6.12 is Qt's last version for Windows 10 (packaging/versions.env)"),
            "shiboken6": ("6.13", "goes with PySide6-Essentials")}
UA = {"User-Agent": "AppKata-pins-newest (+https://github.com/MojoKata/AppKata)"}


# --- what is pinned ---------------------------------------------------------------------------------

def _read(path):
    with open(os.path.join(ROOT, path), encoding="utf-8") as f:
        return f.read()


def _value(text, var):
    m = re.search(rf'^\s*: "\${{{var}:=([^}}"\n]*)}}"', text, re.M) or re.search(rf'^\s*{var}="?([^"\n]*)', text, re.M)
    return re.split(r"\s+#", m.group(1))[0].strip().strip('"') if m else None


def inventory():
    """Every pin, as dicts {kind, name, pinned, where}: kind is pypi, python, docker, release or action."""
    pins, seen = [], set()

    def add(kind, name, pinned, where):
        if (kind, name, pinned) not in seen:
            seen.add((kind, name, pinned))
            pins.append({"kind": kind, "name": name, "pinned": pinned, "where": where})

    env = _read("packaging/versions.env")
    for path in FILES:
        text = _read(path)
        for name, version in re.findall(r"(?<![\w.-])([A-Za-z][\w.-]*)==([0-9][\w.]*)", text):
            add("pypi", name, version, path)
        for var, names in PIP_VARS.items():
            v = _value(text, var)
            if v and re.fullmatch(r"[0-9][\w.]*", v):
                for name in names:
                    add("pypi", name, v, path)
    add("python", "python-build-standalone", _value(env, "PYTHON_BUILD"), "packaging/versions.env")
    for var, image in re.findall(r"^(\w+_IMAGE)=(\S+)", env, re.M):
        add("docker", image.split("@")[0], image.split("@")[1], f"packaging/versions.env {var}")
    for var, url in re.findall(r"^(\w+_URL)=(\S+)", env, re.M):
        m = re.match(r"https://github\.com/([^/]+/[^/]+)/releases/download/([^/]+)/", url)
        if m:
            add("release", m.group(1), m.group(2), f"packaging/versions.env {var}")
    for path in sorted(glob.glob(os.path.join(ROOT, ".github/workflows/*.yml"))):
        for repo, sha, tag in re.findall(r"uses:\s*([\w.-]+/[\w.-]+)@([0-9a-f]{40})\s*#\s*(\S+)", open(path).read()):
            add("action", repo, tag, os.path.relpath(path, ROOT))
    return pins


# --- choosing ---------------------------------------------------------------------------------------

def vkey(version):
    """A version's sort key: its numbers, in order ('6.12.0' -> (6, 12, 0); 'v7.0.1' -> (7, 0, 1))."""
    return tuple(int(n) for n in re.findall(r"\d+", version))


def final(version):
    """A plain release: numbers and dots, maybe a leading v (no rc, beta, dev or post)."""
    return re.fullmatch(r"v?\d+(\.\d+)*", version) is not None


def newest(releases, cutoff=None, ceiling=None, plain=True):
    """The highest-versioned (version, published) of releases published on or before cutoff (any, when
    None) and below ceiling; None when there's none. Highest by version, not by date: 6.11.3 came out
    after 6.12.0 and is still older. plain=False takes versions final() doesn't (3.14.10+20261026)."""
    ok = [(v, t) for v, t in releases if (final(v) or not plain) and (cutoff is None or t <= cutoff)
          and (ceiling is None or vkey(v) < vkey(ceiling))]
    return max(ok, key=lambda r: vkey(r[0]), default=None)


# --- where each comes from ---------------------------------------------------------------------------

def _get(url, headers=None, raw=False):
    req = urllib.request.Request(url, headers={**UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=30) as r:
        body = r.read()
    return body if raw else json.loads(body)


def _time(s):
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))


def _github(path):
    tok = os.environ.get("GITHUB_TOKEN")
    return _get("https://api.github.com/" + path,
                {"Accept": "application/vnd.github+json", **({"Authorization": f"Bearer {tok}"} if tok else {})})


def pypi_releases(name):
    d = _get(f"https://pypi.org/pypi/{name}/json")
    return [(v, min(_time(f["upload_time_iso_8601"]) for f in files)) for v, files in d["releases"].items()
            if files and not all(f.get("yanked") for f in files)]


def github_releases(repo, match=None):
    """(tag, published) of repo's releases that aren't drafts or prereleases; match filters by an asset."""
    out = []
    for r in _github(f"repos/{repo}/releases?per_page=100"):
        if r["draft"] or r["prerelease"]:
            continue
        if match and not any(match(a["name"]) for a in r["assets"]):
            continue
        out.append((r["tag_name"], _time(r["published_at"])))
    return out


def action_releases(repo):
    """An action's releases (vX.Y.Z), or its tags dated by their commits when it makes no releases."""
    rel = github_releases(repo)
    if rel:
        return rel
    out = []
    for t in _github(f"repos/{repo}/tags?per_page=30"):
        c = _github(f"repos/{repo}/commits/{t['commit']['sha']}")
        out.append((t["name"], _time(c["commit"]["committer"]["date"])))
    return out


def docker_created(image, digest):
    """When the image behind digest was built (its config's `created`), for linux/amd64."""
    repo, _, _ = image.partition(":")
    repo = repo if "/" in repo else "library/" + repo
    tok = _get(f"https://auth.docker.io/token?service=registry.docker.io&scope=repository:{repo}:pull")["token"]
    acc = ", ".join(["application/vnd.oci.image.index.v1+json", "application/vnd.docker.distribution.manifest.list.v2+json",
                     "application/vnd.oci.image.manifest.v1+json", "application/vnd.docker.distribution.manifest.v2+json"])
    h = {"Authorization": f"Bearer {tok}", "Accept": acc}
    m = _get(f"https://registry-1.docker.io/v2/{repo}/manifests/{digest}", h)
    if "manifests" in m:
        sub = next(x for x in m["manifests"] if x.get("platform", {}).get("architecture") == "amd64"
                   and x.get("platform", {}).get("os") == "linux")
        m = _get(f"https://registry-1.docker.io/v2/{repo}/manifests/{sub['digest']}", h)
    cfg = _get(f"https://registry-1.docker.io/v2/{repo}/blobs/{m['config']['digest']}", h)
    return _time(cfg["created"][:26].rstrip("Z") + "+00:00" if "." in cfg["created"] else cfg["created"])


def docker_current(image):
    """The digest the image's tag (latest when none) points at now."""
    repo, _, tag = image.partition(":")
    repo = repo if "/" in repo else "library/" + repo
    return _get(f"https://hub.docker.com/v2/repositories/{repo}/tags/{tag or 'latest'}")["digest"]


# --- the report -------------------------------------------------------------------------------------

def check(pin, now, min_age):
    """pin plus age (days), eligible and latest (each 'what (N d)' or a note), young and note."""
    cutoff = now - dt.timedelta(days=min_age)
    days = lambda t: (now - t).days  # noqa: E731
    k, name, pinned = pin["kind"], pin["name"], pin["pinned"]
    note, ceiling = "", None
    if k == "pypi":
        rel = pypi_releases(name)
        ceiling, why = CEILINGS.get(name, (None, ""))
        note = f"below {ceiling}: {why}" if ceiling else ""
    elif k == "python":
        series = _value(_read("packaging/versions.env"), "PY_SERIES")
        want = re.compile(rf"cpython-({re.escape(series)}\.\d+)\+(\d+)-x86_64-unknown-linux-gnu-install_only\.tar\.gz$")
        rel = []
        # its releases carry hundreds of files each: a big page times out (504), so ten at a time
        for r in (r for page in (1, 2, 3) for r in _github(f"repos/astral-sh/python-build-standalone/releases?per_page=10&page={page}")):
            for a in r["assets"]:
                m = want.match(a["name"])
                if m and not r["draft"]:
                    rel.append((f"{m.group(1)}+{m.group(2)}", _time(r["published_at"])))
        note = f"Python {series}; tobix/pywine:{series} must carry the same Python (build-windows.sh checks)"
    elif k == "release":
        rel = [(t, p) for t, p in github_releases(name) if t not in ("continuous", "latest")]
    elif k == "action":
        rel = action_releases(name)
    elif k == "docker":
        pt = docker_created(name, pinned)
        cur = docker_current(name)
        ct = pt if cur == pinned else docker_created(name, cur)
        short = lambda d: d.split(":")[1][:12]  # noqa: E731
        latest = f"{short(cur)} ({days(ct)} d)"
        if cur == pinned:
            eligible = "the pinned one"
        elif ct <= cutoff:
            eligible = latest
        else:
            eligible = f"none newer (the tag moved {days(ct)} d ago: eligible in {min_age - days(ct)} d)"
        return {**pin, "pinned": short(pinned), "age": days(pt), "eligible": eligible, "latest": latest,
                "young": days(pt) < min_age, "note": "built from the tag's image of that day"}
    else:
        raise ValueError(k)

    have = dict(rel)
    published = have.get(pinned) or have.get("v" + pinned)
    plain = k != "python"
    best, top = newest(rel, cutoff, ceiling, plain), newest(rel, None, ceiling, plain)
    fmt = lambda r: f"{r[0]} ({days(r[1])} d)" if r else "none"  # noqa: E731
    age = days(published) if published else None
    return {**pin, "age": age, "eligible": fmt(best), "latest": fmt(top),
            "young": age is not None and age < min_age, "note": note if published else (note + "; pinned release not found").lstrip("; ")}


def main(argv=None, now=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--min-age", type=int, default=14, help="days a release must be out before a pin moves to it (14)")
    ap.add_argument("--allow", action="append", default=[], metavar="NAME",
                    help="a pin the owner allowed younger than --min-age (a security fix that can't wait)")
    a = ap.parse_args(argv)
    now = now or dt.datetime.now(dt.timezone.utc)
    rows, bad = [], []
    for pin in inventory():
        try:
            r = check(pin, now, a.min_age)
        except Exception as e:      # one lookup failing shouldn't hide the rest
            r = {**pin, "age": None, "eligible": "?", "latest": "?", "young": False, "note": f"lookup failed: {e}"}
            bad.append(pin["name"])
        rows.append(r)
    print(f"Pins on {now:%Y-%m-%d}, min age {a.min_age} days (docs/build.md, \"Pinned inputs\")\n")
    print("| Pin | Kind | Pinned (age) | Newest eligible | Newest | Where | Note |\n|---|---|---|---|---|---|---|")
    young = []
    for r in rows:
        age = "?" if r["age"] is None else f"{r['age']} d"
        flag = ""
        if r["young"]:
            flag = " **allowed**" if r["name"] in a.allow else " **too new**"
            if r["name"] not in a.allow:
                young.append(r["name"])
        print(f"| {r['name']} | {r['kind']} | {r['pinned']} ({age}){flag} | {r['eligible']} | {r['latest']} | {r['where']} | {r['note']} |")
    if young:
        print(f"\npins-newest: younger than {a.min_age} days: {', '.join(young)}", file=sys.stderr)
    if bad:
        print(f"\npins-newest: couldn't look up: {', '.join(bad)}", file=sys.stderr)
    return 1 if young or bad else 0


if __name__ == "__main__":
    sys.exit(main())
