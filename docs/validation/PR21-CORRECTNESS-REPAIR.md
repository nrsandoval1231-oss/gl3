# PR21 correctness repair

This repair records the retained-news, lifecycle, shadow traversal, lock-order, project-state, and buying-chain corrections made across R1–R5. It preserves immutable Evidence and judge-run history while adding bounded traversal state, ordered project locking, current admitted field provenance, and per-document buying-chain projection. Project-state API output and generated contracts include `unresolved`.

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

## R2 correctness repair

The attempt-derived shadow cursor could not record traversal when every visited
row already had an immutable attempt for its current input. A singleton
`evidence_judge_scan_checkpoints` table now records the last classified skip or
persisted attempt. It is the only new table: the migration does not update
Evidence or `evidence_judge_runs`. A dedicated checked-out PostgreSQL
connection holds a scan advisory lock across work-session commits, so concurrent
scans cannot overwrite the checkpoint with a stale position. A deadline before
classification leaves that boundary row unadvanced for the next call.

`test_shadow_checkpoint_reaches_changed_context_after_deadline_limited_skips`
preseeds old input keys through a cursor later than a changed-context row,
uses a deterministic advancing clock to make successive calls consume only
skips, and proves the changed row is eventually attempted. This fails on the
reviewed attempt-only cursor because each invocation restarts at the same
consumed prefix.

Structured permit matching now reads candidate projects before taking project
locks, then invokes the existing row-plus-advisory `lock_project` protocol in
UUID order. The actual permit path regression
`test_authoritative_permit_identity_requires_one_exact_site_candidate` records
the emitted SQL and rejects the reviewed broad `FROM projects FOR UPDATE` form;
it requires per-ID project locks.

R2 focused validation at 2026-10-02T18:55:00Z:

- `uv --directory backend run --extra dev pytest tests/integration/test_ingestion.py tests/integration/test_evidence_shadow_storage.py -q` — 37 passed, one existing deprecation warning.
- `uv --directory backend run --extra dev pytest tests/integration/test_ingestion.py tests/integration/test_collection_only_ingestion.py -q` — 51 passed, one existing deprecation warning.
- Ruff and mypy on affected sources/tests, plus `git diff --check` — passed.

The controller still owns migration-chain, full-suite, preservation, browser,
and exact-candidate independent review. No commit, push, merge, deployment, or
provider call was made.

R2 follow-up proof corrected the initial handoff gaps. Setup failures now issue
`pg_advisory_unlock` before returning the dedicated scan connection to its
pool. `test_shadow_setup_error_releases_default_scan_lease` forces checkpoint
creation to fail, acquires the same lease from a fresh connection, and then
proves a normal next call can attempt work. The default-scan concurrency test
holds a provider call open after its attempt commit and proves a second default
scan returns zero work while the lease is held.

The changed-context regression now retains an old immutable target attempt,
changes only its current project context, records multiple zero-attempt scans
over the consumed prefix, and requires exactly one new valid target attempt.
Explicit IDs no longer apply a 20-row SQL limit before skip evaluation;
`test_explicit_shadow_ids_scan_past_twenty_consumed_inputs` proves a second
call reaches the 21st ID after the first 20 immutable attempts.

Retained-news preflight now takes the same all-project lock scope that it had
before the R1 narrowing, but through sorted `lock_project` calls. This covers
any candidate later referenced by a match-decision foreign key. The two-session
structured ingestion regression inserts the higher UUID first, holds the lower
UUID with the retained-news-compatible lock helper, confirms the worker block
with `pg_blocking_pids`, and acquires the higher row with `NOWAIT` before
release. The reviewed broad physical scan would hold the higher row first;
the repaired UUID order passes.

Final R2 focused command:

- `uv --directory backend run --extra dev pytest tests/integration/test_evidence_shadow_storage.py tests/integration/test_ingestion.py tests/integration/test_collection_only_ingestion.py -q` — 65 passed, one existing deprecation warning, 29.04 seconds.

