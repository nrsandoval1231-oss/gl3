# Premium workspace UI — November 11, 2026

Scope: the owner's approved screenshot applied to the existing React workspace. No backend source, schema, ingestion, provider activation, production data, merge or deployment changes.

The shared shell now uses the approved metallic G/wordmark raster without cropping and the retained architectural artwork in a 110px masthead over a 58px navigation row. Opportunities keeps canonical company aggregation, source-backed commercial briefs, distinct amount classes, scoped contact routes, explicit multi-opportunity selection and existing Pursuits state. The single toolbar retains server-side filters, sort, search, exports and URL/history behavior. Phones have a search disclosure, contained logo, circular account control and vertically stacked cards with the primary action before secondary context.

Profile truthfully describes the existing shared-password session. Settings provides a persisted browser reduced-motion preference. The account dropdown retains Research progress, Signals, diagnostics and Sign out, and adds build identity. Production web-image builds require the actual source SHA as a build argument; the environment follows the production Compose configuration. The package version comes from package.json. A deployment timestamp is shown only when supplied by the deployment process; a build time is never presented as deployment time.

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

This is the source-freeze receipt. Final exact-head CI and independent acceptance are recorded in PR #189 metadata, avoiding a receipt-only commit/CI loop.

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

Astra's second pass also identified a fallback-only scope risk: legacy source-context prose could appear under Power need, and an absent kind could produce both Unknown and the prose. The final renderer admits only explicit activity-requirement or facility-demand summaries and labels the latter Facility demand. Five browser cases preserve both positive classes and reject source-context, missing-kind and supported-gap prose as unsupported requirement claims.

## Frozen source verification receipts

UI source is frozen at `689b1366cb531c6003a3771c7f38b926a5e27b43`. The [hash receipt](receipts.json) enumerates the measured UI files and all six regenerated screenshot hashes. Subsequent presentation-test and receipt changes do not change those UI bytes.

- `npm run typecheck --prefix web`: passed.
- `npm run build --prefix web`: passed; existing bundle-size advisory remains.
- `npm run test:ci --prefix web -- --workers=4 --output=<separate full output>`: 333 passed, two obsolete presentation expectations failed. Their modules were updated to assert Profile/Settings/Research keyboard order and one honest Unknown power field, preserving contact suppression and no invented MW.
- `npm run test:ci --prefix web -- --workers=4 tests/approved_workspace.spec.ts tests/customer-accounts.spec.ts --output=<separate repair output>`: 17 passed, zero failed. This is a scoped repair pass, not a claim that the preceding full command passed.
- Opt-in `playwright.rollup-real.config.ts`: three passed against real local API/database fixtures.
- `uv run ruff check src tests`, `uv run ruff format --check src tests`, `uv run mypy src`: passed (578 formatted files, 266 typed source files).
- `uv run alembic upgrade head` and `uv run alembic check`: schema 0051 and no new upgrade operations; no migration introduced.
- Brand validator: 216 assets/eight semantic AA pairs passed; maintained docs: 111 documents/539 local targets/18 anchors passed.

The local full-backend command completed with 5,203 passed, one skipped and one failed in 1,775.38 seconds. The failure was the existing Compose fixture omitting the newly required build SHA. A direct isolated reproduction reported the same required-variable error. The fixture now supplies a clearly synthetic SHA, keeps every provider-key isolation assertion, and checks the build metadata. A new negative test rejects a missing SHA. Its complete 19-test module passes in 1.96 seconds. No backend source or test deadline was changed. The full run remains a failed receipt; the scoped repair does not retroactively turn it into a full pass. Required exact-head PR CI supplies the fresh complete result.

The earlier slow backend tail was independently sampled with py-spy: it was actively running the existing 200-record ingestion/map-concurrency test under CPU contention, not evidence of a deadlock. That test passed. The actual failure was the Compose fixture described above. No speculative performance repair or test timeout increase was made.

The final candidate preserves the UI source and screenshot hashes in receipts.json. The last two UI expectation repairs and Compose test-only repair were independently inspected by Astra. Final approval requires the exact PR head's checks and explicit independent attestation in the PR description. No CI result, source merge or local image is evidence that production was deployed.

## Final test-harness and capture receipts

The next complete local browser run recorded 334 passes and one test-helper readiness race: after reload, the helper checked for the disclosure before authenticated mount and returned early. It now waits for the existing disclosure to become visible, retaining the explicit flat/legacy route exceptions. The complete seven-test environment module passes in 17.8 seconds with its history/search assertions intact. A fresh complete run is recorded in PR validation metadata.

The 11-case premium module also passes in 43.3 seconds, including both review repairs, all power-kind boundaries, landscape account access and mobile action bounds. Ordinary test runs now save screenshots into Playwright's per-test output folder. Set `GRIDLENS_REFRESH_UI_CAPTURES=1` explicitly when regenerating the six committed review captures; ordinary CI must not rewrite the committed receipt images. All final capture hashes were recomputed after regeneration.

