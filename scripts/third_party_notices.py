#!/usr/bin/env python3
"""The license files the AppImage and the Windows installer carry (the walk thru of 2026-10-30, item 1;
docs/reviews/followups-license-files.md): AppKata's LICENSE as LICENSE.txt, and THIRD-PARTY-NOTICES.txt,
every part the build carries that others made, with its license, the license's text and where its
source is.

    scripts/third_party_notices.py write linux|windows TREE BUILT   both files into TREE (the AppDir, or
                                    the Windows build's folder), where PLACE says, with the texts BUILT
                                    holds from the build's own inputs
    scripts/third_party_notices.py check linux|windows TREE         exit 1 unless TREE carries both, every
                                    library in it belongs to a part the notices give, and every Qt
                                    library to a module of the Qt repositories they list
    scripts/third_party_notices.py refresh                          packaging/licenses/ again from the
                                    sources of the versions the builds pin (the network and Docker; when
                                    a version changes, tests/test_third_party_notices.py asks for it)

BUILT holds the texts that come with a build's own inputs, which the build copies as it runs:
    linux    xcb-util/<package>       the Debian copyright file of each xcb-util library the AppImage copies
    windows  python/LICENSE.txt       the Windows Python's (it adds the libraries that build carries)
             truststore/LICENSE       from truststore's wheel
             pyinstaller/COPYING.txt  from PyInstaller's (the bootloader appkata.exe is)
"""

import glob
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import textwrap
import zipfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
LICENSES = os.path.join(ROOT, "packaging", "licenses")
PLACE = {"linux": "usr/share/licenses/appkata", "windows": ""}
RULE = "#" * 78     # no license text has a line of them (write checks)
SITE = r"^usr/python/lib/python3\.\d+/site-packages/"
QT_LIB = re.compile(r"^(?:lib)?Qt6(\w+?)(?:\.so[.\d]*|\.dll)$")

# Each part a build carries that others made, in the order the notices give them: its key, the
# platforms carrying it, its title, its license in short, and the build's libraries that are its (by
# their paths in the tree; each library is one part's, which check holds the patterns to)
MS = r"(?i:vcruntime140|msvcp140)"
PARTS = [
    ("python", {"linux", "windows"}, "Python {PYTHON}", "PSF-2.0, and the licenses of the libraries it carries",
     [r"^usr/python/(?!lib/python3\.\d+/site-packages/)", rf"^_internal/(?!{MS})[^/]+\.(pyd|dll)$"]),
    ("qt", {"linux", "windows"}, "Qt {PYSIDE}", "LGPL-3.0-only; some modules GPL-3.0-only",
     [SITE + r"PySide6/Qt/(lib/(lib)?Qt6|plugins/(?!designer/libPySidePlugin)|qml/|libexec/)", r"^_internal/PySide6/Qt6\w+\.dll$",
      r"^_internal/PySide6/(plugins|qml)/"]),
    ("pyside", {"linux", "windows"}, "PySide6 and Shiboken6 {PYSIDE}", "LGPL-3.0-only",
     [SITE + r"PySide6/[^/]+$", SITE + r"PySide6/Qt/plugins/designer/libPySidePlugin\.so$", SITE + r"shiboken6/",
      rf"^_internal/PySide6/(?!Qt6\w+\.dll$)(?!{MS})[^/]+$", rf"^_internal/shiboken6/(?!{MS})"]),
    ("icu", {"linux"}, "ICU {ICU}", "Unicode-3.0", [SITE + r"PySide6/Qt/lib/libicu\w+\.so[.\d]*$"]),
    ("xcb", {"linux"}, "xcb-util", "MIT", [SITE + r"PySide6/Qt/lib/libxcb-[\w-]+\.so[.\d]*$"]),
    ("truststore", {"windows"}, "truststore {TRUSTSTORE}", "MIT", []),
    ("pyinstaller", {"windows"}, "PyInstaller's bootloader {PYINSTALLER}", "GPL-2.0-or-later with the bootloader exception",
     [r"^appkata\.exe$"]),
    ("msvc", {"windows"}, "The Microsoft Visual C++ runtime", "Microsoft's Distributable Code", [rf"(^|/){MS}[^/]*\.dll$"]),
]


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _assigned(text, var):
    m = re.search(rf'^\s*: "\${{{var}:=([^}}"\n]*)}}"', text, re.M) or re.search(rf'^\s*{var}="?([^"\s]*)', text, re.M)
    return m.group(1).strip() if m else None


