# Follow-ups after the CI work: the Windows tests' Python

The walk thru of 2026-10-30, item 8 (a clear fix): the Windows tier runs the tests on the Python the
release carries, python-build-standalone's build of `PYTHON_BUILD`, pinned by its SHA-256, with
pytest and truststore pinned too.

## Results

| Pass | When | What it found | Where fixed | Tiers at the end |
|---|---|---|---|---|
| The harness (`test_pinned_inputs.py`) | 2026-10-30 | W1; both new tests fail on the old `test-windows-vm.sh` | f90e426 | — |
| Running the tiers for item 2 | 2026-10-30 | W2, the Windows tier's only failure | a3e0d7a | tier 1 2,457 passed; the Windows VM: Python 3.14.8+20261013 fetched and checked, 195 passed, Setup PASS |

## W1. The Windows tier's Python is python-build-standalone's newest — LOW (testing; noticed at the CI handoff) — fixed

`scripts/test-windows-vm.sh --tests` fetched python-build-standalone's `latest` release, took the
first Windows build of `PY_SERIES` in it, and installed pytest and truststore at whatever pip
resolved. Requirement 1.2 says the tests run on the Python the release carries: on another day the
Windows tier tested a newer CPython than the installer's, and the VM kept the first one it fetched
forever (it fetched only when there was none).

**How it slipped past.** `tests/test_pinned_inputs.py` reads what the release builds and CI run;
the local tiers' scripts were left out as not release inputs. Every other tier's Python comes from
`scripts/python-standalone.sh`, which takes `PYTHON_BUILD`; the Windows tier had its own way.

**The class:** a tier that tests AppKata on another Python than the one it ships on.

**The harness:** `tests/test_pinned_inputs.py`:

- `test_every_tier_runs_the_python_the_release_carries`: each script that makes a tier's Python
  (`lib-tier1.sh`, `test-sandbox.sh`, `test-desktop-vm.sh`: `python-standalone.sh`;
  `test-windows-vm.sh`: `PYTHON_WINDOWS_SHA256`) names no moving python-build-standalone URL and no
  pip install without versions; the Windows tier takes `cpython-$PYTHON_BUILD-x86_64-pc-windows-msvc`,
  checks it against its SHA-256 and the version it runs; the VMs run pytest on the Python their host
  script sent.
- `test_one_python_for_the_appimage_the_installer_and_the_tests` also wants `PYTHON_WINDOWS_SHA256`.

Both fail on the old `test-windows-vm.sh`. Seen while reading, and outside the class: `test-sandbox.sh`
fetches the Neovim and Obsidian AppImages it runs as test subjects by `latest`.

**The fix:** `packaging/versions.env` pins `PYTHON_WINDOWS_SHA256` (the `install_only` build of
`PYTHON_BUILD` for x86_64 Windows) and `PYTEST`, the pytest pins `python-standalone.sh` had, now one
list for every tier. `test-windows-vm.sh` downloads that file, checks it, installs pytest, colorama
(pytest's dependency on Windows) and truststore (`build-windows.sh`'s pin) with `--no-deps`, records
what it made in `pin.txt` and makes it again when that changes, and stops unless the Python is
`PYTHON_BUILD`'s version. `python-standalone.sh` makes its Python again when `PYTEST` changes, too.

## W2. The Windows tier fails a test that reads GENESIS.md — LOW (testing; found running the tiers for item 2) — fixed

`tests/test_publish.py::test_every_check_genesis_names_is_one_the_script_reads_back` (PR #3) reads
`GENESIS.md`, and the Windows tier copied only `src tests scripts docs packaging README.md
pyproject.toml`. It failed there, the only failure of the run, on master as it stands.

**The class:** a test that reads a file the Windows copy leaves out. The list of paths was widened
once already, after "every test reading another one failed there".

**The fix:** the copy takes every file git lists but the screenshots' images (about 100 MB, which no
test reads). `test_the_windows_tier_copies_every_file_the_tests_read` holds the copy to no list of
paths.

## Fixes

| Commit | Fixes | What | Proof |
|---|---|---|---|
| f90e426 | W1 | `PYTHON_WINDOWS_SHA256` and `PYTEST` in `versions.env`; `test-windows-vm.sh` takes, checks and pins them; the harness | the new tests fail on the old script and pass; the Windows VM fetched `cpython-3.14.8+20261013` (it had none recorded), its version checked; tier 1 |
| a3e0d7a | W2 | the copy takes every file git lists but the screenshots' images | the Windows run: 195 passed, none failed (before: 1 failed, GENESIS.md) |
