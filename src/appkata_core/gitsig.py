"""Trust repositories: fetching them and checking that AppKata.md changes are signed by an
Authority (requirement 7.6.2, 10.7, 10.8). Uses the system git; SSH signatures are checked in
pure Python (sshsig), OpenPGP ones with gpg in a keyring that holds only the Trust's keys."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field

from . import sshsig

GIT_TIMEOUT = 120


class GitError(Exception):
    pass


def git(repo: str | None, *args: str, env: dict | None = None, check: bool = True, input: bytes | None = None,
        timeout: int = GIT_TIMEOUT) -> str:
    cmd = ["git"] + (["-C", repo] if repo else []) + list(args)
    e = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": "", "SSH_ASKPASS": "", "LC_ALL": "C", **(env or {})}
    try:
        p = subprocess.run(cmd, capture_output=True, env=e, input=input, timeout=timeout)
    except FileNotFoundError:
        raise GitError("git isn't installed" + (": install Git for Windows (winget install Git.Git)" if os.name == "nt" else "")) from None
    except subprocess.TimeoutExpired:
        raise GitError(f"git {args[0]} timed out") from None
    if check and p.returncode != 0:
        msg = p.stderr.decode("utf-8", "replace").strip().splitlines()
        import logging
        logging.getLogger("appkata.git").warning("git %s failed: %s", " ".join(args[:3]), " | ".join(msg[-3:]))
        raise GitError(msg[-1] if msg else f"git {args[0]} failed")
    return p.stdout.decode("utf-8", "replace")


def git_version() -> tuple[int, ...]:
    try:
        m = re.search(r"(\d+)\.(\d+)", git(None, "--version"))
    except GitError:
        return ()
    return tuple(int(x) for x in m.groups()) if m else ()


# ---------------------------------------------------------------- locating the file
@dataclass
class Location:
    clone_url: str           # what git clones (a URL or a local path)
    path: str                # AppKata.md path inside the repo ("" = look in the root, then docs/)
    ref: str = ""            # branch from a /blob/<ref>/ URL


def locate(url: str) -> Location:
    """A Trust URL is a repository or a file in one (requirement 7.6.1)."""
    u = url.strip()
    if u.startswith("file://"):
        u = u[7:]
    if os.path.exists(os.path.expanduser(u)):
        p = os.path.abspath(os.path.expanduser(u))
        if os.path.isfile(p):
            top = git(os.path.dirname(p), "rev-parse", "--show-toplevel", check=False).strip()
            if top:
                return Location(top, os.path.relpath(p, top).replace(os.sep, "/"))
            return Location("", p)            # a plain file, not in git (the user's own file)
        return Location(p, "")
    m = re.match(r"^(https?://[^/]+/.+?)/(?:-/)?(?:blob|raw|src/branch)/([^/]+)/(.+\.md)$", u, re.I)
    if m:
        return Location(m.group(1) + ".git" if "github.com" in m.group(1) else m.group(1), m.group(3), m.group(2))
    m = re.match(r"^(https?://.+?)/(.+\.md)$", u, re.I)
    if m and not u.endswith(".git"):
        return Location(m.group(1), m.group(2))
    return Location(u, "")


def fetch(loc: Location, dest: str) -> str:
    """Clone or update a Trust repository into dest; return the commit at the tip."""
    if os.path.isdir(os.path.join(dest, ".git")) or os.path.isfile(os.path.join(dest, "HEAD")):
        git(dest, "fetch", "--quiet", "--prune", "--force", "origin", "+refs/heads/*:refs/remotes/origin/*")
    else:
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        tmp = dest + ".tmp"
        shutil.rmtree(tmp, ignore_errors=True)
        git(None, "clone", "--quiet", "--no-checkout", "--filter=blob:none", loc.clone_url, tmp)
        os.replace(tmp, dest)
    ref = f"refs/remotes/origin/{loc.ref}" if loc.ref else "refs/remotes/origin/HEAD"
    tip = git(dest, "rev-parse", "--verify", "--quiet", ref + "^{commit}", check=False).strip()
    if not tip:      # no origin/HEAD (e.g. a local clone): use the default branch
        head = git(dest, "symbolic-ref", "--quiet", "refs/remotes/origin/HEAD", check=False).strip()
        tip = git(dest, "rev-parse", (head or "refs/remotes/origin/main") + "^{commit}", check=False).strip() or \
              git(dest, "rev-parse", "refs/remotes/origin/master^{commit}").strip()
    return tip


def find_file(repo: str, tip: str, hint: str) -> str:
    """AppKata.md in the root or in docs/ (requirement 7.6.2)."""
    files = set(git(repo, "ls-tree", "-r", "--name-only", tip).splitlines())
    for cand in ([hint] if hint else []) + ["AppKata.md", "docs/AppKata.md"]:
        if cand in files:
            return cand
    lower = {f.lower(): f for f in files}
    for cand in ("appkata.md", "docs/appkata.md"):
        if cand in lower:
            return lower[cand]
    raise GitError("no AppKata.md in the repository root or docs/ folder")


def show(repo: str, commit: str, path: str) -> str:
    return git(repo, "show", f"{commit}:{path}")


def commits_touching(repo: str, tip: str, path: str, since: str = "") -> list[str]:
    rng = f"{since}..{tip}" if since else tip
    return git(repo, "log", "--format=%H", "--reverse", "--no-merges", "--first-parent", rng, "--", path).split()


def last_commit_touching(repo: str, tip: str, path: str) -> str:
    return git(repo, "log", "-1", "--format=%H", tip, "--", path).strip()


def is_ancestor(repo: str, a: str, b: str) -> bool:
    return subprocess.run(["git", "-C", repo, "merge-base", "--is-ancestor", a, b], capture_output=True).returncode == 0


# ---------------------------------------------------------------- signatures
@dataclass
class Signer:
    kind: str                 # "ssh" | "gpg"
    fingerprint: str          # "SHA256:…" or 40 hex digits
    key: str = ""             # SSH key line / armored OpenPGP key (when known)
    name: str = ""
    email: str = ""


@dataclass
class Check:
    commit: str
    status: str               # "good" | "unsigned" | "bad" | "nokey"
    signer: Signer | None = None
    author: str = ""
    author_email: str = ""
    date: str = ""
    reason: str = ""


def _split_commit(raw: bytes) -> tuple[bytes, str]:
    """(signed payload, signature) — git signs the commit object minus its gpgsig header."""
    lines = raw.split(b"\n")
    out, sig, i, in_headers = [], [], 0, True
    while i < len(lines):
        line = lines[i]
        if in_headers and line == b"":
            in_headers = False
        if in_headers and (line.startswith(b"gpgsig ") or line.startswith(b"gpgsig-sha256 ")):
            sig.append(line.split(b" ", 1)[1])
            i += 1
            while i < len(lines) and lines[i].startswith(b" "):
                sig.append(lines[i][1:])
                i += 1
            continue
        out.append(line)
        i += 1
    return b"\n".join(out), b"\n".join(sig).decode("utf-8", "replace")


def check_commit(repo: str, commit: str, gpg_keys: list[str] | None = None) -> Check:
    """Check one commit's signature. SSH: any valid signature identifies its key. OpenPGP: only
    keys in gpg_keys can be checked (others report 'nokey' with the issuer fingerprint)."""
    raw = subprocess.run(["git", "-C", repo, "cat-file", "commit", commit], capture_output=True, check=True).stdout
    meta = git(repo, "log", "-1", "--format=%an%x00%ae%x00%cI", commit).strip().split("\x00")
    base = dict(commit=commit, author=meta[0], author_email=meta[1] if len(meta) > 1 else "",
                date=meta[2] if len(meta) > 2 else "")
    payload, sig = _split_commit(raw)
    if not sig:
        return Check(status="unsigned", **base)
    if sshsig.ARMOR_BEGIN in sig:
        try:
            blob = sshsig.verify(sig, payload, "git")
        except sshsig.SshSigError as e:
            try:
                blob = sshsig.signer_blob(sig)
                signer = Signer("ssh", sshsig.fingerprint(blob), sshsig.key_line(blob))
            except sshsig.SshSigError:
                signer = None
            return Check(status="bad", signer=signer, reason=str(e), **base)
        return Check(status="good", signer=Signer("ssh", sshsig.fingerprint(blob), sshsig.key_line(blob),
                                                   meta[0], base["author_email"]), **base)
    if "BEGIN PGP SIGNATURE" in sig:
        return _check_gpg(repo, commit, gpg_keys or [], base)
    return Check(status="bad", reason="unknown signature format", **base)


def gpg_program() -> str:
    """gpg on the PATH, else Git for Windows' own (requirement 15.15)."""
    found = shutil.which("gpg") or ""
    if not found and os.name == "nt":
        from .windows import git_gpg
        found = git_gpg()
    return found


