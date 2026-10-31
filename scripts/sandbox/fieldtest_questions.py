"""What the field test asks the tester, as one list: fieldtest.py asks these, `field-test.sh
--issue-body ENVIRONMENT` makes an environment's checklist of them for its GitHub sub-issue
(docs/testing.md, "Tracking the runs on GitHub"; the walk thru of 2026-10-30, item 4), and
tests/test_field_test_plan.py holds docs/local-proxy-test-plan.md to them. Nothing here touches the
home or the environment, so it can be read without starting a field test.

    python3 scripts/sandbox/fieldtest_questions.py ENVIRONMENT    the sub-issue's body
    python3 scripts/sandbox/fieldtest_questions.py --environments the environments, one a line
"""

import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

# asked everywhere
QUESTIONS = [
    ("P-dialog", "In a sandboxed app, does its own file dialog show its private home and the folders you gave it -- and nothing else of your home?"),
    ("P-openwith", "Does 'Open with' (or a drop on its menu entry) of a file outside its folders open that file in the sandboxed app?"),
    ("T-tray", "Messenger template: does its tray icon appear and do its notifications arrive?"),
    ("T-mpris", "Media player template: do the keyboard's media keys / the lock screen's controls work?"),
    ("U-selfupd", "An app that updates itself, sandboxed: does AppKata offer its updates, and does the app cope with its own updater failing?"),
    ("U-enable", "Switching an installed app from Off to a sandbox: are you told it starts with fresh settings?"),
    ("E-native", "A password manager's browser integration (native messaging): does it still work?"),
]
# asked only where AppKata's AppArmor setup is needed (17.10; docs/testing.md's table)
SETUP_QUESTIONS = [
    ("A1-prompt", "Before the setup, did installing a first AppImage ask 'Set up the sandbox?', did Not now install it unsandboxed, and did a second install not ask again?"),
    ("A1-pkexec", "Did Settings > Sandbox > Set up... show ONE password prompt, then 'Ready'?"),
]
# the sub-issue's box for a real GPU: the run checks it by itself (D-gpu), but only real hardware has one
GPU = ("D-gpu", "On this machine's own GPU: is the OpenGL renderer the run reports inside the sandbox that GPU, not a software one?")


def environments() -> dict:
    """{environment: whether AppKata's setup is needed there}, from testing.md's "What each
    environment boots with": the environments the field test runs in, by hand, before a release."""
    with open(os.path.join(ROOT, "docs", "testing.md"), encoding="utf-8") as f:
        text = f.read()
    table = text[text.index("## What each environment boots with"):text.index("## By hand, before a release")]
    rows = re.findall(r"^\| ([^|]+?) \| [^|]+ \| [^|]+ \| ([^|]+?) \|$", table, re.M)
    return {env: setup.startswith("needed") for env, setup in rows if env not in ("Environment",) and set(env) - set("-")}


def issue_body(environment: str) -> str:
    envs = environments()
    if environment not in envs:
        sys.exit(f"no environment {environment!r} in docs/testing.md; the field test's are: {', '.join(envs)}")
    boxes = (SETUP_QUESTIONS if envs[environment] else []) + QUESTIONS + [GPU]
    return (f"The field test on **{environment}**: `scripts/sandbox/field-test.sh` from the release's commit, "
            "without `--non-interactive`, on real hardware with a logged-in desktop (docs/testing.md, "
            "\"By hand, before a release\").\n\n"
            "Post each run as a comment: its `report.md` (`gh issue comment <n> --body-file "
            "appkata-fieldtest-…/report.md`), with its `.tar.gz` attached through the web page. Tick each box "
            "a run answered \"yes\". A \"no\" is a bug: open it with the `bug` label and link it from its box, "
            "which is ticked once a later run, after the fix, answers \"yes\".\n\n"
            + "".join(f"- [ ] **{cid}** {question}\n" for cid, question in boxes))


if __name__ == "__main__":
    if sys.argv[1:] == ["--environments"]:
        print("\n".join(environments()))
    elif len(sys.argv) == 2:
        print(issue_body(sys.argv[1]), end="")
    else:
        sys.exit(__doc__)
