# C7 — bounded schedule proof and structured recovery

Approved Sol runtime_architect direction after independent6d88 FIX. Two serialized
nodes C7a then C7b; do not reconvene Tribunal. Base6d88 + B5/C6 shared repairs;
root supplies current identity at dispatch. No self-acceptance or deployment.

## C7a READY after C6 model/worker release

Own worker.py scheduling/receipt logic, a shared pure schedule-proof helper,
persistence/models.py and sole additive0029 migration, API app.py source health,
intelligence_operations.py source-cycle metrics, new PG scheduling proof tests
and narrowly affected source scheduling/health fixtures, explanatory runbook.
C6 retains test_worker_planning_liveness.py until its handoff; B5 owns billing/
settings/provider/financial tests. No competing edits. Use exclusive runtime test
DBs supplied by root. No provider/network/spend/production/commit/merge/deploy.

Add minimal SourceScheduleProgress keyed epoch_id with recent/history lower-bound
cursors and last_planned_at. Fair bounded epoch/instant batches; prioritize rolling
seven-day occurrences, incrementally materialize older history, never replay every
historical epoch/instant each pass. Bulk dedup due keys, advance progress in the
same transaction as durable due insertion. Restart/overlap/concurrency must neither
skip obligations nor create duplicate open epochs. Historical missing obligations
stay missed/UNKNOWN; calculate bounded-window expected denominator from canonical
epoch schedule even before due rows materialize. No historical success fabrication.

Bound assignment query/row locks; newest still-open cycles first. A due may bind
only a queued job, before lease/acquisition, with locked/rechecked Job to prevent
lease race. If enqueue returns running, leave due unassigned. Never repeatedly fetch
today's window to fill stale historical slots. Late results may retain useful
evidence but cannot count as prior scheduled success.

After source/registry/fence/admission preflight, immediately before public fetch,
read PostgreSQL clock_timestamp() as acquisition_started_at. After evidence commits
read acquisition_completed_at. Put ISO aware UTC values and schedule_proof_version=1
in existing digest-bound receipt check_counts; explicitly set recorded_at from
clock_timestamp() at insertion (transaction-start now() is insufficient). One shared
verified-success predicate for health and intelligence operations:
valid job/fence/digest/association; scheduled_for <= started <= completed <= recorded_at
< next epoch-derived scheduled instant, DST-aware and respecting epoch transition.
Legacy successes missing proof remain retained attempts but UNVERIFIED/UNKNOWN for
success numerator and FRESH. Explicit failed/partial outcomes stay negative.
Do not infer start from created_at or backfill historical timestamps.

Sole0029 ownership also creates SourceCollectionProgress for C7b, keyed source_id,
lane and policy/config digest, with bounded window/cursor/checkpoint, completed-
through, incomplete/error status and attempt/completion/update timestamps. Choose
minimal typed columns plus bounded JSON cursor; publish exact frozen schema/contract
in handoff. C7b consumes it without migration/model edits. No new queue/platform.

Meaningful real PG tests: years/hourly backlog per-pass caps and repeat O(batch),
all historical expected misses preserved before materialization, fair other-source
progress, commit/restart and concurrent planners idempotent, queued/running lease
race, today fetch cannot satisfy yesterday, pre-due running fetch cannot satisfy new
slot, valid actual interval passes, late/legacy/invalid digest/naive/reversed times
UNKNOWN, DST gap/fold and epoch transition, health/ops agree. Update only explicitly
synthetic proof fixtures; preserve original receipts. Migration fresh/repeat/drift
and affected tests/Ruff/fullmypy. Two distinct repairs per failure mode.

## C7b WAIT for C7a schema and worker handoff

Own Socrata and Boston adapters, structured branch of ingestion/service.py,
SourceCollectionProgress service/helpers and narrow worker partial/status handling,
adapter/PG recovery tests and runbook. No schema/model/migration edits. Structured
issue and supported modification lanes resume bounded windows from durable state;
Seattle has no modification lane, do not invent it. Boston issue-date lane. Retain
rolling overlap rechecks while old backlog resumes beyond original lookback.

One bounded segment per acquisition; split overfull date windows and use documented
stable date/row-ID keysets when a day exceeds cap. Do not invent source guarantees.
Count/order/recheck certifies segment completeness; changing count, parse/time/cap
failure leaves cursor and useful last-good facts intact and shows PARTIAL/UNKNOWN.
Fenced evidence commits precede progress advancement; crash between replays safely.
Bind source/config/parser/lane policy versions and recheck context before checkpoint.
Cursor cannot suppress unfinished processing/reassessment forever. Follow-on
continuation jobs use existing transactional enqueue after old job terminal state;
no source starvation/full-corpus rescan. Current-window partial/backlog cannot be
reported fully fresh/succeeded. Existing disabled/global public admission controls
apply; retain C5 hard pure-acquisition bounds and no DB/provider in child.

Rollback must stop the whole worker and park queued/running ingestion continuation
jobs before starting an older worker. Continuations use the existing ingestion kind;
WORKER_AUTO_REFRESH only disables planning and cannot prevent their execution.
Preserve parked job IDs and collection checkpoints, disable affected sources through
the supported registry control, and document deliberate resume without replaying
already-dispatched provider calls or refunding UNKNOWN exposure.

Tests: supported official-shaped paginated responses, over-cap day/window progress,
long outage resume, modification lane/late updates, changed counts/deletes/no false
completion, crash before/after evidence and before cursor, stale source/fence and
duplicate delivery, source disabled no fetch, partial retains last_good/no false
cycle success, real PG concurrency and bounded responsive reads. No live HTTP or
provider tests. Root reruns final full gates/restore/runtime and independent Sol.

Each handoff: exact files/identity, actual commands/exits/UTC, bounds/limits,
completion artifact; no fabricated timing/tokens/coverage or seven-day proof.
