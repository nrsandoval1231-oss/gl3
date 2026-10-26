# Independent autonomous-core review

Reviewer: Astra independent review agent. Date: 2026-10-26.

Scope: read-only architectural baseline, isolated-builder WIP review, and integrated code review beginning at `bc43995c3e99f7e6708edc5e743e2bbdc701143f` against `edd409b`. The integration branch continued receiving fixes during review. This document is a review ledger, not a deployment or production-readiness receipt.

## Findings and integrated follow-up

1. **P1 — accumulated history stops autonomous planning.** `autonomous_research.planning_cards` calls the API's `_commercial_triage_cards`, which reaches `_commercial_triage_page`. That function rejects the entire invocation when total research questions or commercial pursuits exceed 500, and also applies archived snapshot/note response budgets. At eight questions per day the question history alone can stop autonomous planning after roughly 63 days. Separate bounded current machine planning from historical HTTP response limits; retain all historical rows. Validate with more than 500 historical questions and pursuits, plus retained notes, while new eligible research still schedules.
2. **P1 — contact refresh boundary creates an avoidable stale interval.** Planning becomes due at 30 days, while a contact remains current through calendar day 30 (`age > 30` expires it). The worker's `already_named` shortcut can therefore skip fetching on day 30, save another successful completion, and delay the next job until day 60. The method expires on day 31. Validate the exact day-30/day-31 path and require a real due source refresh without deleting the old evidence.
3. **P2 — planner cleanup exceptions can escape the lane.** Connection acquisition is now protected, but rollback before the cleanup `try` can still raise, and `_planner_lane` has no outer exception boundary. Ensure cleanup failures cannot permanently stop a scheduler thread; test a later poll after a cleanup/disconnect failure.

The coordinator separately identified Research-view stale-result/back-navigation follow-ups and a historical fixture import. Those remain subject to the integrated regression gate.

### Follow-up readback through `ce2b062`

- **Finding 1 corrected in code:** `ce2b062` separates current machine cards from historical HTTP preflight. Both initial planning and grouped reevaluation use the current projection. Oversized current groups are excluded as whole groups with warning diagnostics, allowing other groups to proceed. Added tests cover 501 archived questions/pursuits/notes, oversized snapshots, and an oversized source-row group beside a valid group. The reviewer inspected these tests but did not run their database fixtures.
- **Finding 2 corrected in code:** `4a82a6a` records an explicit `refresh_due` flag and makes a due worker fetch cited URLs even when a named contact remains current on day 30. Failure to obtain a refresh source produces an unresolved receipt instead of a new successful freshness claim. The added boundary test covers real fetching on day 30 and retained usability on day 31.
- **Finding 3 corrected in code:** `83ab3de` contains rollback, unlock, invalidation and close failures, and adds a final exception boundary to the scheduler lane. Tests cover cleanup faults and continued polling.
- `a07ae91` removes legacy public operator-status query filters; historical status data remains. `5ca68b9` removes the four unused manual request classes. `1e3d1e8`, `251aa4c` and `288f6bb` address Research stale results/navigation and browser/mobile follow-ups. Their integrated code was read back.

**Residual bounded-data limitation reported to the coordinator:** the current summary projection still calls `_preflight_streamed_evidence_text` over all eligible active needs before per-group isolation. A retained field exceeding 1 MB, or aggregate retained text exceeding 512 MB, can therefore stop the whole planner. The new group-row isolation tests do not cover this earlier byte preflight. Preserve the safety bounds, and either isolate affected work groups on the machine path or explicitly record this remaining capacity/fault-isolation limitation; do not describe the current code as handling every oversized group independently.

### Assembled-source readback at `8df3231`

The text-preflight limitation above is **corrected in code** by `93a8354`, integrated as `8df3231`. Independent review confirmed machine summary batches of at most 50 needs, recursive splitting before oversized current evidence hydration, complete work-group exclusion, and a full retained-text preflight before each selected group's detail projection. HTTP bounds remain unchanged. Added regression cases cover oversized current and historical fields, affected-group siblings, unrelated valid projects, and an aggregate-limit simulation. The reviewer inspected the regression code and ran `git diff --check`; database execution remains coordinator evidence.

Upstream `d75a856` was merged during this task. Its additive migrations 0042–0044 are unchanged from upstream; the earlier no-migration-change statement describes the pre-upstream surgery diff only. The reviewer did not apply migrations. Workbook writes are restricted to loopback staging/test databases and separate external-import tables. Original rows/events remain retained, rollback changes activation only, and imported contacts are separately labeled unverified without outreach links. The authenticated power-enrichment projection reads exact-scope accepted historical schedules, preserves unknown supply, and does not assign qualification. Company graph relationships remain explicitly unverified assertions; project links retain regional and source-version checks. Manual contact/graph writers are removed, and the mounted public mutation allowlist contains only login/logout.

Research-priority explanations now distinguish unknown demand from zero, name the project/need coverage heuristic accurately, and handle invalid quarter dates and non-finite parsed demand conservatively. This score is not evidence confidence, current power qualification, or verified commercial value.

