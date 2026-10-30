# Working in GridLens GL3

Read in order:
1. [Autonomous intelligence canon](docs/product/AUTONOMOUS_INTELLIGENCE_CANON.md).
2. [PRD](docs/product/PRD.md), then compatible [results semantics](docs/product/PROJECT_FIRST_RESULTS_CANON.md).
3. [UI and brand canon](docs/design/UI_CANON.md); preserve the October 29 released presentation.
4. [Architecture](docs/architecture/overview.md), [current checkpoint](.agent/CURRENT_STATE.md), and [finish contract](.agent/FINISH_CONTRACT.md).

The Autonomous Intelligence Canon is the sole active product authority. Supporting specifications cannot override it. Current owner instructions override historical plans and release exceptions. [Documentation map](docs/README.md) separates maintained guides from dated evidence.

Target architecture: (1) Discovery, (2) Entity/Evidence, (3) Electrical Demand, (4) Lifecycle/Timing, (5) Commercial, (6) Autonomous Evaluation. GridLens centers demand identification and characterization; it does not assert utility shortages, supply constraints, or a publication gate. Preserve dated legacy qualification behavior where current code still uses it, but treat it as evolving/legacy, not target identity. Preserve evidence provenance, privacy/suppression, retries, idempotency, provider accounting and recovery.

Keep ordinary UX autonomous/read-only, compact and responsive with All / Oil & Gas / Data Centers. No routine call/status/note/fact-entry workflows, redesign, new infrastructure or speculative abstractions. Retain audited internal exceptional safeguards.

Validate with [scripts/check.ps1](scripts/check.ps1) and the [CI workflow](.github/workflows/ci.yml); use separate disposable test databases, never retained/production data. Run maintained-doc links with `uv run --project backend python scripts/check_docs.py`. Preserve full gates, network guards and browser checks. Report exact commands/results and unavailable verification; dated receipts never prove current operation.

Use the repository OpenAI harness where available: Sol 6.1/high coordination, 3–6 Luna 6/low builders, Astra 6/high review. Verify availability, partition file ownership and independently review the integrated candidate. Do not claim assignments or checks that did not run.

No production deployment, credential changes, paid-provider execution, destructive data action or history rewriting without separate authorization. Previous PR-specific permissions are [historical](.agent/archive/STREAMLINING-20261029/README.md).

CURRENT CANDIDATE: bounded equipment parsing, deterministic demand, source-bound `equipment-demand-v1` records on existing `EvidencePackage`, normal/unchanged ingestion hooks and intelligence-card output. No migration or new provider. Demand-centered UI preserves the October 29 layout; portfolio totals remain unavailable. TARGET: the six-layer architecture. NEXT: real engineering-document coverage, buyer attribution and deduplicated portfolio demand/ranking; see [audit and implementation](docs/engineering/equipment-demand-slice-20261030.md). Keep documented/calculated/estimated/inferred/unknown distinct. Athena remains optional and replaceable. Latest production evidence is the dated PR148/schema0049 receipt, not a fresh inspection or this candidate's deployment.
