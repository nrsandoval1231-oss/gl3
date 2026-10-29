# Canonical reference UI delivery — October 29, 2026

Source candidate: `d41d4e179edf80147b78486398aa7582fab92bce`, on `feat/canonical-reference-ui-20261029`, based on `629b2c83`. This records implemented and locally tested source, not a merged or deployed release.

## Result

The Opportunities default now follows the owner reference: compact navy horizontal navigation, exact metallic G/wordmark/subtitle artwork, confined architectural art, three honest compact KPIs, a dense project table, and adjacent selected detail. The existing server-paginated flat project API is reused. Operator/customer aggregation remains at `?groupBrowse=1`; account research remains at `?accountBrowse=1`. No backend API, model, schema, provider setting, retained data or production configuration was changed.

Search/project type use the server cohort. Region/stage/rank filtering and sorting apply to the loaded page and are identified as page filters. Selection, history/focus restoration, related needs, export, qualification labels, contact verification/authority, dated evidence, raw-source chunks, research, supply drilldown, logout/cache invalidation and responsive navigation remain functional. Long and qualified MW source values remain verbatim. Missing information remains unknown.

## Visual evidence

All populated implementation screenshots below use explicitly synthetic, intercepted browser-test records. They do not establish real corpus coverage or contact validity. Real production was observed only at unauthenticated sign-in. The retained local environment's database credentials failed; validation used new loopback-only disposable PostgreSQL databases without changing retained credentials or data.

- [Approved source](../design/references/canonical-opportunities-20261029.jpg)
- [Combined source/implementation comparison](canonical-reference-ui-20261029/comparison-synthetic.png)
- [1280×720 desktop](canonical-reference-ui-20261029/desktop-synthetic.png)
- [390×844 selected detail](canonical-reference-ui-20261029/mobile-detail-synthetic.png)
- [390×844 list](canonical-reference-ui-20261029/mobile-list-synthetic.png)

At least four review/correction passes were completed; [visual QA](../../design-qa.md) records the findings. No pixel-perfect claim is made. The logo is a faithful raster extraction from the exact approved image, not a newly authored vector master. Browser captures extracted `(28,8,285,40)` and `(1086,0,145,53)` from the 1280×720 source. The two PNGs total 27,378 bytes and live outside the protected generated brand asset directory; all existing vector masters and 216 manifest assets are unchanged.

## Verification

| Check | Actual result |
| --- | --- |
| `npm run test:ci -- --workers=1` | 168 passed, including real disposable-API login/reload/sign-out, canonical browser journeys and retained grouped/account regressions |
| `npm run typecheck --prefix web` | Passed |
| `npm run build --prefix web` | Passed; JS 417.31 kB / 120.26 kB gzip, CSS 101.29 kB / 17.46 kB gzip |
| `npm audit --prefix web --audit-level=high` | Zero vulnerabilities |
| `uv run --extra dev pytest tests -q -n 4` | 3309 passed, 1 skipped, 7 subtests passed; 403.56 seconds |
| `uv run ruff check src tests` | Passed |
| `uv run ruff format --check src tests` | 401 files already formatted |
| `uv run mypy src` | No issues in 183 source files |
| `alembic upgrade head` / `alembic check` | Disposable databases migrated through 0049; no new upgrade operations detected |
| Pinned backend dependency audit | 48 packages, zero vulnerable packages |
| `python tools/brand/validate.py` | 216 assets, integrity and eight semantic AA pairs passed |
| `uv run --project backend python scripts/check_docs.py` | Maintained documentation graph passed |
| `git diff --check` | Passed |

The first complete backend attempt had four missing-auth-table failures in the newly created application test database. After migrating that separate database, all four targeted cases passed, then the entire suite passed cleanly as recorded above. No product code was changed to hide those failures. Earlier browser failures led to real render-loop, cache-race, malformed-payload and mobile-overflow repairs; tests were retained. Legacy layout tests explicitly use the retained grouped route. Retry tests assert request-count changes from a captured baseline rather than depending on development-mode StrictMode duplicate requests.

The mechanical design detector reported only its generic Inter-font warning; Inter is explicitly required by the owner reference and was retained. React hooks, request cancellation, bounded cache/retries, safe links, method verification, keyboard history and overflow were independently reviewed.

## Performance observations

