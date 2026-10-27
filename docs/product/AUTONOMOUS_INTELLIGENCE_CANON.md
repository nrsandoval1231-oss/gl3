# GridLens — Autonomous Commercial Intelligence Canon
Status: OWNER-APPROVED · 2026-10-25 · exceptional-control clarification 2026-10-26 · operator/customer hierarchy amendment 2026-10-27
Authority: This document supersedes conflicting product, workflow, UI, and agent instructions throughout this repository. The later owner-approved [Project-First Results Canon](PROJECT_FIRST_RESULTS_CANON.md) controls the current opportunity surface and vertical-specific field presentation. Historical documents are records, not active requirements where they conflict.

## Product truth
GridLens is an autonomous commercial intelligence engine for constrained and temporary power. It discovers projects, resolves project/company identity, investigates power needs, determines evidence-supported residual power gaps, identifies buying chains, enriches business contact details, ranks opportunities, and continuously refreshes intelligence. The user opens the application to see which projects matter, why, and whom to contact. The user is not a data-entry operator.

## Non-negotiable user experience
- No call logging, manual fact drafting, operator statuses, manual qualification, routine correction forms, human workflow updates, or administrative pursuit logging in ordinary user-facing product flows.
- Do not reintroduce these routine workflows under new names, tabs, dialogs, or routes. Preserve exceptional correction, suppression and privacy controls through audited internal operations/services. They must not become a prerequisite to discovery, enrichment, qualification or daily use.
- Primary surfaces: actionable Opportunities, automated Research, emerging Signals, and search. Operations/diagnostics may remain internal, not a user workflow.
- Every opportunity should expose company/project, physical location, power need, plausible residual gap, timing/duration, priority, decision-maker and verified business email/phone where available, explanation, sources, freshness, and explicit unknowns.
- Preserve the approved seven-color G/L brand and compact navigation. Display **operator/customer groups with nested wells/projects and minimal actionable results** rather than the prior dense account table, four KPI tiles, placeholder totals or raw technical workflows. The primary market filters are All / Oil & Gas / Data Centers. Mobile must be genuinely usable; the results canon with its latest operator/customer amendment is authoritative for layout and sector fields.

## Autonomous pipeline
DISCOVER → RESOLVE → RESEARCH → ENRICH → ANALYZE → SCORE → PUBLISH → REFRESH.
Run independently of the owner's device, with scheduled/incremental ingestion, durable queues, idempotency, bounded retries, source health, cost controls and observability. Preserve existing useful adapters and algorithms; improve rather than gratuitously rewrite.

## Evidence and commercial integrity
- Never fabricate project identities, power loads, gaps, dates, probabilities, contacts, or verification.
- Preserve immutable source provenance, evidence versions, conflicts, source health, auditability and deterministic qualification boundaries as backend machinery. Retire routine human-operated product workflows while retaining exceptional, authorized correction/suppression/privacy controls with reason, actor, expected version, idempotency and immutable audit history. Suppression must remain effective across source refresh and regenerated claim identifiers; reinstatement must be explicit. Corrections cannot fabricate verification or bypass qualification.
- Distinguish facility load, activity-specific temporary power, committed supply, and residual gap; unknown is not zero.
- Consolidate company accounts without merging distinct physical projects. Prefer owner/developer over contractors as headline entity; retain contractor relationships in buying chain.
- Enrich from permitted public/business sources and licensed data only. Respect privacy, provider terms, provenance and freshness. Apollo and Firecrawl are optional authorized integrations, not assumed free datasets.
- Preserve the existing TX/OK/NM physical-site eligibility until the owner explicitly changes territory scope. Keep 300 kW floor and Signal/Prospect/Lead evidence semantics unless separately amended.

## Success metrics
Verified actionable contacts per eligible project; source-backed gap/timing coverage; freshness; unique project/company resolution; buyer relevance; precision of priority; pipeline reliability and time to commercially actionable discovery. Never optimize for raw permit counts or manual entries.

## Implementation directive
1. Inventory UI/routes/components, APIs, models/migrations, background jobs, tests, docs, and operational dependencies referencing human workflow, call facts, operator status, or manual qualification.
2. Build a dependency and data-retention map. Delete obsolete routine user-facing functionality and dead code; migrate safely, preserve historical evidence/data, and retain supported internal exceptional controls.
3. Make this file and AGENTS.md authoritative; amend current PRD/UI canon and linked current documentation to remove contradictory requirements. Mark obsolete specifications as historical rather than silently treating them as current.
4. Deliver autonomous project/contact intelligence end-to-end, not merely a cosmetic cleanup.
5. Test migrations, extraction, company matching, source attribution, gap math, contact verification, mobile UI and production regressions. Independent review before merge; verify deployment separately.

## Engineering execution
Use the repository harness where actually supported: Sol 6.1/high coordinator, 3–6 Luna 6/low independent builders, Astra 6/high independent review. Confirm availability/concurrency rather than inventing assignments. Separate file ownership, integrate and run final gates. No deployment or destructive data mutation without validated safeguards.

## October 26 commercial repair direction

Increase useful business-contact coverage through priority-driven bounded research, retained-source reuse, incremental source evidence and explicit low-yield stopping. Preserve literal named-person/method attribution from the overlapping PR123 work. Treat generic company methods, relevant professionals, source-confirmed project decision makers and verified purchasing authority as separate outcomes.

Reconcile accessible workbooks to conservative company and physical-site identities through read-only reports before any separately authorized staging. Preserve original file/sheet/row provenance, ambiguity and unknowns; imported campus/IT capacity and completion dates never establish temporary demand, a residual gap or a need date. Measure the requested 25 actual eligible projects only against an accessible actual corpus, with complete denominators and source freshness. Synthetic checks establish software behavior and remain separately labeled.

The latest October 26 owner direction additionally authorizes isolated workbook activation and measurement of 25 genuine source-backed opportunities from the available corpus; a production snapshot is not mandatory. Workbook assertions alone do not establish canonical identity, temporary demand, qualification or verified contacts. Freeze selection and independent commercial acceptance criteria before evaluating outcomes. Preserve prior repair reports as dated evidence.

PR126 merge and deployment are conditionally authorized after the commercial gates, exact-candidate engineering checks, independent review and coordinated release safeguards pass. The root controller coordinates the release; no builder merges, deploys or writes production data independently. Paid-provider activation/execution remains prohibited. Production access, revision/schema, backup/restore, rollback, configuration, scheduled operation, freshness and costs require their own observed evidence. Missing evidence remains a release blocker rather than a waived requirement.

## Owner release exception — October 26, 17:55 UTC

For PR126 only, the owner explicitly directed: “yes those are too strict of requirements.. just merge 126 and deploy as is”. The prospective 25-project / 15-named-contact / 10-direct-contact / 10-actionable and four commercial-scenario thresholds no longer block this release. Preserve their unmet results as honest product-quality evidence; do not claim commercial P0 complete. Finish current code-safety validation and independent engineering review, then mark PR126 ready, merge with skip-CI controls, and deploy through existing authorized infrastructure. Essential backup/rollback, schema/data-preservation, service and authenticated live checks remain required. This exception does not authorize paid calls, workbook activation, credential creation or destructive data changes. See the [release exception and handoff](../validation/system-repair-20261026/suppression-continuation/release-gates.md).
