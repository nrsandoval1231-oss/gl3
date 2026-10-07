# GridLens — Clean-Sheet Product Requirements Document

**Version:** 1.0  
**Date:** September 24, 2026  
**Product owner:** Nick Sandoval  
**Status:** Initial specification for the new build  
**Scope:** Nationwide power-need discovery, daily ingestion, and evidence-based qualification  
**Numbered requirements:** 42

## Executive summary

GridLens finds projects across the United States that may need temporary or supplemental power, investigates the requirement, and helps a commercial user pursue the opportunity.

The system collects broadly every day, maintains one evolving record per project, and organizes individual power needs into **Signals, Prospects, and Leads**. Data center construction and commissioning receive default priority. All industries remain eligible, including manufacturing, mining, oil and gas, EV charging, utilities, commercial construction, and remote infrastructure.

Users can work every tier. A Signal offers a reason to make a discovery call. A Prospect has an established power requirement and evidence that suitable supply may be insufficient. A Lead has an evidence-supported remaining power requirement, MW range, start window, and duration range.

The product's core loop is:

**Discover → preserve evidence → match project → investigate power need → qualify → prioritize → act → update.**

This is a new implementation in a new repository and database. Existing GridLens code, schemas, pipelines, tests, and architecture are excluded. Decisions agreed in the current product discussion define this specification.

## Vertical lifecycle intelligence

The canonical vertical/asset lifecycle doctrine is [Vertical Lifecycle Intelligence Strategy](VERTICAL_LIFECYCLE_STRATEGY.md). GridLens optimizes for earliest actionable awareness of a future power requirement, not permit collection. Source events must be interpreted relative to asset lifecycle. Data centers prioritize pre-permit discovery and construction/commissioning monitoring. Upstream O&G uses drilling and subsequent milestones to estimate the future production/electrification window. Fixed O&G infrastructure retains project-formation → regulatory/permitting → construction → commissioning/startup lifecycle intelligence. Commercial tier remains separate from lifecycle state, and deterministic qualification gates remain authoritative.

## Frozen application UI

The approved visual and interaction direction is [the frozen UI canon](../design/UI_CANON.md), with the [browse](../design/references/browse.webp) and [detail](../design/references/detail.webp) reference screens. Visual examples are fictional. Product and evidence requirements in this PRD govern actual values and tier behavior.

## Product outcomes

### Owner-authorized acquisition priorities — October 1, 2026

Priority geographies are **Dallas, Austin, Houston, El Paso, and California**. These guide source onboarding, coverage repair and investigation effort; they do not exclude other United States geographies or disable existing feeds. California is a statewide priority, with actual coverage stated separately for each city, district or state source.

Commercial activity priority is **(1) data-center construction temporary power, (2) data-center commissioning temporary power, (3) oil and gas temporary power**. Early project formation evidence remains useful to those activities. Commissioning must have its own supporting evidence; construction or a generator permit alone does not establish commissioning.

Include official **flare-gas permits and flaring/venting exceptions** in oil-and-gas ingestion where records can be acquired reproducibly. Preserve applications, authorizations, amendments, expiration and reported operational events distinctly. An authorization is not proof of actual flaring, recoverable gas, continuous flow, gas composition, fuel suitability, generator capacity, an open power package or purchasing authority. Broad national and cross-industry collection remains enabled. These are owner priorities, not a claim that every requested source is already implemented or that runtime ranking has changed.

### Owner-authorized presentation amendment — October 1, 2026

- Remove the standalone Cannabis Watch view and its topic-match API behavior. Retained cannabis industry source evidence and supplemental news remain available in the ordinary ingestion inbox; only dated, site-identifiable official cultivation applications may be admitted as Signals.
- Use a project company as the displayed title when current project-specific evidence supports its role. Prefer owner/operator roles to contractors, label applicants as applicants, and label contractors as contractors. When a company is unknown, use an activity-and-site title rather than a permit-system label. Preserve source titles and identifiers as evidence.
- Apply an inclusive 300 kW (0.3 MW) minimum to visible opportunities, with no maximum. Retain unknown-size Signals with an explicit unknown-size label; hide confirmed below-floor work from opportunity views while preserving its raw evidence and history. Interpret only activity-specific values; ignore campus totals and nameplate or operating capacity when assessing a temporary-power work scope. A small generator replacement remains below the commercial floor without creating a rental-demand claim.

