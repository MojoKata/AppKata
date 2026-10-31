# Follow-ups after the CI work: the field test's runs on GitHub

The walk thru of 2026-10-30, item 4, decided **B**: `publish.sh setup` makes the `field-test`
label and `check` reads it back (with a GENESIS.md row); an issue template for a release's issue;
`field-test.sh --issue-body`; and `publish.sh field-test VERSION`, which opens the release's issue
and one sub-issue per environment with its checklist. Pointing the docs at the first tracking issue
waits for the first release.

## Results

| Pass | When | What it found | Where fixed | Tiers at the end |
|---|---|---|---|---|

## F1. The field test's runs have nowhere to go — LOW (process; testing.md, 2026-10-24) — fixed

`docs/testing.md` ("Tracking the runs on GitHub") planned a tracking issue per release and a
sub-issue per environment, and waited for the repository to be published. It has been since
2026-10-25.

**The class:** one list kept in several places by hand: the plan's questions, the script's, and
now each environment's checklist. E11 (`tests/test_field_test_plan.py`, review 3) already held the
plan to the script; the checklists would have been a third copy.

**The harness:**

- The questions are one list, `scripts/sandbox/fieldtest_questions.py`: `fieldtest.py` asks them,
  `field-test.sh --issue-body ENVIRONMENT` prints a checklist of them, and E11 reads them.
- `test_each_environments_checklist_is_what_the_field_test_asks_there`: each environment's boxes are
  the questions asked there, the A1 ones only where testing.md's table says the setup is needed,
  and the GPU box; the environments are that table's.
- `test_the_release_issues_template_names_the_same_environments`, for the template.
- `test_field_test_opens_the_release_issue_and_one_under_it_per_environment` and
  `..._opens_nothing_without_the_label_or_twice` (`tests/test_publish.py`) run `publish.sh
  field-test` against a `gh` that records each call.

Found while moving the questions: `test-sandbox.sh launcher-vm` copies a fixed list of the field
test's files into its VM, which the new module had to join (the same kind of list the Windows tier
had, W2 in [`followups-windows-test-python.md`](followups-windows-test-python.md)).

**The fix:** as decided. `field-test` refuses without the label (`setup` makes it) and when the
version has field-test issues already.

## Fixes

| Commit | Fixes | What | Proof |
|---|---|---|---|
