# Sign-in verification — 2026-11-11

Candidate base: current main `f2a4a805` (PR193). The implementation preserves the shared-password system following explicit owner confirmation. No backend, identity, credential, schema, cookie or authorization changes are included.

Current-base completed checks:
- `uv sync --locked --extra dev` — passed.
- `npm ci --prefix web` — passed.
- `npm run typecheck --prefix web` — passed.
- `npm run build --prefix web` — passed; existing application bundle exceeds Vite's 500 KB advisory threshold (534.46 KB uncompressed / 152.17 KB gzip).
- `npm audit --prefix web --audit-level=high` — zero vulnerabilities.
- Locked backend `pip-audit==2.10.1` — no known vulnerabilities.
- `uv run alembic upgrade head` / `uv run alembic check` — passed on task-owned disposable database through schema 0056; no schema drift.
- `uv run ruff check src tests` — passed.
- `uv run ruff format --check src tests` — 585 files already formatted.
- Astra independent `npm run typecheck` and login suite — 14 passed; see independent-review.md.

- `uv run mypy src` — passed, 266 source files.
- `uv run python ../scripts/check_docs.py` — passed, 112 maintained documents / 540 local targets / 18 anchors.
- Backend authentication suite (`test_auth_persistence.py`, `test_api_auth.py`, `test_security.py`, `test_origin.py`) — 17 passed.
- `uv run --project backend pytest web/acceptance/pursuits-release/test_seed_safety.py -q` — 32 passed.

Full-suite/acceptance outcomes and current-head CI status are recorded in [PR194](https://github.com/nrsandoval1231-oss/gl3/pull/194), which is the final delivery receipt. A scoped pass does not imply those wider suites passed. The PR remains draft; no merge or deployment is authorized.

Local execution uses a fresh loopback-only PostgreSQL 17.11 cluster on port 5543 with separate task-owned app/test databases. CI uses PostgreSQL 18.6 and remains the exact-version gate. No retained or production data or external paid providers are used. `scripts/check.ps1` cannot run directly because PowerShell is unavailable; equivalent checks are executed individually. Operational live-source acceptance is not established by these isolated tests.

Superseded: initial runs on stale checkout `d54646` were interrupted after discovering current main. They are not current-candidate evidence. That baseline had backend failures and an old pypdf advisory; current main updates pypdf to 6.21.4 and its dependency audit is clean. One old-baseline frontend pending-request logout race passed in isolation; current-base full regression supersedes that result.

## Full CI receipt before final decorative polish

[CI run 43103472805](https://github.com/nrsandoval1231-oss/gl3/actions/runs/43103472805), exact head `d0887f90a683dbaf6f12c1a33fef6bc2071d4ebe`, passed every job on PostgreSQL 18.6:
- Backend: **5,350 passed, 1 skipped**, 632.05 seconds.
- Browser regressions including real authentication: **335 passed**, 2.7 minutes, no retries/flaky count reported.
- Seeder safety: **32 passed**.
- Real rollup acceptance: **3 passed**.
- Persisted Pursuits acceptance: **1 passed**.
- Phase 2 brief acceptance: **1 passed**.
- Web build/typecheck/audit, backend lint/types/migrations/audits and brand-assets jobs: passed.

Only the decorative photo and its gradient wash changed afterward; final primary login verification passed **14/14**, 19.2 seconds, and Astra approved the final fresh captures. Final-head CI status is linked from PR194 rather than inferred from this earlier run.

Local wider results differ from CI and remain disclosed: frontend regression **334 passed, 1 failed** (`project_results.spec.ts` — mounted account project details and contacts disappear at their independent generation expiry). The same test fails on an untouched export of `f2a4a805`. Local persisted Pursuits timed out in the repeated Companies search loop; its baseline attempt failed at an earlier Add-to-Pursuit assertion, so the exact timeout is not claimed reproduced. Both journeys pass in the full CI run above. Local real rollup **3 passed**; local Phase 2 brief **1 passed**. The complete local backend outcome is recorded in the PR delivery receipt; no backend source changed in this PR.

Browser-rendered final 1280px initial sign-in check: logo and background decoded, no horizontal overflow, no console errors. This is separate from intentional network/credential errors exercised by the automated suite.
