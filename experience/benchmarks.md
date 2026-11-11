# Benchmarks

Measured in the cloud dev container, 2026-11-06 (local disposable Postgres 16). Latest figures by the tester at end of feat/commercial-workspace-ux (earlier: web ~195 tests 1.6–2.5 min, unit 3,310, integration 1,496).

| Check | Command | Result |
|---|---|---|
| Web regression | `npx playwright test --project=regression --trace off --workers=4` | 247 tests, ~1.4 min |
| Backend unit | `pytest tests/unit -n 4` | 3,322 passed, ~29 s |
| Backend integration | `pytest tests/integration -n 4` | 1,501 passed, ~5 min 27 s |

## Ingestion write-path baseline (performance Phase 2, Step 0), 2026-11-11

Harness: `scripts/ingestion_write_benchmark.py` (corpus recipe in its docstring). Environment: 4 vCPU cloud
container, local disposable Postgres 16 (default fsync, `track_functions = all`), real `process_job` on the Texas
RRC drilling-permit source with fixture payloads only (no network). Database dropped, migrated to head and reseeded
on every run, so the real browse-invalidation triggers are installed. R = 300 records per phase; each phase is one
`process_job` call. Phase c amends 5% (15 records, sequence 2 to 1; RRC treats the lowest sequence as the latest).

Commands (from `backend/`, after `source /var/tmp/builder_env.sh s0`):

```
python ../scripts/ingestion_write_benchmark.py --database-url "$TEST_DATABASE_URL" --projects 5000 --records 300 --json-out ../experience/benchmarks/ingestion-writes-baseline-5k.json
python ../scripts/ingestion_write_benchmark.py --database-url "$TEST_DATABASE_URL" --projects 50000 --records 300 --json-out ../experience/benchmarks/ingestion-writes-baseline-50k.json
```

Per-function trigger detail is in the JSON files. Trigger ms is `pg_stat_user_functions.total_time`, inclusive of
nested calls (so an upper bound).

5,000 seeded projects (5,300 after phase a; run took 2 m 24 s):

| phase | wall s | rec/s | commits/rec | stmts/rec | lock stmts/rec | trigger calls/rec | trigger ms | trigger % wall | project scans | scan s |
|---|---|---|---|---|---|---|---|---|---|---|
| a all new | 124.1 | 2.42 | 0.02 | 86.2 | 12.03 | 69.1 | 7964 | 6.4% | 1500 | 4.0 |
| b all unchanged | 1.5 | 196.84 | 0.02 | 13.1 | 5.03 | 0.0 | 0 | 0.0% | 300 | 0.0 |
| c 5% changed | 2.8 | 108.43 | 0.02 | 16.2 | 5.43 | 1.9 | 209 | 7.5% | 345 | 0.1 |

50,000 seeded projects (50,300 after phase a; run took 17 m 48 s, under the 25 minute per-phase cap, so R stayed 300):

| phase | wall s | rec/s | commits/rec | stmts/rec | lock stmts/rec | trigger calls/rec | trigger ms | trigger % wall | project scans | scan s |
|---|---|---|---|---|---|---|---|---|---|---|
| a all new | 1044.0 | 0.29 | 0.02 | 86.2 | 12.03 | 69.1 | 112999 | 10.8% | 1500 | 29.2 |
| b all unchanged | 1.7 | 174.92 | 0.02 | 13.1 | 5.03 | 0.0 | 0 | 0.0% | 300 | 0.0 |
| c 5% changed | 7.4 | 40.50 | 0.02 | 16.2 | 5.43 | 1.9 | 4993 | 67.4% | 345 | 0.0 |

Findings:
- All-new ingestion is the cost: 10x the corpus is about 8.4x slower per run (124 s to 1,044 s) at identical statement
  counts, so the cost is client/DB work that scales with corpus size, not statement volume.
- `dirty_browse_project` is called 21 times per new record (6,300 calls) and dominates trigger time (6.2 s at 5k,
  110 s at 50k, about 98% of trigger time), growing with corpus size. Per-record total commit count is already low
  (about 6 commits per 300-record run) because the service batches commits in these paths.
- Unchanged replay is cheap and touches no browse trigger; amendments (c) cost 14 dirty calls per changed record.

