# GridLens brand guidelines · 2.0 review candidate

**Release status: NOT approved for production or print.** The October 23 owner board is the visual authority. Its printed seven-color labels and Sora/Inter families are transcribed. The vector trace and wordmark spacing remain review candidates; no exact reproduction claim is made. This guide documents the implementation and production requirements so review can resolve concrete artwork, not a verbal proposal.

## Positioning

GridLens provides commercial intelligence for constrained power: real power, real projects, before they become obvious. Product content must distinguish evidence, inference and unknowns. Do not reproduce the fictional metrics, customer names or out-of-region locations from the board as operational data.

## Construction and fidelity gate

`tools/brand/masters/symbol.svg` is the editable path source, in a 200 × 200 coordinate system. Three closed paths describe the rounded upper G, continuous integrated lower/left return, and diagonal right return. The L is part of the silhouette and color segmentation, never a separately inserted letter. No raster is embedded in these SVGs.

The supplied board is 1280 × 960. Its large logo occupies roughly 132 × 128 pixels and includes shading and highlights. The trace uses flat palette fills in accordance with the implementation directive. The exact curvature at the upper-left shoulder and lower-left return, junction at the horizontal bar, diagonal fold, hidden-L boundary and wordmark tracking cannot be certified from this image alone. Compare `web/public/brand/review/comparison.svg` with the supplied board, especially the large header mark and icon-only sample. The comparison sheet shows the candidate on both backgrounds; it is not a pixel overlay because the source attachment is not available as a local byte file.

The outlined wordmark uses licensed Inter Light (weight 300), uppercase GRIDLENS with deliberate tracking. This is a candidate reconstruction, not a claim that the board's wordmark was typeset in Inter. Owner confirmation or original wordmark paths are required. Do not change the approval flags merely to pass generation. Record approval, exact source hash and reviewer in the PR before setting them true.

## Clear space and minimum sizes

Provisional production rules pending visual/vendor proof: preserve at least 0.2 symbol heights on all sides; no content inside the negative space. Core symbol exports include 20 units of margin on a 240-unit canvas: add external clear space when placing them. Horizontal lockups need additional external clear space as well.

Use the symbol at 24 CSS px or larger, horizontal lockup at 160 CSS px or larger, and stacked at 100 CSS px or larger. Favicons at 16/32/48 px are explicit small-size exceptions and need optical review. Print symbol minimum 10 mm; embroidery minimum 34 mm, subject to actual stitch-out. Never squeeze, crop, rotate or independently move the three symbol paths.

## Color specifications

These are sRGB hexadecimal labels read from the board, not image-sampled averages.

| Token | sRGB | Use |
| --- | --- | --- |
| Harbor Navy | #0B1F33 | Primary identity, buttons, emphasis |
| Deep Slate | #23384C | Secondary text, hover and borders needing stronger contrast |
| Slate Steel | #607F88 | Symbol segmentation and non-text accents |
| Sea Cliff | #6E909A | Dark logo accent and decorative highlights |
| Driftwood Gray | #A9B4BC | Borders and dividers |
| Fog | #E8ECEF | Selected rows and secondary surfaces |
| Graphite | #1E2A33 | Primary text |
| White (neutral) | #FFFFFF | Application surfaces and reverse artwork |

Do not use Sea Cliff or Slate Steel for small body text on white. Semantic text uses Graphite/Deep Slate/Harbor Navy; primary button text uses white on navy. Existing accessible danger, warning and success colors are semantic exceptions, paired with textual status and never used as additional identity colors. Token definitions live in `docs/design/brand.tokens.json`; generated CSS must not be edited independently.

No Pantone equivalence or professionally verified CMYK specification is available. Supply sRGB artwork with embedded/reference values to the printer; request conversion for their actual ink, stock and ICC profile and approve a physical proof. Do not invent a universal CMYK recipe.

## Typography

Sora: major and display headings. Inter: interface, labels, forms, tables and body. Licensed variable TTF masters, WOFF2 runtime files and SIL Open Font License notices live in `web/public/fonts/`. Sources: Google Fonts `ofl/sora` and `ofl/inter`. Font files are pinned in Git; runtime does not depend on a font CDN. The font license allows distribution; preserve license notices when handing assets to vendors.

Do not use a substitute and describe it as exact. The outlined candidate wordmark has no runtime font dependency. Source wordmark parameters are in the generator for reproducibility, pending owner review.

## Light, dark and incorrect use

Use `horizontal-light.svg` on white/Fog and `horizontal-dark.svg` on Harbor Navy. White and navy variants use one ink with unchanged geometry. Do not invert arbitrary fills, add gold, introduce gradients, use the archived identity, stretch proportions, separate the L, fill negative space or place the mark over a photograph. Embroidery uses the one-ink navy/white variants; vendor simplification requires approval.

## Application system

