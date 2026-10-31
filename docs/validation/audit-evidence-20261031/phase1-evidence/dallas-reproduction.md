# Dallas fixture clock regression

Baseline snapshot: 593cfd516d82a12b66558f53b975ad6c2b711517, `/workspace/gl3-audit-main/backend`.
Run on 2026-10-31. Days since fixture report month 2026-08-01: 91; adapter rejects over 90 days.

Baseline command (dummy settings; no service connection):
`DATABASE_URL=postgresql+psycopg://unused:[REDACTED-TEST-PASSWORD]@127.0.0.1:1/unused SESSION_SECRET=isolated-dallas-fixture APP_PASSWORD_HASH=unused PYTHONPATH=src /workspace/gl3/backend/.venv/bin/python -m pytest tests/unit/test_city_permits.py::test_dallas_latest_month_link_retrieval_and_host_bounds -q`

Result: 1 failed at Dallas adapter line 267; `dallas-baseline.log`. Baseline test file and adapter were byte-identical to phase1 before editing.

Fix: test-local subclass freezes only Dallas module datetime.now to October 1, aligned with adjacent parser fixture; inherited strptime retained. Production source and threshold unchanged. Whole test file 12 passed; `dallas-green.log`. Ruff check and format passed.

Adapter SHA256 baseline: 8137d73ced1c0467997b1f6fae918a98727358d07b7c4e475f446943873c9978
Adapter SHA256 after test fix: 8137d73ced1c0467997b1f6fae918a98727358d07b7c4e475f446943873c9978
