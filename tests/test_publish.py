"""scripts/publish.sh, the owner's steps for the release key and releases (GENESIS.md): what can be
checked without GitHub. Its GitHub half (setup, check, key-github, resume, verify) was run against a
fork with a throwaway key; see docs/github-workflows.md."""

import os
import re
import shutil
import subprocess
import time

import pytest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
SCRIPT = os.path.join(ROOT, "scripts", "publish.sh")


def _script():
    with open(SCRIPT, encoding="utf-8") as f:
        return f.read()


def test_the_usage_lists_every_command_the_script_takes():
    text = _script()
    listed = set(re.findall(r"^#     ([a-z][a-z-]+)", text, re.M))
    dispatch = text[text.index("case $CMD in"):]
    taken = set()
    for pattern in re.findall(r"^\s+([a-z|-]+)\)", dispatch, re.M):
        taken |= set(pattern.split("|"))
    assert listed == taken, (listed, taken)


@pytest.mark.skipif(not shutil.which("gpg"), reason="needs gpg")
def test_key_new_makes_a_certify_only_main_key_and_a_signing_subkey(tmp_path):
    passphrase = tmp_path / "passphrase"
    passphrase.write_text("a passphrase for the test\n")
    home = tmp_path / "key"
    env = dict(os.environ, APPKATA_KEY_PASSPHRASE_FILE=str(passphrase))
    try:
        subprocess.run(["sh", SCRIPT, "key-new", str(home), "AppKata test <test@example.org>"], env=env, check=True,
                       capture_output=True, timeout=120)
        out = subprocess.run(["gpg", "--batch", "--with-colons", "--list-keys"], env=dict(env, GNUPGHOME=str(home / "gnupg")),
                             check=True, capture_output=True, text=True).stdout
    finally:
        subprocess.run(["gpgconf", "--kill", "all"], env=dict(os.environ, GNUPGHOME=str(home / "gnupg")), capture_output=True)
    rows = [line.split(":") for line in out.splitlines()]
    pub = [r for r in rows if r[0] == "pub"]
    sub = [r for r in rows if r[0] == "sub"]
    fpr = next(r[9] for r in rows if r[0] == "fpr")
    assert len(pub) == 1 and len(sub) == 1
    assert pub[0][3] == sub[0][3] == "22", "ed25519 both"                 # algorithm 22: EdDSA
    own = lambda r: "".join(c for c in r[11] if c.islower())             # noqa: E731  (upper case: the whole key's)
    assert own(pub[0]) == "c" and own(sub[0]) == "s", (pub[0][11], sub[0][11])
    years = lambda r: (int(r[6]) - int(r[5])) / (365.25 * 86400)          # noqa: E731
    assert 4.9 < years(pub[0]) < 5.1 and 1.9 < years(sub[0]) < 2.1
    assert int(pub[0][5]) <= time.time()
    assert (home / "fingerprint").read_text().strip() == fpr
    assert "BEGIN PGP PUBLIC KEY BLOCK" in (home / "appkata-release-key.asc").read_text()
    assert "REVOCATION" in (home / "revocation.asc").read_text().upper()
    assert oct((home / "gnupg").stat().st_mode & 0o777) == "0o700"
