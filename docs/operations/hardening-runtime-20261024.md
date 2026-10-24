# Runtime hardening findings — 2026-10-24

## Disposition

One bounded runtime fix addresses a credible lost-renewal defect: a transient
lock on the worker's own job row could permanently stop its lease-renewer
thread. Other production signals do not justify database configuration or
failure-classification changes. The sampled host was healthy and idle at capture
time; historical attribution remains uncertain where the sanitized parser may
have associated adjacent statements.

## Evidence reviewed

- `.artifacts/readiness-20261024/production-runtime.json` reports 54 row-lock
  errors, 24 canceled autovacuum tasks, 2 lock-timeout cancellations, and 1
  statement-timeout cancellation. It reports zero expired running leases and
  zero overdue queued jobs. Its relation name is redacted.
- `.artifacts/hardening-20261024/production-readonly.json` captured 11 database
  connections against `max_connections=100`, no blocked sessions, no
  idle-in-transaction sessions, and zero cumulative deadlocks. It identifies
  `pg_toast_669935` as the relation involved in the autovacuum cancellations;
  the parent relation is `browse_rows`.
- `.artifacts/hardening-20261024/production-readonly-detail.json` associates 53
  row-lock events with statements touching `jobs`, but the statement parser may
  attach a later statement to an earlier error. The runtime contains a matching
  nonblocking `NOWAIT` job-row renewal path, making it a credible source of
  transient row-lock errors; this does not establish that all 53 events came
  from that path. No blocker was visible during either current-state sample.
  Historical waiter/blocker identity remains unknown.
- `.artifacts/hardening-20261024/production-libraries.json` attributes the two
  lock-timeout and one statement-timeout events to `ANALYZE browse_rows`.

## Locking and browse publication paths

`jobs/queue.py::lease_one` claims work with `FOR UPDATE SKIP LOCKED`. The
`FencedLeaseRenewer` in `ingestion/adapters/acquisition_runtime.py` also uses
NOWAIT on its own `Job` row, then previously stopped permanently on any lock
exception. A short worker checkpoint or status transaction can legitimately
hold that row for one tick, so permanent renewal shutdown on that collision was
too brittle. The fix uses `SKIP LOCKED`; a skipped but still-present job is
retried at the next bounded interval. Missing jobs, terminal jobs, owner/fence
mismatches, and expired leases still stop renewal, and other database errors
remain fail-closed. The five-second settlement cap is unchanged.

The SQLAlchemy engine uses `pool_pre_ping=True` with standard pool defaults. The
host sample shows neither connection pressure nor a lingering open transaction,
so no pool-size or timeout change is supported by this evidence.

Browse maintenance does not truncate `browse_rows`. Scoped publication clones
rows into a new generation and prunes old generations with DELETE. Its
`_publish_group_metadata` step updates JSONB `BrowseRow.compact`, which writes
the `browse_rows` TOAST relation. Full rebuilds write a generation, analyze the
table, commit it, and then publish the generation pointer under the
`BrowseState` lock. `ANALYZE browse_rows` accounts for the observed 2 lock and 1
statement timeout. For worker scoped publication it runs inside the
`worker_browse._before_commit` savepoint; the handler catches the error, rolls
back derived publication only, retains canonical writes and leaves qualification
pending. For full rebuild it precedes the new generation commit and pointer
publication, so failure leaves the old generation selected. Keep ANALYZE: the
code comment documents that fresh backfills need usable filter/group plans to
avoid quadratic nested-loop metadata work. The artifacts do not establish the
specific lock interaction behind the 24 canceled autovacuum tasks. Autovacuum is
enabled; no setting change is justified.

## Source outcomes

- `houston-weekly-permits` is failed with `publisher_stale`, zero fetched and
  parsed rows. The Houston adapter raises this classification when the newest
  official dated report is more than 30 days old. This is a publisher-freshness
  failure, not a transport retry or evidence that the source returned an empty
  current report.
- `austin-building-permits` is partial after 1,000 records were fetched and
  parsed, with 13 accepted. The worker explicitly records `Collection paused at
  chain job budget` when the bounded collection continuation reaches its job
  budget. This is a budget pause, not a successful complete backfill; it remains
  partial and is not silently retried without a scheduled retry state.
- `texas-tceq-nsr-pending` is partial with 328 fetched, 327 parsed, and 4
  accepted. Ingestion service selects `RecordLocalFailures` when a partial
  adapter result contains rejected records. The one-record difference supports
  this local-failure classification; it does not justify discarding accepted
  records or relabeling the batch complete.
- `texas-puct-large-load-dockets`, `texas-puct-large-load-filings`, and
  `oklahoma-deq-public-review` are reported updated with 10, 296, and 7 parsed
  records, respectively. The available evidence shows no acquisition failure
  for these paths. New Mexico coverage is not implicated by the sampled events.

## Validation boundary

The H2 runtime change is limited to lease-renewer recovery after a transient
job-row lock. No database settings, migrations, indexes, retry policy, or source
failure classifications changed. The focused Postgres tests
`test_lease_renewer_resumes_after_transient_job_row_lock` and
`test_lease_renewer_caps_extension_at_original_deadline_plus_grace` passed
against the controller-provided isolated test database (2 passed, 2.73 seconds).
The fixture's existing `_test` suffix safety guard remains unchanged.
Controller-owned SSH, Docker, shared production database, and live source
operations were not performed by H2.
