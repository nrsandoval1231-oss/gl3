# Canonical reference UI — October 29, 2026

Objective: implement the owner's attached 1280×720 reference in the existing React application. The current mission supersedes older visual layout prescriptions. Preserve backend APIs, organization/project identity, authentication and provenance. No deployment, paid-provider calls or production writes.

Branch: `feat/canonical-reference-ui-20261029`, based on local main `629b2c83` (includes an existing unpushed documentation commit).

Ownership: Luna header component; Luna ProjectResults/table; Luna detail component; Sol integration and verification. Independent Astra review follows integration.

Acceptance: compact navy horizontal header, three honest KPI cards, approximately 56/44 table/detail layout, real API data and no fabricated contacts or metrics, responsive detail navigation, retained caching/cohorts, two visual passes and relevant checks.

Inspection: React 19/TypeScript/Vite, plain scoped CSS, FastAPI/PostgreSQL. Default browse uses server-paginated operator/customer groups and atomic group-open projects. Need detail has current-cohort guards. Keep those contracts intact. Header-only routes for Developers/Power Supply/Reports have no complete standalone product counterparts; connect existing account/supply/change views honestly. Follow/completion APIs are absent. Existing active brand is a two-tone G/L; no isolated metallic screenshot mark was found.

Verification in progress. Production was observed unauthenticated at sign-in. Local API starts but retained environment database credentials fail authentication; no retained or production data/settings were changed. Browser contract fixtures will be explicitly synthetic test data, never product fallback data.

Next: integrate components, run build and focused/regression browser checks, compare desktop/mobile captures with the reference twice, resolve review findings, record actual remaining limits and create a draft PR if acceptance remains blocked.

## Implemented candidate checkpoint

The default now uses the existing flat project-results API, 25 rows per server page. Secondary `groupBrowse=1` retains original operator/customer grouping and `accountBrowse=1` retains account research. Three compact KPIs, source-identical cropped header artwork, a 56/44 table/detail composition, verified contact methods, evidence status/dates, and existing deep evidence/research/supply views are integrated. No backend/model/migration/configuration changes.

Three Luna builders, an additional Luna verification builder, and independent Astra review ran through supported runtime roles. Review found and repaired the error-state render loop, logout/cache race, date-only timezone shifts, qualifier-loss parsing, contact-authority ambiguity, stale interactions and exact need focus restoration. A final long-name overflow was traced to absolute screen-reader labels outside their table scrollport; the wrapper now establishes their containing block.

Latest completed full browser run: 167 passed; an additional malformed-payload regression and final layout corrections are under final serialized verification. Production build, TypeScript, npm audit, Ruff/mypy, migration compatibility, maintained-doc links and all 216 protected brand-asset checks passed. Backend full run initially had 3305 passed/4 environment failures/1 skipped/7 subtests: the disposable application database lacked auth tables. Migrating that separate database fixed all four targeted cases; a clean full xdist run is in progress. No retained database credentials, schema or data were changed.

The production bundle showed the shell in 111 ms under a synthetic 1000 ms API delay with one initial browse request. This is a controlled local check, not production-service performance evidence. Header derivatives total 27,378 bytes; original approved artwork remains in design references. The protected vector masters and their manifest are unchanged.

No Follow/completion endpoints exist in the retained API; the UI does not fake those states. High Priority/New This Week and historical growth remain neutral without supported metadata. Page-local region/stage/rank filtering is visibly identified; search/project type are server-wide. Mobile has controlled table scrolling and a dedicated selected-detail view. Production was inspected only at unauthenticated sign-in; real retained/production populated-data acceptance remains unverified.

Next: freeze source, finish final checks, obtain exact-candidate Astra review, record visual/verification receipts, and create a review PR. No merge or deployment is authorized.

## Final source validation

Frozen source `d41d4e179edf80147b78486398aa7582fab92bce` passes 168 serialized browser regressions and a clean full backend run: 3309 passed, 1 skipped, 7 subtests passed (403.56 s). Build/types, audits, Ruff/format/mypy, migrations, 216 protected brand assets, maintained docs and diff checks pass. The earlier four missing-table errors were corrected by migrating the isolated application database, not by editing application behavior.

