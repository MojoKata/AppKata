"""Windows decisions (R15), tested on any OS: installer arguments and scopes, exit
codes, Uninstall entries, command links, PATH, folder permissions, names, and file order."""

import os

import pytest

from appkata_core import windows as w
from appkata_core.assets import candidates, choose, exe_type
from appkata_core.forges import Asset

from test_install_review import APP, env, server  # noqa: F401  (fixtures)


def test_safe_names():
    assert w.safe_name("con") == "_con" and w.safe_name("NUL.txt") == "_NUL.txt" and w.safe_name("com1") == "_com1"
    assert w.safe_name("console") == "console"
    assert w.safe_name("app.") == "app_" and w.safe_name("app ") == "app_"
    assert w.safe_name('a<b>:c"d|e?f*') == "a_b_c_d_e_f_"


def test_installer_arguments_by_scope():
    prog, args, elev = w.installer_command("msi", "", r"C:\d\x.msi", "me", r"C:\d\msi.log")
    assert prog == "msiexec.exe" and "/qn" in args and "MSIINSTALLPERUSER=1" in args and '/l*v "C:\\d\\msi.log"' in args and not elev
    assert w.installer_command("msi", "", "x.msi", "everyone")[1].endswith("ALLUSERS=1") and w.installer_command("msi", "", "x.msi", "everyone")[2]
    assert w.installer_command("exe", "inno", "s.exe", "me") == ("s.exe", "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /CURRENTUSER", False)
    assert w.installer_command("exe", "inno", "s.exe", "everyone") == ("s.exe", "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /ALLUSERS", True)
    assert w.installer_command("exe", "electron", "s.exe", "me") == ("s.exe", "/S /currentuser", False)
    assert w.installer_command("exe", "electron", "s.exe", "everyone") == ("s.exe", "/S /allusers", True)
    # the installer decides who it's for: no scope argument, no forced elevation
    assert w.installer_command("exe", "nsis", "s.exe", "everyone") == ("s.exe", "/S", False)
    assert w.installer_command("exe", "squirrel", "s.exe", "me") == ("s.exe", "--silent", False)
    # unrecognized: interactive
    assert w.installer_command("exe", "installer", "s.exe", "me") == ("s.exe", "", False)


def test_scopes_offered():
    assert w.scopes("zip") == ["me", "everyone"] and w.scopes("exe", "portable") == ["me", "everyone"]
    assert w.scopes("msi") == ["me", "everyone"] and w.scopes("exe", "inno") == ["me", "everyone"]
    assert w.scopes("exe", "electron") == ["me", "everyone"]
    assert w.scopes("msix") == ["me"] and w.scopes("exe", "squirrel") == ["me"]
    assert w.scopes("exe", "nsis") == [] and w.scopes("exe", "wix") == []


def test_exit_codes():
    assert [w.exit_meaning(c) for c in (0, 3010, 1641, 1602, 1223, 1618, 1603)] == \
        ["ok", "restart", "restart", "cancelled", "cancelled", "busy", "failed"]


def test_installers_known_by_their_release():
    assert w.exe_kind_from_release(["App-Setup-1.2.exe", "latest.yml", "App-Setup-1.2.exe.blockmap"]) == "electron"
    assert w.exe_kind_from_release(["Setup.exe", "RELEASES", "App-1.2-full.nupkg"]) == "squirrel"
    assert w.exe_kind_from_release(["App-1.2.exe"]) == ""
    nsis = b"xx NullsoftInst yy"
    assert exe_type("App-Setup-1.2.exe", nsis, ["App-Setup-1.2.exe", "latest.yml"]) == "electron"
    assert exe_type("App-Setup-1.2.exe", nsis, []) == "nsis"
    assert exe_type("App-Setup.exe", b"", ["App-Setup.exe", "RELEASES", "App-1-full.nupkg"]) == "squirrel"
    assert exe_type("App-1.2-portable.exe", b"", ["App-1.2-portable.exe", "latest.yml"]) == "portable"
    assert exe_type("x.exe", b"Inno Setup Setup Data", ["latest.yml"]) == "inno"
    assert exe_type("Git-2.56.0-64-bit.exe", "..InnoSetupLdrWindow..".encode("utf-16-le")) == "inno"      # Inno Setup 6.3+


def entry(hive, key, name, version="1.0", **kw):
    return {"hive": hive, "key": key, "wow32": False, "DisplayName": name, "DisplayVersion": version, **kw}


def test_finding_the_entry_an_installer_made():
    before = {"HKCU\\a": entry("HKCU", "a", "Other App")}
    new = entry("HKCU", "kpx", "KeePassXC", "2.7.9")
    after = {**before, "HKCU\\kpx": new}
    assert w.changed_entry(before, after, ["KeePassXC"]) == new
    # an update changes the version of an existing entry
    upd = entry("HKCU", "kpx", "KeePassXC", "2.7.10")
    assert w.changed_entry(after, {**before, "HKCU\\kpx": upd}, ["KeePassXC"]) == upd
    # several changes: the one named like the app; none matching and several: unknown
    other = entry("HKLM", "vc", "Microsoft Visual C++ 2015-2022 Redistributable")
    both = {**before, "HKCU\\kpx": new, "HKLM\\vc": other}
    assert w.changed_entry(before, both, ["KeePassXC"]) == new
    assert w.changed_entry(before, both, ["Something"]) is None
    assert w.changed_entry(before, before, ["KeePassXC"]) is None
    assert w.entry_id(entry("HKLM", "{X}", "n", wow32=True)) == "HKLM32\\{X}"


def test_uninstall_commands():
    assert w.split_command('"C:\\P F\\unins000.exe" /SILENT') == ("C:\\P F\\unins000.exe", "/SILENT")
    assert w.split_command("C:\\Apps\\x\\uninst.exe") == ("C:\\Apps\\x\\uninst.exe", "")
    quiet = entry("HKCU", "k", "A", QuietUninstallString='"C:\\a\\u.exe" /quiet')
    assert w.uninstall_command(quiet) == ("C:\\a\\u.exe", "/quiet", False)
    msi = entry("HKLM", "{12345678-1234-1234-1234-123456789ABC}", "A", UninstallString="MsiExec.exe /X{12345678-1234-1234-1234-123456789ABC}",
                WindowsInstaller=1)
    assert w.uninstall_command(msi) == ("msiexec.exe", "/x {12345678-1234-1234-1234-123456789ABC} /qn /norestart", True)
    inno = entry("HKCU", "x_is1", "A", UninstallString='"C:\\a\\unins000.exe"')
    assert w.uninstall_command(inno, "inno") == ("C:\\a\\unins000.exe", "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART", False)
    nsis = entry("HKLM", "A", "A", UninstallString='"C:\\Program Files\\A\\Uninstall A.exe" /currentuser')
    assert w.uninstall_command(nsis, "electron") == ("C:\\Program Files\\A\\Uninstall A.exe", "/currentuser /S", True)
    sq = entry("HKCU", "app", "A", UninstallString='"C:\\Users\\u\\AppData\\Local\\app\\Update.exe" --uninstall')
    assert w.uninstall_command(sq, "squirrel") == ("C:\\Users\\u\\AppData\\Local\\app\\Update.exe", "--uninstall -s", False)


