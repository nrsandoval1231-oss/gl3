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

## TARGET — demand-centered temporal claim model

Represent the product graph around scoped demand: Organization ↔ Site/Facility ↔ Project ↔ Phase/Activity ↔ Equipment ↔ Demand Record, with lifecycle events and commercial roles linked when evidenced. Supply and procurement facts are optional context, not required graph nodes or publication gates. Relationships are many-to-many where ownership, operation, contracting, equipment service, or commercial roles cross entity boundaries. A source claim can support or contradict multiple scoped assertions without being copied as independent corroboration.

Every assertion should carry: stable claim/subject/predicate/object identity; source and immutable evidence-version reference; source-published/event date (if known); first observed/retrieved time; validity interval (effective-from/until); extraction and rule/model version; units and scope; evidence class; verification/conflict state; and correction/supersession linkage. Preserve competing claims and history. Do not overwrite an old claim when a later source disagrees. A source reappearance must not create duplicate evidence or extra corroboration.

Unknown, contradicted, stale and absent are distinct states. Missing equipment drive is not electric; missing timing is not a predicted date. Derived values link to exact input claim IDs/hashes and formula version. Demand may be represented with unknown MW. Identity resolution links require evidence and retain prior decisions.

## NEXT — evolve existing contracts only as demonstrated

1. Reuse `EvidencePackage` and existing project/need relationships for the candidate `equipment-demand-v1` slice; no migration is planned for that slice.
2. Map real source/project/equipment cases to existing structures. Add or evolve persistence only when a demonstrated gap blocks a demand record, with compatibility and rollback evidence.
3. Preserve all historical IDs and claims; never backfill unsupported values or make supply/qualification mandatory for demand records.

## DEFERRED

A property graph store; global merge by string similarity; copying each source into multiple synthetic corroboration records; destructive replacement of current IDs or migration history; schema claims based on proposed tables.

See [intelligence engine](intelligence-engine.md), [demand models](demand-models.md) and [verification/evaluation](verification-evaluation.md).
