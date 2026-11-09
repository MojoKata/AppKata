"""scripts/publish.sh, the owner's steps for the release key and releases (docs/GENESIS.md): what can be
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


@pytest.mark.skipif(not shutil.which("gpg"), reason="needs gpg")
def test_the_release_key_is_the_one_the_docs_name(tmp_path):
    """packaging/appkata-release-key.asc is what publish.sh verify checks every release against, and
    the README's fingerprint is what a user checks a download against: the two must be the same key,
    and the key what GENESIS.md step 7 promises (an ed25519 main key that only certifies, 5 years; an
    ed25519 signing subkey, 2 years)."""
    out = subprocess.run(["gpg", "--batch", "--with-colons", "--show-keys",
                          os.path.join(ROOT, "packaging", "appkata-release-key.asc")],
                         env=dict(os.environ, GNUPGHOME=str(tmp_path)), check=True, capture_output=True, text=True).stdout
    rows = [line.split(":") for line in out.splitlines()]
    keys = [r for r in rows if r[0] in ("pub", "sub")]
    fprs = [r[9] for r in rows if r[0] == "fpr"]
    assert [r[0] for r in keys] == ["pub", "sub"], out
    assert [r[9] for r in rows if r[0] == "uid"] == ["AppKata <app@mojokata.xyz>"], out
    (pub, sub), year = keys, 365 * 86400
    assert pub[3] == sub[3] == "22" and pub[16] == sub[16] == "ed25519", out          # EdDSA, ed25519
    assert "".join(c for c in pub[11] if c.islower()) == "c" and sub[11] == "s", out    # certify; sign
    assert int(pub[6]) - int(pub[5]) == 5 * year and int(sub[6]) - int(sub[5]) == 2 * year, out
    groups = [fprs[0][i:i + 4] for i in range(0, 40, 4)]
    shown = " ".join(groups[:5]) + "  " + " ".join(groups[5:])         # as gpg --verify prints it
    for doc in ("README.md", os.path.join("docs", "gpg.md"), os.path.join("docs", "github-workflows.md"), os.path.join("docs", "GENESIS.md")):
        with open(os.path.join(ROOT, doc), encoding="utf-8") as f:
            assert shown in f.read(), (doc, shown)


def test_every_check_genesis_names_is_one_the_script_reads_back():
    with open(os.path.join(ROOT, "docs", "GENESIS.md"), encoding="utf-8") as f:
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
    assert "  release key: " in lines[-1], r.stderr            # it went on to the end
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


RESUME_GH = r'''#!/usr/bin/env python3
# gh for publish.sh resume, without GitHub: run 77 of v0.9.9, built and not waiting for an approval.
# FAKE_GH_ATTEMPTS is the run's attempts; a build job carries its sha256 notice only in the attempts
# FAKE_GH_BUILT names, as when "gh run rerun --failed" carries a job over into a new attempt.
import os, re, sys
a = sys.argv[1:]
attempts, built = int(os.environ["FAKE_GH_ATTEMPTS"]), os.environ["FAKE_GH_BUILT"].split()
sha = {"appimage": "a" * 64 + "  AppKata-0.9.9-x86_64.AppImage", "windows": "b" * 64 + "  AppKata-0.9.9-setup.exe"}
job = lambda attempt, name: f"{attempt}0{1 + list(sha).index(name)}"      # 101, 102, 201, ...
q = a[a.index("--jq") + 1] if "--jq" in a else ""
name = next((n for n in sha if f'"{n}"' in q), None)
if a[:2] == ["run", "list"]:
    print(77)
elif a[:2] == ["run", "view"] and "status,conclusion" in a:
    print("completed success")
elif a[:2] == ["run", "view"] and "attempt" in a:
    print(attempts)
elif a[:2] == ["run", "view"] and "jobs" in a:                 # the latest attempt's jobs
    print(job(attempts, name))
elif a[0] == "api" and a[1].endswith("/pending_deployments"):
    print(0)
elif a[0] == "api" and (m := re.search(r"/attempts/(\d+)/jobs$", a[1])):
    print(job(int(m.group(1)), name))
elif a[0] == "api" and (m := re.search(r"/check-runs/(\d)0(\d)/annotations$", a[1])):
    n = list(sha)[int(m.group(2)) - 1]
    if m.group(1) in built:
        print(sha[n])
'''


@pytest.mark.skipif(not shutil.which("sh"), reason="runs publish.sh, a POSIX shell script")
@pytest.mark.parametrize("attempts, built, shown", [
    (1, "1", True),             # the run as it first ran
    (2, "2", True),             # re-run whole: each attempt builds again
    (2, "1", True),             # gh run rerun --failed: the builds carried over from attempt 1
    (3, "1", True),
    (2, "", False),             # no attempt posted them
])
def test_resume_shows_what_ci_built_after_any_rerun(tmp_path, attempts, built, shown):
    """resume shows the SHA-256s of what CI built before the owner approves the signing (issue #13).
    After "gh run rerun --failed", GitHub carries the build jobs that passed into the new attempt
    as new jobs without their annotations, and resume stopped: "the run's build jobs posted no sha256
    notices". It reads each from the attempt that built it."""
    gh = tmp_path / "bin" / "gh"
    gh.parent.mkdir()
    gh.write_text(RESUME_GH)
    gh.chmod(0o755)
    r = subprocess.run(["sh", SCRIPT, "--repo", "owner/name", "--key", str(tmp_path / "no-key.asc"), "--yes",
                        "resume", "0.9.9"], capture_output=True, text=True, timeout=60,
                       env=dict(os.environ, FAKE_GH_ATTEMPTS=str(attempts), FAKE_GH_BUILT=built,
                                PATH=f"{gh.parent}{os.pathsep}{os.environ['PATH']}"))
    assert r.returncode == 1, r.stderr                         # verify then stops: no key to check with
    if shown:
        assert f"{'a' * 64}  AppKata-0.9.9-x86_64.AppImage\n{'b' * 64}  AppKata-0.9.9-setup.exe\n" in r.stderr, r.stderr
        assert "no public key to check the signature with" in r.stderr, r.stderr
    else:
        assert "publish.sh: the run's build jobs posted no sha256 notices" in r.stderr, r.stderr


GATE_GH = r'''#!/usr/bin/env python3
# gh for publish.sh release's and publish's gates, without GitHub. FAKE_CI: CI's run on master at the
# commit ("completed success", "in_progress ", "completed failure" or nothing); FAKE_FT_ALL and
# FAKE_FT_OPEN: the release's field-test issues; anything about the tag's run fails, which ends release.
import os, sys
a = sys.argv[1:]
if a[:2] == ["run", "list"] and "master" in a:
    print(os.environ.get("FAKE_CI", ""), end="")
elif a[:2] == ["release", "view"]:
    print("true")
elif a[:2] == ["issue", "list"]:
    print(os.environ.get("FAKE_FT_" + a[a.index("--state") + 1].upper(), ""), end="")
else:
    sys.exit(1)
'''

RECORD = "".join(f"- [x] **{step}** done\n" for step in
                 ("tier1", "sandbox", "github-paths", "pins", "version", "state", "screenshots"))


def _gate_repo(tmp_path, record=RECORD, state=True, status="0.9.9: Linux and Windows"):
    """A clone of a repository like this one at the commit the release pull request left, whose
    origin is a bare repository standing in for github.com/owner/name."""
    work, bare = tmp_path / "work", tmp_path / "remote" / "github.com" / "owner" / "name.git"
    for d in ("scripts", "src/appkata_core", "docs/releases", "tests/data/state", "bin"):
        (work / d).mkdir(parents=True)
    shutil.copy(SCRIPT, work / "scripts" / "publish.sh")
    (work / "src/appkata_core/__init__.py").write_text(
        '__version__ = "0.9.9"\nAPPKATA_REPO = "https://github.com/owner/name"\n')
    (work / "README.md").write_text(f"# AppKata\n\n## Status ({status})\n")
    if record is not None:
        (work / "docs/releases/0.9.9.md").write_text("# AppKata 0.9.9\n\n" + record)
    if state:
        (work / "tests/data/state/0.9.9.json").write_text("{}\n")
    (work / ".gitignore").write_text("bin/\n")
    gh = work / "bin" / "gh"
    gh.write_text(GATE_GH)
    gh.chmod(0o755)
    git = lambda *args, cwd=work: subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)  # noqa: E731
    subprocess.run(["git", "init", "-q", "--bare", "-b", "master", str(bare)], check=True)
    git("init", "-q", "-b", "master")
    for k, v in (("user.name", "Test"), ("user.email", "test@example.org"), ("commit.gpgsign", "false"),
                 ("tag.gpgsign", "false")):                 # this throwaway repository's own, for release's tag too
        git("config", k, v)
    git("add", "-A")
    git("commit", "-q", "-m", "0.9.9")
    git("remote", "add", "origin", str(bare))
    git("push", "-q", "origin", "master")
    return work, bare


