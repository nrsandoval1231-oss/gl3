# M4 atomic publication repair

Node M4-PUBLICATION-REPAIR; one Luna. Repository gl3-production-20261023, branch feat/production-intelligence-20261023, rejected base48ee7dc8a2ac7b9a939b2a50f7d0bde76dda0bc3. Read .agent/artifacts/PRODUCTION-M4-PUBLICATION-RECOVERY.md and .agent/artifacts/PRODUCTION-M4-REVIEW/REVIEW-r1-static.json. Sol approved this concrete concurrency boundary. Opening Tribunal already completed; no new Tribunal. You are not alone: preserve all controller/reviewer artifacts and other work.

## Objective

Publish one M4 LogicalCall result and its Job checkpoint atomically from one coherent final input snapshot. The first repair could commit a validated call before the final check marked only the Job stale. Do not try to rewrite a terminal ledger receipt or weaken currentness. Preserve original successful call d776be18-16b4-42b0-9888-b6f2e5678a6f, exact request/result digests and zero-call replay. No paid call.

## Allowed ownership

backend/src/gridlens/intelligence/intelligence_jobs.py for M4 finalization only; backend/src/gridlens/integrations/logical_calls.py for opt-in deferred commit with unchanged defaults; backend/tests/integration/test_commercial_assessment_job.py; backend/tests/integration/test_logical_calls.py; backend/tests/unit/test_commercial_assessment.py only if needed; docs/operations/production-pipeline-20261023.md. Own ignored .agent/artifacts/PRODUCTION-M4-PUBLICATION/COMPLETION.json and development receipts. Exclude all other files, canonical requirements, migrations/models, provider schema/transport, UI/API, credentials, retained databases, Git and external mutations. No subagents.

## Required boundary

Follow Sol's recovery note exactly: for M4 valid/stale provider responses, defer complete_call until final currentness decision; retain existing quarantine/conclusive-failure behavior. Use a transaction-level REPEATABLE READ snapshot before input queries, deterministic locking/refresh of the Job fence and exact need/project/package/evidence/observation/source rows, and one as-of-publication digest/time label. Do not claim locks freeze inserts or all future writers. Invoke no-internal-commit settlement while Job remains running, check returned call/fence state, update checkpoint/status, and commit together. Lost fence, unexpected terminal state or failed publication rolls back. Serialization retry is bounded and retries only final read/settlement, never provider execution. No new store, orchestrator, migration or broad worker rewrite. Return a demonstrated constraint if these invariants cannot be achieved in scope.

## Deterministic acceptance

Force the exact inter-check race with two sessions and a deterministic barrier; assert call and Job both record STALE_CONTEXT, no disposition/selected-fact advisory, preserved usage/cost, zero second dispatch and no unrelated canonical writes. Fresh path publishes both VALIDATED. Cover lost fence, duplicate terminal settlement and rollback preventing split statuses; later changed source must make replay stale with zero dispatch. Verify default complete_call behavior still commits, deferred mode is caller-transactional, and injected failure rolls back call and Job together. All prior M4/M3/ledger tests remain green.

Use backend working directory and explicit pyproject.toml for Ruff/format/mypy, then run root m4_checks.py --owner builder --label publication (root enables label). Run static checks again after any import edit. Isolated pipeline_test only; no direct credential reads/printing. Two materially distinct repair attempts maximum, preserve failures; if unresolved return to canonical recovery instead of another unchanged attempt. Root reruns focused checks, healthy retained replay, freezes exact candidate, full gates/CI and independent Sol review. No self-acceptance.

Handoff exact file hashes, commands/exit codes, measured UTC start/finish and durations, model/lane/config identity, repair count, tokens or UNKNOWN, and remaining uncertainties. Keep declaration and proof aligned; earlier real-call evidence is preserved, not re-executed or silently broadened.

## Bounded specialist recovery

Luna stopped after two failed combined receipts, publication and publication-r1. They exposed a wrong model in a citation-lock predicate and UUID conversion of string Source.id; both were locally corrected afterward. Three targeted M4 tests and static checks passed on later bytes, but the whole candidate and atomic rollback/fence/serialization coverage remain unverified. The failed receipts are retained and do not certify current files. The controller now assigns the same allowed files and approved architecture to one Terra specialist for this concurrency/integration problem; Luna releases implementation ownership. Terra must inspect the actual partial implementation, finish the required behavioral coverage, and run the unused specialist focused labels. No scope expansion or new paid call. At most two materially distinct specialist repairs, then return concrete remaining constraints. Independent Sol acceptance and root exact-candidate gates remain required.
