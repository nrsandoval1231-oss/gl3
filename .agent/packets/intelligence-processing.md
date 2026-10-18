# B2/D — Queued bounded intelligence processing

Depends B1 interface and deterministic gates. Same worktree/branch/base as B1.
Objective: all eight advisory Jev tasks and grounded OpenAI extraction/reasoning
run through existing fenced jobs and durable shared call ledger, with persisted
results, exact evidence/context identity, strict schemas and no canonical model writes.

Allowed: new `intelligence/intelligence_jobs.py`, `grounded_candidates.py`,
`question_contracts.py`, `integrations/intelligence_provider.py`; existing worker
dispatch branch, settings, narrow existing EvidenceJudge/brief/research invocation
wiring as explicitly documented. New focused tests. Controller must approve any
needed foundation/schema repair before touching B1-owned files.
Excluded: API/web, new tables/migrations without identified unmet need, qualification
gates, source registry enablement, editorial, provider activation/spend/production.

Use existing actual Source for target jobs; no fake source or generic source-only
enqueue. Enqueue identity binds need/project/evidence version(s), current accepted
context, task/schema/prompt/policy/provider/model. Job checkpoint stores request and
call ID; logical result JSON stores candidates. Recompute freshness before dispatch
and publication. Reserve fresh sessions, current job lease/fence, current flags and
finite configured per-scope caps; commit uncertain outcome before remote send.
No retry/refund after unknown effect; cancellation before send safe. Network outside
DB transaction; hard bound below lease. Unknown usage/cost null, actual model recorded.

Provider configs: separate empty fast/reasoning pinned IDs; existing TypeSafe
transport shape from official spec, no guessed IDs/pricing. One Responses integration
with strict JSON schema/store:false/no provider browsing/tools. Eight catalog choices
per owner. Per-contract/provider/research switches; disabled/evaluation/advisory/
bounded-routing states. Routing activation requires explicit evaluated policy; no
model route grants scheduling authority itself.

Grounded claim schema: field/value/unit, exact evidence ID+hash, quote/span/location,
publisher/date, direct/inferred/ambiguous, candidate/reviewed/accepted/rejected
states. Verify exact retained passage supports units/date precision; reject campus
MW as temporary demand, applicant as buyer, flare as available fuel. Quote validation
does not grant source authority. Results remain advisory candidates; existing
source/identity/consistency/admission services exclusively own canonical writes.
Question types: UTILITY_ONLINE_DATE,TEMP_LOAD_MW,CONSTRUCTION_START,
COMMISSIONING_WINDOW,NATURAL_GAS_AVAILABILITY,DIRECT_BUYER_AUTHORITY; map existing
question categories rather than replacing existing question history.

Expose service interfaces for F: enqueue_intelligence(session,...)->job;
intelligence_history(session,need_id,limit<=50); processor(job_id,worker,fence);
strict request/task registry and schemas; return explicit blocked/unknown/stale.
Reasoning gets bounded accepted/retained dossier; citations only fetched evidence;
query suggestions untrusted data and acquisition allowlist owned by code. Existing
retrieval and retained research path reused in E. No auto Lead or uncertain merge.

Acceptance: fake transport all eight; queued extraction and question result journey;
no duplicate on unchanged/context replay; changed version reprocess; invalid spans/
units/date/schema/injection denied; zero flags/budgets/probes/fallback no network;
crash windows, live lease turnover, kill-after-reserve, cancellation, stale input,
missing usage null. Existing judge/brief/research regressions. Focused Ruff/mypy.
Two materially different repairs then controller reconstructs PRD direction.
Completion artifact files/commands/UTC durations/limits/UNKNOWN tokens; no self PASS,
commit/push/merge/deploy. Release test DB to controller at handoff.
