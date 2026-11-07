# Evidence-led opportunity shortlist — candidate and validation

Owner request: November 6, 2026. Branch `codex/evidence-led-shortlist`, based on `fc59eab64306b7bcd0d047a0f5b7b3eb9381b6aa`. This is a PR candidate, not a production release. No merge, deployment, production write or paid-provider execution is part of this task.

## Implemented behavior

Opportunities opens a source-led shortlist. All Projects retains the complete discoverable cohort, including unresolved Signals. Existing brand assets, header, colors and four primary destinations remain. Research is available as **Research progress** in the account menu.

A separate view policy assesses exact current retained Evidence versions before grouping, counts and pagination. It does not change qualification, delete observations, or publish model prose as evidence. Source dates—not ingestion timestamps—govern a 365-day freshness window. Explicitly labeled future planned milestones can be retained as estimates with past publication support. Undated, stale and explicitly closed/cancelled source records remain available in All Projects.

Eligible source clauses cover specific temporary/construction electrical service, emergency restoration, generator/transfer work, named data-center construction/commissioning, material commercial or industrial electrical buildout, electrically driven equipment, and explicit energization constraints. Generic permit labels, W-1 permission alone, minor civil work, classifications and model labels are insufficient. Neither known MW, buyer identity nor utility shortage is required. Scope and amount uncertainty remain explicit.

Only validated physical well identity, exact native paired-permit scopes, and identical headline-plus-abstract news developments are grouped. Pecos Buildings A/B/C stay distinct. These 41 conservative source/project groups are not an exhaustive deduplication of physical sites; possible same-site work packages and phase ambiguity remain in both views. Full-generation identity mapping keeps grouped siblings accessible through search and selected-project details. Assessments pass through the existing suppression/history privacy projection and contact-token redaction; verified contact routes remain separately projected.

Cards show What, Why now, Power need and one next step, with Add to Pursuit and project detail access. Internal scores, qualification labels and repeated unknowns are removed. Facility scale, activity demand and residual gap remain distinct. Sources, missing research and sibling source records are in project detail.

Research planning prioritizes identity, temporary-power scope, phase, timing and buyer work. The protected Jev route selects only configured unresolved grounded questions; follow-on Sol dossiers retain existing source, privacy, approval, model, pricing, budget and dispatch checks. Supported recommendation inputs require source provenance. Existing query/source fingerprints, freshness checks and changed-input fences prevent unchanged repeat work. No new live provider completion or model accuracy is claimed.

## Baseline and comparison

Before changing filtering, a read-only repeatable-read production export froze generation `d77dc446-f1a9-42c1-ab2b-ec169115de97`: 2,258 needs/projects (2,133 Oil & Gas, 18 Data Centers, 107 other) and their 2,258 referenced immutable Evidence versions. Original ranking and projection inputs are retained privately under ignored `.artifacts/evidence-shortlist/`; raw contacts are not committed.

| Measure | Before | Candidate |
|---|---:|---:|
| Default project records/groups | 2,258 | 41 |
| Source-eligible records before duplicate grouping | — | 48 |
| Duplicate records grouped | — | 7 |
| All Projects records retained | 2,258 | 2,258 |
| Cards with source references / why / next action | — | 41 / 41 / 41 |
| Established activity MW values | 0 | 0; unknown is not zero |

A separate critic selected and source-checked a [32-case calibration sample](../validation/evidence-shortlist-20261106/sample.json): all 20 worthwhile source records remain represented, all 7 definite low-value records are excluded from the default, and 5 uncertain records remain in All Projects. The policy was repaired using this sample, so these are calibration results, not held-out precision/recall.

A different final critic then inspected all 81 initially excluded non-W1 records and identified four electrical-buildout misses (hospital expansion, industrial warehouse services, and two industrial facility scopes). A general source rule repaired all four without project-ID exceptions. That later audit is kept separate in the [machine comparison](../validation/evidence-shortlist-20261106/comparison.json); no population-wide accuracy percentage is claimed. All 41 retained cards and seven duplicate clusters were inspected against retained source excerpts.

An isolated PostgreSQL replay of copied source/generation inputs exercised the actual project-results SQL: 41 grouped results, all 2,258 All Projects records preserved, empty-sector/search handling, global pagination and stable duplicate-member detail/search identity. This is a disposable domain replay, not a full production contact/suppression database clone or a deployed API result. The exact receipts distinguish these boundaries.

## Research findings and limits

