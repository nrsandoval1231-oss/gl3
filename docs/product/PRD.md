# GridLens — Product Requirements Document

## Current execution scope — Phase 2, November 8, 2026

The owner authorizes scheduled autonomous commercial research on the existing account-first foundation, through one tested, independently reviewed draft PR. Cards show source-backed Why now, useful scoped Power need, permitted Best contact and one justified Next action; evidence stays on demand. Shared canonical-company research must preserve distinct projects and needs. Existing owner-managed need-scoped Commercial Pursuits is the only manual execution workspace; research never creates its stages, tasks or activity. Existing Jev authority is unchanged. No merge, deployment, production writes, credential changes, paid-provider calls or source activation is authorized. [Current contracts and acceptance](../engineering/autonomous-commercial-research-20261108.md) distinguish disabled/mock validation from live operation; older release permissions below are historical.

## Account-first foundation — accepted Slice 1, November 7, 2026

One canonical customer/operator account. Distinct physical projects and power needs underneath. Curated commercial relevance upfront. Contacts and a justified action within easy reach. Evidence on demand; research/process machinery behind the scenes. This owner decision supersedes flat-project defaults, mandatory KPI tiles and historical evidence-heavy layouts. Preserve the existing logo, navy header, palette, typography and exact primary navigation: Opportunities | Companies | Pursuits | Reports. Keep All | Oil & Gas | Data Centers with their actual sector semantics.

Opportunities presents compact source-backed account cards. Companies uses the same canonical identities and detail across its broader directory. Account detail places contacts near the top, orders distinct projects by relevance and retains project/account context across mobile Back, browser history and reload. Sources is collapsed by default; material uncertainty remains visible at the claim. Search, combined project filters, sorting, counts and grouping apply server-side before account pagination; combined project predicates must match the same child. Account and child pages are independent. Routine document volume, a shared name or contractor role cannot establish identity or relevance. Provisional buckets stay provisional; separate subsidiaries/sites/packages remain distinct.

Need-scoped Pursuits retain IDs, stages, tasks and confirmed activity, presented under canonical accounts. Multiple eligible opportunities require a compact explicit picker. Call/Email opens only a permitted contact route and records no activity. Owner-approved manual Pursuits actions are a scoped exception to older read-only prescriptions. Unknown MW is neither zero nor an automatic exclusion; facility scale is not rental demand. Preserve privacy, suppression, provenance and contradictions in projections and explicitly scoped safe exports. No scores, repeated unavailable fields, permit dumps or processing diagnostics in ordinary account cards.

[Slice 1 implementation and exact acceptance](../engineering/account-first-slice-20261107.md) records the accepted repository baseline. The current Phase 2 scope is above. Historical presentation instructions below apply only where compatible with this foundation and Phase 2. Dated deployment receipts do not establish current runtime state.


**Version:** Demand-centered scope · 2026-10-30
**Status:** Active requirements subordinate to the sole [Autonomous Power Demand Intelligence Canon](AUTONOMOUS_INTELLIGENCE_CANON.md).
**Product owner:** Nick Sandoval

The prior gap-led PRD is retained as [dated pre-pivot history](../../.agent/archive/DEMAND-CENTERED-PIVOT-20261030/PRD-pre-pivot-20261029.md). It records historical qualification requirements and is not active product authority.

**Amendment 2026-11-06 (owner direction, branch only, not deployed):** an owner-managed Pursuits workspace (stages, follow-up tasks, user-confirmed activity logging, server-computed Needs Attention) is in scope, overriding prior no-manual-status/notes language for that workspace only. Ordinary Opportunities browsing remains autonomous/read-only and audited internal safeguards are unchanged. See [commercial pursuits](../engineering/commercial-pursuits-20261106.md).

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

The deployed bounded slice parses an O&G pump/compressor cohort and computes electrical demand with `Decimal`. It uses `equipment-demand-v1` on existing `EvidencePackage` records, normal and unchanged-record ingestion hooks, and the existing intelligence-card API contract for demand records. The deployed slice required no new migration. It preserves source efficiency/rating basis, count, operating/standby state, new/existing classification, and project/evidence binding. Engineer-owned deterministic tests cover arithmetic and negative cases. It is included in the accepted application release, but it is not the full six-layer pipeline; see the [November 2 receipt](../validation/production-release-20261102.md) for dated runtime evidence and limits.

## Primary measure and presentation

Primary KPI: **Identified Power Demand MW**. Report documented, calculated, and estimated MW separately, deduplicated by supported demand/equipment scope. Also report identified records whose MW is unknown. Inferred amounts do not enter documented/calculated/estimated totals.

Demand-centered UI changes are deployed within `ec6486a2`. At the November 2 verification, the demand summary had zero supported validated equipment records and remained explicitly unavailable rather than fabricated. The October 29 visual identity is retained with bounded November 2 loading/alignment/header refinements; equipment-only MW is not total portfolio demand. Preserve evidence access, responsive behavior, privacy, and authentication.

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

## Dated production boundary

Latest accepted application receipt is [November 2, 2026](../validation/production-release-20261102.md): `ec6486a2726758b2a9fb64a03e99276583a27a6e` (PR165), schema `0049_scoped_identity_browse`, 74 public tables. It records exact images, current-data recovery and authenticated responsive acceptance. It is dated evidence, not proof of subsequent runtime state or sustained source coverage. Earlier PR148/October 29 receipts remain historical.
