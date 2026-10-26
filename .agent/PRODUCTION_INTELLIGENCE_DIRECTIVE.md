# GRID LENS — MASTER BUILD DIRECTIVE

> Supporting earlier directive. The autonomous canon wins where workflow, scope, harness or acceptance language conflicts; historical provider and release directions are not current authorization. Authority: [Autonomous Intelligence Canon](../docs/product/AUTONOMOUS_INTELLIGENCE_CANON.md).

## Production Intelligence Pipeline: Firecrawl + Jev + GPT Sol

**Repository:** `nrsandoval1231-oss/gl3`
**Baseline:** `main`, commit `a70e533` (October 23, 2026)
**Geographic scope:** Texas, Oklahoma, New Mexico
**Priority:** High — functional commercial intelligence over cosmetic features

---

# 1. Mission

Transform GridLens from a functioning source-ingestion application into an operational commercial intelligence engine that autonomously discovers, investigates, validates, and prioritizes real power opportunities.

The system must turn raw evidence into consolidated customer accounts, actionable project intelligence, and ranked commercial pursuits.

Integrate three specialized capabilities:

1. **Firecrawl:** Web acquisition, source discovery, and difficult-page extraction.
2. **Jev:** Evidence preparation, structured fact extraction, normalization, validation, and quality control.
3. **GPT Sol:** Commercial reasoning, power-gap assessment, customer research, and recommended actions.

These must work together as a durable, observable intelligence pipeline.

Do not simply create interfaces, placeholders, mock responses, or configuration screens. Implement and verify real provider execution.

Do not claim an integration is operational until it has successfully executed against live sources.

# 2. Preserve Existing Work

Before making changes:

- Inspect the current repository, migrations, architecture, and existing provider integrations.
- Read canonical PRDs, engineering directives, source registries, and existing QA reports.
- Identify existing Jev, OpenAI, research, classification, enrichment, and evidence infrastructure.
- Reuse working functionality instead of creating parallel systems.
- Preserve historical evidence and migration compatibility.
- Avoid rewriting functioning ingestion adapters.
- Preserve all security protections, including SSRF restrictions and public-address validation.

Use the existing PostgreSQL database as the canonical persistence layer.

Do not introduce another database, orchestration framework, or independent agent platform unless demonstrably necessary.

# 3. Target Architecture

Implement this logical workflow:

```text
OFFICIAL SOURCE REGISTRIES
          +
       FIRECRAWL
          |
          v
  SOURCE ACQUISITION
          |
          v
  EVIDENCE NORMALIZATION
          |
          v
        JEV
  Structured Extraction
  Fact Validation
  Entity Candidates
  Contradiction Detection
          |
          v
       GPT SOL
  Commercial Reasoning
  Power Gap Assessment
  Customer Intelligence
  Buying Chain Research
  Next-Best Action
          |
          v
 DETERMINISTIC VERIFICATION
          |
          v
   CANONICAL DATA MODEL
          |
          v
  GRID LENS APPLICATION
  Customer Accounts
  Projects
  Power Opportunities
  Pursuit Queue
```

This is a logical architecture. Do not require a separate network service for every stage.

All stages must be independently testable, observable, and recoverable.

# 4. Firecrawl Integration

Implement Firecrawl as an optional acquisition provider within the existing ingestion infrastructure.

### Requirements

- Native adapters remain the preferred acquisition mechanism for official APIs and structured sources.
- Use Firecrawl when native extraction is inadequate, incomplete, or requires JavaScript rendering.
- Support targeted source discovery and enrichment research.
- Preserve original URLs, acquisition timestamps, retrieved content, document identity, and provenance.
- Store sufficient source content to support later reprocessing.
- Prevent duplicate evidence records.
- Apply strict geographic and source-relevance controls.
- Enforce bounded crawling, request limits, credit budgets, and retry policies.
- Do not bypass authentication, access restrictions, or source security policies.

### First validation

Compare Firecrawl and native extraction on representative real sources, including:

- Crusoe Longhorn Data Center
- Texas PUCT large-load dockets
- TCEQ NSR pending registrations
- Oklahoma DEQ public review
- Albuquerque building permits

