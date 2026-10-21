# Opportunity intelligence release and acceptance record

**Current implementation candidate:** [`6befa72`](https://github.com/nrsandoval1231-oss/gl3/commit/6befa723c156b11ddb838a4ec8fd9f41485bf51b). **Status: implementation integrated; final release gates pending.** This record does not authorize merge, production changes, paid activation, or deployment. The concise evidence packet is [ACCEPTANCE.md](../../.agent/artifacts/PR102-FINISH/ACCEPTANCE.md).

## Implemented behavior

The existing horizontal Pursuit Workspace renders the authenticated opportunity-intelligence aggregate with cited project/customer facts, current research gaps, evidence, and next actions. Reads are bounded and provider/job-free. Project-scoped buying-chain corrections retain reason and history, use optimistic versions/idempotency, and return stale-version feedback. F3C composes sparse patches, supersedes identity links on subject changes, removes old same-kind methods when replacements are unverified/uncited, and permits review against current evidence after stale correction history. Operator-reported methods are not call/email actions. Identity auto-linking is limited to current cited, entity-bound valid LEI/US EIN; attributed project-scoped review preserves history.

The row-based power-schedule editor records attributed demand phases and supply entries through draft, accept, correct, retract, and history. The card separates scenarios from the current qualified gap and retains supply source kind, ready date/basis, suitability, source reference, and reporter attribution. Only explicit utility-grid entries are presented as reported energization. Snapshot fingerprints and schedule-independent research hashing preserve prior semantics.

## Current proof and open gates

The baseline isolated retained copy contains **1,620 projects, 1,620 needs, 18,016 evidence rows**. The curated manifest [`pr102-retained-manifest.json`](pr102-retained-manifest.json) contains **14 reviewed cases and 79 fields**. The read-only retained-v5-f5 report for source candidate `69c19f8` reports **79/79 exact field matches, zero populated expected-null values, and exact equality with the independent original expected fields**. This is field-level comparison only, not category or release acceptance.

The offline ten-category runner remains **BLOCKED** because three required categories are absent: site-specific utility constraint, conflicting power dates, and legitimate bridge-power potential. A read-only scan of all 1,620 existing needs and 1,622 linked current evidence found none of those categories. Do not relabel or infer missing positives. Persisted runtime/restart and production-latency proof remain pending. Live provider acceptance and actual inference cost remain UNKNOWN/BLOCKED pending separate credentials, source permissions, budget, and owner authorization.

Controller focused receipts report 60 F5 backend tests passed and 46 F3C/backend integration tests passed in 59.54 seconds on `6befa72` (`.artifacts/pr102/controller-f5-tests.json`, `.artifacts/pr102/controller-f3c-final-focused.json`). These focused runs do not replace final whole-pipeline checks, runtime proof, or independent review; those gates remain pending. No production/provider action was performed.

## Bounded corpus-extension recovery

F6C is **PARTIAL_FAILED_BOUND**, not acceptance. It completed 11 GETs (six direct collector plus five worker retrievals). A construction-timeout acquisition occurred before the five worker returns; whether its HTTP request was sent or completed is UNKNOWN. This exceeded the six-request ceiling. Activity was confined to a local copy and yielded +33 observations/+34 evidence, but projects/needs stayed 1,620/1,620, there were zero new candidate Need IDs, and LogicalCalls stayed at 10. No paid inference was recorded. Five collector snapshots were later overwritten by worker snapshots; earlier hashes remain but original raw bodies were not preserved. Five offline replays were individually stable for observations/evidence/projects/needs/calls, while the helper aggregate reported an incorrect terminal status. A read-only scan found no missing-category cases. This attempt is not evidence of acceptance. Raw failure material remains outside Git. Cause is UNKNOWN; locks have cleared, so no current external-resource block is asserted. Do not repeat the unchanged retrieval route.

## Schema and operational constraints

Migrations `0035_reconciled_identity` then `0036_buying_chain_corrections` are required before deploying integrated code. For any separately authorized rollout, validate a restored isolated database, apply migrations through head (`uv run alembic upgrade head` from `backend`), verify revision, then deploy the exact accepted app. Rollback may restore a compatible prior application while retaining additive tables/history; do not downgrade/drop schema or clear jobs, receipts, ledger reservations, or history.

`OPPORTUNITY_ENRICHMENT_ENABLED=false` defaults off only the new automatic expanded planner; it does not disable the UI. Autonomous research, providers/models, and public buying-chain research have separate controls. Verify deployed flags independently. No production-ready or live-provider claim is made.

Historical intake is preserved at [Git candidate `5ef5f3f`](https://github.com/nrsandoval1231-oss/gl3/commit/5ef5f3f29e94fffb071351b61e186d236d40068c). Historical empty-database and earlier field-count reports do not describe current corpus status.
