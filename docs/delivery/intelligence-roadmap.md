# Autonomous Power Demand Intelligence roadmap

**Authority:** subordinate to the [Autonomous Power Demand Intelligence Canon](../product/AUTONOMOUS_INTELLIGENCE_CANON.md). The full six-layer system is not shipped.

## Sequence

| Status | Scope | Interface and evidence | Boundary |
|---|---|---|---|
| Historical | October 29 PR150 Phase 0 documentation and audit. | Dated packet, audit, and validation remain historical evidence. | Does not restrict separately authorized implementation. |
| **Released bounded slice** | Bounded O&G source equipment parser and deterministic `Decimal` electric pump/compressor demand models. | `equipment-demand-v1`; existing `EvidencePackage`; normal and unchanged-record ingestion hooks; demand-summary API; no migration. Included in accepted Nov 2 production main `ec6486a2726758b2a9fb64a03e99276583a27a6e`; see [release receipt](../validation/production-release-20261102.md) and [slice plan](../engineering/equipment-demand-slice-20261030.md). | Does not implement all six layers or change legacy qualification. The released summary is additional-equipment scoped and had zero validated demand records at verification. |
| Next | Expand validated source/equipment coverage and lifecycle/timing interpretations; populate the deployed demand summary only from supported, scope-deduplicated evidence. | Separate documented/calculated/estimated MW; keep inferred, unknown and conflicted records distinct and out of unsupported MW totals. | Identified Power Demand (MW) remains unavailable until validated records exist; it is not a total for all facility or portfolio demand. Shortage and qualification are not demand gates. |
| Later | Commercial context and autonomous evaluation across six layers; broaden verticals when validated. | Engineer-owned tests and source/entity/demand quality measures with transparent uncertainty. | Reasoning provider optional and replaceable; no new framework or self-evaluation. |

## Compact repository disposition

| Disposition | Paths / behavior |
|---|---|
| **KEEP** | Source adapters/jobs, `EvidencePackage`, project/entity identity, intelligence-card/API/auth contracts, privacy/suppression, worker reliability, immutable history, dated receipts. |
| **EVOLVE** | Equipment/activity demand interpretation, lifecycle/timing, commercial context, independent deterministic evaluation, demand-centered results/KPI. |
| **REPLACE** | Active target language making residual gap, utility shortage, or Signal/Prospect/Lead qualification the product promise or prerequisite to demand publication. Existing runtime rules remain compatibility behavior until changed. |
| **REMOVE** | No code, schema, or historical data removal authorized. Superseded active requirements are preserved once in the dated pre-pivot archive. |
| **DEFER** | Broad sectors, advanced simulations, provider activation, automated policy/model promotion, and new frameworks/infrastructure. Any later production release needs separate current authorization and exact-candidate verification. |

Production truth for the released application is main `ec6486a2726758b2a9fb64a03e99276583a27a6e`, deployed November 2 with schema `0049_scoped_identity_browse` and 74 public tables. Exact API/web image IDs and accepted recovery/live evidence are in the [production release receipt](../validation/production-release-20261102.md). The earlier October 29 PR148 receipt remains historical evidence.
