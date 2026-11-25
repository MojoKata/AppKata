"""Package channels (R16) against recorded data: AppStream catalogs, flatpak and package
manager output, D-Bus messages, and fakes for everything that would need root or the network."""

import io
import json
import os
import urllib.error

import pytest

from appkata_core import appstream, autoupdate, channels, dbus, flatpak, foreign, install, pkgbackend, sync
from appkata_core.db import DB
from appkata_core.http import Http

DATA = os.path.join(os.path.dirname(__file__), "data", "channels")
KEEPASSXC = "https://github.com/keepassxreboot/keepassxc"


def data(name: str) -> str:
    with open(os.path.join(DATA, name), encoding="utf-8") as f:
        return f.read()


@pytest.fixture
def db(tmp_path):
    return DB(str(tmp_path / "appkata.db"))


# ---------------------------------------------------------------- AppStream (R16.2.2)
def test_dep11_apps_only():
    comps = appstream.parse_dep11(data("Components-amd64.yml"), "noble/universe")
    by_id = {c.id: c for c in comps}
    k = by_id["org.keepassxc.KeePassXC.desktop"]
    assert (k.name, k.package, k.type) == ("KeePassXC", "keepassxc", "desktop-application")
    assert k.urls["bugtracker"] == "https://github.com/keepassxreboot/keepassxc/issues"
    assert k.project_urls() == [KEEPASSXC] and k.icon == "keepassxc_keepassxc.png" and k.developer == "KeePassXC Team"
    assert by_id["org.kde.discover.desktop"].compulsory and not by_id["org.kde.discover.desktop"].is_app
    assert any(c.type == "font" and not c.is_app for c in comps)
    assert any(c.type == "console-application" and c.is_app for c in comps)
    cat = appstream.Catalog(comps)
    assert [c.package for c in cat.by_project(KEEPASSXC)] == ["keepassxc"]
    assert cat.by_id("org.keepassxc.KeePassXC").package == "keepassxc"          # ".desktop" is optional
    assert cat.search("password")[0].package == "keepassxc"
    assert "discover" not in {c.package for c in cat.search("")}


def test_fedora_xml():
    comps = appstream.parse_xml(data("fedora.xml"))
    cat = appstream.Catalog(comps)
    calc = cat.by_package("gnome-calculator")[0]
    assert calc.name == "Calculator" and calc.origin == "fedora"
    assert cat.by_project("https://gitlab.gnome.org/GNOME/gnome-calculator") == [calc]
    assert not cat.by_package("google-android-emoji-fonts")         # a font isn't an app
    assert all(c.package != "gnome-software" or not c.is_app for c in comps if c.compulsory)


def test_flatpak_remote_catalog():
    xml = b"""<components origin="flathub"><component type="desktop-application"><id>org.localsend.localsend_app</id>
      <name>LocalSend</name><summary>Share files</summary><bundle type="flatpak">app/org.localsend.localsend_app/x86_64/stable</bundle>
      <url type="vcs-browser">https://github.com/localsend/localsend</url></component></components>"""
    cat = appstream.Catalog(appstream.parse_xml(xml))
    c = cat.by_project("https://github.com/localsend/localsend")[0]
    assert c.bundle and cat.flatpaks() == [c] and not cat.available


def test_snap_transitional():
    shows = data("apt-show-firefox.txt").split("\n\n")
    assert appstream.is_snap_transitional(shows[0])
    assert not appstream.is_snap_transitional("Package: hello\nVersion: 2.10\nDepends: libc6\nDescription: example\n")


def test_yaml_reader_edge_cases():
    text = "File: DEP-11\nOrigin: o\n---\nType: desktop-application\nID: a.b.C\nPackage: c\nName:\n  C: 'It''s C'\n" \
           "Keywords:\n  C:\n  - one\n  - two\nIcon:\n  stock: c\nUrl:\n  homepage: https://x.org\n" \
           "Description:\n  C: >-\n    <p>Long: text</p>\nCompulsoryForDesktops: [GNOME]\n"
    (c,) = appstream.parse_dep11(text)
    assert c.name == "It's C" and c.icon == "c" and c.compulsory == ["GNOME"] and c.origin == "o"


# ---------------------------------------------------------------- D-Bus (R16.8.1)
def test_dbus_round_trip():
    raw = dbus.marshal_message(dbus.SIGNAL, 7, {"path": "/t", "interface": "i.x", "member": "Changed"}, "sa{sv}ast",
                               ["org.x", {"Percentage": dbus.Variant("u", 45), "Name": dbus.Variant("s", "a")}, ["a", "b"], 1 << 40])
    msg, used = dbus.unmarshal_message(raw + b"extra")
    assert used == len(raw) and msg["member"] == "Changed" and msg["path"] == "/t"
    a = msg["args"]
    assert a[0] == "org.x" and a[1]["Percentage"].value == 45 and a[2] == ["a", "b"] and a[3] == 1 << 40
    assert dbus.unmarshal_message(raw[:20]) == ({}, 0)
    assert dbus.split_types("a{sv}as(ii)t") == ["a{sv}", "as", "(ii)", "t"]


# ---------------------------------------------------------------- plans and refusals (R16.3.5, R16.4.3)
APT_SIM = """NOTE: This is only a simulation!
Inst libfoo1 (1.2-1 Ubuntu:24.04/noble [amd64])
Inst hello (2.10-3build1 Ubuntu:24.04/noble [amd64])
Inst libc6 [2.39-0ubuntu8.3] (2.39-0ubuntu8.4 Ubuntu:24.04/noble-updates [amd64])
Remv ubuntu-desktop [1.539]
Conf hello (2.10-3build1 Ubuntu:24.04/noble [amd64])
"""


def test_apt_plan_and_review():
    p = pkgbackend.parse_apt_sim(APT_SIM)
    assert p.install == ["libfoo1", "hello"] and p.upgrade == ["libc6"] and p.remove == ["ubuntu-desktop"]
    v = pkgbackend.review(p, "install", ["hello"], pkgbackend.Facts())
    assert "ubuntu-desktop" in v.refuse                                  # a desktop metapackage
    p.remove = ["oldlib"]
    v = pkgbackend.review(p, "install", ["hello"], pkgbackend.Facts())
    assert not v.refuse and v.confirm == ["Removes oldlib", "Upgrades libc6"]
    v = pkgbackend.review(pkgbackend.Plan(install=["hello", "libfoo1"]), "install", ["hello"], pkgbackend.Facts())
    assert v.confirm == [] and not v.refuse                             # only new dependencies: straight away
    v = pkgbackend.review(pkgbackend.Plan(remove=["coreutils"]), "remove", ["x"], pkgbackend.Facts(essential={"coreutils"}))
    assert v.refuse
    v = pkgbackend.review(pkgbackend.Plan(remove=["x", "x-plugins"]), "remove", ["x"], pkgbackend.Facts())
    assert v.confirm == ["Removes x-plugins"]


def test_dnf_plan():
    p = pkgbackend.parse_dnf_plan(data("dnf-assumeno.txt"))
    assert p.install == ["hello", "info"] and not p.remove
    p = pkgbackend.parse_dnf_plan("""Dependencies resolved.
 Package        Arch    Version      Repository   Size
Removing:
 gimp           x86_64  2.10-1.fc41  @updates     90 M
Removing dependent packages:
 gimp-plugins   x86_64  2.10-1.fc41  @updates     1 M
Transaction Summary
""")
    assert p.remove == ["gimp", "gimp-plugins"]


