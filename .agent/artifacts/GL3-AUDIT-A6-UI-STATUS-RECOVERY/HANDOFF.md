# A6 UI/status recovery handoff

This packet repairs the lost-response status workflow in `FactWorkflowPanel`. The first status request is frozen with its exact Need/project/pursuit, idempotency key, expected version, status, and trimmed reason. An ambiguous POST preserves that request and draft. A retry uses the same payload; the returned event is checked against the frozen request, then exact-Need history confirms its ID, version, scope, status, reason, and content hash before the draft is cleared. An unavailable/mismatched read-back remains UNKNOWN. A newer current status is shown separately from an older confirmed event. The bounded ascending event list displays the newest ten.

The change is limited to `web/src/features/pursuits/FactWorkflowPanel.tsx` and `web/tests/call-facts.spec.ts`, plus this packet artifact. The focused browser cases cover same-key recovery, repeated loss, unavailable reads, foreign scope, competing 409, concurrent newer status, events outside the latest-100 window, and newest-ten ordering. The existing ordinary status flow and fact-draft regressions remain intact.

## Evidence

- Focused Playwright suite: 19 passed, 1 dedicated persisted-path skip. The skip is expected in the fixture-only suite; a separate real persisted path passed.
- Real local API/browser path: 1 passed against the disposable builder application database. It authenticates with synthetic credentials, persists ordinary fact/status state, lets the second real workflow-status POST reach the API, aborts only the browser's response, retries, verifies byte-for-byte equivalent decoded request payload, and reads back exactly one committed event at version 2. The synthetic receipt and raw output are in `raw/`.
- Web typecheck and production build passed. `git diff --check` passed.
- The initial persisted attempt returned HTTP 401 before the selected synthetic fixture appeared; no workflow-status write occurred. A guarded check confirmed a mismatch between the wrapper's synthetic bcrypt hash and the test password. The corrected run generated a matching hash in-process, set the actual Vite trusted origin after fixture setup, and passed. A separate runner-script syntax error was retained and corrected before the green run.
- The independent review remains a `FIX` for the prior candidate and is copied unchanged as `FAILED-REVIEW.json`. This handoff makes no acceptance claim. Root owns final gates and a fresh independent review.

Raw captured logs and the synthetic fixture receipt are byte-hashed in `RAW-MANIFEST.json`; `RAW-VALIDATION.zip` packages the selected raw logs. Playwright result directories remain in ignored `.artifacts/` and are identified in the raw logs. Original failed outputs were not overwritten.

## Repeatable persisted proof boundary

Use a fresh eligible synthetic source-backed Need in the builder's disposable application database, not a retained corpus or any root final database. Clear `FIRECRAWL_API_KEY`, `OPENAI_API_KEY`, and `TYPESAFE_API_KEY` and disable background/autonomous research before Python or app imports. Generate a matching synthetic bcrypt hash in-process after any fixture setup, seed only synthetic permit-family rows, then set `A6_UI_PERSISTED_NEED_ID`, `A6_UI_PERSISTED_PROJECT_ID`, `A6_UI_PERSISTED_NAME`, `A6_UI_PERSISTED_PASSWORD`, `DATABASE_URL`, `APP_PASSWORD_HASH`, `TRUSTED_ORIGINS`, `GRIDLENS_API_PORT`, `GRIDLENS_WEB_PORT`, and `VITE_API_PROXY_TARGET` for the isolated Playwright launch. Use a new receipt path, free ports, and unique Playwright output directory each time. The recorded successful launch used API port 55561 and web port 55562 with `gl3audit_a6_ui_builder_migration`; the fixture values are synthetic and recorded in `raw/`.
