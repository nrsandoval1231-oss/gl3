# GridLens dashboard implementation — October 24, 2026

## Result and repository inspection

Initially extended PR #115 while it was open at `fe913f9`, with main at `a70e533`. The PR already contained the seven-color migration, two-ink G/L candidate assets, Sora/Inter fonts, and initial table/detail integration; those changes were reused. All remote branch heads and active PR #114 (`d2a2c6c`) were inspected. Separate PR #114 backend work was not imported or overwritten.

Concurrent commits `bb2bf6e` and `54770e0` added account-menu contrast checks and Windows/UTF-8 asset validation; they were incorporated and preserved. PR #115 was independently merged at 02:49:37 UTC on October 24, while this implementation was underway. Its merged head was `54770e0`; it did **not** include these dashboard changes. After detecting that state, this exact dashboard delta was placed on `ui/approved-gridlens-dashboard`, based on latest main `bb6f240`, as a focused follow-up. The tested frontend content is unchanged by this branch transition. The assistant did not merge PR #115 or deploy production.

## Implementation

- Harbor Navy horizontal header using the existing dark corporate lockup; header search and existing navigation/account controls.
- Four KPI positions and right-hand Quick Filters. Total Pipeline uses API disposition counts and explicitly states its power-need/all-disposition scope. No page-slice aggregation, fabricated high-priority threshold, aggregate MW, timeline or confidence.
- Approximately 69/31 desktop split with a compact seven-column semantic table. Canonical numerical priority, commercial disposition and qualification remain separate. Verified remaining gap is never replaced by required demand.
- Company selection opens detail while retaining the desktop table. The separate project-count action preserves account aggregation, aliases, evidence summaries, projects and need pagination.
- Customer intelligence has three primary metric positions and Overview / Buying Chain / Evidence / Power Analysis / Notes. More retains Timeline and Research Gaps. Power Analysis retains the original demand, supply, duration, energization and gap basis; qualification/provenance remain inspectable.
- Tablet/phone use a readable dedicated selected-detail view. Mobile list uses labeled compact rows. No permanent sidebar, decorative map or photography.
- Selection, URL reload, browser tab history and Back restoration handle delayed responses and direct-entry URLs. Research, notes, facts, corrections, sources, Signals, Operations and sessions retain their existing APIs.
- Superseded global layout declarations were consolidated rather than introducing a new stylesheet. No backend/schema source was changed.

## Screenshots and provenance

All captures are Chromium screenshots of the real running Vite application, not rendered mockups. Screenshots retain the actual app UI and local Sora/Inter fonts.

| Size | Real local API | Disclosed populated test fixture |
| --- | --- | --- |
| 1648 × 928 | [Empty cohort](screenshots/dashboard-1648x928.png) | [Dashboard](screenshots/fixture-dashboard-1648x928.png) |
| 1440 × 900 | [Empty cohort](screenshots/dashboard-1440x900.png) | [Dashboard](screenshots/fixture-dashboard-1440x900.png) |
| 1280 × 800 | [Empty cohort](screenshots/dashboard-1280x800.png) | [Dashboard](screenshots/fixture-dashboard-1280x800.png) |
| 768 × 1024 | [Empty cohort](screenshots/dashboard-768x1024.png) | [Tablet detail](screenshots/fixture-dashboard-768x1024.png) |
| 390 × 844 | [Empty cohort](screenshots/dashboard-390x844.png) | [Phone detail](screenshots/fixture-dashboard-390x844.png) |

[Phone list](screenshots/fixture-dashboard-mobile-list.png). Additional `fixture-workspace-*` captures test adversarial long customer/project names. Fixture names, scores and records exist only in tests and never enter application operation or the local database.

Local runtime: existing loopback PostgreSQL and API were started; existing migrations were applied to the local development database. The first capture correctly exposed an unpublished cohort. Running the existing saved-browse projection builder published **zero eligible rows**. Final `dashboard-*` captures show this real empty cohort and authenticated session. No new discovery records or provider calls were created. This verifies real login/API/empty-state rendering, not populated real-data acceptance.

## Visual comparison and independent review

Compared the supplied inline owner dashboard with rendered captures. The approved seven-color identity supersedes the screenshot's metallic/gold treatments. Header height is 92px on desktop; table/detail widths measure approximately 69/31 with a 12px gap. At 1648px the panels measure 1096px / 492px; at 1440px, 952px / 428px; at 1280px, 842px / 378px. No page overflow at any requested viewport. Phone toolbar geometry is asserted separately to catch clipping within panels.

