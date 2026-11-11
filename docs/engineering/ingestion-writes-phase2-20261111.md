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

All numbers are single runs of `scripts/ingestion_write_benchmark.py` (300 records per phase, one run per size) in a 4 vCPU
container with Postgres 16, default fsync and a local database, so commits are cheap and there is no network latency.
Wall times carry roughly 10% noise. Rows marked "provisional" ran while other builders used the CPU. Raw JSON is under
`experience/benchmarks/`; commands and approximations are in `experience/benchmarks.md`.

**Shipped state, RRC drilling permits (structured collection path), before Phase 2 and at the final head:**

| Corpus | Phase | Before s | Before rec/s | After s | After rec/s | Speedup |
|---|---|---|---|---|---|---|
| 5k projects | all new | 124.1 | 2.42 | 22.1 | 13.58 | 5.6x |
| 5k projects | all unchanged | 1.5 | 196.84 | 1.9 | 158.88 | 0.8x (noise) |
| 5k projects | 5% changed | 2.8 | 108.43 | 2.3 | 133.26 | 1.2x |
| 50k projects | all new | 1044.0 | 0.29 | 25.4 | 11.82 | 41x |
| 50k projects | all unchanged | 1.7 | 174.92 | 1.6 | 189.24 | 1.1x (noise) |
| 50k projects | 5% changed | 7.4 | 40.50 | 2.5 | 120.28 | 3.0x |

All-new cost no longer depends on corpus size (22.1 s at 5k, 25.4 s at 50k). Statements per record are unchanged
(about 88), commits per record stay at 0.02 on this path and explicit row-lock statements stay at 12 per new record.

**Legacy per-record-commit path (Fort Worth permits via `process_job`, `commit=True`).** There is no pre-Phase-2
measurement of this source: its baseline was taken after Step 1 and before Step 3.

| Corpus | Phase | Baseline (after Step 1) s | Final s | Final rec/s | Commits per record |
|---|---|---|---|---|---|
| 5k | all new | 25.8 | 15.9 | 18.87 | 3.00 |
| 5k | all unchanged | 4.3 | 2.7 | 112.71 | 2.00 |
| 5k | 5% changed | 4.4 | 2.9 | 103.25 | 2.05 |
| 50k | all new | 137.9 | 20.7 | 14.48 | 3.00 |
| 50k | all unchanged | 4.8 | 2.3 | 128.90 | 2.00 |
| 50k | 5% changed | 12.4 | 3.4 | 88.10 | 2.05 |

The legacy gain at 50k comes from Step 2a (its trigger time was 79% of wall). Commits per record are still 3.0 because
batching ships off.

**By step (RRC all-new wall seconds):**

| Step | 5k | 50k | Basis |
|---|---|---|---|
| 0, baseline | 124.1 | 1044.0 | quiet |
| 1, indexed matching alone | 26.2 | 73.8 | provisional (other builders running) |
| 2a, index-driven statement-level triggers alone | 115.8 | 935.9 | builder run, without Step 1 |
| 1 + 2a | 24.0 | 26.2 | provisional |
| final head (Step 3 off, Step 4 analysis only) | 22.1 | 25.4 | quiet |

Step 1 removes the corpus-scaling matcher cost (about 14 minutes of ORM hydration at 50k). Step 2a removes the corpus-scaling
trigger cost (`dirty_browse_project` 113 s at 50k became 6 s; per-call cost about 0.3 ms at every size) but on its own moved
50k wall time only about 10% because the scans dominated; it matters once Step 1 is in.

**Step 2, set-based invalidation: delivered as 2a only.** The brief asked to remove the per-row `browse_state` lock so
concurrent writers do not queue. That cannot be done while the pinned test
`test_all_declared_input_tables_have_transactional_statement_triggers` requires every statement on a hot table (even a
zero-row one) to advance `browse_state.input_revision` visibly inside the writing transaction: seeing your own change to a
shared row means updating it, which holds its row lock until commit. The only lock-free design found assigns the revision
at commit time (a deferrable constraint trigger that merges an append-only journal and does the single `browse_state`
update at the end), which makes the revision visible only after commit, rewrites that pinned assertion, the
structural-fence and stale-since triggers' use of the in-transaction revision, and affects some of the roughly 237 test
references to `input_revision`. That is an owner decision (Step 2b) and was not attempted. Step 2a still takes one
`browse_state` lock per statement (not per row), and since the ORM writes one row per statement the lock count per record
is unchanged (about 21 calls per new record).