- All activity-MW fields in the frozen cohort are unknown. Campus/facility values (including the reported Edged scale) do not become temporary load or portfolio demand.
- A TDLR estimated schedule, registration date, permit issue, control-house permit and achieved construction milestone retain their different meanings. Recent retrieval does not establish current construction.
- Source-listed methods do not establish purchasing authority. Next steps request the missing commercial confirmation rather than inventing a buyer or shortage.
- Evidence coverage measures source links, not completeness: retained adapter snapshots and short RSS excerpts were audited; original full pages/PDFs were not refreshed. Broader source coverage, undated/stale active projects, unresolved duplicates and current buyer/timing confirmation remain limitations.
- New live Jev/Sol research was not run. Routing/provenance/cache behavior is tested locally; provider efficacy and new research completion remain unverified for this candidate.

## Before and after

These are local browser replays of the frozen production project inputs, not screenshots of a deployed candidate. See the [capture provenance and fixture boundaries](../validation/evidence-shortlist-20261106/ui-replay-captures.md).

| Viewport | Before | After |
|---|---|---|
| 1648 × 928 | [Before](../validation/evidence-shortlist-20261106/ui-before-1648x928.png) | [After](../validation/evidence-shortlist-20261106/ui-after-1648x928.png) |
| 1440 × 900 | [Before](../validation/evidence-shortlist-20261106/ui-before-1440x900.png) | [After](../validation/evidence-shortlist-20261106/ui-after-1440x900.png) |
| 1280 × 800 | [Before](../validation/evidence-shortlist-20261106/ui-before-1280x800.png) | [After](../validation/evidence-shortlist-20261106/ui-after-1280x800.png) |
| 768 × 1024 | [Before](../validation/evidence-shortlist-20261106/ui-before-768x1024.png) | [After](../validation/evidence-shortlist-20261106/ui-after-768x1024.png) |
| 390 × 844 | [Before](../validation/evidence-shortlist-20261106/ui-before-390x844.png) | [After](../validation/evidence-shortlist-20261106/ui-after-390x844.png) |

## Verification status

Local environment: Python3.11.16, PostgreSQL18.6, Node24.21.0, uv0.13.4. GitHub CI supplies its pinned Node22 environment. Disposable test databases are isolated on loopback58627; retained/production storage was never a test target.

Three Luna builders implemented separate API, UI and research scopes. Astra handled the source-policy escalation; a different Astra performs final integrated review. Earlier predicate, formatting/type-check, privacy and layout failures are preserved privately and are not passing receipts. The unrelated preexisting `.agent/WORK_GRAPH.md` edit is preserved and excluded from this PR.

The full local `pwsh -NoProfile -File scripts/check.ps1` on commit `8ef2d616` passed: 4,957 backend tests passed, three skipped, seven subtests passed (11 warnings); all 290 browser regressions passed. The same gate passed pip-audit, ruff, formatting, mypy, Alembic upgrade/check, npm ci/audit (zero vulnerabilities), typecheck, build and Chromium installation. All five GitHub CI jobs also passed on that commit, including Node22 browser tests and three real-backend customer-rollup journeys. Tests used four pytest workers and owned disposable databases with provider keys empty. Local brand validation passed 216 assets and eight semantic AA pairs; documentation links passed 109 documents / 513 local targets / 18 anchors. See the [hashed check and screenshot receipt](../validation/evidence-shortlist-20261106/checks.json).

Subsequent PR review reproduced two source-policy edge cases: a prose colon could hide news scope, and a negated electrical-drive phrase could falsely qualify equipment. The bounded repair distinguishes recognized source fields from prose and rejects negated drive claims while retaining affirmative sibling clauses. All 114 policy/API integration tests passed after repair; the frozen pure-policy and actual SQL replays still return 48 eligible records, 41 groups and 2,258 All Projects records. The unchanged replay leaves the screenshots and calibration totals applicable. Independent re-review and exact-head CI status are recorded in the PR, separately from the preceding full local gate.

The separate push-triggered CI run on `8ef2d616` failed the existing publication-diagnostic test `test_refresh_outcome_survives_savepoint_and_excludes_private_error[True]` with a missing `worker_browse_outcome` key, while its PR-triggered CI run passed. Both results are retained; the passing PR run is not represented as proof that every run passed. Final-head CI is reported separately in the PR.

Review additionally reproduced disconnected electrical wording (a utility name, trade or electrical-service scope) incorrectly establishing electric equipment drive. The repair requires an explicit equipment modifier or drive/motor relationship and preserves direct, passive and mixed-replacement positives. The preceding `f833a4c8` PR CI passed 4,989 backend tests (one skipped), 290 browser regressions and three real-backend rollup journeys; its separate push run failed the existing WS6 inline/job document-count parity test. That distinct failure also remains unexplained; no unrelated test was weakened or changed. The [check receipt](../validation/evidence-shortlist-20261106/checks.json) links both outcomes; final-head results are maintained in the PR.

