# Permit-document extraction core (workstream 1a)

**Date:** 2026-11-03 · **Code:** `backend/src/gridlens/ingestion/parsers/permit_docs/` · **Version:** `permit-doc-extract-v1`

This is the deterministic, offline half of workstream 1 in the [ingestion handoff](../strategy/ingestion-handoff-20261103.md). It turns permit and application PDFs into verified equipment rows and a schedule text that the existing `equipment-schedule-lines-v4` parser (`extract_equipment_claims`) accepts unchanged. It has no network, LLM or database access and is not wired into any worker, fetch adapter or ingestion hook yet. Nothing here changes production behavior; wiring it to `Evidence.abstract` and `Evidence.provenance` is the next step.

## Pipeline

1. `text_layer.py` builds a canonical text with pdfplumber (pinned `0.11.7`): per-page text, one string with page offsets, and a line-level bounding box for any offset. Bounds: 64 MB, 1,200 pages, 120,000 characters per page, 180 s total, 20 s per page. A breach returns a typed `TextLayerFailure`, never partial success. A page whose extraction raises is listed in `failed_pages`, routed to OCR and reported as an issue. Pages with fewer than 40 non-space characters are marked scanned.
2. `router.py` labels each page `table`, `narrative`, `scan` or `irrelevant`. Scan pages are returned as needing OCR and produce no rows. Pages that cite the RBLC or RACT/BACT/LAER Clearinghouse are `irrelevant`, because they list other facilities.
3. `tables.py` reads header-keyed text tables (Oklahoma DEQ `EU Point Description Horsepower Serial # Const. Date`, `EUG-N` group titles) and NMED Table 2-A rows (`ID make model serial 2250 HP 2250 HP`, first value is Rated Capacity). The header fixes how many trailing columns follow the rating; rows that do not fit are skipped with an issue. Continuation rows on later pages inherit the header until prose appears.
4. `narrative.py` applies driver-phrase rules to prose such as `(3) 2,500-hp Siemens electric compressor motors`. Threshold and range wording (`greater than 500 hp`, `>500 hp`, `500 to 1,000 hp`, `g/hp-hr`) never yields a row.
5. `verifier.py` checks every field of every row: the quote must sit at the stated span and page of the canonical text (whitespace runs may differ, nothing else) and the value must be recomputed from the quote alone. A row with any failing field is rejected and counted.
6. `schedule.py` splits verified rows into demand claims and supply/other rows, renders the v4 schedule text, and builds per-line provenance. `pipeline.py` exposes `extract_permit_document(pdf_bytes, *, document_hash, company, facility, as_of)` and a per-page-text seam, `extract_from_pages`.

## Rules the code enforces

- **Electric drive only from the permit's own words.** No electric-drive wording means drive `unknown` and no electrical MW. Negations (`non-electric`, `not electric`) are not electric.
- **Motor rating and driven-compressor rating are never merged.** In the West Edmond memo (OK DEQ 2017-0987-C M-2) the prose says three 2,500-hp electric compressor motors and the EUG-17 table lists the three Ariel compressors at 5,200 rated hp with no driver column. Both are kept as separate rows. The motor row is linked to table rows only through the permit's own phrase (`associated Ariel`). The table compressors stay drive `unknown` and never become demand claims.
- **Claims are narrow.** Only `compressor` or `pump` rows with an explicit stated drive (electric, gas engine, diesel engine, steam) and a rating unit the demand model supports (hp, kW, MW, kVA) become `EquipmentClaim` objects. Engines, turbines, generators, heaters, flares, rows with no stated drive and MMBtu/hr ratings are retained with provenance in `supply_rows` and never feed demand.
- **Table rows have count unknown** unless a count is stated. Repeated mentions of the same narrative unit are collapsed (first kept, later duplicate counted), so a unit is never counted twice. Identical table-like prose rows also collapse; this undercounts rather than overcounts.
- **Unknown is not zero.** Missing count, drive, state and rating basis stay unknown. A page with no equipment yields no rows and an empty schedule text.

## Provenance

`PermitExtractionResult.provenance` maps the zero-based line number in `schedule_text` to `{page, start, end, quote, document_hash, verifier: "exact-span-v1", origin, stitched, linked_to, fields}`. `fields` holds the value, verbatim quote, span and page of each field. Offsets are into the canonical text, so the canonical text must be stored (or rebuilt from the same document bytes) for the spans to be checkable later.

## Measured behavior

See the workstream report for the run over the 23 spike documents. In short: the gold set (`backend/tests/fixtures/permit_docs/gold/`, 30 hand-labelled excerpts from Oklahoma DEQ, NMED and TCEQ records) is a development set, so its precision is optimistic; recall is lower because several real layouts are not read yet.

## Known gaps

- Layouts not read: ratings embedded in a description column without a rating header (`WC-1 1,380-hp Caterpillar ...`), table rows whose rating sits on the line above or below the id line, rating written after the equipment noun (`Natural Gas Boiler 5.02 MMBTUH`), ratings written as `171 Mega Watts`, and `x` between a count and a rating (`six (6) x 4 MMBtu/hr`).
- Scanned pages (3% to 16% of the sample, mostly drawings and forms) are only flagged. OCR is a later workstream.
- Electric-drive evidence is rare: in the downloaded TX, NM and OK documents only West Edmond states it in prose. Flow-sheet evidence such as NMED `Electric Inlet Compression` is not in the text layer.
- Generator and turbine MW values are nameplate output (supply). They are retained as supply/other rows only.
- Time budget: a 1,000-page composite can take several minutes with pdfplumber. The default 180 s total bound fails such documents with a typed `time_budget` failure; callers that fetch TCEQ composites must raise the bounds explicitly.
- No Docling or Camelot fallback, and no lattice-table extraction, was added.
