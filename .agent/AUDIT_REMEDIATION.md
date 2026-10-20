# Audit remediation, 2026-10-20
Base: 9e9e188bdf2825a8305a0e9eac0b23f0af1df47e. Owner request and Downloads/GL3_Deep_Repository_Audit_2026-10-20.md govern repairs. Existing architecture and UI preserved. No new architecture initiative; existing Tribunal not reconvened.

| Node | Dependencies | State | Ownership / acceptance |
|---|---|---|---|
| AUDIT-CORE | baseline verified | READY | Luna A: ranking endpoint, correction transactions, limiter, decision aggregation, queue digest dedup; exact focused PostgreSQL gates |
| AUDIT-RETAINED | baseline verified, PR96 inspected | READY | Luna B: news policy/reassessment, retained-only buying-chain jobs; retained corpus and ingestion/idempotency proof |
| AUDIT-WORKSPACE | CORE joined | WAIT | error/filter identity, morning changes and persisted baseline; browser and API proof |
| AUDIT-OPS-DOCS | baseline verified | READY controller inspection | measured browse benchmark; current docs/archives/runbooks/links; governance proposal, no settings mutation |
| AUDIT-ACCEPT | all code/docs frozen | WAIT | exact candidate full gates; Sol independent review; coherent PR; no merge/deploy |

Two disjoint builder worktrees, independent disposable DBs, serial cherry-pick integration. Retry budget two materially distinct repairs; no paid calls/fetch/production replay. Preserve historical receipts, credentials, accounting and owner deployment hold. Timings UTC recorded per completion; tokens/config load UNKNOWN unless measured. Repository main equals audit baseline; #94/#95 merged, #96/#97/#98 open. Production not freshly observed.
