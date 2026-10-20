# Source coverage

Observed 2026-10-20. The authoritative source inventory and enabled state are in [`registry.v1.json`](../../config/sources/registry.v1.json); source-specific limits and evidence interpretation belong in the linked source notes. Collection breadth is not nationwide completeness.

The production registry had 26 entries. Recent successes were mixed: 19 entries had a recent success, while Boston, Chicago and Georgia last succeeded October 14. California CEQAnet, TCEQ NSR and Houston had no successful check. TDLR remained disabled in the registry. These dated observations are not a claim that every enabled source is healthy or current.

The PRD launch requirement remains open: 12 independent feeds across five source families, two national structured sources, and three industries, with seven measured daily cycles and reviewed opportunity evidence. Source count alone does not satisfy it. See [delivery status](../delivery/milestones.md) for release gates and [operations status](../operations/README.md) for the production observation and its limits.

On October 20, the owner authorized site-specific news to create standalone discovery Signals while leaving power facts unknown and Prospect/Lead gates unchanged. The repository implements versioned admission and bounded retained reassessment; see [news interpretation and its measured limits](project-interpretation.md). Frozen positive holdouts exposed misses and were subsequently used for development; prospective generalization remains unverified. This implementation is not deployed by this remediation. See the exact [owner decision](../decisions.md#owner-decision-october-20-2026-site-specific-news-may-create-discovery-signals).

## Authorities

- [Source onboarding](onboarding.md): acquisition requirements and access boundaries.
- [Source notes](.): source-specific behavior and limitations.
- [PRD](../product/PRD.md): product scope and evidence requirements.

Older source audits and local retrieval reports are dated evidence. They describe only their named candidate and observation period.
