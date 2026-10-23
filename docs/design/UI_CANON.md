# GridLens production UI canon — owner-approved 2026-10-23

**Authority:** the final seven-color GridLens corporate brand board and the owner-approved compact opportunity workspace screenshot. See [BRAND_ASSETS.md](BRAND_ASSETS.md) and [brand.tokens.json](brand.tokens.json). This supersedes all prior Aperture, gold, silver/orange, Signal Blue, ABC Diatype, and left-sidebar design directives. Historical documents remain evidence, not implementation authority.

## Mandatory composition

- **No left sidebar or toolbar.** One compact horizontal top navigation with the canonical logo, Opportunities, Customers, Power Markets, Permits, Interconnection, Reports, search and account controls.
- White/light workspace with restrained navy/slate typography and seven-color brand accents. No decorative photography, maps, hero illustrations or gradients in product UI.
- Top KPI cards and quick filters; dense, sortable, filterable, paginated opportunity/customer table on the left; selected customer intelligence detail panel on the right.
- Detail panel includes Overview, Buying Chain, Evidence, Power Analysis and Notes, using real records and verifiable values. Do not invent MW, dates, contacts, statuses or confidence.
- Sora headings/display; Inter body, labels and tables. Wordmark uses the approved thin, tracked uppercase treatment. Use only the final G with contrasting integrated hidden L. The generated brand board is a visual reference; vector fidelity must be reviewed against it.
- Accessible contrast, keyboard controls, and responsive tablet/phone reflow. On phones the right detail panel can stack or become a detail view, but do not introduce a permanent left navigation rail.

## Data and behavior must survive

Consume the existing [intelligence projection](../architecture/OPPORTUNITY_INTELLIGENCE.md). Preserve existing authentication, API records, route behavior, searches, filters, sorting, pagination, signals, operations, research, buying-chain and evidence workflows. Do not equate facility load with a credible bridge-power gap; distinguish unknown from zero, and preserve source provenance and qualification state. No screenshot-only invented data.

## Migration acceptance

1. Replace all legacy Aperture lockups, favicons, app icons and generator outputs with verified final G/L assets, including light/dark variants.
2. Replace old font declarations, hard-coded legacy colors and contradictory docs; remove orphaned assets after all references are migrated.
3. Verify no left toolbar/sidebar or photography/maps across actual routes, including desktop and mobile.
4. Run build, tests and visual comparisons at 1648x928, 1440x900, 1280x800, 768x1024 and 390x844; independently inspect final candidate.
5. Do not merge or deploy before the logo and UI are verified; do not claim brand parity from a mockup alone.
