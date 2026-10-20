# Operations and deployment status

Observed 2026-10-20. This is the operational status entry point. Follow [local runtime](local-runtime.md) for development commands, [runtime recovery](runtime-recovery.md) for safe application-database checks, and [delivery status](../delivery/milestones.md) for product gates.

## Production observation

A read-only host inspection on October 20, 2026, 18:29–18:39 UTC found the running API, web, worker and browse containers using image tag `title02-802cbb4055c5`; PostgreSQL reported schema `0032`. The application database was named `gridlens_restore_20261014`. No rename or cleanup is part of this documentation work.

The source registry contained 26 entries: 19 had a recent successful check. Boston, Chicago and Georgia last succeeded October 14. California CEQAnet, Texas TCEQ NSR and Houston permits had no successful check; TDLR was registry-disabled. The worker heartbeat was fresh. There were no queued or running jobs; historical job totals were 228 failed and 662 succeeded. Logical calls showed 9 COMPLETED and 1 RECONCILED, with zero active budget slots. Saved browse input and generation revisions both equaled 15663 and the generation was valid through 00:00 UTC October 21. `POWER_NEED_BRIEF` was the only enabled intelligence contract, with its existing 8/day and $50/month limits.

These are point-in-time database/container observations, not proof of authenticated user workflow or seven consecutive scheduled collection cycles. Production image, database, schedules, source state and controls were not changed by this documentation repair.

## Backups and actual host layout

The host reported a `gridlens-db-backup.timer`; its service reported success. A daily dump at 2026-10-20 17:04 UTC was 18,811,807 bytes. A pre-deploy dump dated 15:19 UTC was copied off-host and its SHA-256 matched `b74583c19cf03fc6a290d736d4aa942388157cece729358da7c6f2e834d742e1`. That copy was restored to a private local PostgreSQL 18 database, yielding 1,620 projects, 18,016 evidence versions and 16,694 observations. This proves one copy and restore; scheduled off-host retention remains UNKNOWN.

The inspected runtime uses `/etc/gridlens/compose.app.yaml` and `/etc/gridlens/runtime.env`, prebuilt images and `/opt/gridlens/releases/<tag>`. Repository Git-clone, `.env.prod`, and managed-Postgres instructions describe a separate preparation path and are not the observed production layout. Do not follow those preparation steps as production commands.

## Governance proposal

At inspection, GitHub main was unprotected and no rulesets were configured. Governance authority is absent, so no settings were changed. Proposed owner-applied rule: require the backend and web checks to pass on the latest main candidate; block force pushes and branch deletion; allow an explicit, auditable owner override. Verify settings after the owner authorizes application.

## Evidence and procedures

The source registry and its coverage limits are summarized in [source coverage](../sources/coverage.md). Historical deployment proposals and receipts remain historical; see the [documentation index](../README.md#documentation-authorities-and-history). Do not infer a current deployment from a manifest, CI run, backup timer, or earlier dated report.
