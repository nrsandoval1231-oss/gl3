# Phase 2 validation — November 8, 2026

This record separates implemented source, deterministic fixtures, independent review and final acceptance. **Local validation is complete at source `a4e326d87650218b2c978e139c1ccb442952c015`.** Independent source review is accepted; the resulting draft PR and exact-head CI are the publication record. No merge, deployment, operational retained-data mutation, credential change, source activation, paid-provider request or outreach is authorized by this task.

## Same-fixture reference

[Final sanitized comparison](matched-fixture-summary-a4e326d8.json) records the independently executed v5 pair at baseline `bc433650ce4706dddfb5b30d78a502e3b528f54e` and candidate `a4e326d87650218b2c978e139c1ccb442952c015`. Earlier [ffc3](matched-fixture-summary-ffc3c890.json) and [e598](matched-fixture-summary-e5983baa.json) pairs remain historical source-specific references. Raw captures/logs remain ignored under `.artifacts/phase2/`.

- Fixture SHA256: `15e29ff076b6f1c02a3cd11ac18c76a86e716f34d3daa660b23ae93da3531111`.
- Imported GridLens package marker SHA256 (`gridlens.__file__`, raw capture `imported_module_sha256`): `7eb70257593da06f682a3ddda54a9d260d4fc514f645237f5ca74b08f8da61a6`.
- Evaluator SHA256 (nested `commercial.evaluator_sha256`): `fde98d53cde8a7b16d24e4518c9f7e11ca35664576bcda025e503651a8abdcd2`.
- V5 before/after aggregate of **346 tracked files**: `c03a7f2c57169adeaecfad7453f92cf7b20db685749dbe816ca92330d2144835`, unchanged. Scope is `backend/src`, `web/src`, and `scripts/phase2_metrics.py`; algorithm is SHA-256 over UTF-8 compact JSON of sorted relative-path/byte-SHA256 entries. This explicit v5 scope is different from earlier 416-file receipts. Both captures and comparison passed with same-HEAD/clean-source guards; imported application module hashes were verified.

| Synthetic fixture metric | Baseline | Candidate a4 |
|---|---:|---:|
| Canonical accounts / physical projects / needs | 2 / 4 / 5 | 2 / 4 / 5 |
| Common source-backed Why now + justified action | 4 / 5 | 4 / 5 |
| New structured brief contract | 0 | 4 |
| Unique generic methods | 2 | 1 |
| Relevant named contacts / named methods | 0 / 0 | 0 / 0 |
| Known power amounts | 0 | 0 |
| Paid-provider logical requests | 0 | 0 |
| Synthetic mocked provider dollars | $0 | $0 |
| Actual provider cost | Unknown/unverified | Unknown/unverified |
| In-process account-project read p50 / p95, milliseconds | 4.77 / 12.21 | 16.17 / 25.75 |
| Fixture workflow elapsed, milliseconds | 5,695.35 | 11,711.77 |

The candidate removed an unverified `acme.test` method while retaining the RRC method; this is a quality filter, not increased contact coverage. Structured-field presence is separate from the unchanged common usefulness measure. All four power amounts remain unknown: candidate scopes are two construction-temporary, one commissioning and one campus-capacity. No campus, IT or nameplate MW is added to rental demand. Zero fixture conflicts does not establish conflict-free production data.

Ten initial jobs were scheduled; the later bounded retry makes eleven recorded outcomes (three successful jobs and eight failed/blocked research outcomes). Those eight are not accepted findings or completed commercial research. The fixture checks replay/entity/spend deduplication and outage recovery; the candidate reaches retained/native route checks and reports disabled discovery honestly. This fixture recorded zero buyer handoffs; separate real PostgreSQL planner-order and claim-only handoff tests prove that contract. Zero mock dollars/zero paid calls per four useful fixture needs is not a verified live cost per accepted enrichment.