Independent reviewer inspected all five populated captures plus mobile list and reviewed navigation/data handling. Found and corrected account selection replacing the table, Back stepping through tabs, sign-out contrast, mobile toolbar clipping, tablet sticky-header occlusion, and direct-entry Back navigation. Final review found **no remaining P1/P2 implementation issue**. P3: a small strip of scrolling rows can show beneath the sticky account footer at some desktop heights.

Expected differences: supported existing navigation destinations and dispositions replace screenshot-only pages/statuses; unknown metrics remain unavailable; canonical numerical rank is not relabeled High/Medium. Actual long records may wrap. Exact pixel/brand parity is **not claimed**.

## Acceptance blockers and delivery boundary

1. `brand.tokens.json` still records `geometry_verified: false` and `wordmark_verified: false`; PR #115's G/L trace and outlined wordmark are review candidates. This task reused them without redrawing or asserting approval.
2. The local API publishes zero eligible records. Populated real-record selection/research verification requires an eligible retained cohort; fixtures do not satisfy that gate.
3. Screenshot-only Power Markets, Permits, Interconnection and Reports routes do not exist. Existing Opportunities/customer accounts, Research, Signals and Operations remain functional. No fake destinations or watchlist mutation endpoint was introduced.

The dashboard follow-up PR remains draft and unmerged under the owner's explicit acceptance criteria. No production deployment occurred.

## Validation

- `npm ci --prefix web`: locked installation passed.
- `npm run build --prefix web`: TypeScript and Vite **6.4.4** production build passed.
- `npx playwright test -c playwright.brand.config.ts --workers=2`: **191 passed, 1 skipped** in each of the last two complete locked-dependency runs, including the final visible/accessible tab labels. After incorporating the concurrent account-menu/Windows fixes, the combined-branch dashboard, responsive account-menu contrast and login check passed **10/10**; build and asset validation also passed again. The skipped optional synthetic authenticated write-through check requires its dedicated isolated API setup; populated live acceptance is not claimed.
- Browser coverage includes search, quick/advanced filters, category filters, server sorting, pagination/cohorts, account/project aggregation, keyboard selection, immediate detail replacement, tabs, reload, Back/Forward, direct-entry Back, stale responses, research/title polling, buying-chain relationships, evidence provenance, notes and fact corrections, login failures, Signals and Operations.
- Earlier runs exposed stale presentation expectations and a Signals request-count race. Tests now navigate explicitly to Evidence/Power Analysis for those workflows. The Signals invariant counts fetch starts inside the browser instead of racing asynchronous route-handler delivery during StrictMode replay; it continues to prohibit a refetch on clicking the active tier.
- `python tools/brand/validate.py`: **216 assets passed** hashes, SVG geometry format, dimensions, alpha, filenames, active references, fonts, token consistency and eight checked semantic AA pairs. This is not visual logo approval.
- `git diff --check`: passed. Active frontend search found no legacy Aperture/ABC Diatype/old navy literals or gold styling. Prior archived records were preserved.
- Real API capture: authenticated session, actual zero-row saved projection, all five sizes, no page JavaScript errors and no page overflow. No production deployment or provider invocation.

## Changed files

| Area | Files |
| --- | --- |
| Dashboard shell, KPI/filter placement, selection/history | `web/src/features/workspace/Workspace.tsx` |
| Shared semantic table and truthful remaining-gap display | `web/src/features/workspace/OpportunityTable.tsx` |
| Account aggregation and explicit project browsing | `web/src/features/workspace/CustomerAccountsQueue.tsx` |
| Detail metrics, primary tabs, preserved deeper workflows | `web/src/features/workspace/WorkspaceDetail.tsx` |
| Consolidated desktop/tablet/mobile presentation | `web/src/styles/workspace.css` |
| Main dashboard regression and fixture capture | `web/tests/dashboard.spec.ts`, `web/tests/fixtures/dashboard.ts`, `web/tests/approved_workspace.spec.ts` |
| Updated navigation, accessibility and workflow regressions | `web/tests/{buying_chain,call-facts,commercial-pursuits,customer-accounts,environment,first_path,pr101-regressions,project_cards,workspace}.spec.ts` |
| Reproducible real local capture | `web/scripts/capture-dashboard.mjs` (run from `web/` with API/Vite running) |
| Canon, delivery and visual evidence | `docs/design/UI_CANON.md`, this report, `docs/design/screenshots/`, `design-qa.md` |