The earlier failed full run is retained privately. Research fixtures now supply actual source-backed identity/contact facts rather than assuming those gaps were already resolved; phase-transition tests exercise the real worker and bounded timing follow-up. The privacy worker fixture commits and verifies an explicitly due job before exercising the unchanged no-provider/no-ledger/source-immutability assertions. Its original isolated timing cause was not reproduced and is not asserted as proven. Independent final review is recorded in the pull request; it is separate from local tests and does not authorize merge or deployment.

## November 7 owner-requested completion

The follow-on implementation simplifies each card to project/company/location, a source-backed reason, a supported activity/facility power statement or explicit unknown, and one next step with Add to Pursuit. Scores, classifications, redundant detail actions and unavailable secondary KPI tiles are removed from the default scan. The primary equipment-demand summary and its coverage disclosure remain. Internal API/type/CSS names remain compatible, while visible Intelligence labels become Details, Project details, Research history or Research progress. The raster header tagline is hidden through a bounded CSS crop; its approved mark/wordmark asset bytes are unchanged.

Live-QA repairs align Companies project totals with the same Signals-inclusive discovery scope as its rows, remove the false Company unknown label from Research when identity is merely absent from the list projection, display selected source-backed company context, and humanize stage/type labels and single-project counts.

Shortlist assessment now consumes exact-version, current-policy, pinned-model demand-v1 Jev decisions. HOLD vetoes only its own source; another independently sufficient source can still support the project. SHOW breaks ties between equal source-rule priorities; REVIEW and missing, stale, unpinned or incompatible judgments abstain. Jev cannot invent scope, quantities or sources, and a SHOW alone cannot satisfy source eligibility. The effective evidence-to-decision map is read once and hashed into pagination identity, so changed decisions require a restart rather than silently altering later pages. Explicitly negated development is excluded without discarding a separate affirmative equipment clause. Existing bounded Jev-to-Sol question routing, grounded extraction, privacy, retry/freshness fences and cost controls remain the research path; no new framework or paid dispatch was introduced.

Fresh production validation used a single read-only repeatable-read export at 2026-11-07 18:31:27 UTC: generation 1df3db08-a4d3-4ab1-a23a-52c7975a9bd8, 2,304 browse records and their 2,304 immutable evidence versions. An additional read-only decision export at 18:37:46 UTC retained source/hash/model/policy bindings. The isolated actual-SQL replay imported 2,440 decision versions that bind to the copied cohort. Latest qualifying Jev coverage is 109 REVIEW and four SHOW; none covers the shortlist's 48 cited versions. Thus this validates model-decision handling and retained source selection, not new model efficacy or newly completed Sol research.

The replay produces 41 shortlisted groups from 48 source-eligible records, while All Projects retains all 2,304 records. Independent inspection checked all 41 retained projects, six pagination pages and 14 duplicate-detail probes. It is a source-calibrated discovery shortlist, not a measured precision/recall guarantee, full production database clone, live candidate deployment, or assertion that the projects have a confirmed rental demand/buyer. All activity MW remains unknown in this observed cohort. Raw source exports and contacts stay in ignored private artifacts.

Final check results and candidate hash are recorded after the integrated gates; earlier November 6 receipts remain dated evidence for their own code. Production/provider settings are unchanged by this implementation.

Final November 7 validation completed in sections: `pwsh -NoProfile -File scripts/check.ps1` passed dependency audit, Ruff/format, mypy, migration upgrade/drift, and 5,011 backend tests (three skipped; seven subtests passed), then stopped at Windows EPERM while npm tried to replace a preview-held esbuild executable. After stopping the task-owned preview, the remaining npm install/audit/typecheck/build/Chromium steps passed. The first full browser run exposed ten stale approved-label/KPI assertions; only selectors and the intentional three-to-one KPI expectation were updated, preserving behavior, privacy, retry, idempotency and geometry checks. The final complete browser rerun passed all 291 tests. The separate real-backend rollup lane passed all three journeys against dedicated disposable 2,098-row fixtures. Brand validation passed 216 assets/eight semantic AA pairs; maintained links passed 109 documents/513 targets/18 anchors. The initial formatting failure, superseded partial run, Windows lock and stale-selector logs remain private and are not passing receipts.

Independent Astra review verified the final application sources, five negation/affirmative-work probes, the complete copied-source SQL cohort and paging, the effective-Jev-decision token change, responsive screenshots, and unchanged behavioral coverage in the selector repairs. These are repository/local replay results; this candidate is not merged or deployed and does not claim new paid-provider completion. Existing production configuration remains untouched.
