# Final matched performance measurements

**Historical snapshot:** these measurements cover the earlier candidate at `7f11ef12`. The
November 13 recheck covers optimized commit `e653c78f` after the bounded ingestion query fix
and should be used for current performance review: [recheck results](recheck-20261113/README.md).
The receipts below are retained as evidence for the earlier candidate and are not a production
performance guarantee.

## Scope and status

These measurements compare exact baseline `5ee2f30c2b1c9998063db1c6468d1f4e65f7ac2d` with
the source-frozen candidate at commit `7f11ef12f5136c07d8cd4e99839a53cdd59d3f92`. The
candidate source manifest was `f5b8e1b9b6dec0f9a5d041bddac15e0e1e6a5fe7c71d5ea6b99620c77a394fe3`
before and after both measurements. The baseline backend source manifest was
`ccab75506a8587426ec983b3339b89066493fb5c02cd495f6346790592a8a4ec` before and after its runs.

The baseline uses an isolated detached worktree at the exact commit. Both checkouts run in the
same local `uv` environment. The backend pins `beautifulsoup4==4.13.4` in both trees; the
runtime package versions are recorded in per-run metadata. PostgreSQL is local 16.2 on
`127.0.0.1:55439`. No production or retained database is accessed, and no provider request is
made. Ingestion runs the existing fixture-backed write benchmark in a disposable database;
rollup seeding writes only synthetic rows to a new disposable database, then the measured
service reads use read-only transactions.

## Baseline receipts

Ingestion uses 5,000 seeded projects and 300 synthetic Texas RRC permit records per phase.
The adapter retrieval is fixture-monkeypatched. Results are 300 new records in the first
phase, 300 unchanged on replay, then 15 changed and 285 unchanged; each phase uses five
commits. Wall time and SQL statements are:

| Phase | Seconds | SQL statements |
| --- | ---: | ---: |
| All new | 34.262 | 27,067 |
| Unchanged replay | 2.985 | 3,927 |
| 5% changed | 3.943 | 4,887 |

The candidate ran the same synthetic phases: 300 new records in 43.259 seconds / 28,267 SQL
statements; unchanged replay in 4.180 seconds / 3,927 statements; and 15 changes in a 300-record
replay in 5.372 seconds / 4,947 statements. Both sides used five commits per phase and ended at
5,300 projects / 300 observations. Result counts match. Candidate acquisition metadata has a
different current collection-window day (November 13 versus November 12 for baseline); both are
synthetic `PARTIAL` fixture runs, not completed live-source cycles.

The unchanged replay count is equal, while all-new adds 1,200 statements (600 of which are
`FROM projects` scans, or two extra scans per new record) and the 5% changed phase adds 60
statements (30 `FROM projects` scans, or two per changed record). Explicit lock-statement counts
and commit counts are unchanged. This is a measurable write-path cost associated with new and
changed records; the benchmark does not identify the responsible application call site. A
bounded follow-up is to trace those additional project scans on new/changed ingestion and batch
the added lookup if it is repeated per record. Timings are single runs and should be treated as
diagnostic rather than an SLA.

The final database has 5,300 projects and 300 observations. Source-run metadata reports the
bounded synthetic collection as `PARTIAL`; it is not evidence of a completed live source cycle.

The customer rollup corpus contains 40,000 canonical projects, 48 needs, 48 evidence rows and
38,319 customer groups. The 48 underlying need/evidence rows are intentional in this frozen
presentation-scale fixture; it does not represent 40,000 researched customer claims.
Ten direct service samples per page size use read-only transactions, a 15-second statement
timeout and transaction-local `jit=off`, matching the request path. Setup and JIT configuration
are outside the timer; SQL counts reset immediately before each service call.

| Page size | p50 ms | p95 ms | SQL statements per sample | Compact JSON bytes |
| ---: | ---: | ---: | --- | ---: |
| 1 | 2,475.7 | 6,980.8 | 55 on first call; then 53 | 5,475 |
| 25 | 2,436.7 | 2,691.3 | 53 | 15,760 |
| 50 | 3,554.4 | 4,542.4 | 53 | 26,360 |

