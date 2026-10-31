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


def test_every_check_genesis_names_is_one_the_script_reads_back():
    with open(os.path.join(ROOT, "GENESIS.md"), encoding="utf-8") as f:
        genesis = f.read()
    text = _script()
    checks = text[text.index("check() {"):text.index("\n}\n", text.index("check() {"))]
    read_back = re.findall(r'^\s+(?:else )?is "([^"]+)"', checks, re.M)
    named = []
    for paragraph in re.findall(r"^Check: `publish\.sh check`(.*?)(?:\n\n|\Z)", genesis, re.M | re.S):
        named += re.findall(r'"([^"]+)"', paragraph.replace("\n", " "))
    assert "actions pinned by SHA" in named
    missing = [name for name in named if not any(label.startswith(name) for label in read_back)]
    assert not missing, missing


REFUSING_GH = """#!/bin/sh
# gh as a member without admin rights sees GitHub: every read refused, the API's error JSON on stdout
printf '{"message":"Must have admin rights to Repository.","status":"403"}'
echo "gh: Must have admin rights to Repository. (HTTP 403)" >&2
exit 1
"""


@pytest.mark.skipif(not shutil.which("sh"), reason="runs publish.sh, a POSIX shell script")
def test_check_says_it_cant_read_what_github_refuses_and_goes_on(tmp_path):
    """check, run by a member who can't read a setting: each line said the API's error JSON before
    "(can't read)", and a refused read of the rulesets ended the whole check (set -e) after three
    lines. The class: a command's refusal taken as its answer. With gh refusing every read, every
    line check reads back says "(can't read)", nothing else, through to the last."""
    gh = tmp_path / "gh"
    gh.write_text(REFUSING_GH)
    gh.chmod(0o755)
    r = subprocess.run(["sh", SCRIPT, "--repo", "owner/name", "check"], capture_output=True, text=True, timeout=60,
                       env=dict(os.environ, PATH=f"{tmp_path}{os.pathsep}{os.environ['PATH']}"))
    lines = r.stderr.splitlines()
    assert r.returncode == 1 and "{" not in r.stderr, r.stderr
    assert lines[-1].startswith("FAIL  release key:"), r.stderr            # it went on to the end
    text = _script()
    checks = text[text.index("check() {"):text.index("\n}\n", text.index("check() {"))]
    for name in dict.fromkeys(re.findall(r'\bis "([^"]+)" "\$\((?:api|gh) ', checks)):
        if name in ("release environment: deploys", "release environment: secrets") or name.startswith(
                ("master ruleset:", "tags ruleset:")):
            continue                        # read only once the environment or the ruleset is there
        assert f"FAIL  {name}: (can't read) (want" in r.stderr, name


FAKE_GH = r'''#!/usr/bin/env python3
# gh for publish.sh field-test, without GitHub: answers what it asks and logs each call as JSON
import json, os, sys
d, a = os.environ["FAKE_GH_DIR"], sys.argv[1:]
call = {"args": a}
if a[:2] == ["issue", "create"]:
    call["body"] = sys.stdin.read()
    n = 101 + len([f for f in os.listdir(d) if f.startswith("issue-")])
    open(os.path.join(d, f"issue-{n}"), "w").close()
    print(f"https://github.com/owner/name/issues/{n}")
elif a[:2] == ["label", "list"]:
    print(os.environ.get("FAKE_GH_LABELS", "bug\nfield-test"))
elif a[:2] == ["issue", "list"]:
    print(os.environ.get("FAKE_GH_ISSUES", ""), end="")
elif a[0] == "api" and a[1].startswith("repos/owner/name/issues/") and "--jq" in a:
    print(9000 + int(a[1].rsplit("/", 1)[1]))
with open(os.path.join(d, "calls"), "a") as f:
    f.write(json.dumps(call) + "\n")
'''


def _field_test(tmp_path, **env):
    import json
    gh = tmp_path / "bin" / "gh"
    gh.parent.mkdir()
    gh.write_text(FAKE_GH)
    gh.chmod(0o755)
    r = subprocess.run(["sh", SCRIPT, "--repo", "owner/name", "--yes", "field-test", "0.9.9"], capture_output=True,
                       text=True, timeout=60, env=dict(os.environ, FAKE_GH_DIR=str(tmp_path), **env,
                                                       PATH=f"{gh.parent}{os.pathsep}{os.environ['PATH']}"))
    calls = [json.loads(line) for line in open(tmp_path / "calls")] if (tmp_path / "calls").exists() else []
    return r, calls


@pytest.mark.skipif(not shutil.which("sh"), reason="runs publish.sh, a POSIX shell script")
def test_field_test_opens_the_release_issue_and_one_under_it_per_environment(tmp_path):
    """publish.sh field-test (the walk thru of 2026-10-30, item 4): the release's issue, then one per
    environment docs/testing.md names, with field-test.sh --issue-body's checklist, each made a
    sub-issue of the release's; all labelled field-test."""
    import sys
    sys.path.insert(0, os.path.join(ROOT, "scripts", "sandbox"))
    import fieldtest_questions as fq
    r, calls = _field_test(tmp_path)
    assert r.returncode == 0, r.stderr
    made = [c for c in calls if c["args"][:2] == ["issue", "create"]]
    title = lambda c: c["args"][c["args"].index("--title") + 1]
    envs = list(fq.environments())
    assert [title(c) for c in made] == ["Field test: 0.9.9"] + [f"Field test: 0.9.9 on {e}" for e in envs]
    assert all(c["args"][c["args"].index("--label") + 1] == "field-test" for c in made)
    assert all(f"- {e}" in made[0]["body"] for e in envs)
    assert [c["body"] for c in made[1:]] == [fq.issue_body(e) for e in envs]
    linked = [c["args"] for c in calls if "repos/owner/name/issues/101/sub_issues" in c["args"]]
    assert [a[a.index("-F") + 1] for a in linked] == [f"sub_issue_id={9102 + i}" for i in range(len(envs))]


@pytest.mark.skipif(not shutil.which("sh"), reason="runs publish.sh, a POSIX shell script")
def test_field_test_opens_nothing_without_the_label_or_twice(tmp_path):
    for case, env, says in (("no-label", {"FAKE_GH_LABELS": "bug"}, "publish.sh setup makes it"),
                            ("twice", {"FAKE_GH_ISSUES": "7\n"}, "already")):
        (tmp_path / case).mkdir()
        r, calls = _field_test(tmp_path / case, **env)
        assert r.returncode == 1 and says in r.stderr, (case, r.stderr)
        assert not [c for c in calls if c["args"][:2] == ["issue", "create"]], case
