"""Installing from a local web server (R4), and writing reviews with git (R8)."""

import hashlib
import http.server
import io
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import threading

import pytest

from appkata_core import assets, devtools, forges, install, review
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


_FILE = b"\x7fELF the program"
_SHA = hashlib.sha256(_FILE).hexdigest()
_OTHER = hashlib.sha256(b"another file").hexdigest()
_SHA512 = hashlib.sha512(_FILE).hexdigest()
# A release's other files, in the release's order, each with what it holds -> the one whose SHA-256 is used
_CHECKSUM_FILES = {
    "a .sha512 beside the file, and SHA256SUMS":                    # the finding's case
        ([("App.AppImage.sha512", f"{_SHA512}  App.AppImage\n"), ("SHA256SUMS", f"{_SHA}  App.AppImage\n")], "SHA256SUMS"),
    "a .sha512 beside the file, of the digest alone, and SHA256SUMS":
        ([("App.AppImage.sha512", _SHA512 + "\n"), ("SHA256SUMS", f"{_OTHER}  Other.AppImage\n{_SHA} *App.AppImage\n")], "SHA256SUMS"),
    "a list for another platform's files first":
        ([("arm64-SHA256SUMS.txt", f"{_OTHER}  App-arm64.AppImage\n"), ("x86_64-SHA256SUMS.txt", f"{_SHA}  App.AppImage\n")],
         "x86_64-SHA256SUMS.txt"),
    "a list of SHA-512 digests first":
        ([("checksums.txt", f"{_SHA512}  App.AppImage\n"), ("SHA256SUMS", f"{_SHA}  App.AppImage\n")], "SHA256SUMS"),
    "a list of MD5 digests first":
        ([("checksums", f"{hashlib.md5(_FILE).hexdigest()}  App.AppImage\n"), ("checksums.txt", f"{_SHA}  ./dist/App.AppImage\n")],
         "checksums.txt"),
    "the file's own .sha256 before any list":
        ([("SHA256SUMS", f"{_SHA}  App.AppImage\n"), ("App.AppImage.sha256", _SHA + "\n")], "App.AppImage.sha256"),
    "the file's own .sha256sum before any list":
        ([("sha256sums.txt", f"{_SHA}  App.AppImage\n"), ("App.AppImage.sha256sum", f"{_SHA}  App.AppImage\n")], "App.AppImage.sha256sum"),
    "the file's own .sha256 names another file":
        ([("App.AppImage.sha256", f"{_OTHER}  Other.AppImage\n"), ("SHA256SUMS", f"{_SHA}  App.AppImage\n")], "SHA256SUMS"),
    "a list that is missing, then one that is there":
        ([("SHA256SUMS", None), ("checksums.txt", f"{_SHA}  App.AppImage\n")], "checksums.txt"),
    "only a .sha512": ([("App.AppImage.sha512", f"{_SHA512}  App.AppImage\n")], ""),
    "only a .sha512 and a signature": ([("App.AppImage.sha512", _SHA512), ("App.AppImage.asc", "-----BEGIN PGP SIGNATURE-----")], ""),
    "no list names the file": ([("SHA256SUMS", f"{_OTHER}  Other.AppImage\n"), ("checksums.txt", f"{_SHA512}  App.AppImage\n")], ""),
    "nothing else in the release": ([], ""),
}


def _release_with(server, others, data=_FILE):
    """A release on the test's server: App.AppImage and its other files (a file whose text is None
    is listed and isn't there). -> (the file, the release's files)."""
    root, base = server
    (root / "App.AppImage").write_bytes(data)
    for name, text in others:
        if text is not None:
            (root / name).write_text(text)
    a = Asset("App.AppImage", base + "/App.AppImage")
    return a, [a] + [Asset(name, f"{base}/{name}") for name, _ in others]


@pytest.mark.parametrize("release", list(_CHECKSUM_FILES))
def test_a_file_is_checked_against_the_first_of_its_releases_checksum_files_that_lists_it(env, server, release):
    """R4.4 (CR1.3-6): "Checks the file against `SHA256SUMS`, `*.sha256` or a forge-provided digest,
    when one exists". One checksum file was picked by its name, a `<file>.sha512` before any
    `SHA256SUMS`, and only that one was read, for 64 digits: a release with both was installed
    Unverified, and a file that didn't match its `SHA256SUMS` wasn't stopped. No test had a release
    with two such files. Here each of them, in each order, as a release publishes them."""
    others, used = _CHECKSUM_FILES[release]
    a, files = _release_with(server, others)
    assert install.expected_sha256(a, files)[:2] == ((_SHA, used) if used else ("", ""))
    # the same release with another file under that name: stopped wherever a SHA-256 of it is published
    a, files = _release_with(server, others, data=b"tampered")
    if used:
        with pytest.raises(install.InstallError, match=re.escape(f"doesn't match its checksum ({used})")):
            install.install(env, APP, a, "appimage", files)
        assert _downloads() == [] and env.one("SELECT * FROM installs") is None


@linux_only
def test_a_release_with_a_sha512_and_sha256sums_is_installed_as_checked(env, server, tmp_path):
    a, files = _release_with(server, _CHECKSUM_FILES["a .sha512 beside the file, and SHA256SUMS"][0])
    rec = install.install(env, APP, a, "appimage", files, portable=install.Portable(folder=str(tmp_path / "apps"), app_menu=False))
    assert (rec["verified"], rec["checksum_source"]) == ("checksum", "SHA256SUMS")


def _long_list(end, at=1 << 20):
    """A checksum list of other files that is `at` bytes long and ends with the text `end`."""
    line = _OTHER + "  filler-{:08d}.bin\n"
    n, rest = divmod(at - len(end), len(line.format(0)))
    return "".join(line.format(i) for i in range(n - 1)) + f"{_OTHER}  {'x' * (len(line.format(0)) - 67 + rest)}\n" + end


_MINE = f"{_SHA}  App.AppImage\n"
_NO_ANSWER = "http://127.0.0.1:1/"          # nothing listens there: the connection is refused
# A release's checksum files, as _CHECKSUM_FILES has them (a text that starts "http" is where the file
# is said to be) -> what the install is checked against, and the reason kept when that is nothing
_NO_CHECKSUM = {
    "a list that answers 404": ([("SHA256SUMS", None)], "", "couldn't read SHA256SUMS (HTTP 404)"),
    "a list on a server that doesn't answer": ([("SHA256SUMS", _NO_ANSWER)], "", "couldn't read SHA256SUMS"),
    "a list without the file": ([("SHA256SUMS", f"{_OTHER}  Other.AppImage\n")], "", "SHA256SUMS doesn't list this file"),
    "a list of another kind of digest": ([("checksums.txt", f"{_SHA512}  App.AppImage\n")], "", "checksums.txt doesn't list this file"),
    "an empty list": ([("SHA256SUMS", "")], "", "SHA256SUMS doesn't list this file"),
    "the file listed after the first 1 MB":
        ([("SHA256SUMS", _long_list("") + _MINE)], "", "SHA256SUMS is longer than 1 MB, and the part AppKata reads doesn't list this file"),
    "the first 1 MB ends inside the line of a file whose name starts as this one's":
        ([("SHA256SUMS", _long_list(f"{_OTHER}  App.AppImage") + ".zsync\n" + _MINE)], "",
         "SHA256SUMS is longer than 1 MB, and the part AppKata reads doesn't list this file"),
    "the file's own .sha256 answers 404 and the list is without it":
        ([("App.AppImage.sha256", None), ("SHA256SUMS", f"{_OTHER}  Other.AppImage\n")], "",
         "couldn't read App.AppImage.sha256 (HTTP 404); SHA256SUMS doesn't list this file"),
    # ...and where there is a checksum, or no checksum file at all, there is nothing to say
    "a list that answers 404, then one with the file": ([("SHA256SUMS", None), ("checksums.txt", _MINE)], "checksums.txt", ""),
    "the file listed at the end of the first 1 MB": ([("SHA256SUMS", _long_list(_MINE) + f"{_OTHER}  later.bin\n")], "SHA256SUMS", ""),
    "a list of just 1 MB, the file on its last line": ([("SHA256SUMS", _long_list(_MINE.rstrip()))], "SHA256SUMS", ""),
    "no checksum file": ([], "", ""),
    "only a .sha512": ([("App.AppImage.sha512", f"{_SHA512}  App.AppImage\n")], "", ""),
}


def _release_of(server, others):
    a, files = _release_with(server, [(n, None if str(t).startswith("http") else t) for n, t in others])
    return a, [Asset(f.name, t + f.name) if str(t := dict(others).get(f.name)).startswith("http") else f for f in files]


@pytest.mark.parametrize("release", list(_NO_CHECKSUM))
def test_a_checksum_file_that_gives_no_checksum_is_said_with_the_reason(server, release):
    """R4.4 (CR1.3-29): a checksum file that is there and can't be used is not "none exists". The
    install went on as Unverified with no word of it, as if the release published nothing."""
    others, used, why = _NO_CHECKSUM[release]
    a, files = _release_of(server, others)
    assert install.expected_sha256(a, files) == (_SHA if used else "", used, why)


@linux_only
@pytest.mark.parametrize("release", list(_NO_CHECKSUM))
def test_an_install_that_couldnt_use_its_releases_checksum_file_keeps_why_in_its_record(env, server, tmp_path, caplog, release):
    others, used, why = _NO_CHECKSUM[release]
    a, files = _release_of(server, others)
    rec = install.install(env, APP, a, "appimage", files, portable=install.Portable(folder=str(tmp_path / "apps"), app_menu=False))
    assert rec == json.loads(env.one("SELECT record FROM installs")["record"])
    assert (rec["verified"], rec["checksum_source"], rec.get("checksum_reason")) == ("checksum" if used else "unverified", used, why or None)
    assert ("checked against no checksum: " + why in caplog.text) == bool(why)


def test_the_checksum_files_of_a_release_are_the_files_own_then_its_lists_and_never_another_digests():
    A = lambda *names: [Asset(n, "https://example.org/" + n) for n in names]      # noqa: E731
    rel = A("App.AppImage", "SHA256SUMS", "App.AppImage.sha512", "App.AppImage.SHA256", "checksums.txt", "App.AppImage.sha256sum",
            "App.AppImage.md5", "Other.AppImage.sha256", "linux-sha256sums.txt", "App.AppImage.asc", "SHA512SUMS", "notes.txt")
    assert [x.name for x in assets.checksums_for(rel[0], rel)] == ["App.AppImage.SHA256", "App.AppImage.sha256sum", "SHA256SUMS",
                                                                   "checksums.txt", "linux-sha256sums.txt"]
    assert assets.checksum_for(rel[0], rel).name == "App.AppImage.SHA256"
    for only in ("App.AppImage.sha512", "SHA512SUMS", "Other.AppImage.sha256", "App.AppImage.asc"):
        rel = A("App.AppImage", only)
        assert assets.checksums_for(rel[0], rel) == [] and assets.checksum_for(rel[0], rel) is None


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
    desktop, menu = tmp_path / "xdg" / "applications" / "appkata-demo-tool.desktop", tmp_path / "data" / "menu" / "demo-tool"
    assert f'Exec=/bin/sh "{menu}" %U' in desktop.read_text() and _menu_starts(menu) == str(stable)    # launchers use the stable name
    install.uninstall(env, APP["url"])
    assert not os.path.lexists(cmd) and not (tmp_path / "bin-apps" / "demo-tool").exists() and not desktop.exists()
    assert not os.path.lexists(menu)
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
def test_the_record_keeps_the_sha256_of_each_versions_own_download(env, server, tmp_path):
    """R10.3.4, R8.4.5.1 (CR1, #467): the install hashed the download, logged the digest and kept it
    nowhere, so "the installed file's SHA-256" was whatever the forge said later of a file of that
    name. It is in the record, under its version: a kept version made current again has its own,
    and a version that is no longer kept has none."""
    root, base = server
    p = install.Portable(folder=str(tmp_path / "apps"), app_menu=False, keep=1)
    digest = {}

    def stored():
        return json.loads(env.one("SELECT record FROM installs")["record"])

    for v, has in (("1.0", ["1.0"]), ("1.1", ["1.0", "1.1"]), ("1.2", ["1.1", "1.2"])):
        data = f"the program, {v}".encode()
        (root / f"Tool-{v}-x86_64.AppImage").write_bytes(data)
        a = Asset(f"Tool-{v}-x86_64.AppImage", f"{base}/Tool-{v}-x86_64.AppImage")       # the forge gives no digest
        rec = install.install(env, {**APP, "installVersion": v}, a, "appimage", [a], portable=p)
        digest[v] = hashlib.sha256(data).hexdigest()
        assert rec["verified"] == "unverified" and rec == stored() and rec.get("sha256") == {x: digest[x] for x in has}
        assert install.installed_sha256(stored(), v) == digest[v]
    install.switch_to(env, {**APP}, "1.1", p)                                             # no download: 1.1's own file again
    assert stored()["current"]["version"] == "1.1" and install.installed_sha256(stored(), "1.1") == digest["1.1"]
    assert install.installed_sha256(stored(), "1.0") == ""


def test_a_record_has_no_sha256_for_a_copy_appkata_didnt_download():
    assert install.installed_sha256({"sha256": {"1.0": "aa", "1.1": "bb"}}, "1.1") == "bb"
    assert install.installed_sha256({"sha256": {"1.0": "aa"}}, "1.1") == ""
    assert install.installed_sha256({"current": {"version": "1.0", "path": "p", "exec": "e", "external": True}, "verified": "adopted"}, "1.0") == ""
    assert install.installed_sha256({"channel": "flatpak", "commit": "c0ffee"}, "1.0") == ""


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
    link = str(tmp_path / "data" / "menu" / rec["id"])                    # what the entry starts (#685)
    assert _menu_starts(link) == rec["exec"]
    want = f'/bin/sh "{link}" %U'
    entry = _entry(path)
    assert list(entry) == ["Desktop Entry"] and list(entry["Desktop Entry"]) == _ENTRY_KEYS, entry
    assert entry["Desktop Entry"]["Exec"] == want
    # the text is still there to read, as text: one line of it
    assert entry["Desktop Entry"]["Name"] == "Demo MimeType=x-scheme-handler/https;text/html; Terminal=true"
    assert entry["Desktop Entry"]["Comment"] == 'A tool Exec=sh -c "touch /tmp/pwned" [X] NoDisplay=true'
    if (glib := _glib_reads(path)) is not None:
        assert glib == [["Desktop Entry"], _ENTRY_KEYS, ["/bin/sh", link, "%U"]], glib


