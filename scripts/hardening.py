"""The hardening page of the Pages site (docs/github-workflows.md, "The Pages site"): a sweep's steps,
each step's findings with their severity, area and state, the coverage and the findings by area, and
the open gaps and questions. scripts/coverage_site.py builds it beside the coverage page and keeps each
push's findings by area in the history, so a step's result is what changed in its areas at its merge.

Its source is the repository's issues, read from GitHub's GraphQL API (the project board isn't read):

- a step is an issue labelled `hardening`, with no parent, titled "H<sweep>.<n> <what>" ("H1.6 Trust
  and signatures"); its pull request is the one GitHub links as closing it, merged or open;
- its findings are its sub-issues, titled "H<sweep>.<n>-<m> <what>", each in the area its `area:`
  label names, else its step's, with the severity its body gives ("severity High", "Med" or "Low";
  none given reads as unrated). A finding is open, or a question while open and labelled `question`;
  fixed when closed as completed, else closed;
- the gaps and questions are the open issues labelled `gap` or `question` that aren't findings.

Only an issue's number, title, labels, state and severity reach the page: no body text does.

Each area's mutation testing comes from its latest record in docs/hardening/mutation/
(scripts/mutate.py, docs/testing.md "Mutation testing"): its changes and survivors, and the
modules changed since that record or in none, which mark it "baseline, changed since"."""

import importlib.util
import json
import os
import re
import shutil
import subprocess
import urllib.request
from pathlib import Path

PAGE = Path(__file__).with_name("hardening.html")
ROOT = Path(__file__).resolve().parent.parent
LABEL = "hardening"
# a step's title, "H1.6 Trust and signatures"; a finding's, "H1.6-2 What goes wrong (CR1-14)"
TITLE = re.compile(r"^H(\d+)\.(\d+)(?:-(\d+))? +(.*?)(?: \((CR\d+-\d+)\))?$")
SEVERITY = re.compile(r"\bseverity:? *\**(High|Med|Low)\b", re.I)
# a step's or a finding's pull request, when GitHub links none: "done by #44", "Fixed by #44"
BODY_PR = re.compile(r"\b(?:done|fixed) by #(\d+)", re.I)
SEVERITIES = ("High", "Med", "Low")
NO_AREA = "no area"
API = "https://api.github.com/graphql"
QUERY = """query($owner: String!, $name: String!, $after: String) {
  repository(owner: $owner, name: $name) {
    issues(first: 100, after: $after, orderBy: {field: CREATED_AT, direction: ASC}) {
      pageInfo { hasNextPage endCursor }
      nodes {
        number title body state stateReason
        labels(first: 30) { nodes { name } }
        parent { number }
        closedByPullRequestsReferences(first: 5, includeClosedPrs: true) { nodes { number state } }
      }
    }
  }
}"""


# ---------- the issues ----------


def token():
    """GITHUB_TOKEN (CI's) or GH_TOKEN; outside CI, gh's own when it is signed in. GitHub's GraphQL
    API answers no one without a token."""
    for var in ("GITHUB_TOKEN", "GH_TOKEN"):
        if os.environ.get(var):
            return os.environ[var]
    if os.environ.get("GITHUB_ACTIONS") != "true" and shutil.which("gh"):
        r = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    return None


def post(query, variables):
    """One GraphQL request's data; an OSError when GitHub can't be reached or refuses, a ValueError
    when it answers with errors."""
    req = urllib.request.Request(API, data=json.dumps({"query": query, "variables": variables}).encode(),
                                 headers={"Content-Type": "application/json", "User-Agent": "coverage_site.py"})
    t = token()
    if t:
        req.add_header("Authorization", f"Bearer {t}")
    with urllib.request.urlopen(req, timeout=30) as r:          # noqa: S310 (https, a fixed host)
        answer = json.loads(r.read())
    if answer.get("errors"):
        raise ValueError(f"GitHub's GraphQL API: {answer['errors']}")
    return answer["data"]


def normal(node):
    """An issue as the page reads it: its labels' names, its parent's number, its pull requests."""
    prs = [p for p in node.get("closedByPullRequestsReferences", {}).get("nodes", []) if p]
    return {"number": node["number"], "title": node["title"], "body": node.get("body") or "",
            "state": node["state"].lower(), "reason": (node.get("stateReason") or "").lower() or None,
            "labels": [lb["name"] for lb in node["labels"]["nodes"]],
            "parent": (node.get("parent") or {}).get("number"),
            "prs": [(p["number"], p["state"].lower()) for p in prs]}


def fetch_issues(repo):
    """Every issue of `repo` (owner/name), open and closed, page by page."""
    owner, name = repo.split("/")
    out, after = [], None
    while True:
        issues = post(QUERY, {"owner": owner, "name": name, "after": after})["repository"]["issues"]
        out += [normal(n) for n in issues["nodes"]]
        if not issues["pageInfo"]["hasNextPage"]:
            return out
        after = issues["pageInfo"]["endCursor"]


def _pr(issue):
    """The pull request that closes an issue: a merged one, else an open one, else the one its body
    names; None when there is none."""
    for want in ("merged", "open"):
        for n, state in issue["prs"]:
            if state == want:
                return n
    m = BODY_PR.search(issue["body"])
    return int(m[1]) if m else None


def _areas(labels):
    return sorted(lb.removeprefix("area:") for lb in labels if lb.startswith("area:"))


