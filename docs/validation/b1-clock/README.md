# Prepared clock transitions: PostgreSQL evidence

Base PR77 introduced immutable canonical browse generations and atomic ordinary
operator updates. Its forced-expiry fixture windows were 12–22 seconds of explicit
pending. This follow-on prepares the next canonical clock interval ahead of time;
read selection changes only in the interval `[valid_from, valid_until)`, bound to
unchanged inputs and policy. Broad/source writes remain full-build pending cases.

## Method and limits

These are disposable **synthetic** dated Signal histories (roughly 1 KB abstracts),
not a production copy: 1,461 projects/15,874 evidence and 2,922/31,748 at 2× capacity,
one active need per project. Strong focused fixtures separately prove source-bound
Prospect→Lead at accepted-fact start and Lead→Prospect at exact expiry, alongside
rank/filter/group parity and multiple date clocks.

The benchmark first simulates an unprepared expiry and times its full retained
rebuild. It restores the valid original generation, prepares the exact next real
calendar/fact boundary ahead of time, and observes ordinary reads while preparing.
It then simulates the reader clock at the prepared boundary, without promoting the
pointer or calling maintenance, and measures 60 sequential/60 calls with 4 readers.
A fresh connection pool measures the first boundary read; PostgreSQL cache stays
warm. It finally commits three ordinary scoped writes during another preparation and
verifies rejection, fresh current reads, explicit pending at the invalidated
future boundary, and successful preparation after writes stop.

Timing covers server functions, connection/pool acquisition and transactions;
HTTP, authentication, network and client rendering are excluded. Driver transaction
setup is excluded from instrumented SQL statement counts. CPU/connection waits are
not separately isolated. The host was shared with regression validation; timings
and earlier diagnostic variation do not establish production SLOs. Preparation
really executes before its deadline; boundary time is simulated in the disposable
benchmark only. No system/production clock is changed.

## Final matching-runtime results

| Measurement |1× |2× |
|---|---:|---:|
|Initial full build (s)|25.156|34.515|
|Unprepared expiry pending (s)|16.604|23.331|
|Ahead-of-time preparation (s)|15.141|25.388|
|Fresh-pool first boundary read (s)|0.012|0.014|
|Invalidated preparation work (s)|14.679|23.918|
|Quiet retry preparation (s)|12.439|22.884|

| Read path |1× p50 / p95 / max (s)|2× p50 / p95 / max (s)|SQL statements|
|---|---:|---:|---:|
|During preparation|0.013 / 0.065 / 0.145|0.010 / 0.062 / 0.244|2|
|Prepared boundary, sequential|0.006 / 0.010 / 0.011|0.003 / 0.004 / 0.007|2|
|Prepared boundary,4 readers|0.016 / 0.158 / 0.176|0.010 / 0.025 / 0.040|2|

All 421 / 743 background reads during preparation succeeded. The prepared
boundary reads needed no builder, promotion or maintenance poll. All measured
saved ranked pages used 2 statements. Evidence counts/full-row checksums matched
before/after both runs. Both artifacts bind runtime fingerprint
`browse-b1-v1/ranking-v1/5ebca23233ac5da14c624ca639b6a1c5e94a551b5f212832368c1278ca36c316`.

[1× raw result](fixture-1461.json), [2× raw result](fixture-2922.json).
Earlier candidate diagnostics remain [1×](diagnostic-1461.json) and
[2×](diagnostic-2922.json); the latter recorded 40.922s unprepared pending under
shared regression load. They predate the future-base clock-skew guard, idle-loop
gate and deterministic metadata tie break. They are not the final runtime runs.
PR77's earlier 71.5s contended build and 2.48s detail outlier remain in its report.

## Safety and availability boundaries

- Preparation never grants future qualification early. Readers fence both ends of
  the interval, input revision and complete local-code policy fingerprint.
- A context-local evaluation instant drives canonical read evaluators only.
  Confirmation/authentication/lease/publication clocks remain real. Normal callers
  retain their original clock defaults and timezones.
- Relevant committed writes invalidate preparation transactionally. Rollback
  preserves it. A write at the boundary first promotes a now-effective prepared
  base; an application clock still before valid_from refuses that base safely.
- Any concurrent write rejects future publication. Both measured races with three writes
  returned `superseded`; after writes stop, preparation succeeds. Continued writes
  can miss readiness and leave pending after expiry.
- Missing/late/failed/policy-mismatched preparation and intervals shorter than build
  time retain explicit pending/full rebuilding. This is conditional availability
  improvement. Broad source/full invalidations are not eliminated.
- Both pointers survive pruning and restarts. Rollback refuses future generations.
  No canonical evidence/history is deleted. No collection/research/paid provider
  calls or scheduler activation are introduced.

## Verification

Baseline reproduction confirms 503 at an unprepared deadline. The final focused
PostgreSQL+clock suite passes **68 tests**, independently reproduced. Tests include
real source-bound fixture qualification changes at start/end, SQL fact-loader
cutovers, policy mismatches, failure isolation, rollback, repeated writes,
exact-boundary edits, next-interval preparation, missed maintenance, restart,
pruning, clock skew, context nesting/exception/thread isolation, UTC/Chicago/host
calendar boundaries, DST and year change.

Full local regression passed **1,817 / 1 skipped** before the final three focused cases;
all 68 final focused cases pass. Canonical targeted regressions passed 179 tests.
Ruff, mypy (104 source files), migration 0022 upgrade/repeat/downgrade 0021/upgrade and
schema drift checks pass. Independent review has no correctness blocker. Exact-head
CI remains the merge gate. No production performance or deployment is claimed;
existing PC thread owns rollout and live QA after connectivity/access gates.
