# Offline intelligence evaluation exports

The four-route evaluation reads a frozen evidence manifest, an independent label
file, and candidate route exports. It does not call models, acquire sources, or
turn proposed thresholds into acceptance rules. Route metrics may be synthetically
supplied for fixture testing; mark those exports with
`metric_provenance.kind: synthetic_fixture`. Persisted production receipts should
use a stable reference and a measured provenance kind. Never copy fixture values
into a measured export.

Create a route template with:

```powershell
py -3 scripts/intelligence_evaluation.py template `
  .artifacts/INTELLIGENCE-20261018/G2-retained-addendum-manifest.json `
  .artifacts/INTELLIGENCE-20261018/four-route-export.json
```

The template binds every route row to the frozen sample and leaves versions and
measurements as `UNKNOWN`. Populate it only from persisted job, provider-call,
queue, evidence, and independent review receipts. Each route must retain its
route version; the top-level context version and frozen sample hash bind the
shared evaluation context. Fabricated-claim counts require a review marker for
every exported prediction. An unreviewed or absent marker leaves the aggregate
count `UNKNOWN`; reviewed rows can explicitly record zero.

Optional numeric fields are `source_freshness_hours`, `latency_ms`,
`end_to_end_latency_ms`, `provider_latency_ms`, `queue_delay_ms`, `cost.amount`,
`cost.uncertain_amount`, and `reserved_cost`. They accept finite non-negative
numbers only; booleans are rejected as numbers. Optional queue outcomes are
`COMPLETED`, `FAILED`, `CANCELLED`, or `UNRESOLVED`. The `schema_valid` and
`useful_independently_reviewed` fields require booleans. Unknown or absent values
remain `UNKNOWN`, and cost is never inferred from latency.

Run the report with:

```powershell
py -3 scripts/intelligence_evaluation.py report <manifest.json> <independent-labels.json> <four-route-export.json> <report.json>
```

Partial routes are identified as `PARTIAL`; they cannot pass the reviewed-sample
gate. Even a complete report remains `PROPOSED` with `accepted: false`. The seven
cycle receipt check proves structural validity only: live operation and evidence
authenticity remain `UNKNOWN` pending external verification.
