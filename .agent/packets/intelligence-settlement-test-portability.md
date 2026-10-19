# B4-H — Canonical test harness reconstruction

Controller rerun from backend (the mandatory scripts/check.ps1 working directory)
on the released operations test/app DBs:19 pass/3 fail. Failure evidence in ignored
B4-controller.log: runpy paths backend/scripts/... become backend/backend/scripts;
trigger test hardcodes builder application DB name and refuses other environments.
Builder's repository-root22-test PASS is retained, not a portable/full-suite pass.
Prior local builder repairs did not reconstruct the actual final-gate contract.

Luna G2 receives this bounded test-only sidecar after B4 release; B3 owns none of
these files. Read scripts/check.ps1 and existing isolated test/migration fixtures
first. Own only tests/integration/test_logical_calls.py and test_snapshot_presence.py
for these three regressions; preserve B4 behavioral assertions and G1 snapshot tests.
No ledger/model/migration/product changes. Resolve script paths from __file__, not
process cwd; prove both supported root and backend invocation.

Actual0028 append-only trigger proof must use the exclusive disposable TEST DB,
never settings.database_url or a hardcoded owner DB. Exercise the real migration,
not a copied trigger string; an isolated temporary schema or established safe
migration fixture is acceptable. Guard test DB ends_test and differs from app.
Keep failing UPDATE/DELETE attempts in recoverable savepoints and verify retained
rows. Restore isolation/cleanup; no production or source corpus mutation.

Run exact controller22 tests from backend and the three affected tests from repo
root using the same dedicated evaluation test DB (only your lane). Record both
results and scoped Ruff. If failure indicates actual product behavior rather than
harness path/isolation, stop scope expansion and report controller evidence.
No claim these replace full final gates. Completion appended separately as B4-H.
