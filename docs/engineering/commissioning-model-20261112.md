# Commissioning test-plan scenario v1

Implemented in `backend/src/gridlens/domain/commissioning.py` as
`estimate_commissioning(inputs: list[dict], *, config: dict | None = None) -> dict`.
This extends the existing Decimal calculation conventions. It creates no database,
provider integration, research job or alternative company/project identity.

## Engineering basis and research boundary

Engineering references collected during the 2026-11-12 architecture audit:

| Reference | Relevance | Boundary |
| --- | --- | --- |
| [Cummins: Load Bank Performance Testing](https://www.cummins.com/en-na/na/sales-and-service/load-bank-performance-testing) | Equipment load-bank testing and test load/procedure context | Maintenance and wet-stacking recommendations do not establish a new development's commissioning or rental requirement |
| [Robert Trefz, 7x24 Exchange: Load Bank Testing in Data Centers](https://www.7x24exchange.org/industry-news/magazine-archives/load-bank-testing-in-data-centers/) | Equipment/system commissioning and load-bank test context | Does not establish a universal fraction of announced campus capacity |
| [Cadence: Load Bank Testing for Data Centers](https://cadencenow.com/load-bank-testing-for-data-centers-verifying-backup-power/), published 2026-10-01 | Project electrical systems and backup-power verification context | Secondary engineering context; cannot substitute for the project's test sequence |

No reference supplies a campus-to-commissioning multiplier for this model. No maintenance
load percentage is adopted as a commissioning coefficient. The baseline instead requires
project-specific test loading, equipment/block ratings, scope and concurrency. These references
support that choice of inputs; they are not project evidence and must never populate a
project's sequence-evidence field simply because its development capacity is known.

## Input contract

Each input represents one electrical equipment type or defined test block within **one project**.
All records supplied in a call must describe a mutually consistent commissioning plan.

| Field | Required meaning |
| --- | --- |
| `project_id` | Existing canonical physical project identity; identical across the call |
| `block_id` | Unique test-block identity, including the equipment or test package |
| `load_scope_id` | The physical electrical load path being tested; upstream/downstream tests of the same load use the same identity |
| `sequence_stage` | Explicit test sequence: blocks in one stage run concurrently; different stages are sequential |
| `rating` | Positive, finite electrical rating per equipment unit or defined block; decimal string preferred |
| `unit` | `MW`, `kW` or `kVA` |
| `rating_basis` | `electrical_input` or `electrical_output`; mechanical/nameplate ambiguity is rejected |
| `installed_units` | Positive integer count of these equipment units/blocks |
| `concurrent_units` | Project-supported count tested concurrently, between 1 and installed count |
| `test_fraction` | Evidenced active-power fraction of the rating, between 0 and 1 |
| `power_factor` | Required for kVA, greater than 0 and at most 1 |
| `evidence` | Field-specific source lists for `rating`, `test_fraction`, `sequence`, and `power_factor` when relevant |
| `scenarios` | Optional complete `low` and `high` objects, each specifying `test_fraction` and `concurrent_units`; requires `evidence.scenarios` |

Every evidence reference is an object containing the exact `project_id` and at least one of
`url`, `source_url`, `document_ref` or `evidence_id`. Preserve the source envelope's publication,
observation, extraction/version, verification and immutable-source binding fields in these
objects. The model returns their deduplicated, deterministically ordered union without stripping
metadata. Input URLs are evidence references, never fetch instructions.

The existing retained-fact admission/projection layer owns authenticity, current/superseded
selection, confidence, privacy and scope resolution. This calculator cannot verify the contents
of a document from a URL. Its caller must supply source-supported IDs and prove that differently
identified load scopes are disjoint. Do not invent separate load identities to bypass overlap
protection. Equal-strength inconsistent test plans must be held by fact resolution, not concatenated
into a plan. Unknown commissioning coverage must remain visible at account/project projection.

Project type, construction phase and electrical constraints influence **which source-supported
test plan is applicable**, rather than choosing a hidden default coefficient. No project-type
percentage or default concurrency is provided. A campus-capacity-only announcement abstains.

## Arithmetic and overlap

For active electrical power:

`block_MW = rating_MW × test_fraction × concurrent_units`

`stage_MW = sum(block_MW for proven disjoint blocks in that stage)`

`scenario_MW = max(stage_MW across sequential stages)`

kW converts to MW by dividing by exactly 1,000. kVA first converts to active kW using an
explicit evidenced power factor, then to MW. No horsepower conversion, PUE conversion, utility
capacity conversion, diversity coefficient or bridge-power inference exists.

Duplicate block IDs cause abstention. The same `load_scope_id` twice within a stage causes
abstention instead of adding an upstream generator/UPS/PDU measurement to its downstream load.
The same load in different sequential stages is permitted; taking the peak avoids summing
sequential tests. Independent projects are refused because their tests are not known to coincide.
Account projections may show project-specific scenarios, but must not claim their sum as a
customer-wide simultaneous commissioning demand without additional scheduling evidence.

For example, four installed 2 MW generators with a project plan testing two simultaneously at
75% create a **3 MW engineering scenario**. Installed generation is 8 MW. A later 6 MW sequential
test makes the project peak 6 MW; it does not produce 9 MW. None of these values establishes
how much power the customer would rent, whether grid or installed generation supplies the test,
or who purchases a load bank.

## Scenarios, confidence and configuration

Low/high results are absent unless **every block** supplies complete source-bound scenarios.
Each block's low/base/high demands must be ordered. Each scenario independently takes the peak
of its stage totals; low and high are deterministic engineering cases, not statistical
confidence intervals. There are no automatic ± percentages around base.

`confidence` is `medium` only when all supplied evidence references explicitly carry
`verification_status: verified`; otherwise a calculable scenario is `low`. Numeric outputs are
always labeled `demand_class: engineering_scenario` and `verified_customer_demand: false`.
A verified source improves input confidence; it does not turn a scenario into verified demand.
Abstention yields `confidence: insufficient`, `status: insufficient_data` and null MW values.
The UI should render that state as **Insufficient data**.

Model version: `commissioning-test-plan-v1.0.0`. Returned `calculation_version`, `config_digest`
and `input_digest` bind the result to its inputs and configuration. Input order and the process's
global Decimal context do not alter results. Inputs are never mutated. Scope IDs and evidence
metadata remain in the input digest; equivalent reordered records have the same digest.

Only two configuration keys exist:

- `decimal_places`: integer 0–9, default 6. Base uses half-even rounding, low rounds down and high
  rounds up. This is a reporting bound, not source precision. A positive base that would round
  to zero abstains explicitly instead of publishing a false zero.
- `max_blocks`: integer 1–10,000, default 1,000, to bound work. Reference lists are bounded to 100
  per input dimension; ratings and counts are bounded as documented in source validation.

Unknown configuration keys raise `ValueError`; no setting can replace project evidence or
supply a universal campus percentage. Rating, loading and concurrency are configurable only
through versioned, source-backed project inputs. Changing configuration changes its digest.

## Output and limitations

The result includes `status`, `low_mw`, `base_mw`, `high_mw`, `confidence`, class/verified flags,
version, effective configuration/digests, `input_evidence`, `stage_demands`, `assumptions` and
`limitations`. Decimal MW values are strings; unavailable scenarios are null, never zero.
Missing/invalid evidence, rating/basis, sequence, overlap, inconsistent ranges or a partially
valid plan refuses the whole supplied plan; no incomplete partial peak is presented as total.

This model does not size transient response, reactive power, power quality, cables, protection,
redundant banks, unreported auxiliaries or customer procurement. It does not infer actual load
bank or generator rental demand. Its output covers the admitted supplied test plan, not every
unobserved commissioning activity on a project. Commercial qualification and contact authority
remain independent facts.

## Reproduction and rollback

Focused command, with the repository's ordinary disposable test environment configured:

```bash
uv run --project backend pytest backend/tests/unit/test_commissioning.py -q
```

Tests cover announcement-only abstention, arithmetic/concurrency/sequential peak, kVA source
requirements, upstream/downstream duplication, duplicate blocks, cross-project refusal,
missing/mis-scoped references, finite decimal/count validation, source-bound scenario ranges,
malformed JSON, confidence, reporting precision and stable non-mutating recomputation.
Integration, source extraction, real-customer coverage and professional usefulness are separate
acceptance checks; these pure unit tests do not certify production readiness.

Rollback can withhold scenario publication or revert this additive module/call site while
preserving retained evidence and identity. No migration or retained-data rewrite is necessary.
