"""No private name in the public repository (scripts/public_text.py): not the other projects that share
the machine AppKata is developed on, their folders or accounts, nor private accounts and domains.

How they got in: the documents and scripts were written on that machine for its owner, so the shared
Windows VM was named after the project that set it up, its account was the scripts' login, and the
ISOs lived in a folder named after the tool that fetched them. Nothing checked the repository for
what only made sense there. The class: a name that belongs to the machine, not to AppKata, written into a file. The shared
things now follow coworker/ and are reached through settings; this test reads every file git
tracks, and scripts/test-screenshot-text.sh the text in every screenshot."""

import os
import subprocess
import sys

import pytest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import public_text  # noqa: E402


def _tracked():
    try:
        out = subprocess.run(["git", "-C", ROOT, "ls-files", "-z"], capture_output=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("not a git work tree (the Windows VM's copy of the sources)")
    return [p for p in out.decode().split("\0") if p]


def test_no_private_name_in_any_tracked_file():
    hits = {}
    for rel in _tracked():
        path = os.path.join(ROOT, rel)
        if not os.path.isfile(path):
            continue
        with open(path, "rb") as f:
            data = f.read()
        if b"\0" in data[:8192]:
            continue                                          # binary: the screenshots have their own check
        found = public_text.found(data.decode("utf-8", errors="replace"))
        if found:
            hits[rel] = found
    assert not hits, f"private names in tracked files: {hits}"


def test_the_check_finds_a_name_however_it_is_written(monkeypatch):
    monkeypatch.setattr(public_text, "PRIVATE", {public_text.digest("examplecorp"), public_text.digest("lab-vm")})
    for text in ("ExampleCorp's VM", "~/examplecorp/scripts", "user examplecorp@127.0.0.1", "C:\\Users\\examplecorp",
                 "examplecorp-vm2", "the-examplecorp_tools.sh", "~/lab-vm/README.md", "container lab-vm"):
        assert public_text.found(text), text
    for text in ("examplecorporation", "myexamplecorp", "lab vm", "lab-vmware"):
        assert not public_text.found(text), text


def test_the_repository_address_is_appkata_core_s():
    """AppKata's own repository is written in one place, APPKATA_REPO (requirement 2.11.1): it was a
    placeholder until the real one was chosen, and the placeholder had been copied into the installer,
    the tour, the demo data and the mockups. Every address of AppKata's repository in a tracked file is
    APPKATA_REPO's, and the placeholder is nowhere."""
    import re

    from appkata_core import APPKATA_REPO
    own = APPKATA_REPO.split("://", 1)[1]
    hits = {}
    for rel in _tracked():
        path = os.path.join(ROOT, rel)
        if not os.path.isfile(path):
            continue
        with open(path, "rb") as f:
            data = f.read()
        if b"\0" in data[:8192]:
            continue
        text = data.decode("utf-8", errors="replace")
        bad = [m for m in re.findall(r"github\.com/[\w.-]+/appkata\b", text, re.I) if m != own]
        bad += re.findall(r"(?<![\w/])appkata/appkata(?![\w.])", text)
        if bad:
            hits[rel] = sorted(set(bad))
    assert not hits, f"AppKata's repository other than {own}: {hits}"
