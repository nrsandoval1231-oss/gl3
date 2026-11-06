# Architecture notes

Product architecture lives in `docs/architecture/overview.md`; this file only holds engineering-workflow facts not recorded there.

- Web: React 19 + Vite, plain CSS, hand-rolled history navigation in `web/src/features/workspace/Workspace.tsx`; Playwright tests mock the API in-browser (a backend only needs to boot).
- Backend: FastAPI + SQLAlchemy + Alembic; schema head `0050_commercial_pursuits` on branch `feat/commercial-workspace-ux` (production is at 0049).
- Two unrelated "pursuit" concepts: `pursuits*` (autonomous research) and `commercial_pursuits*` (owner execution workspace).