| Outcome | Meaning |
|---|---|
| Reliable daily discovery | New information arrives without Nick manually starting collection. |
| Broad visibility | Relevant national sources and expanding regional sources cover multiple industries; coverage limits remain visible. |
| Useful at every tier | Signals and Prospects can support calls before a complete gap estimate exists. |
| Defensible Leads | MW, timing, and remaining supply are traceable to evidence and explicit assumptions. |
| Commercial relevance | Each opportunity identifies the power activity, likely buying party, and useful next action. |
| Simple operation | One workspace, a small application architecture, and visible source health. |

## Primary user and daily journey

Nick is the initial user. The first release supports an authenticated private workspace; public subscriptions and multi-customer administration are later product decisions.

Nick opens GridLens and sees important overnight changes and ranked power needs. He can browse Signals, Prospects, or Leads, filter by location and activity, open evidence, identify the likely owner or contractor, and record what he learns on a call. That information updates the same opportunity and can change its tier or priority.

The short morning list is a convenience. All active records remain searchable and available in their tiers.

## Vocabulary and qualification

| Term | Definition |
|---|---|
| Source | A specific external dataset, publication, feed, portal, or discovery query that GridLens checks. |
| Observation | A dated piece of information retrieved from a source. |
| Project | A physical development, facility, or identifiable activity at a location. |
| Power need | A particular activity requiring power within a project, with its own load, timing, supply, and buyer. |
| Evidence | A sourced claim attached to a project or power need, including attributed user confirmations. |
| Signal | A sourced event creates a plausible reason to investigate a power need. |
| Prospect | A power requirement is established and evidence suggests suitable supply may be insufficient when required. |
| Lead | Evidence supports an unresolved power need with MW, start, and duration ranges. |
| Priority | How urgently and usefully the user can pursue the opportunity. Independent of tier. |
| Pursuit status | User workflow state: New, Investigating, Contacted, Qualified, Won, Lost, or Closed. Independent of tier. |

**Illustration only:** A campus with an eventual 200 MW operating load might have a 2–4 MW construction need and a separate commissioning requirement. Campus capacity is never automatically treated as either requirement. Different needs on the same project can occupy different tiers.

## Product requirements

### Foundation and scope

1. **Fresh implementation.** Create a new repository and new database. Author the implementation and tests from this specification. Do not import old GridLens application code, schemas, migrations, pipeline configuration, or architecture. Leave existing repositories untouched.

2. **National, cross-industry scope.** Accept relevant projects anywhere in the United States and across industries. Default acquisition and rankings prioritize data-center pre-permit formation, construction and commissioning, plus asset-aware O&G production and fixed-infrastructure intelligence. Geography, industry, and activity preferences change what users see and how it is ranked; they must not silently stop national collection.

3. **Private, usable first release.** Provide an authenticated web application and automated cloud execution that continue when Nick's computer is off. Keep read access, edits, source administration, and private notes protected by server-side authorization.

4. **Simple application structure.** Use one backend codebase with an API process and a worker process, a web frontend, PostgreSQL, and object storage for source artifacts where permitted. Implement collection and research jobs through a durable PostgreSQL job table and a managed scheduler. Add infrastructure only when a measured limitation requires it.

### Daily ingestion and discovery

5. **Source registry.** Maintain a versioned registry with a stable source ID, owner/publisher, source URL or endpoint, source family, geography, industries, retrieval method, credential reference, check cadence, expected publication cadence, parser, enabled state, and access/retention notes. A source is production-ready only after a real retrieval, parse, persistence, and repeat-run check succeeds.

6. **Daily execution.** Check each enabled production source at least once per day, subject to its documented access limits. Target the morning refresh for 7:00 a.m. America/Chicago, with a configurable user timezone. Report partial coverage when a source cannot be checked; do not block all other sources while one fails.

7. **Two collection jobs.** Run broad discovery for new projects and targeted monitoring for existing active projects. Monitoring follows known project sources and unresolved questions. Record when an observation was first seen, when the source published it, and when its described event occurred, where those dates are available.

8. **Multiple source families.** Support structured APIs/files, public web pages and feeds, and public documents such as PDFs. Cover national industrial/regulatory data, corporate and contractor announcements, construction/permit records, utility/regulatory material, and news/discovery. Use direct structured access where practical and Firecrawl for appropriate web extraction. Cleanview's paid API is excluded.

9. **Evidence preservation.** Persist source identifiers, retrieval time, content hash, permitted source artifact or excerpt, and extraction location such as page or section. Link claims to that evidence. Republishing articles does not form part of the product; retain content according to source access and retention rules.