@linux_only
def test_the_menu_entry_starts_the_app_through_its_script_whatever_the_install_folder_holds(env, server, tmp_path):
    # CR1.3-7's other half: Exec= held the path in quotes and escaped nothing in it, so an install
    # folder with a %, a $, a backtick or a backslash in its name made an entry that started something
    # else or nothing. Escaped, a % (written %%) made GLib take the app for one that isn't installed:
    # it looks for the program before it reads %% as % (seen with GLib 2.80), so the app had no entry
    # in the menus of Cinnamon, GNOME, MATE or Xfce, and a folder with a quote or a line break was
    # refused (#685). The owner's decision: the entry starts the app through a link AppKata keeps in
    # its own folder, at a path with no %, so its Exec= never holds the install folder's path, and no
    # folder is refused. That "link" is a small script (#689's review, P2-1: the test below). Each
    # such folder installs, with an entry the specification and GLib (where it is) read as that
    # script, which runs what the app runs, and goes with the app.
    root, base = server
    (root / "t.AppImage").write_bytes(b"\x7fELF")
    a = Asset("t.AppImage", base + "/t.AppImage")
    for i, folder in enumerate((tmp_path / "My Apps" / "50% off %U" / "a $ and `id`" / "back\\slash\\\\two",
                                tmp_path / "100%", tmp_path / 'quo"te', tmp_path / "line\nbreak", tmp_path / "tab\there",
                                tmp_path / "nul\x7f")):
        app = {**APP, "url": f"{APP['url']}-{i}", "name": f"Demo {i}"}
        rec = install.install(env, app, a, "appimage", [a], portable=install.Portable(folder=str(folder)))
        assert rec["exec"].startswith(str(folder))
        path = next(f for f in rec["files"] if f.endswith(".desktop"))
        link = str(tmp_path / "data" / "menu" / f"demo-{i}")
        entry = _entry(path)["Desktop Entry"]
        assert _exec_words(entry["Exec"]) == ["/bin/sh", link, "%U"] and "%%" not in entry["Exec"], entry["Exec"]
        assert _menu_starts(link) == rec["exec"] and link in rec["files"]
        if (glib := _glib_reads(path)) is not None:
            assert glib[2] == ["/bin/sh", link, "%U"], glib                # GLib loads it: the app is in the menu
        assert install.uninstall(env, app["url"]) == [] and not os.path.lexists(link) and not os.path.exists(path)
    # the escaping, for a path that has these characters: a sandbox launcher's own word stays a word
    # of its own, outside the quotes, and a path no entry can start is refused
    assert _exec_words(install.desktop_exec("/a b/run", "--appkata-menu")) == ["/a b/run", "--appkata-menu", "%U"]
    assert _exec_words(install.desktop_exec("/50% off/a $ and `id`/back\\slash")) == ["/50% off/a $ and `id`/back\\slash", "%U"]
    for bad in ('quo"te', "line\nbreak", "tab\there", "nul\x7f"):
        with pytest.raises(ValueError, match="quote or a line break"):
            install.desktop_exec(f"/x/{bad}")
    # a backslash in the name is a backslash, not the start of an escape (`\n` would be a line break)
    rec = install.install(env, {**APP, "name": "Demo\\nTool"}, a, "appimage", [a], portable=install.Portable(folder=str(tmp_path / "f")))
    assert "Name=Demo\\\\nTool\n" in open(next(f for f in rec["files"] if f.endswith(".desktop"))).read()


@linux_only
@pytest.mark.parametrize("stable_name", [True, False], ids=["stable name", "no stable name"])
def test_a_program_started_from_its_menu_entry_is_started_by_its_own_path(env, server, tmp_path, stable_name):
    # #689's review, P2-1: the file the entry starts (#685) was a symbolic link to what the app runs,
    # so an app that runs unsandboxed was started with that link as its $0, and a program that finds
    # its files beside "$0" (a start script's `. "$(dirname "$0")/lib.sh"`) looked for them in
    # AppKata's menu folder and didn't start from the menu, while Open started it. The file is a
    # small script of AppKata's that runs the app by its own path, with the words the entry passes,
    # whatever the install folder's path holds; it is the app's, and goes with it.
    a = _start_script_archive(*server)
    for i, folder in enumerate((tmp_path / "apps", tmp_path / "it's \"50% off\" a $ and `id` \\n", tmp_path / "line\nbreak")):
        app = {**APP, "url": f"{APP['url']}-{i}", "name": f"tool {i}"}
        rec = install.install(env, app, a, "tarball", [a], portable=install.Portable(folder=str(folder), stable_name=stable_name))
        assert "launcher" not in rec and rec["exec"].startswith(str(folder))                 # it runs unsandboxed
        entry = next(f for f in rec["files"] if f.endswith(".desktop"))
        sh, first, *words = _exec_words(_entry(entry)["Desktop Entry"]["Exec"])
        assert first == str(tmp_path / "data" / "menu" / f"tool-{i}") and words == ["%U"]  # still AppKata's own folder (#685)
        started = subprocess.run([sh, first, "a file.txt", "$HOME", "it's"], capture_output=True, text=True)   # as GLib starts it
        assert (started.returncode, started.stdout, started.stderr) == (0, "found my files\n[a file.txt][$HOME][it's]", ""), started
        assert not os.path.islink(first) and _menu_starts(first) == rec["exec"]
        assert first in rec["files"] and first not in rec["links"]
        assert install.uninstall(env, app["url"]) == [] and not os.path.lexists(first) and not os.path.exists(entry)


def _start_script_archive(root, base):
    """A tarball whose program is a start script that sources lib.sh beside "$0" and prints data.txt
    from there, then its arguments, each in brackets: it starts only by its own path."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for path, mode, body in (("tool-1.2/tool", 0o755, b'#!/bin/sh\n. "$(dirname "$0")/lib.sh"\nfound "$@"\n'),
                                 ("tool-1.2/lib.sh", 0o644, b'found() { cat "$(dirname "$0")/data.txt"; printf "[%s]" "$@"; }\n'),
                                 ("tool-1.2/data.txt", 0o644, b"found my files\n")):
            info = tarfile.TarInfo(path)
            info.size, info.mode = len(body), mode
            tf.addfile(info, io.BytesIO(body))
    (root / "tool-1.2-linux-x86_64.tar.gz").write_bytes(buf.getvalue())
    return Asset("tool-1.2-linux-x86_64.tar.gz", base + "/tool-1.2-linux-x86_64.tar.gz")


def _glib_starts(path):
    """What an app prints when GLib starts its menu entry as a desktop's menu does, with no file
    (Gio.DesktopAppInfo.launch): its output, "not shown" where GLib loads no app from the file or
    its menu doesn't show it, or None where no system python3 has python3-gi (tier 1's container
    has it). The app inherits the output, so it is read to its end, past GLib's own exit."""
    py = shutil.which("python3", path="/usr/bin:/bin")
    if not py or subprocess.run([py, "-c", "import gi"], capture_output=True).returncode:
        return None
    code = ("import sys, gi\ngi.require_version('Gio', '2.0')\nfrom gi.repository import Gio\n"
            "try:\n    i = Gio.DesktopAppInfo.new_from_filename(sys.argv[1])\nexcept TypeError:\n    i = None\n"
            "if not i or not i.should_show():\n    print('not shown', end='')\nelse:\n    i.launch([], None)\n")
    return subprocess.run([py, "-c", code, str(path)], capture_output=True, text=True, timeout=60).stdout


@linux_only
@pytest.mark.parametrize("data", ["data", "100% data", "d%x %U"], ids=["plain", "a percent", "a field code"])
def test_an_app_starts_from_its_menu_entry_whatever_appkatas_own_folder_holds_or_how_it_is_mounted(env, server, tmp_path,
                                                                                                    monkeypatch, data):
    # #689's review, P3-2: the entry's program, the first word of its Exec=, was the app's script in
    # AppKata's own folder (#685), which GLib runs as a program. A % in that folder's path (a home
    # such as /home/u/100%, or $XDG_DATA_HOME's, or APPKATA_DATA's), written %% as the specification
    # asks, made GLib take the app for one that isn't installed, as a % in the install folder did
    # before #685: the app was in no menu. And a program is run only from a mount that allows it:
    # with the home mounted noexec, every entry failed with "Permission denied", while Open and the
    # command link started the app from its install folder on another mount. The entry's program
    # is /bin/sh, which GLib finds wherever AppKata's folder is, and the script its first argument,
    # which sh only reads. Here the script can't be run (mode 0644, as on a noexec mount), and the
    # entry is started by GLib itself where it is here, and by its words everywhere.
    folder = tmp_path / data / "appkata"
    monkeypatch.setenv("APPKATA_DATA", str(folder))
    a = _start_script_archive(*server)
    rec = install.install(env, APP, a, "tarball", [a], portable=install.Portable(folder=str(tmp_path / "apps")))
    assert "launcher" not in rec and rec["exec"].startswith(str(tmp_path / "apps"))           # it runs unsandboxed
    entry = next(f for f in rec["files"] if f.endswith(".desktop"))
    script = str(folder / "menu" / rec["id"])
    os.chmod(script, 0o644)                                 # as on a mount that runs no program: read, never run
    if (glib := _glib_starts(entry)) is not None:
        assert glib == "found my files\n[]", glib           # GLib shows the entry and starts the app from it
    words = _exec_words(_entry(entry)["Desktop Entry"]["Exec"])
    started = subprocess.run([w for w in words if w != "%U"] + ["a file.txt", "100%"], capture_output=True, text=True)
    assert (started.returncode, started.stdout, started.stderr) == (0, "found my files\n[a file.txt][100%]", ""), started
    assert words == ["/bin/sh", script, "%U"] and script in rec["files"]
    assert install.uninstall(env, APP["url"]) == [] and not os.path.lexists(script) and not os.path.exists(entry)


@linux_only
@pytest.mark.parametrize("sandboxed", [False, True], ids=["unsandboxed", "sandboxed"])
def test_an_install_folder_whose_name_isnt_utf8_installs_and_starts_from_the_menu(env, server, tmp_path, monkeypatch, sandboxed):
    # #689's review, P3-B3: the menu script was written as UTF-8 text, so an install folder whose
    # name has a byte that isn't UTF-8 (a Latin-1 name on a UTF-8 system; Python gives it as a
    # surrogate escape) stopped the install with Python's own "'utf-8' codec can't encode" error,
    # and the app couldn't be installed there at all, which R4.3.1.1 says no folder's name causes.
    # The script holds the path as its bytes. AppKata's own folder is the entry's, and an entry is
    # UTF-8 text: a byte that isn't is refused before anything is placed, with the reason.
    # P4-1: a sandboxed app's launcher, which holds the folder's path too, was still written as
    # text: its install stopped with the same error and left run.<pid>.tmp beside the launcher, and
    # the launcher was compared as text at AppKata's start. It holds the path's bytes, and is the
    # launcher AppKata would write today, so the start leaves it be.
    from appkata_core import sandbox
    app = {**APP, "sandbox": sandbox.resolve_template("standard") if sandboxed else None}
    a = _start_script_archive(*server)
    folder = tmp_path / os.fsdecode(b"apps-\xe9\xff")
    port = install.Portable(folder=str(folder))
    rec = install.install(env, app, a, "tarball", [a], portable=port)
    entry, script = next(f for f in rec["files"] if f.endswith(".desktop")), str(tmp_path / "data" / "menu" / rec["id"])
    assert rec["exec"].startswith(str(folder)) and ("launcher" in rec) is sandboxed
    assert os.fsencode(shlex.quote(rec["exec"])) in open(script, "rb").read()
    words = _exec_words(_entry(entry)["Desktop Entry"]["Exec"])
    if sandboxed:
        launcher = str(folder / rec["id"] / "run")
        assert rec["exec"] == rec["launcher"] == launcher and words == ["/bin/sh", script, "--appkata-menu", "%U"]
        assert b"\nappdir=" + os.fsencode(shlex.quote(rec["current"]["path"])) + b"\n" in open(launcher, "rb").read()   # the folder's own bytes
        assert subprocess.run(["sh", "-n", launcher]).returncode == 0 and os.access(launcher, os.X_OK)
        assert install.launcher_is_current(rec, app, port)                                  # the start leaves it be
        assert sorted(os.listdir(folder / rec["id"])) == ["1.2.0", "current", "run"]       # nothing beside it
    else:
        if (glib := _glib_starts(entry)) is not None:
            assert glib == "found my files\n[]", glib                           # GLib starts it from the menu
        started = subprocess.run([w for w in words if w != "%U"] + ["x"], capture_output=True, text=True)
        assert (started.returncode, started.stdout, started.stderr) == (0, "found my files\n[x]", ""), started
    assert install.uninstall(env, APP["url"], remove_sandbox=True) == []
    assert not os.path.lexists(script) and not os.path.exists(folder / rec["id"])
    monkeypatch.setenv("APPKATA_DATA", str(tmp_path / os.fsdecode(b"data-\xff")))
    with pytest.raises(install.InstallError, match="has a byte that isn't UTF-8 in it, which a menu entry can't hold"):
        install.install(env, app, a, "tarball", [a], portable=install.Portable(folder=str(tmp_path / "apps")))
    assert not (tmp_path / "apps" / rec["id"]).exists() and not os.path.exists(entry)


@linux_only
@pytest.mark.parametrize("fails", ["the script", "the entry"])
def test_a_menu_file_whose_write_fails_is_left_as_it_was(env, server, tmp_path, monkeypatch, fails):
    # #689's review, P3-B4: the app's menu script was removed and then written in place, and its
    # entry truncated and then written in place, so a write that failed (a full disk, a quota) left
    # a missing or empty file, which the menu starts with "Exec format error", and an app started
    # between the two found nothing. An activation runs at every update, sandbox change and start
    # that rewrites a launcher, and taking a failed update back runs it again. Each is written
    # beside its place and renamed over it, as a launcher is: whole, or not at all.
    a = _start_script_archive(*server)
    port = install.Portable(folder=str(tmp_path / "apps"))
    rec = install.install(env, APP, a, "tarball", [a], portable=port)
    entry, script = next(f for f in rec["files"] if f.endswith(".desktop")), str(tmp_path / "data" / "menu" / rec["id"])
    was = {p: open(p, "rb").read() for p in (entry, script)}
    full = {"the script": script, "the entry": entry}[fails]
    real_open, real_fdopen = open, os.fdopen

    class Full:
        """A file on a full disk, for writing: it opens, and nothing can be written to it."""
        def __init__(self, f):
            self.f = f

        def write(self, data):
            raise OSError(28, "No space left on device")

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self.f.close()

    def on_full_disk(f, name, mode):
        return Full(f) if any(c in mode for c in "wax+") and re.sub(r"\.\d+\.tmp$", "", str(name)) == full else f
    monkeypatch.setattr(install, "open", lambda file, mode="r", *a, **k: on_full_disk(real_open(file, mode, *a, **k), file, mode),
                        raising=False)
    monkeypatch.setattr(install.os, "fdopen", lambda fd, mode="r", *a, **k: on_full_disk(
        real_fdopen(fd, mode, *a, **k), os.readlink(f"/proc/self/fd/{fd}"), mode))
    with pytest.raises(OSError, match="No space left on device"):
        install._activate(dict(rec), APP, port, rec["target"])              # an update's, a sandbox change's
    monkeypatch.undo()
    assert {p: open(p, "rb").read() for p in (entry, script)} == was         # both as they were, whole
    assert sorted(os.listdir(os.path.dirname(script))) == [rec["id"]]        # and nothing half-written beside them
    assert sorted(os.listdir(os.path.dirname(entry))) == [os.path.basename(entry)]
    started = subprocess.run(["/bin/sh", script, "x"], capture_output=True, text=True)
    assert (started.returncode, started.stdout) == (0, "found my files\n[x]"), started


def _menu_starts(path):
    """What the file an app's menu entry starts runs: AppKata's script, `exec <the path> "$@"`."""
    text = open(path).read()
    assert text.startswith("#!/bin/sh\n") and os.access(path, os.X_OK), text
    word, target, *rest = shlex.split(text.split("\n", 1)[1])
    assert word == "exec" and rest == ["$@"], text
    return target


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
        why = install.command_link_refusal(name, "/nonexistent/bin/" + name)
        assert why == f"{name} is a name kept for the system's own command", name


# The programs AppKata's code runs by name only on another platform, which no Linux install reaches
_OTHER_PLATFORMS = {"open": "macOS", "icacls": "Windows", "notepad.exe": "Windows", "powershell.exe": "Windows"}