The built production bundle showed the shell in 111 ms with an artificial 1000 ms browse API delay, one initial browse request, and the table at 1446 ms. This demonstrates that the shell does not block on the dataset; it is not a production-service benchmark or a baseline latency comparison. Only 25 projects are requested per server page; no full-dataset fetch or polling was introduced. The bounded cache expires with server validity and is purged on session end, including while unmounted. Header artwork is 27.4 kB; JS gzip grew by approximately 6 kB from the initial inspected build. Live backend performance and populated production behavior remain unverified.

## Independent review

Astra independently approved source `d41d4e179edf80147b78486398aa7582fab92bce` with no unresolved P0/P1/P2 findings. It ran 10 focused browser tests with its own artifact directory, a fresh production build and diff checks, confirmed a clean source tree, and inspected final desktop/mobile captures and the combined comparison. It did not claim to rerun the separate 168-browser or 3309-backend suites. This is source approval with the limits below; it does not approve deployment or establish overall mission/live acceptance.

## Remaining limits and release boundary

- No existing Follow or action-completion API was found. The UI does not pretend to persist those states; Next Action opens the retained functional research workflow. Implementing new persisted workflow semantics is outside this visual change set.
- High Priority, New This Week and historical growth lack supported API metadata and remain neutral. Active Opportunities is the actual project total, with Signals explicitly included.
- Lifecycle stage and ranking are shown only as supplied. Qualification, rank and contact authority remain separate concepts; no arbitrary High/Medium/Low classes are invented.
- Region/stage/priority filters and sorting are page-local; search/project type are server-wide. Mobile table columns use contained horizontal scrolling, with a dedicated selected-detail view.
- Header destinations without standalone backend products connect existing read-only account, supply and change/report surfaces. They do not imply new backend products.
- Production authenticated visual/data acceptance, live follow/completion behavior, merge and deployment are not established by this receipt. No deployment occurred.

## Modified files

Core: `web/src/components/CanonicalHeader.tsx`, `canonical-header.css`; `web/src/features/workspace/CanonicalOpportunityResults.tsx`, `canonical-opportunity-results.css`, `CanonicalOpportunityDetail.tsx`, `canonical-opportunity-detail.css`, `Workspace.tsx`, `GlobalSearch.tsx`, `ProjectResults.tsx`; `web/src/styles/canonical-workspace.css`; `web/package.json` and lockfile; two UI PNG derivatives; the approved reference image.

Tests: new `canonical_detail.spec.ts`, `canonical_flat_results.spec.ts`, `canonical_shell.spec.ts`; retained `approved_workspace`, `autonomous-research`, `dashboard`, `environment`, `evidence-content`, `pr101-late-regressions`, `pr101-regressions`, `project_cards`, `project_results`, and `workspace` specs migrated only as needed for current versus secondary route coverage.

Documentation: current UI/product canon amendments, this receipt and screenshots, root visual QA, and the existing `.agent/packets/CANONICAL-REFERENCE-UI-20261029.md` task checkpoint.

## PR #148 CI follow-up

