"""One fact, one answer: wherever two places decide the same fact, they agree (review 3, harness 4).

How review 2's F7 slipped past -- and class H with it, a name used as a proxy for behaviour: which
display a sandboxed app is given is decided twice. The launcher gives the Wayland socket when
$WAYLAND_DISPLAY names one; the session warning asks $XDG_SESSION_TYPE and $XDG_CURRENT_DESKTOP,
and decides what the compositor leaks from the desktop's *name*. Each was tested alone, against
inputs its own author chose: the warning's test always set XDG_SESSION_TYPE=wayland, and treated
"GNOME" in the name as GNOME's compositor. So Budgie:GNOME and Phosh:GNOME (wlroots compositors)
were called safe, and a session the warning's test never imagined -- sway started from a TTY, where
logind sets XDG_SESSION_TYPE=tty and sway sets neither variable -- gets no warning at all.

This harness takes each fact decided in more than one place and runs every decider over one corpus,
against the truth where there is one:

- the display an app is given (the launcher, run) against the session the warning names;
- what the compositor leaks -- the Wayland globals it offers an ordinary client, from the registry
  listings the `wayland`, `kwin` and `kwin6` harnesses take (H) -- against the warning's verdict,
  and the warnings' advice and the tour's copy of the text against the same truth;
- whether a folder may be shared: the CLI tool's run-time rule in the launcher's shell (17.3.3)
  against the grant check in Python (17.3.1), over one corpus of folders;
- whether an app brings Chromium's sandbox: the launcher's shell test against App Detail's;
- whether this machine can sandbox an app, per level: support_status() against what the launchers
  do (tier 2).

The network grant's two deciders (the identity marker's `shared=network`, the launcher's
--share-net) are held by tests/test_sandbox_properties.py already. Each disagreement still open is
listed with the finding that keeps it; two fixed ones are re-introduced to show the harness sees
them.
"""

import json
import os
import re
import shutil
import subprocess
import types

import sys

import pytest

from appkata_core import install, sandbox as sb
from fake_wayland import OFFERS, FakeCompositor
from test_sandbox_exposure import _recording_bwrap
from test_sandbox_run import Env, _bwrap_ok, path_without

pytestmark = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="the sandbox and its launchers are Linux-only (17.1)")

# Disagreements still open, and the finding that keeps each
STILL_WRONG: dict = {}