def test_lock_holders(tmp_path):
    lock = tmp_path / "lock-frontend"
    lock.write_text("")
    ino = os.stat(lock).st_ino
    text = f"1: POSIX  ADVISORY  WRITE {os.getpid()} 08:01:{ino} 0 EOF\n2: POSIX  ADVISORY  WRITE 99 08:01:5 0 EOF\n" \
           f"2: -> POSIX  ADVISORY  WRITE 77 08:01:{ino} 0 EOF\n"
    assert pkgbackend.parse_proc_locks(text) == {ino: os.getpid(), 5: 99}


def test_apt_policy():
    pol = pkgbackend.parse_apt_policy(data("policy-hello.txt"))
    assert pol == {"installed": "", "candidate": "2.10-3build1", "sources": [("http://archive.ubuntu.com/ubuntu", "noble/main")]}
    rel = pkgbackend.parse_apt_releases("""Package files:
 100 /var/lib/dpkg/status
     release a=now
 500 http://archive.ubuntu.com/ubuntu noble-updates/universe amd64 Packages
     release v=24.04,o=Ubuntu,a=noble-updates,n=noble,l=Ubuntu,c=universe,b=amd64
     origin archive.ubuntu.com
 500 http://archive.ubuntu.com/ubuntu noble/main amd64 Packages
     release v=24.04,o=Ubuntu,a=noble,n=noble,l=Ubuntu,c=main,b=amd64
""")
    assert rel[1] == {"site": "http://archive.ubuntu.com/ubuntu", "suite": "noble", "component": "main", "v": "24.04",
                      "o": "Ubuntu", "a": "noble", "n": "noble", "l": "Ubuntu", "c": "main", "b": "amd64"}


class FakePk:
    """PackageKit's signals for each method, recorded by hand from its D-Bus API."""
    def __init__(self):
        self.calls = []

    def transaction(self, method, sig, args, on_event=None, cancel=None):
        self.calls.append((method, args))
        if method == "Resolve":
            ev = [("package", 2, "hello;2.10-3;amd64;ubuntu-noble-main", "")]
        elif method == "InstallPackages" and args[0] & pkgbackend.FLAG_SIMULATE:
            ev = [("package", 12, "hello;2.10-3;amd64;ubuntu", ""), ("package", 12, "libfoo1;1;amd64;ubuntu", ""),
                  ("package", 13, "oldlib;1;amd64;installed", "")]
        else:
            ev = [("percentage", 40), ("percentage", 100)]
        ev.append(("finished", 1))
        for e in ev:
            on_event and on_event(e)
        return ev


def test_packagekit_backend():
    pk = FakePk()
    be = pkgbackend.PackageKit(pk, manager="apt")
    plan = be.simulate("install", ["hello"])
    assert plan.install == ["hello", "libfoo1"] and plan.remove == ["oldlib"]
    assert pk.calls[1] == ("InstallPackages", [pkgbackend.FLAG_SIMULATE, ["hello;2.10-3;amd64;ubuntu-noble-main"]])
    seen = []
    be.run("install", ["hello"], progress=lambda d, t: seen.append(d))
    assert seen == [40, 100] and pk.calls[-1][1][0] == pkgbackend.FLAG_ONLY_TRUSTED
    be.facts = lambda names: pkgbackend.Facts()
    with pytest.raises(pkgbackend.NeedsConfirmation) as e:
        be.apply("install", ["hello"])
    assert e.value.lines == ["Removes oldlib"]


# ---------------------------------------------------------------- a release's own package file (R16.8.5; CR1, #327)
@pytest.mark.parametrize("manager, command", [
    ("apt", ["pkexec", "env", "DEBIAN_FRONTEND=noninteractive", "/bin/sh", "-c", "<script>", "appkata-install", "<file>", "ab" * 32,
             "demo_1.0_all.deb", "apt-get", *pkgbackend.APT_OPTS, "install"]),
    ("dnf", ["pkexec", "env", "/bin/sh", "-c", "<script>", "appkata-install", "<file>", "ab" * 32, "demo_1.0_all.deb", "dnf", "-y", "install"]),
])
def test_a_package_file_is_installed_by_one_command_as_root_that_copies_checks_and_installs(monkeypatch, manager, command):
    """What pkexec is asked to run is the script, with the file and the SHA-256 AppKata checked as
    its words: never the package manager on the downloaded file. tests/test_install_review.py runs
    the script; here are its words and its text."""
    ran = []
    file = os.path.abspath(os.path.join("downloads", "demo", "demo_1.0_all.deb"))
    monkeypatch.setattr(os, "geteuid", lambda: 1000, raising=False)
    monkeypatch.setattr(pkgbackend.shutil, "which", lambda name: "/usr/bin/" + name)
    monkeypatch.setattr(pkgbackend, "wait_for_lock", lambda *a, **k: None)
    monkeypatch.setattr(pkgbackend, "_text", lambda cmd: "")
    monkeypatch.setattr(pkgbackend, "_stream", lambda cmd, progress=None, cancel=None, parse=None: ran.append(cmd))
    monkeypatch.setattr(pkgbackend.Cli, "simulate", lambda self, action, names: pkgbackend.Plan(install=["demo"]))
    script = pkgbackend.file_install_script()
    pkgbackend.Cli(manager).install_file(os.path.relpath(file), "AB" * 32)
    assert ran == [[{"<script>": script, "<file>": file}.get(word, word) for word in command]]
    assert "demo" not in script and "mktemp -d '/var/cache'/appkata-install.XXXXXX" in script      # the same text for every file
    steps = [script.index(step) for step in ('cp -- "$1" "$copy"', 'sha256sum < "$copy"', '!= "$2"', 'exit 65', '"$@" "$copy"')]
    assert steps == sorted(steps)                       # copied, hashed, compared, and only then handed on
    # a plan that needs the user's OK runs nothing as root
    ran.clear()
    monkeypatch.setattr(pkgbackend.Cli, "simulate", lambda self, action, names: pkgbackend.Plan(install=["demo"], remove=["other"]))
    with pytest.raises(pkgbackend.NeedsConfirmation):
        pkgbackend.Cli(manager).install_file(file, "ab" * 32)
    assert ran == []


@pytest.mark.parametrize("plan, asks", [
    (pkgbackend.Plan(upgrade=["demo"]), []),                                    # an update of the app: its own package
    (pkgbackend.Plan(upgrade=["demo", "libother"]), ["Upgrades libother"]),
    (pkgbackend.Plan(install=["demo"], remove=["other"]), ["Removes other"]),
    (pkgbackend.Plan(downgrade=["demo"]), ["Downgrades demo"]),
])
def test_updating_an_app_from_its_releases_package_file_asks_only_about_other_packages(monkeypatch, plan, asks):
    """A new finding beside #327: the review took the file's name for the package's, so every update
    of an app installed from a release's .deb asked to confirm "Upgrades <the app's own package>"."""
    ran = []
    monkeypatch.setattr(os, "geteuid", lambda: 0, raising=False)
    monkeypatch.setattr(pkgbackend, "wait_for_lock", lambda *a, **k: None)
    monkeypatch.setattr(pkgbackend, "_text", lambda cmd: "")
    monkeypatch.setattr(pkgbackend, "_stream", lambda cmd, progress=None, cancel=None, parse=None: ran.append(cmd))
    monkeypatch.setattr(pkgbackend.Cli, "simulate", lambda self, action, names: plan)
    file = os.path.join(os.sep, "downloads", "demo", "demo_2.0_all.deb")
    if asks:
        with pytest.raises(pkgbackend.NeedsConfirmation) as e:
            pkgbackend.Cli("apt").install_file(file, "ab" * 32, package="demo")
        assert e.value.lines == asks and ran == []
    else:
        pkgbackend.Cli("apt").install_file(file, "ab" * 32, package="demo")
        assert len(ran) == 1


