# GL3-029R1 final-gate regression repair

- **Objective:** Correct the focused test fake so the failure receipt path exercises the callable `SessionLocal()` context-manager lifecycle used by production.
- **Repository / candidate:** `gl3-repair-20261004`, branch `repair/gl3-pr24-20261004`, base `9e8246ef67b95fa2582cd9ea7e3ca5e3fb9cf71a`.
- **Owner / allowed files:** Builder owns only `backend/tests/unit/test_firecrawl_extraction.py`, this packet, and ignored `.artifacts/audit-repair/regression-completion.json` plus raw local check logs under `.artifacts/audit-repair/`.
- **Failure evidence:** Parent full pytest log `../gl3-repair-evidence-20261004/pytest-final.log` reports the `[False]` parameter failing at `autonomous_research.py:417` because test `SessionLocal` was a non-callable `SimpleNamespace`. A separate origin test failure is outside this repair.
- **Invariant:** Do not change production code, fallback behavior, assertions, provider boundaries, or perform paid calls. Preserve direct-retrieval failure receipt assertions and successful JavaScript-shell fallback assertions.
- **Acceptance:** Test fake supports both `.begin()` transaction contexts and callable `SessionLocal()` contexts; failed direct retrieval is recorded with `access_restricted`, and no Firecrawl scrape occurs for that ineligible failure.
- **Validation:** Focused extraction pytest and Ruff on the owned test file, using the isolated builder database configuration with provider credentials blank. Preserve raw outputs and exit codes.
- **Retry budget:** Two materially distinct implementation attempts maximum. Stop if the scoped test contract indicates a production API conflict.
- **Handoff:** Report exact changed paths, candidate identity, commands, raw logs, exit codes, and unresolved limits. No commit, push, merge, or deployment.
