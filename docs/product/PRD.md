# GridLens — Product Requirements Document

**Version:** Demand-centered scope · 2026-10-30
**Status:** Active requirements subordinate to the sole [Autonomous Power Demand Intelligence Canon](AUTONOMOUS_INTELLIGENCE_CANON.md).
**Product owner:** Nick Sandoval

The prior gap-led PRD is retained as [dated pre-pivot history](../../.agent/archive/DEMAND-CENTERED-PIVOT-20261030/PRD-pre-pivot-20261029.md). It records historical qualification requirements and is not active product authority.

## Product outcome

GridLens autonomously discovers electrical demand, identifies the entities, projects, activities, and equipment behind it, characterizes supported MW and timing, and derives useful commercial context. A demand record may exist when MW is unknown. Utility supply, shortage, residual gap, buyer identity, and legacy qualification are not prerequisites to demand discovery or characterization.

The target pipeline has six layers: **Discovery → Entity/Evidence → Electrical Demand → Lifecycle/Timing → Commercial → Autonomous Evaluation.** The full pipeline is not shipped. The current bounded O&G equipment slice is described in the [implementation plan](../engineering/equipment-demand-slice-20261030.md).

## Demand records and evidence

Each demand record has supported project/activity/equipment scope, source references, source/retrieval dates where available, parser/calculation version, units, and an explicit amount class:

- **Documented:** source directly states the electrical demand value and basis.
- **Calculated:** deterministic arithmetic from cited inputs and a versioned formula.
- **Estimated:** a bounded engineering estimate with stated assumptions and range.
- **Inferred:** interpretation supported by cited evidence but not directly stated or deterministically calculated.
- **Unknown:** demand or activity is identified, but evidence does not establish an amount.

Conflicting, stale, or incomplete evidence remains explicit. Never convert unknown to zero, infer electric load from unknown/non-electric drive, double-count equipment or phases, or present an estimate as documented fact. Report documented, calculated, and estimated MW separately. Inferred/unknown records remain countable as records but do not contribute fabricated MW.

## Six target layers

1. **Discovery:** collect and incrementally refresh evidence with durable jobs, provenance, bounded retries, and source health.
2. **Entity/Evidence:** bind claims to the correct organization, site, project, phase, activity, and equipment; preserve alternatives, time, conflicts, and source identity.
3. **Electrical Demand:** produce documented/calculated/estimated/inferred/unknown demand records with reproducible arithmetic and explicit assumptions.
4. **Lifecycle/Timing:** record observed milestones and clearly separate bounded estimates; never invent dates.
5. **Commercial:** connect demand to relevant organizations, roles, and commercial context. Demand characterization does not assert a utility shortage or require qualification.
6. **Autonomous Evaluation:** engineers own independent deterministic tests and evaluation. Candidate models do not evaluate themselves. Track quality by source, entity class, demand type, and uncertainty.

These are target boundaries, not claims of current end-to-end operation. Athena may be a future replaceable reasoning provider; the product functions without it and requires no new framework.

## First implementation slice

The candidate slice parses a bounded O&G pump/compressor cohort and computes electrical demand with `Decimal`. It uses `equipment-demand-v1` on existing `EvidencePackage` records, normal and unchanged-record ingestion hooks, and the existing intelligence-card API contract for demand records. No migration is planned. It preserves source efficiency/rating basis, count, operating/standby state, new/existing classification, and project/evidence binding. Engineer-owned deterministic tests cover arithmetic and negative cases. It is not the full six-layer pipeline or a production deployment.

## Primary measure and presentation

Primary KPI: **Identified Power Demand MW**. Report documented, calculated, and estimated MW separately, deduplicated by supported demand/equipment scope. Also report identified records whose MW is unknown. Inferred amounts do not enter documented/calculated/estimated totals.

Demand-centered UI changes are implemented in the current candidate, but the Identified Power Demand MW KPI data is unavailable and must remain explicitly unavailable rather than fabricated. This candidate is not production shipped. The October 29 UI remains the dated production presentation. Preserve evidence access, responsive behavior, privacy, and authentication.

## Current runtime compatibility

The current application retains regional TX/OK/NM policy and Signal/Prospect/Lead qualification, including historical 300 kW behavior where implemented. These are legacy compatibility semantics and may evolve separately. They do not define a target demand record, require a supply-gap assertion, or gate demand representation. Preserve dated production facts and historical records; do not imply fresh production inspection from this PRD.

## Compact implementation disposition

| Disposition | Scope |
|---|---|
| **KEEP** | Source adapters, immutable evidence and `EvidencePackage`, entity/project identity, incremental ingestion, API/auth, privacy/suppression, worker reliability, dated release receipts. |
| **EVOLVE** | Equipment/activity demand records, lifecycle/timing, entity/evidence binding, commercial context, deterministic evaluation, demand-centered presentation. |
| **REPLACE** | Active target language making utility shortage, residual gap, or Signal/Prospect/Lead qualification the product promise or prerequisite to demand representation. Legacy runtime qualification remains compatible until changed. |
| **REMOVE** | No historical data or code removal is authorized. Superseded active requirements are retained once in the dated archive. |
| **DEFER** | Broad vertical coverage, advanced simulations, provider activation, automated model/policy promotion, new infrastructure/frameworks, and production rollout without current verification/authorization. |

## Historical production boundary

Latest available receipt is dated October 29, 2026: PR148 application `ca12443f5c57f3502584d8a353d83cdf7d5372b1`, migration `0049_scoped_identity_browse`, 74 public tables. It is historical production evidence, not a fresh inspection and not proof that the in-progress slice is deployed.
