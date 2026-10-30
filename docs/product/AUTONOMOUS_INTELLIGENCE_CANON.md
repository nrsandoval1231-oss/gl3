# GridLens — Autonomous Commercial Intelligence Canon

**Status:** Sole active product authority · owner-approved 2026-10-29
**Authority:** This document controls product identity, operating boundaries, evidence policy, vertical sequence, and target autonomy. The [PRD](PRD.md) supplies compatible, detailed requirements; the [Results Canon](PROJECT_FIRST_RESULTS_CANON.md) supplies compatible presentation requirements; the [Vertical Lifecycle Strategy](VERTICAL_LIFECYCLE_STRATEGY.md) supplies compatible lifecycle doctrine. In a conflict, this canon prevails. The [October 29 UI canon](../design/UI_CANON.md) and approved screenshot control presentation.

## Delivery state

- **CURRENT:** Hosted application and released UI state are recorded in [.agent/CURRENT_STATE.md](../../.agent/CURRENT_STATE.md) and dated release receipts. This canon does not claim that the target engine below is shipped.
- **TARGET:** The autonomous evidence-driven intelligence platform specified here.
- **NEXT:** Phase 1 evidence/entity foundation, then deterministic demand models for Oil & Gas and Data Centers.
- **DEFERRED:** Additional vertical lenses, Athena integration, autonomous model/policy promotion, paid-provider activation, and any production/deployment changes without separate authorization.

## Product truth
**GridLens is Commercial Intelligence for Constrained Power.** It is an autonomous, evidence-driven platform that discovers electrical demand, interprets the equipment and projects creating it, evaluates documented supply constraints, identifies procurement opportunities and decision-makers, independently verifies its conclusions, and improves through measured outcomes. Its routine intelligence pipeline has no mandatory human review gate.

The target commercial output is a concise, ranked **Today** queue of actionable, evidence-backed, company-centered opportunity cards. Each connects the responsible organization to distinct physical projects and power needs, states why it matters and what to do next, and retains source-backed evidence and explicit unknowns. Today and company-centered outputs are target product direction, not a claim that each is already shipped.

## Non-negotiable user experience
- No call logging, manual fact drafting, operator statuses, manual qualification, routine correction forms, human workflow updates, or administrative pursuit logging in ordinary user-facing product flows.
- Do not reintroduce these routine workflows under new names, tabs, dialogs, or routes. Preserve exceptional correction, suppression and privacy controls through audited internal operations/services. They must not become a prerequisite to discovery, enrichment, qualification or daily use.
- Primary surfaces: actionable Opportunities, automated Research, emerging Signals, and search. Operations/diagnostics may remain internal, not a user workflow.
- Every opportunity should expose company/project, physical location, power need, plausible residual gap, timing/duration, priority, decision-maker and verified business email/phone where available, explanation, sources, freshness, and explicit unknowns.
- Preserve the approved seven-color G/L brand and compact navigation. The October 29 approved Opportunities surface is a project table with adjacent detail and three honest KPIs; operator/customer grouping remains secondary. The primary market filters are All / Oil & Gas / Data Centers. Mobile must be genuinely usable; see the UI canon for presentation detail.

## Autonomous pipeline
DISCOVER → RESOLVE → RESEARCH → ENRICH → ANALYZE → SCORE → PUBLISH → REFRESH.
Run independently of the owner's device, with scheduled/incremental ingestion, durable queues, idempotency, bounded retries, source health, cost controls and observability. Preserve existing useful adapters and algorithms; improve rather than gratuitously rewrite.

The target engine has seven cooperating layers: **(1) autonomous discovery, (2) evidence and entity graph, (3) equipment and demand intelligence, (4) lifecycle and timing, (5) supply and constraints, (6) commercial qualification, and (7) evaluation and learning.** Their current/target ownership and contracts are specified in [architecture overview](../architecture/overview.md), [intelligence engine](../architecture/intelligence-engine.md), [data model](../architecture/data-model.md), [demand models](../architecture/demand-models.md), and [verification and evaluation](../architecture/verification-evaluation.md). These describe target architecture, not shipped capability.

