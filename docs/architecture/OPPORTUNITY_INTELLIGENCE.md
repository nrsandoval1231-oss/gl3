# Opportunity intelligence architecture

**Current as of 2026-10-21:** PR102 and approved PR103 are merged upstream. The follow-up integration preserves the approved workspace and places reported power scheduling in its existing Commercial Assessment tab. Focused browser validation passed 62/62; typecheck and build passed. Final exact-candidate controller gates, runtime proof, and independent review remain pending; this document is not release or production authority.

## Ownership and evidence

`Project` identifies physical work; `PowerNeed` scopes one power activity. Retained evidence, immutable observations, and accepted fact versions remain claim authority. Opportunity intelligence is a bounded read projection: it does not write facts, assign tiers, or promote qualification. Completeness is separate from qualification. Failed research is not evidence that information is unavailable.

Buying-chain claims and citations remain project-scoped. The `reconcile_claim_identity` helper and its tests enforce a narrow strong-ID rule: only checksum-valid 20-character LEI or exact nine-digit US EIN, typed and bound to the named entity in the same current cited evidence version, can qualify for automatic reconciliation; generic/unscoped identifiers fail closed. The helper is not called by ordinary enrichment, so no automatic cross-project production behavior is claimed. Ordinary enrichment remains project-scoped; cross-project links occur through attributed review using the existing correction API. Link changes supersede the prior link and preserve history. Names, employment, shared contact strings, or an identifier without entity binding do not merge parties. Identity does not establish project responsibility or purchasing authority.

Contact actions require a current project claim citing a current public source, exact retained passage, and literal method. Operator-reported values remain non-actionable. F3C composes sparse corrections, supersedes the old identity link when the subject changes absent a valid attributed rebind, removes old same-kind actions even when the replacement is not publicly actionable, and permits review against current evidence after stale history. Prior versions and sibling projects remain isolated. The correction UI parent-aggregate refresh fix is integrated; builder-reported targeted browser and type checks passed. Exact-candidate controller validation is pending.

## Read, research, and persistence

- Authenticated `GET /api/opportunities/needs/{id}` returns current `intelligence_card`; `GET /api/opportunity-intelligence?need_ids=...` is bounded to 1–20 eligible needs.
- Reads use current canonical projections and bounded batched evidence, identity, and research reads. Reads do not acquire sources, invoke providers, or enqueue jobs.
- Snapshot versions follow the intelligence input fingerprint: changed supplied projections persist once, identical repeats do not churn, and omitted optional projections do not erase unchanged saved data. Current detail rebuilds from current facts so snapshots cannot restore retracted values.
- Schedule-only operator refs do not change the research semantic hash; the legacy four-key semantic-ref shape is preserved. Evidence/contact changes retain their established invalidation behavior.

## Commercial schedule and workspace

The canonical qualified `power_gap` remains separate from the dated operator schedule. The schedule partitions demand phases by supply boundaries, calculates intervals only when coverage is confirmed complete, leaves unknown coverage unresolved, and labels proposed/hypothetical supply as scenarios. It does not change qualification. Facility load or unknown supply cannot substitute for scoped demand or zero supply.

Supply summaries retain explicit source kind, ready date/date basis, state, suitability, source reference, and reporter name/organization/role. Only explicit `utility_grid` entries are presented as reported energization; missing legacy source kind is `other`. Segment dates and labels do not imply utility availability. Grounded source-native project names and raw identifiers remain cited in the existing horizontal workspace. The schedule editor uses attributed draft, accept, correct, retract, history, and readback. Contact corrections use project scope, reason/provenance, version checks, and history.

`OPPORTUNITY_ENRICHMENT_ENABLED=false` is the code default for the **new automatic expanded planner only**; it does not disable the UI. Explicit research actions retain their existing auth, autonomous-research, provider, source-permission, and budget gates. Public buying-chain research and provider/model features default off; deployed values must be verified independently.

## Required schema, rollout, and rollback

The integrated application requires migration `0035_reconciled_identity` followed by `0036_buying_chain_corrections`. Before any separately authorized rollout, validate a restored isolated database, apply migrations through head (`uv run alembic upgrade head` from `backend`), verify the revision, then deploy the exact accepted API/web/worker candidate. Do not run integrated code against a schema earlier than `0036`.

Rollback may restore a compatible application while retaining additive tables and correction history. Do not downgrade/drop them or clear jobs, receipts, ledger reservations, or history as a rollback shortcut. Feature-flag or application rollback does not cancel already authorized work.

## Open release boundary

The retained sample has 14 cases/79 fields and reports 79/79 exact with zero expected-null overpromotion, but the offline ten-category gate remains blocked by absent site-specific utility constraint, conflicting-date, and bridge-power cases. F6C exceeded its collection ceiling and yielded no new candidate needs; it is not acceptance proof. Production/runtime/restart evidence, live provider acceptance/cost, controller final pipeline checks, and independent review remain pending. See the [current release record](../operations/opportunity-intelligence-release.md) and [curated acceptance packet](../../.agent/artifacts/PR102-FINISH/ACCEPTANCE.md).