def _gate(work, *args, **env):
    return subprocess.run(["sh", str(work / "scripts" / "publish.sh"), "--yes", *args], cwd=work, capture_output=True,
                          text=True, timeout=120, env=dict(os.environ, **env, GIT_CONFIG_GLOBAL=os.devnull,
                                                           PATH=f"{work / 'bin'}{os.pathsep}{os.environ['PATH']}"))


@pytest.mark.skipif(not (shutil.which("sh") and shutil.which("git")), reason="runs publish.sh in a git repository")
@pytest.mark.parametrize("case, says", [
    ("no record", "the release pull request isn't merged"),
    ("a step left out", "the step screenshots isn't ticked"),
    ("a step not done", "has steps not done: - [ ] **notes**"),
    ("no state", "tests/data/state/0.9.9.json is missing"),
    ("README", "README.md's Status heading doesn't name 0.9.9"),
    ("CI not run", "CI hasn't run on master"),
    ("CI running", "CI is still running on master"),
    ("CI failed", "CI failed on master"),
])
def test_release_tags_nothing_before_the_release_pull_request_is_merged_and_ci_passed_on_it(tmp_path, case, says):
    """release used to tag whatever master held: a missing state snapshot only asked "tag anyway?",
    and that CI had passed on master, the steps the release pull request takes and the README's
    version were the owner's to remember (docs/RELEASE.md). Each is a refusal now, before the tag."""
    repo = {"no record": dict(record=None), "a step left out": dict(record=RECORD.replace("**screenshots**", "**other**")),
            "a step not done": dict(record=RECORD + "- [ ] **notes** the release notes\n"), "no state": dict(state=False),
            "README": dict(status="0.9.8: Linux and Windows")}.get(case, {})
    ci = {"CI not run": "", "CI running": "in_progress \n", "CI failed": "completed failure\n"}.get(case, "completed success\n")
    work, bare = _gate_repo(tmp_path, **repo)
    r = _gate(work, "release", FAKE_CI=ci)
    assert r.returncode == 1 and says in r.stderr, r.stderr
    tags = subprocess.run(["git", "tag"], cwd=bare, capture_output=True, text=True).stdout
    assert tags == "", tags


