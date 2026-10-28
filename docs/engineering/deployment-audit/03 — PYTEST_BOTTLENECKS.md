# 03 — Pytest Bottlenecks: Profile, Root Causes, and Proposed Optimizations

Audit date: 2026-10-28
Evidence: CI step timings (21 runs, see `02 — DEPLOYMENT_TIMINGS.md`) + a full local profile run in an isolated sandbox (`pytest tests -q --durations=60`, 3,292 tests, 1,028s) + targeted micro-benchmarks.

## 1. Headline finding

**pytest is 81% of the backend CI job (median 826s of 1,026s).** The suite is not slow because of a few monster tests. It is slow because **~78% of integration test wall time is per-test database schema destruction and recreation** — the same 73-table DDL being dropped and re-created before and after nearly every integration test.

Measured decomposition:

| Component | Time | Share of pytest |
|---|---|---|
| Integration tests wall time (842 tests) | ~985s | ~96% |
| — of which per-test `drop_all + create_all` overhead (604 tests × ~0.92s setup+teardown) | **~556s** | **~54% (measured micro-benchmark × count)** |
| — of which actual test execution (`call`) | ~430s | ~42% |
| Unit tests wall time (2,048 tests) | ~43s | ~4% |

Micro-benchmark (local, median of 5, warm): `Base.metadata.drop_all(engine) + Base.metadata.create_all(engine)` on the 73-table schema = **0.46s per invocation**. Integration fixtures do this in setup *and* teardown (e.g. `tests/integration/test_acquisition_runtime_bounds.py::acquisition_runtime_db`), and the fixture is function-scoped (default), so it repeats per test, serially, against one shared `gridlens_test` database.

## 2. The 25 slowest individual tests (local profile, `call` phase)

| # | Duration | Test |
|---|---|---|
| 1 | 51.14s | `integration/test_evidence_shadow_storage.py::test_shadow_rotates_through_more_than_two_hundred_candidates` |
| 2 | 26.61s | `integration/test_saved_browse.py::test_structured_ingestion_bulk_commit_keeps_authenticated_maps_current` |
| 3 | 7.66s | `integration/test_buying_chain.py::test_unverified_company_page_links_are_never_followed` |
| 4 | 7.55s | `integration/test_power_need_briefs.py::test_summary_batches_preserve_cross_boundary_case_siblings_and_compact_history[False]` |
| 5 | 7.28s | `integration/test_autonomous_questions_integration.py::test_real_projection_groups_outside_shortlist_before_research_planning` |
| 6 | 6.41s | `integration/test_power_need_briefs.py::test_summary_batches_preserve_cross_boundary_case_siblings_and_compact_history[True]` |
| 7 | 6.11s | `integration/test_evidence_shadow_storage.py::test_shadow_wrap_scans_past_consumed_prefix_to_find_unseen_candidate` |
| 8 | 5.55s | `unit/test_contact_assertions.py::test_contact_privacy_key_budget_is_per_project_and_preserves_suppression` |
| 9 | 4.66s | `unit/test_workbook_import.py::test_large_contact_csv_stays_bounded_and_keeps_all_rows` |
| 10 | 4.40s | `integration/test_external_imports.py::test_25k_rows_are_staged_in_bounded_chunks_and_return_bounded_summary` |
| 11 | 3.62s | `integration/test_research_transitions.py::test_corroborating_missing_lead_fields_are_not_conflicting_but_different_load_is[1-Signal-True]` |
| 12 | 3.59s | `integration/test_research_transitions.py::test_corroborating_missing_lead_fields_are_not_conflicting_but_different_load_is[2-Signal-False]` |
| 13 | 3.11s | `integration/test_pursuits.py::test_ingestion_dispatches_full_retained_research_batch_without_saved_map_gap` |
| 14 | 2.98s | `integration/test_saved_browse.py::test_worker_budget_exhaustion_retains_changes_and_offline_recovers` |
| 15 | 2.47s | `integration/test_pursuit_evidence.py::test_existing_url_correction_is_not_skipped_when_another_url_has_same_content` |
| 16 | 2.46s | `integration/test_saved_browse.py::test_worker_publishes_bulk_segment_but_operator_request_stays_small` |
| 17 | 2.14s | `integration/test_research_transitions.py::test_retained_relationships_precede_sibling_question_fingerprints` |
| 18 | 2.09s | `integration/test_pursuit_evidence.py::test_known_reviewed_public_url_identity_corrections_retract_old_contacts[structured]` |
| 19 | 2.06s | `integration/test_ingestion.py::test_tdlr_exact_refetch_receipt_refreshes_only_fetched_retained_contact_source` |
| 20 | 1.93s | `integration/test_saved_browse.py::test_long_history_can_publish_compact_browse_but_detail_stays_bounded` |
| 21 | 1.84s | `integration/test_research_transitions.py::test_retained_native_rrc_inspection_preserves_truth_and_replay` |
| 22 | 1.80s | `unit/test_jeti_runtime_proxy.py::test_default_jeti_transport_reaches_configured_runtime_proxy` |
| 23 | 1.75s | `integration/test_saved_browse.py::test_incremental_customer_projection_reassignment_matches_full_rebuild` |
| 24 | 1.72s | `integration/test_saved_browse.py::test_receipt_rollback_and_failed_preparation_leave_current_state` |
| 25 | 1.70s | `integration/test_intelligence_worker_integration.py` (max `setup` 1.70s + multiple 1.5–1.7s `call`s) |

Note the shape: two genuine heavyweights (51s, 27s), then a cliff to <8s. The top 25 sum to ~155s — under 16% of the suite. **Optimizing individual tests cannot fix this suite; fixture strategy is the fix.**

## 3. Slow test modules (local profile, by total `call` time)

