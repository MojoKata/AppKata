"""Test and demo helpers: SSH-signed commits made without OpenSSH (sshsig's Ed25519 signer)."""

from __future__ import annotations

import os
import subprocess

from . import sshsig


def _run(repo: str, *args: str, input: bytes | None = None, env: dict | None = None) -> bytes:
    return subprocess.run(["git", "-C", repo, *args], input=input, capture_output=True, check=True,
                          env={**os.environ, **(env or {})}).stdout


def commit(repo: str, message: str, *, author: str = "Test", email: str = "test@example.com",
           ssh_seed: bytes | None = None, gpg_key: str = "", gnupghome: str = "", date: str = "") -> str:
    """Commit everything staged; sign with an Ed25519 SSH key (seed) or an OpenPGP key."""
    env = {"GIT_AUTHOR_NAME": author, "GIT_AUTHOR_EMAIL": email, "GIT_COMMITTER_NAME": author,
           "GIT_COMMITTER_EMAIL": email}
    if date:
        env.update(GIT_AUTHOR_DATE=date, GIT_COMMITTER_DATE=date)
    args = ["commit", "--quiet", "--allow-empty", "-m", message]
    if gpg_key:
        _run(repo, "-c", "gpg.format=openpgp", "-c", f"user.signingkey={gpg_key}", "commit", "--quiet", "-S",
             "--allow-empty", "-m", message, env={**env, "GNUPGHOME": gnupghome})
        return _run(repo, "rev-parse", "HEAD").decode().strip()
    _run(repo, "-c", "commit.gpgsign=false", *args, env=env)
    head = _run(repo, "rev-parse", "HEAD").decode().strip()
    if ssh_seed is None:
        return head
    raw = _run(repo, "cat-file", "commit", head)
    sig = sshsig.sign_ed25519(ssh_seed, raw, "git")
    header, _, body = raw.partition(b"\n\n")
    signed = header + b"\ngpgsig " + sig.replace("\n", "\n ").encode() + b"\n\n" + body
    new = _run(repo, "hash-object", "-t", "commit", "-w", "--stdin", input=signed).decode().strip()
    _run(repo, "update-ref", "HEAD", new, head)
    return new


def ssh_key_line(seed: bytes, comment: str = "") -> str:
    return sshsig.key_line(sshsig.ed25519_pub_blob(seed)) + (f" {comment}" if comment else "")


def gpg_keygen(home: str, uid: str) -> tuple[str, str]:
    """(fingerprint, armored public key) of a new passphrase-less Ed25519 key in `home`."""
    os.makedirs(home, mode=0o700, exist_ok=True)
    env = {**os.environ, "GNUPGHOME": home}
    subprocess.run(["gpg", "--batch", "--quiet", "--passphrase", "", "--quick-gen-key", uid, "ed25519", "sign", "never"],
                   env=env, capture_output=True, check=True)
    out = subprocess.run(["gpg", "--batch", "--with-colons", "--list-keys", uid], env=env, capture_output=True,
                         text=True, check=True).stdout
    fpr = next(line.split(":")[9] for line in out.splitlines() if line.startswith("fpr:"))
    pub = subprocess.run(["gpg", "--batch", "--armor", "--export", fpr], env=env, capture_output=True, text=True,
                         check=True).stdout
    return fpr, pub
