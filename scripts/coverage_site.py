#!/usr/bin/env python3
"""The Pages site (docs/github-workflows.md, "The Pages site"): the coverage report with its history,
the hardening page (scripts/hardening.py) and the screenshots, published to the repository's GitHub
Pages on each push to master.

    coverage_site.py build [--coverage DIR] [--screenshots DIR] [--out DIR]

builds the site into build/site/ (--out) from what `coverage_report.py report` wrote into
build/coverage/ (--coverage: totals.json, files.json and the HTML report), the history the published
site holds with this commit's totals added last, and the repository's issues. CI builds it on every
run and keeps it as the `site` artifact; on a push to master the `pages` job publishes it. Built
anywhere else, it is a preview of what publishing this commit would show, and publishes nothing.

The repository is GITHUB_REPOSITORY (owner/name), else the one APPKATA_REPO names
(src/appkata_core/__init__.py); its site is https://<owner>.github.io/<name>/, or APPKATA_SITE.

The history lives on the site alone: each push to master reads it back and adds its own entry. A site
that answers with no history.json starts one only while there is no site at all; any other failure to
read it fails the build in CI, so a bad moment never starts the history over. The screenshots are kept
the same way: the published ones, under screenshots/<version>/ as screenshots/index.json lists them, are
carried into each build, and --screenshots DIR adds or replaces the versions DIR holds
(DIR/<version>/...)."""

import argparse
import html
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COVERAGE = ROOT / "build" / "coverage"
SITE = ROOT / "build" / "site"
PR = re.compile(r"\(#(\d+)\)$")
VERSION = re.compile(r"^[0-9A-Za-z][0-9A-Za-z.+_-]*$")
# Each chart's frame, in SVG units; the page's script places the crosshair from the same.
W, H, LEFT, RIGHT, TOP, BOTTOM = 360, 150, 40, 12, 10, 24
SERIES = (("lines", "Lines"), ("branches", "Branches"))


