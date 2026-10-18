# Logical call settlement runbook

`reconcile_logical_call.py` is a host-only operator tool. It uses the configured
application database authority. The actor value identifies the host-authorized
operator; it is not an independent review or approval.

First preview a settlement. Use an external receipt reference and provide at
least one measured field. Empty fields remain unknown.

```powershell
python scripts/reconcile_logical_call.py <call-uuid> --action settle `
  --actor <operator-id> --receipt-ref <billing-receipt> `
  --expected-status COMPLETED --actual-cost-usd 0.004200 --input-tokens 900
```

Review the digest and redacted call/budget identity printed by the dry run. Apply
the same request with `--apply --expect-digest <preview-digest>`. The command
locks the call, rechecks status and identity, then appends the settlement receipt
and fills only previously unknown measured projections. A stale preview fails
without applying changes.

For a dispatched call whose provider outcome is independently known, use
`--action outcome --expected-status SENT_OUTCOME_UNKNOWN --outcome-proof
<conclusive-evidence-reference>`. This action uses the existing reconciliation
routine and requires the same dry-run/apply digest sequence. Billing alone never
resolves an unknown outcome. Neither action dispatches, retries, releases an
unknown active slot, changes source facts, or contacts a provider.

Settlement is append-only. Reusing the same receipt with identical actor and
measurements is idempotent; any changed payload for that reference conflicts.
Existing measurements are fill-once. Actual cost below the reservation does not
refund reserved budget. A measured cost above the reserved ceiling adds only the
positive overage to each original daily and monthly budget row. Unknown token
fields remain unknown and are reported separately from known input/output
subtotals.
