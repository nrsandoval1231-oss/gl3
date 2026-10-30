# O&G equipment candidate verification — October 29, 2026

Base `c8d3ceb1e33b5e865c8e85cc8e27004af177932a`, branch `feat/og-equipment-claims-20261029`, stacked on open PR150. CURRENT scope: two pure strict frozen candidate-validation modules, tests/fixtures, schema map and checkpoints. No runtime wiring, persistence, migration, calculation, qualification, API, UI, provider configuration, merge or deployment. Full CI and independent review pending at this receipt checkpoint.

## Observed local verification

Commands run from backend in the isolated worktree unless noted. Unit settings use process-only loopback-port1 placeholder DSNs ending `_test`, inert app hash/session values; no retained environment copied, database connection or paid calls.

- `uv sync --locked --extra dev`: PASS, locked Python3.11 environment.
- Baseline `uv run pytest tests/unit/test_generator_schedule.py tests/unit/test_call_facts.py -q`: 47 PASS. Initial invocation without required settings produced setup errors; corrected with ephemeral process environment, no settings/test changes.
- Integrated `uv run pytest tests/unit/test_equipment_evidence.py tests/unit/test_equipment_claims.py tests/unit/test_og_equipment_cohort.py tests/unit/test_generator_schedule.py tests/unit/test_call_facts.py tests/unit/test_rrc_completion.py tests/unit/test_tceq_nsr_pending.py -q`: **190 PASS**.
- `uv run ruff check src tests`: PASS. `uv run ruff format --check src tests`: PASS,406files.
- `uv run mypy src`: PASS,185sourcefiles; unchanged existing untyped-body notes.
- Root `uv run --project backend python scripts/check_docs.py`: PASS,89documents/344localtargets/3anchors.
- Root `uv run --with-requirements tools/brand/requirements.txt --project backend python tools/brand/validate.py`: PASS,216assets and8semanticAApairs.
- `git diff --check`: PASS for active changes. Archived checkpoint bytes retained unchanged.

## Test-first and integration evidence

Three independent Luna low builders used disjoint file ownership. Evidence and claim tests initially failed to import their absent modules (RED), then passed after implementation. New JSON roundtrip tests exposed a dataclass/Pydantic mismatch; integrated interface corrected to frozen strict Pydantic. Additional RED tests rejected whitespace/Unicode/underscore/exponent/nonfinite rating lexemes and oversize fields; raw decimal text retained without unit conversion. A constructed nested `EquipmentRating` containing NaN initially bypassed validation; revalidation and regression tests fixed it. Malformed supplied contexts cannot bypass binding. Four initial evidence mypy narrowing errors were corrected without ignores. The lead reran integrated tests and full source lint/types rather than relying solely on builder summaries.

## Source-backed versus synthetic evidence

Retained RRC completion samples support identity and historic completion/recompletion dates, not equipment facts. No equipment or load claim is assigned to those well IDs. Negative gas/unknown/missing/standby/conflict scenarios are explicitly synthetic and use harness-only UUIDs.

The lead separately retrieved the [official historical Federal Register notice](https://www.govinfo.gov/content/pkg/FR-2024-06-12/html/2024-12869.htm) read-only, at `2026-10-30T01:16:10.278252+00:00`. The notice provides a historically proposed electric-compressor rating; shaft/electrical-input basis remains unknown, and no conversion is performed. Companion tracked provenance records original HTML hash `d4e94db733664b6045b046296bb96666a25885d661bfce5482d8f787d019a74f` and retained excerpt hash `d76f9ac3c5e5621cd16101033ab35e0e7b3b7e22aec98757ed815794c88c4d57`. The original download remains ignored; tracked fixture retains only the quoted sentence plus provenance. Fixture IDs are not production IDs. This is source-backed fixture traceability, not installed-equipment, present-demand, supply-gap, buyer or commercial proof.

## Remaining acceptance

Required full backend/migration/dependency/browser/web CI and independent Astra review must pass on the final candidate before readiness. No check/threshold/exclusion is changed. Preserve both failed and passing CI attempts. The inherited intermittent saved-browse publication failure seen in PR150 remains unresolved, not repaired by unused candidate modules.

Structural validation binds to a caller-supplied snapshot and exact quote; it cannot authenticate database rows, verify source meaning, establish independent entity identity, detect whether the source is truthful/current, or confer qualification. No production/live-source pipeline acceptance is claimed. Persistence/shadow ingestion, deterministic demand models and independent semantic verification remain later slices. Rollback is reverting unused modules/tests/docs with no data/schema rollback. Tokens and phase timing breakdown UNKNOWN; no speed claims. Model roles: three supported `gpt-6-luna` low builders, separate `gpt-6-astra` high review pending; do not infer lead runtime identity from a role label.