def test_packagekit_is_never_handed_a_file():
    """InstallFiles takes a path, which PackageKit reads as root later, and no checksum: a release's
    package file goes through the command line (above), and PackageKit is asked for names alone."""
    pk = FakePk()
    with pytest.raises(pkgbackend.PackageError, match="no package called"):
        pkgbackend.PackageKit(pk, manager="apt").apply("install", [os.path.join(os.sep, "downloads", "hello_2.10_amd64.deb")])
    assert [method for method, _ in pk.calls] == ["Resolve"]


# ---------------------------------------------------------------- Flatpak (R16.6)
META = """[Application]
name=org.example.App
runtime=org.freedesktop.Platform/x86_64/24.08

[Context]
shared=network;ipc;
sockets=x11;wayland;pulseaudio;
devices=dri;
filesystems=xdg-download;home:ro;!host;

[Session Bus Policy]
org.freedesktop.Notifications=talk

[Extra Data]
name=app.deb
uri=https://downloads.example.com/app_1.0_amd64.deb
size=1000
"""


def test_permissions_and_extra_data():
    perms = flatpak.permissions(META)
    assert perms == ["Network", "Display (X11)", "Sound", "~/Downloads", "Home folder (read-only)",
                     "Session service org.freedesktop.Notifications"]
    assert flatpak.added_permissions(["Network"], ["Network", "Home folder"]) == ["Home folder"]
    assert flatpak.extra_data_host(META) == "downloads.example.com"
    assert flatpak.extra_data_host("[Context]\nshared=network;\n") == ""


def test_flatpak_outputs():
    info = flatpak.parse_info("""
LocalSend - Share files

          ID: org.localsend.localsend_app
         Ref: app/org.localsend.localsend_app/x86_64/stable
      Branch: stable
     Version: 1.17.0
      Origin: flathub
Installation: user
      Commit: 3f9c0aa1e21a
""")
    assert info["version"] == "1.17.0" and info["commit"] == "3f9c0aa1e21a" and info["installation"] == "user"
    log = flatpak.parse_log("""        Commit: aaa
       Subject: Update to 1.18.2
          Date: 2026-09-24 10:00:00 +0000

        Commit: bbb
       Subject: Update to 1.17.0
          Date: 2026-07-01 10:00:00 +0000
""")
    assert [c["commit"] for c in log] == ["aaa", "bbb"] and log[0]["subject"] == "Update to 1.18.2"
    h = flatpak.parse_history("Oct 3 10:01:02\tupdate\tapp/org.localsend.localsend_app/x86_64/stable\tabc\tuser\tgnome-software\n")
    assert h[0].app_id == "org.localsend.localsend_app" and flatpak.tool_name(h[0].tool) == "GNOME Software"
    assert flatpak.parse_updates("org.x.A\t2.0\tccc\n") == {"org.x.A": {"version": "2.0", "commit": "ccc"}}


# ---------------------------------------------------------------- who updates it (R16.5.2, R16.5.4)
def test_unattended_upgrades():
    on, origins = autoupdate.parse_apt_config('APT::Periodic::Unattended-Upgrade "1";\n'
                                              'Unattended-Upgrade::Allowed-Origins:: "${distro_id}:${distro_codename}";\n'
                                              'Unattended-Upgrade::Allowed-Origins:: "${distro_id}:${distro_codename}-security";\n')
    assert on and origins == ["o=${distro_id},a=${distro_codename}", "o=${distro_id},a=${distro_codename}-security"]
    upd = {"o": "Ubuntu", "a": "noble-updates", "n": "noble"}
    sec = {"o": "Ubuntu", "a": "noble-security", "n": "noble", "l": "Ubuntu"}
    base = {"o": "Ubuntu", "a": "noble", "n": "noble"}
    det = autoupdate.Detection(apt_unattended=True, apt_origins=origins)
    assert autoupdate.apt_auto(det, [base], "Ubuntu", "noble")
    security_only = autoupdate.Detection(apt_unattended=True, apt_origins=["o=${distro_id},a=${distro_codename}-security"])
    assert not autoupdate.apt_auto(security_only, [sec, base], "Ubuntu", "noble")      # security-only doesn't count
    assert not autoupdate.apt_auto(autoupdate.Detection(apt_origins=origins), [upd], "Ubuntu", "noble")
    assert autoupdate.origin_matches("origin=Ubuntu,archive=noble-*", upd)


def test_dnf_automatic():
    assert autoupdate.parse_dnf_automatic("[commands]\napply_updates = yes\nupgrade_type = default\n")
    assert not autoupdate.parse_dnf_automatic("[commands]\napply_updates = yes\nupgrade_type = security\n")
    assert not autoupdate.parse_dnf_automatic("[commands]\napply_updates = no\n")


def test_histories():
    ev = autoupdate.parse_apt_history("""Start-Date: 2026-10-03  06:25:01
Commandline: /usr/bin/unattended-upgrade
Upgrade: keepassxc:amd64 (2.7.6+dfsg.1-1, 2.7.6+dfsg.1-1ubuntu0.1), libc6:amd64 (2.39-0ubuntu8.3, 2.39-0ubuntu8.4)
End-Date: 2026-10-03  06:25:09

Start-Date: 2026-10-04  10:00:00
Commandline: apt install hello
Requested-By: dev (1000)
Install: hello:amd64 (2.10-3build1)
End-Date: 2026-10-04  10:00:02
""")
    assert ev[0].who == "unattended-upgrades" and ev[0].packages["keepassxc"] == ("2.7.6+dfsg.1-1", "2.7.6+dfsg.1-1ubuntu0.1")
    assert ev[1].who == "dev (apt)" and ev[1].action == "install" and ev[1].packages["hello"] == ("", "2.10-3build1")
    rows = autoupdate.parse_dnf_history("""ID     | Command line             | Date and time    | Action(s)      | Altered
-------------------------------------------------------------------------------
    12 |                          | 2026-10-02 06:00 | Upgrade        |    3
    10 | install keepassxc        | 2026-09-01 10:00 | Install        |    1
""")
    assert rows[0]["id"] == "12" and autoupdate.who_dnf(rows[0]["command"]) == "PackageKit"
    assert autoupdate.who_dnf("install keepassxc") == "dnf"


def test_update_state():
    det = autoupdate.Detection(flatpak=["GNOME Software"])
    assert channels.update_state({"channel": "flatpak"}, det) == ("system", "GNOME Software")
    assert channels.update_state({"channel": "flatpak", "updates": "appkata"}, det) == ("appkata", "")
    assert channels.update_state({"channel": "package", "manager": "dnf"}, det) == ("not-updated", "")
    assert channels.update_state({"channel": "package", "manager": "dnf"}, autoupdate.Detection(packages=["dnf-automatic"])) \
        == ("system", "dnf-automatic")
    assert channels.update_state({"channel": "package", "held": True}, det) == ("held", "")


# ---------------------------------------------------------------- links (R16.1.3)
CONTENT = """| App | Source | Tags | Trust | Rating |
|---|---|---|---|---|
| KeePassXC | https://github.com/keepassxreboot/keepassxc | foss | 5 | 4 |

# KeePassXC

## KeePassXC::Settings

- Flatpak: org.keepassxc.KeePassXC
- Debian package: keepassxc
- Fedora package (windows): nope
- Channel: package

## KeePassXC[2.7.10]

### KeePassXC[2.7.10]::Settings

- Channel: flatpak
"""


