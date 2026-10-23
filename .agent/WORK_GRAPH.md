# Production intelligence work graph

Base a70e5330ee8ad7483391abe313d2bb9f68183975. Owner directive/PRD govern; no merge/deploy.
One opening Tribunal completed; do not reconvene during build.

| Node | Dependencies | State | Acceptance |
|---|---|---|---|
| M1-BACKEND | opening | ACCEPTED | ten records persisted; zero new/ten unchanged on live replay; normal startup authenticated200 without manual rebuild |
| M1-UI | opening | ACCEPTED | long-value fixture at1280×800,1648px and390×844; no clipping; screenshots retained |
| M1-GATE | both handoffs | ACCEPTED | exact 5c7ad6f; backend, serial browser, docs, independent Sol PASS; remote CI 39999964231 success |
| M2-ACQUISITION | M1-GATE | ACCEPTED | exact86a4434 independent Sol PASS; backend2779/browser191, docs and CI40009230663 PASS; one real Firecrawl call and replay |
| M3-EVIDENCE | M2 | VALIDATING | independent914caf4FIX corrected through Sol recovery; root77focused tests and repaired real replay PASS; new frozen full gates/CI/re-review pending |
| M4-INTELLIGENCE | M3 | WAIT | supported OpenAI model, cited structured assessments, deterministic gates |
| M5-RESOLUTION | M4 | WAIT | account/project/buying chain identity,446-record investigation, five regional sources, bounded continuation |
| M6-ACCEPTANCE | M5 | WAIT | five-project live chain, cost/latency/recovery, full regressions/browser, runbook/readiness PR |

M3 recovery and replay correction handoffs are terminal. Original two repairs, independent FIX, interrupted full gates and subsequent recovery failures remain retained. Controller owns PostgreSQL/bootstrap, paid live runs, evidence, integration, commits/PR and graph. Independent Sol re-review follows the new frozen candidate. Builders cannot commit or alter shared runtime. Provider access/pricing gaps stay UNKNOWN; fixtures cannot pass live acceptance. M4 remains WAIT until M3 acceptance and secure OpenAI/model access.
