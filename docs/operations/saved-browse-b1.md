# Saved browse B1

The rollout switch is `SAVED_BROWSE_ENABLED`, default **false**. The approved UI
is unchanged. Only its project-title helper consumes the saved title because
compact list/map responses deliberately omit evidence and lifecycle histories.
Opening a record reads canonical detail for that exact need.

## Behavior and boundaries

Canonical evaluators remain authoritative. A retained-data-only builder writes
immutable summaries, normalized historical search text, ranks/reasons, filter
columns, group metadata and counts. Generations bind the complete local Python
code fingerprint, input revision, build instant and expiry instant. PostgreSQL
statement triggers invalidate on relevant committed SQL writes, including bulk
updates, corrections, accepted/rejected facts and relationship changes. Rolled
back writes do not invalidate. Queue/auth/budget writes are excluded.

The first implementation uses a conservative global revision. It serializes the
revision update and rebuilds the complete generation after a relevant mutation.
This is an explicit update-availability tradeoff, not per-project incremental
maintenance. Rebuild lag and write contention need production measurement before
activation. During a rebuild, browse returns HTTP 503 with qualification pending,
`Retry-After: 5` and `X-Qualification-State: pending`; no stale Lead is returned as
current. Unscoped detail still reads current canonical inputs directly.

Expiry is the earliest UTC, Chicago or host-local date rollover, or a future
operator fact start/end instant. A build crossing its expiry cannot publish.
Publication compares the captured input revision atomically. A separate advisory
lock permits one builder per database. Three derived generations are retained;
canonical evidence/history is never deleted by maintenance.

Ordinary ranked pages/maps use saved counts and an ordered index page read.
Arbitrary dimension/search/decision combinations aggregate compact scalar rows to
preserve grouping after dimension filters and group-wide search/decision rules.
They load presentation payloads only after LIMIT. They do not reconstruct evidence
or rerank the population. Offset pagination can still walk skipped index entries;
arbitrary substring search is not constant-time. Export retains its explicit row,
history and byte limits and reads canonical detail only for selected records.

## Commands

Run in the already configured application environment; never print or export its
secrets. These commands do not dispatch collection, research or paid providers:

```sh
uv run python -m gridlens.jobs.browse status
uv run python -m gridlens.jobs.browse rebuild
uv run python -m gridlens.jobs.browse maintain
uv run python -m gridlens.jobs.browse rollback --generation <retained-generation-UUID>
```

`rollback` refuses a generation with different canonical inputs, code policy or
expired clocks. It is not permission to serve obsolete qualification. Rebuilding
after a restart is idempotent. A failed or interrupted build preserves the
published pointer and leaves qualification pending if canonical inputs changed.

## Production activation gate

No production activation has been performed from the saved cloud environment.
It has GitHub access but no SSH directory/agent, DigitalOcean/Infisical token,
production database URL or production environment file. No credentials or access
were created. No production checksum or authenticated live-page verification can
be claimed from these local fixtures.

With the existing legitimate deployment identity available:

1. Record deployed SHA, current source/evidence/project/need counts and evidence
   checksum, timer/scheduler state, worker enablement and all spending limits.
   Keep collection/scheduling/autonomous research OFF and provider budgets zero.
2. Take the existing database backup and verify its receipt and restore path.
   Preserve the previous image/SHA and environment settings for rollback.
3. Apply `0021_saved_browse` after main's `0020_evidence_source_provenance`; run
   upgrade again and `alembic check`. PR72's conflicting 0020 stays separate.
4. Build once with the switch false; compare saved rows/ranks/groups/search against
   canonical reads on the retained corpus. Record checksum/counts unchanged.
5. Start the existing-code `browse` service using the `saved-browse` Compose
   profile. Its provider keys are empty, budgets zero and research/collection
   disabled. It is independent of the collection worker and scheduler.
6. Set `SAVED_BROWSE_ENABLED=true` for API recreation through the existing
   Infisical deployment wrapper. Preserve the disabled operating configuration.
   Test authenticated map/list, pages beyond 50, groups, exact detail, operator
   updates, pending/readback, process restart and persistence.
7. Measure real HTTP p50/p95/max, query counts, connection wait, payload bytes,
   database CPU/locks and process memory. The proposed API p95 <1s is a target,
   not production acceptance established by fixture timings.

For runtime rollback, set the switch false and recreate the API (or use the
recorded previous image). Leave the additive tables/migration in place. Stop the
profile's maintenance process if reverting the image. Do not downgrade/drop
canonical evidence, change network access, enable timers or spend providers.