Limitations (nothing below is invented; these are what the numbers do not show):
- Rows locked cannot be measured from the client. Reported proxies: explicit `FOR UPDATE`/`FOR SHARE` statements
  issued by the client (lock stmts/rec) and per-record calls of browse-invalidation trigger functions (locks taken
  inside triggers are invisible to the client).
- `scan s` is the time inside cursor execution of client statements containing `FROM projects` (joins included).
  It excludes row fetch and ORM hydration, which is why 50k user CPU (about 14.7 min) far exceeds scan time; the
  remaining gap is not attributed here.
- Function stats are read after a 2 s wait and `pg_stat_clear_snapshot()`; very late flushes could be missed.
- Single run per size, no repetition or variance; the container was shared with no other deliberate load.
- Seeded rows bypass the ORM region classifier (server defaults HOLD), so seeded projects are not region-classified.

### After Step 2a (index-driven, statement-level `dirty_browse_project`, schema 0056)

Same harness, environment and commands as the baseline above (single run per size, no variance measured; the
50k corpus took 17 m 31 s end to end). Baseline numbers are in parentheses.

5,000 seeded projects:

| phase | wall s | rec/s | trigger calls/rec | trigger ms | trigger % wall |
|---|---|---|---|---|---|
| a all new | 115.8 (124.1) | 2.59 (2.42) | 69.1 (69.1) | 3626 (7964) | 3.1% (6.4%) |
| b all unchanged | 1.4 (1.5) | 209.82 (196.84) | 0.0 | 0 | 0.0% |
| c 5% changed | 2.2 (2.8) | 133.80 (108.43) | 1.9 (1.9) | 53 (209) | 2.4% (7.5%) |

50,000 seeded projects:

| phase | wall s | rec/s | trigger calls/rec | trigger ms | trigger % wall |
|---|---|---|---|---|---|
| a all new | 935.9 (1044.0) | 0.32 (0.29) | 69.1 (69.1) | 6014 (112999) | 0.6% (10.8%) |
| b all unchanged | 1.5 (1.7) | 197.09 (174.92) | 0.0 | 0 | 0.0% |
| c 5% changed | 2.1 (7.4) | 144.16 (40.50) | 1.9 (1.9) | 49 (4993) | 2.4% (67.4%) |

Findings:
- Trigger time no longer grows with the corpus: the dirty-project functions cost about 0.3 ms per call at 5k and
  50k (baseline 1 ms rising to 17 ms), so trigger time at 50k fell from 113 s to 6 s. Every
  `browse_observation_projects` branch is an index scan at 50k (`EXPLAIN ANALYZE`, 0.3 ms); no new index was needed.
- Call counts are unchanged (about 21 dirty-project calls per new record) because the ORM writes one row per
  statement; statement-level triggers therefore do not reduce the lock count for this workload, only multi-row
  statements. Wall time at 50k fell only 10% (1,044 s to 936 s): the remaining roughly 900 s is client-side
  work that scales with corpus size and is not attributed here (cursor time in `FROM projects` statements is
  only 29.5 s; unindexed project matching and ORM hydration are the suspected remainder, targeted by Step 1).

## Legacy commit-per-record path baseline (before Step 3), 2026-11-11

The RRC source above commits once per collection segment, so it cannot show per-record commit cost. Step 3 changes
the other path: `process_job` calling `process_records(commit=True)`, which commits at every durable boundary of
every record. `scripts/ingestion_write_benchmark.py --source legacy` measures it with the Fort Worth data-center
permit source (`fort-worth-development-permits`, retrieval method `fort-worth-permits`, not in the structured-segment
list). The planned Federal Register source was not usable: its mine notices are admitted as context only, so they
never reach project matching. Fort Worth rows are built by the adapter's own `record()` from synthetic permits (filed
within 22 days, Issued, new data-center building, Texas address), interpret to a Signal, create or match projects
(one third reuse seeded `Bench Energy Campus <n>` names for near-duplicate candidates), and run needs, lifecycle,
material state and adjudication. Offline: `service.retrieve_source` is monkeypatched, no model, no network. Phase c
amends the work description of 5% of records. R = 300 per phase, same corpus recipe, same machine and Postgres as
above. The integration head already includes Step 1 (indexed project matching), so these numbers are Step 1 plus
nothing else.

