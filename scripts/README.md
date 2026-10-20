# Scripts

These scripts support local setup, validation, replay and bounded diagnostics. Read each script's help and documentation before using it against a configured database. Never point destructive or fixture-oriented commands at production or retained evidence.

## Local setup and checks

- [`setup_local.py`](setup_local.py) prepares ignored local credentials using the documented local database configuration.
- [`setup_compose.py`](setup_compose.py) prepares ignored credentials for the repository's local Compose stack.
- [`check.ps1`](check.ps1) runs the locked backend and web checks, Ruff lint and format checks, migrations, tests, build, and browser regression. It requires configured `DATABASE_URL`, a disposable `TEST_DATABASE_URL` ending `_test`, `APP_PASSWORD_HASH`, and `SESSION_SECRET`. It does not start PostgreSQL, generate credentials, deploy, or prove live scheduled collection.
- [`check_docs.py`](check_docs.py) checks local relative links in the active documentation entry points. Historical missing targets are reported separately from that gate.
- [`export_openapi.py`](export_openapi.py) exports the backend OpenAPI document; then run `npm run generate:api` from `web` to refresh generated TypeScript API types.

From PowerShell at the repository root, run the documentation check with `uv run --project backend python scripts/check_docs.py`. Run the full local gate with `pwsh scripts/check.ps1` after configuring the required environment and disposable databases. See the root [setup and validation guide](../README.md).

Other scripts are purpose-specific. Read their adjacent docs and `--help` before running. A successful local or synthetic command is not production or commercial acceptance evidence.
