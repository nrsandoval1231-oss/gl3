# Deployment and rollback gate

No deployment, merge, production data write, credential change or paid-provider activation was performed or authorized for this repair. This is a proposed release procedure, subject to final integrated validation and owner release authorization.

## Before release

1. Pin the reviewed source commit and immutable API/worker/web images. Require the complete backend, frontend, API-contract, migration and independent-review receipts for that candidate.
2. Back up PostgreSQL and verify restoration in an isolated database. Preserve evidence, corrections, import batches, project/company links and the suppression ledger. Record deployed revision and image digests.
3. Apply the additive migration through `0045_contact_suppressions` before starting the new API and workers. It creates an append-only suppression ledger; it does not rewrite existing project/evidence records. Use the existing deployment mechanism and connection settings.
4. Confirm the existing production territory, budgets, provider gates and credentials remain unchanged. Do not activate licensed/paid providers as part of this release.
5. Verify authenticated opportunity, company, search and contact-history reads, suppressed-contact handling, worker retry/fencing, source health, and desktop/mobile views against an authorized isolated production snapshot before any live acceptance.
6. Resolve the missing 25-existing-opportunity acceptance cohort. Publish measured denominators and unknowns; workbook rows and synthetic fixtures cannot close this gate. Imported workbook promotion requires separate explicit authorization and row-level reconciliation review.

## Rollback

Keep the database at the additive schema revision. Migration downgrade refuses to remove a populated suppression ledger. Never discard privacy history to make an older image start.

An application rollback must use a compatible image that applies the suppression ledger to every exposed contact surface. If none is available, keep contact surfaces and refresh workers disabled until a compatible image is prepared. Merely restoring the pre-repair image can expose suppressed contact details and is not an acceptable rollback. See [the suppression rollback contract](../../operations/contact-suppression-rollback.md).

Retain failed-release artifacts and diagnostic logs. Recover using the verified backup only through the established recovery procedure, with reconciliation of any newer privacy events before contact surfaces reopen. No automated downgrade or workbook promotion is part of this plan.

## Local migration evidence

Fresh installation, repeated upgrade, and Alembic metadata drift checks passed in disposable PostgreSQL databases. An isolated clone of the retained Austin acquisition upgraded from `0041_evidence_packages` through `0045_contact_suppressions`; all 660 original rows across 65 existing tables retained identical canonical JSON digests. Six intervening additive tables were empty. This is local migration evidence, not a production backup/restore rehearsal.
