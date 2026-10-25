"""Arguments as users give them, and users unlike the tester (review 3, harness 6).

How review 2's F6 and F15 slipped past: the corpus was the tester's own habits. The file-argument
tests passed absolute paths and file:// URIs, from the home folder. Nobody ran `codium .` from a
project folder, named a file relatively, passed `--file=notes.txt`, or opened a link on the
desktop. The sandbox tests ran as one person: English, no screen reader, no input method, no proxy,
default formats. The class: a corpus drawn from the tester instead of from users.

Part one runs a corpus of arguments shaped as users shape them, against the real document portal
in the launcher tiers. The shapes come from a shell (relative, `.`, `..`, globs, options with
values), from a desktop entry's %U and %F, from a file manager (links, linked folders), and from
intent (a folder, a file still to be made). The truth is whether the sandboxed app reaches what the
user meant.

Part two runs personas, users whose session carries what the tester's doesn't, through the
launcher's own words (tier 1). It checks whether each persona's needs reach the app: the variables,
the sockets and the bus names. One need is negative: what must never reach the app.

Each case still failing is listed with the finding that keeps it. Round two's R7 (no hand-over at
all) and a variable dropped from the allow-list are re-introduced to show the harness sees them.
"""

import json
import os
import subprocess

import sys

import pytest

from appkata_core import sandbox as sb
from test_sandbox_exposure import _recording_bwrap
from test_sandbox_run import Env, _Bus, _bwrap_ok, _DocPortal, env, needs_proxy   # noqa: F401

pytestmark = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="the sandbox and its launchers are Linux-only (17.1)")


@pytest.fixture(autouse=True)
def _proxy_here(monkeypatch):
    """The launchers here are for a host with xdg-dbus-proxy, as every launcher tier is; one without
    it has its own tests (review 2, F12)."""
    monkeypatch.setattr(sb, "have_bus_filter", lambda: True)


needs_bwrap = pytest.mark.skipif(not _bwrap_ok(), reason="needs a working bwrap 0.5+ (scripts/test-sandbox.sh launcher)")

# Arguments still not reaching what the user meant, and the finding that keeps each
STILL_FAILING = {
    "a file still to be made": "R3-16",       # deferred by the owner to 17.18 (review 3, decisions)
}

# The app: reads what it was given as a real one would -- its own options parsed, a URI decoded, a
# folder listed, a file read, or made when it isn't there yet (`make`)
APP_READS = r'''shift; a="$1"
case "$a" in --*=*) a="${a#*=}" ;; -o*) a="${a#-o}" ;; esac
case "$a" in file://*) a=$(python3 -c 'import sys, urllib.parse as u; print(u.unquote(u.urlsplit(sys.argv[1]).path))' "$a") ;; esac
if [ "$MAKE" = 1 ]; then echo MADE > "$a" 2>/dev/null && echo "WROTE"; elif [ -d "$a" ]; then ls "$a"; elif [ -e "$a" ]; then cat "$a"; else echo "MISSING $a"; fi'''


def _corpus(h: str) -> list[tuple]:
    """(case, where the user stands, the argument, what the app must print, make it?)"""
    return [
        ("an absolute path outside the granted folders", h, f"{h}/Elsewhere/out.txt", "OUTSIDE", False),
        ("an absolute path in a granted folder", h, f"{h}/Docs/in.txt", "IN-GRANT", False),
        ("a relative path from a granted folder", f"{h}/Docs", "in.txt", "IN-GRANT", False),
        ("./ from a granted folder", f"{h}/Docs", "./in.txt", "IN-GRANT", False),
        ("../ from inside a granted folder", f"{h}/Docs/sub", "../in.txt", "IN-GRANT", False),
        ("a relative path from elsewhere", f"{h}/Elsewhere", "out.txt", "OUTSIDE", False),
        ("a file:// URI (a menu entry's %U)", h, f"file://{h}/Elsewhere/out.txt", "OUTSIDE", False),
        ("a file:// URI with an encoded space", h, f"file://{h}/Elsewhere/my%20file.txt", "SPACED", False),
        ("a path with spaces and accents", h, f"{h}/Elsewhere/Résumé 2024.txt", "ACCENTED", False),
        ("an option with its value (--file=/path)", h, f"--file={h}/Elsewhere/out.txt", "OUTSIDE", False),
        ("a short option glued to its value (-o/path)", h, f"-o{h}/Elsewhere/out.txt", "OUTSIDE", False),
        ("a link on the desktop to a file in a granted folder", h, f"{h}/Desktop/link.txt", "IN-GRANT", False),
        ("a path through a linked folder", h, f"{h}/docs-link/in.txt", "IN-GRANT", False),
        (". from a granted folder (the folder itself)", f"{h}/Docs", ".", "in.txt", False),
        ("a folder outside the granted folders", h, f"{h}/Elsewhere/sub", "listed.txt", False),
        ("a file still to be made", h, f"{h}/Elsewhere/new.txt", "WROTE", True),
    ]


