#!/usr/bin/env python3
"""Package channels end to end (R16), run as root inside a disposable container by
scripts/test-channels.sh. Uses local repositories only (an apt or rpm repository it builds, and a
Flatpak remote with a tiny runtime and app), plus one signed distribution package for adopting.
Usage: channels_e2e.py --manager apt|dnf [--pkg hello] [--packagekit] [--no-flatpak]"""

import argparse
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, "/src/src")
os.environ.setdefault("APPKATA_DATA", tempfile.mkdtemp())

from appkata_core import autoupdate, channels, flatpak, foreign, install, pkgbackend, sync  # noqa: E402
from appkata_core.db import DB  # noqa: E402
from appkata_core.forges import Asset  # noqa: E402

FAIL = []


def sh(cmd: str, check: bool = True) -> str:
    p = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if check and p.returncode:
        raise SystemExit(f"$ {cmd}\n{p.stdout}\n{p.stderr}")
    return p.stdout


def ok(what: str, cond: bool, detail="") -> None:
    print(("  ok   " if cond else "  FAIL ") + what + (f"  ({detail})" if detail and not cond else ""), flush=True)
    if not cond:
        FAIL.append(what)


def app(db: DB, name: str, settings: dict) -> dict:
    url = f"https://github.com/appkata-test/{name}"
    db.x("INSERT OR REPLACE INTO apps(url, name, repo) VALUES(?,?,?)", (url, name, f"appkata-test/{name}"))
    db.x("INSERT OR REPLACE INTO sources(url, settings) VALUES(?,?)", (url, json.dumps(settings)))
    return {"url": url, "name": name}


# ---------------------------------------------------------------- a local package repository
def deb(repo: str, name: str, version: str, depends: str = "", postinst: str = "") -> None:
    d = tempfile.mkdtemp()
    os.makedirs(f"{d}/DEBIAN")
    os.makedirs(f"{d}/usr/share/doc/{name}")
    if postinst:
        with open(f"{d}/DEBIAN/postinst", "w") as f:
            f.write(f"#!/bin/sh\n{postinst}\n")
        os.chmod(f"{d}/DEBIAN/postinst", 0o755)
    with open(f"{d}/DEBIAN/control", "w") as f:
        f.write(f"Package: {name}\nVersion: {version}\nArchitecture: all\nMaintainer: t <t@t>\n"
                f"Description: AppKata test package\n" + (f"Depends: {depends}\n" if depends else ""))
    with open(f"{d}/usr/share/doc/{name}/README", "w") as f:
        f.write(version)
    sh(f"dpkg-deb --build {d} {repo}/{name}_{version}_all.deb >/dev/null")


def apt_repo_refresh(repo: str) -> None:
    sh(f"cd {repo} && apt-ftparchive packages . > Packages && apt-get update -qq -o Dir::Etc::sourcelist=/etc/apt/sources.list.d/akrepo.list -o Dir::Etc::sourceparts=- -o APT::Get::List-Cleanup=0")


def rpm(repo: str, name: str, version: str, requires: str = "") -> None:
    top = tempfile.mkdtemp()
    spec = f"{top}/{name}.spec"
    with open(spec, "w") as f:
        f.write(f"Name: {name}\nVersion: {version}\nRelease: 1\nSummary: AppKata test package\nLicense: MIT\nBuildArch: noarch\n"
                + (f"Requires: {requires}\n" if requires else "") +
                f"%description\nAppKata test package\n%install\nmkdir -p %{{buildroot}}/usr/share/doc/{name}\n"
                f"echo {version} > %{{buildroot}}/usr/share/doc/{name}/README\n%files\n/usr/share/doc/{name}/README\n")
    sh(f"rpmbuild -bb --define '_topdir {top}' {spec} >/dev/null 2>&1 && cp {top}/RPMS/noarch/*.rpm {repo}/")


def rpm_repo_refresh(repo: str) -> None:
    sh(f"createrepo_c -q --update {repo} && dnf -q makecache --refresh >/dev/null 2>&1 || true")


