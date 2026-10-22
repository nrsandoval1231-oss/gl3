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

The October21 [UI canon](UI_CANON.md) restores the dark navy header and selective Signal Blue accents from the owner screenshot. Use an existing light-on-dark Aperture lockup once at the top left. Preserve all original masters; do not regenerate or approximate a new logo. Silver/orange v3 presentation rules are superseded for this workspace.

The palette is Deep Current #101F2D, GridLens Navy #17324A, Steel Blue #395A75, Atmosphere #6F879D, Mist #D5DEE5, Ice #F3F6F7, White #FFFFFF and selective Signal Blue #3B82F6. See [tokens](brand.tokens.json).

## Typography and reproducibility

The brand sheet specifies ABC Diatype. That commercial font is not included in this repository. The supplied lockup exports use outlined DejaVu Sans Bold as a self-contained approximation, so the wordmark will not depend on installed fonts. Replace the wordmark outline from an authorized ABC Diatype source when the licensed master is available; the Aperture geometry and palette remain the same. The DejaVu font license is included in `../../web/public/brand/FONT-LICENSE.txt`.

Run `python3 tools/brand/generate.py` from the repository root with Pillow, NumPy, fontTools and DejaVu Sans Bold installed to regenerate the exports. The generator does not need any old GridLens code.
