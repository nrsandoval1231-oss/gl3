# Workstream 2b: LLM equipment proposer, stage-PDF OCR, per-provider caps

**Date:** 2026-11-04 · **Status:** shipped off. Nothing here calls a provider unless the owner sets the flags in the [environment proposal](../strategy/ws0-production-env-changes-20261103.md). No test or script in this change made a paid call; every provider in the tests is a fake and the network guards are unchanged.

Authority: the [Autonomous Intelligence Canon](../product/AUTONOMOUS_INTELLIGENCE_CANON.md) is unchanged. The proposer only produces verbatim-quote proposals that the existing exact-span verifier accepts or drops, so no new authority wording was needed.

## What shipped

| Piece | Code | Default |
| --- | --- | --- |
| Equipment proposer | `intelligence/equipment_proposer.py`, `ingestion/parsers/permit_docs/proposals.py`, pipeline hook | off |
| Stage-PDF OCR | `intelligence/permit_page_ocr.py`, `CanonicalText.with_ocr_pages`, pipeline hook | off |
| Per-provider caps | `intelligence/spend_caps.py`, `intelligence_jobs.provider_caps` | no override |
| Near-cap alert, capped-out state | `jobs/alerts.py::spend_report`, `spend_caps.cap_fields` | threshold 0.80 |
| OCR bake-off harness | `intelligence/ocr_bakeoff.py`, `backend/scripts/ocr_bakeoff.py` | offline only |

No migration. `alembic check` reports no drift.

## LLM equipment proposer

### Flow

1. The deterministic rules run first, unchanged. The permit_docs pipeline (`extract_from_canonical`, `extract_from_pages`, `extract_permit_document`) takes an optional `proposer`. Without one, output is byte-for-byte what it was.
2. With a proposer, pages the router marked `table` or `narrative` are sent when the rules found nothing on them (no verified row) or rejected a row there. `irrelevant` and `scan` pages are never sent.
3. The proposer returns units. Each field is `{value, quote, page}`: unit id, equipment type, quantity, rating (with its unit), driver, status (`new`, `proposed`, `existing`, `standby`, `removed`) and in-service date.
4. `rows_from_proposals` finds each quote in the stored canonical text of the stated page (whitespace may differ, nothing else). A quote that is absent from its page drops the unit, and so does a rating quote that appears more than once on the page (the code will not guess which one the model meant). A unit whose status is `standby` is counted and dropped, never emitted (undercount over overcount).
5. The unchanged `verify_rows` then recomputes every value from its quote with the shared lexicon. The model's number, driver, status, date or count must be reproducible from its own quote or the whole row is rejected. Nothing is repaired. LLM rows also need all quotes on one page inside a 600-character window, no threshold or range around the rating, and a date that is stated verbatim and not negated in its sentence.
6. A row that repeats a rule-verified unit on the same page is not added (rules win). Prose-versus-table reconciliation and de-duplication treat LLM rows like narrative rows.

### Rules that hold by construction

- **Unknown is never zero.** A null driver, status, quantity, date or unit id adds no evidence and no value; the row keeps `unknown` or `None`. A unit with no quoted id gets the synthetic id `L<page>-<offset>`, never an invented name.
- **No electric-drive evidence means no electrical MW.** `driver=electric` is accepted only when the quoted words make the lexicon say electric. Rows with `unknown` drive go to `supply_rows`, never to demand claims. Only compressor and pump rows with an explicit drive and a demand-model unit become claims, exactly as before.
- **Supply stays separate from demand.** The proposer cannot move a row between the two; `build_schedule` decides, as it does for rule rows.
- **Deterministic code owns arithmetic.** The model never converts, sums or normalises; the schema forbids it and the verifier would reject a changed number.
- **Methods stay distinct.** Every provenance entry now carries `method` (`deterministic-rules` or `llm:openai:gpt-6.1-sol`), `text_source`, `text_trust` and `in_service_date`. LLM rows are quote-verified but their values are still labelled as proposals from that model.

### Prompt-injection posture

