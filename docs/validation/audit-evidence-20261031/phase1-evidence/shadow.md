# Shadow concurrency deadline investigation — Phase1

Base `/workspace/gl3-phase1` main593cfd516d82a12b66558f53b975ad6c2b711517. Diagnostic-only scope so far; no product/test source edits, stress load, providers or production access. Read AGENTS and unchanged current canon/architecture/finish constraints. Uses newly created dedicated `audit_phase1_shadow_test` at127.0.0.1:55432 on parent's disposable PostgreSQL18.6, separate from other application/test DBs. External diagnostic `/workspace/phase1-evidence/shadow-profile.py` imports existing synthetic seed and FakeJudge, records SQL execution timing and cProfile, and temporarily wraps project_state only within its own process. No instrumentation persisted in product code.

## Prior failed gate remains failed

Original audit full suite:1failed3650passed1skipped7subtests625.84s. Failure was Future.result(1) in shadow lock testline255, not a failed0attempt/0judge assertion. Three unchanged isolated reruns passed. Those results remain historical evidence for the exact original candidate and do not establish the original cause or current full-suite acceptance.

## Controlled boundary measurements

No CPU saturation or stress workload used. Seeded one physical project/one power need with1,10or100 synthetic evidence records and ran once with daily reservation lock held, once without. The daily lock was held by a separate DB session under647809130122; release was explicitly signaled after each operation. Profiles are process-level controlled diagnostics, not production benchmarks.

| Evidence records | Held lock duration ms | project_state ms | total SQL | project_state SQL | attempted/judge |
|---|---:|---:|---:|---:|---|
|1|178.53|104.47|22|13|0/0|
|10|67.99|39.30|31|22|0/0|
|100|204.99|163.38|125|116|0/0|

Unlocked cases:1/10/100 records62.07/65.42/200.39ms and26/35/129SQL respectively; all attempted1/judge1. First sample has cold query compilation overhead, so wall times are not monotonic perdata volume and cannot be treated as a regression trend alone. SQL count scaling is deterministic evidence. All samples returned correctly below1second; original timeout was not reproduced at idle.

The held-lock path spends work preparing candidate/context before trying lock: `evidence_shadow.py:306` calls `project_state`; only`:359` executes PostgreSQL's nonblocking `pg_try_advisory_xact_lock`. If acquisition returnsfalse,`:360-362` rolls back/breaks with0calls. The test's1second Future limit includes SQL compilation, context/relationship loading, scheduling, and DB latency before that acquisition. This supports a load-sensitive end-to-end test budget hypothesis, but does not prove original resource contention, PostgreSQL blocking, or the exact consuming call in the original failed run.

## Concrete redundant-query source identified

`intelligence/buying_chain.py:983` selects Evidence and Interpretation for each bounded retained-evidence page. At`:1006-1007` it discards the already-selected Interpretation and invokes `_retained_evidence_current_for_project` without preloaded inputs. That helper`:899-906` issues another scalar Interpretation query by observation_id for each record (and may fetch Observation/Source if not in identity map). For100records, cProfile attributes100helper calls/103ms to this path inside `_retained`/`_permit_summaries`; state preparation uses116SQL. Exact source maps and every SQL prefix/timing are in shadow-profile.json; full cProfile outputs shadow-profile-{count}-{True|False}.txt.

A potential narrow optimization is to select existing Observation/Source/Interpretation values in the bounded page and use the helper's existing preloaded=True path, preserving current-binding rules, order, paging, and target fallback. This touches buying_chain.py outside this lane's owned files; proposed to coordinator before any edit. It could remove provenN+1 work but is not established as the cause or fix of the original one-record timeout. No arbitrary deadline increase, semantic test weakening or lock-order change is justified by current evidence.

## Decision / limits

Original timeout root cause remains unresolved; no product fix has been made. Current known behavior is correct in these controlled cases; profiled pre-lock context cost and redundant query growth are supported findings. Next work, if authorized, should add a deterministic query-bound/parity regression for retained evidence and independently review any focused optimization. A complete gate under the existing480second CI budget remains necessary; do not erase prior failures or replace it with narrow passing results.

## Approved narrow implementation and red/green evidence

Coordinator approved only the measured redundant-query fix in `buying_chain._retained`, plus a new isolated regression file. Product change selects existing Evidence, Observation, Interpretation and Source in each bounded24-row page; Source remains an outer join; passes these exact objects through the existing preloaded=True current-binding path. No locks, deadlines, acceptance conditions, page ordering, target fallback, freshness thresholds or provider behavior changed.