**Step 3, batch commits: implemented, default off, recommend dropping or deferring.** Gain is replay-only (unchanged
records 1.4 to 1.8 times faster, amended 8 to 22%); all-new is unchanged (24.9 s vs 25.8 s at 5k, 142 s vs 138 s at 50k)
and statements per record rise by 3 to 4. With a batch open, pursuit, owner-fact and need-status inserts that reference a
project or need wait for the batch (FK `FOR KEY SHARE` against ingestion's `FOR UPDATE`), the job row and `browse_state`
row are held for the whole batch, and lock-order deadlocks become more likely. The proposed narrowing to
`FOR NO KEY UPDATE` (`experience/benchmarks/step3-lock-narrowing.patch`) needs an existing test's text match changed, so it
was not applied; it also would not remove the `browse_state` wait. `INGESTION_BATCH_SIZE` therefore defaults to 1
(today's behaviour, verified identical by the critic). The first review found and this branch fixes a defect in batched mode
(a failed flush discarded the whole batch). Only the structured collection path (`commit=False`) and publisher RSS are not
affected by the setting.

**Step 4, bulk-skip unchanged records: analysis only, recommend dropping.** See the analysis below. An unchanged structured
permit already writes nothing to any record table and costs about 4.7 ms; a prefilter would cost about 0.04 ms per record,
a ceiling of roughly 4.6 s saved per 1,000-record segment and only for the proven-safe classes (older RRC amendments whose
evidence is retained, current rejected or regionally ineligible permits). Accepted-and-admitted permits, stale-evaluator
and elapsed-`review_after` records and all non-permit sources are not safe to skip. The real record-class mix is unknown.

**Finding outside this plan:** non-permit legacy sources (for example `federal-register-eis`) are not idempotent on replay:
each replay resets the interpretation to pending, re-interprets, grows `previous_decisions`, refetches the PDF and takes
about 3.7 commits per record.

**Not verified:** behaviour on Postgres 18 (CI) and on a remote database; migrations 0055 and 0056 at production table
size (0055 holds `ACCESS EXCLUSIVE` on `projects` during its backfill; run it with the worker stopped); real record-class mix;
concurrency under production load; WAL volume.

## Step 4 analysis

Analysis only; no skip is implemented. Method: code read of `process_records`
(`backend/src/gridlens/ingestion/service.py`, loop from about line 4085), plus an instrumented replay on a scratch
`*_test` database (alembic head, real triggers, 300 seeded projects, fixture records only, no network): the real
`process_job` (or `process_records` where stated) runs once all-new and then unchanged, capturing every statement
with SQLAlchemy `after_cursor_execute` (verb, table, `FOR UPDATE`/advisory lock, rowcount), a before/after dump of
every table keyed by primary key with `xmin`/`xmax` (xmin change = an UPDATE happened, including no-op UPDATEs; xmax
change with xmin unchanged = row lock only), `pg_stat_user_functions` and `pg_stat_user_tables`. The throwaway
scripts live outside the repository (`/var/tmp/s4_*.py`) and are not committed. Counts below are per record after
subtracting a fixed per-job overhead of 27 statements (collection-progress, source lock, timeouts); they match the
Step 0 baseline (13.1 statements and 5.03 lock statements per unchanged RRC record).

### 1. What an unchanged record does, per kind (measured)

Entry points: `process_records` is called from `_process_structured_collection_segment` (`commit=False`, line 2662),
from `process_job` for everything else (`commit=True`, line 2440) and from `research_evidence.retain_registered_record`
(single record, `commit=False`, `allow_model=False`, inside the caller's SAVEPOINT). `publisher-rss` does NOT reach
`process_records`; it uses `_process_collection_only` (line 5785).

| Kind (fixture) | Path | Stmts/rec | Reads / writes per rec | Row-lock stmts/rec | Content writes | Triggers fired |
|---|---|---|---|---|---|---|
| RRC drilling, current lane, accepted, interpretation current (20 rec) | structured, shortcut at line 4426 | 13 | 13 / 0 | 5 (obs, interp, jobs x3) | none | none |
| RRC drilling, older amendment, evidence already retained (20 rec) | structured, older branch line 4147 | 4 | 4 / 0 | 3 (obs, jobs x2) | none | none |
| RRC older amendment, FIRST sight of that amendment | same branch | 5 | 4 / 1 | 3 | 1 `INSERT evidence` | `dirty_browse_project` + `track_browse_stale_since` per evidence insert, `browse_state.input_revision` bump |
| RRC history lane (`historical_snapshot=True`): older seq and same-seq `daf420.dat` replay (20 rec) | same branch | 4 (+1 for new evidence) | as above | 3 | evidence insert only for the new amendments | as above |
| Socrata `austin-building-permits`, 5 accepted + 5 rejected (10 rec) | structured, shortcut | about 10 (accepted about 13, rejected about 7, derived) | 10 / 0 | about 6 / 4 | none | none |
| Boston CKAN, regional-excluded (8 rec) | structured, shortcut | 9 | 9 / 0 | 5 | none | none |
| RRC flare/vent, always rejected application evidence (8 rec) | structured, shortcut | 7 | 7 / 0 | 5 | none | none |
| Austin via `process_records(commit=True)` (10 rec) | legacy permit shortcut | 11 | 10 / 1 (`UPDATE jobs`) | 5 | none; `jobs.checkpoint` per record | none |
| `federal-register-eis` json-api, `commit=True`, 6 rec (3 with `pdf_url`) | non-permit full re-run | 17 (+PDF fetch x3) | 12 / 3 | about 9 | `interpretations.attempts+1`, `assessment` rewritten (`previous_decisions` grows by one each replay), `updated_at` | `dirty_browse_project` 2 per record, `browse_state.input_revision` bump |
| `publisher-rss` (`mjbizdaily-news`, 6 rec), `_process_collection_only` | not `process_records` | 11.5 | 10.5 / 1 (`UPDATE jobs`) | 9 (sources, interp x2, obs, jobs) | none; `jobs.checkpoint` per record, 2 commits per record | none |

Job-level writes of the structured path that exist regardless of record content: one `UPDATE jobs` (checkpoint =
`records[-1]` external id, line 2699), 2 to 3 `UPDATE source_collection_progress` (window, status, `last_attempt_at`,
`updated_at`, `completed_through`, `last_completed_at`) and 5 commits per run. `commit=False` means no per-record
commit, no per-record checkpoint and no lease extension (`_advance_job_lease` is under `if commit`). With
`commit=True` each record costs 2 commits and one `jobs` UPDATE.

Findings that matter for a skip:
- An unchanged permit record writes nothing to any record table in the structured path. The only avoidable cost is
  reads: about 13 statements, 5 `FOR UPDATE` row locks (they dirty heap pages and write lock WAL even though no
  value changes; WAL volume was not measured) and about 4.7 ms per record wall (3 repeats, 150 records, 5k projects:
  0.71, 0.69, 1.22 s). A read-only prefilter query for the same 150 records took about 5.5 ms in total, but see the
  classification: it can only remove part of the work.
- There is no `last_seen` column. `Observation` has only `first_seen_at`; nothing records "seen again".
- Absence detection is not fed by record processing. `reconcile_snapshot` (`intelligence/snapshot_presence.py`) is
  called once from `process_job` (line 2468) with `{record["document_number"] for record in retrieved}`, only for
  sources declaring `snapshot_complete`, which the registry restricts to three legacy sources
  (`georgia-air-draft-title-v`, `texas-tceq-nsr-pending`, `texas-tceq-temporary-batch-plants`). The structured
  sources (RRC, Socrata, Boston, flare) have no absence inference at all. Skipping a seen record therefore cannot
  change absence detection provided the `retrieved` id set is built from the full list, never from the post-filter
  list.
- `ProjectMatchDecision` is not written for an unchanged record: matching runs only when the project row is not
  found by `identity_key` (lookup at line 4688, matching in the `if project is None` block at line 5182), which is a first-sight or reassignment event. In the stale-evaluator replays
  below no match decision was written either.

### 2. When "unchanged" still triggers re-evaluation (measured)

`same_version` is `observation.content_hash == digest` (permit sources) or, for non-permit sources, that or equal
material fields. For permit sources the interpretation is reused only if ALL of these hold (line 4426): status in
{accepted, rejected}; `interpretation.content_hash == digest`; `interpretation.evaluator_version ==
permit_evaluator_version(record)`; `assessment.semantic_hash == digest`; `assessment.evidence_hash ==
evidence_digest`; `assessment.review_after` absent or not in the past (`date.today()`); and, for admitted accepted
records, the admission and need checks that follow. Otherwise the full path runs although `counts["unchanged"]` is
still incremented (it is incremented before the decision; the counter does not mean "nothing happened").

Measured with the stored `interpretations.evaluator_version` set older than the code constant (the code constant is
the version bump; there is no per-source setting):

| Kind | Stmts/rec unchanged-current | Stmts/rec stale evaluator | Result |
|---|---|---|---|
| RRC drilling (20) | 13 | 64 | 3 `UPDATE interpretations` per record (`attempts` 1 to 2, `assessment` with a `previous_decisions` entry, `evaluator_version`, `updated_at`), `browse_dirty_projects.revision` and `browse_state.input_revision` bumped, 16 lock statements per record, no `ChangeEvent`, no new evidence |
| Austin (10) | 10 | 35 | same shape |
| RRC flare (8) | 7 | 14 | same shape |
| Boston (8) | 9 | 16 | same shape |

Other triggers of re-evaluation on identical bytes, all taken from the code and pinned by tests (section 4):
- `review_after` elapsed: calendar time alone closes an event permit on a same-hash replay
  (`test_event_signal_closes_after_explicit_end_date_on_same_hash_replay`). Only the Austin-style event assessment sets
  `review_after`; every other assessment stores `None`.
- Interpretation missing, `pending` or `failed` (a prior crash or evaluator failure is retried only because an
  unchanged record re-enters the loop: `test_interpretation_failure_is_durable_and_retried_on_replay`).
- Non-permit sources never reuse an interpretation (except native FERC with a current native assessment): see the
  FR row above. Every replay resets the row to `pending`, re-interprets and rewrites the assessment.
- The accepted shortcut also repairs downstream state. Measured: setting one need's `admission_basis` to `{}` and
  replaying unchanged made the shortcut rewrite `power_needs.admission_basis` (and fire the browse trigger); a need
  set inactive was NOT reactivated (the shortcut does not reopen). The comment at line 4487 says the same shortcut
  rebuilds a missing equipment-demand package via `materialize_equipment_investigation`; that branch was not
  exercised (RRC fixtures produce no package) and is unverified here beyond the code and
  `test_unchanged_frozen_inputs_do_not_repeat_extraction`.
- Companion and PDF handling runs on unchanged records: `pdf_url` on a signal-eligible FR record is re-fetched on
  every replay (3 of 3 fetches in each of 3 replays) and a changed companion hash inserts new evidence while the
  observation stays "unchanged" (`test_pdf_representation_is_companion_evidence_not_a_second_discovery`).
  `record["companions"]` evidence is inserted if its hash is missing (line 4256). Application-document staging
  (`_enrich_with_application_documents`) runs in `process_job` BEFORE `process_records` for every record, so a skip
  inside `process_records` cannot save that network work.
- Evidence provenance alias merge: for an existing evidence row with non-empty `_source_link_provenance` (TCEQ NSR,
  CEQAnet, `nc-commerce`, retained/application/OK DEQ/NMED/early-signal documents) the incoming hrefs are unioned
  into `evidence.provenance` on an unchanged hash (line 4250, pinned by
  `test_adapter_href_provenance_survives_process_job_reopen_and_alias_replay`). RRC, Socrata, Boston, flare and FR
  produce empty provenance, so no write happens for them (confirmed by the trace).

### 3. Required effects and redundant effects of an unchanged record

REQUIRED (must still happen, or be provably moot, after a skip):
1. Lease/fence guard (`assert_fence`, `jobs ... FOR UPDATE`, 2 to 3.2 per record): a worker that lost its lease must
   not write. Any bulk write must be preceded by one `assert_fence` in the same transaction; `remaining_seconds(deadline)`
   likewise.
2. Counters in `counts`, which feed source health, attempt receipts and the schedule proof
   (`jobs/worker.py` lines 1218-1340, `jobs/source_schedule_proof.py`): `unchanged`, `permit_accepted`/`permit_rejected`
   or `regional_held`/`regional_excluded` (taken from the stored assessment), `older_amendments_retained`, and
   `latest_publication_date`, `earliest/latest_public_comment_deadline`, `latest_permit_issue_date`, which are computed
   from the record before the database is consulted. A skip must reproduce them exactly.
3. Checkpoint: structured path writes `records[-1]` once after the loop from the FULL record list (line 2699), so the
   prefilter must not shrink `records`; `commit=True` paths write `job.checkpoint` per record and extend
   `lease_until` (liveness; `_advance_job_lease`).
4. Evidence presence: `(observation_id, evidence_digest)` must exist or be inserted (also for older amendments, the
   only write of that branch); same for companions and provenance aliases (excludes every record carrying
   `companions`, `pdf_url` or non-empty source provenance).
5. Interpretation freshness decision (the conjunction in section 2, including `review_after` against today).
6. For accepted and admitted records, the repair checks: need exists and has current support, `admission_basis`
   current, equipment package present (these depend on OTHER observations that support the same need, so they cannot
   be decided from the record's own row).
7. Same-batch duplicates: two records with the same `document_number` in one batch are order dependent; a prefilter
   built on pre-batch state is only valid for ids that occur once in the batch.

REDUNDANT for an unchanged record that passes all checks above (no value changes, measured): the per-record
`observations FOR UPDATE` and `interpretations FOR UPDATE` row locks (they only serialize against concurrent writers,
see risks), the 2 to 3 repeated `assert_fence` reads after the first, the three `SELECT evidence` lookups for the same
row, `session.get(Source)` per record, and for rejected, regional-ineligible or older-amendment records the project,
need, support and package reads.

### 4. Classification

Shadow test (read-only prefilter reproduced in the throwaway script, compared with the real `process_records` run
record by record on 16 mixed RRC records: 4 unchanged, 3 stale evaluator, 3 older amendment with evidence, 2 older
amendment with new evidence, 2 changed, 2 `review_after` elapsed): every record the prefilter classified `SKIP`
(older amendment, evidence present) produced no insert, update or delete in any table apart from job and progress
bookkeeping; stale-evaluator and `review_after` records were correctly kept out; the four unchanged accepted records
were classified `CHECK` (not skippable without the support checks) and also wrote nothing. This is evidence for the
predicate, not a proof for production data.

| Kind | Classification | Condition / reason |
|---|---|---|
| RRC older amendment already retained (current or `issue_history` lane, incl. the stale same-sequence `daf420.dat` replay) | PROVABLY SAFE to skip | observation exists; incoming sequence greater than retained (or historical and same-seq stale by `amendment_snapshot_rank`); evidence `(observation_id, source_hash)` exists. Effects left: counters (`older_amendments_retained`, `unchanged`) and checkpoint. First sight of an amendment must stay on the normal path (it inserts evidence and fires the browse trigger). |
| Structured permit, unchanged, interpretation current, status `rejected` or stored regional scope not ELIGIBLE (flare is always rejected; Boston fixture regional-excluded; Austin non-power permits) | PROVABLY SAFE to skip | full conjunction of section 2, evidence present, no companions/`pdf_url`/provenance, id unique in the batch, `review_after` not elapsed. Writes nothing today, so the only effects to keep are counters and checkpoint. |
| Structured permit, unchanged, accepted AND admitted (RRC fixtures: 100% of records; real proportion unknown) | UNKNOWN, do not skip in Step 4 | writes nothing in the traced cases, but the shortcut contains cross-record repairs (`admission_basis` repair demonstrated; equipment package repair unexercised). A SQL-only predicate would have to re-implement `_need_has_current_support`, `_need_admission_basis_is_current` and the package key; keeping it per record (about 13 reads) is the safe option. |
| Structured permit with stale evaluator, `review_after` elapsed, missing/pending/failed interpretation, missing evidence | NOT SAFE to skip | re-evaluation is the intended effect (64 statements per record, interpretation history, browse invalidation). |
| Legacy `commit=True` permit methods not traced (Houston, Dallas, El Paso, Georgia, TCEQ NSR/batch, CEQAnet, MA cultivation, OK DEQ, NMED, ERCOT, ...) | UNKNOWN | they share the permit shortcut, but add companions, application documents (fetched before `process_records`), alias provenance merges, 2 commits and a checkpoint/lease write per record, and 3 of them use `snapshot_complete`. Only Austin was traced under `commit=True`. Exclude from Step 4. |
| Non-permit legacy methods (`federal-register-eis`, `nc-commerce`, Taylor, retained documents, early-signal) | NOT SAFE | no interpretation reuse: every replay increments `attempts`, rewrites `assessment` (history grows without bound), refetches companions/PDFs and may reach `adjudicate_signal`. State after a skip would differ, and companion refresh would be lost. Any change here is a behavior change that needs its own decision, not a performance step. |
| `publisher-rss` | OUT OF SCOPE | different function (`_process_collection_only`); unchanged records already write only the per-record checkpoint, but cost 2 commits and 8 to 9 lock statements per record. |
| `research_evidence.retain_registered_record` | NOT APPLICABLE | one record inside the caller's SAVEPOINT; the caller reads the post-call interpretation and evidence. Put the prefilter in `_process_structured_collection_segment`, never inside `process_records`. |

Honest sizing: the unchanged phase is already about 5 ms per record (benchmark: 1.5 s per 300 records). A segment is
bounded at 1000 records, so the ceiling for skipping is about 5 s per segment, and only for the SAFE classes. How many
production records fall in them (older amendments in the history lane, rejected permits) is not measured. Step 4's own
rule applies: if the measured gain on the SAFE classes is not material, drop the step.

### 5. What a prefilter would need (if the step proceeds)

1. Scope: structured segments only (`_process_structured_collection_segment`), behind a setting that defaults to off.
   One set-based read: `observations o LEFT JOIN interpretations i` for `(source_id, external_id = ANY(ids))` returning
   `o.id, o.content_hash`, the retained amendment sequence (`substring(abstract ...)`, NULL means do not skip),
   `i.status, i.content_hash, i.evaluator_version`, and from `assessment` `semantic_hash`, `evidence_hash`,
   `review_after`, `regional_scope.status`, `decision`; plus one `evidence` read for `(observation_id, content_hash)`.
   Evaluator version comes from `permit_evaluator_version(record)` in Python (it depends on `permit.source_type`).
2. Decide skip only on the SAFE classes of section 4; everything else goes through the unchanged loop. The input
   `records` list and the `retrieved` id set stay intact; the checkpoint uses `records[-1]`.
3. Reproduce counters exactly (a table of counter increments per skip class; test by comparing the whole `counts`
   dict with the unskipped run).
4. One `assert_fence` + `remaining_seconds` before the skipped group; keep a lease-safe cadence by processing skipped
   groups in bounded chunks. If row-lock parity is wanted, take one set-based `SELECT ... FOR SHARE` on the matched
   observation ids `ORDER BY id`; note this changes lock order relative to the per-record loop.
5. Exclusions inside the predicate: `companions`, `pdf_url`, non-empty `_source_link_provenance`, duplicate ids in the
   batch, `historical_snapshot` same-sequence records whose rank cannot be proven stale, sources with
   `snapshot_complete`.

Risks: (a) read-then-skip without a row lock changes behavior only under a concurrent writer to the same observation
(for example a research refresh); the current loop would block and, on a hash mismatch, overwrite with the incoming
content, the skip leaves the concurrent change. Not testable serially, not tested. (b) Classification drift: the
predicate duplicates the shortcut conjunction; a new condition added to line 4426 without the prefilter would
silently skip. Mitigation: factor the conjunction into one function used by both, plus the equivalence test below.
(c) Locks taken inside triggers and WAL volume are invisible to this analysis. (d) Real corpus mix unknown. (e) Only
synthetic fixtures were traced; no live source, retained or production data.

### 6. Equivalence check design and existing pins

Equivalence test (integration, scratch `*_test` database cloned with `CREATE DATABASE ... TEMPLATE` so both runs
start from the same state): build a varied batch (unchanged accepted, unchanged rejected, stale evaluator,
`review_after` elapsed, older amendment present and new, changed, new, duplicate ids, companions, alias provenance),
run it with the skip disabled and enabled, then compare (1) the complete `counts` dict, (2) every table's rows keyed by
primary key with `to_jsonb(row)` minus an allow-list, and (3) `xmin` of `observations`, `interpretations`, `evidence`,
`power_needs`, `projects`, `project_material_states`, `change_events` rows of skipped records equal before and after
(no row version created; `xmax` may differ because row locks are the intended difference). Allowed to differ:
`jobs.lease_until` and `jobs.updated_at` (time), `source_collection_progress.updated_at/last_attempt_at/last_completed_at`
(time). Must be identical: `jobs.checkpoint`, `source_collection_progress.window_*/status/completed_through/cursor`,
`browse_state` counters and `browse_dirty_projects` (an all-unchanged run bumps none today), sequence values, and
`source.health`. Measured today for an all-unchanged structured run, the only columns that change are
`jobs.checkpoint` and the collection-progress timestamp/window columns; no record-level timestamp moves.
Add a per-record variant (as in the shadow test) so a failure names the record class.

Tests that already pin unchanged-record behavior (grep of `tests/` for unchanged, replay, idempotent, same hash; the
first 11 plus 8 below were run green in this worktree on a `create_all` test database):
- `tests/integration/test_ingestion.py`: `test_replay_versions_and_withdrawal_preserve_evidence`,
  `test_permit_assessment_replay_correction_and_deactivation` (stale evaluator `permit-project-v4` re-evaluated on an
  unchanged row, history kept), `test_permit_v5_rejected_to_v6_clause_recovery_and_replay`,
  `test_event_signal_closes_after_explicit_end_date_on_same_hash_replay` (`review_after`),
  `test_interpretation_failure_is_durable_and_retried_on_replay`,
  `test_pdf_representation_is_companion_evidence_not_a_second_discovery`,
  `test_complete_pdf_notice_is_durable_and_same_hash_excerpt_is_immutable`,
  `test_prior_candidate_hash_replays_without_a_migration_or_duplicate_evidence`,
  `test_same_version_reclassification_deactivates_unsupported_need_idempotently`,
  `test_same_version_context_reinterpretation_preserves_source_display_fields`,
  `test_rrc_amendment_rollover_history_no_duplicate_asset_or_inferred_production` (older amendment and
  `historical_snapshot`, `older_amendments_retained`).
- `tests/integration/test_collection_only_ingestion.py` (RSS replay, same-hash reassignment, news duplicate
  correction), `test_feed_link_provenance.py` (alias merge on same-version replay), `test_snapshot_presence.py`
  (absence recorded once, only declared snapshots), `test_structured_collection_recovery.py` and
  `test_structured_collection_adversarial.py` (checkpoint/progress), `test_acquisition_transaction_boundaries.py`
  (commit and fence boundaries), `test_equipment_intelligence.py::test_unchanged_frozen_inputs_do_not_repeat_extraction`,
  `test_ferc_equipment_ingestion.py::test_ferc_native_replay_reinterprets_stale_cached_evaluator`,
  `test_taylor_ingestion.py` replay tests.
- Gaps: no test asserts statement counts, row locks, `attempts`/`previous_decisions` growth on replay, counter
  completeness for a mixed batch, or that an unchanged accepted RRC record leaves `admission_basis` untouched or
  repaired; none covers a mixed batch of all classes at once (the equivalence test above would be new).

Not verified: sources not listed in the section 1 table (all other `commit=True` permit and document sources),
equipment-package repair on an unchanged record, behavior under concurrent writers, WAL/page-dirtying savings, and any
real-data class mix.
