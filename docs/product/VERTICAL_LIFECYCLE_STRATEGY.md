# GridLens Vertical Lifecycle Intelligence Strategy

**Date:** September 27, 2026  
**Status:** Supporting lifecycle strategy · owner-approved 2026-09-27
**Applies to:** `gl3`  
**Authority:** Subordinate to the [Autonomous Intelligence Canon](AUTONOMOUS_INTELLIGENCE_CANON.md) and compatible with detailed [PRD](PRD.md) requirements. It explains lifecycle interpretation; it cannot expand current territory or commercial eligibility.

**Delivery state:** CURRENT lifecycle coverage is limited to what deployed sources and code demonstrate. TARGET is the lifecycle doctrine below. NEXT is Oil & Gas and Data Centers. DEFERRED are other sectors and speculative pre-permit models until source-backed validation.

## Core doctrine

GridLens optimizes for **earliest actionable awareness of a future power requirement**, not earliest available permit.

A source record has no universal commercial meaning. GridLens must interpret an event relative to the lifecycle of the specific asset. A building permit can be late-stage evidence for a data center, while a drilling permit can be an early predictive anchor for a future upstream production-power requirement.

The canonical intelligence flow is:

**Source event → asset classification → lifecycle state → expected power event → time-to-power estimate → missing evidence → monitoring plan → commercial qualification**

Permits are evidence. Depending on the asset, they may be discovery, confirmation, enrichment, monitoring, or a clock-starting event. They are not automatically Signals and they are not automatically cold leads.

GridLens maintains one evolving project/asset record and a living timeline. New evidence should update that record rather than create disconnected cards whenever identity can be established safely.

## Commercial tiers remain separate from lifecycle

Lifecycle state and commercial qualification are different dimensions.

- **Signal:** sourced evidence creates a defensible reason to investigate a possible power need.
- **Prospect:** an actual power requirement is established and separate evidence supports that suitable supply may be late, insufficient, inaccessible, or otherwise unsuitable.
- **Lead:** evidence supports an unresolved power need with MW range, start window, duration range, supply-gap explanation, likely buying organization/role, and specific next action.

A lifecycle event does not promote a tier by itself. Deterministic qualification rules remain authoritative.

# Priority 1 — Data centers

Data centers require aggressive **pre-permit discovery** because ordinary construction permits can appear after the project is already commercially visible.

## Data-center lifecycle

**Project formation → site control/planning → permitting → construction → electrical buildout → commissioning → utility energization → operation**

GridLens should seek evidence as far left as practical.

### Pre-permit discovery — primary Signal territory

Prioritize:

- land acquisition and site control;
- rezoning and planning cases;
- development agreements and tax incentives;
- economic-development negotiations and announcements;
- utility load/service discussions when public;
- interconnection/service proceedings;
- water/sewer infrastructure requests;
- developer campus announcements;
- financing or major capital commitments;
- GC/EPC preconstruction activity;
- major electrical/equipment procurement;
- contractor and supplier awards.

The objective is to know a campus is forming before ordinary building/electrical permits become the first discovery event.

### Construction intelligence

Prioritize data-center-specific:

- grading/site permits;
- building permits;
- electrical permits;
- substation work;
- transformer and switchgear activity;
- generator permits;
- fuel infrastructure;
- EPC/GC awards;
- electrical-contractor awards;
- construction mobilization;
- temporary service and construction-power evidence.

Construction permits primarily **confirm, enrich, locate and time** a project already known when pre-permit discovery succeeds.

### Commissioning intelligence

Commissioning is a first-class power opportunity phase. Do not assume a universal "commissioning permit" exists.

Discover commissioning through multiple evidence types:

- commissioning-agent awards;
- commissioning packages and schedules;
- load-bank work;
- temporary generators;
- temporary electrical distribution;
- UPS commissioning;
- generator testing;
- switchgear testing;
- phased energization;
- utility-service milestones;
- temporary service requests;
- contractor procurement and bid packages.

