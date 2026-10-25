"""Installing from a local web server (requirement 4), and writing reviews with git (requirement 8)."""

import hashlib
import http.server
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import threading

import pytest

from appkata_core import devtools, install, review
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
    # unsigned: committed, never pushed (requirement 8.5)
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
    """Install folder, stable name, app-menu entry and command link (requirement 4.3.1)."""
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
    """~/bin/apps/<app>/ holds each version; older ones are kept up to the setting (req 4.3.1.5)."""
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
    # AppKata's own AppImage, adopted rather than placed (requirement 2.11.3)
    paths = [tmp_path / n for n in ("new", "a", "adopted")]
    for p in paths:
        p.write_text("x")
    rec = {"current": {"path": str(paths[0])}, "kept": [{"path": str(paths[1])}, {"path": str(paths[2]), "external": True}]}
    install._retain(rec, 0)
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
    # requirement 4.8.2: the second request asks only for the rest, and the digest covers the whole file
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
    # requirement 4.10.2: one file under a stable name, nothing kept, no "current" link
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


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="the sandbox is Linux-only (17.1)")
def test_a_self_updating_app_that_runs_sandboxed_moves_to_versions_when_appkata_updates_it(env, server, tmp_path):
    # Review 2, F3: a sandboxed app can't update itself (its files are read-only), so AppKata updates
    # it as if it didn't (17.12). Its first such update leaves the fixed-name layout of 4.10.2: the
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
