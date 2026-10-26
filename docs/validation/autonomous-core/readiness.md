# Autonomous core — integration validation and release readiness

Status: integration validation in progress. This report is not production acceptance or deployment authorization.

## Scope and authority

The implementation starts at PR #124 (`edd409b13042d24d5d8ac7919411dc4b6f3145a5`). The [Autonomous Intelligence Canon](../../product/AUTONOMOUS_INTELLIGENCE_CANON.md) controls the reconciled [PRD](../../product/PRD.md), [architecture](../../architecture/autonomous-intelligence.md), and [path-level contradiction/retirement inventory](../../architecture/autonomous-migration-inventory.md). Original governing records remain in the lossless governance archive.

The changes preserve PostgreSQL, existing ingestion adapters, physical-project identity, source/version attribution, historical facts/corrections, deterministic qualification and residual-gap arithmetic, TX/OK/NM eligibility, the 300 kW floor, authentication, and the seven-color G/L identity. PR #125 (`d75a856`) landed during implementation and is integrated here. Its additive persistence models and migrations 0042–0044 are preserved unchanged. This surgery adds no further schema migration; no production data or deployed environment was changed.

## Implementation delivered for validation

- Removed manual call/fact/status/correction interfaces, draft state, client mutations, public manual and research-trigger APIs, manual-only correction writers, and unused request contracts. Historical records and read-side evidence remain.
- Added authenticated typed search across projects, companies, contacts, and opportunity intelligence. Unpublished projections are explicitly pending; stored raw tiers cannot substitute for current qualification.
- Added read-only Research and mobile search/detail behavior. Diagnostics are secondary account navigation, outside the main commercial workflow.
- Enabled bounded unpaid opportunity/contact planning in defaults and example configurations; paid/model dispatch retains independent provider, licensing, budget and validation gates.
- Added replica-safe planner coordination, failure containment, publisher Retry-After preservation, fair research category selection, contact retry/freshness repairs, current-evidence ranking and owner-first presentation.
- Separated source attribution from email deliverability and purchasing authority. No new contact, MW, timing, probability, or commercial-success claim is manufactured.

## Test evidence

The first complete 2,971-test backend gate at `ce2b062` failed: 2,882 passed, 87 failed, one skipped and one setup error. Its [failure receipt](initial-integrated-gate.json) is retained. It exposed obsolete test contracts and a real workspace call-signature defect; fixes and a new complete run are required. Final integrated results will replace this in-progress section. The initial baseline and focused builder checks do not substitute for the complete integrated gate.

- Baseline: lint/format/type checks passed; frontend build passed; 603 backend tests passed before the serial baseline was deliberately stopped for integration. Baseline browser checks passed 201 tests with one skip after installation-related launch failures were rerun.
- Integrated unit checkpoint: 1,839 passed, one skipped, seven subtests passed. The subsequent browser checkpoint passed all 115 tests; real 390-pixel screenshots were inspected and retained under `screenshots/`. Full PostgreSQL regression and final post-upstream browser acceptance remain pending here.
- Fresh disposable PostgreSQL 18.6 migration, repeated upgrade, and Alembic drift check passed. Schema files are unchanged relative to the incorporated upstream main; fresh/repeated/drift checks must also cover upstream revisions 0042–0044.
- Locked backend, frontend and brand dependency audits reported no known vulnerabilities. Upstream PR #125 adds the locked openpyxl dependency; final dependency audit must cover that incorporated lockfile.
- Brand structural validation passed for 216 assets and eight semantic AA contrast pairs; final UI screenshots remain separately required.
- The [independent review ledger](independent-review.md) records findings, fix verification and its own limits. An initial review request for changes is not approval.

## Contact coverage and live acquisition limits

No current production contact-coverage measurement was performed. The retained October 25 v12 benchmark remains a **historical** baseline: 20 companies, four with usable source-published company methods (20%), two with named relevant professionals, and zero verified direct-buyer methods. These are not results of this candidate. Benchmark CSVs are not imported as fresh verified contacts. Apollo access/licensing and current Firecrawl account readiness were not established; no paid engine/provider requests were made during these checks.

A bounded ordinary-worker Austin acquisition in a fresh local database persisted 171 observations/evidence records and six project/power-need records, with no failed or pending interpretations in that batch. Source coverage remained partial, with durable continuation work queued. The receipt tool then failed serializing UUIDs in change history; that defect was repaired and its four unit tests passed. This observation proves that bounded real-source ingestion occurred, **not** complete source coverage, idempotent replay, autonomous contact yield, or a qualified Lead.

The ordinary TCEQ pending-permit worker check failed with a visible network error. The exact official page returned HTTP 200 through the workspace's required proxy; the adapter intentionally uses direct DNS-pinned transport, which is incompatible with this proxy-only execution environment. Its SSRF/TLS protections were not weakened. Neither the failed initial job nor its replay is reported as successful.

## Data safety, recovery and deployment gate

No table/column drops, historical rewrites, production backfills, production migrations, merges, or deployments occurred. Existing append-only history remains readable. Schema retirement is intentionally deferred: leaving retained history tables is not retaining public manual workflows. Relative to current upstream main this surgery needs no additional migration or recovery of deleted data. An installation still at schema 0041 must apply the retained upstream additive migrations 0042–0044 with its existing backup/recovery procedure; do not downgrade them destructively or discard imported rows. Worker rollback still requires checkpoint/status compatibility verification: an older queue must honor the new `retry_after_unrepresentable` hold before resuming affected sources. Retain the current worker or backport that hold behavior if the prior worker does not recognize it; do not silently release publisher retry holds.

Before production release, independently validate the exact release images/configuration, backup and restore, real source network compatibility, worker/browse processes and heartbeat/retry health, contact/provider permissions and cost limits, and source/identity/contact coverage. Observe unattended scheduled operation and the retained launch gates rather than inferring them from local tests. Current direct-buyer yield, full live source coverage, seven consecutive daily cycles, and a reviewed real Lead remain unverified. Deployment is a separate acceptance gate.
