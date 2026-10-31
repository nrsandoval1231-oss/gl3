# Phase 1 reliability candidate — October 31, 2026

## Scope and authority

Owner authorized bounded Phase 1 code, isolated tests, scoped commit/push and a **draft PR**. Merge, auto-merge, deployment, production business-data writes, ingestion/backfill, paid providers, credential/provider changes, new infrastructure/spending and the user's PC remain unauthorized. See [current request](../../.agent/OWNER_REQUEST.md). Initial refreshed main: `593cfd516d82a12b66558f53b975ad6c2b711517`; no open PRs returned at task start. Existing original checkout and all retained evidence/data were preserved.

CURRENT candidate preserves project-first presentation and project/need IDs. TARGET company-centered primary browsing is a later intentional presentation change, not evidence that multiple rows under one operator are corrupt duplicates. NEXT is independent review/full exact-candidate gates and draft handoff. DEFERRED: company aggregation, demand/ingestion/enrichment expansion, RRC catch-up/status monitoring, merge and deployment. Historical Diamondback counts and identical-looking Pecos rows require reproduction before deduplication.

## Verified defects and repairs

- Company/Project controls sorted only the loaded page; the backend now orders scalar representative company/visible-project keys across the full cohort before LIMIT/OFFSET. Stable asset-key ties, nulls-last and explicit ascending priority retain deterministic paging. Project sorting strips the exact displayed company prefix, matching the visible project name without altering returned identity/name. Sort participates in request, cohort, URL, cache, navigation and offset reset. API schema/types are regenerated.
- Empty page filters could show an inverted range (`1–0` in synthetic reproduction; the owner handoff reported `26–25 of 2032` live). Footer now separates visible page matches from the unfiltered server page/total. Page-filter scope remains explicit.
- Changing sort beside selected detail could schedule an asynchronous history Back that undid the new sort. Browse changes clear detail synchronously; explicit detail Back remains unchanged. New browser regressions cover selection, back/reload and browser history.
- Retained evidence loading selected Interpretation but re-read its binding per rejected row. The existing bounded query now preloads Observation/Interpretation/Source and passes them to the existing fail-closed validation helper. Pagination, accepted-version/project/source rules, four-document limit and explicit target path remain intact. No identity, provider, classification or schema change.
- Maintained runtime/recovery guides no longer present October 20 unknowns/holds as current operational truth. Dated wrapper/release evidence is retained; current API/worker revision and rollback outcome remain unverified. Earlier deployment instructions are archived, not authorization for this draft.
- Fresh backend advisory audit identified seven pypdf 6.21.2 resource-exhaustion advisories. Pin and lock advance only to patched 6.21.4 (same dependency graph), verified against the [official patch release](https://github.com/py-pdf/pypdf/releases/tag/6.21.4). Patched locked audit reports zero vulnerabilities across 47 entries. Npm now reports three moderate development-tool entries through one minimatch advisory chain (minimatch/Redocly/openapi-typescript), no automatic fix; the existing high-severity gate passes. These are current results, distinct from the earlier zero-advisory audit. No unrelated frontend dependency override was forced.
- Server-scope CSP `frame-ancestors 'none'` and X-Frame-Options DENY cover static, SPA, proxied and error responses. No broader CSP redesign, caching or compression change.

## Red/green and diagnostic evidence

Local receipts are retained under `/workspace/phase1-evidence/`; they contain isolated synthetic data, not production operation receipts.

- Backend global-sort regressions: three failures before implementation; exact-prefix regression also failed before repair. Final focused PostgreSQL selection: seven passed. Tests cover page concatenation, stable ties, nulls, sort-cohort mismatch, route validation and unchanged representative IDs.
- Initial six new browser regressions failed before repair, then passed. First integrated browser regression: **178 passed**, no failures/skips/flaky, 156.065 seconds. Review then added an empty server-page regression (out-of-range offset after shrink/deep link), which failed before a minimal honest-zero footer fix. Seven focused browser cases passed afterward; final179-test receipt follows below. Includes genuine local authentication, pending/retry behavior, privacy/session continuity, responsive detail/back and existing domain cases. Retained-source/live-worker suites were not run on empty isolated data.
- Loader query-growth regressions failed before optimization (15/64/162 SELECTs for 1/25/73 rejected rows plus accepted documents), then passed with bounded page-query counts. Seven current/stale/rejected/missing/wrong-project binding cases remain asserted. New loader plus full shadow module: **25 passed**.
- A full buying-chain diagnostic was interrupted after eight failures/22 passes. Comparing the same failed test against unmodified main proved an October 31 fixture-clock expiry: fixed September 30 observations exceed the 30-day freshness policy. Baseline passed at the fixture-valid historical clock. The module's default reads are now anchored at October 29; explicit nested evaluation clocks, production freshness, leases/auth time and assertions are unchanged. Full module after fixture correction: **119 passed**. Raw failed receipts remain recorded; they are not a preload regression or suppressed result.
- The first strict full-suite attempt also exposed a Dallas unit fixture expiring on October 31: its fixed August 1 report is91 days old, correctly outside the unchanged90-day source window. The same test and adapter were byte-identical to baseline, where the failure reproduced. Only the test now anchors Dallas retrieval to October 1, matching its adjacent parse fixture; inherited date parsing and all official-host assertions remain unchanged. The complete unit file passes 12 tests. The first full-run failure remains in receipts; final full-gate outcome is recorded below.
- The original one-second shadow-lock test is unchanged and passes in focused testing. Profiling proves bounded request preparation occurs before a nonblocking try-lock, but does not establish the cause of the earlier full-run deadline failure. No lock movement, timeout increase or assertion weakening was used. The original failed full audit remains historical evidence: 3650 pass/one fail/one skip/seven subtests in 625.84s, followed by three isolated passes; never a green gate.

## Local performance: bounded and separated

### Retained context query profile

Same isolated synthetic fixture at 1/10/100 evidence records, fake judge, no real provider calls. With the daily lock held, request SELECT/SQL counts fell **22/31/125 → 21/21/25**; at 100 records, project-state queries fell **116 → 16**. Equivalent attempted/judge outcomes and evidence-binding regressions are retained. Profile wall times were affected by concurrent checks and did not establish a latency improvement. Do not claim that this optimization solved the original one-second failure.

### API baseline and candidate

Fresh disposable PostgreSQL 18.6; 2,032 synthetic projects, two needs each (4,064 rows), 50 companies, 1,915 O&G/18 data-center/99 other projects, page size 25. No real entity or permit data. This is a projection read workload, not a retained-source rebuild or commercial-identity benchmark.

Actual local opaque session and FastAPI TestClient; each case has one first request plus30 serial warm requests, no concurrent load/stress. Includes auth SQL/serialization; excludes network/browser rendering. First request is only client/session-cold: process, PostgreSQL and OS caches may already be warm. Query plans were captured with EXPLAIN ANALYZE/BUFFERS; p95 is nearest-rank from30 local samples, not an SLA estimate.

| Case | Warm p50 ms | Warm p95 ms | Response bytes |
|---|---:|---:|---:|
| Main priority baseline |27.96|29.67|38135|
| Candidate priority |27.38|29.19|38135|
| Candidate company |33.67|45.15|38131|
| Candidate visible project |38.66|40.79|37701|
| Candidate search (41 matches) |20.97|22.68|38129|
| Candidate next page |26.82|29.08|38136|

Each sample used four SQL statements, including authentication and current-generation reads. Query execution median was about19ms priority,25ms company and30ms project; remaining in-process overhead includes ORM/serialization/dispatch. No production speed improvement or material priority-baseline speedup is claimed. Local JSON, harness and per-case plans: `browse-benchmark.*`, `plan-*.json` under the receipt directory.

### Public versus authenticated browser limits

The earlier public-sign-in cloud-proxy medians were desktop866/408ms and mobile viewport605/371ms cold/warm (n=3 each). They are not signed-in API timings. Warm loads transferred963,681 bytes; normal browser Accept-Encoding gzip/deflate/br/zstd received no-store/uncompressed JS/CSS on that observed proxy path. Origin/edge responsibility remains unverified; no cache/compression configuration was changed. Private API/auth caching requirements remain intact.

The owner handoff reports authenticated live search/filter/details/evidence/contact/back checks and counts2032 All/1915 O&G/18 DC. Native authenticated production timing sample count remains **zero**; browser tool limitations prevent a credible production server/network/render split. The earlier local fixture browser timings likewise exclude real API/network cost. Proposed performance targets require a representative authorized baseline; this PR does not declare them met. Error recovery was not established by the live handoff. Contained mobile/tablet table scroll is a usability limitation, not demonstrated broken layout.

## Framing and operations verification

The standalone app has no ordinary cross-origin embed contract in current UI. Real local nginx1.28-alpine configuration syntax passed; responses from static200, SPA-deep-link200 and API/OpenAPI502 all had both security headers. Initial fixture403 came from disposable directory permissions and was corrected; it was not hidden as a product failure. Local runtime response receipt: `/workspace/phase1-security-runtime/responses.json`. No production configuration or header was modified.

Historical completed PR148/schema0049/74-table evidence and e97 canary/rollback-in-progress checkpoint are distinct. New maintained docs do not infer a completed rollback or current backend from static frontend bytes. Any later release needs current image/schema/source identities, fresh authorized backup/restore and forward-schema rollback evidence through established machinery.

## Integrated gates and review

Final local backend gate: **3667 passed, one intentional external live-probe skip, seven subtests passed, 11 warnings, 350.31 seconds, exit0**, using `timeout 480 .venv/bin/pytest tests -n 4 -v --tb=short`. The original one-second shadow test passed unchanged. The first strict attempt is preserved separately:3666 passed/one Dallas fixture failure/one skip/seven subtests in338.45s. A passing rerun does not erase that diagnosed failed attempt or prove the original audit timeout's cause.

Fresh migration upgrade/check passed. An isolated dump restored into a separate disposable database with `--exit-on-error` matched0049/74 tables. Ruff check/format (425 files), mypy (190 source files), doc links, brand structural checks (216 assets/eight AA pairs), patched backend audit (47 entries/zero vulnerabilities), brand audit (13/zero) and npm's existing high-severity gate passed. Three moderate development-tool entries remain, with no automatic fix. An initial mypy invocation from the wrong directory omitted backend configuration and reported two missing-stub errors; the prescribed backend-directory command passed. An initial advisory tool cache path was read-only; rerunning with a writable cache completed. These setup errors are not hidden as product defects.

After `npm ci`, frontend typecheck/build passed and JS/CSS hashes matched the179-test Node24 run exactly. The prescribed Node22.23.4 recheck also passed: **179 browser tests, zero failures/skips/flaky, 144.274 seconds**, plus frontend typecheck and production build. The Node24 receipt is preserved separately; no test assertion or retry policy was weakened. Retained-source/commercial-real browser suites remain excluded on isolated data; no live worker or source/provider call was used.

Independent integrated source review and the repository-requested Astra/high review found no concrete blockers. Their exact file manifests include all production, dependency, test, config and archive changes. Final receipt-only documentation is reviewed separately; no formal GitHub approval or merge is implied. Full CI retains its existing four-worker 480-second backend gate; local incomplete/failed runs are reported as such and never replaced with historical results. No mandatory tests are removed or weakened. There is no schema migration or new runtime dependency.

## Later phases and unresolved limits

Company-centered grouping/projections/API/UI and broader electrical demand/contacts/ingestion changes require separate bounded work. Raw permits remain evidence, not automatic customers/leads. Preserve legal entities, physical projects and electrical needs. RRC flare acquisition still has the documented three-submission-day limitation; plan durable catch-up and retained-ID status refresh later without claiming a specific live filing is missing. RRC drilling current/prior-month correction coverage remains explicit.

Publishing a draft is not approval to merge or deploy. Current production backend, worker state, provider availability/budgets, scheduled freshness, backup retention and final rollback outcome remain unverified by this repository-local task.


## Future release/rollback compatibility

This is a draft source candidate, not a deployed repair. `saved_browse.POLICY_VERSION` fingerprints backend source, so these code changes intentionally require a compatible derived browse generation for the selected application/worker revision. A separately authorized release must prepare/verify that generation and retain a compatible previous image/generation rollback path; mixed policy versions fail closed and must not be presented as fresh data. No production browse rebuild, ingestion, migration, backup/restore or cutover was executed here. The pypdf security patch changes the candidate image dependency, not historical evidence. Current runtime-image/OS advisory scanning remains separate from package audits.


Final acceptance: global cohort sorting, both empty-range cases, stable IDs/cohorts, detail/back/history, current evidence binding/query bounds, deterministic fixture clocks and compatible framing all passed their focused regressions and integrated suites. Independent source and Astra/high reviews found no concrete blocker; exact non-Markdown hashes remained unchanged through final validation. Original shadow-timeout cause, native authenticated production speed and edge/cache attribution remain unproven. GitHub CI is a separate post-publication gate and must not be inferred green from local tests. This candidate is draft-only and has not been merged or deployed.
