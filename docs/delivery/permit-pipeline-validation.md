# Permit pipeline validation — GL3-008

Builder checks on 2026-09-27:

- Read-only public GET through the new adapter: Austin 311, Seattle 84, Chicago 597 rows for 2026-08-28–2026-09-27 UTC. Each exact count matched the complete paged result; all returned issue dates were within the window. Normalized rows and builder assessments are in ignored `.artifacts/GL3-008/public-audit-2026-09-27/`. A domain specialist re-evaluated all 992 retained records and reported 11 candidates (7 Austin, 3 Chicago, 1 Seattle) with permit-project-v2; this is not durable runtime evidence or independent exact-candidate acceptance.
- Focused unit checks: `uv run pytest tests/unit/test_socrata_permits.py tests/unit/test_registry.py -q` — 19 passed.
- Durable isolated-DB replay/correction: `uv run pytest tests/integration/test_ingestion.py::test_permit_assessment_replay_correction_and_deactivation -q` — 1 passed. The test persisted a supported permit Signal, replayed it without creating another Observation/Evidence version, then changed only `status_current` from Active to Withdrawn; this produced a retained correction version, rejected the current assessment, and deactivated the unsupported need.
- Focused Ruff: all touched permit adapter, interpretation, registry, queue, worker, API, and test files passed.
- API contract export and web type generation completed with `scripts/export_openapi.py` and `npm --prefix web run generate:api`.

The test used only the isolated `*_test` database configured for backend tests. No live application database write, worker/API restart, migration, push, merge, or deployment was performed by the builder. The controller owns ordinary job retrieval, durable replay in the application runtime, retained sample review, browser evidence, final gates, exact-candidate manifest, and independent review. A local runtime retrieval is not a national coverage claim or launch completion.
