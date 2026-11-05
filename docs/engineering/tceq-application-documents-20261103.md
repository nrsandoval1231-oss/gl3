# TCEQ application documents (workstream 1b)

**Date:** 2026-11-03 (revised after independent review) · **Code:** `backend/src/gridlens/ingestion/adapters/tceq_application_documents.py`, `tceq_portfolio.py`, `tceq_pi1_workbook.py`, `ingestion/tceq_document_stage.py` · **Stage version:** `tceq-application-document-v1`

This is the fetch half of workstream 1 in the [ingestion handoff](../strategy/ingestion-handoff-20261103.md). It feeds the offline extractor from [workstream 1a](permit-document-extraction-20261103.md) with TCEQ application files and writes the result through the existing ingestion service, so `equipment_intelligence` reads it unchanged. **It ships disabled.** No deployment, credential, paid provider, migration or production data was touched. Operation against the live site is shown only by the one-off smoke summarised at the end, which is not evidence that the stage works in production.

## What it does

For each in-scope pending NSR filing the stage checks the `{project}-ac.pdf` or `{project}-tc.pdf` application file, downloads it only when it is new or changed, unpacks the PDF Portfolio, reads the composite PDF with the 1a extractor and the PI-1 workbook for unit types, and attaches the result to the filing's existing NSR record.

1. **Discovery.** The stage works on the records the NSR adapter already built from the listing. In scope means the adapter's own `RELEVANT_NAME` test on applicant and facility. Admission remains the domain layer's decision. Only an exact `…/applications/{digits}-(ac|tc).pdf` path on `www.tceq.texas.gov` whose number equals the project is accepted. The plain-language-summary path and its tests are unchanged.
2. **Check, then fetch.** One `HEAD` per document. If the stored ETag matches, or the stored Last-Modified and length both match, the document is skipped. Otherwise `GET`, streamed to a temporary file with a running SHA-256, never held in memory. The `GET` response headers are compared with the accepted and failed states before any body is read, so a host that rejects `HEAD` (405/501) does not re-send an unchanged file; with no usable validators the content hash decides. Redirects may move host or path but never to another project number or kind.
3. **Unpack.** The outer file is parsed in a spawned child, killed at a time bound, with an address-space cap on POSIX. Embedded files are enumerated, size-checked, hashed and written under generated names inside one temporary directory. Names from the PDF are sanitised for display only. Type follows content and extension together. Unknown types are listed with name, size and hash, then ignored; they still count toward the total-size cap. Nothing is executed.
4. **Extract.** The first non-"READ THIS FIRST" PDF goes to `extract_permit_document` with `company` set to the applicant, `facility` omitted (the NSR abstract already has the one `Facility:` header) and `as_of` set to the listing's received date. Up to two PI-1 workbooks (latest first) with a `Unit Types - Emission Rates` sheet are read in a killable spawned child (read-only, `data_only`, address-space cap on POSIX).
5. **Write.** The result is folded into the NSR record and stored as `Observation`/`Evidence` exactly as before.

## Time budget

The job lease is 600 s and the worker uses it as the job deadline. The stage must never spend the time that ordinary persistence (`process_records`, snapshot reconcile) needs, or the whole NSR run would fail and repeat daily.

- The stage works to its own deadline: job deadline minus a persistence reserve of `max(120 s, 60 s + 0.5 s per listing record)`, capped at 300 s.
- A `HEAD` can block for the 60 s read timeout, so none starts with less than 70 s of stage time left. No download starts with less than 240 s left.
- Each child (unpack, extraction, workbook) is bounded by `min(its own constant, stage time left − 30 s margin − 20 s start-up grace)`; a step with too little time left is deferred, not started. Downloads stop at the stage deadline.
- Deferred work keeps the retained state and is retried next run. An extraction budget cut short by the deadline is retried without spending a retry attempt.

## What is stored

| Field | Content |
| --- | --- |
| `Evidence.abstract` | The existing NSR abstract, plus (only when verified rows exist) the 1a `schedule_text`: `Company:`, `As of:` and `Equipment ID: …` lines. A document with no verified demand rows leaves the abstract as it was. |
| `Evidence.provenance["application_document"]` | The document state: URL, kind, SHA-256, size, validators, fetch time, portfolio manifest (name, size, SHA-256, kind, status, role), extraction summary, per-line provenance, supply rows, workbook summaries, `abstain`, `last_attempt`, `dates`. |
| `Evidence.extraction_location` | The listing row plus the embedded file name and page range, clipped to 100 characters. |
| `Evidence.published_at` | Unchanged (null). TCEQ states no publication date; Last-Modified is a validator only. |
| `Evidence.observed_at`, `Observation.first_seen_at` | Database defaults. First-seen is never updated. |
| `source_hash` | The base NSR hash combined with a digest of the document state that excludes fetch time. |

