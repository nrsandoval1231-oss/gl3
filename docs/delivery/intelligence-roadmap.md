# Autonomous Power Demand Intelligence roadmap

**Authority:** subordinate to the [Autonomous Power Demand Intelligence Canon](../product/AUTONOMOUS_INTELLIGENCE_CANON.md). The full six-layer system is not shipped.

## Sequence

| Status | Scope | Interface and evidence | Boundary |
|---|---|---|---|
| Historical | October 29 PR150 Phase 0 documentation and audit. | Dated packet, audit, and validation remain historical evidence. | Does not restrict separately authorized implementation. |
| **Candidate implemented** | Bounded O&G source equipment parser and deterministic `Decimal` electric pump/compressor demand models. | `equipment-demand-v1`; existing `EvidencePackage`; normal and unchanged-record ingestion hooks; existing intelligence-card API; no migration; engineer-owned deterministic tests. See [slice plan](../engineering/equipment-demand-slice-20261030.md). | Not production shipped. Does not implement all six layers or change legacy qualification. |
| Next | Expand source/equipment coverage and lifecycle/timing interpretations; wire data for the implemented demand-centered UI's Identified Power Demand MW KPI. | Separate documented/calculated/estimated MW; track inferred/unknown records without unsupported MW; deduplicate by supported scope. | KPI data is currently unavailable. Shortage and qualification are not demand gates. |
| Later | Commercial context and autonomous evaluation across six layers; broaden verticals when validated. | Engineer-owned tests and source/entity/demand quality measures with transparent uncertainty. | Reasoning provider optional and replaceable; no new framework or self-evaluation. |

## Compact repository disposition

| Disposition | Paths / behavior |
|---|---|
| **KEEP** | Source adapters/jobs, `EvidencePackage`, project/entity identity, intelligence-card/API/auth contracts, privacy/suppression, worker reliability, immutable history, dated receipts. |
| **EVOLVE** | Equipment/activity demand interpretation, lifecycle/timing, commercial context, independent deterministic evaluation, demand-centered results/KPI. |
| **REPLACE** | Active target language making residual gap, utility shortage, or Signal/Prospect/Lead qualification the product promise or prerequisite to demand publication. Existing runtime rules remain compatibility behavior until changed. |
| **REMOVE** | No code, schema, or historical data removal authorized. Superseded active requirements are preserved once in the dated pre-pivot archive. |
| **DEFER** | Broad sectors, advanced simulations, provider activation, automated policy/model promotion, new frameworks/infrastructure, and production rollout absent current verification/authorization. |

Production truth remains the dated October 29 PR148 receipt: application `ca12443f5c57f3502584d8a353d83cdf7d5372b1`, schema `0049_scoped_identity_browse`, 74 public tables. It is not fresh inspection or proof that this slice is deployed.