There was one matched capture per source. Read latency uses five repeated **direct in-process `account_projects` database reads**, not HTTP. Cold-cache state was not controlled. Candidate reads and workflow were slower. Pytest wall times were 10.10 and 14.48 seconds. Hardware: Intel Core Ultra 5 225F, 10 cores, 31.5 GiB RAM, local Windows; Python 3.11.16, PostgreSQL 18.6, uv 0.13.4. This small synthetic fixture is not production coverage, production lead quality, a billing receipt or a scale benchmark. The source-specific browser HTTP measurement below is a separate surface, with no matched HTTP baseline.

## Reproduction boundary

Run from the repository root with the existing locked backend environment, newly created reserved loopback-only databases, privately generated process-local test authentication, disabled providers and blank provider keys. Set `DATABASE_URL` to the separate `gl3_phase2_acceptance_app` database; set `TEST_DATABASE_URL` to the exact selected fixture database for each capture. The runner rejects routing overrides, unknown database names, dirty tracked/untracked Python source, receipt overwrite and mismatched fixture/evaluator hashes. Do not point these commands at retained or production data.

```powershell
uv run --project backend python scripts/phase2_metrics.py capture --mode baseline --database gl3_phase2_baseline_fixture_test --source-root <managed-base-checkout>/backend/src --output <new-baseline-receipt.json>
uv run --project backend python scripts/phase2_metrics.py capture --mode candidate --database gl3_phase2_candidate_fixture_test --source-root <candidate-checkout>/backend/src --output <new-candidate-receipt.json>
uv run --project backend python scripts/phase2_metrics.py compare --baseline <new-baseline-receipt.json> --candidate <new-candidate-receipt.json> --output <new-comparison.json>
```

Use verified source roots; changing `PYTHONPATH` alone is insufficient because pytest config sets its own source path. The runner verifies imported source paths, hashes and checkout revision. A source/evaluator change requires a new pair. Do not compare this fixture with the historical November 7 population or purposive sample.

## Final browser seed

The final disposable seed is `.artifacts/phase2/browser_fixture_final_ffc3c890.json`, SHA256 `5933feb2dd2c90e8a643aa7911652e8dfebbfb75b7c6e1a49da0a8e618ea10f3`. Its source commit is `960218831bfa6d93edeecf01b94927d4fba34fb8`, a documentation-only descendant of the matched source. Independent verification matched all 18 imported candidate module hashes plus production/harness/acceptance bytes to the accepted pair. Fixture and evaluator hashes above also match.

The new browser application and backend test databases are separate on the task-owned loopback cluster and migrated to 0051. The application fixture retains two accounts, four physical projects and five needs; the primary account has three projects/four needs, with a separate conflicting-identifier lookalike. Two company jobs succeeded, eight question jobs honestly blocked, and logical-call, budget and settlement counts are zero. External transport is deterministic only.

For reproduction, migrate each new disposable browser database from `backend/` with `uv run alembic upgrade head`. Then invoke the existing seed runner from the repository root:

```powershell
uv run --project backend python scripts/phase2_metrics.py seed-browser --database gl3_phase2_browser_fixture_test --manifest-output <new-browser-manifest.json> --source-root backend/src
```

Set `DATABASE_URL` to the exact browser fixture application database and `TEST_DATABASE_URL` to the separate browser backend test database; both use the task-owned loopback endpoint. Generate authentication values privately in process and leave provider keys blank/budgets zero. The browser runner uses `GRIDLENS_PHASE2_MANIFEST` and its own process-local test password, password hash and session secret. No credential is written into the manifest. Existing receipt paths must not be overwritten.

## Real browser journey and HTTP measurements

