# H2 completion handoff

Implemented health pending-lane projection from the existing bulk current-policy progress query. Complete windows now remain pending when they have not reached the current UTC boundary; the Austin backfill lane remains pending until `completed_through` reaches its configured end. Missing expected lanes are reported pending only when matching current-policy progress exists. Disabled sources do not expose active pending lanes, and no current progress metadata preserves the existing omitted/unknown response.

Changed files within H2 ownership:

- `backend/src/gridlens/api/app.py` — health projection only; no additional database query.
- `backend/tests/integration/test_source_health_backlog.py` — complete-window boundary, caught-up empty result, stale digest, unknown metadata, and disabled-source coverage.

Validation, using `.artifacts/regional/range-test.env` loaded silently:

- `pytest tests/integration/test_source_health_backlog.py tests/integration/test_source_schedule_proof.py tests/integration/test_source_scheduling.py -q` — **58 passed** (27.82s).
- `ruff format src/gridlens/api/app.py tests/integration/test_source_health_backlog.py` — formatted both files.
- `ruff check src/gridlens/api/app.py tests/integration/test_source_health_backlog.py` — **passed**.
- `mypy src/gridlens/api/app.py` — **Success: no issues found in 1 source file**.
- `git diff --check` — **passed** (only existing CRLF normalization warnings on unrelated shared files).

One initial focused run exposed fixture-only issues (local `date` import and response omission semantics); corrected within the packet. No remaining H2 test failures. Final frozen-candidate integration, API proof, and performance gates remain with root.
