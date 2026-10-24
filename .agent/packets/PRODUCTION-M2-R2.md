# M2 R2 — require native raw capture before paid dispatch

Base 4eab0616c87476e8fbd410aab33dc20aedcc817e in the existing production
worktree and branch. Independent Sol REVIEW.json returned FIX: inline text with
self-computed hashes can reach paid dispatch without raw_path/raw_sha256.
Actual live first/replay receipts used verified raw files and remain valid.
The controller stopped the long gate on this invalid candidate and preserved its
partial passing checks as INTERRUPTED_REVIEW_FIX_REQUIRED.

One Luna owns scripts/compare_acquisition.py, its focused CLI test file,
docs/operations/acquisition-comparison.md, and ignored COMPLETION-r2.json.
Change the comparison module only if a narrow shared validator is necessary.
No provider wrapper, ledger, schema, other tests, scheduling, native parser,
credentials, canonical promotion, source registry or governance edits.
You are not alone; preserve others' work. No subagents, commits or paid calls.

Require paired raw path and SHA-256 for every supplied complete native capture
before paid execution. Verify raw bytes with existing containment, byte-bound and
hash checks before any provider call; absence of raw proof must fail preflight.
An incomplete/missing case may still be reported, but cannot dispatch for that
case. Preserve the non-dispatch inspection path and all replay behavior.
Test missing raw path, missing raw hash, and a later invalid raw receipt blocking
an earlier eligible case. Valid verified captures must still dispatch once and
replay cached. Update the documentation with this prerequisite.

Run focused comparison unit/CLI/integration tests using disposable pipeline_test,
root-context changed-file Ruff/format, targeted mypy and docs. Controller's gate
processes have stopped; do not touch retained pipeline_m2_app or its ledger.
Handoff exact changed files, commands/results, measured UTC timing and unknown
tokens. This is the second materially distinct integrity repair; if unresolved,
return evidence for controller recovery instead of another unchanged retry.