# ---------------------------------------------------------------- packages
def packages(db: DB, mgr: str, distro_pkg: str, local: bool) -> None:
    be = pkgbackend.backend()
    print(f"== packages: {mgr} through {be.name}", flush=True)
    if local:
        repo = "/tmp/akrepo"
        os.makedirs(repo, exist_ok=True)
        if mgr == "apt":
            with open("/etc/apt/sources.list.d/akrepo.list", "w") as f:
                f.write(f"deb [trusted=yes] file:{repo} ./\n")
            deb(repo, "akdemo", "1.0-1")
            apt_repo_refresh(repo)
        else:
            with open("/etc/yum.repos.d/akrepo.repo", "w") as f:
                f.write(f"[akrepo]\nname=akrepo\nbaseurl=file://{repo}\ngpgcheck=0\nenabled=1\nmetadata_expire=0\n")
            rpm(repo, "akdemo", "1.0")
            rpm_repo_refresh(repo)
        a = app(db, "akdemo", {"package": "akdemo"})
        found = channels.links(db, a["url"], None, mgr)
        ok("Source settings link the package (R16.1.3)", found.get("package") and found["package"].value == "akdemo")
        opts = channels.options(db, a["url"], [], found)
        ok("a package card", opts and opts[0]["channel"] == "package")
        rec = install.install_channel(db, a, opts[0])
        row = db.one("SELECT * FROM installs WHERE url=?", (a["url"],))
        ok("installed through the channel (R16.3.5)", row and row["version"] == "1.0" and rec["manager"] == mgr, row)
        # this repository is taken without a key ([trusted=yes], gpgcheck=0): no key checked the package
        ok("a package of a repository trusted without a key isn't Verified (R16.3.6)",
           rec["verified"] == "unverified" and rec["repository"] == (f"file:{repo}" if mgr == "apt" else "akrepo"), rec)
        if mgr == "apt":
            # ...however its entry says so: the answer is this apt's own, not AppKata's reading of the entry
            for option in ("trusted=true", "trusted=1", "trusted=on", "allow-insecure=yes", "trusted=yes"):
                with open("/etc/apt/sources.list.d/akrepo.list", "w") as f:
                    f.write(f"deb [{option}] file:{repo} ./\n")
                apt_repo_refresh(repo)
                v = pkgbackend.signed_by("akdemo", mgr)
                ok(f"nor one taken with [{option}]", (v["verified"], v["repository"]) == ("unverified", f"file:{repo}"), v)
        # a newer version appears in the repository
        if mgr == "apt":
            deb(repo, "akdemo", "2.0-1")
            apt_repo_refresh(repo)
        else:
            rpm(repo, "akdemo", "2.0")
            rpm_repo_refresh(repo)
        pend = pkgbackend.pending_updates(["akdemo"], mgr)
        ok("the pending update is found without root (R16.5.5)", "akdemo" in pend, pend)
        sync.track_channel_installs(db)
        rec = json.loads(db.one("SELECT record FROM installs WHERE url=?", (a["url"],))["record"])
        ok("the sync records it as pending", rec.get("pending", {}).get("projectVersion") == "2.0", rec.get("pending"))
        rec = install.update_channel(db, a["url"])
        ok("updated (R16.5.5)", db.one("SELECT version FROM installs WHERE url=?", (a["url"],))["version"] == "2.0")
        ok("and still not Verified after its update", rec["verified"] == "unverified", rec)
        # a desktop metapackage that depends on it: uninstalling is refused (R16.4.3)
        meta = "task-akdemo-desktop"
        if mgr == "apt":
            deb(repo, meta, "1.0", "akdemo")
            apt_repo_refresh(repo)
            sh(f"DEBIAN_FRONTEND=noninteractive apt-get install -y -qq {meta} >/dev/null")
        else:
            rpm(repo, meta, "1.0", "akdemo")
            rpm_repo_refresh(repo)
            sh(f"dnf -y -q install {meta} >/dev/null")
        try:
            install.uninstall(db, a["url"])
            ok("removing it with a desktop metapackage is refused", False, "it was removed")
        except pkgbackend.Refused as e:         # as a refusal, which the plan dialog shows, and no plain install error
            ok("removing it with a desktop metapackage is refused", "needs" in str(e).lower() or "metapackage" in str(e), e)
        except install.InstallError as e:
            ok("removing it with a desktop metapackage is refused", False, f"as a plain install error: {e}")
        ok("and the package is still installed", bool(pkgbackend.installed_version("akdemo", mgr)))
        sh(f"{'apt-get remove -y -qq' if mgr == 'apt' else 'dnf -y -q remove --noautoremove'} {meta} >/dev/null")
        # a dependent package that isn't special: confirmation first
        dep = "akdemo-plugins"
        if mgr == "apt":
            deb(repo, dep, "1.0", "akdemo")
            apt_repo_refresh(repo)
            sh(f"DEBIAN_FRONTEND=noninteractive apt-get install -y -qq {dep} >/dev/null")
        else:
            rpm(repo, dep, "1.0", "akdemo")
            rpm_repo_refresh(repo)
            sh(f"dnf -y -q install {dep} >/dev/null")
        try:
            install.uninstall(db, a["url"])
            ok("a removal that takes others asks first", False)
        except pkgbackend.NeedsConfirmation as e:
            ok("a removal that takes others asks first", any(dep in l for l in e.lines), e.lines)
        install.uninstall(db, a["url"], confirmed=True)
        ok("uninstalled after confirming", not pkgbackend.installed_version("akdemo", mgr) and
           not db.one("SELECT 1 FROM installs WHERE url=?", (a["url"],)))
        # busy package manager (R16.8.3)
        lockf = pkgbackend.APT_LOCKS[0] if mgr == "apt" else pkgbackend.RPM_LOCKS[0]
        if os.path.exists(lockf) or mgr == "apt":
            holder = subprocess.Popen(["flock", lockf, "sleep", "4"])
            time.sleep(0.5)
            seen = []
            pkgbackend.wait_for_lock([lockf], on_wait=seen.append, limit=30)
            holder.wait()
            ok("waits while another program holds the lock, and names it", seen and seen[0] == "flock", seen)
    # adopting a signed distribution package installed by hand (R16.4.2)
    sh(f"{'DEBIAN_FRONTEND=noninteractive apt-get install -y -qq' if mgr == 'apt' else 'dnf -y -q install'} {distro_pkg} >/dev/null")
    b = app(db, distro_pkg, {"package": distro_pkg})
    foreign.scan(db)
    row = db.one("SELECT * FROM foreign_installs WHERE url=?", (b["url"],))
    ok("found as adoptable (R16.4.2)", row and row.get("adopt"), row)
    if row and row.get("adopt"):
        rec = foreign.adopt(db, b["url"])
        ok("adopted", db.one("SELECT 1 FROM installs WHERE url=?", (b["url"],)) is not None)
        ok("the distribution's key checked it: Verified, signed by its repository (R16.3.6)",
           rec["verified"] == "signed" and rec["signer"] in ("Ubuntu", "Debian", "Fedora Project", "Rocky Enterprise Software Foundation"), rec)
        install.uninstall(db, b["url"])
        ok("adopted package uninstalled", not pkgbackend.installed_version(distro_pkg, mgr))
    # and installing it through the channel
    rec = install.install_channel(db, b, {"channel": "package", "value": distro_pkg})
    ok(f"{distro_pkg} installed from the distribution", bool(pkgbackend.installed_version(distro_pkg, mgr)))
    ok("Verified, signed by its repository", rec["verified"] == "signed" and rec["signer"], rec)
    if mgr == "apt":
        # the same package put in by hand over the distribution's (`dpkg -i`), under AppKata's
        # record of the Verified one: the next sync finds another copy there, which no key checked
        byhand = tempfile.mkdtemp()
        deb(byhand, distro_pkg, "99.0-1")
        sh(f"dpkg -i {byhand}/{distro_pkg}_99.0-1_all.deb >/dev/null")
        sync.track_channel_installs(db)
        rec = json.loads(db.one("SELECT record FROM installs WHERE url=?", (b["url"],))["record"])
        ok("a package replaced by hand outside AppKata is no longer Verified after a sync (R16.3.6)",
           (rec["verified"], rec["signer"], rec["repository"], rec["pkgVersion"]) == ("unverified", "", "", "99.0-1"), rec)
        # ...and no repository offers that version, so adopting it finds no key that checked it
        install.uninstall(db, b["url"])
        sh(f"dpkg -i {byhand}/{distro_pkg}_99.0-1_all.deb >/dev/null")
        foreign.scan(db)
        rec = foreign.adopt(db, b["url"])
        ok("a package put in by hand is adopted as not Verified (R16.3.6)",
           (rec["verified"], rec["signer"], rec["repository"], rec["pkgVersion"]) == ("unverified", "", "", "99.0-1"), rec)
    install.uninstall(db, b["url"])
    ok(f"{distro_pkg} uninstalled", not pkgbackend.installed_version(distro_pkg, mgr))


