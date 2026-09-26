# Backend verification

Run `uv run --project backend pytest backend/tests` at repository root. Unit tests cover qualification, source configuration, and auth boundaries. PostgreSQL integration tests use only `TEST_DATABASE_URL`, which must identify a different explicit test database; their destructive fixture checks this before dropping schema. Fixtures are labeled synthetic; retained real discovery artifacts are separate in ignored `.artifacts/`. No routine test calls paid services or external outreach.