def test_path_edits():
    assert w.path_with("C:\\a;C:\\b", "C:\\x") == "C:\\a;C:\\b;C:\\x"
    assert w.path_with("C:\\a;C:\\x", "C:\\x") == "C:\\a;C:\\x"
    assert w.path_with("", "C:\\x") == "C:\\x"
    assert w.path_without("C:\\a;C:\\x;C:\\b", "C:\\x") == "C:\\a;C:\\b"


def test_command_links(tmp_path):
    text = w.shim_text("C:\\Programs\\localsend\\current\\localsend.exe")
    assert text.startswith(w.SHIM_MARK) and '@"C:\\Programs\\localsend\\current\\localsend.exe" %*' in text
    p = w.write_shim(str(tmp_path), "localsend", "C:\\x.exe")
    assert os.path.basename(p) == "localsend.cmd"
    w.write_shim(str(tmp_path), "localsend", "C:\\y.exe")         # its own: replaced
    (tmp_path / "mine.cmd").write_text("@echo hello\r\n")
    with pytest.raises(FileExistsError):
        w.write_shim(str(tmp_path), "mine", "C:\\z.exe")             # someone else's: never
    w.remove_shim(p)
    assert not os.path.exists(p)


ME = "S-1-5-21-1-2-3-1001"


def rule(sid, rights, inh=3, prop=0, kind="Allow"):
    return {"sid": sid, "rights": rights, "type": kind, "inh": inh, "prop": prop}


FULL, RX = 0x1F01FF, 0x1200A9


def test_folder_permissions():
    app = {"owner": ME, "protected": True, "rules": [rule(ME, FULL), rule(w.ADMINS, FULL), rule(w.SYSTEM, FULL), rule(w.USERS, RX)]}
    assert w.acl_problem(app, ME, root=False) == ""
    assert "inherits" in w.acl_problem({**app, "protected": False}, ME, root=False)
    assert "another account" in w.acl_problem({**app, "owner": "S-1-5-21-9-9-9-1002"}, ME, root=False)
    loose = {**app, "rules": app["rules"] + [rule(w.AUTH_USERS, 0x1301BF)]}       # Modify
    assert w.AUTH_USERS in w.acl_problem(loose, ME, root=False)
    root = {"owner": w.ADMINS, "protected": True,
            "rules": [rule(w.ADMINS, FULL), rule(w.SYSTEM, FULL), rule(w.CREATOR_OWNER, 0x10000000, prop=2),
                      rule(w.USERS, RX), rule(w.USERS, w.APPEND_DATA, inh=0)]}
    assert w.acl_problem(root, ME, root=True) == ""
    # Windows' default for C:\: Authenticated Users may change everything created under it
    default = {**root, "protected": True, "rules": root["rules"] + [rule(w.AUTH_USERS, 0x1301BF, prop=2)]}
    assert w.acl_problem(default, ME, root=True) != ""
    # creating folders is fine on the Programs folder itself, not on an app's folder
    assert w.acl_problem({**app, "rules": app["rules"] + [rule(w.USERS, w.APPEND_DATA, inh=0)]}, ME, root=False) != ""


def test_mark_of_the_web_text():
    assert w.zone_identifier("https://x/y.exe") == "[ZoneTransfer]\r\nZoneId=3\r\nHostUrl=https://x/y.exe\r\n"


def test_signature_verdicts():
    assert w.signature_verdict("Valid") == "signed"
    assert w.signature_verdict("HashMismatch") == "bad"
    assert w.signature_verdict("NotSigned") == "" and w.signature_verdict("NotTrusted") == "" and w.signature_verdict("") == ""


def A(name, size=1):
    return Asset(name=name, url="https://h/" + name, size=size)


def test_windows_prefers_portable_files():
    rel = [A("App-1.2-x64.msi"), A("App-Setup-1.2.exe"), A("App-1.2-win-x64.zip"), A("App-1.2-portable.exe"), A("App-1.2.msix"),
           A("App-1.2-x86_64.AppImage"), A("App-1.2-linux.tar.gz")]
    kinds = [(c.kind, c.asset.name) for c in candidates(rel, "windows", "x86_64")]
    assert kinds == [("zip", "App-1.2-win-x64.zip"), ("exe", "App-1.2-portable.exe"), ("msi", "App-1.2-x64.msi"),
                     ("exe", "App-Setup-1.2.exe"), ("msix", "App-1.2.msix")]
    assert choose(rel, "windows", "x86_64").asset.name == "App-1.2-win-x64.zip"
    assert choose([A("App-Setup-1.2.exe"), A("App-1.2-x64.msi")], "windows", "x86_64").asset.name == "App-1.2-x64.msi"
    assert choose([A("App-Setup-1.2.exe"), A("App-1.2-portable.exe")], "windows", "x86_64").asset.name == "App-1.2-portable.exe"
    # Linux is unchanged
    assert choose(rel, "linux", "x86_64").asset.name == "App-1.2-x86_64.AppImage"


def test_long_paths():
    if os.name == "nt":
        assert w.long_path("C:\\x" + "\\x" * 130).startswith("\\\\?\\C:\\") and w.long_path("C:\\short") == "C:\\short"
    else:
        assert w.long_path("/x" * 200) == "/x" * 200


# ---------------------------------------------------------------- on Windows itself (the test VM)
on_windows = pytest.mark.skipif(os.name != "nt", reason="needs Windows")


@pytest.fixture
def winenv(tmp_path, monkeypatch, env):
    """Start menus inside the test folder, so nothing lands in the real ones."""
    monkeypatch.setenv("APPDATA", str(tmp_path / "roaming"))
    monkeypatch.setenv("ProgramData", str(tmp_path / "programdata"))
    return env


