# B7b — fail-closed provider quarantine exceptions

Objective: close consolidated independent-review findings on frozen
`f47f151973ffc430aee5587c83bf1bf666d3c41c` (tree
`e60d2a5266c9c4caa61f512e7cd5b4e7f14c88f7`) in the existing isolated
`feat/intelligence-integration-20261018` worktree. Parent B7 contract remains binding.

Ownership: Luna typesafe_guard_builder owns integrations/logical_calls.py,
legacy_calls.py, intelligence_provider.py; intelligence/intelligence_jobs.py,
scanned_pdf_ocr.py and narrowly required provider-envelope callers; their affected
unit/integration tests and billing runbook notes. Root owns control/delivery docs.
No migrations, product gates, UI redesign, live provider/source calls or activation.
Only the dedicated settlement test/app database pair on task loopback PostgreSQL.

Required invariants:
- Any model/usage breach persists quarantine even when a conservative estimate
  overflows the ledger numeric limit. Unrepresentable exposure is UNKNOWN or
  unbounded, never a fabricated finite invoice or refunded reservation.
- Audit handling cannot throw out of quarantine for recursive, invalid or large
  response data. Measure original response bytes before truncation; retain safe
  bounded identity/usage/hash metadata, and enforce the final stored byte limit.
- Ordinary completion/failure cannot terminalize a quarantined call. Only explicit
  attributable reconciliation can release it; reservation and dispatch guards persist.
- Settlement/reconciliation updates assign copied JSON values. Fresh sessions must
  observe matching stored payload/digest and no repeated exposure charge.
- Parsed HTTP-200 status/refusal/invalid-output errors preserve available model,
  usage and response metadata before semantic rejection across queued, legacy and
  OCR/follow-on paths. Unparsed metadata remains UNKNOWN. Documented conclusive
  HTTP failures remain distinct; do not assume refusal or invalid output is unbilled.
- OpenAI cache/context identity includes pinned priced model, pricing verification,
  rates, enforced output limit and response-guard policy. No historical relabeling.

Verification: adversarial numeric/recursive/oversized response tests; queued and
legacy caller tests; both OCR paths; complete/fail rejection after quarantine;
fresh-session settlement/reconciliation idempotence and digest equality; existing
OFF/zero-cap and positive fake controls. One sequential affected PostgreSQL test
command, Ruff, mypy and diff checks; root then re-freezes, runs complete final gates,
V5 restore non-replay rechecks, runtime/browser checks and independent Sol review.

Risk: financial/authority boundary. Two materially distinct repair attempts for a
reproduced failure; preserve negative evidence, escalate material uncertainty.
Handoff: exact files/commands/results/UTC/limits, no self-certification. Tokens and
unmeasured metrics stay UNKNOWN. No push, merge, deployment, spend or outreach.

Clarification: a valid exact-model response may retain NULL usage/cost when verified conservative reservation fully bounds the call. Missing usage alone does not establish a billing breach. Preserve this positive case; invalid or reported over-bound usage and unvalidatable error envelopes remain guarded. Independent reviewer confirmed this boundary.

Recovery: Luna's final combined run had158 passes/1 new test assertion failure.
Terra verified canonical succeeded-job/UNKNOWN-checkpoint semantics and repaired
only that assertion;78 affected tests passed in26.44s. Independent pre-freeze
inspection then found deeply nested JSON parsing and invalid legacy token-type
escapes. Terra owns narrow provider/legacy exception guards and regression tests
for these findings, using the same isolated database. No other builder edits those
files. This is a revised evidence-backed repair packet, not a repeated unchanged
attempt; final candidate still needs independent review and complete gates.

Consolidated specialist scope additionally covers both OCR successful-response input versus preflight-count and output versus enforced-limit checks, conservative exposure reconciliation, and preserved request ID/raw-body hash/size in oversized parsed-error audit. Four independent findings are consolidated before testing; no other architecture expansion.

Specialist handoff: terminal25 unit (0.62s),19 ledger (8.91s),45 worker (21.56s),6 two-path OCR (4.49s) passes; scoped Ruff/mypy/diff pass. A new legacy fixture omitted required SIGNAL_ADJUDICATION abstract and failed before dispatch; fixed without product relaxation. Partial combined command has no terminal claim. Controller final full suite covers integrated candidate.
