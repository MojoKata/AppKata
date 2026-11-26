"""Adversarial strings at the sandbox's trust boundaries (round five, "Coverage after round five").

Three kinds of text reach the launcher and its helpers from outside AppKata: a review's `Sandbox
folders` line (remote text from a Trust), the arguments an app is started with (a file manager's
"Open with", `%U`, a command line) and file and app names. The property corpus checks well-formed
grant sets; these feed hostile ones -- spaces, quotes, newlines, globs, `--`, option-like words,
percent escapes, shell metacharacters -- and hold four invariants: the launcher stays valid shell,
it binds exactly the folders the grant set names and nothing else, `parse_folders` keeps every path
whole, and the file-argument helper hands every argument back unchanged when it has nothing to
export, through the launcher's own lines that read its answer.

A fourth kind is the names of commands (CR1.5-31). A launcher runs a dozen host commands before and
around bwrap, as the user, outside every sandbox, and an app's command link is a command named by
the app's publisher: the launcher took whatever the PATH it was started with gave it for `python3`,
`readlink` or `mktemp`, and evaluated what the first of them printed. Two more invariants: nothing on
the caller's PATH is ever run, and what the helper prints is only ever read as arguments. The one
folder a launcher's PATH may hold beside the system's is that of a bwrap the system lacks, and never
one an app is.
"""

import json
import os
import re
import shlex
import shutil
import subprocess
import unicodedata

import sys

import pytest

from appkata_core import sandbox as sb

pytestmark = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="the sandbox and its launchers are Linux-only (R17.1)")


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
    # a control character (CR1.5-26): a NUL, which os.path.realpath() raises on, and the others; the
    # corpus had a newline and a tab alone, which were bound, and its one NUL was cut off (WORDS, below)
    "~/a\x00b", "\x00", "~/\x00", "/media/usb\x00/../../proc", "~/bell\x07", "~/esc\x1b[2J", "~/back\x08space", "~/del\x7f", "~/next\x85line", "~/cr\rlf",
]


def _marked(path: str) -> str:
    """`path` as it is kept and shown: the mark where each control character was (CR1.5-26)."""
    return "".join("\ufffd" if unicodedata.category(c) == "Cc" else c for c in path)


CONTROLS = [p for p in HOSTILE if p != _marked(p)]
# ...as arguments, which can hold no NUL: the kernel ends each at one
WORDS = [w for w in HOSTILE if "\x00" not in w] + ["--ro-bind", "--", "-", "", " ", "file:///no/such/file", "file://evil/x", "https://x/y z",
                   "$(touch /tmp/pwned)", "`id`", "'", '"', "\\", "a\x00b"[:1] + "nul"]


def _bwrap_words(text: str) -> list[str]:
    """The words of the app's bwrap command that the launcher's text holds, unquoted: each folder
    grant's, which it puts before "$@" at the launch while the grant stands (`[ F = "$g1" ] && set
    -- --bind-try F F "$@"`, the lines after the guard's; CR1.5-40: they were baked into the
    command), and the command's own, from its `bwrap \\` line to the `"$@" || status=$?` word."""
    grants = text[text.rindex('; do guard "$d"; done\n'):text.rindex("if [ \"$logging\" = 1 ]")].split("\n", 1)[1]
    block = text[text.rindex("bwrap \\\n"):]
    block = block[:block.index('"$@" || status=$?')]
    return shlex.split(grants, posix=True) + shlex.split(block.replace("\\\n", " "), posix=True)


def _bind_pairs(text: str) -> list[tuple[str, str]]:
    """Every `--bind-try X Y` / `--ro-bind-try X Y` word pair among them (_bwrap_words)."""
    words = _bwrap_words(text)
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
    expanded = os.path.expanduser(sb.folder_path(path))      # as a grant is named: no doubled slash, no `.` step, no slash last (CR1.5-16)
    refused = sb.protected_folder(path, str(tmp_path / "home/bin/apps"))
    home = str(tmp_path / "home")
    pairs = [(s, d) for s, d in _bind_pairs(text) if s.startswith(home)]      # the folder grants: under the fake home
    if path in CONTROLS:
        # refused whoever asks, kept and shown with a mark where the character was, and no check raises
        named, why = _marked(path), "not a full path (it has a control character in it, shown as \ufffd)"
        assert refused == sb.protected_folder(named) == why and sb.secret_folder(path) == sb.secret_folder(named) == sb.system_folder(path) == ""
        assert sb.folder_path(path) == named and list(gs["folders"]) == [named] and CONTROLS and "\ufffd" in named
        assert sb.strip_protected(gs)[1] == [(named, why)] and sb.strip_secrets(gs)[1] == []
        assert f"{named} · refused: {why}" in sb.summary(gs) and f"# Refused folder grant {' '.join(named.split())}: {why} (R17.3.1).\n" in text
        assert sb.changes(sb.resolve_template("standard"), gs)[0] == [named + " (read-write)"] and named in json.dumps(sb.to_json(gs), ensure_ascii=False)
        assert sb.parse_folders(f"+{path}:ro, ~/Notes") == {f"+{named}": "ro", "~/Notes": "rw"}     # ...from the line's own reading on
    if "\n" not in path:
        assert not [c for c in text if unicodedata.category(c) == "Cc" and c != "\n"], path      # nothing of it in the launcher's text
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


# CR1.5-5 (#380): a system place was an ordinary folder to the never-shared check, so a review's
# `Sandbox folders: /proc:ro` was bound as asked, after the sandbox's own /proc, and over it. The
# corpora above name folders from `~` or from nowhere; none named a place outside the home. These
# are the system's own places (sb.SYSTEM_PLACES), what an app would want inside them, a folder above
# two of them, and each written the ways a line can write a path: all refused, none ever a bind.
SYSTEM = ["/proc", "/proc/1/environ", "/proc/self/root", "/proc/self/cwd", "/sys", "/dev", "/dev/shm", "/run", "/run/dbus/system_bus_socket",
          "/run/docker.sock", "/run/user", "/var/run", "/var/run/docker.sock", "/var", "/tmp", "/tmp/.X11-unix", "/tmp/ssh-XXXXab12cd/agent.4242",
          "/var/tmp", "/etc", "/etc/passwd", "/usr", "/usr/lib", "/boot", "//proc", "/proc/", "/./proc", "/proc/.", "/tmp//", "/mnt/../proc",
          "/run/media/../docker.sock", "/usr/../tmp", "/dev/shm/my folder", "/tmp/it's", "/tmp/new\nline", "/tmp/$(id)"]


