"""scripts/pins-newest.py, which enforces the pin cooldown (docs/build.md, "Pinned inputs"): a pin moves
only to a release at least 14 days old. Offline: how it chooses, and that its inventory holds every pin
the repository has, so a pin added later isn't left out of the check.

How the class got in: pins were bumped to the newest release of each input, whatever its age (the
0.1.0 re-cut, 2026-11-07, until the owner asked about a cooldown). Nothing read a pin's age."""

import datetime as dt
import glob
import importlib.util
import os
import re

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
_spec = importlib.util.spec_from_file_location("pins_newest", os.path.join(ROOT, "scripts", "pins-newest.py"))
pn = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pn)

T = dt.datetime(2026, 11, 8, tzinfo=dt.timezone.utc)


def d(days):
    return T - dt.timedelta(days=days)


def test_newest_is_by_version_not_by_date():
    # 6.11.3 came out after 6.12.0: the newest eligible is still 6.12.0
    rel = [("6.11.2", d(81)), ("6.12.0", d(31)), ("6.11.3", d(13))]
    assert pn.newest(rel, d(14)) == ("6.12.0", d(31))


def test_newest_leaves_out_what_is_younger_than_the_cutoff():
    rel = [("9.1.1", d(141)), ("9.2.0", d(12))]
    assert pn.newest(rel, d(14))[0] == "9.1.1"
    assert pn.newest(rel)[0] == "9.2.0"


def test_newest_leaves_out_prereleases_and_what_is_at_or_past_the_ceiling():
    rel = [("6.12.0", d(31)), ("6.13.0rc1", d(40)), ("6.13.0", d(20))]
    assert pn.newest(rel, d(14), ceiling="6.13")[0] == "6.12.0"
    assert pn.newest(rel, d(14))[0] == "6.13.0"


def test_a_python_build_version_sorts_by_version_then_build():
    rel = [("3.14.8+20261013", d(25)), ("3.14.9+20261021", d(18)), ("3.14.10+20261026", d(13))]
    assert pn.newest(rel, d(14), plain=False)[0] == "3.14.9+20261021"
    assert pn.newest(rel, plain=False)[0] == "3.14.10+20261026"


def test_versions_compare_as_numbers():
    assert pn.vkey("3.14.10") > pn.vkey("3.14.9")
    assert pn.vkey("v7.0.1") == (7, 0, 1)


def _pins(kind):
    return {(p["name"], p["pinned"]) for p in pn.inventory() if p["kind"] == kind}


def test_every_pip_pin_in_the_repository_is_in_the_inventory():
    # any name==version in a script or packaging file, wherever it is: one outside pins-newest.py's
    # FILES fails here until FILES names its file
    have = _pins("pypi")
    files = glob.glob(os.path.join(ROOT, "scripts", "**", "*.sh"), recursive=True) + \
        glob.glob(os.path.join(ROOT, "packaging", "**", "*"), recursive=True)
    for path in files:
        if not os.path.isfile(path) or path.endswith((".png", ".ico", ".svg", ".asc")):
            continue
        for name, version in re.findall(r"(?<![\w.-])([A-Za-z][\w.-]*)==([0-9][\w.]*)", open(path, errors="replace").read()):
            assert (name, version) in have, f"{os.path.relpath(path, ROOT)}: {name}=={version} isn't in pins-newest.py's inventory"


def test_every_package_installed_by_a_variable_is_in_the_inventory():
    have = {n for n, _ in _pins("pypi")}
    for name in ["PySide6-Essentials", "shiboken6", "pyinstaller", "truststore"]:
        assert name in have


def test_every_image_url_and_action_pin_is_in_the_inventory():
    env = open(os.path.join(ROOT, "packaging", "versions.env")).read()
    images = {i.split("@")[0] for i in re.findall(r"^\w+_IMAGE=(\S+)", env, re.M)}
    assert images and images == {n for n, _ in _pins("docker")}
    assert len(re.findall(r"^\w+_URL=https://github\.com/", env, re.M)) == len(_pins("release"))
    assert {n for n, _ in _pins("python")} == {"python-build-standalone"}
    uses = set()
    for path in glob.glob(os.path.join(ROOT, ".github", "workflows", "*.yml")):
        uses |= set(re.findall(r"uses:\s*([\w.-]+/[\w.-]+)@", open(path).read()))
    assert uses and uses == {n for n, _ in _pins("action")}, "a workflow's action without '# vX.Y.Z' after its SHA"


def test_a_pin_younger_than_the_min_age_fails_unless_allowed(monkeypatch, capsys):
    monkeypatch.setattr(pn, "inventory", lambda: [{"kind": "pypi", "name": "x", "pinned": "2.0", "where": "f"}])
    monkeypatch.setattr(pn, "pypi_releases", lambda name: [("1.0", d(100)), ("2.0", d(3))])
    assert pn.main(["--min-age", "14"], now=T) == 1
    assert "too new" in capsys.readouterr().out
    assert pn.main(["--min-age", "14", "--allow", "x"], now=T) == 0
    assert pn.main(["--min-age", "2"], now=T) == 0
