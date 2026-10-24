# M1-UI — selected detail readability at1280×800

- Repo/worktree/branch: nrsandoval1231-oss/gl3; gl3-production-20261023; feat/production-intelligence-20261023.
- Base a70e5330ee8ad7483391abe313d2bb9f68183975; READY independent of backend.
- Allowed only: web/src/styles/workspace.css, web/tests/approved_workspace.spec.ts; own evidence .agent/artifacts/PRODUCTION-M1-UI/.
- Read AGENTS.md, PRD, UI_CANON, PURSUIT_WORKSPACE, WorkspaceDetail.tsx, existing tests.
- Exclude TSX/backend/APIs/assets/package locks/runtime config/shared state/other docs.
- Acceptance: reproduce selected-detail overflow with truthful-length fixtures; preserve five desktop metrics/approved composition1280×800; readable wrap/vertical growth; no metric/hero/control clipping/page horizontal overflow. Preserve tablet/mobile and existing geometry.
- Validation: npm run typecheck; npm run build; focused approved_workspace.spec.ts --project=regression. Meaningful long-value bounds/scrollWidth assertions; screenshots1280×800/390×844. Fixture evidence labeled.
- Runtime dependencies installed; isolated app DB migrated. GRIDLENS_API_PORT=8013; GRIDLENS_WEB_PORT=5183; Playwright workers2. Do not touch PostgreSQL or launch source worker;8000 belongs to other work.
- Authority/risk: reversible CSS repair, no redesign. No commit/push/merge/deploy/providers. Two materially different repairs then report.
- Handoff .agent/artifacts/PRODUCTION-M1-UI/COMPLETION.json with commands/exits/files/screenshots, UTC times/model and UNKNOWN tokens. Builder does not grade completion.
- You are not alone: backend owns Python/config/compose. Preserve others, no subagents.
