# GridLens production UI canon — owner-approved 2026-10-24

**Authority:** the final seven-color GridLens corporate brand board and the owner-approved compact opportunity workspace screenshot. See [BRAND_ASSETS.md](BRAND_ASSETS.md) and [brand.tokens.json](brand.tokens.json). This supersedes all prior Aperture, gold, silver/orange, Signal Blue, ABC Diatype, and left-sidebar design directives. Historical documents remain evidence, not implementation authority.

## Mandatory composition

- **No left sidebar or toolbar.** One compact horizontal top navigation with the canonical logo, existing Opportunities, Research, Signals and Operations routes, search and account controls. Customer account/project navigation remains within Opportunities. Labels pictured in the brand board do not authorize invented routes.
- Harbor Navy header with the existing dark G/L lockup; white/light workspace with restrained navy/slate typography and seven-color brand accents. No decorative photography, maps, hero illustrations or gradients in product UI.
- Four KPI cards (High Priority, Total Pipeline, Estimated Power Gap, Average Timeline) and Quick Filters on their right. Dense, sortable, filterable, paginated opportunity/customer table at approximately 69%, with customer intelligence at approximately 31%. Use the owner’s supplied dashboard composition, never the older sidebar layout.
- Seven table columns: Company / Project, Location, Estimated Gap, Need Date, Confidence, Priority, Status. Preserve canonical numerical priority and commercial disposition/qualification; do not invent High/Medium thresholds or confidence percentages.
- Total Pipeline counts API power needs across all dispositions under current non-disposition filters, explicitly labeled. Aggregate priority, remaining gap and average timeline remain unavailable until the API provides them. Never aggregate one paginated slice or substitute required demand for gap.
- Detail panel includes Overview, Buying Chain, Evidence, Power Analysis and Notes, using real records and verifiable values. Timeline and research gaps remain under More; supported facility demand, supply, energization, duration and gap basis remain in Power Analysis. Qualification and provenance remain inspectable. Do not invent MW, dates, contacts, statuses or confidence.
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

## October 24 implementation evidence

See [dashboard implementation report](DASHBOARD_IMPLEMENTATION.md) and [screenshots](screenshots/). Desktop uses a 92px header and 69/31 panels. Tablet and phone preserve readable lists and use a dedicated selected-detail view. Search is consolidated in the header. Account row selection keeps the desktop table visible; the separate project-count action opens the existing account/project workflow.

Existing Opportunities, Research, Signals and Operations destinations remain functional. The screenshot’s Power Markets, Permits, Interconnection and Reports destinations have no implemented routes and are not fabricated. Customer aggregation remains inside Opportunities. No favorite/watchlist write API is invented.

The original source geometry/wordmark verification flags remain false. Do not treat UI integration or automated asset validation as approval of that trace.