10. **Reliable, economical runs.** Use checkpoints, bounded retries with backoff, timeouts, job leases, and idempotent writes. Fetch incrementally or detect unchanged content where supported. Do not repeatedly send unchanged documents to an LLM. Interrupted jobs must resume safely without duplicating observations or project cards.

11. **Visible source health.** Show last attempt, last successful check, source publication date when known, new/changed record counts, parse failures, and error reason. Distinguish Checked—No Change, Updated, Failed, and Overdue. An HTTP success with a broken parser or unexpected empty result does not count as a verified successful refresh.

12. **Coverage and budget controls.** Display live collection coverage by source family, geography, and industry. Keep planned, disabled, manual-import, and active automated sources distinct. Track retrieval and model usage against configurable daily limits. When a limit pauses work, expose the pause and backlog; preserve the last valid data.

### Project matching and investigation

13. **One evolving project.** Match observations using stable identifiers, site/location, names and aliases, developer, and explicit source relationships. Keep matching reasons and confidence. Similar company names alone are insufficient. Ambiguous records remain separate candidates until evidence supports a merge.

14. **Separate power needs.** Attach multiple power needs to a project: construction, commissioning, bridge, operational supplemental, backup/emergency, or another explicitly described activity. Each need owns its tier, load, schedule, supply assessment, evidence, and buyer relationships. Do not apply campus totals to an individual activity without supporting evidence.

15. **Evidence-guided investigation.** For relevant Signals and Prospects, automatically research missing facts about load, dates, supply, project identity, and buying responsibility. Bound each research job by query, time, and spending limits. Persist findings or a documented unresolved result; routine evidence processing must not require owner approval.

16. **AI and code responsibilities.** Use LLMs for document interpretation, candidate classification, assisted matching, research, and explanations. Require structured output and citations to retrieved evidence. Use deterministic code for validation, unit conversion, dates, arithmetic, tier gates, priority rules, and persistence. Treat external text as data; it cannot authorize actions or alter system rules.

17. **History and corrections.** Preserve prior accepted claims and the evidence behind them. Record replacements, corrections, merges, splits, and their reasons. Show material changes to load, dates, supply, contractor, tier, or status. Repeated reporting of the same underlying claim must not count as independent corroboration.

18. **Negative and aging evidence.** Incorporate cancellations, permit denials, missed milestones, contradictory facts, and secured supply. Reassess affected tiers and priority. Treat a source outage separately from project inactivity. Retain historical evidence; use activity-specific review intervals to identify stale claims instead of deleting all projects after a fixed age.

### Qualification and power-gap calculation

19. **Signal gate.** A visible Signal requires a dated, linked source; an identifiable company, project, or site; and a concrete explanation of how the event could create a power need. Unknown fields are permitted. A generic company directory entry alone is insufficient.

20. **Prospect gate.** A Prospect requires evidence of an actual power requirement and a separate supported reason that suitable supply may be late, insufficient, inaccessible for the activity, or otherwise unsuitable. Unknown utility availability alone is insufficient for promotion. Preserve the specific facts still needed to establish a Lead.

21. **Lead gate.** A Lead requires a supported power activity and location, required MW range, start window, duration range, and an explained unresolved supply gap. Show a likely buying organization or role and next action; a named individual is helpful but not mandatory. A known fully awarded package is excluded from open pursuits unless a distinct remaining need is evidenced.

22. **Evidence labels.** Label material inputs Reported, User-confirmed, Inferred, Derived, or Unknown. Retain their sources, dates, and basis. Use Low, Medium, or High confidence with published rubrics. Confidence reflects evidence support; it is not a probability. Tier promotion depends on required facts, not a single confidence score.

23. **Scope-specific arithmetic.** For each applicable time interval, calculate remaining MW as the greater of zero and required MW minus suitable available supply. Evaluate construction and commissioning against the supply usable for those activities. Preserve unit and date precision, input versions, scenario assumptions, and calculation version.

24. **Supply realism.** Separate operating/available supply, credibly committed future supply, proposed supply, and hypothetical options. Avoid counting the same supply twice. Do not treat a permit application, gas pipeline proximity, battery power rating, or flexible service offer as proof of adequate continuous power. Subtract only supply supported for the relevant date, duration, and service requirements; show alternatives as labeled scenarios.

25. **Ranges and uncertainty.** Use MW and date ranges where evidence is approximate. Compute scenarios explicitly rather than combining incompatible extremes. If unknown supply or dates prevent a defensible range, retain the appropriate lower tier and identify the missing evidence. Show phased changes where needed; do not build a power-flow or dispatch simulator.

