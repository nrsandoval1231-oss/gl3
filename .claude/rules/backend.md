---
paths:
  - "backend/**"
---
# Backend rules
- Schema changes need an Alembic migration (next revision after the current head) with a working downgrade; verify upgrade → downgrade → upgrade on a blank disposable database.
- New autonomous-research `pursuits*` tables are unrelated to owner-managed `commercial_pursuits*`; do not conflate them.
- Tests use a disposable Postgres whose database name ends `_test`; never retained or production data. Network guards in `tests/conftest.py` stay on.
- Keep `ruff check` and `ruff format` clean (line length 100). The mutation allow-list test `tests/unit/test_autonomous_api_surface.py` must list every write route explicitly.
- Preserve evidence provenance, privacy/suppression, idempotency and provider accounting.
