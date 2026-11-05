# PR160 backend runtime: environment and source-path analysis

Read-only investigation of current clean worktree `/workspace/gl3-phase1`, HEAD `78591b308aa829a25157bf3310133ed069434d3b`. No source edits, database requests, new test runs, providers, production access or competing workload were performed in this lane. Source/log inspection and local artifact writing only.

## Conclusion

The preserved evidence **does not establish a root cause** for the fresh480second timeout. `WORKER_AUTO_REFRESH` is a genuine invocation difference, but source tracing finds **no affected backend-test path that would start additional planner work**. It should not be presented as the explanation. Similarly, CI=true, role name, verbosity, fresh instance and cache differences are observed comparisons or hypotheses, not established causes.

The fresh run remains a failed local gate, not superseded by the earlier pass or the independently reported hosted CI pass. Earlier pytest completed3667passed/1skipped/7subtests in350.31s (wrapper355.946s); fresh GNUtimeout returned124 after480.095s with3668collected and last printed progress94%. Fresh result row says FAIL, not orchestration TIMEOUT: the inner exact480second command expired before the helper's500second cap. No individual failed assertion, final pass count or remaining-node identity can be inferred from truncated output.

## Environment comparison

Sources: `/workspace/phase1-evidence/run-full-backend.py:2-4`, corresponding backend/results.json and pytest.log; `/workspace/local-ci-pr160-20261031-1644/run.py`, metadata.json/results.json and backend/pytest.log.

| Difference | Earlier passing invocation | Fresh local CI invocation | Supported interpretation |
|---|---|---|---|
| Worker refresh | Explicit false | Initial false is removed before backend at run.py:67; settings default true | Real setting difference; no extra test work path found below. |
| CI variable | Inherits process environment; script does not explicitly set false | Explicit true | Prior script alone cannot prove CI=false. No backend app/test branch reading CI found. |
| Pytest entry/reporting | Direct .venv/bin/pytest tests -n4 -v --tb=short | uv run pytest tests -n4 | Same Python3.11.16, pytest9.1.1, xdist3.8.0 and anyio4.15.1 appear in both logs;3668items/fourworkers. UVsync0.032s before fresh run. Verbosity differs; effect on runtime not measured. |
| DB endpoint/role/database stem | audit role, loopback55432, phase1_full_test | gridlens role, loopback5432, gridlens_test | No repository role-name-specific execution branch found. Role privilege equivalence was not queried in this lane. |
| PostgreSQL instance | Existing audit instance, initializedOct30 per preserved startup log | Fresh container/cluster initializedOct31 at16:47:59 | Same18.6image per coordinator; fresh-vs-existing catalog/buffer/OS-cache state remains a possible difference, not proof. |
| Cookie flag | Explicit false | Not explicitly set for backend | Default true absent inherited value; relevant auth test explicitly sets true. Only inspected runtime uses set/delete-cookie security flags. No sustained work/loop branch found. |
| Python path | Explicit current backend/src | Repo pytest pythonpath=src (may also inherit environment) | Both load current project paths; no evidence of stale alternate import. |
| Frontend/tool/cache flags | Mostly inherited | Explicit Node22path, cache dirs, provided CA, UVtool settings | Backend subprocess discovery may see changed PATH/cache state; no affected slow test identified. No browser workload overlaps backend in the fresh sequential helper. |

Both helpers copy inherited environment, so neither script is a complete recorded allowlisted environment. Do not infer equality for every unset feature/configuration flag. No environment dump or credential-value inspection was used. Current worktree has no root/backend .env files (existence checked only); Settings.env_file points to root .env, so no current file override explains the worker default. These observations do not recreate an earlier inherited environment.

## WORKER_AUTO_REFRESH: call-chain proof

Repository search finds one runtime consumer: `backend/src/gridlens/jobs/worker.py:1573`, inside `_worker_lane_specs`, which adds source/pursuit/contact/well planner lanes. Merely importing the module or invoking `run_one` does not use this flag or start these lanes. `_run_worker_lanes` creates/starts them at worker.py:1612-1620; main invokes that method after setup.

Relevant tests exhaustively found by `_worker_lane_specs`, `_run_worker_lanes` and worker.main references:

- `test_worker_planning_liveness.py::test_blocked_acquisition_does_not_block_planners_or_heartbeat` explicitly sets worker_auto_refresh=True at:115, source action is mocked to throw and pursuit action returns0. Its behavior is independent of inherited false/true.
- `test_worker_planning_liveness.py::test_disabled_planner_flags_do_not_create_planner_lanes` explicitly sets false at:177. Again independent of inherited value; joins/stops its controller.
- `test_buying_chain.py::test_rrc_directory_retrieval_policy_queues_once_and_deduplicates` explicitly sets true at:675 and only inspects constructed lane names at:681 before its controlled contact workflow.
- `test_saved_browse.py::test_worker_startup_publishes_flushed_ingestion_before_each_commit` is the only worker.main call found. It replaces `_run_worker_lanes` with a finite synthetic transaction function at:1481 before calling main at:1482. Thus main never calls `_worker_lane_specs` in that test and no extra source planner starts. The finite function is at:1464-1479.

Consequently, the saved-browse startup test does not acquire hidden continuous ingestion/planner work when the default changes to true. Saved browse's `install_worker_publication` callback is governed by saved_browse_enabled and actual transaction dirtiness, not worker_auto_refresh. No other runtime flag consumer or unmocked worker-main launch was found in backend tests. This strongly rejects the proposed hidden-refresh explanation **on repository source evidence**, while not claiming an instrumented execution trace of the timed-out run.

## CI, database reset, output and storage cautions

- No application/backend-test os.getenv/os.environ CI branch found. CI appears in workflow configuration, and browser config can vary workers/retries, but that job starts after backend termination in the fresh helper. Installed third-party tooling could vary presentation under CI; this lane did not assert it cannot have any effect.
- `backend/tests/conftest.py:29-55` drops/recreates four worker databases before each xdist suite. Therefore earlier passing workers were not simply reusing previous test rows. However this does **not** equate PostgreSQL instance caches, global/shared catalogs, disk state or background processes. `db_reset.py` still uses per-test truncation/schema handling within each worker.
- PostgreSQL fresh log records substantial WAL checkpoint work:16:50:28→16:52:50 (142.132s including51.884ssync/277640files),16:52:50→16:54:32 (102.582s),16:54:36→16:57:07 (150.647s). Earlier instance log also contains long checkpoints. Background checkpoint elapsed time is not foreground query blocked time and cannot be added to pytest duration as causal delay. These logs justify examining measured SQL/I/O/catalog behavior, not declaring storage the cause.
- No deadlock/statement-timeout/lock-timeout marker found in preserved fresh PostgreSQL log. At shutdown, active SQL includes broad evidence-size/projection queries, but statements alone do not map uniquely to a test or establish a hang. Parent owns bounded database diagnostics.
- Earlier -v logs identify completed tests but have no per-test durations/timestamps. Fresh progress dots do not identify tail nodes. Dynamic xdist LoadScheduling means94% completion does not identify the last6% by source/collection order. Do not claim saved-browse or shadow tests are definitely the tail based only on those logs.

## Next evidence / disposition

Keep source and exact480second gate unchanged during diagnosis. Bounded targeted measurements can compare actual query/phase timing and plans on representative isolated fixtures under the two recorded DB/setup conditions, with fresh identity/timing receipts, without another competing full run. A future separately authorized full rerun should record per-node durations/timestamps and worker completion state so tail attribution is possible; this is a diagnostic recommendation, not a changed command or run executed here.

No actions denied, pending approval or uncertain in this lane. Report completed at `/workspace/pr160-runtime-diagnostics-20261031/environment-analysis.md`. Runtime cause remains unresolved.

Coordinator supplied additional hosted evidence at handoff: hosted backend checked out PR merge commit9d82c33 (78591b3 into593cfd5), reporting3667passed/1skipped in362.56s, step16:34:19→16:40:23. This is an independently passing hosted environment/tree integration observation, not a substitute for the fresh local timeout or proof of its cause. Coordinator is running bounded saved-browse/shadow diagnostics with per-test durations and PostgreSQL/cgroup samples; this lane has stopped commands and starts no competing work.