def pins():
    """The versions the builds carry: packaging/versions.env's, build-windows.sh's own, and what
    packaging/licenses/SOURCES says the texts there were made from."""
    env = read(os.path.join(ROOT, "packaging", "versions.env"))
    win = read(os.path.join(ROOT, "scripts", "build-windows.sh"))
    p = {v: _assigned(env, v) for v in ("PY_SERIES", "PYSIDE", "PYTHON_BUILD", "PYWINE_IMAGE")}
    p.update({v: _assigned(win, v) for v in ("TRUSTSTORE", "PYINSTALLER")})
    p["PYTHON"] = p["PYTHON_BUILD"].split("+")[0]
    p["ICU"] = sources().get("ICU", "")
    return p


def sources():
    path = os.path.join(LICENSES, "SOURCES")
    if not os.path.exists(path):
        return {}
    return dict(line.split("=", 1) for line in read(path).splitlines() if line and not line.startswith("#"))


def appkata_version():
    return re.search(r'^__version__ = "(.*)"', read(os.path.join(ROOT, "src", "appkata_core", "__init__.py")), re.M).group(1)


def fill(*paragraphs):
    """The paragraphs the notices write themselves (not the license texts), wrapped for a text viewer."""
    return "\n\n".join(textwrap.fill(p, 100, break_long_words=False, break_on_hyphens=False) for p in paragraphs)


def section(title, body):
    return f"{RULE}\n{title}\n{RULE}\n\n{body.strip()}\n\n"


# ------------------------------------------------------------------------------------------- write

def _built(built, *names):
    for name in names:
        hits = sorted(glob.glob(os.path.join(built, name)))
        if hits:
            return hits
    sys.exit(f"{built} holds no {' or '.join(names)}: the build copies it from its inputs")


def bodies(platform, built):
    p = pins()
    piece = lambda name: read(os.path.join(LICENSES, name))
    b = {"qt": piece("qt.txt"), "pyside": piece("pyside.txt"), "python": piece("python.txt")}
    if platform == "linux":
        b["python"] += "\n" + piece("python-linux.txt")
        b["icu"] = piece("icu.txt")
        xcb = [fill("The xcb-util libraries Qt's X11 support needs, which the AppImage carries (no Debian-family "
                    "desktop installs them): each one's copyright file, as its Ubuntu 22.04 package gives it. Each file's "
                    "Source line says where the library's source code is, and Ubuntu publishes each package's source "
                    "with it (apt-get source <package>).")]
        for path in _built(built, "xcb-util/*"):
            xcb.append(f"--- {os.path.basename(path)} ---\n\n{read(path).strip()}")
        b["xcb"] = "\n\n".join(xcb)
    else:
        lic = read(_built(built, "python/LICENSE.txt")[0])
        at = lic.find("Additional Conditions for this Windows binary build")
        if at < 0:
            sys.exit("the Windows Python's LICENSE.txt has no \"Additional Conditions for this Windows binary build\"")
        b["python"] += ("\n\n" + fill("The Windows build of Python adds these conditions and the licenses of the "
                                     "libraries it carries, from its own LICENSE.txt:") + "\n\n" + lic[at:].strip() + "\n\n" + piece("python-windows.txt"))
        b["msvc"] = piece("msvc-runtime.txt")
        b["truststore"] = (fill(f"truststore {p['TRUSTSTORE']}, which lets AppKata check certificates with Windows' "
                                "own store: https://github.com/sethmlarson/truststore") + "\nSource code: "
                           f"https://github.com/sethmlarson/truststore/tree/v{p['TRUSTSTORE']}\n\n"
                           + read(_built(built, "truststore/LICENSE*")[0]).strip())
        b["pyinstaller"] = (fill(f"appkata.exe is PyInstaller {p['PYINSTALLER']}'s bootloader, which starts "
                                 "AppKata's Python: https://pyinstaller.org. Its license lets it be distributed with any "
                                 "program, under the program's own terms (the bootloader exception, below).")
                            + "\nSource code: "
                            f"https://github.com/pyinstaller/pyinstaller/tree/v{p['PYINSTALLER']}\n\n"
                            + read(_built(built, "pyinstaller/COPYING*")[0]).strip())
    return b


