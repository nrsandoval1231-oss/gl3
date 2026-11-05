# Fresh local CI validation — PR160

Validated commit: `78591b308aa829a25157bf3310133ed069434d3b`
Tree: `125b7dc0ee61a890b1dffff40f3b2891df3be9c1`
Workflow SHA-256: `8dd1a97a4c1f1006aa3bb3a2e36562fb75c5b2ddb1ace68bec2e30214675d38c`
Started: 2026-10-31T16:47:53.925932+00:00
Finished: 2026-10-31T17:02:52.379062+00:00

**Overall: FAIL.** The fresh backend test gate timed out. Prior passing runs are not substituted for this request. No application code/configuration was edited, no GitHub Actions run was dispatched, and no production/PC/provider operation occurred.

| Job | Fresh local result | Evidence |
|---|---|---|
|changes|PASS|All flags full/backend/web/brand=true for PR to main.|
|backend|FAIL|`timeout 480 uv run pytest tests -n 4`: exit124 after 480.095s. 3668 collected; last progress 94%. No final test/pass/subtest summary.|
|browser|PASS|179 passed; no skips/flaky reported; command 109.347s. Two workers, up to two configured retries, original config, bundled Chromium. Host bootstrap limitation below.|
|web|PASS|Fresh npm ci, npm audit --audit-level=high, typecheck and build passed.|
|brand-assets|PASS|Fresh brand venv/install;216 assets/eight semantic AA pairs passed.|
|extras|PASS|Maintained-doc graph and source/diff checks passed; not separate workflow jobs.|

## Backend failure and completed checks

The exact configured480-second pytest gate returned exit124 at 480.095s. It collected3668 tests and stopped at about94% progress. A full result, remaining-test coverage, final skip count and subtest totals are unavailable because the process was terminated. One skip marker appears in partial progress. No individual assertion-failure summary was emitted. This does not establish a root cause or a passing suite. No longer timeout, selective passing replacement or source fix was used.

Before the gate, locked uv sync/export, pinned pip-audit2.10.1 backend/brand audits, Ruff, format check, mypy, fresh migration upgrade and metadata drift check all passed. Mypy checked190 source files; formatting checked425 files. Backend audit:47 entries/zero vulnerabilities. Brand dependency audit:13/zero.

## Browser/bootstrap result and platform limits

The original repository Playwright configuration ran with CI=true,179 regression tests,2 workers and2 configured retries. Exact bundled browser153.0.8010.12 (revision1243) installed and launched; no system Chromium substitute or temporary config override was used. The regression workload passed. Local real authentication used a fresh disposable application database and newly generated ephemeral credentials; all other data was isolated fixtures. Retained-source and commercial-real projects are excluded by the workflow, not silently claimed tested.

**Full GitHub runner bootstrap equivalence is BLOCKED/not reproduced on this host.** GitHub runs ubuntu-latest and rewrites an Azure apt mirror before `playwright install --with-deps chromium`. This cloud is Debian13. We installed exact Chromium with `npx playwright install chromium`; an extra `npx playwright install-deps --dry-run chromium` failed (exit1): unreadable `/etc/apt/apt.conf.d/80-applied-apt-retries` and unavailable apt candidates including xvfb/font packages. No privileged package installation, permission bypass or host config change was attempted. Bundled-browser smoke and all179 tests passed on existing host libraries. This is a local test-equivalent PASS with an explicit provisioning limitation, not a byte-identical Ubuntu CI run.

Checkout, Actions cache and artifact-upload service actions were not run locally. Fresh logs replace uploaded artifacts. Backend/browser databases used separate fresh PostgreSQL18.6 containers at127.0.0.1:5432 with workflow database/user names and cryptographically generated ephemeral credentials; both containers are stopped. Jobs ran sequentially, with no browser/typecheck workload competing during backend pytest. Configured backend15m/browser20m/brand5m budgets were retained; local changes/web safety caps were5m/20m, stricter than their unspecified workflow defaults and not reached.

Versions: Python3.11.16; Node22.23.4; npm11.9.0; uv0.12.19; pytest9.1.1; pytest-xdist3.8.0; Playwright1.63.0; Chromium153.0.8010.12; PostgreSQL18.6. Workflow pins Node22/Python3.11 and dependency files, not exact npm/uv micro versions. Writable cache locations and provided CA trust were selected for this cloud; TLS remained enabled. Browser safety additionally cleared Firecrawl credentials. Backend used workflow defaults, including no WORKER_AUTO_REFRESH override.

## Dependency threshold

The configured npm high-severity threshold passed with three moderate development-tool entries through minimatch/Redocly/openapi-typescript. Its suggested force fix is a breaking downgrade; no dependency or code change was made. This is not a zero-advisory npm result.

## Exact executed commands

Every command, working directory, exit status and runtime is in results.json; full output is in the linked job/step logs. Ephemeral secret-generation values were never logged. Key equivalents use the exact workflow flags; output destinations are local.