def _load(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cr = _load("appkata_coverage_report", "coverage_report.py")
hardening = _load("appkata_hardening", "hardening.py")
areas = cr.areas

# The sums the charts and the pushes' table show: the app's code (every area but the scripts'), and
# everything.
SUMS = {"app": [a for a in areas.AREAS if a != "scripts"], "overall": list(areas.AREAS)}


def in_ci():
    return os.environ.get("GITHUB_ACTIONS") == "true"


def repository():
    """owner/name: GITHUB_REPOSITORY, else the repository APPKATA_REPO names."""
    if os.environ.get("GITHUB_REPOSITORY"):
        return os.environ["GITHUB_REPOSITORY"]
    text = (ROOT / "src" / "appkata_core" / "__init__.py").read_text(encoding="utf-8")
    return re.search(r'^APPKATA_REPO = "https://github\.com/([^"/]+/[^"/]+)"', text, re.M)[1]


def site_url():
    """The published site: APPKATA_SITE, else the repository's own Pages."""
    if os.environ.get("APPKATA_SITE"):
        return os.environ["APPKATA_SITE"].rstrip("/") + "/"
    owner, name = repository().split("/")
    return f"https://{owner.lower()}.github.io/{name}/"


def repo_url():
    return f"{os.environ.get('GITHUB_SERVER_URL', 'https://github.com')}/{repository()}"


def get(url):
    """What the site serves at url, or None when it answers 404."""
    request = urllib.request.Request(url, headers={"Cache-Control": "no-cache", "User-Agent": "coverage_site.py"})
    try:
        with urllib.request.urlopen(request, timeout=30) as r:                       # noqa: S310
            return r.read()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def published(base, nonce, path):
    """A file the site keeps across builds (path, from its root), parsed; None while there is no site at
    all. `nonce` keeps a cache on the way from answering with an older copy."""
    body = get(f"{base}{path}?{nonce}")
    if body is not None:
        return json.loads(body)
    if get(base) is not None:
        raise SystemExit(f"{base} is up but has no {path}: not starting it over")
    return None


def fetch_history(base, nonce):
    """The published history; empty while there is no site."""
    return published(base, nonce, "history.json") or []


def git(*args):
    return subprocess.run([shutil.which("git") or "git", *args], cwd=ROOT, capture_output=True, text=True)


def entry(by_area):
    """This commit's point in the history: its totals by area, and the pull request its subject names
    (a squash merge ends with "(#19)")."""
    r = git("log", "-1", "--format=%H%n%cI%n%s", "HEAD")
    commit, date, subject = [*r.stdout.splitlines(), "", "", ""][:3]
    m = PR.search(subject)
    return {"commit": commit, "date": date, "pr": int(m[1]) if m else None, "subject": subject, "areas": by_area}


def add(history, e):
    """The history with e last; a commit already in it (a run done again) moves to the end with what was
    measured this time."""
    return [h for h in history if h["commit"] != e["commit"]] + [e]


def figure(h, area, kind):
    """An entry's figure for an area, or for one of the sums."""
    if area in SUMS:
        return cr.total({a: t for a, t in h["areas"].items() if a in SUMS[area]} or {"": cr.counted(0, 0, 0, 0, 0)})[kind]
    return (h["areas"].get(area) or {}).get(kind)


def band(v):
    """How well a figure is tested: top from 95%, good from 80%, fair from 60%, else low."""
    return "top" if v >= 95 else "good" if v >= 80 else "fair" if v >= 60 else "low"


# ---------- the coverage page ----------


def x_at(i, n):
    return LEFT + (W - LEFT - RIGHT) * (i / (n - 1) if n > 1 else 0.5)


def y_at(v):
    return TOP + (H - TOP - BOTTOM) * (1 - v / 100)


def label(h):
    return f"#{h['pr']}" if h["pr"] else h["commit"][:7]


def chart(history, area):
    """One area's line and branch coverage over the pushes: a 0-100% scale, a hairline grid, 2px lines,
    a ringed dot on each series' last point (and on any point alone)."""
    n = len(history)
    out = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="{html.escape(area)}: line and branch coverage '
           f'over the pushes">']
    for v in (0, 50, 100):
        y = y_at(v)
        out.append(f'<line class="grid" x1="{LEFT}" x2="{W - RIGHT}" y1="{y:.1f}" y2="{y:.1f}"/>')
        out.append(f'<text class="axis" x="{LEFT - 6}" y="{y + 3.5:.1f}" text-anchor="end">{v}%</text>')
    for i, anchor in ([(0, "start"), (n - 1, "end")] if n > 1 else [(0, "middle")]):
        out.append(f'<text class="axis" x="{x_at(i, n):.1f}" y="{H - 6}" text-anchor="{anchor}">'
                   f'{html.escape(label(history[i]))}</text>')
    for kind, _ in SERIES:
        values = [figure(h, area, kind) for h in history]
        path, dots = [], []
        for i, v in enumerate(values):
            if v is None:
                continue
            joined = i > 0 and values[i - 1] is not None
            path.append(f"{'L' if joined else 'M'}{x_at(i, n):.1f} {y_at(v):.1f}")
            alone = not joined and (i == n - 1 or values[i + 1] is None)
            if alone or all(w is None for w in values[i + 1:]):
                dots.append(f'<circle class="dot {kind}" cx="{x_at(i, n):.1f}" cy="{y_at(v):.1f}" r="4"/>')
        if path:
            out.append(f'<path class="line {kind}" d="{" ".join(path)}"/>')
        out += dots
    out.append(f'<line class="cross" x1="0" x2="0" y1="{TOP}" y2="{H - BOTTOM}" visibility="hidden"/>')
    out.append("</svg>")
    return "".join(out)


def pct(v):
    return "—" if v is None else f"{v:.1f}%"


def change(now, was):
    if now is None or was is None or round(now - was, 1) == 0:
        return ""
    return f"{now - was:+.1f}".replace("-", "−")


def keyed(kind, text):
    return f'<span class="key {kind}"></span>{text}'


def meter(kind, v, floor=None, was=None):
    """A bar for a percentage in its band's colour, a tick at the floor (striped below it), the figure,
    marked with a star from 95%, and its change."""
    if v is None:
        return "<td class='m'><span class='meter none'></span><span class='star'></span><span class='pct'>—</span></td>"
    below = " below" if floor is not None and v < floor else ""
    tick = f"<i style='left:{floor}%' title='floor {pct(floor)}'></i>" if floor is not None else ""
    name = band(v)
    # a star's bar stays green: gold beside amber would blur the bands, so the star is its mark
    star = "<span class='star' title='95% and up'>★</span>" if name == "top" else "<span class='star'></span>"
    return (f"<td class='m'><span class='meter {kind} {name}{below}'><b style='width:{v}%'></b>{tick}</span>"
            f"{star}<span class='pct'>{pct(v)}</span><span class='delta'>{change(v, was)}</span></td>")


def cells(t, floor=None, was=None):
    """A row's figures: lines and branches, each a bar and the count reached."""
    out = []
    for kind, _ in SERIES:
        out.append(meter(kind, t[kind], (floor or {}).get(kind), (was or {}).get(kind)))
        out.append(f"<td class='n'>{cr.reached(t, kind)}</td>")
    return "".join(out)


