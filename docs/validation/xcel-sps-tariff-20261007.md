# SPS tariff proposal validation — 2026-10-07

Base: GL3 main `94c3acb7b36c6d5d04a77a0ec445e793e05120a4`.
Five new files only. No existing production code, migrations or project projections change.
The current main tree was read through GitHub; 206 backend/config/script/AGENTS
files in the local snapshot were matched byte-for-byte to its Git blob IDs.
Existing snapshot trailing newlines were corrected locally for validation; those
baseline files are not part of this change. Backend README and uv.lock were not
materialized, and dependencies were provided by the available runtime.

## Focused evidence

- Initial new test failed because the proposal module did not exist.
- `python -m pytest backend/tests/unit/test_utility_tariff_proposals.py -q`:
  **21 passed**.
- Ruff on the new module and test file: **passed**.
- Mypy on the new module: **passed**.
- Module CLI against the real reviewed JSON: **passed**, JSON round trip unchanged.
- Scope/source review: application Attachment A verified threshold, territory,
  aggregation and exclusions; application introduction distinguishes future rate
  design; Order No. 1 is procedural, not an approval. Per-term citations retained.

Tests cover status restrictions, no effective-date activation, project-fact
rejection, unknown applicability, malformed thresholds, dangling/blank citations,
announcement-versus-filing provenance, duplicate IDs, chronology, future-rate-case
separation and the actual JSON loader. No automated eligibility or billing is claimed.

## Broader checks and limits

Runtime: Python 3.12.14; repository requires 3.11. Pinned-runtime acceptance is open.

Final unit run: **874 passed, 1 failed, 1 skipped, 1 setup error**.

- Failure: `test_rrc_drilling.py::test_retained_reconstruction_rejects_deeply_nested_json_as_source_parse_error`.
  Unchanged baseline expects `retained content is malformed`; parser emits
  `RRC retained segment count invalid`. No tariff code is involved.
- Setup error: `test_georgia_air_permits.py::test_georgia_job_retains_null_publication_and_replays_with_pdf_evidence`.
  PostgreSQL at localhost:5432 refused connection.
- Existing warning: Starlette/httpx TestClient deprecation.
- Existing optional NC local-access probe skipped.

Full `pytest -q --maxfail=5` attempt stopped at five PostgreSQL connection setup errors:
`test_autonomous_questions_integration.py` cases
`test_two_distinct_target_jobs_active_cap_and_evaluation_replay`,
`test_daily_question_cap_holds_then_reopens_next_day`, and
`test_fresh_cache_reused_until_force_material_change_or_expiry[force/evidence/expired]`.
No full-suite success is claimed.

An earlier run omitted TEST_DATABASE_URL and TRUSTED_ORIGINS, causing database-URL
setup errors and an origin expectation failure. Corrected test-only environment
removed the origin failure; the final results above supersede that run. Database
and test database URLs were distinct; no production database was used.

Keep the PR draft pending normal Python 3.11/PostgreSQL regression validation and
review. No independent agent review, browser test, live ingestion, scheduled docket
monitor, project matching, merge or deployment is claimed. This is deliberately
only a validated proposal representation and its source notes.
