# G2 — Complete reproducible evaluation measurements

READY after G1 releases a builder slot; independent of D2 provider/context work.
One Luna, no live calls or new schema. Own integration_evaluation.py, root
scripts/intelligence_evaluation.py, their focused tests and evaluation runbook.
Preserve the frozen 90-case manifest and independently proposed labels unchanged.

The existing four-route export scorer must report every requested measurement:
relevance precision/recall, unsafe merges/promotions, independently reviewed
unsupported claims, source freshness, end-to-end and provider p50/p95 latency,
model schema validity, queue delay/outcomes, known/reserved/uncertain cost,
cost per useful independently reviewed result, and resolved-question yield.
Use optional bounded typed export fields with provenance/version references;
missing measurements remain UNKNOWN and never become zero or healthy.
Fabricated-claim count currently defaults absent review markers to zero: repair
that coverage error. Explicit known-zero is valid only for measured/reviewed rows.
Reject bool-as-number, negative/nonfinite amounts/latencies, malformed field
types, duplicate IDs and inconsistent frozen/context/route versions. Do not let
partial paid-route exports satisfy full-run or accepted quality gates.

Keep independent labels separate from candidate outputs; valid UNKNOWN labels
remain unknown rather than making a case falsely safe. All thresholds absent
canonical numeric rules stay proposed; accepted=false. Add a bounded export
template/validation CLI so operators can reproducibly collect four route results
from existing persisted job/call/evidence receipts without model answer relabeling.
No need to run paid routes. Do not invent runtime/model/cost data or infer usage
from latency. Explicitly distinguish synthetically supplied fixture metrics from
real measured exports. Preserve structural-only seven-cycle receipt semantics.

Focused tests, Ruff, mypy; completion artifact with exact changed files,
commands/exit codes, UTC and measured/UNKNOWN limits. No push/deploy/activation.
