# Customers default visibility review — November 13, 2026

Status: bounded backend and UI change accepted at the exact hashes below. The backend commit is `2336b02a`; UI hashes were checked again after the independent browser replay. Broader final regression gates remain the coordinator's responsibility. This is an independent review of the owner-authorized change from the default Shortlist to all canonical customer accounts. It does not approve production deployment, change source admission, or establish commercial mission completion.

## Required boundary

Changing only `shortlist` to false is insufficient. The existing `customer_results.groups(shortlist=False)` includes unresolved and same-name-unconfirmed project groups. Presenting those as the default Customers account list would contradict the requested canonical-account boundary. Filtering a returned page in the browser would also corrupt counts and pagination.

The agreed bounded contract is an optional server-side `canonical_only=False` argument. The Customers account route explicitly supplies true; legacy callers retain false. True selects the existing `resolved_identity` group kind before pagination, window counts, need totals, empty-page fallback counts, facets, metadata lookup and account open/child lookup. It does not impose Shortlist eligibility. An explicit Shortlist still requires the existing relevant-project eligibility rule. Existing native RRC identity resolution remains valid; this change does not invent a stronger global-company identity requirement.

The true mode must have a distinct parent cohort token and therefore distinct child token. False must preserve the legacy token bytes. Route-specific API query allowlists should accept the new argument only on the three group endpoints. Browser list caches and account page-recovery intent must distinguish the canonical mode; cached legacy unresolved groups must not leak into Customers.

Compatibility refinement: an explicit `groupBrowse=1` route without `customerScope=canonical` retains the existing raw-group behavior, including unresolved groups. The unchanged real-rollup regression depends on that route. The new bare Customers default uses canonical scope and must carry `customerScope=canonical` whenever navigation creates an explicit group route. This marker must survive account/project opening, reload, filters, back navigation and workspace resume. It is a deliberate compatibility route, not the default customer cohort.

## Route and action audit

- Bare `/`, workspace and normal account browsing should select all canonical customers. Explicit `shortlist=1` remains a shareable Shortlist. The explicit legacy `projectBrowse=1` route keeps its existing default.
- Account aliases and project/need deep links retain account context and source access. Account-first need detail must use the same default mode as its parent; a bare need link must not silently start with Shortlist. Existing fallback access to sources for a legacy need remains.
- Back navigation, query changes and cohort expiry must invalidate or reuse the matching mode only. The pre-change expiry call omitted the actual shortlist value; the builder corrected that call in the initial patch.
- The generic Companies return link should follow the new Customers default. Companies itself and the legacy flat project view retain their existing contracts.
- Visibility does not create a Pursuit. The card quick action still requires the existing eligible-need condition. Existing ordinary account detail can offer a user-selected active need; backend creation remains need-scoped, with its existing alias, activity and idempotency checks. This is not a new qualification or contact-verification policy.

## Evidence and pending verification

The review read the route selectors, workspace alias/navigation flow, list cache, account recovery intent, group SQL/count paths and existing Pursuits creation boundary. The backend contract is accepted at these SHA-256 values:

| File | SHA-256 |
| --- | --- |
| `backend/src/gridlens/intelligence/customer_results.py` | `0ed7f395e747b7d95857effedaa1f761bfc94ffc3d0539ccf63871bbe5a23ade` |
| `backend/src/gridlens/api/app.py` | `6eb22cc5caad9b3915955736b41e344f4fd512e86fdaa410c186e4d677468d0f` |
| `backend/tests/integration/test_customer_canonical_scope.py` | `c6f071ae94a23179610e947a2df4dbf8373c6c0bce50c4ee68ac31cf503237c8` |

Independent pure checks compared the actual isolated `_cohort` functions before/after: omitted and false mode preserve token bytes for both Shortlist states, while true differs. Seven isolated API query-validator cases accepted only the group paths and rejected the flag on project/export/map/unknown paths. The builder reported five new tests passing (two database cases and three parametrized API validator cases), including exact unresolved-only facet exclusion, same-name-unconfirmed child denial, legacy access, empty-page totals and mode-crossing token rejection. This reviewer did not rerun database tests.

Review found and the UI builder fixed a real reload boundary: opening an account from bare `/` introduces `groupBrowse=1`; without treating the canonical marker as authoritative, reload reverted to Shortlist. Nine independent probes of the transpiled current route selector now pass for bare/workspace, explicit Shortlist, canonical marked routes, legacy group routes and legacy flat browsing. Account-first need-detail default was aligned as well.

The focused UI run also exposed an expiry-timer overflow. Independent Chromium execution confirmed that scheduling a callback for the unchanged 2099 fixture expiry (about 2.276 trillion milliseconds) fired within 100 milliseconds. `ProjectResults` scheduled parent and child expiry directly without clamping or rechecking the current time; parent expiry increments the retry counter, allowing repeated fetches. The builder repaired both timers using the bounded-delay/recheck pattern already present in `CompanyView`, without changing fixture expiry values. Independent execution of both repaired scheduling functions confirmed initial clamping to 2,147,483,647 milliseconds, rescheduling the remaining 5,000 milliseconds without premature expiration, and one expiration at the actual deadline. Cleanup clears outstanding timer IDs.

The canonical facet query now runs the assignment/grouping SQL to restrict facets correctly. This is constant work per request, with no added per-card query, but the previous latency/payload benchmark did not measure this new default path. This review does not carry forward performance acceptance.

## Frozen UI and retained-payload replay

