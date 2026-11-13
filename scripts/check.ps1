# Local checks corresponding to the current GitHub Actions workflow.
# Run from any directory:  pwsh scripts/check.ps1
#
# Prerequisites:
#   - uv 0.7.13 and Python 3.11
#   - Node.js 22
#   - PostgreSQL 18.6, the image in compose.yaml
#   - DATABASE_URL and TEST_DATABASE_URL pointing at separate databases.
#     Both must use a loopback host and a disposable database name ending in
#     _test; the script refuses to run migrations or tests otherwise.
#   - APP_PASSWORD_HASH and SESSION_SECRET set for the API process.
#
# The script does not start Postgres, generate secrets, or upload logs.

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $Root

function Invoke-Native {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][scriptblock]$Command
    )
    Write-Host "== $Name"
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$Name failed with exit code $LASTEXITCODE"
    }
}

foreach ($name in @("DATABASE_URL", "TEST_DATABASE_URL", "APP_PASSWORD_HASH", "SESSION_SECRET")) {
    if (-not (Test-Path "Env:$name") -or [string]::IsNullOrWhiteSpace((Get-Item "Env:$name").Value)) {
        throw "Set $name before running scripts/check.ps1"
    }
}

# Migrations and the pytest fixtures create and drop schema. Refuse anything that
# is not a loopback, disposable database so retained/production data is never touched.
function Assert-DisposableLoopbackDatabase {
    param([Parameter(Mandatory = $true)][string]$Name)
    $value = (Get-Item "Env:$Name").Value
    try {
        $uri = [System.Uri]($value -replace '^[A-Za-z0-9+_.-]+://', 'postgresql://')
        $dbHost = $uri.Host
        $database = $uri.AbsolutePath.TrimStart('/')
    }
    catch {
        throw "$Name is not a parseable database URL"
    }
    if (@("localhost", "127.0.0.1", "::1", "[::1]") -notcontains $dbHost) {
        throw "$Name must point at a loopback host (localhost, 127.0.0.1 or ::1), not '$dbHost'"
    }
    if ($database -notmatch '_test$') {
        throw "$Name must name a disposable database ending in _test"
    }
}
foreach ($name in @("DATABASE_URL", "TEST_DATABASE_URL")) {
    Assert-DisposableLoopbackDatabase $name
}

Push-Location (Join-Path $Root "backend")
try {
    Invoke-Native "uv sync" { uv sync --locked --extra dev }
    New-Item -ItemType Directory -Force -Path .artifacts | Out-Null
    Invoke-Native "export locked requirements" {
        uv export --locked --extra dev --no-emit-project --format requirements-txt --output-file .artifacts/backend-requirements.txt
    }
    Invoke-Native "pip-audit" {
        $audit = & uv tool run --python 3.11 --from pip-audit==2.10.1 pip-audit -r .artifacts/backend-requirements.txt --disable-pip --no-deps --format json
        if ($LASTEXITCODE -ne 0) { throw "pip-audit failed with exit code $LASTEXITCODE" }
        $audit | Out-File -Encoding utf8 .artifacts/backend-dependency-audit.json
    }
    Invoke-Native "documentation links" { uv run python (Join-Path $Root "scripts/check_docs.py") }
    Invoke-Native "ruff" { uv run ruff check src tests }
    Invoke-Native "ruff format check" { uv run ruff format --check src tests }
    Invoke-Native "mypy" { uv run mypy src }
    Invoke-Native "alembic upgrade head" { uv run alembic upgrade head }
    Invoke-Native "alembic check" { uv run alembic check }
    Invoke-Native "pytest" { uv run pytest tests }
}
finally {
    Pop-Location
}

Invoke-Native "npm ci" { npm ci --prefix web }
Invoke-Native "npm audit" { npm audit --prefix web --audit-level=high }
Invoke-Native "web typecheck" { npm run typecheck --prefix web }
Invoke-Native "web build" { npm run build --prefix web }

Push-Location (Join-Path $Root "web")
try {
    Invoke-Native "playwright chromium" { npx playwright install chromium }
}
finally {
    Pop-Location
}

$browserEnv = @{
    COOKIE_SECURE = "false"
    WORKER_AUTO_REFRESH = "false"
    OPENAI_API_KEY = ""
    TYPESAFE_API_KEY = ""
    BRIEFS_DAILY_REQUEST_LIMIT = "0"
    PURSUITS_DAILY_MODEL_LIMIT = "0"
}
foreach ($entry in $browserEnv.GetEnumerator()) {
    Set-Item -Path "Env:$($entry.Key)" -Value $entry.Value
}
Invoke-Native "browser regression" { npm run test:ci --prefix web }

Write-Host "checks passed"
