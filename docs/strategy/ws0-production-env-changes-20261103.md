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


### Federal Register hp/driver evidence activation

The notice hp/driver parser ([workstream 3](../engineering/widen-document-sources-20261103.md#a-federal-register-hpdriver-evidence)) ships **off**. To turn it on, add `"hp_driver_evidence": true` to `query` on the `federal-register-eis` entry in `config/sources/registry.v1.json` through the protected release. It uses no paid provider, no environment variable and no new request: it reads the GovInfo PDF text the existing companion fetch already captures.

- Effect: for a PDF captured in a run, `Evidence.provenance["fr_hp_driver"]` carries verified hp/kW/MW ratings with driver, count, state and verbatim quotes (PDF page, character span inside `Evidence.abstract`). Electric drive counts as `electric_demand_evidenced` only when the same phrase states it. Nothing else changes: the evidence hash, abstract, interpretation and equipment admission are identical with the flag on or off.
- Not retroactive: evidence is immutable and keyed by the PDF hash, so a notice whose PDF was already stored is not re-annotated. Only newly seen PDF bytes carry the block.
- The flag is validated as a boolean on `federal-register-eis` only. Roll back by removing it or setting `false`; stored blocks stay.

### FERC eLibrary

Nothing to activate: GridLens makes no FERC eLibrary request (there is no compliant machine-readable path; see the [finding](../engineering/widen-document-sources-20261103.md#b-ferc-elibrary)). `ferc_elibrary.py` only builds a reference link from a docket a notice already states and rejects CEII/privileged markers. No registry entry exists and no environment change is needed.

### NMED application documents activation

The NMED source `new-mexico-nmed-air-applications` ([workstream 3](../engineering/widen-document-sources-20261103.md#c-nmed)) ships **off twice**: the entry has `"enabled": false`, and `query.application_documents.enabled` is `false`. It uses no paid provider and no environment variable. To turn it on, in order and through the protected release:

1. Set `enabled` to `true` on the entry. This alone makes one request per day to `https://www.env.nm.gov/public-notices/` (about 1.3 MB) and records the application PDF links as listing records. No PDF is fetched.
2. Optionally add owner-curated exact upload URLs to `query.application_documents.seed_urls` (at most 50; each must already be in the canonical spelling `https://www.env.nm.gov/...` with no port, query or fragment, and match the upload-path policy in the engineering note).
3. Set `query.application_documents.enabled` to `true` to fetch and read documents. Shipped bounds: `max_downloads` 2, `max_checks` 40, `extract_seconds` 300; at most one request per second to `www.env.nm.gov`; 40 MB per file; the first 429 or 503 ends the stage and stores `not_before` in source health.
- Admission: the job holds the global public-acquisition admission for its whole run; with the stage on that can reach the 600 s lease less the persistence reserve. Watch the `application_documents` counts in the first enabled runs.
- Memory: a file up to 40 MB is read into memory once for the extraction child; POSIX children are address-space capped, a Windows host is not.
- Evidence effect: records are retained evidence. No NMED equipment-demand admission rule exists, so enabling does not create demand, needs or cards; a rule is a separate, reviewed change. Dates are upload months only (`publication_date` is the first of the month, precision `month`).
- Roll back by setting either `enabled` to `false`. Evidence versions and the check index stay.

### ERCOT planning documents activation

The source `texas-ercot-rpg-projects` ([workstream 4a](../engineering/early-signal-sources-20261103.md)) ships **off twice**: the entry has `"enabled": false`, and `query.documents.enabled` is `false`. It uses no paid provider, no credential and no environment variable, and needs no migration. To turn it on, in order and through the protected release:

1. Set `enabled` to `true` on the entry. This alone makes about five requests per day (the RPG hub, up to `max_meetings` meeting pages, the planning page). No document is fetched and **nothing is stored**: with `query.documents.enabled` false the ERCOT document records are withheld, because a bare listing line is not evidence.
2. Optionally add owner-listed System Planning update PDFs to `query.documents.seed_urls` (at most 20; each an exact `https://www.ercot.com/files/docs/YYYY/MM/DD/<name>.pdf` URL).
3. Set `query.documents.enabled` to `true` to fetch and read documents. Shipped bounds: `max_downloads` 6, `max_checks` 40, `extract_seconds` 300; at most one request per second to `www.ercot.com`; 40 MB per PDF and 12 MB for the workbook; the first 429 or 503 ends the stage and stores `not_before` in source health. Dated-path PDFs are asked again after 14 days; the TPIT workbook (replaced in place monthly) after about a day, and a changed hash starts the monthly diff.
- Admission: the job holds the global public-acquisition admission for its run; watch the `application_documents` counts in the first enabled runs.
- Evidence effect: retained evidence only. The first TPIT snapshot writes about 925 baseline row observations (labelled baseline, not new projects); they are re-emitted unchanged (idempotent) on later runs until the next monthly snapshot, which writes only its diff rows. The TPIT state key is the stable `tpit`; the workbook URL is replaced in place monthly and may be renamed. `Evidence.provenance["early_signal"]` holds the states; no schema change.
- Memory: a PDF up to 40 MB is read into memory once for the extraction child; POSIX children are address-space capped, a Windows host is not.
- Roll back by setting either `enabled` to `false`. Evidence versions and the check index stay.

### PUCT certificate-docket activation

The source `texas-puct-ccn-transmission-dockets` ships **off twice**: `"enabled": false` and `query.documents.enabled` `false`. No credential, provider, environment variable or migration. To turn it on, in order:

1. Review the PUCT site policies (their sub-pages were not read during the build; `robots.txt` is a 404 and no challenge was seen). Then set `enabled` to `true`: four requests per day (two case-style searches and two Excel exports for the `window_days` window, default 60) and one listing record per matching certificate docket, carrying only case-style facts.
2. Set `query.documents.enabled` to `true` to read filings. Shipped bounds: `max_downloads` 4 dockets per run (about five requests each: filings list, two document pages, two PDFs of at most 15 MB), `extract_seconds` 300, one request per second to `interchange.puc.texas.gov`; the first 429 or 503 ends the stage and stores `not_before`. `seed_urls` must stay empty.
- Links to ERCOT projects are computed in the same run from the RPG source's retained evidence; with the ERCOT source off or empty every link is **unknown** and no link record is written. Activate the ERCOT source first if links are wanted.
- Evidence effect: retained evidence only, no needs or cards. A stated customer request is documented text with its verbatim quote, not demand.
- Roll back by setting either `enabled` to `false`.

### More early-signal sources (workstream 4b) activation

Four sources ([workstream 4b](../engineering/early-signal-sources-more-20261103.md)) ship **off**: `"enabled": false`, and, where a document stage exists, `query.documents.enabled` `false`. None uses a paid provider, a credential, an environment variable or a migration. Each is retained evidence only: enabling creates no project, need or card. Before enabling any of them, the owner should read the publisher's site terms (only `robots.txt` was checked) and the first run should be watched for the `application_documents` counts.

1. **`texas-comptroller-dc-registry`** (weekly, no document stage). Set `enabled` to `true`: one request per run to `comptroller.texas.gov`; about 177 observations on the first run (one per registry row), then one new evidence version per changed or new row. Roll back with `enabled: false`.
2. **`oklahoma-occ-data-center-notices`** (daily). Set `enabled` to `true`: one request per day to `oklahoma.gov`; one listing observation per notice (link-text facts only). Set `query.documents.enabled` to `true` to read each notice's first two pages (`max_downloads` 6, 20 MB cap, `extract_seconds` 300, at most one request per second, first 429/503 ends the stage and stores `not_before`); scanned forms stay listing-only. `seed_urls` must stay empty.
3. **`texas-county-abatement-agendas`** (daily, Haskell County only). Set `enabled` to `true` and `query.documents.enabled` to `true`. With documents off the source stores **nothing** (a bare agenda link is not evidence of an abatement). One listing request plus up to `max_downloads` (2) agenda PDFs per run from `www.haskellcountytx.gov`; scans are withheld and retried only after the permanent-failure window. `counties` must stay `["haskell"]`. Adding Milam would need a reviewed exception for the third-party CMS redirect; Medina is blocked by its host's `robots.txt`.
4. **`texas-tceq-water-rights-pending`** (weekly). Set `enabled` to `true`: one request per run to `www.tceq.texas.gov`; about 110 listing observations. Set `query.documents.enabled` to `true` to read notice packages (`max_downloads` 2, up to 40 MB each, the first four pages read, `extract_seconds` 300). A notice can be 30 MB or more: watch worker memory in the first enabled runs.
- Memory: a PDF up to 40 MB is read into memory once for the extraction child; POSIX children are address-space capped, a Windows host is not.
- Roll back by setting `enabled` (or `query.documents.enabled`) to `false`. Evidence versions and the check index stay.
- Sentinel-2 change detection has no activation: it is a [research spike](sentinel2-change-detection-spike-20261104.md).

### NMED air-facility layers

`nmed_air_facilities.py` (ArcGIS MapServer, layers 0 to 6) is a bounded, read-only reader with no registry entry and no caller in the job path: the layers carry no AI or permit number and no date, so records would be dateless observations with no join. Nothing is shipped to activate. A future consumer (an identity join) is separate work; its config shape is validated by `nmed_air_facilities.valid_config` and the host is pinned in `nmed_http.py`.
