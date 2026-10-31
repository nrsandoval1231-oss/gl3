# PR160 backend runtime investigation — 2026-10-31

## Outcome

No confirmed source defect explains the inconsistent full-suite runtime. No source, test, workflow, assertion, timeout or PR changes were made. Draft PR160 remains at `78591b308aa829a25157bf3310133ed069434d3b`, tree `125b7dc0ee61a890b1dffff40f3b2891df3be9c1`; worktree clean. The fresh local CI backend gate **remains FAIL**, with the cause unresolved. Hosted CI success is separate evidence, not a replacement for that failure. No further full-suite rerun was performed: the bounded diagnostics did not establish a causal change or controlled full-run hypothesis.

PR: https://github.com/nrsandoval1231-oss/gl3/pull/160

## Preserved full-run evidence

| Run | Actual result | Limits |
|---|---|---|
| Earlier local exact candidate | 3667 passed, 1 skipped, 7 subtests in350.31s; command355.946s | Same local Python3.11.16; verbose reporting; explicit WORKER_AUTO_REFRESH=false; pre-existing separate PostgreSQL instance. |
| Hosted CI41220159391, backend job124592885866 | 3667 passed, 1 skipped, 11 warnings in362.56s; teststep16:34:19.205→16:40:23.021UTC | Ubuntu24.04, Python3.11.18; GitHub PR merge9d82c33, explicitly merging78591b3 into593cfd5. Hosted integration result, not a local or identical-host run. |
| Fresh local CI | GNUtimeout exit124 after480.095s, 3668 collected, last printed progress94% | No final summary or per-node durations. No individual assertion failure proved. Tail test identity cannot be recovered from progress dots with dynamic xdist scheduling. Python3.11.16/Debian13. |

Original receipts: `/workspace/phase1-evidence/backend/`; fresh CI receipts `/workspace/local-ci-pr160-20261031-1644/REPORT.md`, `results.json`, `backend/pytest.log`. Retrieved hosted logs saved here as `hosted-backend.log`. Hosted uses a newer Python patch version than local; neither that nor OS difference is demonstrated as causal.

## Bounded diagnostic performed

Command, in `/workspace/gl3-phase1/backend`:

```
timeout 180 .venv/bin/pytest tests/integration/test_saved_browse.py tests/integration/test_evidence_shadow_storage.py -n 4 --durations=30 --junitxml=/workspace/pr160-runtime-diagnostics-20261031/targeted-junit.xml
```

Result: **142 passed, 5 warnings in72.43s**, exit0. Process measurement73.643s; container lifecycle-inclusive wrapper78.358s. Existing disposable PostgreSQL18.6 container only; four freshly recreated worker databases; application DB and *_test DB distinct. CI=true, default WORKER_AUTO_REFRESH, blank provider keys, test network guards and original assertions preserved. External harness generated disposable session/auth values. No production access or concurrent test workload.

Measured slow calls:

- `test_saved_browse.py:1819::test_structured_ingestion_bulk_commit_keeps_authenticated_maps_current`:34.92s.
- `test_evidence_shadow_storage.py:377::test_shadow_rotates_through_more_than_two_hundred_candidates`:20.58s.
- `test_evidence_shadow_storage.py:412::test_shadow_wrap_scans_past_consumed_prefix_to_find_unseen_candidate`:12.81s.
- Original one-second lock test `test_evidence_shadow_storage.py:231::test_shadow_skips_reservation_when_daily_lock_is_held`:passed unchanged; JUnit total0.265s including fixture phases. Its isolated pass does not resolve the historical full-suite timeout of that assertion.

These are measured slow tests in this subset, **not proven tail tests of the failed full run**. Parallel call times overlap and must not be added as wall time. This subset is not a full-suite green receipt.

### Database / resource observations

External monitor sampled grouped pg_stat_activity every1second;83 active-backend samples:75 no wait event,4 IO/WalSync,1 LWLock/LockManager,3 Client/ClientRead. This is sampling, not a query-time breakdown; sub-second contention can be missed. It provides no evidence of sustained lock contention in this successful subset.

Four completed requested checkpoints during the subset: checkpointer write_time delta23ms, sync_time delta272ms, buffers_written2857. Settings recorded: fsync/on, synchronous_commit/on, full_page_writes/on, shared_buffers128MiB, max_wal_size1GiB, checkpoint_timeout300s, completion_target0.9. No durability settings changed.

Cgroup has4CPU quota and16GiB memory limit. During successful subset: CPU usage230.516CPU-seconds;15 additional throttled periods and0.05538s additional throttled_usec; no memory/OOM events. Snapshot counters cover the environment cgroup, not exclusive per-process attribution. Pressure files unavailable. No failed-run contemporaneous resource samples exist, so these later samples cannot explain that run retrospectively.

Failed-run PostgreSQL logs contain checkpoints142.132s (sync51.884s/277640files),102.582s and150.647s. Earlier passing-instance logs also contain heavy checkpoints, including136.403s (sync63.736s/306532files). Background checkpoint elapsed time is not foreground blocked time and cannot be added to pytest duration. Thus I/O variance remains a hypothesis, not a proven host limitation or source bug. No deadlock/statement-timeout/lock-timeout marker found in the preserved failed log. Shutdown termination messages are intentional container shutdown, not independently occurring application faults.

Both local instances used image sha256:a1be1c8380f5c8ca80b4ad72f6be191f8a283e0ecb2e9496b1ee67dc0022d0f1 with no Docker CPU/memory cap. Distinct persistent volumes and pre-existing/fresh cluster state prevent an exact storage/cache comparison.

### Independent source-path review

`environment-analysis.md` records an independent read-only review. WORKER_AUTO_REFRESH=false versus defaulttrue is real, but its only runtime consumer builds continuous worker lanes. Tests invoking those paths explicitly override the flag or replace the lane runner. No hidden planner workload caused by the flag was found. No backend CI-variable branch found. Prior CI=false is not established because the earlier helper inherited environment. Role/port/name, reporting verbosity and cache differences remain unproven hypotheses. Do not attribute the timeout to any of them.

## Harness errors preserved

Two preliminary external diagnostic attempts are retained and excluded from success claims:

1. `setup-error-targeted.*`: missing required auth/session settings caused collection errors; no tests ran.
2. `interrupted-harness-targeted.*`: operator interrupted after noticing application/test URL equality in the diagnostic helper, before using its results.77tests completed before interruption; pytest exit3/internal shutdown error. This is an invalid/interrupted diagnostic, not a product regression or validation receipt. The external helper was corrected to distinct databases; repository files were unchanged.

Final corrected helper is `targeted.py`; final actual command/configuration/resources/results are `targeted.json`, `targeted.log`, `targeted-junit.xml`. PostgreSQL logs captured before diagnostic restarts are `failed-postgres.log` and `prior-postgres.log`.

## Disposition and remaining gate

No change is justified merely to make this host pass. Leave PR160 unchanged, preserve the480second gate and all tests. The local full-suite runtime gate remains failed and exact root cause uncertain. A future diagnostic full run, if warranted, should capture per-node completion/durations and contemporaneous CPU/I/O/database waits from the start while retaining the480second limit. That would be an investigation run, not a substitute for the exact CI command. There is currently no evidence-backed code fix to independently review or publish.

All commands completed; disposable database container stopped. No hung command, production request/write, paid call, GitHub Actions dispatch, PR approval, merge, deployment, new infrastructure or PC access occurred. No action was denied or awaits approval in this investigation. The unresolved item is technical uncertainty, not an authorization blocker.