Final lease follow-up: checkpoint initialization commits before any traversal so a
zero-work caller cannot retain the singleton insert after the dedicated lease
is released. `test_zero_work_default_scan_commits_checkpoint_before_releasing_lease`
keeps that first caller Session open while a second default scan completes with
zero provider calls and zero attempts. Acquisition now releases a newly opened
connection if the advisory-lock query itself raises;
`test_shadow_acquisition_error_closes_new_connection` verifies pool checkout
count returns to baseline. The existing setup-error and default contention
tests remain in the focused suite.

Controller before-proof executes the exact `bfa6186` ingestion and shadow source
against the current fixture schema (so the checkpoint model can import), in an
isolated source copy. Both new Codex regressions fail: changed-context judging
stays at zero calls, and structured ingestion never reaches the required per-ID
lower-project lock marker. This is execution evidence, not a full historical
tree test or an observed PostgreSQL deadlock. The repaired two-session test
separately proves that the higher project remains lockable while ingestion waits
on the lower project. See `R2-BEFORE.json` for the exact scope and assertion output.

## R3 provenance and multi-document repair

`project_state` now projects a need field only from an accepted assessment for
the current project and activity that passes the existing admission predicate.
Tier, MW, supply, timing, and duration each retain their own supporting
Evidence; the public evidence list is deduplicated. A failed or pending refresh
still uses the prior accepted assessment through the existing version predicate.

`buying_chain_view` now selects the newest run's persisted claim IDs. Citation
processing still marks withdrawn or stale support as `UNKNOWN`, so a rejected
document does not suppress another current claim in the same run, and historical
claims omitted by the newest run are not resurrected. The latest run also
supplies the status and unresolved metadata.

`R3-BEFORE.json` records exact `1b186a` source-overlay failures: reassigned,
supplemental evidence incorrectly projected `SUPPORTED`, and a rejected
document A made a multi-document run report `not_researched`. The repaired
multi-document regression retains document B's contractor, emits no false
contractor removal when recording document A, retains material state, and
asserts complete latest-run metadata. Existing A to B to A and freshness
regressions continue to cover no historical resurrection and quiet
freshness-only updates.

R3 focused validation at `2026-10-02T20:03:58.9325399Z`:

- `uv --directory backend run --extra dev pytest tests/integration/test_project_state_changes.py tests/integration/test_buying_chain.py tests/integration/test_collection_only_ingestion.py -q` — 58 passed, one existing deprecation warning, 25.34 seconds.
- Ruff on the changed R3 source/tests and mypy on `project_state.py` and `buying_chain.py` — passed.
- `git diff --check` — passed (line-ending warnings only).

Full repository gates, browser/preservation checks, and fresh independent review remain controller-owned. No commit, push, merge, deployment, or provider call was made.

## R3 Astra proof follow-up

Test-only follow-up separates each eligibility predicate around a realistic
official permit source: wrong project identity, wrong activity, and a
non-admitting news source each leave an otherwise valid Evidence as the sole
support. A two-row eligible fixture then verifies exact Evidence IDs for tier,
MW, timing, duration, and Prospect supply, asserts exactly two deduplicated
top-level evidence rows, and returns UNKNOWN after stored MW/timing/duration no
longer match either accepted row. It preserves the prior accepted assessment
through both failed and pending refreshes with a changed Observation hash.
`R3-PROOF.json` records a temporary blanket-support mutant failure; the
production source was restored before final validation.

Focused follow-up: `test_project_state_changes.py` — 16 passed, one existing
deprecation warning, 10.03 seconds; Ruff and mypy passed. Final controller gates
and audit remain controller-owned.

## R4 CI synchronization repair

