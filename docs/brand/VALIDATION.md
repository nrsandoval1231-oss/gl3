# GridLens brand implementation validation

Execution: October 23–24, 2026. Delivery branch: `brand/gridlens-seven-color-canon`, PR #115.

**Status: implementation delivered for visual acceptance; not approved for merge or production.**
The supplied board resolves the earlier missing-image blocker. Exact G/L contours,
flat segmentation of the shaded mark and wordmark lettering remain owner-review
items. See [provenance](REFERENCE_PROVENANCE.json),
[candidate comparison](../../web/public/brand/review/comparison.png) and
[guidelines](GRIDLENS_BRAND_GUIDELINES.md).

## Delivered

- 216 inventoried assets: editable/outlined SVGs; light/dark/one-ink lockups;
  primary corporate tagline and compact application versions; transparent
  PNG/lossless WebP at four master widths; favicon, Apple, PWA, maskable and social
  exports; business and physical-production templates.
- Locally served SIL-OFL Sora/Inter variable fonts and license notices.
- Canonical palette and semantic surface, text, interaction, navigation, table,
  status and logo tokens. Brand colors are transcribed from printed labels.
- Light horizontal navigation, compact real API briefing counts, customer and
  power-need tables, contextual intelligence, responsive reflow and current logo
  integration in the shared shell and login. Existing route/selection/filter/
  pagination/research/evidence/account actions remain in place.
- Complete Markdown guidelines and reproducible four-page visual PDF.
- Former public identity files moved to the explicitly historical archive after
  dependencies were replaced and a frontend build succeeded. Old generation
  code is archived as text; active generation uses only the new path master.
- CI asset-validation job and browser regression configuration using a local
  Chromium executable. No duplicate PR, merge, production deployment or provider
  activation.

`git diff b3d020d -- backend` is empty. No backend logic, database schema, ingestion,
qualification or research-provider implementation changed.

## Asset and build checks

- `python tools/brand/validate.py`: PASS for all 216 files. Checks source/output
  SHA-256, XML/viewBox validity, absence of raster-in-SVG, canonical SVG fills,
  raster dimensions/alpha, duplicate names, unmanaged assets, referenced paths,
  licensed font presence, primitive/semantic/status CSS consistency, undefined
  brand variables and eight AA text/background pairs.
- Full repeated generation produced byte-identical assets, font conversions,
  generated CSS and PDF. The final platform-template changes were also generated
  twice with an identical manifest. Native export dependencies are recorded in
  `tools/brand/requirements.txt`; this is reproducibility in the tested Linux
  environment, not a claim about arbitrary Cairo versions.
- Normal production generation correctly refuses unapproved geometry/wordmark.
  The explicit `--review-candidate` flag produces review exports. A temporary
  source-free checkout fails with a clear missing-token-source error.
- `npm ci --prefix web`, then `npm --prefix web run build`: PASS with locked Vite
  6.4.4. The initial preinstalled 6.4.3 was replaced before final verification.
- Python compilation and `git diff --check`: PASS. PDFs are explicitly binary;
  font-license trailing whitespace was normalized without changing license text.

## Browser verification

Chromium 151.0.7922.173; local Playwright 1.63.0. The app and fonts run locally.

The first broad mocked-API run passed 189 checks, skipped one and failed one old
assertion requiring flex rows. That obsolete presentation assertion was replaced
with the requested semantic table expectation; its complete workflow test then
passed. A targeted 18-test visual/customer/login run passed. The real session,
reload and sign-out test passed against a disposable local API/database.

The locked-dependency broad rerun passed 189 checks, skipped one and exposed a
contact-correction test race: an instantaneous form count ran before canonical
readback remounted the detail. The test now waits for the new closed form, retaining
all correction/retraction assertions. The complete buying-chain file passed 12 tests
on recheck, and the corrected case passed three consecutive runs. No production
contact-workflow code changed. The final login suite passed all eight checks after
fixing internal phone-form width and adding an internal-boundary assertion. These
results are passing coverage across runs, not a claim of a single final clean
combined browser run; combined CI remains required.

Saved and visually reviewed actual viewport captures:

| Viewport | Capture | Observed behavior |
| --- | --- | --- |
| 1648 × 928 | [Workspace](screenshots/workspace-1648x928.png) | Horizontal navigation, briefing, table left, intelligence right |
| 1440 × 900 | [Workspace](screenshots/workspace-1440x900.png) | Split panes, readable customer identity and functional controls |
| 1280 × 800 | [Workspace](screenshots/workspace-1280x800.png) | Identity wrap corrected; no page overflow |
| 768 × 1024 | [Workspace](screenshots/workspace-768x1024.png) | Table and intelligence stack; horizontal navigation retained |
| 390 × 844 | [Workspace](screenshots/workspace-390x844.png) | Selected detail, horizontal navigation and existing mobile workflow action |

Additional [desktop login](screenshots/login-1440x900.png) and
[phone login](screenshots/login-390x844.png) captures verify the shared identity.

These are actual browser renders of explicitly synthetic regression fixtures,
not live-data acceptance. Comparison to the board is compositional, not a pixel
parity claim: supported routes/fields replace fictional board labels and metrics.
The original image has no accessible local byte file for an overlay. The candidate
logo has also been inspected on light, dark and one-ink comparison backgrounds.

## Existing backend tests

The original environment lacked PostgreSQL. A dedicated local Postgres 16 container
was created for tests; no existing or production database was used. Its fsync and
synchronous_commit were disabled for test speed; these runs are not durability or
production-operation proof. Four file
shards used separate disposable databases. Results:

| Shard | Result |
| --- | --- |
| 0 | 578 passed |
| 1 | 739 passed, 13 failed, 7 passing subtests |
| 2 | 666 passed |
| 3 | 755 passed, 1 skipped |

The thirteen failures were rechecked using **normal full-suite collection**:
`pytest backend/tests -k 'test_real_orm_projection_requires_exact_public_project_support or test_dirty_revision_maintenance_prepares_near_boundary_and_preserves_parity'`
returned **13 passed, 2739 deselected**. Twelve failures were SQLite PostgreSQL-default
compilation failures: the file-shard harness omitted compiler registrations supplied
by other collected test modules. The remaining saved-browse near-boundary test
reported `published` instead of `prepared` during the sharded run and passed both
its isolated and full-collection rechecks; no backend fix is claimed.

`uv sync --locked --extra dev` reconciled two preinstalled dependency versions
(Uvicorn and pypdf). The subsequent full unit run returned **1693 passed, 1 skipped,
7 passing subtests**. All 2,751 non-skipped backend tests have passing coverage across
the shards and rechecks, but this is **not a single clean full-suite run under the
final lockfile**. CI remains the final combined-suite gate. Live-provider acceptance
tests requiring retained real-source records were not represented as fixture proof.

## Remaining acceptance

1. Owner comparison/approval of the actual G/L edges, hidden-L color boundary,
   diagonal return and outlined wordmark. Approval flags remain false.
2. Combined CI and application acceptance before merge. Do not infer approval from
   structural asset checks or mocked browser screenshots.
3. Physical vendor proofing/stitch-out and original print profile specifications
   before merchandise release; no professional Pantone/CMYK equivalence is claimed.

PR #115 remains draft and unmerged. Production deployment is not authorized.
