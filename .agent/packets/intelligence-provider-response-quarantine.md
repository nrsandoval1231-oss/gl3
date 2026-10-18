# B7 — provider response billing quarantine

Candidate base: `8c3d3c2ee627b74cb3fb50dd6b9d5d813bb4daca`; work remains unfrozen.

## Contract

- Require exact configured/actual model string equality for TypeSafe and OpenAI. Do not infer alias mappings.
- Check identity and provider usage limits before semantic parsing or advisory effects. Quarantine missing/different model, invalid reported usage, TypeSafe total billable input above its attested ceiling, OpenAI reported output above the sent enforced bound, or raw response over the logical-call result limit.
- Persist bounded, credential-redacted response evidence and usage in `LogicalCall.result_payload`; retain response ID/model/usage and hash when the raw body exceeds storage bound.
- Keep quarantined call `SENT_OUTCOME_UNKNOWN`, retain `active_count`, `finished_at=NULL`, and `actual_cost_usd=NULL`. Preserve reservation. Quarantine estimates are explicitly conservative and are not provider-invoiced cost.
- For same-model valid over-bound usage, estimate conservatively at pinned rate, charge only the additional exposure beyond the existing reservation, and track budgeted exposure in the quarantine payload. Repeated quarantine, later receipt settlement, and explicit reconciliation must avoid double-counting and must never erase the larger conservative exposure.
- A provider-scoped PostgreSQL advisory transaction lock serializes reserve, dispatch, quarantine, settlement, and reconciliation. Lock order is provider → job/call/budget. Provider guard blocks new reservations and previously reserved `NOT_SENT` dispatches while any same-provider quarantined call remains unknown.
- Only authorized explicit reconciliation with attributable actual-cost evidence may close quarantine; preserve its raw response and usage. Do not retry, auto-refund, or mark estimated exposure as actual.
- Legacy TypeSafe/OpenAI calls must carry actual response model through the shared runner before completion. Preserve Firecrawl calls.

## Scope

`backend/src/gridlens/integrations/logical_calls.py`, `backend/src/gridlens/integrations/legacy_calls.py`, `backend/src/gridlens/intelligence/intelligence_jobs.py`, `backend/src/gridlens/intelligence/briefs.py`, and narrow raw-response envelope propagation in `backend/src/gridlens/intelligence/evidence_shadow.py`; affected integration/unit tests and the activation runbook paragraph. No schema/migration, worker/API/UI, provider call, or deployment action.

## Validation

Use only `gl3_intelligence_settlement_20261018_test` and `_app` on loopback `127.0.0.1:55487`. Run logical-call and worker integration tests, affected unit tests, scoped Ruff and mypy, then diff checks. Required behavior tests include mismatch/missing identity, TypeSafe total-input and OpenAI output-bound breaches, invalid/oversized evidence, stale fence, duplicate quarantine, invoice settlement/reconciliation idempotence, provider lock races and already-reserved dispatch blocking, no-call OFF/zero-cap matrix with synthetic key present, successful synthetic control, and Firecrawl preservation. No self-review acceptance claim; controller re-freezes and runs final gates.

## Current implementation note

Implementation is ready for controller validation; no self-acceptance claim. Positive fixtures are synthetic; official TypeSafe billing/model compatibility remains UNKNOWN and default settings stay OFF/zero.

Focused evidence (2026-10-18 local): first combined run: 142 passed, 5 failed in existing PowerNeedBrief fake-provider tests because their synthetic results lacked the now-required actual model identity. Repair updated those fake results with the pinned synthetic model. A response guard policy identity (`exact-model-usage-v1`) now participates in TypeSafe/OpenAI context freshness and dedup, so pre-guard completed entries do not match current calls; the unit test asserts provider and policy identity. The second single combined run of logical-call, worker, processing, evidence-shadow, signal-adjudication, briefs, and PowerNeedBrief modules passed: 147 passed, 4 warnings in 95.17s. Scoped Ruff, Mypy (five source modules, including evidence_shadow.py), and `git diff --check` passed after the final code/test edits. Earlier isolated evidence-shadow setup encountered PostgreSQL `DeadlockDetected` during fixture `DROP TABLE` (PIDs 26152/35804); attribution is UNKNOWN. No full backend suite or final candidate review is claimed; controller owns final freeze/review.