CI run [40946937392](https://github.com/nrsandoval1231-oss/gl3/actions/runs/40946937392) passed on exact head `808ac9cf7a2b85840243dcdd9e6406fcce77ecef`: backend 3309 passed / 1 skipped; web, brand and path checks passed. Browser result was 166 first-attempt passes and two retry passes. The two grouped-browse cases advanced retry/cache-expiry clocks with `fastForward`; the follow-up uses `runFor` so intervening timer work is executed. Existing request-count, retry exhaustion, manual retry and cache replacement assertions remain intact. No product source or CI retry policy changed.

Fresh read-only Chromium production probe returned HTTP 200 and rendered Sign in; `/api/health` returned 401. No production login was attempted. The earlier temporary local API is no longer running. Populated retained/live source acceptance still requires an authenticated populated environment; PR CI deliberately excludes live-acceptance/commercial-real suites. Existing absent Follow/completion/KPI metadata remains unavailable rather than fabricated. No merge or deployment is authorized or performed.

Follow-up local verification: the affected four retry/expiry tests passed in an independent no-retry run. The updated grouped-browse file passed 35/35; a later repeat had one unrelated initial-navigation timeout (34 passed), with no timer failures. Additional focused repetitions are recorded in the final handoff. Parent/child tests now await client retry status before advancing the Retry-After boundary; assertions remain unchanged. This test-only repair does not claim every potential browser timing flake is eliminated.

Final escalation found two concrete harness causes: `clock.install()` advances with wall time, and aborted StrictMode mount requests do not have a guaranteed intercepted count. Tests now freeze at a mounted response boundary before timers are created, capture the initial request baseline, and explicitly change mock response phase. Exact early-boundary, three automatic retries, exhaustion, manual retry and generation replacement assertions are retained. The affected four cases passed40/40 parallel repeated executions without retries, plus an independent Sol4/4. The earlier runFor-only repair was insufficient and is superseded.

CI also skipped browser tests on web-only branch pushes. The browser job now runs when either backend or web paths change; all four truth-table combinations were independently reviewed. No application source, backend contract or CI retry setting changed. Final-head CI will be recorded in PR148; source receipt remains historical to its stated hash.

## All Signals and real contact channels follow-up

The owner requested default All inclusion of real Signals and populated phone/email, authenticated snapshot verification, and PR #148 update, without merge or deployment.

The canonical client explicitly requests `include_signals=true`. The mounted API exposes the existing internal flag and validates it; existing callers still default to qualified-only scope. Scope remains bound to the pagination cohort, qualification does not change, and KPI wording follows the response. Generated OpenAPI/types were refreshed, also reconciling an already-mounted atomic group-open endpoint missing from the prior schema snapshot.

Contact Overview displays retained phone/email through safe call/mail links with source/date and authority labels. The first phone and email appear together; exact duplicate company routes are suppressed, distinct company paths retained, and the arbitrary first-two-contacts cutoff is removed. Undated methods require matching current method-specific source support. Missing channels remain individually unavailable. Company routes do not establish a named person's purchasing authority or address deliverability. Project metadata and contact routes are bound to the selected need ID, hiding previous-selection data immediately while a new request is pending or fails. No contact addresses were guessed, fabricated or newly enriched.

### Authenticated real-data verification

The private isolated October 29 production-derived snapshot contains 1,969 projects and 1,966 power needs; production authentication rows were excluded. Only local retained-data summaries were rebuilt after the backend source/policy fingerprint changed. No acquisition workers or paid providers were started.

- Unauthenticated discovery request: 401.
- Authenticated legacy All request: 200, zero qualified projects, unchanged default.
- Explicit Signals All request: 200, 1,896 discovery projects, 25 server-page rows, retained Signal classifications.
- Pagination to offset 25 retained the 1,896-project scope; search, selection and mobile Clear returned the expected real records.
- Switching a discovery cohort to qualified-only scope returned 409; malformed boolean returned 422.
- Real EOG Resources Leviathan C Well 3H displayed its retained company phone and email together. Two phone and three email methods have source URLs and verification dates; purchasing authority remains unconfirmed.
- Desktop 1440/1280 and mobile 390 captures used the real API and database, with no response interception or synthetic records. No browser page errors; the sole non-GET request was ordinary local login. Private captures and machine receipts remain under ignored `.artifacts/canonical-all-contact-review/`.

Snapshot coverage is limited: 187 saved rows contain phone actions, 15 contain email actions, and four projects contain both. These are snapshot observations, not universal contact coverage or deliverability claims. Data-center email gaps remain explicit. This supersedes the earlier empty-All defect; it does not imply PR #148 is deployed.

### Checks and review

The full backend suite passed: 3,309 tests, one skipped, seven subtests passed (426.53 seconds). The scope/tier/cohort regression was then strengthened and its two focused integration tests passed. A full 169-case browser run passed without retries before the final contact ordering/identity guard; affected tests passed afterwards and the final full run is recorded in the PR handoff. TypeScript/build, Ruff/format, backend-directory mypy (183 files), maintained docs and all 216 protected brand assets passed. An initial mypy invocation from the repository root lacked backend configuration; the corrected backend-directory check passed.

Independent Astra review found no unresolved material findings, verified the real-data API boundaries and EOG contact provenance, and ran two focused browser cases plus fresh types/build/diff checks. Reviewed changed-source digest: `5af680147f7ba37dd23026bc23bd5db1f42c11ac75d4645fc7e44a6c1bdc99db`.

The npm high-severity audit gate passes, with one newly reported moderate Vite development-server advisory. No unrelated forced dependency upgrade was performed. Exact-head CI is linked in PR #148. No production credentials, retained data, deployment settings, schema, provider budgets, merge or deployment changed.

Final integrated local browser rerun: **169 passed, retries disabled (1.6 minutes)**, including the completed contact ordering, deduplication and identity guard. Final real-snapshot captures and checks were repeated after that guard: All 1,896 projects, pagination, search, real phone/email and mobile Clear passed, with no page errors. Independent review is clear. Remote CI on the final committed head remains the release gate; PR stays unmerged and undeployed.
