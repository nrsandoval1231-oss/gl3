# GridLens 3

GridLens 3 is a private, evidence-backed workspace for discovering emerging commercial power needs. The current local candidate registry enables 18 public sources spanning municipal planning notices, construction permits, air permitting/regulatory records, government/economic-development publications, public documents, and industry news. The system preserves source observations and evidence history, groups supported records into project-oriented Signal cards, and keeps unsupported commercial facts explicitly unknown.

The latest verified main snapshot was `07c0886` (GL3-019, PR9); this checkout is the separate `feat/gl3-023-city-permits` draft PR15 candidate at base `118d419`. GL3-023 and GL3-024 changes here are local and unmerged. See [the saved-cloud handoff](docs/operations/post-gl3-019-handoff.md) for the earlier main snapshot's starting point and remaining gaps. The accepted local Signal foundation adds bounded adjudication for ambiguous evidence, persisted reproducible SHOW / REVIEW / HOLD decisions, and conservative physical-project grouping. National coverage and deployed daily operation remain unproven.

The local GL3-024 candidate removes the standalone Cannabis Watch and its topic-match API behavior while retaining cannabis and publisher evidence in the ordinary inbox. Opportunity titles use project-bound company evidence with the role shown; unknown companies fall back to the activity and site. The visible commercial floor is 300 kW inclusive with no maximum: confirmed smaller activity is hidden from opportunity views, while unknown-size Signals remain marked unknown. Campus totals and nameplate or operating capacity do not establish temporary-power need. See the dated [PRD amendment](docs/product/PRD.md).

## Today’s Power Pursuits

The next working slice adds persisted daily Austin/RRC pursuits, bounded official-source research, separate action statuses and owner call outcomes. Open `?view=pursuits`; see [startup and scheduler limits](docs/operations/power-pursuits.md) and [real-source validation](docs/validation/gl3-021-power-pursuits.md). Unknown rental demand, load, fuel, duration and buying authority remain unknown. This feature does not promote tiers or establish cloud operation.

## Product model

GridLens follows:

**Discover → preserve evidence → resolve project → investigate power need → qualify → prioritize → act → update.**

- **Signal:** sourced event with a defensible reason to investigate a possible power need.
- **Prospect:** actual power requirement plus supported evidence that suitable supply may be insufficient or unavailable when required.
- **Lead:** supported unresolved power need with MW range, start window, duration range, supply-gap explanation, likely buying organization/role, and next action.

Current production-like local behavior is intentionally conservative: Signals do not inherit MW, timing, buyer, utility-shortage, or rental-need claims that the evidence does not support.

## Current source coverage

The current local candidate registry contains 18 enabled sources, including:

- Austin commercial building/electrical permits with a bounded 2026 data-center backfill; Seattle and Chicago permits.
- Texas RRC current-month drilling file plus official prior-month EOM overlap, with amendment history and unknown production timing.
- Houston’s four latest linked weekly permit workbooks, with reporting lag and limited fields explicitly retained.
- Bounded Dallas monthly and El Paso new-commercial permits, plus Massachusetts Cannabis Control Commission cultivation applications; each retains its source-specific site, date, and role limits.
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

GL3-019 passed 418 backend tests (one existing missing-fixture skip), Ruff/mypy, frontend typecheck/build, clean/repeated migrations with no drift, live replay/provenance audits and 13 browser checks (11 repository checks plus two saved-cloud live acceptance cases). See [the validation report](docs/validation/gl3-019-acquisition-continuation.md); the additional live cases remain captured acceptance artifacts, not repository tests. Hosted GitHub Actions remain blocked before runner execution by the account payment/spending-limit condition; the workflow itself has not been weakened.

Runtime status and bounded in-place source recovery are available through `python -m gridlens.jobs.runtime` with the backend environment. See [runtime recovery](docs/operations/runtime-recovery.md) for registry reconciliation, selected checks, retry behavior and operational limits.

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

## Project buying chain and merged GL3-019

Project detail now has a bounded Buying Chain enrichment action. It reuses the physical Project ID and retained evidence, reads exact Chicago permit contractor fields, and accepts up to four additional public evidence links. Organization involvement, a person's current organization role, and personal project assignment remain separate evidence claims. ROLE_SUPPORTED never means a person is assigned to the project or controls its temporary-power purchase. Missing facts remain UNKNOWN.

GL3-017 through GL3-019 are merged; this is not a deployment claim. GL3-018 live acquisition produced 25 permit-backed Signals across Chicago and Georgia, with no proven Prospects or Leads. See [GL3-018 validation](docs/validation/gl3-018-validation.md). Earlier GL3-017 network failures remain historical validation records.

GL3-019 prioritizes **data-center construction temporary power**, then **data-center commissioning temporary power**, then **oil and gas temporary power**. Permit-derived project/site, scope, dates and organizations should be useful directly from retained evidence. Drilling permits are valid early production Signals without an already-proven power gap; production date, load and fuel suitability stay unknown unless supported. Upstream wells and fixed O&G infrastructure retain separate lifecycles. News stays supplemental.

GL3-019 repaired permit enrichment using existing evidence and persistence. GL3-023 adds bounded Dallas monthly, El Paso NewCommercial, and Houston weekly Sold Permit acquisition, with source-specific event semantics and role-attributed enrichment. Each route has limited geographic, permit-type, and date coverage; current permit activity, commissioning, rental demand, fuel fit, and buying authority remain UNKNOWN unless separately supported. See [GL3-023 city permit coverage and limits](docs/sources/gl3-023-city-permits.md). The discontinued Dallas open-data dataset remains disabled.
