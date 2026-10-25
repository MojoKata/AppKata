"""Adversarial strings at the sandbox's trust boundaries (round five, "Coverage after round five").

Three kinds of text reach the launcher and its helpers from outside AppKata: a review's `Sandbox
folders` line (remote text from a Trust), the arguments an app is started with (a file manager's
"Open with", `%U`, a command line) and file and app names. The property corpus checks well-formed
grant sets; these feed hostile ones -- spaces, quotes, newlines, globs, `--`, option-like words,
percent escapes, shell metacharacters -- and hold four invariants: the launcher stays valid shell,
it binds exactly the folders the grant set names and nothing else, `parse_folders` keeps every path
whole, and the file-argument helper hands every argument back unchanged when it has nothing to
export, through the same `eval "set -- $fwd"` the launcher uses.
"""

import os
import re
import shlex
import subprocess

import sys

import pytest

from appkata_core import sandbox as sb

pytestmark = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="the sandbox and its launchers are Linux-only (17.1)")


@pytest.fixture(autouse=True)
def _proxy_here(monkeypatch):
    """The launchers here are for a host with xdg-dbus-proxy, as every launcher tier is; one without
    it has its own tests (review 2, F12)."""
    monkeypatch.setattr(sb, "have_bus_filter", lambda: True)


HOSTILE = [
    "~/My Projects", "~/it's", '~/say "hi"', "~/semi;colon", "~/a&b", "~/dollar$HOME", "~/back`tick`",
    "~/glob*", "~/q?", "~/[set]", "~/--not-an-option", "~/-x", "~/new\nline", "~/tab\tbed", "~/perc%20ent",
    "~/unicode-ünïcødé", "~/paren(s)", "~/pipe|here", "~/redirect>out", "~/hash#tag", "~/tilde~2",
    "~/trailing/", "~/double//slash", "~/dot/./dot", "~/" + "x" * 200,
]
WORDS = HOSTILE + ["--ro-bind", "--", "-", "", " ", "file:///no/such/file", "file://evil/x", "https://x/y z",
                   "$(touch /tmp/pwned)", "`id`", "'", '"', "\\", "a\x00b"[:1] + "nul"]


def _bind_pairs(text: str) -> list[tuple[str, str]]:
    """Every `--bind-try X Y` / `--ro-bind-try X Y` word pair baked into the app's bwrap command,
    unquoted: the command runs from its `bwrap \\` line to the `"$@" || status=$?` word."""
    block = text[text.rindex("bwrap \\\n"):]
    block = block[:block.index('"$@" || status=$?')]
    words = shlex.split(block.replace("\\\n", " "), posix=True)
    return [(words[i + 1], words[i + 2]) for i, w in enumerate(words)
            if w in ("--bind-try", "--ro-bind-try", "--bind", "--ro-bind") and i + 2 < len(words)]


@pytest.mark.parametrize("path", HOSTILE, ids=[repr(p)[:20] for p in HOSTILE])
def test_a_hostile_folder_path_is_bound_whole_or_refused_and_the_launcher_stays_valid_shell(path, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "run"))
    for v in ("XDG_DATA_HOME", "APPKATA_APPS", "APPKATA_DATA"):
        monkeypatch.delenv(v, raising=False)
    gs = sb.apply_overrides(sb.resolve_template("standard"), {"folders": {"+" + path: "rw"}})
    text = sb.build_launcher("app", "App", str(tmp_path / "home/bin/apps/app/1"), "bin/app", gs,
                             apps_root=str(tmp_path / "home/bin/apps"))
    subprocess.run(["sh", "-n"], input=text, text=True, check=True)
    expanded = os.path.expanduser(path)
    refused = sb.protected_folder(path, str(tmp_path / "home/bin/apps"))
    home = str(tmp_path / "home")
    pairs = [(s, d) for s, d in _bind_pairs(text) if s.startswith(home)]      # the folder grants: under the fake home
    if refused:
        assert pairs == [] and "# Refused folder grant" in text
    else:
        assert pairs == [(expanded, expanded)], (path, pairs)      # one bind, source and destination whole
    assert all(s.startswith(("/", "$")) for s, _ in _bind_pairs(text)), _bind_pairs(text)   # never a relative source


