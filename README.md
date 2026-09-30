# GridLens 3

GridLens 3 is a private, evidence-backed workspace for discovering emerging commercial power needs. The current local registry enables 13 public sources spanning municipal planning notices, construction permits, air permitting/regulatory records, government/economic-development publications, public documents, and industry news. Taylor planning notices have fresh isolated ordinary-worker persistence/replay and authenticated card proof; deployed daily operation remains unproven. The system preserves source observations and evidence history, groups supported records into project-oriented Signal cards, and keeps unsupported commercial facts explicitly unknown.

GL3-017 and GL3-018 are merged on main (verified at `7f24174`). GL3-018 adds authoritative Signal admission, Chicago electrical permits and deeper Georgia permit documents. The accepted local Signal foundation retains 14 enabled public sources and adds bounded Jev adjudication for ambiguous evidence, persisted reproducible SHOW / REVIEW / HOLD decisions, and conservative physical-project grouping. The frozen GL3-015 corpus contained 81 Signal records displayed as 63 cards; GL3-016 preserved the evidence rather than promoting unsupported commercial facts. National coverage and deployed daily operation remain unproven.

## Product model

GridLens follows:

**Discover → preserve evidence → resolve project → investigate power need → qualify → prioritize → act → update.**

- **Signal:** sourced event with a defensible reason to investigate a possible power need.
- **Prospect:** actual power requirement plus supported evidence that suitable supply may be insufficient or unavailable when required.
- **Lead:** supported unresolved power need with MW range, start window, duration range, supply-gap explanation, likely buying organization/role, and next action.

Current production-like local behavior is intentionally conservative: Signals do not inherit MW, timing, buyer, utility-shortage, or rental-need claims that the evidence does not support.

## Current source coverage

The registry currently contains 14 enabled sources, including:

- Austin commercial building/electrical permits with a bounded 2026 data-center backfill; Seattle and Chicago permits.
- Houston’s four latest linked weekly permit workbooks, with reporting lag and limited fields explicitly retained.
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

## Project buying chain and next acquisition slice

Project detail now has a bounded Buying Chain enrichment action. It reuses the physical Project ID and retained evidence, reads exact Chicago permit contractor fields, and accepts up to four additional public evidence links. Organization involvement, a person's current organization role, and personal project assignment remain separate evidence claims. ROLE_SUPPORTED never means a person is assigned to the project or controls its temporary-power purchase. Missing facts remain UNKNOWN.

GL3-017 and GL3-018 are merged; this is not a deployment claim. GL3-018 live acquisition produced 25 permit-backed Signals across Chicago and Georgia, with no proven Prospects or Leads. See [GL3-018 validation](docs/validation/gl3-018-validation.md). Earlier GL3-017 network failures remain historical validation records.

GL3-019 prioritizes **data-center construction temporary power**, then **data-center commissioning temporary power**, then **oil and gas temporary power**. Permit-derived project/site, scope, dates and organizations should be useful directly from retained evidence. Drilling permits are valid early production Signals without an already-proven power gap; production date, load and fuel suitability stay unknown unless supported. Upstream wells and fixed O&G infrastructure retain separate lifecycles. News stays supplemental.

GL3-019 repairs permit enrichment using existing evidence and persistence, including Austin permit-listed organizations, names and business-phone fields. Dallas and El Paso official routes currently return access errors from this cloud executor; neither is enabled. It does not claim national completeness, an active drilling feed, a commissioning connector, rental demand from generator nameplate, or a supply gap from missing energization. See [GL3-019 scope](docs/sources/gl3-019-permit-enrichment.md).
