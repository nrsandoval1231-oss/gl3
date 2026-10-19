# UI79 integration episode

UTC start: 2026-10-19T18:03:29Z. Builder handoff: 2026-10-19T18:17Z.

Branch `feat/pursuit-workspace-79`, worktree `gl3-ui-79`. Preserved checkpoint `cd84b774543e4d3f789464de8710f8fe3b383fcd`; fetched main `211d744eb3ecf58e0ffd27ecf6a82d83a68c8b03`. Merged main in `4430b58ce57cdb7e19155edf3ad83306bfa3886e`. The only textual conflict was `.agent/CURRENT_STATE.md`; resolution retained the complete main record and linked UI79 as a separate episode/node. Main intelligence, saved publication, API, tests, generated contracts, and governance changes are retained.

## Builder work

- Kept the approved opportunity-first route and preserved the existing Research, Signals, and Operations routes.
- Made the current workspace row authoritative for commercial disposition/reason after detail loads and refreshes, avoiding reuse of older row metadata.
- Routed Next action through the same selection path as the project row so mobile Back restores list position and keyboard focus.
- Replaced hardcoded Unknowns claims for buying authority and fuel/site constraints with explicit “not evaluated in this summary” guidance.
- Added evidence-state labels from supported quotes/qualified values and an evidence-status-unavailable label where provenance cannot be established. Conflict notice now recognizes actual conflict values only and renders once; `Not assessed` remains non-conflict.
- Removed the duplicate legacy global search field on the Opportunities view; retained the page filter and new workspace search. Updated the stale Operations navigation assertion to the approved label.
- Labeled the existing lexicographic timing sort `Start (source text)`.
- Exported OpenAPI from the merged FastAPI application and regenerated TypeScript API types.

## Validation evidence

Commands and outcomes:

- `npm run typecheck` — exit 0.
- `npm run build` — exit 0; Vite emitted the existing >500 kB chunk-size advisory.
- `python scripts/export_openapi.py` under `.artifacts/UI79/resume/run.py` — exit 0.
- `npm run generate:api` — exit 0.
- `npx playwright test tests/workspace.spec.ts --project=regression` under the secure runner — 12 passed, including search, unknowns/conflict states, deep-link metadata freshness, mobile Next action/Back focus, cohort reset, and stale-response protection.
- Focused affected legacy regressions (`Cannabis Watch`, browse filter restoration, unchanged search while loading, active Operations click while loading) — 4 passed after updating the outdated Ingestion label assertion.
- `python -m pytest tests/integration/test_pursuit_workspace.py tests/integration/test_workspace_power_gap.py tests/integration/test_saved_browse.py tests/unit/test_api_auth.py -q` under the secure runner — 155 passed, 1 skipped in 159.90s. Six warnings include the existing Starlette/httpx deprecation and saved-browse isolation warnings.
- Initial browser attempts retained: first workspace run was 11 passed/1 failed because the new provenance assertion expected an unavailable label for an actually unknown value; test now supplies a known value. The first affected-legacy run was 3 passed/1 failed because the old test expected the retired `Ingestion` label; it now checks `Operations`. Final focused reruns passed.

The controller independently reported isolated runtime and screenshot proof, and is running the full browser regression, full backend suite, and final gates on this source. Builder does not certify those results.

## Boundaries and remaining state

No provider calls, spend, production writes, migration changes, credential changes, deployment, or outreach. Original brand assets remain unchanged; controller reports all 29 assets byte-identical to latest main. Production performance and authenticated production behavior remain UNKNOWN. Synthetic 2,000-row runtime data is not production evidence. Benchmark observations showed slower medians for richer workspace reads; no speedup is claimed. Full-candidate gates and independent Sol review remain pending. Tokens and active model/config identity were not measured and are UNKNOWN.

## Integration recovery and final receipt boundary

Independent review of f43d151 returned FIX: lost legacy tier switching, lost explicit root Environment aliases, and stale selected commercial metadata. Packet UI79-REPAIR1 restores those paths, cohort-token restoration, and an honest source-health Unknown fallback. Unchanged main reproduced the health 500. Full browser after repair: 161 passed, 1 skipped. Typecheck/build then caught a nullable helper argument; the type-only signature correction passed both checks. The parity helper call inherited a required monkeypatch parameter from main; repair 6c81b71 passes the existing fixture without weakening parity assertions, and the full parity journey passed on an isolated database.

Full backend harness failures are retained separately from product failures: inherited browser feature flags were reset to CI defaults, and nine adversarial setup guards rejected a test-suffixed application DB. A distinct disposable ui79_ci_app plus dedicated *_test database preserves those guards; the nine blocked tests then passed. Final source is frozen for coherent controller gates and fresh independent review. The definitive exact-candidate gate/review/metrics receipts are local `.agent/artifacts/UI79/` and `.artifacts/UI79/resume/`; no earlier review is inherited by a changed candidate. Review and PR do not authorize merge/deployment or close the parent Finish Contract.

Candidate execution lesson: match CI feature defaults and its distinct application/test DB naming before the full repository gate. Attribution: browser-specific local runtime harness, not qualification or ingestion behavior. Evidence: nine guard errors became nine passes after isolated harness correction. Metric: setup errors, direction 9 to 0; reversibility: local runner changes only. Retain this as a candidate workflow lesson for independent review, never a relaxation of safety assertions.
