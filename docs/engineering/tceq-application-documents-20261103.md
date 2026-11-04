# TCEQ application documents (workstream 1b)

**Date:** 2026-11-03 · **Code:** `backend/src/gridlens/ingestion/adapters/tceq_application_documents.py`, `tceq_portfolio.py`, `tceq_pi1_workbook.py`, `ingestion/tceq_document_stage.py` · **Stage version:** `tceq-application-document-v1`

This is the fetch half of workstream 1 in the [ingestion handoff](../strategy/ingestion-handoff-20261103.md). It feeds the offline extractor from [workstream 1a](permit-document-extraction-20261103.md) with real TCEQ application files and writes the result through the existing ingestion service, so `equipment_intelligence` reads it unchanged. Nothing here is a release: no deployment, credential, paid provider, migration or production data was touched, and no live source coverage is claimed beyond the smoke test reported at the end.

## What it does

For each in-scope pending NSR filing the stage checks the `{project}-ac.pdf` or `{project}-tc.pdf` application file, downloads it only when it is new or changed, unpacks the PDF Portfolio, reads the composite PDF with the 1a extractor and the PI-1 workbook for unit types, and attaches the result to the filing's existing NSR record.

1. **Discovery.** The stage works on the records the NSR adapter already built from the listing. In scope means the adapter's own `RELEVANT_NAME` test on applicant and facility (data center, digital, compute, hyperscale, electric generating, power plant/station/generation, generating unit, EGU, peaker). Admission remains the domain layer's decision. The AC/TC link is the listing's `application` link. Only an exact `…/applications/{digits}-(ac|tc).pdf` path on `www.tceq.texas.gov` whose number equals the project is accepted. The existing plain-language-summary path and its tests are unchanged.
2. **Check, then fetch.** One `HEAD` per document. If the stored ETag matches, or the stored Last-Modified and length both match, the document is skipped. Otherwise `GET`, streamed to a temporary file with a running SHA-256, never held in memory. If the hash equals the stored hash the document is unchanged (only the validators are refreshed). A server that rejects `HEAD` (405/501) falls back to `GET` plus hash comparison.
3. **Unpack.** The outer file is parsed in a spawned child that is killed at a time bound. Embedded files are enumerated, size-checked, hashed and written under generated names (`emb-000.pdf`, `emb-002.xlsx`) inside one temporary directory. Names from the PDF are sanitised for display only. Type follows content (`%PDF-`, `PK`) and extension together. Unknown types are listed with name, size and hash, then ignored. Nothing is executed or opened with an application.
4. **Extract.** The first non-"READ THIS FIRST" PDF (the composite) goes to `extract_permit_document` with `company` set to the applicant, `facility` omitted (the NSR abstract already has the single `Facility:` header the parser needs) and `as_of` set to the listing's received date. Up to two PI-1 workbooks (latest submission first) with a `Unit Types - Emission Rates` sheet are read with openpyxl in read-only, `data_only` mode.
5. **Write.** The result is folded into the NSR record. The service stores it as `Observation`/`Evidence` exactly as before.

## What is stored

| Field | Content |
| --- | --- |
| `Evidence.abstract` | The existing NSR abstract, plus (only when verified rows exist) the 1a `schedule_text`: `Company:`, `As of:` and `Equipment ID: … | Type: … | Drive: electric | Rating: … | Count: … | State: …` lines. A document with no verified demand rows leaves the abstract exactly as it was. |
| `Evidence.provenance["application_document"]` | The document state: URL, kind, SHA-256, size, ETag/Last-Modified/length validators, fetch time, portfolio manifest (each embedded file: sanitised name, size, SHA-256, kind, status, role), extraction summary, per-line provenance, supply rows, workbook summaries, `abstain`, `last_attempt`, `dates`. |
| `Evidence.extraction_location` | The listing row plus the embedded file name and page range, for example `…; 1-399766-ac.pdf pp.211-214`, clipped to the 100-character column. |
| `Evidence.published_at` | Unchanged (null). TCEQ states no publication date. Last-Modified is kept as a validator, not promoted to a publication date. |
| `Evidence.observed_at`, `Observation.first_seen_at` | Database defaults. First-seen is never updated by ingestion. |
| `source_hash` | The base NSR hash combined with a digest of the document state that excludes only fetch time. A re-run over unchanged bytes is therefore `unchanged`; changed bytes make a new evidence version. |

Per-line provenance has the page, offsets, quote, document hash, verifier (`exact-span-v1`), field-level quotes and the line bounding box from 1a, plus `embedded_file` and `outer_sha256`. Offsets index the canonical text of the embedded composite PDF, which is rebuilt from the same bytes (identified by its hash) when a span must be checked; the canonical text itself is not stored.

**Supply is separate.** Engines, turbines, generators and every row without a stated electric drive are written to `extraction.supply` (with evidence spans) and to the workbook summaries, never to the abstract. A portfolio of generators only produces zero schedule lines and an explicit `abstain: "no equipment schedule found"`. That is an abstention, not zero demand.

**Workbook facts are `documented` listings.** The reader reports distinct FINs by the applicant's unit-type family (`Engine`, `Turbine`, …) with sheet and cell, plus quoted description sentences and the counts and MW figures they state. A row can stand for several physical units and a stated MW is usually generation, so these are context and are labelled that way. The reader never produces a rating field: the workbooks carry none in a numeric column.

## Bounds

