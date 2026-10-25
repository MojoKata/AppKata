"""The coworker protocols (coworker/README.md): the scripts every project carries to share a machine's
ISOs and VMs, run against a throwaway folder ($ISO_DIR, $VM_DIR) as the README says they behave."""

import hashlib
import os
import shutil
import subprocess
import time

import pytest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
ISO = os.path.join(ROOT, "coworker", "iso")
VM = os.path.join(ROOT, "coworker", "vm")

pytestmark = pytest.mark.skipif(not shutil.which("flock"), reason="the protocols need flock (util-linux)")


def _run(script, *args, env=None, check=True):
    res = subprocess.run(["sh", script, *args], capture_output=True, text=True, env={**os.environ, **(env or {})}, timeout=60)
    if check:
        assert res.returncode == 0, res.stderr + res.stdout
    return res


# ------------------------------------------------------------------------------------------- ISOs

@pytest.fixture
def isodir(tmp_path):
    d = tmp_path / "iso"
    return d, {"ISO_DIR": str(d)}


def test_iso_claims_keep_an_iso_until_the_last_is_released(isodir):
    d, env = isodir
    _run(os.path.join(ISO, "claim.sh"), "x.iso", "one", env=env)
    _run(os.path.join(ISO, "claim.sh"), "x.iso", "two", env=env)
    for f in ("x.iso", "x.iso.sha256", "x.iso.part", "x.iso.bad", "x.iso.lock"):
        (d / f).write_text("data")
    out = _run(os.path.join(ISO, "release.sh"), "x.iso", "one", env=env).stdout
    assert "kept, claimed by two" in out and (d / "x.iso").exists() and not (d / "x.iso.one").exists()
    out = _run(os.path.join(ISO, "release.sh"), "x.iso", "two", env=env).stdout
    assert "removed" in out and os.listdir(d) == []


def test_iso_project_names_are_checked(isodir):
    for bad in ("a b", "x/y", "lock", "sha256", "part", "bad"):
        res = _run(os.path.join(ISO, "claim.sh"), "x.iso", bad, env=isodir[1], check=False)
        assert res.returncode == 2, bad


def test_iso_list_shows_claims_and_verifies(isodir):
    d, env = isodir
    d.mkdir()
    (d / "a.iso").write_bytes(b"A")
    (d / "a.iso.sha256").write_text(hashlib.sha256(b"A").hexdigest() + "  a.iso\n")
    (d / "a.iso.one").touch()
    (d / "b.iso").write_bytes(b"B")
    (d / "b.iso.sha256").write_text("0" * 64 + "  b.iso\n")
    (d / "c.iso.two").touch()                                    # claimed, not here yet
    out = _run(os.path.join(ISO, "list.sh"), "--verify", env=env).stdout.splitlines()
    assert out[0].startswith("a.iso |") and out[0].endswith("claimed by one | SHA-256 ok")
    assert out[1].startswith("b.iso |") and "unclaimed" in out[1] and "doesn't match" in out[1]
    assert out[2] == "c.iso | not here yet | claimed by two"


@pytest.mark.skipif(not shutil.which("curl"), reason="download.sh needs curl")
def test_iso_download_checks_resumes_and_claims(isodir, tmp_path):
    d, env = isodir
    src = tmp_path / "src"
    src.mkdir()
    (src / "x.iso").write_bytes(b"x" * 100_000)
    good = hashlib.sha256(b"x" * 100_000).hexdigest()
    (src / "sha256sum.txt").write_text(f"{'1' * 64}  other.iso\n{good} *x.iso\n")   # a mirror's list
    (src / "wrong.txt").write_text("2" * 64 + "\n")
    args = ("x.iso", "one", f"file://{src}/x.iso")
    res = _run(os.path.join(ISO, "download.sh"), *args, f"file://{src}/wrong.txt", env=env, check=False)
    assert res.returncode == 1 and "doesn't match" in res.stderr and not (d / "x.iso").exists()
    os.remove(d / "x.iso.part")
    (d / "x.iso.part").write_bytes(b"x" * 40_000)                       # stopped part-way: resumed
    out = _run(os.path.join(ISO, "download.sh"), *args, f"file://{src}/sha256sum.txt", env=env).stdout
    assert "resuming" in out and "SHA-256 matches" in out and "one claims x.iso" in out
    assert (d / "x.iso").read_bytes() == b"x" * 100_000 and (d / "x.iso.one").exists()
    assert (d / "x.iso.sha256").read_text() == f"{good}  x.iso\n"
    out = _run(os.path.join(ISO, "download.sh"), "x.iso", "two", f"file://{src}/x.iso", f"file://{src}/sha256sum.txt",
               env=env).stdout
    assert "downloading" not in out and "two claims x.iso" in out           # already here: only claimed
    (d / "x.iso").write_bytes(b"corrupt")
    out = _run(os.path.join(ISO, "download.sh"), *args, f"file://{src}/sha256sum.txt", env=env).stdout
    assert "doesn't match" in out and (d / "x.iso.bad").read_bytes() == b"corrupt"
    assert (d / "x.iso").read_bytes() == b"x" * 100_000


