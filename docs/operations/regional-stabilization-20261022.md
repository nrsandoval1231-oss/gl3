# Regional pivot and ingestion stabilization â€” engineering evidence

Status: implemented regional candidate; exact-head CI and independent-review results are recorded in its PR. Base `0f876440a1375c502534cc1dd3c08ceff38c7349`; branch `feat/regional-stabilization-20261022`. No merge or deployment authorized. Production remains outside this local candidate.

## Scope and source inventory

The [canonical PRD](../product/PRD.md) establishes exclusive TX/OK/NM physical-project eligibility without narrowing verticals or intelligence. [Every registered source](../sources/regional-inventory-20261022.md) is classified: 29 definitions, 25 previously enabled, 18 retained enabled (11 Texas + seven national), seven newly disabled outside the territory and four pre-existing disabled entries. Dedicated OK/NM integration coverage is absent. This assignment builds none.

## Preservation and baseline

The old recovery checkout and its uncommitted changes remain intact. A retained PostgreSQL dump was restored into a new loopback-only application database on a separate local instance; tests use a distinct disposable database. Provider keys are blank in the proof environment. Before changes: 18,535 observations, 20,057 immutable evidence versions and 1,661 projects. Raw evidence/identity manifests and runtime receipts stay ignored, outside Git. The forward regional migration preserved every original field/identity in all five checked tables: 20,057 evidence versions, 18,535 observations, 1,661 projects, 1,661 needs and 5,086 change events, with zero missing or changed original rows. It classified 1,598 TX projects eligible and 63 retained out-of-region projects excluded; this retained corpus contains no OK/NM projects, so their acceptance is a fixture-backed behavioral proof rather than a claimed real discovery.

Ten local TestClient requests per endpoint measure routing, SQL and serialization, with authentication bypassed only inside the local measurement harness. These are not public-network or production latencies. Baseline ordinary opportunity path: median 1,669.661 ms, p95 1,795.343 ms and 163 SQL statements. Baseline source health: median 59.7425 ms and 35 SQL statements. Existing saved browsing was already fast after a separately published generation: opportunity median 8.1395 ms, p95 46.901 ms and four SQL statements. Report comparable configuration results separately; an enabled/disabled generation or HTTP 503 is never a speed improvement.

## Matched final performance

The reserved benchmark clone still contains exactly 18,535 observations, 20,057 evidence versions and 1,661 projects. Ten final requests per endpoint returned HTTP 200. Measurements exclude network and login; the SQL counter includes the harness transaction-safety statements.

| Path and mode | Before p50 / p95 | Final p50 / p95 | SQL before â†’ final |
|---|---|---|---|
| Opportunities, ordinary fallback | 1669.661 / 1795.343 ms | 1576.1105 / 1827.586 ms | 163 â†’ 138 |
| Opportunities, existing saved generation | 8.1395 / 46.901 ms | 6.1475 / 19.767 ms | 4 â†’ 4 |
| Source health, ordinary mode | 59.7425 ms p50 | 64.7675 ms p50 | 35 â†’ 14 |
| Customer accounts, saved mode | 3.868 / 9.445 ms | 3.3385 / 7.809 ms | 5 â†’ 5 |

The fallback cohort preflight is now one SQL aggregation rather than repeated evidence hydration per batch. Health uses bulk receipt, job and collection-progress queries. Existing field, cohort, pagination and payload bounds remain enforced; no timeout was increased. The uncached path still costs about 1.6 seconds on this corpus. Its final median improved by about 5.6%, but p95 was slightly higher; health reduced SQL work without improving its ordinary-mode median in this final sample. These measurements do not establish a production latency improvement. The existing saved-publication path keeps expensive aggregation outside the request and is verified locally after an explicit retained-data rebuild; its production flag remains unchanged and rollout is not claimed. Customer-account baseline HTTP 503 without a published generation is not counted as a latency improvement.

## Repairs and actual source execution

All 18 enabled definitions were dispatched through the existing fenced worker against real public sources in the isolated retained clone. These were scoped manual verification jobs, not proof of seven days of scheduled operation. The final replay returned 17 successful jobs and one publisher-freshness failure. Fifteen sources had complete snapshots; NSR remained record-partial, while Austin completed its bounded window but retained incomplete historical coverage. Final health correctly reports Austin degraded with pending backfill. Houston failed the existing publisher-freshness gate. A successful job does not override partial source health. Counts below are fetched / processed into retained records / record-local rejected; accepted into evidence does not mean qualified as a Signal, Prospect or Lead.