def sort_keys(name, t, q=""):
    """What the page's script sorts and filters a row by."""
    keys = {"name": name, "lines": t["lines"], "lc": t["lineCount"], "branches": t["branches"], "bc": t["branchCount"]}
    attrs = "".join(f' data-{k}="{html.escape("" if v is None else str(v))}"' for k, v in keys.items())
    return attrs + (f' data-q="{html.escape(q.lower())}"' if q else "")


def area_group(area, t, floor, was, files):
    """An area's row, and its files' rows under it, shown when it is opened."""
    fl = floor or {}
    floor_text = f"{pct(fl.get('lines'))} / {pct(fl.get('branches'))}".replace("% /", " /") if floor else ""
    rows = [f"<tr class='head'{sort_keys(area, t, area)}><th><span class='caret'></span>{html.escape(area)}</th>"
            f"{cells(t, floor, was)}<td class='n'>{t['files']:,}</td><td class='floor'>{floor_text}</td></tr>"]
    for f in files:
        name = html.escape(f["path"])
        link = f"<a href='{html.escape(f['report'])}'>{name}</a>" if f.get("report") else name
        rows.append(f"<tr class='file'{sort_keys(f['path'], f, f['path'])}><th>{link}</th>{cells(f)}<td></td><td></td></tr>")
    return f"<tbody class='area'>{''.join(rows)}</tbody>"


def banner(by_area):
    """The headline: everything as one, and the app's code without the scripts."""
    t = cr.total(by_area)
    app = {a: v for a, v in by_area.items() if a in SUMS["app"]}
    sides = " · ".join(f"{name} <b>{pct(cr.total(part)['lines']) if part else '—'}</b>"
                       for name, part in (("App", app), ("Scripts", {a: v for a, v in by_area.items() if a == "scripts"})))
    return (f"<div class='banner'><div class='label'>Overall</div>"
            f"<div><div class='big'>{pct(t['lines'])}</div><div>of {t['lineCount']:,} lines reached</div></div>"
            f"<div><div class='big b'>{pct(t['branches'])}</div><div>of {t['branchCount']:,} branches taken</div></div>"
            f"<div class='sides'><div>Lines by side</div><div>{sides}</div><div>{t['files']:,} files</div></div></div>")


def page(history, floors, files, base, repo):
    last = history[-1]
    before = history[-2] if len(history) > 1 else None
    charted = [*SUMS, *last["areas"]]
    commit = html.escape(last["commit"][:7])
    pr = f' (<a href="{repo}/pull/{last["pr"]}">#{last["pr"]}</a>)' if last["pr"] else ""

    by_area = {}
    for f in files:
        by_area.setdefault(f["area"], []).append(f)
    groups = [area_group(area, t, floors.get(area), (before["areas"].get(area) if before else None),
                         by_area.get(area, [])) for area, t in last["areas"].items()]
    sums = []
    for name in SUMS:
        part = {a: v for a, v in last["areas"].items() if a in SUMS[name]}
        if not part:
            continue
        t = cr.total(part)
        was = cr.total({a: v for a, v in before["areas"].items() if a in SUMS[name]} or part) if before else None
        sums.append(f"<tr class='sum'><th>{name.capitalize()}</th>{cells(t, None, was)}"
                    f"<td class='n'>{t['files']:,}</td><td></td></tr>")

    figures = []
    for area in charted:
        latest = " · ".join(keyed(k, f"{name} {pct(figure(last, area, k))}") for k, name in SERIES)
        figures.append(f'<figure class="chart" data-area="{html.escape(area)}"><figcaption><b>{html.escape(area)}</b>'
                       f'<span>{latest}</span></figcaption>{chart(history, area)}<div class="tip" hidden></div></figure>')

    pushes = []
    for h in reversed(history):
        link = f'<a href="{repo}/commit/{h["commit"]}">{html.escape(h["commit"][:7])}</a>'
        pr_cell = f'<a href="{repo}/pull/{h["pr"]}">#{h["pr"]}</a>' if h["pr"] else ""
        figs = "".join(f"<td>{' / '.join(pct(figure(h, a, k)) for k, _ in SERIES)}</td>" for a in SUMS)
        pushes.append(f"<tr><td>{html.escape(h['date'][:10])}</td><td>{pr_cell}</td><td>{link}</td>{figs}"
                      f"<td class='subject'>{html.escape(h['subject'])}</td></tr>")

    data = {"frame": {"w": W, "left": LEFT, "right": RIGHT},
            "pushes": [{"label": label(h), "date": h["date"][:10]} for h in history],
            "series": {a: {k: [figure(h, a, k) for h in history] for k, _ in SERIES} for a in charted}}
    unmeasured = ", ".join(f"<code>{a}</code>" for a in cr.UNMEASURED)
    return TEMPLATE.format(
        commit=commit, commit_url=f"{repo}/commit/{last['commit']}", pr=pr, subject=html.escape(last["subject"]),
        date=html.escape(last["date"][:10]), pushes_count=len(history), banner=banner(last["areas"]),
        groups="\n".join(groups), sums="\n".join(sums), figures="\n".join(figures), pushes="\n".join(pushes),
        data=json.dumps(data, separators=(",", ":")).replace("</", "<\\/"), base=html.escape(base),
        unmeasured=unmeasured)