The system should explicitly model construction power, commissioning power and bridge power as separate power needs.

### Data-center power-gap timeline

The target timeline is:

**Pre-permit Signal → project confirmed → construction need → commissioning need → utility energization evidence → bridge-gap assessment**

A utility-delay or phased-service event can materially increase priority but must still be supported by evidence.

# Priority 2 — Oil & gas

Oil & gas must not use one generic lifecycle. GridLens should maintain asset-specific state machines.

The O&G Lens contains at least:

1. Upstream production.
2. Compressor stations.
3. Gas processing / cryogenic plants.
4. SWD and produced-water infrastructure.
5. Gathering and pipeline infrastructure.
6. Pipeline pump/compressor facilities.
7. Treatment facilities.
8. Terminals.
9. Field-electrification projects.
10. Other fixed midstream/production infrastructure supported by evidence.

Mobile drilling-rig and frac-power rental is not the default pursuit target.

## Upstream production — predictive production clock

For upstream wells, the primary future power event is generally **production/electrification**, not drilling.

Canonical lifecycle:

**Pre-permit development evidence → drilling permit → spud → drilling → completion → first production → electrification/production power**

A drilling permit therefore can be a valuable **clock-starting predictive event** even though the power requirement may be weeks or months later.

GridLens should organize drilling-permit and subsequent activity into an operator/site/pad development record and estimate the future power-relevant window.

### Deterministic time-to-production intelligence

Where evidence and historical data support it, calculate and continuously update:

- operator;
- basin/county;
- well or pad identity;
- number of wells;
- permit date;
- spud date;
- drilling/completion state;
- estimated first-production window;
- estimated days to production;
- electrification evidence;
- utility/grid evidence;
- production/compression/artificial-lift power evidence;
- confidence/basis;
- next investigation.

Initial estimates may use transparent basin/operator/well-type rules. As historical outcomes accumulate, use measured operator- and basin-specific distributions rather than opaque probability claims.

Never present a predicted date as reported fact. Preserve the observed inputs and deterministic rule/version that produced the estimate.

### Upstream pre-permit discovery

Pre-permit upstream prediction is useful but higher-noise. Potential evidence can include development plans, spacing/unit activity, pad/site work, operator capex plans, acreage-development patterns, infrastructure buildout and other supported precursors.

Treat this as an **experimental predictive layer**, not a launch dependency. Do not flood the Signal list with speculative acreage or company-level activity.

## Fixed O&G infrastructure

Compressor stations, processing plants, SWDs, produced-water systems, gathering/pipeline facilities, treatment facilities, terminals and field-electrification projects behave more like infrastructure projects.

Canonical lifecycle:

**Project formation → regulatory/environmental application → permit → EPC/procurement → construction → commissioning/startup → operation**

For these assets, GridLens should pursue pre-permit discovery when practical using:

- project/operator announcements;
- regulatory applications and dockets;
- environmental/air/water filings;
- land/right-of-way evidence;
- EPC and contractor awards;
- equipment procurement;
- operator capex disclosures;
- midstream/customer agreements;
- gathering-system expansion;
- produced-water agreements;
- utility/electrification activity.

Permits then confirm, enrich and time the project.

### Asset-specific power relevance

Each O&G asset class must have its own lifecycle and power-event rules. Examples:

- **Upstream well/pad:** production/electrification is the principal future power event.
- **Compressor station:** construction/commissioning plus operational compression load may matter.
- **Gas processing/cryogenic plant:** construction, commissioning and operational plant load are separate needs.
- **SWD/produced water:** facility startup and pumping load are central.
- **Gathering/pipeline:** fixed compression/pumping and associated facility construction matter.
- **Field electrification:** direct evidence of a power requirement can be commercially significant immediately.

Do not apply one asset's assumptions to another.

# Discovery and monitoring loops

GridLens operates two complementary intelligence loops.

## Loop A — Discovery

Purpose: identify new projects/assets early.

