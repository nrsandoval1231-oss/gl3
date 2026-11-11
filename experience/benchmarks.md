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
