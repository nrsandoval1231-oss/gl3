# A5B implementation and validation checkpoint

This candidate implements the bounded browse, saved history, detail, filters, and export slice described in `.agent/packets/GL3-AUDIT-A5B.md`. The active controller amendments are `.agent/packets/GL3-AUDIT-A5B-BOUNDED-CARD-DIRECTION.md`, `.agent/packets/GL3-AUDIT-A5B-FILTER-CONTRACT.md`, and `.agent/packets/GL3-AUDIT-A5B-DISPATCH-20261008.md`. This is builder evidence, not an acceptance verdict.

## Behaviors in this candidate

- Opportunity listing uses the canonical compact A5A projection, exact frozen client grouping/title/search semantics, dimension filters from the filter-contract supplement, filtered-cohort tokens, page metadata, bounded group-member traversal, exact-need detail, and authenticated filtered CSV. Unsupported query parameters and unsupported filter values fail explicitly. Numeric MW filters share `exact_mw_interval()` with commercial floor presentation; the floor decision itself is unchanged.
- Summary title derivation for Houston permit projects now uses the same owner/occupant extraction as the full projection. It passes only eligible Houston project IDs, in batches of at most 32, to the canonical `buying_chain_views()` reader. Summary records without supported owner/occupant facts remain without title-company attribution. Full detail and compact summary share `_opportunity_title_company()`.
- Commercial triage retains the canonical work-group/card builder. It preflights over-50 groups and nested row/byte limits before full card construction or evaluation writes, returning an explicit 413 rather than returning a partial authoritative card. Triage pages and saved-history pages expose bounded offsets and page metadata.
- Saved-history detail is lazily fetched from the exact saved pursuit endpoint. The historical panel renders only stored snapshot/version/note material and does not load the current autonomous-research status. It labels search as page-scoped. Queue page counts distinguish selected-page totals from the all-eligible grouped total; page controls preserve per-need unsaved note drafts.
- Opportunity filters persist in the URL/history state and restore on Back, including selected need and page offset. The UI consumes server group identifiers and completeness metadata rather than deciding from a page fragment.

## Builder validation

Focused backend tests passed: 79 tests across the browse/filter/export/API tests plus the unit commercial-triage test's 20 tests (99 total; one Starlette deprecation warning in the API run). Focused browser checks passed: `web/tests/commercial-pursuits.spec.ts` 12/12, including queue/history pagination, Back-to-page draft survival, saved detail, and no live research/evaluate call while viewing a saved snapshot. Web typecheck and production build passed. OpenAPI TypeScript generation was repeated with no change to `generated.ts` (SHA-256 `A333ACC87536B3DE22DCB6E068A709BDDF7BA2D13759C2C098B543A3875A852D`). Focused Ruff passed for the changed backend modules/tests; focused mypy passed for `app.py` and `commercial_presentation.py`.

The controller independently reported read-only frozen TypeScript parity after the Houston title repair: 1,167 eligible rows / 1,149 opportunity groups, exact group keys/order/titles/decisions and 17 search-query results. The diagnostic run reported 151 SQL statements and 6.3348 seconds; this was an investigation run, not a final public-page performance measurement. The controller owns the frozen page traversal, response-size/performance, full suite, fresh migration, browser, and final candidate gates; those remain pending.

## Failed attempts retained

All named raw logs listed in `RAW_LOGS.json` remain under the ignored worktree `.artifacts/` directory. This includes the two initial focused browser failures, earlier filter-test failures, the first title-attribution FK-order fixture failure, Ruff/mypy failures corrected by later focused runs, and the initial generated-client typecheck failure corrected by adding `workflow_status: UNKNOWN` to typed test fixtures. No failure output was rewritten to claim a pass.

An early direct pytest/bootstrap attempt was identified by the controller as violating the required provider-blank-before-settings-import sequence. No retained raw log exists for that incident and the unredacted tool bytes are UNKNOWN; no credential values were persisted in repository artifacts. All subsequent backend checks used `.artifacts/run-a5b-focused-safe.ps1`, whose provider preflight succeeded. The two browser attempts run with all provider variables blank and synthetic test authentication; the first command failed before starting Playwright because it resolved the wrong local log directory, and subsequent executions used a unique `.artifacts/` log path.

## Still open

Builder checks do not certify A5B. The controller must rerun the complete backend/Ruff/mypy/web/OpenAPI audits on the frozen head, independent actual-TypeScript API/group/page traversal, retained-corpus read-only checks, matched public-page SQL/latency/response-byte/allocation checks, and fresh browser suite. Exact source SHA/tree and raw file hashes are recorded in `COMPLETION.json` and `RAW_LOGS.json` after the source commit is created.
