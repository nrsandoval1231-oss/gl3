# Deployment artifacts

Files under `deploy/` are implementation/build artifacts or alternate deployment preparation. They are not a verified production runbook. The October 20 read-only host observation reported prebuilt images under `/opt/gridlens/releases/<tag>`, `/etc/gridlens/compose.app.yaml`, and `/etc/gridlens/runtime.env`; the approved command and secret-injection context remain unknown.

Use [operations status](../docs/operations/README.md) for the production hold, observed host paths, backup/restore evidence, and gaps. Use [local runtime](../docs/operations/local-runtime.md) for the local native or Compose development setup. `deploy/digitalocean/README.md` is retained as alternate preparation only and explicitly is not to be executed against the observed host.

Production deploy, rollback, restore, and cutover commands have not been verified. No settings or production state were changed by this documentation work.