Per-line provenance has page, offsets, quote, document hash, verifier (`exact-span-v1`), field quotes and the line bounding box from 1a, plus `embedded_file` and `outer_sha256`. Offsets index the canonical text of the embedded composite PDF, rebuilt from the same bytes when a span must be checked; the canonical text is not stored.

**Size.** A state with no rows is about 6 KB. With the bounded samples below, large permits measured 85 KB (528 pages) in the smoke test, and 100 to 300 KB is the realistic range for a large filing (at most 120 schedule lines of about 1 KB each, 100 supply rows with quotes cut to 160 characters, up to 25 sample units per workbook and two workbooks). It lives in JSONB provenance, one copy per evidence version.

**Supply is separate.** Engines, turbines, generators and every row without a stated electric drive go to `extraction.supply` and the workbook summaries, never to the abstract. A portfolio of generators produces no schedule lines and an explicit `abstain: "no equipment schedule found"`: an abstention, not zero demand.

**Workbook facts are `documented` listings.** Distinct FINs by the applicant's unit-type family with sheet and cell (counts for every unit, a sample of 25 in provenance), quoted description sentences, and the counts and MW they state. A row can stand for several physical units and a stated MW is usually generation, so these are context only. No rating field is ever produced.

## Bounds

| Bound | Value |
| --- | --- |
| Request rate | at most 1 per second, including HEAD, GET and each redirect hop; user agent `GridLens public source reader/1.0` |
| Hosts and path | exact `www.tceq.texas.gov`, HTTPS, no query, exact `applications/{n}-(ac\|tc).pdf`; public DNS pinned; 3 redirects, each re-validated and bound to the same project and kind |
| Outer file | 300 MB, by Content-Length and by running count |
| Content check | `application/pdf` only; HTML/script/markup is `js_shell`; first bytes must be `%PDF-` |
| Embedded files | 64 files, 128 MB each, 512 MB total (ignored types count); pypdf stream limits set explicitly to 128 MB |
| Children | unpack 240 s, extraction `extract_seconds` (registry), workbook 60 s, each also cut to the stage time left; POSIX `RLIMIT_AS` 2 GiB (unpack), 1 GiB (workbook); **Windows has no equivalent, so there only bytes, counts and the kill timer bound a child** |
| Workbooks | 2 parsed per document, 64 MB each, 400 MB uncompressed zip, 2,000 members, macros refused |
| Per run (registry) | `max_checks` HEADs, `max_downloads` downloads; stage stops on the first 429 or 503 |
| Retries | environment failures: 3 counted attempts, then 7 days' rest unless the validators change |

## Failure classes

Real failures are rejection records (stage `tceq_application_document`, a `[a-z0-9_]` code, only codes and small integers as fields; exception text and response content are never stored) in the job's `rejected_records`. The job then reports `partial` with `parse_failures` and the stage counts under `application_documents`. Deliberately, `collection_status` is **not** set: that status drives the source's rate-limit cooldown and retry scheduling, which belong to the listing, and an optional stage must not move them. The listing is processed and its snapshot reconcile runs regardless.

**Notices are not failures.** `zero_verified_rows` and `listing_shrink` are listed under `application_document_notices` and never set `partial` or `parse_failures`.

| Code | Meaning | Handling |
| --- | --- | --- |
| `js_shell`, `wrong_content_type`, `not_pdf_signature`, `oversize`, `embedded_oversize`, `no_composite_pdf`, `unreadable_stream`, `encrypted`, `empty_text_layer`, `text_layer_too_large`, `text_layer_too_many_pages`, `text_layer_unreadable`, `text_layer_encrypted`, `url_policy` | a property of the file or URL | remembered with the response validators and hash in the state's `last_attempt`; not fetched again until they change |
| `text_layer_time_budget`, `text_layer_memory_limit`, `text_layer_page_too_long`, `text_layer_worker_failed`, `unpack_time_budget`, `network_error` (including DNS failure), `acquisition_timeout` | environment limits | retryable; nothing is written to evidence; attempts and time are kept in source health (`application_documents_attempts`), 3 counted attempts then a 7-day rest unless the validators change; a budget cut short by the job deadline does not count |
| `http_status_429`, `http_status_503` | the publisher is throttling | the stage stops at once; `Retry-After` (bounded to 7 days) is reported as `application_documents.retry_after_seconds`; if the listing acquisition itself was rate-limited the stage is skipped with no requests |
| other `http_status_*` | transport | 408, 425 and 5xx retryable; HEAD failures never write a marker |
| `zero_verified_rows`, `listing_shrink` | notices | recorded in the state and the notice list |
| `stage_error` | unexpected fault in the stage | reported by exception class only; every retained state stays on its record |

