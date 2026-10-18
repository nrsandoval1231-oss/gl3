# B1 performance and correctness evidence

Runtime implementation: PR77, based on main `9e20bbd`. These are disposable local
PostgreSQL fixtures and server-function measurements, not production HTTP/browser
acceptance. The production evidence/project counts supplied by Nick set fixture
sizes; a production-sized data copy was unavailable. Each fabricated project has
one active Signal, with dated retained histories and roughly 1 KB source abstracts.
This is not a claim that production has one need per project or this data mix.

Ordinary ranked page/map reads use saved counts and an ordered index. Filtered
reads preserve dynamic grouping/search by aggregating scalar summaries and loading
only selected payloads. Detail reads use canonical evaluators for the exact need.
No measured saved read rebuilds the evidence population. The rollout remains off
until retained-corpus and authenticated deployment checks can be performed.

## Measurement protocol

`backend/scripts/benchmark_saved_browse.py` creates a random schema in an explicit
disposable `*_test` database and drops only that schema afterward. It seeds retained
evidence, captures an evidence checksum before/after rebuilding, measures sequential
and concurrent reads, and records the PostgreSQL plan. Provider calls, collection,
research and scheduler execution are absent. No production data is modified.

Saved measurements use 30 samples per case, with up to four concurrent calls in one
Python process. Legacy comparisons use three samples, including three concurrent
calls; their empirical p95 is simply the maximum and is diagnostic, not a robust
latency SLO. Canonical/saved output fingerprints must agree on selected IDs/order,
tiers, MW/timing/supply, ranks/reasons, priority, workflow and grouping fields.

Times include handler/database work and payload-budget checks, but exclude HTTP,
authentication, browser rendering and network latency. Read counts include SQL
starting with SELECT or WITH; driver transaction/connection setup is separate.
Cold observations use a fresh Python process/connection pool against a warm
PostgreSQL cache, not an OS/database-cache flush. Cloud workspace cache/load is
uncontrolled. Database CPU, connection wait and production lock behavior are not
separately measured; peak process RSS includes building and legacy comparisons.

## Correctness and recovery

- Canonical source-backed operator workflow compares saved reads throughout fact
  acceptance, correction/rejection and source changes.
- Projection tests cover historical Unicode/search, literal wildcard text,
  dimension/timing/MW/workflow filters, dynamic cross-need grouping, exact rank
  metadata, extreme Decimal bounds including known/zero/unknown intervals, and
  selected detail metadata.
- All 27 declared canonical input tables have transactional statement invalidation;
  committed writes block stale generations, while rollback preserves freshness.
- Failed builds, competing builders, concurrent input changes, expiry/policy
  changes, clock crossings during construction, retention and guarded generation
  rollback are exercised on PostgreSQL.
- A 501-evidence history can publish compact summaries without truncating history;
  ordinary detail retains its existing explicit 500-row response limit.
- Migration upgrade/repeat, downgrade/re-upgrade and Alembic schema checks pass.

## Limits and production gate

Global invalidation deliberately favors correctness: any relevant mutation can
make browse pending until a whole generation is rebuilt. Arbitrary filters/search
still scan scalar cohorts; offset pages can walk skipped index entries. These are
not constant-time guarantees. No production sub-second p95, ingestion reliability,
or canonical-input-to-projection lag target is claimed from fixtures.

Connected DigitalOcean inventory confirms the production droplet, but exposes no
host command channel. This environment has no existing SSH identity/agent,
production database configuration or authenticated app session. No credentials,
access, collection, provider spending or infrastructure were enabled. Backup,
retained-corpus checksum/parity, live persistence and authenticated production
verification remain blocked. Activation/rollback procedure:
[saved-browse-b1.md](../../operations/saved-browse-b1.md).

## Recorded timings

Times below are seconds, shown as p50 / empirical p95 / max. Full raw records retain
read counts, payload bytes, output fingerprints, checksum pairs, restart reads and
PostgreSQL plans. Policy fingerprints bind each measurement to its implementation;
later edge fixes preserve empty group pages and oversized-offset behavior.

### 1,461 projects / 15,874 evidence

