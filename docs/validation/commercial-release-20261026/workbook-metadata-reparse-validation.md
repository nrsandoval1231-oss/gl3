# Workbook metadata-only replay validation

Migration `0046_import_meta_reparse` adds an append-only `metadata_reparsed` audit event for hyperlink metadata recovered by a newer parser on the same workbook bytes. The integration tests use generated `.xlsx` files because the four original workbook attachments are unavailable in this checkout. This validates the recovery capability but does not recover targets from the retained workbook rows or establish whether their visible `Link` cells had hyperlinks.

The replay path accepts only generated hyperlink sidecars after checking identical file hash, row identity, displayed raw cells, normalized values, errors, and mapping report. It preserves the original batch and rows. Event targets remain unverified hints; non-HTTP or malformed targets are retained with an unsupported-target status and are never visited. Replay idempotency uses the existing per-file advisory lock. Same-parser metadata drift and removal of previously captured targets fail closed. Exact replays and same metadata under a later parser revision add no duplicate event.

## Test results

Ran against the dedicated isolated database `gridlens_release_reparse_functional_test` with the corpus branch source path:

```text
pytest -q backend/tests/integration/test_external_imports.py backend/tests/unit/test_workbook_import.py
45 passed in 30.82s
```

The suite includes a same-bytes parser-v1 staging to parser-v2 metadata replay, stable original row/report values and inactive activation, repeat idempotency, changed raw/mapping rejection, same-revision target drift and full target removal rejection, same fingerprint under a newer revision, and guarded rollback. The synthetic workbook has ten user headers named like the reserved metadata key, forcing the generated sidecar key to `#11`; the test confirms those user cells are retained. It also includes HTTP, `mailto:`, and malformed URL targets. New hints are labeled `UNVERIFIED`; no canonical project, power need, or evidence records are written.

Ruff and `git diff --check` passed for the changed source, test, and migration files.

## Migration and source-history preservation

Created isolated clone `gridlens_release_reparse_clone3_test` from `gridlens_repair_workbook_actual_test`, then ran:

```text
alembic upgrade head
```

The clone advanced from `0045_contact_suppressions` to `0046_import_meta_reparse`. Before inserting a test-only receipt, its source tables matched the source database exactly:

| Table | Rows | SHA-256 of sorted full-row snapshot |
| --- | ---: | --- |
| `external_import_batches` | 4 | `20f29036a8cb144cf6854d4f065e8ebcdb50bdfec1da4e109ee833b8033c0401` |
| `external_import_rows` | 4,520 | `47a989497de714d0086a74a77bf4ae212b816b20377d3f738222c98bd1b32437` |
| `external_import_activations` | 4,520 | `4374efb49950f4d1352c2562035def5ed4826bcdcf26b78573ad9c92866e6741` |
| `external_import_events` | 4 | `2e578e573fd117b1d1de407896cc2674d64f3b950548ac1f84117a771b1ae596` |

The clone and source also both have zero canonical projects, power needs, and evidence records. A repeat `alembic upgrade head` completed successfully without running another migration step. After inserting one valid test-only metadata receipt in the disposable clone, `alembic downgrade 0045_contact_suppressions` exited with the intended error before any DDL: `metadata receipts are immutable; retain this schema for application rollback or restore a verified pre-reparse backup`. The clone remained at `0046_import_meta_reparse`; the downgrade guard does not delete or rewrite receipts.

Neither the workbook source database nor production was modified. The original attachments are still required to recover any actual workbook hyperlink targets.