26. **Requalification.** Recompute affected power needs when accepted evidence changes. Allow promotion, demotion, and closure, with an explanation and history. A cancellation, confirmed adequate supply, or expired need must leave the active pursuit list while remaining searchable in history. Material unresolved contradictions block promotion.

### Priority and commercial workflow

27. **Explainable ranking.** Rank active needs using opportunity timing, recent material change, evidence strength, product fit, and purchasing accessibility. Default activity preference favors data center construction and commissioning, but strong opportunities elsewhere remain eligible. Publish the initial rule weights and show the principal ranking reasons. Do not rank solely by campus MW or tier.

28. **Buying responsibility.** Associate relevant owners, developers, GCs, EPCs, electrical contractors, commissioning firms, or procurement roles with the specific power need. Identify who may buy or influence that package, with evidence and uncertainty. Prioritize direct users and responsible project contractors; exclude rental intermediaries as pursuit targets by default.

29. **Contacts and next action.** Surface sourced business contact information when available, including when and where it was found. Never fabricate an email, phone number, named buyer, or verified responsibility. Every visible opportunity provides a specific next question or action based on its missing facts and timing.

30. **User feedback.** Allow notes, attributed factual corrections, source attachments/links, pursuit status, and follow-up dates. Store who supplied a fact and when it was confirmed. Recalculate from accepted corrections. User workflow status does not automatically promote evidence tier; confidential notes remain private.

### User experience

31. **Three primary views.** Make Signals, Prospects, and Leads the main navigation. Offer search plus filters for geography, industry, power activity, timing, known MW, priority, and pursuit status. Retain unknown values as filterable values rather than treating them as zero.

32. **Morning changes.** Show a compact digest of newly discovered, promoted, materially changed, and closed opportunities, plus collection health. Repeated unchanged records must not masquerade as fresh discoveries. The digest links into the complete working lists.

33. **Opportunity detail.** Show company/project/location, power activity, tier and reason, what changed, MW and timing, suitable supply, remaining gap, likely buyer, next action, and evidence. Expand technical details on demand. Display an explicit missing-evidence checklist for lower tiers.

34. **Practical access.** Support desktop and mobile browser use, responsive detail views, keyboard navigation, readable type, and clear loading/empty/error states. Provide CSV export of selected opportunities with tier, evidence links, and estimate labels preserved. Exports and all routes respect authentication.

### Operations and verification

35. **Durable cloud operation.** Deploy the scheduler, worker, API, database, and document storage independently of Nick's PC. Record run IDs and timestamps. Store secrets in the deployment secret store; keep credentials and source content out of application logs and the repository.

36. **Recovery and visibility.** Maintain database backups and a documented restore procedure. Provide failure alerts for overdue daily collection and material processing failures through a configured owner channel. An unavailable LLM service must leave collected evidence intact and research queued for retry. Reconcile abandoned worker jobs after a crash.

37. **Useful tests.** Test duplicate replay, wrong-project matches, phase/load confusion, citation validation, unit/date conversion, uncertain supply, tier gates, demotion, canceled projects, scheduler failures, interrupted jobs, and authorization. Use representative stored fixtures and a small set of actual-source smoke checks. Test counts alone are not completion evidence.

38. **Live source readiness.** Before launch, demonstrate at least 12 independent active source feeds across at least five source families, including at least two national structured sources. Produce real relevant Signals across at least three industries. Search query variants against one publication do not count as independent feeds. This is a proposed launch minimum, not a claim of exhaustive national coverage.

39. **Qualification review.** Review a retained sample of 30 independently discovered Signals/Prospects. Target at least 24 with the correct project identity, source-supported event, and defensible reason to investigate power. Review every initial Lead against all Lead-gate fields. Fix errors and re-review; never promote incomplete records to meet a volume target.

40. **Operational launch gate.** Complete seven consecutive scheduled daily runs with at least 95% of due source checks verified successful overall, no source missed for two consecutive daily cycles without a visible alert, and no unreported failures. Demonstrate restart/replay, restore, and mobile/desktop use. Show daily cost and backlog alongside freshness.

41. **End-to-end commercial proof.** Independently discover and substantiate at least one real Lead, reviewed by Nick against original evidence or an attributed customer confirmation. Track discovery time, missing facts, qualification time, and next action. If public evidence supports only Signals/Prospects, release that usable capability honestly and keep Lead capability acceptance open.