One light horizontal top navigation; no navigation rail. Retain existing Opportunities, Research, Signals and Operations routes and account/project workflows. Customer accounts are a real table on the left, selected intelligence on the right. Tablet and phone reflow for readable content; selection/history behavior remains intact. No decorative maps or photography. Compact metrics display only existing backend values. Do not add fake routes or financial KPIs to mimic the board.

Semantic tokens cover surfaces, text hierarchy, dividers, buttons, interactive/hover/focus/selection, table headings, navigation, statuses and light/dark logos. `tools/brand/validate.py` checks representative AA text pairs; browser acceptance must also check actual rendering and focus states.

## Production artwork and placement

All templates in `web/public/brand/production/` are editable SVGs with physical millimetre dimensions and outlined text. They are clean artwork, not mockup photos, and all inherit the unapproved geometry status. Placeholder names/titles must be replaced. Templates contain no printer-specific bleed or cut marks: obtain the vendor dieline, add 3 mm bleed where requested, and keep content at least 5 mm from trim. Do not scale a page template to force a different trim size.

| File | Canvas / intended placement | Production instruction |
| --- | --- | --- |
| business-card.svg | 89 × 51 mm | US card; 8 mm inset, replace name/title; confirm trim/bleed |
| letterhead.svg | A4 210 × 297 mm | 18 mm inset; keep body copy below identity |
| email-signature.html | HTML text template | Replace name/title/email/phone; use absolute hosted logo URL only where client supports it |
| presentation-cover.svg | 320 × 180 mm, 16:9 | Replace presentation title; preserve proportions |
| proposal-cover.svg | A4 | 20 mm left inset; replace proposal title |
| notebook-cover.svg | 148 × 210 mm | 70 mm symbol; verify binding and vendor trim |
| tshirt-placement.svg | 300 × 350 mm placement area | 80 mm mark centered at x=150 mm, y=110 mm; placement area is not a garment cut pattern |
| polo-embroidery.svg | 80 × 60 mm placement area | 40 mm mark; locate on left chest using vendor garment measurement |
| hat-embroidery.svg | 100 × 50 mm placement area | 34 mm mark centered; confirm seam and curved-panel clearance |
| tumbler-mark.svg | 60 × 100 mm imprint area | 40 mm mark; obtain actual cylindrical wrap/dieline |
| signage.svg | 1000 × 300 mm artwork area | Outlined one-ink lockup; obtain substrate and mounting drawing |

Embroidery: keep one ink, no shading; target minimum stitched stroke/gap of 1.5 mm and inspect the integrated return at a physical stitch-out. These are provisional shop guidelines, not stitch files. The diagonal currently narrows to a point: vendor proof must establish legibility without silently altering geometry. A professional digitizer must supply machine-specific stitch data. Screen print, vinyl and engraving also require material proofs. No final vendor release before logo approval.

## Asset directory

- `logos/`: primary horizontal with tagline, compact application horizontal, stacked with tagline, symbol and outlined wordmark; light, dark, navy, white.
- `masters/`: editable SVG symbol copy; authoritative editable source in `tools/brand/masters/`.
- `rasters/`: transparent PNG and lossless WebP at 256, 512, 1024 and 2048 px widths, aspect ratio preserved.
- `icons/`: SVG/ICO, PNG/WebP 16/32/48, Apple 180, PWA 192/512 and maskable 512. Maskable mark stays inside the safe circle.
- `social/`: 1200 × 630 artwork and opaque exports.
- `production/`: business and merchandise templates.
- `review/`: light/dark/one-ink comparison sheet.
- `asset-manifest.json`: complete inventory, dimensions, transparency requirements, SHA-256 and approval state.

Historical assets/generator live outside the public tree in `docs/design/archive/pre-seven-color/`. Never serve that archive as current branding.

## Regeneration and validation

From repository root, Python 3.11 or newer with Cairo system libraries:

```sh
python3 -m venv .venv-brand
.venv-brand/bin/pip install -r tools/brand/requirements.txt
.venv-brand/bin/python tools/brand/generate.py --review-candidate
.venv-brand/bin/python tools/brand/validate.py
.venv-brand/bin/python tools/brand/guide.py
npm --prefix web run build
cd web && npx playwright test -c playwright.brand.config.ts
```

The review flag is required while the master is unverified. Normal generation intentionally fails until both geometry and wordmark are approved. Missing required sources fail before export. Exports are deterministic in the pinned dependency environment; regenerate twice and compare hashes before release. `GRIDLENS_BROWSER_PATH` selects the installed Chromium executable for local regression checks.

## Versioning and change control

Keep tokens, masters, font sources, generated manifest and outputs in the same reviewed commit. Geometry, segmentation, palette and wordmark changes require owner visual approval. Record source provenance and unresolved questions; do not convert a candidate to approved by inference. PR #115 remains the delivery vehicle. Merge only after logo fidelity, tests, browser review and application acceptance pass. Deployment is a separate authorization.
