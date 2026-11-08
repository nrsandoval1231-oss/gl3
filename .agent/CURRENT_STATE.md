# PR187 review repairs - November 8, 2026

Owner requested review of [PR187](https://github.com/nrsandoval1231-oss/gl3/pull/187), review of comments, validation and merge when ready. This supersedes the original draft-only delivery restriction for this PR. No deployment, paid provider execution, production mutation or credential changes are authorized.

The account-first implementation and original acceptance remain documented in the [Slice 1 record](../docs/engineering/account-first-slice-20261107.md) and [original receipt](../docs/validation/account-first-20261107/README.md). The prior checkpoint is retained [unchanged](archive/PR187-REVIEW-20261108/CURRENT_STATE-before-review.md).

Review repairs preserve historical alias-connected Pursuit privacy across list/detail/mutation responses, account child relevance/sort order, and selected project context across header navigation. Account membership is revalidated before restored account contacts become actionable. Persisted data is not rewritten. No schema change is added.

Focused validation and independent review passed: 53 changed-file backend integration tests, desktop/mobile delayed-membership regressions, repeated header roundtrips, browser Back/Forward, reload and restoration of 48 loaded projects. A mutation probe disabling order preservation makes the crossed-ranking regression fail as intended. The [review receipt](../docs/validation/pr187-review-20261108.md) gives scope, commands and limits.

Full local and exact-head CI passed on review candidate `caa2a15`; the receipt records exact counts. The subsequent CodeRabbit review identified a restored-alias-chain availability error and two documentation inconsistencies. Saved Pursuit lists, detail and exact retries now remain available without trusting unknown alias membership; filtered lookups and new ambiguous creates fail explicitly. Seven new real regressions failed before the repair and now pass. Historical privacy remains fail-closed.

The review-comment repairs passed all 63 Pursuit/alias integration tests in both implementation and independent runs. Independent follow-up source/test/documentation review passed without blockers. Next: pass full latest-head CI, check for new material comments, then merge only when all blocking findings and required checks are clear. The PR's current checks and merge record are authoritative after this dated checkpoint. No production validation or deployment is claimed.