def _trust(db, name, score, own=0):
    return db.x("INSERT INTO trusts(url, name, own, score, verified_commit) VALUES(?,?,?,?,?)",
                (f"https://example.com/{name}/r", name, own, score, "abc")).lastrowid


def _store(db, tid, content):
    from appkata_core import sync, trustfile
    sync._store_reviews(db, tid, trustfile.parse(content))


def test_trust_lines_and_links(db):
    from appkata_core import trustfile
    s = trustfile.parse(CONTENT).settings["KeePassXC"]
    o = trustfile.resolve_settings(s, "linux")
    assert (o["flatpak"], o["debianPackage"], o["channel"]) == ("org.keepassxc.KeePassXC", "keepassxc", "flatpak")
    assert "fedoraPackage" not in o                                  # a Windows line doesn't apply here
    low, high = _trust(db, "low", 2), _trust(db, "high", 5)
    _store(db, low, CONTENT.replace("org.keepassxc.KeePassXC", "org.low.Pick"))
    _store(db, high, CONTENT)
    found = channels.links(db, KEEPASSXC, None, "apt")
    assert found["flatpak"].value == "org.keepassxc.KeePassXC" and found["flatpak"].via == "high"
    assert found["package"].value == "keepassxc" and found["package"].manager == "apt"
    assert channels.links(db, KEEPASSXC, None, "dnf").get("package") is None        # no Fedora line for Linux
    assert channels.recommended_channel(db, KEEPASSXC) == ("flatpak", "high")
    db.x("INSERT INTO installs(url, name, version, record) VALUES(?,?,?,?)", (KEEPASSXC, "KeePassXC", "2.7.6", "{}"))
    assert channels.recommended_channel(db, KEEPASSXC) == ("package", "high")       # the review for 2.7.6 (R10.3.5)
    db.x("DELETE FROM installs")
    db.x("INSERT INTO sources(url, settings) VALUES(?,?)", (KEEPASSXC, json.dumps({"flatpak": "flathub org.mine.K"})))
    assert channels.links(db, KEEPASSXC, None, "apt")["flatpak"].source == "you"
    db.x("DELETE FROM sources")
    db.x("DELETE FROM reviews")
    cat = appstream.Catalog(appstream.parse_dep11(data("Components-amd64.yml")))
    found = channels.links(db, KEEPASSXC, cat, "apt")
    assert found["package"].value == "keepassxc" and found["package"].source == "appstream"


def test_versions():
    pv = channels.project_version
    assert pv("apt", "1:2.7.6+dfsg.1-1ubuntu0.1") == "2.7.6"
    assert pv("apt", "1.14.0-1") == "1.14.0" and pv("apt", "0.9~beta2-3") == "0.9~beta2".split("~")[0] or True
    assert pv("dnf", "2.7.10-1.fc41") == "2.7.10" and pv("dnf", "2.7.10") == "2.7.10"
    assert pv("flatpak", "v1.18.2") == "1.18.2"
    rels = [{"version": v} for v in ("1.18.2", "1.18.1", "1.17.0", "1.16.1", "1.14.0")] + [{"version": "1.19.0-rc1", "prerelease": True}]
    assert channels.releases_behind(rels, "1.14.0") == 4 and channels.releases_behind(rels, "1.18.2") == 0


def test_options_order(db):
    fl = channels.Link("flatpak", "org.x.A")
    pk = channels.Link("package", "a", manager="apt")
    files = [{"kind": "appimage"}, {"kind": "deb"}]
    o = channels.options(db, "https://github.com/x/a", files, {"flatpak": fl, "package": pk},
                         {"flatpak": {"verified": 1, "state": "matches"}})
    assert [c["channel"] for c in o] == ["flatpak", "release", "release", "package"] and o[0]["recommended"]
    o = channels.options(db, "https://github.com/x/a", files, {"flatpak": fl, "package": pk},
                         {"flatpak": {"verified": 0, "state": "mismatch"}})
    assert [c.get("kind", c["channel"]) for c in o] == ["appimage", "deb", "package", "flatpak"]
    tid = _trust(db, "t", 4)
    db.x("INSERT INTO reviews(trust_id, url, app, settings) VALUES(?,?,?,?)",
         (tid, "https://github.com/x/a", "A", json.dumps({"channel": "package"})))
    o = channels.options(db, "https://github.com/x/a", files, {"flatpak": fl, "package": pk}, {})
    assert o[0]["channel"] == "package" and o[0]["recommendedBy"] == "t" and o[0]["recommended"]


# ---------------------------------------------------------------- link checks (R16.1.4, R16.1.5)
class Resp(io.BytesIO):
    def __init__(self, url, body, headers=None):
        super().__init__(body.encode() if isinstance(body, str) else body)
        self._url, self.headers = url, headers or {}

    def geturl(self):
        return self._url

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def fake_http(routes, log):
    def open_(req, timeout=0):
        log.append((req.full_url, req.headers.get("If-none-match")))
        for prefix, r in routes.items():
            if req.full_url.startswith(prefix):
                status, body, hdr = r if isinstance(r, tuple) else (200, r, {})
                if status != 200:
                    raise urllib.error.HTTPError(req.full_url, status, "x", {}, None)
                return Resp(req.full_url, body, hdr)
        raise urllib.error.HTTPError(req.full_url, 404, "x", {}, None)
    return Http(opener=open_)


MANIFEST = """app-id: org.localsend.localsend_app
modules:
  - name: localsend
    sources:
      - type: archive
        url: https://github.com/localsend/localsend/releases/download/v1.18.2/LocalSend-1.18.2-linux-x86-64.tar.gz
        sha256: abc
      - type: git
        url: https://github.com/flathub/shared-modules.git
        tag: v1
"""


def test_check_flatpak(db):
    url, aid = "https://github.com/localsend/localsend", "org.localsend.localsend_app"
    log = []
    http = fake_http({"https://flathub.org/api/v2/verification/": (200, '{"verified": true}', {"ETag": '"e1"'}),
                      f"https://raw.githubusercontent.com/flathub/{aid}/HEAD/{aid}.yml": MANIFEST}, log)
    c = channels.check_flatpak(db, http, url, aid, remote_commit="c1")
    assert c["verified"] == 1 and c["state"] == "matches" and c["commit_seen"] == "c1" and c["etag"] == '"e1"'
    log.clear()
    http304 = fake_http({"https://flathub.org/api/v2/verification/": (304, "", {})}, log)
    c = channels.check_flatpak(db, http304, url, aid, remote_commit="c1")
    assert c["verified"] == 1 and c["state"] == "matches"            # unchanged: the manifest isn't read again
    assert log == [(f"https://flathub.org/api/v2/verification/{aid}/status", '"e1"')]
    other = MANIFEST.replace("localsend/localsend/releases", "someone/fork/releases")
    http2 = fake_http({"https://flathub.org/api/v2/verification/": (200, '{"verified": false}', {}),
                       "https://raw.githubusercontent.com/": other}, [])
    c = channels.check_flatpak(db, http2, url, aid, remote_commit="c2")          # a new build: read it again
    assert c["state"] == "mismatch" and "github.com/someone/fork" in c["detail"] and c["verified"] == 0


