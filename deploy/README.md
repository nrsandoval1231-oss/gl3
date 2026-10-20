# Deployment artifacts

Files under this directory are repository deployment preparations. They are not the observed production entry point. The October 20 read-only host inspection found prebuilt images launched from `/etc/gridlens/compose.app.yaml`, runtime configuration at `/etc/gridlens/runtime.env`, and release directories under `/opt/gridlens/releases/<tag>`. See [operations status](../docs/operations/README.md) for the dated observation and limits.

The host's active procedure, release operator, credentials flow and rollback were not validated by this packet. Do not use the repository clone plus `.env.prod` examples in `digitalocean/README.md` as instructions for the observed production host. Those files describe an alternate preparation path and may contain stale assumptions.

For local development only, see the root [setup guide](../README.md) and [Compose preparation](../deploy/digitalocean/README.md). Deployment remains on hold pending the owner-authorized release process, exact-candidate checks, runtime verification and open product acceptance gates. This documentation change does not alter production or hosting settings.