42. **Scope discipline.** Deliver this PRD through the milestones below. Document changes in a short decision log. Defer equipment marketplaces, detailed solution engineering, power-flow models, portfolio finance, advanced ML probabilities, automated outreach, full CRM, and multi-customer billing. Expand sources and improve qualification using observed results.

## Source acquisition plan

The following are candidate source families for validation during implementation. These are discovery starting points, not assertions that an endpoint, license, daily publication schedule, or adapter has already been verified. Each production feed must pass Requirement 5.

| Source family | Candidate examples | Value to GridLens | Interpretation boundary |
|---|---|---|---|
| National industrial/regulatory data | EPA facility/environmental records; SEC EDGAR filings; EIA project data | Facilities, expansion activity, disclosed schedules and power arrangements | A facility or generating asset is not automatically a load-side rental opportunity. |
| Construction and permits | State construction registries, city/county permit portals, planning agendas, environmental permits | Project identity, construction milestones, equipment and site details | A permit is evidence of a proposal or authorization, not delivery or operation. |
| Company and contractor publications | Developer/owner news, GC/EPC awards and portfolios, electrical-contractor project pages | Project activity, awarded roles, scope and timeline | Company capability does not establish involvement in a particular project. |
| Utility and regulatory material | Utility project announcements, service filings, state commission dockets, ISO/RTO data where relevant | Service timing, constraints, utility work, explicit load evidence | Generation queues and regional congestion do not establish a specific customer's service date. |
| National and local discovery | Public news feeds, targeted searches, economic-development announcements | Early events and source discovery across industries | Syndicated stories share an underlying source and must not inflate confidence. |

**Expansion order:** Establish national discovery and priority construction/commissioning feeds together. Add local and regional sources where actual opportunities or coverage gaps justify the effort. Evaluate each source by unique useful observations, freshness, qualification contribution, failure rate, and cost. Recheck active sources daily while respecting their publication cadence.

## Lean technical design

These are implementation decisions for the initial build. Pin supported dependency versions when scaffolding.

| Component | Initial choice | Responsibility |
|---|---|---|
| Web UI | React + TypeScript | Lists, opportunity detail, notes, source health |
| Backend | Python + FastAPI | Authenticated API and domain services |
| Worker | Same Python package, separate process | Collection, extraction, matching, research, recalculation |
| Database | PostgreSQL; SQLAlchemy + Alembic | Domain data, evidence metadata, history, durable jobs |
| Source artifacts | Managed object storage | Permitted documents, snapshots, excerpts |
| Scheduling | Managed cloud scheduler | Enqueue daily and targeted refresh jobs |
| Extraction | Source-specific code plus Firecrawl where appropriate | Structured records and web/document extraction |
| AI | One provider adapter with schema validation | Bounded interpretation and research |
| Deployment | Containerized API/worker, managed database, hosted frontend | Always-on operation and repeatable deployment |

Choose the hosting provider during foundation setup based on cost, reliable scheduling, secret management, and backups. No purchase is authorized by this document. No graph database, microservice fleet, or separate workflow platform is required for the first release. Relationships and history fit in PostgreSQL.

### Data ownership

| Entity | Key contents | Relationships |
|---|---|---|
| Source / SourceRun | Coverage, cadence, health, counts, failure, cost | Source → many runs → observations |
| Observation | Source ID, publication/event/retrieval times, hash, artifact reference | Supports extracted evidence |
| Project | Name/aliases, site/location, industry, lifecycle | Has organizations and multiple power needs |
| PowerNeed | Activity, load/time ranges, qualification, supply inputs, status | Belongs to a project; references evidence |
| Evidence | Claim, value/unit, label, confidence basis, citation, effective interval | Supports or contradicts project/need fields |
| Organization / Contact / Role | Name, sourced contact details, project-specific role | Linked to project and/or power need |
| Assessment / Change | Inputs, rule version, outputs, previous state, reason | Versioned qualification and gap results |
| Pursuit / Note | User status, action, follow-up, attributed feedback | Associated with a power need |
| Job | Type, payload, lease, attempts, checkpoint, status | Durable execution and crash recovery |

These are logical entities; use ordinary tables and small association tables. Supply inputs can be a simple child table or validated structure initially. Avoid a configurable ontology framework.

### Processing and failure behavior

Each source job fetches and checkpoints observations independently. Validation produces accepted claims or unresolved extraction results. Matching attaches accepted claims to projects and needs; qualification recalculates only affected needs. UI reads the latest accepted assessment and its history. Partial extraction must not silently replace complete records with blanks.

If research stops because of a budget, model outage, or source restriction, collected evidence remains available. The record displays its existing tier and unresolved questions. Retrieval dates never replace original publication dates to make an old event appear new.

