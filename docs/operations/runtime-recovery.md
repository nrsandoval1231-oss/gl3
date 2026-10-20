# Local database and source recovery commands

This is a **local development** procedure. It is not the production deployment or backup/restore runbook. Production commands and rollback are UNKNOWN; use the [operations authority](README.md), which maintains the deployment hold.

## Read-only status

Run from the repository root after configuring the ignored local `.env` and starting only the local PostgreSQL cluster described in [local runtime](local-runtime.md):

```powershell
uv run --project backend python -m gridlens.jobs.runtime status
```

The command reads registry drift, source health, counts, and queue backlog. It does not probe the database's service health, retrieve sources, or prove a current source refresh. A saved old success is not a fresh check.

## Registry reconciliation

`reconcile` writes registry definitions to the configured database while preserving saved health, jobs, evidence, and project history. Run it only against the disposable local application database after verifying the effective database target. Never run it merely to fix a report or against a production/retained database.

```powershell
uv run --project backend python -m gridlens.jobs.runtime reconcile
```

Unregistered rows are reported and retained. The command does not delete sources or history.

## Explicit source check

`check` can enqueue work and make real external HTTP requests. It can also write observations and evidence. Only run a specifically approved source against the local database, after checking source access/retention rules and the active environment. The following example is a shape, not authorization to fetch either named source:

```powershell
uv run --project backend python -m gridlens.jobs.runtime check `
  --source <approved-source-id>
```

The command validates all IDs before mutation and attempts each selected source at most once. Active jobs are reused; retry backoff and leases can defer work. Exit 1 means at least one selected check failed or was deferred; exit 2 means invalid input or runtime setup failure. A deferred result does not mean a new request occurred.

After a successful, authorized check, repeat only if a replay was explicitly requested. Compare durable observation/evidence identities, source health, and the relevant opportunity history. Do not treat unchanged rows as new discoveries. Parser failures must remain visible and must not overwrite last accepted data.

For source schedule and worker behavior as implementation contracts, see [source scheduling proof](source-scheduling-proof.md) and [source controls and worker health](source-controls-and-worker-health.md). Those detailed engineering records do not establish production's scheduler or seven-day health.
