# Source definitions

# Source registry

[`registry.v1.json`](registry.v1.json) is the source-definition file. Its `id`, publisher, geography, cadence, `retrieval_method`, and access/readiness metadata describe configured sources. The registry does not have a separate `parser` field: `ingestion/adapters/__init__.py` selects an adapter from `retrieval_method`.

For current source health, use [coverage](../../docs/sources/coverage.md); registry presence or an old source note does not establish a recent successful check. The onboarding process is [here](../../docs/sources/onboarding.md). Do not create parallel family YAML files.

## Regional operating policy — October 22, 2026

The top-level `regional_policy` block in `registry.v1.json` owns the policy version, eligible physical-project states in priority order (`TX`, `OK`, `NM`), and locked disabled source IDs. Source `enabled` still controls configured acquisition, separately from the persisted operator switch. The seven fixed out-of-region feeds are disabled and cannot be re-enabled through source administration while locked. Four prior disabled/manual definitions remain preserved. All definitions and historical data remain retained.

National publisher/regulatory sources may be fetched upstream; their company domicile and coverage labels never establish project eligibility. The canonical backend classifier uses explicit physical-site fields and holds unknown/conflicting states. See [all29 source decisions](../../docs/sources/regional-inventory-20261022.md) and the [PRD](../../docs/product/PRD.md). Geographic expansion requires an explicit versioned policy change, reclassification, source reconciliation and a fresh published saved generation; request filters cannot expand territory.
