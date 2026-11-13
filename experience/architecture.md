# Architecture notes

Product architecture lives in `docs/architecture/overview.md`; this file only holds engineering-workflow facts not recorded there.

- Web: React 19 + Vite, plain CSS, hand-rolled history navigation in `web/src/features/workspace/Workspace.tsx`; Playwright tests mock the API in-browser (a backend only needs to boot).
- Backend: FastAPI + SQLAlchemy + Alembic; schema head on `main` was `0050_commercial_pursuits` when PR #183 merged (`cbe4aec`) and is `0056_statement_dirty_projects` as of 2026-11-13 (run `alembic heads` for the current value; it moves). The Nov 2 receipt recorded production at 0049; current production schema is unverified.
- Two unrelated "pursuit" concepts: `pursuits*` (autonomous research) and `commercial_pursuits*` (owner execution workspace).
