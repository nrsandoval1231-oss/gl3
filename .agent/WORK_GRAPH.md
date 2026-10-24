# Production hardening work graph — 2026-10-24

Build on accepted PR119/main `de1c7b0`; no hygiene re-audit, new architecture, or Tribunal.

| Node | State | Evidence / dependency |
|---|---|---|
| H1 security residuals | INVESTIGATION_COMPLETE / RISK_OPEN | Historical 242-row matrix and fresh preliminary API/web/Postgres scans documented. Preliminary images are from `de1c7b0`, before H2 lease fix. Residual package/vendor risk and owner credential disposition remain open; exact-candidate scans pending. |
| H2 DB/source reliability | IMPLEMENTED / FOCUSED_TESTS_PASS | Bounded lease-renewer `SKIP LOCKED` retry. Focused Postgres tests: 2 passed in 2.73s. Historical blocker identity and autovacuum conflict remain unknown; no speculative DB settings changes. |
| H3 credential/corpus | BLOCKED_EXTERNAL_EVIDENCE | Owner says Google key ownership UNKNOWN; no GCP admin evidence. Alert remains open. Original 446-record export absent from targeted connected/local named-export searches; 578 corpus is not a substitute. |
| H4 release/restore/rollback | LOCAL_PROOFS_PASS / PRODUCTION_PROCEDURE_BLOCKED | `rehearsal-development-5` and actual service-development-3 proofs passed; these support repository-candidate evidence only. Production cutover is BLOCKED / NOT EXECUTABLE because the protected wrapper starts all services and cannot perform selective canary, one-shot candidate browse rebuild before API reads, or held worker/browse writes. Local helper does not validate wrapper execution. |
| H5 exact validation/review | REPOSITORY_CANDIDATE_TRACKED_SEPARATELY | Rebuild/scan exact candidate SHA including H2 fix; run full gates/CI and follow-up independent Sol review. Preliminary `de1c7b0` images do not include H2. Repository review status cannot clear the production procedure blocker. |
| H6 reviewed merge/main/release record | PRODUCTION_NO_GO | Exact-head guarded PR/main CI and release record remain separate from cutover authority. Protected wrapper/config changes or production cutover testing require owner deployment authorization; none is present. Gate A and Gate B remain separate. |

Controller owns builds, shared Docker/test DB, live read-only probes, and final integration. No production deployment, mutation, provider dispatch, Albuquerque retry, budget change, history rewrite, or uncertain cleanup.
