# M2 acquisition R1 — pre-dispatch integrity

Same repository, branch, base and file ownership as PRODUCTION-M2-ACQUISITION.
Controller focused twelve tests and lint passed. Root-level format check, full
backend mypy and docs passed. A controller format command from backend selected
the wrong configuration for the root script; preserve that failed receipt and
the corrected root-level result. This is not a product formatting defect.

Repair actual gaps before live dispatch: report persisted LogicalCall.max_cost_usd
on cached replay instead of the current configured unit cost; validate native
capture MIME against manifest; constrain absolute extracted-text references as
well as relative paths to the receipt directory; reject connection URL query
overrides of the exact isolated database. Add behavioral preflight tests proving
no dispatch with missing credentials, nonfinite or exhausted caps, wrong database,
path escape, missing native capture, and mismatched MIME. Prove changed unit-cost
configuration reuses the completed call and its original reservation.

Clarify docs: one-cent reservation is not actual invoice; use --output; larger
native HTML is skipped by local policy, not a demonstrated provider inability.
No changed acquisition security, provider client, scheduling, migrations,
canonical promotion or live calls. Preserve original handoff. Return
COMPLETION-r1.json with exact focused checks and failures. This is first bounded
repair; second must be materially different. Controller owns live run and final
acceptance.
