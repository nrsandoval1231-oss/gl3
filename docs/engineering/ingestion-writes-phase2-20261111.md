# Faster ingestion writes (performance Phase 2), 2026-11-11

Owner-authorized 2026-11-11 as one draft PR on `perf/phase2-ingestion-writes`, cut from `main` after Phase 1
(schemas 0052-0054, serve-stale fences). No merge, deployment, retained or production data, live publishers, paid
providers or credential changes. Out of scope: in-place snapshot updates, precomputed account groups, JSON-to-column
promotion, search indexes on browse rows, parallel job lanes, concurrent fetching, a connection pooler (Phases 3-4).

The existing `scripts/ingestion_performance.py` measures read-only API latency, not ingestion writes, so Step 0 adds
a write-path harness rather than extending it.

## Rules for every step

- One commit per step so any step can be reverted alone. Existing recovery and idempotency tests pass unmodified; if
  one must change, stop and explain first. Never weaken, skip or delete an assertion.
- Matching decisions, evidence provenance, privacy/suppression, retries, idempotency and provider accounting do not
  change. A step with no measurable gain is dropped, not shipped.
- Gates after each step: `pytest tests/unit -n 4`, `pytest tests/integration -n 4`, `alembic upgrade head`,
  `alembic check`, downgrade and re-upgrade of new migrations, `ruff check`, `ruff format --check`, `mypy src`,
  `npx tsc --noEmit`, Playwright regression, docs link check.

## Acceptance criteria

**Step 0, baseline.** `scripts/ingestion_write_benchmark.py` seeds a disposable `*_test` database at about 5k and 50k
projects and runs a synthetic source (RRC drilling permits through the real `process_job`; fixture payloads only) as
(a) all-new, (b) all-unchanged, (c) 5% changed records. It reports wall time and records per second; commits,
statements and explicit row-lock statements per record; and time inside browse-invalidation trigger functions from
`pg_stat_user_functions` with `track_functions = all`. Numbers are committed in `experience/benchmarks.md`; anything
that cannot be measured is stated.

**Step 1, indexed project matching.** Every unfiltered `select(Project)` on an ingestion path is replaced by an
indexed candidate query (exact identity keys first, then normalized name/site keys). An equivalence test runs the
retained full-scan matcher and the new matcher over a varied synthetic corpus and asserts identical
`ProjectMatchDecision` output; any difference widens the candidate query. Migration follows the 0053 conventions.

**Step 2, set-based browse invalidation.** `dirty_browse_project` becomes statement-level with transition tables and
no per-row `browse_state` lock. Readers never see a generation current while a committed write is newer; Phase 1
fences (full-scope, deletion, deactivation, `stale_since`) behave as before; scoped refresh learns every dirty
project including on DELETE and TRUNCATE. A concurrency test shows two sessions writing different projects both
commit without one waiting on the other and both projects reach the dirty set.

**Step 3, batch commits.** `process_records` commits once per batch (setting, default 200) with a SAVEPOINT per
record. Tests prove: resume after a mid-source crash without duplicate or lost evidence; lease loss mid-batch aborts
without partial publication; retained evidence survives a later enrichment failure; idempotent replay adds no rows;
provider accounting and usage ledgers are unchanged. API writes are not blocked for a whole batch.

**Step 4, bulk-skip unchanged records (only if Steps 1-3 are green).** First document what an unchanged record still
triggers and which effects are required; skip only the record kinds where that is provably safe, and list the rest.
An all-unchanged run leaves the database identical to the current code apart from timestamps meant to move.

## Results

Filled in per step below as each lands.
