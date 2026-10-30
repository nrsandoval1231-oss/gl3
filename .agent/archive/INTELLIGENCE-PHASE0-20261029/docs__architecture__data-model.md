# Data model — first slice

| Table | Role and boundary |
|---|---|
| sources | Stable configured publisher endpoint, coverage/cadence and latest source health. Registry describes intended collection; durable state describes actual attempts. |
| jobs | Durable queued/running/succeeded/failed execution, attempts, available time, lease owner/expiry/fence and checkpoint. |
| observations | One current record envelope per source+external ID, preserving first-seen identity and current version hash. |
| evidence | Immutable source-content versions, linked to observation, retaining original date, URL, excerpt, retrieval time/hash and extraction location. |
| interpretations | Pending/accepted/rejected/failed interpretation state so preserved observations can be retried independently. |
| projects | Conservative stable-record identity; name alone cannot merge sites. |
| power_needs | Separate activity per project, evidence tier, rationale, unknown scope fields, active state, and `admission_basis` provenance. No campus-MW inference. |
| need_observations | Explicit evidence relationship between needs and observations. |
| change_events | Immutable accepted project-state transitions with prior/new snapshots, source date, replay identity and material flag. `evidence_id` anchors source Evidence; `buying_chain_evidence_id` anchors a contractor/buyer transition to the immutable buying-chain document version that actually supports it. The two source references are kept distinct. |
| project_material_states | Current compact material snapshot and monotonic revision per Project, used under project serialization to compare actual accepted state and recognize reversions. |
| evidence_judge_runs | Bounded TypeSafe EvidenceJudge attempt/result metadata, deterministic comparison, status and measured usage. Input identity makes retries/replays idempotent; pending attempts remain visible after interruption. This table never drives accepted domain state. |

An observation envelope can point at a newer content hash while old evidence remains. Reappearance of a previously seen version must reuse retained evidence without a uniqueness error. Alternate representations require explicit shared identity and do not create a second project or corroborating source claim.

The implementation uses ordinary relational tables and does not import schemas from older GridLens repositories. User notes, supply scenarios and commercial assessments now have persisted models; their presence does not establish complete commercial or live-provider acceptance. Merged GL3-017 buying-chain tables and the GL3-018 admission column are below; current migrations are the authoritative schema inventory.

Migration `0012_evidence_graph_jev_shadow` adds these small relational projections. `project_material_states` contains only semantic accepted fields; retrieval metadata, updated timestamps and rationale-only churn are excluded. Project locking encloses prior-state reads, writes, diffs and revision updates. Legacy state is seeded without manufacturing a discovery event. `EvidenceJudgeRun` is separate from `signal_adjudication` and is written only by explicit shadow execution; normal ingestion remains provider-independent.

Accepted contractor and buyer changes cite their supporting immutable `BuyingChainEvidence` through `change_events.buying_chain_evidence_id` and leave the generic `evidence_id` unset. Contractor/buyer removals use a checked replacement found at the prior claim's URL when one exists. The authenticated morning `/api/changes` feed resolves either source reference to the actual source title and URL while retaining its existing response shape.

## GL3-017 project-scoped enrichment

The merged buying chain adds `buying_chain_evidence`, `buying_chain_claims` and
`buying_chain_runs`, all bound to existing `projects.id`. An enrichment excerpt
may reference an existing `evidence.id`; otherwise its public source URL, content
hash, extraction location and dates are retained. Claim snapshots distinguish
project–organization, organization–person/current role and person–project links.
Claims remain project-scoped. Later company/person identity tables and reviewed
identity links can associate supported claims across projects; name similarity
alone is not authority to merge them. Semantic versions and replay retain prior
claims. Neither PowerNeed tier nor source observations are changed by identity linking.

`BuyingChainEvidence.observed_at` is immutable first observation; `last_seen_at`
records verified reobservation without creating a content version. Run evidence
and claim IDs identify the currently accepted snapshot, including A→B→A source
reversions. A failed or bounded-out source does not erase accepted evidence;
checked replacements and independent unresolved role conflicts remain distinct.

## GL3-018 admission provenance

`power_needs.admission_basis` is non-null JSON. Accepted needs store
`signal-admission-v1`, an origin label, reason, source id, and evidence hash.
Migration `0009_signal_admission` closes active needs that lack a current exact
authoritative link and stores their prior active flag and tier inside that JSON.
It does not delete projects, observations, evidence, or links. News and planning
context can remain stored without an active standalone Signal.
