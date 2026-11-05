# Ingestion, evidence and ownership scoped audit

Audit snapshot: current main `593cfd516d82a12b66558f53b975ad6c2b711517`, extracted at `/workspace/gl3-audit-main`. Earlier saved checkout `d54646c` was superseded during investigation; its test results are excluded from current-head evidence. No application source was changed, no ingestion/backfill/provider action executed, and no production state accessed by this reviewer.

## Outcome

No newly validated runtime defect identified in this scoped read and isolated unit execution. This is not a claim that ingestion currently works in production. Durable queue/DB integration, live source health, contacts and runtime scheduled coverage require other audit lanes or remain unverified.

Reviewed source adapter bounds, Federal Register dual-query acquisition/completeness/deduplication, structured permit checkpoint progression, worker partial/success health handling, unchanged-record equipment receipt replay, evidence/package binding and current-read validation, deterministic equipment calculations, RRC operator identity and company contacts privacy projection. Current canon explicitly distinguishes the six-layer target from legacy qualification behavior; legacy supply/300kW gates therefore were not misreported as newly introduced defects.

## Current-head execution

Reused interpreter `/workspace/gl3/backend/.venv/bin/python`, with `PYTHONPATH=backend/src` in current snapshot. Supplied dummy local-only settings: `DATABASE_URL=postgresql+psycopg://audit@127.0.0.1:5432/audit_ingestion_test`, `APP_PASSWORD_HASH=local-audit-placeholder`, `SESSION_SECRET=local-audit-session-placeholder`. No database connection was required by these selections. Test conftest clears paid keys and blocks external socket/DNS/httpx access.

- Equipment deterministic/extraction/claim tests: `python -m pytest backend/tests/unit/test_equipment_demand.py backend/tests/unit/test_equipment_claims.py backend/tests/unit/test_equipment_extraction.py backend/tests/unit/test_ferc_equipment_extraction.py backend/tests/unit/test_ferc_equipment_interpretation.py -q --tb=short`: **170 passed in 4.11s**, `/workspace/audit-ingestion-unit.log`.
- Adapter/legacy qualification tests: `python -m pytest backend/tests/unit/test_socrata_permits.py backend/tests/unit/test_rrc_drilling.py backend/tests/unit/test_rrc_completion.py backend/tests/unit/test_rrc_customer_identity.py backend/tests/unit/test_rrc_operator_directory.py backend/tests/unit/test_rrc_result_identity.py backend/tests/unit/test_rrc_flare_exceptions.py backend/tests/unit/test_power_qualification.py -q --tb=short`: **196 passed in 1.93s**, `/workspace/audit-ingestion-adapters.log`.
- Federal Register acquisition tests: `python -m pytest backend/tests/unit/test_federal_register.py -q --tb=short`: **20 passed in 0.67s**, `/workspace/audit-ingestion-federal.log`.

Initial current-snapshot run omitted mandatory dummy settings and failed test setup; rerun above corrected the isolated environment. Initial stale-checkout mixed selection had DB setup errors (local PostgreSQL unavailable) and is not current-head evidence.

## Material documented coverage limits, not newly discovered defects

1. **RRC flare/vent status freshness and outage recovery are bounded.** `config/sources/registry.v1.json:27-34` explicitly configures only three calendar days by submittal date. `backend/src/gridlens/ingestion/adapters/rrc_flare_exceptions.py:282-283` computes that window from today, not a last-success cursor. A filing submitted four days ago that later changes status will not be rechecked; an outage exceeding overlap can miss submissions. This is a confirmed static acquisition limitation, already documented, not proof that any actual live filing is stale. Recommendation: bounded retained-ID status monitoring plus missed-window recovery, tested with outage and late-status-change fixtures. Do not represent this feed as comprehensive current authorization or flaring demand.
2. **RRC drilling history recovery is limited to current/prior monthly snapshots.** Registry lines 84-85 explicitly state older-month correction monitoring is absent and outages beyond overlap can miss activity. Source absence does not delete retained entities. Recommendation: separately scoped catch-up policy and stale-entity visibility, without claiming discovery completeness.
3. **Equipment target remains narrow.** Current native FERC records intentionally preserve UNKNOWN quantity, buyer and current status; broader prose/table extraction, physical-unit deduplication and portfolio MW remain deferred. Current read projection abstains on differing schedule signatures (`equipment_intelligence.py:968-995`) rather than adding quantities. Future proposed equipment retaining planned capacity before its effective date is explicitly tested (`test_equipment_demand.py:234`); it was investigated and rejected as an alleged as-of arithmetic bug.

## Operational documentation discrepancy requiring live resolution

`.agent/CURRENT_STATE.md` says an e97 main canary reached API/web with workers held, failed visual acceptance, and PR148 image rollback is **in progress**. `docs/product/PROJECT_FIRST_RESULTS_CANON.md` calls PR148 the latest available production receipt. These are dated evidence, not proof of the live image. The deployed SHA and worker state must be established from fresh read-only inspection. This lane did not inspect deployment access.

## Blockers and limits

No operation denied. No production/login action pending or uncertain in this lane. Production deployed revision, live source freshness, scheduled recovery behavior, provider integration, DB-backed contacts and full durable queue integration were not verified here. Parent audit owns full-suite/database and live QA coverage; this report supplies scoped unit evidence only.
