# AUDIT-PUBLICATION-FIXTURE-PORT

Objective: remove the test fixture's machine-specific PostgreSQL port assertion while preserving its loopback host, `_test` suffix, no-`corpus`, and app/test database separation guards.

Repository/worktree: GridLens gl3, `gl3-audit-publication-fixture-20261020`; branch `repair/audit-publication-fixture-20261020`; base `7c57f7d118b7e910886cbc0f327858af7906b9d3`.

Allowed source file: `backend/tests/integration/test_fact_draft_publication.py` only. Exclude production code, migrations, SQL policy, budgets, CI settings, shared DBs, external effects. Create fresh private app/test databases only after absence and loopback checks. Run five focused tests on loopback port 55520. Actual CI port 5432 proof is controller-owned.

Acceptance: remove only the literal port assertion; retain all other guards. Run Ruff format/check and the focused module. Return source commit and a separate completion artifact. No push, merge, or deploy.

Source commit: `3c3494d989d1cded69b7ce1f622a0471ccdf6307`.
