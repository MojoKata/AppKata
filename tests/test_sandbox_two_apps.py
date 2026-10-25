"""Two installed apps at once (round six, R6-1 and the "two apps" class).

Every other test installs one app. Two Sources can each carry an app with the same name, and the
user can install both; everything about an install was keyed on the name's slug, so the two shared
one folder, one launcher, one desktop entry, one bus identity and one private home, and
uninstalling either took the other's launcher, marker and home with it.
"""

import json
import os
import subprocess

import pytest

from appkata_core import install, sandbox as sb
from appkata_core.db import now
from test_sandbox_backend import be   # noqa: F401
from test_sandbox_transitions import snapshot

A, B = "https://github.com/alice/notes", "https://codeberg.org/bob/notes"


@pytest.fixture
def two(be, tmp_path, monkeypatch):
    """Two 'Notes' from two Sources, installed through install() itself (no download: the archive
    step is bypassed by handing it an already placed version), A chosen Strict and B Online app."""
    monkeypatch.setattr(sb, "have_tools", lambda: True)
    monkeypatch.setattr(sb, "support_status", lambda: {"status": "ok"})
    monkeypatch.setattr(sb, "have_bus_filter", lambda: True)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / ".local" / "share"))
    apps = {A: {"url": A, "name": "Notes", "installed": "1.0"}, B: {"url": B, "name": "Notes", "installed": "2.0"}}
    be._app = lambda url: apps.get(url)
    be._is_cli = lambda url, eff=None: False
    be._sandbox_kind = lambda url: "tarball"
    root = tmp_path / "bin" / "apps"
    for url, ver in ((A, "1.0"), (B, "2.0")):
        app_id = install.new_app_id(be.db, url, "Notes") if hasattr(install, "new_app_id") else install.slug("Notes")   # the old code: one slug
        target = root / app_id
        (target / ver / "bin").mkdir(parents=True)
        exe = target / ver / "bin" / "notes"
        exe.write_text(f"#!/bin/sh\necho I am {url}\n")
        exe.chmod(0o755)
        rec = {"id": app_id, "current": {"version": ver, "path": str(target / ver), "exec": f"{ver}/bin/notes"},
               "target": str(target), "links": [], "files": []}
        be.db.x("INSERT OR REPLACE INTO installs(url, name, version, kind, record, installed_at) VALUES(?,?,?,?,?,?)",
                (url, "Notes", ver, "tarball", json.dumps(rec), now()))
    be.setSandbox(A, {"template": "strict", "overrides": {}})
    be.setSandbox(B, {"template": "online-app", "overrides": {}})
    return tmp_path


def _rec(be, url):
    return json.loads(be.db.one("SELECT record FROM installs WHERE url=?", (url,))["record"])


def test_two_apps_with_one_name_get_their_own_folder_launcher_identity_and_home(be, two):
    ra, rb = _rec(be, A), _rec(be, B)
    assert ra["id"] == "notes" and rb["id"] == "notes-2"
    assert ra["launcher"] != rb["launcher"] and all(os.path.exists(r["launcher"]) for r in (ra, rb))
    ta, tb = open(ra["launcher"]).read(), open(rb["launcher"]).read()
    assert "xdg-dbus-proxy" not in ta and "appdir=" + sb.shlex.quote(ra["current"]["path"]) in ta       # A: Strict, A's program
    assert "xdg-dbus-proxy" in tb and "appdir=" + sb.shlex.quote(rb["current"]["path"]) in tb           # B: Online app, B's program
    assert "--own=io.appkata.notes " in ta.replace("\\\n", " ") or "--own=io.appkata.notes" not in ta   # Strict has no proxy
    assert "--own=io.appkata.notes-2" in tb
    assert sb.sandbox_home("notes") != sb.sandbox_home("notes-2")
    assert os.path.exists(sb.identity_path("notes")) and os.path.exists(sb.identity_path("notes-2"))
    entries = sorted(f for f in os.listdir(two / ".local" / "share" / "applications") if f.startswith("appkata-"))
    assert entries == ["appkata-notes-2.desktop", "appkata-notes.desktop"]
    assert be.sandboxInfo(A)["home"].endswith("/notes") and be.sandboxInfo(B)["home"].endswith("/notes-2")
    assert be.sandboxInfo(A)["level"] == "strict" and be.sandboxInfo(B)["level"] == "standard"


def test_uninstalling_one_of_two_same_named_apps_leaves_the_other_whole(be, two):
    before = snapshot(be, two)
    ra = _rec(be, A)
    be._uninstall(B, False, remove_home=True)
    assert be.db.one("SELECT 1 FROM installs WHERE url=?", (A,)) and not be.db.one("SELECT 1 FROM installs WHERE url=?", (B,))
    assert os.path.exists(ra["launcher"]) and os.path.exists(sb.identity_path("notes"))
    assert not os.path.exists(sb.identity_path("notes-2")) and not os.path.exists(sb.sandbox_home("notes-2"))
    after = snapshot(be, two)
    gone = {k for k in before if k not in after and not k.startswith("<")}
    assert gone and all("notes-2" in k for k in gone), gone                  # only B's things went
    assert be._heal_launchers() == []                                        # A's launcher is still today's text


C = "https://git.example.org/mallory/notes"


