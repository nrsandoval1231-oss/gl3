# A6 adequate-supply reconciliation repair

## Result

The current accepted-fact projection now reconciles suitable supply against the complete supported activity interval before the operator-only Lead gate. The interval uses accepted timing when present, or the already-supported official Lead start-window and maximum duration. Adequacy requires suitable quality, full interval coverage, and the supply minimum to meet the compatible demand maximum. This produces a numeric `[0,0]` closure basis with the accepted fact ID/hash and source-version hashes; it does not represent cancellation or rewrite the source's Reported supply quote.

When the remaining interval is `[0,positive]`, the need remains active at an honest lower tier. A positive remainder remains Lead only when its existing support is valid, and its gap is recomputed with suitable-fact provenance. Partial coverage and unknown quality do not close a source Lead. Reassessment after source replay, fact correction, or retraction derives state from the current accepted versions; the existing active-state mechanism removes only confirmed adequate needs from active results while preserving fact history and the source record.

The integration regression proves the corrected current state through page, group, CSV, count/token invalidation, saved detail, and history reads. It also verifies the exact accepted fact/source bindings, unchanged Reported source quote, unaffected sibling need, source replay staying closed, and correction/retraction reopening only the supported state.

## Validation

Provider keys were cleared before imports, automated worker flags disabled, and the safe focused wrapper used with the disposable A6 builder databases. No providers or retained/original rows were mutated.

| Check | Command | Result | Raw log |
|---|---|---|---|
| Focused behavior | `pytest -q tests/unit/test_call_facts.py tests/unit/test_commercial_presentation.py tests/integration/test_call_fact_workflow_integration.py` | 54 passed; one existing deprecation warning | `.artifacts/a6-adequate-final-focused-3-20261008T2209147150495Z-6297eae87dcc41c48dc6602334f3662f-pytest.log` |
| Ruff | `ruff check src/gridlens/domain/call_facts.py src/gridlens/ingestion/service.py tests/unit/test_call_facts.py tests/integration/test_call_fact_workflow_integration.py` | Passed | `.artifacts/a6-adequate-final-ruff-3-20261008T2209208236249Z-405c9c90c8f5400ebc6453b4d4978269-ruff.log` |
| Mypy | `mypy src` | Passed, 80 source files | `.artifacts/a6-adequate-final-mypy-3-20261008T2209209361688Z-3291ccad4f464016b3af4b7cf6b73d25-mypy.log` |
| Diff check | `git diff --check` | Passed | Terminal result; no raw wrapper log |

The initial exact reproduction failed both reported adequate-supply cases. Intermediate failures and fixture corrections are retained in `RAW-HASH-MANIFEST.json`; they distinguish assertion/fixture corrections from the missing suitable-fact provenance defect discovered in the public Prospect path. Full repository gates, retained-corpus gates, and independent review are reserved for root after freeze.
