# October 9, 2026 reconciliation

The October 9 candidate integrates onto current main and returns event_date and event_date_label separately from publication and retrieval. ORM regressions exercise publication-dated and event-only disclosures, including invalid bindings. The original base, test counts and environment limitations below are historical. Exact-candidate CI and independent review are recorded in PR #30; no acquisition writer or production readiness is claimed.

---

# ERCOT RFI mapping validation — October 7, 2026

Base: main `94c3acb7b36c6d5d04a77a0ec445e793e05120a4`.
Official sources and representability mapping:
[public RFI contract](../sources/ercot-state-community-impact-rfi.md).

## Scope and evidence

Four product files: new domain contract and read-only evidence projection; existing
project-state endpoint addition and source-origin labels. Two test files.
Existing JSON storage reused, zero migration. No registry adapter, live ingestion,
project answer acquisition, confidential response access, backfill, outreach,
tier/lifecycle change or deployment.

Focused run: **27 passed** (22 new RFI cases plus five existing signal-admission tests).
New cases cover threshold boundaries, unknown/voluntary categories, publication
states, unsupported confidential inputs, mandatory excerpts, RFI no-admission,
and actual SQLite ORM projection with stale hash, wrong site, absent excerpt,
aggregate-as-project and wrong evidence UUID rejection.
The initial new-test run failed collection because the new domain module did not
exist. The SQLite tests initially required local configuration; after providing
test-only settings all 18 passed. This is not PostgreSQL or live browser acceptance.

Ruff passes on all four product files and two new test files under project rules.
Mypy passes on the new domain/projection and existing project-state module.

## Broader validation limits

Available runtime: Python 3.12.14; repository requires >=3.11,<3.12.
No configured isolated PostgreSQL test database is available.

Full backend attempt (`pytest -q --maxfail=5`) collected successfully after restoring
the supporting script/config/fixture snapshot, then stopped on five setup errors:

- test_two_distinct_target_jobs_active_cap_and_evaluation_replay
- test_daily_question_cap_holds_then_reopens_next_day
- test_fresh_cache_reused_until_force_material_change_or_expiry[force]
- test_fresh_cache_reused_until_force_material_change_or_expiry[evidence]
- test_fresh_cache_reused_until_force_material_change_or_expiry[expired]

All are in test_autonomous_questions_integration.py and require test_database_url.
The first partial snapshot attempt had five missing script/config collection errors;
those snapshot files were restored before the subsequent attempt.

Broader final unit run: **875 passed, 1 failed, 1 skipped, 1 setup error**.
Failure: test_rrc_drilling.py::test_retained_reconstruction_rejects_deeply_nested_json_as_source_parse_error;
expected malformed-content wording, actual segment-count wording. Parser and test
are unchanged. This same runtime failure is reported in existing draft PR29.
Setup error: test_georgia_air_permits.py::test_georgia_job_retains_null_publication_and_replays_with_pdf_evidence,
missing PostgreSQL test_database_url. Existing optional probe skip and Starlette/httpx
deprecation warning remain.

An earlier unit run also failed
test_origin.py::test_login_allows_configured_frontend_origin_to_reach_password_check
because trusted_origins was absent. Setting the documented local frontend origin
removed that environmental failure without product changes.

Keep draft pending pinned-Python/PostgreSQL regression validation and final review.
No full-suite green, production readiness or real-project RFI disclosure is claimed.

Independent file-content review found one malformed-input crash: a nontext
Batch Zero classification could reach set membership and raise TypeError.
Four regression cases reproduced missing validation before the repair. The
validator now rejects list/dict/bool/int classification values before projection.
Review of the remaining public provenance and commercial boundaries found no
material defect. Git metadata is unavailable locally; publication uses the
GitHub connector and the pinned base tree.
