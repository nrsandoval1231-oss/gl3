# C3 — Acquisition transaction boundaries

READY after B3 release; one Luna, disjoint from G2. Repository/branch are the
current intelligence worktree, base057899fab940ba5ff21363173c4d9432010ae0b3 plus
integrated B3. No production/network/provider activation.

Own ingestion/service.py only, new focused acquisition transaction integration
tests and concise architecture note. Do not touch queue, provider, schema, API,
evaluation or snapshot. Use released grounding `_test`/`_app` databases exclusively;
never original corpus or another active builder database. You are not alone;
preserve others' work. Release service.py before D3 capture work starts.

Fix demonstrated non-RSS process_job acquisition holding caller Source locks.
Network acquisition, including existing GovInfo companion retrieval, must run
outside long database transactions. Preserve evidence-first checkpoints, durable
leases/fences, cancellation and source-disable/endpoint-change rechecks. Do not
silently commit pending unrelated writes; reject unsafe dirty/nested sessions or
make explicit existing durable boundaries. Keep process_records(commit=False)
semantics honest: no network in nested/pending transaction; return/raise bounded
unavailable instead of silently committing an owner's transaction. Do not weaken
source acceptance or existing test fixtures solely to pass.

Real PostgreSQL concurrency test: acquisition blocked on a test Event while a
second connection updates Source using finite lock_timeout; update must succeed.
Cover RSS/non-RSS, source disabled/endpoint changed and stale/cancelled lease during
retrieval, last-good evidence unchanged on retrieval failure. Existing companion
evidence must remain durable and cannot be written by a stale worker. Run focused
ingestion/lease/RSS/PDF tests, lint and mypy; two materially distinct repairs then
canonical reconstruction. Report exact commands/results/files/UTC timing in C3
completion artifact. No merge/push/deploy; controller final gates and independent
review remain mandatory.
