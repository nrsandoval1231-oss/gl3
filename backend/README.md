# Backend

Python 3.11 package for the authenticated FastAPI API, PostgreSQL persistence/Alembic migrations, structured source services, and separate fenced job worker. The versioned source registry is in `../config/sources/registry.v1.json`.

From the repository root, install with `uv sync --project backend --extra dev`, migrate using `uv run --directory backend alembic upgrade head`, and run the app commands in the root README. Integration tests require the isolated `TEST_DATABASE_URL`; their fixture refuses to reset the configured application database.