Measure extraction completeness, fact recovery, latency, and provider cost.

Do not route every document through Firecrawl by default.

# 5. Jev — Evidence Intelligence

Integrate Jev as the structured evidence-processing and validation layer.

Inspect Jev's actual available API capabilities before implementing its role. Do not assume it provides native extraction or validation operations that have not been verified.

### Responsibilities

Where supported by its actual interface, Jev should:

- Normalize extracted source facts.
- Identify company, owner, operator, contractor, and project entities.
- Extract generation capacity, fuel, voltage, operating hours, dates, and equipment references.
- Detect contradictory statements.
- Distinguish explicit source facts from inferred values.
- Flag insufficient or low-quality evidence.
- Prepare compact, high-quality evidence packages for GPT Sol.

Use deterministic parsers for straightforward fields wherever practical.

Do not force Jev into operations better handled by deterministic code.

### Required output

Produce versioned, schema-validated evidence packages with:

- Source references
- Extracted facts
- Entity candidates
- Confidence or quality indicators where justified
- Missing fields
- Contradictions
- Processing status

Every factual assertion must be traceable to source evidence.

If Jev fails, preserve the source evidence and mark the processing stage as incomplete. Do not silently replace Jev with another provider.

# 6. GPT Sol — Commercial Intelligence

Implement GPT Sol as the primary reasoning model for commercially meaningful power-opportunity assessment.

Verify the actual available OpenAI model/API configuration. Do not assume that the ChatGPT product label "Sol" is a callable API model identifier.

Use a supported, configured OpenAI model for the Sol reasoning role, and record the actual provider and model identifier.

### Responsibilities

For each relevant project, evaluate:

**Customer intelligence**
- Actual owner or operator
- Parent company
- General contractor
- Electrical contractor
- Engineering or EPC partners
- Relevant decision-makers
- Verified public contact information

**Power intelligence**
- Project power requirements
- Existing utility service
- Planned onsite generation
- Backup or standby generation
- Potential temporary generation requirements
- Construction and commissioning timelines
- Estimated power-supply gap
- Potential rental duration
- Natural gas or propane suitability

**Commercial assessment**
- Is this a genuine potential rental-power customer?
- Is there evidence of a timing or capacity constraint?
- What information is missing?
- Who should be contacted?
- What is the next best research or sales action?
- How strong is the supporting evidence?

Separate:

1. Verified facts
2. Calculated estimates
3. Model inferences
4. Unknowns

Do not invent MW, rental duration, project schedules, or contact information.

Do not equate permanent onsite generation with temporary rental demand.

# 7. Customer and Project Consolidation

Implement or repair the canonical relationship:

```text
CUSTOMER ACCOUNT
    |
    +-- PROJECT A
    |      +-- Evidence
    |      +-- Power Requirements
    |      +-- Buying Chain
    |
    +-- PROJECT B
    |      +-- Evidence
    |      +-- Power Requirements
    |      +-- Buying Chain
    |
    +-- COMMERCIAL OPPORTUNITIES
```

One company may own multiple projects.

One project may have hundreds of supporting permits and documents.

Do not create hundreds of opportunities from hundreds of permits.

For data centers, prioritize the actual developer, owner, or operator rather than a subcontractor appearing on a permit.

Preserve distinct projects and legitimate separate commercial opportunities.

Require defensible identity matching and provenance. Uncertain matches must remain reviewable.

# 8. Power-Signal Classification

Investigate the October 23 finding that 446 records produced zero bridge, backup, or BTM classifications.

Determine whether this reflects genuinely absent evidence or pipeline defects.

Support evidence-backed distinctions between:

- Onsite generation
- Behind-the-meter generation
- Bridge power
- Backup power
- Commissioning power
- Construction power
- Permanent generation
- Unclassified generation references

Allow multiple supported classifications when appropriate.

Do not assign bridge or BTM tags simply because onsite generation is mentioned.

Fix extraction truncation and incomplete document processing where they prevent relevant facts from being evaluated.

Add regression cases using real, cited source evidence.

# 9. Repair October 23 QA Failures

Complete the following:

