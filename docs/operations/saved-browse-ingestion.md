# Saved browse publication during ingestion

Continuous evidence ingestion previously invalidated the entire saved browse
generation. A full rebuild could finish after another write and repeatedly lose
its publication race, leaving ordinary map requests at qualification-pending 503.

Migration `0030_browse_ingestion` records the affected projects for retained
evidence, observation links, interpretations, lifecycle, matching, material state,
brief and buying-chain writes. Reassignment includes old and new owners and all
shared-observation consumers. Unknown inputs and source policy changes still
require a full rebuild. Source health-only updates do not change qualification.

The worker installs a before-commit callback. A transaction-local database trigger
flag restricts it to transactions that actually changed canonical browse inputs;
queue, planner and lease-renewal commits cannot repair someone else's backlog.
Canonical changes flush before the derived-work savepoint. A failed publication
rolls back only derived work, retaining the evidence and invalidation for recovery.

Publication holds the browse-state fence, expires previously read ORM values,
copies unaffected saved rows, and reconstructs affected needs with the canonical
qualification/ranking code. Summary batches contain at most 100 needs; detail
batches contain at most 50. Global counts and the pointer publish together only
after all batches complete. Policy, exact input revision and clock validity checks
remain mandatory on every read.

Interactive mutations keep a 100-project/100-need bound. Worker publication allows
up to 1,000 projects/needs, with a cooperative 60-second budget capped by the
original acquisition deadline. Checks occur between summary/detail batches and
before publication. This is not an absolute interrupt of one Python/SQL operation.
The existing acquisition lock/statement timeouts and lease settlement rules remain
in force. Offline maintenance and full-build tail rebasing can finish a larger
finite dirty set in the same small batches, avoiding permanent bulk starvation.

## Release and recovery

Use the [current release/recovery procedure](recovery-release.md) for operational ordering and the protected wrapper contract. This guide describes retained ingestion publication; it grants no production action.

Before a separately authorized release, verify actual images/schema and protected tooling, hold writers and browse maintenance, capture a fresh verified backup and prove isolated restore/current-data rollback. Keep canonical evidence, source schedules and provider accounting intact. Coordinate API, ingestion and browse on the same validated backend artifact and policy. Stage, inspect and guarded-publish a valid derived generation before accepting candidate reads; release workers only after authenticated canary acceptance.

Current project/company result routes always require a valid generation, regardless of `SAVED_BROWSE_ENABLED`. Some legacy list/map/detail paths retain flag-gated canonical evaluation, but switching the flag false does not recover the ordinary project/company UI. Missing, expired or invalidated generations remain qualification-pending HTTP503. If publication or canary fails, hold traffic/writers and use the rehearsed current-data stage/inspect/publish recovery lane under the selected compatible image's policy. Never force pointers, bypass freshness or restore an old database over new evidence.

Historically, migration 0030 downgrade restored the previous trigger policy and invalidated derived generations without deleting canonical evidence. That behavior is not a current application rollback procedure; preserve the forward schema and privacy ledger.
Tests cover rollback/reapply, source policy versus health, shared dependencies,
concurrent reads, bulk ingestion/checkpoints, replay deduplication, expired budgets,
and savepoint/heartbeat isolation. Provider calls are unnecessary for these tests.
