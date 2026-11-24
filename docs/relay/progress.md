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

## Batch 2

Files touched: `src/appkata_core/http.py`, `src/appkata_core/forges.py`, `src/appkata_core/explore.py`,
`src/appkata_core/db.py`, `src/appkata_core/applog.py`, `src/appkata/backend.py`,
`src/appkata/qml/SettingsDialog.qml`, `docs/requirements/R3-app-metadata.md`,
`docs/requirements/R9-sync-and-updates.md`, `docs/requirements/R11-settings.md`, `tests/test_forges.py`,
`tests/test_audit_log_explore.py`, and three files outside the findings' records (under **Guard**):
`tests/test_backend.py`, `tests/test_requirements_trace.py`, `tests/skips/windows.txt`.

Counts: 5 fixed, 0 no defect, 0 remedy changed, 0 set aside, 0 still left, 2 new.

First, the commit the coordinator asked for: `6176fb6`, text only. R9.2.2 says https only and the
redirect rule; R3.1.1, a new item, says where an image is fetched from (doubt 1 says why R3.1.1).

Each new test was shown failing by exporting the commit before it with `git archive` to a scratch
folder, putting the new test files over it and running them there.

| Finding | Outcome | Commit | Tests | Before the fix |
|---|---|---|---|---|
| #275 | fixed | `b85604c` | `tests/test_forges.py`: `test_every_forge_type_has_its_form_and_a_redirect_knows_each_header`, `test_a_forges_requests_carry_the_token_in_its_types_form_whatever_the_host_is_called`, `test_every_host_appkata_knows_gets_the_form_of_the_forge_it_runs`, `test_a_forge_that_needs_its_token_is_detected_and_read_on_a_host_whose_name_says_nothing`, `test_with_no_forge_type_known_only_github_coms_own_names_get_its_form`, `test_a_search_sends_the_token_in_the_form_of_the_forge_it_searches` | 25 failed (invent.kde.org, salsa.debian.org and framagit.org got `Authorization: token`; a GitLab that needs its token wasn't detected), 131 passed |
| #297 | fixed | `9b87145` | `tests/test_forges.py`: `test_a_token_is_sent_to_the_one_address_it_is_kept_for`, `test_every_call_for_a_source_finds_the_token_kept_for_the_sources_host`, `test_what_is_typed_for_a_tokens_host_is_kept_as_a_sources_host_is_written`, `test_on_a_local_forge_only_the_sources_own_address_may_be_local`, `test_r11_1_6_r9_2_2_and_settings_say_which_host_a_token_is_kept_for`; `tests/test_backend.py`: `test_a_token_is_kept_under_the_one_address_it_belongs_to` | 45 failed (the probes carried no token for a forge on a port; a token for a name went to its other ports), 183 passed. Four of the 45 are #264's redirect tests, whose token is now kept under the server's address |
| #292 | fixed (the tests are the fix) | `aef4b9a` | `tests/test_forges.py`: `test_every_request_of_three_syncs_and_three_searches_keeps_r9_2_2`, `test_the_harness_itself_sees_each_way_r9_2_2_is_broken`, `test_through_real_sockets_a_forges_token_reaches_its_own_address_alone` | On the code before the four fixes (`ae63101`): 4 failed (21 requests broke the rule; the second server got the token). On six copies of this batch's code with one fault put back each (the token by the caller's host alone, over plain http, a redirect carrying it on, a redirect to plain http followed, the form by the host's name, the port left out of a host): each failed, 1 to 4 tests |
| #434 | fixed | `41253c4` | `tests/test_audit_log_explore.py`: `test_the_data_and_log_folders_and_the_database_are_the_users_alone` (new, and made wider earlier) | 2 failed (the folders 0755), 10 passed |
| #485 | fixed | `88c1547` | `tests/test_requirements_trace.py`: `test_every_backend_slot_is_wired_to_the_ui_or_listed`, read more strictly | 1 failed ("slots the UI never uses: addSource, addTrust, tokens"), 3 passed |

Runs at the batch's head (`88c1547`), from the worktree's root:

- The whole suite with the project's `.venv` (`pytest -q tests/`, no skip list): 2990 passed, 39
    skipped, in 2 min 36 s.
- The whole suite in the tier 1 image with no network and 3 GB (`docker run --network none
    --memory=3g`, `APPKATA_SKIPS=tier1`, the main checkout's `build/python-3.14` and
    `build/pyside-6.12.0-py3.14` mounted read-only): 2903 passed, 121 skipped, 5 failed, all five
    because a worktree's `.git` points outside the mount ("not a git repository"). Their four files
    again with the main checkout's `.git` mounted read-only: 79 passed. `scripts/test-tier1.sh`
    itself was not run, as in batch 1.
- The four document checks of the brief, and the guard, before each commit.

How the design fits together, for batches 3 and 4:

- **A host is one address** (`http._host`): the name, and the port unless it is the scheme's own.
    It is how `urls.parse` writes `Repo.host`. `Http.tokens`, `Http.forges`, the host a request is
    made for (`whose`) and `token_hosts()` all use that spelling; `http.token_key` makes it from
    typed text. `_is_for(parts, whose)` is an exact match and serves both the token and the local
    address exception.
- **The form** is `http.TOKEN_FORMS[forge type]`. `Forge.__init__` tells Http what its host runs
    (`Http.set_forge`), so nothing downstream passes it; a caller with no Forge passes `forge=` (the
    probes, explore). `Http._auth(host, forge)` falls back to the name only when neither says.
- **The harness** of #292 (`may_carry`, `breaks_r9_2_2`, `three_forges`) is written apart from
    Http: batch 4's whole-Sync tests (#293) can sync `three_forges()` and add to it.

### New

- `src/appkata_core/urls.py:64`, `parse`: the port is left out when it is 80 or 443 whatever the
    scheme, so `https://git.example.org:80/o/r` becomes `https://git.example.org/o/r` and is asked
    on port 443. Run: `urls.parse` gives host `git.example.org`. Low. Not fixed: `urls.py` is
    another unit's (U20).
- `src/appkata_core/sync.py:44`, `_ext`: an answer that is no image by its first bytes is taken
    for one when its address ends in an image's extension, so a sign-in page answered with 200 at
    `…/shot.png` is saved as `hero.png` and the candidates after it are never tried. Run:
    `_ext("https://x.example/shot.png", b"<!DOCTYPE html>…")` gives `.png`. Low. Not fixed:
    `sync.py` is in none of this batch's records.

