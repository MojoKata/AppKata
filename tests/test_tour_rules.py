"""What no screen may show: two parts of the app that tell one fact agree, under each state the tour
stages and each state a launcher can be in (review 3, R3-27; the tour checks tour.RULES on every
screen it takes).

How R3-27 slipped past: whether an app runs sandboxed is read in two places. App Detail asks
whether the launcher file is there; the Apps list's 17.12 rule (an app that would update itself is
updated by AppKata while it runs sandboxed) asks whether the install record names one. The tour
stages "a working system, healed" by forcing App Detail's answer, and the Apps list kept reading
the demo's records, which name no launcher, so A09 showed Syncthing both sandboxed and updating
itself. Harness 4 (one fact, one function) compares the product's deciders and never saw the
tour's staging; E4 checks what screenshots/README.md promises, and A09's promise held. The class:
a state staged, or reached, through one reader of a fact and not the others, so a screen
contradicts itself.

Here a self-updating tarball app goes through every state the tour stages ("ok", "x11", "setup",
none) crossed with the launcher's (none, there, named but gone) and the user's Off, and the rules
are checked as the tour checks them: on the Apps list's row and App Detail's sandboxInfo.
"""

import json
import threading

import pytest

pytest.importorskip("PySide6")

from appkata_core import sandbox as sb                                       # noqa: E402
from appkata_core.db import now                                             # noqa: E402
from test_sandbox_backend import URL, _review_lines, _tarball_install, be   # noqa: E402,F401

# Each case: (the tour's sandbox state, the user's sandbox choice, the launcher)
CASES = {
    "no launcher": ("", None, None),
    "a launcher": ("", None, "there"),
    "a launcher named, its file gone": ("", None, "gone"),
    "the user's Off": ("", "off", None),
    "the tour's working system": ("ok", None, None),
    "the tour's working system, the user's Off": ("ok", "off", None),
    "the tour's X11 session": ("x11", None, None),
    "the tour's setup needed": ("setup", None, None),
}
# Contradictions still open, as "case: App: rule", and the finding that keeps each
STILL_CONTRADICTS: dict = {}


def _staged(be, tmp_path, monkeypatch, mode, choice, launcher):
    """The Demo tarball app, in the catalog for real, updating itself (a review says so), on a host
    that can sandbox, in one case's state."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / ".local" / "share"))
    host = {"status": "setup-needed" if mode == "setup" else "ok"}
    monkeypatch.setattr(sb, "have_tools", lambda: True)
    monkeypatch.setattr(sb, "support_status", lambda: dict(host))
    monkeypatch.setattr(threading.Thread, "start", lambda self: self.run())
    _review_lines(be, "- Auto update: yes\n- Sandbox (linux): online-app\n")
    be.db.x("UPDATE trusts SET verified_commit='e9ee159'")             # its reviews count in the catalog (10.5)
    be.db.x("INSERT INTO sources(url, settings, added_at) VALUES(?,?,?)", (URL, "{}", now()))
    be.db.x("INSERT INTO apps(url, name, releases) VALUES(?,?,?)", (URL, "Demo", json.dumps(
        [{"tag": "v1.0", "name": "1.0", "version": "1.0", "date": "2026-01-01T00:00:00Z", "prerelease": False, "notes": "",
          "html_url": URL + "/releases/v1.0", "assets": [{"name": "demo-1.0-linux-x86_64.tar.gz", "url": "u", "size": 1,
                                                         "digest": "", "content_type": ""}]}])))
    _tarball_install(be, tmp_path)
    del be._app                                                       # the real lookup, through the catalog
    be._sandbox_kind = lambda url: "tarball"
    if launcher:
        lp = tmp_path / "launcher.sh"
        if launcher == "there":
            lp.write_text("#!/bin/sh\n")
        rec = json.loads(be.db.one("SELECT record FROM installs WHERE url=?", (URL,))["record"])
        be.db.x("UPDATE installs SET record=? WHERE url=?", (json.dumps({**rec, "launcher": str(lp)}), URL))
    if choice:
        be.db.x("INSERT INTO app_settings(url, install) VALUES(?,?)", (URL, json.dumps({"sandbox": {"template": choice}})))
    be.reload()
    be.demoSandbox(mode)


@pytest.mark.parametrize("case", list(CASES))
def test_no_screen_contradicts_itself(be, tmp_path, monkeypatch, case):
    from appkata import tour
    _staged(be, tmp_path, monkeypatch, *CASES[case])
    assert be._app(URL)["autoUpdate"] is True                         # the case is the one that matters: 17.12 applies
    seen = {f"{case}: {c}" for c in tour.contradictions(be)}
    listed = {c for c in STILL_CONTRADICTS if c.startswith(case + ": ")}
    assert seen - listed == set(), "new"
    assert listed - seen == set(), "fixed: take it off STILL_CONTRADICTS"


def test_each_listed_contradiction_names_a_case_a_rule_and_its_finding():
    from appkata import tour
    from test_requirements_trace import _finding_exists
    for c, finding in STILL_CONTRADICTS.items():
        case, _, rest = c.partition(": ")
        assert case in CASES, c
        assert any(rest.endswith(": " + text) for text, _ in tour.RULES), c
        assert _finding_exists(finding), c


def test_the_tour_stages_the_sandbox_only_through_the_deciders():
    """The tour's sandbox state is read only where the facts every screen shows are decided: the
    session warning, the support status and whether an app runs sandboxed. A state forced on one
    reader of a fact, and not the others, is R3-27's class: App Detail's "runs sandboxed" was
    forced in sandboxInfo itself, and in the empty-home warning beside it."""
    import ast
    import os
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src", "appkata", "backend.py")
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read())
    readers = set()
    for fn in ast.walk(tree):
        if isinstance(fn, ast.FunctionDef):
            for node in ast.walk(fn):
                if (isinstance(node, ast.Constant) and node.value == "_demo_sandbox"
                        or isinstance(node, ast.Attribute) and node.attr == "_demo_sandbox"):
                    readers.add(fn.name)
    assert readers == {"_sb_session_warning", "_sb_support", "_runs_sandboxed", "demoSandbox"}


def test_every_setting_a_tour_step_makes_is_read():
    """Each key a tour step sets is read by Main.qml's tour hooks (review 3, R3-28: U02's
    auditFilter was read nowhere, so the real U02 showed U01 again). The tour checks the same as it
    runs, where a key read only under another (a review's settings, under `review`) counts too."""
    import os
    import re
    from appkata import tour
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src", "appkata", "qml", "Main.qml")
    with open(path, encoding="utf-8") as f:
        qml = f.read()
    hooks = qml[qml.index("function tour(step)"):qml.index("function tourSignerHover")]
    read = set(re.findall(r"\bstep\.(\w+)", hooks)) | {f"reviewSet.{k}" for k in re.findall(r"\bs\.(\w+)", hooks)}
    unread = {f"{n}: {k}" for n, st, _ in tour.STEPS for k in tour.step_keys(st) if k not in read}
    assert unread == set(tour.STILL_UNREAD)
