# RV1 — direct project-state regional fence

READY review repair. Repository gl3-regional-20261022, branch feat/regional-stabilization-20261022, base/candidate a05a3cb9f3f46383d3799bfd1c11140aaeade8ab. Fresh independent Sol verdict FIX: `/api/projects/{id}/state` returns current activity/power-need fields for retained excluded projects, unlike sibling guarded active routes. Root reproduced HTTP200 for an actual excluded project with a retained active need. Preserve this rejected candidate and review evidence.

Owner: one Luna. Allowed source: backend/src/gridlens/api/app.py only project_state_endpoint; tests backend/tests/integration/test_regional_eligibility.py (or a new narrowly named project-state regional test if needed). No other source, schema, migration, registry, UI, fixture infrastructure or docs edits. You are not alone; do not revert other work.

Implement current regional ELIGIBLE gate before expensive current-state hydration, consistent with sibling direct active routes, returning404 for EXCLUDED and HOLD. Preserve historical ingestion/evidence and buying-chain/history routes. Do not deactivate/delete old needs or evidence. No new framework/region algorithm changes.

Regression must create retained excluded CA/GA and HOLD/unknown/conflicting projects with active needs, prove direct current-state404, and prove TX/OK/NM route success. Keep original evidence and project/need state unchanged and an intended historical-evidence route accessible. Prefer existing isolated-schema fixtures; do not change existing regional gates/assertions. Test exact case first failing old code then passing repaired code.

Validation: use private range-test.env only (`uv run --directory backend --env-file ../.artifacts/regional/range-test.env python -m pytest ... -q`), Ruff check/format, scoped mypy, git diff --check. Root full old-candidate suite uses recovery-test.env; do not touch it, app, perf or recovery databases. No Python multiprocessing through stdin. No commit/push/merge/deploy/paid/network actions. Retry budget2 materially different repairs, checkpoint if scope or fixture semantics exceed allowance.

Output private .artifacts/regional/RV1-COMPLETION.json with exact files/commands/exit codes/results, failing-before/passing-after proof, uncertainties, UTC start/finish and measured/UNKNOWN metrics. Do not grade own acceptance. Root reruns gates, freezes new candidate and re-requests independent exact-head review.
