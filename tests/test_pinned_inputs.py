"""What the release builds and CI take from outside is pinned (the CI walk thru, item 7): an input
changes only by a commit, so the signature on a release vouches for inputs the repository names.

How they got in: the build scripts were written to fetch the newest of everything (appimagetool's
`continuous` release, the AppImage runtime appimagetool downloads by itself, python-build-standalone's
latest release, Docker images by tag, whatever dependencies pip resolves that day), which suited
builds made by hand and checked by running them. Nothing read the scripts for what they download.
The class: an input named by something that moves. This test reads every file the builds and CI
run and flags a URL through `latest` or `continuous`, a Docker image without a digest, a pip install
that leaves a version or a dependency open, a GitHub Action without a commit SHA, a download pin
without its SHA-256, and appimagetool without the runtime file it would otherwise fetch."""

import glob
import os
import re
import shlex

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")

# the files the builds and CI run (the local tiers' scripts aren't release inputs)
FILES = ["packaging/versions.env", "scripts/build-appimage.sh", "scripts/build-windows.sh", "scripts/lib-python.sh",
         "scripts/python-standalone.sh", "scripts/lib-tier1.sh", "scripts/test-tier1.sh"]

# what the test found when it was written, each to be pinned (item 7); the test fails on anything
# new, and on a listed item that is gone, so the list only shrinks
STILL_UNPINNED = {
}

DIGEST = re.compile(r"@sha256:[0-9a-f]{64}(?![0-9a-z])")
SHA = re.compile(r"^[0-9a-f]{64}$")
DOCKER_VALUED = {"-v", "--volume", "-e", "--env", "--env-file", "-w", "--workdir", "-u", "--user", "--name",
                 "--entrypoint", "--network", "--platform", "--mount", "-p", "--publish", "--device", "--cap-add",
                 "--security-opt", "--shm-size", "--add-host", "--tmpfs", "-l", "--label", "-h", "--hostname"}
PIP_VALUED = {"--cache-dir", "--target", "-t", "--prefix", "--root", "-i", "--index-url", "-c", "--constraint",
              "-r", "--requirement"}


def _tokens(s):
    """Shell words from s, as far as they go: a quoted command string running on past the line ends
    the list there."""
    lex = shlex.shlex(s, posix=True)
    lex.whitespace_split, lex.commenters = True, ""
    try:
        while (t := lex.get_token()) is not None:
            yield t
    except ValueError:
        return


def _assigned(text, var):
    """The value text gives var (VAR=..., VAR="...", or versions.env's : "${VAR:=...}"), or None."""
    m = re.search(rf'^\s*: "\${{{var}:=([^}}"\n]*)}}"', text, re.M) or re.search(rf'^\s*{var}="?([^"\n]*)', text, re.M)
    return re.split(r"\s+#", m.group(1))[0].strip() if m else None


def _image_pinned(image, text):
    if DIGEST.search(image):
        return True
    m = re.fullmatch(r"\$\{?(\w+)\}?", image)
    if not m:
        return False
    if m.group(1) == "IMG":                    # an image built here, FROM a pinned one (checked on its own)
        return True
    value = _assigned(text, m.group(1)) or _assigned(_read("packaging/versions.env"), m.group(1))
    return bool(value and DIGEST.search(value))


def _specs_pinned(specs, text):
    words = []
    for s in specs:
        m = re.fullmatch(r"\$\{?(\w+)\}?", s)
        words += (_assigned(text, m.group(1)) or _assigned(_read("packaging/versions.env"), m.group(1)) or s).split() if m else [s]
    return [w for w in words if "==" not in w]


