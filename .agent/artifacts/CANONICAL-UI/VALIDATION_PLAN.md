# Validation plan and scope

This PR changes presentation/navigation only. Base backend and API contracts are unchanged. Validate exact final frontend/docs candidate and preserve prior failure logs.

- Required repository gates: dependency audit, Ruff/format, mypy, repeated migrations/schema parity, full backend tests, npm audit/typecheck/build, complete browser regression, docs graph, diff check.
- Behavior: need-level full-server filters/counts/pagination; selection/tab/Back/reload; grouped Signals decisions/members/all filters/scoped export; Research needs and saved workflow links; Operations source/ingestion controls; auth, error/loading/empty states; real fact/call persistence retains qualification semantics.
- Browser: desktop approved layout/logo comparison and390px list/detail/back with no horizontal overflow. Check contrast on Research and Operations, including failure states.
- Data boundary: loopback clone of retained corpus (1619 needs), dedicated app DB and separate _test DB; providers disabled, no ingestion worker/outreach/live writes. Synthetic test actions are not commercial acceptance.
- Review: independent Sol on frozen candidate after gates and complete docs. Any code change invalidates affected validation/review.
- Delivery: commit/push and PR only. CI status verified separately. No merge/deploy.

Started UTC 2026-10-20T22:42:01Z. Subphase durations and model token/config accounting UNKNOWN unless explicitly measured. No speedup claim.
