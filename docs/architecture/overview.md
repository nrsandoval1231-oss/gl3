# Architecture: current implementation and target

Authority: [Autonomous Intelligence Canon](../product/AUTONOMOUS_INTELLIGENCE_CANON.md) and [PRD](../product/PRD.md). This document describes implementation only where labeled CURRENT. Target contracts are proposals, not shipped services.

## CURRENT — repository implementation boundaries

- API: FastAPI application and response contracts in `backend/src/gridlens/api/app.py` and `backend/src/gridlens/api/intelligence.py`.
- Persistence: PostgreSQL SQLAlchemy models in `backend/src/gridlens/persistence/models.py`; additive Alembic history in `backend/migrations/versions/`. The November 2 production receipt confirms schema 0049 / 74 tables for deployed main `ec6486a`; see [production release evidence](../validation/production-release-20261102.md).
- Collection: source registry, scheduled checks/receipts, durable jobs, observations, immutable evidence versions, interpretation and worker execution (`backend/src/gridlens/ingestion/`, `backend/src/gridlens/jobs/worker.py`).
- Identity: project identity and match decisions plus company/person identity, membership and buying-chain claims; associations remain evidence- and project-scoped. Identity links do not imply demand qualification.
- Commercial intelligence: accepted need/activity records, typed fact versions and decisions, lifecycle events, existing power schedules, deterministic official qualification, commercial assessment/research, and published browse projections. A bounded equipment-demand-v1 path is also implemented and deployed; the current production summary has zero validated records and reports demand unavailable. See `backend/src/gridlens/domain/power_qualification.py`, `power_schedule.py`, `call_facts.py`, `equipment_demand.py`, and `opportunity_intelligence.py`.
- Verification: some deterministic boundaries and optional/shadow EvidenceJudge runs exist (`evidence_judge_runs`); they are not a general independent validator or a learned autonomous evaluation system.
- API/UI publication: server-owned browse and opportunity projections. UI/API presence is not evidence that every target claim is supported. Unknown supply, uncertain contacts, and incomplete signals remain unknown or held.

Existing eligibility, tier, evidence and privacy boundaries remain those in the canonical product docs. Historical tables and internal exceptional controls do not imply routine human review in the target workflow.

## TARGET — six-layer demand intelligence contract

The [engine specification](intelligence-engine.md) defines six layers: (1) Discovery, (2) Entity/Evidence, (3) Electrical Demand, (4) Lifecycle/Timing, (5) Commercial, and (6) Autonomous Evaluation. Demand identification and characterization do not depend on supply constraint or shortage claims. Existing API, worker, PostgreSQL, EvidencePackage, intelligence-card API and source adapters are the preferred substrate; no migration or new framework is planned for the current slice.

A replaceable reasoning-provider interface may assist interpretation. Athena is optional, not a runtime dependency or required framework. Engineers own deterministic calculations and tests.

## CURRENT — bounded equipment-demand implementation

The bounded O&G equipment parser, deterministic `Decimal` pump/compressor calculations, immutable `EvidencePackage` persistence, normal/unchanged-record ingestion hooks, and intelligence-card API contract are in deployed main `ec6486a`. No schema migration was needed. The live release receipt reports **zero current validated equipment-demand records**; the demand summary is unavailable, with no supported portfolio MW total. This is implemented code, not evidence of current validated demand coverage.

See the dated [implementation and validation record](../engineering/equipment-demand-slice-20261030.md) for source and fixture limits. Later work can add broader deterministic, versioned O&G and data-center models with explicit input provenance, units, scenarios and negative cases. Independent evaluation fixtures, abstention thresholds, and rollback/promotion records remain necessary before connecting autonomous reasoning to publication. The historical Phase 0 specification work itself made no runtime change.

## DEFERRED

General-purpose graph database, speculative orchestration framework and paid provider activation without separate authorization.

## EXCLUDED

Required routine human approval queues, unrestricted autonomous production code editing, and representing documentation as implemented capability.

## Related specifications

- [Data model](data-model.md)
- [Demand models](demand-models.md)
- [Verification and evaluation](verification-evaluation.md)
- [Existing opportunity intelligence](OPPORTUNITY_INTELLIGENCE.md)

The deployed [native FERC notice path](../engineering/native-equipment-demand-20261030.md) reuses this contract for a narrowly scoped proposed equipment site. Its source-bound equipment claims remain UNVERIFIED; unsupported electrical inputs remain unknown. The source configuration adds a bounded FERC environmental-assessment query alongside the existing EIS query. Historical fixture replay and current service health do not establish a complete scheduled-source cycle or broad equipment coverage. The exact production observation and zero-record demand summary are in the [release receipt](../validation/production-release-20261102.md).
