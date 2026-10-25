"""Every sandbox mutation leaves its audit entry (requirement 17.16), as a table over the slots and
as part of the transitions snapshot (round five, "Coverage after round five").

Round four's R4-3 found a save path that applied a sandbox and wrote no audit row; the transitions
test snapshots the files and the app's two rows but not the audit table, so a path like it could
still go unnoticed. The snapshot here includes the audit rows, and each state-changing slot is
driven once and must add exactly the entry 17.16 names.
"""

import json
import time

import pytest

from appkata_core import sandbox as sb
from test_sandbox_backend import URL, _review, _tarball_install, be   # noqa: F401
from test_sandbox_transitions import sandboxed                          # noqa: F401


def audit_rows(be) -> list[tuple]:
    return [(r["kind"], r["action"], r["subject"]) for r in be.db.all("SELECT kind, action, subject FROM audit ORDER BY id")]


SLOTS = [
    ("setSandbox template", lambda be: be.setSandbox(URL, {"template": "strict", "overrides": {}}), [("app", "set the sandbox of", "Demo")]),
    ("setSandbox custom", lambda be: be.setSandbox(URL, {"custom": sb.to_json(sb.resolve_template("messenger"))}), [("app", "set the sandbox of", "Demo")]),
    ("setSandbox off", lambda be: be.setSandbox(URL, {"template": "off"}), [("app", "set the sandbox of", "Demo")]),
    ("setSandbox back to theirs", lambda be: be.setSandbox(URL, None), [("app", "set the sandbox of", "Demo")]),
    ("keepSandbox", lambda be: be.keepSandbox(URL), [("app", "kept the sandbox of", "Demo")]),
    ("useSuggestion", lambda be: be.useSuggestion(URL), [("app", "set the sandbox of", "Demo")]),      # review 2, F8
    ("install options with a sandbox", lambda be: be.installWith(URL, {"kind": "tarball", "appMenu": True, "install": False,
                                                                       "sandbox": {"template": "offline-editor", "overrides": {}}}),
     [("app", "chose how to install", "Demo"), ("app", "set the sandbox of", "Demo")]),
    ("install options untouched", lambda be: be.installWith(URL, {"kind": "tarball", "appMenu": True, "install": False}),
     [("app", "chose how to install", "Demo")]),
    ("uninstall keeping the home", lambda be: be._uninstall(URL, False, remove_home=False), [("app", "uninstalled", "Demo")]),
]


@pytest.mark.parametrize("name,act,expected", SLOTS, ids=[s[0] for s in SLOTS])
def test_each_sandbox_mutation_writes_exactly_its_audit_entry(be, sandboxed, monkeypatch, name, act, expected):
    monkeypatch.setattr(be, "_install", lambda *a, **k: None)
    before = audit_rows(be)
    act(be)
    added = audit_rows(be)[len(before):]
    assert added == expected, (name, added)


def test_a_sandbox_mutation_that_changes_nothing_still_says_so_once(be, sandboxed):
    before = audit_rows(be)
    be.setSandbox(URL, {"template": "online-app", "overrides": {}})      # what the review already says
    assert len(audit_rows(be)) == len(before) + 1                         # 17.16: every change of the choice, even to the same grants


def test_the_system_setup_is_audited_once_it_really_worked(be, monkeypatch):
    outcomes = iter([sb.SandboxError("the administrator prompt was dismissed"), True])

    def install_profile():
        o = next(outcomes)
        if isinstance(o, Exception):
            raise o
        return o
    monkeypatch.setattr(sb, "install_profile", install_profile)
    monkeypatch.setattr(be, "_heal_launchers", lambda actor="system": [])
    for expected in ([], [("setting", "enabled system sandbox support", "AppArmor")]):
        before = audit_rows(be)
        be.setupSandboxSupport()
        for _ in range(50):
            if audit_rows(be)[len(before):] == expected and expected:
                break
            time.sleep(0.1)
        assert audit_rows(be)[len(before):] == expected


def test_the_transitions_snapshot_now_sees_the_audit_table(be, sandboxed):
    from test_sandbox_transitions import snapshot
    before = snapshot(be, sandboxed)
    assert "<audit>" in before
    be.keepSandbox(URL)
    after = snapshot(be, sandboxed)
    assert json.loads(after["<audit>"]) == json.loads(before["<audit>"]) + [["app", "kept the sandbox of", "Demo"]]
