# Follow-ups after the CI work: the builds' license files

The walk thru of 2026-10-30, item 1, decided **A**: the AppImage and the Windows installer carry
AppKata's license as `LICENSE.txt` and a `THIRD-PARTY-NOTICES.txt` with every part they carry that
others made, its license, the license's text and where its source is. The installer puts both in
the install folder and shows no license page. Each build stops if either file is missing. The
owner's standing method applies: step back from the bug, name its class, build a harness for the
class, and report what else the harness catches.

## Results

| Pass | When | What it found | Where fixed | Tiers at the end |
|---|---|---|---|---|
| The harness, `check` | 2026-10-30 | L1 on both builds of db5e96c; every library in them is a part (Python, Qt, PySide6, ICU, xcb-util; PyInstaller, the Visual C++ runtime) | 010c534 | — |
| The fix, `write` and `refresh` | 2026-10-30 | L2 (upstream notices with gaps) and L3 (parts AppKata doesn't use) while gathering the texts | L1, L2: 010c534, 0d39b4a; L3 open | tier 1 2,470 passed, 122 skipped; `test-appimage.sh` ok on every desktop; the Windows VM PASS |

## L1. The builds carry no license files — HIGH (licensing; the walk thru) — fixed

The AppImage carried `usr/python/lib/python3.14/LICENSE.txt` only because python-build-standalone's
tarball has it. AppKata's own GPL text wasn't in it, nor the texts the LGPL asks to go with Qt
(the LGPL's and the GPL's), nor the notices of the libraries Python and Qt are built with, nor
those of the five xcb-util libraries the build copies in (MIT, whose notice must go with each
copy). The Windows build carried no license file at all.

**How it slipped past.** The builds were checked for what AppKata needs to *run*: the Windows build
stops without Qt's platform plugin or with an ICU DLL, `test-appimage.sh` checks the libraries the
AppImage takes from the host. Nothing read a build for what the licenses of its parts ask of a copy.

**The class:** a part a build carries whose license goes unmet. It covers a missing file, a new
library that comes in with a new input (a Qt plugin, a Python module built on another library),
and a Qt module from a repository whose licenses nobody looked at.

**The harness:** `scripts/third_party_notices.py check linux|windows TREE`, which both builds run
on what they are about to pack:

- `LICENSE.txt` is AppKata's `LICENSE`, and `THIRD-PARTY-NOTICES.txt` has a section, not empty,
  for each part the platform's build carries (`PARTS`).
- Every library in the tree (an ELF or PE file) is **one** part's, by its path. A library no part
  takes stops the build, and so does one two parts take (the patterns are wrong).
- Every Qt library (`libQt6<Module>`, `Qt6<Module>.dll`) is a module of a repository the Qt section
  lists, with the licenses its files carry. Qt offers some modules only under the GPL version 3.
- `tests/test_third_party_notices.py` runs the check on trees laid out as the builds lay them out:
  without the files, with them written, with a stray library, with a Qt module from a repository
  not listed (Qt Charts), with a section emptied and `LICENSE.txt` replaced. It also checks that
  the texts in `packaging/licenses/` are of the versions the builds pin, and that both builds run
  `write` and `check`.

**Run on db5e96c's builds** (before the fix): both fail, `no usr/share/licenses/appkata/LICENSE.txt`
and `no .../THIRD-PARTY-NOTICES.txt` on Linux, `no LICENSE.txt` and `no THIRD-PARTY-NOTICES.txt` on
Windows. Every library in both builds is a part the notices now give: no other catch.

**The fix:** `scripts/third_party_notices.py write`, run by both builds before `check`:

- `refresh` makes `packaging/licenses/` from the sources of the pinned versions: Qt's repositories at
  the tag `PYSIDE` names (each one's `qt_attribution.json`, `LICENSES/`, the SPDX lines of its files
  and the modules its CMake files make), PySide6's, CPython's license and its documentation's
  notices for the code it includes, the libraries python-build-standalone builds into `PYTHON_BUILD`
  (its full archive's `PYTHON.json` and `licenses/`), what the Windows Python leaves out, and the
  ICU in Qt's Linux wheel. `SOURCES` records the versions; the test fails when one moves without a
  refresh.
- The builds copy what their own inputs carry: the xcb-util libraries' Debian copyright files (in
  the Ubuntu 22.04 build container), and on Windows the Python's `LICENSE.txt` (its "Additional
  Conditions for this Windows binary build" and the libraries that build carries) and truststore's
  and PyInstaller's licenses.
- The AppImage has them in `usr/share/licenses/appkata/`; the Windows build beside `appkata.exe`,
  so Setup installs them into the install folder. `test-windows-vm.sh` checks them there after
  Setup.

## L2. Upstream notices with gaps — LOW (licensing; found gathering the texts) — fixed

What the parts' own makers publish leaves some out. The notices fill each gap from the source:

- **python-build-standalone's `LICENSE.cpython.txt` is older than CPython 3.14.8's.** It stops at
  the W3C C14N test suite: CPython's own License page (`Doc/license.rst` at the tag) adds OpenSSL,
  libffi, zlib, mimalloc, asyncio's code from uvloop, the Zstandard bindings and the Unicode
  Character Database. The notices take CPython's `LICENSE` and that page.
- **Its `PYTHON.json` names `LICENSE.zstd.txt` for `_zstd`, and the archive lacks the file.** The
  notices take zstd's `LICENSE` at the version the Python reports (1.5.7).
- **The Windows Python's `LICENSE.txt` leaves out liblzma, SQLite and zlib-ng** (2.2.4, which that
  build uses for `zlib`). The notices add them.

