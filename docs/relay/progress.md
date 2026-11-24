# Relay progress: CR1's unit U07, tokens and requests

4 batches cover the unit's 16 findings, taken from `docs/remediation/CR1-schedule.json` at
`upstream/master` ae63101: batch 1 the High finding and the rules for where a token and a request may go; batch 2 how a token is formed, keyed and kept; batch 3 how a Sync survives a failing or slow host; batch 4 a GitHub Enterprise file list, and the tests of the whole.
One agent at a time; the coordinator checks each batch before the next starts, and pushes.

## Batch 1

Files touched: `src/appkata_core/http.py`, `src/appkata_core/sync.py` (a docstring),
`docs/requirements/R9-sync-and-updates.md`, `tests/test_forges.py`.

Counts: 4 fixed, 0 no defect, 0 remedy changed, 0 set aside, 0 still left, 1 new.

Each new test was shown failing by exporting the commit before it with `git archive` to a scratch
folder, putting the new `tests/test_forges.py` over it and running the file there.

| Finding | Outcome | Commit | Tests (all in `tests/test_forges.py`) | Before the fix |
|---|---|---|---|---|
| #263 | fixed | `22364da` | `test_the_github_token_goes_to_its_named_hosts_over_https_and_nowhere_else`, `test_another_hosts_token_goes_to_that_host_alone`, `test_a_request_that_names_no_host_gets_its_own_hosts_token_and_no_other`, `test_an_image_on_another_host_is_fetched_without_the_sources_token`, `test_a_whole_sync_sends_the_token_to_the_sources_named_hosts_alone` | 15 failed (the token reached the other host, and went over plain http), 10 passed |
| #264 | fixed | `ee245b7` | `test_a_redirect_to_another_host_arrives_without_the_token`, `test_a_redirect_from_https_to_http_of_a_request_with_a_token_is_refused`; holding what must stay: `test_a_redirect_on_the_same_host_keeps_the_token`, `test_a_redirect_from_https_to_http_without_a_token_is_followed` | 6 failed (the second server got the token; the plain address was asked for), 28 passed |
| #276 | fixed | `b9b7807` | `test_r9_2_2_names_the_hosts_the_code_sends_a_token_to` | 1 failed (R9.2.2 named no host), 34 passed |
| #266 | fixed | `05acc96` | `test_only_http_and_https_addresses_are_opened_whoever_asks`, `test_https_own_opener_has_no_way_to_open_anything_but_http_and_https`, `test_a_file_address_is_not_saved_as_an_icon`, `test_an_image_whose_host_stands_for_a_local_address_is_refused`, `test_an_image_at_a_local_address_is_refused_by_the_real_lookup`, `test_a_host_whose_name_cant_be_looked_up_is_refused_too`, `test_a_whole_sync_opens_only_http_and_https_and_no_local_address_but_the_sources`, `test_a_redirect_to_a_local_address_is_refused`, `test_a_redirect_to_anything_but_http_and_https_is_refused`; holding what must stay: `test_the_sources_own_host_may_stand_for_a_local_address` | 72 failed, 39 passed |

Runs at the batch's head (`05acc96`), from the worktree's root:

- `tests/test_forges.py` whole: 111 passed. With the four document checks of the brief: 137 passed.
- The whole suite with the project's `.venv` (`pytest -q tests/`, no skip list): 2879 passed, 39
    skipped, in 2 min 37 s. A scratch plugin noted every name lookup the test process made: none.
- `tests/test_forges.py` and the other files that use `Http` (`test_core`, `test_audit_log_explore`,
    `test_channels`, `test_hardening`, `test_trust`) in the tier 1 image with no network
    (`docker run --network none`, the main checkout's `build/python-3.14` and
    `build/pyside-6.12.0-py3.14` mounted read-only, since this worktree has no `build/`): 209 passed,
    1 skipped. `scripts/test-tier1.sh` itself was not run here: it would fetch Python and PySide6
    into the worktree and register the worktree with coworker.
- The guard passed before and after each commit, naming only `docs/relay/`.

How the design fits together, for batch 2 (the same lookup): `Http._request` takes one parts object
from `Http._allowed(url, token_host)` (http or https, no local address but the host asked for);
`whose = token_host or the address's host` is "the host this request is made for", which picks the
token (`Http._token(parts, whose)`, then `Http._auth(whose)` as before) and is the one host that may
be local. `http.TOKEN_HOSTS` with `token_hosts()` is R9.2.2's one list. The token is an unredirected
header, and `http._Redirects` hands it on. A port in a host was left as it behaved (`_host_port`,
`_is_for`): #297 settles it. The tests stand in for `_auth` with `lambda *a, **k`, so #275 can
change its arguments.

### New