def notices(platform, built):
    p = pins()
    b = bodies(platform, built)
    for key, body in b.items():
        if re.search(rf"^{RULE}$", body, re.M):
            sys.exit(f"the text of {key} has a line like the notices' section rule")
    parts = [(key, title.format(**p), short) for key, plats, title, short, _ in PARTS if platform in plats]
    width = max(len(t) for _, t, _ in parts) + 2
    head = (f"Third-party notices for AppKata {appkata_version()} "
            f"({'the Linux AppImage' if platform == 'linux' else 'Windows'})\n\n"
            + fill("AppKata is free software under the GNU General Public License, version 3 or (at your option) any "
                   "later version: LICENSE.txt, beside this file. Its source code: https://github.com/MojoKata/AppKata",
                   "It carries these parts made by others, each under its own license. Each one's section below gives "
                   "its license and the license's text, and where its source code is.") + "\n\n"
            + "".join(f"  {t:<{width}}{s}\n" for _, t, s in parts) + "\n")
    return head + "".join(section(t, b[key]) for key, t, _ in parts)


def write(platform, tree, built):
    dest = os.path.join(tree, PLACE[platform])
    os.makedirs(dest, exist_ok=True)
    text = notices(platform, built)
    shutil.copyfile(os.path.join(ROOT, "LICENSE"), os.path.join(dest, "LICENSE.txt"))
    with open(os.path.join(dest, "THIRD-PARTY-NOTICES.txt"), "w", encoding="utf-8") as f:
        f.write(text)
    print(f"wrote {os.path.join(PLACE[platform], 'LICENSE.txt')} and THIRD-PARTY-NOTICES.txt ({len(text) // 1024} KB)")


# ------------------------------------------------------------------------------------------- check

def binaries(tree):
    """Every executable and library in tree (ELF or PE), by its path in it."""
    for d, _, files in os.walk(tree):
        for name in files:
            path = os.path.join(d, name)
            if os.path.islink(path) or not os.path.isfile(path):
                continue
            with open(path, "rb") as f:
                magic = f.read(4)
            if magic == b"\x7fELF" or magic[:2] == b"MZ":
                yield os.path.relpath(path, tree).replace(os.sep, "/")


def parts_of(rel, platform):
    """The parts whose patterns take a library: one, unless the patterns are wrong or it is no part's."""
    return [key for key, plats, _, _, patterns in PARTS if platform in plats and any(re.search(pat, rel) for pat in patterns)]


def problems(platform, tree):
    """What tree lacks: the two files, a part for each library, a module for each Qt library."""
    p = pins()
    dest = os.path.join(tree, PLACE[platform])
    found = []
    lic, notes = os.path.join(dest, "LICENSE.txt"), os.path.join(dest, "THIRD-PARTY-NOTICES.txt")
    if not os.path.isfile(lic):
        found.append(f"no {os.path.join(PLACE[platform], 'LICENSE.txt')}")
    elif read(lic) != read(os.path.join(ROOT, "LICENSE")):
        found.append("LICENSE.txt isn't AppKata's LICENSE")
    if not os.path.isfile(notes):
        found.append(f"no {os.path.join(PLACE[platform], 'THIRD-PARTY-NOTICES.txt')}")
    else:
        text = read(notes)
        titles = dict(re.findall(rf"^{RULE}\n([^\n]+)\n{RULE}\n\n(.*?)(?=^{RULE}\n|\Z)", text, re.M | re.S))
        for key, plats, title, _, _ in PARTS:
            if platform in plats and len(titles.get(title.format(**p), "").strip()) < 200:
                found.append(f"the notices have no section \"{title.format(**p)}\", or an empty one")
        modules = set()
        for line in re.findall(r"^  Modules: (.*)$", text, re.M):
            modules |= set(line.split(", "))
    for rel in binaries(tree):
        keys = parts_of(rel, platform)
        key = keys[0] if len(keys) == 1 else None
        if not keys:
            found.append(f"{rel}: no part the notices give")
        elif len(keys) > 1:
            found.append(f"{rel}: the patterns of {' and '.join(keys)} each take it")
        m = QT_LIB.match(os.path.basename(rel))
        if key == "qt" and m and os.path.isfile(notes) and m.group(1) not in modules:
            found.append(f"{rel}: Qt's {m.group(1)}, a module of none of the repositories the Qt section lists")
    return found


