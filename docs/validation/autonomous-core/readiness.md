# Autonomous core — integration validation and release readiness

Status: implementation and regression acceptance passed for source candidate `24f3985d8b6f3c71d4fb415d4abcea8836d04694`. **Production and live-commercial acceptance remain open.** No deployment occurred. Delivery: [draft PR #126](https://github.com/nrsandoval1231-oss/gl3/pull/126).

## Scope and authority

The implementation starts at PR #124 (`edd409b13042d24d5d8ac7919411dc4b6f3145a5`). The [Autonomous Intelligence Canon](../../product/AUTONOMOUS_INTELLIGENCE_CANON.md) controls the reconciled [PRD](../../product/PRD.md), [architecture](../../architecture/autonomous-intelligence.md), and [path-level contradiction/retirement inventory](../../architecture/autonomous-migration-inventory.md). Original governing records remain in the lossless governance archive.

The changes preserve PostgreSQL, existing ingestion adapters, physical-project identity, source/version attribution, historical facts/corrections, deterministic qualification and residual-gap arithmetic, TX/OK/NM eligibility, the 300 kW floor, authentication, and the seven-color G/L identity. Upstream PR #125 (`d75a856`) landed during implementation and is integrated here. Its additive models and migrations 0042–0044 are preserved unchanged. This surgery adds no further migration and changes no production data or deployed environment.

Sol 6.1/high coordination, Luna 6/low builders and Astra 6/high independent review actually ran. Builders used isolated worktrees and scoped ownership; substantial integrated findings were repaired and independently read back. Aggregate token counts are not claimed.

## Implementation delivered

- Removed manual call/fact/status/correction interfaces, draft state, client mutations, public manual and research-trigger APIs, manual-only correction writers, and unused request contracts. Mounted public mutations are limited to login/logout. Historical records, corrections and read-side evidence remain.
- Added authenticated typed search across projects, companies, contacts and opportunity intelligence. Unpublished projections explicitly report pending qualification; stored raw tiers cannot substitute for current qualification.
- Added read-only Research and mobile search/detail behavior. Diagnostics are secondary account navigation, outside the primary commercial workflow.
- Enabled bounded unpaid opportunity/contact planning in defaults and example configurations. Paid/model dispatch retains independent provider, licensing, budget and validation gates.
- Added replica-safe planner coordination, failure containment, publisher Retry-After preservation, fair research category selection, contact retry/freshness repairs, current-evidence ranking and owner-first presentation.
- Isolated accumulated histories and oversized evidence before machine hydration so unrelated complete work groups continue. Historical rows and HTTP safety bounds are preserved.
- Preserved upstream immutable workbook staging, unverified imported assertions, source-backed company graph reads, exact-scope power projections and incremental enrichment. Removed its manual contact/relationship correction writers.
- Kept source attribution separate from deliverability and purchasing authority. Unknown demand remains unknown; research-priority heuristics are not evidence confidence. No contact, MW, timing, probability or commercial-success claim is manufactured.

## Final validation

The [machine-readable receipt](verification.json) records the tested source, partition results, artifact hashes and scope trees. Subsequent delivery commits contain documentation/screenshots only; executable source and tests remain identical to the tested candidate.

| Check | Result |
|---|---|
| Complete local backend suite | All 3,049 collected tests ran across four isolated PostgreSQL database pairs: **3,048 passed, one skipped, seven subtests passed**; every partition exited 0. Longest partition: 801.35 seconds. |
| Independent GitHub CI | [Run 40255316876](https://github.com/nrsandoval1231-oss/gl3/actions/runs/40255316876) passed all backend, web and brand jobs at the same source commit. Serial backend: **3,048 passed, one skipped** in 512.36 seconds; Chromium: **120 passed**. |
| Local Chromium regression suite | **120 passed** in 3.9 minutes, including real authentication, mobile navigation, source/unknown states and graph/import presentation. |
| Separate native Chrome login suite | **Eight passed** in 19.7 seconds using official Google Chrome 156.0.8078.47. The default installer required unavailable root access; the official package was unpacked in the workspace and the existing login configuration used an executable-path override. No production or application configuration changed. |
| Static/build/contracts | Ruff lint and format passed (365 files); mypy passed (169 source files); frontend typecheck/build passed; regenerated OpenAPI/types have zero drift. |
| Schema/data integrity | Fresh upgrade, repeated upgrade and Alembic drift check passed at `0044_enrichment_planner_cursor`. A separate populated 0041→0044 upgrade preserved the seeded Source/Observation/Evidence identity, content hash and provenance. Migration and persistence files are byte-identical to upstream main. |
| Dependency/brand/docs | Backend, web and brand dependency audits report zero known vulnerabilities. Brand validation passed 216 assets and eight semantic AA pairs. Maintained documentation link/anchor validation passed. |
| Independent architectural review | All identified blocking code findings corrected and read back; see the [review ledger](independent-review.md). Independent focused checks: 79 earlier tests and 48 assembled-source tests passed; these are not added to the full-suite count. |

The single backend skip is `tests/unit/test_nc_commerce.py:206`: its optional local access-probe artifact is absent. Four separately configured live-acceptance browser cases require retained real-source corpus records, including out-of-region permits and specific Texas data-center records, which the available local database does not contain. Those four checks are **blocked by their data preconditions**, not reported as passes and not filled with synthetic records. The passing mobile [screenshots](screenshots/README.md) use disclosed synthetic browser fixtures; they do not prove live intelligence yield.

Earlier failures are retained rather than recast as successful checks. The first complete gate at `ce2b062` failed (2,882 passed, 87 failed, one skipped, one setup error); its [receipt](initial-integrated-gate.json) identifies the failures subsequently repaired. The 8df3231 run was deliberately interrupted to incorporate the independently found refresh-retry correction and is not a passing gate. An ambiguous browser test selector was repaired before the final complete passing run. Deprecation and fixture isolation warnings remain visible in test logs; no failures are suppressed.

## Contact coverage and live acquisition limits

No current production contact-coverage measurement was performed. The retained October 25 [v12 benchmark](../contact-intelligence/firecrawl-v12-results.json) is **historical**, not a result of this candidate: 20 companies, four with usable source-published company methods (20%), three named relevant professionals across two companies, and zero direct-buyer methods. Benchmark CSVs are not imported as fresh verified contacts. Upstream workbook staging and its benchmark remain separately dated evidence. Apollo access/licensing and current Firecrawl account readiness were not established; no paid engine/provider requests were made during these checks.

A bounded ordinary-worker Austin acquisition in a fresh local database persisted 171 observations/evidence records and six project/power-need records, with no failed or pending interpretations in that batch. Source coverage remained partial, with durable continuation work queued. The receipt tool then failed serializing UUIDs in change history; that defect was repaired and its four unit tests passed. This proves bounded real-source ingestion occurred, **not** complete coverage, idempotent live replay, autonomous contact yield or a qualified Lead.

The ordinary TCEQ pending-permit worker check failed with a visible network error. The exact official page returned HTTP 200 through the workspace's required proxy; the adapter intentionally uses direct DNS-pinned transport, which is incompatible with this proxy-only execution environment. SSRF/TLS protections were not weakened. Neither the failed initial job nor its replay is reported as successful.

## Data safety, recovery and deployment gate

No table/column drops, historical rewrites, production backfills, production migrations, merges into main or deployments occurred. Existing append-only history remains readable. Schema retirement is deferred: retaining historical tables does not retain public manual workflows. Relative to incorporated upstream main, this surgery needs no additional migration. An installation still at 0041 must apply the retained upstream additive migrations 0042–0044 with its existing backup/recovery procedure; do not downgrade them destructively or discard imported rows.

Worker rollback requires checkpoint/status compatibility verification. An older queue must honor the new `retry_after_unrepresentable` hold before resuming affected sources. Retain the current worker or backport that hold behavior if the prior worker does not recognize it; never silently release publisher retry holds.

Before production release, validate the exact release images/configuration, production backup/restore, real source network compatibility, worker/browse heartbeat and retry health, provider permissions/cost limits, and source/identity/contact coverage. Observe unattended operation rather than inferring it from local tests. Current direct-buyer yield, full live source coverage, seven consecutive daily cycles and a reviewed real Lead remain unverified. Deployment is a separate acceptance gate.