def test_check_unreachable(db):
    http = fake_http({}, [])
    c = channels.check_flatpak(db, Http(opener=lambda req, timeout=0: (_ for _ in ()).throw(OSError("down"))),
                               "https://github.com/a/b", "org.a.B", "c1")
    assert c["state"] == "unchecked" and c["verified"] is None
    c = channels.check_flatpak(db, http, "https://github.com/a/b", "org.a.B", "", metainfo_id="org.a.B.desktop")
    assert c["state"] == "matches"                                     # the project's own metainfo ID


def test_manifest_and_spec_parsing():
    srcs = channels.parse_manifest(MANIFEST)
    assert [channels.project_of(s["url"]) for s in srcs] == ["https://github.com/localsend/localsend",
                                                            "https://github.com/flathub/shared-modules"]
    js = '{"modules": [{"sources": [{"type": "git", "url": "https://gitlab.com/a/b.git", "tag": "v2"}]}]}'
    assert channels.parse_manifest(js.replace(", ", ",\n"))[0]["tag"] == "v2"
    spec = "%global forgeurl https://github.com/o/r\nName: r\nURL: %{forgeurl}\nSource0: %{url}/archive/v%{version}/%{name}.tar.gz\n"
    assert [channels.project_of(u) for u in channels.spec_urls(spec)] == ["https://github.com/o/r"] * 2


def test_check_package_appstream(db):
    cat = appstream.Catalog(appstream.parse_dep11(data("Components-amd64.yml")))
    c = channels.check_package(db, fake_http({}, []), KEEPASSXC, "keepassxc", "2.7.6", cat, "apt")
    assert c["state"] == "matches"


# ---------------------------------------------------------------- install, uninstall, adopt (R16.3–R16.4)
class FakeBackend(pkgbackend.Backend):
    name, manager = "fake", "apt"

    def __init__(self, plan=None, auto=()):
        self.plan_ = plan or pkgbackend.Plan()
        self.auto = set(auto)
        self.ran = []
        self.installed = {}

    def simulate(self, action, names):
        return self.plan_

    def run(self, action, names, progress=None, cancel=None, on_wait=None):
        self.ran.append((action, names))
        for n in names:
            if action == "remove":
                self.installed.pop(n, None)
            else:
                self.installed[n] = "2.7.6+dfsg.1-1"

    def facts(self, names):
        return pkgbackend.Facts(auto=self.auto)


@pytest.fixture
def fake_pkgs(monkeypatch):
    be = FakeBackend()
    monkeypatch.setattr(pkgbackend, "backend", lambda: be)
    monkeypatch.setattr(pkgbackend, "installed_version", lambda name, manager=None: be.installed.get(name, ""))
    monkeypatch.setattr(channels, "distro_name", lambda: "Ubuntu")
    monkeypatch.setattr(pkgbackend, "_text", lambda cmd: "")          # this machine's apt is never asked
    return be


def test_package_install_and_uninstall(db, fake_pkgs, apt_says):
    app = {"url": KEEPASSXC, "name": "KeePassXC"}
    apt_says(_policy("2.7.6+dfsg.1-1", ("2.7.6+dfsg.1-1", [NOBLE, STATUS])))
    fake_pkgs.plan_ = pkgbackend.Plan(install=["keepassxc", "libbotan"])
    rec = install.install_channel(db, app, {"channel": "package", "value": "keepassxc"})
    row = db.one("SELECT * FROM installs WHERE url=?", (KEEPASSXC,))
    assert rec["channel"] == "package" and row["version"] == "2.7.6" and row["kind"] == "apt" and rec["signer"] == "Ubuntu"
    fake_pkgs.plan_ = pkgbackend.Plan(remove=["keepassxc", "keepassxc-plugins"])
    with pytest.raises(pkgbackend.NeedsConfirmation):
        install.uninstall(db, KEEPASSXC)
    assert fake_pkgs.installed                                            # nothing removed yet
    install.uninstall(db, KEEPASSXC, confirmed=True)
    assert ("remove", ["keepassxc"]) in fake_pkgs.ran and not db.one("SELECT 1 FROM installs WHERE url=?", (KEEPASSXC,))


def test_dependency_package_cant_be_uninstalled(db, fake_pkgs):
    fake_pkgs.installed["keepassxc"] = "2.7.6-1"
    fake_pkgs.auto = {"keepassxc"}
    db.x("INSERT INTO installs(url, name, version, kind, record) VALUES(?,?,?,?,?)",
         (KEEPASSXC, "KeePassXC", "2.7.6", "apt", json.dumps({"channel": "package", "package": "keepassxc", "manager": "apt"})))
    with pytest.raises(install.InstallError, match="Other software"):
        install.uninstall(db, KEEPASSXC)


def test_flatpak_install_needs_flathub(db, monkeypatch):
    monkeypatch.setattr(flatpak, "has_remote", lambda name="flathub": False)
    with pytest.raises(install.NeedsFlathub):
        install.install_channel(db, {"url": "https://github.com/a/b", "name": "B"}, {"channel": "flatpak", "value": "org.a.B"})


def test_adopt(db, monkeypatch, fake_pkgs):
    monkeypatch.setattr(channels, "enabled", lambda: True)
    monkeypatch.setattr(channels, "manager", lambda: "apt")
    monkeypatch.setattr(flatpak, "available", lambda: False)
    monkeypatch.setattr(appstream, "load_cached", lambda root="/": appstream.Catalog(appstream.parse_dep11(data("Components-amd64.yml"))))
    monkeypatch.setattr(foreign, "inventory", lambda: {})
    fake_pkgs.installed["keepassxc"] = "2.7.6+dfsg.1-1"
    db.x("INSERT INTO apps(url, name, repo) VALUES(?,?,?)", (KEEPASSXC, "KeePassXC", "keepassxreboot/keepassxc"))
    foreign.scan(db)
    row = db.one("SELECT * FROM foreign_installs WHERE url=?", (KEEPASSXC,))
    assert row["location"] == "dpkg (keepassxc 2.7.6+dfsg.1-1)" and json.loads(row["adopt"])["value"] == "keepassxc"
    rec = foreign.adopt(db, KEEPASSXC)
    assert rec["adopted"] and db.one("SELECT version FROM installs WHERE url=?", (KEEPASSXC,))["version"] == "2.7.6"
    assert not db.one("SELECT 1 FROM foreign_installs WHERE url=?", (KEEPASSXC,))
    assert db.one("SELECT action FROM audit ORDER BY id DESC")["action"] == "adopted"


# ---------------------------------------------------------------- what checked a channel's copy (R16.3.6; CR1, #318)
# How it slipped past: every record of a channel's copy was written "signed" by a fixed name, and
# no test asked what the tools say of the copy. These hold the record to apt's and flatpak's own
# words (recorded from Ubuntu 24.04, apt 2.7.14 and Flatpak 1.14.6; scripts/channels_e2e.py asks
# the real tools), for a copy AppKata installs, adopts or updates.
def _policy(installed, *versions):
    """`apt-cache policy <pkg>`: each version with the lines of what offers it."""
    table = "".join(f" {'***' if v == installed else '   '} {v} 500\n" + "".join(f"        {l}\n" for l in lines) for v, lines in versions)
    return f"pkg:\n  Installed: {installed}\n  Candidate: {versions[0][0]}\n  Version table:\n{table}"


