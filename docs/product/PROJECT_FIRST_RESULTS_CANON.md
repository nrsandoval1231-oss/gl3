# Demand-Centered Results Canon

**Status:** Active target presentation semantics · 2026-10-30
**Authority:** Subordinate to the [Autonomous Power Demand Intelligence Canon](AUTONOMOUS_INTELLIGENCE_CANON.md). Current released UI and API behavior are dated in [release receipts](../validation/).

The prior operator/customer presentation specification is preserved as [dated pre-pivot history](../../.agent/archive/DEMAND-CENTERED-PIVOT-20261030/PROJECT_FIRST_RESULTS-pre-pivot-20261029.md). The October 29 UI remains released production truth. Demand-centered UI changes exist in the current candidate; the Identified Power Demand MW KPI data is unavailable and is not fabricated. Candidate changes are not production shipped.

## Target result

Center results on identified electrical demand and show its supported scope, amount class, lifecycle/timing, evidence, and uncertainty. Organization, project, and contact context support interpretation. A demand record may have unknown MW. Neither utility shortage nor Signal/Prospect/Lead qualification is required to show demand.

Primary KPI: **Identified Power Demand MW**, with documented, calculated, and estimated values reported separately and deduplicated by supported scope. Inferred and unknown amounts do not enter those MW totals. Report identified records with unknown MW separately. Do not use raw record count as MW or imply missing MW is zero.

## Amount classes

- **Documented:** source states amount and electrical basis.
- **Calculated:** deterministic arithmetic with cited inputs and formula version.
- **Estimated:** bounded scenario with explicit assumptions and uncertainty.
- **Inferred:** evidence-supported interpretation that is neither directly stated nor deterministically calculated.
- **Unknown:** activity or demand is identified but the amount is unsupported.

Every displayed amount links to source or input evidence, units, scope, and relevant extraction/calculation version. Preserve conflicting and superseded claims. Keep facility capacity distinct from activity demand and connected capacity distinct from time-average energy.

## Commercial context and current compatibility

Show organization/project/equipment identity, location, dates, contacts, and commercial relevance only when supported. Contact method does not establish buyer authority. Current project table, filters, and Signal/Prospect/Lead labels remain legacy presentation/runtime behavior until updated; they are not target demand definitions. Do not rank demand primarily by residual supply gap or qualify it by shortage evidence.

Keep privacy, source provenance, safe pagination, and responsive access. The current candidate implements demand-centered UI, but KPI data remains unavailable. Do not describe candidate changes as shipped.

## Historical implementation boundary

The in-progress equipment slice uses existing `EvidencePackage` and intelligence-card API contracts, with no migration planned. The latest available production receipt is dated October 29, 2026: PR148 application `ca12443f5c57f3502584d8a353d83cdf7d5372b1`, schema `0049_scoped_identity_browse`, 74 public tables. This receipt does not show the equipment slice or demand-centered KPI in production.
