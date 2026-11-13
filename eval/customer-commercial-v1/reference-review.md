# Independent reference-review evidence

These independent Astra reports are retained verbatim below. The initial report records findings against an earlier label revision. The later report verifies the corrected reference hash `243dce0a8dac5592ead63103deb4688d2d613168107f998d4f49d96993df9177` and all 29 source artifacts; its backend findings remain bound to its named code revision. Neither report supplies runtime or salesperson acceptance.

## Original reference review — retained historical findings

# Independent reference-label review — 2026-11-12

Reviewed `/workspace/reference-research/reference-customers.json`, SHA-256 `e54ff1c5a21fe2476de3d3631805c671258b6166215067a29512d1711b31ed0b`, against all 29 retained source excerpt artifacts. All 29 artifact hashes and all 29 excerpt hashes match `source-hashes.json` (excerpt hash is SHA-256 of excerpts joined with two newlines).

This is an independent comparison with the retained excerpts, not a fresh website verification, proof of canonical database binding, current employment verification, salesperson acceptance, or a passing extraction evaluation. Source artifacts and labels were not edited. A corrected fixture under `eval/customer-commercial-v1/` is being prepared separately and is not accepted by this report until its changes are checked.

## Blocking label corrections

1. **Crusoe utility capacity is unsupported.** `crusoe-abilene.capacity[2]` asserts 1,200 MW of utility service / grid interconnection. `sources/crusoe.json` states an eight-building campus with “a total power capacity of 1.2 gigawatts,” but its retained excerpts never establish a 1.2 GW grid interconnection. Remove the utility claim or supply an independently retained supporting source. Campus capacity, initial-phase 200+ MW, June 2024 construction and H1 2025 expected energization are supported as reported historical claims.

2. **Digital Realty labels exceed the retained metadata.** `digital-realty-lagos` identifies a third facility and an August 22 opening. The retained title only says “new data center in Lagos”; the excerpt ends “today announced the...”. Neither “third” nor “opening” is retained. Use a new Lagos data-center announcement with a publication date and unknown event date/type; keep retrieval-partial missingness. Do not call an opening established from these artifacts.

3. **CyrusOne DFW10 identity is unbound.** Neither CyrusOne excerpt uses `DFW10`. They identify a new CyrusOne facility adjacent to Thad Hill Energy Center in Bosque County. Use that source-supported description or retain separate evidence for the DFW10 identifier. The 190 MW agreement is a power-supply contract, not IT load. The separate up-to-400 MW capability belongs to Calpine's Bosque delivery platform; its existing exclusion from committed project totals must remain, and it must not become an exclusive CyrusOne asset.

4. **Publication days are not actual event days.** Equinix's November 10 header and November 11 dateline conflict as publication dates; “marked ... topping out” does not establish the topping-out event occurred on one of those days. Fervo's September 24 announcement says first power “has achieved”; that establishes achieved-by-publication, not the exact event day. STACK's March 26 announcement describes groundbreaking but does not expressly date the ceremony. Keep the announcement dates separate and actual event dates unknown unless further evidence supplies them.

5. **Fervo deadline and quantity semantics need correction.** October 1, 2026 and January 1, 2027 COD targets are explicitly “by” dates: retain an at-or-before/deadline qualifier, not an exact expected event day. The 900 MW claim is “approximately” contracted offtake; preserve approximation and type it as contractual offtake, not physical generation capacity. Excluding it from an aggregate does not repair a misleading capacity type. Approximately 100 MW phase I, three 33 MW GeoBlocks and an additional 400 MW phase are supported as reported generation capacities, not commissioning demand.

6. **QTS lease approximation is missing.** The 4.5 MW lease is expressly “approximately 4.5 megawatts.” Add approximation alongside leased/basis-unspecified semantics. Preserve the more-than-250 MW campus lower bound and gross-power basis; do not treat them as exact IT load.

7. **Switch capability is not verified operating capacity.** The 60 MW properties are “capable of delivering” that amount. Rename `acquisition_existing_capacity` to acquired-site delivery capability or retain explicit unknown operating status. The 185 MW total is a planned multi-site Texas ecosystem including Austin/Houston, not The Rock alone. Current non-addition safeguards are appropriate.

## Scope/type cautions that must survive serialization and evaluation

