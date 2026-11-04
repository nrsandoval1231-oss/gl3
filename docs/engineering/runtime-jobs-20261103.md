# Workstream 6: runtime jobs, nightly timing, document-source alerts

**Date:** 2026-11-04 · **Status:** shipped off. Nothing here calls a paid provider; every test provider is a fake. The [Autonomous Intelligence Canon](../product/AUTONOMOUS_INTELLIGENCE_CANON.md) is unchanged; this is runtime plumbing. Owner environment and the proposed schedule table are in the [environment proposal](../strategy/ws0-production-env-changes-20261103.md).

## What shipped

| Piece | Code | Default |
| --- | --- | --- |
| `document_extraction` job (discovery split) | `jobs/document_extraction.py`, `adapters/tceq_application_documents.py` (`ExtractionHooks`, `on_changed`) | off (`DOCUMENT_EXTRACTION_JOBS_ENABLED`) |
| Clock-time schedule (`run_at`, `run_weekday`) | `ingestion/registry.py`, `jobs/worker.py::_scheduled_instants` | absent from the registry |
| Document-source alerts | `jobs/document_alerts.py`, `ingestion/document_health.py`, `jobs/alerts.py` | on (read-only; silent when healthy) |
| First-signal sample, immutable `first_seen_at` | `intelligence/first_signal.py`, `persistence/models.py` | on |

No migration; `alembic check` reports no drift.

## Discovery and extraction jobs

### Flow with the flag on (TCEQ NSR pending)

1. The listing (`ingestion`) job runs the stage in discovery mode: for each in-scope filing it makes the same HEAD request as before and compares validators (ETag, Last-Modified, length) with the retained state. Unchanged, known-failed and backed-off documents are classified exactly as in-line. A **new or changed** document is queued as one `document_extraction` job instead of being downloaded. Wrong content type (`js_shell`, `wrong_content_type`), oversize and rate-limit outcomes of the HEAD are recorded as before.
2. The extraction job (same worker, same per-source admission and lease renewal as `ingestion`) re-checks the one document, downloads it (at most one request per second, 300 MB bound), unpacks the portfolio and runs the permit_docs pipeline: text layer in the killable child, then rules, then the optional passes in the parent process. The job holds a 600 s lease (renewed while it runs); the stage works to the lease deadline minus its persist reserve (120 s for one record), and the child's budget is `min(extract_seconds, time left - 50 s)`. The proposer and OCR passes run in the parent after the text layer and are **not** bounded by that child budget: they are bounded by their own provider call timeouts, the per-call and period caps, and the lease renewal, so a slow provider can extend a job past the stage budget. A document whose bytes hash to the retained `sha256` is recorded `unchanged_by_hash` and produces no new state.
3. The job is the **leased job context** for the model passes. `ExtractionHooks` carries `configured_proposer(...)` and `configured_stage_ocr(...)` built with the job id, worker id and fence, so every call reserves in the shared ledger. Both return `None` while `PERMIT_LLM_PROPOSER_ENABLED` / `PERMIT_OCR_ENABLED` are off, which is the default: the pipeline then runs rules only and the stored state has no `proposer` or `ocr` key (a test pins this). When a pass runs, its status and cap fields are stored on `document.extraction.proposer` / `.ocr`.
4. The finished state is the same dictionary the in-line stage produces, and for the same publisher sequence (new document, same bytes with refreshed validators, then a script shell) the folded record has the same `source_hash` and abstract at every step as the in-line stage (a test runs both). It is kept in the job checkpoint (`state`, `content_sha256`, `outcome`). On success the job requests a refresh of the listing job, coalesced: skipped while another extraction job for the source is still queued or running (that one asks when it finishes). The next listing run merges succeeded jobs' states that are strictly newer than the retained evidence state (`merge_pending`) and folds them onto the NSR record through the existing `apply_state`, so abstract, `source_hash`, provenance and `EvidencePackage` follow the in-line path. A finished job's state replaces the retained one when the job ended **after** that evidence was recorded (completion order, not the state's own fetch time, which an unchanged-bytes check or a failed attempt on an accepted document leaves old); an identical state is skipped, and an older job result never replaces newer evidence.

### Idempotency, retries, not-before, capped-out

- **Key.** `Job.target_id` is a UUIDv5 over source, project, URL and a digest of the publisher's validators. One document version has at most one live job; a new validator digest is a new job. Only a **decided** success blocks a re-queue (the stage settled the version: unchanged, unchanged by hash, known-failed, or a new state), and only while its state can still be loaded (30 days). A job that ended `succeeded` with `decided: false` (outcome `undecided_backed_off`, `undecided_deferred_deadline`, `undecided_no_decision`, `disabled`) and a `failed` job only **rest**: `rest_hours` after they ended (168 h for a backed-off document, matching the stage's seven-day rest, otherwise `DOCUMENT_EXTRACTION_FAILED_RETRY_HOURS`) the version is queued again. This closes the case where the fourth attempt of a repeatedly failing document finished as a no-op success and used up the version's key forever. With no validators the digest includes the date: at most one extraction per document per day. The content hash then decides, after download, whether the bytes are really new. Enqueueing locks the source row and commits per job, so the lock is not held across network calls. Each listing run creates at most `DOCUMENT_EXTRACTION_MAX_ENQUEUE_PER_RUN` jobs, which defaults to the stage's own `max_downloads` (versions that already have a job spend nothing; `deferred_enqueue_budget` counts the rest, and they are picked up on a later run).
- **Retries and backoff.** A retryable failure (network, timeouts, 5xx, environment limits) raises `DocumentExtractionRetry`; the worker's existing path requeues with jittered exponential backoff up to five attempts, then marks the job `failed` (counted in the daily alert's `document_extraction jobs`). The stage's own bookkeeping still rests a document for seven days after three counted attempts. Non-retryable failures (`js_shell`, `wrong_content_type`, `empty_text_layer`, ...) are stored as a failed state with `last_attempt`, as in-line.
- **Not before.** A publisher `Retry-After` (429/503) is saved as `application_documents_not_before` in source health, the same key the in-line stage uses. A job that starts before it, or meets a 429 itself, is requeued at that time **without spending an attempt**, and makes no request while waiting.
- **Capped-out.** If the proposer or OCR pass ends `capped_out`, the job checkpoint gets `capped_out: true`, `cap_state`, `cap_scope`, `cap_period`, `cap_reason`, `cap_pass`, and the near-cap alert counts it with the intelligence jobs (`recent_capped_out_jobs` now includes this kind). A capped-out pass is not retried for the same bytes: the document is decided (its rule-only state is folded) and a re-run would hit `unchanged_by_hash`. After a cap resets, those rows are picked up only when the publisher changes the document or an operator clears the retained state; this is deliberate so a cap cannot cause repeated paid attempts.

