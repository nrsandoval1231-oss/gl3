# A6 backend builder handoff

**Status:** implementation complete, pending root validation and independent review. This handoff does not claim A6 acceptance or Finish Contract completion.

**Candidate:** `repair/gl3-facts-workflow-20261008`, dispatched from `df4e8216bfa07ec8194aa00053d5883f6065d5db` / tree `e10149ddaad95d4dc885f68d42eeaf612bc0b88b`. The exact frozen commit and tree are recorded in `COMPLETION.json` after the source freeze. The root-owned dispatch packet and its A5B snapshot-binding amendment are preserved byte-for-byte under `.agent/artifacts/GL3-AUDIT-A6-DISPATCH/`.

The backend adds immutable, exact-need call-fact versions and decision receipts, separate seven-state workflow events, source-reassessment through the existing qualification path, a current fact digest in browse cohort binding, and bounded bulk fact/status loading. Current accepted fact input is preflighted by exact-need count and byte aggregates before ORM hydration; overbound rows return an explicit 413 and are never silently truncated.

Commercial triage cards keep their public `facts` and `sources` limited to Reported Evidence. A new additive `operator_fact_refs` field stores only exact `need_id`, immutable fact version ID, content hash, and `User-confirmed` authority. References are deterministically ordered, deduplicated, kept attached to grouped siblings, and included in the current card `input_hash`. New saved history versions carry `operator_fact_provenance=recorded`; older versions without the marker read as `legacy_unknown`. Known-empty cards omit the references field from the saved card, keep the existing no-fact `input_hash` and saved-card field shape, and use the version provenance marker to distinguish known-empty from legacy unknown. Existing snapshots are not rewritten.

`backend/migrations/versions/0017_call_fact_versions.py` creates the three append-only version/event tables. The authored code also updates the OpenAPI schema and generated TypeScript contract for the additive fact-reference and history-provenance fields.

## Changed implementation surfaces

- `backend/src/gridlens/domain/call_facts.py`
- `backend/src/gridlens/domain/workflow_status.py`
- `backend/src/gridlens/domain/pursuits.py`
- `backend/src/gridlens/domain/commercial_triage.py`
- `backend/src/gridlens/intelligence/commercial_evaluation.py`
- `backend/src/gridlens/intelligence/opportunity_browse.py`
- `backend/src/gridlens/ingestion/service.py`
- `backend/src/gridlens/api/app.py`
- `backend/src/gridlens/persistence/models.py`
- `backend/migrations/versions/0017_call_fact_versions.py`
- `backend/tests/unit/test_call_facts.py`
- `backend/tests/unit/test_commercial_triage.py`
- `backend/tests/integration/test_call_fact_workflow_integration.py`
- `backend/tests/integration/test_power_need_briefs.py`
- `web/src/api/openapi.json`
- `web/src/api/generated.ts`

The root-owned `.agent/CURRENT_STATE.md`, `.agent/WORK_GRAPH.md`, dispatch packets, and preflight corpus receipts are included unchanged as required by the dispatch. The read-only corpus copy was migrated from 0016 to 0017; root compared all original-column fingerprints (23 data tables identical, only the expected `alembic_version` difference). The original corpus and backup were not mutated. No provider calls, live application writes, push, merge, or deployment occurred.

## Builder validation

- Safe-wrapper backend focused suite: 120 passed. It covers fact/status APIs, source reassessment, A→B→A fact versions, persisted saved-card as-of behavior, legacy provenance, grouped sibling references, UNKNOWN workflow status, and count/byte rejection before fact ORM hydration. Three warnings remain: Starlette/httpx deprecation and two synthetic-harness repeatable-read warnings after the transaction has already begun.
- The fail-closed fact preload regression is `test_current_fact_preflight_fails_closed_before_fact_orm_hydration` in `backend/tests/integration/test_call_fact_workflow_integration.py`. It proves both a 51-version exact-need set and a single provenance field above 512 KiB return 413 before any `CallFactVersion` ORM entity is hydrated; it confirms the stored rows remain unchanged. The loader's scalar preflight applies to each exact need before loading only current accepted versions, and no row/value/reference is truncated. The page/card response guards remain 4 MB/page and 2 MB/card; emitted fact references contain bounded identity/hash fields only, not fact values or notes.
- Saved history read-back preserves the distinction between `legacy_unknown` (no provenance was recorded) and a newly written, known-empty card. Existing snapshot JSON is not backfilled from current facts. Current accepted-fact references are stored only on new card snapshots and are immutable across later correction/retraction.
- Ruff passed on the owned source, migration, and focused tests.
- `mypy src` passed for 80 source files. `mypy src tests` was attempted earlier and failed only on the unchanged `tests/integration/test_source_scheduling.py:95` fixture type mismatch; retained in the raw log manifest.
- Alembic fresh upgrade, repeat upgrade, downgrade to 0016, re-upgrade, and `alembic check` passed on the dedicated migration database before the final additive card-only work. The 0017 migration was not changed afterward.
- OpenAPI export and generated-client repeat match passed. Web typecheck and build passed.
- The required synthetic current-fact/status 50-input handler proof returned 50 public records/130 cohort groups at 38 SQL, and 50 commercial cards/128–129 groups at 54 SQL. Both are below 200 SQL. This synthetic fixture reuses an open test transaction and does not prove fresh-session snapshot isolation.
- Read-only retained-copy public and commercial 50-item output hashes exactly match the accepted A5 oracle at fixed date 2026-10-07. Final measurements after the fact-bound query: public 125 SQL; commercial 135 SQL; both below 200. See raw logs and output hashes in the manifest.

Root still owns full backend/fresh final database gates, exact candidate corpus preservation checks, final performance review, and independent review. The synthetic facts are test mechanics and are not evidence of an actual customer-confirmed Lead.

## Evidence and limits

Raw command output remains in ignored `.artifacts/`; `RAW-LOG-MANIFEST.json` records exact SHA-256 and byte lengths for 101 A6 raw log files, all verified present and matching the manifest at freeze preparation. Retained corpus dumps/payloads are excluded. A few corrected invocation and fixture failures remain intentionally preserved; see `ATTEMPT-HISTORY.md`. Tool-only failures without saved raw files are marked unavailable rather than reconstructed as raw evidence.

Start was recorded in the dispatch binding at `2026-10-08T19:41:05.306462Z`; finish time, source commit/tree, and measured wall clock are in `COMPLETION.json`. Planning/build/validation phase durations, exact runtime model/config identity, and token usage were not measured and remain `UNKNOWN`.
