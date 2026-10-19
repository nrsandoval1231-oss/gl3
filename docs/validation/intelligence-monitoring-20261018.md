# Bounded intelligence monitoring (C/E slice)

This slice adds per-need versioned watch sets on the existing PostgreSQL jobs and
evidence graph. Monitoring and provider intelligence remain disabled by default.
The worker's monitor planner runs independently from broad source auto-refresh;
it does not create a new source or grant a source privilege.

`ProjectMonitorWatch` owns the need, stable question IDs, unresolved questions,
last-good facts/references, status, freshness, and immutable revision snapshots.
`ProjectMonitorWatchSource` owns exact URLs and stable IDs, registry/acquisition/
retention policy digest, due time, cursor/checkpoint, optional validator metadata,
backoff, and quarantine state. A watch revision or explicit bounded
`reprocess_revision` change makes every enabled source due again and retains the
previous policy/cursor/last-good snapshot. Initial accepted evidence is the
watch's last-good baseline, so the first identical retrieval does not enqueue
grounded reasoning.

The only automatic provisioning inputs are active needs with current accepted
evidence linked to a currently enabled registry source and stable observation.
Provisioning uses bounded UUID keyset pages and wraps once to revisit older
eligible needs. Unmatched, disabled, unsupported, or private targets do not gain
authority. Manual watch APIs are `upsert_watch(session, need_id, *, sources,
question_ids=None, enabled=True, reprocess_revision=None)` and
`watch_view(session, need_id)`.

Planning is disabled unless the worker feature flag is on. A PostgreSQL advisory
lock serializes schedulers; selection uses `SKIP LOCKED`, a maximum 100-row due
page, configured plan size, global/per-host/per-source active caps, and active
need/enabled-source checks. Repeated failed or partial attempts back off at 1,
6, then 24 hours and quarantine at five consecutive failures. A deliberate watch
revision resets quarantine and schedules reprocessing.

The default runner fetches only each already accepted stable record through the
existing reviewed adapter. It validates public URLs, does not follow redirects,
checks the exact source host and per-watch result URL, caps the complete attempt
at five documents, 750,000 bytes per document, and 180 seconds, then runs the
existing `retain_registered_record` canonical admission with models disabled.
Network I/O occurs outside database transactions. A second short transaction
rechecks source/need/watch policy and the job fence before retention. Facts and
evidence are changed only after retained evidence links back to the same need,
source, content hash, and exact allowlist. Partial, failed, blocked, and
cancelled attempts retain last-good facts. Optional grounded-job scheduling is
called inside that fenced transaction only after an actual retained content
change; unchanged content does not enqueue it. The shared question registry
contains the six stable utility, load, construction, commissioning, gas, and
buyer-authority IDs while preserving the existing research categories.

## Validation

Commands ran against task-local databases only:

```powershell
$env:DATABASE_URL='postgresql+psycopg://gl3_intelligence@127.0.0.1:55487/appgl3_monitoring_20261018'
$env:TEST_DATABASE_URL='postgresql+psycopg://gl3_intelligence@127.0.0.1:55487/gl3_monitoring_20261018_test'
uv run --directory backend ruff check src/gridlens/intelligence/monitoring.py src/gridlens/intelligence/question_contracts.py src/gridlens/persistence/watch_models.py tests/integration/test_monitoring.py
uv run --directory backend mypy src/gridlens/intelligence/monitoring.py src/gridlens/intelligence/question_contracts.py src/gridlens/persistence/watch_models.py --show-error-codes
uv run --directory backend pytest tests/integration/test_monitoring.py -q --tb=short
uv run --directory backend alembic downgrade 0025_logical_call_ledger
uv run --directory backend alembic upgrade head
uv run --directory backend alembic upgrade head
```

Results: Ruff PASS; mypy PASS; focused PostgreSQL integration `12 passed`; the
dedicated application DB downgraded 0026→0025, upgraded to `0026_watch_sets`,
and repeated upgrade was a no-op. The resulting schema includes both watch
tables, their revision and policy snapshot columns, and the partial active
monitor-job index. `git diff --check` passed (Git emitted only existing
line-ending normalization notices for concurrently owned files).

The default-runner test patches the low-level acquisition transport and
canonical-retention seam; all retrieval decisions are exercised without HTTP.
No real-source cycle, deployment, provider call, owner review, or live daily
cycle was performed. Those remain UNKNOWN/open and require separate
authorization and runtime evidence.