**Previous accepted state survives failure.** A failure never replaces an accepted `document`. A transient failure changes nothing in the evidence hash. A validator-matched unchanged result clears any stale failure note. Workbook failures are counted under `application_documents` and kept in the state, not raised as document failures.

**Order and starvation.** Never-tried documents go first, then accepted ones, then those with failed attempts, newest first within each, so a permanently failing filing cannot take the download budget from others.

## Running it and operating limits

- The stage runs inside the existing `texas-tceq-nsr-pending` job, after retrieval and with no transaction or source lock held, then retakes the source lock. It is controlled by `query.application_documents` in `config/sources/registry.v1.json`, which ships with `"enabled": false`; the stage does not run unless that is `true`. Turning it on is a registry change through the protected release: see [source activation](../strategy/ws0-production-env-changes-20261103.md#source-activation-registry-change-not-an-environment-variable).
- **Admission hold.** The job holds the global public-acquisition admission for its whole run, so while the stage works (up to the lease, about 600 s) no other public source starts. A normal listing run is seconds. Plan the schedule with that in mind and watch the first enabled runs.
- Discovery and extraction are separable: `discover`, `head_document`, `download_document`, `build_state` and `apply_state` take no database; `tceq_document_stage.py` is the only database glue. Splitting extraction into its own queued job (workstream 6) means calling `build_state` from a job instead of `run_stage`.
- At two downloads a day and a 24-hour cadence a large pending set takes many days to cover.
- **Memory.** The outer file streams to disk; the unpacked composite is read into memory once (up to 128 MB) and again in the 1a child. POSIX children have address-space caps; Windows does not.
- **Known size gap.** A composite over 128 MB is reported as `embedded_oversize`. In the ten-file spike one (399049) is above that.

## Limits

- Only the first composite PDF is extracted; other embedded PDFs are listed in the manifest as `pdf_not_extracted`.
- Extraction recall is 1a's: electric-drive evidence is rare and most filings describe on-site generation, so supply rows and no schedule is the expected common result.
- Scanned pages are counted (`needs_ocr_pages`) and not read.
- `listing_shrink` is a heuristic over projects that already have an accepted state.
- A project moving from AC to TC is a new URL with no prior state.

## What was tested

- Unit tests with synthetic PDF portfolios and a mock origin (no network): unpack, hostile names and sizes, content-type and shell detection, pacing, redirect policy, change detection, typed failures, retry and back-off, rate-limit abort, evidence shape, time-budget cuts.
- DB-backed tests on a disposable PostgreSQL: a stated electric compressor schedule through `process_records` to an equipment `EvidencePackage`; a generator-only portfolio producing supply and no demand; replay; changed bytes producing a second evidence version with first-seen kept and the earlier evidence preserved; failure keeping the accepted schedule; a finite job deadline with a slow extractor still persisting the listing; a rate-limited acquisition making no document requests.
- Offline on ten real downloaded files from the spike, and one dated live smoke (below).

### One-off live smoke, 2026-11-03 (not proof of operation)

At most one request per second, files kept outside the repository. The listing had 313 rows; 7 were in scope by name (4 AC, 3 TC), all with links. Four of those projects were sampled:

| Project | Pages (scanned) | Verified rows | Schedule lines | Supply rows | Workbook units (parsed) | Outcome |
| --- | --- | --- | --- | --- | --- | --- |
| 407086 | 232 (23) | 0 | 0 | 0 | 25 | abstained (`zero_verified_rows` notice) |
| 404507 | 528 (63) | 11 | 0 | 3 | 227 | abstained, supply only |
| 400428 | 976 (29) | 53 | 0 | 6 | 203 | abstained, supply only; 171 s alone, but `text_layer_time_budget` under CPU load in the first run (the per-page bound was then raised from 20 s to 60 s) |
| 399766 (offline) | 424 (13) | 6 | 0 | 3 | 16 | abstained, supply only |

No electric compressor or pump schedule was found in any of them. The smoke shows that real portfolios unpack and extract within the bounds on one machine; it shows nothing about scheduled operation, source breadth, or demand yield.
