# Permit-document extraction core (workstream 1a)

**Date:** 2026-11-03 (revised after independent review) · **Code:** `backend/src/gridlens/ingestion/parsers/permit_docs/` · **Version:** `permit-doc-extract-v1`

This is the deterministic, offline half of workstream 1 in the [ingestion handoff](../strategy/ingestion-handoff-20261103.md). It turns permit and application PDFs into verified equipment rows and a schedule text that the existing `equipment-schedule-lines-v4` parser (`extract_equipment_claims`) accepts unchanged. It has no network, LLM or database access and is not wired into any worker, fetch adapter or ingestion hook. Nothing here changes production behavior; wiring it to `Evidence.abstract` and `Evidence.provenance` is the next step.

## Dependencies

`pdfplumber==0.11.10` (pulls `pdfminer.six` 20260107, which clears PYSEC-2026-1761 and PYSEC-2026-1762, plus Pillow, cryptography, cffi and `pypdfium2`). `pypdfium2` is installed as a pdfplumber dependency but this code never calls it (no rendering, no OCR); it ships in the image anyway. `pip-audit` as run by `scripts/check.ps1` reports no known vulnerabilities for the locked set.

## Pipeline

1. `text_layer.py` builds a canonical text: per-page text, one string with page offsets, and a line-level bounding box for any offset (`CanonicalText.locate`). Extraction runs by default in a spawned child process (`isolate=True`). The parent kills the child at `max_seconds` plus a 20 s start-up grace, so parsing of the page tree and of every page is under one hard wall-clock bound. Other bounds: 64 MB, 1,200 pages, 120,000 characters per page, 20 s per page (soft, checked after the page). Any breach returns a typed `TextLayerFailure`, never partial success. A page whose extraction raises is listed in `failed_pages`, routed to OCR and reported as an issue.
2. `router.py` labels each page `table`, `narrative`, `scan` or `irrelevant`. Scan pages (fewer than 40 non-space characters) are returned as needing OCR and produce no rows. Pages that cite the RBLC or the RACT/BACT/LAER Clearinghouse are `irrelevant` because they list other facilities.
3. `tables.py` reads header-keyed text tables (Oklahoma DEQ `EU Point Description Horsepower Serial # Const. Date`, `EUG-N` group titles) and, on `table` pages only, NMED Table 2-A rows (`ID make model serial 2250 HP 2250 HP`; the first value is Rated Capacity). The header fixes how many trailing columns follow the rating; rows that do not fit are skipped with an issue. Continuation rows on later pages inherit the header until prose appears. A group title supplies type or drive only when it names exactly one kind of equipment, and a title drive applies only to rows of that kind.
4. `narrative.py` applies driver-phrase rules to prose such as `(3) 2,500-hp Siemens electric compressor motors`. The equipment noun must start on the same line as the rating and in the same sentence; a rating at the end of a line never pairs with the next line. Lines already read as table rows are skipped.
5. `verifier.py` checks every field of every row: the quote sits at the stated span and page (whitespace runs may differ, nothing else), the value is recomputed from the quote alone, and the quote is associated with this row. Associated means: for prose, after the rating, same line and sentence, count directly before the rating, state cue in the rating's sentence; for tables, on the row's own line or in its own nearest group title; for capacity tables, on or beside the row line and not on another capacity row's line. Unknown evidence keys, missing evidence and unexplained evidence reject the row. Rejections are counted and reported, never dropped silently.
6. `pipeline.py` removes repeated narrative mentions, reconciles prose against tables, and hands the rows to `schedule.py`, which splits demand claims from supply/other rows, renders the v4 schedule text and builds provenance. Entry points: `extract_permit_document(pdf_bytes, *, document_hash, company, facility, as_of)` and the per-page-text seam `extract_from_pages`.

## Counting rules

- A prose count is taken only directly before the rating, on the same line, inside the rating's sentence: `three (3) 2,500-hp`, `Two 2,000-hp`, or a bare `(3)` that follows a comma, semicolon, `and` or `or` in the middle of a sentence. A bare `(4)` at a line start, after a colon, or opening a sentence is list numbering and is not a count.
- Table rows have count unknown unless a count is stated.
- A narrative row that repeats an earlier narrative row (same type, drive, rating, unit, count) is dropped and counted in `duplicates`. This undercounts two genuinely separate identical units described in prose.
- A unit described in both prose and a table (same type, drive, rating, unit) is counted once: when the prose count is unknown or no larger than the number of table rows, only the table rows are kept; when the prose states more units than the table lists, only the prose row is kept. Either way an issue beginning `Conflict:` is recorded. Prose and table rows whose drive differs (for example the table does not state the drive) are different rows and are not reconciled; the table row has no stated drive and is never a claim.

