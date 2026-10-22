# FR6 bounded test compatibility — handoff

## Scope

Changed only the 13 owned tests listed in `FR6.md`. No production implementation, retained-document test, configuration, or other-owned test was edited.

The fixtures now use consistent explicit Texas sites for positive regional cases. Disabled Boston and Georgia coverage verifies no new queue/retrieval work while retaining historical hashes, dates, evidence, and interpretation bindings. Scheduling asserts `DISABLED` freshness when registry/operator policy disables a source. Structured collection recovery uses test-local `PAGE_SIZE=1`, a realistic per-day count fixture, and a seeded legacy cursor; it retains crash, fence, nonempty-cursor, and seven-day-window assertions. The adversarial fixture patches both the registry module and the worker’s import-time registry alias so policy preflight is stable regardless of test import order.

## Validation evidence

- Focused ordered gate after the import-alias repair: `pytest tests/integration/test_source_scheduling.py tests/integration/test_structured_collection_adversarial.py -q --tb=short` — **56 passed**, 27.94 s, exit 0.
- Owned-file lint/format: `ruff format --check` and `ruff check --output-format concise` on all 13 owned paths — **13 files formatted; all checks passed**, exit 0.
- Full owned suite before the import-alias repair: **262 passed, 1 failed, 1 warning**, 135.65 s, exit 1. The sole failure was `test_worker_retry_continues_after_progress_commit_before_job_terminal`: when the scheduling tests had already imported `worker`, its captured unpatched `load_registry` caused policy preflight to reject the test-local `per_page=1` fixture before any mock HTTP call. The fixture now patches the captured worker alias too; the focused ordered gate above passes.
- A redundant full-suite rerun was stopped at 44% after controller direction to leave the final all-owned and repository gates to root. It produced no terminal result and is not counted as validation.

The all-owned suite still needs a terminal run on the frozen integrated candidate. FR6 is handed off for root validation and independent review; this artifact does not claim acceptance.
