# Historical database identity and backup proposal — October 20, 2026

This is a dated planning record, not an executable production procedure. The October 22 review integrates its useful risk analysis only. It authorizes no database rename, cleanup, backup transfer, credential installation, timer change or paid resource. The [operations authority](README.md), [dated observation](observations/2026-10-20-production-readonly.md) and [guarded local restore drill](local-restore-drill.md) supersede its operational steps.

## Observations and subsequent evidence

The original audit reported PostgreSQL database `gridlens_restore_20261014` as live production, an empty database named `gridlens`, and many other scratch databases. A disposable-looking name is not proof that a database can be removed. Preserve the live name and all other databases unless a separately authorized, exact-target operation proves ownership and references.

At the initial audit no GridLens backup timer was observed. A later October 20 observation recorded a timer, a successful dump, and one off-host copy restored into isolated local PostgreSQL 18. The initial proposed label/timer/restore steps must therefore not be treated as pending installation instructions. This dated evidence does not prove the current installed script body, scheduled off-host retention, present recovery readiness or present runtime.

## Recovery requirements retained from the proposal

- Identify the exact current source database and approved command/secret context without printing credentials. A database name or historical row count alone is insufficient.
- Preserve and checksum an authorized recovery checkpoint. `pg_restore --list` proves archive readability only; it does not prove successful restore or application recovery.
- Restore only to a newly created isolated target proven absent beforehand. Never drop or reuse a fixed scratch name, terminate unrelated connections, rename production, or restore over the live database as part of a drill.
- Verify the restored schema and full agreed data/history/accounting invariants, with dispatch and providers disabled. Preserve logs and failures. Cleanup requires explicit ownership and scope; do not delete older backups based only on filename age.
- Record local retention, independent off-host retention and restore evidence separately. Droplet backup observations do not establish logical restore consistency or a scheduled off-host policy. Spaces, new credentials and data transfers require their own authorization.

The original proposal, including its superseded executable commands, is preserved in [commit d794070](https://github.com/nrsandoval1231-oss/gl3/blob/d794070840d3d1d152d6d255e3987f22dba9c3c1/docs/operations/production-database-and-backups.md). Its fixed-name database drop, live rename, automatic age-based deletion and archive-listing-as-verification claims are withdrawn. Do not execute them. No host change was made by this documentation repair.
