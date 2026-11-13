# Read-only integrated preflight observation — 2026-11-13

Candidate: `1de298af`. No source edits, test cancellation, competing database tests,
backend signals or operational database access occurred during this diagnosis.

## Final result

`/workspace/task-runtime/backend-fix-integrated.log` completed:
**251 passed, 3 warnings in 654.02 seconds; EXIT_CODE=0.**
The warnings are the existing test-client deprecation and existing-connection
isolation-option warnings in both cross-boundary summary variants. The run did not hang.

## Exact case and source identity

Read-only collection of the same selected test paths/options produced 251 nodes:
224 and 225 are
`test_summary_batches_preserve_cross_boundary_case_siblings_and_compact_history[False]`
and `[True]` in `test_power_need_briefs.py`.
Collection receipt: `/workspace/task-runtime/backend-fix-readonly-collection.log`.

This existing adversarial case creates 129 needs/projects, 260 extra observations,
64 historical evidence revisions, 50 fact/status records and a largest need with
261 linked/lifecycle records. It repeatedly executes summary, public, commercial
and full projections, including tracemalloc and query/memory/equality assertions.
It was introduced in `faebdeee` (Bound browse summaries with canonical streaming reducers).
The repair does not change this case or its assertions.

The active `WITH evidence_scopes AS MATERIALIZED` query originates in
`api.app._preflight_streamed_evidence_text`, whose materialization boundary dates
to `61bfb9734f4873ed8cc47cc854798ab3278d05a7` (2026-11-05).
Exact function text was compared with audited main `bf75d327`:

| Function | Identical to main | SHA256 |
| --- | --- | --- |
| `_preflight_streamed_evidence_text` | yes | `c0f745568af3835ab5a3171f3ea36fc5bb3cc966147f0b2a277cb68e46d031be` |
| `_commercial_triage_page` | yes | `46d63c5bfecebf7063d9f2fce7a9a72497d6976fb9b7769339dea7ae8b4383c7` |
| `_commercial_current_triage_page` | yes | `0ec44fbdfb407d1a3ad1dd46c96734d25d1d65f2c68239b37727b7eb111620e5` |

The entire candidate `app.py` diff versus that main is the bounded
`_begin_consistent_read` transaction-local JIT change. The observed active query
was not the repaired customer-group/contact aggregate or ChangeEvent projection.

## Observation limits

PG backend 23132 was observed active with no lock wait. Successive observations
had changing query starts/query shapes, demonstrating progress through preflight
statements; they do not establish a single continuously stuck statement.
An early pg_stat/pg_class estimate of one live row was lagging during the test
transaction. It is not actual corpus size and was discarded after collection
identified the bulk test. The initial inference that the first eight brief tests
were running was likewise corrected by the exact collection map.

A representative fake-50-UUID preflight query was inspected using
`EXPLAIN (FORMAT JSON, ANALYZE FALSE)` only, without executing its data query.
Its estimated cost was 60.09 and it had no JIT section. This was not the active
query's actual bindings or plan and cannot identify the active query's cause.
Artifact: `/workspace/task-runtime/backend-fix-preflight-representative-plan.json`.

Conclusion: this run exercised a pre-existing full-module bulk/streaming path and
finished green. The relevant SQL and triage functions are unchanged. These facts
provide no direct evidence that the repaired customer SQL caused the delay, but
they also do not prove its precise CPU cause, a before/after timing guarantee,
or absence of every indirect effect. No broader preflight repair is claimed.
