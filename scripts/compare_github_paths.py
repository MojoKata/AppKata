#!/usr/bin/env python3
"""Read each GitHub project's releases through the API and through github.com's pages (the fallback
when the API's hour runs out, requirement 2.4.1), and say where the two disagree: a release one has
and the other hasn't, a prerelease flag, the latest version, a release's files (review 3, R3-23).

    scripts/compare_github_paths.py [owner/repo ...]    default: the demo data's projects

Uses about one API request per project; GITHUB_TOKEN raises the limit. Exits 1 on any disagreement.
"""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))
sys.path.insert(0, HERE)

from appkata_core import forges, urls  # noqa: E402
from appkata_core.http import Http  # noqa: E402


def read(repo: str, web: bool):
    http = Http({"github.com": os.environ["GITHUB_TOKEN"]} if os.environ.get("GITHUB_TOKEN") else {})
    f = forges.GitHub(http, urls.parse("https://github.com/" + repo))
    f.web = web
    return f.releases()


def compare(repo: str) -> list[str]:
    api, web = read(repo, web=False), read(repo, web=True)
    if not web:
        return []
    out = []
    by_api = {r.tag: r for r in api}
    oldest = min(r.date for r in web if r.date)          # the pages' feed reaches this far back
    for r in web:
        a = by_api.get(r.tag)
        if a is None:
            out.append(f"{r.tag}: on the pages, not a release through the API")
            continue
        if a.prerelease != r.prerelease:
            out.append(f"{r.tag}: prerelease {r.prerelease} on the pages, {a.prerelease} through the API")
        if r.assets and sorted(x.name for x in r.assets) != sorted(x.name for x in a.assets):
            out.append(f"{r.tag}: other files on the pages")
    seen = {r.tag for r in web}
    out += [f"{a.tag}: a release through the API, missing from the pages" for a in api
            if a.date >= oldest and a.tag not in seen]
    la, lw = forges.latest(api), forges.latest(web)
    if (la and la.version) != (lw and lw.version):
        out.append(f"latest: {lw and lw.version} on the pages, {la and la.version} through the API")
    return out


def main() -> int:
    repos = sys.argv[1:]
    if not repos:
        import demo_data
        repos = demo_data.SOURCES + ["upscayl/upscayl", "tukaani-project/xz", "VSCodium/vscodium", "ProtonVPN/proton-vpn-gtk-app"]
    bad = 0
    for repo in repos:
        diffs = compare(repo)
        print(f"{repo}: {'agree' if not diffs else ''}")
        for d in diffs:
            print("   ", d)
        bad += bool(diffs)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