### PUCT dockets
Update the obsolete registry endpoint and restore successful ingestion without weakening redirect or SSRF protections.

### Fresh database initialization
Ensure Opportunities works after normal startup and migrations without requiring a manual browse rebuild.

### Desktop detail panel
Correct the cramped 1280×800 layout, broken word wrapping, and clipped metric cards.

### Remaining regional sources
Test:

- SPP thermal interconnection
- ERCOT large-load report
- JETI
- TDLR TABS
- TXR150000 stormwater notices

Document source failures and evidence-only yields separately from accepted commercial signals.

# 10. Autonomous Research and Recovery

Implement bounded autonomous continuation for incomplete research.

If a customer record lacks a critical fact:

1. Determine whether the missing fact materially affects commercial qualification.
2. Search approved sources using existing adapters or Firecrawl.
3. Process newly retrieved evidence.
4. Update verified facts.
5. Reassess the commercial opportunity.
6. Stop when the question is answered, the budget is exhausted, or no useful sources remain.

Prevent infinite research loops.

Use durable job states, idempotency, retry limits, and clear failure reasons.

Never mark a research job successful merely because a model returned a response.

# 11. Observability

Add or reuse internal monitoring for:

- Acquisition status
- Firecrawl execution
- Jev execution
- GPT Sol execution
- Extraction and verification outcomes
- Customer resolution
- Commercial qualification
- Provider failures
- Retry counts
- Latency and cost
- Evidence freshness

Make it possible to inspect exactly why a project was classified or rejected.

Avoid adding unnecessary complexity to the primary sales interface.

# 12. Verification and Acceptance

Run the full regression suite and browser QA.

Additionally, demonstrate a real end-to-end execution:

**Live source → acquisition → Jev → GPT Sol → deterministic verification → consolidated customer/project record.**

Use real provider responses, not scripted substitutes, for the live acceptance run.

Test at least five representative projects across the supported region where sufficient real evidence exists.

Required proof:

- Actual provider calls and model identities
- Structured outputs
- Evidence citations
- Customer/entity resolution results
- Power classification results
- Commercial assessments
- Actual costs and latency
- Failure and recovery behavior
- Browser screenshots
- Regression test results

A passing mocked test suite is not proof of operational AI integration.

If credentials, provider access, or required external infrastructure are unavailable, identify the exact blocker and leave the affected capability explicitly unverified.

Never fabricate success.

# 13. Execution Order

Execute in this order:

**Milestone 1 — Repair**
Fix PUCT dockets, fresh-database startup, and desktop layout.

**Milestone 2 — Acquisition**
Implement and validate optional Firecrawl extraction.

**Milestone 3 — Evidence**
Integrate Jev with real provider execution and persisted evidence packages.

**Milestone 4 — Intelligence**
Integrate GPT Sol commercial reasoning and deterministic verification.

**Milestone 5 — Customer Resolution**
Validate consolidated accounts, projects, buying chains, and power opportunities.

**Milestone 6 — Acceptance**
Run complete end-to-end QA and produce a production-readiness report.

Commit coherent milestones and maintain a clear implementation record.

Do not let unrelated enhancements delay the core pipeline.

# 14. Final Deliverables

Provide:

1. Implemented code in the existing repository
2. Database migrations where necessary
3. Updated canonical architecture documentation
4. Updated environment configuration examples
5. Automated regression tests
6. Real provider acceptance evidence
7. Browser QA screenshots
8. Before/after source and intelligence metrics
9. Operational runbook
10. Final readiness assessment

Create a PR with a clear summary and verification evidence.

Do not merge or deploy production until the implementation is validated and explicitly approved.

---

# Non-Negotiable Product Principle

GridLens is not a permit database, a generic research chatbot, or a dashboard displaying thousands of records.

**GridLens is a commercial intelligence engine for identifying customers who may need power before their needs become obvious sales opportunities.**

Its primary output must answer:

- Who needs power?
- Where?
- How much?
- When?
- Why might conventional power be unavailable or insufficient?
- Who controls the buying decision?
- What should we do next?

Every architectural decision should move GridLens closer to answering those questions accurately, reliably, and faster.