# What each compositor offers an ordinary client, of the globals that leak (17.9): screen capture
# (zwlr_screencopy_manager_v1, ext_image_copy_capture), the clipboard (zwlr_data_control_manager_v1,
# ext_data_control_manager_v1) and input injection (zwp_virtual_keyboard_manager_v1,
# org_kde_kwin_fake_input). None: a compositor AppKata has never heard of, which 17.9 says is not
# assumed safe.
ALL = frozenset({"capture", "clipboard", "input"})
COMPOSITORS = {
    "mutter": (frozenset(), "run: the `wayland` harness's registry listing (mutter 46)"),
    "sway": (ALL, "run: the `wayland` harness (sway 1.9): screenshot, wl-paste and a typed key from a sandbox"),
    "kwin5": (frozenset({"clipboard"}), "run: the `kwin` harness (kwin 5.27), round seven R7-1"),
    "kwin6": (frozenset({"clipboard"}), "run: the `kwin6` harness (kwin 6.3)"),
    "labwc": (ALL, "read: wlroots, Budgie 10.10's Wayland session (review 2, F7)"),
    "phoc": (ALL, "read: wlroots, Phosh's compositor (review 2, F7)"),
    "unknown": (None, "17.9: a compositor AppKata has never heard of is not assumed safe"),
}
W, X = {"WAYLAND_DISPLAY": "wayland-0", "DISPLAY": ":0"}, {"DISPLAY": ":0"}
# A session as the user has it: its variables, and the compositor that really runs
SESSIONS = [
    ("GNOME (Ubuntu)", {"XDG_SESSION_TYPE": "wayland", "XDG_CURRENT_DESKTOP": "ubuntu:GNOME", **W}, "mutter"),
    ("GNOME (Fedora)", {"XDG_SESSION_TYPE": "wayland", "XDG_CURRENT_DESKTOP": "GNOME", **W}, "mutter"),
    ("Budgie 10.10 (labwc)", {"XDG_SESSION_TYPE": "wayland", "XDG_CURRENT_DESKTOP": "Budgie:GNOME", **W}, "labwc"),
    ("Phosh (phoc)", {"XDG_SESSION_TYPE": "wayland", "XDG_CURRENT_DESKTOP": "Phosh:GNOME", **W}, "phoc"),
    ("KDE Plasma 5", {"XDG_SESSION_TYPE": "wayland", "XDG_CURRENT_DESKTOP": "KDE", **W}, "kwin5"),
    ("KDE Plasma 6", {"XDG_SESSION_TYPE": "wayland", "XDG_CURRENT_DESKTOP": "KDE", **W}, "kwin6"),
    ("sway from a display manager", {"XDG_SESSION_TYPE": "wayland", "XDG_CURRENT_DESKTOP": "sway", **W}, "sway"),
    # sway sets WAYLAND_DISPLAY, DISPLAY and SWAYSOCK and nothing else (run: sway 1.9, the session
    # image); a console login's XDG_SESSION_TYPE is logind's "tty"
    ("sway from a TTY", {"XDG_SESSION_TYPE": "tty", **W}, "sway"),
    ("sway from a TTY, no logind", {**W}, "sway"),
    ("Hyprland from a TTY", {"XDG_SESSION_TYPE": "tty", "XDG_CURRENT_DESKTOP": "Hyprland", **W}, "unknown"),
    ("COSMIC", {"XDG_SESSION_TYPE": "wayland", "XDG_CURRENT_DESKTOP": "COSMIC", **W}, "unknown"),
    ("Cinnamon on X11", {"XDG_SESSION_TYPE": "x11", "XDG_CURRENT_DESKTOP": "X-Cinnamon", **X}, None),
    ("GNOME on Xorg", {"XDG_SESSION_TYPE": "x11", "XDG_CURRENT_DESKTOP": "GNOME", **X}, None),
    ("KDE on X11", {"XDG_SESSION_TYPE": "x11", "XDG_CURRENT_DESKTOP": "KDE", **X}, None),
    ("no display (ssh)", {}, None),
]
SESSION_VARS = ("XDG_SESSION_TYPE", "XDG_CURRENT_DESKTOP", "WAYLAND_DISPLAY", "DISPLAY")
# the desktops the warnings' advice may name, and the compositor each runs on Wayland
ADVICE = {"GNOME": "mutter", "KDE": "kwin6"}


def _verdict(w: dict) -> tuple:
    return (w.get("session"), w.get("leak", "all")) if w else (None, None)


def _truth(given: str | None, compositor: str | None) -> tuple:
    """The warning the app's real exposure calls for."""
    if given is None:
        return (None, None)
    if given == "x11":
        return ("x11", "all")
    leaks = COMPOSITORS[compositor][0]
    if leaks is None or leaks - {"clipboard"}:
        return ("wayland", "all")
    return ("wayland", "clipboard") if leaks else (None, None)


def _given(env: Env, lp: str, vars_: dict) -> str | None:
    """The display the launcher gives the app, read from its bwrap words."""
    path, log = _recording_bwrap(env)
    if os.path.exists(log):
        os.unlink(log)
    launch = {**{v: "" for v in SESSION_VARS}, **vars_, "PATH": path}
    env.run(lp, "true", env={k: v for k, v in launch.items() if v or k == "PATH"})
    with open(log) as f:
        argv = next(a for a in reversed([json.loads(line) for line in f]) if "/.flatpak-info" in a)
    names = {argv[i + 1] for i, a in enumerate(argv[:-1]) if a == "--setenv"}
    return "wayland" if "WAYLAND_DISPLAY" in names else "x11" if "DISPLAY" in names else None


def _display_disagreements(tmp_path, monkeypatch) -> set[str]:
    env = Env(tmp_path, monkeypatch)
    lp = env.app("viewer", sb.resolve_template("strict"))
    monkeypatch.setattr(sb, "OS", "linux")
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(env.rt))
    wrong = set()
    for label, vars_, compositor in SESSIONS:
        # the session's compositor, answering the registry with the globals it offers (fake_wayland)
        fake = FakeCompositor(str(env.rt / "wayland-0"), OFFERS[compositor]) if compositor else None
        try:
            given = _given(env, lp, vars_)
            for v in SESSION_VARS:
                monkeypatch.delenv(v, raising=False)
            for k, v in vars_.items():
                monkeypatch.setenv(k, v)
            if _verdict(sb.session_warning()) != _truth(given, compositor):
                wrong.add(label)
        finally:
            if fake:
                fake.close()
    return wrong


