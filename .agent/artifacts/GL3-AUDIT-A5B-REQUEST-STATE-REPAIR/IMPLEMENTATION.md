# A5B same-cohort request-state repair

Same-key browse actions no longer erase a valid page or invalidate its in-flight request. Clicking the active tier on its first page is a data no-op when no selection is open. From an open detail it closes the detail and returns to the same first-page list while preserving the page headers and browser-history behavior. The active view and active Signals decision are also no-ops; equal search and browse-filter values return before request invalidation.

Actions that do change the browse scope still advance the request epoch and trigger the normal effect. They clear old rows and page metadata before the new result arrives, so an old card cannot be opened under the new filter while its replacement request is pending. Opening or moving between exact records clears obsolete pending-restore bookkeeping without canceling a same-cohort page request. A page response can therefore finish loading and metadata updates without overriding the user's newer record selection. Pending exact-need hydration is skipped if its navigation intent was cleared before the page response.

## Regression coverage

The focused browser tests use valid page headers and delayed routes to verify ready and pending active-tier clicks, first-page reset from a later page, closing detail through the active tier, active Signals decision, same-value search/filter input, the active ingestion view, and opening then moving between two records while a Back-triggered same-cohort page request is unresolved. Assertions cover request counts, current CSV availability, pagination, route, selected title, and the loading status. Existing selected-need Back/direct-hash/off-page lookup, stale-token 409, changed-filter and rapid-navigation tests remain in the same focused file.

## Scope and validation

Product changes are limited to `web/src/app/App.tsx`; browser regressions are in `web/tests/project_cards.spec.ts`. No client API, backend, schema, auth, migration, qualification, styling, provider, or retained-data change was made. The copied packet and independent FIX receipt are byte-exact in this directory.

- `tests/project_cards.spec.ts`: 23 passed.
- `npm run typecheck`: exit 0.
- `npm run build`: exit 0.
- `git diff --check`: exit 0.

The first RED iterations include test-locator/expectation corrections; those bytes are retained and classified in `RAW_LOGS.json`. One same-value filter fixture passes before product repair because filling an input with its existing value emits no browser change event; the equality guard remains as a defensive same-key boundary. Full A5B/root gates and independent review of the resulting candidate remain pending.
