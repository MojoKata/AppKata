"""AppKata calls coworker only through its coworker/ submodule (coworker protocol 4, MojoKata/coworker
README, "In a project"): never the installed commands directly, and no install checks of its own.

The submodule's launcher checks the installed coworker and hands the call over, so the checks live
in coworker. The checks that used to be copied into each script are where 11-07's CI failure came
from: build-appimage.sh's copy ran inside its own container, where nothing is installed. This
reads the scripts and the workflows for a direct call or a copied check.
"""

import os
import re

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
DIRECT = re.compile(r'(\$CW|\$\{?COWORKER_HOME\}?|\$HOME/coworker\}?|~/coworker\}?)/bin/')


def direct_calls(text):
    """The lines that call an installed coworker command, or check for one, directly."""
    return [l.strip() for l in text.splitlines() if DIRECT.search(l) and not l.lstrip().startswith("#")]


def files():
    for d, ext in (("scripts", ".sh"), (".github/workflows", ".yml")):
        for name in sorted(os.listdir(os.path.join(ROOT, d))):
            if name.endswith(ext):
                yield os.path.join(d, name)


def test_every_coworker_call_goes_through_the_submodule():
    bad = {}
    for path in files():
        with open(os.path.join(ROOT, path), encoding="utf-8") as f:
            hits = direct_calls(f.read())
        if hits:
            bad[path] = hits
    assert not bad, bad


def test_the_submodule_is_carried():
    assert os.path.isfile(os.path.join(ROOT, ".gitmodules"))
    with open(os.path.join(ROOT, ".gitmodules"), encoding="utf-8") as f:
        assert "path = coworker" in f.read()


def test_the_check_sees_a_direct_call_and_a_copied_check():
    text = ('CW=${COWORKER_HOME:-$HOME/coworker}\n[ -x "$CW/bin/deps" ] || exit 1\n'
            '"$CW/bin/deps" register "$HERE"\nexec "${COWORKER_HOME:-$HOME/coworker}/bin/vms" run w "$HERE"\n'
            '"$HERE/coworker/bin/deps" register "$HERE"\n# a comment about ~/coworker/bin/deps\n')
    assert direct_calls(text) == ['[ -x "$CW/bin/deps" ] || exit 1', '"$CW/bin/deps" register "$HERE"',
                                  'exec "${COWORKER_HOME:-$HOME/coworker}/bin/vms" run w "$HERE"']
