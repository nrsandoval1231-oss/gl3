# A6-R1 attempt history

The product source at initial R1 checkout `225258f90bc3dd2eee5fac689e41fd4caba4af8d`
(tree `1c09eebef2906de54393c5984325656bdf575aa6`) was the review's rejected
product candidate plus dispatch-only commits. The raw review was not edited;
`FAILED-REVIEW.json` SHA256 is
`318ad39dc32816e7521165153cc905ab416ff6e80454afdea870c7ebbf534367`.

The two independent repro result JSONs were copied to `FAILED-REPROS/` without
content changes. Their SHA256 values still match the original paths named in the
review: prospect `a3cea0aaaa8bf2198cd293537f9835c8781e5fdbd97c70d9aae6ac05e0e713c7`
and interval `3e7e2c756d33aa5af0493767970d628676b15f06e39f849bf26f095890f41b54`.
They are result receipts, so a separate ignored pure-domain runner was created
to replay their material inputs without importing application settings. The
first wrapper call supplied a relative script path and failed with exit 2
because the wrapper runs from `backend/`; that raw failure remains. The corrected
absolute-path invocation exited 0 and reproduced Prospect→Prospect with no gap
and Signal→Lead using supply that ended 2026-10-09 for a 2027 activity window.
All calls used `.artifacts/run-a6-focused-safe.ps1`; its provider-key-empty and
automation-off preflight passed, synthetic authentication only, and candidate
`.env` was absent.

## Repairs and validation attempts

1. Before product edits, the new unit regressions ran against the rejected
   implementation: 4 failed, 7 passed. The failures were the reported
   source-Prospect promotion and supply interval cases. The unmodified raw log
   is listed in `RAW-HASH-MANIFEST.json`.
2. The first domain edit introduced full-window coverage and source-Prospect
   handling. Its first unit run had 3 failures, 8 passes: inspection found the
   interval predicate had been passed decoded fact values instead of their
   interval-bearing rows. This was corrected in the owned domain file; the red
   output was preserved.
3. The first focused unit plus workflow integration run passed 12 tests.
4. The expanded integration fixture then had two test-only failures. One tried
   to assert a derived-gap field omitted by the existing mutation API response;
   the test now checks the canonical `effective_need_qualification` result,
   without expanding the public response. The next run detected that the
   integration fixture's manually appended closure draft/decision/retraction
   had advanced the history version three times without advancing its local
   expected-version counter. The fixture now accounts for those events; no
   production code changed for either failure.
5. Final focused run: 30 passed, one pre-existing Starlette/httpx deprecation
   warning. Final Ruff, `mypy src` (80 source files), and `git diff --check`
   passed. Exact raw invocation outputs, including all intermediate failures,
   are preserved at the paths and hashes in `RAW-HASH-MANIFEST.json`.

No production-service seam or migration was required. This is one bounded
implementation attempt; the root's frozen-candidate gates and new independent
review remain required. No old-candidate PASS is reused as acceptance.
