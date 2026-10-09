# GL3-AUDIT-A2-CI-R1 — combined lifecycle integration repair

Base: `990994f3a161a7fc3720f4f8330e5446d09eef20` on `repair/gl3-lifecycle-delivery-20261007`.

## Objective

Repair the two substantive failures and twelve setup errors in `.artifacts/controller-full-tests.log` without weakening current-version, facility-scope, stage, commercial-tier, or retained-history rules.

## Owned paths

- `backend/tests/integration/test_lifecycle_scope_integration.py`: make its database guard accept a distinct disposable `*_test` database (including CI `gridlens_test`) while rejecting the configured application database.
- If required by reproduced evidence: `backend/src/gridlens/intelligence/lifecycle_service.py`, `backend/src/gridlens/domain/lifecycle.py`, `backend/src/gridlens/intelligence/project_state.py`, `backend/src/gridlens/ingestion/service.py`, and the directly affected regression tests.
- Narrow follow-up extension from controller: `scripts/replay_lifecycle_history.py` and `backend/tests/unit/test_replay_lifecycle_history_cli.py` may be changed to require a distinct disposable `*_test` database and the repository's actual Alembic head, with no auto-migration and cwd-independent migration lookup. The controller will run replay/idempotency on its own clone of the retained copy; this worker must not access or mutate either retained corpus database.
- Compatibility/safety: preserve the existing `--use-application-database` selector. This task must not invoke it. The default and explicit `--database-url` paths require a distinct disposable `*_test` database and current repository Alembic head, with no auto-migration. A future owner-run procedure must review and authorize application replay before an operator selects that flag.
- Controller-authorized inventory-reader extension: `scripts/reconcile_lifecycle_inventory.py` may be updated so its retained-event inventory applies the same current semantic/source hashes and event/interpretation/evidence foreign-key binding as the lifecycle service.
- This packet and its `.agent/artifacts/GL3-AUDIT-A2-CI-R1/` raw logs and completion receipt.

## Acceptance

1. Integration setup is guarded by both a disposable-test database identity (`*_test`) and explicit inequality from the application database; no live/application database is touched.
2. Reproduce and fix the data-center-to-warehouse canonical-source reevaluation regression (`RESEARCH` should become `WATCH`) with evidence-bound current project/need state; preserve the inverse warehouse-to-data-center transition and tier invariance.
3. Reproduce and fix the same-ID supported Taylor withdrawal material-state regression so the current withdrawal is supported and replay stays quiet, while preserving the retained withdrawn evidence and prior history.
4. Run targeted red/green tests, full affected tests, Ruff, mypy, and diff check on the frozen candidate. Preserve the controller's initial full-suite failure log and all repair attempts.

## Application replay owner procedure

The application selector remains available for compatibility, but no application URL was selected during this packet. Before any future operator uses `--use-application-database`, the owner must review the exact candidate, retained-event inventory, rollback/backup readiness, and expected write set, then authorize that run. The CLI still requires the database to be at the repository Alembic head and never runs migrations. This task's replay/idempotency evidence uses only the controller's isolated clone.

## Constraints

Use only the dedicated disposable `gl3audit_lifecycle_delivery_test` and `gl3audit_lifecycle_delivery_migration` databases on local PostgreSQL port `55437`. Keep provider keys blank for these tests. Do not access or mutate the corpus copy/original backup, other workers' databases, source-provider state, or production. No push, merge, deployment, or scope expansion. If the two substantive failures need a cross-boundary architecture or schema change, stop and report evidence before broadening ownership.

## Handoff

Commit implementation and a receipt containing the exact candidate SHA, commands/exit codes, raw log locations, remaining uncertainty, and explicit note that controller reruns/independent review are still pending. Do not claim A2 acceptance.
