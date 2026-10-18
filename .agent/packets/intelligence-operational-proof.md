# G1 — Reproducible snapshots, restore comparison and operational receipts

One Luna after C2/D2 and E/F ownership releases. Existing deployment/queue only.
Own scripts/intelligence_snapshot.py, jobs/operational_receipts.py, narrow
intelligence_operations.py + jobs/alerts.py + deploy/digitalocean/gridlens-run.sh,
operations tests/runbook. Do not edit settings.py/worker.py while E owns them.
Controller will serialize one Settings field `operational_receipt_file: str = ""`
after E release; use getattr(settings,"operational_receipt_file", "") meanwhile.
No API/UI redesign or canonical changes. API response model additions, if needed,
owned narrowly by this packet after F release; keep generated types consistent.

Read-only DB snapshot tool outputs bounded metadata/counts/streamed deterministic
digests of evidence/jobs/logical_calls/budgets/watch state, reservation statuses,
known/uncertain amounts and migration head; no raw text, secrets or credentials.
Compare before/after restore; fail closed if identities/exposure missing/changed.
Document no dispatch during restore; duplicate intent reuses same logical ID and
SENT_OUTCOME_UNKNOWN cannot replay. Controller local rehearsal already preserved
19326 evidence,95 jobs,2 synthetic calls,12 budgetrows; repeat final candidate proof.

Collect/read versioned operational receipt JSON from explicitly configured server
file path, default absent => UNKNOWN. No new database/platform. Size/schema/date
bounds; treat content as data, never commands. Separate configured/reported from
verified restore (requires comparison metadata plus attributable reference). Never
claim file authenticates cloud/PCoff/owner acceptance. Keep seven-daily receipt
validator as structural only. Backup host script may atomically write upload-return
receipt to fixed host path only after successful existing pipeline; include UTC,
objectref/deployedSHA where safely available, no secrets. Bind read-only receipt
mount API/worker only if explicit disabled optional compatible config; do not activate
cloud destinations. No fake last_verified_restore timestamp from a successfulbackup.

Extend existing alerts deterministic summary for uncertain calls, oldqueued work,
monitor quarantine and logicalfailed work using persisted counts; no notification
send during tests/build. Existing configured destination remains untouched. Ops view
reads actual receipt status with evidence/reference and UNKNOWN when absent; nullable
measured metrics stay truthful. Required tests malformed/missing/future/oversized
receipts, restore mismatch/unknown preserved, alertsummary off/unknown, no external
calls, no secrets. Reuse backend pipeline/deployment-script fixtures.

No source/provider activation, spend, productionwrites, push/deploy/outreach.
Handoff exactfiles/checks/UTC/limits in ignored artifact; controller gates/finalreview.

Financial reporting must include all-time outstanding exposure, including terminal
COMPLETED/FAILED provider outcomes whose actual cost remains NULL and whose ledger
ceiling is still reserved. Conclusive response does not mean a free call. Show
known subtotal separately from full total UNKNOWN; no latency-derived cost/usage.
Compute complete aggregates in SQL and mark detail-list truncation; a 5000-row
window must not silently undercount spend or outstanding reservations. Source due
counts use one latest receipt per occurrence, parse success/freshness explicit.
