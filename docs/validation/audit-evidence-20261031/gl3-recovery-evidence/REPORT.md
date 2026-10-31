# Recovery tooling/docs implementation and validation

Published draft [PR161](https://github.com/nrsandoval1231-oss/gl3/pull/161), commit `49fe43805a2d31a2253521946dcbd2f08e901ced`, branch `fix/recovery-tooling-local-20261031`, base main `00026c758ece2bc41eea88c478cbb0112f9e0de5`.

Validated and published complete tree: `2ec4e47c9628501ca68b326f5c345bdd0fac08e6`. All 11 changed/new files match the independent reviewer’s exact fingerprints; combined manifest SHA-256 `aacd9f01bfd5cfa9d6fe2e58456b8d46bb318155ebc86e82e71310199aae824f`. GitHub tree creation matched local write-tree; fetched remote commit/tree and PR head were independently checked. Local feature checkout is clean. No source changes followed validation/review.

## Changes

- Protected selective wrapper now allowlists `browse-status`, `stage-browse`, `inspect-browse UUID`, and `publish-browse UUID`, mapping to the existing backend CLI. Removed rollback operation is rejected. Canonical UUID, exact input bytes/AST/command identity, protected prefix, private output mode, no-overwrite and arbitrary-command rejection remain intact.
- Legacy 0041 rehearsal requires explicit `--historical-0041-only` at CLI and programmatic entry before resource access. Its original schema/isolation/evidence checks remain unchanged. It cannot certify current image pairs/schema; no generic schema acceptance was introduced.
- New current recovery guide and five maintained guide updates explain endpoint-specific generation requirements, stale receipt/CAS handling, actual runtime policy, prior-image/current-data recovery, preserved forward schema/suppression/evidence/provider accounting, and production hold. Dated historical receipts were retained.
- Regression tests cover generated operations through the real CLI parser/dispatcher, rejection of obsolete/arbitrary/noncanonical arguments, historical entry guards, actual PostgreSQL stage/inspect/stale-publish refusal/fresh publication, and project/company generation requirements with the switch disabled.

No application evaluator, schema, ingestion, UI, dependency or runtime optimization changes.

## Actual validation

- Locked dev dependencies installed in a separate local worktree virtual environment, Python 3.11.16; no shared environment replacement.
- Wrapper RED: 6 failed / 17 passed against old generator; GREEN: 23 passed. Logs `wrapper-red.log`, `wrapper-green.log`.
- Historical guard RED: 7 failed; GREEN with existing rehearsal tests: 15 passed. Logs `legacy/red.log`, `legacy/green.log`.
- Focused disposable PostgreSQL validation: `timeout 180 uv run pytest tests/unit/test_stage_release_wrapper.py tests/unit/test_rehearse_release_legacy.py tests/unit/test_release_rehearsal.py tests/integration/test_browse_recovery.py -n 4 -q --tb=short`: **70 passed in 15.78s**, exit0, wrapper19.3796s. See `focused.json/log`.
- Full backend: `timeout 480 uv run pytest tests -n 4`: **3,686 passed, one skipped, 11 warnings in 337.44s**, exit0, process338.936s. See `full.json/log`. One full run, unchanged four-worker/480-second gate, no competing validation workload. Summary-only CI output does not identify the skipped test or its reason; no invented skip explanation.
- Ruff check for all src/tests and changed scripts: PASS (`lint.log`). Format check: **428 files already formatted** (`format.log`). Mypy: **no issues in 190 source files**, with existing untyped-body notes (`mypy.log`). Documentation graph: **93 documents, 372 local targets, three anchors**, PASS (`docs.log`). Diff whitespace check passed.
- Initial lint invocation from repository root with explicit backend config reported three import-order issues, including unchanged code, because project-root import classification differed. Correct CI backend cwd passed without changing those imports. This invocation failure was not hidden or treated as an application defect.
- Independent Astra review: no concrete blocker; `independent-review.md` records reviewed files, exact hashes and scope/verification limits. Full test run completed afterward on identical bytes.

The earlier exact-command local **480.095s timeout remains an unexplained failed historical receipt**, alongside earlier successful runs. This patch does not diagnose or fix that variability. Its new full pass does not erase the failure. No tests/assertions/deadlines/data-volume or durability settings were weakened.

No fresh frontend/browser, dependency audit, migration/restore, protected-wrapper installation or actual image-pair rollback rehearsal is claimed. Frontend, dependency manifests, migrations and backend production source are unchanged. Local recovery checks used synthetic fixtures in the existing disposable PostgreSQL18.6 container and isolated worker databases; the container is stopped after validation.

## Publication and remaining gates

Publication was initially excluded following an authorization rejection. The owner subsequently explicitly approved committing/pushing this scope and opening a draft PR. Only then were the reviewed commit/branch and draft created. No rejection was bypassed. `publication.json` records draft=true, merged=false, auto_merge=null, expected head/base, tree and clean local status.

Automatic PR [CI41230339349](https://github.com/nrsandoval1231-oss/gl3/actions/runs/41230339349) was in progress at handoff. No manual Actions run was dispatched. Do not confuse local validation with terminal hosted CI.

Production remains untouched and deployment explicitly held. Actual protected host tooling, selected images/schema/policies, fresh backup/isolated restore, prior-image/current-data recovery and authenticated live acceptance remain production-only gates. The updated companion is not installed or verified on the host. A synthetic PostgreSQL test is not production rollback readiness.

Artifacts: this report; `recovery.patch` (complete base-to-head diff including new files); `candidate-manifest.json`; `validated-tree.txt`; validation logs/JSON; independent review; `publication.json`.

No merge, PR approval, auto-merge, deployment, production operations, generation/data/config changes, ingestion/backfill, paid calls, production credential creation or PC access. No unresolved denied action or uncertain mutation. Pending: hosted PR CI and future separately authorized release gates.
