# Customer group page payload profile — 2026-11-13

## Change under review

The original `groups()` CTE assembled `commercial_projects` JSON for all 38,319 groups before the page `LIMIT`. The bounded candidate keeps the existing group counts, scores, ordering, cohort totals, filters, and JSON object fields. It materializes the selected page first, then aggregates those same project payloads for the selected group keys. Detail and child routes keep their existing CTE behavior.

The before source is commit `2336b02ab5f12d88a87ca8b00968050ece047089`, with `backend/src/**/*.py` manifest SHA-256 `8c2e667d62c1d4dc3f7d9f7f2f2c5114f37d76d42075f4402d898b6725e995bb`. The after source is the same HEAD plus the isolated, uncommitted page-payload change, with backend source manifest `1f05af5cecd518ca575aaaf4af4d3606e8c9943f955e6fbe1ec91ba3855599de`. Python 3.11.16, SQLAlchemy 2.0.41, and SoupSieve 4.0 were shared between runs.

## Data and execution context

Both sides use 40,000 synthetic projects and browse rows, 48 synthetic needs/evidence records, the same generation UUID, and matching row/content hashes. The after database is a PostgreSQL template clone of the untouched before database. Since `customer_results.py` participates in the saved-browse policy fingerprint, the clone’s current generation `policy_version` alone was rebound to the candidate source fingerprint. The before database was left unchanged; the metadata adjustment and checks are recorded in [controlled_policy_binding_adjustment.json](controlled_policy_binding_adjustment.json).

Profiles use read-only transactions, `SET LOCAL jit=off`, and `SET LOCAL statement_timeout='15s'` per statement. Page size is 25, sector is `all`, and search is absent. Results are direct backend service calls; the measurements exclude HTTP, authentication, and browser work.

## Evidence

| `canonical_only` | 10-sample p50 before → after | 10-sample p95 before → after | Main SQL `EXPLAIN ANALYZE` before → after |
| --- | ---: | ---: | ---: |
| `false` | 3,154.9 → 2,996.5 ms (-5.0%) | 10,028.4 → 11,637.3 ms (+16.0%) | 2,363.2 → 1,622.9 ms (-31.3%) |
| `true` | 4,610.1 → 4,164.6 ms (-9.7%) | 5,861.9 → 5,399.4 ms (-7.9%) | 1,874.4 → 1,522.4 ms (-18.8%) |

The p95 is nearest-rank over ten samples, so it is the maximum. The false-scope timings are highly variable: their first samples were 10.0 seconds before and 11.6 seconds after. The SQL statement count did not grow: 53 statements on the nine steady false-scope samples, 55 on the first, and 55 for every true-scope sample on both sides. Response byte counts match before and after for each scope.

In the before plan, the `grouped` aggregate emitted 38,319 rows and included the JSON aggregate; it took 1,716 ms (`canonical_only=false`) and 1,725 ms (`true`). In the after plan, the scalar `grouped` aggregate still emits 38,319 rows but took 1,160 ms and 1,112 ms respectively. The new `page_rows` CTE emits 25 rows (or one in the nonempty shortlist case); the page-key payload aggregate emits 25 rows (one in the shortlist case). This shows the expensive project payload construction is restricted to the returned page. Other whole-cohort grouping, window totals, sort work, and temp spills remain.

The same full synthetic response JSON was recursively compared for all four `canonical_only` × `shortlist` combinations. Only `freshness.as_of` fields were ignored; every other field and array order matched. Each shortlist mode returned one group on this synthetic corpus. Hashes and the exact ignored field paths are in [payload_parity.json](payload_parity.json).

## Checks and limits

The new SQL guard, unchanged card/detail contract test, and existing positive shortlist integration test passed: 3 passed in 10.13 seconds. Ruff check and format check passed for the changed source and new test.

The whole-call p50 deltas are modest, and the false-scope p95 worsened in this noisy run. The single-query plan improved on both scope modes, but this synthetic local profile does not establish an end-to-end production latency improvement or SLA. It is evidence that page-scoped JSON aggregation removes avoidable pre-page work while preserving the measured response contract; broader runtime effects need the parent’s remaining gates.

Receipts: [before_timing_10.json](before_timing_10.json), [after_timing_10.json](after_timing_10.json), before/after plan JSON files, [payload_parity.json](payload_parity.json), and the controlled policy-binding receipt above.

## Canonical facet follow-up

A second plan inspection found that `_facets(canonical_only=true)` also built the full `commercial_projects` JSON aggregate even though the facet query only consumes group keys and facet dimensions. In the first candidate plan, the JSON aggregate covered 316 resolved groups, took about 681 ms, and read/wrote 15,938/8,981 temporary blocks. The follow-up omits that unused aggregate only for canonical facet queries. The regular group-page JSON payload and legacy noncanonical facet path are unchanged.

The follow-up ran against a separate template clone, `gl3_mission_rollup_scale_payload_after_facet_20261113_test`; its only data adjustment was the current generation `policy_version`, with all seed records, UUIDs, and content hashes verified equal to the original synthetic snapshot. The receipt is [controlled_policy_binding_adjustment_after_facet.json](controlled_policy_binding_adjustment_after_facet.json). The facet EXPLAIN plan had zero JSON aggregate nodes and returned the same three regions and three stages. Its single-query execution was 1,371.8 ms versus 1,646.3 ms before the facet change. These are individual diagnostic plans, not a latency distribution.

All four response combinations (canonical-only × shortlist) remained equal except `freshness.as_of`; page counts, totals, byte counts, fields, and array order matched. The parity receipt is [payload_parity_after_facet.json](payload_parity_after_facet.json). The new page/facet SQL guard, unchanged route contract test, and existing positive shortlist test passed: 3 passed in 11.06 seconds. Ruff and format checks passed.

The follow-up ten-sample canonical-only whole-call timing did not show an improvement: p50 was 4,849.5 ms versus 4,164.6 ms before the facet change (+16.4%); nearest-rank p95 was 15,016.3 ms versus 5,399.4 ms. The first sample completed as a 15,016.3 ms whole-call measurement; the 15-second per-statement guard was configured, and no statement cancellation was observed. The other nine samples ranged from 3,948 to 5,728 ms. This one-run comparison shows a slower measured distribution, but it does not establish that the facet change caused the difference or an end-to-end production regression. The plan confirms removal of unused JSON work, but no whole-call latency improvement or production SLA is claimed. See [canonical_facets_explain_after_facet.json](canonical_facets_explain_after_facet.json) and [after_facet_canonical_true_timing_10.json](after_facet_canonical_true_timing_10.json).

## Strict freshness parity recheck

The initial parity comparer ignored any field named `as_of`. This was broader than intended. It is now path-aware and ignores only `*.commercial_brief.freshness.as_of`; top-level snapshot clocks and `commercial_intelligence.as_of` are compared exactly. New receipts were generated from the already-saved JSON snapshots without database calls: [strict_freshness_parity.json](strict_freshness_parity.json) and [strict_freshness_parity_after_facet.json](strict_freshness_parity_after_facet.json). All four canonical-only × shortlist combinations pass in both receipts. The only differing allowed paths observed were the card and need commercial-brief freshness clocks, plus the featured project and its need freshness clocks for shortlist responses. The built-in negative control changes only top-level `as_of` and is detected.
