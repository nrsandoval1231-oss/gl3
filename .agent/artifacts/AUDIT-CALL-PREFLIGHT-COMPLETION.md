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