@pytest.mark.skipif(not (shutil.which("sh") and shutil.which("git")), reason="runs publish.sh in a git repository")
def test_release_tags_once_the_release_pull_request_is_merged_and_ci_passed_on_it(tmp_path):
    work, bare = _gate_repo(tmp_path)
    r = _gate(work, "release", FAKE_CI="completed success\n")
    assert "CI passed on master at" in r.stderr, r.stderr
    tags = subprocess.run(["git", "tag"], cwd=bare, capture_output=True, text=True).stdout
    assert tags == "v0.9.9\n", r.stderr


@pytest.mark.skipif(not (shutil.which("sh") and shutil.which("git")), reason="runs publish.sh in a git repository")
@pytest.mark.parametrize("case, all_, open_, says", [
    ("none", "", "", "0.9.9 has no field-test issues"),
    ("open", "#5 CLOSED Field test: 0.9.9 on A\n#4 OPEN Field test: 0.9.9\n", "#4 OPEN Field test: 0.9.9\n",
     "the field test of 0.9.9 isn't done: these are open (docs/RELEASE.md, 4):\n#4 OPEN Field test: 0.9.9"),
    ("closed", "#5 CLOSED Field test: 0.9.9 on A\n#4 CLOSED Field test: 0.9.9\n", "",
     "Every field-test issue of 0.9.9 is closed.\npublish.sh: no public key"),
])
def test_publish_waits_for_every_field_test_issue_to_close(tmp_path, case, all_, open_, says):
    """publish used to publish any draft: that the field test was done was the owner's to remember.
    It refuses while the release has no field-test issues or one is open; once all are closed it
    goes on (to verify, which stops here on the missing key)."""
    work, _ = _gate_repo(tmp_path)
    r = _gate(work, "--key", str(tmp_path / "no-key.asc"), "publish", FAKE_FT_ALL=all_, FAKE_FT_OPEN=open_)
    assert r.returncode == 1 and says in r.stderr, r.stderr


def test_the_steps_release_requires_are_the_ones_the_agent_is_told_to_take():
    """release reads the record's ticked steps by ID (PREPARED); docs/RELEASE_AGENT.md's "Prepare a
    release" names each step by the same ID and shows the record's template. A step added to one and
    not the other is either never checked or never done."""
    prepared = re.search(r'^PREPARED="([^"]+)"', _script(), re.M).group(1).split()
    with open(os.path.join(ROOT, "docs", "RELEASE_AGENT.md"), encoding="utf-8") as f:
        agent = f.read()
    section = agent[agent.index("## 1. Prepare a release"):agent.index("## 2.")]
    assert re.findall(r"^\d+\. \*\*`([a-z0-9-]+)`:\*\*", section, re.M) == prepared
    assert re.findall(r"^   - \[x\] \*\*([a-z0-9-]+)\*\*", section, re.M) == prepared


def test_git_keeps_every_file_the_release_reads():
    # publish.sh release reads docs/releases/<version>.md and tests/data/state/<version>.json from
    # the merged pull request; .gitignore's "releases/" (the builds' folder at the top) also matched
    # docs/releases/, so the record could never be committed, and release would have refused every
    # version (the 0.1.0 re-cut, 2026-11-08, the first record).
    if not shutil.which("git"):
        pytest.skip("needs git")
    for path in ("docs/releases/9.9.9.md", "tests/data/state/9.9.9.json", "screenshots/linux/dark/X.png"):
        r = subprocess.run(["git", "check-ignore", "-q", "--no-index", path], cwd=ROOT)
        assert r.returncode == 1, f"git ignores {path}"
    r = subprocess.run(["git", "check-ignore", "-q", "--no-index", "releases/AppKata-9.9.9-x86_64.AppImage"], cwd=ROOT)
    assert r.returncode == 0, "the builds' releases/ folder is no longer ignored"
