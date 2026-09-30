# GridLens 3

GridLens 3 is a private, evidence-backed workspace for discovering emerging commercial power needs. The current local registry enables 13 public sources spanning municipal planning notices, construction permits, air permitting/regulatory records, government/economic-development publications, public documents, and industry news. Taylor planning notices have fresh isolated ordinary-worker persistence/replay and authenticated card proof; deployed daily operation remains unproven. The system preserves source observations and evidence history, groups supported records into project-oriented Signal cards, and keeps unsupported commercial facts explicitly unknown.

GL3-016 is merged on main. The accepted local Signal foundation retains 13 enabled public sources and adds bounded Jev adjudication for ambiguous evidence, persisted reproducible SHOW / REVIEW / HOLD decisions, and conservative physical-project grouping. The frozen GL3-015 corpus contained 81 Signal records displayed as 63 cards; GL3-016 preserved the evidence rather than promoting unsupported commercial facts. National coverage and deployed daily operation remain unproven.

## Product model

GridLens follows:

**Discover → preserve evidence → resolve project → investigate power need → qualify → prioritize → act → update.**

- **Signal:** sourced event with a defensible reason to investigate a possible power need.
- **Prospect:** actual power requirement plus supported evidence that suitable supply may be insufficient or unavailable when required.
- **Lead:** supported unresolved power need with MW range, start window, duration range, supply-gap explanation, likely buying organization/role, and next action.

Current production-like local behavior is intentionally conservative: Signals do not inherit MW, timing, buyer, utility-shortage, or rental-need claims that the evidence does not support.

## Current source coverage

The registry currently contains 13 enabled sources, including:

- Austin, Seattle, and Chicago building-permit feeds.
- Georgia Draft Title V air-permit filings and supporting public documents.
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

GL3-013 passed 205 backend tests, frontend typecheck/build, zero-vulnerability npm audit, migrations/replay checks, and three authenticated Playwright tests against isolated databases. Hosted GitHub Actions remain blocked before runner execution by the account payment/spending-limit condition; the workflow itself has not been weakened.

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

## GL3-017 buying-chain draft

Project detail now has a bounded Buying Chain enrichment action. It reuses the physical Project ID and retained evidence, reads exact Chicago permit contractor fields, and accepts up to four additional public evidence links. Organization involvement, a person's current organization role, and personal project assignment remain separate evidence claims. ROLE_SUPPORTED never means a person is assigned to the project or controls its temporary-power purchase. Missing facts remain UNKNOWN.

This is a draft slice, not a verified live deployment. Captured real-source parsing/persistence is distinct from direct application retrieval, which is blocked by this cloud shell's DNS limits. Browser interaction validation is also blocked by the runtime. See [GL3-017 contract, real-source review and validation limitations](docs/validation/gl3-017-buying-chain.md). No outreach, new acquisition source, tier promotion, merge or deployment is included. GL3-018 remains later acquisition expansion.