# Review 2, F1: a folder named from neither / nor ~ -- a bare word, `run/user/1000`, `./x` -- was judged
# by protected_folder() against AppKata's own working directory, while bwrap resolves a bind source from
# the host's root. `Sandbox folders: home` therefore passed as "<cwd>/home" and bound the real /home over
# the private one (shown under bwrap 0.9: the app read ~/.ssh and wrote the real ~/.bashrc). The corpus
# above had only `~/` paths, and its pair filter looked only under the fake home, so it never saw one.
RELATIVE = ["home", "tmp", "run/user/1000", "Documents", "./Documents", "../..", "..", ".", "home/kata/.ssh",
            "~no-such-user-x/y", "etc", "media/usb"]


@pytest.mark.parametrize("path", RELATIVE, ids=[repr(p) for p in RELATIVE])
def test_a_folder_not_named_from_the_root_or_home_is_refused_and_never_bound(path, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "run"))
    for v in ("XDG_DATA_HOME", "APPKATA_APPS", "APPKATA_DATA"):
        monkeypatch.delenv(v, raising=False)
    monkeypatch.chdir(tmp_path)                                      # a working directory where "home" is no protected folder
    gs = sb.apply_overrides(sb.resolve_template("standard"), {"folders": {"+" + path: "rw"}})
    apps = str(tmp_path / "home/bin/apps")
    assert sb.protected_folder(path, apps), path                     # refused, with a reason
    text = sb.build_launcher("app", "App", apps + "/app/1", "bin/app", gs, apps_root=apps)
    assert all(path not in (s, d) for s, d in _bind_pairs(text)), _bind_pairs(text)
    assert "# Refused folder grant" in text
    chips = sb.summary(gs, apps)
    assert any(c.startswith(path + " · refused") for c in chips), chips
    kept, refused = sb.strip_protected(gs, apps)
    assert path not in kept["folders"] and [p for p, _ in refused] == [path]


def test_parse_folders_keeps_every_hostile_path_whole():
    for path in HOSTILE:
        if "," in path or "\n" in path:
            continue                                     # the line's own separators; a newline ends the line
        out = sb.parse_folders(f"+{path}:ro, -{path}, {path}")
        assert out == {f"+{path}": "ro", f"-{path}": None, path: "rw"}, (path, out)
    assert sb.parse_folders("~/a:RO,~/b:Rw, ,,") == {"~/a": "ro", "~/b": "rw"}


