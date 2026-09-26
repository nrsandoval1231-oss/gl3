# GridLens 3

GridLens 3 is a private, evidence-backed workspace for emerging commercial power needs. The validated first path collects Federal Register environmental-impact notices, keeps source observations and evidence history, and shows only narrowly qualified mine-development Signals. The current source package also includes North Carolina Commerce project announcements and GovInfo PDF evidence linked to an existing Federal Register record; alternate formats are not counted as fresh source records. Missing MW, supply, and event dates remain unknown.

## Run locally

Requirements: Python 3.11, uv, Node.js 22+, npm, and PostgreSQL 15 or later. From PowerShell at the repository root:

```powershell
uv sync --project backend --extra dev
npm --prefix web ci
uv run --project backend python scripts/setup_local.py
```

The setup script reads PostgreSQL connection values from the ignored `.artifacts/local-postgres/connection.env` created by the isolated local database setup. It writes ignored `.env` and `.artifacts/local-auth.txt`; the latter contains the generated local password. Do not copy either file into Git. For a different PostgreSQL instance, create distinct application and test databases, set `$env:DATABASE_URL` and `$env:TEST_DATABASE_URL` in PowerShell, then run `uv run --project backend python scripts/setup_local.py --use-environment`. Never point the test URL at the application database. Both setup scripts refuse to rotate existing credential files unless `--force` is explicit.

Start the services in separate terminals:

```powershell
uv run --directory backend alembic upgrade head
uv run --project backend uvicorn gridlens.api.app:app --app-dir backend/src --host 127.0.0.1 --port 8000
$env:PYTHONPATH = (Join-Path $PWD 'backend/src')
uv run --project backend python -m gridlens.jobs.worker
npm --prefix web run dev
```

Open http://127.0.0.1:5173 and use the password in `.artifacts/local-auth.txt`. The worker polls durable PostgreSQL jobs; it does not use a model or take external actions. The Federal Register adapter uses a bounded, complete, recent date window. Retrieval requires public internet access.

## Validate

```powershell
uv run --directory backend ruff check src tests
uv run --directory backend mypy src
uv run --directory backend pytest tests
npm --prefix web run typecheck
npm --prefix web run build
npm --prefix web audit --audit-level=high
```

PostgreSQL integration tests destructively reset only `TEST_DATABASE_URL` after verifying it names an explicit test database distinct from `DATABASE_URL`. The Playwright test exercises login, browse/detail, browser Back, and mobile source health when the local auth file and runtime are available.

## Containers

Run `uv run --project backend python scripts/setup_compose.py`, then run `docker compose --env-file .env.compose up --build` for a local HTTP session at http://127.0.0.1:8080. Before remote HTTPS access, edit `.env.compose` to set `COOKIE_SECURE=true` and `TRUSTED_ORIGINS` to the exact HTTPS site origin. Compose runs PostgreSQL, migrations/API, the separate worker, and a static web server that proxies `/api`. See [deployment notes](deploy/README.md); scheduler configuration is preparation only and does not deploy anything.

## Product and operations

- [Product requirements](docs/product/PRD.md)
- [Architecture](docs/architecture/overview.md)
- [Source coverage and limitations](docs/sources/coverage.md)
- [Local recovery proof](docs/operations/local-recovery-proof.md)
