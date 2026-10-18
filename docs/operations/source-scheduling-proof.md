# Source schedule recovery and proof

The worker materializes scheduled source checks in bounded batches. The rolling
seven-day window is planned first; older schedule history advances through a
persisted per-epoch cursor. A one-day overlap makes recent inserts safe to repeat
after a restart. Due rows are uniquely keyed by source, epoch, and scheduled
instant, so repeated or concurrent planner passes do not create duplicate
obligations. Health derives its seven-day expected denominator from the canonical
epoch schedule, including obligations that have not yet materialized; missing
checks remain overdue or unknown rather than being treated as complete.

A scheduled success receipt requires a fenced completed ingestion job, matching
due/job association and digest, plus `schedule_proof_version: 1` and aware UTC
`acquisition_started_at` / `acquisition_completed_at` values in `check_counts`.
The recorded timestamp is taken from PostgreSQL at receipt insertion. The interval
must start at or after the scheduled instant, complete before receipt insertion,
and be recorded before the next epoch-derived scheduled instant. Epoch transitions
and local daylight-saving rules determine that next boundary. Missing legacy proof,
invalid timestamps, and late results remain inspectable attempts and count as
`UNKNOWN`; failed and partial dispositions remain negative outcomes.

`source_collection_progress` is the C7b checkpoint contract. Its unique key is
`(source_id, lane, policy_digest)`. `cursor` is JSONB limited to 8,192 text
characters by the database guard. A row records
the bounded window, completion-through instant, `incomplete|complete|partial|error`
status, error class, and last attempt/completion/update timestamps. Collection
progress changes must follow durable evidence commits and must remain bound to the
source, lane, and policy digest.

Structured permit collection uses one date at a time and at most one 1,000-row
keyset page per acquisition. A date with more than 1,000 rows resumes after its
stable row key. The adapter counts before and after the page, checks returned row
order and window membership, and advances only when the observed rows match the
count. These checks bound and detect common concurrent edits; they do not assert
that the publisher provides a transactional snapshot. A count change, invalid
page, disabled source, changed registry policy, stale lease, or oversized cursor
leaves the lane incomplete/partial and does not advance its cursor. Cursor JSON is
also limited to 8,192 serialized UTF-8 bytes in the service.

Socrata lanes are `issue_recent` and `issue_history`. Austin and Chicago also have
`modified_recent` and durable `modified_history` lanes because their reviewed field
maps expose modification dates. Seattle has no modification lane. Boston uses
issue-date lanes only. Recent lanes recheck a rolling seven-day overlap. The issue
history lane starts at the configured issue `window_days`; a modification-history
lane starts at the source's configured `modified_window_days`. Each then resumes
from its own `completed_through` in windows no larger than seven days, including
after a long outage. Austin's configured `issue_backfill` is a separate finite,
filtered lane and does not widen the general permit query. The initial source
lookback is not a claim of completeness before that configured baseline.

Date filters preserve source field semantics. Austin's `issue_date` and
`statusdate`, and Boston's `issued_date`, are treated as date/naive source values;
the UTC-midnight database carrier is not interpreted as their local timezone.
Chicago's `:updated_at` is a UTC system timestamp and its modified-lane bounds use
`Z`. No timezone is inferred for a date-only or naive publisher field. History
continuations are ordinary `ingestion` jobs queued transactionally only after the
current job becomes terminal; each segment commits evidence before separately
rechecking the fence and source policy to advance progress. A crash between those
commits safely repeats evidence and leaves the cursor unchanged. Partial or
backlogged lanes do not update source `last_success` or count as fresh.
