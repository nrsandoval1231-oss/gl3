# GridLens brand — canonical 2026-10-23

**Status:** owner approved. This supersedes the former Aperture, gold, orange, Signal Blue, and ABC Diatype brand directions.

## Source of truth
The final seven-color brand board approved in the October 23 design conversation is the visual master. The generated mockup is a *visual reference*, not a production-grade vector master. Do not approximate or substitute a new symbol and claim exact equivalence. Before replacing binary assets, trace and visually verify the precise G/hidden-L segmentation against the approved reference.

## Seven colors
- harbor navy: `#0B1F33`
- deep slate: `#23384C`
- slate steel: `#607F88`
- sea cliff: `#6E909A`
- driftwood gray: `#A9B4BC`
- fog: `#E8ECEF`
- graphite: `#1E2A33`

## Typography
- Sora: headings and display.
- Inter: body, tables, and UI.
- Approved wordmark: thin, generously spaced uppercase GRID LENS as shown in the visual reference. Do not reuse the old bold title treatment.

## Product interface rules
- White/light product workspace, horizontal top navigation only; **no left toolbar/sidebar**.
- KPI cards and quick filters across top; dense ranked opportunity table left; selected customer intelligence details right.
- No maps, photography, or decorative images in the product UI.
- Use the approved navy/slate/steel palette consistently, with restrained status colors and accessible contrast.
- Keep existing data, routes, functionality, and evidence intact during the rebrand.

## Required migration before merging
1. Replace legacy `web/public/brand/aperture-*`, `lockup-*`, favicon and app icons with traced, reviewed final mark variants, including dark/light SVG and raster exports.
2. Update `tools/brand/generate.py`, manifest and all component logo references; remove obsolete artifacts only after references are migrated.
3. Audit `web/src/styles`, components, docs and tests for conflicting colors, font declarations, old logo references, sidebar layout and photographic UI.
4. Verify pixel-level logo fidelity, both light and dark treatments, typography licenses, responsive screenshots, contrast, builds and tests.
5. Remove contradictory brand instructions from active docs; archive historical decisions rather than deleting unrelated evidence.

**Migration warning:** Existing legacy SVG/PNG assets remain in the repository until exact replacement assets are ready. This branch establishes the canonical spec and token foundation, not a completed visual rebrand.