def test_a_later_app_with_the_same_name_never_inherits_a_kept_private_home(be, two):
    # Review 2, F19: R6-1 made ids unique among *installed* apps, but uninstalling keeps the private
    # home by default (17.14), and new_app_id() looked only at the installs table: the next "Notes",
    # from another Source, got the freed id -- and with it the first app's home, accounts and tokens.
    home_a = sb.sandbox_home("notes")
    os.makedirs(os.path.join(home_a, ".config", "notes"), exist_ok=True)
    with open(os.path.join(home_a, ".config", "notes", "session-token"), "w") as f:
        f.write("ALICE-NOTES-TOKEN\n")
    be._uninstall(A, False, remove_home=False)                               # the dialog's default: keep it
    assert os.path.exists(home_a)
    c_id = install.new_app_id(be.db, C, "Notes")
    assert c_id not in ("notes", "notes-2"), c_id                            # not A's kept home, not B's
    assert not os.path.exists(os.path.join(sb.sandbox_home(c_id), ".config", "notes", "session-token"))
    assert install.new_app_id(be.db, A, "Notes") == "notes"                  # A reinstalled gets its own home back


def test_a_home_with_no_owner_recorded_counts_as_another_apps(be, two):
    # 17.6, review 2 F19: a home made before owners were recorded (or whose record went) may hold
    # another app's accounts and tokens, so it counts as taken -- the safe direction: the worst case is
    # a reinstalled app starting afresh under a new id. Review 3, R3-4: no test made one.
    orphan = sb.sandbox_home("notes-3")
    os.makedirs(os.path.join(orphan, ".config"), exist_ok=True)
    assert not os.path.exists(sb.home_owner_path("notes-3"))
    assert sb.home_belongs_to_another("notes-3", C) and sb.home_belongs_to_another("notes-3", A)
    assert install.new_app_id(be.db, C, "Notes") == "notes-4"            # past notes, notes-2 and the orphan
    sb.record_home_owner("notes-3", C)                                    # once recorded, it is C's own
    assert not sb.home_belongs_to_another("notes-3", C) and install.new_app_id(be.db, C, "Notes") == "notes-3"


def test_a_home_removed_with_its_app_frees_the_name(be, two):
    be._uninstall(A, False, remove_home=True)
    assert not os.path.exists(sb.sandbox_home("notes"))
    assert install.new_app_id(be.db, C, "Notes") == "notes"                  # nothing of A's is left to inherit


def test_an_install_record_without_an_id_still_keys_on_the_slug(be, tmp_path):
    # a record written before round six: the slug is the id, so nothing moves on upgrade
    assert install.app_id_of({}, {"name": "My Notes"}) == "my-notes"
    assert install.app_id_of({"id": "my-notes-2"}, {"name": "My Notes"}) == "my-notes-2"
    be.db.x("INSERT OR REPLACE INTO installs(url, name, version, kind, record, installed_at) VALUES(?,?,?,?,?,?)",
            (A, "My Notes", "1.0", "tarball", json.dumps({"current": {"version": "1.0", "path": "/x", "exec": "x"}}), now()))
    assert install.new_app_id(be.db, B, "My Notes") == "my-notes-2"        # the old record holds the plain slug
    assert install.new_app_id(be.db, A, "My Notes") == "my-notes"          # the same URL keeps its own


# ------------------------------------------------------------------- the keyspace, from what the apps write (review 3)

# Files both same-named apps write, or that the second writes without its own id in the path, and the
# finding that keeps each so
STILL_SHARED: dict = {}


def _everything(root) -> dict:
    """{path: content hash} for every file under `root` but the database. The transitions snapshot
    leaves logs out, which is how F14 (logs keyed by name) passed the tests above."""
    out = {}
    for d, _, names in os.walk(root):
        for n in names:
            p = os.path.join(d, n)
            if n.startswith("appkata.db"):
                continue
            with open(p, "rb") as f:
                out[os.path.relpath(p, root)] = hash(f.read())
    return out


def _use(be, url, root):
    """What a user does with an installed app: start it from the app menu (its launcher writes its
    log), change its sandbox, and let AppKata rewrite its launcher."""
    fake = root / "fakebin"
    fake.mkdir(exist_ok=True)
    (fake / "bwrap").write_text("#!/bin/sh\nexit 0\n")
    (fake / "bwrap").chmod(0o755)
    rt = root / "run"
    rt.mkdir(exist_ok=True)
    rt.chmod(0o700)
    subprocess.run([_rec(be, url)["launcher"], "--appkata-menu"], capture_output=True, timeout=30,
                   env={"HOME": os.environ["HOME"], "XDG_RUNTIME_DIR": str(rt), "PATH": f"{fake}:{os.environ['PATH']}"})
    be.setSandbox(url, {"template": "offline-editor", "overrides": {}})
    be._regenerate_launcher(url)


def _collisions(be, root) -> set[str]:
    touched = {}
    for url in (A, B):
        before = _everything(root)
        _use(be, url, root)
        after = _everything(root)
        touched[url] = {k for k in set(before) | set(after) if before.get(k) != after.get(k)}
    state = os.path.relpath(os.environ.get("XDG_STATE_HOME") or os.path.join(os.environ["HOME"], ".local", "state"), root)
    norm = lambda k: k.replace(state, "<state>", 1)          # noqa: E731
    shared = touched[A] & touched[B]
    unkeyed = {k for k in touched[B] if "notes-2" not in k}
    return {norm(k) for k in shared | unkeyed}


def test_nothing_one_of_two_same_named_apps_writes_is_the_others_but_the_listed(be, two):
    assert _collisions(be, two) == set(STILL_SHARED)


def test_the_keyspace_catches_round_sixs_one_id_for_both(be, two):
    # R6-1: both installs keyed on the name's slug; give B the slug again and regenerate its launcher
    rb = _rec(be, B)
    rb["id"] = "notes"
    be.db.x("UPDATE installs SET record=? WHERE url=?", (json.dumps(rb), B))
    be._regenerate_launcher(B)
    found = _collisions(be, two)
    assert any("notes" in k and "notes-2" not in k and "Notes.log" not in k for k in found), found