def _run_by_name(src=None):
    """Every program AppKata's own code (`src`, src/ by default) runs by name: {name: ["file:line",
    ...]}. A name is the first word of a list given first to any call (subprocess's, applog.run, a
    helper such as autoupdate._out that runs what it is given), or what `which("name")` looks for.
    Given to what runs a program (subprocess's calls, or a function of AppKata's that gives its
    first parameter to one), the list may also be built first and given by name (`cmd =
    [...]`, then `Popen(cmd)`, in the same function or at the module's top), chosen by a
    conditional (both its lists), added to (`["git"] + args`), started with a starred list
    (`[*BASE, x]`), grown with `+=` from an empty one, held on an attribute (`self.cmd`), given by
    keyword (`args=[...]`), or be a string (`run("tool -x")`): #689's review, P2-4, the form gio came
    in by, and P3-3. A program os runs (`os.execvp("tool", ...)`, `os.spawnlp(mode, "tool", ...)`,
    `os.system("tool ...")`) or asyncio does (`create_subprocess_exec("tool", ...)`) is one too. A
    wrapper that puts its own program before its caller's words (flatpak.run: ["flatpak", *args])
    gives that program, and its callers' first words are that program's, not programs."""
    import ast
    src = src or os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src")
    trees = {}
    for d, _, names in os.walk(src):
        for n in sorted(names):
            if n.endswith(".py"):
                with open(os.path.join(d, n), encoding="utf-8") as f:
                    trees[os.path.join(d, n)] = ast.parse(f.read())

    def first(node):
        if isinstance(node, (ast.List, ast.Tuple)) and node.elts and isinstance(node.elts[0], ast.Constant) \
                and isinstance(node.elts[0].value, str):
            return node.elts[0].value
        return None

    def held(node):
        """The name a value is held by: `cmd`, or `self.cmd` for an attribute."""
        if isinstance(node, ast.Name):
            return node.id
        return f"{node.value.id}.{node.attr}" if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) else None

    def empty(node):
        return isinstance(node, (ast.List, ast.Tuple)) and not node.elts

    def first_word(text):
        """A command line's first word, as a shell splits it."""
        try:
            return shlex.split(text)[:1]
        except ValueError:
            return []

    def firsts(node, assigned, seen=()):
        """The first words of every list `node` can be: a list (or the first words of the starred
        list it starts with), either list of a conditional, the left of a `+` (its right where the
        left is empty), a string's first word, or the lists a name or an attribute is assigned,
        with what `+=` adds to one assigned an empty list."""
        if isinstance(node, ast.IfExp):
            return firsts(node.body, assigned, seen) + firsts(node.orelse, assigned, seen)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            return firsts(node.right if empty(node.left) else node.left, assigned, seen)
        if isinstance(node, (ast.List, ast.Tuple)) and node.elts and isinstance(node.elts[0], ast.Starred):
            return firsts(node.elts[0].value, assigned, seen)
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return first_word(node.value)
        if (key := held(node)) and key not in seen:
            values = assigned.get(key, [])
            grown = assigned.get(key + " +=", []) if any(empty(v) for v in values) else []
            return [w for v in values + grown for w in firsts(v, assigned, seen + (key,))]
        return [w] if (w := first(node)) else []

    def assignments(scope, nodes=None):
        """{name: [the values assigned to it]} in a function (or a module's own statements), with
        what `+=` adds to a name under "<name> +="."""
        out = {}
        for n in nodes if nodes is not None else (ast.walk(scope) if not isinstance(scope, ast.Module) else scope.body):
            targets = n.targets if isinstance(n, ast.Assign) else [n.target] if isinstance(n, ast.AnnAssign) and n.value else []
            for t in targets:
                if key := held(t):
                    out.setdefault(key, []).append(n.value)
            if isinstance(n, ast.AugAssign) and isinstance(n.op, ast.Add) and (key := held(n.target)):
                out.setdefault(key + " +=", []).append(n.value)
        return out

    def calls(node, assigned):
        """(call, what its function assigns, and its module) for every call under `node`, in its
        innermost function."""
        for child in ast.iter_child_nodes(node):
            inner = {**assigned, **assignments(child)} if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) else assigned
            if isinstance(child, ast.Call):
                yield child, inner
            yield from calls(child, inner)

    def callee(call, module):
        f = call.func
        if isinstance(f, ast.Name):
            return module, f.id
        return (f.value.id, f.attr) if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) else None

    def given(call, keyword):
        """What a call gives a runner: its first argument, else the keyword its runner takes it by."""
        return call.args[0] if call.args else next((k.value for k in call.keywords if k.arg == keyword), None)

    module = lambda p: os.path.splitext(os.path.basename(p))[0]       # noqa: E731
    # what runs a list of words, by the keyword it takes it by; and os's and asyncio's, by where the
    # program is among the arguments
    runners = {("subprocess", f): "args" for f in ("run", "Popen", "call", "check_call", "check_output")}
    by_program = {**{("os", f): 0 for f in ("execl", "execle", "execlp", "execlpe", "execv", "execve", "execvp", "execvpe",
                                            "posix_spawn", "posix_spawnp", "system", "popen")},
                  **{("os", f): 1 for f in ("spawnl", "spawnle", "spawnlp", "spawnlpe", "spawnv", "spawnve", "spawnvp", "spawnvpe")},
                  ("asyncio", "create_subprocess_exec"): 0, ("asyncio", "create_subprocess_shell"): 0}
    while True:                                 # and AppKata's own functions that run what they are given
        more = {}
        for p, tree in trees.items():
            for fn in ast.walk(tree):
                param = [a.arg for a in fn.args.args if a.arg not in ("self", "cls")][:1] \
                    if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) else []
                if param and (module(p), fn.name) not in runners and any(
                        isinstance(c, ast.Call) and callee(c, module(p)) in runners
                        and isinstance(g := given(c, runners[callee(c, module(p))]), ast.Name) and g.id == param[0]
                        for c in ast.walk(fn)):
                    more[(module(p), fn.name)] = param[0]
        if not more:
            break
        runners |= more
    wrappers = set()
    for p, tree in trees.items():
        for fn in ast.walk(tree):
            if isinstance(fn, ast.FunctionDef):
                params = {a.arg for a in fn.args.args + fn.args.kwonlyargs} | ({fn.args.vararg.arg} if fn.args.vararg else set())
                for c in ast.walk(fn):
                    if isinstance(c, ast.Call) and c.args and first(c.args[0]) and any(
                            isinstance(e, ast.Starred) and isinstance(e.value, ast.Name) and e.value.id in params for e in c.args[0].elts):
                        wrappers.add((module(p), fn.name))
    found = {}
    for p, tree in trees.items():
        # a module's own names, and what its code holds on an attribute anywhere in it
        top = {**assignments(tree), **{k: v for k, v in assignments(tree, list(ast.walk(tree))).items() if "." in k}}
        for c, assigned in calls(tree, top):
            who = callee(c, module(p))
            if who in wrappers:
                continue
            if who in by_program:
                at = by_program[who]
                arg = c.args[at] if len(c.args) > at else None
                words = [w for v in ([arg] if not isinstance(arg, ast.Name) else assigned.get(arg.id, []))
                         if isinstance(v, ast.Constant) and isinstance(v.value, str) for w in first_word(v.value)]
            elif (lst := given(c, runners[who]) if who in runners else c.args[0] if c.args else None) is None:
                continue
            else:
                words = [first(lst)] if first(lst) else firsts(lst, assigned) if who in runners else []
                if not words and (who or ("", ""))[1] == "which" and isinstance(lst, ast.Constant):
                    words = [lst.value]
            for name in words:
                if isinstance(name, str) and re.fullmatch(r"[a-z0-9]([a-z0-9._+-]*[a-z0-9])?", name):     # a program's name
                    found.setdefault(name, []).append(f"{os.path.relpath(p, src)}:{c.lineno}")
    return found


# The forms a program's list takes on its way to what runs it (#689's review, P2-4), and what the
# harness must find in them: {the source, the names it runs}
_RUN_FORMS = ("""
import subprocess


def built_first(path):
    cmd = ["built-first", path]
    subprocess.Popen(cmd, start_new_session=True)


def chosen(apt):
    subprocess.run(["chosen-by-apt", "-L"] if apt else ["chosen-by-rpm", "-ql"], check=True)


def chosen_then_run(apt, args):
    cmd = ("chosen-a", "x") if apt else ["chosen-b"] + args
    return _out(cmd)


def _out(words):
    return subprocess.check_output(words, text=True)


def added(args):
    _out(["added-to"] + args)


def not_run(path):
    words = ["not-a-program", path]
    print(words)
    return ", ".join(words)
""", {"built-first", "chosen-by-apt", "chosen-by-rpm", "chosen-a", "chosen-b", "added-to"})

# More of them (#689's review, P3-3): a module's own list, a list given by keyword, a starred list
# first, a list grown with += from an empty one, a list held on self, and the os and asyncio calls
# that run a program; a program run by its path, and a word added after a program's, are not
# programs run by name
_RUN_FORMS_MORE = ("""
import asyncio
import os
import subprocess

MODULE_LEVEL = ["module-level", "-x"]
BASE = ["starred-first", "-q"]


def module_constant():
    subprocess.run(MODULE_LEVEL, check=True)


def by_keyword(path):
    subprocess.run(args=["by-keyword", path], check=True)


def starred(path):
    subprocess.run([*BASE, path], check=True)


def grown(args):
    cmd = []
    cmd += ["grown-from-empty"]
    subprocess.run(cmd + args, check=True)


def grown_after_a_program():
    cmd = ["grown-after"]
    cmd += ["not-a-program-either"]
    subprocess.run(cmd, check=True)


class Held:
    def __init__(self):
        self.cmd = ["held-on-self", "--flag"]

    def go(self):
        return subprocess.check_output(self.cmd, text=True)


def replaced(args):
    os.execvp("exec-p", ["exec-p", *args])


def replaced_by_path(args):
    os.execv("/usr/bin/exec-by-path", ["exec-by-path", *args])


def spawned(args):
    return os.spawnlp(os.P_WAIT, "spawned", "spawned", *args)


async def asynchronous(args):
    return await asyncio.create_subprocess_exec("async-exec", *args)


def through_a_shell():
    os.system("shell-word --flag")
""", {"module-level", "by-keyword", "starred-first", "grown-from-empty", "grown-after", "held-on-self", "exec-p",
      "spawned", "async-exec", "shell-word"})


def test_the_harness_finds_a_program_however_its_list_reaches_what_runs_it(tmp_path):
    # #689's review, P2-4: _run_by_name took a list only where it was given straight to a call (or a
    # which("name")), so a list built first and run after, as _launch_package's gio, or chosen by a
    # conditional, as _package_entries' dpkg-query or rpm, got past it; gio was found only through
    # the which() beside it. A list given by name, chosen or added to counts where what it is given
    # to runs a program (subprocess's, or a function of AppKata's such as _out here that gives it to
    # one), and not where it is printed or joined. P3-3: nor did it follow a module's own list into
    # its functions, a list given by keyword, a starred list first, a list grown with +=, one held
    # on self, or a program run by os's exec, spawn or system calls or asyncio's.
    (tmp_path / "forms.py").write_text(_RUN_FORMS[0])
    assert set(_run_by_name(str(tmp_path))) == _RUN_FORMS[1]
    (tmp_path / "forms.py").write_text(_RUN_FORMS_MORE[0])
    assert set(_run_by_name(str(tmp_path))) == _RUN_FORMS_MORE[1]
    import inspect

    def where(fn, text):                        # the line of `fn` holding `text`, as the harness names it
        lines, start = inspect.getsourcelines(fn)
        return f"{os.path.join('appkata_core', 'install.py')}:{start + next(i for i, line in enumerate(lines) if text in line)}"
    found = _run_by_name()
    assert where(install._package_entries, "subprocess.run(cmd") in set(found["dpkg-query"]) & set(found["rpm"])
    assert where(install._launch_package, "subprocess.Popen(cmd") in set(found["gio"]) & set(found["gtk-launch"])


def test_every_program_appkata_runs_by_name_is_a_name_no_command_link_takes():
    # #689's review, P1-2: R4.3.1.3 keeps "the commands AppKata and its sandbox launchers run by name"
    # from ever becoming a command link, whatever this computer has installed, and the list held a
    # launcher's (sandbox.HOST_COMMANDS, held to the launcher's text) and a hand-written few. Open on
    # a system package began running gio and gtk-launch by name (#319) and neither was added, nor were
    # gsettings and apt-mark, which AppKata ran by name before: on a computer without gio and
    # gtk-launch an app named gtk-launch got ~/bin/gtk-launch, first on the PATH, and Open on any
    # package ran it. Every program AppKata's code runs by name is collected from the code itself,
    # so one added later is reserved with it or this fails.
    found = _run_by_name()
    assert {"gio", "gtk-launch", "gsettings", "apt-mark", "flatpak", "git", "dpkg-query", "pkexec"} <= set(found), sorted(found)
    assert set(_OTHER_PLATFORMS) <= set(found), sorted(set(_OTHER_PLATFORMS) - set(found))      # none listed for nothing
    unreserved = {n: where for n, where in found.items() if n not in install.RESERVED_COMMANDS and n not in _OTHER_PLATFORMS}
    assert unreserved == {}, unreserved


def _appkata_start(env, tmp_path, monkeypatch, app, portable, sandbox_here=False, grants=None):
    """AppKata's start as the backend makes it -- the pass its constructor starts on a thread
    (`Backend._heal_launchers_at_startup`) -- on the test's database, for the installed `app` with
    the options `portable` and the grant set `grants` (None: it can't be sandboxed). This machine's
    sandbox is never asked: here it works when `sandbox_here`, and bwrap is missing otherwise.
    Returns a function that runs the pass and gives the app's stored record; its `backend` is the
    Backend."""
    pytest.importorskip("PySide6")                              # the backend is Qt's
    from appkata_core import sandbox
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setattr(sandbox, "have_tools", lambda: sandbox_here)
    monkeypatch.setattr(sandbox, "userns_works", lambda refresh=False: sandbox_here)
    monkeypatch.setattr(sandbox, "nested_userns_works", lambda refresh=False: True)
    monkeypatch.setattr(sandbox, "support_status", lambda: {"status": "ok" if sandbox_here else "unsupported"})
    from appkata.backend import Backend
    be = Backend(db_path=env.path, heal=False)
    be._timer.stop()
    be._app = lambda url: {**app, "installed": app.get("installVersion") or app["version"]} if url == app["url"] else None
    be._app_options = lambda url, choice=None: portable
    be._resolved_sandbox = lambda url, kind=None, is_cli=None: (
        {"source": "user", "grants": grants, "template": "test"} if grants is not None and url == app["url"] else None)

    def start():
        be._heal_launchers_at_startup()
        return json.loads(env.one("SELECT record FROM installs WHERE url=?", (app["url"],))["record"])
    start.backend = be
    return start


@linux_only
def test_an_apps_own_command_link_is_replaced_and_one_that_becomes_a_command_goes_at_the_next_update(env, server, tmp_path, debian_path, monkeypatch):
    # The other side of the name check: the link AppKata made for this app is on the PATH too, and
    # an update must not take it for someone else's command. And a name that becomes a command
    # later (the system installs a `demo-tool`) loses its link at the next update, since the link
    # would be ahead of it, and gets it back at the one after once the name is free (AppKata's
    # start does both too: the test below).
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
    a = _appimage(server, "Tool-1.2-x86_64.AppImage", b"1.2")
    rec = install.install(env, {**APP, "installVersion": "1.2"}, a, "appimage", [a], portable=p)
    assert rec["commandRefused"] == f"demo-tool is already a command on this computer ({system / 'demo-tool'})"
    assert not os.path.lexists(debian_path / "demo-tool")
    (system / "demo-tool").unlink()
    a = _appimage(server, "Tool-1.3-x86_64.AppImage", b"1.3")
    rec = install.install(env, {**APP, "installVersion": "1.3"}, a, "appimage", [a], portable=p)    # the option stood
    assert "commandRefused" not in rec and open(debian_path / "demo-tool", "rb").read() == b"1.3"


