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

