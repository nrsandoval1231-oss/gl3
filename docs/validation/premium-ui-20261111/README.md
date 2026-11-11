# Premium workspace UI — November 11, 2026

Scope: the owner's approved screenshot applied to the existing React workspace. No backend source, schema, ingestion, provider activation, production data, merge or deployment changes.

The shared shell now uses the approved metallic G/wordmark raster without cropping and the retained architectural artwork in a 110px masthead over a 58px navigation row. Opportunities keeps canonical company aggregation, source-backed commercial briefs, distinct amount classes, scoped contact routes, explicit multi-opportunity selection and existing Pursuits state. The single toolbar retains server-side filters, sort, search, exports and URL/history behavior. Phones have a search disclosure, contained logo, circular account control and vertically stacked cards with the primary action before secondary context.

Profile truthfully describes the existing shared-password session. Settings provides a persisted browser reduced-motion preference. The account dropdown retains Research progress, Signals, diagnostics and Sign out, and adds build identity. Production Compose requires the actual source SHA as a build argument; the environment follows the production Compose configuration. The package version comes from package.json. A deployment timestamp is shown only when supplied by the deployment process; a build time is never presented as deployment time.

## Screenshots and comparison

All screenshot data is **synthetic acceptance data**, visibly labeled Synthetic, with `.invalid` email routes and test phone numbers. It is not a sample of current production research. No reference/mockup contacts or numerical claims were added to production code.

- [Desktop 1440×900](desktop-1440x900.png)
- [Desktop 1648×928](desktop-1648x928.png)
- [Desktop 1280×800](desktop-1280x800.png)
- [Tablet 768×1024](desktop-768x1024.png)
- [iPhone 390×844](mobile-390x844.png)
- [Full phone page, including contacts and sources](mobile-full.png)

Direct visual inspection against the attached owner reference checked the two header levels, contained original logo, architectural center artwork, right-hand statement, active underline, introduction/metrics alignment, segmented toolbar and compact company/power/Why now/contact/action grouping. Sora follows the explicit brand instruction despite the reference headline's serif appearance. Cards expand for substantive scope/uncertainty text instead of truncating material qualifications. On phones the first Pursuit action is inside the initial 844px viewport; contact routes and secondary context remain below. The retained raster artwork is only 145×53, so the enlarged center is visibly softer than a high-resolution reference; no replacement artwork was invented.

## Honest availability boundaries

The existing API exposes the total canonical accounts matching the current shortlist query and filters. That supplies Shortlist. It has no corresponding New Today or In Research aggregate: these display a dash with an accessible Unavailable label, rather than invented counts or misleading visible-page totals. The Shortlist number is also unavailable while browsing All Projects. Future aggregate endpoints are outside this presentation-only change.

Authentication exposes no individual user name, so the account button uses an accessible user icon, without fabricated initials. There is no existing notification or saved-star workflow, so those unsupported controls are omitted. Documented, calculated, estimated, inferred and unknown amounts remain distinct; none is relabeled Verified without verification evidence. Energization is displayed only for explicitly matching energization/commissioning/in-service events. No permit date is relabeled as energization.

## Verification

Local checks use disposable loopback PostgreSQL databases and disabled providers. Full command logs are retained under `.artifacts/premium-ui/` in the task workspace. Final results and independent review are recorded in the PR; earlier failed or interrupted runs are not passing receipts.

Observed before final source freeze:

- Locked frontend/backend dependency installs completed; frontend audit found zero vulnerabilities.
- TypeScript typecheck and Vite production build passed (existing large-bundle advisory retained).
- Ruff lint/format passed; mypy passed 266 source files.
- Brand validator passed 216 assets and eight semantic AA pairs; original image assets are unchanged.
- Maintained documentation graph passed.
- Premium shell/browser acceptance passed, including 375/390px overflow, real search handler, four navigation handlers, account modal Escape/focus, persisted settings, amount classes, safe contacts, and five viewport captures.
- Retained project detail acceptance: 14 passed, including action bounds at 1648/1440/1280/390 widths and overflow/footer checks.

The initial broad browser run was interrupted after 99 passes and obsolete selector failures. An intermediate broad run overlapped an isolated run sharing Playwright's output folder, causing artifact ENOENT failures; isolated runs now use separate output paths. The first real-backend rollup attempt exceeded its 15-second initial navigation budget during concurrent cold builds; its failure is retained separately. These are not claimed as successful final acceptance.

## Independent review repair

Independent Astra reviewed `9544d4762a1b3906d5360978d449bd8147b9d4c6` and withheld approval for two concrete issues: populated mobile search results could remain open after the close toggle, and an unbounded energization substring test could mislabel decommissioning or regulatory commission events. The repair closes both search state flags and restricts timing to explicit normalized lifecycle kinds. New browser cases cover close/reopen/Escape, a genuine commissioning positive and decommissioning/regulatory-permit/free-text negatives. The account disclosure also gains Escape/focus restoration and bounded short-screen scrolling; tablet cards avoid word fragmentation and artwork no longer overlaps the statement. This is a repair record, not a final approval claim.

The isolated real-backend rollup lane subsequently passed all three viewport journeys (1440, 768 and 390 pixels) against 2,098 synthetic persisted rows, with providers disabled. This demonstrates actual API/account/pagination behavior using fixtures; it does not prove production freshness or research coverage.