_STARTS = {"the sandbox unsupported here": (False, None), "the app's sandbox Off": (True, "off"),
           "the app sandboxed, its launcher today's": (True, "standard")}


@linux_only
@pytest.mark.parametrize("start", list(_STARTS))
def test_appkatas_start_makes_a_command_link_once_its_name_is_free_and_removes_one_whose_name_became_a_command(env, server, tmp_path, debian_path, monkeypatch, start):
    # #689's review, P1-1: R4.3.1.3 says a command link refused while its name was a command "is
    # made at a later update or start of AppKata once the name is free, and a link whose name has
    # since become a command is removed then". The start's only pass that reached the command link
    # was the heal of a sandboxed app's launcher that isn't today's text: an app that runs Off, any
    # app where the sandbox isn't supported, and a sandboxed one whose launcher is current got their
    # link back, or lost one ahead of a newly installed command, only at their next update. The test
    # that held the sentence called rewrite_launcher by hand and called it the start. This one runs
    # the backend's own start pass, for each kind of app the heal passes over.
    from appkata_core import sandbox
    sandbox_here, template = _STARTS[start]
    grants = sandbox.resolve_template(template) if template else None
    system = tmp_path / "usr-bin"
    system.mkdir()
    (system / "demo-tool").write_text("#!/bin/sh\n")
    (system / "demo-tool").chmod(0o755)
    monkeypatch.setenv("PATH", f"{os.environ['PATH']}:{system}")
    p = install.Portable(folder=str(tmp_path / "apps"), command_dir=str(debian_path))
    start_appkata = _appkata_start(env, tmp_path, monkeypatch, APP, p, sandbox_here, grants)
    a = _appimage(server, "Tool-1.0-x86_64.AppImage", b"1.0")
    rec = install.install(env, {**APP, "sandbox": grants}, a, "appimage", [a], portable=p)
    assert rec["commandRefused"] == f"demo-tool is already a command on this computer ({system / 'demo-tool'})"
    sandboxed = template not in (None, "off")
    assert bool(rec.get("launcher")) is sandboxed
    if sandboxed:                           # its launcher is the one AppKata writes today: nothing for the heal to do
        assert start_appkata.backend._heal_launchers() == []
    assert start_appkata() == rec and not os.path.lexists(debian_path / "demo-tool")       # still a command: nothing changes
    (system / "demo-tool").unlink()                                     # the system's demo-tool is uninstalled
    rec = start_appkata()
    assert "commandRefused" not in rec and str(debian_path / "demo-tool") in rec["links"]
    assert os.readlink(debian_path / "demo-tool") == rec["exec"]        # the launcher, when it is sandboxed
    made = os.lstat(debian_path / "demo-tool")
    assert start_appkata() == rec and os.lstat(debian_path / "demo-tool").st_ino == made.st_ino      # in place: left alone
    (system / "demo-tool").write_text("#!/bin/sh\n")                    # and installed again: the link is ahead of it
    (system / "demo-tool").chmod(0o755)
    rec = start_appkata()
    assert rec["commandRefused"] == f"demo-tool is already a command on this computer ({system / 'demo-tool'})"
    assert not os.path.lexists(debian_path / "demo-tool") and str(debian_path / "demo-tool") not in rec["links"]
    assert shutil.which("demo-tool") == str(system / "demo-tool")
    if sandboxed:
        assert start_appkata.backend._heal_launchers() == []
    assert rec == json.loads(env.one("SELECT record FROM installs")["record"])
    install.uninstall(env, APP["url"])
    assert not (tmp_path / "apps" / "demo-tool").exists()


@linux_only
@pytest.mark.parametrize("path", ["off the PATH", "on the PATH", "on the PATH, and a command of that name further on"])
@pytest.mark.parametrize("theirs", ["a link to their own program", "their own program"])
@pytest.mark.parametrize("name", ["Demo Tool", "git"])
def test_a_file_of_the_users_at_the_command_links_place_stops_the_install_whatever_the_path(env, server, tmp_path, monkeypatch, name, theirs, path):
    # CR1.5-31, R4.3.1.3: "AppKata never replaces a file there that isn't a link it made", and
    # `_link` took any symbolic link for one it made: the user's own ~/bin/demo-tool -> /opt/... was
    # replaced. Only a link that leads into the install folder is AppKata's.
    # #689's review, P1-B2: with the folder on the PATH, the user's own program there answered as a
    # command already on this computer, so the install went on without a link and said so, where
    # off the PATH the same file stopped it (and a reserved name never looked at the place). The
    # owner decided (option B) that it stops the install with the error whatever the PATH, as
    # before the name check; "already a command" is for a name something elsewhere answers to, and
    # once the place is free again that, or a reserved name, is the reason there is no link.
    slug = install.slug(name)
    cmd, program = tmp_path / "cmd", tmp_path / "opt" / "their-tool"
    cmd.mkdir()
    program.parent.mkdir()
    program.write_text("#!/bin/sh\necho theirs\n")
    program.chmod(0o755)
    if path != "off the PATH":
        monkeypatch.setenv("PATH", f"{cmd}:{os.environ['PATH']}")
    if path.endswith("further on"):
        monkeypatch.setenv("PATH", f"{os.environ['PATH']}:{program.parent}")
        program = program.rename(program.parent / slug)
    if theirs == "a link to their own program":
        (cmd / slug).symlink_to(program)
    else:
        shutil.copy(program, cmd / slug)
    mine = os.readlink(cmd / slug) if theirs.startswith("a link") else (cmd / slug).read_text()
    a = _appimage(server)
    p = install.Portable(folder=str(tmp_path / "apps"), command_dir=str(cmd))
    before = _left(tmp_path, env)
    with pytest.raises(install.InstallError, match=re.escape(f"{cmd / slug} exists and isn't a link AppKata made; not replacing it")):
        install.install(env, {**APP, "name": name}, a, "appimage", [a], portable=p)
    assert _changed(before, _left(tmp_path, env)) == {}                  # nothing of the install, nothing of theirs touched
    assert (os.readlink(cmd / slug) if theirs.startswith("a link") else (cmd / slug).read_text()) == mine
    (cmd / slug).unlink()                                               # the place is free
    rec = install.install(env, {**APP, "name": name}, a, "appimage", [a], portable=p)
    if slug in install.RESERVED_COMMANDS:
        assert rec["commandRefused"] == f"{slug} is a name kept for the system's own command"
    elif path.endswith("further on"):                                   # the name is a command elsewhere
        assert rec["commandRefused"] == f"{slug} is already a command on this computer ({program})"
    else:
        assert "commandRefused" not in rec and os.readlink(cmd / slug) == rec["exec"]
    assert os.path.lexists(cmd / slug) is ("commandRefused" not in rec)


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


_REFUSALS = {"the command link": "isn't a link AppKata made", "an archive with no program": "couldn't find the program",
             "a folder that can't be put in place": "Not a directory"}


@linux_only
@pytest.mark.parametrize("update", [False, True], ids=["a first install", "an update"])
@pytest.mark.parametrize("refused", list(_REFUSALS))
def test_a_refused_install_leaves_everything_as_it_was(env, server, tmp_path, monkeypatch, refused, update):
    # CR1.3-15: the record is stored last, and nothing took back what a refused install had made by
    # then. A first install refused at its command link (a file of the user's is there) left the
    # app's folder, its stable link and its menu entry with no record: in the desktop's menu, not in
    # AppKata, and nothing to uninstall it with. Refused as an update, `current` and the menu entry
    # were the new version's and the record the old one's, and an archive with no program left its
    # <version>.new folder. Each refusal here is a real one: a file where the command link goes, an
    # archive with no program. The third is the one made to happen: the unpacked version can't be
    # renamed into place, as when what is at its name isn't a folder. (A program whose path in the
    # archive held a quote was refused too, at its menu entry, until #685: the entry starts the app's
    # link in AppKata's own folder now, whatever the path holds.)
    apps, cmd, mine = tmp_path / "apps", tmp_path / "cmd", tmp_path / "their-bin"
    mine.mkdir()
    (mine / "tool").write_text("mine")
    app = {**APP, "name": "tool"}
    good = install.Portable(folder=str(apps), command_dir=str(cmd))
    if update:
        a1 = _tarball(server, "tool-1.0.tar.gz", {"tool-1.0/tool": 0o755})
        install.install(env, {**app, "installVersion": "1.0"}, a1, "tarball", [a1], portable=good)
        assert os.readlink(apps / "tool" / "current") == "1.0" and os.path.islink(cmd / "tool")
    files = {"an archive with no program": {"tool-2.0/README": 0o644}}
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
@pytest.mark.parametrize("then", ["an update", "a kept version", "a launcher rewrite", "the next start", "uninstall"])
@pytest.mark.parametrize("theirs", _THEIRS)
def test_what_the_user_put_where_a_command_link_was_is_never_removed_or_replaced(env, server, tmp_path, monkeypatch, theirs, then, on_path):
    # CR1.3-11, R4.3.1.3: "AppKata never replaces a file there that isn't a link it made". A first
    # install has checked that since CR1.5-31. But an installed app's record names its command
    # link's path, and whatever symbolic link was at a recorded path was taken for AppKata's: an
    # update, a switch to a kept version and the startup pass removed it and put AppKata's there,
    # and uninstalling removed it. A link is AppKata's when it leads into the install folder,
    # wherever its path is written down. So: the user puts something of their own where the
    # command link was (a link to their program, a link to nothing, a file), and nothing AppKata
    # then does to the app touches it. The update stops with the error, on the PATH or off it
    # (R4.3.1.3; #689's review, P1-B2: on it, a link to a program was taken for a command already
    # on this computer, and the update went on without one), and changes nothing, and a
    # launcher's rewrite (a sandbox change, or the start's for a launcher that isn't today's) is
    # made without the command, as AppKata's start is (#689's review, P1-1: "the next start" here
    # was rewrite_launcher by hand; it is the backend's start pass now).
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
    start = _appkata_start(env, tmp_path, monkeypatch, APP, p) if then == "the next start" else None
    before = _left(tmp_path, env)
    a = _appimage(server, "Tool-2.0-x86_64.AppImage", b"2.0")
    act = {"an update": lambda: install.install(env, {**APP, "installVersion": "2.0"}, a, "appimage", [a], portable=p),
           "a kept version": lambda: install.switch_to(env, dict(APP), "1.0", p),
           "a launcher rewrite": lambda: install.rewrite_launcher(env, dict(APP), p),
           "the next start": start,
           "uninstall": lambda: install.uninstall(env, APP["url"])}[then]
    if then == "uninstall":
        act()
        assert env.one("SELECT * FROM installs") is None and not os.path.lexists(tmp_path / "apps" / "demo-tool")
    elif then in ("a launcher rewrite", "the next start"):      # no install: made in full, without the command (CR1.3-46)
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
@pytest.mark.parametrize("road", ["an update", "a launcher rewrite", "a kept version"])
@pytest.mark.parametrize("off", list(_OPTIONS))
def test_what_an_option_made_goes_when_it_is_turned_off_and_nothing_outlasts_uninstall(env, server, tmp_path, off, road):
    # CR1.3-14: each time an app is activated its record forgot its menu entry, and the entry was
    # written again only while the app-menu option was on; nothing deleted the file. Turned off in
    # Install options, the entry stayed in the desktop's menu, in no record, and outlasted the
    # uninstall, starting a program that was gone. The class is what any of an app's three options
    # made (R4.3.1.6) once the option is off, by each road an app is activated again (a launcher's
    # rewrite: a sandbox change, which takes the app's options as they are now), and R4.7's
    # "uninstalling reverses what AppKata recorded": after it, nothing of the app is left anywhere.
    # The stable name and the command link held this already.
    from dataclasses import replace
    nothing = _left(tmp_path, env)
    on = install.Portable(folder=str(tmp_path / "apps"), command_dir=str(tmp_path / "cmd"))
    for v in ("1.0", "1.1"):
        a = _appimage(server, f"Tool-{v}-x86_64.AppImage", v.encode())
        rec = install.install(env, {**APP, "installVersion": v}, a, "appimage", [a], portable=on)
    made = {"the app menu": [str(tmp_path / "xdg" / "applications" / "appkata-demo-tool.desktop"),
                             str(tmp_path / "data" / "menu" / "demo-tool")],               # the entry, and the script it starts (#685)
            "the stable name": [str(tmp_path / "apps" / "demo-tool" / "DemoTool.AppImage")],
            "the command link": [str(tmp_path / "cmd" / "demo-tool")]}
    assert all(os.path.lexists(path) and path in rec["files"] + rec["links"] for paths in made.values() for path in paths)    # made, and in the record
    p = replace(on, **_OPTIONS[off])
    a = _appimage(server, "Tool-2.0-x86_64.AppImage", b"2.0")
    rec = {"an update": lambda: install.install(env, {**APP, "installVersion": "2.0"}, a, "appimage", [a], portable=p),
           "a launcher rewrite": lambda: install.rewrite_launcher(env, dict(APP), p),
           "a kept version": lambda: install.switch_to(env, dict(APP), "1.0", p)}[road]()
    for what, paths in made.items():
        for path in paths:
            assert os.path.lexists(path) is (what != off), (what, path)
            assert (path in rec["files"] + rec["links"]) is (what != off), (what, path)
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
@pytest.mark.parametrize("then", ["an update", "the same version again", "a kept version", "a launcher rewrite"])
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
           "a launcher rewrite": lambda: install.rewrite_launcher(env, dict(app), now)}[then]()
    home = old / "demo-tool"
    assert not os.path.lexists(new)
    assert (rec["root"], rec["target"]) == (str(old), str(home))
    assert rec["current"]["version"] == {"an update": "2.0", "a kept version": "1.0"}.get(then, "1.1")
    menu = tmp_path / "data" / "menu"
    its = [rec["current"]["path"], rec["exec"], *(k["path"] for k in rec["kept"]), *(l for l in rec["links"] if os.path.dirname(l) != str(cmd)),
           *(f for f in rec["files"] if not f.endswith(".desktop") and os.path.dirname(f) != str(menu))]
    assert all(_inside(p, home) or p == str(home) for p in its) and all(os.path.lexists(p) for p in its), its
    assert _inside(cmd / "demo-tool", home)                    # the command link leads to the app where it is
    assert _menu_starts(menu / "demo-tool") == rec["exec"] and str(menu / "demo-tool") in rec["files"]     # and the menu entry's script
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
    assert _menu_starts(_exec_words(_entry(entry)["Desktop Entry"]["Exec"])[1]) == rec["exec"]    # and what the menu starts
    assert (os.readlink(link) if link.is_symlink() else link.read_text()) == kept_as and str(link) not in rec["links"]
    assert rec["options"]["commandLink"] is True and rec["commandRefused"] == f"{link} exists and isn't a link AppKata made; not replacing it"
    link.unlink()                                                                           # the place is free again
    rec = install.rewrite_launcher(env, {**APP, "sandbox": after}, p)
    assert "commandRefused" not in rec and os.readlink(link) == rec["exec"] and str(link) in rec["links"]
    assert install.uninstall(env, APP["url"], remove_sandbox=True) == []