| Source | Actual result | Fetched / processed / rejected | Latest publisher date when provided |
|---|---|---|---|
| austin-building-permits | Checkedâ€”No Change | 1 / 1 / 0 | 2026-01-29 |
| construction-dive-news | Checkedâ€”No Change | 0 / 0 / 0 | 2026-10-22 |
| dallas-monthly-permits | Checkedâ€”No Change | 109 / 109 / 0 | UNKNOWN |
| dcd-news | Checkedâ€”No Change | 20 / 20 / 0 | 2026-10-22 |
| el-paso-new-commercial-permits | Checkedâ€”No Change | 67 / 67 / 0 | UNKNOWN |
| federal-register-eis | Checkedâ€”No Change | 66 / 66 / 0 | 2026-10-22 |
| fort-worth-development-permits | Checkedâ€”No Change | 4 / 4 / 0 | UNKNOWN |
| houston-weekly-permits | Publisher stale: failed | UNKNOWN / UNKNOWN / UNKNOWN | UNKNOWN |
| manufacturing-dive-news | Checkedâ€”No Change | 0 / 0 / 0 | 2026-10-22 |
| mjbizdaily-news | Checkedâ€”No Change | 0 / 0 / 0 | 2026-10-22 |
| ogj-exploration-news | Checkedâ€”No Change | 25 / 25 / 0 | 2026-10-19 |
| san-antonio-development-permits | Checkedâ€”No Change | 1 / 1 / 0 | UNKNOWN |
| taylor-development-newsflash | Checkedâ€”No Change | 24 / 24 / 0 | 2026-10-09 |
| texas-rrc-drilling-permits | Checkedâ€”No Change | 1644 / 1644 / 0 | 2026-10-21 |
| texas-rrc-flare-vent-exceptions | Checkedâ€”No Change | 60 / 60 / 0 | UNKNOWN |
| texas-tceq-nsr-pending | Partial | 328 / 327 / 1 | UNKNOWN |
| texas-tceq-temporary-batch-plants | Checkedâ€”No Change | 2 / 2 / 0 | 2026-07-07 |
| utility-dive-news | Checkedâ€”No Change | 0 / 0 / 0 | 2026-10-22 |

The [complete inventory](../sources/regional-inventory-20261022.md) separately records all 29 definitions, previous policy/dated health, new policy and reasons. Per-source attempts, previous successful run, meaningful retained update, latest valid record, retry and collection completeness are retained in the sanitized engineering receipts; unknown publication dates remain unknown. The existing health interface exposes source coverage, cadence, processing status, counts, backlog and failure state. Disabled sources remain historical evidence sources and cannot be re-enabled through an ordinary API override.

- TCEQ now permits only the exact official records host, verified HTTPS path and bounded query form, in addition to existing official listing/summary routes. Public DNS is validated and pinned; every redirect is checked, downloads are bounded, and PDF content type/signature are required. A real records document returned 503 once, then a bounded delayed check retained a 572,150-byte PDF. No invented listing-to-record association was used. NSR retained 327 valid sibling rows while isolating one summary returning 404; this is degraded coverage, not a falsely complete snapshot.

- Houstonâ€™s official index responds but its newest indexed weekly report is September 7, 2026, beyond the existing 30-day freshness bound. A final read-only check found 41 dated report links, none newer; the September 7 workbook still parses correctly into 317 records through September 14. It was not ingested as current evidence. Keep this source enabled, preserve previous evidence and report the publisher blocker. California-specific adapter repair was excluded under the owner mandate.

- Shared acquisition normalization preserves legacy list adapters and accepts structured partial batches. Missing optional extraction-location metadata defaults to its established citation; malformed records, conflicting duplicate identities and document failures receive bounded explicit rejections while unrelated records continue. Partial snapshots cannot reconcile missing records or advance last-success.

- TCEQ document-level rate limits now stop further document requests, retain already valid siblings and publish a durable source cooldown through the actual worker. Numeric/date Retry-After values are bounded; excessive holds require operator review. The integration test proves natural cooldown publication, queued-job exclusion, boundary resumption and idempotent replay. An earlier handoff lost the cooldown during a later health merge; that failure and its corrected end-to-end proof are retained.

- Existing retries distinguish permanent parser/HTTP failures from bounded transient failures; lease fencing, per-record commits and checkpoints remain in the existing worker. Austin uses contiguous count-checked ranges with source-change detection and adaptive subdivision rather than spending its entire eight-job chain on individual dates. The final ordinary eight-job Austin chain prioritized two recent slots per history slot, completed both current-overlap lanes and advanced backfill before stopping at its existing budget. Remaining backfill is partial, with the completion boundary and budget pause exposed; neither a completed bounded window nor a successful job means the entire lane is caught up. No orchestration framework or new integration was added.

