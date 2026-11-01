# Customer rollup performance repair — November 1, 2026

Status: locally validated draft repair; retained-data HTTP performance and deployment acceptance remain pending. Owner explicitly authorized publishing this draft on November 1. This record does not approve merging or deploying it.

Group opening now computes the complete customer header and bounded first child page in one grouping pass, then uses the existing privacy-aware project serializer. Search, region and stage select matching customer sets independently, preserving cases where different children satisfy different filters. Identity assignment and suppression checks are unchanged.

Final local backend validation: 3,698 tests and 7 subtests passed; 2 declared skips. Pytest took198.93 seconds, wrapper201.219 seconds, below the unchanged480-second limit. All184 ordinary browser regressions passed, as did3 real-backend responsive journeys at1440,768 and390pixels. Those journeys cover full child traversal, filters/search/sort/global pagination, separate Amazon identities and actual detail/back navigation. Independent source review found no blocking issue.

The synthetic scale fixture contains2,098 browse rows and417 customer groups, including DE Central48, Diamondback159 and Amazon3projects with3separate identities. Final first-context UI readiness measured347–387ms, reload286–308ms, and maximum complete HTTP response779ms across38requests per viewport. These are synthetic local measurements; first-context does not mean cold PostgreSQL or operating-system caches.

The earlier retained-snapshot direct open profile took11.04–14.55seconds, overwhelmingly SQL. An authenticated retained-copy HTTP run exceeded15seconds on its preceding group-list request, before reaching open. Its temporary session was subsequently removed and all74table hashes matched the pre-test copy. The final repaired retained-data HTTP comparison has not run: automatic approval review blocked transferring the prepared source/helper to the existing isolated SSH test workspace. No workaround or retry occurred.

Final runtime source SHA256 values, normalized to LF: API5155a4b5e06dc95891edebc6641d79c0bba00ac2eb6d3aae22ed283b99b72eae; customer results16be2642235c646127023a3a330dd7de79c91736cc007451562bc184ea9654d8. The source and new backend test files match the full-suite archive. Static/type/build/schema/document-link checks passed locally; dependency locks are unchanged, audits were not rerun, and exact new-head CI remains required.

Production was previously recovered to593cfd516d82a12b66558f53b975ad6c2b711517. No production operation occurred during this repair. No migration, index, backfill, provider or security change is included. Earlier unexplained480-second local timeout and ingestion catch-up gaps remain unresolved. Retained performance, release compatibility, fresh recovery checks and any required exact-controller approval remain separate gates.
