# F — Commercial and operations integration

Depends on frozen B2/D and C interfaces, same isolated branch. Owner authorizes
useful integration surfaces in existing approved UI; no sidebar/photos/redesign.
Canonical tier/priority/pursuit/activity/buyer distinctions remain unchanged.

Own new `api/intelligence.py`, new `intelligence/intelligence_operations.py`,
new web `features/pursuits/IntelligenceResearch.tsx` and compact operations component,
generated OpenAPI/types and narrow wiring in client/existing detail/health panel.
Controller will serialize any shared app.py/models/settings/worker edits.

Service interfaces:
`enqueue_intelligence(session, *, need_id, task_type, question_id=None, origin='operator') -> Job`;
`intelligence_history(session,need_id,limit<=50) -> list[dict]`;
`enqueue_missing_intelligence(session, *, need_id,question_ids,origin=...)`.
Tasks eight Jev contracts or GROUNDED_EXTRACTION/GROUNDED_DOSSIER. History envelope
job/task/need/status/result/error/evidence_ids/logical_call_id/usage/reserved/
uncertain/created_at/completed_at. Read only persisted data, no model call on GET.
Watch service `upsert_watch(session,need_id,*,sources,question_ids=None,enabled=True)`
and `watch_view(session,need_id)`; source dict has reviewed source_id/exact URLs.
No model URL or applicant role grants acquisition or buyer authority.

Authenticated API: bounded history/tasks/eligible request/retry; truthful disabled,
queued/running/completed/unknown/blocked/stale. Enqueue commits atomically, same
durable policy controls. Cancellation before dispatch only; UNKNOWN cannot retry.
Inspect exact candidate evidence/hash/quote/location/date/source/validation status;
explicitly candidate/source-review-required, not an accepted fact. Show meaningful
unanswered question/next action; preserve previous last-good commercial values.
Owner review can append an attributed persisted note through existing pursuit-note
records referencing exact call/need and idempotent client ID. Never overwrite model
result/history, silently label evaluation truth or promote tiers. Existing correction
and pursuit-status APIs remain authoritative. Evaluation exports expose review notes
as attributed pending-review material, not automatic benchmark labels.

Operations: configured/enabled/called/completed/accepted separate; no secret dumps.
SQL bounded aggregates over source/due receipts/queue/ledger/questions/changes.
Counts zero only when actually queried; unavailable/backup/restore UNKNOWN unless
receipts exist. Provider actual/pinned models, errors/p95 (measured only), usage,
reserved/known/uncertain USD and outstanding unknown calls. Key present ≠ healthy.
Source last cycle/due/checked/partial/failed/freshness/parser failures, queued oldest,
retry/deadletter counts, watch state, question outcomes, reviewed Signals/independent
Leads only if supported review provenance exists. Do not invent acceptance counts.
No provider probe, source retrieval, state mutation or full corpus projection on GET.

UI: integrate research component into existing exact-need detail/action and ops into
existing source-health disclosure. Ordinary commercial workflow stays concise.
No fabricated diagrams/gaps; null/UNKNOWN/CONFLICT visible. Focusable controls,
loading/errors, cancel stale requests on need switch; polling only active jobs and
bounded. Native existing CSS tokens. Generate API schemas after routes stabilize.

Tests: actual authenticated API on isolated PostgreSQL; unauth/CSRF/wrong need/
unsupported task/limits; durable request/result/feedback/replay; no network read;
missing measurements UNKNOWN. Browser tests candidate citations, disabled controls,
question outcomes, owner note persistence, rapid need change, mobile keyboard UI.
Typecheck/build/regression; runtime proof desktop/mobile. Root runs final full gates.
Return exact files/evidence/timing/limits, no self acceptance/commit/push/deploy.
