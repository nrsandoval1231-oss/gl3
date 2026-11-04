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
