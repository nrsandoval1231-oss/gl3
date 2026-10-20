# DigitalOcean + Cloudflare deployment

One droplet runs the API, worker and web containers. DigitalOcean Managed PostgreSQL holds the data. Spaces holds nightly dumps and, later, permitted source artifacts. A Cloudflare Tunnel is the only ingress; the droplet publishes no ports. ntfy pushes health to Nick's phone.

## Resources (create once)

| Resource | Setting |
|---|---|
| Droplet | Ubuntu 24.04, 2 vCPU / 4 GB, Docker installed, firewall: inbound SSH only |
| Managed PostgreSQL | Version 18 if offered, else 17; trusted source = the droplet; daily backups on |
| Spaces bucket | Private, e.g. `gridlens-artifacts`; access key scoped to that bucket |
| Cloudflare Tunnel | Public hostname `gridlens.<domain>` → `http://web:8080`; add a Cloudflare Access policy for Nick's email |
| ntfy | Private topic name; subscribe in the phone app |

## Install on the droplet

```bash
sudo git clone https://github.com/nrsandoval1231-oss/gl3.git /opt/gridlens
cd /opt/gridlens
sudo cp deploy/digitalocean/env.prod.example .env.prod && sudo chmod 600 .env.prod
sudo nano .env.prod   # fill every value
sudo docker compose -f deploy/digitalocean/compose.prod.yaml --env-file .env.prod up -d --build
sudo cp deploy/digitalocean/systemd/* /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now gridlens-collect.timer gridlens-alert.timer gridlens-backup.timer
sudo /opt/gridlens/deploy/digitalocean/gridlens-run.sh alert   # phone should buzz
```

`WORKER_AUTO_REFRESH=true` keeps the always-on worker planning each source at its own cadence (hourly news, daily permits anchored to 07:00 America/Chicago) and planning missing-fact research. The 07:00 timer is an independent, idempotent trigger for the same due ledger: if the worker planner stalls, the daily run still happens and a failure alerts.

## Update

```bash
cd /opt/gridlens && sudo git pull
sudo docker compose -f deploy/digitalocean/compose.prod.yaml --env-file .env.prod up -d --build
```

## Restore procedure (Requirement 36)

1. Create a new empty database in the managed cluster (`gridlens_restore`).
2. Download the dump: `aws s3 cp s3://$SPACES_BUCKET/backups/<file>.dump . --endpoint-url https://$SPACES_REGION.digitaloceanspaces.com`
3. `pg_restore --no-owner --dbname "<restore URL>" <file>.dump`
4. Point a one-off API container at it (`DATABASE_URL=<restore URL>`), run `alembic upgrade head` and `alembic check`, and confirm `/health/ready` plus record counts.
5. To cut over, change `DATABASE_URL` in `.env.prod` and `up -d`.

The managed cluster's own point-in-time backups are a second path. Record each restore drill with date and counts in `docs/operations/`.

## Alerts

- 08:30 and 18:00 America/Chicago: always one push. "collection healthy" or a list of failed/overdue sources, stale worker, overdue collection, or terminal job/interpretation failures (jobs from the last 48 hours).
- A failed collection or backup run triggers an immediate alert run.
- No morning push means the droplet, timer, or ntfy path is down.

## Existing Infisical runtime identity and Jev

Secrets live in Infisical: project `06ded1a4-5c85-426a-a833-d40358529795`,
environment slug `dev`, path `/`. Expected secret names are `TYPESAFE_API_KEY`
and `OPENAI_API_KEY`. Optional controlled Firecrawl acquisition also uses
`FIRECRAWL_API_KEY` when that provider is configured and authorized. Compose forwards
all three names to the API, worker, and
migration containers the same way (`${NAME:-}`); neither goes in the web image or
in any file.

