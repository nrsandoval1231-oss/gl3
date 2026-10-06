# Frontend tests

`npm run test:ci` runs the `regression` Playwright project: deterministic browser
tests for cards, filters, briefs, buying chains, pursuits, notes, and history, plus
a real API login/reload/logout check. Use a migrated disposable PostgreSQL
database and set `GRIDLENS_TEST_PASSWORD` to the password matching
`APP_PASSWORD_HASH`. Set `COOKIE_SECURE=false` for local HTTP. Playwright starts
the API and Vite; CI supplies fresh credentials, disables model budgets, and
never starts an ingestion worker. Install Chromium with
`npx playwright install --with-deps chromium` first.

`npm run test:live` runs `first_path.spec.ts` and `pursuits.spec.ts`. These six
acceptance tests require a populated real-source workspace and, for refresh,
its active worker. They inspect specific retained discoveries and can append
validation notes or queue research. Run them only against the intended local
acceptance workspace. A passing regression job does not prove live acquisition
or production operation. `npm test` still selects both projects.

Failed CI browser runs retain their HTML report and traces for seven days.
