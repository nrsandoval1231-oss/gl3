# Commercial coverage diagnostic — November 13, 2026

## Scope and evidence

This is a diagnosis of the source-text replay and native adapter receipt.
Expected capacity, timeline and contact values are comparison labels only.
Reference project names and locations ARE supplied to the scoper as disclosed
oracle identity context; this does not measure project matching or identity
accuracy. Native aliases derive only from freshly reparsed source text, never
from expected claim values or reference aliases.

The frozen replay is
[`source-text-scope-replay-source-coverage-final-20261113.json`](source-text-scope-replay-source-coverage-final-20261113.json)
(gold SHA-256 `dd061c52a85b0ba05b59aab4229f5dd886bced31145fe6ab315c5ad1cda0b922`,
source manifest SHA-256 `4b8831df9e94261806d2df7d51a4df1fd4299fe3b4daf862fdc64b99f192c5fb`).
It uses reference identity/location only as disclosed oracle evaluation context.
The current native validation capture is
[`native-runtime-replay-source-coverage-final-20261113.json`](native-runtime-replay-source-coverage-final-20261113.json).

Across 32 physical capacity assertions, scoped predictions score **2 TP, 0 FP,
30 FN**. The two true positives are DataBank Red Oak's phase 1 up-to 240 MW IT
load and the up-to 480 MW campus IT total. Across 30 timeline assertions, the
score is **0 TP, 0 FP, 30 FN**. The replay is high precision on very sparse
coverage. It does not show that remaining facts are absent from sources.

The native adapter admitted 4 of 22 unique-URL document groups (Aligned,
CyrusOne, DataBank, and Switch) and held 18. This created 4 Projects, 4 accepted
Evidence/Interpretation pairs, and 3 PowerNeeds, all with `required_mw: null`.
Aligned's Conesville Industrial Park project has an unknown region state and no
PowerNeed under current region policy. Switch creates an eligible Round Rock
PowerNeed, but its account identity remains unresolved. The runtime contains 2
account queue cards and 2 current project-scoped company links (CyrusOne and
DataBank). The legacy ordinary group query returns 3 entries: those 2 canonical
customer groups plus an unresolved `Fifth Prime data center campus` project
group. The explicit shortlist is empty. The primary canonical-only customer
group query returns 2 groups, CyrusOne and DataBank. These counts measure this
bounded offline path, not production source activation or identity accuracy.
The DataBank source facts remain evidence and do not become required demand.

The native runtime's CyrusOne project detail now includes its retained-source
operational forecast: expected to be operational by the fourth quarter of 2026,
with quarter precision and a deadline qualifier, from the July 30, 2025 source.
This is a reported operational target, not construction start, energization, or
commissioning demand. The runtime pipeline has accepted this source-backed
timeline fact and the saved detail API displays it. The separate source-text
oracle replay below still scopes zero timeline claims for CyrusOne and scores
the reference's Q4 2026 target as a false negative. Do not combine the runtime
projection result with oracle-scoped extraction metrics.

The source-backed runtime fact packages include DataBank's up-to 240 MW Phase 1
IT load and up-to 480 MW campus IT total as separate scopes. They do not set
required MW. The only timeline package claim is CyrusOne's expected operational
Q4 2026 target. Aligned and Switch have no source-backed capacity or timeline
claims in this run; their different admission/Need states do not imply fact
coverage. All three created PowerNeeds have unknown required MW.

## Per-source miss diagnosis

“Raw” below means the production extractor found a candidate before strict
project scoping. Candidate counts and labels are from the frozen replay; where
the table names a missed basis or event, it compares that candidate/source text
with the independent reference assertion. “Native hold” is the adapter's
project/location/activity admission result, not proof that the fact is absent.

