# Power demand intelligence — first equipment slice

**Candidate implementation, October 30, 2026; not deployed.** Authority: [product canon](../product/AUTONOMOUS_INTELLIGENCE_CANON.md). Validation and limitations are recorded in [the candidate receipt](../validation/equipment-demand-20261030.md).

## Audit: current versus target

Audit base: `a65b0d1d3196914699e3446447246c4e7b10f598`, fetched after PR150's documentation alignment and PR149's Vite fix. PR145/146 performed cleanup; neither implemented equipment demand. Existing FastAPI, workers, PostgreSQL, and React already provide evidence versions, conservative identities, regional source admission, qualification and authenticated company/project browsing. The missing path was explicit equipment inputs through deterministic demand to a persisted, inspectable commercial result. Oklahoma source admission also required data-center or temporary/bridge-power context; that blocked demand alone.

| Disposition | Paths / responsibility | Decision |
|---|---|---|
| KEEP | `ingestion/adapters/`, registry, `jobs/worker.py` | Preserve official retrieval, schedules, retries, fences, idempotency and out-of-region adapter history. |
| KEEP | `persistence/models.py`, `backend/migrations/` | Reuse `EvidencePackage`, `Evidence`, `Project`, `PowerNeed` and `NeedObservation`; no migration or extra service. |
| EVOLVE | `domain/permit_interpretation.py` | Narrow Oklahoma DEQ admission for an explicit valid O&G equipment schedule, independent of supply or temporary-power tags. Existing qualification remains compatible. |
| EVOLVE | `ingestion/parsers/equipment.py`, `domain/equipment_demand.py` | Add bounded explicit schedule extraction and versioned deterministic arithmetic. |
| EVOLVE | `intelligence/equipment_intelligence.py`, `ingestion/service.py` | Freeze/replay source-bound demand records and expose only current, recomputed, validated results. |
| EVOLVE | Domain/repository `opportunity_intelligence.py`, canonical workspace components | Add demand detail and terminology through existing authenticated contracts. Preserve the layout and brand. |
| REPLACE | Active PRD/results canon and gap-led product definitions | Demand is central. Preserve the preceding documents in the indexed dated archive. |
| REMOVE | None | No useful runtime, migration, historical evidence or test deleted. |
| DEFER | Live engineering-document acquisition, broader sectors, portfolio demand ranking/totals, buyer automation extensions, Athena | Require source evaluation and independently measured scope; no new infrastructure or paid-provider activation. |

## PR152 integration

Main advanced during validation to `d54646c1600ff4f658d765fa0acf749a4166803c` (PR152). Its `domain/equipment_claims.py` and `domain/equipment_evidence.py` are preserved as strict, unverified candidate/extraction contracts with historic source fixtures. They do not perform demand arithmetic. The later [native notice slice](native-equipment-demand-20261030.md) now consumes these candidates through an explicit source-bound conversion; candidates remain UNVERIFIED. The bounded schedule parser and `equipment-demand-v1` receipt use separate calculation inputs and independent current-database/source verification; structural candidate validity never certifies a demand result. Broader document extractors must preserve that explicit conversion and its uncertainty checks. Consolidation must preserve unsupported states and source binding rather than blindly casting between the two contracts.

## Implemented path

A representative official O&G schedule enters ordinary `process_records`. Exact company and facility headers, dated regional source context, and at least one new/proposed electric compressor or pump permit Signal discovery without a utility shortage or rental hypothesis. Missing motor efficiency does not prevent the demand investigation record. Gas-only, malformed or mismatched schedules cannot use this new admission path.

The parser accepts bounded, labeled equipment rows and preserves exact character spans. It distinguishes drive, rating basis, units, counts, normal operating count, standby, new/existing state and explicit dates. Unrecognized equipment rows make extraction incomplete rather than silently reducing totals. General prose and PDF-table interpretation remain unsupported. The later [native notice slice](native-equipment-demand-20261030.md) adds one bounded FERC notice layout with original source spans.

`equipment-demand-v1` uses existing immutable evidence-package storage, with source, semantic, model and extractor versions. Stable input fingerprints avoid repeating extraction/calculation on unchanged ingestion; the normal and unchanged-record hooks share the caller's transaction and fencing. Read projection independently checks current accepted source/project/activity binding and recomputes the entire stored result. Old receipts remain history. No legacy provider package can accept this contract.

Calculations use a fixed Decimal context: shaft hp × 0.745699872; electric input divides shaft kW only by an explicit efficiency. kVA requires power factor and is never treated as mechanical power. Count, simultaneous operation and utilization are separate. Standby stays connected but is excluded from normal coincidence; existing equipment is not incremental. Future proposed capacity retains its documented timing and planned label. Missing inputs remain unknown, not default assumptions. Duplicate unit IDs deduplicate; contradictions and overlapping documents abstain. Different document dates/calculated quantities cannot be arbitrarily selected or summed.

The record connects source-reported company and physical facility to existing project/need IDs. It retains classifications, inputs, model versions, lifecycle/timing, evidence, unknown buyer and recommended investigation. Company headers do not establish a verified company identity or buyer. Existing sourced contact attribution remains available on the enclosing intelligence card. Calculated equipment scope never overwrites legacy qualified MW, facility demand or a supply gap.

The approved workspace gains a compact schedule assessment with planned/current labels, dates, capacities and next action. **Identified Power Demand (MW)** is explicitly unavailable: there is no defensible cohort-wide aggregate yet. No page-only sum, fake zero or verified-total claim is made.

## Evaluation and next work

Deterministic regression tests are the promotion gate for this parser/model version. They cover unit conversion, efficiency, drive, standby, simultaneous counts, duplicates, contradictions, dates, malformed input, exact evidence/entity binding, stale withdrawal, immutable replay, normal ingestion and API/card compatibility. These are controlled synthetic cases, not a measured real-world extraction-accuracy claim. Candidate changes require independent review and full CI; no self-modifying production code or automatic model promotion exists.

Next, in commercial-value order:

1. Acquire and evaluate a permitted, representative real O&G engineering-document corpus; add extraction for its actual layouts through existing bounded workers.
2. Add source-backed corporate identity/buyer attribution and targeted investigation for missing specifications and contradictions, preserving existing privacy and budgets.
3. Add deduplicated cohort-wide demand summaries and demand-first ranking, with explicit facility/equipment overlap and classification rules.
4. Extend the same demand contract to data-center phases and additional equipment models, with separately validated scenarios and lifecycle rules.

No live source coverage, buyer verification, deployment, or production readiness is established by this candidate. The latest available production receipt remains the dated October 29 PR148 application `ca12443f5c57f3502584d8a353d83cdf7d5372b1`, schema `0049_scoped_identity_browse`, 74 tables; it was not freshly inspected.
