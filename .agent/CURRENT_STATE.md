# Current state — October 5, 2026

## GL3-029 acceptance reconciliation

Current remote main: `9a4669e592a64d0513f0bbb70e9a29197b8d2e0d`. PR24 remains an OPEN draft at remote head `d8b0e99897c600f32a0e00bb6770b841f2c6f907`, based on the earlier PR23 head. This isolated checkout is branch `repair/gl3-029-current-main-20261005`; frozen code candidate `15e27bcbbc0163a8af3c22761e2963df3479f73a`, tree `2ccdc2686a351b9f35888b3b7cb09d35b6d73e03`, includes current-main negation and fixed-date corrections. A docs-only descendant is being prepared; controller must verify source/test manifest identity and obtain fresh independent Sol review before any PR update.

Controller mandatory gates on the exact code candidate pass: Ruff, mypy, backend 1,157 passed/1 skipped/1 warning, clean/repeat/drift migrations, frontend typecheck/build, zero-vulnerability audit, and diff check. Generated OpenAPI contract is exact after line-ending normalization.

The hash-verified original corpus (16,960 Evidence rows) was restored only in isolated databases. Acceptance is **3/5, overall gate false**: Austin data-center and temporary-power pass only under the October 5 owner-approved source-linked no-question/no-change/replay exception; Chicago meaningful investigation passes; O&G and low-quality/unresolvable remain unmet. Preservation and replay pass. Full original-corpus browser suite passes 41/41. Provider configuration is present, but cost ceiling is $0 and search/scrape reservations are unset; no provider calls occurred.

See [validation report](../docs/validation/gl3-029-autonomous-pursuit-research.md), [work graph](WORK_GRAPH.md), and `.agent/artifacts/GL3-029-ACCEPTANCE-20261005/`. No merge, push, deployment, or GL3-030 integration. Preserve all recovery/evidence worktrees and data. Next direction: verify docs-only candidate identity and complete independent Sol review; corpus acceptance remains OPEN.
