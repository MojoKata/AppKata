# Relay progress: CR1's unit U05, the sandbox: what may be granted, and file arguments

5 batches cover the unit's 17 findings, taken from `docs/remediation/CR1-schedule.json` at
`upstream/master` 6c3d380: batch 1 the system places refused to every grant and to a tool's working
directory; batch 2 the file-argument helper; batch 3 where a grant's path really leads; batch 4 the
places of the home the never-shared and secret lists miss; batch 5 what an uninstall leaves.
One agent at a time; the coordinator checks each batch before the next starts, and pushes.
This branch is stacked on U04's (`cr1-u04-downloads-checksums`): it started at U04's relay commit
b912a42, and each batch first merges U04's pushed tip in.