## Organized repository folder tree

**Repository name:** `gl3`. This new repository has no dependency on any old GridLens repository.

The tree is the intended organization. Create modules when their milestone needs them; empty directories and placeholder services are not deliverables.

```text
gl3/
├── README.md                         # Purpose, quick start, production commands
├── AGENTS.md                         # Builder scope, working rules, verification
├── .env.example                      # Variable names and safe examples only
├── .gitignore
├── Makefile                          # install, dev, test, lint, migrate, refresh
├── compose.yaml                      # Local PostgreSQL/API/worker development
│
├── docs/
│   ├── product/
│   │   ├── PRD.md                    # This document; product authority
│   │   ├── qualification.md          # Exact tier gates and evidence examples
│   │   └── priority.md               # Ranking rules, weights, explanations
│   ├── architecture/
│   │   ├── overview.md               # Processes, boundaries, data flow
│   │   └── data-model.md             # Entities, relationships, constraints
│   ├── sources/
│   │   ├── coverage.md               # Actual coverage and known gaps
│   │   └── onboarding.md             # How to validate and add a feed
│   ├── operations/
│   │   ├── deployment.md             # Cloud setup and rollback
│   │   ├── daily-refresh.md          # Schedule, health, retry/replay
│   │   └── recovery.md               # Backups, restore, worker recovery
│   ├── delivery/
│   │   ├── milestones.md             # Gates, current state, next work
│   │   └── launch-review.md          # Real-source and commercial evidence
│   └── decisions.md                  # Short dated decisions with reasons
│
├── config/
│   ├── sources/                      # Validated feed definitions; no secrets
│   │   ├── national.yaml
│   │   ├── construction.yaml
│   │   ├── corporate.yaml
│   │   ├── utility.yaml
│   │   └── discovery.yaml
│   ├── qualification.yaml            # Versioned tier/evidence rules
│   ├── priority.yaml                 # Default preferences and ranking weights
│   └── operations.yaml               # Cadences, timeouts, budgets, thresholds
│
├── backend/
│   ├── pyproject.toml                # Python dependencies and tooling
│   ├── uv.lock
│   ├── alembic.ini
│   ├── migrations/                   # Database changes; reviewed and versioned
│   ├── src/gridlens/
│   │   ├── api/
│   │   │   ├── main.py               # API entry point
│   │   │   ├── auth.py               # Authentication/authorization dependencies
│   │   │   └── routes/               # opportunities, projects, notes, sources
│   │   ├── domain/
│   │   │   ├── schemas.py            # Shared validated domain contracts
│   │   │   ├── qualification.py      # Signal/Prospect/Lead decisions
│   │   │   ├── power_gap.py          # MW/date scenarios and calculations
│   │   │   └── priority.py           # Deterministic ranking and explanations
│   │   ├── ingestion/
│   │   │   ├── registry.py           # Load and validate source definitions
│   │   │   ├── runner.py             # Fetch/checkpoint/retry source jobs
│   │   │   ├── adapters/             # Publisher-specific retrieval code
│   │   │   └── parsers/              # Structured, HTML and document extraction
│   │   ├── intelligence/
│   │   │   ├── matching.py           # Project/site identity and merge candidates
│   │   │   ├── research.py           # Bounded missing-fact research jobs
│   │   │   ├── evidence.py           # Claim validation, conflicts, attribution
│   │   │   └── updates.py            # Apply evidence and recompute affected needs
│   │   ├── integrations/
│   │   │   ├── firecrawl.py          # Web extraction client
│   │   │   ├── llm.py                # Model calls, schema checking, usage
│   │   │   ├── storage.py            # Source artifact storage
│   │   │   └── alerts.py             # Configured owner notifications
│   │   ├── persistence/
│   │   │   ├── database.py           # PostgreSQL connections and transactions
│   │   │   ├── models.py             # Database tables and constraints
│   │   │   └── queries.py            # Shared reads/writes
│   │   ├── jobs/
│   │   │   ├── worker.py             # Worker entry point
│   │   │   ├── queue.py              # Leases, retries, idempotency, recovery
│   │   │   └── schedules.py          # Due sources and targeted refresh planning
│   │   ├── prompts/                 # Versioned extraction/research templates
│   │   └── settings.py              # Runtime configuration and secret references
│   └── tests/
│       ├── unit/                     # Calculation, qualification, ranking rules
│       ├── integration/              # Persistence, APIs, adapters, job recovery
│       ├── acceptance/               # End-to-end product requirements
│       └── fixtures/                 # Small permitted samples and adversarial cases
│
├── web/
│   ├── package.json
│   ├── package-lock.json
│   ├── index.html
│   ├── src/
│   │   ├── app/                      # Shell, routes, authentication
│   │   ├── features/
│   │   │   ├── opportunities/        # Three tiers, filters, detail, next actions
│   │   │   ├── morning/              # Important changes and daily digest
│   │   │   ├── pursuits/             # Notes, statuses, follow-up
│   │   │   └── sources/              # Health, freshness, coverage
│   │   ├── components/               # Reusable UI primitives
│   │   ├── api/                      # Generated API types and thin client
│   │   └── styles/                   # Design tokens and shared styles
│   └── tests/                        # Critical browser journeys and accessibility
│
├── scripts/
│   ├── refresh.py                    # Enqueue a manual/daily refresh
│   ├── check_sources.py              # Real source readiness checks
│   ├── replay_observations.py        # Reprocess evidence without refetching
│   └── export_review_sample.py       # Qualification review evidence
│
├── deploy/
│   ├── Dockerfile.api
│   ├── Dockerfile.worker
│   └── scheduler.yaml                # Selected cloud scheduler configuration
│
└── .github/workflows/
    └── ci.yml                        # Lint, types, meaningful tests, build
```