@pytest.mark.parametrize("path", SYSTEM, ids=[repr(p) for p in SYSTEM])
def test_a_system_place_is_refused_and_never_bound_however_it_is_written(path, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", "/home/kata")                        # where a user's home is: /tmp is not above it
    monkeypatch.setenv("XDG_RUNTIME_DIR", "/run/user/1000")
    for v in ("XDG_DATA_HOME", "XDG_STATE_HOME", "APPKATA_APPS", "APPKATA_DATA", "APPKATA_LOG_DIR", "DBUS_SESSION_BUS_ADDRESS"):
        monkeypatch.delenv(v, raising=False)
    monkeypatch.chdir(tmp_path)
    apps = "/home/kata/bin/apps"
    for mode in ("rw", "ro"):
        gs = sb.apply_overrides(sb.resolve_template("standard"), {"folders": {"+" + path: mode, "+/media/usb": mode}})
        assert sb.protected_folder(path, apps), path                 # refused, with a reason
        text = sb.build_launcher("app", "App", apps + "/app/1", "bin/app", gs, apps_root=apps)
        subprocess.run(["sh", "-n"], input=text, text=True, check=True)
        words = _bwrap_words(text)
        grants = [(words[i + 1], words[i + 2]) for i, w in enumerate(words) if w in ("--bind-try", "--ro-bind-try")]
        assert ("/media/usb", "/media/usb") in grants               # the folder beside it, as asked
        mine = {path, os.path.normpath(path), os.path.realpath(path)}
        assert not [g for g in grants if set(g) & mine], grants     # and this one never, by any of its names
        assert "# Refused folder grant" in text
        chips = sb.summary(gs, apps)
        named = sb.folder_path(path)                                # `//proc` and `/proc/` are named /proc (CR1.5-16)
        assert any(c.startswith(named + " · refused") for c in chips), chips
        kept, refused = sb.strip_protected(gs, apps)
        assert not {path, named} & set(kept["folders"]) and [p for p, _ in refused] == [named]


# CR1.5-9 (#384): places in the home that code runs from later, which the never-shared list had not
# heard of (Cinnamon's folders, bash-completion's files, a window manager's configuration, an
# editor's extensions, Cargo's and Go's programs), each written the ways a line can write a path, with
# what is inside it and above it: all refused, none ever a bind, and the folder beside it as asked.
LATER = ["~/.local/share/cinnamon", "~/.local/share/cinnamon/applets", "~/.local/share/cinnamon/extensions/", "~//.local/share/cinnamon/desklets",
         "/home/kata/.local/share/cinnamon/search_providers", "~/.cinnamon", "~/.cinnamon/panel-launchers/x.desktop", "~/.bash_completion",
         "/home/kata/.bash_completion", "~/.config/bash_completion", "~/.local/share/bash-completion", "~/.local/share/bash-completion/completions/git",
         "~/.xinputrc", "~/.config/sway", "~/.config/sway/config", "~/.sway", "~/.config/i3", "~/.i3/config", "~/.config/hypr/hyprland.conf",
         "~/.config/labwc/autostart", "~/.config/openbox", "~/.config/river/init", "~/.config/niri", "~/.config/wayfire.ini",
         "~/.config/pipewire", "~/.config/pipewire/pipewire.conf.d/x.conf", "~/.vscode/extensions", "~/.vscode", "~/./.vscode/extensions/a.b-1.0",
         "~/.vscode-oss/extensions", "~/.cargo/bin", "~/.cargo", "~/.cargo/bin/cargo", "~/go/bin", "~/go", "~/Notes/../go/bin",
         "~/.config/sway/it's", "~/.cargo/bin/new\nline", "~/go/bin/$(id)",
         # the desktop's settings database and the file xdg-user-dir runs as shell (pr-review pass 1 of #735, P1-2)
         "~/.config/dconf", "~/.config/dconf/", "~/.config/dconf/user", "/home/kata/.config/dconf", "~//.config/dconf/user",
         "~/.config/user-dirs.dirs", "/home/kata/.config/user-dirs.dirs", "~/Notes/../.config/user-dirs.dirs", "~/.config/./dconf",
         # more of them, each found by pr-review pass 2 of #735: the user's own menu files (P2-1)
         "~/.config/menus", "~/.config/menus/", "~/.config/menus/applications-merged", "/home/kata/.config/menus/cinnamon-applications-merged/x.menu",
         "~//.config/menus", "~/Notes/../.config/menus/cinnamon-applications.menu"]


@pytest.mark.parametrize("path", LATER, ids=[repr(p) for p in LATER])
def test_a_place_code_runs_from_later_is_refused_and_never_bound_however_it_is_written(path, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", "/home/kata")
    monkeypatch.setenv("XDG_RUNTIME_DIR", "/run/user/1000")
    for v in ("XDG_DATA_HOME", "XDG_CONFIG_HOME", "XDG_STATE_HOME", "APPKATA_APPS", "APPKATA_DATA", "APPKATA_LOG_DIR", "DBUS_SESSION_BUS_ADDRESS"):
        monkeypatch.delenv(v, raising=False)
    monkeypatch.chdir(tmp_path)
    apps = "/home/kata/bin/apps"
    for mode in ("rw", "ro"):
        gs = sb.apply_overrides(sb.resolve_template("standard"), {"folders": {"+" + path: mode, "+~/Notes": mode}})
        assert sb.protected_folder(path, apps), path                 # refused, with a reason
        text = sb.build_launcher("app", "App", apps + "/app/1", "bin/app", gs, apps_root=apps)
        subprocess.run(["sh", "-n"], input=text, text=True, check=True)
        words = _bwrap_words(text)
        grants = [(words[i + 1], words[i + 2]) for i, w in enumerate(words) if w in ("--bind-try", "--ro-bind-try")]
        assert ("/home/kata/Notes", "/home/kata/Notes") in grants   # the folder beside it, as asked
        full = os.path.expanduser(path)
        mine = {full, os.path.normpath(full), os.path.realpath(full)}
        assert not [g for g in grants if set(g) & mine], grants     # and this one never, by any of its names
        assert "# Refused folder grant" in text
        named = sb.folder_path(path)
        assert any(c.startswith(named + " · refused") for c in sb.summary(gs, apps)), sb.summary(gs, apps)
        kept, refused = sb.strip_protected(gs, apps)
        assert set(kept["folders"]) == {"~/Notes"} and [p for p, _ in refused] == [named]


# CR1.5-45 (#701): another folder AppKata has apps in (the install folder before Settings changed),
# written the ways a line can write it, with what an app would want of it: the other app's program
# and launcher. An app was told of its own install folder alone; all refused now, none ever a bind.
OTHER_ROOT = ["~/OldApps", "~/OldApps/", "~//OldApps", "/home/kata/OldApps", "~/OldApps/victim", "~/OldApps/victim/run", "~/OldApps/victim/1.0/bin/victim",
              "~/./OldApps/victim/", "~/Notes/../OldApps/victim", "~/OldApps/it's", "~/OldApps/$(id)", "~/OldApps/a b/run"]


@pytest.mark.parametrize("path", OTHER_ROOT, ids=[repr(p) for p in OTHER_ROOT])
def test_another_folder_apps_are_installed_in_is_refused_and_never_bound_however_it_is_written(path, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", "/home/kata")
    monkeypatch.setenv("XDG_RUNTIME_DIR", "/run/user/1000")
    for v in ("XDG_DATA_HOME", "XDG_CONFIG_HOME", "XDG_STATE_HOME", "APPKATA_APPS", "APPKATA_DATA", "APPKATA_LOG_DIR", "DBUS_SESSION_BUS_ADDRESS"):
        monkeypatch.delenv(v, raising=False)
    monkeypatch.chdir(tmp_path)
    apps, own = "/home/kata/Apps", sb.Own(roots=("/home/kata/Apps", "/home/kata/OldApps"))
    for mode in ("rw", "ro"):
        gs = sb.apply_overrides(sb.resolve_template("standard"), {"folders": {"+" + path: mode, "+~/Notes": mode}})
        assert sb.protected_folder(path, apps, own) == "AppKata's installed apps", path
        text = sb.build_launcher("app", "App", apps + "/app/1", "bin/app", gs, apps_root=apps, own=own)
        subprocess.run(["sh", "-n"], input=text, text=True, check=True)
        words = _bwrap_words(text)
        grants = [(words[i + 1], words[i + 2]) for i, w in enumerate(words) if w in ("--bind-try", "--ro-bind-try")]
        assert ("/home/kata/Notes", "/home/kata/Notes") in grants   # the folder beside it, as asked
        assert not [g for g in grants if any("/OldApps" in w for w in g)], grants      # and nothing of the other apps'
        named = sb.folder_path(path)
        assert any(c.startswith(named + " · refused") for c in sb.summary(gs, apps, own=own))
        kept, refused = sb.strip_protected(gs, apps, own)
        assert set(kept["folders"]) == {"~/Notes"} and [p for p, _ in refused] == [named]


def test_parse_folders_keeps_every_hostile_path_whole():
    for path in HOSTILE:
        if "," in path:
            continue                                     # the line's own separator
        out = sb.parse_folders(f"+{path}:ro, -{path}, {path}")
        kept = _marked(path)                             # whole, but a control character: a mark stands where one was (CR1.5-26)
        assert out == {f"+{kept}": "ro", f"-{kept}": None, kept: "rw"} and (kept == path) is (path not in CONTROLS), (path, out)
    assert sb.parse_folders("~/a:RO,~/b:Rw, ,,") == {"~/a": "ro", "~/b": "rw"}


def _through_the_launchers_own_lines(helper, args, tmp_path, visible=()):
    """The launcher's own file-argument lines (sb._FORWARD_BLOCK, as build_launcher fills them in),
    run by sh over `args` with `helper` as the helper; returns the arguments the app would get."""
    block = sb._FORWARD_BLOCK.format(helper=shlex.quote(str(helper)), incwd='""', visible=" ".join(shlex.quote(str(v)) for v in visible),
                                     never=shlex.quote(str(tmp_path / "never-shared")), name="App")
    script = f"id=io.appkata.app; rt={shlex.quote(str(tmp_path / 'rt'))}\n{block}" + 'for a; do printf "%s\\0" "$a"; done\n'
    r = subprocess.run(["sh", "-euc", script, "sh", *args], capture_output=True, timeout=30,
                       env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)})
    assert r.returncode == 0, r.stderr
    return r.stdout.decode().split("\0")[:-1], r.stderr.decode()


def test_every_argument_survives_the_forward_helper_and_the_launchers_reading_of_it(tmp_path):
    # The helper rewrites only an existing file outside the visible folders; everything else must
    # come back byte for byte through the lines the launcher reads its answer with. An argument
    # with a line break in it comes back too, which `eval "set -- $(...)"` never managed at the end
    # of the last one.
    helper = tmp_path / "forward.py"
    helper.write_text(sb.FORWARD_HELPER)
    args = WORDS + ["trailing\n", "\n", "\\n", "back\\slash\\\\", "=", "=x", "\\c", "a\\0101b", "%s", "x; echo ESCAPED >&2"]
    back, err = _through_the_launchers_own_lines(helper, args, tmp_path, visible=[tmp_path])
    assert back == args and err == ""
    # a word that is a real file in a visible folder keeps its path; an option-like file name too
    for name in ("--ro-bind", "-x", "it's a file", "glob*", "new\nline"):
        (tmp_path / name).write_text("x")
    files = [str(tmp_path / n) for n in ("--ro-bind", "-x", "it's a file", "glob*", "new\nline")]
    assert _through_the_launchers_own_lines(helper, files, tmp_path, visible=[tmp_path]) == (files, "")


HOSTILE_ANSWERS = [
    "x; echo ESCAPED >&2",                                         # the finding's own: evaluated, it ran
    "=$(echo ESCAPED >&2)\n=`echo ESCAPED >&2`",                   # the right shape, shell inside
    "='; echo ESCAPED >&2; '\n=\"; echo ESCAPED >&2; \"",
    "=a\nEOF\necho ESCAPED >&2\n=b",                              # the end of the here-document it is read from
    "=\\c\n=\\0101\\x41%s%n",                                     # printf's own escapes
    "", "=", "=one", "=one\n=two\n=three", "\x00=one\n=two",
]


@pytest.mark.parametrize("answer", HOSTILE_ANSWERS, ids=[repr(a)[:24] for a in HOSTILE_ANSWERS])
def test_whatever_the_helper_prints_is_read_as_arguments_and_never_run(answer, tmp_path):
    # CR1.5-31: `eval "set -- $fwd"` ran the helper's answer as shell, on the host, as the user. The
    # helper is AppKata's own file, but whatever answered to `python3` wrote the answer, and nothing
    # held the launcher to reading it. The class is every answer, so the helper here is hostile: its
    # answer may become arguments (when it holds as many as were given) and nothing else.
    helper = tmp_path / "hostile.py"
    helper.write_text(f"import sys\nsys.stdout.buffer.write({answer.encode()!r})\n")
    back, err = _through_the_launchers_own_lines(helper, ["one", "two"], tmp_path)
    assert "ESCAPED" not in err and len(back) == 2, (back, err)
    assert back == ["one", "two"] or answer.count("\n=") == 1 and answer.startswith("="), back


def test_a_line_of_the_answer_that_says_why_is_printed_as_text_and_is_no_argument(tmp_path):
    # ...and a line with "!" first is why an argument was not handed over (CR1.5-38): printed after
    # the app's name on stderr, as text (no format, no shell, no escape read), and counted as no
    # argument; a line that is neither is nothing. R17.4 says so, and no hostile answer above had one.
    ran = tmp_path / "ran"
    why = f"%s%n\\c\\0101 $(touch {ran}) `touch {ran}`; touch {ran} 'x' \"y\""
    helper = tmp_path / "hostile.py"
    answer = ("!" + why + "\n=one\njunk\n!second\n=two\n").encode()
    helper.write_text(f"import sys\nsys.stdout.buffer.write({answer!r})\n")
    back, err = _through_the_launchers_own_lines(helper, ["a", "b"], tmp_path)
    assert back == ["one", "two"] and err == f"App {why}\nApp second\n" and not ran.exists(), (back, err)
    helper.write_text("import sys\nsys.stdout.write('!x\\n!y\\n')\n")           # two lines that say why are not two arguments
    assert _through_the_launchers_own_lines(helper, ["a", "b"], tmp_path) == (["a", "b"], "")


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


def _stub_bwrap(tmp_path) -> str:
    """A folder whose bwrap only reports it was reached (and, asked to unpack an AppImage, leaves
    the folder the launcher expects), so what the generated text does on the host is visible. It is
    given to build_launcher as the first of the machine's command folders (`path`): a launcher takes
    its commands from there and nowhere else (CR1.5-31)."""
    bindir = tmp_path / "stub"
    bindir.mkdir(exist_ok=True)
    (bindir / "bwrap").write_text('#!/bin/sh\necho BWRAP-REACHED\nprev=\n'
                                  'case " $* " in *" --appimage-extract "*)\n'
                                  '  for a; do if [ "$prev" = --chdir ]; then mkdir "$a/squashfs-root"; fi; prev=$a; done ;;\nesac\nexit 0\n')
    (bindir / "bwrap").chmod(0o755)
    return str(bindir)


def _run_launcher(text: str, tmp_path, *args, path: str | None = None) -> subprocess.CompletedProcess:
    """Run a launcher's own shell -- the guard, the comments, the run-time words -- started with
    `path` as its caller's PATH."""
    lp = tmp_path / "run"
    lp.write_text(text)
    lp.chmod(0o755)
    return subprocess.run([str(lp), *args], env={"PATH": path or "/usr/bin:/bin", "HOME": str(tmp_path / "home"),
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
                             apps_root=str(tmp_path / "home/bin/apps"), path=f"{_stub_bwrap(tmp_path)}:{sb.HOST_PATH}")
    r = _run_launcher(text, tmp_path)
    assert "INJECTED" not in r.stdout + r.stderr, (r.stdout, r.stderr)
    assert "BWRAP-REACHED" in r.stdout, (r.stdout, r.stderr)


# The launchers the next two tests run: one for each stretch of host-side shell a grant set can add.
# Standard ones are built for a host without xdg-dbus-proxy, so no proxy has to answer.
def _launchers(tmp_path, monkeypatch, path: str) -> dict:
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "run.d"))
    for v in ("XDG_DATA_HOME", "XDG_STATE_HOME", "APPKATA_APPS", "APPKATA_DATA", "APPKATA_LOG_DIR"):
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setattr(sb, "sandboxes_root", lambda: str(home / ".local/share/appkata/sandboxes"))
    (tmp_path / "run.d").mkdir()
    apps = home / "bin/apps"
    (apps / "demo").mkdir(parents=True)
    img = apps / "demo" / "Demo-1.AppImage"
    img.write_bytes(b"\x7fELF")
    helper = sb.write_forward_helper()
    common = dict(apps_root=str(apps), forward=helper, shims=sb.shims_dir(), bus_filter=False, path=path)
    build = lambda gs, **kw: sb.build_launcher("demo", "Demo", str(apps / "demo/1"), "bin/demo", gs, **common, **kw)   # noqa: E731
    return {
        "strict": build(sb.resolve_template("strict")),
        "standard-network": build(sb.resolve_template("online-app")),
        "cli-tool": build(sb.resolve_template("cli-tool")),
        "no-inner-sandbox": build(sb.resolve_template("standard"), inner_sandbox=False),
        "appimage": sb.build_launcher("demo", "Demo", str(apps / "demo/1.extracted"), "AppRun", sb.resolve_template("online-app"),
                                      str(img), **common),
    }


