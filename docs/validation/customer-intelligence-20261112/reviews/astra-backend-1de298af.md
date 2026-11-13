# Independent backend repair review — 1de298af

Exact revision: `1de298af047f09a32e9a0349f41410a55bc1791e`, inspected in `/workspace/gl3-backend-fix`. Scope is the eight-file delta from independently reviewed `4b6d0f92`: API read transaction policy, commercial extraction, customer grouping/projection, generation snapshots, three test files and the performance reconciliation document. No product edits were made by this reviewer.

**Scoped disposition:** No new material correctness, identity or privacy defect was identified in this repair. The inspected implementation preserves the earlier safety corrections and makes a coherent bounded-query/compact-response change. The completed affected integration receipt supports scoped acceptance of this repair. This is not final whole-candidate acceptance: full remote gates and fresh controlled performance acceptance remain separate.

## Review findings

- Commercial facts now travel in the existing grouped SQL result. Full detail preserves claims, sources, calculation inputs and original change states; list cards remove those large arrays while retaining supported totals, qualifiers, completeness, coverage, precise timeline display fields, conflict counts and scenario scalars. This is a deliberate card/detail contract distinction, not evidence deletion. The reviewed UI follow-on tolerates optional card sources and priority components.
- Actual fact/engineering/development content still passes the existing batched saved-history privacy projector before compact serialization. The skipped privacy path applies when those inputs are empty, leaving generated scalar/constant unknown-state output. The final contact-token scrub remains. No new authorization channel or public raw-history path was introduced.
- Recent capacity/timing events are frozen during generation build, including original before/after states and causal references. Read requests use the frozen events and retain stale-generation withholding. The bounded event query shares the prior material-change context read and preserves the newest three commercial events per project.
- Contact SQL materializes only requested resolved groups and aggregates physical-asset project IDs once. Primary-company restrictions, method/name candidate predicates, deterministic selection and current native attribution/suppression guards remain in place. The added old/new SQL equivalence test explicitly labels its authorization seam and does not masquerade as native-source coverage.
- `SET LOCAL jit=off` follows REPEATABLE READ setup and applies only to PostgreSQL in the read transaction. It does not change global or retained configuration. The added test checks rollback restoration and transaction isolation.
- Postfix and unrecognized phase qualifiers abstain instead of becoming complete site capacity. Recognized prefix phases retain partial scope; the explicitly recognized across-all total remains supported. Earlier canonical-name/address scoping, numeric-bound and timeline repairs remain intact.
- Existing query-count/scale gates were not loosened in this delta. New tests replacing whole-object card/detail equality instead assert display/identity parity and full-detail evidence preservation; this is appropriate for the intentionally compact card contract.

## Independent execution and inspected receipts

From the repair worktree's `backend/`, using the task-local environment without printing credentials:

```bash
PYTHONPATH=src .venv/bin/pytest tests/unit/test_customer_phase_scope.py tests/unit/test_customer_intelligence.py tests/unit/test_customer_scope.py tests/unit/test_customer_capacity_alternatives.py -q
```

Independent result: **95 passed in 1.01 seconds**. These tests do not use the busy shared database.

Inspected coordinator/implementation receipts, distinguished from independent reruns:

- `/workspace/task-runtime/commercial-query-equivalence.log`: **2 passed in 5.02 seconds**, covering previous-versus-reconciled candidate SQL and local JIT behavior.
- `/workspace/task-runtime/backend-fix-lint.log`: lint passed; **599 files already formatted**.
- `docs/engineering/customer-commercial-read-performance-20261113.md` records unchanged scale/query gates, actual native-positive/current-suppression coverage, full-detail/card checks and earlier failed moving-source receipts with explicit limits.

The completed `/workspace/task-runtime/backend-fix-integrated.log` was subsequently inspected: **251 passed, 3 warnings in 654.02 seconds; EXIT_CODE=0**. Warnings are one existing test-client deprecation and two connection-already-established/isolation-options warnings in the cross-boundary summary fixtures. The coordinator identifies this as the exact `1de298af` affected matrix, including unchanged scale/query-budget/customer-results checks and the complete power-need-brief module. The log reports no deselections. It is a coordinator execution independently inspected here, not an independent database rerun. Database tests were deliberately not launched independently against the concurrently busy shared test database. No retained or production database operation occurred.