def check(platform, tree):
    found = problems(platform, tree)
    for line in found:
        print(f"  {line}", file=sys.stderr)
    if found:
        sys.exit(f"{tree}: {len(found)} problems with its license files (scripts/third_party_notices.py)")
    print(f"{tree}: LICENSE.txt and THIRD-PARTY-NOTICES.txt, and every library a part of them")


# ----------------------------------------------------------------------------------------- refresh

CACHE = os.path.join(ROOT, "build", "notices-cache")
# the Qt repositories the builds' Qt libraries and plugins come from
QT_REPOS = ["qtbase", "qtdeclarative", "qtsvg", "qtimageformats", "qtwayland", "qtlottie", "qtquicktimeline", "qttools",
            "qt3d", "qtscxml", "qtwebengine"]
# third-party code a Qt repository uses only to build, test or show examples, not in its libraries
QT_NOT_SHIPPED = ("cmake/", "examples/", "tests/", "coin/", "src/testinternal/", "src/qdoc/", "src/3rdparty/gradle/")
PBS = "https://github.com/astral-sh/python-build-standalone/releases/download"


def fetch(url, name):
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, name)
    if not os.path.exists(path):
        print(f"== {url}", file=sys.stderr)
        subprocess.run(["curl", "-fsSL", "-o", path + ".part", url], check=True)
        os.rename(path + ".part", path)
    return path


def fetch_text(url):
    return subprocess.run(["curl", "-fsSL", url], check=True, capture_output=True, text=True).stdout


def _members(tar_path, want):
    """{path in the archive, without its top folder: bytes} for each regular file want(path) takes."""
    out = {}
    with tarfile.open(tar_path) as t:
        for m in t:
            rel = m.name.split("/", 1)[1] if "/" in m.name else ""
            if m.isfile() and want(rel):
                out[rel] = t.extractfile(m).read()
    return out


def _spdx(expr):
    """The licenses AppKata takes a file under, given its SPDX expression: the LGPL 3 where it is offered, the
    first other choice otherwise, never the Qt commercial license."""
    choices = [c.strip("() ") for c in expr.split(" OR ") if c.strip("() ") != "LicenseRef-Qt-Commercial"]
    if not choices:
        return []
    pick = "LGPL-3.0-only" if "LGPL-3.0-only" in choices else choices[0]
    return [x.strip("() ") for x in re.split(r" WITH | AND ", pick)]