The sole local backend skip was independently reproduced with `pytest tests/unit/test_nc_commerce.py::test_live_probe_article_parses_without_becoming_a_fixture_or_runtime_seed -q -rs`: the optional local access probe is absent. No live probe was fetched or converted into production data.

## Final workflow preservation and complete browser run

The complete browser run at `76414e39b1eaf5315123a818692a31ca3c0fd84a` passed **335/335** in 4.6 minutes. Its application UI source and screenshot hashes remain unchanged by the following build-only correction.

Independent review identified that requiring the web SHA during all Compose interpolation would also block existing backend-only collect/alert operations. The final implementation makes the Compose argument optional for configuration and validates it inside the actual production web-image build instead. `deploy/validate-web-build.sh` uses POSIX sh and requires a 40-character hexadecimal source revision only for production UI builds. Docker invokes that same script before compiling. No fabricated fallback SHA is permitted. Backend operations without frontend metadata remain usable.

The final deployment/credential-boundary module passes **24/24** in 1.49 seconds: production missing/malformed/short SHA rejection, valid SHA acceptance, local missing-SHA acceptance, backend Compose configuration without frontend metadata, and unchanged provider-key isolation. The temporary test Compose tree mirrors the original relative environment-file layout. The intermediate failed temporary-path run is retained separately; no test deadline or engine behavior was changed. Four deployment source hashes are recorded alongside the nine frozen UI hashes. Final exact-head full CI and independent approval remain authoritative in PR #189 metadata.

## Complete real-backend journey receipts

The required separate Pursuits acceptance lane still referenced the old heading and always-visible search toolbar. Only its heading/selectors and opening the existing Filters disclosure were updated; creation, persistence, idempotency, lost-response assertions and all ten warm iterations remain intact. The complete real-backend journey passes: one test in 1.5 minutes on 2,098 synthetic persisted rows.

The source-backed commercial-research lane also passes: one test in 17.4 seconds, including five viewports and read-only account/brief/contact/history behavior. It now expects one Unknown power field, with no MW value, when the backend supplies no useful scope. Source-backed quantified and material-uncertainty assertions remain unchanged. The first seeding attempt correctly refused the non-approved test port; the successful run used a separate disposable PostgreSQL container on the harness-approved loopback port, without weakening the guard. Five measured HTTP reads all returned 200 (227.55–328.25ms); this is synthetic local fixture evidence, not production latency.

Required CI on application/build candidate `8fbf50b36644d20425718098067e7da0a6ecbda2` passed the complete backend suite: **5,210 passed, one optional-probe skip, 11 warnings in 571.11 seconds**. Its browser job exposed the separate obsolete Pursuits selectors above. Final exact-head CI must re-run after the test-only adaptation; the PR check metadata owns that result.

## Build artifact identity and image-build limit

The production-mode Vite artifact was compiled with the actual `8fbf50b36644d20425718098067e7da0a6ecbda2` source revision, production environment and package version 0.1.0. A programmatic check verified all three values in the compiled JavaScript. This proves build identity wiring, not deployment.

The optional local Docker build is **unverified**. It failed at the unchanged `npm ci` dependency-install instruction, before the new build guard, with npm registry requests reporting `SELF_SIGNED_CERT_IN_CHAIN` in this managed proxy environment. Standard proxy forwarding and a temporary BuildKit mount of the existing platform CA did not resolve it. No TLS checks were disabled, no production trust configuration was changed and no image was deployed. The tracked Dockerfile's guard wiring was independently reviewed and its 24 actual shell/configuration tests pass. The Vite production build and required CI web build pass. This environment-specific image-build limitation is explicitly retained, not relabeled as a pass.

## Supplementary push-check qualification repair

The required PR workflow on `82321a59da9bed17b20e4a73136b43ae7253755c` passed all five jobs, but its separate push workflow failed the commercial-research test. Final overall acceptance was explicitly paused rather than ignoring that supplementary check. The failing assertion discarded a whole limitation array entry whenever generic Unknown wording occurred anywhere inside it; the actual UI correctly retained the material clause “Campus, IT, or equipment nameplate amount is not rental demand.”

The test now splits semicolon-delimited clauses and excludes only complete generic boilerplate clauses. All scope, material-caveat, unknown/no-MW and campus-40MW-not-rental assertions remain intact. A new explicit mixed-string fixture verifies the material caveat remains visible independently of the seeded representative need. No application or backend source changed. The complete affected account module passes 17/17 in 29.5 seconds, and the real commercial-research journey passes 1/1 in 20.3 seconds after the repair. Final acceptance requires both push and PR checks on the corrective head. The failed supplementary run remains a failed receipt.
