# Operational scripts

- `setup_local.py` creates ignored native-runtime credentials from `.artifacts/local-postgres/connection.env` or process `DATABASE_URL`/`TEST_DATABASE_URL` when passed `--use-environment`; it refuses to replace existing credentials unless passed `--force`.
- `setup_compose.py` creates separate ignored Compose credentials and `.artifacts/compose-auth.txt`; it also refuses silent credential rotation.
- `export_openapi.py` exports typed FastAPI response schemas to `web/src/api/openapi.json`; run `npm run generate:api` in `web` to refresh TypeScript types.

The worker and optional managed scheduler share the application queue services rather than duplicating qualification logic.
