# A5B page-transition repair handoff

The browse now treats a loaded opportunity page as valid only for its exact tier, search, decision, filters, and offset. When that key changes, card rows, decision totals, page counts, CSV export, and detail navigation are unavailable until the matching response settles. A failed replacement leaves an explicit error/unavailable state and does not claim that the cohort is empty.

The repair is limited to `web/src/app/App.tsx` and focused browser regressions in `web/tests/project_cards.spec.ts`. It preserves same-key request behavior, token bootstrap, cohort-change restart, selected-need Back restoration, and the existing request epoch guards.

## Validation evidence

- Original page-zero reproduction: RED; the page-25 card remained present after Previous requested offset zero. The failure log and trace are listed in `RAW_LOGS.json`.
- Focused page-transition tests: delayed replacement and failure in both directions passed.
- Complete focused `project_cards.spec.ts`: 27 passed, including existing Back/forward selected-need, stale-response, token, and same-key cases.
- Web typecheck and production build passed; `git diff --check` passed.

See `RAW_LOGS.json` for exact command receipts, log hashes, retained traces, the corrected 503 assertion attempt, and the non-retained shell preflight warning. No acceptance claim is made. Root exact-candidate gates and independent review remain required.

## Scope and authority

No backend, schema, authentication, provider, retained-corpus, original-data, style, release, push, merge, deploy, or A6 action was performed. Browser tests used fixture routes and synthetic non-production authentication with provider keys blank and automation disabled.