| Path | Sequential p50 / p95 / max | Concurrent p50 / p95 / max | Reads | Max bytes |
|---|---:|---:|---:|---:|
| Legacy ranked_page | 33.349 / 34.738 / 34.738 | 51.990 / 52.068 / 52.068 | 807 | 909,338 |
| Legacy map | 16.374 / 22.923 / 22.923 | 61.688 / 62.275 / 62.275 | 873 | 3,648,763 |
| Legacy detail | 7.143 / 8.772 / 8.772 | 26.791 / 27.567 / 27.567 | 147 | 16,662 |
| Saved ranked_page | 0.007 / 0.032 / 0.040 | 0.027 / 0.220 / 0.230 | 2 | 102,493 |
| Saved filtered | 0.028 / 0.055 / 0.066 | 0.042 / 0.195 / 0.212 | 3 | 102,469 |
| Saved map | 0.018 / 0.057 / 0.063 | 0.135 / 0.402 / 0.469 | 2 | 410,955 |
| Saved detail | 0.082 / 0.436 / 0.465 | 0.335 / 0.564 / 0.565 | 33 | 16,662 |

Build: **22.6 s**. Fresh-process page: **0.083 s**, 2 instrumented statements. Evidence count/checksum unchanged. Peak process RSS: 277,028 KiB. [Raw result](final-fixture-1461.json).

### 2,922 projects / 31,748 evidence

| Path | Sequential p50 / p95 / max | Concurrent p50 / p95 / max | Reads | Max bytes |
|---|---:|---:|---:|---:|
| Saved ranked_page | 0.006 / 0.021 / 0.034 | 0.025 / 0.101 / 0.110 | 2 | 102,493 |
| Saved filtered | 0.013 / 0.042 / 0.178 | 0.025 / 0.074 / 0.082 | 3 | 102,469 |
| Saved map | 0.011 / 0.019 / 0.026 | 0.039 / 0.068 / 0.086 | 2 | 410,955 |
| Saved detail | 0.066 / 0.438 / 0.485 | 0.169 / 0.874 / 2.482 | 33 | 16,616 |

Build: **71.5 s**. Fresh-process page: **0.226 s**, 2 instrumented statements. Evidence count/checksum unchanged. Peak process RSS: 127,240 KiB. [Raw result](final-fixture-2922.json).

### 10,000 projects / 100,000 evidence

| Path | Sequential p50 / p95 / max | Concurrent p50 / p95 / max | Reads | Max bytes |
|---|---:|---:|---:|---:|
| Saved ranked_page | 0.004 / 0.005 / 0.007 | 0.014 / 0.027 / 0.035 | 2 | 102,493 |
| Saved filtered | 0.024 / 0.026 / 0.029 | 0.033 / 0.047 / 0.050 | 3 | 102,469 |
| Saved map | 0.010 / 0.011 / 0.012 | 0.039 / 0.059 / 0.067 | 2 | 410,958 |
| Saved detail | 0.046 / 0.050 / 0.096 | 0.148 / 0.200 / 0.210 | 33 | 16,609 |

Build: **66.1 s**. Fresh-process page: **0.042 s**, 2 instrumented statements. Evidence count/checksum unchanged. Peak process RSS: 143,328 KiB. [Raw result](final-fixture-10000.json).

The rank-page plan reads 50 rows through an ordered index in every recorded case.
The 2× rebuild (71.5 s) and 10,000-need rebuild (66.1 s) exceed the proposed
60-second lag target; that target is not established. The 2× detail maximum of
2.48 s is retained alongside its sub-second empirical p95.

### Additional 2× historical-search run

This separate uncontented fixture run adds a cross-history substring query (`history 9`),
with the same data sizes, 30 samples and four concurrent calls. It does not replace
the outlier/build measurements above.

| Path | Sequential p50 / p95 / max | Concurrent p50 / p95 / max | Reads |
|---|---:|---:|---:|
| ranked_page | 0.004 / 0.005 / 0.006 | 0.014 / 0.028 / 0.030 | 2 |
| filtered | 0.011 / 0.013 / 0.013 | 0.022 / 0.029 / 0.031 | 3 |
| search | 0.154 / 0.163 / 0.180 | 0.201 / 0.245 / 0.279 | 3 |
| map | 0.010 / 0.011 / 0.013 | 0.038 / 0.056 / 0.062 | 2 |
| detail | 0.041 / 0.053 / 0.092 | 0.147 / 0.170 / 0.175 | 33 |

Build 29.7 s; cold process 0.045 s; evidence checksum unchanged. [Raw result](final-fixture-2922-search.json).

## Review and automated checks

Independent source review approved the runtime changes, including policy/input
fencing, expiry clocks, compact pages, group/offset edge cases and Decimal bounds.
The final focused PostgreSQL suite passes **44 tests**. The full local suite passed
**1,780 tests / 1 skipped** before the final boundary cases were added; GitHub CI
on the initial implementation passed **1,786 backend / 1 skipped** and
**141 browser / 1 skipped**, including real disposable authentication. Exact final
head CI is required before merge; its source-of-truth status is linked in PR77.
