# November 13 matched performance recheck

This recheck compares baseline `5ee2f30c2b1c9998063db1c6468d1f4e65f7ac2d` with optimized
commit `e653c78f11b48dad2926d37c72a5d35f5b1512fc`. The source manifests are stable during
the successful runs: baseline `ccab75506a8587426ec983b3339b89066493fb5c02cd495f6346790592a8a4ec`,
optimized `08b731418fd83c707fc6264b37bdac0bf777c9400a070fe019d9c947d1d57cb1`. Both use the
same local `uv` environment (Python 3.11.16, SQLAlchemy 2.0.41, BeautifulSoup 4.13.4,
Soupsieve 4.0, psycopg 3.2.9) and PostgreSQL 16.2 on loopback port 55439. All benchmark
databases end in `_test`; no production or retained database and no external or paid provider
was used.

## Ingestion

The baseline and successful optimized run both processed 5,000 seeded projects and 300
synthetic permit records through new, unchanged, and 5%-changed phases. Each phase used five
commits and returned matching record counts. The candidate lane had a 150 ms observer polling
its PostgreSQL activity, so its wall times are diagnostic and not a causal speedup comparison.

| Phase | Baseline seconds / SQL | Optimized seconds / SQL | `FROM projects` scans, baseline / optimized |
| --- | ---: | ---: | ---: |
| 300 new | 50.509 / 27,067 | 48.085 / 27,667 | 2,100 / 2,100 |
| 300 unchanged | 3.897 / 3,927 | 3.629 / 3,927 | 300 / 300 |
| 15 changed, 285 unchanged | 4.698 / 4,887 | 4.617 / 4,917 | 375 / 375 |

The preloaded-project optimization removes the excess project scans measured in the previous
candidate run: scan counts now match the same-day baseline in all phases. The remaining SQL
difference is 600 statements for 300 new records and 30 for the 15 changed records, or two
statements per new or changed record, in the typed-fact validation path. Unchanged replay has
no statement-count delta. This fixture shows no new project-scan growth; it does not establish
that every account/contact shape is free of N+1 queries.

One uninstrumented optimized attempt failed while autoflushing a `NeedObservation` insert. The
nested `invalidate_browse_generation()` trigger statement updating `browse_state` was canceled
under the application’s `SET LOCAL statement_timeout = '2500ms'`. This is a per-statement
deadline, not a cumulative transaction deadline. Post-failure sampling found no active session
or lock on the two run databases. The initial timeout cause remains unresolved.

A single instrumented fresh candidate reproduction then completed all three phases with the
same 2.5 second setting. Its 411 activity samples found no blocker PIDs, no lock waits, and no
active SQL older than 521 ms. It observed one `DataFileExtend` and one `WALSync` wait sample.
CPU and I/O pressure files were unavailable; cgroup throttled CPU time rose by about 13.6
seconds during the 80 second run, and host load average rose from 0.22 to 1.49. This successful
reproduction does not prove the first timeout was a flake. The observer and pressure receipts
are retained in `candidate_observer.jsonl`, `candidate_host_pressure.jsonl`, and
`candidate_instrumented_metadata.json`.

The initial failed attempt and its sanitized log remain preserved as
`ingestion_candidate.log`; its database is `gl3_mission_ingest_recheck_candidate_test`. That
failed database remains test-only with its 5,000-project seed and zero persisted observations.
The successful baseline and candidate databases are `gl3_mission_ingest_recheck_base_test` and
`gl3_mission_ingest_repro_candidate_test`; each ended at 5,300 projects and 300 observations.
Logical-call, budget, and settlement ledgers were zero on the successful baseline and candidate
databases.

## 40k customer rollup

The baseline rollup measurement is a read-only repeat on the existing synthetic 40,000-project
corpus. The optimized measurement uses a fresh seeded database. Both corpora have 40,000
projects, 48 needs, 48 evidence rows, 38,319 groups, and 16 companies. Ten direct service samples
per page size use read-only transactions, a 15 second statement timeout, and transaction-local
`jit=off`, matching the request context. SQL is counted immediately before each service call.

| Page size | Baseline p50 / p95 ms | Optimized p50 / p95 ms | SQL per sample | Compact JSON bytes, baseline / optimized |
| ---: | ---: | ---: | --- | ---: |
| 1 | 2,617 / 7,357 | 2,725 / 7,854 | 55 first call, then 53 | 5,475 / 7,180 |
| 25 | 2,554 / 3,008 | 2,863 / 4,282 | 53 | 15,760 / 57,128 |
| 50 | 2,573 / 3,036 | 2,870 / 3,740 | 53 | 26,360 / 109,378 |

The statement count is flat from page size 25 to 50 for this corpus. Candidate p50 at page size
25 is 12.1% higher and p95 is 42.4% higher; the nearest-rank p95 is the maximum of ten samples
and is unstable. Compact response JSON is 3.62x baseline at page size 25 and 4.15x at page size
50, reflecting the added commercial-intelligence projection. This is a material latency and
payload tradeoff to retain in the release review. All three logical-call accounting tables have
zero rows on both sides.

The rollup latency and byte counts are direct local service measurements. They exclude HTTP,
authentication, network transport, compression, and browser rendering; they do not establish a
production SLA. Full per-run results, hashes, SQL samples, and database names are in
[`summary.json`](summary.json), [`rollup_recheck_metadata.json`](rollup_recheck_metadata.json),
[`rollup_base.json`](rollup_base.json), and [`rollup_candidate.json`](rollup_candidate.json).

## Reproduction commands

From `/workspace/gl3-commercial`, with the private task environment loaded:

```bash
source /workspace/task-runtime/security-env.sh
uv run --no-sync --project backend python docs/validation/customer-intelligence-20261112/final-performance/recheck-20261113/run_recheck.py
uv run --no-sync --project backend python docs/validation/customer-intelligence-20261112/final-performance/recheck-20261113/instrument_candidate.py
uv run --no-sync --project backend python docs/validation/customer-intelligence-20261112/final-performance/recheck-20261113/run_recheck.py --rollup-only
uv run --no-sync --project backend python docs/validation/customer-intelligence-20261112/final-performance/recheck-20261113/measure_payload.py --side base --output docs/validation/customer-intelligence-20261112/final-performance/recheck-20261113/rollup_base_payload.json
uv run --no-sync --project backend python docs/validation/customer-intelligence-20261112/final-performance/recheck-20261113/measure_payload.py --side candidate --output docs/validation/customer-intelligence-20261112/final-performance/recheck-20261113/rollup_candidate_payload.json
```

The initial same-day paired command's candidate run failed and is retained as `ingestion_candidate.log`;
the separate instrumented command is the single successful candidate reproduction. Commands refuse
to reuse existing output receipts and the instrumentation and rollup scripts use fixed task-owned
database names. Do not rerun them against existing receipts or databases.