## L3. The builds carry parts AppKata doesn't use — open (for the owner)

Gathering the texts showed what the builds carry beyond what AppKata runs. The notices cover all of
it as it is; whether to remove it is the owner's call:

- **Qt modules only under the GPL version 3**, in the AppImage: Qt Lottie, Qt Quick Timeline, the
  Wayland compositor (`qtwayland`'s compositor files are GPL-3.0-only), and from `qttools` Designer,
  Help and UiTools (GPL-3.0 with Qt's exception). The Windows build has Quick Timeline. AppKata is
  GPL-3.0-or-later, so they may be combined with it, but a build carrying them can be conveyed
  only under the GPL version 3, not a later one.
- **Plugins whose libraries the build removes**, which can never load: Qt PDF's (`imageformats/
  libqpdf.so`, `qml/QtQuick/Pdf`) and Qt 3D's (`qml/QtQuick/Scene2D`, `Scene3D`).
- **Build and debugging tools**: `Qt/libexec` (qmlcachegen and others), the `qmltooling`, `qmllint`
  and `designer` plugins, and three `.o` object files of `Qt/labs/assetdownloader`.
- **Python's Tcl/Tk and Berkeley DB**: `tkinter` is removed, but `_tkinter` and the Tcl/Tk libraries
  stay; `_dbm` links Berkeley DB, under the Sleepycat license, which asks that a program using it
  say where its source is.
- In the AppImage these come to about 36 MB of its 324 MB unpacked (the Qt libraries above 18 MB,
  the plugins, tools and QML 6.5 MB, Tcl/Tk and `_dbm` 12 MB).

## Fixes

| Commit | Fixes | What | Proof |
|---|---|---|---|
| 010c534 | L1 (the texts and the check), L2 | `scripts/third_party_notices.py`, `packaging/licenses/`, `tests/test_third_party_notices.py` | `check` fails on db5e96c's builds (no `LICENSE.txt`, no notices); with the files written it passes on both, every library one part's; the test's 15 cases |
| 0d39b4a | L1 | Both builds write the files and run `check`; Setup installs them; `test-windows-vm.sh` looks for them | AppImage: `check` ok, both files extracted from the built AppImage, `LICENSE.txt` byte for byte AppKata's, `test-appimage.sh` starts it on X11 and Wayland in every desktop; Windows: `check` ok, `test-windows-vm.sh` PASS with `licenses: True True` after Setup; tier 1 2,470 passed, 122 skipped |
| a7c478b | — | The tests read and write their text as UTF-8 | on Windows they read the notices as cp1252 and failed; found running all eight follow-up branches merged on the Windows tier, which then passed |
