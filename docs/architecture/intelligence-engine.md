# Intelligence engine contract

Authority: [Autonomous Intelligence Canon](../product/AUTONOMOUS_INTELLIGENCE_CANON.md) and [PRD](../product/PRD.md). This spec is TARGET unless a row explicitly says CURRENT. Routine target operation is autonomous; insufficient evidence leads to targeted research, explicit uncertainty, or abstention, never a mandatory review queue.

## CURRENT

The worker runs source collection, durable jobs and interpretation. Retained observations/evidence feed project and company resolution, power-need qualification, lifecycle/change state, enrichment/research, deterministic commercial rules and server-owned browse projections. Exact current implementation is mapped in [overview](overview.md) and [data model](data-model.md). Equipment-level load modeling and full seven-layer evaluation are not established capabilities.

## TARGET — layer contracts

| Layer | Input → output | Contract and fail-closed behavior |
|---|---|---|
| 1. Autonomous discovery | Source schedules and incremental provider results → immutable observation/evidence versions and collection receipts | Keep original/source identity, content hash, event/published date, retrieval time, parser version and retry outcome. Partial/error collection never erases accepted claims. |
| 2. Evidence and entity graph | Evidence plus candidate entities → scoped claims and supported identity/relationship links | Preserve alternatives, temporal history and many-to-many edges. Separate company, physical facility, project, phase, activity and person. Ambiguous resolution remains unresolved. |
| 3. Equipment and demand | Scoped equipment/operation claims → versioned connected and operating-load scenarios | Deterministic formulas consume explicit unit, drive, rating basis, duty and redundancy assumptions. LLM may extract candidates only; unknown drive/rating cannot become electric load. |
| 4. Lifecycle and timing | Dated observed events and source-backed schedules → current lifecycle state and bounded milestone windows | Observed facts and estimated milestones have separate types and provenance. Never invent dates; stale or conflicting dates lower certainty or abstain. |
| 5. Supply and constraints | Scoped, time-aligned service/interconnection/onsite supply claims → supply intervals and residual-gap state | Compare compatible capacity, activity and time windows only. Distance is context, not service. Missing/incomparable supply produces unknown gap, not zero or shortage. |
| 6. Commercial qualification | Verified demand, timing, supply, procurement and buyer evidence → company-centered opportunity or investigation lead | Preserve Signal/Prospect/Lead semantics and 300 kW floor where applicable. Lead requires evidence-supported residual gap, relevant timing and buyer/procurement evidence under canonical rules. Emit next action and claim citations. |
| 7. Evaluation and learning | Frozen labeled cases, outcome evidence and candidate versions → metrics, promotion decision or rollback | Evaluate independently of candidate reasoning. Promotion is gated, reproducible and reversible. Outcomes improve policy only through bounded, measured changes. |

### Shared interfaces

Each layer consumes a versioned, schema-validated envelope with `subject_scope`, `input_claim_refs`, `as_of`, `producer_version`, `status`, and typed payload. Outputs carry immutable run identity, `input_digest`, exact claim/evidence references, warnings, and one of `SUPPORTED`, `PARTIAL`, `CONFLICTED`, `UNKNOWN`, `ABSTAINED`, or `FAILED`. Retries use idempotency keys; partial source failure cannot overwrite a supported snapshot. User-facing claims resolve to source title, URL, date and retained excerpt where permitted.

### Evidence classes

- `SOURCE_VERIFIED_FACT`: attributed assertion directly supported by retained source; verification applies to the specific scoped claim, not the whole document.
- `REPRODUCIBLE_CALCULATION`: deterministic output with formula version, units and exact input references.
- `ENGINEERING_ESTIMATE`: bounded scenario derived from explicit assumptions and validated inputs; never presented as observed or confirmed.
- `MODEL_INFERENCE`: model-proposed interpretation or hypothesis, schema-validated and separately attributable; not proof.
- `UNKNOWN`: evidence insufficient or absent.
- `CONTRADICTED`: material scoped claims conflict and remain visible until resolved by evidence; do not average or silently choose.

Confidence is claim- and task-specific, calibrated against labeled data, not a substitute for source authority. Current implementation has evidence packages and multiple deterministic state machines; these target labels are not implied to exist as one persisted common enum today.

### Replaceable reasoning provider (spec only)

Define an adapter contract `interpret(task, schema, evidence_refs, budget, deadline) -> validated proposal + provider/model/version + usage + trace`. The adapter has no database write, qualification, calculation, publication, or authority to modify evidence. Deterministic code validates JSON/schema, evidence citations, temporal scope, and policy. A no-provider path remains functional. Athena may implement the adapter later but is optional; provider credentials, endpoint, model and budget are configuration, and provider failure yields retry/partial/abstention. Do not duplicate Athena internals or make a model-specific payload canonical.

## NEXT

Implement the missing graph relations and deterministic equipment models first; then run independent evaluation/verification before enabling any model proposal in publication decisions. No runtime implementation is included in this documentation slice.

## EXCLUDED

Required human approval; single-model self-verification; model-authored arithmetic; provider-specific domain schema; unbounded multi-agent research; self-modifying production code.

## DEFERRED

Athena integration, broader sector lenses and autonomous policy promotion until the earlier foundations and evaluation gates pass.