The application reads `TYPESAFE_API_KEY` from its process environment through
`Settings`; it does not contact Infisical. Settings are cached on first use.
Compose's service `env_file: ../../.env.prod` reads a file, not the invoking
shell's environment. The explicit backend `environment` mapping now forwards
an Infisical-injected `TYPESAFE_API_KEY` into API, worker, and migration containers.
It also preserves an existing Compose `--env-file` value when there is no host
override. No key belongs in the web image or build arguments.

Use the **existing** authenticated Infisical CLI identity on the deployment host.
Set `INFISICAL_PROJECT_ID`, `INFISICAL_ENVIRONMENT` (environment slug), and
`INFISICAL_SECRET_PATH` (folder path) to the actual GL3 binding. These are routing
metadata, not credentials. The wrapper deliberately has no guessed defaults.
Confirm in Infisical that this identity can read the existing secret named
`TYPESAFE_API_KEY` at that binding, including any existing secret reference/import.
Do not create another key, export secrets to `.env.prod`, or print secret values.
The existing identity must also be available to the user running Docker/systemd;
interactive CLI access under a different Unix user does not establish that.

For Jev-enabled installs and **every update/recreation** of backend containers,
replace the unwrapped Compose startup above with:

```bash
cd /opt/gridlens
./deploy/digitalocean/with-infisical.sh \
  docker compose -f deploy/digitalocean/compose.prod.yaml --env-file .env.prod \
  up -d --build
```

Run this as the already-authorized deployment user. Avoid wrapping it in `sudo`
that discards the injected environment or changes the CLI identity. A restart
alone does not update a container's environment: recreate API/worker after the
binding changes. Do not use `docker inspect`, `printenv`, `set -x`, or unredacted
`docker compose config` to diagnose secrets.

Scheduled source collection only enqueues work; the persistent worker performs
intelligence using its startup environment. `gridlens-run.sh collect` and `alert`
now let Compose load `.env.prod` directly, preserving any injected host override.
Only the backup path sources the file for its existing backup-specific variables.
For other one-off intelligence commands, use the same wrapper around Compose.
Infisical unavailability during provisioning fails the wrapper; it does not stop
already-running ingestion containers. A runtime missing/rejected Jev key or
provider outage retains evidence and records REVIEW without promoting a tier.

Inspect the **running worker's** injected settings without a provider call:

```bash
docker compose -f deploy/digitalocean/compose.prod.yaml --env-file .env.prod \
  exec -T worker uv run python -m gridlens.intelligence.jev_health
```

Append `--probe` for exactly one authenticated request with a 12-second HTTP
operation timeout and no retries. This verifies the pinned model and all six
typed response dimensions; it writes no evidence, decisions, or database rows.
Repeat in `api` to check that container separately. A CLI subprocess checks its
container environment, not a previously cached settings object in another process.
The diagnostic prints only provider/model, credential presence, status, request
count, and scope. It exits nonzero on failure. Statuses:

| Status | Meaning |
|---|---|
| `missing_credentials` | Key absent, empty, or whitespace; no request made |
| `not_checked` | Key present; no request requested |
| `available` | Authenticated response and model/dimensions validated |
| `authentication_failed` | Provider returned 401 or 403; no retry |
| `provider_unavailable` | Transport failure, timeout, 429, or 5xx |
| `request_rejected` | Other unsuccessful HTTP status; no retry |
| `malformed_response` | Invalid JSON/model/typed dimensions; no retry |

Normal adjudication retries transient failures at most three times, retaining
existing per-attempt research budget accounting. Persisted decisions now carry
the failure category instead of a combined malformed/unavailable status; the
existing `missing_api_key` decision status remains compatible. Error bodies,
credentials, and raw provider exceptions are not recorded. Existing idempotency
and explicit error retry behavior are unchanged. `JEV_ENABLED` controls the
separate EvidenceJudge shadow path, not this Signal/pursuit adjudicator.

The repository cannot establish the actual Infisical project/environment/folder,
identity permissions, or deployed container state. Those must be checked with
existing host access. Passing local injection tests is not live Jev acceptance.