STYLE = """:root {
  color-scheme: light;
  --surface: #fcfcfb; --raised: #f3f2ee; --text: #0b0b0b; --text-2: #52514e; --muted: #898781;
  --grid: #e1e0d9; --track: #e9e8e2; --border: rgba(11, 11, 11, 0.10);
  --lines: #2a78d6; --branches: #eb6834; --bad: #c8312b;
  --good: #2f9e55; --fair: #d79b0f; --stripe: rgba(255, 255, 255, 0.55); --gold: #b8860b;
}
@media (prefers-color-scheme: dark) {
  :root {
    color-scheme: dark;
    --surface: #1a1a19; --raised: #232321; --text: #f0efec; --text-2: #c3c2b7; --muted: #898781;
    --grid: #2c2c2a; --track: #34342f; --border: rgba(255, 255, 255, 0.10);
    --lines: #3987e5; --branches: #d95926; --bad: #e5534b;
    --good: #3fb768; --fair: #e2ab2b; --stripe: rgba(0, 0, 0, 0.5); --gold: #f2c94c;
  }
}
* { box-sizing: border-box; }
body { margin: 0 auto; max-width: 1400px; padding: 24px 16px 48px; background: var(--surface);
  color: var(--text); font: 16px/1.45 system-ui, -apple-system, "Segoe UI", sans-serif; }
a { color: inherit; }
h1 { font-size: 27px; margin: 0 0 4px; }
h2 { font-size: 20px; margin: 32px 0 8px; }
p { margin: 4px 0; color: var(--text-2); max-width: 80ch; }
nav { margin: 0 0 12px; color: var(--text-2); }
.scroll { overflow-x: auto; }"""

TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AppKata coverage</title>
<style>
""" + STYLE.replace("{", "{{").replace("}", "}}") + """
table {{ border-collapse: collapse; font-variant-numeric: tabular-nums; }}
th, td {{ padding: 5px 10px; border-bottom: 1px solid var(--border); text-align: right; white-space: nowrap; }}
th:first-child, th.subject, td.subject {{ text-align: left; }}
thead th {{ color: var(--text-2); font-weight: 600; }}
td.floor {{ color: var(--text-2); }}
td.subject {{ white-space: normal; color: var(--text-2); }}

.banner {{ display: flex; flex-wrap: wrap; gap: 16px 48px; align-items: flex-end; margin: 20px 0 8px;
  padding: 20px 24px; border: 1px solid var(--border); border-radius: 12px; background: var(--raised);
  color: var(--text-2); }}
.banner .big {{ font-size: 42px; font-weight: 700; line-height: 1.1; color: var(--lines); font-variant-numeric: tabular-nums; }}
.banner .big.b {{ color: var(--branches); }}
.banner .label {{ width: 100%; margin-bottom: -12px; font-weight: 600; }}
.banner .sides {{ margin-left: auto; text-align: right; }}
.banner .sides b {{ color: var(--text); }}

.tools {{ display: flex; flex-wrap: wrap; gap: 8px 16px; align-items: center; margin: 12px 0; color: var(--text-2); }}
.tools input {{ font: inherit; width: 22em; max-width: 100%; padding: 6px 10px; color: var(--text);
  background: var(--surface); border: 1px solid var(--border); border-radius: 6px; }}
