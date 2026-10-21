# PR102 follow-up integration acceptance checkpoint

**Status:** F8 implementation checkpoint; full exact-candidate gates, persisted runtime proof, and independent review are pending. PR102 and approved PR103 have already merged upstream. This candidate normally merges the implementation branch with approved main `cf440a2bab7f7c1a63ffc98dce229e6ee73f671c`; exact commit identity is recorded in ignored `F8-COMPLETION.json` after commit. This document is not release or production approval.

## Integrated behavior and focused proof

The approved horizontal Opportunity Intelligence workspace is preserved. Reported phased supply/demand scheduling appears in the existing Commercial Assessment tab, separate from the canonical qualified gap. Schedule entries retain source kind, ready date/basis, state, suitability, evidence reference, and reporter attribution; only explicit `utility_grid` entries are called reported energization. Proposed phases remain scenarios. Draft, accept, correction, retraction, history, and readback are available through the existing workflow. Contact correction parent refresh and stale-selection guards remain integrated.

The F8 focused browser set passed 62/62 in `approved_workspace.spec.ts`, `workspace.spec.ts`, `buying_chain.spec.ts`, and `pr101-regressions.spec.ts`. Typecheck and production build passed. An initial 60/62 run exposed two stale test selectors for the prior “Your pursuits” heading; selectors now target the approved “Opportunity Intelligence” heading. The current full controller gates and exact-candidate review have not yet run.

The tested `reconcile_claim_identity` strong-ID helper is not called by ordinary enrichment. Ordinary identity remains project-scoped; cross-project links use attributed review through the existing correction API. `OPPORTUNITY_ENRICHMENT_ENABLED=false` defaults off only the new automatic expanded planner, not the UI.

## Retained-data boundary

The isolated retained copy has 1,620 projects, 1,620 needs, and 18,016 evidence rows. The curated manifest has 14 reviewed cases and 79 fields; read-only evaluation reports 79/79 exact agreements and zero populated expected-null fields. Mean completeness is 24.07%; this is field-level accuracy, not commercial completeness. The offline runner remains BLOCKED because site-specific utility constraint, conflicting power dates, and legitimate bridge-power potential are still absent. Do not infer or relabel missing positives.

F6C remains PARTIAL_FAILED_BOUND: 11 GETs completed; a construction-timeout acquisition had an UNKNOWN HTTP send/outcome; there are zero new candidate Need IDs. No production readiness or live-provider acceptance is claimed.

## Deployment and release boundary

Migrations `0035_reconciled_identity` followed by `0036_buying_chain_corrections` are required before integrated code. A separately authorized rollout must validate an isolated restore, apply migrations through head, verify revision, then deploy the exact accepted app. Rollback may retain additive schema and history; do not delete jobs, receipts, ledger reservations, or correction history.

Whole-pipeline controller gates, persisted runtime/restart proof, independent review, live provider acceptance/cost, and the three missing retained categories remain pending or blocked. No push, deployment, production mutation, provider activation, or spend is authorized by this checkpoint.