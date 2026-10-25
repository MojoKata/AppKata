"""The documents requirement 17 delegates to describe what is built (review 2, D1; class F).

17.4 and 17.18 hand the launcher's explanation and the real-desktop checklist to
docs/local-proxy-test-plan.md and scripts/sandbox/field-test.sh. Both had kept the planning-stage
design long after it changed -- the marker in the private home and on the proxy, the whole portal
name, a random instance id, the camera portal, an updater option never built -- and the field test,
the release gate, exercised that design instead of AppKata's launcher (and overwrote the tester's
real SSH key). These checks keep the retired identifiers out of them.
"""

import os

HERE = os.path.dirname(os.path.abspath(__file__))
DELEGATES = ["docs/local-proxy-test-plan.md", "scripts/sandbox/field-test.sh", "scripts/sandbox/fieldtest.py"]
RETIRED = {
    "Status: planning": "the launcher is built",
    "isn't built yet": "the launcher is built",
    '$home/.flatpak-info': "the marker lives outside the private home (016476a)",
    "--talk=org.freedesktop.portal.Desktop": "the portal name is opened per interface (17.5)",
    "instance-id=<random": "the instance id is the install's own id (17.6)",
    "camera portal (via": "the Camera portal is closed to sandboxed apps (17.8)",
    "Disable the app's own updater\" option is on": "AppKata updates a sandboxed self-updater (17.12)",
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
    req = _read("docs/requirements.md")
    assert "tests/data/launchers/" in req and "kept byte" in req
    py = _read("scripts/sandbox/fieldtest.py")
    assert "install.install(" in py and "rewrite_launcher(" in py           # the product's install path and launcher
    assert "bwrap --ro-bind" not in py                                      # no hand-written sandbox
    assert "tempfile.mkdtemp" in py and 'os.environ.update(HOME=FAKE' in py  # a throwaway home
