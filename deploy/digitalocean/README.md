# DigitalOcean deployment preparation only

**This is not the production runbook. Do not execute these steps against the observed host.** This folder describes an alternate Git-clone/`.env.prod`/managed-PostgreSQL deployment proposal. The October 20 host observation instead reported prebuilt images under `/opt/gridlens/releases/<tag>`, `/etc/gridlens/compose.app.yaml`, and `/etc/gridlens/runtime.env`.

The approved secret-injection shell context, deployment command, rollback command, installed backup unit/script, retention policy, and repeatable restore command are not established by the sanitized host receipts. A prior `docker compose config` attempt failed because the shell did not receive `TYPESAFE_API_KEY`; do not diagnose that as running-service failure or work around it by printing/creating secret files.

Use [operations status](../../docs/operations/README.md) as the sole production authority. It records the deployment hold, verified observations, exact UNKNOWN items, and evidence required before a future owner-authorized release. This historical preparation document was shortened during the October 20 documentation repair; the prior bytes are archived at [the documentation inventory index](../../.agent/archive/AUDIT-20261020/DOCUMENTATION-INVENTORY-20261020.md).