| Reference source set | Frozen raw candidates | Main reason reference assertion(s) remain unmatched |
| --- | --- | --- |
| Vantage / Frontier | 2 capacity; 0 timeline | The 1,400 MW source phrase is found, but the parser records ordinary campus-development capacity rather than preserving the quoted GPU-compute basis. The first-building second-half-2026 delivery target is not parsed. Native admission lacks a complete source-bound site/activity relation. |
| Aligned / Conesville | 0 capacity; 0 timeline | No physical MW assertion is in this excerpt. “Targeting initial capacity delivery mid 2026” is not recognized as a supported delivery event. The native adapter now binds the Conesville Industrial Park site and activity, but does not bind Ohio from the title to the physical site; the resulting Project has unknown state and is region-held without a PowerNeed. |
| DataBank / Red Oak | 3 capacity; 1 timeline | The strict scoper retains the phase and campus IT claims (the two TPs). The 400 MW substation rating is not emitted by the raw typed extractor. The RFS quarter is parsed raw, but site-anaphora scoping withholds it. Native admission succeeds from body text and the explicit adjacent “Red Oak Campus” alias. |
| CyrusOne / Bosque | 2 capacity; 2 timeline | The oracle-scoped replay finds raw 190 MW agreement capacity and the Q4 2026 operational deadline but withholds both during project scoping: the deadline occurs in the later “The deal … facility” clause. The separate 400 MW Calpine platform capability is not an exclusive CyrusOne facility claim and is correctly absent from this source's raw candidates. Separately, the native retained-source runtime now admits the Q4 operational target into the CyrusOne project detail with quarter precision. The raw oracle scope replay still scores the timeline as 0 TP / 1 FN for this project; the native projection is not a scoring TP. Native admission succeeds, and the project/customer relationship does not turn 190 MW agreement capacity into IT load. |
| QTS / Hillsboro | 2 capacity; 0 timeline | Raw 27 MW initial-building and 250 MW campus candidates exist; both are lost at source-to-project scoping. The approximately 4.5 MW lease is outside the physical-capacity denominator because its basis is unspecified. “Open and commission … mid-2020” and second-half-2020 additional power are not parsed into their distinct event types. Native relation is held. |
| Switch / The Rock | 0 capacity; 0 timeline | The 60 MW acquired Austin/Houston properties and 185 MW Texas ecosystem total are expressly multi-site claims, not The Rock capacity. They must remain unbound. “Begin site preparation and permitting … summer 2021” is not extracted as a site-preparation event. The native adapter now admits the Round Rock/Fifth Prime project and preserves the source-native The Rock alias, but current extraction produces no MW or timeline facts for it. |
| Meta / Richland Parish | 2 capacity; 0 timeline | Raw parser emits 5 GW and over 2 GW as campus-development candidates, while the source wording explicitly says compute capacity. The December 2024 announcement is an announcement date, not a construction/operation milestone; no timeline candidate is appropriate without a distinct announcement event type. Native project/location/activity relation is held. |
| Google / Fort Wayne | 0 capacity; 0 timeline | The retained set has no reference capacity or timeline assertion. No commercial extraction miss is scored for this source set. |
| AWS / Madison County | 0 capacity; 0 timeline | The retained set has no reference capacity or timeline assertion. No commercial extraction miss is scored for this source set. |
| Microsoft / Fairwater | 0 capacity; 0 timeline | No capacity is stated. “On track to complete construction and bring this AI datacenter online in early 2026” is present, but raw timeline extraction does not emit the completion/online target. Native project/location/activity relation is held. |
| STACK / SVY01 | 3 capacity; 0 timeline | Raw 100 MW campus candidates are found, but the distinct 60 MW expansion is not parsed. The dated “announced a groundbreaking” is announcement evidence; the event date must not be represented as a verified physical start. Native project/location/activity relation is held. |
| Applied Digital / Ellendale | 1 capacity; 2 timeline | The raw parser finds 400 MW designed IT load and two RFS dates (first building and optional third building), but misses the 100/150 MW lease components, the second building's mid-2026 target, and the 1 GW load-study qualifier. All scoped claims are withheld. North Dakota remains excluded by current regional policy; do not use this source to widen that policy. The captured publication date metadata is null; preserve that as unknown. |
| Crusoe / Abilene | 1 capacity; 2 timeline | Raw candidates include a 1,200 MW figure assigned to phase 2 and the June 2024 construction start / H1 2025 energization; the initial-phase >200 MW and mid-2026 phase-2 completion are missed. The retained source explicitly names Lancium Clean Campus and Abilene, Texas, but native admission held the source relation. Publication date metadata is null; do not fill it from a present-day observation date. |
| Compass / Meridian | Multiple capacity candidates; 0 timeline | The source corpus contains the 500 MW Meridian utility-supply assertion, but also unrelated 200 MW, 79 MW, 212 MW, and 108 MW campus claims from other market pages. Native project/source association must keep the Meridian sentence while refusing neighboring market sites. The site's 320 MW basis is not parsed. Groundbreaking in 2025 is not extracted as a dated event. Native project relation is held. |
| EdgeCore / Mesa | 0 capacity; 0 timeline | Retained source describes a 450 MW+ Mesa development and building/expansion figures, but typed extraction emits none of the three reference capacity scopes. The two power-on-completion year targets are also not parsed. A direct positive Mesa site relation exists in the announcement; native activity binding is the weak stage rather than evidence absence. |
| Digital Realty / Lagos | 0 capacity; 0 timeline | No physical capacity or timeline assertion is in the label denominator. Retrieval is partial: the retained body is shell/truncated metadata, so the title supports the project name only. Do not infer that the live source has no MW or milestone information. |
| Equinix / JH2 | 0 capacity; 0 timeline | No capacity is stated. “Expected to launch … in Q3 2027” is not parsed as a launch target. The source is in Malaysia; the current native location grammar is U.S.-state oriented and holds it. This is parser/geography coverage, not evidence that the project is unavailable. |
| Fervo / Cape Station | 0 capacity; 0 timeline | The source reports 100 MW phase 1, 33 MW per GeoBlock, 400 MW phase 2, and 900 MW contracted offtake; none is emitted by the raw parser. First Power, contractual commercial operations, and phase-2 commercial operations are separate timeline semantics and all are missed. Native site/activity relation is held. Preserve contracted offtake as a distinct nonphysical basis. |
| Dominion / CVOW | 1 capacity; 1 timeline | The 2.6 GW generation project candidate and early-2024 construction-start candidate are found; the other construction-start target and 2026/2027 completion assertions are not. The two completion years conflict across sources and should remain visibly conflicting, not normalized into one date. The offshore project is outside the adapter's current accepted relation patterns. |
| TerraPower / Kemmerer | 1 capacity; 0 timeline | The 345 MW reactor-base output candidate is found; the 500 MW storage-boosted peak output is missed or must be distinguished by operating condition. The April 23, 2026 plant-construction start and June 2024 support-facility construction start are not extracted with their separate scopes. Native activity/location relation is held. |

