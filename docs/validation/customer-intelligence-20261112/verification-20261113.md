# November 13 verification receipt

The first application freeze was `605d6bcc`; the full-suite failure and accepted repair at `380b0dec` are recorded below. Subsequent evidence commits add reproduction scripts, measurements and documentation. This is a draft acceptance record, not production verification.

## Coordinator checks

Commands ran in `/workspace/gl3-commercial`, unless a directory is specified. The private test environment was sourced without printing its values. The local helper rejects non-loopback targets and uses separate disposable databases ending `_test`.

```sh
# backend/
.venv/bin/ruff check src tests
.venv/bin/ruff format --check src tests
.venv/bin/mypy src

# repository root, after sourcing the private disposable-test environment
backend/.venv/bin/python /workspace/task-runtime/run_mission_checks.py \
  .venv/bin/python /workspace/task-runtime/run_touched_backend.py
backend/.venv/bin/python /workspace/task-runtime/run_mission_checks.py \
  .venv/bin/python -m pytest tests/unit/test_retained_publication_date_boundary.py -q
uv run --project backend python scripts/check_docs.py
backend/.venv/bin/python -m py_compile scripts/evaluate_customer_commercial_runtime.py \
  scripts/evaluate_customer_commercial_scope_replay.py
git diff --check
```

Results: Ruff passed, 629 files already formatted; mypy passed across 276 source files; 210 touched tests passed in 46.63 seconds and the 8 new publication-date tests passed in 0.72 seconds. Documentation passed with 119 documents, 555 local targets and 18 anchors. Compilation and whitespace checks passed. The touched-test runner checks that no pre-existing tests were modified after main integration `dc6dac3b`. An initial direct invocation of the 8 date tests lacked required settings and produced setup errors; the configured invocation above passed without changing tests.

The current UI also passed `npm run typecheck`, `npm run build`, and `npx playwright test --project=regression --workers=2 --retries=0 --reporter=line` from `web/` (339 passed, 5.2 minutes). `npm audit --prefix web --audit-level=high` passed from the repository root. Brand validation via `backend/.venv/bin/python tools/brand/validate.py` passed. The earlier contended browser run was interrupted and remains a failed/incomplete attempt, not a passing receipt. These generic browser checks do not replace real-backend journeys.

## Remote verification and publication

`git fetch origin refs/heads/feat/customer-commercial-acceptance:refs/remotes/origin/feat/customer-commercial-acceptance` showed no remote-only commits. Main remained `5ee2f30c`. The required attempt to fetch `perf/account-groups-query` failed because that remote branch no longer exists after PR197 merged. No rebase, force push, merge, approval or deployment was performed.

`git push origin HEAD:refs/heads/feat/customer-commercial-acceptance` advanced draft PR199 from `978b2d43` to `605d6bcc`. Its PR description was updated through `gh api --method PATCH ... --input` after `gh pr edit --body-file` failed on GitHub's deprecated Projects Classic GraphQL field.

The final evidence pre-push touched-test run passed **218 tests in 63.59 seconds** (the 8 date tests are now committed and included in the touched-module selection). Ruff and formatting passed again.

