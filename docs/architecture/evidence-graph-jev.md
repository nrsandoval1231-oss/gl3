# Evidence Graph and Jev Judgment Architecture

**Status:** Canonical architecture decision  
**Date:** 2026-10-01

## Objective

GridLens is not a generic lead scraper. It is a real-world project reconstruction and commercial timing engine for distributed and temporary power.

The core question is:

> Who is going to need temporary, commissioning, bridge, or behind-the-meter power; how much; when; for how long; and who can buy it?

The system must turn fragmented public evidence into an evolving, evidence-backed representation of physical projects and then surface only commercially meaningful changes.

## Architecture

```text
Sources
  -> raw immutable evidence
  -> parse
  -> normalize
  -> deterministic matching
  -> bounded Jev judgment where ambiguity remains
  -> canonical project/entity graph
  -> graph diff / change detection
  -> signal engine
  -> selective deep enrichment
  -> Signal -> Prospect -> Lead
  -> actionable pursuit
```

The architecture combines two useful public patterns without copying proprietary implementations:

- **Project/evidence first:** reconstruct physical projects by linking permits, utility/regulatory filings, county records, procurement records, company disclosures, and other source evidence.
- **Entity/change first:** normalize records into canonical entities, resolve duplicates, preserve relationships, and detect what changed rather than repeatedly rediscovering a static list.

GridLens specializes both patterns around power-gap detection.

## Source strategy

Every source adapter must have a defined signal purpose. Prefer primary public sources and records that reveal project state before general news.

Five **signal-purpose categories** (these do not replace or rename the existing source registry `family` field or its accepted values):

1. **Discovery** — evidence that a physical project may exist or advance: land, zoning, planning, incentives, large-load proceedings, environmental filings.
2. **Construction** — grading, civil, building, electrical, mechanical, generator and related permits or contractor activity.
3. **Power** — utility filings, service/energization evidence, interconnection records, air/generator permits, behind-the-meter generation evidence.
4. **Procurement** — RFPs, bid packages, commissioning packages, temporary utility requests, equipment procurement.
5. **Buyer** — developer, owner, GC/EPC, electrical contractor, commissioning contractor, energy/procurement contacts and other supported buying-chain evidence.

News, trade media, LinkedIn and company pages may enrich or confirm a project, but should not displace stronger primary evidence.

## Observation and evidence boundary

A connector does not directly create a Lead. It produces or updates the stable **Observation** envelope for a source/external identifier, while each retrieved content state is preserved as an immutable **Evidence version**. Claims and derived assertions point back to the evidence version that supports them. This preserves first-seen/last-seen history, corrections, unchanged replay, and provenance without mutating historical evidence.

Preserve:
- source and source type
- canonical URL/document identifier
- retrieval and source timestamps
- raw/original content or durable reference
- geography
- extracted facts
- extracted entities
- provenance for every derived assertion

A permit, RRC record, article or bid is an observation about a changing real-world object, not inherently a lead.

## Minimal canonical object model

Do not copy a giant universal ontology. Start with the smallest useful set:

- Project
- Organization
- Person
- Location
- Permit
- Procurement
- PowerRequirement
- Evidence
- Signal

Relationships carry semantics such as:
- Organization develops Project
- Organization builds Project
- Person works_for Organization
- Project located_at Location
- Project has Permit
- Project has Procurement
- Project requires PowerRequirement
- Evidence supports assertion/entity/relationship

Extend this model only when a real source or commercial workflow requires it.

## Entity resolution

The system must converge multiple names and records on canonical real-world objects while preserving uncertainty and provenance.

Resolution order:
1. exact authoritative identifiers
2. deterministic normalized identifiers/addresses/coordinates
3. deterministic multi-field matching
4. Jev adjudication for bounded ambiguous cases
5. deeper model/research escalation only when commercially justified

Never silently merge uncertain entities. Preserve aliases and the evidence behind a merge/link decision.

## Change detection is first class

GridLens should primarily ask **what changed since the last accepted state?**

Examples:
- new permit
- changed permit status
- new contractor
- new project phase
- construction start evidence
- generator/turbine equipment disclosed
- utility energization date disclosed or moved
- commissioning procurement appears
- ownership/contact changes
- new relationship between existing entities

The graph stores current state; the evidence history preserves how that state became known. A meaningful delta becomes a Signal candidate.

## Power-gap inference

The commercially valuable transformation is not merely identifying a project. It is assembling enough evidence to estimate:

- required MW or defensible range
- need/start window
- expected duration or range
- permanent-power/energization timing
- temporary/commissioning/bridge/BTM power relevance
- fuel fit, including natural gas/propane where evidence supports it
- buying chain and reachable buyer
- uncertainty and contradictory evidence

Example:

```text
construction-ready window: Q1 2028
permanent utility window: Q3 2028
=> possible ~6 month bridge-power gap
```

The dates and gap remain UNKNOWN when evidence is insufficient. Do not fabricate precision.

## Intelligence responsibility boundary

### Level 0 — deterministic code

Code owns facts, hard rules and state:
- fetching and retries
- raw document preservation
- hashing/deduplication
- exact identifiers
- dates and URLs
- deterministic normalization/matching
- arithmetic and known MW calculations
- graph/database writes
- graph diffing
- confidence/admission thresholds
- Signal -> Prospect -> Lead promotion rules
- provenance enforcement

Do not use Jev or a generative LLM where deterministic code can produce the correct result.

### Level 1 — Jev

Jev is the fast, bounded judgment layer for ambiguity. It is not the ingestion engine and does not autonomously mutate canonical truth.

Good Jev tasks:
1. evidence relevance
2. ambiguous entity-resolution adjudication
3. evidence/event classification
4. change-significance judgment
5. power-relevance judgment
6. escalation judgment: is expensive enrichment justified?

