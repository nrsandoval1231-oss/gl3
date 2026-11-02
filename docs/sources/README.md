# Sources and acquisition documentation

The [source registry](../../config/sources/registry.v1.json) is the current configured inventory. The [October 22 regional inventory](regional-inventory-20261022.md), [regional engineering report](../operations/regional-stabilization-20261022.md) and [coverage snapshot](coverage.md) are dated evidence with historical counts and limitations, not a current source-health dashboard. The [November 2 release receipt](../validation/production-release-20261102.md) establishes application deployment and bounded worker/browse health; it does not establish completed scheduled cycles or broad source freshness. The versioned [source registry](../../config/sources/registry.v1.json) defines configured sources and policy; an enabled definition alone does not prove recent retrieval, successful parsing, broad coverage, or production scheduling.

[Onboarding](onboarding.md) defines the acceptance path for a new feed. [Ingestion strategy](ingestion-strategy.md) explains the discovery and monitoring approach. The remaining files in this directory are source-specific contracts, interpretation notes, and dated retrieval/review evidence. Their claims are limited to their named source, date, and candidate. Verify live health through a fresh authorized runtime observation; do not treat the dated coverage snapshot or a source note as present availability.

Oklahoma and New Mexico source notes for the October 23 adapters, including sources that were checked and not ingested, are in [oklahoma-new-mexico-20261023](oklahoma-new-mexico-20261023.md).

Texas power-source notes for the October 23 adapters, including sources that were checked and not ingested, are in [texas-power-sources-20261023](texas-power-sources-20261023.md).

The [Autonomous Intelligence Canon](../product/AUTONOMOUS_INTELLIGENCE_CANON.md) owns product authority; the compatible [PRD](../product/PRD.md) supplies supporting requirements. Source acquisition may preserve observations, but deterministic evidence gates decide qualification. No source note can relax those gates or authorize a new provider, paid call, or production activation.

The old source map is retained unchanged in the [documentation archive](../../.agent/archive/AUDIT-20261020/pre-docs-repair-8163f13__docs__sources__README.md).
