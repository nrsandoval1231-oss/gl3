# Oklahoma DEQ permit documents (workstream 1c)

**Date:** 2026-11-03 to 2026-11-04 · **Code:** `backend/src/gridlens/ingestion/adapters/ok_deq_documents.py`, `ok_deq_memo.py`, `ok_deq_data_center_page.py`, `ingestion/okdeq_document_stage.py` · **Stage version:** `okdeq-permit-document-v1`

This is the OK DEQ half of the fetch work in the [ingestion handoff](../strategy/ingestion-handoff-20261103.md). It feeds the offline extractor from [workstream 1a](permit-document-extraction-20261103.md) with DEQ evaluation memoranda and writes the result through the existing ingestion service, so `equipment_intelligence` reads it unchanged. It follows the [TCEQ stage](tceq-application-documents-20261103.md), reuses its pacer, typed failures, validators, report shape and DB-glue pattern, and applies the lessons from that stage's review fixes. **It ships disabled.** No deployment, credential, paid provider, migration or production data was touched. Operation against the live sites is shown only by the one-off smoke below, which is not evidence that the stage works in production.

## What the listing does and does not give us (discovery finding)

Checked live on 2026-11-04 with a few polite requests (at most one per second, files kept outside the repository):

- The `PermitsPublicReview` listing is one HTML table. Each row has two links, both to `permitinformation.aspx?id={N}` where `N` (about 1.06 to 1.2 million) is the OnBase object id of the permit row. **Neither link carries a `storedpermits` key.**
- The detail page is a JavaScript shell (a 63 KB form plus a tier-process description). Its "Related Documents" frame loads `/PermitsPublicReview/index.html?CQID=262&OBKey__844_1={id}`, an OnBase Public Access custom-query app whose configuration (`obpa-config.json`) points at a **different host**, `okdeqonbaseexternal.databankcloud.com/pav/api`. The document list is therefore not on `applications.deq.ok.gov`; it is a third-party JSON API. This work does not call it (the owner scoped hosts to `applications.deq.ok.gov` and the DEQ page), so whether that API reveals a `storedpermits` key is **unverified**.
- The sampled `storedpermits` memos are old (key 8013 is dated June 2021, 8406 March 2023). How far keys have advanced to today, or whether new drafts are still written there, is unknown. Keys have holes (8200 returns 404).
- Only 47 of the 287 listing rows pass the adapter's relevance filter today; the West Edmond permit is not on the current listing at all.

Consequences, stated plainly:

1. There is **no listing-to-document join by key**. The join is the permit number printed in the memo's own SUBJECT line, matched to the listing's `Permit #`.
2. Documents are reached from three explicit sources, in order: `seed_keys` (an owner-curated registry list, at most 50), keys already in the retained index that join a listing row, and an **optional capped forward probe** (`probe`, default OFF) that starts at a recorded `frontier`, issues at most `max_probes` (at most 20) HEADs per run, and stops after `max_misses` consecutive missing keys. Nothing enumerates integer keys unless an owner turns the probe on, and the registry diff shows it.
3. A memo whose permit is not on the current listing is indexed (key, hash, permit number, memo date) and joined to nothing; when that permit later appears on the listing it is extracted then. Nothing is written as evidence for it, so this stage cannot invent a record.

## What it does

For each key to examine (seed, unfinished, re-validation, probe):

