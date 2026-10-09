# A5B group expansion scope repair

## Change

`toggleGroup()` now binds an expansion to the current view, browse cohort and page, cohort token, stable group ID, and latest expansion intent. It checks that binding after every group-page response and before changing member data, expansion state, or the error banner. Scope-changing navigation and exact-record selection invalidate pending expansion work. Clicking the same pending group cancels it; starting a different group makes the newer request authoritative.

No API, schema, migration, qualification, grouping-policy, or client changes were made. Existing server-provided group identity and bounded group-page behavior remain in use.

## Reproduction and focused proof

The delayed second-page regression was run once against the exact base `App.tsx` blob `60f2176a3ccbbaccaa9f151e391dc68e773e7e0b`. It failed because a stale expansion restored `.project-members` after an activity-filter change. The guarded source was restored in a PowerShell `finally` block and its SHA256 matched before and after (`950639946198a83460f3790cd933d43b7b1052c9766c5db8589588e27467d027`). The old-base log and unique Playwright trace remain in ignored `.artifacts`.

New browser coverage checks delayed successful group pages across an activity change; delayed stale errors after a newer group opens; a current request error; same-key reclick/collapse; selected-record navigation; tier, search, Signal decision, offset, and view changes; and Back/forward refresh that rotates the cohort token while an old expansion is pending. The page-request fixtures assert the old and new cohort tokens and the group request's captured token.

## Validation

The final focused run used synthetic authentication, blank provider keys, disabled automatic research/worker flags, no candidate `.env`, and only the assigned disposable A5B databases. It ran all `web/tests/project_cards.spec.ts` browser tests (32 passed) on the final source and test files. `npm run typecheck`, `npm run build`, and `git diff --check` passed. Exact logs, Playwright result/trace hashes, and the guarded-source backup hash are in `RAW-MANIFEST.json`; files remain outside Git under ignored `.artifacts`.

The root-owned full A5B gates and independent review are pending. This is an implementation handoff, not an A5B acceptance claim.

## Preserved failed attempts

Early focused runs failed on test-only issues and were retained: duplicate route registration in the transition matrix, tier-case fixture selection, ambiguous nested row/member selectors, and a derived-heading expectation. One matrix assertion also targeted a view control after it had left the rendered page; the test now checks the resulting URL state. The first typecheck/build attempt exposed a TypeScript closure-narrowing issue in the token fixture and was corrected by storing request URLs in an array. The final focused run, typecheck, and build pass.

Two PowerShell command-construction mistakes stopped before test or application startup; their console text was not saved to a raw file and is explicitly recorded as unavailable in the completion receipt. No provider or retained data was accessed.
