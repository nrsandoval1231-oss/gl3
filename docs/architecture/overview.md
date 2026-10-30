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

## TARGET — six-layer demand intelligence contract

The [engine specification](intelligence-engine.md) defines six layers: (1) Discovery, (2) Entity/Evidence, (3) Electrical Demand, (4) Lifecycle/Timing, (5) Commercial, and (6) Autonomous Evaluation. Demand identification and characterization do not depend on supply constraint or shortage claims. Existing API, worker, PostgreSQL, EvidencePackage, intelligence-card API and source adapters are the preferred substrate; no migration or new framework is planned for the current slice.

A replaceable reasoning-provider interface may assist interpretation. Athena is optional, not a runtime dependency or required framework. Engineers own deterministic calculations and tests.

## NEXT — implementation sequence (first slice in progress)

1. Implement the bounded O&G source equipment parser and deterministic `Decimal` electric pump/compressor models; retain source efficiency, count, operating/standby state, and new-versus-existing classification.
2. Bind through the confirmed `EvidencePackage`, normal and unchanged-record ingestion hooks, and existing intelligence-card API contract; no migration is planned for this slice.
3. Later, add broader deterministic, versioned O&G and data-center models with explicit input provenance, units, scenarios and negative cases.
4. Add independent evaluation fixtures, abstention thresholds and rollback/promotion records before connecting autonomous reasoning to publication.

The first slice is documented as in progress, not shipped; see [implementation plan](../engineering/equipment-demand-slice-20261030.md). Each implementation slice needs migration/API compatibility and isolated-database regression evidence. The historical Phase 0 specification work itself made no runtime change.

## DEFERRED

General-purpose graph database, speculative orchestration framework and paid provider activation without separate authorization.

## EXCLUDED

Required routine human approval queues, unrestricted autonomous production code editing, and representing documentation as implemented capability.

## Related specifications

- [Data model](data-model.md)
- [Demand models](demand-models.md)
- [Verification and evaluation](verification-evaluation.md)
- [Existing opportunity intelligence](OPPORTUNITY_INTELLIGENCE.md)
