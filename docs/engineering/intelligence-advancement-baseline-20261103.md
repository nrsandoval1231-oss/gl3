# Intelligence advancement — read-only baseline (2026-11-03)

Base: `main` @ `0a51885` (application `ec6486a2`, PR165). Alembic head `0049_scoped_identity_browse`.
Method: three read-only Claude subagents (the repository's Sol/Luna/Astra harness was **not available**: no launcher, config or provider key) plus owner review. Findings are file-level inspection, not executed tests. Line numbers are approximate and should be re-verified before editing.

## Requirement map

| Spec item | Status | Existing module to extend | Gap |
|---|---|---|---|
| 12 Versioned CommercialOpportunityAssessment | PARTIAL | `domain/commercial_triage.py` (`commercial-triage-v2.1`, card + `input_hash`, stored in `pursuits.snapshot`); `intelligence/commercial_assessment.py` (LLM advisory, `ADVISORY_ONLY`); `PowerNeedBriefVersion` | No dedicated table/entity; versions live as JSON. Next Alembic revision would be `0050` (down `0049_scoped_identity_browse`). |
| 13 Application classes | MISSING (typed) / regex hints | regex in `commercial_triage.py` (~146, 239, 538-585); `PowerNeed.activity_key` free string | No enum; no utility-delay-bridge or distributed-generation class. |
| 14 Buying chain | PARTIAL | `domain/buying_chain.py` `Category`; `intelligence/buying_chain.py`; identity links/memberships | No `utility` role; developer folded into `owner_developer`; no role-confidence tiers. |
| 15 Explainable priority, missing-MW tolerance | PARTIAL | `domain/ranking.py` (six weighted factors, legacy); triage `_priority` tuple | Triage priority not itemized into factors; MW already non-disqualifying (only upper bound <0.3 MW rejects). |
| 16 One next action | EXISTS (free text) | triage `next_action`/`next_question` | Not typed/enumerated; assessment job fallback is two generic strings. |
| Merge safeguards (Phase A acceptance) | EXISTS | `identity_reconciliation.py` (LEI/EIN only, reviewed link), `project_identity.decide_project_match` | Needs acceptance test run, not new code. |
| 17-22 Demand | EXISTS (bounded) | `domain/equipment_demand.py`, `ingestion/parsers/equipment.py`, `intelligence/equipment_intelligence.py`, `demand_summary.py` | MW low/base/high ranges and stepwise calculation trace MISSING; prose/PDF-table parsing MISSING; data-center equipment MISSING; negative cases already tested. |
| Real corpus (18, B acceptance) | PARTIAL | 2 real FERC PDFs + RRC/TCEQ/OK-DEQ fixtures | No measured extraction accuracy; 0 production validated records at Nov 2. |
| 23-26 Lifecycle | PARTIAL | `domain/lifecycle.py`, `lifecycle_service.py`, `lifecycle_replay.py`, `change_detection.py` | No campus/building/phase hierarchy; start-window estimate only for upstream wells; equipment demand not re-run on milestone change; no explicit "announced" state. |
| 27 Source audit | EXISTS | schedule epochs, `SourceDueCheck`, `SourceCheckReceipt`, fenced `Job`, continuation budget (8), provider gates default OFF | No dead-letter/cancelled job status. |
| 28 Seven-cycle measurement | PARTIAL | `operations_view` (30-day counts); `integration_evaluation.validate_operational_receipts` (offline 7-day / 95%) | `SourceDueCheck.local_day` is written but never aggregated: no live DB-derived per-day success metric. |
| 29 Investigation scheduling | EXISTS | `pursuit_research.plan_questions`, `autonomous_research.py`, `monitoring.py` (gated off) | Reuse; add buyer/equipment/timing prioritization only if measured need. |
| 30 Assessment lifecycle | PARTIAL | disposition, workflow status, lifecycle enums scattered | No unified state machine (discovered/assessed/enriched/reassessed/withdrawn/superseded). |
| 31 Eval datasets | PARTIAL | `scripts/intelligence_evaluation.py`, `.agent/AUDIT_NEWS_*_LABELS.json` | Holdouts consumed for development; no untouched split or CI gate. |
| 32 Provider gates | EXISTS | `settings.py`, `integrations/logical_calls.py` | Preserve; no change. |
| 33-37 UI | EXISTS | `Workspace.tsx`, `ProjectResults.tsx`, `customer_results.py` | Default is the customer rollup (priority sort); commercial columns (application, next action, demand range, start window) not shown. |
| 38 Daily pursuit brief | MISSING | `WorkspaceChanges.tsx` + `workspace_changes.py` (material changes panel) | No dated brief surface. |
| 40 Validation | see below | `ci.yml`, `scripts/check.ps1` | |

## Validation environment (this container)
Present: uv, Python 3.13 only (project needs 3.11), Node 22, psql 16 client, PostgreSQL 16 server binaries. Absent: `pwsh` (`check.ps1` cannot run; run its commands individually), running Docker daemon, backend venv, `web/node_modules`, Playwright browsers. Repo targets PostgreSQL 18.6, so a PG16 local cluster is a parity risk. `scripts/check_docs.py` is not wired into CI or `check.ps1`. Nothing has been executed yet.

## Constraints on acceptance
- "25 real, independently sourced records" and "five verified opportunities" need retained/production data or permitted live fetches. This container has no production data and none is authorized. Achievable here: evaluation against tracked real fixtures and permitted public-source fetches, with actual yield and blockers reported. No synthetic substitution.
- Seven-cycle source health needs seven days of production scheduler observation; it cannot be produced from this repository. PR-B can only ship the measurement query and its denominator rules.

## Proposed PR sequence (each reversible)
1. **PR-A** — typed application classes and next-action types in the domain layer; itemized priority factors; `utility` buying-chain role; `CommercialOpportunityAssessment` as a versioned projection (migration 0050, additive) reusing triage cards; merge-safeguard acceptance tests; real-fixture cohort report.
2. **PR-B** — live per-local-day due-check success query/endpoint over `SourceDueCheck`/`SourceCheckReceipt` with exclusions and denominator (read-only; no schema change expected).
3. **PR-C** — MW low/base/high + stepwise calculation trace on `equipment-demand-v1`; corpus acquisition from permitted sources.
4. **PR-D** — lifecycle hierarchy/phase scoping and non-well start windows; re-run demand on milestone change.
5. **PR-E** — commercial columns in the rollup and a daily pursuit brief built on `workspace_changes`.
