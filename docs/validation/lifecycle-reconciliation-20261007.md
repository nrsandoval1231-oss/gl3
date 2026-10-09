# Lifecycle reconciliation inventory — 2026-10-07

This is a read-only inventory of retained lifecycle events whose support changes under the current evidence-bound policy. It does not update lifecycle events, interpretations, projections, evidence, or power-need tiers.

## Reproduce safely

Run from `backend` with the locked Python 3.11 environment. The root-level script refuses any database other than the explicitly authorized loopback copy `gl3audit_corpus_test` on port `55437`, runs in a read-only repeatable-read transaction, and compares row counts and content hashes before and after its inventory query.

```powershell
$env:LIFECYCLE_INVENTORY_DATABASE_URL='postgresql+psycopg://gl3audit@127.0.0.1:55437/gl3audit_corpus_test'
uv run python ..\scripts\reconcile_lifecycle_inventory.py `
  --baseline 'C:\path\to\corpus-baseline-inventory.json' `
  --output '..\.artifacts\audit-20261007\lifecycle-reconciliation-inventory.json'
```

The checked-in script contains no credentials. The connection uses PostgreSQL `default_transaction_read_only=on` and `SET TRANSACTION ... READ ONLY`; the final artifact at `.agent/artifacts/GL3-AUDIT-A2-R1/lifecycle-reconciliation-inventory.json` records every suspect with event, observation, evidence, and project IDs, exact evidence hash, source URL, retained/proposed classifications, support reason, and projection effect.

## Retained-corpus result

The owner baseline identifies backup SHA-256 `828beace65cd2b06182f30e4713857656a993d3969c8cbecb02e6ee40ff8a886`. The authorized copy had these row counts both before and after the script: 938 lifecycle events, 938 lifecycle projections, 16,960 evidence rows, 16,921 interpretations, 16,921 observations, and 1,168 projects. All six table content hashes were identical before and after the run. The full hashes and baseline comparison are preserved in `.agent/artifacts/GL3-AUDIT-A2-R1/lifecycle-reconciliation-inventory.json`.

The current read-only inventory identifies nine retained events across nine projects whose stored event is unsupported by current evidence-bound policy; all nine currently match their projection. Four Georgia draft Title V permit records (QTS ATL3, Apex Site Solutions, TADG ATL02 / Ellenwood, and QTS Fayetteville I) have no unambiguous achieved lifecycle milestone in their exact bound evidence. A proposed facility, received application, or draft permit does not establish campus construction; a separately stated, achieved campus event remains eligible. The current policy proposes no event for those four records.

The other five records are dated permit evidence from official Austin and Chicago adapters. The evidence supports three `building_permit_issued` and two `electrical_permit_issued` events at `permitting`; it does not establish physical construction or electrical buildout. Their stored classifications are electrical buildout for Austin 2026-036762 EP, Austin 2025-155325 EP, and Austin 2025-155325 BP; construction for Austin 2026-036762 BP and Chicago permit 3451848. The inventory carries the exact project/event/observation/evidence identifiers, URLs, hashes, proposed stages, and reasons for all nine records. These are classification assessments only; no retained row was changed. Table counts and content hashes were identical before and after the read-only run.

## Correction procedure

If an owner later authorizes correction, first reproduce this inventory against a fresh protected copy and compare its backup hash and row fingerprints. Review each cited source and project binding individually; preserve evidence and interpretation history. Apply a correction only in a separately authorized disposable migration/test database, rebuild the affected projection through the lifecycle service, and verify event history, projection, identity/hash binding, and commercial tier invariance. Re-run the inventory and compare all before/after table counts and hashes. Do not execute a correction against this retained-corpus copy or production as part of this packet.
