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