def test_every_argument_survives_the_forward_helper_and_the_launchers_eval(tmp_path):
    # The helper rewrites only an existing file outside the visible folders; everything else must
    # come back byte-for-byte through `eval "set -- $fwd"`, which is what the launcher runs on it.
    helper = tmp_path / "forward.py"
    helper.write_text(sb.FORWARD_HELPER)
    args = [w for w in WORDS if "\n" not in w]            # argv can carry a newline; $(...) strips a trailing one
    r = subprocess.run(["python3", str(helper), "io.appkata.app", str(tmp_path / "rt"), str(tmp_path), "--", *args],
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    fwd = r.stdout.rstrip("\n")
    back = subprocess.run(["sh", "-c", 'eval "set -- $1"; for a; do printf "%s\\0" "$a"; done', "sh", fwd],
                          capture_output=True, timeout=10)
    assert back.returncode == 0, back.stderr
    assert back.stdout.decode().split("\0")[:-1] == args
    # a word that is a real file in a visible folder keeps its path; an option-like file name too
    for name in ("--ro-bind", "-x", "it's a file", "glob*"):
        (tmp_path / name).write_text("x")
    r = subprocess.run(["python3", str(helper), "io.appkata.app", str(tmp_path / "rt"), str(tmp_path), "--",
                        *(str(tmp_path / n) for n in ("--ro-bind", "-x", "it's a file", "glob*"))],
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0 and shlex.split(r.stdout) == [str(tmp_path / n) for n in ("--ro-bind", "-x", "it's a file", "glob*")]


@pytest.mark.parametrize("name", ["My App", "it's", 'say "hi"', "a;b", "a&b", "$HOME", "`id`", "glob*", "--help", "-", "",
                                  "7zip", "ünïcødé", "a/b", "a\\b", "x" * 100])
def test_a_hostile_app_name_gives_a_valid_launcher_and_identity(name, tmp_path, monkeypatch):
    from appkata_core.install import slug
    monkeypatch.setattr(sb, "sandboxes_root", lambda: str(tmp_path / "sandboxes"))
    app_id = slug(name) or "app"
    assert re.fullmatch(r"[A-Za-z0-9._-]+", app_id), app_id
    ident = sb.app_identity(app_id)
    assert re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*(\.[A-Za-z_][A-Za-z0-9_-]*)+", ident), ident      # a valid bus name
    lp = sb.write_launcher(app_id, name, str(tmp_path / "apps"), str(tmp_path / f"apps/{app_id}/1"), "bin/app",
                           sb.resolve_template("online-app"))
    text = open(lp).read()
    subprocess.run(["sh", "-n"], input=text, text=True, check=True)
    assert f"--own={ident}" in text
    assert (shlex.quote(name) if name else "''") in text          # the name is quoted where the launcher prints it


def _run_launcher_with_a_stub_bwrap(text: str, tmp_path) -> subprocess.CompletedProcess:
    """Run a launcher's own shell -- the guard, the comments, the run-time words -- against a bwrap
    that only reports it was reached, so what the generated text does on the host is visible."""
    bindir = tmp_path / "stub"
    bindir.mkdir(exist_ok=True)
    (bindir / "bwrap").write_text("#!/bin/sh\necho BWRAP-REACHED\nexit 0\n")
    (bindir / "bwrap").chmod(0o755)
    lp = tmp_path / "run"
    lp.write_text(text)
    lp.chmod(0o755)
    return subprocess.run([str(lp)], env={"PATH": f"{bindir}:/usr/bin:/bin", "HOME": str(tmp_path / "home"),
                                          "XDG_RUNTIME_DIR": str(tmp_path / "run.d")}, capture_output=True, text=True, timeout=30)


@pytest.mark.parametrize("hostile", ["name", "refused-path"])
def test_text_from_outside_never_becomes_a_line_of_the_launcher(hostile, tmp_path, monkeypatch):
    # The launcher is generated shell. A name or a path is quoted wherever it is a word -- but a
    # comment is not a word, and a newline inside one ends the comment: whatever follows runs as the
    # user at every launch. The app's name comes from a Source's catalog; a refused folder's path
    # from a Trust's review line or the picker. Neither can carry a newline today (a Markdown line,
    # a GitHub name), which is why this is a harness, not a finding; the generator must not rely on it.
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "run.d"))
    for v in ("XDG_DATA_HOME", "APPKATA_APPS", "APPKATA_DATA"):
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setattr(sb, "sandboxes_root", lambda: str(tmp_path / "home/.local/share/appkata/sandboxes"))
    (tmp_path / "run.d").mkdir()
    name, gs = "Demo", sb.resolve_template("strict")
    if hostile == "name":
        name = "Demo\necho INJECTED-BY-NAME\n#"
    else:
        gs = sb.apply_overrides(sb.resolve_template("standard"), {"folders": {"+~/.ssh/keys\necho INJECTED-BY-PATH\n#": "ro"}})
        gs["level"] = "strict"                                         # no proxy to start: the stub bwrap is all it needs
        gs = sb.normalize(gs); gs["folders"] = {"~/.ssh/keys\necho INJECTED-BY-PATH\n#": "ro"}
    text = sb.build_launcher("demo", name, str(tmp_path / "home/bin/apps/demo/1"), "bin/demo", gs,
                             apps_root=str(tmp_path / "home/bin/apps"))
    r = _run_launcher_with_a_stub_bwrap(text, tmp_path)
    assert "INJECTED" not in r.stdout + r.stderr, (r.stdout, r.stderr)
    assert "BWRAP-REACHED" in r.stdout, (r.stdout, r.stderr)