Current-source CI runs are [43396794478](https://github.com/nrsandoval1231-oss/gl3/actions/runs/43396794478) and [43396785582](https://github.com/nrsandoval1231-oss/gl3/actions/runs/43396785582). Their final statuses must be checked before any acceptance claim. Older green runs do not verify this candidate. The [delivery record](final-delivery-20261113.md) lists commercial and performance blockers independently of CI.

The browser job `131789619793` in run43396794478 passed at application source `605d6bcc`: 339 browser/authentication regressions (2.9 minutes), 32 disposable-seeder safety tests (0.44 seconds), all 3 real rollup viewports (37.2 seconds), the persisted Pursuits journey (54.2 seconds), and the Phase2 source-backed brief journey (8.3 seconds). Logs were retrieved through `github_fetch_workflow_job_logs` after direct `gh` log retrieval was unavailable. Backend CI was still running at this observation.

Fresh local verification also passed all 3 rollup viewports and the Pursuits journey. The [real-browser receipt](real-browser-20261113.md) retains exact commands, fixture names, earlier harness failures, and the distinction between local and CI checks. Final pre-push mypy again passed all 276 modules; documentation links passed with 121 documents and 561 local targets before this additional receipt was linked.

## Full-suite failure at 605d6bcc

Run43396794478 backend job131789619905 finished with **1 failed, 5,760 passed, 1 skipped in 568.01 seconds**. The unchanged `tests/integration/test_customer_material_changes.py::test_deadline_to_within_year_is_a_schedule_change_and_replay_is_quiet` expected one `build_timing` event and received none. Running the entire unchanged module locally with the disposable-test helper reproduced **1 failed, 8 passed in 11.87 seconds**. No CI rerun was used to dismiss the failure.

The raw date extractor preserved operational-target deadline versus within-year semantics. The new subject predicate omitted the auxiliary in “is expected to be operational,” so both claims were dropped before material-state comparison. The repair extends that finite predicate grammar; it does not alter change detection, date interpretation, eligibility or the existing assertion. Candidate verification is recorded separately after that repair. The earlier 605d review and browser pass remain bound to their stated source, rather than being relabeled as later-source acceptance.

The parallel push-event run43396785582 independently failed the same unchanged test (5,760 passed, one skipped; 697.01 seconds). Source repair `380b0dec` adds the optional auxiliary only to the existing expected-to-be predicate. Builder verification passed the full unchanged material-change module plus two new tests (11 total); Astra independently accepted 13 bounded qualifier/foreign-site/negation controls. Final standalone `ruff check` and `ruff format --check` from `backend/` also passed (699 files).

Final local gates for repair `380b0dec`: **220 touched tests passed in 56.63 seconds**; the entire unchanged material-change module passed **9 tests in 122.61 seconds**; mypy passed all276 source modules. Ruff check/format and documentation checks passed. These are candidate passes, not a relabeling or rerun of the failed605d CI jobs.

The refreshed [operational-final runtime](../../../eval/customer-commercial-v1/runtime/native-runtime-replay-operational-final-20261113.json) and [oracle replay](../../../eval/customer-commercial-v1/runtime/source-text-scope-replay-operational-final-20261113.json) are bound to the repaired source hashes. Native coverage remains two of20 organizations and zero default-shortlist groups; oracle capacity is2TP/0FP/30FN and timeline0TP/0FP/30FN. Prior captures remain unchanged.

## Canonical default and timer checkpoint

The owner approved the default-policy test changes in `2467dafb`. Coordinator verification passed 259 backend cases (83.71 seconds), Ruff/format across 700 files, mypy across 276 modules, frontend typecheck/build, and 34 focused default/account/Companies browser cases. The native before/after capture is linked in the delivery record.

At `f9d9d96f`, CI runs 43443710027 and 43443700247 passed backend and web/brand checks. Browser jobs 131947677606 and 131947706249 were cancelled at the twenty-minute limit after legacy flat-browse navigation failures. The raw expiry timer overflowed for the unchanged year-2099 fixture; `916ab6c5` clamps the delay and rechecks expiration. The previously failing history case and all 27 workspace/boundary cases passed after that change.

The next full local command was `npx playwright test --project=regression --workers=2 --retries=0 --reporter=line`: 339 passed, two failed. Authentication failed because the launch omitted `GRIDLENS_TEST_PASSWORD`; sourcing `/workspace/task-runtime/security-env.sh` and rerunning `TRUSTED_ORIGINS=http://127.0.0.1:5173 COOKIE_SECURE=false npx playwright test tests/auth.spec.ts --project=regression --workers=1 --retries=0` passed. A separate accidental live-acceptance first-path invocation failed against an unseeded disposable database and is not a product pass. No data was added to hide that failure.

The other failure is `project_results.spec.ts:1288`: its two-second contact lease expires during navigation/setup before its initial assertion. The trace shows the first group/account responses after more than 3.5 seconds. A private candidate using the adjacent test's pause-before-response pattern passes without changing the lease, manual expiry advance or assertions. The owner approved this bounded clock correction; its application and full rerun are pending at this checkpoint. Historical screenshot files overwritten by the regression suite were archived privately and restored to their exact committed bytes.

### Approved clock correction and isolated test environment

The owner approved the existing lease test's deterministic clock correction. Astra accepted test SHA `eb09b47bcaf6c8f88c03d903e24f99d245353ece1808fdba83b58d479973b179`: install at 11:59, pause at 12:00 before the first group response. The two-second contact lease, `fastForward(2100)` and every assertion remain unchanged. The targeted lease test passed (15.4 seconds).

The first correctly authenticated full command was `source /workspace/task-runtime/security-env.sh; TRUSTED_ORIGINS=http://127.0.0.1:5173 COOKIE_SECURE=false npx playwright test --project=regression --workers=2 --retries=0` from `web/`. It was interrupted after 8.5 minutes: 104 passed, seven failed, two interrupted, 228 not run. Concurrent isolated-worktree mypy jobs and a backend test lane competed with the browser run. The first two inspected traces consumed their timeout creating a page or waiting for navigation load, before assertions; both exact Research cases then passed isolated (two passed, 10.3 seconds). This attempt remains failed/incomplete. Cgroup counters reported no OOM or OOM kill; no OOM explanation is claimed.

The coordinator stopped competing checks before a fresh full run. Root, source-coverage and performance mypy runs were terminated, so none is counted as passing. The relevance lane's wrong-environment mypy reported missing openpyxl stubs and was terminated; its focused pytest invocation was interrupted after 13 passes (exit130), also not a suite pass. All require sequential configured reruns.

The screenshot restoration harness initially extracted a web-relative image archive at the repository root. That copied tree was moved to private diagnostics; committed screenshots were restored to exact HEAD bytes and a root-relative archive was created. No generated copy was added to the repository.

The quiet full rerun passed **341 tests in 5.3 minutes**, with retries disabled and two workers. Its exact shell command was the configured full regression command above, piped through `tee /workspace/task-runtime/customer-project-results-full-regression-20261113-quiet.log` with `pipefail` enabled. This includes authentication, the corrected lease boundary and the earlier setup/navigation cases. Original failed trace ZIPs were inspected but not archived before Playwright cleared/replaced its results; they are not retained artifacts. The failed/incomplete attempt is not relabeled as passing.

All tracked screenshot bytes were restored after the run; the root-relative before/after archive SHA-256 was identical (`e9ef3f0309e03856c6bccda80a923fb48cc3649af36d306ba7dfb8e7b4198f32`). No screenshot assertion or application assertion was removed.

Final main-candidate pre-push standalone checks from `backend/`: `.venv/bin/ruff check .` passed; `.venv/bin/ruff format --check .` passed (700 files); `.venv/bin/mypy src` passed (276 source files). Documentation graph passed (122 documents, 567 local targets, 18 anchors). The full browser pass above covers all touched timer/default/lease tests. The 259-case backend contract run and both prior-head full backend CI passes remain separately scoped; the follow-up timer/fixture/documentation commits change no backend source.
