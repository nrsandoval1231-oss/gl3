# GridLens — Autonomous Power Demand Intelligence Canon

**Status:** Sole active product authority · owner-aligned 2026-10-30
**Authority:** This document controls product identity, operating boundaries, evidence policy, vertical sequence, and target autonomy. The [PRD](PRD.md) supplies compatible, detailed requirements; the [Results Canon](PROJECT_FIRST_RESULTS_CANON.md) supplies compatible presentation requirements; the [Vertical Lifecycle Strategy](VERTICAL_LIFECYCLE_STRATEGY.md) supplies compatible lifecycle doctrine. In a conflict, this canon prevails. The [October 29 UI canon](../design/UI_CANON.md) and approved screenshot control presentation.

## Delivery state

- **CURRENT:** Hosted application and released UI state are recorded in [.agent/CURRENT_STATE.md](../../.agent/CURRENT_STATE.md) and dated release receipts. This canon does not claim that the target engine below is shipped.
- **TARGET:** The autonomous evidence-driven intelligence platform specified here.
- **NEXT:** Complete and verify the bounded O&G demand slice; integrate the demand KPI from supported records. Broader layers remain later target work.
- **DEFERRED:** Additional vertical lenses, Athena integration, autonomous model/policy promotion, paid-provider activation, and any production/deployment changes without separate authorization.

## Product truth
**GridLens is Autonomous Power Demand Intelligence.** It autonomously discovers and characterizes electrical demand from source evidence, resolves the entities and equipment behind it, tracks lifecycle and timing, derives commercial relevance, and evaluates its own performance. Demand identification is the product center. Utility shortages, supply constraints, residual gaps, and qualification gates are not prerequisites to defining or publishing a demand record.

The target output is an evidence-linked demand record centered on amount and amount class, equipment/activity, entity scope, lifecycle/timing, and uncertainty. Commercial context is subordinate to identified demand. The target six-layer engine is not shipped.

## Non-negotiable user experience
- No call logging, manual fact drafting, operator statuses, manual qualification, routine correction forms, human workflow updates, or administrative pursuit logging in ordinary user-facing product flows.
- Do not reintroduce these routine workflows under new names, tabs, dialogs, or routes. Preserve exceptional correction, suppression and privacy controls through audited internal operations/services. They must not become a prerequisite to discovery, enrichment, qualification or daily use.
- Target primary result: an evidence-linked demand record, with entity/project/equipment scope, demand amount and class, timing/lifecycle, source provenance, and explicit uncertainty. Commercial entities and contacts add context where supported.
- A demand record does not require a plausible residual gap, utility constraint, buyer, or qualification tier. Supply context may be shown when sourced, but no supply shortage is asserted by default.
- Preserve evidence access, privacy, and responsive behavior. The October 29 UI remains released production truth; demand-centered UI is implemented in the current candidate, while KPI data is unavailable. Candidate work is not production deployment.

## Autonomous pipeline
DISCOVERY → ENTITY/EVIDENCE → ELECTRICAL DEMAND → LIFECYCLE/TIMING → COMMERCIAL → AUTONOMOUS EVALUATION.
Run independently of the owner's device, with scheduled/incremental ingestion, durable queues, idempotency, bounded retries, source health, cost controls and observability. Preserve existing useful adapters and algorithms; improve rather than gratuitously rewrite.

The target engine has six layers: **(1) Discovery, (2) Entity/Evidence, (3) Electrical Demand, (4) Lifecycle/Timing, (5) Commercial, and (6) Autonomous Evaluation.** Their boundaries are in [architecture overview](../architecture/overview.md), [intelligence engine](../architecture/intelligence-engine.md), [data model](../architecture/data-model.md), [demand models](../architecture/demand-models.md), and [verification and evaluation](../architecture/verification-evaluation.md). These describe target architecture, not shipped capability. Current Signal/Prospect/Lead rules and 300 kW eligibility remain legacy runtime behavior where deployed; they are not target demand definitions or prerequisites.