def unpinned(text):
    """What text downloads by a moving name, each as a short description."""
    found = []
    joined = text.replace("\\\n", " ")
    for url in re.findall(r"https?://[^\s\"'|)]+", text):
        if {"latest", "continuous"} & set(url.split("/")):
            found.append(f"moving URL {url}")
    for m in re.finditer(r"\bdocker run\b(.*)", joined):
        words = iter(_tokens(m.group(1)))
        for w in words:
            if w in DOCKER_VALUED:
                next(words, None)
            elif not w.startswith("-"):
                if not _image_pinned(w, text):
                    found.append(f"image {w}")
                break
    for m in re.finditer(r"\bFROM\s+([^\s\\'\"]+)", text):
        if not _image_pinned(m.group(1), text):
            found.append(f"image {m.group(1)}")
    for m in re.finditer(r"^\s*(\w+_IMAGE)=(\S+)", text, re.M):
        if not DIGEST.search(m.group(2)):
            found.append(f"image {m.group(2)}")
    for m in re.finditer(r"^\s*(\w+)_URL=(\S+)", text, re.M):
        if not SHA.match(_assigned(text, f"{m.group(1)}_SHA256") or ""):
            found.append(f"no SHA-256 for {m.group(1)}_URL")
    for m in re.finditer(r"\bpip install\b(.*)", joined):
        words, specs, opts = iter(_tokens(m.group(1))), [], set()
        for w in words:
            if w[:1] in ">|;&)" or w.startswith("2>"):
                break
            if w in PIP_VALUED:
                next(words, None)
            elif w.startswith("-"):
                opts.add(w)
            else:
                specs.append(w)
        loose = _specs_pinned(specs, text)
        if loose:
            found.append(f"pip install {' '.join(loose)} without a version")
        if specs and "--no-deps" not in opts:
            found.append(f"pip install {' '.join(specs)} leaves its dependencies open")
    for line in joined.splitlines():
        if re.search(r"(?i)appimagetool\S*\"?\s+--", line) and "--runtime-file" not in line:
            found.append("appimagetool without --runtime-file (it downloads the newest runtime)")
    for m in re.finditer(r"^\s*-?\s*uses:\s*['\"]?([^\s'\"#]+)", text, re.M):
        u = m.group(1)
        if not (u.startswith("./") or re.fullmatch(r"[\w.-]+/[\w./-]+@[0-9a-f]{40}", u)
                or (u.startswith("docker://") and DIGEST.search(u))):
            found.append(f"action {u}")
    for m in re.finditer(r"^\s*(?:container|image):\s*['\"]?([^\s'\"#{]+)", text, re.M):
        if not DIGEST.search(m.group(1)):
            found.append(f"image {m.group(1)}")
    return found


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


def _files():
    return FILES + sorted(os.path.relpath(p, ROOT) for p in glob.glob(os.path.join(ROOT, ".github/workflows/*.y*ml")))


def test_every_input_of_the_builds_and_ci_is_pinned():
    found = {}
    for rel in _files():
        for what in dict.fromkeys(unpinned(_read(rel))):
            found.setdefault(rel, []).append(what)
    new = {rel: [w for w in ws if w not in STILL_UNPINNED.get(rel, [])] for rel, ws in found.items()}
    gone = {rel: [w for w in ws if w not in found.get(rel, [])] for rel, ws in STILL_UNPINNED.items()}
    assert not any(new.values()), f"inputs named by something that moves: {new}"
    assert not any(gone.values()), f"pinned now: take these off STILL_UNPINNED: {gone}"


def test_the_check_finds_each_way_an_input_moves():
    bad = {
        "curl -sSL -o x https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage":
            "moving URL",
        "TAG=$(curl -sSIL -o /dev/null https://github.com/astral-sh/python-build-standalone/releases/latest)": "moving URL",
        'test -f x || docker run --rm -v "$HERE:/src" debian:12 sh -c "': "image debian:12",
        'docker run --rm -e A=1 -v "$HERE:/w" -w /w/packaging amake/innosetup "/DV=1" x.iss': "image amake/innosetup",
        "printf 'FROM ubuntu:22.04\\nRUN apt-get update'": "image ubuntu:22.04",
        "JAMMY_IMAGE=ubuntu:22.04": "image ubuntu:22.04",
        "TOOL_URL=https://example.org/tool-1.0": "no SHA-256 for TOOL_URL",
        '"$PY" -m pip install -q --cache-dir "$C" "PySide6-Essentials==$PYSIDE"': "leaves its dependencies open",
        '"$PY" -m pip install -q --no-deps pytest >&2': "pip install pytest without a version",
        'ARCH=x86_64 "$CACHE/appimagetool" --appimage-extract-and-run --no-appstream "$APPDIR" "$OUT"':
            "appimagetool without --runtime-file",
        "      - uses: actions/checkout@v4": "action actions/checkout@v4",
        '"$APPIMAGETOOL" --appimage-extract-and-run --no-appstream "$APPDIR" "$OUT"': "appimagetool without --runtime-file",
        "    container: quay.io/pypa/manylinux2014_x86_64": "image quay.io/pypa/manylinux2014_x86_64",
    }
    for text, what in bad.items():
        assert any(what in f for f in unpinned(text)), (text, unpinned(text))
    d = "@sha256:" + "0" * 64
    good = [
        "curl -fsSL https://github.com/AppImage/appimagetool/releases/download/1.9.1/appimagetool-x86_64.AppImage",
        f'JAMMY_IMAGE=ubuntu:22.04{d}\ndocker run --rm -v "$HERE:/src" "$JAMMY_IMAGE" sh -c "',
        f'MINGW_IMAGE=debian:12{d}\n_df="FROM $MINGW_IMAGE"',
        'IMG=appkata-build:1\ndocker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp "$IMG" sh',
        f"TOOL_URL=https://example.org/tool-1.0\nTOOL_SHA256={'a' * 64}",
        '"$PY" -m pip install -q --no-deps "PySide6-Essentials==$PYSIDE" "shiboken6==$PYSIDE" >/dev/null',
        'DEPS="altgraph==0.17.4 pefile==2024.8.26"\nwine python -m pip install -q --no-deps pyinstaller==6.16.0 $DEPS >/dev/null 2>&1',
        'ARCH=x86_64 "$APPIMAGETOOL" --appimage-extract-and-run --runtime-file "$R" --no-appstream "$APPDIR" "$OUT"',
        f"JAMMY_IMAGE=ubuntu:22.04{d}      # builds the AppImage\n_df=\"FROM $JAMMY_IMAGE\"",
        "      - uses: actions/checkout@" + "1" * 40 + "  # v5.0.0",
        "      - uses: ./.github/actions/local",
    ]
    for text in good:
        assert unpinned(text) == [], (text, unpinned(text))


