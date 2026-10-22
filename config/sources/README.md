# Source definitions

# Source registry

[`registry.v1.json`](registry.v1.json) is the source-definition file. Its `id`, publisher, geography, cadence, `retrieval_method`, and access/readiness metadata describe configured sources. The registry does not have a separate `parser` field: `ingestion/adapters/__init__.py` selects an adapter from `retrieval_method`.

For current source health, use [coverage](../../docs/sources/coverage.md); registry presence or an old source note does not establish a recent successful check. The onboarding process is [here](../../docs/sources/onboarding.md). Do not create parallel family YAML files.
