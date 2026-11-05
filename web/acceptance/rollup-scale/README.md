# Real-backend customer rollup lane

This opt-in lane uses only a lead-created, migrated, loopback PostgreSQL database whose name contains `_rollup_scale_` and ends in `_test`. The seeder refuses any other database and any populated schema. It adds synthetic rows through the shared backend fixture; it does not create or alter tables.

The lead starts a separate API and Vite stack with provider credentials absent, all provider budgets at zero, and `WORKER_AUTO_REFRESH=false`. Use distinct loopback ports, for example API `18191` and web `15293`. No external requests are part of this lane.

From `release/backend`, run `uv run python ../web/acceptance/rollup-scale/seed.py --manifest-output <local-json-path>` with `DATABASE_URL` set to the dedicated disposable database and `TEST_DATABASE_URL` set to a different database. The manifest contains synthetic target identifiers and counts only. It never contains the test password. Set `CUSTOMER_ROLLUP_REAL_PASSWORD` separately for browser login.

Run the one dedicated browser spec from `release/web` with `CUSTOMER_ROLLUP_REAL=1`, `CUSTOMER_ROLLUP_REAL_WEB_ORIGIN=http://127.0.0.1:15293`, `CUSTOMER_ROLLUP_REAL_MANIFEST=<manifest-path>`, and `CUSTOMER_ROLLUP_REAL_PASSWORD=<dummy-password>` using `npx playwright test -c playwright.rollup-real.config.ts`. The config refuses to load unless opted in and the web origin is loopback. Set `CUSTOMER_ROLLUP_REAL_START_STACK=1` to let Playwright start and stop separate uvicorn/Vite processes; this mode requires the lead’s isolated API database and zero-budget provider environment, disables server reuse, and uses the API port from `GRIDLENS_API_PORT` (default 18191).

The browser checks actual HTTP responses and browser resource timing at 1440×900, 768×1024, and 390×844. API response acceptance stays at 15 seconds. UI readiness is measured separately with a default 15-second budget that can be set explicitly through `CUSTOMER_ROLLUP_UI_READY_MS`. Traces and timing attachments are retained by Playwright. This lane has not been run unless a completion artifact records observed results.