### Choice: what stays in-line

TCEQ is migrated behind the flag. The OK DEQ stage and the in-line TCEQ path are unchanged and never receive a proposer or OCR: the OK DEQ stage joins documents to listing rows through a probe frontier and key index that a single-document job cannot reproduce without a larger change. The seam is generic (`run_stage(..., on_changed=, hooks=)`); an OK DEQ adapter is the follow-up. There is no NMED document stage in this branch to migrate. With the flag off nothing changes: same HEAD, same download, same states, same hashes.

### Operating notes

- A document waits for the next listing run (queue), the job, then the next listing run (fold). The job's refresh request shortens the second wait to the next free worker slot. Unfolded states expire from the lookback after 30 days, after which the version is queued and extracted again rather than lost.
- If the flag is switched off while jobs are pending, queued jobs finish as `disabled`; states already stored stay unused and the in-line stage resumes.
- Job checkpoints hold the state (schedule text, line provenance, up to 100 supply rows): hundreds of KB at most per document, read back over a 30-day lookback.

## Nightly timing

`SourceScheduleEpoch` already anchors one local clock time per day (`schedule_mode: local_daily`, `timezone`, `schedule_anchor_time`) with whole-day cadences and a DST-safe slot function. It could not express two times a day or a weekday. Two optional registry fields close that, both interpreted in the source's timezone:

- `run_at`: one to four distinct `"HH:MM"` (or `HH:MM:SS`) local times per scheduled day. Requires a local-daily schedule.
- `run_weekday`: `0` Monday to `6` Sunday, with a whole-week `cadence_hours` (168, 336, ...).

Absent, a source runs on `cadence_hours` and the single anchor time as before (a test pins that). Validation is in `load_registry`. The fields are part of the schedule epoch configuration, so adding or removing them starts a new epoch through the existing mechanism. A nonexistent spring-forward time resolves to the first valid time after the gap and an ambiguous fall-back time runs once; both are tested. `jobs/worker.py` is the only scheduler code that changed. The registry itself was **not** changed; the proposed table is in the [environment proposal](../strategy/ws0-production-env-changes-20261103.md).

## Document-source health alerts

Each listing run, discovery run and extraction job appends a small summary (counts, failure and notice codes, extraction totals; no exception text) to `Source.health["document_stage"]["runs"]`, capped at 30 listing-kind and 30 job-kind entries separately so job runs cannot push out the listing baseline. Summaries count only documents fetched in that run (copies of an accepted state do not inflate `docs` or `verified_rows`), and job summaries carry no `in_scope`. The health read-modify-write takes the source row lock. The OK DEQ stage records counts only (no per-document states), so it gets `wrong_content_type`, `listing_shrink`, `overdue` and `zero_new_records` but not the yield, empty-text-layer or rejection-spike findings. The daily alert (`alerts.py`) evaluates them with `Observation.first_seen_at` and adds a line per finding; any finding makes the message urgent. A failure to compute them is itself a line (`document_check_failed`), never silence. `/api/health` and the generated web types are not touched.

