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
