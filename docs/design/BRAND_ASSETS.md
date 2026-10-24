# GridLens brand assets · seven-color system

The October 23 owner-supplied G/hidden-L board supersedes earlier identity directions.
Printed palette labels are recorded in `brand.tokens.json`; fonts are locally distributed Sora and Inter with SIL Open Font License notices.

**Owner acceptance recorded 2026-10-24.** The owner explicitly accepted the existing G/hidden-L geometry and wordmark in this chat. No additional comparison or independent graphic verification is claimed. The generated artwork and all 216 asset hashes are unchanged. Vendor proofs apply to later physical production and are separate from dashboard integration acceptance.

See [brand guidelines](../brand/GRIDLENS_BRAND_GUIDELINES.md), [visual PDF](../brand/GRIDLENS_BRAND_GUIDE.pdf) and [candidate comparison](../../web/public/brand/review/comparison.svg).

| Surface | Asset |
| --- | --- |
| Light app / login | `/brand/logos/horizontal-light.svg` |
| Dark surface | `/brand/logos/horizontal-dark.svg` |
| Standalone | `/brand/logos/symbol-light.svg` |
| One ink | `/brand/logos/symbol-navy.svg`, `/brand/logos/symbol-white.svg` |
| Browser | `/brand/icons/favicon.svg`, `favicon.ico`, `favicon-{16,32,48}.png` |
| Installation | `/brand/icons/pwa-{192,512}.png`, `pwa-maskable-512.png`, `apple-touch-icon.png` |
| Social | `/brand/social/sharing.png` |
| Physical/business | `web/public/brand/production/` |

Complete outputs and integrity hashes are in `web/public/brand/asset-manifest.json`. Editable geometry is `tools/brand/masters/symbol.svg`; wordmark outlining is reproducible from the pinned Inter source in the generator. No embedded raster substitutes for vector geometry.

Regenerate with `python tools/brand/generate.py --review-candidate`, then `python tools/brand/validate.py` and `python tools/brand/guide.py` using dependencies from `tools/brand/requirements.txt`. Historical masters and generator are preserved outside the active public pipeline in `docs/design/archive/pre-seven-color/`.

Owner correction, October 24: the logo uses two colors only (one ink for monochrome). Both G segments share the primary color; the integrated L uses the secondary. The seven-color application palette remains canonical. Owner acceptance of the existing geometry and wordmark was recorded October 24, 2026, in `brand.tokens.json`; no additional comparison or independent graphic verification is claimed.
