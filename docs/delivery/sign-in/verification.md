# Sign-in verification — 2026-11-11

Candidate base: current main `f2a4a805` (PR193). The implementation preserves the shared-password system following explicit owner confirmation. No backend, identity, credential, schema, cookie or authorization changes are included.

Current-base completed checks:
- `uv sync --locked --extra dev` — passed.
- `npm ci --prefix web` — passed.
- `npm run typecheck --prefix web` — passed.
- `npm run build --prefix web` — passed; existing application bundle exceeds Vite's 500 KB advisory threshold (534.46 KB uncompressed / 152.17 KB gzip).
- `npm audit --prefix web --audit-level=high` — zero vulnerabilities.
- Locked backend `pip-audit==2.10.1` — no known vulnerabilities.
- `uv run alembic upgrade head` / `uv run alembic check` — passed on task-owned disposable database through schema0054; no schema drift.
- `uv run ruff check src tests` — passed.
- `uv run ruff format --check src tests` — 585 files already formatted.
- Astra independent `npm run typecheck` and login suite — 14 passed; see independent-review.md.

In progress: full backend suite (5,351 tests), full frontend regression, backend authentication checks, docs graph and mypy final output. Final results will replace this status before handoff.

Local execution uses a fresh loopback-only PostgreSQL 17.11 cluster on port5543 with separate task-owned app/test databases. CI uses PostgreSQL18.6 and remains the exact-version gate. No retained or production data or external paid providers are used. `scripts/check.ps1` cannot run directly because PowerShell is unavailable; equivalent checks are executed individually. Operational live-source acceptance is not established by these isolated tests.

Superseded: initial runs on stale checkout `d54646` were interrupted after discovering current main. They are not current-candidate evidence. That baseline had backend failures and an old pypdf advisory; current main updates pypdf to6.21.4 and its dependency audit is clean. One old-baseline frontend pending-request logout race passed in isolation; current-base full regression supersedes that result.
