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
| B5 | Independent6d88 FIX | LOCALLY VERIFIED | 2d6a89d; full verified billable-input ceiling; controller46 tests; defaults blocked |
| C3 | C2,B3 | LOCALLY VERIFIED | cad2e19; controller54 tests; non-RSS/companion transactions/source/fence rechecks |
| C4 | C3 | LOCALLY VERIFIED | 228a5ce/30670dc; controller67 scheduler/monitor/queue tests |
| C5 | C4,D3 shared release | INTEGRATED CANDIDATE | bf24b07;135 focused repeat passes; one prior event timeout UNKNOWN retained |
| C6/B6 | Full6d88 backend failure | LOCALLY VERIFIED | 7f69e75; controller133 tests; external test guard and exact completed Signal-decision reuse |
| C7a | Independent6d88 follow-up FIX | LOCALLY VERIFIED | 1a6249d; controller58 tests; bounded historical planning/current-window assignment;0029 restore52tables MATCH |
| C7b | C7a frozen schema/worker | LOCALLY VERIFIED | Durable structured issue/modification continuation, bounded segments and truthful partial recovery |
| C7b-T | C7b implemented segment interface | LOCALLY VERIFIED | Disjoint adversarial PG crash/fence/recovery tests; separate operations test DB; no product edits |
| D3 | E,D2,B3 | BUILDER VERIFIED; CONTROLLER WAIT | 7187de2;45 focused tests; dormant capture/count/OCR_UNVERIFIED; dispatch joins C5 |
| F1 | B2/D,C frozen interfaces | LOCALLY VERIFIED | c4d0eb6; controller3 offlinejourney/APItests; builder14 browsertests |
| E | C,B2/D | LOCALLY VERIFIED | 3779042; controller170 focused tests; B3 owns actual routing effect |
| E3 | C4 broad regression | LOCALLY VERIFIED | a95a6d3; builder91 current research-interface/jitter tests; final controller gate pending |
| F3 | D3 API/UI release,C5 public helper | INTEGRATED CANDIDATE | 59f4a80;42 PostgreSQL/5 browser builder checks; full controller gates govern acceptance |
| G1 | C2 slot release | LOCALLY VERIFIED | 938c243; controller19 focused tests; final v2/0028 restore replay required |
| G2 | G1 builder slot release | LOCALLY VERIFIED | 304062d; complete metric coverage; paid routes NOT_RUN; proposed labels not acceptance |
| F | E,F1,F3 | INTEGRATED CANDIDATE | Combined authenticated commercial/ops/feedback; frozen runtime/browser receipt governs acceptance |
| G | B–F | INTEGRATED CANDIDATE | Frozen evaluation, activation/rollback/restore/cycle tooling; final gate/review receipt governs acceptance |
| B7 | independent8c FIX, bounded accounting design | INTEGRATED CANDIDATE | Provider response quarantine, exact model and usage-bound validation across queued/legacy routes; durable exposure and reservation/dispatch guard |
| TEST-R2 | full8c failure | LOCALLY VERIFIED | Reproduce and repair suite-order log capture without weakening liveness assertions |
| B7b | consolidated f47 independent FIX | SUPERSEDED | Nonthrowing numeric/audit quarantine and strict raw/fallback byte bounds; no schema changes |
| LIVE | G, authority/access/budget/time | OPEN | Real journey, PC-off/seven daily cycles/owner acceptance |

At most two disjoint READY builders; serialized integration and controller gates.
Independent Sol review covers the final repaired financial/authority/integration candidate.
Green slices do not complete this graph. F1 builds against frozen pure service/result
interfaces without shared schema/provider/worker ownership; F requires integrated proof.
Direction VALIDATE the repaired B5/C6/C7 candidate; controller C7b combined128 tests pass, including nine adversarial cases.6d88 is superseded, not accepted. Full suite recorded
2000 passed/12 failed/12 setup errors/3 skipped/7 subtests. One stale test mock
allowed a synthetic-key auth-rejected provider request; actual suite-wide network
count was not instrumented. No real key or successful model response. Final local acceptance requires a matching immutable
`.artifacts/INTELLIGENCE-20261018/final/release-manifest.json`; no missing receipt,
pending provider comparison, or absent operational proof becomes success.

Direction VALIDATE repaired B7 candidate. Builder combined147 tests pass; controller V5 restore and three-test logging predecessor proof pass. Final full suite/runtime/independent review remain decisive.

| B7c | independent939 FIX | INTEGRATED CANDIDATE | Preserve malformed versus missing usage and billing metadata through every paid adapter |
| F4 | full939 browser failures | LOCALLY VERIFIED | Nine commercial-navigation failures isolated from synthetic health fixture |

| F5 | independent e4fa visual FIX | INTEGRATED CANDIDATE | Scope operations foreground to existing navy; computed contrast plus actual screenshot |

| BROWSE-BOUNDARY-R1 | external near-midnight test failure after cd8d local PASS | VALIDATE | Fresh-session current generation plus deterministic preparation-window parity; tests only |

## Issue #79 Pursuit Workspace integration (separate branch)

| Node | Dependencies | State | Deliverable |
|---|---|---|---|
| UI79-I | checkpoint cd84b77 + origin/main 211d744 | BUILDER FOCUSED CHECKS PASS; CONTROLLER FULL GATES/REVIEW PENDING | Merge commit 4430b58 preserves main intelligence/publication surfaces; need-level server-filtered workspace, navigation/detail repairs, OpenAPI/types, and browser/backend evidence in [UI79 episode](episodes/UI79-integration.md). |

This isolated issue79 node does not replace or complete the main intelligence graph. Main completion gates and UI79 production proof remain independently open.

## PR87 owner-approved follow-up, October 19

| Node | Dependencies | State | Deliverable |
|---|---|---|---|
| PR87-CALL | exact PR87 07d676b; owner local approval | IMPLEMENTED / LOCAL | Cited brief, honest question freshness/checkpoint, source-backed contacts and call preparation in approved UI. Final browser166 pass/1skip; actual local auth/call/restart proof. |
| PR87-PUB | same candidate; failed CI receipt | BLOCKED / cause UNPROVEN | Safe diagnostics and fault recovery tested; fourteen rebuild/rollback checks preserve canonical hashes. Intermittent CI503 not reproduced/repaired. |
| PR87-ACCEPT | PR87-CALL, PR87-PUB | RELEASE FAIL / full backend pending | Source manifest f3a0e328; static/contracts/build/audits pass. Independent Sol confirms contact corrections, retains publication release blocker. |

[Packet](packets/PR87-CALL.md). Source recovery a5e4cf9 paused. Publication, merge and deployment require later explicit approval of the concrete result.
