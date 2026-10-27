# GRIDLENS GL3 — MASTER BUILDER DIRECTIVE
## Canonical Customer Intelligence, Project Consolidation & Autonomous Enrichment

**Current authority:** the owner-approved [Autonomous Intelligence Canon](AUTONOMOUS_INTELLIGENCE_CANON.md) supersedes manual workflow and older harness requirements. The later [Project-First Results Canon](PROJECT_FIRST_RESULTS_CANON.md) supersedes this document's company-first default browsing prescription; retain its compatible backend company identity, enrichment and evidence requirements. Compatible company/project identity, source provenance and commercial safeguards below remain in force.

**Repository:** `https://github.com/nrsandoval1231-oss/gl3`

**Production:** `https://app.grid-lens.com/`

**Priority:** Critical

**Objective:** Transform GridLens from a record-heavy permit discovery interface into a fast, intelligent, company-centric commercial opportunity platform.

---

# 1. THE PROBLEM

The current GridLens user experience is unacceptable for commercial prospecting.

After using the application for approximately two minutes, the owner observed:

1. The same company appears dozens or hundreds of times because separate permits become separate visible opportunities.
2. Electrical contractors and other subcontractors appear as customers rather than the actual companies developing, owning, or operating the projects.
3. Excessive raw permit information overwhelms the UI.
4. Valuable information contained in permits is not consistently consolidated into comprehensive customer intelligence cards.
5. There is insufficient proof that Jev and GPT Sol are actively performing their intended intelligence functions.
6. The interface exposes the complexity of evidence collection instead of delivering useful commercial conclusions.

**This is fundamentally an intelligence architecture and data presentation problem, not merely a visual design problem.**

Fix the entire data flow.

Do not simply hide duplicate rows with frontend filtering.

Do not delete historical evidence.

Do not solve this by changing labels.

---

# 2. TARGET PRODUCT EXPERIENCE

GridLens must operate as a commercial intelligence analyst specializing in temporary, bridge, commissioning and distributed generation opportunities.

The owner should open GridLens and immediately see:

- Which companies are worth pursuing.
- Which physical projects each company is developing.
- Why those projects might need temporary or distributed generation.
- Estimated MW requirements and supported uncertainty.
- When power may be needed.
- How long that need may last.
- Who controls purchasing decisions.
- How to contact the relevant people.
- The most useful next commercial action.

Raw documents, permits, ingestion records and evidence-processing details should remain behind the scenes.

**One company. Multiple projects. Multiple evidence sources. One coherent commercial intelligence profile.**

A physical project may have multiple separate power needs; preserve them without creating duplicate customer accounts.

---

# 3. CANONICAL ENTITY ARCHITECTURE

Inspect the existing database schema, ingestion pipeline, evidence graph, project matching, enrichment services, opportunity API, React components and all related tests before making changes.

Reuse existing capabilities and migrations wherever possible.

Implement the following conceptual hierarchy:

```text
CANONICAL ORGANIZATION / ACCOUNT
│
├── Company Identity
│   ├── Legal Name
│   ├── Display Name
│   ├── Known Aliases
│   ├── Parent / Subsidiary Relationships
│   └── Industry Classification
│
├── PROJECT A
│   ├── Project Identity / Location
│   ├── Owner / Developer / Operator
│   ├── General Contractor
│   ├── Electrical Contractor
│   ├── EPC / Engineering Firms
│   ├── Commissioning Contractors
│   ├── Power Requirements
│   ├── Project Timeline
│   ├── Buying Chain
│   └── Supporting Evidence References
│
├── PROJECT B
│   └── ...
│
├── PROJECT C
│   └── ...
│
├── ACCOUNT CONTACTS
│
├── COMMERCIAL ASSESSMENT
│
└── RECOMMENDED NEXT ACTION
```

A company is not a project.

A project is not a permit.

A permit is not a lead.

An electrical contractor is not automatically the customer.

