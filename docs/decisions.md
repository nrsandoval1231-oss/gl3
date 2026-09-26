# Decisions

Record a date, decision, reason, alternatives considered, and affected PRD requirement when a substantive implementation choice is made. Keep product changes explicit.

| Date | Decision | Reason | Requirements |
|---|---|---|---|
| 2026-09-24 | Use new repository `gl3` and a fresh implementation. | Owner requested a clean-sheet build. | 1 |
| 2026-09-24 | Adopt the [ingestion strategy](sources/ingestion-strategy.md): prioritize validated coverage and reliable discovery; retain the managed scheduler, PostgreSQL jobs, and Python worker as the ingestion execution system. Defer n8n research workflows; consider an individual connector only with demonstrated implementation value. | Prove real source access, useful discoveries, freshness, and recovery before adding investigation infrastructure. Add historical and live discovery checks to assess coverage; document limits. Alternatives considered: n8n research orchestration first or split ingestion scheduling. | 4–12, 15–18, 35–42 |

| 2026-09-25 | Initial source selection: broad Federal Register EIS notices, then NC Commerce announcements and discovered GovInfo PDFs. | Direct public retrieval succeeded; specific development/expansion events inspected without project-name queries. PDF and JSON copies count as one underlying feed. USACE runtime 403 excludes it for now. See coverage.md. | 5, 8–13, 19, 38 |
| 2026-09-25 | Use an isolated local PostgreSQL cluster on loopback port 55439 for local proof. | Existing PostgreSQL service is preserved; Docker engine was not available. Fresh databases and generated SCRAM secret remain ignored. No cloud service or account provisioned. | 1, 3–4, 35–36 |
