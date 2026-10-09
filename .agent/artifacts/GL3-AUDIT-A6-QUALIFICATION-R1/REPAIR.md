# A6 qualification review repair

## Scope and result

This bounded repair addresses the two independent FIX findings in
`FAILED-REVIEW.json`. It changes the exact-need fact qualification domain
function and its unit/integration coverage only. The existing canonical
`effective_need_qualification` / `_apply_current_qualification` path remains the
sole evaluation and reassessment path; no ingestion service change, migration,
public contract, source adapter, or policy document change was needed.

An admitted current source `Prospect` now supplies its already-supported exact
demand and separate unsuitable-supply claim. Compatible accepted timing,
suitable-supply, and buyer facts can fill only the remaining Lead gates. A
`Signal` still requires accepted exact-need demand and unsuitable-supply facts
before reaching Prospect. Both paths require a positive gap, suitable quality,
an authorized buyer organization/role, and complete interval support. Operator
facts alone confer no source authority.

Lead fact versions used for qualification must be timezone-aware and cover the
whole possible activity interval. The timing start's first date is inclusive;
its last date is the last possible start date. The required half-open activity
range is therefore `[start_date 00:00 UTC, end_date + duration_days 00:00 UTC)`.
An effective interval covers it only when `effective_from <= activity_start`
and `effective_until` is explicitly `None` (open-ended) or
`effective_until >= activity_end`.
This preserves the persisted `[effective_from, effective_until)` convention and
accepts exact end-boundary coverage. Missing or naive interval metadata fails
closed; an explicitly open-ended interval is supported.

Unit regressions use the real official qualification parser to create the
Prospect base, then prove promotion without redundant demand/shortage facts.
They also preserve Signal-to-Lead behavior, reject missing buyer, unknown
supply quality, expired-before-start and partial-window supply, future starts,
missing intervals on every fact type used by the Signal path, wrong activity,
and wrong facility. An exact exclusive-end boundary and explicit open-ended
facts are positive cases.

The disposable integration workflow now starts from a parser-derived exact-site
official Prospect, adds only timing/suitable-supply/buyer facts to reach Lead,
checks the canonical derived 15 MW gap, then exercises a source A→B→A
contradiction/withdrawal/restoration with an accepted exact-need demand version.
Saved-as-of and fact-reference integration tests remain in the same focused
suite. All evidence is synthetic and does not establish a customer Lead.

## Validation boundary

Focused validation passed on the frozen code at the R1 source commit:

- `pytest -q tests/unit/test_call_facts.py tests/integration/test_call_fact_workflow_integration.py` — 30 passed, 1 existing Starlette/httpx deprecation warning.
- Ruff on the three owned source/test files — passed.
- `mypy src` — passed, 80 source files.
- `git diff --check` — passed.

The root full backend, browser, retained-corpus, migration, and final review
gates remain pending on this changed candidate. The previous full-gate PASS on
the earlier A6 candidate was rejected by the independent review and is not
acceptance evidence for this repair. The known test-tree typing limitation was
not rerun; the required source-only mypy gate passed.

The no-fact source claim continues to be current-source-bound by the existing
service admission path. This repair does not add validity dates to public source
records. For source demand values represented as a range rather than one exact
quantity, the fact-aware scalar gap path remains fail-closed unless a compatible
accepted exact demand fact resolves the quantity; it does not invent range
arithmetic.