A company can have multiple distinct projects. A single project can contain many permits, filings, sources and power requirements.

### Canonical identity rules

Use authoritative identifiers and deterministic matching first.

Use Jev to adjudicate bounded ambiguous cases where appropriate.

Do not merge unrelated physical projects just because they share a corporate parent.

Do not merge organizations based solely on a similar name.

Maintain traceable alias, ownership and entity relationship decisions.

Allow incorrect associations to be reviewed and corrected.

All consolidation must occur in the backend with durable, stable identities.

---

# 4. DIAMONDBACK ENERGY — REQUIRED EXAMPLE

Current unacceptable behavior:

```text
Diamondback — Permit 001
Diamondback — Permit 002
Diamondback — Permit 003
Diamondback — Permit 004
...
Diamondback — Permit 200
```

Required behavior:

```text
DIAMONDBACK ENERGY
Industry: Oil & Gas

Projects:
  Development Area A
  Development Area B
  Infrastructure Project C

Evidence:
  200 associated permit references

Commercial Intelligence:
  Potential generation requirements
  Supported MW estimates
  Activity timeline
  Project locations
  Natural gas suitability
  Relevant commercial contacts
  Recommended pursuit actions
```

The examples above are illustrative. Do not invent these specific projects or claim the 200 permits have been verified.

A newly discovered permit must update an existing account/project when appropriately matched.

It must not automatically create a new customer.

Different site-specific commercial power needs must remain distinguishable beneath the account.

Test this using actual retained Diamondback evidence if available.

---

# 5. DATA CENTER CUSTOMER IDENTIFICATION

Current unacceptable behavior:

```text
JCL ELECTRIC
Electrical Permit
Data Center Construction
```

If the actual supported owner/developer is Sabey Data Centers, the customer-facing identity must be:

```text
SABEY DATA CENTERS

Project:
  [Verified campus or facility]

Developer / Owner:
  Sabey Data Centers

General Contractor:
  [Source-backed company]

Electrical Contractor:
  JCL Electric

Engineering / EPC:
  [Source-backed company]

Commissioning Contractor:
  [Source-backed company]

Power:
  Required MW
  Available / committed utility MW
  Potential temporary generation gap
  Energization schedule

Buying Chain:
  Relevant decision makers
  Company
  Role
  Business email
  Business phone
  Source and verification status
```

Again, this is a required identity-resolution scenario, not permission to assume JCL Electric is associated with Sabey without source evidence.

Determine the actual developer, owner, operator and customer through source-backed research.

If the true customer cannot be established, mark the identity unresolved and research it. Do not substitute the permit applicant as the customer.

Preserve contractors as relationships and possible buying-chain participants.

---

# 6. PERMIT ENRICHMENT ENGINE

Permits are intelligence inputs, not the product interface.

For every relevant retained permit, extract as many legitimately supported commercial facts as possible:

**Identity**
- Company / developer / owner / operator
- Applicant
- Contractor
- Facility
- Project name
- Physical location

**Construction**
- Scope of work
- New construction versus expansion
- Electrical or mechanical infrastructure
- Generation-related equipment
- Project phase and milestones

**Power**
- Documented electrical demand
- Voltage and other useful electrical specifications
- Transformer or service capacity
- Proposed onsite generation
- Utility references
- Commissioning indications
- Fuel infrastructure references

**Timeline**
- Filing date
- Permit status
- Planned construction milestones
- Supported completion or energization dates
- Documented schedule changes

**Commercial**
- Named organizations
- Named people and source-stated roles
- Public business contact information
- Contracting relationships
- Potential purchasing pathway

Store extracted facts with citations, original source identifiers, extraction versions and confidence/status metadata.

Avoid unsupported assumptions.

**Every relevant permit should be evaluated for useful information, but not every permit requires an expensive LLM call.**

Use deterministic parsing, existing field extraction and batching first. Escalate ambiguous or complex material to Jev/Sol.