def _tool_zip(root, version: str) -> str:
    """A portable app: a copy of Windows' ping.exe, which can be left running."""
    import shutil
    import zipfile
    name = f"tool-{version}-win-x64.zip"
    src = os.path.join(os.environ.get("SystemRoot", "C:\\Windows"), "System32", "PING.EXE")
    with zipfile.ZipFile(root / name, "w") as z:
        z.write(src, f"tool-{version}/tool.exe")
    return name


@on_windows
def test_portable_zip_for_me(winenv, server, tmp_path):
    """Junction, Start-menu shortcut, .cmd command link on the PATH, files in use, uninstall (R15.5, R15.6, R15.9)."""
    import subprocess
    import time
    from appkata_core import install
    root, base = server
    bin_dir = str(tmp_path / "bin")
    p = install.Portable(folder=str(tmp_path / "apps"), app_menu=True, stable_name=True, command_dir=bin_dir, keep=1)
    app = {**APP, "name": "Tool"}
    try:
        n = _tool_zip(root, "1.0")
        a = Asset(n, f"{base}/{n}")
        rec = install.install(winenv, {**app, "installVersion": "1.0"}, a, "zip", [a], portable=p)
        cur = os.path.join(rec["target"], "current")
        assert w.is_junction(cur) and os.path.realpath(cur).endswith("1.0")
        assert rec["exec"] == os.path.join(cur, "tool-1.0", "tool.exe")
        lnk = os.path.join(w.start_menu("me"), "Tool.lnk")
        assert rec["shortcuts"][0]["path"] == lnk and os.path.exists(lnk)
        shim = os.path.join(bin_dir, "tool.cmd")
        assert rec["shims"] == [shim] and rec["exec"] in open(shim).read()
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
            assert bin_dir in winreg.QueryValueEx(k, "Path")[0]
        out = subprocess.run(["cmd", "/c", shim, "-n", "1", "127.0.0.1"], capture_output=True)
        assert out.returncode == 0

        # running from its folder: no update until it's closed
        proc = subprocess.Popen([rec["exec"], "-n", "30", "127.0.0.1"], stdout=subprocess.DEVNULL)
        time.sleep(1)
        assert any(x.lower().endswith("tool.exe") for x in w.processes_in(rec["target"]))
        n2 = _tool_zip(root, "1.1")
        a2 = Asset(n2, f"{base}/{n2}")
        with pytest.raises(install.InUse):
            install.install(winenv, {**app, "installVersion": "1.1"}, a2, "zip", [a2], portable=p)
        proc.kill(); proc.wait(); time.sleep(0.5)
        rec = install.install(winenv, {**app, "installVersion": "1.1"}, a2, "zip", [a2], portable=p)
        assert os.path.realpath(cur).endswith("1.1") and os.path.isdir(os.path.join(rec["target"], "1.0"))   # kept
        assert os.path.exists(lnk)      # the shortcut points through `current`: unchanged

        install.uninstall(winenv, APP["url"])
        assert not os.path.exists(rec["target"]) and not os.path.exists(lnk) and not os.path.exists(shim)
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
            assert bin_dir not in winreg.QueryValueEx(k, "Path")[0]
    finally:
        w.remove_from_user_path(bin_dir)


@on_windows
def test_portable_zip_for_everyone(winenv, server, tmp_path):
    """The everyone folder and the app's folder are locked down; the all-users shortcut (R15.4.3, R15.5)."""
    from appkata_core import install
    root, base = server
    p = install.Portable(folder_everyone=str(tmp_path / "Programs"), scope="everyone", app_menu=True, command_dir="")
    n = _tool_zip(root, "2.0")
    a = Asset(n, f"{base}/{n}")
    rec = install.install(winenv, {**APP, "name": "Tool", "installVersion": "2.0"}, a, "zip", [a], portable=p)
    assert rec["scope"] == "everyone" and rec["target"].startswith(str(tmp_path / "Programs"))
    for folder, is_root in ((str(tmp_path / "Programs"), True), (rec["target"], False)):
        acl, me = w.read_acl(folder)
        assert w.acl_problem(acl, me, is_root) == "", folder
    lnk = os.path.join(w.start_menu("everyone"), "Tool.lnk")
    assert os.path.exists(lnk) and rec["shortcuts"][0]["elevated"]
    # someone loosens the app folder: an update refuses it… unless it's ours, which AppKata repairs
    w.run_hidden(["icacls", rec["target"], "/grant", f"*{w.AUTH_USERS}:(OI)(CI)M"])
    acl, me = w.read_acl(rec["target"])
    assert w.acl_problem(acl, me, False)
    w.secure_folder(rec["target"], root=False)
    acl, me = w.read_acl(rec["target"])
    assert w.acl_problem(acl, me, False) == ""
    install.uninstall(winenv, APP["url"])
    assert not os.path.exists(lnk) and not os.path.exists(rec["target"])


@on_windows
def test_registering_with_windows():
    from appkata_core import desktop
    before_run, before_scheme = w.autostart_get(), w.scheme_get()
    try:
        desktop.set_autostart(True)
        assert desktop.autostart_on() and "--tray" in w.autostart_get()
        desktop.set_autostart(False)
        assert not desktop.autostart_on()
        assert desktop.register_scheme(True) and desktop.scheme_registered() and w.scheme_get().endswith('"%1"')
        desktop.register_scheme(False)
        assert not desktop.scheme_registered()
    finally:
        w.autostart_set(before_run)
        if before_scheme:
            w.scheme_set(before_scheme)


@on_windows
def test_signatures_and_mark_of_the_web(tmp_path):
    notepad = os.path.join(os.environ.get("SystemRoot", "C:\\Windows"), "System32", "notepad.exe")
    status, _ = w.authenticode(notepad)
    assert w.signature_verdict(status) == "signed"
    f = tmp_path / "unsigned.exe"
    f.write_bytes(b"MZ not really a program")
    assert w.signature_verdict(w.authenticode(str(f))[0]) == ""
    w.mark_of_web(str(f), "https://example.org/unsigned.exe")
    assert "ZoneId=3" in open(str(f) + ":Zone.Identifier").read()


@on_windows
def test_uninstall_entries_are_read():
    entries = w.uninstall_entries()
    assert entries and all({"hive", "key"} <= set(e) for e in entries.values())