LAUNCHERS = ["strict", "standard-network", "cli-tool", "no-inner-sandbox", "appimage"]


@pytest.mark.parametrize("which", LAUNCHERS)
@pytest.mark.parametrize("menu", [False, True], ids=["command", "menu"])
def test_nothing_on_the_callers_path_is_ever_run_by_a_launcher(which, menu, tmp_path, monkeypatch):
    # CR1.5-31 (High): the launcher set no PATH, so each host command it runs by name -- python3,
    # readlink, mktemp, stat, bwrap itself -- was whatever came first on the PATH of whoever started
    # it. On Ubuntu, Debian and Mint ~/bin comes first once it exists, and that is where AppKata
    # puts a command link named after each app: an app named python3 answered the helper's call, and
    # its output was evaluated; one named readlink chose a file to bind into another app; one named
    # mktemp chose the folder a launcher then removes. How it slipped past: every test that ran a
    # launcher gave it a PATH of its own choosing, with a stand-in bwrap first, so "the caller's
    # PATH decides" was the harness itself. The class, then: a stand-in first on the caller's PATH
    # for every command name this machine has, and none of them may run.
    farm, ran = tmp_path / "callers-bin", tmp_path / "ran.log"
    farm.mkdir()
    (tmp_path / "standin").write_text(f'#!/bin/sh\necho "$0" >> {shlex.quote(str(ran))}\necho "x; echo ESCAPED >&2"\nexit 0\n')
    (tmp_path / "standin").chmod(0o755)
    names = set(sb.HOST_COMMANDS) | {"sh", "env"}
    for d in sb.HOST_PATH.split(":"):
        names.update(os.listdir(d) if os.path.isdir(d) else ())
    for n in names:
        os.symlink(tmp_path / "standin", farm / n)
    text = _launchers(tmp_path, monkeypatch, f"{_stub_bwrap(tmp_path)}:{sb.HOST_PATH}")[which]
    assert text.splitlines()[2] == "set -eu" and text.splitlines()[5].startswith("PATH=")      # before its first command
    r = _run_launcher(text, tmp_path, *(["--appkata-menu"] if menu else []), "an argument", str(tmp_path / "standin"),
                      path=f"{farm}:/usr/bin:/bin")
    assert not ran.exists(), ran.read_text()
    assert "ESCAPED" not in r.stdout + r.stderr and "BWRAP-REACHED" in r.stdout and r.returncode == 0, (r.stdout, r.stderr)


