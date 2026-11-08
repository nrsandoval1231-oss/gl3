# Phase 2 validation — November 8, 2026

This record separates implemented source, deterministic fixtures, independent review and final acceptance. **Final acceptance is pending.** No merge, deployment, operational retained-data mutation, credential change, source activation, paid-provider request or outreach is authorized by this task.

## Same-fixture reference

[Sanitized comparison](matched-fixture-summary-e5983baa.json) records an independently executed pair at baseline `bc433650ce4706dddfb5b30d78a502e3b528f54e` and candidate `e5983baa22e2a8841fafd6173b8c613288770ae2`. It is a reference for that source revision, not acceptance of subsequent preservation repairs. Raw captures/logs remain ignored under `.artifacts/phase2/`.

- Fixture SHA256: `15e29ff076b6f1c02a3cd11ac18c76a86e716f34d3daa660b23ae93da3531111`.
- Evaluator SHA256: `fde98d53cde8a7b16d24e4518c9f7e11ca35664576bcda025e503651a8abdcd2`.
- Before/after aggregate of 416 production/harness files: `c240b8ba4b51060011eef062fc989cdd0c0516f27d129c45da4ef28d1478d956`, unchanged during the 47.91-second quiet window. Both capture tests passed; comparison exited zero.

| Synthetic fixture metric | Baseline | Candidate e598 |
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
| In-process account-project read p50 / p95, milliseconds | 7.35 / 18.04 | 21.53 / 39.08 |
| Fixture workflow elapsed, milliseconds | 8,980.97 | 17,383.24 |

The candidate removed an unverified `acme.test` method while retaining the RRC method; this is a quality filter, not increased contact coverage. Structured-field presence is separate from the unchanged common usefulness measure. All four power amounts remain unknown: candidate scopes are two construction-temporary, one commissioning and one campus-capacity. No campus, IT or nameplate MW is added to rental demand. Zero fixture conflicts does not establish conflict-free production data.

Ten initial jobs were scheduled; the later bounded retry makes eleven recorded outcomes (three successful jobs and eight failed/blocked research outcomes). Those eight are not accepted findings or completed commercial research. The fixture checks replay/entity/spend deduplication and outage recovery; the candidate reaches retained/native route checks and reports disabled discovery honestly.

There was one matched capture per source. Read latency uses five repeated **direct in-process `account_projects` database reads**, not HTTP. Cold-cache state was not controlled. Candidate reads and workflow were slower. Pytest wall times were 15.94 and 22.13 seconds. Hardware: Intel Core Ultra 5 225F, 10 cores, 31.5 GiB RAM, local Windows; Python 3.11.16, PostgreSQL 18.6, uv 0.13.4. This small synthetic fixture is not production coverage, production lead quality, a billing receipt or a scale benchmark. Final browser HTTP measurements are separate and pending.

## Reproduction boundary

Run from the repository root with the existing locked backend environment, newly created reserved loopback-only databases, privately generated process-local test authentication, disabled providers and blank provider keys. Set `DATABASE_URL` to the separate `gl3_phase2_acceptance_app` database; set `TEST_DATABASE_URL` to the exact selected fixture database for each capture. The runner rejects routing overrides, unknown database names, dirty tracked/untracked Python source, receipt overwrite and mismatched fixture/evaluator hashes. Do not point these commands at retained or production data.

```powershell
uv run --project backend python scripts/phase2_metrics.py capture --mode baseline --database gl3_phase2_baseline_fixture_test --source-root <managed-base-checkout>/backend/src --output <new-baseline-receipt.json>
uv run --project backend python scripts/phase2_metrics.py capture --mode candidate --database gl3_phase2_candidate_fixture_test --source-root <candidate-checkout>/backend/src --output <new-candidate-receipt.json>
uv run --project backend python scripts/phase2_metrics.py compare --baseline <new-baseline-receipt.json> --candidate <new-candidate-receipt.json> --output <new-comparison.json>
```

Use verified source roots; changing `PYTHONPATH` alone is insufficient because pytest config sets its own source path. The runner verifies imported source paths, hashes and checkout revision. A source/evaluator change requires a new pair. Do not compare this fixture with the historical November 7 population or purposive sample.

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
| Retained rows, private lifecycle/identity evidence and public abstention | Full claim/evidence snapshots and LEI/EIN conflict/current-version/person-isolation assertions in `test_buying_chain.py`; final full-module run pending |
| Session/navigation, no browser provider/outreach actions, responsive four-tab UX | Generic browser suite observed 324 passes; final real Phase 2 browser run and five card/two detail captures pending |

Earlier failed comparisons, fixture runs and source findings remain failures in their diagnostic logs. The first pair comparison failed due to nested receipt-hash handling; the repaired CLI has round-trip, mismatch and overwrite checks. Original UUID failures were independently reproduced with controlled legitimate UUID allocations; the repair preserves valid pointers while redacting phone/email controls.

## Capability and final gate limits

The public native directory path is fixture-tested. Existing producers do not supply an authoritative canonical-ID-to-company-domain binding, so an imported domain, footer identifier or email domain cannot establish employer identity. Unverified website contact publication remains blocked; this is not broad official-website coverage. Presence of a business method does not prove deliverability or purchasing authority.

Firecrawl metadata-only search has deterministic contract/recovery tests; remote HTML extraction remains capability-blocked where preventive target redirect/private-network control is unverified. Apollo is an always-blocked no-network interface, not an operational licensed connector. No live/paid smoke was run; actual access, credits, prices and rights remain unverified. See [contact evidence and official documentation](contacts.md).

Final full backend/frontend/dependency/migration/brand checks, real browser receipts, latest-source matched comparison, final integrated Astra head attestation, draft PR and exact-head CI are still required. No schema migration has been added; migration/drift verification and rollback notes must be recorded at final handoff.