#areas thead th button {{ font: inherit; color: inherit; background: none; border: 0; padding: 0; cursor: pointer; }}
#areas thead th[aria-sort] button::after {{ content: " ↑"; }}
#areas thead th[aria-sort="descending"] button::after {{ content: " ↓"; }}
#areas thead th[data-key="lines"], #areas thead th[data-key="branches"] {{ text-align: left; }}
#areas tbody.area tr.head {{ cursor: pointer; }}
#areas tbody.area tr.head:hover {{ background: var(--raised); }}
#areas tbody.area tr.head th {{ font-weight: 600; }}
.caret {{ display: inline-block; width: 1em; color: var(--muted); }}
.caret::before {{ content: "▸"; }}
tbody.open .caret::before, tbody.found .caret::before {{ content: "▾"; }}
#areas tr.file {{ display: none; font-size: 15px; }}
#areas tbody.open tr.file, #areas tbody.found tr.file {{ display: table-row; }}
#areas tbody.area tr.file.miss {{ display: none; }}
#areas tr.file th {{ padding-left: 40px; font-weight: 400; }}
#areas tr.file th a {{ text-decoration: none; }}
#areas tr.file th a:hover {{ text-decoration: underline; }}
#areas tfoot th, #areas tfoot td {{ font-weight: 600; border-bottom: 0; }}
#areas tfoot tr:first-child > * {{ border-top: 2px solid var(--grid); }}
#areas tfoot tr:last-child > * {{ font-size: 18px; }}
td.m {{ text-align: left; }}
td.n {{ color: var(--text-2); }}
.meter {{ position: relative; display: inline-block; width: 110px; height: 12px; vertical-align: middle;
  border-radius: 6px; background: var(--track); }}
#areas tr.file .meter {{ height: 8px; }}
.meter b {{ position: absolute; inset: 0 auto 0 0; border-radius: 6px; }}
.meter.top b, .meter.good b {{ background-color: var(--good); }}
.meter.fair b {{ background-color: var(--fair); }}
.meter.low b {{ background-color: var(--bad); }}
.meter.below b {{ background-image: repeating-linear-gradient(135deg, transparent 0 3px, var(--stripe) 3px 6px); }}
.meter.none {{ visibility: hidden; }}
.meter i {{ position: absolute; top: -4px; bottom: -4px; width: 2px; margin-left: -1px; background: var(--text); }}
.pct {{ display: inline-block; width: 3.9em; text-align: right; }}
.star {{ display: inline-block; width: 1.1em; text-align: right; color: var(--gold); }}
.delta {{ display: inline-block; width: 3.2em; text-align: right; font-size: 14px; color: var(--text-2); }}

.legend {{ display: flex; flex-wrap: wrap; gap: 6px 16px; color: var(--text-2); margin: 8px 0 12px; }}
.key {{ display: inline-block; width: 14px; height: 2px; vertical-align: middle; margin-right: 6px; border-radius: 1px; }}
.key.lines {{ background: var(--lines); }}
.key.branches {{ background: var(--branches); }}
.swatch {{ display: inline-block; width: 22px; height: 12px; vertical-align: middle; margin-right: 6px; border-radius: 6px; }}
.swatch.good {{ background-color: var(--good); }}
.swatch.fair {{ background-color: var(--fair); }}
.swatch.low {{ background-color: var(--bad); }}
.swatch.below {{ background-image: repeating-linear-gradient(135deg, transparent 0 3px, var(--stripe) 3px 6px); }}
.charts {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(min(380px, 100%), 1fr)); gap: 16px; }}
figure {{ position: relative; margin: 0; padding: 10px 12px 4px; border: 1px solid var(--border); border-radius: 8px; }}
figcaption {{ font-size: 16px; }}
figcaption > span {{ display: block; color: var(--text-2); font-size: 15px; font-variant-numeric: tabular-nums; }}
svg {{ display: block; width: 100%; height: auto; overflow: visible; }}
.grid {{ stroke: var(--grid); stroke-width: 1; }}
.axis {{ fill: var(--muted); font-size: 13px; }}
.line {{ fill: none; stroke-width: 2; stroke-linejoin: round; stroke-linecap: round; }}
.line.lines {{ stroke: var(--lines); }}
.line.branches {{ stroke: var(--branches); }}
.dot {{ stroke: var(--surface); stroke-width: 2; }}
.dot.lines {{ fill: var(--lines); }}
.dot.branches {{ fill: var(--branches); }}
.cross {{ stroke: var(--muted); stroke-width: 1; }}
.tip {{ position: absolute; pointer-events: none; padding: 6px 8px; border-radius: 6px; background: var(--surface);
  border: 1px solid var(--border); color: var(--text); font-size: 15px; white-space: nowrap;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.12); }}
.tip div {{ color: var(--text-2); }}
details summary {{ cursor: pointer; font-weight: 600; margin: 32px 0 8px; }}
</style>
</head>
<body>
<h1>AppKata coverage</h1>
<nav><b>Coverage</b> · <a href="hardening.html">Hardening</a> · <a href="screenshots/index.html">Screenshots</a></nav>
<p>As of <a href="{commit_url}">{commit}</a>{pr}, {date}: {subject}</p>
{banner}
<p>What tier 1 reaches, measured by CI's <code>coverage</code> job on each push to <code>master</code>
(<code>scripts/coverage_report.py</code>). Line by line: <a href="report/index.html">the report</a>.
The history: <a href="history.json">history.json</a> ({pushes_count} pushes); each file's counts:
<a href="files.json">files.json</a>. The sweep's steps, findings, gaps and questions:
<a href="hardening.html">hardening</a>. The app's screens, by version: <a href="screenshots/index.html">screenshots</a>.</p>

