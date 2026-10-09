# A6 selected-interval repair

This bounded repair implements the accepted selected-interval direction; the Astra `ACCEPT` applies to the proposal only, not to this candidate. It changes only `backend/src/gridlens/domain/call_facts.py` and focused existing unit/integration tests. It does not change qualification admission, arithmetic, source authority, public interfaces, saved-history policy, schemas, or service/API code.

## Change

`_finalize_lead_interval` copies the current gap mapping and synchronizes its current `start_window` and `duration` with the resolved top-level Lead interval. Where the gap already carries selected-interval provenance, it writes both half-open UTC bounds from that same resolved interval. Fact-derived promotion also preserves displaced source dates under `source_reported_*`. Call sites are after existing successful coverage and Lead gates. Source-only no-fact returns bypass the finalizer, and all edits use copied dictionaries so source claims and saved snapshots are not mutated.

The decisive compatible-narrowing regression starts with a source Lead Jan 1–Feb 1 / 31–62 days, then applies accepted Jan 10–20 / 40-day timing. The current top-level and gap dates now both say Jan 10–20 / 40 days, selected exclusive end is March 1, and the old window remains under `source_reported_*`. The source numeric gap and source gap object remain unchanged.

## Deterministic coverage

- `tests/unit/test_call_facts.py::test_compatible_timing_narrowing_closes_with_timing_version_provenance` checks source-supply narrowing with and without new suitable supply, all three current date representations, source-reported dates, unchanged numeric/source gap, and source object immutability.
- `tests/unit/test_call_facts.py::test_lead_requires_current_gap_interval_and_buyer_facts` checks the matching nested interval for Signal-to-Lead promotion from accepted User-confirmed facts.
- Existing fact-unit coverage retains the no-fact/source-only path, adequate-supply closure, explicit source correction, unresolved/stale timing conflicts, and partial/zero-gap behavior.
- `tests/integration/test_call_fact_workflow_integration.py::test_timing_correction_is_source_version_bound_and_replayed_after_source_change` now exercises a persisted source Lead narrowing through effective qualification and `PowerNeed`, current page/group/detail, `timing=KNOWN`, CSV row/scope, exact-target saved card, and immutable source/compatible/current as-of versions. It then retracts the compatible test fact before the separate disjoint-correction/reassessment sequence.
- `tests/integration/test_call_fact_workflow_integration.py::test_current_public_support_bounds_fact_qualification_and_reassessment` checks the generic Signal/Prospect-to-Lead fact path through effective qualification and current gap dates.

## Attempts and fixture classification

The initial pure-domain regression failed because the copied current gap retained Jan 1–Feb 1 / 31–62 days while the selected interval and top-level fields were Jan 10–20 / 40 days. That is the product defect addressed here.

During integration expansion, one run used a future `effective_from` (2027) against the 2026 test clock. A later run kept the compatible timing fact active while starting the independent disjoint-correction case, so two accepted timing versions correctly conflicted and the old test's expected Prospect result was invalid. The fixture now uses an active effective interval and explicitly retracts the separate compatible fact before the correction subcase. A unit exact-dictionary assertion was updated only to include the newly required current gap date fields. These are fixture/expectation corrections, not product-policy changes; their original logs are retained and hashed.

## Validation

The final focused run passed 50 unit and integration tests. Ruff passed on the changed source and test files. Mypy passed for all 80 backend source files. The exact raw logs and hashes, including failures, are listed in `RAW-MANIFEST.json`.

Repository-level full backend/browser, retained-corpus, migration, contract, and fresh independent review remain root/controller gates against the frozen exact candidate. No acceptance or overall A6 completion is claimed here.