- DataBank's 400 MW value is a substation rating. The explicit subtype must survive; it is not a guarantee of delivered utility service or 400 MW IT. The 240 MW phase and 480 MW campus IT distinction is supported by the surrounding sentence. Keep “up to” and inclusion.
- Applied Digital's 1+ GW is power capacity under load study; it is neither contracted/energized utility service nor committed 1 GW construction. Preserve study/potential status and lower-bound semantics. The 400 MW IT campus includes leased 100 + 150 MW and optional 150 MW; do not aggregate optional capacity as committed.
- EdgeCore's 206 MW “construct and commission” statement is a company quotation. The same article says two buildings remain under construction with power slated in 2025 and 2026. Retain this as a source-reported claim and visible scope/status tension; do not certify all 206 MW as presently operational. The 450+ and additional 250+ values are lower bounds, not exact 450 or computed exact 456.
- Meta's 5 GW and “over two gigawatts” are compatible exact-versus-lower-bound statements. The excerpt alone does not prove which page copy is stale. Do not invent a revision date or conflict merely from the two numbers.
- Vantage calls its 1.4 GW campus “GPU compute capacity.” Preserve the reported electrical-basis wording; do not silently convert to utility service or commissioning load.
- Name/role quotations establish historical source-named functional leaders, not current buyer authority or verified contact methods. The six-label coverage statement is acceptable only with that limitation. Executive quotes omitted by the labeling policy must not be counted as extractor false negatives unless the eligible-role taxonomy includes them.

## Record-level disposition

| Record | Disposition against retained excerpts |
| --- | --- |
| Vantage Frontier | Supported historical campus/delivery/role labels; retain GPU-compute basis limitation. |
| Aligned Conesville | Supported initial-delivery target; no MW or exact start date in excerpts. |
| DataBank Red Oak | Supported phase/campus IT and RFS labels; preserve substation subtype and upper bounds. |
| CyrusOne Bosque | Correction required: DFW10 identity; preserve supply-contract and third-party-platform scopes. |
| QTS Hillsboro | Correction required: approximate lease amount; retain gross-power and lower-bound semantics. |
| Switch The Rock / Texas ecosystem | Correction required: acquired-site capability status; no single-site 185 MW total. |
| Meta Richland | Supported historical announcement/compute amounts; no inferred staleness or false numerical conflict. |
| Google Fort Wayne | Operational status appears in excerpt; dates and MW remain unknown. |
| AWS Madison County | Supported planned two-complex scope and historical functional role; MW/dates absent. |
| Microsoft Fairwater | Supported early-2026 construction/online target; offsite 250 MW solar correctly excluded. |
| STACK SVY01 | Capacity/inclusion and role supported; exact actual groundbreaking day needs correction. |
| Applied Ellendale | Supported IT capacities and RFS targets with lease/option/study distinctions. |
| Crusoe Abilene | Correction required: unsupported grid-interconnection amount. |
| Compass Meridian | Supported approximately 500 MW supply, 320 MW site and 2025 groundbreaking; distinct bases. |
| EdgeCore Mesa | Reported amounts supported; retain lower bounds and operating-status tension. |
| Digital Realty Lagos | Correction required: third facility and opening are not retained. |
| Equinix JH2 | Launch quarter supported; actual topping-out day unsupported. |
| Fervo Cape Station | Correction required: event dates, COD deadlines and approximate offtake type. |
| Dominion CVOW | Supported 2.6 GW and approximate construction starts; retain unresolved 2026/2027 completion targets. |
| TerraPower Kemmerer | Supported source-reported 345/500 MW non-additive plant design, June 2024 non-nuclear and April 2026 announced nuclear construction. |

All 20 bounded source sets lack a source-supported test-load/concurrency envelope. Commissioning abstention is the appropriate expected result for this cohort, but does not validate positive scenario calculations. The corpus is a purposive reference set, not representative coverage. Do not publish accuracy or acceptance metrics until corrected labels are independently checked and actual extraction outputs are compared separately from identity and arithmetic tests.

## Code-review status

Integration code review is paused at the coordinator's request while builders change the candidate. Reproductions already sent to the coordinator concern phase-only completeness, range/lower-bound truncation, multi-project/phase scope, dropped qualifiers, ranking fallback and UI provenance rendering. Those observations are not an assessment of a later frozen commit. No integrated-candidate acceptance or full-gate result is claimed.


## Corrected-reference follow-up in independent backend review

# Independent backend review — bcffe372

