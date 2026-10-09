# A6 source-timing conflict and correction binding

## Behavior

Current source Lead timing is parsed into start-window bounds and minimum/maximum duration. An accepted operator timing value can narrow both components only when its possible start range and duration are wholly contained in those source bounds. Disjoint timing, partial overlap, stale source hashes, incomplete correction markers, or a marker against a Lead with no replayable source timing produces an active lower-tier conflict and removes obsolete Lead gap/window fields. It cannot prove closure.

An explicitly attributed correction carries both current SHA-256 source hashes and a nonempty basis in the existing typed timing `value`. It may replace the source interval only when both hashes still match and the source Lead interval is replayable. The selected interval must be fully covered by the timing and suitable-supply fact effective windows before adequate-supply closure. Closure basis records timing fact ID/hash, resolution classification, source hashes, selected interval, basis reason, and original Reported window/duration. Any revised gap records timing fact ID/hash, resolution classification, source hashes, and selected interval. Accepted correction history retains the marker. No API model or route change was needed.

The integration regression creates an official source Lead, accepts a version-bound November correction and suitable supply, and verifies inactive public state plus fact-history readback. It then replays the source under different semantic/evidence hashes. The old correction becomes a visible conflict, the Need returns to the active Prospect page and CSV, and the pre-replay cohort token returns 409. The stored source assessment still retains its original January-February Reported timing.

## Validation

All checks ran through `.artifacts/run-a6-focused-safe.ps1`, which clears the three provider keys before imports, disables worker/autonomous flags, uses synthetic auth, refuses a candidate `.env`, and targets only the disposable A6 builder databases. No provider, retained corpus, or original database action occurred.

| Check | Command | Result | Raw log |
|---|---|---|---|
| Focused suite | `pytest -q tests/unit/test_call_facts.py tests/unit/test_commercial_presentation.py tests/integration/test_call_fact_workflow_integration.py` | 61 passed; one existing Starlette/httpx deprecation warning | `.artifacts/a6-timing-final-focused-4-20261008T2240192223345Z-5c0b1e6b5bd74d9a9487015005a4452c-pytest.log` |
| Ruff | `ruff check src/gridlens/domain/call_facts.py tests/unit/test_call_facts.py tests/integration/test_call_fact_workflow_integration.py` | Passed | `.artifacts/a6-timing-ruff-final-2-20261008T2240306564948Z-52d01258c1904f219e6b82be291ed197-ruff.log` |
| Mypy | `mypy src` | Passed, 80 source files | `.artifacts/a6-timing-mypy-2-20261008T2239572166957Z-56fe6f1a703e4bda86da61a34544bada-mypy.log` |
| Diff check | `git diff --check` | Passed before freeze | Terminal result; no wrapper raw log |

These are builder-focused results only. Root full backend/browser/schema/retained gates and fresh independent review remain pending; this artifact does not claim A6 acceptance.