def _check_gpg(repo: str, commit: str, keys: list[str], base: dict) -> Check:
    gpg = gpg_program()
    if not gpg:
        return Check(status="nokey", reason="gpg isn't installed", **base)
    home = tempfile.mkdtemp(prefix="appkata-gpg-")
    try:
        os.chmod(home, 0o700)
        env = {"GNUPGHOME": home}
        for k in keys:
            subprocess.run([gpg, "--batch", "--quiet", "--import"], input=k.encode(), capture_output=True, env={**os.environ, **env})
        out = subprocess.run(["git", "-C", repo, "-c", f"gpg.program={gpg}", "verify-commit", "--raw", commit], capture_output=True,
                             env={**os.environ, **env}).stderr.decode("utf-8", "replace")   # gpg status lines
        status = git(repo, "-c", f"gpg.program={gpg}", "log", "-1", "--format=%G?%x00%GF%x00%GP%x00%GS", commit, env=env).strip().split("\x00")
        code = status[0]
        fpr = (status[2] if len(status) > 2 and status[2] else status[1] if len(status) > 1 else "").upper()
        if not fpr:
            m = re.search(r"ERRSIG \S+ \S+ \S+ \S+ \S+ \S+ ([0-9A-F]{40})", out) or \
                re.search(r"(?:VALIDSIG|NO_PUBKEY) ([0-9A-F]{16,40})", out)
            fpr = m.group(1) if m else ""
        signer_uid = status[3] if len(status) > 3 else ""
        name, email = _uid(signer_uid)
        signer = Signer("gpg", fpr, "", name or base["author"], email or base["author_email"]) if fpr else None
        if code in ("G", "U"):
            return Check(status="good", signer=signer, **base)
        if code == "E":
            return Check(status="nokey", signer=signer, reason="the signing key isn't known", **base)
        if code in ("X", "Y"):
            return Check(status="bad", signer=signer, reason="the signing key has expired", **base)
        if code == "R":
            return Check(status="bad", signer=signer, reason="the signing key was revoked", **base)
        return Check(status="bad", signer=signer, reason="the signature doesn't match", **base)
    finally:
        shutil.rmtree(home, ignore_errors=True)