## Performance and release limits

Query consolidation and payload bounding are supported by source inspection and the named tests, but query count alone is not a latency or scalability acceptance result. Aggregating the frozen project payload within the grouped query must still be measured at realistic account sizes. Shared-machine test contention prevents interpreting suite duration as a controlled latency comparison. Fresh matched artifacts and final full-suite/CI results must be reconciled before claiming a performance pass.

The subsequently finalized `docs/validation/customer-intelligence-20261112/performance/read-repair/` receipt was independently checked: all **15 artifact hashes** match its manifest; all **12 sets of 30 raw samples** reproduce the reported median and nearest-rank p95 exactly. Its README hash is `af09c5c00c7f5d70fc92e475df04508b30df9c43627768f5256ae76e7ee3b453`; summary hash is `d22de0863c58c20442dfc38e5ec3aa7ac9bf34155b2beb2cbbfacbe57e06840f`. Metadata binds baseline `bf75d327` and repair `1de298af` with unchanged before/after backend manifests. This is artifact verification, not an independent benchmark execution.

The unchanged canonical harness restores sampled steady SQL count to **53** for both baseline and repair. Repair response bytes at page sizes 1/25/50 are **7,176 / 57,126 / 109,376**, smaller than the previous commercial candidate but larger than baseline **5,471 / 15,756 / 26,356**. Repair median and p95 latency remain above baseline in the canonical measurements; the separately labeled API-transaction/JIT supplement also does not establish a general latency gain. **No latency-regression pass is granted.** Both fixtures contain 2,098 synthetic project/presentation rows across 417 groups but only 48 underlying persisted needs/evidence and no newly supported commercial facts. Rich-source payloads, HTTP/authentication/UI, quiet-machine behavior and production operation remain outside that measurement. Shared live pytest/PostgreSQL load is documented; zombie processes are correctly distinguished from live CPU load.

This report does not accept the separate UI revision, real HTTP authentication/Pursuits/browser journeys, full migration/recovery gates or final merged candidate. Earlier full-run failures and interrupted runs remain failures/interruption receipts unless separately closed by exact-source evidence.

Real commercial completion remains blocked: safe abstention, synthetic source tests, improved query structure and compact JSON do not establish useful real-source scoped recall, verified contact acquisition or salesperson acceptance. No merge or deployment approval is issued.

## Test-contract follow-up, aa5f2c35

The subsequent full backend CI for application source `1de298af` was reported by the coordinator as **1 failed, 5,534 passed, 1 skipped**. The remaining failure compared the entire opened group with its compact list card, including intentionally different commercial evidence arrays. This does not constitute a passing full suite.

I independently reviewed exact test-only commit `aa5f2c351c153fd7a20ce7a75292ec0a35f5a2cd`; its only changed file is `backend/tests/integration/test_customer_group_routes.py`. Application source and the performance benchmark binding remain unchanged. The repaired assertion retains exact equality for every legacy group field. Commercial comparisons check displayed amounts/bounds/completeness/coverage, the full retained date dictionaries including qualifiers, compact priority and commissioning scalars, and recent-development dictionaries excluding only raw before/after payloads. Counts and full-detail claim/conflict/source/input arrays are separately asserted. This is a legitimate compact-card versus full-detail contract correction, not acceptance of missing evidence or a weakening of legacy equality. My requested additions for date qualifiers, ranking method, optional scenario version and developments were incorporated before commit.

Inspected implementation receipts: the routes/projection/scale/query module selection passed **13 tests in 47.02 seconds** before the final assertion-completeness additions; the final changed route case passed **1 test in 6.93 seconds** after those additions. These are inspected receipts, not an independent database rerun. The final full suite/remote CI must run on the test-only repair before being described as green. Scoped test repair accepted; commercial and whole-release acceptance remain withheld.