<h2>By area</h2>
<div class="tools"><input id="filter" type="search" placeholder="Filter files, e.g. sync or backend.py"
 aria-label="Filter files"><span>Click an area for its files, a heading to sort.</span></div>
<div class="scroll"><table id="areas">
<thead><tr><th data-key="name"><button>Area</button></th>
<th data-key="lines"><button>Lines</button></th>
<th data-key="lc"><button>Lines reached</button></th>
<th data-key="branches"><button>Branches</button></th>
<th data-key="bc"><button>Branches taken</button></th><th>Files</th>
<th title="The floor: lines / branches">Floor</th></tr></thead>
{groups}
<tfoot>
{sums}
</tfoot>
</table></div>
<div class="legend"><span><span class="star">★</span> 95% and up</span>
<span><span class="swatch good"></span>80% and up</span>
<span><span class="swatch fair"></span>60% to 80%</span>
<span><span class="swatch low"></span>under 60%</span>
<span><span class="swatch fair below"></span>below its floor</span></div>
<p>The change is since the push before. A bar's colour is how well it is tested, and a star marks 95% and
up; the tick on it is the area's floor (<code>tests/coverage-floor.json</code>, its lines' / branches' in
the last column), and a bar below its floor is striped. <i>App</i> is every area but the scripts';
<i>Overall</i> is every area. QML ({unmeasured}) isn't Python, and coverage.py doesn't measure it.
Sorting by a count sorts by size.</p>

<h2>Over the pushes</h2>
<div class="legend"><span><span class="key lines"></span>Lines</span>
<span><span class="key branches"></span>Branches</span></div>
<div class="charts">
{figures}
</div>

<details>
<summary>Every push, its lines / branches</summary>
<div class="scroll"><table>
<thead><tr><th>Date</th><th>PR</th><th>Commit</th>
<th title="Lines / branches">App</th><th title="Lines / branches">Overall</th>
<th class="subject">Subject</th></tr></thead>
<tbody>
{pushes}
</tbody>
</table></div>
</details>