1. `test_evidence_shadow_storage.py` — 63s (bulk candidate rotation; the 51s test dominates)
2. `test_saved_browse.py` — ~50s over 117 tests (plus ~110s of per-test fixture overhead)
3. `test_power_need_briefs.py` — ~20s
4. `test_research_transitions.py` — ~19s
5. `test_pursuit_evidence.py` — ~15s
6. `test_buying_chain.py`, `test_autonomous_questions_integration.py`, `test_external_imports.py`, `test_pursuits.py` — 8–14s each

All remaining modules are individually small; their cost is volume × per-test fixture overhead.

## 4. Fixture and isolation costs (measured)

- **44 of 78 integration modules** define a fixture that runs `Base.metadata.drop_all/create_all`; **604 of 842 integration tests** execute in those modules.
- Estimated fixture cost: 604 × 0.46s × 2 (setup+teardown) ≈ **556s** — 54% of the CI median pytest time (826s). Consistent with the observed per-module rate: `test_saved_browse.py` averaged 1.10s/test wall vs ~0.4s median `call`.
- Each fixture also builds a fresh `create_engine` + sessionmaker and monkeypatches module globals (`worker.SessionLocal`, `WORKER_ID`), so application state is re-initialized per test as well.
- **Repeated PostgreSQL setup/teardown is the single largest line item in the entire deployment pipeline.**

## 5. External requests, sleeps, polling

- No external HTTP is possible in tests by design: `tests/conftest.py` monkeypatches httpx transports and socket connect/DNS to fail on any non-loopback destination (verified in profile: zero external calls).
- Only 13 `time.sleep` sites across the whole suite, each 0.01–3s and mostly inside concurrency-bounded runtime tests. Total sleep impact is low (est. <20s suite-wide). Not a primary target.

## 6. Parallelization experiment (measured, safe, local)

| Experiment | Result |
|---|---|
| `pytest tests/unit -n 4` | 41.8s vs 43.5s serial — **no meaningful gain**; 2 flaky failures appear under xdist (e.g. `test_auth_persistence` login-budget test) — unit tests already fast, parallelism adds flake |
| `pytest tests/integration/test_saved_browse.py -n 4` | **46 failed / 71 passed** (vs 117 passed serial) in 96.9s — direct proof that the single shared `gridlens_test` database is a hard serialization point: concurrent schema drops race |

**Conclusion from experiment:** pytest-xdist is worth ~3–4× on integration time, but only after per-worker isolation exists. The required pattern is standard and mechanical: derive a per-worker DSN from `TEST_DATABASE_URL` (e.g. database suffix `_gw{worker}`), create it in a session-scoped conftest hook, and keep per-test schema reset *within* each worker's database. Given 4 CI vCPUs this is a realistic post-fix target, not a speculation about bigger runners.

## 7. Classification of the suite

| Class | Count | Content | Proposal |
|---|---|---|---|
| Fast unit tests | 2,048 | pure logic, some with sqlite-ish/no DB; 43.5s total | **Run on every PR** (gate) |
| Integration tests | 842 | PostgreSQL, API, ingestion, worker, service interactions; ~985s | Run on every PR **after fixture optimization**; keep as mandatory release gate (they are the substance of the platform's correctness) |
| Browser/E2E tests | 18 spec files (Playwright, `regression` project) | critical user journeys + real auth; ~69s in CI | Keep mandatory, but move out of the backend job into a parallel job |
| Extended regression | `publication-diagnostic.yml` style repeats; live-acceptance and commercial-real Playwright projects | expensive, needs retained data/worker | Scheduled (nightly) + pre-release manual trigger; already partially practiced |

Nothing should be disabled or weakened. The suite's green CI record (18/22 recent runs fully green; failures were genuine code failures, not infra) shows the gates are meaningful.

## 8. Proposed optimizations (evidence-backed, in priority order)

1. **Replace per-test `drop_all/create_all` with per-test data reset against a persistent schema.** Options, cheapest first: (a) `TRUNCATE` all tables in one statement (~10–30ms for empty/small tables) inside a transaction rolled back per test; (b) PostgreSQL template database per worker cloned via `CREATE DATABASE ... TEMPLATE` once per worker, with per-test TRUNCATE; (c) module-scoped schema where a module's tests share one schema and reset data per test. Expected: removes ~550s (measured overhead) → pytest ≈ 250–330s. Risk: low, provided truncation order respects FKs (or `TRUNCATE ... CASCADE`) and fixtures that deliberately mutate schema (DDL tests, migration tests) keep their own path — audit found migration/DDL-specific tests already isolated in unit tests.
2. **pytest-xdist with per-worker databases** (4 workers): after #1, integration ≈ 250–330s → est. **80–140s**. Prerequisite: per-worker DSN in conftest (the experiment above proves the current single-DB design races). Risk: medium-low; deterministic isolation must be verified by the full suite.
3. **Move browser regressions + Node/Chromium out of the backend job** into a `browser` job running in parallel with pytest: measured ~110–140s off the backend critical path (Chromium install 27–35s + browser run ~69s + npm ci/setup-node). Also stops the backend job from paying for a frontend toolchain.
4. **Trim duplicated setup in `ci.yml`:** remove the second `alembic upgrade head` (~1s, trivial), and skip web `npm ci` in the backend job once browser tests move.
5. **Split fast gate vs full run during PR iteration** (optional, merge-queue style): unit+lint+smoke integration subset on PR push; full suite on merge-ready. Only recommended after #1/#2 make the full suite cheap enough that splitting is unnecessary — prefer the simpler fix first.

Estimated combined result: pytest step 826s → **~120–200s (estimate; components #1 and #2 measured independently, interaction conservative)**, backend job → ~5–7 min, with no test disabled.
