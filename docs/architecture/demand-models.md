# Electrical demand models

Authority: [Autonomous Intelligence Canon](../product/AUTONOMOUS_INTELLIGENCE_CANON.md). These are design contracts, not shipped equipment models. Current source-backed demand/qualification behavior is in `backend/src/gridlens/domain/power_qualification.py`, `power_schedule.py`, and `call_facts.py`.

## CURRENT

The system supports source-quoted project/activity demand and suitable/unsuitable supply facts, bounded power schedules, and versioned deterministic qualification. For compatible intervals, residual gap is `[max(0, demand_min - supply_max), max(0, demand_max - supply_min)]`. A gap is not established when demand/supply do not align in scope and time, when a conflict exists, or when necessary data is absent. This is qualification arithmetic, not equipment engineering. No general drive-aware horsepower-to-electric-load model is established.

## TARGET — equipment-to-scenario contract

Every equipment record identifies facility/project/phase, equipment type, count, drive (`electric`, `gas_engine`, `diesel_engine`, `steam`, `unknown`), status (`existing`, `proposed`, `installed`, `retired`, `standby`), source claims and dates. Rating fields distinguish mechanical shaft output, electrical input, nameplate and measured values. Store original value/unit and normalized SI value; retain efficiency basis, power factor where relevant, operating schedule, part-load basis, redundancy/standby role, and assumptions separately. Keep two distinct output types: **coincident electrical capacity** (MW required while equipment is running in a stated interval/scenario) and **time-average energy/load** (MWh over a stated duration, optionally its average MW). They answer different questions and must not share one unlabeled “demand” field.

For explicitly electric equipment with mechanical output rating:

`electrical_input_kW = shaft_output_kW / efficiency`

Connected capacity is the sum of in-scope installed electrical input ratings times unit counts, including electrically connected standby units; it is distinct from the capacity concurrently required in a particular operating scenario.

For electrical input/nameplate rating, do not divide again by efficiency. Convert mechanical output to the required electrical input before applying any operational factors. For each time interval and scenario, coincident running demand is the sum of `electrical_input_kW × part_load_fraction` for units running in that interval. If the part-load value is unknown, use full input capacity as the conservative coincident bound or mark the modeled value unknown; do not silently apply an average duty factor. A coincidence/diversity factor may be applied only to a clearly defined multi-unit group, with its scope and calibration recorded; never apply both a group diversity factor and a second factor representing the same overlap.

Count is explicit: multiply per-unit rating by the number of equivalent units in the same operating state. A duty fraction means fraction of a stated period operating and is used only for time-average energy: `average_MW = running_MW × duty_fraction`, and `energy_MWh = running_MW × operating_hours`. Duty fraction does **not** reduce the MW required while the unit is on. Report time basis, period, units and scenario on every result. Values and scenario outputs identify whether they are observed, calculated or estimated.

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

### Numeric acceptance examples

These examples are normative arithmetic checks for the eventual implementation:

| Inputs | Coincident capacity / energy result | Required interpretation |
|---|---|---|
| One electric pump, 1.0 MW electrical input, runs 30 minutes in a one-hour period; compatible supply is 0.75 MW during that run | Coincident demand 1.0 MW; residual coincident gap 0.25 MW. Time-average load 0.5 MW and energy 0.5 MWh over the hour. | The 0.5 MW average must not hide the 0.25 MW gap while operating. |
| Two 1.0 MW electric duty pumps run together; one 1.0 MW standby pump; supply 1.75 MW | Normal coincident demand 2.0 MW; residual gap 0.25 MW. Standby unit contributes zero to normal scenario. A separately requested all-units contingency scenario would be 3.0 MW. | Count the two concurrent duty units; exclude the standby unit from normal operation. |
| One explicitly gas-engine-driven 1.0 MW shaft-output pump | New electric motor demand from this pump is 0 MW; shaft rating is not electric input. | No electrical gap may be asserted from this equipment alone. |
| One 1,000 HP pump with drive type unknown | Electrical demand is UNKNOWN; no horsepower-to-electric conversion or shortage claim. | Abstain pending drive evidence. |

Residual-gap arithmetic is permitted only for coincident demand and supply values covering the same activity, interval, and capacity basis. The current interval rule remains `[max(0, demand_min - supply_max), max(0, demand_max - supply_min)]`; time-average energy may not be substituted for coincident capacity. A numerical scenario is still a modeled result, not proof of a shortage or procurement need.

O&G and data-center examples must follow same schema but have separate equipment catalogs. Data-center announced campus MW does not imply present IT load; phase, energized date, IT/cooling scope and source-backed commissioning are required.

### Versioning and provenance

Each calculation stores model ID/version, unit-conversion version, formula, scenario timestamp/as-of, input claim IDs and hashes, explicit assumptions with source or calibration version, output unit/range, and validation results. Recompute deterministically from frozen inputs. A changed formula yields a new result version; prior results remain addressable.

## NEXT

Build catalog and formula fixtures for O&G compression/pumping and data-center IT/cooling/phase loads. Test unit conversion, efficiency, duty, redundancy, timing overlap, drive negatives, unknown supply and reproducibility before any outputs feed qualification.

## EXCLUDED

Human review/approval is not a prerequisite for routine model operation. Models may not self-modify production code or publish a shortage from unknown drive, duty average, campus capacity, grid distance, or incomparable/missing supply. No model output may convert absent evidence to zero or verified fact.

## DEFERRED

Dynamic engineering simulation and sector defaults until calibrated. Inferring service availability from grid proximity or absent evidence is excluded, not a future capability.
