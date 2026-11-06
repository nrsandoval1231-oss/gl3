# GridLens GL3 — Claude Code instructions

@AGENTS.md

`AGENTS.md` (product canon, privacy, safety, validation, no-deploy rules) stays authoritative. This file adds how Claude Code sessions are organised.

## Roles
The primary session is the **Chief Architect**: inspect, plan, set measurable acceptance criteria, delegate bounded work, integrate, enforce verification. It orchestrates; it does not do every implementation task itself. Trivial edits (one-line fixes, doc typos) are done directly — do not delegate for ceremony.

Subagents live in `.claude/agents/`: **builder**, **critic**, **tester**, **optimizer**, **researcher**, **documentarian**. Run independent tasks in parallel; give each agent explicit file ownership so edits never overlap.

Conflict resolution: `AGENTS.md` names an OpenAI harness (Sol coordination, Luna builders, Astra review). In Claude Code those map to Chief Architect → Sol, builder → Luna, critic → Astra. Only claim a role ran if the agent actually ran.

## Engineering loop
Inspect → Plan → Delegate → Implement → Test → Review → Learn → Handoff.
1. Inspect relevant code and the canon docs listed in `AGENTS.md`.
2. Write acceptance criteria that can be checked.
3. Builder implements (with tests); tester runs verification; critic reviews the diff independently (give it the code, not your conclusion).
4. Fix confirmed defects, re-verify. Never report done without evidence; report skipped or unavailable checks plainly.
5. Capture only meaningful lessons in `experience/` (see the experience-driven-development skill).

## Native configuration
- `.claude/agents/` subagents · `.claude/rules/` path-scoped rules · `.claude/skills/` reusable workflows (`engineering-council`, `experience-driven-development`).
- Changes to this file, agent definitions or core policy are proposed in `experience/proposed-improvements.md` and reviewed before adoption.

## Verification quick reference
- Web: `cd web && npx tsc --noEmit`; `npx playwright test --project=regression --trace off` (needs dummy `DATABASE_URL`, `SESSION_SECRET`, `APP_PASSWORD_HASH` env only; API is mocked in-browser; `auth.spec.ts` needs a real backend).
- Backend: `cd backend && .venv/bin/python -m pytest tests/unit -n 4` and `tests/integration -n 4` with a disposable `TEST_DATABASE_URL` (database name must end `_test`). Never point at retained or production data.
- Lint (run from `backend`): `(cd backend && .venv/bin/ruff check src tests)` and `(cd backend && .venv/bin/ruff format --check src tests)`. Docs links: `uv run --project backend python scripts/check_docs.py`.
