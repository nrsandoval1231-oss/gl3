# Remaining audit: backend runtime variability

## Scope and conclusion

Audit-only analysis of preserved receipts on2026-10-31. Current merged main `00026c758ece2bc41eea88c478cbb0112f9e0de5` and PRhead `78591b308aa829a25157bf3310133ed069434d3b` share complete tree `125b7dc0ee61a890b1dffff40f3b2891df3be9c1`, per release-readiness/source-identity.json. Local source inspected at78591b3 with that exact tree. No source/test/workflow edits, tests, reruns, database requests, providers, production access or credential actions were performed. Only existing files were read and this report written.

**No validated product defect explains the original local480second timeout.** The passing diagnostic establishes real slow workloads, repeated fixture setup cost and a long partially occupied worker tail. Those are useful measurement targets, not proof of the failed run's tail or a justification for changing scheduling, assertions, data volume, isolation, PostgreSQL durability or the480second gate. No forced fix is recommended.

## Exact full-run facts

| Receipt | Actual result | Distinction |
|---|---|---|
| Earlier local candidate, phase1-evidence/backend |3667passed/1skipped/11warnings/7subtests;350.31spytest,355.946sprocess; exit0|Verbose direct pytest; no per-node durations/timestamps.|
| Hosted PR CI41220159391, backend124592885866 |3667passed/1skipped/11warnings;362.56s|PRmerge9d82c33 containing78591b3; Ubuntu24.04/Python3.11.18, separate host.|
| Fresh exact-command local CI, local-ci-pr160-20261031-1644 |GNUtimeout exit124 after480.095s;3668collected, last printed94%|No final summary or tail node identities. This remains a failed receipt.|
| Single full instrumented local diagnostic, pr160-runtime-full-20261031 |3667passed/1skipped/11warnings;336.98spytest,338.677sprocess; exit0|Exact selection/fourworkers/480s preserved, but external observer and --durations=30 make it a diagnostic command, not exact CI-command equivalence.|
| Hosted merged-main CI41226509696, backend124611701811 |3667passed/1skipped/11warnings;346.00s|Exactmain00026c75/sharedtree; complete hosted gate passed.|

The full diagnostic command was `timeout 480 uv run pytest tests -n 4 -p runtime_observer --durations=30`. It reused/restarted the previously fresh disposable PostgreSQL18.6 cluster; conftest recreated four worker test databases. It was not a cold-instance reproduction. All3668test teardown receipts exist and no phase failed. The summary does not print a separate subtest total; do not invent one. Earlier or later passes do not erase the failed local receipt or demonstrate why it was slow.

The prior bounded diagnostic (142saved-browse/shadow tests,72.43s) is subset evidence only. Its two invalid preliminary harness attempts are preserved and excluded from passing claims in pr160-runtime-diagnostics-20261031/REPORT.md.

## P3: observed tail imbalance is a validation-efficiency concern

Independently reaggregated raw events-gw*.jsonl against metadata.started_monotonic:

| Worker | Cases | Sum setup/call/teardown seconds | Last teardown | Session finish |
|---|---:|---:|---:|---:|
|gw0|518|183.76|189.828s|189.829s|
|gw1|2351|175.01|183.414s|183.414s|
|gw2|397|329.10|335.106s|335.107s|
|gw3|402|311.60|317.630s|317.631s|

At190seconds3390cases had completed,278remained, and onlygw2/gw3 subsequently reported work. At317.7seconds65cases remained, all ongw2. Thus the last~145seconds had at most two active pytest workers, ending with~17.5seconds on one. This is a measured distribution in the passing run. It does not show that pytest was frozen or identify any test in the failed run.

The busiest worker's accumulated phase time is nearly its entire330second span after first start. Its largest components were saved_browse155.42s, pursuit_evidence53.95s and power_need_briefs43.35s. gw3 carried research_transitions58.55s, evidence_shadow_storage42.46s and another28.11s of saved_browse. Case count alone would be misleading:2351mostlyshort cases ongw1 finished well before397heavier cases ongw2.

Inspected installed pytest-xdist3.8.0 `scheduler/load.py`: default LoadScheduling.schedule initializes consecutive chunks of `floor(floor(3668/4)/4)=229` cases perworker, then adapts refill thresholds using outstanding counts and last duration. check_schedule shuts a node down when global pending is empty. remove_pending_tests_from_node raises NotImplementedError in this scheduler; it does not normally steal already-assigned pending cases from another healthy worker. This makes observed tail imbalance plausible under heterogeneous test costs. **Actual assignment/queue lengths were not recorded**, so initial chunks or any individual scheduling decision cannot be declared the cause. No scheduler change was tested or recommended as an established fix.

Practical impact: variable suite duration and reduced headroom under480seconds, with incomplete diagnostics when the cap is reached. The diagnostic process finished with~141seconds to spare, but that is one observation, not a reliability bound or guaranteed future margin.

## Measured slow work and fixture cost

All values below are phase elapsed time; they overlap across workers and must not be added as full-run wall time.

| File | Cases | Setup | Call | Teardown | Total |
|---|---:|---:|---:|---:|---:|
|saved_browse|127|62.70s|107.45s|13.38s|183.53s|
|buying_chain|119|10.61s|76.21s|0.10s|86.93s|
|research_transitions|38|17.39s|37.69s|3.47s|58.55s|
|pursuit_evidence|44|19.00s|29.78s|5.18s|53.95s|
|power_need_briefs|48|not separately listed here|—|—|43.35s|
|evidence_shadow_storage|15|not separately listed here|—|—|42.46s|

Across all workers:337.78ssetup,603.47scall,58.22steardown,999.48ssummed phases. Setup+teardown comprise~39.6% of summed phase time. Dividing999.48byfour is **not** an achievable runtime estimate: tests are indivisible, resource contention changes durations, and fixture/order constraints plus scheduler behavior matter.