def from_issues(issues):
    """(the steps, the findings, the gaps and questions) from the issues. The steps come in order,
    each with its findings' numbers; a sub-issue of a step is a finding whatever it is titled."""
    steps = {}
    for i in issues:
        m = TITLE.match(i["title"])
        if LABEL in i["labels"] and i["parent"] is None and m and m[3] is None:
            steps[i["number"]] = {
                "id": f"H{m[1]}.{m[2]}", "sweep": int(m[1]), "n": int(m[2]), "issue": i["number"], "what": m[4],
                "areas": _areas(i["labels"]), "pr": _pr(i), "done": i["state"] == "closed", "findings": []}
    found, others = [], []
    for i in issues:
        if i["parent"] in steps:
            step = steps[i["parent"]]
            m = TITLE.match(i["title"])
            sev = SEVERITY.search(i["body"])
            closed = i["state"] == "closed"
            state = (("fixed" if i["reason"] == "completed" else "closed") if closed
                     else "question" if "question" in i["labels"] else "open")
            areas = _areas(i["labels"]) or step["areas"]
            found.append({"id": i["number"], "step": step["id"], "cr": m[5] if m else None,
                          "sev": sev[1].capitalize() if sev else None, "desc": m[4] if m else i["title"],
                          "state": state, "pr": _pr(i), "area": areas[0] if areas else NO_AREA})
            step["findings"].append(i["number"])
        elif i["number"] not in steps and i["state"] == "open":
            kinds = [k for k in ("gap", "question") if k in i["labels"]]
            if kinds:
                others.append({"id": i["number"], "title": i["title"], "kind": kinds[0],
                               "areas": _areas(i["labels"])})
    path = sorted(steps.values(), key=lambda s: (s["sweep"], s["n"]))
    for s in path:
        s["areas"] = s["areas"] or sorted({f["area"] for f in found if f["id"] in s["findings"]})
    return path, found, others


def is_open(f):
    return f["state"] in ("open", "question")


# ---------- the figures ----------


def figures(area_names, found):
    """This push's findings by area, as the history keeps them: open, of them High or Med (severe),
    fixed or closed, and all."""
    out = {a: {"open": 0, "severe": 0, "fixed": 0, "all": 0} for a in area_names}
    for f in found:
        t = out.setdefault(f["area"], {"open": 0, "severe": 0, "fixed": 0, "all": 0})
        t["all"] += 1
        if is_open(f):
            t["open"] += 1
            t["severe"] += f["sev"] in ("High", "Med")
        else:
            t["fixed"] += 1
    return out


def result(step, history):
    """What changed in the step's areas at its pull request's merge: the findings closed and the
    coverage's change, from the history's entries before and at it; None where the history has no
    entry for its merge, or none before."""
    at = next((i for i, h in enumerate(history) if step["pr"] and h.get("pr") == step["pr"]), None)
    if not at:
        return None
    before, after = history[at - 1], history[at]
    out = {}
    for a in step["areas"]:
        h0, h1 = before.get("hardening", {}).get(a, {}), after.get("hardening", {}).get(a, {})
        c0, c1 = before["areas"].get(a, {}), after["areas"].get(a, {})
        out[a] = {"fixed": h1.get("fixed", 0) - h0.get("fixed", 0),
                  "lines": _change(c1.get("lines"), c0.get("lines")),
                  "branches": _change(c1.get("branches"), c0.get("branches"))}
    return out


def _change(now, was):
    return None if now is None or was is None else round(now - was, 1)


# ---------- mutation testing ----------


def _mutate():
    """scripts/mutate.py, which keeps the records and knows what changed since."""
    spec = importlib.util.spec_from_file_location("appkata_mutate_records", Path(__file__).with_name("mutate.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def mutation(root=ROOT, records=None):
    """Each area's mutation testing: its latest record's name and counts, the modules changed since
    it (`changed`) and those it doesn't hold (`new`). An area with modules and no record has its
    record None."""
    m = _mutate()
    records = Path(records) if records else Path(root) / "docs" / "hardening" / "mutation"
    out = {}
    for area, (name, r) in m.latest_records(records).items():
        out[area] = {"record": name, **{k: r.get(k, 0) for k in ("mutants", "killed", "timeout", "survived")},
                     "noTests": r.get("no tests", 0), "changed": [], "new": []}
    for f in m.stale_modules(Path(root), records):
        entry = out.setdefault(f["area"], {"record": None, "changed": [], "new": []})
        entry["changed" if f["state"] == "changed since" else "new"].append(f["module"])
    return out


# ---------- the page ----------


def data(history, area_names, repo, issues, mutated=None):
    """What the page shows: the steps with their results, the areas with their coverage (now, and at
    the first entry the history has), their findings and their mutation testing (`mutation`, read
    from the checkout unless given), and the gaps and questions."""
    path, found, others = from_issues(issues)
    last = history[-1]
    base = history[0] if len(history) > 1 else None
    names = [*area_names, *sorted({f["area"] for f in found} - set(area_names))]
    return {
        "repo": repo,
        "head": {k: last.get(k) for k in ("commit", "pr", "date", "subject")},
        "base": {k: base.get(k) for k in ("commit", "pr", "date")} if base else None,
        "issues": f"{repo}/issues?q=label%3A{LABEL}+no%3Aparent-issue",
        "steps": [{**s, "result": result(s, history) if s["done"] else None} for s in path],
        "findings": [{k: f[k] for k in ("id", "step", "cr", "sev", "desc", "state", "pr", "area")} for f in found],
        "areas": [{"area": a, "now": last["areas"].get(a), "was": base["areas"].get(a) if base else None}
                  for a in names],
        "others": others,
        "mutation": mutation() if mutated is None else mutated,
    }


def page(history, area_names, repo, issues, mutated=None):
    """The page: hardening.html with its data in place."""
    script = json.dumps(data(history, area_names, repo, issues, mutated), separators=(",", ":")).replace("</", "<\\/")
    return PAGE.read_text(encoding="utf-8").replace("/*DATA*/", script)
