# Electrical demand models

Authority: [Autonomous Intelligence Canon](../product/AUTONOMOUS_INTELLIGENCE_CANON.md). These are design contracts, not shipped equipment models. Current source-backed demand/qualification behavior is in `backend/src/gridlens/domain/power_qualification.py`, `power_schedule.py`, and `call_facts.py`.

## CURRENT

The system supports source-quoted project/activity demand and suitable/unsuitable supply facts, bounded power schedules, and versioned deterministic qualification. For compatible intervals, residual gap is `[max(0, demand_min - supply_max), max(0, demand_max - supply_min)]`. A gap is not established when demand/supply do not align in scope and time, when a conflict exists, or when necessary data is absent. This is qualification arithmetic, not equipment engineering. No general drive-aware horsepower-to-electric-load model is established.

## TARGET — equipment-to-scenario contract

Every equipment record identifies facility/project/phase, equipment type, count, drive (`electric`, `gas_engine`, `diesel_engine`, `steam`, `unknown`), status (`existing`, `proposed`, `installed`, `retired`, `standby`), source claims and dates. Rating fields distinguish mechanical shaft output, electrical input, nameplate and measured values. Store original value/unit and normalized SI value; retain efficiency basis, power factor where relevant, duty/capacity factor, coincident fraction, redundancy/standby role, and assumptions separately.

For explicitly electric equipment with mechanical output rating:

`electrical_input_kW = shaft_output_kW / efficiency`

For electrical input/nameplate rating, do not divide again by efficiency. Connected load is the sum of in-scope electrical input ratings; operating scenario is the sum of `input_kW × duty_fraction × coincidence_fraction` for concurrently operating equipment. Exclude standby/redundant units from normal coincident operation unless the modeled contingency scenario explicitly includes them. Values and scenario outputs must identify whether they are observed, calculated or estimated.

Scenario bands (low/base/high) are computed only from cited bounded inputs or declared, calibrated assumptions; never create a plausible number just to fill a field. Source claims for campus capacity, total project investment, horsepower without drive type, generic facility size or grid proximity are not load inputs. When a permitted input is missing, preserve the known subtotal and mark total `UNKNOWN`/partial; do not impute.

### Negative and edge cases

- Explicit combustion-engine-driven pump/compressor/generator: zero *new electric motor load from that equipment*; generator output is supply only when capacity, availability, interval and suitability are evidenced.
- Unknown or mixed drive: abstain from electric demand for that item; do not treat HP as kW electric.
- Electric motor with mechanical HP: `kW_mechanical = HP × 0.745699872`; then divide by cited/assumed efficiency only if estimating electrical input. Label efficiency estimate and propagate range.
- kVA is not kW without a supported power factor. Do not infer PF.
- Existing load is not incremental demand; retired equipment is excluded after its effective end date.
- N+1/standby redundancy is not additive normal load; explicit contingency is separate.
- Overlapping operating windows determine coincidence; non-overlapping phases must not be summed as simultaneous.
- Missing unit, invalid negative rating, conflicting ratings, stale evidence or impossible efficiency causes validation failure/abstention, not silent correction.

O&G and data-center examples must follow same schema but have separate equipment catalogs. Data-center announced campus MW does not imply present IT load; phase, energized date, IT/cooling scope and source-backed commissioning are required.

### Versioning and provenance

Each calculation stores model ID/version, unit-conversion version, formula, scenario timestamp/as-of, input claim IDs and hashes, explicit assumptions with source or calibration version, output unit/range, and validation results. Recompute deterministically from frozen inputs. A changed formula yields a new result version; prior results remain addressable.

## NEXT

Build catalog and formula fixtures for O&G compression/pumping and data-center IT/cooling/phase loads. Test unit conversion, efficiency, duty, redundancy, timing overlap, drive negatives, unknown supply and reproducibility before any outputs feed qualification.

## DEFERRED

Dynamic engineering simulation, inferred grid availability, uncalibrated sector defaults, and treating a modeled load as a confirmed power shortage.