Source inspection confirms saved_browse.py:40-71 uses a function-scoped fresh UUIDschema, creates all model tables and browse triggers, and drops the schema afterward. Its measured fixture setup+teardown is76.08s across127cases. Other modules use db_reset.py:37-83, which reuses schema and truncates tables while explicitly handling DDL invalidation and non-superuser behavior. This source difference supports measuring DDL/trigger/catalog cost separately, but does not prove that all62.70ssetup is PostgreSQL I/O, or that replacing the fresh-schema fixture would preserve its concurrency/migration isolation. Do not weaken isolation based on this audit.

Slowest full calls, independently checked against raw duration reports:

- saved_browse::test_structured_ingestion_bulk_commit_keeps_authenticated_maps_current:29.39s (targeted34.92s). Source at:1819 seeds200projects and tests real publication/read concurrency; a bounded intentional workload.
- evidence_shadow_storage::test_shadow_rotates_through_more_than_two_hundred_candidates:24.91s (targeted20.58s). Source at:377 seeds225evidence records and requires220distinct attempts across11batches.
- autonomous_questions::test_real_projection_groups_outside_shortlist_before_research_planning:13.51s.
- evidence_shadow_storage::test_shadow_wrap_scans_past_consumed_prefix_to_find_unseen_candidate:12.77s (targeted12.81s). Source at:412 seeds1205records to test traversal past a consumed prefix.
- power_need_briefs summary-parity cases:12.54s/9.68s.

These are reproducibly expensive within preserved measurements, not proven runaway loops, accidental live requests or product failures. Do not reduce fixture data counts or skip cases to improve timing. The original one-second daily-lock assertion passed unchanged; measured full call0.129879s, setup0.095403s, teardown0.000591s. That does not establish the exact future.result interval or resolve its earlier load-sensitive failure.

## Causal claims checked

- **Original failed tail:** unknown. Earlier logs lack per-node timing and fresh output is bare progress. Dynamic xdist order means similar94% markers do not identify equal tests. The diagnostic's final12teardowns are source-scheduling cases; this cannot be projected backward onto the failure.
- **Worker auto-refresh:** earlier explicitfalse versus fresh/defaulttrue is real. Prior environment-analysis.md traces the sole runtime consumer to lane construction. Actual scheduler tests explicitly set the flag; saved-browse worker.main test replaces the lane runner. No added backend planner-work path found. No flag fix is justified.
- **CI variable:** no backend application/test branch found. Prior helper inherited its environment, so CI=false was not proven. Browser configuration branches onCI, but browser did not overlap the backend workload.
- **Quota/OOM:** passing diagnostic recorded945.16cgroupCPU-seconds/~335seconds,0.597sadditional throttled_usec and no OOM/memory events; sampled memory.current max~10.92GiB includes cache. These counters cover the environment and do not establish failed-run conditions or exclude brief CPU pressure.
- **Database locks/waits:** sparse five-second samples mostly had no wait event; isolated lock/WAL/vacuum samples are not duration attribution. Short events, including one-second failures, can be missed. No sustained lock defect demonstrated.
- **Checkpoint/storage:** six completed checkpoints in the passing diagnostic added157.869scheckpointer write_time and76.727ssync_time. Heavy checkpoints also occurred in both prior pass/failure logs. Background counters cannot be summed into foreground pytest blocked time. Storage remains unproven as a cause.
- **Observer overhead:** direct worker serialization/write sums~0.526s and monitor query sum~0.310s are not wall-clock corrections. Hook/scheduling/cache/race effects are unquantified; no paired control exists. The observer pass cannot prove instrumentation had zero effect or explain the faster result.

## Recommended bounded CI observability, no change performed

For a separately authorized future diagnostic, preserve all selected tests, four workers, assertions, durability settings and480second cap. Useful bounded artifacts are built-in `--durations=30` plus JUnit outcome/duration output, and per-worker start/setup/call/teardown/finish records containing monotonic time and nodeid. Retain partial artifacts on timeout. If exact command equivalence is required, keep the original command as its own receipt and label any added observer/duration flags as diagnostics.

To investigate imbalance rather than guess, also capture controller-side assignment/queued-case counts and worker shutdown times at bounded intervals; per-case completions alone cannot prove queue causation. For representative expensive fixtures, phase-boundary SQL counts and separate schema-create/trigger-install/seed/rebuild/call/drop timing would distinguish setup cost from application work. Parent's existing isolated fixtures suffice; no stress tests or additional infrastructure are implied. Sparse resource/checkpoint samples should remain timestamped with explicit overhead/scope limits.

Do not change scheduler mode/chunk size, raise timeouts, relax PostgreSQL fsync/synchronous_commit, cache mutable evidence across tests or edit freshness/qualification gates without a separately reproduced issue and parity evidence. The actionable issue from this lane is validation observability/efficiency, not a newly validated production defect.

## Evidence and status

Primary evidence: `/workspace/pr160-runtime-full-20261031/{REPORT.md,metadata.json,result.json,analysis.json,events-gw0.jsonl,events-gw1.jsonl,events-gw2.jsonl,events-gw3.jsonl,events-controller.jsonl,observations.jsonl,pytest.log,runtime_observer.py}`. Comparisons: `/workspace/pr160-runtime-diagnostics-20261031/`, `/workspace/local-ci-pr160-20261031-1644/`, `/workspace/phase1-evidence/backend/`, `/workspace/pr160-release-readiness-20261031/CI-RESULT.md` and source-identity.json.

No denied, pending or uncertain actions in this lane. Remaining uncertain fact: the cause and repeatability of the original480second exact-command local timeout. Audit report completed; no rerun or source modification performed.