# ---------------------------------------------------------------- a portable install that fails part-way (CR1.3-15)
@pytest.fixture
def windows_road(winenv, monkeypatch):
    """install.py's Windows road on any OS, with a Start-menu shortcut that is a plain file and
    nothing written to the user's PATH. Off Windows a junction is a symbolic link. Returns the
    calls that made a shortcut, and `refuse`: what the next one fails with."""
    from appkata_core import install
    road = {"made": [], "refuse": None}

    def make_shortcut(lnk, target, elevate=False, description=""):
        if road["refuse"]:
            error, road["refuse"] = road["refuse"], None
            raise error
        os.makedirs(os.path.dirname(lnk), exist_ok=True)
        with open(lnk, "w") as f:
            f.write(target)
        road["made"].append(lnk)

    def make_junction(target, link):
        if os.path.islink(link):
            os.remove(link)
        os.symlink(target, link)

    monkeypatch.setattr(w, "make_shortcut", make_shortcut)
    monkeypatch.setattr(w, "add_to_user_path", lambda folder: None)
    monkeypatch.setattr(w, "remove_from_user_path", lambda folder: None)
    if os.name != "nt":
        monkeypatch.setattr(install, "OS", "windows")
        monkeypatch.setattr(w, "make_junction", make_junction)
    return road


def _plain_zip(root, version: str) -> str:
    import zipfile
    name = f"tool-{version}-win-x64.zip"
    with zipfile.ZipFile(root / name, "w") as z:
        z.writestr(f"tool-{version}/tool.exe", "MZ, and not a program")
    return name


@pytest.mark.parametrize("update", [False, True], ids=["a first install", "an update"])
@pytest.mark.parametrize("refused", ["the shortcut", "the command link", "the command link, after the check"])
def test_a_refused_portable_install_leaves_everything_as_it_was(windows_road, env, server, tmp_path, monkeypatch, refused, update):
    # CR1.3-15, Windows' side: a Start-menu shortcut Windows wouldn't make, or someone else's
    # <app>.cmd where the command link goes, stopped the install after the version's folder and the
    # `current` junction were made, and the record is stored last: a first install left them with no
    # record, an update left `current` on the new version under the old version's record. The .cmd
    # is now looked at before anything is placed; a refusal that only shows later is taken back.
    from appkata_core import install
    from test_install_review import _changed, _left
    root, base = server
    apps, theirs = tmp_path / "apps", tmp_path / "their-bin"
    theirs.mkdir()
    (theirs / "tool.cmd").write_bytes(b"@echo mine\r\n")
    app = {**APP, "name": "Tool"}
    # without the stable name each version's program has its own path, so an update makes the shortcut again
    stable = refused != "the shortcut"
    good = install.Portable(folder=str(apps), stable_name=stable, command_dir=str(tmp_path / "bin"), keep=2)
    if update:
        a1 = Asset(_plain_zip(root, "1.0"), f"{base}/tool-1.0-win-x64.zip")
        rec = install.install(env, {**app, "installVersion": "1.0"}, a1, "zip", [a1], portable=good)
        assert len(windows_road["made"]) == 1 and rec["shims"] == [str(tmp_path / "bin" / "tool.cmd")]
        assert os.path.realpath(apps / "tool" / "current").endswith("1.0") is stable
    a2 = Asset(_plain_zip(root, "2.0"), f"{base}/tool-2.0-win-x64.zip")
    before = _left(tmp_path, env)
    p = good
    if refused == "the shortcut":
        windows_road["refuse"], match = OSError("Access is denied"), "couldn't add the Start-menu shortcut: Access is denied"
    elif refused == "the command link":
        p, match = install.Portable(folder=str(apps), command_dir=str(theirs), keep=2), "isn't a command link AppKata made"
    else:
        real, failed, match = w.write_shim, [], "appeared since"

        def write_shim(folder, name, program):
            if not failed:
                failed.append(1)
                raise FileExistsError("appeared since")
            return real(folder, name, program)
        monkeypatch.setattr(w, "write_shim", write_shim)
    with pytest.raises(install.InstallError, match=match):
        install.install(env, {**app, "installVersion": "2.0"}, a2, "zip", [a2], portable=p)
    assert _changed(before, _left(tmp_path, env)) == {}
    assert (theirs / "tool.cmd").read_bytes() == b"@echo mine\r\n" and os.path.lexists(apps / "tool") is update
    if update:                                                  # and the app is whole: it updates, and uninstalls
        assert os.path.realpath(apps / "tool" / "current").endswith("1.0") is stable
        a3 = Asset(_plain_zip(root, "3.0"), f"{base}/tool-3.0-win-x64.zip")
        rec = install.install(env, {**app, "installVersion": "3.0"}, a3, "zip", [a3], portable=good)
        assert [k["version"] for k in rec["kept"]] == ["1.0"] and os.path.isdir(apps / "tool" / "3.0")
        install.uninstall(env, APP["url"])
        assert not os.path.lexists(apps / "tool") and not os.path.exists(tmp_path / "bin" / "tool.cmd")
        assert not any(os.path.exists(lnk) for lnk in windows_road["made"])


@pytest.mark.parametrize("name,exe", [("日本語アプリ", "app.exe"), ("Приложение 2", "2.exe"), ("Demo Tool", "DemoTool.exe")])
def test_a_portable_program_is_named_after_its_app_or_by_the_apps_id(windows_road, env, server, tmp_path, monkeypatch, name, exe):
    # CR1.3-39, Windows' side: a portable .exe is kept under the app's name without what isn't an
    # ASCII letter or digit, and an app whose name has none had a program named just `.exe`.
    from appkata_core import install
    monkeypatch.setattr(w, "authenticode", lambda path: ("NotSigned", ""))
    root, base = server
    (root / "tool-1.0-portable.exe").write_bytes(b"MZ, and not a program")
    a = Asset("tool-1.0-portable.exe", f"{base}/tool-1.0-portable.exe")
    p = install.Portable(folder=str(tmp_path / "apps"), command_dir=str(tmp_path / "bin"))
    rec = install.install(env, {**APP, "name": name, "exeKind": "portable", "installVersion": "1.0"}, a, "exe", [a], portable=p)
    assert rec["current"]["exec"] == os.path.join("1.0", exe) and os.listdir(rec["current"]["path"]) == [exe]
    assert os.path.basename(rec["exec"]) == exe and os.path.exists(rec["exec"])
    install.uninstall(env, APP["url"])
    assert not os.path.lexists(rec["target"])