| Bound | Value | Where |
| --- | --- | --- |
| Request rate | at most 1 per second (`Pacer`), including HEAD, GET and each redirect hop | `MIN_REQUEST_INTERVAL_SECONDS` |
| User agent | `GridLens public source reader/1.0` | `USER_AGENT` |
| Hosts and path | exact `www.tceq.texas.gov`, HTTPS, no query, exact `applications/{n}-(ac\|tc).pdf`; public DNS answer pinned; 3 redirects, each re-validated | `tceq_http._route`, `open_tceq_application` |
| Outer file | 300 MB, by Content-Length and by running count | `MAX_OUTER_BYTES` |
| Content check | `application/pdf` only; HTML, script and markup bodies are `js_shell`; first bytes must be `%PDF-` | `_classify_type`, `download_document` |
| Embedded files | 64 files, 128 MB each, 512 MB total; pypdf stream limits are set explicitly to 128 MB (default 75 MB) | `tceq_portfolio` |
| Unpack time | 240 s plus start-up grace, child killed | `UNPACK_SECONDS` |
| Extraction | 1a bounds with `max_bytes` 128 MB, 1,200 pages, `extract_seconds` (registry, 420 s) | `_extract_pdf` |
| Workbooks | 2 parsed per document, 64 MB each, 400 MB uncompressed zip, 2,000 members, macros refused, 20,000 rows, 400 units listed | `tceq_pi1_workbook` |
| Per run (registry) | `max_checks` 60 HEADs, `max_downloads` 2 downloads, work stops 20 s before the job deadline, no download starts with under 240 s left | `query.application_documents` |
| State size | one state is about 6 KB for a document with no rows and grows with schedule lines (about 1 KB each, at most 120) | JSONB in provenance |

## Failure classes

Every failure is a rejection record (stage `tceq_application_document`, a `[a-z0-9_]` code) in the job's `rejected_records`. The job then reports `partial`, `parse_failures` and the stage counts under `application_documents`. The ordinary listing is still processed and the snapshot reconciliation is not blocked by a document failure.

| Code | Meaning | Retried |
| --- | --- | --- |
| `js_shell`, `wrong_content_type`, `not_pdf_signature` | HTML/script shell, other media type, or no `%PDF-` signature | not until validators change |
| `oversize` | over 300 MB | not until validators change |
| `embedded_oversize`, `no_composite_pdf` | the composite PDF is over 128 MB or absent | not until validators change |
| `unreadable_stream`, `encrypted`, `unpack_time_budget` | the outer file cannot be read | not until validators change (time budget is retried) |
| `text_layer_*` | 1a typed failure (`too_large`, `too_many_pages`, `time_budget`, `page_too_long`, `memory_limit`, `unreadable`, `encrypted`); `worker_failed` is retried | as listed |
| `empty_text_layer` | every page is scanned (no text layer); OCR is a later workstream | not until validators change |
| `zero_verified_rows` | notice: a non-empty document with no verified rows of any kind; the state records the abstention | n/a |
| `listing_shrink` | notice: fewer than half of at least four projects with an accepted state are still listed | n/a |
| `url_policy` | a URL or redirect left the allowlist | not until validators change |
| `http_status_NNN`, `network_error`, `acquisition_timeout` | transport; 408, 425, 429 and 5xx are retryable | next run |

Workbook failures (`workbook_unsafe`, `workbook_unreadable`, `workbook_oversize`, `workbook_layout_unrecognised`) are counted under `application_documents` and kept in the state, not raised as document failures.

**Previous accepted state survives failure.** A failure never replaces an accepted `document`. A non-retryable failure is written as `last_attempt` (code and validators) next to the preserved document, so the same bytes are not downloaded again; a known failed document is counted in `known_failed` without re-raising. A retryable failure writes nothing and is retried. The record is rebuilt each run from the stored state, so the NSR adapter's daily refresh does not drop the schedule.

## Running it and operating limits

- The stage runs inside the existing `texas-tceq-nsr-pending` job, after retrieval and with no transaction or source lock held, then retakes the source lock. It uses the worker process and the job lease (600 s) as its deadline. It is enabled by `query.application_documents` in `config/sources/registry.v1.json`; removing that object disables it. Callers that spawn (the unpack and 1a children) need an `if __name__ == "__main__":` guard.
- Discovery and extraction are separable: `discover`, `head_document`, `download_document`, `build_state` and `apply_state` take no database, and `tceq_document_stage.py` is the only database glue (prior state read, report merge). Splitting extraction into its own queued job (workstream 6) means calling `build_state` from a job instead of `run_stage`.
- At two downloads a day and a 24-hour cadence a large pending set takes many days to cover. Raise `max_downloads` only after watching job time and TCEQ's response; the 600 s lease limits a run to roughly two large documents.
- **Memory.** The outer file streams to disk and the unpacked composite is read into memory once (up to 128 MB) and again in the 1a child. A POSIX child has the 1a address-space cap; Windows has none (see 1a).
- **Known size gap.** Embedded files over 128 MB are reported as `embedded_oversize`. In the 10-document spike one composite (399049) is about that large.

## Limits

- Only the first composite PDF is extracted; other embedded PDFs are listed in the manifest as `pdf_not_extracted`.
- Extraction recall is 1a's: electric-drive evidence is rare in these filings and most are on-site generation. A filing yielding supply rows and no schedule is the expected common result.
- Scanned pages are counted (`needs_ocr_pages`) and not read.
- Listing-shrink detection is a heuristic over projects that already have an accepted state; it does not know about permits issued and withdrawn legitimately.
- A tc/ac link replaced by a different project number is a different document; a project moving from AC to TC is treated as a new URL with no prior state.
- The stage was exercised on synthetic portfolios in tests and on ten downloaded real files offline; see the report for the one live smoke test.
