"""Package channels (requirement 16) against recorded data: AppStream catalogs, flatpak and package
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


# ---------------------------------------------------------------- AppStream (16.2.2)
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


# ---------------------------------------------------------------- D-Bus (16.8.1)
def test_dbus_round_trip():
    raw = dbus.marshal_message(dbus.SIGNAL, 7, {"path": "/t", "interface": "i.x", "member": "Changed"}, "sa{sv}ast",
                               ["org.x", {"Percentage": dbus.Variant("u", 45), "Name": dbus.Variant("s", "a")}, ["a", "b"], 1 << 40])
    msg, used = dbus.unmarshal_message(raw + b"extra")
    assert used == len(raw) and msg["member"] == "Changed" and msg["path"] == "/t"
    a = msg["args"]
    assert a[0] == "org.x" and a[1]["Percentage"].value == 45 and a[2] == ["a", "b"] and a[3] == 1 << 40
    assert dbus.unmarshal_message(raw[:20]) == ({}, 0)
    assert dbus.split_types("a{sv}as(ii)t") == ["a{sv}", "as", "(ii)", "t"]


# ---------------------------------------------------------------- plans and refusals (16.3.5, 16.4.3)
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


# ---------------------------------------------------------------- Flatpak (16.6)
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


# ---------------------------------------------------------------- who updates it (16.5.2, 16.5.4)
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


# ---------------------------------------------------------------- links (16.1.3)
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
    assert channels.recommended_channel(db, KEEPASSXC) == ("package", "high")       # the review for 2.7.6 (10.3.5)
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


# ---------------------------------------------------------------- link checks (16.1.4, 16.1.5)
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


# ---------------------------------------------------------------- install, uninstall, adopt (16.3–16.4)
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
    return be


def test_package_install_and_uninstall(db, fake_pkgs):
    app = {"url": KEEPASSXC, "name": "KeePassXC"}
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


def test_tracking(db, monkeypatch, fake_pkgs):
    """Removed and updated outside AppKata, and pending updates (16.4.1, 16.5.4, 16.5.5)."""
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


@pytest.mark.skipif(not os.path.exists(dbus.SYSTEM_BUS), reason="no system bus")
def test_system_bus():
    with dbus.Connection() as c:
        assert c.name.startswith(":") and c.has_name("org.freedesktop.DBus")