@pytest.mark.parametrize("name,exe", [("Con", "_Con.exe"), ("AUX", "_AUX.exe"), ("Com 1", "_Com1.exe"), ("nul!", "_nul.exe"),
                                      ("Console", "Console.exe"), ("Com 10", "Com10.exe")])
def test_a_portable_program_of_an_app_named_as_a_device_has_a_name_windows_accepts(windows_road, env, server, tmp_path, monkeypatch, name, exe):
    # R15.16: "App folder and file names avoid the names Windows reserves ... by adding `_`". The
    # app's folder and its Start-menu shortcut did; its portable program was the name's letters and
    # digits as they came, so an app named Con had `Con.exe`, which Windows reads as the console
    # whatever the extension. Found beside CR1.3-39, in the same expression.
    from appkata_core import install
    monkeypatch.setattr(w, "authenticode", lambda path: ("NotSigned", ""))
    root, base = server
    (root / "tool-1.0-portable.exe").write_bytes(b"MZ, and not a program")
    a = Asset("tool-1.0-portable.exe", f"{base}/tool-1.0-portable.exe")
    p = install.Portable(folder=str(tmp_path / "apps"), command_dir=str(tmp_path / "bin"))
    rec = install.install(env, {**APP, "name": name, "exeKind": "portable", "installVersion": "1.0"}, a, "exe", [a], portable=p)
    assert os.listdir(rec["current"]["path"]) == [exe] and not w.RESERVED.match(exe) and w.safe_name(exe) == exe
    assert os.path.basename(rec["exec"]) == exe and open(rec["exec"], "rb").read() == b"MZ, and not a program"
    install.uninstall(env, APP["url"])
    assert not os.path.lexists(rec["target"])


# ---------------------------------------------------------------- the Visual C++ run-time (R15.18)
def make_pe(path, dlls, delay=(), pe32plus=True):
    """A minimal Windows program whose import tables name `dlls` (and delay-loaded `delay`)."""
    import struct
    rva, off = 0x1000, 0x200
    n_desc, n_delay = len(dlls) + 1, (len(delay) + 1) if delay else 0
    names, name_rva = b"", []
    base = rva + 20 * n_desc + 32 * n_delay
    for d in list(dlls) + list(delay):
        name_rva.append(base + len(names))
        names += d.encode() + b"\0"
    data = b"".join(struct.pack("<IIIII", 0, 0, 0, r, 0) for r in name_rva[:len(dlls)]) + b"\0" * 20
    if delay:
        data += b"".join(struct.pack("<IIIIIIII", 1, r, 0, 0, 0, 0, 0, 0) for r in name_rva[len(dlls):]) + b"\0" * 32
    data += names
    opt_size = 240 if pe32plus else 224
    dd = 112 if pe32plus else 96
    opt = bytearray(opt_size)
    struct.pack_into("<H", opt, 0, 0x20B if pe32plus else 0x10B)
    struct.pack_into("<I", opt, dd - 4, 16)
    struct.pack_into("<II", opt, dd + 8, rva, 20 * n_desc)
    if delay:
        struct.pack_into("<II", opt, dd + 13 * 8, rva + 20 * n_desc, 32 * n_delay)
    coff = struct.pack("<HHIIIHH", 0x8664, 1, 0, 0, 0, opt_size, 0x22)
    sect = struct.pack("<8sIIIIIIHHI", b".idata", len(data), rva, len(data), off, 0, 0, 0, 0, 0x40000040)
    head = b"MZ" + b"\0" * 0x3A + struct.pack("<I", 0x40) + b"PE\0\0" + coff + bytes(opt) + sect
    with open(path, "wb") as f:
        f.write(head + b"\0" * (off - len(head)) + data)


def test_reading_a_programs_imports(tmp_path):
    p = tmp_path / "tool.exe"
    make_pe(p, ["KERNEL32.dll", "VCRUNTIME140.dll", "api-ms-win-crt-runtime-l1-1-0.dll"], delay=["MSVCP140.dll"])
    assert w.pe_imports(str(p)) == ["KERNEL32.dll", "VCRUNTIME140.dll", "api-ms-win-crt-runtime-l1-1-0.dll", "MSVCP140.dll"]
    make_pe(tmp_path / "old.exe", ["USER32.dll"], pe32plus=False)
    assert w.pe_imports(str(tmp_path / "old.exe")) == ["USER32.dll"]
    (tmp_path / "notes.exe").write_bytes(b"not a program")
    assert w.pe_imports(str(tmp_path / "notes.exe")) == [] and w.pe_imports(str(tmp_path / "missing.exe")) == []


def test_which_apps_need_the_runtime(tmp_path):
    needs, carries, static = tmp_path / "needs", tmp_path / "carries", tmp_path / "static"
    for d in (needs, carries, static):
        (d / "bin").mkdir(parents=True)
    make_pe(needs / "bin" / "hyperfine.exe", ["KERNEL32.dll", "VCRUNTIME140.dll"])
    make_pe(carries / "bin" / "app.exe", ["KERNEL32.dll", "MSVCP140.dll", "VCRUNTIME140_1.dll"])
    for dll in ("msvcp140.dll", "vcruntime140_1.dll"):         # the app brings its own copies
        (carries / dll).write_bytes(b"MZ")
    make_pe(static / "bin" / "rg.exe", ["KERNEL32.dll", "ntdll.dll"])
    assert w.needs_msvcrt(str(needs)) and not w.needs_msvcrt(str(carries)) and not w.needs_msvcrt(str(static))
    assert w.MSVC_DLL.match("vcruntime140_1.dll") and w.MSVC_DLL.match("MSVCP140_ATOMIC_WAIT.dll") and not w.MSVC_DLL.match("msvcrt.dll")
    assert w.exit_meaning(1638) == "ok"          # vc_redist: a newer one is already installed


@on_windows
def test_runtime_on_real_programs(tmp_path):
    import shutil
    import sys
    home = os.path.dirname(sys.executable)          # Python for Windows imports the run-time, and carries it
    dll = next(f for f in os.listdir(home) if f.lower().startswith("python3") and f.lower().endswith(".dll") and f.lower() != "python3.dll")
    assert any(w.MSVC_DLL.match(d) for d in w.pe_imports(os.path.join(home, dll)))
    assert not w.needs_msvcrt(home)
    shutil.copy(os.path.join(home, dll), tmp_path / dll)  # the same library without the run-time beside it
    assert w.needs_msvcrt(str(tmp_path))
    w.msvcrt_installed()                              # reads the registry without failing


