# Current state — October 5, 2026

## GL3-029 acceptance reconciliation

Current remote main: `9a4669e592a64d0513f0bbb70e9a29197b8d2e0d`. PR24 remains an OPEN draft at remote head `d8b0e99897c600f32a0e00bb6770b841f2c6f907`. Isolated branch `repair/gl3-029-current-main-20261005` now freezes code candidate `7768f2a6e3ec19f29f657c23c2120a392d1c31bf`, tree `4118cdf83f21e0fa3519b9ca956eae4bf8c9ae8f`, including current-main negation/date corrections and fail-closed category source proof. The prior docs candidate `b3f1121` received independent Sol FIX; that receipt is preserved. The repair requires a current canonical Evidence row with matching ID, URL and content hash and takes its quote only from the row abstract whenever a database session is supplied.

Controller mandatory gates on exact code `7768f2a` pass: Ruff, mypy, 1,161 backend passed/1 skipped/1 warning, clean/repeat/drift migrations, frontend typecheck/build, zero-vulnerability audit, and diff check. Focused validator tests pass 44. Full authenticated browser suite passed 41/41 on `15e27bc`; R4 changed validator tooling/tests only, so app/browser files are unchanged; this is not a new R4 browser run.

The hash-verified original corpus was restored in a fresh isolated database. R4 acceptance is **3/5, overall false**: Austin data-center and temporary-power pass only under the October 5 owner-approved source-linked no-question/no-change/replay exception, now citing canonical rows; Chicago meaningful investigation passes; O&G and low-quality/unresolvable remain unmet. Preservation and replay pass. Provider config is present, but maximum cost is $0 and provider reservations are unset; no provider calls occurred.

See [validation report](../docs/validation/gl3-029-autonomous-pursuit-research.md), [work graph](WORK_GRAPH.md), [R4 repair packet](packets/GL3-029-category-proof-r2.md), and `.agent/artifacts/GL3-029-ACCEPTANCE-20261005/`. No merge, push, deployment, or GL3-030 integration. Next direction: independent Sol review on exact docs descendant; corpus acceptance remains OPEN.
