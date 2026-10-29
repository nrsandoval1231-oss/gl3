# Repository streamlining — 2026-10-29

Base: `eadb203be231af045480b97f196b89f1b6457846` (PR143). Scope: reversible repository cleanup only; no production, credential, provider, schema or retained-data changes. Current canons govern; no visual redesign.

## Bounded execution and inventory

- [x] A: Read authority/current-state/operations, inspect Git history and inventory repository.
- [x] B: Consolidate active instructions and archive superseded candidate permissions verbatim.
- [x] C: Frontend dependency audit and justified cleanup.
- [x] D: Backend dependency audit and justified cleanup.
- [x] E: Tooling/CI audit and justified cleanup.
- [ ] F: Integrated checks and independent Astra review; report unavailable verification explicitly.

Baseline tracked inventory: 1,986 files; 566 code files / 213,041 lines / 8,991,769 bytes; 695 Markdown files / 28,701 lines / 3,577,155 bytes; 725 other files. Code means `.py/.ts/.tsx/.css/.js/.mjs/.ps1/.sh`; documentation means `.md`. Counts include retained history. Subsystem counts: 183 backend source Python modules, 217 backend test Python files, 48 migration Python files, 20 React TSX files, 20 browser test TS files, 40 Python scripts, 18 deployment files, 11 configuration files and 224 web-public assets. Mounted API has 46 paths. Archive copies/relocations are not deletions or size savings.

| Paths / subsystem | Disposition | Dependency evidence and rationale | Risk |
|---|---|---|---|
| `AGENTS.md`, `.agent/{README,AGENT_RULES,OWNER_REQUEST,CURRENT_STATE,FINISH_CONTRACT,WORK_GRAPH}.md`, `docs/README.md`, `docs/delivery/milestones.md` | CONSOLIDATE | Prior active files repeat old missions/permissions and candidate status. One reading hierarchy and current checkpoint; exact replaced records archived. | Low; documentation links checked |
| `docs/product/AUTONOMOUS_INTELLIGENCE_CANON.md` candidate-specific October26 appendices | ARCHIVE | PR126 release exceptions cannot authorize new releases. Preserve original full canon, retain product/evidence/engineering requirements and historical link. | Low; no product rule removed |
| `backend/migrations/**`, `backend/src/gridlens/persistence/**` | KEEP | Durable model registration, history, replay and schema compatibility; not removable from static references alone. | Critical data boundary |
| `backend/src/gridlens/ingestion/**`, `config/sources/**` | KEEP | Worker/config dispatch and official parsers; disabled out-of-region adapters remain useful. | Critical intelligence boundary |
| `backend/src/gridlens/{domain,intelligence,jobs,integrations}/**` | KEEP / INVESTIGATE | Domain qualification, research, buying chain, budgets, suppression and leased scheduling have runtime consumers. No broad deletion supported. | High |
| `backend/src/gridlens/api/app.py` | INVESTIGATE | 6,140 lines; mounted routes and helper consumers in saved browse, opportunity intelligence and jobs. A trial 17-line health extraction was discarded: it added compatibility plumbing without reducing coupled responsibilities. Full health separation requires shared date/schema/scheduling dependencies to be addressed together. | High coupling; deferred |
| `web/src/api/client.ts` | REMOVE | Two wrappers (`intelligenceTasks`, `intelligenceHistory`) and their hand-written response types have no source/test consumers; backend routes/generated contract retained. | Low; build/typecheck/browser gate |
| `web/src/styles/{app,workspace}.css`, `web/src/features/workspace/intelligence-card.css` | REMOVE | Unused selectors from retired workflows/dashboard; source and browser-test class references checked, including mixed selector branches. | Medium; independent dynamic-class review and browser gate |
| `web/src/**`, `web/public/brand/**` | KEEP | All 20 TSX components reachable through imports/direct secondary routes. Brand manifest declares deliverables beyond runtime icons. | UX/contracts |
| `backend/tests/**`, `web/tests/**` | KEEP | Retained regression contracts and browser coverage; no tests removed for speed. | Verification |
| `scripts/check.ps1` repeated migration upgrade | REMOVE | Same upgrade already runs before `alembic check`; CI PR137 removed identical redundancy. One upgrade plus drift check retained. | Low |
| `.github/workflows/publication-diagnostic.yml`, `scripts/diagnose_publication.py` | ARCHIVE | One-off PR87 branch-pinned workflow tests immutable historical source with fixed test IDs/counts. Original bytes retained under `docs/validation/archive/pr87-publication-diagnostic/`; no current recovery consumer. | Low; historical reproducibility retained |
| `.github/workflows/ci.yml` | KEEP | PR137–143 preserve parallel jobs, per-worker DBs, data reset, path filtering, full gates and timeouts. | Required gate |
| `deploy/**`, `compose.yaml`, recovery/rollback scripts | KEEP | Deployment entrypoints and recovery safety; lack of application imports is not deadness. | Production recovery |
| `docs/validation/**`, `.agent/archive/**`, historical screenshots/artifacts | KEEP | Immutable candidate evidence, failed runs and audit data; not deleted to inflate reductions. | Evidence retention |
| Backend/web/brand dependency manifests | KEEP / INVESTIGATE | No proven unused direct dependency from initial audits. Preserve lockfiles and required tooling. | Build/runtime |

## Validation and measurements

Pending integrated results. Production operation and real commercial coverage are outside this local cleanup. No CI speedup is claimed without measured runs.

## Exact duplicate historical records removed

Each deleted file was unreferenced by a repository-wide hidden-file search and byte-identical to the retained path below. No unique historical content was removed; original paths remain in Git history.

| Removed duplicate | Retained identical record | SHA256 |
|---|---|---|
| `.agent/archive/STAGE2-20261009/git-CURRENT_STATE.md` | `.agent/archive/STAGE2-20261009/CURRENT_STATE.md` | `69002f0c23ba1a28a55a11a03b640d405c4a9c3bc92ae3395344c1d25a6a98f3` |
| `.agent/archive/STAGE2-20261009/git-WORK_GRAPH.md` | `.agent/archive/STAGE2-20261009/WORK_GRAPH.md` | `fa7d47c320911aea17da6ca23833041fe3d89f205567115e2fb4c31b9d50f42f` |
| `.agent/archive/pre-UI79-CURRENT_STATE.md` | `.agent/archive/intelligence-20261018/CURRENT_STATE.md` | `6331ce22d6a0c3b1a66680b710d77fbd4ed4f8b1c54e47a53fc0abf2b5296951` |
| `.agent/history/pre-m5-replay-pass-20261024T024500Z-CURRENT_STATE.md` | `.agent/history/pre-m5-runtime-20261024T021700Z-CURRENT_STATE.md` | `23b41efaad1e986b3ad56deb53dc3f85fb01274626097567bc420dab2baeebde` |
