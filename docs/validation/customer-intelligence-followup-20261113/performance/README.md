# Customer results performance follow-up

## Outcome

The previous page-card hydration query allowed PostgreSQL to join the complete
40,000-row `all_rows` and `assigned` cohorts before applying the selected page.
The independent plan review found a broad hash join whose row estimate lost the
`project_id`/`need_id` correlation, followed by a nested loop that could rescan
the assigned cohort. The query now materializes the selected group's complete
`(group_key, project_id, company_id, need_id)` key set before looking up
`browse_rows`. It still hydrates every project for each selected account and
matches the original browse row on both project and need IDs.

The new plan removes that unsafe hydration join order, but the measured result
does **not** pass a general latency or payload regression gate. On this one
synthetic 40k clone, matched legacy-path p50 increased 6–13% relative to the
main-file control.
The current canonical-only product default remains a separate route and took
about 2.5–2.6 seconds p50. No timeout was raised and no speedup/SLA is claimed.

## Matched 20-sample results

`paired-profile-20.json` contains 20 timed samples for each source/path/page
size, individual raw timings, SQL call counts, response byte counts and response
hashes. The loop alternates main/candidate legacy order and interleaves the
candidate canonical-only default. All calls pin the same generation from the
same cloned 40k fixture, run read-only with JIT off and a 15-second statement
timeout. This internal `selected_generation` path intentionally bypasses the
current-generation qualification lookup; it measures list query behavior on a
specific already-published synthetic snapshot.

| Page size | Main-file control p50/p95 ms | Candidate legacy p50/p95 ms | Candidate canonical default p50/p95 ms | Median payload bytes: main-file control / candidate legacy / candidate default |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 1,577 / 1,609 | 1,673 / 1,734 | 2,495 / 2,563 | 5,475 / 7,180 / 7,176 |
| 25 | 1,588 / 1,669 | 1,779 / 2,007 | 2,610 / 2,688 | 15,760 / 57,128 / 57,141 |
| 50 | 1,601 / 1,652 | 1,809 / 1,846 | 2,616 / 2,781 | 26,360 / 109,378 / 109,391 |

The candidate legacy response includes the new commercial card fields, so its
larger body is not a like-for-like payload contract. Each full body is
represented by byte count and SHA-256 in the raw samples; body contents are not
stored in the receipt. Median SQL statement counts were 55 for main-file
control/candidate
legacy and 57 for candidate canonical-only. Median SQL execute time was
1,549/1,641/2,462 ms at page 1, 1,560/1,724/2,556 ms at page 25, and
1,575/1,723/2,545 ms at page 50 (main-file control / candidate legacy / candidate
default). These sums include all list SQL; page-size growth does not remove the
full-cohort facet/contact work on canonical reads.

`main_legacy` in this paired receipt is a **main-file control**, not a full main
checkout execution: the c5 `customer_results.py` file was loaded by module spec
inside the candidate package environment, so its imported `gridlens` dependencies
resolve from the candidate source tree. The raw timing and payload samples are
unchanged; use the separate `main-c5-legacy-phases.json` for the earlier
full-main-source measurements, which were not interleaved with candidate runs.
The historical `account_total` sample field is null because the original runner
read `totals.account_total` instead of `totals.accounts`; those nulls are not
account-count evidence. The runner now reads the correct key, without rewriting
historical samples.

## Page hydration plans

`candidate-canonical-page{1,25,50}-actual-retry.json` are one-execution
`EXPLAIN ANALYZE BUFFERS` plans for the page SQL; the paired distribution above
is the timing result. Plan-root `Actual Total Time` values were 1,107.158 /
1,107.580 / 1,143.558 ms (full-query `Execution Time`: 1,115.508 / 1,116.287 /
1,152.341 ms), returning 1 / 25 / 50 rows. Temporary reads/writes were 130,648 / 17,905 blocks
at limit 1 and 131,541 / 18,799 blocks at limits 25 and 50. The main/facet and
contact SQL still contribute material time to the full group response.

The JSON receipt preserves the byte-exact captured SQL string. The adjacent
`.sql` file is a readable export with trailing horizontal whitespace removed;
`query_sha256` hashes the raw captured string, not that normalized export.
The historical failed-variant receipt also now contains a hash-verified
reconstruction in `captured_sql`; its plan/timing fields were left unchanged.

The integration test runs actual plans at limits 1, 25 and 50 for both
`canonical_only` values, verifies the materialization boundaries and actual
page/project-key cardinalities, and compares the narrow projection with the
full-width reference. A separate fixture assigns 30 sibling projects with
distinct need IDs to one account, selects that account on a one-group page and
asserts every project/need fact survives hydration. The shortlist parity test
also compares narrow and full-width responses across all four
`canonical_only` × `shortlist` combinations. Full detail and privacy assertions
remain in the existing customer-intelligence tests.

## Baseline and limitations

`baseline-canonical-phases.json` shows the pre-fix candidate canonical path at
about 2.54–2.58 seconds p50; its SQL execution dominated Python card projection.
The saved baseline top-SQL receipts attribute significant time to the main page
query, canonical facets, and account-contact project query. The CTE/page change
addresses a distinct planner hazard in card hydration; it does not remove those
other full-cohort operations. The timeout experiments and their nonexecuting
plans are preserved as separate receipts and are not used to infer actual row
counts.

The paired run used a local PostgreSQL 18.6 disposable clone only. Host and DB
container snapshots immediately before and after are in
`paired-window-environment-before.json` and
`paired-window-environment-after.json`. They show DB container memory at about
454–456 MiB; host process snapshots are best-effort and do not characterize a
dedicated benchmark machine. No production/retained database, paid provider,
deployment or external call was used.

## Checks

- `uv run --project backend ruff check` on the owned source, integration tests
  and performance scripts: passed.
- Focused PostgreSQL integration set: 14 passed before the additional 30-sibling
  case; page payload/planner file then passed 3/3. The combined final command was
  not rerun after that one test was added.
- No full repository CI or independent final review is claimed here.