def _arrange(home) -> None:
    for d in ("Docs/sub", "Elsewhere/sub", "Desktop"):
        (home / d).mkdir(parents=True, exist_ok=True)
    for rel, text in (("Docs/in.txt", "IN-GRANT"), ("Elsewhere/out.txt", "OUTSIDE"), ("Elsewhere/my file.txt", "SPACED"),
                      ("Elsewhere/Résumé 2024.txt", "ACCENTED"), ("Elsewhere/sub/listed.txt", "x")):
        (home / rel).write_text(text + "\n")
    if not (home / "Desktop" / "link.txt").is_symlink():
        (home / "Desktop" / "link.txt").symlink_to(home / "Docs" / "in.txt")
        (home / "docs-link").symlink_to(home / "Docs")


def _arguments(env: Env, bus, monkeypatch=None) -> set[str]:
    _arrange(env.home)
    gs = sb.apply_overrides(sb.resolve_template("online-app"), {"folders": {"+~/Docs": "rw"}})
    lp = env.app("reader", gs)
    failing = set()
    for case, cwd, arg, want, make in _corpus(str(env.home)):
        r = subprocess.run([lp, APP_READS, arg], cwd=cwd, capture_output=True, text=True, timeout=60,
                           env={**env.env, "DBUS_SESSION_BUS_ADDRESS": bus.addr, "MAKE": "1" if make else "0"})
        made = make and (env.home / "Elsewhere" / "new.txt").exists()
        if want not in r.stdout or (make and not made):
            failing.add(case)
    return failing


@needs_bwrap
@needs_proxy
def test_arguments_shaped_as_users_shape_them_reach_what_they_meant_but_the_listed(env):
    bus = _Bus(env)
    try:
        portal = _DocPortal(env, bus)
        try:
            failing = _arguments(env, bus)
        finally:
            portal.close()
    finally:
        bus.close()
    assert failing == set(STILL_FAILING), f"failing {sorted(failing)}, listed {sorted(STILL_FAILING)}"


@needs_bwrap
@needs_proxy
def test_the_harness_catches_round_twos_arguments_never_handed_over(env, monkeypatch):
    # R7 (round two): the launcher passed host paths through, and the app found nothing at them
    monkeypatch.setattr(sb, "FORWARD_HELPER", "import shlex, sys\nr = sys.argv[sys.argv.index('--') + 1:]\n"
                                              "print(' '.join(shlex.quote(a) for a in r))\n")
    bus = _Bus(env)
    try:
        portal = _DocPortal(env, bus)
        try:
            failing = _arguments(env, bus)
        finally:
            portal.close()
    finally:
        bus.close()
    assert "an absolute path outside the granted folders" in failing and "a file:// URI (a menu entry's %U)" in failing, failing


# ------------------------------------------------------------------- personas (tier 1)