**New P1 finding — failed due-refresh retry loses its refresh intent (open at `8df3231`).** After a real day-30 refresh is queued with `refresh_due=true`, a terminal worker failure becomes the latest job. The planner retains `refresh_generation`, but enqueue recomputes `refresh_due=false` because the latest job is no longer a completed success. That changes the request fingerprint and allows the retry worker to reuse a still-current named contact without fetching. The resulting successful receipt can recreate the day-31-to-day-60 contact outage. Preserve refresh intent and fingerprint across failed retries in the same generation. Existing retry-fingerprint tests start with a fresh company and do not exercise the true-to-false transition; the regression must seed an old success and current named contact, fail the real due job, and verify the retry fetch plus day-31 usability. The coordinator assigned an isolated follow-up; source acceptance remains pending.

### Final contact-retry readback at `24f3985`

The failed-refresh finding is **corrected in code** by `3960f33`, included in source candidate `24f3985d8b6f3c71d4fb415d4abcea8836d04694`. An explicit refresh generation now preserves `refresh_due=true` regardless of the latest attempt's failure state. The reviewer inspected the new exact-boundary regression: prior successful contact, day-30 refresh failure before a receipt, one-hour planner retry with identical request digest and refresh generation, actual mocked source retrieval, and current contact projection on day 31. The coordinator reports four focused tests passed; the reviewer did not rerun their database fixtures. No new defect was identified in this small fix.

## Earlier findings independently read back

- Research planning now requests the complete bounded category list before applying active-slot, freshness, backoff and retry exclusions; early unresolved categories no longer structurally truncate later categories.
- Contact enqueue deduplication distinguishes completed, unresolved and active jobs. The planner uses bounded company selection, bounded per-company job history and persisted deferred receipts instead of loading the entire historical job table.
- Ordinary terminal ingestion failures are no longer indefinitely blocked by the queue. Unrepresentable publisher Retry-After values have a separate hold state; representable deadlines remain scheduled.
- Planner connection acquisition is inside its failure/retry boundary, and PostgreSQL session advisory locking coordinates replicas.
- Search normalizes opportunity navigation IDs, omits raw stored project tiers, and reports unavailable saved company/opportunity projections separately from direct project/contact results. The UI rejects stale query results and reports pending projections.
- Manual write routes and mounted request schemas were removed. Historical fact, note, correction and membership evidence tables and read-side projections remain. The original surgery diff had no persistence-model or migration changes; the later upstream additive migrations are accounted for above.
- Old operator statuses do not appear in the new classification, ranking or research-planning decisions. Legacy public browse/map/export status query filters found during review were subsequently removed by `a07ae91`, without deleting historical status rows.

## Evidence integrity and scope

The existing exact-source qualification gates, TX/OK/NM physical-site eligibility, 300 kW commercial floor, unknown-versus-zero distinction and residual-gap interval subtraction were preserved. Contact methods continue to depend on retained current citation support. Contact labels distinguish source attribution from deliverability and purchasing authority. Owner-first presentation does not merge separate physical projects or establish new power claims.

Historical fact/correction replay and immutable-row fixtures remain in the integration suite; replacing retired writer tests must not be mistaken for permission to discard those records. Four unreferenced manual request classes reported for cleanup were removed by `5ca68b9`; historical output contracts remain useful.

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

On assembled source `8df3231`, the reviewer also ran **48 passing non-database tests** covering enrichment-route authentication, research ranking, power-enrichment arithmetic/scope, workbook parsing, and the public mutation allowlist:

```text
uv run pytest tests/unit/test_enrichment_api.py \
  tests/unit/test_enrichment_planner.py tests/unit/test_power_enrichment.py \
  tests/unit/test_workbook_import.py tests/unit/test_autonomous_api_surface.py -q
```

## Acceptance state

**Local implementation and regression acceptance is granted for source `24f3985d8b6f3c71d4fb415d4abcea8836d04694`.** All identified blocking findings have corrective code independently read back. The reviewer fetched [GitHub Actions run 40255316876](https://github.com/nrsandoval1231-oss/gl3/actions/runs/40255316876), verified its exact source SHA and successful backend, web and brand-assets jobs, and read the backend job's raw test summaries: **3,048 passed, 1 skipped** from 3,049 collected tests; **120 browser tests passed**. A source diff against that SHA is empty for `backend`, `web`, `scripts`, `config`, `tools` and `.github`; subsequent review-document changes do not alter that tested source.

The reviewer also inspected the local final-gate manifest and four pytest logs in `/tmp/gridlens-final-gate`: the same candidate, all four exit codes zero, and 763 + 761 + 762 + 762 = **3,048 passed**, with one optional local-access-probe skip and seven passing subtests. The interrupted `8df3231` run is not used as acceptance evidence. The coordinator additionally reports fresh/repeated/drift schema checks, seeded 0041→0044 evidence preservation, and all three dependency audits passing; those are coordinator evidence, not reviewer-executed checks.

**Production deployment remains on hold.** Four browser cases requiring a live corpus remain blocked. The passing local and CI regressions do not establish live TCEQ acquisition through the required proxy, paid-provider readiness, current territory coverage, sustained daily autonomous cycles, a real qualified Lead, verified actionable-contact yield, or deployed behavior. This acceptance covers the reviewed implementation and exact-source regression results only.
