# Autonomous migration inventory

Authority: [Autonomous Intelligence Canon](../product/AUTONOMOUS_INTELLIGENCE_CANON.md). This inventory records concrete conflicting elements and their dispositions. It is an acceptance checklist, not a blanket claim that an assigned change or final runtime gate has passed. Final integration receipts identify the exact candidate and actual results. `KEEP` preserves compatible behavior/data, `TRANSFORM` replaces the behavior under autonomous requirements, `REMOVE` deletes obsolete product code, and `ARCHIVE` retains historical instructions as dated evidence.

## Product and governing instructions

| Path / conflicting element | Disposition | Required result / evidence |
|---|---|---|
| `AGENTS.md` and `docs/product/AUTONOMOUS_INTELLIGENCE_CANON.md` | KEEP | Highest owner-approved authority, supported OpenAI harness, evidence/data safeguards, autonomous stages and no human data-entry product |
| `docs/product/PRD.md`: sole authority, fresh repository, manual daily journey | TRANSFORM | Canon precedence, improve existing system, user reads automatically refreshed intelligence |
| `docs/product/PRD.md`: requirement 30, pursuit-status vocabulary/filter, call acceptance example, notes/follow-up milestones and tree | TRANSFORM | Remove manual input requirements, preserve historical attribution; automated evidence update and commercial-disposition semantics |
| `docs/product/PRD.md`: User-confirmed label and location/conflict “review” | TRANSFORM | Retained historical attribution only; autonomous investigation/unresolved state, no operator acceptance gate |
| `docs/product/PRD.md`: TX/OK/NM, 300 kW, requirements 19–26, original live launch gates | KEEP | Physical-site eligibility, unknown-versus-zero, source-specific demand/supply, deterministic tiers and separately verified launch evidence |
| `docs/design/UI_CANON.md`: status column, Notes, preserve every old route/workflow | TRANSFORM | Dense evidence-derived table/detail, no operator controls, current autonomous destinations, seven-color brand and mobile reflow |
| `docs/design/PURSUIT_WORKSPACE.md`: call/fact/notes/correction workflows | TRANSFORM | Autonomous opportunity/contact/evidence/research contract with unified search |
| `README.md`, `docs/README.md`, `docs/product/README.md` | TRANSFORM | Canon-first authority links, regional autonomous product scope |
| `.agent/OWNER_REQUEST.md`: regional-only UI restrictions, old PRD as sole canon | TRANSFORM | Current complete autonomous scope and original compatible safeguards |
| `.agent/CURRENT_STATE.md`: PR122 as current task, old benchmark as current state | TRANSFORM | Current work and exact-candidate evidence boundary; benchmark results historical only |
| `.agent/AGENT_RULES.md`: single serial Luna, preserve old workflows | TRANSFORM | Owner-approved isolated parallel builders, actual model availability and independent review |
| `.agent/FINISH_CONTRACT.md`, `.agent/WORK_GRAPH.md`: prior manual slice and release directions | TRANSFORM | Autonomous implementation acceptance, actual assignments, independent review; separate live launch/deployment gates |
| `.agent/PRODUCTION_INTELLIGENCE_DIRECTIVE.md`, `docs/architecture/INTELLIGENCE_INTEGRATION_STRATEGY.md` | ARCHIVE | Earlier directions explicitly subordinate; compatible evidence/model safeguards preserved |
| `docs/architecture/autonomous-pursuit-research.md` | ARCHIVE | Prior operator-refresh/contribution instructions remain historical implementation record |
| `docs/design/DASHBOARD_IMPLEMENTATION.md`, `docs/design/UI_MIGRATION_20261020.md`, `docs/delivery/build-plan.md`, `docs/delivery/milestones.md` | ARCHIVE | Prominent historical notices; earlier manual workflow/test results do not govern this candidate |
| `docs/operations/commercial-pursuits.md`, `docs/operations/intelligence-surfaces.md` | TRANSFORM | Superseded manual guide replaced by current autonomous/internal boundaries; original text preserved |
| `docs/operations/README.md`: October 24 release authorization as current | TRANSFORM | Dated observation remains evidence; no inherited deployment/spending authorization for this candidate |
| `.agent/archive/AUTONOMOUS-20261026/` | ARCHIVE | Lossless deterministic `.md.gz` snapshots of pre-edit active directions; decompress for exact original bytes |
| `scripts/check_docs.py`, `scripts/README.md`, `scripts/README-pursuit-research-validation.md` | TRANSFORM | Maintained authority link checks include canon/agent files; internal isolated utilities cannot recreate retired user workflows |

