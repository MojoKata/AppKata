#!/usr/bin/env python3
"""One self-contained page of a Linux tour, for reviewing a pull request's screens in the browser
(docs/github-workflows.md, "The tour"): every screen inlined, those that differ from master's
published tour first, each beside master's, then the new ones, the ones gone, and the rest.

    tour_page.py TOUR OUT [--master URL]

TOUR is a tour's folder (dark/ and light/, as scripts/test-layout.sh leaves build/layout-tour); OUT
the page to write. --master is the Pages site whose screenshots/master/ it compares with (the
repository's own by default, as coverage_site.py names it); "none" compares with nothing. A screen
counts as changed when its file's bytes differ: the tour draws the same pixels into the same bytes,
but some screens show the day (the Audit's dates), so they differ from one day to the next. CI
uploads the page unzipped (actions/upload-artifact's archive: false), so a pull request's checks
link to it and it opens in the browser.
"""

import argparse
import base64
import hashlib
import html
import importlib.util
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
THEMES = ("dark", "light")


def _site():
    spec = importlib.util.spec_from_file_location("appkata_coverage_site", ROOT / "scripts" / "coverage_site.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def screens(folder):
    """{"dark/A01-apps.png": bytes, ...} of a tour's folder."""
    out = {}
    for theme in THEMES:
        d = Path(folder) / theme
        if d.is_dir():
            for p in sorted(d.glob("*.png")):
                out[f"{theme}/{p.name}"] = p.read_bytes()
    return out


def published(base, get=None):
    """{name: bytes} of master's published tour, as the site's screenshots/index.json lists it; {} when
    the site has none."""
    get = get or _site().get
    nonce = os.environ.get("GITHUB_RUN_ID") or str(os.getpid())
    body = get(f"{base}screenshots/index.json?{nonce}")
    out = {}
    for name in sorted(json.loads(body).get("versions", {}).get("master", [])) if body else []:
        data = get(f"{base}screenshots/master/{name}?{nonce}")
        if data is not None:
            out[name] = data
    return out


def compare(new, old):
    """(changed, added, gone, same): names, each list in order."""
    changed = [n for n in new if n in old and hashlib.sha256(new[n]).digest() != hashlib.sha256(old[n]).digest()]
    added = [n for n in new if n not in old]
    gone = [n for n in old if n not in new]
    same = [n for n in new if n in old and n not in changed]
    return changed, added, gone, same


def _img(data, alt):
    return f"<img loading='lazy' alt='{html.escape(alt)}' src='data:image/png;base64,{base64.b64encode(data).decode()}'>"


STYLE = """
:root { color-scheme: light dark; --bg: #f6f7f9; --card: #fff; --text: #1d2026; --muted: #5b6270; --line: #d9dde4;
        --accent: #5b5bd6; --warn: #b35a00; }
@media (prefers-color-scheme: dark) { :root { --bg: #14161b; --card: #1d2027; --text: #e6e8ee; --muted: #9aa1ad;
        --line: #333844; --accent: #8f8ff0; --warn: #f0a040; } }
body { margin: 0; padding: 16px 24px 48px; background: var(--bg); color: var(--text);
       font: 15px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; }
h1 { margin: 0 0 4px; font-size: 22px; } h2 { margin: 32px 0 8px; font-size: 18px; }
p { margin: 4px 0; color: var(--muted); }
nav a { margin-right: 14px; color: var(--accent); }
figure { margin: 16px 0; padding: 12px; background: var(--card); border: 1px solid var(--line); border-radius: 8px; }
figcaption { font-weight: 600; margin-bottom: 8px; }
.pair { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.pair span { display: block; font-size: 13px; color: var(--muted); margin-bottom: 4px; }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(min(360px, 100%), 1fr)); gap: 12px; }
.grid figure { margin: 0; }
img { display: block; width: 100%; height: auto; border: 1px solid var(--line); border-radius: 4px; }
details summary { cursor: pointer; color: var(--accent); margin: 8px 0; }
.warn { color: var(--warn); }
@media (max-width: 900px) { .pair { grid-template-columns: 1fr; } }
"""


def page(new, old, title, compared):
    changed, added, gone, same = compare(new, old)
    parts = [f"<h1>{html.escape(title)}</h1>"]
    if compared:
        parts.append(f"<p>{len(new)} screens: {len(changed)} differ from master's published tour, {len(added)} new, "
                     f"{len(gone)} gone, {len(same)} the same. Screens that show the day (the Audit) differ from one "
                     "day to the next.</p>")
    else:
        parts.append(f"<p class='warn'>{len(new)} screens; master's published tour wasn't read, so none is "
                     "compared.</p>")
    parts.append("<nav><a href='#changed'>Changed</a><a href='#new'>New</a><a href='#gone'>Gone</a>"
                 "<a href='#same'>The same</a></nav>")
    parts.append(f"<h2 id='changed'>Changed ({len(changed)})</h2>")
    for n in changed:
        parts.append(f"<figure><figcaption>{html.escape(n)}</figcaption><div class='pair'>"
                     f"<div><span>master</span>{_img(old[n], 'master ' + n)}</div>"
                     f"<div><span>this run</span>{_img(new[n], n)}</div></div></figure>")
    if not changed:
        parts.append("<p>None.</p>")
    parts.append(f"<h2 id='new'>New ({len(added)})</h2><div class='grid'>"
                 + "".join(f"<figure><figcaption>{html.escape(n)}</figcaption>{_img(new[n], n)}</figure>" for n in added)
                 + "</div>" + ("" if added else "<p>None.</p>"))
    parts.append(f"<h2 id='gone'>Gone ({len(gone)})</h2><div class='grid'>"
                 + "".join(f"<figure><figcaption>{html.escape(n)} (master)</figcaption>{_img(old[n], n)}</figure>"
                           for n in gone)
                 + "</div>" + ("" if gone else "<p>None.</p>"))
    parts.append(f"<h2 id='same'>The same ({len(same)})</h2><details><summary>Show them</summary><div class='grid'>"
                 + "".join(f"<figure><figcaption>{html.escape(n)}</figcaption>{_img(new[n], n)}</figure>" for n in same)
                 + "</div></details>")
    return ("<!doctype html>\n<html lang='en'>\n<head>\n<meta charset='utf-8'>\n"
            "<meta name='viewport' content='width=device-width, initial-scale=1'>\n"
            f"<title>{html.escape(title)}</title>\n<style>{STYLE}</style>\n</head>\n<body>\n"
            + "\n".join(parts) + "\n</body>\n</html>\n")


def main(argv=None):
    p = argparse.ArgumentParser(prog="tour_page.py", description=__doc__.split("\n\n")[0])
    p.add_argument("tour")
    p.add_argument("out")
    p.add_argument("--master", help="the Pages site to compare with (default: the repository's); none: no comparison")
    p.add_argument("--title", default="AppKata's Linux tour")
    p.add_argument("--summary", help="also append what changed to this Markdown file (CI's job summary)")
    args = p.parse_args(argv)
    new = screens(args.tour)
    if not new:
        print(f"no screens in {args.tour}/{{dark,light}}", file=sys.stderr)
        return 1
    old, compared = {}, args.master != "none"
    if compared:
        base = (args.master.rstrip("/") + "/") if args.master else _site().site_url()
        try:
            old = published(base)
        except (OSError, ValueError) as e:
            print(f"{base}: master's tour couldn't be read ({e}); the page compares nothing", file=sys.stderr)
            compared = False
    Path(args.out).write_text(page(new, old, args.title, compared), encoding="utf-8")
    changed, added, gone, _ = compare(new, old)
    print(f"{args.out}: {len(new)} screens, {len(changed)} changed, {len(added)} new, {len(gone)} gone, "
          f"{Path(args.out).stat().st_size / 1e6:.1f} MB")
    if args.summary:
        lines = [f"## {args.title}", "",
                 (f"{len(new)} screens: {len(changed)} differ from master's published tour, {len(added)} new, "
                  f"{len(gone)} gone." if compared else f"{len(new)} screens, not compared with master's."), ""]
        for what, names in (("Changed", changed), ("New", added), ("Gone", gone)):
            if names:
                lines += [f"{what}: " + ", ".join(f"`{n}`" for n in names), ""]
        with open(args.summary, "a", encoding="utf-8") as f:
            f.write("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