### Folder ownership rules

| Location | Owns | Boundary |
|---|---|---|
| `docs/product/PRD.md` | Product requirements | Other documents explain implementation; they do not silently expand scope. |
| `config/` | Sources and transparent policy values | No credentials, scraped documents, or production data. |
| `domain/` | Qualification, calculations, ranking | No web fetching or LLM calls. |
| `ingestion/` | External collection and parsing | Emits observations; does not award a Lead tier. |
| `intelligence/` | Research, matching, evidence application | Calls domain logic for final decisions. |
| `integrations/` | Vendor-specific clients | Provider details remain behind these clients. |
| `persistence/` | Durable records and queries | Transactions protect partial updates and duplicates. |
| `jobs/` | Scheduling and reliable execution | Business rules live in domain/intelligence modules. |
| `web/` | Presentation and user actions | Uses backend decisions; does not recalculate tiers independently. |
| `tests/` | Behavioral evidence | Fixtures are identified as fixtures and never appear as live discoveries. |

Raw source documents, runtime exports, logs, secrets, and production database files stay outside Git. Production artifacts live in managed storage. Temporary developer files go in an ignored local directory. Generate frontend API types from the backend contract to avoid competing schema definitions.

## Delivery milestones and exit gates

| Milestone | Deliverable | Required proof |
|---|---|---|
| **A — Foundation** | New repository, PostgreSQL migrations, auth, API/worker, cloud scheduler, source registry | A real scheduled source check persists an observation while the owner's PC is off; secrets absent from Git. |
| **B — Daily Signals** | Multiple source families, preserved evidence, basic matching, live Signal list, health screen | Real national/cross-industry observations; replay creates no duplicate cards; parser and source failures are visible. Nick can start discovery calls here. |
| **C — Prospects** | Power-need separation, missing-fact research, evidence labels, Prospect gate, contractor roles | Correct identity and activity on reviewed records; unsupported utility uncertainty cannot promote a record. |
| **D — Leads** | MW/time scenarios, suitable supply assessment, Lead gate, history, demotion | An auditable real Lead when evidence permits; hypothetical tests establish calculations without masquerading as live findings. |
| **E — Daily working release** | Morning changes, search/filter/export, notes, follow-up, recovery and alerts | Requirements 38–41 reviewed: source breadth, sample quality, seven daily cycles, commercial proof, and backup restore. |

Complete and deploy usable milestones sequentially. Source onboarding can continue alongside later milestones through the same adapter interface. Preserve daily collection while improving qualification.

## Critical acceptance scenarios