<script type="application/json" id="data">{data}</script>
<script>
(() => {{
  // By area: sorting by a heading, opening an area, and the filter.
  const table = document.getElementById("areas");
  const groups = [...table.tBodies];
  const sort = {{ key: "lines", dir: 1 }};
  const value = (tr) => {{
    const v = tr.dataset[sort.key];
    return sort.key === "name" ? v.toLowerCase() : v === "" ? null : Number(v);
  }};
  const byKey = (a, b) => {{
    const x = value(a), y = value(b);
    if (x === y) return a.dataset.name.localeCompare(b.dataset.name);
    if (x === null) return 1;
    if (y === null) return -1;
    return (x < y ? -1 : 1) * sort.dir;
  }};
  const order = () => {{
    groups.sort((g, h) => byKey(g.rows[0], h.rows[0]));
    for (const g of groups) {{
      table.insertBefore(g, table.tFoot);
      g.append(...[...g.rows].slice(1).sort(byKey));
    }}
    for (const th of table.tHead.querySelectorAll("th[data-key]")) {{
      if (th.dataset.key === sort.key) th.setAttribute("aria-sort", sort.dir > 0 ? "ascending" : "descending");
      else th.removeAttribute("aria-sort");
    }}
  }};
  for (const th of table.tHead.querySelectorAll("th[data-key]")) {{
    th.querySelector("button").addEventListener("click", () => {{
      sort.dir = sort.key === th.dataset.key ? -sort.dir : 1;
      sort.key = th.dataset.key;
      order();
    }});
  }}
  for (const g of groups) g.rows[0].addEventListener("click", () => g.classList.toggle("open"));
  const filter = document.getElementById("filter");
  filter.addEventListener("input", () => {{
    const q = filter.value.trim().toLowerCase();
    for (const g of groups) {{
      let found = false;
      for (const tr of [...g.rows].slice(1)) {{
        const hit = !q || tr.dataset.q.includes(q);
        tr.classList.toggle("miss", !hit);
        found ||= Boolean(q) && hit;
      }}
      g.classList.toggle("found", found);
      g.hidden = Boolean(q) && !found && !g.rows[0].dataset.q.includes(q);
    }}
  }});
  order();

  // The charts: each push's figures on hover.
  const data = JSON.parse(document.getElementById("data").textContent);
  const {{ w, left, right }} = data.frame;
  const n = data.pushes.length;
  const pct = (v) => (v == null ? "—" : v.toFixed(1) + "%");
  for (const fig of document.querySelectorAll("figure.chart")) {{
    const svg = fig.querySelector("svg");
    const cross = svg.querySelector(".cross");
    const tip = fig.querySelector(".tip");
    const series = data.series[fig.dataset.area];
    svg.addEventListener("pointermove", (e) => {{
      const box = svg.getBoundingClientRect();
      const x = ((e.clientX - box.left) / box.width) * w;
      const step = n > 1 ? (w - left - right) / (n - 1) : 0;
      const i = n > 1 ? Math.max(0, Math.min(n - 1, Math.round((x - left) / step))) : 0;
      const at = n > 1 ? left + i * step : left + (w - left - right) / 2;
      cross.setAttribute("x1", at);
      cross.setAttribute("x2", at);
      cross.setAttribute("visibility", "visible");
      const m = data.pushes[i];
      tip.innerHTML = "";
      const head = document.createElement("b");
      head.textContent = m.label + " · " + m.date;
      tip.append(head);
      for (const [kind, name] of [["lines", "Lines"], ["branches", "Branches"]]) {{
        const row = document.createElement("div");
        const key = document.createElement("span");
        key.className = "key " + kind;
        row.append(key, name + " " + pct(series[kind][i]));
        tip.append(row);
      }}
      tip.hidden = false;
      const fbox = fig.getBoundingClientRect();
      const px = box.left - fbox.left + (at / w) * box.width;
      const room = fbox.width - tip.offsetWidth - 8;
      const left_ = px + 12 > room ? px - tip.offsetWidth - 12 : px + 12;
      tip.style.left = Math.max(8, Math.min(room, left_)) + "px";
      tip.style.top = box.top - fbox.top + 8 + "px";
    }});
    svg.addEventListener("pointerleave", () => {{
      cross.setAttribute("visibility", "hidden");
      tip.hidden = true;
    }});
  }}
}})();
</script>
<!-- built from {base} -->
</body>
</html>
"""


# ---------- the screenshots ----------


def _version_key(v):
    return [(0, int(p), "") if p.isdigit() else (1, 0, p) for p in re.split(r"[.+_-]", v)]


def _safe(rel):
    """A file's path under its version's folder, as the index may name it: relative, without '..'."""
    parts = rel.split("/")
    return bool(rel) and not rel.startswith("/") and all(p not in ("", ".", "..") for p in parts) and "\\" not in rel


def screenshots(base, nonce, dest, new=None, fetch=True):
    """{version: [file, ...]} of the screenshots the site holds, written under dest/<version>/: the
    published ones carried over (none when `fetch` is false), and those in `new` (a folder of
    <version>/ folders) added or put in their place."""
    index = {}
    added = {}
    if new and Path(new).is_dir():
        for d in sorted(Path(new).iterdir()):
            if d.is_dir() and VERSION.match(d.name):
                added[d.name] = sorted(p.relative_to(d).as_posix() for p in d.rglob("*") if p.is_file())
    old = (published(base, nonce, "screenshots/index.json") or {}).get("versions", {}) if fetch else {}
    for version, names in old.items():
        if version in added or not VERSION.match(version):
            continue
        for rel in names:
            if not _safe(rel):
                raise SystemExit(f"screenshots/index.json names {version}/{rel}: not a file under its version")
            body = get(f"{base}screenshots/{version}/{rel}?{nonce}")
            if body is None:
                raise SystemExit(f"{base}screenshots/{version}/{rel} is listed but not there")
            (dest / version / rel).parent.mkdir(parents=True, exist_ok=True)
            (dest / version / rel).write_bytes(body)
        index[version] = list(names)
    for version, names in added.items():
        shutil.copytree(Path(new) / version, dest / version, dirs_exist_ok=True)
        index[version] = names
    return dict(sorted(index.items(), key=lambda kv: _version_key(kv[0]), reverse=True))


def screenshots_page(index):
    """The screenshots' page: each version's, newest first, each image linked to itself."""
    out = []
    for version, names in index.items():
        images = [n for n in names if n.lower().endswith((".png", ".jpg", ".jpeg", ".webp"))]
        tiles = "".join(f"<a href='{html.escape(version)}/{html.escape(n)}'><img loading='lazy' alt='{html.escape(n)}' "
                        f"src='{html.escape(version)}/{html.escape(n)}'><span>{html.escape(n)}</span></a>" for n in images)
        out.append(f"<h2 id='v{html.escape(version)}'>{html.escape(version)}</h2>"
                   f"<p>{len(images)} screens.</p><div class='shots'>{tiles}</div>")
    body = "\n".join(out) or ("<p class='none'>None are published. CI's Linux tour publishes each version's under "
                              "<code>screenshots/&lt;version&gt;/</code>.</p>")
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AppKata screenshots</title>
<style>
{STYLE}
.shots {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(min(320px, 100%), 1fr)); gap: 16px; }}
.shots a {{ display: block; text-decoration: none; color: var(--text-2); font-size: 14px; }}
.shots img {{ display: block; width: 100%; height: auto; border: 1px solid var(--border); border-radius: 6px; }}
.none {{ margin-top: 16px; }}
</style>
</head>
<body>
<h1>AppKata screenshots</h1>
<nav><a href="../index.html">Coverage</a> · <a href="../hardening.html">Hardening</a> · <b>Screenshots</b></nav>
<p>The app's screens as each version shows them, from CI's Linux tour. The list:
<a href="index.json">index.json</a>.</p>
{body}
</body>
</html>
"""


