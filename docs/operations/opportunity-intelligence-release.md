# Opportunity intelligence release and acceptance record

**As of 2026-10-21.** Implementation candidate: [`69c19f8`](https://github.com/nrsandoval1231-oss/gl3/commit/69c19f85bd67e35028e0c9def43d4e689e068406). This record describes local implementation and retained-data evidence; it does not grant merge, production mutation, paid activation, or deployment authority. F3C repair/integration and controller final gates remain pending.

## Implemented behavior

The authenticated opportunity detail and bounded 1–20-need aggregate expose source-backed commercial intelligence in the existing Pursuit Workspace. Reads use current accepted evidence/facts and do not acquire sources, invoke providers, or enqueue jobs. Snapshot versions follow aggregate fingerprints; identical reads do not churn and omitted optional projections do not erase saved intelligence. Schedule-only operator fact metadata does not perturb the legacy research fingerprint or four-key semantic-reference shape.

The workspace supports project-scoped contact corrections/retractions with reason, cited or operator-reported provenance, current/history readback, and stale-version 409 feedback. Operator-reported contacts have no call/email action. The row-based schedule editor supports attributed demand phases and supply entries through draft, accept, correction, retraction, and history. The card separates dated schedule scenarios from the current qualified gap; supply summaries retain explicit source kind, ready date, basis, suitability, source reference, and reporter attribution. Only explicit utility-grid supply is presented as a reported energization date. Source-native RRC/Austin/QTS/TADG names and raw source identifiers remain cited, with the QTS narrative address where supported.

Company/person IDs stay project scoped by default. Automatic cross-project linking accepts only a valid entity-bound LEI or US EIN in current cited evidence. Attributed review can set/correct an identity link with a reason and current project evidence; prior links are retained as history. Names and contact strings do not merge parties. Identity does not imply purchasing authority.

## Migrations and operational boundary

The integrated application requires migrations `0035_reconciled_identity` and `0036_buying_chain_corrections`, in that order. `0035` adds identity and evidence-bound link tables; `0036` adds append-only project-scoped contact correction history. Any future separately authorized rollout must validate a restored isolated database, apply migrations through head (`uv run alembic upgrade head` from `backend`), verify the revision, then deploy the exact accepted app. New code must not run against a schema earlier than `0036`.

Code defaults are `OPPORTUNITY_ENRICHMENT_ENABLED=false` for the **new automatic expanded planner**, `AUTONOMOUS_RESEARCH_ENABLED=true`, `BUYING_CHAIN_PUBLIC_RESEARCH_ENABLED=false`, and provider/model features disabled. Disabling expanded planning does not disable the UI or independent existing research controls. Runtime values must be checked in their own authorized environment; repository defaults are not proof of deployed flags. No live provider acceptance or inference-cost measurement is claimed.

Rollback may restore a compatible prior application while retaining additive migrations and correction history. Do not downgrade/delete these tables, clear jobs, discard receipts, or remove ledger reservations/history as a rollback shortcut. No deployment, production mutation, provider call, merge, or push was performed by this implementation slice.

## Current retained-data evidence and open gates

The isolated retained copy contains **1,620 projects, 1,620 power needs, and 18,016 evidence rows**. The independent manifest at [`pr102-retained-manifest.json`](pr102-retained-manifest.json) contains **14 source-reviewed cases and 79 labeled fields**. The controller's read-only local report (`.artifacts/pr102/retained-v5-f5-report.json`, ignored task evidence) for implementation candidate `69c19f8` reports **79/79 exact field agreements and zero populated fields where the independent label expected null**. The curated manifest is exact-equal to the independent original `expected_fields`. This is a bounded field comparison, not a ten-category or release pass; it does not substitute for independent review of source passages, contradictions, identity, or commercial meaning.

The offline ten-category runner remains **BLOCKED** only because three required categories are absent: site-specific utility constraint, conflicting power dates, and legitimate bridge-power potential. Do not relabel cases or infer missing positives. Persisted retained-corpus latency/restart proof and production latency are pending. Live Jev/OpenAI acceptance and actual inference cost are pending/blocked until their separate credentials, source permissions, budget, and owner-authorization gates are satisfied.

F3 independent review also found correction semantics/action defects involving cumulative sparse patches, subject changes, and stale/uncited methods. A separate bounded repair is in progress; its integration and validation remain pending. Controller-owned final exact-candidate tests, schema/migration/dependency checks, and independent review have not completed. The local F5 focused evidence is recorded in the ignored task receipt `.agent/artifacts/PR102-FINISH/F5-COMPLETION.json`; it does not certify readiness.

## Historical evidence

The original PR intake candidate and its then-current limitations are preserved at [Git candidate `5ef5f3f`](https://github.com/nrsandoval1231-oss/gl3/commit/5ef5f3f29e94fffb071351b61e186d236d40068c). Earlier full-suite results, empty-database observations, and pre-F2C field counts describe that historical checkpoint; they are not current corpus or release status.