| Scenario | Expected behavior | Requirements |
|---|---|---|
| The same source job is retried after a worker crash | No duplicate observation, project, need, or digest item | 10, 13, 36 |
| A site returns a login page or changes its table structure | Parse failure is visible; source does not receive a false success | 5, 11 |
| A monthly dataset has not changed during today's check | Last checked updates; publication date remains unchanged | 6, 7, 11 |
| Two similarly named projects are in different counties | They remain separate unless stronger evidence establishes identity | 13 |
| A campus reports a 200 MW eventual load | No automatic 200 MW construction or commissioning requirement | 14, 23 |
| Power need is documented but utility availability is simply unknown | Remains Signal; missing facts are identified for research/call | 20 |
| A construction package needs power before a documented energization window | Can advance as evidence supports activity, MW and duration | 20–25 |
| A new air permit proposes onsite generation | Records proposed supply; does not automatically erase the gap | 24 |
| A source changes its target date; another source disagrees | Both claims retained; uncertainty/conflict displayed | 17, 25, 26 |
| Utility power or another solution is confirmed adequate for the activity | Affected need is closed/downgraded with its history preserved | 18, 26 |
| Nick confirms dates and MW on a call | Attributed evidence updates the same need and recalculates its tier | 30 |
| A valuable non-data-center opportunity appears | It remains visible and can outrank a distant data center need | 2, 27 |
| Model API is unavailable | Ingestion persists evidence; research remains queued | 15, 36 |
| An unauthenticated visitor accesses a detail API or export | Private opportunity records and notes are inaccessible | 3, 34 |

## Success measurement

| Measure | Initial use |
|---|---|
| Verified successful due checks / all due checks | Reliability gate; overall success cannot conceal a repeatedly failing source. |
| Age of latest source check and latest source publication | Separates collection health from underlying data age. |
| Unique useful Signals by industry and geography | Measures discovery breadth and prevents a single feed from dominating apparent coverage. |
| Correct identity + supported event + plausible power relevance | Reviewed sample quality under Requirement 39. |
| Evidence completeness of Leads | All required Lead fields supported; no invented values. |
| Time from discovery to useful call or qualification | Measures practical commercial speed. |
| Daily operating cost and research backlog | Keeps wide collection economically manageable. |
| Calls made, needs confirmed, pursuits advanced | Tests whether GridLens helps actual business development. |

Source count, record count, and test count are supporting metrics. The release must satisfy both broad reliable ingestion and commercially useful output.

## Decisions to resolve during implementation

The product direction is settled. Remaining implementation choices are the cloud provider, initial cost ceiling, alert destination, authentication provider, exact first source feeds, and visual design tokens. Record selections in `docs/decisions.md`. Validate source access during onboarding rather than making unverifiable commitments in the PRD.

The build can begin with local development and source validation before purchases or new external account permissions are needed. The source-readiness and operating-cost evidence should inform those choices.

## Research used as design input

These references informed product patterns. They are not dependencies, complete technical specifications, or proof of competitor capabilities. This PRD does not import any old GridLens implementation decisions.

| Reference | Useful lesson |
|---|---|
| [Vavan product](https://vavan.ai/product) and [integration documentation](https://vavan.ai/docs/integrations) | Broad collection and matching records to shared real-world entities. |
| [Cleanview about](https://cleanview.co/about) and [data-center API documentation](https://docs.cleanview.co/api-reference/endpoint/data-centers) | Project tracking, lifecycle details, and source-linked records. Paid API excluded. |
| [GridGlasses methodology](https://gridglasses.com/methodology) and [sources](https://gridglasses.com/sources) | Changes over time, explicit uncertainty, source visibility, and buying responsibility. |
| [Shared research summary](https://chatgpt.com/share/6ab53816-17c4-83ea-ae48-12f636035d8e) | Evidence-driven power-gap reasoning, negative evidence, and keeping the first build focused. |

**Product promise:** Broad discovery every day. Useful opportunities at every tier. Power gaps with evidence you can inspect.

## October 4, 2026 amendment — bounded autonomous pursuit research

Commercial RESEARCH may schedule at most two specific missing-fact questions per
pursuit using existing Project/PowerNeed/evidence context. Research searches retained
evidence first, then bounded public sources, admits findings through canonical
evidence rules and invokes the existing deterministic commercial evaluator. It may
produce a changed pursuit or an explicit unresolved outcome. Fact, inference,
hypothesis, unknown, commercial status, evidence tier and project lifecycle remain
separate. ACTION NOW never substitutes for Prospect/Lead qualification.

Users must inspect prior context, the exact question, searched sources, accepted
and rejected evidence, remaining unknowns, before/after status and next action.
Request budgets, caching, freshness and at most one follow-up prevent unlimited
research. Models remain advisory; research performs no external commercial outreach.
This amendment preserves the existing qualification criteria: typed public reports
may resolve uncertainty but cannot independently promote a need. Current admitted
official evidence must satisfy the Prospect/Lead gates, and contradictions or
corrections can remove obsolete support. The candidate's local validation and unmet
original retained-corpus gate are recorded in the autonomous-research report;
it does not claim cloud deployment or production proof.