Retain raw documents and complete evidence in backend storage.

Ordinary account browsing must never download thousands of complete raw permit records.

The UI may display compact evidence summaries, relevant dates, document types and permit reference numbers, with optional drill-down.

---

# 7. JEV — REQUIRED RESPONSIBILITIES

Inspect all existing Jev integrations, contracts, routes, flags, worker jobs and stored execution results.

Jev should function as the fast structured judgment layer.

Responsibilities:

1. Evaluate incoming evidence relevance.
2. Identify possible duplicate or related organizations and projects.
3. Classify participant roles.
4. Detect material project changes.
5. Assess temporary/bridge/commissioning power relevance.
6. Prioritize commercially valuable research.
7. Route genuinely complex questions to deeper LLM reasoning.
8. Avoid redundant research against unchanged evidence.

Jev is not allowed to fabricate facts, silently merge companies, independently promote leads or mutate canonical truth without deterministic validation.

Its outputs must follow explicit schemas.

Every genuine invocation must record:

- Task type
- Candidate / project identifiers
- Actual provider and model
- Execution result
- Input/output provenance
- Latency
- Token usage and cost when available
- Validation outcome
- Fallback or error reason

Do not confuse an implemented integration with a working production integration.

Verify genuine execution.

---

# 8. GPT SOL — REQUIRED RESPONSIBILITIES

The intended deeper intelligence model is GPT Sol 6.1, subject to actual supported model availability and configured access.

Do not silently substitute a different model while presenting it as Sol.

Inspect existing OpenAI integration and provider routing.

The deeper intelligence service must be capable of:

1. Researching and reconstructing complex real-world projects.
2. Consolidating multiple evidence sources into a coherent project narrative.
3. Identifying the actual customer behind contractor-submitted documents.
4. Reconciling conflicting ownership, location, schedule and equipment information.
5. Finding corroborated buyer and decision-maker information.
6. Evaluating potential distributed generation needs.
7. Identifying missing commercial facts.
8. Producing concise, actionable intelligence for customer cards.
9. Recommending the next useful sales action.
10. Explaining why an opportunity is commercially relevant.

Use tools/retrieval only through configured, authorized interfaces.

The model must not invent identities, power requirements, MW gaps, dates or contacts.

Every factual claim must trace to source evidence.

Model conclusions are proposals until validated and accepted through the existing deterministic evidence governance.

If GPT Sol 6.1 is unavailable through the current integration, explicitly identify the blocker and report the actual configured model. Do not claim acceptance using a mock or fallback model.

---

# 9. CUSTOMER INTELLIGENCE CARD — REQUIRED FIELDS

Each consolidated account must produce a polished, useful card containing:

### Company overview
- Canonical organization name
- Industry
- Operating geography
- Website when verified
- Parent/subsidiary relationships
- Relevant associated projects

### Project intelligence
- Physical project name and location
- Development/construction phase
- Supported power needs
- Temporary versus permanent power context
- Construction or commissioning milestones

### Power opportunity
- Required MW or supported estimate/range
- Credible committed supply
- Residual power gap where calculable
- Estimated power need date
- Estimated duration
- Natural gas / propane fit
- Technical constraints
- Power application category

### Buying chain
- Verified or source-attributed decision makers
- Job titles
- Company affiliations
- Public business emails and phones where supported
- GC/EPC and electrical contractor relationships
- Contact confidence and source recency

### Commercial evaluation
- Qualification tier
- Opportunity priority
- Strength of supporting evidence
- Main opportunity drivers
- Material uncertainties
- Important changes since prior assessment

### Action
- Most valuable next step
- Specific research gaps
- Recommended person or organization to contact
- Read-only retained evidence and audit history; no manual notes/activity entry

### Evidence
- Supporting source count
- Compact source references
- Last evidence update
- Expandable details only when requested

Never fabricate a value to avoid an empty field.