The [delivery receipt](../../docs/validation/canonical-reference-ui-20261029.md) and [visual QA](../../design-qa.md) contain synthetic screenshot comparisons, complete limitations and exact commands. Independent final Astra review is requested against this source hash. Remaining: record that verdict, commit only delivery documentation/evidence, push and open a review PR. Production remains unchanged; Follow/completion APIs and authenticated production-data acceptance remain unavailable.

## Handoff

Independent Astra approved exact source `d41d4e179edf80147b78486398aa7582fab92bce`: no unresolved P0/P1/P2 findings, 10 independent focused browser cases plus fresh build/diff checks passed. Full verifier evidence remains 168 browser cases and 3309 backend tests passed, as separately recorded. Only delivery documentation and synthetic screenshots follow that source commit; application code is frozen.

The focused branch is ready for draft-PR review. Next owner action is to review the documented absent API capabilities and real-data/live acceptance limits before authorizing any merge or deployment. No deployment, paid-provider execution, production mutation, credential rotation or outreach occurred.

## PR #148 CI follow-up — October 29, 2026

Owner requested CI repair and remaining validation, explicitly no merge/deploy. Exact-head CI808ac9cf passed all gates (3309 backend pass/1skip;166 browser first-pass plus2 retry-pass). One Luna builder owns the tightly coupled grouped-browse timing test repair; Sol independently checks the full35-case file. Tests switch fastForward to runFor without relaxing assertions; product source unchanged. Fresh production read-only probe confirms Sign in and protected health401, no credentials tried. Real-source acceptance remains blocked by unavailable authenticated populated environment; no providers or data writes were activated. Next: push the timing-test fix and verify final-head CI, keeping PR draft and production unchanged.

Final CI repair: Astra reproduced wall-clock drift and intercepted StrictMode-count variance, then repaired the four tests with mounted-response clock pauses and explicit response phases.40/40 repeated no-retry focused executions plus independent Sol4/4passed. Browser CI now runs for web-only changes as well as backend changes; Astra checked its truth table. Product source remains unchanged. Final step is exact-head CI after committing this bounded test/workflow/doc repair; no merge/deployment permitted.

## Owner follow-up: All Signals and contact channels

Objective: make the canonical default All browse include real Signals explicitly, preserving qualification and existing API defaults, and populate actual retained phone/email channels with truthful source/verification/authority labels. Owner requests authenticated real-snapshot verification and updating PR148; no merge/deploy.

Starting branch feat/canonical-reference-ui-20261029, commit fa673cd4; clean. Three independent Luna scopes: opt-in API/client browse fix; sourced contact display; new All-view browser regression and private real-data contact audit. Sol integrates, runs final checks/captures; independent Astra reviews integrated change. Existing private production-derived copy canonical_real_20261029 is read-only for validation; disposable tests use separate databases. No production writes, paid provider activation, fabricated contact methods or inferred addresses permitted.

Acceptance: initialAll fetchexplicitly includesSignals and realresults; pagination/search/filter retain same scope; noSignalpromotion; contact phone/email actionable onlywhen supported, eachmissingchannel explicit; companyroute distinct from directperson/authority; realauthenticated desktop/mobile captures; focused/fullrequiredCI and review before handoff.

## All/contact verification checkpoint

Default All now explicitly includes Signals while the API preserves qualified-only compatibility. Real authenticated snapshot verification shows 1,896 projects, server pagination, search and mobile Clear; EOG Leviathan C Well 3H shows actual sourced phone and email without claiming buyer authority or deliverability. Contact attribution is guarded by selected need identity. Three Luna builders completed independent scopes; Astra independently reviewed source and real-data boundaries with no unresolved material findings (changed-source digest 5af680147f7ba37dd23026bc23bd5db1f42c11ac75d4645fc7e44a6c1bdc99db). Backend 3,309 passed / one skipped / seven subtests; focused regressions, types/build, Ruff/format/mypy, docs and brand passed. Final full browser and exact-head CI remain to record in PR #148 before handoff. No merge or deployment is authorized.

Final local full browser rerun passed 169/169 with retries disabled after all source changes. Real snapshot recapture passed All 1,896, pagination/search, actual phone/email and mobile Clear with no page errors. Source and review frozen; next action: push focused PR #148 update and await exact-head CI. Keep draft, do not merge or deploy.
