# Repository streamlining — 2026-10-29

Base: `eadb203be231af045480b97f196b89f1b6457846` (PR143). Scope: reversible repository cleanup only; no production, credential, provider, schema or retained-data changes. Current canons govern; no visual redesign.

## Bounded execution and inventory

- [x] A: Read authority/current-state/operations, inspect Git history and inventory repository.
- [x] B: Consolidate active instructions and archive superseded candidate permissions verbatim.
- [x] C: Frontend dependency audit and justified cleanup.
- [x] D: Backend dependency audit and justified cleanup.
- [x] E: Tooling/CI audit and justified cleanup.
- [ ] F: Integrated checks and independent Astra review; report unavailable verification explicitly.

Baseline Git-blob inventory (avoids checkout newline conversions): 1,986 files; 566 code files / 213,042 lines / 8,991,851 bytes; 695 Markdown files / 28,701 lines / 3,577,155 bytes; 725 other files. Code means `.py/.ts/.tsx/.css/.js/.mjs/.ps1/.sh`; documentation means `.md`. Counts include retained history. Subsystem counts: 183 backend source Python modules, 217 backend test Python files, 48 migration Python files, 20 React TSX files, 20 browser test TS files, 40 Python scripts, 18 deployment files, 11 configuration files and 224 web-public assets. Mounted API has 46 paths. Archive copies/relocations are not deletions or size savings.

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

Local integrated gates completed as recorded below; hosted CI receipt remains separate. Production operation and real commercial coverage are outside this local cleanup. No CI speedup is claimed without measured runs.

## Exact duplicate historical records removed

Each deleted file was unreferenced by a repository-wide hidden-file search and byte-identical to the retained path below. No unique historical content was removed; original paths remain in Git history.

| Removed duplicate | Retained identical record | SHA256 |
|---|---|---|
| `.agent/archive/STAGE2-20261009/git-CURRENT_STATE.md` | `.agent/archive/STAGE2-20261009/CURRENT_STATE.md` | `69002f0c23ba1a28a55a11a03b640d405c4a9c3bc92ae3395344c1d25a6a98f3` |
| `.agent/archive/STAGE2-20261009/git-WORK_GRAPH.md` | `.agent/archive/STAGE2-20261009/WORK_GRAPH.md` | `fa7d47c320911aea17da6ca23833041fe3d89f205567115e2fb4c31b9d50f42f` |
| `.agent/archive/pre-UI79-CURRENT_STATE.md` | `.agent/archive/intelligence-20261018/CURRENT_STATE.md` | `6331ce22d6a0c3b1a66680b710d77fbd4ed4f8b1c54e47a53fc0abf2b5296951` |
| `.agent/history/pre-m5-replay-pass-20261024T024500Z-CURRENT_STATE.md` | `.agent/history/pre-m5-runtime-20261024T021700Z-CURRENT_STATE.md` | `23b41efaad1e986b3ad56deb53dc3f85fb01274626097567bc420dab2baeebde` |

## Architecture conclusions

Sol 6.1/high architecture review and three actual Luna 6/low builder sessions used the available collaboration harness; Astra 6/high independently reviewed the integrated changes. No standalone repository agent launcher was found; no provider keys were used. Actual session starts verified those models were callable. This does not assert a model identity for the root runtime.

Backend source has 183 modules: API 5, domain 30, ingestion 56, intelligence 69, integrations 4, jobs 9, persistence 7, root 3. Persistence registers 73 tables across four model files, with 48 linear migrations ending `0048_browse_recovery_stages`. The source registry has 39 definitions, 29 enabled and 30 declared retrieval methods. Every enabled definition has dispatch; three disabled retained-document definitions intentionally lack generic dispatch and must not be auto-enabled. Preserve disabled out-of-region adapters.

`api/app.py` remains oversized: 6,140 lines, 54 schema classes, 76 top-level functions and 40 route decorators. Mounted API exposes 46 schema paths (plus excluded private OpenAPI route). `saved_browse.py` lazily imports API projection/search/date/rank helpers; commercial evaluation, autonomous research, opportunity intelligence, alerts and security also import the API module. A future focused extraction should move a coherent shared projection/evaluation responsibility with explicit session/date dependencies, preserving monkeypatch and worker behavior. Simply relocating route decorators would hide this dependency rather than remove it.