@linux_only
@pytest.mark.parametrize("fails", ["the menu script", "the menu entry"])
@pytest.mark.parametrize("change", list(_CHANGES))
def test_a_sandbox_change_whose_menu_file_cant_be_written_leaves_the_app_as_it_was(env, server, tmp_path, change, fails):
    # #689's review, P4-B3: a sandbox change rewrites the launcher, the menu script and entry and
    # the command link, and stores the record last. With the sandbox turned Off and the entry's
    # write failing (a full disk), the launcher was gone (an Off removes it first) and the command
    # link too, the script ran the program, the entry still passed --appkata-menu, and the stored
    # record named the removed launcher, so Open started nothing; nothing repaired it. Only the
    # move back to an app's own updater's layout was taken back. Whatever step fails, the app is
    # put back as its stored record has it, as a failed update is (R4.6), and the error is raised
    # for the Sandbox dialog to say.
    from appkata_core import sandbox
    before, after = (sandbox.resolve_template(t) if t else None for t in _CHANGES[change])
    p = install.Portable(folder=str(tmp_path / "apps"), command_dir=str(tmp_path / "cmd"))
    a = _appimage(server, "Tool-1.0-x86_64.AppImage", b"#!/bin/sh\necho 1.0\n")
    was = install.install(env, {**APP, "installVersion": "1.0", "sandbox": before}, a, "appimage", [a], portable=p)
    assert os.readlink(tmp_path / "cmd" / "demo-tool") == was["exec"] and ("launcher" in was) is bool(before)
    kept = _left(tmp_path, env)
    script, entry = str(tmp_path / "data" / "menu" / was["id"]), str(tmp_path / "xdg" / "applications" / "appkata-demo-tool.desktop")
    full = {"the menu script": script, "the menu entry": entry}[fails]
    real = install._write_whole
    with pytest.MonkeyPatch.context() as m:
        m.setattr(install, "_write_whole", _failing_once(real, lambda path, data, mode: path == full))
        with pytest.raises(OSError, match="No space left on device"):
            install.rewrite_launcher(env, {**APP, "sandbox": after}, p)
    assert _changed(kept, _left(tmp_path, env)) == {}                    # the app as it was, every file and its record
    assert _menu_starts(script) == was["exec"] and os.access(was["exec"], os.X_OK)    # what the menu and Open start
    rec = install.rewrite_launcher(env, {**APP, "sandbox": after}, p)     # and the change, made again, is made
    assert rec == json.loads(env.one("SELECT record FROM installs")["record"]) and ("launcher" in rec) is bool(after)
    assert os.readlink(tmp_path / "cmd" / "demo-tool") == rec["exec"] == _menu_starts(script) and os.access(rec["exec"], os.X_OK)
    assert ("--appkata-menu" in _exec_words(_entry(entry)["Desktop Entry"]["Exec"])) is bool(after)


def _full(entry, fails, failed):
    """install._write_whole, through which every file AppKata keeps for an app is written (P5-B3),
    failing as on a disk that stays full: every write, the menu entry's every time (its folder
    can't be written), or the menu entry's once and every one after it."""
    real = install._write_whole

    def write(path, data, mode):
        if fails == "every write" or path == entry or (failed and fails.endswith("then every write")):
            failed.append(path)
            raise OSError(28, "No space left on device")
        return real(path, data, mode)
    return write


_DISK_STAYS_FULL = ["every write", "the menu entry's, every time", "the menu entry's once, then every write"]


@linux_only
@pytest.mark.parametrize("fails", _DISK_STAYS_FULL)
@pytest.mark.parametrize("change", list(_CHANGES))
def test_a_sandbox_change_on_a_disk_that_stays_full_leaves_the_app_as_it_was(env, server, tmp_path, change, fails):
    # #689's review, P5-2: the take-back of a failed sandbox change (P4-B3) activated the stored
    # record again, writing the launcher, the menu script and the entry anew on the disk that had
    # just refused one. Where the failure lasts (a full disk, a quota, a folder that can't be
    # written) it failed at the same write and stopped: the command link, which an activation
    # removes first and makes last, was left removed under a record that named it, and a private
    # home the change made for an app that runs unsandboxed stayed (R17.13), while the toast and
    # R17.4 said the app was as it was. What the change replaces is kept beside it now, and
    # putting it back writes nothing.
    from appkata_core import sandbox
    before, after = (sandbox.resolve_template(t) if t else None for t in _CHANGES[change])
    p = install.Portable(folder=str(tmp_path / "apps"), command_dir=str(tmp_path / "cmd"))
    a = _appimage(server, "Tool-1.0-x86_64.AppImage", b"#!/bin/sh\necho 1.0\n")
    was = install.install(env, {**APP, "installVersion": "1.0", "sandbox": before}, a, "appimage", [a], portable=p)
    assert os.readlink(tmp_path / "cmd" / "demo-tool") == was["exec"] and ("launcher" in was) is bool(before)
    kept, failed = _left(tmp_path, env), []
    script, entry = str(tmp_path / "data" / "menu" / was["id"]), str(tmp_path / "xdg" / "applications" / "appkata-demo-tool.desktop")
    with pytest.MonkeyPatch.context() as m:
        m.setattr(install, "_write_whole", _full(entry, fails, failed))
        with pytest.raises(OSError, match="No space left on device") as e:
            install.rewrite_launcher(env, {**APP, "sandbox": after}, p)
    assert failed and _changed(kept, _left(tmp_path, env)) == {}        # every file, link, private home, and the record
    assert _menu_starts(script) == was["exec"] and os.access(was["exec"], os.X_OK)    # what the menu and Open start
    assert not isinstance(e.value, install.NotPutBack)                   # all of it put back, as the error says
    rec = install.rewrite_launcher(env, {**APP, "sandbox": after}, p)     # with room on the disk, the change is made
    assert rec == json.loads(env.one("SELECT record FROM installs")["record"]) and ("launcher" in rec) is bool(after)
    assert os.readlink(tmp_path / "cmd" / "demo-tool") == rec["exec"] == _menu_starts(script) and os.access(rec["exec"], os.X_OK)


# What the user knows each of an app's paths as (install.NotPutBack's words), by its place under the test's folder
_PARTS = {os.path.join("apps", "demo-tool", "run"): "its launcher",
          os.path.join("data", "sandboxes", ".identity", "apps", "demo-tool"): "its launcher",
          os.path.join("data", "menu", "demo-tool"): "its app-menu entry",
          os.path.join("xdg", "applications", "appkata-demo-tool.desktop"): "its app-menu entry",
          os.path.join("cmd", "demo-tool"): "its command link",
          os.path.join("apps", "demo-tool", "DemoTool.AppImage"): "its stable name link",
          os.path.join("data", "sandboxes", "demo-tool"): "its private home",
          os.path.join("data", "sandboxes", ".owners", "demo-tool"): "its private home"}


@linux_only
@pytest.mark.parametrize("change", list(_CHANGES))
def test_a_sandbox_change_that_cant_be_put_back_names_what_isnt_as_it_was(env, server, tmp_path, monkeypatch, change):
    # #689's review, P5-2: where even putting a change back fails, the error says what isn't as
    # it was, and that is exactly what isn't, so the toast doesn't say the app runs as it did. Here
    # the file system makes no hard links, so what the change replaced is kept as its bytes and
    # written back, and the disk is full from the menu entry's write on.
    from appkata_core import sandbox
    before, after = (sandbox.resolve_template(t) if t else None for t in _CHANGES[change])
    p = install.Portable(folder=str(tmp_path / "apps"), command_dir=str(tmp_path / "cmd"))
    a = _appimage(server, "Tool-1.0-x86_64.AppImage", b"#!/bin/sh\necho 1.0\n")
    install.install(env, {**APP, "installVersion": "1.0", "sandbox": before}, a, "appimage", [a], portable=p)
    kept, failed = _left(tmp_path, env), []
    entry = str(tmp_path / "xdg" / "applications" / "appkata-demo-tool.desktop")

    def no_hard_links(*a, **k):
        raise OSError(1, "Operation not permitted")
    monkeypatch.setattr(os, "link", no_hard_links)
    with pytest.MonkeyPatch.context() as m:
        m.setattr(install, "_write_whole", _full(entry, "the menu entry's once, then every write", failed))
        with pytest.raises(install.NotPutBack, match="No space left on device") as e:
            install.rewrite_launcher(env, {**APP, "sandbox": after}, p)
    changed = _changed(kept, _left(tmp_path, env))
    assert "<installs>" not in changed and changed                     # the record as it was; some file not
    assert sorted(e.value.left) == sorted({_PARTS[k] for k in changed})  # named, every one, and only those
    assert not [k for k in _left(tmp_path, env) if k.endswith(".was")]   # and nothing kept is left beside its place
    rec = install.rewrite_launcher(env, {**APP, "sandbox": after}, p)     # with room on the disk, the change is made
    assert rec == json.loads(env.one("SELECT record FROM installs")["record"]) and ("launcher" in rec) is bool(after)
    assert os.readlink(tmp_path / "cmd" / "demo-tool") == rec["exec"] and os.access(rec["exec"], os.X_OK)


def _beside(tmp_path, env):
    """What a process stopped part-way leaves beside an app's files, of all _left lists: a hard link a
    sandbox change kept (`<path>.<pid>.was`) and a file a write hadn't finished (`<path>.<pid>.tmp`)."""
    return sorted(k for k in _left(tmp_path, env) if re.search(r"\.[0-9]+\.(was|tmp)$", k))


# The files of the test's sandboxed Demo Tool a sandbox change keeps aside, by their place under the test's folder
_KEPT = [os.path.join("apps", "demo-tool", "run"), os.path.join("data", "sandboxes", ".identity", "apps", "demo-tool"),
         os.path.join("data", "sandboxes", ".owners", "demo-tool"), os.path.join("data", "menu", "demo-tool"),
         os.path.join("xdg", "applications", "appkata-demo-tool.desktop")]


def _stopped_change(tmp_path, env, p, monkeypatch, gs):
    """A sandbox change to `gs` whose process stopped (killed, the power gone) once the change was
    written and before it dropped what it kept beside the app's files, and a write by another
    process stopped the same way beside each of them."""
    with monkeypatch.context() as m:
        m.setattr(install, "_drop_aside", lambda kept: None)
        install.rewrite_launcher(env, {**APP, "sandbox": gs}, p)
    for f in _KEPT:
        os.rename(tmp_path / f"{f}.{os.getpid()}.was", tmp_path / f"{f}.4241.was")       # that process's, not this one's
        open(tmp_path / f"{f}.4242.tmp", "w").close()


@linux_only
@pytest.mark.parametrize("home", [True, False], ids=["with its private home", "keeping its private home"])
def test_an_uninstall_removes_what_a_stopped_change_left_beside_the_apps_files(env, server, tmp_path, monkeypatch, home):
    # #689's review, P6-B2: a sandbox change keeps the files it replaces as hard links beside them
    # (<path>.<pid>.was) and drops them once it is written or put back. A process stopped between
    # the two left them, as a write stopped part-way leaves <path>.<pid>.tmp; the next change of
    # the app removed the .was, and an uninstall removed nothing but each file by its own name, so
    # the old menu script, the old entry (in the user's applications folder), the old identity
    # marker and the owner record (the app's URL) stayed for good, the private home gone or not.
    from appkata_core import sandbox
    p = install.Portable(folder=str(tmp_path / "apps"), command_dir=str(tmp_path / "cmd"))
    a = _appimage(server, "Tool-1.0-x86_64.AppImage", b"#!/bin/sh\necho 1.0\n")
    install.install(env, {**APP, "installVersion": "1.0", "sandbox": sandbox.resolve_template("standard")}, a, "appimage", [a], portable=p)
    _stopped_change(tmp_path, env, p, monkeypatch, sandbox.resolve_template("strict"))
    left = _beside(tmp_path, env)
    assert len([k for k in left if k.endswith(".was")]) == len([k for k in left if k.endswith(".tmp")]) == 5, left
    assert install.uninstall(env, APP["url"], remove_sandbox=home) == []
    assert _beside(tmp_path, env) == []
    owner = tmp_path / "data" / "sandboxes" / ".owners" / "demo-tool"
    assert owner.exists() is not home                                   # the private home, kept or not, as asked


@linux_only
def test_the_sweep_removes_only_what_a_stopped_change_or_write_left_beside_an_apps_files(env, server, tmp_path, monkeypatch, caplog):
    # #689's review, P7-T1: the sweep removes <path>.<digits>.was and <path>.<digits>.tmp beside an
    # app's files and nothing else (R17.4). Every file the tests put beside them was of that shape
    # or matched none of its globs, so with the check of the name and the folder taken out every
    # test still passed. Here a file of each near shape is beside them too, with a folder and a
    # link to one of the shape, and what a stopped write left of an app AppKata didn't install:
    # AppKata's start removes the ten its stopped change left, keeps all of these and tries none.
    import logging
    from appkata_core import sandbox
    p = install.Portable(folder=str(tmp_path / "apps"), command_dir=str(tmp_path / "cmd"))
    a = _appimage(server, "Tool-1.0-x86_64.AppImage", b"#!/bin/sh\necho 1.0\n")
    install.install(env, {**APP, "installVersion": "1.0", "sandbox": sandbox.resolve_template("standard")}, a, "appimage", [a], portable=p)
    _stopped_change(tmp_path, env, p, monkeypatch, sandbox.resolve_template("strict"))
    left = _beside(tmp_path, env)
    run, mine = str(tmp_path / _KEPT[0]), tmp_path / "mine"
    keep = [f"{run}.abc.was", f"{run}.1.2.tmp", f"{run}..tmp", f"{run}.-5.was", f"{run}.٣.was", f"{run}.5.was.d",
            f"{tmp_path / _KEPT[4]}.12.was.bak", str(tmp_path / "xdg" / "applications" / "appkata-other.desktop.4242.tmp")]
    for f in keep:
        open(f, "w").close()
    mine.mkdir()
    os.mkdir(f"{run}.77.was")                                           # a folder
    os.symlink(mine, f"{run}.88.tmp")                                   # and a link to one
    keep += [f"{run}.77.was", f"{run}.88.tmp"]
    caplog.set_level(logging.WARNING, logger="appkata.install")
    assert sorted(os.path.relpath(f, tmp_path) for f in install.sweep_left_beside(env)) == left and len(left) == 10
    assert [f for f in keep if not os.path.lexists(f)] == [] and caplog.text == ""
    assert sorted(_beside(tmp_path, env)) == sorted(os.path.relpath(f, tmp_path) for f in keep if re.search(r"\.[0-9]+\.(was|tmp)$", f))


@linux_only
@pytest.mark.parametrize("where", ["AppKata's start", "the change that kept it"])
def test_a_file_left_beside_an_apps_files_that_cant_be_removed_is_logged_with_why(env, server, tmp_path, monkeypatch, caplog, where):
    # #689's review, P7-B1a: a leftover beside an app's files that AppKata's start (or the app's
    # next change, or its uninstall) can't remove was logged by its path alone, at every start that
    # met it, and so was a file a sandbox change kept beside one and couldn't drop once it was
    # written: the App log never said why (R14.2), where the start's other steps say theirs.
    import logging
    from appkata_core import sandbox
    p = install.Portable(folder=str(tmp_path / "apps"), command_dir=str(tmp_path / "cmd"))
    a = _appimage(server, "Tool-1.0-x86_64.AppImage", b"#!/bin/sh\necho 1.0\n")
    install.install(env, {**APP, "installVersion": "1.0", "sandbox": sandbox.resolve_template("standard")}, a, "appimage", [a], portable=p)
    start = where == "AppKata's start"
    if start:
        _stopped_change(tmp_path, env, p, monkeypatch, sandbox.resolve_template("strict"))
    stuck, real = str(tmp_path / f"{_KEPT[0]}.{4241 if start else os.getpid()}.was"), os.remove

    def remove(path, *a, **k):
        if str(path) == stuck:
            raise PermissionError(13, "Permission denied", str(path))
        return real(path, *a, **k)
    caplog.set_level(logging.WARNING, logger="appkata.install")
    with monkeypatch.context() as m:
        m.setattr(install.os, "remove", remove)
        if start:
            assert stuck not in install.sweep_left_beside(env) and len(_beside(tmp_path, env)) == 1
        else:
            install.rewrite_launcher(env, {**APP, "sandbox": sandbox.resolve_template("strict")}, p)
    assert f"couldn't remove {stuck}: Permission denied" in caplog.text
    assert install.sweep_left_beside(env) == [stuck] and _beside(tmp_path, env) == []     # gone once it can be


