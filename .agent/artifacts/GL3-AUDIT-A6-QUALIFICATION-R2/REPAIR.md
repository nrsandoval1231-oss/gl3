# A6-R2 exact demand and suitable-supply ranges

## Scope and result

This bounded repair implements the independent range FIX in `FAILED-REVIEW.json`.
The exact-need fact domain now accepts either typed `mw_min`/`mw_max` values or
one exact bounded interval in the typed `mw` field. It reuses
`commercial_presentation.exact_mw_interval`, canonicalizes equal endpoints to
the legacy scalar shape, and leaves unsuitable-supply facts scalar-only.
Uncertain prose, open bounds, negative/reversed/non-finite values, and values
over the existing 1,000,000 MW ceiling fail validation. Legacy scalar value
normalization remains unchanged. Suitable supply may explicitly be zero, but
zero-gap uncertainty keeps the need below Lead.

For a current source-supported Prospect, exact source demand and accepted
exact-need demand are kept separately. Overlapping intervals are intersected
only for the calculation; disjoint intervals produce the existing visible
qualification conflict and Signal tier. `demand_mw` remains the original source
claim. A fact-assisted calculated `required_mw` is selected only after the
fact passes full activity-window checks and the need reaches Lead. The derived
gap retains min/max inputs and remaining bounds, the canonical
`official-power-qualification-v2` calculation version, source and operator
values, and the exact accepted fact ID/content hash. Scalar gap serialization
is unchanged when no interval calculation is needed.

`ingestion.service._effective_qualification_from_claim` has one narrow
fact-assisted projection: it uses the explicit `fact_derived_required_mw`
marker when present and otherwise retains the original Reported `demand_mw`
projection. The integration regression demonstrated the old projection defect:
the correct 17 MW point gap was computed, but persisted/read-back
`required_mw` stayed at 20–25 MW until this marker was honored. No source
interpretation is rewritten. Public page, selected detail, group page, CSV and
commercial-size status now read the same persisted range calculation.

## Deterministic coverage

Unit tests begin with the real official parser's exact-site 20–25 MW Prospect.
They cover source-only 15–20 MW gap, compatible 22 MW point intersection and
17 MW gap, overlapping 22–30 MW confirmation intersected to 22–25 MW,
disjoint 26–30 MW conflict, suitable-supply interval arithmetic, explicit zero
supply, zero-gap lower-tier behavior, invalid/open/prose ranges, unknown or
unsuitable quality, full-window demand fact validity, and legacy scalar output.

The disposable authenticated integration workflow covers text-range draft
normalization, typed-bound equivalent idempotent read-back/hash, 22 MW point
confirmation, append-only correction to a typed 21–24 MW interval, persistence
of `PowerNeed.required_mw`, exact accepted fact ID/hash provenance, and matching
page/detail/group/CSV values and floor status. Its A→B→A source correction and
withdrawal path preserves the original 20–25 MW Reported assessment while the
accepted 21–24 MW calculation is restored. The existing saved-as-of and
current-fact preflight tests remain in the focused integration file.
Fixtures are synthetic and do not establish a customer Lead.

## Validation boundary

The latest focused validation passed on the working implementation before the
documentation/freeze commit:

- Safe-wrapper pytest for `tests/unit/test_call_facts.py`,
  `tests/unit/test_commercial_presentation.py`, and
  `tests/integration/test_call_fact_workflow_integration.py`: 50 passed, one
  existing Starlette/httpx deprecation warning.
- Ruff on the two owned source files and three focused test files: passed.
- `mypy src`: passed, 80 source files.
- `git diff --check`: passed after implementation and explanatory artifact authoring.

All focused application imports used the safe wrapper, which cleared Firecrawl,
OpenAI, and Typesafe provider keys before startup, disabled automation flags,
used synthetic authentication, and directed tests to the disposable builder
database. The root final databases, retained corpus, source providers, and
original data were not used or mutated.

The root still owns mandatory exact-candidate full backend/browser/static,
migration, retained-corpus/query-budget and independent-review gates. Those are
not run or claimed by this builder receipt. This artifact records a frozen
implementation candidate, not acceptance of A6 or the parent finish contract.