Candidate results for the same corpus and transaction settings:

| Page size | p50 ms | p95 ms | SQL statements per sample | Compact JSON bytes |
| ---: | ---: | ---: | --- | ---: |
| 1 | 3,041.1 | 8,368.6 | 55 on first call; then 53 | 7,180 |
| 25 | 3,253.0 | 10,450.4 | 53 | 57,128 |
| 50 | 3,142.2 | 7,217.2 | 53 | 109,378 |

The page-25 p50 is 1.33x baseline; its nearest-rank p95 is 3.88x, driven by the maximum of ten
samples and therefore unstable. Page-25 compact JSON is 3.62x baseline. The query count remains
flat at 53 for both page sizes 25 and 50, so these measurements show no page-size query growth
for this fixture and request shape. All provider-accounting tables contain zero rows on both
sides.

The read-only field-size profile attributes 40,693 summed UTF-8 bytes of the candidate page-25
items to the new `commercial_intelligence` card field; the largest included subfields are
`commissioning` (20,310 bytes), `capacity` (3,403), `limitations` (3,636), and
`recommended_next_action` (2,425). The baseline has no `commercial_intelligence` field in these
cards. The pre-existing `account_contact_project` field is 4,557 bytes on both sides. The field
breakdown receipts are [baseline](rollup-fields-base.json) and [candidate](rollup-fields-candidate.json).
This isolates the payload growth to the new summary projection; it does not establish that the
new customer facts are unnecessary. If response-size or latency budgets require reduction, a
bounded option is to compact repeated long explanations in the card while retaining their full
detail view.

The flat 53-statement counts at page sizes 25 and 50 show no page-size query growth for this
fixture. They do not prove absence of N+1 behavior for every account/contact shape. All three
provider-accounting tables contain zero rows. The earlier JIT-on baseline run is retained as
`rollup-base.json` for diagnostics only; the matched comparison uses `rollup-fixed-base.json`
and the corresponding candidate receipt so JIT contexts stay aligned.

## Candidate and comparison

Per-run receipts record source `HEAD`, a SHA-256 manifest over Python source files under
`backend/src` (including untracked modules), database corpus counts, harness and fixture hashes,
command timings and sanitized logs. Before/after fingerprints match for every run.
[`summary.json`](summary.json) compares both candidate lanes to the exact baseline and confirms
rollup corpus and account totals match.

The recorded commands, from `/workspace/gl3-commercial`, were:

```bash
source /workspace/task-runtime/security-env.sh
uv run --no-sync --project backend python docs/validation/customer-intelligence-20261112/final-performance/run_matched.py ingestion-candidate
uv run --no-sync --project backend python docs/validation/customer-intelligence-20261112/final-performance/run_matched.py rollup-candidate
python docs/validation/customer-intelligence-20261112/final-performance/summarize.py
uv run --no-sync --project backend python docs/validation/customer-intelligence-20261112/final-performance/measure_field_bytes.py --source-root /workspace/gl3-mission-baseline-5ee2f30c --output docs/validation/customer-intelligence-20261112/final-performance/rollup-fields-base.json --database gl3_mission_rollup_scale_base_test --limit 25
uv run --no-sync --project backend python docs/validation/customer-intelligence-20261112/final-performance/measure_field_bytes.py --source-root /workspace/gl3-commercial --output docs/validation/customer-intelligence-20261112/final-performance/rollup-fields-candidate.json --database gl3_mission_rollup_scale_candidate_test --limit 25
```

The baseline was measured with the same runner's `ingestion-base`, `rollup-base`, and
`rollup-fixed-base` lanes against the isolated exact-commit worktree. `rollup-fixed-base`
repeated the read after adding request-equivalent JIT-off context to the common measurement
harness. The recorded runner refuses receipt overwrites and rollup database reuse; a future
repeat needs fresh task-owned test-database and output names.

The rollup latency and payload figures are direct local service measurements. They exclude
HTTP, authentication, network transport and browser rendering. Single-run p95s and shared
machine timings are diagnostic; they do not establish a production SLA.
