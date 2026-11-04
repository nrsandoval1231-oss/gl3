# Workstream 0 — production environment changes for owner release

**Prepared:** 2026-11-03 · **Status:** proposal only. Nothing here was applied, deployed or tested against a provider. Production configuration changes go through the protected release process and need the owner's confirmation.

Source of truth for every rule below is `backend/src/gridlens/settings.py`, `intelligence/intelligence_jobs.py` (`_enabled`, `_typesafe_billing_block_reason`, `_dispatch_policy`) and `intelligence/scanned_pdf_ocr.py` (`_ocr_configuration_ready`). Template: `deploy/digitalocean/intelligence.disabled.env.example`. Secret values are never listed; `TYPESAFE_API_KEY` and `OPENAI_API_KEY` come from Infisical.

## Findings that change the handoff's assumptions

1. **Caps have five scopes, all required.** A dispatch is refused unless the daily and monthly call caps and USD caps are above zero for global, provider, model, source and project. The handoff table lists only global and provider.
2. **Caps are per value, not per provider budget.** Each scope applies the same number to every provider, model, source or project. The OpenAI 90 / TypeSafe 10 split cannot be expressed; the global $100 monthly cap is the only combined backstop. A real split needs a small code change (propose in workstream 2).
3. **Jev live mode does not exist yet.** Today `JEV_SHADOW_MODE` gates the shadow path only; live authority is workstream 2 code. Turning flags on now buys shadow calls only.
4. **Jev prompts still use temporary-power framing** (`signal_adjudication.py`, `typesafe_evidence_judge.py`). Enabling `SIGNAL_ADJUDICATION` before workstream 2 would pay for the old question.
5. **Existing OCR only accepts GovInfo Federal Register PDFs** (`_validate_source` rejects any other source). It cannot OCR TCEQ, OK DEQ or NMED pages until workstream 2 widens it.
6. **TypeSafe finite billing needs more proof fields** than the handoff lists: a verified total-input token ceiling and a billing reference. Owner-supplied.
7. **Grounded contracts are keyed by question ID** (`TEMP_LOAD_MW`, `UTILITY_ONLINE_DATE`, ...). The equipment proposer needs its own contract name, added with workstream 2 code.

**Recommendation:** apply stage A at the next release only if the owner wants shadow data early. Apply stage B together with the workstream 2 release.

## Stage A — shadow observation (safe to release first)

```env
INTELLIGENCE_ENABLED=true
INTELLIGENCE_MODE=advisory
JEV_ENABLED=true
INTELLIGENCE_TYPESAFE_ENABLED=true
JEV_SHADOW_MODE=true
JEV_SHADOW_DAILY_LIMIT=20
INTELLIGENCE_ENABLED_CONTRACTS=EVIDENCE_SHADOW
INTELLIGENCE_TYPESAFE_MODEL=jev-1.13.0
INTELLIGENCE_TYPESAFE_PRICED_MODEL_ID=jev-1.13.0
INTELLIGENCE_TYPESAFE_INPUT_USD_PER_MILLION=0.042
INTELLIGENCE_TYPESAFE_OUTPUT_USD_PER_MILLION=0
INTELLIGENCE_TYPESAFE_PRICING_VERIFIED=false
INTELLIGENCE_TYPESAFE_BILLING_MODE=input_only
INTELLIGENCE_TYPESAFE_BILLING_MODEL_ID=jev-1.13.0
INTELLIGENCE_TYPESAFE_BILLING_CONTRACT_ID=systemone-v1
INTELLIGENCE_TYPESAFE_BILLING_POLICY_ID=typesafe-total-input-ceiling-v1
INTELLIGENCE_TYPESAFE_BILLING_REFERENCE=<owner: TypeSafe account/invoice reference>
INTELLIGENCE_TYPESAFE_BILLING_VERIFIED=false
INTELLIGENCE_TYPESAFE_MAX_TOTAL_BILLABLE_INPUT_TOKENS=<owner: from TypeSafe account>
INTELLIGENCE_TYPESAFE_TOTAL_INPUT_BOUND_VERIFIED=false
```