- `src/appkata_core/metadata.py:66-67`, `resolve`: the test for a GitHub page link is
    `"github.com/" in url and "/blob/" in url`, anywhere in the address, so a README image at
    `https://notgithub.com/o/r/blob/main/shot.png` is rewritten to
    `https://notraw.githubusercontent.com/o/r/main/shot.png`, and
    `https://evil.example/x?u=github.com/o/r/blob/main/shot.png` has its query rewritten. Low: a
    wrong image address, and since #263 no token goes with it. Not fixed here: `metadata.py` is in
    none of this batch's records.

### Needs your eye

- `ee245b7` (#264): a new Source error, "<host> redirected a request that carried its API token to
    plain http; the redirect wasn't followed".
- `b9b7807` (#276): R9.2.2's text, as decided: the host and the forge's named API and raw-file
    hosts (`github.com`: `api.github.com`, `raw.githubusercontent.com`), every other host itself.
- `05acc96` (#266): two new refusals, "'<address>' isn't an http or https address" and "<host> is
    on this computer or its local network (<address>): not fetched, since it isn't the Source's own
    host". An image's refusal is passed over for the next candidate, so the user sees a missing icon
    or hero at most; a forge's own redirect that is refused shows on the Source's row. A forge on the
    local network whose files redirect to another local host (object storage) loses those files:
    that is the decision as written.

### Needs a run

- The Windows suite, for the new tests that use real sockets and the `localhost` name:
    `scripts/test-windows-vm.sh --tests`. Nothing of this batch was run on Windows; the SMB case of
    #266 rests on reading, as in the finding (a `file:` address is now refused before urllib sees it).

### Guard

Nothing: every file changed is in U07's files.

### Doubts

1. **A name that changes its answer.** #266's check looks a host's name up, and the connection
    looks it up again. A host that answers with a public address first and a local one second gets
    past (a blind GET, no token). Closing it means checking the address the socket connected to,
    which needs Http's own connection classes: more than this finding's remedy, so it is left. It
    could be a new finding.
2. **"Local" is a little wider than the decision's three words.** `http._local` also refuses
    0.0.0.0 and anything Python's `ipaddress` doesn't call global, such as 100.64.0.0/10 (a
    carrier's shared range, which some private overlay networks use). A Source's own host is
    exempt either way.
3. **What the requirements say.** R9.2.2 has the decision's sentence and no more: "over https only"
    (#263's remedy) and the redirect rule (#264) are in the code and the tests, not in the text.
    #266's rule has no requirement text at all (its record lists none; the finding cites R3.2 and
    R3.3). R11.1.6 and Settings' help still say "only sent to their own host", as #276's record
    says to leave them.
4. **`token_host` now means two things**: whose token, and the one host that may be local. The
    name was kept so `forges.py` and `explore.py` stay untouched; it is said in `_request`'s
    docstring. A caller that asks for a project-named address without it would skip the local check
    for a first address (none does today; `_save_image` always passes it).
5. **Proxies.** Http's opener takes the system's http and https proxies only. Behind a proxy the
    local-address check still looks the name up on this computer, not as the proxy would.
6. **#269 (batch 3)**: an address urlsplit can't read, or one with no http or https scheme, is now
    `Unreachable`, so that part of "a bad README image address" no longer escapes. One with a space
    in it (`http://exa mple.invalid/x.png`) still raises `http.client.InvalidURL` out of Http:
    batch 3's reproduction should use that kind.
7. **A 401 after a redirect.** "rejected the API token (HTTP 401)" is still said when the request's
    first address carried a token, even if a redirect to another host, which got none, gave the 401.
8. The #264 tests give urllib's https handler a plain connection (no certificate to make): the
    request, headers and redirect are handled as https, and only the encryption is left out.

### The coordinator, after batch 1 (2026-11-24)

Checked: every answer of the agent on its named model; the guard; `tests/test_forges.py` and the
document tests, whole; the batch pushed.

- **New findings filed**, and added to this unit and to batch 4: #681 (the GitHub page link rewrite,
    batch 1's "New"), #682 (doubt 1: a name that changes its answer) and #683 (doubt 7: the 401
    after a redirect).
- **Doubt 3, for batch 2 to do first, in one commit of its own before its findings:** write into
    the requirements what batch 1's fixes made true and no requirement says. In R9.2.2: a token is
    sent over https only (#263), and a redirect carries it on only to the same scheme, host and
    port (#264). In R3, where the icon, the screenshot and the README's images are fetched (R3.2,
    R3.3 or R3.4, whichever covers all three): only http and https addresses are asked for, and
    none on a loopback, private or link-local address unless it is the Source's own host, a
    redirect included (#266, the owner's decision). `docs/requirements/R3-app-metadata.md` is in
    this unit's files now. Keep R11.1.6 and Settings' help text as #276's record says.
- **Doubt 2** (what counts as local is a little wider than the decision's three words) stands as
    built: say it in the R3 sentence ("or another address that isn't public").
- **Doubts 4, 5, 6 and 8** are noted; 6 is batch 3's to use.
- **Needs a run** (the Windows VM tests): the coordinator runs it once, when the unit's last batch
    is in.