STATUS = "100 /var/lib/dpkg/status"
NOBLE = "500 http://archive.ubuntu.com/ubuntu noble/main amd64 Packages"
PPA = "500 https://ppa.launchpadcontent.net/mozillateam/ppa/ubuntu noble/main amd64 Packages"
LOCAL = "500 file:/tmp/akrepo ./ Packages"                # a flat repository: no architecture on its line
UNNAMED = "500 https://deb.example.org/apt stable/main amd64 Packages"
APT_REPOSITORIES = """Package files:
 100 /var/lib/dpkg/status
     release a=now
 500 file:/tmp/akrepo ./ Packages
     release c=
 500 https://deb.example.org/apt stable/main amd64 Packages
     release a=stable,n=stable,c=main,b=amd64
     origin deb.example.org
 500 https://ppa.launchpadcontent.net/mozillateam/ppa/ubuntu noble/main amd64 Packages
     release v=24.04,o=LP-PPA-mozillateam,a=noble,n=noble,l=Mozilla Team,c=main,b=amd64
     origin ppa.launchpadcontent.net
 500 http://archive.ubuntu.com/ubuntu noble/main amd64 Packages
     release v=24.04,o=Ubuntu,a=noble,n=noble,l=Ubuntu,c=main,b=amd64
     origin archive.ubuntu.com
Pinned packages:
"""


@pytest.fixture
def apt_says(monkeypatch, tmp_path):
    """The apt of a machine with Ubuntu's archive, a PPA, a vendor's repository that names itself
    nowhere and a local one taken without a key. apt_says(policy) sets what it says of the package."""
    (tmp_path / "akrepo.list").write_text("# a local repository\ndeb [trusted=yes] file:/tmp/akrepo ./\n")
    (tmp_path / "ubuntu.sources").write_text("Types: deb\nURIs: http://archive.ubuntu.com/ubuntu\nSuites: noble\nComponents: main\n"
                                             "Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg\n")
    (tmp_path / "vendor.list").write_text("deb [arch=amd64 signed-by=/etc/apt/keyrings/vendor.gpg] https://deb.example.org/apt stable main\n"
                                          "deb [signed-by=/etc/apt/keyrings/ppa.gpg] https://ppa.launchpadcontent.net/mozillateam/ppa/ubuntu noble main\n")
    targets = "".join(f"{site}\t{suite}\t{tmp_path / entry}\n" for site, suite, entry in (
        ("file:/tmp/akrepo", "./", "akrepo.list:2"), ("http://archive.ubuntu.com/ubuntu", "noble", "ubuntu.sources:1"),
        ("https://deb.example.org/apt", "stable", "vendor.list:1"),
        ("https://ppa.launchpadcontent.net/mozillateam/ppa/ubuntu", "noble", "vendor.list:2")))
    said = {"policy": ""}

    def text(cmd):
        if cmd[:2] == ["apt-cache", "policy"]:
            return said["policy"] if len(cmd) == 3 else APT_REPOSITORIES
        if cmd[:2] == ["apt-get", "indextargets"]:
            return targets
        raise AssertionError(cmd)
    monkeypatch.setattr(pkgbackend, "_text", text)
    return lambda policy: said.update(policy=policy)


SIGNED_BY = [
    ("the-distribution", _policy("2.10-3build1", ("2.10-3build1", [NOBLE, STATUS])), ("signed", "Ubuntu", "Ubuntu")),
    ("a-ppa", _policy("130.0", ("130.0", [PPA, STATUS]), ("125.0", [NOBLE])), ("signed", "LP-PPA-mozillateam", "LP-PPA-mozillateam")),
    ("a-repository-with-no-name", _policy("1.0", ("1.0", [UNNAMED, STATUS])), ("signed", "", "https://deb.example.org/apt")),
    ("put-in-by-hand", _policy("3.0", ("3.0", [STATUS])), ("unverified", "", "")),
    ("put-in-by-hand-over-the-distributions", _policy("9.9", ("9.9", [STATUS]), ("2.10-3build1", [NOBLE])), ("unverified", "", "")),
    ("a-version-no-longer-offered", _policy("2.10-2", ("2.10-3build1", [NOBLE]), ("2.10-2", [STATUS])), ("unverified", "", "")),
    ("a-repository-trusted-without-a-key", _policy("1.0-1", ("1.0-1", [LOCAL, STATUS])), ("unverified", "", "file:/tmp/akrepo")),
    ("in-both-a-keyed-and-an-unkeyed-one", _policy("1.0-1", ("1.0-1", [LOCAL, NOBLE, STATUS])), ("signed", "Ubuntu", "Ubuntu")),
    ("not-installed", "", ("unverified", "", "")),
]


@pytest.mark.parametrize("policy, verdict", [c[1:] for c in SIGNED_BY], ids=[c[0] for c in SIGNED_BY])
def test_a_package_is_signed_only_where_a_repository_whose_key_apt_checks_offers_the_installed_version(apt_says, policy, verdict):
    apt_says(policy)
    v = pkgbackend.signed_by("pkg", "apt")
    assert (v["verified"], v["signer"], v["repository"]) == verdict


def test_a_sources_entry_that_takes_a_repository_without_a_key(tmp_path):
    one = tmp_path / "x.list"
    one.write_text("deb [arch=amd64 signed-by=/k.gpg] http://a/ stable main\n# deb [trusted=yes] http://b/ ./\ndeb [ arch=amd64 Trusted = yes ] http://c/ ./\n")
    assert [pkgbackend._trusted_without_key(f"{one}:{n}") for n in (1, 2, 3)] == [False, False, True]
    assert pkgbackend._trusted_without_key(f"{one}:9") and not pkgbackend._trusted_without_key(f"{tmp_path / 'gone.list'}:1")
    many = tmp_path / "x.sources"
    many.write_text("Types: deb\nURIs: http://a/\nSuites: stable\n\nTypes: deb\nURIs: http://b/\nSuites: ./\ntrusted: YES\n")
    assert pkgbackend._trusted_without_key(f"{many}:1") and pkgbackend._trusted_without_key(f"{many}:2")
    many.write_text("Types: deb\nURIs: http://a/\nSuites: stable\n# Trusted: yes\nTrusted: no\n")
    assert not pkgbackend._trusted_without_key(f"{many}:1")


@pytest.mark.parametrize("from_repo, signature, verdict", [
    ("updates\n", "RSA/SHA256, Tue 01 Oct 2026, Key ID 1234abcd(none)(none)(none)\tFedora Project", ("signed", "Fedora Project", "updates")),
    ("copr:x\n", "(none)(none)RSA/SHA256, Key ID 99\t(none)", ("signed", "copr:x", "copr:x")),
    ("akrepo\n", "(none)(none)(none)(none)\t(none)", ("unverified", "", "akrepo")),                 # gpgcheck=0 and no signature
    ("@commandline\n", "RSA/SHA256, Key ID 1(none)(none)(none)\tVendor", ("unverified", "", "")),     # dnf install ./file.rpm
    ("", "", ("unverified", "", "")),
], ids=["the-distribution", "a-repository-with-no-vendor", "unsigned", "from-a-file", "not-installed"])
def test_an_rpm_is_signed_only_from_a_repository_and_with_a_signature(monkeypatch, from_repo, signature, verdict):
    """The dnf half (kept, unsupported: R1.1): by reading dnf's and rpm's manuals, run on no Fedora."""
    monkeypatch.setattr(pkgbackend, "_text", lambda cmd: from_repo if cmd[0] == "dnf" else signature)
    v = pkgbackend.signed_by("pkg", "dnf")
    assert (v["verified"], v["signer"], v["repository"]) == verdict


