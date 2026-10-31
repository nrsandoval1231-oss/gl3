# Fresh local validation — PR161

Commit: `49fe43805a2d31a2253521946dcbd2f08e901ced`
Tree: `2ec4e47c9628501ca68b326f5c345bdd0fac08e6`
Workflow SHA-256: `8dd1a97a4c1f1006aa3bb3a2e36562fb75c5b2ddb1ace68bec2e30214675d38c`
Started: 2026-10-31T18:46:04.630986+00:00
Completed: 2026-10-31T18:55:34.379500+00:00

**All local workflow test/check workloads passed. Full Ubuntu runner provisioning was not reproduced.** This is a fresh requested run, not reuse of earlier passing receipts. No source fixes or external repository writes occurred.

| Job | Result | Actual receipt |
|---|---|---|
|Changes|PASS|PR targeting main selects full/backend/web/brand.|
|Backend|PASS|3686 passed, 1 skipped, 11 warnings in 323.97s (0:05:23); process 325.114s, exit0.|
|Browser workload|PASS|179 passed (1.8m); command 110.518s, exit0.|
|Web|PASS|Fresh npm ci; high-severity audit gate; typecheck and production build.|
|Brand assets|PASS|Fresh isolated tool environment; 216 assets and eight semantic AA pairs.|
|Additional repository checks|PASS|93 maintained documents / 372 targets / three anchors; diff and clean source status; changed-script lint/format.|

## Backend and isolation

Exact backend test command: `timeout 480 uv run pytest tests -n 4`, working directory `/workspace/gl3-recovery/backend`. Collected3687tests. Final actual result:3686 passed, 1 skipped, 11 warnings in 323.97s (0:05:23). No deadline, assertion, worker-count or fixture reduction. No browser/typecheck/brand workload competed during this gate. One test skipped; the bare CI output does not identify it or its reason, so no skip explanation is invented. Eleven warnings are retained in full output.

Fresh disposable PostgreSQL18.6 containers were created separately for backend and browser. Application/test settings used only local addresses and ephemeral test credentials; secrets were not logged. Existing network guards/provider-key clearing and browser budget-zero controls remained active. Migrations upgraded a fresh database and drift check passed. Containers are stopped; no production data/session/host was accessed.

## Browser provisioning limitation

The exact bundled Chromium153.0.8010.12 launched and179browser tests passed under the original repository config (CI=true, two workers, up to two configured retries). Full log reports no flaky/failed/skipped test summary. Retained-corpus and commercial-real projects excluded by that config are not claimed as tested live coverage.

The separate platform probe `npx playwright install-deps --dry-run chromium` **failed**, exit1: apt could not read `/etc/apt/apt.conf.d/80-applied-apt-retries` and lacked xvfb/font package candidates. This Debian13 host is not GitHub ubuntu-latest. We used `npx playwright install chromium` and verified launch with existing shared libraries; we did not run privileged package installation, rewrite apt configuration, bypass denial, or claim exact Ubuntu provisioning. This failed extra probe is preserved in browser/host-dependencies-dry-run.log.

Checkout/cache/artifact-upload Actions services were not reproduced locally. Local logs replace artifact upload. Backend15m/browser20m/brand5m job limits were retained; changes/web/extras had local safety caps. Workflow executables used Python3.11.16, Node22.23.4, npm11.9.0, uv0.12.19, pytest9.1.1, xdist3.8.0 and Playwright1.63.0. Pins/flags and actual command receipts are below; this is a cloud-local workload validation with stated platform differences.

## Dependencies and preserved history

Fresh locked backend and brand dependency audits passed. npm audit passed its configured `--audit-level=high` gate with **three moderate development-tool vulnerabilities** in the minimatch/Redocly/openapi-typescript chain. No force fix or dependency change was applied. Lint/format/type/docs and build outputs are retained, including non-error mypy notes.

The previous480.095second local timeout remains an unexplained failed historical receipt. This fresh323.97second backend pass and earlier passes do not establish its cause or erase it. No repeated-until-green loop was performed for this request.

## Exact commands and receipts

Every command argument vector, cwd, exit and runtime is in results.json; changed-script extras are in post-checks.json. Values below are actual results.

