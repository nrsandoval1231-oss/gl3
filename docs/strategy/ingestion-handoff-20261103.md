# GridLens ingestion and intelligence build — Claude Code handoff

**Written:** 2026-11-03 · **Repo:** github.com/nrsandoval1231-oss/gl3

## Read first

1. `AGENTS.md`, then the canon, PRD, architecture overview, `.agent/CURRENT_STATE.md` and `.agent/FINISH_CONTRACT.md`, as AGENTS.md orders them.
2. **Strategy:** [ingestion-strategy-20261103.md](ingestion-strategy-20261103.md) (exported from the owner's Claude doc). This is the plan you are implementing. Its roadmap, per-source table, extraction pipeline, Jev section and gl3 code map are the spec. Two diagrams were dropped in export; their content is described in the surrounding text.
3. **Research report:** [ingestion-research-20261103.md](ingestion-research-20261103.md). Per-source detail and citations.

## Owner decisions (Nov 3, 2026) — these are authorizations

- **Paid providers are authorized, low-fee.** Combined monthly cap: **$100** for Jev + OpenAI LLM + OCR. Start conservative, watch one week of spend against records produced, report, then the owner decides on raising it.
- **TypeSafe Jev goes live, not shadow,** with tiered authority (below). Update the canon's "advisory only" wording to match, in the same PR as the code.
- **The LLM is switched on** for grounded proposals, including equipment fields.
- **Paid OCR is approved** for scanned pages, using gl3's existing OpenAI vision OCR path first.
- **Keys:** `TYPESAFE_API_KEY` and `OPENAI_API_KEY` are already in Infisical. Never print, copy or commit them.
- **No Firecrawl** for official government sources; use the existing bounded HTTP adapters (and Playwright only if a page truly needs JavaScript).
- **Competitor data** (Cleanview, Baxtel, etc.) is a benchmark only, never a feed.
- Production deployment still goes through the protected release process. Prepare it; the owner confirms the deploy.

## OpenAI model choice (owner, Nov 3, 2026)

Use **GPT-6.1 Sol** (`gpt-6.1-sol`) for the LLM. Prices from [OpenAI's pricing page](https://developers.openai.com/api/docs/pricing), read Nov 3, 2026, per million tokens: **$2.00 input, $0.10 cached input, $10.00 output**. The page's half-price table appears to be Batch/Flex ($1.00 / $0.05 / $5.00), but its labels weren't readable, so confirm in the OpenAI dashboard before relying on it. A third-party listing gives a 1.05M-token context, 128K max output and image input, with higher prices above 272K input tokens; confirm on OpenAI's model page.

- `INTELLIGENCE_OPENAI_MODEL` and `INTELLIGENCE_OPENAI_REASONING_MODEL` = `gpt-6.1-sol`, priced 2.00 / 10.00, marked verified after checking the dashboard.
- `INTELLIGENCE_OPENAI_FAST_MODEL`: the owner chose Sol; propose `gpt-6-luna` ($0.10 / $0.50) for cheap high-volume fast-slot tasks only if the owner agrees, otherwise Sol here too.
- OCR (`INTELLIGENCE_OCR_MODEL`): `gpt-6.1-sol` if it accepts the PDF/image input the existing OCR path sends; confirm, and include it in the OCR bake-off.
- Keep max output tokens tight (e.g., 2,000 for proposals) and use prompt caching for repeated instructions ($0.10 cached input).
- Nightly work isn't latency-sensitive: if gl3 can use the Batch API, propose it for the 50% discount.
- Rough budget check: a proposal call of ~5K input + 500 output tokens costs about $0.015, so ~$60 a month covers about 4,000 calls. Report actual per-call cost after the first night.

## Open inputs to ask the owner for

- Confirm Jev pricing and billing fields (vendor lists $0.042 per million input tokens, output free; one listing says $0.0578). Verify on the TypeSafe account before marking verified.

## Spend caps to propose (confirm semantics in `settings.py` before setting)

| Setting | Suggested start |
| --- | --- |
| `INTELLIGENCE_GLOBAL_MONTHLY_USD` | 100 |
| `INTELLIGENCE_GLOBAL_DAILY_USD` | 5 |
| Provider monthly USD (OpenAI / TypeSafe) | ~90 / ~10 |
| `INTELLIGENCE_MAX_CALL_USD` | 0.25 |
| `INTELLIGENCE_OCR_MAX_CALL_USD` | 0.10 |
| Call-count caps | Set from the first night's observed volume; never leave at 0 if the path should run |

Add a "spend near cap" alert and make sure a capped-out job is visible, not silently skipped.

## Workstreams, in order

Each one is its own PR with full `scripts/check.ps1` gate and CI. Report exact commands and results.

### 0. Config activation (no code)
Prepare the production env changes using `deploy/digitalocean/intelligence.disabled.env.example` as the template: Jev flags (`JEV_ENABLED`, `INTELLIGENCE_TYPESAFE_ENABLED`, model `jev-1.13.0`, pricing/billing fields), LLM flags (`INTELLIGENCE_ENABLED`, `INTELLIGENCE_OPENAI_ENABLED`, `INTELLIGENCE_RESEARCH_ENABLED`, model IDs, prices, `INTELLIGENCE_ENABLED_CONTRACTS`), OCR flags (`INTELLIGENCE_OCR_ENABLED`, `INTELLIGENCE_OCR_VISION_ENABLED`, model, prices, retention source IDs), and caps. Hand the owner the exact list for the release.

### 1. Make the demand engine produce records
- **Spike first:** ~20 real TCEQ AC/TC, OK DEQ `storedpermits` and NMED application PDFs through pdfplumber/Docling. Report usable equipment rows per document and the scanned-page share.
- **Extraction core** in `ingestion/parsers/`: page router, canonical text layer with char→bbox, pdfplumber/Camelot lattice then Docling fallback, multi-page stitching, header synonyms, unit lexicon, narrative driver-phrase rules, exact-span verifier. Feed verified claims through the existing `equipment_claims` / `equipment_evidence` → `equipment_demand` path.
- **Internal gold set** of 50–100 permits in `backend/tests/fixtures/`; field precision is the CI gate.
- **Fetch documents:** TCEQ `{project}-ac.pdf` / `-tc.pdf` for all in-scope pending NSR filings (`tceq_nsr_pending.py`); OK DEQ `storedpermits/{N}.pdf` memos plus the DEQ data-center permit page (lineage keyed on permit number).
- **Exit:** first validated `equipment-demand-v1` records.

### 2. Jev live + LLM + OCR
- **Live mode** beside shadow mode, with per-contract authority settings:
  - *Acts alone:* page/document routing (table / narrative / scan / irrelevant), event-type and lifecycle labels, materiality, docket and RPG triage.
  - *Acts with corroboration:* project matching/merges — high probability **and** a deterministic key agrees (county, substation, permit number, coordinates); otherwise UNKNOWN.
  - *Never:* creating or changing values, arithmetic, demand amounts.
- **Rewrite Jev questions** around demand (electric vs combustion driver in a quoted passage, new vs existing, supply vs demand, lifecycle phase, new large load). Remove the temporary-power framing in `signal_adjudication.py` and `typesafe_evidence_judge.py`.
- **Pin one model** (`jev-1.13.0`) in both paths and store it on every decision; send full relevant passages instead of 1,200-character cuts; abstain below probability thresholds; store probability and model with every decision.
- **LLM equipment proposer:** extend `grounded_candidates.py` with equipment fields (unit, quantity, rating, units, driver, new/existing/standby, dates). Every value carries a verbatim quote and page and must pass the span verifier.
- **OCR:** route scanned pages to the existing OpenAI vision OCR path; label `text_source` by provider/model; run a small bake-off on gold-set scans (OpenAI vision vs Textract vs Mistral OCR) and report precision per dollar.

### 3. Widen document sources
- Federal Register hp/driver parser plus FERC eLibrary fetch for TX/OK/NM CP dockets (no API; eSubscription email or docket sheet).
- NMED: ArcGIS facility layers (`mercator.env.nm.gov/.../aqb/air_facilities/MapServer`) plus crawl of dated WordPress application uploads.

### 4. Early-signal layer (the "know first" goal)
- **ERCOT RPG adapter:** project PDFs (IDs like `25RPG020`), monthly System Planning status reports and TPIT (Word/Excel, parse locally). Extract project ID, utility, county, MW, new load substations, cost, in-service date, tier, CCN requirement. Diff monthly. First confirm whether a listing page exists or files must be discovered by date path.
- **PUCT certificate-docket adapter:** bounded Interchange search for CCN cases mentioning transmission lines or substations, reusing `puct_docket_index.py` and `puct_large_load.py`. First count monthly volume. Extract county, voltage, cost, and "customer has submitted a request for approximately X megawatts."
- **Link** dockets to RPG projects by substation name and county (Jev assists, deterministic key required).
- Comptroller data-center registry; OK HB 2992 land-purchase notices if published; county abatement agendas in pilot counties; water applications; Sentinel-2 change detection at flagged parcels (research spike first).

### 5. Other sectors and regulation
FAA OE/AAA (keyless REST, 8,000-row cap, spatial join to campuses), MSHA Mines.zip (weekly diff), TCEQ aggregate dataset `9ixa-7k3m`, AFDC (**host moved to developer.nlr.gov** — fix any `developer.nrel.gov`), TxDOT/ODOT NEVI awards, SEC EDGAR site MW, ERCOT monthly approved-vs-observed, and a dated regulatory event feed (Texas data-center permit pause → "pending — paused" status).

### 6. Runtime
- Split discovery from extraction: new job type queued after a new/changed document; fetch only new or changed PDFs (content hash).
- Nightly timing: daily sources 3–4 AM Central, twice-daily RRC pending also midday, slow sources weekly. Registry uses `cadence_hours`; check whether `SourceScheduleEpoch` can anchor clock times or add a run-at field.
- Document-source health alerts: wrong content type (JS shell instead of PDF), empty text layer, extraction yield drop, zero new records, listing shrink, overdue, spend near cap, verifier rejection spike.
- Keep `published_at`, `first_seen_at`, `observed_at` complete for every new source; never overwrite first-seen. Start a retained first-signal sample to measure lead time.

## Rules that do not change

Evidence or nothing (hash, page, location on every value); no electric-drive evidence → no electrical MW; unknown is never zero; supply separate from demand; deterministic code owns arithmetic; documented / calculated / estimated / inferred / unknown stay distinct; no routine human workflows in the product (the gold set is internal); never touch FERC CEII; polite access (≤1 request/second where limits are unpublished, declared generic user agent).

## Known gaps to close along the way

- Texas TCEQ research beyond the NSR listing (Title V, PBR 106.512, Records Online, TERP awards, the post-Aug-31 Permit Search Portal) was never completed. Check whether new filings still expose AC/TC PDF links.
- No TCEQ AC/TC PDF has been opened yet; OK `storedpermits/8406.pdf` (West Edmond electric motors) is unverified.