### Needs your eye

- `6176fb6`: R9.2.2 gains "over https only" and the redirect rule; R3.1.1 is new: only http and
    https addresses, none local unless it is the Source's own host, a redirect included, and a
    refused image passed over for the next.
- `9b87145` (#297), what the user sees: Settings' help text gains "A forge on its own port is
    entered with it (git.example.org:3000); a host alone means the default port.", and the host
    field's placeholder is "host or host:port" (it was "github.com"; the field still opens filled
    with github.com). What is typed is kept as a host: lower case, `:443` left out, a pasted
    address cut down to its host, and the row and the Audit show that.
- `9b87145` (#297), the text: R11.1.6 gains a paragraph (a token belongs to one address; how the
    host is entered; the placeholder; a pasted address). R9.2.2 says a host is one address, and
    "nor to another port of its own". R3.1.1 gains "on the Source's own port" (doubt 2).
- `41253c4` (#434): R11.1.6 gains "Tokens are kept in the database (R1.8). On Linux the data folder
    and the log folder (R14.3) are the user's own account's alone (mode 0700), and so is the
    database file (0600); one that is there already and wider is narrowed when AppKata starts."
    A user who had opened either folder to another account on purpose loses that at the next start.
- `b85604c` (#275) and `88c1547` (#485) change nothing the user sees and no requirement.

### Needs a run

- The Windows suite, once, with batch 1's: `scripts/test-windows-vm.sh --tests`. New for it here:
    the line added to `tests/skips/windows.txt` for #434's test, and the tests of this batch that
    use real sockets.
- The screenshot tour and its layout and text checks, for Settings' longer help text (CI's `tour`
    job runs it on the push; locally `scripts/test-layout.sh`). Not run here: it builds into the
    worktree.

### Guard

- `tests/test_backend.py` (a shared file: add it to U07's files): #297's test of `Backend.setToken`
    needs a real Backend, and `tests/test_forges.py` runs where PySide6 isn't installed.
- `tests/test_requirements_trace.py` (no other unmerged unit claims it: add it to U07's files):
    #485's test is the existing check that every backend slot is used, read more strictly.
- `tests/skips/windows.txt` (no other unmerged unit claims it: add it to U07's files): the line for
    #434's Linux-only test, without which the Windows run fails on an unlisted skip.

### Doubts

1. **R3.1.1, not R3.2, R3.3 or R3.4.** The coordinator's note said whichever of those covers the
    icon, the screenshot and the README's images. None does: R3.2 is the icon, R3.3 the hero image,
    R3.4 the README's text. So it is a new item under R3.1, which names both images. The README's
    own images are fetched only as hero candidates: the README shown has its images taken out
    (`backend._plain_readme`).
2. **The local exception is now per address, and that is my reading, not a decision.** #266's
    decision says "unless it is the Source's own host". Batch 1 let through every port of a Source's
    name when the Source was on the default port, and only the Source's port when it was on one.
    With #297's "a host is one address" I made it the Source's own address in both cases (http's
    and https's own ports count as the same host, as `urls.parse` writes it), so a project on a
    local forge can't have AppKata ask another service on that machine. If the owner meant the
    name on any port, it is one line in `http._is_for` and the words "on the Source's own port" in
    R3.1.1; `test_on_a_local_forge_only_the_sources_own_address_may_be_local` pins it.
3. **#275: Http keeps what each host runs** (`Http.forges`, set by each Forge made), rather than
    every call passing the type. It is what lets Sync's image requests carry the right form with
    no change to `sync.py`. Two Sources on one host with different forge types set (R2.6.5): the
    Forge made last decides for both. A host runs one forge, so one of the two settings is wrong
    anyway.
4. **#275: the probes send the token in three forms.** Each of `forges.detect`'s API probes sends
    the host's own token in the form of the forge whose API it asks; the record's note said the
    probes and explore "keep the name test". The probes ask before the type is known, and by the
    name a GitLab that needs its token was never detected. Explore's searches pass their forge.
    The fourth probe (the home page) still goes by the name. #292's harness lets a probe carry any
    form (`probe()` in the tests).
5. **#275 was not run against a real forge.** How GitLab treats `Authorization: token` is still
    from its documentation; the stand-in forge is stricter than a real one (it takes one form only).
6. **#297: `token_key` does more than "document the key".** A pasted `https://host:3000/o/r` is
    kept as `host:3000`. Text that is no address (`git.example.org:port`) is kept as typed and
    never matches; the field doesn't refuse it. A token an earlier build kept under a spelling
    `token_key` changes (a pasted address, a typed `:443`) shows a row whose trash button doesn't
    remove it: nothing is carried over, as the brief says, and I left that case alone.
7. **#434: where the sentence went, and what is beyond the remedy.** The rule is in R11.1.6 (in
    this unit's files, and the finding's own citation); R1.8, which names the folders, is the other
    place and isn't in U07's files. The two log files are made 0600 too, which the remedy doesn't
    ask. Each app's own log under `logs/apps/` keeps its mode inside the 0700 folder. A chmod that
    fails (a folder another account owns) is passed over silently. A database outside the data
    folder is made 0600 and its folder left alone, so `DB()` never narrows a folder that isn't
    AppKata's.
8. **#292 against "a test that fails on the code before your commit".** The commit is tests only
    and passes on the commit before it: the four fixes were already in. What I showed instead is in
    the table: it fails on `ae63101` and on each of six one-fault copies.
9. **Two things I did outside the brief, both undone or harmless.** `git fetch upstream master`
    once (it moved nothing: still `ae63101`). And `sh scripts/python-standalone.sh --help`, meant
    to print its usage, ran the script: it fetched the release's Python from GitHub and pytest from
    PyPI into the worktree's `build/` (169 MB, ignored by git). I removed that folder; nothing of
    it is in a commit.

### The coordinator, after batch 2 (2026-11-24)

Checked: every answer of the agent on its named model; the guard; `tests/test_forges.py`,
`tests/test_backend.py`, `tests/test_requirements_trace.py` and the document tests, whole; the batch
pushed.

- **New:** the port lost by `urls.py:64` is filed as #690 and goes to U20, the unit that holds
    #280 and that line. The answer that is no image and is saved as one (`sync.py:44`) is #284's
    first part already, in U15: nothing to file.
- **Guard:** `tests/test_backend.py`, `tests/test_requirements_trace.py` and
    `tests/skips/windows.txt` are in U07's files now.
- **Doubt 2** (the local-address exception is the Source's own name and port) stands as built: it
    is the narrower reading and agrees with #297's key. It goes to the owner under Needs your eye.
- **Doubts 1, 3, 4, 6, 7 and 8** stand as built and are said in the pull request where the owner
    sees them (R3.1.1 as a new item; the token's form remembered per host; the probes; #434's
    sentence in R11.1.6). **Doubt 5** (#275 not run against a real forge) is said there too.
- **Doubt 9:** `scripts/python-standalone.sh` takes no `--help` and runs: don't call the project's
    build scripts to read their usage, read the script. Nothing was left behind.
- **Needs a run** (the Windows VM tests; the screenshot tour, which CI makes): the coordinator's,
    when the last batch is in.

## Batch 3

Files touched: `src/appkata_core/http.py`, `src/appkata_core/sync.py`, `src/appkata_core/forges.py`,
`src/appkata_core/metadata.py`, `src/appkata/backend.py`, `docs/requirements/R9-sync-and-updates.md`,
`tests/test_forges.py`, `tests/test_backend.py`.

Counts: 4 fixed, 0 no defect, 0 remedy changed, 0 set aside, 0 still left, 3 new.

Each new test was shown failing by exporting the commit before it with `git archive` to a scratch
folder, putting the new test files over it and running them there.

| Finding | Outcome | Commit | Tests (`tests/test_forges.py` unless said) | Before the fix |
|---|---|---|---|---|
| #269 | fixed | `ed83dbf` | `test_whatever_opening_or_reading_an_address_ends_in_http_gives_a_source_error`, `test_an_answer_cut_short_is_asked_for_again`, `test_through_real_sockets_an_address_that_cant_be_sent_and_an_answer_cut_short_are_unreachable`, `test_a_readme_images_own_path_is_written_as_an_address_can_be_sent`, `test_git_missing_or_too_slow_is_no_answer_from_it`, `test_with_no_git_on_the_path_there_is_no_answer_from_it`, `test_whatever_one_apps_sync_ends_in_wherever_the_sync_goes_on_and_its_row_says_so`, `test_a_forges_answer_of_another_shape_is_an_error_on_that_apps_row`, `test_an_error_on_an_apps_row_keeps_what_the_last_sync_stored`, `test_what_sync_app_itself_lets_out_is_passed_over_and_the_rest_are_synced`, `test_through_real_sockets_a_readme_image_that_cant_be_sent_as_written_doesnt_end_the_sync`, `test_through_real_sockets_a_source_whose_own_address_cant_be_sent_has_that_on_its_row`; `tests/test_backend.py`: `test_the_add_source_preview_answers_whatever_asking_the_forge_ends_in` | On `44f84d9`, both files: 163 failed, 277 passed, 5 errors (`InvalidURL`, `IncompleteRead`, `KeyError` and the rest left `sync_all`; the preview's thread ended with no answer, which is the 5 errors too) |
| #296 | fixed | `8dcc9ad` | `test_an_answer_that_comes_a_byte_at_a_time_ends_at_the_requests_deadline`, `test_the_deadline_counts_the_wait_for_an_answer_to_start`, `test_an_answer_that_comes_in_pieces_in_time_is_whole_and_the_size_limit_holds`, `test_r9_2_1_says_how_long_a_request_is_given_and_that_cancel_stops_one`, `test_a_cancel_is_its_own_threads_and_its_own_blocks`, `test_a_cancel_stops_a_request_before_it_is_asked_for_again`, `test_cancel_stops_a_sync_while_an_answer_is_still_being_read`, `test_through_real_sockets_a_byte_at_a_time_ends_at_the_deadline_and_at_cancel` | On `ed83dbf`: 15 failed, 421 passed (through real sockets the request ran the server's whole three seconds and came back with 60 bytes of a declared million: "DID NOT RAISE") |
| #277 | fixed | `c981377` | `test_a_retry_after_on_a_failing_answer_is_the_hosts_limit`, `test_a_retry_after_no_longer_than_the_retries_wait_is_waited_out`, `test_a_retry_after_on_another_answer_is_remembered_and_the_answer_means_what_it_did`, `test_a_sync_asks_a_host_that_said_when_to_come_back_once`, `test_a_host_that_gives_no_answer_is_unreachable_at_its_first_probe`, `test_through_real_sockets_a_503_that_says_when_and_a_host_with_nothing_listening`; holding what must stay: `test_a_failing_answer_that_says_nothing_is_asked_for_again_as_before`, `test_a_host_that_answers_but_not_as_a_forges_api_is_probed_to_the_end` | On `8dcc9ad`: 20 failed, 449 passed (a 503 with `Retry-After: 120` was asked three times and not remembered; a host with nothing listening was "couldn't tell which forge … runs") |
| #626 | fixed | `c131a22` | `test_an_answer_shorter_than_the_length_it_declared_is_cut_short_and_asked_for_again`, `test_an_answer_cut_short_once_is_whole_the_second_time`, `test_through_real_sockets_a_cut_off_image_isnt_saved_and_a_cut_off_readme_isnt_stored`; holding what must stay: `test_an_answer_that_is_whole_or_rightly_declares_what_it_doesnt_send_is_taken` | On `c981377`: 7 failed, 478 passed (100 bytes of a declared 1000 were saved as `icon.png`) |

Runs at the batch's head (`c131a22`), from the worktree's root:

- `tests/test_forges.py` whole: 485 passed. The seven files that use `Http` and the four document
    checks of the brief: 631 passed. Both before each commit.
- The whole suite with the project's `.venv` (`pytest -q tests/`, no skip list): 3261 passed, 39
    skipped, in 2 min 52 s.
- The whole suite in the tier 1 image with no network and 3 GB (`docker run --network none
    --memory=3g`, `APPKATA_SKIPS=tier1`, the main checkout's `build/python-3.14` and
    `build/pyside-6.12.0-py3.14` mounted read-only, and its `.git` read-only at its own path, so the
    five tests batch 2 saw fail on a worktree's `.git` pass): 3179 passed, 121 skipped, in 1 min 58 s.
    `scripts/test-tier1.sh` itself was not run, as in batches 1 and 2.
- The guard passed before each commit, naming only `docs/relay/`.

How the design fits together, for batch 4:

- **Every error of a request is a SourceError**, and its `extra` says what kind, so no caller reads
    an error's words: `status` (an HTTP status), `timeout`, `deadline` (not asked for again), `cut`
    (an answer cut short, chunked or by its Content-Length: asked for again), `no_answer` (nothing
    came back at all: what `forges.detect` stops on), `retry_after` (a short Retry-After, which the
    retry waits out). `Http.request` retries after `http.WAITS`. #298's table has these branches to
    pin, and #683's 401 is beside them in `_request`.
- **`Http.stopping(cancelled)`** is a block, and its Cancel is the thread's own. `http.Cancelled` is
    a BaseException: `except Exception` and `except SourceError` don't catch it, and `sync_all`'s
    `one()` does.
- **The read** is `Http._read`: read1, a piece at a time, the clock and Cancel before each piece.
    What comes before the body (connecting, the headers, a redirect) is still urllib's own: the
    first item under New. #682's connection classes are where that can be closed.
- **The tests' harness** (`tests/test_forges.py`): `clock` (Http's clock and waits, stepped, nothing
    waits), `ending_in` (an opener whose every request ends in an error, opened or read),
    `answering` (an error status with chosen headers), `declaring` (an answer with chosen headers),
    `Dripping` (a byte a read), `catalog`, `rows`, `at` and `synced_but` (a whole `sync_all` of
    `three_forges()` with one place of one app's sync changed), and, through real sockets,
    `forgejo_project` on the `pair` servers, whose `files` now make one a stand-in forge (a path's
    bytes, its JSON, or a function that writes the answer itself). #293's whole-Sync tests can
    start from `synced_but`: about a hundred cases call `sync_all` now, where none did.

### New

- `src/appkata_core/http.py:361`, `_request`, `with self._open(req, timeout=self.timeout)`: the
    deadline and Cancel cover an answer's body, and not what comes before it. A host that sends
    its status line and headers a byte at a time (each within the 20 second timeout) holds the
    request until its headers end, and Cancel can't stop it: #296's own effect, by another way.
    Run, in a scratch script with real sockets: headers sent a byte every 20 ms for 4.5 seconds,
    `Http(timeout=2.0, deadline=0.4)`: the request ended after 4.5 seconds, when the server
    closed. http.client allows 100 header lines of 64 KiB each, so the hold has no practical end.
    Not fixed: the wait is inside urllib's opener, and ending it needs Http's own connection
    classes (a socket whose every read is held to what is left of the deadline, or one that a
    Cancel can close), which is what #682 builds in batch 4. More than small.
- `src/appkata_core/sync.py:56-61`, `_save_image`: the old image file is removed and the new one
    written before the app's row is. An app whose sync then ends without writing its row, and
    whose new image has another extension (`icon.png`, now `icon.svg`), keeps a row that names a
    file that is gone: no icon until its next whole Sync. Two ends of that kind are this batch's
    (a Cancel, #296; an unexpected error after the icon is saved, #269, where the whole Sync ended
    at that spot before). Low. Not fixed: #284 (U15) changes those lines.
- `src/appkata_core/http.py:347`, `_request`, `host = parts.hostname.lower()`: `Http.limited` is
    keyed by a host's name without its port, where a token, a forge type and the local-address
    rule take a host as one address (#297). A limit of `git.example.org:3000` refuses requests to
    `git.example.org`, and the other way round; `forges.GitHub._api_limited` reads the same key.
    Low, and more reachable now that any failing answer's Retry-After sets a limit (#277). Not
    fixed: no finding of this batch is about the key.

### Needs your eye

- `ed83dbf` (#269), what the user sees: four new texts on a Source's row, all of the kind
    `Unreachable`. "unexpected error (KeyError: 'name'); the app log has the details", which the Add
    source dialog shows too; "couldn't ask <host>: the address '<address>' can't be sent
    (InvalidURL)"; "couldn't read <host>'s answer (BadStatusLine: …)"; "<host> cut its answer
    short". A README image written with a space or with letters outside ASCII is fetched now, and
    can be the hero. No requirement's text changes: an unexpected error is R2.10's `Unreachable`,
    as the record says, and a new kind would have been a refine.
- `8dcc9ad` (#296), the text: R9.2.1 gains "A request is given two minutes for the whole of its
    answer, however steadily the answer keeps coming: one that takes longer is given up, as an
    `Unreachable` error (R2.10) or, for an image, passed over for the next one. **Cancel** stops
    the requests under way as well, an answer that is still being read included: an app whose sync
    it stops keeps what the last Sync stored." The two minutes are mine: the remedy names no
    number (doubt 2). `docs/requirements/R9-sync-and-updates.md` is in U07's files and not in
    #296's record: the brief asks for the rule where the user can read it.
- `8dcc9ad` (#296), what the user sees: "<host> hadn't finished its answer after 120 seconds" on a
    row; and Cancel ends a Sync within one read of each worker's answer, where it waited for
    every app under way.
- `c981377` (#277), what the user sees: a Source on a host that gives no answer reads "couldn't
    reach <host>: …" (`Unreachable`), where it read "couldn't tell which forge <host> runs; set the
    forge type in Source settings" (`Unsupported`). A forge that answers a 5xx with Retry-After
    reads "Rate limited until 14:32 · add a token in Settings", the text every `RateLimited` has:
    its second half doesn't fit a forge that is being maintained (doubt 8). No requirement's text
    changes: R9.2.1 already says Retry-After is respected.
- `c131a22` (#626), what the user sees: "<host> cut its answer short (100 of 1000 bytes)", where a
    cut-off JSON answer read "<host> didn't return JSON". No requirement's text changes.

### Needs a run

- The Windows suite, once, with batches 1 and 2's: `scripts/test-windows-vm.sh --tests`. New for
    it here: the tests through real sockets (a stand-in forge, a server that sends a byte every
    50 ms with a 0.4 second deadline and a two second bound on the test, a port where nothing
    listens), and `test_with_no_git_on_the_path_there_is_no_answer_from_it`, which empties `PATH`
    for one real `subprocess` call. No test of this batch is skipped anywhere, and no skip list
    changed.

### Guard

Nothing: every file changed is in U07's files.

### Doubts

1. **#296 is fixed as its remedy says, and the same hold is open through the headers** (the first
    item under New). The finding's own run, a body sent a byte at a time, ends at the deadline
    and at Cancel. I would not call the class closed until what comes before the body is under
    the same clock; I left it because it is #682's kind of change, not a line in `_read`.
2. **The deadline is 120 seconds, by my choice**, and is `Http(deadline=…)`. An image may be 8 MiB:
    on a link slower than about 560 kbit/s a full-size one is given up. Shorter is safer against a
    hostile host and harder on a slow link. A project can name up to twelve images (six icon
    candidates, six hero ones), so a host that drips each one to just under the deadline still
    holds a worker for twenty-four minutes an app; Cancel stops it now.
3. **Cancel stops the apps' requests, and nothing else of a Sync.** The Trusts' part (a key
    lookup; the fetch is git's, not Http's) and the package channels' part run outside a
    `stopping` block, and `_git_out`'s two minutes can't be interrupted. I kept to `one()`: the
    Trust loop is #229's (U08) and the channels are other units'. Each of their requests has the
    deadline. A Sync cancelled among its apps still writes the time of the last Sync
    (`sync.py:471`), as before; among its Trusts it doesn't.
4. **`Cancelled` is a BaseException, and the Cancel is a thread-local of the one Http.** Both are
    choices between two ways to the same behaviour. As an Exception it would be caught by
    `forges.detect`'s probes, the three "keep it" handlers of the GitHub pages and `sync_app`'s
    own catch-all, each of which would have to pass it on. A client of the Sync's own (a copy with
    its Cancel) would have split `calls` and the tokens a `setToken` replaces mid-Sync.
5. **#269's record says the app whose README has `<img src="a b.png">` gets an `Unreachable` on
    its row.** With the remedy as written it doesn't: Http gives an error the hero loop passes
    over, and `resolve` quotes the path, so the image is fetched and the app is stored whole. The
    row's error is shown with the other causes: a Source whose own path has a space, a forge's
    answer of another shape, and any error at any place of an app's sync.
6. **`metadata.resolve` quotes a relative path only.** An absolute address with a space or a letter
    outside ASCII (a README's `<img src="https://…/a b.png">`, a metainfo's icon) is refused by
    Http as one that can't be sent and passed over, where a browser would quote and fetch it.
    #681 (batch 4) changes that branch.
7. **#277, the probes: the remedy's second way.** `detect` stops at the first probe with no
    answer, as the record's proof says; that probe is still asked three times when it times out,
    about a minute for each app on a dead host at every Sync, four at a time (it was over four
    minutes). The remedy's first way, no retry inside `detect`, would make it 20 seconds and
    needs `request` to take a "don't retry". "No answer" is also a TLS failure and a timeout of
    the first probe alone: `detect` stops there though the other three might have answered.
    `detect` is now one `ask` and four tests of its answer, which #278 (U20) will meet when it
    changes the probes; its third proof ("a host no probe can connect to raises Unreachable") is
    already true.
8. **#277, "and any answer".** A 5xx with a Retry-After over three seconds is `RateLimited` and
    isn't retried. A 404, a 401 and another 4xx with one keep their own meaning and the limit is
    remembered, so the next request is the one refused: Retry-After means nothing certain on
    those. A Retry-After that can't be read counts as a minute, and none has an upper bound, both
    as `_reset_time` already did for a 429: a host can lock itself out until AppKata restarts.
    The row's text for a forge being maintained ends "add a token in Settings"
    (`backend._error_text`), which isn't in #277's files.
9. **#626 leaves an encoded body alone, as the record's note says.** urllib doesn't decode, so a
    gzip body's count would be right too, and a cut-off one is still taken for whole. Http never
    asks for an encoding, so one arrives only from a host that sends it unasked.
10. **`backend.py` has other worker threads.** Only the Add source preview got the catch-all (the
    record names it). I didn't go through the others for the same end.
11. **The four new row texts carry Python's own words** (`KeyError: 'name'`, `InvalidURL`,
    `BadStatusLine`). They are for the app log as much as for the row; plainer words would be a
    choice of wording.
12. Nothing outside the brief was run. Scratch files were under `/tmp` and nothing is left
    running. `.pytest_cache/` and the `__pycache__` folders in the worktree are git's ignored
    ones, from the brief's own `pytest` commands.

### The coordinator, after batch 3 (2026-11-24)

Checked: every answer of the agent on its named model; the guard; `tests/test_forges.py` and the
document tests, whole; the batch pushed.

- **New findings filed:** #695 (the headers escape the deadline and Cancel) and #697
    (`Http.limited`'s key) join this unit as a new batch 5, with #682, since all three are in Http's
    own connection and records. #696 (the image file removed before the row is written) goes to
    U15, which holds #284 and those lines.
- **Batch 4** is now #265, #298, #293, #683 and #681. **One more thing for batch 4**, as a
    follow-up commit to #277 (doubt 12 of batch 3): a 5xx answered with Retry-After shows "Rate
    limited until … · add a token in Settings", and the second half doesn't fit a forge that is
    being maintained. The text is in this unit's files: say only when to try again for a 5xx, keep
    the token hint for a real rate limit, with a test, and list the new text under needs your eye.
- **The doubts on #296, #269 and #277** (the 120 seconds, now in R9.2.1; Cancel stops the apps'
    requests only; `Cancelled` and `Http.stopping`; no row error for the README-image case;
    `detect` stopping at the first probe with no answer) stand as built and go to the owner under
    Needs your eye in the pull request.
- **Needs a run** (the Windows VM tests): the coordinator's, when the last batch is in.

## Batch 4

Files touched: `src/appkata_core/forges.py`, `src/appkata_core/sync.py`, `src/appkata_core/http.py`,
`src/appkata_core/metadata.py`, `src/appkata/backend.py`, `tests/test_forges.py`,
`tests/test_backend.py`. No requirement's text changed.

Counts: 5 fixed (two of them tests only), 0 no defect, 0 remedy changed, 0 set aside, 0 still left,
3 new. The follow-up to #277 that the coordinator's notes asked for is its own commit, and #683 has
three follow-up commits (doubt 8).

Each new test of a fix was shown failing by exporting the commit before it with `git archive` to a
scratch folder, putting the new test files over it and running them there. The two findings whose
fix is tests were shown to hold something on copies of the code with one fault put in each (a
scratch script: the module rewritten in a scratch copy of the tree, the new tests run there).

| Finding | Outcome | Commit | Tests (`tests/test_forges.py` unless said) | Before the fix |
|---|---|---|---|---|
| #265 | fixed | `601e34f` | `test_a_github_on_another_host_takes_no_files_from_github_coms_project_of_its_path`, `test_every_way_to_github_coms_pages_is_refused_for_another_host`, `test_a_sync_and_a_file_list_of_an_enterprise_source_ask_nothing_of_github_com`, `test_github_com_itself_reads_its_page_when_its_api_says_to_come_back_and_only_then`; holding what must stay: `test_a_github_on_another_host_has_its_own_apis_files`, `test_github_com_known_to_be_limited_is_asked_for_its_page_alone` | On `0a1dc78`: 38 failed, 515 passed (github.com was asked for the Enterprise project's path and its files were stored: "DID NOT RAISE SourceError") |
| #277, the follow-up | done | `995c79e` | `test_what_said_when_to_come_back_is_kept_with_the_limit`, `test_a_limit_nothing_gave_a_status_for_has_none`, one more line in `test_a_sync_asks_a_host_that_said_when_to_come_back_once`; `tests/test_backend.py`: `test_a_rate_limit_hints_at_a_token_and_a_forge_being_maintained_says_only_until_when` | On `601e34f`, both files: 13 failed, 574 passed (the three 5xx rows read "… · add a token in Settings") |
| #298 | fixed (the tests are the fix) | `9cdaec5` | `test_what_http_makes_of_each_answer` (a table, 61 rows then, 64 now), `test_the_table_has_a_row_for_each_kind_of_error_and_each_thing_a_retry_turns_on`, `test_when_a_host_may_be_asked_again_is_read_from_its_headers`, `test_a_limited_host_is_refused_without_being_asked_until_its_time_has_come`, `test_a_time_to_come_back_that_has_gone_by_limits_nothing`, `test_what_a_request_carries`, `test_a_request_with_a_method_a_body_and_headers_of_its_own`, `test_how_large_an_answer_may_be_and_how_long_a_request_is_given`, `test_an_image_larger_than_an_image_may_be_is_passed_over` | Passes on the commit before it, as tests of right behaviour do. On 60 copies of `http.py` with one fault each: failed on 58; the two it passed (a limit ending a second early, a request's method not passed on) each got an assertion and fail now. On the code before this unit (`ae63101`): 41 of its 93 cases fail |
| #293 | fixed (the tests are the fix) | `2b0f7d4` | `test_what_a_sync_stores_for_an_app`, `test_the_images_are_tried_in_r3_2s_and_r3_3s_order_and_no_others`, `test_the_first_image_that_answers_is_the_one_kept`, `test_an_app_keeps_the_icon_it_had_when_none_answers`, `test_a_project_that_says_nothing_of_itself_is_stored_as_its_forge_describes_it`, `test_a_metainfo_whose_name_is_a_placeholder_leaves_the_forges_name`, `test_a_project_that_moved_has_where_to_on_its_row`, `test_tags_stand_in_for_releases_only_where_the_source_tracks_them`, `test_a_hosts_forge_type_is_found_once_and_kept_for_the_next_sync`, `test_an_app_a_trust_lists_keeps_the_forge_type_found_for_it_too`, `test_the_forge_type_is_the_sources_setting_then_a_trusts_then_the_one_found`, `test_a_sync_reads_the_trusts_first_and_syncs_every_app_of_the_catalog_once`, `test_at_most_four_apps_are_fetched_at_the_same_time`, `test_a_sync_cancelled_before_it_starts_asks_for_nothing`, `test_a_sync_cancelled_between_two_apps_leaves_the_rest_as_they_were`, `test_the_package_channels_are_read_once_after_the_apps_and_never_end_a_sync`, `test_a_source_that_is_no_forges_project_has_that_on_its_row`, `test_each_probe_of_a_hosts_forge_type_in_its_order`, `test_a_host_appkata_knows_is_never_probed`, `test_a_whole_sync_of_a_github_project_by_its_pages_and_git`, `test_by_the_pages_a_projects_tags_come_from_git_newest_version_first`, `test_by_the_pages_a_project_that_moved_is_renamed` (94 cases) | Passes on the commit before it. On 58 copies of `sync.py` and 28 of `forges.py` with one fault each: failed on all but four. Two of the four got an assertion and fail now (a Cancel not looked at before an app that asks for nothing; a release's own date by the pages). The other two change nothing these tests could see: a prerelease marked on the releases page alone (an earlier test fails on it) and a front-page marker that a wider one beside it covers |
| #683 | fixed | `01d57ef`, then `b637650` (a test row), `1d3ce29` (the rest of its class) and `ca3c7d0` (a date held as a number is) | `test_through_real_sockets_an_error_after_a_redirect_is_the_last_hosts_and_the_tokens_only_if_it_went_there`, `test_a_401_with_no_token_sent_is_never_the_tokens`; in `1d3ce29`: `test_through_real_sockets_whatever_a_request_ends_in_after_a_redirect_is_said_of_the_host_it_led_to`, `test_through_real_sockets_a_redirect_to_where_nothing_listens_is_that_hosts_failure`; for the two faults of `_reset_time` fixed with it: `test_a_time_no_clock_can_show_never_reaches_a_sources_row`, three rows of #298's table, ten of `_reset_time`'s, one case of the backend's test, and in `ca3c7d0` `test_whatever_a_host_says_and_wherever_the_clock_is_the_time_to_come_back_is_one_a_clock_shows` | On `2b0f7d4`, both files: 18 failed, 779 passed (4 of them the finding's: "127.0.0.1 rejected the API token (HTTP 401)" for the second host's 401; 14 the reset time's). `1d3ce29`'s on `b637650`: 8 failed, 804 passed. `ca3c7d0`'s on `1d3ce29`: 2 failed (the two zones east of Greenwich), 860 passed |
| #681 | fixed | `be6b3d0` | `test_an_address_that_is_no_github_page_of_a_file_is_asked_for_as_its_readme_wrote_it`, `test_a_github_page_of_a_file_becomes_the_address_of_the_file`, `test_a_whole_address_is_written_as_an_address_can_be_sent_too`, `test_a_sync_asks_for_a_readmes_images_on_other_hosts_as_they_are_written` | On `01d57ef`: 22 failed, 782 passed (the finding's two addresses rewritten, and eleven more) |

Runs at the batch's head (`ca3c7d0`), from the worktree's root:

- `tests/test_forges.py` whole: 862 passed. With `tests/test_backend.py` and the four document
    checks of the brief: 914 passed. Before each commit: the files it touched and the four document
    checks; before #265's, #277's, #683's and #681's, the five other files that use `Http` and
    `tests/test_requirements_trace.py` as well.
- The whole suite with the project's `.venv` (`pytest -q tests/`, no skip list): 3645 passed, 39
    skipped, in 3 min 15 s.
- The whole suite in the tier 1 image with no network and 3 GB (`docker run --network none
    --memory=3g`, `APPKATA_SKIPS=tier1`, the main checkout's `build/python-3.14` and
    `build/pyside-6.12.0-py3.14` mounted read-only, and its `.git` read-only at its own path, as in
    batch 3): 3563 passed, 121 skipped, in 2 min 35 s. `scripts/test-tier1.sh` itself was not run, as in the earlier batches.
- The guard passed before each commit, naming only `docs/relay/`.

How the design fits together, for batch 5:

- **`req.asked`** (`Http._request`, `http._Redirects`): a dict on the request, shared by every hop,
    with the address and the host asked last and whether the token went there. `_Redirects` moves
    it on at each redirect. Every error of `_request` is said of `asked["host"]`; `host`, the one
    asked first, is still the key of `Http.limited` and the host a `RateLimited` names (the second
    item under New, which is #697's subject). #682's connection classes can check the address a
    socket reached at the same place.
- **`RateLimited(host, reset, status)`**, `Http.limit_status` (host to the status that set its
    limit, beside `Http.limited` and under the same key) and `http.LIMIT_STATUSES` (403, 429): #697
    changes both dicts' key together.
- **`_reset_time`** takes a value only when it is a plain number or a date, and a time the
    platform's clock can show in this time zone (`http._a_time`).
- **`GitHub._page()`** is the one place a github.com page address is made, and refuses another host.
- **The tests' harness** (`tests/test_forges.py`): `scripted` (an opener that sends what each case
    says, an answer a request, and records the request objects), the table `ANSWERS` with `answer`,
    `failing` and `limit` (a new branch of `_request` gets a row; `test_the_table_has_a_row_…` names
    what the rows must cover), `widget(forge)` (one project with everything a Sync reads, as each
    forge serves it, its images in R3.2's and R3.3's order), `sync_of`, `kept`, `own_reviews`,
    `saying(status)` for the `pair` servers, and the `git` fixture (a stand-in for
    `forges._git_out`).

### New

- `src/appkata_core/forges.py:225` and `:231`, `GitHub._releases_web`: `pre`, the count of
    prereleases whose files were read, is overwritten at each feed entry by that entry's own
    prerelease flag, so `pre < 1 and rel.prerelease` is never true: by github.com's pages no
    prerelease's files are read at a Sync, where the comment above says the newest one's are. Run,
    in a scratch script: a feed of `v2.0.0-rc1` and `v1.0.0`, each with a file on its assets page:
    the assets page of `v1.0.0` alone was asked for, and `v2.0.0-rc1` was stored with no files.
    Low: its files are read when the version is opened (`ensure_assets`). Not fixed: found after
    #265's commit, and no finding of this batch is about those lines.
- `src/appkata_core/http.py:400` and `:413`, `_request`: a limit is kept for the host asked first,
    whichever host answered. A file that a forge redirects to another host (object storage), which
    answers 429 or a 5xx with a Retry-After, limits the forge itself: its API is refused for every
    app until then, and the storage host is asked again by the next redirect. Run, in a scratch
    test through real sockets: A redirects to B, B answers 429 with `Retry-After: 120`:
    `http.limited` was `{A: 120 seconds from now}`, and A's own API was refused next without a
    request. Low. Not fixed: it is the key of `Http.limited`, which is #697's (batch 5).
- `src/appkata/backend.py:709-718` (`install`'s worker) and `:737` (`_plan`), with
    `sync.ensure_assets` (`src/appkata_core/sync.py:380`): the worker of a first install catches a
    `SourceError` alone. A forge's answer of another shape for a release's files ends the thread
    with nothing handed back, so the Install button does nothing and says nothing: #269's fault,
    in the one worker batch 3's tenth doubt left. Run, in a scratch script: a release list that is
    `["a", "list"]` on a Forgejo, and a GitHub Enterprise's release that is a list:
    `ensure_assets` raised `AttributeError`, which is no `SourceError`. Low. Not fixed: no finding
    of this batch has `backend.py`'s workers.

Fixed here though no finding's, each said in its commit: the two faults of `_reset_time` (`01d57ef`:
a Retry-After of "²" raised a `ValueError` out of Http; one of thirty nines was kept as the time and
made `backend.sourceItems` raise an `OverflowError`, so the Sources list showed nothing while that
row's error stood); and a whole README image address with a space or a letter outside ASCII, which
Http refused (`be6b3d0`, batch 3's sixth doubt). The coordinator may want an issue for the first,
for the record: it was reachable by any Source's host.

### Needs your eye

- `601e34f` (#265), what the user sees: for a Source on a GitHub Enterprise, or on any host whose
    forge type is set to GitHub, an install of a release stored without files shows the forge's own
    error when its API fails ("<host> rejected the API token (HTTP 401)", "… not found", "couldn't
    reach <host>: …"), where it went on with whatever github.com listed under the same path. For
    github.com itself the pages are read when the API says to come back later, as R2.4.1 says, and
    any other failure of the API is now an error at that step (it fell to the pages on a 404, a
    401 and a timeout too). No requirement's text changes: R2.4.1 has the pages under github.com
    alone.
- `995c79e` (#277's follow-up), what the user sees: a Source whose forge answered a 5xx with a
    Retry-After reads "Rate limited until 14:32", R2.10's own words, and no longer "… · add a token
    in Settings"; a 403 or a 429 keeps the hint. The error's own words, which the install plan and
    the Add source dialog show, are "<host> answered HTTP 503 and said when to come back" for such
    an answer. Both rows of two Sources on that host read the same.
- `01d57ef` and `1d3ce29` (#683), what the user sees: after a redirect, an error names the host
    the redirect led to: "<that host> answered HTTP 401" where it said "<the Source's host>
    rejected the API token (HTTP 401)", and likewise "couldn't reach", "cut its answer short",
    "didn't return JSON" and the rest. "rejected the API token" is said only of a host that was
    sent the token.
- `01d57ef`, what the user sees: a Retry-After or reset time that can't be read, or is no time a
    clock can show, counts as a minute, as "soon" already did.
- `be6b3d0` (#681), what the user sees: a README image on another host is asked for at the address
    its README wrote; a link to a file's page on `www.github.com` is fetched (it never was); and a
    whole address with a space or a letter outside ASCII is fetched, so it can become the hero.
- `9cdaec5` (#298) and `2b0f7d4` (#293) are tests and change nothing.

### Needs a run

- The Windows suite, once, with the earlier batches': `scripts/test-windows-vm.sh --tests`. New for
    it here: the tests through real sockets of a redirect that ends in each kind of error (one
    drips a byte every 50 ms against a 0.3 second deadline); the eight Sources whose first requests
    wait for one another on a `threading.Barrier` (ten seconds at most); a review file read from
    the test's folder; one test that turns the package channels on with their three steps stubbed
    (`channels.enabled` is false on Windows by itself); and `_reset_time`, which now asks the
    platform whether a number is a time (`datetime.fromtimestamp`): the times the tests expect back
    are in 2001, 2015 and 2100. The time zone test sets the zone with `time.tzset`, which Windows
    doesn't have: there it runs in the machine's own zone, with nothing skipped. No test of this
    batch is skipped anywhere, and no skip list changed. `tests/test_backend.py` doesn't run there
    (no PySide6).

### Guard

Nothing: every file changed is in U07's files.

### Doubts

1. **#265 narrows github.com too.** The remedy's "best" way, through `_try`, makes `ensure_assets`
    fall to the pages on a `RateLimited` alone, as a Sync's own calls do and as R2.4.1 says. Before,
    github.com's pages also answered for a 404 (a tag with no release), a 401 and a timeout of the
    API. A tag the pages listed and the API doesn't know now ends the install with "… not found"
    where it ended with no download found. The remedy's first way (the host test in
    `ensure_assets`, every failure still falling to the pages for github.com) is the other reading.
2. **#265: a `RateLimited` is also a 5xx with a Retry-After** (since #277), so github.com's API
    being maintained sends `ensure_assets`, and every call of `_try`, to the pages. That reads as
    R2.4.1's intent ("come back later") and isn't its words ("rate limit is used up").
3. **#265's refusal is an `Unsupported`** ("github.com's pages stand in for github.com's API alone,
    and <host> isn't github.com"). Nothing reaches it today: it is there for the next caller.
4. **The follow-up's text.** "Rate limited until 14:32" for a forge being maintained is R2.10's
    text without the hint, as the note asked ("say only when to try again"). Truer words
    ("Unavailable until 14:32") would be a new row of R2.10's table, which is the owner's. A
    limit with no status (none arises in the application) keeps the hint. A 404 or a 401 with a
    long Retry-After limits the host too (#277): the apps refused after it read "Rate limited
    until …" without the hint.
5. **#298's table repeats some of batch 3's cases**, on purpose: it is one place that says what
    every answer becomes. It pins each error's words exactly, so a change of wording fails a row.
6. **#293 is in `tests/test_forges.py`, not a new `tests/test_sync.py`.** The record allows either.
    The Sync harness, the stand-in servers and the fixtures are that file's, and the earlier
    batches' hundred Sync cases are there. The file is 2,800 lines now; splitting it is a move for
    after the unit, with `scripts/areas.py`.
7. **What #293 pins that open findings will move.** The releases' order (by date; the project's
    dates and versions agree, so #267's change shouldn't break it, apart from where `nightly`
    sorts); the error kinds on a row (`Renamed`, `NotFound`, `Unsupported`, `RateLimited`: #273);
    the probes (#278: only real generator and site-name tags are in the table). Not pinned: a hero
    lost to one failed request and a non-image saved as one (#284), the order of dateless tags
    (#267), whether a cancelled Sync writes the time of the last Sync.
8. **#683 has four commits.** The fix as the remedy says it (`01d57ef`); a test row made
    independent of the platform's clock (`b637650`); the rest of the class (`1d3ce29`): I had fixed
    the failing status and left "couldn't reach", "cut short" and the others naming the first
    host; and `_reset_time`'s date branch (`ca3c7d0`), which I had left out of the test of being a
    time. Both later ones came from reading my own commit again after the suite had run. One
    commit would have been tidier; the brief says never to amend.
9. **#683 doesn't move a limit** (the second item under New): `RateLimited` and `Http.limited`
    still go by the host asked first. A 404's words name the address the redirect led to now.
10. **`_a_time` asks the platform.** Whether a number of seconds is a time is
    `datetime.fromtimestamp`'s answer on this computer in its time zone, since the same call shows
    it on the row. A time that Linux shows and Windows doesn't (past the year 3000) counts as a
    minute there. A zone changed while AppKata runs could still move a time at the very edge.
    `backend._error_text` still trusts the number on the row: what a Sync writes is now always a
    time, and a row another build wrote isn't looked after.
11. **#681 keeps the README's scheme**: an `http://github.com/…/blob/…` link becomes
    `http://raw.githubusercontent.com/…`, as before. A host written outside ASCII isn't handled;
    only the path and the query are quoted.
12. **R9.2.1 says four hosts; the code runs four apps.** Four apps of one host run together too.
    The new test pins four apps on eight hosts, which is true under either reading.
13. **The one-fault copies are mine**, 146 hand-written faults in three modules, not the project's
    mutation run (its container is capped at 6 GB, over this relay's 3). They show the new tests
    fail when the code is wrong in those ways, and no more.
14. Each "before" run changed folder to its scratch copy inside its own command (in a subshell,
    all but the first); every `git` command ran from the worktree's root, with the folder and the
    branch checked before each commit, as the coordinator's message asked. Scratch files were
    under `/tmp/u07b4`, removed at the end; the one container this batch started
    (`u07b4-tier1`, three times, one after another) ended with its run. `.pytest_cache/` and the
    `__pycache__` folders in the worktree are git's ignored ones.
