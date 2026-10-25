"""End-to-end check of installing on Windows (requirement 15), run in the test VM by
scripts/test-windows-vm.sh --e2e. Real releases from GitHub, through AppKata's own forge, asset,
install and uninstall code:

  ripgrep       portable .zip, just me: junction, .cmd command link on the PATH
  hyperfine     portable .zip that needs the Visual C++ run-time: flagged, then AppKata installs
                Microsoft's run-time (it stays installed) and the program runs
  WinMerge      Inno Setup installer, just me (/CURRENTUSER): its Uninstall entry under HKCU
  KeePassXC     .msi for everyone, elevated: HKLM entry, Authenticode "Verified"
  MarkText      NSIS by electron-builder, just me (/currentuser)
  Git           Inno Setup for everyone; kept installed (the trust tests need git and its gpg)

Prints one line per check and exits non-zero on the first failure."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
os.environ.setdefault("APPKATA_DATA", os.path.join(tempfile.gettempdir(), "appkata-e2e"))

from appkata_core import forges, install, urls, windows  # noqa: E402
from appkata_core.assets import choose, exe_type  # noqa: E402
from appkata_core.db import DB  # noqa: E402
from appkata_core.http import Http  # noqa: E402
from appkata_core.platform import use_system_certificates  # noqa: E402

use_system_certificates()       # as appkata.exe does

CASES = [
    # name, repo, asset filter (None: AppKata's own choice), scope, expected kind/exe kind, keep installed
    ("ripgrep", "BurntSushi/ripgrep", None, "me", "zip", False),
    ("hyperfine", "sharkdp/hyperfine", r"x86_64-pc-windows-msvc\.zip$", "me", "zip", False),
    ("WinMerge", "WinMerge/winmerge", r"x64-PerUser-Setup\.exe$", "me", "inno", False),
    # its installer was -Win64.msi up to 2.7, -x64.msi from 2.8.0 (2026-10-21), and -ARM64.msi beside it
    ("KeePassXC", "keepassxreboot/keepassxc", r"(?:Win64|x64)\.msi$", "everyone", "msi", False),
    ("MarkText", "marktext/marktext", r"setup.*\.exe$", "me", "electron", False),
    ("Git", "git-for-windows/git", r"^Git-[\d.]+-64-bit\.exe$", "everyone", "inno", True),
]


WINMERGE_SETUP = "https://github.com/WinMerge/winmerge/releases/download/v2.16.58.2/WinMerge-2.16.58.2-x64-PerUser-Setup.exe"


def microsoft_reachable() -> bool:
    import urllib.request
    try:
        urllib.request.urlopen(urllib.request.Request(windows.VC_REDIST_URL, method="HEAD"), timeout=15).close()
        return True
    except OSError:
        return False


def uninstall_after(db, url: str, rec: dict) -> None:
    install.uninstall(db, url)
    check(not os.path.exists(rec["target"]) and not os.path.exists(rec["shims"][0]), "uninstalled: folder and command link gone")


def check(ok: bool, what: str) -> None:
    print(("ok    " if ok else "FAIL  ") + what, flush=True)
    if not ok:
        sys.exit(1)


def main() -> int:
    only = set(sys.argv[1:])
    db = DB(os.path.join(os.environ["APPKATA_DATA"], "appkata.db"))
    http = Http({"github.com": os.environ["GITHUB_TOKEN"]} if os.environ.get("GITHUB_TOKEN") else {})
    for name, repo_path, rx, scope, want, keep in CASES:
        if only and name not in only:
            continue
        print(f"== {name}", flush=True)
        repo = urls.parse(f"https://github.com/{repo_path}")
        rels = forges.forge_for(http, repo, "github").releases(limit=30)
        rel = next((r for r in rels if r.assets and not r.prerelease), None)       # bare tags have no files (requirement 9.4)
        check(rel is not None and bool(rel.assets), f"{name} {rel.version if rel else '?'}: {len(rel.assets) if rel else 0} files")
        ch = choose(rel.assets, "windows", "x86_64", override=rx or "")
        check(ch.asset is not None, f"chose {ch.asset.name if ch.asset else ch.reason}")
        ek = exe_type(ch.asset.name, install.head_bytes(ch.asset.url), [a.name for a in rel.assets]) if ch.kind == "exe" else ""
        check((ek or ch.kind) == want, f"kind {ch.kind} {ek}".strip())
        app = {"url": repo.url, "name": name, "repo": repo_path, "version": rel.version, "installVersion": rel.version,
               "date": rel.date, "exeKind": ek, "summary": ""}
        port = install.Portable(scope=scope, app_menu=True, command_dir=windows.command_dir_default(),
                                folder_everyone=os.path.join(tempfile.gettempdir(), "appkata-e2e-Programs"))
        before = windows.inventory()
        rec = install.install(db, app, ch.asset, ch.kind, rel.assets, portable=port)
        print(f"      installed: verified={rec.get('verified')} signer={rec.get('signer') or '-'} scope={rec.get('scope')}", flush=True)
        if ch.kind == "zip":
            shim = rec["shims"][0]
            if name == "hyperfine":         # requirement 15.18
                check(rec.get("msvcrt") is True, "needs the Visual C++ run-time (MSVCRT)")
                if not windows.msvcrt_installed():
                    out = subprocess.run(["cmd", "/c", shim, "--version"], capture_output=True, text=True)
                    check(out.returncode != 0, f"doesn't start without it (exit {out.returncode:#x})")
                    if microsoft_reachable():
                        meaning = install.install_msvcrt()
                        check(bool(windows.msvcrt_installed()), f"installed Microsoft's run-time ({windows.msvcrt_installed()}, {meaning})")
                    else:
                        # this network can't reach Microsoft: check that only Microsoft's signature is accepted
                        print("      skip: Microsoft's download host isn't reachable from this network", flush=True)
                        real = windows.VC_REDIST_URL
                        windows.VC_REDIST_URL = WINMERGE_SETUP     # signed, but not by Microsoft
                        try:
                            install.install_msvcrt()
                            check(False, "a run-time not signed by Microsoft was refused")
                        except install.InstallError as e:
                            check("isn't signed by Microsoft" in str(e), f"a run-time not signed by Microsoft was refused: {e}")
                        finally:
                            windows.VC_REDIST_URL = real
                        check(not windows.msvcrt_installed(), "nothing was installed")
                        uninstall_after(db, repo.url, rec)
                        continue
            else:
                check(not rec.get("msvcrt"), "doesn't need the Visual C++ run-time")
            out = subprocess.run(["cmd", "/c", shim, "--version"], capture_output=True, text=True)
            check(out.returncode == 0 and name.lower() in out.stdout.lower(), f"command link: {out.stdout.strip()}")
            check(windows.is_junction(os.path.join(rec["target"], "current")), "current is a junction")
        else:
            e = rec.get("entry") or {}
            check(bool(e), f"Uninstall entry {e.get('hive')}\\{e.get('key')}: {e.get('DisplayName')} {e.get('DisplayVersion')}")
            check(rec.get("scope") == scope, f"installed for {rec.get('scope')}")
            if ch.kind == "msi":
                check(rec.get("verified") == "signed", f"Authenticode: signed by {rec.get('signer')}")
            norm = windows._norm(e.get("DisplayName", ""))
            check(norm in windows.inventory(), "seen as installed on this computer" + ("" if norm not in before else " (it was already)"))
        if keep:
            print(f"      kept installed", flush=True)
            continue
        install.uninstall(db, repo.url)
        if ch.kind == "zip":
            check(not os.path.exists(rec["target"]) and not os.path.exists(rec["shims"][0]), "uninstalled: folder and command link gone")
        else:
            check(windows.entry_id(rec["entry"]) not in windows.uninstall_entries(), "uninstalled: entry gone")
    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
