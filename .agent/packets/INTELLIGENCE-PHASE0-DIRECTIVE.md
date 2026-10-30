# CODEX MASTER DIRECTIVE
## GridLens — Canonical Autonomous Intelligence Pivot, Deep Audit & Repository Consolidation

**Repository:** `nrsandoval1231-oss/gl3`  
**Priority:** Critical — Product Architecture and Canonical Vision  
**Mission type:** Audit, canonical documentation consolidation, safe cleanup, architecture gap analysis, and phased implementation planning.

> **Authoritative direction:** GridLens is an autonomous, evidence-driven commercial intelligence platform for constrained power. It continuously discovers electrical demand, determines its technical and commercial significance, investigates supply constraints, identifies procurement opportunities and decision-makers, independently verifies claims, and improves through measurable outcomes. Routine intelligence operations require no human review.

## 1. Mission and boundaries

Act as the lead architect and repository maintainer. Inspect the current repository before modifying it. Understand the actual code, data model, ingestion pipelines, production contracts, tests, deployment, and existing documentation. Make the new direction the sole **active** authority, remove contradictions and verified dead weight, and produce an evidence-based implementation plan. Preserve the functioning production system.

Deliver: (1) deep repository audit; (2) authoritative product vision and PRD; (3) current-versus-target architecture map; (4) safely consolidated documentation and agent instructions; (5) verified cleanup; (6) phased technical backlog with acceptance criteria; (7) tests and independent review; (8) a focused PR. Do not claim that a documentation pivot implements the new engine.

**Non-goals for this PR:** wholesale rewrite, speculative new infrastructure, mass deletion of historical evidence, redesigning the approved UI, silently modifying production data, activating paid providers, sending customer outreach, or unbounded agent self-modification.

## 2. Sole canonical product identity

**Name:** GridLens  
**Positioning:** Commercial Intelligence for Constrained Power  
**Identity:** Autonomous electrical-demand discovery and commercial opportunity intelligence.

GridLens answers:

1. Who needs power, and at which facility/project/phase?
2. What equipment, operations, or planned expansion creates the demand?
3. How much connected and operating electrical load is supported by evidence, and what are the modeled scenarios?
4. When might that demand occur, and what lifecycle event establishes timing?
5. What utility or onsite supply is documented, and is a residual supply gap defensible?
6. What procurement event is likely or verified, who owns the decision, and how can the buyer be reached?
7. What is the next commercially useful action, and what evidence supports it?

GridLens is **not primarily** a permit aggregator, generic CRM, grid map, project directory, engineering simulator, or speculative shortage predictor. These may be inputs or supporting capabilities, not the product identity.

The ultimate output is a concise, ranked **Today** queue of actionable, evidence-backed opportunities and company-centered opportunity cards, not raw records or complex research dashboards.

## 3. Immutable operating principles

### 3.1 No mandatory human involvement in routine intelligence

Ingestion, document extraction, classification, entity resolution, engineering calculations, evidence verification, investigation, scoring, and ordinary publication run autonomously. Eliminate required human approval queues, routine manual review, manual tagging, and manual lead ranking from the **target** architecture.

Autonomy is not permission to fabricate. On inadequate or conflicting evidence, investigate automatically, downgrade confidence, clearly label uncertainty, or abstain. Never convert missing data into a made-up answer. Preserve optional user correction and commercial judgment, but do not require it for engine operation.

### 3.2 Evidence classes are explicit

Represent separately: **source-verified facts**, **reproducible calculations**, **engineering estimates**, **model inferences**, and **unknown/contradicted claims**. Each significant claim has a source, observation date, retrieval date, extraction version, entity linkage, and verification state. Distinguish a demand estimate from a confirmed power shortage.

### 3.3 LLMs interpret; software calculates

LLMs can extract, classify, resolve ambiguous text, propose hypotheses, plan research, and explain findings. Schema-validated, versioned deterministic functions perform unit conversions, load calculations, rules, deduplication constraints, and reproducible scoring. Never let the model silently invent engineering inputs or overwrite provenance.

### 3.4 Independent automated verification

Verification must include source authority, temporal consistency, cross-source corroboration where available, contradiction checks, entity identity checks, engineering sanity bounds, deterministic recomputation, and calibrated abstention. A second model merely agreeing is not sufficient. Design for testable negative cases and provenance-preserving correction.