1. **Check.** One `HEAD` to `https://applications.deq.ok.gov/permitspublic/storedpermits/{N}.pdf`. 404 is `absent` (re-checked after 7 days), not a failure. A matching ETag, or matching Last-Modified and length, is unchanged and skipped.
2. **Fetch.** Otherwise `GET`, streamed to a temporary file with a running SHA-256, never held in memory. The GET headers are compared before any body is read, so a host that rejects HEAD does not re-send unchanged files; with no usable validators the content hash decides.
3. **Read the header.** The canonical text layer comes from the 1a killable child. `ok_deq_memo.parse_memo_header` reads, by deterministic regex, the permit number from the `SUBJECT:` line (`2017-0987-C (M-2)`), the memo date after `MEMORANDUM`, the company and facility, and the facility id. Every fact keeps its verbatim quote, offsets and page, re-checked against the text. A permit number that cannot be matched is recorded as **unknown** (a `unverified_permit_number` notice) and never guessed; a number in the prose does not count.
4. **Join and extract.** If the normalised permit number (`2017-0987-C (M-2)` becomes `2017-0987-C M-2`, the listing's form) equals a listing row's, the memo goes to the 1a extractor.
5. **Write.** The result is folded into the listing record exactly as the TCEQ stage does: schedule text into the abstract, a hash that combines the base hash and a digest excluding fetch and first-seen times, provenance under `okdeq_document`.

The extractor is called with `company` and `facility` omitted: the listing abstract already carries the one `Company:` and `Facility:` header, and a second `Company:` line makes the equipment parser's identity ambiguous and drops the metadata (found while writing the DB test).

## Lineage

Lineage hangs on the permit number, not the key. Several keys can carry one permit number (a draft and its revisions). The state for a permit holds a `versions` list (key, URL, hash, size, status, memo date, row counts, `first_seen_at`). The highest key is current. A newer key becomes the current document and is appended; a lower key found later is added to `versions` without replacing the current document; a version's `first_seen_at` is never rewritten, and changed bytes under the same key keep it and list the earlier hash under `replaced_sha256`. The earlier evidence version stays in the database. Different permit numbers (for example `M-1` and `M-2`) are separate states; only `permit_family` (`YYYY-NNNN`) is recorded for readers, never used to join.

## What is stored

| Field | Content |
| --- | --- |
| `Evidence.abstract` | The listing abstract, plus (only when verified demand rows exist) the 1a `schedule_text`. A memo with no verified rows leaves it unchanged. |
| `Evidence.provenance["okdeq_document"]` | Permit number, normalised join key, family, current key, `versions`, the current document (URL, key, SHA-256, size, validators, fetch time, memo header facts with quotes, identity check against the listing, extraction summary with per-line page/offset/bbox/verifier/document hash, supply rows, `abstain`), `dates`, and the data-center page block. |
| `Evidence.extraction_location` | The listing row plus `storedpermits/{N}.pdf pp.a-b`, clipped to 100 characters. |
| `Evidence.published_at` | **Null.** The memo date is the draft's internal date, not a verified public posting date, and the ingestion service also derives a "latest permit issue date" from the same field. It is stored with its quote under `dates.memo_date`, not promoted. |
| `Evidence.observed_at`, `Observation.first_seen_at` | Database defaults; first-seen is never updated. |

**Supply is separate.** Rows without a stated electric drive, and every generator, engine or turbine row, go to `extraction.supply`, never to the abstract. Where a document yields no demand rows, `abstain: "no equipment schedule found"` is explicit: an abstention, not zero demand. A memo with no equipment text at all adds the `zero_verified_rows` notice.

**West Edmond (the motivating case).** The synthetic memo mirrors permit 2017-0987-C M-2: prose names three 2,500-hp Siemens electric compressor motors; the EUG-17 table lists three Ariel compressors at 5,200 rated hp with no driver column. It yields exactly one demand claim (electric compressor, 2,500 hp, count 3, proposed) and the three table rows as supply with unknown drive. The same holds in the live smoke on the real memo.

**Admission still decides.** The existing OK DEQ domain rule accepts an equipment schedule only for a row that states an event date, which for this listing means a public-comment window start. A listing row without one (for example "Technical Review") keeps the verified schedule as evidence and provenance, and the domain still rejects it as undated. The stage does not change that rule; the DB test therefore uses a row with a comment-window date.

## Data-center page

`https://oklahoma.gov/deq/deq-information-on-data-centers.html` (host `oklahoma.gov`, one request per run) has an HTML table of 40 issued/pending permits with columns DIV, COUNTY, COMPANY, FACILITY, PERMIT TYPE, STATUS, LINK. **There is no permit-number or application-id column**; the permit number is readable only from the linked file name (25 of 40 rows on 2026-11-04; others are named such as `Stillwater Data Center Permit.pdf`). Links to PDFs under `/content/dam/ok/en/deq/documents/` are kept; any other link is dropped.

This is implemented as **discovery only**: with `data_center_page.enabled` the rows are parsed, and a listing row whose permit number equals a row's file-name permit gets a `data_center_page` block (rows as published, source URL, role `discovery_and_supply_context`) in its provenance and hash; a failed fetch keeps the retained block. The linked PDFs are **not fetched or extracted**. They describe on-site generation (supply) and must never become demand; leaving them unread guarantees that, and fetching them is separate work that would need a second host policy and storage for unjoined rows.

## Bounds

| Bound | Value |
| --- | --- |
| Request rate | at most 1 per second including HEAD, GET and the page; user agent `GridLens public source reader/1.0` |
| Hosts and path | exact `applications.deq.ok.gov`, HTTPS, no query, `/permitspublic/storedpermits/{1-6 digits}.pdf`; public DNS pinned; redirects never followed (a 3xx is `redirect_not_followed`); page: exact `oklahoma.gov` URL via the shared host-pinned reader |
| File size | 40 MB, by Content-Length and by running count |
| Content check | `application/pdf` only; HTML/script is `js_shell`; first bytes must be `%PDF-` |
| Per run (registry) | `max_checks` 1 to 60 HEADs, `max_downloads` 1 to 5, `seed_keys` at most 50; probe at most 20 HEADs, at most 5 misses; stage stops on the first 429 or 503 |
| Time | own deadline = job deadline minus a persistence reserve of `max(120 s, 60 s + 0.5 s per record)` (capped at 300 s); no HEAD with less than 70 s left, no download with less than 150 s left; the reading child is bounded by `min(extract_seconds, time left - 30 s - 20 s)`; `extract_seconds` 60 to 900 |
| Pages and time per page | 1a limits: 1,200 pages, 60 s per page |
| Retention | key index at most 800 entries in source health |

## Failure classes

Same model as TCEQ. Real failures are rejection records (stage `okdeq_document`, a `[a-z0-9_]` code, only codes and small integers; exception text and response content are never stored) in the job's `rejected_records`; the job becomes `partial` with `parse_failures`, but `collection_status` is not set, so the listing's cooldown and retry scheduling are not moved. Notices (`zero_verified_rows`, `unverified_permit_number`) are results, not failures.

| Code | Meaning | Handling |
| --- | --- | --- |
| `js_shell`, `wrong_content_type`, `not_pdf_signature`, `oversize`, `redirect_not_followed`, `empty_text_layer`, `text_layer_too_large`, `text_layer_too_many_pages`, `text_layer_unreadable`, `text_layer_encrypted`, `header_quote_mismatch`, `url_policy` | a property of the file or URL | remembered with validators and hash (as a `failed` key, or a `last_failure` note on a key with an accepted document); not fetched again until they change; seeds re-checked weekly |
| `text_layer_time_budget`, `text_layer_memory_limit`, `text_layer_page_too_long`, `text_layer_worker_failed`, `network_error`, `acquisition_timeout` | environment limits | retryable; nothing is written to evidence; attempts kept in the key index, 3 counted attempts then 7 days' rest unless the validators change; a budget cut short by the job deadline does not count |
| `http_status_404` | no document at the key | `absent`, not a failure; seeds re-checked after 7 days |
| `http_status_429`, `http_status_503` | the publisher is throttling | the stage stops at once; `Retry-After` (bounded to 7 days) is reported as `application_documents.retry_after_seconds`; if the listing run was rate-limited the stage is skipped with no requests |
| `stage_error` | unexpected fault | reported by exception class only; every retained state stays on its record |

A failure never replaces an accepted document, and a transient failure changes nothing in the evidence hash.

## Running it

- Controlled by `query.application_documents` on the `oklahoma-deq-public-review` registry entry, shipped `enabled: false`. See [activation](../strategy/ws0-production-env-changes-20261103.md#ok-deq-document-stage-activation).
- The stage runs inside the existing listing job after retrieval and with no transaction or source lock held, then retakes the lock. State comes from the newest evidence that has an `okdeq_document` block; the key index (validators, attempts, probe frontier) lives in `Source.health["okdeq_documents"]`, so it never changes evidence hashes.
- No migration; `alembic check` is clean.

## Limits and open risks

- The key source is the weak point: with `seed_keys` empty and the probe off, an enabled stage makes no document request. A probe from a guessed frontier may spend its few HEADs on keys that never join the listing; the listing offers no way to know a key without opening the third-party viewer.
- Memos for permits not on the listing are read (header only) and then ignored until the permit is listed.
- Only the memo is read; draft permit text, drawings and attachments in the same PDF are read only as far as the extractor reads them. A 20 MB drawing-set file (8407) is within the size cap but its text layer is unevaluated here.
- Scanned pages are counted (`needs_ocr_pages`) and not read.
- Extraction recall is 1a's; most memos describe on-site engines, so supply with no schedule is the common result.
- Windows has no address-space cap for the reading child.

## What was tested

- Unit tests (no network; MockTransport with pinned DNS, fake-clock pacing, synthetic text PDFs): header parsing on six permit-number shapes with verbatim spans; unreadable permit left unknown; West Edmond-style memo giving exactly one electric compressor claim with the driven compressors as supply/unknown; generator-only abstention; zero-row notice; permit lineage across two keys in both orders with first-seen kept; unjoined and unverified documents; HTML shell, wrong type, markup body, oversize (header and stream), redirects, 404, URL policy; one-per-second pacing; change detection by validators and by hash; idempotent rerun; changed bytes; 429 and 503 stopping the stage with `Retry-After`; download and check budgets; deadline; retry caps and 7-day rest; no untrusted text persisted; probe cap, miss stop and frontier; registry bounds (16 rejection cases); the real isolated child process; data-center page parsing, join, retained block on failed fetch, one request, rate limit.
- DB-backed tests on a disposable PostgreSQL: a synthetic memo through the stage and `process_records` to an equipment `EvidencePackage` (one electric compressor claim, quote offsets valid), replay with no new evidence and first-seen kept, a newer key adding a version while preserving the earlier evidence, generator-only supply, a failed refetch keeping the accepted schedule, ships-off `process_job` with zero requests, partial reporting without moving collection status, a stage fault as a typed error, a rate-limited listing making no requests.

### One-off live smoke, 2026-11-04 (not proof of operation)

Real stage code, real httpx client, at most one request per second, work files outside the repository, isolated child. Six seeds (8013, 8014, 8015, 8200, 8405, 8406) against five hand-built listing rows carrying the memos' permit numbers, plus the data-center page. Twelve requests, **29.4 s** end to end.

| Key | Permit (from the memo) | Memo date | Pages (scanned) | Verified rows | Schedule lines | Supply rows |
| --- | --- | --- | --- | --- | --- | --- |
| 8013 | 2020-0501-TVR4 | 2021-06-03 | 47 (0) | 1 | 0 | 1 |
| 8014 | 2020-0510-TVR | 2021-06-18 | 50 (0) | 2 | 0 | 2 |
| 8015 | 2020-0502-TVR4 | 2021-06-21 | 44 (1) | 1 | 0 | 1 |
| 8405 | 2002-279-O M-2 | 2023-03-20 | 19 (0) | 0 | 0 | 0 (notice) |
| 8406 | 2017-0987-C M-2 | 2023-03-09 | 66 (5) | 50 | **1** | 19 |
| 8200 | not a document | | | | | 404, `absent` |

The real West Edmond memo produced exactly one demand line (three 2,500-hp electric compressor motors); all five permit numbers and memo dates were read from the SUBJECT and MEMORANDUM lines, and the memo facility matched the listing facility in all five. The data-center page returned 40 rows, 30 with a safe PDF link and 25 with a permit number in the file name; none matched the five test rows. The smoke shows the real memos fetch, read and join within the bounds on one machine. It shows nothing about scheduled operation, current document keys, how many current listing rows have a memo, or demand yield.
