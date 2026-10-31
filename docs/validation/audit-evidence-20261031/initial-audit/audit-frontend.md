# Frontend audit — current main 593cfd516d82a12b66558f53b975ad6c2b711517

Read-only review and local synthetic browser QA on `/workspace/gl3-audit-main`; no production sessions, writes, providers, ingestion or repository code changes. Original saved checkout d54646c was discovered stale; original type/build receipts are not used as current-main proof. Relevant AGENTS and canonical product/UI/architecture/checkpoint/finish documents read. `.agents/skills` is absent in this snapshot.

## Validated findings

### P2 — Sort control sorts only 25 loaded rows, so the paginated result is not globally sorted

`web/src/features/workspace/CanonicalOpportunityResults.tsx:106` always requests `sort: 'priority'`, while line 150 sorts only `items` in browser for Company, Project and ascending Priority. The control at line 161 is labeled simply Sort; neither URL nor server cohort includes chosen client sort. A 26-project fixture has Zebra projects occupying server priority page 1 and Aardvark occupying page 2. Selecting Company shows Zebra first; Next shows Aardvark. Network requests remain `sort=priority`. This can hide the expected alphabetically earliest or lowest-priority project behind another page and makes export order inconsistent with a user's whole-cohort sort expectation. Recommend implement server-supported stable whole-cohort sort with cohort token and offset reset; until then label explicitly as current-page sort and avoid implying global ranking.

Reproduce: start Vite on 5193, run `node /workspace/audit-evidence/frontend/reproduce-final.mjs`. Synthetic input and full observed network requests are saved in that harness and `reproduce-final.json`. This is local deterministic evidence, not authenticated live record evidence.

### P3 — Phone opportunity list requires contained horizontal table scrolling

`web/src/features/workspace/canonical-opportunity-results.css:7` sets `.cfr-table{min-width:800px}` below 760px; line 6 makes its container `overflow:auto`. Current canonical overrides do not remove the minimum. At 390×844, measured scrollport clientWidth344 and scrollWidth808; document width remains390, meaning existing tests asserting only document width pass while the table itself still scrolls horizontally. Company names appear at the left while power/timing/stage/priority/open controls require sideways travel. This conflicts with canonical scannable phone rows/cards and no horizontal scroll, and adds sideways travel on mobile. The scroll is contained and the document itself does not overflow; no inaccessible flow was demonstrated. Independent review classifies this as a P3 usability limitation. Recommend a stacked mobile row/card presentation or responsive column priority with an accessible full detail action always visible.

Evidence: `mobile-table.png`, `reproduce-final.json`. No claim about live authenticated layout: that remains the parent's separate live coverage.

### P3 — Filtered pages can show an impossible pagination range

`web/src/features/workspace/CanonicalOpportunityResults.tsx:180` combines unfiltered offset and total with filtered visible length. Using the same fixture: Next → Region Dallas → Previous leaves current-page filter Dallas active while no page-1 records match and displays **1–0 of 26 projects**. Empty filtered later pages produce similar reversed/incorrect intervals. Current-page filter scope is documented in a small label/tooltip (the long scope sentence is hidden by `web/src/styles/canonical-workspace.css:25`), so this finding is the invalid range itself rather than a claim that all filters are intended to be global. Recommend render explicit visible-on-page count separate from unfiltered cohort page range and honest empty state.

Evidence: `filter-empty-page.png`, `reproduce-final.json`.

## Verification

- `npm run typecheck --prefix web` at current main: PASS. `/workspace/audit-evidence/frontend/main-typecheck.log`.
- `npm run build --prefix web` at current main: PASS, Vite6.4.5, 2077 modules, CSS101.75kB / JS422.48kB. `main-build.log`.
- No frontend lint script or ESLint dependency exists in package.json; frontend lint is unavailable as a separate gate. TypeScript/build checked instead, not mislabeled lint.
- Fresh disposable PostgreSQL18.6 `gl3_audit_web` migrated through0049 using Alembic: PASS, `migration.log`. No retained data was copied.
- Full regression browser run: **PASS — 172 passed (4.4m;261.416s), exit0**. Corrected final receipt `full-browser-final.log`, structured stats `full-results.json` (172 expected,0 unexpected,0 skipped,0 flaky). Temporary config `/workspace/audit-evidence/frontend/playwright.full.config.mjs` preserves all regression tests, uses 2 workers, no retries, system `/usr/bin/chromium`, isolated backend8192/web5192, JSON reporter and external evidence output. Environment includes `GRIDLENS_WEB_PORT=5192`, `GRIDLENS_API_PORT=8192`, fresh local auth/session, COOKIE_SECURE=false, WORKER_AUTO_REFRESH=false, empty model keys and zero model budgets. All172 current regression tests completed, including genuine API authentication and mocked search, sector filtering, cohort pagination, evidence/contact truth and responsive history/detail flows.
- A preliminary mock-only run was intentionally interrupted after full isolated API environment became available; it is not a passing full suite. A first full attempt omitted GRIDLENS_WEB_PORT, causing tests that construct absolute interception URLs to miss requests; it was interrupted and is not product defect evidence. `invalid-port-browser.log` is retained solely as rejected setup coverage. The corrected run uses all required port variables.
- Live-acceptance first_path and commercial-real suites intentionally not run: their retained real-source manifests/corpus and active-worker expectations cannot be established in empty isolated test data without violating requested scope. Parent performs live read-only QA separately. Dedicated login Chrome-channel configuration duplicates mocked regression login scenarios but would require Google Chrome; regression uses installed Chromium and includes genuine API auth test.

## Examined and dismissed

A detail request omits include_signals. This is not a demonstrated Signal detail bug: `backend/src/gridlens/intelligence/project_results.py:78` explicitly enters discovery for any need_id. Existing source URL sanitization, conservative missing contact display, distinction between direct methods and generic company route, session cache clearing, count units, cohort token paging, and isolated need/detail navigation were inspected; broad coverage depends on final browser results, not this inspection.