The structured-ingestion lock-order regression no longer treats SQLAlchemy's
`before_cursor_execute` callback as evidence that PostgreSQL is already
blocking the worker. After that pre-send marker, it polls `pg_blocking_pids`
with a two-second deadline and short event waits, then retains the original
higher-project `NOWAIT` assertion. Four consecutive targeted runs passed;
the full ingestion module passed 28 tests in 14.28 seconds. No production code
changed.

## R4 retained project-binding repair

Current lifecycle and buying-chain projections now require the accepted
assessment's explicit current `project_identity_key`. Retained citations are
also checked through the source-admission policy: official admitted evidence is
eligible, while context evidence is eligible only when ingestion recorded the
explicit `supplemental` project match. Missing bindings and unmatched/context
records cannot become current support; history remains inspectable. Focused
buying-chain, project-state, and collection-only ingestion tests passed on the
dedicated builder database.

Retained reassessment discovers affected projects through need links and retained
lifecycle/buying-chain history before changing the Interpretation. It seeds their
material state under the existing ordered locks, rebuilds lifecycle support,
and evaluates material changes in the same transaction. This includes former
projects with another active need source and historical citations without a
remaining need link. Citation freshness and historical stale status use the same
current-project predicate. History and immutable Evidence are retained.

`test_official_same_hash_reassignment_clears_former_project_support_and_keeps_history`
uses the real deterministic assessor and ingestion function: an older accepted
interpretation points at A, the current evaluator binds the same immutable
Evidence to B, and both projects' projections and causal material transitions
are checked. Replay and later unrelated Evidence remain quiet. `R4-BEFORE.json`
records the corresponding failures on the exact reviewed `89d4bb8` source.
`R4-PROVENANCE-BASELINE.json` records a read-only retained-clone check: all 938
current-hash lifecycle events have explicit matching project bindings, and all
38 current retained buying-chain citations remain supported by the repaired rule.

The final frozen-candidate results are recorded in `VALIDATION.json`,
`BROWSER.json`, `PRESERVATION.json`, and `REVIEW.json` under
`.agent/artifacts/PR21-REPAIR/`. Earlier round results above are historical
checkpoints, not substitutes for that final acceptance.

The independent R4 audit also identified a historical role-conflict path that
could reuse a retained citation after reassignment. The regression
`test_reassigned_retained_role_cannot_conflict_with_current_independent_role`
reproduces the false UNKNOWN result; the conflict loop now applies the same
current-project citation predicate while preserving valid independent conflicts.
`R4-CONFLICT-PROOF.json` records the failure with only those new guards removed
in an isolated source copy. The buying-chain module passes all 23 tests.

The first R4 full gate exposed an older lifecycle replay fixture that restored
an accepted assessment without its known project binding. The fixture now
retains that binding; all replay assertions remain. An unchanged runtime test
also failed once and passed in isolation and with its full module; its cause was
not proven and no runtime code or assertion was changed. `R4-GATE-FAILURE.json`
preserves this failed checkpoint. A new frozen full run is required for acceptance.

## R5 independent citations and retained input paging

Codex on `37c4491` identified two further buying-chain correctness issues. A
deduplicated claim could be removed when just one retained citation became
invalid, despite independent current support. Retained input selection could
also stop after 24 invalid historical rows and miss older valid Evidence.

Current projection now evaluates retained citations individually. Independently
supported facts survive; unsupported role, assignment, category, and contact
facts are withheld or shown as UNKNOWN. Historical claims and citations remain
inspectable. Category survival reuses the existing extraction role vocabulary,
including aliases such as construction manager, rather than guessing from an
internal category key. Retained input selection advances by a deterministic timestamp/ID
cursor through 24-row pages until four valid inputs or exhaustion, without
expanding external document or request budgets.

