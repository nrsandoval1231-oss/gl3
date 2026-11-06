# Working in GridLens GL3

Read in order:
1. [Autonomous intelligence canon](docs/product/AUTONOMOUS_INTELLIGENCE_CANON.md).
2. [PRD](docs/product/PRD.md), then compatible [results semantics](docs/product/PROJECT_FIRST_RESULTS_CANON.md).
3. [UI and brand canon](docs/design/UI_CANON.md); preserve the released visual identity and the bounded November 2 refinements.
4. [Architecture](docs/architecture/overview.md), [current checkpoint](.agent/CURRENT_STATE.md), and [finish contract](.agent/FINISH_CONTRACT.md).

The Autonomous Intelligence Canon is the sole active product authority. Supporting specifications cannot override it. Current owner instructions override historical plans and release exceptions. [Documentation map](docs/README.md) separates maintained guides from dated evidence.

Target architecture: (1) Discovery, (2) Entity/Evidence, (3) Electrical Demand, (4) Lifecycle/Timing, (5) Commercial, (6) Autonomous Evaluation. GridLens centers demand identification and characterization; it does not assert utility shortages, supply constraints, or a publication gate. Preserve dated legacy qualification behavior where current code still uses it, but treat it as evolving/legacy, not target identity. Preserve evidence provenance, privacy/suppression, retries, idempotency, provider accounting and recovery.

Keep ordinary UX autonomous/read-only, compact and responsive with All / Oil & Gas / Data Centers. No routine call/status/note/fact-entry workflows, redesign, new infrastructure or speculative abstractions — **except** the owner-authorized (2026-11-06) four-section navigation (Opportunities | Companies | Pursuits | Reports) and the owner-managed Pursuits workspace (stages, follow-up tasks, user-confirmed activity), which is the only place manual execution state is recorded; see [commercial pursuits](docs/engineering/commercial-pursuits-20261106.md) and the UI canon. Retain audited internal exceptional safeguards.

Validate with [scripts/check.ps1](scripts/check.ps1) and the [CI workflow](.github/workflows/ci.yml); use separate disposable test databases, never retained/production data. Run maintained-doc links with `uv run --project backend python scripts/check_docs.py`. Preserve full gates, network guards and browser checks. Report exact commands/results and unavailable verification; dated receipts never prove current operation.

Use the repository OpenAI harness where available: Sol 6.1/high coordination, 3–6 Luna 6/low builders, Astra 6/high review. Verify availability, partition file ownership and independently review the integrated candidate. Do not claim assignments or checks that did not run.

No production deployment, credential changes, paid-provider execution, destructive data action or history rewriting without separate authorization. Previous PR-specific permissions are [historical](.agent/archive/STREAMLINING-20261029/README.md).

CURRENT RELEASE (the commercial workspace and schema 0050 were merged to `main` in PR #183 (`cbe4aec`) but are not deployed; production remains at schema 0049): application main `ec6486a2` (PR165) is deployed and independently accepted; see the [November 2 release receipt](docs/validation/production-release-20261102.md) for exact images/schema/CI/recovery/live evidence and limitations. Current implementation includes bounded equipment parsing, deterministic source-bound `equipment-demand-v1` records on existing `EvidencePackage`, normal/unchanged ingestion hooks, native notice assertions, customer/operator rollups, conservative equipment-only demand summary, source continuation and guarded browse recovery. PR165 adds truthful changed-cohort loading/retry, count/header alignment and the bounded Oil-query repair. No schema/provider activation occurred.

TARGET remains the six-layer architecture. Demand summary was unavailable with zero supported validated equipment records at the dated live observation; unknown is not zero and equipment MW is not portfolio demand. Source code deployment does not prove broad source coverage or sustained scheduled cycles. NEXT requires separately scoped freshness/source-cycle observation, wider engineering/buyer evidence and deduplicated portfolio aggregation; see [audit and implementation](docs/engineering/equipment-demand-slice-20261030.md). Keep documented/calculated/estimated/inferred/unknown distinct. Athena remains optional and replaceable. Current [checkpoint](.agent/CURRENT_STATE.md) and [owner request](.agent/OWNER_REQUEST.md) distinguish documentation progress from future runtime authorization.