```
python ../scripts/ingestion_write_benchmark.py --database-url "$TEST_DATABASE_URL" --source legacy --projects 5000 --records 300 --json-out ../experience/benchmarks/ingestion-writes-legacy-baseline-5k.json
python ../scripts/ingestion_write_benchmark.py --database-url "$TEST_DATABASE_URL" --source legacy --projects 50000 --records 300 --json-out ../experience/benchmarks/ingestion-writes-legacy-baseline-50k.json
```

5,000 seeded projects (5,300 after phase a):

| phase | wall s | rec/s | commits/rec | stmts/rec | lock stmts/rec | trigger calls/rec | trigger ms | trigger % wall | project scans | scan s |
|---|---|---|---|---|---|---|---|---|---|---|
| a all new | 25.8 | 11.62 | 3.00 | 76.0 | 13.01 | 49.0 | 5502 | 21.3% | 1500 | 0.9 |
| b all unchanged | 4.3 | 70.24 | 2.00 | 14.0 | 5.01 | 0.0 | 0 | 0.0% | 300 | 0.1 |
| c 5% changed | 4.4 | 67.84 | 2.05 | 17.0 | 5.46 | 2.0 | 264 | 6.0% | 345 | 0.1 |

50,000 seeded projects (50,300 after phase a):

| phase | wall s | rec/s | commits/rec | stmts/rec | lock stmts/rec | trigger calls/rec | trigger ms | trigger % wall | project scans | scan s |
|---|---|---|---|---|---|---|---|---|---|---|
| a all new | 137.9 | 2.18 | 3.00 | 76.0 | 13.01 | 49.0 | 109308 | 79.3% | 1500 | 2.7 |
| b all unchanged | 4.8 | 62.40 | 2.00 | 14.0 | 5.01 | 0.0 | 0 | 0.0% | 300 | 0.1 |
| c 5% changed | 12.4 | 24.15 | 2.05 | 17.0 | 5.46 | 2.0 | 6494 | 52.3% | 345 | 0.1 |

Reading: 300 new records give 300 signals and 300 accepted permits in phase a, 300 unchanged in b, 15 changed in c.
The legacy path really does commit 2 to 3 times per record (commit events counted client side; an empty COMMIT still
counts). At 50k, all-new wall time is dominated by browse-invalidation triggers (79% inclusive), not by commits.
Single run per size, no variance; the machine is shared with other builders, so wall times carry noise.

## Legacy path after batch commits (Step 3), 2026-11-11

Same harness, corpus, machine and R = 300 as the baseline above, run on the Step 3 candidate with the defaults
(`INGESTION_BATCH_SIZE=200`, `INGESTION_BATCH_MAX_SECONDS=2.0`; in these runs the 2 s time bound, not the size, ends
almost every batch). JSON: `experience/benchmarks/ingestion-writes-legacy-after-{5k,50k}.json`.

5,000 seeded projects:

| phase | wall s (base to after) | rec/s (base to after) | commits/rec | stmts/rec | lock stmts/rec | trigger ms | project scans |
|---|---|---|---|---|---|---|---|
| a all new | 25.8 to 24.9 | 11.62 to 12.03 | 3.00 to 0.05 | 76.0 to 81.1 | 13.01 to 12.06 | 5502 to 6433 | 1500 to 1500 |
| b all unchanged | 4.3 to 2.4 | 70.24 to 126.24 | 2.00 to 0.01 | 14.0 to 17.0 | 5.01 to 4.02 | 0 to 0 | 300 to 300 |
| c 5% changed | 4.4 to 4.1 | 67.84 to 73.60 | 2.05 to 0.01 | 17.0 to 20.1 | 5.46 to 4.47 | 264 to 431 | 345 to 345 |

50,000 seeded projects:

