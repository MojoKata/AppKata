# Follow-ups after the CI work: tests that skip where they were meant to run

The walk thru of 2026-10-30, item 2, decided **A**: each tier runs against a committed list of the
tests it may skip and why. A skip not on the list fails the run, and so does a listed test that
ran. The DNS test waits up to a minute for a VM's resolver before it skips, and tier 1's image gets
curl. What else the lists catch is listed open here, for the owner, before it is fixed.

## Results

| Pass | When | What it found | Where fixed | Tiers at the end |
|---|---|---|---|---|

## S1. Tests skip in the tier that exists to run them, and the run still passes — MEDIUM (testing; the walk thru) — fixed

Two seen before the walk thru:

- **The DNS test** (`tests/test_sandbox_run.py::test_a_network_grant_includes_working_dns`) exists
  for the VMs: on Ubuntu and Mint `/etc/resolv.conf` is a symlink into `/run/systemd/resolve`, which
  the sandbox must bind, and only a booted system shows it. In the run at a93909a (review 3) three
  VMs skipped it: their guests couldn't resolve names while four VMs ran at once.
- **The ISO download test** (`tests/test_coworker.py::test_iso_download_checks_resumes_and_claims`)
  skipped on every tier 1 run: the image has no curl.

**How it slipped past.** A skip says why, and the run passes. The tiers were read as counts
("128 passed, 6 skipped"): a count that stays the same says nothing about which tests it holds, and
a count that grows by one reads as noise.

**The class:** a test that skips where it was meant to run, or nowhere runs at all.

**The harness:** `tests/conftest.py` and `tests/skips/<name>.txt`. Every pytest run a tier makes
sets `APPKATA_SKIPS` to its list's name. A skip the list doesn't name, or a listed test that ran,
becomes a failure (an error when the skip came at setup), so the run's summary line counts it, and
that line is what every tier reads; a test module skipped whole fails the run with its own summary.
`tests/test_skip_lists.py`:

- the verdict on each kind of report, on a list made for the test;
- every script that runs pytest for a tier sets `APPKATA_SKIPS`, and each tier has its list;
- each listed test exists and says why it may skip;
- the modules each tier's script takes are the ones the test knows (`TAKES`);
- every test some tier skips, another tier that takes its module runs: a test every tier skips is
  one that never runs. `NEVER_RUN` lists those allowed, each with why; the test fails on anything
  new, and on a listed test some tier runs.

**Run before the fix** (16d2726, the lists without the fix): tier 1 fails with one error,
`tests/test_coworker.py::test_iso_download_checks_resumes_and_claims  # download.sh needs curl`.
The DNS test, run in the Mint 22.3 container with its network off (`docker run --network none`,
`-k working_dns`): it waits a minute, skips, and fails the run, `skipped, and
tests/skips/launcher-mint22.3.txt doesn't list it`.

**The lists**, from a run of each tier with none, every skip read for its reason: tier 1 121 (the
sandbox tests that need bwrap or xdg-dbus-proxy, Windows', the booted-kernel check, the state
freezer, the system bus); each launcher container 5 and each launcher VM 6 (the PySide6 checks
tier 1 runs, the GPU in a container, the tmpfs, camera node and stand-in browser the containers
make); each desktop VM 5; Windows 52 lines (the Linux-only files whole, `file::*`).

**The fix:** tier 1's image has curl, and the DNS test waits up to a minute for the resolver
before it skips. Run with four VMs at once (the 24.04 launcher VM, both desktop VMs and the
Windows VM), the 24.04 VM's DNS test passed.

## S2. A test no tier runs — LOW (testing; found by the harness) — open

`tests/test_channels.py::test_system_bus` skips without a system bus. Tier 1's container has none,
Windows has none, and the tiers that have one (the VMs) don't take `test_channels.py`. It is in
`NEVER_RUN` as open, for the owner: give tier 1's container a bus, or have a VM take it.

## S3. Tier 1 from a git worktree skips the private-names check — MEDIUM (testing; found by the harness) — open

Run from a `git worktree` (a second checkout, so work goes on in the main one meanwhile), tier 1 mounts
the worktree at `/src`, whose `.git` file points at the main repository's `.git/worktrees/`, which
the container doesn't have. `tests/test_public_text.py`'s two tests skip, "not a git work tree", and
with them the check that no private name is in a tracked file. Now the run fails on it (two errors);
before, it passed. For the owner: mount the git directory the worktree names, or run tier 1 only
from a main checkout.

## Fixes

| Commit | Fixes | What | Proof |
|---|---|---|---|
