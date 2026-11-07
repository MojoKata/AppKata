"""A script that requires the coworker protocol and runs itself again in a container skips the check
in that run: coworker is installed on the host, not in the container.

How it slipped past: scripts/build-appimage.sh re-runs itself in an Ubuntu 22.04 container with
HOME=/tmp. When the scripts began requiring coworker, the check went at the top, so the container's
run looked for /tmp/coworker and stopped, and CI's appimage job failed. The change was proven with
the tiers that don't re-run themselves (tier 1 runs pytest in its container, not the script), and no
AppImage was built before it was pushed. This reads every script that has the check and runs
itself in a container, and requires the check to sit inside an `if` on the marker the container's
run is given (`-e NAME=1`).
"""

import os
import re

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
CHECK = re.compile(r'\[ -x "\$CW/bin/')


def _joined(text):
    """The script's lines, with each backslash-continued command on one line."""
    return text.replace("\\\n", " ").splitlines()


def unguarded(name, text):
    """Why the script's coworker check runs in its own container run, or None."""
    lines = _joined(text)
    reruns = [l for l in lines if "docker run" in l and re.search(r'scripts/' + re.escape(name) + r'\b', l)]
    if not reruns or not any(CHECK.search(l) for l in lines):
        return None
    markers = set()
    for l in reruns:
        markers |= set(re.findall(r"-e ([A-Z_][A-Z0-9_]*)=1\b", l))
    if not markers:
        return "runs itself in a container without an -e NAME=1 marker to tell the two runs apart"
    depth_guarded = []                      # the markers of the open `if`s that skip the container run
    for l in lines:
        s = l.strip()
        m = re.match(r'if \[ "\$\{([A-Z_][A-Z0-9_]*):-\}" != 1 \]', s)
        if m:
            depth_guarded.append(m.group(1))
        elif re.match(r"if\b", s):
            depth_guarded.append(None)
        elif s == "fi" or s.startswith("fi ") or s.startswith("fi;"):
            if depth_guarded:
                depth_guarded.pop()
        if CHECK.search(l) and not markers & set(depth_guarded):
            return f"checks for coworker outside an `if` on {sorted(markers)}"
    return None


def test_no_script_requires_coworker_inside_its_own_container():
    bad = {}
    for name in sorted(os.listdir(os.path.join(ROOT, "scripts"))):
        if name.endswith(".sh"):
            with open(os.path.join(ROOT, "scripts", name), encoding="utf-8") as f:
                why = unguarded(name, f.read())
            if why:
                bad[name] = why
    assert not bad, bad


RERUN = '''if [ "${IN_BOX:-}" != 1 ] && command -v docker >/dev/null; then
    exec docker run --rm -e HOME=/tmp -e IN_BOX=1 \\
        img sh "$HERE/scripts/b.sh" "$@"
fi
'''


def test_the_check_sees_an_unguarded_check():
    text = 'CW=$HOME/coworker\n[ -x "$CW/bin/deps" ] || exit 1\n' + RERUN
    assert "outside an `if`" in unguarded("b.sh", text)


def test_the_check_passes_a_guarded_check():
    text = ('if [ "${IN_BOX:-}" != 1 ]; then\n    [ -x "$CW/bin/deps" ] || exit 1\n'
            '    if [ -n "$X" ]; then :; fi\nfi\n' + RERUN)
    assert unguarded("b.sh", text) is None


def test_the_check_ignores_a_script_that_doesnt_run_itself():
    text = '[ -x "$CW/bin/deps" ] || exit 1\nexec docker run --rm img sh "$HERE/scripts/other.sh"\n'
    assert unguarded("b.sh", text) is None