Reviewed exact commit `bcffe37291ad3ba355d1da70d13fa872c20106dc` in `/workspace/gl3-commercial`, including its four-file delta from `f8b4caa6f66f3a61e303f0820841db8a40c2d1c9` and the previously reviewed complete backend integration. Read-only product review; no product code changes, provider calls, deployment, outreach, or retained-data writes were performed. Test fixtures used random disposable PostgreSQL schemas.

**Disposition: correctness acceptance withheld.** The reported geographic-scope and Roman-phase findings are closed narrowly, but the scope repair introduces a verified retained-research regression. This is not whole-candidate or commercial-readiness acceptance.

## Findings

1. **Blocking regression: canonical project name followed by its retained address is rejected.** `scope_customer_facts` now passes only the project name to `_subject_predicate`. That correctly refuses city/county subjects, but also rejects `Orion Data Center at 811 Clayton Ln, Austin, TX has 400 MW of campus development capacity.` and the equivalent construction-timeline statement. Existing real retained-research-path tests now return `UNRESOLVED` instead of `ACCEPTED`. Preserve the canonical-name requirement while permitting the exact retained location only after that name; location must never be an alternate subject. Do not weaken or delete the positive integration assertions.
2. **Previous P1 geographic attribution is closed for tested cases.** `Dallas, TX`, `Midland, TX`, and `Loudoun County, Virginia` cannot authorize another named project's capacity. The bare exact project-name positive remains supported.
3. **Previous P2 Roman phase noise is closed for tested cases.** Extraction and explicit inclusion links normalize equivalent Roman/numeric phase tokens. The real material-state replacement from Phase I to Phase 1 emits no event. Invalid/unsupported phase notations are not certified by this review.

## Independent execution

From `backend/`, after sourcing the task-local environment without printing credentials:

```bash
PYTHONPATH=src .venv/bin/pytest tests/unit/test_customer_scope.py tests/integration/test_customer_material_changes.py tests/integration/test_customer_commercial_intelligence.py -q
```

Result: **2 failed, 49 passed in 78.07 seconds**. Both failures are `test_capacity_only_research_uses_existing_admission_guards`, parameterizations `capacity` and `timeline`, at the original positive acceptance assertion. The source modules were imported from the exact reviewed commit before any follow-on repair. Direct pure-code diagnostics independently reproduced geographic refusal, bare-name acceptance, and name-at-address rejection.

Earlier exact `f8b4caa6` changed-suite execution passed 159 tests in 113.42 seconds, but that result does not validate this subsequent scope edit. The coordinator's interrupted full runs are not passing receipts. Full backend, migration/recovery, frontend/browser, performance and exact-head CI acceptance remain outside this focused result.

## Commercial and evidence limits

- No real-customer published/scoped extraction coverage or verified named-contact acquisition improvement has been established. Synthetic integration positives do not close that release blocker.
- The evaluator's new `within`/`deadline` timeline qualifiers require semantic normalization against reference labels before final raw metrics; evaluator fixes and final rerun were not accepted by this backend review.
- Production non-government source authority remains conservatively unknown; evaluator fixtures labeling sources primary are a different assumption and must be disclosed.
- Commissioning positive tests establish bounded arithmetic/admission behavior on synthetic explicit engineering sections, not real engineering-source availability or customer rental demand.
- UI changes were not part of this backend commit review. Final whole-candidate acceptance requires the revised source, successful complete gates and separate UI review.

The corrected 20-record reference fixture previously checked at SHA-256 `243dce0a8dac5592ead63103deb4688d2d613168107f998d4f49d96993df9177` incorporates the seven prior label corrections; all 29 retained artifact hashes matched its manifest. That bounded label review is not runtime association, current contact verification or sales acceptance.


## Independent r2 follow-up — November13, 2026

Verbatim follow-up received from reviewer `/root/astra_acceptance` after independent retained-source, semantic-diff, artifact-hash and control-test verification:

> Bounded independent attestation: new reference-customers.json and reference-customers-r2.json are byte-identical SHA256 dd061c52a85b0ba05b59aab4229f5dd886bced31145fe6ab315c5ad1cda0b922. Preserved old file hashes exactly243dce0a8dac5592ead63103deb4688d2d613168107f998d4f49d96993df9177. Independently removing only cyrusone-bosque.timeline[0].qualifier='at_or_before' makes parsed new JSON identical to old. All29artifacts still match manifest. Correction is supported by independently inspected retained source wording. Evaluator controls independently10pass0.61s. Approved bounded label/scorer correction only; no rerun metrics/runtime/commercial acceptance.
