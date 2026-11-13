# DigitalOcean deployment preparation only

**This is not the production runbook. Do not execute these steps against the observed host.** This folder describes an alternate Git-clone/`.env.prod`/managed-PostgreSQL deployment proposal. The November 2 release receipt confirms production continues to use prebuilt immutable images under `/opt/gridlens/releases/<tag>`, protected Compose/runtime configuration and the established host controller.

The November 2 release completed through the existing protected process and is documented in [operations status](../../docs/operations/README.md) and the [production release record](../../docs/validation/production-release-20261102.md). The private controller and host configuration remain protected; this alternate preparation does not supply their credentials, command surface or authority. A prior `docker compose config` attempt that lacked `TYPESAFE_API_KEY` is historical and is not evidence of current running-service failure. Do not print, create or replace secret files to make this proposal work.

The repository's newer wrapper companion has not been established as installed on the production host. Use the established protected controller only under separately authorized release procedures. This historical preparation document was shortened during the October 20 documentation repair; the prior bytes are archived at [the documentation inventory index](../../.agent/archive/AUDIT-20261020/DOCUMENTATION-INVENTORY-20261020.md).

## Network change note (2026-11-13)

`compose.prod.yaml` now pins the default network to `172.28.0.0/24` so `TRUSTED_PROXY_CIDRS` matches the nginx-to-API hop. An existing `gridlens_default` network created without that subnet cannot be reused: stop the stack, remove the old network (`docker network rm gridlens_default`) and run `compose up` again. If the host already uses that range, change the subnet and `TRUSTED_PROXY_CIDRS` together. Confirm after deploy that two different clients get separate login buckets; this assumes cloudflared forwards the real client address in `X-Forwarded-For`.