## Removed user features and dependency chain

| Path / feature | Disposition | Required result / retained dependency |
|---|---|---|
| `web/src/features/pursuits/QuickCallLog.tsx` | REMOVE | Delete call entry component and imports; no renamed log action |
| `web/src/features/pursuits/FactWorkflowPanel.tsx` | REMOVE | Delete manual fact draft/accept/reject/correct/retract controls |
| `web/src/features/pursuits/callDrafts.ts` | REMOVE | Delete obsolete browser draft persistence |
| `web/src/features/pursuits/CommercialPursuits.tsx`, `Pursuits.tsx`, `commercialDrafts.ts` | REMOVE | Delete manual question/note/pursuit workspace dependencies |
| `web/src/features/pursuits/IntelligenceResearch.tsx` | REMOVE | Delete owner feedback/candidate acceptance/manual request UI |
| `web/src/features/pursuits/ResearchChanges.tsx`, `ResearchChanges.css` | REMOVE | Delete obsolete manual research-change review component/style dependencies |
| `web/src/features/workspace/WorkspaceDetail.tsx` | TRANSFORM | Source-backed identity/gap/timing/buyer/contact details; remove call/status/fact/note forms and manual generation triggers |
| `web/src/features/buyingChain/BuyingChain.tsx` | TRANSFORM | Read-only role/source/contact inspection; remove operator correction/enrichment controls |
| `web/src/features/workspace/WorkspaceChanges.tsx` | TRANSFORM | Read-only material intelligence changes; no administrative review acknowledgment workflow |
| `web/src/features/pursuits/AutonomousResearch.tsx`, `ResearchView.tsx` | TRANSFORM | Read-only autonomous research status/findings/unknowns; no question editor or start button |
| `web/src/features/workspace/Workspace.tsx`, `GlobalSearch.tsx` | TRANSFORM | Opportunities/Research/Signals and unified company/project/contact/intelligence search with restored URL and mobile state |
| `web/src/api/client.ts` | REMOVE / TRANSFORM | Delete manual mutation helpers and obsolete draft/status types; keep current authenticated reads/search |
| `web/src/styles/pursuits.css` | REMOVE / KEEP | Remove orphaned manual-form styles; retain active autonomous research styling |
| `backend/src/gridlens/api/app.py`: fact draft/decision and workflow-status handlers | REMOVE | Physically remove obsolete handlers/request models/write-only helpers and mounted OpenAPI entries; preserve read-side historical evidence services |
| `backend/src/gridlens/api/app.py`: pursuit notes, exact-question research, manual research trigger/evaluation | REMOVE | No user-operated logging or arbitrary research mutation route; scheduled machine research/evaluation survives |
| `backend/src/gridlens/api/app.py`: customer membership/buying-chain corrections, signal adjudication, change acknowledgment | REMOVE | Public operator mutation routes retired; immutable corrections and independent worker qualification retained |
| `backend/src/gridlens/api/intelligence.py`: task/watch/review mutations | REMOVE | No owner-feedback, manual candidate acceptance, watch-maintenance or job-entry product; internal durable automation retained |
| `backend/src/gridlens/api/app.py`: unified search and opportunity/contacts/research reads | TRANSFORM | Bounded authenticated region-eligible results, current source-backed identity/contact/intelligence and explicit unknowns |
| `backend/src/gridlens/intelligence/customer_accounts.py`: `retract_customer_membership` | REMOVE | Remove manual-only service if no remaining automated caller; retain account membership projections/evidence |
| `backend/src/gridlens/intelligence/buying_chain_corrections.py`: `correct_buying_chain_claim` | REMOVE | Remove manual-only writer after caller audit; preserve correction history/view needed by historical reads |
| `backend/src/gridlens/domain/call_facts.py`, qualification/ingestion consumers | KEEP | Historical validation and effective qualification evidence remain; no deletion merely because user routes disappear |
| `backend/src/gridlens/intelligence/commercial_evaluation.py`, `signal_adjudication.py` | KEEP | Automated deterministic/machine job consumers remain after public trigger removal; verify callers before deletion |

## Persistence, automation, tests and evidence

