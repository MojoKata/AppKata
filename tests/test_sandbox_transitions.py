"""State transitions leave nothing behind: a snapshot of everything AppKata writes, before and
after each change an app's sandbox can go through (requirement 17.4, 17.11, 17.14).

Two findings were leftovers of a transition (round two's R10: the identity marker after an
uninstall that kept the home; round four's R4-7: the same marker after a switch to Off), and one
was a transition that changed what it should not have (round two's R1: an options re-save
dropping the pin). A snapshot -- every file under the test home, by content, plus the app's two
database rows -- taken before and after makes every leftover and every unintended change a
failing diff, for all transitions at once rather than the one a finding named.
"""

import hashlib
import json
import os

import pytest

from appkata_core import sandbox as sb
from test_sandbox_backend import URL, _review, _tarball_install, be   # noqa: F401

SKIP = ("appkata.db", "appkata.db-journal", "appkata.db-wal", "appkata.db-shm", ".log", "AppKata.log")


def snapshot(be, root):
    """{path: content hash | link target} for every file under `root` (the database and logs
    aside), plus the app's settings row and install record."""
    files = {}
    for d, dirs, names in os.walk(root):
        for n in names:
            p = os.path.join(d, n)
            if any(p.endswith(s) for s in SKIP):
                continue
            rel = os.path.relpath(p, root)
            if os.path.islink(p):
                files[rel] = "-> " + os.readlink(p)
            else:
                with open(p, "rb") as f:
                    files[rel] = hashlib.sha256(f.read()).hexdigest()[:16]
    row = be.db.one("SELECT record FROM installs WHERE url=?", (URL,))
    files["<install record>"] = json.dumps(json.loads(row["record"]) if row else None, sort_keys=True)
    files["<settings row>"] = json.dumps(be._install_settings(URL), sort_keys=True)
    # the audit table too (17.16: every sandbox change is recorded; round five's audit category)
    files["<audit>"] = json.dumps([[r["kind"], r["action"], r["subject"]] for r in be.db.all("SELECT kind, action, subject FROM audit ORDER BY id")])
    return files


def diff(before, after):
    keys = set(before) | set(after)
    return {k: (before.get(k), after.get(k)) for k in keys if before.get(k) != after.get(k)}


@pytest.fixture
def sandboxed(be, tmp_path, monkeypatch):
    """An installed, reviewed, sandboxed app with its launcher, marker and desktop entry in place."""
    monkeypatch.setattr(sb, "have_tools", lambda: True)
    monkeypatch.setattr(sb, "support_status", lambda: {"status": "ok"})
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / ".local" / "share"))
    _review(be, "online-app")
    _tarball_install(be, tmp_path)
    be._regenerate_launcher(URL)
    be._pin_sandbox(URL, be._resolved_sandbox(URL))
    return tmp_path


def test_off_and_back_on_leaves_the_tree_and_the_rows_as_they_were(be, sandboxed):
    before = snapshot(be, sandboxed)
    assert any(k.endswith("/run") for k in before) and any(".identity/demo" in k for k in before)
    be.setSandbox(URL, {"template": "off"})
    off = snapshot(be, sandboxed)
    gone = {k for k in before if k not in off}
    assert gone == {k for k in before if k.endswith("/run") or ".identity/demo" in k}, gone     # R4-7: the marker goes with the launcher
    be.setSandbox(URL, None)                                                                   # back to the reviewers' suggestion
    after = snapshot(be, sandboxed)
    changed = diff(before, after)
    assert set(changed) <= {"<settings row>", "<audit>"}, changed       # the files are byte-identical again; the row records "seen", the audit the two changes
    assert be._install_settings(URL).get("sandboxPinned") == json.loads(before["<settings row>"]).get("sandboxPinned")


def test_saving_the_same_sandbox_twice_and_healing_twice_change_nothing(be, sandboxed):
    be.setSandbox(URL, {"template": "messenger", "overrides": {}})
    once = snapshot(be, sandboxed)
    be.setSandbox(URL, {"template": "messenger", "overrides": {}})
    assert set(diff(once, snapshot(be, sandboxed))) == {"<audit>"}        # the same choice again is still a recorded choice (17.16)
    twice = snapshot(be, sandboxed)
    assert be._heal_launchers() == []
    assert diff(twice, snapshot(be, sandboxed)) == {}


def test_resaving_install_options_untouched_changes_only_the_dialogs_own_keys(be, sandboxed, monkeypatch):
    # round two, R1
    monkeypatch.setattr(be, "_install", lambda *a, **k: None)
    _review(be, "messenger")
    be.keepSandbox(URL)
    before = snapshot(be, sandboxed)
    be.installWith(URL, {"kind": "tarball", "appMenu": False, "install": False})
    changed = diff(before, snapshot(be, sandboxed))
    assert set(changed) == {"<settings row>", "<audit>"}, changed      # the dialog's keys, and "chose how to install"
    b, a = (json.loads(x) for x in changed["<settings row>"])
    assert {k for k in set(a) | set(b) if a.get(k) != b.get(k)} <= set(be._PORTABLE_KEYS)


@pytest.mark.parametrize("remove_home", [False, True])
def test_uninstall_leaves_only_what_it_promises_to_keep(be, sandboxed, remove_home):
    # 17.14: the private home is kept unless asked; nothing else of the app survives (R10). The
    # helpers under sandboxes/.identity/ (the xdg-open shim, the forwarding helper, the seccomp
    # filter) are AppKata's own, shared by every launcher, and stay.
    pristine = {k: v for k, v in snapshot(be, sandboxed).items() if "/apps/demo/" not in k and "/appkata-demo" not in k
                and "/sandboxes/demo" not in k and ".identity/demo" not in k and not k.startswith("<")}
    home = os.path.relpath(sb.sandbox_home("demo"), sandboxed)
    os.makedirs(sb.sandbox_home("demo"), exist_ok=True)
    with open(os.path.join(sb.sandbox_home("demo"), "settings.ini"), "w") as f:      # the app's data, from a run
        f.write("[app]\n")
    be._uninstall(URL, False, remove_home=remove_home)
    after = snapshot(be, sandboxed)
    leftovers = {k for k in after if not k.startswith("<") and k not in pristine}
    assert all(k.startswith(home + os.sep) for k in leftovers), leftovers
    assert bool(leftovers) is not remove_home
    assert json.loads(after["<install record>"]) is None and "sandboxPinned" not in json.loads(after["<settings row>"])
