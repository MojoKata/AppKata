#!/usr/bin/env python3
"""Package channels end to end (requirement 16), run as root inside a disposable container by
scripts/test-channels.sh. Uses local repositories only (an apt or rpm repository it builds, and a
Flatpak remote with a tiny runtime and app), plus one signed distribution package for adopting.
Usage: channels_e2e.py --manager apt|dnf [--pkg hello] [--packagekit] [--no-flatpak]"""

import argparse
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
def deb(repo: str, name: str, version: str, depends: str = "") -> None:
    d = tempfile.mkdtemp()
    os.makedirs(f"{d}/DEBIAN")
    os.makedirs(f"{d}/usr/share/doc/{name}")
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
        ok("Source settings link the package (16.1.3)", found.get("package") and found["package"].value == "akdemo")
        opts = channels.options(db, a["url"], [], found)
        ok("a package card", opts and opts[0]["channel"] == "package")
        rec = install.install_channel(db, a, opts[0])
        row = db.one("SELECT * FROM installs WHERE url=?", (a["url"],))
        ok("installed through the channel (16.3.5)", row and row["version"] == "1.0" and rec["manager"] == mgr, row)
        # a newer version appears in the repository
        if mgr == "apt":
            deb(repo, "akdemo", "2.0-1")
            apt_repo_refresh(repo)
        else:
            rpm(repo, "akdemo", "2.0")
            rpm_repo_refresh(repo)
        pend = pkgbackend.pending_updates(["akdemo"], mgr)
        ok("the pending update is found without root (16.5.5)", "akdemo" in pend, pend)
        sync.track_channel_installs(db)
        rec = json.loads(db.one("SELECT record FROM installs WHERE url=?", (a["url"],))["record"])
        ok("the sync records it as pending", rec.get("pending", {}).get("projectVersion") == "2.0", rec.get("pending"))
        install.update_channel(db, a["url"])
        ok("updated (16.5.5)", db.one("SELECT version FROM installs WHERE url=?", (a["url"],))["version"] == "2.0")
        # a desktop metapackage that depends on it: uninstalling is refused (16.4.3)
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
        except install.InstallError as e:
            ok("removing it with a desktop metapackage is refused", "needs" in str(e).lower() or "metapackage" in str(e), e)
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
        # busy package manager (16.8.3)
        lockf = pkgbackend.APT_LOCKS[0] if mgr == "apt" else pkgbackend.RPM_LOCKS[0]
        if os.path.exists(lockf) or mgr == "apt":
            holder = subprocess.Popen(["flock", lockf, "sleep", "4"])
            time.sleep(0.5)
            seen = []
            pkgbackend.wait_for_lock([lockf], on_wait=seen.append, limit=30)
            holder.wait()
            ok("waits while another program holds the lock, and names it", seen and seen[0] == "flock", seen)
    # adopting a signed distribution package installed by hand (16.4.2)
    sh(f"{'DEBIAN_FRONTEND=noninteractive apt-get install -y -qq' if mgr == 'apt' else 'dnf -y -q install'} {distro_pkg} >/dev/null")
    b = app(db, distro_pkg, {"package": distro_pkg})
    foreign.scan(db)
    row = db.one("SELECT * FROM foreign_installs WHERE url=?", (b["url"],))
    ok("found as adoptable (16.4.2)", row and row.get("adopt"), row)
    if row and row.get("adopt"):
        foreign.adopt(db, b["url"])
        ok("adopted", db.one("SELECT 1 FROM installs WHERE url=?", (b["url"],)) is not None)
        install.uninstall(db, b["url"])
        ok("adopted package uninstalled", not pkgbackend.installed_version(distro_pkg, mgr))
    # and installing it through the channel
    rec = install.install_channel(db, b, {"channel": "package", "value": distro_pkg})
    ok(f"{distro_pkg} installed from the distribution", bool(pkgbackend.installed_version(distro_pkg, mgr)))
    install.uninstall(db, b["url"])
    ok(f"{distro_pkg} uninstalled", not pkgbackend.installed_version(distro_pkg, mgr))


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
    ok("installed per user (16.3.4)", "org.appkata.Hello" in flatpak.installed() and rec["perms"] == ["Network"], rec)
    first = rec["commit"]
    build_flatpaks(repo, 2)
    sync.track_channel_installs(db)
    rec = json.loads(db.one("SELECT record FROM installs WHERE url=?", (a["url"],))["record"])
    ok("a new build is pending, asking for more (16.6.3)", rec.get("pending", {}).get("addedPerms") == ["Home folder"],
       rec.get("pending"))
    rec = install.update_channel(db, a["url"])
    ok("updated to the new build", rec["commit"] != first and "Home folder" in rec["perms"], rec)
    log = flatpak.history_log("org.appkata.Hello", "aktest")
    ok("its versions come from the remote's log (16.5.7)", len(log) >= 2, log)
    install.set_pinned(db, a["url"], True)
    ok("pinned with flatpak mask (16.5.6)", "org.appkata.Hello" in sh("flatpak mask --user"))
    install.set_pinned(db, a["url"], False)
    ok("unpinned", "org.appkata.Hello" not in sh("flatpak mask --user"))
    # updated outside AppKata (16.5.4): an older commit deployed by hand counts as a change
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
        foreign.adopt(db, a["url"])
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
    a = ap.parse_args()
    if not a.packagekit:
        os.environ["APPKATA_NO_PACKAGEKIT"] = "1"
    db = DB(os.path.join(os.environ["APPKATA_DATA"], "appkata.db"))
    ok("channels are on here", channels.enabled() and channels.manager() == a.manager, channels.manager())
    packages(db, a.manager, a.pkg, not a.no_local)
    if not a.no_flatpak and flatpak.available():
        flatpaks(db)
    detection(a.manager)
    print(f"== {'FAILED: ' + ', '.join(FAIL) if FAIL else 'all passed'}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