def _uid(uid: str) -> tuple[str, str]:
    m = re.match(r"^(.*?)\s*<([^>]+)>", uid or "")
    return (m.group(1), m.group(2)) if m else (uid or "", "")


def gpg_key_info(armored: str) -> list[dict]:
    """[{fingerprint, name, email}] for the keys in an armored block."""
    gpg = gpg_program()
    if not gpg:
        return []
    p = subprocess.run([gpg, "--batch", "--with-colons", "--import-options", "show-only", "--import"],
                       input=armored.encode(), capture_output=True)
    out, cur = [], None
    for line in p.stdout.decode("utf-8", "replace").splitlines():
        f = line.split(":")
        if f[0] == "pub":
            cur = {"fingerprint": "", "name": "", "email": ""}
            out.append(cur)
        elif f[0] == "fpr" and cur is not None and not cur["fingerprint"]:
            cur["fingerprint"] = f[9]
        elif f[0] == "uid" and cur is not None and not cur["name"]:
            cur["name"], cur["email"] = _uid(f[9].replace("\\x3a", ":"))
    return out


def repo_gpg_keys(repo: str, commit: str) -> list[str]:
    """Armored keys a Trust publishes in .appkata/keys/ (one way to find an OpenPGP signer's key)."""
    out = []
    for p in git(repo, "ls-tree", "-r", "--name-only", commit, "--", ".appkata/keys/", check=False).splitlines():
        if p.endswith((".asc", ".gpg", ".pub")):
            out.append(git(repo, "show", f"{commit}:{p}", check=False))
    return [k for k in out if "BEGIN PGP PUBLIC KEY" in k]


# ---------------------------------------------------------------- following a Trust's history
@dataclass
class Authority:
    kind: str
    fingerprint: str
    key: str = ""
    enabled: bool = True
    pending: bool = False      # a new signer the user hasn't approved: still unknown (requirement 7.6.6)


@dataclass
class Advance:
    """The result of checking new commits (requirement 10.8)."""
    verified: str                     # the last verified commit to apply
    checks: list[Check] = field(default_factory=list)
    stopped: Check | None = None      # first commit that couldn't be accepted
    problem: str = ""                 # "" | "unsigned" | "unknown-signer" | "disabled" | "bad" | "rewritten"


def advance(repo: str, tip: str, path: str, since: str, authorities: list[Authority]) -> Advance:
    """Walk commits that changed `path` after `since`, accepting them while each is signed by an
    enabled Authority. The first that isn't stops the walk; nothing after it is applied."""
    if since and not is_ancestor(repo, since, tip):
        return Advance(verified=since, problem="rewritten")
    enabled = {a.fingerprint.upper(): a for a in authorities if a.enabled and not a.pending}
    known = {a.fingerprint.upper(): a for a in authorities if not a.pending}
    gpg_keys = [a.key for a in authorities if a.kind == "gpg" and a.key]
    res = Advance(verified=since)
    for c in commits_touching(repo, tip, path, since):
        chk = check_commit(repo, c, gpg_keys)
        res.checks.append(chk)
        fpr = chk.signer.fingerprint.upper() if chk.signer else ""
        if chk.status == "good" and fpr in enabled:
            res.verified = c
            continue
        res.stopped = chk
        if chk.status == "unsigned":
            res.problem = "unsigned"
        elif chk.status == "good" and fpr in known:
            res.problem = "disabled"
        elif chk.status in ("good", "nokey") and fpr and fpr not in known:
            res.problem = "unknown-signer"
        else:
            res.problem = "bad"
        break
    return res