After real ingestion, every original evidence version (20,057) and change event (5,086) remains unchanged; every original project/need/observation identity remains present. Across the bounded live checks and Austin continuations, the clone now contains 19,155 observations, 22,275 evidence versions, 1,804 projects/needs and 5,593 change events. The final preservation proof finds no original identity deletions or original evidence/change-event mutations. Existing observations and need state legitimately changed as new versions were ingested (1,591 original observations and 71 original needs in the final comparison); original project fields remain unchanged. Duplicate observation keys and project identity keys both remained zero.

A separate fresh recovery database deliberately exited immediately after the first actual evidence commit. The normal worker reclaimed the expired lease with fence 2 and completed 327 observations, 327 evidence versions, four projects and four needs. A new real-source replay left all four counts unchanged. This proves local interruption/replay behavior, not production recovery.

## Regional and regression validation

The first broad development run returned 2,617 passed, 56 failed and three skipped in 761.22 seconds (plus seven subtests). This was an in-flight candidate, not final acceptance. Failures exposed positive nationwide/unknown-location fixture assumptions, intentional source disablement, updated retry semantics, and a real loss of RSS HTTP validator metadata during normalization. Fixture repairs preserve qualification, provenance, pagination, conflict and resource-bound assertions; RSS is repaired in implementation rather than by changing its validator tests. The final focused PostgreSQL controller gate passed 132 tests in 36.50 seconds; full frozen-head Linux CI and independent review are required for acceptance and are recorded in the PR checks/report. Earlier failed attempts remain retained as development evidence. Parent cloud/launch Finish Contract remains open; local official-source proof cannot establish production readiness.

The local browser regression run passed 191 tests with one skip in the runner-reported 1.7 minutes, including real ephemeral authentication against the local API. Most browser content regressions use mocked API responses; they are UI compatibility proof, not live-source eligibility proof. A separate four-test live acceptance run passed against the actual retained clone: desktop and mobile navigation, preserved Georgia/Chicago ingestion evidence with disabled scheduling and empty active results, plus Texas organization attribution with person-to-project authority explicitly unknown. These four tests used no API mocks or paid providers. A separate four-test live acceptance run passed against the actual retained clone: desktop and mobile navigation, preserved Georgia/Chicago ingestion evidence with disabled scheduling and empty active results, plus Texas organization attribution with person-to-project authority explicitly unknown. These four tests used no API mocks or paid providers. Regional eligibility is tested separately against real PostgreSQL-backed service/API projections. No web component, CSS or approved workflow was changed; generated API contracts expose backend health fields.

## Future territory configuration

`config/sources/registry.v1.json` owns the versioned regional policy and state priority order. Future owner-approved expansion must update its policy version, eligible states and source locks, validate the source definitions and access separately, reclassify retained projects through the canonical classifier in bounded offline batches, reconcile source scheduling with the existing worker, and publish a fresh saved generation. Merely requesting another geography in an API cannot change eligibility. Keep the current generation unavailable until the revised source/projection policy is coherent; never convert missing location evidence into eligibility.


## Eligibility and authority limits

The controller's actual retained-clone API check returned an empty California list, HTTP 404 for an excluded need's direct opportunity detail and HTTP 422 for an oversized limit; all 1,804 persisted project classifications match the current classifier. Dedicated PostgreSQL tests cover TX/OK/NM, CA/GA exclusions, headquarters versus site, unknown/conflicting sites, national evidence attachment, cross-border context, historical retention, replay idempotency and disabled scheduling. Unsupported bare city/state phrases without a comma or ZIP remain held; possible state suffixes can trigger conflict review but cannot establish eligibility. This deliberately favors review over unsupported promotion.

No production database was destructively modified, source integration added, UI redesigned, PR merged or deployment performed. Dedicated OK/NM acquisition is a future owner-scoped coverage task; national evidence remains available now. Real local public-source execution does not verify production credentials, continuous scheduling or live Jev/model routing; paid providers were disabled in this proof environment.

The final stricter conflict detector moved one retained Chicago project from excluded to held because its uppercase street token is also a state abbreviation. Only derived regional metadata was refreshed in the two isolated proof clones; original project fields and evidence stayed unchanged. The final API proof has zero classifier drift.
