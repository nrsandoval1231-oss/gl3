# Current work ownership

READY graph: `BROWSE-AVAILABILITY-20261029`, base `37cc949b`.
Owner-authorized [bounded packet](packets/BROWSE-AVAILABILITY-20261029.md) defines
acceptance and boundaries; [AGENTS](../AGENTS.md) and [finish contract](FINISH_CONTRACT.md) govern.

| Node | Owner | Dependencies | Current state |
| --- | --- | --- | --- |
| Diagnose deployed state and baseline | Sol | none | observed, baseline recorded |
| Identity invalidation and rollover | Luna/low backend | diagnosis | frozen; focused PostgreSQL checks passed |
| Group SQL request path | Luna/low performance | baseline | frozen; measured retained-data comparison |
| Browse UX and state | Luna/low frontend | API snapshot metadata | frozen; focused and full browser checks |
| Related source operation diagnosis | Luna/low source | current job evidence | complete: external RRC failure; Austin13 tests pass |
| Integrate and required gates | Sol | three implementation nodes | final gates running |
| Independent candidate review | root Astra/high | frozen diff and verification | scoped review complete; full/live gates pending |
| PR and production repair | Sol and root | review | pending; root owns production writes |
| Authenticated live desktop/mobile acceptance | root | deployed candidate | baseline session available; final pending |

An assignment is not completion. Exact current candidate, measured evidence and
unknowns remain in [current checkpoint](CURRENT_STATE.md). Prior graph preserved
[verbatim](archive/BROWSE-AVAILABILITY-20261029/WORK_GRAPH.md).
