"""What the documents state as fact -- counts, lists, names, section numbers, a status -- is what
the code says (review 3, E2).

How review 2's nits and D2 slipped past: each was a fact copied into prose (seven templates, four
review rounds, "Planned", "process 2 (or 3)", "(R4.5)") that the code later outgrew. Class F's docs
test (review 2) caught retired identifiers in the documents R17 delegates to; nothing compared a
stated fact with the code that decides it. This harness lists the facts, each with where the
document states it and how the code decides it, and fails when they differ -- or when one listed
as wrong is fixed, so the list shrinks.
"""

import os
import re
import sys

from appkata_core import sandbox as sb, trustfile
import reqdocs
import written
import test_booted as booted
from test_requirements_trace import _finding_exists

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
REQ = "docs/requirements/"                 # every section file, as one text (reqdocs)
A1 = "docs/architecture/A1-app-sandboxing/"  # the sandboxing design's files, as one text
RECORD = "docs/reviews/app-sandboxing-build.md"
COUNTED_DOCS = (REQ, A1, "docs/local-proxy-test-plan.md", "README.md", "DEVELOP.md")
WORDS = {"two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}

# Facts the documents still state wrongly, and the finding that keeps each
STILL_WRONG: dict = {}


def _read(rel):
    if rel == REQ:
        return reqdocs.text()
    if rel == A1:
        return reqdocs.section(1, reqdocs.ARCH)
    with open(written.path(rel), encoding="utf-8") as f:     # the code as written, in a mutation run too
        return f.read()


def _req(rid: str) -> str:
    return reqdocs.item(rid, _read(REQ))


def _labels_to_keys(text: str) -> set:
    by_label = {v.lower(): k for k, v in sb.TEMPLATE_LABELS.items()}
    return {by_label[p.strip().lower()] for p in re.split(r"[·,]", text) if p.strip().lower() in by_label}


def _named(cell: str) -> dict:
    """A "Named elsewhere" cell of A1.2.3.14's table as {where: name}: "R17.5.1 and R17.3: tray; the
    dialog: Tray icon" is {"R17.5.1": "tray", "R17.3": "tray", "dialog": "Tray icon"}."""
    out = {}
    for part in cell.split("; "):
        where, _, name = part.partition(": ")
        out.update({w.removeprefix("the "): name for w in where.split(" and ")})
    return out


def _audit_actions() -> dict:
    """{(kind, action)} the Backend writes, from its _audit calls."""
    # the actor may be a word or a name ("you", actor): a call with a variable actor slipped past (F11)
    return set(re.findall(r'_audit\((?:"[a-z]+"|[a-z_]+), "([a-z]+)", "([^"]+)"', _read("src/appkata/backend.py")))


# each action's words as R13.3 would name it (a new action without an entry here fails the test)
AUDIT_WORDS = {
    "installed": "installed", "updated": "updated", "uninstalled": "uninstalled", "chose how to install": "how to install",
    "pinned": "pinned", "adopted": "adopted", "removed a kept version of": "kept version",
    "set the sandbox of": "sandbox", "kept the sandbox of": "sandbox", "added": "added", "removed": "removed",
    "changed the settings of": "settings changed", "set the Score of": "Score changed", "reviewed": "saved",
    "re-signed the last commit": "re-signed", "set an API token for": "API tokens", "chose the review file": "review file",
    "registered appkata:// links": "appkata://", "imported settings from": "imported", "exported settings to": "exported",
    "enabled system sandbox support": "sandbox support", "removed AppKata's AppArmor profile": "AppArmor",
    "put off system sandbox support": "put off with Not now", "sandboxed": "an app sandboxed by a setup",
    "rewrote the launcher of": "a launcher rewritten at AppKata's start",
}
SANDBOX_ACTIONS = {"set the sandbox of", "kept the sandbox of", "enabled system sandbox support", "removed AppKata's AppArmor profile",
                   "put off system sandbox support", "sandboxed", "rewrote the launcher of"}


def _facts() -> dict:
    """{fact: (what the document states, what the code says)}"""
    f = {}
    m = re.search(r"(\w+) are built in", _req("R17.3"))
    f["R17.3: how many templates are built in"] = (WORDS.get(m.group(1).lower()) if m else None, len(sb.TEMPLATES))
    f["R17.3: the templates in its table"] = (set(re.findall(r"^\| `([a-z-]+)` \|", _req("R17.3"), re.M)), set(sb.TEMPLATE_ORDER))
    row = re.search(r"^\| Sandbox \| a template name \((.*?)\) or `off`", _req("R10.3.1"), re.M)
    f["R10.3.1: the templates a review may name"] = (set(re.findall(r"`([a-z-]+)`", row.group(1))) if row else set(),
                                                    set(trustfile.SANDBOX_TEMPLATES))
    # every option a review's Settings may hold has its row in R10.3.1's table, and no row is of none
    # (CR1.5-36 added one, `Sandbox MPRIS name`; Trust, Rating and Tags are the review's own values)
    options = set(re.findall(r"^\| ([A-Z][A-Za-z ]+?) \|", _req("R10.3.1"), re.M)) - {"Option", "Trust", "Rating", "Tags"}
    f["R10.3.1: the options in its table"] = (options, set(trustfile.SETTINGS_LABELS.values()))
    hint = re.search(r'label: "Built-in templates"\s*hint: "([^"]*)\. Each app', _read("src/appkata/qml/SettingsDialog.qml"))
    f["Settings: the built-in templates row"] = (_labels_to_keys(hint.group(1)) if hint else set(), set(sb.TEMPLATE_ORDER))
    # every count of the templates, wherever a document states one (found fixing review 2: R17.3.4 and
    # the design doc said "seven" after `standard` made eight; this harness checked two sentences)
    for doc in COUNTED_DOCS:
        text = re.sub(r"\s+", " ", _read(doc))
        for m in re.finditer(r"\b(" + "|".join(WORDS) + r") (?:built-in )?templates\b", text, re.I):
            f[f"{doc}: “{text[max(0, m.start() - 30):m.end()].strip()}”"] = (WORDS[m.group(1).lower()], len(sb.TEMPLATES))
    # the design doc's own table of the templates names every built-in one
    table = re.search(r"^\| Template \| Level \|.*?\n((?:\|.*\n)+)", _read(A1), re.M)
    rows = re.findall(r"^\| \*\*([^*]+)\*\* \|", table.group(1), re.M) if table else []
    f["A1: the templates in its table"] = (_labels_to_keys(", ".join(r.split(" / ")[0] for r in rows)), set(sb.TEMPLATES))

    m = re.search(r"allow (.*?) \(and the Request", re.sub(r"\s+", " ", _req("R17.5")))
    f["R17.5: the portal interfaces every app may call"] = (set(re.split(r", | and ", m.group(1))) if m else set(), set(sb.PORTAL_INTERFACES))
    others = {re.search(r"=org\.freedesktop\.(?:portal\.)?([A-Za-z.]+)\.\*@", r).group(1) for r in sb.portal_rules() if r.startswith("--call=")}
    others -= set(sb.PORTAL_INTERFACES) | {"Request", "Session"}
    said = {o for o in others if o.split(".")[-1] in _req("R17.5")}
    f["R17.5: nothing else on the portal's name"] = (said, others)
    caps17 = {"notifications": "notifications", "screensaver inhibit": "inhibit", "tray": "tray", "media keys": "mpris", "secrets": "secrets"}
    bold = {b.lower() for b in re.findall(r"\*\*([^*]+)\*\*", _req("R17.5.1"))}
    f["R17.5.1: the capabilities"] = ({caps17[b] for b in bold if b in caps17}, set(sb.CAP_PROXY_ARGS) - {"secrets-provide"})
    plan = _read(A1)
    rows = dict(re.findall(r"^\| ([A-Z][^|]+?) \| (.+?) \|", plan[plan.index("### A1.2.3.14. Capability → proxy arguments"):], re.M))
    stated = {k for k, lab in sb.CAP_LABELS.items() if lab in rows and all(a.split("=", 1)[-1].split("@")[0].split(".")[-1].rstrip("*").rstrip(".")
                                                                           in rows[lab] for a in sb.CAP_PROXY_ARGS[k][:1])}
    f["A1.2.3.14: the capability table"] = (stated, set(sb.CAP_LABELS))
    # ...and the one table of each capability's names (CR1.11-80: the requirement, the template table,
    # the review lines and the dialog each had their own, and only the code held the mapping): its
    # word in a review, then what R17.5.1, R17.3's table, the dialog's switch and the summary's chip call it
    table = plan[plan.index("### A1.2.3.14. Capability → proxy arguments"):]
    cells = {r[0]: r for r in (tuple(c.strip() for c in line.strip("|").split(" | ")) for line in table.splitlines() if line.startswith("| "))
             if len(r) == 5}
    names = {k: _named(cells[lab][3]) for k, lab in sb.CAP_LABELS.items() if lab in cells}
    word = {k: m.group(1) for k, lab in sb.CAP_LABELS.items() if lab in cells and (m := re.match(r"`([a-z-]+)`", cells[lab][2]))}
    f["A1.2.3.14: each capability's word in a review"] = (word, sb.LINE_WORDS["caps"])
    switch = {k: re.sub(r" \(chip: .*\)$", "", n.get("dialog", "")) for k, n in names.items()}
    qml = _read("src/appkata/qml/SandboxDialog.qml")
    f["A1.2.3.14: each capability's switch in the dialog"] = (
        switch, {k: lab for lab, k in re.findall(r'SbxToggle \{ label: "([^"]+)"; ic: "[a-z]+";(?: warn: true;)? on: root\.has\(root\.gs\.caps, "([a-z-]+)"\)', qml)})
    chip = {k: (m.group(1) if (m := re.search(r"\(chip: (.*)\)$", n.get("dialog", ""))) else switch[k]) for k, n in names.items()}
    f["A1.2.3.14: each capability's chip in the summary"] = (chip, {k: v[0] for k, v in sb._CAP_CHIP.items()})
    f["A1.2.3.14: the names R17.5.1 gives the capabilities"] = ({n.get("R17.5.1", "").split(",")[0] for n in names.values()}, bold & set(caps17))
    services = {m.group(1): {w for w in m.group(2).split(", ") if w != "—"}
                for m in re.finditer(r"^\| `([a-z-]+)` \|(?:[^|]*\|){5} ([^|]+) \|", _req("R17.3"), re.M)}
    f["A1.2.3.14: the words of R17.3's table"] = ({t: {names.get(c, {}).get("R17.3") for c in sb.TEMPLATES[t]["caps"]} for t in sb.TEMPLATES}, services)
    f["A1.2.3.14: the names R17.3.1 gives the keyring's two"] = (
        {k: n["R17.3.1"] for k, n in names.items() if "R17.3.1" in n and n["R17.3.1"] in re.sub(r"\s+", " ", _req("R17.3.1"))},
        {"secrets": "saved passwords", "secrets-provide": "the password service"})
    f["R17.5.1: where the capabilities' names are"] = ("review" in re.sub(r"\s+", " ", _req("R17.5.1")).split("The full mapping table is A1.2.3.14")[-1], True)
    text = re.sub(r"\s+", " ", _req("R17.17"))
    old = re.search(r"process (\d+) \(or (\d+)\)", text)                # the wording review 2 found
    new = re.search(r"processes (\d+) to (\d+)", text)
    pids = ({int(old.group(1)), int(old.group(2))} if old else set(range(int(new.group(1)), int(new.group(2)) + 1)) if new else set())
    f["R17.17: the tray item's process ids"] = (pids,
                                               {int(re.search(r"-(\d+)-\d+$", o).group(1)) for o in sb._TRAY_OWNS})
    order = [tuple(int(x) for x in n.split(".")) for n in re.findall(r"^R(17\.[\d.]*\d)\. ", _read(REQ), re.M)]
    f["17: its sub-sections in order"] = (order, sorted(order))
    uninst = re.search(r"^(R\d+\.\d+)\. \*\*Uninstalling\*\*", _read(REQ), re.M).group(1)
    ref = re.search(r"like any app data \((R\d+\.\d+)\)", _req("R17.14"))
    f["R17.14: where uninstalling is"] = ({ref.group(1)} if ref else set(), {uninst})
    groups = {t.lower() for t in re.findall(r"^R11\.1\.\d+\. \*\*([^*]+)\*\*", _read(REQ), re.M)}
    f["R11.1: the Settings groups"] = (groups, {t.lower() for t in re.findall(r'Section \{[^}]*text: "([A-Z ]+)"', _read("src/appkata/qml/SettingsDialog.qml"))})
    # a fixed path (review 2's nit: "on /usr/bin/bwrap"), or the bwrap it names; profile_text() names the one installed
    fixed = re.search(r"userns`? on `?/usr/bin/bwrap", _req("R17.10.1")) is not None
    f["R17.10.1: the bwrap the profile names"] = ("a fixed path" if fixed else "the one installed",
                                                 "the one installed" if "/opt/x/bwrap" in sb.profile_text("/opt/x/bwrap") else "a fixed path")
    f["R4.3.1.2: what a sandboxed app's entries point at"] = (bool(re.search(r"17\.4|/run\b", _req("R4.3.1.2"))), True)

    audit = _req("R13.3")
    actions = _audit_actions()
    unnamed = {a for _, a in actions if a not in AUDIT_WORDS}
    assert not unnamed, f"Audit actions with no words for R13.3 yet: {sorted(unnamed)}"
    told = {a for _, a in actions if AUDIT_WORDS[a].lower() in audit.lower()}
    f["R13.3: the sandbox entries the Audit records"] = (told & SANDBOX_ACTIONS, {a for _, a in actions} & SANDBOX_ACTIONS)
    f["R13.3: the other entries the Audit records"] = (told - SANDBOX_ACTIONS, {a for _, a in actions} - SANDBOX_ACTIONS)

    # one Python and one PySide6 for every release, the development and the tests (R1.2, review 3 R3-21)
    env = _read("packaging/versions.env")
    series, pyside = re.search(r"PY_SERIES:=([\d.]+)", env).group(1), re.search(r"PYSIDE:=([\d.]+)", env).group(1)
    floor = re.search(r'requires-python = ">=([\d.]+)"', _read("pyproject.toml"))
    f["pyproject: the Python AppKata requires"] = (floor.group(1) if floor else None, series)
    pinned = {rel: sorted(set(re.findall(r"pywine:(3\.\d+)|cpython-3\\?\.(\d+)|PY_SERIES=\$\{PY_SERIES:-([\d.]+)|PYSIDE=\$?\{?PYSIDE:-([\d.]+)|PYSIDE=([\d.]+)", _read(rel))))
              for rel in ("scripts/build-appimage.sh", "scripts/build-windows.sh", "scripts/test-windows-vm.sh")}
    f["the build scripts: a Python or PySide6 of their own"] = ({r: v for r, v in pinned.items() if v}, {})

    # R1.6: the AppImage is AppKata's only Linux form (R3-21's decision); README and build.md still said
    # ".deb/.rpm maybe later" after R1.6 dropped it
    only = "no `.deb` or `.rpm`" in re.sub(r"\s+", " ", _req("R1.6"))
    maybe = sorted(rel for rel in ("README.md", "DEVELOP.md", "docs/build.md")
                   if re.search(r"\.deb.{0,40}\bmaybe\b|\bmaybe\b.{0,40}\.rpm", re.sub(r"\s+", " ", _read(rel)), re.I))
    f["README and build.md: a .deb or .rpm of AppKata"] = (maybe, [] if only else None)

    # Windows 10's one release, 22H2 (R1.1): where the documents name it, and Setup's MinVersion, which
    # a user meets (R1.1 and R15.1 said 1809 and build.md "Windows 10+" after the owner's target was 22H2)
    build = re.search(r"^MinVersion=10\.0\.(\d+)", _read("packaging/windows/appkata.iss"), re.M)
    releases = {"17763": "1809", "18363": "1909", "19041": "2004", "19042": "20H2", "19043": "21H1", "19044": "21H2",
                "19045": "22H2"}
    row = re.search(r"^\| (Windows 10[^|]*)\|", _read("docs/build.md"), re.M)
    named = {where: (m.group(1) if (m := re.search(r"Windows 10 \(?(\w+)", text or "")) else None)
             for where, text in (("1.1", _req("R1.1")), ("15.1", _req("R15.1")), ("15.10", _req("R15.10")),
                                 ("build.md's platform table", row and row.group(1)))}
    f["the Windows 10 release the documents name, and Setup's"] = (named, dict.fromkeys(named, releases.get(build.group(1)) if build else None))
    readme = next((l for l in _read("DEVELOP.md").splitlines() if l.startswith("| App sandboxing")), "")
    f["DEVELOP.md: sandboxing's status"] = ("Planned" if "| Planned" in readme else "implemented", "implemented")
    doc = _read(A1)
    f["A1: its title's status"] = ("planning" if "planning" in doc.splitlines()[0] else "implemented", "implemented")
    # round one has no "Round" heading of its own: it is the file's first part
    rounds = 1 + len(re.findall(r"^## Round \w+", _read("docs/reviews/app-sandboxing-1.md"), re.M))
    m = re.search(r"taken through (\w+) review rounds", _read(RECORD))
    f["A1: how many review rounds"] = (WORDS.get(m.group(1).lower()) if m else None, rounds)
    # what a system boots with, against docs/testing.md's table, which each VM checks (E10, R3-37):
    # every place that names where the AppArmor setup is needed, or where the namespaces are
    # restricted, may name only systems the table says so of; every kernel named, the table's
    for where, rel, pattern, truth in BOOTED_CLAIMS:
        for i, m in enumerate(re.finditer(pattern, _read(rel), re.M)):
            named = sorted({booted.series(s) for s in re.findall(DISTRO, m.group(1))})
            f[f"{rel}, {where}" + (f" ({i + 1})" if i else "")] = (named, sorted(set(named) & truth()))
    for i, m in enumerate(re.finditer(r"(Mint \d+|Ubuntu \d\d\.\d\d)'s (\d+\.\d+) kernel", _read(A1))):
        f[f"A1: {m.group(1)}'s kernel ({i + 1})"] = (m.group(2), booted.kernels().get(booted.series(m.group(1))))
    return f


# a system as the documents name one: "Ubuntu 24.04 (LTS)", "(Linux) Mint 22(.3)", "LMDE 7", a bare "24.04"
DISTRO = r"(?:Linux )?Mint \d+(?:\.\d+)?|LMDE \d+|Ubuntu \d\d\.\d\d(?: LTS)?|(?<![\d.])2[2-9]\.(?:04|10)(?![\d.])"

# (where, document, a pattern whose group is where the place names its systems, if it names any,
# the systems the table says it of). Since R3-37's fix most places state the condition and name
# none; a place that names one again is held to the table.
BOOTED_CLAIMS = (
    ("R17.10's heading: where the setup is needed", REQ, r"R17\.10\. \*\*AppArmor setup \(([^)]*)\)", booted.needs_setup),
    ("R17.10.2: a machine where the setup ran", REQ, r"— (an? [^—]*?machine where the setup ran)", booted.needs_setup),
    ("the Approach: where the privileged step is", A1, r"One privileged step (.+?) \(found", booted.needs_setup),
    ("bubblewrap: where the privileged requirement is", A1, r"\*\*One privileged requirement, ([^*]+)\.\*\*", booted.needs_setup),
    ("the Limits: where AppArmor is needed", A1, r"^- \*\*AppArmor ([^*]+)\.\*\*", booted.needs_setup),
    ("the claims table: who restricts", A1, r"^\| (.+?) restricts? unprivileged user namespaces through AppArmor", booted.restricted),
    ("A1-prompt: where it's asked", "docs/local-proxy-test-plan.md", r"\*\*A1-prompt\.\*\* (.+?), before the setup", booted.needs_setup),
    ("A1-pkexec: where it's asked", "docs/local-proxy-test-plan.md", r"\*\*A1-pkexec\.\*\* (.+?), Settings", booted.needs_setup),
    ("the field test's A1-pkexec question", "scripts/sandbox/fieldtest.py", r'"A1-pkexec", "([^"]+)"', booted.needs_setup),
    ("its docstring: where the pkexec setup is", "src/appkata_core/sandbox.py", r"one-time pkexec setup ([^()]+?) \(R17\.10\)", booted.needs_setup),
)


def test_every_fact_the_documents_state_is_what_the_code_says_but_the_listed():
    facts = _facts()
    wrong = {name for name, (stated, true) in facts.items() if stated != true}
    report = "\n".join(f"  {n}: the document says {facts[n][0]!r}, the code {facts[n][1]!r}" for n in sorted(wrong - set(STILL_WRONG)))
    assert wrong - set(STILL_WRONG) == set(), "facts the documents state wrongly:\n" + report
    assert set(STILL_WRONG) - wrong == set(), f"now right (drop them from the list): {sorted(set(STILL_WRONG) - wrong)}"


def test_a_booted_claim_naming_a_system_the_table_does_not_is_caught(monkeypatch):
    # R3-37's own shape, put back into R17.10's heading
    real = _read
    monkeypatch.setattr(sys.modules[__name__], "_read", lambda rel: real(rel).replace(
        "AppArmor setup (where the kernel", "AppArmor setup (Ubuntu 24.04 / Mint 22; where the kernel") if rel == REQ else real(rel))
    stated, true = _facts()[f"{REQ}, R17.10's heading: where the setup is needed"]
    assert (stated, true) == (["Mint 22", "Ubuntu 24.04"], ["Ubuntu 24.04"])


def test_each_place_a_booted_claim_reads_is_still_there():
    # a reworded sentence its pattern no longer finds would leave the place unchecked
    for where, rel, pattern, _ in BOOTED_CLAIMS:
        assert re.search(pattern, _read(rel), re.M), (rel, where)


def test_each_wrong_fact_names_a_finding_that_exists():
    review2 = _read("docs/reviews/app-sandboxing-2.md")
    for name, fid in STILL_WRONG.items():
        assert _finding_exists(fid) or (fid == "R2-nits" and "### Smaller mismatches (nits)" in review2), (name, fid)


def test_the_harness_catches_a_template_added_without_the_documents(monkeypatch):
    # the nits' own origin: `standard` joined the code and no document's count or list followed
    monkeypatch.setitem(sb.TEMPLATES, "kiosk", dict(sb.TEMPLATES["strict"]))
    facts = _facts()
    assert facts["R17.3: how many templates are built in"][1] == len(sb.TEMPLATES)
    assert facts["R17.3: how many templates are built in"][0] != facts["R17.3: how many templates are built in"][1]
    # ...and every other count of them, wherever it is written, and the design doc's table
    counts = {k: v for k, v in facts.items() if "templates”" in k}
    assert counts and all(stated != true for stated, true in counts.values()), counts
    assert facts["A1: the templates in its table"][0] != facts["A1: the templates in its table"][1]


def test_the_harness_catches_setup_and_the_documents_naming_different_windows_10s(monkeypatch):
    # Setup's MinVersion moved alone: every document's release now differs from it
    real = _read
    monkeypatch.setitem(globals(), "_read", lambda rel: real(rel).replace("MinVersion=10.0.19045", "MinVersion=10.0.17763"))
    named, setup = _facts()["the Windows 10 release the documents name, and Setup's"]
    assert set(setup.values()) == {"1809"} and set(named.values()) == {"22H2"}, (named, setup)


def test_the_documented_dev_setup_installs_the_releases_pyside6():
    """The documents' `pip install -e .` pins PySide6 to versions.env's PYSIDE: without the pin, pip took
    the newest (6.12.0 while the release carried 6.11.2, 2026-11-07), so tests ran on a PySide6 no
    release carried. pyproject.toml's range is what AppKata runs on, not what the release ships."""
    for doc in ("DEVELOP.md", "docs/build.md"):
        with open(os.path.join(ROOT, doc), encoding="utf-8") as f:
            installs = [line for line in f if re.search(r"pip install .*-e \.", line)]
        assert installs, doc
        for line in installs:
            assert '"PySide6-Essentials==$PYSIDE"' in line and '"shiboken6==$PYSIDE"' in line and "versions.env" in line, (doc, line)