| phase | wall s (base to after) | rec/s (base to after) | commits/rec | stmts/rec | lock stmts/rec | trigger ms | project scans |
|---|---|---|---|---|---|---|---|
| a all new | 137.9 to 142.3 | 2.18 to 2.11 | 3.00 to 0.21 | 76.0 to 81.4 | 13.01 to 12.22 | 109308 to 114165 | 1500 to 1500 |
| b all unchanged | 4.8 to 3.3 | 62.40 to 90.06 | 2.00 to 0.01 | 14.0 to 17.0 | 5.01 to 4.02 | 0 to 0 | 300 to 300 |
| c 5% changed | 12.4 to 10.1 | 24.15 to 29.65 | 2.05 to 0.02 | 17.0 to 20.2 | 5.46 to 4.48 | 6494 to 6492 | 345 to 345 |

Reading, plainly:
- Commits per record fall from 2 to 3 to 0.01 to 0.2, but statements per record rise by 3 to 4 (a RELEASE and a SAVEPOINT
  at every former commit point, which is cheaper than a COMMIT only where COMMIT is expensive). On this machine a COMMIT is
  cheap (local Postgres, no network), so the gain is small.
- All-new ingestion, the expensive case, is unchanged within noise (24.9 s vs 25.8 s at 5k, 142 s vs 138 s at 50k): it is
  dominated by browse-invalidation triggers (80% of wall at 50k, 109 s to 114 s), not by commits. Batching does not touch
  that cost; Step 2 does.
- Unchanged replays, which only pay commits, fixed fence checks and cheap reads, are 1.4x to 1.8x faster (5k: 70 to 126 rec/s;
  50k: 62 to 90 rec/s). Amendments gain 8% to 22%. Single run per size on a shared machine, so treat every wall time as
  +/- 10%.
- A network round trip per commit (managed Postgres, a separate host) and a slower fsync would raise the gain; neither is
  measured here.
- Recommendation: keep the step only as the measurable win for the unchanged/amended replays that dominate steady state, and
  only together with the lock narrowing below; if the narrowing is not accepted, the 2 s lock window it introduces is a cost
  with a gain that is only visible on replays, and dropping the step is defensible.

### Lock scope of a batch (Step 3)

Row locks taken per record (`lock_project`, `SELECT ... FOR UPDATE` on observations, interpretations, needs, project
material state and the job row, membership advisory locks) are held until the batch commit instead of the record commit, so
the window grows from one record to at most `INGESTION_BATCH_MAX_SECONDS` plus the record in flight. Measured by
`test_open_ingestion_batch_does_not_block_api_style_writes` (an open batch on committed rows, other connections writing under
`lock_timeout = 400ms`):

| API-style write | result |
|---|---|
| contact suppression insert | completes |
| saved-view style write (workspace change acknowledgment) | completes |
| commercial pursuit insert (FK to need and project) | BLOCKED until the batch ends |
| owner fact insert (`call_fact_versions`, FK to need and project) | BLOCKED until the batch ends |
| need workflow status insert (FK to need and project) | BLOCKED until the batch ends |

Cause: a foreign key INSERT takes FOR KEY SHARE on the referenced row, which conflicts only with FOR UPDATE. Ingestion
uses FOR UPDATE on projects (`lock_project`, `seed_material_state`, `enqueue_retained_buying_chain_research`) and needs.
Switching those to FOR NO KEY UPDATE is equivalent for mutual exclusion between ingestion workers (and any other FOR
UPDATE or NO KEY UPDATE locker) and removes the wait: with the change applied locally, all five probes complete. It needs
edits outside the Step 3 file ownership (`change_detection.lock_project`, `buying_chain.enqueue_retained_buying_chain_research`)
and changes the SQL text matched by the existing test `test_linked_negative_correction_locks_project_before_need` (it greps
for `for update`), so it was NOT applied. The proposed patch is `experience/benchmarks/step3-lock-narrowing.patch` (service.py, the two files and the test string; the test hunk is illustrative, not line-exact)
Until then the wait is bounded by the time bound (2 s default) plus the slowest single record, because the bound is checked only between records (about 0.5 s per record in the 50k all-new run). Caveat on the lock probe: the test schema has no `browse_state` row and no browse triggers, so it cannot see the system-wide `browse_state` row lock that real writes to the scoped tables take and a batch would hold until it commits; `FOR NO KEY UPDATE` does not remove that wait, which needs the lock-free revision design (Step 2b). Batching also lengthens the window for lock-order deadlocks between concurrent writers.
