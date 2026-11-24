"""Installing from a local web server (R4), and writing reviews with git (R8)."""

import hashlib
import http.server
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import threading

import pytest

from appkata_core import devtools, forges, install, review
from appkata_core.db import DB
from appkata_core.forges import Asset


@pytest.fixture
def server(tmp_path):
    root = tmp_path / "www"
    root.mkdir()
    handler = lambda *a, **k: http.server.SimpleHTTPRequestHandler(*a, directory=str(root), **k)   # noqa: E731
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    httpd.RequestHandlerClass.log_message = lambda *a: None
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield root, f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("APPKATA_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("APPKATA_APPS", str(tmp_path / "apps"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    return DB(str(tmp_path / "data" / "appkata.db"))


def _downloads():
    """Every file in the downloads folder (R4.8.2), under whichever app's name."""
    return sorted(os.path.join(d, n) for d, _, names in os.walk(install.downloads_dir()) for n in names)


# Linux's layout (AppImages, symbolic links, .desktop entries); Windows' is in tests/test_windows.py
linux_only = pytest.mark.skipif(os.name == "nt", reason="the Linux install layout")

APP = {"url": "https://github.com/demo/tool", "name": "Demo Tool", "version": "1.2.0", "date": "2026-09-01T00:00:00Z",
       "summary": "A demo", "icon": "", "repo": "demo/tool", "foreign": ""}


@linux_only
def test_appimage_with_forge_digest(env, server, tmp_path):
    root, base = server
    data = b"\x7fELF fake appimage"
    (root / "Tool-1.2.0-x86_64.AppImage").write_bytes(data)
    a = Asset("Tool-1.2.0-x86_64.AppImage", base + "/Tool-1.2.0-x86_64.AppImage", len(data),
              "sha256:" + hashlib.sha256(data).hexdigest())
    rec = install.install(env, APP, a, "appimage", [a])
    exe = rec["exec"]
    assert os.access(exe, os.X_OK) and open(exe, "rb").read() == data and rec["verified"] == "checksum"
    desktop = tmp_path / "xdg" / "applications" / "appkata-demo-tool.desktop"
    assert "Name=Demo Tool" in desktop.read_text()
    assert env.one("SELECT version FROM installs")["version"] == "1.2.0"
    install.uninstall(env, APP["url"])
    assert not os.path.exists(exe) and not desktop.exists() and env.one("SELECT * FROM installs") is None


def test_checksum_mismatch_installs_nothing(env, server, tmp_path):
    root, base = server
    (root / "Tool.AppImage").write_bytes(b"tampered")
    (root / "SHA256SUMS").write_text(hashlib.sha256(b"original").hexdigest() + "  Tool.AppImage\n")
    a = Asset("Tool.AppImage", base + "/Tool.AppImage")
    sums = Asset("SHA256SUMS", base + "/SHA256SUMS")
    with pytest.raises(install.InstallError, match="doesn't match its checksum"):
        install.install(env, APP, a, "appimage", [a, sums])
    assert not (tmp_path / "apps").exists() or not os.listdir(tmp_path / "apps")
    assert _downloads() == []                   # R4.8.2: the complete file that failed its checksum is deleted


@linux_only
def test_tarball_and_foreign_refused(env, server):
    root, base = server
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, mode, body in (("tool-1.2/tool", 0o755, b"#!/bin/sh\necho hi\n"), ("tool-1.2/README", 0o644, b"hi")):
            info = tarfile.TarInfo(name); info.size = len(body); info.mode = mode
            tf.addfile(info, io.BytesIO(body))
    (root / "tool-1.2-linux-x86_64.tar.gz").write_bytes(buf.getvalue())
    a = Asset("tool-1.2-linux-x86_64.tar.gz", base + "/tool-1.2-linux-x86_64.tar.gz")
    rec = install.install(env, {**APP, "name": "tool"}, a, "tarball", [a])
    assert rec["exec"].endswith("tool-1.2/tool") and rec["verified"] == "unverified"
    with pytest.raises(install.InstallError, match="outside AppKata"):
        install.install(env, {**APP, "foreign": "/usr/share/applications/tool.desktop"}, a, "tarball", [a])


def test_review_commit_and_push_rules(tmp_path):
    repo = tmp_path / "reviews"
    bare = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
    for k, v in (("user.name", "You"), ("user.email", "you@example.com"), ("commit.gpgsign", "false")):
        subprocess.run(["git", "-C", str(repo), "config", k, v], check=True)
    subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", str(bare)], check=True)
    path = str(repo / "AppKata.md")
    st = review.repo_state(path)
    assert st.in_repo and st.remote == str(bare) and not st.signs
    # unsigned: committed, never pushed (R8.5)
    r = review.save(path, "LocalSend", "https://github.com/localsend/localsend", ["foss"], 4, 5, "Good.", commit=True, push=True)
    assert r.committed and not r.signed and not r.pushed and "isn't signed" in r.error
    assert review.current(path, "LocalSend", "https://github.com/localsend/localsend")["trust"] == 4
    if shutil.which("gpg"):
        home = str(tmp_path / "gnupg")
        fpr, _ = devtools.gpg_keygen(home, "You <you@example.com>")
        os.environ["GNUPGHOME"] = home
        try:
            subprocess.run(["git", "-C", str(repo), "config", "user.signingkey", fpr], check=True)
            subprocess.run(["git", "-C", str(repo), "config", "commit.gpgsign", "true"], check=True)
            r = review.save(path, "LocalSend", "https://github.com/localsend/localsend", ["foss"], 5, 5, "Better.", commit=True, push=True)
            assert r.signed and r.pushed, r.error
            log = subprocess.run(["git", "--git-dir", str(bare), "log", "--format=%s", "main"], capture_output=True, text=True).stdout
            assert "Review LocalSend" in log
        finally:
            del os.environ["GNUPGHOME"]


@linux_only
def test_portable_options(env, server, tmp_path):
    """Install folder, stable name, app-menu entry and command link (R4.3.1)."""
    root, base = server
    data = b"\x7fELF v2"
    (root / "Demo.Tool-2.0-x86_64.AppImage").write_bytes(data)
    a = Asset("Demo.Tool-2.0-x86_64.AppImage", base + "/Demo.Tool-2.0-x86_64.AppImage")
    p = install.Portable(folder=str(tmp_path / "bin-apps"), app_menu=True, stable_name=True, command_dir=str(tmp_path / "cmd"))
    rec = install.install(env, APP, a, "appimage", [a], portable=p)
    stable = tmp_path / "bin-apps" / "demo-tool" / "DemoTool.AppImage"
    assert os.path.islink(stable) and os.readlink(stable) == "Demo.Tool-2.0-x86_64.AppImage" and rec["exec"] == str(stable)
    cmd = tmp_path / "cmd" / "demo-tool"
    assert os.path.islink(cmd) and open(cmd, "rb").read() == data
    desktop = tmp_path / "xdg" / "applications" / "appkata-demo-tool.desktop"
    assert str(stable) in desktop.read_text()                                 # launchers use the stable name
    install.uninstall(env, APP["url"])
    assert not os.path.lexists(cmd) and not (tmp_path / "bin-apps" / "demo-tool").exists() and not desktop.exists()
    # without the options: no menu entry, no links
    rec = install.install(env, APP, a, "appimage", [a], portable=install.Portable(folder=str(tmp_path / "plain"), app_menu=False,
                                                                                    stable_name=False))
    assert rec["exec"].endswith("Demo.Tool-2.0-x86_64.AppImage") and not rec["links"] and not desktop.exists()


@linux_only
def test_command_link_never_replaces_a_real_file(env, server, tmp_path):
    root, base = server
    (root / "t.AppImage").write_bytes(b"x")
    (tmp_path / "cmd").mkdir()
    (tmp_path / "cmd" / "demo-tool").write_text("mine")
    a = Asset("t.AppImage", base + "/t.AppImage")
    with pytest.raises(install.InstallError, match="isn't a link AppKata made"):
        install.install(env, APP, a, "appimage", [a], portable=install.Portable(folder=str(tmp_path / "f"), command_dir=str(tmp_path / "cmd")))
    assert (tmp_path / "cmd" / "demo-tool").read_text() == "mine"


@linux_only
def test_zip_install(env, server, tmp_path):
    import zipfile
    root, base = server
    zp = root / "tool-1.2-linux-x64.zip"
    with zipfile.ZipFile(zp, "w") as z:
        zi = zipfile.ZipInfo("tool-1.2/tool"); zi.external_attr = 0o755 << 16
        z.writestr(zi, "#!/bin/sh\n")
    a = Asset(zp.name, base + "/" + zp.name)
    rec = install.install(env, {**APP, "name": "tool"}, a, "zip", [a], portable=install.Portable(folder=str(tmp_path / "z"), app_menu=False))
    assert rec["exec"].endswith("tool-1.2/tool")
    bad = root / "bad.zip"
    with zipfile.ZipFile(bad, "w") as z:
        z.writestr("../escape", "x")
    b = Asset("bad.zip", base + "/bad.zip")
    with pytest.raises(install.InstallError, match="unsafe path"):
        install.install(env, {**APP, "name": "bad"}, b, "zip", [b], portable=install.Portable(folder=str(tmp_path / "z")))


@linux_only
def test_versions_kept_side_by_side(env, server, tmp_path):
    """~/bin/apps/<app>/ holds each version; older ones are kept up to the setting (R4.3.1.5)."""
    root, base = server
    p = install.Portable(folder=str(tmp_path / "apps"), app_menu=False, command_dir=str(tmp_path / "bin"), keep=2)
    for v in ("1.0", "1.1", "1.2", "1.3"):
        (root / f"Tool-{v}-x86_64.AppImage").write_bytes(v.encode())
        a = Asset(f"Tool-{v}-x86_64.AppImage", f"{base}/Tool-{v}-x86_64.AppImage")
        rec = install.install(env, {**APP, "installVersion": v}, a, "appimage", [a], portable=p)
    folder = tmp_path / "apps" / "demo-tool"
    files = sorted(f.name for f in folder.iterdir() if not f.is_symlink())
    assert files == ["Tool-1.1-x86_64.AppImage", "Tool-1.2-x86_64.AppImage", "Tool-1.3-x86_64.AppImage"]
    assert install.kept_versions(env, APP["url"]) == ["1.2", "1.1"]
    assert open(tmp_path / "bin" / "demo-tool", "rb").read() == b"1.3"
    rec = install.switch_to(env, {**APP}, "1.1", p)                      # rollback without downloading
    assert open(tmp_path / "bin" / "demo-tool", "rb").read() == b"1.1"
    assert env.one("SELECT version FROM installs")["version"] == "1.1" and install.kept_versions(env, APP["url"]) == ["1.3", "1.2"]
    install.remove_version(env, APP["url"], "1.2")
    assert not (folder / "Tool-1.2-x86_64.AppImage").exists() and install.kept_versions(env, APP["url"]) == ["1.3"]
    install.uninstall(env, APP["url"])
    assert not folder.exists() and not os.path.lexists(tmp_path / "bin" / "demo-tool")


@linux_only
def test_tarball_versions_and_current_link(env, server, tmp_path):
    root, base = server
    p = install.Portable(folder=str(tmp_path / "apps"), app_menu=False, keep=1)
    for v in ("2.0", "2.1"):
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tf:
            body = f"#!/bin/sh\necho {v}\n".encode()
            info = tarfile.TarInfo(f"tool-{v}/tool"); info.size = len(body); info.mode = 0o755
            tf.addfile(info, io.BytesIO(body))
        (root / f"tool-{v}.tar.gz").write_bytes(buf.getvalue())
        a = Asset(f"tool-{v}.tar.gz", f"{base}/tool-{v}.tar.gz")
        rec = install.install(env, {**APP, "name": "tool", "installVersion": v}, a, "tarball", [a], portable=p)
    folder = tmp_path / "apps" / "tool"
    assert (folder / "2.0").is_dir() and (folder / "2.1").is_dir() and os.readlink(folder / "current") == "2.1"
    assert rec["exec"] == str(folder / "current" / "tool-2.1" / "tool")


def test_retention_never_deletes_an_adopted_file(tmp_path):
    # AppKata's own AppImage, adopted rather than placed (R2.11.3)
    paths = [tmp_path / n for n in ("new", "a", "adopted")]
    for p in paths:
        p.write_text("x")
    rec = {"current": {"path": str(paths[0])}, "kept": [{"path": str(paths[1])}, {"path": str(paths[2]), "external": True}]}
    install._forget(install._retain(rec, 0))
    assert rec["kept"] == [] and not paths[1].exists() and paths[2].exists()


class _RangeHandler(http.server.BaseHTTPRequestHandler):
    """Serves one file with ETag and Range support; the first full response breaks halfway."""
    data = b""
    broke = []

    def log_message(self, *a):
        pass

    def do_GET(self):
        d, start = self.data, 0
        rng = self.headers.get("Range")
        if rng and self.headers.get("If-Range") == '"v1"':
            start = int(rng.split("=")[1].split("-")[0])
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{len(d) - 1}/{len(d)}")
        else:
            self.send_response(200)
        self.send_header("ETag", '"v1"')
        self.send_header("Content-Length", str(len(d) - start))
        self.end_headers()
        if start == 0 and not self.broke:
            self.broke.append(1)
            self.wfile.write(d[: len(d) // 2])
            self.wfile.flush()
            self.connection.shutdown(2)            # the connection breaks mid-download
            return
        self.wfile.write(d[start:])


@pytest.fixture
def range_server():
    _RangeHandler.data = os.urandom(300_000)
    _RangeHandler.broke = []
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _RangeHandler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}/file.bin"
    httpd.shutdown()


def test_download_resumes_after_a_break(range_server, tmp_path, monkeypatch):
    # R4.8.2: the second request asks only for the rest, and the digest covers the whole file
    monkeypatch.setattr(install.time, "sleep", lambda s: None)
    dest = tmp_path / "file.bin"
    seen = []
    digest = install.download(range_server, str(dest), progress=lambda got, total: seen.append(got))
    assert dest.read_bytes() == _RangeHandler.data and digest == hashlib.sha256(_RangeHandler.data).hexdigest()
    assert not (tmp_path / "file.bin.part").exists() and not (tmp_path / "file.bin.part.json").exists()
    assert min(g for g in seen if g >= len(_RangeHandler.data) // 2) >= len(_RangeHandler.data) // 2


def test_cancelled_download_leaves_nothing(range_server, tmp_path):
    dest = tmp_path / "file.bin"
    with pytest.raises(install.Cancelled):
        install.download(range_server, str(dest), cancel=lambda: True)
    assert not list(tmp_path.iterdir())


def test_app_that_updates_itself_has_no_version_folders(env, server, tmp_path):
    # R4.10.2: one file under a stable name, nothing kept, no "current" link
    root, base = server
    p = install.Portable(folder=str(tmp_path / "apps2"), app_menu=False, stable_name=True, keep=2)
    for v in ("1.0", "2.0"):
        name = f"Tool-{v}-x86_64.AppImage"
        (root / name).write_bytes(b"\x7fELF " + v.encode())
        a = Asset(name, f"{base}/{name}")
        rec = install.install(env, {**APP, "autoUpdate": True, "installVersion": v}, a, "appimage", [a], portable=p)
    folder = tmp_path / "apps2" / "demo-tool"
    assert sorted(os.listdir(folder)) == ["DemoTool.AppImage"] and rec["kept"] == [] and rec["selfUpdating"]
    assert open(folder / "DemoTool.AppImage", "rb").read() == b"\x7fELF 2.0"


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="the sandbox is Linux-only (R17.1)")
def test_a_self_updating_app_that_runs_sandboxed_moves_to_versions_when_appkata_updates_it(env, server, tmp_path):
    # Review 2, F3: a sandboxed app can't update itself (its files are read-only), so AppKata updates
    # it as if it didn't (R17.12). Its first such update leaves the fixed-name layout of R4.10.2: the
    # old <App>.AppImage sat exactly where the versioned layout's stable-name link goes, and _link()
    # refused to replace "a file AppKata didn't make" -- the update would have stopped there.
    root, base = server
    p = install.Portable(folder=str(tmp_path / "apps3"), app_menu=False, stable_name=True, keep=2)
    (root / "Tool-1.0-x86_64.AppImage").write_bytes(b"\x7fELF 1.0")
    a1 = Asset("Tool-1.0-x86_64.AppImage", f"{base}/Tool-1.0-x86_64.AppImage")
    install.install(env, {**APP, "autoUpdate": True, "installVersion": "1.0"}, a1, "appimage", [a1], portable=p)
    (root / "Tool-2.0-x86_64.AppImage").write_bytes(b"\x7fELF 2.0")
    a2 = Asset("Tool-2.0-x86_64.AppImage", f"{base}/Tool-2.0-x86_64.AppImage")
    rec = install.install(env, {**APP, "autoUpdate": False, "installVersion": "2.0"}, a2, "appimage", [a2], portable=p)
    folder = tmp_path / "apps3" / "demo-tool"
    assert not rec.get("selfUpdating")
    assert os.path.islink(folder / "DemoTool.AppImage") and open(folder / "DemoTool.AppImage", "rb").read() == b"\x7fELF 2.0"
    assert [k["version"] for k in rec["kept"]] == ["1.0"] and open(rec["kept"][0]["path"], "rb").read() == b"\x7fELF 1.0"
    assert not os.path.islink(rec["kept"][0]["path"]) and rec["kept"][0]["path"] != str(folder / "DemoTool.AppImage")


@linux_only
@pytest.mark.parametrize("libs,kind", [([], "cli"), (["libgtk-3.so.0", "libc.so.6"], "gui")])
def test_a_tarballs_kind_comes_from_its_program_and_a_tool_gets_no_menu_entry(env, server, tmp_path, libs, kind):
    # Review 2, F4: an app's kind decided "a command link and no menu entry", which Settings' defaults
    # never gave, so every unreviewed tool ran Strict. install() now reads the download right after
    # placing it -- here a program linking a display library or none -- asks for the grant set again
    # with the kind, and leaves a tool's menu entry out when that option was only Settings' default.
    from test_appkind import make_elf
    root, base = server
    prog = tmp_path / "prog"
    make_elf(prog, libs)
    body = prog.read_bytes()
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        info = tarfile.TarInfo("tool-1.2/tool")
        info.size, info.mode = len(body), 0o755
        tf.addfile(info, io.BytesIO(body))
    (root / "tool.tar.gz").write_bytes(buf.getvalue())
    a = Asset("tool.tar.gz", base + "/tool.tar.gz")
    p = install.Portable(folder=str(tmp_path / "apps4"), app_menu=True, stable_name=True, keep=2)
    asked = []
    app = {**APP, "name": "tool", "sandbox_for_kind": lambda is_cli: asked.append(is_cli), "menuFromDefault": True}
    rec = install.install(env, app, a, "tarball", [a], portable=p)
    assert rec["appKind"] == kind and asked == [kind == "cli"]
    assert rec["options"]["appMenu"] is (kind == "gui")
    assert any(os.path.basename(f).startswith("appkata-") for f in rec["files"]) is (kind == "gui")
    install.install(env, {**app, "cliKind": "gui"}, a, "tarball", [a], portable=p)        # the user's word wins
    assert asked[-1] is False
    rec = install.install(env, {**app, "menuFromDefault": False}, a, "tarball", [a], portable=p)
    assert rec["options"]["appMenu"] is True                                               # a chosen menu option stands


# ---------------------------------------------------------------- the app-menu entry's text (CR1.3-7)

_ENTRY_KEYS = ["Type", "Name", "Comment", "Exec", "Categories", "X-AppKata"]
# every character some reader of a line-based file ends a line at (str.splitlines' list), and NUL
_LINE_ENDS = ["\n", "\r", "\r\n", "\x0b", "\x0c", "\x1c", "\x1d", "\x1e", "\x85", " ", " ", "\x00"]


def _glib_reads(path):
    """What the desktop's own reader, GLib, makes of an entry: (its groups, [Desktop Entry]'s keys,
    the command line's words), or None where no system python3 has python3-gi. GLib is what starts
    a menu entry, so it has the last word where it is there (tier 1's container has it)."""
    code = ("import json, sys\nfrom gi.repository import Gio, GLib\n"
            "k = GLib.KeyFile(); k.load_from_file(sys.argv[1], GLib.KeyFileFlags.NONE)\n"
            "cmd = Gio.DesktopAppInfo.new_from_filename(sys.argv[1]).get_commandline()\n"
            "print(json.dumps([k.get_groups()[0], k.get_keys('Desktop Entry')[0], GLib.shell_parse_argv(cmd)[1]]))\n")
    py = shutil.which("python3", path="/usr/bin:/bin")
    if not py or subprocess.run([py, "-c", "import gi"], capture_output=True).returncode:
        return None
    return json.loads(subprocess.run([py, "-c", code, str(path)], capture_output=True, text=True, check=True).stdout)


def _exec_words(value):
    """The words of an Exec= value, read as the Desktop Entry Specification says: the escapes of a
    string value first (a doubled backslash is one), then double-quoted arguments, where a backslash
    escapes a quote, a backtick, a dollar sign and itself, then a doubled percent sign is one."""
    assert "\\" not in re.sub(r"\\\\", "", value), value            # no other escape is written
    value = value.replace("\\\\", "\\")
    words, i = [], 0
    while i < len(value):
        if value[i] == " ":
            i += 1
        elif value[i] == '"':
            word, i = "", i + 1
            while value[i] != '"':
                if value[i] == "\\":
                    assert value[i + 1] in '"`$\\', value
                    i += 1
                else:
                    assert value[i] not in "`$", value              # reserved inside quotes unless escaped
                word, i = word + value[i], i + 1
            words.append(word)
            i += 1
        else:
            j = value.find(" ", i) if " " in value[i:] else len(value)
            words.append(value[i:j])
            i = j
    assert all(re.fullmatch(r"(%%|[^%])*", w) or w == "%U" for w in words), words     # a lone % is a field code
    return [w if w == "%U" else w.replace("%%", "%") for w in words]


def _entry(path):
    """The entry as the strictest standard reader has it (configparser refuses a key given twice):
    {group: {key: value}}, keys as written."""
    import configparser
    cp = configparser.RawConfigParser(strict=True, delimiters=("=",), comment_prefixes=("#",))
    cp.optionxform = str
    cp.read(path, encoding="utf-8")
    return {s: dict(cp[s]) for s in cp.sections()}


@linux_only
@pytest.mark.parametrize("end", _LINE_ENDS, ids=[repr(e) for e in _LINE_ENDS])
def test_a_projects_name_and_summary_cannot_add_a_line_to_the_menu_entry(env, server, tmp_path, end):
    # CR1.3-7: the name and the summary are the project's (its metainfo, its README, its forge), and
    # were written as they came. A line break in the summary, then `Exec=...` and a group header, made
    # the project's command the entry's Exec, and AppKata's own -- the sandbox launcher's -- a line of
    # a group nobody reads: a Strict app's menu entry ran the project's command on the host. A break
    # in the name added MimeType= and Terminal=. The class is every value written into the entry and
    # every character a reader may end a line at, so the entry is read here as a list of lines, by
    # the widest notion of a line there is, and by two parsers.
    root, base = server
    (root / "t.AppImage").write_bytes(b"\x7fELF")
    a = Asset("t.AppImage", base + "/t.AppImage")
    app = {**APP, "name": f"Demo{end}MimeType=x-scheme-handler/https;text/html;{end}Terminal=true",
           "summary": f"A tool{end}Exec=sh -c \"touch /tmp/pwned\"{end}[X]{end}NoDisplay=true"}
    rec = install.install(env, app, a, "appimage", [a], portable=install.Portable(folder=str(tmp_path / "f")))
    path = next(f for f in rec["files"] if f.endswith(".desktop"))
    text = open(path, encoding="utf-8", newline="").read()
    lines = text.splitlines()
    assert lines[0] == "[Desktop Entry]" and [l.split("=", 1)[0] for l in lines[1:]] == _ENTRY_KEYS, lines
    assert "\x00" not in text and text.endswith("\n")
    want = f'"{rec["exec"]}" %U'
    entry = _entry(path)
    assert list(entry) == ["Desktop Entry"] and list(entry["Desktop Entry"]) == _ENTRY_KEYS, entry
    assert entry["Desktop Entry"]["Exec"] == want
    # the text is still there to read, as text: one line of it
    assert entry["Desktop Entry"]["Name"] == "Demo MimeType=x-scheme-handler/https;text/html; Terminal=true"
    assert entry["Desktop Entry"]["Comment"] == 'A tool Exec=sh -c "touch /tmp/pwned" [X] NoDisplay=true'
    if (glib := _glib_reads(path)) is not None:
        assert glib == [["Desktop Entry"], _ENTRY_KEYS, [rec["exec"], "%U"]], glib


@linux_only
def test_the_menu_entry_escapes_the_path_it_starts_and_refuses_one_it_cannot_write(env, server, tmp_path):
    # CR1.3-7's other half: Exec= held the path in quotes and escaped nothing in it, so an install
    # folder with a %, a $, a backtick or a backslash in its name made an entry that started something
    # else or nothing. The words are read back by the specification's rules, and by GLib where it is.
    root, base = server
    (root / "t.AppImage").write_bytes(b"\x7fELF")
    a = Asset("t.AppImage", base + "/t.AppImage")
    # GLib looks for the program before it reads `%%` as `%`, so it takes an entry whose program's
    # path holds a % for an app that isn't installed, written either way (seen with GLib 2.80); it
    # reads the second folder, which has every other character.
    for folder, glib_too in ((tmp_path / "My Apps" / "50% off %U" / "a $ and `id`" / "back\\slash\\\\two", False),
                             (tmp_path / "My Apps" / "a $ and `id`" / "back\\slash\\\\two", True)):
        app = {**APP, "url": f"{APP['url']}-{'glib' if glib_too else 'spec'}"}
        rec = install.install(env, app, a, "appimage", [a], portable=install.Portable(folder=str(folder)))
        assert rec["exec"].startswith(str(folder))
        path = next(f for f in rec["files"] if f.endswith(".desktop"))
        entry = _entry(path)["Desktop Entry"]
        assert _exec_words(entry["Exec"]) == [rec["exec"], "%U"], entry["Exec"]
        if glib_too and (glib := _glib_reads(path)) is not None:
            assert glib[2] == [rec["exec"], "%U"], glib
    # a sandbox launcher's own word stays a word of its own, outside the quotes
    assert _exec_words(install.desktop_exec("/a b/run", "--appkata-menu")) == ["/a b/run", "--appkata-menu", "%U"]
    # a backslash in the name is a backslash, not the start of an escape (`\n` would be a line break)
    rec = install.install(env, {**APP, "name": "Demo\\nTool"}, a, "appimage", [a], portable=install.Portable(folder=str(tmp_path / "f")))
    assert "Name=Demo\\\\nTool\n" in open(next(f for f in rec["files"] if f.endswith(".desktop"))).read()
    for bad in ('quo"te', "line\nbreak", "tab\there", "nul\x7f"):
        with pytest.raises(install.InstallError, match="quote or a line break"):
            install.install(env, {**APP, "url": APP["url"] + "-other", "name": "Other"}, a, "appimage", [a],
                            portable=install.Portable(folder=str(tmp_path / bad)))
    assert not (tmp_path / "xdg" / "applications" / "appkata-other.desktop").exists()


class _HostileForge:
    """A forge whose project has no release and one file, a metainfo."""
    kind = "github"

    def __init__(self, name, description, metainfo):
        self._info, self._metainfo = forges.RepoInfo(name=name, description=description), metainfo

    def info(self):
        return self._info

    def releases(self):
        return []

    def tree(self, branch):
        return ["data/io.example.tool.metainfo.xml"] if self._metainfo else []

    def readme(self, branch, paths):
        return "", ""

    def raw(self, path, branch):
        return self._metainfo.encode()

    def raw_url(self, path, branch):
        return "https://forge.example/raw/" + path


@pytest.mark.parametrize("metainfo", [True, False], ids=["metainfo", "forge"])
def test_sync_stores_a_projects_name_and_summary_as_one_line_each(env, tmp_path, monkeypatch, metainfo):
    # CR1.3-7: where the text comes in. A metainfo's <name> and <summary> kept their line breaks
    # (`&#10;` is one), and so did the forge's own name and description, which stand in when the
    # project has no metainfo and its README no paragraph. What is stored is what every list shows
    # and what the menu entry is written from.
    from appkata_core import sync
    xml = ("<component><id>io.example.tool</id><name>Foo&#10;MimeType=x-scheme-handler/https;&#10;Terminal=true</name>"
           "<summary>A tool&#10;Exec=sh -c \"touch /tmp/pwned\"&#13;&#10;[X]</summary></component>")
    forge = _HostileForge("tool\nTerminal=true", "A forge's\ndescription Exec=sh", xml if metainfo else "")
    monkeypatch.setattr(sync.forges, "forge_for", lambda http, repo, kind: forge)
    monkeypatch.setattr(sync.forges, "detect", lambda http, host: "github")
    sync.sync_app(env, None, "https://github.com/demo/tool", root=str(tmp_path / "data"))
    row = env.one("SELECT name, summary, error FROM apps WHERE url=?", ("https://github.com/demo/tool",))
    assert not row["error"]
    assert row["name"] == ("Foo MimeType=x-scheme-handler/https; Terminal=true" if metainfo else "tool Terminal=true")
    assert row["summary"] == ('A tool Exec=sh -c "touch /tmp/pwned" [X]' if metainfo else "A forge's description Exec=sh")
    assert all(len(v.splitlines()) == 1 for v in (row["name"], row["summary"]))


# ---------------------------------------------------------------- the command link's name (CR1.5-31)

def _appimage(server, name="t.AppImage", data=b"\x7fELF"):
    root, base = server
    (root / name).write_bytes(data)
    return Asset(name, f"{base}/{name}")


@pytest.fixture
def debian_path(tmp_path, monkeypatch):
    """A PATH as Ubuntu, Debian and Mint make it at login: the command links folder (~/bin) first,
    then the system's. Returns that folder."""
    cmd = tmp_path / "home-bin"
    cmd.mkdir()
    monkeypatch.setenv("PATH", f"{cmd}:{os.environ['PATH']}")
    return cmd


@linux_only
@pytest.mark.parametrize("name", ["python3", "Readlink", "mktemp", "bwrap", "sudo", "git", "SSH", "ls", "My Own Tool"])
def test_an_app_named_after_a_command_is_installed_without_a_command_link(env, server, tmp_path, debian_path, monkeypatch, name):
    # CR1.5-31 (High), the owner's decision: an app's command link is named after the app, the
    # publisher picks the name, and the link goes where the PATH looks first. An app named python3,
    # readlink or mktemp then answered every sandbox launcher's own calls, outside any sandbox, and
    # one named sudo, ssh or git answered the user's terminal; `_link` checked the name against
    # nothing. No link is made for a name that is already a command here or is reserved: the app is
    # installed, with its app-menu entry, and its record says why it has no command.
    own = tmp_path / "opt"
    own.mkdir()
    (own / "my-own-tool").write_text("#!/bin/sh\necho mine\n")
    (own / "my-own-tool").chmod(0o755)
    monkeypatch.setenv("PATH", f"{os.environ['PATH']}:{own}")
    slug = install.slug(name)
    rec = install.install(env, {**APP, "name": name}, _appimage(server), "appimage", [_appimage(server)],
                          portable=install.Portable(folder=str(tmp_path / "apps"), command_dir=str(debian_path)))
    assert not os.path.lexists(debian_path / slug) and os.listdir(debian_path) == []
    assert all(os.path.dirname(l) != str(debian_path) for l in rec["links"])
    assert slug in rec["commandRefused"] and rec["options"]["commandLink"] is True         # the option stays as chosen
    assert ("kept for the system's own command" in rec["commandRefused"]) is (slug in install.RESERVED_COMMANDS)
    if slug not in install.RESERVED_COMMANDS:
        assert rec["commandRefused"] == f"{slug} is already a command on this computer ({shutil.which(slug)})"
    assert os.path.exists(tmp_path / "xdg" / "applications" / f"appkata-{slug}.desktop") and os.access(rec["exec"], os.X_OK)
    assert json.loads(env.one("SELECT record FROM installs")["record"])["commandRefused"] == rec["commandRefused"]
    install.uninstall(env, APP["url"])
    assert not (tmp_path / "apps" / slug).exists()


def test_no_command_link_is_ever_named_after_a_command_a_launcher_or_appkata_runs():
    # The reserved names hold whatever this computer has installed: a launcher's own commands
    # (sandbox.HOST_COMMANDS, which tests/test_sandbox_adversarial.py holds to the launcher's text),
    # and a name that is no command today may be one tomorrow, with the link then ahead of it.
    from appkata_core import sandbox
    assert set(sandbox.HOST_COMMANDS) <= install.RESERVED_COMMANDS
    assert {"python3", "bwrap", "xdg-dbus-proxy", "readlink", "mktemp", "sudo", "ssh", "git", "gpg", "pkexec", "sh"} <= install.RESERVED_COMMANDS
    for name in sorted(install.RESERVED_COMMANDS):
        why = install.command_link_refusal(name, "/nonexistent/bin/" + name, ("/nonexistent/apps",))
        assert why == f"{name} is a name kept for the system's own command", name


@linux_only
def test_an_apps_own_command_link_is_replaced_and_one_that_becomes_a_command_goes(env, server, tmp_path, debian_path, monkeypatch):
    # The other side of the name check: the link AppKata made for this app is on the PATH too, and
    # an update must not take it for someone else's command. And a name that becomes a command
    # later (the system installs a `demo-tool`) loses its link at the next update or start, since
    # the link would be ahead of it.
    p = install.Portable(folder=str(tmp_path / "apps"), command_dir=str(debian_path))
    for v in ("1.0", "1.1"):
        a = _appimage(server, f"Tool-{v}-x86_64.AppImage", v.encode())
        rec = install.install(env, {**APP, "installVersion": v}, a, "appimage", [a], portable=p)
        assert "commandRefused" not in rec and open(debian_path / "demo-tool", "rb").read() == v.encode()
    # a link of AppKata's own that no record names (a reinstall after a lost record) is still its own
    env.x("DELETE FROM installs")
    rec = install.install(env, {**APP, "installVersion": "1.1"}, a, "appimage", [a], portable=p)
    assert "commandRefused" not in rec and str(debian_path / "demo-tool") in rec["links"]
    system = tmp_path / "usr-bin"
    system.mkdir()
    (system / "demo-tool").write_text("#!/bin/sh\n")
    (system / "demo-tool").chmod(0o755)
    monkeypatch.setenv("PATH", f"{os.environ['PATH']}:{system}")
    rec = install.rewrite_launcher(env, dict(APP), p)                     # what AppKata's start does
    assert rec["commandRefused"] == f"demo-tool is already a command on this computer ({system / 'demo-tool'})"
    assert not os.path.lexists(debian_path / "demo-tool")
    (system / "demo-tool").unlink()
    rec = install.rewrite_launcher(env, dict(APP), p)                     # the name is free again: the option stood
    assert "commandRefused" not in rec and os.path.islink(debian_path / "demo-tool")


@linux_only
@pytest.mark.parametrize("on_path", [False, True])
def test_a_link_that_is_not_appkatas_is_never_replaced_by_a_command_link(env, server, tmp_path, monkeypatch, on_path):
    # CR1.5-31, R4.3.1.3: "AppKata never replaces a file there that isn't a link it made", and
    # `_link` took any symbolic link for one it made: the user's own ~/bin/demo-tool -> /opt/... was
    # replaced. Only a link that leads into the install folder is AppKata's. On the PATH, the
    # user's link is a command already, so the app is installed without one; off it, the install
    # stops as it does for a file.
    cmd, theirs = tmp_path / "cmd", tmp_path / "opt" / "their-tool"
    cmd.mkdir()
    theirs.parent.mkdir()
    theirs.write_text("#!/bin/sh\necho theirs\n")
    theirs.chmod(0o755)
    (cmd / "demo-tool").symlink_to(theirs)
    if on_path:
        monkeypatch.setenv("PATH", f"{cmd}:{os.environ['PATH']}")
    a = _appimage(server)
    p = install.Portable(folder=str(tmp_path / "apps"), command_dir=str(cmd))
    if on_path:
        rec = install.install(env, APP, a, "appimage", [a], portable=p)
        assert rec["commandRefused"] == f"demo-tool is already a command on this computer ({cmd / 'demo-tool'})"
    else:
        with pytest.raises(install.InstallError, match="isn't a link AppKata made"):
            install.install(env, APP, a, "appimage", [a], portable=p)
    assert os.readlink(cmd / "demo-tool") == str(theirs)


def test_the_install_notice_says_why_no_command_was_added_and_says_it_once():
    # The owner's decision on CR1.5-31: "the app installs with its menu entry and no command, and the
    # install says why". The notice is the install's own toast; an update whose reason hasn't
    # changed doesn't repeat it.
    pytest.importorskip("PySide6")                              # the backend is Qt's; the Windows run has none
    from appkata.backend import Backend
    why = "python3 is a name kept for the system's own command"
    assert Backend._command_note(why) == " No command was added: python3 is a name kept for the system's own command."
    assert Backend._command_note(why, before=why) == "" and Backend._command_note("") == "" and Backend._command_note("", before=why) == ""
    assert Backend._command_note("x is already a command on this computer (/usr/bin/x)", before=why).startswith(" No command was added: x is")


# ---------------------------------------------------------------- an install that fails part-way (CR1.3-15)

def _left(tmp_path, db):
    """Everything an install can leave behind: every file and link under the test's folder, the
    folders in the install folder and the sandbox homes, and the installs table. The web server's
    files, the database's own and the helpers AppKata keeps for every sandboxed app are no app's."""
    out = {}
    shared = os.path.join("data", "sandboxes", ".identity")
    for d, dirs, names in os.walk(tmp_path):
        if d == str(tmp_path):
            dirs[:] = [n for n in dirs if n != "www"]
        for n in dirs + names:
            p = os.path.join(d, n)
            rel = os.path.relpath(p, tmp_path)
            if n.startswith("appkata.db") or (rel.startswith(shared + os.sep) and not rel.startswith(os.path.join(shared, "apps") + os.sep)):
                continue
            if os.path.islink(p) or getattr(os.path, "isjunction", os.path.islink)(p):     # Windows' `current` is a junction
                out[rel] = "-> " + os.readlink(p)
            elif os.path.isfile(p):
                with open(p, "rb") as f:
                    out[rel] = hashlib.sha256(f.read()).hexdigest()[:16]
            elif rel.startswith("apps" + os.sep) or (os.path.dirname(rel) == os.path.join("data", "sandboxes") and not n.startswith(".")):
                out[rel] = "a folder"                      # an app's folder and what is in it, and its private home
    out["<installs>"] = json.dumps([{**dict(r), "record": json.loads(r["record"])} for r in db.all("SELECT * FROM installs ORDER BY url")],
                                   sort_keys=True)
    return out


def _changed(before, after):
    return {k: (before.get(k), after.get(k)) for k in sorted(set(before) | set(after)) if before.get(k) != after.get(k)}


def _failing_once(real, when=lambda *a, **k: True):
    """`real`, failing the first time it is asked for what `when` names, as on a full disk: the
    step fails for the new version, and making it again for the previous one is what takes the
    install back."""
    failed = []

    def call(*args, **kw):
        if when(*args, **kw) and not failed:
            failed.append(1)
            raise OSError(28, "No space left on device")
        return real(*args, **kw)
    return call


def _tarball(server, name, files):
    """An archive of `files`, {path: mode}, on the test's web server."""
    root, base = server
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for path, mode in files.items():
            body = f"#!/bin/sh\necho {path}\n".encode()
            info = tarfile.TarInfo(path)
            info.size, info.mode = len(body), mode
            tf.addfile(info, io.BytesIO(body))
    (root / name).write_bytes(buf.getvalue())
    return Asset(name, f"{base}/{name}")


_REFUSALS = {"the command link": "isn't a link AppKata made", "the menu entry": "couldn't add the app-menu entry",
             "an archive with no program": "couldn't find the program", "a folder that can't be put in place": "Not a directory"}


@linux_only
@pytest.mark.parametrize("update", [False, True], ids=["a first install", "an update"])
@pytest.mark.parametrize("refused", list(_REFUSALS))
def test_a_refused_install_leaves_everything_as_it_was(env, server, tmp_path, monkeypatch, refused, update):
    # CR1.3-15: the record is stored last, and nothing took back what a refused install had made by
    # then. A first install refused at its command link (a file of the user's is there) left the
    # app's folder, its stable link and its menu entry with no record: in the desktop's menu, not in
    # AppKata, and nothing to uninstall it with. Refused as an update, `current` and the menu entry
    # were the new version's and the record the old one's, and an archive with no program left its
    # <version>.new folder. Each refusal here is a real one: a file where the command link goes, a
    # program whose path in the archive holds a quote (no menu entry can start it, and that is known
    # only once it is unpacked), an archive with no program. The fourth is the one made to happen:
    # the unpacked version can't be renamed into place, as when what is at its name isn't a folder.
    apps, cmd, mine = tmp_path / "apps", tmp_path / "cmd", tmp_path / "their-bin"
    mine.mkdir()
    (mine / "tool").write_text("mine")
    app = {**APP, "name": "tool"}
    good = install.Portable(folder=str(apps), command_dir=str(cmd))
    if update:
        a1 = _tarball(server, "tool-1.0.tar.gz", {"tool-1.0/tool": 0o755})
        install.install(env, {**app, "installVersion": "1.0"}, a1, "tarball", [a1], portable=good)
        assert os.readlink(apps / "tool" / "current") == "1.0" and os.path.islink(cmd / "tool")
    files = {"the menu entry": {'tool-2.0/a "quoted" folder/tool': 0o755}, "an archive with no program": {"tool-2.0/README": 0o644}}
    a2 = _tarball(server, "tool-2.0.tar.gz", files.get(refused, {"tool-2.0/tool": 0o755}))
    p = install.Portable(folder=str(apps), command_dir=str(mine)) if refused == "the command link" else good
    before = _left(tmp_path, env)
    with monkeypatch.context() as m:
        if refused == "a folder that can't be put in place":
            real = os.replace
            m.setattr(install.os, "replace", lambda src, dst: (_ for _ in ()).throw(NotADirectoryError(20, "Not a directory", src, None, dst))
                      if src.endswith(".new") else real(src, dst))
        with pytest.raises((install.InstallError, OSError), match=_REFUSALS[refused]):
            install.install(env, {**app, "installVersion": "2.0"}, a2, "tarball", [a2], portable=p)
    assert _changed(before, _left(tmp_path, env)) == {}
    assert (mine / "tool").read_text() == "mine" and os.path.lexists(apps / "tool") is update
    if update:                                                  # and the app is whole: it updates, and uninstalls
        a3 = _tarball(server, "tool-3.0.tar.gz", {"tool-3.0/tool": 0o755})
        rec = install.install(env, {**app, "installVersion": "3.0"}, a3, "tarball", [a3], portable=good)
        assert os.readlink(apps / "tool" / "current") == "3.0" and [k["version"] for k in rec["kept"]] == ["1.0"]
        install.uninstall(env, APP["url"])
        assert not os.path.lexists(apps / "tool") and not os.path.lexists(cmd / "tool")
        assert not os.path.lexists(tmp_path / "xdg" / "applications" / "appkata-tool.desktop")


_STEPS = ["the stable link", "the launcher", "the menu entry", "the command link", "the record"]


@linux_only
@pytest.mark.parametrize("sandboxed", [False, True], ids=["unsandboxed", "sandboxed"])
@pytest.mark.parametrize("update", ["a first install", "an update", "an update out of the fixed layout", "a kept version"])
@pytest.mark.parametrize("step", _STEPS)
def test_whichever_step_of_an_install_fails_nothing_of_it_is_left(env, server, tmp_path, monkeypatch, step, update, sandboxed):
    # The class of CR1.3-15: an install changes the disk in steps (the version's files, the stable
    # link, the launcher, the menu entry, the command link) and stores its record last, so a failure
    # at any step left the steps before it with no record, or with the previous version's. Each
    # step is made to fail here, whatever would make it fail on a user's computer (a full disk, a
    # folder that can't be written), for a first install, an update, the update that moves an app
    # which updated itself into version folders (R17.12: its file is renamed first) and a switch to a
    # kept version, of an app that has a sandbox launcher and one that has none: afterwards every
    # file, link and folder and the installs table are what they were, so the next step that changes
    # the disk before the record is stored fails this test too.
    from appkata_core import sandbox
    cmd = tmp_path / "cmd"
    p = install.Portable(folder=str(tmp_path / "apps"), command_dir=str(cmd))
    app = {**APP, **({"sandbox": sandbox.resolve_template("standard")} if sandboxed else {})}
    fixed = update == "an update out of the fixed layout"
    for v in () if update == "a first install" else ("1.0",) if fixed else ("1.0", "1.1"):
        a = _appimage(server, f"Tool-{v}-x86_64.AppImage", v.encode())
        install.install(env, {**app, "installVersion": v, "autoUpdate": fixed}, a, "appimage", [a], portable=p)
    a = _appimage(server, "Tool-2.0-x86_64.AppImage", b"2.0")
    before = _left(tmp_path, env)
    if sandboxed and update != "a first install":
        assert before[os.path.join("apps", "demo-tool", "run")] and before[os.path.join("data", "sandboxes", ".identity", "apps", "demo-tool")]
    if fixed:
        assert before[os.path.join("apps", "demo-tool", "DemoTool.AppImage")] == hashlib.sha256(b"1.0").hexdigest()[:16]

    def failing(real, when=lambda *a, **k: True):
        """`real`, failing the first time it is asked for what `when` names: the step fails for the
        new version, and making it again for the previous one is what takes the install back."""
        failed = []

        def call(*args, **kw):
            if when(*args, **kw) and not failed:
                failed.append(1)
                raise OSError(28, "No space left on device")
            return real(*args, **kw)
        return call

    with monkeypatch.context() as m:
        if step == "the stable link":
            m.setattr(install, "_link", failing(install._link, lambda target, link, own=None: os.path.basename(link) == "DemoTool.AppImage"))
        elif step == "the command link":
            m.setattr(install, "_link", failing(install._link, lambda target, link, own=None: os.path.dirname(link) == str(cmd)))
        elif step == "the launcher":
            m.setattr(install, "_sandbox_launcher", failing(install._sandbox_launcher))
        elif step == "the menu entry":
            m.setattr(install, "_desktop_entry", failing(install._desktop_entry))
        else:
            m.setattr(env, "x", failing(env.x, lambda sql, *a: sql.startswith(("INSERT OR REPLACE INTO installs", "UPDATE installs"))))
        with pytest.raises(OSError, match="No space left"):
            if update == "a kept version":
                install.switch_to(env, dict(app), "1.0", p)
            else:
                install.install(env, {**app, "installVersion": "2.0"}, a, "appimage", [a], portable=p)
    assert _changed(before, _left(tmp_path, env)) == {}


@linux_only
def test_a_failed_first_install_takes_nothing_that_was_there_before_it(env, server, tmp_path, monkeypatch):
    # What takes a failed install back removes only what the install made: a folder of the user's
    # where the app's goes, and the private home an earlier uninstall kept for this app (R17.14),
    # with what is in them, are there afterwards.
    from appkata_core import sandbox
    (tmp_path / "apps" / "demo-tool").mkdir(parents=True)
    (tmp_path / "apps" / "demo-tool" / "notes.txt").write_text("mine")
    home = tmp_path / "data" / "sandboxes" / "demo-tool"
    home.mkdir(parents=True)
    (home / "settings.ini").write_text("kept")
    sandbox.record_home_owner("demo-tool", APP["url"])
    a = _appimage(server, "Tool-2.0-x86_64.AppImage", b"2.0")
    before = _left(tmp_path, env)
    monkeypatch.setattr(install, "_desktop_entry", lambda *a, **k: (_ for _ in ()).throw(OSError(28, "No space left on device")))
    with pytest.raises(OSError, match="No space left"):
        install.install(env, {**APP, "sandbox": sandbox.resolve_template("standard")}, a, "appimage", [a],
                        portable=install.Portable(folder=str(tmp_path / "apps"), command_dir=str(tmp_path / "cmd")))
    assert _changed(before, _left(tmp_path, env)) == {}
    assert (home / "settings.ini").read_text() == "kept" and (tmp_path / "apps" / "demo-tool" / "notes.txt").read_text() == "mine"


# ---------------------------------------------------------------- a link where a command link was (CR1.3-11)

_THEIRS = ["a link to their own program", "a link that leads nowhere", "a file"]


@linux_only
@pytest.mark.parametrize("on_path", [False, True], ids=["off the PATH", "on the PATH"])
@pytest.mark.parametrize("then", ["an update", "a kept version", "the next start", "uninstall"])
@pytest.mark.parametrize("theirs", _THEIRS)
def test_what_the_user_put_where_a_command_link_was_is_never_removed_or_replaced(env, server, tmp_path, monkeypatch, theirs, then, on_path):
    # CR1.3-11, R4.3.1.3: "AppKata never replaces a file there that isn't a link it made". A first
    # install has checked that since CR1.5-31. But an installed app's record names its command
    # link's path, and whatever symbolic link was at a recorded path was taken for AppKata's: an
    # update, a switch to a kept version and the startup pass removed it and put AppKata's there,
    # and uninstalling removed it. A link is AppKata's when it leads into the install folder,
    # wherever its path is written down. So: the user puts something of their own where the
    # command link was (a link to their program, a link to nothing, a file), and nothing AppKata
    # then does to the app touches it. On the PATH, a link to a program is a command already, so
    # the app goes on without one (R4.3.1.3); otherwise the update stops with the error, and
    # changes nothing, and the launcher's rewrite at the next start is made without the command.
    cmd, their_program = tmp_path / "cmd", tmp_path / "opt" / "their-tool"
    their_program.parent.mkdir()
    their_program.write_text("#!/bin/sh\necho theirs\n")
    their_program.chmod(0o755)
    if on_path:
        monkeypatch.setenv("PATH", f"{cmd}:{os.environ['PATH']}")
    p = install.Portable(folder=str(tmp_path / "apps"), command_dir=str(cmd))
    for v in ("1.0", "1.1"):
        a = _appimage(server, f"Tool-{v}-x86_64.AppImage", v.encode())
        install.install(env, {**APP, "installVersion": v}, a, "appimage", [a], portable=p)
    link = cmd / "demo-tool"
    assert os.readlink(link) == str(tmp_path / "apps" / "demo-tool" / "DemoTool.AppImage")
    link.unlink()
    if theirs == "a file":
        link.write_text("mine")
    else:
        link.symlink_to(their_program if theirs == "a link to their own program" else tmp_path / "gone" / "tool")
    was = os.readlink(link) if link.is_symlink() else link.read_text()
    before = _left(tmp_path, env)
    a = _appimage(server, "Tool-2.0-x86_64.AppImage", b"2.0")
    act = {"an update": lambda: install.install(env, {**APP, "installVersion": "2.0"}, a, "appimage", [a], portable=p),
           "a kept version": lambda: install.switch_to(env, dict(APP), "1.0", p),
           "the next start": lambda: install.rewrite_launcher(env, dict(APP), p),
           "uninstall": lambda: install.uninstall(env, APP["url"])}[then]
    if then == "uninstall":
        act()
        assert env.one("SELECT * FROM installs") is None and not os.path.lexists(tmp_path / "apps" / "demo-tool")
    elif on_path and theirs == "a link to their own program":
        rec = act()
        assert rec["commandRefused"] == f"demo-tool is already a command on this computer ({link})"
        assert str(link) not in rec["links"]
    elif then == "the next start":          # the launcher's rewrite is no install: it is made, without the command (CR1.3-46)
        rec = act()
        assert rec["commandRefused"] == f"{link} exists and isn't a link AppKata made; not replacing it"
        assert str(link) not in rec["links"] and set(_changed(before, _left(tmp_path, env))) == {"<installs>"}
    else:
        with pytest.raises(install.InstallError, match="isn't a link AppKata made"):
            act()
        assert _changed(before, _left(tmp_path, env)) == {}
    assert (os.readlink(link) if link.is_symlink() else link.read_text()) == was
    assert os.path.islink(link) is (theirs != "a file")


# ---------------------------------------------------------------- a folder as Settings holds it (CR1.3-32)

@linux_only
@pytest.mark.parametrize("typed", ["$HOME", "${HOME}", "~", "$HOME/../home", "$ELSEWHERE/there"])
def test_a_folder_typed_in_settings_is_read_one_way_for_the_apps_and_for_their_command_links(env, server, tmp_path, monkeypatch, typed):
    # CR1.3-32: the install folder had `~` and `$VARIABLES` expanded, the command links folder `~`
    # alone, so one typed as `$HOME/bin` was a folder named `$HOME` under AppKata's working
    # directory, with the command link in it and that relative path in the record. Every test gave
    # both folders as absolute paths, and each was read by its own expression (a third on Windows).
    # They are read by one now, so each spelling here names the same place for both, the record
    # holds absolute paths, and nothing is made in the working directory.
    home, cwd = tmp_path / "home", tmp_path / "cwd"
    home.mkdir()
    cwd.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("ELSEWHERE", str(tmp_path / "else where"))
    monkeypatch.chdir(cwd)
    base = tmp_path / "else where" / "there" if "ELSEWHERE" in typed else home
    p = install.Portable(folder=f"{typed}/apps", command_dir=f"{typed}/bin")
    a = _appimage(server)
    rec = install.install(env, APP, a, "appimage", [a], portable=p)
    assert rec["links"] == [str(base / "apps" / "demo-tool" / "DemoTool.AppImage"), str(base / "bin" / "demo-tool")]
    assert (p.root, p.command_folder) == (str(base / "apps"), str(base / "bin"))
    assert os.path.realpath(base / "bin" / "demo-tool") == str(base / "apps" / "demo-tool" / "t-1.2.0.AppImage")
    assert rec["root"] == str(base / "apps") and os.listdir(cwd) == []
    install.uninstall(env, APP["url"])
    assert not os.path.lexists(base / "bin" / "demo-tool") and not os.path.lexists(base / "apps" / "demo-tool") and os.listdir(cwd) == []
    # a relative folder is under the working directory, for both; and no command link has no folder
    rel = install.Portable(folder="rel/apps", command_dir="rel/bin")
    assert (rel.root, rel.command_folder) == (str(cwd / "rel" / "apps"), str(cwd / "rel" / "bin"))
    assert install.Portable(command_dir="").command_folder == ""


# ---------------------------------------------------------------- what an option made, once it is off (CR1.3-14)

_OPTIONS = {"the app menu": {"app_menu": False}, "the stable name": {"stable_name": False}, "the command link": {"command_dir": ""}}


@linux_only
@pytest.mark.parametrize("road", ["an update", "the next start", "a kept version"])
@pytest.mark.parametrize("off", list(_OPTIONS))
def test_what_an_option_made_goes_when_it_is_turned_off_and_nothing_outlasts_uninstall(env, server, tmp_path, off, road):
    # CR1.3-14: each time an app is activated its record forgot its menu entry, and the entry was
    # written again only while the app-menu option was on; nothing deleted the file. Turned off in
    # Install options, the entry stayed in the desktop's menu, in no record, and outlasted the
    # uninstall, starting a program that was gone. The class is what any of an app's three options
    # made (R4.3.1.6) once the option is off, by each road an app is activated again, and R4.7's
    # "uninstalling reverses what AppKata recorded": after it, nothing of the app is left anywhere.
    # The stable name and the command link held this already.
    from dataclasses import replace
    nothing = _left(tmp_path, env)
    on = install.Portable(folder=str(tmp_path / "apps"), command_dir=str(tmp_path / "cmd"))
    for v in ("1.0", "1.1"):
        a = _appimage(server, f"Tool-{v}-x86_64.AppImage", v.encode())
        rec = install.install(env, {**APP, "installVersion": v}, a, "appimage", [a], portable=on)
    made = {"the app menu": str(tmp_path / "xdg" / "applications" / "appkata-demo-tool.desktop"),
            "the stable name": str(tmp_path / "apps" / "demo-tool" / "DemoTool.AppImage"),
            "the command link": str(tmp_path / "cmd" / "demo-tool")}
    assert all(os.path.lexists(path) and path in rec["files"] + rec["links"] for path in made.values())    # made, and in the record
    p = replace(on, **_OPTIONS[off])
    a = _appimage(server, "Tool-2.0-x86_64.AppImage", b"2.0")
    rec = {"an update": lambda: install.install(env, {**APP, "installVersion": "2.0"}, a, "appimage", [a], portable=p),
           "the next start": lambda: install.rewrite_launcher(env, dict(APP), p),
           "a kept version": lambda: install.switch_to(env, dict(APP), "1.0", p)}[road]()
    for what, path in made.items():
        assert os.path.lexists(path) is (what != off), what
        assert (path in rec["files"] + rec["links"]) is (what != off), what
    assert rec == json.loads(env.one("SELECT record FROM installs")["record"])
    install.uninstall(env, APP["url"])
    assert _changed(nothing, _left(tmp_path, env)) == {}


@linux_only
def test_an_update_that_shows_the_app_to_be_a_command_line_tool_takes_its_menu_entry_away(env, server, tmp_path):
    # CR1.3-14's other road: the option came from Settings' default, and the new version's program
    # shows a command-line tool, which gets no menu entry (R4.3.1.1). The entry 1.0 had, as an app
    # with a window, goes with the update.
    from test_appkind import make_elf
    root, base = server
    nothing = _left(tmp_path, env)
    entry = tmp_path / "xdg" / "applications" / "appkata-tool.desktop"
    p = install.Portable(folder=str(tmp_path / "apps"))
    for v, libs in (("1.0", ["libgtk-3.so.0", "libc.so.6"]), ("2.0", [])):
        make_elf(tmp_path / "prog", libs)
        body = (tmp_path / "prog").read_bytes()
        (tmp_path / "prog").unlink()
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tf:
            info = tarfile.TarInfo(f"tool-{v}/tool")
            info.size, info.mode = len(body), 0o755
            tf.addfile(info, io.BytesIO(body))
        (root / f"tool-{v}.tar.gz").write_bytes(buf.getvalue())
        a = Asset(f"tool-{v}.tar.gz", f"{base}/tool-{v}.tar.gz")
        rec = install.install(env, {**APP, "name": "tool", "menuFromDefault": True, "installVersion": v}, a, "tarball", [a], portable=p)
        assert rec["appKind"] == ("gui" if libs else "cli") and rec["options"]["appMenu"] is bool(libs)
        assert entry.exists() is bool(libs) and (str(entry) in rec["files"]) is bool(libs)
    install.uninstall(env, APP["url"])
    assert _changed(nothing, _left(tmp_path, env)) == {}


# ---------------------------------------------------------------- the install folder setting changes (CR1.3-12)

def _inside(path, folder):
    return (os.path.realpath(path) + os.sep).startswith(os.path.realpath(folder) + os.sep)


def _version(server, kind, v):
    """Version `v` of the test's app on the web server, as an AppImage or an archive."""
    if kind == "appimage":
        return _appimage(server, f"Tool-{v}-x86_64.AppImage", v.encode())
    return _tarball(server, f"tool-{v}.tar.gz", {f"tool-{v}/tool": 0o755})


@linux_only
@pytest.mark.parametrize("sandboxed", [False, True], ids=["unsandboxed", "sandboxed"])
@pytest.mark.parametrize("kind", ["appimage", "tarball"])
@pytest.mark.parametrize("then", ["an update", "the same version again", "a kept version", "the next start"])
def test_an_installed_app_stays_in_its_folder_when_the_install_folder_setting_changes(env, server, tmp_path, then, kind, sandboxed):
    # CR1.3-12, the owner's decision: an installed app keeps its folder through its updates, and only
    # a new install goes to the folder Settings names now. An update did keep the files where they
    # were, but wrote the new folder into the record as the app's root: uninstalling then took the
    # app's own folder for one outside its root and left every version on disk, saying nothing, and
    # a sandboxed app's launcher went to <new folder>/<app>/run, away from its files and in no
    # record. Every test installed, updated and uninstalled with one folder. The class is whatever
    # AppKata does to an installed app after the setting changed -- an update, the same version
    # again, a kept version, the launcher rewritten at a sandbox change or a start -- for both
    # layouts, with a launcher and without: all of the app is where it was, the record says so,
    # nothing is made in the new folder, and uninstalling leaves nothing.
    from appkata_core import sandbox
    nothing = _left(tmp_path, env)
    old, new, cmd = tmp_path / "apps", tmp_path / "elsewhere", tmp_path / "cmd"
    app = {**APP, **({"sandbox": sandbox.resolve_template("standard")} if sandboxed else {})}
    was, now = install.Portable(folder=str(old), command_dir=str(cmd)), install.Portable(folder=str(new), command_dir=str(cmd))
    for v in ("1.0", "1.1"):
        a = _version(server, kind, v)
        install.install(env, {**app, "installVersion": v}, a, kind, [a], portable=was)
    a = _version(server, kind, "1.1" if then == "the same version again" else "2.0")
    rec = {"an update": lambda: install.install(env, {**app, "installVersion": "2.0"}, a, kind, [a], portable=now),
           "the same version again": lambda: install.install(env, {**app, "installVersion": "1.1"}, a, kind, [a], portable=now),
           "a kept version": lambda: install.switch_to(env, dict(app), "1.0", now),
           "the next start": lambda: install.rewrite_launcher(env, dict(app), now)}[then]()
    home = old / "demo-tool"
    assert not os.path.lexists(new)
    assert (rec["root"], rec["target"]) == (str(old), str(home))
    assert rec["current"]["version"] == {"an update": "2.0", "a kept version": "1.0"}.get(then, "1.1")
    its = [rec["current"]["path"], rec["exec"], *(k["path"] for k in rec["kept"]), *(l for l in rec["links"] if os.path.dirname(l) != str(cmd)),
           *(f for f in rec["files"] if not f.endswith(".desktop"))]
    assert all(_inside(p, home) or p == str(home) for p in its) and all(os.path.lexists(p) for p in its), its
    assert _inside(cmd / "demo-tool", home)                    # the command link leads to the app where it is
    assert (rec.get("launcher") == str(home / "run")) is sandboxed and os.path.exists(home / "run") is sandboxed
    if sandboxed:               # and it is the launcher AppKata would write: the next start has nothing to rewrite
        assert rec["exec"] == rec["launcher"] and install.launcher_is_current(rec, app, now)
    assert rec == json.loads(env.one("SELECT record FROM installs")["record"])
    # a new install goes to the folder Settings names now
    b = _appimage(server, "Other-1.0-x86_64.AppImage", b"other")
    other = install.install(env, {**APP, "url": APP["url"] + "-other", "name": "Other"}, b, "appimage", [b], portable=now)
    assert (other["root"], other["target"]) == (str(new), str(new / "other")) and _inside(other["exec"], new / "other")
    # and each is uninstalled from where it is, every version, with nothing to report
    assert install.uninstall(env, APP["url"], remove_sandbox=True) == [] and install.uninstall(env, APP["url"] + "-other") == []
    assert not os.path.lexists(home) and not os.path.lexists(new / "other")
    left = _changed(nothing, _left(tmp_path, env))
    assert all(k.startswith(os.path.join("data", "sandboxes", ".owners")) for k in left), left      # whose a kept home is (R17.14)


@linux_only
@pytest.mark.parametrize("left", ["the app's folder", "what the user put where the command link was"])
def test_uninstalling_says_what_it_did_not_remove(env, server, tmp_path, monkeypatch, left):
    # CR1.3-12's other half: uninstalling skipped a folder that wasn't inside the record's root and
    # deleted the app's row with no word of it, so nothing AppKata showed knew of the files again.
    # It still removes only what is AppKata's (a folder inside the install folder the app was
    # installed into, a link that leads there), and now returns what the record names and is still
    # there, which the notice names: a folder that couldn't be deleted, and the user's own file
    # where the command link was (R4.3.1.3: "uninstalling leaves it").
    a = _appimage(server, "Tool-1.0-x86_64.AppImage", b"1.0")
    p = install.Portable(folder=str(tmp_path / "apps"), command_dir=str(tmp_path / "cmd"))
    install.install(env, {**APP, "installVersion": "1.0"}, a, "appimage", [a], portable=p)
    home, link = tmp_path / "apps" / "demo-tool", tmp_path / "cmd" / "demo-tool"
    if left == "the app's folder":
        monkeypatch.setattr(install.shutil, "rmtree", lambda *a, **k: None)          # as a folder that can't be deleted
    else:
        link.unlink()
        link.write_text("mine")
    want = home if left == "the app's folder" else link
    assert install.uninstall(env, APP["url"]) == [str(want)]
    assert env.one("SELECT * FROM installs") is None and os.path.lexists(want)
    assert os.path.lexists(home) is (want == home) and os.path.lexists(link) is (want == link)
    assert not os.path.lexists(tmp_path / "xdg" / "applications" / "appkata-demo-tool.desktop")
    pytest.importorskip("PySide6")                              # the notice is the backend's; the Windows run has none
    from appkata.backend import Backend
    assert Backend._left_note([str(want)]) == f" Not removed: {want}." and Backend._left_note([]) == ""
    assert Backend._left_note(["/a", "/b"]) == " Not removed: /a, /b."


# ---------------------------------------------------------------- the installed version, until the new one is in (CR1.3-13)

# a release's file name for every version, and the versions: what each is kept as
_ONE_NAME = [("Tool-x86_64.AppImage", ("1.0", "2.0", "3.0"), "Tool-x86_64-{}.AppImage"),
             ("nvim-linux-x86_64.appimage", ("0.9.5", "0.10.0", "0.10.1"), "nvim-linux-x86_64-{}.appimage"),
             ("DemoTool.AppImage", ("1.0", "2.0", "3.0"), "DemoTool-{}.AppImage"),            # the stable link's own name
             ("Tool-x86_64.AppImage", ("64", "86", "100"), None),                             # versions the name seems to hold
             ("Tool-ubuntu-22.04-x86_64.AppImage", ("1.0", "2.0", "3.0"), None)]              # a number that is no version


@linux_only
@pytest.mark.parametrize("name,versions,stored", _ONE_NAME, ids=[f"{n} {'-'.join(v)}" for n, v, _ in _ONE_NAME])
def test_each_version_of_an_appimage_released_under_one_name_is_kept_as_its_own_file(env, server, tmp_path, name, versions, stored):
    # CR1.3-13 (a): an AppImage was kept under the release's file name, and many projects use one
    # name for every version (Tool-x86_64.AppImage). The update then deleted the installed version's
    # file and put its own there, before anything else had succeeded, and the record's kept entry
    # for it was dropped as "the current file": no version was ever kept, so the Versions list
    # couldn't go back without a download (R4.3.1.5), and the tests' names all held their version.
    # A version is now kept under the release's name when that holds a version, and with the
    # version added when it doesn't; and no version is ever placed where another one of the app's
    # is, whatever its name seems to hold (the last cases: "64" and "86" are both in x86_64, and
    # 22.04 is no version of the app).
    nothing = _left(tmp_path, env)
    p = install.Portable(folder=str(tmp_path / "apps"), command_dir=str(tmp_path / "cmd"), keep=2)
    folder, cmd = tmp_path / "apps" / "demo-tool", tmp_path / "cmd" / "demo-tool"
    for v in versions:
        a = _appimage(server, name, v.encode())                 # the same name, the next version's bytes
        rec = install.install(env, {**APP, "installVersion": v}, a, "appimage", [a], portable=p)
        assert cmd.read_bytes() == v.encode() and (folder / "DemoTool.AppImage").read_bytes() == v.encode()
    files = {f.name: f.read_bytes() for f in folder.iterdir() if not f.is_symlink()}
    assert sorted(files.values()) == sorted(v.encode() for v in versions) and len(files) == 3, files
    if stored:
        assert files == {stored.format(v): v.encode() for v in versions}
    assert [k["version"] for k in rec["kept"]] == [versions[1], versions[0]] == install.kept_versions(env, APP["url"])
    assert all(open(k["path"], "rb").read() == k["version"].encode() for k in rec["kept"] + [rec["current"]])
    rec = install.switch_to(env, dict(APP), versions[0], p)                # back, without a download
    assert cmd.read_bytes() == versions[0].encode() and install.kept_versions(env, APP["url"]) == [versions[2], versions[1]]
    a = _appimage(server, name, b"4.0")
    rec = install.install(env, {**APP, "installVersion": "4.0"}, a, "appimage", [a], portable=p)
    files = {f.name: f.read_bytes() for f in folder.iterdir() if not f.is_symlink()}
    assert sorted(files.values()) == sorted([b"4.0", versions[0].encode(), versions[2].encode()]), files       # two kept, the oldest gone
    assert install.uninstall(env, APP["url"]) == [] and _changed(nothing, _left(tmp_path, env)) == {}


@pytest.mark.parametrize("asset,version,kept_as", [
    ("LocalSend-1.18.2-x86_64.AppImage", "1.18.2", "LocalSend-1.18.2-x86_64.AppImage"),
    ("Tool-v2-x86_64.AppImage", "2", "Tool-v2-x86_64.AppImage"),
    ("Tool-26.11.AppImage", "2026.11", "Tool-26.11.AppImage"),          # a version, in the project's own spelling
    ("Tool-x86_64.AppImage", "2.0", "Tool-x86_64-2.0.AppImage"),
    ("Tool.AppImage", "1.2", "Tool-1.2.AppImage"),
    ("Tool-2-x86_64.AppImage", "2.1", "Tool-2-x86_64-2.1.AppImage"),
    ("Tool-12-x86_64.AppImage", "2", "Tool-12-x86_64-2.AppImage"),      # another number's digits aren't this version
    ("tool.appimage", "nightly/2026 11", "tool-nightly_2026_11.appimage"),
    ("Tool.AppImage", "", "Tool-unknown.AppImage")])
def test_the_name_a_version_of_an_appimage_is_kept_under(asset, version, kept_as):
    assert install._appimage_name(asset, version) == kept_as
    stem, ext = os.path.splitext(asset)                 # and with the version whatever the name holds, when it is another's
    assert install._appimage_name(asset, version, versioned=True) == f"{stem}-{install._safe(version)}{ext}"


_ROADS = ["an app that updates itself", "the same version again", "an app that updates itself from now on",
          "an update that retires a kept version"]
_FAILS = ["an archive with no program", "putting it in place", "the menu entry", "the command link", "the record"]


@linux_only
@pytest.mark.parametrize("road", _ROADS)
@pytest.mark.parametrize("fails,kind", [(f, k) for f in _FAILS for k in ("appimage", "tarball")
                                        if (f, k) != ("an archive with no program", "appimage")])     # an AppImage is one file
def test_the_versions_an_app_has_are_there_until_the_new_one_is_installed(env, server, tmp_path, monkeypatch, fails, road, kind):
    # CR1.3-13 (b), and its class. R4.6: an update "keeps the previous version's files until the
    # update succeeds". For an app that updates itself, install() deleted the installed version, and
    # every kept one, before the new file was placed or unpacked: an archive with no program, or a
    # full disk, and the app was gone, under a record that still named it. The class is every
    # deletion an update makes before its record is stored. There were three more: the installed
    # version's own file or folder when the new one has its name (a fixed name, R4.10.2, and the
    # same version installed again), deleted by _place before the new one was in; the versions of
    # an app that updates itself from now on; and the kept version an update retires (Keep older
    # versions, R4.3.1.5), deleted before the record that drops it was stored. So each road here
    # is made to fail at each step after the download, and afterwards every file, link and folder
    # and the installs table are what they were; then the same update succeeds and leaves nothing
    # set aside, and uninstalling leaves nothing at all.
    nothing = _left(tmp_path, env)
    cmd, home = tmp_path / "cmd", tmp_path / "apps" / "demo-tool"
    p = install.Portable(folder=str(tmp_path / "apps"), command_dir=str(cmd), keep=1 if road == "an update that retires a kept version" else 2)
    itself = road == "an app that updates itself"
    for v in ("1.0",) if itself else ("1.0", "1.1"):
        a = _version(server, kind, v)
        install.install(env, {**APP, "installVersion": v, "autoUpdate": itself}, a, kind, [a], portable=p)
    new = "1.1" if road == "the same version again" else "2.0"
    app = {**APP, "installVersion": new, "autoUpdate": road.startswith("an app that updates itself")}
    # the new download: other bytes than any installed version's, under the same version's name too
    good = (_appimage(server, f"Tool-{new}-x86_64.AppImage", b"downloaded again") if kind == "appimage"
            else _tarball(server, f"tool-{new}.tar.gz", {f"tool-{new}/tool": 0o755, f"tool-{new}/NEWS": 0o644}))
    bad = _tarball(server, f"tool-{new}-bad.tar.gz", {f"tool-{new}/README": 0o644}) if fails == "an archive with no program" else good
    before = _left(tmp_path, env)
    with monkeypatch.context() as m:
        if fails == "putting it in place":
            m.setattr(install.os, "replace", _failing_once(os.replace, lambda src, dst: src.endswith(".new")))
        elif fails == "the menu entry":
            m.setattr(install, "_desktop_entry", _failing_once(install._desktop_entry))
        elif fails == "the command link":
            m.setattr(install, "_link", _failing_once(install._link, lambda target, link, own=None: os.path.dirname(link) == str(cmd)))
        elif fails == "the record":
            m.setattr(env, "x", _failing_once(env.x, lambda sql, *a: sql.startswith(("INSERT OR REPLACE INTO installs", "UPDATE installs"))))
        with pytest.raises((install.InstallError, OSError), match="couldn't find the program" if bad is not good else "No space left"):
            install.install(env, app, bad, kind, [bad], portable=p)
    assert _changed(before, _left(tmp_path, env)) == {}
    rec = install.install(env, app, good, kind, [good], portable=p)            # and the update itself goes through
    assert rec["current"]["version"] == new and os.access(rec["exec"], os.X_OK)
    assert [k["version"] for k in rec["kept"]] == {"an app that updates itself": [], "the same version again": ["1.0"],
                                                   "an app that updates itself from now on": [], "an update that retires a kept version": ["1.1"]}[road]
    assert sorted(n for n in os.listdir(home) if not os.path.islink(home / n) and not n.endswith(".extracted")) == \
        sorted(os.path.relpath(k["path"], home) for k in [rec["current"]] + rec["kept"]), os.listdir(home)
    assert install.uninstall(env, APP["url"]) == [] and _changed(nothing, _left(tmp_path, env)) == {}


# ---------------------------------------------------------------- an update that fails part-way (CR1.3-37)

_PART_WAY = {"its checksum": "doesn't match its checksum", "a Cancel once it is downloaded": "cancelled",
             "placing it": "No space left|couldn't find the program", "its command link": "No space left"}


def _runs(path):
    """What the program at `path` prints: the test's versions are scripts that say which they are."""
    return subprocess.run([str(path)], capture_output=True, text=True, timeout=30).stdout.strip()


@linux_only
@pytest.mark.parametrize("kind", ["appimage", "tarball"])
@pytest.mark.parametrize("fails", list(_PART_WAY))
def test_an_update_that_fails_part_way_leaves_the_previous_version_running_and_no_download(env, server, tmp_path, monkeypatch, fails, kind):
    # CR1.3-37: no test failed an update part-way and looked at what was left. R4.6: the previous
    # version still runs, through its links, and the record is the one it had; R4.8.2: "a complete
    # file that fails its checksum or its install is deleted" (the checksum test looked only at the
    # apps folder, so the `finally` that deletes it could go unnoticed); R4.8.3: a Cancel before
    # the Installing phase deletes the download and installs nothing (the Cancel test called
    # download() alone); and the staging folder of a version that couldn't be placed is gone.
    # CR1.3-13 and CR1.3-15 were two ways the first of these didn't hold. The update fails here at
    # each point after its download is complete, in turn, and each is looked at by name, as well
    # as by the snapshot of everything; then the same update goes through.
    root, base = server
    cmd, home = tmp_path / "cmd" / "demo-tool", tmp_path / "apps" / "demo-tool"
    p = install.Portable(folder=str(tmp_path / "apps"), command_dir=str(tmp_path / "cmd"))

    def release(v, name=None, program=True):
        script = f"#!/bin/sh\necho {v}\n".encode()
        if kind == "appimage":
            return _appimage(server, name or f"Tool-{v}-x86_64.AppImage", script)
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tf:
            info = tarfile.TarInfo(f"tool-{v}/tool" if program else f"tool-{v}/README")
            info.size, info.mode = len(script), 0o755 if program else 0o644
            tf.addfile(info, io.BytesIO(script))
        (root / (name or f"tool-{v}.tar.gz")).write_bytes(buf.getvalue())
        return Asset(name or f"tool-{v}.tar.gz", f"{base}/{name or f'tool-{v}.tar.gz'}")

    for v in ("1.0", "1.1"):
        a = release(v)
        was = install.install(env, {**APP, "installVersion": v}, a, kind, [a], portable=p)
    assert _runs(cmd) == _runs(was["exec"]) == "1.1" and _downloads() == []
    row = dict(env.one("SELECT * FROM installs"))
    there = sorted(os.listdir(home))
    before = _left(tmp_path, env)
    good = release("2.0")
    bad, cancel = good, None
    with monkeypatch.context() as m:
        if fails == "its checksum":
            bad = Asset(good.name, good.url, good.size, "sha256:" + hashlib.sha256(b"what the project released").hexdigest())
        elif fails == "a Cancel once it is downloaded":         # asked for while it downloads, it says no; then yes
            cancel = lambda: os.path.exists(os.path.join(install.downloads_dir(), "demo-tool", good.name))    # noqa: E731
        elif fails == "placing it" and kind == "tarball":
            bad = release("2.0", "tool-2.0-no-program.tar.gz", program=False)
        elif fails == "placing it":
            m.setattr(install.os, "replace", _failing_once(os.replace, lambda src, dst: src.endswith(".new")))
        else:
            m.setattr(install, "_link", _failing_once(install._link, lambda target, link, own=None: link == str(cmd)))
        with pytest.raises((install.InstallError, OSError), match=_PART_WAY[fails]) as e:
            install.install(env, {**APP, "installVersion": "2.0"}, bad, kind, [bad], cancel=cancel, portable=p)
    assert isinstance(e.value, install.Cancelled) is (fails == "a Cancel once it is downloaded")
    assert _runs(cmd) == _runs(was["exec"]) == "1.1"                            # the previous version, through its links
    assert os.readlink(cmd) == was["exec"] and all(os.path.islink(l) for l in was["links"])
    assert dict(env.one("SELECT * FROM installs")) == row                       # its record, and the version AppKata shows
    assert install.kept_versions(env, APP["url"]) == ["1.0"]
    assert _downloads() == []                                                   # the complete file is deleted (R4.8.2, R4.8.3)
    assert sorted(os.listdir(home)) == there                                    # no 2.0, no staging folder, nothing set aside
    assert _changed(before, _left(tmp_path, env)) == {}
    rec = install.install(env, {**APP, "installVersion": "2.0"}, good, kind, [good], portable=p)
    assert _runs(cmd) == _runs(rec["exec"]) == "2.0" and [k["version"] for k in rec["kept"]] == ["1.1", "1.0"] and _downloads() == []


# ---------------------------------------------------------------- back to the fixed name, sandbox Off (CR1.11-41)

@linux_only
@pytest.mark.parametrize("kind", ["appimage", "tarball"])
@pytest.mark.parametrize("fails", ["the menu entry", "the command link", "the record"])
def test_a_move_back_to_the_fixed_name_that_fails_leaves_the_app_in_its_version_folders(env, server, tmp_path, monkeypatch, fails, kind):
    # CR1.11-41's other side. Turning the sandbox Off for an app that updates itself renames its
    # current version to R4.10.2's fixed name and drops its kept versions (R4.10.5); the proof of
    # that road is in tests/test_sandbox_transitions.py. It is the one change to an installed
    # app's files that isn't an install, so it has R4.6's rule to keep on its own: when a step
    # after the rename fails, the version folders, the links, the launcher, the kept versions and
    # the record are what they were; and then the move goes through.
    from appkata_core import sandbox
    cmd, home = tmp_path / "cmd", tmp_path / "apps" / "demo-tool"
    p = install.Portable(folder=str(tmp_path / "apps"), command_dir=str(cmd))
    gs = sandbox.resolve_template("standard")
    a = _version(server, kind, "1.0")
    install.install(env, {**APP, "installVersion": "1.0", "autoUpdate": True}, a, kind, [a], portable=p)       # runs Off: the fixed name
    install.rewrite_launcher(env, {**APP, "autoUpdate": True, "sandbox": gs}, p)                              # sandboxed
    a = _version(server, kind, "2.0")
    was = install.install(env, {**APP, "installVersion": "2.0", "sandbox": gs}, a, kind, [a], portable=p)      # AppKata's update (R17.12)
    assert not was.get("selfUpdating") and [k["version"] for k in was["kept"]] == ["1.0"] and was["launcher"]
    before = _left(tmp_path, env)
    with monkeypatch.context() as m:
        if fails == "the menu entry":
            m.setattr(install, "_desktop_entry", _failing_once(install._desktop_entry))
        elif fails == "the command link":
            m.setattr(install, "_link", _failing_once(install._link, lambda target, link, own=None: os.path.dirname(link) == str(cmd)))
        else:
            m.setattr(env, "x", _failing_once(env.x, lambda sql, *a: sql.startswith("UPDATE installs")))
        with pytest.raises(OSError, match="No space left"):
            install.rewrite_launcher(env, {**APP, "autoUpdate": True, "sandbox": None}, p)
    assert _changed(before, _left(tmp_path, env)) == {}
    rec = install.rewrite_launcher(env, {**APP, "autoUpdate": True, "sandbox": None}, p)
    fixed = "DemoTool.AppImage" if kind == "appimage" else "app"
    assert sorted(os.listdir(home)) == [fixed] and rec["selfUpdating"] and rec["kept"] == [] and "launcher" not in rec
    assert rec["current"]["path"] == str(home / fixed) and os.access(rec["exec"], os.X_OK) and os.readlink(cmd / "demo-tool") == rec["exec"]
    assert rec == json.loads(env.one("SELECT record FROM installs")["record"])
    # an app that doesn't update itself stays in its version folders when its sandbox is turned Off,
    # and so does one that never had a launcher
    assert install.rewrite_launcher(env, {**APP, "sandbox": None}, p) == rec
    b = _appimage(server, "Other-1.0-x86_64.AppImage", b"other")
    other = {**APP, "url": APP["url"] + "-other", "name": "Other"}
    for sbx, auto in ((gs, False), (None, True)):
        install.install(env, {**other, "sandbox": sbx}, b, "appimage", [b], portable=p)
        rec = install.rewrite_launcher(env, {**other, "autoUpdate": auto, "sandbox": None}, p)
        assert not rec.get("selfUpdating") and rec["current"]["path"].endswith("Other-1.0-x86_64.AppImage") and os.path.islink(rec["exec"])


# ---------------------------------------------------------------- a change to an installed app, its command link's place taken (CR1.3-46)

_CHANGES = {"its sandbox turned on": (None, "standard"), "its sandbox turned Off": ("standard", None), "its sandbox changed": ("standard", "strict")}


@linux_only
@pytest.mark.parametrize("on_path", [False, True], ids=["off the PATH", "on the PATH"])
@pytest.mark.parametrize("theirs", _THEIRS)
@pytest.mark.parametrize("change", list(_CHANGES))
def test_a_sandbox_change_is_made_whole_when_the_user_has_taken_the_command_links_place(env, server, tmp_path, monkeypatch, change, theirs, on_path):
    # CR1.3-46: an install checks the command link's place before it changes anything (CR1.3-15).
    # The launcher's rewrite -- a sandbox change from the Sandbox dialog or Install options, and the
    # startup pass -- did its steps in the old order: the launcher and the menu entry rewritten,
    # then the command link, and with something of the user's at that place it stopped there with
    # the error, its record not stored. Turned Off, the launcher was deleted and AppKata's own Open
    # still started it, by the record; turned on, the menu started the app sandboxed and Open
    # didn't. Checking first would leave the old launcher under the new choice, and the launcher is
    # the enforcement (R17.4), so the rewrite is made in full, without the command link, and the
    # record says why there is none. Afterwards the launcher, the menu entry, the record and what
    # AppKata starts agree, the user's file is as it was, and the link comes once its place is free.
    from appkata_core import sandbox
    cmd, home, their_program = tmp_path / "cmd", tmp_path / "apps" / "demo-tool", tmp_path / "opt" / "their-tool"
    their_program.parent.mkdir()
    their_program.write_text("#!/bin/sh\necho theirs\n")
    their_program.chmod(0o755)
    if on_path:
        monkeypatch.setenv("PATH", f"{cmd}:{os.environ['PATH']}")
    before, after = (sandbox.resolve_template(t) if t else None for t in _CHANGES[change])
    p = install.Portable(folder=str(tmp_path / "apps"), command_dir=str(cmd))
    a = _appimage(server, "Tool-1.0-x86_64.AppImage", b"#!/bin/sh\necho 1.0\n")
    was = install.install(env, {**APP, "installVersion": "1.0", "sandbox": before}, a, "appimage", [a], portable=p)
    link, entry = cmd / "demo-tool", tmp_path / "xdg" / "applications" / "appkata-demo-tool.desktop"
    assert os.readlink(link) == was["exec"] and ("launcher" in was) is bool(before)
    link.unlink()
    if theirs == "a file":
        link.write_text("mine")
    else:
        link.symlink_to(their_program if theirs == "a link to their own program" else tmp_path / "gone" / "tool")
    kept_as = os.readlink(link) if link.is_symlink() else link.read_text()

    rec = install.rewrite_launcher(env, {**APP, "sandbox": after}, p)
    assert rec == json.loads(env.one("SELECT record FROM installs")["record"])            # what was done is what is recorded
    launcher = home / "run"
    if after:
        assert rec["launcher"] == rec["exec"] == str(launcher) and rec["sandbox"] == sandbox.to_json(after)
        assert install.launcher_is_current(rec, {**APP, "sandbox": after}, p)               # the grant set chosen, enforced
    else:
        assert not os.path.lexists(launcher) and "launcher" not in rec and "sandbox" not in rec
        assert rec["exec"] == str(home / "DemoTool.AppImage") and _runs(rec["exec"]) == "1.0"
    assert os.access(rec["exec"], os.X_OK)                                                  # what AppKata's Open starts
    assert _exec_words(_entry(entry)["Desktop Entry"]["Exec"])[0] == rec["exec"]            # and what the menu starts
    assert (os.readlink(link) if link.is_symlink() else link.read_text()) == kept_as and str(link) not in rec["links"]
    assert rec["options"]["commandLink"] is True and rec["commandRefused"] == (
        f"demo-tool is already a command on this computer ({link})" if on_path and theirs == "a link to their own program"
        else f"{link} exists and isn't a link AppKata made; not replacing it")
    link.unlink()                                                                           # the place is free again
    rec = install.rewrite_launcher(env, {**APP, "sandbox": after}, p)
    assert "commandRefused" not in rec and os.readlink(link) == rec["exec"] and str(link) in rec["links"]
    assert install.uninstall(env, APP["url"], remove_sandbox=True) == []


# ---------------------------------------------------------------- the program of an archive (CR1.3-17)

_ELF, _SCRIPT = b"\x7fELF\x02\x01\x01" + b"\0" * 57, b"#!/bin/sh\nexec true\n"

# Archives as their publishers lay them out: what is in them (a path, and its kind: an ELF, a script,
# or a text file's own content), the app's names (its own and its repository's), and the program.
_ARCHIVES = {
    # CR1.3-17: no file is named after the app, and Chromium's helpers sort first
    "VSCodium, unpacked flat": ({"chrome-sandbox": _ELF, "chrome_crashpad_handler": _ELF, "codium": _ELF,
                                 "bin/codium": _SCRIPT, "libffmpeg.so": _ELF, "resources/app/out/cli.js": None},
                                ["VSCodium", "vscodium"], "codium"),
    "its own .desktop file names it": ({"bin/zed": _SCRIPT, "libexec/zed-editor": _ELF, "share/applications/dev.zed.desktop":
                                        b"[Desktop Entry]\nType=Application\nName=Zed\nExec=env ZED_X=1 /opt/zed/libexec/zed-editor %U\n"},
                                       ["Zed", "zed"], "libexec/zed-editor"),
    "a compiled program before a script": ({"tool": _SCRIPT, "lib/tool": _ELF}, ["Tool", "tool"], "lib/tool"),
    "a helper sorts first and is never taken": ({"chrome-sandbox": _ELF, "chrome_crashpad_handler": _ELF, "x/editor": _ELF},
                                                ["Notes", "notes"], "x/editor"),
    "a program and its -bin": ({"firefox": _ELF, "firefox-bin": _ELF, "libxul.so": _ELF, "crashreporter": _ELF,
                                "updater": _ELF, "glxtest": _ELF}, ["Firefox", "firefox"], "firefox"),
    "an app with no repository": ({"aaa": _ELF, "sub/thingapp": _ELF}, ["Thing", ""], "sub/thingapp"),
    "nothing but its own program": ({"rg": _ELF, "doc/rg.1": None, "complete/rg.bash": None}, ["ripgrep", "ripgrep"], "rg"),
}


def _archive(folder, files):
    for path, body in files.items():
        p = folder / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(body if body is not None else b"text\n")
        p.chmod(0o755 if body in (_ELF, _SCRIPT) else 0o644)


@linux_only
@pytest.mark.parametrize("archive", list(_ARCHIVES))
def test_the_program_of_an_archive_is_the_one_its_desktop_file_its_name_or_its_kind_says(tmp_path, archive):
    # CR1.3-17: by name alone, then by depth and alphabet, VSCodium's program was chrome-sandbox,
    # and the menu entry, the command link and the app's kind (R17.3.3) all took the helper. The
    # archive's own .desktop file names its program, a name the app's name holds counts, a compiled
    # program comes before a script, and a helper is never the program.
    files, names, program = _ARCHIVES[archive]
    _archive(tmp_path / "v", files)
    assert install._find_executable(str(tmp_path / "v"), names) == str(tmp_path / "v" / program)


@linux_only
def test_an_archive_with_nothing_but_helpers_has_no_program(tmp_path):
    _archive(tmp_path / "v", {"chrome-sandbox": _ELF, "chrome_crashpad_handler": _ELF, "libnss3.so": _ELF,
                              "libGLESv2.so.2": _ELF, "start.sh": _SCRIPT, "notes.desktop": b"[Desktop Entry]\nExec=notes\n"})
    with pytest.raises(install.InstallError, match="couldn't find the program"):
        install._find_executable(str(tmp_path / "v"), ["Notes", "notes"])


@linux_only
def test_what_an_archive_installs_starts_its_program_not_a_helper(env, server, tmp_path):
    # the whole road: the record, the menu entry and the command link start what was picked
    a = _tarball(server, "VSCodium-linux-x64-1.2.0.tar.gz", {"chrome-sandbox": 0o755, "chrome_crashpad_handler": 0o755,
                                                             "codium": 0o755, "resources/app/LICENSE.txt": 0o644})
    p = install.Portable(folder=str(tmp_path / "apps"), app_menu=True, stable_name=True,
                         command_dir=str(tmp_path / "cmd"), keep=0)
    rec = install.install(env, {**APP, "name": "VSCodium", "repo": "VSCodium/vscodium"}, a, "tarball", [a], portable=p)
    assert os.path.basename(rec["exec"]) == "codium" and _runs(rec["exec"]) == "codium"
    assert _runs(str(tmp_path / "cmd" / "vscodium")) == "codium"
    entry = _entry(tmp_path / "xdg" / "applications" / "appkata-vscodium.desktop")
    assert _runs(_exec_words(entry["Desktop Entry"]["Exec"])[0]) == "codium"
