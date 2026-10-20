# Operational scripts

- `setup_local.py` creates ignored native-runtime credentials from `.artifacts/local-postgres/connection.env` or process `DATABASE_URL`/`TEST_DATABASE_URL` when passed `--use-environment`; it refuses to replace existing credentials unless passed `--force`.
- `setup_compose.py` creates separate ignored Compose credentials and `.artifacts/compose-auth.txt`; it also refuses silent credential rotation.
- `export_openapi.py` exports typed FastAPI response schemas to `web/src/api/openapi.json`; run `npm run generate:api` in `web` to refresh TypeScript types.

The worker and optional managed scheduler share the application queue services rather than duplicating qualification logic.

## Captured buying-chain acceptance

`validate_buying_chain_captures.py` replays the five retained real-source captures
through the production buying-chain parser, extraction, and persistence code. It
reconstructs the three existing GL3-016 corpus identities in a disposable schema
of the separate `TEST_DATABASE_URL` database. It commits, reloads, and repeats each
pass, checking candidate identity, exact citations, unchanged counts, and unchanged
Signal/power fields. No organization or person claim is seeded.

With PostgreSQL running and the backend environment configured:

```bash
uv run --project backend python scripts/validate_buying_chain_captures.py \
  --captures /path/to/retained-capture-directory
```

The capture directory must contain `manifest.json` and its unedited five body
files. Their SHA-256 hashes must match the manifest. Keep full source captures
outside Git. `--repo` defaults to this checkout; `--output` defaults to
`docs/validation/gl3-017-real-acceptance.json`. The report preserves prior attempt
summaries. Exit status is nonzero on any failed acceptance check. This verifies
captured-source processing only, not direct live-network or browser operation.

## Runtime inspection and recovery

Use `uv run --project backend python -m gridlens.jobs.runtime` from the repository root. `status` reads registry drift, source health, content counts and backlog without changing the database. `reconcile` updates/inserts registry definitions while retaining existing health, jobs and content. `check --source SOURCE_ID` (repeat the flag for multiple sources) attempts each selected source once through the normal fenced worker. It reuses active jobs, honors retry backoff/live leases, and leaves unrelated jobs untouched. Exit 0 means every selected job was attempted successfully; exit 1 includes failed or deferred jobs; exit 2 reports invalid input or runtime setup failure.

See [runtime recovery](../docs/operations/runtime-recovery.md) for startup and validation boundaries. These commands do not deploy a scheduler or establish daily reliability.

## Isolated synthetic browser acceptance

`seeded_browser_acceptance.py` creates a uniquely named `gl3_synthetic_browser_*`
PostgreSQL database using the existing configured database account, applies the
current migrations, then seeds explicitly synthetic source-shaped fixtures through
canonical permit rendering, ingestion, evidence admission and pursuit research.
It never installs fixtures into the ordinary application database or shared test
database. It refuses a nonempty seed target and occupied API/web ports. The worker
uses fixture acquisition; model credentials are disabled for this run.

```bash
PLAYWRIGHT_BROWSERS_PATH=/path/to/installed/playwright \
UV_CACHE_DIR=/tmp/uv-cache uv run --directory backend \
  python ../scripts/seeded_browser_acceptance.py --full-suite
```

Omit `--full-suite` to run the six existing authenticated browser scenarios in
`first_path.spec.ts` and `pursuits.spec.ts`, unchanged. Requires an installed
Chromium, existing workspace authentication (`GRIDLENS_TEST_PASSWORD` or the
existing private `.artifacts/local-auth.txt`), and a database role allowed to
create an isolated database. Ports default to 8137/5237 and can be overridden.
No credentials are generated. Each run retains its database, migration/seed/worker
logs, browser results/screenshots and candidate manifest under
`.artifacts/synthetic-browser/` for inspection; no database is automatically dropped.

This proves application workflows with **synthetic fixtures only**. The existing
test names contain “live”/“real” because they ordinarily expect a populated runtime;
passing them here does **not** establish live-source acceptance, the retained PR23
corpus, or production operation. Source URLs in fixtures identify adapter formats,
not claims that those pages supplied the synthetic facts.
