# Data model — first slice

| Table | Role and boundary |
|---|---|
| sources | Stable configured publisher endpoint, coverage/cadence and latest source health. Registry describes intended collection; durable state describes actual attempts. |
| jobs | Durable queued/running/succeeded/failed execution, attempts, available time, lease owner/expiry/fence and checkpoint. |
| observations | One current record envelope per source+external ID, preserving first-seen identity and current version hash. |
| evidence | Immutable source-content versions, linked to observation, retaining original date, URL, excerpt, retrieval time/hash and extraction location. |
| interpretations | Pending/accepted/rejected/failed interpretation state so preserved observations can be retried independently. |
| projects | Conservative stable-record identity; name alone cannot merge sites. |
| power_needs | Separate activity per project, evidence tier, rationale, unknown scope fields and active state. No campus-MW inference. |
| need_observations | Explicit evidence relationship between needs and observations. |
| change_events | Material opportunity state transitions, separate from raw intake or repeated checks. |

An observation envelope can point at a newer content hash while old evidence remains. Reappearance of a previously seen version must reuse retained evidence without a uniqueness error. Alternate representations require explicit shared identity and do not create a second project or corroborating source claim.

The initial implementation uses ordinary relational tables. It does not introduce a configurable ontology or import schemas from older GridLens repositories. Organization/contact, user notes, detailed supply scenarios and later assessments remain governed future scope.