# What each persona's session carries, and what of it must reach a sandboxed app: a variable
# ("env X"), a folder or socket in view ("mount <path>"), a bus name the filter lets the app reach
# ("bus <name>"). "never" needs must not reach it.
PERSONAS = {
    "a German user": ({"LANG": "de_DE.UTF-8", "LANGUAGE": "de", "LC_TIME": "de_DE.UTF-8"},
                      ["env LANG", "env LANGUAGE", "env LC_TIME"]),
    "a user with regional formats unlike their language": (
        {"LANG": "en_US.UTF-8", **{v: "de_DE.UTF-8" for v in ("LC_MONETARY", "LC_PAPER", "LC_MEASUREMENT", "LC_ADDRESS",
                                                                 "LC_TELEPHONE", "LC_NAME", "LC_COLLATE", "LC_IDENTIFICATION")}},
        ["env LC_MONETARY", "env LC_PAPER", "env LC_MEASUREMENT", "env LC_ADDRESS", "env LC_TELEPHONE", "env LC_NAME",
         "env LC_COLLATE", "env LC_IDENTIFICATION"]),
    "a user in another time zone": ({"TZ": "Asia/Tokyo"}, ["env TZ"]),
    "a user behind a proxy": ({"http_proxy": "http://proxy:3128", "https_proxy": "http://proxy:3128", "no_proxy": "localhost"},
                              ["env http_proxy", "env https_proxy", "env no_proxy"]),
    "a Chinese or Japanese user (IBus)": ({"GTK_IM_MODULE": "ibus", "QT_IM_MODULE": "ibus", "XMODIFIERS": "@im=ibus"},
                                          ["env GTK_IM_MODULE", "env QT_IM_MODULE", "env XMODIFIERS", "bus org.freedesktop.portal.IBus"]),
    "a screen-reader user": ({}, ["mount $rt/at-spi", "bus org.a11y.Bus"]),
    "a HiDPI user on Plasma's X11 session": ({"QT_SCREEN_SCALE_FACTORS": "eDP-1=2;", "QT_AUTO_SCREEN_SCALE_FACTOR": "0",
                                              "GDK_SCALE": "2", "XCURSOR_SIZE": "48"},
                                             ["env QT_SCREEN_SCALE_FACTORS", "env QT_AUTO_SCREEN_SCALE_FACTOR", "env GDK_SCALE",
                                              "env XCURSOR_SIZE"]),
    "a developer with an SSH agent and a keyring": ({"SSH_AUTH_SOCK": "/run/user/1000/ssh-agent", "GNOME_KEYRING_CONTROL": "/run/user/1000/keyring"},
                                                    ["never env SSH_AUTH_SOCK", "never env GNOME_KEYRING_CONTROL"]),
}

# Needs not met yet, and the finding that keeps each
STILL_UNMET = {          # accessibility: stated as a limit in 17.17, its filtered proxy in 17.18 (the owner's decision)
    "a screen-reader user: mount $rt/at-spi": "R2-F15",
    "a screen-reader user: bus org.a11y.Bus": "R2-F15",
}


def _reaches(env: Env, session: dict) -> tuple[set, set, set]:
    """The variables, mount destinations and filter rules a Standard app gets in this session."""
    path, log = _recording_bwrap(env)
    (env.rt / "at-spi").mkdir(exist_ok=True)
    (env.rt / "at-spi" / "bus").write_text("")
    lp = env.app("persona", sb.resolve_template("online-app"))
    if os.path.exists(log):
        os.unlink(log)
    env.run(lp, "true", env={**session, "PATH": path, "DBUS_SESSION_BUS_ADDRESS": f"unix:path={env.rt}/bus"})
    with open(log) as f:
        calls = [json.loads(line) for line in f]
    app = next(a for a in reversed(calls) if "/.flatpak-info" in a)
    proxy = next((a for a in calls if "xdg-dbus-proxy" in a), [])
    names = {app[i + 1] for i, a in enumerate(app[:-1]) if a == "--setenv"}
    dests = {app[i + 2].replace(str(env.rt), "$rt") for i, a in enumerate(app[:-2]) if a.startswith(("--bind", "--ro-bind"))}
    return names, dests, set(proxy)


def _unmet(tmp_path, monkeypatch) -> set[str]:
    env = Env(tmp_path, monkeypatch)
    out = set()
    for persona, (session, needs) in PERSONAS.items():
        names, dests, rules = _reaches(env, session)
        for need in needs:
            neg = need.startswith("never ")
            kind, _, what = need.removeprefix("never ").partition(" ")
            got = (what in names if kind == "env" else
                   any(d == what or d.startswith(what + "/") for d in dests) if kind == "mount" else
                   any(what in r for r in rules if r.startswith(("--talk=", "--call=", "--own=", "--see="))))
            if got == neg:
                out.add(f"{persona}: {need}")
    return out


def test_what_each_personas_session_carries_reaches_the_app_but_the_listed(tmp_path, monkeypatch):
    unmet = _unmet(tmp_path, monkeypatch)
    assert unmet == set(STILL_UNMET), f"unmet {sorted(unmet - set(STILL_UNMET))}, now met {sorted(set(STILL_UNMET) - unmet)}"


def test_the_harness_catches_a_variable_dropped_from_the_allow_list(tmp_path, monkeypatch):
    monkeypatch.setattr(sb, "_ENV_PASSTHROUGH", tuple(v for v in sb._ENV_PASSTHROUGH if v != "LANGUAGE"))
    assert "a German user: env LANGUAGE" in _unmet(tmp_path, monkeypatch)
