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
| change_events | Material opportunity state transitions, separate from raw intake or repeated checks. |

An observation envelope can point at a newer content hash while old evidence remains. Reappearance of a previously seen version must reuse retained evidence without a uniqueness error. Alternate representations require explicit shared identity and do not create a second project or corroborating source claim.

The initial implementation uses ordinary relational tables. It does not introduce a configurable ontology or import schemas from older GridLens repositories. User notes, detailed supply scenarios, and later assessments remain governed future scope. Merged GL3-017 buying-chain tables and the GL3-018 admission column are below.

## GL3-017 project-scoped enrichment

The merged buying chain adds `buying_chain_evidence`, `buying_chain_claims` and
`buying_chain_runs`, all bound to existing `projects.id`. An enrichment excerpt
may reference an existing `evidence.id`; otherwise its public source URL, content
hash, extraction location and dates are retained. Claim snapshots distinguish
project–organization, organization–person/current role and person–project links.
Organizations and people remain project-scoped normalized identities, not a
cross-project contacts database. Semantic versions and replay retain prior
claims. Neither PowerNeed tier nor source observations are changed.

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
