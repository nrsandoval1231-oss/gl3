# Account list read performance, 2026-11-12

Reported symptom: project loading is slow on the live site. This note records a **local, synthetic** measurement and
fix. It does not describe production: no retained or production data was read, and whether the live site shows the
same cause is unverified.

## Measurement

Disposable PostgreSQL 16, schema 0056, synthetic corpus from `web/acceptance/rollup-scale/seed.py` (`--rows`),
`gridlens.api.app` served locally with provider keys absent. Single user, warm cache, `curl` wall time.

| Route (40,000 projects) | Before | After query fix | After query fix + JIT off |
|---|---:|---:|---:|
| `GET /api/opportunities/groups?limit=25` | about 115-120 s | about 6 s | about 1.3 s |
| `.../groups/{id}/open` | 3.3 s | 3.3 s | 0.74 s |
| `.../groups/{id}/projects` | not measured | 2.9 s | 0.61 s |

At 2,098 projects the same route answers in about 0.14 s, so the cost is super-linear (19x rows, about 800x time).

## Cause

1. `customer_results._account_contact_projects` joined `assigned`, `all_rows` and `browse_rows` with an
   `EXISTS (jsonb_array_elements(...))` filter on `jsonb_typeof(compact->'contact_actions')`. PostgreSQL cannot estimate
   that expression and assumed about 0.5% of rows (200), so it expected the join to return 1 row and chose a nested
   loop that re-scanned the 40,000-row `assigned` CTE once per candidate row (`EXPLAIN ANALYZE`: about 2.5 million join
   rejections, 1.6 billion filter checks, 122 s). Table statistics do not help because the expression is opaque.
2. Each candidate row also carried a correlated `ARRAY(SELECT ... FROM all_rows ...)` for its asset's project list.
3. PostgreSQL JIT compiled these large CTE queries on every request, about 2.5 s each (`JIT: Timing ... Total 2480 ms`).

## Change

- The query now selects the page's resolved groups first in a `MATERIALIZED` CTE, and aggregates the per-asset project
  list once (`array_agg(DISTINCT project_id ORDER BY project_id)`, identical to the removed subquery).
- `_begin_consistent_read` sets `SET LOCAL jit = off` for the transaction only.
- Equivalence: the `groups()` payload for the same seed is identical before and after except the wall-clock
  `freshness.as_of` values (compared as JSON). Existing customer-result tests pass unmodified.

## Not done

Four other queries repeat the correlated `ARRAY(SELECT ... all_rows ...)` pattern (`customer_results.py`, group open,
group projects and related paths). They are fast enough after JIT-off (under 1 s at 40k) and were left unchanged to
keep this change to the measured cause. Re-measure before treating them as solved at larger scale.

## Limits

Synthetic data, one machine, one user, no network, no concurrent ingestion, no production configuration. The synthetic
generation is built once; the planner's behaviour on production statistics and row shapes is unverified. The JIT cost
applies only if production runs with `jit` on (the PostgreSQL default); check `SHOW jit` there. Deployment of any
change is a separate decision.
