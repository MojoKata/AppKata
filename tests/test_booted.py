"""What each environment boots with, as docs/testing.md says, checked from inside each VM that
boots it (review 3, E10).

How R3-37 slipped past: "Mint 22 is built on 24.04 and ships the same restriction" was inferred
from Ubuntu 24.04 in round 2 of the experiments and copied into every document that names where
AppKata's AppArmor setup is needed. The Mint containers run on the test machine's kernel, so no
tier could show Mint's kernel or its sysctl settings; the first to boot them was the desktop VM.
The class: a fact about a system's kernel or boot-time settings, said of a distribution from its
base or from a container. One table in docs/testing.md now says what each environment boots with.
Every tier that boots one (the Ubuntu 24.04 and 26.04 VMs, the Mint 22.3 and LMDE 7 desktop VMs)
runs the last test here with APPKATA_BOOTED=1, so the table is run, not read; and
tests/test_docs_facts.py holds each document's naming of these facts to the table.
"""

import os
import platform
import re

import pytest

from appkata_core import sandbox as sb
from test_platform_matrix import claimed

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
HEADING = "## What each environment boots with"


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


def booted() -> dict:
    """{environment: {kernel, restricted, setup}} from docs/testing.md's table: the kernel series
    as tested, whether unprivileged user namespaces are restricted, whether AppKata's AppArmor
    setup is needed (17.10)."""
    text = _read("docs/testing.md")
    sec = text[text.index(HEADING + "\n") + len(HEADING):]
    end = re.search(r"^## ", sec, re.M)
    rows = {}
    for line in (sec[:end.start()] if end else sec).splitlines():
        if not line.startswith("| "):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if cells[0] == "Environment" or set(cells[0]) <= set("-"):
            continue
        rows[cells[0]] = {"kernel": cells[1], "restricted": cells[2].startswith("restricted"),
                          "setup": not cells[3].startswith("not needed")}
    return rows


def series(name: str) -> str:
    """One name for a system however a document writes it: "Linux Mint 22.3" and "Mint 22" are
    "Mint 22"; "Ubuntu 24.04 LTS" and "24.04" are "Ubuntu 24.04"."""
    n = " ".join(name.replace("Linux ", "").replace(" LTS", "").split())
    if re.fullmatch(r"\d\d\.\d\d", n):
        n = "Ubuntu " + n
    m = re.fullmatch(r"Mint (\d+)(?:\.\d+)?", n)
    return f"Mint {m.group(1)}" if m else n


def needs_setup() -> set:
    return {series(n) for n, row in booted().items() if row["setup"]}


def restricted() -> set:
    return {series(n) for n, row in booted().items() if row["restricted"]}


def kernels() -> dict:
    return {series(n): row["kernel"] for n, row in booted().items()}


def test_every_environment_with_a_sandbox_has_a_row_and_no_other():
    assert set(booted()) == claimed()


def test_the_setup_is_needed_only_where_the_namespaces_are_restricted():
    for name, row in booted().items():
        assert row["restricted"] or not row["setup"], name
        assert re.fullmatch(r"\d+\.\d+", row["kernel"]), (name, row["kernel"])


def _this_system() -> str:
    rel = {}
    with open("/etc/os-release") as f:
        for line in f:
            k, _, v = line.strip().partition("=")
            rel[k] = v.strip('"')
    here = f"{rel.get('NAME', '')} {rel.get('VERSION_ID', '')}"
    names = [n for n in booted() if n.replace(" LTS", "") == here]
    assert names, f"{here!r} has no row in docs/testing.md's {HEADING!r}"
    return names[0]


@pytest.mark.skipif(not os.environ.get("APPKATA_BOOTED"),
                    reason="only where the tier boots the environment's own kernel (the VMs); a container has the test machine's")
def test_this_system_boots_what_testing_md_says():
    name = _this_system()
    row = booted()[name]
    assert platform.release().startswith(row["kernel"] + "."), (name, platform.release(), row["kernel"])
    assert sb.userns_restricted() == row["restricted"], (name, "restricted" if sb.userns_restricted() else "allowed")
    # the setup is needed where the namespaces are restricted and the system has no bwrap profile of
    # its own (17.10, 17.10.2): what support_status() decides, before any setup has run
    others = sb.other_bwrap_profiles()
    assert (sb.userns_restricted() and not others) == row["setup"], (name, others)
