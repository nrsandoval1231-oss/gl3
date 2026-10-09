# A6 UI status and fact-entry handoff

This is the frozen builder handoff for packet `GL3-AUDIT-A6-UI-STATUS-READY-20261008.md` (SHA-256 `1f12f06ae525a817c40d6716c557e47d73584da6673c1d88e59055e969eeff1b`). It is an implementation candidate for root validation, not an acceptance verdict.

## Implemented slice

The authenticated exact-Need UI supports attributed fact drafts, explicit accept/reject/correct/retract decisions, exact-Need server read-back, separate live workflow status, and current-source timing correction review. Workflow status remains non-authoritative for qualification. The UI exposes all seven operator statuses plus `UNKNOWN`, and the backend applies status consistently to bounded browse, group/page selection, exact detail, counts, CSV, and cohort invalidation. Saved commercial history labels recorded references, recorded-empty basis, and legacy-unrecorded `UNKNOWN` separately without rebuilding old snapshots from current facts.

Timing correction drafts only advance their reviewed target when the server read-back is the same exact-Need timing draft, one fact version newer (or the same already-persisted idempotent draft), and the source identity, semantic/evidence hashes, reported bounds, project, activity, and submitted correction payload still match. A concurrent source/bounds change retains the draft and requires review. No public qualification or storage policy changed in this UI packet.

The browser fixtures now provide valid empty facts and `UNKNOWN` status DTOs for selected-detail routes. This is fixture support for the additive endpoints; it does not mock or change product behavior in the isolated persisted proof.

## Deterministic evidence

- Backend affected tests: `test_call_fact_workflow_integration.py`, `test_browse_filters.py`, and `test_opportunity_browse.py`: **40 passed**, one upstream Starlette/httpx deprecation warning. Raw log: `.artifacts/a6-ui-backend-affected-final-20261009T0120106156566Z-0f01452d0f7a45c29033cdbd44d7b284-pytest.log`.
- Ruff on the changed backend modules/tests: **passed**. Raw log: `.artifacts/a6-ui-ruff-affected-final-20261009T0120334244185Z-e32a01b08e32458ea637cb12fd50d8c2-ruff.log`.
- Mypy over `backend/src`: **80 source files passed**. Raw log: `.artifacts/a6-ui-mypy-final-20261009T0120335891996Z-3de4a89b9ef84ceea276a8775368b966-mypy.log`.
- Affected browser suites (`call-facts.spec.ts`, `commercial-pursuits.spec.ts`, `project_cards.spec.ts`): **54 passed, 1 intentionally skipped**. The persisted case was omitted in this aggregate run because its exact fixture environment variables are set only for an isolated, fresh-Need run. Raw log and Playwright output are `.artifacts/a6-ui-affected-fixture-browser-20261009T0119105085582Z-3d49d4b59c3944a8be279393555d962c.log` and its matching `-results` directory.
- Isolated persisted authenticated browser/API flow: **1 passed** against builder application database `gl3audit_a6_ui_builder_migration`, PostgreSQL loopback `127.0.0.1:55437`, with synthetic credentials, provider keys absent, and automated research disabled. The test used a wholly synthetic, current source-backed Signal Need. Its selected detail read, facts draft/decision/read-back, workflow-status write/read-back, and before/after tier checks used the real local API. Only the opportunity-list, health, and changes endpoints were stubbed by the test. Raw log: `.artifacts/a6-ui-persisted-registered-browser-20261009T0113592491968Z-fa5a01537d774d9b9ebd2f98370a276a.log`; matching result directory has Playwright metadata.
- Web typecheck and production build: **passed**. Logs: `.artifacts/a6-ui-web-typecheck-fixture-final-20261009T0122020718343Z-ed12eceb8e534495adf8c2735373925d.log` and `.artifacts/a6-ui-web-build-final-20261009T0120549541992Z-39d1cb2c817349d891c3a4fe6d6c0d1c.log`.
- OpenAPI type generation to an ignored temporary output matched `web/src/api/generated.ts` byte-for-byte; both SHA-256 `BA63DCBB8983961A647AB74A9036437F457924A41920106CF06F1B291FC0374B`. Raw generator log: `.artifacts/a6-ui-generated-check-5a3f92cfc3524a86bbe14e6847b09d1b.log`.
- `git diff --check`: exit 0. Raw output log: `.artifacts/a6-ui-diff-check-final-20261009T012400Z.log`. Git emitted only its configured LF-to-CRLF working-copy notices.
- Builder ran the retained-scale populated-status measurement on a root-created, authorized disposable clone; root independently verified the 24 original-table fingerprints afterward. These checks do not claim the frozen candidate has passed root's final gates.

## Persisted fixture diagnosis

An initial bare-Need fixture returned 404 because it had no accepted linked source evidence. A follow-up read-only projection probe showed the next accepted interpretation had exact matching hashes but the source was `family=synthetic`, `retrieval_method=synthetic`; canonical admission correctly rejected it. The final disposable fixture uses a new synthetic source ID and the existing registered `construction-permits` / `socrata-permits` pair, exact accepted interpretation/evidence hashes, the evidence ID, exact project identity/activity, and the NeedObservation link. Its publisher, endpoint, project, evidence text, and citation are explicitly synthetic. A read-only preflight then returned support=true, one Signal summary, and one exact selected detail before the browser flow ran. The projection was not changed.

The repeatable seed script is `seed_persisted_fixture.py`. It requires an explicit expected database name, loopback port 55437, user `gl3audit`, a builder/root persisted-test database allowlisted in the script, and a new receipt path. Run it only through a wrapper that clears `FIRECRAWL_API_KEY`, `OPENAI_API_KEY`, and `TYPESAFE_API_KEY`, disables automation, and points `DATABASE_URL` to that exact approved disposable database. No source/corpus/application data is included in this artifact.

For the browser proof, use API port 55491 and web port 55492 after confirming they are free. Set `GRIDLENS_API_PORT=55491` and `GRIDLENS_WEB_PORT=55492`; set `TRUSTED_ORIGINS=http://127.0.0.1:55492`, `COOKIE_SECURE=false`, synthetic `SESSION_SECRET` and `APP_PASSWORD_HASH`, and the disposable `DATABASE_URL`. Set `A6_UI_PERSISTED_NEED_ID`, `A6_UI_PERSISTED_PROJECT_ID`, `A6_UI_PERSISTED_NAME`, and `A6_UI_PERSISTED_PASSWORD` from the new fixture receipt. Run only `npm exec -- playwright test tests/call-facts.spec.ts -g "synthetic authenticated browser writes persist through the isolated local API" --project=regression --output=<new-unique-results-directory>`. Clear all four `A6_UI_PERSISTED_*` variables for fixture-only suites; this persisted test expects a fresh fact-history version 0.

## Validation still owned by root

The complete backend suite, fresh migration/repeat/downgrade/drift gates, full browser gate, final retained-scale/parity and original-data preservation checks, known-secret scan, exact frozen source capture, and independent review remain open for root. No merge, push, deployment, provider call, or customer-source validation was performed here.

UTC validation window began with the projection diagnosis at `2026-10-09T01:12:10Z` and ended after the focused frontend typecheck at `2026-10-09T01:22:02Z`. Individual command durations are preserved in their logs. Total build, planning, and prior continuation durations are `UNKNOWN`; model/config identity and token usage are `UNKNOWN`.

