# October 9, 2026 reconciliation

The current-main repair supersedes the original mutable Interpretation JSON storage described below. Reviewed request facts now live in append-only interconnection_fact_versions, tied to a project and retained evidence version. Migration 0018 adds only this table and reuses the existing database immutable-history trigger function; it does not rewrite existing data. Corrections append new evidence-bound attachments; current projection excludes rejected, stale and foreign bindings while historical structured payloads remain stored. The draft feature was not deployed; no legacy attachment backfill is claimed.

Regressions cover idempotent attachment, refused overwrite, current semantic/document bindings, rejected reinterpretation and a real ingestion correction/replay. Exact-candidate CI and independent review are recorded on PR #29. Original baseline, no-migration statement, validation counts and environment limitations below are historical. No feed/parser/UI or production acceptance is claimed.

---

# §25.194 mapping verification — October 7, 2026

Base: GL3 main `94c3acb7b36c6d5d04a77a0ec445e793e05120a4` (PR24 merged).

Changes are confined to one domain module, one retained-evidence service, the
existing project-state projection, two test files and source/verification notes.
No migration, registry activation, provider call, production data modification,
commercial tier change, frontend change, deployment or merge is included.

## Targeted checks

From `backend`, with isolated test-only settings:

```bash
python -m pytest tests/unit/test_large_load_interconnection.py tests/unit/test_interconnection_evidence.py -q
python -m ruff check src/gridlens/domain/large_load_interconnection.py src/gridlens/intelligence/interconnection.py src/gridlens/intelligence/project_state.py tests/unit/test_large_load_interconnection.py tests/unit/test_interconnection_evidence.py
python -m mypy src/gridlens/domain/large_load_interconnection.py src/gridlens/intelligence/interconnection.py src/gridlens/intelligence/project_state.py
```

- 24 tests passed, plus 7 threshold subtests.
- Ruff passed; mypy passed on all three touched source modules.
- Evidence/projection tests use a real isolated SQLite ORM database with a
  test-only JSONB compilation hook. This validates read/write behavior, not
  PostgreSQL concurrency or deployment acceptance.
- Tests were observed failing before missing behavior was implemented, including
  co-location uncertainty, project-state exposure, retained-payload mutation
  protection and malformed stored facts.

## Full backend attempt and remaining validation

The full `python -m pytest -q --tb=no` command was run. Final result:
**881 passed, 1 failed, 1 skipped, 374 setup errors, 7 subtests passed.**

The setup errors occur in PostgreSQL-dependent tests: this workspace has no
running test PostgreSQL server. URLs pointed only to isolated localhost test
databases. There was no attempt to connect to a production database. The
PostgreSQL integration suite and lock behavior remain unverified here.

The failing existing test is
`tests/unit/test_rrc_drilling.py::test_retained_reconstruction_rejects_deeply_nested_json_as_source_parse_error`.
It expects `retained content is malformed`; this environment returns
`RRC retained segment count invalid`. Its parser and test source are unchanged
from the inspected main. No RRC repair is included in this regulatory slice.

The earlier unit/full runs also exposed an origin test failure due to missing
`TRUSTED_ORIGINS` and a missing optional SOCKS transport dependency. The origin
configuration and transport dependency were repaired locally; neither failure
remained in the final full run. An existing Starlette test-client deprecation
warning remains.

Runtime here is Python 3.12.14; the project declares Python 3.11. A 3.11 runtime
download timed out. Relevant available dependencies were pinned back to the
project's versions where possible. A full pinned-Python/PostgreSQL run is required
before considering this candidate ready to merge. This is not a green-suite claim.

## Delivery boundary

Only reviewed facts from existing accepted project evidence can be attached.
No real project agreement, allocation or financial commitment was backfilled.
No automated Register/queue retrieval or extraction was added. The legal rule
mapping is advisory and separate from reported facts and qualification.

The candidate should remain a draft until pinned-runtime/PostgreSQL validation
and independent review are complete. Future regulatory-feed onboarding and the
morning material-change notification path are separate work.
