"""State transitions leave nothing behind: a snapshot of everything AppKata writes, before and
after each change an app's sandbox can go through (R17.4, R17.11, R17.14).

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

from appkata_core import install
from appkata_core import sandbox as sb
from test_install_review import _appimage, _menu_starts, _tarball, server   # noqa: F401
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
    # the audit table too (R17.16: every sandbox change is recorded; round five's audit category)
    files["<audit>"] = json.dumps([[r["kind"], r["action"], r["subject"]] for r in be.db.all("SELECT kind, action, subject FROM audit ORDER BY id")])
    return files


def diff(before, after):
    keys = set(before) | set(after)
    return {k: (before.get(k), after.get(k)) for k in keys if before.get(k) != after.get(k)}


@pytest.fixture
def sandboxed(be, tmp_path, monkeypatch):
    """An installed, reviewed, sandboxed app with its launcher, marker and desktop entry in place."""
    monkeypatch.setattr(sb, "have_tools", lambda: True)
    # and xdg-dbus-proxy, as the distributions AppKata supports install it with flatpak: the launcher's
    # text, and the state frozen from it, are the same on every host (the RHEL 8 host had none,
    # so tests/data/state/0.1.0.json froze a launcher without the bus filter)
    monkeypatch.setattr(sb, "have_bus_filter", lambda: True)
    monkeypatch.setattr(sb, "support_status", lambda: {"status": "ok"})
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / ".local" / "share"))
    _review(be, "online-app")
    _tarball_install(be, tmp_path)
    be._regenerate_launcher(URL)
    be._pin_sandbox(URL, be._resolved_sandbox(URL))
    return tmp_path


def test_off_and_back_on_leaves_the_tree_and_the_rows_as_they_were(be, sandboxed):
    before = snapshot(be, sandboxed)
    assert any(k.endswith("/run") for k in before) and any(".identity/apps/demo" in k for k in before)
    be.setSandbox(URL, {"template": "off"})
    off = snapshot(be, sandboxed)
    gone = {k for k in before if k not in off}
    assert gone == {k for k in before if k.endswith("/run") or ".identity/apps/demo" in k}, gone     # R4-7: the marker goes with the launcher
    be.setSandbox(URL, None)                                                                   # back to the reviewers' suggestion
    after = snapshot(be, sandboxed)
    changed = diff(before, after)
    assert set(changed) <= {"<settings row>", "<audit>"}, changed       # the files are byte-identical again; the row records "seen", the audit the two changes
    assert be._install_settings(URL).get("sandboxPinned") == json.loads(before["<settings row>"]).get("sandboxPinned")


def test_saving_the_same_sandbox_twice_and_healing_twice_change_nothing(be, sandboxed):
    be.setSandbox(URL, {"template": "messenger", "overrides": {}})
    once = snapshot(be, sandboxed)
    be.setSandbox(URL, {"template": "messenger", "overrides": {}})
    assert set(diff(once, snapshot(be, sandboxed))) == {"<audit>"}        # the same choice again is still a recorded choice (R17.16)
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
    # R17.14: the private home is kept unless asked; nothing else of the app survives (R10). The
    # helpers under sandboxes/.identity/ (the xdg-open shim, the forwarding helper, the seccomp
    # filter) are AppKata's own, shared by every launcher, and stay.
    pristine = {k: v for k, v in snapshot(be, sandboxed).items() if "/apps/demo/" not in k and "/appkata-demo" not in k
                and "/sandboxes/demo" not in k and ".identity/apps/demo" not in k and not k.startswith("<")}
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


@pytest.mark.parametrize("kind", ["appimage", "tarball"])
def test_turning_the_sandbox_off_puts_an_app_that_updates_itself_back_under_its_fixed_name(be, server, tmp_path, monkeypatch, kind):   # noqa: F811
    # CR1.11-41, the owner's decision: R4.10.5 and R17.12 said "Switched to Off, it updates itself
    # again" and nothing of the layout. While it runs sandboxed AppKata updates such an app, and
    # its first update moves it out of R4.10.2's fixed-name layout into version folders; nothing
    # moved it back, so with the sandbox Off again the app's own updater found a versioned file
    # behind a stable link, and kept versions it would never replace. Turning the sandbox Off now
    # moves the current version back to the fixed name and removes the kept versions. The whole
    # road is walked here, by the install and by the backend's own sandbox change: installed Off
    # (fixed), sandboxed (still fixed, with its launcher), updated by AppKata (version folders,
    # the old version kept), and Off again.
    monkeypatch.setattr(sb, "have_tools", lambda: True)
    monkeypatch.setattr(sb, "have_bus_filter", lambda: True)
    monkeypatch.setattr(sb, "support_status", lambda: {"status": "ok"})
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / ".local" / "share"))
    a = {"url": URL, "name": "Demo", "installed": "", "autoUpdate": True, "summary": "", "icon": ""}
    monkeypatch.setattr(be, "_app", lambda url: a)
    home, cmd, entry = tmp_path / "bin" / "apps" / "demo", tmp_path / "bin" / "demo", tmp_path / ".local" / "share" / "applications" / "appkata-demo.desktop"
    fixed = "Demo.AppImage" if kind == "appimage" else "app"

    def update_to(v):
        """What Backend._install does for the app, with the layout and the grant set it would pass."""
        r = (_appimage(server, f"Demo-{v}-x86_64.AppImage", f"#!/bin/sh\necho {v}\n".encode()) if kind == "appimage"
             else _tarball(server, f"demo-{v}.tar.gz", {f"demo-{v}/demo": 0o755}))
        gs = be._sandbox_for_install(URL, kind=kind)
        rec = install.install(be.db, {**a, "installVersion": v, "autoUpdate": be._updates_itself(a, gs), "sandbox": gs}, r, kind, [r],
                              portable=be._app_options(URL))
        a["installed"] = v
        return rec

    def says(path):
        import subprocess
        return subprocess.run([str(path)], capture_output=True, text=True, timeout=30).stdout.strip()

    def record():
        return json.loads(be.db.one("SELECT record FROM installs WHERE url=?", (URL,))["record"])

    be.setSandbox(URL, {"template": "off"})
    rec = update_to("1.0")
    assert rec["selfUpdating"] and sorted(os.listdir(home)) == [fixed] and "1.0" in says(cmd)
    be.setSandbox(URL, {"template": "standard"})                # sandboxed: it can't update itself, and stays where it is
    assert sorted(os.listdir(home)) == [fixed, "run"] and record()["selfUpdating"] and be._updates_itself(a, be._sandbox_for_install(URL)) is False
    rec = update_to("2.0")                                      # AppKata's update: into version folders, 1.0 kept (R17.12)
    assert not rec.get("selfUpdating") and [k["version"] for k in rec["kept"]] == ["1.0"] and rec["exec"] == rec["launcher"] == str(home / "run")
    assert os.path.islink(home / ("Demo.AppImage" if kind == "appimage" else "current")) and len(os.listdir(home)) == 4

    be.setSandbox(URL, {"template": "off"})                     # and Off: it updates itself again (R4.10.5)
    rec = record()
    assert sorted(os.listdir(home)) == [fixed] and not os.path.islink(home / fixed)        # no version folders, kept versions, link or launcher
    assert rec["selfUpdating"] and rec["kept"] == [] and "launcher" not in rec and "sandbox" not in rec
    assert rec["current"] == {"version": "2.0", "path": str(home / fixed), "exec": fixed if kind == "appimage" else "app/demo-2.0/demo"}
    assert rec["exec"] == str(home / rec["current"]["exec"]) and "2.0" in says(rec["exec"]) and "2.0" in says(cmd)
    menu = install._menu_link_path("demo")                     # what the menu entry starts (R4.3.1.1)
    assert os.readlink(cmd) == rec["exec"] == _menu_starts(menu) and f'Exec=/bin/sh "{menu}" %U' in entry.read_text()
    assert be._updates_itself(a, be._sandbox_for_install(URL)) is True and not sb.runs_sandboxed(rec)
    off = snapshot(be, tmp_path)
    be.setSandbox(URL, {"template": "off"})                     # the same choice again changes nothing but the audit
    assert set(diff(off, snapshot(be, tmp_path))) <= {"<audit>"}
    be.setSandbox(URL, {"template": "standard"})                # sandboxed again: still its fixed name, until AppKata's next update
    assert sorted(os.listdir(home)) == [fixed, "run"] and record()["selfUpdating"] and record()["current"] == rec["current"]
    be._uninstall(URL, False, remove_home=True)
    assert not os.path.lexists(home) and not os.path.lexists(cmd) and not entry.exists()
