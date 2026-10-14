# Build plan — October 14, 2026

Goal: a deployed, daily-running GridLens Nick uses for real calls. Gates stay as defined in [milestones](milestones.md); this file is the execution order.

| Phase | Work | Closes |
|---|---|---|
| 0 — Unblock | Restore GitHub CI; hermetic tests; fix RRC drilling non-ASCII decode; clear Houston staleness message; record owner decisions | — |
| 1 — Deploy | DigitalOcean droplet (API, worker, web) + managed PostgreSQL + Spaces; Cloudflare DNS/TLS; scheduled 07:00 America/Chicago collection with `WORKER_AUTO_REFRESH=false`; nightly backup and one restore drill; ntfy alerts for overdue/failed sources | Milestone A; starts the seven-cycle clock |
| 2 — Usable UI | Rebuild the shell to the [UI canon](../design/UI_CANON.md): navy canvas, U.S. map, tier/lens selector, bottom command bar, project → need → evidence → buyers → action, Back restoration; merge "Today's pursuits" into the home view | S5; owner visual acceptance |
| 3 — First Lead | 3–5 discovery calls through the call-facts workflow; add load-stating sources (ERCOT large-load / PUCT dockets, TCEQ generator air permits, county abatement agendas, California utility/regulatory, a second national structured source); fix Clayton grouping and source-role titles | C, D; Req 38, 41 |
| 4 — Structure | Split `api/app.py` into routers; move projection helpers out of the API layer; one AI provider adapter; web reads verticals from the API | S6; audit D5–D8 |
| 5 — Launch | 30-record qualification review, seven measured daily cycles, Nick-reviewed Lead | E; Req 38–41 |
| 6 — Process reset | Archive `.agent` packets; move bulky validation JSON out of Git; one status page | R3, R4 |