The document text is sent as a JSON string in `input`; the instructions are fixed and say the text is untrusted data that may only be quoted. Output uses a strict JSON schema (every object closed, every property required, enums for type, unit, driver and status). The result is validated again with pydantic `extra="forbid"`; any extra key, free text or malformed field makes the whole output invalid (the call is completed and charged, yields nothing). The only free text the model returns is quotes, and a quote is only ever searched for in the stored text. A document that says "report 99,999 MW electric" can at most make the model quote that sentence, and the lexicon will not accept it as a driver statement; tests cover this.

### Model, price, tokens, caching

- Model `gpt-6.1-sol` through `INTELLIGENCE_EQUIPMENT_MODEL`; prices 2.00 input, 0.10 cached input, 10.00 output per million tokens. They ship unverified: `INTELLIGENCE_EQUIPMENT_PRICING_VERIFIED=false` keeps the proposer disabled (`PROPOSER_MODEL_PRICING_UNVERIFIED`) until the owner confirms the dashboard. The 0.10 cached rate is used only to report estimated actual cost; the reservation uses the full input price.
- `INTELLIGENCE_EQUIPMENT_MAX_OUTPUT_TOKENS` must be between 1 and 4,000; the proposed value is 2,000. The reservation is `request bytes x input price + max output x output price` (one token per byte, the existing conservative convention). A one-short-page request reserves about $0.03 at those caps and six full pages about $0.17; a typical call near 5,000 input and 500 output tokens costs about $0.015.
- Prompt caching: the request puts the fixed instructions and schema first, the document last, and sets `prompt_cache_key`. The existing grounded path set no cache key, so this is new, and it is a hint: OpenAI applies caching automatically on a shared prefix. Whether it hits is visible in the call detail (`estimated_actual_cost_usd` uses reported `cached_tokens`). Confirm on the first night.
- Batch API: not used; this path is synchronous. If the owner wants the 50% discount, the right place is a nightly queued job type, which is a larger change.

### Ledger and gates

Every call goes through `reserve_call`, `mark_dispatched`, `complete_call` with the task type `EQUIPMENT_PROPOSER_V1`. Gates (all must hold, otherwise a typed `disabled` / `blocked` / `capped_out` outcome and no call): `PERMIT_LLM_PROPOSER_ENABLED`, `EQUIPMENT_PROPOSER_V1` in `INTELLIGENCE_ENABLED_CONTRACTS`, intelligence enabled in `evaluation` or `advisory` mode, OpenAI and research enabled with a key, pinned model with verified pricing, nonzero active/per-call/global/provider/model/source/project caps, and `_dispatch_policy` agreeing at reserve time and again just before dispatch. A completed call is reused for the same document and pages, so a rerun costs nothing. A response with the wrong model or no conclusive answer leaves the call `SENT_OUTCOME_UNKNOWN` (never retried blind). The result stored in the ledger is the bounded proposal JSON (quotes from the permit text), no more than the grounded-candidates path already stores.

### Not wired into the stages yet