`test_deduplicated_claim_keeps_independent_category_after_retained_reassignment`
uses actual enrichment/deduplication and covers rejection and reassignment,
exact surviving public provenance, and quiet material diffing.
`test_partial_citation_survival_downgrades_role_and_excludes_all_invalid_claim`
covers partial support and history. `test_retained_scan_reaches_older_current_version_after_invalid_prefix`
checks that 25 invalid newer rows do not starve the valid retained input or
remove its enrichment. `R5-BEFORE-AFTER.json` records exact-reviewed-head failure
proof; final acceptance uses the frozen manifest and final gate/review receipts.
Final focused buying-chain and project-state validation: 49 passed; Ruff, mypy,
and diff check passed. The receipt also retains the alias regression's failure
on the first unaccepted R5 implementation and its passing correction.

The first R5 full run exposed immediate-lease timing assumptions in pursuit
fixtures: PostgreSQL's timestamp was ahead of the Windows Python clock reading
in 195 of 200 local samples, by up to 0.983 ms. Freshly seeded test jobs now
explicitly start due; pre-existing queued/running jobs keep their availability,
and production queue/backoff code and assertions are unchanged. A second full
run exposed the same assumption in scoped-worker and pre-created research-job
fixtures. The two affected modules now explicitly seed intended-ready jobs as
due; their 22 tests pass, including deferred-backoff and fenced-worker assertions.
`R9-PURSUITS-FIXTURE.json` preserves both failures and the bounded fixture audit.
The same full run had a browser network-fetch failure before the card assertion;
`R5-GATE-FAILURE.json` retains it. Final backend and browser gates run separately,
with the unchanged serial browser suite and failure tracing enabled.

## R6 admitted claim conflicts and project change contract

Codex on exact `6a61e84` found that equality checks against the mutable
`PowerNeed` row dropped otherwise current, admitted project/activity claims for
different tier, MW, timing, or duration. The state projection now collects each
eligible field claim with its own Evidence first. Distinct eligible values show
`CONFLICT` and exact provenance, while a single claim that does not support the
mutable value leaves that field `UNKNOWN`. Matching claims retain all supporting
Evidence IDs. The existing current-version, project identity, activity, and
source-admission gates still exclude rejected, reassigned, wrong-activity, and
nonadmitted records; no unrelated utility projection was expanded.

The project change history endpoint now declares a concrete list response model
for its existing payload, including nullable prior/new states, both evidence
IDs, source date, and detection timestamp. The canonical OpenAPI export and
generated TypeScript client types were refreshed.

`R6-BEFORE-AFTER.json` records two independent failing regressions on the exact
base, plus a passing unsupported-field control. After repair, the full
project-state changes module passed 23 tests; Ruff, mypy, web typecheck,
OpenAPI/type generation, and diff check passed. Full repository gates and
independent review remain controller-owned.

## R7 material need conflicts

The material `power_need` snapshot now adds a `conflicts` map only when two or
more current, admitted, project/activity-bound claims disagree. It stores
distinct field values, without citation IDs or timestamps, and leaves the
historical row shape intact when claims agree. An unchanged selected `PowerNeed`
value can therefore produce a causal conflict event; a changed selection still
shows the contradiction. Resolution, renewed conflict, identical replay, an
agreeing citation, and later unrelated Evidence retain their expected behavior.

When an existing material snapshot predates this field, `seed_material_state`
captures pre-action claim conflicts under the project lock and quietly aligns
only its conflict metadata. It preserves prior selected values for a genuine
post-action diff. Retained-news assessment now avoids two eager `setdefault`
seed calls that could otherwise overwrite an already captured baseline after
the Interpretation changed. The same-observation revision regression proves
that this guard preserves a causal conflict-resolution event. A temporary
isolated mutant restoring eager seeding failed that regression.

`R7-BEFORE-AFTER.json` records exact `cf0662e` source-copy failures and final
focused evidence. A proposed Taylor identity-key adjustment was removed after
checking the current admission policy: Taylor planning-news records are
context-only and return before the affected branch. No Taylor product code or
test was changed. The affected project-state, collection-only ingestion, and
Taylor modules passed 65 tests; Ruff, mypy, and diff check passed. Full gates
and independent review remain controller-owned.
