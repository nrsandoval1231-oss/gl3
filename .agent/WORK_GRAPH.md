# Production hardening work graph — 2026-10-24

Build on accepted PR119/main `de1c7b0`; no hygiene re-audit, new architecture, or Tribunal.

| Node | State | Evidence / dependency |
|---|---|---|
| H1 security residuals | INVESTIGATION_COMPLETE / RISK_OPEN | Historical 242-row matrix and fresh preliminary API/web/Postgres scans documented. Preliminary images are from `de1c7b0`, before H2 lease fix. Residual package/vendor risk and owner credential disposition remain open; exact-candidate scans pending. |
| H2 DB/source reliability | IMPLEMENTED / FOCUSED_TESTS_PASS | Bounded lease-renewer `SKIP LOCKED` retry. Focused Postgres tests: 2 passed in 2.73s. Historical blocker identity and autovacuum conflict remain unknown; no speculative DB settings changes. |
| H3 credential/corpus | BLOCKED_EXTERNAL_EVIDENCE | Owner says Google key ownership UNKNOWN; no GCP admin evidence. Alert remains open. Original 446-record export absent from targeted connected/local named-export searches; 578 corpus is not a substitute. |
| H4 release/restore/rollback | DEVELOPMENT_PROOFS_PASS | `rehearsal-development-5` passed; actual service-development-3 proof passed. These do not establish production readiness. Rollback requires preserving a compatible, unexpired prior browse generation and input revision, captured before candidate cutover. |
| H5 exact validation/review | READY_AFTER_FREEZE | Rebuild/scan exact candidate SHA including H2 fix; run full gates/CI and independent Sol review. Preliminary `de1c7b0` images do not include H2. |
| H6 reviewed merge/main/release record | DEPENDENT | Exact-head guarded PR/main CI and release record. Gate A and Gate B stay separate; owner risk disposition and deployment authorization remain explicit. |

Controller owns builds, shared Docker/test DB, live read-only probes, and final integration. No production deployment, mutation, provider dispatch, Albuquerque retry, budget change, history rewrite, or uncertain cleanup.