| Job/step | Command | Exit | Seconds |
|---|---|---:|---:|
|changes/classify|`bash /workspace/local-ci-pr161-20261031-1845/changes/classify.sh`|0|0.004|
|backend/start-postgres|`docker --host=unix:///var/run/docker.sock run -d --name gl3-local-ci-pr161-backend-1845 -e POSTGRES_USER=gridlens -e POSTGRES_PASSWORD -e POSTGRES_DB=gridlens -p 127.0.0.1:5432:5432 postgres:18.6`|0|3.084|
|backend/versions|`bash -c backend/.venv/bin/python --version; uv --version; node --version; npm --version`|0|0.217|
|backend/uv-sync|`uv sync --locked --extra dev`|0|0.032|
|backend/export|`uv export --locked --extra dev --no-emit-project --format requirements-txt --output-file /workspace/local-ci-pr161-20261031-1845/backend/requirements.txt`|0|0.016|
|backend/dependency-audit|`uv tool run --python 3.11 --from pip-audit==2.10.1 pip-audit -r /workspace/local-ci-pr161-20261031-1845/backend/requirements.txt --disable-pip --no-deps --format json`|0|2.973|
|backend/brand-dependency-audit|`uv tool run --python 3.11 --from pip-audit==2.10.1 pip-audit -r tools/brand/requirements.txt --format json`|0|8.035|
|backend/ruff|`uv run ruff check src tests`|0|0.064|
|backend/format|`uv run ruff format --check src tests`|0|0.032|
|backend/mypy|`uv run mypy src`|0|40.741|
|backend/migration-upgrade|`uv run alembic upgrade head`|0|1.370|
|backend/migration-drift|`uv run alembic check`|0|1.418|
|backend/create-test-database|`docker --host=unix:///var/run/docker.sock exec gl3-local-ci-pr161-backend-1845 psql -U gridlens -d gridlens -c CREATE DATABASE gridlens_test`|0|0.215|
|backend/pytest|`timeout 480 uv run pytest tests -n 4`|0|325.114|
|browser/start-postgres|`docker --host=unix:///var/run/docker.sock run -d --name gl3-local-ci-pr161-browser-1845 -e POSTGRES_USER=gridlens -e POSTGRES_PASSWORD -e POSTGRES_DB=gridlens -p 127.0.0.1:5432:5432 postgres:18.6`|0|6.782|
|browser/uv-sync|`uv sync --locked --extra dev`|0|0.065|
|browser/migration-upgrade|`uv run alembic upgrade head`|0|1.318|
|browser/npm-ci|`npm ci --prefix web`|0|3.685|
|browser/install-chromium|`npx playwright install chromium`|0|0.766|
|browser/host-dependencies-dry-run (extra/platform)|`npx playwright install-deps --dry-run chromium`|1|0.768|
|browser/bundled-browser-smoke (extra/platform)|`node -e const{chromium}=require('playwright');(async()=>{console.log('executable',chromium.executablePath());const b=await chromium.launch();console.log('browser',await b.version());await b.close()})().catch(e=>{console.error(e);process.exit(1)})`|0|0.521|
|browser/regression|`npm run test:ci --prefix web`|0|110.518|
|web/npm-ci|`npm ci --prefix web`|0|4.685|
|web/npm-audit|`npm audit --prefix web --audit-level=high`|0|1.068|
|web/typecheck|`npm run typecheck --prefix web`|0|5.851|
|web/build|`npm run build --prefix web`|0|8.039|
|brand-assets/venv|`uv venv .venv-brand`|0|0.033|
|brand-assets/install|`uv pip install --python .venv-brand/bin/python -r tools/brand/requirements.txt`|0|0.466|
|brand-assets/validate|`.venv-brand/bin/python tools/brand/validate.py`|0|1.218|
|extras/maintained-docs (extra/platform)|`uv run --project backend python scripts/check_docs.py`|0|0.115|
|extras/diff-check (extra/platform)|`git diff --check`|0|0.008|
|extras/source-status (extra/platform)|`git status --porcelain`|0|0.016|
|extra/changed-scripts-lint|`.venv/bin/ruff check ../scripts/stage_release_wrapper.py ../scripts/rehearse_release.py`|0|0.032|
|extra/changed-scripts-format|`.venv/bin/ruff format --check ../scripts/stage_release_wrapper.py ../scripts/rehearse_release.py`|0|0.016|

## Final integrity and remaining gates

Local and remote feature heads remain49fe43805a2d31a2253521946dcbd2f08e901ced; source checkout is clean. No source edits, commits, pushes, PR changes, hosted-CI dispatch, production action, ingestion/backfill, paid call or PC use occurred during this validation. Existing PR161 is unchanged; deployment remains held.

No automatic approval denial or uncertain mutation occurred. Known failed action: local apt simulation, with the exact environmental errors above. Full Ubuntu bootstrap equivalence remains unavailable; production/live rollback and authenticated performance are outside this local validation.

Artifact root: `/workspace/local-ci-pr161-20261031-1845`. Files: REPORT.md, metadata.json, results.json, post-checks.json, run.py, summarize.py, final-source-status.txt; per-job command logs and browser test/report artifacts.
