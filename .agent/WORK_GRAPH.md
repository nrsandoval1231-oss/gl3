# Production intelligence work graph

Base a70e5330ee8ad7483391abe313d2bb9f68183975. Owner directive/PRD govern; no merge/deploy.
One opening Tribunal completed; do not reconvene during build.

| Node | Dependencies | State | Acceptance |
|---|---|---|---|
| M1-BACKEND | opening | HANDOFF | ten records persisted; zero new/ten unchanged on live replay; normal startup authenticated200 without manual rebuild |
| M1-UI | opening | HANDOFF | long-value fixture at1280×800,1648px and390×844; no clipping; screenshots retained |
| M1-GATE | both handoffs | VALIDATE | freeze implementation/docs, controller full gates, exact-candidate Sol review |
| M2-ACQUISITION | M1-GATE | WAIT | optional bounded Firecrawl reused; five-source native comparison, provenance/replay/cost/latency |
| M3-EVIDENCE | M2 | WAIT | live Jev capability, persisted versioned packages, explicit incomplete failures |
| M4-INTELLIGENCE | M3 | WAIT | supported OpenAI model, cited structured assessments, deterministic gates |
| M5-RESOLUTION | M4 | WAIT | account/project/buying chain identity,446-record investigation, five regional sources, bounded continuation |
| M6-ACCEPTANCE | M5 | WAIT | five-project live chain, cost/latency/recovery, full regressions/browser, runbook/readiness PR |

Backend/frontend own disjoint files in isolated integration worktree. Builders cannot commit or alter shared runtime. Controller owns PostgreSQL/bootstrap, evidence, integration, commits/PR, graph. Integrate backend then UI. Provider access/pricing gaps stay UNKNOWN; fixtures cannot pass live acceptance.
