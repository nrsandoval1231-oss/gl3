# Documentation map

Start with [AGENTS.md](../AGENTS.md). For current deployment facts, use the accepted [November 2 production release receipt](validation/production-release-20261102.md) and its [sanitized machine receipt](validation/production-release-20261102.json). The [Autonomous Intelligence Canon](product/AUTONOMOUS_INTELLIGENCE_CANON.md) remains the sole active product authority; supporting documents remain compatible and dated reports prove only their named candidate and environment.

| Need | Maintained entry point |
|---|---|
| Current production revision and verification | [November 2 release receipt](validation/production-release-20261102.md), [sanitized machine receipt](validation/production-release-20261102.json) |
| Product and commercial integrity | [Autonomous canon](product/AUTONOMOUS_INTELLIGENCE_CANON.md), [operator/customer results](product/PROJECT_FIRST_RESULTS_CANON.md), compatible [PRD](product/PRD.md) |
| UI and brand | [UI canon](design/UI_CANON.md), [brand assets](design/BRAND_ASSETS.md) |
| Architecture and data | [Overview](architecture/overview.md), [retention map](architecture/autonomous-intelligence.md), [data model](architecture/data-model.md) |
| Current work and verification | [Checkpoint](../.agent/CURRENT_STATE.md), [finish contract](../.agent/FINISH_CONTRACT.md), [cleanup manifest](engineering/streamlining-20261029.md) |
| Ingestion strategy and build (owner-authorized Nov 3) | [Claude Code handoff](strategy/ingestion-handoff-20261103.md), [ingestion strategy](strategy/ingestion-strategy-20261103.md), [supporting research](strategy/ingestion-research-20261103.md), [workstream 0 env proposal](strategy/ws0-production-env-changes-20261103.md), [workstream 1 extraction spike](strategy/ws1-extraction-spike-20261103.md), [workstream 1a permit extraction core](engineering/permit-document-extraction-20261103.md), [workstream 1b TCEQ application documents](engineering/tceq-application-documents-20261103.md), [workstream 1c OK DEQ permit documents](engineering/okdeq-permit-documents-20261103.md), [workstream 2a live Jev mode](engineering/jev-live-mode-20261103.md), [owner request](../.agent/OWNER_REQUEST.md) |
| Sources and configuration | [Coverage](sources/coverage.md), [registry](../config/sources/registry.v1.json), [runtime configuration](operations/runtime-configuration.md) |
| Development and validation | [README](../README.md), [local runtime](operations/local-runtime.md), [scripts](../scripts/README.md), [CI](../.github/workflows/ci.yml) |
| Deployment and recovery | [Operations](operations/README.md), [runtime recovery](operations/runtime-recovery.md), [local restore drill](operations/local-restore-drill.md) |

## Historical evidence

[Validation records](validation/), [agent archive](../.agent/archive/), dated operations reports and [design screenshots](design/screenshots/) retain previous plans, failed runs, release receipts and review evidence. Historical authorizations never apply automatically to a new candidate. The [2026-10-29 archive](../.agent/archive/STREAMLINING-20261029/README.md) preserves superseded active instructions verbatim; the [2026-10-20 inventory](../.agent/archive/AUDIT-20261020/DOCUMENTATION-INVENTORY-20261020.md) and [2026-10-26 archive](../.agent/archive/AUTONOMOUS-20261026/README.md) index earlier governance history. Some dated reports reference ignored receipts unavailable in a clean checkout; do not invent replacements or interpret them as current operational proof.

## Intelligence consolidation — CURRENT / TARGET / NEXT / DEFERRED

CURRENT implementation and TARGET contracts are separated in the [architecture](architecture/overview.md), [engine](architecture/intelligence-engine.md), [data model](architecture/data-model.md), [demand models](architecture/demand-models.md) and [verification/evaluation](architecture/verification-evaluation.md). NEXT work is sequenced in the [roadmap](delivery/intelligence-roadmap.md) and [current equipment-demand audit](engineering/equipment-demand-slice-20261030.md); the [Phase 0 audit](engineering/intelligence-phase0-audit-20261029.md) preserves the earlier baseline. DEFERRED engine capabilities are specifications, not shipped functionality. Replaced authority bytes are retained in the [Phase 0 archive](../.agent/archive/INTELLIGENCE-PHASE0-20261029/README.md).

The deployed Nov 2 application includes the bounded [O&G equipment-demand slice](engineering/equipment-demand-slice-20261030.md) and its `equipment-demand-v1` summary contract. The current release reported zero validated equipment-demand records, so its additional-equipment demand summary remains unavailable; it does not represent total portfolio demand. Earlier [PR152 equipment claim-map verification](validation/og-equipment-claims-20261029.md) and the [native FERC notice extension](engineering/native-equipment-demand-20261030.md) are separate dated evidence; they do not establish broad or scheduled source coverage.