# ---------------------------------------------------------------- an installer run with administrator rights (R15.7.5; CR1, #327)
# How it slipped past: the installer tests stopped at the command's words (test_installer_arguments_by_scope),
# and nothing asked which file Windows is handed with administrator rights. It was the download itself,
# in a folder any program of the user's can write, started after the check and the UAC prompt.
def _elevated_values(args: str) -> dict:
    """What the script Windows is asked to elevate holds: its values, read back from its own text."""
    import base64
    import re
    script = base64.b64decode(args.split("-EncodedCommand ")[1]).decode("utf-16-le")
    said = {name: base64.b64decode(value).decode("utf-8") for name, value in re.findall(r"\$(\w+) = V '([A-Za-z0-9+/=]*)'", script)}
    return {**said, "msi": re.search(r"\$msi = \$(true|false)", script).group(1) == "true", "script": script}


@pytest.fixture
def installer_road(windows_road, monkeypatch):
    """The installers' road on any OS: no signature, no Uninstall entries, and Windows' own start of a
    program replaced by `started`, the calls, each answered with `road["code"]` or, for the script
    that runs with administrator rights, by what that script would find: the file's own SHA-256
    compared with the one it was given."""
    import hashlib
    road = {"started": [], "code": 0, "swap": None}

    def shell_execute(program, args="", elevate=False, wait=True, cwd="", show=1, timeout=3600):
        road["started"].append({"program": program, "args": args, "elevate": elevate, "show": show})
        if not elevate:
            return road["code"]
        v = _elevated_values(args)
        if road["swap"]:
            road["swap"](v["src"])
        with open(v["src"], "rb") as f:
            return road["code"] if hashlib.sha256(f.read()).hexdigest() == v["want"] else w.CHANGED
    monkeypatch.setattr(w, "shell_execute", shell_execute)
    monkeypatch.setattr(w, "authenticode", lambda path: ("NotSigned", ""))
    monkeypatch.setattr(w, "uninstall_entries", lambda: {})
    monkeypatch.setattr(w, "processes_in", lambda folder: [])
    return road


ODD = "Demo's $(tool) `setup` ‘1.0’"            # a name PowerShell would read as more than text, were it pasted in


@pytest.mark.parametrize("kind, exe_kind, args", [
    ("msi", "", '/qn /norestart /l*v "{log}" ALLUSERS=1'),
    ("exe", "inno", "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /ALLUSERS"),
    ("exe", "electron", "/S /allusers"),
])
def test_an_installer_for_everyone_is_started_by_the_script_that_copies_and_checks_it(installer_road, env, server, tmp_path, kind, exe_kind, args):
    import hashlib
    import urllib.parse
    from appkata_core import install
    root, base = server
    name, data = f"{ODD}.{kind}", b"MZ, an installer as its release published it"
    (root / name).write_bytes(data)
    a = Asset(name, f"{base}/{urllib.parse.quote(name)}", len(data))
    rec = install.install(env, {**APP, "installVersion": "1.0", "exeKind": exe_kind}, a, kind, [a],
                          portable=install.Portable(folder_everyone=str(tmp_path / "Programs"), scope="everyone"))
    (started,) = installer_road["started"]                    # one start, and it is not of the downloaded file
    assert started["elevate"] and started["show"] == 0
    assert started["program"].replace("\\", "/").endswith("/System32/WindowsPowerShell/v1.0/powershell.exe")
    assert started["args"].startswith("-NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -EncodedCommand ")
    v = _elevated_values(started["args"])
    folder = os.path.join(install.downloads_dir(), rec["id"])
    assert v["src"] == os.path.join(folder, name) and v["name"] == name and v["want"] == hashlib.sha256(data).hexdigest()
    assert v["argl"] == args.format(log=os.path.join(folder, "msi.log")) and v["msi"] is (kind == "msi")
    assert not any(odd in v["script"] for odd in ("Demo", "$(tool)", "‘", folder))         # its values are base64, not pasted text
    assert rec["sha256"] == {"1.0": v["want"]} and rec["installer"] == (exe_kind or "msi")


@pytest.mark.parametrize("kind, exe_kind, scope, program, args", [
    ("msi", "", "me", "msiexec.exe", '/i "{file}" /qn /norestart /l*v "{log}" ALLUSERS=2 MSIINSTALLPERUSER=1'),
    ("exe", "inno", "me", "{file}", "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /CURRENTUSER"),
    ("exe", "nsis", "everyone", "{file}", "/S"),                 # it decides for itself, and asks Windows itself if it needs to
    ("exe", "installer", "me", "{file}", ""),
])
def test_an_installer_appkata_doesnt_elevate_is_started_as_before(installer_road, env, server, tmp_path, kind, exe_kind, scope, program, args):
    from appkata_core import install
    root, base = server
    name = f"setup.{kind}"
    (root / name).write_bytes(b"MZ")
    a = Asset(name, f"{base}/{name}", 2)
    rec = install.install(env, {**APP, "installVersion": "1.0", "exeKind": exe_kind}, a, kind, [a],
                          portable=install.Portable(folder_everyone=str(tmp_path / "Programs"), scope=scope))
    folder = os.path.join(install.downloads_dir(), rec["id"])
    said = {"file": os.path.join(folder, name), "log": os.path.join(folder, "msi.log")}
    assert installer_road["started"] == [{"program": program.format(**said), "args": args.format(**said), "elevate": False, "show": 1}]


def _replaced(path):
    with open(path, "wb") as f:
        f.write(b"MZ, another installer")


@pytest.mark.parametrize("swap, code, error", [
    (_replaced, 0, "the downloaded file changed after AppKata checked it; nothing was installed"),
    (None, "NOT_STARTED", "Windows couldn't make the administrators' copy of the installer or start it; nothing was installed"),
    (None, 1223, ""),                                           # declined at the UAC prompt: cancelled (R15.7.3)
    (None, 1603, "the installer exited with code 1603"),
], ids=["swapped after the check", "no copy", "declined", "the installer failed"])
def test_an_installer_that_isnt_the_file_that_was_checked_is_not_started(installer_road, env, server, tmp_path, swap, code, error):
    from appkata_core import install
    root, base = server
    (root / "setup.msi").write_bytes(b"MZ, an installer as its release published it")
    a = Asset("setup.msi", f"{base}/setup.msi", 44)
    installer_road.update(swap=swap, code=getattr(w, code) if isinstance(code, str) else code)
    with pytest.raises(install.Cancelled if not error else install.InstallError) as e:
        install.install(env, {**APP, "installVersion": "1.0"}, a, "msi", [a],
                        portable=install.Portable(folder_everyone=str(tmp_path / "Programs"), scope="everyone"))
    assert not error or str(e.value) == error
    assert len(installer_road["started"]) == 1 and not env.one("SELECT 1 FROM installs")


