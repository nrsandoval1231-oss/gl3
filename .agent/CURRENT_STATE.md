# Current checkpoint — released and synchronized, October 29, 2026

GridLens runs on DigitalOcean at https://app.grid-lens.com/ independently of the
owner's Windows device. PR147 is merged and deployed. The application release is
main `4376f4d1`, deployed from tree-equivalent source `e153cefd`, schema0049.
Subsequent documentation-only commits do not change that deployed application.

The [final release evidence](../docs/validation/browse-availability-repair-20261029.md)
records completed gates, dated live verification and remaining limits. Final local
backend: 3308 passed/2 skipped/7 subtests; browser: 158 passed; source CI40894911298
passed. Independent source review found no unresolved material findings.
Authenticated desktop/tablet/mobile journeys passed. No tests or live probes were
rerun solely for the documentation synchronization.

Remaining: Oil filtering and atomic group open miss their speed targets; actual
live read/update overlap and midnight rollover are unverified; RRC acquisition
failures remain external/unknown. These are follow-up limits, not completed work.
No production changes or paid-provider activation are authorized by this checkpoint.

## Local repository organization

Both `GridLens/gl3` and `GitHub/gl3` main checkouts were synchronized with origin/main
on October29. Thirteen secondary worktrees were archived intact under the owner-local
`GridLens/archive/repo-cleanup-20261029/`; its cleanup record maps former paths.
Seventeen merged local branches were removed after verified Git bundles were created.
Unmerged branches, ignored files, deployment evidence and backups were retained.

Optional Windows launcher/loopback-auth work is preserved locally on
`preserve/local-launcher-auth-20261029` (`f4077bf5`); it is not required for hosted
use and is not queued for merge. Recovery notes are on
`preserve/recovery-notes-20261029` (`3fe00aa6`). Old worktree locations and dirty-main
statements in candidate receipts are historical.

The [repair packet](packets/BROWSE-AVAILABILITY-20261029.md) preserves implementation
history. Next work should start from current main and the owner-approved canons.
