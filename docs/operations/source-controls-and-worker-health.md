# Source controls and worker health

Registry enablement and the database operator switch are separate controls.
Effective collection requires both to be enabled. Routine registry reconciliation
updates the registry flag and source definition but never resets the operator
switch. An operator can explicitly change that switch with the authenticated,
same-origin endpoint:

```http
POST /api/sources/{source_id}/enabled
Content-Type: application/json

{"enabled": false}
```

Use `{"enabled": true}` to explicitly re-enable a source that is still enabled
in the registry. The endpoint reads and synchronizes that source's current
registry definition while holding its transition lock, even for a no-op request.
An operator transition closes the current schedule epoch and records its known
effective UTC time in the same transaction. If registry/configuration drift was
not observed earlier, its prior interval becomes unknown rather than being
backdated to the operator request. Seven-day
freshness remains `UNKNOWN` until the uncertain interval leaves the window. If
the registry disables a source, the operator endpoint cannot override it.

### Disable behavior

Before disable, a queued or expired-retry ingestion job can be leased and may
make a provider request. After disable, ingestion jobs remain queued/running for
inspection but are not leased. A worker also reloads the source definition and
checks the effective database state immediately before acquisition; if disabled,
it returns the job to the queue without consuming a provider attempt and records
the reason on the job and source health. A PostgreSQL dispatch lock spans
acquisition and the fenced result, so an operator disable waits for a request
already dispatched to finish or fail. That in-flight attempt is retained with
its outcome; the worker does not interrupt a possibly completed external
request and blindly replay it.

### Scheduling and freshness

Each enabled schedule epoch records its source configuration, cadence, mode,
timezone, anchor and effective interval. Cadences below 24 hours use elapsed UTC
intervals. Local-daily cadence is a positive integer number of whole 24-hour
days; values such as 36 hours are rejected rather than rounded to a different
schedule. Daily schedules use a local wall-clock anchor (default 03:00 in
America/Chicago); nonexistent spring-forward times resolve to the first valid
wall time after the gap, and ambiguous fall-back times use the first occurrence.
The worker reconciles missed occurrences into a unique source/epoch/UTC due
ledger. Each due occurrence can link to one ingestion job; retries keep that
link and add fenced attempt receipts instead of creating another denominator
unit. Receipts distinguish successful, partial, failed and unknown outcomes.
The seven-day health view independently derives expected due identities from
known enabled epochs over the Chicago-local window. Every expected slot must
have a persisted due row and a matching fenced, complete success receipt to
count as fresh. A worker stopped before due-ledger reconciliation therefore
leaves missing slots `OVERDUE`; the health request never reconciles or enqueues
work itself. Unprovable legacy or drift intervals, invalid schedule parameters,
and unverifiable receipts remain `UNKNOWN` rather than being treated as
successful coverage. The health query loads only epoch intervals that intersect
the window, and old schedule anchors are evaluated from the seven-day window
boundary, not replayed from enrollment. It also compares the current registry
definition with the latest open known epoch; an unrecorded registry edit is
reported as `UNKNOWN` until a worker records its transition. The displayed
health `enabled` flag is true only when the persisted registry flag, current
live registry declaration, and operator switch are all enabled. An unsynchronized
registry enable cannot override a persisted registry disable or make health claim
that ingestion is effective.
Registry comparison covers publisher, endpoint, family, geography, industries,
retrieval method, cadence, schedule mode, timezone, and schedule anchor. A missing
meaningful snapshot field is not ignored. Omitted current cadence is equivalent
to 24 hours only when the persisted epoch cadence proves that default; omitted
mode, timezone, or anchor values are checked against the epoch's immutable
schedule columns and anchor.

Health signals answer different questions:

- `GET /health/live` reports that the API process can answer without querying
  PostgreSQL.
- `GET /health/ready` verifies the database and queue can be queried.
- Authenticated `GET /api/health` reports the worker heartbeat (`LIVE`, `STALE`
  or `UNKNOWN`), planner attempt/success/backoff state, and per-source seven-day
  ledger freshness. An HTTP 200 response alone does not establish collection
  freshness.

For example, after a source is disabled, its pending ingestion stays visible but
`lease_one()` leaves it untouched; explicitly enabling it again makes it
eligible under ordinary queue limits. If source planning raises an exception,
the planner row records its error class and bounded next retry while the worker
continues to lease unrelated ready jobs and runs the independent pursuit
question planner when eligible.
