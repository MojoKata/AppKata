"""Every platform requirement 1.1 supports a sandbox on has a sandbox tier, or is named as untested
(review 3, E3).

How review 2's F17 slipped past: the launcher tiers were chosen from the family the tester uses
(Mint and Ubuntu), and 17.1 described their ends as "both ends of what the supported platforms
ship". 1.1 also supported Debian, Fedora, RHEL and its rebuilds, and arm64, and none of them ran.
This test derives the claimed platforms from 1.1 and the tiers from scripts/test-sandbox.sh,
and fails when a claimed platform has neither a tier nor an entry in the list of untested ones. A
platform 1.1 supports "without the sandbox" (Ubuntu 22.04) needs no tier, and 1.1 must say so.
Since 2026-10-24 the platforms are the environments docs/testing.md tests (the owner's decision):
Fedora, RHEL and its rebuilds, Debian 12, Mint 21.3 and Ubuntu 25.04 left with their tiers.

A second check is about the platforms themselves: the launcher is a /bin/sh script, and the shell
behind /bin/sh differs (dash on Debian and Ubuntu, bash on RHEL and Fedora). Its pass-through block,
run by each tier's own /bin/sh with an empty environment, must pass nothing: bash's own TERM=dumb
reached every app there until R3-20.
"""

import os
import re
import shutil
import sys

import pytest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")

# Claimed platforms with no tier yet, and the finding that keeps each so
STILL_UNTESTED: dict = {}
# What each tier's image is, as platforms 1.1 names them
IMAGES = {
    "linuxmintd/mint22.3-amd64": {"Linux Mint 22.3"},
    "linuxmintd/lmde7-amd64": {"LMDE 7"},
}
VMS = {"launcher-vm": {"Ubuntu 24.04 LTS"}, "launcher-vm26": {"Ubuntu 26.04 LTS"}}       # 24.04 and 26.04 cloud images


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


def _platforms() -> list[str]:
    """1.1's Linux platforms, one bullet each, as written."""
    req = _read("docs/requirements.md")
    block = req[req.index("- Linux x86_64:"):req.index("\n- Windows")]
    return [" ".join(b.split()) for b in re.split(r"\n  - ", block)[1:]]


def claimed() -> set[str]:
    """The Linux platforms 1.1 supports a sandbox on: each bullet's name, up to its first comma or
    full stop, but those it supports "without the sandbox"."""
    return {re.split(r",|\.(?:\s|$)", p)[0].strip() for p in _platforms() if "without the sandbox" not in p}


def without_sandbox() -> set[str]:
    return {re.split(r",|\.(?:\s|$)", p)[0].strip() for p in _platforms() if "without the sandbox" in p}


def tiers(script: str | None = None) -> dict[str, set[str]]:
    """{launcher mode: the platforms it runs on}, from scripts/test-sandbox.sh."""
    script = script or _read("scripts/test-sandbox.sh")
    out = {}
    for modes, body in re.findall(r'if (\[ "\$\{1:-\}" = launcher[\w-]* \](?: \|\| \[ "\$\{1:-\}" = launcher[\w-]* \])*); then\n(.*?)\nfi\n',
                                  script, re.S):
        img = re.search(r"FROM ([^\\\s]+)", body)
        bases = re.findall(r"BASE=([^\s;]+)", body)       # one block, several images: FROM %s, a BASE each
        branches = re.findall(r'(?:if \[ "\$1" = ([\w-]+) \]; then|else) IMG=\S+ BASE=(\S+?);?(?:\s|$)', body)
        named = {m for m, _ in branches if m}
        for mode in re.findall(r"= (launcher[\w-]*) \]", modes):
            if mode in VMS:                    # a VM: the image built there only runs the QEMU
                out[mode] = VMS[mode]
            elif img and img.group(1) == "%s":
                base = next((b for m, b in branches if m == mode or (not m and mode not in named)), None)
                out[mode] = IMAGES.get(base, {f"unknown image for {mode}"})
            elif img:
                out[mode] = IMAGES.get(img.group(1), {f"unknown image {img.group(1)}"})
    return out


def _untested(script: str | None = None) -> set[str]:
    covered = set().union(*tiers(script).values())
    return {p for p in claimed() if p not in covered}


def test_every_platform_1_1_supports_has_a_sandbox_tier_but_the_listed():
    # arm64 is a later target, not a claim (review 2, F17, the owner's decision)
    assert claimed() == {"Linux Mint 22.3", "LMDE 7", "Ubuntu 24.04 LTS", "Ubuntu 26.04 LTS"}
    assert without_sandbox() == {"Ubuntu 22.04 LTS"}
    assert not any("unknown image" in p for ps in tiers().values() for p in ps), tiers()
    assert _untested() == set(STILL_UNTESTED), f"untested {sorted(_untested())}, listed {sorted(STILL_UNTESTED)}"


def test_17_1_says_where_the_sandbox_is_not_tested():
    req = _read("docs/requirements.md")
    scope = req[req.index("17.1. **Scope.**"):req.index("17.2. **Levels")]
    assert all(p.removesuffix(" LTS") in " ".join(scope.split()) for p in without_sandbox())


def test_the_matrix_catches_a_claimed_platform_losing_its_tier():
    script = _read("scripts/test-sandbox.sh")
    without = script.replace(' || [ "${1:-}" = launcher-lmde7 ]', "")
    assert "LMDE 7" in _untested(without)
    without = re.sub(r'if \[ "\$\{1:-\}" = launcher-vm \] \|\| .*?\nfi\n', "", script, flags=re.S)
    assert {"Ubuntu 24.04 LTS", "Ubuntu 26.04 LTS"} <= _untested(without)


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="the launcher is a Linux /bin/sh script (17.1)")
def test_the_launcher_passes_no_variable_its_shell_made_up():
    # Review 3, R3-20: the pass-through read its shell's own variables, and bash -- /bin/sh on RHEL and
    # Fedora -- sets TERM=dumb when it is unset, so every app started from the menu there got it.
    # The launcher's own block, run by this machine's /bin/sh with an empty environment, passes nothing.
    sys.path.insert(0, os.path.join(ROOT, "scripts", "sandbox"))
    import exposure as ex
    shell = os.path.basename(os.path.realpath(shutil.which("sh") or "/bin/sh"))
    made_up = ex.passed_through({"PATH": os.environ["PATH"]})
    assert made_up == set(), f"/bin/sh ({shell}): the launcher passes {sorted(made_up)} it was never given"
    assert ex.passed_through({"PATH": os.environ["PATH"], "TERM": "xterm", "LANG": "C.UTF-8"}) == {"TERM", "LANG"}
