# Data model: current facts and target extensions

Authority: [Autonomous Intelligence Canon](../product/AUTONOMOUS_INTELLIGENCE_CANON.md). CURRENT describes repository structures; TARGET/NEXT are design only. Migrations in `backend/migrations/versions/` and ORM definitions in `backend/src/gridlens/persistence/models.py` are authoritative for actual schema.

## CURRENT — implemented relational model

| Concept | Implemented structures | Meaning / boundary |
|---|---|---|
| Source and collection | `sources`, `source_schedule_epochs`, `source_due_checks`, `source_check_receipts`, `source_collection_progress`, `jobs`, `observations` | Registry, durable scheduling/attempts, checkpoints and one observation per source/external ID. |
| Immutable evidence | `evidence`, `evidence_packages`, `interpretations` | Content versions are unique by observation/hash; preserve source URL, dates, extraction location and provenance. Evidence packages bind evidence hash, extractor/question versions and provider metadata. |
| Project/activity | `projects`, `project_lifecycles`, `lifecycle_events`, `power_needs`, `need_observations` | Conservative project identity; a need is an activity/project-level qualification unit, not a full equipment inventory. |
| Facts and state | `call_fact_versions`, `call_fact_decisions`, `change_events`, `project_material_states`, `signal_decisions` | Effective-dated accepted/corrected/rejected facts; immutable transitions and compact current snapshots. Historical operator facts are preserved. |
| Commercial identity | `company_identities`, `person_identities`, `identity_identifiers`, `company_project_memberships`, `buying_chain_evidence`, `buying_chain_claims`, corrections and identity links | Company/person identities can associate with multiple projects; roles and claims retain evidence and project scope. Name similarity alone is not merge authority. |
| Evaluation/operations | `evidence_judge_runs`, logical-call budgets/settlements, source receipts, worker heartbeats | Bounded operational/accounting and optional shadow/advisory evaluations; not a general evaluation corpus or autonomous promotion system. |
| Publication | `browse_*`, pursuit and assessment tables | Read projections and commercial research state. They do not make missing evidence known. |

## TARGET — temporal, many-to-many claim model

Represent the product graph as Company ↔ Facility ↔ Project ↔ Phase ↔ Equipment ↔ Demand Scenario ↔ Supply Constraint ↔ Procurement Event ↔ Decision-Maker. Relationships are many-to-many where real ownership, operation, contracting, equipment serving, supply coverage, or buyer authority crosses entity boundaries. A project may have multiple facilities/phases; a company may own or operate multiple projects; a source claim can support or contradict multiple scoped assertions without being copied as independent corroboration.

Every assertion should carry: stable claim/subject/predicate/object identity; source and immutable evidence-version reference; source-published/event date (if known); first observed/retrieved time; validity interval (effective-from/until); extraction and rule/model version; units and scope; evidence class; verification/conflict state; and correction/supersession linkage. Preserve competing claims and history. Do not overwrite an old claim when a later source disagrees. A source reappearance must not create duplicate evidence or extra corroboration.

Unknown, contradicted, stale and absent are distinct states. Missing supply is not zero; missing equipment drive is not electric; missing timing is not a predicted date. Derived values link to exact input claim IDs/hashes and formula version. Identity resolution links require evidence and retain prior decisions.

## NEXT — additive migration slices

1. Inventory existing claim JSON and relationship tables against the target contract; map, do not replace, existing projects, needs, company identities and evidence IDs.
2. Add only missing equipment, phase, scenario, supply-coverage and procurement-event relations with effective dates and source references. Use ordinary PostgreSQL unless measured query needs justify otherwise.
3. Backfill only values derivable from retained evidence; leave unavailable fields null/unknown. Provide dual-read compatibility, bounded backfill, rollback plan and cross-project isolation tests.

## DEFERRED

A property graph store; global merge by string similarity; copying each source into multiple synthetic corroboration records; destructive replacement of current IDs or migration history; schema claims based on proposed tables.

See [intelligence engine](intelligence-engine.md), [demand models](demand-models.md) and [verification/evaluation](verification-evaluation.md).
