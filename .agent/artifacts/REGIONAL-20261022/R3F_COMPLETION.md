# R3F completion handoff

Both TCEQ document adapters now stop making document requests after HTTP 429, or after a transient HTTP response carrying a valid `Retry-After`. Successful earlier documents remain processable; the throttled and unrequested siblings stay explicit presence-only rejections, preventing snapshot reconciliation from treating them as absent. The bounded numeric/date/excessive `Retry-After` diagnostics flow through source acquisition normalization. Source partial health records a source-wide `scheduled` cooldown or `operator_review` for a delay over seven days; the existing enqueue and SQL lease guards enforce it. A 429 without `Retry-After` uses the existing bounded jittered retry policy. Record-local 404 behavior remains unchanged.

Changed files:

- `backend/src/gridlens/ingestion/adapters/tceq_nsr_pending.py`
- `backend/src/gridlens/ingestion/adapters/tceq_temporary_batch.py`
- `backend/src/gridlens/ingestion/service.py` — bounded diagnostics normalization and count propagation.
- `backend/src/gridlens/jobs/worker.py` — partial-source retry hold health fields.
- `backend/tests/integration/test_tceq_rate_limit.py`

Validation used `.artifacts/regional/range-test.env`, loaded silently:

- `pytest tests/integration/test_tceq_rate_limit.py tests/unit/test_tceq_nsr_pending.py tests/unit/test_tceq_temporary_batch.py tests/unit/test_tceq_http.py tests/unit/test_acquisition_recovery.py tests/integration/test_structured_collection_recovery.py tests/integration/test_structured_collection_adversarial.py -q` — **63 passed** (9.94s).
- Ruff format/check on all five changed files — **passed**.
- Mypy on both TCEQ adapters, `service.py`, and `worker.py` — **Success: no issues found in 4 source files**.
- `git diff --check` — **passed**.

The integration regression verifies both adapters make no third PDF request after the throttle, retain the successful prefix, normalize the 120-second hint, and mark the remaining row deferred. It also verifies persisted evidence replays unchanged without duplicate Evidence/Observation rows and that a queued job is not leasable before the source retry boundary, then is leasable after it. Excessive-delay diagnostics are covered through the seven-day bound. Root retains final frozen-candidate, official replay, and broader repository checks.

## Repair 2 after controller rejection

Root rejected the initial handoff after finding that `run_one` first set partial cooldown health, but the later generic health merge unconditionally replaced it with `retry_state="not_scheduled"` and `retry_at=None`. The initial integration test manually assigned `Source.health.retry_state="scheduled"` and therefore did not exercise propagation through `run_one`; that test was insufficient and has been replaced. The generic merge now preserves retry fields only when the run carries validated `source_rate_limited=True`, while non-throttle and complete paths clear stale holds.

The replacement parameterized range-DB test calls the real `worker.run_one` and real `process_job`/normalizer, with the adapter's acquisition response produced by `httpx.MockTransport` and an inline acquisition seam. It verifies scheduled 120-second cooldown, over-bound `operator_review` and blocked enqueue/lease, and no-header 429 bounded fallback. It verifies `last_success` and prior `last_success_counts` remain unchanged; accepted prefix counters are known (`attempt_new=1`, `attempt_processed=1`, `attempt_fetched=3`, `attempt_rejected=2`); prefix Evidence and Observation each persist once and replay unchanged; new jobs cannot lease before the source hold and can after the explicitly advanced boundary.

Repair 2 validation, using `.artifacts/regional/range-test.env` loaded silently:

- `pytest tests/integration/test_tceq_rate_limit.py tests/unit/test_tceq_nsr_pending.py tests/unit/test_tceq_temporary_batch.py tests/unit/test_tceq_http.py tests/unit/test_acquisition_recovery.py tests/integration/test_structured_collection_recovery.py tests/integration/test_structured_collection_adversarial.py -q` — **65 passed** (11.00s).
- Ruff format/check — **passed**.
- Mypy on both TCEQ adapters, `service.py`, and `worker.py` — **Success: no issues found in 4 source files**.
- `git diff --check` — **passed**.
