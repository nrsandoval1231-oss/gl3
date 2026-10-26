# Commercial release and rollback plan

Status: HOLD. The owner authorizes PR126 merge and production deployment only after commercial, engineering, independent-review and operational gates pass. PR126 has not been merged into main, and no deployment or production data mutation has occurred during this repair. Missing production access is separate from the demonstrated commercial failures.

## Required sequence

1. Pin the final reviewed commit, complete regression receipts, actual cohort measurements and independent acceptance. The current cohort does not demonstrate the required named contacts or temporary-power actionability; do not waive these failures because engineering tests pass.
2. Use the established DigitalOcean host procedure, including `/etc/gridlens/compose.app.yaml`, protected Infisical configuration and immutable `/opt/gridlens/releases` artifacts. Do not substitute the alternate deployment proposal or create replacement infrastructure.
3. Through established authenticated access, inventory deployed SHA, image digests, schema revision and canonical/import/contact/evidence counts. Record current territory, provider gates, budgets and schedules without exporting secrets. These production observations are currently unavailable.
4. Take a fresh logical backup and prove restoration in isolation. Verify evidence, privacy suppressions, corrections, source versions and import-event history. An available DigitalOcean infrastructure backup alone is not a logical restore rehearsal.
5. Validate upgrade from the observed production revision through `0046_import_meta_reparse` against the restored copy. Compare retained row contents and constraints, repeat the upgrade, and verify application compatibility before production execution.
6. After all gates pass, finalize and merge PR126, build immutable artifacts from the merged SHA, migrate through the established procedure, and start compatible API, worker and web services. Do not activate paid providers or promote unverified workbook assertions as part of migration.
7. Rebuild required saved-browse projections using the exact deployed API/worker artifact before accepting traffic readiness. Verify the published generation matches the runtime policy fingerprint, input revision and validity window; matching database counts alone is insufficient. A local mixed-source browser setup produced an expected 503 because an older-backend projection fingerprint differed from the current API.
8. Verify authenticated services, scheduled work, retry/fencing, source health, suppression behavior, retained data counts and desktop/mobile commercial scenarios. Record the deployed SHA and observed results. A frontend HTML response from a health-looking URL does not prove backend readiness.

## Workbook boundary

The retained four batches contain 4,520 source rows and 4,520 inactive activation records, with no canonical projects in that staging database. Isolated test authorization does not establish safe production promotion. Production activation requires row-level reconciliation, independent source support and the coordinated release safeguards. Original workbook bytes are absent in the resumed workspace: metadata-reparse tests prove software behavior, not recovered real targets.

## Rollback and retained history

Prefer a compatible application rollback while retaining the additive schema and all new history. Migration 0045 refuses to drop a populated suppression ledger. An older application that exposes suppressed contacts is not a valid rollback; disable contact surfaces and refresh workers if no compatible image exists. Follow the [suppression contract](../../operations/contact-suppression-rollback.md).

Migration 0046 refuses to downgrade when metadata-reparse receipts exist. Do not delete immutable receipts to bypass the guard. Retain the schema, or use a verified pre-reparse backup only through the established recovery procedure with explicit reconciliation of subsequent evidence, privacy and import events. Never discard newer production intelligence silently.

Local [0046 preservation evidence](workbook-metadata-reparse-validation.md) proves retained source-table equality in an isolated clone, idempotent upgrade and guarded downgrade. It does not establish production backup validity, current production revision or post-deployment preservation. Those checks remain unperformed.

## Access evidence

The [access receipt](../system-repair-20261026/release-access.json) records an active DigitalOcean droplet and available infrastructure backup, but no authenticated host execution, production API session, current schema or deployed SHA. Credentials must be supplied through an established secure environment or authenticated connection, never chat or repository files. No credential changes or access-control bypass are part of this plan.
