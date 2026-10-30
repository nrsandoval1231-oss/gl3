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

## Independent review and portability repair

Astra high independently reviewed source candidate `50da643fe4c533c1bcb2140cbb9fa55c06dd77e3` against base c8d3ceb1 and returned CHANGES REQUESTED for one P2: the new raw-byte hash fixture changed to CRLF under fresh Windows checkout. Reviewer independently ran190focused tests and docs89/344/3, inspected schema/module/fixture boundaries and verified the official source and retained hashes; no additional material contract/provenance findings.

Repair: `.gitattributes` now pins only `backend/tests/fixtures/ferc-cp24-8-equipment-excerpt.txt` to `text eol=lf`. No fixture/hash/test normalization or threshold changed. `git cat-file --filters 50da643f:<fixture>` with core.autocrlf=true was independently checked by the lead to produce noCRLF and SHA256d76f9ac3c5e5621cd16101033ab35e0e7b3b7e22aec98757ed815794c88c4d57, exactly the retained manifest digest. This verifies checkout behavior rather than only authored bytes.

Scoped re-review and final exact-head CI remain pending at receipt authoring. The focused PR completion record will retain the final SHA, exact CI run/commands/counts, independent scoped verdict and readiness after observation. Initial and final source commits remain distinct. Existing CI workflow is unchanged; no historical pass proves final readiness.

## CI collection defect and deterministic repair

Initial full CI runs [40985291745](https://github.com/nrsandoval1231-oss/gl3/actions/runs/40985291745) and [40985222820](https://github.com/nrsandoval1231-oss/gl3/actions/runs/40985222820) failed during pytest-xdist collection, before backend execution: a new test parameter generated an uppercase UUID using uuid4 at import time, producing different node IDs in each worker. This is a defect introduced by this test, not the inherited saved-browse issue. Logs retain all worker mismatches. The b0c6d80e runs were cancelled after diagnosis rather than consuming CI on the same known defect.

Repair changes only that parameter to fixed uppercase UUID `AFF1A621-9B4A-469D-84FA-70F267B96410`, preserving the same noncanonical-UUID rejection case and every assertion. No test removed, skip, xdist setting or acceptance gate changed. Two independent process collect-only runs now produce exactly identical115newtestnodeIDs across all3newmodules; the builder also observed identical64claimtestIDs and64focusedPASS. Scoped independent re-review and finalCI must cover the repaired test commit.

Astra's scoped review on b0c6d80e accepted the LF fix and inspected metadata; no unresolved contract/provenance findings. That review is not a substitute for reviewing the subsequent deterministic test change or running final CI. Final immutable CI logs and raw scoped verdict will be retained in the PR completion record.