def test_one_python_for_the_appimage_the_installer_and_the_tests():
    """Requirement 1.2: PY_SERIES is PYTHON_BUILD's series, and the Wine image is tagged with it
    (build-windows.sh checks the image's own Python is PYTHON_BUILD's version when it runs)."""
    env = _read("packaging/versions.env")
    build = _assigned(env, "PYTHON_BUILD")
    assert re.fullmatch(r"\d+\.\d+\.\d+\+\d{8}", build), build
    series = build.rsplit(".", 1)[0]
    assert _assigned(env, "PY_SERIES") == series
    assert _assigned(env, "PYWINE_IMAGE").startswith(f"tobix/pywine:{series}@")
    assert SHA.match(_assigned(env, "PYTHON_LINUX_SHA256"))
    assert SHA.match(_assigned(env, "PYTHON_WINDOWS_SHA256"))


# Every tier's Python (requirement 1.2). How the Windows one got past: the test above read only what
# the release builds and CI run ("the local tiers' scripts aren't release inputs"), and the Windows
# tier fetched python-build-standalone's newest release itself, with pytest and truststore at
# whatever pip resolved that day. The class: a tier that tests AppKata on another Python than the
# one it ships on. (The walk thru of 2026-10-30, item 8; docs/reviews/followups-windows-test-python.md.)
TIER_PYTHON = {"scripts/lib-tier1.sh": "python-standalone.sh", "scripts/test-sandbox.sh": "python-standalone.sh",
               "scripts/test-desktop-vm.sh": "python-standalone.sh", "scripts/test-windows-vm.sh": "PYTHON_WINDOWS_SHA256"}


def test_every_tier_runs_the_python_the_release_carries():
    for rel, how in TIER_PYTHON.items():
        text = _read(rel)
        assert how in text, rel
        python = [w for w in unpinned(text) if w.startswith("pip install")
                  or (w.startswith("moving URL") and "python-build-standalone" in w)]
        assert not python, (rel, python)
    win = _read("scripts/test-windows-vm.sh")
    assert "cpython-$PYTHON_BUILD-x86_64-pc-windows-msvc-install_only.tar.gz" in win
    assert 'sha256sum -c' in win and '[ "$V" = "${PYTHON_BUILD%%+*}" ]' in win     # and it checks what it got
    assert "lib-tier1.sh" in _read("scripts/test-tier1.sh")
    for script in ("scripts/sandbox/vm-launcher.sh", "scripts/sandbox/vm-desktop.sh"):
        assert re.search(r"\$PY -m pytest", _read(script)), script      # the Python their host script sent


def test_the_windows_tier_copies_every_file_the_tests_read():
    """The Windows run copies what git lists but the screenshots' images: a list of folders left out
    GENESIS.md, which tests/test_publish.py reads, and the test failed only there."""
    zip_line = next(line for line in _read("scripts/test-windows-vm.sh").splitlines() if "git ls-files" in line)
    assert re.search(r"git ls-files -co --exclude-standard \|", zip_line), zip_line
