# Matched local performance evidence

Measured November 12–13, 2026. Baseline `bf75d32746d28ac44effcb65989d53fdeaa765e4` versus candidate `4b6d0f92ad3d2475c9a783fe7b6bdd649ca0c74a`. Ingestion ran at those exact commits. During the later rollup stage candidate HEAD advanced to `953b63d4ebc4bd074bedda1a5d533ea4b703dd13` for web/UI and validation artifacts; its backend Python source manifest was identical to measured `4b6d0f92` (`1a7b43fa01c8aa005e6c47a4eb67ea25bd89348bef7efb39c9b91d8deb3e0a96`). These direct backend measurements make no UI timing claim. Both backend source manifests stayed unchanged throughout each measured run. PostgreSQL reports 16.2; the executor has a four-CPU cgroup quota and 16 GiB memory limit.

**This is not a no-regression pass.** Candidate SQL work and serialized payload sizes increased. Wall-clock measurements also share the machine with root's four-worker backend test suite, and each candidate run followed its baseline sequentially. No quiet-machine repeat or variance estimate is available. The prior separate 31.4-second baseline is not substituted into this matched pair.

## Ingestion

The existing, unchanged `scripts/ingestion_write_benchmark.py` ran the real offline Texas RRC ingestion path on separate newly created task databases, with 5,000 seeded projects and 300 records per phase.

| Phase | Baseline seconds | Candidate seconds | Baseline SQL | Candidate SQL |
| --- | ---: | ---: | ---: | ---: |
| All new | 73.467 | 102.493 | 27,067 | 27,967 |
| Unchanged replay | 5.030 | 9.368 | 3,927 | 4,227 |
| 5% amended | 8.091 | 9.386 | 4,887 | 5,217 |

Both runs report 300 new records, then 300 unchanged records, then 15 amendments/285 unchanged records, ending with 5,300 projects and 300 observations. Commit counts are five per phase for both candidates. Trigger-call counts are identical: 20,740 / 0 / 570. The added 900 / 300 / 330 SQL statements are a deterministic observed cost; noisy timings do not erase that increase. This does not establish behavior at 50,000 projects.

The pair crosses UTC midnight. Fixture records and phase definitions are unchanged, but the harness's current-day collection-window date changes between the two runs. The reports retain the actual timestamps and source-run outcomes, including their bounded `PARTIAL` collection status; they do not claim completion of a live scheduled source cycle.

## Customer rollups

Each source's existing `web/acceptance/rollup-scale/seed.py` and `account_fixture.py` seeded its own empty, migrated task database. Both have 2,098 canonical project rows and 2,098 synthetic presentation rows representing 417 groups. The existing fixture intentionally materializes only 48 underlying need/evidence records; it is a synthetic frozen browse corpus, not a retained-production snapshot or a corpus of 2,098 fully researched needs. It contains no newly supported customer capacity facts. The fixture's source-matched `POLICY_VERSION` was preserved.

Root's `scripts/benchmark_customer_commercial.py` ran unchanged, with ten direct read-only service calls at each page size. Its first sample includes process-local initialization; no separate cold/warm classification is asserted. The nearest-rank p95 of ten samples is their maximum, so it is especially unstable.

| Page size | Baseline p50 / p95 ms | Candidate p50 / p95 ms | Baseline SQL counts | Candidate SQL counts | Baseline JSON bytes | Candidate JSON bytes |
| --- | ---: | ---: | --- | --- | ---: | ---: |
| 1 | 204.101 / 1,111.115 | 264.506 / 1,279.209 | 53–55 | 59–61 | 5,471 | 58,113 |
| 25 | 186.330 / 285.761 | 355.401 / 484.270 | 53 | 55 | 15,756 | 187,193 |
| 50 | 243.729 / 741.773 | 391.051 / 481.619 | 53 | 55 | 26,356 | 308,443 |

The flat 55-query count for candidate pages 25 and 50 shows no query-per-card growth in these sampled cohorts. Page 1 exercises a different contact-bearing cohort path and has additional queries; this is not a proof that every account/contact shape is free of N+1 behavior. The payload increase is material and should be reviewed before release. Byte counts are a separate direct read, compact JSON UTF-8 with `default=str`; they exclude headers, compression and transport. Latencies exclude HTTP, authentication and browser/UI rendering. They do not prove mobile/network responsiveness.

All three provider-accounting tables contain zero rows in both rollup databases. Ingestion retrieval is monkeypatched by the existing benchmark. Seeder discovery uses retained deterministic fixtures and blocks paid search. No production, retained-data or paid-provider execution occurred.

## Reproduction and receipts

From `/workspace/gl3-commercial`, with the task environment configured without printing credentials:

```bash
source /workspace/task-runtime/env.sh
uv run --no-sync --project backend python docs/validation/customer-intelligence-20261112/performance/run_matched.py ingestion
uv run --no-sync --project backend python docs/validation/customer-intelligence-20261112/performance/run_matched.py rollup
python docs/validation/customer-intelligence-20261112/performance/summarize.py
```

`run_matched.py` pins the baseline/candidate checkouts and restricts targets to four explicit task-owned loopback database names on port 55439. The ingestion harness recreates only its two designated disposable databases. The rollup runner refuses existing target databases and nonempty schemas. Logs and the root measurement harness refuse to overwrite prior receipts. These commands describe the original run; an intentional repeat needs fresh receipt filenames and, for reseeding, new expressly authorized disposable databases or separately authorized cleanup of these task-owned databases. Ordinary repeated rollup measurement can read the existing corpus without reseeding, preserving source policy and using new output filenames.

[summary.json](summary.json) recomputes the tabulated metrics from raw reports. Per-side JSON reports retain phase outcomes, SQL/trigger details, sample latency lists and actual corpus counts. `*-metadata.json` records source/harness hashes, sanitized log hashes, command exits and timestamps. [machine.json](machine.json) records a process snapshot without command arguments. [executor-interruption.json](executor-interruption.json) explains the transport outage: the candidate ingestion completed while the transport was down; recovery checked completion markers and did not duplicate it. [sha256-manifest.json](sha256-manifest.json) hashes every retained file except itself.

The latency differences need a quiet matched repeat before a strict regression conclusion. Independently of timing noise, the observed added statements and response bytes remain explicit release-review considerations.
