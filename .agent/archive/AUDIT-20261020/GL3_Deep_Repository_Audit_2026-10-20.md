# GL3 — Deep Repository Audit

**Date:** October 20, 2026  
**Repository:** `nrsandoval1231-oss/gl3`  
**Pinned main:** `9e9e188bdf2825a8305a0e9eac0b23f0af1df47e`  
**Review type:** Broad source, architecture, security, commercial correctness, ingestion, persistence, frontend, delivery and validation audit. Read-only with isolated diagnostics; no application changes or deployment.

## Decision

**Keep the architecture and repair the commercial path. GL3 has meaningful engineering safeguards, but its default experience still has defects that can hide useful opportunities, misorder the pursuit queue, and display misleading results after errors.** Passing tests and healthy collection alone do not establish that it reliably produces useful pursuits.

The most valuable next work is: correct workspace ranking, finish and validate news admission, automatically extract supported buying roles from retained permit data, then prove the complete discovery-to-call workflow on actual projects. Preserve the evidence gates and accounting safeguards. Another redesign or a replacement qualification engine would delay the outcome.

No critical authentication bypass, remote-code-execution path, or exposed live credential was confirmed in the inspected snapshot. That is a review result, not a security certification.

## 1. Scope and evidence quality

The repository tree was inventoried at the pinned commit. **483 application, configuration, migration, test, script and selected instruction files were materialized and individually verified against their Git blob SHA.** This includes all backend source, backend tests, frontend source/tests, deployment files, source configuration, scripts and lockfiles selected by the audit manifest. Binary design assets and most historical narrative documents were outside the code snapshot.

Inventory includes 139 backend source files (57,048 lines including package READMEs), 158 backend test/fixture files (60,102 lines), 35 migration files/templates (32 versioned migrations), and 45 frontend source files (21,630 lines including generated API contracts). These are inventory counts, not a claim that every line received equal manual review.

Deep tracing focused on:

- Registry → collection → retained observations → interpretation → project/power-need creation.
- News admission, project identity, qualification, operator facts, buying-chain extraction and ranking.
- Durable job leasing/fencing, provider deadlines, logical-call identity and unknown-outcome accounting.
- Saved browse publication, revision/clock fences and workspace query behavior.
- Session authentication, login limiting, origin checks, public URL validation and protected mutations.
- Frontend loading/error/readback behavior, type contracts, build and dependencies.
- Deployment manifests, backup commands, CI configuration and GitHub branch controls.

An independent reviewer checked security, API and fact-history behavior as required by repository agent instructions. Findings were cross-checked before inclusion. A suspected duplicate-paid-call issue was rejected after tracing the logical-call deduplication protection.

**Evidence labels:** “Reproduced” means an isolated local execution; “static” means a directly inspected code path; “reported production” means a dated handoff, not a fresh server observation in this audit. No live database, authenticated production UI, current deployment digest, source freshness or latency was independently measured here.

## 2. Findings at a glance

P1 = directly undermines the primary commercial workflow; P2 = important correctness, reliability, security or delivery issue. Priority is remediation order, not a CVSS score.

| ID | Priority | Finding | Evidence |
|---|---|---|---|
| F01 | P1 | Default workspace priority ignores the implemented weighted ranking | Reproduced ranking inversion + static SQL |
| F02 | P1 | News admission misses early-stage events and ordinary city/state locations | Reproduced on pinned main |
| F03 | P1 | Retained buying-chain extraction requires manual enrichment | Static call graph; production impact separately reported |
| F04 | P2 | Fact corrections can supersede an inappropriate predecessor | Static API + reproduced domain consequence |
| F05 | P2 | Failed workspace refresh redisplays old rows beneath new filters | Static frontend state/render trace |
| F06 | P2 | One throttled client can consume the global login allowance | Actual limiter reproduced with fake persistence |
| F07 | P2 | Signal decision counts stop at the first 50 records | Actual endpoint function with page-boundary stub |
| F08 | P2 | Default workspace does not deliver the required morning-change briefing | Static frontend/API contract |
| F09 | P2 | Main has no enforced branch protection or repository ruleset | GitHub configuration read |

### F01 — Default priority bypasses the weighted score