### 3.5 Measured self-improvement, not uncontrolled self-editing

Observe extraction precision, source reliability, equipment classification, demand-model error, buyer-contact validity, commercial relevance, and realized outcomes. Evaluate prompt/model/policy candidates against frozen holdouts and regression gates; deploy only with explicit automated promotion conditions, observability, and rollback. Do not implement unrestricted production code mutation.

### 3.6 Incremental, economical, maintainable

Reuse current PostgreSQL, workers, APIs, and ingestion architecture where sound. Prefer incremental change detection and targeted research to full recrawls. Do not add a graph database, orchestration framework, or complex multi-agent hierarchy without measured necessity.

## 4. Canonical intelligence architecture

### Layer 1 — Autonomous discovery

Monitor permits, environmental records, interconnection and utility proceedings, construction records, equipment filings, company announcements, RFPs/RFIs, infrastructure expansions, and legally accessible public sources. Retain original documents/snapshots, dates, source IDs, change events, and ingestion outcomes. Use baseline-plus-incremental processing and retry/backoff for unreliable providers.

### Layer 2 — Evidence and entity graph

Maintain relationships among **Company → Facility → Project → Phase → Equipment → Demand Scenario → Supply Constraint → Procurement Event → Decision-Maker**. Support non-tree and many-to-many relationships where required. Consolidate company-level opportunities with nested source evidence. Preserve conflicting assertions and temporal history rather than overwriting them. Avoid duplicate company/project records and stale cross-project contact joins.

### Layer 3 — Equipment and demand intelligence

Recognize electric versus gas/mechanical drives; nameplate versus input electrical power; connected versus coincident operating load; new versus existing assets; duty cycles; redundancy; proposed versus installed equipment; and primary versus standby use. Produce traceable low/base/high scenarios **only where assumptions are defensible**. Examples: compression, pumps, processing motors, data-center IT/cooling, charging, mining loads, industrial expansion. Preserve unknowns and calculation version.

### Layer 4 — Lifecycle and timing

Track planning, permitting, procurement, construction, commissioning, energization, expansion, operation, and replacement. Record observed events and estimated milestones separately. Derive urgency from source-backed schedules and changes, not invented dates.

### Layer 5 — Supply and constraints

Assess known electrical service, upgrade requests, interconnection milestones, documented delays, temporary generation, onsite generation, and commissioning needs. Grid distance is contextual evidence, **not** proof of service availability. Compute residual gap only where demand and supply inputs are comparable in capacity, time, and scope. Otherwise identify unresolved questions and pursue evidence.

### Layer 6 — Commercial qualification

Generate company-centered opportunity records with sector, facility, phase, documented demand, modeled MW scenarios, timing, buyer/owner/operator, sourced contact channels, procurement status, solution type, confidence, evidence, and next action. Distinguish verified opportunity from investigation lead. Never fabricate buyer authority, email, phone, procurement intent, or contractual need.

### Layer 7 — Evaluation and learning

Measure source freshness/coverage, extraction precision, entity resolution, contradiction rate, model error, lead precision, contact coverage, research cost, and time-to-opportunity. Use outcome evidence to improve ranking and investigation strategy. Independent regression and rollback remain mandatory.

## 5. Sector strategy and sequence

**First:** Oil & Gas and Data Centers.

- **Oil & Gas:** Electric compression, SWD, pumps, processing, electrification, midstream infrastructure, and expansions. Do not infer electric demand from engine horsepower without verifying drive type.
- **Data Centers:** Owner/developer-centered opportunities; construction and commissioning power; IT/cooling demand; phased capacity and energization; temporary bridge requirements. Do not confuse campus announced capacity with an immediate load.

**Later modular lenses:** Industrial/manufacturing, EV charging, mining, digital assets, and other large loads. Build one shared evidence/entity/commercial foundation with modular sector-specific rules; do not build six independent platforms.

## 6. Athena interface

GridLens owns domain evidence, entities, deterministic engineering models, sector rules, opportunities, and outcomes. Athena may eventually provide reusable specialized decision reasoning and learning. Independent validators remain outside either model's authority. Create a replaceable reasoning-provider contract now, but do not block GridLens on an unfinished Athena model or duplicate Athena inside the repository.

