# A5B R2 implementation handoff

Packet: `.agent/packets/GL3-AUDIT-A5B-R2.md`  
Controller direction: `.agent/graphs/GL3-AUDIT-A5B-BROWSER-R2-DIRECTION.md`  
Base: `67a30c1b83b9990c17cff321ed54e4d1a1bc60d8`  
Start: 2026-10-08 UTC; elapsed duration UNKNOWN.

## Changes

- Replaced the commercial browse safety-preflight per-group queries with bounded batch queries for evidence counts by need, lifecycle and relationship counts by project, and snapshot/note counts by commercial workspace. Per-canonical-group totals and all existing caps/413 responses remain applied before detail hydration or evaluation writes. `_commercial_triage_cards` retains its list return contract; the separate page helper still supplies grouped totals.
- Added a focused 1-versus-50-group SQL-count regression and an oversized evidence regression proving 413 happens before the evaluation endpoint mutates commercial pursuit state.
- Historical saved evaluation details remain as-of and make no autonomous-research request on expansion. A separate explicit action loads read-only research history for the exact saved `need_id`, labels it as loaded-now and potentially later than the saved evaluation, and provides no action or poll controls. Failed later-history reads render UNKNOWN independently of the saved disposition. Only overlapping read-only requests for the same need share an in-flight Promise, which avoids a duplicate request under React StrictMode; the Promise is removed on success or failure. Existing active/actionable research uses its original abort, action, and poll behavior.
- Corrected the old project-card and vertical fixtures to supply canonical group IDs, complete-group metadata, cohort/count headers, representative titles, decision scopes and search-filtered counts. The dated event test retains whole-group identity and permits opening every retained member.

## Focused validation

- Backend: safe wrapper, provider keys absent, synthetic test authentication, dedicated `gl3audit_a5b_test` and `gl3audit_a5b_migration`; six focused tests passed, including the two original R1 failures and four R2/list/preflight regressions.
- Backend source typing: `mypy src` passed, 78 source files. Exploratory `mypy src tests` was also run and reported one type error at unchanged, out-of-scope `tests/integration/test_source_scheduling.py:95` (`counts` inferred as `dict[str, int]` in one branch and a string value in the alternate branch). This is retained as a non-R2 result; no unrelated test edit was made.
- Backend focused lint: Ruff passed for `src/gridlens/api/app.py` and `tests/integration/test_power_need_briefs.py`.
- Browser: six focused cases passed, including explicit one-read behavior, no reads while opening saved detail, exact-need switching, UNKNOWN on unavailable history, and retry after remount. The default Playwright native output directory was reused across earlier development runs; original trace bytes from those runs are UNKNOWN. The raw console logs listed in `RAW_LOGS.json` remain available and hashed.
- Web typecheck and production build passed.
- `git diff --check` passed before freeze.

## Preserved failures and boundaries

Earlier focused browser red runs and the first Ruff failure are retained and hashed in `RAW_LOGS.json`. They exposed the StrictMode duplicate GET, stale fixture count wording, and helper use of `q` where the API uses `search`; the focused regressions now pass with the exact server-side filtered cohort contract. One browser command did not start because its log path was rooted under `web/.artifacts` instead of repository `.artifacts`; its tool output was not retained as a raw file. The first attempted empty-argument mypy wrapper call failed argument validation and produced no checker log. These incidents are identified as unavailable bytes, not reconstructed raw evidence.

No full backend suite, full browser suite, final migration run, frozen retained-corpus traversal/performance run, or independent review is claimed here. Root owns those post-freeze gates and the final acceptance decision. No corpus or production data was read or changed by this R2 work; test writes were confined to the assigned disposable databases.