def _attributions(files, where):
    """The third-party code of a Qt-style repository (its qt_attribution.json files), shipped parts only,
    as text: each with its usage, license, copyright and the license's text, a text given once."""
    out, given = [], {}
    for rel in sorted(r for r in files if r.endswith("qt_attribution.json")):
        folder = os.path.dirname(rel)
        if folder.startswith(QT_NOT_SHIPPED):
            continue
        data = json.loads(files[rel].decode("utf-8"), strict=False)
        for e in data if isinstance(data, list) else [data]:
            lic_files = e.get("LicenseFiles") or ([e["LicenseFile"]] if e.get("LicenseFile") else [])
            copyright = e.get("Copyright") or ""
            if isinstance(copyright, list):
                copyright = "\n".join(copyright)
            if not copyright and e.get("CopyrightFile"):
                copyright = files[os.path.normpath(os.path.join(folder, e["CopyrightFile"]))].decode("utf-8", "replace")
            lines = [f"--- {e['Name']}{' ' + e['Version'] if e.get('Version') else ''} ({where}/{folder}) ---", ""]
            usage = " ".join((e.get("QtUsage") or "").split())
            if usage:
                lines += [usage, ""]
            lines.append(f"License: {e.get('License', '')} ({e.get('LicenseId', '')})")
            if e.get("Homepage"):
                lines.append(f"Homepage: {e['Homepage']}")
            if copyright.strip():
                lines += ["", copyright.strip()]
            for lf in lic_files:
                text = files[os.path.normpath(os.path.join(folder, lf))].decode("utf-8", "replace").strip()
                digest = hashlib.sha256(" ".join(text.split()).encode()).hexdigest()
                if digest in given:
                    lines += ["", f"(The license's text is the one given above for {given[digest]}.)"]
                else:
                    given[digest] = e["Name"]
                    lines += ["", text]
            out.append("\n".join(lines))
    return out


def refresh_qt(p):
    ver, licenses, summaries, attrib, ids = p["PYSIDE"], {}, [], [], set()
    for repo in QT_REPOS:
        tar = fetch(f"https://github.com/qt/{repo}/archive/refs/tags/v{ver}.tar.gz", f"{repo}-{ver}.tar.gz")
        files = _members(tar, lambda r: r.endswith("qt_attribution.json") or r.startswith("LICENSES/")
                         or (r.startswith("src/") and r.endswith("CMakeLists.txt")))
        wanted = set()
        for rel in [r for r in files if r.endswith("qt_attribution.json")]:
            data = json.loads(files[rel].decode("utf-8"), strict=False)
            for e in data if isinstance(data, list) else [data]:
                for f in (e.get("LicenseFiles") or []) + [e.get("LicenseFile"), e.get("CopyrightFile")]:
                    if f:
                        wanted.add(os.path.normpath(os.path.join(os.path.dirname(rel), f)))
        files.update(_members(tar, lambda r: r in wanted))
        counts = {}
        with tarfile.open(tar) as t:
            for m in t:
                rel = m.name.split("/", 1)[1] if "/" in m.name else ""
                if (m.isfile() and rel.startswith("src/") and "/3rdparty/" not in rel and not rel.startswith(QT_NOT_SHIPPED)
                        and rel.endswith((".cpp", ".h", ".c", ".mm", ".qml", ".js", ".frag", ".vert"))):
                    head = t.extractfile(m).read(4096).decode("utf-8", "replace")
                    s = re.search(r"SPDX-License-Identifier:\s*(.+?)\s*(?:\*/|-->|$)", head, re.M)
                    if s:
                        counts[s.group(1)] = counts.get(s.group(1), 0) + 1
        modules = set()
        for rel, data in files.items():
            if rel.endswith("CMakeLists.txt"):
                # an internal module's target is <name>Private, its library still Qt6<name>
                modules |= {re.sub(r"Private$", "", m) for m in
                            re.findall(r"qt_internal_add_(?:qml_)?module\(\s*(\w+)", data.decode("utf-8", "replace"))}
        for expr in counts:
            ids.update(_spdx(expr))
        for rel, data in files.items():
            if rel.startswith("LICENSES/"):
                licenses.setdefault(os.path.basename(rel)[:-4], data.decode("utf-8", "replace").strip())
        merged = {}
        for e, n in counts.items():
            merged[e.replace("LicenseRef-Qt-Commercial OR ", "")] = merged.get(e.replace("LicenseRef-Qt-Commercial OR ", ""), 0) + n
        shown = "; ".join(f"{e} ({n} file{'s' if n > 1 else ''})" for e, n in sorted(merged.items(), key=lambda x: -x[1]))
        summaries.append(f"{repo} (https://github.com/qt/{repo}/tree/v{ver})\n  Licenses: {shown}\n"
                         f"  Modules: {', '.join(sorted(modules))}")
        attrib += _attributions(files, repo)
    texts = []
    for i in sorted(ids - {"GPL-3.0-only", "GPL-2.0-only", "LicenseRef-Qt-Commercial"}):
        if i not in licenses:
            sys.exit(f"no text for {i} in the Qt repositories' LICENSES folders")
        texts.append(f"--- {i} ---\n\n{licenses[i]}")
    out = (fill(f"Qt {ver}, by The Qt Company Ltd. and other contributors: https://www.qt.io",
                "The Qt libraries and plugins here are the open-source edition of Qt. Qt offers most of its code under "
                "the GNU Lesser General Public License, version 3, or the GNU General Public License, version 2 or 3; "
                "some modules only under the GPL version 3. AppKata takes each file under the LGPL version 3 where "
                "that is offered, and otherwise under the first license offered: the GPL version 3 (its text is "
                "LICENSE.txt, beside this file), or the others below. Each repository the libraries and plugins come "
                "from, with the licenses its files carry (how many files carry each) and the modules it makes; its "
                f"source code is the repository at the tag v{ver}:") + "\n\n" + "\n\n".join(summaries) + "\n\n"
           + fill("The third-party code in these repositories that Qt's libraries and plugins use, as each repository "
                  "lists it (qt_attribution.json; code for other platforms included):") + "\n\n" + "\n\n".join(attrib)
           + "\n\n" + fill("The texts of the licenses above (but the GPL version 3's, LICENSE.txt), as Qt gives them:")
           + "\n\n" + "\n\n".join(texts) + "\n")
    with open(os.path.join(LICENSES, "qt.txt"), "w", encoding="utf-8") as f:
        f.write(out)


