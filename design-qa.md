# Canonical Opportunities visual validation

final result: passed

Scope: visual implementation against the owner's supplied 1280×720 image, with explicit existing-API limitations below. This is not pixel-perfect, production-data, deployment or commercial-launch acceptance.

Source: [approved reference](docs/design/references/canonical-opportunities-20261029.jpg), SHA-256 `3fea04be9043f337eeae6be89ae6e2baed07e31c0dc8219c9d78b6aa788a0b09`.

Final source candidate: `d41d4e179edf80147b78486398aa7582fab92bce`.

## Comparison evidence

The [combined comparison](docs/validation/canonical-reference-ui-20261029/comparison-synthetic.png) places the approved reference and rendered production bundle together at equivalent 1280×720 selected-record state. Implementation records are conspicuously synthetic browser-test fixtures, not real opportunities. [Desktop](docs/validation/canonical-reference-ui-20261029/desktop-synthetic.png), [mobile detail](docs/validation/canonical-reference-ui-20261029/mobile-detail-synthetic.png), and [mobile list](docs/validation/canonical-reference-ui-20261029/mobile-list-synthetic.png) were inspected. Wide desktop at 1440×900 and both ends of mobile horizontal table scrolling were also captured locally.

## Review and correction passes

1. Initial implementation exposed an overcrowded filter row, excessive spacing and an incorrect reusable brand asset. Corrected gutters, typography, compact filters and source-identical header artwork.
2. Populated comparison exposed duplicate group/project rows. Reused the existing flat project-results API for the canonical default while retaining grouped/account browsing as secondary routes. Corrected the independent need/gap columns and table density.
3. Desktop/mobile review exposed long unknown metrics, timezone-shifted dates, lost source qualifiers, ambiguous contact authority, and overlapping mobile KPI labels. Corrected the presentations without inventing values or verification.
4. Ten-row production-bundle comparison exposed an extra filter row, title wrapping and a next-action container below the visible panel. Corrected header search proportions, row density, inline qualification, and the bounded detail body with an always-visible action. A long-name regression traced page overflow to absolute screen-reader labels escaping the table scrollport; established the wrapper containing block and verified the regression passes.

No unresolved material visual defects were observed in these reviewed states. The existing API does not provide Follow/Mark Complete state or global priority/newness/history metrics, so these states are not fabricated. Extra confidence/qualification and contact-authority text necessarily differs from the illustration. Mobile uses controlled table scrolling; region/stage/priority filters are explicitly page-scoped. See the [delivery record](docs/validation/canonical-reference-ui-20261029.md) for exact checks and limits.

Independent Astra review approved exact source `d41d4e179edf80147b78486398aa7582fab92bce` with no unresolved P0/P1/P2 findings; its separate 10-test browser check and fresh build passed. Broader suite results are recorded separately in the delivery receipt.
