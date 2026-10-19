# C7b adversarial durability verification

READY after structured_collection.py and process_job segment interface exist.
Base84336c8 plus the C7b working-tree implementation. One Luna owns only new
`backend/tests/integration/test_structured_collection_adversarial.py` and its
ignored completion artifacts. No product/schema or existing test-file edits.
Source builder owns adapters/service/worker and legacy fixture repairs. Coordinate
interface changes; preserve other work. Exclusive operations_test/app loopback55487
databases. Real PostgreSQL, mock source transport, external network guard active.

Prove actual process_job boundaries: crash after durable evidence but before cursor,
restart/repeat without duplicate evidence; crash after progress before terminal job
and safe continuation; duplicate delivery/concurrent stale fence cannot advance
cursor; source/context change during fetch rejects progress; changing counts or
malformed/unexpected empty content cannot mark complete or lose last-good facts.
Preserve strict bounds, original timestamps and UNKNOWN/partial outcomes. Exercise
the new service path, not a reimplementation of its algorithm. Use explicitly due
fixtures for immediate leasing except tests specifically exercising scheduling.

Report implementation defects with reproducible evidence to root/source builder;
do not mask bugs or edit product code. At most two materially distinct test-setup
repairs; no repeated unchanged reruns. Run new real-PG module, Ruff and diff check.
Handoff exact commands/results/files/UTC, unknown timing/token fields honestly.
No network/provider/spend/production/commit/push/deploy or new subagents.