# ---------- building it ----------


def with_reports(files, html_dir):
    """The files' rows, each with its line-by-line report's page (from coverage.py's status.json)."""
    status = Path(html_dir) / "status.json"
    urls = {}
    if status.exists():
        for f in json.loads(status.read_text()).get("files", {}).values():
            index = f.get("index", {})
            if index.get("file") and index.get("url"):
                urls[index["file"]] = "report/" + index["url"]
    return [{**f, "report": urls[f["path"]]} if f["path"] in urls else f for f in files]


def build(coverage=COVERAGE, out=SITE, shots=None):
    coverage, out = Path(coverage), Path(out)
    totals_file = coverage / "totals.json"
    if not totals_file.exists():
        print(f"nothing measured in {coverage}: run scripts/coverage_report.py report first, or download a CI "
              "run's coverage artifact (gh run download RUN -n coverage)")
        return 1
    by_area = json.loads(totals_file.read_text())
    base = site_url()
    nonce = os.environ.get("GITHUB_RUN_ID") or str(os.getpid())
    reachable = True
    try:
        history = fetch_history(base, nonce)
    except (OSError, ValueError) as e:
        if in_ci():
            raise
        print(f"{base}history.json couldn't be read ({e}); the preview starts without it")
        history, reachable = [], False
    files_file = coverage / "files.json"
    files = with_reports(json.loads(files_file.read_text()) if files_file.exists() else [], coverage / "html")
    repo = repo_url()
    try:
        issues = hardening.fetch_issues(repository())
    except (OSError, ValueError) as e:
        if in_ci():
            raise
        print(f"the issues couldn't be read ({e}); the preview has none")
        issues = []
    this = entry(by_area)
    this["hardening"] = hardening.figures(areas.AREAS, hardening.from_issues(issues)[1])
    history = add(history, this)

    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    if (coverage / "html").is_dir():
        shutil.copytree(coverage / "html", out / "report")
    (out / "history.json").write_text("[\n" + ",\n".join(json.dumps(h, sort_keys=True) for h in history) + "\n]\n")
    (out / "files.json").write_text(json.dumps(files, indent=1) + "\n")
    (out / "screenshots").mkdir()
    index = screenshots(base, nonce, out / "screenshots", shots, fetch=reachable)
    (out / "screenshots" / "index.json").write_text(json.dumps({"versions": index}, indent=1) + "\n")
    (out / "screenshots" / "index.html").write_text(screenshots_page(index), encoding="utf-8")
    (out / "index.html").write_text(page(history, cr.floors(), files, base, repo), encoding="utf-8")
    (out / "hardening.html").write_text(hardening.page(history, list(areas.AREAS), repo, issues), encoding="utf-8")
    print(f"{out / 'index.html'}: {len(history)} pushes, {len(issues)} issues, {len(index)} screenshot versions"
          + ("" if in_ci() else ", a preview"))
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="coverage_site.py", description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="what", required=True)
    b = sub.add_parser("build", help="build the site")
    b.add_argument("--coverage", default=str(COVERAGE), help="what coverage_report.py report wrote (build/coverage)")
    b.add_argument("--screenshots", help="a folder of <version>/ folders of screenshots to add")
    b.add_argument("--out", default=str(SITE), help="where to build it (build/site)")
    args = p.parse_args(argv)
    return build(args.coverage, args.out, args.screenshots)


if __name__ == "__main__":
    sys.exit(main())
