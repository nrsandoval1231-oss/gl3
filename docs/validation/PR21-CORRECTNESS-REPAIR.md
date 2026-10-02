# PR21 correctness repair

This repair closes five review findings and two adjacent demonstrated errors. Retained-news processing now emits a material `power_need` event on supported creation or change, bound to the immutable Evidence version used in that ingestion. A supported same-ID Taylor withdrawal enters the material diff with its own Evidence. Lifecycle readers share a version-bound support predicate; an explicit `withdrawal_supported` assessment remains valid even when interpretation status is rejected, while a failed refresh continues to use the last accepted version. Shadow judging pages through skipped candidates until its attempt budget or deadline, rechecks reservations under the daily advisory lock, and treats nullable identity keys as non-matching unless an exact match is proven. Project-state API output and generated contracts include `unresolved`.

Research recommendations now require supported nested timing evidence and a buyer-role record with a retained public contact. Publisher RSS remains context-only.

Regression mapping:

- `test_supported_news_need_change_is_attributed_once_and_unrelated_evidence_stays_quiet`: admitted official-source creation plus existing-need transitions across immutable evidence versions (Prospect 42 MW / constraint → Prospect 58 MW / constraint → Signal / unknown); checks prior and current snapshots, version attribution, replay, and later unrelated evidence.
- `test_same_id_supported_withdrawal_updates_stored_state_and_replays`: checks exact withdrawn phase, supported lifecycle provenance by withdrawal Evidence ID, replay, and quiet later unrelated Evidence.
- `test_rejected_interpretation_with_supported_withdrawal_remains_current` and failed-refresh regression: cover the shared predicate's special withdrawal and accepted-version fallback.
- `test_shadow_rotates_through_more_than_two_hundred_candidates`, `test_shadow_wrap_scans_past_consumed_prefix_to_find_unseen_candidate`, `test_shadow_missing_identity_key_does_not_turn_exact_match_check_unknown_to_exclusion`, and `test_concurrent_shadow_workers_reserve_identical_input_once`: cover >200 candidate progress, consumed-prefix wrap, nullable identity, and serialized duplicate reservation.
- `test_recommendation_requires_nested_timing_and_a_public_buyer_contact`: covers both recommendation corrections.
- `test_actual_prior_new_transitions_revert_and_authenticated_reads`: asserts the authenticated JSON `unresolved` equals a nonempty projection value.

OpenAPI was exported with `uv run --directory backend --extra dev python ../scripts/export_openapi.py`; frontend contracts were regenerated with `npm run generate:api` from `web`.

Focused validation command and raw output: `.artifacts/pr21-repair/focused.log`. Controller-owned final evidence is linked at `.agent/artifacts/PR21-REPAIR/VALIDATION.json`, `BROWSER.json`, `PRESERVATION.json`, and `REVIEW.json`; builder handoff claims are in `.agent/artifacts/PR21-REPAIR/COMPLETION.json`.

Lock ordering for ingestion and shadow reservation contention is covered by the R1 two-session regressions below. Full repository gates and exact-candidate independent review remain controller-owned.

## R1 concurrency repair

The negative ingestion path now discovers linked need and project IDs without row locks, locks all affected/candidate project rows and per-project advisory locks in stable ID order, then locks impacted needs in stable ID order. A negative record with an identity-key project and a different linked-need project is covered by `test_linked_negative_correction_locks_project_before_need` and the deterministic two-session `test_linked_negative_correction_does_not_hold_need_while_waiting_for_project`. Retained-news preflights its prior and plausible reassignment targets before locking old needs; candidate discovery no longer takes broad late project row locks.

Shadow reservation now uses `pg_try_advisory_xact_lock`; lock contention returns without provider work or a PENDING row, and remaining run time is refreshed after acquiring the lock. `test_shadow_skips_reservation_when_daily_lock_is_held` holds the lock in a separate transaction and verifies prompt zero-attempt behavior. Existing identical-input and daily-limit regressions remain covered.

R1 focused command: `uv run --directory backend --extra dev pytest tests/integration/test_ingestion.py tests/integration/test_collection_only_ingestion.py tests/integration/test_taylor_ingestion.py tests/integration/test_evidence_shadow_storage.py -q` → 72 passed, 1 warning in 29.21s; raw output: `.artifacts/pr21-repair/round-r1-focused.log`. Ruff passed on changed source/tests; mypy passed on `service.py` and `evidence_shadow.py`; `git diff --check` passed. An initial concurrency-test harness draft waited for the worker while still holding the project lock itself; it was interrupted and replaced with a two-session test that releases the holder transaction before awaiting worker completion. That was a test-harness deadlock, not product-failure evidence.

The reviewer FIX receipt and previous-candidate receipts remain untouched. Controller must rerun full gates and obtain fresh independent review for this repaired candidate.