# -------------------------------------------------------------------------------------------- VMs

@pytest.fixture
def vmdir(tmp_path):
    d = tmp_path / "vm"
    (d / "win").mkdir(parents=True)
    (d / "win" / "vm.env").write_text('VM_OS="Windows 10 Pro 22H2"\nVM_CONTAINER=box\nVM_SSH_PORT=2222\n'
                                      'VM_SSH_USER=tester\nVM_SSH_KEY=vm_key\n')
    return d, {"VM_DIR": str(d)}


def test_vm_release_never_deletes_a_vm(vmdir):
    d, env = vmdir
    _run(os.path.join(VM, "claim.sh"), "win", "one", env=env)
    _run(os.path.join(VM, "claim.sh"), "win", "two", env=env)
    assert "kept, claimed by two" in _run(os.path.join(VM, "release.sh"), "win", "one", env=env).stdout
    out = _run(os.path.join(VM, "release.sh"), "win", "two", env=env).stdout
    assert "no project claims it now" in out and (d / "win" / "vm.env").exists()
    assert _run(os.path.join(VM, "claim.sh"), "win", "lock", env=env, check=False).returncode == 2


def test_vm_env_resolves_the_vms_paths(vmdir):
    d, env = vmdir
    out = _run(os.path.join(VM, "env.sh"), "win", env=env).stdout
    got = dict(line.split("=", 1) for line in out.splitlines())
    home = os.path.realpath(d / "win")
    assert got["VM_HOME"] == f"'{home}'" and got["VM_SSH_KEY"] == f"'{home}/vm_key'"
    assert got["VM_KNOWN_HOSTS"] == f"'{home}/known_hosts'" and got["VM_SSH_HOST"] == "'127.0.0.1'"
    assert got["VM_OS"] == "'Windows 10 Pro 22H2'" and got["VM_CONTAINER"] == "'box'"
    shell = subprocess.run(["sh", "-c", f'eval "$(sh {VM}/env.sh win)"; echo "$VM_SSH_USER@$VM_SSH_HOST:$VM_SSH_PORT"'],
                           capture_output=True, text=True, env={**os.environ, **env})
    assert shell.stdout.strip() == "tester@127.0.0.1:2222"
    (d / "win" / "vm.env").write_text("VM_SSH_PORT=22\n")
    res = _run(os.path.join(VM, "env.sh"), "win", env=env, check=False)
    assert res.returncode == 1 and "sets no VM_SSH_USER" in res.stderr


def test_vm_lock_runs_one_project_at_a_time(vmdir, tmp_path):
    import fcntl                                                  # POSIX only: the module still loads on Windows
    d, env = vmdir
    lock = os.path.join(VM, "lock.sh")
    out = _run(lock, "win", "one", "--", "sh", "-c", f'echo "$COWORKER_VM_LOCKED"; cat {d}/win.lock', env=env).stdout
    assert out.startswith("win\none, pid ")                       # the command sees the lock and its holder
    assert (d / "win.lock").read_text() == ""                     # cleared after
    assert _run(lock, "win", "one", "--", "sh", "-c", "exit 3", env=env, check=False).returncode == 3
    with open(d / "win.lock", "a") as held:                       # another run holds it
        fcntl.flock(held, fcntl.LOCK_EX)
        (d / "win.lock").write_text("two, pid 1, since then\n")
        res = _run(lock, "win", "one", "--no-wait", "--", "true", env=env, check=False)
        assert res.returncode == 75 and "in use: two, pid 1" in res.stderr
        assert "in use: two" in _run(os.path.join(VM, "list.sh"), env=env).stdout
        mark = tmp_path / "ran"
        waiting = subprocess.Popen(["sh", lock, "win", "one", "--", "touch", str(mark)], env={**os.environ, **env},
                                   stdout=subprocess.PIPE, text=True)
        time.sleep(1)
        assert not mark.exists()                                  # waits for the holder
        fcntl.flock(held, fcntl.LOCK_UN)
    assert waiting.wait(timeout=20) == 0 and mark.exists()
    assert "waiting for it" in waiting.stdout.read()
    assert _run(lock, "nowhere", "one", "--", "true", env=env, check=False).returncode == 1


def test_vm_list_shows_what_claims_and_who_holds(vmdir):
    d, env = vmdir
    (d / "win.one").touch()
    (d / "other.two").touch()                                     # claimed, not set up yet
    out = _run(os.path.join(VM, "list.sh"), env=env).stdout.splitlines()
    assert out == ["other | not set up yet (no other/vm.env) | claimed by two | free",
                   "win | Windows 10 Pro 22H2 | claimed by one | free"]
