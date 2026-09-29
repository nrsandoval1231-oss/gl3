# GL3-015G independent review r1

**Verdict: FIX**

Verbatim issue from Sol:

> Your compatibility verifier returns GO for a synthetic new hash with non-ASCII mapped type-01 lease bytes `[14,46)` or type-02 well number `[48,54)`, while accepted E profile requires ASCII and F parser rejects them.

Repair scope: G-owned verifier/tests/receipts/docs only. Preserve the prior single 302 `REDIRECT`/`UNKNOWN` access outcome. No new live request; no edits to D/E/F, graph/state, registry, or DB.
