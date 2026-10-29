# Current checkpoint — PR148 released, October 29, 2026

GridLens runs at https://app.grid-lens.com/ independently of the owner's Windows
PC. PR148 merged and deployed application source `ca12443f5c57f3502584d8a353d83cdf7d5372b1`.
Schema remains 0049/74 tables. Final release verification passed at 23:18 UTC
(6:18 pm America/Chicago); API, worker, browse and web run the exact candidate
images with zero restarts, readiness READY and external HTTPS 200.

The [production release receipt](../docs/validation/canonical-ui-release-20261029.md)
records source/main tree equivalence, green source CI, fresh backup and isolated
74-table restore, independent review, 38 authenticated API reads and actual Chrome
desktop/tablet/mobile checks. All shows 1,896 real projects including Signals;
retained phone/email displays preserve source dates and authority uncertainty.
Both canaries passed before workers resumed; protected settings, effective
environments and closed paid-provider gates were preserved. No migration,
production database restore, credential change or outbound outreach occurred.

Application source CI: 169 browser tests and 3,309 backend tests passed, one skipped.
Release/documentation commits after the application SHA do not imply a different
deployed application. The candidate history below is dated and superseded.

Remaining: source-backed contact coverage/deliverability and buyer authority are
incomplete; absent KPI/Follow/completion APIs remain explicit; page filters and
sorting are page-local. Oil/group-open latency, long-duration update overlap,
midnight rollover and existing external-source failures remain follow-up limits.
Do not infer new paid-provider or data-replacement authority from this record.

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

## Historical canonical UI candidate checkpoint — superseded by release above

The owner-requested canonical screenshot implementation is on
`feat/canonical-reference-ui-20261029`, source `d41d4e17`. It is not merged or
deployed; the released production revision above remains unchanged. Local checks:
168 browser regressions; 3309 backend tests passed/1 skipped/7 subtests; build,
types, audits, migration compatibility and protected brand assets passed. The
[candidate receipt](../docs/validation/canonical-reference-ui-20261029.md) records
visual evidence, API limitations and the separate live-acceptance boundary.