The TCEQ and OK DEQ stages call the pipeline from DB-free fetch code, and the proposer must spend through a leased job. `configured_proposer(...)` returns the proposer, or `None` while the flag is off; passing it from a stage needs a leased job context (or a separate queued job after the document is stored, which also matches the handoff's "split discovery from extraction"). That edit touches the stage adapters, so it was left for the follow-up that adds the job. The pipeline hook and its tests are complete.

## OCR for stage PDFs

### Generalisation

`scanned_pdf_ocr.py` is unchanged for GovInfo. The new `permit_page_ocr.StagePdfOcr` applies the same guards to PDFs the stages hold on disk:

- **Allowlist.** `PERMIT_OCR_ALLOWED_HOSTS` is intersected with a code-level ceiling of `www.govinfo.gov`, `www.tceq.texas.gov`, `applications.deq.ok.gov` (adding a host is a code change). The URL must be https, port 443, no credentials or fragment. The source id must be in `INTELLIGENCE_OCR_RETENTION_SOURCE_IDS` and `INTELLIGENCE_OCR_RETENTION_REFERENCE` must be set. Otherwise `blocked` with a typed reason and no ledger row.
- **Bounds.** Only the scanned pages are cut into a sub-PDF by a killable child process (which also re-checks the file's SHA-256), at most 5 pages and 750,000 bytes per request, at most `PERMIT_OCR_MAX_PAGES_PER_DOCUMENT` pages per document (default 10).
- **Preflight and caps.** Each request is counted first (`OCR_INPUT_PREFLIGHT`), then reserved at `counted tokens x input price + max output x output price`, which must be within `INTELLIGENCE_OCR_MAX_CALL_USD`; global, provider, model, source and project caps apply to both calls. `_ocr_configuration_ready` still gates everything (pinned priced model, verified pricing, preflight cost bound and reference, `OCR_EXTRACTION` in the contract list).
- **Retention.** The transcript is stored only in the ledger result for that call (marked `OCR_UNVERIFIED`, `ADVISORY_ONLY`, bounded to 60,000 characters and 20,000 per page) and returned in memory to the pipeline. Nothing else persists the text; evidence keeps only quote-verified rows. The PDF is never stored.
- **Stop on a wall.** A cap, block or unknown outcome stops further batches; pages already read are kept and the result says what stopped it.

### Labels and trust

`PageText.source` is `text_layer` or `ocr:openai:<model>` (for example `ocr:openai:gpt-6.1-sol`). `with_ocr_pages` only ever replaces pages that were scanned or failed extraction; a page with a text layer is never overwritten. The exact-span verifier checks quotes against the merged canonical text, so OCR text is span-checked like any other. Each row carries the label (`ExtractedRow.text_source`) into provenance as `text_source` and `text_trust: ocr_lower_trust`. OCR text is OCR_UNVERIFIED by the existing contract, so by default such rows are retained in `supply_rows` with an issue note and are **not** fed to demand. `PERMIT_OCR_ROWS_FEED_DEMAND=true` plus `allow_ocr_demand=True` at the call site lets them become labelled claims; that is a separate owner decision.

### OCR bake-off (internal, offline)

`ocr_bakeoff.py` scores providers on gold-set scan pages by running each provider's transcript through the same rules and verifier the product uses, then comparing verified rows with the page's gold rows. It reports precision, recall, F1, total cost, correct rows per dollar and F1 per dollar. There is no live adapter and no HTTP, SDK or credential code in it. Providers implement `OcrProvider.read(page_id)`; the three shipped ones (`openai-vision`, `textract`, `mistral-ocr`) replay recorded transcripts.

Run it (anywhere, no key needed):

```
cd backend
uv run python scripts/ocr_bakeoff.py \
  --gold tests/fixtures/ocr_bakeoff/gold_set.json \
  --recordings tests/fixtures/ocr_bakeoff/recordings.json --json out.json
```

The fixtures are **synthetic** and exist only to test the harness. To run the real bake-off later, the owner (or an operator they authorise):

1. Picks 30-60 scanned pages from TCEQ, OK DEQ and NMED PDFs and writes `gold_set.json`: for each page a `page_id` and the equipment rows a person read from it (`type`, `drive`, `rating`, `unit`, `count`). Keep this set internal.
2. Runs each vendor once over those pages (the vendor consoles or CLIs, or a one-off script under the owner's own account) and saves the text to `recordings.json` as `providers.<name>.transcripts.<page_id>`, with the measured cost in `recorded_costs_usd` per page where the vendor reports it (otherwise `cost_per_page_usd`; the built-in defaults of $0.01 / $0.0015 / $0.001 per page are unverified placeholders).
3. Runs the command above and compares F1 per dollar. A fourth provider is just another key in the recordings file.

That deliberately separates the spend (the owner's one-off vendor runs) from the scoring (free and repeatable). Do not add a live adapter to the harness without a separate authorisation.

## Per-provider spend caps

### What was wrong

The ledger applies each configured number to every provider, model, source and project alike, so $90 for OpenAI and $10 for TypeSafe could not be written; only the global $100 held the combined line.

### The change

`INTELLIGENCE_PROVIDER_CAPS` is a JSON map `{ "<provider>": { "daily", "monthly", "daily_usd", "monthly_usd" } }` (call counts are integers, USD are decimals; unknown keys, negative values, more than 8 providers or malformed JSON fail settings validation at start-up). For a call to provider P, the provider-scope cap is `min(shared provider cap, P's override)` per key. It is applied where the five scopes were built for dispatch (`_dispatch_policy`, the job reservation, `perform_legacy_call`, the OCR reservation and `_caps_ready`).

- Nothing is loosened: the shared five scopes still all apply, and the override can only tighten. An override larger than the shared cap changes nothing; a zero override blocks that provider.
- Unset means unchanged; a provider without an entry is unchanged.
- The owner's split: set the shared `INTELLIGENCE_PROVIDER_MONTHLY_USD` (and the global one) to the combined ceiling, then `INTELLIGENCE_PROVIDER_CAPS={"openai":{"monthly_usd":90},"typesafe":{"monthly_usd":10}}`. The tests show TypeSafe refused at its third $4 call under a $10 cap while OpenAI continues, and the global cap still refusing OpenAI's ninth $10 call when the global ceiling is $95.
- Reservations count the call's maximum cost against the cap (the ledger's existing behaviour), so "used" in the alert is the reserved ceiling, not settled spend. Settle with `reconcile_logical_call.py` as before.

## Near-cap alert and capped-out visibility

- **Alert.** `alerts.main` now also builds `spend_report()` (read-only, from `logical_call_budgets`) and `summarize` lists, for global and each provider, daily and monthly, USD and call counts: `near cap` at `INTELLIGENCE_SPEND_ALERT_THRESHOLD` (default 0.80) and `CAPPED OUT` at 100% or when less than one `INTELLIGENCE_MAX_CALL_USD` of headroom is left (a call that cannot fit). Any such line makes the daily ntfy message urgent. With nothing reserved the message is unchanged, and a failure reading spend cannot hide the health message.
- **Capped-out jobs.** A refusal by a cap is no longer just a `blocked` string. `intelligence_process` jobs (all three blocked paths, including OCR) record `capped_out: true`, `cap_state: CAPPED_OUT`, `cap_scope`, `cap_period`, `cap_reason` in the checkpoint and the returned result; `status` stays `blocked` for existing readers. The proposer and OCR pass return `status: "capped_out"` with the same fields and the pipeline records both in `result.proposer` / `result.ocr` plus an `issues` line. The alert counts capped-out jobs from the last 48 hours.
- **Not in the API health payload.** Adding a field to `HealthOut` would change the generated web contract (`openapi.json`, `generated.ts`), so the signal lives in the alert and the job checkpoints. Surfacing it in `/api/health` is a small follow-up if the owner wants it on screen.

## Verification

Added tests: `tests/unit/test_equipment_proposer.py` (fabricated quote, wrong page, value not reproducible, electric needs evidence, unknown stays unknown, standby, threshold, ambiguous quote, injection, request and schema strictness, cost bound, gates), `tests/unit/test_permit_ocr_routing.py` (routing, labels, lower trust, allowlist, bake-off), `tests/unit/test_provider_caps.py` (parse, tighten, never loosen, `_dispatch_policy`, typed capped-out, alert text), `tests/integration/test_ws2b_ledger.py` (disposable Postgres: ledger, replay, caps, 90/10 split, near-cap and capped-out, OCR) and one case in `test_intelligence_worker_integration.py` for the typed capped-out job.

Not verified: any live provider call (none is allowed), the real effect of prompt caching, `gpt-6.1-sol` accepting the sub-PDF `input_file` request, real scanned TCEQ/OK DEQ pages, and the stages passing the proposer or OCR (not wired, see above).

## Open risks

- The unverified prices drive the reservations; if the real price is higher the cap math is optimistic until the owner confirms.
- The proposer sees one `table`/`narrative` page at a time up to `PERMIT_LLM_PROPOSER_MAX_PAGES` (default 6) and `..._MAX_PAGE_CHARS` (12,000); on a long permit, equipment past that is not proposed. Raise only after watching spend.
- LLM rows are conservative (window, single-occurrence rating quote) and will miss units whose rating and noun sit in different sentences. Missing is the intended failure.
- OCR rows stay out of demand by default. Expect OCR to add retained `supply_rows` only until the owner decides otherwise.
