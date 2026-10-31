# Default Customer Rollup Implementation Plan

> For agentic workers: use the repository agent harness and bounded packet; three Luna lanes, lead integrated validation, independent Astra review.

**Goal:** Default Opportunities lists each safely resolved customer/operator once and nests its distinct projects.
**Architecture:** Reuse saved-generation customer_results grouping and ProjectResults expansion, using existing regulator/company identity keys and server-owned cohort tokens. Extend full-cohort query controls and switch only the default browse path; retain project detail/evidence/privacy boundaries.
**Tech stack:** FastAPI/SQLAlchemy/PostgreSQL18.6, React/TypeScript/Playwright.
**Spec:** [.agent packet](../../../.agent/packets/CUSTOMER-ROLLUP-20261031.md), settled owner-approved requirement.

## Constraints
No production changes, migrations, provider activation, normalization/backfill, loose-name entity merges, PR publication or merge. All backend validation uses new disposable local databases. Existing released presentation is preserved except the requested nesting and truthful customer controls/counts.

## Review focus
- Same customer across several project pages must remain one group with complete child pagination.
- Near-identical names without identity evidence must remain unresolved/separate.
- Changed filters, sort or generation invalidate incompatible parent/child/cache tokens.
- Search by one project must find its customer and retain related selected-sector projects.
- Pending/error/expired pages must not expose stale actionable controls or misleading totals.

## Tasks
- [ ] Backend lane: add failing integration cases for complete identity groups, no false merges, global sort/filter/search/pagination and facets; implement customer_results and grouped-route query controls; run focused tests.
- [ ] Frontend lane: make grouping default for root/workspace/header navigation; preserve explicit projectBrowse legacy path; carry filters/sort through URL, cache and child/open requests; keep expansion/details/back and responsive errors.
- [ ] Browser lane: add true default-group fixtures and interaction regressions; label retained flat tests with explicit legacy mode without weakening their assertions.
- [ ] Lead: inspect retained real-name samples read-only, integrate generated API types, run strict backend checks/migrations/tests on new test DB plus frontend typecheck/build/browser suite and doc links. Preserve actual failed attempts.
- [ ] Astra: independently inspect frozen integrated diff/evidence and report specific findings; repair and rerun affected gates before acceptance.
- [ ] Lead: commit clean reviewed local branch with actual gate evidence and remaining limitations; no PR publication, merge or deployment.
