# Independent final test-only review — e25fd1c7

Reviewed on November 13, 2026, in the assigned independent Astra critic role. Scope is the final browser-test corrections after the previously reviewed application-source freezes. No repository application, test, CI, provider or retained-data edits were made by this reviewer; independent execution used an isolated archive.

**Scoped disposition: accepted for these test-only corrections.** No remaining material defect or gate weakening was identified in the final inspected delta. This is not whole-candidate, commercial-readiness, performance, merge or deployment acceptance. Final main-based full CI remains a separate requirement and is not claimed as passed here.

## Exact revisions and source boundary

- Frozen backend application source: `1de298af047f09a32e9a0349f41410a55bc1791e`.
- Frozen web application source: `7c85c32e3c96627971d706dae863089e92818a10`, equivalent to the previously recorded `c0063c7f27dffeb591697a039a481edd1044b77e` web source.
- Persisted Pursuits heading correction: `8da9ac87aa37960781420dada8e338631528dbb1`.
- Initial lookup/list test barriers: `81a6b9ab83bd93c1445a18359e5c4c4ddf4d71f9`.
- Final exact-request completion follow-up and reviewed test head: `e25fd1c7519aad0009b6b8f10fd1389d57cc956f`.

I inspected both applicable AGENTS files, the governing product/architecture/checkpoint material, and the existing `astra-backend-1de298af.md` and `astra-ui-7c85c32e.md` scoped reviews. Independent Git inspection confirms that the final two commits change only `web/tests/pursuits.spec.ts`. Comparisons of final head against `1de298af` for `backend/src` and against `7c85c32e` for `web/src` are empty. CI workflow, scripts and Playwright configuration are unchanged by the final corrections. The UI worktree has no tracked uncommitted change; its untracked `web/node_modules` is the local dependency symlink.

## Findings and resolution

The three substitutions in `8da9ac87` change exactly the obsolete heading expectation `Customer accounts` to the actual `Customers` heading. Visibility assertions remain at all three points. Navigation, persistence and timing assertions were neither removed nor relaxed. This is a label alignment, not a changed application contract.

The former lookup-401 case expected transient `View Details` even though its mock returned 401 immediately, before the existing lookup hold could apply. The new mock awaits the optional lookup hold before returning 401. The test now confirms both lookup and list requests have entered their holds, asserts the authenticated detail is visible, and then releases the lookup failure. It retains sign-in visibility, a positive authentication-ended event count and the original need URL.

The initial `81a6b9ab` replacement of the fixed delay with a callback after `route.fulfill()` had a real verification limitation: mock protocol handoff alone does not prove the renderer has consumed the response, and negative assertions can pass prematurely. That limitation was raised during this independent review and is closed by `e25fd1c7` for this bounded path. The follow-up tracks the exact held list `Request`, installs terminal listeners before releasing the 401, waits for that request's `requestfinished` or `requestfailed` event, and allows two animation frames before checking absence. A request failure represents the valid abort outcome; the test does not assert that every browser run must consume the stale payload successfully. Existing dedicated microtask-race cases remain unchanged.

The stale-response assertions still require no Add-to-Pursuit control, and now also require no Pursuit card, synthetic project title, contact name, email or telephone. No skip, timeout increase, retry increase, assertion deletion, application change or CI-gate change was introduced. These assertions establish the bounded visible-data behavior; they do not certify every possible internal cache or race schedule.

## Independent execution and inspected receipts

I created an exact `git archive` of `e25fd1c7` under `/workspace/task-runtime/astra-final-tests-e25fd1c7/`. A temporary review-only configuration used one Chromium worker, zero retries and an isolated Vite server on loopback port 32881. API/authentication routes remained the unchanged synthetic mocks. No backend server, database, retained source, credential change or provider execution was used.

From the archive's `web/` directory:

```bash
npx playwright test --config playwright.review.config.ts --grep 'a background 401 on the lookup expires the session and removes opportunity data' --repeat-each=5
```

Independent result: **5 passed in 14.3 seconds**, exit code 0. Log: `/workspace/task-runtime/astra-final-tests-e25fd1c7-repeat.log`. Only Node color-environment warnings were emitted. This focused repetition supports the repaired ordering; it is not a full regression-suite run.

Separately inspected implementation receipt `/workspace/task-runtime/ui-pursuits-e25fd1c7-receipt.md` records typecheck success, the focused case passing 1/1 in 2.5 seconds, and the complete Pursuits module passing 34/34 in 46.2 seconds. Those are implementation receipts, not independent reruns. The earlier `81a6b9ab` 34/34 receipt remains historical and does not erase the completion-barrier finding. No pending final CI job is represented as passing by this report.

## Unchanged acceptance limits

The real evaluation still comprises 20 organizations with zero project-scoped published claims. Contacts, identity quality and the salesperson journey have not been evaluated end to end on that real cohort. Query/payload repair does not resolve the outstanding latency and ingestion-overhead acceptance questions. Original before captures and expanded after fixtures are not matched inputs. Synthetic test success does not establish commercial extraction, useful recall, actual contact acquisition or readiness. No production deployment, retained-data write or provider activation is approved or performed.
