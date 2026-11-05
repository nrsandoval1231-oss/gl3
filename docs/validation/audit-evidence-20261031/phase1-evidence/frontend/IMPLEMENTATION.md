# Phase 1 frontend reliability

Scope: `CanonicalOpportunityResults.tsx`, `Workspace.tsx`, `client.ts`, and new `canonical_cohort_sort.spec.ts`. Shared branch has other agents' backend/deployment changes; those are not claimed here. No commits or production activity.

Company, Project and ascending Priority now request the backend's complete cohort ordering; client code no longer sorts the loaded25 rows. Sort is validated from URL, included in cache key/request and preserved in cohort pagination, search/sector changes, selected need links, secondary navigation and browser Back. A sort change clears selected rows, resets offset and removes the previous cohort token. Priority column retains accessible ascending/descending state; the select exposes ascending Priority explicitly.

Filtered-page status now uses the unfiltered server page's range (e.g.1–25 of26) and separately reports visible matches (e.g.0 of25 on this page), avoiding1–0 when page filters yield no rows. Empty server pages beyond a smaller cohort show0projects on this page and the cohort total rather than an inverted range.

A regression discovered while implementing showed that browse-change `select(null)` called asynchronous browser history Back if desktop detail was selected, undoing new sorting. Browse changes now clear selected detail synchronously; explicit detail Back keeps its existing history behavior.

## Test-first evidence

- Five original new regressions watched fail against pre-change code (`red-browser.log`,5failed), then pass after implementation.
- Additional selected-desktop-detail sorting regression watched fail (`red-selected-sort.log`,sort reverted topriority), then pass after synchronous clearing.
- All7 focused tests passed (`green-browser-final-seven.log`,10.5s), including a new empty-server-page regression watched red before its footer fix (`red-empty-server-page.log`).
- TypeScript typecheck PASS (`typecheck-final.log`).
- Production build PASS (`build.log`,2077modules,CSS101.75kB gzip17.55kB,JS422.95kB gzip122.14kB).
- `git diff --check` PASS.
- Previous candidate full browser regression:178passed,0failed,0skipped,0flaky (`full-results-178.json`, `full-browser-178.log`). Final updated candidate179-test run PASS:179expected,0unexpected/0skipped/0flaky,143.090s (`full-results.json`, `full-browser.log`), using current worktree backend .venv.
- Fresh disposable `phase1_web` PostgreSQL database migrated through0049 (`migration.log`). Genuine API authentication included in full suite. No ingestion worker or paid providers; model keys blank and model budgets zero.
- Full suite config outside source changes only isolated ports5195/API8195, system Chromium executable, reporters/output and2workers/no retries. All maintained regression tests run. Retained-source first_path/commercial-real suites excluded because an empty synthetic test database cannot establish their required real corpus; no production permission is inferred.

React review: request effects include sort in primitive dependencies; current-page identity includes sort so old rows cannot masquerade as another ordered cohort; existing abort/sequence/session-clear safeguards remain; local filter derivation preserves server order; no extra packages, data waterfall or design change.

Review note: `WorkspaceFilters` legacy union is not widened because the legacy workspace endpoint retains its own contract. Canonical project-result sort has its own typed union. Parent owns generated OpenAPI/types and backend tests.