## 7. Deep repository audit procedure

First inventory the actual repository, current `main`, branches/PRs, services, schemas, CI, docs, and deployments. Read the canonical PRD and current-state files, then inspect relevant code paths. Record exact paths and evidence for each conclusion. Examine:

- Product vision, PRD, README, milestones, ADRs, roadmaps, agent instruction files, active vs archived specifications.
- Sources, schedules, crawlers, ingestion, snapshots, extraction, LLM interfaces, classification, entity resolution, deduplication, qualification, scoring, and background jobs.
- PostgreSQL tables, migrations, indexes, source lineage, historical evidence, cohort materialization, account/project relationships, and contact privacy boundaries.
- Engineering calculations, assumptions, unit handling, equipment identification, demand scenarios, and supply-side evidence.
- APIs, authentication, pagination, caching, frontend data contracts, Today queue, project/company cards, contacts, filtering, and browser performance.
- CI/CD, test isolation, security/dependency audits, workers, health checks, operational telemetry, rollback, provider budgets, and secrets handling.

Classify each major component as **KEEP / EVOLVE / REPLACE / REMOVE / DEFER**. For each classification, give rationale, impacted paths, dependencies, migration risk, and recommended order. Clearly separate verified findings from hypotheses.

## 8. Cleanup policy

Remove conflicting active instructions, stale claims, duplicated active specs, dead exports, unused wrappers, redundant styles, abandoned experimental scaffolding, and unreferenced duplicates **only after verifying non-use**. Prefer a single canonical document per concern and concise pointers elsewhere.

Preserve production behavior, schemas and migration history, source records, legal/audit evidence, validation receipts, security boundaries, historical decisions, rollback procedures, existing working integrations, and canonical brand assets. Archive historical visions clearly as non-authoritative rather than pretending they never existed. Do not equate moving files into an archive with reducing repository size.

Do not perform destructive production migrations, production replays, credential changes, paid-provider activation, or production deployment as an incidental cleanup step.

## 9. Canonical documentation hierarchy

Update existing authoritative paths when possible rather than spawning competing documents. Establish:

1. `README.md` — short identity, actual status, quickstart, links.
2. One canonical PRD — mission, personas, outputs, sectors, autonomy, evidence states, acceptance criteria.
3. Architecture specification — **current** and **target** with exact subsystem ownership.
4. Intelligence engine specification — seven layers, contracts, evidence and abstention semantics.
5. Evidence/entity/data-model specification — schema and provenance design.
6. Electrical demand-model specification — formulas, assumptions, versioning, reference cases.
7. Autonomous verification/evaluation specification — independent gates, holdouts, failure handling, rollback.
8. Phased roadmap — sequenced milestones and measurable outcomes.
9. Agent instructions and current-state checkpoint — concise and consistent.

Each document must label **CURRENT / TARGET / NEXT / DEFERRED**. No future capability may be represented as already shipped. All active files must link to the same product authority. Historical records are not active instructions.

## 10. Preserve the approved product and brand

Do not redesign the UI. Preserve the metallic G mark; approved navy/slate/sea-cliff/graphite palette; compact navy horizontal navigation; light, clean, data-first workspace; no left sidebar or photography; dense opportunity table; adjacent company/project evidence and contact detail; responsive views; and fast loading. The user-facing priority remains the ranked **Today** queue and actionable opportunity card, not a GIS dashboard or engineering laboratory.

Preserve existing qualified-versus-Signals semantics, pagination, authenticated browsing, session privacy cleanup, and provenance-backed contacts. Do not regress the October 29 canonical UI release or background-browsing improvements.

## 11. Phased implementation plan

### Phase 0 — Audit and canonical consolidation (this PR)
- Establish authoritative product identity and requirements.
- Produce current/target gap analysis with path-level evidence.
- Remove verified dead weight and contradictory active docs.
- Preserve production behavior and demonstrate unchanged contracts.
- Create focused next-phase tickets or implementation slices.

### Phase 1 — Evidence and entity foundation
- Add only missing claim, equipment, lifecycle, and temporal/provenance structures.
- Prefer additive, backward-compatible migrations.
- Define confidence, contradiction, unknown, and abstention semantics.
- Demonstrate exact-source traceability and no cross-project contamination.

