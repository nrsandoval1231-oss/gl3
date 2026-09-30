# GridLens 3

GridLens 3 is a private, evidence-backed workspace for discovering emerging commercial power needs. The current local registry enables 13 public sources spanning municipal planning notices, construction permits, air permitting/regulatory records, government/economic-development publications, public documents, and industry news. The system preserves source observations and evidence history, groups supported records into project-oriented Signal cards, and keeps unsupported commercial facts explicitly unknown.

GL3-018 is merged on main (PR #8, `7f24174`). Standalone Signals require official permit evidence, a project-specific official utility filing, or an explicit temporary-power solicitation. News supplements one supported physical project. Planning and entitlement remain research context. GL3-016 remains the bounded Jev adjudication path for ambiguous retained evidence, with persisted SHOW / REVIEW / HOLD decisions and conservative physical-project grouping. The frozen GL3-015 corpus contained 81 Signal records displayed as 63 cards. National coverage and deployed daily operation remain unproven.

## Product model

GridLens follows:

**Discover → preserve evidence → resolve project → investigate power need → qualify → prioritize → act → update.**

- **Signal:** sourced event with a defensible reason to investigate a possible power need.
- **Prospect:** actual power requirement plus supported evidence that suitable supply may be insufficient or unavailable when required.
- **Lead:** supported unresolved power need with MW range, start window, duration range, supply-gap explanation, likely buying organization/role, and next action.

Current production-like local behavior is intentionally conservative: Signals do not inherit MW, timing, buyer, utility-shortage, or rental-need claims that the evidence does not support.

## Current source coverage

The registry currently contains 13 enabled sources, including:

- Austin, Seattle, and Chicago building-permit feeds. Chicago also includes Express Permit Program Electrical Work.
- Georgia Draft Title V, SIP, and synthetic-minor air filings, with bounded page-cited generator excerpts from narratives and drafts. Full air applications remain unretrieved.
- Federal Register environmental-impact notices with eligible GovInfo PDF evidence.
- North Carolina Commerce project announcements.
- Taylor, Texas Development News and Development Notices, including bounded archive revisions.
- Data Center Dynamics, Utility Dive, Manufacturing Dive, Construction Dive, Oil & Gas Journal, and MJBizDaily publisher feeds.

Permits are the primary discovery path and news is supplemental. Coverage is not yet nationally complete. See [source coverage](docs/sources/coverage.md) and the [local Signal verification](docs/delivery/local-signal-verification.md) for measured limits.

## Run locally

Requirements: Python 3.11, uv, Node.js 22+, npm, and PostgreSQL 15 or later. From PowerShell at the repository root:

```powershell
uv sync --project backend --extra dev
npm --prefix web ci
uv run --project backend python scripts/setup_local.py
```

The setup script reads PostgreSQL connection values from the ignored `.artifacts/local-postgres/connection.env`. It writes ignored `.env` and `.artifacts/local-auth.txt`; the latter contains the generated local password. Do not commit either file.

Start the services in separate terminals:

```powershell
uv run --directory backend alembic upgrade head
uv run --project backend uvicorn gridlens.api.app:app --app-dir backend/src --host 127.0.0.1 --port 8000
$env:PYTHONPATH = (Join-Path $PWD 'backend/src')
uv run --project backend python -m gridlens.jobs.worker
npm --prefix web run dev
```

Open http://127.0.0.1:5173 and use the password in `.artifacts/local-auth.txt`.

## Validate

```powershell
uv run --directory backend ruff check src tests
uv run --directory backend mypy src
uv run --directory backend pytest tests
npm --prefix web run typecheck
npm --prefix web run build
npm --prefix web audit --audit-level=high
```

GL3-013 recorded an earlier checkpoint of 205 backend tests, frontend typecheck/build, zero-vulnerability npm audit, migrations/replay checks, and three authenticated Playwright tests. The latest recorded full local acceptance is GL3-018: 381 pytest passes, one existing local-probe skip, Ruff, mypy, migrations, frontend typecheck/build, and nine Playwright tests, in [GL3-018 validation](docs/validation/gl3-018-validation.md). Earlier records said hosted GitHub Actions were blocked before runner execution by the account payment/spending-limit condition. This repository does not re-check that account state.

## Containers and deployment

Run `uv run --project backend python scripts/setup_compose.py`, then `docker compose --env-file .env.compose up --build` for local container operation.

Cloud scheduling is **not yet deployed or accepted**. The scheduler manifest is preparation only. Production still requires authorized hosting/secrets, PC-off scheduled ingestion, operational alerts, backup/restore proof, and seven measured daily cycles.

## Product and operations

- [Product requirements](docs/product/PRD.md)
- [Frozen UI canon](docs/design/UI_CANON.md)
- [Architecture](docs/architecture/overview.md)
- [Source coverage and limitations](docs/sources/coverage.md)
- [Local Signal verification](docs/delivery/local-signal-verification.md)
- [Signal card review](docs/delivery/signal-card-review.md)
- [Local recovery proof](docs/operations/local-recovery-proof.md)
- [Current agent state](.agent/CURRENT_STATE.md)

## Merged GL3-017 and GL3-018

GL3-017 (PR #7) adds a project-detail Buying Chain. It reuses the physical Project ID and retained evidence, reads exact Chicago permit contractor fields, and accepts up to four additional public evidence links. Organization involvement, a person's current organization role, and personal project assignment remain separate evidence claims. ROLE_SUPPORTED never means a person is assigned to the project or controls its temporary-power purchase. Missing facts remain UNKNOWN. See [GL3-017 validation](docs/validation/gl3-017-buying-chain.md). That record's saved-cloud run did not prove direct live retrieval. Later owner-reported acceptance is not restated here as new proof. No outreach or tier promotion is included.

GL3-018 (PR #8) is the current admission and acquisition behavior. See [GL3-018 admission](docs/sources/gl3-018-admission-and-acquisition.md) and [GL3-018 validation](docs/validation/gl3-018-validation.md). No deployment is included.
