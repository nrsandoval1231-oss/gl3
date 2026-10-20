# AUDIT-CALL-PREFLIGHT completion

- Base: c847babe61756058fbaef98cab209561ef6d6bf4
- Source commit: 58813912231d8ddd2aa6b0d155bfa54791fe1ed
- Objective: validate unsuitable-supply MW before any quick-call fact writes.
- Changes: local validation requires one finite positive unsuitable-supply MW no greater than the API maximum; suitable-supply behavior is unchanged. Browser coverage verifies zero causes zero POSTs and corrected positive input saves demand, timing, buyer and unsuitable supply as drafts, then accepts all four explicitly.
- Validation (worktree gl3-audit-call-preflight-20261020):
  - 
pm ci — exit 0 (locked dependencies).
  - 
pm run typecheck — exit 0.
  - 
px playwright test tests/environment.spec.ts -g "one call logs several facts" with local placeholder DATABASE_URL, APP_PASSWORD_HASH, and SESSION_SECRET — exit 0; 1 passed.
  - git diff --check — exit 0.
- Initial browser attempt without required local env — exit 1 before app startup; rerun with placeholder local settings succeeded. No external/provider effects.
- Retry count: 1 test adjustment after validator-order evidence.
- UTC completion recorded: 2026-10-20T20:35:20Z
- Tokens, start time, duration and model config identity: UNKNOWN.
- Scope: UI and focused browser regression only; no backend/schema/production changes.

## Second bounded preflight pass

- Source commit: `6d125eb2341578c7d971f6d6b6757af1e6abb4cd` (on prior source commit `b58813912231d8ddd2aa6b0d155bfa54791fe1ed`).
- Added preflight for API-bounded duration, calendar date, buyer organization, contact fields, location, note length, and the canonical MW scalar/range constraints. Suitable supply zero remains valid; unsuitable supply remains a single positive MW value.
- Updated the browser regression to bypass the duration input's HTML minimum and prove invalid duration and invalid unsuitable zero each produce zero draft writes, then correct the values, save four facts and explicitly accept. It also verifies suitable supply zero can be saved.
- `npm run typecheck` — exit 0.
- `npm run build` — exit 0 (existing chunk-size advisory only).
- `npx playwright test tests/environment.spec.ts tests/call-facts.spec.ts` — exit 0; 68 passed, 1 skipped (existing synthetic authenticated-write test).
- After final metadata-bound checks, focused `npx playwright test tests/environment.spec.ts -g "one call logs several facts"` — exit 0; 1 passed.
- `git diff --check` — exit 0.
- UTC timing/token metrics and model config identity remain UNKNOWN.