## Evidence and commercial integrity
- Never fabricate project identities, power loads, dates, probabilities, contacts, or verification.
- Keep amount classes distinct: **documented**, **calculated**, **estimated**, **inferred**, and **unknown**. Material claims retain source/citation, source publication or event date where available, observation and retrieval dates, extraction/calculation version, linked entity, and verification/conflict state. Preserve competing assertions and temporal history.
- Reasoning models may interpret or propose claims; they do not own arithmetic or evaluate themselves. Documented, calculated, estimated, inferred, and unknown are the target amount classes. Deterministic software owns unit conversion and reproducible calculations; preserve provenance and uncertainty.
- Independent verification checks source authority and time, entity identity, contradictions, corroboration where available, engineering bounds, deterministic recomputation, and calibrated abstention. Agreement from a second model alone is insufficient.
- Preserve immutable source provenance, evidence versions, conflicts, source health, auditability and deterministic qualification boundaries as backend machinery. Retire routine human-operated product workflows while retaining exceptional, authorized correction/suppression/privacy controls with reason, actor, expected version, idempotency and immutable audit history. Suppression must remain effective across source refresh and regenerated claim identifiers; reinstatement must be explicit. Corrections cannot fabricate verification or bypass qualification.
- Distinguish demand assertions from supply facts. Supply context may be recorded when evidenced, but absence of supply data neither blocks demand characterization nor implies shortage.
- Consolidate company accounts without merging distinct physical projects. Prefer owner/developer over contractors as headline entity; retain contractor relationships in buying chain.
- Enrich from permitted public/business sources and licensed data only. Respect privacy, provider terms, provenance and freshness. Apollo and Firecrawl are optional authorized integrations, not assumed free datasets.
- Preserve TX/OK/NM and Signal/Prospect/Lead as current legacy runtime compatibility rules where applicable. They do not define the target product or gate demand record creation. The 300 kW floor is not a target demand-record threshold.

## Vertical and learning strategy

**Oil & Gas equipment is the first bounded implementation cohort.** Reuse one shared evidence/entity/demand foundation with sector-specific equipment and lifecycle interpretation. Do not infer electric load from horsepower without drive evidence. Broader data center and other sector coverage follows later; campus capacity is not construction or commissioning demand.

Improve through independently tested extraction, identity, demand-model, lifecycle, and commercial metrics. Engineers own deterministic tests and evaluation; model output cannot evaluate itself. No unrestricted self-editing. A future reasoning provider such as Athena is replaceable and optional; it is neither a product dependency nor a required framework.

## Success metrics
Primary demand KPI: **Identified Power Demand MW**, with documented, calculated, and estimated MW reported separately and no double counting. Demand may be identified even when MW is unknown; report identified demand records and unknown MW separately. Track evidence coverage, freshness, entity resolution, lifecycle/timing quality, and commercial relevance as supporting measures.

## Historical Phase 0 scope and current implementation boundary

The October 29 Phase 0 was documentation-only. Current implementation is a narrower first slice: source equipment parsing and deterministic `Decimal` electric-pump/compressor models using `equipment-demand-v1` on existing `EvidencePackage` records and normal and unchanged-record ingestion hooks; demand records use the existing intelligence-card API contract. No migration is planned. Independent deterministic tests are engineer-owned. This slice is in progress and does not implement all six layers. Demand-centered UI changes are in the current candidate, but Identified Power Demand MW data is unavailable. October 29 UI remains released production truth; candidate work is not deployed. See the [implementation plan](../engineering/equipment-demand-slice-20261030.md).

## Historical candidate directions

The October 26 commercial repair, workbook activation and PR126-only release exception are preserved in the [pre-streamlining canon](../../.agent/archive/STREAMLINING-20261029/docs__product__AUTONOMOUS_INTELLIGENCE_CANON.md). They record that candidate’s scope and permissions, not current operating instructions or authorization for another release. Current product, evidence and engineering requirements above remain authoritative.