Avoid overwhelming the UI with repeated UNKNOWN labels. Prioritize actionable information, use concise “Needs confirmation” indicators where necessary, and consolidate missing information into a research-gaps section.

Preserve the important distinction between supported facts, estimates, conflicts and missing information.

---

# 10. UI/UX REQUIREMENTS

Follow the existing approved GridLens brand kit and canonical UI design.

Preserve:

- Correct GridLens logo
- White/navy visual direction
- Existing approved fonts
- Minimal, professional layout
- Fast browsing
- Clear information hierarchy
- Responsive desktop/mobile views

Do not introduce a new design language, decorative photographs, unnecessary charts or additional navigation complexity.

### Main workspace

The primary opportunity browser must default to consolidated **company accounts**.

Each company row should contain:

- Company name
- Industry
- Project count
- Highest-priority power opportunity
- Supported MW/timing summary
- Qualification and next action

Selecting a company opens its intelligence profile.

Projects appear nested beneath that company.

Selecting a project reveals its detailed commercial assessment.

Evidence stays collapsed by default.

Preserve the ability to inspect individual power needs, source records and research history through secondary workflows.

Do not silently eliminate existing functionality.

---

# 11. PERFORMANCE REQUIREMENTS

Fix performance at the backend/query level.

Do not rely on client-side aggregation across thousands of permit rows.

Implement efficient server-side account summaries using appropriate relationships, indexed queries and bounded projections.

Requirements:

- Server-side pagination
- Efficient company search and filtering
- Precomputed/materialized summaries where justified
- Incremental enrichment and projections
- No N+1 evidence queries
- No full evidence retrieval for account list views
- No expensive live LLM execution in a normal browsing request
- Stable account and project IDs
- Explicit refresh and freshness states

Target fast interactive browsing and measure actual p50/p95 response times.

Do not claim performance improvements without baseline and after measurements on a representative data volume.

---

# 12. AUTONOMOUS OPERATION

GridLens must continuously improve its commercial intelligence as new evidence arrives.

Implement or properly connect the existing workflow:

```text
INGEST NEW EVIDENCE
        ↓
NORMALIZE + EXTRACT FACTS
        ↓
RESOLVE ORGANIZATION / PROJECT
        ↓
UPDATE CANONICAL EVIDENCE GRAPH
        ↓
DETECT MATERIAL CHANGE
        ↓
JEV JUDGMENT WHEN NEEDED
        ↓
SOL RESEARCH WHEN JUSTIFIED
        ↓
VALIDATE SOURCE-BACKED CLAIMS
        ↓
UPDATE PROJECT / POWER NEED
        ↓
REFRESH COMMERCIAL ACCOUNT CARD
        ↓
SURFACE MEANINGFUL CHANGE
```

Unchanged evidence must not repeatedly trigger expensive research.

Failed provider calls must not corrupt the account.

Jobs must be durable, retryable, idempotent and observable.

Respect existing source permissions, model routing, cost limits, concurrency controls and qualification rules.

Do not enable paid providers or change production credentials without explicit authorization.

---

# 13. ACCEPTANCE TESTING

Do not declare success after unit tests alone.

Create realistic end-to-end validation scenarios for:

**A. Diamondback consolidation**
- Multiple permits
- Multiple aliases
- Multiple physical sites
- Correct account grouping
- No duplicate customer rows

**B. Sabey / JCL identity**
- Contractor-submitted permit
- Correct customer where evidenced
- Contractor retained under proper project role
- Unresolved owner handled safely

**C. Permit-derived enrichment**
- New permit enriches existing card
- Important field changes are reflected
- Conflicting evidence remains visible
- Replay is idempotent

**D. Real Jev**
- Actual configured model call
- Valid structured response
- Useful identity/materiality decision
- Persistent execution receipt
- Safe failure behavior

**E. Real Sol**
- Actual configured OpenAI model call
- Multiple sources synthesized
- Identity and buying-chain research
- Source-backed card output
- No unsupported power claims

