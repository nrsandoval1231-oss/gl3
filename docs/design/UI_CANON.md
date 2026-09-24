# GridLens application UI — frozen canon

**Status:** Frozen by Nick Sandoval on September 24, 2026  
**Scope:** Private GridLens application UI in gl3  
**Product authority:** [PRD](../product/PRD.md); its 42 requirements and qualification gates remain authoritative.  
**Visual references:** [Browse](references/browse.webp) · [Opportunity detail](references/detail.webp) · [Owner-provided brand system](references/brand-system.webp)

The two screenshots define one application flow: **browse opportunities → open a focused power need → return to the same browse context**. They are fictional sample-data design references, not working screens or proof of actual ingestion, sources, projects, contacts, or verified power gaps. The brand reference is owner supplied. Implement real behavior and show only supported facts.

## Frozen decisions

| Area | Decision |
|---|---|
| Brand | GridLens Aperture mark and wordmark appear once, together in the **top-left header lockup**. No repeated symbol, watermark, faceted logo graphic, or logo art in panels. |
| Color | Primary visual and interactive color is **GridLens Navy `#17324A`**; deep current `#101F2D`; steel `#395A75`; atmosphere `#6F879D`; mist `#D5DEE5`; ice `#F3F6F7`; white `#FFFFFF`. Do not use the brand reference's signal blue `#3B82F6` in the application interface. |
| Type | Crisp modern sans in the ABC Diatype direction; readable 14–16px body text, strong project names and MW figures, no more than two font families. Match the screenshots' hierarchy rather than attempting to use image text as a font asset. |
| Frame | Light ice canvas, generous spacing, a small number of rounded navy and white surfaces, subtle borders, no gratuitous card grid, heavy shadow, or technical dashboard. Navy leads both screens. |
| Primary navigation | Signals, Prospects, Leads stay visible in the header. A subtle menu contains secondary destinations and settings. Search is always available. Tier describes evidence maturity, not score. |
| Browse | One navy heading surface and one small “Today” changes surface above a single continuous list. Lists cover the nation and all industries; construction and commissioning are default priorities, not collection limits. Rows show only supported project, power need, start, and duration fields. |
| Selected row | Restrained navy indicator/tint and arrow; opening it presents the focused brief. The back action restores tier, filters, sort, selected row, and scroll position. Previous/next advances within the current result set. |
| Detail | Navy project heading; one compact power-gap summary; plain-language explanation; evidence disclosure; likely buyer; one specific next action. Technical inputs, competing evidence, source links, history, and notes open on demand. |
| Action | Use an action suited to the known facts. If a named contact is missing, “Add contact” or a discovery action is appropriate. Do not imply an outreach call happened or that a person is known. |
| Motion | Fluid but restrained transition between list row and detail, about 200–300ms; gentle hover/focus feedback. Preserve scroll context and focus. Respect reduced-motion preference. No continuous decorative animation on the working surfaces. |
| Responsive | Keep the same content priorities on mobile: tier navigation, readable opportunity rows, focused brief, evidence disclosure, and action. Stack the small surfaces instead of squeezing desktop columns. |
| Integrity | UI copy, Today counts, source counts, MW, dates, buyers, and conclusions derive from real accepted data. Missing or disputed values say so; a Signal or Prospect does not inherit the Lead mockup's completed numbers. |

### Tier-aware display

- **Signal:** Show the dated source, project or organization, why power may be needed, next discovery question. Unknown MW, utility status, start, or duration stay unknown. No implied gap calculation.
- **Prospect:** Show supported power requirement and the independent evidence that suitable supply may be late or insufficient. Name the missing facts required for Lead.
- **Lead:** Show supported remaining MW range, start window, duration range, explained supply gap, likely buying organization or role, and one next action. Open the sources and assumptions on demand.

The **Today** surface reflects actual newly discovered, promoted, materially changed, or closed opportunities. A failed source refresh, unchanged item, or reprocessed document cannot create a fresh-change count. A visible route to source health remains available through the menu; failures and overdue runs must not be hidden.

### Implementation handoff

Use the screenshots as visual targets, this file for interaction and state behavior, and the PRD for product/data requirements. Mock screenshots use fictional Prairie Ridge Campus and Northstar Commissioning. They are never seed records or production claims. Use the supplied brand image as a visual reference for the Aperture; produce a real SVG or other accessible vector from approved source assets when implementing the UI rather than embedding screenshot pixels as a logo.

The owner has frozen this direction. Change it only upon a new explicit design decision. Routine responsive adaptation, accessibility fixes, and factual field corrections consistent with this canon do not constitute a change of direction.
