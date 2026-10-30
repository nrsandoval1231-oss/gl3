# GridLens GL3

**GridLens — Autonomous Power Demand Intelligence.** GridLens discovers, classifies, and quantifies power demand from evidence, then tracks the entities, equipment, and lifecycle events behind it. This target direction is not a claim that the full engine is shipped. The [sole product canon](docs/product/AUTONOMOUS_INTELLIGENCE_CANON.md) defines six target layers and separates CURRENT, TARGET, NEXT, and DEFERRED capabilities. The October 29 UI is the dated released presentation; the candidate preserves that layout while adding demand terminology and equipment details.

The current FastAPI/PostgreSQL/worker/React system retains regional project discovery, evidence packages, and legacy Signal/Prospect/Lead qualification. The bounded Oil & Gas parser/model slice is implemented in this candidate; see its [implementation plan](docs/engineering/equipment-demand-slice-20261030.md). A [native FERC notice extension](docs/engineering/native-equipment-demand-20261030.md) connects a retained real equipment proposal to an investigation with unknown electrical capacity. The demand-centered UI is implemented in the current candidate, but KPI data is unavailable and the candidate is not production shipped.

## Current status

The [current repository checkpoint](.agent/CURRENT_STATE.md) records the inspected main head, engineering changes and unresolved live/commercial proof. The [delivery gates](docs/delivery/milestones.md) define acceptance boundaries. Dated [validation](docs/validation/) records apply only to their specific candidate and environment; none should be mistaken for a fresh production observation.

## Work areas

- [Product requirements](docs/product/PRD.md)
- [Architecture boundaries](docs/architecture/overview.md)
- [Source coverage](docs/sources/coverage.md)
- [Operations status](docs/operations/README.md)
- [Delivery gates](docs/delivery/milestones.md)
- [Validation evidence](docs/validation/)

Historical status narratives and reports are retained under [.agent/archive/STAGE1-20261009/](.agent/archive/STAGE1-20261009/) and existing dated validation records. They are not current state.

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

A successful local check does not prove production operation. Do not infer the current production deployment or its authorization from local checks. Historical production observations, operational safeguards and open verification gates are documented in [operations status](docs/operations/README.md) and [delivery status](docs/delivery/milestones.md).

## Documentation authorities and history

Use [docs/README.md](docs/README.md) as the topic map. The [Autonomous Intelligence Canon](docs/product/AUTONOMOUS_INTELLIGENCE_CANON.md) governs product behavior, supported by compatible [PRD](docs/product/PRD.md) qualification rules; the [UI canon](docs/design/UI_CANON.md) governs presentation; [architecture overview](docs/architecture/overview.md), [source coverage](docs/sources/coverage.md), [operations status](docs/operations/README.md), and [delivery status](docs/delivery/milestones.md) summarize their respective implementation and evidence. Historical reports remain dated evidence and do not establish current deployment or acceptance.
