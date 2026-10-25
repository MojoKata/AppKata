# App sandboxing — review findings (handoff)

Review of PR #3 (`app-sandboxing` → `master`) at commit f94bcfc, 2026-10-10, followed by the fixes.

> Rounds one to nine (2026-10-10/12). Review 2 (2026-10-17, the requirements against the code, at
> 76edcf4) is in [`app-sandboxing-2.md`](app-sandboxing-2.md), and reopens the PR with two HIGH
> findings: F1, a never-shared bypass; and F2, the AppArmor model on Ubuntu 26.04.

## Results

Every finding of rounds one to nine is fixed or closed, and nothing of this file is open (since
2026-10-12). Each pass: when it was reviewed and at which commit, what it found, when and where it
was fixed, and the tiers at its end (tier 1 · tier 2 · tier 3, passed / skipped; "Mint 21.3" is tier
2b). The commits of each pass, one per finding, are in the section the last column names, and each
finding has its own **Status** line.

| Pass | Reviewed | Found | Fixed | Tiers at the end | Recorded in |
|---|---|---|---|---|---|
| The first fix pass | 2026-10-10, before f94bcfc | two escapes (016476a, cf0ccb8) and the rest of its table; one suspicion disproved (f3ccf8a) | 2026-10-10, 016476a..ace1f40 | tiers 2 and 3: 38 / 1 | "The first fix pass", below |
| Round one | 2026-10-10, at f94bcfc | findings 0 to 8 (0 and 1 HIGH; 2 to 4 MEDIUM; 5 to 8 LOW), notes A to C | 2026-10-10, 0050a15..d0f61c4; finding 0 decided by the owner (option a) and done in 15ae403, 2026-10-11 | 266 / 55 · 48 / 1 · 48 / 1 (after finding 0) | "For the reviewer of the fixes"; "Finding 0: option (a), done" |
| Round two | 2026-10-10, at 525208e | R1 to R10 (one HIGH, three MEDIUM, six LOW) | 2026-10-10, c8cdbe3..c4dd595 | 264 / 53 · 46 / 1 · 46 / 1 | "Round two fixes" |
| Round three | 2026-10-11, at c2ff54f | R3-1 to R3-6 (two MEDIUM, four LOW) | 2026-10-11, ea1cfa9..03305dc | 269 / 57 · 50 / 1 · 50 / 1 | "Round three fixes" |
| Round four | 2026-10-11, at 7323c5e | R4-1 to R4-9 (one HIGH, three MEDIUM, five LOW) | 2026-10-11, a8bcd3e..667f545 | 283 / 63 · 56 / 1 · 56 / 1 | "Round four fixes" |
| Coverage after round four | 2026-10-12 | one bug, by the first harness (4de6722) | 2026-10-12, f695fbb..a1cfe4e | 1,944 / 63 · 56 / 1 · 56 / 1 | "Coverage after round four"; "Merge readiness" |
| Round five | 2026-10-12, at 6cf30c1 | R5-1 (MEDIUM), R5-2 to R5-6 (LOW), R5-7 | 2026-10-12, 5b95a62..cbb7860; its harnesses c7368c9..53e9075, three of which found something, each fixed or stated | 2,034 / 79 · 71 / 1 · Mint 21.3 67 / 1 · 71 / 1 | each finding's Status; "Coverage after round five" |
| Round six | 2026-10-12, at 9572629 | R6-1 and R6-4 (MEDIUM), R6-2 and R6-3 (LOW) | 2026-10-12, 04eae96, 86847ef, f287c44, 09626af | 2,039 / 84 · 76 / 1 · Mint 21.3 67 / 1 · 75 / 2 | "Round six fixes"; "Coverage after round six" |
| Round seven | 2026-10-12, at c5a0c77 | R7-1 (MEDIUM) | 2026-10-12, 42e1933; 7ef036b and 8936e48 ran the claims only read | — | "Round seven fixes"; "Coverage after round seven" |
| Rounds eight and nine | 2026-10-12 | no finding (round eight fixed a test's assertion for Python 3.13) | — | 2,042 / 90 · 81 / 2 · 81 / 2 | "Round Eight", "Round Nine"; "Confidence" |

Review 2 (2026-10-17) reopened the PR with two HIGH findings; its results are in
[`app-sandboxing-2.md`](app-sandboxing-2.md), and review 3's in
[`app-sandboxing-3.md`](app-sandboxing-3.md).

## Status, round by round

**Where this stands (2026-10-12, after round nine):** rounds seven to nine ran in the same session over
what round six left and the classes it pointed at. One finding, R7-1 (MEDIUM): on KDE Wayland a
sandboxed app reads the clipboard — kwin 5.27 and 6.3 offer the clipboard-manager protocol to every
client — so the session warning clears GNOME alone and names the clipboard on KDE. Every claim that
had only been read is run now but one (Electron's own dialog); the launcher tier runs on four
platforms; the product's own install path is driven end to end under bwrap; and a "Confidence"
section at the very end says what the sandbox delivers, what it says it doesn't, and what is still
owed (the pkexec prompt, NVIDIA, Obsidian's dialog, the security-context protocol, a first release).
Nothing is open against the PR.

**Where this stood (2026-10-12, after round six):** round six, run in the same session over the areas
round five named, found four items — two of them *by* building its harnesses — and fixed all four
(R6-1 one id per install, MEDIUM; R6-2 the camera promise; R6-3 tray names past pid 3; R6-4 GTK 4.18
with no file dialog, MEDIUM: the launcher now sets `GDK_DEBUG=no-portals`), with every harness built:
see "Round Six Review" and "Coverage after round six" at the very end. Nothing is open against the
PR. Tiers at the end of round six: 1 — 2,039 passed, 84 skipped; 2 — 76 / 1; 2b — 67 / 1 at db671ff;
3 — 75 / 2 (the disk-full test needs the container's tmpfs, the camera one its node); `filedialogs`, `filedialogs-qt68`, `consumers`, `wayland` — `EXPECTED: ok`.

**Where this stood (2026-10-12, after round five):** every round-five item is fixed (see the Status
lines under "Round Five Review") and every class and category in "Coverage after round five" has its
harness, two of which found bugs on their first run (the shim not waiting for the portal's answer,
R5-6; a race between the heal pass and a sandbox change, the threads category) and two found silent
exits (the degraded-host category). Nothing is open against the PR. Tiers at the end of round five:
1 — 2,034 passed, 79 skipped; 2 (Mint 22.1) — 71 passed, 1 skipped; 2b (Mint 21.3) — 67 / 1 at
db671ff; 3 (Ubuntu 24.04 VM) — 71 / 1; `filedialogs`, `consumers` and `wayland` as their expected lines
say. The paragraph below is the history.

**Where this stood (2026-10-11):** findings 1–8 and notes A–C are fixed or documented in the ten
commits 0050a15..d0f61c4 (one per finding; each commit message explains the fix and its evidence;
listed under Results); the round-two items R1–R10 in c8cdbe3..c4dd595;
and finding 0 was decided by the owner (option a, requirement 17.6.1) and done in 15ae403 — see
its "Status" and "Finding 0" at the end of the round-two section; the round-three items R3-1–R3-6
(reviewed at c2ff54f, 2026-10-11) are fixed in ea1cfa9..03305dc, see "Round Three Review"; the
**round-four** items R4-1–R4-9 (reviewed at 7323c5e, 2026-10-11; one HIGH, three MEDIUM, five LOW)
are fixed in a8bcd3e..667f545, see "Round Four Review" at the end. After round four, five
**coverage** commits (f695fbb..a1cfe4e, plus 4de6722 for a bug the first of them found) closed the
*classes* the four rounds' findings fell into, and "Merge readiness" at the very end gives the
verdict: ready to merge on code and evidence; a field pass on a physical desktop is what remains
before a release. **Round five** (reviewed at 6cf30c1, 2026-10-12; one MEDIUM, five LOW, small things) is
recorded in "Round Five Review" and was fixed the same day (5b95a62..cbb7860, one commit each), followed
by the eleven harness commits of "Coverage after round five".
A fresh session reviewing the fixes should read "For the reviewer of the
fixes" below, then the commits and the "Status" line under each finding; the finding sections
themselves are the original brief (line numbers as of f94bcfc, before the fixes). Read
`docs/app-sandboxing.md` (design and evidence), `docs/requirements.md` §17 (the spec) and
`docs/local-proxy-test-plan.md` (launcher shape) first; the code under review is
`src/appkata_core/sandbox.py`, `src/appkata_core/install.py`, `src/appkata_core/applog.py`,
`src/appkata/backend.py` and `src/appkata/qml/SandboxDialog.qml` / `AppDetail.qml`.

## The first fix pass (2026-10-10)

Before round one, a review of the implementation (91df918, 2026-10-09) found the issues below; it
was not written down as a file of its own, and this table stood in the PR body until 2026-10-24.
Each fix is its own commit, most severe first. Where it could be shown, the fix carries a test that
fails on the code before it.

**The test harness it built.** `tests/test_sandbox_run.py` runs the launchers AppKata generates under real bwrap, as an ordinary user:
- `scripts/test-sandbox.sh launcher` runs it in a Mint 22.1 container (bwrap 0.9, xdg-dbus-proxy, dbus, the document portal on FUSE, a registered link/text handler as a desktop has): 56 passed, 1 skipped (no `/dev/dri`) as of round four (50 / 1 after round three, 38 / 1 at first).
- `scripts/test-sandbox.sh launcher-vm` runs it in a real Ubuntu 24.04 VM under KVM, with AppKata's AppArmor profile applied, systemd-resolved, and a virtio GPU: 56 passed, 1 skipped (no camera node there) as of round four (50 / 1 after round three, 38 / 1 at first).
- `scripts/test-sandbox.sh filedialogs` (since round four) runs real GTK3, GTK4 and Qt 6 apps behind generated launchers on Xvfb with xdg-desktop-portal and its gtk backend on the bus, and reports which file dialog each shows and which proxy denial makes it so: their own, every time.
- Real AppImages (Obsidian, AppKata) and an X11-only program were also run through the launcher in a sway + XWayland session container.

| Commit | Fix |
|---|---|
| 016476a | **Escape:** `.flatpak-info` lived in the app's writable home. A symlink there exposed any host file (e.g. an SSH key) at `/.flatpak-info`, and the next regeneration overwrote it. The marker now lives outside every sandbox and is written without following symlinks. |
| cf0ccb8 | **Escape:** a `cli-tool` run from `~` got the real home read-write, and run from `/` the whole filesystem. The home folder, folders above it, and AppKata's own folders are never shared. |
| 0f09167 | **Decision 5:** updates re-resolved grants from the current reviews, so a changed review widened access silently. Grants are now pinned at install; a changed review raises the review badge instead. |
| 066de0d | Apps installed while setup was pending stayed unsandboxed after setup, while the UI said "Sandboxed". Launchers are now regenerated once sandboxing works, and the pill follows the real launcher. |
| 51e62ec | No DNS on Ubuntu/Mint (`/etc/resolv.conf` → `/run/systemd/resolve`). Reproduced on the 24.04 VM. |
| e5842f2 | *(found while testing)* `WAYLAND_DISPLAY`/`DISPLAY` were set before `--clearenv` and wiped, so no generated launcher could open a window. |
| 4cb7989 | No X11 on Wayland, so X11-only apps couldn't open. Added a default-on "X11 apps (XWayland)" device grant. |
| f3ccf8a | *(suspicion disproved)* Standard apps do run without a session bus: xdg-dbus-proxy listens before it connects upstream. Tests only. |
| b20827f | Unquoted env/display words: an empty variable broke the launch and spaces split values. Run-time words are now passed via quoted `"$@"`. |
| 48dc49e | The tray capability's `StatusNotifierItem-*` made xdg-dbus-proxy exit, so messenger-template apps couldn't start. The exact names are owned instead. |
| 2a3d201 | The camera grant did nothing; it now binds `/dev/video*` and `/dev/media*`. Play-only sound can also record (verified on PipeWire 1.0.5 / WirePlumber 0.4.17), so it's labelled honestly and enforcement is deferred (17.18). |
| c97ef39 | An `off` review stripped every grant when merged; it now adds no limit of its own. |
| 4213838 | No `/sys`, so GPUs couldn't be identified (software rendering). Shown on the VM's virtio GPU. |
| 7e353c1 | *(regression from b20827f)* bwrap warned about two `--chdir` options on every CLI-tool run. |
| 3660d46 | `--new-session` cut terminal tools off their tty. Replaced with a seccomp filter refusing TIOCSTI/TIOCLINUX, as Flatpak does. |
| d7282ec, 191578b | Trustfile: a dead settings key, and `Sandbox: standard` was ignored. |
| 7450553 | Uninstall deleted the private home before steps that can fail. |
| 9aa0528 | Extraction: a stale cache after in-place replacement, concurrent first launches clobbering each other, and a `squashfs-root` symlink being trusted. |
| 527aca6 | The AppArmor carve-out lets any program use bwrap for user namespaces; this is now stated in the docs and the UI (requirements 17.10.1). |
| ace1f40, f94bcfc | Regenerated the screenshots whose content changed or was stale. |

**Not a problem:** X11 MIT-SHM with IPC unshared. Obsidian and AppKata (Qt) run and render normally under Xvfb, with no SHM errors.

## For the reviewer of the fixes

**The commits**, in the order they landed (`git log --format='%h %s' f94bcfc..`): 0050a15 (finding
1), 9d0a6d9 (2), d8645af (4), fea0971 (3), 55955d0 (5), e2984f3 (6), ca21f95 (8), 644be18 (7),
da7ce4f (note A), d0f61c4 (notes B, C). Each message names the tests it added and the harness
result; where the new test could be shown failing on the previous code, the message says so.
09bfffe and 88d7bee are housekeeping (Windows VM container name; this file). **Round two** (the
section at the end of this file) landed after 525208e: c8cdbe3 (R1), 9949108 (R2), 77fb0a5 (R3),
4d4aa54 (R4), fee3657 (R5), 05c4b5e (R6), 2b51b40 (R7), 708f035 (R8), 4ba1cc4 (R9), c4dd595 (R10);
4cc9c29 recorded the findings. **Round three** (the last section): ea1cfa9 (R3-2), 34969d6 (R3-6),
7fd3625 (R3-3), 2da76d5 (R3-1), 75269dd (R3-4), 03305dc (R3-5). **Round four** (the last section;
e43d2cf recorded the findings): a8bcd3e (R4-1), bbdce73 (R4-2), 906e44f (R4-3), 6e75ca7 (R4-4),
242ddee (R4-5), 9d92b1a (R4-6), 5664cf5 (R4-7), 568f1a0 (R4-8), 667f545 (R4-9). The same
convention: each message names its tests and which fail on the code before it. **Coverage**
(after round four, the last section but one): f695fbb (the dialog contract test), 4de6722 (the
QVariant-slot bug it found), 808acf8 (grant-set properties), 81b7d5c (launcher goldens), 66ee89c
(real consumers), a1cfe4e (transition snapshots); each message says which earlier findings it
would have caught and shows the re-introduced fault failing.

**How to re-run the evidence.** Three tiers; the first two need Docker (the host here is Rocky 8
with no desktop, see the gotchas in `docs/app-sandboxing.md`), the third needs `/dev/kvm`:

1. Local: `.venv/bin/python -m pytest -q tests/` — expected 1,944 passed, 63 skipped on a box
   without bwrap 0.9 / xdg-dbus-proxy (the run tests skip; the grant-set property corpus is most
   of the count); it was 283 / 63 after round four's fixes, 269 / 57 after round three, 266 / 55
   after finding 0, 264 / 53 after round two and 231 / 45 before it. The QML-driven tests
   (`test_dialog_contract.py`, `test_qml_slots.py`) need PySide6 and run offscreen. The sandbox tests are `tests/test_sandbox.py`,
   `tests/test_sandbox_backend.py`, `tests/test_launch.py`, `tests/test_sandbox_run.py`.
2. Mint 22.1 container: `scripts/test-sandbox.sh launcher` (builds `appkata-sandbox-test2` on first
   use; runs `tests/test_sandbox_run.py` as an unprivileged user with bwrap 0.9, xdg-dbus-proxy and
   xdg-document-portal on FUSE; since round three it also registers a handler for links and text
   files as root first, `scripts/sandbox/register-test-handler.sh`, as a desktop has). Expected 56
   passed, 1 skipped (no `/dev/dri`); it was 50 / 1 after round three, 48 / 1 after finding 0,
   46 / 1 after round two and 38 / 1 before it. Extra arguments go to pytest, e.g. `-k planted`.
2b. (since the coverage work after round five) Mint 21.3 container: `scripts/test-sandbox.sh launcher-21`
   (builds `appkata-sandbox-test21`): the same tests on the older end of the version matrix — bwrap
   0.6.1, xdg-desktop-portal 1.14.4, GLib 2.72; the log's first line names the versions. Expected the
   same counts as tier 2 (67 passed, 1 skipped at db671ff).
3. Ubuntu 24.04 VM: `scripts/test-sandbox.sh launcher-vm` (cloud image cached in
   `build/sandbox-test/vm/`, AppKata's AppArmor profile applied, the same handler registered, about
   6 minutes). Expected 56 passed, 1 skipped (no camera node; 50 / 1 after round three, 48 / 1
   after finding 0, 46 / 1 after round two, 38 / 1 before); the log header shows the kernel, bwrap
   version, that the profile loaded and "test handler registered".

4. (since round four) `scripts/test-sandbox.sh filedialogs`: real GTK3, GTK4 and Qt 6 apps behind
   generated launchers on Xvfb with the portal running, one verdict line per toolkit and proxy
   variant (R4-5). Expected: "its own dialog" for every toolkit as generated; GTK4 "the portal's
   dialog" only when FileChooser is allowed too.
4b. (since round six) `scripts/test-sandbox.sh filedialogs-qt68`: the same on Ubuntu 25.04 — GTK 4.18, Qt
   6.8.3, bwrap 0.11 — which is where R6-4 (GTK 4.18: no dialog) was found. Expected: the lines
   `filedialogs.py` asserts ("EXPECTED: ok"), on both images.
4c. (since round seven) `scripts/test-sandbox.sh kwin` and `kwin6`: what KDE's kwin (5.27 on Mint 22.1,
   6.3 on Ubuntu 25.04) gives a sandboxed app — the clipboard-manager protocol and the clipboard
   (LEAKED, as 17.9 now says), screencast and fake input hidden (BLOCKED); "EXPECTED: ok".
2c. (since round eight) `scripts/test-sandbox.sh launcher-25`: the launcher tier on Ubuntu 25.04
   (bwrap 0.11, GLib 2.84, Python 3.13). Expected the same counts as tier 2 less the tmpfs case.
6. (since round five) `scripts/test-sandbox.sh wayland`: the generated launcher in the round-2 session
   image (headless sway, PipeWire, the portals) — expected "WORKS" for the GTK3 window and the tone
   (with `client access='flatpak' app_id='io.appkata.player'`), "BLOCKED" for `offline-editor`,
   "LEAKED" for the play-only recording (17.8 says so). Needs the session image.
7. (since round five) a frozen state per release: `UPDATE_STATE=<label> .venv/bin/python -m pytest
   tests/test_sandbox_state.py` before tagging; the test then runs over every snapshot. This is a
   release step, not a review one: it is in `docs/build.md`, "Before tagging a release", which is
   where it lives after the merge.
5. (since the coverage work after round four) `scripts/test-sandbox.sh consumers`: the same kind
   of image plus Chromium and xdotool; a GLib app's notification, a GTK3 app's link and Chromium's
   file chooser, with the real portal, its gtk backend, a stand-in notification daemon and the
   test link handler on the host. Expected: the notification "shown on the host" for `online-app`
   and "nothing reached the host daemon" for `offline-editor`; the GTK3 link "the host handler ran"
   with the URL and no "INSIDE" warning; Chromium "its own GTK dialog" as generated, "no dialog"
   with Properties allowed, "the portal's dialog" with FileChooser allowed too; the file cases (round
   five, R5-6): "the host handler ran on the host path … no chooser (the only handler)" for the shim
   and for `gio open`, and "refused by the portal; the shim failed as it should" for a file in the
   private home. About three minutes on first use (the image), under a minute after.

To see a fix's test fail on the code before it: `git stash`/checkout the parent commit's
`src/appkata_core/sandbox.py` (or whichever file the message names) and re-run tier 2 with `-k`.

**Finding 0 reproduction**: `scripts/sandbox/validate-chooser.sh` (its header has the `docker run`
line; it needs the `appkata-sandbox-session` image left by `scripts/test-sandbox.sh session`, or a
Mint 22.1 image with that mode's package list). It writes a real `online-app` launcher around a
tiny app that calls `FileChooser.OpenFile`, and printed `REFUSED … bwrapinfo.json` on xdg-desktop-
portal 1.20 before any dialog appeared. The portal source that does this is
`src/xdp-app-info-flatpak.c` in xdg-desktop-portal 1.18+. Since 15ae403 it prints the proxy's own
bare `AccessDenied` (re-run 2026-10-11): the portal is never asked, by design (17.6.3).

**Screenshots** (finding 3 changed `A21-sandbox-dialog`, `A22-update-review-badge`,
`A25-sandbox-advanced` under `screenshots/linux/`): regenerate with the tour as `docs/build.md`
describes, with the demo data built first —
`.venv/bin/python scripts/demo_data.py build build/demo && … sync … && … finish build/demo`, then
`APPKATA_DATA=build/demo XDG_DATA_HOME=build/demo/xdg .venv/bin/appkata --tour screenshots/linux
--tour-only A21-sandbox-dialog,A22-update-review-badge,A25-sandbox-advanced`. Running the tour
against an empty data dir renders empty screens; check `git diff --stat screenshots` before
committing.

**Where results go** (the owner, 2026-10-24): a review's results, its fixes and the tiers at its
end, are recorded in its review file, dated, under that file's Results; the PR body is a summary
that links to them and to the requirements, not a second record. Until 2026-10-24 the PR body
carried a "Review fixes" table; its rows are here now (Results and "The first fix pass"). Edit the
body with `gh pr edit 3 --body-file <file>`, from the current body (`gh pr view 3 --json body -q
.body`).

**What the fixes deliberately leave** (not regressions; check they are still stated where noted):
- Finding 2: the pre-launch symlink sweep is not atomic against a second, already-running instance
  of the same app that re-plants a link between the check and bwrap's mount. Stated in the launcher
  comment and `docs/app-sandboxing.md` Limits.
- Finding 7 is documented, not fixed: two tray-capable sandboxed apps still contend for the same
  StatusNotifierItem name.
- Strict apps have no session bus, so no portals and no file hand-over, by design (17.6).
- Finding 8's launch-failure toast covers the launcher's own refusals whenever they happen and the
  program dying within 10 s of the launcher starting it (`applog.watch`, since round two's R4);
  later crashes are in `logs/apps/<name>.log` only.
- Finding 4: a protected folder named by a review or saved from the dialog is dropped, with a
  comment in the launcher, a chip in the dialog and a toast on save; it is not an error that blocks
  the install.
- Finding 0 is decided (option a) and done in 15ae403. What that leaves by design: the file chooser
  portal is not used (the app's own dialog shows what the sandbox sees), and a file in the private
  home can't be opened on the host through the app's `xdg-open` (the portal can't locate it; a file
  in a granted folder or the hand-over view can). Both stated in requirement 17.6.3 and the design
  doc's Limits.

**How the fixes are expected to land** (see `~/.claude/projects/-home-dev-appkata/memory/`): one
commit per fix, pushed as you go, each proven with a test that fails on the code before it plus a
run in the containers/VM (`scripts/test-sandbox.sh launcher` / `launcher-vm`), and a row recorded
in this file (until 2026-10-24 that row went to the PR body; see "Where results go"). Line numbers
below are as of f94bcfc.

Local baseline: `tests/test_sandbox.py`, `tests/test_sandbox_backend.py`, `tests/test_sandbox_run.py`
→ 137 passed, 57 skipped on this box (bwrap 0.4.0, no `xdg-dbus-proxy`; the run tests need the
Mint 22.1 container or the Ubuntu 24.04 VM). It was 123 / 51 after round three, 120 / 49 after
finding 0, 118 / 47 after round two and 51 / 29 before it.

---

## 0. Portals are refused outright on xdg-desktop-portal 1.18+ — HIGH, needs a design decision

**Status: decided by the owner (option a, 2026-10-11) and done** (commit 15ae403, "Present
sandboxed apps to the portals as host callers, on a narrowed proxy"). The proxy's bwrap no longer
binds `/.flatpak-info`; `proxy_args` replaces `--talk=org.freedesktop.portal.Desktop` with
`portal_rules()` (per-interface `--call`/`--broadcast` rules); `GTK_USE_PORTAL` is no longer set;
an `xdg-open` of AppKata's (`sandboxes/.identity/bin`, bound at `/run/appkata`, first on PATH) sends
links and files to the host through OpenURI; the marker in the app's root gains `[Context]
shared=network` by grant. Tests named in the commit; the run tests put xdg-desktop-portal 1.20 itself
on the test bus, and the portal-answers test fails on the previous code with this finding's exact
refusal. Details, limits and what to look at: "Finding 0" at the end of the round-two section.

**Found while proving finding 1 end to end** (Mint 22.1 session container, xdg-desktop-portal 1.20,
a real generated `online-app` launcher calling `FileChooser.OpenFile` through its proxy):

```
GDBus.Error:org.freedesktop.DBus.Error.AccessDenied: Portal operation not allowed:
Failed to open file "/run/user/1001/.flatpak/<instance-id>/bwrapinfo.json": No such file or directory
```

`xdp_app_info_flatpak_new` (src/xdp-app-info-flatpak.c, 1.18+) accepts a caller whose
`/proc/<pid>/root/.flatpak-info` exists only if its `[Instance] instance-id` names a live Flatpak
instance's records under `$XDG_RUNTIME_DIR/.flatpak/`; otherwise it returns an error and the portal
refuses the request. So on Ubuntu 24.04 / Mint 22 — the platforms the AppArmor work targets — **no
portal answers a sandboxed app at all**: no file chooser, no notifications, no OpenURI. Mint 21.3's
1.14 behaves as the design assumed. The earlier "recognition confirmed" (round 3) only showed that the
marker changed the portal's behaviour, not that requests succeed.

**This is not a code fix; the author/owner must choose** (recorded as requirement 17.6.1):
- (a) Present the app to portals *without* the marker, i.e. as a host app, and narrow the proxy from
  `--talk=org.freedesktop.portal.Desktop` to the safe interfaces with xdg-dbus-proxy `--call`/
  `--broadcast` rules (FileChooser, Notification, OpenURI, Settings, Inhibit, Print… and not
  Background/DynamicLauncher, which treat a host caller as trusted). The document-portal hand-over
  then has to be done by AppKata itself (a host process may call `Documents.Add` +
  `GrantPermissions` for the app id — the mechanism finding 1's run test exercises), e.g. a small
  AppKata chooser helper. PipeWire's identity marker (17.8) is a separate file and can stay.
- (b) Keep the marker and state that portals are unavailable on those systems.
Do **not** fabricate Flatpak instance records to satisfy the check; that defeats a security
validation in another project's code.

*Round two note for whoever decides:* option (a)'s hand-over mechanism — a host process exporting a
file to the app id through `Documents.Add` + `GrantPermissions`, the sandbox reading it under
`$XDG_RUNTIME_DIR/doc` — is no longer just test-proven: since R7 the launcher uses it for file
arguments (`forward-files.py`), on portal 1.20, from the host side, where the marker plays no part.
That lowers (a)'s risk to "a chooser helper that calls the same code". Whichever option is taken,
check in the session container what GTK, Qt and Electron do when the portal refuses with the marker
and `GTK_USE_PORTAL=1` in place (fall back to the in-process dialog, or fail?);
`scripts/sandbox/validate-chooser.sh` only exercises the raw D-Bus call.

## 1. The document-portal file hand-over cannot work as built — HIGH (functional)

**Status: fixed in the launcher** (per-app `by-app/<id>` view bound at `$rt/doc`, `GTK_USE_PORTAL=1`,
run test exporting through the Documents portal passes in the Mint 22.1 container), **plus** the
identity is now a valid bus name for digit-led slugs (`io.appkata._7zip`; xdg-dbus-proxy exited on
`--own=io.appkata.7zip`, leaving such apps with no bus). The end-to-end chooser flow was blocked by
finding 0 and, with its decision (option a), is no longer portal-based: the app's own dialog shows
the sandbox's view, and the `by-app/<id>` bind serves the file arguments of R7 (17.6.2, 17.6.3).
`GTK_USE_PORTAL=1` was removed again in 15ae403.

**Claim in the PR / design:** decision 4 and `docs/app-sandboxing.md` ("the document portal still
hands over any file the user picks in a dialog, grant or no grant").

**What the code does:** `build_launcher` creates the runtime dir with `--dir "$rt"`
(`src/appkata_core/sandbox.py:828`) and binds only the Wayland/X11/sound sockets and the proxy
socket into it. It never binds the document portal's FUSE export. Flatpak binds
`$XDG_RUNTIME_DIR/doc/by-app/<app-id>` onto `$XDG_RUNTIME_DIR/doc` inside the sandbox; the
FileChooser portal returns paths of the form `/run/user/<uid>/doc/<docid>/<name>`, which do not
exist in an AppKata sandbox. The launcher also doesn't set `GTK_USE_PORTAL=1` (Flatpak does), so
GTK/Electron apps open their own in-sandbox chooser, which only sees the private home.

**Consequence:** with folder grants all default Off (decision 4) and unreviewed GUI apps defaulting
to Strict (no session bus at all, so no portals), the default experience is an app that cannot open
any user file. The PR lists hand-over as "owed real-hardware validation"; it is missing code.

**Fix sketch:**
- In the Standard launcher (bus present), add
  `--bind-try "$rt/doc/by-app/$id" "$rt/doc"` after `--dir "$rt"` (`-try` keeps a session without a
  document portal working; the `by-app/<id>` dir exists as soon as the portal runs, before any
  export — round two's R8 corrected the original claim here that it appears only after one).
- Add `--setenv GTK_USE_PORTAL 1` after `--clearenv`.
- Confirm the app id the portal keys on equals `io.appkata.<id>` from `.flatpak-info`
  (`app_identity`), and that `xdg-document-portal` accepts the fake Flatpak identity (see note D).
- Test: in the container session (`scripts/sandbox/session.sh` / `portals.sh`), pick a file through
  the FileChooser portal from inside a generated launcher and read it back.
- Update decision 4 / 17.x wording if Strict apps still can't (they have no bus by design).

## 2. Mount destinations inside the app-writable private home follow app-planted symlinks — MEDIUM (security hygiene)

**Status: fixed** (launcher `guard` sweeps every destination under `$HOME` before bwrap; run test with
four planted-link cases fails before / passes after on bwrap 0.9.0). The live race with a second
running instance remains, as documented in the code.

**Where:** every bind whose destination is under `$HOME`, which is already the private home at that
point (`--bind "$home" "$HOME"` is first): `~/.themes`, `~/.icons`, `~/.fonts`,
`~/.config/fontconfig` (`sandbox.py:836-837`), `~/.Xauthority` when `XAUTHORITY` is unset or under
home (`:795-796`), `$appdir` and `$img` (`:834-835`, `:842`), every baked folder grant (`:850-855`)
and the CLI `$here` bind (`:724`).

**Confirmed here (bwrap 0.4.0):** a symlink `~/.Xauthority -> ../../../oldroot/<host path>` placed
in the private home made `--ro-bind <real> "$HOME/.Xauthority"` *create an empty 0666 file at that
host path* (bwrap's `ensure_file` → `creat()` follows the symlink); a symlinked directory destination
whose target's parents don't exist aborted the launch ("Can't mkdir parents"), and one whose target
exists gets host directories created under it. No privilege gain found: the mount itself lands under
the old root, which bwrap detaches before exec. Net effect: an app can create empty files/dirs as the
user anywhere, and can brick its own launch. Commit 016476a closed the same class on the *source*
side (`.flatpak-info`). Verify first on bwrap 0.9 in the container, since newer bwrap may resolve
destinations differently.

**Fix sketch:** before starting bwrap, the launcher walks each known destination's path components
under `$home` (the relative parts of the list above, plus `$here`/`$xa` at run time) and refuses or
removes any symlink (`[ -L ]`), then proceeds. Serialize launches on a lock if a concurrently running
instance racing the check matters. Add a run test next to
`test_an_appimage_cannot_swap_its_extraction_for_a_host_folder` that plants such a symlink and
asserts no host file appears and the launch still succeeds (or fails cleanly).

## 3. The review badge can't be dismissed and there's no way back to "follow the reviewers" — MEDIUM (spec 17.11 / UX)

**Status: fixed** (fea0971: Keep mine / Use theirs, badge keyed on the suggestion acted on).

**Where:** `Backend.sandboxInfo` (`src/appkata/backend.py`, `reviewBadge = … summary(suggested) !=
summary(gs)`) ignores `source`; it fires when the source is the user's own choice too.
`SandboxDialog.qml:215-217` only ever calls `setSandbox` with `{template:"off"}`, `{template, overrides:{}}`
or `{custom}`; the backend's `setSandbox(url, null)` path (clear the user choice, re-adopt reviews /
default and re-pin) is never reachable from the UI.

**Consequence:** a user who deliberately deviates sees "Reviewers suggest a sandbox change" forever,
and a review that carries `Sandbox folders` / `Sandbox network` overrides can never be matched through
the template dropdown (overrides are `{}`), so even "accept the suggestion" leaves the badge up.

**Fix sketch:** add a "Use the reviewers' suggestion" action (calls `setSandbox(url, null)`) and a
"Keep mine" that records the suggestion as seen (e.g. store `summary(suggested)` in the app's install
settings as `sandboxReviewSeen`; badge only when the current suggestion differs from *that*). Keep the
badge for the update-kept-your-grants case (pinned source). Cover with `tests/test_sandbox_backend.py`.

## 4. Folder grants bypass the protected set that the `$cwd` grant enforces — MEDIUM (security)

**Status: fixed** (d8645af: `protected_folder()` in the launcher, chips and the dialog save; run test reads the key on the old launcher).

**Where:** `build_launcher` bakes every folder grant as `--bind-try <path> <path>` after
`os.path.expanduser` (`sandbox.py:850-855`). Grants come from a review's `Sandbox folders` line
(`parse_folders`, `config_from_review`) and from the Customize folder picker
(`SandboxDialog.qml:54-60`). Nothing checks them, while commit cf0ccb8 made the `$cwd` grant refuse
the home, anything above it, the sandboxes root and the apps root (`_CWD_BLOCK`, `:713-730`).

**Consequence:** `~`, `/`, `~/bin/apps`, `~/.local/share/appkata`, `~/.ssh`, `~/.config` all go
straight to bwrap; because the bind lands after `--bind "$home" "$HOME"`, granting `~` silently puts
the real home back over the private one. A hostile or careless review, or one click on the home
folder in the picker, defeats the sandbox with only a small chip ("~") as the hint.

**Fix sketch:** one `protected_folder(path, apps_root)` check (same set as `_CWD_BLOCK`, plus
`~/.config`, `~/.ssh`, `~/.gnupg`, `$XDG_RUNTIME_DIR`) applied in `grants_from_config` /
`build_launcher` (drop and log) and in the picker (refuse with a message). Tests in
`tests/test_sandbox.py` for review-sourced and user-sourced grants.

## 5. The `$cwd` protected list misses two cheap cases — LOW (security)

**Status: fixed** (55955d0).

`_CWD_BLOCK` (`sandbox.py:713-730`) protects `$HOME`, its ancestors, the sandboxes root and the apps
root. Add:
- `~/.config` — holds `autostart/` and `systemd/user/`, the persistence paths the goals say an app
  must never write; a CLI tool run from there gets them read-write.
- `$XDG_RUNTIME_DIR` — the run-time `--bind "$here" "$here"` is in `"$@"`, i.e. *after*
  `--bind "$sock" "$rt/bus"`, so running a tool from inside `$rt` mounts the real runtime dir over
  it and exposes the unfiltered session bus (systemd escape).
Extend `test_cli_tool_never_gets_the_home_or_above_or_appkata_areas` with both.

## 6. AppArmor setup reports success without checking it worked — LOW (correctness)

**Status: fixed** (e2984f3).

`install_profile` calls `userns_works(refresh=True)` and returns True regardless of the result
(`sandbox.py:464`); `Backend.setupSandboxSupport` toasts "Sandbox support is set up" unconditionally.
`PROFILE_TEXT` hard-codes `/usr/bin/bwrap` (`:350`), so a bwrap installed elsewhere gets a profile
that attaches to nothing, and the user is told it's fixed while apps keep running Off.

**Fix sketch:** use `os.path.realpath(shutil.which("bwrap"))` in the profile; after loading, if
`userns_works(refresh=True)` is still False raise `SandboxError("the profile loaded but bwrap still
can't create a user namespace")`. Unit-test with the subprocess mocked.

## 7. Tray bus names collide between sandboxed apps — LOW (functional, document)

**Status: documented** (644be18).

`_TRAY_OWNS` (`sandbox.py:533`) owns `org.kde.StatusNotifierItem-{2,3}-{1,2,3}` for every
tray-capable app, because each is pid 2/3 in its own namespace. Two such apps running at once contend
for the same well-known name on the host bus; the second can't take it and its icon may not appear.
Same limitation as Flatpak. At minimum state it in `docs/app-sandboxing.md` limits and the
`messenger` blurb; a real fix needs a per-app proxy rewrite, out of scope.

## 8. Launch failures are invisible — LOW (diagnosability)

**Status: fixed** (ca21f95: per-app log file, toast on an immediate non-zero exit).

`install.launch()` runs the launcher with `stdout`/`stderr` to `/dev/null`
(`src/appkata_core/install.py:827`). bwrap errors, "didn't unpack to a folder", and the CLI-tool
"can't see this folder" notice all vanish when the app is started from AppKata or the menu, and
sandboxing adds several new failure modes. Capture stderr into the app log (`applog`) and surface a
toast when the launcher exits non-zero within a couple of seconds.

## Smaller notes

**Status: A fixed (da7ce4f), B and C fixed (d0f61c4), D is finding 0 — decided (option a, 15ae403):
the portals no longer act on a Flatpak identity, since they are not shown one.**

- **A.** `_heal_launchers` runs in `Backend.__init__` on the UI thread; when any app needs a
  launcher it calls `support_status()` → `userns_works()` (a bwrap probe with a 15 s timeout) there.
  It also doesn't skip foreign-adopted apps the way `setSandbox` does (`backend.py`, `_heal_launchers`
  vs `setSandbox`'s `not a.get("foreign")`); confirm `_resolved_sandbox` returns None for them, or
  add the guard.
- **B.** Only the legacy `~/.fonts`, `~/.icons`, `~/.themes` are bound (`sandbox.py:836-837`);
  `~/.local/share/{fonts,icons,themes}` are not, so user-installed fonts and cursor themes disappear
  inside sandboxed apps. Add `--ro-bind-try` for the three.
- **C.** `_EXTRACT_BLOCK` tests `[ ! -e "$appdir/AppRun" ]` (`:673`); a dangling or symlinked
  `AppRun` re-extracts on every launch. Use the stamp alone, or `-d "$appdir"`.
- **D. Design caveat, not a bug:** the portal/PipeWire story depends on xdg-desktop-portal and
  WirePlumber accepting a non-Flatpak process that carries `.flatpak-info`. Portals that *act* on a
  Flatpak identity will misbehave (the Background portal's autostart writes
  `Exec=flatpak run io.appkata.<id>`; OpenURI/DynamicLauncher may shell out to `flatpak`), and newer
  portal releases read more of the file (`[Instance]`, `app-path`). This is the riskiest assumption in
  the approach and sits inside the owed hardware validation; finding 1 is where it will first show.

---

## Recommended model for the fixes

**Claude Fable 5.1** (`claude-fable-5-1`). The work is security-sensitive shell and bwrap mount
semantics (findings 2, 4, 5), portal mechanics that have to be verified empirically in the container
and VM rather than reasoned about (finding 1, note D), and backend/QML state changes with tests
(finding 3). That combination rewards the most capable model; Fable 5.1 found finding 2 by running
bwrap rather than assuming. **Claude Opus 5.5** is the fallback if Fable isn't available for the
session: it handles all of the above well, and the brief per finding is concrete enough that the
gap is mostly in the empirical verification steps. Don't use Sonnet/Haiku for 1, 2 or 4.

Suggested order (as followed): 1 → 2 → 4 → 5 → 3 → 6 → 8 → 7 → A–C, each its own commit, run
tests in the Mint container (`scripts/test-sandbox.sh launcher`) and the 24.04 VM (`launcher-vm`)
before pushing, then record the row (then in the PR body's "Review fixes" table, now under Results). This file stays in the
tree as the record of the review; once finding 0 is decided, move whatever still applies into
`docs/app-sandboxing.md` and delete it.

---

## Round Two Review

Review of the fixes at 525208e (branch `app-sandboxing`), 2026-10-10. Line numbers below are as of
that commit. Each item's **Status** line says whether it has been fixed since, and by which commit
(the "Round two fixes" paragraph at the end of this section lists them in order).

**What was re-run.** Tier 1 (`.venv/bin/python -m pytest -q tests/`): 231 passed, 45 skipped, as
documented. Tier 2 (`scripts/test-sandbox.sh launcher`, Mint 22.1 container, xdg-desktop-portal
1.20.0): 38 passed, 1 skipped, as documented. Tier 3 (the 24.04 VM) was not re-run this round. The PR
body's "Review fixes" table matches the commits. Two extra probes were run in the tier-2 container
(their results are in R8 and "Verified" below), and one backend probe locally (R1). All three were
committed as scripts at 4cc9c29 (`scripts/sandbox/probe_round2_run.py`, `probe_round2_backend.py`)
and have since become regression tests and been removed: the backend probe is
`test_resaving_install_options_keeps_the_pin_the_seen_marker_and_the_users_choice` in
`tests/test_sandbox_backend.py` (R1); the container probes are
`test_a_file_exported_while_the_app_runs_is_readable_on_its_first_launch` (R8) and
`test_nested_folder_grants_cannot_reopen_the_symlink_hole` ("Verified") in `tests/test_sandbox_run.py`.

### R1. Re-saving Install options wipes the sandbox pin, the seen marker and the user's choice — HIGH (decision 5 regression)

**Status: fixed** (commit "Keep the sandbox pin, the seen marker and the user's choice across an
install-dialog answer"). `installWith` and `_choose_channel` now go through `_answer_install_dialog`,
which replaces only the dialog's own keys (`kind`, `exeKind`, `appMenu`, `commandLink`, `stableName`,
`autoUpdate`, `scope`, `motw`, `channel`, `updates`) in the row and keeps the rest. Each dialog
answer drops the *other* dialog's keys too, so switching to a package channel and back doesn't leave
a stale `channel` preselecting that card. Test: the one named in the intro; shown failing on the
previous `backend.py`.

**Where:** `Backend.installWith` (`src/appkata/backend.py:773-782`) builds the `app_settings.install`
row afresh from the dialog's fields and writes it with `ON CONFLICT … SET install=excluded.install`,
replacing the row. But `sandboxPinned` (`_pin_sandbox`), `sandboxReviewSeen` (`keepSandbox`,
`setSandbox`) and the user's `sandbox` choice all live in that same row, and the dialog only sends
`sandbox` when the card was touched this time (`InstallDialog.qml`, `sandboxTouched`).

**Consequence:** after the user opens "Install options…" and saves (or installs an update through the
dialog) without touching the Sandbox card: the pin is gone, so `_resolved_sandbox` falls through to the
current reviews; `_install` (`:977`, `:994`) then re-pins whatever the reviews say *now*. A changed
review therefore does change an installed app's grants silently — the exact case 0f09167 and decision
5 rule out, and the case `test_a_changed_review_never_changes_an_installed_apps_grants` guards, only
one step earlier. A sandbox chosen in the Sandbox dialog is lost the same way, and "Keep mine" is
forgotten.

**Reproduced** (backend, local): pin an app on `offline-editor`, `keepSandbox`, change the review to
`online-app`, then `be.installWith(URL, {"kind": "appimage", "appMenu": True, "install": False})`;
the row afterwards is `{"kind", "appMenu"}` and the resolved source is `reviews` with network on.

**Fix sketch:** merge into the existing row the way `_save_options` (`:1587-1594`) does with
`cur.update(...)`, never replace it; the same for `_choose_channel` if a package channel should keep
the sandbox keys. Test in `tests/test_sandbox_backend.py`: pin → keep → changed review →
`installWith` without `sandbox` → source still `pinned`, `sandboxReviewSeen` still set, and a
`setSandbox` choice survives an options save.

### R2. A sandbox chosen in the install dialog doesn't count as "seen" — MEDIUM (17.11)

**Status: fixed** (commit "Count a sandbox chosen in the install dialog as seen"). `installWith`
records `sandboxReviewSeen` whenever the dialog sends a sandbox choice, exactly as `setSandbox` does.
Test: `test_a_sandbox_chosen_in_the_install_dialog_counts_as_seen` in `tests/test_sandbox_backend.py`;
fails on the previous `backend.py`.

`installWith` saves `c["sandbox"]` (`:779-780`) but not `sandboxReviewSeen`, while `setSandbox` does
(`:1795`). The install card shows "suggested by <reviewer>" next to the dropdown, so a user who picks
another template there chose knowing the suggestion — and gets the review badge the moment the install
finishes. 17.11 says a choice "of their own knowing it" clears it. Fix: when `c.get("sandbox")` is
present set `saved["sandboxReviewSeen"] = self._review_suggestion_summary(url)` (after R1's merge).
Test: review `online-app`, `installWith(... sandbox={"template": "strict", ...})`, `sandboxInfo`
→ `reviewBadge` False.

### R3. The never-shared list misses other ways to start again later — MEDIUM (17.3.1 / 17.3.3, security)

**Status: fixed** (commit "Never share the other places a program can start again from, or change
what your commands do"). `_protected_roots` now also lists `~/.local/bin`, `~/.config/autostart-scripts`,
`~/.local/share/systemd`, `~/.local/share/dbus-1`, `~/.local/share/flatpak`, `~/.config/environment.d`,
`~/.pam_environment`, `~/.config/plasma-workspace`, `~/.gitconfig`, `~/.config/git`, the shell startup
files (bash, zsh, fish, ksh, csh) and the X session files; a file root is matched exactly by the
existing `p == r` test, so no separate file rule was needed. The `$cwd` block shares the list, so the
CLI tool refuses those directories too. Tests: new rows in `test_protected_folders_are_never_granted`
(with negatives for `~/.local/share/fonts`, `~/.config/git-extras`, `~/.bashrc.d` to show the prefix
match is exact) and `test_cli_launcher_protects_the_persistence_dirs_and_the_runtime_folder`; three
new `where` cases (`local-bin`, `environment.d`, `plasma-env`) in
`test_cli_tool_never_gets_the_home_or_above_or_appkata_areas`, which fail on the previous
`sandbox.py` in the tier-2 container and pass with it (tier 2 is now 41 passed, 1 skipped). 17.3.1
and 17.3.3 list the additions.

`_protected_roots` (`src/appkata_core/sandbox.py:197-211`) covers autostart, systemd user units,
`~/.local/share/applications`, `~/.ssh`, `~/.gnupg` and the runtime dir. `protected_folder()` still
allows (checked): `~/.local/bin` (on `PATH` from `~/.profile` on Debian/Ubuntu/Mint, so a dropped
binary shadows `ls`), `~/.config/environment.d`, `~/.config/plasma-workspace/env` (KDE runs scripts
there at login), `~/.config/autostart-scripts`, `~/.local/share/flatpak`, `~/.gitconfig`
(`core.hooksPath`, aliases) and the shell/session startup files `~/.bashrc`, `~/.profile`,
`~/.xsessionrc`, `~/.xprofile` — a `Sandbox folders` line is just a path and `--bind-try` binds a
file as readily as a folder. The CLI tool's `$cwd` rule shares the same list, so a tool run from
`~/.local/bin` gets it read-write. The threat is the one finding 4 addressed: a hostile or careless
review, or a picker click. Fix: extend `_protected_roots` with those folders and refuse file paths
(or the known rc files) in `protected_folder`; add them to
`test_protected_folders_are_never_granted` and to the `where` cases of
`test_cli_tool_never_gets_the_home_or_above_or_appkata_areas`; update the 17.3.1 / 17.3.3 lists.

### R4. Launches from the menu or command link are still silent; so are failures after 10 s — MEDIUM (finding 8 left open)

**Status: fixed** (commit "Keep a menu launch's errors in the app log, and report a refusal however
long the unpacking took"). Three parts. (1) The launcher bakes in the app's log path; when its
stderr already *is* that file (AppKata's Open) it just notes so, and when its first argument is
`--appkata-menu` — which the desktop entry now passes, so a file manager's "Open with" and copied
shortcuts carry it too — it appends its stderr there under a dated line, rotating at 2 MB. Any other
start (a command link in a terminal or a script) keeps stderr where the caller put it: the first
cut used "no controlling terminal" as the trigger and hijacked a tool's `2>file` and every
non-interactive run (the container suite showed it: 16 failures). (2) `launch()` opens the log for
appending (`applog.open_app_log`, with the same rotation and header), so a second instance no longer
truncates the first's. (3) The launcher writes `AppKata: running <exe> (<epoch>)` just before bwrap;
`applog.watch` measures the grace from that line, and a non-zero exit with no such line is the
launcher's own refusal, reported however long it took (extraction included). Bugs found on the way:
dash's `printf` takes a format starting with `---` as options (`printf --`). Tests:
`test_a_launch_from_the_menu_writes_its_refusal_to_the_app_log` (tier 2, fake `bwrap` on `PATH`),
`test_launches_append_to_the_app_log_and_rotate_it`,
`test_a_launchers_refusal_is_reported_after_any_delay_but_a_crash_later_is_not`,
`test_a_program_run_directly_is_only_reported_within_the_grace`,
`test_launcher_keeps_its_stderr_when_nothing_else_shows_it`,
`test_the_menu_entry_passes_the_menu_word_only_to_a_launcher`; 7 local and the tier-2 one fail on the
previous code. Tier 2 is 42 passed, 1 skipped. 14.2.1 and the design doc's Limits describe the
behaviour, including that an older desktop entry gains the word at its next rewrite.

`install.launch` (`src/appkata_core/install.py:819-837`) is only reached from Open in AppKata. The
`.desktop` `Exec=` and the command link run `~/bin/apps/<app>/run` directly, so a bwrap refusal there
(the userns restriction returning after an OS upgrade, bwrap removed, a tarball app whose launcher is
stale) still shows nothing and writes nothing — finding 8 named "from AppKata or the menu".
`applog.watch`'s grace is 10 s (`applog.py:118`); a first sandboxed launch of an AppImage extracts it
first, which takes longer than that for a large one, so "didn't unpack to a folder" after extraction
is log-only even from AppKata. And the log is opened with `"w"` per launch (`install.py:834`): a
second instance truncates the first's live log.

**Fix sketch:** bake the log path into the launcher and have it redirect its own stderr there when
stderr isn't a terminal (`[ -t 2 ] || exec 2>>"$log"`, with a dated header line), so every way of
starting the app leaves the same trace; open the file in append mode in `launch()`; start the grace
timer after extraction or raise it. Run test: a generated launcher whose bwrap fails, started with
stderr on a pipe, writes the bwrap error into the baked log path.

### R5. The bwrap probe still runs on the UI thread in the common case — LOW (note A partial)

**Status: fixed** (commit "Warm the bwrap probe on the startup thread even when nothing needs
healing"). `_heal_launchers_at_startup` calls `sandbox.userns_works()` unconditionally before the
heal pass, so the cache is filled off the UI thread on every start. Test:
`test_the_startup_pass_warms_the_bwrap_probe_even_with_nothing_to_heal` in
`tests/test_sandbox_backend.py`; fails on the previous `backend.py`.

`_heal_launchers` (`src/appkata/backend.py:1863-1885`) only calls `support_status()` when some app
needs a launcher: `if not todo or not sandbox.have_tools() or sandbox.support_status()…` short-
circuits. So on a normal start (every app already has its launcher) the startup thread never warms
`_userns_cache`, and the first `detail()` / `sandboxInfo()` / `sandboxSupport` on the UI thread runs
the probe with its 15 s timeout — what da7ce4f set out to move. Fix: in `_heal_launchers_at_startup`
call `sandbox.userns_works()` first, unconditionally. Test: monkeypatch `userns_works` to count calls,
run the startup pass with nothing to heal, assert it was called once.

### R6. "Follow reviewers' suggestions" off still badges, and still uses the reviewed baseline — LOW (17.15, needs a decision)

**Status: fixed** (commit "Take reviews out of sandboxing when the user turns off following
them"). Decided: off means reviews play no part — `_resolved_sandbox` treats the app as unreviewed
(the user's default for the kind applies, not the `standard` baseline) and `sandboxInfo` never
badges; the dialog still shows the suggestion and offers "Use theirs" as an explicit choice.
17.15 says so. Test: `test_follow_reviewers_off_uses_the_users_default_and_never_badges` in
`tests/test_sandbox_backend.py`; fails on the previous `backend.py`. The owner can reverse the
decision by flipping the two `follow` uses; the test documents the intended behaviour either way.

With `followReviewerSandbox` off, `_resolved_sandbox` (`:1650-1673`) drops the reviews but still
computes `reviewed=True`, so `default_template` gives the `standard` baseline rather than the user's
Settings → Sandbox GUI default; and `sandboxInfo` (`:1731-1767`) computes `suggested`, `reviewBadge`
and `hasSuggestion` from the reviews regardless of the pref, so the app is badged (and the dialog
offers "Use theirs") for a suggestion the user asked not to follow. Either is defensible; say which
is intended in 17.15 and cover it in `tests/test_sandbox_backend.py` (no test touches the pref today).

### R7. Files passed as arguments never reach the sandboxed app — LOW (design, state or fix)

**Status: fixed** (commit "Hand file arguments over to a Standard app through the document
portal"). Chose to fix rather than state: the mechanism was already proven and the gap was
functional. A Standard launcher now runs a helper (`forward-files.py`, written beside the seccomp
filter) over its arguments before the bwrap words are fixed: a path or `file://` URI naming a file
outside the granted folders (and outside a CLI tool's own directory) is exported with
`Documents.Add` + `GrantPermissions` (read, plus write when the user has it) for the app's id, and the
argument becomes `$XDG_RUNTIME_DIR/doc/<id>/<name>`. Strict apps get no block (no bus, no portal).
Without `python3-gi` or a document portal the arguments pass through unchanged. Requirement 17.6.2
and the Limits state it, including that the app sees the file, not its folder. Tests:
`test_a_file_argument_is_handed_over_to_a_standard_app` (tier 2: plain path, URI, granted folder,
read-only file, a non-file URI, and the app's edit reaching the real file) and
`test_file_arguments_pass_through_when_there_is_no_document_portal` in `tests/test_sandbox_run.py`;
`test_launcher_hands_over_file_arguments_only_for_standard_apps` in `tests/test_sandbox.py`.

The desktop entry is `Exec="<launcher>" %U` (`install.py:193`) and the command link passes arguments
through. A file manager's "Open with", a file dragged onto the entry, or `tool ~/notes.txt` hand the
app host paths that don't exist inside the private home (a `cli-tool` sees only `$cwd`), so the app
opens nothing or errors. Not stated in 17.17 or the Limits. Flatpak solves this with file forwarding;
AppKata's launcher could do the same from the host side with `Documents.Add` + `GrantPermissions`
for the app id — the mechanism `test_a_file_handed_over_by_the_document_portal_is_readable_and_only_by_that_app`
already proves on portal 1.20, and the same one option (a) of finding 0 relies on. Otherwise add it
to the limits.

### R8. The document-portal bind's comment is wrong; the first-launch hand-over works — LOW (comment + test gap)

**Status: fixed** (commit "Say that the document portal's per-app view is there from the first
launch, and test it"). Correction to this finding: the wrong sentence was in *this file's* finding-1
fix sketch, not in `sandbox.py` (whose comment said only "-try: no document portal, no mount");
both now say the view exists as soon as the portal runs. Test:
`test_a_file_exported_while_the_app_runs_is_readable_on_its_first_launch` in
`tests/test_sandbox_run.py` (first launch with nothing exported: `$XDG_RUNTIME_DIR/doc` present; a
file exported while the app runs is readable at once). The nested-grant probe became
`test_nested_folder_grants_cannot_reopen_the_symlink_hole` in the same file and the one-line
explanation sits above `_GUARD_FN`. No behaviour change.

`build_launcher` (`sandbox.py:942-947`) says the `by-app/<id>` dir "only exists once the document
portal is running and has exported something for that id", which would make `--bind-try` skip the
mount on an app's first launch and the first picked file invisible until a relaunch. Checked in the
tier-2 container (xdg-desktop-portal 1.20.0): `$XDG_RUNTIME_DIR/doc/by-app/io.appkata.fresh` is a
directory before anything is exported, `$XDG_RUNTIME_DIR/doc` is present inside the sandbox on the
first launch, a file exported *while the app runs* is readable at once, and a hyphenated id
(`io.appkata.local-send`) resolves. Fix the comment (keep `-try` for the no-portal session) and add
that export-during-the-run case to `tests/test_sandbox_run.py`, since it is the real first-use path.

### R9. The summary chips and the launcher disagree on the install root — LOW (consistency)

**Status: fixed** (commit "Judge refused folders in the chips against the app's install root, as
the launcher does"). `summary_chips` and `summary` take `apps_root`; the backend passes
`_app_options(url).root` everywhere it has the app (the install card, `sandboxInfo`, the badge and
"seen" comparisons, the live `summaryChips` slot, which now takes the url from the dialog). Test:
the custom-root case added to `test_launcher_and_summary_refuse_protected_folders`; fails on the
previous `sandbox.py`.

`summary_chips` calls `protected_folder(path)` with no `apps_root` (`sandbox.py:364`), so it checks
`platform.apps_dir()`; the launcher and `setSandbox` use `portable.root`. With a custom install folder
(Settings → Portable apps) a grant under it is refused by the launcher but shown as granted by the
chips, while the unused default `~/bin/apps` shows as refused. Pass the root through (`summary_chips(gs,
apps_root)`; the backend has it) and assert the two agree in `test_launcher_and_summary_refuse_protected_folders`.

### R10. Small things

**Status: fixed** (commit "Round two's small things: the launch-failure toast from the worker
thread, and the identity marker on uninstall"); the finding-0 note is now in finding 0 itself.

- `openApp`'s failure callback emits `self.toast` from the watcher thread (`backend.py:1127-1129`);
  every other worker path emits `self._toast`, which is connected to `toast` for that reason (`:127`).
  Use `_toast`. *Fixed;* `test_open_reports_a_launch_that_fails_at_once` still covers the text.
- Uninstalling without "delete its sandbox home" leaves `.identity/<app>` behind:
  `remove_sandbox_home` is the only thing that unlinks the marker (`sandbox.py:596-600`). Remove the
  marker with the launcher instead. *Fixed:* `uninstall` always calls the new
  `sandbox.remove_identity`; test `test_uninstall_keeping_the_home_still_removes_the_identity_marker`.
- Finding 0: decided (option a) and done after this round, see its Status and "Finding 0" below.
  The question this note asked (what GTK/Qt/Electron do when the portal refuses with
  `GTK_USE_PORTAL=1` in place) is moot: the launcher no longer sets it and the proxy denies the
  file chooser outright, so the toolkits never ask.

### Verified this round, no change needed

- **Nested folder grants don't reopen finding 2.** Probe: grants `~/Projects` (rw) and
  `~/Projects/sub/deep` (ro); from inside, `mv ~/Projects/sub ~/Projects/sub.old && ln -s
  /oldroot/<victim> ~/Projects/sub` lands on the host (the outer grant is the real folder); the next
  launch succeeds and creates nothing under the victim. Reason: `--ro-bind-try`'s *source* is the same
  path and must resolve on the host, where `/oldroot` does not exist, so the bind is skipped; a link to
  a path that resolves on both sides lands inside the private home. Now a comment above `_GUARD_FN`
  and the test `test_nested_folder_grants_cannot_reopen_the_symlink_hole` (with the R8 commit).
- The items the previous round listed under "What the fixes deliberately leave" are all still stated
  where it says (17.4, 17.6.1, 17.17, 14.2.1, the design doc's Limits).
- `test_sandbox_run.py`'s no-session-bus case holds because xdg-dbus-proxy creates its socket before
  connecting upstream; the launcher's `-S "$sock"` wait is therefore sound.

### Round two fixes

All ten items above are fixed, one commit each, in order of severity, on 2026-10-10: c8cdbe3 (R1),
9949108 (R2), 77fb0a5 (R3), 4d4aa54 (R4), fee3657 (R5), 05c4b5e (R6), 2b51b40 (R7), 708f035 (R8),
4ba1cc4 (R9), c4dd595 (R10). Each message says what it changed, which tests it added and which of
them fail on the code before it; each **Status** line above summarises that and names the tests.
Two of the items were decisions rather than straight fixes and are reversible: R6 (reviews are out
of sandboxing altogether when "Follow reviewers' suggestions" is off) and R7 (file arguments are
handed over through the document portal rather than stated as a limit).

**Re-run after the fixes** (at c4dd595). Tier 1: 264 passed, 53 skipped. Tier 2 (Mint 22.1
container, xdg-desktop-portal 1.20.0): 46 passed, 1 skipped. Tier 3 (Ubuntu 24.04 VM, kernel
6.8.0-142, bwrap 0.9.0, AppArmor profile loaded): 46 passed, 1 skipped — the first VM run since the
round began, so the launcher changes of R3, R4, R7 and R8 are shown on real AppArmor-restricted
userns too.

**For the next reviewer.** Finding 0 was decided after this round (option a) and is done; see
"Finding 0" below. Things worth a look that this round touched but didn't exhaust:
- R4's `--appkata-menu` word: an app-menu entry written before 4d4aa54 lacks it until the entry is
  rewritten (next update or sandbox change); `_heal_launchers` does not rewrite entries.
- R7's helper needs `python3-gi` on the host; the Debian family has it, other distributions may
  not, and then file arguments silently pass through as before. A `flatpak document-export`
  fallback would cover hosts with Flatpak and no gi.
- R3's list is the longest it has been; a reviewer with a different desktop (GNOME extensions in
  `~/.local/share/gnome-shell`, `~/.config/kioslaverc`, …) may see further persistence paths worth
  adding. The pattern is one line per root in `_protected_roots()` plus a row in the two tests.
- Screenshots were not regenerated this round; no screen changed its content (the chips' root is a
  correctness change, the badge rules change only when the pref is off).

### Finding 0: option (a), done

**Decision (owner, 2026-10-11):** present the app to the portals as a host caller and narrow the
proxy — option (a) of finding 0, requirement 17.6.1. Commit 15ae403; its message is the full account.

**What changed.** The proxy's own bwrap no longer binds `/.flatpak-info` (the portals judge the
caller by the proxy's root). `proxy_args` replaces `--talk=org.freedesktop.portal.Desktop` with
`portal_rules()`: `--call` rules for Notification, OpenURI, Settings, Inhibit, Print, Email,
NetworkMonitor, ProxyResolver, MemoryMonitor on the portal object, Request and Session objects,
Introspectable (`gdbus call` types its arguments from it), and `--broadcast` rules for those
interfaces' signals; nothing else on that name — not Background, DynamicLauncher, Documents, Camera,
ScreenCast, RemoteDesktop, Screenshot, Location, Realtime, Account, Trash, FileChooser, nor
Properties. The launcher no longer sets `GTK_USE_PORTAL=1` and binds nothing at
`$XDG_RUNTIME_DIR/flatpak-info`, so GTK, Qt and xdg-open keep their in-process dialogs, which show
the sandbox's view. A small `xdg-open` (`XDG_OPEN_SHIM`, written to `sandboxes/.identity/bin`,
bound at `/run/appkata`, first on the app's PATH) sends a URL through `gdbus`/`busctl` and a file as
a descriptor through `python3-gi` to the OpenURI portal. The marker in the app's root stays (PipeWire,
GLib) and carries `[Context] shared=network` when the app has the network grant, which is what GLib's
NetworkMonitor reads. Requirements 17.5, 17.6, 17.6.1 (now the decision) and 17.6.3 (new); design
doc recipe items 6–7, template table, verification item 4, Limits, scripts table;
`local-proxy-test-plan.md`; `validate-chooser.sh` header records both outcomes.

**Why these interfaces and not Properties.** xdg-dbus-proxy's `--call` rules were read from its
source (`filter_new_from_rule`, `filter_matches`): `IFACE.*@/path` and `@/path/*` are supported, a
call rule makes the name visible, and unicast signals (Request.Response, ActionInvoked) always pass;
only broadcasts need a rule. The portal's `open-uri.c` (1.20) was read for host-caller handling:
the app chooser and content-type logic apply to host callers too, only the writable-fd check is
relaxed. Properties are denied because Chromium/Electron switch to the portal file chooser whenever
they can read FileChooser's `version`; GLib's NetworkMonitor uses `DO_NOT_LOAD_PROPERTIES`, and
GTK/Qt probe versions only when told to use the portals. This Chromium behaviour was not exercised
with a real Electron app here (no display in the launcher container) — worth one manual check with
an Electron AppImage in the session container: its Open dialog should be GTK's, showing the private
home.

**Evidence.** Unit: `test_the_portals_see_the_app_as_a_host_caller_through_a_narrowed_proxy`,
`test_a_sandboxed_app_gets_an_xdg_open_that_asks_the_host` (`tests/test_sandbox.py`). Run, with
xdg-desktop-portal 1.20 itself on the test bus (`_DesktopPortal`):
`test_the_portals_answer_a_sandboxed_app_as_a_host_caller` — NetworkMonitor answers `(true,)`,
FileChooser and Background get the proxy's bare `AccessDenied`, the Documents name is unknown; on
the code before 15ae403 it fails with "Portal operation not allowed: Failed to open file
…/.flatpak/web/bwrapinfo.json", the finding itself. `test_links_and_files_an_app_opens_go_to_the_host_through_the_portal`
runs a stand-in OpenURI service (`_FAKE_OPENURI`, answering with a Request path and its Response
signal, which `gio open` waits for) and sees the URL, a granted-folder file by its host path, and
GLib's own call. Re-run after the change: tier 1 266 passed, 55 skipped; tier 2 48 passed, 1
skipped; tier 3 (Ubuntu 24.04 VM, kernel 6.8.0-142, bwrap 0.9.0, AppArmor profile loaded) 48
passed, 1 skipped. `validate-chooser.sh` in the session container: `REFUSED … AccessDenied` from the
proxy, the by-app view present and empty.

**Limits found on the way, all stated (17.6.3, Limits, the shim's comment).**
- A file in the private home can't be opened on the host through the shim: the portal resolves the
  descriptor via `/proc/self/fd`, which yields the path the file has inside the sandbox (`$HOME/x`,
  the private home being mounted over `$HOME`), where the host has no such file, and the portal
  checks the inode. The stand-in test showed this directly (it first asserted the sandbox-home path
  and saw the real-home path). A file in a granted folder or the hand-over view opens.
- An app whose own AppRun sets `GTK_USE_PORTAL=1` loses its GTK file dialog (the proxy denies the
  portal; GTK3 then emits a delete-event and shows nothing). The launcher can't undo what AppRun
  sets inside the sandbox; if such an app turns up, a per-app environment override is the fix.
- The shim needs `gdbus` (libglib2.0-bin) or `busctl` for URLs and `python3-gi` for files; without
  them it says so on stderr and exits 3.
- The chooser-portal hand-over described in decision 4 of the design doc is gone by design; the
  design doc's verification item 4 and Limits say what replaces it ("Open with", drops, grants).

---

## Round Three Review

Review of the fixes at c2ff54f (branch `app-sandboxing`, everything through finding 0's commit
15ae403), 2026-10-11. Line numbers are as of that commit. Nothing here is a regression of an earlier
fix; items 1–3 are gaps the earlier rounds' tests did not reach, 4–6 are test and wording gaps.
**All six are fixed** (same day), one commit each, in the order 2 → 6 → 3 → 1 → 4 → 5; each
**Status** line names the commit and its tests, and "Round three fixes" at the end has the re-run.

**What was re-run** (all as documented in "For the reviewer of the fixes"). Tier 1
(`.venv/bin/python -m pytest -q tests/`): 266 passed, 55 skipped. Tier 2 (`scripts/test-sandbox.sh
launcher`, Mint 22.1 container, xdg-desktop-portal 1.20.0, GLib 2.80): 48 passed, 1 skipped. Tier 3
(`scripts/test-sandbox.sh launcher-vm`, Ubuntu 24.04 VM, AppArmor profile loaded): 48 passed, 1
skipped. The PR body's "Review fixes" table matches the commits through 15ae403.

**Probes.** Three were run in the tier-2 image on top of `tests/test_sandbox_run.py`'s helpers
(probe A: item 1, with a handler for `x-scheme-handler/https` and `text/plain` registered in the
container's `/usr/share/applications` first; B: item 4; C: item 3) and one locally with
`build_launcher` (item 2). As in round two, each became a regression test with its fix — named in
the Status lines — and the probe file was deleted; the handler registration became
`scripts/sandbox/register-test-handler.sh`, which both harnesses now run as root before the tests.

### R3-1. A GLib program opens links and files *inside* the sandbox when the host has a handler — MEDIUM (17.6.3 claim wrong)

**Status: fixed** (2da76d5, "Hide the host's desktop entries from the sandbox, so GLib opens links
on the host"). The launcher masks `/usr/share/applications` and `/usr/local/share/applications`
with an empty tmpfs at every level (only the folders that exist: no `--tmpfs-try`, and a missing
one under the read-only `/usr` can't be created); GLib then finds no handler and asks the portal.
Cost, stated in 17.4 and the Limits: an app that lists installed applications sees none, as in
Flatpak. Tests: `test_a_glib_program_opens_links_on_the_host_even_when_the_host_has_a_handler`
(tier 2 and 3, with the handler the harness registers; fails on the previous launcher — 15 entries
in view, the handler ran inside) and `test_the_hosts_desktop_entries_are_hidden_from_the_sandbox`
(unit). 17.6.3, the Limits and the shim's comment now say who takes which road.

17.6.3, the design doc's Limits and the shim's comment say GLib-based apps reach the OpenURI portal
"on their own" from `/.flatpak-info`. GLib does not: `g_app_info_launch_default_for_uri` (gio/gappinfo.c)
looks up the default handler first and uses the portal only when it finds none. The sandbox binds the
host's `/usr` read-only, so `/usr/share/applications` and its `mimeinfo.cache` are in view, and on
any real desktop that registers `firefox.desktop` for `https` and `xed.desktop`/`gedit` for
`text/plain`. GLib then runs that handler *in the sandbox*: a second browser with the private home as
its profile (and no network under `offline-editor`/`strict`-ish grants), a text editor that can't
see the host's files. The run test passes only because the tier-2 image registers no handlers.

**Confirmed** (probe A, GLib 2.80.0, portal 1.20): with a handler registered for `https` and
`text/plain`, `gio open https://example.com/x` and `gio open ~/Documents/n.txt` (a granted folder)
from inside an `online-app` launcher both ran the handler inside the sandbox (its marker appeared in
the app's private home) and the OpenURI stand-in saw nothing; without the handler registered, both
went to the portal, as the existing test shows.

Who takes this road: `gio open`; GTK3's `gtk_show_uri`/`gtk_show_uri_on_window` (GTK 3.24 decides
portal use from `$XDG_RUNTIME_DIR/flatpak-info` or `GTK_USE_PORTAL`, neither set, so it calls the
GLib function — `libgtk-3.so.0` has no `/.flatpak-info` string); any app calling the GLib function
directly. Not Qt: with `/.flatpak-info` present Qt's `QGenericUnixServices::openUrl`/`openDocument`
calls the OpenURI portal itself (`OpenURI`/`OpenFile` with a descriptor, both allowed) and runs
`xdg-open` only as a fallback — so the "Electron and Qt run xdg-open" wording is also inaccurate,
harmlessly. GTK4 reads `/.flatpak-info` (`libgtk-4.so.1` 4.14 carries the string) and its
`GtkUriLauncher` prefers the portal when that says sandboxed; not exercised here.

**Fix sketch:** make the lookup find nothing, as a Flatpak runtime does: after the `/usr` bind add
`--tmpfs /usr/share/applications --tmpfs /usr/local/share/applications` (keep `/usr/share/mime`,
which the MIME sniffing needs). Side effect to state: an app that lists installed applications
("open with…" menus) sees none — the same as in Flatpak. Alternative: a `mimeapps.list` in the
private home can't cover every type. Test: the tier-2 harness runs as root before `su kata`, so it
can register the probe's handler in `/usr/share/applications` for the whole run; then extend
`test_links_and_files_an_app_opens_go_to_the_host_through_the_portal` to assert the portal saw the
`gio open` calls and no marker appeared in the private home. Re-word 17.6.3, the Limits and the shim
comment (GLib's road, Qt's road).

### R3-2. Strict doesn't enforce its own table: folders, sound and services ride along, and the chips say what isn't given — MEDIUM (17.2 / 17.4, spec mismatch)

**Status: fixed** (ea1cfa9, "Make Strict mean its table everywhere"). `normalize()` clears folders,
network, ports, sound, caps, the non-X11 devices and `write_app` at level strict, so the launcher,
the chips, the badge comparisons and the marker agree; the dialog switches the working set to
Standard the moment a widening grant is added at Strict and says so in one line (`setField`/
`widens` in `SandboxDialog.qml`). 17.2.1 states both. Test:
`test_strict_drops_every_grant_that_would_widen_it` (unit; fails on the previous `sandbox.py`).

17.2's table and 17.4 say Strict is "private only" — no folders, no network, no bus, and the blurb
says no desktop services. The launcher forces only the network off at Strict (`net = gs["network"]
and not strict`, `sandbox.py:1165`); folder grants (`:1236-1241`), the sound sockets (`:1245-1247`)
and devices are baked whatever the level, and `summary_chips` shows every grant as given.

**Reachable** two ways: a review line `Sandbox: strict` with `Sandbox folders: +~/Documents` or
`Sandbox network: yes` (`config_from_review` applies the overrides to the Strict template), and the
dialog — pick Strict, open Customize, add a folder or toggle sound/notifications/network (the
working set keeps `level: strict`, saved as `{custom}`). Shown locally: `apply_overrides(strict,
{folders: {+~/Documents: rw}, network: True})` plus sound and the notifications cap gives a launcher
with `--bind-try ~/Documents`, the PipeWire/Pulse binds, no `--share-net` and no proxy, while the
chips read `Strict · private home · ~/Documents · Network · Sound · Notifications` — two of them
untrue, two of them contrary to the level. (The marker side already has the rule: the finding-0 test
asserts no `[Context] shared=network` for a Strict set with network set.)

**Fix sketch:** decide what Strict means and make one place say it. The least surprising: `normalize()`
(or `grants_from_config`) clears `folders`, `network`, `sound`, `caps` and the non-`x11` devices when
`level == "strict"`, so the launcher, the chips, the badge comparisons and the marker all agree; the
dialog then shows the controls disabled at Strict (or the dialog could flip the level to Standard
the moment a folder is added — say which in 17.2). Tests: extend
`test_strict_launcher_has_no_bus_no_network` with a folder/sound/caps override and assert no bind or
socket for them; a chips test that the Strict summary carries no Network/Notifications chip; a
review-line case in `tests/test_sandbox.py`.

### R3-3. A CLI tool run from a refused folder can't open the file it was given — LOW (17.6.2 gap)

**Status: fixed** (7fd3625, "Hand over a CLI tool's file arguments from a refused folder too"). The
`$cwd` decision moved into the launcher header ahead of the file-argument block (`_CWD_DECIDE`; the
bwrap words stay after, `_CWD_WORDS`), and the forward call counts the directory as visible only
when it will be shared (`${cwdvis:+"$cwdvis"}`). Tests:
`test_a_cli_tool_run_from_a_refused_folder_is_still_given_its_file_arguments` (tier 2/3; fails on
the previous `sandbox.py`) and the order check in
`test_launcher_hands_over_file_arguments_only_for_standard_apps`. 17.6.2 and the "can't see" notice
say it.

`_FORWARD_BLOCK` runs in the launcher header, before `_CWD_BLOCK` decides whether `$cwd` is shared,
and for a CLI tool its visible list always includes `"$PWD"` (`sandbox.py:1103`). When the folder is
then refused (the home, `~/.config`, `~/.local/bin`…) a file argument inside it is treated as already
visible and not handed over, and the tool — now in its private home — can't find it by the relative
or the absolute path. 17.6.2 says a CLI tool's own directory "keeps its real path", which holds only
when the directory is shared.

**Confirmed** (probe C, tier 2 with the document portal): `cd ~ && tool Documents/notes.txt` and
`tool ~/Documents/notes.txt` both end in "No such file or directory" inside the sandbox, with the
"can't see" notice on stderr; the same file from a project folder, or `~/Documents` granted, works.

**Fix sketch:** compute `share` before the forward block (move the cwd test up, keep the bind words
where they are) and pass `"$PWD"` as visible only when `share=1`. The helper already resolves a
relative argument against the host's working directory (`os.path.isfile`/`realpath`), so the rewritten
argument is absolute. Test: a `where=home` case beside `test_a_file_argument_is_handed_over_to_a_standard_app`.

### R3-4. The Properties denial is load-bearing for three toolkits and only its rule text is tested — LOW (test gap, comment wrong)

**Status: fixed** (75269dd, tests and wording only). `test_the_portals_answer_a_sandboxed_app_as_a_host_caller`
now calls `Properties.Get … FileChooser version` from both apps and asserts the proxy's
AccessDenied; the comment above `PORTAL_INTERFACES`, the marker's comment in the launcher, 17.5 and
17.6.3 name GTK4, Qt and Chromium as the readers of `/.flatpak-info` and say the denial is what
holds them.

Finding 0 denies `org.freedesktop.DBus.Properties` on the portal name "because Chromium/Electron
switch to the portal file chooser when they can read FileChooser's `version`", and the code comment
(`sandbox.py:667-669`) and 17.6.3 say GTK and Qt probe "only when told to use the portals". That is
true of GTK3 (it reads `$XDG_RUNTIME_DIR/flatpak-info` or `GTK_USE_PORTAL`, which the launcher
withholds), not of the other two, which read `/.flatpak-info` — bound in the app's root: Qt prepends
its `xdgdesktopportal` platform theme whenever that file exists (`checkNeedPortalSupport` in
qguiapplication.cpp) and that theme reads FileChooser's `version` through `Properties.Get`, using the
portal dialog when it is non-zero and the base theme's otherwise; GTK4's `gdk_should_use_portal`
reads the same file (`libgtk-4.so.1` 4.14 carries the string) and its file dialog reads the
FileChooser `version` property before choosing the portal. So the denial, not the missing
environment, is what keeps GTK4, Qt and Chromium apps on their own dialogs — the right outcome, for
the wrong stated reason, and a reviewer who later allows Properties (say, for a portal that needs
`version`) would flip all three to a chooser that returns paths the sandbox can't open.

**Confirmed** (probe B): `Properties.Get org.freedesktop.portal.FileChooser version` and the same for
`OpenURI` get the proxy's immediate `AccessDenied` (no timeout, so no startup delay for Qt).

**Fix sketch:** add a `Properties.Get … FileChooser version` line to
`test_the_portals_answer_a_sandboxed_app_as_a_host_caller` (the unit test only checks the string
`DBus.Properties` is absent from the rules); correct the comment above `PORTAL_INTERFACES` and
17.6.3/Limits to name GTK4 and Qt alongside Chromium as readers of the marker. The manual check
round two asked for (an Electron AppImage's Open dialog in the session container) should include a
Qt and a GTK4 app for the same reason.

### R3-5. Text left behind by finding 0 — LOW

**Status: fixed** (03305dc for the test plan's launcher shape; the dialog hint went with R3-6, the
Qt/Electron wording and the Limits with R3-1, the reader list with R3-4; the PR body's stale lines
were edited with the round-three rows).

- `src/appkata/qml/SandboxDialog.qml:171`, the "Desktop services (portals)" toggle's hint: "File
  chooser, notifications and opening links — always on". The file chooser is denied now (17.6.3).
  Not in any screenshot (A25 is cut off above that row), so no regeneration.
- `docs/local-proxy-test-plan.md:64`: the launcher shape still shows `--setenv GTK_USE_PORTAL 1` and
  lacks the `/run/appkata` shim bind and PATH; the document is cited as "the launcher shape" by this
  file's intro.
- The PR body: decision 4 ("The document portal still hands over individually picked files
  regardless"), the "Still owed" line ("the portal file chooser's hand-over … see the open decision
  under Review fixes"), and the harness paragraph's 38 passed / 1 skipped for both tiers. The
  finding-0 row and the "Decided" paragraph are right; the earlier sections above them aren't.
- 17.6.3, the design doc's Limits and the shim's comment: "Electron and Qt run xdg-open" — see R3-1
  for what Qt does.

### R3-6. The Notification portal is open to every Standard app, whatever the chips say — LOW (17.5.1, say or gate)

**Status: fixed, gated** (34969d6, "Open the Notification and Inhibit portals with their
capabilities, not to every app"). Chosen over documenting the exception because the chips are
presented as the truth about what an app can do (the sound chip is the precedent). The Inhibit
portal had the same shape and is gated the same way. Each capability now opens both roads (portal
interface and direct name); `PORTAL_INTERFACES` keeps OpenURI, Settings, Print, Email and the
monitors. Tests: `test_the_notification_and_inhibit_portals_come_with_their_capabilities` (unit) and
the Notification/Inhibit calls added to the host-caller run test (both fail on the previous
`sandbox.py`). 17.5, 17.5.1, the design doc and the test plan's table say it. Reversible: drop the
two `_portal_call` entries from `CAP_PROXY_ARGS` and put the names back in `PORTAL_INTERFACES`.

`portal_rules()` allows `org.freedesktop.portal.Notification` for every Standard app; the
`notifications` capability only adds direct `--talk=org.freedesktop.Notifications`. A GLib app with
`/.flatpak-info` sends notifications through the portal, so an `offline-editor` (no capability, no
"Notifications" chip) notifies anyway. Flatpak behaves the same, but AppKata's summary presents the
capability as the switch. Either gate the portal rule on the capability (one line in `proxy_args`,
plus a case in `test_proxy_args_map_capabilities`) or say in 17.5.1 and the chip's hint that the
portal road is always open and the capability covers the direct one.

### Verified this round, no change needed

- The round-two "deliberately leaves" list and finding 0's limits are still stated where the intro
  says (17.4, 17.6.1–17.6.3, 17.17, 14.2.1, the design doc's Limits, the shim).
- `_activate` clears `rec["links"]` and the `appkata-` files before re-adding them, so
  `rewrite_launcher` (every sandbox change, every heal) doesn't accumulate links or entries.
- GTK3 has no `/.flatpak-info` reader (string absent from `libgtk-3.so.0` 3.24.41), so the marker in
  the app's root cannot switch a GTK3 app to the portal chooser; only `GTK_USE_PORTAL` can, as stated.
- The install-dialog answer path (R1/R2) and `setSandbox(null)` → re-pin were re-read against the
  tests; nothing further.

### Round three fixes

All six items above are fixed, one commit each, on 2026-10-11: ea1cfa9 (R3-2), 34969d6 (R3-6),
7fd3625 (R3-3), 2da76d5 (R3-1), 75269dd (R3-4), 03305dc (R3-5). Each message says what it changed,
which tests it added and which of them fail on the code before it. One was a decision and is
reversible: R3-6 (the Notification and Inhibit portals come with their capabilities rather than
being open to every Standard app). R3-2's dialog behaviour (Strict flips to Standard when a widening
grant is added) is a UI choice the owner may prefer as disabled controls instead; `normalize()`'s
rule stands either way.

**Re-run after the fixes** (at 03305dc). Tier 1: 269 passed, 57 skipped. Tier 2 (Mint 22.1
container, xdg-desktop-portal 1.20.0, GLib 2.80, the test handler registered): 50 passed, 1 skipped.
Tier 3 (Ubuntu 24.04 VM, kernel 6.8.0-142, bwrap 0.9.0, AppArmor profile loaded, the test handler registered): 50 passed, 1 skipped.
Tier 3 was also run at 2da76d5 (R3-1 alone): 50 passed, 1 skipped.

### For the next reviewer

- Two things changed in what every sandboxed app sees, and only the container and VM exercised
  them: the empty tmpfs over `/usr/share/applications` (R3-1) and the Notification/Inhibit portals
  only with their capabilities (R3-6). A real desktop check is the next evidence: a GTK3 app's
  "open link" lands in the host browser; a GLib app with no `notifications` capability fails to
  notify quietly rather than hanging (the proxy's denial is immediate, so no hang is expected); and
  an app that lists installed applications shows none without erroring. The round-two manual check
  (an Electron AppImage's Open dialog in the session container) now also covers GTK4 and Qt (R3-4).
- A KDE/KIO app's `KIO::OpenUrlJob` with the applications folder empty was not exercised; Qt's own
  `QDesktopServices::openUrl` takes the portal (it sees `/.flatpak-info`), but KIO consults
  `ksycoca` first and may show an empty "open with". Worth one check with a KDE AppImage.
- Round two's open notes still stand: the `python3-gi` fallback for the file-argument helper, the
  per-desktop persistence paths, and that no screenshot has changed its content since f94bcfc (the
  dialog hint and the Strict note are below the fold in A21/A25).
- Once these land, this file's intro says it should be folded into `docs/app-sandboxing.md` and
  deleted; it has grown to three rounds and the "Status" lines are the record that matters.

---

## Round Four Review

Review of the fixes at 7323c5e (branch `app-sandboxing`, everything through round three),
2026-10-11. Line numbers are as of that commit. None of the items is a regression of an earlier
fix; items 1–4 are bugs in paths the earlier rounds' tests did not reach (two of them in the UI's
save paths), 5–9 are wording, hygiene and one claim that the evidence does not support. **All nine
are fixed** (same day), one commit each, in order 1 → 9; each **Status** line names the commit's
subject and its tests, and "Round four fixes" at the end has the re-run.

**What was re-run** (all as documented in "For the reviewer of the fixes"). Tier 1
(`.venv/bin/python -m pytest -q tests/`): 269 passed, 57 skipped. Tier 2 (`scripts/test-sandbox.sh
launcher`, Mint 22.1 container): 50 passed, 1 skipped. Tier 3 (`scripts/test-sandbox.sh launcher-vm`,
Ubuntu 24.04 VM, kernel 6.8.0-142, bwrap 0.9.0, AppArmor profile loaded, test handler registered):
50 passed, 1 skipped. The PR body's "Review fixes" table matches the commits through 03305dc.

**Probes.** Four backend probes locally (items 1, 3, 4, 7: a Backend with two Trusts, the install-
dialog answer path, the heal pass over a doctored launcher, a switch to Off), two in the tier-2
container on top of `tests/test_sandbox_run.py`'s `Env` (item 2: a launcher started by a parent
that exits three seconds later; item 8: an abstract-namespace socket bound on the host and connected
to from inside), and one in the session image (`appkata-sandbox-session`, item 5): Xvfb, a session
bus with xdg-desktop-portal 1.20 and the gtk backend, and three tiny apps — GTK3
(`Gtk.FileChooserNative`), GTK4 (`Gtk.FileDialog`, application id `io.appkata.gtk4`) and Qt 6.4
(PyQt6 `QFileDialog`, with `qt6-xdgdesktopportal-platformtheme` installed) — each behind a generated
`online-app` launcher, with `--log` added to the proxy, run as generated and again with the
Properties interface allowed and with Properties plus FileChooser allowed; a fourth app ran `gdbus`
against the same three launchers to show what each rule change lets through. As in earlier rounds,
each probe is described well enough here to become a regression test with its fix; none is committed.

### R4-1. Saving the Sandbox dialog on an app whose template is "custom" crashes, and the bad config sticks — HIGH (functional)

**Status: fixed** ("Refuse a sandbox config that names no template, before it is saved"). Three
layers: `sandbox.config_error()` says why a config can't be resolved and `grants_from_config`
raises `ValueError` instead of `KeyError`; `setSandbox` and `installWith` refuse such a config
with a toast before writing; `_user_sandbox_config` ignores (and logs) one already in a row, so a
row poisoned by the old code heals itself; and the dialog sends `{custom: gs}` whenever the
template is "custom" (and hides "Reset to template" there, since there is nothing to reset to).
Tests: `test_saving_the_dialog_on_a_merged_review_app_keeps_what_it_showed`
(`tests/test_sandbox_backend.py`, fails with the KeyError on the previous code) and
`test_a_config_naming_no_template_is_refused_not_looked_up` (`tests/test_sandbox.py`).

**Where:** `SandboxDialog.qml:245` sends `{template: root.tpl, overrides: {}}` whenever nothing was
customized, and `root.tpl` is `info.template`, which `sandbox.choose()` sets to `"custom"` for an
app with two or more Trusts' Sandbox lines (`sandbox.py:369`), for a pin taken from such reviews
(`:365`), and for a user's own custom set (`:363`; the dialog marks that one `customized`, `:27`,
but "Reset to template" at `:109` clears the flag and leaves `tpl` as it is). `grants_from_config`
then calls `resolve_template("custom")`, which is `TEMPLATES["custom"]` (`:121`): `KeyError`.

**Consequence:** `setSandbox` has already written `saved["sandbox"] = {"template": "custom"}` to
`app_settings` before it resolves (`backend.py:1841-1844`), so the exception leaves the broken
choice in the row; from then on every `sandboxInfo()` and `detail()` for that app raises the same
`KeyError` (`_resolved_sandbox` → `choose` → `grants_from_config`), i.e. App Detail for the app is
dead until the row is edited by hand, and the launcher is never regenerated. Reached by: two Trusts
reviewing the same app, open Sandbox, press Save without touching anything.

**Confirmed** (local, Backend with two Trusts, `online-app` and `offline-editor`): `sandboxInfo`
reports `template: custom, source: reviews`; `setSandbox(url, {"template": "custom", "overrides":
{}})` raises `KeyError: 'custom'`; the row holds the config; `sandboxInfo` afterwards raises.

**Fix sketch:** two layers. In the backend, make `grants_from_config` (or `resolve_template`) treat
an unknown template as an error that `setSandbox` rejects *before* saving (a toast, nothing
written), so no UI mistake can poison the row; and in the dialog, send `{custom: root.gs}` whenever
`tpl === "custom"`, customized or not, so a plain Save on a merged-review app pins what it shows.
Test in `tests/test_sandbox_backend.py`: two Trusts → `setSandbox` with the template `sandboxInfo`
reported → no exception, `source == "user"`, chips unchanged; and `setSandbox(url, {"template":
"nonsense"})` leaves the row untouched.

### R4-2. A Strict app dies when whatever started it exits — AppKata's Open included — MEDIUM (functional, the default template)

**Status: fixed** ("Run bwrap as the launcher's child at every level, so a Strict app outlives
whatever started it"). The launcher no longer `exec`s bwrap at Strict: bwrap is the shell's child
at every level, `status=0` / `|| status=$?` / `exit $status` carry the program's exit code out, and
the proxy teardown stays Standard-only. Tests: `test_the_app_outlives_the_process_that_started_it`
(`tests/test_sandbox_run.py`, both levels; fails for `strict` on the previous launcher in the tier-2
container) and the changed shape assertion in `test_strict_launcher_has_no_bus_no_network`. Tier 2:
52 passed, 1 skipped; tier 3 (Ubuntu 24.04 VM): 52 passed, 1 skipped.

**Where:** the Strict launcher `exec`s bwrap (`sandbox.py:1241`, "exec the sandbox so it replaces
this shell") with `--die-with-parent` (`:1305`). After the `exec`, bwrap's parent is the launcher's
*caller*, and `--die-with-parent` kills the sandbox when that parent dies. A Standard launcher runs
bwrap as a child of the shell (it has a proxy to tear down), so there the parent is the shell, which
lives as long as the app.

**Consequence:** every Strict app — the default for every unreviewed GUI app (17.3.3) — is tied to
the process that started it. Open it from AppKata and quit AppKata: the app is killed (`launch()`
starts the launcher from the UI thread; the death signal fires when that thread exits). Start it
from the app menu and the desktop shell restarts or crashes (Cinnamon's "restart", GNOME's Alt-F2
`r`): killed. Start it through a launcher that exits at once (`gio launch`, `gtk-launch`, `dex`, a
script): killed or not depending on whether the launcher reached `exec` first. None of this happens
to a Standard app started the same way.

**Confirmed** (tier 2): a Python parent that `Popen`s the launcher, sleeps three seconds and exits,
with the app writing a mark into its private home after six seconds — `strict`: the mark never
appears (the app died with its parent); `online-app`: it does. A parent that exits *before* the
launcher reaches bwrap leaves both alive, which is why the existing tests (every one of which waits
for the launcher) never saw it.

**Fix sketch:** run bwrap as a child in the Strict launcher too (`bwrap … ; exit $?`, the shape
Standard already has), or drop `--die-with-parent` from the `exec` form — the former keeps the
teardown semantics identical across levels. `test_strict_launcher_has_no_bus_no_network` asserts
`"exec bwrap" in text` and must change with it. Regression test: the probe above, in
`tests/test_sandbox_run.py`, for both levels.

### R4-3. A sandbox chosen in Install options for an installed app is saved but never applied — MEDIUM (17.4 / 17.11)

**Status: fixed** ("Apply a sandbox chosen in Install options to an installed app at once"):
`installWith` with `install: false` and a sandbox choice, on an installed, non-foreign app,
regenerates the launcher and writes the "set the sandbox of" audit entry, as `setSandbox` does;
the dialog's footer says the sandbox applies at the next start when the card was touched. Test:
`test_a_sandbox_chosen_in_install_options_for_an_installed_app_applies_at_once`
(`tests/test_sandbox_backend.py`; fails on the previous `backend.py` with `--share-net` still in
the launcher).

**Where:** the install dialog's Save for an installed app (`root.change`) sends `install: false`
(`InstallDialog.qml:333`) and, when the Sandbox card was touched, the `sandbox` choice.
`installWith` (`backend.py:791-810`) saves it through `_answer_install_dialog` and calls
`reload()`; only `_install` → `_activate` or `setSandbox` → `_regenerate_launcher` ever rewrite the
launcher, and neither runs here. The Sandbox card is visible in that dialog
(`InstallDialog.qml:209-247`, no `!root.change` in its `visible`).

**Consequence:** the user's choice wins in `_resolved_sandbox` at once, so App Detail shows the new
level and chips with the "Sandboxed" pill (the launcher file exists), while `~/bin/apps/<app>/run`
keeps the old grants until the next update or a save in the Sandbox dialog. The footer says
"Applies from the next update." in small print; the detail page contradicts it. The Sandbox dialog
itself does regenerate (`setSandbox`), so the two surfaces disagree.

**Confirmed** (local): an installed, launcher-bearing `online-app`; `installWith(url, {"kind":
"tarball", "appMenu": True, "install": False, "sandbox": {"template": "strict", …}})`;
`sandboxInfo` → `level: strict, source: user, active: True`; the launcher on disk still carries
`--share-net` and the proxy.

**Fix sketch:** in `installWith`, when `install` is false and a `sandbox` key was sent (and the app
is installed and not foreign), call `_regenerate_launcher(url)` as `setSandbox` does — or route the
card's choice through `setSandbox` itself, which also audits it (17.16 says every sandbox change is
audited; this path writes no audit entry either). Test beside
`test_resaving_install_options_keeps_the_pin…`: the launcher text changes with the choice.

### R4-4. A launcher written by an older AppKata is never regenerated — MEDIUM (design gap; every launcher fix in this PR has it)

**Status: fixed** ("Regenerate at startup any launcher that is not the one AppKata would write
today"). Chose the comparison over a format stamp: `sandbox.launcher_text()` is the pure text
`write_launcher` writes (the helpers it refers to live at fixed paths), `install.launcher_is_current()`
compares the file with it, and `_heal_launchers` rewrites any that differ — a launcher a previous
AppKata wrote, or a hand-edited one — on the startup thread. The desktop entry is rewritten with
it (`_activate`), so a stale `--appkata-menu` word goes too, but only when the launcher text also
differs; an entry alone is not compared. 17.4 says so. Test:
`test_the_startup_pass_regenerates_a_launcher_an_older_appkata_wrote`
(`tests/test_sandbox_backend.py`; fails on the previous `backend.py`, which returned `[]` for the
doctored launcher).

**Where:** `_heal_launchers` (`backend.py:1900-1921`) skips any app whose launcher file exists
(`:1908`); nothing else rewrites a launcher except an update, a sandbox change or the heal of a
*missing* one. Nothing in the launcher says which AppKata wrote it.

**Consequence:** the launcher text is the enforcement (17.4: "its text is exactly what runs"), and
this PR alone changed it in nine of its fixes (the symlink guard, the refused folders, the narrowed
proxy, the capability-gated portals, the desktop-entry mask, the shim, the log redirect, the
file-argument block, the seccomp filter). An app installed before any such change keeps running
with the old text until the user happens to update it or touch its sandbox. The same holds for the
desktop entry's `--appkata-menu` word (round two's open note). Today nobody has pre-PR launchers,
but the first post-release change to `build_launcher` will leave every installed app on the old
one, and a security fix to the launcher will not reach installed apps.

**Confirmed** (local): with the desktop-entry mask edited out of a written launcher,
`_heal_launchers()` returns `[]` and the file is left as doctored.

**Fix sketch:** in the heal pass, compare the file with what `build_launcher` would write now
(`rewrite_launcher` already does the work; the comparison is one `read()`), or stamp the launcher
with a format number (`# AppKata launcher format N` in `_LAUNCHER_HEADER`) and regenerate on
mismatch. The first is simpler and also catches a hand-edited launcher, which 17.4 says is not
allowed; it costs one `build_launcher` per installed app at startup, on the startup thread. Test:
`test_apps_installed_before_sandbox_support_get_their_launcher_once_it_works` gains a case where the
file exists but differs.

### R4-5. The Properties denial is not what holds GTK4 or Qt 6.4; the manual dialog check is now done for three toolkits — LOW (R3-4's claim, wording)

**Status: fixed** ("Say which denial keeps each toolkit on its own file dialog, and keep the probe
that shows it"). The comment above `PORTAL_INTERFACES`, the marker's comment in the launcher, 17.5,
17.6.3 and the run test's comment now say: GTK3 and Qt ≤ 6.4 never ask; GTK4 (and Qt 6.5+) ask and
are held by the FileChooser denial, falling back to their own dialog; Chromium reads `version`
first and is held by the Properties denial; both stay denied. The session probe is now
`scripts/test-sandbox.sh filedialogs` (`scripts/sandbox/filedialogs.py`, its own Mint 22.1 image
with Xvfb, the portal, its gtk backend, GTK3/GTK4 gir, PyQt6 and the Qt portal theme): one line per
toolkit and variant with the verdict and the portal calls the proxy saw. Electron and a Qt ≥ 6.5
app remain the real-desktop check.

**Claim** (round three, R3-4; `sandbox.py:685-691` and `:1292-1296`, 17.5 at `requirements.md:2225`,
17.6.3 at `:2272`, the Limits bullet at `app-sandboxing.md:749`): GTK4, Qt and Chromium read
`/.flatpak-info`, then FileChooser's `version` property, and "the denial [of Properties] is what
keeps all three on their own dialogs; allowing Properties would flip all three".

**What the session probe showed** (xdg-desktop-portal 1.20, gtk backend answering `version` 4 on the
host, the proxy's `--log` on):
- GTK3 3.24.41 never touches the portal in any variant: its own `FileChooserDialog`, as stated.
- GTK4 4.14.5, as generated: `Properties.GetAll` on the portal object (denied by the proxy), then
  `FileChooser.OpenFile` (denied) — and it **falls back to its own `FileChooserDialog`** (its
  `open_file_msg_cb` error handler runs the non-portal dialog). With Properties allowed: `GetAll`
  answered, `OpenFile` still denied, still its own dialog. With FileChooser allowed too: the
  portal's dialog (no `FileChooserDialog` among its toplevels). So for GTK4's Open the FileChooser
  denial is what holds it, it does not read `version` for that path (the source consults the
  version only for `SELECT_FOLDER`), and it degrades cleanly.
- Qt 6.4.2 (Ubuntu 24.04's Qt) with the portal theme plugin installed: **never touches the portal**
  in any variant — this Qt's `checkNeedPortalSupport()` looks for `$XDG_RUNTIME_DIR/flatpak-info`,
  which the launcher withholds, not `/.flatpak-info` (Qt 6.6's source reads `/.flatpak-info`, as
  round three said; Qt 5.15, which most Qt AppImages bundle, reads the runtime one). Forced with
  `QT_QPA_PLATFORMTHEME=xdgdesktopportal` it reads `version` at startup (denied → `QFileDialog`
  widget), and with `version` answered as 4 it *still* showed its own `QFileDialog` and never called
  `OpenFile`; the reason was not run down (the portal theme's `createPlatformDialogHelper` should
  return the portal helper when the version is non-zero), so for Qt the "would flip" half is
  unproven either way.
- Chromium/Electron was not exercised (no display-driven run here); its `IsPortalAvailable()` does
  read `version` and, unlike GTK4, cancels the dialog when `OpenFile` then fails, so for Electron
  the Properties denial likely is load-bearing — the only toolkit of the three for which the claim
  may hold, and the one still unchecked.

**Consequence:** the design outcome stands (every toolkit here shows its own dialog, with no hang
or empty dialog — the round-two/three manual check is done for GTK3, GTK4 and Qt 6.4), but the
explanation in the code comments, 17.5, 17.6.3 and the Limits names the wrong denial for GTK4 and a
marker Qt 6.4 does not read, and the run test added in R3-4 asserts the Properties denial as the
protection while the FileChooser denial it also asserts is the one doing the work.

**Fix sketch:** re-word the four places: GTK3 and Qt ≤ 6.4 never ask; GTK4 (and Qt 6.5+) ask and are
held by the FileChooser denial, falling back to their own dialog; Chromium reads `version` first and
is held by the Properties denial (keep it denied — nothing here needs it). Keep the Properties
assertion in the run test with that reason. The remaining manual check is one Electron AppImage
(Obsidian is in `build/sandbox-test/`) and one Qt ≥ 6.5 app; the session probe's shape — Xvfb, the
real portal with the gtk backend, a generated launcher, the app printing its visible toplevels, the
proxy's `--log` — is worth keeping as a `scripts/sandbox/` script, since it answers in a minute what
three rounds deferred to real hardware.

### R4-6. Text left behind by finding 0 and the seccomp change, in 17.4 and 17.18 — LOW

**Status: fixed** ("Bring 17.4 and 17.18 up to the launcher as built"): 17.4's launcher paragraph
now says no `GTK_USE_PORTAL`, the seccomp filter with `--new-session` as the fallback, the
hand-over as 17.6.2's, and bwrap as the launcher's child (R4-2); 17.18 defers a *fuller* seccomp
filter. Docs only.

- `requirements.md:2199-2201` (17.4): the launcher "sets `GTK_USE_PORTAL=1`", uses `--new-session`,
  and "see there for what currently stops the file chooser from doing so" (17.6 says nothing of the
  kind any more). The launcher sets no `GTK_USE_PORTAL` (17.6.3, `test_standard_launcher_binds_the_apps_document_portal_view`)
  and uses `--seccomp 3` with `--new-session` only as the no-filter fallback. R3-5 fixed the test
  plan and the dialog hint but not the spec's own launcher paragraph.
- `requirements.md:2390` (17.18) still defers "a **seccomp** filter" while 17.17 (`:2381`) says the
  terminal-injection filter exists; say "a fuller seccomp filter (Flatpak's)".

### R4-7. Switching an installed app to Off leaves its identity marker behind — LOW (hygiene, R10's other half)

**Status: fixed** ("Remove the identity marker with the launcher when an app is switched to
Off"): `_sandbox_launcher`'s Off/unsupported branch calls `sandbox.remove_identity`. Test: the
extended `test_off_uses_the_program_directly_no_launcher` (fails on the previous `install.py`).

`_sandbox_launcher` at Off/unsupported (`install.py:365-369`) pops `rec["launcher"]` and removes the
launcher file but not `.identity/<app>`; R10 made *uninstall* remove it. An app set to Off keeps a
stale marker in `sandboxes/.identity/` for good (and, when set back on, `write_flatpak_info`
overwrites it, so nothing worse). **Confirmed** locally: after `setSandbox(url, {"template":
"off"})` the launcher is gone and `identity_path("demo")` still exists. Fix: `sandbox.remove_identity`
in that branch; extend `test_off_uses_the_program_directly_no_launcher`.

### R4-8. With the network grant, X11's abstract socket is reachable whatever the X11 device grant says — LOW (17.9, say it)

**Status: documented** ("Say that the X11 toggle withholds the socket and the cookie, not the
server's reach"): 17.9, the design doc's Limits and the toggle's hint say it; the probe is the
test `test_the_x11_abstract_socket_follows_the_network_grant_not_the_x11_one` in
`tests/test_sandbox_run.py` (connects with the network, refused without, no socket file either
way). Not closed: no namespace shares the network without its abstract sockets, and Flatpak has
the same property.

`--share-net` shares the network namespace, and the X server's abstract-namespace socket
(`@/tmp/.X11-unix/X<n>`) lives there; the "X11 apps (XWayland)" toggle only governs the bind of
`/tmp/.X11-unix` and `DISPLAY`. **Confirmed** (tier 2): an abstract socket bound on the host;
`online-app` with `x11` removed from its devices connects to it from inside; `offline-editor`
without the network is refused. On GNOME/mutter and KDE/kwin Wayland, Xwayland is started with an
auth file, so the app still lacks the cookie and this is not a door; on wlroots compositors (no
auth) the toggle is void, but that session is warned about already; on an X11 session the toggle
does nothing by design. Flatpak has the same property. Say in 17.9 and the toggle's hint
(`SandboxDialog.qml:201`) that the toggle withholds the socket and the cookie, not the reachability,
and that "off" rests on the compositor's Xwayland cookie when the app has the network.

### R4-9. Persistence paths still open from round two — LOW (17.3.1, one line each)

**Status: fixed** ("Never share the desktop's extension and script folders, nor Firefox's
native-messaging hosts"): seven rows in `_protected_roots()`, with rows in
`test_protected_folders_are_never_granted` (plus two negatives: `~/.mozilla/firefox`,
`~/.local/share/plasma/look-and-feel`), `test_cli_launcher_protects_the_persistence_dirs_and_the_runtime_folder`
and two `where` cases (`gnome-extensions`, `kwin-scripts`) in
`test_cli_tool_never_gets_the_home_or_above_or_appkata_areas`; 17.3.1 and 17.3.3 list them.

Round two's note stands and can be closed with a row each in `_protected_roots()` and the two
tests: `~/.local/share/gnome-shell/extensions` (an enabled extension's code runs in gnome-shell at
the next login), `~/.local/share/kwin/scripts` and `~/.local/share/plasma/plasmoids` (KWin scripts
and Plasma widgets run inside kwin/plasmashell at login), `~/.local/share/nautilus/scripts`,
`~/.local/share/kservices5`/`kio/servicemenus` (scripts run from a file manager's menu on a click),
`~/.mozilla/native-messaging-hosts` and `~/.config/*/NativeMessagingHosts` (the latter already
refused under `~/.config`; the Firefox one is not). The threat is the one finding 4 and R3 closed:
a careless review line or a picker click.

### Verified this round, no change needed

- Tier 1, 2 and 3 counts match the "Round three fixes" paragraph exactly.
- xdg-desktop-portal 1.20's `open-uri.c` treats a host caller like a sandboxed one for the app
  chooser and content-type logic (only the writable-fd check is relaxed), as finding 0's account
  says; `OpenURI`/`OpenFile` for a host caller is therefore not a silent "open anything with
  anything".
- xdg-dbus-proxy honours a `--call … org.freedesktop.DBus.Properties.*@/org/freedesktop/portal/desktop`
  rule when one is added (the `gdbus` probe: `version` answered, `OpenFile` still denied), so the
  per-interface rule shape of finding 0 composes as expected.
- GTK3's, GTK4's and Qt 6.4's file dialogs inside a generated launcher are their own, with the real
  portal running on the host (R4-5): the behaviour the design wants, now shown rather than inferred.
- The CLI tool's working-directory rule, the forward helper's visibility list and the guard were
  re-read against the tests; nothing further. The forward helper hands over a file named from a
  protected folder (`tool ~/.ssh/config`) as well — that is the user naming the file, as Flatpak's
  file forwarding does, and not a finding.

### For the next reviewer

- R4-1 and R4-3 are both in the UI's two save paths; the backend tests never drive the QML, so a
  `qmllint`/offscreen run of the two dialogs with a two-Trust app and an installed app would have
  caught them. Worth one test that opens `SandboxDialog.openFor(url)` offscreen and presses Save.
- R4-2 changes the Strict launcher's last line; re-run tiers 2 and 3 after it, since the teardown
  shape (and `test_no_launcher_file_descriptors_leak_into_the_app`, which counts the app's fds) is
  what it touches.
- R4-4 is a design decision as much as a fix (regenerate on every start, or stamp and compare);
  either way `_heal_launchers` becomes the one place that keeps installed apps on the current
  launcher, and the docs' "regenerated on each install, update and sandbox-settings change" (17.4)
  gains "and when AppKata's launcher changes".
- The session probe for R4-5 is the first evidence from a real toolkit stack; Electron (Obsidian)
  and a Qt ≥ 6.5 app are what remain, and the Qt-forced oddity (version known, portal dialog still
  not used) is worth a look at `qxdgdesktopportaltheme.cpp` for Qt 6.4 before trusting any Qt claim.

### Round four fixes

All nine items above are fixed, one commit each, on 2026-10-11, in severity order: a8bcd3e (R4-1),
bbdce73 (R4-2), 906e44f (R4-3), 6e75ca7 (R4-4), 242ddee (R4-5), 9d92b1a (R4-6), 5664cf5 (R4-7),
568f1a0 (R4-8), 667f545 (R4-9); e43d2cf recorded the findings first. Each message says what it
changed, which tests it added and which of them fail on the code before it; each **Status** line
above summarises that and names the tests. Two were decisions and are reversible: R4-4 (the
startup pass compares each launcher with today's text rather than stamping a format number;
`launcher_is_current` is the one place to change) and R4-8 (documented and tested rather than
closed, since no namespace shares the network without its abstract sockets). R4-5 corrected a
claim rather than code and left the probe behind as `scripts/test-sandbox.sh filedialogs`.

**Re-run after the fixes** (at 667f545). Tier 1: 283 passed, 63 skipped (the three sandbox files
alone: 137 passed, 57 skipped). Tier 2 (Mint 22.1 container, xdg-desktop-portal 1.20.0, the test
handler registered): 56 passed, 1 skipped. Tier 3 (Ubuntu 24.04 VM, kernel 6.8.0-142, bwrap 0.9.0,
AppArmor profile loaded, the test handler registered): 56 passed, 1 skipped — run after R4-2 alone
(52 / 1) and again after all nine. `filedialogs` (Mint 22.1, GTK 3.24 / 4.14, Qt 6.4): every toolkit
on its own dialog as generated; GTK4 on the portal's only with FileChooser allowed too.

**For the next reviewer** (what this round touched but did not exhaust):
- R4-2 removed the only `exec` in the launcher; `test_no_launcher_file_descriptors_leak_into_the_app`
  still sees fds 0–3 in the app, but a Strict app now has a waiting `sh` as bwrap's parent, as
  Standard always had — worth a glance at `ps` on a real desktop that nothing odd (a terminal's
  job control, a `.desktop` `StartupNotify`) treats the extra process differently.
- R4-4 compares launcher text at every start; on a box with many installed apps that is one
  `build_launcher` each on the startup thread, cheap today, and the comparison also rewrites a
  launcher the user edited by hand (17.4 forbids it, but nothing tells them it happened — a log
  line only).
- R4-5's probe runs four apps × three proxy variants; it does not run Electron itself. Since the
  coverage work, `scripts/test-sandbox.sh consumers` runs Chromium 154 (the same file-dialog code
  Electron ships, `select_file_dialog_linux_portal`) under the three variants and shows the
  Properties denial load-bearing for it — own dialog as generated, *no dialog* with Properties
  allowed, the portal's with FileChooser too — plus a GLib notification with and without the
  capability and a GTK3 link landing on the host. Obsidian itself (an AppImage, in
  `build/sandbox-test/`) remains unrun; nothing in the evidence suggests it would differ.
- R4-9's list is longer again; a reviewer on a desktop not covered here (Xfce's `~/.config/xfce4`
  is under `~/.config`, already refused; LXQt, Budgie) may know further autoload folders.

---

## Coverage after round four

Asked after round four whether the rounds were converging: not on the same bugs (no finding has
recurred; every fix carries a test that fails on the code before it) but on the same *classes* —
each round opened a surface the previous round's point tests did not reach. The classes, and the
commit that now covers each (2026-10-12):

| Class | Findings that fell in it | Coverage commit |
|---|---|---|
| The QML composes what the backend is told; nothing ran the QML | R1, R4-1, R4-3 | f695fbb `tests/test_dialog_contract.py`: the real dialogs offscreen against the real Backend, every state, every button; found 4de6722 on its first run |
| A JS object reaches a `QVariant` slot as a `QJSValue` on PySide 6.9 | installWith and six slots outside sandboxing did nothing when called from QML | 4de6722 `_plain()` in every such slot; `tests/test_qml_slots.py` calls each from QML |
| Readers of a grant set disagreeing for a set no test built | R2-R9, R3-2, R4-1 | 808acf8 `tests/test_sandbox_properties.py`: 137 sets × the launcher, chips, marker, resolver, merge and review lines; 1,623 cases |
| A launcher change visible only as Python | every launcher fix | 81b7d5c `tests/data/launchers/*.sh` goldens, tied to the R4-4 heal pass |
| Mechanism asserted, consumer never run | R3-1, R3-4, R3-6, R4-5 | 66ee89c `scripts/test-sandbox.sh consumers` (GLib notification, GTK3 link, Chromium's chooser) after 242ddee's `filedialogs` |
| State left behind by a transition | R10, R4-7, R1 | a1cfe4e `tests/test_sandbox_transitions.py`: a snapshot of every file and both rows across Off/on, re-save, heal and uninstall |

Each commit's message names the earlier findings it would have caught and shows the fault
re-introduced failing the new test. Coverage measured before this work: `sandbox.py` 94%,
`install.py` 58%, `backend.py` 37% (whole file), the three dialogs 0%; after it the dialogs' sandbox
paths and every QVariant slot are driven from QML. Tiers at a1cfe4e: 1 — 1,944 passed, 63 skipped;
2 — 56 passed, 1 skipped; 3 (Ubuntu 24.04 VM) — 56 passed, 1 skipped; `filedialogs` and
`consumers` as their expected lines say.

## Merge readiness

**Verdict: ready to merge on code and evidence.** What supports it: four review rounds, 24 findings
and 9 earlier-review fixes, each closed in its own commit with a test shown failing before; the
security findings (the real home over the private one, symlinked mount points, the never-shared
list, the narrowed portal name, the Strict table, the `$cwd` rule) all hold in the Mint container
and on a real Ubuntu 24.04 kernel with AppKata's AppArmor profile; the integration claims that
could only be inferred before (file dialogs, notifications, links, Chromium) are now shown with the
real portal and real toolkits; and the test suite now covers the *classes* the findings fell into,
not only the instances. The PR body, the spec (§17), the design doc and this file agree with the
code, and the goldens make any later launcher change a reviewed diff.

**What is not shown, and the owner should weigh before a release** (not before the merge; none is a
code gap):
- **No end-to-end run on a physical desktop.** Every tier is a container or a VM without a display
  server of its own; `local-proxy-test-plan.md`'s field checklist (`scripts/sandbox/field-test.sh`)
  — the `pkexec` AppArmor prompt on Mint 22, GPU acceleration, a tray icon with a real
  StatusNotifierWatcher, PipeWire sound, a self-updating app, Obsidian's own dialogs — has not been
  run on a Mint Cinnamon (X11) or GNOME Wayland machine. This has been "still owed" since the PR's
  first version and is the one item a release should wait for.
- **The QVariant-slot bug (4de6722) implies the non-sandbox UI had not been exercised on PySide
  6.9.3**, which the AppImage build pins: Install, Install options, Add source, Source settings and
  Save review did nothing when driven from QML. They are fixed and now tested from QML, but a
  manual pass over the AppImage build's dialogs is cheap insurance.
- **Six decisions are recorded as reversible** and the owner has not confirmed them beyond the
  reviews: R6 (reviews out when "Follow reviewers" is off), R7 (file arguments through the
  document portal), R3-6 (Notification/Inhibit gated on the capability), R3-2's dialog flip to
  Standard, R4-4's compare-rather-than-stamp, R4-8 documented rather than closed.
- **Deferred by design and stated** (17.18, the Limits, the UI): the Wayland security-context, the
  Landlock layer, the play/record split, a fuller seccomp filter, X11/wlroots capture and
  injection, tray-name collisions, the X11 abstract socket under a network grant.
- **Screenshots** were last regenerated at f94bcfc; since then only hint and footer text changed,
  below the fold of A21/A25 and in the install dialog's change mode, which C11 does not show.
- **Merge mechanics**: 100 commits and 11.6k lines on the branch; this file's intro says it should
  be folded into `docs/app-sandboxing.md` after merge, or kept as the record — the owner's call.
  What must outlive this file is already elsewhere: the tiers and what each shows in
  `app-sandboxing.md` ("Tests, in four tiers"), the claims-and-evidence table there, and the
  release steps — the sandbox tiers to re-run and the per-release state freeze — in `build.md`
  ("Before tagging a release").

---

## Round Five Review

Review of the branch at 6cf30c1 (`app-sandboxing`, everything through the coverage work and the
merge-readiness verdict), 2026-10-12. Line numbers are as of that commit. Nothing here is a
regression of an earlier fix, and none of it changes the merge verdict: one item is a stated v1
safeguard that doesn't fire where it should (R5-1), three are small security-hygiene and
correctness gaps in the same classes earlier rounds closed (R5-2, R5-3, R5-4), two are claims the
evidence doesn't quite support (R5-5, R5-6), and R5-7 is small things. **None is fixed yet**; each
item ends with a fix sketch and the test that would prove it, in the convention of the earlier
rounds. Severity order: 1 → 7.

**What was re-run** (as "For the reviewer of the fixes" describes). Tier 1
(`.venv/bin/python -m pytest -q tests/`): 1,944 passed, 63 skipped. Tier 2 (`scripts/test-sandbox.sh
launcher`, Mint 22.1 container): 56 passed, 1 skipped. Tier 3 (`scripts/test-sandbox.sh launcher-vm`,
Ubuntu 24.04 VM, kernel 6.8, bwrap 0.9.0, AppArmor profile loaded, the test handler registered):
56 passed, 1 skipped. The PR body's "Review fixes" table matches the commits through
a1cfe4e.

**Probes.** Four, none committed; each is described well enough below to become the regression
test named with its fix. Locally: `protected_folder()` over thirty more persistence paths (R5-2)
and `session_warning()` under a sway, COSMIC and Cinnamon-Wayland environment (R5-1). In the tier-2
image (`appkata-sandbox-test2`): a script whose wait line ends exactly on the shell's 8 KiB read
boundary, rewritten in place and by rename while it waits, under dash and bash (R5-3); and a Strict
launcher running the host's `xdg-open` with a fake `/usr/bin/firefox` installed, under four values
of `XDG_CURRENT_DESKTOP` (R5-4). The portal's chooser logic (R5-5) was read from xdg-desktop-portal
1.20.0's `src/open-uri.c`, not run.

### R5-1. The wlroots warning is a name list, so sway from a TTY and every compositor it doesn't name get no warning — MEDIUM (17.9, the one v1 safeguard for the display leak)

**Status: fixed** ("Warn on every Wayland compositor but GNOME's and KDE's, not on a list of leaking
ones"). Decided (owner): the allowlist. `session_warning()` clears only a desktop naming GNOME or
KDE; every other Wayland session warns, naming the compositor from `XDG_CURRENT_DESKTOP` when set
("a wlroots compositor" for the seven known) and "this Wayland compositor" when not. 17.9, 17.17 and
the Limits say it. Test: `test_the_display_leak_warning_clears_only_gnome_and_kde_wayland` (15
cases) and `test_the_warning_is_quiet_with_no_display_and_off_linux` in `tests/test_sandbox.py`;
seven of the cases fail on the previous `sandbox.py`. Tier 1: 1,960 passed, 63 skipped.

**Where:** `session_warning()` (`sandbox.py:546-566`) warns on a Wayland session only when
`XDG_CURRENT_DESKTOP` contains one of seven names (`_WLROOTS`, `:543`: sway, hyprland, wlroots,
river, wayfire, labwc, niri); any other Wayland session returns `{}`, which the UI reads as "GNOME
or KDE, nothing to warn about". 17.9 and the design doc's Limits reason the other way round: only
mutter and kwin are *known* to block screen capture, the clipboard and input injection; the warning
is what v1 ships instead of the security-context protocol.

**Consequence:** sway started from a TTY (the usual way; sway sets no `XDG_CURRENT_DESKTOP` itself
— a display manager exports it from the session file's `DesktopNames`) reports no warning:
Settings → Sandbox and the App Detail caveat say nothing on the one compositor the design doc
confirmed leaks (round 2). The same for COSMIC, Weston, Cinnamon's experimental Wayland session,
and any compositor released after this list. No test exercises `session_warning()` at all (grep
over `tests/`), so the list can't be seen to drift.

**Confirmed** (local, `XDG_SESSION_TYPE=wayland`): with `XDG_CURRENT_DESKTOP` unset → `{}`; set to
`sway` → `wlroots`; `X-Cinnamon` → `{}`; `COSMIC` → `{}`.

**Fix sketch:** invert the rule — a Wayland session is clear only when the desktop names GNOME or
KDE (`gnome`, `ubuntu:gnome`, `gnome-classic`, `kde` all contain the two words), and every other
Wayland session gets the wlroots-style warning, naming the compositor when the variable says it and
"this Wayland compositor" when it doesn't. Keep `_WLROOTS` only for the wording. Test in
`tests/test_sandbox.py`: a matrix over session type × desktop name (x11; wayland + GNOME/KDE →
nothing; wayland + sway/unset/COSMIC → a warning; no session type + `DISPLAY` → x11), with
`monkeypatch.setenv`. The owner may prefer to keep the denylist and accept the miss; then say so in
17.9, since today it reads as if every leaking session warns.

### R5-2. The never-shared list misses Mint's own shell and file-manager hooks, and 17.3.1 claims a Chromium path it doesn't cover — LOW (17.3.1 / 17.3.3, security hygiene; the class of R3 and R4-9)

**Status: fixed** ("Never share the shell's sourced files, Nemo's hooks, Python's user site, nor a
browser's native-messaging folder"). Rows in `_protected_roots()` for `~/.bash_aliases`, `~/.bashrc.d`,
`~/.local/lib`, `~/.local/share/nemo/{scripts,actions}` and `NativeMessagingHosts` under eight
Chromium-family profile folders (named one by one; the profile folders themselves are therefore
refused as folders above one). 17.3.1 and 17.3.3 list them and the Chromium sentence is corrected.
Tests: eleven rows (and three negatives) in `test_protected_folders_are_never_granted`, seven paths in
`test_cli_launcher_protects_the_persistence_dirs_and_the_runtime_folder`, three `where` cases
(`nemo-actions`, `python-site`, `chrome-hosts`) in `test_cli_tool_never_gets_the_home_or_above_or_appkata_areas`
(fail on the previous `sandbox.py` in the tier-2 container), and the `cli-tool` golden regenerated
(the two protected lists gain the paths). Tier 1: 1,974 passed, 66 skipped; tier 2: 59 passed, 1 skipped.

**Where:** `_protected_roots()` (`sandbox.py:226-267`) and `protected_folder()` (`:270-289`), which
refuses a path only when it equals, lies inside, or lies above one of the listed roots.
`protected_folder()` returns "" (allowed) for all of these (local probe):

- `~/.bash_aliases` — Mint 22.1's `/etc/skel/.bashrc` sources it (lines 104–105, verified in the
  `linuxmintd/mint22.1-amd64` image; Ubuntu's skel is the same). The list has `~/.bashrc` and its
  kin; a line appended to this file runs in every new terminal just the same.
- `~/.bashrc.d` — Fedora's skel sources every file in it. `test_protected_folders_are_never_granted`
  (`tests/test_sandbox.py:638`) asserts it *allowed*, as a "prefix match is exact" negative.
- `~/.config/chromium/NativeMessagingHosts`, `~/.config/google-chrome/NativeMessagingHosts` —
  17.3.1 (`requirements.md:2156-2157`) says "Chromium's equivalents are under `~/.config`" beside
  Firefox's refused folder, and round four's R4-9 said the same, as if refused: they are not. The
  rule refuses `~/.config` itself (as a folder above `autostart`) and the children it names; a
  browser's profile folder is neither. A native-messaging host manifest names a program the browser
  starts, as the user, on an extension's request.
- `~/.local/lib` — Python's user site (`~/.local/lib/python3.X/site-packages`): a `.pth` file
  there runs code in every Python the user starts without `-s`, their own scripts and the system's
  Python tools alike. AppKata itself is not affected (`scripts/build-appimage.sh:64` sets
  `PYTHONNOUSERSITE=1`).
- `~/.local/share/nemo/scripts`, `~/.local/share/nemo/actions` — Nemo is Mint's file manager, the
  platform the PR targets; the same class as `nautilus/scripts` and `kio/servicemenus`, which R4-9
  added.

**Fix sketch:** one row each in `_protected_roots()` (for the browsers, the known profile folders:
`chromium`, `google-chrome`, `BraveSoftware/Brave-Browser`, `microsoft-edge`, `vivaldi` — the
matcher takes exact roots, not globs), rows in `test_protected_folders_are_never_granted` (flip the
`~/.bashrc.d` line) and `test_cli_launcher_protects_the_persistence_dirs_and_the_runtime_folder`,
and the lists in 17.3.1 and 17.3.3; correct the Chromium sentence either way.

### R5-3. The launcher is rewritten in place under a running app's shell — LOW (functional, latent; one line to close)

**Status: fixed** ("Write the launcher beside and rename it over, so a running app's shell keeps its
text"). `write_launcher` writes `run.<pid>.tmp`, chmods it and `os.replace`s it, as the marker, the
filter, the helper and the shim already did. Tests:
`test_a_launcher_is_replaced_not_truncated_so_a_running_copy_keeps_its_text` (`tests/test_sandbox.py`;
fails on the previous `sandbox.py`: same inode) and
`test_a_launcher_rewritten_while_the_app_runs_still_tears_down_and_reports_its_status`
(`tests/test_sandbox_run.py`, tier 2: the app sleeps, the launcher is regenerated with other grants,
the app's `exit 7` comes out as 7 and no socket remains; the behavioural guarantee, not shown
failing before since the old fault depends on the read-boundary layout). Tier 1: 1,975 passed, 67 skipped; tier 2: 60 passed, 1 skipped.

**Where:** `write_launcher()` (`sandbox.py:1380-1393`) opens `~/bin/apps/<app>/run` with `"w"`
(`:1390`): it truncates and refills the inode every running launcher has open. Since R4-2 every
running sandboxed app is a waiting `sh` on that file at every level, and that shell has not yet
read its teardown (`kill "$proxy"`, `rm -f "$sock"`, `exit $status`: the last 62 bytes of a Standard
launcher, 13 of a Strict one). The file is rewritten while apps run by Save in the Sandbox dialog
(`setSandbox` → `_regenerate_launcher`, no running check), by Install options for an installed app
(R4-3), by an update, and by the startup heal pass (R4-4) after any AppKata upgrade that changed the
text. The marker, the seccomp filter, the forward helper and the shim are all written to a
temporary file and renamed over (`write_flatpak_info` says why); the launcher is the one writer
that isn't.

**Confirmed** (tier-2 image, dash — Mint's `/bin/sh` — and bash): a script whose wait line ends
exactly at 8192 or 16384 bytes, rewritten with `open(…, "w")` during the wait, ran *nothing* after
the wait — the shell found EOF at its old offset: no teardown, exit 0; the same rewrite by
`os.replace` ran `TEARDOWN-ORIGINAL`, as it should. A rewrite longer than the original would have
the shell execute whatever bytes of the new text sit at the old offset instead. Whether a given
launcher hits this depends on where the shell's 8 KiB read boundary falls relative to its tail:
none of the six goldens does today (checked), but the text's length varies with the app's name,
paths and folder grants, so any installed app can. When hit: the app's exit status is reported as
0 whatever it was (the toast and the App log say it exited cleanly), the socket file is left under
`$rt/appkata/`; the proxy's bwrap dies with the shell regardless (`--die-with-parent`).

**Fix sketch:** write `run.<pid>.tmp`, `chmod 0o755`, `os.replace` — the pattern four other writers
in the file already use. Tests: unit, `write_launcher` twice → the inode changes and a descriptor
opened on the first still reads the first text; run (tier 2), an app that sleeps while its launcher
is regenerated with different grants → the status propagates (`exit 7` → 7) and no `bus-*` socket
remains. `launcher_is_current` and "Show the launch command" read the path, so neither changes.

### R5-4. A Strict app's `xdg-open` is the host's, run inside — LOW (17.4 / 17.6.3, not stated; one of two cheap fixes)

**Status: fixed** ("Put AppKata's xdg-open on a Strict app's PATH too, so it fails plainly instead of
starting a browser inside"). Decided (owner): bind the shim at every level. The shim exits 3 with
"this app runs Strict, with no desktop services, so it can't open … on this computer" when there is
no bus; the launcher binds it and prefixes `PATH` at Strict as well; the dialog's "Desktop services"
row reads off at Strict with a hint that says so; 17.4, 17.6.3 and the Limits say it. The harness
(`register-test-handler.sh`) installs a stand-in `firefox` where the host has none. Tests:
`test_a_strict_apps_xdg_open_fails_plainly_instead_of_starting_a_browser_inside`
(`tests/test_sandbox_run.py`; fails on the previous `sandbox.py` in the tier-2 container — the
desktop's `xdg-open`, exit 0 — and still shows the road the shim shadows by calling `/usr/bin/xdg-open`
directly: the stand-in browser runs inside), the extended
`test_a_sandboxed_app_gets_an_xdg_open_that_asks_the_host` (unit; the shim's Strict message), the
properties invariant and the regenerated `strict-tarball` golden. Tier 1: 1,975 passed, 68 skipped;
tier 2: 61 passed, 1 skipped. Tier 3 failed its first run on this test: the Ubuntu cloud image has
no `xdg-utils`, so the second half (the desktop's own `xdg-open` by full path) now runs only where
`/usr/bin/xdg-open` exists; the re-run passed, 61 / 1 (committed with R5-5/R5-6).

**Where:** the `xdg-open` shim is bound, and put first on `PATH`, only when the level has a bus
(`sandbox.py:1334-1336`, `:1340`). A Strict app finds `/usr/bin/xdg-open` in the bound `/usr`, and
runs it inside the sandbox, where there is no bus, no portal and (since R3-1) no desktop entries.

**Confirmed** (tier-2 image, a fake `/usr/bin/firefox` that leaves a marker in `$HOME`, a Strict
launcher, `xdg-open https://example.com/x`): with `XDG_CURRENT_DESKTOP` `X-Cinnamon` or `GNOME` →
`gio: … OpenURI portal is not available`, exit 4, nothing on screen; with it unset or an unknown
desktop (`fluxbox`) → xdg-open's generic path finds `firefox` on `PATH` and starts it *inside* the
sandbox (the marker in the private home) — a browser with no network and an empty profile, which is
what the user sees when they click a link in a Strict app under such a session. 17.4
(`requirements.md:2212-2213`) says a Strict app "can open only files in its private home" and says
nothing about links; the dialog's "Desktop services (portals)" hint (`SandboxDialog.qml:189-190`)
says "Opening links and files on this computer … always on", which at Strict is untrue.

**Fix sketch:** bind the shim at every level (the `shims` bind and the `PATH` prefix without the
`bus` condition) and have the shim say, when `DBUS_SESSION_BUS_ADDRESS` is unset, "AppKata: this
app runs Strict, with no desktop services, so it can't open links or files on this computer" and
exit 3 — one line on stderr instead of a browser inside the sandbox; and say in 17.4/17.6.3 and the
hint that Strict opens nothing on the host. Tests: the shape in `test_strict_launcher_has_no_bus_no_network`;
the run probe above with the fake `firefox` (no marker, exit 3).

### R5-5. "Asking which program, as for a Flatpak app" overstates the prompt — LOW (17.6.3 / Limits wording; a limit to state)

**Status: fixed** (docs, with R5-6's harness case as the evidence: "Say when the portal asks, show the
real portal opening a file, and have the shim report what the host answered"). 17.6.3 says when the
chooser appears and that a single handler opens at once; 17.17 and the Limits' "Granted is granted" say
a read-write folder is also a road to the host's programs for files the app writes there. Shown, not
only read: in `consumers`, the test handler (the only one for `text/plain`) ran on the host with no
chooser for the shim's and `gio open`'s file alike.

17.6.3 (`requirements.md:2300-2302`) and the Limits (`app-sandboxing.md:866-868`) say a file the shim
hands to the OpenURI portal is opened with a host program "asking which, as for a Flatpak app".
xdg-desktop-portal 1.20.0's `open-uri.c` (read, not run): the app chooser is skipped when the scheme
is http/https/ftp/mailto/webcal/calendar or the target is a directory (`should_use_default_app`),
when exactly one installed application handles the content type (`n_choices == 1`), or when the
user has chosen the same application three times before (`latest_count >= latest_threshold`); it is
shown otherwise, and `ask` forces it. Host and sandboxed callers get the same logic (only the
writable-descriptor check differs, as round four noted). So for a type with one handler on the host
— a `.jar` where a JRE registers `java -jar`, a `.deb` with gdebi — the handler runs on the host at
once, no question asked. With a read-write folder grant the app can write such a file and open it:
a road from "granted folder" to "a host program runs on a file the app wrote". Flatpak has the same
property; "Granted is granted" doesn't say it, and "asking which" says the opposite. **Fix:** word
17.6.3 and the Limits as the portal behaves (asks only when there is more than one candidate and no
settled choice), and add the sentence to "Granted is granted". No code change proposed — a
per-type block would be the portal's job, and the round-four verification already relies on the
portal's own handling of host callers. R5-6's harness case shows the single-handler path.

### R5-6. The real portal's OpenFile has never been run for a host caller — LOW (test gap; the class coverage 4 covered for links, not files)

**Status: fixed, and it found a bug** (same commit). `scripts/sandbox/consumers.py` gained the file cases:
an `online-app` with `~/Documents` granted opens a file there through the shim and through `gio open`
— the real portal (1.20, gtk backend) ran the host's handler on the host path both times, no chooser —
and a file in the private home, which the portal refused (Response code 2). On its first run the
shim reported *success* for that file: `OpenFile` returns a Request at once and the failure comes
later as the Request's Response signal, which the shim never waited for (GLib does; the stand-in had
answered 0 for everything, so no test could see it). The shim now sends a `handle_token`, subscribes
to the Response, waits (up to 120 s, a chooser may be up), and exits 1 with "the host couldn't open …
A file in this app's private home isn't visible outside the sandbox" on code 2, quietly on a cancel.
Test: the stand-in `_FAKE_OPENURI` answers 2 for a file named `refuse…`, and
`test_links_and_files_an_app_opens_go_to_the_host_through_the_portal` asserts the exit and the message
(fails on the previous shim in the tier-2 container: `REFUSED 0`, no message). Expected `consumers`
lines are in "For the reviewer of the fixes". Tier 1: 1,975 passed, 68 skipped; tier 2: 61 passed, 1 skipped.

Every file-opening claim in 17.6.3 — the shim passing a descriptor, the portal resolving it to the
host path, GLib's `gio open` of a file taking the same road — is shown against `_FAKE_OPENURI`
(`tests/test_sandbox_run.py:698-724`), a stand-in that records the path behind the descriptor. The
real portal (1.20) answers a host caller's `OpenURI` in `consumers` (the GTK3 link) and its
`OpenFile` nowhere. `scripts/sandbox/consumers.py` already has what the case needs: the real portal
with its gtk backend on Xvfb, the `text/plain` test handler registered as the only handler, and the
`online-app` launcher. One more case: `xdg-open "$HOME/Documents/note.txt"` from an app with
`~/Documents` granted, and `gio open` of the same file, each asserting the handler's "ran inside:"
marker lands in the *host* home with the host path and no chooser appeared (the single-handler case
of R5-5); and the private-home negative (`xdg-open "$HOME/x"` → the portal's refusal on stderr,
nothing opened), which 17.6.3 states and only the stand-in has seen.

### R5-7. Small things

**Status: fixed** ("Round five's small things: two heal messages, the password toggles' plain hints,
the developer blurb"). The heal pass logs "brought the launcher of … up to today's text" for a
launcher that existed and keeps "now that this system supports it" for one that was missing
(asserted with `caplog` in `test_the_startup_pass_regenerates_a_launcher_an_older_appkata_wrote`);
the dialog gains a "Saved passwords" toggle for the `secrets` capability, whose hint says the
keyring has no per-app walls, and "Password service" warns that the app then holds every other
app's passwords; the `developer` blurb no longer claims an execute lock the others don't have.

- `_heal_launchers` (`backend.py:1952`) logs "sandboxed %s now that this system supports it" for
  every regeneration, R4-4's text catch-ups included: after an AppKata upgrade the App log says
  every installed app was sandboxed "now that this system supports it". Two messages.
- The "Password service" hint (`SandboxDialog.qml:215-217`) doesn't say that owning
  `org.freedesktop.secrets` makes the app the keeper of every other app's passwords; and the
  `secrets` (consume) capability in `CAP_LABELS` (`sandbox.py:36-37`) has no toggle, no template and
  no review line — reachable only through a custom grant set written by hand, where its chip reads
  "Secrets". Either a toggle with a plain hint ("can read every password in your keyring") or drop
  it from the labels until it has a road.
- `TEMPLATE_BLURB["developer"]` (`sandbox.py:110`) "and may run other programs" implies the other
  templates stop that; execute-deny is deferred (17.18; the dialog's Advanced toggle says "Later").
  Drop the phrase or mark it as later.
- `test_protected_folders_are_never_granted` asserts `~/.bashrc.d` allowed (R5-2).

### Verified this round, no change needed

- Tier 1 and tier 2 counts match "Coverage after round four" exactly; tier 3 as above.
- The seccomp filter (`seccomp_filter`, `sandbox.py:769-806`) re-derived by hand against the kernel
  ABI: the four `AUDIT_ARCH` constants, `ioctl`'s number per ABI including the x32 bit, the low word
  of `args[1]` at offset 24 of `seccomp_data`, the relative jump resolution, `SECCOMP_RET_ERRNO|EPERM`.
  It matches what `test_seccomp_filter_refuses_terminal_injection_on_every_abi` interprets and
  `test_terminal_input_injection_stays_blocked` runs.
- The launcher's word order holds for the things that depend on it: `--dir "$rt"` precedes the
  `$rt/doc` and `$rt/bus` binds; the X11 socket bind lands in `"$@"` after `--tmpfs /tmp`; the proxy
  address is set after `--clearenv`; `--die-with-parent` on the proxy's bwrap ties it to the waiting
  shell.
- `_CWD_DECIDE`'s quoting and the three cases (the working directory equal to, above, or inside a
  protected root) re-read with spaces and glob characters in mind; the guard's walk over
  `$HOME`-relative components; the forward helper's visible list excluding refused folders (they are
  stripped before the launcher is built, so a file there is handed over, as 17.6.2 says).
- The six goldens' tails sit clear of the shell's read boundaries, so R5-3 is latent in today's
  shipped texts (a check, not a guarantee: the texts vary per app).
- `open-uri.c` 1.20.0: the host-caller handling round four described (the chooser and content-type
  logic shared with sandboxed callers, the writable-descriptor check relaxed) is as stated; R5-5 is
  the nuance about *when* the chooser appears, not a correction.
- The PR body's "Review fixes" table and "Still owed" paragraph match the commits through a1cfe4e.

### For the next reviewer

- R5-1 is the owner's decision as much as a fix (allowlist mutter/kwin, or keep the name list and
  say so in 17.9); whichever way, `session_warning()` needs its first test.
- R5-3 interacts with R4-4: the heal pass's comparison includes `log_dir()` (so `XDG_STATE_HOME`)
  and `XDG_RUNTIME_DIR`; an AppKata started from an environment that sets either differently from
  the desktop session rewrites every launcher at that start, while apps run, and logs R5-7's line
  for each. Atomic writes make that harmless; a stamp-based comparison (the alternative R4-4
  weighed) would make it not happen.
- `check_not_running` (`install.py:58-64`) is Windows-only: on Linux, "remove a kept version" and
  `_retain` delete a version's folder — and, since this PR, its extracted AppImage cache
  (`_remove_extracted`) — under a running app. Pre-existing for tarballs, not a sandbox regression;
  a Linux implementation would scan `/proc/*/exe` (a bwrap'd process shows the same path, since the
  app folder is bound where it lives — worth confirming before relying on it).
- The inhibit capability allows `org.freedesktop.ScreenSaver` and the portal; Electron's
  `powerSaveBlocker` tries `org.freedesktop.ScreenSaver` and then `org.gnome.SessionManager`, which
  the proxy does not allow. Whether a messenger's "keep awake during a call" works on GNOME is a
  field-test item; the portal road covers GTK and Qt apps.
- R5-2's list follows the pattern of R3 and R4-9: one row and two test rows per path. A reviewer on
  Fedora or Arch may know further shell and desktop hooks (`~/.bashrc.d` is Fedora's).

---

## Coverage after round five

**The habit this file should record.** Five rounds in, every round has found bugs the previous
round's tests could not have found, and each time the useful step was not the fix but stepping back
from the observation to ask what *class* it belongs to and what harness would catch the whole class
— the round-four table above did that for rounds one to four, and the coverage commits that
followed found a real bug (4de6722) on their first run. Round five's items were found by a reviewer
reading, probing and asking "what about the input nobody named"; that is the signal that the
harness has a blind spot, not that the reviewer was thorough. The step back has to be taken every
round, before the fixes, and written down here as a class with its harness, or the next round finds
the same shape again.

**The classes round five's items fall into** (none covered yet; each is one fixture or one
invariant test):

| Class | Findings in it | Harness that would catch it |
|---|---|---|
| **The unknown input.** A list is tested on its members; the policy for a non-member is the safeguard, and it defaults to "allowed" or "clear" | R5-1 (an unlisted compositor is "clear"), R5-2 (an unlisted path is shared); R3 and R4-9 were the same shape | **Covered** ("Derive the protected list's expectation from the platform"): the negative space for the warning is R5-1's matrix (an unheard-of compositor must warn) and for the filter the existing unknown-machine case; for the list, `test_every_file_the_distributions_default_bashrc_sources_is_refused` (`tests/test_sandbox_run.py`, tier 2) parses the host's default shell files (`/etc/skel/.bashrc` and kin) for what they source and asserts each is refused — on Mint it finds `~/.bash_aliases`, and with R5-2 reverted it fails on exactly that; on a host whose skel sources nothing it says so and skips. Tier 1: 1,976 passed, 74 skipped; tier 2: 67 passed, 1 skipped. |
| **AppKata acting while an app runs.** Every run test starts a launcher and waits for it; nothing changes AppKata-side state mid-run | R5-3; also where uninstall, update, switch-to-Off and the heal pass act | **Covered** ("Act on an app while it runs: the writers invariant and the mid-run operations"): `test_every_file_a_running_app_may_hold_open_is_replaced_never_truncated` (`tests/test_sandbox.py`) holds each of the five writers' outputs open across a rewrite and fails on any writer that truncates in place (R5-3 re-introduced: fails); `test_appkata_can_act_on_an_app_while_it_runs_and_the_run_still_ends_cleanly` (`tests/test_sandbox_run.py`, tier 2) runs switch-to-Off, uninstall keeping and removing the home, and the heal pass while the app sleeps, and asserts the app's own status, its output and no socket left. Tier 1: 1,976 passed, 72 skipped; tier 2: 65 passed, 1 skipped. |
| **The Strict counterpart.** Every link, file, portal and notification test runs at Standard; Strict is tested for what it withholds, never for what the app does instead | R5-4 (the fallback into the host's `xdg-open` and browser on `PATH`) | **Covered** ("Try every desktop road from a Strict app"): `test_a_strict_app_fails_fast_on_every_desktop_road_and_never_falls_back_inside` (`tests/test_sandbox_run.py`, tier 2) runs eight roads — `xdg-open` on a link and a file, `gio open` on both, `gio launch` of a desktop entry, the Notification portal, `notify-send`, the secret service — from a Strict app under no known desktop, and asserts each fails within a bound with a line on stderr and that neither the host's handler nor the stand-in browser ran inside. Tier 1: 1,976 passed, 73 skipped; tier 2: 66 passed, 1 skipped. |
| **Doc claims about third parties.** A sentence in the spec describing someone else's behaviour, written from reading source or from a stand-in | R5-5, R5-6, the Chromium sentence in R5-2; R3-1, R3-4, R4-5 earlier | **Covered** ("Mark every third-party claim in the design doc with its evidence"): "Claims and their evidence" in `docs/app-sandboxing.md`, 28 rows over 17.3.1, 17.4, 17.5, 17.6.x, 17.7, 17.8, 17.9 and 17.10, each marked run (which harness, which version), read (which source) or inferred. Seven are inferred or part-inferred today: Qt ≥ 6.5 behind a launcher, a real Qt app's OpenURI road, Electron itself, the camera portal's prompt, kwin's protocol gating, the Xwayland cookie on real desktops, Fedora's `~/.bashrc.d` — the next round's list |

**Categories no round has looked at yet.** Asked after round five what else a reviewer could
find that none of the five rounds' tests reach — not because the code is suspected, but because
the harness has never pointed there:

| Category | Why it is uncovered | Harness |
|---|---|---|
| **State written by yesterday's AppKata.** Rows and files from a previous release: `sandboxPinned` and `sandbox` configs, `rec["launcher"]`, `.identity/`, extracted dirs and their stamps | Every test starts from a fresh database and tree. R4-1's poisoned row and R4-4's stale launcher were both this class; the heal pass covers the launcher text and nothing covers the rest | **Covered** ("Thaw the state a previous AppKata left and live with it"): `tests/test_sandbox_state.py` freezes an installed, reviewed, pinned, sandboxed app — both rows and every file under the home, the home folder as `$HOME` — into `tests/data/state/<label>.json` (`UPDATE_STATE=<label> pytest tests/test_sandbox_state.py`; the first is `pr3-round-five`), and thaws every snapshot into a fresh Backend: App Detail reads it, "Show the launch command" shows it, the heal pass brings the launcher up to today's text at most once, Strict / Off / back-to-theirs all work, uninstall leaves only the home. One snapshot per release from now on; the test runs over all of them |
| **Adversarial strings at the trust boundaries.** Review lines (`Sandbox folders`, from a Trust), argv (from a file manager, a URL handler, `%U`), file names, app names | The property corpus (coverage 2) is 137 *well-formed* sets; the run tests use one spaced path. The forward helper and `eval "set -- $fwd"` run on the host over caller-supplied strings; `parse_folders` runs over remote text | **Covered, and it found a gap** ("Feed hostile strings to every boundary of the launcher"): `tests/test_sandbox_adversarial.py` — 24 hostile folder paths (spaces, quotes, newlines, globs, `--`, `%`, 200 characters…) each bound whole as one pair or refused, with the launcher still valid shell; `parse_folders` keeps each whole; the forward helper hands every hostile argument back byte-for-byte through the launcher's own `eval`, and keeps option-like file names; 15 hostile app names give a valid launcher and bus name. The gap: a newline in an app's *name* or in a *refused* path landed unquoted in a launcher comment, and the rest ran as shell at every launch — shown with a stub `bwrap` (`INJECTED` printed). No input can carry a newline today (a Markdown line, a GitHub name), so a hardening, not a finding: comment text is flattened now, and `test_text_from_outside_never_becomes_a_line_of_the_launcher` fails without it. Tier 1: 2,021 passed, 74 skipped. |
| **A degraded host.** Each external dependency absent, slow, or dying mid-run | The tiers assume a healthy host. Covered so far: no session bus (R4), no document portal, no `python3-gi`, no `/dev/dri`. Not covered: `$XDG_RUNTIME_DIR` missing, disk full during extraction, the document portal hanging, the proxy dying after the socket appeared, an AppImage whose runtime has no `--appimage-extract`, `flock` absent | **Covered, and it found two silent exits** ("Stall or remove one dependency at a time"): four tier-2 tests — a runtime folder that can't be created (the launcher said only `mkdir: cannot create directory`; it now says which folder and that a logged-in session is needed), a document portal that never answers (the helper's timeout, the arguments pass through, the app runs: under 30 s), the proxy killed mid-run (the app's later bus call fails at once, its status comes out, no socket left), and an AppImage whose runtime exits without unpacking (the launcher exited 1 with *nothing* on stderr, the runtime's complaint discarded; it now says the runtime couldn't unpack it and cleans the staging folder). Disk full and a missing `flock` stay uncovered (root to simulate, and `flock` is in util-linux everywhere). Tier 1: 2,033 passed, 78 skipped; tier 2: 71 passed, 1 skipped. |
| **Stand-ins with a real counterpart available.** `_FAKE_OPENURI`, the listening socket in `test_wayland_display_reaches_the_app`, the `mknod` camera, the stand-in notification daemon, `_Bus` | Each stand-in was the right first step; the real thing now exists in an image: the round-2 `session` image has sway, mutter and PipeWire, `consumers` has the real portal | **Covered for the display and the sound** ("Run the generated launcher under sway and PipeWire"): `scripts/test-sandbox.sh wayland` (`scripts/sandbox/wayland.py`, the session image): a GTK3 app behind an `online-app` launcher maps a window on headless sway (`GdkWaylandWindow`, seen in sway's tree); `pw-play` behind the same launcher plays a tone that PipeWire counts as a stream from a client with `pipewire.access = flatpak` and `app_id = io.appkata.player` (17.8's claim, now run behind a generated launcher); `offline-editor` has no socket ("Host is down"); and the play-only app records 385 KB from the same sockets, which 17.8 states. The real portal's `OpenFile` is R5-6's case. Still stand-ins: mutter (the image has it; not driven), the camera node, the notification daemon in `consumers` |
| **The version matrix of the external tools.** bwrap, xdg-dbus-proxy, xdg-desktop-portal, GLib, GTK | Tier 2 and 3 pin one of each (bwrap 0.9, portal 1.20, GLib 2.80). The branch's own round-1 probes ran on Mint 21.3 (bwrap 0.6.1, portal 1.14), and 17.1 states no minimum bwrap; `test_sandbox_run.py` skips below 0.5 | **Covered** ("Run the launcher tests on Mint 21.3 as well"): `scripts/test-sandbox.sh launcher-21`, a Mint 21.3 image with the same packages — bwrap 0.6.1, xdg-desktop-portal 1.14.4, GLib 2.72.4: 67 passed, 1 skipped, the same as tier 2 on 22.1 — and 17.1 now states the minimum (bwrap 0.5) and the two ends the tests run on. GTK and Qt stay pinned to the `filedialogs` image's versions |
| **Every mutation leaves its audit entry and toast.** 17.16 says every sandbox change is audited | R4-3 found a path that didn't; the transitions test snapshots the two rows but not the audit table | **Covered** ("Audit every sandbox mutation, as a table and in the snapshot"): `tests/test_sandbox_audit.py` drives eight slots (the four `setSandbox` shapes, `keepSandbox`, Install options with and without a sandbox, uninstall) and asserts exactly the rows 17.16 names; the system setup is audited only once `install_profile` succeeded; and the transitions snapshot now carries the audit table, so the earlier transition tests say which operations record what. Toasts stay with the dialog contract test. Tier 1: 2,033 passed, 78 skipped. |
| **AppKata's own threads.** The startup thread (heal, probe) and the UI thread share the database and the settings rows | `_heal_launchers` rewrites launchers and rows while the first `sandboxInfo` may be running; nothing tests the overlap | **Covered, and it found a race** ("Overlap the heal pass with the UI thread"): `tests/test_sandbox_threads.py` runs the startup pass forty times on a thread under sixty rounds of `sandboxInfo` / `setSandbox` / `keepSandbox` on the test thread. On its first run the two raced in `install._activate` on the stable link (`File exists: '1.0' -> …/current`) and on the marker's per-process temporary name; the loser logged "couldn't regenerate the launcher" and skipped it, leaving the launcher on disk behind the row. `_activate` is serialized behind a lock now; the test asserts no such warning, the last choice in the row, and at most one reconciliation by the heal pass. Tier 1: 2,033 passed, 78 skipped. |

All seven are built (2026-10-12, the commits after cbb7860), and three of them found something on
their first run — the point of the exercise: the adversarial strings found comment text that a
newline would turn into shell (hardened), the degraded host found two silent exits (said now), and
the threads found a race between the heal pass and a sandbox change (serialized). Tiers after all of
it: 1 — 2,034 passed, 79 skipped; 2 — 71 / 1; 3 — 71 / 1.

**For the next reviewer**, what the harnesses leave: `wayland.py` drives sway, not mutter (the image
has it); disk-full and a missing `flock` are not simulated; the camera node and the `consumers`
notification daemon are still stand-ins; the claims table's seven inferred rows; and the first frozen
state is this branch's own — the harness earns its keep from the first release after it.

---

## Round Six Review

Review of the branch at 9572629 (`app-sandboxing`, after round five and its harnesses), 2026-10-12,
over the areas the end of round five named as the next cycle: two apps at once, harnesses nobody
asserts, UI text as claims, what the field test still owes that can move indoors, and the leftovers
(mutter, disk-full, the remaining stand-ins, the claims table's inferred rows). Line numbers are as
of 9572629. **Findings first, as before**; each has a Status line once fixed, and "Coverage after
round six" at the end records the harnesses. Two findings, one MEDIUM; the rest of the cycle is
harness work.

**Probes.** Locally: a Backend with two installed apps named "Notes" from two Sources (R6-1); the
hint and text strings of the three dialogs listed and checked one by one against the code and the
claims table (R6-2). In the tier-2 image: `Camera.AccessCamera`, `Camera.IsCameraPresent` and the
`IsCameraPresent` property called from an app *with* the camera grant and one without (R6-2). A
Fedora 40 image's `/etc/skel/.bashrc` (the claims table's `~/.bashrc.d` row, now run).

### R6-1. Two apps with the same name share one folder, one launcher, one identity and one private home — MEDIUM (functional and security; the "two apps" class)

**Status: fixed** ("Give each install its own id, so two apps with one name share nothing").
`install.new_app_id` picks `slug`, `slug-2`, `-3`… against the other installs' ids at a fresh install,
`install()` records it as `rec["id"]` and keeps it across updates, and `install.app_id_of(rec, app)`
(the id, else the name's slug for a record from before) is what the folder, launcher, entry, command
link, identity, private home, startup comparison, uninstall and `sandboxInfo` use; the backend's
`_app_id(url)` reads it. 17.6 says the identity is unique per install. Tests:
`tests/test_sandbox_two_apps.py` — two "Notes" from two Sources get `notes` and `notes-2`, their own
launcher with their own program and grants, entries, identities and homes; uninstalling one leaves
the other whole (snapshot over both); a record without an id keys on the slug. On the old code the
first test fails on `'notes' == 'notes-2'` and the launcher is one file. Tier 1: 2,037 passed, 79 skipped; tier 2: 71 passed, 1 skipped.

**Where:** everything about an installed app is keyed on `slug(app["name"])`: the install folder
(`install.py:614`, `:629`: `os.path.join(portable.root, app_id)`), the download folder (`:549`),
the launcher path, the identity marker and the private home (`_sandbox_launcher`, `:375`;
`sandbox.launcher_path`, `identity_path`, `sandbox_home`), the desktop entry and command link
(`_activate`, `:338`), the startup comparison (`launcher_is_current`, `:414`) and the uninstall
(`:785-787`); `sandboxInfo`'s "home" too (`backend.py`). Nothing makes the slug unique among
installs: two Sources can each carry a "Notes", and a user can install both.

**Consequence** (confirmed, local, two URLs named "Notes", A chosen Strict and B Online app): both
records point at the *same* launcher file; A's launcher now runs B's program folder (`appdir=…/notes/2.0`)
with B's grants (a proxy, the network) while App Detail says A is Strict and active; there is one
desktop entry, one command link, one `io.appkata.notes` identity, one private home — B reads
and writes A's data, and the document portal's per-app view is shared. Uninstalling B removed
A's launcher, identity marker and private home while A stayed installed. The folder collision is
older than this PR (`install()` always used `root/<slug>`); the launcher, identity and home make
it a sandbox finding: the private home is the one promise Strict makes.

**Fix sketch:** give each install its own id, chosen once and recorded: `slug(name)` unless
another install already holds it, then `<slug>-2`, `-3`…; store it as `rec["id"]`, read it
everywhere `slug(app["name"])` is used today (a helper `app_id_of(rec, app)` with the slug as the
fallback for records written before this, which the frozen-state test covers), and say in 17.6 that
the identity is unique per install. Tests: a backend test with two same-named apps asserting
distinct launchers, entries, identities and homes and that uninstalling one leaves the other whole;
a transitions-style snapshot over both.

### R6-2. "Without this an app can still ask through the camera portal, which asks you first" — the portal is denied; nothing asks — LOW (17.8, the Camera hint; a claim the proxy narrowed away in finding 0)

**Status: fixed** ("Say that an app without the camera grant has no camera at all"): the hint, 17.8 and
the launcher comment say it; the claims table row is *run*; the host-caller run test calls
`Camera.AccessCamera` and `Camera.IsCameraPresent` from an `online-app`, an `offline-editor` and a
`messenger` (the grant) and asserts the proxy's denial for each. Tier 2: 71 passed, 1 skipped.

**Where:** the Camera toggle's hint (`SandboxDialog.qml:200`), 17.8 (`requirements.md:2343`), the
launcher comment (`sandbox.py:1372`) and the claims table's "inferred" row. Since finding 0 the
proxy allows only `PORTAL_INTERFACES` on the portal name, and Camera is deliberately not among
them (17.5: for a host caller it hands over devices without the sandbox's consent).

**Confirmed** (tier 2, xdg-desktop-portal 1.20 on the bus): `Camera.AccessCamera`,
`Camera.IsCameraPresent` and the `IsCameraPresent` property all get the proxy's `AccessDenied`,
from an app with the camera grant and from one without. Nothing asks the user anything: without the
grant the app has no camera at all, which is the safer direction but not what the hint and the spec
promise, and the claims table carried it as inferred — the one row of the seven that could be run
in a minute.

**Fix sketch:** say it: the hint "The camera devices themselves. Without this the app has no camera;
the camera portal is not open to sandboxed apps", the same in 17.8 and the launcher comment; the
claims table row becomes *run*; add the three Camera calls to
`test_the_portals_answer_a_sandboxed_app_as_a_host_caller` so the denial is asserted both ways.

### R6-3. A tray icon has no owned name once its AppRun forked before starting it — LOW (functional; found by the field test moved indoors)

**Status: fixed** ("Own a tray item's name for the pids an AppRun's forks leave it with"): `_TRAY_OWNS`
covers pids 2–6 (the `messenger-camera` and `developer-every-capability` goldens show the words).
Test: `test_a_tray_icon_registers_with_a_watcher_which_can_talk_back_to_it` (`tests/test_sandbox_run.py`,
tier 2): the watcher stand-in registers both shapes of app and reads each item's title back through
the proxy; an app without the capability reaches no watcher. On the previous `sandbox.py` the forked
case times out registering. Tier 1: 2,039 passed, 84 skipped; tier 2: 76 passed, 1 skipped (both with the whole of round six's run tests).

**Where:** `_TRAY_OWNS` (`sandbox.py:678`) owns `org.kde.StatusNotifierItem-<pid>-<n>` for pids 2 and 3
only: the program exec'd straight (pid 2 in bwrap's namespace) or run as its AppRun's child (3).
An AppRun that forks anything first — a command substitution computing a path, a `which` — pushes
the real program's pid higher, and the item name it derives from its pid is then not an owned
name: xdg-dbus-proxy refuses the `RequestName`, the watcher is told a name nobody owns, and the
desktop's host can't call back into the item. The round-two tray test only ever checked that the
app could *own* a name, with the app exec'd straight.

**Confirmed** (tier 2, a StatusNotifierWatcher stand-in on the test bus that registers the item
and then reads its `Title` back through the proxy): `exec python3 item.py` registers as `-2-1` and
the watcher reads the title; `d=$(dirname "$0"); python3 "$d/item.py"` registers as `-4-1`, which the
proxy never let the app own, and the watcher's call back fails.

**Fix sketch:** own the names for pids 2–6 (fifteen `--own` words instead of six; the collision
between two tray apps, 17.17, is unchanged), and say in the launcher comment why. Test: the watcher
stand-in with both shapes of app, asserting the registration and the title read back for each.

### R6-4. On GTK 4.18 a GTK4 app behind the generated launcher has no file dialog at all — MEDIUM (functional; found by running the claims table's "Qt ≥ 6.5" row)

**Status: fixed** ("Tell GTK4 not to ask the portal for its file dialog, since GTK 4.18 shows none when
refused"). The launcher sets `GDK_DEBUG=no-portals` after `--clearenv`, at every level (`GTK_USE_PORTAL=0`
was tried first and changed nothing: a marked process asks regardless). Shown on both images with
`filedialogs`: GTK4 its own dialog with *no* portal calls as generated, on 4.14 and on 4.18; the new
"portals on, FileChooser allowed" variant (the flag removed) is the only road left to the portal's
dialog; GTK3 and Qt unchanged. `consumers` gains a GTK4 link (`GtkUriLauncher`): with GTK's portal
road off it goes through GLib, which asks the OpenURI portal when no handler is in view, and the
host handler ran. 17.4, 17.6.3, the recipe, the test plan's launcher shape and the claims table say
it, with the cost (GTK4's print and colour dialogs are the in-sandbox ones). Unit test:
`test_standard_launcher_binds_the_apps_document_portal_view` asserts the word after `--clearenv`,
at Strict too; six goldens gain the line. `filedialogs` and `filedialogs-qt68`: `EXPECTED: ok` (16 lines each); `consumers`: `EXPECTED: ok` (12 lines). Tier 1: 2,039 passed, 84 skipped; tier 2: 76
passed, 1 skipped.

**Where:** 17.6.3 says GTK4 "calls [the FileChooser portal] outright and falls back to its own dialog
when refused", shown on GTK 4.14 (Mint 22.1, round four R4-5). The launcher relies on that fallback:
it binds `/.flatpak-info` (GTK4 reads it and so takes the portal road), denies the portal, and sets no
`GTK_USE_PORTAL` (`sandbox.py`, the comment above the `DBUS_SESSION_BUS_ADDRESS` word).

**Confirmed** (`scripts/test-sandbox.sh filedialogs-qt68`, Ubuntu 25.04: GTK 4.18, Qt 6.8.3, portal
1.20, the same harness as round four): GTK4 as generated → `Properties.GetAll`, `FileChooser.OpenFile`
(denied) → **no dialog**; the same with Properties allowed; the portal's dialog only with FileChooser
allowed too. GTK3 3.24 and Qt 6.8 show their own dialog in every variant (Qt 6.8 does read the
marker and probes `version`, as 17.6.3 says, and keeps its own dialog even when the portal is
allowed). So on any distribution shipping GTK 4.18 or later — Ubuntu 25.04, Fedora 42, the next
Mint — a GTK4 app sandboxed by AppKata cannot open or save a file through its dialog.

**Fix sketch:** tell GTK not to ask instead of relying on its fallback: `--setenv GTK_USE_PORTAL 0`
after `--clearenv`. GTK3 and GTK4 both read the variable before the marker (`gdk_should_use_portal`),
and it is GTK's alone: GLib's roads (links through OpenURI when no handler is in view, notifications
through the portal) read `/.flatpak-info` and are unchanged. Shown with the harness's new
"GTK_USE_PORTAL=0" variant on both images (below); then the launcher word, the goldens, 17.6.3,
the Limits, the claims table (GTK4 and Qt rows now *run* on two versions each), the unit test that
asserted the variable was not set, and `filedialogs`' expected verdicts.

### Verified this round, no change needed

- Every other hint in the Sandbox dialog states something a test shows: the sound hints (the
  `wayland` harness records from a play-only app), the X11 hint (R4-8's test), the tray collision
  (documented), the password hints (R5-7), Strict's (R5-4), the Landlock rows say "Later".
- The claims table's `~/.bashrc.d` row: Fedora 40's `/etc/skel/.bashrc` lines 18–19 source
  `~/.bashrc.d/*` — now run, not read.

### Round six fixes

All four items are fixed, one commit each, on 2026-10-12: 04eae96 (R6-1), 86847ef (R6-2),
f287c44 (R6-3), 09626af (R6-4); ff317ff recorded the first two findings. Each message says what changed, which
tests it added and which fail on the code before it; the Status lines above summarise that.

---

## Coverage after round six

The round was run over the areas the end of round five named, and the habit held: four findings,
two of them (R6-3, R6-4) found *by* building a harness and one of those a MEDIUM, and the harness
for every area, one commit each. The table:

| Area | What was built | Found |
|---|---|---|
| **Two apps at once** | `tests/test_sandbox_two_apps.py`: two same-named apps from two Sources, their own everything, uninstall of one leaves the other (a snapshot over both) | R6-1 (MEDIUM): one slug, one folder, launcher, identity and private home for both |
| **Harnesses nobody asserts** | `consumers.py`, `filedialogs.py`, `wayland.py` carry their expected verdicts, print `EXPECTED: ok` or the mismatches, exit 1 on any (9963a63) | — (all ok on their first asserted run) |
| **UI text as claims** | "UI text and its evidence" in `app-sandboxing.md`, one row per hint; `tests/test_sandbox_ui_claims.py` fails on a hint without a row or a row without a hint (afed587) | R6-2 (LOW): the camera hint and 17.8 promised a portal that is denied |
| **The field test, moved indoors** | tier 2: a self-updating app with and without the writable grant, a self-updating AppImage (its unpacked copy changes, the `.AppImage` never), a tray item against a StatusNotifierWatcher stand-in that calls back into the item (2e20036, f287c44) | R6-3 (LOW): a tray item's name was owned for pids 2 and 3 only; an AppRun that forks first left the icon without a name |
| **Leftovers** | disk-full (a 1 MB tmpfs the tier-2 harness mounts; 2e20036); mutter in the `wayland` harness (a GTK3 window maps under headless mutter too); Qt 6.8 and GTK 4.18 behind a generated launcher (`filedialogs-qt68`, Ubuntu 25.04); the claims table's Fedora, camera, Qt ≥ 6.5 and GTK4 rows are *run* | R6-4 (MEDIUM): GTK 4.18 shows no file dialog when the portal is denied — the "Qt ≥ 6.5" row, run, found a GTK finding |

Tiers at the end of round six: 1 — 2,039 passed, 84 skipped; 2 (Mint 22.1) — 76 passed, 1
skipped; 3 (Ubuntu 24.04 VM, AppArmor profile loaded) — 75 passed, 2 skipped; `consumers`, `filedialogs`, `filedialogs-qt68`, `wayland` — `EXPECTED: ok`.

**What round six leaves** (the next cycle's list, shorter than round five's): the claims table's
remaining inferred rows — a real Qt app's own OpenURI road, Electron itself (Obsidian) rather than
Chromium, kwin's protocol gating, the Xwayland cookie on real desktops — and the UI table's three
(MPRIS against a media-key daemon, the direct ScreenSaver name, the password service against a
client); a missing `flock`; the camera node and the `consumers` notification daemon as stand-ins;
and the physical-desktop checklist, now down to the pkexec prompt, GPU acceleration and Obsidian's
own dialogs — the three that need hardware.

---

## Round Seven Review

Review at c5a0c77 (after round six), 2026-10-12, over what round six left: the claims table's
inferred rows (a real Qt app's link road, Electron, kwin's protocol gating, the Xwayland cookie),
the UI table's three inferred rows, a missing `flock`, the two stand-ins, and the physical-desktop
checklist's items that can move indoors. Probed before anything was fixed; one finding, a security
claim that turned out false on one of the two desktops the design calls clear.

**Probes.** A kwin container (`kwin_wayland --virtual`, kwin 5.27.11, Mint 22.1's KDE packages) and
the round-2 session image (sway and headless mutter): a sandboxed `online-app` listing the Wayland
globals it is offered, reading the clipboard with `wl-paste`, and sending an unauthenticated X11
connection setup to every abstract X socket in the shared network namespace. Tier 2: stand-in
daemons and clients on the other end of the MPRIS, ScreenSaver and Secret Service names.

### R7-1. On KDE Wayland a sandboxed app reads the clipboard: kwin offers `zwlr_data_control` to every client — MEDIUM (17.9, the warning's allowlist; a claim that was read, not run)

**Status: fixed** ("Warn on KDE Wayland about the clipboard: kwin offers the clipboard-manager protocol
to every client"). The allowlist is GNOME alone; a KDE Wayland session gets "an app can still read and
change the clipboard (KWin offers the clipboard-manager protocol to every program)" with the screen
and keystrokes named as protected; the other-compositor text says only GNOME is known to block all
three. 17.9, 17.17, the Limits and the claims table say it. Tests: the matrix
(`test_the_display_leak_warning_clears_only_gnome_wayland`, the KDE case flipped and its text
asserted). Harnesses: `scripts/test-sandbox.sh kwin` (`kwin.py`: the globals kwin offers a sandboxed
app — `zwlr_data_control` yes, screencast/fake-input/virtual-keyboard no — and `wl-paste` reading
the host's clipboard; "EXPECTED: ok"), and `wayland` gains the clipboard under sway (LEAKED) and
mutter (BLOCKED) and the Xwayland cookie under both. Tier 1: 2,039 passed, 88 skipped.

**Where:** 17.9 and the design doc's Limits say GNOME/mutter *and KDE/kwin* block screen capture,
the clipboard and input injection, and R5-1 made the session warning clear a Wayland session whose
desktop names GNOME or KDE (`_CLEAR`, `sandbox.py`). The kwin half was read from source (the claims
table: *read*), never run.

**Confirmed** (kwin 5.27.11 under `--virtual`): the globals kwin advertises to an ordinary client
include `zwlr_data_control_manager_v1`, the clipboard-manager protocol, while `zkde_screencast`,
`org_kde_kwin_fake_input` and the other trusted-only interfaces are hidden from it (kwin's global
filter). From inside a generated `online-app` launcher, `wl-paste` printed the text a host client
had copied. Under sway the same (expected: 17.9 says so, and sway advertises screencopy and the
virtual keyboard as well — and, new since wlroots 0.17, `wp_security_context_manager_v1`, the
deferred fix of 17.18). Under mutter none of the five is advertised and `wl-paste` falls to the
ordinary selection, which needs keyboard focus: nothing leaks.

**Consequence:** on KDE Wayland the sandbox does not protect the clipboard — a sandboxed app reads
(and can set) whatever the user copies, passwords included — while Settings → Sandbox and App
Detail show no warning, the one thing v1 promises for a leaking session. Capture and injection *are*
blocked by kwin; the warning text should say which. Whether kwin 6.x filters data-control for
clients without a security context is not known here (Plasma 6 is not in these images); the safe
reading is to warn until shown otherwise.

**Fix sketch:** the allowlist becomes GNOME alone; a KDE Wayland session gets a warning that names
the clipboard ("an app can still read and change the clipboard; the screen and your keystrokes are
protected"); 17.9, the Limits, the claims table (kwin: *run*, leaks the clipboard) say so; the
matrix test gains the KDE cases. Harness: a `kwin` mode (the container above) and a clipboard
case in `wayland` for sway and mutter, each asserting what its compositor gives a sandboxed
client.

### Verified this round, no change needed

- The Xwayland cookie (17.9, R4-8), now run: an unauthenticated X11 connection over the abstract
  socket from a sandboxed app with the network grant is accepted by sway's Xwayland (no `-auth`)
  and refused by mutter's (`-auth`, "Authorization required"). kwin's Xwayland could not be started
  under `--virtual` here (its Xwayland aborts without a GPU); kwin's `-auth` stays *read*.
- The three UI-table rows and `flock`: run (the commit before this record).

### Round seven fixes

R7-1 is fixed in 42e1933; 7ef036b ran the last inferred link claim (Qt) on two Qt versions and put
dunst where the stand-in daemon was; 8936e48 put a daemon or a client on the other end of the three
UI rows and lost `flock`.

---

## Coverage after round seven

| Area | What was built | Found |
|---|---|---|
| **kwin** | `scripts/test-sandbox.sh kwin` (`kwin.py`): the globals kwin 5.27 offers a sandboxed app and `wl-paste` reading the host's clipboard | R7-1 (MEDIUM): KDE Wayland leaks the clipboard; the warning now says so and clears GNOME alone |
| **The Xwayland cookie and the clipboard under sway and mutter** | two cases in `wayland` (sway accepts an unauthenticated X connection and gives up the clipboard; mutter refuses both) | — (17.9 as stated) |
| **Qt's link road** | `consumers` (Qt 6.4) and `filedialogs-qt68` (Qt 6.8): `QDesktopServices.openUrl` lands on the host | — |
| **The UI table's inferred rows** | tier 2: a media-key daemon, a ScreenSaver stand-in, a Secret Service client | — |
| **Stand-ins** | dunst as the notification daemon in `consumers`; a missing `flock` | — |
| **Electron** | Obsidian's own AppImage behind a generated launcher in `consumers`: unpacked by the launcher, started, its window mapped (asserted); its file dialog needs a click on its start screen and stays the field's — Chromium 154's dialog code is the same | — |
| **GPU** | `test_the_gpu_renders_inside_the_sandbox_where_the_host_has_one` (tier 3, the VM's virtio GPU, `eglinfo` on the device platform): the app names the host's renderer, not a software fallback — 80 passed, 2 skipped in the VM | — |
| **The tables stay honest** | `tests/test_sandbox_claims_table.py`: every claim row names run/read/inferred, and the rows still inferred must equal the list in the test | — |

What round seven leaves: kwin 6.x and the Ubuntu 25.04 corner of the launcher tier (round eight,
below), Obsidian's dialog (a click away; the field's), the pkexec prompt (the field's), and the
camera node.

---

## Round Eight

Run in the same session, over what round seven left and the classes rounds six and seven pointed
at: a claim that was *read* is a finding until run (GTK 4.18, kwin), and the version matrix has a
newest corner the tiers never visited.

| Area | What was built | Found |
|---|---|---|
| **kwin 6** | the `kwin` mode takes `kwin6` (Ubuntu 25.04, kwin 6.3.4): the same answer as 5.27 — `zwlr_data_control` offered, the clipboard read, screencast and fake input hidden — and `wp_security_context_manager_v1` advertised, as sway's is | the claims table's last inferred compositor row is *run*; 17.18 now puts the security-context protocol first, since both leaking compositors advertise it |
| **The newest corner** | `launcher-25` (Ubuntu 25.04: bwrap 0.11, portal 1.20, GLib 2.84, Python 3.13): 80 passed, 2 skipped | one test's assertion read a word out of Python 3.13's richer traceback (fixed: a line, not a substring); the launcher needed nothing |
| **The tables stay honest** | `tests/test_sandbox_claims_table.py`: every claim row names run/read/inferred; the rows still inferred must equal the list in the test (one left: Electron's own dialog); every UI-table row names a test or a harness — it caught one row that said "the same" | — |

**Considered, no change:** the summary chips say nothing about the X11 grant (on in every template:
"the X11 fallback is the default, not worth a chip"). Silence is a claim only where it implies
protection; the chips describe grants, the dialog's toggle and hint say what X11 gives, and the
session warning covers the display. Left as designed.

Tiers at the end of round eight: 1 — 2,042 passed, 89 skipped; 2 (Mint 22.1) — 76 / 1; 2b (Mint 21.3) — 67 / 1 at
db671ff; 2c (Ubuntu 25.04) — 80 / 2; 3 (Ubuntu 24.04 VM) — 80 / 2; `consumers`, `filedialogs`,
`filedialogs-qt68`, `wayland`, `kwin`, `kwin6` — `EXPECTED: ok`.

---

## Round Nine

Stepping back from rounds six to eight: every backend test composes an install record by hand
(`_tarball_install`, the frozen state, the two-apps fixture), and every run test writes a launcher
with `write_launcher` directly. The product's own path — `install.install()` with a real archive,
`launch()`, an update, a rollback, `uninstall()` — had never been driven under bwrap. One harness:

| Area | What was built | Found |
|---|---|---|
| **The real install path** | `test_a_real_install_update_rollback_and_uninstall_run_sandboxed_end_to_end` (tier 2): a local HTTP server serves two tarballs; `install.install` (Strict), `launch` (the log shows the app's line, the private home, no real file), an update to 2.0 (the kept 1.0, the launcher current), `switch_to` back to 1.0, `remove_version`, `uninstall` removing the home — and afterwards no launcher, entry, link, marker or home | — (passed on its first run) |

Tiers at the end of round nine: 1 — 2,042 passed, 90 skipped; 2 (Mint 22.1) — 81 passed, 2 skipped (no render node, no video node here); 3 (Ubuntu 24.04 VM, AppArmor profile loaded, the virtio GPU rendering) — 81 passed, 2 skipped.

---

## Confidence: what the sandbox delivers, what it says it doesn't, and what is still owed

Asked at the end of these rounds what it takes to be confident that app sandboxing delivers what
it can and never claims what it can't. Three things, all now in place and each kept by a test:

1. **Every promise has evidence at a named level.** The spec's third-party claims
   (`app-sandboxing.md`, "Claims and their evidence": 28 rows) and the dialog's hints ("UI text and
   its evidence": 15 rows) each say *run* (which harness, which versions), *read* (which source)
   or *inferred*. `tests/test_sandbox_claims_table.py` fails when a row lacks the word or an
   inferred row is not in its list; `tests/test_sandbox_ui_claims.py` fails when a hint has no row.
   Rounds six to eight showed why: three *read* claims were false when run (GTK 4.18's dialog,
   kwin's clipboard, the camera portal), one of them a MEDIUM. Today one row is inferred (Electron's
   own file dialog, Chromium's code run in its place).
2. **The silent surfaces say the same as the loud ones.** The session warning's rule is an
   allowlist (GNOME alone), so a compositor nobody has tested is warned about, not trusted; the
   summary chips are generated from the same grant set the launcher bakes (the property corpus,
   1,623 cases); a Strict app is told, in words, what it can't do (R5-4); the launcher's own
   refusals are reported wherever the app was started from.
3. **The harness reaches what the product does, on the platforms it names.** The launcher tier on
   Mint 21.3, Mint 22.1, Ubuntu 24.04 (a real kernel with the AppArmor profile) and Ubuntu 25.04;
   real toolkits (GTK 3.24, GTK 4.14 and 4.18, Qt 6.4 and 6.8, Chromium 154, Obsidian), the real
   portal (1.14 and 1.20), real compositors (sway, mutter, kwin 5.27 and 6.3), real PipeWire, a
   real notification daemon; the product's own install path end to end; a frozen state per
   release; hostile strings at every boundary; a dependency stalled or removed at a time; two apps
   at once; AppKata acting while an app runs.

**What it delivers, shown:** a private home and a read-only install folder at both levels; no
network, no bus and no desktop services at Strict; a bus filtered to the portals safe for a host
caller and the granted capabilities at Standard, each capability shown both roads; files handed
over through the document portal and the app's own dialog on every toolkit tested; the identity
PipeWire and GLib act on; the camera devices with the grant and no camera without; launchers kept
current across upgrades and regenerated safely while apps run; nothing left behind by any
transition; every change audited.

**What it says it does not deliver, and shows:** on X11 and on every Wayland compositor but
GNOME's, the screen, the clipboard and keystrokes (on KDE the clipboard alone) — the warning is
the deliverable, and the harnesses show the leak and the warning; play-only sound (the app records
too); the X11 abstract socket under a network grant; tray-name collisions; the Landlock layer and
the fuller seccomp filter (deferred, the toggles say "Later"); a read-write folder as a road to
the host's programs.

**What is still owed** before "high confidence" is the plain truth rather than "high confidence
on everything a container can show":
- the **pkexec prompt** on a real Mint 22 desktop (the one piece that needs a polkit agent and a
  graphical session; the VM shows the profile works once loaded);
- **NVIDIA's device nodes** (17.18; no such hardware here) and a real GPU beyond virtio;
- **Obsidian's own file dialog** (a click on its start screen; Chromium's dialog code is run in
  its place);
- the **Wayland security-context** protocol, now advertised by sway and kwin 6 — the next
  release's first item, since it turns the KDE and wlroots warnings into protection;
- a **release** to freeze state from, so the upgrade harness has a real yesterday.

The method that got here, and that the next session should keep: after each round, write the
class and the harness before the fixes; run every claim that was only read; and let the tables'
tests refuse a new claim without evidence.
