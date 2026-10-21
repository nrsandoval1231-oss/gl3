# Work graph — PR102 follow-up integration

Authority remains the owner request, PRD, Finish Contract, and approved UI canon. PR102 and PR103 were merged upstream; this branch is a follow-up integration candidate, not an update to either merged PR.

| Node | Status | Evidence / next action |
|---|---|---|
| F1–F5 implementation | Integrated | Exact retained read: 14 cases, 79/79 fields; see curated release manifest and prior controller receipts. |
| PR103 approved UI preservation | Integrated | Main protected card, styles, tokens, navigation, and approved workspace behavior retained from `cf440a2`. |
| F8 schedule/workspace integration | Focused validation passed | Browser 62/62, typecheck, and build passed; exact receipt is ignored `artifacts/PR102-FINISH/F8-COMPLETION.json`. |
| Final frozen-candidate gates | Pending | Controller must run full required gates against the resulting merge commit. |
| Persisted runtime/restart proof | Pending | Controller-owned; no live-provider or production claim. |
| Independent review | Pending | Must review the exact frozen candidate after final gates. |
| Retained category acceptance | BLOCKED | Three required categories remain absent: utility constraint, conflicting dates, bridge power. |
| Live provider and release | BLOCKED / UNKNOWN | Separate authorization, source permission, budget, and runtime proof remain required. |

The strong-ID reconciliation helper is tested but not wired into ordinary enrichment. Production linking remains project-scoped; cross-project links require attributed review through the correction API. Migration order is `0035_reconciled_identity`, then `0036_buying_chain_corrections`. Do not widen scope or treat focused green checks as parent-goal completion.