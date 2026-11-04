# Workstream 1 — document extraction spike

**Run:** 2026-11-03 · **Scope:** 23 real public documents, read-only, no repo code or dependency changes. Files were fetched at about one request per second with a declared generic user agent and kept outside the repository. This is a measurement of text-layer availability and candidate-row yield. It is not a precision measurement; no gold set exists yet.

## What was run

| Source | Documents | How fetched |
|---|---|---|
| TCEQ pending NSR (data-center and power filings) | 10 AC/TC files | Links from the live NSR listing |
| OK DEQ `storedpermits` | 8 memos (8013, 8014, 8015, 8300, 8350, 8405, 8406, 8407) | Direct `{N}.pdf` |
| NMED application uploads | 5 PDFs (Black River 6567M6, El Cedro PSD-0340-M15, La Jara 339-M9, Thompson P018, Outland initial NSR) | Dated WordPress paths and the NMED document translator |

Tools: pypdf for per-page text and scanned detection, pdfplumber for table probing, openpyxl for Excel workbooks. **Docling and Camelot were not run.** Every inspected document had a usable text layer, so a layout fallback was not needed to answer the spike's questions. They stay in scope for the extraction core.

"Candidate row" below means a distinct (rating, unit, equipment noun) mention, with regulatory thresholds such as "greater than 500 hp" excluded. It is a recall-oriented count of things a parser could try to extract. It still includes repeated mentions of one unit and some non-equipment text. Treat it as an upper bound.

## Results

| Document | Pages | Scanned pages | Candidate rows | Electric-driver phrases |
|---|---|---|---|---|
| OK 8013 | 47 | 0% | 7 | 0 |
| OK 8014 | 50 | 0% | 5 | 0 |
| OK 8015 | 44 | 2% | 4 | 0 |
| OK 8300 | 59 | 0% | 6 | 0 |
| OK 8350 | 46 | 11% | 9 | 0 |
| OK 8405 | 19 | 0% | 4 | 0 |
| OK 8406 (West Edmond) | 66 | 8% | 20 | 3 |
| OK 8407 | 69 | 9% | 0 | 0 |
| NM Black River 6567M6 | 165 | 16% | 21 | 0 |
| NM La Jara 339-M9 | 238 | 12% | 18 | 1 |
| NM Thompson P018 | 196 | 5% | 19 | 0 |
| TX 399766 West Royal | 424 | 3% | 168 | 0 |
| TX 400428 Crusoe Longhorn | 976 | 3% | 162 | 0 |
| TX 402091 Voltagrid | 860 | 4% | 58 | 3 |
| TX 404507 Crusoe Goodnight | 528 | 12% | 120 | 0 |
| TX 405217 Nexus Hubbard | 226 | 10% | 88 | 0 |
| TX 407086 Aligned Plano | 232 | 9% | 1 | 0 |
| TX 407249 NRG Prairie | 352 | 7% | 212 | 0 |
| TX 411884 Caprock Ranch | 166 | 8% | 6 | 0 |

Not measured: NM El Cedro and Outland (downloaded, not scored in the final pass), and TX 399049 and 399548 (extraction failed, below). OK 8407 is an environmental-remediation drawing set, not an equipment memo, so zero is correct.

Scanned share across all scored documents runs from 0% to 16%, mostly 3% to 12%. Scanned pages are drawings, forms and attachments, not the equipment narrative.

## Findings

1. **TCEQ AC/TC files are PDF Portfolios, not plain PDFs.** Each is a one-page cover that says "download and open in Acrobat," wrapping an inner composite PDF (13 to 53 MB, 166 to 976 pages) plus Excel workbooks. The adapter's current limits (2 MB, 4 pages) cannot read any of it. The fetch path must extract embedded files, and the size bound must change (outer files are 16 to 249 MB).
2. **Two of ten portfolios failed to extract with pypdf** because an embedded stream exceeds its default length limit (399049, 399548; 249 MB and 102 MB). The extractor needs a streaming approach or a raised, bounded limit, and a visible failure state.
3. **The Excel workbooks (TCEQ PI-1) are structured and parse locally.** Each lists emission units with a unit-type label (for example "Engine: Internal Combustion Engine, Spark Ignited"), unit IDs, and project descriptions with counts and sometimes total MW. Distinct units found in the latest workbook per project: 30, 164, 214, 214, 138, 25, 14, 10 (some are aggregated, so 3,428 engines in 411884 appear as a few rows). **Ratings are almost never in a numeric column**; they appear in free-text names such as "Diesel Engine (each 685 kW/932 hp)" or in the PDF. So workbooks give reliable counts and types, and the PDF or a text field must supply ratings.
4. **Most TCEQ data-center filings describe on-site generation, not grid load.** Crusoe, Nexus, Voltagrid, Aligned and Caprock are engines and turbines serving the site. This is supply evidence and belongs in the separate supply ledger, not demand. Electric-drive evidence was found in only 3 TCEQ phrases and nowhere else in the sample.
5. **OK DEQ memos are the cleanest.** Text layer, header-keyed unit tables ("EU Point Description Horsepower Serial # Const. Date"), stable structure. Extractable as text lines without a table engine.
6. **The West Edmond memo (8406) confirms the motivating case and a trap.** It fetched fine. The narrative says "three (3) 2,500-hp Siemens electric compressor motors" and the EUG-17 table lists the three Ariel compressors at 5,200 rated hp with no driver column. The driver comes only from prose. A parser that reads the table alone would report 5,200 hp per unit and no electric drive. Rating (2,500 hp motor) and compressor rating (5,200 hp) must not be mixed. This validates the driver-phrase rules and the exact-span verifier.
7. **NMED applications are long (165 to 238 pages) with 5% to 16% scanned pages.** Black River's four 2,250 hp engines were found; the "Electric Inlet Compression" evidence lives in a flow sheet and was not captured by text rules.
8. **Closed gap:** current TCEQ NSR listing rows still expose `{project}-ac.pdf` and `-tc.pdf` links. The post-August Permit Search Portal, Title V, PBR 106.512 and Records Online remain unchecked.
9. **Closed gap:** OK `storedpermits/8406.pdf` exists and is a text PDF. The enumeration range is partly tested only: eight of nine probes returned a PDF, and `8200` returned 404, so the key space has holes.

## Limits and risks

- Candidate rows are not validated equipment records. Precision needs the internal gold set.
- The first pdfplumber table probe was noisy and is not reported. The OK tables did not need it.
- Sample is 23 documents chosen by name relevance, not random. TCEQ yields skew toward data-center and power filings.
- Page-text extraction can disagree with what a reader sees; verifier spans must be computed against the stored canonical text.
- Download sizes are large. A nightly TCEQ fetch of all in-scope filings could be several GB; apply content-hash change detection before any fetch of the full portfolio.

## Recommended next steps (not started)

1. Add portfolio-aware fetch: read the cover's attachment catalog, pull the inner PDF and workbooks, hash each.
2. Parse workbooks with openpyxl first for unit counts, types and IDs; use PDF text for ratings.
3. Build OK DEQ header-keyed table rules first because they have the highest clean yield.
4. Add narrative driver-phrase rules with the exact-span verifier before any LLM proposer.
5. Seed the gold set from these 23 documents plus 30 to 75 more, labelled internally.
