# Compact sidebar controls

Final production inspection of the released navigation correction (`71b3f7b`, reviewed source `d44cf5a`) exposed nested sidebar overflow at 1280 × 800 in Windows Chrome. The document itself fit, but the sidebar had clientWidth 304 and scrollWidth 316; the Tools summary ended at x316.17 beyond its visible client edge. The preceding page-width assertion could not detect this clipped control.

This bounded frontend correction lets the opportunity count, sort and Tools controls wrap when the panel needs more room. It preserves the primary desktop composition, readable controls and existing Tools/filter behavior. It changes no backend, dependency, data, qualification, provider setting, budget, brand asset or typography. The production update replaces only the web image.

The focused regression uses a four-digit opportunity count and the normal Priority sort. A stable scrollbar gutter reproduces the Windows condition in headless Chromium. Assertions check the sidebar's own scrollWidth/clientWidth and the visible Tools bounds, then open Tools and More filters to access Tier. Intermediate desktop widths are included to avoid validating only the five requested capture sizes.

Controller gates: **171 browser tests passed, one gated persistence case skipped**, 108.39 seconds; dependency audit, typecheck, production build, documentation and diff checks passed. [Gate receipt](sidebar-fix/gates.json), [raw browser results](sidebar-fix/browser.log), [frontend manifest](sidebar-fix/frontend-manifest.json). The separately executed persistence proof and unchanged backend/provenance validation remain linked in [the original candidate](CANDIDATE.md) and [navigation release evidence](NAVIGATION_RELEASE_FIX.md). Independent review and remote CI bind the subsequent frozen commit; local gates alone do not establish either.

[Fresh side-by-side reference comparison](sidebar-fix/desktop-side-by-side.png) · [50% overlay](sidebar-fix/desktop-overlay.png) · [Geometry/request ledger](sidebar-fix/browser-measurements.json)

| Viewport | Current UI, isolated historical API |
|---|---|
| 1648 × 928 | [Primary desktop](sidebar-fix/desktop-1648x928.png) |
| 1440 × 900 | [Desktop](sidebar-fix/desktop-1440x900.png) |
| 1280 × 800 | [Compact desktop](sidebar-fix/desktop-1280x800.png) |
| 768 × 1024 | [Tablet](sidebar-fix/desktop-768x1024.png) |
| 390 × 844 | [Mobile](sidebar-fix/desktop-390x844.png) |

All five captures have zero page JavaScript errors and no horizontal document overflow. The separate focused control-bounds regression covers the nested list at 1280, 1321, 1330, 1399 and 1440, including a reserved scrollbar gutter. Historical captures use the isolated retained ACS record, without a production freshness claim; production authenticated observations are retained separately. The earlier rapid-resize live capture's first image showed a stale loading frame and is excluded from visual acceptance.

The prior [visual discrepancy report](VISUAL_DISCREPANCIES.md) still applies to real-data density and missing licensed ABC Diatype binaries/official wordmark master. This correction closes the nested control clipping; it does not claim exact-brand parity or completion of the parent product Finish Contract.