def refresh_pyside(p):
    ver = p["PYSIDE"]
    tar = fetch(f"https://github.com/qtproject/pyside-pyside-setup/archive/refs/tags/v{ver}.tar.gz", f"pyside-setup-{ver}.tar.gz")
    files = _members(tar, lambda r: r.endswith("qt_attribution.json") and r.startswith("sources/"))
    wanted = set()
    for rel, data in files.items():
        d = json.loads(data.decode("utf-8"), strict=False)
        for e in d if isinstance(d, list) else [d]:
            for f in (e.get("LicenseFiles") or []) + [e.get("LicenseFile"), e.get("CopyrightFile")]:
                if f:
                    wanted.add(os.path.normpath(os.path.join(os.path.dirname(rel), f)))
    files.update(_members(tar, lambda r: r in wanted))
    out = (fill(f"PySide6 and Shiboken6 {ver}, Qt for Python, by The Qt Company Ltd.: https://www.qt.io/qt-for-python",
                "License: LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only, which AppKata takes under the GNU Lesser "
                "General Public License, version 3 (its text is in the Qt section).")
           + f"\nSource code: https://github.com/qtproject/pyside-pyside-setup/tree/v{ver}\n\n"
           + fill("The third-party code in them, as the repository lists it (qt_attribution.json):") + "\n\n"
           + "\n\n".join(_attributions(files, "pyside-setup")) + "\n")
    with open(os.path.join(LICENSES, "pyside.txt"), "w", encoding="utf-8") as f:
        f.write(out)


def _release_python():
    return subprocess.run(["sh", os.path.join(ROOT, "scripts", "python-standalone.sh")], check=True,
                          capture_output=True, text=True).stdout.strip()