| Code | Fires when | Setting |
| --- | --- | --- |
| `wrong_content_type` | any run in the last 24 hours (or one cadence, if longer) saw a web page or script shell (`js_shell`) or a non-PDF type instead of a PDF | none (any occurrence) |
| `empty_text_layer` | at least 3 recent documents (extracted, or failed as empty) and at least this share have no text layer; runs where every document was empty count | `DOC_ALERT_EMPTY_TEXT_RATIO` |
| `extraction_yield_drop` | verified rows per document in the last 3 active runs fell this far below the earlier baseline (the baseline needs enough documents) | `DOC_ALERT_YIELD_DROP_RATIO`, `DOC_ALERT_MIN_BASELINE_DOCS` |
| `verifier_rejection_spike` | the verifier rejected at least this share of candidate rows (minimum row count) | `DOC_ALERT_REJECTION_SPIKE_RATIO`, `DOC_ALERT_REJECTION_MIN_ROWS` |
| `listing_shrink` | the stage's `listing_shrink` notice, or in-scope filings below this share of the earlier maximum; judged on listing runs only (single-document jobs never feed it) | `DOC_ALERT_LISTING_SHRINK_RATIO` |
| `overdue` | no document-stage run for this multiple of `cadence_hours`; skipped when the registry has the source's document stage off | `DOC_ALERT_OVERDUE_MULTIPLIER` |
| `zero_new_records` | the source has retained records but none first seen in the last N days | `DOC_ALERT_ZERO_NEW_DAYS` |
| spend near cap | existing: `alerts.spend_report` (80% default) | `INTELLIGENCE_SPEND_ALERT_THRESHOLD` |

Source-level `Failed`/`Overdue` states and failed job counts were already in the message. Each finding names the numbers behind it.

## Timestamps and the first-signal sample

- **`first_seen_at`** (Observation) is set once at insert and never assigned by code. A SQLAlchemy `before_update` guard now raises if an ORM edit changes a loaded value, so a future code edit cannot overwrite it silently. The guard covers ORM edits of a loaded value only; it does not stop raw SQL, a bulk `UPDATE`, or an ORM edit of an object whose value was not loaded, and there is no database trigger (that would need a migration). Observations are never deleted.
- **`observed_at`** (Evidence) is set at insert for every evidence version; **`published_at`** is the publisher's date. TCEQ and OK DEQ state no publication date, so `published_at` stays `NULL` there by design (unknown is never filled from the fetch time), with `event_date` (application received / memo date) and `dates.published_at_basis` in the stored state as the explicit basis. Federal Register rows carry the publisher's `publication_date`. Tests cover TCEQ (and its changed-document replay) and Federal Register: all three timestamps present, tz-aware, first-seen preserved across a changed version. The OK DEQ replay was already covered. The Federal Register hp/driver sources named in the handoff are not in this branch; they use the same ingestion path, so the same columns are set.
- **First-signal sample.** `Observation.first_seen_at` is the retained record of when each source first observed each project; no new table was needed. `intelligence/first_signal.py::first_signal_sample` joins projects to their observation and earliest evidence (`first_evidence_observed_at`, `first_event_date`, `first_published_at`); `lead_time_days` compares against a later reference. `backend/scripts/first_signal_sample.py` prints it as JSON lines (read-only, internal, no UI, no workflow). Lead time needs the later reference (for example a press date) supplied offline.

## Verification

Added: `tests/unit/test_ws6_runtime.py` (schedule math including both DST transitions, weekday pinning, registry validation, every alert condition, summaries, job keys, pending-state precedence) and `tests/integration/test_ws6_runtime_jobs.py` on a disposable Postgres (discovery queues without downloading, idempotent enqueue, failed-version rest, end-to-end extraction and fold into evidence, ships-off pipeline, proposer/OCR wiring with fakes, not-before, 429 requeue, retryable raise, js_shell state, capped-out count, DB-driven findings, timestamps, immutable first-seen, first-signal sample). The existing TCEQ and OK DEQ ingestion tests run unchanged against the flag-off path.

Not verified: any live provider call (none allowed), a real nightly cycle, real TCEQ response shapes after the Aug-31 portal change, and the worker loop end to end with the new kind (the generic retry path is existing code; the new kind's processor is tested directly).

## Open risks

- The two-step fold means a new document reaches evidence on the listing run after its job; if the worker is down between, the state waits in the job checkpoint (30-day lookback).
- A job that exhausts five attempts is `failed` and rests 24 hours before the same version is queued again; the daily alert shows failed `document_extraction` jobs.
- `zero_new_records` can fire on a legitimately quiet source; the window is a setting.
- OK DEQ and the in-line TCEQ path still cannot use the proposer or OCR.
- A registry `run_at` change starts a new schedule epoch; verify the first night after applying.