Jev inputs must be compact structured context. Outputs must be schema-constrained and stored with model/version, latency, cost where available, and input/output provenance.

### Level 2 — generative LLM / research agent

Use a deeper model only for work that genuinely requires synthesis or open-ended investigation:
- reconstructing a complex project
- finding missing corroborating evidence
- resolving contradictions
- researching the buying chain
- extracting and reconciling cited load, supply, timing inputs and assumptions for a power-gap scenario
- producing a pursuit brief

The LLM does not replace source evidence and must not turn unsupported inference into fact. It may extract or reconcile cited scenario inputs and assumptions, but deterministic versioned domain code calculates remaining MW, timing gaps, duration ranges, and other power-gap arithmetic from accepted inputs.

## First Jev integration: EvidenceJudge

Do not build a Jev framework. Implement one reversible adapter and one bounded task.

Input:
- existing canonical project state
- new normalized evidence
- deterministic candidate links/matches

Example output contract:

```json
{
  "relevant": true,
  "same_project": true,
  "event_type": "electrical_construction",
  "material_change": true,
  "power_relevance": 0.87,
  "temporary_power_hint": true,
  "needs_deep_enrichment": true
}
```

Exact schema/enums should be tightened during implementation. Scores are judgment metadata, not verified facts.

## GL3-028 implementation boundary

The GL3-028 slice implements this architecture with relational projections rather than a graph database. `GET /api/projects/{id}/state` reads only currently accepted evidence versions and exposes field-level `SUPPORTED`, `CONFLICT`, or `UNKNOWN` status with evidence provenance. `project_material_states` holds a compact accepted semantic snapshot and revision per project. Under a project lock, deterministic mutation hooks compare actual prior/new state and append material `change_events`; initial legacy seeding is not a discovery, metadata-only changes are omitted, and A→B→A remains visible.

`evidence_judge_runs` stores only explicitly invoked, bounded EvidenceJudge comparisons. Its strict categorical output and deterministic result are advisory metadata, separate from the existing signal-adjudication authority. The default `JEV_ENABLED=false`, shadow-only flag, daily and batch limits, durable PENDING reservation, and explicit CLI keep provider calls out of ordinary ingestion. A pure `research_recommended` decision can be stored beside the comparison; it cannot enqueue research, retrieve sources, contact a buyer, modify accepted facts, or promote a Signal. See the [dated validation report](../validation/gl3-028-evidence-graph-jev-shadow.md) for implementation and bounded measurement evidence.

### Shadow-mode requirement

Initially, EvidenceJudge must not change admission, promotion or canonical truth. Run it against existing accepted/rejected evidence and compare it with current deterministic outcomes and human-reviewed examples.

Measure:
- precision
- false-positive rate
- false-negative rate
- latency p50/p95
- cost per judgment and per ultimately actionable Signal
- invalid/timeout rate
- disagreement categories
- routing/escalation yield

Define acceptance thresholds from a labeled GridLens fixture set before enabling any decision authority. Failure, timeout or invalid output falls back to current deterministic behavior.

If Jev does not materially improve quality, speed or cost, remove the adapter.

## End-to-end ingestion loop

1. **Discover** — find new/changed source records.
2. **Capture** — preserve original evidence.
3. **Parse** — extract structured facts into immutable evidence versions linked to stable observations.
4. **Normalize** — map source-specific fields to canonical schema.
5. **Resolve** — identify candidate projects/entities.
6. **Link** — attach observation/evidence versions and claims to canonical objects with provenance.
7. **Diff** — compare accepted state with prior state.
8. **Judge/Signal** — use deterministic rules first; Jev only for bounded ambiguity.
9. **Enrich** — spend deeper research only on commercially important candidates.
10. **Score/Promote** — preserve existing Signal -> Prospect -> Lead semantics and deterministic gates.
11. **Route** — surface an evidence-backed pursuit with the next useful commercial action.

## Commercial target

The desired output is not “1,880 permits found.” It is closer to:

> A project materially advanced yesterday. Evidence now suggests a likely temporary/bridge-power requirement in a defined time window; the estimated MW/duration and buying chain are shown with explicit confidence and source provenance.

The system should optimize for actionable pursuits, not raw record count.

## Non-goals

- No universal knowledge graph for its own sake.
- No 50+ object ontology until proven necessary.
- No Jev call on every record.
- No LLM-first ingestion.
- No autonomous model writes to canonical truth without deterministic validation.
- No new orchestration/governance layer solely to host Jev.
- No replacement of existing proven ingestion workers/scheduler merely because this architecture is adopted.
- No relaxation of current evidence/admission rules unless separately measured and approved.

## Migration path

1. Keep existing source collectors and current production behavior intact.
2. Preserve the existing Observation -> immutable Evidence-version boundary and add/clarify canonical project/entity linkage around existing records.
3. Add explicit graph/state diff events.
4. Build a labeled fixture set from accepted and rejected existing evidence.
5. Implement `EvidenceJudge` behind a feature flag in shadow mode.
6. Measure it against current deterministic behavior.
7. If accepted, allow it only to recommend enrichment/escalation first.
8. Expand later to ambiguous entity resolution or change significance only when metrics justify it.
9. Add new source families after the core can convert added evidence into better project reconstruction rather than more noise.

## Success criterion

GridLens succeeds when wide ingestion produces a small number of timely, source-backed direct-buyer/contractor pursuits where the user can understand:
- what changed
- why it matters
- likely MW
- likely start window
- likely duration
- permanent-power gap
- fuel fit
- who can buy
- what evidence supports each conclusion
- what to do next

That is the canonical ingestion and intelligence direction until explicitly superseded.
