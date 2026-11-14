# Read performance repair: fresh matched evidence

Candidate backend `1de298af047f09a32e9a0349f41410a55bc1791e` versus baseline `bf75d32746d28ac44effcb65989d53fdeaa765e4`, measured November 13, 2026. Both application source worktrees were clean, and their backend Python manifests remained unchanged. The root's query/compaction repair is measured here; the [earlier 4b6d0f92 results](../README.md) remain historical and are not relabeled as this candidate.

**The repair restores the baseline's sampled read-model query count and reduces the earlier candidate's payloads. It does not establish a latency regression pass.** Repair latency remains higher than baseline in these measurements. Live integrated-test/PostgreSQL activity shared the executor. Snapshots include process STAT: the old four workers are `Z` (defunct), while the then-current pytest process and CPU-active PostgreSQL process are live. No quiet-machine or production-SLA claim is made.

## Unchanged canonical service harness

Root's `scripts/benchmark_customer_commercial.py` ran unchanged with 30 samples at each page size. It invokes the read service directly, without the API's transaction-local JIT setup. It counts service SQL statements after its own read-only/timeout setup and excludes HTTP, authentication, browser rendering and compression.

| Customers per page | Baseline p50 / p95 ms | Repair p50 / p95 ms | Baseline SQL | Repair SQL | Baseline JSON bytes | Repair JSON bytes |
| --- | ---: | ---: | --- | --- | ---: | ---: |
| 1 | 192.121 / 305.084 | 286.008 / 399.944 | 53–55 | 53–55 | 5,471 | 7,176 |
| 25 | 241.511 / 261.450 | 375.371 / 836.131 | 53 | 53 | 15,756 | 57,126 |
| 50 | 187.575 / 243.948 | 360.325 / 458.946 | 53 | 53 | 26,356 | 109,376 |

First-call initialization accounts for the 55-query sample; remaining samples use 53. Query count stays flat across the sampled 25/50-customer pages. That closes the observed extra per-request statements in the earlier commercial read projection for this fixture; it is not proof against N+1 behavior for every contact/source shape.

The corresponding historical 4b6d0f92 payloads were 58,113 / 187,193 / 308,443 bytes. The repair reduces those by approximately 88% / 69% / 65%. It still carries additional intelligence relative to baseline, so its payload is larger than baseline. Historical and fresh timing samples have different load conditions and sample counts; do not infer a repair timing improvement by comparing their medians.

## Supplemental source-specific API transaction setup

The separate `measure_api_setup.py` calls each pinned source's actual `_begin_consistent_read` before the same `groups` service. This preserves baseline REPEATABLE READ and includes the repair's real transaction-local `SET LOCAL jit=off`. These timings/counts also include the setup plus the benchmark's READ ONLY and statement-timeout guard statements. They still exclude HTTP, authentication and UI.

| Customers per page | Baseline p50 / p95 ms | Repair p50 / p95 ms | Baseline SQL including setup | Repair SQL including setup |
| --- | ---: | ---: | --- | --- |
| 1 | 200.084 / 439.621 | 249.977 / 297.834 | 55–57 | 56–58 |
| 25 | 208.497 / 290.620 | 322.407 / 525.532 | 55 | 56 |
| 50 | 185.041 / 270.328 | 513.373 / 826.759 | 55 | 56 |

The repair's extra setup statement is its intended transaction-local JIT policy; it does not represent query-per-card growth. This supplement does not establish a general latency gain from that setting in this cohort. It remains separate from the unchanged canonical harness result.

## Corpus, safety and source boundaries

Both corpora have 2,098 project rows and 2,098 synthetic frozen presentation rows representing 417 groups, with 48 underlying persisted needs and evidence rows. This existing fixture does not represent 2,098 fully researched needs and has no newly supported customer capacity facts. Rich retained-source/engineering performance and a 40,000-project corpus remain unmeasured here.

Baseline reuses its existing task-owned `commercial_rollup_scale_perf_base_test` corpus read-only. Repair uses a new, empty, source-matched `commercial_rollup_scale_perf_repair_test`, migrated and populated through its existing `seed.py` and `account_fixture.py` without fixture changes. Both use PostgreSQL 16.2 on loopback port 55439. Root's source-specific policy version is preserved by each seeder. Both body-size samples report zero logical calls, budgets and settlements. No ingestion, retained/production-data mutation, external research or paid provider call was run in this repair measurement.

The external PR197 SQL work was reconciled by root into the candidate. Its historical 40,000-project claims are not new measurements of this candidate. This report neither claims that PR was merged nor establishes a live production cause. See the candidate's engineering reconciliation document for exact upstream provenance and separate tests.

## Reproduction and retained evidence

With the task environment loaded without printing credentials:

```bash
source /workspace/task-runtime/env.sh
uv run --no-sync --project backend python docs/validation/customer-intelligence-20261112/performance/read-repair/run_read_repair.py --repair-commit 1de298af047f09a32e9a0349f41410a55bc1791e
```

The runner pins source roots, refuses a different/uncommitted repair source, accepts only its explicit task-owned loopback databases, refuses an existing repair database and refuses receipt overwrites. This command describes the original run; do not rerun it blindly against existing artifacts. Repeat measurements can read the existing compatible corpora with new output names. No new ingestion benchmark was requested or run after the repair.

- `base.json` / `repair.json`: canonical harness source hashes, actual corpus, 30 raw timings/query counts per page and account totals.
- `base-body.json` / `repair-body.json`: compact JSON UTF-8 bytes, query counts and provider-ledger counts; excludes transport/compression.
- `metadata.json`: pinned commits, before/after source hashes, clean-source checks, command exits, seeder/harness hashes, timestamps and real process-state snapshots.
- `base-api-setup.json` / `repair-api-setup.json`: separately labeled API-setup supplement with source manifests and raw samples.
- `api-setup-metadata.json`: supplement commits, exits, sanitized log hashes and process-state snapshots.
- `summary.json` / `sha256-manifest.json`: reproducible metric summary and hashes of retained non-log artifacts. Sanitized local logs are supplemental workspace receipts and may be ignored by repository policy.

The measured remaining latency overhead and shared-load limitations remain explicit release-review considerations. Full CI, independent acceptance, source-extraction quality and production readiness are separate gates.