## Verification receipts

All checks use local disposable PostgreSQL 18.6 databases `gridlens_cleanup` and isolated `_test` workers, synthetic browser fixtures where declared, blank paid-provider keys and no production operations.

| Check | Actual result |
|---|---|
| `uv sync --locked --extra dev` | PASS |
| `uv run ruff check src tests` / `ruff format --check src tests` | PASS |
| `uv run mypy src` | PASS |
| `uv run alembic upgrade head` / `alembic check` | PASS on fresh isolated database; migrations unchanged |
| API and worker import | PASS; browser gate also starts real API |
| `npm run typecheck` / `npm run build` | PASS |
| `npm run test:ci -- --workers=2` | 147 passed, 144.61 s invocation wall time; includes real auth and desktop/mobile regression cases |
| Locked backend pip-audit / brand pip-audit / npm audit | PASS, no known vulnerabilities reported |
| `tools/brand/validate.py` in isolated locked-requirement environment | PASS: 216 assets, hashes/fonts/tokens and eight semantic AA pairs |
| Maintained docs links / `git diff --check` | PASS |
| Independent Astra review | No unresolved critical or functional findings; archive bytes and dynamic CSS classes checked |
| `uv run pytest tests -n 4 -q` | 3,296 passed, one skipped, seven passing subtests; 451.52 s pytest / 452.68 s invocation wall time |
| Hosted CI | Latest PR checks pending; drafts until required gates finish |

Original and cleaned production bundles were built with the same installed lockfile dependencies: CSS **87,451 → 73,494 bytes** (gzip with Python gzip/mtime=0: 14,503 → 12,444); JS **367,226 → 366,981 bytes** (105,648 → 105,597 gzip). These are artifact measurements, not page-load or CI latency claims. Nine core active instruction/canon/map files shrink **3,917 → 1,722 words**, **33,784 → 16,265 bytes**. Original wording remains archived. Four exact duplicate documents remove 9,046 bytes; historical workflow/script relocation saves zero repository bytes. Dependency reduction is zero. No obsolete commercial-intelligence subsystem was removed.

## Remaining limits and PRs

- [PR145](https://github.com/nrsandoval1231-oss/gl3/pull/145): active governance, archived candidate permissions and exact historical deduplication; incorporates PR144's upstream reconciliation. [PR146](https://github.com/nrsandoval1231-oss/gl3/pull/146): unused frontend wrappers/styles, archived diagnostic and duplicate local migration command. Separate reviewable changes; no merge/deploy performed.
- Runtime OpenAPI has one existing route absent from committed generated JSON: `/api/opportunities/groups/{group_id}/open`. All common paths/schemas match. Backend/generated contracts are unchanged by cleanup; regeneration is a separate follow-up rather than a silent unrelated change.
- Full native PowerShell wrapper execution is unavailable (`pwsh` absent); its individual gates are exercised directly. The duplicate migration deletion itself is independently reviewed.
- Worker module imports and dispatch/tests are checked; no live ingestion/provider or continuous scheduled-worker run was performed. Production revision/schema, authenticated production flows, retained real-data corpus, independent exact visual screenshot comparison, fresh real-source commercial coverage and restore/rollback remain unverified by this task.
- No CI acceleration is claimed: retained PR137–143 improvements are inspected in Git, not newly benchmarked against old runs. One duplicate local command is eliminated. Full required gates and every test remain.

## Before and after (combined PR scope)

Git baseline `eadb203` → union of PR145 and PR146, including upstream PR144 documentation reconciliation: **1,986 → 1,997 files**. Four duplicate documents are deleted; two diagnostic files are relocated, not deleted. New archive/index files make the net file count rise by eleven. This task prioritizes less active context and runtime dead code over a misleading file-count target.

Retained code files: **566 → 566**; code lines **213,042 → 212,933** (**109 fewer**); code bytes **8,991,851 → 8,975,702** (**16,149 fewer**), counting the archived Python helper in both totals. Documentation totals grow because previous instructions remain preserved; exact final Markdown totals are recorded after the final report edit. No repository-size savings are attributed to archive moves/copies, and no test or intelligence service is deleted.