def test_the_visual_cpp_runtime_is_started_by_the_same_script_held_to_the_file_whose_signature_was_read(installer_road, env, monkeypatch):
    import hashlib
    from appkata_core import install
    data = b"MZ, vc_redist as Microsoft published it"

    def download(url, dest, *a, **k):
        with open(dest, "wb") as f:
            f.write(data)
        return hashlib.sha256(data).hexdigest()
    monkeypatch.setattr(install, "download", download)
    monkeypatch.setattr(w, "authenticode", lambda path: ("Valid", "Microsoft Corporation"))
    monkeypatch.setattr(w, "msvcrt_installed", lambda: "14.40")
    assert install.install_msvcrt() == "ok"
    (started,) = installer_road["started"]
    v = _elevated_values(started["args"])
    assert started["elevate"] and started["program"].replace("\\", "/").endswith("/powershell.exe")
    assert (v["name"], v["argl"], v["msi"], v["want"]) == ("vc_redist.x64.exe", "/install /quiet /norestart", False, hashlib.sha256(data).hexdigest())
    installer_road["started"].clear()
    installer_road["swap"] = _replaced                           # swapped between the signature check and the start
    with pytest.raises(install.InstallError, match="changed after AppKata checked it"):
        install.install_msvcrt()


# How it slipped past (found answering pass 3's P3-4): every test of an install that fails left a
# file at the download's path that could be removed, so nothing asked what the user is told when it
# can't be. The removal runs as the install's own error is on its way out, and its failure took
# that error's place: "[Errno 21] Is a directory", or Windows' own words for a file another program
# holds, where the install's reason should be. The class is a cleanup step that can fail in an
# install's last lines; the two that remove a download are held here.
@pytest.mark.parametrize("in_the_way", ["a folder at its path", "a file that can't be removed"])
def test_a_download_that_cant_be_removed_takes_nothing_from_what_the_install_says(installer_road, env, server, tmp_path, monkeypatch, caplog, in_the_way):
    import hashlib
    import logging
    from appkata_core import install
    caplog.set_level(logging.WARNING, logger="appkata.install")
    remove = os.remove

    def block(path):
        """After this, the download at `path` can't be removed: as a folder, or as Windows refuses a file that is held."""
        if in_the_way == "a folder at its path":
            remove(path)
            os.mkdir(path)
        else:
            def held(p, *a, **k):
                if p == path:
                    raise PermissionError(13, "held by another program", p)
                remove(p, *a, **k)
            monkeypatch.setattr(os, "remove", held)

    # an installer that fails: the install says why, whatever becomes of the file it ran
    root, base = server
    (root / "setup.exe").write_bytes(b"MZ")
    a = Asset("setup.exe", f"{base}/setup.exe", 2)
    start = w.shell_execute
    monkeypatch.setattr(w, "shell_execute", lambda program, args="", **how: (start(program, args, **how), block(program))[0])
    installer_road["code"] = 1603
    with pytest.raises(install.InstallError, match="^the installer exited with code 1603$"):
        install.install(env, {**APP, "installVersion": "1.0", "exeKind": "inno"}, a, "exe", [a],
                        portable=install.Portable(folder_everyone=str(tmp_path / "Programs"), scope="me"))
    file = os.path.join(install.downloads_dir(), "demo-tool", "setup.exe")
    assert not env.one("SELECT 1 FROM installs") and f"couldn't remove the download {file}: " in caplog.text
    monkeypatch.setattr(os, "remove", remove)
    monkeypatch.setattr(w, "shell_execute", start)

    # the Visual C++ run-time: installed is installed, and a refusal is said as it is
    data = b"MZ, vc_redist as Microsoft published it"
    file = os.path.join(install.downloads_dir(), "vc_redist.x64.exe")

    def download(url, dest, *a, **k):
        if os.path.isdir(dest):
            os.rmdir(dest)
        with open(dest, "wb") as f:
            f.write(data)
        block(dest)
        return hashlib.sha256(data).hexdigest()
    monkeypatch.setattr(install, "download", download)
    monkeypatch.setattr(w, "authenticode", lambda path: ("Valid", "Microsoft Corporation"))
    monkeypatch.setattr(w, "msvcrt_installed", lambda: "14.40")
    monkeypatch.setattr(w, "run_elevated", lambda file, sha256, args="", **how: installer_road["code"])
    for code, said in ((0, "ok"), (w.CHANGED, "the downloaded file changed after AppKata checked it; nothing was installed")):
        installer_road["code"] = code
        caplog.clear()
        if code:
            with pytest.raises(install.InstallError) as e:
                install.install_msvcrt()
            assert str(e.value) == said
        else:
            assert install.install_msvcrt() == said
        assert f"couldn't remove the download {file}: " in caplog.text
        monkeypatch.setattr(os, "remove", remove)


