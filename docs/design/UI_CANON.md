# GridLens production UI canon — brand approved 2026-10-24, autonomous amendment 2026-10-26

**Product authority:** the owner-approved [Autonomous Intelligence Canon](../product/AUTONOMOUS_INTELLIGENCE_CANON.md) supersedes manual-workflow requirements. **Visual authority:** the final seven-color GridLens corporate brand board and owner-approved compact opportunity workspace screenshot. See [BRAND_ASSETS.md](BRAND_ASSETS.md) and [brand.tokens.json](brand.tokens.json). This supersedes all prior Aperture, gold, silver/orange, Signal Blue, ABC Diatype, and left-sidebar design directives. Historical documents remain evidence, not implementation authority.

## Mandatory composition

- **No left sidebar or toolbar.** One compact horizontal top navigation with the canonical logo, Opportunities, automated Research and Signals routes, unified search and account controls. Operations/diagnostics remain internal, not a primary user workflow. Customer account/project navigation remains within Opportunities. Labels pictured in the brand board do not authorize invented routes.
- Harbor Navy header with the existing dark G/L lockup; white/light workspace with restrained navy/slate typography and seven-color brand accents. No decorative photography, maps, hero illustrations or gradients in product UI.
- Four KPI cards (High Priority, Total Pipeline, Estimated Power Gap, Average Timeline) and Quick Filters on their right. Dense, sortable, filterable, paginated opportunity/customer table at approximately 69%, with customer intelligence at approximately 31%. Use the owner’s supplied dashboard composition, never the older sidebar layout.
- Dense table fields include Company / Project, Location, Estimated Gap, Need Date, Confidence, Priority and evidence-derived commercial disposition. No operator-maintained Status control. Preserve canonical numerical priority and commercial disposition/qualification; do not invent High/Medium thresholds or confidence percentages.
- Total Pipeline counts API power needs across all dispositions under current non-disposition filters, explicitly labeled. Aggregate priority, remaining gap and average timeline remain unavailable until the API provides them. Never aggregate one paginated slice or substitute required demand for gap.
- Detail panel includes Overview, Buying Chain, Evidence and Power Analysis, using real records and verifiable values. Sources, freshness, unknowns and read-only retained audit remain inspectable. Timeline and research gaps remain under More; supported facility demand, supply, energization, duration and gap basis remain in Power Analysis. Qualification and provenance remain inspectable. Do not invent MW, dates, contacts, statuses or confidence.
- Sora headings/display; Inter body, labels and tables. Wordmark uses the approved thin, tracked uppercase treatment. Use only the final G with contrasting integrated hidden L. The generated brand board is a visual reference; vector fidelity must be reviewed against it.
- Accessible contrast, keyboard controls, and responsive tablet/phone reflow. On phones the right detail panel can stack or become a detail view, but do not introduce a permanent left navigation rail.

## Data and behavior must survive

Consume the existing [intelligence projection](../architecture/OPPORTUNITY_INTELLIGENCE.md). Preserve authentication, retained API records, search, filters, sorting, pagination, Signals, autonomous Research, buying-chain and source inspection. Retire manual call logging, notes, operator statuses, fact drafting/correction, manual qualification and administrative pursuit updates, including obsolete clients and public mutation routes. Backend immutable evidence and historical attribution remain retained. Do not equate facility load with a credible bridge-power gap; distinguish unknown from zero, and preserve source provenance and qualification state. No screenshot-only invented data.

## Migration acceptance

1. Replace all legacy Aperture lockups, favicons, app icons and generator outputs with verified final G/L assets, including light/dark variants.
2. Replace old font declarations, hard-coded legacy colors and contradictory docs; remove orphaned assets after all references are migrated.
3. Verify no left toolbar/sidebar or photography/maps across actual routes, including desktop and mobile.
4. Run build, tests and visual comparisons at 1648x928, 1440x900, 1280x800, 768x1024 and 390x844; independently inspect final candidate.
5. Owner acceptance of the existing logo geometry and wordmark is recorded in `brand.tokens.json`. Complete exact-candidate implementation, browser, and required review gates before merge; do not claim independent graphic verification or exact pixel parity from mockups.

## Historical October 24 implementation evidence

See [dashboard implementation report](DASHBOARD_IMPLEMENTATION.md) and [screenshots](screenshots/). Desktop uses a 92px header and 69/31 panels. Tablet and phone preserve readable lists and use a dedicated selected-detail view. Search is consolidated in the header. Account row selection keeps the desktop table visible; the separate project-count action opens the existing account/project workflow.

The October 24 implementation kept Opportunities, Research, Signals and Operations destinations; this is historical behavior, superseded where it conflicts with the autonomous experience. The screenshot’s Power Markets, Permits, Interconnection and Reports destinations have no implemented routes and are not fabricated. Customer aggregation remains inside Opportunities. No favorite/watchlist write API is invented.

Owner acceptance of the existing geometry and wordmark was recorded on 2026-10-24; no additional comparison or independent graphic verification is claimed. The bounded retained-real-source desktop/mobile UI gate passed on 2026-10-24 and PR116 subsequently merged. See [PR116 acceptance evidence](PR116_ACCEPTANCE_20261024.md). Each later release requires its own exact-candidate gates and independent review; parent M6 and Finish Contract remain open.
