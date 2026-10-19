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

1. Back up canonical PostgreSQL and the private deployment configuration. Verify
   the dump catalog and a restore on an isolated database. Retain prior images.
2. Gracefully stop the ingestion worker and browse maintenance for migration;
   preserve persistent volumes, source schedules, due checks and provider budgets.
3. Deploy the same validated backend image to API, ingestion and browse services.
   Upgrade the schema and build a current saved generation before enabling saved
   reads. Keep the API's canonical read fallback available during this transition.
4. Resume ingestion and maintenance. Measure authenticated national map, state,
   project, evidence and Back navigation, including repeated reads during real
   ingestion commits. A ready web page alone is insufficient acceptance.
5. If publication fails, switch only the API to `SAVED_BROWSE_ENABLED=false` and
   use canonical reads while diagnosing maintenance. This fallback is slower.
   Prior application images may be restored with the fallback enabled. Do not
   restore an older database over new evidence merely to roll back application code.

The migration downgrade restores the previous trigger policy and invalidates
derived generations; it does not delete canonical evidence or accepted history.
Tests cover rollback/reapply, source policy versus health, shared dependencies,
concurrent reads, bulk ingestion/checkpoints, replay deduplication, expired budgets,
and savepoint/heartbeat isolation. Provider calls are unnecessary for these tests.
