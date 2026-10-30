# Architecture: current implementation and target

Authority: [Autonomous Intelligence Canon](../product/AUTONOMOUS_INTELLIGENCE_CANON.md) and [PRD](../product/PRD.md). This document describes implementation only where labeled CURRENT. Target contracts are proposals, not shipped services.

## CURRENT — repository implementation boundaries

- API: FastAPI application and response contracts in `backend/src/gridlens/api/app.py` and `backend/src/gridlens/api/intelligence.py`.
- Persistence: PostgreSQL SQLAlchemy models in `backend/src/gridlens/persistence/models.py`; additive Alembic history in `backend/migrations/versions/`. Current production checkpoint reports migration 0049 / 74 tables; see [.agent/CURRENT_STATE.md](../../.agent/CURRENT_STATE.md).
- Collection: source registry, scheduled checks/receipts, durable jobs, observations, immutable evidence versions, interpretation and worker execution (`backend/src/gridlens/ingestion/`, `backend/src/gridlens/jobs/worker.py`).
- Identity: project identity and match decisions plus company/person identity, membership and buying-chain claims; associations remain evidence- and project-scoped. Identity links do not imply demand qualification.
- Commercial intelligence: accepted need/activity records, typed fact versions and decisions, lifecycle events, demand/supply schedules, deterministic official qualification, commercial assessment/research, and published browse projections. See `backend/src/gridlens/domain/power_qualification.py`, `power_schedule.py`, `call_facts.py`, and `opportunity_intelligence.py`.
- Verification: some deterministic boundaries and optional/shadow EvidenceJudge runs exist (`evidence_judge_runs`); they are not a general independent validator or a learned autonomous evaluation system.
- API/UI publication: server-owned browse and opportunity projections. UI/API presence is not evidence that every target claim is supported. Unknown supply, uncertain contacts, and incomplete signals remain unknown or held.

Existing eligibility, tier, evidence and privacy boundaries remain those in the canonical product docs. Historical tables and internal exceptional controls do not imply routine human review in the target workflow.

## TARGET — seven-layer intelligence contract

The [engine specification](intelligence-engine.md) defines layer inputs, outputs and evidence gates. Flow: (1) discovery, (2) evidence/entity graph, (3) equipment and demand, (4) lifecycle/timing, (5) supply/constraints, (6) commercial qualification, (7) evaluation/learning. Existing API, worker, PostgreSQL and source adapters are the preferred substrate; no new infrastructure is assumed.

A replaceable reasoning-provider interface may assist extraction, classification, ambiguous resolution and research planning. Athena is optional and outside this repository's runtime dependency. Deterministic software owns calculations, qualification, validation and publication eligibility.

## NEXT — implementation sequence

1. Extend evidence/entity structures additively for temporal many-to-many equipment, demand scenario and supply relationships; retain current identifiers and projections.
2. Add deterministic, versioned O&G and data-center demand models with explicit input provenance, units, scenarios and negative cases.
3. Add independent evaluation fixtures, abstention thresholds and rollback/promotion records before connecting autonomous reasoning to publication.

Each slice needs migration/API compatibility and isolated-database regression evidence. No runtime change is part of the Phase 0 specification work.

## DEFERRED

General-purpose graph database, speculative orchestration framework and paid provider activation without separate authorization.

## EXCLUDED

Required routine human approval queues, unrestricted autonomous production code editing, and representing documentation as implemented capability.

## Related specifications

- [Data model](data-model.md)
- [Demand models](demand-models.md)
- [Verification and evaluation](verification-evaluation.md)
- [Existing opportunity intelligence](OPPORTUNITY_INTELLIGENCE.md)
