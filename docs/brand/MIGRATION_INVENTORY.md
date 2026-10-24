# GridLens brand migration inventory

Inspected 2026-10-23 against PR #115 head `b3d020d34893d384073b3489e5171b0ef0a57343`.
Status at initial inspection: **blocked on missing artwork**.

Update: the owner subsequently attached the 1280 × 960 board. The missing-image blocker is resolved; exact vector geometry/wordmark approval remains open. This inventory and JSON scan are baseline evidence, not current-state claims. See `VALIDATION.md` for delivery status.

## Source material gate

The current task supplied no accessible image attachment. PR #115 has no comments
or attached reference in its description. The branch contains October 1/20/21
reference artwork, but no October 23 seven-color G/hidden-L board or verified SVG
master. Neither `/workspace/library-files` nor `/workspace/shared` contains the
missing board. Existing files named `brand-system.webp` and
`brand-system-v1-owner.jpg` are earlier references, not evidence of the final mark.

Required owner input: attach the approved final board (full resolution), or supply
an accessible link to the exact image/vector master. Supply original color values
if available. The seven values in the directive remain implementation candidates;
they have not been reconciled against the missing image. Wordmark outlines,
segmentation boundaries, proportions, and light/dark treatment cannot be verified.
Do not generate substitute geometry, assert fidelity, or merge this PR.

## Dependency inventory and migration order

| Surface | Existing dependency / conflict | Required replacement and verification |
| --- | --- | --- |
| Header | `web/src/features/workspace/Workspace.tsx`, `/brand/lockup-horizontal-white.svg` | Verified dark-surface lockup; check all routed screens |
| Login | `web/src/features/auth/LoginPage.tsx`, `/brand/lockup-pursuits-v3.svg` | Verified light-surface lockup; retain authentication behavior |
| Browser | `web/index.html`, old theme color and `/brand/favicon.svg` | New favicon family and canonical theme metadata |
| Installation | `web/public/site.webmanifest`, old colors and `icon-192.png`, `icon-512.png` | New icons, maskable icon, manifest wiring and touch metadata |
| Public library | `web/public/brand/`, all existing Aperture, lockup, app-icon, favicon and raster families | Preserve historical evidence outside public assets; replace dependencies before removing orphans |
| Generation | `tools/brand/generate.py` | Replace hard-coded Aperture polygons, gradients, old palette and DejaVu Bold outlines with verified master inputs and canonical tokens |
| Typography | CSS names Inter/Sora but no bundled font files or font dependencies | Licensed distributable font assets and notices; verify actual browser font loading |
| Styles | `app.css`, `workspace.css`, `pursuits.css` and other active styles | Reconcile hard-coded old colors; semantic tokens, accessible contrast, responsive layout |
| Token compatibility | `brand-tokens.css` aliases old token names to new values | Migrate consumers, remove obsolete aliases after reference scan; naming alone is not evidence of old displayed colors |
| Broken CSS | Variable expressions with hexadecimal alpha suffixes, e.g. `var(--gl-harbor-navy)0a` | Valid explicit semantic shadow colors; browser validation |
| Instructions | `AGENTS.md` still requires Aperture preservation and October 20 application identity | Archive superseded instructions; align active rules with October 23 directive |
| Reference authority | `docs/design/references/README.md` still calls October 21 current | Clearly label old references historical; record hash/provenance for new supplied source |
| Product navigation | UI canon requests destinations not present in current header | Preserve functional routes; do not invent product screens from screenshot labels |
| Layout | Current workspace styles contain multiple historical override layers | Verify horizontal navigation, left dense table/right intelligence panel and phone reflow without changing workflows |
| Business / merchandise | No verified final production artwork | Build requested templates, placement specifications, clear space and print-proof caveats from verified master |
| Documentation | No final production guidelines or PDF | Generate from verified sources; distinguish owner specifications from provisional measurements |

`MIGRATION_SCAN.json` records file/line matches for legacy geometry/font names,
known superseded hex values, invalid CSS variable alpha suffixes and brand URLs.
It is a baseline search inventory, not proof that every match should be removed
or that unlisted colors are approved. Scan all sources again after replacement.

## Acceptance still outstanding

- Exact source comparison and explicit resolution of uncertain G/L edges.
- Seven-color reconciliation, semantic status/interaction tokens and AA contrast.
- Complete SVG/PNG/WebP/icon/social and physical production exports.
- Deterministic generator, missing-source failures, dimensions/transparency checks.
- All route integration and preservation of data, controls and workflows.
- Legacy reference cleanup after dependency replacement and successful builds.
- Frontend build, existing repository tests, and actual browser screenshots at
  1648 × 928, 1440 × 900, 1280 × 800, 768 × 1024 and 390 × 844.
- Final brand guidelines, PDF, visual comparison and permitted merge checks.

This inspection changes no runtime code or assets. No build, test, screenshot,
logo approval, merge or deployment is claimed. Keep PR #115 open as a draft.
