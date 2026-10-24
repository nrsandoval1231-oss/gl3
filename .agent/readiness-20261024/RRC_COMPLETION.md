# RRC IPC repair completion

Execution UTC: 2026-10-24 17:53 UTC. Worktree: `gl3-readiness-rrc-20261024`, branch `audit/rrc-ipc-repair-20261024`. Base: `fae481db749b2e71dfb41ee63547c3fa1f6b1170`.

## Change

The generic isolated-result cap remains 8 MiB. The fixed 64 MiB cap is selected only for `gridlens.ingestion.adapters:_retrieve_source_direct` when its selected source has both ID `texas-rrc-drilling-permits` and method `rrc-drilling-permits`. Parent receive and child send independently derive the same fixed cap from that allowlist; neither accepts a caller-provided byte cap. Generic calls and either mismatched identity/method retain 8 MiB. The 512 MiB child memory cap, shared deadline, kill/cleanup behavior, source fetch bounds, parsing, and persistence path are unchanged.

## Deterministic evidence

Commands ran from `backend` under uv's isolated Python 3.11 environment. `DATABASE_URL`, `APP_PASSWORD_HASH`, and `SESSION_SECRET` were set to test-only values; `OPENAI_API_KEY`, `TYPESAFE_API_KEY`, and `FIRECRAWL_API_KEY` were blank. No `.env` was copied.

| Command | Exit | Result |
|---|---:|---|
| `uv run --offline --python 3.11 --extra dev pytest tests/unit/test_research_acquisition_boundary.py -q` | 0 | 28 passed; includes generic >8 MiB rejection, exact ID+method allowlist and spoof cases, >8 MiB evidence/provenance/hash pipe round-trip, >64 MiB child failure payload, parent receive rejection before unpickling, 512 MiB invariant and timeout cleanup. |
| `uv run --offline --python 3.11 --extra dev pytest tests/unit/test_rrc_drilling.py tests/unit/test_retained_permits.py -q` | 0 | 67 passed. |
| `uv run --offline --python 3.11 --extra dev ruff format tests/unit/test_research_acquisition_boundary.py` | 0 | Reformatted the assigned test file to satisfy repository formatting gate. |
| `uv run --offline --python 3.11 --extra dev ruff format --check tests/unit/test_research_acquisition_boundary.py` | 0 | 1 file already formatted. |
| `uv run --offline --python 3.11 --extra dev ruff check src/gridlens/ingestion/adapters/bounded_http.py tests/unit/test_research_acquisition_boundary.py` | 0 | All checks passed. |
| `git diff --check` | 0 | No whitespace errors. |

## Production evidence and limits

Read-only receipt: `C:\Users\nrsan\Nucleus\02_Projects\GridLens\gl3-readiness-20261024\.artifacts\readiness-20261024\production-runtime.json`, SHA-256 `DCC564B4E333C4C31312BC09F73385821F0740D1C7A2DCAABE3CA7D5754148CB`. Its RRC source-health row reports enabled source `texas-rrc-drilling-permits`, five attempts, `acquisition_result_too_large`, zero retrieved records, and an earlier success as summarized in `.agent/readiness-20261024/INDEPENDENT_SECURITY_AND_RRC_REVIEW.md`. This supports an IPC-size diagnosis; it does not prove current upstream completeness or acceptance.

No live retrieval, ingestion, provider call, or database write was performed. Hosted CI, full repository gates, and independent review of the implementation candidate remain controller-owned and `UNKNOWN` here. UTC start-to-finish duration, model/config identity, and token counts are `UNKNOWN` (not measured). Candidate commit SHA is reported by the commit handoff; base SHA is recorded above.