@pytest.mark.parametrize("which", LAUNCHERS)
@pytest.mark.parametrize("menu", [False, True], ids=["command", "menu"])
def test_a_launcher_runs_no_host_command_but_the_listed_ones(which, menu, tmp_path, monkeypatch):
    # sandbox.HOST_COMMANDS is the list no command link may be named after (install.RESERVED_COMMANDS),
    # so it has to be whole: on a machine whose command folders hold those names and no other, every
    # stretch of the launcher's shell still gets to bwrap. A command added to the launcher and not to
    # the list stops here with "not found".
    only = tmp_path / "only"
    only.mkdir()
    for n in sb.HOST_COMMANDS:
        real = shutil.which(n, path=sb.HOST_PATH)
        if real and n != "bwrap":
            os.symlink(real, only / n)
    os.symlink(os.path.join(_stub_bwrap(tmp_path), "bwrap"), only / "bwrap")
    text = _launchers(tmp_path, monkeypatch, str(only))[which]
    r = _run_launcher(text, tmp_path, *(["--appkata-menu"] if menu else []), "an argument", str(tmp_path / "only"))
    log = tmp_path / "home/.local/state/appkata/apps/demo.log"
    said = r.stderr + (log.read_text() if log.exists() else "")
    assert r.returncode == 0 and "BWRAP-REACHED" in r.stdout and "not found" not in said, (r.stdout, said)


