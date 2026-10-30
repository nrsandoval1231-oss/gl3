# Equipment-demand candidate validation — October 30, 2026

**PR:** [#153](https://github.com/nrsandoval1231-oss/gl3/pull/153). **Audit base:** `a65b0d1d3196914699e3446447246c4e7b10f598`. **Implementation revision:** `9a6534c7a2276d2cc09f0af354886f7c24420453`; the following receipt/checkpoint edits change documentation only. This is repository validation, not deployment evidence.

## Result and scope

Ordinary ingestion accepts a representative, source-bound O&G electric-compression schedule with distinct applicant/facility and no temporary-power tag or utility-capacity evidence. It persists a versioned demand receipt, reuses it on unchanged ingestion, and exposes verified current output through the existing opportunity intelligence card. A 1,000 hp electric motor with source efficiency 0.90 yields `828.555413333… kW` input per operating unit. Two connected units and one operating unit retain separate connected/coincident quantities. Missing efficiency produces a PARTIAL record with unknown electrical demand. These are synthetic test claims, not live commercial findings.

The [audit and implementation record](../engineering/equipment-demand-slice-20261030.md) identifies reused paths, dispositions, contracts, scope and next work. No dependency, schema migration, provider service or production configuration was added. The dated PR148 production receipt remains separate from this candidate.

## Local verification

Checks used PostgreSQL 18.6 with separate disposable application/test databases, isolated xdist worker databases, blank paid-provider keys, and disabled live scheduling. Commands below run from `backend/` unless prefixed otherwise.

| Check | Observed result |
|---|---|
| `pytest tests/unit/test_equipment_{demand,extraction,card}.py tests/unit/test_regional_power_sources.py tests/integration/test_equipment_{intelligence,ingestion}.py -q` | **91 passed**, 12.68 seconds. Includes real ingestion/replay and API/card assembly, source identity, unknown efficiency, dates, duplicate/conflicting documents, tamper rejection and calculation reproducibility. |
| `pytest tests/integration/test_saved_browse.py -n 4 -q` | **127 passed**, 80.17 seconds, four existing warnings. Includes fixed-clock recovery plus the dedicated boundary/preparation tests. |
| `npm run test:ci --prefix web -- --workers=2` from root | **169 passed**, 2.5 minutes, including real authentication, browsing, contacts, desktop/mobile and evidence. Subsequent display-only precision change additionally passed all **10** canonical-detail/results tests. |
| Two session-cache browser cases, `--repeat-each=3` | **6 passed** after replacing request-count-dependent fixtures with explicit failure phases. |
| Ruff lint and format; `mypy src` | Passed; mypy checked **186 source files**. Existing untyped-function notes remain. |
| `alembic upgrade head`; `alembic check` | Passed from an empty scratch database through `0049_scoped_identity_browse`; no new upgrade operations detected. No migration changes. |
| API/worker startup | API started and returned an unauthenticated session; worker started idle and shut down cleanly with scheduling disabled and no runnable jobs. |
| OpenAPI export and `npm run generate:api`; web typecheck/build | Passed. The equipment record and Calculated field status are additive contracts. |
| Locked backend and brand `pip-audit`; `npm audit --audit-level=high` | Passed, no known vulnerabilities reported. No dependency changes. |
| Brand validator | **216 assets** and eight semantic AA contrast pairs passed. |
| Maintained documentation checker; `git diff --check` | Passed: **90 documents, 345 local targets, three anchors**; no whitespace errors. |

Earlier development full backend runs recorded 3,370 passed/one skipped, then 3,382 passed/one failed/one skipped while review fixes were being integrated. The failure was the existing recovery test expecting `published` during the 15-minute pre-midnight preparation window; three recovery cases now use an ordinary fixed clock while retaining exact assertions. Two overlapping local validation commands also contended on database-wide advisory locks; the isolated 127-test run above replaced that invalid execution arrangement. The existing skip is `test_nc_commerce.py:206`, because its optional local access-probe artifact is absent.

**Full final CI is required.** At receipt creation, the final head's GitHub CI is pending. The PR check suite and PR description record its final observed run and status; these local results alone do not assert that gate passed. CI retains parallel testing, isolated databases, full main-target gates, security checks and browser checks. No CI performance improvement is claimed.

## Independent verification

A Sol architecture audit, five Luna implementation lanes and independent Astra review were actually run. Review found and resolved ambiguous drive parsing, malformed numeric separators, Decimal-context-dependent conflict detection, cross-document temporal selection, silently omitted equipment rows/prose, nonoverlapping operating-window aggregation, conflict classifications and missing planned-capacity presentation. Astra independently passed 71 focused tests during final code review, later rechecked all 20 parser tests, and reported no unresolved blocking findings. The final small presentation-format change is covered by the canonical browser regression.

## Limits and release boundary

- No live engineering-document coverage, production data inspection, paid-provider execution, real buyer verification, deployment or production-readiness claim.
- The parser supports explicit bounded schedules, not general PDF tables or arbitrary engineering prose. Unsupported or conflicting evidence abstains; broader acquisition/extraction requires a real corpus evaluation.
- Company is source-attributed; company identity and buyer remain unknown unless independently established by existing entity/contact machinery.
- Demand scope is equipment capacity, not verified facility peak, rental demand or residual gap. Overlapping documents and incompatible operating windows cannot create an unsupported aggregate.
- Portfolio MW totals and demand-first portfolio ranking are deferred. The primary KPI explicitly displays unavailable; it does not sum a page or mislabel unknown as zero.
- The full six-layer system, autonomous model promotion and Athena integration remain target work. The next commercially useful phases are in the implementation record.

Latest available production evidence remains the **dated October 29** PR148 application `ca12443f5c57f3502584d8a353d83cdf7d5372b1`, schema0049, 74 tables. It is not a fresh observation of production and does not establish deployment of this work.

## Subsequent main integration

The exact PR153 head `d24c70bdade334e24059bcac88d1c45fb56c970c` passed [CI run 41005705346](https://github.com/nrsandoval1231-oss/gl3/actions/runs/41005705346): 3,388 backend tests passed/one existing skip (301.23 seconds), 169 browser tests passed (2.0 minutes), and all five jobs succeeded. A fresh fetch then found PR152 main `d54646c1`; its unverified equipment candidate contracts and tests were integrated without changing their runtime semantics. The sole merge conflict was the current checkpoint. Superseded active merge instructions were archived exactly. A new combined-head CI gate is required; final results are recorded in the PR description/check suite.

Combined local verification: all three PR152 candidate/cohort test modules plus the seven demand/admission/integration modules passed **206 tests in 14.14 seconds**. Ruff lint/format passed (414 files); maintained-document links passed (90 documents, 352 targets before the added cross-link). Sol 6.1/high independently confirmed module coexistence and no separate repository harness launcher; the session uses the native OpenAI collaboration harness with explicitly selected roles.

Independent Astra 6/high integration review found no blockers on `b3e01eefcee0c87d61f1eeb55c7753e4296d5727`: PR152 modules matched main unchanged, no candidate-to-demand runtime promotion existed, and archived checkpoint bytes matched exactly. One nonblocking documentation-index label was corrected in the following documentation-only commit. Full CI for that final head remains required.

## Follow-up review repairs

Review comments received after the prior green head identified three valid edge cases: generic permit/geographic metadata created bogus equipment investigations; historical packages exhausted the current-document bound; and reordered equivalent schedules falsely conflicted. The follow-up parser (`equipment-schedule-lines-v2`) exempts ordinary metadata while retaining incomplete structured equipment/prose and excludes company/facility headers from equipment detection. The Oklahoma admission evaluator includes the parser version so unchanged previously rejected records are reassessed. Regression coverage reproduces the rejection-to-acceptance replay without changing source bytes.

Current binding and supported package-version filters now precede the bounded SQL ranking; immutable stale history no longer consumes the current-document budget. Publication still independently checks eligibility and recomputes the payload. Engineering comparisons canonicalize duplicate IDs, row order and exact Decimal values without relying on ambient rounding. Actual excessive current documents and conflicting engineering claims still abstain.

Independent review caught and prompted repairs for unfamiliar equipment rows hidden by the metadata exception and for admission-cache invalidation. The final follow-up checks and review are recorded on PR153; prior CI evidence is retained above and does not certify later commits. No production operation or new source activation was performed.

Follow-up local focused gate: **107 passed in 15.70 seconds** across parser, engineering, card, regional admission and equipment persistence/ingestion modules. A new replay test caught the first expanded evaluator identifier exceeding the existing varchar(40); a compact deterministic version fingerprint repairs it without a schema change. Ruff lint/format and maintained-document links passed. Astra reviewed metadata, bounded current-receipt selection, engineering comparison and replay invalidation with no remaining blocker at freeze; final commit CI remains required.
