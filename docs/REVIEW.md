# Code review

AppKata's own part of a code review: its commands, names and cases. The method (the stages, the
pieces and their briefs, the claim kinds, confirmation, the owner's questions and the filing) is the
shared `review` skill, [`agents/skills/review/SKILL.md`](../agents/skills/review/SKILL.md), and
nothing here restates it. The filing script's config is [`review.json`](review.json).

## Requirements and their ids

Requirement ids are R… ([`requirements/`](requirements/README.md)), architecture ids A…
([`architecture/`](architecture/README.md)). Code cites the item it builds in a comment or a string,
as "(R17.10)", and [`scripts/doccheck.py`](../scripts/doccheck.py) checks that every id cited names
an item.

## Document groups

| Group | Documents |
|---|---|
| `docs-1-apps` | [`requirements/README.md`](requirements/README.md), R1 to R9, [`screenshots/README.md`](../screenshots/README.md) (the mockups' text) |
| `docs-2-trust-platform` | R10 to R16, [`AppKata.md`](AppKata.md) |
| `docs-3-sandbox` | R17 ([`requirements/R17-app-sandboxing/`](requirements/R17-app-sandboxing/README.md)), [`architecture/`](architecture/README.md) (A1, A2), [`requirements-trace.md`](requirements-trace.md) |
| `docs-4-process` | [`README.md`](../README.md), [`DEVELOP.md`](../DEVELOP.md), [`build.md`](build.md), [`testing.md`](testing.md), [`RELEASE.md`](RELEASE.md), [`RELEASE_AGENT.md`](RELEASE_AGENT.md), [`github-workflows.md`](github-workflows.md), [`gpg.md`](gpg.md), [`local-proxy-test-plan.md`](local-proxy-test-plan.md), [`GENESIS.md`](GENESIS.md) |

Each group also reads the open `gap` and `question` issues on its sections. `docs/reviews/` and
`docs/releases/` are records of their day, and no group reads them.

AppKata has no glossary. Terms are checked against the requirements' own definitions: a term is set
in bold where it is defined, most of them in R2. A term used without a definition is a Doc Review
claim.

## Areas

The areas are the 12 of [`scripts/areas.py`](../scripts/areas.py), the same as the `area:` labels,
in its order; `python3 scripts/areas.py` prints them. A finding on a document is in `docs`, and one
on the tooling in `tooling`.

For the review only, two areas hold more than `scripts/areas.py` lists (its lists, which coverage and
the tests' durations use, stay as they are):

- `scripts` also holds `scripts/*.sh` and `scripts/sandbox/*.sh`. The map cuts it into two units:
    build and release; tests and tour.
- `tooling` holds `.github/workflows/`, `packaging/`, `.coworker/` and the test tooling
    (`tests/conftest.py`, `tests/parts.py`, `tests/durations/`), read against
    [`github-workflows.md`](github-workflows.md), [`build.md`](build.md) and
    [`testing.md`](testing.md).

## Sensitive code

Read whole whenever any of it changed:

| Code | What depends on it |
|---|---|
| `src/appkata_core/` `trustfile`, `gitsig`, `sshsig`, `scoring` | trust verdicts |
| `src/appkata_core/` `http`, `urls` | tokens and links |
| `src/appkata_core/` `install`, `assets`, `selfinstall`, `autoupdate`, `transfer` | what is downloaded, checked and run; AppKata replacing itself; imports that add Trusts |
| `src/appkata_core/` `windows` | elevation |
| `src/appkata_core/` `sandbox`, `dbus`; `scripts/sandbox/exposure.py` | what a sandboxed app reaches |
| `src/appkata_core/` `nostr` | it parses untrusted relay input |
| `scripts/publish.sh`, `scripts/build-*.sh` | the release signing key and what a release holds |
| `.github/workflows/` | CI's secrets and the signing environment |

## The mechanical check

```
python3 scripts/doccheck.py > review/<N>/checks.txt
```

It reports ids cited that name nothing, issue links that aren't their issue, each index's sections
against the files, section files too long or ids numbered twice, and words and dates a statement
doesn't carry; its header says which of those fail the run.

## Commands

A claim may reproduce with:

- one test: `.venv/bin/pytest tests/<file>::<test>`;
- tier 1 in its container, the release's Python and PySide6: `scripts/test-tier1.sh -k <test name>`
    (it collects the whole suite and runs the tests named), which takes over a minute, so an attended
    review asks first;
- CI's artifacts of the latest `master` run: the coverage report, the tour and the mutation baseline.

A review never starts `scripts/test-sandbox.sh launcher-vm`, `test-windows-vm.sh`,
`test-desktop-vm.sh`, `test-appimage.sh`, `test-channels.sh`, `test-clock.sh`, `test-layout.sh`,
`test-mutate.sh` or `mutate.py`, `build-appimage.sh`, `build-windows.sh`, `publish.sh` or
`repo-admin.sh` (all in `scripts/`).

An unattended run of a command over a minute is capped at 10 minutes.

## Earlier reviews

The reviews in `docs/reviews/` were made by another method, and a review doesn't read them: the first
review by this method has no delta and no earlier findings.

## Settled records

- [`A1.12-decisions.md`](architecture/A1-app-sandboxing/A1.12-decisions.md);
- the open `gap`, `question` and `future` issues, and the issues closed as not planned.

Won't do is `wontfix`, later is `future` (agreed, with no time set) and a gap is `gap`. AppKata keeps
no rejected-ideas file.

## Claim kinds and severity

AppKata adds no claim kinds. A wrong trust verdict is at least Med: the user shown an app as
reviewed, signed, verified or sandboxed when the code didn't establish it, or the reverse.

## Branch and labels

The target branch is `master`. The labels are the skills' defaults: `question` is a question issue,
`refine` a finding that waits on the owner's decision, and `dismiss` a finding the work showed to be
no defect (`wontfix` stays what it was: a real defect that won't be fixed). `review.json` sets no
`labels` and no `kind_prefix`: an issue carries only the labels the skill gives it, and a finding's
kind is in its body only.

## After a review

What follows a review is the shared `review-triage` skill's,
[`agents/skills/review-triage/SKILL.md`](../agents/skills/review-triage/SKILL.md): the findings
sorted, batched into work units and scheduled, and the schedule run. `review.json` sets none of its
fields, so its defaults hold: a sweep's schedule is `docs/remediation/<sweep>-schedule.json`, a unit
holds at most 20 findings, at most 3 units are open at once, and a file that 3 or more units change
is listed in the schedule as shared, so those units need not run one after another. The hardening
page shows a finding that waits on the owner (`refine`, `dismiss`, or a question issue below a step)
apart from the open ones.