## Evidence and commercial integrity
- Never fabricate project identities, power loads, gaps, dates, probabilities, contacts, or verification.
- Keep five claim classes distinct: **source-verified facts**, **reproducible calculations**, **engineering estimates**, **model inferences**, and **unknown or contradicted claims**. Material claims retain source/citation, source publication or event date where available, observation and retrieval dates, extraction/calculation version, linked entity, and verification/conflict state. Preserve competing assertions and temporal history.
- LLMs may interpret, extract, classify, resolve ambiguity, propose hypotheses, plan bounded research, and explain. Versioned deterministic software owns unit conversions, engineering arithmetic, qualification rules, identity constraints, and reproducible scoring. Models cannot silently invent inputs, change evidence classes, or overwrite provenance.
- Independent verification checks source authority and time, entity identity, contradictions, corroboration where available, engineering bounds, deterministic recomputation, and calibrated abstention. Agreement from a second model alone is insufficient.
- Preserve immutable source provenance, evidence versions, conflicts, source health, auditability and deterministic qualification boundaries as backend machinery. Retire routine human-operated product workflows while retaining exceptional, authorized correction/suppression/privacy controls with reason, actor, expected version, idempotency and immutable audit history. Suppression must remain effective across source refresh and regenerated claim identifiers; reinstatement must be explicit. Corrections cannot fabricate verification or bypass qualification.
- Distinguish facility load, activity-specific temporary power, committed supply, and residual gap; unknown is not zero.
- Consolidate company accounts without merging distinct physical projects. Prefer owner/developer over contractors as headline entity; retain contractor relationships in buying chain.
- Enrich from permitted public/business sources and licensed data only. Respect privacy, provider terms, provenance and freshness. Apollo and Firecrawl are optional authorized integrations, not assumed free datasets.
- Preserve the existing TX/OK/NM physical-site eligibility until the owner explicitly changes territory scope. Keep 300 kW floor and Signal/Prospect/Lead evidence semantics unless separately amended.

## Vertical and learning strategy

**Oil & Gas and Data Centers are the first verticals.** Use one shared evidence/entity/commercial foundation with modular sector-specific lifecycle and demand rules. Oil & Gas includes supported upstream production/electrification and fixed infrastructure; do not infer electric load from horsepower without drive evidence. Data Center campus capacity is not construction or commissioning load; model phases and needs separately. Industrial/manufacturing, EV charging, mining, digital assets, and other large loads are later lenses, not current scope expansion.

Improve through measured extraction, identity, demand-model, contact, commercial-relevance, and outcome metrics. Candidate prompts, models, and policies are evaluated on frozen holdouts and regression gates; promotion requires explicit measurable conditions, observability, and rollback. No unrestricted self-editing. **Athena is optional and replaceable** as a future reasoning provider; GridLens owns domain evidence, deterministic models, qualification, and outcomes, and does not depend on Athena.

## Success metrics
Verified actionable contacts per eligible project; source-backed gap/timing coverage; freshness; unique project/company resolution; buyer relevance; precision of priority; pipeline reliability and time to commercially actionable discovery. Never optimize for raw permit counts or manual entries.

## Phase 0 scope and implementation boundary

Phase 0 is documentation-only: establish this authority, align the supporting PRD and current documents, identify current/target gaps, and define the next implementation slices. It does not deliver the target engine, remove code or product workflows, change data/schema/configuration, run migrations, or establish current production capability. Architecture gaps and code changes belong in separately scoped follow-on implementation work; do not treat this canon as permission to deploy or alter production. Later phases require their own scoped acceptance and verification.

## Historical candidate directions

The October 26 commercial repair, workbook activation and PR126-only release exception are preserved in the [pre-streamlining canon](../../.agent/archive/STREAMLINING-20261029/docs__product__AUTONOMOUS_INTELLIGENCE_CANON.md). They record that candidate’s scope and permissions, not current operating instructions or authorization for another release. Current product, evidence and engineering requirements above remain authoritative.