**F. Performance**
- Production-scale representative data
- Company queue responds without full permit payloads
- Pagination/filtering operate on the full cohort
- Detail requests remain bounded
- Measured baseline and after results

**G. Real UI**
- Browser-based desktop testing
- Mobile layouts
- Company and project navigation
- Search and filter behavior
- Account-to-project drill-down
- Evidence expansion
- Back/forward/reload
- Contact and next-action workflows

Test real provider behavior separately from mocks.

Document exactly which scenarios were proven and which remain blocked.

---

# 14. IMPLEMENTATION DISCIPLINE

Start by examining the existing repository.

Read and respect:

- `AGENTS.md`
- `docs/product/PRD.md`
- `docs/design/UI_CANON.md`
- `.agent/CURRENT_STATE.md`
- `.agent/FINISH_CONTRACT.md`
- Existing entity/evidence graph architecture
- Relevant GL3-019/028 implementation
- PR #102/#103 commercial enrichment work
- Current provider routing and automatic planner
- Latest merged source and active PRs

Do not rebuild existing services unnecessarily.

Do not create a competing intelligence framework.

Do not redesign the entire app.

Do not introduce a graph database or vector database without a demonstrated need.

Keep PostgreSQL as canonical state.

Use the existing FastAPI/backend and React architecture.

Preserve existing historical evidence, user notes, identity corrections, contact authority and source lineage.

Prefer the smallest robust implementation that delivers the full commercial outcome.

---

# 15. EXECUTION DIRECTIVE

You are authorized to inspect, develop, test, and prepare a reviewable pull request for this scope.

Proceed autonomously through implementation.

Do not stop at architectural proposals, mockups, or documentation.

Do not repeatedly request instructions when the repository and canonical product requirements provide a clear next step.

Use these phases:

1. Inspect the actual source and identify root causes.
2. Document the minimal architecture and compatibility plan.
3. Implement canonical account aggregation.
4. Repair developer/owner/contractor attribution.
5. Integrate permit-to-card enrichment.
6. Connect and test Jev/Sol execution paths.
7. Update the existing UI using approved design.
8. Run comprehensive automated and browser tests.
9. Perform representative end-to-end data validation.
10. Prepare the PR and an evidence-backed implementation report.

You may proceed with subsequent phases without waiting for approval where the work is local, reversible and within scope.

Do not merge, deploy, change production data, enable paid-provider calls or alter credentials without the appropriate explicit authorization.

If a true external blocker exists, complete all independent work and report the exact blocker, consequences and required owner action. Never represent blocked work as complete.

---

# 16. DEFINITION OF DONE

The work is complete for review only when:

- Companies are consolidated correctly.
- Genuine separate projects remain distinct.
- Subcontractors are not automatically presented as customers.
- Permits populate intelligence rather than clutter the UI.
- Customer cards contain the best available source-backed commercial information.
- Jev execution is validated against its intended contracts.
- Sol execution is validated against actual configured provider capabilities.
- Real and mocked execution are clearly distinguished.
- All existing qualification and evidence safeguards remain intact.
- Browsing performance is measured and acceptable.
- Full automated and browser regression tests pass.
- No unrelated functionality is broken.
- A reviewable PR exists with an accurate acceptance report.

For blocked provider activation or unavailable production credentials, explicitly mark the live-provider criterion **BLOCKED**, not PASS.

## FINAL OWNER REQUIREMENT

**I do not want a database viewer. I want a commercial intelligence platform.**

I want to open GridLens and see actual companies worth contacting, the projects those companies are building, why they may need distributed or temporary power, when they need it, how much they may need, and who I need to speak with.

I want Jev and Sol to do the complex intelligence work behind the scenes.

I want supporting evidence preserved, but I do not want to navigate thousands of permits to understand one customer.

**Build GridLens around commercial decisions, not raw records.**

Proceed with implementation.
