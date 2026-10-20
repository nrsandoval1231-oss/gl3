# Sources and acquisition documentation

Use [coverage](coverage.md) for the dated source health snapshot and remaining breadth gaps. The versioned [source registry](../../config/sources/registry.v1.json) defines configured sources and policy; an enabled definition alone does not prove recent retrieval, successful parsing, broad coverage, or production scheduling.

[Onboarding](onboarding.md) defines the acceptance path for a new feed. [Ingestion strategy](ingestion-strategy.md) explains the discovery and monitoring approach. The remaining files in this directory are source-specific contracts, interpretation notes, and dated retrieval/review evidence. Their claims are limited to their named source, date, and candidate. Verify live health in the current coverage snapshot; do not use a source note to claim present availability.

The [PRD](../product/PRD.md) owns product scope and qualification. Source acquisition may preserve observations, but deterministic evidence gates decide qualification. No source note can relax those gates or authorize a new provider, paid call, or production activation.

The old source map is retained unchanged in the [documentation archive](../../.agent/archive/AUDIT-20261020/pre-docs-repair-8163f13__docs__sources__README.md).