The source capture's `publication_date_metadata` is null for many retained
pages, but exact publication dates can still be read from a recognizable
published-date line or city/state dateline. Article-body event dates are not
publication dates. The adapter requires explicit exact metadata or a bounded
date header; year, month, or quarter precision is never promoted to an exact
day. See the [publication date boundary review](publication-date-boundary-review-20261113.md)
for the accepted parser and reparse controls. Held-document receipts in this
run report relation failures, not publication-date failures. Do not treat an
unknown publication date alone as proof that a project is unavailable.

## Smallest reusable improvements

1. **Close the typed electrical grammar gaps.** Extend the existing pure
   extractor's label/basis families for compute-vs-IT, utility/substation
   ratings, generation output, storage-boosted output, and per-building or
   expansion amounts. Preserve qualifiers and phase/site/building scopes from
   the sentence and compare the exact candidate span. Reuse the existing
   `extract_customer_facts` parser and scope IDs; do not add another number
   scraper. Controls should pair real positives (DataBank substation, STACK
   expansion, Fervo generation, TerraPower storage) with adversarial controls
   for portfolio totals, foreign sites, lease options, and phase totals.

2. **Add event-specific timeline patterns with source precision intact.** The
   existing timeline extractor should recognize site preparation/permitting,
   capacity delivery, RFS, construction start/completion, first energization,
   first power, launch, and announcement only as their own event types. Parse
   the date expression as written (`mid 2026`, H1, quarter, season, year, exact
   day) and preserve `by`/deadline qualifiers. Do not turn publication dates,
   announcements, deliveries, RFS, construction completion, and energization
   into interchangeable milestones or invent exact dates. Reuse existing
   `TimelineEvent` semantics and source citation plumbing.

3. **Share one bounded physical-subject binding across native admission and
   claim scoping.** Reuse source-native aliases and explicit locality/site
   relations; require the activity or value predicate to govern the selected
   subject in the same sentence, with a narrow source-local anaphora rule only
   where its antecedent is unique. Preserve cross-site refusal for DataBank's
   other-market portfolio, Switch's Austin/Houston ecosystem, and Compass's
   unrelated campuses. Keep native adapter admission as validation, not
   production source activation; canonical project/company identity accuracy
   still needs its own measurement.

These are diagnostic priorities, not implementation approval or acceptance.
The present miss pattern is not adequately described as missing source
information: raw parser misses, semantic typing/scope, subject binding, event
vocabulary/precision, and native admission each contribute. Google, AWS, and
Digital Realty are denominator/source-coverage cases rather than scored
physical-fact false negatives.
