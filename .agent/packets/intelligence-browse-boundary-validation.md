# BROWSE-BOUNDARY-R1

Objective: repair test-only midnight maintenance assumption and prove parity in the preparation window.
Repository: gl3-intelligence-20261018; branch feat/intelligence-integration-20261018; base cd8d9433b79728dd0a7253e7b85513a38df5040e.
READY dependency: accepted local cd8d, subsequent external-controller report of prepared versus published at UTC23:58. External full-suite proof remains pending.
Luna owns only backend/tests/integration/test_call_fact_workflow_integration.py and test_saved_browse.py if necessary. Root owns documentation. No application, migrations, generated files or external state changes.
Preserve every canonical-versus-saved parity assertion. After maintenance, require current_generation in a fresh session instead of equating success with one return status. Add deterministic real PostgreSQL near-boundary coverage reaching prepared/ready; no wall-clock luck or relaxed qualification assertion.
Use settlement isolated test/app databases on 127.0.0.1:55487, external test guard, blank provider keys and all providers OFF/zero. Validate focused workflow and saved-browse modules, scoped Ruff and diff check. No commit/push/deploy/spend. Two distinct repair attempts maximum before evidence-based escalation.
Handoff: exact diff, commands/exit codes, UTC timing, raw logs, remaining uncertainties. Independent review and frozen final checks remain controller responsibilities.

Sol diagnostic 2026-10-19: CORRECT. Preserve original prepared-clock test unchanged. Add separate deterministic dirty-to-503-to-maintenance regression. Freeze saved_browse clock at old boundary minus30seconds; mutate active state, assert pending503. maintain_once returns prepared; fresh current_generation identifies refreshed current (valid_from=near clock), while BrowseState.prepared_generation_id identifies DISTINCT future interval at boundary. Second maintain returns ready. Compare saved/canonical at near time and boundary using evaluate_at and reader clock. No clock move to boundary before first maintain. This revised packet follows failed ID-conflation attempts; retain raw failures, one bounded implementation attempt then escalate if unresolved.
