# DigitalOcean deployment preparation only

**This is not the production runbook. Do not execute these steps against the observed host.** This folder describes an alternate Git-clone/`.env.prod`/managed-PostgreSQL deployment proposal. The November 2 release receipt confirms production continues to use prebuilt immutable images under `/opt/gridlens/releases/<tag>`, protected Compose/runtime configuration and the established host controller.

The November 2 release completed through the existing protected process and is documented in [operations status](../../docs/operations/README.md) and the [production release record](../../docs/validation/production-release-20261102.md). The private controller and host configuration remain protected; this alternate preparation does not supply their credentials, command surface or authority. A prior `docker compose config` attempt that lacked `TYPESAFE_API_KEY` is historical and is not evidence of current running-service failure. Do not print, create or replace secret files to make this proposal work.

The repository's newer wrapper companion has not been established as installed on the production host. Use the established protected controller only under separately authorized release procedures. This historical preparation document was shortened during the October 20 documentation repair; the prior bytes are archived at [the documentation inventory index](../../.agent/archive/AUDIT-20261020/DOCUMENTATION-INVENTORY-20261020.md).

## Frontend build identity

Before an authorized frontend image build, export `GRIDLENS_BUILD_SHA` from
`git rev-parse HEAD` in the exact clean source checkout being built. The production
web-image build requires a 40-character hexadecimal value and identifies its
deployment environment as production. Compose configuration remains usable without
frontend metadata for backend-only collection, alerting and migration commands.
The account dropdown reads this build identity; it does not query the running Git checkout.
The application version comes from `web/package.json` unless `VITE_APP_VERSION` is
explicitly supplied. Set `GRIDLENS_DEPLOYED_AT` only when the deployment process
knows the actual deployment timestamp (ISO 8601); absent timestamps display Unavailable.
A build timestamp is not a deployment timestamp. Local builds identify themselves as
Local build and derive their commit with Git when available.

This wiring does not build, merge or deploy an image by itself.
