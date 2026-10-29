# Current checkpoint — browse availability, 2026-10-29

Objective: restore reliable, fast operator/customer browsing during background work,
with qualification, security, provenance and canonical design preserved.

Branch: `fix/browse-availability-20261029`; base
`37cc949b4c230851c88f4181966b888a26e1f037`; dedicated worktree
`.worktrees/browse-availability-20261029`. Existing dirty `gl3` is outside scope.

Authority: [AGENTS](../AGENTS.md), [autonomous canon](../docs/product/AUTONOMOUS_INTELLIGENCE_CANON.md),
[results canon](../docs/product/PROJECT_FIRST_RESULTS_CANON.md), [finish contract](FINISH_CONTRACT.md).
[READY graph](WORK_GRAPH.md), [bounded packet](packets/BROWSE-AVAILABILITY-20261029.md)
and [evidence report](../docs/validation/browse-availability-repair-20261029.md) record scope and acceptance.

Four Luna/low lanes delivered availability, SQL performance, frontend behavior and
source diagnosis. Root Astra independently reviewed the actual integrated slices;
no material code finding remains, conditional on final gates and live acceptance.

Implemented: scoped identity/entity/company-membership invalidation with conservative
fallback; 15-minute rollover preparation; UTC recovery integrity; one-pass group
counts; All query reuse; transaction-local search JIT control; safe bounded browse
cache and navigation; debounced/canceled searches; accurate loading/terminal states;
menu fixes and separate latest-check/schedule-health labels.

Static, migration/drift, dependency and canonical brand gates pass. Focused checks:
34 availability/recovery/rollover, 7 membership follow-up, 3 SQL, 13 Austin; corrected
app-schema auth/origin rerun 8/8. Full browser passed 156/156 before a diagnostics
copy-only clarification, which passed its focused check; exact final browser rerun
is completing. Two prior backend full runs failed from controller test-environment
setup and one manually canceled slow native query; failed receipts are retained.
Final backend full run follows the frozen membership change and migrated app schema.
Only owned loopback PostgreSQL 18.6 databases on port55441 are used for local tests.

Production still observed at37cc949b/schema0048; no implementation-lane production
write, paid provider activation, ingestion replay or retained-data deletion occurred.
Baseline HTTPS16 samples: median1206.8ms/p95=1648.2ms. Read-only candidate timings
improve All/DC; Oil & Gas603–696ms remains above the500ms warm target.

Next: candidate commit/draft PR and final gates, root release/rebuild, then authenticated
live desktop/mobile journeys, exact-image percentiles and actual update-window
availability. Production deployment and live acceptance remain pending. RRC MFT
endpoint timeouts and exact well-research failure stage remain external/unknown.