# ---------------------------------------------------------------- a release's own package file (R4.4, R16.8.5)
RAN_AS_ROOT = "/tmp/akfile-ran-as-root"          # what the other package's script would leave
POLKIT_RULE = "/etc/polkit-1/rules.d/00-appkata-e2e.rules"
USER = "akuser"


def serve(folder: str) -> str:
    """A web server on this machine for a "release": its address."""
    import functools
    import http.server
    import threading

    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=folder))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{httpd.server_address[1]}"


def other_package() -> str:
    """Another akfile, whose script runs as root when it is installed: what a program of the user's
    would put where the downloaded file was."""
    d = tempfile.mkdtemp()
    os.chmod(d, 0o755)
    deb(d, "akfile", "6.6-6", postinst=f"touch {RAN_AS_ROOT}")
    return f"{d}/akfile_6.6-6_all.deb"


def release_file(db: DB, mgr: str, other: str) -> None:
    """A release's .deb, installed by whoever runs this: root, or a user through the real pkexec."""
    root = os.geteuid() == 0
    print(f"== a release's package file, as {'root' if root else 'a user, through pkexec'}", flush=True)
    rel = tempfile.mkdtemp()
    deb(rel, "akfile", "1.0-1")
    a = {**app(db, "akfile", {}), "installVersion": "1.0", "version": "1.0"}
    base = serve(rel)
    asset = Asset("akfile_1.0-1_all.deb", base + "/akfile_1.0-1_all.deb")
    asked, transaction = [], pkgbackend.PkTransport.transaction
    pkgbackend.PkTransport.transaction = lambda self, method, *args, **kw: asked.append(method) or transaction(self, method, *args, **kw)

    def left():
        return glob.glob(f"{pkgbackend.STAGING}/appkata-install.*")
    rec = install.install(db, a, asset, "deb", [asset])
    ok("installed, from the copy only root can change (R16.8.5)",
       pkgbackend.installed_version("akfile", mgr) == "1.0-1" and (rec["package"], rec["manager"]) == ("akfile", mgr), rec)
    ok("the copy's folder is gone, and this user couldn't have made or changed it",
       not left() and (root or not os.access(pkgbackend.STAGING, os.W_OK)), left())
    # an update from the release's next file upgrades the app's own package: nothing to confirm
    deb(rel, "akfile", "2.0-1")
    newer = Asset("akfile_2.0-1_all.deb", base + "/akfile_2.0-1_all.deb")
    try:
        install.install(db, {**a, "installVersion": "2.0", "version": "2.0"}, newer, "deb", [newer])
        ok("updated from the release's next file, with nothing to confirm (R16.3.5)", pkgbackend.installed_version("akfile", mgr) == "2.0-1")
    except pkgbackend.NeedsConfirmation as e:
        ok("updated from the release's next file, with nothing to confirm (R16.3.5)", False, e.lines)
    ok("PackageKit was never handed the file", "InstallFiles" not in asked, asked)
    install.uninstall(db, a["url"])
    ok("uninstalled", not pkgbackend.installed_version("akfile", mgr))
    # the file is swapped after AppKata's check, as a program of the user's could: here after the dry
    # run, before the command that runs as root reads it
    simulate = pkgbackend.Cli.simulate

    def swapping(self, action, names):
        plan = simulate(self, action, names)
        if action == "install" and os.path.sep in names[0]:
            shutil.copy(other, names[0])
        return plan
    pkgbackend.Cli.simulate = swapping
    try:
        install.install(db, a, asset, "deb", [asset])
        ok("a file swapped after its check is refused on the administrator's side (R4.4)", False, "it was installed")
    except install.InstallError as e:
        ok("a file swapped after its check is refused on the administrator's side (R4.4)", str(e) == pkgbackend.CHANGED_TEXT, e)
    finally:
        pkgbackend.Cli.simulate, pkgbackend.PkTransport.transaction = simulate, transaction
    ok("nothing of the other file was installed, and its script never ran",
       not pkgbackend.installed_version("akfile", mgr) and not os.path.exists(RAN_AS_ROOT) and not left(),
       (pkgbackend.installed_version("akfile", mgr), os.path.exists(RAN_AS_ROOT), left()))