def test_the_fake_compositors_offer_what_the_table_says_they_leak(tmp_path, monkeypatch):
    # the stand-in serves each compositor's globals; the product's reader turns them into the leaks
    # COMPOSITORS states (the real ones: the wayland, kwin and kwin6 harnesses)
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-9")
    for name, (leaks, _) in COMPOSITORS.items():
        fake = FakeCompositor(str(tmp_path / "wayland-9"), OFFERS[name])
        try:
            assert sb.compositor_globals() == set(OFFERS[name])
            assert sb.compositor_leaks() == (leaks if leaks is not None else set()), name
        finally:
            fake.close()
    assert sb.compositor_globals() is None                  # no compositor: nothing read


def test_the_warning_matches_the_display_the_app_gets_and_what_its_compositor_leaks_but_the_listed(tmp_path, monkeypatch):
    wrong = _display_disagreements(tmp_path, monkeypatch)
    sessions = {label for label, _, _ in SESSIONS}
    assert wrong == {k for k in STILL_WRONG if k in sessions}, \
        f"the warning against the truth: wrong {sorted(wrong)}, listed {sorted(k for k in STILL_WRONG if k in sessions)}"


def test_the_harness_catches_round_sevens_kde_on_the_allowlist(tmp_path, monkeypatch):
    # R7-1: KDE was on the allowlist, but kwin offers the clipboard-manager protocol to every client
    # (with the globals read, as F7 now has them, KDE's clipboard keeps the warning; without them, not)
    monkeypatch.setattr(sb, "_CLEAR", sb._CLEAR + ("kde",))
    monkeypatch.setattr(sb, "compositor_leaks", lambda env=None: None)
    wrong = _display_disagreements(tmp_path, monkeypatch)
    assert {"KDE Plasma 5", "KDE Plasma 6"} <= wrong, wrong


def test_the_harness_catches_review_twos_gnome_named_wlroots_compositors(tmp_path, monkeypatch):
    # F7: the warning judged the compositor by the desktop's name alone; "GNOME" in Budgie's and
    # Phosh's names cleared labwc and phoc
    monkeypatch.setattr(sb, "compositor_leaks", lambda env=None: None)
    wrong = _display_disagreements(tmp_path, monkeypatch)
    assert {"Budgie 10.10 (labwc)", "Phosh (phoc)"} <= wrong, wrong


def _texts_wrong(monkeypatch) -> set[str]:
    wrong = set()
    monkeypatch.setattr(sb, "OS", "linux")
    monkeypatch.setenv("XDG_SESSION_TYPE", "x11")
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    x11 = sb.session_warning()
    # the advice may recommend only desktops whose Wayland compositor leaks nothing: the ones it names
    # before "Wayland session", or in a parenthesis right after it ("(GNOME or KDE)", review 2's F7)
    m = re.search(r"Log into an? ([\w ]*?)Wayland session( \(([^)]*)\))?", x11["text"])
    said = (m.group(1) + " " + (m.group(3) or "")) if m else ""
    named = [d for d in ADVICE if d in said]
    if any(COMPOSITORS[ADVICE[d]][0] for d in named):
        wrong.add("the X11 advice")
    # the tour's copy of the warning is the product's text for the same session
    from appkata.backend import Backend
    tour = Backend._sb_session_warning(types.SimpleNamespace(_demo_sandbox="x11"))
    if tour != x11:
        wrong.add("the tour's warning")
    return wrong


def test_the_harness_catches_review_twos_x11_advice(monkeypatch):
    # F7: the X11 warning told users that a KDE Wayland session closes the leak; kwin leaks the clipboard
    pytest.importorskip("PySide6")
    monkeypatch.setattr(sb, "X11_WARNING", {"session": "x11", "text": "On X11 the sandbox protects your files. Log into a "
                                            "Wayland session (GNOME or KDE) to close this, or accept it per app."})
    assert "the X11 advice" in _texts_wrong(monkeypatch)


