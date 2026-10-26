# Independent autonomous-core review

Reviewer: Astra independent review agent. Date: 2026-10-26.

Scope: read-only architectural baseline, isolated-builder WIP review, and integrated code review beginning at `bc43995c3e99f7e6708edc5e743e2bbdc701143f` against `edd409b`. The integration branch continued receiving fixes during review. This document is a review ledger, not a deployment or production-readiness receipt.

## Findings requiring integrated follow-up

1. **P1 — accumulated history stops autonomous planning.** `autonomous_research.planning_cards` calls the API's `_commercial_triage_cards`, which reaches `_commercial_triage_page`. That function rejects the entire invocation when total research questions or commercial pursuits exceed 500, and also applies archived snapshot/note response budgets. At eight questions per day the question history alone can stop autonomous planning after roughly 63 days. Separate bounded current machine planning from historical HTTP response limits; retain all historical rows. Validate with more than 500 historical questions and pursuits, plus retained notes, while new eligible research still schedules.
2. **P1 — contact refresh boundary creates an avoidable stale interval.** Planning becomes due at 30 days, while a contact remains current through calendar day 30 (`age > 30` expires it). The worker's `already_named` shortcut can therefore skip fetching on day 30, save another successful completion, and delay the next job until day 60. The method expires on day 31. Validate the exact day-30/day-31 path and require a real due source refresh without deleting the old evidence.
3. **P2 — planner cleanup exceptions can escape the lane.** Connection acquisition is now protected, but rollback before the cleanup `try` can still raise, and `_planner_lane` has no outer exception boundary. Ensure cleanup failures cannot permanently stop a scheduler thread; test a later poll after a cleanup/disconnect failure.

The coordinator separately identified Research-view stale-result/back-navigation follow-ups and a historical fixture import. Those remain subject to the integrated regression gate.

## Earlier findings independently read back

- Research planning now requests the complete bounded category list before applying active-slot, freshness, backoff and retry exclusions; early unresolved categories no longer structurally truncate later categories.
- Contact enqueue deduplication distinguishes completed, unresolved and active jobs. The planner uses bounded company selection, bounded per-company job history and persisted deferred receipts instead of loading the entire historical job table.
- Ordinary terminal ingestion failures are no longer indefinitely blocked by the queue. Unrepresentable publisher Retry-After values have a separate hold state; representable deadlines remain scheduled.
- Planner connection acquisition is inside its failure/retry boundary, and PostgreSQL session advisory locking coordinates replicas.
- Search normalizes opportunity navigation IDs, omits raw stored project tiers, and reports unavailable saved company/opportunity projections separately from direct project/contact results. The UI rejects stale query results and reports pending projections.
- Manual write routes and mounted request schemas were removed. Historical fact, note, correction and membership evidence tables and read-side projections remain. There were no persistence-model or migration changes in the reviewed diff.
- Old operator statuses do not appear in the new classification, ranking or research-planning decisions. Legacy public browse/map/export status query filters remained during review; retiring that obsolete API behavior does not require deleting historical status rows.

## Evidence integrity and scope

The existing exact-source qualification gates, TX/OK/NM physical-site eligibility, 300 kW commercial floor, unknown-versus-zero distinction and residual-gap interval subtraction were preserved. Contact methods continue to depend on retained current citation support. Contact labels distinguish source attribution from deliverability and purchasing authority. Owner-first presentation does not merge separate physical projects or establish new power claims.

Historical fact/correction replay and immutable-row fixtures remain in the integration suite; replacing retired writer tests must not be mistaken for permission to discard those records. Four unreferenced manual request classes were reported for cleanup; historical output contracts remain useful.

## Independent verification and limits

The reviewer ran only the following focused, non-database tests; all **79 passed**:

```text
uv run pytest tests/unit/test_autonomous_api_surface.py \
  tests/unit/test_autonomous_questions.py \
  tests/unit/test_contact_planner_fairness.py \
  tests/unit/test_opportunity_intelligence_contract.py \
  tests/unit/test_acquisition_diagnostics.py \
  tests/unit/test_ranking.py -q
```

No reviewer database tests, destructive mutations, provider calls or deployment actions were performed. Full backend/browser/integration results belong to the coordinator's isolated final gate and must identify its exact commit. This review does not establish live contact yield, live TCEQ acquisition, paid-provider readiness, or production deployment. The reported Austin local acquisition and TCEQ transport limitation are separate acquisition evidence, not a full live-coverage proof.

## Acceptance state

**Changes requested pending the integrated follow-ups above and exact-candidate regression verification.** Update this ledger with concrete fix commits and readback evidence before treating these findings as closed.
