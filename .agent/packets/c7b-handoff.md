# C7b builder handoff (in progress pending concurrency repair)

Candidate base: `84336c8014bc58fd678e6bac7a7750a44d2a61e0` (HEAD; working tree dirty).
No commit, push, merge, deployment, live HTTP, provider call, or spend occurred.
Evaluation PostgreSQL only: `127.0.0.1:55487`, databases
`gl3_intelligence_evaluation_20261018_test` and
`gl3_intelligence_evaluation_20261018_app`, user `gl3_intelligence`.

## Implemented C7b surface

Structured Socrata and Boston CKAN acquisition now uses durable date/keyset
segments through the real `process_job` path. Each acquisition handles at most
one date segment and one page (1,000 rows); date windows are capped at seven days.
Overfull days resume by stable source row identity, with count/order/recheck
validation. Changed counts reset the segment cursor and return partial; malformed
or over-bound responses fail closed. Evidence is committed before progress cursor
advancement, and policy/source/fence context is rechecked before the progress
write. Follow-on jobs use transactional enqueue after terminal status. Partial
health preserves last-good success/facts and emits a partial receipt.

Lane contract: `issue_recent` and `issue_history` for structured permit sources;
`modified_recent` and durable `modified_history` only when the registry maps a
modified timestamp (Austin and Chicago); no invented Seattle modified lane; Boston
is issue-date only. Austin's finite configured `issue_backfill` is separate. Each
lane catches up in bounded seven-day windows; recent lanes recheck a rolling seven
days; history resumes from its own `completed_through` after outages. Austin,
Seattle, and Boston date-only/naive source timestamps remain date-only, with no
timezone inference. Chicago's system modification field retains its UTC `Z` value.

Frozen `SourceCollectionProgress` contract (migration 0029, owned/frozen in C7a):
UUID primary key; source FK; lane (`String(80)`); 64-character policy digest; unique
`(source_id, lane, policy_digest)`; nullable timezone-aware window start/end and
completed-through; bounded JSONB cursor; status in `incomplete|complete|partial|error`;
error class; last attempt/completion and update timestamps. DB constraint permits at
most 8,192 characters in `CAST(cursor AS TEXT)` for SQLite/PostgreSQL compatibility.
Service writes separately enforce an 8,192-byte UTF-8 serialized cursor bound.
Cursor policy digest binds source ID/endpoint/method/query, lane policy, parser,
evaluator, and admission policy versions. No model or migration edits were made in
C7b.

## Validation observed

At 2026-10-18 21:41 UTC, the following completed with exit 0 after both
concurrency repairs:

```text
cd backend
.venv\Scripts\python.exe -m pytest tests\integration\test_structured_collection_recovery.py tests\integration\test_source_scheduling.py tests\integration\test_ingestion.py tests\integration\test_collection_only_ingestion.py tests\unit\test_structured_permit_segments.py -q
```

Captured pytest output:

```text
....................................................................................................................... [100%]
============================== warnings summary ===============================
.venv\Lib\site-packages\fastapi\testclient.py:1
  C:\Users\nrsan\Nucleus\02_Projects\GridLens\gl3-intelligence-20261018\backend\.venv\Lib\site-packages\fastapi\testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
119 passed, 1 warning in 52.71s
```

The five modules above cover the C7a scheduling proof as a dependency and the
existing ingestion/admission behavior, plus recovery and adapter segments. The
segment unit module now includes over-cap keyset continuation, changed count,
empty date, unsupported lane, malformed page, and old issue date with a recent
Chicago modification timestamp. The recovery integration includes a modified
history outage beyond overlap with an older issue-date record, persistence across
restart, bounded continuation, disabled source, stale fence, and partial health.

```text
cd backend
.venv\Scripts\mypy.exe src\gridlens
```

Exit 0: `Success: no issues found in 123 source files`.

```text
cd backend
.venv\Scripts\ruff.exe check src\gridlens\ingestion\structured_collection.py src\gridlens\ingestion\adapters\__init__.py src\gridlens\ingestion\adapters\socrata_permits.py src\gridlens\ingestion\adapters\boston_permits.py src\gridlens\ingestion\service.py src\gridlens\jobs\worker.py tests\unit\test_structured_permit_segments.py tests\integration\test_structured_collection_recovery.py tests\integration\test_ingestion.py tests\integration\test_collection_only_ingestion.py
```

Exit 0: `All checks passed!`.

The independent adversarial integration module
`tests/integration/test_structured_collection_adversarial.py` passed 9/9 after
the full-snapshot repair (reported 4.22s by its owner). Its same-cursor/different-
window case blocks an older acquisition while a newer recent window is installed;
the old worker is rejected as `CollectionCheckpointChanged`, the new window stays
incomplete, and a continuation advances it.

Controller combined rerun of these five modules plus the adversarial module passed
128 tests in 56.91s on the full-snapshot candidate (reported by root at
2026-10-18 21:43 UTC). The controller owns the exact combined command/log and will
bind it to the frozen candidate in its final evidence.

