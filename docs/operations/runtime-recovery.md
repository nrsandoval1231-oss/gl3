# Runtime recovery — GL3-020

Recover the configured application database in place. Preserve `.env`, credentials, source artifacts and existing data. Do not create a replacement corpus or reset the application database to make acceptance pass.

From the repository root, first inspect existing listeners and processes. Start the existing PostgreSQL cluster using its established command if needed. Apply pending migrations with `(cd backend && .venv/bin/alembic upgrade head)`; this is additive migration, not database replacement.

```bash
uv run --project backend python -m gridlens.jobs.runtime status
uv run --project backend python -m gridlens.jobs.runtime reconcile
uv run --project backend python -m gridlens.jobs.runtime check \
  --source austin-building-permits --source texas-rrc-drilling-permits
```

`status` uses a read-only transaction. Missing persisted registry entries, field drift and unregistered retained sources are reported separately. Counts and saved source health are database observations, not service-health probes. A stale saved success is not a current refresh.

`reconcile` inserts/updates registry entries using the existing worker synchronization. Health, jobs, evidence and project history are preserved. Unregistered rows are reported and retained; no automatic deletion or retirement is performed.

`check` validates all selections before mutation, deduplicates repeated IDs and attempts each selected source at most once. Existing queued/running jobs are reused. Future backoff and active leases remain intact, so a job can be reported as deferred without a new request. Expired selected jobs use normal lease recovery; unrelated jobs and expired leases are untouched. Exit 1 means at least one selected check failed or was deferred. It does not block checks for other selected sources. Existing adapter timeouts, byte/page limits, source restrictions and deterministic admission stay authoritative.

After a successful check, repeat the same command to test source replay. Inspect job status and new/changed/unchanged counts, and verify persisted content/evidence identities before claiming duplicate-free replay. Source data can change between requests; changed records must retain prior evidence. Do not count unchanged records as fresh opportunities.

Start API and web using the saved handoff commands; sign in using the existing ignored local credential file. Verify authenticated Signals, evidence detail and source health; unauthenticated requests must remain rejected.

For continuous collection in this development runtime, the existing worker can be started with `WORKER_AUTO_REFRESH=true`. It plans due sources at startup and hourly thereafter. A paused/suspended executor cannot guarantee daily collection. Production still requires authorized durable hosting, the managed scheduler, secrets, alerts, backups and seven measured scheduled daily cycles. This slice does not close PRD milestones A or E.

## Texas RRC calendar boundary

RRC snapshot selection and freshness use `America/Chicago`, the publisher’s local day. Between UTC midnight and Texas midnight, the previous month-end product must still be selected from the Texas month. This fixes the October 1 01:00 UTC request for a September EOM while it was still September 30 in Texas. After Texas midnight, an unpublished required EOM still fails visibly; no guessed backup or older archive substitutes for it. The missing-snapshot error includes the requested filename.

## Stable grouped-permit replay

Several accepted permits can support the same power need. An unchanged check retains its saved admission citation when that citation still links to current accepted evidence for the same project/activity and current admission policy. This avoids rotating between valid permit citations and updating the opportunity timestamp on replay. Invalid/outdated bases still refresh; real source changes continue through the existing correction/history path.
