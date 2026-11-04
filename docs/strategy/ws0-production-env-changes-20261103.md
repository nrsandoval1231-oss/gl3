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
- Rolling back: set `JEV_LIVE_MODE=false`. Live label records already stored stay as history; consumers must ignore them because `accepted_labels` only honours decisions from a live-mode, pinned record, and nothing in this release consumes them.
- The first week should watch: attempts per day, share `abstained` by reason (`BELOW_ABSTAIN_PROBABILITY`, `MODEL_ANSWERED_UNKNOWN`, `NO_DETERMINISTIC_KEY_AGREES`), `failure_reason` counts, truncated passages (`passage_bounds.truncated`), and actual TypeSafe spend against the $100 combined cap.
- Not covered here (PR 2b): LLM and OCR flags, equipment-proposer contract, per-provider cap semantics.
