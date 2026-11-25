# Relay progress: CR1's unit U04, downloads, checksums and what App Detail says of them

4 batches cover the unit's 15 findings, taken from `docs/remediation/CR1-schedule.json` at
`upstream/master` 6c3d380: batch 1 the High finding and what a release's version and an app's name
may be as a part of a path; batch 2 the installed file's SHA-256 and what App Detail and the review
dialog say of it; batch 3 what Verified means and the file an administrator's command installs;
batch 4 download() and the checksum fetch.
One agent at a time; the coordinator checks each batch before the next starts, and pushes.
U05 is stacked on this branch and merges its pushed tip in before each of its batches.