### Phase 2 — Deterministic demand models
- Implement tested O&G electric equipment and data-center phase models.
- Validate unit conversions, efficiency, duty, redundancy, and scenario assumptions.
- Ensure non-electric equipment cannot silently create electrical load.

### Phase 3 — Autonomous investigation and verification
- Schema-validated extraction; independent checks; conflict handling; targeted follow-up discovery.
- Failure-safe retries, cost ceilings, and publication/abstention policies.

### Phase 4 — Commercial opportunity qualification
- Combine demand, timing, supply constraints, procurement evidence, and buyer contacts.
- Prioritize company-centered Today queue and next-action usefulness.
- Preserve separate verified, estimated, inferred, and unknown fields.

### Phase 5 — Evaluation and autonomous optimization
- Establish labeled evaluation fixtures, measurable precision, calibration, drift monitoring, and controlled policy/model promotion.
- Compare lead quality against actual downstream commercial outcomes where observable.

For each phase provide scope, dependencies, estimated effort, risks, acceptance tests, rollback, and commercial impact. Favor small, independently mergeable PRs.

## 12. Validation and release gates

Before declaring Phase 0 complete:

- Run relevant full backend tests, frontend/browser regressions, build/typecheck, lint, dependency/security checks, documentation link checks, and brand protection tests.
- Verify migrations and API compatibility if touched; run deterministic calculation reference tests for any new models.
- Test conflicting sources, missing values, incorrect drive-type inference, duplicate identities, stale evidence, and adversarial extraction where relevant.
- Verify removed code has no runtime consumers and active documents contain no conflicting mission statements.
- Obtain an independent architectural review and resolve material findings.
- Record exact commit, commands, outcomes, skipped tests, and remaining risks.
- Keep local/CI success separate from authenticated live-production validation.
- Do not merge or deploy with failing required checks. Do not silently relax test thresholds or bypass gates.

## 13. Deliverables and PR format

Create a focused branch and PR containing:

**A. Audit:** subsystem inventory and KEEP/EVOLVE/REPLACE/REMOVE/DEFER matrix with exact paths.

**B. Canonical vision:** one product identity, consistent throughout active documents.

**C. Updated PRD:** explicit autonomous operations, evidence taxonomy, technical/commercial outcomes, sector scope, and acceptance criteria.

**D. Gap analysis:** current versus target services, data tables, APIs, workers, model boundaries, and operational risks.

**E. Safe cleanup:** itemized removals, proof of non-use, and preservation of history.

**F. Roadmap:** minimal first implementation slices, dependencies, measurable milestones, and commercial priorities.

**G. Validation:** commands, results, test counts, CI URLs, independent review, residual issues, and exact merge readiness.

**H. PR summary:** what changed, what did not change, and what is still only planned.

If a safe cleanup or foundational code change is too large, split it into a follow-up PR instead of bloating the canonical consolidation PR.

## 14. Acceptance criteria

The mission is done only when:

- One authoritative active product direction exists, with no competing active vision.
- The new PRD and architecture agree, and **CURRENT** versus **TARGET** is unambiguous.
- No mandatory human review is part of the **target** intelligence workflow.
- Working production behavior, approved UI, privacy, and brand remain intact.
- Evidence provenance, demand calculations, supply-gap rules, uncertainty, and independent verification have clear technical contracts.
- Athena is optional and replaceable, not a dependency.
- Safe cleanup is demonstrably safe and repository maintenance is simpler.
- The next implementation PR can begin without reinterpreting strategy.
- Tests and independent review have authentic retained evidence.

## 15. Execution instructions

Start immediately by inspecting the real repository and reporting the actual current architecture. Do not assume prior plans were implemented. Produce the audit and canonical document changes, then complete safe cleanup, validate, and open the focused PR. Do not perform destructive operations or claim success without evidence. Report what remains unfinished and identify the single highest-leverage implementation slice.

**Final product statement:**

> **GridLens is an autonomous commercial intelligence platform for constrained power. It continuously discovers electrical demand, interprets the equipment and projects creating it, evaluates documented supply constraints, identifies procurement opportunities and decision-makers, independently verifies its conclusions, and produces actionable commercial intelligence. Its normal intelligence pipeline operates without mandatory human intervention, and it improves through measured outcomes and independently validated learning.**
