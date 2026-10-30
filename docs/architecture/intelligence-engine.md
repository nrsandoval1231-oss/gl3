# Intelligence engine contract

Authority: [Autonomous Intelligence Canon](../product/AUTONOMOUS_INTELLIGENCE_CANON.md) and [PRD](../product/PRD.md). This spec is TARGET unless a row explicitly says CURRENT. Routine target operation is autonomous; insufficient evidence leads to targeted research, explicit uncertainty, or abstention, never a mandatory review queue.

## CURRENT

The worker runs source collection, durable jobs and interpretation. Retained observations/evidence feed project and company resolution, power-need qualification, lifecycle/change state, enrichment/research, deterministic commercial rules and server-owned browse projections. Exact current implementation is mapped in [overview](overview.md) and [data model](data-model.md). The current candidate adds bounded, deterministic equipment-demand records through these structures. The full six-layer target and live equipment coverage are not established capabilities.

## TARGET — six-layer contracts

| Layer | Input → output | Contract and fail-closed behavior |
|---|---|---|
| 1. Discovery | Source schedules and incremental results → immutable observations and evidence versions | Preserve source identity/hash, event and retrieval times, parser version and retry outcome. |
| 2. Entity/Evidence | Evidence and candidate entities → scoped claims and supported links | Preserve temporal alternatives; distinguish organizations, sites, projects, activities, equipment and people. |
| 3. Electrical Demand | Equipment/activity claims → demand records with documented, calculated, estimated, inferred or unknown MW | Deterministic Decimal formulas own arithmetic. Unknown drive/rating does not become electric load. A record can exist with unknown MW. |
| 4. Lifecycle/Timing | Dated events and schedules → lifecycle state and bounded timing | Separate observed facts from estimates; retain source and uncertainty. |
| 5. Commercial | Demand, lifecycle and entity evidence → commercial relevance and prioritization | No utility-shortage assertion, supply-constraint gate or qualification promotion is required to characterize demand. Existing tiers remain current legacy behavior. |
| 6. Autonomous Evaluation | Frozen labeled cases and candidate versions → independent metrics and findings | Engineers own deterministic tests; candidate models do not self-evaluate. Promotion policy is future work and remains bounded/reversible. |

### Shared interfaces

Each layer consumes a versioned, schema-validated envelope with `subject_scope`, `input_claim_refs`, `as_of`, `producer_version`, `status`, and typed payload. Outputs carry immutable run identity, `input_digest`, exact claim/evidence references, warnings, and one of `SUPPORTED`, `PARTIAL`, `CONFLICTED`, `UNKNOWN`, `ABSTAINED`, or `FAILED`. Retries use idempotency keys; partial source failure cannot overwrite a supported snapshot. User-facing claims resolve to source title, URL, date and retained excerpt where permitted.

### Demand amount classes and evidence state

Demand amount classes are **documented**, **calculated**, **estimated**, **inferred**, and **unknown** as defined in the active [PRD](../product/PRD.md). These are not source verification states. Separately retain source attribution, evidence authority, freshness, conflict, correction, and supersession state. Do not silently resolve contradictions or turn an inferred/unknown amount into MW totals.

### Replaceable reasoning provider (spec only)

Define an adapter contract `interpret(task, schema, evidence_refs, budget, deadline) -> validated proposal + provider/model/version + usage + trace`. The adapter has no database write, qualification, calculation, publication, or authority to modify evidence. Deterministic code validates JSON/schema, evidence citations, temporal scope, and policy. A no-provider path remains functional. Athena may implement the adapter later but is optional; provider credentials, endpoint, model and budget are configuration, and provider failure yields retry/partial/abstention. Do not duplicate Athena internals or make a model-specific payload canonical.

## CURRENT CANDIDATE — bounded equipment slice

The candidate implements bounded source equipment parsing and deterministic `Decimal` electric-pump/compressor models, preserving source efficiency, count, operating/standby, and new-versus-existing state. The contract uses existing `EvidencePackage`, normal and unchanged-record ingestion hooks, and intelligence-card API; no migration is planned. Engineer-owned independent tests validate behavior. This is not deployed; see [implementation plan](../engineering/equipment-demand-slice-20261030.md). Broaden graph relations only for demonstrated demand-model needs. The historical Phase 0 documentation slice included no runtime implementation.

## EXCLUDED

Required human approval; single-model self-verification; model-authored arithmetic; provider-specific domain schema; unbounded multi-agent research; self-modifying production code.

## DEFERRED

Athena integration, broader sector lenses and autonomous policy promotion until the earlier foundations and evaluation gates pass.