Jev stays blocked (`TYPESAFE_BILLING_OR_INPUT_BOUND_PROOF_MISSING_OR_MISMATCHED`) until the owner sets the three `<owner>` or `false` fields to verified values. That is intentional.

## Stage B — LLM and OCR, with the workstream 2 release

```env
# Contracts: add the equipment proposer name once workstream 2 defines it
INTELLIGENCE_ENABLED_CONTRACTS=EVIDENCE_SHADOW,SIGNAL_ADJUDICATION,OCR_EXTRACTION,<equipment-proposer-contract>

# OpenAI (GPT-6.1 Sol). Mark pricing verified only after the dashboard check.
INTELLIGENCE_OPENAI_ENABLED=true
INTELLIGENCE_RESEARCH_ENABLED=true
INTELLIGENCE_OPENAI_MODEL=gpt-6.1-sol
INTELLIGENCE_OPENAI_REASONING_MODEL=gpt-6.1-sol
INTELLIGENCE_OPENAI_REASONING_PRICED_MODEL_ID=gpt-6.1-sol
INTELLIGENCE_OPENAI_REASONING_INPUT_USD_PER_MILLION=2.00
INTELLIGENCE_OPENAI_REASONING_OUTPUT_USD_PER_MILLION=10.00
INTELLIGENCE_OPENAI_REASONING_MAX_OUTPUT_TOKENS=2000
INTELLIGENCE_OPENAI_REASONING_PRICING_VERIFIED=false   # true after dashboard check
# Fast slot: owner chose Sol. Use Sol unless the owner approves gpt-6-luna.
INTELLIGENCE_OPENAI_FAST_MODEL=gpt-6.1-sol
INTELLIGENCE_OPENAI_FAST_PRICED_MODEL_ID=gpt-6.1-sol
INTELLIGENCE_OPENAI_FAST_INPUT_USD_PER_MILLION=2.00
INTELLIGENCE_OPENAI_FAST_OUTPUT_USD_PER_MILLION=10.00
INTELLIGENCE_OPENAI_FAST_MAX_OUTPUT_TOKENS=2000
INTELLIGENCE_OPENAI_FAST_PRICING_VERIFIED=false         # true after dashboard check

# OCR (GovInfo FR scans only until workstream 2 widens the path)
INTELLIGENCE_OCR_ENABLED=true
INTELLIGENCE_OCR_VISION_ENABLED=true
INTELLIGENCE_OCR_PREFLIGHT_ENABLED=true
INTELLIGENCE_OCR_PREFLIGHT_COST_BOUND_VERIFIED=false    # true once reference set
INTELLIGENCE_OCR_PREFLIGHT_COST_REFERENCE=<owner: reference>
INTELLIGENCE_OCR_MODEL=gpt-6.1-sol                      # confirm it accepts the PDF/image input
INTELLIGENCE_OCR_PRICED_MODEL_ID=gpt-6.1-sol
INTELLIGENCE_OCR_INPUT_USD_PER_MILLION=2.00
INTELLIGENCE_OCR_OUTPUT_USD_PER_MILLION=10.00
INTELLIGENCE_OCR_MAX_OUTPUT_TOKENS=4000
INTELLIGENCE_OCR_PRICING_VERIFIED=false                 # true after dashboard check
INTELLIGENCE_OCR_DETAIL=auto
INTELLIGENCE_OCR_PREFLIGHT_MAX_COST_USD=0.10
INTELLIGENCE_OCR_MAX_CALL_USD=0.10
INTELLIGENCE_OCR_RETENTION_SOURCE_IDS=<source IDs of GovInfo FR registry entries>
INTELLIGENCE_OCR_RETENTION_REFERENCE=<owner: retention policy reference>
```

## Caps (both stages; all must be nonzero)

