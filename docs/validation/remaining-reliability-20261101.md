# Remaining reliability repair — November 1, 2026

Baseline: main `9d3aedffea7b411a53d3b80bbf4a7c56c46f77dc` after PR163. This receipt describes a repository candidate, not deployed behavior.

## Changes

- RRC flare collection uses existing durable recent/history progress rows. Recent overlap remains three days; initial history begins 90 days back and advances at most seven days per segment. Count/byte/page limits remain enforced. Failed acquisition cannot advance completion, and evidence persistence precedes cursor advancement. The existing worker continuation budget applies. Source day is America/Chicago across progress and retrieval.
- Demand summary reads current saved browse identities/sector metadata and revalidates current equipment packages. Candidate count is bounded; over-budget cohorts return unavailable instead of a partial total. Physical-asset overlaps are excluded conservatively. Unknown/conflicted demand never becomes numeric MW. Documented/calculated/estimated values remain separate.
- Default grouped browsing displays the bounded additional-equipment KPI. Sector changes and refresh update it; session clearing aborts pending work and removes values. Periodic refresh bounds displayed staleness. The KPI explicitly is not total portfolio demand.

## Validation

Local frontend typecheck/build and focused checks are being run on the candidate. An initial broad unit run recorded 2,298 passes, two skips, 28 failures and 31 setup errors; this is not a passing suite. The environment lacks a usable PostgreSQL process and httpx initially lacked the runtime proxy's optional SOCKS transport. No repository dependency or test guard was weakened. Browser installation returned a truncated/non-ZIP download. GitHub CI with disposable PostgreSQL and browser installation remains the required complete validation environment.

Independent review found and prompted corrections to PostgreSQL query shape, source-backed sector/physical identity, Texas-local calendar handling, default-view mounting and KPI expiry. Final exact-candidate review is pending.

## Remaining limitations

- Flare submissions before the initial 90-day history boundary are not claimed complete. Completed historical submission intervals are not continuously revisited for later status changes.
- RRC drilling current/prior-month acquisition does not establish arbitrary historical correction coverage. Replaying older snapshots without amendment ordering could regress retained evidence; no unsafe replay was added.
- The summary measures supported additional equipment input, not every facility's total power demand. Unsupported/conflicted cohorts remain unavailable or excluded, with counts.
- Production is unchanged. No production SSH execution capability is present in this workspace. Current images/schema, backup/restore/rollback, real source freshness and authenticated canary performance remain unverified.
