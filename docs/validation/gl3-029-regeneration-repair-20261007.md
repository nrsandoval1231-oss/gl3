# GL3-029 regenerated corpus — retained-input ordering repair

**Four selected real cases now pass. Full five-cohort acceptance remains incomplete.** This follow-up repairs the recoverable stale-input failures in the [first regenerated diagnostic](gl3-029-regeneration-20261007.md), whose failed receipts remain unchanged. Neither run is original PR23 retained-corpus proof. PR24 remains draft, unmerged and undeployed.

## Cause and implementation

Both initial questions were fingerprinted before the worker's retained-only buying-chain preparation. That preparation derived supported relationships from unchanged canonical Evidence, changed the commercial input hash, and invalidated the queued sibling. The guard correctly stopped it, but the ordering caused avoidable failures.

`schedule_questions` now prepares retained relationships before reevaluating exact targets and freezing their question contexts. It uses the existing canonical relationship extractor and evaluator, performs no external retrieval/model call, excludes any project with an active question, and acquires unique project locks in deterministic order. The worker's evidence/source fingerprint guard and job fences are unchanged. Real changes after queueing still fail before acquisition. Historical contexts and failed attempts are not rewritten.

The local preparation pass covers supplied eligible projects independently of the daily question acquisition cap. Unchanged relationship and run identities are reused. No migration, new provider, source admission relaxation or general orchestration was added.

Frozen code candidate: `15f4910c812c33de3b7a516ea455a06038537bfc`.
Source/configuration hash: `361b468c24db80207bd7f4b7788df3d5f56aea4314dd8970feb98cc5849e72ac`.
Subsequent documentation-only commits publish these receipts without claiming their future commits were executed.

## New real execution

A separate clone, `gl3_regen_20261007_repaired`, was restored from the unchanged fresh source corpus: **14 Evidence rows, 13 Signal PowerNeeds**. The planner fix was applied to the original unprepared state, not the previously researched clone. All 28 table inventories matched before execution.

Fresh backup SHA256: `a3c69aba7f9189d2c7f4d5df60294633b5942f6d2269778088f1e8f1d736d26e`.
Evidence inventory SHA256: `7a1594f33a62e862121c137685f1fae1a6430ad075e1c65a4cc81987d8429d40`.

| Case | Actual result | Acceptance |
| --- | --- | --- |
| Austin data center, 811 Clayton Ln | ACTION NOW unchanged; Signal unchanged; no question needed | Existing narrow no-question/no-change exception |
| Austin explicit temporary power, E Braker Ln | ACTION NOW unchanged; Signal unchanged; no question needed | Same existing exception |
| Chicago conversion, 400 S La Salle St | Two bounded native-source questions, both UNRESOLVED; RESEARCH/Signal unchanged | Meaningful investigation passed |
| Low-quality scope, 2800 S Ashland Ave | Two bounded native-source questions, both UNRESOLVED; RESEARCH/Signal unchanged | Meaningful investigation passed |
| O&G | RRC drilling route investigation described below; no record download/admission yet | Missing; full acceptance false |

Run interval: October 7 `02:43:01.660571`–`02:43:13.295202` UTC (11.635 seconds). Four question jobs, four UNRESOLVED, **zero FAILED**, zero pending replacements/queued jobs. Two native retrievals, zero executed searches, zero model calls, $0 known provider cost. Median question latency 1.671 seconds; failure rate 0%; four duplicate-work-avoidance events. Generated discovery queries were not executed; Firecrawl was unavailable.

No commercial or evidence-tier transition occurred. Existing Evidence/history/identities were preserved. Relationships were derived before questions, without purchasing-authority inflation. Dry replay created zero questions and retained exact state hash `17c56bf6bea0f40ab8230f4a33ac235ba32679888c679324845700f9fc1f43ab`.

The unchanged five-case validator still rejects the four-case manifest. Partial mechanical acceptance is true; full five-cohort, original retained proof and original-corpus attestation remain false. Detailed questions, source checks, citations, before/after states, costs, hashes and limits are in the [safe receipt](gl3-029-regeneration-repair-20261007.json). Original failed receipts are not relabeled successful.

## Corrected O&G assessment: existing RRC drilling

The earlier fixed-infrastructure-only scouting was too narrow. The existing `texas-rrc-drilling-permits` adapter and admission policy already support dated, identified, approved drill/reentry/recompletion permits as early production Signals. No demonstrated power shortage is required for that Signal gate. Load, production date, fuel suitability, rental demand and buyer remain unknown.

Two bounded public listing GETs both returned **HTTP 200**:

- [Daily RRC file listing](https://mft.rrc.texas.gov/link/5f07cc72-2e79-4df8-ade1-9aeb792e03fc): `daf420.dat`, modified October 6, 305.70 KB.
- [RRC monthly file listing](https://mft.rrc.texas.gov/link/f5dfea9c-bb39-4a5e-a44e-fb522e088cba): required September `daf420.dat.09-30-2026`, modified October 1, 2.67 MB.

The current filenames/freshness pass existing adapter checks. Its next step is an anonymous public download form POST, followed by a same-host GET. No login is involved. Because the original specification prohibits form submissions, an explicit clarification was requested before that operation. **No file download was attempted; no download HTTP error or lack of eligible drilling records is claimed.** Actual records and admission remain unverified until that download is permitted and executed through the existing pipeline.

The actionable next step is to permit this narrowly defined public-file download or provide the current official files for the existing parser. That enables real O&G case selection without a new adapter or weaker qualification. The research worker still lacks a bounded exact-record RRC research route; retained context and any other permitted configured route must be assessed honestly after ingestion. Merely acquiring the cohort does not itself pass meaningful research acceptance.

## Validation and independent review

On frozen candidate `15f4910`:

- Full backend: **1,197 passed, 1 skipped**, one existing warning, 141.27 seconds. The skip is the optional local NC access probe.
- Focused validator/regeneration subset: **71 passed**.
- Ruff and mypy: passed; 77 source files.
- Frontend typecheck/build: passed; npm audit: 0 vulnerabilities; OpenAPI exact.
- Browser regression: **36 passed**, 36.2 seconds.
- Supplemental real-database browser: all four check groups passed against a separate repaired restore, without API mocks; actual question status, prior context, citations, budgets and mobile reload inspected.
- Clean upgrade, populated 0013→0014 upgrade, repeated upgrade and drift check: passed. All 28 table inventories match after the populated migration cycle.
- Backup/restore and research preservation/replay: passed.
- Six named historical live-browser cases: unavailable/not run; supplemental fresh-data checks are not historical proof.

The canonical Chicago regression proves two sibling questions finish on unchanged evidence, active contexts are not prepared again, relationships/questions are not duplicated on replay, and Signal tier remains unchanged. The existing genuine post-queue input-change test still passes and stops before acquisition.

Independent review of the final code and actual repaired artifacts found no material issue: deterministic lock order, active-project exclusion, unchanged guards, four-case acceptance, preserved Evidence/history, settled queue and exact replay were verified. Full five-cohort acceptance remains separate.

No outreach, credentials, purchases, access-control bypass, merge or deployment occurred. Cloud operation remains a separate milestone. The only acquisition authorization currently pending is the existing RRC anonymous download operation; historical browser prerequisites remain distinct.