def release_file_as_a_user(mgr: str, other: str) -> None:
    """The same through the real pkexec: as a user with none of root's rights, whom polkit is told
    to let through without the password no test can type."""
    sh("DEBIAN_FRONTEND=noninteractive apt-get install -y -qq polkitd pkexec dbus >/dev/null 2>&1")
    os.makedirs("/run/dbus", exist_ok=True)
    if not os.path.exists("/run/dbus/system_bus_socket"):
        sh("dbus-daemon --system --fork")
    os.makedirs(os.path.dirname(POLKIT_RULE), exist_ok=True)
    with open(POLKIT_RULE, "w") as f:
        f.write(f'polkit.addRule(function(action, subject) {{ if (subject.user == "{USER}") {{ return polkit.Result.YES; }} }});\n')
    polkitd = subprocess.Popen(["/usr/lib/polkit-1/polkitd", "--no-debug"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(2)
        sh(f"id {USER} >/dev/null 2>&1 || useradd -m {USER}")
        p = subprocess.run(["runuser", "-u", USER, "--", "env", "-u", "APPKATA_DATA", f"HOME=/home/{USER}", sys.executable,
                            os.path.abspath(__file__), "--manager", mgr, "--release-file-as-user", other], capture_output=True, text=True)
        print(p.stdout, end="", flush=True)
        ok("as a user, through the real pkexec", p.returncode == 0 and "FAIL" not in p.stdout, (p.stdout + p.stderr)[-2000:])
    finally:
        polkitd.terminate()
        os.remove(POLKIT_RULE)


# ---------------------------------------------------------------- Flatpak
def build_flatpaks(repo: str, version: int) -> None:
    w = tempfile.mkdtemp()
    if version == 1:
        # a runtime's build folder by hand: build-init would need an SDK installed already
        arch = sh("flatpak --default-arch").strip()
        os.makedirs(f"{w}/rt/usr/bin"); os.makedirs(f"{w}/rt/files")
        shutil.copy("/bin/true", f"{w}/rt/usr/bin/true")
        with open(f"{w}/rt/metadata", "w") as f:
            f.write(f"[Runtime]\nname=org.appkata.Platform\nruntime=org.appkata.Platform/{arch}/1\n"
                    f"sdk=org.appkata.Platform/{arch}/1\n")
        sh(f"flatpak build-export --runtime {repo} {w}/rt 1 >/dev/null")
        sh(f"flatpak remote-add --user --no-gpg-verify --if-not-exists aktest {repo}")
        sh("flatpak install --user -y --noninteractive aktest org.appkata.Platform//1 >/dev/null")
    sh(f"flatpak build-init {w}/app org.appkata.Hello org.appkata.Platform org.appkata.Platform 1 >/dev/null")
    os.makedirs(f"{w}/app/files/bin")
    with open(f"{w}/app/files/bin/hello", "w") as f:
        f.write(f"#!/bin/sh\necho {version}\n")
    os.chmod(f"{w}/app/files/bin/hello", 0o755)
    perms = "--share=network" + (" --filesystem=home" if version > 1 else "")
    sh(f"flatpak build-finish {w}/app --command=hello {perms} >/dev/null")
    sh(f"flatpak build-export {repo} {w}/app stable >/dev/null")
    sh("flatpak update --user --appstream aktest >/dev/null 2>&1", check=False)


def flatpaks(db: DB) -> None:
    print("== flatpak", flush=True)
    repo = "/tmp/fprepo"
    build_flatpaks(repo, 1)
    a = app(db, "Hello", {"flatpak": "aktest org.appkata.Hello"})
    found = channels.links(db, a["url"], None, "")
    ok("Source settings link the Flatpak with its remote", found.get("flatpak") and found["flatpak"].remote == "aktest")
    rec = install.install_channel(db, a, {"channel": "flatpak", "value": "org.appkata.Hello", "remote": "aktest"})
    ok("installed per user (R16.3.4)", "org.appkata.Hello" in flatpak.installed() and rec["perms"] == ["Network"], rec)
    # aktest was added with --no-gpg-verify: flatpak checked this copy against no key
    ok("a Flatpak from a remote with signature checking off isn't Verified (R16.3.6)",
       (rec["verified"], rec["signer"]) == ("unverified", "") and not flatpak.checks_signatures("aktest"), rec)
    first = rec["commit"]
    build_flatpaks(repo, 2)
    sync.track_channel_installs(db)
    rec = json.loads(db.one("SELECT record FROM installs WHERE url=?", (a["url"],))["record"])
    ok("a new build is pending, asking for more (R16.6.3)", rec.get("pending", {}).get("addedPerms") == ["Home folder"],
       rec.get("pending"))
    rec = install.update_channel(db, a["url"])
    ok("updated to the new build", rec["commit"] != first and "Home folder" in rec["perms"], rec)
    log = flatpak.history_log("org.appkata.Hello", "aktest")
    ok("its versions come from the remote's log (R16.5.7)", len(log) >= 2, log)
    install.set_pinned(db, a["url"], True)
    ok("pinned with flatpak mask (R16.5.6)", "org.appkata.Hello" in sh("flatpak mask --user"))
    install.set_pinned(db, a["url"], False)
    ok("unpinned", "org.appkata.Hello" not in sh("flatpak mask --user"))
    # updated outside AppKata (R16.5.4): an older commit deployed by hand counts as a change
    sh(f"flatpak update --user -y --noninteractive --commit={first} org.appkata.Hello >/dev/null")
    sync.track_channel_installs(db)
    ok("a change made elsewhere is in the Audit (actor System)",
       db.one("SELECT 1 FROM audit WHERE actor='system' AND action='was updated outside AppKata'") is not None)
    install.uninstall(db, a["url"])
    ok("uninstalled", "org.appkata.Hello" not in flatpak.installed())
    # adopting a Flatpak installed by hand
    sh("flatpak install --user -y --noninteractive aktest org.appkata.Hello >/dev/null")
    foreign.scan(db)
    row = db.one("SELECT * FROM foreign_installs WHERE url=?", (a["url"],))
    ok("found as adoptable", row and row.get("adopt"), row)
    if row and row.get("adopt"):
        rec = foreign.adopt(db, a["url"])
        ok("adopted from the remote it came from, and not Verified", (rec["remote"], rec["verified"]) == ("aktest", "unverified"), rec)
        install.uninstall(db, a["url"])
        ok("adopted and uninstalled", "org.appkata.Hello" not in flatpak.installed())
    sh("flatpak uninstall --user -y --noninteractive --all >/dev/null 2>&1", check=False)


def detection(mgr: str) -> None:
    print("== automatic updates", flush=True)
    d = autoupdate.detect()
    ok("detection runs", isinstance(d, autoupdate.Detection))
    if mgr == "apt":
        with open("/etc/apt/apt.conf.d/20auto-upgrades", "w") as f:
            f.write('APT::Periodic::Unattended-Upgrade "1";\n')
        on, origins = autoupdate.parse_apt_config(sh("apt-config dump"))
        ok("unattended-upgrades seen as on", on)
        os.remove("/etc/apt/apt.conf.d/20auto-upgrades")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manager", required=True)
    ap.add_argument("--pkg", default="hello")
    ap.add_argument("--packagekit", action="store_true")
    ap.add_argument("--no-flatpak", action="store_true")
    ap.add_argument("--no-local", action="store_true")
    ap.add_argument("--release-file-as-user", default="", help=argparse.SUPPRESS)      # release_file_as_a_user()'s own run
    a = ap.parse_args()
    if not a.packagekit:
        os.environ["APPKATA_NO_PACKAGEKIT"] = "1"
    db = DB(os.path.join(os.environ["APPKATA_DATA"], "appkata.db"))
    if a.release_file_as_user:
        release_file(db, a.manager, a.release_file_as_user)
        return 1 if FAIL else 0
    ok("channels are on here", channels.enabled() and channels.manager() == a.manager, channels.manager())
    packages(db, a.manager, a.pkg, not a.no_local)
    if a.manager == "apt":
        other = other_package()
        release_file(db, a.manager, other)
        release_file_as_a_user(a.manager, other)
    if not a.no_flatpak and flatpak.available():
        flatpaks(db)
    detection(a.manager)
    print(f"== {'FAILED: ' + ', '.join(FAIL) if FAIL else 'all passed'}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
