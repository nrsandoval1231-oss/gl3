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

## Mutation availability and expiry acceptance gate

Ordinary operator edits initially invalidated every browse read until a full
rebuild. The measured full-rebuild pending window was unacceptable for ordinary
work. The revised implementation publishes project-scoped canonical refreshes in
the same transaction as supported operator edits. Broad/unknown writes, policy
changes, derived failures, oversized dirty sets and clock expiry remain explicit
pending/full-build cases.

The following final runs use the same fabricated dated histories and evidence
sizes, 12 sequential workflow edits, 12 edits in four-writer bursts, continuous
repeatable-read ranked-page calls, and four each actual fact draft/accept/retract
handler calls. They time server functions plus committed fresh-read verification;
HTTP/authentication/network are excluded. Writer timings include serialized
publication contention. The background read includes an extra qualification probe
before the ordinary two-query saved page. Connection wait and database CPU are not
separately measured. Empirical p95 at these small write sample counts equals max.

| Path | 1,461 projects p50 / p95 / max (s) | 2,922 projects p50 / p95 / max (s) |
|---|---:|---:|
| Sequential workflow | 0.208 / 0.292 / 0.292 | 0.384 / 0.446 / 0.446 |
| Four-writer workflow | 0.493 / 0.927 / 0.927 | 0.882 / 1.748 / 1.748 |
| Concurrent ranked read | 0.005 / 0.010 / 0.031 | 0.005 / 0.009 / 0.060 |
| Fact draft | 0.212 / 0.470 / 0.470 | 0.402 / 0.567 / 0.567 |
| Fact accepted | 0.210 / 0.347 / 0.347 | 0.450 / 0.556 / 0.556 |
| Fact retracted | 0.227 / 0.308 / 0.308 | 0.444 / 0.526 / 0.526 |

Both runs observed **zero pending/errors during ordinary workflow writes**, across
442 and 911 background reads. Workflow handler + fresh probe used
[62] / [62] instrumented SQL statements (writes/ANALYZE included, not read-only
query counts). Fact statement counts were captured in the 2× raw run; the 1× fact
phase records time only. The ordinary saved read path remains two statements.

Without incremental publication, an ordinary committed write followed by a full
rebuild left qualification pending for 16.116 / 23.799 s.
External scoped SQL commit plus immediate maintenance refresh took
0.207 / 0.455 s; add the maintenance process's nominal
250ms polling interval (and scheduling/load delay) in real operation.

Full initial builds took 18.775 / 26.341 s. Forced stored-clock expiry required
12.374 / 22.267 s of pending before publication. Each expiry rebuild overlapped
eight actual workflow edits at 250ms spacing; all eight saved successfully, and
the builder published once after canonically rebasing their bounded tail. All eight API calls succeeded and publication completed rather than being
superseded; regression tests separately verify these edits survive rebasing. No
stale generation was served as current. This simulates a
stored expiry crossing rather than waiting for a real date rollover; focused
PostgreSQL tests separately exercise future fact boundaries, calendar deadlines
and a clock advancing during incremental/full construction.

Evidence counts/checksums matched before/after both runs, and only three derived
generations remained. [1× raw result](mutation-fixture-1461.json),
[2× raw result](mutation-fixture-2922.json).

A prior incremental candidate kept browse available but had slow publication
plans: workflow p95 4.057 s sequential / 13.275 s four-writer.
The final code analyzes the newly copied generation before global metadata work,
skips unchanged compact group metadata and aggregates counts directly from groups.
[Retained diagnostic](mutation-planner-diagnostic-1461.json).

**Limits:** SQL cloning/pruning still copies population-sized presentation payloads;
canonical evidence reconstruction is limited to dirty projects. Four competing
writers can exceed one second, and clock/broad invalidations still interrupt browse
for a full build. These fixture improvements do not establish a production-wide
sub-second API SLO or eliminate the earlier 71.5-second contended rebuild outlier.
The rollout switch remains false until production backup/parity/access gates pass.

## Review and automated checks

Independent review found and reproduced a stale-tail rebase race; retained dirty
revisions and a regression test prevent already-published corrections from being
lost. Final independent focused PostgreSQL validation passed **52 tests**. Full
local regression passed **1,803 / 1 skipped** before the final reader/clock cases;
final focused validation passed **52**. Ruff, mypy (103 source files), migration
upgrade/repeat/downgrade/upgrade/schema-drift checks pass. Earlier browser CI passed
**141 / 1 skipped** with disposable authentication. Final exact-head CI is linked
in PR77 and remains a separate merge gate; no production deployment is claimed.