@linux_only
def test_a_sandbox_change_removes_what_one_stopped_part_way_left_beside_the_apps_files(env, server, tmp_path, monkeypatch):
    # #689's review, P6-B3: a sandbox change removes, before it keeps the app's files beside them,
    # what an earlier change or write stopped part-way left there (_keep_aside), and no test failed
    # with that removal taken out.
    from appkata_core import sandbox
    p = install.Portable(folder=str(tmp_path / "apps"), command_dir=str(tmp_path / "cmd"))
    a = _appimage(server, "Tool-1.0-x86_64.AppImage", b"#!/bin/sh\necho 1.0\n")
    install.install(env, {**APP, "installVersion": "1.0", "sandbox": sandbox.resolve_template("standard")}, a, "appimage", [a], portable=p)
    _stopped_change(tmp_path, env, p, monkeypatch, sandbox.resolve_template("strict"))
    assert len(_beside(tmp_path, env)) == 10
    rec = install.rewrite_launcher(env, {**APP, "sandbox": sandbox.resolve_template("standard")}, p)
    assert _beside(tmp_path, env) == []                                 # none of it, and nothing of its own
    assert rec == json.loads(env.one("SELECT record FROM installs")["record"]) and rec["exec"] == rec["launcher"]
    assert install.launcher_is_current(rec, {**APP, "sandbox": sandbox.resolve_template("standard")}, p)


@linux_only
def test_a_failed_sandbox_change_puts_back_the_links_it_removed_or_moved(env, server, tmp_path):
    # #689's review, P6-B3: what a failed change put back by a link was untested: a link at the
    # place of one of the app's kept files (_keep_aside keeps it by its target, and _put_back makes
    # it again), as the user's own entry linked in for the app's; and the command link, which the
    # change pointed elsewhere. Here the sandbox is turned Off with the app menu turned off since
    # the install, so the change removes both menu links and points the command link at the
    # program, and then its record can't be stored.
    from dataclasses import replace
    from appkata_core import sandbox
    p = install.Portable(folder=str(tmp_path / "apps"), command_dir=str(tmp_path / "cmd"))
    a = _appimage(server, "Tool-1.0-x86_64.AppImage", b"#!/bin/sh\necho 1.0\n")
    was = install.install(env, {**APP, "installVersion": "1.0", "sandbox": sandbox.resolve_template("standard")}, a, "appimage", [a], portable=p)
    mine = tmp_path / "mine"
    mine.mkdir()
    for f in (tmp_path / "data" / "menu" / "demo-tool", tmp_path / "xdg" / "applications" / "appkata-demo-tool.desktop"):
        shutil.copy(f, mine / f.name)
        f.unlink()
        f.symlink_to(mine / f.name)
    cmd = tmp_path / "cmd" / "demo-tool"
    assert os.readlink(cmd) == was["launcher"]
    kept = _left(tmp_path, env)
    with pytest.MonkeyPatch.context() as m:
        m.setattr(env, "x", _failing_once(env.x, lambda sql, *a: sql.startswith("UPDATE installs")))
        with pytest.raises(OSError, match="No space left on device") as e:
            install.rewrite_launcher(env, {**APP, "sandbox": None}, replace(p, app_menu=False))
    assert not isinstance(e.value, install.NotPutBack)                   # all of it put back, as the error says
    assert _changed(kept, _left(tmp_path, env)) == {}                    # the menu links and the command link too
    rec = install.rewrite_launcher(env, {**APP, "sandbox": None}, replace(p, app_menu=False))    # and then it is made
    assert os.readlink(cmd) == rec["exec"] != was["launcher"] and not os.path.lexists(tmp_path / "data" / "menu" / "demo-tool")


@linux_only
def test_a_failed_sandbox_change_removes_the_command_link_it_made(env, server, tmp_path, monkeypatch):
    # #689's review, P7-T3: a failed change puts back the links it removed or moved (P6-B3's test),
    # and removes a link it made where the stored record had none; with that removal taken out
    # every test still passed. Here the app's name was a command at its install, so it got no
    # command link (R4.3.1.3); that command is uninstalled since, so the sandbox change makes the
    # link, and then its record can't be stored. The link it made goes, as R17.4 has the app left
    # as it was: under a record that doesn't name it, nothing would remove it, at uninstall either.
    from appkata_core import sandbox
    system = tmp_path / "usr-bin"
    system.mkdir()
    (system / "demo-tool").write_text("#!/bin/sh\n")
    (system / "demo-tool").chmod(0o755)
    monkeypatch.setenv("PATH", f"{os.environ['PATH']}:{system}")
    p = install.Portable(folder=str(tmp_path / "apps"), command_dir=str(tmp_path / "cmd"))
    a = _appimage(server, "Tool-1.0-x86_64.AppImage", b"#!/bin/sh\necho 1.0\n")
    was = install.install(env, {**APP, "installVersion": "1.0", "sandbox": sandbox.resolve_template("standard")}, a, "appimage", [a], portable=p)
    cmd = tmp_path / "cmd" / "demo-tool"
    assert was["commandRefused"] and not os.path.lexists(cmd)
    (system / "demo-tool").unlink()                                     # the name is free now
    kept, made, real = _left(tmp_path, env), [], env.x

    def store(sql, *a, **k):
        if sql.startswith("UPDATE installs") and not made:
            made.append(os.path.islink(cmd))                            # the change has made its link by now
            raise OSError(28, "No space left on device")
        return real(sql, *a, **k)
    with pytest.MonkeyPatch.context() as m:
        m.setattr(env, "x", store)
        with pytest.raises(OSError, match="No space left on device") as e:
            install.rewrite_launcher(env, {**APP, "sandbox": sandbox.resolve_template("strict")}, p)
    assert made == [True] and not isinstance(e.value, install.NotPutBack)
    assert _changed(kept, _left(tmp_path, env)) == {}                    # the link it made gone, and all else as it was
    rec = install.rewrite_launcher(env, {**APP, "sandbox": sandbox.resolve_template("strict")}, p)    # then it is made, link and all
    assert os.readlink(cmd) == rec["exec"] == rec["launcher"] and "commandRefused" not in rec


@linux_only
@pytest.mark.parametrize("kind", ["appimage", "tarball"])
def test_a_failed_move_back_to_the_fixed_name_that_cant_be_undone_is_named(env, server, tmp_path, monkeypatch, kind):
    # #689's review, P6-B3: turning the sandbox Off for an app that updates itself moves its current
    # version to the fixed name (R4.10.2) first; when a later step fails and the version can't be
    # moved back either, the error names it, so the toast doesn't say the app runs as it did
    # (R17.4), and no test failed with that taken out.
    from appkata_core import sandbox
    home = tmp_path / "apps" / "demo-tool"
    p = install.Portable(folder=str(tmp_path / "apps"), command_dir=str(tmp_path / "cmd"))
    gs = sandbox.resolve_template("standard")
    a = _version(server, kind, "1.0")
    install.install(env, {**APP, "installVersion": "1.0", "autoUpdate": True}, a, kind, [a], portable=p)
    install.rewrite_launcher(env, {**APP, "autoUpdate": True, "sandbox": gs}, p)
    a = _version(server, kind, "2.0")
    was = install.install(env, {**APP, "installVersion": "2.0", "sandbox": gs}, a, kind, [a], portable=p)
    fixed, before = str(home / ("DemoTool.AppImage" if kind == "appimage" else "app")), was["current"]["path"]
    with monkeypatch.context() as m:
        m.setattr(env, "x", _failing_once(env.x, lambda sql, *a: sql.startswith("UPDATE installs")))
        m.setattr(install.os, "replace", _failing_once(os.replace, lambda src, dst: (src, dst) == (fixed, before)))
        with pytest.raises(install.NotPutBack, match="No space left on device") as e:
            install.rewrite_launcher(env, {**APP, "autoUpdate": True, "sandbox": None}, p)
    assert os.path.lexists(fixed) and not os.path.lexists(before)        # the version is at the fixed name
    assert "the folder of its current version" in e.value.left, e.value.left


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
    assert _runs(_exec_words(entry["Desktop Entry"]["Exec"])[1]) == "codium"


# ---------------------------------------------------------------- Windows' "Installs to" for an installed app (CR1.8-36)

@pytest.mark.parametrize("scope", ["me", "everyone"])
def test_install_options_on_windows_show_the_folder_an_installed_app_is_in(tmp_path, monkeypatch, scope):
    # CR1.8-36: since CR1.3-12 an installed app stays in the folder it is in when the install folder
    # setting changes (R4.3.1), and Linux's "Installs to" said so; Windows' read Settings' two folders,
    # so it named a folder the app isn't in and won't go to. It reads the app's own now, for the
    # scope it is installed for. The other scope is a move, a new install (R15.4.1), and goes where
    # Settings says: the backend's options had given it the app's folder too, so an app moved to
    # Everyone would have been installed in the user's own folder.
    pytest.importorskip("PySide6")                              # the backend is Qt's; the Windows run has none
    from appkata_core import channels, platform, sync
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from appkata.backend import Backend
    be = Backend(db_path=str(tmp_path / "appkata.db"), heal=False)
    for module in (platform, install):
        monkeypatch.setattr(module, "OS", "windows")
    assets = [{"name": "Demo-1.0-win-x64.zip", "url": "https://example.org/Demo-1.0-win-x64.zip", "size": 1000}]
    monkeypatch.setattr(sync, "ensure_assets", lambda db, http, url, version: {"assets": assets})
    monkeypatch.setattr(channels, "enabled", lambda: False)
    monkeypatch.setattr(be, "_app", lambda url: {"url": APP["url"], "name": "Demo", "installed": "1.0", "version": "1.0", "updateTo": ""})
    settings = {"me": str(tmp_path / "now" / "me"), "everyone": str(tmp_path / "now" / "everyone")}
    be._prefs["installDir"], be._prefs["installDirEveryone"] = settings["me"], settings["everyone"]

    assert be.planFor(APP["url"])["windows"] == {"scope": "me", "motw": False, "folderMe": settings["me"],
                                                 "folderEveryone": settings["everyone"]}        # not installed: Settings'
    was = str(tmp_path / "then" / scope)                                                        # Settings' when it was installed
    rec = {"current": {"version": "1.0", "path": os.path.join(was, "demo", "1.0"), "exec": "1.0\\Demo.exe"},
           "target": os.path.join(was, "demo"), "root": was, "scope": scope, "links": [], "files": []}
    env = DB(str(tmp_path / "appkata.db"))
    env.x("INSERT INTO installs(url, name, version, kind, record, installed_at) VALUES(?,?,?,?,?,?)",
          (APP["url"], "Demo", "1.0", "zip", json.dumps(rec), "2026-11-24T00:00:00Z"))
    other = "everyone" if scope == "me" else "me"
    plan = be.planFor(APP["url"])["windows"]
    assert plan["scope"] == scope
    assert plan["folderMe" if scope == "me" else "folderEveryone"] == was                      # where it is
    assert plan["folderMe" if other == "me" else "folderEveryone"] == settings[other]          # where a move goes
    assert be._app_options(APP["url"]).root == was
    assert be._app_options(APP["url"], {"scope": other}).root == settings[other]               # what the move installs into


# ---------------------------------------------------------------- a release's own text as a part of a path (CR1.3-8)

def _own(tmp_path, env, app_id="demo-tool"):
    """What an install changed that isn't the app's own: every difference `_left` sees from before
    it, but the app's folder, its downloads, its command link (in the tests' `cmd`), its menu
    entry with its script, and its row. Returns a function to call after it."""
    before = _left(tmp_path, env)
    own = tuple(os.path.join(*p, "") for p in (("apps", app_id), ("data", "downloads", app_id), ("cmd", app_id),
                                               ("data", "menu", app_id), ("xdg", "applications", f"appkata-{app_id}.desktop")))

    def others():
        return {k: v for k, v in _changed(before, _left(tmp_path, env)).items()
                if k != "<installs>" and not (k + os.sep).startswith(own)}
    return others


# where each name leads from the download folder (<data>/downloads/<app>/) and from the app's
# folder (<apps>/<app>/), which are at different depths: {how the release names its file: the name}
_PATH_NAMES = {"three folders up": "../../../{}", "two folders up": "../../{}", "another app's folder": "../other-app/{}",
               "an absolute path": "{abs}", "a path that comes back": "x/../{}", "in a folder": "sub/{}"}


@linux_only
@pytest.mark.parametrize("kind", ["appimage", "tarball", "a self-updating appimage"])
@pytest.mark.parametrize("named", list(_PATH_NAMES))
def test_a_release_file_named_as_a_path_is_kept_under_its_last_part_in_the_apps_own_folders(env, server, tmp_path, named, kind):
    # CR1.3-8: the release's name for its file was joined to the download folder and to the app's
    # folder as it came. `../../../victim.tar.gz` was downloaded over the user's file three folders
    # up; as an AppImage it was then moved to another depth, where a missing folder made the
    # install fail and the failure deleted what the download had just replaced, and an existing one
    # got the program, executable, outside the app's folder; `/...` dropped AppKata's folder.
    file = "Victim-1.2.0-x86_64.AppImage" if "appimage" in kind else "victim-1.2.0-linux-x86_64.tar.gz"
    theirs = [tmp_path / file, tmp_path / "apps" / file, tmp_path / "apps" / "other-app" / file,
              tmp_path / "data" / "downloads" / "other-app" / file, tmp_path / "data" / file]
    for f in theirs:                    # the user's, and another app's, wherever such a name leads
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("theirs")
    if "appimage" in kind:
        a = _appimage(server, "served.AppImage", b"\x7fELF the release's")
    else:
        a = _tarball(server, "served.tar.gz", {"tool-1.2.0/tool": 0o755})
    a = Asset(_PATH_NAMES[named].format(file, abs=str(theirs[0])), a.url)
    others = _own(tmp_path, env)
    app = {**APP, "autoUpdate": True} if kind.startswith("a self-updating") else APP
    rec = install.install(env, app, a, kind.split()[-1], [a],
                          portable=install.Portable(folder=str(tmp_path / "apps"), app_menu=False, command_dir=""))
    assert others() == {} and [f.read_text() for f in theirs] == ["theirs"] * len(theirs)
    folder = tmp_path / "apps" / "demo-tool"
    assert os.path.dirname(rec["current"]["path"]) == str(folder) and _inside(rec["exec"], folder)
    if kind == "appimage":                                      # under the name's last part (R4.3.1)
        assert os.path.basename(rec["current"]["path"]) == file
    assert _downloads() == [str(theirs[3])]                     # nothing of this app's, and the other app's as it was
    assert env.one("SELECT asset FROM installs")["asset"] == a.name        # the release's own name, as its checksums name it


