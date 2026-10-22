# RG02 + R3E Builder Handoff

- Base: `0f876440a1375c502534cc1dd3c08ceff38c7349`
- Branch: `feat/regional-stabilization-20261022`
- Owned changes:
  - `backend/src/gridlens/domain/regional_scope.py`: anchored uppercase postal state code with optional ZIP; combines with existing explicit physical site tokens so conflicts hold.
  - `backend/tests/unit/test_regional_scope.py`: postal TX/OK/NM, outside GA, conflicting sites, English narrative and no-city-inference coverage.
  - `backend/tests/integration/test_regional_eligibility.py`: persisted conflict rows in the existing regional eligibility fixture.
  - `backend/src/gridlens/jobs/worker.py`: `_acquisition_retry_class` now prioritizes bounded retry-after rejection, then HTTP/transport diagnostics, then parser permanence.
  - `backend/tests/unit/test_job_retry.py`: direct and wrapped timeout/status cases, permanent parser/403, overbound retry-after precedence.
- Validation from `backend/` with `.artifacts/regional/range-test.env` loaded silently:
  - `python -m pytest tests/unit/test_regional_scope.py tests/unit/test_job_retry.py tests/integration/test_regional_eligibility.py tests/integration/test_regional_evidence_recovery.py -q` — exit 0, 58 passed.
  - `ruff format --check` on the five owned files — exit 0, already formatted.
  - `ruff check` on the five owned files — exit 0, all checks passed.
  - `mypy` on `regional_scope.py` and `worker.py` — exit 0, no issues in 2 files.
  - `git diff --check` for owned paths — exit 0.
- No network, paid services, production, configuration edits, or commit performed.
- Timing and token usage: UNKNOWN.
- Integration caveat: `worker.py` contains substantial concurrent edits from other packets in this shared worktree. This packet changed only `_acquisition_retry_class`; do not revert or attribute the other hunks to this handoff. Base SHA remained the packet base.
- Regional behavior algorithm changed while the existing migration imports the classifier. Historical migration was left untouched; root should evaluate current backfill/fresh migration implications as specified in RG02.
