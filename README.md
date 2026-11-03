# GridLens GL3

**GridLens — Autonomous Power Demand Intelligence.** GridLens discovers, classifies, and quantifies power demand from evidence, then tracks the entities, equipment, and lifecycle events behind it. The November 2 production release provides authenticated company/operator rollups and nested projects. Sector selection, search, region/stage/priority filters, sorting, and generation-bound pagination run against server data. The full six-layer intelligence engine remains a target, not a shipped claim. See the [accepted production release receipt](docs/validation/production-release-20261102.md) for the exact source, image identities, recovery evidence and live verification.

The current FastAPI/PostgreSQL/worker/React application retains source-backed project discovery, evidence packages and Signal/Prospect/Lead as legacy qualification compatibility. Its deployed `equipment-demand-v1` summary is scoped to additional equipment and separates supported amounts from unknown or conflicted records. At the November 2 release generation there were no validated equipment-demand records, so Identified Power Demand (MW) is shown as unavailable; this is not a total for all facility or portfolio demand. Do not convert unavailable or unknown values to zero. The bounded Oil & Gas equipment parser/model is described in its [implementation plan](docs/engineering/equipment-demand-slice-20261030.md); this slice does not complete the six-layer engine or establish broad scheduled-source coverage.

## Current status

The [current repository checkpoint](.agent/CURRENT_STATE.md) records active work. The [delivery gates](docs/delivery/milestones.md) distinguish the accepted November 2 release from longer-term operating and commercial gates. Dated [validation](docs/validation/) records apply only to their named candidate and environment; the [production release receipt](docs/validation/production-release-20261102.md) is the current accepted deployment evidence.

## Work areas

- [Product requirements](docs/product/PRD.md)
- [Architecture boundaries](docs/architecture/overview.md)
- [Source coverage](docs/sources/coverage.md)
- [Operations status](docs/operations/README.md)
- [Delivery gates](docs/delivery/milestones.md)
- [November 2 production release and validation](docs/validation/production-release-20261102.md)
- [Historical and candidate validation evidence](docs/validation/)

Historical status narratives and reports were removed from the working tree in the 2026-11-03 evidence cleanup; they remain retrievable from git history prior to that commit. Existing dated validation records are not current state unless a current status page cites and revalidates them.

## Run locally

For a clean-checkout native Windows setup, follow the [local runtime guide](docs/operations/local-runtime.md). It provisions a loopback-only PostgreSQL 18 cluster on port `55439`, separates `gridlens` and `gridlens_test`, and explains ignored environment files. The setup helper refuses to overwrite existing credentials by default. Do not point tests or setup at a retained or production database.

For the optional containerized local stack, see [`setup_compose.py`](scripts/setup_compose.py) and [`compose.yaml`](compose.yaml). Its PostgreSQL is on the Compose network as `db:5432`; its environment file is `.env.compose`, separate from native `.env`. Neither path configures production.

## Validate

`uv run --project backend python scripts/check_docs.py` verifies local links in the maintained documentation graph. `scripts/check.ps1` is the full local gate: locked backend sync, dependency audit, Ruff lint and format checks, mypy, migration checks, pytest, npm audit, TypeScript check, web build, and Playwright browser regression.

The full gate requires process environment variables `DATABASE_URL`, `TEST_DATABASE_URL`, `APP_PASSWORD_HASH`, and `SESSION_SECRET`; the test URL must end in a separate disposable `_test` database. The PowerShell script does not parse `.env`. From a PowerShell window with the generated ignored `.env`, load only these four values into the current process without displaying them:

```powershell
foreach ($line in Get-Content .env) {
    $pair = $line -split '=', 2
    if ($pair.Count -eq 2 -and $pair[0] -in @('DATABASE_URL', 'TEST_DATABASE_URL', 'APP_PASSWORD_HASH', 'SESSION_SECRET')) {
        [Environment]::SetEnvironmentVariable($pair[0], $pair[1], 'Process')
    }
}
pwsh scripts/check.ps1
```

A successful local check does not prove production operation. Do not infer the current production deployment or its authorization from local checks. The November 2 deployment is documented in its exact [release receipt](docs/validation/production-release-20261102.md); longer-term operating safeguards and open verification gates are summarized in [operations status](docs/operations/README.md) and [delivery status](docs/delivery/milestones.md).

## Documentation authorities and history

Use [docs/README.md](docs/README.md) as the topic map. The [Autonomous Intelligence Canon](docs/product/AUTONOMOUS_INTELLIGENCE_CANON.md) governs product behavior, supported by compatible [PRD](docs/product/PRD.md) qualification rules; the [UI canon](docs/design/UI_CANON.md) governs presentation; [architecture overview](docs/architecture/overview.md), [source coverage](docs/sources/coverage.md), [operations status](docs/operations/README.md), and [delivery status](docs/delivery/milestones.md) summarize their respective implementation and evidence. Historical reports remain dated evidence and do not establish current deployment or acceptance.
