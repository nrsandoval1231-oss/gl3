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
| D2 | E shared dispatcher release | LOCALLY VERIFIED | 4e758e5; controller55 tests; current-context/page/unit/attribution guards |
| B3 | E,D2 | LOCALLY VERIFIED | 2c8f9c3; combined controller88 tests; API compatibility site repaired in C3 |
| B4 | E,G1 slot release | LOCALLY VERIFIED | 057899f; late billing audit; combined88 controller tests after harness repairs |
| B4-H | B4,G2 ownership | LOCALLY VERIFIED | 304062d; portable actual0028 trigger on TEST DB; restore summary MATCH |
| C3 | C2,B3 | LOCALLY VERIFIED | cad2e19; controller54 tests; non-RSS/companion transactions/source/fence rechecks |
| C4 | C3 | BUILDING | Fixed planner/heartbeat lanes independent of slow job in existing runtime |
| C5 | C4,D3 shared release | WAIT | Killable finite acquisition, fenced renewal and shared public admission |
| D3 | E,D2,B3 | BUILDING | Dormant source-permitted scanned-PDF capture/count/extraction; service/API serialization waits C3 release |
| F1 | B2/D,C frozen interfaces | LOCALLY VERIFIED | c4d0eb6; controller3 offlinejourney/APItests; builder14 browsertests |
| E | C,B2/D | LOCALLY VERIFIED | 3779042; controller170 focused tests; B3 owns actual routing effect |
| G1 | C2 slot release | LOCALLY VERIFIED | 938c243; controller19 focused tests; final v2/0028 restore replay required |
| G2 | G1 builder slot release | LOCALLY VERIFIED | 304062d; complete metric coverage; paid routes NOT_RUN; proposed labels not acceptance |
| F | E,F1 | WAIT | Combined authenticated commercial/ops journey and owner feedback proof |
| G | B–F | WAIT | Frozen evaluation, activation/rollback/restore/cycle tooling |
| LIVE | G, authority/access/budget/time | OPEN | Real journey, PC-off/seven daily cycles/owner acceptance |

At most two disjoint READY builders; serialized integration and controller gates.
Independent Sol review covers the final repaired financial/authority/integration candidate.
Green slices do not complete this graph. F1 builds against frozen pure service/result
interfaces without shared schema/provider/worker ownership; F requires integrated proof.