def refresh_python(p):
    build, ver = p["PYTHON_BUILD"], p["PYTHON"]
    release = build.split("+")[1]
    name = f"cpython-{build}-x86_64-unknown-linux-gnu-pgo+lto-full.tar.zst"
    sums = fetch_text(f"{PBS}/{release}/SHA256SUMS")
    want = re.search(rf"^([0-9a-f]{{64}})\s+{re.escape(name)}$", sums, re.M).group(1)
    path = fetch(f"{PBS}/{release}/{name.replace('+', '%2B')}", name)
    with open(path, "rb") as f:
        if hashlib.sha256(f.read()).hexdigest() != want:
            sys.exit(f"{name} doesn't match the release's SHA256SUMS")
    tar = path[:-4]
    if not os.path.exists(tar):
        with open(tar + ".part", "wb") as out:
            subprocess.run(["zstd", "-dcq", path], stdout=out, check=True)
        os.rename(tar + ".part", tar)
    files = _members(tar, lambda r: r == "PYTHON.json" or r.startswith("licenses/"))
    info = json.loads(files["PYTHON.json"])
    py = _release_python()
    facts = json.loads(subprocess.run([py, "-I", "-c", (
        "import json, ssl, zlib, compression.zstd as z; print(json.dumps({'openssl': ssl.OPENSSL_VERSION_INFO[0], "
        "'zstd': '.'.join(map(str, z.zstd_version_info)), 'zlibng': getattr(zlib, 'ZLIBNG_VERSION', '')}))")],
        check=True, capture_output=True, text=True).stdout)
    used = {}
    for module, variants in info["build_info"]["extensions"].items():
        for lp in variants[0].get("license_paths") or []:
            base = os.path.basename(lp)
            if base.startswith("LICENSE.openssl-") and not base.startswith(f"LICENSE.openssl-{facts['openssl']}"):
                continue
            if base == "LICENSE.zlib-ng.txt" and not facts["zlibng"]:
                continue
            used.setdefault(base, set()).add(module)
    missing = {"LICENSE.zstd.txt": f"https://raw.githubusercontent.com/facebook/zstd/v{facts['zstd']}/LICENSE",
               "LICENSE.zlib-ng.txt": f"https://raw.githubusercontent.com/zlib-ng/zlib-ng/{facts['zlibng']}/LICENSE.md"}
    libs = []
    for base in sorted(used):
        text = files.get("licenses/" + base)
        text = text.decode("utf-8", "replace") if text else fetch_text(missing[base])
        libs.append(f"--- {base[8:-4]} (for {', '.join(sorted(used[base]))}) ---\n\n{text.strip()}")
    # CPython's license, and its notices for the code it includes (the License page of its documentation;
    # python-build-standalone's LICENSE.cpython.txt is an older one, without mimalloc's or the Zstandard bindings')
    cpy = _members(fetch(f"https://github.com/python/cpython/archive/refs/tags/v{ver}.tar.gz", f"cpython-{ver}.tar.gz"),
                   lambda r: r in ("LICENSE", "Doc/license.rst"))
    rst = cpy["Doc/license.rst"].decode("utf-8")
    other = rst[rst.index(".. _OtherLicenses:"):]
    other = re.sub(r"(?m)^\.\. _[\w-]+:\n", "", other)                               # labels
    other = re.sub(r":[\w:]+:`!?([^`<]+?)(?:\s*<[^>]*>)?`", r"\1", other)             # :mod:`x`, :file:`x`
    other = re.sub(r"`([^`<]+?)\s*<([^>]+)>`_+", r"\1 (\2)", other)                   # `text <url>`_
    other = re.sub(r"(?m)::$", ":", other)
    with open(os.path.join(LICENSES, "python.txt"), "w", encoding="utf-8") as f:
        f.write(f"Python {ver}, by the Python Software Foundation: https://www.python.org\n"
                f"Source code: https://github.com/python/cpython/tree/v{ver}\n\n"
                + cpy["LICENSE"].decode("utf-8").strip() + "\n\n\n" + other.strip() + "\n")
    with open(os.path.join(LICENSES, "python-linux.txt"), "w", encoding="utf-8") as f:
        f.write(fill(f"The libraries python-build-standalone {release} builds into this Python "
                     "(https://github.com/astral-sh/python-build-standalone), each with the modules that use it:") + "\n\n"
                + "\n\n".join(libs) + "\n")
    return files, facts