def test_the_administrators_side_starts_only_the_file_that_was_checked_from_a_folder_of_its_own(tmp_path):
    """The script that runs with administrator rights. On any system, what its text must hold to,
    since it runs with nothing to rely on but Windows' own files. On Windows itself (the test VM's
    session has administrator rights, so UAC doesn't ask) it is run: a copy of cmd.exe is the
    installer, which writes down where it runs from and who may change that folder."""
    import hashlib
    import re
    import shutil
    script = w.elevated_script("C:\\d\\setup.exe", "ab" * 32, 44, "/S", False)
    assert not re.search(r"\b[A-Z][a-z]+-[A-Z][A-Za-z]+\b", script)              # no cmdlet: one could come from the user's own modules
    assert "$env:" not in script and "%" not in script                         # nor a folder the user's environment names
    assert "'O:BAG:BAD:PAI(A;OICI;FA;;;BA)(A;OICI;FA;;;SY)'" in script          # the folder: Administrators' and SYSTEM's, nothing inherited
    steps = [script.index(step) for step in ("::CreateDirectory($dir, $only)", "::CreateFileW($src,", "$out.Write($buf, 0, $n)", "ComputeHash($in)",
                                             "if ($got -ne $want)", "[Diagnostics.Process]::Start($start)", "[IO.Directory]::Delete($dir, $true)")]
    assert steps == sorted(steps)                                              # made, copied, hashed, compared, then started; removed after
    assert script.count("$copy") >= 4 and "$start.FileName = $src" not in script and "+ $src" not in script     # only the copy is ever started
    if os.name != "nt":
        return
    setup = tmp_path / "setup one.exe"
    shutil.copy(os.path.join(os.environ.get("SystemRoot", "C:\\Windows"), "System32", "cmd.exe"), setup)
    sha = hashlib.sha256(setup.read_bytes()).hexdigest()
    where, acl = tmp_path / "where.txt", tmp_path / "acl.txt"
    assert w.run_elevated(str(setup), sha, f'/d /c "cd>{where}&icacls .>{acl}"') == 0
    ran_in = where.read_text().strip()
    temp = os.path.join(os.environ.get("SystemRoot", "C:\\Windows"), "Temp")
    assert os.path.dirname(ran_in).lower() == temp.lower() and os.path.basename(ran_in).startswith("AppKata-")
    assert not os.path.exists(ran_in)                             # the copy's folder is gone when the installer is done
    grants = [line for line in acl.read_text(errors="replace").splitlines() if ":(" in line]
    assert len(grants) == 2 and all("(OI)(CI)(F)" in g for g in grants), grants          # Administrators and SYSTEM, no one else
    assert sorted(g.split(":(")[0].split("\\")[-1] for g in grants) == ["Administrators", "SYSTEM"], grants
    # the file changed after its check (a byte added): not started
    with open(setup, "ab") as f:
        f.write(b"\0")
    again = tmp_path / "again.txt"
    assert w.run_elevated(str(setup), sha, f'/d /c "cd>{again}"') == w.CHANGED and not again.exists()
    assert w.run_elevated(str(tmp_path / "gone.exe"), sha, "") == w.NOT_STARTED
    # an installer's own exit code comes back
    sha = hashlib.sha256(setup.read_bytes()).hexdigest()
    assert w.run_elevated(str(setup), sha, "/d /c exit 3010") == 3010


# How it slipped past (pass 2 of the unit's own review): the test above asks that a copy is made
# before it is hashed, and never how the user's path is opened or how much of it is copied. Round 1
# bounded what root reads on Linux (P1-2: a link, a device or an endless file at the download's
# path) and left the same step on Windows as it was: `[IO.File]::Copy`, which follows a link and
# copies whatever it reaches, whole, into the administrators' folder. The class is one rule kept on
# one system's road and not the other's: R15.7.5 now says for Windows what R16.8.5 says for Linux.
def test_the_administrators_side_opens_the_download_once_follows_no_link_and_copies_no_more_than_was_checked(tmp_path, monkeypatch):
    """On any system, what the script's text must hold to, and what AppKata hands it. On Windows
    itself it is run (the test VM's session has administrator rights) on a link, on a longer
    file and on a folder at the download's path, and on a file of more than one read."""
    import hashlib
    import shutil
    setup = tmp_path / "setup one.exe"
    setup.write_bytes(b"MZ" + b"\0" * 70000)
    sha = hashlib.sha256(setup.read_bytes()).hexdigest()
    with monkeypatch.context() as m:
        asked = []
        m.setattr(w, "shell_execute", lambda program, args="", **how: asked.append(args) or 0)
        assert w.run_elevated(str(setup), sha.upper(), "/S") == 0
        script = _elevated_values(asked[0])["script"]
        # the user's path is opened once: by Windows' own CreateFileW, to read, an existing file, and with
        # FILE_FLAG_OPEN_REPARSE_POINT (0x00200000), so a link there is opened itself and not followed
        assert "[IO.File]::Copy" not in script and script.count("$src") == 2
        assert "::CreateFileW($src, [int]::MinValue, 1, [IntPtr]::Zero, 3, 0x00200000, [IntPtr]::Zero)" in script
        # only a file on a disk, of the length AppKata checked, and no more of it than that length and one byte
        assert "$len = [long]70002\n" in script
        steps = [script.index(step) for step in ("::CreateFileW($src,", "if ($k::GetFileType($from) -eq 1) {", "if ($in.Length -eq $len) {",
                                                 "$left = $len + 1", "while ($left -gt 0) {", "$in.Read($buf, 0, [int][Math]::Min($left, [long]$buf.Length))",
                                                 "$left -= $n", "[IO.File]::OpenRead($copy)", "if ($got -ne $want) { $code = %d }" % w.CHANGED)]
        assert steps == sorted(steps)
        # the length is that of the very bytes whose SHA-256 was checked: a file that already isn't those is
        # refused before Windows is asked, and so is one that can't be read
        with open(setup, "ab") as f:
            f.write(b"\0")
        assert w.run_elevated(str(setup), sha, "/S") == w.CHANGED and w.run_elevated(str(tmp_path / "gone.exe"), sha, "/S") == w.NOT_STARTED
        assert len(asked) == 1
    if os.name != "nt":
        return
    real, ran = tmp_path / "real.exe", tmp_path / "ran.txt"
    shutil.copy(os.path.join(os.environ.get("SystemRoot", "C:\\Windows"), "System32", "cmd.exe"), real)
    data = real.read_bytes()
    sha, args = hashlib.sha256(data).hexdigest(), f'/d /c "cd>{ran}"'
    # a link at the download's path to a file of the very bytes that were checked: followed, it would pass every check
    link = tmp_path / "setup two.exe"
    os.symlink(real, link)
    assert w.run_script_elevated(w.elevated_script(str(link), sha, len(data), args, False)) == w.CHANGED and not ran.exists()
    # a longer file, whose first bytes are the checked ones, and a shorter one
    longer, shorter = tmp_path / "setup three.exe", tmp_path / "setup four.exe"
    longer.write_bytes(data + b"\0" * (3 << 20))
    shorter.write_bytes(data[:-1])
    for other in (longer, shorter):
        assert w.run_script_elevated(w.elevated_script(str(other), sha, len(data), args, False)) == w.CHANGED and not ran.exists()
    # a folder at the path can't be opened as a file
    assert w.run_script_elevated(w.elevated_script(str(tmp_path), sha, len(data), args, False)) == w.NOT_STARTED and not ran.exists()
    # and the checked file itself is copied whole and started: one of more than one read (cmd.exe with 3 MB after it)
    assert w.run_elevated(str(longer), hashlib.sha256(longer.read_bytes()).hexdigest(), args) == 0 and ran.exists()
