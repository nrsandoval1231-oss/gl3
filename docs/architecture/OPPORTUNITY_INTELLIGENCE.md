# Opportunity intelligence architecture

**Current as of 2026-10-21:** the integrated implementation is present on candidate `69c19f85bd67e35028e0c9def43d4e689e068406`. This documents behavior and release constraints; it does not authorize production activation or release. F3 correction repair and controller validation remain pending.

## Ownership and evidence

`Project` identifies physical work; `PowerNeed` scopes a particular power activity. Retained evidence, immutable observations, and accepted fact versions are the authority for claims. The opportunity-intelligence aggregate is a bounded read projection: it does not write facts, assign tiers, or promote qualification. Completeness is separate from qualification. Failed research is not evidence that information is publicly unavailable.

Buying-chain claims and their citations remain project-scoped. Current claims may receive project-scoped company/person IDs. Cross-project automatic identity reconciliation is restricted to a checksum-valid 20-character LEI or exact nine-digit US EIN that is typed, bound to the named entity, and quoted in the same current cited evidence version. Generic or unscoped identifiers fail closed. Direct identity links require an attributed reviewer, a reason, and current claim evidence; corrections supersede links while preserving history. Names, employment, shared contact strings, or an ID submitted without its cited entity binding do not merge identities. Identity links do not establish project responsibility or purchasing authority.

Contact methods are actionable only when the current project claim cites a current public source, exact retained passage, and literal method. Operator-reported values are visibly reports and have no call/email action. The correction workflow retains reason and provenance, reads current/history state, and returns stale-version feedback; independent F3 review has opened a repair for cumulative sparse corrections, subject changes, and stale or uncited methods. That repair and its validation are pending.

## Read and persistence behavior

- Authenticated `GET /api/opportunities/needs/{id}` includes the current `intelligence_card`; `GET /api/opportunity-intelligence?need_ids=...` returns a bounded aggregate for 1–20 eligible needs.
- These reads use the canonical current projection and bounded batched evidence/identity/research reads. They do not acquire sources, invoke providers, or enqueue work.
- Intelligence snapshots are versioned by their input fingerprint: a changed supplied projection persists once, identical repeats do not churn, and omission of an optional projection does not erase an unchanged saved value. Current detail is rebuilt from current facts so snapshots do not restore retracted claims.
- Schedule-only operator references are excluded from the research semantic hash before the legacy four-key reference shape is formed. Schedule changes therefore do not restart unchanged research; evidence/contact changes retain their established invalidation behavior.

## Commercial and schedule semantics

The existing qualified `power_gap` remains the only value eligible for the canonical Lead gap. It retains its source/fact references, qualification version, timing and duration. A dated operator schedule is a separate bounded scenario: it partitions demand phases by supply dates, computes intervals only when coverage is confirmed complete, leaves unknown coverage unresolved, and labels proposed/hypothetical supply as scenarios. It never changes tier or qualified-gap arithmetic. Facility load, nameplate capacity, or an unknown supply value cannot be substituted for scoped demand or zero supply.

Supply summaries retain explicit source kind, service-ready date, date basis, state, suitability, source reference, and reporter name/organization/role. Only an explicit `utility_grid` entry is displayed as reported grid energization; missing legacy kind is `other`. Segment dates and labels do not imply utility service. Source-native names and identifiers remain cited; the raw source title/permit identifier stays available as provenance.

## Workspace and research controls

The existing horizontal Pursuit Workspace displays supported identity/power facts, contacts, grouped gaps, evidence, and next actions. Its row-based schedule editor uses the attributed fact draft, accept/correct/retract, history, and readback flow. Desktop/mobile layout and Back selection remain the approved workspace behavior.

`OPPORTUNITY_ENRICHMENT_ENABLED=false` is the code default for the **new automatic expanded planner only**; it does not hide or disable the intelligence UI. The explicit research action remains governed by its existing authentication, `AUTONOMOUS_RESEARCH_ENABLED`, provider, source-permission, and budget gates. `BUYING_CHAIN_PUBLIC_RESEARCH_ENABLED` and provider/model features default off; verify actual deployed settings independently. Reads remain provider-free. No new provider, runtime service, or spend authority was added.

## Required schema and rollout order

The F5 projection itself adds no migration, but the integrated application requires the prior schema work: migration `0035_reconciled_identity` creates evidence-bound identity/link tables, and `0036_buying_chain_corrections` adds append-only project-scoped contact correction history. They are sequential (`0035` then `0036`) and must be present before deploying the integrated application. For any separately authorized release, restore and validate an isolated database, apply forward migrations (`uv run alembic upgrade head` from `backend`), verify the resulting revision, then deploy the exact accepted API/web/worker candidate. Do not deploy new code against a pre-0036 schema.

Rollback may restore a compatible prior application image while retaining these additive tables and correction history. Do not downgrade/drop them or delete jobs, receipts, ledger reservations, or history as a rollback shortcut. Keep automatic expanded planning off until separately authorized gates pass; application rollback and feature-flag changes do not cancel already authorized work.

## Remaining boundary

The current implementation does not establish full field coverage for utility constraints, conflicting dates, or bridge-power potential, nor does it prove production persistence latency/restart, live provider acceptance, or inference cost. See the [current release and retained-data record](../operations/opportunity-intelligence-release.md). Historical intake and earlier claims are preserved at [Git candidate `5ef5f3f`](https://github.com/nrsandoval1231-oss/gl3/commit/5ef5f3f29e94fffb071351b61e186d236d40068c); that historical state is not current release evidence.