|Job/step|Command|Exit|Seconds|
|---|---|---:|---:|
|changes/classify|`bash /workspace/local-ci-pr160-20261031-1644/changes/classify.sh`|0|0.004|
|backend/start-postgres|`docker --host=unix:///var/run/docker.sock run -d --name gl3-local-ci-pr160-backend-1644 -e POSTGRES_USER=gridlens -e POSTGRES_PASSWORD -e POSTGRES_DB=gridlens -p 127.0.0.1:5432:5432 postgres:18.6`|0|4.876|
|backend/versions|`bash -c backend/.venv/bin/python --version; uv --version; node --version; npm --version`|0|0.166|
|backend/uv-sync|`uv sync --locked --extra dev`|0|0.032|
|backend/export|`uv export --locked --extra dev --no-emit-project --format requirements-txt --output-file /workspace/local-ci-pr160-20261031-1644/backend/requirements.txt`|0|0.016|
|backend/dependency-audit|`uv tool run --python 3.11 --from pip-audit==2.10.1 pip-audit -r /workspace/local-ci-pr160-20261031-1644/backend/requirements.txt --disable-pip --no-deps --format json`|0|5.229|
|backend/brand-dependency-audit|`uv tool run --python 3.11 --from pip-audit==2.10.1 pip-audit -r tools/brand/requirements.txt --format json`|0|9.641|
|backend/ruff|`uv run ruff check src tests`|0|0.064|
|backend/format|`uv run ruff format --check src tests`|0|0.032|
|backend/mypy|`uv run mypy src`|0|42.936|
|backend/migration-upgrade|`uv run alembic upgrade head`|0|1.417|
|backend/migration-drift|`uv run alembic check`|0|1.367|
|backend/create-test-database|`docker --host=unix:///var/run/docker.sock exec gl3-local-ci-pr160-backend-1644 psql -U gridlens -d gridlens -c CREATE DATABASE gridlens_test`|0|0.165|
|backend/pytest|`timeout 480 uv run pytest tests -n 4`|124|480.095|
|browser/start-postgres|`docker --host=unix:///var/run/docker.sock run -d --name gl3-local-ci-pr160-browser-1644 -e POSTGRES_USER=gridlens -e POSTGRES_PASSWORD -e POSTGRES_DB=gridlens -p 127.0.0.1:5432:5432 postgres:18.6`|0|7.142|
|browser/uv-sync|`uv sync --locked --extra dev`|0|0.064|
|browser/migration-upgrade|`uv run alembic upgrade head`|0|1.367|
|browser/npm-ci|`npm ci --prefix web`|0|4.384|
|browser/install-chromium|`npx playwright install chromium`|0|29.960|
|browser/host-dependencies-dry-run (extra/platform)|`npx playwright install-deps --dry-run chromium`|1|0.817|
|browser/bundled-browser-smoke (extra/platform)|`node -e const{chromium}=require('playwright');(async()=>{console.log('executable',chromium.executablePath());const b=await chromium.launch();console.log('browser',await b.version());await b.close()})().catch(e=>{console.error(e);process.exit(1)})`|0|1.319|
|browser/regression|`npm run test:ci --prefix web`|0|109.347|
|web/npm-ci|`npm ci --prefix web`|0|4.436|
|web/npm-audit|`npm audit --prefix web --audit-level=high`|0|1.069|
|web/typecheck|`npm run typecheck --prefix web`|0|5.797|
|web/build|`npm run build --prefix web`|0|8.225|
|brand-assets/venv|`uv venv .venv-brand`|0|0.016|
|brand-assets/install|`uv pip install --python .venv-brand/bin/python -r tools/brand/requirements.txt`|0|0.465|
|brand-assets/validate|`.venv-brand/bin/python tools/brand/validate.py`|0|1.168|
|extras/maintained-docs (extra/platform)|`uv run --project backend python scripts/check_docs.py`|0|0.115|
|extras/diff-check (extra/platform)|`git diff --check`|0|0.016|
|extras/source-status (extra/platform)|`git status --porcelain`|0|0.017|

## Scope, setup receipt and final integrity

The initial external orchestration helper failed to create its output directory before any CI command ran. Only that helper outside the repository was corrected; bootstrap-failure.log preserves the error. This was not an application-code fix or a repeated passing test substitution.

Additional AGENTS check: `uv run --project backend python scripts/check_docs.py`;91 maintained documents/362 local targets/3 anchors passed. `git diff --check` and final source status were clean. Remote branch head was verified unchanged at78591b308aa829a25157bf3310133ed069434d3b after the run. No commit/push, PR approval, merge, deployment, production access, ingestion/backfill or paid call was performed. No automatic approval denial occurred; the host apt dry-run failure is an environment limitation.

Receipt root: `/workspace/local-ci-pr160-20261031-1644`
Files: REPORT.md, metadata.json, results.json, progress.log, run.py, bootstrap-failure.log; per-job command logs; browser/playwright-report and browser/test-results. Browser binaries are setup assets, not report deliverables.
