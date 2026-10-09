# Preserved attempt record

All captured browser logs and Playwright native files are hashed in `RAW-MANIFEST.json`. The early failures below are test harness or assertion corrections; the only product regression reproduction is the separately identified failure against the exact base source.

| UTC run stamp | Result | Classification |
| --- | --- | --- |
| `1855477259796Z` | Browser file: 28 passed, 2 failed. | Test-only strict locator collision when a row and its expanded member share `data-opportunity-id`, plus an incorrect expected heading. Both expectations were corrected. |
| `1857077117886Z` | Browser file: 30 passed, 1 failed. | Transition-matrix test fixture installed multiple route handlers and selected the wrong tier-case fixture; the matrix was refactored to one dynamic handler and case-normalized tier selection. |
| `1858230887090Z` | Browser file: 30 passed, 1 failed. | The view-transition assertion expected a heading before the route state was established; test now asserts the resulting URL state. The route-fulfill teardown text followed that assertion failure and was not a product error. |
| `1859035031149Z` | One matrix test failed. | Test-only ingestion heading assertion was too specific; switched to checking the view URL. |
| `1859534523602Z` | One matrix test failed. | Test-only navigation locator assertion after view change; switched to checking the URL state. |
| `1900387828464Z` | Transition matrix passed. | Tier, search, Signal decision, page offset, and view invalidation passed. |
| `1901218762801Z` | One targeted test failed against base `App.tsx` (expected). | Actual product regression reproduced: after activity scope changed, the delayed old group page reopened members. Guarded source restored and SHA256 matched before/after. |
| `1902323919567Z` | Browser file: 32 passed. | Focused pre-final run; later token-fixture type-only edit was separately validated. |
| `1903119801357Z` | Typecheck and build failed. | Test-only TypeScript control-flow narrowing made a closure-assigned nullable URL resolve to `never`; replaced it with a request URL array. |
| `1903497598398Z` | Typecheck and build passed. | Corrected token fixture. |
| `1904570355422Z` | Browser file: 32 passed. | Full focused browser suite after token assertion and implementation freeze. |
| `1905400796870Z` | Typecheck, build, and browser file all passed; browser 32/32. | Final focused candidate checks. |

Two PowerShell command-construction errors stopped before test/application startup and have no separately saved raw log: the first focused wrapper's `Test-Path` parameter expression, and the first old-base repro's mismatched quote in its generated label. Their console outputs were available in the tool response but were not copied byte-for-byte to a file. They remain explicitly `UNKNOWN` rather than reconstructed as raw evidence.