Questions:

- What is being formed, planned or developed?
- What asset type is it?
- What lifecycle state does the evidence support?
- What future power event should GridLens anticipate?
- Is there enough evidence for a Signal?

Discovery should be broad but evidence-bound. Pre-permit sources are especially important for data centers and fixed O&G infrastructure.

## Loop B — Project monitoring

Purpose: continuously update known projects/assets.

Monitor for:

- new permits and permit changes;
- contractor/EPC/electrical awards;
- procurement;
- construction milestones;
- commissioning activity;
- drilling/spud/completion/production milestones where applicable;
- utility service and energization;
- temporary generation;
- secured permanent supply;
- delays/cancellations;
- ownership/buyer changes.

Monitoring should update the same project timeline and trigger requalification only when evidence materially changes.

# Deterministic lifecycle intelligence

The intelligence engine should maintain explicit state and explain its reasoning.

Minimum conceptual outputs:

- asset type;
- current lifecycle state;
- supporting evidence;
- prior lifecycle state;
- expected next milestone;
- estimated time to power-relevant event where appropriate;
- estimate basis/version;
- open questions;
- monitoring plan;
- commercial tier;
- tier reason;
- likely buying organization/role when supported;
- specific next action.

LLMs/search/research may classify, extract and find evidence. Deterministic code owns lifecycle validation, date arithmetic, time-to-event calculations, tier gates and persisted state transitions.

# Historical owner acquisition priorities — October 1, 2026 (superseded)

The geography and sequence in this dated paragraph are superseded. Current product authority limits eligible physical sites to TX/OK/NM, prioritizes Oil & Gas and Data Centers as the first verticals, and defers other sectors. Lifecycle events remain evidence only and do not imply a power gap or commissioning activity.

Official flare-gas permits and flaring/venting exceptions are in scope for oil-and-gas source onboarding. Preserve their legal/event type and dates separately from actual flaring/production measurements. Do not convert an authorized gas volume to electric output or assume gas availability, composition, suitable fuel or a buyer.

# Source prioritization

New source work should be evaluated by **commercial timing advantage**, not raw record volume.

Priority order:

1. Data-center pre-permit project formation.
2. Data-center construction/electrical/commissioning intelligence.
3. Upstream drilling/production lifecycle data.
4. Fixed O&G infrastructure pre-permit and regulatory intelligence.
5. Fixed O&G permit/monitoring sources.
6. Utility/energization evidence relevant to known projects.
7. Broader cross-industry discovery.

Do not add generic municipal permit feeds merely because they are easy to ingest if they provide less timing advantage than a harder priority source.

# Success measures

Measure:

- days of awareness before first ordinary construction permit for data centers;
- percentage of known data-center projects discovered pre-permit;
- time from project formation evidence to useful commercial Signal;
- accuracy/calibration of upstream permit→production windows against realized outcomes;
- percentage of upstream records with useful production/electrification monitoring state;
- percentage of fixed O&G projects discovered before final construction/startup;
- number of Signals converted to evidence-supported Prospects;
- duplicate observations consolidated into real projects/assets;
- time from Signal to identified buyer/contractor and next action;
- eventual commercial outcomes.

Raw permit count, observation count and Signal count are supporting diagnostics, not primary success metrics.

# Immediate implementation direction

Preserve the verified GL3-013 ingestion foundation. Do not rewrite durable jobs, evidence history or deterministic qualification without a demonstrated defect.

The next architecture work should add asset/lifecycle intelligence and prioritize source acquisition around this document. Existing permit sources remain useful as monitoring and confirmation inputs; they are not discarded.

The first implementation should prove the model with bounded real examples:

- data-center projects where pre-permit and later permit/commissioning events can be placed on one timeline;
- upstream drilling records where a transparent time-to-production clock can be calculated and updated;
- at least one fixed O&G infrastructure class such as compressor stations or SWDs.

The system must show what is observed, what is derived, what remains unknown, and why each next action matters.
