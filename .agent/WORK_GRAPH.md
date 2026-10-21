# Work graph — PR102 follow-up integration

Authority remains the owner request, PRD, Finish Contract, and approved UI canon. PR102 and PR103 were merged upstream; this branch is a follow-up integration candidate, not an update to either merged PR.

| Node | Status | Evidence / next action |
|---|---|---|
| F1–F5 implementation | Integrated | Exact retained read: 14 cases, 79/79 fields; see curated release manifest and prior controller receipts. |
| PR103 approved UI preservation | Integrated | Main protected card, styles, tokens, navigation, and approved workspace behavior retained from `cf440a2`. |
| F8 schedule/workspace integration | Focused validation passed | Browser 62/62, typecheck, and build passed; exact receipt is ignored `artifacts/PR102-FINISH/F8-COMPLETION.json`. |
| F9 dependency audit repair | Integrated | Only pypdf 6.19.0 to 6.20.1; focused parser/audit proof retained. |
| F11 independent-review repairs | Integrated | Typed identity-link response/replay and additive, fail-closed supply scenarios; prior ff05491 code review and full gates passed. |
| F12 restored browse recovery | Validated on prior candidate | Retained-only derived rebuild restored queue200; source tables, snapshots, jobs, and calls unchanged. |
| F13 diagnosis recovery | Corrected | Initial broad-scan explanation rejected before edits; actual legacy path measured at 161 SQL/about 2.4s. |
| F14 unfiltered legacy detail | Focused validation passed | 6979fa4; 21 focused tests/static checks; identical 65-field payload at 37 SQL/about 60-67ms. Scoped paths preserved. |
| Final frozen-candidate gates | READY / pending | Freeze the resulting implementation plus this handoff, then run mandatory full gates. Prior ff05491 results do not transfer. |
| Persisted runtime/restart proof | Pending on final candidate | Repeat real authenticated queue/card/five-viewport/restart proof, exact payload and raw/snapshot/job/call comparisons. |
| Independent review | Pending on final candidate | Sol reviews exact F14 integration plus final deterministic/runtime receipts; no parent completion while data gates remain blocked. |
| Retained category acceptance | BLOCKED | Three required categories remain absent: utility constraint, conflicting dates, bridge power. |
| Live provider and release | BLOCKED / UNKNOWN | Separate authorization, source permission, budget, and runtime proof remain required. |

The strong-ID reconciliation helper is tested but not wired into ordinary enrichment. Production linking remains project-scoped; cross-project links require attributed review through the correction API. Migration order is `0035_reconciled_identity`, then `0036_buying_chain_corrections`. Do not widen scope or treat focused green checks as parent-goal completion.
