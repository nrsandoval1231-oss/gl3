# GridLens Premium UI Implementation Plan

Goal: Apply the owner's November 11 screenshot and detailed approved specification to the existing commercial workspace.

Architecture: Refine the existing shared header and canonical company rollup. Keep API projections, company identities, child project selection, contacts, research, authentication and Pursuits intact. Use existing raster artwork without alteration, Sora headings and Inter interface text.

Scope: CanonicalHeader and responsive search; ProjectResults presentation and toolbar; isolated account disclosure/dialogs; build metadata passed through Vite and Docker build arguments. No backend engine, ingestion, schema, source activation or production changes.

- [x] Restore two-level navy header with contained approved logo, architectural raster, statement and existing four navigation handlers.
- [x] Add mobile search disclosure with focus and Escape behavior around existing API search.
- [x] Refine canonical account cards and single filter toolbar; preserve all existing filtering, need selection and provenance safeguards.
- [x] Add working Profile/Settings disclosures and truthful build metadata. Shared password sessions have no individual initials. Unsupported notifications/stars are omitted.
- [ ] Run typecheck/build, repository browser regressions, brand checks, disposable backend acceptance where available; capture and inspect desktop/mobile screenshots.
- [ ] Commit the final candidate and obtain independent Astra review. Fix blockers and repeat exact-head review after source changes.
- [x] Open one draft PR with receipts/screenshots; do not merge or deploy.

Review focus: long company names; unknown/conflicted power; scoped company contacts and multi-need Pursuit picker; expired session cleanup; iPhone overflow and dialog/search focus. Missing backend aggregate counts remain unavailable, never estimated from the visible page. Build SHA must reflect the compiled source, not an assumed deployment.

Exact-head full gates and independent final attestation are owned by PR #189 metadata; intermediate failed runs remain in the validation receipt. No merge or deployment is authorized.