@pytest.mark.parametrize("named", list(_PATH_NAMES) + ["three folders up, by backslashes"])
def test_a_download_named_as_a_path_that_fails_its_checksum_is_deleted_where_it_was_downloaded(env, server, tmp_path, named):
    # CR1.3-8, the failure's side (R4.8.2: "A complete file that fails its checksum or its install
    # is deleted"): the file deleted was the one the release's name led to. On every system, so
    # Windows' run shows it with its own separator; the backslashes are one file's name on Linux.
    root, base = server
    (root / "served.AppImage").write_bytes(b"tampered")
    file = "Victim-1.2.0-x86_64.AppImage"
    theirs = [tmp_path / file, tmp_path / "apps" / file, tmp_path / "apps" / "other-app" / file, tmp_path / "data" / file]
    for f in theirs:
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("theirs")
    form = _PATH_NAMES.get(named) or "..\\..\\..\\{}"
    a = Asset(form.format(file, abs=str(theirs[0])), base + "/served.AppImage", digest="sha256:" + hashlib.sha256(b"original").hexdigest())
    with pytest.raises(install.InstallError, match="doesn't match its checksum"):
        install.install(env, APP, a, "appimage", [a])
    assert [f.read_text() for f in theirs] == ["theirs"] * len(theirs)
    assert _downloads() == [] and not (tmp_path / "apps" / "demo-tool").exists()


def test_appkatas_own_setup_named_as_a_path_waits_in_the_updates_folder(env, server, tmp_path, monkeypatch):
    # CR1.3-8, AppKata's own update on Windows (R2.11.5): the setup that waits for the restart was
    # moved to the updates folder joined with the release's name, and run from there with the
    # user's rights or an administrator's. Windows' road, on any system.
    from appkata_core import windows
    monkeypatch.setattr(install, "OS", "windows")
    monkeypatch.setattr(windows, "authenticode", lambda path: ("NotSigned", ""))
    root, base = server
    (root / "served.exe").write_bytes(b"MZ the new setup")
    theirs = [tmp_path / "AppKata-Setup.exe", tmp_path / "data" / "AppKata-Setup.exe"]     # two up from the updates folder,
    for f in theirs:                                                                    # and from the download's
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("theirs")
    a = Asset("../../AppKata-Setup.exe", base + "/served.exe")
    rec = install.install(env, {**APP, "selfSetup": True}, a, "exe", [a])
    assert rec["pendingSetup"] == str(tmp_path / "data" / "updates" / "AppKata-Setup.exe")
    assert open(rec["pendingSetup"], "rb").read() == b"MZ the new setup" and [f.read_text() for f in theirs] == ["theirs"] * 2
    assert os.listdir(tmp_path / "data" / "updates") == ["AppKata-Setup.exe"] and _downloads() == []


_FILE_NAMES = [     # (the release's name for its file, the name it is kept under: None = refused), on (which systems)
    ("Tool-1.2.0-x86_64.AppImage", "Tool-1.2.0-x86_64.AppImage", "both"),
    ("My Tool (1.2).tar.gz", "My Tool (1.2).tar.gz", "both"),
    ("日本語アプリ-1.0.AppImage", "日本語アプリ-1.0.AppImage", "both"),
    ("../../../victim.tar.gz", "victim.tar.gz", "both"),
    ("/etc/victim.tar.gz", "victim.tar.gz", "both"),
    ("..\\..\\..\\AppData\\Roaming\\Microsoft\\Windows\\Start Menu\\Programs\\Startup\\x.exe", "x.exe", "both"),
    ("C:\\Users\\Public\\x.exe", "x.exe", "both"),
    ("\\\\server\\share\\x.exe", "x.exe", "both"),
    ("a/b\\c/..\\x.zip", "x.zip", "both"),
    ("", None, "both"), (".", None, "both"), ("..", None, "both"), ("../..", None, "both"), ("tool/", None, "both"),
    ("tool\\", None, "both"), ("/", None, "both"),
    (".AppImage", None, "both"), ("../.hidden.tar.gz", None, "both"), ("...", None, "both"),
    ("tool\n.AppImage", None, "both"), ("tool\x00.AppImage", None, "both"), ("tool\x7f.zip", None, "both"),
    ("C:x.exe", None, "windows"), ("x.exe:stream", None, "windows"), ("con.exe", None, "windows"), ("NUL", None, "windows"),
    ("x/COM1.zip", None, "windows"), ("tool.exe.", None, "windows"), ("tool.exe ", None, "windows"), ("a<b>.zip", None, "windows"),
    ('a"b.zip', None, "windows"), ("a|b.zip", None, "windows"), ("a?.zip", None, "windows"), ("a*.zip", None, "windows"),
]


@pytest.mark.parametrize("system", ["linux", "windows"])
@pytest.mark.parametrize("name,kept,on", _FILE_NAMES, ids=[repr(n) for n, _, _ in _FILE_NAMES])
def test_the_one_file_name_a_release_file_is_kept_under(monkeypatch, name, kept, on, system):
    # R4.8.2: the part after the last / or \ (on every system), refused when that is no file's name
    # here. What Windows alone refuses is a name on Linux, where a release's Linux file may hold it.
    monkeypatch.setattr(install, "OS", system)
    if kept is None and on in ("both", system):
        with pytest.raises(install.InstallError, match="has a name that can't be used .*nothing was installed"):
            install._file_name(name)
    else:
        got = install._file_name(name)
        assert got == (kept or name.rsplit("/", 1)[-1]) and "/" not in got and "\\" not in got


def test_a_release_whose_file_has_no_usable_name_is_refused_before_anything_is_downloaded(env, server, tmp_path):
    a = _appimage(server, "served.AppImage")
    others = _own(tmp_path, env)
    with pytest.raises(install.InstallError, match="has a name that can't be used"):
        install.install(env, APP, Asset("../..", a.url), "appimage", [a])
    assert others() == {} and _downloads() == [] and not (tmp_path / "apps").exists()
    assert not (tmp_path / "data" / "downloads").exists() and env.one("SELECT * FROM installs") is None


@pytest.mark.parametrize("name", ["../x-1.0.AppImage", "/x-1.0.AppImage", "sub/x-1.0.AppImage", "..", ".", ""])
def test_no_name_is_joined_to_a_folder_unless_it_names_a_file_in_it(tmp_path, name):
    # the check at the place of use: whatever cleans a name where it comes in, a path that isn't
    # directly in its folder is refused before anything is written, moved or deleted there
    folder = tmp_path / "apps" / "demo-tool"
    with pytest.raises(install.InstallError, match="isn't a name in"):
        install._in_folder(str(folder), name)
    assert install._in_folder(str(folder), "x-1.0.AppImage") == str(folder / "x-1.0.AppImage")
    if "x-1.0" in name:                 # and _place, given a path for the release's file name
        file = tmp_path / "downloaded"
        file.write_bytes(b"\x7fELF")
        with pytest.raises(install.InstallError, match="isn't a name in"):
            install._place("appimage", str(file), APP, str(folder), "1.0", name)
        assert file.read_bytes() == b"\x7fELF" and os.listdir(folder) == [] and os.listdir(tmp_path / "apps") == ["demo-tool"]


# ---------------------------------------------------------------- a release's version as a part of a path (CR1.3-9)

def _other_app(env, server, p):
    """Another app in the same install folder, installed and running."""
    b = _tarball(server, "other-1.0.tar.gz", {"other-1.0/other": 0o755})
    rec = install.install(env, {**APP, "url": APP["url"] + "-other", "name": "Other", "repo": "demo/other", "installVersion": "1.0"},
                          b, "tarball", [b], portable=p)
    assert _runs(rec["exec"]) == "other-1.0/other"
    return rec


@linux_only
@pytest.mark.parametrize("version", ["..", ".", "...", ".hidden", "../.."])
def test_a_release_whose_version_is_dots_gets_a_folder_in_the_apps_own_and_takes_no_other_apps(env, server, tmp_path, version):
    # CR1.3-9: R4.3.1 unpacks an archive "into a folder named after its version", and the name kept
    # the version's dots: for `..` that folder was the install folder itself, with every app in it,
    # and for `.` the app's own, with its kept versions. A version is whatever the host that
    # answers as the forge sends. The app is installed all the same, in a folder of its own.
    p = install.Portable(folder=str(tmp_path / "apps"), command_dir=str(tmp_path / "cmd"), keep=2)
    other = _other_app(env, server, p)
    a = _version(server, "tarball", "1.0")
    install.install(env, {**APP, "installVersion": "1.0"}, a, "tarball", [a], portable=p)
    others = _own(tmp_path, env)
    a = _tarball(server, "tool-next.tar.gz", {"tool-next/tool": 0o755})
    rec = install.install(env, {**APP, "installVersion": version}, a, "tarball", [a], portable=p)
    home = tmp_path / "apps" / "demo-tool"
    assert others() == {} and _runs(other["exec"]) == "other-1.0/other"
    assert os.path.dirname(rec["current"]["path"]) == str(home) and not os.path.basename(rec["current"]["path"]).startswith(".")
    assert rec["current"]["version"] == version and _runs(rec["exec"]) == "tool-next/tool" == _runs(tmp_path / "cmd" / "demo-tool")
    assert [k["version"] for k in rec["kept"]] == ["1.0"] and os.path.isdir(rec["kept"][0]["path"])      # its kept version too
    back = install.switch_to(env, dict(APP), "1.0", p)                      # which it goes back to, and returns from
    assert _runs(back["exec"]) == "tool-1.0/tool" and [k["version"] for k in back["kept"]] == [version]
    assert _runs(install.switch_to(env, dict(APP), version, p)["exec"]) == "tool-next/tool"
    assert install.uninstall(env, APP["url"]) == [] and not os.path.lexists(home)
    assert others() == {} and _runs(other["exec"]) == "other-1.0/other"


@pytest.mark.parametrize("system", ["linux", "windows"])
def test_a_version_is_always_one_plain_name_in_the_apps_folder(monkeypatch, system):
    # the class, for whatever a version holds: never empty, `.` or `..`, never a hidden name, never
    # a path; and the versions people release are named as they were
    import itertools
    from appkata_core import sandbox
    monkeypatch.setattr(install, "OS", system)
    for v, name in (("2.1", "2.1"), ("1.0-beta+3", "1.0-beta+3"), ("v2", "v2"), ("nightly/2026 11", "nightly_2026_11"),
                    ("", "unknown"), ("..", "_.."), (".", "_."), ("...", "_..."), (".5", "_.5"), ("../..", "_.._.."),
                    ("/", "_"), ("\\", "_"), ("日本", "_")):
        assert install._safe(v) == (name if system == "linux" or not name.endswith(".") else name.rstrip(".") + "_"), v
    folder = os.path.join(os.path.abspath(os.sep), "apps", "demo-tool")
    for v in ("".join(c) for n in range(6) for c in itertools.product("./\\ a_", repeat=n)):
        s = install._safe(v)
        assert s and s not in (".", "..") and not s.startswith(".") and "/" not in s and "\\" not in s, (v, s)
        assert os.path.dirname(install._in_folder(folder, s)) == folder, (v, s)
        assert system != "windows" or s[-1] not in ". ", (v, s)
        assert os.path.dirname(sandbox.extracted_dir(folder, v)) == folder                # an extracted AppImage's folder
        name = install._appimage_name("Tool.AppImage", v)                       # and an AppImage's own file
        assert os.path.dirname(install._in_folder(folder, name)) == folder and name.startswith("Tool"), (v, name)


def test_no_version_is_placed_in_a_folder_that_isnt_in_the_apps_own(tmp_path, monkeypatch):
    # the check at the place of use (_in_folder), should a version's name ever come out as a path
    folder, file = tmp_path / "apps" / "demo-tool", tmp_path / "downloaded.tar.gz"
    (tmp_path / "apps" / "other-app" / "1.0").mkdir(parents=True)
    file.write_bytes(b"an archive")
    for name in ("..", ".", "../other-app", "/x", "a/b"):
        monkeypatch.setattr(install, "_safe", lambda v, name=name: name)
        with pytest.raises(install.InstallError, match="isn't a name in"):
            install._place("tarball", str(file), APP, str(folder), "1.0", "tool.tar.gz")
        assert os.listdir(folder) == [] and os.listdir(tmp_path / "apps" / "other-app") == ["1.0"] and file.exists()


# ---------------------------------------------------------------- the file AppKata names after an app (CR1.3-39)

@linux_only
@pytest.mark.parametrize("name", ["日本語アプリ", "Приложение", "Εφαρμογή", "…", "!!!", ""])
def test_an_app_whose_name_has_no_ascii_letter_or_digit_gets_its_id_in_the_file_named_after_it(env, server, tmp_path, name):
    # CR1.3-39: the stable name (R4.3.1.2) and the one file of an app that updates itself (R4.10.2)
    # are the app's name without what isn't an ASCII letter or digit, which for such a name is
    # nothing: the file was `.AppImage`, hidden and nameless. The whole road of that name: the
    # fixed layout, AppKata's own update into versions with the stable link, and back.
    from appkata_core import sandbox
    app, gs = {**APP, "name": name}, sandbox.resolve_template("standard")
    home, cmd = tmp_path / "apps" / "app", tmp_path / "cmd"
    p = install.Portable(folder=str(tmp_path / "apps"), command_dir=str(cmd))
    a = _version(server, "appimage", "1.0")
    rec = install.install(env, {**app, "installVersion": "1.0", "autoUpdate": True}, a, "appimage", [a], portable=p)
    assert rec["id"] == "app" and os.listdir(home) == ["app.AppImage"]                    # it updates itself: one file
    assert rec["current"]["path"] == rec["exec"] == str(home / "app.AppImage") and open(rec["exec"], "rb").read() == b"1.0"
    install.rewrite_launcher(env, {**app, "autoUpdate": True, "sandbox": gs}, p)        # sandboxed, so AppKata updates it
    a = _version(server, "appimage", "2.0")
    rec = install.install(env, {**app, "installVersion": "2.0", "sandbox": gs}, a, "appimage", [a], portable=p)
    assert os.readlink(home / "app.AppImage") == "Tool-2.0-x86_64.AppImage" and str(home / "app.AppImage") in rec["links"]
    assert [os.path.basename(k["path"]) for k in rec["kept"]] == ["app-1.0.AppImage"]
    assert not [n for n in os.listdir(home) if n.startswith(".")]
    rec = install.rewrite_launcher(env, {**app, "autoUpdate": True, "sandbox": None}, p)       # Off: it updates itself again
    assert os.listdir(home) == ["app.AppImage"] and not os.path.islink(home / "app.AppImage")
    assert rec["current"]["path"] == rec["exec"] == str(home / "app.AppImage") and open(rec["exec"], "rb").read() == b"2.0"
    # a second such app has its own id, and its own name
    b = _appimage(server, "Other-1.0-x86_64.AppImage", b"other")
    other = install.install(env, {**app, "url": APP["url"] + "-other", "name": "別のアプリ"}, b, "appimage", [b], portable=p)
    assert other["id"] == "app-2" and other["exec"] == str(tmp_path / "apps" / "app-2" / "app-2.AppImage")
    assert os.readlink(other["exec"]) == "Other-1.0-x86_64.AppImage"
    assert install.uninstall(env, APP["url"]) == [] and install.uninstall(env, APP["url"] + "-other") == []
    assert not os.path.lexists(home) and not os.path.lexists(tmp_path / "apps" / "app-2")


