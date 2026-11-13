# GL3 repository audit — November 13, 2026

## Scope and authority

Owner requested a full repository audit and validation/merging of ready changes. This audit covers the open PR graph, dependency advisories, backend/browser gates, identity/privacy/provenance boundaries and integration readiness. It does not certify every possible defect or authorize production deployment, provider calls or retained-data mutation.

Original checkout: `C:/Users/nrsan/Nucleus/02_Projects/GridLens/gl3`, local main `bc433650`, with pre-existing untracked worktree directories. Preserved unchanged. Audit checkout: `C:/Users/nrsan/.codex/worktrees/gl3-full-audit/gl3`. Initial remote main: `5ee2f30c`.

## Confirmed findings

1. Main locks Soup Sieve 2.10. GitHub reports three open dependency advisories: GHSA-6655-6qjp-jx7x (high), GHSA-7g44-g9rc-x53w (medium), GHSA-mmhr-3c5m-f64f (high). PR200 pins 4.0 and raises Python floor to 3.11.5. Fresh locked pip-audit and npm audit report no known vulnerabilities on the candidate.
2. Legacy flat browse passes far-future expiry to a browser timer. A 2099 fixture overflows the timer limit, immediately expires results and repeatedly detaches navigation controls. Isolated fix from 916ab6c5 ported as 373cc21b; regression added.
3. Canonical account/child browse has the same unbounded expiry timers in ProjectResults.tsx. The first repair leaves 18 browser failures; both account effects require bounded rearming and actual-expiry controls. Repair in progress. No passing browser claim yet.
4. PR201 cohort test can select a deliberately conflicting project when UUID ordering puts it second. Deterministic adverse-order reproduction fails with the original StopIteration. Fixture correction preserves all 22 original assertions and adds one. Focused test passes three repeats; entire customer-results module 14/14; updated integration suite 27/27. Final candidate 563439cb is pushed; CI pending.
5. PR204 company roster publication bypasses global person suppression when no person identity is attached. Independent source/helper probe confirmed the linked contact is removed while the equivalent role remains. Real-database regression/repair in progress.
6. PR204 ranks company roster snapshots only among currently eligible projects. Losing the project carrying a newer withdrawal can resurrect an older positive roster from a surviving project. Regression/repair in progress.
7. PR199 commercial acceptance remains unmet: sparse retained-source coverage, low extraction recall, unverified current contacts/usefulness, adverse latency/payload samples and unresolved ingestion timeout. Passing code checks do not establish those outcomes. PR189 conflicts and is selectively superseded by the later workspace work; merging it wholesale would ignore that reconciliation.

## Merges completed

- PR195 architecture audit/contract merged to main: `5426032432ec5594f8f9d61e03f848cc19cb0d88`. Independent Astra source review, exact-head green CI, fresh integrated documentation check.
- PR205 reference-context overlay merged into PR199 integration branch: `2bf6157157724915ae6b77031a4d505e4ee7ae99`. Independent exact-byte builder check, seven integrity tests, source-context review and green CI. Does not change runtime/scoring.
- PR202 source-dated revision relevance merged into PR199 integration branch: `26344b8bef10c9f2a55bd4959651317077a4b434`. Independent source review and green exact-head CI. Final combined integration gates remain required.

## Current validation

Security parent `a5e11666`, including main/PR195: full local backend `pytest backend/tests -q -n 4` passed 5,350 tests, 3 skipped, 7 subtests, 22 warnings in 1,310.28 seconds. Disposable loopback PostgreSQL 18.6 only. The original brief-map failure did not reproduce in four isolated parameters, the entire 48-case module, this full suite or both refreshed CI backend jobs; its initiating cause remains unclassified. No freshness assertion was weakened.

Local gates passed: locked installation, dependency audits, Ruff and format, configured backend mypy (266 source files), documentation graph (113 documents / 541 targets / 18 anchors), frontend typecheck/build, migration upgrade through 0056 and drift check, API/worker imports. An initial mypy invocation from repository root missed backend configuration and reported four stub errors; the canonical backend-directory invocation passed without dependency/code changes.

Browser evidence is explicit: initial 335-case run had 300 passed / 35 failed; after legacy-only timer repair, 336 cases had 318 passed / 18 failed. These failures are preserved in `security-browser.txt` and `security-browser-repaired.txt`; neither is acceptance.

## Pending and boundaries

PR200 must pass repaired full browser checks, final exact-head CI and independent final review before main merge. PR201/203/204 target PR199's integration branch and need updated combined checks. PR196/198 are earlier review slices, not independent alternatives to the evaluated PR199 candidate. Do not merge commercial runtime to main until its explicit material acceptance blockers are addressed.

No deployment, production schema/data operation, credential change, paid-provider execution or branch history rewriting occurred.
