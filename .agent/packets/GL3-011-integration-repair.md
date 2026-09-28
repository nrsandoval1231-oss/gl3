# GL3-011 integration repair

READY; preserve base a7ee3e4 and prior frozen candidate 171a6b48ec1bca96cc7068b33435f6b4e3799732b3be708b36a572512d01f1db. One Luna; same checkout and branch. No runtime/DB changes.

Repair only generated API/schema synchronization for three Georgia source-health fields, and the existing browser test's incorrect assumption that every permit source exposes an issue date. Allowed API generation inputs/outputs, web/tests/first_path.spec.ts, completion receipt. No adapter/domain/classification/migration changes.

Acceptance: generated contract matches current API; web typecheck/build and all three Playwright tests pass, with specific GA snapshot/comment-deadline/extraction-scope assertions and preserved city/news checks. Controller reruns exact final gates. Retry budget two materially distinct repairs. No push/merge/deploy. Record commands/exits/changedpaths in INTEGRATION_REPAIR.json and release test surfaces. Prior evidence retained.