The historical r3 persisted Phase 2 Playwright journey passed one test in 12.5 seconds before the later backend privacy repair. It verified source-backed card claims, the permitted contact, five widths without horizontal overflow, account open/history, exact physical-project IDs and canonical titles, selected-need contact/action after tab restoration and Back to account, no automatic write requests, and signout/session cleanup on that revision. API/Vite servers stopped afterward; ports 8152/5179 had no listeners. Screenshot files are under the ignored passing run directory `.artifacts/phase2/playwright-final-9192548b-r3/phase2_commercial_brief-so-d429d-ation-and-remains-read-only/phase2-viewports/`:

- Cards: `1648x928.png`, `1440x900.png`, `1280x800.png`, `768x1024.png`, `390x844.png`.
- Account detail: `account-detail-1440x900.png`, `account-detail-390x844.png`.

The tested spec is committed as `976283ff9118d8ef3b70e71f29fd9f9685ddfc55`; frontend typecheck and diff check pass. Root independently inspected all seven r3 images: released brand/four tabs, compact contact/action and optional Sources remain intact, with no material visual finding, visible technical clutter or horizontal overflow. These images, HTTP samples and the original manifest are **pre-privacy-repair**, as well as pre-format/type-repair. Unchanged UI bytes support the visual brand/layout observation, not proof of current backend behavior. The final exact-head CI must supply its own fresh seed, real browser journey and screenshots for current runtime acceptance. No local rerun or relabeled old manifest is implied.

Five authenticated sequential HTTP reads of `/api/opportunities/groups?sector=all&search=Acme%20Incorporated&limit=25&offset=0&sort=priority&shortlist=true` all returned 200 and the expected account/brief. Samples were 165.31, 115.90, 113.87, 173.60 and 111.79 milliseconds; p50 is 115.90 ms and nearest-rank p95 is 173.60 ms. They ran after the initial card load in the same warm local application/database process, before screenshots/detail work, with other heavy gates paused. The hardware/runtime is the local configuration described above. This is one candidate-only development HTTP measurement with n=5, separate from the matched direct database-read surface; it establishes no production or scale SLA and is not a baseline/candidate HTTP comparison.

Two preceding browser runs failed test expectations about restored navigation, rather than application source behavior. Their traces/screenshots remain separate failed receipts; the test now verifies the actual selected-detail restoration, exact parent-account route and canonical project mapping. Only the fresh r3 pass is acceptance evidence.

## Adversarial evidence map

| Contract | Meaningful deterministic evidence |
|---|---|
| Account reuse, distinct campuses/needs, same-name isolation, replay and outage | `test_phase2_acceptance.py`; company planner persistence tests; same physical-project label/need-selection regression |
| Amount class/scope, unknown versus zero, IT/nameplate/campus exclusion, source/date conflicts | `test_commercial_brief.py`; actual retained-ingestion/research-to-brief pipeline, with official Signal MW left unknown |
| Raw/semantic source versions across Opportunities, account brief and Pursuits | `test_commercial_brief_pipeline.py`; accepted-row TDLR native parser/projection regression is a separate contract test, not an ingestion end-to-end claim |
| One paid logical effect, restart, ambiguous SENT state, expiry/policy/source changes | [Acquisition map](acquisition.md); autonomous-question PostgreSQL tests include post-reservation interruption and grouped planner/follow-up mode |
| Exact publisher/method/person/source-version attribution and current cached reads | Native attribution/action unit tests and RRC/P5/Houston/TDLR integration cases; unverified website binding abstains |
| Method suppression after a genuinely visible native phone | `test_phase2_native_contact_privacy.py`: nonempty company/project routes before suppression, absent immediately afterward without rebuild |
| Alias/history privacy and valid UUID evidence references | Saved-history/account privacy tests; original controlled UUID replay failed twice on old source and passes both unchanged assertions at `b21a95e0` after the fixture-order and full sanitizer fixes |
| Retained rows, private lifecycle/identity evidence and public abstention | Full claim/evidence snapshots and LEI/EIN conflict/current-version/person-isolation assertions in `test_buying_chain.py`: 124 passed/one warning; contact-assertion unit module 27 passed at `9192548b` |
| Session/navigation, no browser provider/outreach actions, responsive four-tab UX | Full canonical gate at a4 passed 324 generic browser tests; source-specific real Phase 2 journey passed one test with five card/two detail captures. Final exact-head CI also seeds and runs all real lanes |

