# F4 — valid intelligence fixtures in commercial navigation tests

Base rejected9391984, branch feat/intelligence-integration-20261018. Luna owns only
web/tests/environment.spec.ts mock helper. Root owns docs. Terra's provider repair
is disjoint; no shared migrations or database ownership.

Evidence: four isolated mocked reproductions fail without database/backend access.
New IntelligenceResearch GETs receive generic [] from the old mock catchall, but
tasks/history require objects with items. The resulting component exception removes
the expanded card subtree; nine full-run navigation failures share that path.

Return schema-valid empty responses for the exact tasks and need-history GETs.
Do not broadly change unknown-route handling, product components, assertions,
timeouts, navigation behavior or protected UI. No external calls or live writes.

Validate the complete environment.spec.ts module, typecheck and diff check. Use
dedicated loopback8387/5387 and mock-only stub, no database; clean owned processes.
Retain failing traces and exact command/terminal count evidence. Two bounded repair
attempts, then report constraint. Root reruns complete regression on next frozen
candidate and independent review remains required.

Handoff:48 complete environment tests pass in54.9s; typecheck/diff pass. Exact GET fixtures only; unknown routes and assertions unchanged. Isolated servers cleaned up. Root complete regression still required.
