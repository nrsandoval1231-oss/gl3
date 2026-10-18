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
