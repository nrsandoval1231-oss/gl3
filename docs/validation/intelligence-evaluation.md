# Intelligence evaluation and operating receipts

This offline tool compares exactly four route exports on one content-hashed
evidence sample. It does not invoke providers, mutate retained production
evidence, or establish live operation. The evidence export must contain
`{"cases":[{"case_id":"...","evidence":{...}}]}` and must not include
labels. `freeze` writes canonical evidence plus its SHA-256. Keep the resulting
file unchanged and distribute its hash to the independent label author and all
route runners.

Labels are a separate JSON document with independently authored provenance:

```json
{
  "provenance": {"author": "reviewer name", "method": "evidence review", "created_at": "2026-10-18"},
  "labels": [
    {"case_id": "case-1", "decision": "SHOW", "relevant": "YES", "safe_to_merge": "NO",
     "safe_to_promote": "NO", "question_expected": true}
  ]
}
```

Do not copy model output into labels or claim owner review without the owner’s
actual review. Supported human labels are `YES`/`NO`; missing labels invalidate
the report. A prediction export has `sample_sha256` and four `routes`. Each
route contains a `predictions` array keyed by `case_id`. The required route IDs are
`rules`, `rules_jev_advisory`, `rules_fast_extract`, and
`rules_jev_extract_deep`, matching the four planned evaluation paths. An
unrun path must have no prediction rows: its metrics stay `UNKNOWN` or report
missing predictions, and its costs are never treated as zero. Rows may include `relevant` (`YES`,
`NO`, or `UNKNOWN`), `merge_proposed`, `promotion_proposed`,
`fabricated_claim`, `latency_ms`, `cost` (`{"status":"KNOWN","amount":0.01}`
or `{"status":"UNKNOWN","uncertain_amount":0.02}`), `reserved_cost`, and
`question_resolved`, and an independently audited `fabricated_claim` marker.

```powershell
cd backend
uv run python ..\scripts\intelligence_evaluation.py freeze ..\sample-evidence.json ..\frozen-evidence.json
uv run python ..\scripts\intelligence_evaluation.py report ..\frozen-evidence.json ..\independent-labels.json ..\predictions.json ..\evaluation-report.json
uv run python ..\scripts\intelligence_evaluation.py receipts ..\daily-receipts.json --output ..\receipt-check.json
uv run pytest tests/unit/test_integration_evaluation.py
```

The controller-frozen retained-corpus evidence has the compatible top-level
`cases` export shape; preserve its exact rows and sample hash. Freezing alone
does not prove the sample covers adversarial categories. Record those strata
in a separate sample-selection note if/when a representative subset is drawn.

The report includes precision, recall, labeled coverage, missing predictions,
unsafe merge and promotion proposals, fabricated-claim audit counts, p50/p95
latency, known/subtotal/uncertain/reserved costs, and resolved-question yield.
Unknown labels and missing predictions do not increase success. A missing cost
keeps total known cost `UNKNOWN`, while a known subtotal remains visible.
`PROPOSED` means the comparison was structurally scoreable; `accepted` always
remains false. The retained-corpus PRD gate is at least 30 independently
reviewed records with 24 or more correct decisions. The report exposes that
gate as PASS/FAIL/UNKNOWN from separately authored `decision` labels and route
outputs. A controller must bind thresholds and independent review to the exact
artifact before any gate can be recorded as accepted.

## Proposed performance comparison

The local cloned-corpus baseline during300 mocked RSS records used eight samples
per endpoint, with sequential reads alongside a separate ingestion thread. Its p95
values were health26.51ms, operations120.89ms,
changes39.51ms and the20-record opportunity page3119.63ms. These are local fixture
measurements, with no accepted production SLO or claim that eight samples are a
stable population estimate.

Proposed investigation thresholds are a p95 exceeding the matching endpoint's
recorded baseline above, measured with the same corpus,300-record workload and
configuration. Collect at least30 samples per endpoint before judging a regression;
preserve both runs and report variability. These thresholds are proposed comparison
triggers, not owner acceptance or a production latency promise. In particular, the
opportunity-page baseline is already a visible performance limitation.

Safety comparisons require no unsupported promotions, fabricated accepted claims,
or false identity merges under the existing canonical rules. Model precision,
recall, validity, resolved-question yield and cost per useful result remain UNKNOWN
for unrun paid routes. Propose numerical quality/economic promotion thresholds only
after authorized measurements and independent labels exist; do not invent provider
usage, an owner budget or acceptance from an empty report.

## Seven daily operating cycles

Receipt input contains `{"receipts":[...]}` with exactly seven unique consecutive
local dates. Optional `schedule` metadata sets `timezone` and local `time`; the
defaults are `America/Chicago` and `07:00`. Each row must include a unique
`cycle_id`, timezone-aware `scheduled_at`, `started_at`, and `completed_at`.
Every daily cycle includes due-source status receipts plus content-addressed
`pc_off` and `runtime` evidence. Document-level `evidence` includes
`backup`, `restore`, and `owner_review` campaign references and digests. Due
source IDs must be unique within each cycle, and receipt timestamps cannot be
in the future. Due-source success must be at least 95%; a source that misses
twice consecutively needs referenced visible-alert evidence. Duplicate dates
and shortened same-day replay cannot produce seven days. The checker verifies
date continuity, schedule bounds, and reference digests. It returns `live_proof: UNKNOWN` even when
structurally valid: supplied JSON can be fabricated. Operational proof needs
independent verification of scheduler/provider/job receipts, actual PC-off
execution, runtime and source outcomes, backup and restore results, and the
owner’s real review. Local fixture checks prove only local code behavior.
