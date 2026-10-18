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

The global revision still fences every read. Ordinary operator fact capture,
accept/reject/correct/retract and workflow changes now refresh all needs in the
affected project **inside the canonical write transaction**. Unchanged rows are
copied by PostgreSQL into a new immutable generation; canonical evidence work is
limited to the changed projects. Global scalar grouping/counts are recomputed.
Readers see the previous complete generation before commit and the new complete
generation after commit, without an ordinary-edit pending interval. This still
copies population-sized JSON payloads and serializes publication; measure write
latency and contention as well as read latency.

The proven incremental whitelist is `power_needs`, `call_fact_versions`,
`call_fact_decisions`, and `need_workflow_status_events`. Row triggers journal both
old/new project scopes transactionally; every other relevant table and TRUNCATE
forces a full build. More than 100 dirty projects or 100 selected needs also falls
back to the full builder. Direct SQL scoped writes can commit pending until the
retained maintenance process (250ms poll plus work) refreshes them. Dirty revisions
are retained through local publications so a concurrent full builder can rebase a
bounded ordinary-write tail without losing already-published corrections. Only a
successful serialized full publication clears its covered journal entries.

A derived refresh error rolls back its savepoint while retaining the canonical
operator write and its invalidation. Unknown/broad writes, policy changes and
clock expiry require full rebuilding. During these periods browse returns HTTP
503 with qualification pending, `Retry-After: 5` and
`X-Qualification-State: pending`; no stale Lead is returned as current. An edit
crossing a clock boundary may commit with qualification pending. Unscoped detail
still reads current canonical inputs directly. These fallbacks have a materially
longer availability window than ordinary successful edits.

Expiry is the earliest UTC, Chicago or host-local date rollover, or a future
operator fact start/end instant. A build crossing its expiry cannot publish.
Publication compares the captured input revision atomically, or canonically
rebases a bounded scoped tail while holding the singleton publication lock. A separate advisory
lock permits one builder per database. Retention keeps the latest three derived
generations plus the published pointer if it is older; canonical evidence/history
is never deleted by maintenance. API browse transactions use repeatable read, so MVCC retains their immutable
cohort across statements while concurrent pruning and publication proceed.

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
It has GitHub access and connected DigitalOcean inventory access, which confirms
the active production droplet. That connector exposes no host command channel.
There is no SSH directory/agent, local DigitalOcean/Infisical token, production
database URL or production environment file. No credentials or access were
created. No production checksum or authenticated live-page verification can be
claimed from these local fixtures.

With the existing legitimate deployment identity available:

1. Record deployed SHA, current source/evidence/project/need counts and evidence
   checksum, timer/scheduler state, worker enablement and all spending limits.
   Keep collection/scheduling/autonomous research OFF and provider budgets zero.
2. Take the existing database backup and verify its receipt and restore path.
   Preserve the previous image/SHA and environment settings for rollback.
3. Apply `0021_saved_browse` and `0022_browse_clock_transitions` after
   main's `0020_evidence_source_provenance`; run
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
When reverting to an older image, recreate only the API with `--no-deps`; do not
run an older migration container against the newer 0022 revision. The simplest
rollback is the current image with the switch false.

## Prepared clock transitions (0022 follow-on)

Migration `0022_browse_clock_transitions` adds `valid_from` and one persisted
prepared-generation pointer. After the existing backup and switch-false gates,
apply upgrade/repeat/check and rebuild with the final runtime before activation.
No separate UI switch, scheduler, provider or infrastructure dependency is added.

The retained maintenance process prepares the next exact calendar/fact interval
within120 seconds of expiry. Canonical read evaluators use a context-local frozen
instant for qualification, accepted-fact effectiveness, research dates, buyer
freshness and ranking. Real publication, confirmation, authentication and lease
clocks are unaffected. A generation is eligible only in its half-open
`[valid_from, valid_until)` interval with matching input revision and policy.
Readers select the prepared pointer at the boundary without a maintenance poll;
restarts retain this ability. Maintenance later promotes it and can prepare the
next interval. Idle maintenance retains the original one-query freshness poll;
heavier preparation checks run only when pending or near expiry.

Every relevant committed SQL write clears preparation; rolled-back writes do not.
The invalidation trigger first promotes a candidate already effective according
to database time as the incremental base. Application-side `valid_from` checks
still reject future bases if the two clocks disagree. Any write while preparing
rejects publication rather than guessing its future effects. Pruning protects both
pointers. Generation rollback refuses a future interval.

This improves availability when preparation completes unchanged before expiry.
Repeated writes, short intervals, slow builds, process downtime, policy changes or
preparation failure can still require explicit pending/full rebuild. Broad/source
mutations remain the existing full-build fallback. No stale/future Lead is served
as current. Measure production HTTP behavior and clock agreement; fixtures are not
live acceptance. Keep collection/research/paid AI and scheduling disabled.

The runtime rollback remains the final image with the browse switch false. Keep
the additive0022 schema in place. If reverting to any older image, stop maintenance
and recreate only API/web with `--no-deps`; do not run an older migration container
against0022 or remove canonical evidence/history.
