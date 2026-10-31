# Documentation map

Start with [AGENTS.md](../AGENTS.md). The [Autonomous Intelligence Canon](product/AUTONOMOUS_INTELLIGENCE_CANON.md) is the sole active product authority; supporting documents remain compatible and dated reports prove only their named candidate and environment.

| Need | Maintained entry point |
|---|---|
| Product and commercial integrity | [Autonomous canon](product/AUTONOMOUS_INTELLIGENCE_CANON.md), [operator/customer results](product/PROJECT_FIRST_RESULTS_CANON.md), compatible [PRD](product/PRD.md) |
| UI and brand | [UI canon](design/UI_CANON.md), [brand assets](design/BRAND_ASSETS.md) |
| Architecture and data | [Overview](architecture/overview.md), [retention map](architecture/autonomous-intelligence.md), [data model](architecture/data-model.md) |
| Current work and verification | [Checkpoint](../.agent/CURRENT_STATE.md), [finish contract](../.agent/FINISH_CONTRACT.md), [cleanup manifest](engineering/streamlining-20261029.md) |
| Sources and configuration | [Coverage](sources/coverage.md), [registry](../config/sources/registry.v1.json), [runtime configuration](operations/runtime-configuration.md) |
| Development and validation | [README](../README.md), [local runtime](operations/local-runtime.md), [scripts](../scripts/README.md), [CI](../.github/workflows/ci.yml) |
| Deployment and recovery | [Operations](operations/README.md), [runtime recovery](operations/runtime-recovery.md), [local restore drill](operations/local-restore-drill.md) |

## Historical evidence

[October 30–31 audit and validation archive](validation/audit-evidence-20261031/README.md) preserves the audit, independent reviews, failed and successful validation receipts, and PR160/161 post-merge evidence. Its index distinguishes superseded findings, unresolved work and the deployment hold.

[Validation records](validation/), [agent archive](../.agent/archive/), dated operations reports and [design screenshots](design/screenshots/) retain previous plans, failed runs, release receipts and review evidence. Historical authorizations never apply automatically to a new candidate. The [2026-10-29 archive](../.agent/archive/STREAMLINING-20261029/README.md) preserves superseded active instructions verbatim; the [2026-10-20 inventory](../.agent/archive/AUDIT-20261020/DOCUMENTATION-INVENTORY-20261020.md) and [2026-10-26 archive](../.agent/archive/AUTONOMOUS-20261026/README.md) index earlier governance history. Some dated reports reference ignored receipts unavailable in a clean checkout; do not invent replacements or interpret them as current operational proof.

## Intelligence consolidation — CURRENT / TARGET / NEXT / DEFERRED

CURRENT implementation and TARGET contracts are separated in the [architecture](architecture/overview.md), [engine](architecture/intelligence-engine.md), [data model](architecture/data-model.md), [demand models](architecture/demand-models.md) and [verification/evaluation](architecture/verification-evaluation.md). NEXT work is sequenced in the [roadmap](delivery/intelligence-roadmap.md) and [current equipment-demand audit](engineering/equipment-demand-slice-20261030.md); the [Phase 0 audit](engineering/intelligence-phase0-audit-20261029.md) preserves the earlier baseline. DEFERRED engine capabilities are specifications, not shipped functionality. Replaced authority bytes are retained in the [Phase 0 archive](../.agent/archive/INTELLIGENCE-PHASE0-20261029/README.md).

Delivered PR152 candidate foundation: [O&G equipment claim map](architecture/og-equipment-claim-map.md), [historical implementation packet](../.agent/packets/OG-EQUIPMENT-CLAIMS-20261029.md), and [verification](validation/og-equipment-claims-20261029.md). Its outputs remain UNVERIFIED. The separate [PR153 equipment-demand slice](engineering/equipment-demand-slice-20261030.md) adds bounded calculation, evidence verification, persistence and opportunity integration; its remaining work and validation are explicit. The [native FERC notice extension](engineering/native-equipment-demand-20261030.md) records real-document processing, limits, and validation separately from live source coverage.