Call counts are provisional (about 4,000 calls per month fits the handoff's $60 estimate). Reset them from the first night's observed volume.

```env
INTELLIGENCE_MAX_ACTIVE_CALLS=2
INTELLIGENCE_MAX_CALL_USD=0.25
INTELLIGENCE_GLOBAL_DAILY_USD=5
INTELLIGENCE_GLOBAL_MONTHLY_USD=100
INTELLIGENCE_PROVIDER_DAILY_USD=5
INTELLIGENCE_PROVIDER_MONTHLY_USD=90
INTELLIGENCE_MODEL_DAILY_USD=5
INTELLIGENCE_MODEL_MONTHLY_USD=90
INTELLIGENCE_SOURCE_DAILY_USD=1
INTELLIGENCE_SOURCE_MONTHLY_USD=20
INTELLIGENCE_PROJECT_DAILY_USD=0.50
INTELLIGENCE_PROJECT_MONTHLY_USD=5
INTELLIGENCE_GLOBAL_DAILY_CALLS=300
INTELLIGENCE_GLOBAL_MONTHLY_CALLS=4000
INTELLIGENCE_PROVIDER_DAILY_CALLS=300
INTELLIGENCE_PROVIDER_MONTHLY_CALLS=4000
INTELLIGENCE_MODEL_DAILY_CALLS=300
INTELLIGENCE_MODEL_MONTHLY_CALLS=4000
INTELLIGENCE_SOURCE_DAILY_CALLS=100
INTELLIGENCE_SOURCE_MONTHLY_CALLS=1500
INTELLIGENCE_PROJECT_DAILY_CALLS=20
INTELLIGENCE_PROJECT_MONTHLY_CALLS=100
```

Every USD cap must be at least the per-call cost ceiling or the call is refused (`*_USD_CAP_INVALID`). Not set: `INTELLIGENCE_FINANCIAL_BUDGET_MODE` stays `finite`; `owner_unlimited` is not recommended under a $100 cap.

## Owner inputs still needed before release

- TypeSafe billing reference, total-input token ceiling, and confirmed price ($0.042 vs $0.0578 per million input tokens).
- OpenAI dashboard confirmation of `gpt-6.1-sol` prices, and whether it accepts the OCR input.
- Decision: Sol or `gpt-6-luna` for the fast slot.
- OCR retention policy reference and the GovInfo source IDs.
- Whether to accept the per-value cap semantics or fund a code change for a true 90/10 split.
- Keys already in Infisical: confirm they are mapped to `TYPESAFE_API_KEY` and `OPENAI_API_KEY` in the production secret set.

## Source activation (registry change, not an environment variable)

The TCEQ application-document stage ([workstream 1b](../engineering/tceq-application-documents-20261103.md)) ships **off**. To turn it on, set `query.application_documents.enabled` to `true` on the `texas-tceq-nsr-pending` entry in `config/sources/registry.v1.json` through the protected release. Nothing in the environment list above enables it, and it uses no paid provider.

- Shipped bounds: `max_downloads` 2, `max_checks` 60, `extract_seconds` 420, at most one request per second to `www.tceq.texas.gov`.
- Memory: the worker holds one unpacked composite PDF (up to 128 MB) in memory plus a copy in the extraction child; POSIX children are capped (`RLIMIT_AS` 2 GiB unpack, 1 GiB workbook), a Windows host would have no cap. Size the worker accordingly before enabling.
- Admission: the NSR job holds the global public-acquisition admission for its whole run. With the stage on that can be up to the 600 s lease instead of seconds. Watch the first enabled runs and the `application_documents` counts in the job result.
- Roll back by setting `enabled` to `false`; retained evidence and states stay.

### OK DEQ document stage activation

The Oklahoma DEQ permit-document stage ([workstream 1c](../engineering/okdeq-permit-documents-20261103.md)) ships **off**. To turn it on, set `query.application_documents.enabled` to `true` on the `oklahoma-deq-public-review` entry in `config/sources/registry.v1.json` through the protected release. It uses no paid provider and no environment variable.

- Enabling alone does nothing useful: the listing does not expose document keys. Add owner-curated `seed_keys` (at most 50), or switch on the capped forward `probe` (`probe.enabled`, a nonzero `probe.frontier` that names where it starts, `max_probes` at most 20, `max_misses` at most 5). Both are explicit, visible in the registry diff, and shipped empty/off. Nothing blind-enumerates integer keys unless an owner turns the probe on.
- Shipped bounds: `max_downloads` 2, `max_checks` 40, `extract_seconds` 300; at most one request per second to `applications.deq.ok.gov` (and to `oklahoma.gov` when `data_center_page.enabled`, shipped off); 40 MB per file; the first 429 or 503 ends the stage.
- Admission: the OK DEQ job holds the global public-acquisition admission for its whole run. With the stage on that can reach the 600 s lease instead of seconds, less the persistence reserve the stage keeps. Watch the first enabled runs and the `application_documents` counts in the job result.
- Memory: a file up to 40 MB is read into memory once for the extraction child; POSIX children are address-space capped, a Windows host is not.
- Evidence effect: a verified schedule reaches the domain only for rows the existing OK DEQ admission accepts, which needs a stated event date (a public-comment window start). Other rows keep the document as evidence and provenance only.
- Roll back by setting `enabled` to `false`: the next run builds listing-only evidence, so current evidence goes back to listing-only. Older evidence versions stay in the database; the key index in source health is kept but unused.

## Workstream 2a live Jev environment proposal

**Prepared:** 2026-11-04 · **Status:** proposal only, for the owner's protected release. Code ships with everything below **off**; nothing is applied, and no provider was called. Design and behavior: [live Jev mode](../engineering/jev-live-mode-20261103.md). This supersedes findings 3 and 4 above once the workstream 2a code is released: live mode now exists and the Jev questions are demand questions.

Prerequisite: the Stage A fields (Jev enabled, pinned model, pricing and billing proof). Live mode needs the same `input_only` / `systemone-v1` / `typesafe-total-input-ceiling-v1` proof, a billing reference, and a verified total-input ceiling, so it stays blocked until the owner supplies them.

```env
# Live Jev, off by default in code. Add to Stage A to enable.
JEV_ENABLED=true
JEV_LIVE_MODE=true
JEV_MODEL=jev-1.13.0
INTELLIGENCE_TYPESAFE_MODEL=jev-1.13.0        # must equal JEV_MODEL when JEV_LIVE_MODE=true
INTELLIGENCE_ENABLED_CONTRACTS=EVIDENCE_SHADOW,SIGNAL_ADJUDICATION

# Per-contract authority. Enable in this order, one release or one week at a time.
JEV_LIVE_ROUTING=true        # acts alone: page/document route
JEV_LIVE_TRIAGE=true         # acts alone: new large load / relevance of filings
JEV_LIVE_LABELS=true         # acts alone: event type, lifecycle, driver, new vs existing, demand vs supply
JEV_LIVE_MATERIALITY=true    # acts alone: material change
JEV_LIVE_MATCHING=false      # acts only with probability >= match threshold AND a deterministic key; enable last

# Thresholds (code defaults shown; conservative)
JEV_ABSTAIN_PROBABILITY=0.80   # below this the effective answer is UNKNOWN
JEV_MATCH_PROBABILITY=0.95     # matching only; must be >= JEV_ABSTAIN_PROBABILITY
JEV_PASSAGE_MAX_BYTES=24000    # full-passage budget; replaces the old 1,200/1,500 character cuts

# Input ceiling and per-call cap. The ceiling must exceed passage budget + request overhead + 2,048 reserve.
INTELLIGENCE_TYPESAFE_MAX_TOTAL_BILLABLE_INPUT_TOKENS=40000   # owner: confirm with TypeSafe
INTELLIGENCE_MAX_CALL_USD=0.01      # 40,000 tokens x $0.042 per million = $0.00168 reserved per call
JEV_SHADOW_DAILY_LIMIT=20           # raise only after watching a week of decisions and spend
```

Notes for the owner:

- **Every flag above defaults off in code** (`JEV_LIVE_MODE=false` and all five authorities `false`). Settings fail validation at start-up if an authority is on without live mode, live mode is on without `JEV_ENABLED`, the model is not a pinned `jev-N.N.N`, `INTELLIGENCE_TYPESAFE_MODEL` differs from `JEV_MODEL`, or the match probability is below the abstain probability. A bad value stops the process rather than running unpinned.
- `EVIDENCE_SHADOW` must be in `INTELLIGENCE_ENABLED_CONTRACTS`; the live label record is produced by the same ledger-guarded call as the shadow comparison, so caps, billing proof and the input ceiling apply unchanged. A call refused by a cap or billing policy leaves a visible failed attempt (`failure_reason`) and no decision.
- Rolling back: set `JEV_LIVE_MODE=false`. Live label records already stored stay as history; `accepted_labels` returns nothing once live mode or the label's authority is off, and nothing in this release consumes them yet.
- The first week should watch: attempts per day, share `abstained` by reason (`BELOW_ABSTAIN_PROBABILITY`, `MODEL_ANSWERED_UNKNOWN`, `NO_DETERMINISTIC_KEY_AGREES`), `failure_reason` counts, truncated passages (`passage_bounds.truncated`), and actual TypeSafe spend against the $100 combined cap.
- **Live matching is inert** until `Project.identity_facts` carries `permit_number`, `substation`, `county` or coordinates: it needs a non-county deterministic key, and today's identity-fact writers do not store one. Enabling `JEV_LIVE_MATCHING` before that changes nothing (it abstains `NO_DETERMINISTIC_KEY_AGREES`); it does no harm.
- **Behavior change needing owner sign-off.** The signal display policy now sends pure supply-side passages (`supply_side` at least 0.8 and weak new-large-load score) to REVIEW instead of SHOW. This applies as soon as the code is released, independent of any flag. Tell me to drop it if you want the old behavior.
- **Ceiling floor.** In live mode startup rejects an input ceiling below 15,048 (request-overhead floor 12,000 + wrapper reserve 2,048 + minimum passage 1,000); 40,000 is comfortable. Probability ordering (match at least abstain) is only validated when live mode is on.
- Rolling back live mode withdraws stored decisions immediately because consumers read them through `accepted_labels`, which checks the current flags and the current `JEV_MODEL`.
- LLM, OCR and per-provider caps are in the next section (workstream 2b).

## Workstream 2b LLM, OCR and per-provider cap environment proposal

**Prepared:** 2026-11-04 · **Status:** proposal only, for the owner's protected release. Code ships with everything below **off**; no provider was called. Design: [LLM proposer, OCR and caps](../engineering/llm-proposer-ocr-caps-20261103.md). This supersedes findings 1, 2, 5 and 7 above once the workstream 2b code is released: the 90 / 10 split is now expressible, stage PDFs can be OCR'd behind an allowlist, and the equipment proposer has its own contract (`EQUIPMENT_PROPOSER_V1`).

### Order to enable

1. **Caps first, with everything else off.** Set the shared and per-provider caps below and watch one nightly cycle of Jev shadow spend against them (the daily alert now lists any scope at 80% or more and any capped-out job).
2. **OpenAI pricing.** Confirm the `gpt-6.1-sol` prices in the OpenAI dashboard, then flip each `*_PRICING_VERIFIED` to `true`. Until then the proposer and OCR stay blocked by design.
3. **OCR on GovInfo scans only** (existing path, unchanged) if wanted; then add the stage hosts and source IDs.
4. **Proposer** (`PERMIT_LLM_PROPOSER_ENABLED=true`) after the stages call it from a leased job. The pipeline hook exists; the stage adapters do not pass a proposer yet, so enabling the flag alone does nothing until that follow-up ships.
5. **OCR rows into demand** (`PERMIT_OCR_ROWS_FEED_DEMAND`) last, and only as a separate decision after reading a week of labelled OCR rows.

### Per-provider caps and the near-cap alert

```env
# Shared scopes: the combined backstop. These are the existing settings.
INTELLIGENCE_GLOBAL_MONTHLY_USD=100
INTELLIGENCE_GLOBAL_DAILY_USD=5
INTELLIGENCE_PROVIDER_MONTHLY_USD=100       # replaces the 90 in the caps section above: this is the shared
                                            # provider scope (the combined ceiling); the map below tightens it
                                            # per provider. The model-scope 90 above stays.
INTELLIGENCE_PROVIDER_DAILY_USD=5
# New. smaller value wins per provider, so this can only tighten:
INTELLIGENCE_PROVIDER_CAPS={"openai":{"monthly_usd":90,"daily_usd":4.5},"typesafe":{"monthly_usd":10,"daily_usd":0.5}}
# Alert when any global/provider scope reaches this fraction of its USD or call cap.
INTELLIGENCE_SPEND_ALERT_THRESHOLD=0.80
```

The per-call, model, source and project caps and every call-count cap stay as listed in the caps section above; the provider map accepts `daily`, `monthly`, `daily_usd` and `monthly_usd` keys if call counts should be split too. The alert needs `NTFY_URL` (and token) as before; it adds lines to the existing daily message.

### LLM equipment proposer (GPT-6.1 Sol)

```env
INTELLIGENCE_ENABLED_CONTRACTS=EVIDENCE_SHADOW,SIGNAL_ADJUDICATION,OCR_EXTRACTION,EQUIPMENT_PROPOSER_V1
INTELLIGENCE_OPENAI_ENABLED=true
INTELLIGENCE_RESEARCH_ENABLED=true
PERMIT_LLM_PROPOSER_ENABLED=true
INTELLIGENCE_EQUIPMENT_MODEL=gpt-6.1-sol
INTELLIGENCE_EQUIPMENT_PRICED_MODEL_ID=gpt-6.1-sol
INTELLIGENCE_EQUIPMENT_INPUT_USD_PER_MILLION=2.00
INTELLIGENCE_EQUIPMENT_CACHED_INPUT_USD_PER_MILLION=0.10
INTELLIGENCE_EQUIPMENT_OUTPUT_USD_PER_MILLION=10.00
INTELLIGENCE_EQUIPMENT_MAX_OUTPUT_TOKENS=2000
INTELLIGENCE_EQUIPMENT_PRICING_VERIFIED=false     # true only after the dashboard check
PERMIT_LLM_PROPOSER_MAX_PAGES=6
PERMIT_LLM_PROPOSER_MAX_PAGE_CHARS=12000
# Existing, required: INTELLIGENCE_ENABLED=true, INTELLIGENCE_MODE=advisory,
# INTELLIGENCE_MAX_ACTIVE_CALLS, INTELLIGENCE_MAX_CALL_USD (>= the per-call bound: about 0.03 for one short page, up to about 0.17 for six full pages).
```

The fast and reasoning slots (`INTELLIGENCE_OPENAI_FAST_*`, `..._REASONING_*`) are separate and unchanged.

**`INTELLIGENCE_MAX_CALL_USD` (owner decision).** It is one global ceiling, not per task. The 2a block above shows `0.01` for live Jev; the proposer cannot run under that (its bound is $0.03 to $0.17). This release proposes `0.25` for both. That does not let Jev spend more per call: Jev's reservation is its verified token ceiling times its price (`INTELLIGENCE_TYPESAFE_MAX_TOTAL_BILLABLE_INPUT_TOKENS` x $0.042 per million, about $0.0017 at 40,000), and its protection is that ceiling plus the TypeSafe provider cap of $10, not this setting. If the owner wants a hard per-task or per-provider call ceiling, that is a small code change and is not shipped. The `0.01` line in the 2a block is superseded when 2b is enabled. `0.25` clears the proposer's bound of about $0.03 to $0.17. Pricing stays `false` (blocking the proposer) until the owner confirms.

### OCR for TCEQ and OK DEQ stage PDFs

```env
# Existing OCR gates (see Stage B above) plus the stage allowlist.
INTELLIGENCE_OCR_ENABLED=true
INTELLIGENCE_OCR_VISION_ENABLED=true
INTELLIGENCE_OCR_PREFLIGHT_ENABLED=true
INTELLIGENCE_OCR_PREFLIGHT_COST_BOUND_VERIFIED=false   # true once the reference is set
INTELLIGENCE_OCR_PREFLIGHT_COST_REFERENCE=<owner: reference>
INTELLIGENCE_OCR_MODEL=gpt-6.1-sol
INTELLIGENCE_OCR_PRICED_MODEL_ID=gpt-6.1-sol
INTELLIGENCE_OCR_INPUT_USD_PER_MILLION=2.00
INTELLIGENCE_OCR_OUTPUT_USD_PER_MILLION=10.00
INTELLIGENCE_OCR_MAX_OUTPUT_TOKENS=4000
INTELLIGENCE_OCR_PRICING_VERIFIED=false                # true only after the dashboard check
INTELLIGENCE_OCR_PREFLIGHT_MAX_COST_USD=0.10
INTELLIGENCE_OCR_MAX_CALL_USD=0.10
INTELLIGENCE_OCR_RETENTION_SOURCE_IDS=texas-tceq-nsr-pending,oklahoma-deq-public-review
INTELLIGENCE_OCR_RETENTION_REFERENCE=<owner: retention policy reference>
# New, off by default. Hosts are capped in code at govinfo, tceq and the OK DEQ applications host.
PERMIT_OCR_ENABLED=true
PERMIT_OCR_ALLOWED_HOSTS=www.tceq.texas.gov,applications.deq.ok.gov
PERMIT_OCR_MAX_PAGES_PER_DOCUMENT=10
PERMIT_OCR_ROWS_FEED_DEMAND=false                       # OCR rows stay out of demand unless true
```

An OCR request is a sub-PDF of at most 5 scanned pages and 750,000 bytes; with the numbers above one counted request of about 5,000 tokens reserves roughly $0.05 against the $0.10 per-call ceiling. Confirm that `gpt-6.1-sol` accepts the PDF `input_file` request before relying on this: the code sends the same request shape as the existing GovInfo OCR.

### Owner inputs still needed for 2b

- OpenAI dashboard confirmation of `gpt-6.1-sol` input, cached and output prices (flip the two `*_PRICING_VERIFIED` flags: equipment and OCR; the OpenAI fast and reasoning slots have their own), and that it accepts PDF input for OCR.
- OCR retention reference and the preflight cost-bound reference.
- Whether OCR-read rows may ever feed demand (default no).
- The bake-off gold set and recorded vendor runs (see the engineering doc), if a different OCR provider should replace OpenAI vision.


## Workstream 6 runtime: schedule, extraction jobs and document alerts

**Prepared:** 2026-11-04 · **Status:** proposal only. Code ships with everything below **off or absent**; the registry was not changed. Design: [runtime jobs](../engineering/runtime-jobs-20261103.md).

### Order to enable

1. Release the code (flag off, no `run_at` in the registry). Behaviour is the in-line stages exactly as before. The daily alert now also lists any document-source finding.
2. Registry PR with the schedule table below (`run_at`, `run_weekday`). Reversible by deleting the fields; the worker then falls back to `cadence_hours` and the 07:00 Central anchor. Watch one night: the first slots after the change are the new times.
3. `DOCUMENT_EXTRACTION_JOBS_ENABLED=true`. The TCEQ listing job then only discovers and queues `document_extraction` jobs; run one night of rule-only extraction in jobs before any model pass.
4. Then follow the 2b order above (caps, pricing, OCR allowlist, `PERMIT_LLM_PROPOSER_ENABLED`). The proposer and stage OCR are now passed from the extraction job, so the 2b note "stages do not pass a proposer yet" is closed for TCEQ once step 3 is on. They are still never passed from the in-line TCEQ path or the OK DEQ stage.

### New settings (all optional; shown with defaults)

```env
DOCUMENT_EXTRACTION_JOBS_ENABLED=false
# DOCUMENT_EXTRACTION_MAX_ENQUEUE_PER_RUN unset: the stage's own max_downloads (1-5 per run);
# set 1-200 to queue more jobs per listing run
DOCUMENT_EXTRACTION_FAILED_RETRY_HOURS=24       # a failed document version rests this long
# Document-source alert thresholds (daily ntfy message)
DOC_ALERT_MIN_BASELINE_DOCS=5                   # documents needed before a yield baseline exists
DOC_ALERT_YIELD_DROP_RATIO=0.5                  # recent rows per document <= baseline x (1 - this)
DOC_ALERT_EMPTY_TEXT_RATIO=0.5                  # share of recent documents with no text layer
DOC_ALERT_LISTING_SHRINK_RATIO=0.5              # in-scope filings now vs the earlier maximum
DOC_ALERT_ZERO_NEW_DAYS=14                      # no new record for this many days
DOC_ALERT_OVERDUE_MULTIPLIER=2.5                # x cadence_hours with no document-stage run
DOC_ALERT_REJECTION_SPIKE_RATIO=0.6             # verifier-rejected share of candidate rows
DOC_ALERT_REJECTION_MIN_ROWS=10
```

No new infrastructure. The worker already runs every job kind; `document_extraction` takes the same per-source public-acquisition admission and lease renewal as `ingestion`.

### Proposed per-source schedule (America/Chicago; for the owner to confirm)

Nothing here is applied. Times sit in the 03:00-04:00 window after overnight publisher batches and are spread out so sources on one host do not start together (the three TCEQ sources are ten minutes apart). There is no cross-source host lock: only a per-source admission, so a long run can still overlap its neighbour, and each stage paces its own requests to at most one per second. `run_at` is local wall-clock time and follows daylight saving time (a skipped spring-forward time runs at the next valid minute; an ambiguous fall-back time runs once).

| Source id | Today | Proposed registry fields |
| --- | --- | --- |
| `texas-tceq-nsr-pending` | 24 h at 07:00 | `"run_at": ["03:00"]` |
| `texas-tceq-egu-registrations` | 24 h at 07:00 | `"run_at": ["03:10"]` |
| `texas-tceq-construction-noi` | 24 h at 07:00 | `"run_at": ["03:20"]` |
| `texas-tceq-temporary-batch-plants` | 24 h at 07:00 | `"run_at": ["03:30"]` |
| `oklahoma-deq-public-review` | 24 h at 07:00 | `"run_at": ["03:40"]` |
| `texas-rrc-drilling-permits` (pending) | 24 h at 07:00 | `"run_at": ["03:35", "12:00"]` |
| `texas-rrc-flare-vent-exceptions` | 24 h at 07:00 | `"run_at": ["03:50"]` |
| `federal-register-eis` | 24 h at 07:00 | `"run_at": ["03:15"]` |
| `texas-puct-large-load-filings`, `texas-puct-large-load-dockets` | 24 h at 07:00 | `"run_at": ["03:25"]`, `["03:45"]` |
| `texas-ercot-large-load-status`, `spp-thermal-interconnection` | 24 h at 07:00 | `"run_at": ["03:55"]`, `["03:05"]` |
| `texas-jeti-applications`, `texas-jeti-agreements` | 24 h at 07:00 | `"run_at": ["03:12"]`, `["03:22"]` |
| `texas-tdlr-tabs-data-centers`, `taylor-development-newsflash` | 24 h at 07:00 | `"run_at": ["03:18"]`, `["03:28"]` |
| City permit feeds (Austin, Fort Worth, San Antonio, Albuquerque, El Paso) | 24 h at 07:00 | `"run_at"` from `03:32` in 4-minute steps |
| `houston-weekly-permits` | 24 h at 07:00 | weekly: `"cadence_hours": 168, "run_at": ["04:00"], "run_weekday": 0` (owner: confirm the publisher's weekday) |
| `dallas-monthly-permits` (slow) | 24 h at 07:00 | weekly: `"cadence_hours": 168, "run_at": ["04:00"], "run_weekday": 6` |
| Annual stack-claim sources (`f17-*`, disabled) | 8760 h | unchanged |
| News feeds (`*-news`, 1 h) | hourly | unchanged (hourly UTC cadence) |

Two limits. `run_at` needs a local-daily schedule (a multiple of 24 hours), so it cannot express "every 12 hours"; twice a day is two clock times. A weekly source with `run_at` and no `run_weekday` falls on the weekday its schedule epoch was created. Changing the fields starts a new schedule epoch (the existing mechanism); history is kept.
