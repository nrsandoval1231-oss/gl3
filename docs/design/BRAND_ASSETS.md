# GridLens brand assets · v1.0

This is the production asset set for the approved Aperture identity. The owner-provided brand sheet is preserved at [`references/brand-system.webp`](references/brand-system.webp); generated assets live in [`../../web/public/brand/`](../../web/public/brand/). Source geometry and export settings live in [`../../tools/brand/generate.py`](../../tools/brand/generate.py).

## Core identity

The Aperture consists of four engineered pieces around an unpainted central diamond and narrow vertical openings. Keep its proportions, negative space, and upright orientation intact. The SVG is the master for new sizes; use PNG or WebP where vectors are unsupported. The outlined wordmark is self-contained in the lockup SVGs.

| Need | Asset |
| --- | --- |
| Main logo on a light surface | `lockup-horizontal-navy.svg` |
| Main logo on a dark surface | `lockup-horizontal-white.svg` |
| Narrow compositions | `lockup-stacked-navy.svg`, `lockup-stacked-white.svg` |
| Standalone symbol outside the product UI | `aperture-gradient.svg`, `aperture-navy.svg`, `aperture-white.svg` |
| Dark and light application icon | `app-icon-dark.svg`, `app-icon-light.svg` |
| Browser favicon | `favicon.svg`, `favicon.ico`, `favicon-{16,32,48}.png` |
| Installed app and touch icon | `icon-192.png`, `icon-512.png`, `apple-touch-icon-180.png` |
| Raster sharing and presentation | `*-1024.png`, `*-1024.webp`, `lockup-horizontal-*-1100.png`, `lockup-horizontal-*-1100.webp` |

The app icon is a square with its own navy or white background. The standalone mark and lockups have transparent backgrounds. `site.webmanifest` points to the installable icons.

## Application rules

The October 20, 2026 approved Pursuit Workspace uses [`lockup-pursuits-v3.svg`](../../web/public/brand/lockup-pursuits-v3.svg) as its application lockup, rendered at 156px wide on desktop, 134px on tablet, and 114px on phone. Keep the original Aperture source masters listed above intact. The v3 application surface adds silver `#E7EAED` and a restrained orange accent; these are application-only tokens, not edits to the original brand palette.

- In the product interface, place the October 20 application lockup **once in the top-left header**. The original navy/white lockups remain available for their established non-application surfaces. Do not repeat the symbol in panels, empty states, or buttons. Favicons and installed app icons are separate system surfaces.
- The original identity palette remains Deep Current `#101F2D`, GridLens Navy `#17324A`, Steel Blue `#395A75`, Atmosphere `#6F879D`, Mist `#D5DEE5`, Ice `#F3F6F7`, and White `#FFFFFF`. The October 20 application adds its own navy ink, silver surface, and restrained orange accent in [`brand.tokens.json`](brand.tokens.json), without changing those original values.
- The reference's Signal Blue `#3B82F6` remains outside the application palette. Use the tokens in [`brand.tokens.json`](brand.tokens.json) and [`../../web/src/styles/brand-tokens.css`](../../web/src/styles/brand-tokens.css).
- Maintain clear space of at least a quarter of the symbol's width around the mark or lockup. Prefer the horizontal lockup at 140 px width or larger. At tiny sizes, switch to the dedicated favicon rather than shrinking the full logo.
- Never stretch, rotate, recolor individual pieces, fill the negative space, apply a glow, or put the dark logo on a dark field.

## Typography and reproducibility

The brand sheet specifies ABC Diatype. That commercial font is not included in this repository. The supplied lockup exports use outlined DejaVu Sans Bold as a self-contained approximation, so the wordmark will not depend on installed fonts. Replace the wordmark outline from an authorized ABC Diatype source when the licensed master is available; the Aperture geometry and palette remain the same. The DejaVu font license is included in `../../web/public/brand/FONT-LICENSE.txt`.

Run `python3 tools/brand/generate.py` from the repository root with Pillow, NumPy, fontTools and DejaVu Sans Bold installed to regenerate the exports. The generator does not need any old GridLens code.