**Location:** [pursuit_workspace.py:77–87](https://github.com/nrsandoval1231-oss/gl3/blob/9e9e188bdf2825a8305a0e9eac0b23f0af1df47e/backend/src/gridlens/intelligence/pursuit_workspace.py#L77-L87), [ranking.py](https://github.com/nrsandoval1231-oss/gl3/blob/9e9e188bdf2825a8305a0e9eac0b23f0af1df47e/backend/src/gridlens/domain/ranking.py), [saved_browse.py:240–280](https://github.com/nrsandoval1231-oss/gl3/blob/9e9e188bdf2825a8305a0e9eac0b23f0af1df47e/backend/src/gridlens/intelligence/saved_browse.py#L240-L280).

`rank_opportunity()` implements the published 100-point policy and saved browse stores `rank_score`. The default workspace instead orders by `commercial_segment, commercial_geography, commercial_date, project_id, need_id`. Neither evidence strength, buyer accessibility nor the weighted score can overcome the segment ordering.

**Reproduction:** A synthetic distant data-center Signal with unknown timing scores **25**, segment **6**. A synthetic Houston industrial Lead with supported start timing, recent evidence and a known company scores **78**, segment **8**. The default SQL ordering puts segment 6 first. This contradicts PRD requirement 27 and its explicit strong-non-data-center acceptance scenario. These are controlled fixture inputs, not invented real leads.

**Repair:** Use the canonical persisted ranking score for default priority, with stable tie-breakers, or explicitly approve and publish a replacement policy. Keep one ranking policy across queue, detail reasons and exports. Do not merely change the label.

**Acceptance:** An API-level workspace test must put the 78-point need before the 25-point need; verify pagination stability and matching displayed explanations. Existing domain ranking tests alone cannot catch this integration failure.

### F02 — News discovery is too restrictive for the target opportunities

**Location:** [news_interpretation.py:65–74](https://github.com/nrsandoval1231-oss/gl3/blob/9e9e188bdf2825a8305a0e9eac0b23f0af1df47e/backend/src/gridlens/domain/news_interpretation.py#L65-L74), [155–182](https://github.com/nrsandoval1231-oss/gl3/blob/9e9e188bdf2825a8305a0e9eac0b23f0af1df47e/backend/src/gridlens/domain/news_interpretation.py#L155-L182), [492–540](https://github.com/nrsandoval1231-oss/gl3/blob/9e9e188bdf2825a8305a0e9eac0b23f0af1df47e/backend/src/gridlens/domain/news_interpretation.py#L492-L540).

The concrete-action grammar omits land acquisition and site-specific financing. Location parsing accepts a small city dictionary or a state directly following “in/at/near”; an ordinary “in City, State” expression outside that dictionary fails.

| Input to actual `assess_news()` on main | Result |
|---|---|
| Microsoft acquires 600 acres for data center in Woodward, Iowa | Rejected: no concrete project action |
| Digi Power X secures $200m financing for 40MW Alabama data center | Rejected: no concrete project action |
| Acme will build a data center in Fort Worth, Texas | Rejected: US project location not stated |
| Acme will build a data center in Dallas, Texas | Accepted Signal |

The first two strings are examples retained in PR #96’s analysis; their underlying project claims were not independently researched here. The Acme pair is synthetic and isolates a location-parser defect in a priority market.

**Existing work:** [PR #96](https://github.com/nrsandoval1231-oss/gl3/pull/96), head `290c6af2b36f11d59f1166c3d3dfd653797c7198`, is open and describes fixes for these categories. It is outside the main snapshot; this audit does not certify that branch. Reuse and independently validate that work rather than create a competing rewrite.

**Repair:** Broaden supported event and geographic structures without equating financing, campus MW or a power deal with temporary rental demand. Use a held-out retained corpus, including non-US, speculative, company-level and already-served negatives. Reprocess retained rejected items under a versioned interpretation policy after validation; future-only collection will not repair existing misses.

**Acceptance:** Positive admission for clearly scoped Fort Worth and early-stage site events; no unsupported MW/tier promotion; measured recall and false-positive rates on a frozen held-out sample. Preserve rejected observations for review.

### F03 — Known permit organizations are not automatically converted into a buying chain

**Location:** [app.py:4146–4164](https://github.com/nrsandoval1231-oss/gl3/blob/9e9e188bdf2825a8305a0e9eac0b23f0af1df47e/backend/src/gridlens/api/app.py#L4146-L4164), [buying_chain.py:187–267](https://github.com/nrsandoval1231-oss/gl3/blob/9e9e188bdf2825a8305a0e9eac0b23f0af1df47e/backend/src/gridlens/intelligence/buying_chain.py#L187-L267), [buying_chain_extraction.py](https://github.com/nrsandoval1231-oss/gl3/blob/9e9e188bdf2825a8305a0e9eac0b23f0af1df47e/backend/src/gridlens/intelligence/buying_chain_extraction.py).

The extraction capability exists, including retained permit fields. The application call graph queues `enqueue_buying_chain_research()` from the explicit project enrichment API, not normal ingestion. The worker executes that job after it is requested. Existing general pursuit research is not equivalent to automatically populating these BuyingChainClaim records.

**Impact:** A collected permit can already contain an operator or contractor while its structured buying chain remains empty until a user requests enrichment. This creates manual work at precisely the point where GL3 should make a Signal callable. It is a delivery gap against requirements 15 and 28, not a missing parser from scratch.

**Repair:** Enqueue bounded, retained-data-only extraction after relevant accepted evidence changes. Reuse the existing extractor and provenance checks; use project/evidence/policy identity for idempotency. Backfill in small batches. Keep new external research and paid calls governed by their existing settings. Do not treat a permit applicant or corporate employee as a proven buyer.

**Acceptance:** On a real permit with an explicit supported organization role, ingestion produces an inspectable role without a manual click; a repeated unchanged ingestion produces no duplicate claim; a source correction updates the current view while preserving history.

### F04 — Correction predecessor validation is insufficient

**Location:** [app.py:4488–4491](https://github.com/nrsandoval1231-oss/gl3/blob/9e9e188bdf2825a8305a0e9eac0b23f0af1df47e/backend/src/gridlens/api/app.py#L4488-L4491), [4587–4619](https://github.com/nrsandoval1231-oss/gl3/blob/9e9e188bdf2825a8305a0e9eac0b23f0af1df47e/backend/src/gridlens/api/app.py#L4587-L4619), [call_facts.py](https://github.com/nrsandoval1231-oss/gl3/blob/9e9e188bdf2825a8305a0e9eac0b23f0af1df47e/backend/src/gridlens/domain/call_facts.py).

The API verifies that a correction predecessor belongs to the same need, but not that it is the current accepted fact of the same type. It appends a superseded decision to that predecessor and accepts the successor. An unrelated fact type can be superseded, or the intended older accepted fact can remain active.

**Independent reproduction:** Begin with accepted demand 20 MW. Create a 21 MW corrected successor pointing to an unrelated draft 19 MW version. The decision branch permits that relationship; current-fact reduction retains both 20 and 21 MW. Actual `qualification_from_facts()` returns Signal with `qualification_conflict=true` and “Accepted demand facts conflict for this need.” This was a pure-domain reproduction plus API inspection, not an end-to-end database transaction.

**Repair:** Under the existing need lock, require an eligible predecessor with matching fact type/activity/facility and a valid current history state. Reject an obsolete or already superseded correction target. If correcting drafts is intentionally supported, define that separately rather than treating it as replacement of an accepted fact.

**Acceptance:** Wrong-type, draft-target and stale-predecessor corrections return a clear conflict/validation response; a valid correction leaves only its intended successor current. Preserve legitimate independent conflicting reports as conflicts.

### F05 — A failed refresh exposes old rows under new filters

**Location:** [Workspace.tsx:47–61](https://github.com/nrsandoval1231-oss/gl3/blob/9e9e188bdf2825a8305a0e9eac0b23f0af1df47e/web/src/features/workspace/Workspace.tsx#L47-L61), [91–115](https://github.com/nrsandoval1231-oss/gl3/blob/9e9e188bdf2825a8305a0e9eac0b23f0af1df47e/web/src/features/workspace/Workspace.tsx#L91-L115).

On request failure, the component clears `loading` and sets `error`, but retains `page`. The table renders `(loading ? [] : items)` without excluding the error state; briefing totals also come from the retained page. After changing geography, tier or MW and receiving a 500/network error/first-page 503, the old results return beneath the new filter controls. An error banner exists, but the table is not explicitly marked as the previous result set.

**Repair:** Bind visible page data to the successful request/filter identity. Hide mismatched rows and counts on failure, or show them explicitly as the previous result set with its original filters and disabled current-cohort actions. Do not erase source data.

**Acceptance:** Browser test: successfully load Austin, switch to Houston, fail the second request; Austin rows must not appear as Houston results. Also test a previously loaded Lead that becomes pending after an accepted fact change. Existing initial-load-error and late-response tests do not exercise this transition. Local browser execution was blocked by browser download failure, so this finding is static rather than browser-reproduced.

### F06 — Per-client rejection still consumes the shared login budget

**Location:** [security.py:47–97](https://github.com/nrsandoval1231-oss/gl3/blob/9e9e188bdf2825a8305a0e9eac0b23f0af1df47e/backend/src/gridlens/security.py#L47-L97).

`consume_login_attempt()` increments the global bucket before applying the already-exhausted client limit. With defaults, one client can submit 500 requests within a 60-second window and deny new login attempts from other clients, even though only its first five attempts passed the per-client gate. Existing signed-in sessions are not revoked by this mechanism. An upstream rate limiter could reduce exposure; current edge configuration was not verified.

**Independent reproduction:** Actual function with in-memory fake session, client/global limits 2/5: same-client results `true, true, false, false, false`, global usage reaches 5, first attempt from another client is denied. The test isolates admission logic and does not prove database concurrency behavior.

**Repair:** Check exhausted client capacity before consuming global admission capacity, within the same atomic transaction. Keep a separate bounded abuse counter if needed. Preserve the global allowance against distributed password guessing.

**Acceptance:** Throttled requests from one client do not consume remaining admission slots for another client; concurrent callers still cannot exceed the intended global budget.

### F07 — Signal decision summary silently truncates at 50

**Location:** [app.py:1644–1652](https://github.com/nrsandoval1231-oss/gl3/blob/9e9e188bdf2825a8305a0e9eac0b23f0af1df47e/backend/src/gridlens/api/app.py#L1644-L1652), [3882–3895](https://github.com/nrsandoval1231-oss/gl3/blob/9e9e188bdf2825a8305a0e9eac0b23f0af1df47e/backend/src/gridlens/api/app.py#L3882-L3895).

`/api/signals/decisions` loops over `opportunities(tier="Signal")`, whose default page limit is 50. The response claims counts of active Signal records and exposes no truncation marker.

**Reproduction:** Invoke the actual summary function with a pagination stub using the real function's default limit. Seventy-five SHOW records produce `show=50`. The current workspace’s separate disposition counts use SQL aggregation; do not confuse them with this broken endpoint.

**Repair:** Aggregate the entire eligible Signal cohort under the same evaluation/snapshot rules; reuse the existing whole-cohort count path where appropriate. Do not raise the page limit as a workaround.

**Acceptance:** Test more than 50 mixed SHOW/REVIEW/HOLD/unadjudicated records, including ineligible or inactive records, and compare totals with the complete filtered cohort.

### F08 — The default briefing cannot tell Nick what changed

**Location:** [Workspace.tsx:105](https://github.com/nrsandoval1231-oss/gl3/blob/9e9e188bdf2825a8305a0e9eac0b23f0af1df47e/web/src/features/workspace/Workspace.tsx#L105), [pursuit_workspace.py:142–151](https://github.com/nrsandoval1231-oss/gl3/blob/9e9e188bdf2825a8305a0e9eac0b23f0af1df47e/backend/src/gridlens/intelligence/pursuit_workspace.py#L142-L151).

The default view explicitly displays “Changes since previous review: Unavailable”; its API hardcodes `changes_available=false`. This is honest presentation, but requirement 32 and the daily journey remain incomplete in the primary workspace. Change-detection and historical evidence code elsewhere do not complete this user-facing path.

**Repair:** Connect retained material changes to a compact, bounded briefing with a persisted review baseline. Distinguish a source being rechecked from a meaningful project change. Include newly discovered, promoted, changed and closed needs, and relevant collection-health exceptions.

**Acceptance:** An unchanged refresh adds no briefing event; a supported demand/date/supply change does; its link opens the correct need and preserved before/after evidence. No decorative chart is required.

### F09 — Main is not protected by an enforced merge gate

GitHub branch metadata returned `protected=false`, with required status checks disabled. The repository rulesets endpoint returned an empty list. Thus the green CI workflow exists, but this configuration does not enforce it before changes reach main. This is a repository-control finding, not evidence that an unsafe merge actually occurred.

**Repair:** Configure a minimal main-branch rule requiring the relevant backend/web checks and blocking force pushes/deletion, with the owner’s chosen emergency override. Keep the process simple. If human review is required, encode it rather than relying solely on instructions in Markdown.

**Acceptance:** An ordinary failing or unchecked PR cannot merge to main; the documented override remains auditable. No settings were changed by this audit.

## 3. Architectural and operational risks

### R01 — Scoped browse refresh still copies the corpus

[saved_browse.py:288–419](https://github.com/nrsandoval1231-oss/gl3/blob/9e9e188bdf2825a8305a0e9eac0b23f0af1df47e/backend/src/gridlens/intelligence/saved_browse.py#L288-L419) limits canonical reevaluation to changed projects, but creates a new generation by copying all unchanged browse rows, then runs `ANALYZE`, global group metadata and generation pruning. This occurs under the singleton publication lock. Worker publication may spend up to its configured 60-second cooperative budget; interactive refresh lacks that same explicit execution-deadline argument.

**Confirmed property:** Write work grows with corpus size even for a small canonical change. **Not established:** that this is causing today’s production latency or any specific seconds-long delay.

Before adding more sources, benchmark single-fact saves, batch ingestion and clock rollover at current size and larger retained/fixture sizes. Measure lock wait, copied rows, WAL, p95/p99 write/read latency and pending-generation intervals. Reduce repeated per-record publication or introduce bounded shared immutable rows only if measurements justify it; preserve transactional freshness and coherent pagination.

### R02 — Current code and reported deployment are different

The [October 20 recovery handoff in PR #98](https://github.com/nrsandoval1231-oss/gl3/blob/f944be98f980c17558b6a7828a3947257ec4f23a/docs/operations/2026-10-20-recovery-handoff.md) reports observations around 14:00–17:00 UTC:

| Reported state | Audit interpretation |
|---|---|
| Production build `802cbb4`; merged #94/#95 held from deployment | Main-source fixes cannot be claimed live |
| 19 sources fresh; Boston/Chicago/Georgia stale; CEQAnet/TCEQ/Houston never successful; TDLR disabled | Dated handoff only; rerun current health checks |
| Prior unknown call reconciled; no active slot held | Do not repeat the previous audit’s blocked-slot state as current fact |
| Daily host backup timer, 54-table dump and restore proof reported | Do not claim “no backups”; off-host copy remains unverified |
| 1,589 of 1,620 projects from RRC; 239 news items rejected | Strong reported symptom consistent with admission defects; not a new DB query here |
| Only 31 projects with buying-chain claims | Consistent with manual-only extraction path; not a new DB query here |

The handoff also states that the actual deployment uses `/etc/gridlens/compose.app.yaml`, runtime env and prebuilt images, while the repository runbook assumes a different layout and managed PostgreSQL. This discrepancy makes recovery instructions unreliable until reconciled. The database name alone is not a defect; prioritize known live identity, access boundaries, backups and restore safety over cosmetic renaming.

**Required next receipt:** exact running image/commit/schema, enabled processing flags, current source success dates, queue/unknown-call counts, saved-browse freshness, real authenticated list/detail/save/readback and backup location plus off-host restore evidence. Do this from the existing authorized server session; preserve its active deployment hold.

### R03 — Too much behavior is concentrated in large modules

`api/app.py` is 5,781 lines and ingestion `service.py` is 4,065 lines. Saved-browse construction imports API projection internals, while API handlers invoke ingestion and intelligence helpers. This coupling makes it easier for a correct domain function to be bypassed by a newer route, as F01 demonstrates. Mypy also reports that untyped function bodies are not checked by default.

Move canonical projection/qualification interfaces into focused application services while repairing these exact areas. Avoid a wholesale architectural rewrite. Preserve behavior with integration tests that compare default workspace, canonical detail and export—not just tests of private helpers.

The frontend production build produced one **524.68 kB minified / 160.44 kB gzip JavaScript chunk**. Eager imports include legacy environment and research surfaces. Route-level code splitting is a reasonable later improvement, but it does not outrank the commercial defects and is not proof of slow production page loads.

### R04 — Conservative qualification exists, but public-text coverage is narrow

The official power parser supports exact site/activity clauses, demand and suitable-supply intervals, date/duration checks, buyer role and conservative interval subtraction. Operator-fact qualification and negative-evidence paths also exist. This is real functionality, not a blank Power Gap Engine.

However, `qualify_official_power()` uses tightly templated sentence matches and a broad unsafe-word veto. It should be treated as a bounded parser, not general understanding of ordinary project documents. Improve extraction of evidence-grounded typed candidates and verify them against scope/authority before feeding the existing deterministic gates. Do not relax unknown supply into a Lead, or treat eventual campus MW as commissioning demand.

### R05 — Duplicate queued jobs can survive a ten-job dedupe window

`intelligence_jobs.py:436–455` searches only ten recent active jobs for a matching request digest. An older matching request can be missed after enough different tasks are queued. **The logical-call fingerprint and reservation state machine prevent a duplicate paid dispatch for the same logical identity**; the confirmed concern is unnecessary queue work/history, not duplicate billing. Query the exact active identity or add an appropriate uniqueness constraint when touching this code.

## 4. What is working and should be preserved

- Server-side session dependencies protect the inspected API mutation routes, with same-origin checks on mutations. Session tokens are opaque, stored as digests, expire and are revocable on credential changes.
- Public acquisition code has URL validation, response limits, deadline/admission controls and lease fencing. This review did not establish an SSRF exploit.
- Evidence hashes, accepted interpretation bindings, project/activity matching and prior versions are integral to qualification. These guardrails should remain.
- Provider dispatch records unknown outcome before I/O. Shared budgets, logical fingerprints, cache reuse and quarantine/reconciliation protect against blind retry and unaccounted duplicate requests.
- Saved browse separates expensive projection work from ordinary reads and refuses stale qualification generations. Fix UI failure handling rather than weakening the freshness fence.
- Tests cover many difficult cases: wrong-project evidence, parser boundaries, replay, worker failure, provenance and provider outcomes. Current-main CI exercises database migrations, schema parity, backend tests and browser regressions.
- Dependency versions and CI actions are pinned; live model keys are disabled by test fixtures. The source scan found no matches for the selected live-key/private-key patterns in the 483-file snapshot. This was not a historical Git secret scan or a proof that every possible secret format is absent.

## 5. Validation receipts and limitations

| Check | Result in this audit |
|---|---|
| Source integrity | 483/483 files matched Git blob hashes; executable modes restored from tree metadata |
| Python runtime and install | Python 3.11.17; `uv sync --locked --extra dev` succeeded |
| Backend lint | Ruff passed |
| Backend formatting | 266 files passed |
| Backend types | Mypy passed 127 source files; existing untyped-body note remains |
| Local unit suite, environment-compatible run | **1,422 passed, 2 skipped, 8 database-dependent tests deselected; 7 subtests passed** |
| Transport/source focused rerun | 52 passed, 1 skipped; overlaps the final unit suite, not additive |
| Frontend typecheck/build | Both passed; single-chunk size warning noted above |
| npm dependency audit | 0 reported vulnerabilities |
| Locked Python dependency audit | 43 audited dependencies, 0 known vulnerabilities reported |
| Current-main CI | GitHub run [39454100538](https://github.com/nrsandoval1231-oss/gl3/actions/runs/39454100538): backend and web successful, including migrations, schema check, full pytest step and browser/authentication step |
| Local PostgreSQL integration/migration tests | Not run: no PostgreSQL server; installation unavailable in this environment |
| Local Playwright/browser tests | Not run: browser archive download failed |
| Production latency, authenticated UX, data and backup state | Not freshly measured |

The first local unit attempt reported 1,407 passes, 21 failures, 2 errors and 2 skips. Investigation attributed the failures/errors to unavailable PostgreSQL, the runner’s SOCKS proxy configuration, and executable modes lost during source materialization—not confirmed product regressions. Git executable modes were restored and loopback-only tests ran with proxy bypass for local test transport while the repository’s external-network guard remained active. The final run excluded only the eight identified database-dependent tests. Initial failure evidence was not silently represented as a clean run.

Dependency tools report known advisories at execution time; zero advisories does not imply secure application logic. Current CI success is a retrieved CI receipt, not a locally repeated full-stack result.

## 6. PRD acceptance assessment

This is a targeted requirements assessment, not a claim that all 42 requirements are accepted.

| Requirement group | Assessment |
|---|---|
| Private access, evidence retention, deterministic gates (3, 9, 16, 19–26) | Substantial implementation; correction and limiter defects above need repair; live acceptance unverified |
| Broad discovery and monitoring (2, 5–12) | Implemented acquisition infrastructure; useful breadth constrained by admission and reported source/runtime state |
| Automatic investigation and buying responsibility (15, 28–29) | Existing capabilities; retained buying-chain automation missing from normal ingestion path |
| History, corrections, feedback (17, 30) | Preserved versioned records; correction-target validation incomplete |
| Explainable ranking (27) | Weighted policy exists but default workspace bypasses it |
| Morning changes (32) | Explicitly unavailable in default workspace |
| Practical UI and data access (33–34) | Build/types pass; stale-results error transition needs repair; live/mobile acceptance not rerun |
| Recovery/operations (35–36, 40) | Significant mechanisms and dated host receipts; current deployed state, off-host restore and seven-cycle proof not established here |
| Commercial acceptance (38–41) | Do not declare complete from source count or test count; fresh multi-industry useful-output sample and real pursuit proof still required |

## 7. Ordered repair plan

### Batch A — Correct what Nick sees and acts on

1. Fix F01 default ranking with an endpoint-level inversion regression.
2. Review and complete existing PR #96; validate held-out early-stage and location cases; add a bounded versioned replay of retained news.
3. Fix F05 stale rows/counts after refresh failures and F07 cohort counts.

**Gate:** A real relevant project can be found, prioritized, opened and explained consistently across list/detail/reload. Unknowns remain explicit. No generic permit label or low-value feed volume may substitute for evidence of a useful pursuit.

### Batch B — Make retained evidence callable and corrections trustworthy

4. Add the retained-only automatic buying-chain job from F03, with idempotent bounded backfill.
5. Repair F04 correction validation; verify fact acceptance, correction, retraction, conflicts and tier readback end-to-end on PostgreSQL.
6. Repair F06 login allowance consumption and add distinct-client/concurrency regressions.

**Gate:** A supported project organization appears without manual enrichment; a legitimate call fact updates exactly the intended need, and a correction does not accidentally retain or erase the wrong accepted fact.

### Batch C — Establish operational acceptance

7. Reconcile the actual host deployment/runbook and obtain a fresh read-only production receipt. Respect the existing deployment hold; this audit does not authorize deploying open PRs or activating paid features.
8. Verify off-host backup and restoration; keep production and scratch databases unmistakably identified.
9. Enforce a simple main-branch check gate.
10. Benchmark saved-browse publication under ingestion and operator writes before increasing source volume. Proposed engineering target: p95 bounded list/detail reads <=1 second and no unexpected 5xx in an explicitly recorded sample; this is a proposed target, not a measured result.

### Batch D — Complete the daily decision product

11. Connect the morning-change briefing to retained change events.
12. Review 30 independently discovered Signals/Prospects against PRD requirement 39, stratified across priority industries and sources. Measure useful projects, not just records.
13. Demonstrate one evidence-backed commercial pursuit through buying organization, next action, call facts and reload. Claim a Lead only when its required evidence exists. Preserve the seven daily cycle and live source-family gates.

**Completion standard:** Nick can open GL3, understand what changed, select a well-ranked relevant need, identify a supported organization, make a useful call, and save facts that change the same opportunity correctly. That is the next product milestone.

## 8. Boundaries

No source, application setting, database, deployment, budget, paid provider or GitHub branch setting was changed. No issue, PR comment, merge or external message was posted. The report distinguishes code defects from reported host conditions and design risks. Binary assets, full historical Git secret scanning, live penetration testing, live performance and full local database/browser validation remain outside the completed evidence.
