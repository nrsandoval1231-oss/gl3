# Demand-Centered Results Canon

**Status:** Active target presentation semantics · 2026-10-30
**Authority:** Subordinate to the [Autonomous Power Demand Intelligence Canon](AUTONOMOUS_INTELLIGENCE_CANON.md). Current released UI and API behavior are dated in [release receipts](../validation/).

The prior operator/customer presentation specification is preserved as [dated pre-pivot history](../../.agent/archive/DEMAND-CENTERED-PIVOT-20261030/PROJECT_FIRST_RESULTS-pre-pivot-20261029.md). The accepted November 2 release is recorded in the [production receipt](../validation/production-release-20261102.md). It serves company/operator groups with nested projects and server-side search, filters, sorting and pagination. The deployed demand summary is scoped to additional equipment; at release verification it had zero validated records, so Identified Power Demand (MW) was honestly unavailable. It is not a whole-facility or portfolio total.

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

## Released presentation and current compatibility

The released workspace presents company/operator groups with nested project detail, All / Oil & Gas / Data Centers filters, search, region/stage/priority filters, company/priority/recently updated sorting, and generation-bound paging. These are verified production behavior, not the complete target result. Existing Signal/Prospect/Lead qualification remains legacy runtime compatibility; those labels and any historical thresholds do not define a target demand record. Show organization/project/equipment identity, location, dates, contacts, and commercial relevance only when supported. Contact method does not establish buyer authority. Do not rank demand primarily by residual supply gap or qualify it by shortage evidence.

Keep privacy, source provenance, safe pagination, and responsive access. The deployed `equipment-demand-v1` summary may only describe additional equipment records; unknown or unsupported amounts are not zero, and this summary is not total portfolio demand. Do not present unavailable data as a measured KPI.

## Implementation boundary and release evidence

The bounded O&G equipment slice uses existing `EvidencePackage` and intelligence-card API contracts. It is included in accepted production main `ec6486a2726758b2a9fb64a03e99276583a27a6e`, deployed November 2, 2026, on schema `0049_scoped_identity_browse` with 74 public tables. See the [production release receipt](../validation/production-release-20261102.md) for the exact API/web image identities, recovery evidence, authenticated checks and limitations. The receipt reports zero validated equipment-demand records, an unavailable equipment-only summary, closed provider gates, and no broad scheduled-source or commercial-completeness claim. The October 29 PR148 receipt is retained as historical evidence.