def refresh_python_windows(p, pbs_files):
    script = ("import json, zlib, sqlite3; print(json.dumps({'zlibng': getattr(zlib, 'ZLIBNG_VERSION', ''), "
              "'sqlite': sqlite3.sqlite_version}))")
    run = subprocess.run(["docker", "run", "--rm", p["PYWINE_IMAGE"], "sh", "-c", f"wine python -c \"{script}\" 2>/dev/null"],
                         check=True, capture_output=True, text=True).stdout
    facts = json.loads(run.strip().splitlines()[-1])
    libs = [f"--- liblzma (for _lzma) ---\n\n{pbs_files['licenses/LICENSE.liblzma.txt'].decode().strip()}",
            f"--- SQLite {facts['sqlite']} (for _sqlite3, sqlite3.dll) ---\n\n"
            f"{pbs_files['licenses/LICENSE.sqlite.txt'].decode().strip()}"]
    if facts["zlibng"]:
        text = fetch_text(f"https://raw.githubusercontent.com/zlib-ng/zlib-ng/{facts['zlibng']}/LICENSE.md")
        libs.append(f"--- zlib-ng {facts['zlibng']} (for zlib) ---\n\n{text.strip()}")
    with open(os.path.join(LICENSES, "python-windows.txt"), "w", encoding="utf-8") as f:
        f.write(fill("Libraries the Windows build of Python carries whose licenses its LICENSE.txt leaves out:") + "\n\n"
                + "\n\n".join(libs) + "\n")
    return facts


def refresh_icu(p):
    wheels = os.path.join(CACHE, "wheels")
    os.makedirs(wheels, exist_ok=True)
    plats = [a for t in ("2_28", "2_31", "2_34", "2_35", "2_39") for a in ("--platform", f"manylinux_{t}_x86_64")]
    subprocess.run([_release_python(), "-m", "pip", "download", "-q", "--no-deps", "--only-binary=:all:", *plats,
                    "--python-version", p["PY_SERIES"], "-d", wheels, f"PySide6-Essentials=={p['PYSIDE']}"], check=True)
    wheel = glob.glob(os.path.join(wheels, f"pyside6_essentials-{p['PYSIDE']}-*manylinux*.whl"))[0]
    with zipfile.ZipFile(wheel) as z:
        name = next(n for n in z.namelist() if re.search(r"/libicuuc\.so\.\d+$", n))
        major = name.rsplit(".", 1)[1]
        found = re.search(rb"\b" + major.encode() + rb"\.(\d+)\b", z.read(name))
    ver = f"{major}.{found.group(1).decode()}"
    text = fetch_text(f"https://raw.githubusercontent.com/unicode-org/icu/release-{ver.replace('.', '-')}/icu4c/LICENSE")
    with open(os.path.join(LICENSES, "icu.txt"), "w", encoding="utf-8") as f:
        f.write(fill(f"ICU {ver}, by the Unicode Consortium and others: https://icu.unicode.org. Its libraries "
                     "(libicu*) come with Qt's Linux build.") + "\n"
                f"Source code: https://github.com/unicode-org/icu/tree/release-{ver.replace('.', '-')}\n\n{text.strip()}\n")
    return ver


def refresh():
    p = pins()
    os.makedirs(LICENSES, exist_ok=True)
    refresh_qt(p)
    refresh_pyside(p)
    pbs_files, facts = refresh_python(p)
    win = refresh_python_windows(p, pbs_files)
    icu = refresh_icu(p)
    with open(os.path.join(LICENSES, "SOURCES"), "w", encoding="utf-8") as f:
        f.write("# What scripts/third_party_notices.py refresh made the texts here from;\n"
                "# tests/test_third_party_notices.py checks they are the versions the builds pin\n"
                f"PYSIDE={p['PYSIDE']}\nPYTHON_BUILD={p['PYTHON_BUILD']}\nPYWINE_IMAGE={p['PYWINE_IMAGE']}\n"
                f"ICU={icu}\nZSTD={facts['zstd']}\nZLIBNG_WINDOWS={win['zlibng']}\n")
    print(f"refreshed {os.path.relpath(LICENSES, ROOT)}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "write" and len(sys.argv) == 5 and sys.argv[2] in PLACE:
        write(sys.argv[2], sys.argv[3], sys.argv[4])
    elif cmd == "check" and len(sys.argv) == 4 and sys.argv[2] in PLACE:
        check(sys.argv[2], sys.argv[3])
    elif cmd == "refresh" and len(sys.argv) == 2:
        refresh()
    else:
        sys.exit(__doc__)