Earlier failed comparisons, fixture runs and source findings remain failures in their diagnostic logs. The first pair comparison failed due to nested receipt-hash handling; the repaired CLI has round-trip, mismatch and overwrite checks. Original UUID failures were independently reproduced with controlled legitimate UUID allocations; the repair preserves valid pointers while redacting phone/email controls.

## Capability and final gate limits

The public native directory path is fixture-tested. Existing producers do not supply an authoritative canonical-ID-to-company-domain binding, so an imported domain, footer identifier or email domain cannot establish employer identity. Unverified website contact publication remains blocked; this is not broad official-website coverage. Presence of a business method does not prove deliverability or purchasing authority.

Firecrawl metadata-only search has deterministic contract/recovery tests; remote HTML extraction remains capability-blocked where preventive target redirect/private-network control is unverified. Apollo is an always-blocked no-network interface, not an operational licensed connector. No live/paid smoke was run; actual access, credits, prices and rights remain unverified. See [contact evidence and official documentation](contacts.md).

The `ffc3c890` private-evidence/public-publication separation passed independent scoped review: 20 repository tests and five targeted diagnostic probes, including old/target company and person suppression, native alignment, bounded overflow refusal, cached privacy, and public history/omit-ID modes. Private proof and carry-forward readers preserve raw current evidence; public modes always apply current attribution and suppression. This is scoped source acceptance, not final whole-candidate approval.

The first complete gate attempt failed canonical formatting before tests; the next failed four local mypy typing errors before tests. Both remain failed receipts. The complete run at `e7a13271` then failed 14 tests, with 5,161 passed, three skipped and 11 warnings in 656.98 seconds. Independent RCA found genuine private-state/public-publication defects; those were repaired rather than masked by empty fixture assertions.

The coherent candidate `a4e326d87650218b2c978e139c1ccb442952c015` passed 201 affected tests, then 31 publication/workspace checks after a local annotation correction. Its 25 publication cases cover real native positives, historical suppression scopes, original-side provenance, no-ID/two-person isolation, organization withdrawal, forged payload keys, malformed inputs and valid-neighbor preservation. Independent exact-source review accepted the repaired boundary. Central locked formatting changed four files with identical parsed ASTs and touched no migrations.

Root's full canonical run at `a4e326d8` has passed locked install/dependency audit (zero vulnerabilities), Ruff lint/format (578 files), mypy (266 source files), schema upgrade to 0051 and no-drift check. Backend result is **5,202 passed, three skipped, 11 warnings in 546.59 seconds**. Actual skips are the missing local NC Commerce access probe, unavailable Windows `RLIMIT_AS`, and unavailable Windows symlink privilege. Frontend locked install/audit (zero vulnerabilities), typecheck, production build and **324 generic browser tests (2.1 minutes)** pass. The complete script exited zero in **734.08 seconds**; API/Vite teardown was verified with no listeners on its owned ports.

Final local gates, stable-source v5 comparison, brand validation (216 assets/eight semantic AA pairs), and maintained documentation checks pass. Independent exact-source acceptance is recorded for a4; final receipt/head review and the resulting draft PR/exact-head CI are publication gates recorded by GitHub. Earlier real rollup 3/3 and Pursuits 1/1 readiness runs predate the final privacy repair and have only graph-derived source provenance; they are not current-source acceptance. Exact-head CI runs fresh rollup, Pursuits and Phase 2 real fixtures. No schema migration was added. A future code rollback must retain equivalent public change-read privacy or withhold those surfaces; never rewrite private audit history or downgrade schema. No merge, deployment, operational retained-data mutation, source activation, credential change, paid call or outreach occurred.
