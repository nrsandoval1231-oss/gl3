# Intelligence integration work graph

Owner full-build request 2026-10-18; prior graph archived unchanged.

| Node | Dependencies | State | Deliverable |
|---|---|---|---|
| A | none | AUDITED | Exact baseline/dependency map/checklist |
| G0 | A | LOCALLY VERIFIED | Nine tests;90 agent-proposed labels; limited rulesbaseline; paid comparisons NOT_RUN |
| B1 | A | REPAIRED; FINAL REVIEW WAIT | Original FIX preserved; repairs included9aa3117 |
| B2/D | B1 interface | LOCALLY VERIFIED | 9aa3117; controller39 focused tests; final independent review pending |
| C | B1 interface | LOCALLY VERIFIED; C2 REQUIRED | eb2dcf0; controller12 tests; fresh upgrade reveals two metadata drift repairs |
| C2 | C,F1 slot release | LOCALLY VERIFIED | 15de356; controller58 tests and schema check no drift |
| D2 | E shared dispatcher release | WAIT | Exact retained document passages/pages, units/date precision and attribution |
| B3 | E,D2 | WAIT | Task-specific catalog inputs and per-candidate identity advice |
| F1 | B2/D,C frozen interfaces | LOCALLY VERIFIED | c4d0eb6; controller3 offlinejourney/APItests; builder14 browsertests |
| E | C,B2/D | BUILDING | Legacy accounting and controlled question/retrieval continuation |
| G1 | C2 slot release | BUILDING | Read-only restore snapshots/operational receipts and alert plumbing |
| F | E,F1 | WAIT | Combined authenticated commercial/ops journey and owner feedback proof |
| G | B–F | WAIT | Frozen evaluation, activation/rollback/restore/cycle tooling |
| LIVE | G, authority/access/budget/time | OPEN | Real journey, PC-off/seven daily cycles/owner acceptance |

At most two disjoint READY builders; serialized integration and controller gates.
Independent Sol review covers the final repaired financial/authority/integration candidate.
Green slices do not complete this graph. F1 builds against frozen pure service/result
interfaces without shared schema/provider/worker ownership; F requires integrated proof.