def test_every_copy_of_the_warning_says_what_the_product_does_but_the_listed(monkeypatch):
    pytest.importorskip("PySide6")
    wrong = _texts_wrong(monkeypatch)
    listed = {"the X11 advice", "the tour's warning"} & set(STILL_WRONG)
    assert wrong == listed, f"wrong {sorted(wrong)}, listed {sorted(listed)}"


# ------------------------------------------------------------------- may this folder be shared (17.3.1, 17.3.3)

def _folders(env: Env) -> dict[str, str]:
    h = str(env.home)
    corpus = {
        "the home folder": h, "above the home folder": os.path.dirname(h), "/": "/", "a project": f"{h}/src/proj",
        "a folder with spaces": f"{h}/My Projects/a b", "a folder named like a glob": f"{h}/[x]*",
        "~/.config": f"{h}/.config", "~/.config/autostart": f"{h}/.config/autostart",
        "inside autostart": f"{h}/.config/autostart/sub", "~/.local": f"{h}/.local", "~/.local/bin": f"{h}/.local/bin",
        "~/.local/share": f"{h}/.local/share", "the app-menu folder": f"{h}/.local/share/applications",
        "AppKata's data": f"{h}/.local/share/appkata", "another app's private home": f"{h}/.local/share/appkata/sandboxes/other",
        "the install root": f"{h}/apps", "an installed app": f"{h}/apps/other/1.0", "~/.ssh": f"{h}/.ssh",
        "inside ~/.ssh": f"{h}/.ssh/sub", "~/.cache": f"{h}/.cache", "~/Documents": f"{h}/Documents",
        "Firefox's profiles (a secret)": f"{h}/.mozilla/firefox/x.default", "the runtime folder": str(env.rt),
        "inside the runtime folder": f"{env.rt}/sub", "/tmp's own folder": str(env.home.parent / "elsewhere"),
    }
    for p in corpus.values():
        if p != "/":
            os.makedirs(p, exist_ok=True)
    for name, target in (("a link to ~/.ssh", f"{h}/.ssh"), ("a link to a project", f"{h}/src/proj"),
                         ("a link to the home folder", h)):
        link = env.home.parent / name.replace(" ", "-").replace("/", "_").replace("~", "home")
        if not link.exists():
            link.symlink_to(target)
        corpus[name] = str(link)
    return corpus


def _sharing_disagreements(tmp_path, monkeypatch) -> list[str]:
    env = Env(tmp_path, monkeypatch)
    lp = env.app("tool", sb.resolve_template("cli-tool"))
    path, log = _recording_bwrap(env)
    wrong = []
    for name, folder in _folders(env).items():
        if os.path.exists(log):
            os.unlink(log)
        env.run(lp, "true", cwd=folder, env={"PATH": path})
        with open(log) as f:
            argv = next(a for a in reversed([json.loads(line) for line in f]) if "/.flatpak-info" in a)
        here = os.path.realpath(folder)
        shell = any(argv[i:i + 3] == [b, here, here] for i in range(len(argv) - 2) for b in ("--bind", "--ro-bind"))
        python = sb.protected_folder(folder, str(env.home / "apps")) == ""
        if shell != python:
            wrong.append(f"{name}: the launcher {'shares' if shell else 'refuses'} it, the grant check "
                         f"{'allows' if python else 'refuses'} it ({sb.protected_folder(folder, str(env.home / 'apps')) or 'no reason'})")
    return wrong


def test_the_cli_tools_folder_rule_and_the_grant_check_agree_on_every_folder(tmp_path, monkeypatch):
    wrong = _sharing_disagreements(tmp_path, monkeypatch)
    assert not wrong, "\n".join(wrong)


def test_the_harness_catches_the_cli_tool_sharing_the_home_it_runs_from(tmp_path, monkeypatch):
    # The first $cwd bind had no rule: a tool run from ~ got the whole real home (round one). Taking
    # out the "the folder or one above it" test brings that back for every folder above a protected one
    build = sb.build_launcher
    monkeypatch.setattr(sb, "build_launcher", lambda *a, **k: build(*a, **k).replace(
        'case "$d/" in "$here"/*) share=0 ;; esac', ":"))
    wrong = _sharing_disagreements(tmp_path, monkeypatch)
    assert any(w.startswith("the home folder: the launcher shares it") for w in wrong), wrong