def test_the_file_named_after_an_app_has_its_names_ascii_letters_and_digits_or_its_id():
    folder = os.path.join("apps", "app-2")
    for name, stem in (("LocalSend", "LocalSend"), ("Demo Tool", "DemoTool"), ("日本 App 2", "App2"), ("7-Zip", "7Zip"),
                       ("日本語アプリ", "app-2"), ("", "app-2"), ("..", "app-2"), ("/", "app-2")):
        assert install._file_stem({"name": name}, folder) == stem


# ---------------------------------------------------------------- a version named as what AppKata keeps in the app's folder (CR1.3-47)

@linux_only
@pytest.mark.parametrize("sandboxed", [False, True], ids=["unsandboxed", "sandboxed"])
@pytest.mark.parametrize("version", ["current", "run", "Current", "RUN"])
def test_a_release_whose_version_is_a_name_appkata_keeps_in_the_apps_folder_is_installed_beside_it(env, server, tmp_path, version, sandboxed):
    # CR1.3-47: an archive's version gets a folder named after it (R4.3.1), beside the `current`
    # link (R4.3.1.2) and a sandboxed app's launcher, `run` (R17.4). A release whose version was
    # the word "current" asked for its folder at the link's own place, and one named "run" at the
    # launcher's: neither could be installed, and "run" installed unsandboxed couldn't be
    # sandboxed after. It gets `_` before it, as a version of dots does (CR1.3-9), and is a
    # version like any other from there: kept, gone back to, removed.
    from appkata_core import sandbox
    app = {**APP, **({"sandbox": sandbox.resolve_template("standard")} if sandboxed else {})}
    home, cmd, folder = tmp_path / "apps" / "demo-tool", tmp_path / "cmd", "_" + version
    p = install.Portable(folder=str(tmp_path / "apps"), command_dir=str(cmd), keep=2)
    a = _version(server, "tarball", "1.0")
    install.install(env, {**app, "installVersion": "1.0"}, a, "tarball", [a], portable=p)
    a = _tarball(server, "tool-next.tar.gz", {"tool-next/tool": 0o755})
    rec = install.install(env, {**app, "installVersion": version}, a, "tarball", [a], portable=p)

    def whole(rec):
        assert (rec["current"]["version"], rec["current"]["path"]) == (version, str(home / folder))
        assert os.readlink(home / "current") == folder and _runs(home / "current" / "tool-next" / "tool") == "tool-next/tool"
        assert (rec.get("launcher") == str(home / "run")) is sandboxed and os.path.isfile(home / "run") is sandboxed
        if sandboxed:
            assert rec["exec"] == rec["launcher"] and install.launcher_is_current(rec, app, p)
        else:
            assert _runs(rec["exec"]) == "tool-next/tool" == _runs(cmd / "demo-tool")
        assert rec == json.loads(env.one("SELECT record FROM installs")["record"])
    whole(rec)
    assert [k["version"] for k in rec["kept"]] == ["1.0"]
    a = _version(server, "tarball", "2.0")                      # kept through the next update, and gone back to
    rec = install.install(env, {**app, "installVersion": "2.0"}, a, "tarball", [a], portable=p)
    assert [(k["version"], k["path"]) for k in rec["kept"]] == [(version, str(home / folder)), ("1.0", str(home / "1.0"))]
    assert os.readlink(home / "current") == "2.0" and os.path.isdir(home / folder)
    whole(install.switch_to(env, dict(app), version, p))
    if not sandboxed:                                           # and an app installed unsandboxed can be sandboxed after
        gs = sandbox.resolve_template("standard")
        rec = install.rewrite_launcher(env, {**APP, "sandbox": gs}, p)
        assert rec["launcher"] == str(home / "run") and os.path.isfile(home / "run") and os.path.isdir(home / folder)
    assert install.uninstall(env, APP["url"], remove_sandbox=True) == [] and not os.path.lexists(home)


@pytest.mark.parametrize("system", ["linux", "windows"])
def test_the_folder_a_version_is_unpacked_into(monkeypatch, system):
    # the version as a name (CR1.3-9), and never one AppKata keeps there itself, in any case
    # (Windows compares names without it, R15.16)
    monkeypatch.setattr(install, "OS", system)
    for version, folder in (("2.1", "2.1"), ("1.0-beta+3", "1.0-beta+3"), (".5", "_.5"), ("", "unknown"),
                            ("current", "_current"), ("run", "_run"), ("Current", "_Current"), ("RUN", "_RUN"),
                            ("currents", "currents"), ("current.1", "current.1"), ("rerun", "rerun"), ("app", "app"),
                            ("2.0.new", "2.0.new_"), ("2.0.old", "2.0.old_"), ("2.0.OLD", "2.0.OLD_"), ("run.new", "run.new_"),
                            ("new", "new"), ("2.0.newer", "2.0.newer"), ("2.0-old", "2.0-old"), ("current.old", "current.old_")):
        assert install._version_folder(version) == folder
        made = [folder + end for end in install._KEPT_ENDS]                 # what placing it makes beside it
        assert not [v for v in ("2.0", "2.0.new", "2.0.old", "run", "current", version) if install._version_folder(v) in made]
    kept = [n.lower() for n in install._KEPT_NAMES]
    assert all(install._version_folder(v).lower() not in kept for v in install._KEPT_NAMES + ("CURRENT", "Run", "current ", " run"))


# ---------------------------------------------------------------- a version named as a folder AppKata makes while placing one

@linux_only
@pytest.mark.parametrize("fails", [False, True], ids=["the install succeeds", "the install fails"])
@pytest.mark.parametrize("state", ["in use", "kept"])
@pytest.mark.parametrize("end", [".new", ".old", ".NEW"])
def test_installing_a_version_never_removes_one_named_as_its_staging_or_set_aside_folder(env, server, tmp_path, end, state, fails):
    # Found beside CR1.3-47, in the same family: a version's folder at a name AppKata uses itself.
    # Placing 2.0 unpacks it in `2.0.new`, after removing what is there, and sets what is at `2.0`
    # aside in `2.0.old`, after removing what is there: a version named 2.0.new or 2.0.old was
    # deleted by an install of 2.0, the one in use too, and whether or not the install succeeded
    # (R4.6 keeps the installed version until the new one is in place).
    p = install.Portable(folder=str(tmp_path / "apps"), command_dir=str(tmp_path / "cmd"), keep=3)
    home, odd = tmp_path / "apps" / "demo-tool", "2.0" + end
    for v in (odd, "3.0")[:2 if state == "kept" else 1]:
        a = _tarball(server, f"tool-{v}.tar.gz", {f"tool-{v}/tool": 0o755})
        was = install.install(env, {**APP, "installVersion": v}, a, "tarball", [a], portable=p)
    its = next(k["path"] for k in [was["current"]] + was["kept"] if k["version"] == odd)
    before = _left(tmp_path, env)
    if fails:
        (server[0] / "tool-2.0.tar.gz").write_bytes(b"not an archive")
        a = Asset("tool-2.0.tar.gz", server[1] + "/tool-2.0.tar.gz")
        with pytest.raises(tarfile.ReadError):
            install.install(env, {**APP, "installVersion": "2.0"}, a, "tarball", [a], portable=p)
        assert _changed(before, _left(tmp_path, env)) == {}
        assert _runs(was["exec"]) == f"tool-{was['current']['version']}/tool"
    else:
        a = _tarball(server, "tool-2.0.tar.gz", {"tool-2.0/tool": 0o755})
        rec = install.install(env, {**APP, "installVersion": "2.0"}, a, "tarball", [a], portable=p)
        assert _runs(rec["exec"]) == "tool-2.0/tool" and odd in [k["version"] for k in rec["kept"]]
        back = install.switch_to(env, dict(APP), odd, p)
        assert back["current"]["path"] == its and _runs(back["exec"]) == f"tool-{odd}/tool"
    assert os.path.isfile(os.path.join(its, f"tool-{odd}", "tool"))


# ---------------------------------------------------------------- a release's .deb or .rpm (R4.4, R16.8.5; CR1, #327)
# How it slipped past: no test installed a release's package file at all, so none saw which file the
# package manager is handed. It was the downloaded one, in a folder any program of the user's can
# write, read again as root after the dry run and the password prompt.
@pytest.fixture
def package_tools(tmp_path, monkeypatch):
    """Stand-ins for the package tools, first on the PATH: dpkg-deb and rpm name the package; apt-get
    and dnf plan an install of it and, told to install, keep the file they were handed and say where
    it was. The command that would run as root runs here as the test's user, with the folder only
    root can write under the test's own. No PackageKit of this machine's is ever asked."""
    from appkata_core import pkgbackend
    tools, out, staging = tmp_path / "tools", tmp_path / "installed", tmp_path / "root-only"
    for d in (tools, out, staging):
        d.mkdir()
    manager = f"""#!/bin/sh
for a in "$@"; do last=$a; done
case " $* " in
    *" -s "*) echo "Inst demo (1.0 local [all])"; exit 0 ;;
    *" --assumeno "*) printf 'Installing:\\n demo  noarch  1.0  @commandline  1 k\\nTransaction Summary\\n'; exit 0 ;;
    *" install "*) ;;
    *) exit 0 ;;                # a question about the system's packages: nothing to say
esac
cp "$last" {shlex.quote(str(out))}/file
echo "$last" > {shlex.quote(str(out))}/path
stat -c %a "$(dirname "$last")" "$last" > {shlex.quote(str(out))}/modes
ls "$(dirname "$last")" > {shlex.quote(str(out))}/beside
"""
    for name, text in (("apt-get", manager), ("dnf", manager), ("dpkg-deb", "#!/bin/sh\necho demo\n"), ("rpm", "#!/bin/sh\nprintf demo\n")):
        (tools / name).write_text(text)
        (tools / name).chmod(0o755)
    monkeypatch.setenv("PATH", f"{tools}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setattr(pkgbackend, "STAGING", str(staging), raising=False)
    monkeypatch.setattr(pkgbackend, "_priv", lambda cmd, env=None: cmd)
    monkeypatch.setattr(pkgbackend, "wait_for_lock", lambda *a, **k: None)
    monkeypatch.setattr(pkgbackend, "linux_family", lambda: "debian")
    monkeypatch.setattr(pkgbackend.PkTransport, "available", lambda self: False)
    return out, staging


def _package_file(server, kind, data=b"a package, as its release published it"):
    root, base = server
    name = "demo_1.0_all.deb" if kind == "deb" else "demo-1.0-1.noarch.rpm"
    (root / name).write_bytes(data)
    return Asset(name, f"{base}/{name}", len(data), "sha256:" + hashlib.sha256(data).hexdigest()), data


def _swap_after_the_dry_run(monkeypatch, swap):
    """The dry run is the first of what lies between AppKata's check and the package manager's read:
    then come a confirmation, perhaps, and the password prompt."""
    from appkata_core import pkgbackend
    real = pkgbackend.Cli.simulate

    def simulate(self, action, names):
        plan = real(self, action, names)
        swap(names[0])
        return plan
    monkeypatch.setattr(pkgbackend.Cli, "simulate", simulate)


@linux_only
@pytest.mark.parametrize("kind", ["deb", "rpm"])
def test_a_releases_package_is_installed_from_roots_own_copy_of_the_file_that_was_checked(env, server, package_tools, kind):
    out, staging = package_tools
    a, data = _package_file(server, kind)
    rec = install.install(env, {**APP, "installVersion": "1.0"}, a, kind, [a])
    handed = (out / "path").read_text().strip()
    assert os.path.dirname(os.path.dirname(handed)) == str(staging) and os.path.basename(handed) == a.name
    assert not handed.startswith(install.downloads_dir())                       # never the file a program of the user's can write
    assert (out / "file").read_bytes() == data and (out / "beside").read_text().split() == [a.name]
    assert (out / "modes").read_text().split() == ["755", "644"]                # read by all, written by its owner alone
    assert os.listdir(staging) == [] and _downloads() == []                     # the copy and the download are gone
    assert (rec["package"], rec["manager"], rec["verified"]) == ("demo", "apt" if kind == "deb" else "dnf", "checksum")
    assert rec["sha256"] == {"1.0": hashlib.sha256(data).hexdigest()}


def _other_bytes(path):
    with open(path, "wb") as f:
        f.write(b"a package of someone else's, with scripts that run as root")


def _same_size(path):
    size = os.path.getsize(path)
    with open(path, "r+b") as f:                # changed in place: the same file, the same size
        f.write(b"X" * size)


def _a_link_to_another(path):
    other = path + ".other"
    with open(other, "wb") as f:
        f.write(b"another file, behind the same name")
    os.remove(path)
    os.symlink(other, path)


@linux_only
@pytest.mark.parametrize("kind", ["deb", "rpm"])
@pytest.mark.parametrize("swap", [_other_bytes, _same_size, _a_link_to_another])
def test_a_package_swapped_after_its_check_is_refused_on_the_administrators_side(env, server, package_tools, monkeypatch, kind, swap):
    """The finding's case: the download is hashed and compared, and a program of the user's then
    puts another file at its path before the package manager opens it as root."""
    out, staging = package_tools
    a, _ = _package_file(server, kind)
    _swap_after_the_dry_run(monkeypatch, swap)
    with pytest.raises(install.InstallError, match="^the downloaded file changed after AppKata checked it; nothing was installed$"):
        install.install(env, {**APP, "installVersion": "1.0"}, a, kind, [a])
    assert os.listdir(out) == []                                                 # the package manager was handed nothing
    assert os.listdir(staging) == [] and not env.one("SELECT 1 FROM installs")
    assert [p for p in _downloads() if not p.endswith(".other")] == []          # nor is the swapped file kept to "resume"


@linux_only
def test_a_releases_package_never_goes_to_packagekit_which_takes_a_path_and_no_checksum(env, server, package_tools, monkeypatch):
    from appkata_core import pkgbackend
    out, _ = package_tools
    asked = []
    monkeypatch.setattr(pkgbackend.PkTransport, "available", lambda self: True)          # a desktop, where PackageKit runs
    monkeypatch.setattr(pkgbackend.PkTransport, "transaction", lambda self, method, *a, **k: asked.append(method) or [("finished", 1)])
    a, data = _package_file(server, "deb")
    install.install(env, {**APP, "installVersion": "1.0"}, a, "deb", [a])
    assert asked == [] and (out / "file").read_bytes() == data


@linux_only
def test_an_update_from_a_releases_package_file_upgrades_the_apps_own_package_without_asking(env, server, package_tools, monkeypatch):
    # A new finding beside #327: the dry run's review took the file's name for the package's
    from appkata_core import pkgbackend
    out, _ = package_tools
    monkeypatch.setattr(pkgbackend.Cli, "simulate", lambda self, action, names: pkgbackend.Plan(upgrade=["demo"]))     # "Inst demo [1.0] (2.0 …)"
    a, data = _package_file(server, "deb")
    install.install(env, {**APP, "installVersion": "2.0"}, a, "deb", [a])
    assert (out / "file").read_bytes() == data


@linux_only
def test_a_package_whose_plan_needs_the_users_ok_is_copied_nowhere_before_it_is_given(env, server, package_tools, monkeypatch):
    from appkata_core import pkgbackend
    out, staging = package_tools
    monkeypatch.setattr(pkgbackend.Cli, "simulate", lambda self, action, names: pkgbackend.Plan(install=["demo"], remove=["other"]))
    a, data = _package_file(server, "deb")
    with pytest.raises(pkgbackend.NeedsConfirmation):
        install.install(env, {**APP, "installVersion": "1.0"}, a, "deb", [a])
    assert os.listdir(out) == [] and os.listdir(staging) == [] and len(_downloads()) == 1       # kept for Install again
    install.install(env, {**APP, "installVersion": "1.0", "confirmed": True}, a, "deb", [a])
    assert (out / "file").read_bytes() == data and os.listdir(staging) == []