| File | SHA-256 |
| --- | --- |
| `web/src/features/workspace/ProjectResults.tsx` | `7a5ddae1359a46b664a198cbd52167f2bab877d9679aac2e29136656a789b9d4` |
| `web/src/features/companies/CompanyView.tsx` | `2b270e98c911b4f251a4636854c45e99698c6536da810440707ae9054e328f6c` |
| `web/src/api/client.ts` | `84d9dc10361bd8c3f3d7f9f3d8cfba93e011b95e46dc1d0fb4daef053be578a6` |
| `web/src/features/workspace/Workspace.tsx` | `e3a2d739f96cf82aa01220f8502eeb8ddff16512ea2ded603c9fee3fbc169ddf` |
| `web/src/features/workspace/CanonicalOpportunityDetail.tsx` | `d413554453c781d605bdeeece6137213b809392f546f3c34826d650ea554db9c` |
| `web/src/features/companies/CompaniesPanel.tsx` | `ceb223c8646e4ebb62798a44da1459b971c8960da4aa4cb103cc18cbca87031b` |
| `web/src/state/projectBrowseCache.ts` | `9d8f4ac520401efd643f17bf3c3c979b95395af645e3dfc807f65e5ba2a9458d` |
| `web/tests/default_browse_mode.spec.ts` | `0e30a73f8baa49ead03fa3d8a9516fe1e986da90014df9249021ec39f89999da` |
| `web/tests/companies.spec.ts` | `461df0a5de05266b7c000dc6dd88341725bfac548d8230af9c45ad17ddd1417d` |
| `web/acceptance/pursuits-release/pursuits-real.spec.ts` | `8731c995cb705d4734255714c4552976feb78ee64501e09bd16495b7e13bd14e` |

The builder reported typechecking and 22 focused Playwright tests passing, followed by all 12 Companies tests after updating its directly affected return-link expectation. Reviewed existing-test changes are limited to the authorized default policy, related navigation assertions and accurate default-scope receipt labels; the real Pursuits test's historical metric key remains explicitly documented. This review does not claim the real Pursuits acceptance journey was rerun.

Independent smoke used a temporary frontend-only Vite server on port 5187 and headless Chromium. Every API request was intercepted; unknown/external requests were rejected. It replayed unmodified `ordinary_groups`, `shortlist_groups` and `opened_group` objects from [the native publication replay](../../../eval/customer-commercial-v1/runtime/native-runtime-replay-publication-final-20261113.json), with browser time fixed to the capture time, `2026-11-13T08:52:18.531968+00:00`. No backend database or provider was called.

Observed results:

- Bare `/` requested `/api/opportunities/groups?sector=all&limit=25&offset=0&sort=priority&shortlist=false&canonical_only=true` and visibly rendered CyrusOne and DataBank, with All customers selected.
- Both cards had zero quick Add-to-Pursuit actions. The cards displayed DataBank's up-to-480-MW IT-load claim and CyrusOne's source-reported operational target by fourth quarter of 2026; energization remained unestablished and commissioning explicitly lacked sufficient inputs.
- Opening CyrusOne through its account title produced `/?view=workspace&groupBrowse=1&customerScope=canonical&account=cg_785a71dbc1767302ca7e22c56102d154`. Opening and reloading requested `shortlist=false&canonical_only=true` throughout.
- Explicit `?shortlist=1` selected Shortlist and displayed zero groups. Selecting All customers restored both accounts.
- The replay recorded zero page errors and zero unknown/external requests. The browser and temporary server were closed.

One preliminary attempt used a button present only when a featured project exists; the retained ordinary response does not include that field. The final smoke used the actual account-title control. This was a probe-selector correction, not a UI failure or altered fixture.

The retained native replay contains two ordinary canonical groups and zero Shortlist groups. The browser smoke proves their rendering and navigation through the new frontend contract; it does not rerun native ingestion or prove the new API contract against those live records. The backend boundary has separate source/pure review and builder-reported database tests. Broader source coverage and verified contacts remain unmet; changing the default does not fix those gaps or establish human commercial acceptance.

## Actual-backend visual follow-up

The coordinator subsequently supplied a separate [actual-backend receipt](default-native-ui-20261113-final/receipt.json), captured at `2026-11-13T13:59:27.746Z`, with `api_mocking: false` and native source data in disposable database `gl3_retained_ui_smoke_20261113_13da6025_test`. It compares baseline frontend `2cf4f67b` with the accepted frontend against the same current backend and generation `0cd3900a-afe3-4805-88e4-085670a4d9d0`; it is not a complete before/after backend deployment comparison. Receipt SHA-256: `15b155e72e0936544ced38a4b7686fe4e024df4351a0cf63af0c8df4cde6cafa`.

This reviewer opened all four supplied images: [before desktop](default-native-ui-20261113-final/before-default-desktop.png), [after desktop](default-native-ui-20261113-final/after-default-desktop.png), [after mobile](default-native-ui-20261113-final/after-default-mobile.png), and [DataBank detail](default-native-ui-20261113-final/after-databank-detail.png). All eight source hashes and four image hashes in the receipt match the files inspected.

The before image shows zero accounts with Shortlist selected; the after images show both canonical names with All customers selected. The GridLens brand and navigation remain intact. Capacity, timing and commissioning unknowns are readable without opening the account; the 480-MW figure remains qualified as an upper-bound IT-load claim. The mobile cards wrap within the visible page, with no visible overlap or horizontal clipping. DataBank detail explicitly states that no verified business contact is available and preserves project-specific navigation and the existing need-scoped action. These observations support the bounded default-visibility and readability change; the reviewer did not independently rerun this actual-backend journey.

**Separate factual blocker remains:** the captured Recent development labels describe initial historical facts as revisions and affect commercial prioritization/next-action language. The coordinator has identified that as a separate first-fact/history defect for an isolated repair. This visual acceptance does not approve those revision claims, historical freshness, verified ownership/contact availability, ranking usefulness, or completion of the commercial mission.
