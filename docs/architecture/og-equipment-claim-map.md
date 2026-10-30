# Oil & Gas equipment claim cohort map

**Status:** bounded Phase 1 implementation note. The claim types under development are pure, unverified candidates; this map does not establish equipment facts, electrical demand, qualification, or publication. **Scope:** repository schema, retained RRC completion fixtures and one historical Federal Register equipment excerpt. The lead retrieved the official public notice read-only on October29 local time; no runtime source job, paid provider or production request was made.

**Current integration:** this document describes PR152 candidate contracts. PR153 adds a separate, independently verified bounded schedule-to-demand path; see [equipment-demand implementation](../engineering/equipment-demand-slice-20261030.md). The candidate-only gaps below do not imply that the calculation/persistence path is absent. `equipment-claim-v1` remains UNVERIFIED and is not automatically promoted into `equipment-demand-v1`.

## Existing schema reuse

ORM definitions in `backend/src/gridlens/persistence/models.py` and migrations are authoritative. Existing structures already provide source version and project/activity anchors:

| Existing entity | Relevant fields/relationship | Reuse boundary |
|---|---|---|
| `Source` | ID, publisher, endpoint, retrieval method, geography/family, enabled state | Identifies the registered origin and acquisition policy. Not a claim-level verification result. |
| `Observation` (`observations`) | `source_id`, `external_id`, title/abstract, published date, URL, content hash, first-seen time | Stable source record identity plus current extracted record fields. The unique source/external ID is not project identity. |
| `Evidence` (`evidence`) | `observation_id`, version `content_hash`, title/abstract, URL, published/observed date, `extraction_location`, event date and provenance | Immutable source-content version keyed by observation and hash. It does not currently represent typed equipment, drive, rating basis, role, or equipment-level assertion history. |
| `Project` (`projects`) | UUID, `identity_key`, name/location, source ID/external ID, asset type, identity facts and regional decision/provenance | Physical project identity anchor. A well/API identity can support resolution, but must not be widened to the operator's unrelated facilities. |
| `PowerNeed` (`power_needs`) | UUID, project FK, activity key, tier, rationale, admission basis, `required_mw`, timing/duration, supply | Existing project/activity qualification unit. These values are not an equipment inventory; an equipment candidate cannot write demand or gap into it. |
| `NeedObservation` (`need_observations`) | Unique need/observation pair | Explicit join between a need and its source observation. Does not bind each equipment assertion to an exact evidence version by itself. |
| `EvidencePackage` (`evidence_packages`) | Evidence and observation FKs, nullable project/need FKs, evidence hash, schema/extractor/question versions, provider/model, advisory processing state, payload | Existing versioned package can help preserve advisory extraction output. It is not a strongly typed equipment claim table and package links do not prove source meaning. |

Related history in `ProjectLifecycle` / `LifecycleEvent` tracks project lifecycle; `Interpretation` and `NeedObservation` support existing source interpretation/need attachment. Migrations `0001_initial.py` establish source, observation, evidence, project and need primitives; `0005_asset_lifecycles.py` adds lifecycle structures; `0011_power_need_briefs.py` adds need-specific advisory text; `0020_evidence_source_provenance.py` expands provenance; `0041_evidence_packages.py` adds immutable source-bound advisory packages. No equipment-claim migration or durable typed equipment inventory was found in this map. Do not add tables unless the current claim contract requires persistence and the additive migration is separately reviewed.

## Candidate-only interfaces

`backend/src/gridlens/domain/equipment_evidence.py` defines frozen `EvidenceReference` and `EvidenceContext`; `validate_evidence_reference` validates structure and exact equality with a caller-supplied retained snapshot, then checks exact quote substring containment. It does **not** fetch/authenticate a database row or validate source authority/claim semantics.

`backend/src/gridlens/domain/equipment_claims.py` defines `EquipmentRating` and `EquipmentClaim`; `validate_equipment_claim` validates the strict claim shape, exact project/need context, and evidence snapshot binding. It does **not** calculate demand, infer electric drive, award verification, qualify a Lead, or produce MW/gap. All accepted candidates remain `UNVERIFIED`; candidate records are not wired into runtime persistence or publication in this slice.

The candidate intentionally stores source rating numeric value and unit with a basis (`electrical_input`, `mechanical_output`, `generator_output`, or `unknown`). The fixture removes a thousands separator from the numeric value while retaining the original rating in its quote/provenance; no unit conversion occurs. There is no implicit horsepower conversion, count substitution, efficiency assumption, drive inference, or arithmetic in these modules. Unknown and contradicted states stay explicit.

## Retained O&G corpus check

The RRC fixture is an actual captured Texas Railroad Commission completion packet set already used by `backend/tests/unit/test_rrc_completion.py`. The packet adapter `backend/src/gridlens/ingestion/adapters/rrc_completion.py` checks a bounded set of official completion history packets against supplied API/operator/well identity and returns dated history events. The retained source identity used here is API `16538299`, operator `OXY USA WTP LP` (operator number `630555`), lease `WEST SEMINOLE SA UNIT`, well `604 R`, Gaines County. The initial packet reports a historical new-well completion dated `2015-04-19`; the later packet reports historical recompletion dated `2016-06-02`.