## Other rules the code enforces

- **Electric drive only from the permit's own words.** No electric-drive wording means drive `unknown` and no electrical MW. Negations (`non-electric`, `not electric`) are not electric.
- **Motor rating and driven-compressor rating are never merged.** In the West Edmond memo (OK DEQ 2017-0987-C M-2) the prose says three 2,500-hp electric compressor motors and the EUG-17 table lists the three Ariel compressors at 5,200 rated hp with no driver column. Both are kept as separate rows; the motor row is linked to table rows only through the permit's phrase `associated Ariel`.
- **Claims are narrow.** Only `compressor` or `pump` rows with an explicit stated drive and an hp/kW/MW/kVA rating become `EquipmentClaim` objects. Engines, turbines, generators, heaters, flares and MMBtu/hr ratings are retained in `supply_rows` with provenance and never feed demand.
- **Equipment leaving service is never `existing`.** Removal wording (`remove`, `replace`, `retire`, `decommission`, `shut down`, `dismantle`, `abandon`, `demolish`) in the rating's sentence, in either direction, gives state `retired`. A removal cue marks every rating in its sentence as retired, so a new unit introduced in a replace sentence is undercounted rather than overcounted.
- **Unknown is not zero.** Missing count, drive, state and rating basis stay unknown. A page with no equipment yields no rows and an empty schedule text.

## Provenance

`PermitExtractionResult.provenance` maps the zero-based line number in `schedule_text` to `{page, start, end, quote, document_hash, verifier: "exact-span-v1", origin, stitched, linked_to, fields}`. Each entry of `fields` has the value, verbatim quote, span, page and `bbox` (the `(x0, top, x1, bottom)` of the text line holding the first character of the quote; null when the text came from the per-page seam). The box is line-level, not character-level. Offsets are into the canonical text, so the canonical text must be stored (or rebuilt from the same bytes) for the spans to be checkable later.

## Bounds and platform limits

- Wall clock: hard on every platform, because the child process is killed.
- Memory: a POSIX child gets an address-space cap (`max_memory_bytes`, default 2 GiB, `RLIMIT_AS`). **Windows has no `RLIMIT_AS` and no cap is applied there.** On Windows the memory bound is only the byte, page-count and per-page-character limits plus the wall-clock kill, so a PDF that allocates quickly inside those limits is not stopped by memory.
- Callers that run the isolated path from a script must guard their entry point with `if __name__ == "__main__":` (spawn re-imports the main module). In-process extraction (`isolate=False`) exists for tests and for text already extracted.
- A 1,000-page composite can take several minutes with pdfplumber. The default 180 s bound fails such documents with a typed `time_budget` failure; callers that fetch TCEQ composites must raise the bounds explicitly.
- Digit runs in number patterns are bounded (15 digits) and long table lines are skipped, so a hostile token cannot cause quadratic matching.

## Measured behavior

The gold set (`backend/tests/fixtures/permit_docs/gold/`, 39 hand-labelled entries: 30 public excerpts from Oklahoma DEQ, NMED and TCEQ records and 9 synthetic regression cases) gates field precision at 0.98, any wrong drive, and every demand claim exactly. It is a development set: the extractor was tuned against it. Recall is reported, not gated. The workstream report lists the numbers and the run over the 23 spike documents.

## Known gaps

- Layouts not read: ratings in a description column without a rating header (`WC-1 1,380-hp Caterpillar ...`), table rows whose rating sits on the line above or below the id line, a rating written after the equipment noun (`Natural Gas Boiler 5.02 MMBTUH`), `171 Mega Watts`, `six (6) x 4 MMBtu/hr`, and prose that wraps between the rating and its noun (`2,000-hp Cooper-Bessemer` at a line end). These are recall losses, deliberately: reading across a line break is what let a rating pair with the next table row's noun.
- Scanned pages (3% to 16% of the sample, mostly drawings and forms) are only flagged. OCR is a later workstream.
- Electric-drive evidence is rare: in the downloaded TX, NM and OK documents only West Edmond states it in prose. Flow-sheet evidence such as NMED `Electric Inlet Compression` is not in the text layer.
- Generator and turbine MW values are nameplate output (supply) and are retained as supply/other rows only. Prose about other facilities that lacks an RBLC marker can still produce such rows.
- Capacity-table neighbour lines are accepted only if they carry no other capacity row's id; numeric row ids that also appear as unit numbers (`Field Unit 3`) are tolerated when the line also carries the row's own id.
- No Docling or Camelot fallback and no lattice-table extraction.