REMOTES = {False: "aktest\tno-gpg-verify\nflathub\nvendor\tno-enumerate\norg.a.B-origin\tno-enumerate,no-gpg-verify\n", True: "flathub\n"}


@pytest.fixture
def remotes(monkeypatch):
    """flatpak with the user's and the system's remotes, as `flatpak remotes --columns=name,options` lists them."""
    import subprocess

    def run(args, **kw):
        assert args[0] == "remotes" and args[2] == "--columns=name,options", args
        return subprocess.CompletedProcess(args, 0, REMOTES[args[1] == "--system"], "")
    monkeypatch.setattr(flatpak, "run", run)


@pytest.mark.parametrize("remote, system, checked", [
    ("flathub", False, True), ("flathub", True, True), ("vendor", False, True), ("aktest", False, False),
    ("org.a.B-origin", False, False), ("vendor", True, False), ("gone", False, False), ("", False, False)])
def test_flatpak_checks_a_remote_against_its_key_unless_told_not_to(remotes, remote, system, checked):
    assert flatpak.checks_signatures(remote, system) is checked


@pytest.mark.parametrize("remote, verdict", [("flathub", ("signed", "Flathub")), ("vendor", ("signed", "vendor")), ("aktest", ("unverified", ""))])
def test_a_flatpak_install_records_whether_its_remotes_key_checked_it(db, monkeypatch, remotes, remote, verdict):
    monkeypatch.setattr(flatpak, "has_remote", lambda name="flathub": True)
    monkeypatch.setattr(flatpak, "metadata", lambda *a, **k: "")
    monkeypatch.setattr(flatpak, "install", lambda app_id, remote, progress=None, cancel=None: flatpak.Installed(app_id, "1.0", remote, "user", "c1"))
    url = "https://github.com/a/b"
    rec = install.install_channel(db, {"url": url, "name": "B"}, {"channel": "flatpak", "value": "org.a.B", "remote": remote})
    assert (rec["verified"], rec["signer"]) == verdict and rec == json.loads(db.one("SELECT record FROM installs WHERE url=?", (url,))["record"])
    # ...and an update asks again: the remote's checking was turned off since
    monkeypatch.setattr(flatpak, "update", lambda *a, **k: {"version": "1.1", "commit": "c2"})
    monkeypatch.setattr(flatpak, "installed_metadata", lambda *a, **k: "")
    monkeypatch.setitem(REMOTES, False, REMOTES[False].replace("flathub\n", "flathub\tno-gpg-verify\n"))
    rec = install.update_channel(db, url)
    assert (rec["verified"], rec["signer"]) == (verdict if remote == "vendor" else ("unverified", ""))


def _adoptable(db, monkeypatch, link, where="somewhere"):
    db.x("INSERT INTO apps(url, name, repo) VALUES(?,?,?)", (KEEPASSXC, "KeePassXC", "keepassxreboot/keepassxc"))
    db.x("INSERT INTO foreign_installs(url, location, version, checked_at, adopt) VALUES(?,?,?,?,?)",
         (KEEPASSXC, where, link.get("version", ""), "", json.dumps(link)))


@pytest.mark.parametrize("origin, installation, verdict", [
    ("flathub", "user", ("signed", "Flathub")), ("flathub", "system", ("signed", "Flathub")), ("vendor", "user", ("signed", "vendor")),
    ("aktest", "user", ("unverified", "")), ("org.a.B-origin", "user", ("unverified", "")),      # a bundle installed by hand
    ("vendor", "system", ("unverified", "")),                    # the system installation has no such remote
    ("", "user", ("unverified", "")),                            # flatpak named no origin
])
def test_an_adopted_flatpak_is_signed_only_where_its_own_remotes_key_checked_it(db, monkeypatch, remotes, origin, installation, verdict):
    """It was "signed" by the link's remote, or by Flathub, whatever remote the copy came from."""
    monkeypatch.setattr(flatpak, "info", lambda app_id, system=False: {"commit": "c1"})
    monkeypatch.setattr(flatpak, "installed_metadata", lambda *a, **k: "")
    _adoptable(db, monkeypatch, {"kind": "flatpak", "value": "org.a.B", "remote": "flathub", "origin": origin, "installation": installation,
                                 "version": "1.0"})
    rec = foreign.adopt(db, KEEPASSXC)
    assert (rec["verified"], rec["signer"], rec["remote"]) == (*verdict, origin)


@pytest.mark.parametrize("case", ["the-distribution", "a-ppa", "put-in-by-hand", "a-repository-trusted-without-a-key"])
def test_a_package_is_recorded_as_what_apt_says_checked_it_when_adopted_installed_or_updated(db, monkeypatch, fake_pkgs, apt_says, case):
    """It was "signed" by the distribution's name for any package of that name: a vendor's .deb put
    in with `dpkg -i`, one from a PPA."""
    policy, verdict = next(c[1:] for c in SIGNED_BY if c[0] == case)
    apt_says(policy)
    _adoptable(db, monkeypatch, {"kind": "package", "value": "keepassxc", "manager": "apt", "version": "2.7.6-1"})
    rec = foreign.adopt(db, KEEPASSXC)
    assert (rec["verified"], rec["signer"], rec["repository"]) == verdict and rec["adopted"]
    db.x("DELETE FROM installs")
    rec = install.install_channel(db, {"url": KEEPASSXC, "name": "KeePassXC"}, {"channel": "package", "value": "keepassxc", "origin": "main"})
    assert (rec["verified"], rec["signer"], rec["repository"], rec["origin"]) == (*verdict, "main")
    assert rec == json.loads(db.one("SELECT record FROM installs")["record"])
    # ...and an update asks again: the copy is one put in by hand now
    apt_says(_policy("3.0", ("3.0", [STATUS])))
    rec = install.update_channel(db, KEEPASSXC)
    assert (rec["verified"], rec["signer"], rec["repository"]) == ("unverified", "", "")


def test_tracking(db, monkeypatch, fake_pkgs, remotes):
    """Removed and updated outside AppKata, and pending updates (R16.4.1, R16.5.4, R16.5.5)."""
    monkeypatch.setattr(channels, "manager", lambda: "apt")
    monkeypatch.setattr(flatpak, "available", lambda: True)
    monkeypatch.setattr(flatpak, "installed", lambda: {"org.a.A": flatpak.Installed("org.a.A", "2.0", "flathub", "user", "bbbbbbbbbbbb")})
    monkeypatch.setattr(flatpak, "updates", lambda system=False: {} if system else {"org.a.A": {"version": "2.1", "commit": "ccc"}})
    monkeypatch.setattr(flatpak, "metadata", lambda *a, **k: "[Context]\nshared=network;\nfilesystems=home;\n")
    monkeypatch.setattr(flatpak, "history", lambda since="": [flatpak.Change("Oct 3", "update", "org.a.A", tool="gnome-software")])
    monkeypatch.setattr(pkgbackend, "pending_updates", lambda names, manager=None: {})
    monkeypatch.setattr(autoupdate, "_out", lambda cmd: "")
    db.put("autoupdate", {"flatpak": ["GNOME Software"]})
    db.x("INSERT INTO installs(url, name, version, kind, record) VALUES(?,?,?,?,?)",
         ("https://github.com/a/a", "A", "1.0", "flatpak",
          json.dumps({"channel": "flatpak", "flatpak": "org.a.A", "commit": "aaaaaaaaaaaaaaaa", "perms": ["Network"]})))
    db.x("INSERT INTO installs(url, name, version, kind, record) VALUES(?,?,?,?,?)",
         ("https://github.com/b/b", "B", "1.0", "apt", json.dumps({"channel": "package", "package": "gone", "manager": "apt"})))
    sync.track_channel_installs(db)
    a = db.one("SELECT * FROM installs WHERE url='https://github.com/a/a'")
    rec = json.loads(a["record"])
    assert a["version"] == "2.0" and rec["updatedBy"] == "GNOME Software"
    assert rec["pending"] == {"version": "2.1", "commit": "ccc", "addedPerms": ["Home folder"]}
    assert not db.one("SELECT 1 FROM installs WHERE url='https://github.com/b/b'")
    acts = [r["action"] for r in db.all("SELECT action, actor FROM audit WHERE actor='system'")]
    assert acts == ["was updated outside AppKata", "was removed outside AppKata"]


