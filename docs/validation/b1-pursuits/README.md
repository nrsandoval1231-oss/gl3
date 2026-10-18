# Commercial pursuits: saved canonical group selection

The production operator's sanitized profile on deployed `e222c4c` reported 163
reads and 7.98s instrumented handler time: 6.84s in whole-population canonical
summary reconstruction, 1.26s summed SQL cursor execution and 4ms JSON encoding.
The same path on a synthetic 1,461-project/15,874-evidence fixture took 5.347s
under cProfile, 163 statements, with 4.827s in the summary builder. This establishes
the cause; it does not imply profiler times equal ordinary request latency.

## Repair and semantic boundary

Migration 0023 adds nullable commercial group and three numeric priority fields,
plus a composite index, to existing derived browse rows. Existing canonical
`_priority` and current-support work identity determine these values during full,
prepared and incremental generation builds. UUID project/need columns supply the
remaining priority tuple components. Old generations are fenced by the runtime
policy fingerprint and require rebuilding; their NULL fields are never current.

Only GET `/api/commercial/triage` opts into saved selection when
`SAVED_BROWSE_ENABLED=true`. SQL selects the minimum **complete** priority tuple
for each Signal commercial group, orders groups, and then loads every member of
the requested groups. It preserves exact grouped totals, oversized group errors,
unselected oversized groups, empty offsets and arbitrarily large valid offsets.
Selected IDs/project IDs alone cross into Python. SQL still scans saved Signal
scalar rows; this is not a constant-time indexed group-page claim.

The existing preflight budgets and targeted canonical detail/card evaluation
remain in place, including its final card ordering, evidence, qualification,
accepted/rejected facts, buying-chain roles, HOLD/REJECT membership and notes.
Commercial work grouping is distinct from browse grouping. No card dispositions
are cached. Research/evaluation/write callers retain canonical selection and do
not acquire a new saved-generation dependency. With the switch false, GET uses
the original canonical path. A stale enabled generation returns explicit pending;
GET never repairs or reconstructs the population as a fallback.

## Benchmark method

`backend/scripts/benchmark_pursuits.py` creates/drops only a random schema in an
explicit `*_test` PostgreSQL database. It uses synthetic dated Signal histories
(~1KB abstracts), unique synthetic addresses and one active need/project, not a
production copy. It compares complete canonical/saved payload digests except the
response evaluation timestamp, including first, middle, final and empty pages.
Evidence full-row checksums/counts must match before/after.

Timing includes server functions, connection-pool acquisition and transactions;
HTTP/authentication/network/rendering are excluded, as is driver BEGIN in query
counts. PostgreSQL cache is warm. The host is shared with regression validation;
CPU and connection waits are not isolated. Baseline uses 5 sequential samples,
saved uses 30, and concurrency uses 40 calls with 4 readers. The small baseline
sample p95 equals its maximum. These are fixture measurements, not production
SLO acceptance. No real production date boundary has been observed by this task.

Final results and exact-head validation are recorded with the PR handoff. Initial
candidate diagnostics are retained separately when they predate the final runtime.

## Rollout

The PC task owns deployment and live QA. Follow the existing backup, disabled
collection/research/paid-AI and zero-budget gates in
[the operations guide](../../operations/saved-browse-b1.md). Stop retained browse
maintenance and keep the switch false while applying 0023/repeat/schema check.
Rebuild using the final runtime, compare retained-corpus commercial groups/pages
against the canonical path, restart maintenance and activate the existing switch.
Measure real authenticated pursuits first/middle/empty pages and concurrency.

Runtime rollback is the final image with the switch false, retaining additive
schema/canonical evidence. If reverting an image, stop maintenance and recreate
only API/web with `--no-deps`; never run older migration containers against 0023.
Broad/source invalidations, including existing full invalidation from pursuit
receipt/note writes, and unprepared expiry retain the pending/full-build fallback.
The saved GET now shares that freshness fence; verify save/readback behavior
during rollout, including explicit pending until maintenance publishes. This repair does not address the separately measured writer or
unprepared-expiry bottlenecks. No UI, ingestion, provider or infrastructure change.

## Final-runtime results with shared regression load

Both runs bind runtime fingerprint
`browse-b1-v1/ranking-v1/7cd81624f372e770989fa87d9fbbd64eff115a701d147f2798a1cd8ef3bb76a2`.

| Path |1× p50 / p95 / max (s)|2× p50 / p95 / max (s)|Queries1× /2×|
|---|---:|---:|---:|
|Canonical sequential|4.546 /5.500 /5.500|8.904 /9.374 /9.374|163 /273|
|Saved sequential|0.340 /0.466 /0.539|0.260 /0.440 /0.468|44 /44|
|Saved four readers|1.180 /2.575 /2.751|0.947 /1.681 /1.958|44 /44|

Builds took 19.571s /28.720s. All payload comparisons and first/middle/final/empty
page comparisons passed; evidence counts/full-row checksums stayed unchanged.
The concurrent p95 exceeds 1s under this load, so the proposed SLO is not claimed.
[1× raw](loaded-1461.json) / [2× raw](loaded-2922.json).

An [earlier 1× diagnostic](diagnostic-1461.json) predates the extreme-offset guard
and has a different runtime fingerprint. Its sequential p95 was 0.479s and
four-reader p95 1.556s. It is retained as variation, not final-runtime evidence.
[Baseline cProfile](baseline-profile.txt) records the causal reconstruction cost.

## Quieter final-runtime comparison

After local regression/focused suites finished, the same runner and runtime ran
serially without concurrent validation in this workspace. This still is a shared
cloud host, not an isolated production machine. The same parity/checksum gates
passed in both runs.

| Path |1× p50 / p95 / max (s)|2× p50 / p95 / max (s)|Queries1× /2×|
|---|---:|---:|---:|
|Canonical sequential|3.144 /3.921 /3.921|6.325 /7.553 /7.553|163 /273|
|Saved sequential|0.230 /0.261 /0.266|0.309 /0.564 /0.600|44 /44|
|Saved four readers|0.798 /1.268 /1.335|0.835 /1.212 /1.232|44 /44|

Builds took17.500s /21.486s. Four-reader p95 still exceeds1s; production HTTP
performance remains to be measured. [1× raw](quiet-1461.json) /
[2× raw](quiet-2922.json). Loaded outliers above are retained, not replaced by
this quieter comparison.

## Validation

The before-fix regression failed because pursuits invoked the population summary
projection. Final focused PostgreSQL/clock coverage passes **74 tests**, also
independently reproduced; the strengthened complete-tuple/UUID-tie test passes.
Coverage includes canonical full page equality via the GET handler, current
support/Austin identities, whole group ordering/membership, selected/unselected
oversized groups, extreme/empty offsets, Signal-only selection, pending,
canonical write callers, incremental publication, prepared transition and restart.

An earlier full local collection passed **1,823 /1 skipped**, five warnings and
seven subtests, before the final tests/offset guard. Ruff and mypy (104 files)
pass. Migration0023 upgrade/repeat/check/down0022/up/check passes. Initial
parallel focused invocations in the same disposable database collided with the
singleton builder advisory lock (busy/pending); serial final validation and the
independent run in a separate disposable database both pass. Final exact-head CI
is required before merge and is recorded in the PR handoff.

No production deployment, live speedup or real calendar-boundary validation is
claimed by this cloud implementation task. The PC task owns those checks.
