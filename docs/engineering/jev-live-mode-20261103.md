# Live Jev mode (workstream 2a)

**Date:** 2026-11-03 · **Status:** code complete, ships **off**. Nothing here enables a provider, spends money or changes production configuration; the proposed environment is in the [workstream 0 proposal](../strategy/ws0-production-env-changes-20261103.md#workstream-2a-live-jev-environment-proposal). Authority wording is in the [canon](../product/AUTONOMOUS_INTELLIGENCE_CANON.md#typesafe-jev-decision-authority).

Scope is WS2a only. The LLM equipment proposer, OCR routing and per-provider cap semantics are PR 2b and are not touched.

## What changed

1. **Live mode beside shadow mode.** `JEV_LIVE_MODE` (default `false`) lets the existing EvidenceJudge call also produce *live label decisions*. Shadow mode (`JEV_SHADOW_MODE`, default `true`) is unchanged and remains the only active path until live is switched on. `run_shadow` runs when either flag is on.
2. **Per-contract authority settings**, all default `false` and all requiring `JEV_LIVE_MODE`:

   | Setting | Tier | Labels it may write (closed vocabularies only) |
   | --- | --- | --- |
   | `JEV_LIVE_ROUTING` | acts alone | `document_route`: table, narrative, scan, irrelevant |
   | `JEV_LIVE_LABELS` | acts alone | `event_type`, `lifecycle_phase`, `driver`, `novelty`, `side` |
   | `JEV_LIVE_MATERIALITY` | acts alone | `material_change` |
   | `JEV_LIVE_TRIAGE` | acts alone | `new_large_load`, `relevant` (dockets, RPG and other filings) |
   | `JEV_LIVE_MATCHING` | acts with corroboration | `same_project` (inert until `Project.identity_facts` carries deterministic keys; see Corroboration) |

3. **Questions rewritten around demand.** Electric versus combustion driver in the quoted passage, new versus existing, demand versus supply, lifecycle phase, new large load, and document route. The temporary-power, bridge-power and rental framing is gone from both Jev paths (`typesafe_evidence_judge.py` and `signal_adjudication.py`).
4. **One pinned model.** `JEV_MODEL` (default `jev-1.13.0`) is the default in both paths; `jev-latest` is no longer used anywhere. The billing/ledger identity is still `INTELLIGENCE_TYPESAFE_MODEL`; settings validation requires the two to be equal and versioned (`jev-N.N.N`) whenever live mode is on.
5. **Full passages.** The 1,200 (EvidenceJudge) and 1,500 (signal) character cuts are replaced by a byte budget; see below.
6. **Abstention.** Below `JEV_ABSTAIN_PROBABILITY` (default 0.80) the effective EvidenceJudge label is UNKNOWN. Matching needs `JEV_MATCH_PROBABILITY` (default 0.95, never below the abstain probability when live mode is on) *and* a deterministic key other than county. The signal display policy uses its own fixed 0.8 decisiveness threshold and does not read these settings, so turning live mode on or off cannot change signal SHOW/HOLD/REVIEW.

## Authority is structural

`backend/src/gridlens/intelligence/jev_live.py` is the only place a live decision is built, and it cannot express a value:

* A `LiveLabel` is constructed only for a `(authority, field)` pair in `AUTHORITY_FIELDS`, with a value drawn from that field's closed `StrEnum`. A number, quantity, rating or free text is rejected at construction. UNKNOWN can never be accepted; a corroborated-tier label cannot be accepted without a deterministic key; the model must be a pinned `jev-N.N.N`.
* `Judgment` (the parsed provider answer) contains only enum-typed labels. The parser rejects any "choice" outside the enum, so a number cannot be smuggled in as an answer.
* `jev_live` imports no persistence, SQLAlchemy or equipment module. The record is a JSON document written to the decision's **own** `evidence_judge_runs` row (`result["live"]`, or `deterministic["live"]` when there is no result). `validate_live_record` rejects unexpected keys and non-label fields before it is stored.
* Tests prove it: unit tests for the label and record guards, and a DB-backed test that seeds an accepted interpretation carrying `demand_mw` and equipment values, runs a live decision with every authority on, and asserts every project, need, observation, evidence and interpretation row (including the JSON values) is byte-identical afterwards.

Consumers read decisions through `accepted_labels(result)`. It returns labels only while live mode and that label's own authority are **currently** enabled, only from a decided record whose model (record and label) equals the current `JEV_MODEL`, and only for accepted labels. Setting `JEV_LIVE_MODE=false` (or one authority off) therefore withdraws every stored decision at once; the rows stay as history. Nothing in this PR consumes them yet: routing, triage and matching consumers belong to the extraction and early-signal workstreams that need them, and each will read this one function. **No live decision currently changes ingestion, a project, a merge or the UI.** Live matching records an accepted/UNKNOWN verdict with its corroborating key; the merge itself is not wired.

### Corroboration

`corroborating_keys` compares the candidate project's `Project.identity_facts` (project side) with the evidence's `Interpretation.assessment` (evidence side) and the retained source passage. A match needs at least one **non-county** key (permit number, substation or coordinates); county is only a supporting second key and never acts alone (`LiveLabel` refuses to be accepted otherwise). A missing key on either side never agrees; county is never inferred from prose; substation and permit number agree on an exact normalized field match or as a whole token (at least four characters) in the evidence's retained source text; coordinates agree within about 1 km when both sides carry them.

**Where the evidence side comes from.** `Interpretation` rows are created only in `ingestion/service.py` from the deterministic interpretation and admission code and the structured source adapters (checked by search: no Jev, LLM or intelligence module creates one); the retained passage is source text. No Jev or LLM output is written to either, and the model-proposed equipment fields of PR 2b live in `EvidencePackage`, which this module never reads. A key therefore cannot be supplied by a model-extracted claim.

**Matching is inert today.** Current `Project.identity_facts` writers store `project_name`, `site`, `site_candidates` and similar, not `permit_number`, `substation`, `county` or coordinates, so no deterministic key can agree and live matching abstains with `NO_DETERMINISTIC_KEY_AGREES` until a later change makes the project side carry those keys. This PR deliberately adds no identity-fact writer.

## Fail closed

* Provider error, timeout, invalid response, unexpected model, the ledger's cap and billing policy, and any problem deriving the record all leave **no decision**. The attempt is stored with status `failed`/`timeout`/`invalid`, `deterministic["live"]` holding an `abstained` record with its reason, and `deterministic["failure_reason"]` holding the (truncated) block reason, so a capped-out job is visible, not silently skipped.
* Live decisions are derived inside the existing logical-call ledger path (`perform_legacy_call`, task `EVIDENCE_SHADOW`), so the five-scope caps, `input_only` / `systemone-v1` / `typesafe-total-input-ceiling-v1` billing proof, billing reference and total-input token ceiling apply unchanged. No new provider path, no new infrastructure.
* The tests use fakes and an injected provider callable; the network guards are untouched.
* Only the exception class name is persisted for provider and parsing errors (never provider text); a ledger policy block also keeps its controlled block reason (`LegacyCallBlocked:<reason>`). A path that is blocked before dispatch (for example the contract is no longer allowlisted) also writes an abstained live record.
* A queued job created under `evidence-judge-v1` keeps its checkpoint `contract_version` and is **not** replayed against the demand questions: it is closed with error class `LegacyContractReplayUnsupported` and no provider call.

## Passages and the input ceiling

`jev_passages.py` replaces the fixed cuts. Per request:

* one UTF-8 byte is counted as one billable token (tokens never exceed bytes);
* request overhead (questions, state, JSON) is measured, not guessed;
* `WRAPPER_RESERVE_BYTES` (2,048) covers opaque provider wrapper tokens;
* budget = min(`JEV_PASSAGE_MAX_BYTES` (24,000), `INTELLIGENCE_TYPESAFE_MAX_TOTAL_BILLABLE_INPUT_TOKENS` minus overhead minus reserve, and the estimate policy's 16,384-byte request limit when that narrow policy is selected).

A passage that does not fit is cut at a paragraph or sentence boundary and `passage_bounds` (`chars_total`, `chars_sent`, `truncated`) is sent with the request, so a partial passage is never presented as whole. The worst-case size of that metadata is reserved inside the budget (the estimate policy's 16,384-byte limit is therefore never exceeded; a test asserts it and that the policy does not block the request), and the bounds are persisted on the attempt: `result["passage_bounds"]` on valid runs in both the direct and queued paths, and `deterministic["passage_bounds"]` on every queued attempt.

**Minimum passage.** If the passage was cut to nothing, or to fewer than `MIN_PASSAGE_CHARS` (200) characters, every enabled authority abstains with `PASSAGE_TRUNCATED_BELOW_MIN`. When live mode is on, startup also rejects an `INTELLIGENCE_TYPESAFE_MAX_TOTAL_BILLABLE_INPUT_TOKENS` below `REQUEST_OVERHEAD_FLOOR_BYTES` (12,000) + reserve (2,048) + minimum passage (1,000) = 15,048, so a ceiling that cannot hold a usable request is a configuration error rather than silent truncation. The ledger still reserves the full verified ceiling per call and checks reported usage against it, as before.

## Storage and migration

**No migration.** `model`, probability and decision are stored in existing columns: `evidence_judge_runs.model`, `result["probabilities"]` (Jev's probability for each chosen label, kept on every valid run including shadow-only runs), `result["passage_bounds"]`, `result["live"]` (model, per-label probability, outcome, reason) when live, and `signal_decisions.model_version`, `dimensions` (the probabilities, plus `question_set`: `demand-v1`, or `temporary-power-v2` for a response to the retired questions) and `decision`. `alembic check` is expected clean and was run.

## Backward compatibility with stored decisions

* **Behavior change needing owner sign-off: supply-side filings.** The display policy now returns REVIEW instead of SHOW when `supply_side` is at least 0.8 and `new_large_load` is below 0.7 (a pure generation/interconnection/utility passage is not a demand signal). It abstains to REVIEW, never HOLD. It applies to new adjudications only, but it changes which ambiguous filings reach SHOW; keep or drop it at the owner's direction.
* **Signals keep `POLICY_VERSION = "signal-display-v2"`.** Bumping it would hide every stored SHOW/HOLD decision from the readers that filter on it. Stored decisions written under the old temporary-power questions remain valid and are not re-adjudicated; only new adjudications use the demand questions.
* `validated_dimensions` still accepts a response answering the old six questions (a call dispatched before the rewrite and completed after, or a stored receipt). `map_dimensions` maps `commercial_relevance` to `new_large_load` and `temporary_power_relevance` to the demand-driver dimension.
* `Judgment` keeps `temporary_power_hint` (default UNKNOWN, no longer asked) and defaults the new labels to UNKNOWN, so rows stored under `evidence-judge-v1` still validate. The EvidenceJudge schema is now `evidence-judge-v2`, so v1 attempts do not suppress new input keys.
* `power_relevance` keeps its key (consumed by `research_recommendation`); only its question text changed to demand.
* The retired EvidenceJudge `temporary_power_hint` question is no longer scored for v2 rows by `evidence_evaluation`; the new demand labels (event type, driver, novelty, side, lifecycle phase, new large load, document route) are scored.
* New signal dimensions: `new_large_load`, `electric_driver`, `combustion_driver`, `supply_side`. The display policy treats a pure supply-side passage (`supply_side` at least the abstain probability with a weak new-large-load score) as REVIEW, never SHOW.

## Deliberate limits and open items

* Not done (PR 2b): LLM equipment proposer, OCR routing, per-provider cap split.
* `jev_task_context.py` advisory contracts (for example `POWER_ACTIVITY_HINT_V1`) still carry older wording; they are a third path outside this scope and unchanged.
* The shadow scan skips deterministic exact matches, so live labels (including routing) are produced for ambiguous/new evidence in that scan. Routing of pages and documents for the new extraction pipeline will call the same judge on its own passages.
* Probabilities are Jev's own and uncalibrated; thresholds are conservative defaults to be tuned from the first week of recorded decisions, not validated accuracy.
* A latent bug was fixed on the way: the queued shadow path serialized a date in the request digest and would have raised on any real evidence (`published_at`). It is covered by the new worker-path tests.
* Live acceptance with the real provider is not claimed; no paid call was made.

## Verification

See the PR description for exact commands and results. Unit: `tests/unit/test_jev_live.py`. DB-backed: `tests/integration/test_jev_live_storage.py` (live off, label record, no value change, matching with and without a key, provider failure and timeout, ledger worker success, over-cap block, provider error, unpinned model).
