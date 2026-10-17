# GridLens GL3

GridLens is a clean-sheet, evidence-governed system for discovering nationwide power needs and qualifying commercial opportunities. Product scope and qualification rules are defined by [the PRD](docs/product/PRD.md); the owner-approved interaction design is [the UI canon](docs/design/UI_CANON.md).

## Current status

The status page is [delivery milestones](docs/delivery/milestones.md). Current main is `3af0be9` (includes pull requests #49, #66, #67 and #68). [.agent/CURRENT_STATE.md](.agent/CURRENT_STATE.md) is a short checkpoint that points there. Stage reports under [validation](docs/validation/) are dated evidence. They do not establish deployment or commercial acceptance.

## Work areas

- [Product requirements](docs/product/PRD.md)
- [Architecture boundaries](docs/architecture/overview.md)
- [Source coverage](docs/sources/coverage.md)
- [Operations status](docs/operations/README.md)
- [Delivery gates](docs/delivery/milestones.md)
- [Validation evidence](docs/validation/)

Historical status narratives and reports are retained under [.agent/archive/STAGE1-20261009/](.agent/archive/STAGE1-20261009/) and existing dated validation records. They are not current state.

## Run locally

The development entry points below are documented for a configured local environment; Stage 1 found no `.env`, virtual environment, or GL3 runtime in this checkout. Setup requires Python 3.11, uv 0.7.13, Node.js 22+, npm, and PostgreSQL 18.6. From PowerShell at the repository root:

```powershell
uv sync --project backend --extra dev
npm --prefix web ci
uv run --project backend python scripts/setup_local.py
```

The setup script reads PostgreSQL connection values from ignored `.artifacts/local-postgres/connection.env` and writes ignored `.env` and `.artifacts/local-auth.txt`. Do not commit them. Start services in separate terminals:

```powershell
uv run --directory backend alembic upgrade head
uv run --project backend uvicorn gridlens.api.app:app --host 127.0.0.1 --port 8000 --no-proxy-headers
uv run --project backend python -m gridlens.jobs.worker
npm --prefix web run dev
```

Open http://127.0.0.1:5173 and use the password in `.artifacts/local-auth.txt`. This documents the local developer path; it does not prove a live service, scheduled cloud operation, or deployment.


## Validate

Before backend integration tests, configure `TEST_DATABASE_URL` for an isolated disposable database. Keep it separate from the application `DATABASE_URL`; do not use retained or production data.

`scripts/check.ps1` is the full local check: locked sync, dependency audit, ruff, mypy, Alembic upgrade (twice) and `alembic check`, pytest, one `npm ci`, npm audit, TypeScript check, web build, and the Playwright regression project. It needs `DATABASE_URL`, `TEST_DATABASE_URL`, `APP_PASSWORD_HASH`, and `SESSION_SECRET`. Passing it does not prove a scheduled cloud run.

Cloud scheduling is not established by local validation. The scheduler manifest is preparation only. Production requires separately authorized hosting/secrets, PC-off scheduled ingestion, operational alerts, backup/restore proof, and seven measured daily cycles.
