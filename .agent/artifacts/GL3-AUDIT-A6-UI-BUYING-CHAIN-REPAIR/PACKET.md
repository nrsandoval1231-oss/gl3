# A6 additive-contract fixture repair

Node A6-UI-R1 is READY. Candidate base is `e306b289fdd6081ed4a59ae94eb16b5644d12982`, branch `repair/gl3-facts-entry-20261008`, worktree `gl3-facts-entry-20261008`.

Root full browser gate returned 68 passed, 1 skipped, 4 failed in buying_chain.spec.ts. Its shared API fallback still returns an array for newly added exact-Need facts and workflow-status GETs. Inspect the retained traces to confirm the missing DTO attribution before edits. Preserve all failures and assertions.

Luna owns only `web/tests/buying_chain.spec.ts` and new repair handoff artifacts under `.agent/artifacts/GL3-AUDIT-A6-UI-BUYING-CHAIN-REPAIR`. Add the existing empty fact-history and UNKNOWN status DTOs for exact selected Needs. Do not alter product code, canonical tests' assertions, provider calls, auth, API contracts, or other fixtures. Root-owned controller capture and diagnostics are excluded from staging. You are not alone; preserve other work.

Acceptance: all four buying-chain tests pass with prior evidence/navigation/mobile assertions retained; frontend typecheck and diff check pass. Clear A6_UI_PERSISTED_* flags in this fixture-only run; providers absent, research disabled, no candidate .env. Use a fresh isolated browser output label and synthetic auth only. One fixture repair attempt; unresolved behavior returns evidence to controller, no product repair or blind retry.

Freeze exact allowed source and explanatory handoff, raw logs/archive/hash receipt. Do not grade acceptance, push, merge, or deploy. Root reruns required final gates after clean terminal handoff and binds independent review to the resulting candidate.
