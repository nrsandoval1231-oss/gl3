# Opportunity intelligence implementation plan

**Goal:** Present current, evidence-backed commercial intelligence together and progressively research material gaps without changing qualification or paid activation.

**Architecture:** Extend the existing Project → PowerNeed and BuyingChainClaim/Evidence graph, exact canonical projection, Pursuit snapshots, PostgreSQL research jobs and logical-call ledger. Add a typed read-only aggregate; retain existing correction and review workflows. No new agent runtime or provider activation.

**Authority:** Owner's October 21 implementation directive, PRD, UI_CANON and PURSUIT_WORKSPACE. Implementation is authorized; merge, deployment, paid activation and production writes are not.

## Audit (main 1c6c1cd)

Already implemented: immutable evidence, conservative matching, separate power needs, scoped buying-chain relationships, bounded retained-first research, task-specific Jev/OpenAI contracts, reservations and quarantine, deterministic qualification, saved browse and evaluation history. Jev/OpenAI activation is independently gated. Current runtime cannot be inferred from repository defaults.

Missing: typed aggregate/completeness, unified primary presentation, global normalized company/contact identities, phased supply schedules, broad field research. Exact research requests incorrectly depend on the first 50 cards. UI gap parsing drops the operator-confirmed shape. Commercial evaluation redundantly loads chains even though canonical projection already bulk-loads them.

## Sequence and checks

- [x] Typed card and field provenance in `domain/opportunity_intelligence.py`; normalize qualified gap variants, preserve missing supply, suppress unsupported contact actions. Unit regressions for contacts, stale claims, facility load, conflict and both gap formats.
- [x] Bounded aggregate in `intelligence/opportunity_intelligence.py`, authenticated API contract and batch reads; reuse projected chains and bulk question retrieval. Preserve snapshot versions and transactional refresh. Integration tests for authentication, input drift and independent qualification/completeness.
- [x] Extend existing question planning and exact-target refresh with unchanged provider policy/caps; tests for off-shortlist and incomplete actionable records.
- [x] Unified component in the existing contextual panel, grouped gaps and verified actions; preserve corrections, evidence, Back and keyboard controls. Generate API types; desktop/mobile regression.
- [ ] Run local PostgreSQL regression and migration checks, inspect actual retained corpus availability, measure query latency, independent review and fixes; publish focused unmerged PR with precise acceptance limits.

## Review focus

A failed or disabled research route is not proof information is not public. Employment is not project responsibility or purchasing authority. Facility MW is not temporary demand. Unknown supply is not zero. Similar names cannot merge customers or projects. Existing qualified operator gaps must remain visible with their fact provenance. Current source changes must suppress stale contact actions. Read endpoints cannot dispatch research.

## Validation availability

The attached local `gridlens` database was initially at 0007 with zero projects, needs, observations and evidence. The empty local database was migrated to 0034 for integration checks. It is not the production retained corpus. PostgreSQL 17 is available locally; repository CI uses its configured version. Live retained-record accuracy/cost and production latency gates remain open until measured on an authorized corpus/runtime.
