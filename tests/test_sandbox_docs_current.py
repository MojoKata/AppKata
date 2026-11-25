"""The documents R17 delegates to describe what is built (review 2, D1; class F).

R17.4 and R17.18 hand the launcher's explanation and the real-desktop checklist to
docs/local-proxy-test-plan.md and scripts/sandbox/field-test.sh. Both had kept the planning-stage
design long after it changed -- the marker in the private home and on the proxy, the whole portal
name, a random instance id, the camera portal, an updater option never built -- and the field test,
the release gate, exercised that design instead of AppKata's launcher (and overwrote the tester's
real SSH key). These checks keep the retired identifiers out of them.
"""

import collections
import os
import re

import reqdocs

HERE = os.path.dirname(os.path.abspath(__file__))
DELEGATES = ["docs/local-proxy-test-plan.md", "scripts/sandbox/field-test.sh", "scripts/sandbox/fieldtest.py"]
RETIRED = {
    "Status: planning": "the launcher is built",
    "isn't built yet": "the launcher is built",
    '$home/.flatpak-info': "the marker lives outside the private home (016476a)",
    "--talk=org.freedesktop.portal.Desktop": "the portal name is opened per interface (R17.5)",
    "instance-id=<random": "the instance id is the install's own id (R17.6)",
    "camera portal (via": "the Camera portal is closed to sandboxed apps (R17.8)",
    "Disable the app's own updater\" option is on": "AppKata updates a sandboxed self-updater (R17.12)",
    '"$HOME/.ssh/id_ed25519"': "the field test never touches the tester's home",
}


def _read(rel):
    with open(os.path.join(HERE, "..", rel), encoding="utf-8") as f:       # not the platform's (cp1252 on Windows)
        return f.read()


def test_the_documents_17_delegates_to_carry_no_retired_design():
    for rel in DELEGATES:
        text = _read(rel)
        for marker, why in RETIRED.items():
            if rel.endswith("fieldtest.py") and marker == '"$HOME/.ssh/id_ed25519"':
                continue                       # the probe reads it inside the sandbox, in the throwaway home
            assert marker not in text, f"{rel}: {marker!r} -- {why}"


def test_17_points_at_the_goldens_and_the_field_test_runs_appkatas_own_code():
    req = reqdocs.text()
    assert "tests/data/launchers/" in req and "kept byte" in req
    py = _read("scripts/sandbox/fieldtest.py")
    assert "install.install(" in py and "rewrite_launcher(" in py           # the product's install path and launcher
    assert "bwrap --ro-bind" not in py                                      # no hand-written sandbox
    assert "tempfile.mkdtemp" in py and 'os.environ.update(HOME=FAKE' in py  # a throwaway home


# PR #694's review, P4-B2: once protected_folder() read bus_files(), bus_sockets() had no caller in
# AppKata, only in the tests, and the docstrings of _protected_roots() and protected_folder() still
# sent a reader to it, away from the function that holds the rule. How it slipped past: a function
# only the tests call passes every test, and nothing read what a docstring points at. Every function
# sandbox.py defines is one AppKata's own code (src/, scripts/) names, and every :func: a docstring
# there points at is one of those.
def test_every_function_of_the_sandbox_is_one_appkata_names_and_its_docstrings_point_at_those():
    own = ""
    for top in ("src", "scripts"):
        for d, _, files in os.walk(os.path.join(HERE, "..", top)):
            own += "".join(_read(os.path.relpath(os.path.join(d, f), os.path.join(HERE, ".."))) for f in sorted(files)
                           if f.endswith((".py", ".sh", ".qml")))
    # each word, less its definitions and the docstrings' pointers: what names it
    words = collections.Counter(re.findall(r"\w+", own))
    words.subtract(re.findall(r"^def (\w+)\(", own, re.M) + re.findall(r":func:`(?:\w+\.)*(\w+)`", own))
    text = _read("src/appkata_core/sandbox.py")
    defined = re.findall(r"^def (\w+)\(", text, re.M)
    assert [n for n in defined if words[n] < 1] == [], "functions of sandbox.py nothing in src/ or scripts/ names"
    pointed = re.findall(r":func:`(?:\w+\.)*(\w+)`", text)
    assert pointed and [n for n in pointed if words[n] < 1] == [], "docstrings of sandbox.py point at these"
