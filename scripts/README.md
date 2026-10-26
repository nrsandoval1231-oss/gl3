# Script entry points

These scripts support local setup, checks, replay, and diagnostics. Read each script's help and the relevant runbook before using it against a configured database. Do not use fixture, replay, migration, or source-check commands against production or retained evidence without explicit authorization.

## Local setup and validation

- [`setup_local.py`](setup_local.py) reads database URLs from ignored `.artifacts/local-postgres/connection.env` or process environment with `--use-environment`; it writes ignored `.env` and `.artifacts/local-auth.txt` and refuses to overwrite existing files unless `--force` is passed.
- [`setup_compose.py`](setup_compose.py) writes separate ignored `.env.compose` and `.artifacts/compose-auth.txt`; the Compose URL uses `db:5432` inside the Compose network.
- [`check_docs.py`](check_docs.py) recursively checks repository-local Markdown links reachable from maintained entry points, including anchors. Historical evidence is inventoried and linked but excluded from the active documentation graph.
- [`check.ps1`](check.ps1) runs locked backend and web gates, Ruff lint and format checks, migration checks, tests, build, and Playwright regression. It requires `DATABASE_URL`, `TEST_DATABASE_URL` ending in a separate disposable `_test` database, `APP_PASSWORD_HASH`, and `SESSION_SECRET` in the **process environment**. The PowerShell script does not load `.env` automatically; see the root README's non-printing PowerShell loader.
- [`export_openapi.py`](export_openapi.py) exports the backend contract; run `npm run generate:api` from `web` to refresh generated TypeScript types.

From the repository root, run the docs graph check as `uv run --project backend python scripts/check_docs.py` and the local full gate as `pwsh scripts/check.ps1`. See [clean-checkout local runtime](../docs/operations/local-runtime.md) for database setup and [runtime configuration](../docs/operations/runtime-configuration.md) for code defaults.

Other scripts are purpose-specific. A successful local or synthetic command is not production, live-provider, or commercial acceptance evidence.

The operator-run five-case native/Firecrawl comparison is documented in [acquisition-comparison](../docs/operations/acquisition-comparison.md). Its default inspect mode consumes immutable adapter captures and makes no provider request; paid execution is explicitly bounded and isolated.

Evidence package materialization and exact-job Jev advisory are documented in [production-pipeline-20261023](../docs/operations/production-pipeline-20261023.md). Default mode writes only a cited package; `--execute-jev` is explicitly bounded to one exact selected evidence version and the existing shared call ledger.

The M4 commercial advisory runner is [`run_commercial_assessment.py`](run_commercial_assessment.py). It requires an exact `--package-id`; default mode inspects safely, `--execute` queues and runs only that need's exact M4 job, and `--replay` reads the existing job/call without dispatch or creating work. It is allowlist-gated, uses the existing logical-call budget ledger, and never promotes canonical qualification. See [production-pipeline-20261023](../docs/operations/production-pipeline-20261023.md) for the M4 controls and limitations.

Retained-only operator tools: [news reassessment](../docs/sources/project-interpretation.md#bounded-operator-reassessment) and [buying-chain backfill](../docs/operations/retained-buying-chain-backfill.md). Both use bounded pages and explicit database identity for apply; application/production actions require separate authorization. Use `uv run --project backend python scripts/<script>.py --help` from the repository root.

## Regional stabilization proof utilities

`ingestion_performance.py` compares local TestClient routing/SQL timings on a fixed retained clone and configuration, without network/authentication latency. `verify_ingestion_recovery.py` runs explicitly selected enabled sources through the real worker only in an isolated loopback `*_app` database, clears model keys and retains private source receipts. `regional_preservation.py` checks that every pre-existing evidence/change-event version and retained identity survives migration and ingestion, and rejects duplicate source/project identities. These utilities neither authorize nor prove production operation. Raw receipts and database files belong in ignored `.artifacts/`.

`prove_ingestion_interruption.py` deliberately exits after the first committed real TCEQ evidence row in an empty loopback `*_recovery_app` database, then proves expired-lease recovery and unchanged replay. Its destructive process interruption is restricted to its own disposable verification process/database; it must never target the application or production database.

## Autonomous product and validation boundary

The [Autonomous Intelligence Canon](../docs/product/AUTONOMOUS_INTELLIGENCE_CANON.md) governs current behavior. These scripts are internal diagnostics, isolated validation or scheduled-pipeline helpers; they do not authorize manual user forms or public data-entry mutation routes. Preserve the immutable evidence/call-note tables in validation retention checks even though the public logging workflow is retired.

`python scripts/check_docs.py` validates the maintained product/agent authority graph as well as setup/runbook links. The [autonomous architecture](../docs/architecture/autonomous-intelligence.md) maps retired public behavior to retained evidence and automation. Older browser or research receipts remain candidate-specific; regenerate expectations for the autonomous UI and distinguish synthetic fixtures from actual source/provider and production measurements. Benchmark CSVs and prior contact-recovery results are evaluation records, not automatically accepted current contacts.