New `backend/tests/integration/test_retained_evidence_loading.py`: three real-PostgreSQL query-count cases with1/25/73stale-prefix evidence records plus4accepted records, and seven exact-binding/status cases (accepted, failed/pending last-accepted assessment, rejected, evidence-hash mismatch, wrong project, missing interpretation). RED `/workspace/phase1-evidence/shadow-red.log`:3failed7passed because SELECT counts15/64/162exceeded boundedpage counts1/2/4; accepted output already matched. GREEN `/workspace/phase1-evidence/shadow-green.log`: all10new cases plus complete15-test shadow module **25passed54.43s**. Existing one-second concurrency test passed unchanged. Ruff check/format and scoped git diff --check passed. Full integrated gate belongs to parent and remains pending.

Before profiles retained in `/workspace/phase1-evidence/shadow-before/`; after profiles in root shadow-profile.json and shadow-after-profile.log. Held dailylock SQL for1/10/100evidence: **22/31/125before →21/21/25after**. Project-state SQL13/22/116before →12/12/16after. Attempted/judge0/0held and1/1unlocked unchanged. Wall times after were348/77/206msheld and97/82/265msunlocked; shared-host/cold-compilation differences mean these samples do **not** demonstrate latency improvement. Deterministic query reduction is the supported performance result. Original one-record timeout cause remains unproven; this optimization is not presented as fixing it.

## Additional interrupted module run and newly proven fixture-clock issue

I started a redundant full buying-chain module run after profiling; coordinator requested stopping to reserve full-gate verification for parent. SIGINT interrupted that ownprocess after39.84s: **8failed22passed1warning**, raw `/workspace/phase1-evidence/shadow-buying-chain.log`. Failures were empty current contact methods in tests membership-only company discovery, contact refresh, three team-card cases, two generic-method refresh variants and exactRRCphone. These failures are disclosed and not overwritten by narrowpasses.

Controlled same-test baseline comparison proved a fixture-date defect independent of this preload change. External diagnostic plugin `/workspace/phase1-evidence/shadow_baseline_plugin.py` restores only HEAD's original `_retained` function inside its pytest process (source tree untouched). `test_membership_only_company_contact_job_persists_canonical_method` at actualOct31 **fails1.42s** with emptyemail (`shadow-baseline-contact.log`). Identical HEADfunction/test with only canonical read evaluation context set toOct30 **passes1.41s** (`shadow-baseline-contact-oct30.log`). Fixed module NOW is2026-09-30; `buying_chain.py:2537-2540` correctly suppresses literal contacts when age exceeds30days, so the fixture crossed its boundary atOct31. This is a confirmed test-clock problem, not a reason to relax production freshness. Proposed to parent: explicitly anchor read evaluation context to the existing synthetic fixture's NOW within this module; keep all original assertions and deliberate age-offset tests. No fixture/date edit made in this lane pending coordinator direction.

## Authorized deterministic fixture clock

Coordinator authorized a minimal change to existing `test_buying_chain.py` db fixture: wrap its yielded session factory with `evaluate_at(NOW + timedelta(days=29))`, i.e.2026-10-29, after latest synthetic source captures datedOct28 and before fixedSep30contact captures exceed30days. This changes only the context-local default clock of canonical **read projections** during these synthetic tests; systemtime, auth expiry, session leases, sourcewrites, production freshness thresholds and all assertions remain unchanged. Explicit now arguments remain authoritative, and existing nested evaluate_at boundaries override the fixture context. In particular `test_expired_public_contact_method_is_hidden_but_company_relationship_survives` still uses NOW+366days and nested evaluate_at(old); `test_stale_role_does_not_erase_direct_organization_relationship` still uses NOW+370days. No assertion was removed or loosened. Full buying-chain module validation running in own isolated DB; exact result will be appended below. Scope now comprises buying_chain.py, new retained-loading regression file, and the approved buying-chain test fixture only.

Final module result: `/workspace/phase1-evidence/shadow-buying-chain-clock.log` **119passed,1existing Starlette TestClient deprecation warning in70.74s**. This includes unchanged explicit expired-contact, stale-role, independent-role-conflict, retraction/correction, retained-version and target-binding coverage. Scoped Ruff check, Ruff format check and git diff --check all passed. All three owned files are frozen for independent review and parent full-gate verification. No source provider/live write, lock change, freshness weakening, raised deadline or stress test occurred.
