# Single instrumented backend full run — PR160

2026-10-31; existing draft https://github.com/nrsandoval1231-oss/gl3/pull/160

## Result and disposition

**PASS:3667passed,1skipped,11warnings in336.98seconds; process338.677seconds, exit0.** Exactly one additional full run was performed under the unchanged four-worker/480second gate. All3668collected test cases have teardown receipts; no failed reports. Source, assertions, selection, workflow and time limit were unchanged. Current head remains `78591b308aa829a25157bf3310133ed069434d3b`, tree `125b7dc0ee61a890b1dffff40f3b2891df3be9c1`.

This is **an instrumented diagnostic pass, not exact CI-command equivalence and not a resolution of the original failure**. It did not reproduce a stuck test or timeout. Variability remains unexplained. The earlier fresh exact-command local timeout at480.095seconds remains a failed receipt. No further rerun, code fix or PR update is justified by this result alone. No loop-until-green was performed.

## Actual command/environment

From `/workspace/gl3-phase1/backend`:

```
timeout 480 uv run pytest tests -n 4 -p runtime_observer --durations=30
```

Start17:14:54UTC; metadata.json holds monotonic reference. Python3.11.16, pytest9.1.1, xdist3.8.0, Debian13 saved cloud host. Existing disposable PostgreSQL18.6 container `gl3-local-ci-pr160-backend-1644` was restarted; test session recreated four *_gwN_test databases through existing conftest. Application gridlens and controller gridlens_test URLs were distinct; no production target. CI=true, default WORKER_AUTO_REFRESH, disposable bcrypt default-cost/session values, model keys blank, repository network guards active. Existing cloud caches/cluster were reused; this is not a cold/fresh-instance reproduction. No competing validation workload or child reviewer workload ran. Container stopped after capture.

## Instrumentation and its limits

External file `runtime_observer.py` loaded with `-p` and external PYTHONPATH; no repository changes. Each worker appended JSONL on test start and setup/call/teardown completion, plus session end. Events have worker/node IDs, monotonic timestamps, phase outcomes/durations. One external persistent administrative PostgreSQL connection sampled active test-database sessions and cgroup counters every5seconds; its own queries had1000ms statement_timeout. Built-in --durations=30 printed the slowest phases. Full command, configuration and checkpointer baselines:metadata.json. Exit/runtime:result.json.

Measured observer work across workers:14679events,0.367931seconds serialization and0.157777seconds writes, totaling0.525708seconds.68database samples consumed0.309885seconds aggregate query time, maximum12.122ms. These sums span parallel workers; they are **not a wall-clock overhead correction**. They omit hook dispatch/scheduling effects, filesystem/cache perturbation, cgroup read/observer processing costs, and the possibility of timing-sensitive race effects. There was no paired uninstrumented control. Thus actual end-to-end instrumentation overhead is unquantified, despite small measured direct costs. Five-second sampling can miss short contention, including a one-second assertion. Observer output uses append writes without fsync; nothing weakens test durability settings.

## Tail and distribution

All workers progressed. Worker completion:

| Worker | Cases completed | Last teardown, seconds from command start |
|---|---:|---:|
|gw0|518|189.83|
|gw1|2351|183.41|
|gw2|397|335.11|
|gw3|402|317.63|

The final150seconds had an observed scheduling/work-distribution imbalance:two workers had finished while two continued. This is a measured distribution in this passing run, **not proof that changing scheduler settings would fix the failed run**. No scheduling change was made. At239.67seconds3472tests had completed (about94.7%); active tests were bulk saved-browse ingestion and research transitions. At296.48seconds3567had completed; active tests were saved-browse checks. Final12test teardowns were source-scheduling cases ongw2 from332.95through335.11seconds; each made progress. There was no test still running near480seconds because the process finished at338.677seconds.

Largest file-level accumulated phase time (setup+call+teardown summed across workers, not wall time):saved_browse183.53s/127cases, buying_chain86.93s/119cases, research_transitions58.55s/38cases, pursuit_evidence53.95s/44cases, power_need_briefs43.35s/48cases, evidence_shadow_storage42.46s/15cases. Full distribution inanalysis.json; raw per-worker events retained.

Slowest calls and comparison to the earlier bounded targeted run:

| Test | Full diagnostic | Targeted diagnostic |
|---|---:|---:|
|saved_browse::test_structured_ingestion_bulk_commit_keeps_authenticated_maps_current|29.39s|34.92s|
|evidence_shadow_storage::test_shadow_rotates_through_more_than_two_hundred_candidates|24.91s|20.58s|
|evidence_shadow_storage::test_shadow_wrap_scans_past_consumed_prefix_to_find_unseen_candidate|12.77s|12.81s|

Other full-run slow calls:autonomous_questions::test_real_projection_groups_outside_shortlist_before_research_planning13.51s; power_need_briefs summary parityFalse12.54s/True9.68s. Original one-second daily-lock test passed unchanged; call0.129879s, setup0.095403s, teardown0.000591s. No direct measurement of just its future.result interval was injected.

The earlier350.31second local pass and480.095second failure did not preserve per-node durations/timestamps. The hosted362.56second pass also lacks per-node durations. Consequently, a test-by-test comparison against those runs, or identification of the original failed tail, is impossible from retained logs. The table above uses actual targeted durations, not invented historical timings. Dynamic xdist scheduling means identical percentages do not identify identical tail tests.

## Resource/database evidence

Cgroup sample delta:945.156CPU-seconds over approximately335seconds between first/lastsamples;65additional throttled periods and0.597012seconds throttled_usec. Sampled cgroup memory peak11727290368bytes (~10.92GiB), including process/cache usage; memory/OOM event counters remainedzero. Cgroup capacity4CPU/16GiB. Counters cover the environment, not exclusively pytest; no pressure files available. These measurements show no OOM or large recorded quota-throttling event in this passing run and cannot retrospectively prove failed-run conditions.

Active-backend wait samples:53no wait event;1transactionid lock;1LockManagerLWLock;1ClientRead;1VacuumTruncate;2WalSync;6VacuumDelay;2WalInitSync;1DataFileExtend. This is sparse sampling, not total wait-time attribution. It did not show sustained lock contention. The long calls therefore remain measured slow workloads, not proven blocking defects.

Six completed checkpoints during observation (seven requested), with157.869s checkpointer write_time and76.727s sync_time deltas. Significant background checkpoint sync also occurred in this **passing** run. This further rejects treating long checkpoint elapsed/sync totals alone as sufficient proof of the480second timeout cause. PostgreSQL durability/cache settings stayed unchanged; no fsync/synchronous_commit relaxation. Raw logspostgres.log, sampled queries/resourcesobservations.jsonl.

## Comparison with preserved full-suite receipts

| Receipt | Result |
|---|---|
|Earlier local uninstrumented candidate|3667passed/1skipped/7subtests in350.31s; command355.946s|
|Hosted CI41220159391 backend124592885866|3667passed/1skipped in362.56s, Ubuntu24.04/Python3.11.18, GitHub merge9d82c33 containing78591b3|
|Fresh local exact CI command|FAIL exit124 at480.095s,3668collected, last printed94%, no final summary|
|This single instrumented full run|PASS3667/1skip/11warnings in336.98s; command338.677s|

Original CI report remains `/workspace/local-ci-pr160-20261031-1644/REPORT.md`; previous investigation and independent source review `/workspace/pr160-runtime-diagnostics-20261031/REPORT.md` andenvironment-analysis.md. Neither the passing runs nor this instrumented observation supersede the exact-command failure. Root cause and repeatability of the failure remain uncertain; no reproducible product bottleneck or host limitation was established. Runtime variation and tail imbalance were observed.

## Artifacts / action state

- REPORT.md: this report.
- pytest.log: actual complete pytest output, warnings,30slowest phases.
- events-gw0.jsonl … events-gw3.jsonl: test start/phase/end receipts; events-controller.jsonl:controller finish.
- observations.jsonl:68periodic database/cgroup observations.
- metadata.json/result.json/analysis.json:actual command/configuration, exit/runtime, parsed distribution/counters.
- runtime_observer.py/run.py/analyze.py/status.py:external reproducible diagnostic helpers.
- postgres.log:local disposable database logs (includes earlier container history; use timestamps).

No source edits, commits, pushes, PR mutation, new Actions, production requests/writes, paid calls, timeout increases, new infrastructure, PC use, merge or deployment. All commands finished and database container stopped. No action denied or pending approval. Uncertain item:why the original exact-command local run exceeded480seconds. No further full run will be started under this instruction.
