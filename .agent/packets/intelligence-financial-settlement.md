# B4 — Late financial settlement without changing remote outcome

READY after G1 slot/ops/snapshot ownership release. Sol narrow architecture
direction 2026-10-18: MODIFY, separate financial settlement from provider outcome.
This is not a new tribunal or completion verdict. One Luna; no paid/production
calls, credential access, push/merge/deploy or actual operator reconciliation.

Own models.py, logical_calls.py, additive0028 migration, new host operator CLI
backend/scripts/reconcile_logical_call.py, narrow ops/snapshot settlement projection,
focused tests and runbook. D2/B3 own dispatcher/provider and must remain untouched.
Preserve all other workers' changes; exclusive settlement test/application DBs.

Add append-only LogicalCallSettlement: call FK, actor, receipt_ref, UTC settled_at,
nullable actual_cost_usd/input_tokens/output_tokens; unique(call_id,receipt_ref),
at least one measured field. No arbitrary JSON payload or provider response copy.
Keep LogicalCall measurement columns fill-once projections. One row-lock transaction
requires a dispatched call in SENT_OUTCOME_UNKNOWN/COMPLETED/FAILED/RECONCILED.
Nonempty authenticated host-operator actor and external receipt ref, strict finite
nonnegative values. Exact same receipt+values idempotent; mismatched receipt payload
or overwrite of known measurement conflicts. Fill NULL only; preserve original
response/digest/status/fence/finished_at/outcome reconciliation/active slot fields.
Billing proof alone never changes UNKNOWN outcome or authorizes retry.

First measured cost above max adds positive delta atomically to each original
daily/monthly budget row and records visible overage. Never subtract/refund reserved
ceiling merely because actual lower or unknown. Concurrent receipts charge once.
Use exact Decimal constraints; unknown tokens remain NULL. Do not infer from time.
Ops must preserve terminal cost-unknown exposure including RECONCILED. Snapshot
streams settlement audit rows/digest; final restore rehearsal reruns after0028.
Expose measured input/output-token subtotals and known/unknown coverage separately
when settlement supplies only one token field; do not erase a known input count
because output remains NULL, or present a partial subtotal as the full total.

Host-only CLI uses existing DB access authority; no new auth or provider endpoint.
Default dry-run, call UUID/action outcome|settle/actor/receipt/expected status/state
identity/explicit measured fields; apply requires --apply --expect-digest from
preview, locks/rechecks exact identity before commit. Redact response/text/secrets;
emit safe post-state receipt. Outcome action only SENT_OUTCOME_UNKNOWN→RECONCILED
via existing routine with explicit conclusive outcome evidence; missing proof fails.
No action dispatches, retries, releases unknown exposure blindly or mutates source
facts. Document actor is host-authorized operator, not an independent reviewer.

Tests real isolated PG: completed late cost leaves immutable result/token NULL;
RECONCILED metadata preserved; same receipt replay/concurrent distinct receipts;
overmax original budget period positive delta/no refund; unknown outcome+active slot
unchanged by billing; stale preview; terminal exposure; restore audit omission.
Fresh/repeat migration/schema check, Ruff/mypy/focused tests; exact completion files,
UTC, commands, measured/UNKNOWN metrics. Controller rerun and final Sol independent
review required; no builder self-acceptance. Two distinct repairs then canonical
reconstruction. No downgrade/delete production ledger or settlement history.
