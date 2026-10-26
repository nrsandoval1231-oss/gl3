# Autonomous intelligence architecture and retention map

Authority: [Autonomous Intelligence Canon](../product/AUTONOMOUS_INTELLIGENCE_CANON.md). This describes implementation boundaries and required acceptance; it does not certify a deployed candidate. Source files and migrations remain authoritative for exact runtime behavior.

See the [path-level migration inventory](autonomous-migration-inventory.md) for each KEEP/TRANSFORM/REMOVE/ARCHIVE decision, removed-feature dependencies and verification obligations.

## Processing boundaries

The existing API, Python worker and React application share PostgreSQL domain/evidence projections. Source adapters retrieve permitted artifacts; ingestion retains Source → Observation → immutable Evidence, conservative physical Project and separate PowerNeed. Company identity groups supported accounts without collapsing distinct project sites. Research and enrichment retain source-backed claims and unresolved outcomes; deterministic rules analyze activity-specific supply/demand, tier and gap. Explainable ranking and browse publication expose current accepted intelligence. Existing queued jobs, leases/fences, checkpoints and planner state support repeatable refresh independently of a user's browser or device.

Each stage must retain the current accepted result when retrieval, extraction, budget, provider or source access fails. Missing supply is unknown, never zero. Contact source membership and publisher ownership must be checked separately from a person's role or package buying responsibility. Public-source verification is not deliverability verification. Repeated unchanged content must reuse evidence and logical work identities without buying duplicate provider calls.

## Dependency and data-retention decisions

| Area | Retire from the product | Preserve / autonomous consumer |
|---|---|---|
| Web workspace and generated clients | Call logging, note/status updates, fact drafts/decisions/corrections, manual qualification, question/owner-review/watch entry forms | Read-only opportunities, automated research, Signals, unified search, sources and authenticated historical evidence |
| Public API / OpenAPI | User-operated mutation routes and schemas used only by those routes | Current reads, search, auth and internal machine processing; generated types must match mounted routes |
| `domain/call_facts.py`, qualification and ingestion | New user-operated data-entry capability | Retained historical fact validation/projection and deterministic reassessment where still consumed |
| CallFactVersion / Decision; workflow-status events; Pursuit / Note | Public creation/update workflows | Existing rows, source attribution, immutable decision and audit history; no table/data drops |
| `intelligence/pursuit_questions.py`, `domain/pursuit_research.py` | Dependence on user question or status to schedule research | Bounded eligible-category planning, freshness, unresolved outcomes, retries and source-supported findings |
| `intelligence/company_contact_discovery.py`, `company_contacts.py` | Manual enrichment requirement or benchmark-file import as accepted fact | Scheduled source-backed discovery, own-company membership, relevant-role attribution, method freshness and explicit missing contacts |
| `jobs/worker.py`, durable queue/planner state | Browser-triggered progress or duplicate per-replica planning | Scheduled incremental ingestion/research/enrichment, bounded retries, durable coordination, source health, costs and heartbeats |
| Existing migrations and saved-browse triggers | Destructive cleanup of historical workflow schema | Original schema/data compatibility, preserved history, current read projections and invalidation rules |
| Dated reports, benchmark CSVs and screenshots | Treating historical results as active requirements or fresh intelligence | Original evidence, exact candidate/environment context, clearly disclosed evaluation inputs |

Removing a public route does not authorize removing a persistence service that also ingests machine evidence. Conversely, retaining a legacy model does not justify exposing a manual workflow. Test the actual mounted API and browser flow as well as preserved read/assessment behavior.

## Upstream intelligence imports and graph

PR #125 adds immutable workbook/CSV staging and reversible import activation, canonical company/project graph reads, imported assertions, a durable incremental company scan cursor, and exact-scope power projections. These capabilities are retained. Import staging is an operations migration utility, never a customer fact-entry dependency; imported methods remain explicitly unverified and cannot award qualification or replace accepted source-backed contact methods. Historical contact corrections and relationship assertions remain readable with their original provenance, without public mutation routes or manual-only write services. The source-preserving additive migrations 0042–0044 are unchanged from upstream.

The company scan reuses canonical identities and bounded queued jobs. Evidence/input digests, supported timing and research priorities guide refresh; they do not turn campus demand into a residual rental gap. Current-method checks, thirty-day refresh, retry intervals, per-planner locking and source failure receipts remain in force after integration.

## Commercial and operational controls

TX/OK/NM physical-site eligibility, the inclusive 300 kW visibility floor, original Signal/Prospect/Lead gates and source scope apply at admission, indexed queries and exports. Company headquarters and source geography do not establish site eligibility. Facility load, activity-specific demand, committed suitable supply and residual gap remain distinct. Confidence, priority and commercial disposition are separate outputs with reasons and current citations.

Apollo and Firecrawl integrations depend on permitted account access, configured credentials, provider terms and bounded cost controls. Missing integration or budget is an explicit unresolved state. Historical benchmark contact details may be used as evaluation evidence with provenance; they are not a feed of verified current contacts. No source-backed method or buying authority is invented to increase coverage.

## Verification and deployment boundary

Verify job replay/interruption and multi-replica planning, research-category fairness, contact attribution/freshness, same-company distinct-site resolution, deterministic gap/tier/ranking, auth, retired routes, generated API types, search and mobile usability. Final receipts must bind exact commits and clearly separate synthetic fixtures, retained-data replay, actual source checks and deployed operation. Production health, credential/budget availability, paid cost and PC-off scheduling remain unverified until observed in that environment. The [Finish Contract](../../.agent/FINISH_CONTRACT.md) retains separate commercial launch gates.
