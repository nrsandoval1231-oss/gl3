# Operations authority

This page is the only current summary for production, deployment, rollback, and backup/restore. **Production remains on hold.** The latest documented production observation spans October 20, 2026, 18:28:48–18:50:41 UTC. It is a read-only snapshot, not a release authorization or a runbook. See the [sanitized observation receipt](observations/2026-10-20-production-readonly.md).

## Observed host and runtime

The host was reported to use `/etc/gridlens/compose.app.yaml`, `/etc/gridlens/runtime.env`, prebuilt images, and `/opt/gridlens/releases/<tag>`. The reported running tag was `title02-802cbb4055c5`; schema `0032`; database `gridlens_restore_20261014`. See the receipt for exact source-state and count details.

Production credentials are injected into the host command context. A controller's `docker compose config` attempt failed because `TYPESAFE_API_KEY` was not injected into that shell; that is a shell-context failure, not evidence that the running containers failed. No secret files or values are part of the documentation. The inspected receipts do not establish the approved deploy wrapper/command, release selection procedure, secret-manager identity, or required host-side preflight.

## Deployment and rollback: not yet an executable procedure

No production deploy or rollback command is documented here because the authorized release command and secret-injection context have not been verified. The `deploy/digitalocean/` clone/`.env.prod`/managed-Postgres instructions are alternate preparation and have been withdrawn as production instructions. Do not run them against the observed host.

Before an owner-authorized release, the release operator must identify the approved host wrapper and secret context without printing values; freeze and record the exact image/tag and repository candidate; verify a fresh backup and isolated restore; confirm forward-schema compatibility; save the exact active compose/runtime metadata using the approved protected procedure; and record preflight, post-release health, worker, source and authenticated-save evidence. These steps describe required evidence, not commands. The deployment hold remains until the owner authorizes a concrete candidate and procedure.

Rollback is also not executable from the available evidence. The presence of timestamped compose copies and release directories does not prove which is a compatible prior release or how secrets are injected. Do not downgrade migrations, delete tables, switch database names, or restart an older worker without proving forward-schema compatibility and resolving in-flight work. The previous accepted image, exact rollback command, compatibility result, and cutover criteria are UNKNOWN.

## Backup and restore: measured evidence and gaps

On October 20, a `gridlens-db-backup.timer` existed and its service reported success. The 17:04 UTC daily dump was 18,811,807 bytes. A pre-deploy dump from 15:19 UTC was copied off-host; its recorded SHA-256 is `b74583c19cf03fc6a290d736d4aa942388157cece729358da7c6f2e834d742e1`. The copy restored into a private local PostgreSQL 18 database and reported 1,620 projects, 18,016 evidence versions and 16,694 observations.

This proves one off-host copy and one isolated restore. It does not prove the daily dump was copied off-host, scheduled retention, backup alerting, repeatable restore instructions, recovery time, or production cutover. The receipts do not contain the installed unit/service/script bodies, retention configuration, or repeatable restore command. Those steps remain UNKNOWN; no command is invented here. Do not restore over or rename the live database.

For an authorized future drill, retain the source dump read-only, verify its digest and archive readability, restore only to a new isolated PostgreSQL 18 target with dispatch/providers disabled, compare schema and the agreed row-count set, preserve logs/digests, and destroy the target only under an explicit cleanup record. Production cutover, credential injection, and rollback require the missing approved runbook and owner authorization.

## Current state and detailed guides

- [Dated observation receipt](observations/2026-10-20-production-readonly.md): sanitized source files, SHA-256 digests and exact October 20 counts.
- [Runtime configuration](runtime-configuration.md): settings defaults and what they control, verified against `backend/src/gridlens/settings.py`.
- [Local runtime](local-runtime.md): clean-checkout loopback PostgreSQL, separate app/test databases, and local env loading.
- [Runtime recovery](runtime-recovery.md): local-only read-only inspection and guarded database/source operations.
- [Delivery status](../delivery/milestones.md): PRD release gates; all A–E remain open in this observation.

Other `docs/operations/` pages describe particular code paths or dated proofs (source scheduling, saved browse, buying chain, pursuit research, local restore, and intelligence). They do not authorize production commands. Their original dated text is preserved; see the [documentation inventory and archive index](../../.agent/archive/AUDIT-20261020/DOCUMENTATION-INVENTORY-20261020.md).

GitHub branch protection was unconfigured at inspection. The owner has not authorized governance settings changes. The proposal is backend and web checks required on latest main, block force-push and deletion, with an explicit auditable owner override.
