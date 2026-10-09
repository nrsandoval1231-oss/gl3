# A5B Back-selection repair

This repair carries a selected need as an explicit navigation intent instead of resolving it from whichever tier/page happens to be in memory. On Back/forward and direct selected URLs, the client restores the URL/history scope, bootstraps page zero when an offset page needs a cohort token, then resolves the exact ID from that page or a scoped exact-need GET. The GET carries tier, search, decision, browse filters, and the current cohort token. A missing need clears the selected hash and reports an unavailable state; stale cohort responses keep the existing 409 page-one restart behavior. Request and navigation sequence guards prevent late page/detail responses from replacing a newer destination.

The back/forward regression covers a selected Signal on offset 25, transition to Prospects, restoration of the exact Signal citation and filter/offset/hash, page-zero token bootstrap, focus restoration, and forward navigation. Additional regressions cover exact scoped hydration when the selected row moved off-page, truthful 404 behavior without substituting an unrelated row, and a delayed response racing a newer navigation. Existing filter/history and stale-cohort cases remain in the focused file.

## Scope

Changed source files are `web/src/app/App.tsx`, `web/src/api/client.ts`, and `web/tests/project_cards.spec.ts`. No backend, public schema, migration, authentication, qualification, styling, provider, or retained-data changes were made. Packet and review receipt are copied byte-exact in this directory.

## Focused validation

- Playwright: `tests/project_cards.spec.ts`, 14 passed.
- Web typecheck: `npm run typecheck`, exit 0.
- Web build: `npm run build`, exit 0.
- `git diff --check`, exit 0.

One browser launch failed before collection because the first command used the wrong Playwright port variable names; the preserved raw log identifies the occupied default port. A corrected launch used unique ports and passed. The initial RED regression run is also retained, with the two intended selection-restoration failures. See `RAW_LOGS.json` for exact paths, hashes, and status.

These are focused builder checks only. Full repository, retained-corpus, fresh migration, and independent review gates remain with the controller.