# A bwrap the system's folders lack (sandbox.host_path): the launcher takes its commands from those
# folders alone, and AppKata finds a bwrap on its own PATH too, so a bwrap the user built or
# installed with a package manager of their own has its folder added after them. What AppKata says
# of bwrap is said of that one (sandbox.host_which).
def _system_without_bwrap(tmp_path, monkeypatch) -> str:
    """A machine whose command folders (sandbox.HOST_PATH, here one folder) hold every command a
    launcher runs but bwrap, with a home; returns that folder."""
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "run.d"))
    for v in ("XDG_DATA_HOME", "XDG_STATE_HOME", "APPKATA_APPS", "APPKATA_DATA", "APPKATA_LOG_DIR"):
        monkeypatch.delenv(v, raising=False)
    (tmp_path / "run.d").mkdir()
    system = tmp_path / "system"
    system.mkdir()
    for n in sb.HOST_COMMANDS:
        real = shutil.which(n, path=sb.HOST_PATH)
        if real and n != "bwrap":
            os.symlink(real, system / n)
    monkeypatch.setattr(sb, "HOST_PATH", str(system))
    return str(system)


def _program(path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\nexit 0\n")
    path.chmod(0o755)


# Where AppKata's own PATH finds a bwrap the system's folders lack, under the test's folder: the bwrap,
# what it is a link to (or None), the entry of AppKata's PATH that finds it, and the folder a
# launcher's PATH gains after the system's (None: none, since that bwrap is an app).
FOUND_BWRAP = {
    "installed-in-local-bin": ("home/.local/bin/bwrap", None, "{tmp}/home/.local/bin", "home/.local/bin"),
    "a-link-to-a-build": ("home/.local/bin/bwrap", "home/src/bubblewrap/_build/bwrap-0.11", "{tmp}/home/.local/bin",
                          "home/.local/bin"),
    "by-a-relative-entry": ("tools/bwrap", None, "tools", "tools"),
    "named-like-the-install-folder": ("home/bin/apps-tools/bwrap", None, "{tmp}/home/bin/apps-tools", "home/bin/apps-tools"),
    "an-apps-command-link": ("home/bin/bwrap", "home/bin/apps/demo/run", "{tmp}/home/bin", None),
    "in-the-install-folder": ("home/bin/apps/demo/1/bin/bwrap", None, "{tmp}/home/bin/apps/demo/1/bin", None),
    "in-a-private-home": ("home/.local/share/appkata/sandboxes/demo/bin/bwrap", None,
                          "{tmp}/home/.local/share/appkata/sandboxes/demo/bin", None),
    "a-link-into-a-private-home": ("home/.local/bin/bwrap", "home/.local/share/appkata/sandboxes/demo/.local/bin/bwrap",
                                   "{tmp}/home/.local/bin", None),
}


@pytest.mark.parametrize("case", FOUND_BWRAP)
def test_a_launchers_path_gains_the_folder_of_a_bwrap_the_system_lacks_unless_that_bwrap_is_an_app(case, tmp_path, monkeypatch):
    # The folder comes after the system's, so it decides bwrap and nothing the system has. It is the
    # folder AppKata found the name in, not where a link leads (the launcher runs `bwrap` by name),
    # and absolute: a relative one would be looked up from wherever the launcher is started. Never
    # when that bwrap is an app -- a file in the install folder or in a private home, or a link into
    # one, as an app's command link named bwrap is -- which would run as the user, outside every
    # sandbox, at each start of every app; a folder whose name only begins like the install
    # folder's isn't in it. And once the system's folders have a bwrap, nothing joins them.
    tmp = tmp_path.resolve()
    system = _system_without_bwrap(tmp, monkeypatch)
    where, target, entry, gains = FOUND_BWRAP[case]
    _program(tmp / (target or where))
    if target:
        (tmp / where).parent.mkdir(parents=True, exist_ok=True)
        (tmp / where).symlink_to(tmp / target)
    monkeypatch.chdir(tmp)
    monkeypatch.setenv("PATH", f"{entry.format(tmp=tmp)}:{system}")    # AppKata's own, a login's: the user's folder first
    apps = str(tmp / "home/bin/apps")
    assert sb.host_path(apps) == (f"{system}:{tmp / gains}" if gains else system)
    assert sb.have_tools() is bool(gains)          # AppKata says bwrap is here exactly where a launcher reaches one
    _program(tmp / "system/bwrap")
    assert sb.host_path(apps) == system and sb.have_tools()


def test_a_folder_whose_name_holds_a_colon_never_joins_a_launchers_path(tmp_path, monkeypatch):
    # A PATH splits at every colon, so such a folder can't be one of its entries: written into the
    # launcher's PATH line it would be read as two folders, neither of them the one AppKata found, the
    # second relative to wherever the launcher is started. AppKata finds a bwrap there only through
    # a relative entry of its own PATH, from inside it; the launcher keeps the system's folders alone,
    # and says bwrap isn't installed (test_sandbox.py, test_a_launcher_says_plainly_when_bwrap_is_missing),
    # as AppKata does.
    tmp = tmp_path.resolve()
    system = _system_without_bwrap(tmp, monkeypatch)
    _program(tmp / "a:b/bwrap")
    monkeypatch.chdir(tmp / "a:b")
    monkeypatch.setenv("PATH", f".:{system}")
    assert sb.host_path(str(tmp / "home/bin/apps")) == system
    assert not sb.have_tools() and "bubblewrap" in sb.missing_tools()


@pytest.mark.parametrize("menu", [False, True], ids=["command", "menu"])
def test_a_launcher_reaches_the_bwrap_appkata_found_outside_the_systems_folders(menu, tmp_path, monkeypatch):
    # What the folder is for: AppKata found a bwrap and says the sandbox works, so an app installed
    # sandboxed has to start, from the app menu too, whose PATH has no ~/.local/bin. A launcher with
    # the system's folders alone would stop at "bwrap isn't installed" there.
    tmp = tmp_path.resolve()
    system = _system_without_bwrap(tmp, monkeypatch)
    own = tmp / "home/.local/bin"
    own.mkdir(parents=True)
    (own / "bwrap").symlink_to(os.path.join(_stub_bwrap(tmp), "bwrap"))
    monkeypatch.setenv("PATH", f"{own}:{system}")
    monkeypatch.setattr(sb, "nested_userns_works", lambda refresh=False: True)    # its probe would run the stand-in
    apps = tmp / "home/bin/apps"
    lp = sb.write_launcher("demo", "Demo", str(apps), str(apps / "demo/1"), "bin/demo", sb.resolve_template("strict"))
    with open(lp) as f:
        text = f.read()
    assert f"\nPATH={shlex.quote(f'{system}:{own}')}; export PATH\n" in text
    r = _run_launcher(text, tmp, *(["--appkata-menu"] if menu else []), "an argument", path="/usr/bin:/bin")
    log = tmp / "home/.local/state/appkata/apps/demo.log"
    said = r.stderr + (log.read_text() if log.exists() else "")
    assert r.returncode == 0 and "BWRAP-REACHED" in r.stdout and "not found" not in said, (r.stdout, said)


@pytest.mark.parametrize("found", ["the system's and the user's", "the user's alone"])
def test_appkata_asks_about_the_very_bwrap_a_launcher_runs(found, tmp_path, monkeypatch):
    # #689's review, P1-4: a launcher runs the bwrap of the system's folders whenever they hold one
    # (host_path), and everything AppKata decides about bwrap asked its own PATH, where a login's
    # ~/.local/bin comes first: the AppArmor profile's attachment (R17.10), the probe that says the
    # sandbox works, the one that decides an app's own sandbox gets --no-sandbox, and whether bwrap
    # is here at all. With a newer bwrap of the user's there on Ubuntu 24.04 the setup profiled it,
    # the probe passed on it, and every launcher ran /usr/bin/bwrap, which no profile covered: no
    # sandboxed app started. The AppImage kind probe ran it too. Here each stand-in says where it
    # ran from, and every answer has to be about the bwrap a launcher runs.
    tmp = tmp_path.resolve()
    system = _system_without_bwrap(tmp, monkeypatch)
    own, ran = tmp / "home/.local/bin", tmp / "ran.log"

    def standin(path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f'#!/bin/sh\necho "$0 $*" >> {shlex.quote(str(ran))}\nexit 0\n')
        path.chmod(0o755)
    standin(own / "bwrap")
    both = found == "the system's and the user's"
    if both:
        standin(tmp / "system" / "bwrap")
    # AppKata's own PATH, a login's: the user's folder first; /usr/bin after, for unshare, which the
    # inner-sandbox probe runs inside bwrap by its path
    monkeypatch.setenv("PATH", f"{own}:{system}:/usr/bin")
    monkeypatch.setattr(sb, "_userns_cache", None)
    monkeypatch.setattr(sb, "_nested_cache", None)
    runs = str(tmp / "system" / "bwrap") if both else str(own / "bwrap")
    launchers = sb.host_path(str(tmp / "home/bin/apps"))
    assert shutil.which("bwrap", path=launchers) == runs                    # what every launcher runs
    assert sb.bwrap_path() == runs and f"profile appkata-sandbox {runs} flags=" in sb.profile_text()     # the profile names it
    assert sb.setup_command()[-1] == runs                                     # and the setup probes it, as the user
    assert sb.have_tools() and "bubblewrap" not in sb.missing_tools()
    assert sb.userns_works(refresh=True) and sb.nested_userns_works(refresh=True)
    from appkata_core import appkind
    (tmp / "Demo.AppImage").write_text("x")
    assert appkind.kind_of_appimage(str(tmp / "Demo.AppImage")) is None        # what an AppImage is: its runtime, run in bwrap
    probed = ran.read_text().splitlines()
    assert {line.split()[0] for line in probed} == {runs}, probed                  # every probe ran it, and no other
    assert any("--unshare-user" in line for line in probed) and any("--appimage-extract" in line for line in probed)
    assert any("--map-root-user" in line for line in probed) is bool(shutil.which("unshare", path="/usr/bin")), probed


def test_what_appkata_says_of_bwrap_is_about_the_install_folder_a_launcher_is_written_for(tmp_path, monkeypatch):
    # #689's review, P2-B3: a launcher's PATH leaves out a bwrap in its app's install folder (host_path:
    # that is an app), and AppKata's answers about bwrap -- whether it is here, the probe that says
    # the sandbox works -- were asked with the default install folder, whatever Settings named. With
    # no bwrap in the system's folders, the user's own in ~/bin and the install folder set to ~/bin,
    # Settings said the sandbox works, an install there was sandboxed, and its launcher stopped at
    # "bubblewrap (bwrap) isn't installed". What AppKata says and decides for the system is asked of
    # a launcher in the install folder Settings names, and for an installed app of its own launcher:
    # where that finds no bwrap, bubblewrap is missing, as on a system without one.
    be, home, URL = _a_backend_with_the_users_bwrap_in_bin(tmp_path, monkeypatch)
    bwrap_here = {home / "bin" / "apps": True, home / "bin": False}          # the default install folder, and the bwrap's own
    for folder, runs in bwrap_here.items():                                  # Settings → Sandbox, and a new install
        be.setPref("installDir", str(folder))
        assert (shutil.which("bwrap", path=sb.host_path(str(folder))) is not None) is runs     # what a launcher there finds
        st = be.sandboxSupport
        assert (st["status"], "bubblewrap" in st["missing"]) == (("ok", False) if runs else ("unsupported", True)), st
        assert (be._sandbox_for_install(URL) is not None) is runs            # sandboxed only where its launcher starts
    be.setPref("installDir", str(home / "bin" / "apps"))
    be.setPref("commandLinks", False)                                        # ~/bin/demo is the second app's folder
    be._app = lambda url: {"url": URL, "name": "Demo", "installed": "1.0"}
    for root, runs in bwrap_here.items():                                    # an app installed there before
        target = _installed_off_in(be, URL, root)
        support = be.sandboxInfo(URL)["support"]                             # its App Detail
        assert (support["status"] == "ok") is runs and ("bubblewrap" in support["appToolsHint"]) is not runs, support
        note = be.sandboxInfo(URL)["notYet"]                                 # and its dialogs, beside a sandboxed choice (P4-B7)
        assert (note == "") is runs and ("until then: bubblewrap isn't installed" in note) is not runs, note
        assert be._heal_launchers() == ([URL] if runs else [])               # AppKata's start sandboxes it where it can start
        rec = json.loads(be.db.one("SELECT record FROM installs WHERE url=?", (URL,))["record"])
        assert (rec.get("launcher") == str(target / "run")) is runs and os.path.exists(target / "run") is runs, rec
        be.db.x("DELETE FROM installs")


def test_the_apps_the_setup_is_said_to_sandbox_are_the_ones_it_sandboxes(tmp_path, monkeypatch):
    # #689's review, P3-B1: AppKata's start gives no launcher to an app that has none where a launcher
    # in its install folder would find no bwrap (it runs Off there, R17.4), and the note said before
    # the setup's password prompt, in Settings → Sandbox and the install's prompt, still named it:
    # with no bwrap in the system's folders, the user's own in ~/bin, user namespaces restricted until
    # the setup, and an app installed Off in ~/bin, "Setting it up sandboxes Demo, which runs
    # unsandboxed until then", and after the setup it ran unsandboxed, still on that list. The note
    # and the start ask one question, so the apps said are the apps sandboxed.
    be, home, URL = _a_backend_with_the_users_bwrap_in_bin(tmp_path, monkeypatch)
    set_up = []
    monkeypatch.setattr(sb, "userns_works", lambda refresh=False: bool(set_up))     # restricted until the setup
    be.setPref("installDir", str(home / "bin" / "apps"))                     # Settings' folder, where a launcher finds it
    be.setPref("commandLinks", False)
    be._app = lambda url: {"url": URL, "name": "Demo", "installed": "1.0"}
    for root, sandboxed in {home / "bin" / "apps": True, home / "bin": False}.items():
        set_up.clear()
        _installed_off_in(be, URL, root)
        st = be.sandboxSupport
        assert st["status"] == "setup-needed", st
        said = st.get("waitingNote", "")
        assert ("Setting it up sandboxes Demo, which runs unsandboxed until then." in said) is sandboxed, said
        assert ([n for _, n, _ in be._waiting_for_sandbox()] == ["Demo"]) is sandboxed
        set_up.append(True)                                                  # the setup worked
        assert be._heal_launchers() == ([URL] if sandboxed else [])          # and sandboxed what it was said to
        assert be._waiting_for_sandbox() == []
        be.db.x("DELETE FROM installs")


def test_an_app_with_a_launcher_where_launchers_find_no_bwrap_keeps_it_and_cant_start(tmp_path, monkeypatch):
    # #689's review, P3-4: R17.4 said the apps of an install folder whose launchers find no bwrap run
    # unsandboxed. That is so of one with no launcher (the two tests above); one that has a launcher
    # keeps it, as R17.10 says, and only the user's own Off runs it unsandboxed. Installed in ~/bin
    # while the system had its own bwrap, with the user's own in ~/bin since: AppKata's start
    # rewrites its launcher and keeps it, App Detail says it can't start, and its launcher stops
    # at "bubblewrap (bwrap) isn't installed".
    be, home, URL = _a_backend_with_the_users_bwrap_in_bin(tmp_path, monkeypatch)
    be.setPref("installDir", str(home / "bin" / "apps"))
    be.setPref("commandLinks", False)
    be._app = lambda url: {"url": URL, "name": "Demo", "installed": "1.0"}
    target = _installed_off_in(be, URL, home / "bin")
    rec = json.loads(be.db.one("SELECT record FROM installs WHERE url=?", (URL,))["record"])
    launcher = target / "run"
    launcher.write_text("#!/bin/sh\n# the launcher of a system that had its own bwrap\n")
    rec["launcher"] = rec["exec"] = str(launcher)
    be.db.x("UPDATE installs SET record=? WHERE url=?", (json.dumps(rec), URL))
    assert be._heal_launchers() == [URL]                                     # not today's text: rewritten, and kept
    rec = json.loads(be.db.one("SELECT record FROM installs WHERE url=?", (URL,))["record"])
    assert rec["launcher"] == rec["exec"] == str(launcher) and be._sandbox_for_install(URL) is not None
    info = be.sandboxInfo(URL)                                               # its App Detail
    assert info["active"] and info["support"]["status"] == "unsupported", info["support"]
    assert info["support"]["brokenHint"].startswith("Can't start: bubblewrap isn't installed, and it runs sandboxed."), info["support"]
    started = subprocess.run([str(launcher)], env={"PATH": "/usr/bin:/bin", "HOME": str(home), "XDG_RUNTIME_DIR": str(tmp_path.resolve() / "run.d")},
                             capture_output=True, text=True, timeout=30)
    assert started.returncode == 1 and "AppKata: bubblewrap (bwrap) isn't installed, so Demo can't run sandboxed here." in started.stderr, started


def _a_backend_with_the_users_bwrap_in_bin(tmp_path, monkeypatch):
    """A Backend on a system whose folders hold no bwrap, with the user's own in ~/bin first on
    AppKata's PATH, and Demo reviewed Strict by a Trust: (the backend, the home, Demo's URL)."""
    pytest.importorskip("PySide6")
    tmp = tmp_path.resolve()
    system = _system_without_bwrap(tmp, monkeypatch)
    home = tmp / "home"
    _program(home / "bin" / "bwrap")                                         # the user's own, in ~/bin
    monkeypatch.setenv("PATH", f"{home / 'bin'}:{system}")
    monkeypatch.setattr(sb, "_userns_cache", None)
    monkeypatch.setattr(sb, "_nested_cache", None)
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from appkata.backend import Backend
    from test_sandbox_backend import URL, _review
    be = Backend(db_path=str(tmp / "appkata.db"), heal=False)
    be.db.x("INSERT INTO trusts(url, name, enabled, score) VALUES(?,?,1,3)", ("https://example.org/trust", "Alice"))
    be._is_cli = lambda url, eff=None: False
    be._sandbox_kind = lambda url: "tarball"
    _review(be, "strict")
    be._app = lambda url: {"url": URL, "name": "Demo"}
    return be, home, URL


def _installed_off_in(be, url, root):
    """Record Demo installed in the install folder `root`, with no launcher (it runs Off); returns
    its folder."""
    from appkata_core.db import now
    target = root / "demo"
    _program(target / "1.0" / "bin" / "demo")
    rec = {"current": {"version": "1.0", "path": str(target / "1.0"), "exec": "1.0/bin/demo"}, "root": str(root),
           "target": str(target), "links": [], "files": [], "exec": str(target / "1.0" / "bin" / "demo")}
    be.db.x("INSERT OR REPLACE INTO installs(url, name, version, kind, record, installed_at) VALUES(?,?,?,?,?,?)",
            (url, "Demo", "1.0", "tarball", json.dumps(rec), now()))
    return target