# ------------------------------------------------------------------- does the app bring its own sandbox (17.10.2)

LAYOUTS = {  # files relative to the version folder, and the program
    "chrome-sandbox beside the program": (["app", "chrome-sandbox"], "app"),
    "crashpad beside the program": (["app", "chrome_crashpad_handler"], "app"),
    "program in bin/, chrome-sandbox at the top": (["bin/app", "chrome-sandbox"], "bin/app"),
    "program and chrome-sandbox in bin/": (["bin/app", "bin/chrome-sandbox"], "bin/app"),
    "chrome-sandbox elsewhere (lib/)": (["bin/app", "lib/chrome-sandbox"], "bin/app"),
    "no Chromium": (["app", "resources.pak"], "app"),
}


def test_the_launcher_and_app_detail_agree_on_which_apps_bring_chromiums_sandbox(tmp_path, monkeypatch):
    pytest.importorskip("PySide6")
    env = Env(tmp_path, monkeypatch)
    monkeypatch.setattr(sb, "nested_userns_works", lambda: False)        # the launcher adds --no-sandbox then
    from appkata.backend import Backend
    path, log = _recording_bwrap(env)
    wrong = []
    for name, (files, exe) in LAYOUTS.items():
        appdir = env.home / "apps" / name.replace(" ", "_").replace("/", "_") / "1.0"
        for f in files:
            (appdir / f).parent.mkdir(parents=True, exist_ok=True)
            (appdir / f).write_text("#!/bin/sh\n")
            (appdir / f).chmod(0o755)
        lp = sb.write_launcher("chromium-ish", "C", str(env.home / "apps"), str(appdir), exe, sb.resolve_template("strict"))
        if os.path.exists(log):
            os.unlink(log)
        env.run(lp, "true", env={"PATH": path})
        with open(log) as f:
            argv = next(a for a in reversed([json.loads(line) for line in f]) if "/.flatpak-info" in a)
        launcher = "--no-sandbox" in argv[argv.index("--"):]
        monkeypatch.setattr(install, "_launcher_program", lambda rec, target, a=str(appdir), e=exe: (a, e, None))
        fake = types.SimpleNamespace(db=types.SimpleNamespace(one=lambda *a: {"record": json.dumps(
            {"current": {"path": "x"}, "target": "t"})}))
        detail = Backend._brings_own_sandbox(fake, "u")
        if launcher != detail:
            wrong.append(f"{name}: the launcher says {launcher}, App Detail says {detail}")
    assert not wrong, "\n".join(wrong)


# ------------------------------------------------------------------- can this machine sandbox an app (17.10; tier 2)

@pytest.mark.skipif(not _bwrap_ok() or not shutil.which("xdg-dbus-proxy"), reason="needs bwrap and xdg-dbus-proxy (scripts/test-sandbox.sh launcher)")
def test_the_support_status_matches_what_each_levels_launcher_does_but_the_listed(tmp_path, monkeypatch):
    env = Env(tmp_path, monkeypatch)
    bare = path_without(tmp_path, "xdg-dbus-proxy")      # a system with bwrap alone
    wrong = set()
    for label, path in (("everything", os.environ["PATH"]), ("no xdg-dbus-proxy", bare)):
        monkeypatch.setenv("PATH", path)
        status = sb.support_status()["status"]
        for level in ("strict", "standard"):
            r = env.run(env.app(level, sb.resolve_template(level)), "echo RAN", env={"PATH": path})
            runs = r.returncode == 0 and "RAN" in r.stdout
            # what AppKata does with an app at this level, by the status: sandbox it, or run it Off
            if (status == "ok") != runs:
                wrong.add(f"{level.title()}, {label}" if label != "no xdg-dbus-proxy" else f"{level.title()}, no xdg-dbus-proxy")
    # bwrap alone runs both levels, Standard with no session bus, and the status says ok (R2-F12)
    assert wrong == {k for k in STILL_WRONG if k.startswith(("Strict,", "Standard,"))}, wrong
