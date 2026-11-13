# Real browser verification receipt — 2026-11-13

This receipt records the final browser checks for the current source snapshot. All local database targets below were fresh disposable databases with `_test` suffixes. The runner and logs are under `/workspace/task-runtime`; no repository source or existing tests were changed for these checks.

## Local fresh rollup lane

Command, from `backend/`:

```bash
source /workspace/task-runtime/security-env.sh
uv run python /workspace/task-runtime/run_mission_browser_lanes_final2.py rollup
```

Targets: `gl3_mission_rollup_scale_final_20261113_browser_test` and `gl3_mission_rollup_scale_final_20261113_backend_test`, loopback PostgreSQL port55439. API/web ports were18391/15391. The underlying browser command from `web/` was `npx playwright test -c playwright.rollup-real.config.ts --output /workspace/task-runtime/mission-rollup-playwright-final-20261113b`, with the real-backend environment from CI and providers disabled.

The runner migrated both new rollup databases, seeded 2,098 synthetic rows, and ran the real browser journeys at 1440×900, 768×1024, and 390×844. Result: **3 passed** (2.1 minutes). Log: `/workspace/task-runtime/mission-rollup-browser-final-20261113b.log`. Playwright output: `/workspace/task-runtime/mission-rollup-playwright-final-20261113b/`.

## Local fresh Pursuits lane

Command, from `backend/`:

```bash
source /workspace/task-runtime/security-env.sh
uv run python /workspace/task-runtime/run_mission_browser_lanes_final2.py pursuits
```

Targets: `ui_pursuits_real_slice1o_test` and `gl3_mission_pursuits_final_20261113_backend_test`, loopback PostgreSQL port55439. API/web ports were18392/15392. The browser command from `web/` was `npx playwright test -c acceptance/pursuits-release/playwright.config.ts --output /workspace/task-runtime/mission-pursuits-playwright-final-20261113b`, using the corresponding real-backend CI environment and disabled providers.

The runner migrated its new disposable databases, seeded 2,098 synthetic rows, and verified the account-first pursuit journey through navigation, reload, and lost-response retry. Result: **1 passed** (1.7 minutes). Log: `/workspace/task-runtime/mission-pursuits-browser-final-20261113b.log`. Playwright output: `/workspace/task-runtime/mission-pursuits-playwright-final-20261113b/`.

## Phase 2 and broad browser suite

I did not rerun Phase 2 locally. The previously saved Phase 2 browser generation was stale; after refreshing its disposable fixture, the manifest group was present in search. The current-source remote CI browser run passed the complete lane set, so a duplicate local run was not needed. Root reports CI job **131789619793**, run **43396794478**, passed: **339** generic/auth browser checks, **32** seeder-safety checks, **3** rollup viewport checks, **1** Pursuits journey, and **1** Phase 2 journey.

## Superseded local attempts and harness correction

Earlier attempts are retained at their original log paths and were not overwritten. The first rollup attempt timed out during page navigation; the first Pursuits attempt timed out waiting for the web server; the earlier Phase 2 attempt read a stale saved generation and showed no fixture group.

One intermediate refresh used the generic `saved_browse.rebuild` path on the synthetic rollup scale fixture. That path collapsed the fixture to **48** canonical project groups instead of the **417** groups required by its scale manifest. This was a harness refresh mistake, not a product regression. I preserved the resulting database and logs; the final rollup result above uses a newly migrated database populated through the documented scale seeder.