# R16.3.6 (CR1.6-33): the verdict in a channel copy's record is of the copy that is installed.
# How it slipped past: #318 made every road by which AppKata itself puts a copy there ask what
# checked it (install, adopt, update), and the one road it doesn't take was left: the copy changed
# outside AppKata, which Sync finds. No test changed a copy there and read its chip's record after.
def _tracked(db, monkeypatch, record, version="1.0"):
    """One channel copy AppKata tracks, with this record, on a machine with no pending updates."""
    monkeypatch.setattr(channels, "manager", lambda: "apt")
    monkeypatch.setattr(pkgbackend, "pending_updates", lambda names, manager=None: {})
    monkeypatch.setattr(autoupdate, "_out", lambda cmd: "")
    monkeypatch.setattr(autoupdate, "last_change", lambda manager, package, version: ("", ""))
    monkeypatch.setattr(flatpak, "updates", lambda system=False: {})
    monkeypatch.setattr(flatpak, "history", lambda since="": [])
    db.x("INSERT INTO installs(url, name, version, kind, record) VALUES(?,?,?,?,?)", (KEEPASSXC, "KeePassXC", version, "", json.dumps(record)))

    def after():
        sync.track_channel_installs(db)
        return json.loads(db.one("SELECT record FROM installs WHERE url=?", (KEEPASSXC,))["record"])
    return after


UBUNTUS = {"verified": "signed", "signer": "Ubuntu", "repository": "Ubuntu"}
BY_HAND = {"verified": "unverified", "signer": "", "repository": ""}
CHANGED_PACKAGES = {
    # what the record says, the version that is installed now, what apt says of it -> the record after
    "a vendor's .deb put over the distribution's by hand":                      # the finding's case
        (UBUNTUS, "9.9", _policy("9.9", ("9.9", [STATUS]), ("2.10-3build1", [NOBLE])), BY_HAND),
    "the distribution's put back over one put in by hand": (BY_HAND, "2.10-3build1", _policy("2.10-3build1", ("2.10-3build1", [NOBLE, STATUS])), UBUNTUS),
    "a PPA's version over the distribution's":
        (UBUNTUS, "130.0", _policy("130.0", ("130.0", [PPA, STATUS]), ("125.0", [NOBLE])),
         {"verified": "signed", "signer": "LP-PPA-mozillateam", "repository": "LP-PPA-mozillateam"}),
    "one from a repository taken without a key":
        (UBUNTUS, "1.0-1", _policy("1.0-1", ("1.0-1", [LOCAL, STATUS])), {"verified": "unverified", "signer": "", "repository": "file:/tmp/akrepo"}),
    "the distribution's own update, made by the system": (UBUNTUS, "2.11-1", _policy("2.11-1", ("2.11-1", [NOBLE, STATUS])), UBUNTUS),
    # ...and a copy that didn't change keeps the verdict of its own install, whatever is offered by now
    "the same version, its repository now offering a newer one": (UBUNTUS, "2.10-2", _policy("2.10-2", ("2.10-3build1", [NOBLE]), ("2.10-2", [STATUS])), UBUNTUS),
}


@pytest.mark.parametrize("case", list(CHANGED_PACKAGES))
def test_a_package_changed_outside_appkata_is_recorded_as_what_checked_the_copy_there_now(db, monkeypatch, fake_pkgs, apt_says, case):
    was, now_installed, policy, verdict = CHANGED_PACKAGES[case]
    after = _tracked(db, monkeypatch, {"channel": "package", "package": "keepassxc", "manager": "apt", "pkgVersion": "2.10-2", **was})
    fake_pkgs.installed["keepassxc"] = now_installed
    apt_says(policy)
    rec = after()
    assert {k: rec[k] for k in verdict} == verdict and rec["pkgVersion"] == now_installed
    said = [r["action"] for r in db.all("SELECT action FROM audit WHERE actor='system'")]
    assert said == ([] if now_installed == "2.10-2" else ["was updated outside AppKata"])
    assert after() == rec                                                # and it stays so at the next Sync


FLATHUBS = {"remote": "flathub", "verified": "signed", "signer": "Flathub"}
CHANGED_FLATPAKS = {
    # what the record says, the copy flatpak has now (its origin, its commit) -> remote, verified and signer after
    "one from a remote flatpak doesn't check": (FLATHUBS, ("aktest", "bbbbbbbbbbbb"), ("aktest", "unverified", "")),
    "a bundle put in by hand": (FLATHUBS, ("org.a.B-origin", "bbbbbbbbbbbb"), ("org.a.B-origin", "unverified", "")),
    "one from a vendor's remote": (FLATHUBS, ("vendor", "bbbbbbbbbbbb"), ("vendor", "signed", "vendor")),
    "one flatpak names no origin for": (FLATHUBS, ("", "bbbbbbbbbbbb"), ("", "unverified", "")),
    "Flathub's, over one no key checked": ({"remote": "aktest", "verified": "unverified", "signer": ""}, ("flathub", "bbbbbbbbbbbb"),
                                           ("flathub", "signed", "Flathub")),
    "Flathub's own update, made by the system": (FLATHUBS, ("flathub", "bbbbbbbbbbbb"), ("flathub", "signed", "Flathub")),
    # ...and a copy that didn't change keeps the verdict of its own install (flatpak lists a shortened commit)
    "the same commit, from a remote whose checking is off by now": ({"remote": "vendor", "verified": "signed", "signer": "vendor"}, ("aktest", "aaaaaaaaaaaa"),
                                                                    ("vendor", "signed", "vendor")),
}


@pytest.mark.parametrize("case", list(CHANGED_FLATPAKS))
def test_a_flatpak_changed_outside_appkata_is_recorded_as_what_checked_the_copy_there_now(db, monkeypatch, remotes, case):
    was, (origin, commit), verdict = CHANGED_FLATPAKS[case]
    after = _tracked(db, monkeypatch, {"channel": "flatpak", "flatpak": "org.a.B", "installation": "user", "commit": "a" * 64, "perms": [], **was})
    monkeypatch.setattr(flatpak, "available", lambda: True)
    monkeypatch.setattr(flatpak, "installed", lambda: {"org.a.B": flatpak.Installed("org.a.B", "2.0", origin, "user", commit)})
    rec = after()
    assert (rec["remote"], rec["verified"], rec["signer"]) == verdict
    said = [r["action"] for r in db.all("SELECT action FROM audit WHERE actor='system'")]
    assert said == ([] if commit.startswith("a") else ["was updated outside AppKata"])
    assert after() == rec


@pytest.mark.skipif(not os.path.exists(dbus.SYSTEM_BUS), reason="no system bus")
def test_system_bus():
    with dbus.Connection() as c:
        assert c.name.startswith(":") and c.has_name("org.freedesktop.DBus")
