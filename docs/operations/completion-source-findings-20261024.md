# Source completion findings - 2026-10-24

## Outcome

The three reported outcomes do not currently establish a safe source-adapter code repair. Austin is an explicit bounded collection pause, Houston is a source-publication freshness failure, and TCEQ has one record-local rejection whose exact sanitized record diagnosis is not present in the supplied evidence. The sources remain partial/failed as reported. No budget, retry, cadence, admission, or rejection behavior was changed.

This diagnosis uses the read-only source outcomes summarized in `../../../audit-20261024/FINAL_REPORT.md` and `docs/operations/hardening-runtime-20261024.md`, plus the current adapter and worker code. No production query, source retrieval, provider call, or ingestion run was performed.

## Austin building permits

The audit records 1,000 fetched and parsed rows, 13 accepted, and a partial result because collection paused at the chain-job budget. `jobs/worker.py` persists `collection_paused_for_budget` and the explicit error `Collection paused at chain job budget`; `ingestion/structured_collection.py` continues through durable, bounded lanes using `collection_jobs_remaining`. The adapter itself also retains fixed page/run limits (`MAX_PAGES=20`, `MAX_RUN=20,000,000`) in `ingestion/adapters/socrata_permits.py`.

This is a policy-bound pause, not evidence of an adapter parse or pagination defect. Increasing the chain-job budget or scheduling an uncontrolled continuation would violate the packet. The actionable blocker is controller/owner disposition of the bounded backlog and authorized capacity; any continuation must retain the configured cap and remain visibly partial until all required lanes complete.

## Houston weekly permits

The audit reports `publisher_stale`, zero fetched rows, and zero parsed rows. The adapter checks the newest dated report listed by the official Houston index and raises a visible source error when that date is more than 30 days old. Existing focused tests explicitly cover this stale-listing branch. The reported result therefore indicates missing or stale publisher output, not a transport timeout or a valid empty report.

No source-side publication correction or newer official report is evidenced in the supplied packet. Retrying the same stale listing cannot repair the publisher gap, and removing the 30-day threshold would hide stale source health. The remaining blocker is an official publisher update or owner-approved source policy review backed by fresh source evidence; until then the source must remain stale/failed.

## Texas TCEQ NSR pending applications

The audit reports 328 fetched, 327 parsed, four accepted, and one record-local rejection. The adapter retains stable TCEQ project identity for row-local failures and emits `presence_only`, `partial_snapshot`, and structured rejection metadata; service processing selects `RecordLocalFailures` when partial acquisition includes rejected records. Existing tests verify that malformed received dates and missing permit data remain explicit row-local failures while valid siblings are preserved.

The controller's sanitized read-only receipt at `../../../completion-20261024/identity-source-read.json` (2026-10-24 21:56:39 UTC) identifies `TCEQ-406704`, permit `4381`, stage `tceq_document`, error `http_status_404`; only the permit is selected and the document body is omitted. This is a missing official Plain Language Summary response for one listed filing, not a listing parser failure. The adapter maps HTTP status to `http_status_404`, keeps the stable TCEQ identity as `presence_only` with `partial_snapshot`, and returns partial acquisition metadata. The existing focused test `test_retrieve_withholds_unsummarized_filings_and_reports_partial_failures` exercises 404 responses and asserts those failures remain visible; valid sibling records are retained. No code change is justified. The unresolved blocker is official availability of the summary document (or a separately owner-approved interpretation of that missing document); keep the record-local rejection visible and do not emit an unsited inferred record.

## Changes and validation

No adapter/parser code defect was verified, so no source code or regression test was added. No test suite was run for this diagnosis-only packet; the cited 404 test behavior is code inspection of an existing focused test, not a new test result. Controller-owned production evidence and any source-policy/capacity decision remain outside this worker's scope.
