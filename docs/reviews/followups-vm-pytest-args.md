# Follow-ups after the CI work: pytest's arguments on the way to the launcher VMs

The walk thru of 2026-10-30, item 6 (a clear fix): `scripts/test-sandbox.sh launcher-vm` and
`launcher-vm26` hand pytest its arguments as they were given.

## Results

| Pass | When | What it found | Where fixed | Tiers at the end |
|---|---|---|---|---|
| The harness, `tests/test_tier_args.py` | 2026-10-30 | A1 (its first two tests fail on the old scripts); nothing else | 765be6c | tier 1 2,458 passed; `launcher-vm -k 'working_dns or no_network_grant'` 2 passed, 132 deselected; the Mint container the same |

## A1. `-k 'a or b'` reaches the VMs' pytest as three words — LOW (testing; noticed in review 3's runs) — fixed

`test-sandbox.sh` put its arguments into the container's environment as `"$*"`, one string; the
container wrote it into the VM's cloud-config, which set it in the VM's environment; and
`vm-launcher.sh` put `${PYTEST_ARGS}` into its `bash -lc "..."` command line, which split it again
on spaces. Run on the old code with `-k 'working_dns or no_network_grant'`, the VM's pytest said
`ERROR: file or directory not found: or` and ran nothing.

**How it slipped past.** Every run gave one-word arguments (`-x`, `-k name`), which survive.

**The class:** arguments that cross a layer as one string (an environment variable, a config file,
a shell command line) and are split again on the other side.

**The harness:** `tests/test_tier_args.py` sends awkward arguments (spaces, `'`, `"`, `$HOME`, `*`,
a backslash) through the steps the scripts take, run as they run them: `test-sandbox.sh`'s encoding,
then `vm-launcher.sh`'s decoding and its `bash -c "... $PYTEST_ARGS"`, with `printf` standing in for
pytest. Each argument must arrive whole. It also checks that tier 1 and the launcher containers,
which pass `"$@"` through `sh -c`'s own arguments, keep doing so. The first two tests fail on the
old scripts. It found nothing else: the other tiers pass no arguments on, or pass them as `"$@"`.

**The fix:** `test-sandbox.sh` quotes each argument for the shell (`'...'`, a `'` in it as `'\''`)
and sends the result base64-encoded (`PYTEST_ARGS_B64`), which the cloud-config and the environment
carry unchanged; `vm-launcher.sh` decodes it into its command line, where the VM's shell takes the
quotes off.

## Fixes

| Commit | Fixes | What | Proof |
|---|---|---|---|
| 765be6c | A1 | `test-sandbox.sh` quotes and base64-encodes the arguments, `vm-launcher.sh` decodes them; the harness | before, the 24.04 VM: `ERROR: file or directory not found: or`, no tests ran; after: 2 passed, 132 deselected |