| Retained test fixture | Canonical fixture SHA-256 from `provenance.json` | Exact source URL host | Evidence limit |
|---|---|---|---|
| `backend/tests/fixtures/rrc_completion/new-well-138740.html` | `ffb33a959abab9bcdc1649d45161f3fd5110ce3b2e394b8bc729bce5418f4ab0` | `https://webapps.rrc.texas.gov/CMPL/` | Completion type/date and well/operator identity only; no compressor/pump, drive, count, role, rating, electrical input, or power demand assertion. |
| `backend/tests/fixtures/rrc_completion/recompletion-273201.html` | `91bc2282eccacdf11eb2052d9c76cf3bb06d82e2853cf391b32419978b61f374` | `https://webapps.rrc.texas.gov/CMPL/` | Historical recompletion for the same API identity; no retained equipment facts. |

An additional official historical proposal provides one retained O&G equipment statement:

> “Install one new electric motor driven compressor unit with a rating of 18,340 hp.”

The source is the [Federal Register filing for docket CP24-8-000](https://www.govinfo.gov/content/pkg/FR-2024-06-12/html/2024-12869.htm), published `2024-06-12`, document dated `2024-06-06`, for a proposed Texas-Louisiana expansion by Natural Gas Pipeline Company of America LLC at Compressor Station 302, Montgomery County, Texas. `backend/tests/fixtures/ferc-cp24-8-equipment-excerpt.txt` retains only that sentence; companion `ferc-cp24-8-equipment-provenance.json` records the URL, exact retrieved-original SHA-256 (`d4e94db733664b6045b046296bb96666a25885d661bfce5482d8f787d019a74f`), retrieval timestamp, excerpt SHA-256 (`d76f9ac3c5e5621cd16101033ab35e0e7b3b7e22aec98757ed815794c88c4d57`) and limitations. The original downloaded HTML was verified in the ignored `.artifacts/ferc-cp24-8-original.html`; it is not copied into the tracked fixture. Whitespace was collapsed only to retain the exact sentence excerpt.

That sentence supports a **historically proposed** compressor, electric drive, count one, and the original rating `18,340 hp`. It does not specify whether hp denotes shaft output or electrical input, so the fixture preserves `18340` / `hp` with basis `unknown`; no conversion is made. The filing does not prove present installation, operation, activity power demand, supply, gap, procurement status, or Lead qualification. The test candidate uses unrelated harness-only project/need/observation/evidence UUIDs and remains `UNVERIFIED`; these UUIDs are not mapped to a production project. The separate RRC well fixtures remain negative evidence for equipment assertions, and synthetic gas/unknown/standby/missing/conflict scenarios remain explicitly synthetic.

The fixture manifest records original and normalized hashes; Windows may check out LF content as CRLF, so the cohort test normalizes only CRLF to LF before comparing the manifest's canonical fixture digest. This validates the retained test asset and its declared source host, not current RRC availability or current facts.

No equipment claim was created for the RRC well identity. Synthetic equipment examples in `backend/tests/fixtures/og_equipment_claims.json` use a separate `synthetic-fixture-only` source marker and unrelated test UUIDs, and are used only to exercise the validator's shape/abstention boundaries. The RRC corpus demonstrates a gap in that retained well sample, not that the well has no equipment.

## Next data-contract gaps

1. Preserve the existing path `Source → Observation → Evidence` and need association `Project → PowerNeed → NeedObservation`; equipment candidates require an exact claim-level evidence version, project, and need context.
2. Existing package payloads and current project/need JSON have no verified common typed equipment inventory contract. Avoid duplicating `Evidence`, identity, or qualification fields in the candidate.
3. Before persistence, decide stable equipment identity, effective-time and supersession semantics, how one source can support/contradict multiple equipment assertions, and how evidence to project/need binding is independently checked.
4. Before modeling, define normalized electrical input versus mechanical output, units, operating schedule, duty/part-load, count, standby/redundancy and scenario assumptions. Keep model arithmetic downstream and versioned.
5. Keep equipment candidates outside `PowerNeed.required_mw`, supply, tier, ranking, API, and UI until evidence verification and deterministic demand contracts pass their own tests and review.

## Verification boundary

`backend/tests/unit/test_og_equipment_cohort.py` checks synthetic gas/electric/unknown drive, standby, missing count/rating and conflicting assertions, scope mismatch, injected MW/qualification fields, exact candidate source binding, and retained RRC fixture hashes/excerpt limits. Passing these tests demonstrates structural behavior only. It does not demonstrate O&G corpus precision, production persistence, source authenticity, electrical engineering validity, commercial quality, or live source health.
