# GL3-001 integration amendment — PDF source-health coverage

READY after GL3-001 terminal handoff; GL3-002 exports five PDF coverage counters. Same repository/branch/base as GL3-001. One Luna reuses the released worker/API/web surfaces; adapter ownership remains disjoint. No architecture change, database mutation, cloud operation or scope expansion.

Allowed: backend/src/gridlens/jobs/worker.py, backend/src/gridlens/api/app.py, generated OpenAPI/TypeScript contract, web/src/app/App.tsx source-health presentation, completion handoff. Persist and expose pdf_candidates, pdf_eligible, pdf_enriched, pdf_skipped_not_signal, pdf_skipped_limit. Show a compact PDF enriched/eligible/deferred line for the Federal Register source so its bounded companion coverage is explicit. JSON/PDF remain one feed, with no extra project or Today event.

Validate focused lint/types, contract regeneration and web typecheck; controller owns final database/build/browser checks. Retry budget two materially different repairs. Return changed files and exact commands/results, release ownership, update GL3-001 completion without claiming acceptance.
