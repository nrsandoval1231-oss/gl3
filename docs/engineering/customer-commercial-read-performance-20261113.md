# Customer commercial read performance reconciliation

## Existing work reused

During implementation we identified external repository PR197, **open and unmerged** when inspected on
2026-11-13: [account query performance](https://github.com/nrsandoval1231-oss/gl3/pull/197),
exact head `30ec16cfdb0d65bce6ef21c47ea46d2a0dd02b6c`.
Its materialized page-group contact selection, per-asset project-ID aggregation and
transaction-local JIT policy were reviewed and reconciled into this candidate. The branch
was fetched for inspection; no blind cherry-pick, merge, deployment or production read occurred.
Its reported 40,000-project measurements are the other PR's historical evidence, not a new
measurement of this candidate or proof of the live site's cause.

Our contact path retains the existing exact primary-company filter, methods **or** verified
named-professional selection, current native attribution/suppression guard and deterministic
ranking. Only page-selected resolved groups enter `contact_assigned AS MATERIALIZED`.
Per-asset project IDs are aggregated once rather than running the correlated all-rows scan
for every candidate. API consistent reads retain REPEATABLE READ and set PostgreSQL
`SET LOCAL jit=off`; rollback/commit restores the connection setting. No global or retained
PostgreSQL configuration is changed.

## Commercial projection repair

The first integrated candidate added a second full grouped CTE, a recent-event read and
history-privacy reads even for empty intelligence. CI exposed violations of the original
four-core-query and one-grouped-query gates. Those tests remain unchanged.

`grouped_need_counts` now aggregates distinct per-project frozen facts, priority, company
identity and developments into `commercial_projects`. Existing group/header/open SELECTs
carry this payload. `_commercial_by_groups` consumes it without another cohort query.

Generation build reuses its existing material-change context query to freeze up to three
recent capacity/timing events per project, preserving original before/after states, causal
source references and timestamps. Request rendering does not scan ChangeEvent. Empty
fact/development content requires no contact-history queries; real claims still pass the
existing batch history privacy projection before publication.

Cards retain supported totals, type/qualifier/completeness/coverage, precise display dates,
scenario scalars, priority/confidence, concise developments and next action. Detail-only raw
claims, quotes, source bodies, old/new states, engineering project arrays and calculation
inputs remain in account detail. Cards expose `source_count` and `details_available`.
This is progressive disclosure, not removal of source evidence.

## Candidate checks and limits

- Three unchanged representative-scale group-open tests, the unchanged cohort query-budget
  test, the actual native-positive/current-suppression journey, five commercial projection
  tests and transaction-local JIT test: **11 passed**, one existing test-client deprecation
  warning, **48.73 seconds**.
- Independent old correlated SQL versus reconciled candidate SQL on the same persisted
  method and named-professional candidates produces the same public JSON after removing
  only read-time `freshness.as_of`. The test explicitly labels its native-authorization seam;
  it is not a native-coverage claim. Together with the JIT restoration test: **2 passed**,
  **5.02 seconds**.
- Broader affected account/material-change/runtime preservation: **63 passed**, **84.50 seconds**.
- Five final projection tests: **5 passed**, **18.06 seconds**. A 62-project account card/page
  stays below 20,000 serialized bytes while detail retains all 62 project scenario states.
  Detail event states/evidence survive and contact tokens remain redacted.
- An earlier moving-source run had the three scale and query-budget tests pass, but failed
  two then-obsolete *new* whole-object/card-raw-array assertions. Those failures remain in
  its receipt. They were replaced by display/identity equivalence plus full-detail preservation,
  not by changes to the legacy performance gates.

The previous combined scale/query/projection run took 230.25 seconds, including a grouped
query observed CPU-active for over two minutes with no lock wait. The reconciled run above
contains additional tests and shared-machine load differed; comparing these suite durations
is diagnostic, not a controlled p50/p95 benchmark. Fresh source-bound benchmark artifacts,
full CI and independent acceptance remain separate gates. No production SLA or readiness
follows from these scoped checks, and the independently reported real-source extraction
coverage limitations remain unresolved by this performance work.