| Path / element | Disposition | Required result / acceptance evidence |
|---|---|---|
| `backend/src/gridlens/persistence/models.py`: `CallFactVersion`, `CallFactDecision`, `NeedWorkflowStatusEvent`, `PursuitCallNote` | KEEP | Preserve existing historical rows, attribution and audit; no schema or data drops |
| Same model file: `BuyingChainCorrection`, `CompanyProjectMembershipCorrection` | KEEP | Retained decisions continue to explain effective historical projections |
| `backend/migrations/versions/0027_intelligence_review.py`, `0033_workspace_review.py`, `0034_draft_fact_browse_invalidation.py`, `0036_buying_chain_corrections.py` and prior migrations | KEEP | Migration history and read/invalidation compatibility remain; obsolete UI does not authorize migration rewrite |
| Sources, observations, immutable evidence, buying-chain claims/evidence, change events, source epochs | KEEP | Preserve original URLs/hashes/dates, versions, conflicts and negative evidence through replay/failure |
| `backend/src/gridlens/jobs/worker.py` and queue/planner persistence | TRANSFORM | Independent scheduled incremental work, durable replica coordination, bounded recovery, source isolation and truthful health |
| `backend/src/gridlens/ingestion/adapters/diagnostics.py` and retry propagation | TRANSFORM | Honor bounded publisher retry deadlines without operator-maintenance dead ends or false scheduled success |
| `backend/src/gridlens/intelligence/pursuit_questions.py`, `domain/pursuit_research.py` | TRANSFORM | Choose bounded eligible research after freshness/backoff/retry/in-flight checks; early unresolved categories cannot starve later facts |
| `backend/src/gridlens/intelligence/company_contact_discovery.py`, `company_contacts.py` | TRANSFORM | Fair scheduled source-backed discovery and refresh; failed/unresolved work retries within bounds, stale successful contact sources rechecked |
| `backend/src/gridlens/domain/opportunity_intelligence.py`, `ranking.py`, buying-chain projection | TRANSFORM / KEEP | Owner/developer-first headline, preserved distinct sites, conservative verified methods, explainable priority separate from confidence and tier |
| `backend/src/gridlens/settings.py`, `deploy/**` | TRANSFORM | Automatic bounded unpaid analysis/planning; external retrieval/model provider credentials, licensing and cost controls fail closed |
| `web/tests/call-facts.spec.ts`, `pursuit-refresh.spec.ts`, `pursuits.spec.ts` | REMOVE | Remove tests requiring obsolete manual features; replace with retired-feature absence and current authenticated/mobile behavior checks |
| Remaining web tests for commercial/research/corrections/status UI | TRANSFORM | Assert current autonomous surfaces, sources/contacts/search, loading/error/unknown states and readable mobile interaction |
| `backend/tests/integration/test_call_fact_workflow_integration.py` and manual API cases | TRANSFORM | Public retired-route denial; preserve service/DB-level historical qualification and evidence read tests |
| `backend/tests/unit/test_call_facts.py` | KEEP | Domain validation/qualification boundaries for retained evidence remain useful |
| API/search, contact/research, queue/planner integration tests | TRANSFORM | Contract/auth/territory, evidence/freshness, fairness/retry/idempotency and source isolation proof on disposable databases |
| `docs/validation/contact-intelligence/benchmark-v12-company-contacts.csv`, `firecrawl-v12-results.json`, `production-inventory-20261025.json` | KEEP | Historical evaluation/observation only; no blind import into accepted fresh contacts or present completion claims |
| Other `docs/validation/**`, historical `.agent` receipts and screenshots | KEEP | Candidate/environment/date-bound evidence, preserved without promotion to current requirements |

The historical v12 benchmark reported 4 of 20 companies with usable company methods (20%), 2 companies with named professionals, and zero direct buyer methods. Its production observation reported zero customer email/phone coverage among 235 eligible primary customers. These are historical baselines, not measurements of this candidate, current provider availability or production operation. Apollo access/licensing and current paid-provider budget require separate evidence; no free or authorized dataset is assumed.

The controller must verify actual physical deletions, remaining imports/callers, mounted routes/OpenAPI, preserved historical reads/data, focused tests and full relevant gates against the integrated candidate. Unused manual code cannot be left behind merely by hiding the navigation. See the [retention map](autonomous-intelligence.md) and [Finish Contract](../../.agent/FINISH_CONTRACT.md).