Earlier negative receipt (retained; not suppressed): the initial combined selected
run reported `98 passed, 19 failed, 1 warning in 81.84s`. The 19 failures were:

```text
test_ingestion.py::test_permit_assessment_replay_correction_and_deactivation
test_ingestion.py::test_permit_v5_rejected_to_v6_clause_recovery_and_replay
test_ingestion.py::test_event_signal_closes_after_explicit_end_date_on_same_hash_replay
test_ingestion.py::test_authoritative_permit_identity_requires_one_exact_site_candidate[case0]
test_ingestion.py::test_authoritative_permit_identity_requires_one_exact_site_candidate[case1]
test_ingestion.py::test_authoritative_permit_identity_requires_one_exact_site_candidate[case2]
test_ingestion.py::test_structured_ingestion_locks_candidates_in_news_compatible_uuid_order
test_ingestion.py::test_structured_ingestion_does_not_wait_on_unrelated_project_lock
test_ingestion.py::test_source_ingestion_queues_jev_without_calling_provider[case0]
test_ingestion.py::test_source_ingestion_queues_jev_without_calling_provider[case1]
test_ingestion.py::test_source_ingestion_queues_jev_without_calling_provider[case2]
test_collection_only_ingestion.py::test_current_rss_supplement_matches_permit_by_explicit_project_and_site[case0]
test_collection_only_ingestion.py::test_current_rss_supplement_matches_permit_by_explicit_project_and_site[case1]
test_collection_only_ingestion.py::test_current_rss_supplement_matches_permit_by_explicit_project_and_site[case2]
test_collection_only_ingestion.py::test_current_rss_supplement_matches_permit_by_explicit_project_and_site[case3]
test_collection_only_ingestion.py::test_current_rss_supplement_matches_permit_by_explicit_project_and_site[case4]
test_collection_only_ingestion.py::test_current_rss_supplement_matches_permit_by_explicit_project_and_site[case5]
test_collection_only_ingestion.py::test_phase_numbered_same_building_permits_consolidate_but_distinct_buildings_do_not
test_collection_only_ingestion.py::test_multiple_labeled_rss_sites_keep_record_separate_with_persisted_ambiguity
```

Classification: the three event/query expectations reflected the old aggregate
status-date request and needed an explicit synthetic bounded-segment response; the
legacy semantic tests monkeypatched `retrieve_source`, which the new structured
branch no longer calls. Their narrow synthetic fixtures now wrap those retained
records as one explicitly complete segment and still exercise the real service
proof/persistence branch. Separately, the three JEV tests exposed a real checkpoint
regression: `process_records(commit=False)` had stopped storing the last processed
record ID. The service now stores that ID while preserving continuation metadata.
After these repairs, the two legacy modules passed 62 tests; the consolidated 119
run above passed.

## Concurrency repairs and remaining gates

The first independent race found that worker A blocking in fetch while B advanced
the cursor left A's `SELECT ... FOR UPDATE` with a stale SQLAlchemy identity-mapped
row; its cursor check accepted A's stale result. Both locked reads now use
`populate_existing=True`. A second adversarial case showed cursor equality alone
was insufficient when `{}` recurred after completing an old window and rolling
the recent lane to a different seven-day window. The service now captures a
separate immutable prefetch snapshot and compares source, lane, policy digest,
window bounds, completed-through, status/error, attempt/update timestamps, and a
canonical serialized cursor on both reads. The 9-case adversarial module passes
with both races covered. Root is rerunning the combined 128 focused checks on the
operations test DB; the combined run is now complete (128 passed, 56.91s). The
earlier isolated adversarial receipt was 7/8 with the stale-cursor assertion
failing; after the first repair it was 8/8, then the added same-empty-cursor,
different-window case exposed the second race. The full-snapshot repair passed all
9 adversarial cases. Root's migration/runtime gates and independent Sol review
remain open; this builder handoff is not a parent-task completion claim.

Owned files in this handoff: `backend/src/gridlens/ingestion/structured_collection.py`,
`backend/src/gridlens/ingestion/adapters/__init__.py`,
`backend/src/gridlens/ingestion/adapters/socrata_permits.py`,
`backend/src/gridlens/ingestion/adapters/boston_permits.py`,
`backend/src/gridlens/ingestion/service.py`, `backend/src/gridlens/jobs/worker.py`,
`backend/tests/integration/test_structured_collection_recovery.py`,
`backend/tests/integration/test_ingestion.py`,
`backend/tests/integration/test_collection_only_ingestion.py`,
`backend/tests/unit/test_structured_permit_segments.py`,
`docs/operations/source-scheduling-proof.md`, and
`docs/operations/intelligence-activation.md`. The adversarial PG test is owned by
`runtime_regression_builder`. Parent-owned graph, delivery, and evaluation files
were preserved.
