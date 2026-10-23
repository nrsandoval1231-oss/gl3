# M1-BACKEND — PUCT and normal-startup browse repair

- Repo/worktree: nrsandoval1231-oss/gl3; gl3-production-20261023 under current GridLens directory.
- Branch/base: feat/production-intelligence-20261023 / a70e5330ee8ad7483391abe313d2bb9f68183975. READY; Sol approved.
- Allowed: backend/src/gridlens/ingestion/adapters/puct_docket_index.py; config/sources/registry.v1.json docket entry; related docket/registry unit tests; backend/src/gridlens/jobs/browse.py; minimal necessary saved-browse startup code; compose.yaml; deploy/digitalocean/compose.prod.yaml; focused browse startup tests; related operations/source docs.
- Exclude: frontend, other adapters, credentials, historical evidence/migrations, qualification rules, generic public HTTP security, production infrastructure, provider activation, shared graph/state.
- Invariants: exact official host/public-address/redirect protections, bounded two-query HTML/export agreement, stable identity/replay, unknown dates. Reuse browse maintainer, never full retained-data rebuild in request handling. Preserve freshness/atomicity/concurrency fences; no paid/source/research dispatch.
- Acceptance: reproduce obsolete endpoint, verify corrected live URL; guarded native parsing with stable replay identifiers; fresh Alembic migration plus ordinary documented startup publishes initial generation and authenticated Opportunities response without manual rebuild; disabled behavior/recovery covered.
- Validation: focused PUCT/registry/public HTTP and saved browse/startup tests; changed Python Ruff/mypy; compose parse. Controller full gates/runtime. Use existing isolated .env TEST database only; never reset app/fresh DB.
- Authority/risk: local reversible implementation, bounded unauthenticated public retrieval permitted; medium startup/security risk. No commit/push/merge/deploy, paid provider, new orchestrator or migration without demonstrated need/controller rescope.
- Retry: two materially different attempts then evidence.
- Handoff: .agent/artifacts/PRODUCTION-M1-BACKEND/COMPLETION.json; commands/exits/files/UTC timing, model, UNKNOWN cost/tokens. Builder does not self-certify.
- You are not alone: UI builder owns web; preserve others. No subagents. Own artifact directory only. Never print secrets.
