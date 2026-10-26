# Frontend tests

`npm run test:ci` runs the `regression` Playwright project: deterministic browser
tests for opportunity/account navigation and filters, evidence and buying chains,
automated research, unified search, mobile layouts and history, plus a real API
login/reload/logout check. Retired manual mutations must remain absent. Use a
migrated disposable PostgreSQL database and set `GRIDLENS_TEST_PASSWORD` to the
password matching `APP_PASSWORD_HASH`. Set `COOKIE_SECURE=false` for local HTTP.
Playwright starts the API and Vite; CI supplies fresh credentials, disables model
budgets, and never starts an ingestion worker. Install Chromium with
`npx playwright install --with-deps chromium` first.

`npm run test:live` runs the four read-only `first_path.spec.ts` acceptance tests.
They require the specified populated real-source workspace, including retained
Texas and out-of-region evidence. An empty or differently populated database
cannot establish that gate. They do not append notes, enter facts, or trigger
research. `npm test` selects both projects. Passing deterministic browser tests
does not prove live acquisition, contact coverage, or production operation.

The separate login configuration exercises the same login scenarios against a
Chrome installation; the regression project already includes those scenarios in
Chromium. Failed CI browser runs retain their HTML report and traces for seven
days. All synthetic fixtures and screenshots remain test evidence, never live
opportunity or contact claims.
