# A5B cohort-token repair

This bounded repair closes the offset-page token gap identified by the independent A5B review. `GET /api/opportunities` now rejects a missing, empty, or whitespace-only cohort token when `offset > 0` with HTTP 422 before querying or returning page records. A supplied token still follows the existing current-cohort comparison and returns HTTP 409 when stale. First-page behavior and the group, detail, CSV, history, and commercial-triage route contracts are unchanged.

The browser binds an in-memory token to the exact opportunity cohort inputs (tier, search, decision, and all declared browse filters). A direct URL or restored navigation to a later offset first requests offset zero if no token is bound to those inputs, then requests the intended offset with that exact token. A stale-token 409 clears the old page and selection and restarts at offset zero. The focused browser proof covers direct offset navigation, token request ordering, filter URL restoration, Back/Forward, and a stale-token response without rendering the previous cohort as current.

## Focused validation

All Python commands used `.artifacts/run-a5b-focused-safe.ps1`, which verified provider keys were absent and used synthetic test authentication. The candidate had no `.env` file. Browser tests used synthetic local settings, disabled workers, and unique Playwright output paths under ignored `.artifacts/`.

| Check | Result |
|---|---|
| Focused API tests (`bounded_opportunity_page_group_detail_and_stale_cohort`, `opportunity_http_and_direct_defaults_are_bounded`, `opportunity_filter_scope_is_shared_by_pages_groups_detail_and_csv`) | 3 passed |
| Focused browser navigation and stale recovery | 2 passed |
| Ruff (owned API implementation and focused test file) | passed |
| mypy (`src`) | passed, 78 source files |
| Web typecheck | passed |
| Web production build | passed |
| `git diff --check` | passed |

An initial backend regression run failed before the API guard was added: both token-rejection assertions showed offset requests without a token could return successfully. The post-fix focused run passed. An initial browser run also failed because the new test used case-sensitive card/title text selectors while canonical titles capitalize words; the assertions were corrected to case-insensitive matches, and the new unique-output rerun passed both tests. These failures are retained in the raw logs and are not counted as passes.

The client bootstrap adds an offset-zero request only when a later-page navigation lacks a valid in-memory cohort token. The browser test confirms this request precedes the page request and that the later request echoes the returned token. No retained-corpus or performance gate was run by this builder; root owns those mandatory final checks.

## Boundaries

No public response fields, headers, schemas, migrations, qualification rules, filters, ordering, auth behavior, provider behavior, or persisted data were changed. No production database, provider, push, merge, or deployment action was used. A5B overall acceptance remains pending independent root validation and fresh review of the frozen candidate.
